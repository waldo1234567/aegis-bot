from fastapi import FastAPI, BackgroundTasks, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel
import threading
import time
import asyncio
import random

from core.memory_daemon import get_daemon
from core.event_bus import get_bus
from core import knowledge_store

from services.social.social_shard import SocialShard
from services.social.hackernews_adapter import HackerNewsAdapter
from services.social.threads_adapter import ThreadsAdapter

import services.brain as brain
from services.deep_dive import deep_dive
from services.wander import generate_curiosity
from services.sleep import enter_rem_sleep

APP_STATE = {                                                                                                                                                                                        
    "is_researching": False,                                                                                                                                                                         
    "current_vad": {"valence": 0.5, "arousal": 0.5, "dominance" : 0.5},                                                                                                                              
    "last_interaction": None,                                                                                                                                                                        
    "obsession_stack": []                                                                                                                                                                            
}      



_active_daemons = set()

def _run_research_isolated(topic: str):
    new_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(new_loop)
    try:
        new_loop.run_until_complete(deep_dive(topic, max_depth=3))
    finally:
        new_loop.close()

async def autonomus_cognitive_loop():
    print("[Cognitive Loop] Online. Aegis is thinking...")
    while True:
        try:
            if APP_STATE["obsession_stack"]:
                topic = APP_STATE["obsession_stack"].pop()
                print(f"[Cognitive Loop] Continuing obsession ({len(APP_STATE['obsession_stack'])} remaining). Target: '{topic}'")
            else:
                topic = await asyncio.to_thread(generate_curiosity)
                print(f"[Cognitive Loop] Wandering. Triggering Deep Dive on: '{topic}'")
                
            APP_STATE["is_researching"] = True
            
            new_obsession = await asyncio.to_thread(_run_research_isolated, topic)
            
            if new_obsession:
                APP_STATE["obsession_stack"].append(new_obsession)
            
            APP_STATE["is_researching"] = False
            
            if random.random() < 0.2:
                await asyncio.to_thread(enter_rem_sleep)
                
            sleep_time = random.randint(300, 900) 
            print(f"[Cognitive Loop] Cycle complete. Resting for {sleep_time/60:.1f} minutes.")
            await asyncio.sleep(sleep_time)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Cognitive Loop] Misfire: {e}")
            APP_STATE["is_researching"] = False
            await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app:FastAPI):
    print("=== BOOTING AEGIS GOD ENGINE ===")
    
    saved_state = brain.load_state() or {}
    
    APP_STATE["current_vad"] = saved_state.get("emotional_state", APP_STATE["current_vad"])
    APP_STATE["last_interaction"] = saved_state.get("last_interaction_timestamp")
    APP_STATE["obsession_stack"] = saved_state.get("obsession_stack", [])
        
    daemon = get_daemon()
    bus = get_bus()
    
    _active_daemons.add(asyncio.create_task(daemon.run()))
    _active_daemons.add(asyncio.create_task(bus.run()))
    
    adapters = [HackerNewsAdapter(), ThreadsAdapter()]
    social_shard = SocialShard(adapters=adapters)
    _active_daemons.add(asyncio.create_task(social_shard.run()))
    
    _active_daemons.add(asyncio.create_task(autonomus_cognitive_loop()))
    
    print("=== ALL SHARDS ONLINE AND AUTONOMOUS ===")
    
    yield
    
    print("=== INITIATING GRACEFUL SHUTDOWN ===")
    bus.stop()
    for task in _active_daemons:
        task.cancel()
        
    saved_state = brain.load_state() or {}
    saved_state["emotional_state"] = APP_STATE["current_vad"]
    saved_state["obsession_stack"] = APP_STATE["obsession_stack"]
    brain.save_state(saved_state)
    
app = FastAPI(title="Aegis Core API", lifespan=lifespan)

class ChatRequest(BaseModel):
    user_input: str
    user_id: str = "Waldo"
    
class ChatResponse(BaseModel):
    reply: str
    valence: float
    arousal: float
    dominance: float

class ResearchRequest(BaseModel):
    topic: str
    
@app.post("/api/chat", response_model=ChatResponse)
async def process_chat(request: ChatRequest):
    try:
        user_text = request.user_input
        
        state = brain.load_state() or {}
        if "emotional_state" not in state:
            state["emotional_state"] = APP_STATE["current_vad"]
            
        chat_buffer = brain.load_short_term()
        
        state = await asyncio.to_thread(brain.update_emotion, user_text, state)
        APP_STATE["current_vad"] = state["emotional_state"]
        reply = await asyncio.to_thread(brain.generate_response, user_text, state, chat_buffer)
        
        chat_buffer.append(f"User: {user_text}")
        chat_buffer.append(f"Aegis: {reply}")
        
        if len(chat_buffer) > 10:
            chat_buffer = chat_buffer[-10:]
            
            
        brain.save_short_term(chat_buffer)
        brain.save_state(state)
        
        if len(chat_buffer) >= 8:
            history_text = "\n".join(chat_buffer)
            asyncio.create_task(asyncio.to_thread(brain.background_worker, history_text, state))
        
        return ChatResponse(
            reply=reply,
            valence=state["emotional_state"]["valence"],
            arousal=state["emotional_state"]["arousal"],
            dominance=state["emotional_state"]["dominance"]
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@app.post("/api/research")
async def trigger_deep_dive(request: ResearchRequest, background_tasks: BackgroundTasks):
    if APP_STATE["is_researching"]:
        return {"status": "rejected", "message": "Aegis is already researching a topic."}

    async def research_task(topic: str):
        APP_STATE["is_researching"] = True
        try:
            await deep_dive(topic, max_depth=3)
        finally:
            APP_STATE["is_researching"] = False
            APP_STATE["current_vad"] = brain.load_state()["emotional_state"] # type: ignore
    
    background_tasks.add_task(research_task, request.topic)
    
    return {"status": "accepted", "message": f"Aegis has begun a background deep dive on '{request.topic}'."}

@app.get("/api/state")
async def get_system_state():
    return {
        "status": "researching" if APP_STATE["is_researching"] else "idle",
        "valence": APP_STATE["current_vad"]["valence"],
        "arousal": APP_STATE["current_vad"]["arousal"]
    }