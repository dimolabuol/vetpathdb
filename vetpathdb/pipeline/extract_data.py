import os
import sys
import json
import asyncio
import time
import subprocess
import tempfile
from collections import defaultdict
from pymongo import MongoClient
from datetime import datetime, timedelta
import argparse
import aiohttp
from colorama import Fore, Style, init

init(autoreset=True)

class ProgressTracker:
    def __init__(self, total_cases, malformed_cases=0, completed_cases=0, errored_cases=0):
        self.total_cases = total_cases
        self.malformed_cases = malformed_cases
        self.completed_cases = completed_cases
        self.errored_cases = errored_cases
        self.processed_cases = 0
        self.successful_cases = 0  # Track successfully processed cases separately
        self.start_time = time.time()
        self.total_tokens = 0
        self.total_processing_time = 0
        self.last_update_time = 0
        self.update_interval = 30  # Status update every 30 seconds
        self.processing_times = []  # Store last N processing times for better averaging
        self.max_times_stored = 100  # Keep last 100 processing times
        self.window_start_time = time.time()  # For calculating aggregate throughput
        self.window_tokens = 0  # Tokens processed in current window

    def update(self, tokens=0, processing_time=0, debug_mode=False, success=True):
        self.processed_cases += 1
        if success:
            self.successful_cases += 1
            self.total_tokens += tokens
            self.total_processing_time += processing_time
            self.window_tokens += tokens
            
            # Only track processing times for successful cases
            self.processing_times.append(processing_time)
            if len(self.processing_times) > self.max_times_stored:
                self.processing_times.pop(0)
        
        current_time = time.time()
        if current_time - self.last_update_time >= self.update_interval:
            self.print_status(debug_mode)
            self.last_update_time = current_time

    def print_status(self, debug_mode=False):
        elapsed_time = time.time() - self.start_time
        
        # Calculate averages using recent processing times for better accuracy
        recent_avg_time = sum(self.processing_times) / len(self.processing_times) if self.processing_times else 0
        # Calculate both sequential and aggregate tokens/second
        sequential_tokens_per_second = self.total_tokens / self.total_processing_time if self.total_processing_time > 0 else 0
        
        # Calculate aggregate throughput over the window period
        window_elapsed = time.time() - self.window_start_time
        aggregate_tokens_per_second = self.window_tokens / window_elapsed if window_elapsed > 0 else 0
        
        # Use recent average time for estimates, considering only remaining cases that need successful processing
        remaining_cases = self.total_cases - (self.successful_cases + self.completed_cases + self.malformed_cases)
        estimated_remaining_seconds = remaining_cases * recent_avg_time if recent_avg_time > 0 else 0
        estimated_completion = datetime.now() + timedelta(seconds=estimated_remaining_seconds)
        
        # Format time remaining
        days = int(estimated_remaining_seconds // (24 * 3600))
        hours = int((estimated_remaining_seconds % (24 * 3600)) // 3600)
        minutes = int((estimated_remaining_seconds % 3600) // 60)
        
        time_remaining = ""
        if days > 0:
            time_remaining += f"{days}d "
        if hours > 0 or days > 0:
            time_remaining += f"{hours}h "
        time_remaining += f"{minutes}m"

        # Print status update
        print_info("\n=== Progress Update ===", debug=False, debug_mode=debug_mode)
        print_info(f"Previously completed: {self.completed_cases} cases", debug=False, debug_mode=debug_mode)
        print_info(f"Previously malformed: {self.malformed_cases} cases", debug=False, debug_mode=debug_mode)
        print_info(f"Errored cases: {self.errored_cases} cases", debug=False, debug_mode=debug_mode)
        print_info(f"Progress: {self.processed_cases}/{self.total_cases} cases ({(self.processed_cases/self.total_cases*100):.1f}%)", 
                  debug=False, debug_mode=debug_mode)
        print_info(f"Recent average time per case: {recent_avg_time:.1f}s", debug=False, debug_mode=debug_mode)
        print_info(f"Total tokens processed: {self.total_tokens:,}", debug=False, debug_mode=debug_mode)
        print_info(f"Sequential processing speed: {sequential_tokens_per_second:.1f} tokens/s", debug=False, debug_mode=debug_mode)
        print_info(f"Aggregate throughput: {aggregate_tokens_per_second:.1f} tokens/s", debug=False, debug_mode=debug_mode)
        print_info(f"Estimated time remaining: {time_remaining}", debug=False, debug_mode=debug_mode)
        print_info(f"Expected completion: {estimated_completion.strftime('%Y-%m-%d %H:%M:%S')}", 
                  debug=False, debug_mode=debug_mode)
        print_info("=====================\n", debug=False, debug_mode=debug_mode)

from vetpathdb.pipeline._utils import (
    print_info, print_success, print_error, print_debug, get_timestamp,
    extract_case_id_from_name_or_path, detect_case_id_format,
)
from vetpathdb.prompts.loader import list_schemas, render_prompt
from vetpathdb.config import AIConfig

_AI_CONFIG = AIConfig()

async def process_case(semaphore, session, case_id, txt_files, model_name, endpoint, prompt_templates,
                       progress_tracker, debug_mode=False, payload_debug=False, mongodb_client=None,
                       enrich_mode=False, enrich_template=None):
    async with semaphore:
        safe_model_name = model_name.replace("/", "_").replace(":", "_")
        
        # Detect case-level report type
        case_report_type = detect_case_report_type(txt_files, debug_mode=debug_mode)
        
        print_info(f"[{case_id}] Processing case ID: {case_id}", debug=False, debug_mode=debug_mode)
        file_list_str = ", ".join([os.path.basename(f) for f in txt_files])
        print_info(f"[{case_id}] Files for this case: {file_list_str}", debug=False, debug_mode=debug_mode)

        if not case_report_type:
            print_error(f"[{case_id}] No report type could be determined for case", 
                       debug=False, debug_mode=debug_mode)
            progress_tracker.errored_cases += 1
            return 0, 0, "error"

        # In enrichment mode, use enrichment template regardless of case type
        if enrich_mode:
            if not enrich_template:
                print_error(f"[{case_id}] No enrichment template provided", 
                          debug=False, debug_mode=debug_mode)
                progress_tracker.errored_cases += 1
                return 0, 0, "error"
        else:
            # Normal mode - validate template availability
            if case_report_type not in prompt_templates:
                print_error(f"[{case_id}] No template available for report type {case_report_type}", 
                           debug=False, debug_mode=debug_mode)
                progress_tracker.errored_cases += 1
                return 0, 0, "error"

        print_info(f"[{case_id}] Case determined to be type: {case_report_type}", 
                  debug=False, debug_mode=debug_mode)

        # Use case report type for filename — same shape for every
        # configured case-ID format.
        primary_report_type = case_report_type
        suffix = ".enriched-json" if enrich_mode else ".json"
        json_path = os.path.join(
            os.path.dirname(txt_files[0]),
            f"{case_id}-{primary_report_type}-{safe_model_name}{suffix}",
        )

        # Combine all file contents
        combined_content = ""
        for txt_path in txt_files:
            file_name = os.path.basename(txt_path)
            with open(txt_path, "r") as txt_file:
                file_content = txt_file.read()
            combined_content += f"Filename: {file_name}\nContent:\n{file_content}\n\n"

        prompt_template = enrich_template if enrich_mode else prompt_templates[case_report_type]

        prompt = f"{prompt_template}\n\n{combined_content}"

        messages = [
            {"role": "system", "content": "You are an expert data extractor."},
            {"role": "user", "content": prompt}
        ]

        if payload_debug:
            print_info(f"[{case_id}] Full LLM payload:", debug=False, debug_mode=debug_mode)
            payload_to_print = {
                "model": model_name,
                "messages": messages,
                "temperature": 0,
                "stream": False
            }
            print_info(json.dumps(payload_to_print, indent=2), debug=False, debug_mode=debug_mode)

        input_size = len(prompt)
        print_info(f"[{case_id}] Sending request to LLM with total input size: {input_size} chars.",
                   debug=False, debug_mode=debug_mode)

        start_time = time.time()

        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": 0,
            "stream": False
        }

        try:
            async with session.post(endpoint, json=payload) as resp:
                if resp.status == 200:
                    response_json = await resp.json()
                    end_time = time.time()
                    time_taken = end_time - start_time
                    usage = response_json.get("usage", {})
                    total_tokens = usage.get("total_tokens", 0)

                    print_info(f"[{case_id}] Case processed successfully.", debug=False, debug_mode=debug_mode)
                    print_debug(f"[{case_id}] Time taken: {time_taken:.2f}s, Total tokens: {total_tokens}, Tokens/s: {total_tokens / time_taken if time_taken else 0:.2f}", debug_mode=debug_mode)

                    full_output = response_json["choices"][0]["message"]["content"]

                    is_valid_json = await save_response_output(full_output, json_path, debug_mode=debug_mode, 
                                                             case_id=case_id, mongodb_client=mongodb_client)
                    if is_valid_json:
                        print_info(f"[{case_id}] LLM response saved as valid JSON.", debug=False, debug_mode=debug_mode)
                    else:
                        print_info(f"[{case_id}] LLM response was malformed, saved as malformed.", debug=False, debug_mode=debug_mode)

                    return total_tokens, time_taken, "success"
                else:
                    print_error(f"[{case_id}] Request failed with status code {resp.status}", debug=False, debug_mode=debug_mode)
                    error_text = await resp.text()
                    print_error(f"[{case_id}] Response: {error_text}", debug=True, debug_mode=debug_mode)
                    progress_tracker.errored_cases += 1
                    return 0, 0, "error"

        except Exception as e:
            print_error(f"[{case_id}] Failed to process: {e}", debug=False, debug_mode=debug_mode)
            progress_tracker.errored_cases += 1
            return 0, 0, "error"

async def validate_json(content):
    """Validate JSON and return (is_valid, error_message)"""
    try:
        # Try parsing with Python's json module first
        json.loads(content)
        return True, None
    except json.JSONDecodeError as e:
        tmp_path = None
        try:
            # Use jq for more detailed error reporting by writing to temp file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.tmp', delete=False, encoding='utf-8') as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            result = subprocess.run(['jq', '.', tmp_path],
                                  capture_output=True, text=True)
            if result.returncode != 0:
                return False, result.stderr
            return True, None
        except subprocess.CalledProcessError as e:
            return False, str(e)
        except FileNotFoundError:
            # Fall back to Python's error if jq isn't available
            return False, str(e)
        except Exception as e:
            return False, f"Error during JSON validation: {str(e)}"
        finally:
            # Clean up temp file
            if tmp_path is not None:
                try:
                    os.remove(tmp_path)
                except (FileNotFoundError, OSError):
                    pass

async def fix_malformed_json(session, content, error_msg, model_name, endpoint, debug_mode=False):
    """Ask LLM to fix malformed JSON"""
    prompt = render_prompt("extraction/json_repair_user.txt", error_msg=error_msg, content=content)

    messages = [
        {"role": "system", "content": "You are a JSON repair expert."},
        {"role": "user", "content": prompt}
    ]

    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0,
        "stream": False
    }

    try:
        async with session.post(endpoint, json=payload) as resp:
            if resp.status == 200:
                response_json = await resp.json()
                fixed_content = response_json["choices"][0]["message"]["content"]
                # Validate the fixed JSON
                is_valid, new_error = await validate_json(fixed_content)
                if is_valid:
                    return True, fixed_content
                else:
                    return False, f"LLM failed to fix JSON: {new_error}"
            else:
                return False, f"LLM request failed with status {resp.status}"
    except Exception as e:
        return False, f"Error during JSON repair: {str(e)}"

async def save_response_output(full_output, json_path, debug_mode=False, case_id="", mongodb_client=None):
    try:
        extracted_json = json.loads(full_output)
        with open(json_path, "w") as json_file:
            json.dump(extracted_json, json_file, indent=4)
        print_success(f"[{case_id}] Processed and saved JSON: {json_path}", debug=False, debug_mode=debug_mode)
        
        # Insert into MongoDB if client is provided
        if mongodb_client:
            try:
                db = mongodb_client[_AI_CONFIG.mongo_db]
                collection = db[_AI_CONFIG.collection_cases]

                # Top-level case_type mirrors data.report_metadata.report_type
                # so downstream queries can filter without regex-matching the
                # source_file path.
                case_type = (
                    (extracted_json.get('report_metadata') or {}).get('report_type')
                    or ''
                ).upper() or None

                doc = {
                    'case_id': case_id,
                    'processed_at': datetime.now(),
                    'data': extracted_json,
                }
                if case_type:
                    doc['case_type'] = case_type

                collection.update_one(
                    {'case_id': case_id},
                    {'$set': doc},
                    upsert=True
                )
                print_success(f"[{case_id}] Successfully inserted into MongoDB", debug=False, debug_mode=debug_mode)
            except Exception as e:
                print_error(f"[{case_id}] Failed to insert into MongoDB: {e}", debug=False, debug_mode=debug_mode)
        
        return True
    except json.JSONDecodeError as e:
        malformed_path = json_path.replace(".json", ".malformed")
        print_error(f"[{case_id}] Failed to parse JSON from LLM response: {e}", debug=False, debug_mode=debug_mode)
        if debug_mode:
            print_debug(f"[{case_id}] Saving malformed output to {malformed_path}", debug_mode=debug_mode)
        with open(malformed_path, "w") as malformed_file:
            malformed_file.write(full_output)
        print_success(f"[{case_id}] Saved malformed output: {malformed_path}", debug=False, debug_mode=debug_mode)
        return False

def create_type_matcher():
    """Build a content-scoring matcher from each schema's detection_patterns.content_regex block."""
    from vetpathdb.prompts.loader import load_schema
    matchers = {}
    for entry in list_schemas():
        code = (entry.get("code") or "").upper()
        if not code:
            continue
        defn = load_schema(entry["path"])
        regexes = (defn.get("detection_patterns") or {}).get("content_regex") or []
        if not regexes:
            continue
        matchers[code] = {"primary": list(regexes), "weight": 10}
    return matchers

def score_report_type(content, matchers):
    """Score content for each report type"""
    import re
    scores = {type_: 0 for type_ in matchers.keys()}
    
    # Normalize content
    content = ' '.join(content.lower().split())
    
    for type_, patterns in matchers.items():
        # Check primary patterns
        for pattern in patterns['primary']:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                scores[type_] += patterns['weight']

    return scores

def extract_case_id_from_path(path):
    """Extract case ID from path — delegates to shared utility."""
    return extract_case_id_from_name_or_path(path)

def _filename_patterns_by_code() -> dict[str, list[str]]:
    """Return filename marker patterns per case-type code, loaded from registered schemas."""
    from vetpathdb.prompts.loader import load_schema
    patterns: dict[str, list[str]] = {}
    for entry in list_schemas():
        code = (entry.get("code") or "").upper()
        if not code:
            continue
        defn = load_schema(entry["path"])
        filename_hits = (defn.get("detection_patterns") or {}).get("filename") or []
        if filename_hits:
            patterns[code] = [p.upper() for p in filename_hits]
    return patterns


def detect_report_type(filename, debug_mode=False):
    """Detect report type from filename using schema-registered markers."""
    filename = filename.upper()
    print_debug(f"Detecting report type for filename: {filename}", debug_mode=debug_mode)

    patterns = _filename_patterns_by_code()

    for report_type, type_patterns in patterns.items():
        for pattern in type_patterns:
            if pattern in filename:
                print_debug(f"Matched pattern '{pattern}' for type {report_type}", debug_mode=debug_mode)
                return report_type

    # Fallback for the `<case_id>_TYPE.txt` filename layout where the
    # suffix is the bare case-type code (e.g. `12345_IH.txt`).
    if detect_case_id_format(filename.lower()) != "unknown":
        parts = filename.split('_')
        if len(parts) > 1:
            possible_type = parts[-1].split('.')[0]
            if possible_type in patterns:
                return possible_type

    print_debug(f"No report type pattern matched", debug_mode=debug_mode)
    return None

def get_files_size(file_paths):
    """Calculate total size of files in KB"""
    return sum(os.path.getsize(f) for f in file_paths) / 1024

class TypeStats:
    def __init__(self):
        self.total_cases = 0
        self.total_files = 0
        self.total_size_kb = 0
        self.completed = 0
        self.malformed = 0
        
    def add_case(self, txt_files):
        self.total_cases += 1
        self.total_files += len(txt_files)
        self.total_size_kb += get_files_size(txt_files)
        
    def __str__(self):
        return (f"Cases: {self.total_cases}, Files: {self.total_files}, "
                f"Size: {self.total_size_kb:.1f}KB")

def detect_case_report_type(txt_files, debug_mode=False):
    """Detect report type for an entire case based on all files in the case."""
    case_id = os.path.basename(os.path.dirname(txt_files[0]))
    print_debug(f"Detecting report type for case: {case_id}", debug_mode=debug_mode)
    
    # First try filename-based detection
    for txt_path in txt_files:
        file_name = os.path.basename(txt_path)
        report_type = detect_report_type(file_name)
        if report_type:
            print_debug(f"Case {case_id} determined to be type {report_type} from filename: {file_name}", 
                       debug_mode=debug_mode)
            return report_type
    
    # If no type found from filenames, analyze content
    matchers = create_type_matcher()
    combined_scores = {type_: 0 for type_ in matchers.keys()}
    
    # Process each file
    for txt_path in txt_files:
        try:
            with open(txt_path, 'r', encoding='utf-8') as f:
                content = f.read()
                scores = score_report_type(content, matchers)
                
                # Add scores from this file
                for type_, score in scores.items():
                    combined_scores[type_] += score
                    
                if debug_mode:
                    print_debug(f"File scores for {os.path.basename(txt_path)}: {scores}")
                    
        except Exception as e:
            print_debug(f"Error reading file {txt_path}: {e}", debug_mode=debug_mode)
            continue
    
    # Find type with highest score
    if any(combined_scores.values()):
        best_type = max(combined_scores.items(), key=lambda x: x[1])
        if best_type[1] > 0:  # Only return if we have a positive score
            print_debug(f"Case {case_id} determined to be type {best_type[0]} with score {best_type[1]}", 
                       debug_mode=debug_mode)
            return best_type[0]
    
    print_debug(f"No report type could be determined for case {case_id}", debug_mode=debug_mode)
    return None

async def process_malformed_files(session, base_dir, model_name, endpoint, concurrency_level, debug_mode=False):
    """Process all malformed files in the directory"""
    malformed_files = []
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith('.malformed'):
                malformed_files.append(os.path.join(root, file))

    if not malformed_files:
        print_info("No malformed files found.", debug=False, debug_mode=debug_mode)
        return

    print_info(f"Found {len(malformed_files)} malformed files to process.", debug=False, debug_mode=debug_mode)
    
    semaphore = asyncio.Semaphore(concurrency_level)
    
    async def process_single_file(malformed_path):
        async with semaphore:
            print_info(f"Processing malformed file: {malformed_path}", debug=False, debug_mode=debug_mode)
            
            with open(malformed_path, 'r') as f:
                content = f.read()
            
            # Validate and get error message
            is_valid, error_msg = await validate_json(content)
            if is_valid:
                print_info(f"File {malformed_path} is actually valid JSON!", debug=False, debug_mode=debug_mode)
                return
                
            print_info(f"JSON Error: {error_msg}", debug=False, debug_mode=debug_mode)
            
            # Try to fix the JSON
            success, result = await fix_malformed_json(session, content, error_msg, model_name, endpoint, debug_mode)
            
            if success:
                # Save the fixed JSON
                json_path = malformed_path.replace('.malformed', '.json')
                with open(json_path, 'w') as f:
                    f.write(result)
                print_success(f"Fixed JSON saved to: {json_path}", debug=False, debug_mode=debug_mode)
                
                # Optionally rename the malformed file to .original
                original_path = malformed_path.replace('.malformed', '.original')
                os.rename(malformed_path, original_path)
                print_info(f"Renamed malformed file to: {original_path}", debug=False, debug_mode=debug_mode)
            else:
                print_error(f"Failed to fix JSON: {result}", debug=False, debug_mode=debug_mode)
    
    # Process files concurrently
    tasks = [process_single_file(path) for path in malformed_files]
    await asyncio.gather(*tasks)

async def main(concurrency_level, base_dir, model_name, endpoint,
               specific_case_id=None, case_path=None, debug_mode=False, payload_debug=False, reprocess=False,
               report_types=None, update_db=False, fix_malformed=False, enrich_mode=False, enrich_template_file=None,
               prompt_templates_override=None):
    # Parse and validate requested report types against the registered schemas.
    allowed_types = {s['code'].upper() for s in list_schemas() if s.get('code')}
    requested_types = set()
    if report_types:
        requested_types = {t.strip().upper() for t in report_types.split(',')}
        invalid_types = requested_types - allowed_types
        if invalid_types:
            print_error(
                f"Invalid report type(s): {', '.join(invalid_types)}. "
                f"Available: {', '.join(sorted(allowed_types)) or '(none registered)'}",
                debug_mode=debug_mode,
            )
            return
        print_info(f"Processing only report types: {', '.join(sorted(requested_types))}", debug_mode=debug_mode)
    else:
        requested_types = allowed_types

    # Prompt templates are assembled upstream by cli.py from --schema and passed
    # in via prompt_templates_override. No per-type CLI flags any more.
    if not prompt_templates_override:
        print_error(
            "No prompt templates supplied. Invoke via the CLI (vetpathdb extract-data --schema ...) "
            "which assembles templates from a schema YAML.",
            debug_mode=debug_mode,
        )
        return
    prompt_templates = prompt_templates_override
    if debug_mode:
        for rt, pt in prompt_templates.items():
            print_debug(f"Using pre-assembled {rt} prompt ({len(pt)} chars)", debug_mode=debug_mode)

    case_files_map = {}
    completed_cases = 0
    malformed_cases = 0

    if case_path:
        if os.path.isdir(case_path):
            case_id = os.path.basename(case_path)
            txt_files = [os.path.join(case_path, f) for f in os.listdir(case_path) if f.endswith(".txt") or f.endswith(".md")]
            case_files_map = {case_id: txt_files}
        elif os.path.isfile(case_path) and (case_path.endswith(".txt") or case_path.endswith(".md")):
            case_id = os.path.basename(os.path.dirname(case_path))
            case_files_map = {case_id: [case_path]}
        else:
            print_error(f"Specified case path '{case_path}' is invalid.", debug_mode=debug_mode)
            return
    else:
        for root, dirs, files in os.walk(base_dir):
            txts = [os.path.join(root, f) for f in files if f.endswith(".txt") or f.endswith(".md")]
            # Extract case ID from directory name or first file
            case_id = extract_case_id_from_path(txts[0] if txts else root)
            
            if not case_id:
                print_debug(f"Skipping directory {root} - no valid case ID found", debug_mode=debug_mode)
                continue
                
            # Skip if no txt files
            if not txts:
                continue
                
            # Detect case type and filter if needed
            case_report_type = detect_case_report_type(txts, debug_mode=debug_mode)
            if case_report_type not in requested_types:
                continue
                
            has_json = any(f.endswith(".json") and not f.endswith(".enriched-json") for f in files)
            has_enriched = any(f.endswith(".enriched-json") for f in files)
            has_malformed = any(f.endswith(".malformed") for f in files)
            
            # In enrichment mode, check for existing enriched files
            if enrich_mode:
                if has_enriched:
                    if reprocess:
                        case_files_map[case_id] = txts
                    completed_cases += 1
                elif has_malformed:
                    malformed_cases += 1
                else:
                    case_files_map[case_id] = txts
            else:
                # Normal mode - only process new or reprocessing cases
                if has_json:
                    if reprocess:
                        case_files_map[case_id] = txts
                    completed_cases += 1
                elif has_malformed:
                    malformed_cases += 1
                else:
                    case_files_map[case_id] = txts

        if specific_case_id:
            if specific_case_id in case_files_map:
                case_files_map = {specific_case_id: case_files_map[specific_case_id]}
            else:
                print_error(f"Specified case ID '{specific_case_id}' not found.", debug_mode=debug_mode)
                return

    # First collect all cases and validate them
    valid_cases = {}
    type_stats = defaultdict(TypeStats)
    
    for case_id, txt_files in case_files_map.items():
        # In enrichment mode, accept all cases regardless of type
        if enrich_mode:
            valid_cases[case_id] = txt_files
            case_type = detect_case_report_type(txt_files, debug_mode=debug_mode)
            if case_type:
                type_stats[case_type].add_case(txt_files)
        else:
            # Normal mode - filter by requested types
            case_type = detect_case_report_type(txt_files, debug_mode=debug_mode)
            if case_type and case_type in requested_types:
                valid_cases[case_id] = txt_files
                type_stats[case_type].add_case(txt_files)
    
    sorted_case_ids = sorted(valid_cases.keys())
    total_cases = len(valid_cases)
    
    # Wait a moment to ensure all case scanning output is shown
    await asyncio.sleep(1)
    
    # Print processing summary before starting
    print_info("\n=== Processing Summary ===", debug=False, debug_mode=debug_mode)
    print_info(f"Total cases to process: {total_cases}", debug=False, debug_mode=debug_mode)
    
    if completed_cases > 0:
        status = "skipped" if not reprocess else "will be reprocessed"
        print_info(f"Previously completed: {completed_cases} ({status})", debug=False, debug_mode=debug_mode)
    if malformed_cases > 0:
        print_info(f"Previously malformed: {malformed_cases} (skipped)", debug=False, debug_mode=debug_mode)
        
    print_info("\nBreakdown by report type:", debug=False, debug_mode=debug_mode)
    for report_type in sorted(type_stats.keys()):
        stats = type_stats[report_type]
        print_info(f"{report_type}: {stats}", debug=False, debug_mode=debug_mode)
    print_info("=====================\n", debug=False, debug_mode=debug_mode)
    semaphore = asyncio.Semaphore(concurrency_level)

    progress_tracker = ProgressTracker(total_cases, malformed_cases, completed_cases, errored_cases=0)
    
    # Setup MongoDB connection if requested
    mongodb_client = None
    if update_db:
        try:
            mongodb_client = MongoClient(os.getenv('MONGODB_URI', 'mongodb://localhost:27017/'))
            mongodb_client.server_info()  # This will raise an exception if connection fails
            print_info("Successfully connected to MongoDB", debug=False, debug_mode=debug_mode)
        except Exception as e:
            print_error(f"Failed to connect to MongoDB: {e}", debug=False, debug_mode=debug_mode)
            return

    # Load enrichment template if in enrichment mode
    enrich_template = None
    if enrich_mode and enrich_template_file:
        with open(enrich_template_file, "r") as f:
            enrich_template = f.read()
            if debug_mode:
                print_debug(f"Loaded enrichment template from {enrich_template_file}:", debug_mode=debug_mode)
                print_debug(enrich_template, debug_mode=debug_mode)

    async with aiohttp.ClientSession() as session:
        tasks = [
            process_case(
                semaphore, session, case_id, valid_cases[case_id], model_name, endpoint, prompt_templates,
                progress_tracker, debug_mode=debug_mode, payload_debug=payload_debug,
                mongodb_client=mongodb_client if update_db else None,
                enrich_mode=enrich_mode, enrich_template=enrich_template
            )
            for case_id in sorted_case_ids
        ]

        for coro in asyncio.as_completed(tasks):
            tokens, processing_time, status = await coro
            progress_tracker.update(tokens, processing_time, debug_mode, status == "success")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Process txt files with LLM API at the case ID level.')
    parser.add_argument('--concurrency', type=int, default=1, help='Concurrency level')
    parser.add_argument('--base-dir', type=str, required=True, help='Path to the base directory containing txt files')
    parser.add_argument('--model', type=str, help='Model name')
    parser.add_argument('--endpoint', type=str, help='LLM API endpoint')
    parser.add_argument('--schema', type=str, action='append', default=[],
                        help='Path to a schema YAML. May be passed multiple times to extract several types in one run.')
    parser.add_argument('--case-id', type=str, help='Specific case ID to process (optional)')
    parser.add_argument('--case-path', type=str, help='Path to specific case directory or file (optional)')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode with more detailed output')
    parser.add_argument('--payload-debug', action='store_true', help='Show full LLM payload (prompt and messages)')
    parser.add_argument('--reprocess', action='store_true', help='Reprocess cases that already have .json output')
    parser.add_argument('--report-types', type=str, help='Comma-separated list of report types to process (e.g., "PM,SP")')
    parser.add_argument('--updatedb', action='store_true', help='Update MongoDB with processed cases')
    parser.add_argument('--fix-malformed', action='store_true', help='Try to fix malformed JSON files using LLM')
    parser.add_argument('--enrich-template', type=str, help='Path to enrichment prompt template file')
    parser.add_argument('--enrich', action='store_true', help='Run in enrichment mode to add new fields')
    parser.add_argument('--dump-case', action='store_true', help='Dump MongoDB data for specific case ID')
    parser.add_argument('--delete-case', action='store_true', help='Delete case from MongoDB')

    args = parser.parse_args()

    # Check if jq is available when --fix-malformed is used
    if args.fix_malformed:
        try:
            subprocess.run(['jq', '--version'], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print_error("The 'jq' command is not available. Please install it to use --fix-malformed option.")
            sys.exit(1)

    async def reprocess_jsons(base_dir: str, debug_mode: bool = False):
        """Reprocess existing JSON files and update MongoDB"""
        try:
            mongodb_client = MongoClient(os.getenv('MONGODB_URI', 'mongodb://localhost:27017/'))
            mongodb_client.server_info()
            db = mongodb_client[_AI_CONFIG.mongo_db]
            collection = db[_AI_CONFIG.collection_cases]
            print_info("Successfully connected to MongoDB", debug=False, debug_mode=debug_mode)
        except Exception as e:
            print_error(f"Failed to connect to MongoDB: {e}", debug=False, debug_mode=debug_mode)
            return

        # Collect files in two lists to control processing order
        regular_jsons = []
        enriched_jsons = []
        for root, _, files in os.walk(base_dir):
            case_id_from_path = os.path.basename(root)
            if args.case_id and case_id_from_path != args.case_id:
                continue
                
            for file in files:
                full_path = os.path.join(root, file)
                if file.endswith('.enriched-json'):
                    enriched_jsons.append(full_path)
                elif file.endswith('.json'):
                    regular_jsons.append(full_path)

        # Combine lists with regular JSONs first
        json_files = regular_jsons + enriched_jsons

        if not json_files:
            print_info("No JSON files found to reprocess.", debug=False, debug_mode=debug_mode)
            return

        print_info(f"Found {len(json_files)} JSON files to reprocess.", debug=False, debug_mode=debug_mode)

        for json_path in json_files:
            try:
                case_id = os.path.basename(os.path.dirname(json_path))
                print_info(f"Processing {case_id} from {json_path}", debug=False, debug_mode=debug_mode)
                
                # Load existing case data from MongoDB first
                existing_doc = collection.find_one({'case_id': case_id})
                
                with open(json_path, 'r') as f:
                    json_data = json.load(f)
                
                if json_path.endswith('.enriched-json'):
                    if existing_doc:
                        # Preserve existing case data and add enriched fields under data
                        doc = existing_doc
                        doc['processed_at'] = datetime.now()
                        # Add enriched fields under data structure
                        for key, value in json_data.items():
                            if key not in ['case_id', 'processed_at']:
                                doc['data'][key] = value
                    else:
                        print_error(f"[{case_id}] No existing case found for enriched data", debug=False, debug_mode=debug_mode)
                        continue
                else:
                    # Regular JSON - preserve any existing enriched fields
                    doc = {
                        'case_id': case_id,
                        'processed_at': datetime.now(),
                        'data': json_data
                    }
                    if existing_doc:
                        for key, value in existing_doc.items():
                            if key not in ['case_id', 'processed_at', 'data']:
                                doc[key] = value
                
                collection.update_one(
                    {'case_id': case_id},
                    {'$set': doc},
                    upsert=True
                )
                print_success(f"Successfully updated MongoDB for case {case_id}", debug=False, debug_mode=debug_mode)
                
            except Exception as e:
                print_error(f"Failed to process {json_path}: {e}", debug=False, debug_mode=debug_mode)

    async def delete_case_data(case_id: str, debug_mode: bool = False):
        """Delete case data from MongoDB"""
        try:
            mongodb_client = MongoClient(os.getenv('MONGODB_URI', 'mongodb://localhost:27017/'))
            mongodb_client.server_info()
            db = mongodb_client[_AI_CONFIG.mongo_db]
            collection = db[_AI_CONFIG.collection_cases]
            
            result = collection.delete_one({'case_id': case_id})
            if result.deleted_count > 0:
                print_success(f"Successfully deleted case ID: {case_id}")
            else:
                print_error(f"No case found with ID: {case_id}")
                
        except Exception as e:
            print_error(f"Failed to connect to MongoDB: {e}")
            return

    async def dump_case_data(case_id: str, debug_mode: bool = False):
        """Dump case data from MongoDB"""
        try:
            mongodb_client = MongoClient(os.getenv('MONGODB_URI', 'mongodb://localhost:27017/'))
            mongodb_client.server_info()
            db = mongodb_client[_AI_CONFIG.mongo_db]
            collection = db[_AI_CONFIG.collection_cases]
            
            doc = collection.find_one({'case_id': case_id})
            if doc:
                # Convert ObjectId to string for JSON serialization
                doc['_id'] = str(doc['_id'])
                print(json.dumps(doc, indent=2, default=str))
            else:
                print_error(f"No data found for case ID: {case_id}")
                
        except Exception as e:
            print_error(f"Failed to connect to MongoDB: {e}")
            return

    async def run_async():
        if args.dump_case or args.delete_case:
            if not args.case_id:
                print_error("--case-id is required with --dump-case or --delete-case")
                return
            if args.dump_case:
                await dump_case_data(args.case_id, args.debug)
            elif args.delete_case:
                await delete_case_data(args.case_id, args.debug)
        elif args.reprocess:
            await reprocess_jsons(args.base_dir, args.debug)
        else:
            if not args.model or not args.endpoint:
                print_error("--model and --endpoint are required when not in reprocess mode")
                return
                
            async with aiohttp.ClientSession() as session:
                if args.fix_malformed:
                    await process_malformed_files(session, args.base_dir, args.model, args.endpoint,
                                               args.concurrency, args.debug)
                else:
                    # Assemble prompt templates from any --schema arguments.
                    prompt_templates_override = None
                    if args.schema:
                        from vetpathdb.prompts.loader import load_schema, assemble_extraction_prompt
                        prompt_templates_override = {}
                        for schema_path in args.schema:
                            defn = load_schema(schema_path)
                            code = (defn.get("code") or "").upper()
                            if not code:
                                print_error(f"Schema {schema_path} has no `code:` field; skipping.")
                                continue
                            prompt_templates_override[code] = assemble_extraction_prompt(schema_path)
                    await main(
                        concurrency_level=args.concurrency,
                        base_dir=args.base_dir,
                        model_name=args.model,
                        endpoint=args.endpoint,
                        specific_case_id=args.case_id,
                        case_path=args.case_path,
                        debug_mode=args.debug,
                        payload_debug=args.payload_debug,
                        reprocess=args.reprocess,
                        report_types=args.report_types,
                        update_db=args.updatedb,
                        fix_malformed=args.fix_malformed,
                        enrich_mode=args.enrich,
                        prompt_templates_override=prompt_templates_override,
                        enrich_template_file=args.enrich_template
                    )

    asyncio.run(run_async())

