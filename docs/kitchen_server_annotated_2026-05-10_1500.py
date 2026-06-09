#!/usr/bin/env python3
# ============================================================================
# READ ME FIRST — orientation for this annotated file
# ============================================================================
# This is the server side of the kitchen display app. It does three jobs:
#
#   1. Serves the HTML page that the phone and laptop both load in a browser.
#   2. Holds the canonical cooking state (current step, timers) in memory and
#      on disk, so two devices can stay in sync by talking to this server
#      instead of to each other.
#   3. Proxies Spotify — the browser asks this server "what's playing,"
#      this server asks Spotify, and caches the answer for 4 seconds so
#      multiple devices don't hammer Spotify's API.
#
# The annotations below explain each section and call out non-obvious bits.
# Lines tagged "DESIGN NOTE" are observations about Ousterhout's deep/shallow
# module distinction — places where the code's structure is doing real work,
# or places where it would creak if extended without care.
#
# DESIGN NOTE — surface area
#   Of the 13 HTTP routes this server exposes, only 4 are core to the cooking
#   app: GET /, GET /state, POST /state, GET /reset. The other 9 are Spotify
#   scaffolding. The peripheral feature owns roughly two-thirds of the route
#   surface, which tells you where the complexity in this file actually lives.
# ============================================================================

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

# ============================================================================
# CONFIG
# ============================================================================
# All the knobs that govern how the server behaves, gathered in one place at
# the top of the file. The pattern of dumping every config value into module-
# level constants is fine for a single-file app like this — for anything
# bigger, these would normally move to environment variables or a config file
# so they can change between dev and production without editing the code.
#
# PORT 8000 is what both the laptop browser and the phone connect to.
# HTML_FILE is the page this server hands back when someone hits the root URL.
# STATE_FILE is where cooking state gets persisted to disk between sessions.
# ============================================================================
PORT = 8000
SCRIPT_DIR = Path(__file__).parent.resolve()
HTML_FILE = SCRIPT_DIR / "kitchen_display.html"
STATE_FILE = SCRIPT_DIR / "kitchen_state.json"

# --- SPOTIFY CONFIG (fill these in or leave blank to disable) ---
# Client ID and secret come from the Spotify developer dashboard and identify
# this specific app to Spotify's auth servers. The redirect URI must match
# exactly what's registered in the dashboard, or Spotify rejects the auth flow.
# The scope string lists what permissions this app is asking for — reading the
# currently-playing track, reading playback state, and modifying playback.
SPOTIFY_CLIENT_ID = "REDACTED-moved-to-.env"
SPOTIFY_CLIENT_SECRET = "REDACTED-moved-to-.env"
SPOTIFY_REDIRECT_URI = f"http://127.0.0.1:{PORT}/spotify-callback"
SPOTIFY_TOKEN_FILE = SCRIPT_DIR / "spotify_tokens.json"
SPOTIFY_SCOPE = "user-read-currently-playing user-read-playback-state user-modify-playback-state"

# ============================================================================
# RECIPE STATE — the load-bearing core of the cooking app
# ============================================================================
# This is where the canonical cooking state lives. Both the phone and the
# laptop hold their own local copies of this same data, but this server is
# the single source of truth. Whenever a device changes something — taps
# "next step," adds a timer — it pushes its change here, this server writes
# it down, and the other device picks it up on its next poll.
#
# The state has four fields. currentStep is the index of the cooking step
# being shown. timers is a list of timer objects. nextTimerId is a counter
# used to assign a unique id to each new timer. version is a counter that
# bumps by 1 every time the state changes — this is what lets each device
# tell whether the state it just received from the server is genuinely new
# or identical to what it already has.
#
# state_lock is a thread lock. Because this server uses ThreadingHTTPServer,
# each incoming request runs on its own thread, and two requests could
# theoretically try to read or write the state dictionary at the same time.
# The lock ensures only one thread is touching state at a time, preventing
# the kind of corruption that happens when concurrent writes interleave.
# ============================================================================
state_lock = threading.Lock()

def default_state():
    return {
        "currentStep": 0,
        "timers": [],
        "nextTimerId": 1,
        "version": 0,
    }

# Loads state from disk on server startup. If the file is missing or
# malformed, falls back to a fresh default_state. The merge of base.update(loaded)
# is a small piece of forward compatibility — if a future version of the
# server adds a new field to default_state, an old saved file that lacks
# that field will still load cleanly, with the new field taking its default.
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

# Writes state to disk after every change. Failures are logged but not
# raised — a save failure shouldn't crash the server mid-cooking.
def save_state(s):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(s, f)
    except Exception as e:
        print(f"[warn] could not save state: {e}")

# The single in-memory copy of state, loaded once on startup.
state = load_state()

# ============================================================================
# SPOTIFY — peripheral feature, owns most of this file
# ============================================================================
# Everything from here through the end of spotify_now_playing handles talking
# to Spotify on behalf of the browser. Spotify's API requires an access token
# on every request, and access tokens expire after an hour. So this section
# spends most of its weight handling tokens — exchanging an authorization
# code for tokens on first use, refreshing tokens when they expire, and
# saving tokens to disk so they survive server restarts.
#
# DESIGN NOTE — deep module
#   spotify_get_access_token (defined below) is a good example of a deep
#   module. Callers ask for a token. They never have to know whether one
#   was loaded from disk, refreshed from Spotify, or whether it expired
#   between the last call and this one. All of that complexity is hidden
#   behind a one-line interface that returns "the access token, ready to
#   use." Two upstream functions — spotify_now_playing and spotify_control
#   — both depend on it, and neither has to think about token lifetimes.
# ============================================================================

# Cache layer. spotify_now_playing is hit roughly every 5 seconds from each
# device. With phone + laptop both polling, that's 24 calls per minute to
# Spotify's API for the same question. The 4-second cache collapses any
# burst of identical requests within a 4-second window into a single
# upstream API call. This is invisible to callers — they always get a
# fresh-looking response, just sometimes from cache.
spotify_lock = threading.Lock()
spotify_cache = {"data": None, "fetched_at": 0}
SPOTIFY_CACHE_SECONDS = 4

# Returns True only if the developer pasted in a Client ID and Secret.
# If either is blank, Spotify features are silently disabled and the
# widget on the page just stays hidden — the cooking app still works.
def spotify_configured():
    return bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET)

# Token persistence. Tokens are written to spotify_tokens.json with
# permission 600 (owner read/write only) so they aren't world-readable.
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

# Builds the HTTP Basic Auth header that Spotify's token endpoints require
# for client authentication. This is separate from the user's access token —
# it identifies this app to Spotify, not the user.
def spotify_basic_auth_header():
    raw = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()
    return "Basic " + base64.b64encode(raw).decode()

# First-time auth handshake. After the user logs in to Spotify in their
# browser, Spotify redirects them back to /spotify-callback with a temporary
# "code" in the URL. This function trades that code with Spotify's token
# endpoint for a real access token (1-hour life) and a refresh token
# (long-lived). Both get saved to disk. The expires_at timestamp has 60
# seconds shaved off it so we refresh slightly before Spotify actually
# expires the token, avoiding a race where we send a request with a token
# that just went stale.
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

# Token refresh. When an access token expires, we use the refresh token —
# which doesn't expire as quickly — to get a fresh access token without
# making the user log in again. Spotify sometimes returns a new refresh
# token along with the new access token; if so, we replace ours.
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

# The convergence point — every Spotify-using function in this server
# eventually calls this to get a usable access token. It tries the cached
# tokens first; if they've expired, it refreshes; if refresh fails, it
# returns None and callers degrade gracefully. The simplicity of the
# interface ("give me a token") hides the entire token lifecycle from
# everyone above it.
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

# Sends a control command to Spotify (play, pause, next, previous). All
# four POST endpoints below — /spotify-play, /spotify-pause, /spotify-next,
# /spotify-previous — call this function with different arguments. The
# function returns (ok, error_message) so callers can report meaningful
# errors back to the browser.
#
# DESIGN NOTE — pass-through pattern
#   In do_POST below, you'll see four 1-line route handlers that all just
#   call this function with different arguments. That's a classic pass-
#   through pattern. At 4 routes it's fine. If this grew to 10+ control
#   actions, the pattern would start to smell — every new action requires
#   another route block. A cleaner shape would be a single /spotify-control
#   endpoint that takes the action as a parameter, but the current shape
#   is appropriate for the size.
#
# After a successful control command, the cache is forcibly invalidated.
# Without this, the next /now-playing fetch from the browser could return
# the old cached track for up to 4 seconds, making the UI feel unresponsive
# right after the user tapped a button.
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

# The "what's playing right now" function. Hits Spotify's currently-playing
# endpoint, extracts the fields the browser cares about, and returns a
# compact dict. The cache check at the top means most calls return without
# hitting Spotify at all. Album art selection is a small but useful detail:
# Spotify returns multiple image sizes; this prefers the medium-sized one
# (200-400px wide) since the widget is small and the largest image would
# waste bandwidth.
def spotify_now_playing():
    with spotify_lock:
        now = time.time()
        # If we have a recent enough cached response, return it without
        # hitting Spotify. This is the heart of the rate-limiting strategy.
        if spotify_cache["data"] is not None and (now - spotify_cache["fetched_at"]) < SPOTIFY_CACHE_SECONDS:
            return spotify_cache["data"]

        # Three layers of "is this even going to work" checks. Each returns
        # a structured response telling the browser exactly what state we're
        # in, so the widget can show appropriate UI (hidden, "configure me,"
        # "log in," etc.) instead of just failing silently.
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
                # 204 No Content from Spotify means "authorized but nothing
                # is currently playing" — distinct from a real error.
                if r.status == 204:
                    result = {"configured": True, "authorized": True, "playing": False}
                else:
                    data = json.loads(r.read().decode())
                    item = data.get("item") or {}
                    if not item:
                        result = {"configured": True, "authorized": True, "playing": False}
                    else:
                        # Album art selection — prefer a medium-sized image
                        # over Spotify's default largest, since the widget
                        # displays the art at ~80px max.
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
            # 401 specifically means the token's been revoked or invalidated
            # by Spotify on their side, which is recoverable by re-authorizing.
            # Other HTTP errors get shown verbatim.
            if e.code == 401:
                result = {"configured": True, "authorized": False, "playing": False}
            else:
                result = {"configured": True, "authorized": True, "playing": False, "error": str(e)}
        except Exception as e:
            result = {"configured": True, "authorized": True, "playing": False, "error": str(e)}

        spotify_cache["data"] = result
        spotify_cache["fetched_at"] = now
        return result

# ============================================================================
# NETWORK
# ============================================================================
# Figures out the laptop's local IP address on the WiFi network so the server
# can print a "your phone connects here" URL on startup. The trick is opening
# a UDP socket toward an external address (8.8.8.8 is Google's DNS, just used
# as a target) — this forces the OS to pick which network interface it would
# use, and we can read the IP off that. No actual packets are sent. Falls
# back to localhost if there's no network.
# ============================================================================
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# ============================================================================
# HTTP HANDLER — every incoming request lands here
# ============================================================================
# This class is what Python's HTTP server library uses to handle requests.
# When a browser sends a GET, the library calls do_GET on a fresh instance
# of this class. When it sends a POST, do_POST. When it sends OPTIONS (a
# pre-flight check browsers do for cross-origin requests), do_OPTIONS.
# These method names are not chosen — the library is hardcoded to look for
# them.
#
# The 13 routes the server exposes don't exist as separate functions. They
# live as branches inside do_GET and do_POST. To find the code that handles
# a particular URL, scroll to the matching method and read down the if/elif
# chain.
#
# DESIGN NOTE — shallow by accumulation
#   The if/elif chains in do_GET and do_POST grow linearly with every new
#   endpoint. At 13 routes it's readable. At 30 it would be a chore.
#   When kitchen_import.py adds new routes, this is the function that
#   gets longer. Worth thinking about whether to keep extending the chain
#   or move to a route-table dispatch pattern (a dict mapping path strings
#   to handler functions). Not urgent, but file it.
# ============================================================================
class Handler(BaseHTTPRequestHandler):

    # Helpers below are small wrappers around the standard response-writing
    # boilerplate, used by every route to return JSON, HTML, or a redirect.
    # Pulling these out keeps the route code focused on intent rather than
    # the mechanics of "set a header, set another header, write the body."

    def _cors(self):
        # CORS headers tell the browser this server is willing to be called
        # from a different origin. Needed because the phone might load the
        # page from one URL and call the API from another.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")

    def _json(self, payload, code=200):
        # Serializes a Python dict to JSON and sends it back as the response.
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, url):
        # 302 redirect — the browser will follow this to the target URL.
        # Used for the Spotify auth handoff.
        self.send_response(302)
        self.send_header("Location", url)
        self.end_headers()

    def _html(self, body, code=200):
        # Sends a chunk of HTML directly. Used for the small status pages
        # the Spotify auth flow shows ("✓ connected", "auth error", etc.).
        encoded = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    # OPTIONS is a pre-flight check the browser sends before some cross-
    # origin requests. We just acknowledge it with CORS headers and a 204
    # (No Content) so the actual request can proceed.
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    # do_GET handles all 9 GET routes. Each route is an elif branch below.
    # The branches range from "serve the HTML file" to "kick off Spotify
    # auth" to "return current state." Several Spotify routes here implement
    # the auth handshake — login redirects to Spotify, callback receives the
    # code and exchanges it for tokens, status reports config, logout clears
    # tokens.
    def do_GET(self):
        global state
        path = urllib.parse.urlparse(self.path).path
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        # GET / — serves the kitchen display HTML page. This is what every
        # browser hits first when it loads the app.
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

        # GET /state — returns the current cooking state as JSON. Polled by
        # every connected browser ~1.6 times per second. The lock ensures
        # we don't return a state mid-mutation from a concurrent POST.
        elif path == "/state":
            with state_lock:
                self._json(state)

        # GET /reset — wipes state back to defaults (step 0, no timers) and
        # bumps version to 1 so connected browsers see the change. Used at
        # the end of a cooking session.
        elif path == "/reset":
            with state_lock:
                state = default_state()
                state["version"] = 1
                save_state(state)
                self._json(state)

        # GET /now-playing — proxies through to Spotify (with caching).
        elif path == "/now-playing":
            self._json(spotify_now_playing())

        # GET /spotify-login — kicks off the OAuth flow by redirecting the
        # browser to Spotify's authorize page. After the user logs in,
        # Spotify will redirect them back to /spotify-callback.
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

        # GET /spotify-callback — receives the temporary auth code from
        # Spotify after the user logs in, trades it for real tokens, and
        # shows a success page.
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

        # GET /spotify-status — tells the browser whether Spotify is set up
        # and authorized, so the UI can show appropriate messaging.
        elif path == "/spotify-status":
            tokens = load_spotify_tokens()
            self._json({
                "configured": spotify_configured(),
                "authorized": tokens is not None,
            })

        # GET /spotify-logout — deletes saved tokens and clears the cache.
        # Used when re-authorizing with new scopes (e.g. when adding the
        # playback control scope to an existing setup).
        elif path == "/spotify-logout":
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

    # do_POST handles all 5 POST routes. The first one — POST /state — is
    # the load-bearing line of the whole sync system. The other four are
    # Spotify control pass-throughs.
    def do_POST(self):
        global state
        path = urllib.parse.urlparse(self.path).path

        # POST /state — the only line that mutates canonical cooking state.
        # Body is JSON with some subset of {currentStep, timers, nextTimerId}.
        # Server merges those fields in, bumps version by 1, saves to disk,
        # and returns the new state. The version bump is what makes cross-
        # device sync work: each browser polls GET /state, sees the version
        # has changed since its last fetch, and repaints the screen.
        #
        # Without the version bump, browsers would have no efficient way to
        # tell whether incoming state is genuinely new or identical to what
        # they already have, and would either repaint constantly (jittery)
        # or have to deep-compare the full state object every poll (slow).
        if path == "/state":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                update = json.loads(body)
                with state_lock:
                    for key in ("currentStep", "timers", "nextTimerId"):
                        if key in update:
                            state[key] = update[key]
                    state["version"] = state.get("version", 0) + 1
                    save_state(state)
                    self._json(state)
            except Exception as e:
                self.send_error(400, f"bad request: {e}")

        # The four Spotify control pass-throughs. Each just calls
        # spotify_control with different arguments. See the DESIGN NOTE
        # above spotify_control for the pattern.
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

    # Suppress the default per-request log line. Without this, every browser
    # poll (1.6 times per second) would print to the terminal.
    def log_message(self, fmt, *args):
        pass

# ============================================================================
# MAIN — server startup
# ============================================================================
# What runs when you launch the server from the command line. Prints a few
# helpful URLs (laptop, phone), reports Spotify status, then hands control
# to the threaded HTTP server which runs forever until Ctrl+C.
#
# ThreadingHTTPServer means each incoming request gets its own thread, so
# the laptop polling /state doesn't block the phone trying to push a
# change. The locks defined earlier (state_lock, spotify_lock) are what
# keep that concurrency safe.
# ============================================================================
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
