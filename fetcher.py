#!/usr/bin/env python3
"""ai-security-briefs fetcher — pulls RSS/Atom feeds and produces items.json."""

from __future__ import annotations

import feedparser
import html
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone


# --- Constants ---

TAG_RULES = [
    ("ai-security", 10, ["ai security", "llm security", "jailbreak", "prompt injection", "model weights", "guardrail", "ai safety", "red-teaming", "red teaming", "ai agent security", "data exfiltration agent", "shadow prompt"]),
    ("supply-chain", 7, ["supply chain", "pypi", "npm", "package manager", "malicious package", "dependency", "open source maintainer", "build pipeline", "backdoor"]),
    ("vulnerability", 6, ["cve", "zero-day", "zero day", "rce", "remote code execution", "exploit", "vulnerability", "sql injection", "buffer overflow", "privilege escalation", "patched"]),
    ("llm", 6, ["llm", "language model", "gpt", "claude", "gemini", "llama", "mistral", "deepseek", "qwen", "fine-tune", "model card", "benchmark", "chatbot", "agent framework", "mcp", "machine learning"]),
    ("incident", 5, ["breach", "ransomware", "data leak", "attack", "compromi", "malware", "threat actor", "campaign", "phishing", "leaked"]),
    ("policy", 4, ["regulat", "eu ai act", "cisa", "advisory", "executive order", "compliance", "export controls", "chip ban", "sanction"]),
    ("privacy", 3, ["privacy", "surveillance", "tracking", "data collection", "gdpr", "spying"]),
    ("general", 2, []),
]

MAX_TAGS = 3
PER_SOURCE_SLICE_DEFAULT = 30
RETRY_DELAYS = [1, 4]
TIMEOUT = 20
INTER_SOURCE_SLEEP = 1.5
REDDIT_SLEEP = 2.0

USER_AGENT = "ai-security-briefs/0.1 (personal local news digest; https://github.com/Amantux/ai-security-briefs)"


# --- Pure functions ---

def canon_url(u: str) -> str:
    """Canonicalize URL per §4.3."""
    import urllib.parse
    u = u.strip()
    parsed = urllib.parse.urlsplit(u)
    # Force https
    scheme = "https"
    netloc = parsed.netloc.lower()
    path = parsed.path
    # Drop fragment
    fragment = ""
    # Drop utm_* and tracking params
    query = parsed.query
    if query:
        params = urllib.parse.parse_qs(query, keep_blank_values=True)
        kept = {}
        for k, v in params.items():
            if k.startswith("utm_") or k in ("fbclid", "gclid"):
                continue
            kept[k] = v
        query = urllib.parse.urlencode(kept, doseq=True)
    # Strip trailing slash on non-root paths
    if path and path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urllib.parse.urlunsplit((scheme, netloc, path, query, fragment))


def parse_feed(raw_bytes: bytes) -> list:
    """Parse feed bytes into list of raw entries."""
    return feedparser.parse(raw_bytes).get("entries", [])


def normalize_entry(raw: dict, source_id: str) -> dict:
    """Normalize a raw feed entry to the 7-field item schema."""
    # Title: HTML-unescaped, whitespace-collapsed
    title = raw.get("title", "")
    if isinstance(title, dict):
        title = title.get("value", "")
    title = html.unescape(str(title))
    title = re.sub(r"\s+", " ", title).strip()

    # URL: canonicalize
    url = raw.get("link", "")
    if isinstance(url, dict):
        url = url.get("href", "")
    url = canon_url(str(url)) if url else ""

    # published_utc: prefer <published>, fallback <updated>, else fetch time
    published = raw.get("published") or raw.get("updated") or ""
    if published:
        # Try common formats
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z"):
            try:
                dt = datetime.strptime(published, fmt)
                published_utc = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                break
            except ValueError:
                continue
        else:
            published_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        published_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # summary: first sentence(s), <=200 chars
    desc = raw.get("description") or raw.get("summary") or ""
    if isinstance(desc, dict):
        desc = desc.get("value", "")
    desc = html.unescape(str(desc))
    # Strip HTML tags
    desc = re.sub(r"<[^>]+>", " ", desc)
    # Collapse whitespace
    desc = re.sub(r"\s+", " ", desc).strip()
    # Cut at sentence boundary <=200 chars
    if len(desc) <= 200:
        summary = desc
    else:
        # Find sentence boundary
        sub = desc[:200]
        m = re.search(r"([.!?]+)\s+", sub)
        if m:
            summary = desc[:m.end()].strip()
        else:
            summary = desc[:197] + "…"

    return {
        "title": title,
        "url": url,
        "source": source_id,
        "published_utc": published_utc,
        "score": 0,
        "tags": [],
        "summary": summary,
    }


def tag_item(item: dict) -> dict:
    """Assign tags to item per §5.1."""
    text = (item.get("title", "") + " " + item.get("summary", "")).lower()
    matched = []
    for tag, weight, keywords in TAG_RULES:
        for kw in keywords:
            if kw.lower() in text:
                matched.append((tag, weight))
                break
    # Dedupe by tag, keep highest weight
    tag_weights = {}
    for tag, weight in matched:
        if tag not in tag_weights or weight > tag_weights[tag]:
            tag_weights[tag] = weight
    # Sort by weight desc, take top MAX_TAGS
    sorted_tags = sorted(tag_weights.items(), key=lambda x: (-x[1], x[0]))
    item["tags"] = [t for t, _ in sorted_tags[:MAX_TAGS]]
    return item


def included(item: dict, core_topic: bool) -> bool:
    """Determine if item passes inclusion rule per §5.2."""
    return len(item.get("tags", [])) >= 1 or core_topic


def merge_items(old_store: dict, new_items: list, fetch_utc: str, days: int = 14) -> dict:
    """Merge new items into old store, upsert by canonical URL, prune old."""
    # Build lookup by canonical URL
    url_to_item = {canon_url(i["url"]): i for i in old_store.get("items", [])}
    # Upsert new items
    for item in new_items:
        url_to_item[canon_url(item["url"])] = item
    # Filter to included items
    filtered = [i for i in url_to_item.values() if included(i, True)]
    # Prune by age
    cutoff = datetime.strptime(fetch_utc, "%Y-%m-%dT%H:%M:%SZ")
    kept = []
    for item in filtered:
        pub = datetime.strptime(item["published_utc"], "%Y-%m-%dT%H:%M:%SZ")
        age_days = (cutoff - pub).days
        if age_days <= days:
            kept.append(item)
    # Hard cap at 2000 (drop oldest first)
    kept.sort(key=lambda x: (x["published_utc"], x["url"]), reverse=True)
    kept = kept[:2000]
    return {
        "schema_version": 1,
        "generated_utc": fetch_utc,
        "window_days": days,
        "sources_ok": old_store.get("sources_ok", []),
        "sources_failed": old_store.get("sources_failed", []),
        "items": kept,
    }


# --- Fetcher logic ---

def fetch_source(source: dict, items_store: dict) -> tuple:
    """Fetch a single source, return (items, success, reason)."""
    source_id = source["id"]
    url = source["url"]
    core_topic = source.get("core_topic", True)
    slice_limit = source.get("slice", PER_SOURCE_SLICE_DEFAULT)

    headers = {"User-Agent": USER_AGENT}
    attempts = 0
    last_status = None

    while attempts <= len(RETRY_DELAYS):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw_bytes = resp.read()
                entries = parse_feed(raw_bytes)
                # Slice if needed
                entries = entries[:slice_limit]
                # Normalize and tag
                new_items = []
                for entry in entries:
                    item = normalize_entry(entry, source_id)
                    item = tag_item(item)
                    if included(item, core_topic):
                        new_items.append(item)
                return (new_items, True, None)
        except urllib.error.HTTPError as e:
            last_status = e.code
            if e.code == 429:
                # Rate limited
                retry_after = e.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = int(retry_after)
                        if delay <= 60:
                            time.sleep(delay)
                            attempts += 1
                            continue
                    except ValueError:
                        pass
                return ([], False, "429")
            elif e.code >= 500:
                # Server error, retry
                delay = RETRY_DELAYS[attempts] if attempts < len(RETRY_DELAYS) else None
                if delay:
                    time.sleep(delay)
                    attempts += 1
                    continue
                return ([], False, str(e.code))
            else:
                # 4xx other than 429
                return ([], False, str(e.code))
        except Exception as e:
            last_status = type(e).__name__
            if attempts < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempts])
                attempts += 1
                continue
            return ([], False, str(last_status) or type(e).__name__)

    return ([], False, str(last_status) if last_status else "unknown")


def fetch_all(config_path: str = "sources.json", items_path: str = "items.json") -> dict:
    """Fetch all sources and return merged store."""
    # Load config
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    sources = config.get("sources", [])
    user_agent = config.get("user_agent", USER_AGENT)

    # Load existing items
    if os.path.exists(items_path):
        with open(items_path, "r", encoding="utf-8") as f:
            try:
                items_store = json.load(f)
            except json.JSONDecodeError:
                print(f"[fetch] ERROR: {items_path} is corrupt")
                return {"error": "corrupt items.json", "exit_code": 2}
    else:
        items_store = {
            "schema_version": 1,
            "generated_utc": "",
            "window_days": 14,
            "sources_ok": [],
            "sources_failed": [],
            "items": [],
        }

    fetch_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sources_ok = []
    sources_failed = []

    for src in sources:
        source_id = src["id"]
        items, success, reason = fetch_source(src, items_store)
        if success:
            sources_ok.append(source_id)
            # Merge into store
            items_store = merge_items(items_store, items, fetch_utc)
            print(f"[fetch] OK source={source_id} items={len(items)}")
        else:
            sources_failed.append({"id": source_id, "reason": reason})
            print(f"[fetch] FAIL source={source_id} status={reason}")

        # Sleep between sources
        if src.get("type") == "rss":
            time.sleep(INTER_SOURCE_SLEEP)
        else:
            time.sleep(REDDIT_SLEEP)

    items_store["sources_ok"] = sources_ok
    items_store["sources_failed"] = sources_failed
    items_store["generated_utc"] = fetch_utc

    # Write atomically
    tmp_path = items_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(items_store, f, indent=2)
    os.replace(tmp_path, items_path)

    return {"exit_code": 0}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fetch AI/security briefs")
    parser.add_argument("--config", default="sources.json", help="Path to sources.json")
    parser.add_argument("--items", default="items.json", help="Path to items.json")
    parser.add_argument("--days", type=int, default=14, help="Retention window in days")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    result = fetch_all(args.config, args.items)
    exit(result.get("exit_code", 0))
