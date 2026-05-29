from typing import Dict, List
from vetpathdb.storage.cases import case_storage


class CaseAnalyzer:
    """Aggregation helpers used by the analysis API routes."""

    @staticmethod
    def get_diagnostic_timeline() -> List[Dict]:
        """Get diagnostic timeline analysis"""
        pipeline = [
            {
                "$project": {
                    "year": {"$substr": ["$data.report_metadata.date_received", 0, 4]},
                    "diagnosis": {
                        "$cond": {
                            "if": {"$isArray": "$data.histopathology.diagnosis"},
                            "then": {"$arrayElemAt": ["$data.histopathology.diagnosis", 0]},
                            "else": "$data.histopathology.diagnosis"
                        }
                    }
                }
            },
            {
                "$project": {
                    "year": 1,
                    "diagnosis": {"$toLower": {"$ifNull": ["$diagnosis", ""]}}
                }
            },
            {"$match": {"diagnosis": {"$ne": ""}}},
            {"$group": {
                "_id": {
                    "year": "$year",
                    "phrase": "$diagnosis"
                },
                "count": {"$sum": 1}
            }},
            {"$sort": {"count": -1}},
            {"$group": {
                "_id": "$_id.year",
                "keywords": {
                    "$push": {
                        "term": "$_id.phrase",
                        "count": "$count"
                    }
                }
            }},
            {"$project": {
                "year": "$_id",
                "keywords": {"$slice": ["$keywords", 10]}
            }},
            {"$sort": {"year": 1}}
        ]
        return case_storage.execute_aggregation(pipeline)

    @staticmethod
    def get_breed_patterns() -> List[Dict]:
        """Get breed patterns analysis"""
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
            {"$sort": {"count": -1}}
        ]
        return case_storage.execute_aggregation(pipeline)

    @staticmethod
    def get_ihc_patterns() -> List[Dict]:
        """Get immunohistochemistry patterns analysis"""
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
            {"$sort": {"count": -1}}
        ]
        return case_storage.execute_aggregation(pipeline)
