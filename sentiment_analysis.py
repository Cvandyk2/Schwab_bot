import os
import re
import spacy
import pandas as pd
from edgar import Company, set_identity
set_identity("Name and Email")
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from datetime import datetime

# === Tip Jar ===
"https://www.paypal.com/paypalme/chancevandyke"

# Initialize spacy and Vader once globally
nlp = spacy.load("en_core_web_sm")
vader = SentimentIntensityAnalyzer()

# Define events and keywords for 8-K event detection
EVENTS = {
    "Executive Changes": ["resigned", "appointed", "left the company", "terminated"],
    "Financial Updates": ["earnings", "guidance", "profit warning", "quarterly report"],
    "Mergers and Acquisitions": ["acquisition", "merger", "purchase", "sale"],
    "Litigation": ["lawsuit", "filed suit", "settled"],
    "Bankruptcy": ["bankruptcy", "chapter 11", "restructure"],
    "Product Announcements": ["product launch", "new product", "discontinued"],
    "Regulatory Changes": ["regulation", "compliance", "fined", "penalty"],
}

def extract_8k_events(text, events_dict=EVENTS):
    detected_events = set()
    text_lower = text.lower()
    for event_type, keywords in events_dict.items():
        if any(keyword in text_lower for keyword in keywords):
            detected_events.add(event_type)
    return list(detected_events)

def adjust_sentiment_for_8k_events(text, events, base_sentiment):
    sentiment_adjustment = 0
    text_lower = text.lower()
    reason_lines = []

    for event in events:
        if event == "Executive Changes":
            sentiment_adjustment -= 0.3
            reason_lines.append(f"Event '{event}' detected: subtract 0.3")
        elif event == "Bankruptcy":
            sentiment_adjustment -= 0.7
            reason_lines.append(f"Event '{event}' detected: subtract 0.7")
        elif event == "Financial Updates":
            if "profit warning" in text_lower or "missed" in text_lower:
                sentiment_adjustment -= 0.4
                reason_lines.append(f"Event '{event}' with negative terms detected: subtract 0.4")
            else:
                sentiment_adjustment += 0.2
                reason_lines.append(f"Event '{event}' detected with positive tone: add 0.2")
        elif event == "Mergers and Acquisitions":
            sentiment_adjustment += 0.5
            reason_lines.append(f"Event '{event}' detected: add 0.5")
        elif event == "Litigation":
            sentiment_adjustment -= 0.4
            reason_lines.append(f"Event '{event}' detected: subtract 0.4")
        elif event == "Product Announcements":
            sentiment_adjustment += 0.3
            reason_lines.append(f"Event '{event}' detected: add 0.3")
        elif event == "Regulatory Changes":
            sentiment_adjustment -= 0.3
            reason_lines.append(f"Event '{event}' detected: subtract 0.3")

    final_sentiment = base_sentiment["compound"] + sentiment_adjustment
    final_sentiment = max(min(final_sentiment, 1), -1)

    reason = (
        f"Base compound sentiment: {base_sentiment['compound']:.3f}. "
        f"Adjustments: {'; '.join(reason_lines)}. "
        f"Final sentiment: {final_sentiment:.3f}."
    )
    return final_sentiment, reason

def analyze_sentiment(text):
    base_sentiment = vader.polarity_scores(text)
    events = extract_8k_events(text)
    adjusted_sentiment, reason = adjust_sentiment_for_8k_events(text, events, base_sentiment)
    return adjusted_sentiment, reason

def clean_filing_text(filing_text):
    clean_text = re.sub(r"[^\w\s,.()\'\"\-]", "", filing_text)
    clean_text = re.sub(r"-{2,}", "", clean_text)
    clean_text = re.sub(r"\s+", " ", clean_text).strip()
    return clean_text

def get_tickers_from_file(filepath):
    with open(filepath, "r") as f:
        tickers = [line.strip().upper() for line in f if line.strip()]
    return tickers

def load_ticker_cik_mapping_from_file(filepath):
    mapping = {}
    with open(filepath, "r") as f:
        for line in f:
            parts = line.strip().split("\t")  # tab-delimited
            if len(parts) != 2:
                continue
            ticker, cik = parts
            mapping[ticker.upper()] = cik.zfill(10)  # pad CIK to 10 digits
    return mapping

def get_8k_filings(tickers, ticker_cik_map):
    ticker_news = []
    for ticker in tickers:
        cik = ticker_cik_map.get(ticker)
        if not cik:
            print(f"ERROR: No CIK found for ticker: {ticker}")
            continue

        try:
            company = Company(cik)
            filings = company.get_filings(form="8-K")
            latest_filing = filings.latest(1)
        except Exception as e:
            print(f"Failed to get filings for {ticker}: {e}")
            continue

        if not latest_filing:
            print(f"Warning: No 8-K filings found for {ticker}")
            continue

        filing_obj = latest_filing.obj()
        filing_text = str(filing_obj)
        clean_text = clean_filing_text(filing_text)
        sentiment, sentiment_reason = analyze_sentiment(clean_text)

        date_match = re.search(
            r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b",
            filing_text,
        )
        filing_date = (
            datetime.strptime(date_match.group(), "%B %d, %Y").date()
            if date_match
            else datetime.today().date()
        )

        filing_description = getattr(latest_filing, "description", "")

        accession_no = getattr(latest_filing, "accession_no", None)
        if accession_no:
            accession_no_no_dash = accession_no.replace("-", "")
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_no_no_dash}/{accession_no}.txt"
        else:
            filing_url = ""

        retrieved_at = datetime.now().isoformat(timespec='seconds')

        ticker_news.append(
            {
                "ticker": ticker,
                "filing_date": filing_date,
                "news": clean_text,
                "adjusted_8k_sentiment": sentiment,
                "sentiment_reason": sentiment_reason,
                "filing_description": filing_description,
                "filing_url": filing_url,
                "retrieved_at": retrieved_at,
            }
        )
    return pd.DataFrame(ticker_news)

if __name__ == "__main__":
    ticker_file_path = os.path.expanduser("~/.investments/Schwab/Tickers/Tickers.txt")
    ticker_cik_file_path = os.path.expanduser("~/.investments/Schwab/Tickers/Ticker_to_CIK.txt")
    output_folder = os.path.expanduser("~/.investments/Schwab/sentiment_bot/sentiment_output")
    output_file = os.path.join(output_folder, "8k_sentiment_output.csv")

    os.makedirs(output_folder, exist_ok=True)

    print("Reading tickers from file...")
    tickers = get_tickers_from_file(ticker_file_path)
    print(f"Tickers loaded: {tickers}")

    print("Loading ticker to CIK mapping from local file...")
    ticker_cik_map = load_ticker_cik_mapping_from_file(ticker_cik_file_path)
    print(f"Loaded {len(ticker_cik_map)} ticker-CIK mappings")

    print("Fetching and analyzing latest 8-K filings...")
    df = get_8k_filings(tickers, ticker_cik_map)
    print(df)

    df.to_csv(output_file, index=False)
    print(f"✅ Sentiment data saved to: {output_file}")
