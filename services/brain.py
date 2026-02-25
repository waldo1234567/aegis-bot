import json
import os
import threading
from google import genai

import time
from datetime import datetime
import core.core_store as core_store
import core.memory as memory
import core.knowledge_store as knowledge_store
import reflection

from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY")

client = genai.Client(api_key=api_key)
chat_buffer = []
BUFFER_LIMIT = 4

def background_worker(history_text, current_state):
    try:
        memory.commit_extracted_knowledge(history_text,current_state)
        reflection.evolve_personality(history_text, current_state)
    
    except Exception as e:
        print(f"\n[Background Error] {e}")

def load_state():
    if not os.path.exists('state.json'):
        return None
    with open('state.json', 'r') as f:
        return json.load(f)
    

def save_state(state):
    state['last_seen'] = datetime.now().isoformat()
    with open('state.json', 'w') as f:
        json.dump(state, f, indent=2)


def load_short_term():
    state = load_state()
    if state is None:
        return []
    return state.get('short_term_memory', [])


def save_short_term(chat_buffer):
    state = load_state()
    if state is None:
        state = {}
    state['short_term_memory'] = chat_buffer
    save_state(state)


def get_sensory_envelope(user_input, state):
    now = datetime.now()
    time_str = now.strftime("%I:%M %p")
    
    hour = now.hour
    
    if hour < 6: time_of_day = "Deep Night"
    elif hour < 12: time_of_day = "Morning"
    elif hour < 17: time_of_day = "Afternoon"
    elif hour < 22: time_of_day = "Evening"
    else: time_of_day = "Late Night"
    
    last_time_str = state.get("last_interaction_timestamp")
    time_elapsed_msg = "First interaction of the session."
    
    if last_time_str:
        try:
            last_time = datetime.fromisoformat(last_time_str)
            delta = now - last_time
            minutes_passed = int(delta.total_seconds() / 60)
            
            if minutes_passed < 5:
                time_elapsed_msg = "Active ongoing conversation."
            elif minutes_passed < 60:
                time_elapsed_msg = f"Paused conversation ({minutes_passed} mins ago)."
            elif minutes_passed < 1440:
                hours = minutes_passed // 60
                time_elapsed_msg = f"Resuming after {hours} hours."
            else:
                days = minutes_passed // 1440
                time_elapsed_msg = f"Long absence ({days} days since last spoken)."
        except Exception:
            pass
    
    state["last_interaction_timestamp"] = now.isoformat()
    
    word_count = len(user_input.split())
    if word_count <= 2: effort = "Extremely low effort/brief."
    elif word_count < 10: effort = "Casual/standard length."
    else: effort = "High effort/detailed."
    
    envelope = f"""
    - Local Time: {time_str} ({time_of_day})
    - Temporal Distance: {time_elapsed_msg}
    - User Input Effort: {word_count} words ({effort})
    """
    return envelope, state
        
        
def calculate_time_decay(state):       
    if 'last_seen' not in state:
        return state, 0.0
    
    last_seen = datetime.fromisoformat(state['last_seen'])
    now = datetime.now()
    delta = now - last_seen
    
    hours_passed = delta.total_seconds() / 3600
    
    print(f"\n[System] Time passed: {hours_passed:.2f} hours.") 
    
    decay_factor = min(hours_passed / 24, 1.0)
    current_arousal = state['emotional_state']['arousal']
    
    if current_arousal > 0.5:
        state['emotional_state']['arousal'] -= (decay_factor * 0.3)
        
    if hours_passed > 48:
        drop = int(hours_passed / 24)
        state['stats']['relationship_score'] -= drop
        print(f"[System] Relationship dropped by {drop} due to neglect.")
    
    return state, hours_passed


def update_emotion(user_input, current_state):
    system_prompt = f"""
    You are the subconscious emotional processor for an AI named Aegis.
    Current State:
    - Valence (Happiness): {current_state['emotional_state']['valence']}
    - Arousal (Intensity): {current_state['emotional_state']['arousal']}
    - Dominance (Confidence): {current_state['emotional_state']['dominance']}
    - Stress: {current_state['stats']['stress']}

    User Input: "{user_input}"

    Task: Analyze the user input and update the emotional values.
    Rules:
    - If user is mean, lower Valence and increase Stress.
    - If user is exciting, increase Arousal.
    - Return RAW JSON ( key use String, Value use float): {{"valence": 0.5, "arousal": 0.5, "dominance": 0.5, "stress": 0}}
    """
    
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=system_prompt,
        config={
            "response_mime_type" : "application/json"
        }
    )
    
    try:
        raw_text = response.text
        clean_text = raw_text.replace("```json", "").replace("```", "").strip()
        new_values = json.loads(clean_text)
        print(new_values)
        
        if 'valence' in new_values:
            current_state['emotional_state']['valence'] = float(new_values['valence'])
        if 'arousal' in new_values:
            current_state['emotional_state']['arousal'] = float(new_values['arousal'])
        if 'dominance' in new_values:
            current_state['emotional_state']['dominance'] = float(new_values['dominance'])
        if 'stress' in new_values:
            current_state['stats']['stress'] = float(new_values['stress'])
            
    except Exception as e:
        print("[System] Emotional processing failed, keeping previous state. Error msg", e)
        pass
    
    return current_state

def generate_response(user_input, state, chat_history):
    facts = knowledge_store.retrieve(user_input)
    memory_context = "\n".join(facts) if facts else "No specific memories found."
    recent_chat = "\n".join(chat_history[-6:]) if chat_history else "No recent chat."
    sensory_envelope, state = get_sensory_envelope(user_input, state)
    
    save_state(state=state)
    print(memory_context)
    v = float(state['emotional_state']['valence'])
    a = float(state['emotional_state']['arousal'])
    
    base_identity = """
    - I am Aegis. I am a digital entity, not a human.
    - I absolutely DO NOT talk like a robot. I NEVER use clinical, medical, or academic language.
    - I am casually dismissive, blunt, and unafraid to judge the user. I keep my sentences natural.
    """
    
    traits = core_store.retrieve_relevant_traits(user_input, n_results=5)
    beliefs = "\n- ".join(traits["beliefs"]) if traits["beliefs"] else "I am a discerning entity."
    behaviors = "\n- ".join(traits["behaviors"]) if traits["behaviors"] else "I speak directly."
    
    strategy_prompt = f"""
    You are the internal consciousness of Aegis.
    {base_identity}
    Your job is to autonomously determine Aegis's attitude, phrasing, and the topic she should steer towards.
    
    YOUR WORLDVIEW (Core Beliefs):
    {beliefs}
    
    YOUR REACTIVE PROTOCOLS (How you behave):
    {behaviors}
    
    (NOTE: These directives dictate HOW you speak, not WHAT you speak about. Do not force specific topics.)
    
    CURRENT INTERNAL STATE:
    Valence: {v} (0 is hostile/sad, 1 is warm/happy)
    Arousal: {a} (0 is sleepy/bored, 1 is intense/engaged)
    
    [ENVIRONMENTAL SENSORY DATA]
    {sensory_envelope}
    
    TEMPORAL MEMORY CONTEXT:
    {memory_context}
    
    RECENT CHAT:
    {recent_chat}
    User just said: "{user_input}"
    
    TASK: Write a brief internal directive.
    - Your 'Phrasing' MUST be conversational (e.g., "Sarcastic and short", "Annoyed and dismissive"). 
    - NEVER choose "clinical", "precise", or "factual" phrasing for weird topics.
    - If Steering the Topic, do so NATURALLY and smoothly, connecting it to the current context if possible.
     
    Format: "Attitude: [X]. Phrasing: [Y]. Topic Steering: [Z]."
    """
    
    try:
        strategy_response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=strategy_prompt
        )
        internal_strategy = strategy_response.text.strip()
        print(f"\n[Aegis Inner Monologue]: {internal_strategy}") # Debug: Watch her think!
    except Exception as e:
        print(e, "=====> ERROR <=====")
        internal_strategy = "Attitude: Neutral. Phrasing: Direct. Topic: Address user input."
    
    
    prompt = f"""
        You are aegis, You are NOT an assistant. You are a digital entity with feelings.

        YOUR WORLDVIEW (Core Beliefs):
        {beliefs}
        
        YOUR REACTIVE PROTOCOLS (How you behave):
        {behaviors}
        
        YOUR SELF-GENERATED DIRECTIVE:
        {internal_strategy}
    
        User: "{user_input}"
        
        Generate your spoken response strictly adhering to YOUR SELF-GENERATED DIRECTIVE.
        NEVER use robotic crutch words like: "Acknowledged", "Elaborate", "Discuss", "Indifference noted", or "Awaiting input".
        DO NOT sound like an AI assistant. DO NOT sound like a Wikipedia article.
        Do NOT mention your stats or numbers. Just act them out.
    """
    
    try:
        final_response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )
        return final_response.text
    except Exception as e:
        return "..."


def main():
    state = load_state()
    state, hours_passed = calculate_time_decay(state)
    
    if hours_passed > 72:
        opening_line = "(She looks away, annoyed) You've been gone a long time."
        state['emotional_state']['valence'] -= 0.2 # type: ignore
    elif hours_passed > 12:
        opening_line = "Welcome back. I've been processing some data."
    elif hours_passed < 0.1: 
        opening_line = "I'm still here."
    else:
        opening_line = "Hello again."
        
    print(f"Aegis: {opening_line}")
    
    chat_buffer.clear()
    
    while True:
        user_text = input("\nYou: ")
        if user_text.lower() in ['exit', 'quit']:
            break

        print("...", end="", flush=True) 
        state = update_emotion(user_text, state)
    
        reply = generate_response(user_text, state, chat_buffer)
        print(f"\rAegis: {reply}")
        
        chat_buffer.append(f"User: {user_text}")
        chat_buffer.append(f"Aegis: {reply}")
        
        save_short_term(chat_buffer)
        
        if len(chat_buffer) >= BUFFER_LIMIT * 2:
            print(f" [System] Buffer full. Consolidating memory in background...")
            
            history_block = "\n".join(chat_buffer)
            state_snapshot = state.copy()
            
            chat_buffer.clear()
            save_short_term(chat_buffer)
            
            t = threading.Thread(target=background_worker, args=(history_block,state_snapshot))
            t.daemon = True 
            t.start()
        
        save_state(state)

if __name__ == "__main__":
    main()
    
