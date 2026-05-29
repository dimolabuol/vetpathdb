from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pymongo import MongoClient
from pymongo.command_cursor import CommandCursor
from bson import json_util
import json
import logging
import traceback
import re
import argparse
import sys
import asyncio
from datetime import datetime, timedelta
import chromadb
from chromadb.config import Settings
from openai import OpenAI
from vetpathdb.api.analysis import router as analysis_router
from vetpathdb.storage.analysis import CaseAnalyzer
from vetpathdb.prompts.loader import render_prompt

import os

# Configure base logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('requests.log')
    ]
)

# Configure request logging format
request_logger = logging.getLogger('request_logger')
request_logger.setLevel(logging.INFO)
file_handler = logging.FileHandler('requests.log')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
request_logger.addHandler(file_handler)
request_logger.propagate = False

# Silence noisy loggers
logging.getLogger("pymongo").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
    
logger = logging.getLogger(__name__)
from typing import Optional, List, Dict, Any, Union
from vetpathdb.pipeline._utils import is_valid_case_id as validate_case_id
import uvicorn
from pydantic import BaseModel, Field, validator
from datetime import datetime
import uuid
from fastapi.background import BackgroundTasks

class Filter(BaseModel):
    category: str
    term: str

# FastAPI app factory function for proper MCP integration
def create_app():
    """Create FastAPI application with optional MCP integration"""
    
    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        """App lifespan context - startup and shutdown logic"""
        logger.info("🚀 Starting VetPathDB application...")

        # Ensure MongoDB indexes exist (best-effort; safe if DB is absent)
        _ensure_indexes()

        # Startup logic that was previously in startup_event
        global ai_search_manager

        # Skip model loading if flag is set (for faster testing)
        if os.getenv('SKIP_MODELS') == 'true':
            logger.info("⚡ Skipping AI model loading (--skip-models flag)")
            ai_search_manager = None
        else:
            from vetpathdb.search.semantic import AISearchManager
            from vetpathdb.config import AIConfig
            try:
                ai_config = AIConfig()
                logger.info(f"🗄️ Using vector database: {ai_config.vector_store_path}")
                ai_search_manager = AISearchManager(collection, ai_config)
            except Exception as e:
                logger.error(f"Failed to initialize AI search manager: {e}")
                ai_search_manager = None

        # Clean up orphaned "running" tasks from previous server instance
        orphaned = tasks_collection.update_many(
            {"status": "running"},
            {"$set": {
                "status": "error",
                "error": "Server restarted while task was running",
                "completed_at": datetime.utcnow()
            }}
        )
        if orphaned.modified_count > 0:
            logger.info(f"Cleaned up {orphaned.modified_count} orphaned running tasks from previous instance")

        # Start the background queue worker
        await start_queue_worker()

        yield  # Application running

        # Shutdown logic that was previously in shutdown_event
        logger.info("🛑 Shutting down VetPathDB application...")

        # Stop the queue worker
        await stop_queue_worker()

        if ai_search_manager:
            ai_search_manager.cleanup()
    
    # Check if MCP integration is enabled (environment variable or command line)
    mcp_enabled = os.getenv('MCP_ENABLED') == 'true'
    
    # Also check command line arguments directly (handles race condition during uvicorn import)
    try:
        import sys
        mcp_enabled = mcp_enabled or '--mcp' in sys.argv
    except (ImportError, AttributeError):
        pass
    
    if mcp_enabled:
        logger.info("🔗 MCP integration enabled - creating combined lifespan...")
        
        # Create MCP integration first
        from vetpathdb.mcp.server import create_mcp_http_integration
        mcp_http = create_mcp_http_integration(
            collection=collection,
            filestore=db[_cfg.collection_filestore],
            ai_search_manager=None  # Will be set in lifespan
        )
        mcp_app = mcp_http.get_asgi_app()
        
        @asynccontextmanager 
        async def combined_lifespan(app: FastAPI):
            """Combined lifespan for app and MCP server"""
            async with app_lifespan(app):
                # Update MCP integration with initialized ai_search_manager
                mcp_http.ai_search_manager = ai_search_manager
                async with mcp_app.lifespan(app):
                    logger.info("✅ MCP server lifespan initialized")
                    yield
                logger.info("✅ MCP server lifespan cleaned up")
        
        # Create FastAPI app with combined lifespan
        app = FastAPI(
            title="Veterinary Pathology Database Explorer",
            lifespan=combined_lifespan
        )
        
        # Mount MCP server
        app.mount("/mcp", mcp_app)
        logger.info("🎯 MCP server mounted at /mcp")
        
    else:
        # Create app without MCP integration
        app = FastAPI(
            title="Veterinary Pathology Database Explorer", 
            lifespan=app_lifespan
        )
        logger.info("📱 FastAPI app created without MCP integration")
    
    return app

# Database connection - must be initialized before app creation.
# serverSelectionTimeoutMS keeps a missing/unreachable MongoDB from hanging
# for the 30s default — importing this module (e.g. in CI or tooling) does
# not touch the server, and a misconfigured deployment fails fast.
client = MongoClient(
    os.getenv('MONGODB_URI', 'mongodb://localhost:27017/'),
    serverSelectionTimeoutMS=5000,
)
# Use demo database if DEMO_MODE environment variable is set; all other
# collection/DB names come from AIConfig so operators can namespace
# deployments without editing code.
from vetpathdb.config import AIConfig as _AIConfig
_cfg = _AIConfig()
db_name = _cfg.mongo_db_demo if os.getenv('DEMO_MODE') == 'true' else _cfg.mongo_db
db = client[db_name]
collection = db[_cfg.collection_cases]
tasks_collection = db[_cfg.collection_ai_search_tasks]
results_collection = db[_cfg.collection_ai_search_results]


def _ensure_indexes():
    """Create the MongoDB indexes the app relies on.

    Called from the application startup lifespan rather than at import time,
    so that simply importing ``vetpathdb.app`` (CI, tests, tooling) never
    requires a running MongoDB. Index creation is best-effort: a missing or
    unreachable database logs a warning and the server still starts (keyword
    features degrade gracefully, AI features error per-request)."""
    try:
        # Tasks: 24h TTL + queue lookup (status, created_at)
        tasks_collection.create_index([("created_at", 1)], expireAfterSeconds=86400)
        tasks_collection.create_index([("status", 1), ("created_at", 1)])
        # Results: by task_id, by (task_id, score) for sorted retrieval, 24h TTL
        results_collection.create_index([("task_id", 1)])
        results_collection.create_index([("task_id", 1), ("score", -1)])
        results_collection.create_index([("created_at", 1)], expireAfterSeconds=86400)
        # Cases: wildcard text index for keyword search
        collection.create_index([("$**", "text")])
        logger.info("MongoDB indexes ensured")
    except Exception as e:
        logger.warning(f"Could not ensure MongoDB indexes (continuing without): {e}")

# Create the app instance
app = create_app()

# Mount the analysis routes
app.include_router(
    analysis_router,
    prefix=""
)

# Make MongoDB collection available to routes
@app.middleware("http")
async def log_requests(request, call_next):
    # Get client IP
    if request.client:
        client_ip = request.client.host
    else:
        client_ip = "unknown"
    
    # Add collection to request state
    request.state.collection = collection
    
    # Process request
    response = await call_next(request)
    
    # Log the request
    request_logger.info(
        f"{client_ip} - \"{request.method} {request.url.path}\" {response.status_code}"
    )
    
    return response

# Mount static files and PDF directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Custom PDF file handler. The on-disk root is configurable via
# AI_PDF_ROOT_PATH so labs can store PDFs on NFS / shared storage without
# editing code.
@app.get("/pdf/{case_id}/{path:path}")
async def get_pdf(case_id: str, path: str):
    # Resolve the request against the configured PDF root and require the
    # resolved path to stay inside it. realpath + commonpath defeats traversal
    # tricks (encoded segments, leading "/", symlinks) that a substring ".."
    # check misses.
    root = os.path.realpath(_cfg.pdf_root_path)
    requested = os.path.realpath(os.path.join(root, case_id, path))
    try:
        inside = os.path.commonpath([root, requested]) == root
    except ValueError:
        inside = False
    if not inside:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not os.path.isfile(requested):
        raise HTTPException(status_code=404, detail="PDF file not found")

    return FileResponse(requested)

# Database connection moved to before app creation

# Serve index.html at root
@app.get("/")
async def read_root():
    return FileResponse("static/index.html")

# API Models
class AiSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Search query string")
    depth: Optional[Union[int, str]] = Field(default=20, description="Search depth")
    report_type: Optional[str] = Field(default=None, description="Report type filter")
    semantic_only: Optional[bool] = Field(default=False, description="If true, perform semantic search only")

    @validator('depth')
    def validate_depth(cls, v):
        if v is None:
            return 20  # Default to 20 if null
        if isinstance(v, str):
            if v != "everything":
                raise ValueError('String depth value must be "everything"')
        elif isinstance(v, int) and v <= 0:
            raise ValueError('Depth must be positive')
        return v

class ChatRequest(BaseModel):
    case_id: str
    message: str
    history: Optional[List[Dict[str, str]]] = []

class TaskResponse(BaseModel):
    task_id: str
    status: str
    queue_position: Optional[int] = None  # Position in queue (only for queued tasks)

class QueryRequest(BaseModel):
    type: str
    pipeline: Optional[List[Dict[str, Any]]] = None
    search: Optional[str] = None
    category: Optional[str] = None
    options: Optional[Dict[str, Any]] = None
    reportType: Optional[str] = None
    filters: Optional[List[Filter]] = None  # Now using Filter model

class SearchQuery(BaseModel):
    term: str
    limit: Optional[int] = 20

class StatsResponse(BaseModel):
    total_cases: int
    unique_species: int
    avg_age: Optional[float] = None
    species_distribution: Optional[List[Dict]] = None
    yearly_cases: Optional[List[Dict]] = None
    diagnosis_distribution: Optional[Dict] = None
    top_diagnoses: Optional[List[Dict]] = None
    top_pathologists: Optional[List[Dict]] = None
    case_type_distribution: Optional[List[Dict]] = None
    recent_activity: Optional[Dict] = None

# API Endpoints
@app.post("/api/query")
async def query(request: QueryRequest):
    # Detailed request logging — enable with VETPATHDB_DEBUG_SEARCH=true or
    # `--debug-search` (the CLI flag sets the env var before app import).
    if os.getenv("VETPATHDB_DEBUG_SEARCH") == "true":
        filters = getattr(request, 'filters', [])
        filter_str = "|".join([f"{f.category}:{f.term}" for f in filters]) if filters else "none"
        search_str = getattr(request, 'search', '')
        options_str = json.dumps(request.options) if request.options else '{}'
        logger.info(f"REQ|type={request.type}|report={getattr(request, 'reportType', 'none')}|search={search_str}|filters={filter_str}|options={options_str}")
    
    try:
        from vetpathdb.search.query import handle_query
        return await handle_query(request, collection)
    except Exception as e:
        logger.error("=== Unhandled API Error ===")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.error(f"Stack trace:\n{traceback.format_exc()}")
        logger.error("=== Request Details ===")
        logger.error(f"Request data: {json.dumps(request.dict(), indent=2, default=str)}")
        raise HTTPException(
            status_code=500,
            detail=f"API error: {type(e).__name__} - {str(e)}"
        )

@app.get("/api/schemas")
async def get_registered_schemas():
    """Return every case-type schema currently registered under vetpathdb/prompts/schemas/.

    Drives the frontend's report-type dropdown and the MCP discovery surface.
    Each entry exposes the schema's short code, human-readable name, the icon
    the UI should render, and the plural label shown in dropdowns.
    """
    try:
        from vetpathdb.prompts.loader import list_schemas
        entries = []
        for s in list_schemas():
            ui = s.get("ui") or {}
            entries.append({
                "code": s.get("code", ""),
                "name": s.get("name", ""),
                "description": s.get("description", ""),
                "icon": ui.get("icon"),
                "label_plural": ui.get("label_plural") or f"{s.get('code', '')} Reports",
            })
        return entries
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats", response_model=StatsResponse)
async def get_basic_stats():
    # Force reload test
    try:
        pipeline = [
            {
                "$facet": {
                    "total_cases": [{ "$count": "count" }],
                    "unique_species": [
                        { "$group": { "_id": "$data.animal_details.species" } },
                        { "$count": "count" }
                    ],
                    "avg_age": [
                        { "$match": { "data.animal_details.age": { "$exists": True, "$ne": None, "$type": "number" } } },
                        { "$group": { "_id": None, "avg": { "$avg": "$data.animal_details.age" } } }
                    ],
                    "species_distribution": [
                        { "$group": { "_id": "$data.animal_details.species", "count": { "$sum": 1 } } },
                        { "$sort": { "count": -1 } },
                        { "$limit": 10 }
                    ],
                    "yearly_cases": [
                        { 
                            "$match": { 
                                "data.report_metadata.date_received": { 
                                    "$exists": True, 
                                    "$ne": None,
                                    "$ne": ""  # Add this to filter out empty strings
                                } 
                            } 
                        },
                        { 
                            "$project": { 
                                "year": { 
                                    "$year": { 
                                        "$dateFromString": { 
                                            "dateString": "$data.report_metadata.date_received",
                                            "onError": None  # Handle parsing errors
                                        } 
                                    } 
                                } 
                            } 
                        },
                        { "$match": { "year": { "$ne": None } } },  # Filter out null years
                        { "$group": { "_id": "$year", "count": { "$sum": 1 } } },
                        { "$sort": { "_id": 1 } }
                    ],
                    "diagnosis_distribution": [
                        { "$project": { 
                            "is_tumor": { "$cond": [{ "$regexMatch": { "input": "$data.histopathology.diagnosis", "regex": "tumor|neoplasia|carcinoma|sarcoma", "options": "i" } }, 1, 0] },
                            "is_inflammatory": { "$cond": [{ "$regexMatch": { "input": "$data.histopathology.diagnosis", "regex": "inflammation|itis|infection", "options": "i" } }, 1, 0] },
                            "is_degenerative": { "$cond": [{ "$regexMatch": { "input": "$data.histopathology.diagnosis", "regex": "degeneration|atrophy|dystrophy", "options": "i" } }, 1, 0] }
                        }},
                        { "$group": { 
                            "_id": None, 
                            "tumor": { "$sum": "$is_tumor" },
                            "inflammatory": { "$sum": "$is_inflammatory" },
                            "degenerative": { "$sum": "$is_degenerative" }
                        }}
                    ],
                    "top_diagnoses": [
                        { "$match": { "data.histopathology.diagnosis": { "$exists": True, "$ne": None } } },
                        { "$group": { "_id": "$data.histopathology.diagnosis", "count": { "$sum": 1 } } },
                        { "$sort": { "count": -1 } },
                        { "$limit": 5 }
                    ],
                    "top_pathologists": [
                        { "$match": { "data.report_metadata.pathologist": { "$exists": True, "$nin": [None, ""] } } },
                        { "$group": { "_id": { "$ifNull": ["$data.report_metadata.pathologist", "Unknown"] }, "count": { "$sum": 1 } } },
                        { "$match": { "_id": { "$ne": "" } } },
                        { "$sort": { "count": -1 } },
                        { "$limit": 10 }
                    ],
                    "recent_activity": [
                        { 
                            "$match": { 
                                "data.report_metadata.date_received": { 
                                    "$exists": True, 
                                    "$ne": None,
                                    "$ne": ""  # Add this to filter out empty strings
                                } 
                            } 
                        },
                        { 
                            "$project": { 
                                "date": { 
                                    "$dateFromString": { 
                                        "dateString": "$data.report_metadata.date_received",
                                        "onError": None  # Handle parsing errors
                                    } 
                                }
                            }
                        },
                        { "$match": { "date": { "$ne": None } } },  # Filter out null dates
                        { "$match": { 
                            "date": { 
                                "$gte": { 
                                    "$dateFromString": { 
                                        "dateString": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d") 
                                    } 
                                } 
                            } 
                        }},
                        { "$count": "weekly_additions" }
                    ],
                    "case_type_distribution": [
                        {
                            "$addFields": {
                                "_resolved_case_type": {
                                    "$ifNull": [
                                        "$case_type",
                                        "$data.report_metadata.report_type",
                                    ]
                                }
                            }
                        },
                        { "$match": { "_resolved_case_type": { "$exists": True, "$nin": [None, ""] } } },
                        { "$group": { "_id": "$_resolved_case_type", "count": { "$sum": 1 } } },
                        { "$sort": { "count": -1 } }
                    ]
                }
            }
        ]
        
        results = list(collection.aggregate(pipeline))
        if not results:
            return {"total_cases": 0, "unique_species": 0, "avg_age": None}
            
        result = results[0]
        
        # Process the results
        response = {
            "total_cases": result["total_cases"][0]["count"] if result["total_cases"] else 0,
            "unique_species": result["unique_species"][0]["count"] if result["unique_species"] else 0,
            "avg_age": round(result["avg_age"][0]["avg"], 1) if result["avg_age"] else None,
            "species_distribution": result["species_distribution"],
            "yearly_cases": result["yearly_cases"],
            "diagnosis_distribution": result["diagnosis_distribution"][0] if result["diagnosis_distribution"] else {},
            "top_diagnoses": result["top_diagnoses"],
            "top_pathologists": result["top_pathologists"],
            "case_type_distribution": result["case_type_distribution"],
            "recent_activity": {
                "weekly_additions": result["recent_activity"][0]["weekly_additions"] if result["recent_activity"] else 0
            }
        }
        
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/case/{case_id}")
async def get_case_details(case_id: str):
    try:
        if not validate_case_id(case_id):
            raise HTTPException(status_code=400, detail="Invalid case ID format")
            
        case = collection.find_one({"case_id": case_id})
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        return {"case": json.loads(json_util.dumps(case))}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/search")
async def search(query: SearchQuery):
    try:
        # Create text index if it doesn't exist
        try:
            collection.create_index([("$**", "text")])
        except Exception:
            pass

        mongo_query = {"$text": {"$search": query.term}}
        projection = {
            "score": {"$meta": "textScore"},
            "case_id": 1,
            "data": 1  # Include all data fields for complete search results
        }
        logger.debug(f"Search query: {mongo_query}")
        logger.debug(f"Projection: {projection}")

        results = list(collection.find(
            mongo_query,
            projection
        ).sort([("score", {"$meta": "textScore"})]).limit(query.limit))

        # Strip BSON types (ObjectId, datetime) — FastAPI's default
        # encoder can't serialise them.
        return {"results": json.loads(json_util.dumps(results))}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/similar/{case_id}")
async def find_similar_cases(case_id: str):
    try:
        # First get the reference case
        reference_case = collection.find_one({"case_id": case_id})
        if not reference_case:
            raise HTTPException(status_code=404, detail="Case not found")

        # Build matching criteria
        match_criteria = {
            "$and": [
                {"case_id": {"$ne": case_id}},  # Exclude the reference case
                {"$or": [
                    {"data.histopathology.tumor_type": reference_case["data"]["histopathology"]["tumor_type"]},
                    {"data.histopathology.tumor_location": reference_case["data"]["histopathology"]["tumor_location"]},
                    {"data.animal_details.species": reference_case["data"]["animal_details"]["species"]},
                    {"data.animal_details.breed": reference_case["data"]["animal_details"]["breed"]}
                ]}
            ]
        }

        # Find similar cases
        similar_cases = list(collection.find(
            match_criteria,
            {
                "case_id": 1,
                "data.histopathology.diagnosis": 1,
                "data.histopathology.tumor_type": 1,
                "data.histopathology.morphological_features": 1,
                "data.animal_details.species": 1,
                "data.animal_details.breed": 1,
                "data.animal_details.age": 1
            }
        ).limit(10))

        return {"similar_cases": json.loads(json_util.dumps(similar_cases))}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# NOTE: /api/ihc-patterns and /api/breed-patterns are served by
# vetpathdb/api/analysis.py (registered as analysis_router above) — those
# implementations correctly use bson.json_util.dumps to strip BSON types.
# The previous in-app.py copies were shadow-registered and have been removed.

@app.get("/api/file-content/{filename}")
async def get_file_content(filename: str):
    try:
        # Query the filestore collection for the file
        db = client[_cfg.mongo_db]
        filestore = db[_cfg.collection_filestore]
        
        file_doc = filestore.find_one({"filename": filename})
        
        if not file_doc:
            raise HTTPException(status_code=404, detail="File not found")
            
        # Return the file content
        return {"content": file_doc.get("content", "")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Initialize AI search manager - moved to lifespan context
# The ai_search_manager global variable will be set during app startup
ai_search_manager = None

# HTTP MCP integration (no separate server instance needed)
mcp_enabled = False  # Will be set based on command line args


async def process_ai_search(task_id: str, request: AiSearchRequest):
    """Background task to process AI search"""
    try:
        results = await ai_search_manager.search(
            query=request.query,
            depth=request.depth,
            semantic_only=request.semantic_only,
            report_type=request.report_type,
            task_id=task_id
        )
        
        # Always clean up partial results written during batch processing
        results_collection = db[_cfg.collection_ai_search_results]
        results_collection.delete_many({"task_id": task_id})

        # Check if results are too large (approaching MongoDB's 16MB limit)
        # A rough estimate: if we have more than 1000 results, store them separately
        if len(results) > 1000:
            
            # Insert results with task_id reference
            for result in results:
                result["task_id"] = task_id
            
            # Insert in batches to avoid issues with large datasets
            batch_size = 500
            for i in range(0, len(results), batch_size):
                batch = results[i:i+batch_size]
                results_collection.insert_many(batch)
            
            # Update task status without including the full results
            tasks_collection.update_one(
                {"task_id": task_id},
                {
                    "$set": {
                        "status": "completed",
                        "results_stored": "collection",
                        "results_count": len(results),
                        "completed_at": datetime.utcnow()
                    }
                }
            )
        else:
            # For smaller result sets, store directly in the task document
            tasks_collection.update_one(
                {"task_id": task_id},
                {
                    "$set": {
                        "status": "completed",
                        "results": results,
                        "completed_at": datetime.utcnow()
                    }
                }
            )
    except Exception as e:
        logger.error(f"Error in AI search task {task_id}: {str(e)}")
        tasks_collection.update_one(
            {"task_id": task_id},
            {
                "$set": {
                    "status": "error",
                    "error": str(e),
                    "completed_at": datetime.utcnow()
                }
            }
        )

@app.post("/api/ai-search", response_model=TaskResponse)
async def ai_search(request: AiSearchRequest, background_tasks: BackgroundTasks):
    logger.info(f"AI search request: query={request.query}, depth={request.depth}, semantic_only={request.semantic_only}, report_type={request.report_type}")
    logger.debug("=== AI Search Request Details ===")
    logger.debug(f"Query: {request.query}")
    logger.debug(f"Depth: {request.depth}")
    logger.debug(f"Semantic only: {request.semantic_only}")

    # Create task ID
    task_id = str(uuid.uuid4())

    # Smart queuing: semantic-only searches bypass queue, LLM searches check capacity
    if request.semantic_only:
        # Semantic-only searches execute immediately (no LLM, so no queue needed)
        logger.info(f"Semantic-only search - executing immediately (task: {task_id})")

        task = {
            "task_id": task_id,
            "status": "pending",
            "query": request.query,
            "created_at": datetime.utcnow()
        }
        tasks_collection.insert_one(task)

        # Start background processing immediately
        background_tasks.add_task(process_ai_search, task_id, request)

        return {"task_id": task_id, "status": "pending"}

    else:
        # LLM-powered search - check capacity and queue if necessary
        if can_start_task():
            # Capacity available - start immediately
            logger.info(f"LLM search - capacity available, starting immediately (task: {task_id})")

            task = {
                "task_id": task_id,
                "status": "running",  # Mark as running since it's starting now
                "query": request.query,
                "created_at": datetime.utcnow(),
                "started_at": datetime.utcnow()
            }
            tasks_collection.insert_one(task)

            # Start background processing immediately
            background_tasks.add_task(process_ai_search, task_id, request)

            return {"task_id": task_id, "status": "running"}

        else:
            # At capacity - queue the task
            queue_position = enqueue_task(
                task_id=task_id,
                query=request.query,
                depth=request.depth,
                semantic_only=request.semantic_only,
                report_type=request.report_type
            )

            logger.info(f"LLM search - at capacity, queued at position {queue_position} (task: {task_id})")

            return {
                "task_id": task_id,
                "status": "queued",
                "queue_position": queue_position
            }

def filter_ai_search_results(results: list, min_score: float = 0.2) -> list:
    """
    Filter AI search results to exclude cases with N/A scores or scores below threshold.

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


# ==================== Queue Management Functions ====================

def get_queue_status():
    """
    Get current queue status including running and queued tasks.

    Returns:
        Dictionary with queue statistics
    """
    running_count = tasks_collection.count_documents({"status": "running"})
    queued_count = tasks_collection.count_documents({"status": "queued"})

    return {
        "running": running_count,
        "queued": queued_count,
        "total": running_count + queued_count
    }


def can_start_task():
    """
    Check if a new LLM search task can start immediately based on current load.

    Returns:
        True if task can start, False if it should be queued
    """
    # Count currently running tasks
    running_count = tasks_collection.count_documents({"status": "running"})

    # Allow task to start if we have capacity (conservative approach: limit running tasks)
    # This works in conjunction with the global LLM semaphore
    max_concurrent_tasks = 1  # Only allow 1 search at a time, rest are queued
    return running_count < max_concurrent_tasks


def enqueue_task(task_id: str, query: str, depth, semantic_only: bool, report_type: str = None):
    """
    Add a task to the queue.

    Args:
        task_id: Unique task identifier
        query: Search query
        depth: Search depth
        semantic_only: Whether this is semantic-only search
        report_type: Optional report type filter

    Returns:
        Queue position (1-indexed)
    """
    # Get current queue position
    queued_count = tasks_collection.count_documents({"status": "queued"})

    # Create task document
    task_doc = {
        "task_id": task_id,
        "status": "queued",
        "query": query,
        "depth": depth,
        "semantic_only": semantic_only,
        "report_type": report_type,
        "created_at": datetime.utcnow(),
        "queued_at": datetime.utcnow(),
        "queue_position": queued_count + 1,
        "progress": 0,
        "total_cases": 0,
        "processed_cases": 0
    }

    tasks_collection.insert_one(task_doc)
    logger.info(f"Task {task_id} queued at position {queued_count + 1}")

    return queued_count + 1


def dequeue_next_task():
    """
    Get the next queued task and mark it as running.

    Returns:
        Task document if found, None otherwise
    """
    # Find oldest queued task and mark it as running atomically
    task = tasks_collection.find_one_and_update(
        {"status": "queued"},
        {
            "$set": {
                "status": "running",
                "started_at": datetime.utcnow()
            }
        },
        sort=[("created_at", 1)],  # Oldest first (FIFO)
        return_document=True
    )

    if task:
        logger.info(f"Dequeued task {task['task_id']} for processing")
        # Update queue positions for remaining tasks
        update_queue_positions()

    return task


def update_queue_positions():
    """
    Recalculate queue positions for all queued tasks.
    """
    queued_tasks = list(tasks_collection.find(
        {"status": "queued"}
    ).sort("created_at", 1))

    for position, task in enumerate(queued_tasks, start=1):
        tasks_collection.update_one(
            {"task_id": task["task_id"]},
            {"$set": {"queue_position": position}}
        )


def cancel_queued_task(task_id: str):
    """
    Cancel a task that's in the queue (not yet running).

    Args:
        task_id: Task to cancel

    Returns:
        True if cancelled, False if not in queue
    """
    result = tasks_collection.update_one(
        {"task_id": task_id, "status": "queued"},
        {"$set": {"status": "cancelled", "completed_at": datetime.utcnow()}}
    )

    if result.modified_count > 0:
        logger.info(f"Cancelled queued task {task_id}")
        update_queue_positions()
        return True

    return False


# ==================== End Queue Management Functions ====================


# ==================== Background Queue Worker ====================

# Global variable to control queue worker
_queue_worker_running = False
_queue_worker_task = None


async def queue_worker():
    """
    Background worker that processes queued AI search tasks.
    Runs continuously, polling the queue and starting tasks when capacity is available.
    """
    global _queue_worker_running
    _queue_worker_running = True

    from vetpathdb.config import AIConfig
    config = AIConfig()
    poll_interval = config.queue_poll_interval

    logger.info(f"🔄 Queue worker started (poll interval: {poll_interval}s)")

    try:
        MAX_TASK_DURATION_SECONDS = 7200  # 2 hours

        while _queue_worker_running:
            try:
                # Watchdog: expire tasks running longer than max duration
                stale_cutoff = datetime.utcnow() - timedelta(seconds=MAX_TASK_DURATION_SECONDS)
                stale = tasks_collection.update_many(
                    {"status": "running", "started_at": {"$lt": stale_cutoff}},
                    {"$set": {
                        "status": "error",
                        "error": f"Task exceeded maximum duration ({MAX_TASK_DURATION_SECONDS // 3600}h)",
                        "completed_at": datetime.utcnow()
                    }}
                )
                if stale.modified_count > 0:
                    logger.warning(f"Force-expired {stale.modified_count} stale running tasks")

                # Check if we can start a new task
                if can_start_task():
                    # Try to dequeue next task
                    task = dequeue_next_task()

                    if task:
                        logger.info(f"📋 Queue worker starting task {task['task_id']}")

                        request = AiSearchRequest(
                            query=task['query'],
                            depth=task.get('depth', 25),
                            semantic_only=task.get('semantic_only', False),
                            report_type=task.get('report_type')
                        )

                        # Start processing in background (non-blocking)
                        asyncio.create_task(process_ai_search(task['task_id'], request))
                    else:
                        # No tasks in queue, wait before checking again
                        await asyncio.sleep(poll_interval)
                else:
                    # At capacity, wait before checking again
                    await asyncio.sleep(poll_interval)

            except Exception as e:
                logger.error(f"Error in queue worker: {e}", exc_info=True)
                await asyncio.sleep(poll_interval)

    except asyncio.CancelledError:
        logger.info("🛑 Queue worker cancelled")
        raise
    finally:
        _queue_worker_running = False
        logger.info("🛑 Queue worker stopped")


async def start_queue_worker():
    """Start the background queue worker task"""
    global _queue_worker_task
    if _queue_worker_task is None or _queue_worker_task.done():
        _queue_worker_task = asyncio.create_task(queue_worker())
        logger.info("✅ Queue worker task created")
    return _queue_worker_task


async def stop_queue_worker():
    """Stop the background queue worker task"""
    global _queue_worker_running, _queue_worker_task
    _queue_worker_running = False

    if _queue_worker_task and not _queue_worker_task.done():
        _queue_worker_task.cancel()
        try:
            await _queue_worker_task
        except asyncio.CancelledError:
            pass
        logger.info("✅ Queue worker stopped cleanly")


# ==================== End Background Queue Worker ====================

@app.get("/api/ai-search/{task_id}")
async def get_search_status(task_id: str):
    task = tasks_collection.find_one({"task_id": task_id})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    response = {
        "status": task["status"],
        "task_id": task["task_id"]
    }

    # Include queue information if available
    if "queue_position" in task:
        response["queue_position"] = task["queue_position"]

    # Include progress information if available
    if "total_cases" in task:
        response["total_cases"] = task["total_cases"]
    if "processed_cases" in task:
        response["processed_cases"] = task["processed_cases"]
    if "progress" in task:
        response["progress"] = task["progress"]
    if "stage" in task:
        response["stage"] = task["stage"]
    if "stage_description" in task:
        response["stage_description"] = task["stage_description"]
    if "total_found" in task:
        response["total_found"] = task["total_found"]
    if "relevant_found" in task:
        response["relevant_found"] = task["relevant_found"]
    
    if task["status"] == "completed":
        # Check if results are stored in the main task document or in the results collection
        if "results_stored" in task and task["results_stored"] == "collection":
            # Fetch all results from the dedicated results collection
            results_collection = db[_cfg.collection_ai_search_results]

            # Fetch all results
            results = list(results_collection.find(
                {"task_id": task_id},
                {"_id": 0, "task_id": 0}  # Exclude these fields
            ).sort("score", -1))

            # Filter results to exclude N/A and low scores
            filtered_results = filter_ai_search_results(results)
            response["results"] = filtered_results
        else:
            # Fall back to getting results from the task document (legacy mode)
            results = task.get("results", [])
            # Filter results to exclude N/A and low scores
            filtered_results = filter_ai_search_results(results)
            response["results"] = filtered_results
    elif task["status"] in ["running", "queued"]:
        # Fetch only relevant partial results (score >= 0.2) — filter in query, not after enrichment
        results_collection = db[_cfg.collection_ai_search_results]
        partial_result_docs = list(results_collection.find(
            {"task_id": task_id, "score": {"$gte": 0.2}},
            {"_id": 0, "created_at": 0}
        ).sort("score", -1))

        if partial_result_docs:
            # Bulk fetch case data for relevant results only
            relevant_case_ids = [doc["case_id"] for doc in partial_result_docs if doc.get("case_id")]
            case_map = {}
            for case in collection.find({"case_id": {"$in": relevant_case_ids}}):
                case_map[case["case_id"]] = case

            partial_results = []
            for result_doc in partial_result_docs:
                case_id = result_doc.get("case_id")
                if case_id and case_id in case_map:
                    partial_results.append({
                        "case_id": case_id,
                        "score": result_doc.get("score", 0),
                        "reasoning": result_doc.get("reasoning", "Analysis in progress"),
                        "data": case_map[case_id].get("data", {})
                    })

            response["results"] = partial_results
    elif task["status"] == "error":
        response["error"] = task.get("error")
    elif task["status"] == "cancelled":
        response["error"] = "Search cancelled by user"
        
        # Include partial results if available
        if "partial_results" in task and task["partial_results"]:
            # Filter partial results to exclude N/A and low scores
            filtered_partial = filter_ai_search_results(task["partial_results"])
            response["partial_results"] = filtered_partial
            response["partial_results_count"] = len(filtered_partial)
        else:
            # Check if there are results in the results collection
            results_collection = db[_cfg.collection_ai_search_results]
            partial_result_docs = list(results_collection.find(
                {"task_id": task_id, "score": {"$gte": 0.2}},
                {"_id": 0}
            ).sort("score", -1))

            if partial_result_docs:
                relevant_case_ids = [doc["case_id"] for doc in partial_result_docs if doc.get("case_id")]
                case_map = {}
                for case in collection.find({"case_id": {"$in": relevant_case_ids}}):
                    case_map[case["case_id"]] = case

                partial_results = []
                for result in partial_result_docs:
                    case_id = result.get("case_id")
                    if case_id and case_id in case_map:
                        partial_results.append({
                            "case_id": case_id,
                            "score": result.get("score", 0),
                            "reasoning": result.get("reasoning", "Analysis interrupted"),
                            "data": case_map[case_id].get("data", {})
                        })

                response["partial_results"] = partial_results
                response["partial_results_count"] = len(partial_results)

    # Strip BSON types (ObjectId, datetime) from any nested case docs
    # before handing back to FastAPI's JSON encoder.
    return json.loads(json_util.dumps(response))

@app.post("/api/ai-search/{task_id}/cancel")
async def cancel_search(task_id: str):
    logger.info(f"Received cancel request for task: {task_id}")
    task = tasks_collection.find_one({"task_id": task_id})
    if not task:
        logger.warning(f"Task not found for cancellation: {task_id}")
        raise HTTPException(status_code=404, detail="Task not found")
        
    # Allow cancelling tasks in any state
    logger.info(f"Cancelling task: {task_id} with status: {task['status']}")
    
    # Get any partial results that might be available
    partial_results = []
    
    # Check if results are stored in the results collection
    results_collection = db[_cfg.collection_ai_search_results]
    
    # Fetch only relevant partial results (score >= 0.2) from results collection
    partial_result_docs = list(results_collection.find(
        {"task_id": task_id, "score": {"$gte": 0.2}},
        {"_id": 0}
    ).sort("score", -1))

    logger.info(f"Found {len(partial_result_docs)} relevant partial results")

    if partial_result_docs:
        relevant_case_ids = [doc["case_id"] for doc in partial_result_docs if doc.get("case_id")]
        case_map = {}
        for case in collection.find({"case_id": {"$in": relevant_case_ids}}):
            case_map[case["case_id"]] = case

        for result in partial_result_docs:
            case_id = result.get("case_id")
            if case_id and case_id in case_map:
                partial_results.append({
                    "case_id": case_id,
                    "score": result.get("score", 0),
                    "reasoning": result.get("reasoning", "Analysis interrupted"),
                    "data": case_map[case_id].get("data", {})
                })

    logger.info(f"Processed {len(partial_results)} complete partial results")

    filtered_partial_results = partial_results
    logger.info(f"After filtering: {len(filtered_partial_results)} partial results remain")

    # Mark the task as cancelled but include partial results
    tasks_collection.update_one(
        {"task_id": task_id},
        {"$set": {
            "status": "cancelled",
            "partial_results": filtered_partial_results if filtered_partial_results else None,
            "partial_results_count": len(filtered_partial_results)
        }}
    )

    return json.loads(json_util.dumps({
        "status": "cancelled",
        "message": "Task cancelled successfully",
        "partial_results": filtered_partial_results,
        "partial_results_count": len(filtered_partial_results)
    }))


# ==================== Queue Visibility API Endpoints ====================

@app.get("/api/ai-search-queue")
async def get_queue():
    """
    Get all queued and running AI search tasks for queue visibility UI.

    Returns:
        Dictionary with queued, running, and recent completed tasks
    """
    # Get queued tasks (sorted by queue position)
    queued_tasks = list(tasks_collection.find(
        {"status": "queued"},
        {"_id": 0}  # Exclude MongoDB _id
    ).sort("created_at", 1))

    # Get running tasks (sorted by start time)
    running_tasks = list(tasks_collection.find(
        {"status": "running"},
        {"_id": 0}
    ).sort("started_at", 1))

    # Get recently completed/failed/cancelled tasks (last 10)
    recent_tasks = list(tasks_collection.find(
        {"status": {"$in": ["completed", "failed", "cancelled"]}},
        {"_id": 0}
    ).sort("created_at", -1).limit(10))

    # Convert datetime objects to ISO strings for JSON serialization
    for task_list in [queued_tasks, running_tasks, recent_tasks]:
        for task in task_list:
            for date_field in ['created_at', 'queued_at', 'started_at', 'completed_at']:
                if date_field in task and task[date_field]:
                    task[date_field] = task[date_field].isoformat()

    return {
        "queued": queued_tasks,
        "running": running_tasks,
        "recent": recent_tasks,
        "stats": {
            "queued_count": len(queued_tasks),
            "running_count": len(running_tasks),
            "total_active": len(queued_tasks) + len(running_tasks)
        }
    }


@app.delete("/api/ai-search-queue/{task_id}")
async def cancel_queued_task_endpoint(task_id: str):
    """
    Cancel a task in the queue (works for both queued and running tasks).

    Args:
        task_id: Task ID to cancel

    Returns:
        Success message or error
    """
    # First try to cancel if it's queued
    if cancel_queued_task(task_id):
        return {
            "status": "success",
            "message": f"Queued task {task_id} cancelled",
            "task_id": task_id
        }

    # If not queued, check if it's running and use the existing cancel logic
    task = tasks_collection.find_one({"task_id": task_id})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task["status"] == "running":
        # Use the existing cancel endpoint logic
        return await cancel_search(task_id)

    # Task is already completed/failed/cancelled
    raise HTTPException(
        status_code=400,
        detail=f"Task is already {task['status']} and cannot be cancelled"
    )


# ==================== End Queue Visibility API Endpoints ====================

from fastapi.responses import StreamingResponse
import json

@app.post("/api/chat")
async def chat(request: ChatRequest):
    return StreamingResponse(
        stream_chat_response(request),
        media_type='text/event-stream'
    )

async def stream_chat_response(request: ChatRequest):
    try:
        case = collection.find_one({"case_id": request.case_id})
        if not case:
            yield "data: {\"error\": \"Case not found\"}\n\n"
            return
            
        case_text = ai_search_manager.create_text_representation(case, full_content=True, include_files=True)
        
        conversation = []
        for msg in request.history:
            conversation.append({"role": msg["role"], "content": msg["content"]})
            
        system_prompt = render_prompt("chat/consultant_system.txt", case_text=case_text)

        conversation.insert(0, {"role": "system", "content": system_prompt})
        conversation.append({"role": "user", "content": request.message})

        stream = ai_search_manager.llm_client.chat.completions.create(
            model=ai_search_manager.config.llm_model,
            messages=conversation,
            temperature=0.3,
            stream=True
        )
        
        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield f"data: {json.dumps({'token': chunk.choices[0].delta.content})}\n\n"
                
    except Exception as e:
        logger.error(f"Chat error: {str(e)}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"

# NOTE: /api/diagnostic-timeline is served by vetpathdb/api/analysis.py;
# the previous in-app.py duplicate has been removed.

# Startup and shutdown logic moved to lifespan context in create_app() function

def main():
    """Entry point for running VetPathDB server."""
    # Parse command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug-search', action='store_true', help='Enable detailed search debugging output')
    parser.add_argument('--demo-db', action='store_true', help='Use demo database (cases_demo) instead of production database')
    parser.add_argument('--mcp', action='store_true', help='Enable MCP server for AI agent / MCP client integration')
    parser.add_argument('--skip-models', action='store_true', help='Skip AI model loading for faster testing')
    args = parser.parse_args()

    # Set environment variable for demo mode (used by database connection)
    if args.demo_db:
        os.environ['DEMO_MODE'] = 'true'
        logger.info("Demo mode enabled - using cases_demo database")

    # Set MCP flag via environment variable (persists across uvicorn reloads)
    if args.mcp:
        os.environ['MCP_ENABLED'] = 'true'
        logger.info("MCP server enabled - will start with FastAPI application")
        try:
            import fastmcp
        except ImportError:
            logger.error("FastMCP library not installed. Run: pip install vetpathdb[mcp]")
            sys.exit(1)

    # Set skip models flag via environment variable
    if args.skip_models:
        os.environ['SKIP_MODELS'] = 'true'
        logger.info("Model loading will be skipped for faster testing")

    if args.debug_search:
        # Configure debug logging if --debug-search is set
        logger.setLevel(logging.DEBUG)
        # Surface to request-scope handlers via env var (the /api/query
        # handler reads VETPATHDB_DEBUG_SEARCH — it can't see `args`).
        os.environ["VETPATHDB_DEBUG_SEARCH"] = "true"
        formatter = logging.Formatter('%(asctime)s [SEARCH] %(message)s')
        for handler in logger.handlers:
            handler.setFormatter(formatter)
            handler.setLevel(logging.DEBUG)

    # TLS is opt-in: drop a key/cert pair into ./certs/ and the server picks
    # them up automatically. Default is plain HTTP (no openssl ceremony).
    from pathlib import Path
    key_path = Path("certs/key.pem")
    cert_path = Path("certs/cert.pem")
    ssl_kwargs = {}
    scheme = "http"
    if key_path.exists() and cert_path.exists():
        ssl_kwargs = {
            "ssl_keyfile": str(key_path),
            "ssl_certfile": str(cert_path),
        }
        scheme = "https"

    # Port convention: HTTPS uses 9443 (prod) / 9444 (demo); plain HTTP uses
    # 8080 (prod) / 8081 (demo) so the port never implies a TLS that isn't
    # there. VETPATHDB_PORT overrides everything and keeps the Docker port
    # deterministic regardless of whether certs are mounted.
    if args.demo_db:
        default_port = 9444 if scheme == "https" else 8081
    else:
        default_port = 9443 if scheme == "https" else 8080
    port = int(os.getenv("VETPATHDB_PORT", default_port))
    if args.demo_db:
        logger.info(f"Demo mode - starting on port {port}")

    # VetPathDB ships with NO authentication. Bind to loopback by default so a
    # local install is not exposed to the network; override with VETPATHDB_HOST
    # (the Docker image sets it to 0.0.0.0 so the published port works). Only
    # bind to a routable address behind an authenticating reverse proxy.
    host = os.getenv("VETPATHDB_HOST", "127.0.0.1")
    logger.info(f"Serving on {scheme}://{host}:{port}")

    # Start uvicorn server
    import uvicorn
    uvicorn.run(
        "vetpathdb.app:app",
        host=host,
        port=port,
        reload=False,
        workers=1,  # Reduced workers for demo mode stability
        **ssl_kwargs,
    )


if __name__ == "__main__":
    main()
