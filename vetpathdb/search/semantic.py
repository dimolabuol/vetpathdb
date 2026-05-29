from typing import Dict, List, Tuple, Optional
import time
import torch
import asyncio
from asyncio import Semaphore
import random
from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings
from openai import OpenAI, AsyncOpenAI
import logging
import json
from datetime import datetime
from vetpathdb.config import AIConfig
from vetpathdb.prompts.loader import render_prompt

logger = logging.getLogger(__name__)

# Global semaphore for LLM request concurrency across ALL tasks/users
# This is initialized once and shared by all AISearchManager instances
_global_llm_semaphore = None
_global_llm_semaphore_lock = asyncio.Lock()

class AISearchManager:
    _instance = None

    def __new__(cls, mongodb_collection=None, config: AIConfig = None):
        if cls._instance is None:
            cls._instance = super(AISearchManager, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self, mongodb_collection=None, config: AIConfig = None):
        if self.initialized:
            return

        self.collection = mongodb_collection
        self.config = config or AIConfig()
        self.device = 'cpu' if self.config.force_cpu else (f'cuda:{self.config.cuda_device}' if torch.cuda.is_available() else 'cpu')

        # Initialize components
        self._init_model()
        self._init_vector_store()
        self._init_llm_client()
        self._init_global_semaphore()

        self.initialized = True

    def _init_global_semaphore(self):
        """Initialize the global LLM semaphore (shared across all tasks)"""
        global _global_llm_semaphore
        if _global_llm_semaphore is None:
            _global_llm_semaphore = Semaphore(self.config.global_max_llm_requests)
            logger.info(f"Initialized global LLM semaphore with limit: {self.config.global_max_llm_requests}")
        self.global_llm_semaphore = _global_llm_semaphore
    
    @staticmethod
    def filter_results_by_score(results: List[Dict], min_score: float = 0.2) -> List[Dict]:
        """
        Filter search results to exclude cases with N/A scores or scores below threshold.

        Args:
            results: List of result dictionaries with 'score' field
            min_score: Minimum score threshold (default 0.2)

        Returns:
            Filtered list of results
        """
        filtered = []
        for result in results:
            score = result.get("score")

            # Skip if score is None, empty string, or N/A string
            if score is None or score == "" or score == "N/A":
                continue

            # Try to convert to float and check threshold
            try:
                score_value = float(score)
                if score_value >= min_score:
                    filtered.append(result)
            except (ValueError, TypeError):
                # Skip results with non-numeric scores
                continue

        return filtered

    def cleanup(self):
        """Cleanup resources"""
        if hasattr(self, 'model'):
            # Move model to CPU and clear CUDA cache
            self.model.to('cpu')
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def _init_model(self):
        """Initialize the embedding model with GPU fallback and memory optimization"""
        try:
            # Build model_kwargs with proper torch dtype (must be torch object, not string)
            model_kwargs = dict(self.config.model_kwargs)
            model_kwargs["torch_dtype"] = torch.float16

            # Try loading with optimizations first
            logger.info(f"Loading model with half precision on {self.device}")
            self.model = SentenceTransformer(
                self.config.embedding_model,
                device=self.device,
                model_kwargs=model_kwargs
            )
            logger.info(f"Model loaded successfully on device: {self.device} with optimizations")
        except RuntimeError as e:
            if "CUDA" in str(e):
                logger.warning(f"CUDA error with optimizations: {e}. Trying CPU fallback.")
                # Clear any CUDA memory that might have been allocated
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

                # Try CPU with same optimizations
                try:
                    self.device = 'cpu'
                    model_kwargs = dict(self.config.model_kwargs)
                    model_kwargs["torch_dtype"] = torch.float16
                    self.model = SentenceTransformer(
                        self.config.embedding_model,
                        device='cpu',
                        model_kwargs=model_kwargs
                    )
                    logger.info("Model loaded on CPU with optimizations (fallback)")
                except Exception as cpu_e:
                    # Fallback to basic CPU loading
                    logger.warning(f"CPU optimized loading failed: {cpu_e}. Using basic loading.")
                    self.model = SentenceTransformer(
                        self.config.embedding_model,
                        trust_remote_code=True,
                        device='cpu'
                    )
                    logger.info("Model loaded on CPU (basic fallback)")
            else:
                raise
        
        self.model.max_seq_length = self.config.max_seq_length

    def _init_vector_store(self):
        """Initialize the vector store"""
        chroma_client = chromadb.PersistentClient(
            path=self.config.vector_store_path,
            settings=Settings(anonymized_telemetry=False)
        )
        self.vector_store = chroma_client.get_or_create_collection(name="cases")
        
        # We'll fit the BM25 model when needed in search()

    def _init_llm_client(self):
        """Initialize the LLM client"""
        # Standard synchronous client for non-batched operations
        self.llm_client = OpenAI(
            base_url=self.config.llm_base_url,
            api_key="dummy"
        )
        
        # Async client for parallel batched operations
        self.async_llm_client = AsyncOpenAI(
            base_url=self.config.llm_base_url,
            api_key="dummy"
        )

    def create_text_representation(self, case: Dict, full_content: bool = False, include_files: bool = False) -> Optional[str]:
        """Convert a case document into a single text representation"""
        text_parts = []
        
        content_fields = 0  # Track number of non-empty content fields
        
        # Add case ID
        case_id = case.get('case_id', 'Unknown')
        text_parts.append(f"Case ID: {case_id}")
        
        # Add summary
        summary = case.get('data', {}).get('summary')
        if summary and len(str(summary).strip()) > 0:
            text_parts.append(f"Summary: {summary}")
            content_fields += 1
            
        # Add animal details
        animal_details = case.get('data', {}).get('animal_details', {})
        if animal_details:
            for field in ['species', 'breed', 'age', 'sex']:
                if value := animal_details.get(field):
                    if len(str(value).strip()) > 0:
                        text_parts.append(f"{field.title()}: {value}")
                        content_fields += 1
        
        # Add histopathology details
        histo = case.get('data', {}).get('histopathology', {})
        if histo:
            for field in ['diagnosis', 'tumor_type']:
                if value := histo.get(field):
                    if len(str(value).strip()) > 0:
                        text_parts.append(f"{field.replace('_', ' ').title()}: {value}")
                        content_fields += 1
        
        # Add clinical details if requested
        if full_content:
            clinical = case.get('data', {}).get('clinical_details', {})
            if clinical:
                for key, value in clinical.items():
                    if value:
                        text_parts.append(f"{key.replace('_', ' ').title()}: {value}")
        
        # Add file contents if requested
        if include_files:
            filestore = self.collection.database[self.config.collection_filestore]
            if filenames := case.get('data', {}).get('report_metadata', {}).get('filenames', []):
                text_parts.append("\nAssociated Files:")
                for filename in filenames:
                    if file_doc := filestore.find_one({"filename": filename}):
                        if content := file_doc.get("content"):
                            text_parts.append(f"\n--- {filename} ---\n{content}")

        # Check if we have sufficient content (at least 2 non-empty fields besides case ID)
        if content_fields < 2:
            return None
            
        return "\n".join(text_parts)

    def _query_chromadb_batched(self, query_embedding, max_results: int, where_clause=None):
        """
        Query ChromaDB with automatic batching if single query fails.

        Args:
            query_embedding: Encoded query vector
            max_results: Total number of results to retrieve
            where_clause: Optional metadata filter

        Returns:
            Dictionary with 'metadatas' and 'distances' keys containing merged results
        """
        batch_size = self.config.chroma_batch_size

        query_params = {
            "query_embeddings": [query_embedding.tolist()],
            "n_results": max_results,
            "include": ["metadatas", "distances"]
        }
        if where_clause:
            query_params["where"] = where_clause

        # Try single query first
        try:
            logger.info(f"Attempting single ChromaDB query for {max_results} results")
            results = self.vector_store.query(**query_params)
            logger.info(f"Single query successful, retrieved {len(results['metadatas'][0])} results")
            return results
        except Exception as e:
            logger.warning(f"Single ChromaDB query failed for {max_results} results: {str(e)}")
            logger.info(f"Falling back to batched queries with batch_size={batch_size}")

        # Fall back to batched queries
        all_metadatas = []
        all_distances = []

        # Calculate number of batches needed
        num_batches = (max_results + batch_size - 1) // batch_size
        logger.info(f"Executing {num_batches} batched queries to retrieve {max_results} total results")

        for batch_num in range(num_batches):
            batch_query_params = query_params.copy()
            # For batching, we need to fetch more than needed to ensure we get the best matches
            # Request batch_size results for each batch
            batch_query_params["n_results"] = min(batch_size, max_results - batch_num * batch_size)

            try:
                logger.info(f"Batch {batch_num + 1}/{num_batches}: querying {batch_query_params['n_results']} results")
                batch_results = self.vector_store.query(**batch_query_params)
                all_metadatas.extend(batch_results["metadatas"][0])
                all_distances.extend(batch_results["distances"][0])
                logger.info(f"Batch {batch_num + 1}/{num_batches} successful, retrieved {len(batch_results['metadatas'][0])} results")
            except Exception as batch_error:
                logger.error(f"Batch {batch_num + 1}/{num_batches} failed: {str(batch_error)}")
                # Continue with next batch or return what we have
                if len(all_metadatas) == 0:
                    raise  # Re-raise if first batch fails
                else:
                    logger.warning(f"Returning partial results from {batch_num} successful batches")
                    break

        # Merge and sort all results by distance
        combined = list(zip(all_metadatas, all_distances))
        combined.sort(key=lambda x: x[1])  # Sort by distance (lower is better)

        # Take top max_results
        combined = combined[:max_results]

        # Unzip back to separate lists
        if combined:
            metadatas, distances = zip(*combined)
            merged_results = {
                "metadatas": [list(metadatas)],
                "distances": [list(distances)]
            }
        else:
            merged_results = {
                "metadatas": [[]],
                "distances": [[]]
            }

        logger.info(f"Batched query complete: merged {len(merged_results['metadatas'][0])} results from {len(all_metadatas)} total retrieved")
        return merged_results

    async def search(self, query: str, depth: int = 20, semantic_only: bool = False, report_type: str = None, timeout: int = None, task_id: str = None) -> List[Dict]:
        """
        Perform AI-powered search with timeout
        
        Args:
            query: Search query string
            depth: Number of results to return
            semantic_only: If True or if depth="semantic", only perform semantic search without LLM analysis
            timeout: Timeout in seconds for LLM request
            
        Returns:
            List of search results with scores and reasoning
        """
        try:
            logger.info(f"Starting {'semantic' if semantic_only else 'AI'} search with query: {query}, depth: {depth}")
            
            # Input validation
            if not isinstance(query, str):
                logger.error(f"Invalid query type: {type(query)}")
                raise ValueError("Query must be a string")
                
            if depth is not None and not isinstance(depth, int) and not (isinstance(depth, str) and depth == "everything"):
                logger.error(f"Invalid depth type: {type(depth)}")
                raise ValueError("Depth must be an integer or the string 'everything'")
            
            is_everything = isinstance(depth, str) and depth == "everything"

            # Define cancellation checker early so both paths can use it
            check_cancelled = None
            if task_id:
                def check_cancelled():
                    task = self.collection.database.ai_search_tasks.find_one({"task_id": task_id})
                    is_cancelled = task and task["status"] == "cancelled"
                    if is_cancelled:
                        logger.info(f"Task {task_id} cancellation detected during search")
                    return is_cancelled

            # For "everything" mode, get case list from MongoDB, then rank by ChromaDB similarity
            if is_everything:
                mongo_filter = {}
                if report_type:
                    code = report_type.upper()
                    mongo_filter["$or"] = [
                        {"case_type": code},
                        {"data.report_metadata.report_type": report_type},
                    ]
                cases_cursor = self.collection.find(mongo_filter, {"case_id": 1})
                case_ids = [c["case_id"] for c in cases_cursor]
                similarity_scores = None
                logger.info(f"'Everything' mode: found {len(case_ids)} cases in MongoDB" +
                           (f" (filtered by report_type={report_type})" if report_type else ""))

                # Use ChromaDB to rank cases by similarity (ordering only, not filtering)
                if self.model and self.vector_store:
                    try:
                        query_embedding = self.model.encode(
                            query,
                            prompt=self.config.embedding_query_prompt,
                            normalize_embeddings=True
                        )
                        where_clause = {"report_type": report_type} if report_type else None
                        chroma_results = self._query_chromadb_batched(
                            query_embedding,
                            max_results=len(case_ids),
                            where_clause=where_clause
                        )
                        if chroma_results and chroma_results.get("ids") and chroma_results["ids"][0]:
                            distance_map = {}
                            for cid, dist in zip(chroma_results["ids"][0], chroma_results["distances"][0]):
                                distance_map[cid] = dist
                            case_ids.sort(key=lambda cid: distance_map.get(cid, float('inf')))
                            similarity_scores = distance_map
                            logger.info(f"Ranked {len(distance_map)} of {len(case_ids)} cases by similarity")
                        elif chroma_results and chroma_results.get("metadatas") and chroma_results["metadatas"][0]:
                            # Fallback: extract case_ids from metadatas
                            distance_map = {}
                            for meta, dist in zip(chroma_results["metadatas"][0], chroma_results["distances"][0]):
                                if meta.get("case_id"):
                                    distance_map[meta["case_id"]] = dist
                            case_ids.sort(key=lambda cid: distance_map.get(cid, float('inf')))
                            similarity_scores = distance_map
                            logger.info(f"Ranked {len(distance_map)} of {len(case_ids)} cases by similarity (via metadatas)")
                    except Exception as e:
                        logger.warning(f"ChromaDB ranking failed, proceeding with unranked order: {e}")
            else:
                # Normal mode: use ChromaDB for semantic search
                query_embedding = self.model.encode(
                    query,
                    prompt=self.config.embedding_query_prompt,
                    normalize_embeddings=True
                )

                where_clause = None
                if report_type:
                    where_clause = {"report_type": report_type}

                min_results = 50 if semantic_only else 500
                max_results = max(depth, min_results)

                results = self._query_chromadb_batched(query_embedding, max_results, where_clause)

                logger.info(f"Raw distances from ChromaDB (first 5): {results['distances'][0][:5]}")

                combined = list(zip(
                    results["metadatas"][0],
                    results["distances"][0]
                ))
                combined.sort(key=lambda x: x[1])
                combined = combined[:depth]

                metadatas, distances = zip(*combined)
                case_ids = [metadata["case_id"] for metadata in metadatas]
                similarity_scores = [1 / (1 + d) for d in distances]

                logger.info(f"After sorting - First 5 cases and scores: {list(zip(case_ids[:5], similarity_scores[:5]))}")

            # Update task status
            if task_id:
                self.collection.database.ai_search_tasks.update_one(
                    {"task_id": task_id},
                    {"$set": {
                        "stage": "vector_search",
                        "stage_description": "Found cases for analysis",
                        "total_found": len(case_ids)
                    }}
                )

                if check_cancelled():
                    logger.info(f"Search task {task_id} was cancelled")
                    return []

            # Use timeout from config if not specified
            if timeout is None:
                timeout = self.config.llm_timeout

            # If semantic_only is True, return vector search results immediately
            if semantic_only:
                logger.info(f"Semantic-only search, returning {len(case_ids)} results directly")
                final_results = []
                for i, case_id in enumerate(case_ids):
                    if case := self.collection.find_one({"case_id": case_id}):
                        if similarity_scores is None:
                            score = 0.5
                        elif isinstance(similarity_scores, dict):
                            dist = similarity_scores.get(case_id, 1.0)
                            score = 1 / (1 + dist)
                        else:
                            score = similarity_scores[i]
                        final_results.append({
                            "case_id": case_id,
                            "score": score,
                            "data": case.get("data", {}),
                            "reasoning": "Semantic similarity match"
                        })
                final_results.sort(key=lambda x: x["score"], reverse=True)
                filtered_results = self.filter_results_by_score(final_results)
                logger.info(f"Filtered from {len(final_results)} to {len(filtered_results)} results (min_score=0.2)")
                return filtered_results
            else:
                # Full AI analysis path
                logger.info(f"Starting full AI analysis for {len(case_ids)} cases")

                if task_id:
                    self.collection.database.ai_search_tasks.update_one(
                        {"task_id": task_id},
                        {"$set": {
                            "stage": "preparing_analysis",
                            "stage_description": "Preparing cases for analysis"
                        }}
                    )

                max_cases = len(case_ids)
                if not self.config.use_batched_scoring:
                    max_cases = min(len(case_ids), self.config.max_cases_for_llm)
                    if max_cases < len(case_ids):
                        logger.info(f"Limiting LLM analysis to {max_cases} cases (out of {len(case_ids)} total)")

                # Bulk fetch cases from MongoDB (batched $in instead of 40k find_one)
                target_ids = case_ids[:max_cases]
                case_cache = {}
                fetch_batch_size = 5000
                for i in range(0, len(target_ids), fetch_batch_size):
                    batch = target_ids[i:i+fetch_batch_size]
                    for case in self.collection.find({"case_id": {"$in": batch}}):
                        case_cache[case["case_id"]] = case

                # Build ordered list of valid case_ids (preserving original order)
                case_id_list = [cid for cid in target_ids if cid in case_cache]
                logger.info(f"Bulk-fetched {len(case_cache)} cases for LLM analysis")

                try:
                    if task_id and check_cancelled():
                        return []

                    if task_id:
                        self.collection.database.ai_search_tasks.update_one(
                            {"task_id": task_id},
                            {"$set": {
                                "stage": "llm_analysis",
                                "stage_description": "Starting AI analysis",
                                "relevant_found": 0
                            }}
                        )

                    if self.config.use_batched_scoring:
                        logger.info("Using batched document scoring approach")
                        llm_results = await self._batch_analyze_with_llm(query, case_cache, case_id_list, timeout, task_id)
                    else:
                        # Traditional mode: pre-build texts (limited to max_cases_for_llm, typically 50)
                        cases_data = []
                        for cid in case_id_list:
                            text = self.create_text_representation(case_cache[cid], full_content=True)
                            if text:
                                cases_data.append(text)
                        logger.info("Using traditional bulk scoring approach")
                        llm_results = await self._analyze_with_llm(query, cases_data, timeout, task_id)

                    if task_id and check_cancelled():
                        return []

                except Exception as e:
                    logger.error(f"LLM analysis failed: {str(e)}")
                    if is_everything:
                        raise  # No meaningful semantic fallback for "everything" mode
                    # Fall back to semantic search results for normal depth searches
                    return await self.search(query, depth, semantic_only=True)

                # Assemble final results using cached case data (no extra MongoDB lookups)
                final_results = []
                for result in llm_results:
                    case = case_cache.get(result["case_id"])
                    if case is None:
                        case = self.collection.find_one({"case_id": result["case_id"]})
                    if case:
                        result["data"] = case.get("data", {})
                        final_results.append(result)

                final_results.sort(key=lambda x: x["score"], reverse=True)
                filtered_results = self.filter_results_by_score(final_results)
                logger.info(f"Filtered from {len(final_results)} to {len(filtered_results)} LLM results (min_score=0.2)")
                return filtered_results
            
        except Exception as e:
            logger.error(f"Error in AI search: {str(e)}")
            raise

    async def _analyze_with_llm(self, query: str, cases_data: List[str], timeout: int = 300, task_id: str = None) -> List[Dict]:
        """Analyze search results using LLM with timeout (traditional bulk approach)"""
        logger.info(f"Starting bulk LLM analysis for query: {query} with {len(cases_data)} cases")
        
        # Log total input size to help diagnose context window issues
        total_chars = sum(len(case) for case in cases_data)
        total_tokens_est = total_chars / 4  # Rough estimate: 4 chars per token
        logger.info(f"Total input size: {total_chars} characters (~{total_tokens_est:.0f} tokens est.)")
        
        # Check if already cancelled before starting
        if task_id:
            task = self.collection.database.ai_search_tasks.find_one({"task_id": task_id})
            if task and task["status"] == "cancelled":
                logger.info(f"Task {task_id} was cancelled before LLM analysis")
                return []
        
        prompt = render_prompt(
            "search/relevance_batch.txt",
            query=query,
            cases="\n\n---\n\n".join(cases_data),
        )
        
        try:
            start_time = time.time()
            logger.info("Sending request to LLM")
            
            # Make the synchronous request with additional parameters to help smaller models
            response = self.llm_client.chat.completions.create(
                model=self.config.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                timeout=timeout,
                max_tokens=4000,  # Limit response length to prevent infinite generation
                stop=["```"]  # Stop if model tries to use markdown code blocks
            )
            
            # Check if cancelled after response
            if task_id:
                task = self.collection.database.ai_search_tasks.find_one({"task_id": task_id})
                if task and task["status"] == "cancelled":
                    logger.info(f"Task {task_id} was cancelled after LLM request")
                    return []
            
            elapsed = time.time() - start_time
            logger.info(f"LLM response received in {elapsed:.2f} seconds")
            
            # Log response length to help diagnose issues
            response_content = response.choices[0].message.content
            logger.info(f"Response length: {len(response_content)} characters")
            
            # Log first 100 chars of response for debugging
            preview = response_content[:100].replace('\n', ' ')
            logger.info(f"Response preview: {preview}...")
            
            try:
                # Try to clean up common JSON formatting issues before parsing
                content = response.choices[0].message.content.strip()
                
                # Remove markdown code block markers if present
                if content.startswith("```json"):
                    content = content.replace("```json", "", 1)
                if content.startswith("```"):
                    content = content.replace("```", "", 1)
                if content.endswith("```"):
                    content = content[:-3]
                
                content = content.strip()
                
                # Log the cleaned content
                logger.info(f"Attempting to parse JSON (length: {len(content)})")
                
                # Try to parse the JSON
                result = json.loads(content)
                logger.info(f"Successfully parsed LLM response with {len(result)} results")
                
                # Validate the structure of the response
                for item in result:
                    if not isinstance(item, dict):
                        logger.warning(f"Invalid item type in response: {type(item)}")
                    if "case_id" not in item:
                        logger.warning("Missing case_id in response item")
                    if "score" not in item:
                        logger.warning("Missing score in response item")
                    if "reasoning" not in item:
                        logger.warning("Missing reasoning in response item")
                
                return result
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse LLM response: {str(e)}")
                logger.error(f"JSON parse error at position: {e.pos}")
                
                # Log a snippet around the error position to help diagnose the issue
                if e.pos > 0 and e.pos < len(content):
                    start = max(0, e.pos - 50)
                    end = min(len(content), e.pos + 50)
                    snippet = content[start:end]
                    logger.error(f"Content around error position: '...{snippet}...'")
                
                logger.error(f"Raw response: {response.choices[0].message.content}")
                raise ValueError("Invalid JSON response from LLM")
                
        except Exception as e:
            logger.error(f"LLM analysis failed: {str(e)}")
            
            # Check if it's a timeout error
            if "timeout" in str(e).lower():
                logger.error(f"LLM request timed out after {timeout} seconds")
            
            # Log elapsed time if available
            try:
                elapsed = time.time() - start_time
                logger.error(f"Error occurred after {elapsed:.2f} seconds")
            except Exception:
                pass  # logging-only helper; don't mask the outer raise
                
            raise
            
    async def _batch_analyze_with_llm(self, query: str, case_cache: Dict, case_ids: List[str], timeout: int = 300, task_id: str = None) -> List[Dict]:
        """Analyze search results using LLM with batched processing. Text generated lazily per-case."""
        total_cases = len(case_ids)
        logger.info(f"Starting batched LLM analysis for query: {query} with {total_cases} cases")
        
        # Check if already cancelled before starting
        if task_id:
            task = self.collection.database.ai_search_tasks.find_one({"task_id": task_id})
            if task and task["status"] == "cancelled":
                logger.info(f"Task {task_id} was cancelled before LLM analysis")
                return []
            
            # Initialize progress tracking in the task document
            self.collection.database.ai_search_tasks.update_one(
                {"task_id": task_id},
                {"$set": {
                    "total_cases": total_cases,
                    "processed_cases": 0,
                    "progress": 0,
                    "stage": "preparing",
                    "stage_description": "Preparing for analysis",
                    "total_found": len(case_ids)
                    # Don't set relevant_found until analysis phase
                }}
            )
        
        # Single-case relevance prompt: prompts/search/relevance_single.txt

        # Use a counter to track completed cases
        completed_cases_counter = 0
    
        # Circuit breaker state
        circuit_breaker_errors = 0
        circuit_breaker_lock = asyncio.Lock()
        circuit_breaker_tripped = False
        
        # Create a function to process a single case
        async def process_single_case(case_id, case_index):
            nonlocal completed_cases_counter, circuit_breaker_errors, circuit_breaker_tripped

            try:
                # Generate text representation lazily (not pre-built for all 40k cases)
                case = case_cache.get(case_id)
                if not case:
                    if task_id:
                        completed_cases_counter += 1
                    return None
                case_data = self.create_text_representation(case, full_content=True)
                if not case_data:
                    if task_id:
                        completed_cases_counter += 1
                    return None
                prompt = render_prompt("search/relevance_single.txt", query=query, case=case_data)
            
                # Check for cancellation
                if task_id:
                    task = self.collection.database.ai_search_tasks.find_one({"task_id": task_id})
                    if task and task["status"] == "cancelled":
                        return None
                
                # Check if circuit breaker is tripped
                if circuit_breaker_tripped:
                    logger.warning(f"Circuit breaker tripped, skipping case {case_id}")
                    return {
                        "case_id": case_id,
                        "score": 0.1,
                        "reasoning": "Skipped due to LLM overload"
                    }
                
                # Implement retry logic with exponential backoff
                retries = 0
                max_retries = self.config.max_retries
                base_delay = self.config.retry_base_delay
                
                while retries <= max_retries:
                    try:
                        # Make the request using the async client for true parallelism
                        start_time = time.time()
                        response = await self.async_llm_client.chat.completions.create(
                            model=self.config.llm_model,
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0.3,
                            timeout=timeout,
                            max_tokens=1000,  # Smaller limit for single document
                            stop=["```"]  # Stop if model tries to use markdown code blocks
                        )
                        elapsed = time.time() - start_time
                        
                        # Reset circuit breaker error count on success
                        async with circuit_breaker_lock:
                            circuit_breaker_errors = 0
                            
                        break  # Success, exit retry loop
                        
                    except Exception as e:
                        retries += 1
                        error_msg = str(e)
                        
                        # Check if it's an overload error
                        is_overload = "429" in error_msg or "overloaded" in error_msg.lower()
                        
                        if is_overload:
                            # Update circuit breaker error count
                            async with circuit_breaker_lock:
                                circuit_breaker_errors += 1
                                
                                # Check if we should trip the circuit breaker
                                if circuit_breaker_errors >= self.config.circuit_breaker_threshold and not circuit_breaker_tripped:
                                    circuit_breaker_tripped = True
                                    logger.warning(f"Circuit breaker tripped after {circuit_breaker_errors} consecutive errors")
                                    
                                    # Schedule circuit breaker reset
                                    asyncio.create_task(reset_circuit_breaker())
                        
                        # If we've exhausted retries or it's not an overload error, raise
                        if retries > max_retries or not is_overload:
                            logger.error(f"Error processing case {case_id} after {retries} retries: {error_msg}")
                            raise
                            
                        # Calculate backoff delay with jitter
                        delay = base_delay * (2 ** (retries - 1)) * (0.5 + random.random())
                        logger.info(f"Retrying case {case_id} in {delay:.2f}s after error: {error_msg}")
                        await asyncio.sleep(delay)
            
                # Process the response
                content = response.choices[0].message.content.strip()
            
                # Clean up JSON
                if content.startswith("```json"):
                    content = content.replace("```json", "", 1)
                if content.startswith("```"):
                    content = content.replace("```", "", 1)
                if content.endswith("```"):
                    content = content[:-3]
            
                content = content.strip()
            
                # Parse the JSON
                result = json.loads(content)
            
                # Add the case ID
                result["case_id"] = case_id
            
                logger.debug(f"Processed case {case_id} in {elapsed:.2f}s with score {result.get('score', 0)}")
            
                # Update progress in the database if task_id is provided
                if task_id:
                    completed_cases_counter += 1
                    progress_percent = round((completed_cases_counter / total_cases) * 100)

                    is_relevant = result.get("score", 0) >= 0.50

                    # Store this result in the results collection for partial results retrieval
                    results_collection = self.collection.database[self.config.collection_ai_search_results]
                    results_collection.insert_one({
                        "task_id": task_id,
                        "case_id": result["case_id"],
                        "score": result.get("score", 0),
                        "reasoning": result.get("reasoning", ""),
                        "created_at": datetime.now()  # For TTL index
                    })

                    # Use $inc for relevant_found to avoid race condition with concurrent coroutines
                    update_ops = {
                        "$set": {
                            "processed_cases": completed_cases_counter,
                            "progress": progress_percent,
                            "stage": "analyzing",
                            "stage_description": "Analyzing cases",
                        }
                    }
                    if is_relevant:
                        update_ops["$inc"] = {"relevant_found": 1}
                    self.collection.database.ai_search_tasks.update_one(
                        {"task_id": task_id}, update_ops
                    )
                    logger.info(f"Progress updated: {completed_cases_counter}/{total_cases} ({progress_percent}%)")
            
                return result
            except Exception as e:
                logger.error(f"Error processing case {case_id}: {str(e)}")
            
                # Still increment the counter for failed cases
                if task_id:
                    completed_cases_counter += 1
                    progress_percent = round((completed_cases_counter / total_cases) * 100)

                    self.collection.database.ai_search_tasks.update_one(
                        {"task_id": task_id},
                        {"$set": {
                            "processed_cases": completed_cases_counter,
                            "progress": progress_percent,
                            "stage": "analyzing",
                        }}
                    )
                    logger.info(f"Progress updated: {completed_cases_counter}/{total_cases} ({progress_percent}%)")
            
                # Return a fallback result with low score
                return {
                    "case_id": case_id,
                    "score": 0.1,
                    "reasoning": "Error during analysis"
                }
        
        # Function to reset the circuit breaker after cooldown
        async def reset_circuit_breaker():
            nonlocal circuit_breaker_tripped
            await asyncio.sleep(self.config.circuit_breaker_cooldown)
            async with circuit_breaker_lock:
                circuit_breaker_tripped = False
                logger.info("Circuit breaker reset after cooldown period")
        
        # Dynamically set concurrency based on number of cases, up to the configured maximum
        dynamic_concurrency = min(total_cases, self.config.max_batch_concurrency)
        logger.info(f"Using dynamic concurrency of {dynamic_concurrency} for {total_cases} cases")
        logger.info(f"Global LLM semaphore limit: {self.config.global_max_llm_requests}")

        # Create a bounded version with BOTH per-task and global semaphores
        # Per-task semaphore limits concurrency within this search
        # Global semaphore limits total LLM requests across ALL users/tasks
        task_semaphore = Semaphore(dynamic_concurrency)

        async def bounded_process_case(case_id, case_index):
            # Acquire both semaphores: first global (across all tasks), then task-local
            async with self.global_llm_semaphore:
                async with task_semaphore:
                    return await process_single_case(case_id, case_index)
        
        # Process cases in batches — users can view partial results and stop early
        batch_size = 100
        num_batches = (total_cases + batch_size - 1) // batch_size
        logger.info(f"Processing {total_cases} cases in {num_batches} sequential batches of {batch_size}")

        start_time = time.time()
        results = []

        for batch_num in range(num_batches):
            batch_start = batch_num * batch_size
            batch_end = min(batch_start + batch_size, total_cases)
            batch_case_ids = case_ids[batch_start:batch_end]

            logger.info(f"Processing batch {batch_num + 1}/{num_batches}: cases {batch_start + 1}-{batch_end}")

            # Create tasks for this batch
            batch_tasks = []
            for i, case_id in enumerate(batch_case_ids):
                batch_tasks.append(bounded_process_case(case_id, batch_start + i))

            # Execute batch concurrently, but wait for it to complete before next batch
            batch_results = await asyncio.gather(*batch_tasks)
            results.extend(batch_results)

            logger.info(f"Batch {batch_num + 1}/{num_batches} complete: {len(batch_results)} cases processed")

        elapsed = time.time() - start_time
        
        # Filter out None results (from cancelled tasks)
        results = [r for r in results if r is not None]
        
        logger.info(f"Completed batched LLM analysis in {elapsed:.2f} seconds for {len(results)} cases")
        
        # Sort by score in descending order
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        
        return results
