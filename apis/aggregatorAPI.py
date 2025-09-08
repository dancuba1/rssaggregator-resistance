from flask import Flask, request, jsonify
from collections import defaultdict
from datetime import datetime
import feedparser
import aiohttp
import asyncio
from xml.etree.ElementTree import Element, SubElement, tostring
from flask_cors import CORS
import re
import hashlib
from cachetools import TTLCache
import requests  # Missing import

app = Flask(__name__)
CORS(app)

"""""
feed_urls = list(set([
    "https://archive.org/services/collection-rss.php?collection=resistancearchive",
    "https://archive.org/services/collection-rss.php?collection=ingabystramstrikingart",
    "https://archive.org/services/collection-rss.php?query=subject:Chiara_Contrino",
    "https://www.youtube.com/feeds/videos.xml?playlist_id=PLmEoLllcfuX3iLGuSVVeri7ZEfud_j-su",
    "https://www.youtube.com/feeds/videos.xml?playlist_id=PLmEoLllcfuX0PzadF1L72XBw8mLpejzrY",
    "https://www.youtube.com/feeds/videos.xml?playlist_id=PLmEoLllcfuX21XJ7pjAWCaJKThHXOWPjb",
    "https://www.youtube.com/feeds/videos.xml?playlist_id=PLmEoLllcfuX375LTWGoOIHgDty4Cs6agg",
    "https://www.youtube.com/feeds/videos.xml?playlist_id=PLmEoLllcfuX3Bi3orWOkZRiPa7m7wKbRL",
    "https://www.youtube.com/feeds/videos.xml?playlist_id=PLmEoLllcfuX3lpMK8PoZTke2DsYbqCJMZ",
    "https://www.youtube.com/feeds/videos.xml?playlist_id=PLmEoLllcfuX0yx5BL-sFjGu3bZIEKmnNq",
    "https://www.flickr.com/services/feeds/photoset.gne?nsid=8933893@N08&set=72157623673144706&lang=en-us&format=atom",
    "https://www.flickr.com/services/feeds/photoset.gne?nsid=8933893@N08&set=72157692538977302&lang=en-us&format=atom",
    "https://www.flickr.com/services/feeds/photoset.gne?nsid=8933893@N08&set=72157600354803923&lang=en-us&format=atom",
    "https://www.flickr.com/services/feeds/photoset.gne?nsid=8933893@N08&set=72157600356404760&lang=en-us&format=atom",
    "https://www.flickr.com/services/feeds/photoset.gne?nsid=8933893@N08&set=72157600357938530&lang=en-us&format=atom",
    "https://www.flickr.com/services/feeds/photoset.gne?nsid=8933893@N08&set=72157604489309701&lang=en-us&format=atom",
    "https://www.flickr.com/services/feeds/photoset.gne?nsid=8933893@N08&set=72157604586597656&lang=en-us&format=atom",
    "https://www.flickr.com/services/feeds/photoset.gne?nsid=8933893@N08&set=72157604184970480&lang=en-us&format=atom"
]))
"""


import os
print("Current working directory:", os.getcwd())
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
file_name = "feedurls.txt"

def load_feed_urls(file_path="feedurls.txt"):
    file_path = os.path.join(BASE_DIR, file_name)  # look inside /apis/
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip()]
        return list(set(urls))  # remove duplicates
    except FileNotFoundError:
        print(f"⚠️ Feed URL file '{file_path}' not found. Using empty list.")
        return []


feed_urls = load_feed_urls()

FLICKR_API_KEY = "715d330285540544f7323bc79dd188c2"
cache = TTLCache(maxsize=100, ttl=3600)  # Cache with 1-hour TTL

# Async functions
async def fetch_url(session, url):
    try:
        async with session.get(url, timeout=10) as response:
            return url, await response.text()
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return url, None

async def fetch_feeds_async(urls):
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_url(session, url) for url in urls]
        responses = await asyncio.gather(*tasks)
        return {url: feedparser.parse(content) for url, content in responses if content}

@app.route("/count_tags", methods=["GET"])
def process_and_count_tags():
    """Process feed data and return a dictionary of tag counts."""
    # Fetch feed data asynchronously
    feed_data = asyncio.run(fetch_feeds_async(feed_urls)); # Replace with your actual feed URLs
    
    tag_count = defaultdict(int)
    
    # Process feed data
    for url, feed in feed_data.items():
        for entry in feed.get("entries", []):
            tags = [tag["term"] for tag in entry.get("tags", [])]
            for tag in tags:
                if not (tag.startswith("texts/") or tag.startswith("image/")):
                                tag_count[tag] += 1
    # Return the tag counts as a JSON response
    return jsonify(tag_count)
def process_entries(feed_data):
    entries = []
    for url, feed in feed_data.items():
        for entry in feed.entries:
            youtube_tags = []
            youtube_thumbnail = None

            if "youtube.com" in entry.link:
                video_id = extract_youtube_video_id(entry.link)
                print("VIDEO ID     :    " + video_id)
                if video_id:
                    youtube_tags = get_youtube_tags(video_id)
                    youtube_thumbnail = get_youtube_thumbnail(video_id)
            processed_entry = {
                "title": entry.title,
                "link": entry.link,
                "published": datetime(*entry.published_parsed[:6]) if entry.get("published_parsed") else None,
                "tags": [tag.term for tag in getattr(entry, "tags", [])] + youtube_tags,
                "thumbnail": youtube_thumbnail if youtube_thumbnail else None,
            }
            #rint("Processed entry:", processed_entry)  # Debug output
            entries.append(processed_entry)
    return sorted(entries, key=lambda x: x["published"], reverse=True)



def extract_youtube_video_id(url):
    """Extracts video ID from YouTube URLs"""
    match = re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})", url)
    return match.group(1) if match else None

YOUTUBE_API_KEY = "AIzaSyCyLv9Mmv0l9C6KAE9lKD_im7WfyFErUaQ"

def get_youtube_tags(video_id):
    """Fetch YouTube video tags using the API."""
    if not video_id:
        return []

    url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={video_id}&key={YOUTUBE_API_KEY}"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
      

        if "items" in data and len(data["items"]) > 0:
            print(data)
            return data["items"][0]["snippet"].get("tags", [])  # Returns list of tags or empty list
    except requests.RequestException as e:
        print(f"Error fetching YouTube tags: {e}")

    return []

def deduplicate(entries):
    seen_links = set()
    unique_entries = []
    for entry in entries:
        if entry["link"] not in seen_links:
            seen_links.add(entry["link"])
            unique_entries.append(entry)
    return unique_entries

@app.route("/search", methods=["GET"])
def search():
    print("In search")
    query = request.args.get("query", "")
    feed_data = asyncio.run(fetch_feeds_async(feed_urls))
    entries = process_entries(feed_data)
    unique_entries = deduplicate(entries)
    results = boolean_search(unique_entries, query)  
    return jsonify(results)

def extract_photo_id(flickr_url):
    """Extract photo ID from a Flickr URL."""
    match = re.search(r'flickr\.com/photos/[^/]+/(\d+)', flickr_url)
    return match.group(1) if match else None

def get_flickr_thumbnail(photo_id):
    """Fetch the thumbnail for a Flickr photo."""
    if not photo_id:  # Ensure valid photo ID
        return None

    try:
        api_url = f"https://www.flickr.com/services/rest/?method=flickr.photos.getSizes&api_key={FLICKR_API_KEY}&photo_id={photo_id}&format=json&nojsoncallback=1"
        response = requests.get(api_url, timeout=5)  # Add timeout
        response.raise_for_status()  # Handle HTTP errors
        data = response.json()
        if data.get("stat") != "ok":
            return None
        
        # Look for the 'Small' size thumbnail
        sizes = data.get("sizes", {}).get("size", [])
        thumbnail = next((size for size in sizes if size["label"] == "Small"), None)
        return thumbnail["source"] if thumbnail else None
    except requests.RequestException as e:
        print("Error fetching Flickr thumbnail:", e)
        return None

    

def clean_query(query):
    cleaned_query = re.sub(r'[^\w\s\-"()|,]', '', query).strip()  # Escaped hyphen
    cleaned_query = cleaned_query.replace("(", " ( ").replace(")", " ) ").replace(",", " , ").replace("|", " | ").replace("-", " - ")  # Add spaces around operators
    cleaned_query = " ".join(cleaned_query.split()) #remove extra spaces
    print(f"Cleaned query: {cleaned_query}")
    return cleaned_query.lower()  


def parse_query(query):
    query = clean_query(query)
    tokens = re.findall(r'"[^"]+"|\S+|\(|\)|,|\||-', query)  # Correct regex to handle quotes
    print(f"Tokens: {tokens}")


    def parse_expression(tokens):
        expression = parse_term(tokens)
        while tokens and tokens[0] == '|':
            tokens.pop(0)  # Consume '|'
            right = parse_term(tokens)
            expression = ('|', expression, right)  # Create OR node in the tree
        return expression

    def parse_term(tokens):
        term = parse_factor(tokens)
        while tokens and tokens[0] == ',':
            tokens.pop(0)  # Consume ','
            right = parse_factor(tokens)
            term = (',', term, right)  # Create AND node in the tree
        return term  # Crucial: Return the term, even if no ',' was found

    def parse_factor(tokens):
        if tokens and tokens[0] == '(':
            tokens.pop(0)  # Consume '('
            expression = parse_expression(tokens)
            tokens.pop(0)  # Consume ')'
            return expression
        elif tokens and tokens[0] == '-':
            tokens.pop(0)  # Consume '-'
            factor = parse_factor(tokens)  # Recursively parse the factor after '-'
            return ('-', factor)  # Correctly create the NOT node
        elif tokens:
            term = tokens.pop(0)
            return term.strip('"').lower()  # Term
        return None

    parsed_query = parse_expression(tokens)
    print(f"Parsed expression tree: {parsed_query}")  # Debug print
    return parsed_query

def evaluate_query(entry, parsed_query):
    tags = {tag.lower().strip() for tag in entry['tags']}
    print(f"Entry tags (processed): {tags}")

    def evaluate(expression):
        if isinstance(expression, tuple):  # Operator node (AND, OR, NOT)
            op = expression[0]
            if op == '-':  # NOT
                return not evaluate(expression[1])
            else:  # AND or OR
                left = evaluate(expression[1])
                right = evaluate(expression[2])
                if op == '|':
                    return left or right
                elif op == ',':
                    return left and right
        elif isinstance(expression, str):  # Term
            return expression in tags
        return False  # Handle unexpected types (shouldn't happen)

    result = evaluate(parsed_query)
    print(f"Final query result: {result}")
    return result

def boolean_search(entries, query):
    """Perform boolean search on entries based on the query."""
    print(f"Starting boolean search for query: {query}") # Debug print
    parsed_query = parse_query(query)

    results = []
    for entry in entries:
        if evaluate_query(entry, parsed_query):
            # Thumbnail logic (unchanged)
            if "archive.org/details" in entry["link"]:
                item_id = entry["link"].split("/")[-1]
                thumbnail_url = f"https://archive.org/services/img/{item_id}"
                entry["thumbnail"] = thumbnail_url
            elif "flickr.com" in entry["link"]:
                photo_id = extract_photo_id(entry["link"])  # Assuming extract_photo_id is defined
                if photo_id:
                    thumbnail_url = get_flickr_thumbnail(photo_id)  # Assuming get_flickr_thumbnail is defined
                    if thumbnail_url:
                        entry["thumbnail"] = thumbnail_url
            elif "youtube.com" in entry["link"] or "you.tube" in entry["link"]:
                video_id = extract_youtube_video_id(entry["link"])
                if(video_id):
                    thumbnail_url = get_youtube_thumbnail(video_id)
                    if thumbnail_url:
                        entry["thumbnail"] = thumbnail_url
            results.append(entry)
    print(f"Search results: {results}")  # Debug output
    return results

youtube_thumbnail_cache = TTLCache(maxsize=1000, ttl=3600)  # 3600 seconds = 1 hour

def get_youtube_thumbnail(video_id):
    if not video_id:
        return None

    # Check if thumbnail is already cached
    if video_id in youtube_thumbnail_cache:
        return youtube_thumbnail_cache[video_id]

    # Generate the thumbnail URL
    thumbnail_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
    
    # Cache the result
    youtube_thumbnail_cache[video_id] = thumbnail_url
    return thumbnail_url

@app.route("/atom-feed", methods=["GET"])
def atom_feed():
    feed_data = asyncio.run(fetch_feeds_async(feed_urls))
    entries = process_entries(feed_data)
    feed = Element("feed", xmlns="http://www.w3.org/2005/Atom")
    SubElement(feed, "title").text = "Aggregated Feed"
    for entry in entries:
        entry_element = SubElement(feed, "entry")
        SubElement(entry_element, "title").text = entry["title"]
        SubElement(entry_element, "link", href=entry["link"])
        SubElement(entry_element, "published").text = entry["published"].isoformat() if entry["published"] else ""
    atom_xml = tostring(feed, encoding="utf-8").decode("utf-8")
    return atom_xml, 200, {"Content-Type": "application/atom+xml"}

if __name__ == "__main__":
    app.run(debug=True)
