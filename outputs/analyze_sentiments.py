import json
from collections import defaultdict
import statistics
import os
from datetime import datetime
import webbrowser

def analyze_sentiment_data(all_json_lines):
    # Initialize data structures
    sentiment_by_ticker = defaultdict(list)
    
    # Process each line - now keeping all mentions
    for line in all_json_lines:
        data = json.loads(line)
        timestamp = data['timestamp']
        
        # Store each mention with its full data
        for ticker, score in data['sentiments'].items():
            sentiment_by_ticker[ticker].append({
                'timestamp': timestamp,
                'sentiment': score,
                'url': data['url']
            })
    
    # Analyze the data while preserving all mentions
    analysis = {}
    for ticker, mentions in sentiment_by_ticker.items():
        # Sort mentions by timestamp
        sorted_mentions = sorted(mentions, key=lambda x: x['timestamp'])
        scores = [m['sentiment'] for m in mentions]
        
        analysis[ticker] = {
            'mentions': sorted_mentions,  # Keep all individual mentions
            'stats': {
                'mention_count': len(mentions),
                'average_sentiment': round(statistics.mean(scores), 2),
                'sentiment_std': round(statistics.stdev(scores), 2) if len(scores) > 1 else 0,
                'max_sentiment': max(scores),
                'min_sentiment': min(scores),
                'latest_sentiment': sorted_mentions[-1]['sentiment'],
                'latest_timestamp': sorted_mentions[-1]['timestamp'],
                'latest_url': sorted_mentions[-1]['url']
            }
        }
    
    return analysis

def get_notable_tickers(analysis, min_mentions=2):
    """Identify tickers worth paying attention to based on various criteria"""
    notable = {
        'highly_discussed': [],
        'very_positive': [],
        'very_negative': [],
        'high_volatility': [],
        'trending_up': [],
        'trending_down': []
    }
    
    for ticker, data in analysis.items():
        stats = data['stats']  # Updated to use new structure
        if stats['mention_count'] < min_mentions:
            continue
            
        # Highly discussed stocks
        if stats['mention_count'] >= 3:
            notable['highly_discussed'].append(
                [ticker, f"Mentions: {stats['mention_count']}, Avg Sentiment: {stats['average_sentiment']}"]
            )
        
        # Very positive sentiment
        if stats['average_sentiment'] >= 70:
            notable['very_positive'].append(
                [ticker, f"Sentiment: {stats['average_sentiment']}"]
            )
            
        # Very negative sentiment
        if stats['average_sentiment'] <= 40:
            notable['very_negative'].append(
                [ticker, f"Sentiment: {stats['average_sentiment']}"]
            )
            
        # High volatility in sentiment
        if stats['sentiment_std'] > 15:
            notable['high_volatility'].append(
                [ticker, f"StdDev: {stats['sentiment_std']}"]
            )
            
        # Trending up (latest > average)
        if stats['latest_sentiment'] > stats['average_sentiment'] + 10:
            notable['trending_up'].append(
                [ticker, f"Latest: {stats['latest_sentiment']} vs Avg: {stats['average_sentiment']}"]
            )
            
        # Trending down (latest < average)
        if stats['latest_sentiment'] < stats['average_sentiment'] - 10:
            notable['trending_down'].append(
                [ticker, f"Latest: {stats['latest_sentiment']} vs Avg: {stats['average_sentiment']}"]
            )
    
    return notable

def export_to_javascript(analysis, notable_tickers):
    """Export the analysis data to a JavaScript file"""
    js_data = {
        'lastUpdate': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'analysis': analysis,
        'notable': notable_tickers
    }
    
    # Create JavaScript file with the data
    with open('sentiment_data.js', 'w') as f:
        f.write('const sentimentData = ')
        json.dump(js_data, f, indent=2)
        f.write(';')

def main():
    # Get all .json and .jsonl files in the current directory
    json_files = [f for f in os.listdir('.') if f.endswith(('.json', '.jsonl'))]
    
    if not json_files:
        print("No JSON files found in the current directory!")
        return
    
    print("Processing sentiment data...")
    
    # Collect all JSON lines from all files
    all_json_lines = []
    for file_name in json_files:
        try:
            with open(file_name, 'r') as f:
                content = f.read()
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                all_json_lines.extend(lines)
                print(f"Processed {file_name}")
        except Exception as e:
            print(f"Error reading file {file_name}: {str(e)}")
            continue
    
    # Analyze the data
    analysis = analyze_sentiment_data(all_json_lines)
    notable_tickers = get_notable_tickers(analysis)
    
    # Export to JavaScript file
    export_to_javascript(analysis, notable_tickers)
    print("Data exported to sentiment_data.js")
    
    # Get the absolute path to the HTML file
    html_path = os.path.abspath('sentiment_dashboard.html')
    
    # Convert the file path to a URL
    url = f'file://{html_path}'
    
    print("Opening dashboard in your default browser...")
    webbrowser.open(url)

if __name__ == "__main__":
    main()