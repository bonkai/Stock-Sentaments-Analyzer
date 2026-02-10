import os
import json
from glob import glob
import logging

def setup_logging():
    """Configure logging."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

def extract_tickers_from_file(filepath):
    """
    Extract tickers from a single JSONL file.
    
    Args:
        filepath (str): Path to the JSONL file
        
    Returns:
        set: Set of unique tickers found in the file
    """
    tickers = set()
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    if 'sentiments' in data and isinstance(data['sentiments'], dict):
                        # Add all tickers from the sentiments dictionary
                        tickers.update(data['sentiments'].keys())
                except json.JSONDecodeError:
                    logging.warning(f"Skipping invalid JSON line in {filepath}")
                except Exception as e:
                    logging.error(f"Error processing line in {filepath}: {e}")
    except Exception as e:
        logging.error(f"Error reading file {filepath}: {e}")
    
    return tickers

def process_output_directory(output_dir='outputs'):
    """
    Process all JSONL files in the output directory and extract tickers.
    
    Args:
        output_dir (str): Directory containing the JSONL files
        
    Returns:
        set: Set of all unique tickers found
    """
    all_tickers = set()
    
    # Find all .jsonl files in the output directory
    jsonl_pattern = os.path.join(output_dir, '*.jsonl')
    jsonl_files = glob(jsonl_pattern)
    
    if not jsonl_files:
        logging.warning(f"No JSONL files found in {output_dir}")
        return all_tickers
    
    logging.info(f"Found {len(jsonl_files)} JSONL files to process")
    
    # Process each file
    for filepath in jsonl_files:
        logging.info(f"Processing {filepath}")
        file_tickers = extract_tickers_from_file(filepath)
        all_tickers.update(file_tickers)
        logging.info(f"Found {len(file_tickers)} tickers in {filepath}")
    
    return all_tickers

def save_tickers(tickers, output_file='valid_tickers.txt'):
    """
    Save tickers to a file, one per line.
    
    Args:
        tickers (set): Set of tickers to save
        output_file (str): Path to the output file
    """
    try:
        # Convert to list and sort for consistent output
        sorted_tickers = sorted(tickers)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            for ticker in sorted_tickers:
                f.write(f"{ticker}\n")
        
        logging.info(f"Successfully saved {len(tickers)} tickers to {output_file}")
    except Exception as e:
        logging.error(f"Error saving tickers to {output_file}: {e}")

def main():
    """Main function to orchestrate the ticker extraction process."""
    setup_logging()
    
    logging.info("Starting ticker extraction process")
    
    # Process all files and get unique tickers
    all_tickers = process_output_directory()
    
    if all_tickers:
        logging.info(f"Found total of {len(all_tickers)} unique tickers")
        
        # Save to valid_tickers.txt
        save_tickers(all_tickers)
    else:
        logging.warning("No tickers found in any files")

if __name__ == "__main__":
    main()