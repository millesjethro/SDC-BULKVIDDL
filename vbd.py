#!/usr/bin/env python3
"""
Video Bulk Downloader
A local app around yt-dlp. Standard library only (Python 3.8+).
Put yt-dlp.exe (and optionally ffmpeg.exe) next to this file, then run it.
"""
import csv
import datetime as dt
import json
import http.cookiejar
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
IS_WIN = os.name == "nt"
NOWIN = 0x08000000 if IS_WIN else 0  # CREATE_NO_WINDOW
TOKEN = secrets.token_hex(16)
LOCK = threading.RLock()
ITEMS = []
PROCS = {}
CHROME_LINK = {"code": "", "expires": 0, "sessions": {}}
CHROME_COOKIE_NAMES = {
    "instagram": {"sessionid", "csrftoken"},
    "threads": {"sessionid", "csrftoken", "ds_user_id", "mid", "ig_did", "ig_nrcb"},
    "facebook": {"c_user", "xs", "datr", "sb", "fr"},
}
CHROME_REQUIRED = {"instagram": {"sessionid"}, "threads": {"sessionid"},
                   "facebook": {"c_user", "xs"}}
THUMBS = {}
META_POOL = ThreadPoolExecutor(max_workers=4)
SETTINGS_FILE = os.path.join(BASE, "settings.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
STATE_META = {"ytdlp_version": "", "last_ping": time.time(), "port": 0}


# --------------------------------------------------------------------------
# tools & settings
# --------------------------------------------------------------------------
def find_ytdlp():
    env = os.environ.get("VBD_YTDLP")
    if env and os.path.isfile(env):
        return env
    for d in (BASE, os.getcwd()):
        for n in ("yt-dlp.exe", "yt-dlp"):
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    return shutil.which("yt-dlp")


def find_ffmpeg():
    for d in (os.path.join(BASE, "ffmpeg"), BASE, os.path.join(BASE, "bin")):
        for n in ("ffmpeg.exe", "ffmpeg"):
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    return shutil.which("ffmpeg")


def default_folder_name():
    return "SocialMediaBackup_" + dt.date.today().strftime("%Y-%m-%d")


SETTINGS = {
    "folder": os.path.join(os.path.expanduser("~"), "Downloads"),
    "folder_name": default_folder_name(),
    "zip": True,
    "farmers": False,
    "date_format": "mdy",
    "quality": "best",
    "parallel": 2,
    "hires": False,
    "cookies_browser": "",
    "threads_cookie": "",
    "instagram_cookie": "",
    "instagram_browser": "",
}
FF = {"ok": False}


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        for k in SETTINGS:
            if k in d:
                SETTINGS[k] = d[k]
    except Exception:
        pass
    if not isinstance(SETTINGS["date_format"], str) or SETTINGS["date_format"] not in DATE_FORMATS:
        SETTINGS["date_format"] = "mdy"
    if str(SETTINGS.get("folder_name", "")).startswith("SocialMediaBackup_"):
        SETTINGS["folder_name"] = default_folder_name()


def save_settings(settings):
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=BASE,
                                         suffix=".tmp", delete=False) as f:
            temp_path = f.name
            json.dump(settings, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, SETTINGS_FILE)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


# --------------------------------------------------------------------------
# naming
# --------------------------------------------------------------------------
SOURCE_LABELS = {
    "youtube": "YouTube", "youtu": "YouTube", "tiktok": "TikTok",
    "instagram": "Instagram", "facebook": "Facebook", "fb": "Facebook",
    "twitter": "X", "x": "X", "reddit": "Reddit", "vimeo": "Vimeo",
    "twitch": "Twitch", "threads": "Threads", "pinterest": "Pinterest",
    "linkedin": "LinkedIn", "snapchat": "Snapchat", "dailymotion": "Dailymotion",
    "bilibili": "Bilibili", "rumble": "Rumble", "telegram": "Telegram",
    "kick": "Kick", "bsky": "Bluesky",
}


def guess_source(url):
    host = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    labels = host.split(".")[:-1] or host.split(".")
    for lab in labels:
        if lab in SOURCE_LABELS:
            return SOURCE_LABELS[lab]
    lab = labels[-1] if labels else "Social Media"
    return (lab[:1].upper() + lab[1:]) if lab else "Social Media"


BAD = re.compile(r'[<>:"|?*\x00-\x1f]')


def sanitize(s, limit=180):
    s = (s or "").replace("/", "-").replace("\\", "-")
    s = BAD.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit].rstrip(". ")


def today_str():
    return dt.date.today().strftime("%m-%d-%Y")


DATE_FORMATS = {"long": None, "iso": "%Y-%m-%d", "mdy": "%m-%d-%Y"}
MONTH_NAMES = ("January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December")


def format_posted_date(value, date_format):
    if isinstance(value, str):
        try:
            if re.fullmatch(r"\d{8}", value):
                value = dt.datetime.strptime(value, "%Y%m%d").date()
            else:
                value = dt.date.fromisoformat(value)
        except ValueError:
            return ""
    if not isinstance(value, dt.date):
        return ""
    if date_format == "long":
        return f"{MONTH_NAMES[value.month - 1]} {value.day}, {value.year}"
    return value.strftime(DATE_FORMATS.get(date_format, DATE_FORMATS["mdy"]))


def final_name(it, settings=None, media_index=None):
    settings = SETTINGS if settings is None else settings
    date_format = settings["date_format"]
    name = sanitize(it["name"])
    posted_date = it["upload_date"]
    if it.get("ig_story_dates"):
        if media_index is None:
            media_index = next((i for i, on in enumerate(it["sel"]) if on), 0)
        posted_date = it["ig_story_dates"][media_index]
    posted = format_posted_date(posted_date, date_format) or "UNKNOWN"
    if settings["farmers"]:
        if name and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", name):
            name = format_posted_date(name, date_format) or name
        captured = format_posted_date(dt.date.today(), date_format)
        return sanitize(f'{it["source"]} video captured {captured}, and posted {name or posted}')
    return name or posted


# --------------------------------------------------------------------------
# queue
# --------------------------------------------------------------------------
def get_item(iid):
    with LOCK:
        for it in ITEMS:
            if it["id"] == iid:
                return it
    return None


def norm_url(u):
    u = u.strip().strip("<>\"'")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", u, re.I):
        u = "https://" + u
    # ?img_index=N only says which slide was open; drop it so the whole carousel is fetched
    pr = urllib.parse.urlsplit(u)
    if "img_index" in pr.query:
        q = [kv for kv in urllib.parse.parse_qsl(pr.query, keep_blank_values=True) if kv[0] != "img_index"]
        u = urllib.parse.urlunsplit(pr._replace(query=urllib.parse.urlencode(q)))
    return u


def get_slide(u):
    """slide number from ?img_index=N (1-based), or 0"""
    try:
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(u).query))
        return max(0, int(q.get("img_index", 0)))
    except ValueError:
        return 0


def add_item(url, name="", highlight_start=None, highlight_end=None):
    slide = get_slide(url.strip().strip("<>\"'"))
    url = norm_url(url)
    if x_status_id(url):
        slide = 0
    if ig_story_title(url) != "Instagram Highlight":
        highlight_start = highlight_end = None
    with LOCK:
        for it in ITEMS:
            if (it["url"] == url and it["status"] != "done"
                    and it.get("highlight_start") == highlight_start
                    and it.get("highlight_end") == highlight_end and it.get("slide", 0) == slide):
                return None
        it = dict(id=uuid.uuid4().hex[:10], url=url, name=(name or "").strip(),
                  source=guess_source(url), title="", thumb="", duration=0,
                  uploader="", upload_date="", status="fetching", progress=0.0,
                  speed="", eta="", error="", outfile="", slide=slide,
                  highlight_start=highlight_start, highlight_end=highlight_end)
        ITEMS.append(it)
    META_POOL.submit(fetch_meta, it["id"])
    return it


def last_error(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    errs = [l for l in lines if "ERROR" in l]
    msg = (errs or lines or ["Unknown error"])[-1]
    msg = re.sub(r"^.*?ERROR:\s*", "", msg)
    msg = re.sub(r"^\[[^\]]+\]\s*[\w\-]+:\s*", "", msg)
    return msg[:220]


def x_status_id(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in (
            "x.com", "www.x.com", "mobile.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"):
        return None
    match = re.fullmatch(r"/(?:[^/]+|i/web)/status/(\d+)/?", parsed.path)
    return match.group(1) if match else None


def x_post_media(post_id):
    # X's public embed endpoint returns the parent and quote as separate objects.
    endpoint = "https://cdn.syndication.twimg.com/tweet-result"
    query = urllib.parse.urlencode({"id": post_id, "token": "0.123"})
    req = urllib.request.Request(endpoint + "?" + query, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as response:
        post = json.load(response)
    if post.get("id_str") != post_id:
        raise RuntimeError("X did not return media for this post.")

    media = []
    for source, entry in (("Original post", post), ("Quoted post", post.get("quoted_tweet") or {})):
        counts = {"video": 0, "animated_gif": 0}
        for detail in entry.get("mediaDetails") or []:
            kind = detail.get("type")
            if kind not in counts:
                continue
            counts[kind] += 1
            variants = []
            for variant in (detail.get("video_info") or {}).get("variants", []):
                url = variant.get("url") or ""
                parsed = urllib.parse.urlsplit(url)
                if (variant.get("content_type") == "video/mp4" and parsed.scheme == "https"
                        and parsed.netloc == "video.twimg.com" and parsed.path.endswith(".mp4")):
                    size = re.search(r"/(\d+)x(\d+)/", parsed.path)
                    variants.append((int(variant.get("bitrate") or 0), int(size[2]) if size else 0, url))
            if variants:
                label = "GIF" if kind == "animated_gif" else "Video"
                media.append(dict(kind=kind, label=f"{label} {counts[kind]} · {source}",
                                  original=source == "Original post", variants=sorted(variants, reverse=True)))
    if not media:
        raise RuntimeError("X did not provide any downloadable videos or GIFs for this post.")
    return post, media


def fetch_x_meta(it, post_id):
    try:
        post, media = x_post_media(post_id)
        with LOCK:
            if it["status"] == "fetching":
                choices = {m["label"]: on for m, on in zip(it.get("media", []), it.get("sel", []))}
                created = post.get("created_at", "")
                upload_date = created[:10].replace("-", "") if re.match(r"\d{4}-\d{2}-\d{2}", created) else ""
                it.update(title=post.get("text") or "X post",
                          uploader=(post.get("user") or {}).get("screen_name") or "",
                          upload_date=upload_date, media=media,
                          sel=[choices.get(m["label"], m["original"]) for m in media],
                          status="ready", error="")
    except Exception as e:
        with LOCK:
            if it["status"] == "fetching":
                it.update(status="error", error=str(e)[:220] or "Could not read this X post.")


def fetch_meta(iid):
    it = get_item(iid)
    if not it:
        return
    post_id = x_status_id(it["url"])
    if post_id:
        fetch_x_meta(it, post_id)
        return
    if is_threads(it["url"]):
        try:
            info = threads_info(it["url"], SETTINGS)
            med = info["media"]
            with LOCK:
                if get_item(iid) and it["status"] == "fetching":
                    it.update(title="Threads - @" + info["author"], uploader="@" + info["author"],
                              upload_date=info["upload_date"],
                              thumb=next((m["thumb"] for m in med if m["thumb"]), ""),
                              media=med, sel=[True] * len(med), status="ready", error="")
        except Exception as e:
            with LOCK:
                if get_item(iid):
                    it.update(status="error", error=str(e)[:220] or "Could not read this Threads link")
        return
    if is_facebook_story(it["url"]):
        try:
            facebook_story_video(it["url"], dict(SETTINGS))
            with LOCK:
                if it["status"] == "fetching":
                    it.update(title="Facebook Story", status="ready", error="")
        except Exception as e:
            with LOCK:
                if it["status"] == "fetching":
                    it.update(status="error", error=str(e)[:220])
        return
    story_title = ig_story_title(it["url"])
    if story_title:
        try:
            media = ig_story_media(it["url"], dict(SETTINGS),
                                   it.get("highlight_start"), it.get("highlight_end"))
            with LOCK:
                if get_item(iid) and it["status"] == "fetching":
                    choices = dict(zip(it.get("ig_story_ids", ()), it.get("sel", ())))
                    it.update(title=story_title, media=[kind for _, kind, _ in media],
                              ig_story_ids=[mid for mid, _, _ in media],
                              ig_story_dates=[date for _, _, date in media],
                              sel=[choices.get(mid, True) for mid, _, _ in media], status="ready", error="")
        except Exception as e:
            with LOCK:
                if get_item(iid) and it["status"] == "fetching":
                    it.update(status="error", error=str(e)[:220])
        return
    yt = find_ytdlp()
    if not yt:
        with LOCK:
            it.update(status="error", error="yt-dlp not found next to the app")
        return
    try:
        fetch_meta_generic(iid, it, yt)
    except Exception as e:
        with LOCK:
            if get_item(iid):
                it.update(status="error", error=str(e)[:220] or "Could not read this link")


# --------------------------------------------------------------------------
# download job
# --------------------------------------------------------------------------
RUN = {"active": False, "phase": "idle", "total": 0, "finished": 0, "saved": 0,
       "failed": 0, "cancel": threading.Event(), "run_id": 0, "result": None,
       "used": set()}


def _owns(fname, base):
    """True if fname is base.ext or base_NN.ext (numbered carousel item)."""
    return re.match(re.escape(base.lower()) + r"(_\d+)?\.", fname.lower()) is not None


def unique_base(outdir, base):
    used = RUN["used"]
    try:
        existing = os.listdir(outdir)
    except OSError:
        existing = []
    cand, n = base, 1
    while cand.lower() in used or any(_owns(f, cand) for f in existing):
        n += 1
        cand = f"{base} ({n})"
    used.add(cand.lower())
    return cand


def build_cmd(yt, it, outdir, base, s, facebook_login=False, x_urls=None):
    ff = find_ffmpeg() if (s.get("hires") and FF["ok"]) else None
    q = s.get("quality", "best")
    h = {"1080": 1080, "720": 720, "480": 480, "360": 360}.get(q)
    cap = f"[height<=?{h}]" if h else ""
    cmd = [yt, "--no-playlist", "--newline", "--no-colors", "--no-warnings",
           "--progress", "--encoding", "utf-8", "--retries", "5",
           "--socket-timeout", "30",
           "--progress-template",
           "download:[[P]]%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
           "--print", "after_move:[[F]]%(filepath)s"]
    cf = ig_cookie_file(s) if (it.get("ig_auth") and "instagram" in it["url"].lower()) else None
    if cf:
        cmd += ["--cookies", cf]
    elif not x_urls and not facebook_login and s.get("cookies_browser"):
        cmd += ["--cookies-from-browser", str(s["cookies_browser"])]
    if x_urls:
        cmd += ["-f", "best"]
    elif ff:
        cmd += ["-f", f"bv*{cap}+ba/b{cap}", "-S", "vcodec:h264,res,acodec:m4a",
                "--merge-output-format", "mp4"]
        if os.path.dirname(ff):
            cmd += ["--ffmpeg-location", ff]
    else:
        # Prefer a ready-made file (fast); if the site only offers separate video+audio
        # (e.g. YouTube) and ffmpeg works, fall back to merging instead of failing.
        fb = find_ffmpeg() if FF["ok"] else None
        if fb:
            cmd += ["-f", f"b{cap}[ext=mp4]/b{cap}/b/bv*{cap}+ba/best",
                    "--merge-output-format", "mp4"]
            if os.path.dirname(fb):
                cmd += ["--ffmpeg-location", fb]
        else:  # no ffmpeg -> single pre-merged file only
            cmd += ["-f", f"b{cap}[ext=mp4]/b{cap}/b"]
    # Multi-item posts (Instagram carousels with photos + videos) come back as a
    # playlist; give every item its own number so none overwrite each other.
    if it.get("slide"):
        cmd += ["--playlist-items", str(it["slide"])]
    # one linked slide -> plain "name.ext" (no index); whole post -> keep _N so items don't overwrite
    single = bool(it.get("slide"))
    idx = "" if single else "%(playlist_index&_{}|)s"
    if x_urls:
        idx = "_%(autonumber)d" if len(x_urls) > 1 else ""
    tmpl = os.path.join(outdir, base.replace("%", "%%") + idx + ".%(ext)s")
    cmd += ["-o", tmpl, *(x_urls or [it["url"]])]
    return cmd


def console_python():
    if IS_WIN and os.path.basename(sys.executable).lower() == "pythonw.exe":
        return os.path.join(os.path.dirname(sys.executable), "python.exe")
    return sys.executable


def find_gallerydl():
    """gallery-dl.exe next to the app, on PATH, or the pip module."""
    for d in (BASE, os.getcwd()):
        for n in ("gallery-dl.exe", "gallery-dl"):
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return [p]
    w = shutil.which("gallery-dl")
    if w:
        return [w]
    try:
        import importlib.util
        if importlib.util.find_spec("gallery_dl"):
            return [console_python(), "-m", "gallery_dl"]
    except Exception:
        pass
    return None


def run_gallery_download(cmd, cancel, payload=None):
    with subprocess.Popen(cmd, stdin=subprocess.PIPE if payload else None, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          creationflags=NOWIN) as proc:
        deadline = time.monotonic() + 300
        try:
            while not cancel.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(cmd[0], 300)
                try:
                    data, payload = payload, None
                    stdout, stderr = proc.communicate(input=data, timeout=min(remaining, 0.25))
                except subprocess.TimeoutExpired:
                    continue
                if not cancel.is_set():
                    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
                break
            raise InterruptedError
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()


def photo_fallback(it, outdir, base, s, run):
    """yt-dlp cannot save Instagram photos ('No video formats found!').
    gallery-dl can. Returns number of files saved (0 = nothing)."""
    gd = find_gallerydl()
    if not gd:
        raise RuntimeError("This slide is a photo. The bundled gallery-dl is missing. Extract the entire ZIP and retry.")
    single = bool(it.get("slide"))
    fmt = base.replace("{", "{{").replace("}", "}}") + ("" if single else "_{num}") + ".{extension}"
    cmd = gd + ["-D", outdir, "-f", fmt, "--no-part"]
    if single:
        cmd += ["--range", str(it["slide"])]
    cf = ig_cookie_file(s) if it.get("ig_auth") else None
    if cf:
        cmd += ["--cookies", cf]
    elif s.get("cookies_browser"):
        cmd += ["--cookies-from-browser", str(s["cookies_browser"])]
    cmd.append(it["url"])
    p = run_gallery_download(cmd, run["cancel"])
    out = p.stdout.decode("utf-8", "replace")
    files = [l.strip() for l in out.splitlines() if l.strip() and not l.startswith("#")]
    if p.returncode != 0 and not files:
        raise RuntimeError(last_error(p.stderr.decode("utf-8", "replace")) or "gallery-dl failed")
    if not files:
        raise RuntimeError("gallery-dl found nothing to download (login may be needed: set cookies_browser in settings.json)")
    it["outfile"] = files[-1]
    it["count"] = len(files)
    return len(files)


FALLBACK_ERR = r"No video formats|no video in this post|Unsupported URL|Unable to extract|Unable to download"


def needs_fallback(url, msg):
    u = url.lower()
    return "instagram" in u and bool(re.search(FALLBACK_ERR, msg or "", re.I))


def media_fallback(it, outdir, base, s, run):
    """yt-dlp can't save Instagram photos. gallery-dl can."""
    return photo_fallback(it, outdir, base, s, run)


# --------------------------------------------------------------------------
# Threads: media comes from the post's server-rendered JSON (needs your Threads login
# from the browser named in settings "cookies_browser", default chrome)
# --------------------------------------------------------------------------
from html.parser import HTMLParser


def is_threads(url):
    return bool(re.match(r"^https?://([\w-]+\.)?threads\.(com|net)/", url or "", re.I))


TH_LOCK = threading.Lock()
TH_STATE = {"seen": {}, "live": {}}   # seen = last value read from the browser, live = newest value we hold


def _th_browser_cookies(s):
    """name -> value for the Threads cookies currently stored by the browser (or pasted by hand)."""
    with LOCK:
        chrome = CHROME_LINK["sessions"].get("threads")
    if chrome:
        return chrome
    manual = (s.get("threads_cookie") or "").strip()
    if manual:
        return {k.strip(): v.strip() for k, _, v in (p.partition("=") for p in manual.split(";")) if k.strip()}
    try:
        import browser_cookie3 as bc
    except ImportError:
        return {}
    fn = {"chrome": bc.chrome, "edge": bc.edge, "firefox": bc.firefox,
          "brave": bc.brave}.get((s.get("cookies_browser") or "chrome").lower(), bc.chrome)
    jar = {}
    for dom in (".threads.com", ".threads.net"):     # threads.com wins (setdefault)
        try:
            for c in fn(domain_name=dom):
                jar.setdefault(c.name, c.value)
        except Exception:
            pass
    return jar


def threads_cookie_host(url):
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme == "https" and parsed.hostname in (
        "threads.com", "www.threads.com", "threads.net", "www.threads.net")


def _th_refresh(s):
    """Re-read the browser every request. A value the browser changed beats ours;
    otherwise keep the rotated one Threads gave us (the browser's copy is only flushed to disk later)."""
    with LOCK:
        chrome = CHROME_LINK["sessions"].get("threads")
    if chrome is not None and TH_STATE.get("chrome") is not chrome:
        TH_STATE.update(seen=dict(chrome), live=dict(chrome), chrome=chrome)
        return
    for k, v in _th_browser_cookies(s).items():
        if TH_STATE["seen"].get(k) != v:
            TH_STATE["seen"][k] = v
            TH_STATE["live"][k] = v


def _th_header():
    return "; ".join("%s=%s" % kv for kv in TH_STATE["live"].items())


def _th_absorb(headers):
    """Threads hands out a newer sessionid (Set-Cookie) on responses - remember it for the next request."""
    for sc in headers.get_all("Set-Cookie") or []:
        k, _, v = sc.split(";", 1)[0].partition("=")
        k, v = k.strip(), v.strip()
        if k and v and v.lower() != "deleted":
            TH_STATE["live"][k] = v


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _th_page(url, s):
    """GET the post page with the freshest cookies, following redirects by hand so every hop's
    Set-Cookie is kept. One page request at a time so rotating cookies can't race."""
    opener = urllib.request.build_opener(_NoRedirect)
    with TH_LOCK:
        _th_refresh(s)
        for _ in range(6):
            if not threads_cookie_host(url):
                raise RuntimeError("Threads redirected outside its site. Check the link and reconnect Threads in Chrome.")
            h = {"User-Agent": UA, "Accept-Language": "en,ru;q=0.9",
                 # Accept: text/html is REQUIRED - otherwise Threads serves a lighter page without the JSON
                 "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                 "Sec-Fetch-Site": "same-origin"}
            if TH_STATE["live"]:
                h["Cookie"] = _th_header()
            try:
                with opener.open(urllib.request.Request(url, headers=h), timeout=40) as r:
                    _th_absorb(r.headers)
                    return r.read().decode("utf-8", "replace"), r.geturl()
            except urllib.error.HTTPError as e:
                _th_absorb(e.headers)
                loc = e.headers.get("Location")
                if e.code in (301, 302, 303, 307, 308) and loc:
                    url = urllib.parse.urljoin(url, loc)
                    continue
                raise
        raise RuntimeError("Too many redirects opening this Threads link")


def _th_file(url, with_cookies=False):
    """Download a media file from the CDN."""
    h = {"User-Agent": UA, "Referer": "https://www.threads.com/"}
    if with_cookies:
        if not threads_cookie_host(url):
            raise RuntimeError("Could not download the Threads media from its CDN.")
        with TH_LOCK:
            h["Cookie"] = _th_header()
        return urllib.request.build_opener(_NoRedirect).open(
            urllib.request.Request(url, headers=h), timeout=90)
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=90)


class _ThJSONScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts, self._attrs, self._buf = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self._attrs, self._buf = dict(attrs), []

    def handle_data(self, data):
        if self._buf is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._buf is not None:
            self.scripts.append((self._attrs or {}, "".join(self._buf)))
            self._attrs = self._buf = None


def _th_blobs(page):
    p = _ThJSONScripts()
    p.feed(page)
    for attrs, body in p.scripts:
        if attrs.get("type") == "application/json" and body.lstrip().startswith("{"):
            try:
                yield json.loads(body)
            except Exception:
                continue


def _th_walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _th_walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _th_walk(v)


_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def _th_code_pk(code):
    """shortcode -> numeric post id (same base64 scheme as Instagram), or ''"""
    try:
        n = 0
        for ch in code:
            n = n * 64 + _B64.index(ch)
        return str(n)
    except ValueError:
        return ""


def _th_has_media(n):
    return bool(n.get("carousel_media") or _th_image(n) or _th_video(n)
                or (n.get("text_post_app_info") or {}).get("linked_inline_media"))


def _th_find_post(page, code):
    """The exact post, matched by shortcode (or its numeric id) ANYWHERE in the page JSON.
    With a shortcode we never fall back to 'the first post' - the page also holds other posts
    by the same user, and that is how a random video got downloaded."""
    pk = _th_code_pk(code) if code else ""
    first, match = None, None
    for blob in _th_blobs(page):
        for node in _th_walk(blob):
            if code:
                hit = node.get("code") == code or (pk and (
                    str(node.get("pk") or "") == pk or str(node.get("id") or "").split("_")[0] == pk))
                if hit and (_th_has_media(node) or match is None):
                    match = node if (match is None or _th_has_media(node)) else match
                    if _th_has_media(node):
                        return node
            elif first is None:
                for item in node.get("thread_items") or []:
                    if item.get("post"):
                        first = item["post"]
                        break
    return match if code else first


def _th_image(n):
    c = [c for c in ((n.get("image_versions2") or {}).get("candidates") or []) if c.get("url")]
    return max(c, key=lambda x: (x.get("width") or 0) * (x.get("height") or 0))["url"] if c else None


def _th_video(n):
    v = [v for v in (n.get("video_versions") or []) if v.get("url")]
    return max(v, key=lambda x: (x.get("width") or 0) * (x.get("height") or 0))["url"] if v else None


def _th_ext(url, default):
    m = re.search(r"\.(jpg|jpeg|png|webp|mp4|mov|webm)(?:\?|$)", url, re.I)
    return m.group(1).lower() if m else default


def _th_media(post):
    """[{kind, url, ext, thumb}] for exactly this post (single or carousel)."""
    src = post
    if not (post.get("carousel_media") or _th_image(post) or _th_video(post)):
        src = (post.get("text_post_app_info") or {}).get("linked_inline_media") or post
    out = []
    for n in (src.get("carousel_media") or [src]):
        v, img = _th_video(n), _th_image(n)
        if v:
            out.append(dict(kind="video", url=v, ext=_th_ext(v, "mp4"), thumb=img or ""))
        elif img:
            out.append(dict(kind="image", url=img, ext=_th_ext(img, "jpg"), thumb=img))
    return out


def threads_info(url, s):
    page, final = _th_page(url, s)
    m = re.search(r"/post/([\w-]+)", final) or re.search(r"/post/([\w-]+)", url)
    a = re.search(r"@([\w.]+)", final) or re.search(r"@([\w.]+)", url)
    code = m.group(1) if m else None
    post = _th_find_post(page, code)
    media = _th_media(post) if post else []
    try:
        codes = []
        for blob in _th_blobs(page):
            codes += [n["code"] for n in _th_walk(blob) if isinstance(n.get("code"), str)]
        cap = ((post or {}).get("caption") or {}).get("text", "") if post else ""
        with open(os.path.join(BASE, "threads_debug.txt"), "w", encoding="utf-8") as f:
            f.write("url: %s\nwanted code: %s (pk %s)\nmatched post: %s\ncaption: %s\nmedia: %s\n"
                    "codes on page: %s\n" % (final, code, _th_code_pk(code or ""),
                    bool(post), cap[:120].replace("\n", " "),
                    [(x["kind"], x["url"][:90]) for x in media], list(dict.fromkeys(codes))[:25]))
    except Exception:
        pass
    if code and not post:
        raise RuntimeError("This post (%s) is not in the page Threads sent - try again, or log in again "
                           "(see threads_debug.txt)" % code)
    if not media:
        if not TH_STATE["live"]:
            raise RuntimeError("Threads needs your login. Sign in to Threads, then use Connect Chrome and select Threads.")
        raise RuntimeError("No media found on this Threads post (private, deleted, or login expired)")
    return dict(author=a.group(1) if a else "threads", media=media,
                upload_date=date_from_timestamp((post or {}).get("taken_at")))


def threads_download(it, outdir, base, s, run):
    """Downloads the picked items. Returns count, or -1 if cancelled."""
    try:
        media = threads_info(it["url"], s)["media"]      # fresh signed URLs
    except Exception:
        media = it.get("media") or []
        if not media:
            raise
    sel = it.get("sel") or []
    todo = [m for i, m in enumerate(media) if i >= len(sel) or sel[i]]
    if not todo:
        raise RuntimeError("Nothing selected - pick at least one item")
    saved = []
    try:
        for n, m in enumerate(todo, 1):
            if run["cancel"].is_set():
                raise InterruptedError
            with LOCK:
                name = base if n == 1 else unique_base(outdir, final_name(it, s))
            dest = os.path.join(outdir, name + "." + m["ext"])
            try:
                r = _th_file(m["url"])
            except Exception:
                r = _th_file(m["url"], True)            # some signed CDN links want the cookies
            with r, open(dest + ".part", "wb") as f:
                shutil.copyfileobj(r, f)
            os.replace(dest + ".part", dest)
            saved.append(dest)
            with LOCK:
                it["progress"] = min(99.0, n / len(todo) * 100)
                it["outfile"], it["count"] = dest, n
    except BaseException as e:
        for p in saved + [p + ".part" for p in saved]:
            try:
                os.remove(p)
            except OSError:
                pass
        for f in os.listdir(outdir):
            if f.startswith(base) and f.endswith(".part"):
                try:
                    os.remove(os.path.join(outdir, f))
                except OSError:
                    pass
        if isinstance(e, InterruptedError):
            return -1
        raise
    return len(saved)


# --------------------------------------------------------------------------
# Instagram login (sessionid) + per-item picker via gallery-dl
# --------------------------------------------------------------------------
IG_AUTH_ERR = (r"isn't available to everyone|can't be seen by certain|login required|log in|logged in|"
               r"rate-limit|Requested content is not available|empty media response|restricted|private")
IG_LOGIN_HINT = ("Sign in to Instagram in Chrome, use Connect Chrome to send your session, "
                 "then retry the link.")


def ig_browser(settings):
    return (settings.get("instagram_browser") or settings.get("cookies_browser") or "chrome").lower()


def ig_cookie_file(s):
    """Netscape cookies.txt with the Instagram login (from the browser named in cookies_browser,
    default chrome, or pasted into settings 'instagram_cookie'). None when there is no sessionid."""
    rows = []
    manual = (s.get("instagram_cookie") or "").strip()
    if manual:
        for pair in manual.split(";"):
            k, _, v = pair.strip().partition("=")
            if k:
                rows.append((".instagram.com", "/", True, 0, k, v))
    else:
        try:
            browser = ig_browser(s)
            if browser == "firefox":
                from gallery_dl.cookies import load_cookies_firefox
                cookies = load_cookies_firefox("firefox", domain=".instagram.com")
            else:
                import browser_cookie3 as bc
                load = {"chrome": bc.chrome, "edge": bc.edge, "brave": bc.brave}.get(browser, bc.chrome)
                cookies = load(domain_name=".instagram.com")
            for c in cookies:
                if c.value and not c.is_expired():
                    rows.append((c.domain or ".instagram.com", c.path or "/", bool(c.secure),
                                 int(c.expires or 0), c.name, c.value))
        except Exception:
            return None
    if not any(r[4] == "sessionid" and r[5] for r in rows):
        return None
    path = os.path.join(BASE, ".ig_cookies.txt")
    tmp = "%s.%d.tmp" % (path, threading.get_ident())
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write("# Netscape HTTP Cookie File\n")
            for dom, pth, sec, exp, k, v in rows:
                f.write("%s\t%s\t%s\t%s\t%d\t%s\t%s\n" % (
                    dom, "TRUE" if dom.startswith(".") else "FALSE", pth,
                    "TRUE" if sec else "FALSE", exp or 4102444800, k, v))
        os.replace(tmp, path)
    except OSError:
        return None
    return path


def ig_story_title(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in (
            "instagram.com", "www.instagram.com"):
        return ""
    path = parsed.path.rstrip("/")
    if re.fullmatch(r"/stories/highlights/[0-9]+|/s/aGlnaGxpZ2h0[^/]+|/[^/]+/highlights", path):
        return "Instagram Highlight"
    if re.fullmatch(r"/stories/(?!highlights(?:/|$)|me(?:/|$))[^/]+(?:/[0-9]+)?", path):
        return "Instagram Story"
    return ""


IG_STORY_OPTIONS = ["-o", "extractor.instagram.videos=merged",
                    "-o", "extractor.instagram.audio=false",
                    "-o", "extractor.instagram.previews=false"]


def story_gallery_command(options, url, cookie_file, session):
    if session:
        script = (
            "import json, sys; from gallery_dl import config, main; "
            "config.set(('extractor', 'instagram'), 'cookies', json.load(sys.stdin)); "
            "sys.exit(main())"
        )
        return [console_python(), "-E", "-s", "-B", "-c", script, "--config-ignore",
                *options, url], json.dumps(session).encode("ascii")
    gd = find_gallerydl()
    if not gd:
        raise RuntimeError("The bundled gallery-dl is missing. Extract the entire ZIP and retry.")
    return gd + list(options) + (["--cookies", cookie_file] if cookie_file else []) + [url], None


def ig_gallery_items(url, cf, options=(), session=None):
    cmd, payload = story_gallery_command([*options, "-j"], url, cf, session)
    p = subprocess.run(cmd, input=payload, capture_output=True, timeout=90, creationflags=NOWIN)
    if p.returncode != 0:
        raise RuntimeError(last_error(p.stderr.decode("utf-8", "replace")))
    data = json.loads(p.stdout.decode("utf-8", "replace"))
    items = []
    for m in data if isinstance(data, list) else []:
        if isinstance(m, list) and len(m) >= 3 and m[0] == 3 and isinstance(m[2], dict):
            ext = str(m[2].get("extension") or os.path.splitext(str(m[1]).split("?")[0])[1].lstrip(".")).lower()
            kind = "video" if ext in ("mp4", "mov", "webm", "m4v") else "image"
            items.append((str(m[2].get("media_id") or ""), kind, m[2].get("date")))
    return items


def date_from_timestamp(value):
    try:
        return dt.datetime.fromtimestamp(float(value), dt.timezone.utc).date()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def ig_enumerate(url, cf, session=None):
    try:
        items = ig_gallery_items(url, cf, session=session)
    except Exception:
        return None, None
    posted = next((date for _, _, timestamp in items
                   if (date := instagram_posted_date(timestamp)) is not None), None)
    return [kind for _, kind, _ in items] or None, posted


def instagram_posted_date(value):
    if not isinstance(value, str):
        return None
    try:
        posted = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=dt.timezone.utc)
    return posted.astimezone().date()


def ig_story_media(url, settings, highlight_start=None, highlight_end=None):
    with LOCK:
        session = CHROME_LINK["sessions"].get("instagram")
    cookies = None if session else ig_cookie_file(settings)
    if not cookies and not session:
        if ig_browser(settings) == "firefox":
            raise RuntimeError("No active Instagram session found in Firefox. Open the link in a regular Firefox tab "
                               "and confirm it plays, then retry here.")
        raise RuntimeError("Use Connect Chrome to send your Instagram session, then retry.")
    items = []
    start = highlight_start or dt.date.min
    end = highlight_end or dt.date.today()
    filtered = highlight_start is not None or highlight_end is not None
    highlight = ig_story_title(url) == "Instagram Highlight"
    for mid, kind, timestamp in ig_gallery_items(url, cookies, IG_STORY_OPTIONS, session):
        if not re.fullmatch(r"[0-9]+", mid) or (highlight and kind != "video"):
            continue
        posted = instagram_posted_date(timestamp)
        if filtered and (posted is None or not start <= posted <= end):
            continue
        items.append((mid, kind, posted))
    if not items and filtered:
        raise RuntimeError("No Highlight videos with a known posting date in the selected range.")
    if not items:
        if highlight:
            raise RuntimeError("No videos found in this Highlight.")
        raise RuntimeError("No story media found. The story may have expired or may be unavailable to this account.")
    return items


def ig_download(it, outdir, base, s, run):
    """Download the picked items of an Instagram post, one gallery-dl call per item. -1 = cancelled."""
    story_ids = it.get("ig_story_ids")
    with LOCK:
        session = CHROME_LINK["sessions"].get("instagram")
    cf = None if session else ig_cookie_file(s)
    if story_ids and not cf and not session:
        raise RuntimeError("Instagram login is unavailable. Use Connect Chrome to send your Instagram session, then retry.")
    sel = it.get("sel") or []
    todo = [i for i in range(len(it.get("media") or [])) if i >= len(sel) or sel[i]]
    if not todo:
        raise RuntimeError("Nothing selected - pick at least one item")
    names = []
    try:
        for n, i in enumerate(todo, 1):
            if run["cancel"].is_set():
                raise InterruptedError
            with LOCK:
                name = base if n == 1 else unique_base(outdir, final_name(it, s, i))
            names.append(name)
            fmt = name.replace("{", "{{").replace("}", "}}") + ".{extension}"
            options = ["-D", outdir, "-f", fmt, "--no-part"]
            if story_ids:
                options += IG_STORY_OPTIONS + ["--filter", f"str(media_id) == '{story_ids[i]}'"]
            else:
                options += ["--range", str(i + 1)]
            cmd, payload = story_gallery_command(options, it["url"], cf, session)
            p = run_gallery_download(cmd, run["cancel"], payload)
            files = [l.strip() for l in p.stdout.decode("utf-8", "replace").splitlines()
                     if l.strip() and not l.startswith("#")]
            if p.returncode != 0 or not files:
                if story_ids and p.returncode == 0:
                    raise RuntimeError(f"Item {i + 1} is no longer available. Retry to refresh the story.")
                raise RuntimeError(last_error(p.stderr.decode("utf-8", "replace")))
            with LOCK:
                it["progress"] = min(99.0, n / len(todo) * 100)
                it["outfile"], it["count"] = files[-1], n
    except BaseException as e:
        for name in names:
            clean_partials(outdir, name)
        if isinstance(e, InterruptedError):
            return -1
        raise
    return len(names)


def facebook_session(url):
    host = urllib.parse.urlsplit(url).hostname or ""
    if host == "facebook.com" or host.endswith(".facebook.com") or host in ("fb.watch", "fb.com"):
        with LOCK:
            return CHROME_LINK["sessions"].get("facebook")
    return None


def is_facebook_story(url):
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    return (parsed.scheme == "https"
            and (host == "facebook.com" or host.endswith(".facebook.com"))
            and parsed.path.startswith("/stories/")
            and bool(parsed.path[len("/stories/"):].strip("/")))


def facebook_media_host(url):
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    return parsed.scheme == "https" and host.endswith((".fbcdn.net", ".fbsbx.com"))


class FacebookStoryRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed):
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not self.allowed(newurl):
            raise RuntimeError("Facebook redirected outside the supported Story or media URL.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def facebook_story_video(url, settings):
    session = facebook_session(url)
    if not session:
        raise RuntimeError("Connect Facebook in the Chrome companion, then retry this Story.")
    jar = http.cookiejar.CookieJar()
    for name, value in session.items():
        jar.set_cookie(http.cookiejar.Cookie(
            0, name, value, None, False, ".facebook.com", True, True,
            "/", True, True, None, True, None, None, {}, False))
    opener = urllib.request.build_opener(
        FacebookStoryRedirect(is_facebook_story), urllib.request.HTTPCookieProcessor(jar))
    request = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
    })
    try:
        with opener.open(request, timeout=30) as response:
            html = response.read(16 * 1024 * 1024).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Facebook Story page returned HTTP {exc.code}. Check the link and reconnect Facebook.") from None

    candidates = dict.fromkeys(
        media for token in re.findall(r'"progressive_url"\s*:\s*("(?:[^"\\]|\\.)*")', html)
        if facebook_media_host(media := json.loads(token))
        and urllib.parse.urlsplit(media).path.lower().endswith(".mp4")
    )
    if not candidates:
        raise RuntimeError("Facebook did not expose a direct Story MP4. This may be a photo, an expired Story, or a different video format.")
    urls = list(candidates)
    return urls[0] if len(urls) == 1 or settings.get("quality") in ("360", "480") else urls[1]


def download_facebook_story(it, outdir, base, run, settings):
    media = facebook_story_video(it["url"], settings)
    target = os.path.join(outdir, base + ".mp4")
    partial = target + ".part"
    opener = urllib.request.build_opener(FacebookStoryRedirect(facebook_media_host))
    request = urllib.request.Request(media, headers={"User-Agent": UA, "Referer": "https://www.facebook.com/"})
    try:
        with opener.open(request, timeout=30) as response, open(partial, "wb") as output:
            header = response.read(16)
            if header[4:8] != b"ftyp":
                raise RuntimeError("Facebook returned a response that is not an MP4 video.")
            output.write(header)
            while not run["cancel"].is_set():
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                output.write(chunk)
        if run["cancel"].is_set():
            return None
        os.replace(partial, target)
        return target
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Facebook media returned HTTP {exc.code}. Retry to refresh the video link.") from None
    finally:
        if os.path.exists(partial):
            os.remove(partial)


def authenticated_ytdlp(cmd, session):
    if not session:
        return cmd, None
    return [console_python(), "-E", "-s", "-B", os.path.join(BASE, "facebook_ytdlp.py"),
            "--ignore-config", *cmd[1:]], json.dumps(session).encode("ascii")


def _yt_meta(yt, url, cf=None):
    cmd = [yt, "--dump-single-json", "--no-playlist", "--no-warnings",
           "--encoding", "utf-8", "--socket-timeout", "20"]
    if cf:
        cmd += ["--cookies", cf]
    cmd, payload = authenticated_ytdlp(cmd + [url], facebook_session(url))
    p = subprocess.run(cmd, input=payload, capture_output=True, timeout=120, creationflags=NOWIN)
    out = p.stdout.decode("utf-8", "replace")
    if p.returncode != 0 or not out.strip():
        raise RuntimeError(last_error(p.stderr.decode("utf-8", "replace")))
    d = json.loads(out)
    if d.get("entries"):
        ent = [e for e in d["entries"] if e]
        if ent:
            d = ent[0]
    return d


def fetch_meta_generic(iid, it, yt):
    is_ig = "instagram" in it["url"].lower()
    d, err, used_login = None, "", False
    try:
        d = _yt_meta(yt, it["url"])
    except Exception as e:
        err = str(e)
    cf = None
    if is_ig and d is None and re.search(IG_AUTH_ERR, err, re.I):
        cf = ig_cookie_file(SETTINGS)
        if cf:
            try:
                d, err, used_login = _yt_meta(yt, it["url"], cf), "", True
            except Exception as e:
                err = str(e)
    media, gallery_date, gallery_session = None, None, None
    if is_ig and re.search(r"/(p|reel|reels|tv)/", it["url"]):
        with LOCK:
            gallery_session = CHROME_LINK["sessions"].get("instagram")
        cf2 = None if gallery_session else (cf or ig_cookie_file(SETTINGS))
        media, gallery_date = ig_enumerate(it["url"], cf2, gallery_session)
    with LOCK:
        if not get_item(iid) or it["status"] != "fetching":
            return
        if used_login:
            it["ig_auth"] = True
        slide = it.get("slide") or 0
        if media and slide > len(media):
            it.update(status="error", error="The linked Instagram slide is unavailable.")
            return
        if media and (slide or len(media) > 1 or (gallery_session and d is None)):
            it.update(media=media, sel=[not slide or i == slide - 1 for i in range(len(media))])
        if d is not None:
            thumb = d.get("thumbnail") or ""
            if not thumb and d.get("thumbnails"):
                thumb = (d["thumbnails"][-1] or {}).get("url", "")
            it.update(title=d.get("title") or "", thumb=thumb, duration=int(d.get("duration") or 0),
                      uploader=d.get("uploader") or d.get("channel") or "",
                      upload_date=d.get("upload_date") or date_from_timestamp(d.get("timestamp")) or gallery_date,
                      status="ready", error="")
        elif media or (is_ig and needs_fallback(it["url"], err)):
            # yt-dlp can't read it (photo / needs login) but gallery-dl can: the download step handles it
            it.update(status="ready", error="", upload_date=gallery_date, title=it.get("title") or "Instagram post",
                      uploader=it.get("uploader") or "Instagram")
        elif is_ig and re.search(IG_AUTH_ERR, err, re.I):
            it.update(status="error", error=(IG_LOGIN_HINT if cf is None else err)[:220])
        else:
            it.update(status="error", error=err[:220] or "Could not read this link")


def clean_partials(outdir, base):
    try:
        for f in os.listdir(outdir):
            if _owns(f, base):
                try:
                    os.remove(os.path.join(outdir, f))
                except OSError:
                    pass
    except OSError:
        pass


def download_one(iid, outdir, run, s):
    it = get_item(iid)
    if not it:
        return
    try:
        t0 = time.time()
        while it["status"] == "fetching" and time.time() - t0 < 120 and not run["cancel"].is_set():
            time.sleep(0.3)
        if run["cancel"].is_set():
            with LOCK:
                it.update(status="ready", progress=0.0)
            return
        if is_threads(it["url"]):
            with LOCK:
                base = unique_base(outdir, final_name(it, s))
                it.update(status="downloading", progress=0.0, speed="", eta="", error="", outfile="", count=0)
            if threads_download(it, outdir, base, s, run) < 0:
                with LOCK:
                    it.update(status="ready", progress=0.0)
            else:
                with LOCK:
                    it.update(status="done", progress=100.0, speed="", eta="")
                    run["saved"] += 1
            return
        if it.get("media") and "instagram" in it["url"].lower():
            with LOCK:
                base = unique_base(outdir, final_name(it, s))
                it.update(status="downloading", progress=0.0, speed="", eta="", error="", outfile="", count=0)
            if ig_download(it, outdir, base, s, run) < 0:
                with LOCK:
                    it.update(status="ready", progress=0.0, outfile="", count=0)
            else:
                with LOCK:
                    it.update(status="done", progress=100.0, speed="", eta="")
                    run["saved"] += 1
            return
        yt = find_ytdlp()
        if not yt:
            raise RuntimeError("yt-dlp not found next to the app")
        x_urls = None
        with LOCK:
            if x_status_id(it["url"]):
                if not it.get("media"):
                    raise RuntimeError("Retry this X link to load the media picker before downloading.")
                selected = [m for m, on in zip(it["media"], it["sel"]) if on]
                if not selected:
                    raise RuntimeError("Select a video or GIF from this X post.")
                height = {"1080": 1080, "720": 720, "480": 480, "360": 360}.get(s.get("quality"))
                x_urls = []
                for media in selected:
                    variants = media["variants"]
                    eligible = [v for v in variants if not height or 0 < v[1] <= height]
                    x_urls.append((eligible[0] if eligible else variants[-1])[2])
            base = unique_base(outdir, final_name(it, s))
            it.update(status="downloading", progress=0.0, speed="", eta="", error="", outfile="", count=0)
        if is_facebook_story(it["url"]):
            output = download_facebook_story(it, outdir, base, run, s)
            with LOCK:
                if output:
                    it.update(status="done", progress=100.0, outfile=output, count=1)
                    run["saved"] += 1
                else:
                    it.update(status="ready", progress=0.0)
            return
        session = facebook_session(it["url"])
        cmd, payload = authenticated_ytdlp(build_cmd(yt, it, outdir, base, s, bool(session), x_urls), session)
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if payload else None, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, creationflags=NOWIN)
        PROCS[iid] = proc
        if run["cancel"].is_set():
            proc.terminate()
        if payload:
            try:
                with proc.stdin:
                    proc.stdin.write(payload)
            except BrokenPipeError:
                pass
        tail = []
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("[[P]]"):
                try:
                    pct, spd, eta = (line[5:].split("|") + ["", ""])[:3]
                    pv = float(pct.strip().rstrip("%"))
                    with LOCK:
                        it["progress"] = max(it["progress"], min(pv, 99.9))
                        it["speed"] = "" if "Unknown" in spd else spd.strip()
                        it["eta"] = "" if "Unknown" in eta else eta.strip()
                except ValueError:
                    pass
            elif line.startswith("[[F]]"):
                it["outfile"] = line[5:].strip()
                it["count"] = it.get("count", 0) + 1
            elif line:
                tail.append(line)
                tail = tail[-12:]
        proc.wait()
        PROCS.pop(iid, None)
        if run["cancel"].is_set():
            clean_partials(outdir, base)
            with LOCK:
                it.update(status="ready", progress=0.0, speed="", eta="")
        elif proc.returncode == 0 and (not x_urls or it["count"] == len(x_urls)):
            with LOCK:
                it.update(status="done", progress=100.0, speed="", eta="")
                run["saved"] += 1
        else:
            joined = "\n".join(tail)
            clean_partials(outdir, base)
            if needs_fallback(it["url"], joined):
                try:
                    media_fallback(it, outdir, base, s, run)
                except InterruptedError:
                    clean_partials(outdir, base)
                    with LOCK:
                        it.update(status="ready", progress=0.0, speed="", eta="", outfile="", count=0)
                    return
                with LOCK:
                    it.update(status="done", progress=100.0, speed="", eta="")
                    run["saved"] += 1
            else:
                raise RuntimeError(last_error(joined) if joined else "Could not save the selected media.")
    except Exception as e:
        with LOCK:
            it.update(status="error", error=str(e)[:220], speed="", eta="")
            run["failed"] += 1
    finally:
        with LOCK:
            run["finished"] += 1


def run_job(ids):
    run = RUN
    s = dict(SETTINGS)
    base_dir = s["folder"] or os.path.join(os.path.expanduser("~"), "Downloads")
    fname = sanitize(s["folder_name"]) or default_folder_name()
    use_zip = bool(s["zip"])
    try:
        outdir = os.path.join(base_dir, (".vbd_" + fname) if use_zip else fname)
        os.makedirs(outdir, exist_ok=True)
        pool = ThreadPoolExecutor(max_workers=max(1, min(4, int(s["parallel"]))))
        for iid in ids:
            pool.submit(download_one, iid, outdir, run, s)
        pool.shutdown(wait=True)

        final_path = outdir
        if use_zip:
            run["phase"] = "zipping"
            files = [f for f in os.listdir(outdir)
                     if os.path.isfile(os.path.join(outdir, f))
                     and not f.lower().endswith((".part", ".ytdl", ".temp"))]
            if files:
                zpath = os.path.join(base_dir, fname + ".zip")
                n = 1
                while os.path.exists(zpath):
                    n += 1
                    zpath = os.path.join(base_dir, f"{fname} ({n}).zip")
                with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as z:
                    for f in files:
                        z.write(os.path.join(outdir, f), f)
                final_path = zpath
            shutil.rmtree(outdir, ignore_errors=True)
            if not files:
                final_path = base_dir
        run["result"] = {"saved": run["saved"], "failed": run["failed"],
                         "path": final_path, "zip": use_zip and final_path.endswith(".zip"),
                         "cancelled": run["cancel"].is_set()}
    except Exception as e:
        run["result"] = {"saved": run["saved"], "failed": run["failed"], "path": base_dir,
                         "zip": False, "cancelled": False, "error": str(e)}
    finally:
        run["active"] = False
        run["phase"] = "finished"


def start_download():
    with LOCK:
        if RUN["active"]:
            return False
        ids = [it["id"] for it in ITEMS if it["status"] != "done"]
        if not ids:
            return False
        for it in ITEMS:
            if it["id"] in ids and it["status"] == "error":
                it["error"] = ""
        RUN.update(active=True, phase="downloading", total=len(ids), finished=0, saved=0,
                   failed=0, result=None, used=set(), run_id=RUN["run_id"] + 1)
        RUN["cancel"] = threading.Event()
    threading.Thread(target=run_job, args=(ids,), daemon=True).start()
    return True


def cancel_download():
    RUN["cancel"].set()
    for p in list(PROCS.values()):
        try:
            p.terminate()
        except Exception:
            pass


# --------------------------------------------------------------------------
# Excel / CSV import  (column A = urls, column B = file name)
# --------------------------------------------------------------------------
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
BUILTIN_DATE_IDS = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))


def _cell_text(v):
    if v is None:
        return ""
    v = str(v).strip()
    if re.fullmatch(r"-?\d+\.0+", v):
        v = v.split(".")[0]
    return v


def read_xlsx(path):
    with zipfile.ZipFile(path) as z:
        return read_xlsx_rows(z)


def read_xlsx_rows(z):
    names = z.namelist()
    shared = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(M + "si"):
            shared.append("".join(t.text or "" for t in si.iter(M + "t")))
    date_xf = set()
    if "xl/styles.xml" in names:
        root = ET.fromstring(z.read("xl/styles.xml"))
        fmts = {int(n.get("numFmtId")): n.get("formatCode", "") for n in root.iter(M + "numFmt")}
        xfs = root.find(M + "cellXfs")
        if xfs is not None:
            for i, xf in enumerate(xfs.findall(M + "xf")):
                fid = int(xf.get("numFmtId", "0"))
                code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", fmts.get(fid, "")).lower()
                if fid in BUILTIN_DATE_IDS or (fid in fmts and re.search(r"[dy]", code)):
                    date_xf.add(i)
    epoch = dt.date(1899, 12, 30)
    sheet_path = "xl/worksheets/sheet1.xml"
    try:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        properties = wb.find(M + "workbookPr")
        if properties is not None and properties.get("date1904") in ("1", "true"):
            epoch = dt.date(1904, 1, 1)
        first = next(wb.iter(M + "sheet"))
        rid = first.get(R + "id")
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        for rel in rels:
            if rel.get("Id") == rid:
                t = rel.get("Target")
                sheet_path = t.lstrip("/") if t.startswith("/") else "xl/" + t
    except Exception:
        pass
    if sheet_path not in names:
        sheet_path = next(n for n in names if n.startswith("xl/worksheets/sheet"))
    rows = []
    for row in ET.fromstring(z.read(sheet_path)).iter(M + "row"):
        cols = {}
        for c in row.findall(M + "c"):
            col = re.match(r"[A-Z]+", c.get("r", "")).group()
            t, s = c.get("t"), int(c.get("s", "0") or 0)
            v = c.find(M + "v")
            val = ""
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(M + "t"))
            elif v is not None and v.text is not None:
                val = v.text
                if t not in ("str", "b", "e") and s in date_xf:
                    try:
                        d = epoch + dt.timedelta(days=float(val))
                        val = d.strftime("%m-%d-%Y")
                    except (ValueError, OverflowError):
                        pass
            cols[col] = val
        values = tuple(_cell_text(cols.get(col)) for col in "ABCD")
        rows.append((int(row.get("r") or len(rows) + 1), values))
    return rows


def read_table(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        rows = read_xlsx(path)
    elif ext in (".csv", ".txt"):
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            rows = [(i, tuple(cell.strip() for cell in (row + [""] * 4)[:4]))
                    for i, row in enumerate(csv.reader(f), 1)]
    else:
        raise ValueError("Please choose an .xlsx or .csv file (old .xls is not supported - re-save as .xlsx)")
    if not rows:
        return [], False
    header = rows[0][1]
    has_header = header[0].lower() in ("url", "urls", "link", "links")
    has_dates = (
        header[1].lower() == "from" or header[2].lower() in ("through", "to", "through/to")
        if has_header else any(row[2] or row[3] for _, row in rows)
    )
    data = rows[1:] if has_header else rows
    return [(i, row) for i, row in data if row[0]], has_dates


# --------------------------------------------------------------------------
# native dialogs (run in a child process so tkinter never fights the server)
# --------------------------------------------------------------------------
def native_dialog(kind, initial=""):
    if kind == "folder":
        body = "p = fd.askdirectory(initialdir=sys.argv[1] or None, title='Choose download folder')"
    else:
        body = ("p = fd.askopenfilename(title='Choose Excel / CSV file', filetypes="
                "[('Excel or CSV', '*.xlsx *.xlsm *.csv'), ('All files', '*.*')])")
    code = ("import sys, tkinter as tk\nfrom tkinter import filedialog as fd\n"
            "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True); r.update()\n"
            + body + "\nsys.stdout.buffer.write((p or '').encode('utf-8'))\n")
    exe = console_python()
    try:
        p = subprocess.run([exe, "-c", code, initial], capture_output=True, timeout=600,
                           creationflags=NOWIN)
        path = p.stdout.decode("utf-8", "replace").strip()
        return os.path.normpath(path) if path else ""
    except Exception:
        return ""


def open_path(path):
    try:
        if IS_WIN:
            if os.path.isfile(path):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                os.startfile(path)  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path] if os.path.isfile(path) else ["open", path])
        else:
            subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)])
    except Exception:
        pass


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
ITEM_KEYS = ("id", "url", "name", "source", "title", "duration", "uploader",
             "status", "progress", "speed", "eta", "error")


def api_state(_=None):
    STATE_META["last_ping"] = time.time()
    with LOCK:
        items = []
        for it in ITEMS:
            d = {k: it[k] for k in ITEM_KEYS}
            d["final"] = final_name(it)
            d["has_thumb"] = bool(it["thumb"])
            d["linked_slide"] = bool(it.get("slide"))
            d["media"] = [m if isinstance(m, str) else m["kind"] for m in it.get("media", [])]
            if x_status_id(it["url"]):
                d["media_labels"] = [m["label"] for m in it.get("media", [])]
            d["sel"] = list(it.get("sel", []))
            items.append(d)
        run = {k: RUN[k] for k in ("active", "phase", "total", "finished", "saved", "failed",
                                   "run_id", "result")}
        run["cancelling"] = RUN["cancel"].is_set()
        return {"items": items, "run": run, "settings": dict(SETTINGS),
                "chrome_connected": {key: key in CHROME_LINK["sessions"] for key in CHROME_COOKIE_NAMES},
                "ytdlp": bool(find_ytdlp()), "ytdlp_version": STATE_META["ytdlp_version"],
                "ffmpeg": bool(find_ffmpeg()), "ffmpeg_ok": FF["ok"], "today": today_str()}


def parse_highlight_range(body):
    dates = []
    for key in ("highlight_start", "highlight_end"):
        value = body.get(key, "")
        if value == "":
            dates.append(None)
        elif isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            dates.append(dt.date.fromisoformat(value))
        else:
            raise ValueError
    start, end = dates
    today = dt.date.today()
    last = end or today
    if last > today or (start and start > last):
        raise ValueError
    return start, end if start or end != today else None


def api_add(b):
    try:
        start, end = parse_highlight_range(b)
    except ValueError:
        return {"ok": False, "msg": "Use valid Highlight dates. The start must be on or before To, and To cannot be in the future."}
    urls = re.findall(r"\S+", b.get("url", ""))
    if not urls:
        return {"ok": False, "msg": "Paste a link first"}
    name = b.get("name", "") if len(urls) == 1 else ""
    added = sum(1 for u in urls if add_item(u, name, start, end))
    dup = len(urls) - added
    msg = f"Added {added} link{'s' if added != 1 else ''}" if added else "Already in the queue"
    if added and dup:
        msg += f" ({dup} duplicate skipped)"
    return {"ok": bool(added), "msg": msg}


def api_rename(b):
    it = get_item(b.get("id"))
    if it and it["status"] not in ("downloading", "done"):
        with LOCK:
            it["name"] = (b.get("name") or "").strip()
    return {"ok": True}


def api_pick(b):
    """Toggle one media item in the queue picker."""
    it = get_item(b.get("id"))
    try:
        i = int(b.get("index"))
    except (TypeError, ValueError):
        return {"ok": False}
    with LOCK:
        if it and not it.get("slide") and it["status"] not in ("fetching", "downloading", "done") and 0 <= i < len(it.get("sel", [])):
            it["sel"][i] = not it["sel"][i]
    return {"ok": True}


def api_remove(b):
    it = get_item(b.get("id"))
    if it and it["status"] != "downloading":
        with LOCK:
            ITEMS.remove(it)
    return {"ok": True}


def api_clear(_):
    if RUN["active"]:
        return {"ok": False}
    with LOCK:
        ITEMS.clear()
    THUMBS.clear()
    return {"ok": True}


def api_retry(b):
    it = get_item(b.get("id"))
    if it and it["status"] == "error":
        if it["title"] and not (ig_story_title(it["url"]) or is_facebook_story(it["url"])):
            with LOCK:
                it.update(status="ready", error="", progress=0.0)
        else:
            with LOCK:
                it.update(status="fetching", error="", progress=0.0)
            META_POOL.submit(fetch_meta, it["id"])
    return {"ok": True}


def api_settings(b):
    with LOCK:
        updated = {key: b.get(key, value) for key, value in SETTINGS.items()}
        if not isinstance(updated["date_format"], str) or updated["date_format"] not in DATE_FORMATS:
            return {"ok": False, "error": "Unknown posted date format."}
        if updated["instagram_browser"] not in ("", "firefox", "chrome", "edge", "brave"):
            return {"ok": False, "error": "Unknown Instagram browser."}
        if updated != SETTINGS:
            try:
                save_settings(updated)
            except OSError as exc:
                return {"ok": False, "error": f"Could not save settings: {exc.strerror or exc}"}
            SETTINGS.update(updated)
    return {"ok": True}


def api_browse_folder(_):
    p = native_dialog("folder", SETTINGS["folder"] if os.path.isdir(SETTINGS["folder"]) else "")
    if not p:
        return {"ok": False, "path": ""}
    return dict(api_settings({"folder": p}), path=p)


def api_browse_excel(_):
    return {"ok": True, "path": native_dialog("file")}


EXCEL_TEMPLATE = "Queue Template.xlsx"


def api_excel_template(_):
    path = os.path.join(BASE, EXCEL_TEMPLATE)
    if not os.path.isfile(path):
        return {"ok": False, "msg": "Queue Template.xlsx is missing from the app folder."}
    try:
        if IS_WIN:
            os.startfile(path)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])
    except OSError:
        return {"ok": False, "msg": "Open Queue Template.xlsx from the app folder in a spreadsheet editor."}
    return {"ok": True, "path": path}


def spreadsheet_date(value):
    if not value:
        return ""
    for pattern in ("%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    raise ValueError


def api_import(b):
    path = (b.get("path") or "").strip().strip('"')
    if not path or not os.path.isfile(path):
        return {"ok": False, "msg": "Choose an Excel file first"}
    try:
        data, has_dates = read_table(path)
    except Exception as e:
        return {"ok": False, "msg": f"Could not read file: {e}"}
    if not has_dates:
        try:
            default_range = parse_highlight_range(b)
        except ValueError:
            return {"ok": False, "msg": "Use valid Highlight dates in the queue before importing."}
    rows = []
    for row_number, (url, second, through, name) in data:
        if not has_dates:
            rows.append((url, second, *default_range))
            continue
        try:
            dates = parse_highlight_range({
                "highlight_start": spreadsheet_date(second),
                "highlight_end": spreadsheet_date(through),
            }) if ig_story_title(norm_url(url)) == "Instagram Highlight" else (None, None)
        except ValueError:
            return {"ok": False, "msg": f"Row {row_number}: use valid Highlight dates. From must be on or before Through/To, and Through/To cannot be in the future."}
        rows.append((url, name, *dates))
    added = sum(1 for row in rows if add_item(*row))
    if not rows:
        return {"ok": False, "msg": "No links found in column A"}
    msg = f"Imported {added} of {len(rows)} link{'s' if len(rows) != 1 else ''}"
    if added < len(rows):
        msg += f" ({len(rows) - added} duplicates skipped)"
    return {"ok": True, "msg": msg}


def api_download(_):
    return {"ok": start_download()}


def api_cancel(_):
    cancel_download()
    return {"ok": True}


def api_open(b):
    p = b.get("path") or SETTINGS["folder"]
    if os.path.exists(p):
        open_path(p)
    return {"ok": True}


def api_update(_):
    yt = find_ytdlp()
    if not yt:
        return {"ok": False, "msg": "yt-dlp not found"}
    try:
        p = subprocess.run([yt, "-U"], capture_output=True, timeout=180, creationflags=NOWIN)
        out = (p.stdout + p.stderr).decode("utf-8", "replace").strip().splitlines()
        load_version()
        return {"ok": p.returncode == 0, "msg": (out[-1] if out else "Done")[:160]}
    except Exception as e:
        return {"ok": False, "msg": str(e)[:160]}


def api_quit(_):
    cancel_download()
    threading.Timer(0.4, lambda: os._exit(0)).start()
    return {"ok": True}


def api_chrome_pair(_):
    with LOCK:
        CHROME_LINK.update(code=secrets.token_hex(24), expires=time.monotonic() + 300)
        return {"code": f"{STATE_META['port']}:{CHROME_LINK['code']}"}


ROUTES = {"/api/chrome-pair": api_chrome_pair, "/api/add": api_add, "/api/rename": api_rename, "/api/pick": api_pick, "/api/remove": api_remove,
          "/api/clear": api_clear, "/api/retry": api_retry, "/api/settings": api_settings,
          "/api/browse-folder": api_browse_folder, "/api/browse-excel": api_browse_excel,
          "/api/excel-template": api_excel_template, "/api/import": api_import, "/api/download": api_download, "/api/cancel": api_cancel,
          "/api/open": api_open, "/api/update": api_update, "/api/quit": api_quit}


def check_ffmpeg():
    ff = find_ffmpeg()
    try:
        FF["ok"] = bool(ff) and subprocess.run([ff, "-version"], capture_output=True, timeout=30,
                                               creationflags=NOWIN).returncode == 0
    except Exception:
        FF["ok"] = False


def load_version():
    check_ffmpeg()
    yt = find_ytdlp()
    if not yt:
        return
    try:
        p = subprocess.run([yt, "--version"], capture_output=True, timeout=60, creationflags=NOWIN)
        STATE_META["ytdlp_version"] = p.stdout.decode().strip()
    except Exception:
        pass


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _ok_host(self):
        return self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost")

    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        origin = self.headers.get("Origin", "")
        if self.path == "/api/chrome-session" and re.fullmatch(r"chrome-extension://[a-p]{32}", origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._ok_host():
            return self._send(403, {"error": "bad host"})
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            with open(os.path.join(BASE, "index.html"), "r", encoding="utf-8") as f:
                html = f.read().replace("__TOKEN__", TOKEN)
            return self._send(200, html, "text/html; charset=utf-8")
        if u.path == "/api/state" and self.headers.get("X-Token") == TOKEN:
            return self._send(200, api_state())
        if u.path == "/thumb" and q.get("t", [""])[0] == TOKEN:
            return self._thumb(q.get("id", [""])[0])
        self._send(404, {"error": "not found"})

    def _thumb(self, iid):
        it = get_item(iid)
        if not it or not it["thumb"]:
            return self._send(404, {})
        if iid not in THUMBS:
            try:
                req = urllib.request.Request(it["thumb"], headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=20) as r:
                    THUMBS[iid] = (r.read(), r.headers.get("Content-Type", "image/jpeg"))
            except Exception:
                return self._send(404, {})
        data, ctype = THUMBS[iid]
        self._send(200, data, ctype, {"Cache-Control": "max-age=3600"})

    def do_OPTIONS(self):
        if (self.path != "/api/chrome-session" or not self._ok_host()
                or not re.fullmatch(r"chrome-extension://[a-p]{32}", self.headers.get("Origin", ""))):
            return self._send(403, {"ok": False})
        return self._send(204, b"", extra={
            "Access-Control-Allow-Methods": "POST",
            "Access-Control-Allow-Headers": "Content-Type, X-Pair-Code",
            "Access-Control-Allow-Private-Network": "true",
        })

    def _receive_chrome_session(self):
        if not self._ok_host():
            return self._send(403, {"ok": False})
        code = self.headers.get("X-Pair-Code", "")
        length = self.headers.get("Content-Length", "")
        if not length.isascii() or not length.isdecimal() or len(length) > 4 or not 0 < int(length) <= 4096:
            return self._send(400, {"ok": False})
        with LOCK:
            valid = bool(re.fullmatch(r"[a-f0-9]{48}", code) and secrets.compare_digest(code, CHROME_LINK["code"])
                         and time.monotonic() < CHROME_LINK["expires"])
        if not valid:
            return self._send(403, {"ok": False, "error": "Generate a new pairing code in the downloader."})
        try:
            self.connection.settimeout(5)
            body = json.loads(self.rfile.read(int(length)))
            platform = body.get("platform", "instagram")
            session = body.get("cookies", body if "platform" not in body else {})
            if (platform not in CHROME_COOKIE_NAMES or not isinstance(session, dict)
                    or not CHROME_REQUIRED[platform] <= session.keys()
                    or not session.keys() <= CHROME_COOKIE_NAMES[platform]
                    or any(not isinstance(value, str) or not re.fullmatch(
                        r"[!#-+\--:<-\[\]-~]{1,2048}", value) for value in session.values())):
                raise ValueError
        except (OSError, ValueError, KeyError, AttributeError, TypeError):
            return self._send(400, {"ok": False, "error": "Invalid session for the selected platform."})
        with LOCK:
            if (not secrets.compare_digest(code, CHROME_LINK["code"])
                    or time.monotonic() >= CHROME_LINK["expires"]):
                return self._send(403, {"ok": False, "error": "Generate a new pairing code in the downloader."})
            CHROME_LINK.update(code="", expires=0)
            CHROME_LINK["sessions"][platform] = session
        return self._send(200, {"ok": True})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/chrome-session":
            return self._receive_chrome_session()
        if u.path == "/api/bye" and self._ok_host() and urllib.parse.parse_qs(u.query).get("t", [""])[0] == TOKEN:
            def bye():
                if not RUN["active"] and time.time() - STATE_META["last_ping"] > 3.5:
                    os._exit(0)
            threading.Timer(4, bye).start()
            return self._send(200, {"ok": True})
        if not self._ok_host() or self.headers.get("X-Token") != TOKEN:
            return self._send(403, {"error": "forbidden"})
        fn = ROUTES.get(urllib.parse.urlparse(self.path).path)
        if not fn:
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            self._send(200, fn(body))
        except Exception as e:
            self._send(500, {"ok": False, "msg": str(e)})


def open_window(url):
    cands = []
    if IS_WIN:
        for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            root = os.environ.get(env)
            if root:
                cands += [os.path.join(root, "Microsoft", "Edge", "Application", "msedge.exe"),
                          os.path.join(root, "Google", "Chrome", "Application", "chrome.exe")]
    else:
        for n in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
            p = shutil.which(n)
            if p:
                cands.append(p)
    for c in cands:
        if os.path.isfile(c):
            try:
                subprocess.Popen([c, f"--app={url}", "--window-size=1320,780"])
                return
            except Exception:
                pass
    import webbrowser
    webbrowser.open(url)


def watchdog():
    # close the server a while after the window is closed (and nothing is downloading)
    while True:
        time.sleep(10)
        if not RUN["active"] and time.time() - STATE_META["last_ping"] > 150:
            os._exit(0)


def main():
    load_settings()
    port = int(os.environ.get("VBD_PORT", "0"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    STATE_META["port"] = srv.server_address[1]
    url = f"http://127.0.0.1:{STATE_META['port']}/"
    print(f"Video Bulk Downloader running at {url}")
    print("yt-dlp:", find_ytdlp() or "NOT FOUND (put yt-dlp.exe next to this file)")
    print("ffmpeg: optional, only used when High-res is switched on")
    print("Close this window to quit.")
    threading.Thread(target=load_version, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    if os.environ.get("VBD_NOWINDOW") != "1":
        open_window(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if IS_WIN and sys.stderr is None:
            from ctypes import windll
            windll.user32.MessageBoxW(None, str(exc), "Video Bulk Downloader", 0x10)
        else:
            raise
