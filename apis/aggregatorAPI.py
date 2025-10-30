from flask import Flask, request, jsonify
from collections import defaultdict
from datetime import datetime
import feedparser
import aiohttp
from apscheduler.schedulers.background import BackgroundScheduler
import asyncio
from xml.etree.ElementTree import Element, SubElement, tostring
from flask_cors import CORS
import re
import hashlib
from cachetools import TTLCache
import requests
import time
import redis
import os
import json
import atexit
import logging

# ---- Logging setup ----
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# ---- Config ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FEED_FILE = "feedurls.txt"
#YOUTUBE_API_KEY = "AIzaSyCyLv9Mmv0l9C6KAE9lKD_im7WfyFErUaQ"
#FLICKR_API_KEY = "715d330285540544f7323bc79dd188c2"
#REDIS_URL = "redis://default:AUfZAAIncDI4ZTczNWJlMDA4NzI0MzJmODY1NTg3Y2NjMmRmN2NjZHAyMTgzOTM@topical-mastodon-18393.upstash.io:6379"


YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
FLICKR_API_KEY = os.getenv("FLICKR_API_KEY")
REDIS_URL = os.getenv("REDIS_URL")

# ---- Redis ----
try:
    r = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None
    r.ping()  # Test connection
except redis.ConnectionError:
    logger.warning("⚠️ Could not connect to Redis. Falling back to in-memory cache.")
    r = None
# ---- Caches ----
tag_cache = {}
last_update_time = 0
cache = TTLCache(maxsize=100, ttl=3600)
processed_feeds_cache = TTLCache(maxsize=10, ttl=3600)
youtube_thumbnail_cache = TTLCache(maxsize=1000, ttl=3600)

# ---- Load feeds ----
def load_feed_urls(file_path=FEED_FILE):
    file_path = os.path.join(BASE_DIR, file_path)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip()]
        return list(set(urls))
    except FileNotFoundError:
        logger.warning(f"Feed URL file '{file_path}' not found. Using default feed.")
        return ["https://archive.org/services/collection-rss.php?collection=resistancearchive"]

feed_urls = load_feed_urls()

# ---- Async feed fetching ----
async def fetch_url(session, url):
    try:
        async with session.get(url, timeout=10) as resp:
            return url, await resp.text()
    except Exception as e:
        logger.warning(f"Error fetching {url}: {e}")
        return url, None

async def fetch_feeds_async(urls):
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_url(session, url) for url in urls]
        responses = await asyncio.gather(*tasks)
        return {url: feedparser.parse(content) for url, content in responses if content}

# ---- Compute tag counts ----
def compute_tag_counts():
    global tag_cache, last_update_time
    logger.info("🔄 Recomputing tag counts...")
    try:
        loop = asyncio.get_event_loop()
        feed_data = loop.run_until_complete(fetch_feeds_async(feed_urls))
    except RuntimeError:  # No running event loop
        feed_data = asyncio.run(fetch_feeds_async(feed_urls))

    tag_count = defaultdict(int)
    for feed in feed_data.values():
        for entry in feed.get("entries", []):
            for tag in [t["term"] for t in entry.get("tags", [])]:
                if not tag.startswith(("texts/", "image/")):
                    tag_count[tag] += 1

    tag_cache = dict(tag_count)
    last_update_time = time.time()
    logger.info(f"✅ Tag cache updated with {len(tag_cache)} tags.")

    if r:
        try:
            r.setex("tags", 86400, json.dumps(tag_cache))
            logger.info("💾 Redis cache refreshed.")
        except Exception as e:
            logger.warning(f"⚠️ Could not update Redis: {e}")

    return tag_cache

# ---- Cached entries ----
def get_feed_cache_key(feed_urls):
    joined_urls = ",".join(sorted(feed_urls))
    return hashlib.sha256(joined_urls.encode()).hexdigest()

def get_cached_entries():
    cache_key = get_feed_cache_key(feed_urls)
    if cache_key in processed_feeds_cache:
        logger.info("✅ Using cached feed entries")
        return processed_feeds_cache[cache_key]

    logger.info("⚙️ Cache miss, fetching feeds...")
    try:
        loop = asyncio.get_event_loop()
        feed_data = loop.run_until_complete(fetch_feeds_async(feed_urls))
    except RuntimeError:
        feed_data = asyncio.run(fetch_feeds_async(feed_urls))

    entries = process_entries(feed_data)
    unique_entries = deduplicate(entries)
    processed_feeds_cache[cache_key] = unique_entries
    logger.info(f"💾 Cached {len(unique_entries)} processed entries")
    return unique_entries

# ---- Entry processing ----
def process_entries(feed_data):
    entries = []
    youtube_ids = []

    # Collect YouTube IDs
    for feed in feed_data.values():
        for entry in feed.entries:
            if "youtube.com" in entry.link:
                vid = extract_youtube_video_id(entry.link)
                if vid:
                    youtube_ids.append(vid)

    # Fetch YouTube metadata
    youtube_metadata = fetch_youtube_metadata(youtube_ids)

    for feed in feed_data.values():
        for entry in feed.entries:
            youtube_tags, youtube_thumb = [], None
            if "youtube.com" in entry.link:
                vid = extract_youtube_video_id(entry.link)
                if vid and vid in youtube_metadata:
                    meta = youtube_metadata[vid]
                    youtube_tags = meta.get("tags", [])
                    youtube_thumb = meta.get("thumbnail")

            processed_entry = {
                "title": entry.title,
                "link": entry.link,
                "published": datetime(*entry.published_parsed[:6]) if entry.get("published_parsed") else None,
                "tags": [t.term for t in getattr(entry, "tags", [])] + youtube_tags,
                "thumbnail": youtube_thumb,
            }
            entries.append(processed_entry)

    return sorted(entries, key=lambda x: x["published"], reverse=True)

# ---- YouTube helpers ----
def extract_youtube_video_id(url):
    match = re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})", url)
    return match.group(1) if match else None

def fetch_youtube_metadata(video_ids):
    if not video_ids or not YOUTUBE_API_KEY:
        return {}
    video_metadata = {}
    BATCH_SIZE = 50
    for i in range(0, len(video_ids), BATCH_SIZE):
        batch = video_ids[i:i+BATCH_SIZE]
        url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={','.join(batch)}&key={YOUTUBE_API_KEY}"
        try:
            resp = requests.get(url, timeout=(3,5))
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("items", []):
                vid = item["id"]
                snippet = item.get("snippet", {})
                video_metadata[vid] = {
                    "tags": snippet.get("tags", []),
                    "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url")
                }
        except requests.RequestException as e:
            logger.warning(f"YouTube metadata error: {e}")
    return video_metadata

def get_youtube_thumbnail(video_id):
    if not video_id:
        return None
    if video_id in youtube_thumbnail_cache:
        return youtube_thumbnail_cache[video_id]
    url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
    youtube_thumbnail_cache[video_id] = url
    return url

# ---- Flickr helpers ----
def extract_photo_id(url):
    match = re.search(r'flickr\.com/photos/[^/]+/(\d+)', url)
    return match.group(1) if match else None

def get_flickr_thumbnail(photo_id):
    if not photo_id or not FLICKR_API_KEY:
        return None
    try:
        api_url = f"https://www.flickr.com/services/rest/?method=flickr.photos.getSizes&api_key={FLICKR_API_KEY}&photo_id={photo_id}&format=json&nojsoncallback=1"
        resp = requests.get(api_url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if data.get("stat") != "ok":
            return None
        sizes = data.get("sizes", {}).get("size", [])
        thumb = next((s for s in sizes if s["label"]=="Small"), None)
        return thumb["source"] if thumb else None
    except requests.RequestException as e:
        logger.warning(f"Flickr thumbnail error: {e}")
        return None

# ---- Deduplicate ----
def deduplicate(entries):
    seen = set()
    unique = []
    for e in entries:
        if e["link"] not in seen:
            seen.add(e["link"])
            unique.append(e)
    return unique

# ---- Boolean search ----
def clean_query(query):
    q = re.sub(r'[^\w\s\-"()|,]', '', query).strip()
    q = q.replace("(", " ( ").replace(")", " ) ").replace(",", " , ").replace("|", " | ").replace("-", " - ")
    return " ".join(q.split()).lower()

def parse_query(query):
    query = clean_query(query)
    tokens = re.findall(r'"[^"]+"|\S+|\(|\)|,|\||-', query)

    def parse_expr(tokens):
        expr = parse_term(tokens)
        while tokens and tokens[0]=='|':
            tokens.pop(0)
            expr = ('|', expr, parse_term(tokens))
        return expr
    def parse_term(tokens):
        term = parse_factor(tokens)
        while tokens and tokens[0]==',':
            tokens.pop(0)
            term = (',', term, parse_factor(tokens))
        return term
    def parse_factor(tokens):
        if tokens and tokens[0]=='(':
            tokens.pop(0)
            expr = parse_expr(tokens)
            tokens.pop(0)
            return expr
        elif tokens and tokens[0]=='-':
            tokens.pop(0)
            return ('-', parse_factor(tokens))
        elif tokens:
            return tokens.pop(0).strip('"').lower()
        return None
    return parse_expr(tokens)

def evaluate_query(entry, parsed_query):
    tags = {t.lower().strip() for t in entry['tags']}
    def eval_expr(expr):
        if isinstance(expr, tuple):
            op = expr[0]
            if op=='-': return not eval_expr(expr[1])
            left, right = eval_expr(expr[1]), eval_expr(expr[2])
            return left or right if op=='|' else left and right
        elif isinstance(expr, str):
            return expr in tags
        return False
    return eval_expr(parsed_query)

def boolean_search(entries, query):
    parsed = parse_query(query)
    results = []
    for e in entries:
        if evaluate_query(e, parsed):
            # Thumbnails
            if "archive.org/details" in e["link"]:
                e["thumbnail"] = f"https://archive.org/services/img/{e['link'].split('/')[-1]}"
            elif "flickr.com" in e["link"]:
                pid = extract_photo_id(e["link"])
                if pid: e["thumbnail"] = get_flickr_thumbnail(pid)
            elif "youtube.com" in e["link"] or "you.tube" in e["link"]:
                vid = extract_youtube_video_id(e["link"])
                if vid: e["thumbnail"] = get_youtube_thumbnail(vid)
            results.append(e)
    return results

# ---- Flask routes ----

#keepalive route
@app.route("/health")
def health():
    return "OK", 200

@app.route("/count_tags")
def count_tags():
    if r:
        cached = r.get("tags")
        if cached: return jsonify(json.loads(cached))
    tags = compute_tag_counts()
    return jsonify(tags)

@app.route("/search")
def search():
    query = request.args.get("query", "")
    entries = get_cached_entries()
    return jsonify(boolean_search(entries, query))

@app.route("/atom-feed")
def atom_feed():
    try:
        loop = asyncio.get_event_loop()
        feed_data = loop.run_until_complete(fetch_feeds_async(feed_urls))
    except RuntimeError:
        feed_data = asyncio.run(fetch_feeds_async(feed_urls))
    entries = process_entries(feed_data)

    feed = Element("feed", xmlns="http://www.w3.org/2005/Atom")
    SubElement(feed, "title").text = "Aggregated Feed"
    for e in entries:
        entry_el = SubElement(feed, "entry")
        SubElement(entry_el, "title").text = e["title"]
        SubElement(entry_el, "link", href=e["link"])
        SubElement(entry_el, "published").text = e["published"].isoformat() if e["published"] else ""
    return tostring(feed, encoding="utf-8").decode("utf-8"), 200, {"Content-Type": "application/atom+xml"}

# ---- Scheduler ----
scheduler = BackgroundScheduler()

# ---- Scheduler ----
scheduler = BackgroundScheduler()
scheduler.add_job(func=compute_tag_counts, trigger="interval", hours=24)
scheduler.start()
logger.info("✅ Scheduler started")

atexit.register(lambda: scheduler.shutdown())



# ---- Main ----
if __name__ == "__main__":
    app.run(debug=True)
