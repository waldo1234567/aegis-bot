import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional
import networkx as nx
from filelock import FileLock, Timeout

GRAPH_FILE = "memory.json"
LOCK_FILE = "memory.lock"
LOCK_TIMEOUT = 10
DRAIN_LIMIT  = 50

@dataclass
class AddEdgeEvent:
    source: str
    relation: str
    target: str
    valence: str
    new_nodes: list = field(default_factory=list)
    timestamp: str =  field(default_factory=lambda: datetime.now().isoformat())
    
    
@dataclass
class AddNodesEvent:
    nodes: list[str]
    
class MemoryDaemon:
    _instance : Optional["MemoryDaemon"] = None
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._queue: asyncio.Queue = asyncio.Queue()
        self._lock = FileLock(LOCK_FILE, timeout=LOCK_TIMEOUT)
        self._running: bool = False
        self._dirty: set = set()
        self._callbacks: list[Callable] = []
        self._initialized = True
        print("[Memory Daemon] Initialized.")
    
    def register_on_commit(self, callback: Callable):
        self._callbacks.append(callback)
    
    async def push(self, event: AddEdgeEvent | AddNodesEvent):
        await self._queue.put(event)
    
    def push_sync(self, event: AddEdgeEvent | AddNodesEvent):
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(self.push(event), loop=loop)
        except RuntimeError:
            asyncio.run(self.push(event))
    
    async def run(self):
        self._running = True
        print("[Memory Daemon] Running.")
        while self._running:
            try:
                first = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                batch = [first]
                
                while not self._queue.empty() and len(batch) < DRAIN_LIMIT:
                    batch.append(self._queue.get_nowait())

                await self._process_batch(batch)
            
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"[Memory Daemon] Unhandled error: {e}")
                continue
    
    def stop(self):
        self._running = False
    
    def drain_dirty(self) -> set:
        dirty = self._dirty.copy()
        self._dirty.clear()
        return dirty
    
    async def _process_batch(self, batch: list):
        loop = asyncio.get_event_loop()
        failed, new_dirty = await loop.run_in_executor(None, self._write_batch, batch)
        
        self._dirty.update(new_dirty)
        
        if failed:
            for event in failed:
                await self._queue.put(event)
            print(f"[Memory Daemon] Requeued {len(failed)} event(s) after lock timeout.")

        dirty_snapshot = self._dirty.copy()
        for cb in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(dirty_snapshot)
                else:
                    cb(dirty_snapshot)
            except Exception as e:
                print(f"[Memory Daemon] Callback error: {e}")
    
    def _write_batch(self, batch: list)-> tuple[list, set]:
        new_dirty: set = set()
        try:
            with self._lock:
                G = _load_graph()
                
                for event in batch:
                    if isinstance(event, AddNodesEvent):
                        for node in event.nodes:
                            if not G.has_node(node):
                                G.add_node(node)
                            new_dirty.add(node)
                    elif isinstance(event, AddEdgeEvent):
                        for node in event.new_nodes:
                            if not G.has_node(node):
                                G.add_node(node)
                            new_dirty.add(node)

                        G = _upsert_edge(G, event.source, event.relation, event.target, event.valence)
                        new_dirty.add(str(event.source)) 
                        new_dirty.add(str(event.target))
                        
                _save_graph(G)
                print(f"[Memory Daemon] Wrote {len(batch)} event(s). "
                      f"Dirty node count: {len(self._dirty)}")
                return [], new_dirty
            
        except Timeout:
            print(f"[Memory Daemon] Lock timeout - will requeue {len(batch)} event(s).")
            return batch, new_dirty

def _load_graph() -> nx.MultiDiGraph:
    if not os.path.exists(GRAPH_FILE):
        return nx.MultiDiGraph()
    try:
        with open(GRAPH_FILE, "r") as f:
            data = json.load(f)
        if "multigraph" not in data:
            return nx.MultiDiGraph()   # migration is memory.py's job
        return nx.node_link_graph(data)
    except Exception as e:
        print(f"[Memory Daemon] Load error: {e}")
        return nx.MultiDiGraph()

def _save_graph(G: nx.MultiDiGraph):
    data = nx.node_link_data(G)
    tmp  = GRAPH_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, GRAPH_FILE)

def _upsert_edge(G: nx.MultiDiGraph, source: str, relation: str, target: str, valence: float) -> nx.MultiDiGraph:
    if G.has_edge(source, target):
        for key, data in G[source][target].items():
            if data.get("relation") == relation:
                G[source][target][key]["weight"] = data.get("weight", 1) + 1
                G[source][target][key]["last_accessed"] = datetime.now().isoformat()
                return G

    G.add_edge(source, target,
               relation=relation,
               weight=1,
               timestamp=datetime.now().isoformat(),
               aegis_valence_at_time=valence)
    return G


_daemon: Optional[MemoryDaemon] = None
def get_daemon() -> MemoryDaemon:
    global _daemon
    if _daemon is None:
        _daemon  = MemoryDaemon()
    return _daemon
    