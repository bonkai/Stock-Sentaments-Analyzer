import streamlit as st
import pandas as pd
import os
import json
from datetime import datetime
import matplotlib.pyplot as plt
import seaborn as sns

@st.cache_data
def load_data(outputs_dir):
    """
    Loads and consolidates data from all .jsonl files in the outputs directory into a DataFrame.
    """
    data = []
    for file in os.listdir(outputs_dir):
        if file.endswith('.jsonl'):
            file_path = os.path.join(outputs_dir, file)
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        url = record.get('url', '')
                        sentiments = record.get('sentiments', {})
                        timestamp = record.get('timestamp', 0)
                        # Convert epoch to datetime
                        date = datetime.fromtimestamp(timestamp)
                        for ticker, score in sentiments.items():
                            data.append({
                                'url': url,
                                'ticker': ticker.upper(),
                                'score': score,
                                'timestamp': date
                            })
                    except json.JSONDecodeError:
                        continue
    df = pd.DataFrame(data)
    return df

def main():
    st.set_page_config(page_title="Market Sentiment Dashboard", layout="wide")
    st.title("📈 Market Sentiment Analysis Dashboard")
    
    # Sidebar Filters
    st.sidebar.header("Filters")
    selected_ticker = st.sidebar.text_input("Search for a Ticker (e.g., AAPL)", "")
    
    # Load Data
    outputs_dir = 'outputs'  # Ensure this is the correct path to your outputs directory
    df = load_data(outputs_dir)
    
    if df.empty:
        st.warning("No data available. Please ensure the outputs directory contains .jsonl files with data.")
        return
    
    # Display Most Recent 100 Sentiments
    st.subheader("📰 Most Recent 1000 Sentiment Entries")
    recent_df = df.sort_values(by='timestamp', ascending=False).head(1000)
    st.dataframe(recent_df[['timestamp', 'ticker', 'score', 'url']].reset_index(drop=True))
    
    # Plotting Sentiment Over Time
    if selected_ticker:
        ticker_upper = selected_ticker.upper()
        ticker_df = df[df['ticker'] == ticker_upper].sort_values(by='timestamp')
        if not ticker_df.empty:
            st.subheader(f"📊 Sentiment Over Time for {ticker_upper}")
            fig, ax = plt.subplots(figsize=(10, 5))
            sns.lineplot(data=ticker_df, x='timestamp', y='score', marker='o', ax=ax)
            ax.set_xlabel("Date")
            ax.set_ylabel("Sentiment Score")
            ax.set_title(f"Sentiment Trend for {ticker_upper}")
            ax.set_ylim(0, 100)
            st.pyplot(fig)
        else:
            st.info(f"No sentiment data found for ticker: {ticker_upper}")
    
    # Display All Sentiments for the Searched Ticker
    if selected_ticker:
        st.subheader(f"🔍 All Sentiment Entries for {ticker_upper}")
        ticker_df = df[df['ticker'] == ticker_upper].sort_values(by='timestamp', ascending=False)
        st.dataframe(ticker_df[['timestamp', 'score', 'url']].reset_index(drop=True))

if __name__ == "__main__":
    main()