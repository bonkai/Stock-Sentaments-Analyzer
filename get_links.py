import requests
import json
from tqdm import tqdm
import time
import os
import logging
from bs4 import BeautifulSoup
from typing import Optional, List, Set
from datetime import datetime
import spacy
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import re
import random
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# ==========================
# Load Configuration
# ==========================

CONFIG_FILE = 'config.json'

def load_config(filepath: str) -> dict:
    """
    Loads configuration parameters from a JSON file.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Configuration file {filepath} not found.")
    with open(filepath, 'r', encoding='utf-8') as f:
        config = json.load(f)
    return config

config = load_config(CONFIG_FILE)

# ==========================
# Enhanced Session Management
# ==========================

def create_session_with_retry() -> requests.Session:
    """
    Creates a requests session with retry mechanism and enhanced headers
    """
    session = requests.Session()
    
    # Create retry strategy
    retry_strategy = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[403, 429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"]
    )
    
    # Mount the adapter to both HTTP & HTTPS requests
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # Add enhanced headers
    session.headers.update({
        'User-Agent': random.choice(config.get("USER_AGENTS", [])),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'DNT': '1'
    })
    
    return session

def get_random_delay() -> float:
    """
    Returns a random delay between requests
    """
    return random.uniform(2, 5)

# ==========================
# Initialize Valid Tickers
# ==========================

def load_valid_tickers(filepath: str) -> Set[str]:
    """
    Loads valid tickers from file and returns as a set.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Valid tickers file {filepath} not found.")
    with open(filepath, 'r', encoding='utf-8') as f:
        tickers = {line.strip().upper() for line in f if line.strip()}
    logging.info(f"Loaded {len(tickers)} valid stock tickers.")
    return tickers

# Always load valid tickers regardless of USE_VALID_TICKERS setting
valid_tickers = load_valid_tickers(config.get("VALID_TICKERS_FILE", "valid_tickers.txt"))

def find_tickers_in_text(text: str, valid_tickers: Set[str]) -> Set[str]:
    """
    Searches for valid stock tickers in the text.
    Returns a set of found valid tickers.
    """
    text_upper = text.upper()
    found_tickers = set()
    
    for ticker in valid_tickers:
        pattern = rf'\b{re.escape(ticker)}\b'
        if re.search(pattern, text_upper):
            found_tickers.add(ticker)
    
    return found_tickers

# ==========================
# Initialize spaCy
# ==========================

try:
    nlp = spacy.load("en_core_web_sm")
    logging.info("spaCy model loaded successfully.")
except Exception as e:
    logging.error(f"Failed to load spaCy model: {e}")
    raise e

def extract_entities(content: str) -> List[str]:
    """
    Extracts organization entities from the content using spaCy NER.
    """
    doc = nlp(content)
    organizations = [ent.text for ent in doc.ents if ent.label_ == "ORG"]
    return organizations

# ==========================
# Logging Configuration
# ==========================

LOG_FILE = config.get("LOG_FILE", "script.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

# ==========================
# Enhanced Helper Functions
# ==========================

def is_scraping_allowed(url: str, user_agent: str = '*') -> bool:
    """
    Checks if scraping is allowed for the given URL based on robots.txt.
    """
    parsed_url = urlparse(url)
    robots_url = f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"
    rp = RobotFileParser()
    rp.set_url(robots_url)
    try:
        rp.read()
        allowed = rp.can_fetch(user_agent, url)
        if not allowed:
            logging.warning(f"Scraping disallowed by robots.txt: {url}")
        return allowed
    except:
        logging.warning(f"Could not read robots.txt from {robots_url}. Assuming scraping is allowed.")
        return True

def get_full_response(url: str, data: dict, headers: dict, proxies: dict, user_agents: List[str]) -> Optional[str]:
    """
    Sends a POST request to the LLM API with enhanced error handling and retry logic.
    """
    session = create_session_with_retry()
    
    for attempt in range(1, config.get("MAX_RETRIES", 3) + 1):
        try:
            response = session.post(url, json=data, stream=True, timeout=120, proxies=proxies)
            response.raise_for_status()
            
            full_content = ""
            response_lines = []

            start_time = time.time()
            for line in response.iter_lines():
                if line:
                    try:
                        message = json.loads(line.decode('utf-8'))
                        if 'message' in message and 'content' in message['message']:
                            content_piece = message['message']['content']
                            full_content += content_piece
                            response_lines.append(content_piece)
                    except json.JSONDecodeError:
                        logging.warning("Received a line that's not valid JSON. Skipping it.")
                        continue

            elapsed_time = time.time() - start_time
            logging.info(f"Completed in {elapsed_time:.2f} seconds with {len(response_lines)} chunks received.")
            return full_content.strip()
            
        except requests.RequestException as e:
            logging.error(f"Attempt {attempt}: Request failed: {e}")
            if attempt < config.get("MAX_RETRIES", 3):
                delay = get_random_delay() * attempt  # Exponential backoff
                logging.info(f"Retrying in {delay:.2f} seconds...")
                time.sleep(delay)
                continue
            else:
                logging.error("Max retries reached. Skipping this request.")
                return None
        finally:
            session.close()

def scrape_webpage(url: str) -> List[str]:
    """
    Enhanced webpage scraping with improved error handling and retry logic.
    """
    session = create_session_with_retry()
    
    try:
        time.sleep(get_random_delay())
        response = session.get(url, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        links = soup.find_all('a', href=True)
        unique_links = set()

        for link in links:
            href = link['href']
            if href.startswith('javascript:') or href.startswith('#'):
                continue
            if href.startswith('/'):
                href = requests.compat.urljoin(url, href)
            elif not href.startswith('http'):
                href = requests.compat.urljoin(url, href)
            if is_valid_url(href):
                unique_links.add(href)

        logging.info(f"Found {len(unique_links)} unique links.")
        return list(unique_links)
    except requests.RequestException as e:
        logging.error(f"Error scraping webpage {url}: {e}")
        return []
    finally:
        session.close()

def scrape_article(url: str) -> tuple[str, Set[str]]:
    """
    Enhanced article scraping with multiple content extraction strategies.
    """
    session = create_session_with_retry()
    
    try:
        time.sleep(get_random_delay())
        response = session.get(url, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        content = ""
        
        # Strategy 1: Look for article content in common containers
        article_containers = soup.select('article, [class*="article"], [class*="content"], main, [role="main"]')
        if article_containers:
            paragraphs = article_containers[0].find_all('p')
            content = ' '.join([para.get_text() for para in paragraphs])
        
        # Strategy 2: Fallback to all paragraphs if no article container found
        if not content:
            paragraphs = soup.find_all('p')
            content = ' '.join([para.get_text() for para in paragraphs])
        
        # Find valid tickers in the content
        found_tickers = find_tickers_in_text(content, valid_tickers)
        
        return content.strip(), found_tickers
    except requests.RequestException as e:
        logging.error(f"Error scraping article {url}: {e}")
        return "", set()
    finally:
        session.close()

# Rest of your existing helper functions remain unchanged
def is_valid_url(url: str) -> bool:
    """
    Validates the URL format.
    """
    regex = re.compile(
        r'^(?:http|https)://'
        r'(?:\S+(?::\S*)?@)?'
        r'(?:'
        r'(?P<private_ip>'
        r'10(?:\.\d{1,3}){3}|'
        r'127(?:\.\d{1,3}){3}|'
        r'169\.254(?:\.\d{1,3}){2}|'
        r'192\.168(?:\.\d{1,3}){2}|'
        r'172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}'
        r')|'
        r'(?P<public_ip>'
        r'(?:[1-9]\d?|1\d\d|2[01]\d|22[0-3])'
        r'(?:\.(?:1?\d{1,2}|2[0-4]\d|25[0-5])){3}'
        r')|'
        r'(?P<domain>'
        r'(?:[a-z\u00a1-\uffff0-9]-*)*'
        r'[a-z\u00a1-\uffff0-9]+'
        r'(?:\.(?:[a-z\u00a1-\uffff0-9]-*)*'
        r'[a-z\u00a1-\uffff0-9]+)*'
        r'(?:\.(?:[a-z\u00a1-\uffff]{2,}))'
        r')'
        r')'
        r'(?::\d{2,5})?'
        r'(?:/\S*)?$', re.IGNORECASE)
    return re.match(regex, url) is not None

def load_processed_urls(filepath: str) -> set:
    if not os.path.exists(filepath):
        return set()
    with open(filepath, 'r', encoding='utf-8') as f:
        processed = set(line.strip() for line in f if line.strip())
    logging.info(f"Loaded {len(processed)} processed URLs.")
    return processed

def save_processed_url(filepath: str, url: str):
    with open(filepath, 'a', encoding='utf-8') as f:
        f.write(url + '\n')

def get_output_filename(output_dir: str) -> str:
    current_date = datetime.utcnow().strftime('%Y-%m-%d')
    return os.path.join(output_dir, config.get("OUTPUT_FILE_TEMPLATE", "market_sentiment_results_{}.jsonl").format(current_date))

def save_sentiment_incrementally(filepath: str, data: dict):
    data['timestamp'] = int(time.time())
    with open(filepath, 'a', encoding='utf-8') as f:
        f.write(json.dumps(data) + '\n')

def log_raw_response(filepath: str, url: str, response: str):
    with open(filepath, 'a', encoding='utf-8') as f:
        f.write(f"URL: {url}\n")
        f.write(response + '\n\n')

def create_prompt(content: str, url: str) -> str:
    prompt = (
        "You are an AI assistant specialized in financial analysis. Your task is to read the following article, "
        "identify any stock tickers or company names mentioned, and provide a sentiment score for each on a scale of 0-100.\n"
        "0 = 100% Must Sell\n"
        "50 = Neutral\n"
        "100 = 100% Must Buy\n\n"
        "Please ensure that your response is **only** in valid JSON format as specified below. Do **not** include any additional text, explanations, or formatting.\n\n"
        "Use the following JSON structure:\n"
        "{\n"
        f'  "url": "{url}",\n'
        '  "sentiments": {\n'
        '    "TICKER1": SCORE1,\n'
        '    "TICKER2": SCORE2\n'
        '  }\n'
        '}'
    )
    return prompt

def validate_sentiment_data(data: dict, url: str) -> bool:
    if not isinstance(data, dict):
        return False
    if "url" not in data or "sentiments" not in data:
        return False
    if data["url"] != url:
        return False
    if not isinstance(data["sentiments"], dict):
        return False
    for ticker, score in data["sentiments"].items():
        if not isinstance(ticker, str) or not isinstance(score, (int, float)):
            return False
        if not (0 <= score <= 100):
            return False
    return True

def ask_question(messages: list, headers: dict, proxies: dict, user_agents: List[str]) -> Optional[str]:
    """
    Sends messages to the LLM and returns the response content.
    Includes enhanced error handling and retry logic.
    """
    # Create payload for the LLM request
    payload = {
        "model": config.get("MODEL", "qwen2.5:14b"),
        "messages": messages
    }
    
    # Create a session for this request
    session = create_session_with_retry()
    
    try:
        response = session.post(
            config.get("API_URL"),
            json=payload,
            stream=True,
            timeout=120,
            proxies=proxies
        )
        response.raise_for_status()
        
        full_content = ""
        response_lines = []

        start_time = time.time()
        for line in response.iter_lines():
            if line:
                try:
                    message = json.loads(line.decode('utf-8'))
                    if 'message' in message and 'content' in message['message']:
                        content_piece = message['message']['content']
                        full_content += content_piece
                        response_lines.append(content_piece)
                except json.JSONDecodeError:
                    logging.warning("Received a line that's not valid JSON. Skipping it.")
                    continue

        elapsed_time = time.time() - start_time
        logging.info(f"LLM request completed in {elapsed_time:.2f} seconds with {len(response_lines)} chunks received.")
        
        return full_content.strip()
        
    except requests.RequestException as e:
        logging.error(f"Error in LLM request: {str(e)}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error in LLM request: {str(e)}")
        return None
    finally:
        session.close()

def extract_json(raw_response: str) -> Optional[str]:
    """
    Extracts JSON substring from the raw response.
    Includes enhanced error handling and validation.
    """
    try:
        # Find the first occurrence of an opening brace
        start_index = raw_response.find('{')
        if start_index == -1:
            logging.warning("No JSON object found in response (no opening brace)")
            return None

        # Find the matching closing brace
        brace_count = 0
        for i in range(start_index, len(raw_response)):
            if raw_response[i] == '{':
                brace_count += 1
            elif raw_response[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    # We found the matching closing brace
                    json_str = raw_response[start_index:i+1]
                    
                    # Validate that it's actually valid JSON
                    try:
                        json.loads(json_str)  # Test if it's valid JSON
                        return json_str
                    except json.JSONDecodeError:
                        logging.warning("Extracted string is not valid JSON")
                        return None

        logging.warning("No matching closing brace found in response")
        return None

    except Exception as e:
        logging.error(f"Error extracting JSON from response: {str(e)}")
        return None        

# ==========================
# Main Processing Function
# ==========================

def main(webpage_url: str):
    """
    Main function to orchestrate scraping and sentiment analysis.
    """
    # Step 1: Load processed URLs
    processed_urls = load_processed_urls(config.get("PROCESSED_URLS_FILE", "processed_urls.txt"))

    # Step 2: Scrape the main webpage to get all links
    links = scrape_webpage(webpage_url)
    if not links:
        logging.info("No links found. Exiting.")
        return

    # Step 3: Ensure the output directory exists
    output_dir = config.get("OUTPUT_DIR", "outputs")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        logging.info(f"Created output directory: {output_dir}")

    # Step 4: Get the output filename based on the current date
    output_filename = get_output_filename(output_dir)

    # Prepare headers and proxies
    headers = config.get("HEADERS", {}).copy()
    user_agents = config.get("USER_AGENTS", [])
    proxies = config.get("PROXIES", {}) if config.get("USE_PROXIES") else None

    # Create a session for reuse
    session = create_session_with_retry()

    try:
        # Step 5: Iterate over each link and process
        for index, link in enumerate(tqdm(links, desc="Processing links", unit="link"), start=1):
            if link in processed_urls:
                logging.info(f"Skipping already processed URL ({index}/{len(links)}): {link}")
                continue

            logging.info(f"\nProcessing article ({index}/{len(links)}): {link}")
            
            try:
                # Get content and check for tickers before LLM processing
                article_content, found_tickers = scrape_article(link)
                
                if not article_content:
                    logging.info(f"Skipping {link} due to empty content.")
                    save_processed_url(config.get("PROCESSED_URLS_FILE", "processed_urls.txt"), link)
                    continue

                if not found_tickers:
                    logging.info(f"No valid tickers found in {link}. Skipping LLM analysis.")
                    save_processed_url(config.get("PROCESSED_URLS_FILE", "processed_urls.txt"), link)
                    continue

                logging.info(f"Found valid tickers in article: {', '.join(found_tickers)}")

                # Add random delay between requests
                time.sleep(get_random_delay())

                # Now we know we have valid tickers, proceed with LLM analysis
                prompt = create_prompt(article_content, link)
                messages = [{"role": "user", "content": prompt}]

                logging.info(f"Sending content to LLM for sentiment analysis.")
                sentiment_response = ask_question(messages, headers, proxies, user_agents)

                if sentiment_response:
                    log_raw_response(config.get("RAW_RESPONSE_FILE", "llm_raw_responses.log"), link, sentiment_response)

                    json_str = extract_json(sentiment_response)
                    if json_str:
                        try:
                            sentiment_data = json.loads(json_str)

                            if validate_sentiment_data(sentiment_data, link):
                                # Filter sentiments to only include the tickers we found in the text
                                filtered_sentiments = {
                                    ticker: score
                                    for ticker, score in sentiment_data["sentiments"].items()
                                    if ticker.upper() in found_tickers
                                }
                                
                                if filtered_sentiments:
                                    sentiment_data["sentiments"] = filtered_sentiments
                                    save_sentiment_incrementally(output_filename, sentiment_data)
                                    logging.info(f"Sentiment for {link} saved with tickers: {', '.join(filtered_sentiments.keys())}")
                                else:
                                    logging.info(f"No valid stock sentiments found in {link} after filtering. Skipping save.")
                            else:
                                logging.warning(f"Invalid sentiment data format for {link}. Logging raw response.")
                        except json.JSONDecodeError:
                            logging.error(f"Failed to parse extracted JSON for {link}. Logging raw response.")
                    else:
                        logging.error(f"No valid JSON found in the response for {link}. Logging raw response.")
                else:
                    logging.error(f"No sentiment data received for {link}.")

            except Exception as e:
                logging.error(f"Error processing {link}: {str(e)}")
                continue
            finally:
                # Mark the URL as processed regardless of success/failure
                save_processed_url(config.get("PROCESSED_URLS_FILE", "processed_urls.txt"), link)

            # Rate limiting between articles
            time.sleep(config.get("REQUEST_DELAY", 1))

    except Exception as e:
        logging.error(f"Fatal error in main processing loop: {str(e)}")
    finally:
        # Clean up the session
        session.close()
        logging.info("\nAll links processed.")

if __name__ == "__main__":
    try:
        # Replace with your target webpage URL
        TARGET_URL = 'https://biztoc.com/'
        main(TARGET_URL)
    except Exception as e:
        logging.error(f"Fatal error: {str(e)}")