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
| `apply_branding` | Scrape a website URL *or* accept manual hex values → push SCSS vars to `sp_portal.css_variables` with WCAG AA check + before-snapshot |
| `branding_score` | Read `css_variables` from the portal, score contrast ratios + SCSS var coverage out of 100 |
| `portal_analytics` | Pull page views and search trends from `sp_log` — top pages, search terms, zero-result gaps |

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
> "Give me a branding score for the 'esc' portal and tell me what to fix."

**4. Analyze portal usage**
> "Show me the top pages and search gaps for the 'esc' portal."

---

## Required ServiceNow Permissions

The configured user needs **read** access to:
- `sp_portal` — list portals, read css_variables for scoring
- `sp_log` — page view and search analytics

And **write** access to:
- `sp_portal` — apply branding changes to css_variables

---

## Architecture

```
servicenow-portal-toolkit/
├── servicenow_portal_toolkit/
│   ├── __init__.py       ← version
│   ├── server.py         ← FastMCP server + all 4 tools
│   ├── setup_cli.py      ← setup / serve / check CLI commands
│   ├── branding.py       ← web scraping, WCAG math, branding score
│   └── analytics.py      ← portal usage aggregation from sp_log
├── pyproject.toml
├── .env.example
└── .gitignore
```

---

## Branding Score Rubric

| Category | Max pts | What's checked |
|---|---|---|
| Primary vs White | 40 | WCAG 2.1 AA/AAA contrast ratio |
| Text vs Background | 40 | WCAG 2.1 AA/AAA contrast ratio |
| SCSS Variable Coverage | 20 | 8 required `$scss-vars` present in css_variables |

Score ≥ 90 → **A** · ≥ 75 → **B** · ≥ 60 → **C** · < 60 → **D**

---

## WCAG Color Extraction (apply_branding auto mode)

Priority order when scraping a URL:

1. `<meta name="theme-color">` tag
2. CSS custom properties (`--primary-color`, `--brand-color`, etc.)
3. Background color of `<header>` / `<nav>` elements
4. Most prominent non-utility color across all CSS

---

## Roadmap

This is v0.1 — a foundation for AI-driven ServiceNow Portal administration. Built with the **Employee Slate** era in mind, here's where this is heading:

### 1. Legacy Portal → Employee Slate Migration Co-pilot
ServiceNow's Employee Slate is redefining the employee experience with conversation-first design, My Canvas personalization, and AI-powered workflows. Every organization running Service Portal today will need to migrate. This tool will audit your existing portal estate, map old widgets to new Employee Slate components, identify pages that can be retired vs rebuilt, and generate a step-by-step migration plan — all through a conversation. What takes a consultant weeks, done in minutes.

### 2. Full Portal Orchestration from a Brief
Give Claude a brief: *"Build an HR portal for 500 employees. Primary color matches our brand site. Needs a homepage, service catalog, knowledge base, and case submission page."* The MCP handles the entire build — portal record, pages, layouts, widget placement, branding, search configuration. Designed to power the rapid deployment Employee Slate demands.

### 3. Search Intelligence Engine
Employee Slate promises enterprise search across 100+ content sources — SharePoint, Google Drive, Slack, and more. Behind that promise is a configuration layer that someone has to build and maintain. This tool will audit search source configurations, detect gaps from zero-result analytics, suggest new sources to connect, auto-draft KB articles for content gaps, and tune relevancy — turning search from a setup task into a continuously improving engine.

---

## Development

```bash
git clone https://github.com/Jithesh11/servicenow-portal-toolkit
cd servicenow-portal-toolkit
pip install -e ".[dev]"
```

---

## Publishing to PyPI

```bash
pip install build twine
python -m build
twine upload dist/*
```

---

## License

MIT — see [LICENSE](LICENSE).
