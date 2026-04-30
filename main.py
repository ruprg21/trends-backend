from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
from datetime import datetime, timedelta

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# --- Cache ---
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

SERPAPI_KEY = os.environ.get("SERPAPI_KEY")

MONTHS = ["Jan","Feb","Mar","Apr","May","Jun",
          "Jul","Aug","Sep","Oct","Nov","Dec"]

def to_12_months(lst):
    if not lst:
        return [0] * 12
    if len(lst) >= 12:
        chunk = len(lst) // 12
        result = []
        for i in range(12):
            slice_ = lst[i * chunk:(i + 1) * chunk]
            result.append(int(sum(slice_) / len(slice_)) if slice_ else 0)
        return result
    return lst + [0] * (12 - len(lst))


@app.get("/trends")
async def get_trends(keyword: str):
    if not SERPAPI_KEY:
        raise HTTPException(status_code=500, detail="SERPAPI_KEY not set")

    cached = get_cached(keyword)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=30) as client:

            # 1. Interest over time
            iot_resp = await client.get("https://serpapi.com/search", params={
                "engine":   "google_trends",
                "q":        keyword,
                "data_type": "TIMESERIES",
                "date":     "today 12-m",
                "api_key":  SERPAPI_KEY,
            })
            iot_data = iot_resp.json()
            timeline = iot_data.get("interest_over_time", {}).get("timeline_data", [])
            raw_interest = [
                item["values"][0]["extracted_value"]
                for item in timeline
                if item.get("values")
            ]
            interest = to_12_months(raw_interest)

            # 2. Related queries
            rq_resp = await client.get("https://serpapi.com/search", params={
                "engine":   "google_trends",
                "q":        keyword,
                "data_type": "RELATED_QUERIES",
                "date":     "today 12-m",
                "api_key":  SERPAPI_KEY,
            })
            rq_data = rq_resp.json()
            related  = rq_data.get("related_queries", {})
            rising   = [r["query"] for r in related.get("rising",  [])[:4]]
            top      = [r["query"] for r in related.get("top",     [])[:6]]

            # 3. Related topics
            rt_resp = await client.get("https://serpapi.com/search", params={
                "engine":   "google_trends",
                "q":        keyword,
                "data_type": "RELATED_TOPICS",
                "date":     "today 12-m",
                "api_key":  SERPAPI_KEY,
            })
            rt_data  = rt_resp.json()
            topics   = rt_data.get("related_topics", {})
            trending = [t["topic"]["title"] for t in topics.get("rising", [])[:4]]

        # Peak month & YoY
        peak_idx   = interest.index(max(interest)) if any(interest) else 0
        peak_month = MONTHS[min(peak_idx, 11)]

        try:
            first_half  = sum(interest[:6]) / 6 or 1
            second_half = sum(interest[6:]) / 6
            yoy         = round(((second_half - first_half) / first_half) * 100)
            trend_str   = f"+{yoy}% vs last year" if yoy >= 0 else f"{yoy}% vs last year"
        except:
            trend_str = "N/A"

        result = {
            "interest":     interest,
            "searchVolume": "Live data (relative scale 0–100)",
            "trend":        trend_str,
            "peakMonth":    peak_month,
            "adjacent":     top,
            "rising":       rising,
            "trendingNow":  trending,
        }

        set_cached(keyword, result)
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
