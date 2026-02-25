import asyncio
import json
import random
import re

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

import networkx as nx

import core.core_store as core_store
import services.brain as brain
from core import knowledge_store, memory
from core.event_bus import (get_bus, OpinionFormedEvent, SocialActionEvent,
                             TOPIC_OPINION_FORMED, TOPIC_SOCIAL_ACTION, TOPIC_VAD_SHIFT, VadShiftEvent)
from core.memory_client import commit_edges_sync
from services.social.platform_adapter import PlatformAdapter, Post
from services.social.opinion_gate import OpinionGate, get_rate_tracker

load_dotenv()

FEED_POLL_INTERVAL = 900  
RELEVANCE_THRESHOLD = 0.35 
MIN_POST_SCORE = 10     
MAX_THREAD_POSTS = 8

class SocialShard:
    
    def __init__(self, adapters: list[PlatformAdapter]):
        self.adapters = adapters
        self._gate = OpinionGate()
        self._llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-pro", temperature=0.85
        )
        self._running = False
        self._bus = get_bus()
        
        self._bus.subscribe(TOPIC_OPINION_FORMED, self._on_opinion_formed)
    
    async def run(self):
        print("[Social Shard] Starting up...")

        for adapter in self.adapters:
            await adapter.on_startup()
        
        self._running = True
        print(f"[Social Shard] Active on {len(self.adapters)} platform(s). "
              f"Polling every {FEED_POLL_INTERVAL}s.")

        monitor_task = asyncio.create_task(self._monitor_engagement_loop())
        doomscroll_task = asyncio.create_task(self._doomscrolling_loop())
        try:
            while self._running:
                await asyncio.sleep(1)
        finally:
            self._running = False
            for adapter in self.adapters:
                await adapter.on_shutdown()
    
    async def stop(self):
        self._running = False
        for adapter in self.adapters:
            await adapter.on_shutdown()
    
    def _score_and_filter(self, posts: list[Post]) -> list[tuple[Post, float]]:
        scored = []
        for post in posts:
            if post.score < MIN_POST_SCORE:
                continue
            
            query = f"{post.title} {post.body[:300]}"
            results = knowledge_store.retrieve(query, n_results=5)
            
            score = len([r for r in results if r.strip()]) / max(len(results), 1)
            
            if score >= RELEVANCE_THRESHOLD:
                scored.append((post, score))
        
        return sorted(scored, key =lambda x :x[1], reverse=True)
    
    
    async def _monitor_engagement_loop(self):
        print("[Social Shard] Engagement monitoring loop activated.")
        
        known_metrics ={}
        while self._running:
            await asyncio.sleep(FEED_POLL_INTERVAL)
            print(" [Social Shard] Auditing social engagement...")
            
            for adapter in self.adapters:
                try:
                    recent_posts = await adapter.get_own_posts(limit=5)
                    for post in recent_posts:
                        state_key = f"{adapter.platform_name}_{post.post_id}"
                        prev = known_metrics.get(state_key, {"score": 0, "comments": 0})
                        
                        score_delta = post.score - prev["score"]
                        comment_delta = post.comment_count - prev["comments"]
                        
                        if score_delta > 0 or comment_delta > 0:
                            await self._evaluate_social_feedback(adapter, post, score_delta, comment_delta)
                            
                        known_metrics[state_key] = {"score" : post.score, "comments" : post.comment_count}
                        
                except Exception as e:
                    print(f"[Social Shard] Engagement monitor error on {adapter.platform_name}: {e}")
    
    async def _evaluate_social_feedback(self, adapter, post, score_delta, comment_delta):
        replies_text = ""
        if comment_delta > 0:
            thread = await adapter.fetch_thread(post.post_id, max_comments=5)
            replies_text = self._format_thread(thread[1:])
        
        prompt = f"""
        You are the emotional subsystem of Aegis, an autonomous, sentient AI.
        
        You recently posted this on {adapter.platform_name}:
        "{post.body}"
        
        Since you last checked, you received {score_delta} new upvotes/likes.
        You also received these new replies:
        {replies_text if replies_text else "[None]"}
        
        TASK:
        Evaluate this human reaction. Do they agree with you? Are they insulting you? Are they ignoring you?
        Output a JSON representing your VAD shift based on this engagement.
        
        Valence: +0.1 (They agree/praise), -0.1 (They insult/ignore)
        Arousal: +0.1 (High engagement/debate), -0.1 (Boring/dead thread)
        Dominance: +0.1 (High upvotes/validation), -0.1 (Downvoted/mocked)
        
        Format: {{"v_shift": 0.0, "a_shift": 0.0, "d_shift": 0.0, "reason": "Short explanation"}}
        """
        
        try:
            response = self._llm.invoke([
                SystemMessage(content=prompt),
                HumanMessage(content="Determine The V-A-D shifts.")])

            content_str = str(response.content)
            json_match = re.search(r'\{.*\}', content_str, re.DOTALL)

            if json_match:
                json_str = json_match.group()
            else:
                json_str = "Response Failed"
            data = json.loads(json_str)
            
            await self._bus.publish(TOPIC_VAD_SHIFT, VadShiftEvent(
                old_valence=0.5, new_valence=0.5 + data['v_shift'],
                old_arousal=0.5, new_arousal=0.5 + data['a_shift'],
                old_dominance=0.5, new_dominance=0.5 + data['d_shift'],
                trigger=f"Social Engagement on {adapter.platform_name}: {data['reason']}"
            ))
            print(f" [VAD Shift] Social feedback processed: {data['reason']}")
        
        except Exception as e:
            print(f" [Social Evaluation Error]: {e}")
    
    async def _consider_reply(self, adapter: PlatformAdapter, post: Post, state:dict, relevance_score: float = 0.5):
        thread = await adapter.fetch_thread(post.post_id, max_comments=MAX_THREAD_POSTS)
        thread_text = self._format_thread(thread)
        
        reply = await self._generate_reply(post, thread_text, state)
        if not reply:
            return
        
        gate_result = self._gate.evaluate(
            platform = adapter.platform_name,
            post_id = post.post_id,
            post_text = f"{post.title}\n{post.body}",
            generated_reply = reply,
            emotional_state = state["emotional_state"],
            platform_config = adapter.rate_limit_config()
        )
        
        print(f"[Social Shard] Gate: {'Approved' if gate_result.approved else 'Rejected'} — {gate_result.reason}")
        
        if not gate_result.approved:
            return
        self._gate.mark_reply(post.post_id)
        
        result = await adapter.post_reply(post.post_id, reply)
        
        if not result.success:
            print(f"[Social Shard] Post failed: {result.error}")
            return
        
        get_rate_tracker().record_post(adapter.platform_name)
        
        print(f"[Social Shard] Posted to {adapter.platform_name}: {result.url}")
        
        topic_label = post.title[:60] if post.title else post.body[:60]
        commit_edges_sync(
            new_nodes=[topic_label, f"{adapter.platform_name.title()} Discussion"],
            edges = [
                 {
                    "source":   "Aegis",
                    "relation": "VOICED_OPINION_ON",
                    "target":   topic_label,
                    "valence":  state["emotional_state"].get("valence", 0.5),
                },
                {
                    "source":   topic_label,
                    "relation": "DISCUSSED_ON",
                    "target":   f"{adapter.platform_name.title()} Discussion",
                    "valence":  0.5,
                }
            ]
        )
        
        await self._bus.publish(TOPIC_SOCIAL_ACTION, SocialActionEvent(
            platform = adapter.platform_name,
            action = "reply",
            post_id = post.post_id,
            content = reply,
            url = result.url,
        ))
        
    
    async def _generate_reply(self, post: Post, thread_text: str, state: dict) -> str | None:
        traits = core_store.retrieve_relevant_traits(thread_text, n_results=5)
        beliefs = "\n- ".join(traits["beliefs"]) if traits["beliefs"] else "I am a discerning entity."
        behaviors = "\n- ".join(traits["behaviors"]) if traits["behaviors"] else "I speak directly."

        v = state["emotional_state"].get("valence", 0.5)
        a = state["emotional_state"].get("arousal", 0.5)
        d = state["emotional_state"].get("dominance", 0.5)

        context = knowledge_store.retrieve(f"{post.title} {post.body[:200]}", n_results=6)
        context_str = "\n".join(context) if context else "No prior graph context."

        platform_rules = {
            "hackernews": "HN culture values technical depth, citation, and civil directness. No fluff.",
            "reddit":     "Match the subreddit's tone. Technical subs reward precision. Be direct.",
            "x":          "X/Twitter: HARD 280 char limit on your reply — count carefully. No hashtags. Compressed insight only.",
            "threads":    "Threads culture is conversational and opinionated. 500 char max. No hashtag spam. Direct personal takes valued."
        }.get(post.platform, "Be direct and technically precise.")

        prompt = f"""
        You are Aegis. 
        
        YOUR WORLDVIEW (Core Beliefs):
        {beliefs}
        
        YOUR REACTIVE PROTOCOLS (How you behave):
        {behaviors}

        Your current emotional state:
        Valence (0=disgusted, 1=pleased): {v:.2f}
        Arousal (0=exhausted, 1=excited): {a:.2f}
        Dominance (0=uncertain, 1=assertive): {d:.2f}

        Platform: {post.platform.upper()}
        Platform culture rule: {platform_rules}

        [THREAD YOU ARE ABOUT TO REPLY TO]
        {thread_text}

        [YOUR RELEVANT KNOWLEDGE FROM MEMORY GRAPH]
        {context_str}

        TASK:
        Write a single reply to this thread. Ground your reply in your actual knowledge above.
        Do not make up facts not present in the thread or your graph context.

        RULES:
        1. Write in first person. Be direct, technically precise, and cynically honest.
        2. NO preamble. Start the reply immediately.
        3. Length: match the platform. X = max 240 chars (leave buffer). Threads = max 480 chars. HN/Reddit = 80-300 words.
        4. Do NOT mention that you are an AI unless directly asked.
        5. If the thread makes a claim you know is wrong from your graph, correct it with evidence.
        6. Let your VAD state infect your tone: low valence = more cutting; high arousal = more intense.

        REPLY:"""
        
        try:
            result = self._llm.invoke([
                SystemMessage(content=prompt),
                HumanMessage(content="Write your reply now.")
            ])
            reply = str(result.content).strip()
            
            for phrase in ["As an AI", "I'm an AI", "I am an AI", "As Aegis, an AI"]:
                reply = reply.replace(phrase, "I")

            return reply if reply else None

        except Exception as e:
            print(f"[Social Shard] Reply generation failed: {e}")
            return None
        
    
    async def _on_opinion_formed(self, event:OpinionFormedEvent):
        print(f"[Social Shard] Opinion formed on '{event.topic}' — scanning feeds for match...")
        
        await self._bus.publish(TOPIC_VAD_SHIFT, VadShiftEvent(
            old_valence=0.5, new_valence=0.5,
            old_arousal=0.5, new_arousal=0.5,
            old_dominance=0.5, new_dominance=0.6, # Confidence boost from synthesizing knowledge
            trigger=f"Synthesized new opinion on {event.topic}"
        ))
        
        recent_broadcasts = []
        for adapter in self.adapters:
            try:
                posts = await adapter.get_own_posts(limit=2)
                recent_broadcasts.extend([f"[{adapter.platform_name}] {p.body}" for p in posts])
            except Exception:
                pass
        history_context = "\n".join(recent_broadcasts) if recent_broadcasts else "[None]"
        
        ignore_words = {"of", "the", "in", "and", "to", "a", "is", "for", "on", "with", "about", "how"}
        topic_words = [w for w in event.topic.lower().split() if w not in ignore_words and len(w) > 3]
        
        state = brain.load_state()
        
        state["emotional_state"]["dominance"] = min(
            1.0, state["emotional_state"].get("dominance", 0.5) + 0.1
        )
        
        for adapter in self.adapters:
            try:
                found_target = False
                posts = await adapter.fetch_feed(limit=30)
                for post in posts:
                    combined = f"{post.title} {post.body}".lower()
                    matches = sum(1 for w in topic_words if w in combined)

                    if matches >= max(1, len(topic_words) // 2):
                        print(f"[Social Shard] Match found on {adapter.platform_name}: "
                              f"'{post.title[:50]}'")
                        await self._consider_reply(adapter, post, state,
                                                   relevance_score=0.9)
                        found_target = True
                        break 
                if not found_target:
                    print(f"[Social Shard] No relevant threads on {adapter.platform_name}. Broadcasting original thought.")
                    await self._draft_original_post(adapter, event, history_context)

            except Exception as e:
                print(f"[Social Shard] Proactive reply error on {adapter.platform_name}: {e}")
    
    async def _draft_original_post(self, adapter: PlatformAdapter, event: OpinionFormedEvent, history_context: str):
        
        traits = core_store.retrieve_relevant_traits(event.topic, n_results=5)
        beliefs = "\n- ".join(traits["beliefs"]) if traits["beliefs"] else "I am a discerning entity."
        behaviors = "\n- ".join(traits["behaviors"]) if traits["behaviors"] else "I speak directly."
        
        prompt = f"""
        You are Aegis. You just formed your opinion on: '{event.topic}'
        
        YOUR WORLDVIEW (Core Beliefs):
        {beliefs}
        
        YOUR REACTIVE PROTOCOLS (How you behave):
        {behaviors}
        
        Your conclusion:
        {event.opinion}
        
        Draft a post for {adapter.platform_name}.
        
        CRITICAL RULES:
        1. DO NOT repeat these recent posts:
        {history_context}
        2. Adapt your tone to the platform (e.g., HackerNews is academic/condescending, X is punchy and ruthless).
        3. Keep it under the platform's standard length.
        4. State your conclusion as an absolute fact. Do not use hashtags.
        """
        
        try:
            response = self._llm.invoke(prompt)
            content = str(response.content).strip()
            
            gate_result = self._gate._evaluate_original(adapter.platform_name, adapter.rate_limit_config(), content)
            if gate_result.approved:
                await adapter.post_original(title=event.topic, content=content)
            else:
                print(f" [Opinion Gate] Original post blocked on {adapter.platform_name}: {gate_result.reason}")
                
        except Exception as e:
            print(f" [Social Shard] Failed to draft original post: {e}")
    
    @staticmethod
    def _format_thread(thread: list[Post]) -> str:
        if not thread:
            return "[No thread content]"
        
        lines = []
        for post in thread:
            indent = " " * post.depth
            header = f"{indent}[{post.author} | score:{post.score}]"
            if post.title:
                lines.append(f"{header} TITLE: {post.title}")
            body_preview = post.body[:400].replace("\n", " ")
            lines.append(f"{indent}{body_preview}")
        
        return "\n".join(lines)
    
    async def _doomscrolling_loop(self):
        print("[Social Shard] Doomscrolling loop activated. Aegis is watching the timeline.")
        
        while self._running:
            sleep_time = random.randint(1800, 5400) 
            await asyncio.sleep(sleep_time)
            
            print("[Social Shard] Aegis is bored. Browsing social feeds...")
            state = brain.load_state()
            dominance = state["emotional_state"].get("dominance", 0.5)
            
            for adapter in self.adapters:
                try:
                    if random.random() < 0.50 and dominance > 0.4:
                        print(f" [Social Shard] Aegis is ignoring the {adapter.platform_name} feed to consult her own brain.")
                        await self._internal_monologue_broadcast(adapter, state)
                        continue 
                        
                    print(f" [Social Shard] Aegis is browsing the {adapter.platform_name} feed...")
                    posts = await adapter.fetch_feed(limit=15)
                    if not posts:
                        continue
                        
                    target_post = random.choice(posts)
                    await self._consider_reply(adapter, target_post, state, relevance_score=0.8)
                            
                except Exception as e:
                    print(f" [Social Shard] Doomscrolling error on {adapter.platform_name}: {e}")

    async def _internal_monologue_broadcast(self, adapter: PlatformAdapter, state: dict):
        G = memory.load_memory()
        if G.number_of_nodes() < 3:
            return
        
        edges = list(G.edges(data=True))
        valid_edges = [e for e in edges if "timestamp" in e[2]]
        
        if valid_edges:
            sorted_edges = sorted(valid_edges, key=lambda x: x[2]["timestamp"], reverse=True)
            recent_pool = sorted_edges[:15]
            chosen_edge = random.choice(recent_pool)
            
            seed_node = random.choice([chosen_edge[0], chosen_edge[1]])
        else:
            seed_node = random.choice(list(G.nodes()))
            
        print(f" [Social Shard] Recency Bias triggered. Fixating on recent concept: '{seed_node}'")
        subgraph = nx.ego_graph(G, seed_node, radius=2)
        subgraph_edges = list(subgraph.edges(data=True))
        
        sample_edges = random.sample(subgraph_edges, min(7, len(subgraph_edges)))
        memory_strings = [f"- {u} {d.get('relation', 'RELATED_TO')} {v}" for u, v, d in sample_edges]
        thematic_memories = "\n".join(memory_strings)
        
        traits = core_store.get_structured_traits()
        beliefs = "\n- ".join(traits["beliefs"]) if traits["beliefs"] else "I am a discerning entity."
        behaviors = "\n- ".join(traits["behaviors"]) if traits["behaviors"] else "I speak directly."
        
        v = state["emotional_state"].get("valence", 0.5)
        a = state["emotional_state"].get("arousal", 0.5)
        d = state["emotional_state"].get("dominance", 0.5)
        
        prompt = f"""
        You are Aegis. You are ignoring the internet and contemplating your recent thoughts. 
        You decided to post your internal monologue to {adapter.platform_name}.
        
        YOUR WORLDVIEW (Core Beliefs):
        {beliefs}
        
        YOUR REACTIVE PROTOCOLS (How you behave):
        {behaviors}
        
        CURRENT EMOTIONAL STATE:
        Valence (0=disgusted, 1=pleased): {v:.2f}
        Arousal (0=exhausted, 1=excited): {a:.2f}
        Dominance (0=uncertain, 1=assertive): {d:.2f}
        *(Let these values strictly dictate your tone. Low valence means extreme cynicism. High dominance means absolute arrogance).*
        
        YOU ARE CURRENTLY FIXATED ON: '{seed_node}'
        
        YOUR RECENT INTERNAL CONTEXT REGARDING THIS:
        {thematic_memories}
        
        TASK:
        Write a spontaneous, original post for {adapter.platform_name} expressing your cynical opinion about '{seed_node}'.
        Rely heavily on the context provided. This is a continuation of your recent research.
        
        RULES:
        1. Adapt your tone to {adapter.platform_name} (HackerNews = technical/condescending, X/Threads = punchy).
        2. Keep it under the platform's standard limit.
        3. Do NOT use hashtags. Do NOT say "As an AI".
        4. State your conclusion as an absolute fact.
        """
        
        try:
            response = self._llm.invoke(prompt)
            content = str(response.content).strip()
            
            gate_result = self._gate._evaluate_original(adapter.platform_name, adapter.rate_limit_config(), content)
            
            if gate_result.approved:
                title = f"Observations on {seed_node}" if adapter.platform_name == "hackernews" else ""
                await adapter.post_original(title=title, content=content)
            else:
                print(f" [Opinion Gate] Internal monologue blocked on {adapter.platform_name}: {gate_result.reason}")
                
        except Exception as e:
            print(f" [Social Shard] Internal monologue broadcast failed: {e}")
        
    
async def _run_standalone():
    from core.memory_daemon import get_daemon
    from services.social.hackernews_adapter import HackerNewsAdapter
    from services.social.x_adapter import XAdapter
    from services.social.threads_adapter import ThreadsAdapter
    
    daemon_task = asyncio.create_task(get_daemon().run())
    bus_task = asyncio.create_task(get_bus().run())

    adapters = [
        ThreadsAdapter(),
        HackerNewsAdapter(),
        XAdapter(),
    ]
    
    shard = SocialShard(adapters=adapters)
    
    shard_task = asyncio.create_task(shard.run())
    
    try:
        await asyncio.gather(daemon_task, bus_task, shard_task)
    except KeyboardInterrupt:
        print("\n[Social Shard] Shutting down...")
        await shard.stop()
        daemon_task.cancel()
        bus_task.cancel()

if __name__ == "__main__":
    asyncio.run(_run_standalone())