#!/usr/bin/env python3
"""
import_spreaker_rss.py
Fetch an RSS/Atom feed (Spreaker), generate Hugo Markdown posts into content/podcast/.
Usage:
  python scripts/import_spreaker_rss.py --rss "https://www.spreaker.com/show/XXXXX/episodes/rss" \
      --output content/podcast --author "Pseudonym" --lang pl

Requirements (install via pip):
  pip install feedparser requests python-slugify
"""

import os
import re
import json
import argparse
from datetime import datetime
import feedparser
import requests
from slugify import slugify

# ----------------------------
# Defaults and helper things
# ----------------------------
EPISODE_DB = ".episodes.json"   # local file to remember processed GUIDs
SPREAKER_EPISODE_ID_RE = re.compile(r"/episode/(\d+)(?:[/?#]|$)")

# Template for YAML front matter and body
MARKDOWN_TEMPLATE = """---
title: "{title}"
date: {date}
slug: "{slug}"
draft: false
episode_id: "{episode_id}"
audio: "{audio_url}"
description: |
  {description}
tags: [{tags}]
lang: "{lang}"
---

<!-- Spreaker player -->
<iframe src="https://widget.spreaker.com/player?episode_id={episode_id}"
        width="100%" height="200" frameborder="0" scrolling="no"></iframe>

{excerpt}
"""

def safe_filename(s):
    # Ensure filename safe for most filesystems
    return slugify(s, lowercase=True)

def extract_spreaker_episode_id(link, guid, enclosure_url):
    # Try to extract episode id from link or guid or enclosure:
    for candidate in (link, guid, enclosure_url):
        if not candidate:
            continue
        m = SPREAKER_EPISODE_ID_RE.search(candidate)
        if m:
            return m.group(1)
    # fallback None
    return ""

def load_db(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}

def save_db(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def make_markdown(item, episode_id, slug, lang="pl"):
    title = item.get("title", "No title").replace('"', '\\"')
    published = item.get("published") or item.get("updated") or ""
    # try parse published into ISO format
    try:
        if published:
            dt = datetime(*item.published_parsed[:6])
            iso_date = dt.isoformat()
        else:
            iso_date = datetime.utcnow().isoformat()
    except Exception:
        iso_date = datetime.utcnow().isoformat()

    # audio enclosure
    audio_url = ""
    if "enclosures" in item and item.enclosures:
        audio_url = item.enclosures[0].get("href", "")
    elif "links" in item:
        # fallback: find type audio
        for l in item.links:
            if l.get("type", "").startswith("audio"):
                audio_url = l.get("href", "")
                break

    # description (strip newlines a bit)
    description = (item.get("description") or item.get("summary") or "").strip().replace('\r', '')
    # simple excerpt — first 250 chars
    excerpt = description[:250] + ("..." if len(description) > 250 else "")
    tags = ",".join([t.get("term", "") for t in item.get("tags", []) if isinstance(t, dict)])


    md = MARKDOWN_TEMPLATE.format(
        title=title,
        date=iso_date,
        slug=slug,
        episode_id=episode_id,
        audio_url=audio_url,
        description=description.replace("\n", "\n  "),
        tags=tags,
        lang=lang,
        excerpt=excerpt
    )
    return md

def main():
    p = argparse.ArgumentParser(description="Import Spreaker RSS into Hugo posts")
    p.add_argument("--rss", required=True, help="RSS feed URL")
    p.add_argument("--output", default="content/podcast", help="Hugo content output directory")
    p.add_argument("--author", default="", help="Author name (optional)")
    p.add_argument("--lang", default="pl", help="Language code to write into front matter")
    p.add_argument("--db", default=EPISODE_DB, help="Local DB file to store processed GUIDs")
    p.add_argument("--max", type=int, default=0, help="Max episodes to import (0 = all)")
    args = p.parse_args()

    os.makedirs(args.output, exist_ok=True)
    db = load_db(args.db)
    feed = feedparser.parse(args.rss)

    if feed.bozo:
        print("Warning: feedparser detected a problem parsing the feed. Proceeding may fail.")
        # but continue

    new_count = 0
    items = feed.entries or []
    # sort by published if present (oldest first)
    items = sorted(items, key=lambda x: x.get("published_parsed") or (0,))

    for item in items:
        guid = item.get("id") or item.get("guid") or item.get("link")
        if not guid:
            # fallback to title+published
            guid = (item.get("title","") + item.get("published","")).strip()

        if guid in db:
            # skip already processed
            continue

        # Extract episode id from link/guid
        episode_id = extract_spreaker_episode_id(item.get("link",""), guid, (item.enclosures[0].get("href") if item.get("enclosures") else ""))

        # Build slug + filename
        base_slug = item.get("slug") or item.get("title") or f"episode-{episode_id or 'noid'}"
        slug = safe_filename(base_slug)
        # filename with date + slug for ordering
        published = item.get("published") or item.get("updated") or ""
        try:
            if published:
                dt = datetime(*item.published_parsed[:6])
                date_prefix = dt.strftime("%Y-%m-%d")
            else:
                date_prefix = datetime.utcnow().strftime("%Y-%m-%d")
        except Exception:
            date_prefix = datetime.utcnow().strftime("%Y-%m-%d")

        filename = f"{date_prefix}-{slug}.md"
        filepath = os.path.join(args.output, filename)

        # If file already exists, append unique suffix
        i = 1
        while os.path.exists(filepath):
            filepath = os.path.join(args.output, f"{date_prefix}-{slug}-{i}.md")
            i += 1

        md = make_markdown(item, episode_id, slug, lang=args.lang)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md)

        db[guid] = {
            "filename": filepath,
            "title": item.get("title"),
            "episode_id": episode_id,
            "imported_at": datetime.utcnow().isoformat()
        }
        new_count += 1
        print("Wrote:", filepath)

        if args.max and new_count >= args.max:
            break

    save_db(args.db, db)
    print(f"Import complete. {new_count} new episodes written. DB saved to {args.db}")

if __name__ == "__main__":
    main()

