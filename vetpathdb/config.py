from pydantic_settings import BaseSettings
import os
import sys

# Check both environment variable and command line args for demo mode (handles race condition)
_is_demo = os.getenv('DEMO_MODE') == 'true' or '--demo-db' in sys.argv

class AIConfig(BaseSettings):
    embedding_model: str = "Alibaba-NLP/gte-Qwen2-1.5B-instruct"  # Keep same model as vectors
    max_seq_length: int = 8192
    cuda_device: int = 0  # Use the available GPU device
    force_cpu: bool = False  # Enable GPU for much faster inference
    model_kwargs: dict = {
        "trust_remote_code": True
    }
    # Instruction prefix prepended to queries at encode time. The bundled
    # default matches the Qwen `gte` family used for the shipped
    # cases_vectorstore. Different embedding families expect different
    # prompt conventions (BGE uses no prefix; E5 uses "query: ...";
    # MiniLM/generic take no prefix at all). Override via
    # AI_EMBEDDING_QUERY_PROMPT when swapping models. See docs/LLM_SETUP.md.
    embedding_query_prompt: str = (
        "Instruct: Given a vet pathology cases search query, "
        "retrieve relevant cases that match the query\nQuery: "
    )
    vector_store_path: str = "./cases_vectorstore_demo" if _is_demo else "./cases_vectorstore"
    llm_base_url: str = "http://localhost:8080/v1"
    llm_model: str = "local-model"  # Model name to use for LLM requests
    max_cases_for_llm: int = 50  # Maximum number of cases to send to LLM for analysis
    llm_timeout: int = 300  # Timeout for LLM requests in seconds
    max_batch_concurrency: int = 25  # Maximum number of concurrent LLM requests for batch processing
    max_retries: int = 3  # Maximum number of retries for LLM requests
    retry_base_delay: float = 1.0  # Base delay for exponential backoff (seconds)
    circuit_breaker_threshold: int = 10  # Number of consecutive errors before pausing processing
    circuit_breaker_cooldown: float = 5.0  # Cooldown period after circuit breaker trips (seconds)
    use_batched_scoring: bool = True  # Whether to use batched document scoring

    # Multi-user scalability settings
    global_max_llm_requests: int = 50  # Total concurrent LLM requests across ALL users/tasks
    chroma_batch_size: int = 5000  # Chunk size for batched ChromaDB queries when single query fails
    queue_poll_interval: float = 2.0  # Seconds between queue worker polls

    # MongoDB database + collection names. Overridable so a single Mongo
    # server can host multiple independent VetPathDB deployments
    # (dev/staging/prod, per-tenant, etc.) without touching code.
    mongo_db: str = "cases_demo" if _is_demo else "cases"
    mongo_db_demo: str = "cases_demo"
    collection_cases: str = "processed_cases"
    collection_filestore: str = "filestore"
    collection_ai_search_tasks: str = "ai_search_tasks"
    collection_ai_search_results: str = "ai_search_results"
    collection_analysis_cache: str = "analysis_cache"

    # Filesystem root where PDFs are stored, organised as
    # <pdf_root_path>/<case_id>/<filename>.pdf. Override via PDF_ROOT_PATH env
    # var to point at NFS / shared storage / a different local directory.
    pdf_root_path: str = "./pdf"

    class Config:
        env_prefix = "AI_"  # Allow override via environment variables
