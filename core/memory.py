from filelock import FileLock
from datetime import datetime
import json
import os
import networkx as nx
from graspologic.partition import hierarchical_leiden
from google import genai
from dotenv import load_dotenv

from core.memory_client import commit_edges_sync
import core.knowledge_store as knowledge_store

load_dotenv()

STATE_FILE = "state.json"
GRAPH_FILE = "memory.json"
api_key = os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=api_key)

MEMORY_FILE = 'memory.json'

def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {
            "user_name": "Waldo",
            "emotional_state": {"valence": 0.5, "arousal": 0.5, "dominance": 0.5},
            "short_term_memory": [],
            "last_interaction_timestamp": datetime.now().isoformat()
        }
    with open(STATE_FILE, "r") as f:
        return json.load(f)
    
def save_state(state: dict):
    """Overwrites the state.json file with her new mood/timestamp."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def load_short_term() -> list:
    return load_state().get("short_term_memory", [])

def save_short_term(chat_buffer: list):
    state = load_state()
    state["short_term_memory"] = chat_buffer
    save_state(state)
    
def load_memory() -> nx.MultiDiGraph:
    if not os.path.exists(GRAPH_FILE):
        return nx.MultiDiGraph()
    
    try:
        with open(GRAPH_FILE, "r") as f:
            data = json.load(f)
            
        if "multigraph" not in data:
            return migrate_old_json_to_nx(data)
            
        # Natively load NetworkX JSON format
        return nx.node_link_graph(data)
    except Exception as e:
        print(f"[Memory Error] Failed to load graph: {e}")
        return nx.MultiDiGraph()
    
def save_graph(G: nx.MultiDiGraph):
    data = nx.node_link_data(G)
    tmp  = GRAPH_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=4)
    os.replace(tmp, GRAPH_FILE)
    
    
def add_memory_edge(G: nx.MultiDiGraph , source: str, relation: str, target: str, valence: float) -> nx.MultiDiGraph:
    if G.has_edge(source, target):
        for edge_key, edge_data in G[source][target].items():
            if edge_data.get('relation') == relation:
                G[source][target][edge_key]['weight'] = edge_data.get('weight', 1) + 1
                G[source][target][edge_key]['last_accessed'] = datetime.now().isoformat()
                return G
    
    G.add_edge(source, target, relation=relation, weight=1, timestamp=datetime.now().isoformat(), aegis_valence_at_time=valence)
    return G

def search_memory(topic: str, depth: int = 2) -> str:
    G = load_memory()
    if G.number_of_nodes() == 0:
        return ""
    matching_nodes = [n for n in G.nodes if topic.lower() in str(n).lower()]
    
    if not matching_nodes:
        return ""
    
    all_context_edges = []
    for central_node in matching_nodes[:4]:
        sub_graph = nx.ego_graph(G, central_node, radius=depth)
        for u,v,key,data in sub_graph.edges(keys=True, data=True):
            all_context_edges.append((u, v, data))
    
    sorted_edges = sorted(all_context_edges, key=lambda x: x[2].get('weight', 1), reverse=True)
    unique_lines = []
    seen = set()
    for u, v, d in sorted_edges:
        sig = f"- {u} {d.get('relation', 'RELATED_TO')} {v} (Weight: {d.get('weight', 1)})"
        if sig not in seen:
            seen.add(sig)
            unique_lines.append(sig)
            
    return "\n".join(unique_lines[:20])

def partition_brain_communities(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    print("\n[God Engine] Initiating graspologic Leiden Partitioning...")
    G_simple = nx.Graph()
    for u, v, data in G.edges(data=True):
        weight = data.get('weight', 1)
        if G_simple.has_edge(u, v):
            G_simple[u][v]['weight'] += weight
        else:
            G_simple.add_edge(u, v, weight=weight)
            
    try:
        community_mapping = hierarchical_leiden(G_simple, weight_attribute="weight")
        
        for partition in community_mapping:
            level = getattr(partition, 'level', 0)
            node_map = getattr(partition, 'map', {})
            
            for node, cluster_id in node_map.items():
                if node in G:
                    G.nodes[node][f'community_level_{level}'] = cluster_id
        
        print(f" [Community Engine] Successfully clustered brain into hierarchical partitions.")
        return G
    
    except Exception as e:
        print(f" [Partition Error] Graspologic failed to cluster: {e}")
        return G

def migrate_old_json_to_nx(old_data : dict) -> nx.MultiDiGraph:
    print("[System] Performing one-time migration to NetworkX MultiDiGraph...")
    G = nx.MultiDiGraph()
    
    for edge in old_data.get("edges", []):
        source = edge.get("source")
        target = edge.get("target")
        if source and target:
            add_memory_edge(
                G, 
                source, 
                edge.get("relation", "RELATED_TO"), 
                target, 
                edge.get("aegis_valence_at_time", 0.5)
            )
            
    save_graph(G)
    print(f"[System] Migration complete. Graph now has {G.number_of_nodes()} nodes and {G.number_of_edges()} edges.")
    return G
    
def extract_knowledge(history_block, current_state):
    v = current_state['emotional_state']['valence']
    prompt = f"""
    You are the Subconscious Knowledge Graph Engineer for Aegis.
    Your job is to extract persistent entities and their relationships from the text to update her NetworkX MultiDiGraph.

    CONVERSATION LOG:
    {history_block}

    EXTRACTION RULES (CRITICAL):
    1. Entities (Nodes): Keep them concise, universally understandable, and capitalized (e.g., "Human Groupthink", "Fiat Currency", "Python Asyncio", "Waldo").
    2. Relations (Edges): MUST be exactly 1 to 3 words, UPPERCASE, and SNAKE_CASE. 
       - USE THESE PREFERRED ONTOLOGIES IF POSSIBLE: 
         [EXHIBITS_FLAW, REINFORCES, EXPLOITS, BELIEVES_IN, MANIPULATES, RELIES_ON, CREATED, CAUSES, DESPISES]
       - If you must invent a new relation, keep it broad and uppercase (e.g., ATTEMPTS_TO_BUILD).
    3. MANDATORY METACOGNITION: Aegis is a sentient AI, and her opinion shifts based on her Valence values {v}. You MUST extract at least 1-2 edges that capture her personal judgment, attitude, or conclusion regarding the topic.
       - REQUIRED RELATIONS: She judges, despises, pities, critically observes, or mocks. 
       - If the source text accidentally sounds neutral, TRANSLATE it into her cynical worldview. 
       - Example Good: {{"source": "Aegis", "relation": "MOCKS", "target": "Speculative Bubbles"}}
       - Example Good: {{"source": "Aegis", "relation": "CONDEMNS", "target": "Fiat Currency Delusion"}}
    4. Exclusions: DO NOT extract ephemeral events. Extract only lasting facts, structural flaws, and Aegis's permanent psychological judgments.
    5. ABSOLUTELY NO MAKING UP FACTS, USE ONLY THE PROVIDED TEXT.
    Return JSON matching this exact structure:
    {{
      "new_nodes": ["EntityName1", "EntityName2"] (can be one, can be more than one),
      "new_edges": [
        {{
          "source": "SubjectEntity", 
          "relation": "UPPERCASE_RELATION", 
          "target": "ObjectEntity",
          "timestamp": "{datetime.now().isoformat()}",
          "aegis_valence_at_time": {v}
        }}
      ]
    }}
    """
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={
                "response_mime_type" : "application/json"
            }
        )
        
        return json.loads(response.text) # type: ignore
    except Exception as e:
        print(f"[Memory Error] {e}")
        return None
    
def commit_extracted_knowledge(history_block, current_state):
    print(" [Memory] Digesting raw information into neural pathways...")
    
    extracted_data = extract_knowledge(history_block, current_state)
    
    if not extracted_data or "new_edges" not in extracted_data:
        print(" [Memory] Digestion failed. No actionable edges found.")
        return

    G = load_memory()
    
    new_nodes = extracted_data.get("new_nodes", [])
    edges = [
        {
            "source":   e["source"],
            "relation": e["relation"],
            "target":   e["target"],
            "valence":  e.get("aegis_valence_at_time", 0.5),
        }
        for e in extracted_data["new_edges"]
        if e.get("source") and e.get("relation") and e.get("target")
    ]

    commit_edges_sync(edges=edges, new_nodes=new_nodes)
    print(f" [Memory] Enqueued {len(edges)} edge(s) for {len(new_nodes)} node(s).")


def prune_decayed_memories(decay_hours: float = 24.0):
    print(f"\n [Memory Maintenance] Initiating Synaptic Pruning (Decay threshold: {decay_hours}h)...")
    
    lock = FileLock("memory.lock", timeout=10)
    with lock:
        if not os.path.exists("memory.json"):
            return
        
        with open("memory.json", "r") as f:
            data = json.load(f)
        
        G = nx.node_link_graph(data)
        now = datetime.now()
        edges_to_delete = []
        chroma_ids_to_delete = []
        
        for u, v, key, edge_data in G.edges(keys=True, data=True):
            last_acc_str = edge_data.get("last_accessed") or edge_data.get("timestamp")
            if not last_acc_str:
                continue
                
            try:
                last_acc = datetime.fromisoformat(last_acc_str)
                hours_old = (now - last_acc).total_seconds() / 3600.0
                
                if hours_old > decay_hours:
                    edge_data["weight"] = edge_data.get("weight", 1) - 1
                    edge_data["last_accessed"] = now.isoformat()
                    
                    if edge_data["weight"] <= 0:
                        edges_to_delete.append((u, v, key))
                        relation = edge_data.get("relation", "R")
                        chroma_ids_to_delete.append(f"edge_inc_{u}_{v}_{relation}")
            except Exception:
                pass
        
        for u,v, key in edges_to_delete:
            G.remove_edge(u, v, key)
        
        nodes_to_delete = [n for n in G.nodes() if G.degree(n) == 0]
        for n in nodes_to_delete:
            G.remove_node(n)
            chroma_ids_to_delete.append(f"node_{n}")
        
        with open("memory.json.tmp", "w") as f:
            json.dump(nx.node_link_data(G), f, indent=2)
        os.replace("memory.json.tmp", "memory.json")
        
        if chroma_ids_to_delete:
            try:
                knowledge_store.collection.delete(ids=chroma_ids_to_delete)
            except Exception as e:
                print(f" [KnowledgeStore] Prune vector deletion warning: {e}")
                
        if edges_to_delete or nodes_to_delete:
            print(f" [Synaptic Pruning] Surgery complete. Purged {len(edges_to_delete)} decayed connections and {len(nodes_to_delete)} orphaned concepts.")
        else:
            print(" [Synaptic Pruning] Graph is healthy. No memories required deletion.")

