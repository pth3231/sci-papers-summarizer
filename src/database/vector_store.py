import chromadb

client = chromadb.PersistentClient(path="./chroma_db")
collection = client.get_or_create_collection(name="documents")

def add_chunk(chunk_id: str, text: str, embedding: list[float], document_id: str, chunk_index: int):
    collection.add(ids=[chunk_id], documents=[text], embeddings=[embedding],
        metadatas=[
            {
                "document_id": document_id,
                "chunk_index": chunk_index,
            }
        ],
    )

def search_chunks(query_embedding: list[float], top_k: int = 5,):
    results = collection.query(query_embeddings=[query_embedding], n_results=top_k)
    return results