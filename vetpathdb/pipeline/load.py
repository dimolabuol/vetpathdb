import os
import json
import argparse
from datetime import datetime
from pymongo import MongoClient
from colorama import Fore, Style, init
import time

init(autoreset=True)

from vetpathdb.pipeline._utils import (
    print_info, print_success, print_error, print_debug, get_timestamp,
    is_valid_case_id,
)
from vetpathdb.prompts.loader import list_schemas
from vetpathdb.config import AIConfig

_AI_CONFIG = AIConfig()


def _registered_case_types() -> list[str]:
    """Return the uppercase codes of every schema registered under prompts/schemas/."""
    return sorted({s['code'].upper() for s in list_schemas() if s.get('code')})


def _case_type_query(case_type: str) -> dict:
    """Build a Mongo filter matching the top-level ``case_type`` field, with
    a fallback to the legacy ``-{TYPE}-`` infix in ``source_file`` for
    documents predating the migration.

    The fallback only applies when ``case_type`` is absent on a document —
    if a doc has ``case_type`` set, that value wins over the filename infix.
    Otherwise a mismatched filename (e.g. extraction was re-run under a
    different schema but the old filename remained) would double-count.
    """
    code = case_type.upper()
    return {
        '$or': [
            {'case_type': code},
            {
                'case_type': {'$exists': False},
                'source_file': {'$regex': f'-{code}-'},
            },
        ]
    }

class ProgressTracker:
    def __init__(self, total_files):
        self.total_files = total_files
        self.processed_files = 0
        self.successful_files = 0
        self.error_files = 0
        self.start_time = time.time()
        self.last_update_time = 0
        self.update_interval = 5  # Status update every 5 seconds

    def update(self, success=True, debug_mode=False):
        self.processed_files += 1
        if success:
            self.successful_files += 1
        else:
            self.error_files += 1

        current_time = time.time()
        if current_time - self.last_update_time >= self.update_interval:
            self.print_status(debug_mode)
            self.last_update_time = current_time

    def print_status(self, debug_mode=False):
        elapsed_time = time.time() - self.start_time
        progress_percent = (self.processed_files / self.total_files * 100) if self.total_files > 0 else 0
        
        print_info("\n=== Progress Update ===", debug=False, debug_mode=debug_mode)
        print_info(f"Progress: {self.processed_files}/{self.total_files} files ({progress_percent:.1f}%)", 
                  debug=False, debug_mode=debug_mode)
        print_info(f"Successfully processed: {self.successful_files} files", debug=False, debug_mode=debug_mode)
        print_info(f"Errors encountered: {self.error_files} files", debug=False, debug_mode=debug_mode)
        print_info(f"Time elapsed: {elapsed_time:.1f}s", debug=False, debug_mode=debug_mode)
        print_info("=====================\n", debug=False, debug_mode=debug_mode)

def process_text_file(file_path, mongodb_client, debug_mode=False, extra_text=False, dir_case_id=None):
    try:
        # Read the text file content
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract filename
        filename = os.path.basename(file_path)
        
        if extra_text:
            # Add 'extra-' prefix to filename when storing in filestore
            stored_filename = 'extra-' + filename
        else:
            stored_filename = filename
        
        # Use provided dir_case_id
        if not dir_case_id:
            dir_case_id = os.path.basename(os.path.dirname(file_path))
        
        # Validate case ID format
        if not is_valid_case_id(dir_case_id):
            print_error(f"Invalid case ID format in directory name: {dir_case_id}",
                        debug=False, debug_mode=debug_mode)
            return False
        
        # Store in filestore collection
        db = mongodb_client[_AI_CONFIG.mongo_db]
        filestore = db[_AI_CONFIG.collection_filestore]
        
        # Create document with file metadata and content
        file_doc = {
            'filename': stored_filename,
            'original_filename': filename,
            'dir_case_id': dir_case_id,
            'content': content,
            'uploaded_at': datetime.now(),
            'source_path': file_path
        }
        
        # Use filename as unique identifier to avoid duplicates
        result = filestore.update_one(
            {'filename': stored_filename},
            {'$set': file_doc},
            upsert=True
        )
        
        if result.modified_count > 0:
            print_success(f"Updated file {stored_filename} in filestore", debug=False, debug_mode=debug_mode)
        elif result.upserted_id:
            print_success(f"Inserted file {stored_filename} to filestore", debug=False, debug_mode=debug_mode)
        
        # Update the case document in processed_cases collection
        collection = db[_AI_CONFIG.collection_cases]
        
        # Determine the field to update
        if extra_text:
            update_field = 'data.report_metadata.extra_filenames'
            filename_to_store = filename  # Without 'extra-' prefix
        else:
            update_field = 'data.report_metadata.filenames'
            filename_to_store = filename
        
        # Update the case document
        # Use $addToSet to avoid duplicate entries
        result = collection.update_one(
            {'case_id': dir_case_id},
            {'$addToSet': {update_field: filename_to_store}}
        )
        
        if result.modified_count > 0:
            print_success(f"Updated case {dir_case_id} with {filename_to_store}", debug=False, debug_mode=debug_mode)
        else:
            print_info(f"No changes made to case {dir_case_id} (may already have {filename_to_store})", debug=True, debug_mode=debug_mode)
        
        return True
        
    except Exception as e:
        print_error(f"Error processing text file {file_path}: {e}", debug=False, debug_mode=debug_mode)
        return False

def process_json_file(file_path, mongodb_client, debug_mode=False, case_type=None):
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        # Extract case_id and type from filename (format: case_id-type-model.json)
        filename = os.path.basename(file_path)
        parts = filename.split('-')
        if len(parts) < 2:
            print_error(f"Invalid filename format: {filename}", debug=False, debug_mode=debug_mode)
            return False
            
        # Case ID is the leading dash-delimited component of the filename;
        # the next component is the case-type code.
        case_id = parts[0]
        file_case_type = parts[1]
        
        # Skip if case type doesn't match requested type
        if case_type and file_case_type != case_type:
            print_debug(f"Skipping {filename} - case type {file_case_type} doesn't match requested type {case_type}", 
                       debug_mode=debug_mode)
            return True
        
        db = mongodb_client[_AI_CONFIG.mongo_db]
        collection = db[_AI_CONFIG.collection_cases]
        
        # First check if document exists and has file_contents
        existing_doc = collection.find_one({'case_id': case_id})
        
        # Prepare the update operations
        update_ops = {
            '$set': {
                'processed_at': datetime.now(),
                'source_file': file_path
            }
        }

        # Determine canonical case_type. Prefer the value the LLM put in
        # data.report_metadata.report_type; fall back to the filename infix
        # for legacy JSONs that predate the schema change.
        canonical_type = (
            ((data.get('report_metadata') or {}).get('report_type') or '')
            .strip()
            .upper()
        )
        if not canonical_type and file_case_type:
            canonical_type = file_case_type.upper()
        if canonical_type:
            update_ops['$set']['case_type'] = canonical_type

        # Handle all fields from the JSON file
        for key, value in data.items():
            if key == 'report_metadata':
                # Special handling for report_metadata
                if 'file_contents' in value:
                    # Skip file_contents from JSON to preserve existing text data
                    metadata = value.copy()
                    del metadata['file_contents']
                    for meta_key, meta_value in metadata.items():
                        if meta_key != 'file_contents':
                            update_ops['$set'][f'data.report_metadata.{meta_key}'] = meta_value
                else:
                    # For other metadata fields, preserve any existing file_contents
                    for meta_key, meta_value in value.items():
                        if meta_key != 'file_contents':
                            update_ops['$set'][f'data.report_metadata.{meta_key}'] = meta_value
            else:
                # For all other fields, update normally under the data object
                update_ops['$set'][f'data.{key}'] = value
        
        # Perform the update
        result = collection.update_one(
            {'case_id': case_id},
            update_ops,
            upsert=True
        )
        
        if result.modified_count > 0:
            print_success(f"Updated existing record for case {case_id}", debug=False, debug_mode=debug_mode)
        elif result.upserted_id:
            print_success(f"Inserted new record for case {case_id}", debug=False, debug_mode=debug_mode)
        else:
            print_info(f"No changes needed for case {case_id}", debug=True, debug_mode=debug_mode)
            
        return True
        
    except json.JSONDecodeError as e:
        print_error(f"Invalid JSON in file {file_path}: {e}", debug=False, debug_mode=debug_mode)
        return False
    except Exception as e:
        print_error(f"Error processing file {file_path}: {e}", debug=False, debug_mode=debug_mode)
        return False


def get_existing_case_ids(mongodb_client, case_type=None):
    """Get set of existing case IDs, optionally filtered by type"""
    db = mongodb_client[_AI_CONFIG.mongo_db]
    collection = db[_AI_CONFIG.collection_cases]
    
    # Prepare query
    query = {}
    if case_type:
        query.update(_case_type_query(case_type))
    
    # Get cases and return their IDs as a set
    return {case['case_id'] for case in collection.find(query, {'case_id': 1})}

def list_cases(mongodb_client, case_type=None, debug_mode=False, sort_by='name', reverse=False):
    """List all case IDs, optionally filtered by type"""
    db = mongodb_client[_AI_CONFIG.mongo_db]
    collection = db[_AI_CONFIG.collection_cases]
    
    # Prepare query
    query = {}
    if case_type:
        query.update(_case_type_query(case_type))
    
    # Get all cases
    cases = list(collection.find(query))
    
    # Calculate sizes for all cases
    for case in cases:
        case['_size'] = len(str(case).encode('utf-8'))
        case['_created'] = case['_id'].generation_time  # Extract creation time from ObjectId
    
    # Sort based on criteria
    if sort_by == 'size':
        cases.sort(key=lambda x: x['_size'], reverse=reverse)
    elif sort_by == 'date':
        cases.sort(key=lambda x: x['_created'], reverse=reverse)
    else:  # sort by name/case_id
        cases.sort(key=lambda x: x['case_id'], reverse=reverse)
    
    # Print results
    print_info("\n=== Case IDs ===", debug=False, debug_mode=debug_mode)
    count = 0
    total_size = 0
    
    for case in cases:
        count += 1
        # Calculate BSON size of this document
        case_size = len(str(case).encode('utf-8'))
        total_size += case_size
        
        # Determine case type: prefer the canonical top-level field, fall
        # back to parsing the legacy source_file infix.
        case_type_str = ""
        resolved_type = case.get('case_type')
        if not resolved_type and 'source_file' in case:
            for t in _registered_case_types():
                if f'-{t}-' in case['source_file']:
                    resolved_type = t
                    break
        if resolved_type:
            case_type_str = f" ({resolved_type})"
        
        size_str = f"{case_size / 1024:.1f} KB"
        print_info(f"{case['case_id']}{case_type_str} - {size_str}", debug=False, debug_mode=debug_mode)
    
    print_info(f"\nTotal cases: {count}", debug=False, debug_mode=debug_mode)
    print_info(f"Total size: {total_size / (1024*1024):.2f} MB", debug=False, debug_mode=debug_mode)
    print_info("===============\n", debug=False, debug_mode=debug_mode)

def list_files(mongodb_client, debug_mode=False, sort_by='name', reverse=False):
    """List all files in the filestore collection"""
    db = mongodb_client[_AI_CONFIG.mongo_db]
    filestore = db[_AI_CONFIG.collection_filestore]
    
    # Get all files
    files = list(filestore.find())
    
    # Calculate sizes and add creation time
    for file in files:
        file['_size'] = len(str(file).encode('utf-8'))
        file['_content_size'] = len(file.get('content', '').encode('utf-8'))
        file['_created'] = file['_id'].generation_time  # Extract creation time from ObjectId
    
    # Sort based on criteria
    if sort_by == 'size':
        files.sort(key=lambda x: x['_size'], reverse=reverse)
    elif sort_by == 'date':
        files.sort(key=lambda x: x['_created'], reverse=reverse)
    else:  # sort by filename
        files.sort(key=lambda x: x['filename'], reverse=reverse)
    
    # Print results
    print_info("\n=== Files in Database ===", debug=False, debug_mode=debug_mode)
    count = 0
    total_size = 0
    
    for file in files:
        count += 1
        # Calculate size of this document
        file_size = len(str(file).encode('utf-8'))
        content_size = len(file.get('content', '').encode('utf-8'))
        total_size += file_size
        
        size_str = f"{file_size / 1024:.1f} KB"
        content_str = f"{content_size / 1024:.1f} KB content"
        print_info(f"{file['filename']} (Case: {file['dir_case_id']}) - {size_str} ({content_str})", 
                  debug=False, debug_mode=debug_mode)
    
    print_info(f"\nTotal files: {count}", debug=False, debug_mode=debug_mode)
    print_info(f"Total size: {total_size / (1024*1024):.2f} MB", debug=False, debug_mode=debug_mode)
    print_info("=====================\n", debug=False, debug_mode=debug_mode)

def dump_file(mongodb_client, filename, debug_mode=False):
    """Dump content of a specific file"""
    db = mongodb_client[_AI_CONFIG.mongo_db]
    filestore = db[_AI_CONFIG.collection_filestore]
    
    file_doc = filestore.find_one({'filename': filename})
    if not file_doc:
        print_error(f"File {filename} not found", debug=False, debug_mode=debug_mode)
        return
    
    print_info(f"\n=== File: {filename} ===", debug=False, debug_mode=debug_mode)
    print_info(f"Case ID: {file_doc['dir_case_id']}", debug=False, debug_mode=debug_mode)
    print_info(f"Uploaded: {file_doc['uploaded_at']}", debug=False, debug_mode=debug_mode)
    print_info(f"Source: {file_doc['source_path']}", debug=False, debug_mode=debug_mode)
    print_info("\nContent:", debug=False, debug_mode=debug_mode)
    print(file_doc['content'])
    print_info("\n==================\n", debug=False, debug_mode=debug_mode)

def dump_case(mongodb_client, case_id, debug_mode=False):
    """Dump all data for a specific case"""
    db = mongodb_client[_AI_CONFIG.mongo_db]
    collection = db[_AI_CONFIG.collection_cases]
    
    case = collection.find_one({'case_id': case_id})
    if not case:
        print_error(f"Case {case_id} not found", debug=False, debug_mode=debug_mode)
        return
    
    def json_serial(obj):
        """JSON serializer for objects not serializable by default json code"""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")
    
    # Convert ObjectId to string for JSON serialization
    case['_id'] = str(case['_id'])
    
    # Pretty print the case data with custom serializer
    print(json.dumps(case, indent=2, default=json_serial))

def get_database_stats(mongodb_client, debug_mode=False):
    """Get statistics about the cases in the database"""
    db = mongodb_client[_AI_CONFIG.mongo_db]
    collection = db[_AI_CONFIG.collection_cases]

    # Get total count
    total_cases = collection.count_documents({})

    # Get counts per type, using whatever schemas are currently registered.
    type_counts = {
        case_type: collection.count_documents(_case_type_query(case_type))
        for case_type in _registered_case_types()
    }
    
    # Calculate total size
    total_size = db.command('collStats', _AI_CONFIG.collection_cases)['size']
    storage_size = db.command('collStats', _AI_CONFIG.collection_cases)['storageSize']
    
    # Print statistics
    print_info("\n=== Database Statistics ===", debug=False, debug_mode=debug_mode)
    print_info(f"Total cases: {total_cases}", debug=False, debug_mode=debug_mode)
    print_info("\nCases by type:", debug=False, debug_mode=debug_mode)
    for case_type, count in type_counts.items():
        print_info(f"  {case_type}: {count} cases", debug=False, debug_mode=debug_mode)
    print_info(f"\nDatabase size: {total_size / (1024*1024):.2f} MB", debug=False, debug_mode=debug_mode)
    print_info(f"Storage size: {storage_size / (1024*1024):.2f} MB", debug=False, debug_mode=debug_mode)
    print_info("=======================\n", debug=False, debug_mode=debug_mode)

def _strip_type_suffix(case_id: str) -> str:
    """Strip any '-TYPE-...' suffix that legacy stored IDs may carry.

    Database case_ids for files processed by older pipelines sometimes look
    like ``12345-SP-demo`` instead of the bare ``12345``. The suffix takes
    the form ``-<2or3 letter code>-<anything>``.
    """
    import re
    return re.sub(r'-[A-Z]{2,3}-.*$', '', str(case_id))


# Override the _utils helper so purge_invalid_cases still accepts the
# legacy combined form (e.g. ``12345-SP-demo``). We validate the bare ID
# after stripping the trailing type suffix.
def _is_valid_stored_case_id(case_id) -> bool:
    return is_valid_case_id(_strip_type_suffix(case_id))

def purge_invalid_cases(mongodb_client, debug_mode=False):
    """Remove cases with invalid case IDs from the database"""
    db = mongodb_client[_AI_CONFIG.mongo_db]
    collection = db[_AI_CONFIG.collection_cases]
    
    # Get all cases
    cases = list(collection.find({}, {'case_id': 1}))
    
    invalid_cases = []
    for case in cases:
        if not _is_valid_stored_case_id(case['case_id']):
            invalid_cases.append(case['case_id'])
    
    if not invalid_cases:
        print_info("No invalid cases found", debug=False, debug_mode=debug_mode)
        return
    
    # Print invalid cases that will be removed
    print_info("\nFound invalid case IDs:", debug=False, debug_mode=debug_mode)
    for case_id in invalid_cases:
        print_info(f"  {case_id}", debug=False, debug_mode=debug_mode)
    
    # Remove invalid cases
    result = collection.delete_many({'case_id': {'$in': invalid_cases}})
    print_success(f"\nPurged {result.deleted_count} invalid cases from database", 
                 debug=False, debug_mode=debug_mode)

def clean_file_data(mongodb_client, case_type=None, case_id=None, debug_mode=False):
    """Remove old file data structure from cases"""
    db = mongodb_client[_AI_CONFIG.mongo_db]
    collection = db[_AI_CONFIG.collection_cases]
    
    # Prepare query based on parameters
    query = {}
    if case_id:
        query['case_id'] = case_id
        print_info(f"Cleaning file data for specific case: {case_id}", debug=False, debug_mode=debug_mode)
    elif case_type:
        query.update(_case_type_query(case_type))
        print_info(f"Cleaning file data for all cases of type: {case_type}", debug=False, debug_mode=debug_mode)
    else:
        print_info("Cleaning file data for all cases", debug=False, debug_mode=debug_mode)
    
    # First find all matching cases to show what will be affected
    matching_cases = list(collection.find(query, {'case_id': 1, 'data.report_metadata.file_contents': 1}))
    cases_with_contents = sum(1 for case in matching_cases 
                            if case.get('data', {}).get('report_metadata', {}).get('file_contents'))
    
    print_info(f"\nFound {len(matching_cases)} matching cases", debug=False, debug_mode=debug_mode)
    print_info(f"Of these, {cases_with_contents} cases have file_contents to clean", 
              debug=False, debug_mode=debug_mode)
    
    if debug_mode:
        for case in matching_cases:
            has_contents = bool(case.get('data', {}).get('report_metadata', {}).get('file_contents'))
            print_debug(f"Case {case['case_id']}: {'has' if has_contents else 'no'} file_contents")
    
    # Update to remove file_contents from report_metadata
    update = {
        '$unset': {
            'data.report_metadata.file_contents': "",
            'data.report_metadata.filenames': ""
        }
    }
    
    result = collection.update_many(query, update)
    print_success(f"\nCleaned file data from {result.modified_count} cases", 
                 debug=False, debug_mode=debug_mode)

def wipe_cases(mongodb_client, case_type=None, case_id=None, debug_mode=False):
    """Wipe cases from database based on type or specific case ID"""
    db = mongodb_client[_AI_CONFIG.mongo_db]
    collection = db[_AI_CONFIG.collection_cases]
    
    if case_id:
        # Delete specific case
        result = collection.delete_one({'case_id': case_id})
        if result.deleted_count > 0:
            print_success(f"Deleted case {case_id}", debug=False, debug_mode=debug_mode)
        else:
            print_error(f"Case {case_id} not found", debug=False, debug_mode=debug_mode)
    elif case_type:
        # Delete all cases of specific type
        # Find cases where filename contains -TYPE- pattern
        result = collection.delete_many({'source_file': {'$regex': f'-{case_type}-'}})
        print_success(f"Deleted {result.deleted_count} cases of type {case_type}", 
                     debug=False, debug_mode=debug_mode)
    else:
        # Delete all cases
        result = collection.delete_many({})
        print_success(f"Deleted all {result.deleted_count} cases from database", 
                     debug=False, debug_mode=debug_mode)

def main(base_dir, debug_mode=False, process_text=False, extra_text_files=False, case_type=None, wipe=False, wipe_case_id=None,
         show_stats=False, dump_case_id=None, list_cases_flag=False, incremental=False, clean_files=False,
         list_files_flag=False, dump_filename=None, sort_by='name', sort_reverse=False, purge_invalid=False):
    try:
        # Connect to MongoDB
        mongodb_client = MongoClient(os.getenv('MONGODB_URI', 'mongodb://localhost:27017/'))
        mongodb_client.server_info()  # Test connection
        print_info("Successfully connected to MongoDB", debug=False, debug_mode=debug_mode)
        
        # Handle special operations
        if show_stats:
            get_database_stats(mongodb_client, debug_mode)
            return
        elif list_cases_flag:
            list_cases(mongodb_client, case_type, debug_mode, sort_by=sort_by, reverse=sort_reverse)
            return
        elif dump_case_id:
            dump_case(mongodb_client, dump_case_id, debug_mode)
            return
        elif list_files_flag:
            list_files(mongodb_client, debug_mode, sort_by=sort_by, reverse=sort_reverse)
            return
        elif dump_filename:
            dump_file(mongodb_client, dump_filename, debug_mode)
            return
        elif purge_invalid:
            purge_invalid_cases(mongodb_client, debug_mode)
            return
        elif clean_files:
            clean_file_data(mongodb_client, case_type, wipe_case_id, debug_mode)
            return
        elif wipe or wipe_case_id:
            wipe_cases(mongodb_client, case_type, wipe_case_id, debug_mode)
            return
            
        if process_text:
            file_type = "text"
        elif extra_text_files:
            file_type = "extra text"
        else:
            file_type = "JSON"
        print_info(f"Starting database update for {file_type} files from directory: {base_dir}",
                  debug=False, debug_mode=debug_mode)
        
        # Get existing case IDs if in incremental mode
        existing_case_ids = get_existing_case_ids(mongodb_client, case_type) if incremental else set()
        if incremental:
            print_info(f"Found {len(existing_case_ids)} existing cases in database", debug=False, debug_mode=debug_mode)

        # Find all files of the appropriate type
        files_to_process = []
        for root, _, files in os.walk(base_dir):
            for file in files:
                # Check if in 'extra' directory when processing extra text files
                path_parts = os.path.normpath(root).split(os.sep)
                is_in_extra_dir = 'extra' in path_parts
                
                if extra_text_files and not is_in_extra_dir:
                    continue  # Skip files not in 'extra' directories
                if not extra_text_files and is_in_extra_dir:
                    continue  # Skip files in 'extra' directories when not processing extra text files
                
                # Extract case ID from directory path - it's the directory above 'extra'
                if is_in_extra_dir:
                    extra_idx = path_parts.index('extra')
                    if extra_idx > 0:  # Make sure there's a parent directory
                        dir_case_id = path_parts[extra_idx - 1]
                    else:
                        continue  # Skip if no parent directory found
                else:
                    dir_case_id = os.path.basename(os.path.dirname(os.path.join(root, file)))
                
                # Skip if case already exists in incremental mode
                if incremental and dir_case_id in existing_case_ids:
                    print_debug(f"Skipping existing case {dir_case_id}", debug_mode=debug_mode)
                    continue
            
                if process_text or extra_text_files:
                    if file.endswith('.txt') or file.endswith('.md'):
                        files_to_process.append((os.path.join(root, file), dir_case_id))
                else:
                    if file.endswith('.json') and not file.endswith('.malformed'):
                        files_to_process.append((os.path.join(root, file), dir_case_id))
        
        total_files = len(files_to_process)
        if process_text:
            file_type = "text"
        elif extra_text_files:
            file_type = "extra text"
        else:
            file_type = "JSON"
        print_info(f"Found {total_files} {file_type} files to process", debug=False, debug_mode=debug_mode)
        
        if total_files == 0:
            print_info(f"No {file_type} files found. Exiting.", debug=False, debug_mode=debug_mode)
            return
        
        # Initialize progress tracker
        progress = ProgressTracker(total_files)
        
        # Process each file
        for file_path_tuple in files_to_process:
            file_path, dir_case_id = file_path_tuple
            print_debug(f"Processing file: {file_path}", debug_mode=debug_mode)
            if process_text or extra_text_files:
                success = process_text_file(file_path, mongodb_client, debug_mode, extra_text=extra_text_files, dir_case_id=dir_case_id)
            else:
                success = process_json_file(file_path, mongodb_client, debug_mode, case_type)
            progress.update(success, debug_mode)
        
        # Final status update
        progress.print_status(debug_mode)
        
    except Exception as e:
        print_error(f"Fatal error: {e}", debug=False, debug_mode=debug_mode)
        return

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Update MongoDB with processed files and manage database content.')
    parser.add_argument('--base-dir', type=str,
                      help='Path to the base directory containing JSON files')
    parser.add_argument('--debug', action='store_true', 
                      help='Enable debug mode with more detailed output')
    parser.add_argument('--text-files', action='store_true',
                      help='Process text files instead of JSON files')
    parser.add_argument('--extra-text-files', action='store_true',
                      help='Process extra text files from extra directories')
    parser.add_argument('--case-type', type=lambda s: s.upper(),
                      help='Process only cases of the specified type. Valid codes are whichever schemas are registered under vetpathdb/prompts/schemas/ (see --help output for the active list).')
    parser.add_argument('--wipe', action='store_true',
                      help='Wipe cases from database (all cases if no type specified)')
    parser.add_argument('--wipe-case-id', type=str,
                      help='Wipe specific case ID from database')
    parser.add_argument('--stats', action='store_true',
                      help='Show database statistics')
    parser.add_argument('--dump-case', type=str,
                      help='Dump all data for a specific case ID')
    parser.add_argument('--list', action='store_true',
                      help='List all case IDs in database')
    parser.add_argument('--incremental', action='store_true',
                      help='Only process cases not already in database')
    
    parser.add_argument('--clean-files', action='store_true',
                      help='Clean old file data structure from cases')
    parser.add_argument('--list-files', action='store_true',
                      help='List all files in the filestore collection')
    parser.add_argument('--dump-file', type=str,
                      help='Dump content of a specific file')
    parser.add_argument('--purge-invalid', action='store_true',
                      help='Remove cases with invalid case IDs from database')
    parser.add_argument('--sort', type=str, choices=['size', 'date', 'name'],
                      default='name', help='Sort results by size, date, or name')
    parser.add_argument('--reverse', action='store_true',
                      help='Reverse the sort order')
    
    args = parser.parse_args()
    
    # Validate arguments
    query_only_ops = (args.wipe or args.wipe_case_id or args.stats or args.list or 
                     args.dump_case or args.list_files or args.dump_file or 
                     args.clean_files or args.purge_invalid)
    
    if query_only_ops:
        # For database query operations, base-dir is not required
        if args.base_dir:
            parser.error("--base-dir should not be specified with query-only operations")
    elif not args.base_dir:
        # For file processing operations, base-dir is required
        parser.error("--base-dir is required for processing files")

    if args.case_type:
        registered = _registered_case_types()
        if args.case_type not in registered:
            parser.error(
                f"--case-type {args.case_type!r} is not a registered schema code. "
                f"Known codes: {', '.join(registered) or '(none)'}"
            )
    
    main(args.base_dir, args.debug, args.text_files, args.extra_text_files, args.case_type, args.wipe, args.wipe_case_id,
         args.stats, args.dump_case, args.list, args.incremental, args.clean_files,
         args.list_files, args.dump_file, args.sort, args.reverse, args.purge_invalid)
