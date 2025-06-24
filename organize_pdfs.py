import json
import os
import shutil
from pathlib import Path
import glob

DOCS_DIR = Path("docs")
COMBINED_METADATA_OUTPUT_FILE = Path("all_metadata_combined.json") # Added for new function

def load_metadata_file(file_path: Path) -> list:
    """Loads and parses a single JSON metadata file."""
    if not file_path.exists():
        print(f"Warning: Metadata file not found at {file_path}")
        return []
    with open(file_path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict): # Handle cases where a single JSON object might be in a file meant to be part of a list
                return [data]
            else:
                print(f"Warning: Metadata in {file_path} is not a list or dictionary.")
                return []
        except json.JSONDecodeError:
            print(f"Error: Could not decode JSON from {file_path}")
            return []

def concatenate_metadata_files(output_file_path: Path = COMBINED_METADATA_OUTPUT_FILE):
    """
    Finds all metadata_page_*.json files in DOCS_DIR,
    combines their content, and writes it to output_file_path.
    """
    all_data = []
    if not DOCS_DIR.exists() or not DOCS_DIR.is_dir():
        print(f"Error: Docs directory not found at {DOCS_DIR}. Cannot find metadata pages.")
        return

    metadata_files_pattern = str(DOCS_DIR / "metadata_page_*.json")
    found_files = list(glob.glob(metadata_files_pattern))

    if not found_files:
        print(f"No metadata files found matching pattern: {metadata_files_pattern}")
        # Optionally, still create an empty JSON file or list
        # with open(output_file_path, 'w', encoding='utf-8') as f:
        #     json.dump([], f, indent=4, ensure_ascii=False)
        # print(f"Created empty combined metadata file at {output_file_path}")
        return

    print(f"Found {len(found_files)} metadata page files to concatenate.")

    for file_path_str in found_files:
        file_path = Path(file_path_str)
        print(f"Processing: {file_path}")
        data = load_metadata_file(file_path)
        if data: # load_metadata_file returns a list
            all_data.extend(data)

    try:
        with open(output_file_path, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, indent=4, ensure_ascii=False)
        print(f"Successfully concatenated metadata to: {output_file_path}")
    except IOError as e:
        print(f"Error writing combined metadata to {output_file_path}: {e}")
    except Exception as e:
        print(f"An unexpected error occurred while writing combined metadata: {e}")

def organize_pdfs():
    """
    Organizes PDF files from the DOCS_DIR into year-based subfolders
    based on metadata from metadata files in DOCS_DIR.
    """
    all_metadata = []

    # Load additional metadata files from docs directory
    if DOCS_DIR.exists() and DOCS_DIR.is_dir():
        for metadata_page_file_path_str in glob.glob(str(DOCS_DIR / "metadata_page_*.json")):
            metadata_page_file_path = Path(metadata_page_file_path_str)
            print(f"Loading additional metadata from: {metadata_page_file_path}")
            all_metadata.extend(load_metadata_file(metadata_page_file_path))
    else:
        print(f"Warning: Docs directory not found at {DOCS_DIR}, cannot load page-specific metadata.")
        # If only the main metadata file is expected to exist and docs dir might not,
        # this warning might be too strong. Adjust if necessary.

    if not all_metadata:
        print("Error: No metadata loaded. Please check metadata files.")
        return

    if not DOCS_DIR.exists() or not DOCS_DIR.is_dir():
        print(f"Error: Docs directory not found at {DOCS_DIR}. Cannot move PDF files.")
        return

    print(f"Organizing PDFs in {DOCS_DIR} using combined metadata...")
    moved_files = 0
    skipped_files = 0
    processed_filenames = set() # Keep track of filenames to avoid processing duplicates if they appear in multiple metadata sources

    for item in all_metadata:
        if not isinstance(item, dict):
            print(f"Warning: Skipping non-dictionary item in combined metadata: {item}")
            continue

        pdf_filename = item.get("downloaded_filename")
        date_str = item.get("date")

        if not pdf_filename:
            print(f"Warning: Skipping item due to missing \'downloaded_filename\': {item.get('title', 'N/A')}")
            continue
        
        if pdf_filename in processed_filenames:
            # print(f"Info: PDF \'{pdf_filename}\' already processed, skipping.")
            # skipped_files +=1 # Counting as skipped might be misleading if it was successfully moved by another metadata entry
            continue


        if not date_str:
            print(f"Warning: Skipping item \'{pdf_filename}\' due to missing \'date\'")
            skipped_files += 1
            processed_filenames.add(pdf_filename)
            continue

        try:
            # Extract year from ISO date string (e.g., "2021-02-12T00:00:00.000Z")
            year = date_str.split('-')[0]
            if not year.isdigit() or len(year) != 4:
                raise ValueError("Year format is incorrect")
        except (IndexError, ValueError) as e:
            print(f"Warning: Skipping item \'{pdf_filename}\' due to invalid date format \'{date_str}\': {e}")
            skipped_files += 1
            processed_filenames.add(pdf_filename)
            continue

        source_pdf_path = DOCS_DIR / pdf_filename
        year_dir = DOCS_DIR / year

        if not source_pdf_path.exists():
            # print(f"Info: Source PDF not found, skipping: {source_pdf_path}")
            skipped_files +=1
            processed_filenames.add(pdf_filename)
            continue
        
        processed_filenames.add(pdf_filename)

        try:
            year_dir.mkdir(parents=True, exist_ok=True)
            destination_pdf_path = year_dir / pdf_filename

            if destination_pdf_path.exists():
                # print(f"Info: Destination already exists, skipping: {destination_pdf_path}")
                # If it already exists in the target, we can consider it "moved" or "organized"
                # For accurate counting, we might not increment moved_files here if we want to count only actual moves by this run.
                # However, if the goal is to ensure all files end up organized, this is fine.
                # For now, let's count it as skipped to reflect it wasn't moved *by this specific operation*.
                skipped_files += 1
                continue

            shutil.move(str(source_pdf_path), str(destination_pdf_path))
            # print(f"Moved: {source_pdf_path} -> {destination_pdf_path}")
            moved_files += 1
        except OSError as e:
            print(f"Error moving file {pdf_filename} to {year_dir}: {e}")
            skipped_files += 1
        except Exception as e:
            print(f"An unexpected error occurred while processing {pdf_filename}: {e}")
            skipped_files += 1
            
    print(f"PDF organization complete. Moved {moved_files} files. Skipped or failed {skipped_files} files.")

if __name__ == "__main__":
    #organize_pdfs()
    # Example of how to call the new function:
    concatenate_metadata_files()
