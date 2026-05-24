# Workflow: YouTube Niche Analysis (AI/Automation)

## Objective
Collect ~100 videos from the last 7 days in the AI/automation niche, analyze trends with OpenAI, generate a professional HTML dashboard, and deliver it via email and browser.

## Inputs
- `.env` with `YOUTUBE_API_KEY` and `OPENAI_API_KEY`
- `credentials.json` for Gmail OAuth (generated on first run)
- `--days` (default: 7) — lookback window
- `--max_videos` (default: 100) — cap on videos to analyze

## Search Topics
The following queries target the user's niche specifically:
```
Claude Code
Claude Code YouTube automation
Claude Code automation tutorial
NotebookLM tutorial 2025
Claude Code NotebookLM
AI agents 2025
new AI tools 2025
free AI models access 2025
Ollama automation tutorial
LM Studio local AI 2025
```

## Pipeline Steps

### Step 1 — Fetch YouTube Data
**Tool:** `tools/fetch_youtube_data.py`
- Uses YouTube Data API v3
- Searches each query (10 queries × ~10 results = ~100 unique videos)
- Deduplicates by video ID
- Fetches full metadata: views, likes, comments, duration, tags, thumbnails
- Fetches channel stats: subscribers, total views, video count
- **Quota cost:** ~1,100 units (10 searches × 100 + ~100 video lookups + channel batch)
- **Output:** `.tmp/youtube_data.json`

### Step 2 — Analyze Trends
**Tool:** `tools/analyze_trends.py`
- Computes engagement rates, duration distributions, keyword frequencies
- Sends top 30 videos to OpenAI GPT-4o-mini for strategic insights
- **Output:** `.tmp/analysis.json`

### Step 3 — Generate Dashboard
**Tool:** `tools/generate_dashboard.py`
- Reads `.tmp/analysis.json`
- Generates a single self-contained HTML file with Chart.js charts
- Auto-opens in default browser
- **Output:** `.tmp/dashboard.html`

### Step 4 — Send Email
**Tool:** `tools/send_gmail.py`
- Attaches `.tmp/dashboard.html` and sends as HTML email body
- Requires Gmail OAuth2 (one-time browser auth, token cached in `token.json`)
- **Output:** Email to `musicboxer@gmail.com`

### Full Run (All Steps)
```bash
python tools/run_analysis.py
```

## Quota Budget (10,000 units/day)
| Operation | Count | Units |
|---|---|---|
| search.list | 10 queries | 1,000 |
| videos.list (batch) | 2 calls | 2 |
| channels.list (batch) | 2 calls | 2 |
| **Total** | | **~1,004** |

Leaves ~9,000 units for additional runs or manual queries.

## Error Handling
- **Quota exceeded:** Script prints quota error and exits cleanly. Re-run after midnight PT.
- **OpenAI rate limit:** analyze_trends.py uses gpt-4o-mini with single call — minimal risk.
- **Gmail auth failure:** Delete `token.json` and re-run `send_gmail.py` to re-authenticate.
- **No videos found:** If search returns 0 results, check API key validity and quota.

## Outputs
| File | Description |
|---|---|
| `.tmp/youtube_data.json` | Raw video + channel data |
| `.tmp/analysis.json` | Trends, stats, AI insights |
| `.tmp/dashboard.html` | Final HTML dashboard |

## Scheduling (Future)
To run weekly automatically, use Windows Task Scheduler or a cron job:
```bash
python "c:\Users\natin\Desktop\ClaudeTest\YT Analyses\tools\run_analysis.py"
```
