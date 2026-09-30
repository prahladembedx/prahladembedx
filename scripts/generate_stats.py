#!/usr/bin/env python3
"""
Generates stats/github-metrics.svg for a GitHub profile README.

- Runs inside GitHub Actions (see .github/workflows/github-stats.yml)
- Uses only the Python standard library
- Reads GH_TOKEN and GH_USER from environment variables

Local preview without network:  python scripts/generate_stats.py --demo
Blank placeholder card:         python scripts/generate_stats.py --placeholder
"""
import datetime as dt
import html
import json
import math
import os
import sys
import urllib.request

API = "https://api.github.com/graphql"
OUT = os.path.join("stats", "github-metrics.svg")

# Languages you don't want counted (example: ["Jupyter Notebook"])
EXCLUDE_LANGS = []


# ----------------------------------------------------------------- fetching
def gql(query, token):
    req = urllib.request.Request(
        API,
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.load(r)
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


def fetch(login, token):
    today = dt.datetime.now(dt.timezone.utc)
    # first query: account creation date
    created = gql('{ user(login:"%s"){ createdAt } }' % login, token)["user"]["createdAt"]
    created_dt = dt.datetime.fromisoformat(created.replace("Z", "+00:00"))

    year_blocks = []
    for y in range(created_dt.year, today.year + 1):
        start = max(created_dt, dt.datetime(y, 1, 1, tzinfo=dt.timezone.utc))
        end = min(today, dt.datetime(y, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc))
        year_blocks.append(
            f'y{y}: contributionsCollection(from:"{start:%Y-%m-%dT%H:%M:%SZ}", to:"{end:%Y-%m-%dT%H:%M:%SZ}")'
            "{ totalCommitContributions contributionCalendar{ totalContributions "
            "weeks{ contributionDays{ date contributionCount } } } }"
        )

    query = """
    { user(login:"%s"){
        name login createdAt
        pullRequests{ totalCount }
        issues{ totalCount }
        repositoriesContributedTo(first:1, contributionTypes:[COMMIT, ISSUE, PULL_REQUEST, REPOSITORY]){ totalCount }
        repositories(first:100, ownerAffiliations:OWNER, isFork:false, privacy:PUBLIC){
          nodes{ stargazerCount
                 languages(first:10, orderBy:{field:SIZE, direction:DESC}){ edges{ size node{ name color } } } }
        }
        %s
    } }""" % (login, "\n".join(year_blocks))
    u = gql(query, token)["user"]

    stars = sum(r["stargazerCount"] for r in u["repositories"]["nodes"])
    langs = {}
    for r in u["repositories"]["nodes"]:
        for e in r["languages"]["edges"]:
            n = e["node"]["name"]
            if n in EXCLUDE_LANGS:
                continue
            cur = langs.setdefault(n, {"size": 0, "color": e["node"]["color"] or "#8b949e"})
            cur["size"] += e["size"]

    commits, days = 0, {}
    for key, val in u.items():
        if key.startswith("y") and key[1:].isdigit():
            commits += val["totalCommitContributions"]
            for w in val["contributionCalendar"]["weeks"]:
                for d in w["contributionDays"]:
                    days[d["date"]] = d["contributionCount"]

    return {
        "name": u["name"] or u["login"],
        "created": created_dt.date(),
        "stars": stars,
        "commits": commits,
        "prs": u["pullRequests"]["totalCount"],
        "issues": u["issues"]["totalCount"],
        "contributed": u["repositoriesContributedTo"]["totalCount"],
        "langs": langs,
        "days": days,
    }


# ------------------------------------------------------------------ streaks
def streaks(days):
    today = dt.datetime.now(dt.timezone.utc).date()
    items = sorted((dt.date.fromisoformat(d), c) for d, c in days.items())
    items = [(d, c) for d, c in items if d <= today]
    total = sum(c for _, c in items)
    first = next((d for d, c in items if c > 0), None)

    longest = (0, None, None)
    run, run_start, prev = 0, None, None
    for d, c in items:
        if c > 0:
            if run and prev is not None and (d - prev).days == 1:
                run += 1
            else:
                run, run_start = 1, d
            prev = d
            if run > longest[0]:
                longest = (run, run_start, d)
        else:
            run, prev = 0, None

    cmap = dict(items)
    cur_end = today if cmap.get(today, 0) > 0 else today - dt.timedelta(days=1)
    cur, d = 0, cur_end
    while cmap.get(d, 0) > 0:
        cur += 1
        d -= dt.timedelta(days=1)
    cur_start = cur_end - dt.timedelta(days=cur - 1) if cur else None
    return total, first, (cur, cur_start, cur_end if cur else None), longest


def fmt(d, with_year):
    return f"{d:%b} {d.day}, {d.year}" if with_year else f"{d:%b} {d.day}"


def span(start, end, today):
    if not start:
        return "No streak yet"
    y = start.year != end.year or end.year != today.year
    return f"{fmt(start, y)} - {fmt(end, y)}"


# ---------------------------------------------------------------- rendering
def grade(score):
    tiers = [(50, "C"), (150, "C+"), (400, "B"), (800, "B+"), (1500, "A"), (3000, "A+")]
    for limit, g in tiers:
        if score < limit:
            return g, min(1.0, score / 3000)
    return "S", 1.0


def esc(s):
    return html.escape(str(s), quote=True)


def ring(cx, cy, r, w, pct, bg, fg):
    c = 2 * math.pi * r
    return (
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{bg}" stroke-width="{w}"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{fg}" stroke-width="{w}" '
        f'stroke-linecap="round" stroke-dasharray="{c * pct:.1f} {c:.1f}" '
        f'transform="rotate(-90 {cx} {cy})"/>'
    )


def icon(kind, x, y):
    s = 'fill="none" stroke="#4c6fd6" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'
    if kind == "star":
        return f'<path transform="translate({x},{y})" {s} d="M10 2 L12.4 7.3 L18 7.9 L13.8 11.7 L15 17.3 L10 14.4 L5 17.3 L6.2 11.7 L2 7.9 L7.6 7.3 Z"/>'
    if kind == "commit":
        return f'<g transform="translate({x},{y})" {s}><circle cx="10" cy="10" r="7.5"/><path d="M10 5.5 V10 L13 12"/></g>'
    if kind == "pr":
        return (f'<g transform="translate({x},{y})" {s}><circle cx="5" cy="4.5" r="2"/><circle cx="5" cy="15.5" r="2"/>'
                f'<circle cx="15" cy="15.5" r="2"/><path d="M5 6.5 V13.5 M15 13.5 V8 Q15 5 12 5 H9.5"/></g>')
    if kind == "issue":
        return f'<g transform="translate({x},{y})" {s}><circle cx="10" cy="10" r="7.5"/><path d="M10 6 V10.5 M10 13.5 V13.6"/></g>'
    return f'<g transform="translate({x},{y})" {s}><path d="M5 3 H15 V16 H6.5 A1.5 1.5 0 0 1 5 14.5 Z M5 14.5 A1.5 1.5 0 0 1 6.5 13 H15"/></g>'


def render(d):
    today = dt.datetime.now(dt.timezone.utc).date()
    total, first, cur, longest = streaks(d["days"]) if d["days"] else (0, None, (0, None, None), (0, None, None))
    score = d["commits"] + 3 * d["prs"] + 2 * d["issues"] + 5 * d["stars"]
    g, pct = grade(score)

    rows = [
        ("star", "Total Stars Earned:", d["stars"]),
        ("commit", "Total Commits:", d["commits"]),
        ("pr", "Total PRs:", d["prs"]),
        ("issue", "Total Issues:", d["issues"]),
        ("repo", "Contributed to:", d["contributed"]),
    ]
    stat_rows = ""
    for i, (k, label, val) in enumerate(rows):
        y = 112 + i * 38
        stat_rows += (
            icon(k, 70, y - 15)
            + f'<text x="102" y="{y}" class="lbl">{esc(label)}</text>'
            + f'<text x="320" y="{y}" class="lbl">{esc(val)}</text>'
        )

    # languages
    langs = sorted(d["langs"].items(), key=lambda kv: -kv[1]["size"])
    total_size = sum(v["size"] for _, v in langs) or 1
    bar, legend, x = "", "", 0.0
    BAR_W = 330
    for i, (name, v) in enumerate(langs[:8]):
        share = v["size"] / total_size
        w = share * BAR_W
        bar += f'<rect x="{600 + x:.1f}" y="92" width="{max(w, 1.5):.1f}" height="10" fill="{esc(v["color"])}"/>'
        x += w
        col, row = i % 2, i // 2
        lx, ly = 600 + col * 175, 140 + row * 32
        legend += (
            f'<circle cx="{lx + 6}" cy="{ly - 5}" r="6" fill="{esc(v["color"])}"/>'
            f'<text x="{lx + 20}" y="{ly}" class="leg">{esc(name)} {share * 100:.1f}%</text>'
        )
    if not langs:
        legend = '<text x="600" y="140" class="leg">No language data yet</text>'
        bar = ""

    flame = ('<path transform="translate(500,344) scale(1.3)" fill="#fb8c00" d="M0 -14 C7 -7 10 -2 5 7 C3 2 -1 2 -4 7 '
             'C-9 -2 -6 -8 0 -14 Z"/>')
    nm = d["name"]
    first_txt = f"{fmt(first, True)} - Present" if first else "No contributions yet"

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 540" width="1000" height="540" role="img" aria-label="GitHub activity and metrics">
  <style>
    text {{ font-family: 'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif; }}
    .ttl {{ font-size: 22px; font-weight: 700; fill: #2f80ed; }}
    .lbl {{ font-size: 16px; font-weight: 600; fill: #434d5b; }}
    .leg {{ font-size: 14px; fill: #434d5b; }}
    .big {{ font-size: 42px; font-weight: 700; fill: #111827; }}
    .cap {{ font-size: 18px; fill: #1f2937; }}
    .sub {{ font-size: 14px; fill: #6b7280; }}
  </style>
  <rect x="0.5" y="0.5" width="999" height="539" rx="10" fill="#ffffff" stroke="#e4e7ec"/>

  <text x="70" y="62" class="ttl">{esc(nm)}'s GitHub Stats</text>
  {stat_rows}
  {ring(480, 180, 46, 10, pct, "#dbe7fb", "#4c8dff")}
  <text x="480" y="191" text-anchor="middle" style="font-size:30px;font-weight:700;fill:#2b2f3a">{esc(g)}</text>

  <text x="600" y="62" class="ttl">Most Used Languages</text>
  <clipPath id="barclip"><rect x="600" y="92" width="{BAR_W}" height="10" rx="5"/></clipPath>
  <g clip-path="url(#barclip)"><rect x="600" y="92" width="{BAR_W}" height="10" fill="#e5e7eb"/>{bar}</g>
  {legend}

  <line x1="375" y1="320" x2="375" y2="515" stroke="#e4e7ec"/>
  <line x1="625" y1="320" x2="625" y2="515" stroke="#e4e7ec"/>

  <text x="250" y="402" text-anchor="middle" class="big">{total}</text>
  <text x="250" y="450" text-anchor="middle" class="cap">Total Contributions</text>
  <text x="250" y="485" text-anchor="middle" class="sub">{esc(first_txt)}</text>

  <circle cx="500" cy="392" r="50" fill="none" stroke="#fb8c00" stroke-width="8" stroke-linecap="round"
          stroke-dasharray="283 31.4" transform="rotate(-73.4 500 392)"/>
  {flame}
  <text x="500" y="406" text-anchor="middle" class="big">{cur[0]}</text>
  <text x="500" y="477" text-anchor="middle" style="font-size:18px;font-weight:600;fill:#fb8c00">Current Streak</text>
  <text x="500" y="505" text-anchor="middle" class="sub">{esc(span(cur[1], cur[2], today))}</text>

  <text x="750" y="402" text-anchor="middle" class="big">{longest[0]}</text>
  <text x="750" y="450" text-anchor="middle" class="cap">Longest Streak</text>
  <text x="750" y="485" text-anchor="middle" class="sub">{esc(span(longest[1], longest[2], today))}</text>
</svg>
'''


# --------------------------------------------------------------------- main
def demo_data():
    today = dt.datetime.now(dt.timezone.utc).date()
    days = {}
    for i in range(300):
        d = today - dt.timedelta(days=i)
        days[d.isoformat()] = 0 if (i % 9 in (5, 6)) else (i % 4) + 1
    return {
        "name": "Demo User", "created": today - dt.timedelta(days=300),
        "stars": 4, "commits": 120, "prs": 4, "issues": 6, "contributed": 1,
        "langs": {"Python": {"size": 6000, "color": "#3572A5"}, "JavaScript": {"size": 2500, "color": "#f1e05a"},
                  "HTML": {"size": 1500, "color": "#e34c26"}, "C": {"size": 600, "color": "#555555"},
                  "CSS": {"size": 400, "color": "#563d7c"}},
        "days": days,
    }


def main():
    os.makedirs("stats", exist_ok=True)
    if "--demo" in sys.argv:
        data = demo_data()
    elif "--placeholder" in sys.argv:
        data = {"name": "Your", "created": dt.date.today(), "stars": 0, "commits": 0, "prs": 0,
                "issues": 0, "contributed": 0, "langs": {}, "days": {}}
    else:
        token, login = os.environ["GH_TOKEN"], os.environ["GH_USER"]
        data = fetch(login, token)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(render(data))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
