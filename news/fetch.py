#!/usr/bin/env python3
"""Collect headlines from public RSS feeds into news/news.json.

Keeps only title, link, source and date for each item (no article text) and
retains the last 7 days. Run daily by .github/workflows/news.yml so the page
always shows a rolling week. Standard library only.
"""
import html, json, os, sys, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "news.json")
UA = "Mozilla/5.0 (compatible; sentinel-atlas-news; +https://github.com/nandkarthik/sentinel-atlas)"
WINDOW = timedelta(days=7)

def only(*cats):
    wanted = {c.lower() for c in cats}
    return lambda it: bool(wanted & {c.strip().lower() for c in it["cats"]})

# section, source name, feed url, optional filter on the item
FEEDS = [
    ("world", "BBC News", "https://feeds.bbci.co.uk/news/world/rss.xml", None),
    ("world", "Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", None),
    ("world", "The Hindu", "https://www.thehindu.com/news/international/feeder/default.rss", None),
    ("ap", "The Hindu", "https://www.thehindu.com/news/national/andhra-pradesh/feeder/default.rss", None),
    ("ap", "Deccan Chronicle", "https://www.deccanchronicle.com/rss_feed/", only("Andhra Pradesh")),
    ("ts", "The Hindu", "https://www.thehindu.com/news/national/telangana/feeder/default.rss", None),
    ("ts", "Deccan Chronicle", "https://www.deccanchronicle.com/rss_feed/", only("Telangana")),
    ("te", "Sakshi", "https://www.sakshi.com/rss.xml", None),
]
PER_SECTION = {"world": 120, "ap": 90, "ts": 90, "te": 70}

def clean(s):
    return " ".join(html.unescape(s or "").split())

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return ET.fromstring(r.read())

def parse(root):
    for it in root.iter("item"):
        title = clean(it.findtext("title"))
        link = (it.findtext("link") or "").strip().split("?")[0]
        pub = it.findtext("pubDate")
        if not (title and link and pub):
            continue
        try:
            dt = parsedate_to_datetime(pub)
        except (TypeError, ValueError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        cats = []
        for tag in ("category", "{http://purl.org/dc/elements/1.1/}subject"):
            for c in it.findall(tag):
                cats += (c.text or "").split(",")
        yield {"title": title, "link": link, "date": dt.astimezone(timezone.utc), "cats": cats}

def main():
    now = datetime.now(timezone.utc)
    cutoff = now - WINDOW
    try:
        with open(OUT, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = {}
    items = {}  # (section, link) -> item
    for sec, lst in old.get("sections", {}).items():
        for it in lst:
            items[(sec, it["link"])] = it

    cache, ok, failed = {}, 0, []
    for sec, source, url, flt in FEEDS:
        try:
            if url not in cache:
                cache[url] = list(parse(fetch(url)))
            got = [it for it in cache[url] if not flt or flt(it)]
            ok += 1
        except Exception as e:  # keep going; older items stay
            failed.append(f"{source} ({sec}): {e}")
            continue
        for it in got:
            if it["date"] < cutoff:
                continue
            items[(sec, it["link"])] = {
                "title": it["title"], "link": it["link"], "source": source,
                "date": it["date"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            }

    sections = {}
    for sec in PER_SECTION:
        rows = [v for (s, _), v in items.items() if s == sec and v["date"] >= cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")]
        rows.sort(key=lambda v: v["date"], reverse=True)
        sections[sec] = rows[: PER_SECTION[sec]]

    if ok == 0:
        print("All feeds failed:", *failed, sep="\n  ", file=sys.stderr)
        return 1
    # keep the stamp stable when nothing new arrived, so the workflow makes no empty commits
    if old.get("sections") == sections:
        print("No new headlines.")
    else:
        data = {"generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "windowDays": WINDOW.days, "sections": sections}
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.write("\n")
        print({k: len(v) for k, v in sections.items()})
    for msg in failed:
        print("warning:", msg, file=sys.stderr)
    return 0

if __name__ == "__main__":
    sys.exit(main())
