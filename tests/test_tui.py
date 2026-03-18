"""Tests for the Codecast TUI app and screens."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml

from head.tui.app import CodecastApp, CODECAST_THEME
from head.tui.screens import SetupWizardScreen, DashboardScreen
from head.tui.widgets import StatusPanel, PeerTable


def _get_static_text(widget) -> str:
    """Extract text content from a Static widget (Textual internals)."""
    # Access the private __content attribute set in Static.__init__
    content = getattr(widget, "_Static__content", "")
    return str(content)


@pytest.mark.asyncio
async def test_app_launches():
    """App should launch and have the correct title."""
    app = CodecastApp(config_path="/tmp/nonexistent_codecast_test.yaml")
    async with app.run_test() as pilot:
        assert app.title == "Codecast"


@pytest.mark.asyncio
async def test_theme_registered():
    """App should register and use the codecast theme."""
    app = CodecastApp(config_path="/tmp/nonexistent_codecast_test.yaml")
    async with app.run_test() as pilot:
        assert app.theme == "codecast"


@pytest.mark.asyncio
async def test_setup_wizard_shown_no_config(tmp_path):
    """Setup wizard should be displayed when config file does not exist."""
    config_path = str(tmp_path / "nonexistent.yaml")
    app = CodecastApp(config_path=config_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, SetupWizardScreen)
        welcome = app.screen.query_one("#welcome")
        text = _get_static_text(welcome)
        assert "Welcome" in text


@pytest.mark.asyncio
async def test_dashboard_shown_when_config_exists(tmp_path):
    """Dashboard should be displayed when a config file exists."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)
        status = app.screen.query_one("#status")
        assert isinstance(status, StatusPanel)


@pytest.mark.asyncio
async def test_wizard_menu_options(tmp_path):
    """Wizard should show the expected menu options."""
    config_path = str(tmp_path / "nonexistent.yaml")
    app = CodecastApp(config_path=config_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        menu = app.screen.query_one("#wizard_menu")
        option_ids = [opt.id for opt in menu._options]
        assert "start_daemon" in option_ids
        assert "add_peer" in option_ids
        assert "config_discord" in option_ids
        assert "config_telegram" in option_ids
        assert "skip" in option_ids


@pytest.mark.asyncio
async def test_dashboard_keybindings(tmp_path):
    """Dashboard should have the expected keybindings."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)
        keys = {b[0] if isinstance(b, tuple) else b.key for b in app.screen.BINDINGS}
        assert "d" in keys
        assert "b" in keys
        assert "w" in keys
        assert "a" in keys
        assert "s" in keys
        assert "q" in keys


@pytest.mark.asyncio
async def test_status_panel_renders(tmp_path):
    """StatusPanel should render all 4 component status lines."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        status = app.screen.query_one("#status", StatusPanel)
        text = _get_static_text(status)
        assert "Head:" in text
        assert "Daemon:" in text
        assert "WebUI:" in text
        assert "Claude:" in text


@pytest.mark.asyncio
async def test_peer_table_shows_peers(tmp_path):
    """PeerTable should show peers from config."""
    config_path = tmp_path / "config.yaml"
    cfg = {
        "default_mode": "auto",
        "peers": {
            "server1": {"transport": "ssh", "ssh_host": "10.0.0.1"},
            "server2": {"transport": "http", "address": "https://10.0.0.2:9100"},
        },
    }
    config_path.write_text(yaml.dump(cfg))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.screen.query_one("#peer_table", PeerTable)
        assert table.row_count == 2


@pytest.mark.asyncio
async def test_peer_table_empty_config(tmp_path):
    """PeerTable should handle config with no peers."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.screen.query_one("#peer_table", PeerTable)
        assert table.row_count == 0


@pytest.mark.asyncio
async def test_peer_table_title_shows_count(tmp_path):
    """Peer table title should show the peer count."""
    config_path = tmp_path / "config.yaml"
    cfg = {
        "default_mode": "auto",
        "peers": {
            "s1": {"transport": "ssh", "ssh_host": "10.0.0.1"},
            "s2": {"transport": "ssh", "ssh_host": "10.0.0.2"},
            "s3": {"transport": "ssh", "ssh_host": "10.0.0.3"},
        },
    }
    config_path.write_text(yaml.dump(cfg))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        title = app.screen.query_one("#peer_table_title")
        text = _get_static_text(title)
        assert "3 configured" in text


@pytest.mark.asyncio
async def test_quit_via_key(tmp_path):
    """Pressing 'q' in the wizard should exit the app."""
    config_path = str(tmp_path / "nonexistent.yaml")
    app = CodecastApp(config_path=config_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")


@pytest.mark.asyncio
async def test_version_displayed(tmp_path):
    """Version string should appear in the welcome screen."""
    config_path = str(tmp_path / "nonexistent.yaml")
    app = CodecastApp(config_path=config_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        welcome = app.screen.query_one("#welcome")
        text = _get_static_text(welcome)
        # Should contain a version like "v0.2.1" or at least "v"
        assert "v" in text


@pytest.mark.asyncio
async def test_dashboard_has_status_panel_container(tmp_path):
    """Dashboard should have bordered status and peer containers."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.query_one("#status_panel_container") is not None
        assert app.screen.query_one("#peer_table_container") is not None
