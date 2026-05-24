#!/usr/bin/env python3
"""
Generates a professional HTML dashboard from analysis data.
Input:  .tmp/{slug}/analysis.json
Output: .tmp/{slug}/dashboard.html  (auto-opens in browser)
Usage:  python tools/generate_dashboard.py --query "LM Studio"
"""

import os
import sys
import json
import re
import argparse
import webbrowser
from datetime import datetime


def make_slug(query: str) -> str:
    slug = query.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug or "query"


def fmt_views(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def fmt_duration(seconds):
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}ч {m}м"
    return f"{m}м {s:02d}с"


def published_relative(dt_str):
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        delta = datetime.now(dt.tzinfo) - dt
        days = delta.days
        if days == 0:
            return "сегодня"
        if days == 1:
            return "вчера"
        return f"{days}д назад"
    except Exception:
        return dt_str[:10]


def extract_category(search_query: str) -> str:
    """Derive a clean category name from the raw search query string."""
    # Strip year patterns like '2026', 'tutorial', 'review', 'beginners guide'
    clean = re.sub(r"\b(20\d\d|tutorial|review|beginners?|guide|how to use)\b", "", search_query, flags=re.IGNORECASE)
    clean = re.sub(r"\s+", " ", clean).strip().title()
    return clean or search_query


def build_html(data: dict, query: str) -> str:
    stats = data["stats"]
    ai = data.get("ai_insights", {})
    top_videos = data.get("top_videos", [])
    top_channels = data.get("top_channels", [])
    duration_dist = data.get("duration_distribution", {})
    title_keywords = data.get("title_keywords", [])
    query_perf = data.get("query_performance", {})
    engagement = data.get("engagement_data", [])
    generated_at = data.get("generated_at", "")[:10]
    days_back = data.get("days_back", 7)

    # Dynamic categories from actual search queries
    cat_map: dict[str, str] = {}
    for v in top_videos:
        sq = v.get("search_query", "")
        if sq and sq not in cat_map:
            cat_map[sq] = extract_category(sq)

    all_cats = sorted(set(cat_map.values()))

    # Chart data
    keyword_labels = json.dumps([kw[0] for kw in title_keywords[:15]])
    keyword_values = json.dumps([kw[1] for kw in title_keywords[:15]])
    dur_labels = json.dumps(list(duration_dist.keys()))
    dur_values = json.dumps(list(duration_dist.values()))
    query_labels = json.dumps(list(query_perf.keys()))
    query_views = json.dumps([q["avg_views"] for q in query_perf.values()])
    ch_labels = json.dumps([c["channel_title"][:25] for c in top_channels[:8]])
    ch_views = json.dumps([c["total_views_in_dataset"] for c in top_channels[:8]])

    # Category filter buttons
    cat_buttons = '<button class="cat-btn active" data-cat="all">Все</button>\n'
    for cat in all_cats:
        cat_buttons += f'<button class="cat-btn" data-cat="{cat}">{cat}</button>\n'

    # Video cards (top 50)
    video_cards = ""
    for i, v in enumerate(top_videos[:50]):
        rank = i + 1
        thumb = v.get("thumbnail_url", "")
        title = v["title"].replace('"', "&quot;").replace("<", "&lt;")
        channel = v["channel_title"].replace("<", "&lt;")
        views = fmt_views(v["view_count"])
        likes = fmt_views(v["like_count"])
        comments = fmt_views(v["comment_count"])
        duration = fmt_duration(v["duration_seconds"])
        pub = published_relative(v["published_at"])
        sq = v.get("search_query", "")
        cat = cat_map.get(sq, extract_category(sq))
        vid_url = f"https://youtube.com/watch?v={v['video_id']}"

        video_cards += f"""
        <a href="{vid_url}" target="_blank" class="video-card" data-cat="{cat}" style="text-decoration:none;">
          <div class="rank-badge">#{rank}</div>
          <img src="{thumb}" alt="thumb" loading="lazy" onerror="this.style.display='none'">
          <div class="card-body">
            <div class="card-title">{title}</div>
            <div class="card-channel">{channel}</div>
            <div class="card-meta">
              <span class="meta-pill views">👁 {views}</span>
              <span class="meta-pill likes">👍 {likes}</span>
              <span class="meta-pill comments">💬 {comments}</span>
              <span class="meta-pill dur">⏱ {duration}</span>
              <span class="meta-pill date">📅 {pub}</span>
            </div>
            <div class="card-query">{cat}</div>
          </div>
        </a>"""

    # Channel rows
    channel_rows = ""
    for i, c in enumerate(top_channels):
        rank = i + 1
        thumb = c.get("thumbnail_url", "")
        name = c["channel_title"].replace("<", "&lt;")
        subs = fmt_views(c["subscriber_count"])
        views = fmt_views(c["total_views_in_dataset"])
        vids = c["video_count_in_dataset"]
        ch_url = f"https://youtube.com/channel/{c['channel_id']}"
        img_html = f'<img src="{thumb}" class="ch-thumb" onerror="this.style.display=\'none\'">' if thumb else ""
        channel_rows += f"""<tr>
          <td>{rank}</td>
          <td><a href="{ch_url}" target="_blank" class="ch-link">{img_html} {name}</a></td>
          <td>{subs}</td>
          <td class="highlight">{views}</td>
          <td>{vids}</td>
        </tr>"""

    # AI insight cards
    insights_html = "".join(
        f'<div class="insight-card"><span class="insight-icon">💡</span>{ins}</div>'
        for ins in ai.get("key_insights", [])
    )
    gaps_html = "".join(
        f'<div class="gap-card"><span>🎯</span>{gap}</div>'
        for gap in ai.get("content_gaps", [])
    )
    patterns_html = "".join(
        f'<div class="pattern-card">📝 {p}</div>'
        for p in ai.get("viral_title_patterns", [])
    )
    ideas_html = "".join(
        f'<div class="idea-card">🚀 {idea}</div>'
        for idea in ai.get("content_ideas", [])
    )
    topics_html = " ".join(f'<span class="topic-tag">{t}</span>' for t in ai.get("top_topics", []))
    formats_html = " ".join(f'<span class="format-tag">{f}</span>' for f in ai.get("content_formats", []))

    # Engagement table
    eng_rows = ""
    for e in engagement[:10]:
        rate_color = "#10b981" if e["rate"] > 5 else "#f59e0b" if e["rate"] > 2 else "#6b7280"
        eng_rows += f"""<tr>
          <td class="eng-title">{e['title'][:60]}…</td>
          <td>{e['channel_title'][:22]}</td>
          <td>{fmt_views(e['views'])}</td>
          <td style="color:{rate_color};font-weight:600">{e['rate']:.2f}%</td>
        </tr>"""

    top_channel_name = top_channels[0]["channel_title"][:18] if top_channels else "N/A"
    top_topic = ai.get("top_topics", ["N/A"])[0] if ai.get("top_topics") else "N/A"

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>YouTube Research: {query}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#0a0e1a;--surface:#111827;--surface2:#1a2236;--border:#1f2d45;
  --accent:#6366f1;--accent2:#8b5cf6;--green:#10b981;--yellow:#f59e0b;
  --text:#e2e8f0;--text2:#94a3b8;--text3:#64748b;
}}
body{{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);line-height:1.6}}

.header{{
  background:linear-gradient(135deg,#0f172a 0%,#1e1b4b 50%,#0f172a 100%);
  border-bottom:1px solid var(--border);
  padding:28px 40px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px
}}
.header-left h1{{
  font-size:1.75rem;font-weight:800;
  background:linear-gradient(135deg,#818cf8,#c084fc);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent
}}
.header-left p{{color:var(--text2);font-size:.875rem;margin-top:4px}}
.header-badge{{background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:10px 20px;text-align:center}}
.header-badge .badge-val{{font-size:1.5rem;font-weight:700;color:var(--accent)}}
.header-badge .badge-label{{font-size:.7rem;color:var(--text3);text-transform:uppercase;letter-spacing:.05em}}

.container{{max-width:1400px;margin:0 auto;padding:32px 40px}}
.section-title{{font-size:1.1rem;font-weight:700;color:var(--text);margin-bottom:20px;padding-bottom:10px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px}}

.stats-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:36px}}
.stat-card{{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:20px 24px;position:relative;overflow:hidden}}
.stat-card::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--accent),var(--accent2))}}
.stat-label{{font-size:.75rem;color:var(--text3);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}}
.stat-value{{font-size:2rem;font-weight:800}}
.stat-sub{{font-size:.8rem;color:var(--text2);margin-top:4px}}

.summary-card{{background:linear-gradient(135deg,#1e1b4b 0%,#1a2236 100%);border:1px solid #312e81;border-radius:14px;padding:24px 28px;margin-bottom:36px}}
.summary-card p{{font-size:1.05rem;line-height:1.7}}

.charts-grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px}}
.chart-card{{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:24px}}
.chart-title{{font-size:.85rem;font-weight:600;color:var(--text2);text-transform:uppercase;letter-spacing:.05em;margin-bottom:20px}}

.topic-tag{{display:inline-block;border-radius:20px;padding:4px 14px;font-size:.8rem;font-weight:500;margin:3px;background:rgba(99,102,241,.15);border:1px solid rgba(99,102,241,.3);color:#818cf8}}
.format-tag{{display:inline-block;border-radius:20px;padding:4px 14px;font-size:.8rem;font-weight:500;margin:3px;background:rgba(139,92,246,.15);border:1px solid rgba(139,92,246,.3);color:#a78bfa}}

.cat-filters{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px}}
.cat-btn{{padding:7px 18px;border-radius:22px;border:1px solid var(--border);background:var(--surface2);color:var(--text2);font-family:'Inter',sans-serif;font-size:.85rem;font-weight:500;cursor:pointer;transition:all .2s}}
.cat-btn:hover{{border-color:var(--accent);color:var(--accent)}}
.cat-btn.active{{background:var(--accent);border-color:var(--accent);color:#fff;box-shadow:0 0 16px rgba(99,102,241,.35)}}

.video-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:18px;margin-bottom:36px}}
.video-card{{background:var(--surface);border:1px solid var(--border);border-radius:14px;overflow:hidden;transition:transform .2s,border-color .2s;position:relative;display:block}}
.video-card:hover{{transform:translateY(-4px);border-color:var(--accent)}}
.video-card.hidden{{display:none}}
.rank-badge{{position:absolute;top:10px;left:10px;background:rgba(99,102,241,.9);color:#fff;font-weight:700;font-size:.8rem;border-radius:8px;padding:3px 10px;z-index:1}}
.video-card img{{width:100%;height:180px;object-fit:cover;display:block;background:var(--surface2)}}
.card-body{{padding:14px}}
.card-title{{font-size:.875rem;font-weight:600;color:var(--text);margin-bottom:5px;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
.card-channel{{font-size:.78rem;color:var(--accent);margin-bottom:8px;font-weight:500}}
.card-meta{{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:6px}}
.meta-pill{{font-size:.7rem;padding:2px 7px;border-radius:12px;font-weight:500}}
.meta-pill.views{{background:rgba(99,102,241,.15);color:#818cf8}}
.meta-pill.likes{{background:rgba(16,185,129,.12);color:#34d399}}
.meta-pill.comments{{background:rgba(245,158,11,.12);color:#fbbf24}}
.meta-pill.dur{{background:rgba(100,116,139,.15);color:var(--text2)}}
.meta-pill.date{{background:rgba(100,116,139,.1);color:var(--text3)}}
.card-query{{font-size:.68rem;color:var(--text3);font-style:italic}}

.insights-grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:36px}}
.insights-col{{display:flex;flex-direction:column;gap:12px}}
.insight-card{{background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--green);border-radius:10px;padding:14px 18px;font-size:.9rem;display:flex;gap:10px;align-items:flex-start}}
.gap-card{{background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--yellow);border-radius:10px;padding:14px 18px;font-size:.9rem;display:flex;gap:10px}}
.pattern-card{{background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:12px 16px;font-size:.875rem;font-style:italic}}
.idea-card{{background:rgba(99,102,241,.08);border:1px solid rgba(99,102,241,.2);border-radius:10px;padding:12px 16px;font-size:.875rem;color:var(--text)}}

.table-wrap{{overflow-x:auto;margin-bottom:36px}}
table{{width:100%;border-collapse:collapse;font-size:.875rem}}
th{{background:var(--surface2);color:var(--text2);font-weight:600;padding:12px 16px;text-align:left;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--border)}}
td{{padding:12px 16px;border-bottom:1px solid var(--border);color:var(--text);vertical-align:middle}}
tr:hover td{{background:rgba(99,102,241,.04)}}
.highlight{{color:var(--accent);font-weight:600}}
.ch-link{{display:flex;align-items:center;gap:10px;color:var(--text);text-decoration:none}}
.ch-link:hover{{color:var(--accent)}}
.ch-thumb{{width:32px;height:32px;border-radius:50%;object-fit:cover}}
.eng-title{{color:var(--text2);font-size:.8rem}}

.footer{{text-align:center;padding:32px;color:var(--text3);font-size:.8rem;border-top:1px solid var(--border)}}
@media(max-width:900px){{.container{{padding:20px}}.charts-grid,.insights-grid{{grid-template-columns:1fr}}.header{{padding:20px}}}}
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <h1>🔍 YouTube Research: {query}</h1>
    <p>Последние {days_back} дней &nbsp;·&nbsp; Создано {generated_at}</p>
  </div>
  <div style="display:flex;gap:12px;flex-wrap:wrap">
    <div class="header-badge">
      <div class="badge-val">{data['total_videos_analyzed']}</div>
      <div class="badge-label">Видео</div>
    </div>
    <div class="header-badge">
      <div class="badge-val">{fmt_views(stats['total_views'])}</div>
      <div class="badge-label">Просмотры</div>
    </div>
    <div class="header-badge">
      <div class="badge-val">{stats['total_channels']}</div>
      <div class="badge-label">Каналов</div>
    </div>
  </div>
</div>

<div class="container">

  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-label">Средние просмотры</div>
      <div class="stat-value">{fmt_views(stats['avg_views'])}</div>
      <div class="stat-sub">на видео</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Средняя длина</div>
      <div class="stat-value">{stats['avg_duration_minutes']}м</div>
      <div class="stat-sub">в среднем</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Оптимальная длина</div>
      <div class="stat-value" style="font-size:1.1rem">{ai.get('optimal_video_length','N/A')}</div>
      <div class="stat-sub">по топ-перформерам</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Топ канал</div>
      <div class="stat-value" style="font-size:1rem">{top_channel_name}</div>
      <div class="stat-sub">больше всего просмотров</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Главный тренд</div>
      <div class="stat-value" style="font-size:1rem">{top_topic}</div>
      <div class="stat-sub">тема #1</div>
    </div>
  </div>

  <div class="section-title">🧠 Исполнительное резюме</div>
  <div class="summary-card"><p>{ai.get('summary','—')}</p></div>

  <div class="section-title">🏷️ Топ темы и форматы</div>
  <div class="chart-card" style="margin-bottom:20px">
    <div style="margin-bottom:16px">
      <div class="chart-title">Топ темы</div>
      <div>{topics_html}</div>
    </div>
    <div>
      <div class="chart-title">Форматы контента</div>
      <div>{formats_html}</div>
    </div>
  </div>

  <div class="charts-grid" style="margin-bottom:20px">
    <div class="chart-card">
      <div class="chart-title">🔑 Частые слова в заголовках</div>
      <canvas id="keywordChart" height="260"></canvas>
    </div>
    <div class="chart-card">
      <div class="chart-title">⏱️ Распределение по длительности</div>
      <canvas id="durationChart" height="260"></canvas>
    </div>
  </div>
  <div class="charts-grid" style="margin-bottom:36px">
    <div class="chart-card">
      <div class="chart-title">🔍 Средние просмотры по запросу</div>
      <canvas id="queryChart" height="260"></canvas>
    </div>
    <div class="chart-card">
      <div class="chart-title">📺 Топ каналы (эта неделя)</div>
      <canvas id="channelChart" height="260"></canvas>
    </div>
  </div>

  <div class="section-title">💡 Стратегические инсайты и возможности</div>
  <div class="insights-grid" style="margin-bottom:36px">
    <div>
      <div class="chart-title" style="margin-bottom:12px">КЛЮЧЕВЫЕ ИНСАЙТЫ</div>
      <div class="insights-col">{insights_html}</div>
      <div class="chart-title" style="margin:20px 0 10px">ИДЕИ ДЛЯ ВИДЕО</div>
      <div class="insights-col">{ideas_html}</div>
    </div>
    <div>
      <div class="chart-title" style="margin-bottom:12px">ПРОБЕЛЫ В КОНТЕНТЕ</div>
      <div class="insights-col">{gaps_html}</div>
      <div class="chart-title" style="margin:16px 0 10px">ВИРУСНЫЕ ШАБЛОНЫ ЗАГОЛОВКОВ</div>
      <div class="insights-col">{patterns_html}</div>
    </div>
  </div>

  <div class="section-title">🏆 Топ 50 видео этой недели</div>
  <div class="cat-filters">{cat_buttons}</div>
  <div class="video-grid" id="videoGrid">{video_cards}</div>

  <div class="section-title">📺 Таблица лидеров каналов</div>
  <div class="table-wrap" style="margin-bottom:36px">
    <table>
      <thead><tr><th>#</th><th>Канал</th><th>Подписчики</th><th>Просмотры (неделя)</th><th>Видео найдено</th></tr></thead>
      <tbody>{channel_rows}</tbody>
    </table>
  </div>

  <div class="section-title">⚡ Видео с наибольшей вовлечённостью</div>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Название</th><th>Канал</th><th>Просмотры</th><th>Вовлечённость</th></tr></thead>
      <tbody>{eng_rows}</tbody>
    </table>
  </div>

</div>

<div class="footer">YouTube Research Dashboard &nbsp;·&nbsp; {generated_at} &nbsp;·&nbsp; YouTube Data API v3 + OpenAI</div>

<script>
Chart.defaults.color='#94a3b8';
Chart.defaults.font.family='Inter';
const gc='rgba(31,45,69,0.8)';
function grad(ctx,c1,c2){{const g=ctx.createLinearGradient(0,0,0,300);g.addColorStop(0,c1);g.addColorStop(1,c2);return g}}

new Chart(document.getElementById('keywordChart').getContext('2d'),{{
  type:'bar',
  data:{{labels:{keyword_labels},datasets:[{{data:{keyword_values},
    backgroundColor:(ctx)=>grad(ctx.chart.ctx,'rgba(99,102,241,0.85)','rgba(139,92,246,0.35)'),
    borderColor:'rgba(99,102,241,0.9)',borderWidth:1,borderRadius:5}}]}},
  options:{{responsive:true,plugins:{{legend:{{display:false}}}},
    scales:{{x:{{ticks:{{maxRotation:45}},grid:{{color:gc}}}},y:{{grid:{{color:gc}}}}}}}}
}});

new Chart(document.getElementById('durationChart').getContext('2d'),{{
  type:'doughnut',
  data:{{labels:{dur_labels},datasets:[{{data:{dur_values},
    backgroundColor:['#6366f1','#8b5cf6','#a78bfa','#c4b5fd','#ddd6fe'],
    borderColor:'#111827',borderWidth:3,hoverOffset:6}}]}},
  options:{{responsive:true,cutout:'60%',plugins:{{legend:{{position:'bottom',labels:{{padding:14,font:{{size:12}}}}}}}}}}
}});

new Chart(document.getElementById('queryChart').getContext('2d'),{{
  type:'bar',
  data:{{labels:{query_labels},datasets:[{{label:'Средние просмотры',data:{query_views},
    backgroundColor:(ctx)=>grad(ctx.chart.ctx,'rgba(16,185,129,0.85)','rgba(16,185,129,0.2)'),
    borderColor:'#10b981',borderWidth:1,borderRadius:5}}]}},
  options:{{indexAxis:'y',responsive:true,plugins:{{legend:{{display:false}}}},
    scales:{{x:{{grid:{{color:gc}}}},y:{{ticks:{{font:{{size:11}}}},grid:{{color:gc}}}}}}}}
}});

new Chart(document.getElementById('channelChart').getContext('2d'),{{
  type:'bar',
  data:{{labels:{ch_labels},datasets:[{{data:{ch_views},
    backgroundColor:(ctx)=>grad(ctx.chart.ctx,'rgba(245,158,11,0.85)','rgba(245,158,11,0.2)'),
    borderColor:'#f59e0b',borderWidth:1,borderRadius:5}}]}},
  options:{{indexAxis:'y',responsive:true,plugins:{{legend:{{display:false}}}},
    scales:{{x:{{grid:{{color:gc}}}},y:{{ticks:{{font:{{size:11}}}},grid:{{color:gc}}}}}}}}
}});

// Category filter
const btns=document.querySelectorAll('.cat-btn');
const cards=document.querySelectorAll('#videoGrid .video-card');
btns.forEach(btn=>{{
  btn.addEventListener('click',()=>{{
    btns.forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    const cat=btn.dataset.cat;
    cards.forEach(card=>{{
      card.classList.toggle('hidden', cat!=='all' && card.dataset.cat!==cat);
    }});
  }});
}});
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate HTML dashboard for a keyword")
    parser.add_argument("--query", required=True, help='Topic keyword, e.g. "LM Studio"')
    args = parser.parse_args()

    slug = make_slug(args.query)
    in_path = os.path.join(".tmp", slug, "analysis.json")

    if not os.path.exists(in_path):
        print(f"[ERROR] {in_path} not found. Run analyze_trends.py first.")
        sys.exit(1)

    with open(in_path, encoding="utf-8") as f:
        data = json.load(f)

    print(f'Generating dashboard for "{args.query}"...')
    html = build_html(data, args.query)

    out_path = os.path.join(".tmp", slug, "dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    abs_path = os.path.abspath(out_path)
    print(f"Dashboard saved -> {abs_path}")
    webbrowser.open(f"file:///{abs_path.replace(chr(92), '/')}")


if __name__ == "__main__":
    main()
