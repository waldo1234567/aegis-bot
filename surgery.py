import chromadb

# Connect to the DB
client = chromadb.PersistentClient(path="./chroma_db")
collection = client.get_collection(name="core_personality")

# Fetch all traits
results = collection.get()

print("Current Traits in Aegis's Core:")
for i, doc in enumerate(results['documents']):
    print(f"[{i}] ID: {results['ids'][i]} | Trait: {doc}")

# Look for the Transformers rule and delete it
for i, doc in enumerate(results['documents']):
    if "Transformers" in doc or "Megan Fox" in doc:
        bad_id = results['ids'][i]
        print(f"\n[Surgery] Deleting obsessive trait: '{doc}'")
        collection.delete(ids=[bad_id])
        print("Deletion successful.")

print("\nSurgery complete. Aegis is cured.")