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

def safe_list(val, fallback=[]):
    try:
        if val is None or not isinstance(val, pd.DataFrame) or val.empty:
            return fallback
        return val.iloc[:, 0].tolist()
    except:
        return fallback

def to_12_months(lst):
    """Safely convert any length list to exactly 12 values."""
    if not lst:
        return [0] * 12
    if len(lst) >= 12:
        chunk = len(lst) // 12
        result = []
        for i in range(12):
            slice_ = lst[i * chunk: (i + 1) * chunk]
            result.append(int(sum(slice_) / len(slice_)) if slice_ else 0)
        return result
    # pad with zeros if shorter than 12
    return lst + [0] * (12 - len(lst))

@app.get("/trends")
def get_trends(keyword: str):
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
        time.sleep(random.uniform(1.5, 3.0))

        # --- Interest over time ---
        pt.build_payload([keyword], timeframe="today 12-m")
        iot = pt.interest_over_time()
        time.sleep(random.uniform(1.0, 2.0))

        if not iot.empty and keyword in iot.columns:
            raw = iot[keyword].tolist()
        else:
            raw = []

        interest = to_12_months(raw)

        # --- Related queries ---
        pt.build_payload([keyword], timeframe="today 12-m")
        related = pt.related_queries()
        time.sleep(random.uniform(1.0, 2.0))

        kw_data = related.get(keyword, {}) or {}

        def extract_queries(df):
            try:
                if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                    return []
                return df["query"].dropna().tolist()
            except:
                return []

        rising = extract_queries(kw_data.get("rising"))
        top    = extract_queries(kw_data.get("top"))

        # --- Related topics ---
        pt.build_payload([keyword], timeframe="today 12-m")
        topics = pt.related_topics()
        time.sleep(random.uniform(1.0, 2.0))

        t_data = topics.get(keyword, {}) or {}
        top_topics = []
        try:
            if isinstance(t_data.get("top"), pd.DataFrame) and not t_data["top"].empty:
                top_topics = t_data["top"]["topic_title"].dropna().tolist()[:6]
        except:
            top_topics = []

        # --- Peak month ---
        months = ["Jan","Feb","Mar","Apr","May","Jun",
                  "Jul","Aug","Sep","Oct","Nov","Dec"]
        peak_idx = interest.index(max(interest)) if any(interest) else 0
        peak_month = months[min(peak_idx, 11)]

        # --- YoY trend ---
        try:
            first_half  = sum(interest[:6]) / 6 or 1
            second_half = sum(interest[6:]) / 6
            yoy = round(((second_half - first_half) / first_half) * 100)
            trend_str = f"+{yoy}% vs last year" if yoy >= 0 else f"{yoy}% vs last year"
        except:
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
