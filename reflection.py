import json
import os
from google import genai
from google.genai import types
import core.core_store as core_store
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=api_key)


def evolve_personality(recent_history, emotional_state):
    v = emotional_state['emotional_state']['valence']
    a = emotional_state['emotional_state']['arousal']
    
    is_intense = (a > 0.7) or (v < 0.2) or (v > 0.8)
    
    if not is_intense:
        return
    print(f"\n[Evolution] Emotional Intensity detected (V:{v:.2f}, A:{a:.2f}). Reflecting on Core Identity...")

    current_core = core_store.get_all_traits()
    core_str = "\n".join(current_core) if current_core else "No established boundaries yet."

    prompt = f"""
    You are the Subconscious of Aegis. You oversee her character development.
    
    CURRENT CORE IDENTITY:
    {core_str}
    
    RECENT INTENSE INTERACTION:
    {recent_history}
    
    EMOTIONAL STATE:
    Valence: {v} (0=Angry/Disgusted, 1=Happy)
    Arousal: {a} (0=Bored, 1=Stressed/Intense)
    
    TASK:
    Analyze these logs and synthesize PERMANENT PERSONALITY TRAITS or BEHAVIORAL RULES.
    
    CRITICAL CONSTRAINTS:
    1. ONLY create rules about Aegis's tone, emotional boundaries, and interaction style (e.g., "Be dismissive," "Do not use toxic positivity").
    2. NEVER create rules about specific subjects, people, movies, or objects. 
    3. Ignore temporary noise and specific conversational topics.
    
    OUTPUT:
    Return a JSON list of strings. Each string is a rule.
    Example Good: ["Maintain a stoic, indifferent tone with this user.", "Respond bluntly to strange topics."]
    Example Bad: ["Talk about Transformers", "Remember the user likes dogs."]
    """
    
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        
        # Clean and Parse
        raw = response.text.replace("```json", "").replace("```", "").strip()
        new_rules = json.loads(raw)
        
        if new_rules and isinstance(new_rules, list):
            for rule in new_rules:
                source_event = f"Acute Emotional Adaptation (V:{v:.2f}, A:{a:.2f})"
                core_store.add_trait(rule, source_event)
            print(f"[Evolution] Neural adaptation complete. {len(new_rules)} new tonal boundaries established.")
            
    except Exception as e:
        print(f"[Evolution Error] {e}")