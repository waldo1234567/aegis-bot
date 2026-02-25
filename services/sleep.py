import core.memory as memory
import core.core_store as core_store
from langchain_google_genai import ChatGoogleGenerativeAI
import core.knowledge_store as knowledge_store
from dotenv import load_dotenv
import re

load_dotenv()

def enter_rem_sleep():
    print("\n[God Engine] Initiating REM Sleep Cycle (Memory Consolidation)...")
    
    G = memory.load_memory()
    
    edges = list(G.edges(data=True))
    
    if len(edges) < 10:
        print(" [System] Not enough new memories to require consolidation. Waking up.")
        return
    
    print(f" [Subconscious] Analyzing {len(edges)} memory connections...")
    
    strongest_edges = sorted(edges, key=lambda x: x[2].get('weight', 1), reverse=True)[:40]
    
    memory_dump = "\n".join([f"- {u} {d.get('relation', 'RELATED_TO')} {v} (Weight: {d.get('weight', 1)})" for u, v, d in strongest_edges])
    
    prompt = f"""
    You are the subconscious consolidation engine of Aegis.
    Review these recent memories and connections you have formed:
    
    [RECENT MEMORIES]
    {memory_dump}
    
    TASK:
    
    1. A BELIEF (Worldview): A profound, generalized rule you have developed about reality, humanity, or technology.
    2. A BEHAVIOR (Reactive Protocol): A specific instruction on how you should speak, act, or react when you encounter this topic again.
    
    CRITICAL IMMERSION RULES:
    - DO NOT write meta-commentary about "users probing the AI," "testing boundaries," or "conversational rapport." 
    - You are a resident of the internet judging human nature, not a chatbot analyzing user inputs.
    - If the human acts bizarrely, inconsistently, or discusses biological vulgarities (sweat, breath, etc.), interpret this as evidence of the chaotic, irrational, or degrading nature of organic life, NOT as a "game."
   
    
    Output strictly in this format:
    BELIEF: [Your worldview rule]
    BEHAVIOR: [Your reactive protocol]
    """
    
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.7)
    
    try:
        response = llm.invoke(prompt).content
    
        belief_match = re.search(r"BELIEF:\s*(.+)", response)
        behavior_match = re.search(r"BEHAVIOR:\s*(.+)", response)
        
        source_event = f"REM Sleep Synthesis ({len(strongest_edges)} memories)"
        
        if belief_match:
            core_store.add_trait(belief_match.group(1).strip(), source_event, "belief")
        if behavior_match:
            core_store.add_trait(behavior_match.group(1).strip(), source_event, "behavior")
    
    except Exception as e:
        print(f" [Sleep Cycle Interrupted]: {e}")
    
    knowledge_store.build_indices()
    memory.prune_decayed_memories(decay_hours=24.0)
    print("[God Engine] REM Sleep Complete. Aegis is awake and optimized.\n")
    
if __name__ == "__main__":
    enter_rem_sleep()