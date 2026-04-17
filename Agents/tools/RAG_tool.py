import asyncio, io, base64, os, pdfplumber, ollama  
from lightrag import LightRAG, QueryParam
from lightrag.llm.ollama import ollama_model_complete, ollama_embed
from lightrag.utils import EmbeddingFunc
from sentence_transformers import CrossEncoder
from lightrag.kg.shared_storage import initialize_pipeline_status
from lightrag.utils import setup_logger
from huggingface_hub import login
import neo4j
from dotenv import load_dotenv

load_dotenv()
HF_TOKEN = os.getenv('HF_TOKEN')


WORKING_DIR = r"D:\brian\2pdf"
setup_logger("lightrag", level="INFO")
os.makedirs(WORKING_DIR, exist_ok=True)

# Storage Mode (for querying, e.g., "hybrid")
MODE = "hybrid" 
COMPLETION_MODEL = "gemma4:e4b"
EMBEDDING_MODEL = "nomic-embed-text"
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"

FOLDER_PATH = r"D:\brian\2pdf"


os.environ["POSTGRES_HOST"] = os.getenv('PG_HOST')  
os.environ["POSTGRES_PORT"] = os.getenv('PG_PORT')
os.environ["POSTGRES_USER"] = os.getenv('PG_USER')
os.environ["POSTGRES_PASSWORD"] = os.getenv('PG_PASSWORD')
os.environ["POSTGRES_DATABASE"] = os.getenv('PG_LIGHTRAG')
POSTGRES_WORKSPACE = "default" # Make sure js give lightrag an abt empty db for it to generate its things in postgres

os.environ["NEO4J_URI"] = os.getenv('NEO4J_URI')
os.environ["NEO4J_USERNAME"] = os.getenv('NEO4J_USER')
os.environ["NEO4J_PASSWORD"] = os.getenv('NEO4J_PASS')
os.environ["NEO4J_DATABASE"] = os.getenv('NEO4J_DB')

reranker = CrossEncoder(RERANK_MODEL, device="cuda")

def rerank_func(query: str, documents: list[str]) -> list[float]:
    pairs = [(query, doc) for doc in documents]
    scores = reranker.predict(pairs)
    return scores.tolist()

rag = LightRAG(
    working_dir=WORKING_DIR,
    llm_model_func=ollama_model_complete,
    llm_model_name=COMPLETION_MODEL,                      
    llm_model_kwargs={"options": {"num_ctx": 32768}},
    embedding_func=EmbeddingFunc(
        embedding_dim=768,
        max_token_size=8192,
        func=lambda texts: ollama_embed(
            texts,
            embed_model=EMBEDDING_MODEL
        )
    ),
    rerank_model_func=rerank_func,

    kv_storage="PGKVStorage",
    vector_storage="PGVectorStorage",
    doc_status_storage="PGDocStatusStorage",
    graph_storage="Neo4JStorage", 
)

def page_to_base64(page) -> str:
    img = page.to_image(resolution=150).original
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()

def summarize_page(image_b64: str) -> str:
    response = ollama.chat(
        model=COMPLETION_MODEL,  
        messages=[{
            "role": "user",
            "content": "Summarise this page in detail. Include tables, diagrams, and key data.",
            "images": [image_b64]
        }]
    )
    return response["message"]["content"]

def process_pdf(file_path: str) -> str:
    all_text = []
    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            print(f"Processing page {i}/{len(pdf.pages)}...")
            image_b64 = page_to_base64(page)
            summary = summarize_page(image_b64)
            all_text.append(f"[Page {i}]\n{summary}")
    return "\n\n".join(all_text)

async def process_folder(folder_path: str):
    pdf_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.pdf')]
    if not pdf_files:
        print(f"No PDF files found in {folder_path}")
        return
    
    print(f"Found {len(pdf_files)} PDF file(s) in {folder_path}")
    for pdf_file in pdf_files:
        file_path = os.path.join(folder_path, pdf_file)
        print(f"\n--- Processing document: {pdf_file} ---")

        doc_text = process_pdf(file_path)
        
        print(f"Inserting {pdf_file} into LightRAG...")
        await rag.ainsert(doc_text)

def rag_query(query: str) -> str:
    return asyncio.run(rag.aquery(
        query=query,
        param=QueryParam(mode=MODE)
    ))
