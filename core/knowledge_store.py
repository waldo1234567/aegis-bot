import uuid
import chromadb
import networkx as nx
from graspologic.partition import hierarchical_leiden
from chromadb.utils import embedding_functions
import core.memory as memory
from core.memory_daemon import get_daemon

MEMORY_FILE = "memory.json"
CHROMA_PATH = "./chroma_db"

ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")

client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = client.get_or_create_collection(name="aegis_memory", embedding_function=ef)

_partition_cache: dict[str, int] = {}

def _compute_partition(G: nx.MultiDiGraph) -> dict[str, int]:
    simple = nx.Graph()
    for u, v, data in G.edges(data=True):
        weight = data.get("weight", 1)
        if simple.has_edge(u, v):
            simple[u][v]["weight"] += weight
        else:
            simple.add_edge(u, v, weight=weight)

    if simple.number_of_nodes() == 0:
        return {}

    try:
        communities = hierarchical_leiden(simple, weight_attribute="weight")
        return {c.node: c.cluster for c in communities}
    except Exception as e:
        print(f" [KnowledgeStore] Leiden failed: {e}. Using flat partition.")
        return {n: 0 for n in G.nodes()}

def _node_document(node_id: str, cluster_id: int, neighbors: list[str]) -> str:
    return (f"{node_id} (Cluster {cluster_id}). "
            f"Related to: {', '.join(neighbors[:5])}")


def _edge_document(u: str, v: str, data: dict) -> str:
    return (f"{u} {data.get('relation', 'RELATED_TO')} {v} "
            f"(Synaptic Strength: {data.get('weight', 1)})")

    
def build_indices():
    global _partition_cache
    
    print(" [System] Rebuilding GraphRAG Indices...", end="", flush=True)
    G = memory.load_memory()
    
    if G.number_of_nodes() == 0:
        print(" (Skipped: Empty Memory)")
        return
    
    _partition_cache = _compute_partition(G)
    
    ids = []
    documents = []
    metadatas = []
    
    for node_id in G.nodes():
        cluster_id = _partition_cache.get(node_id, 0)
        in_nb = list(G.predecessors(node_id))
        out_nb = list(G.successors(node_id))
        all_nb = list(set(in_nb + out_nb))
        doc = _node_document(node_id, cluster_id, all_nb)
        
        ids.append(f"node_{node_id}")
        documents.append(doc)
        metadatas.append({"type": "node", "cluster": cluster_id})
        
    for idx, (u, v, data) in enumerate(G.edges(data=True)):
        ids.append(f"edge_{idx}_{u}_{v}")
        documents.append(_edge_document(u, v, data))
        metadatas.append({"type": "fact", "cluster": -1,
                          "weight": data.get("weight", 1)})
        
    if ids:
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        
    print("done.")
    _register_daemon_callback()
    
    
async def index_dirty(dirty_nodes: set):
    if not dirty_nodes:
        return
    
    print(f" [KnowledgeStore] Incremental index: {len(dirty_nodes)} dirty node(s)...")
    G = memory.load_memory()
    ids, documents, metadatas = [], [], []
    seen_ids = set()
    
    for node_id in dirty_nodes:
        if not G.has_node(node_id):
            try:
                collection.delete(ids=[f"node_{node_id}"])
            except Exception:
                pass
            continue
            
        cluster_id = _partition_cache.get(node_id, 0)
        in_nb = list(G.predecessors(node_id))
        out_nb = list(G.successors(node_id))
        all_nb = list(set(in_nb + out_nb))
        
        node_chroma_id = f"node_{node_id}"
        if node_chroma_id not in seen_ids:
            seen_ids.add(node_chroma_id)
            ids.append(node_chroma_id)
            documents.append(_node_document(node_id, cluster_id, all_nb))
            metadatas.append({"type": "node", "cluster": cluster_id})

        for idx, (u, v, data) in enumerate(G.edges(node_id, data=True)):
            edge_id = f"edge_inc_{u}_{v}_{data.get('relation', 'R')}"
            if edge_id not in seen_ids:
                seen_ids.add(edge_id)
                ids.append(edge_id)
                documents.append(_edge_document(u, v, data))
                metadatas.append({"type": "fact", "cluster": -1,
                                  "weight": data.get("weight", 1)})

        for idx, (u, v, data) in enumerate(G.in_edges(node_id, data=True)):
            edge_id = f"edge_inc_{u}_{v}_{data.get('relation', 'R')}"
            if edge_id not in seen_ids:  
                seen_ids.add(edge_id)
                ids.append(edge_id)
                documents.append(_edge_document(u, v, data))
                metadatas.append({"type": "fact", "cluster": -1,
                                  "weight": data.get("weight", 1)})
    if ids:
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        print(f" [KnowledgeStore] Incremental upsert: {len(ids)} item(s).")
    
    
def retrieve(query_text, n_results = 5):
    results = collection.query(
        query_texts=[query_text],
        n_results=n_results
    )
    
    retrieved_info = []
    
    if results['documents']:
        for i, doc in enumerate(results['documents'][0]):
            meta = results['metadatas'][0][i]
            retrieved_info.append(f"- {doc} [{meta['type']}]")
            
    return retrieved_info

def store_engineering_lesson(topic: str, lesson: str):
    doc_id = f"lesson_{uuid.uuid4().hex[:8]}"
    doc_text = f"Engineering Lesson for '{topic}':\n{lesson}"
    
    collection.upsert(
        ids=[doc_id],
        documents=[doc_text],
        metadatas=[{"type": "engineering_lesson", "cluster": -1, "weight": 5}]
    )
    print(" [KnowledgeStore] Engineering trauma permanently encoded into vector space.")

def _register_daemon_callback():
    daemon = get_daemon()
    
    if index_dirty not in daemon._callbacks:
        daemon.register_on_commit(index_dirty)
        print(" [KnowledgeStore] Registered incremental index callback with daemon.")



if __name__ == "__main__":
    build_indices()