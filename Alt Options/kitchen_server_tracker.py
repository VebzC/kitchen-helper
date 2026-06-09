#!/usr/bin/env python3
"""
Kitchen Display Server v2
-------------------------
Serves the kitchen display, syncs state between devices, and proxies
Spotify "now playing" for the kitchen display widget.

Usage:
    cd /path/to/kitchen/
    python3 kitchen_server.py

Spotify (OPTIONAL):
    1. Edit SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET below
       with values from https://developer.spotify.com/dashboard
    2. In your Spotify app's Settings -> Edit, add this Redirect URI:
         http://localhost:8000/spotify-callback
    3. Restart the server.
    4. Open http://localhost:8000/spotify-login on this MacBook
       to authorize once. Tokens are saved locally and refreshed
       automatically forever after.
    If you don't configure Spotify, the kitchen display still works —
    the Spotify widget just stays hidden.
"""

import base64
import json
import os
import socket
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ============================================
# CONFIG
# ============================================
PORT = 8000
SCRIPT_DIR = Path(__file__).parent.resolve()
HTML_FILE = SCRIPT_DIR / "kitchen_display.html"
STATE_FILE = SCRIPT_DIR / "kitchen_state.json"
HISTORY_FILE = SCRIPT_DIR / "bake_history.json"

# --- SPOTIFY CONFIG (fill these in or leave blank to disable) ---
SPOTIFY_CLIENT_ID = "REDACTED-moved-to-.env"
SPOTIFY_CLIENT_SECRET = "REDACTED-old-secret-moved-to-.env"
SPOTIFY_REDIRECT_URI = f"http://127.0.0.1:{PORT}/spotify-callback"
SPOTIFY_TOKEN_FILE = SCRIPT_DIR / "spotify_tokens.json"
SPOTIFY_SCOPE = "user-read-currently-playing user-read-playback-state user-modify-playback-state"

# ============================================
# RECIPE STATE
# ============================================
state_lock = threading.Lock()

def default_state():
    return {
        "currentStep": 0,
        "timers": [],
        "nextTimerId": 1,
        "version": 0,
        "currentSession": None,
    }

def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                loaded = json.load(f)
            base = default_state()
            base.update(loaded)
            return base
        except Exception:
            pass
    return default_state()

def save_state(s):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(s, f)
    except Exception as e:
        print(f"[warn] could not save state: {e}")

# --- Bake history (the "Bake Diary" feature) ---
history_lock = threading.Lock()

def load_history():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE) as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []

def save_history(history):
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"[warn] could not save bake history: {e}")

state = load_state()

# ============================================
# SPOTIFY
# ============================================
spotify_lock = threading.Lock()
spotify_cache = {"data": None, "fetched_at": 0}
SPOTIFY_CACHE_SECONDS = 4

def spotify_configured():
    return bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET)

def load_spotify_tokens():
    if SPOTIFY_TOKEN_FILE.exists():
        try:
            with open(SPOTIFY_TOKEN_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return None

def save_spotify_tokens(tokens):
    try:
        with open(SPOTIFY_TOKEN_FILE, "w") as f:
            json.dump(tokens, f)
        try:
            os.chmod(SPOTIFY_TOKEN_FILE, 0o600)
        except Exception:
            pass
    except Exception as e:
        print(f"[warn] could not save spotify tokens: {e}")

def spotify_basic_auth_header():
    raw = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()
    return "Basic " + base64.b64encode(raw).decode()

def spotify_exchange_code(code):
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
    }).encode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=body,
        method="POST",
        headers={
            "Authorization": spotify_basic_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode())
    tokens = {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": int(time.time()) + int(data.get("expires_in", 3600)) - 60,
    }
    save_spotify_tokens(tokens)
    return tokens

def spotify_refresh_token(tokens):
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
    }).encode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=body,
        method="POST",
        headers={
            "Authorization": spotify_basic_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode())
    tokens["access_token"] = data["access_token"]
    tokens["expires_at"] = int(time.time()) + int(data.get("expires_in", 3600)) - 60
    if "refresh_token" in data:
        tokens["refresh_token"] = data["refresh_token"]
    save_spotify_tokens(tokens)
    return tokens

def spotify_get_access_token():
    tokens = load_spotify_tokens()
    if not tokens:
        return None
    if tokens.get("expires_at", 0) <= int(time.time()):
        try:
            tokens = spotify_refresh_token(tokens)
        except Exception as e:
            print(f"[warn] spotify refresh failed: {e}")
            return None
    return tokens["access_token"]

def spotify_control(method, endpoint):
    """Send a control command (play/pause/next/previous). Returns (ok, message)."""
    if not spotify_configured():
        return False, "spotify not configured"
    token = spotify_get_access_token()
    if not token:
        return False, "spotify not authorized"
    try:
        req = urllib.request.Request(
            f"https://api.spotify.com/v1/me/player/{endpoint}",
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Length": "0",
            },
        )
        urllib.request.urlopen(req, timeout=5).close()
        # Invalidate now-playing cache so UI updates fast after a control
        with spotify_lock:
            spotify_cache["fetched_at"] = 0
        return True, None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, "no active spotify device — start playing on a device first"
        if e.code == 403:
            return False, "spotify free accounts can't control playback via api (premium required)"
        return False, f"spotify http {e.code}"
    except Exception as e:
        return False, str(e)

def spotify_now_playing():
    with spotify_lock:
        now = time.time()
        if spotify_cache["data"] is not None and (now - spotify_cache["fetched_at"]) < SPOTIFY_CACHE_SECONDS:
            return spotify_cache["data"]

        if not spotify_configured():
            spotify_cache["data"] = {"configured": False, "playing": False}
            spotify_cache["fetched_at"] = now
            return spotify_cache["data"]

        token = spotify_get_access_token()
        if not token:
            spotify_cache["data"] = {"configured": True, "authorized": False, "playing": False}
            spotify_cache["fetched_at"] = now
            return spotify_cache["data"]

        try:
            req = urllib.request.Request(
                "https://api.spotify.com/v1/me/player/currently-playing",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                if r.status == 204:
                    result = {"configured": True, "authorized": True, "playing": False}
                else:
                    data = json.loads(r.read().decode())
                    item = data.get("item") or {}
                    if not item:
                        result = {"configured": True, "authorized": True, "playing": False}
                    else:
                        album = item.get("album") or {}
                        images = album.get("images") or []
                        art_url = images[0]["url"] if images else None
                        for img in images:
                            if 200 <= img.get("width", 0) <= 400:
                                art_url = img["url"]
                                break
                        artists = item.get("artists") or []
                        result = {
                            "configured": True,
                            "authorized": True,
                            "playing": bool(data.get("is_playing")),
                            "track": item.get("name"),
                            "artist": ", ".join(a.get("name", "") for a in artists),
                            "album": album.get("name"),
                            "art_url": art_url,
                            "progress_ms": data.get("progress_ms") or 0,
                            "duration_ms": item.get("duration_ms") or 0,
                            "fetched_at_ms": int(time.time() * 1000),
                        }
        except urllib.error.HTTPError as e:
            if e.code == 401:
                result = {"configured": True, "authorized": False, "playing": False}
            else:
                result = {"configured": True, "authorized": True, "playing": False, "error": str(e)}
        except Exception as e:
            result = {"configured": True, "authorized": True, "playing": False, "error": str(e)}

        spotify_cache["data"] = result
        spotify_cache["fetched_at"] = now
        return result

# ============================================
# NETWORK
# ============================================
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# ============================================
# HTTP HANDLER
# ============================================
class Handler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")

    def _json(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, url):
        self.send_response(302)
        self.send_header("Location", url)
        self.end_headers()

    def _html(self, body, code=200):
        encoded = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        global state
        path = urllib.parse.urlparse(self.path).path
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        if path in ("/", "/index.html"):
            try:
                with open(HTML_FILE, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self._cors()
                self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self.send_error(404, f"HTML file not found at {HTML_FILE}")

        elif path == "/state":
            with state_lock:
                self._json(state)

        elif path == "/reset":
            with state_lock:
                state = default_state()
                state["version"] = 1
                save_state(state)
                self._json(state)

        elif path == "/now-playing":
            self._json(spotify_now_playing())

        elif path == "/spotify-login":
            if not spotify_configured():
                self._html(
                    "<h1>Spotify not configured</h1>"
                    "<p>Edit <code>SPOTIFY_CLIENT_ID</code> and "
                    "<code>SPOTIFY_CLIENT_SECRET</code> in <code>kitchen_server.py</code>, "
                    "then restart the server.</p>",
                    code=400,
                )
                return
            params = urllib.parse.urlencode({
                "client_id": SPOTIFY_CLIENT_ID,
                "response_type": "code",
                "redirect_uri": SPOTIFY_REDIRECT_URI,
                "scope": SPOTIFY_SCOPE,
            })
            self._redirect(f"https://accounts.spotify.com/authorize?{params}")

        elif path == "/spotify-callback":
            code = (query.get("code") or [""])[0]
            err = (query.get("error") or [""])[0]
            if err:
                self._html(f"<h1>Spotify auth error</h1><p>{err}</p>", code=400)
                return
            if not code:
                self._html("<h1>No code received</h1>", code=400)
                return
            try:
                spotify_exchange_code(code)
                self._html(
                    "<h1>&#10003; Spotify connected</h1>"
                    "<p>Tokens saved. Close this tab and return to the kitchen display.</p>"
                    "<p><a href='/'>Back to kitchen display</a></p>"
                )
            except Exception as e:
                self._html(f"<h1>Token exchange failed</h1><p>{e}</p>", code=500)

        elif path == "/history":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            recipe_filter = qs.get("recipe", [None])[0]
            limit = int(qs.get("limit", ["10"])[0])
            with history_lock:
                history = load_history()
            if recipe_filter:
                history = [h for h in history if h.get("recipe") == recipe_filter]
            history = sorted(history, key=lambda h: h.get("startedAt", 0), reverse=True)[:limit]
            self._json({"history": history})

        elif path == "/spotify-status":
            tokens = load_spotify_tokens()
            self._json({
                "configured": spotify_configured(),
                "authorized": tokens is not None,
            })

        elif path == "/spotify-logout":
            # Clear saved tokens (used when re-authorizing with new scopes)
            try:
                if SPOTIFY_TOKEN_FILE.exists():
                    SPOTIFY_TOKEN_FILE.unlink()
                with spotify_lock:
                    spotify_cache["data"] = None
                    spotify_cache["fetched_at"] = 0
                self._html(
                    "<h1>Spotify tokens cleared.</h1>"
                    "<p>Now visit "
                    "<a href='http://127.0.0.1:8000/spotify-login'>http://127.0.0.1:8000/spotify-login</a> "
                    "to re-authorize.</p>"
                )
            except Exception as e:
                self._html(f"<h1>Logout failed</h1><p>{e}</p>", code=500)

        else:
            self.send_error(404)

    def do_POST(self):
        global state
        path = urllib.parse.urlparse(self.path).path
        if path == "/state":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                update = json.loads(body)
                with state_lock:
                    # --- BAKE DIARY: detect events worth logging ---
                    old_step = state.get("currentStep", 0)
                    new_step = update.get("currentStep", old_step)
                    old_timer_ids = {t.get("id") for t in state.get("timers", [])}
                    new_timers = update.get("timers", state.get("timers", []))
                    added_timers = [t for t in new_timers if t.get("id") not in old_timer_ids]

                    # Auto-start a session the first time the user advances from step 0
                    if (not state.get("currentSession")
                            and old_step == 0
                            and new_step > 0
                            and update.get("recipeName")):
                        state["currentSession"] = {
                            "id": f"bake_{int(time.time())}",
                            "recipe": update.get("recipeName"),
                            "totalSteps": update.get("totalSteps", 0),
                            "startedAt": int(time.time()),
                            "stepTransitions": [
                                {"step": 0, "at": int(time.time())},
                            ],
                            "timersRun": [],
                        }

                    # Apply state updates
                    for key in ("currentStep", "timers", "nextTimerId"):
                        if key in update:
                            state[key] = update[key]

                    # Log step transitions during an active session
                    session = state.get("currentSession")
                    if session and new_step != old_step:
                        session["stepTransitions"].append({
                            "step": new_step,
                            "at": int(time.time()),
                        })

                    # Log added timers during an active session
                    if session and added_timers:
                        for t in added_timers:
                            session["timersRun"].append({
                                "name": t.get("name", "Timer"),
                                "durationSec": int((t.get("duration") or 0) / 1000),
                                "startedAt": int(time.time()),
                            })

                    state["version"] = state.get("version", 0) + 1
                    save_state(state)
                    self._json(state)
            except Exception as e:
                self.send_error(400, f"bad request: {e}")
        elif path == "/session/rate":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body) if length else {}
                rating = payload.get("rating")
                notes = (payload.get("notes") or "").strip()
                with state_lock:
                    session = state.get("currentSession")
                    if not session:
                        self.send_error(400, "no active session")
                        return
                    session["endedAt"] = int(time.time())
                    session["durationMinutes"] = max(
                        0, round((session["endedAt"] - session["startedAt"]) / 60)
                    )
                    if rating is not None:
                        session["rating"] = int(rating)
                    if notes:
                        session["notes"] = notes
                    finalized = dict(session)
                    state["currentSession"] = None
                    state["currentStep"] = 0  # ready for next bake
                    state["timers"] = []      # clear timers from finished bake
                    state["version"] = state.get("version", 0) + 1
                    save_state(state)
                with history_lock:
                    history = load_history()
                    history.append(finalized)
                    save_history(history)
                self._json({"ok": True, "session": finalized})
            except Exception as e:
                self.send_error(400, f"bad request: {e}")
        elif path == "/session/discard":
            # User abandons the bake without rating — drop session, don't archive.
            with state_lock:
                state["currentSession"] = None
                state["currentStep"] = 0
                state["timers"] = []
                state["version"] = state.get("version", 0) + 1
                save_state(state)
            self._json({"ok": True})
        elif path == "/spotify-play":
            ok, msg = spotify_control("PUT", "play")
            self._json({"ok": ok, "error": msg})
        elif path == "/spotify-pause":
            ok, msg = spotify_control("PUT", "pause")
            self._json({"ok": ok, "error": msg})
        elif path == "/spotify-next":
            ok, msg = spotify_control("POST", "next")
            self._json({"ok": ok, "error": msg})
        elif path == "/spotify-previous":
            ok, msg = spotify_control("POST", "previous")
            self._json({"ok": ok, "error": msg})
        else:
            self.send_error(404)

    def log_message(self, fmt, *args):
        pass

# ============================================
# MAIN
# ============================================
def main():
    if not HTML_FILE.exists():
        print(f"\n[ERROR] kitchen_display.html not found at:")
        print(f"        {HTML_FILE}")
        print(f"        Make sure both files are in the same folder.\n")
        return

    ip = get_local_ip()
    bar = "=" * 60
    print(f"\n{bar}")
    print(f"  KITCHEN DISPLAY SERVER v2")
    print(f"{bar}")
    print(f"\n  Laptop (this MacBook):")
    print(f"    http://localhost:{PORT}")
    print(f"\n  iPhone (same WiFi):")
    print(f"    http://{ip}:{PORT}")

    if spotify_configured():
        tokens = load_spotify_tokens()
        if tokens:
            print(f"\n  Spotify: configured + authorized")
        else:
            print(f"\n  Spotify: configured but NOT authorized")
            print(f"  -> Open http://localhost:{PORT}/spotify-login on this MacBook to authorize")
    else:
        print(f"\n  Spotify: not configured (widget will stay hidden)")
        print(f"  -> See top of kitchen_server.py for setup steps")

    print(f"\n  Press Ctrl+C to stop.")
    print(f"{bar}\n")

    try:
        with ThreadingHTTPServer(("0.0.0.0", PORT), Handler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped. State saved to kitchen_state.json")
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"\n[ERROR] Port {PORT} is already in use.")
            print(f"        Run: lsof -ti:{PORT} | xargs kill -9\n")
        else:
            raise

if __name__ == "__main__":
    main()
