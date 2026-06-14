# servicenow-portal-toolkit

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org)
[![MCP](https://img.shields.io/badge/MCP-compatible-green)](https://modelcontextprotocol.io)

An **MCP server** that gives Claude Desktop four powerful tools for managing **ServiceNow Service Portal** — branding, WCAG auditing, and usage analytics — without leaving the chat window.

---

## Tools

| Tool | What it does |
|---|---|
| `list_portals` | Fetch all portals from `sp_portal` — name, URL suffix, theme, status |
| `apply_branding` | Scrape a website URL *or* accept manual hex/font values → push to `sp_theme` with WCAG AA check + before-snapshot |
| `branding_score` | Read the current theme, score contrast ratios + CSS vars + font consistency out of 100 |
| `portal_analytics` | Pull page views, search terms, zero-result searches, and mobile/desktop ratio from `pa_page_view` and `sp_log` |

---

## Install

```bash
pip install servicenow-portal-toolkit
```

## Setup

Run the one-time wizard — it saves credentials and patches your Claude Desktop config automatically:

```bash
servicenow-portal-toolkit setup
```

You will be prompted for:

- **Instance name** — e.g. `mycompany` (not the full URL)
- **Username** — e.g. `admin`
- **Password**

Credentials are written to `~/.servicenow-portal-toolkit/.env` (mode 600).  
The wizard auto-detects your Claude Desktop config on Windows, macOS, and Linux and injects the `mcpServers` entry.

**Restart Claude Desktop** after setup.

---

### Manual Claude Desktop Config

If auto-detection fails, add this to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "servicenow-portal-toolkit": {
      "command": "servicenow-portal-toolkit",
      "args": ["serve"]
    }
  }
}
```

Config file locations:

| Platform | Path |
|---|---|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

---

### Verify Connectivity

```bash
servicenow-portal-toolkit check
```

---

## Example Prompts

Try these in Claude Desktop after setup:

**1. Discover your portals**
> "List all active Service Portals in my ServiceNow instance."

**2. Rebrand from a website**
> "Apply the branding from https://www.mybrand.com to the 'sp' portal."

**3. Audit current branding**
> "Give me a branding score for the 'customer_portal' portal and tell me what to fix."

**4. Analyze portal usage**
> "Show me the top search terms and content gaps for the 'sp' portal, then suggest UX improvements."

---

## Required ServiceNow Permissions

The configured user needs **read** access to:
- `sp_portal` — list portals
- `sp_theme` — read theme for scoring / analytics
- `pa_page_view` — page view analytics
- `sp_log` — search log analytics

And **write** access to:
- `sp_theme` — apply branding changes

---

## Architecture

```
servicenow-portal-toolkit/
├── servicenow_portal_toolkit/
│   ├── __init__.py       ← version
│   ├── server.py         ← FastMCP server + all 4 tools
│   ├── setup_cli.py      ← setup / serve / check CLI commands
│   ├── branding.py       ← web scraping, WCAG math, branding score
│   └── analytics.py      ← portal usage aggregation
├── pyproject.toml
├── .env.example
└── .gitignore
```

---

## Branding Score Rubric

| Category | Max pts | What's checked |
|---|---|---|
| Primary vs White | 25 | WCAG 2.1 AA/AAA contrast |
| Text vs Background | 25 | WCAG 2.1 AA/AAA contrast |
| CSS Variable Coverage | 25 | 7 required `--css-vars` present |
| Font Consistency | 25 | Custom `--font-family-base` declared |

Score ≥ 90 → **A** · ≥ 75 → **B** · ≥ 60 → **C** · < 60 → **D**

---

## WCAG Color Extraction (apply_branding auto mode)

Priority order when scraping a URL:

1. `<meta name="theme-color">` tag
2. CSS custom properties (`--primary-color`, `--brand-color`, etc.)
3. Background color of `<header>` / `<nav>` elements
4. Most prominent non-utility color across all CSS

---

## Publishing to PyPI

```bash
pip install build twine
python -m build
twine upload dist/*
```

---

## Development

```bash
git clone https://github.com/yourusername/servicenow-portal-toolkit
cd servicenow-portal-toolkit
pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

---

## License

MIT — see [LICENSE](LICENSE).
