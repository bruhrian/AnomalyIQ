import asyncio, io, base64, os, pdfplumber, ollama  
from lightrag import LightRAG, QueryParam
from lightrag.llm.ollama import ollama_model_complete, ollama_embed
from lightrag.utils import EmbeddingFunc
from sentence_transformers import CrossEncoder
from lightrag.kg.shared_storage import initialize_pipeline_status
from lightrag.utils import setup_logger
import ollama as ollama_client_lib
from huggingface_hub import login
import neo4j
from dotenv import load_dotenv
import tiktoken
import numpy as np

load_dotenv()
HF_TOKEN = os.getenv('HF_TOKEN') # for initial downloading of models

enc = tiktoken.get_encoding("cl100k_base")

WORKING_DIR = r"D:\brian\5g lab\lightrag" # can be replaced with less hardcoded directory
setup_logger("lightrag", level="INFO")
os.makedirs(WORKING_DIR, exist_ok=True)

# Storage Mode (for querying, e.g., "hybrid")
MODE = "hybrid"  
COMPLETION_MODEL = "gemma4:e4b"
EMBEDDING_MODEL = "mxbai-embed-large"
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"

# this is whr, u pass the directory of the folder of the pdf documents 
# that you want to be indexed 
# can be replaced with less hardcoded directory
FOLDER_PATH = r"D:\brian\Manuals" 

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

# reranking function
def rerank_func(query: str, documents: list[str]) -> list[float]:
    pairs = [(query, doc) for doc in documents]
    scores = reranker.predict(pairs)
    return scores.tolist()

# converts texts to embeddings and output in np array format
async def safe_embed(texts: list[str]) -> list[list[float]]:
    MAX_CHARS = 1500
    client = ollama_client_lib.AsyncClient()
    results = []
    print(f"  [safe_embed] called with {len(texts)} texts")  # ← confirm entry
    for t in texts:
        t = t[:MAX_CHARS]
        response = await client.embed(model=EMBEDDING_MODEL, input=t)
        results.append(response.embeddings[0])
    return np.array(results)

# initialise the Lightrag
rag = LightRAG(
    working_dir=WORKING_DIR,
    llm_model_func=ollama_model_complete,
    llm_model_name=COMPLETION_MODEL,                      
    llm_model_kwargs={"options": {"num_ctx": 32768}},
    embedding_func=EmbeddingFunc(
        embedding_dim=1024,
        max_token_size=256,
        func=safe_embed
    ),
    rerank_model_func=rerank_func,

    # Storage declaration
    kv_storage="PGKVStorage",
    vector_storage="PGVectorStorage",
    doc_status_storage="PGDocStatusStorage",
    graph_storage="Neo4JStorage", 
)

# convert doc page to base64
def page_to_base64(page) -> str:
    img = page.to_image(resolution=150).original
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()

# use completion model to summarise page
def summarize_page(image_b64: str) -> str:
    response = ollama.chat(
        model=COMPLETION_MODEL,  
        messages=[{
            "role": "user",
            "content": "Summarise this page in detail in under 300 words. Include tables, diagrams, and key data.",
            "images": [image_b64]
        }]
    )
    return response["message"]["content"]

# shorten max characters
def truncate_to_tokens(text: str, max_tokens: int = 200) -> str:
    """Rough truncation: ~4 chars per token as a safe approximation."""
    max_chars = max_tokens * 4
    return text[:max_chars] if len(text) > max_chars else text

# workflow function for image processing, summarise page & summarise and tokenise
# for single pdf
def process_pdf(file_path: str) -> str:
    all_text = []
    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            print(f"Processing page {i}/{len(pdf.pages)}...")
            image_b64 = page_to_base64(page)
            summary = summarize_page(image_b64)
            summary = truncate_to_tokens(summary, max_tokens=200)  # ← hard cap
            all_text.append(f"[Page {i}]\n{summary}")
    return "\n\n".join(all_text)

# workflow function for image processing, summarise page & summarise and tokenise
# for whole folder
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

async def clear_failed_documents():
    import asyncpg
    conn = await asyncpg.connect(
        host=os.getenv('PG_HOST'),
        port=int(os.getenv('PG_PORT')),
        user=os.getenv('PG_USER'),
        password=os.getenv('PG_PASSWORD'),
        database=os.getenv('PG_LIGHTRAG')
    )

    # Check what the tables are actually named first
    tables = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename ILIKE 'lightrag%'"
    )
    print("Found LightRAG tables:", [t['tablename'] for t in tables])

    deleted = await conn.execute(
        "DELETE FROM lightrag_doc_status WHERE status IN ('FAILED', 'PROCESSING', 'PENDING')"
    )
    print(f"Cleared stale documents: {deleted}")

    await conn.execute("TRUNCATE lightrag_vdb_entity")
    await conn.execute("TRUNCATE lightrag_vdb_relation")
    await conn.execute("TRUNCATE lightrag_vdb_chunks")
    await conn.execute("TRUNCATE lightrag_doc_chunks")
    await conn.execute("TRUNCATE lightrag_llm_cache")

    await conn.close()
