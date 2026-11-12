"""Link previews: the picture and title card under a message with a link in it.

Like the iPhone, Lime downloads the linked page itself and reads the preview tags that sites
put in it for this purpose (Open Graph's og:title and og:image, or Twitter's twitter:*). Each
preview is saved in the cache, so a link is only downloaded once.
"""
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s<>\"]+", re.I)
TRAILING = ".,;:!?'\")]}”’"  # punctuation after a link belongs to the sentence, not the link

# Sites send their preview tags to link-preview fetchers; a plain browser sometimes gets a page
# built by JavaScript with no tags in it. This is the kind of User-Agent the iPhone uses.
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
              "(KHTML, like Gecko) Version/17.0 Safari/605.1.15 facebookexternalhit/1.1 Facebot Twitterbot/1.0")
PAGE_LIMIT = 2 * 1024 * 1024    # preview tags are in the <head>; don't read a whole huge page
IMAGE_LIMIT = 8 * 1024 * 1024
TIMEOUT = 10
RETRY_FAILED = 24 * 60 * 60     # try a link that didn't work again after a day
RETRY_IMAGE = 60 * 60           # try a picture again after an hour if the site refused it


def find_url(text):
    """The first link in a message, with "https://" added if it was left off, or None."""
    m = URL_RE.search(text or "")
    if not m:
        return None
    url = m.group(0)
    while url and url[-1] in TRAILING:
        # keep a closing bracket that matches one inside the link, as in Wikipedia links
        if url[-1] == ")" and url.count("(") >= url.count(")"):
            break
        url = url[:-1]
    if not url.lower().startswith("http"):
        url = "https://" + url
    return url


def domain(url):
    host = urllib.parse.urlsplit(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


class _MetaParser(HTMLParser):
    """Collects <meta> tags and the <title> from a page's <head>."""

    def __init__(self):
        super().__init__()
        self.meta, self.title, self.in_title = {}, "", False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content") and key not in self.meta:  # the first one wins
                self.meta[key] = a["content"].strip()
        elif tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag == "head":
            raise StopIteration  # everything we need is in the <head>

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def google_maps_place(url):
    """The place name in a Google Maps link, e.g. "Space Needle", or None."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if not (host.startswith("maps.google.") or "google." in host and parts.path.startswith("/maps")):
        return None
    m = re.search(r"/maps/(?:place|search)/([^/@]+)", parts.path)
    if m:
        name = m.group(1)
    else:
        query = urllib.parse.parse_qs(parts.query)
        name = (query.get("q") or query.get("query") or [None])[0]
        if not name:
            return None
    return urllib.parse.unquote_plus(name).strip() or None


def parse(html, url):
    """{"url", "title", "site", "image"} for a page; title and image may be None."""
    p = _MetaParser()
    try:
        p.feed(html)
    except StopIteration:
        pass
    meta = p.meta
    title = meta.get("og:title") or meta.get("twitter:title") or " ".join(p.title.split()) or None
    image = meta.get("og:image") or meta.get("og:image:url") or meta.get("twitter:image")
    site = meta.get("og:site_name") or domain(url)
    if image:
        image = urllib.parse.urljoin(url, image)
    place = google_maps_place(url)
    if place or title == "Google Maps":
        # Google's title is always just "Google Maps"; the place name is in the link itself
        title, site = place or title, "Google Maps"
        if image and "center=0.0%2C0.0" in image:  # Google didn't know where; a map of the ocean
            image = None
    return {"url": url, "title": title, "site": site, "image": image}


def download(url, limit):
    """(final URL after redirects, content type, up to `limit` bytes of the body)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.geturl(), resp.headers.get("Content-Type", ""), resp.read(limit)


class Previews:
    """Link previews, cached on disk in `folder`: a .json file per link plus its picture."""

    def __init__(self, folder, download=download):
        self.folder = folder
        self.download = download  # tests pass a fake, so they don't need the internet
        os.makedirs(folder, exist_ok=True)

    def path(self, url, ext):
        return os.path.join(self.folder, hashlib.sha1(url.encode()).hexdigest() + ext)

    def cached(self, url):
        """The saved preview, None if there's none (yet), or {"failed": True} if there's nothing to show."""
        try:
            with open(self.path(url, ".json")) as f:
                preview = json.load(f)
        except (OSError, ValueError):
            return None
        if preview.get("failed") and time.time() - preview.get("ts", 0) > RETRY_FAILED:
            return None
        if preview.get("image_failed") and time.time() - preview["image_failed"] > RETRY_IMAGE:
            return None
        return preview

    def fetch(self, url):
        """Download and save the preview for `url`. Slow: call it from a background thread."""
        try:
            final, kind, body = self.download(url, PAGE_LIMIT)
            if "html" not in kind.lower():
                raise ValueError("not a web page: " + kind)
            charset = re.search(r"charset=([\w-]+)", kind)
            preview = parse(body.decode(charset.group(1) if charset else "utf-8", "replace"), final)
            preview["url"] = url  # the link as it was sent, so it's found again in the cache
            try:
                preview["image_path"] = self.fetch_image(url, preview.pop("image"))
            except Exception:  # noqa: BLE001 - e.g. "too many requests": show the title, retry the picture later
                preview["image_path"], preview["image_failed"] = None, time.time()
            if not preview["title"] and not preview["image_path"]:
                raise ValueError("no preview on this page")
        except Exception:  # noqa: BLE001 - a site can fail in a hundred ways; no preview, no harm
            preview = {"url": url, "failed": True, "ts": time.time()}
        with open(self.path(url, ".json"), "w") as f:
            json.dump(preview, f)
        return preview

    def fetch_image(self, url, image):
        """Path of the saved picture, or None if there's none to use. Raises if the download failed."""
        if not image:
            return None
        _, kind, body = self.download(image, IMAGE_LIMIT)
        if not kind.lower().startswith("image/") or len(body) >= IMAGE_LIMIT:
            return None
        path = self.path(url, ".img")
        with open(path, "wb") as f:
            f.write(body)
        return path
