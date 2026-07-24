# VaultView

A lightweight, self-hosted web viewer for [Obsidian](https://obsidian.md) vaults.

Read your notes from any browser — nested file tree, [[wikilink]] navigation, backlinks panel, full-text search, and an interactive graph view. One Python file, zero build step.

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)

---

## Features

- 📁 **Nested file tree** — folders expand/collapse, reflects vault structure
- 🔗 **[[Wikilink]] support** — clickable internal links, self-links highlighted
- 🔙 **Backlinks panel** — see which notes link to the current one (auto-hides when empty)
- 🔍 **Full-text search** — with highlighted results across all notes
- 🕸️ **Interactive graph view** — hub-and-spoke layout, zoom and pan, click to navigate
- 🌙 **Dark theme** — CSS custom properties, easy on the eyes
- 📱 **Mobile-friendly** — responsive layout, works on phones
- 🔒 **Basic auth** — password protected
- 🐍 **Single file** — one `app.py`, vanilla JS, no bundler

## Screenshots

*Coming soon — PRs welcome!*

## Quick Start

```bash
git clone https://github.com/bmvanwyk/VaultView.git
cd VaultView
pip install -r requirements.txt

# Point it at any Obsidian vault
OBSIDIAN_VAULT_PATH=~/my-vault python3 app.py
```

Open **http://localhost:9120** — log in with default credentials.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OBSIDIAN_VAULT_PATH` | `~/Documents/Obsidian Vault` | Path to your vault folder |
| `VAULT_VIEWER_PORT` | `9120` | HTTP port |
| `VAULT_VIEWER_USER` | `hermes` | Basic auth username |
| `VAULT_VIEWER_PASS` | `hermes` | Basic auth password |

## Systemd Service

```bash
# Copy the service file
sudo cp vaultview.service /etc/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now vaultview
```

## Architecture

See [docs/architecture.md](docs/architecture.md) for design decisions, component diagrams, and tradeoffs.

## Development

See [AGENTS.md](AGENTS.md) for contributor guidance, testing instructions, and design rules.

## License

MIT — see [LICENSE](LICENSE).

## Related

- [Obsidian](https://obsidian.md) — the desktop app this viewer complements
- [Hermes Agent](https://github.com/NousResearch/hermes-agent) — the AI agent that manages this vault
