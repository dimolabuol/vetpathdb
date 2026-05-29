"""VetPathDB unified command-line interface.

Usage::

    vetpathdb serve                  # Start web server
    vetpathdb extract-text ...       # PDF to text
    vetpathdb extract-data ...       # LLM structured extraction
    vetpathdb load ...               # Insert into MongoDB
    vetpathdb index                  # Build vector search index
    vetpathdb pipeline ...           # Run full ingestion pipeline
"""

import argparse
import os
import sys


def cmd_serve(args):
    """Start the VetPathDB web server."""
    from vetpathdb.app import main as serve_main
    # Re-inject args into sys.argv so app.main() can parse them
    argv = []
    if args.mcp:
        argv.append("--mcp")
    if args.demo_db:
        argv.append("--demo-db")
    if args.skip_models:
        argv.append("--skip-models")
    if args.debug_search:
        argv.append("--debug-search")
    sys.argv = ["vetpathdb"] + argv
    serve_main()


def cmd_extract_text(args):
    """Extract text from PDF files."""
    from vetpathdb.pipeline.extract_text import pdf_to_text
    pdf_to_text(
        args.pdf_dir,
        args.output_dir,
        num_processes=args.concurrency,
        copy_pdfs_only=args.copy_pdfs_only,
        extrafiles=args.extra_files,
        use_pypdf=(args.method == "pypdf"),
    )


def cmd_extract_data(args):
    """Extract structured data via LLM."""
    import asyncio

    # Build prompt template(s) from schema or direct template file
    prompt_templates = {}

    if args.schema:
        from vetpathdb.prompts.loader import load_schema, assemble_extraction_prompt
        defn = load_schema(args.schema)
        code = defn["code"]
        prompt_text = assemble_extraction_prompt(args.schema)
        prompt_templates[code] = prompt_text
        print(f"Loaded schema: {defn['name']} (code={code})")
    elif args.template:
        # Direct template file — user provides --template and --type-code
        if not args.type_code:
            print("Error: --type-code is required when using --template")
            sys.exit(1)
        with open(args.template) as f:
            prompt_templates[args.type_code] = f.read()
    else:
        print("Error: provide --schema (recommended) or --template + --type-code")
        sys.exit(1)

    from vetpathdb.pipeline.extract_data import main as extract_main

    asyncio.run(extract_main(
        concurrency_level=args.concurrency,
        base_dir=args.input_dir,
        model_name=args.model,
        endpoint=args.endpoint,
        specific_case_id=args.case_id,
        debug_mode=args.debug,
        update_db=args.load_to_db,
        enrich_mode=args.enrich,
        prompt_templates_override=prompt_templates,
    ))


def cmd_load(args):
    """Load extracted data into MongoDB."""
    from vetpathdb.pipeline.load import main as load_main
    load_main(
        base_dir=args.input_dir,
        debug_mode=args.debug,
        process_text=args.text_files,
        extra_text_files=args.extra_text_files,
        incremental=args.incremental,
    )


def cmd_index(args):
    """Build vector search index."""
    from vetpathdb.search.vectordb import main as index_main
    index_main(debug_mode=args.debug, stats_only=args.stats)


def cmd_pipeline(args):
    """Run the full ingestion pipeline."""
    import os
    import tempfile
    import asyncio

    output_dir = args.output_dir or tempfile.mkdtemp(prefix="vetpathdb_")
    print(f"Step 1/4: Extracting text from PDFs -> {output_dir}")
    cmd_extract_text(argparse.Namespace(
        pdf_dir=args.pdf_dir,
        output_dir=output_dir,
        concurrency=args.concurrency,
        copy_pdfs_only=False,
        extra_files=False,
        method="marker",
    ))

    print(f"\nStep 2/4: Extracting structured data via LLM")
    cmd_extract_data(argparse.Namespace(
        schema=args.schema,
        template=None,
        type_code=None,
        input_dir=output_dir,
        endpoint=args.endpoint,
        model=args.model,
        concurrency=args.concurrency,
        case_id=None,
        debug=args.debug,
        load_to_db=False,
        enrich=False,
    ))

    print(f"\nStep 3/4: Loading into database")
    cmd_load(argparse.Namespace(
        input_dir=output_dir,
        debug=args.debug,
        text_files=False,
        extra_text_files=False,
        incremental=True,
    ))
    # Also load text files
    cmd_load(argparse.Namespace(
        input_dir=output_dir,
        debug=args.debug,
        text_files=True,
        extra_text_files=False,
        incremental=True,
    ))

    print(f"\nStep 4/4: Building search index")
    cmd_index(argparse.Namespace(debug=args.debug, stats=False))

    print(f"\nPipeline complete. Data loaded from {args.pdf_dir}")


def cmd_load_examples(args):
    """Load bundled example cases into the database."""
    import json
    from pathlib import Path
    from pymongo import MongoClient

    examples_path = Path(__file__).parent / "examples" / "demo_cases.json"
    if not examples_path.exists():
        print(f"Error: example data not found at {examples_path}")
        sys.exit(1)

    with open(examples_path) as f:
        cases = json.load(f)

    uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        client.server_info()
    except Exception as e:
        print(f"Error: cannot connect to MongoDB at {uri}")
        print(f"  {e}")
        print("  Make sure MongoDB is running: sudo systemctl start mongod")
        sys.exit(1)

    # Load into the default database so it works out of the box,
    # including inside Docker where no --demo-db flag is set.
    from vetpathdb.config import AIConfig
    cfg = AIConfig()
    db_name = cfg.mongo_db
    db = client[db_name]
    collection = db[cfg.collection_cases]

    # Upsert each case
    for case in cases:
        collection.replace_one({"case_id": case["case_id"]}, case, upsert=True)

    print(f"Loaded {len(cases)} example cases into '{db_name}' database")
    print()
    print("Next steps:")
    print("  vetpathdb serve")
    print("  Open http://localhost:8080  (HTTP default; HTTPS on 9443 if certs/ present)")


def cmd_doctor(args):
    """Check VetPathDB dependencies and configuration."""
    import os
    from pathlib import Path

    print("VetPathDB Doctor")
    print("=" * 40)

    # Python version
    print(f"  Python:          {sys.version.split()[0]}", end="")
    v = sys.version_info
    print(" ok" if v >= (3, 11) else " WARNING: need 3.11+")

    # sqlite3 version (required by ChromaDB >= 3.35)
    import sqlite3
    sqlite_v = tuple(int(x) for x in sqlite3.sqlite_version.split("."))
    print(f"  sqlite3:         {sqlite3.sqlite_version}", end="")
    if sqlite_v >= (3, 35, 0):
        print(" ok")
    else:
        print(" WARNING: ChromaDB needs >= 3.35.0")
        print(f"    fix: pip install pysqlite3-binary")
        print(f"    then: export PYTHONPATH with: import pysqlite3; sys.modules['sqlite3'] = pysqlite3")
        print(f"    see docs/SETUP_GUIDE.md troubleshooting")

    # MongoDB
    try:
        from pymongo import MongoClient
        uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
        client = MongoClient(uri, serverSelectionTimeoutMS=3000)
        client.server_info()
        from vetpathdb.config import AIConfig
        cfg = AIConfig()
        cases_count = client[cfg.mongo_db][cfg.collection_cases].count_documents({})
        demo_count = client[cfg.mongo_db_demo][cfg.collection_cases].count_documents({})
        print(f"  MongoDB:         ok ({uri})")
        print(f"    cases:         {cases_count} documents")
        print(f"    cases_demo:    {demo_count} documents")
    except Exception as e:
        print(f"  MongoDB:         FAILED ({e})")

    # LLM endpoint
    try:
        from vetpathdb.config import AIConfig
        config = AIConfig()
        import urllib.request
        req = urllib.request.Request(config.llm_base_url + "/models", method="GET")
        urllib.request.urlopen(req, timeout=3)
        print(f"  LLM endpoint:    ok ({config.llm_base_url})")
    except Exception:
        print(f"  LLM endpoint:    not reachable ({config.llm_base_url})")
        print(f"    (needed for extraction and AI search, not for basic keyword search)")

    # Vector store
    vs_path = Path(os.getenv('AI_VECTOR_STORE_PATH', './cases_vectorstore'))
    vs_demo = Path('./cases_vectorstore_demo')
    if vs_path.exists():
        print(f"  Vector store:    ok ({vs_path})")
    elif vs_demo.exists():
        print(f"  Vector store:    ok ({vs_demo}, demo)")
    else:
        print(f"  Vector store:    not found (run 'vetpathdb index' to build)")

    # TLS (opt-in): server uses HTTPS if certs/key.pem + certs/cert.pem exist,
    # plain HTTP otherwise. Neither is "required" — informational only.
    key = Path("certs/key.pem")
    cert = Path("certs/cert.pem")
    if key.exists() and cert.exists():
        print(f"  TLS:             HTTPS on port 9443 (certs present)")
    else:
        print(f"  TLS:             HTTP only on port 8080 (drop certs/key.pem + certs/cert.pem to enable HTTPS on 9443)")

    # Optional: FastMCP
    try:
        import fastmcp
        print(f"  FastMCP:         ok (MCP support available)")
    except ImportError:
        print(f"  FastMCP:         not installed (pip install vetpathdb[mcp])")

    print()


def main():
    parser = argparse.ArgumentParser(
        prog="vetpathdb",
        description="VetPathDB - AI-powered document extraction and search",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- serve ---
    serve = subparsers.add_parser("serve", help="Start the web server")
    serve.add_argument("--mcp", action="store_true", help="Enable MCP server")
    serve.add_argument("--demo-db", action="store_true", help="Use demo database")
    serve.add_argument("--skip-models", action="store_true", help="Skip AI model loading")
    serve.add_argument("--debug-search", action="store_true", help="Debug search output")
    serve.set_defaults(func=cmd_serve)

    # --- extract-text ---
    et = subparsers.add_parser("extract-text", help="Extract text from PDFs")
    et.add_argument("--pdf-dir", required=True, help="Source PDF directory")
    et.add_argument("--output-dir", required=True, help="Output directory for text")
    et.add_argument("--method", choices=["marker", "pypdf"], default="marker",
                    help="Extraction method (default: marker)")
    et.add_argument("--concurrency", type=int, default=16, help="Parallel workers")
    et.add_argument("--copy-pdfs-only", action="store_true", help="Copy PDFs without conversion")
    et.add_argument("--extra-files", action="store_true", help="Process extra files into subdirs")
    et.set_defaults(func=cmd_extract_text)

    # --- extract-data ---
    ed = subparsers.add_parser("extract-data", help="Extract structured data via LLM")
    ed.add_argument("--input-dir", required=True, help="Directory with text files")
    ed.add_argument("--schema", help="Path to schema YAML file (recommended)")
    ed.add_argument("--template", help="Path to raw prompt template (advanced)")
    ed.add_argument("--type-code", help="Report type code when using --template")
    ed.add_argument("--endpoint", required=True, help="LLM API endpoint URL")
    ed.add_argument("--model", required=True, help="LLM model name")
    ed.add_argument("--concurrency", type=int, default=4, help="Concurrent LLM requests")
    ed.add_argument("--case-id", help="Process a single case ID")
    ed.add_argument("--enrich", action="store_true", help="Run enrichment pass")
    ed.add_argument("--load-to-db", action="store_true", help="Also load results to MongoDB")
    ed.add_argument("--debug", action="store_true", help="Debug output")
    ed.set_defaults(func=cmd_extract_data)

    # --- load ---
    ld = subparsers.add_parser("load", help="Load extracted data into database")
    ld.add_argument("--input-dir", required=True, help="Directory with extracted JSON/text")
    ld.add_argument("--text-files", action="store_true", help="Load text files into filestore")
    ld.add_argument("--extra-text-files", action="store_true", help="Include extra/ subdirs")
    ld.add_argument("--incremental", action="store_true", help="Skip already-loaded cases")
    ld.add_argument("--debug", action="store_true", help="Debug output")
    ld.set_defaults(func=cmd_load)

    # --- index ---
    ix = subparsers.add_parser("index", help="Build vector search index")
    ix.add_argument("--debug", action="store_true", help="Debug output")
    ix.add_argument("--stats", action="store_true", help="Show stats only")
    ix.set_defaults(func=cmd_index)

    # --- pipeline ---
    pl = subparsers.add_parser("pipeline", help="Run full ingestion pipeline (all steps)")
    pl.add_argument("--pdf-dir", required=True, help="Source PDF directory")
    pl.add_argument("--schema", required=True, help="Path to schema YAML file")
    pl.add_argument("--endpoint", required=True, help="LLM API endpoint URL")
    pl.add_argument("--model", required=True, help="LLM model name")
    pl.add_argument("--output-dir", help="Text output dir (default: temp directory)")
    pl.add_argument("--concurrency", type=int, default=4, help="Parallel workers")
    pl.add_argument("--debug", action="store_true", help="Debug output")
    pl.set_defaults(func=cmd_pipeline)

    # --- load-examples ---
    le = subparsers.add_parser("load-examples", help="Load the bundled synthetic example cases into the database")
    le.set_defaults(func=cmd_load_examples)

    # --- doctor ---
    doc = subparsers.add_parser("doctor", help="Check dependencies and configuration")
    doc.set_defaults(func=cmd_doctor)

    args = parser.parse_args()
    if not args.command:
        # Default to `serve` when no subcommand is given.
        args = parser.parse_args(["serve"] + sys.argv[1:])
    args.func(args)


if __name__ == "__main__":
    main()
