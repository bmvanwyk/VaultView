# AGENTS.md — Working on VaultView

## Project type

This is a **single-file Flask app** with inline HTML/CSS/JS. There is no build step, no bundler, no frontend framework. The entire application lives in `app.py`.

## How to test your changes

```bash
# Start with a test vault
OBSIDIAN_VAULT_PATH=/tmp/test-vault python3 app.py

# Run health check
curl -s -u hermes:hermes http://localhost:9120/health

# Test APIs
curl -s -u hermes:hermes http://localhost:9120/api/graph | python3 -m json.tool
curl -s -u hermes:hermes http://localhost:9120/api/tree | python3 -m json.tool

# Test page rendering
curl -s -u hermes:hermes http://localhost:9120/ | grep -c "Home"
```

**Always verify:** after any change, load `http://localhost:9120` in a real browser and check:
- File tree renders and folders expand/collapse
- Content area scrolls with browser (not trapped inner scrollbar)
- Backlinks panel shows on notes with incoming links, hides on orphans
- Graph view opens, nodes are readable, zoom/pan works
- Search returns results with highlighted matches
- Mobile layout doesn't break (resize to 400px wide)

## File responsibilities

| File | Owns | Do NOT put here |
|------|------|-----------------|
| `app.py` | Everything — routes, API, template, CSS, JS | External dependencies beyond Flask + markdown |
| `docs/architecture.md` | Design decisions, diagrams, tradeoffs | Step-by-step setup (that's README) |
| `README.md` | Quick start, features, env vars | Architecture details |
| `AGENTS.md` | This file — dev guidance | User docs |

## Key design rules

### Python (app.py)

1. **`scan_notes()` is the data layer.** Everything flows from a full vault scan — graph, tree, backlinks, search. Cache nothing. Re-scan on every request.

2. **`render_markdown()` owns wikilink conversion.** The regex `\[\[([^\]]+)\]\]` runs after Python-Markdown. Self-links become `<strong>`, others become `<a>` with `data-note` attributes.

3. **`build_graph()` returns `{nodes: [...], links: [...]}`.** Nodes have `id` and `group`. Links have `source` and `target` (indices into nodes array). The JS client does the layout.

4. **`build_file_tree()` returns nested dicts.** Folders are dicts, `.md` files are leaf string values (note name). The template's `_render_file_tree()` converts to HTML recursively.

5. **Auth is stateless basic auth.** No sessions, no cookies, no CSRF tokens. `requires_auth` decorator checks `Authorization` header on every request.

### Frontend (inline JS in the template)

6. **The file tree uses `.folder-children.collapsed { display: none }`** — no JS animation, just CSS toggling. The `data-folder` attribute links folder name divs to their children divs.

7. **Backlinks load async.** On page load, JS fetches `/api/backlinks/<current>` and renders the right panel. Panel hides with `style.display = 'none'` when empty (no wasted space).

8. **Graph view is hub-and-spoke, NOT force simulation.** Find the most-connected node → center. Arrange others in a circle. This guarantees readability. Zoom/pan via SVG transform on a `<g>` element.

9. **Content area uses browser scroll, not inner scroll.** The sidebar and backlinks panel are `position: fixed`. The content `main` has `margin-left: 260px` and no `overflow-y`. This prevents trapped scrollbars.

10. **Graph scroll doesn't leak.** `svg.onwheel` checks `graphOverlay.classList.contains('show')` before calling `preventDefault()`. ESC key also closes the graph overlay.

### CSS / Layout

11. **Three-column layout: fixed sidebar + fluid content + conditional panel.** On narrow screens (<768px), the layout should stack vertically. Test this.

12. **Dark theme uses CSS custom properties.** `--bg`, `--sidebar-bg`, `--text`, `--link`, `--accent`, etc. All in `:root`. Change once, applies everywhere.

13. **Wikilinks get `color: var(--wikilink)`** (purple). Self-links get `color: var(--gold)` (gold). External links get `color: var(--link)` (blue).

## Common pitfalls

- **Don't add a JavaScript framework.** The app is 20KB of inline JS. A framework would 10x the payload for zero benefit at this scale.
- **Don't cache vault data.** Re-scanning on every request is deliberately simple and correct. Premature caching causes stale data bugs when notes change via git sync.
- **Don't use inner scrollbars.** `overflow-y: auto` on anything except the sidebar file tree is a bug. The browser window should scroll.
- **Don't break the hub-and-spoke layout.** Force simulations look cool but read poorly. The circular layout is boring and reliable — that's the point.
- **Test with real vaults.** The test vault should have notes with wikilinks, nested folders, and varied markdown (tables, code blocks, lists, checkboxes).

## Naming conventions

- Python functions: `snake_case` (`scan_notes`, `build_file_tree`)
- JS functions: `camelCase` (`showGraph`, `renderGraph`)
- CSS classes: `kebab-case` (`.file-tree`, `.graph-overlay`)
- API routes: `/api/` prefix, kebab-case (`/api/backlinks`)
- Page routes: `/` prefix, kebab-case (`/note/<name>`, `/search`)

## PR checklist

- [ ] `curl` tests pass for all `/api/` endpoints
- [ ] Browser test: desktop (1400px) and mobile (400px)
- [ ] Graph view: nodes readable, zoom/pan smooth, ESC closes
- [ ] Backlinks: panel hides when empty, shows correct links
- [ ] File tree: nested folders expand/collapse
- [ ] Search: returns results, highlights matches
- [ ] No inner scrollbars — browser scrolls the page
- [ ] `requirements.txt` unchanged unless new dep added
