# Kitchen Helper

A cooking display for our kitchen wall. A small Python server (`kitchen_server.py`) serves a single-page app (`kitchen_display.html`) to the wall screen and our phones, keeps them in sync, and proxies Spotify so music controls sit next to the recipe.

Recipe import (`kitchen_import.py`, `kitchen_import.html`) uses Claude to turn a pasted recipe into structured ingredients, steps and timers. A review screen lets you correct the result before it's saved to the recipe library.

- Setup: `SETUP.md`
- The milestone prompts I wrote to build it with Claude Code: `docs/claude-code-prompts/`
