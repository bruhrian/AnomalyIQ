# TODO list
# - Will need to see which embedding model to switch to

import ollama
import os
from dotenv import load_dotenv
from qdrant_client import QdrantClient, models
import time

load_dotenv()

qdrantClient = QdrantClient(path=os.getenv('VectorStoreDB'))
collection_name = "anomaly_soln_storage"
search_limit = 3
view_limit = 100

model = 'qwen3-embedding:0.6b'
model_dims=1024

def create_vDB():
    qdrantClient.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(
            size=model_dims,
            distance=models.Distance.COSINE,
        )
    )
    print("Database created!")

class RAG_solution:
    def __init__(self, anomaly_soln: str, metadata):
        self.anomaly_soln = anomaly_soln
        self.metadata = metadata

    def retrieve(self, anomaly: str):
        anomaly_embed = ollama.embed(
            model=model,
            input=anomaly,
            dimensions=model_dims
        )

        input_vector = anomaly_embed['embeddings'][0]

        search_results = qdrantClient.query_points(
            collection_name=collection_name,
            query=input_vector,
            limit=search_limit
        )

        points = search_results.points

        if points:
            best_match = points[0]
            solution_text = best_match.payload['anomaly_soln_text']
            similar_anomaly = best_match.payload['anomaly_soln_text']
        
            retAnomalySoln = {
                "status": "success",
                "anomaly": anomaly,
                "referred_pair": similar_anomaly,  
                "solution": solution_text,          
                "similarity_score": best_match.score,
                "metadata": best_match.payload['metadata']
            }
        
        else:
            retAnomalySoln = {
                "status": "no match found",
                "anomaly": anomaly,
                "referred_pair": None,
                "solution": None
            }
        
        return retAnomalySoln

    def addEmbeddings(self, anomaly_soln, metadata):
        anomaly_soln_embed = ollama.embed(
            model=model,
            input=anomaly_soln,
            dimensions=model_dims
        )

        new_vector = anomaly_soln_embed['embeddings'][0]
        point_id = int(time.time() * 1000)

        qdrantClient.upsert(
            collection_name=collection_name,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector=new_vector,
                    payload={
                        "anomaly_soln_text": anomaly_soln,
                        "metadata": metadata,
                    }
                )
            ]
        )

        status = {
            "status": "New vectors added into the database",
            "point_id": point_id,
            "anomaly_soln": anomaly_soln,
            "metadata": metadata,
        }
        
        return status

    def deleteEmbeddings(self, point_id):
        try:
            retrieved = qdrantClient.retrieve(
                collection_name=collection_name,
                ids=[point_id]
            )
            
            if retrieved:
                # Get the anomaly solution text from the payload
                anomaly_soln = retrieved[0].payload.get('anomaly_soln_text', 'Unknown')
                metadata = retrieved[0].payload.get('metadata', {})
            else:
                anomaly_soln = "Entry not found"
                metadata = {}
            
        except Exception as e:
            anomaly_soln = f"Error retrieving: {e}"
            metadata = {}
        
        qdrantClient.delete(
            collection_name=collection_name,
            points_selector=[point_id]
        )
    
        status = {
            "status": "Vectors deleted from the database",
            "point_id": point_id,
            "deleted_anomaly_soln": anomaly_soln,
            "deleted_metadata": metadata
        }
        
        return status
    
    def viewEntries(self, filter_condition=None, limit=view_limit):
        if filter_condition:
            # Scroll with filter
            entries = qdrantClient.scroll(
                collection_name=collection_name,
                scroll_filter=filter_condition,
                limit=limit,
                with_payload=True,
                with_vectors=False  # We don't need to see the vectors
            )
        else:
            # Scroll all entries
            entries = qdrantClient.scroll(
                collection_name=collection_name,
                limit=limit,
                with_payload=True,
                with_vectors=False
            )
        
        points = entries[0]  # The actual points
        
        if not points:
            print("No entries found in database")
            return
        
        print(f"Found {len(points)} entries:")
        print("-" * 80)
        
        for point in points:
            print(f"Point ID: {point.id}")
            print(f"Solution: {point.payload.get('anomaly_soln_text', 'N/A')[:100]}...")
            print(f"Metadata: {point.payload.get('metadata', {})}")
            print(f"Score: {point.score if hasattr(point, 'score') else 'N/A'}")
            print("-" * 80)
        
        return points