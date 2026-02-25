import asyncio
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine, Optional

TOPIC_OPINION_FORMED = "opinion_formed"   
TOPIC_VAD_SHIFT = "vad_shift"         
TOPIC_NEW_MEMORY = "new_memory"        
TOPIC_SOCIAL_ACTION = "social_action"   
TOPIC_SLEEP_COMPLETE = "sleep_complete"    
TOPIC_DEEP_DIVE_START = "deep_dive_start"  
TOPIC_DEEP_DIVE_ABORT = "deep_dive_abort"

@dataclass
class OpinionFormedEvent:
    topic:       str
    opinion:     str
    valence:     float
    arousal:     float
    dominance:   float
    timestamp:   str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class VadShiftEvent:
    old_valence:   float
    new_valence:   float
    old_arousal:   float
    new_arousal:   float
    old_dominance: float
    new_dominance: float
    trigger:       str   # what caused the shift ("tool_result", "synthesis", etc.)
    timestamp:     str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class NewMemoryEvent:
    node_count: int
    edge_count: int
    dirty_nodes: set
    source:     str   # which shard triggered this ("deep_dive", "chat", "social")
    timestamp:  str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class SocialActionEvent:
    platform:   str    # "hackernews", "reddit", etc.
    action:     str    # "reply", "post", "upvote"
    post_id:    str    # platform's ID for the content we interacted with
    content:    str    # what Aegis wrote
    url:        str
    timestamp:  str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class SleepCompleteEvent:
    new_trait:      str
    edges_analyzed: int
    timestamp:      str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class DeepDiveStartEvent:
    topic:     str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    

@dataclass
class _Envelope:
    topic: str
    event: Any
    
Handler = Callable[[Any], Coroutine[Any, Any, None]]

class EventBus:
    _instance: Optional["EventBus"] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._queue: asyncio.Queue     = asyncio.Queue()
        self._handlers: dict[str, list[Handler]] = {}
        self._running: bool              = False
        self._event_log: list[_Envelope]   = [] 
        self._initialized= True
        print("[Event Bus] Initialized.")
        
    def subscribe(self, topic: str, handler: Handler):
        if topic not in self._handlers:
            self._handlers[topic] = []
        if handler not in self._handlers[topic]:
            self._handlers[topic].append(handler)
            print(f"[Event Bus] Subscribed {handler.__qualname__} → '{topic}'")
    
    def unsubscribe(self, topic: str, handler:Handler):
        if topic in self._handlers:
            self._handlers[topic] = [h for h in self._handlers[topic] if h != handler]
    
    async def publish(self, topic : str, event: Any):
        envelope = _Envelope(topic=topic, event=event)
        await self._queue.put(envelope)
    
    def publish_sync(self, topic: str, event:Any):
        envelope = _Envelope(topic=topic, event=event)
        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(self._queue.put(envelope), loop)
        except RuntimeError:
            asyncio.run(self._queue.put(envelope))
        
    async def run(self):
        self._running = True
        print("[Event Bus] Running.")
        while self._running:
            try:
                envelope = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._dispatch(envelope)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"[Event Bus] Dispatch error: {e}")
    
    async def _dispatch(self, envelope: _Envelope):
        handlers = self._handlers.get(envelope.topic, [])
        if not handlers:
            return
        
        self._event_log.append(envelope)
        if len(self._event_log) > 200:
            self._event_log.pop(0)
        
        tasks = [
            asyncio.create_task(self._safe_call(h, envelope))
            for h in handlers
        ]
        
        await asyncio.gather(*tasks)
    
    async def _safe_call(self, handler: Handler, envelope: _Envelope):
        try:
            await handler(envelope.event)
        except Exception:
            print(f"[Event Bus] Handler '{handler.__qualname__}' on "
                  f"'{envelope.topic}' raised an exception:")
            traceback.print_exc()
    
    def stop(self):
        self._running = False
        
    def recent_events(self, topic: str | None = None, n :int =20) -> list:
        log = self._event_log if topic is None else [
            e for e in self._event_log if e.topic == topic
        ]
        return log[-n:]
    
_bus: Optional[EventBus] = None
def get_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus