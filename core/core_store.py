import chromadb
from chromadb.utils import embedding_functions
import hashlib

CHROMA_PATH = "./chroma_db" 
COLLECTION_NAME = "core_personality"

ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = client.get_or_create_collection(name=COLLECTION_NAME, embedding_function=ef)

def add_trait(trait_text: str, source_event: str,trait_type: str = "belief"):
    trait_id = hashlib.md5(trait_text.encode()).hexdigest()
    
    print(f" [Core] Engraining new trait: '{trait_text}'")
    
    collection.upsert(
        ids=[trait_id],
        documents=[trait_text],
        metadatas=[{"source_event": source_event, "type": trait_type}]
    )
    
def retrieve_relevant_traits(context_text: str, n_results: int = 5) -> dict:
    results = collection.query(
        query_texts=[context_text],
        n_results=n_results
    )
    
    structured = {"beliefs": [], "behaviors": []}
    if results['documents'] and results['metadatas']:
        for doc, meta in zip(results['documents'][0], results['metadatas'][0]):
            t_type = meta.get('type', 'belief')
            if t_type == 'behavior':
                structured['behaviors'].append(doc)
            else:
                structured['beliefs'].append(doc)
                
    return structured

def  get_structured_traits() -> dict:
    result = collection.peek(limit=100)
    structured = {"beliefs": [], "behaviors": []}
    
    if not result['documents'] or not result['metadatas']:
        return structured
        
    for doc, meta in zip(result['documents'], result['metadatas']):
        t_type = meta.get('type', 'belief')
        if t_type == 'behavior':
            structured['behaviors'].append(doc)
        else:
            structured['beliefs'].append(doc)
            
    return structured

def get_all_traits():
    result = collection.peek(limit=100)
    return result['documents']