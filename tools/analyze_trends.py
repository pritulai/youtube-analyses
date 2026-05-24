#!/usr/bin/env python3
"""
Analyzes YouTube data using statistics + OpenAI to extract strategic insights.
Input:  .tmp/{slug}/youtube_data.json
Output: .tmp/{slug}/analysis.json
Usage:  python tools/analyze_trends.py --query "LM Studio"
"""

import os
import sys
import json
import re
import argparse
from collections import Counter
from dotenv import load_dotenv
import httpx
from openai import OpenAI

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))

_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")


def make_slug(query: str) -> str:
    slug = query.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug or "query"


def extract_title_keywords(titles):
    stop_words = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "are", "was", "were", "how", "what",
        "why", "when", "this", "that", "you", "your", "my", "our", "their",
        "i", "it", "its", "be", "do", "did", "does", "have", "has", "had",
        "will", "would", "can", "could", "should", "use", "using", "used",
        "get", "make", "just", "now", "new", "all", "more", "about", "with",
        "into", "than", "then", "not", "no", "so", "we", "me", "he", "she",
        "they", "him", "her", "up", "out", "if", "its", "as",
    }
    words = []
    for title in titles:
        tokens = re.findall(r"\b[a-zA-Z][a-zA-Z0-9+#]*\b", title)
        words.extend([w.lower() for w in tokens if w.lower() not in stop_words and len(w) > 2])
    return Counter(words).most_common(30)


def analyze_with_openai(client, query: str, top_videos_text: str) -> dict:
    prompt = f"""You are a YouTube content strategist. The topic being analyzed is: "{query}".

Below are the top-performing videos published in the last 7 days on this topic:

{top_videos_text}

Return a JSON object with EXACTLY these keys (no extra text, no markdown):
{{
  "top_topics": ["topic1", "topic2", "topic3", "topic4", "topic5"],
  "content_formats": ["format1", "format2", "format3"],
  "key_insights": [
    "Insight 1 (specific, actionable for a creator in this niche)",
    "Insight 2",
    "Insight 3",
    "Insight 4",
    "Insight 5"
  ],
  "content_gaps": ["Gap 1 — underserved angle", "Gap 2", "Gap 3"],
  "optimal_video_length": "X-Y minutes",
  "viral_title_patterns": [
    "Pattern 1 (e.g. How I used X to do Y in Z minutes)",
    "Pattern 2",
    "Pattern 3"
  ],
  "content_ideas": [
    "Idea 1 — specific video concept based on gaps and top performers",
    "Idea 2",
    "Idea 3",
    "Idea 4",
    "Idea 5"
  ],
  "summary": "2-3 sentence executive summary of what is working in '{query}' content right now and what creators should focus on."
}}"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def main():
    parser = argparse.ArgumentParser(description="Analyze YouTube trends for a keyword")
    parser.add_argument("--query", required=True, help='Topic keyword, e.g. "LM Studio"')
    args = parser.parse_args()

    slug = make_slug(args.query)
    tmp_dir = os.path.join(".tmp", slug)

    in_path = os.path.join(tmp_dir, "youtube_data.json")
    if not os.path.exists(in_path):
        print(f"[ERROR] {in_path} not found. Run fetch_youtube_data.py first.")
        sys.exit(1)

    with open(in_path, encoding="utf-8") as f:
        data = json.load(f)

    videos = data["videos"]
    channels = data["channels"]

    if not videos:
        print("[ERROR] No videos in data file.")
        sys.exit(1)

    print(f'Analyzing {len(videos)} videos for "{args.query}"...\n')

    top_videos = sorted(videos, key=lambda v: v["view_count"], reverse=True)[:30]

    # Engagement rate
    engagement_data = []
    for v in videos:
        if v["view_count"] > 100:
            rate = (v["like_count"] + v["comment_count"]) / v["view_count"] * 100
            engagement_data.append({
                "video_id": v["video_id"],
                "title": v["title"],
                "channel_title": v["channel_title"],
                "rate": round(rate, 3),
                "views": v["view_count"],
                "likes": v["like_count"],
                "comments": v["comment_count"],
                "thumbnail_url": v["thumbnail_url"],
                "published_at": v["published_at"],
            })
    engagement_data.sort(key=lambda x: x["rate"], reverse=True)

    # Duration distribution
    duration_buckets = {
        "Shorts (<1 мин)": 0,
        "1–5 мин": 0,
        "5–15 мин": 0,
        "15–30 мин": 0,
        ">30 мин": 0,
    }
    for v in videos:
        s = v["duration_seconds"]
        if s < 60:
            duration_buckets["Shorts (<1 мин)"] += 1
        elif s < 300:
            duration_buckets["1–5 мин"] += 1
        elif s < 900:
            duration_buckets["5–15 мин"] += 1
        elif s < 1800:
            duration_buckets["15–30 мин"] += 1
        else:
            duration_buckets[">30 мин"] += 1

    # Views by search query
    query_performance = {}
    for v in videos:
        q = v["search_query"] or "other"
        if q not in query_performance:
            query_performance[q] = {"total_views": 0, "video_count": 0, "avg_views": 0}
        query_performance[q]["total_views"] += v["view_count"]
        query_performance[q]["video_count"] += 1
    for q in query_performance:
        n = query_performance[q]["video_count"]
        query_performance[q]["avg_views"] = round(query_performance[q]["total_views"] / n) if n else 0

    # Top channels
    from collections import Counter as _Counter
    channel_views = _Counter()
    channel_video_count = _Counter()
    for v in videos:
        channel_views[v["channel_id"]] += v["view_count"]
        channel_video_count[v["channel_id"]] += 1

    top_channels = []
    for ch_id, total_views in channel_views.most_common(10):
        ch = channels.get(ch_id, {})
        top_channels.append({
            "channel_id": ch_id,
            "channel_title": ch.get("channel_title", ""),
            "subscriber_count": ch.get("subscriber_count", 0),
            "total_views_in_dataset": total_views,
            "video_count_in_dataset": channel_video_count[ch_id],
            "thumbnail_url": ch.get("thumbnail_url", ""),
        })

    title_keywords = extract_title_keywords([v["title"] for v in videos])

    valid_durations = [v["duration_seconds"] for v in videos if v["duration_seconds"] > 0]
    avg_duration = round(sum(valid_durations) / len(valid_durations)) if valid_durations else 0
    total_views = sum(v["view_count"] for v in videos)
    avg_views = round(total_views / len(videos)) if videos else 0

    # OpenAI insights
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[WARN] OPENAI_API_KEY not set — skipping AI analysis.")
        ai_insights = {
            "top_topics": [], "content_formats": [],
            "key_insights": ["OpenAI API key not configured."],
            "content_gaps": [], "content_ideas": [],
            "optimal_video_length": "N/A",
            "viral_title_patterns": [],
            "summary": "AI analysis skipped — no API key.",
        }
    else:
        client = OpenAI(api_key=api_key, http_client=httpx.Client(trust_env=False))
        top_videos_text = "\n".join([
            f'- "{v["title"]}" by {v["channel_title"]} | {v["view_count"]:,} views | '
            f'{v["duration_seconds"] // 60}min | Query: {v["search_query"]}'
            for v in top_videos
        ])
        print("Sending top 30 videos to OpenAI for insights...")
        try:
            ai_insights = analyze_with_openai(client, args.query, top_videos_text)
            print(f"Summary: {ai_insights.get('summary', '')}\n")
        except Exception as e:
            print(f"[ERROR] OpenAI call failed: {e}")
            ai_insights = {
                "summary": f"AI analysis failed: {e}",
                "key_insights": [], "top_topics": [],
                "content_formats": [], "content_gaps": [],
                "content_ideas": [], "viral_title_patterns": [],
                "optimal_video_length": "N/A",
            }

    output = {
        "query": args.query,
        "slug": slug,
        "generated_at": data["fetched_at"],
        "days_back": data.get("days_back", 7),
        "total_videos_analyzed": len(videos),
        "stats": {
            "total_views": total_views,
            "avg_views": avg_views,
            "avg_duration_seconds": avg_duration,
            "avg_duration_minutes": round(avg_duration / 60, 1),
            "total_channels": len(channels),
        },
        "top_videos": [
            {
                "video_id": v["video_id"],
                "title": v["title"],
                "channel_title": v["channel_title"],
                "view_count": v["view_count"],
                "like_count": v["like_count"],
                "comment_count": v["comment_count"],
                "duration_seconds": v["duration_seconds"],
                "published_at": v["published_at"],
                "thumbnail_url": v["thumbnail_url"],
                "search_query": v["search_query"],
            }
            for v in top_videos[:50]
        ],
        "top_channels": top_channels,
        "ai_insights": ai_insights,
        "engagement_data": engagement_data[:15],
        "query_performance": query_performance,
        "title_keywords": title_keywords,
        "duration_distribution": duration_buckets,
    }

    out_path = os.path.join(tmp_dir, "analysis.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Analysis saved -> {out_path}")


if __name__ == "__main__":
    main()
