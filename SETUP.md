# Kitchen Display — Setup (v2)

Core files. Keep them in the **same folder** on your MacBook:

- `kitchen_server.py` — local server, syncs state, proxies Spotify
- `kitchen_display.html` — the actual app
- `kitchen_import.py` — recipe import (Claude-powered parsing)
- `.env` — your secrets (created from `.env.example`, never committed)
- `SETUP.md` — this file

The cooking display needs no installs — macOS already has Python 3. The recipe
import feature needs one pip package (see "Dependencies" below).

---

## .env setup

All secrets live in a single `.env` file next to `kitchen_server.py`. Create it
by copying the template:

```bash
cp .env.example .env
```

Then fill in the keys:

- `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` — from
  https://developer.spotify.com/dashboard (see Part 2 below). Leave blank to
  disable Spotify; the cooking display works without it.
- `ANTHROPIC_API_KEY` — from https://platform.claude.com (API Keys page).
  Leave blank to disable recipe import; the cooking display works without it.

The server reads `.env` at startup, so restart it after any change. `.env` is
gitignored — secrets never enter version control.

---

## Dependencies

Recipe import uses the official `anthropic` Python package (the project's only
pip dependency — everything else is stdlib):

```bash
pip3 install anthropic
```

On newer macOS, Python is "externally managed" and plain pip3 refuses to
install. This is the command that works (verified on this MacBook):

```bash
pip3 install --user --break-system-packages anthropic
```

If `anthropic` isn't installed, the server still starts and the cooking
display works — only `POST /import` is disabled.

---

## Part 1 — Get the kitchen display running (60 seconds)

### 1. Pick a folder

Suggested: `~/Documents/kitchen/`. Drop the three files in there.

### 2. Start the server

Open Terminal:

```bash
cd ~/Documents/kitchen
python3 kitchen_server.py
```

Output:

```
============================================================
  KITCHEN DISPLAY SERVER v2
============================================================

  Laptop (this MacBook):
    http://localhost:8000

  iPhone (same WiFi):
    http://192.168.1.42:8000      ← your IP will differ

  Spotify: not configured (widget will stay hidden)

  Press Ctrl+C to stop.
============================================================
```

**Leave the Terminal window open while you cook.**

### 3. Connect both screens

**27" monitor (display):**
- Plug HDMI/USB-C from MacBook → monitor.
- **Rotate the monitor physically to portrait.** Then in macOS: **System Settings → Displays → click the external display → set Rotation to 90°** (try both 90° and 270° to find the orientation where the bottom of the picture is at the bottom of the actual screen).
- Open Chrome on your MacBook → drag the window onto the 27" → press `Ctrl+Cmd+F` for fullscreen.
- Go to `http://localhost:8000`.
- The layout will automatically switch to portrait mode — bigger text, timers as a horizontal grid up top, recipe in the main space.

**iPhone (primary controller):**
- Open **Safari** (must be Safari for next step), type the iPhone URL the script printed.
- Tap **Share** → **Add to Home Screen** → name it "Kitchen" → Add.
- Now you have a fullscreen app icon. Use that going forward — Safari chrome stays out of the way.

### 4. Use it

- Tap **Next →** on either screen. Both update.
- Tap **+ New Timer** to start a timer. State syncs.
- The dot next to the clock is **green = synced, red = offline**. If red: MacBook went to sleep, or WiFi dropped.

**Keyboard shortcuts** (laptop, when nearby):
- `→` / `Space` = Next, `←` = Back, `T` = New timer

---

## Part 2 — Spotify now-playing (one-time setup, ~5 minutes)

### 1. Get your Spotify credentials

Go to https://developer.spotify.com/dashboard. Open the app you created (or create one if you haven't).

In the app's **Settings** page, you'll need:

- **Client ID** — visible at the top
- **Client secret** — click "View client secret"

In **Settings → Edit**, scroll to **Redirect URIs** and add this exact URL:

```
http://localhost:8000/spotify-callback
```

Click **Save** at the bottom of the Edit page.

### 2. Paste credentials into .env

Open `.env` in any text editor (create it from `.env.example` first if you
haven't — see ".env setup" above). Fill in your values:

```
SPOTIFY_CLIENT_ID=abc123...
SPOTIFY_CLIENT_SECRET=xyz789...
```

Save the file.

### 3. Restart the server

In Terminal: `Ctrl+C` to stop, then `python3 kitchen_server.py` to start again. You should see:

```
Spotify: configured but NOT authorized
-> Open http://localhost:8000/spotify-login on this MacBook to authorize
```

### 4. One-time authorization

In your laptop browser, go to:

```
http://localhost:8000/spotify-login
```

You'll be redirected to Spotify, asked to log in (use the account you want to track), then asked to authorize the app. Approve. You'll be redirected back to a success page.

That's it. The server now has refresh tokens saved to `spotify_tokens.json` in your kitchen folder. They auto-renew — you'll never need to log in again unless you delete that file or change your Spotify password.

### 5. Play something

Start playing music on Spotify (any device — phone, desktop, web player, Sonos). Within a few seconds, the now-playing widget appears in the top-right corner of the kitchen display, showing album art, track name, artist, and progress bar.

If nothing's playing, the widget hides. The kitchen display works either way.

---

## When things go wrong

**"Address already in use" on server start.**
A previous server is still running. Run:
```bash
lsof -ti:8000 | xargs kill -9
```
Then start again.

**iPhone can't reach the server.**
- Both devices on the same WiFi (iPhone not on cellular).
- Your MacBook's IP may have changed — re-check the script's startup output for the current IP.
- macOS firewall: System Settings → Network → Firewall → ensure Python is allowed (popup appears the first time).

**MacBook went to sleep mid-bake.**
Open the lid; server resumes automatically. To prevent it during long bakes:
```bash
caffeinate -d &
python3 kitchen_server.py
```
Kill caffeinate later: `pkill caffeinate`.

**Spotify widget shows briefly then disappears.**
You stopped playback, or paused. The widget only shows when actively playing.

**Spotify widget never appears.**
- Confirm `/now-playing` endpoint responds: in the laptop browser, go to `http://localhost:8000/now-playing`. If it returns `{"configured": false, ...}`, your Client ID/Secret aren't pasted in. If `{"configured": true, "authorized": false, ...}`, you haven't completed `/spotify-login`. If `{"configured": true, "authorized": true, "playing": false}`, no music is currently playing.
- If you see `playing: true` in JSON but the widget doesn't appear, hard-refresh the page (Cmd+Shift+R).

**Reset everything to step 1.**
Visit `http://localhost:8000/reset` once. Or delete `kitchen_state.json`.

**"Add to Home Screen" doesn't appear in iOS Safari.**
You're not on Safari (it's hidden in Chrome iOS). Switch to Safari, reload, then Share → Add.

---

## Adding more recipes later

Open `kitchen_display.html` in any text editor. Find the `RECIPE = {` block near the top of the `<script>` section (around line 540). Replace with new recipe in the same shape:

```javascript
const RECIPE = {
  name: "Recipe Name",
  metaLine: "Subtitle  •  Oven temp  •  Pan info",
  steps: [
    {
      title: "Short action title",
      instruction: "Full instruction with amounts inline.",
      timeNote: "X min — start timer",
      ingredients: [
        { amount: "100g", name: "ingredient" }
      ]
    },
    // ...
  ]
};
```

Save, refresh both devices.

---

## Safety note on `spotify_tokens.json`

After authorization, `spotify_tokens.json` lives in your kitchen folder. The file permissions are restricted to your user (mode 0600), but **don't commit this folder to a public GitHub repo** — the refresh token in there grants access to your Spotify. If you ever want to share the project, move secrets to a separate untracked config file first.
