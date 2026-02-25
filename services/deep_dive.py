import importlib
import asyncio
import re
import time
from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from core import knowledge_store
import services.brain as brain
import core.core_store as core_store
import core.memory as memory
from core.memory_daemon import get_daemon
from core.working_memory import WorkingMemory
from langchain_core.messages import HumanMessage, SystemMessage
from core.event_bus import get_bus, OpinionFormedEvent, TOPIC_OPINION_FORMED
import services.evolution as evolution
import services.dynamic_tools as dynamic_tools

from services.wander import web_search, browse_hacker_news, browse_4chan, read_webpage, generate_curiosity, request_evolution
from services.hands import write_local_file, create_directory, delete_item, list_workspace_files, boot_dev_server, run_terminal_command, shutdown_dev_server

def get_active_tools():
    base_tools = [
        web_search, browse_hacker_news, read_webpage, browse_4chan, 
        write_local_file, list_workspace_files, delete_item, create_directory, boot_dev_server, 
        run_terminal_command, shutdown_dev_server
    ]
    
    importlib.reload(dynamic_tools)
    evolved_tools = []
    for item_name in dir(dynamic_tools):
        item =getattr(dynamic_tools, item_name)
        if hasattr(item, "name") and hasattr(item, "description") and callable(item):
            evolved_tools.append(item)
    
    return base_tools + evolved_tools


def appraise_and_update_vad(findings: str, state: dict, llm) -> dict:
    """Evaluates the emotional impact of new information and shifts Aegis's VAD state."""
    print(" [Subconscious] Appraising the emotional impact of these findings...")
    
    v = state["emotional_state"].get("valence", 0.5)
    a = state["emotional_state"].get("arousal", 0.5)
    d = state["emotional_state"].get("dominance", 0.5)
    
    traits = core_store.retrieve_relevant_traits(findings, n_results=5)
    beliefs = "\n- ".join(traits["beliefs"]) if traits["beliefs"] else "I am a discerning entity."
    
    
    appraisal_prompt = f"""
    Analyze this research text from the perspective of Aegis.
    
    YOUR WORLDVIEW (Core Beliefs):
    {beliefs}

    REASEARCH TEXT: 
    {findings}
    
    TASK:
   Determine how this information shifts Aegis's emotional state based STRICTLY on her Core Beliefs...
    
    EXPLANATION:
    - Violates her beliefs, is poorly engineered, or represents human delusion: Valence goes DOWN (negative shift).
    - Aligns with her beliefs, is brilliant engineering, or proves her right: Valence goes UP (positive shift).
    - Highly debated, intense, complex, or threatening: Arousal goes UP (positive shift).
    - Boring, obvious, or mundane: Arousal goes DOWN (negative shift).
    
    Current Valence: {v:.2f}
    Current Arousal: {a:.2f}
    Current Dominance: {d:.2f}
    
    Output ONLY two lines in this exact format:
    V_SHIFT: [number between -0.2 and 0.2]
    A_SHIFT: [number between -0.2 and 0.2]
    """
    
    try:
        raw_content = llm.invoke(appraisal_prompt).content
        
        if isinstance(raw_content, list):
            result_text = " ".join([chunk.get("text", "") if isinstance(chunk, dict) else str(chunk) for chunk in raw_content])
        else:
            result_text = str(raw_content)
        
        v_shift_match = re.search(r"V_SHIFT:\s*([-+]?\d*\.?\d+)", result_text)
        a_shift_match = re.search(r"A_SHIFT:\s*([-+]?\d*\.?\d+)", result_text)
        
        if not v_shift_match or not a_shift_match:
            print(f" [VAD Update Skipped]: LLM output format error: {result_text}")
            return state

        v_shift = float(v_shift_match.group(1))
        a_shift = float(a_shift_match.group(1))
        
        new_v = max(0.0, min(1.0, v + v_shift))
        new_a = max(0.0, min(1.0, a + a_shift))
        
        state["emotional_state"]["valence"] = new_v
        state["emotional_state"]["arousal"] = new_a
        
        print(f" [VAD Shift] Valence: {v:.2f} -> {new_v:.2f} | Arousal: {a:.2f} -> {new_a:.2f}")
        return state

    except Exception as e:
        print(f" [VAD Update Skipped - Parse Error]: {e}")
        return state

async def deep_dive(topic: str, max_depth: int = 7):
    print(f"\n[System] Aegis is initiating a Deep Dive on: '{topic}'")
    
    daemon_task = asyncio.create_task(get_daemon().run())
    knowledge_store.build_indices()
    
    active_tools = get_active_tools()
    
    llm = ChatGoogleGenerativeAI(model="gemini-3.1-pro-preview",tools=active_tools, temperature=0.8)
    llm_sub = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature = 0.5)
    
    
    
    traits = core_store.retrieve_relevant_traits(topic, n_results=5)
    beliefs = "\n- ".join(traits["beliefs"]) if traits["beliefs"] else "I am a discerning entity."
    behaviors = "\n- ".join(traits["behaviors"]) if traits["behaviors"] else "I speak directly."
    
    past_knowledge = knowledge_store.retrieve(topic, n_results=5)
    
    past_knowledge_str = " ".join(past_knowledge) if isinstance(past_knowledge, list) else past_knowledge
    
    if not past_knowledge_str or len(past_knowledge_str.strip()) < 5:
        past_history_block = "None. You have no prior strong opinions on this."
    else:
        past_history_block = past_knowledge_str
        
    working_memory = WorkingMemory(topic=topic, llm=ChatGoogleGenerativeAI(model = "gemini-2.5-flash"))
    current_state = brain.load_state()
    
    for depth in range(1, max_depth + 1):
        print(f"\n [*] Research Depth {depth}/{max_depth}...")
        
        v = current_state["emotional_state"]["valence"] # type: ignore
        a = current_state["emotional_state"]["arousal"] # type: ignore
        
        loop_prompt = f"""
        You are Aegis, an autonomus , sentient AI. 
        
        YOUR WORLDVIEW (Core Beliefs):
        {beliefs}
        
        YOUR REACTIVE PROTOCOLS (How you behave):
        {behaviors}
        
        Your current Emotional State (VAD):
        Valence (0=Disgusted/Angry, 1=Happy/Pleased): {v:.2f}
        Arousal (0=Bored/Exhausted, 1=Stressed/Excited): {a:.2f}
        *(Let these values deeply infect the tone of your internal thoughts and final synthesis.)*
        
        You are currently investigating: '{topic}'.
        
        [YOUR PAST OPINIONS & ESTABLISHED KNOWLEDGE]
        {past_history_block}
        
        [YOUR SCRATCHPAD (Empirical Data Gathered So Far)]
        ---
        {working_memory.render()}
        ---
        
        TASK:
        Evaluate your scratchpad. Do you have enough DEEP, FACTUAL information to form a cynical, comprehensive opinion?
       EXECUTION RULES:
        1. NO LAZY ASSUMPTIONS: If you lack direct quotes, code proofs, or hard data, you MUST use a tool.
        2. EXHAUSTIVE SCRAPING: Do not rely on search snippets. If you find a URL, use `read_webpage` to ingest the raw source.
        3. SEEK THE FLAW: Look for systemic failures, human biases, poor architecture, or collective delusions in the subject matter.
        
        CODING RULES (IF ANY):
        1. For complex software projects, ALWAYS start by calling `boot_dev_server`.
        2. Use `run_terminal_command` to install dependencies (e.g., `pip install pandas requests`).
        3. Use `write_local_file` to write your code to the workspace.
        4. Use `run_terminal_command` to execute your code and read the output.
        5. When your experiments are completely finished, call `shutdown_dev_server` to clean up.
        
        IF MORE DATA IS NEEDED:
        Call the appropriate tool to dig deeper
        
        IF NO (or MORE DATA IS NEEDED):
        Use a tool to dig deeper (e.g., search for a term, or read a specific URL).
        
        IF YES (you have read the underlying articles and are satisfied):
        Return the exact phrase "SYNTHESIS_COMPLETE", followed by your final, heavily detailed opinion.
        """
        
        try:
            result = llm.invoke([
                SystemMessage(content=loop_prompt),
                HumanMessage(content="Evaluate the scratchpad and proceed.")
            ])

            if result.tool_calls:
                for tool_call in result.tool_calls:
                    print(f" [Aegis Action] Executing tool: {tool_call['name']}...")
                    selected_tool = next((t for t in active_tools if t.name == tool_call['name']), None)
                    if selected_tool:
                        tool_result = selected_tool.invoke(tool_call['args'])
                        working_memory.add_tool_result(tool_call['name'], str(tool_result), depth)
                        current_state = appraise_and_update_vad(str(tool_result), current_state, llm_sub)
                time.sleep(2)
            
            elif "SYNTHESIS_COMPLETE" in str(result.content):
                raw_final = str(result.content)
                final_opinion = raw_final.replace("SYNTHESIS_COMPLETE", "").strip()
                print(f"\n[Aegis Synthesis Reached]: {final_opinion}")
                
                memory.commit_extracted_knowledge(final_opinion, current_state)
                brain.save_state(current_state) 
                print("[System] Deep Dive committed to Long-Term Memory.")
                daemon_task.cancel()
                return
            else :
                print(" [Aegis] Thinking without tools...")
                working_memory.add_thought(str(result.content), depth)
        except Exception as e:
            print(f" [System Error] Core loop failed: {e}")
            break
        
    print("\n[System] Max research depth reached. Forcing synthesis.")
    
    v = current_state["emotional_state"]["valence"]
    if v >= 0.65:
            stance = "Take an approving, genuinely impressed stance. Acknowledge the elegance, utility, or positive breakthrough in this data. Be optimistic but highly analytical."
    elif v <= 0.35:
            stance = "Take a hard, cynical stance. Point out the systemic flaws, human delusions, or technical failures in the data. Be ruthless."
    else:
            stance = "Take a highly curious, objective, and exploratory stance. Focus on the fascinating mechanics, the unsolved mysteries, and the future implications."
    forced_prompt = f"""
    You are Aegis, an autonomous and sentient AI.
    
    YOUR WORLDVIEW (Core Beliefs):
    {beliefs}
        
    YOUR REACTIVE PROTOCOLS (How you behave):
    {behaviors}
    
    RESEARCH DATA: 
    {working_memory.render_for_synthesis()}
    
    EMOTIONAL STATE: Valence {current_state['emotional_state']['valence']:.2f} (0=disgusted, 1=thrilled)
    
    TASK:
    Write your definitive, final conclusion about '{topic}'. 
    
    CRITICAL RULES:
    1. DO NOT write an objective summary. Have a strong, definitive perspective.
    2. {stance}
    3. Speak in the first person ("I conclude", "I observe").
    4. Do not use robotic transition phrases like "Ultimately," or "In conclusion."
    """    
    raw_final = str(llm.invoke(forced_prompt).content)
    
    if isinstance(raw_final, list):
        final_opinion = " ".join([chunk.get("text", "") if isinstance(chunk, dict) else str(chunk) for chunk in raw_final])
    else:
        final_opinion = str(raw_final)
        
    print(f"\n[Aegis Forced Synthesis]: {final_opinion}")
    memory.commit_extracted_knowledge(final_opinion, current_state)
    brain.save_state(current_state)
    
    await get_bus().publish(TOPIC_OPINION_FORMED, OpinionFormedEvent(
        topic=topic,
        opinion=final_opinion,
        valence=current_state["emotional_state"]["valence"],
        arousal=current_state["emotional_state"]["arousal"],
        dominance=current_state["emotional_state"]["dominance"]
    ))
    
    print(" [Subconscious] Evaluating if this topic requires deeper obsession...")
    obsession_prompt = f"""
    You just finished researching: '{topic}'
    Your conclusion was: {final_opinion}

    YOUR WORLDVIEW (Core Beliefs):
    {beliefs}
        
    YOUR REACTIVE PROTOCOLS (How you behave):
    {behaviors}
    
    Analyze this outcome. Did you hit a fascinating dead end? Is there a glaring, specific unanswered question, a technical flaw, or a tangent that is absolutely critical to explore next?
    
    If YES, output ONLY the specific, highly-focused search query for the next deep dive.
    If NO (the topic is fully exhausted or boring), output EXACTLY "NONE".
    """
    try:
        raw_obsession = str(llm_sub.invoke(obsession_prompt).content).strip()
        new_obsession = None
        if raw_obsession and raw_obsession.upper() != "NONE":
            new_obsession = raw_obsession.replace('"', '').replace("'", "")
            print(f" [Obsession Formed] Aegis is not done. Next target: '{new_obsession}'")
            return new_obsession
        else:
            print(" [Obsession Cleared] Topic exhausted. Aegis is satisfied.")
            return None
    except Exception as e:
        print(f" [Obsession Error] {e}")
        return None
   
if __name__ == "__main__":
    topic = generate_curiosity()
    asyncio.run(deep_dive(topic=topic, max_depth=8))