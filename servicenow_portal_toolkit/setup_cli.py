"""
CLI entry point: `servicenow-portal-toolkit [setup|serve|check]`

  setup  — interactive credential wizard + Claude Desktop config injection
  serve  — start the MCP server (used by Claude Desktop)
  check  — verify credentials and connectivity
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from . import __version__

_CFG_DIR = Path.home() / ".servicenow-portal-toolkit"
_ENV_FILE = _CFG_DIR / ".env"

_CLAUDE_CONFIG_CANDIDATES: list[Path] = []

if sys.platform == "win32":
    _appdata = os.environ.get("APPDATA", "")
    _localappdata = os.environ.get("LOCALAPPDATA", "")
    _CLAUDE_CONFIG_CANDIDATES = [
        Path(_appdata) / "Claude" / "claude_desktop_config.json",
        Path(_localappdata) / "AnthropicClaude" / "claude_desktop_config.json",
        Path(_localappdata) / "Claude" / "claude_desktop_config.json",
    ]
    # Windows Store installs use a sandboxed Packages path with a variable hash suffix
    _packages_dir = Path(_localappdata) / "Packages"
    if _packages_dir.exists():
        for _pkg in _packages_dir.iterdir():
            if _pkg.name.startswith("Claude_"):
                _store_cfg = _pkg / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"
                _CLAUDE_CONFIG_CANDIDATES.insert(0, _store_cfg)
elif sys.platform == "darwin":
    _CLAUDE_CONFIG_CANDIDATES = [
        Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
    ]
else:
    _xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    _CLAUDE_CONFIG_CANDIDATES = [
        Path(_xdg) / "Claude" / "claude_desktop_config.json",
        Path.home() / ".config" / "Claude" / "claude_desktop_config.json",
    ]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_claude_config() -> Path | None:
    for path in _CLAUDE_CONFIG_CANDIDATES:
        if path.exists():
            return path
    return None


def _mcp_server_entry() -> dict:
    """Return the mcpServers JSON block for this toolkit."""
    return {
        "command": sys.executable,
        "args": ["-m", "servicenow_portal_toolkit.setup_cli", "serve"],
    }


def _write_claude_config(config_path: Path) -> None:
    """Insert or overwrite the servicenow-portal-toolkit entry in Claude Desktop config."""
    if config_path.exists():
        try:
            with config_path.open(encoding="utf-8") as fh:
                config: dict = json.load(fh)
        except (json.JSONDecodeError, OSError):
            config = {}
    else:
        config = {}
        config_path.parent.mkdir(parents=True, exist_ok=True)

    config.setdefault("mcpServers", {})
    config["mcpServers"]["servicenow-portal-toolkit"] = _mcp_server_entry()

    with config_path.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
        fh.write("\n")


def _manual_config_snippet() -> str:
    snippet = {
        "mcpServers": {
            "servicenow-portal-toolkit": _mcp_server_entry()
        }
    }
    return json.dumps(snippet, indent=2)


# ── CLI group ─────────────────────────────────────────────────────────────────

@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="servicenow-portal-toolkit")
def cli() -> None:
    """ServiceNow Portal Toolkit — MCP server for Service Portal management."""


# ── setup command ─────────────────────────────────────────────────────────────

@cli.command()
@click.option("--instance", "-i", default=None, help="ServiceNow instance name (subdomain only).")
@click.option("--user", "-u", default=None, help="ServiceNow username.")
@click.option("--password", "-p", default=None, hidden=True, help="ServiceNow password.")
@click.option("--skip-claude", is_flag=True, default=False, help="Skip Claude Desktop config update.")
def setup(instance: str | None, user: str | None, password: str | None, skip_claude: bool) -> None:
    """Interactive setup: save credentials and register with Claude Desktop."""
    click.echo("\n" + "=" * 52)
    click.echo("  ServiceNow Portal Toolkit — Setup Wizard")
    click.echo("=" * 52 + "\n")
    click.echo("This will save credentials to:\n  " + str(_ENV_FILE) + "\n")

    # ── Collect credentials ───────────────────────────────────────────────
    if instance is None:
        instance = click.prompt(
            "ServiceNow instance name\n  (e.g. 'mycompany' for mycompany.service-now.com)",
            default=os.environ.get("SNOW_INSTANCE", ""),
        ).strip()

    if user is None:
        user = click.prompt(
            "ServiceNow username",
            default=os.environ.get("SNOW_USER", "admin"),
        ).strip()

    if password is None:
        password = click.prompt(
            "ServiceNow password",
            hide_input=True,
            confirmation_prompt=False,
        )

    if not instance or not user or not password:
        click.echo("\nError: all three fields are required.", err=True)
        sys.exit(1)

    # Strip protocol/suffix if user pasted the full URL
    instance = instance.replace("https://", "").replace("http://", "")
    instance = instance.replace(".service-now.com", "").split("/")[0]

    # ── Write .env ────────────────────────────────────────────────────────
    _CFG_DIR.mkdir(parents=True, exist_ok=True)
    with _ENV_FILE.open("w", encoding="utf-8") as fh:
        fh.write(f"SNOW_INSTANCE={instance}\n")
        fh.write(f"SNOW_USER={user}\n")
        fh.write(f"SNOW_PASS={password}\n")
    _ENV_FILE.chmod(0o600)  # owner-read-only (best-effort on Windows)

    click.echo(f"\n✓  Credentials saved to {_ENV_FILE}")

    # ── Update Claude Desktop config ──────────────────────────────────────
    if not skip_claude:
        config_path = _find_claude_config()
        if config_path:
            _write_claude_config(config_path)
            click.echo(f"✓  Updated Claude Desktop config: {config_path}")
        else:
            click.echo("\n⚠  Claude Desktop config not found at any of these locations:")
            for p in _CLAUDE_CONFIG_CANDIDATES:
                click.echo(f"   {p}")
            click.echo("\nAdd the following to your claude_desktop_config.json manually:\n")
            click.echo(_manual_config_snippet())

    click.echo(
        "\n✓  Setup complete!\n"
        "   Restart Claude Desktop to activate the ServiceNow Portal tools.\n"
    )


# ── serve command ─────────────────────────────────────────────────────────────

@cli.command()
def serve() -> None:
    """Start the MCP server (called automatically by Claude Desktop)."""
    # Import here to avoid loading heavy deps at CLI startup
    from .server import mcp  # noqa: PLC0415
    mcp.run()


# ── check command ─────────────────────────────────────────────────────────────

@cli.command()
def check() -> None:
    """Verify credentials and ServiceNow connectivity."""
    from dotenv import load_dotenv  # noqa: PLC0415

    load_dotenv(_ENV_FILE)
    load_dotenv()

    inst = os.environ.get("SNOW_INSTANCE", "")
    user = os.environ.get("SNOW_USER", "")
    pwd = os.environ.get("SNOW_PASS", "")

    if not (inst and user and pwd):
        click.echo(
            "Missing credentials. Run `servicenow-portal-toolkit setup` first.", err=True
        )
        sys.exit(1)

    click.echo(f"Connecting to https://{inst}.service-now.com …")

    try:
        import requests  # noqa: PLC0415

        resp = requests.get(
            f"https://{inst}.service-now.com/api/now/table/sp_portal",
            auth=(user, pwd),
            headers={"Accept": "application/json"},
            params={"sysparm_limit": 1},
            timeout=15,
        )
        resp.raise_for_status()
        count = len(resp.json().get("result", []))
        click.echo(f"✓  Connected successfully. Found {count} portal record(s).")
    except Exception as exc:  # noqa: BLE001
        click.echo(f"✗  Connection failed: {exc}", err=True)
        sys.exit(1)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    cli()


if __name__ == "__main__":
    main()
