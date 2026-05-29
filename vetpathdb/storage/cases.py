import os
from pymongo import MongoClient, ASCENDING, DESCENDING, monitoring
from pymongo.command_cursor import CommandCursor
from pymongo.errors import PyMongoError
from bson import json_util
from datetime import datetime
import json
import logging
from typing import List, Dict, Any, Optional, Union
from vetpathdb.models import Case, SearchQuery, Filter
from vetpathdb.config import AIConfig

_AI_CONFIG = AIConfig()

# Configure MongoDB logging - aggressively suppress all MongoDB-related logging
mongodb_loggers = [
    # Core MongoDB loggers
    'pymongo',
    'pymongo.topology',
    'pymongo.connection',
    'pymongo.server',
    'pymongo.monitoring',
    'pymongo.monitoring.commands',
    'pymongo.monitoring.command_logger',
    'pymongo.monitoring.server_heartbeat',
    'pymongo.network',
    'pymongo.periodic_executor',
    'pymongo.pool',
    'pymongo.ocsp',
    'pymongo.mongo_client',
    'pymongo.server_description',
    'pymongo.server_selectors',
    'pymongo.uri_parser',
    # Additional related loggers
    'mongodb',
    'mongodb.monitoring',
    'motor',
    'motor.motor_common'
]

# Disable command monitoring
class CommandLogger(monitoring.CommandListener):
    def started(self, event):
        pass
    def succeeded(self, event):
        pass
    def failed(self, event):
        pass

monitoring.register(CommandLogger())

for logger_name in mongodb_loggers:
    logger = logging.getLogger(logger_name)
    logger.disabled = True
    logger.propagate = False
    logger.setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)

class CaseStorage:
    def __init__(self, mongo_uri=None):
        # Honour MONGODB_URI from the environment (Docker, k8s, custom deployments).
        # Falls back to localhost only when nothing is configured.
        if mongo_uri is None:
            mongo_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
        # serverSelectionTimeoutMS=5000 keeps the import-time _ensure_indexes
        # call from blocking for the pymongo default of 30 s when Mongo isn't
        # reachable (CI smoke tests, dev tooling). Operations still surface a
        # ServerSelectionTimeoutError after 5 s if the DB is down.
        self.client = MongoClient(mongo_uri,
                                heartbeatFrequencyMS=60000,
                                serverSelectionTimeoutMS=5000)
        self.db = self.client[_AI_CONFIG.mongo_db]
        self.collection = self.db[_AI_CONFIG.collection_cases]
        self.filestore = self.db[_AI_CONFIG.collection_filestore]
        self.analysis_cache = self.db[_AI_CONFIG.collection_analysis_cache]
        
        # Create indexes
        self._ensure_indexes()

    def _ensure_indexes(self):
        """Ensure all required indexes exist.

        Tolerant of MongoDB being unreachable at import time — logs a
        warning and returns. The first real query will surface a
        meaningful connection error to the caller. This matters for
        ``import vetpathdb.storage.cases`` to succeed in CI / tooling /
        smoke-test contexts where Mongo isn't running.
        """
        try:
            # Text index for full-text search (only if it doesn't exist)
            try:
                self.collection.create_index([("$**", "text")])
            except Exception as e:
                if 'IndexOptionsConflict' not in str(e):
                    raise e

            # Case ID index with both formats
            self.collection.create_index([("case_id", ASCENDING)], unique=True)

            # Additional indexes for common queries
            self.collection.create_index([("date", DESCENDING)])
            self.collection.create_index([("species", ASCENDING)])
            self.collection.create_index([("diagnosis", ASCENDING)])

            # Indexes for analysis cache
            self.analysis_cache.create_index([("analysis_type", ASCENDING)])
            self.analysis_cache.create_index([("timestamp", DESCENDING)], expireAfterSeconds=3600)  # Cache expires after 1 hour

            logger.info("All indexes created or already exist")
        except PyMongoError as e:
            logger.warning(
                f"Index setup deferred — MongoDB not reachable at "
                f"import time ({type(e).__name__}: {str(e)[:120]}). "
                f"Indexes will be re-attempted on first query."
            )

    def get_case(self, case_id: str) -> Optional[Case]:
        """Retrieve a single case by ID"""
        try:
            result = self.collection.find_one({"case_id": case_id})
            return Case(**result) if result else None
        except PyMongoError as e:
            logger.error(f"Error retrieving case {case_id}: {str(e)}")
            raise

    def get_file_content(self, filename: str) -> Optional[Dict]:
        """Retrieve file content from filestore"""
        try:
            return self.filestore.find_one({"filename": filename})
        except PyMongoError as e:
            logger.error(f"Error retrieving file {filename}: {str(e)}")
            raise

    def execute_aggregation(self, pipeline: List[Dict]) -> List[Dict]:
        """Execute a MongoDB aggregation pipeline"""
        try:
            return list(self.collection.aggregate(pipeline))
        except PyMongoError as e:
            logger.error(f"Aggregation pipeline error: {str(e)}")
            raise

    def find_cases(self, 
                  query: Dict, 
                  projection: Optional[Dict] = None, 
                  sort: Optional[List] = None, 
                  limit: Optional[int] = None,
                  offset: Optional[int] = 0) -> List[Case]:
        """Find cases matching query criteria"""
        try:
            cursor = self.collection.find(query, projection)
            if sort:
                cursor = cursor.sort(sort)
            if offset:
                cursor = cursor.skip(offset)
            if limit:
                cursor = cursor.limit(limit)
            return [Case(**doc) for doc in cursor]
        except PyMongoError as e:
            logger.error(f"Error finding cases: {str(e)}")
            raise

    def cache_analysis(self, analysis_type: str, results: Dict[str, Any]) -> None:
        """Cache analysis results"""
        try:
            self.analysis_cache.insert_one({
                "analysis_type": analysis_type,
                "timestamp": datetime.now(),
                "results": results
            })
        except PyMongoError as e:
            logger.error(f"Error caching analysis results: {str(e)}")
            # Don't raise - caching errors shouldn't break the application

    def get_cached_analysis(self, analysis_type: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached analysis results"""
        try:
            result = self.analysis_cache.find_one(
                {"analysis_type": analysis_type},
                sort=[("timestamp", DESCENDING)]
            )
            return result["results"] if result else None
        except PyMongoError as e:
            logger.error(f"Error retrieving cached analysis: {str(e)}")
            return None

# Initialize global storage instance
case_storage = CaseStorage()
