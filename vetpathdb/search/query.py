from fastapi import HTTPException
from pymongo.command_cursor import CommandCursor
from bson import json_util
import json
import logging
import re
import traceback
from typing import Dict, List, Optional, Any
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class Filter(BaseModel):
    category: str
    term: str

class QueryRequest(BaseModel):
    type: str
    pipeline: Optional[List[Dict[str, Any]]] = None
    search: Optional[str] = None
    category: Optional[str] = None
    options: Optional[Dict[str, Any]] = None
    filters: Optional[List[Filter]] = None

async def handle_query(request: QueryRequest, collection):
    if request.type == "stats":
        # Handle stats query
        result = list(collection.aggregate(request.pipeline))
        # Convert to JSON-serializable format using json_util
        return {"results": json.loads(json_util.dumps(result))}
        
    elif request.type == "search":
        return await _handle_search_query(request, collection)
        
    elif request.type == "aggregate":
        # Handle aggregation pipeline. Strip BSON types so FastAPI can
        # serialise the response.
        result = list(collection.aggregate(request.pipeline))
        return {"results": json.loads(json_util.dumps(result))}
        
    else:
        raise HTTPException(status_code=400, detail="Invalid query type")

async def _handle_search_query(request: QueryRequest, collection):
    try:
        collection.create_index([("$**", "text")])
    except Exception:
        pass

    # Build combined search query
    query_conditions = []
    mongo_query = {}
    
    # Process search term
    if request.search:
        # Add case ID specific search patterns
        case_id_conditions = []
        search_term = request.search.strip()
        
        # Treat the search term as a possible case ID when it is a single
        # whitespace-free token containing at least one digit. Match it both
        # exactly and by prefix so partial IDs still surface.
        if search_term and not re.search(r'\s', search_term) and re.search(r'\d', search_term) and len(search_term) <= 32:
            case_id_conditions.append({"case_id": search_term})
            case_id_conditions.append({"case_id": {"$regex": f"^{re.escape(search_term)}", "$options": "i"}})
        
        mongo_query = {
            "$or": [
                *case_id_conditions,
                {"data.comment": {"$regex": request.search, "$options": "i"}},
                {"data.summary": {"$regex": request.search, "$options": "i"}},
                {"data.animal_details.breed": {"$regex": request.search, "$options": "i"}},
                {"data.animal_details.species": {"$regex": request.search, "$options": "i"}}
            ]
        }
    else:
        mongo_query = {}

    try:
        # Set up base projection for required fields
        base_projection = {
            "case_id": 1,
            "data.animal_details": 1,
            "data.comment": 1,
            "data.summary": 1,
            "data.case_keywords": 1
        }

        cursor = collection.find(mongo_query, base_projection)

        if request.options and "limit" in request.options:
            limit = max(1, request.options["limit"])
            cursor = cursor.limit(limit)
            logger.debug(f"Applied limit: {limit}")
        
        results = list(cursor)
        return {"results": json.loads(json_util.dumps(results))}

    except Exception as e:
        logger.error("=== MongoDB Query Error ===")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.error(f"Stack trace:\n{traceback.format_exc()}")
        logger.error("=== Query Details ===")
        logger.error(f"MongoDB query: {json.dumps(mongo_query, indent=2)}")
        logger.error(f"Projection: {json.dumps(base_projection, indent=2)}")
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {type(e).__name__} - {str(e)}"
        )
