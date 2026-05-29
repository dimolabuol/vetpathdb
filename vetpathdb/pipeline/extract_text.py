import os
import re
import logging
import argparse
import tempfile
from multiprocessing import Pool, cpu_count

# PDF dependencies (PyPDF2, pdf2image, pytesseract, marker) live in the
# `[pdf]` extras. They are imported lazily at the point of first use so
# that `import vetpathdb.pipeline.extract_text` and the CLI module index
# work on a base install. To actually run extraction, install them with:
#     pip install -e ".[pdf]"

_PDF_EXTRAS_HINT = (
    "PDF extraction dependencies are not installed. "
    "Install them with: pip install -e '.[pdf]'"
)


def _require_pdf_extras():
    """Import-and-return the PDF extras, raising a helpful error if missing."""
    try:
        from PyPDF2 import PdfReader
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError as e:
        raise ImportError(f"{_PDF_EXTRAS_HINT} (missing: {e.name})") from e
    return PdfReader, convert_from_path, pytesseract


# Marker is a separate heavy dependency, also under [pdf]. Probe once at
# module load so callers can branch on availability without import overhead.
try:
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered
    from marker.config.parser import ConfigParser
    MARKER_AVAILABLE = True
except ImportError:
    MARKER_AVAILABLE = False

# Global marker models (initialized lazily for efficiency)
_marker_converter = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler("pdf_conversion.log"),
        logging.StreamHandler()  # Log to console
    ]
)

def sanitize_filename(name):
    """
    Replace spaces and non-alphanumeric characters in filenames with underscores.
    """
    return re.sub(r'[^\w]+', '_', name)

def extract_text_from_pdf(pdf_path):
    """
    Attempt to extract text from a PDF using PyPDF2.
    Returns extracted text or an empty string if no text found.
    """
    PdfReader, _, _ = _require_pdf_extras()
    try:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text
        return text.strip()
    except Exception as e:
        logging.error(f"Error reading {pdf_path} with PyPDF2: {e}")
        return ""

def extract_text_with_ocr(pdf_path, temp_dir=None):
    """
    Extract text from a PDF using OCR (pytesseract + pdf2image).
    This is a fallback if PyPDF2 extraction fails (e.g., scanned PDFs).
    """
    _, convert_from_path, pytesseract = _require_pdf_extras()
    if temp_dir is None:
        temp_dir = tempfile.gettempdir()
    text = ""
    try:
        images = convert_from_path(pdf_path, dpi=300, output_folder=temp_dir)
        for img in images:
            page_text = pytesseract.image_to_string(img)
            if page_text:
                text += page_text
        return text.strip()
    except Exception as e:
        logging.error(f"Error performing OCR on {pdf_path}: {e}")
        return ""


def get_marker_converter():
    """
    Get or create the Marker converter instance.
    Initializes models lazily on first call.
    """
    global _marker_converter
    if _marker_converter is None:
        if not MARKER_AVAILABLE:
            raise RuntimeError("Marker library not available. Install with: pip install marker-pdf")
        logging.info("Initializing Marker models (this may take a moment)...")
        config = {
            "output_format": "markdown",
            "disable_image_extraction": True,
        }
        config_parser = ConfigParser(config)
        _marker_converter = PdfConverter(
            config=config_parser.generate_config_dict(),
            artifact_dict=create_model_dict(),
            processor_list=config_parser.get_processors(),
            renderer=config_parser.get_renderer()
        )
        logging.info("Marker models initialized successfully")
    return _marker_converter


def extract_text_with_marker(pdf_path):
    """
    Extract text from PDF using Marker library.
    Returns markdown-formatted text with better structure preservation.
    """
    try:
        converter = get_marker_converter()
        rendered = converter(pdf_path)
        text, _, _ = text_from_rendered(rendered)
        return text.strip()
    except Exception as e:
        logging.error(f"Error processing {pdf_path} with Marker: {e}")
        return ""

from vetpathdb.pipeline._utils import extract_case_id_from_name_or_path

def cleanup_text(text):
    """
    Clean up text by removing excessive whitespace, blank lines,
    and unwanted characters while retaining meaningful structure.
    """
    # Remove excessive spaces (more than two consecutive spaces)
    text = re.sub(r'[ \t]+', ' ', text)
    # Replace multiple blank lines with a single newline
    text = re.sub(r'\n\s*\n+', '\n\n', text.strip())
    return text.strip()

def process_pdf(pdf_path, output_base_directory, copy_pdfs_only=False, extrafiles=False, use_pypdf=False):
    """
    Process a single PDF file: extract text, clean it, and save both text and PDF to the output directory.
    If copy_pdfs_only is True, only copy PDFs without text extraction.
    If extrafiles is True, files will be placed in an 'extra' subdirectory.
    If use_pypdf is True, use legacy PyPDF2+OCR instead of Marker.
    """
    logging.info(f"Processing PDF: {pdf_path}")

    # Extract case ID, prioritizing the file name. With the default
    # (permissive) configuration this never returns None — it falls back
    # to the sanitized filename stem. An empty return would only happen
    # if the input path has no filename component, which should not occur
    # for a real PDF.
    case_id = extract_case_id_from_name_or_path(pdf_path)
    if not case_id:
        logging.warning(f"Could not derive case ID for {pdf_path}. Skipping.")
        return

    # Get the original base name without extension
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    
    # Use sanitized version of the original filename
    sanitized_file_name = sanitize_filename(base_name)
    
    # Only add case ID suffix if we couldn't extract a case ID from the path
    # and the filename doesn't already contain any digit-bearing identifier
    if not case_id and not re.search(r'\d', base_name):
        sanitized_file_name += f"_{case_id}"

    # Create output directory based on case ID format
    case_dir = os.path.join(output_base_directory, case_id)
    if extrafiles:
        # Place files under the 'extra' subdirectory
        case_dir = os.path.join(case_dir, 'extra')

    os.makedirs(case_dir, exist_ok=True)

    # Define output paths - use .md for Marker, .txt for PyPDF2
    file_ext = ".txt" if use_pypdf else ".md"
    text_path = os.path.join(case_dir, f"{sanitized_file_name}{file_ext}")
    pdf_output_path = os.path.join(case_dir, f"{sanitized_file_name}.pdf")

    # Copy the original PDF file
    try:
        import shutil
        shutil.copy2(pdf_path, pdf_output_path)
        logging.info(f"PDF file copied to: {pdf_output_path}")
    except Exception as e:
        logging.error(f"Error copying PDF file {pdf_path}: {e}")
        return

    # If copy_pdfs_only is True, skip text extraction
    if copy_pdfs_only:
        return

    # Extract text using the appropriate method
    if use_pypdf:
        # Legacy PyPDF2 + OCR extraction
        text_content = extract_text_from_pdf(pdf_path)
        used_ocr = False

        if not text_content:
            logging.info(f"No textual content found via PyPDF2 in {pdf_path}, attempting OCR.")
            text_content = extract_text_with_ocr(pdf_path)
            used_ocr = True

        if not text_content:
            logging.error(f"Failed to extract any text from: {pdf_path}")
            return

        # Clean up the extracted text
        cleaned_text = cleanup_text(text_content)

        # Add "-ocr" suffix if OCR was used
        if used_ocr:
            text_path = os.path.splitext(text_path)[0] + "-ocr.txt"
    else:
        # Marker extraction (default) - produces markdown
        text_content = extract_text_with_marker(pdf_path)

        if not text_content:
            logging.error(f"Failed to extract text with Marker from: {pdf_path}")
            return

        # Marker output is already well-formatted, minimal cleanup needed
        cleaned_text = text_content.strip()

    try:
        with open(text_path, "w", encoding="utf-8") as text_file:
            text_file.write(cleaned_text)
        logging.info(f"Text successfully saved to: {text_path}")
    except Exception as e:
        logging.error(f"Error writing text file {text_path}: {e}")

def pdf_to_text(pdf_directory, output_base_directory, num_processes=None, copy_pdfs_only=False, extrafiles=False, use_pypdf=False):
    """
    Traverse a directory and convert all PDF files to text/markdown.
    Process files in parallel using multiprocessing (PyPDF2 mode) or sequentially (Marker mode).
    If copy_pdfs_only is True, only copy PDFs without text extraction.
    If extrafiles is True, files will be placed in an 'extra' subdirectory.
    If use_pypdf is True, use legacy PyPDF2+OCR instead of Marker.
    """
    pdf_files = []

    for root, _, files in os.walk(pdf_directory):
        for file in files:
            if file.lower().endswith(".pdf"):
                pdf_files.append((os.path.join(root, file), output_base_directory, copy_pdfs_only, extrafiles, use_pypdf))

    if not pdf_files:
        logging.info("No PDF files found to process.")
        return

    mode = "copying" if copy_pdfs_only else "processing"
    method = "PyPDF2+OCR" if use_pypdf else "Marker"

    # Marker uses GPU and can't be parallelized with multiprocessing easily
    # Process sequentially for Marker, parallel for PyPDF2
    if use_pypdf or copy_pdfs_only:
        num_processes = num_processes or cpu_count()
        logging.info(f"Starting parallel {mode} with {num_processes} processes using {method}.")
        with Pool(processes=num_processes) as pool:
            pool.starmap(process_pdf, pdf_files)
    else:
        # Sequential processing for Marker (models loaded once, GPU-accelerated)
        logging.info(f"Starting sequential {mode} using {method} (GPU-accelerated).")
        logging.info(f"Processing {len(pdf_files)} PDF files...")
        for i, args in enumerate(pdf_files, 1):
            logging.info(f"[{i}/{len(pdf_files)}] Processing: {os.path.basename(args[0])}")
            process_pdf(*args)

# Example usage
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Process PDF files to markdown/text and organize by case ID')
    parser.add_argument('--copypdfsonly', action='store_true', help='Only copy PDFs to destination without text conversion')
    parser.add_argument('--pdf-dir', required=True, help='Source directory containing PDF files')
    parser.add_argument('--output-dir', required=True, help='Output directory for processed files')
    parser.add_argument('--concurrency', type=int, default=16, help='Number of parallel processes (PyPDF2 mode only)')
    parser.add_argument('--extrafiles', action='store_true', help='Process extra files and place them under the "extra" directory in per-case output directories')
    parser.add_argument('--use-pypdf', action='store_true', help='Use legacy PyPDF2+OCR instead of Marker (outputs .txt instead of .md)')
    args = parser.parse_args()

    # Determine extraction method
    method = "PyPDF2+OCR (legacy)" if args.use_pypdf else "Marker (default)"
    output_format = ".txt" if args.use_pypdf else ".md"

    print(f"Starting PDF processing with settings:")
    print(f"PDF directory: {args.pdf_dir}")
    print(f"Output directory: {args.output_dir}")
    print(f"Extraction method: {method}")
    print(f"Output format: {output_format}")
    print(f"Concurrency: {args.concurrency}" + (" (parallel)" if args.use_pypdf else " (ignored - Marker uses sequential GPU processing)"))
    print(f"Copy PDFs only: {args.copypdfsonly}")
    print(f"Processing as extra files: {args.extrafiles}")

    # Check Marker availability if needed
    if not args.use_pypdf and not args.copypdfsonly and not MARKER_AVAILABLE:
        print("\nERROR: Marker library not available. Either:")
        print("  1. Install Marker: pip install marker-pdf")
        print("  2. Use legacy mode: --use-pypdf")
        exit(1)

    pdf_to_text(args.pdf_dir, args.output_dir, num_processes=args.concurrency,
                copy_pdfs_only=args.copypdfsonly, extrafiles=args.extrafiles, use_pypdf=args.use_pypdf)

