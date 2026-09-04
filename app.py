#!/usr/bin/env python3
"""
VaultView — A lightweight web viewer for Obsidian vaults.
Serves markdown with [[wikilink]] support, nested file tree,
backlinks, and interactive graph view.
"""
import os, re, json, html
from urllib.parse import quote
from datetime import datetime
from pathlib import Path
from functools import wraps
from collections import defaultdict
from flask import Flask, request, redirect, url_for, jsonify, abort, Response, session, make_response

VAULT_PATH = os.environ.get("OBSIDIAN_VAULT_PATH", os.path.expanduser("~/Documents/Obsidian Vault"))
PORT = int(os.environ.get("VAULT_VIEWER_PORT", "9120"))
AUTH_USER = os.environ.get("VAULT_VIEWER_USER", "hermes")
AUTH_PASS = os.environ.get("VAULT_VIEWER_PASS", "hermes")

app = Flask(__name__)
app.secret_key = os.environ.get("VAULT_VIEWER_SECRET", os.urandom(24).hex())

import markdown
md = markdown.Markdown(extensions=['fenced_code', 'tables', 'codehilite'])

def check_auth(username, password):
    return username == AUTH_USER and password == AUTH_PASS

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('logged_in'):
            return f(*args, **kwargs)
        return redirect(url_for('login_page'))
    return decorated

# ── Login / Logout ──────────────────────────────────────────
LOGIN_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>VaultView — Unlock</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#c9d1d9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  height:100vh;display:flex;align-items:center;justify-content:center}
.card{background:#161b22;border:1px solid #30363d;border-radius:16px;padding:36px 32px;
  width:340px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,.4)}
.logo{width:48px;height:48px;border-radius:12px;background:linear-gradient(145deg,#7c3aed,#a78bfa);
  display:flex;align-items:center;justify-content:center;font-weight:800;font-size:22px;color:#fff;
  margin:0 auto 12px}
h1{font-size:18px;font-weight:600;margin-bottom:4px;color:#f0f6fc}
.sub{font-size:12px;color:#8b949e;margin-bottom:24px}
input{width:100%;padding:10px 14px;border-radius:10px;border:1px solid #30363d;
  background:#0d1117;color:#c9d1d9;font-size:14px;outline:none;margin-bottom:12px}
input:focus{border-color:#7c3aed;box-shadow:0 0 0 3px #7c3aed22}
button{width:100%;padding:10px;border-radius:10px;border:none;background:#7c3aed;
  color:#fff;font-size:14px;font-weight:600;cursor:pointer}
button:hover{opacity:.9}
.error{color:#f85149;font-size:12px;margin-bottom:12px;display:none}
</style>
</head>
<body>
<div class="card">
  <div class="logo">📓</div>
  <h1>Unlock Your Vault</h1>
  <p class="sub">Enter your password to continue</p>
  <form method="post" action="/login">
    <input type="password" name="password" placeholder="Password" autofocus>
    <p class="error" id="error">Wrong password</p>
    <button type="submit">🔓 Unlock</button>
  </form>
</div>
<script>
const params = new URLSearchParams(window.location.search);
if (params.get('error')) document.getElementById('error').style.display = 'block';
</script>
</body>
</html>"""

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        if request.form.get('password') == AUTH_PASS:
            session['logged_in'] = True
            return redirect(url_for('index'))
        return redirect('/login?error=1')
    if session.get('logged_in'):
        return redirect(url_for('index'))
    return LOGIN_PAGE

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

# ── Data layer ──────────────────────────────────────────────
def scan_notes():
    """Return {name: {path, links: [...], tags: [...]}} for all notes."""
    notes = {}
    for f in sorted(Path(VAULT_PATH).rglob("*.md")):
        rel = str(f.relative_to(VAULT_PATH))
        name = f.stem
        content = f.read_text()
        links = re.findall(r'\[\[([^\]]+)\]\]', content)
        # Clean links (remove |display suffix)
        links = [l.split('|')[0].strip() for l in links]
        tags = re.findall(r'#(\w[\w-]*)', content)
        notes[name] = {
            'path': rel,
            'links': list(set(links)),
            'tags': list(set(tags)),
        }
    return notes

def build_file_tree():
    """Build a nested file tree from the vault."""
    tree = {}
    for f in sorted(Path(VAULT_PATH).rglob("*.md")):
        parts = f.relative_to(VAULT_PATH).parts
        current = tree
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = f.stem  # leaf = note name
    return tree

def build_backlinks(notes, target_name):
    """Find all notes that link to target_name."""
    backlinks = []
    for name, data in notes.items():
        if name == target_name:
            continue
        if target_name in data['links']:
            backlinks.append(name)
    return sorted(backlinks)

def build_graph(notes):
    """Build graph data for D3: {nodes: [{id, group}], links: [{source, target}]}."""
    nodes = []
    node_index = {}
    edges = []
    
    for name, data in notes.items():
        if name not in node_index:
            node_index[name] = len(nodes)
            nodes.append({'id': name, 'group': 1})
        
        for link in data['links']:
            if link in notes:  # only link to existing notes
                if link not in node_index:
                    node_index[link] = len(nodes)
                    nodes.append({'id': link, 'group': 2 if link not in data['links'] else 1})
                edges.append({'source': node_index[name], 'target': node_index[link]})
    
    return {'nodes': nodes, 'links': edges}

def render_markdown(filepath, current_note=None):
    """Read and render a markdown file with wikilink conversion."""
    with open(filepath, 'r') as f:
        content = f.read()
    html = md.convert(content)
    
    def replace_link(m):
        name = m.group(1)
        if '|' in name:
            target, display = name.split('|', 1)
        else:
            target = display = name
        if current_note and target == current_note:
            return f'<strong class="self-link">{display}</strong>'
        safe = target.replace(' ', '%20')
        return f'<a href="/note/{safe}" class="wikilink" data-note="{target}">{display}</a>'
    
    return re.sub(r'\[\[([^\]]+)\]\]', replace_link, html)

# ── API Routes ───────────────────────────────────────────────
@app.route('/api/notes')
@requires_auth
def api_notes():
    return jsonify(scan_notes())

@app.route('/api/tree')
@requires_auth
def api_tree():
    return jsonify(build_file_tree())

@app.route('/api/graph')
@requires_auth
def api_graph():
    notes = scan_notes()
    return jsonify(build_graph(notes))

@app.route('/api/backlinks/<path:name>')
@requires_auth
def api_backlinks(name):
    name = name.replace('%20', ' ')
    notes = scan_notes()
    return jsonify(build_backlinks(notes, name))

@app.route('/api/raw/<path:name>')
@requires_auth
def api_raw(name):
    """Return raw markdown content of a note."""
    name = name.replace('%20', ' ')
    notes = scan_notes()
    for note_name, data in notes.items():
        if note_name == name or data['path'] == name or data['path'] == f"{name}.md":
            filepath = Path(VAULT_PATH) / data['path']
            if filepath.exists():
                return Response(filepath.read_text(), mimetype='text/plain')
    return 'Note not found', 404

@app.route('/api/save/<path:name>', methods=['POST'])
@requires_auth
def api_save(name):
    """Save edited markdown content back to a note."""
    name = name.replace('%20', ' ')
    notes = scan_notes()
    
    filepath = None
    for note_name, data in notes.items():
        if note_name == name or data['path'] == name or data['path'] == f"{name}.md":
            filepath = Path(VAULT_PATH) / data['path']
            break
    
    if filepath is None:
        return jsonify({'error': 'Note not found'}), 404
    
    content = request.get_json().get('content', '')
    filepath.write_text(content)
    
    # Log the edit so Aegis knows
    edit_log = Path(os.path.expanduser("~/.hermes/data/vault_edits.jsonl"))
    edit_log.parent.mkdir(parents=True, exist_ok=True)
    with open(edit_log, 'a') as f:
        f.write(json.dumps({
            'note': name,
            'time': datetime.utcnow().isoformat(),
            'size': len(content)
        }) + '\n')
    
    return jsonify({'status': 'saved', 'note': name})
@app.route('/')
@requires_auth
def index():
    notes = scan_notes()
    # Default to Home if it exists
    home = Path(VAULT_PATH) / "Home.md"
    if home.exists():
        content = render_markdown(str(home), "Home")
        current = "Home"
    else:
        content = "<p><em>No Home.md found.</em></p>"
        current = None
    return render(current, content, notes)

@app.route('/note/<path:name>')
@requires_auth
def view_note(name):
    name = name.replace('%20', ' ')
    notes = scan_notes()
    
    # Find the note file
    filepath = None
    for note_name, data in notes.items():
        if note_name == name or data['path'] == name or data['path'] == f"{name}.md":
            filepath = Path(VAULT_PATH) / data['path']
            current = note_name
            break
    
    if filepath is None or not filepath.exists():
        return f"<h1>Note not found</h1><p>{name}</p><a href='/'>← Back</a>", 404
    
    content = render_markdown(str(filepath), current)
    return render(current, content, notes)

SNIPPET_CONTEXT = 60   # chars of context either side of a match
SNIPPETS_PER_NOTE = 3  # max snippets shown per result

def search_notes(notes, query):
    """Return [{name, path, score, match_types, snippets}] for a query.

    Searches note names, tags, and content. Snippets are HTML-escaped and
    have match text wrapped in <mark>. Case-insensitive substring match —
    deliberately simple, same as the rest of the data layer.
    """
    q = query.lower()
    results = []
    for name, data in notes.items():
        path = Path(VAULT_PATH) / data['path']
        try:
            text = path.read_text()
        except OSError:
            continue

        match_types = []
        snippets = []
        score = 0
        if q in name.lower():
            match_types.append('name')
            score += 10
        for tag in data.get('tags', []):
            if q in tag.lower():
                match_types.append('tag')
                score += 5
                break
        if q in text.lower():
            match_types.append('content')
            content_count = text.lower().count(q)
            score += content_count
            # Collect snippets around each occurrence (max SNIPPETS_PER_NOTE)
            for m in re.finditer(re.escape(query), text, flags=re.IGNORECASE):
                if len(snippets) >= SNIPPETS_PER_NOTE:
                    break
                start = max(0, m.start() - SNIPPET_CONTEXT)
                end = min(len(text), m.end() + SNIPPET_CONTEXT)
                raw = text[start:end]
                snippet = html.escape(raw)
                # Escape the query too, then highlight it inside the escaped snippet
                snippet = re.sub(
                    f'({re.escape(html.escape(query))})',
                    r'<mark>\1</mark>', snippet, flags=re.IGNORECASE)
                if start > 0:
                    snippet = '…' + snippet
                if end < len(text):
                    snippet = snippet + '…'
                # Newlines read better in a <pre>-style block than mid-line gaps
                snippet = snippet.replace('\n', ' ')
                snippets.append(snippet)
            if content_count > SNIPPETS_PER_NOTE:
                snippets.append(f'<em>…{content_count - SNIPPETS_PER_NOTE} more match(es) in this note</em>')

        if not match_types:
            continue

        if 'name' in match_types:
            snippet_text = f'Note title matches "<strong>{html.escape(query)}</strong>".'
        elif 'tag' in match_types and not snippets:
            matched = [t for t in data.get('tags', []) if q in t.lower()]
            snippet_text = f'Tagged <strong>#{html.escape(", #".join(matched))}</strong>.'
        else:
            snippet_text = ''
        if snippet_text:
            snippets.insert(0, snippet_text)

        results.append({
            'name': name,
            'path': data['path'],
            'score': score,
            'match_types': match_types,
            'count': text.lower().count(q),
            'snippets': snippets,
        })

    # Best matches first: name matches > tag > content frequency
    results.sort(key=lambda r: r['score'], reverse=True)
    return results

@app.route('/api/search')
@requires_auth
def api_search():
    """JSON search endpoint — drives the live search on /search."""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])
    return jsonify(search_notes(scan_notes(), query))

@app.route('/search')
@requires_auth
def search():
    query = request.args.get('q', '').strip()
    notes = scan_notes()
    if not query:
        return redirect(url_for('index'))

    results = search_notes(notes, query)

    q_esc = html.escape(query)
    content_html = '<div class="search-results">'
    if results:
        content_html += f'<p class="search-count">{len(results)} result(s) for "<strong>{q_esc}</strong>"</p>'
        for r in results:
            url = '/note/' + quote(r['name'])
            name_esc = html.escape(r['name'])
            badges = ''
            for mt in r['match_types']:
                badges += f'<span class="search-badge">{mt}</span>'
            snippet_html = ''
            for s in r['snippets']:
                snippet_html += f'<pre>{s}</pre>'
            content_html += (
                f'<div class="search-result"><h3><a href="{url}">{name_esc}</a></h3>'
                f'{badges}{snippet_html}</div>'
            )
    else:
        content_html += f'<p class="search-count">No results for "<strong>{q_esc}</strong>".</p>'
    content_html += '</div>'

    return render(None, content_html, notes, query=query)

def render(current, content, notes, query=""):
    """Render the full page template."""
    notes_list = [{'name': n, 'path': d['path']} for n, d in sorted(notes.items())]
    query_esc = html.escape(query)
    
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{current + " — " if current else ""}VaultView</title>
<style>
:root {{
  --bg: #0d1117; --sidebar-bg: #161b22; --text: #c9d1d9; --link: #58a6ff;
  --border: #30363d; --accent: #7c3aed; --hover: #1c2128; --code-bg: #1a1a2e;
  --heading: #f0f6fc; --wikilink: #7c3aed; --gold: #e8a030;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg); color: var(--text); display: flex; min-height: 100vh;
}}
/* ── Left Sidebar: File Tree ── */
.sidebar {{
  width: 260px; min-width: 260px; background: var(--sidebar-bg);
  border-right: 1px solid var(--border); display: flex; flex-direction: column;
  position: fixed; top: 0; left: 0; height: 100vh; overflow: hidden; z-index: 10;
}}
.sidebar-header {{
  padding: 16px; border-bottom: 1px solid var(--border);
}}
.sidebar-header h2 {{ font-size: 16px; color: var(--heading); }}
.search-form {{ display: flex; gap: 4px; margin-top: 8px; }}
.search-form input {{
  flex: 1; padding: 6px 10px; background: var(--bg); border: 1px solid var(--border);
  border-radius: 6px; color: var(--text); font-size: 12px; outline: none;
}}
.search-form input:focus {{ border-color: var(--accent); }}
.search-form button {{
  padding: 6px 10px; background: var(--accent); color: #fff; border: none;
  border-radius: 6px; cursor: pointer; font-size: 12px;
}}
.file-tree {{
  flex: 1; overflow-y: auto; padding: 8px;
}}
.file-tree .folder {{ margin-left: 0; }}
.file-tree .folder-name {{
  font-size: 12px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px;
  padding: 4px 8px; cursor: pointer; border-radius: 4px; user-select: none;
}}
.file-tree .folder-name:hover {{ background: var(--hover); }}
.file-tree .folder-children {{ margin-left: 12px; }}
.file-tree .folder-children.collapsed {{ display: none; }}
.file-tree a {{
  display: block; padding: 4px 8px; color: var(--text); text-decoration: none;
  border-radius: 4px; font-size: 13px;
}}
.file-tree a:hover {{ background: var(--hover); }}
.file-tree a.active {{ background: var(--accent); color: #fff; font-weight: 600; }}
.sidebar-footer {{
  padding: 12px 16px; border-top: 1px solid var(--border);
}}
.logout-link {{
  display: block; padding: 6px 10px; color: #8b949e; text-decoration: none;
  border-radius: 6px; font-size: 13px;
}}
.logout-link:hover {{ background: var(--hover); color: #f85149; }}
/* ── Center: Content ── */
.content {{
  margin-left: 260px; padding: 32px 48px; max-width: 900px;}}
.content h1 {{ font-size: 28px; color: var(--heading); margin-bottom: 16px; }}
.content h2 {{ font-size: 20px; color: var(--heading); margin: 28px 0 10px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }}
.content h3 {{ font-size: 16px; color: var(--heading); margin: 20px 0 8px; }}
.content p {{ margin: 0 0 12px; line-height: 1.6; }}
.content a {{ color: var(--link); text-decoration: none; }}
.content a:hover {{ text-decoration: underline; }}
.content .wikilink {{ color: var(--wikilink); font-weight: 500; }}
.content .wikilink:hover {{ text-decoration: underline; }}
.content .self-link {{ color: var(--gold); }}
.content ul, .content ol {{ margin: 0 0 12px 20px; }}
.content li {{ margin-bottom: 3px; }}
.content code {{
  background: var(--code-bg); padding: 2px 6px; border-radius: 4px; font-size: 13px;
}}
.content pre {{
  background: var(--code-bg); padding: 14px; border-radius: 8px; overflow-x: auto;
  margin: 0 0 14px; border: 1px solid var(--border); font-size: 13px;
}}
.content pre code {{ background: none; padding: 0; }}
.content blockquote {{
  border-left: 3px solid var(--accent); padding: 6px 14px; margin: 0 0 12px;
  color: #8b949e; background: #7c3aed0a; border-radius: 0 6px 6px 0;
}}
.content table {{ border-collapse: collapse; width: 100%; margin-bottom: 14px; }}
.content th, .content td {{ padding: 6px 10px; border: 1px solid var(--border); text-align: left; }}
.content th {{ background: var(--sidebar-bg); }}
.content input[type="checkbox"] {{ margin-right: 6px; }}
/* ── Right Sidebar: Backlinks ── */
.panel {{
  width: 220px; min-width: 220px; background: var(--sidebar-bg);
  border-left: 1px solid var(--border); padding: 16px;
  position: fixed; top: 0; right: 0; height: 100vh; overflow-y: auto; z-index: 5;
}}
.panel h3 {{
  font-size: 14px; color: var(--heading); margin-bottom: 12px;
}}
.backlink-item {{
  display: block; padding: 4px 8px; color: var(--text); text-decoration: none;
  border-radius: 4px; font-size: 13px; margin-bottom: 2px;
}}
.backlink-item:hover {{ background: var(--hover); }}
.backlink-item::before {{ content: "← "; color: #8b949e; }}
.panel-empty {{ font-size: 12px; color: #8b949e; }}
/* ── Edit mode ── */
.edit-bar {{
  display: flex; gap: 8px; margin-bottom: 16px;
}}
.edit-btn, .save-btn, .cancel-btn {{
  padding: 6px 14px; border-radius: 6px; font-size: 13px; font-weight: 600;
  cursor: pointer; border: 1px solid var(--border);
}}
.edit-btn {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
.save-btn {{ background: #238636; color: #fff; border-color: #238636; display: none; }}
.cancel-btn {{ background: transparent; color: var(--text); display: none; }}
.edit-btn:hover, .save-btn:hover {{ opacity: 0.85; }}
.cancel-btn:hover {{ background: var(--hover); }}
.edit-textarea {{
  display: none; width: 100%; min-height: 500px; background: #0d1117;
  color: #e6edf3; border: 1px solid var(--border); border-radius: 8px;
  padding: 20px; font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
  font-size: 14px; line-height: 1.7; resize: vertical; outline: none;
  tab-size: 4;
}}
.edit-textarea:focus {{ border-color: var(--accent); box-shadow: 0 0 0 3px #7c3aed22; }}
.edit-textarea.active {{ display: block; }}
.edit-mode .save-btn, .edit-mode .cancel-btn {{ display: inline-block; }}
.edit-mode .edit-btn {{ display: none; }}
.edit-mode .rendered-content {{ display: none; }}
/* Full-screen overlay editing */
.edit-overlay {{
  display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  background: #0d1117; z-index: 500; flex-direction: column;
}}
.edit-overlay.show {{ display: flex; }}
.edit-overlay-toolbar {{
  display: flex; align-items: center; gap: 12px; padding: 12px 20px;
  background: #161b22; border-bottom: 1px solid var(--border);
}}
.edit-overlay-toolbar span {{ color: var(--heading); font-weight: 600; font-size: 14px; }}
.edit-overlay-toolbar .spacer {{ flex: 1; }}
.edit-overlay-toolbar button {{
  padding: 6px 16px; border-radius: 6px; font-size: 13px; font-weight: 600;
  cursor: pointer; border: 1px solid var(--border);
}}
.edit-overlay-save {{ background: #238636; color: #fff; border-color: #238636; }}
.edit-overlay-cancel {{ background: transparent; color: var(--text); }}
.edit-overlay-save:hover {{ opacity: 0.85; }}
.edit-overlay-cancel:hover {{ background: var(--hover); }}
.edit-overlay textarea {{
  flex: 1; width: 100%; background: #0d1117; color: #e6edf3;
  border: none; padding: 24px 32px; font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 15px; line-height: 1.8; resize: none; outline: none;
  tab-size: 4;
}}
.edit-overlay textarea:focus {{ border: none; outline: none; }}
.edit-overlay-hint {{
  padding: 8px 20px; font-size: 11px; color: #8b949e;
  border-top: 1px solid var(--border);
}}
.saved-toast {{
  position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
  background: #238636; color: #fff; padding: 10px 20px; border-radius: 8px;
  font-size: 14px; z-index: 300; opacity: 0; transition: opacity 0.3s;
}}
.saved-toast.show {{ opacity: 1; }}
/* ── Search ── */
.search-results p {{ margin-bottom: 16px; color: #8b949e; }}
.search-count {{ font-size: 13px; margin-bottom: 16px; color: #8b949e; }}
.search-badge {{
  display: inline-block; font-size: 10px; text-transform: uppercase; letter-spacing: .5px;
  padding: 1px 7px; border-radius: 10px; margin: 0 4px 6px 0;
  background: #7c3aed33; color: #a78bfa; border: 1px solid #7c3aed66;
}}
.search-result {{
  background: var(--sidebar-bg); border: 1px solid var(--border);
  border-radius: 8px; padding: 14px; margin-bottom: 10px;
}}
.search-result h3 {{ margin: 0 0 6px; font-size: 15px; }}
.search-result pre {{ white-space: pre-wrap; font-size: 12px; color: #8b949e; background: none; padding: 0; border: none; margin: 0; }}
mark {{ background: #bb800944; color: inherit; padding: 1px 3px; border-radius: 3px; }}
/* ── Graph ── */
.graph-toggle {{
  position: fixed; bottom: 20px; right: 20px; z-index: 100;
  width: 44px; height: 44px; border-radius: 50%; background: var(--accent);
  border: none; color: #fff; font-size: 20px; cursor: pointer;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
}}
.graph-overlay {{
  display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  background: rgba(0,0,0,0.9); z-index: 200; flex-direction: column;
}}
.graph-overlay.show {{ display: flex; }}
.graph-toolbar {{
  display: flex; align-items: center; gap: 16px; padding: 12px 20px;
  background: var(--sidebar-bg); border-bottom: 1px solid var(--border);
}}
.graph-title {{ color: var(--heading); font-weight: 600; font-size: 14px; }}
.graph-legend {{ font-size: 11px; color: #8b949e; margin-left: auto; }}
.graph-fit-btn {{
  padding: 4px 12px; background: var(--accent); color: #fff; border: none;
  border-radius: 4px; cursor: pointer; font-size: 12px;
}}
.graph-close-btn {{
  background: none; border: none; color: #fff; font-size: 22px; cursor: pointer;
  padding: 0 4px;
}}
.graph-overlay svg {{
  flex: 1; width: 100%; cursor: grab;
}}
.graph-overlay svg:active {{ cursor: grabbing; }}
.graph-hint {{
  padding: 8px; text-align: center; font-size: 11px; color: #8b949e;
  border-top: 1px solid var(--border);
}}
.menu-toggle {{
  display: none; position: fixed; top: 12px; left: 12px; z-index: 40;
  width: 36px; height: 36px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--sidebar-bg); color: var(--text); font-size: 16px;
  align-items: center; justify-content: center; cursor: pointer;
  transition: left .25s ease;
}}

/* ── Mobile (<768px): stack vertically, sidebar becomes a top drawer ── */
@media (max-width: 768px) {{
  .sidebar {{
    position: fixed; top: 0; left: -280px; width: 260px;
    transition: left .25s ease; z-index: 30; height: 100vh;
  }}
  .sidebar.open {{ left: 0; box-shadow: 0 0 0 100vmax rgba(0,0,0,.5); }}
  .content {{ margin-left: 0; padding: 64px 16px 32px; max-width: none; }}
  .panel {{ display: none; }}
  .graph-toggle {{ bottom: 16px; right: 16px; }}
  .menu-toggle {{ display: flex; }}
  body.menu-open .menu-toggle {{ left: 268px; }}
}}
</style>
</head>
<body>

<!-- Mobile menu button -->
<button class="menu-toggle" id="menuToggle" aria-label="Menu">☰</button>

<!-- Left: File Tree -->
<aside class="sidebar">
  <div class="sidebar-header">
    <h2>📓 Vault</h2>
    <form class="search-form" action="/search" method="get">
      <input type="text" name="q" id="searchInput" placeholder="Search… ('/' to focus)" value="{query_esc}">
      <button>🔍</button>
    </form>
  </div>
  <nav class="file-tree" id="fileTree">
    {_render_file_tree(build_file_tree(), '')}
  </nav>
  <div class="sidebar-footer">
    <a href="/logout" class="logout-link">🔒 Lock vault</a>
  </div>
</aside>

<!-- Center: Content -->
<main class="content">
  <div class="edit-bar">
    <button class="edit-btn" onclick="startEdit()">✏️ Edit</button>
  </div>
  <div class="rendered-content">
  {content}
  </div>
</main>

<!-- Full-screen Edit Overlay -->
<div class="edit-overlay" id="editOverlay">
  <div class="edit-overlay-toolbar">
    <span>✏️ Editing: {current or 'Note'}</span>
    <span class="spacer"></span>
    <button class="edit-overlay-cancel" onclick="cancelEdit()">Cancel</button>
    <button class="edit-overlay-save" onclick="saveEdit()">💾 Save</button>
  </div>
  <textarea id="editTextarea" placeholder="Write markdown here..."></textarea>
  <div class="edit-overlay-hint">🖱️ Markdown — [[wikilinks]] supported · Ctrl+S to save · Esc to cancel</div>
</div>

<!-- Right: Backlinks -->
<aside class="panel" id="backlinksPanel">
  <h3>🔗 Links to this note</h3>
  <div id="backlinksList"><span class="panel-empty">Loading…</span></div>
</aside>

<!-- Graph button -->
<button class="graph-toggle" id="graphToggle" title="Graph View">🕸️</button>

<!-- Graph overlay -->
<div class="graph-overlay" id="graphOverlay">
  <div class="graph-toolbar">
    <span class="graph-title">🕸️ Note Graph</span>
    <span class="graph-legend"><span style="color:#7c3aed">●</span> has links <span style="color:#58a6ff">●</span> orphan</span>
    <button class="graph-fit-btn" id="graphFit">Fit</button>
    <button class="graph-close-btn" id="graphClose">&times;</button>
  </div>
  <svg id="graphSvg"></svg>
  <div class="graph-hint">🖱️ Scroll to zoom · Drag to pan · Click node to open</div>
</div>

<!-- Mermaid JS for diagram rendering -->
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script>
mermaid.initialize({{ startOnLoad: true, theme: 'dark', themeVariables: {{
  primaryColor: '#7c3aed', primaryTextColor: '#c9d1d9',
  lineColor: '#58a6ff', secondaryColor: '#1a1a2e',
  tertiaryColor: '#161b22', background: '#0d1117',
  mainBkg: '#161b22', nodeBorder: '#30363d',
  clusterBkg: '#161b22', titleColor: '#f0f6fc',
  edgeLabelBackground: '#161b22'
}} }});
</script>

<script>
// File tree toggle
document.querySelectorAll('.folder-name').forEach(el => {{
  el.addEventListener('click', () => {{
    const children = el.nextElementSibling;
    if (children) children.classList.toggle('collapsed');
  }});
}});

// Mobile sidebar drawer
const menuToggle = document.getElementById('menuToggle');
if (menuToggle) {{
  menuToggle.addEventListener('click', () => {{
    const sidebar = document.querySelector('.sidebar');
    const open = sidebar.classList.toggle('open');
    document.body.classList.toggle('menu-open', open);
    menuToggle.textContent = open ? '✕' : '☰';
  }});
  // Close drawer when a note/link is chosen
  sidebar = document.querySelector('.sidebar');
  sidebar.addEventListener('click', e => {{
    if (e.target.closest('a')) {{
      sidebar.classList.remove('open');
      document.body.classList.remove('menu-open');
      menuToggle.textContent = '☰';
    }}
  }});
}}

// Load backlinks
const currentNote = "{current or ''}";
if (currentNote) {{
  fetch('/api/backlinks/' + encodeURIComponent(currentNote))
    .then(r => r.json())
    .then(links => {{
      const container = document.getElementById('backlinksList');
      if (links.length === 0) {{
        document.getElementById('backlinksPanel').style.display = 'none';
      }} else {{
        document.getElementById('backlinksPanel').style.display = '';
        container.innerHTML = links.map(l =>
          `<a class="backlink-item" href="/note/${{encodeURIComponent(l)}}">${{l}}</a>`
        ).join('');
      }}
    }});
}}

// ── Live search (debounced /api/search fetch, only on the /search page) ──
const searchInput = document.getElementById('searchInput');
const isSearchPage = window.location.pathname === '/search';
let searchTimer = null;

if (isSearchPage && searchInput) {{
  searchInput.addEventListener('input', () => {{
    clearTimeout(searchTimer);
    const q = searchInput.value.trim();
    if (!q) {{
      document.querySelector('.search-results').innerHTML =
        '<p class="search-count">Type to search the vault…</p>';
      return;
    }}
    searchTimer = setTimeout(() => liveSearch(q), 250);
  }});
}}

function liveSearch(q) {{
  fetch('/api/search?q=' + encodeURIComponent(q))
    .then(r => r.json())
    .then(results => {{
      const box = document.querySelector('.search-results');
      if (!box) return;
      if (results.length === 0) {{
        box.innerHTML = `<p class="search-count">No results for "<strong>${{esc(q)}}</strong>".</p>`;
        return;
      }}
      let html = `<p class="search-count">${{results.length}} result(s) for "<strong>${{esc(q)}}</strong>"</p>`;
      results.forEach(r => {{
        const badges = r.match_types.map(mt => `<span class="search-badge">${{mt}}</span>`).join('');
        const snips = r.snippets.map(s => `<pre>${{s}}</pre>`).join('');
        html += `<div class="search-result"><h3><a href="/note/${{encodeURIComponent(r.name)}}">${{esc(r.name)}}</a></h3>${{badges}}${{snips}}</div>`;
      }});
      box.innerHTML = html;
    }});
}}

function esc(s) {{
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}}

// '/' focuses the search box (unless already typing in an input)
window.addEventListener('keydown', function(e) {{
  if (e.key !== '/' || searchInput === null) return;
  const t = e.target;
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')) return;
  e.preventDefault();
  searchInput.focus();
  searchInput.select();
}});

// Graph view with zoom + pan
let graphData = null;
let graphTransform = {{ x: 0, y: 0, scale: 1 }};
let graphDragging = false;
let graphDragStart = {{ x: 0, y: 0 }};
let graphTransformStart = {{ x: 0, y: 0 }};

function showGraph() {{
  document.getElementById('graphOverlay').classList.add('show');
  if (!graphData) {{
    fetch('/api/graph')
      .then(r => r.json())
      .then(data => {{
        graphData = data;
        renderGraph(data);
      }});
  }} else {{
    renderGraph(graphData);
  }}
}}

function hideGraph() {{
  document.getElementById('graphOverlay').classList.remove('show');
}}

function renderGraph(data) {{
  const svg = document.getElementById('graphSvg');
  const width = svg.clientWidth || window.innerWidth;
  const height = svg.clientHeight || window.innerHeight - 60;

  svg.innerHTML = '';
  svg.setAttribute('viewBox', `0 0 ${{width}} ${{height}}`);

  const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  g.setAttribute('id', 'graphGroup');
  svg.appendChild(g);

  graphTransform = {{ x: 0, y: 0, scale: 1 }};
  applyTransform(g);

  const nodes = data.nodes;
  const links = data.links;
  const cx = width / 2, cy = height / 2;
  const radius = Math.min(width, height) * 0.35;

  // Find hub node (most links) and spoke nodes
  const linkCounts = {{}};
  links.forEach(l => {{
    linkCounts[l.source] = (linkCounts[l.source] || 0) + 1;
    linkCounts[l.target] = (linkCounts[l.target] || 0) + 1;
  }});
  
  // Hub = node with most connections, or Home if it exists
  let hubIndex = 0;
  let maxLinks = 0;
  nodes.forEach((n, i) => {{
    const count = linkCounts[i] || 0;
    if (count > maxLinks || (count === maxLinks && n.id === 'Home')) {{
      maxLinks = count;
      hubIndex = i;
    }}
  }});

  // Position hub at center
  const positions = nodes.map((n, i) => {{
    if (i === hubIndex) return {{ x: cx, y: cy }};
    // Spokes arranged in circle
    const spokeNodes = nodes.filter((_, j) => j !== hubIndex);
    const spokeIdx = spokeNodes.findIndex(sn => sn.id === n.id);
    const angle = (spokeIdx / spokeNodes.length) * 2 * Math.PI - Math.PI / 2;
    return {{
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
    }};
  }});

  // Links
  links.forEach(l => {{
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', positions[l.source].x);
    line.setAttribute('y1', positions[l.source].y);
    line.setAttribute('x2', positions[l.target].x);
    line.setAttribute('y2', positions[l.target].y);
    line.setAttribute('stroke', '#30363d');
    line.setAttribute('stroke-width', l.source === hubIndex || l.target === hubIndex ? '2' : '1');
    g.appendChild(line);
  }});

  // Nodes
  nodes.forEach((n, i) => {{
    const isHub = i === hubIndex;
    const pos = positions[i];
    const ng = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    ng.style.cursor = 'pointer';
    ng.setAttribute('transform', `translate(${{pos.x}},${{pos.y}})`);
    ng.onclick = () => {{ window.location = '/note/' + encodeURIComponent(n.id); }};

    const r = isHub ? 18 : 11;
    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('r', r);
    circle.setAttribute('fill', isHub ? '#e8a030' : '#7c3aed');
    circle.setAttribute('stroke', isHub ? '#ffd700' : '#a78bfa');
    circle.setAttribute('stroke-width', isHub ? '3' : '2');
    ng.appendChild(circle);

    // Hub gets large bold label, spokes get smaller
    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('fill', isHub ? '#ffd700' : '#e8e8f0');
    text.setAttribute('font-size', isHub ? '16' : '12');
    text.setAttribute('font-weight', isHub ? '700' : '500');
    text.setAttribute('text-anchor', isHub ? 'middle' : 'start');
    text.setAttribute('dy', isHub ? r + 20 : r + 16);
    if (!isHub) text.setAttribute('dx', 0);
    text.textContent = n.id;
    ng.appendChild(text);

    g.appendChild(ng);
  }});

  // Zoom + pan (same as before)
  svg.onwheel = function(e) {{
    if (!document.getElementById('graphOverlay').classList.contains('show')) return;
    e.preventDefault();
    const scaleBy = e.deltaY < 0 ? 1.1 : 0.9;
    const newScale = Math.max(0.1, Math.min(5, graphTransform.scale * scaleBy));
    const rect = svg.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    graphTransform.x = mx - (mx - graphTransform.x) * (newScale / graphTransform.scale);
    graphTransform.y = my - (my - graphTransform.y) * (newScale / graphTransform.scale);
    graphTransform.scale = newScale;
    applyTransform(g);
  }};
  svg.onmousedown = function(e) {{
    if (e.target.tagName === 'circle' || e.target.tagName === 'text') return;
    graphDragging = true;
    graphDragStart = {{ x: e.clientX, y: e.clientY }};
    graphTransformStart = {{ ...graphTransform }};
  }};
  window.addEventListener('mousemove', function(e) {{
    if (!graphDragging) return;
    graphTransform.x = graphTransformStart.x + (e.clientX - graphDragStart.x);
    graphTransform.y = graphTransformStart.y + (e.clientY - graphDragStart.y);
    applyTransform(g);
  }});
  window.addEventListener('mouseup', () => {{ graphDragging = false; }});
  document.getElementById('graphFit').onclick = function() {{
    graphTransform = {{ x: 0, y: 0, scale: 1 }};
    applyTransform(g);
  }};
}}

function applyTransform(g) {{
  g.setAttribute('transform',
    `translate(${{graphTransform.x}},${{graphTransform.y}}) scale(${{graphTransform.scale}})`);
}}

document.getElementById('graphToggle').addEventListener('click', showGraph);
document.getElementById('graphClose').addEventListener('click', hideGraph);
// ESC to close graph
window.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape' && document.getElementById('graphOverlay').classList.contains('show')) {{
    hideGraph();
  }}
}});

// ── Edit mode (full-screen overlay) ──
let rawMarkdown = '';
let currentNoteName = "{current or ''}";

function startEdit() {{
  const overlay = document.getElementById('editOverlay');
  overlay.classList.add('show');
  document.body.style.overflow = 'hidden';
  const ta = document.getElementById('editTextarea');
  
  if (!rawMarkdown && currentNoteName) {{
    fetch('/api/raw/' + encodeURIComponent(currentNoteName))
      .then(r => r.text())
      .then(text => {{
        rawMarkdown = text;
        ta.value = rawMarkdown;
        ta.focus();
      }});
  }} else {{
    ta.value = rawMarkdown;
    ta.focus();
  }}
}}

function saveEdit() {{
  const ta = document.getElementById('editTextarea');
  const newContent = ta.value;
  fetch('/api/save/' + encodeURIComponent(currentNoteName), {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{content: newContent}})
  }})
  .then(r => r.json())
  .then(data => {{
    if (data.status === 'saved') {{
      rawMarkdown = newContent;
      document.getElementById('editOverlay').classList.remove('show');
      document.body.style.overflow = '';
      showToast('✅ Saved!');
      setTimeout(() => location.reload(), 400);
    }}
  }});
}}

function cancelEdit() {{
  document.getElementById('editOverlay').classList.remove('show');
  document.body.style.overflow = '';
}}

// Ctrl+S to save, Esc to cancel
document.addEventListener('keydown', function(e) {{
  const overlay = document.getElementById('editOverlay');
  if (!overlay.classList.contains('show')) return;
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {{
    e.preventDefault();
    saveEdit();
  }}
  if (e.key === 'Escape') {{
    cancelEdit();
  }}
}});

function showToast(msg) {{
  let toast = document.getElementById('savedToast');
  if (!toast) {{
    toast = document.createElement('div');
    toast.id = 'savedToast';
    toast.className = 'saved-toast';
    document.body.appendChild(toast);
  }}
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2000);
}}
</script>
</body>
</html>'''

def _render_file_tree(tree, indent):
    """Recursively render a file tree as HTML."""
    html = ''
    for key, value in sorted(tree.items()):
        if isinstance(value, dict):
            # Folder
            folder_id = f"folder-{indent}-{key}".replace(' ', '-')
            html += f'<div class="folder"><div class="folder-name" data-folder="{folder_id}">📁 {key}</div>'
            html += f'<div class="folder-children" id="{folder_id}">'
            html += _render_file_tree(value, f"{indent}-{key}")
            html += '</div></div>'
        else:
            # Note file
            name = value
            active = ' class="active"' if name == 'Home' and indent == '' else ''
            html += f'<a href="/note/{name.replace(" ", "%20")}"{active}>📄 {name}</a>'
    return html

if __name__ == '__main__':
    print(f"📓 VaultView starting on port {PORT}")
    print(f"   Vault: {VAULT_PATH}")
    app.run(host='0.0.0.0', port=PORT, debug=False)
