"""Keepsake API: fetches media from public Instagram posts and reels.

Routes
  POST /api/info   {"urls": [...]}  -> media items for each link
  GET  /api/file   ?u=<cdn url>&name=<file name>&dl=1  -> streams one file
  POST /api/zip    {"items": [{"url": "...", "name": "..."}]} -> ZIP file
"""
import base64
import json
import os
import re
import tempfile
import time
import zipfile
from urllib.parse import urlparse

import requests
import yt_dlp
from flask import Flask, Response, abort, jsonify, request, send_file, stream_with_context
from flask_cors import CORS

app = Flask(__name__)

# Set ALLOWED_ORIGINS to your GitHub Pages address, e.g. https://yourname.github.io
origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
CORS(app, origins=origins)

MAX_LINKS = 10
MAX_ZIP_ITEMS = 30
MAX_FILE_BYTES = 150 * 1024 * 1024
CDN_SUFFIXES = (".cdninstagram.com", ".fbcdn.net")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
POST_RE = re.compile(
    r"instagram\.com/(?:[A-Za-z0-9_.]+/)?(p|reel|reels|tv)/([A-Za-z0-9_-]+)"
)

# Optional: paste the contents of a Netscape cookies.txt into the IG_COOKIES
# environment variable if Instagram starts asking for a login.
COOKIE_FILE = None
if os.environ.get("IG_COOKIES"):
    COOKIE_FILE = os.path.join(tempfile.gettempdir(), "ig_cookies.txt")
    with open(COOKIE_FILE, "w") as fh:
        fh.write(os.environ["IG_COOKIES"])

YDL_OPTS = {"quiet": True, "no_warnings": True, "skip_download": True}
if COOKIE_FILE:
    YDL_OPTS["cookiefile"] = COOKIE_FILE

# ---- tiny in-memory rate limit (per IP) ----
HITS = {}


def limited(ip, limit=15, window=600):
    now = time.time()
    recent = [t for t in HITS.get(ip, []) if now - t < window]
    if len(recent) >= limit:
        HITS[ip] = recent
        return True
    recent.append(now)
    HITS[ip] = recent
    return False


def client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or "unknown"


def safe_name(name):
    return re.sub(r"[^A-Za-z0-9._-]", "_", name or "instagram-media")[:100]


def is_cdn(url):
    p = urlparse(url or "")
    return p.scheme == "https" and (p.hostname or "").endswith(CDN_SUFFIXES)


# ---- extraction ----
def via_ytdlp(url, shortcode):
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        info = ydl.extract_info(url, download=False)
    entries = info.get("entries") or [info]
    items = []
    for i, e in enumerate(entries, 1):
        media = e.get("url")
        if not media and e.get("formats"):
            best = max(e["formats"], key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))
            media = best.get("url")
        if not media:
            continue
        ext = e.get("ext") or "mp4"
        is_video = ext in ("mp4", "webm", "mov", "m4v")
        items.append(
            {
                "url": media,
                "kind": "video" if is_video else "image",
                "thumb": e.get("thumbnail") or (None if is_video else media),
                "name": f"{shortcode}_{i}.{ext}",
            }
        )
    return {
        "title": (info.get("title") or "")[:90],
        "uploader": info.get("uploader") or info.get("channel") or "",
        "items": items,
    }


def items_from_post(post, prefix):
    """Turn an instaloader Post into a list of downloadable files."""
    sc = post.shortcode
    items = []
    if post.typename == "GraphSidecar":
        for i, node in enumerate(post.get_sidecar_nodes(), 1):
            if node.is_video:
                items.append({"url": node.video_url, "kind": "video", "thumb": node.display_url,
                              "name": f"{prefix}{sc}_{i}.mp4"})
            else:
                items.append({"url": node.display_url, "kind": "image", "thumb": node.display_url,
                              "name": f"{prefix}{sc}_{i}.jpg"})
    elif post.is_video:
        items.append({"url": post.video_url, "kind": "video", "thumb": post.url,
                      "name": f"{prefix}{sc}_1.mp4"})
    else:
        items.append({"url": post.url, "kind": "image", "thumb": post.url,
                      "name": f"{prefix}{sc}_1.jpg"})
    return items


def new_loader():
    import instaloader

    return instaloader.Instaloader(
        quiet=True,
        download_pictures=False,
        download_videos=False,
        save_metadata=False,
        max_connection_attempts=1,
        request_timeout=20,
    )


def via_instaloader(shortcode):
    import instaloader

    loader = new_loader()
    post = instaloader.Post.from_shortcode(loader.context, shortcode)
    return {
        "title": (post.caption or "")[:90],
        "uploader": post.owner_username,
        "items": items_from_post(post, ""),
    }


def fetch_post(url):
    m = POST_RE.search(url)
    if not m:
        return {"source": url, "error": "This isn't a post or reel link. Use a link like instagram.com/p/… or instagram.com/reel/…"}
    shortcode = m.group(2)
    canonical = f"https://www.instagram.com/p/{shortcode}/"
    result = None
    try:
        result = via_ytdlp(canonical, shortcode)
    except Exception:
        result = None
    if not result or not result["items"]:
        try:
            result = via_instaloader(shortcode)
        except Exception:
            return {"source": url, "error": "Couldn't fetch this post. It may be private, deleted, or Instagram is limiting the server. Try again in a few minutes."}
    result["source"] = url
    return result


# ---- routes ----
@app.get("/")
def health():
    return jsonify(status="ok")


@app.post("/api/info")
def info():
    if limited(client_ip()):
        return jsonify(error="Too many requests. Wait a few minutes and try again."), 429
    data = request.get_json(silent=True) or {}
    urls = [u.strip() for u in data.get("urls", []) if isinstance(u, str) and u.strip()][:MAX_LINKS]
    if not urls:
        return jsonify(error="Paste at least one post or reel link."), 400
    return jsonify(results=[fetch_post(u) for u in urls])


PAGE_SIZE = 30
USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


def enc_cursor(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).decode()


def dec_cursor(s):
    return json.loads(base64.urlsafe_b64decode(s.encode()))


@app.get("/api/profile")
def profile():
    """One page (30 posts) of a public profile. Pass the returned `next` as `cursor` for the next page."""
    if limited(client_ip(), limit=40):
        return jsonify(error="Too many requests. Wait a few minutes and try again."), 429

    raw = request.args.get("username", "").strip().lstrip("@")
    m = re.search(r"instagram\.com/([A-Za-z0-9._]+)", raw)
    username = (m.group(1) if m else raw).lower()
    if not USERNAME_RE.match(username):
        return jsonify(error="That doesn't look like an Instagram username."), 400

    import instaloader

    loader = new_loader()
    try:
        prof = instaloader.Profile.from_username(loader.context, username)
    except instaloader.ProfileNotExistsException:
        return jsonify(error=f"No account named @{username} was found."), 404
    except Exception:
        return jsonify(error="Instagram didn't answer. The server may be rate-limited. Wait a few minutes and try again."), 503

    if prof.is_private:
        return jsonify(error=f"@{username} is private. Only public profiles can be loaded."), 403

    posts = []
    it = prof.get_posts()
    cursor = request.args.get("cursor")
    try:
        if cursor:
            it.thaw(instaloader.FrozenNodeIterator(**dec_cursor(cursor)))
        for post in it:
            try:
                items = items_from_post(post, f"{username}_")
            except Exception:
                continue
            kind = "carousel" if len(items) > 1 else (items[0]["kind"] if items else "image")
            posts.append({
                "id": post.shortcode,
                "thumb": post.url,
                "kind": kind,
                "count": len(items),
                "date": post.date_utc.strftime("%Y-%m-%d"),
                "caption": (post.caption or "")[:80],
                "items": items,
            })
            if len(posts) >= PAGE_SIZE:
                break
        next_cursor = enc_cursor(it.freeze()._asdict()) if len(posts) >= PAGE_SIZE else None
    except Exception:
        if not posts:
            return jsonify(error="Couldn't load posts. Instagram may be limiting the server. Wait a few minutes and try again."), 503
        next_cursor = None  # return what we got; the user can retry for the rest

    return jsonify(
        username=username,
        full_name=prof.full_name,
        total=prof.mediacount,
        page_size=PAGE_SIZE,
        posts=posts,
        next=next_cursor,
    )


@app.get("/api/file")
def file():
    url = request.args.get("u", "")
    if not is_cdn(url):
        abort(400)
    upstream = requests.get(url, stream=True, timeout=20, headers={"User-Agent": UA}, allow_redirects=False)
    if upstream.status_code != 200:
        abort(502)
    headers = {"Content-Type": upstream.headers.get("Content-Type", "application/octet-stream")}
    if request.args.get("dl") == "1":
        headers["Content-Disposition"] = f'attachment; filename="{safe_name(request.args.get("name"))}"'
    return Response(stream_with_context(upstream.iter_content(65536)), headers=headers)


@app.post("/api/zip")
def make_zip():
    if limited(client_ip(), limit=10):
        return jsonify(error="Too many requests. Wait a few minutes and try again."), 429
    data = request.get_json(silent=True) or {}
    items = [i for i in data.get("items", []) if isinstance(i, dict)][:MAX_ZIP_ITEMS]
    if not items:
        return jsonify(error="Select at least one file."), 400
    tmp = tempfile.TemporaryFile()
    used = set()
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:
        for item in items:
            url = item.get("url", "")
            if not is_cdn(url):
                continue
            name = safe_name(item.get("name"))
            while name in used:
                name = "dup_" + name
            used.add(name)
            r = requests.get(url, stream=True, timeout=30, headers={"User-Agent": UA}, allow_redirects=False)
            if r.status_code != 200:
                continue
            size = 0
            with zf.open(name, "w") as out:
                for chunk in r.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        break
                    out.write(chunk)
    tmp.seek(0)
    return send_file(tmp, mimetype="application/zip", as_attachment=True, download_name="keepsake.zip")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
