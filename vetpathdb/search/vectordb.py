import sys
import os
import time
import psutil
import torch
import json
from openai import OpenAI
import torch.multiprocessing as mp
from pymongo import MongoClient
from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings
import numpy as np

from vetpathdb.config import AIConfig
from vetpathdb.pipeline._utils import is_valid_case_id as validate_case_id
from vetpathdb.prompts.loader import render_prompt

_AI_CONFIG = AIConfig()


def get_timestamp():
    """Return current timestamp in readable format"""
    return time.strftime('%Y-%m-%d %H:%M:%S')

def print_info(msg, debug=False, debug_mode=False):
    if debug_mode:
        print(f"[{get_timestamp()}][DEBUG] {msg}")
    elif not debug:
        print(f"[{get_timestamp()}][INFO] {msg}")

def print_debug(msg, debug_mode=False):
    if debug_mode:
        print(f"[{get_timestamp()}][DEBUG] {msg}")

class ProgressTracker:
    def __init__(self, total_cases):
        self.total_cases = total_cases
        self.processed_cases = 0
        self.start_time = time.time()
        self.last_batch_time = time.time()
        self.total_embedding_time = 0
        self.avg_batch_size = 0
        self.max_memory_used = 0
        self.batch_count = 0
        
    def update(self, batch_size, embedding_time, debug_mode=False):
        current_time = time.time()
        self.processed_cases += batch_size
        self.total_embedding_time += embedding_time
        batch_duration = current_time - self.last_batch_time
        
        # Update statistics
        self.batch_count += 1
        self.avg_batch_size = ((self.avg_batch_size * (self.batch_count - 1)) + batch_size) / self.batch_count
        
        # Track memory usage
        process = psutil.Process()
        memory_info = process.memory_info()
        current_memory = memory_info.rss / 1024 / 1024  # Convert to MB
        self.max_memory_used = max(self.max_memory_used, current_memory)
        
        if debug_mode:
            print_debug(f"Batch Statistics:", debug_mode)
            print_debug(f"  - Batch size: {batch_size} cases", debug_mode)
            print_debug(f"  - Batch duration: {batch_duration:.2f}s", debug_mode)
            print_debug(f"  - Embedding time: {embedding_time:.2f}s", debug_mode)
            print_debug(f"  - Memory usage: {current_memory:.1f}MB", debug_mode)
            
        self.last_batch_time = current_time
        
    def print_status(self, debug_mode=False):
        elapsed_time = time.time() - self.start_time
        cases_per_second = self.processed_cases / elapsed_time if elapsed_time > 0 else 0
        
        print_info(f"Progress: {self.processed_cases}/{self.total_cases} cases processed", debug_mode=debug_mode)
        print_info(f"Elapsed time: {elapsed_time:.1f}s", debug_mode=debug_mode)
        print_info(f"Processing speed: {cases_per_second:.1f} cases/second", debug_mode=debug_mode)
        print_info(f"Total embedding time: {self.total_embedding_time:.1f}s", debug_mode=debug_mode)
        print_info(f"Average batch size: {self.avg_batch_size:.1f} cases", debug_mode=debug_mode)
        print_info(f"Peak memory usage: {self.max_memory_used:.1f}MB", debug_mode=debug_mode)
        
        if self.total_embedding_time > 0:
            print_info(f"Average embedding time per case: {self.total_embedding_time/self.processed_cases:.3f}s", debug_mode=debug_mode)

def create_text_representation(case, full_content=False):
    """
    Convert a case document into a single text representation.
    Returns None if case has insufficient content.
    """
    text_parts = []
    content_fields = 0  # Track number of non-empty content fields

    # Always start with case ID, ensure it's a string
    case_id = str(case.get('case_id', 'Unknown'))
    if validate_case_id(case_id):
        text_parts.append(f"Case ID: {case_id}")
    else:
        text_parts.append(f"Case ID: Unknown")

    # Add RAG summary if present, fallback to regular summary
    summary = case.get('data', {}).get('rag_summary') or case.get('data', {}).get('summary')
    if summary and len(summary.strip()) > 0:
        text_parts.append(f"Summary: {summary}")
        content_fields += 1

    # Add animal details
    animal_details = case.get('data', {}).get('animal_details', {})
    if animal_details:
        # Handle both dictionary and list formats
        if isinstance(animal_details, list):
            # Take first animal if multiple
            animal_details = animal_details[0] if animal_details else {}
            
        species = animal_details.get('species')
        if species and len(str(species).strip()) > 0:
            text_parts.append(f"Species: {species}")
            content_fields += 1

        breed = animal_details.get('breed')
        if breed and len(str(breed).strip()) > 0:
            text_parts.append(f"Breed: {breed}")
            content_fields += 1

        age = animal_details.get('age')
        if age:
            text_parts.append(f"Age: {age} years")
            content_fields += 1

        sex = animal_details.get('sex')
        if sex and len(str(sex).strip()) > 0:
            text_parts.append(f"Sex: {sex}")
            content_fields += 1

        neutered = animal_details.get('neutered')
        if neutered and len(str(neutered).strip()) > 0:
            text_parts.append(f"Neutered: {neutered}")
            content_fields += 1

        bodyweight = animal_details.get('bodyweight')
        if bodyweight:
            text_parts.append(f"Body Weight: {bodyweight} kg")
            content_fields += 1

    # Add comment if present
    comment = case.get('data', {}).get('comment')
    if comment and len(str(comment).strip()) > 0:
        text_parts.append(f"Comment: {comment}")
        content_fields += 1

    # If full_content is True and you want to add more details,
    # here is where you would add them. For now, we keep it as is.

    # Check if we have sufficient content (at least 2 non-empty fields besides case ID)
    if content_fields < 2:
        return None

    return "\n".join(text_parts)

def process_batch(batch_docs, model, debug_mode=False):
    """Process a single batch using the given model"""
    if debug_mode:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}][DEBUG] Processing batch of {len(batch_docs)} documents")
    
    try:
        # Clear CUDA cache before processing
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            
        embeddings = model.encode(
            batch_docs,
            prompt=_AI_CONFIG.embedding_query_prompt,
            batch_size=32  # Process in smaller sub-batches to manage memory
        )
        
        return embeddings
        
    except Exception as e:
        print(f"Error processing batch: {str(e)}")
        raise

def run_interactive_query(mongodb_client, debug_mode=False, rag_fusion=False):
    """Run interactive query interface"""
    # Initialize Chroma client
    client = chromadb.PersistentClient(
        path=_AI_CONFIG.vector_store_path,
        settings=Settings(anonymized_telemetry=False)
    )
    chroma_collection = client.get_or_create_collection(name="cases")

    # Initialize the model on the configured device (AI_FORCE_CPU / AI_CUDA_DEVICE)
    device = 'cpu' if _AI_CONFIG.force_cpu else (
        f'cuda:{_AI_CONFIG.cuda_device}' if torch.cuda.is_available() else 'cpu'
    )
    if device.startswith('cuda:'):
        torch.cuda.set_device(_AI_CONFIG.cuda_device)
    print_info(f"Loading model on {device}...", debug_mode=debug_mode)
    model = SentenceTransformer(_AI_CONFIG.embedding_model,
                               trust_remote_code=True,
                               device=device)
    model.max_seq_length = _AI_CONFIG.max_seq_length

    while True:
        query = input("\nEnter your query (or 'quit' to exit): ").strip()
        if query.lower() == 'quit':
            break
            
        if not query:
            continue
            
        # Check if query is a case ID
        if validate_case_id(query):
            print_info(f"Detected case ID query: {query}", debug_mode=debug_mode)
            # Direct case ID lookup from MongoDB
            db = mongodb_client[_AI_CONFIG.mongo_db]
            collection = db[_AI_CONFIG.collection_cases]
            
            # Handle both string and numeric case IDs
            case = collection.find_one({
                "$or": [
                    {"case_id": query},
                    {"case_id": str(query)}  # Try string version if numeric
                ]
            })
            if case:
                # Display single case result
                print("\nExact case match found:")
                print("-" * 100)
                animal_details = case.get('data', {}).get('animal_details', {})
                species = animal_details.get('species', 'Unknown')
                age = animal_details.get('age', 'Unknown')
                sex = animal_details.get('sex', 'Unknown')
                summary = case.get('data', {}).get('summary', 'No summary')
                print(f"[{query}] {species}, {age}y, {sex} - {summary}")
                continue
            
        # Encode query
        query_embedding = model.encode(
            query,
            prompt=_AI_CONFIG.embedding_query_prompt
        )
        
        # Search
        results = chroma_collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=20,
            include=["metadatas", "distances"]
        )
        
        # Get case IDs from results
        case_ids = [metadata["case_id"] for metadata in results["metadatas"][0]]
        
        # Fetch full case details from MongoDB
        db = mongodb_client[_AI_CONFIG.mongo_db]
        collection = db[_AI_CONFIG.collection_cases]

        if rag_fusion:
            # Fetch complete details for all cases
            cases_data = []
            for case_id in case_ids:
                case = collection.find_one({"case_id": case_id})
                if case:
                    case_text = create_text_representation(case, full_content=True)
                    cases_data.append(case_text)

            # Combine all cases into one text
            all_cases_text = "\n\n---\n\n".join(cases_data)

            # Prepare prompt for LLM (shared retrieval template)
            prompt = render_prompt("search/relevance_batch.txt", query=query, cases=all_cases_text)

            # Call OpenAI API
            from vetpathdb.config import AIConfig
            _cfg = AIConfig()
            client = OpenAI(
                base_url=_cfg.llm_base_url,
                api_key="dummy"
            )

            if debug_mode:
                print_debug("Sending prompt to LLM:", debug_mode)
                print_debug("-" * 80, debug_mode)
                print_debug(prompt, debug_mode)
                print_debug("-" * 80, debug_mode)

            try:
                response = client.chat.completions.create(
                    model="local-model",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3
                )

                if debug_mode:
                    print_debug("LLM Response:", debug_mode)
                    print_debug("-" * 80, debug_mode)
                    print_debug(response.choices[0].message.content, debug_mode)
                    print_debug("-" * 80, debug_mode)
                
                # Parse JSON response
                try:
                    results = json.loads(response.choices[0].message.content)
                    # Keep only reasonably-relevant matches. The score floor used
                    # to be requested inline in the prompt; it now lives in code so
                    # the shared relevance template stays threshold-agnostic.
                    results = [r for r in results if r.get("score", 0) >= 0.3]
                    print("\nRAG Fusion Analysis Results:")
                    print("-" * 100)
                    for result in results:
                        case = collection.find_one({"case_id": result["case_id"]})
                        if case:
                            animal_details = case.get('data', {}).get('animal_details', {})
                            species = animal_details.get('species', 'Unknown')
                            age = animal_details.get('age', 'Unknown')
                            sex = animal_details.get('sex', 'Unknown')
                            summary = case.get('data', {}).get('summary', 'No summary')
                            if len(summary) > 100:
                                summary = summary[:97] + "..."
                            print(f"Score: {result['score']:.2f} - [{result['case_id']}] {species}, {age}y, {sex} - {summary}")
                            print(f"Reasoning: {result['reasoning']}")
                            print("-" * 100)
                except json.JSONDecodeError:
                    print("Error: Could not parse LLM response as JSON")
                    print("Raw response:", response.choices[0].message.content)
            
            except Exception as e:
                print(f"Error calling LLM API: {str(e)}")
                print("\nFalling back to standard vector search results:")
                print("-" * 100)
                for i, case_id in enumerate(case_ids, 1):
                    case = collection.find_one({"case_id": case_id})
                    if case:
                        animal_details = case.get('data', {}).get('animal_details', {})
                        species = animal_details.get('species', 'Unknown')
                        age = animal_details.get('age', 'Unknown')
                        sex = animal_details.get('sex', 'Unknown')
                        summary = case.get('data', {}).get('summary', 'No summary')
                        if len(summary) > 100:
                            summary = summary[:97] + "..."
                        print(f"{i:2d}. [{case_id}] {species}, {age}y, {sex} - {summary}")
        else:
            print("\nTop 20 matching cases:")
            print("-" * 100)
        
        for i, case_id in enumerate(case_ids, 1):
            case = collection.find_one({"case_id": case_id})
            if case:
                animal_details = case.get('data', {}).get('animal_details', {})
                species = animal_details.get('species', 'Unknown')
                age = animal_details.get('age', 'Unknown')
                sex = animal_details.get('sex', 'Unknown')
                summary = case.get('data', {}).get('summary', 'No summary')
                
                # Truncate summary if too long
                if len(summary) > 100:
                    summary = summary[:97] + "..."
                
                # Get all metadata
                report_metadata = case.get('data', {}).get('report_metadata', {})
                metadata_str = []
                
                # Add basic animal details
                metadata_str.append(f"{species}, {age}y, {sex}")
                
                # Add breed if available
                breed = animal_details.get('breed')
                if breed:
                    metadata_str.append(f"Breed: {breed}")
                    
                # Add neutered status if available
                neutered = animal_details.get('neutered')
                if neutered:
                    metadata_str.append(f"Neutered: {neutered}")
                    
                # Add report type if available
                report_type = report_metadata.get('report_type')
                if report_type:
                    metadata_str.append(f"Type: {report_type}")
                    
                # Join all metadata with semicolons
                metadata_display = " | ".join(metadata_str)
                
                print(f"{i:2d}. [{case_id}] {metadata_display}")
                print(f"    Summary: {summary}")
        
        print("-" * 100)

def wipe_empty_cases(debug_mode=False):
    """Remove embeddings of cases with insufficient content from the vector store"""
    print_info("Starting empty cases cleanup...", debug_mode=debug_mode)
    
    # Connect to MongoDB
    mongodb_client = MongoClient(os.getenv('MONGODB_URI', 'mongodb://localhost:27017/'))
    db = mongodb_client[_AI_CONFIG.mongo_db]
    mongo_collection = db[_AI_CONFIG.collection_cases]
    
    # Initialize Chroma client
    client = chromadb.PersistentClient(
        path="./cases_vectorstore",
        settings=Settings(anonymized_telemetry=False)
    )
    collection = client.get_or_create_collection(name="cases")
    
    # Get all cases from vector store
    vector_store_data = collection.get()
    total_cases = len(vector_store_data["ids"])
    print_info(f"Found {total_cases} cases in vector store", debug_mode=debug_mode)
    
    cases_to_remove = []
    
    # Check each case
    for i, case_id in enumerate(vector_store_data["ids"]):
        if debug_mode and i % 1000 == 0:
            print_debug(f"Checking case {i}/{total_cases}...", debug_mode=debug_mode)
            
        # Get case from MongoDB
        case = mongo_collection.find_one({"case_id": case_id})
        if not case:
            print_debug(f"Case {case_id} not found in MongoDB, marking for removal", debug_mode=debug_mode)
            cases_to_remove.append(case_id)
            continue
            
        # Check if case has sufficient content
        text_representation = create_text_representation(case, full_content=False)
        if text_representation is None:
            print_debug(f"Case {case_id} has insufficient content, marking for removal", debug_mode=debug_mode)
            cases_to_remove.append(case_id)
    
    # Remove empty cases
    if cases_to_remove:
        print_info(f"Removing {len(cases_to_remove)} cases with insufficient content...", debug_mode=debug_mode)
        # Remove in batches to avoid memory issues
        batch_size = 1000
        for i in range(0, len(cases_to_remove), batch_size):
            batch = cases_to_remove[i:i + batch_size]
            collection.delete(ids=batch)
            if debug_mode:
                print_debug(f"Removed batch of {len(batch)} cases", debug_mode=debug_mode)
    
    print_info(f"Cleanup complete. Removed {len(cases_to_remove)} cases.", debug_mode=debug_mode)
    
    # Print updated stats
    remaining_cases = collection.count()
    print_info(f"Vector store now contains {remaining_cases} cases", debug_mode=debug_mode)

def get_vectorstore_stats(debug_mode=False):
    """Get statistics about the vector store"""
    print_info("Retrieving vector store statistics...", debug_mode=debug_mode)
    
    # Initialize Chroma client
    client = chromadb.PersistentClient(
        path="./cases_vectorstore",
        settings=Settings(anonymized_telemetry=False)
    )
    collection = client.get_or_create_collection(name="cases")
    
    # Get collection stats
    count = collection.count()
    print_info(f"Total embedded cases: {count}", debug_mode=debug_mode)
    
    # Get peek at a few entries to verify data
    if count > 0:
        peek = collection.peek(limit=1)
        embeddings = peek['embeddings']
        embedding_dim = len(embeddings[0]) if len(embeddings) > 0 else 0
        print_info(f"Embedding dimension: {embedding_dim}", debug_mode=debug_mode)
    
    # Get database size
    db_path = "./cases_vectorstore"
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(db_path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            total_size += os.path.getsize(fp)
    
    print_info(f"Vector store size: {total_size / (1024*1024):.1f} MB", debug_mode=debug_mode)

def main(debug_mode=False, stats_only=False):
    if stats_only:
        get_vectorstore_stats(debug_mode)
        return
        
    # Configuration parameters
    MONGO_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    DB_NAME = _AI_CONFIG.mongo_db
    COLLECTION_NAME = _AI_CONFIG.collection_cases
    CASE_TYPE = None  # Set this if you want to filter by case type
    
    # Connect to MongoDB
    mongodb_client = MongoClient(MONGO_URI)
    mongodb_client.server_info()  # Test connection
    print_info("Successfully connected to MongoDB", debug=False, debug_mode=False)

    db = mongodb_client[DB_NAME]
    mongo_collection = db[COLLECTION_NAME]

    # Construct the query. Prefer the top-level canonical case_type field
    # but fall back to the legacy -TYPE- infix in source_file so that
    # documents predating the migration still filter correctly.
    query = {}
    if CASE_TYPE:
        code = CASE_TYPE.upper()
        query['$or'] = [
            {'case_type': code},
            {'source_file': {'$regex': f'-{code}-'}},
        ]
    
    # We only need the entire cases now, not just case_id
    cursor = mongo_collection.find(query)
    
    # Initialize the embedding model on the configured device
    print_info("Loading the embedding model...", debug=False)

    # Honour AI_FORCE_CPU / AI_CUDA_DEVICE rather than assuming a multi-GPU host
    device = 'cpu' if _AI_CONFIG.force_cpu else (
        f'cuda:{_AI_CONFIG.cuda_device}' if torch.cuda.is_available() else 'cpu'
    )
    if device.startswith('cuda:'):
        torch.cuda.set_device(_AI_CONFIG.cuda_device)
    print_info(f"Using device: {device}", debug=False)

    model = SentenceTransformer(_AI_CONFIG.embedding_model,
                               trust_remote_code=True,
                               device=device)
    model.max_seq_length = _AI_CONFIG.max_seq_length

    # Initialize Chroma vector store at the configured path (telemetry off).
    print_info("Initializing Chroma vector store...", debug=False)
    client = chromadb.PersistentClient(
        path=_AI_CONFIG.vector_store_path,
        settings=Settings(anonymized_telemetry=False),
    )
    collection = client.get_or_create_collection(name="cases")

    # Get total count for progress tracking
    total_cases = mongo_collection.count_documents(query)
    progress = ProgressTracker(total_cases)
    
    # Get existing case IDs from vector store
    existing_ids = set(collection.get()["ids"])
    print_info(f"Found {len(existing_ids)} existing embedded cases", debug_mode=debug_mode)

    # Process each case
    print_info(f"Starting to process {total_cases} cases...", debug_mode=debug_mode)
    batch_docs = []
    batch_ids = []
    batch_metadata = []
    batch_embeddings = []
    BATCH_SIZE = 1000  # For efficiency, process in batches
    count = 0  # Initialize counter
    skipped = 0  # Track skipped cases
    
    for doc in cursor:
        case_id = str(doc.get('case_id', ''))  # Ensure case_id is string
        
        # Skip invalid case IDs
        if not validate_case_id(case_id):
            print_debug(f"Skipping invalid case ID: {case_id}", debug_mode=debug_mode)
            continue
            
        # Skip if already embedded
        if case_id in existing_ids:
            skipped += 1
            continue
        text_representation = create_text_representation(doc, full_content=False)
        
        batch_docs.append(text_representation)
        batch_ids.append(str(case_id))
        # Extract metadata fields for filtering
        data = doc.get('data', {})
        report_metadata = data.get('report_metadata', {})
        animal_details = data.get('animal_details', {})
        
        # Handle animal_details being either a list or dict
        if isinstance(animal_details, list):
            # Take first animal if multiple
            animal_details = animal_details[0] if animal_details else {}
            
        # Build metadata dict, excluding None values.
        # case_format is tagged from the configured case-ID patterns (see
        # vetpathdb/prompts/case_id_patterns.yaml) so labs with non-default
        # ID shapes get useful labels out of the box.
        from vetpathdb.pipeline._utils import detect_case_id_format
        metadata = {
            "case_id": case_id,  # Already validated and converted to string
            "case_format": detect_case_id_format(case_id),
        }

        # Only add non-None values. Populate both `report_type` (for legacy
        # Chroma index filters) and `case_type` (canonical) so queries can
        # use either key once the index is rebuilt.
        resolved_type = doc.get('case_type') or report_metadata.get('report_type')
        if resolved_type:
            metadata["report_type"] = resolved_type
            metadata["case_type"] = resolved_type
            
        for field in ['species', 'breed', 'age', 'sex', 'neutered']:
            if animal_details.get(field) is not None:
                metadata[field] = str(animal_details.get(field))  # Convert all values to strings
        batch_metadata.append(metadata)

        count += 1
        
        # Show sample of text representation and metadata every 100 cases
        if debug_mode and count % 100 == 0:
            print_debug(f"\nSample case {count}:", debug_mode)
            print_debug("Text representation:", debug_mode)
            print_debug(f"{text_representation}", debug_mode)
            print_debug("\nMetadata fields:", debug_mode)
            for key, value in metadata.items():
                print_debug(f"  {key}: {value}", debug_mode)
            print_debug("", debug_mode)

        # If we reached batch size, encode and store
        if len(batch_docs) == BATCH_SIZE:
            print_debug(f"Processing batch of {len(batch_docs)} cases...", debug_mode=debug_mode)
            
            # Time the embedding process
            embed_start = time.time()
            
            # Process the batch
            embeddings = process_batch(batch_docs, model, debug_mode)
            
            embedding_time = time.time() - embed_start
            
            # Update progress and show stats
            progress.update(len(batch_docs), embedding_time, debug_mode=debug_mode)
            
            print_debug("Adding batch to vector store...", debug_mode=debug_mode)
            collection.add(
                documents=batch_docs,
                metadatas=batch_metadata,
                ids=batch_ids,
                embeddings=embeddings
            )
            
            # Clear batches
            batch_docs.clear()
            batch_ids.clear()
            batch_metadata.clear()

    # If there are remaining docs in the batch
    if batch_docs:
        embeddings = model.encode(batch_docs, prompt=_AI_CONFIG.embedding_query_prompt)
        collection.add(
            documents=batch_docs,
            metadatas=batch_metadata,
            ids=batch_ids,
            embeddings=embeddings
        )

    # Print final statistics
    progress.print_status(debug_mode=debug_mode)
    print_info(f"Vector store processing completed successfully. Skipped {skipped} already embedded cases.", debug_mode=debug_mode)
    
    # Note: ChromaDB automatically persists changes, no need to call persist() explicitly

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--stats', action='store_true', help='Show embedding statistics')
    parser.add_argument('--query', action='store_true', help='Run interactive query interface')
    parser.add_argument('--ragfusion', action='store_true', help='Enable RAG fusion for more accurate search results')
    parser.add_argument('--gpu', type=int, default=0, help='GPU device ID to use (default: 0)')
    parser.add_argument('--wipe-empty-cases', action='store_true', help='Remove embeddings of cases with insufficient content')
    args = parser.parse_args()
    
    if args.wipe_empty_cases:
        wipe_empty_cases(debug_mode=args.debug)
    elif args.query:
        # Connect to MongoDB
        mongodb_client = MongoClient(os.getenv('MONGODB_URI', 'mongodb://localhost:27017/'))
        run_interactive_query(mongodb_client, debug_mode=args.debug, rag_fusion=args.ragfusion)
    else:
        main(debug_mode=args.debug, stats_only=args.stats)

