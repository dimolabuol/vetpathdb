from fastapi import APIRouter, HTTPException, Request
from typing import Dict, Any
import logging
import json
import traceback
from bson import json_util

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["analysis"]
)

@router.get("/morphological-analysis")
async def get_morphological_analysis(request: Request):
    collection = request.state.collection
    logger.info("Starting morphological analysis")
    try:
        def categorize_size(size_str):
            if not size_str:
                return None
            size_str = size_str.lower()
            if any(term in size_str for term in ['small', 'tiny', '5-10', '<10']):
                return 'small'
            elif any(term in size_str for term in ['medium', 'moderate', '10-20']):
                return 'medium'
            elif any(term in size_str for term in ['large', 'enlarged', '>20', 'swollen']):
                return 'large'
            elif any(term in size_str for term in ['variable', 'heterometric', 'varied']):
                return 'variable'
            return None

        def categorize_shape(shape_str):
            if not shape_str:
                return None
            shape_str = shape_str.lower()
            if any(term in shape_str for term in ['round', 'oval', 'circular']):
                return 'round'
            elif any(term in shape_str for term in ['polygonal', 'angular']):
                return 'polygonal'
            elif any(term in shape_str for term in ['spindle', 'spindloid', 'elongated']):
                return 'spindle'
            elif any(term in shape_str for term in ['pleomorphic', 'variable', 'irregular']):
                return 'pleomorphic'
            return None

        pipeline = [
            {"$match": {
                "data.histopathology.morphological_features": {"$exists": True},
                "data.histopathology.tumor_type": {"$ne": None}
            }},
            {"$group": {
                "_id": "$data.histopathology.tumor_type",
                "raw_features": {"$push": "$data.histopathology.morphological_features"},
                "count": {"$sum": 1}
            }},
            {"$sort": {"count": -1}},
            {"$limit": 10}
        ]

        results = list(collection.aggregate(pipeline))
        
        analyzed_results = []
        for tumor in results:
            if not tumor['_id']:
                continue
                
            size_counts = {'small': 0, 'medium': 0, 'large': 0, 'variable': 0}
            shape_counts = {'round': 0, 'polygonal': 0, 'spindle': 0, 'pleomorphic': 0}
            
            for features in tumor['raw_features']:
                if isinstance(features, dict):
                    for feature in features.values():
                        size = categorize_size(str(feature))
                        if size:
                            size_counts[size] += 1
                        
                        shape = categorize_shape(str(feature))
                        if shape:
                            shape_counts[shape] += 1
            
            total_cases = tumor['count']
            analyzed_results.append({
                'tumor_type': tumor['_id'],
                'total_cases': total_cases,
                'features': {
                    'size': {k: {'count': v, 'percentage': round((v/total_cases)*100, 1)} 
                            for k, v in size_counts.items() if v > 0},
                    'shape': {k: {'count': v, 'percentage': round((v/total_cases)*100, 1)}
                             for k, v in shape_counts.items() if v > 0}
                }
            })
        
        return {"analysis": analyzed_results}
    except Exception as e:
        logger.error(f"Error in morphological analysis: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing morphological analysis: {str(e)}"
        )

@router.get("/ihc-patterns")
async def get_ihc_patterns(request: Request):
    collection = request.state.collection
    logger.info("Starting IHC patterns analysis")
    try:
        logger.debug("Building aggregation pipeline")
        pipeline = [
            {
                "$match": {
                    "data.histopathology.immunohistochemistry.results": {"$exists": True, "$ne": []}
                }
            },
            {
                "$unwind": "$data.histopathology.immunohistochemistry.results"
            },
            {
                "$project": {
                    "tumor_type": {"$ifNull": ["$data.histopathology.tumor_type", "Unknown"]},
                    "marker": "$data.histopathology.immunohistochemistry.results.marker",
                    "intensity": "$data.histopathology.immunohistochemistry.results.intensity",
                    "distribution": "$data.histopathology.immunohistochemistry.results.distribution"
                }
            },
            {
                "$group": {
                    "_id": {
                        "tumor_type": "$tumor_type",
                        "marker": "$marker"
                    },
                    "patterns": {
                        "$push": {
                            "intensity": "$intensity",
                            "distribution": "$distribution"
                        }
                    },
                    "count": {"$sum": 1}
                }
            },
            {
                "$sort": {"count": -1}
            }
        ]

        results = list(collection.aggregate(pipeline))
        
        processed_results = {}
        for result in results:
            tumor_type = result.get('_id', {}).get('tumor_type', 'Unknown')
            marker = result['_id']['marker']
            
            if not marker:
                continue
                
            if tumor_type not in processed_results:
                processed_results[tumor_type] = []
                
            intensity_counts = {}
            distribution_counts = {}
            total_patterns = len(result['patterns'])
            
            for pattern in result['patterns']:
                if pattern.get('intensity'):
                    intensity = pattern['intensity'].lower().strip()
                    intensity_counts[intensity] = intensity_counts.get(intensity, 0) + 1
                    
                if pattern.get('distribution'):
                    distribution = pattern['distribution'].lower().strip()
                    distribution_counts[distribution] = distribution_counts.get(distribution, 0) + 1
            
            marker_data = {
                'marker': marker,
                'total_cases': result['count'],
                'patterns': {
                    'intensity': {
                        k: {
                            'count': v,
                            'percentage': round((v/total_patterns)*100, 1)
                        } for k, v in intensity_counts.items()
                    },
                    'distribution': {
                        k: {
                            'count': v,
                            'percentage': round((v/total_patterns)*100, 1)
                        } for k, v in distribution_counts.items()
                    }
                }
            }
            
            processed_results[tumor_type].append(marker_data)

        return {"patterns": processed_results}
    except Exception as e:
        logger.error(f"Error in get_ihc_patterns: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing IHC patterns: {str(e)}"
        )

@router.get("/breed-patterns")
async def get_breed_patterns(request: Request):
    collection = request.state.collection
    logger.info("Starting breed patterns analysis")
    try:
        logger.debug("Building aggregation pipeline")
        pipeline = [
            {
                "$group": {
                    "_id": {
                        "species": "$data.animal_details.species",
                        "breed": "$data.animal_details.breed"
                    },
                    "diagnoses": {"$push": "$data.histopathology.diagnosis"},
                    "tumor_types": {"$push": "$data.histopathology.tumor_type"},
                    "clinical_diagnoses": {"$push": "$data.clinical_details.clinical_diagnosis"},
                    "clinical_suspicions": {"$push": "$data.clinical_details.clinical_suspicion"},
                    "gross_findings": {"$push": "$data.gross_findings.tissue_samples.description"},
                    "age_stats": {
                        "$push": {
                            "$cond": [
                                { "$and": [
                                    { "$ne": ["$data.animal_details.age", None] },
                                    { "$ne": ["$data.animal_details.age", ""] },
                                    # Generous upper bound: covers tortoises/parrots (60+),
                                    # treats anything over 150 as data error and excludes.
                                    { "$lt": ["$data.animal_details.age", 150] },
                                    { "$gt": ["$data.animal_details.age", 0] }
                                ]},
                                "$data.animal_details.age",
                                None
                            ]
                        }
                    },
                    "sex_stats": {
                        "$push": {
                            "sex": "$data.animal_details.sex",
                            "neutered": "$data.animal_details.neutered"
                        }
                    },
                    "locations": {"$push": "$data.histopathology.tumor_location"},
                    "count": {"$sum": 1},
                    "tumor_cases": {
                        "$sum": {
                            "$cond": [
                                { "$ne": ["$data.histopathology.tumor_type", None] },
                                1,
                                0
                            ]
                        }
                    }
                }
            },
            {
                "$project": {
                    "_id": 1,
                    "diagnoses": 1,
                    "tumor_types": 1,
                    "age_stats": 1,
                    "sex_stats": 1,
                    "locations": 1,
                    "count": 1,
                    "tumor_cases": 1,
                    "tumor_percentage": {
                        "$multiply": [
                            { "$divide": ["$tumor_cases", "$count"] },
                            100
                        ]
                    }
                }
            },
            {
                "$sort": {
                    "count": -1
                }
            }
        ]
        
        results = list(collection.aggregate(pipeline))
        json_results = json.loads(json_util.dumps(results))
        return {"patterns": json_results}
            
    except Exception as e:
        logger.error(f"Error in get_breed_patterns: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing breed patterns: {str(e)}"
        )

@router.get("/diagnostic-timeline")
async def get_diagnostic_timeline(request: Request):
    collection = request.state.collection
    logger.info("Starting diagnostic timeline analysis")
    try:
        logger.debug("Building aggregation pipeline")
        # Excluded terms: species, technical/IHC terms, generic anatomical/pathological terms
        excluded_keywords = [
            # Species
            "canine", "equine", "feline", "bovine", "ovine", "porcine", "avian",
            "dog", "cat", "horse", "cow", "sheep", "pig", "bird",
            # Technical/IHC terms
            "immunohistochemistry", "immunohistology", "ki67 index", "ki67",
            "ckit pattern", "vimentin", "neoplastic cells", "cox-2",
            # Generic pathological terms
            "neoplasm", "neoplasia", "inflammation", "haemorrhage", "hemorrhage",
            "fibrosis", "necrosis", "oedema", "edema", "ulceration", "tumor",
            "granulation tissue", "pulmonary oedema", "metastasis",
            # Generic anatomical terms
            "subcutaneous", "dermal", "skin", "lymph node", "liver disease",
            "lymphoplasmacytic", "neutrophils", "macrophages", "lymphocytes",
            # Generic descriptors
            "t cell", "b cell"
        ]
        # Keyword normalisation: fold variant spellings and synonyms onto a
        # single canonical form so analytics consolidate across them. We pick
        # British spelling as the canonical form arbitrarily (consistent with
        # the demo data); US input is folded onto the UK form. Reports written
        # in either English variant are analysed identically.
        keyword_normalization = {
            # FIP / Feline Coronavirus -> FCoV
            "fip": "fcov",
            "feline coronavirus": "fcov",
            "feline infectious peritonitis": "fcov",
            "coronavirus": "fcov",
            # US/UK spelling pairs (US → UK canonical).
            "mast cell tumor": "mast cell tumour",
            "hemangiosarcoma": "haemangiosarcoma",
            "hemangioma": "haemangioma",
            "edema": "oedema",
            "esophagus": "oesophagus",
            "esophageal": "oesophageal",
            "hematoma": "haematoma",
            "hematology": "haematology",
            "leukemia": "leukaemia",
            "diarrhea": "diarrhoea",
            "anemia": "anaemia",
            "fetal": "foetal",
            "color": "colour",
            "gray": "grey",
            "tumor": "tumour",
            # Sarcoid variations
            "equine sarcoid": "sarcoid",
            "equine sarcoids": "sarcoid",
            "sarcoids": "sarcoid",
            # Lymphoma subtypes - normalize hyphenation
            "t-cell lymphoma": "t cell lymphoma",
            "b-cell lymphoma": "b cell lymphoma",
            "tcell lymphoma": "t cell lymphoma",
            "bcell lymphoma": "b cell lymphoma",
        }
        pipeline = [
            {
                "$match": {
                    "data.case_keywords": {"$exists": True, "$type": "array"}
                }
            },
            {
                "$project": {
                    "year": {"$substr": ["$data.report_metadata.date_received", 0, 4]},
                    "keywords": "$data.case_keywords"
                }
            },
            {
                "$match": {
                    "year": {"$ne": ""}
                }
            },
            {"$unwind": "$keywords"},
            {
                "$project": {
                    "year": 1,
                    "keyword_raw": {"$toLower": "$keywords"}
                }
            },
            {
                # Apply keyword normalization
                "$project": {
                    "year": 1,
                    "keyword": {
                        "$switch": {
                            "branches": [
                                {"case": {"$eq": ["$keyword_raw", k]}, "then": v}
                                for k, v in keyword_normalization.items()
                            ],
                            "default": "$keyword_raw"
                        }
                    }
                }
            },
            {
                "$match": {
                    "keyword": {"$nin": excluded_keywords}
                }
            },
            {
                "$group": {
                    "_id": {
                        "year": "$year",
                        "keyword": "$keyword"
                    },
                    "count": {"$sum": 1}
                }
            },
            {"$sort": {"count": -1}},
            {
                "$group": {
                    "_id": "$_id.year",
                    "keywords": {
                        "$push": {
                            "term": "$_id.keyword",
                            "count": "$count"
                        }
                    }
                }
            },
            {
                "$project": {
                    "year": "$_id",
                    "keywords": {"$slice": ["$keywords", 10]}
                }
            },
            {"$sort": {"year": 1}}
        ]

        results = list(collection.aggregate(pipeline))

        if not results:
            logger.warning("No results found in diagnostic timeline aggregation")
            return {"timeline": []}

        processed_results = json.loads(json_util.dumps(results))
        return {"timeline": processed_results}
    except Exception as e:
        logger.error(f"Error in get_diagnostic_timeline: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing diagnostic timeline: {str(e)}"
        )

@router.get("/database-explorer")
async def get_database_explorer(request: Request):
    """Get database schema and field statistics for the explorer"""
    collection = request.state.collection
    logger.info("Starting database explorer schema analysis")
    try:
        # Define the schema structure based on the processed_cases collection
        schema = {
            "case_id": {"type": "string", "path": "case_id"},
            "data": {
                "type": "object",
                "children": {
                    "report_metadata": {
                        "type": "object",
                        "children": {
                            "case_id": {"type": "string", "path": "data.report_metadata.case_id"},
                            "report_type": {"type": "string", "path": "data.report_metadata.report_type"},
                            "pathologist": {"type": "string", "path": "data.report_metadata.pathologist"},
                            "date_received": {"type": "string", "path": "data.report_metadata.date_received"},
                            "date_reported": {"type": "string", "path": "data.report_metadata.date_reported"}
                        }
                    },
                    "animal_details": {
                        "type": "object",
                        "children": {
                            "species": {"type": "string", "path": "data.animal_details.species"},
                            "breed": {"type": "string", "path": "data.animal_details.breed"},
                            "age": {"type": "mixed", "path": "data.animal_details.age"},
                            "sex": {"type": "string", "path": "data.animal_details.sex"},
                            "neutered": {"type": "string", "path": "data.animal_details.neutered"}
                        }
                    },
                    "clinical_details": {
                        "type": "object",
                        "children": {
                            "history": {"type": "string", "path": "data.clinical_details.history"},
                            "clinical_presentation": {"type": "string", "path": "data.clinical_details.clinical_presentation"},
                            "clinical_diagnosis": {"type": "string", "path": "data.clinical_details.clinical_diagnosis"},
                            "clinical_suspicion": {"type": "string", "path": "data.clinical_details.clinical_suspicion"}
                        }
                    },
                    "gross_findings": {
                        "type": "object",
                        "children": {
                            "tissue_samples": {
                                "type": "object",
                                "children": {
                                    "description": {"type": "string", "path": "data.gross_findings.tissue_samples.description"}
                                }
                            }
                        }
                    },
                    "histopathology": {
                        "type": "object",
                        "children": {
                            "diagnosis": {"type": "mixed", "path": "data.histopathology.diagnosis"},
                            "tumor_type": {"type": "string", "path": "data.histopathology.tumor_type"},
                            "tumor_location": {"type": "string", "path": "data.histopathology.tumor_location"},
                            "morphological_features": {"type": "object", "path": "data.histopathology.morphological_features"},
                            "immunohistochemistry": {
                                "type": "object",
                                "children": {
                                    "results": {
                                        "type": "array",
                                        "children": {
                                            "marker": {"type": "string", "path": "data.histopathology.immunohistochemistry.results.marker"},
                                            "intensity": {"type": "string", "path": "data.histopathology.immunohistochemistry.results.intensity"},
                                            "distribution": {"type": "string", "path": "data.histopathology.immunohistochemistry.results.distribution"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        # Get total document count
        total_docs = collection.count_documents({})

        # Get field statistics for key fields
        field_stats = {}

        # Stats for species
        species_pipeline = [
            {"$group": {"_id": "$data.animal_details.species", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 20}
        ]
        species_results = list(collection.aggregate(species_pipeline))
        field_stats["data.animal_details.species"] = {
            "unique_count": len(species_results),
            "top_values": [{"value": r["_id"], "count": r["count"]} for r in species_results if r["_id"]]
        }

        # Stats for breed
        breed_pipeline = [
            {"$group": {"_id": "$data.animal_details.breed", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 20}
        ]
        breed_results = list(collection.aggregate(breed_pipeline))
        field_stats["data.animal_details.breed"] = {
            "unique_count": len(breed_results),
            "top_values": [{"value": r["_id"], "count": r["count"]} for r in breed_results if r["_id"]]
        }

        # Stats for tumor_type
        tumor_pipeline = [
            {"$group": {"_id": "$data.histopathology.tumor_type", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 20}
        ]
        tumor_results = list(collection.aggregate(tumor_pipeline))
        field_stats["data.histopathology.tumor_type"] = {
            "unique_count": len(tumor_results),
            "top_values": [{"value": r["_id"], "count": r["count"]} for r in tumor_results if r["_id"]]
        }

        # Stats for report_type
        report_type_pipeline = [
            {"$group": {"_id": "$data.report_metadata.report_type", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        report_type_results = list(collection.aggregate(report_type_pipeline))
        field_stats["data.report_metadata.report_type"] = {
            "unique_count": len(report_type_results),
            "top_values": [{"value": r["_id"], "count": r["count"]} for r in report_type_results if r["_id"]]
        }

        return {
            "schema": schema,
            "total_documents": total_docs,
            "field_stats": field_stats
        }
    except Exception as e:
        logger.error(f"Error in database explorer: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error loading database explorer: {str(e)}"
        )

@router.post("/database-explorer/query")
async def execute_explorer_query(request: Request, query_params: Dict[str, Any]):
    """Execute pre-built aggregation queries for the database explorer"""
    collection = request.state.collection
    logger.info(f"Executing explorer query: {query_params}")
    try:
        query_type = query_params.get("query_type")
        field_path = query_params.get("field_path")

        if query_type == "field_distribution":
            # Get value distribution for a specific field
            limit = query_params.get("limit", 50)
            pipeline = [
                {"$group": {"_id": f"${field_path}", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": limit}
            ]
            results = list(collection.aggregate(pipeline))
            return {
                "query_type": "field_distribution",
                "field": field_path,
                "results": [{"value": r["_id"], "count": r["count"]} for r in results if r["_id"] is not None]
            }

        elif query_type == "cross_field_analysis":
            # Analyze relationship between two fields
            field1 = query_params.get("field1")
            field2 = query_params.get("field2")
            limit = query_params.get("limit", 20)

            pipeline = [
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
            results = list(collection.aggregate(pipeline))
            return {
                "query_type": "cross_field_analysis",
                "field1": field1,
                "field2": field2,
                "results": [{
                    "field1_value": r["_id"]["field1"],
                    "field2_value": r["_id"]["field2"],
                    "count": r["count"]
                } for r in results if r["_id"]["field1"] is not None and r["_id"]["field2"] is not None]
            }

        elif query_type == "count_by_filter":
            # Count documents matching specific criteria
            filters = query_params.get("filters", {})
            match_stage = {}
            for field, value in filters.items():
                match_stage[field] = value

            count = collection.count_documents(match_stage)
            return {
                "query_type": "count_by_filter",
                "filters": filters,
                "count": count
            }

        elif query_type == "field_completeness":
            # Check how many documents have non-null values for a field
            total_docs = collection.count_documents({})
            non_null_docs = collection.count_documents({field_path: {"$exists": True, "$ne": None}})

            return {
                "query_type": "field_completeness",
                "field": field_path,
                "total_documents": total_docs,
                "non_null_count": non_null_docs,
                "completeness_percentage": round((non_null_docs / total_docs * 100), 2) if total_docs > 0 else 0
            }

        else:
            raise HTTPException(status_code=400, detail=f"Unknown query type: {query_type}")

    except Exception as e:
        logger.error(f"Error executing explorer query: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error executing query: {str(e)}"
        )

@router.post("/database-explorer/search")
async def search_database(request: Request, search_params: Dict[str, Any]):
    """Search the database with keywords and optional field filtering"""
    collection = request.state.collection
    logger.info(f"Database search: {search_params}")

    try:
        query = search_params.get("query", "").strip()
        field_filter = search_params.get("field_filter", "all")
        skip = search_params.get("skip", 0)
        limit = search_params.get("limit", 50)

        if not query:
            raise HTTPException(status_code=400, detail="Search query is required")

        # Build regex pattern for case-insensitive search
        regex_pattern = {"$regex": query, "$options": "i"}

        # Define searchable fields based on filter
        search_fields_map = {
            "all": [
                "data.histopathology.diagnosis",
                "data.histopathology.tumor_type",
                "data.histopathology.tumor_location",
                "data.animal_details.species",
                "data.animal_details.breed",
                "data.clinical_details.history",
                "data.clinical_details.clinical_presentation",
                "data.clinical_details.clinical_diagnosis",
                "data.clinical_details.clinical_suspicion",
                "data.gross_findings.tissue_samples.description",
                "case_id"
            ],
            "diagnosis": [
                "data.histopathology.diagnosis",
                "data.histopathology.tumor_type",
                "data.clinical_details.clinical_diagnosis"
            ],
            "clinical": [
                "data.clinical_details.history",
                "data.clinical_details.clinical_presentation",
                "data.clinical_details.clinical_suspicion"
            ],
            "animal": [
                "data.animal_details.species",
                "data.animal_details.breed"
            ],
            "tumor": [
                "data.histopathology.tumor_type",
                "data.histopathology.tumor_location"
            ]
        }

        search_fields = search_fields_map.get(field_filter, search_fields_map["all"])

        # Build MongoDB $or query for multiple fields
        match_conditions = [
            {field: regex_pattern} for field in search_fields
        ]

        match_stage = {"$or": match_conditions}

        # Get total count
        total_count = collection.count_documents(match_stage)

        # Get paginated results
        results = list(collection.find(match_stage).skip(skip).limit(limit))

        # Process results to find matching excerpts
        processed_results = []
        for doc in results:
            case_data = {
                "_id": str(doc["_id"]),
                "case_id": doc.get("case_id", ""),
                "report_type": doc.get("data", {}).get("report_metadata", {}).get("report_type", ""),
                "species": doc.get("data", {}).get("animal_details", {}).get("species", ""),
                "breed": doc.get("data", {}).get("animal_details", {}).get("breed", ""),
                "age": doc.get("data", {}).get("animal_details", {}).get("age", ""),
                "sex": doc.get("data", {}).get("animal_details", {}).get("sex", ""),
                "diagnosis": doc.get("data", {}).get("histopathology", {}).get("diagnosis", ""),
                "tumor_type": doc.get("data", {}).get("histopathology", {}).get("tumor_type", ""),
                "full_document": doc.get("data", {})
            }

            # Find matching excerpt
            excerpt = find_matching_excerpt(doc, query, search_fields)
            case_data["excerpt"] = excerpt

            processed_results.append(case_data)

        return {
            "query": query,
            "field_filter": field_filter,
            "total_count": total_count,
            "returned_count": len(processed_results),
            "skip": skip,
            "limit": limit,
            "has_more": (skip + len(processed_results)) < total_count,
            "results": json.loads(json_util.dumps(processed_results))
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in database search: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error executing search: {str(e)}"
        )

def find_matching_excerpt(doc, query, search_fields, context_chars=150):
    """Find and return excerpt from document showing where the query matched"""
    import re

    query_lower = query.lower()

    # Define friendly field names for display
    field_names = {
        "data.histopathology.diagnosis": "Diagnosis",
        "data.histopathology.tumor_type": "Tumor Type",
        "data.histopathology.tumor_location": "Tumor Location",
        "data.animal_details.species": "Species",
        "data.animal_details.breed": "Breed",
        "data.clinical_details.history": "Clinical History",
        "data.clinical_details.clinical_presentation": "Clinical Presentation",
        "data.clinical_details.clinical_diagnosis": "Clinical Diagnosis",
        "data.clinical_details.clinical_suspicion": "Clinical Suspicion",
        "data.gross_findings.tissue_samples.description": "Gross Findings",
        "case_id": "Case ID"
    }

    # Search through fields in order to find match
    for field_path in search_fields:
        # Navigate nested structure
        value = doc
        try:
            for key in field_path.split('.'):
                if isinstance(value, dict):
                    value = value.get(key, "")
                else:
                    value = ""
                    break

            # Handle arrays (like diagnosis)
            if isinstance(value, list):
                value = " ".join(str(v) for v in value if v)

            value_str = str(value) if value else ""

            if query_lower in value_str.lower():
                # Found a match - extract excerpt with context
                match_pos = value_str.lower().find(query_lower)

                # Calculate excerpt boundaries
                start = max(0, match_pos - context_chars // 2)
                end = min(len(value_str), match_pos + len(query) + context_chars // 2)

                excerpt = value_str[start:end]

                # Add ellipsis if truncated
                if start > 0:
                    excerpt = "..." + excerpt
                if end < len(value_str):
                    excerpt = excerpt + "..."

                field_name = field_names.get(field_path, field_path.split('.')[-1])
                return f"{field_name}: {excerpt}"

        except Exception:
            continue

    return "No excerpt available"
