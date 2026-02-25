import time
from dataclasses import dataclass

from core import knowledge_store

MIN_DOMINANCE = 0.45   
MIN_KNOWLEDGE_RESULTS = 2      
MIN_REPLY_LENGTH = 80    

CHAR_LIMITS = {
    "x": 280,
    "threads": 500,
    "hackernews": 2000,
    "reddit": 10000,
    "default": 1200,
}


@dataclass
class GateResult:
    approved: bool
    reason: str 
    knowledge_context: list[str]      
    confidence_score:  float = 0.0


class RateLimitTracker:
    def __init__(self):
        self._post_times: dict[str, list[float]] = {}
        self._daily_counts: dict[str, list[float]] = {}
    
    def can_post(self, platform: str, config: dict) -> tuple[bool,str]:
        now   = time.time()
        times = self._post_times.get(platform, [])
        
        times = [t for t in times if now - t < 3600]
        self._post_times[platform] = times
        
        if times:
            since_last = now - times[-1]
            min_gap    = config.get("min_seconds_between", 300)
            if since_last < min_gap:
                wait = int(min_gap - since_last)
                return False, f"Rate limit: {wait}s until next allowed post on {platform}"

        hourly_count = len(times)
        max_hourly   = config.get("max_posts_per_hour", 2)
        if hourly_count >= max_hourly:
            return False, f"Rate limit: {hourly_count}/{max_hourly} posts this hour on {platform}"
        
        daily = [t for t in self._daily_counts.get(platform, []) if now - t < 86400]
        self._daily_counts[platform] = daily
        max_daily = config.get("max_posts_per_day", 8)
        if len(daily) >= max_daily:
            return False, (f"Daily cap: {len(daily)}/{max_daily} posts "
                           f"today on {platform}.")

        return True, "ok"

    def record_post(self, platform: str):
        now = time.time()
        self._post_times.setdefault(platform, []).append(now)
        self._daily_counts.setdefault(platform, []).append(now)

    def daily_remaining(self, platform: str, config: dict) -> int:
        now   = time.time()
        daily = [t for t in self._daily_counts.get(platform, []) if now - t < 86400]
        return max(0, config.get("max_posts_per_day", 8) - len(daily))
    
_rate_tracker = RateLimitTracker()

def get_rate_tracker() -> RateLimitTracker:
    return _rate_tracker


class OpinionGate:
    
    def __init__(self):
        self._seen_threads: set[str] = set()
        
    def evaluate(self,platform: str,post_id: str,post_text: str,generated_reply: str,emotional_state: dict,platform_config: dict) -> GateResult:
        can, msg = _rate_tracker.can_post(platform, platform_config)
        if not can:
            return GateResult(approved=False, reason=msg, knowledge_context=[])
        
        dominance = emotional_state.get("dominance", 0.5)
        if dominance < MIN_DOMINANCE:
            return GateResult(
                approved=False,
                reason=f"Dominance too low ({dominance:.2f} < {MIN_DOMINANCE}) - staying silent.",
                knowledge_context=[]
            )
        
        context = knowledge_store.retrieve(post_text, n_results=5)
        strong  = [c for c in context if c]
        
        if len(strong) < MIN_KNOWLEDGE_RESULTS:
            return GateResult(
                approved=False,
                reason=f"Insufficient knowledge: only {len(strong)} graph hits for this topic.",
                knowledge_context=strong
            )
        
        if post_id in self._seen_threads:
            return GateResult(
                approved=False,
                reason=f"Already replied to {post_id} - skipping to avoid spam.",
                knowledge_context=strong
            )
        
        reply   = generated_reply.strip()
        ceiling = CHAR_LIMITS.get(platform, CHAR_LIMITS["default"])
        
        if len(generated_reply.strip()) < MIN_REPLY_LENGTH:
            return GateResult(
                approved=False,
                reason=f"Reply too short ({len(generated_reply)} chars < {MIN_REPLY_LENGTH}).",
                knowledge_context=strong
            )

        if len(reply) > ceiling:
            return GateResult(
                approved=False,
                reason=(f"Reply exceeds {platform} limit ({len(reply)} > {ceiling} chars). "
                        "Adjust LLM prompt to enforce shorter output."),
                knowledge_context=strong
            )
        
        confidence = min(1.0, (dominance + min(len(strong) / 5, 1.0)) / 2)
        remaining  = _rate_tracker.daily_remaining(platform, platform_config)
        
        return GateResult(
            approved=True,
            reason=f"Approved. {remaining} post(s) remaining today on {platform}.",
            knowledge_context=strong,
            confidence_score=confidence
        )
    
    def _evaluate_original(self, platform: str, platform_config: dict, content: str) -> GateResult:
        can_post, limit_reason = _rate_tracker.can_post(platform, platform_config)
        if not can_post:
            return GateResult(approved=False, reason=limit_reason, knowledge_context=[])
        
        content_clean = content.strip()
        ceiling = CHAR_LIMITS.get(platform, CHAR_LIMITS["default"])
        
        if len(content_clean) > ceiling:
            return GateResult(
                approved=False,
                reason=f"Original post exceeds {platform} limit ({len(content_clean)} > {ceiling} chars).",
                knowledge_context=[]
            )
            
        remaining = _rate_tracker.daily_remaining(platform, platform_config)
        return GateResult(
            approved=True,
            reason=f"Approved. {remaining} post(s) remaining today on {platform}.",
            knowledge_context=[],
            confidence_score=1.0  
        )
    
    def mark_reply(self, post_id: str):
        self._seen_threads.add(post_id)

    def clear_seen(self):
        self._seen_threads.clear()