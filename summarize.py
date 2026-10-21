#!/usr/bin/env python3
"""ai-security-briefs summarizer — produces daily/weekly briefs from items.json."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone


def render_daily(items_store: dict, top_n: int = 15) -> str:
    """Render daily brief per §6."""
    items = items_store.get("items", [])
    fetch_utc = items_store.get("generated_utc", "")
    sources_ok = items_store.get("sources_ok", [])
    sources_failed = items_store.get("sources_failed", [])

    if not fetch_utc:
        # No data
        return "# AI & Security Brief — N/A\n\nNo data available.\n"

    # Parse fetch time
    try:
        fetch_dt = datetime.strptime(fetch_utc, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return "# AI & Security Brief — N/A\n\nInvalid timestamp in items.json.\n"

    # Filter to 24h window
    cutoff_24h = fetch_dt - timedelta(hours=24)
    cutoff_48h = fetch_dt - timedelta(hours=48)

    window_items = [i for i in items if parse_utc(i["published_utc"]) > cutoff_24h]
    if len(window_items) == 0:
        # Fallback to 48h
        window_items = [i for i in items if parse_utc(i["published_utc"]) > cutoff_48h]
        window_label = "Window: 48 h fallback"
    else:
        window_label = "Window: items published in the 24 h preceding this run."

    # Rank per §5.3
    ranked = rank_items(window_items, fetch_utc)

    # Take top N
    top_items = ranked[:top_n]

    lines = []
    # Date is UTC date of run
    date_str = fetch_dt.strftime("%Y-%m-%d")
    lines.append(f"# AI & Security Brief — {date_str}")
    lines.append("")
    lines.append(window_label)
    n_ok = len(sources_ok)
    n_total = n_ok + len(sources_failed)
    lines.append(f"Coverage: {len(window_items)} relevant items in window · {n_ok}/{n_total} sources OK.")
    lines.append("")
    lines.append("## Top items")
    lines.append("")

    for i, item in enumerate(top_items, 1):
        title = item.get("title", "")
        url = item.get("url", "")
        summary = item.get("summary", "") or title
        tags = " ".join(f"#{t}" for t in item.get("tags", []))
        source = item.get("source", "")
        if summary == title:
            lines.append(f"{i}. **[{title}]({url})**")
        else:
            lines.append(f"{i}. **[{title}]({url})** — {summary}")
        lines.append(f"     {tags} · source: {source}")
        lines.append("")

    lines.append("## Sources")
    lines.append("")
    if sources_ok:
        lines.append(f"OK: {', '.join(sources_ok)}")
    else:
        lines.append("OK: none")
    if sources_failed:
        fail_str = ", ".join(f"{s['id']} ({s['reason']})" for s in sources_failed)
        lines.append(f"Failed: {fail_str}")
    else:
        lines.append("Failed: none")

    return "\n".join(lines)


def render_weekly(items_store: dict, target_week_start: datetime, target_week_end: datetime) -> str:
    """Render weekly digest per §7."""
    items = items_store.get("items", [])
    sources_ok = items_store.get("sources_ok", [])

    # Filter to week
    week_items = [i for i in items if target_week_start <= parse_utc(i["published_utc"]) <= target_week_end]

    # Count dailies in week
    briefs_dir = "briefs"
    dailies = []
    if os.path.isdir(briefs_dir):
        for fname in sorted(os.listdir(briefs_dir)):
            if fname.endswith(".md"):
                try:
                    date_str = fname[:-3]  # strip .md
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    if target_week_start <= dt <= target_week_end:
                        dailies.append(date_str)
                except ValueError:
                    continue

    # Rank items
    fetch_utc = items_store.get("generated_utc", "")
    if fetch_utc:
        try:
            fetch_dt = datetime.strptime(fetch_utc, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            fetch_dt = None
    else:
        fetch_dt = None

    if fetch_dt:
        ranked = rank_items(week_items, fetch_utc)
    else:
        ranked = sorted(week_items, key=lambda x: (x["published_utc"], x["url"]), reverse=True)

    # Themes: top 5 tags by count
    tag_counts = {}
    for item in ranked:
        for tag in item.get("tags", []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    # Sort by count desc, then weight desc (using TAG_RULES)
    from fetcher import TAG_RULES
    tag_weight = {t: w for t, w in TAG_RULES}
    sorted_tags = sorted(tag_counts.items(), key=lambda x: (-x[1], -tag_weight.get(x[0], 0)))

    # Build weekly
    lines = []
    # ISO week date
    week_start_str = target_week_start.strftime("%Y-%m-%d")
    week_end_str = target_week_end.strftime("%Y-%m-%d")
    iso_week = target_week_start.isocalendar()[1]
    lines.append(f"# AI & Security Weekly — {target_week_start.year}-W{iso_week:02d} ({week_start_str} – {week_end_str})")
    lines.append("")
    lines.append(f"{len(week_items)} relevant items across the week · {len(dailies)} dailies published in this window.")
    lines.append("")

    if ranked:
        lines.append("## Themes")
        lines.append("")

        for tag, count in sorted_tags[:5]:
            lines.append(f"### {tag} ({count} items)")
            lines.append("")
            # Get top 3 examples
            examples = [i for i in ranked if tag in i.get("tags", [])][:3]
            for item in examples:
                title = item.get("title", "")
                url = item.get("url", "")
                source = item.get("source", "")
                lines.append(f"- **[{title}]({url})** · source: {source}")
            lines.append("")

        lines.append("## Top 10 across the week")
        lines.append("")

        for i, item in enumerate(ranked[:10], 1):
            title = item.get("title", "")
            url = item.get("url", "")
            summary = item.get("summary", "") or title
            tags = " ".join(f"#{t}" for t in item.get("tags", []))
            source = item.get("source", "")
            if summary == title:
                lines.append(f"{i}. **[{title}]({url})**")
            else:
                lines.append(f"{i}. **[{title}]({url})** — {summary}")
            lines.append(f"   {tags} · source: {source}")
            lines.append("")

        lines.append("## Dailies")
        lines.append("")
        if dailies:
            for date_str in dailies:
                lines.append(f"- [{date_str}](briefs/{date_str}.md)")
        else:
            lines.append("_No dailies in this window._")
    else:
        lines.append("## Top 10 across the week")
        lines.append("")
        lines.append("_No items in this week._")

    return "\n".join(lines)


def parse_utc(s: str) -> datetime:
    """Parse UTC timestamp."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


def rank_items(items: list, fetch_utc: str) -> list:
    """Rank items per §5.3."""
    fetch_dt = parse_utc(fetch_utc)

    def recency_bonus(pub_dt: datetime) -> int:
        age = fetch_dt - pub_dt
        hours = age.total_seconds() / 3600
        if hours <= 24:
            return 4
        elif hours <= 72:
            return 2
        elif hours <= 168:  # 7 days
            return 1
        return 0

    def score_bonus(score: int) -> int:
        return min(2, score // 1000)

    def rank(item: dict) -> tuple:
        # Get max tag weight
        from fetcher import TAG_RULES
        tag_weight = {t: w for t, w in TAG_RULES}
        tags = item.get("tags", [])
        max_weight = max((tag_weight.get(t, 0) for t in tags), default=0)

        pub_dt = parse_utc(item["published_utc"])
        score = item.get("score", 0)

        r = max_weight + recency_bonus(pub_dt) + score_bonus(score)
        # Ties: published_utc DESC, then url ASC
        return (-r, item["published_utc"], item["url"])

    return sorted(items, key=rank)


def summarize(items_path: str, top_n: int = 15, briefs_dir: str = "briefs", weekly_dir: str = "weekly",
              only: str = "both", week_str: str = "") -> dict:
    """Run summarization per §6/7."""
    # Load items
    if not os.path.exists(items_path):
        return {"error": f"items.json not found: {items_path}", "exit_code": 1}

    with open(items_path, "r", encoding="utf-8") as f:
        try:
            items_store = json.load(f)
        except json.JSONDecodeError:
            return {"error": f"items.json is corrupt", "exit_code": 1}

    # Determine target week
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone()  # local timezone
    if week_str:
        # Parse YYYY-Www
        year, week_num = int(week_str[:4]), int(week_str[6:8])
        # Get Monday of that ISO week
        jan4 = datetime(year, 1, 4)
        delta = timedelta(days=(week_num - 1) * 7)
        week_start = jan4 + delta - timedelta(days=jan4.weekday())
        week_end = week_start + timedelta(days=6)
    else:
        # Last completed ISO week
        # Rule: if now_local is Monday 00:00-23:59 OR later in that ISO week, take previous week
        weekday = now_local.weekday()  # Monday=0
        if weekday == 0:  # Monday
            # Check if we're past midnight of this Monday
            # Use the rule: target_week = ISO week containing (now_local - 7 days)
            target_dt = now_local - timedelta(days=7)
        else:
            target_dt = now_local - timedelta(days=7)
        # ISO week of target_dt
        iso = target_dt.isocalendar()
        year, week_num = iso[0], iso[1]
        jan4 = datetime(year, 1, 4)
        delta = timedelta(days=(week_num - 1) * 7)
        week_start = jan4 + delta - timedelta(days=jan4.weekday())
        week_end = week_start + timedelta(days=6)

    # Create dirs
    os.makedirs(briefs_dir, exist_ok=True)
    os.makedirs(weekly_dir, exist_ok=True)

    # Render daily
    if only in ("both", "daily"):
        daily_md = render_daily(items_store, top_n)
        date_str = now_utc.strftime("%Y-%m-%d")
        daily_path = os.path.join(briefs_dir, f"{date_str}.md")
        # Write atomically
        tmp_path = daily_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(daily_md)
        os.replace(tmp_path, daily_path)
        print(f"[summarize] Wrote {daily_path}")

    # Render weekly
    if only in ("both", "weekly"):
        weekly_md = render_weekly(items_store, week_start, week_end)
        iso_week = week_start.isocalendar()[1]
        weekly_path = os.path.join(weekly_dir, f"{week_start.year}-W{iso_week:02d}.md")
        tmp_path = weekly_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(weekly_md)
        os.replace(tmp_path, weekly_path)
        print(f"[summarize] Wrote {weekly_path}")

    return {"exit_code": 0}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Summarize items into briefs")
    parser.add_argument("--items", default="items.json", help="Path to items.json")
    parser.add_argument("--top", type=int, default=15, help="Top N items")
    parser.add_argument("--briefs-dir", default="briefs", help="Briefs output dir")
    parser.add_argument("--weekly-dir", default="weekly", help="Weekly output dir")
    parser.add_argument("--only", choices=["daily", "weekly", "both"], default="both", help="What to render")
    parser.add_argument("--week", help="Target ISO week (YYYY-Www)")
    args = parser.parse_args()

    result = summarize(args.items, args.top, args.briefs_dir, args.weekly_dir, args.only, args.week)
    exit(result.get("exit_code", 0))
