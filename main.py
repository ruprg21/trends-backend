from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pytrends.request import TrendReq
import pandas as pd
import time
import random
from datetime import datetime, timedelta

app = FastAPI()

# --- Simple in-memory cache ---
cache = {}
CACHE_TTL = timedelta(hours=24)

def get_cached(keyword):
    key = keyword.lower().strip()
    if key in cache:
        data, timestamp = cache[key]
        if datetime.now() - timestamp < CACHE_TTL:
            return data
    return None

def set_cached(keyword, data):
    cache[keyword.lower().strip()] = (data, datetime.now())

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

@app.get("/trends")
def get_trends(keyword: str):
    # Return cached result if available
    cached = get_cached(keyword)
    if cached:
        return cached

    try:
        pt = TrendReq(
            hl="en-US",
            tz=360,
            timeout=(10, 25),
            retries=3,
            backoff_factor=0.5,
        )
        time.sleep(random.uniform(1.5, 3.0))  # polite delay

        # Interest over time (last 12 months)
        pt.build_payload([keyword], timeframe="today 12-m")
        iot = pt.interest_over_time()
        interest = (
            iot[keyword].tolist() if not iot.empty else [0] * 12
        )

        # Downsample to 12 buckets safely
        if len(interest) == 0:
            interest = [0] * 12
        elif len(interest) > 12:
            chunk = len(interest) // 12
            interest = [
                int(sum(interest[i*chunk:(i+1)*chunk]) / max(chunk, 1))
                for i in range(12)
            ]
        elif len(interest) < 12:
            # Pad with zeros if too short
            interest += [0] * (12 - len(interest))

        # Related queries
        pt.build_payload([keyword], timeframe="today 12-m")
        related = pt.related_queries()
        kw_data = related.get(keyword, {})

        def extract(df):
            if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                return []
            return df["query"].tolist()

        rising = extract(kw_data.get("rising"))
        top    = extract(kw_data.get("top"))

        # Related topics
        pt.build_payload([keyword], timeframe="today 12-m")
        topics = pt.related_topics()
        t_data = topics.get(keyword, {})
        top_topics = []
        if isinstance(t_data.get("top"), pd.DataFrame):
            top_topics = t_data["top"]["topic_title"].tolist()[:6]

        # Peak month
        peak_idx = interest.index(max(interest)) if any(interest) else 0
        months = ["Jan","Feb","Mar","Apr","May","Jun",
                  "Jul","Aug","Sep","Oct","Nov","Dec"]
        peak_month = months[peak_idx % 12]

        # Simple YoY trend
        if len(interest) >= 12:
            first_half  = sum(interest[:6]) / 6 or 1
            second_half = sum(interest[6:]) / 6
            yoy = round(((second_half - first_half) / first_half) * 100)
            trend_str = f"+{yoy}% vs last year" if yoy >= 0 else f"{yoy}% vs last year"
        else:
            trend_str = "N/A"

        result = {
            "interest":     interest,
            "searchVolume": "Live data (relative scale 0–100)",
            "trend":        trend_str,
            "peakMonth":    peak_month,
            "adjacent":     top[:6],
            "rising":       rising[:4],
            "trendingNow":  top[:4],
        }

        set_cached(keyword, result)
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
