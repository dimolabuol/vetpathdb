#!/usr/bin/env python3
"""
HTTP MCP Server Integration for VetPathDB using FastMCP
Provides HTTP transport for MCP tools and database access
"""

import logging
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
from bson import json_util

from fastmcp import FastMCP
from vetpathdb.search.semantic import AISearchManager
from vetpathdb.pipeline._utils import is_valid_case_id as validate_case_id

logger = logging.getLogger(__name__)


def _registered_codes() -> list[str]:
    """Return the uppercase codes of every registered case-type schema."""
    try:
        from vetpathdb.prompts.loader import list_schemas
        return sorted({s["code"].upper() for s in list_schemas() if s.get("code")})
    except Exception:
        return []


# Computed at import time so the schema hint we return to MCP clients reflects
# whichever schemas the operator has under vetpathdb/prompts/schemas/.
_REPORT_TYPE_HINT = (
    f"string ({', '.join(_registered_codes()) or 'see /api/schemas for available codes'})"
)

class VetPathDBMCPHTTP:
    def __init__(self, collection=None, filestore=None, ai_search_manager=None):
        """Initialize HTTP MCP server with shared database resources"""
        self.collection = collection
        self.filestore = filestore
        self.ai_search_manager = ai_search_manager
        
        # Initialize FastMCP server — keep version in lockstep with the package.
        from vetpathdb import __version__ as _vetpathdb_version
        self.mcp = FastMCP(name="vetpathdb", version=_vetpathdb_version)
        self._setup_tools()

    def _setup_tools(self):
        """Register all MCP tools using FastMCP decorators"""
        
        @self.mcp.tool
        def get_database_schema(include_examples: bool = False) -> str:
            """Discover the database schema including available collections, field types, and data structure"""
            try:
                schema_info = {
                    "collections": {
                        "processed_cases": "Main pathology cases with structured data",
                        "filestore": "Text files associated with cases",
                        "ai_search_tasks": "Background AI search task tracking",
                        "ai_search_results": "Large AI search result sets"
                    },
                    "case_schema": {
                        "case_id": "string - Unique case identifier",
                        "data": {
                            "report_metadata": {
                                "case_id": "string",
                                "report_type": _REPORT_TYPE_HINT,
                                "pathologist": "string",
                                "date_received": "string",
                                "date_reported": "string"
                            },
                            "animal_details": {
                                "species": "string",
                                "breed": "string",
                                "age": "string",
                                "sex": "string"
                            },
                            "clinical_details": {
                                "history": "string",
                                "clinical_presentation": "string",
                                "duration": "string"
                            },
                            "gross_findings": {
                                "description": "string",
                                "organs_affected": "array of strings"
                            },
                            "histopathology": {
                                "diagnosis": "string - Primary diagnosis",
                                "tumor_type": "string",
                                "morphological_features": "array of strings",
                                "immunohistochemistry": "object with test results"
                            }
                        }
                    }
                }
                
                if include_examples and self.collection is not None:
                    # Add sample case data but limit field sizes
                    sample_cases = list(self.collection.find().limit(2))  # Reduced from 3
                    processed_samples = []
                    for case in sample_cases:
                        # Create a summarized version to avoid token limits
                        summary = {
                            "case_id": case.get("case_id", "Unknown"),
                            "data": {
                                "animal_details": case.get("data", {}).get("animal_details", {}),
                                "report_metadata": case.get("data", {}).get("report_metadata", {}),
                                "histopathology": {
                                    "diagnosis": case.get("data", {}).get("histopathology", {}).get("diagnosis", ""),
                                    "tumor_type": case.get("data", {}).get("histopathology", {}).get("tumor_type", "")
                                }
                            }
                        }
                        processed_samples.append(summary)
                    
                    schema_info["sample_cases"] = processed_samples
                    schema_info["note"] = "Sample cases have been summarized to show key fields only"
                
                return json_util.dumps(schema_info, indent=2)
                
            except Exception as e:
                logger.error(f"Database schema error: {str(e)}")
                return f"Database schema error: {str(e)}"

        @self.mcp.tool
        def get_field_values(field_path: str, limit: int = 20) -> str:
            """Get unique values for a specific field across all cases"""
            try:
                if self.collection is None:
                    return "Database connection not available"
                
                # Use MongoDB aggregation to get distinct values
                pipeline = [
                    {"$match": {field_path: {"$exists": True, "$nin": [None, ""]}}},
                    {"$group": {"_id": f"${field_path}"}},
                    {"$limit": limit},
                    {"$sort": {"_id": 1}}
                ]
                
                distinct_values = list(self.collection.aggregate(pipeline))
                values = [doc["_id"] for doc in distinct_values if doc["_id"]]
                
                result = {
                    "field": field_path,
                    "unique_values": values,
                    "count": len(values),
                    "limited_to": limit
                }
                
                return json_util.dumps(result, indent=2)
                
            except Exception as e:
                logger.error(f"Field values error: {str(e)}")
                return f"Field values error: {str(e)}"

        @self.mcp.tool
        def get_basic_stats() -> str:
            """Get basic statistics about the database"""
            try:
                if self.collection is None:
                    return "Database connection not available"
                
                total_cases = self.collection.count_documents({})
                
                # Get distribution by species
                species_pipeline = [
                    {"$group": {"_id": "$data.animal_details.species", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}},
                    {"$limit": 10}
                ]
                species_dist = list(self.collection.aggregate(species_pipeline))
                
                # Get distribution by report type — prefer the canonical
                # top-level case_type field, fall back to the nested
                # data.report_metadata.report_type for pre-migration docs.
                type_pipeline = [
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
                    {"$group": {"_id": "$_resolved_case_type", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}},
                ]
                type_dist = list(self.collection.aggregate(type_pipeline))
                
                stats = {
                    "total_cases": total_cases,
                    "species_distribution": [
                        {"species": doc["_id"], "count": doc["count"]} 
                        for doc in species_dist if doc["_id"]
                    ],
                    "report_type_distribution": [
                        {"type": doc["_id"], "count": doc["count"]} 
                        for doc in type_dist if doc["_id"]
                    ]
                }
                
                return json_util.dumps(stats, indent=2)
                
            except Exception as e:
                logger.error(f"Basic stats error: {str(e)}")
                return f"Basic stats error: {str(e)}"

        @self.mcp.tool
        def search_cases(query: str, limit: int = 10, skip: int = 0, date_from: Optional[str] = None, date_to: Optional[str] = None) -> str:
            """Search cases using text search on all fields with date filtering and pagination"""
            try:
                if self.collection is None:
                    return "Database connection not available"
                
                # Create text search query with optional date filtering
                search_filter = {"$text": {"$search": query}}
                
                # Add date range filtering
                if date_from or date_to:
                    date_filter = {}
                    if date_from:
                        date_filter["$gte"] = date_from
                    if date_to:
                        date_filter["$lte"] = date_to
                    search_filter["data.report_metadata.date_received"] = date_filter
                
                projection = {
                    "case_id": 1,
                    "data.animal_details.species": 1,
                    "data.animal_details.breed": 1,
                    "data.histopathology.diagnosis": 1,
                    "data.report_metadata.report_type": 1,
                    "data.report_metadata.date_received": 1,
                    "score": {"$meta": "textScore"}
                }
                
                # Get total count for pagination
                total_count = self.collection.count_documents(search_filter)
                
                cursor = self.collection.find(
                    search_filter, projection
                ).sort([("score", {"$meta": "textScore"})]).skip(skip).limit(limit)
                
                results = []
                for case in cursor:
                    result = {
                        "case_id": case.get("case_id", "Unknown"),
                        "species": case.get("data", {}).get("animal_details", {}).get("species", "Unknown"),
                        "breed": case.get("data", {}).get("animal_details", {}).get("breed", "Unknown"),
                        "diagnosis": case.get("data", {}).get("histopathology", {}).get("diagnosis", "Unknown"),
                        "report_type": case.get("data", {}).get("report_metadata", {}).get("report_type", "Unknown"),
                        "relevance_score": case.get("score", 0)
                    }
                    results.append(result)
                
                search_result = {
                    "query": query,
                    "date_from": date_from,
                    "date_to": date_to,
                    "pagination": {
                        "total_count": total_count,
                        "returned_count": len(results),
                        "skip": skip,
                        "limit": limit,
                        "has_more": (skip + len(results)) < total_count,
                        "next_skip": skip + limit if (skip + len(results)) < total_count else None
                    },
                    "results": results
                }
                
                return json_util.dumps(search_result, indent=2)
                
            except Exception as e:
                logger.error(f"Search cases error: {str(e)}")
                return f"Search cases error: {str(e)}"

        @self.mcp.tool
        def semantic_search(query: str, limit: int = 10) -> str:
            """Perform semantic search using AI embeddings"""
            try:
                if self.ai_search_manager is None:
                    # Fallback to text search when AI models not loaded
                    if self.collection is None:
                        return json_util.dumps({"error": "Database not available"})
                    
                    # Use text search as fallback
                    search_filter = {"$text": {"$search": query}}
                    projection = {
                        "case_id": 1,
                        "data.animal_details.species": 1,
                        "data.animal_details.breed": 1,
                        "data.histopathology.diagnosis": 1,
                        "score": {"$meta": "textScore"}
                    }
                    
                    cursor = self.collection.find(
                        search_filter, projection
                    ).sort([("score", {"$meta": "textScore"})]).limit(limit)
                    
                    results = []
                    for case in cursor:
                        result = {
                            "case_id": case.get("case_id", "Unknown"),
                            "similarity_score": case.get("score", 0) / 10,  # Normalize text score
                            "species": case.get("data", {}).get("animal_details", {}).get("species", "Unknown"),
                            "breed": case.get("data", {}).get("animal_details", {}).get("breed", "Unknown"),
                            "diagnosis": case.get("data", {}).get("histopathology", {}).get("diagnosis", "Unknown")
                        }
                        results.append(result)
                    
                    return json_util.dumps({
                        "query": query,
                        "search_type": "text_fallback",
                        "results_count": len(results),
                        "results": results
                    }, indent=2)
                
                # Use the AI search manager for semantic search (synchronous wrapper)
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    search_results = loop.run_until_complete(
                        self.ai_search_manager.search(query, depth=limit, semantic_only=True)
                    )
                finally:
                    loop.close()
                
                results = []
                for result in search_results:
                    case_data = {
                        "case_id": result.get("case_id", "Unknown"),
                        "similarity_score": result.get("relevance_score", result.get("score", 0)),
                        "species": result.get("species", "Unknown"),
                        "breed": result.get("breed", "Unknown"),
                        "diagnosis": result.get("diagnosis", "Unknown")
                    }
                    results.append(case_data)
                
                search_result = {
                    "query": query,
                    "search_type": "semantic",
                    "results_count": len(results),
                    "results": results
                }
                
                return json_util.dumps(search_result, indent=2)
                
            except Exception as e:
                logger.error(f"Semantic search error: {str(e)}")
                return f"Semantic search error: {str(e)}"

        @self.mcp.tool
        def get_case_details(case_id: str) -> str:
            """Get detailed information for a specific case"""
            try:
                if not validate_case_id(case_id):
                    return f"Invalid case ID format: {case_id}"
                
                if self.collection is None:
                    return "Database connection not available"
                
                case_doc = self.collection.find_one({"case_id": case_id})
                if not case_doc:
                    return f"Case not found: {case_id}"
                
                # Create a version that only truncates truly large content
                case_details = {
                    "case_id": case_doc.get("case_id", "Unknown"),
                    "data": {}
                }
                
                needs_truncation = False
                data = case_doc.get("data", {})
                if data:
                    # Copy main sections but only truncate truly large arrays/strings
                    for section, section_data in data.items():
                        if isinstance(section_data, dict):
                            processed_section = {}
                            for key, value in section_data.items():
                                if isinstance(value, list) and len(value) > 20:
                                    processed_section[key] = value[:20] + [f"... and {len(value) - 20} more items"]
                                    needs_truncation = True
                                elif isinstance(value, str) and len(value) > 3000:
                                    processed_section[key] = value[:3000] + "... (truncated)"
                                    needs_truncation = True
                                else:
                                    processed_section[key] = value
                            case_details["data"][section] = processed_section
                        else:
                            case_details["data"][section] = section_data
                
                # Only add note if we actually truncated
                if needs_truncation:
                    case_details["note"] = "Some large arrays or text fields have been truncated"
                
                return json_util.dumps(case_details, indent=2)
                
            except Exception as e:
                logger.error(f"Case details error: {str(e)}")
                return f"Case details error: {str(e)}"

        @self.mcp.tool 
        def get_yearly_stats(start_year: int = 2015, end_year: int = 2022) -> str:
            """Get yearly statistics with proper date handling for mixed date formats"""
            try:
                if self.collection is None:
                    return "Database connection not available"
                
                # Handle mixed date formats in the database
                pipeline = [
                    {
                        "$match": {
                            "data.report_metadata.date_received": {"$exists": True, "$nin": [None, "", "multiple"]}
                        }
                    },
                    {
                        "$addFields": {
                            "parsed_year": {
                                "$cond": {
                                    "if": {"$regexMatch": {"input": "$data.report_metadata.date_received", "regex": "^\\d{4}-\\d{2}-\\d{2}$"}},
                                    # YYYY-MM-DD format
                                    "then": {"$toInt": {"$substr": ["$data.report_metadata.date_received", 0, 4]}},
                                    "else": {
                                        "$cond": {
                                            "if": {"$regexMatch": {"input": "$data.report_metadata.date_received", "regex": "^\\d{2}/\\d{2}/\\d{2}$"}},
                                            # DD/MM/YY format - convert YY to YYYY
                                            "then": {
                                                "$add": [
                                                    {"$toInt": {"$substr": ["$data.report_metadata.date_received", 6, 2]}},
                                                    2000  # Assume 20XX for 2-digit years
                                                ]
                                            },
                                            "else": None
                                        }
                                    }
                                }
                            }
                        }
                    },
                    {
                        "$match": {
                            "parsed_year": {"$gte": start_year, "$lte": end_year, "$ne": None}
                        }
                    },
                    {
                        "$group": {
                            "_id": {
                                "year": "$parsed_year",
                                "species": "$data.animal_details.species"
                            },
                            "count": {"$sum": 1}
                        }
                    },
                    {
                        "$group": {
                            "_id": "$_id.year",
                            "total_cases": {"$sum": "$count"},
                            "species_breakdown": {
                                "$push": {
                                    "species": "$_id.species",
                                    "count": "$count"
                                }
                            }
                        }
                    },
                    {"$sort": {"_id": 1}},
                    {"$limit": 20}  # Limit years to prevent large responses
                ]
                
                results = list(self.collection.aggregate(pipeline))
                
                yearly_stats = {
                    "year_range": {"start": start_year, "end": end_year},
                    "total_years": len(results),
                    "yearly_data": []
                }
                
                for result in results:
                    year_data = {
                        "year": result["_id"],
                        "total_cases": result["total_cases"],
                        "top_species": sorted(result["species_breakdown"], key=lambda x: x["count"], reverse=True)[:5]
                    }
                    yearly_stats["yearly_data"].append(year_data)
                
                return json_util.dumps(yearly_stats, indent=2)
                
            except Exception as e:
                logger.error(f"Yearly stats error: {str(e)}")
                return f"Yearly stats error: {str(e)}"

        @self.mcp.tool
        def custom_aggregation(pipeline_json: str) -> str:
            """Execute a custom MongoDB aggregation pipeline (use get_yearly_stats for date-based queries)"""
            try:
                if self.collection is None:
                    return "Database connection not available"
                
                import json
                pipeline = json.loads(pipeline_json)
                
                # Safety check - limit results only for queries that could return many records
                has_group_by_id = any(
                    isinstance(stage, dict) and "$group" in stage and 
                    stage["$group"].get("_id") not in [None, "$_id"]
                    for stage in pipeline
                )
                
                if not any(stage.get("$limit") for stage in pipeline if isinstance(stage, dict)):
                    # Only add limit if this looks like it could return many individual records
                    if has_group_by_id or any(stage.get("$match") for stage in pipeline if isinstance(stage, dict)):
                        pipeline.append({"$limit": 100})  # Higher limit for legitimate queries
                
                results = list(self.collection.aggregate(pipeline))
                
                # Smart truncation based on content type
                needs_truncation = False
                processed_results = []
                
                for result in results:
                    processed_result = {}
                    for key, value in result.items():
                        if isinstance(value, list):
                            # Only truncate very large arrays
                            if len(value) > 50:
                                processed_result[key] = value[:50] + [f"... and {len(value) - 50} more items"]
                                needs_truncation = True
                            else:
                                processed_result[key] = value
                        elif isinstance(value, str) and len(value) > 2000:
                            # Only truncate very long strings
                            processed_result[key] = value[:2000] + "... (truncated)"
                            needs_truncation = True
                        else:
                            processed_result[key] = value
                    processed_results.append(processed_result)
                
                # Build response
                aggregation_result = {
                    "results_count": len(processed_results),
                    "results": processed_results
                }
                
                # Only add truncation note if we actually truncated something
                if needs_truncation:
                    aggregation_result["note"] = "Some large arrays or strings have been truncated"
                
                # Check if we have too many results (not response size)
                if len(processed_results) > 200:
                    # Only truncate if we have many individual results
                    truncated_results = processed_results[:200]
                    aggregation_result = {
                        "results_count": len(results),
                        "results_shown": len(truncated_results),
                        "results": truncated_results,
                        "note": f"Showing first {len(truncated_results)} of {len(results)} results to manage response size"
                    }
                
                return json_util.dumps(aggregation_result, indent=2)
                
            except Exception as e:
                logger.error(f"Custom aggregation error: {str(e)}")
                return f"Custom aggregation error: {str(e)}"

        @self.mcp.tool
        def list_cases_by_criteria(
            species: Optional[str] = None,
            breed: Optional[str] = None,
            diagnosis_contains: Optional[str] = None,
            report_type: Optional[str] = None,
            date_from: Optional[str] = None,
            date_to: Optional[str] = None,
            limit: int = 20,
            skip: int = 0
        ) -> str:
            """List cases matching specific criteria with date filtering and pagination"""
            try:
                if self.collection is None:
                    return "Database connection not available"
                
                # Build the filter
                filter_criteria = {}
                
                if species:
                    filter_criteria["data.animal_details.species"] = {"$regex": species, "$options": "i"}
                
                if breed:
                    filter_criteria["data.animal_details.breed"] = {"$regex": breed, "$options": "i"}
                
                if diagnosis_contains:
                    filter_criteria["data.histopathology.diagnosis"] = {"$regex": diagnosis_contains, "$options": "i"}
                
                if report_type:
                    filter_criteria["data.report_metadata.report_type"] = report_type
                
                # Add date range filtering
                if date_from or date_to:
                    date_filter = {}
                    if date_from:
                        date_filter["$gte"] = date_from
                    if date_to:
                        date_filter["$lte"] = date_to
                    filter_criteria["data.report_metadata.date_received"] = date_filter
                
                # Get total count for pagination info
                total_count = self.collection.count_documents(filter_criteria)
                
                cursor = self.collection.find(filter_criteria).skip(skip).limit(limit).sort("data.report_metadata.date_received", -1)
                
                results = []
                for case in cursor:
                    result = {
                        "case_id": case.get("case_id", "Unknown"),
                        "species": case.get("data", {}).get("animal_details", {}).get("species", "Unknown"),
                        "breed": case.get("data", {}).get("animal_details", {}).get("breed", "Unknown"),
                        "diagnosis": case.get("data", {}).get("histopathology", {}).get("diagnosis", "Unknown"),
                        "report_type": case.get("data", {}).get("report_metadata", {}).get("report_type", "Unknown")
                    }
                    results.append(result)
                
                search_result = {
                    "criteria": {
                        "species": species,
                        "breed": breed,
                        "diagnosis_contains": diagnosis_contains,
                        "report_type": report_type,
                        "date_from": date_from,
                        "date_to": date_to
                    },
                    "pagination": {
                        "total_count": total_count,
                        "returned_count": len(results),
                        "skip": skip,
                        "limit": limit,
                        "has_more": (skip + len(results)) < total_count,
                        "next_skip": skip + limit if (skip + len(results)) < total_count else None
                    },
                    "results": results
                }
                
                return json_util.dumps(search_result, indent=2)
                
            except Exception as e:
                logger.error(f"List cases error: {str(e)}")
                return f"List cases error: {str(e)}"

        @self.mcp.tool
        def explore_field_relationships(field1: str, field2: str, limit: int = 20) -> str:
            """Explore relationships between two fields in the database"""
            try:
                if self.collection is None:
                    return "Database connection not available"
                
                pipeline = [
                    {"$match": {
                        field1: {"$exists": True, "$nin": [None, ""]},
                        field2: {"$exists": True, "$nin": [None, ""]}
                    }},
                    {"$group": {
                        "_id": {
                            "field1": f"${field1}",
                            "field2": f"${field2}"
                        },
                        "count": {"$sum": 1}
                    }},
                    {"$sort": {"count": -1}},
                    {"$limit": limit}
                ]
                
                relationships = list(self.collection.aggregate(pipeline))
                
                result = {
                    "field1": field1,
                    "field2": field2,
                    "relationships": [
                        {
                            field1: doc["_id"]["field1"],
                            field2: doc["_id"]["field2"],
                            "count": doc["count"]
                        }
                        for doc in relationships
                    ],
                    "total_relationships": len(relationships)
                }
                
                return json_util.dumps(result, indent=2)
                
            except Exception as e:
                logger.error(f"Field relationship analysis error: {str(e)}")
                return f"Field relationship analysis error: {str(e)}"

        @self.mcp.tool
        def get_date_range_info() -> str:
            """Get the date range of cases in the database"""
            try:
                if self.collection is None:
                    return "Database connection not available"
                
                # Use aggregation to get date range
                pipeline = [
                    {
                        "$match": {
                            "data.report_metadata.date_received": {"$exists": True, "$nin": [None, ""]}
                        }
                    },
                    {
                        "$group": {
                            "_id": None,
                            "min_date": {"$min": "$data.report_metadata.date_received"},
                            "max_date": {"$max": "$data.report_metadata.date_received"},
                            "total_cases_with_dates": {"$sum": 1}
                        }
                    }
                ]
                
                results = list(self.collection.aggregate(pipeline))
                
                if results:
                    result = results[0]
                    date_info = {
                        "earliest_case": result.get("min_date"),
                        "latest_case": result.get("max_date"),
                        "total_cases_with_dates": result.get("total_cases_with_dates"),
                        "date_format_info": "Dates are in YYYY-MM-DD format for filtering",
                        "usage_examples": {
                            "last_year_2022": {"date_from": "2022-01-01", "date_to": "2022-12-31"},
                            "specific_month": {"date_from": "2020-06-01", "date_to": "2020-06-30"},
                            "recent_cases": {"date_from": "2020-01-01"}
                        }
                    }
                else:
                    date_info = {
                        "error": "No cases with valid dates found",
                        "total_cases_with_dates": 0
                    }
                
                return json_util.dumps(date_info, indent=2)
                
            except Exception as e:
                logger.error(f"Date range info error: {str(e)}")
                return f"Date range info error: {str(e)}"

    def get_asgi_app(self):
        """Get the ASGI application for mounting in FastAPI"""
        # The path is handled by FastAPI mounting, so we use root path here
        return self.mcp.http_app(path='/')

def create_mcp_http_integration(collection=None, filestore=None, ai_search_manager=None):
    """Factory function to create MCP HTTP integration"""
    return VetPathDBMCPHTTP(collection, filestore, ai_search_manager)