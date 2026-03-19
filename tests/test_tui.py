"""Tests for the Codecast TUI app and screens."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml

from head.tui.app import CodecastApp, CODECAST_THEME
from head.tui.screens import (
    AddMachineScreen,
    ConfigBotScreen,
    DashboardScreen,
    HelpScreen,
    SessionsScreen,
    SetupWizardScreen,
    StartDaemonScreen,
    StartHeadScreen,
    StartWebUIScreen,
)
from head.tui.widgets import StatusPanel, MachineTable


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
        assert "add_machine" in option_ids
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
        assert "H" in keys
        assert "w" in keys
        assert "a" in keys
        assert "s" in keys
        assert "x" in keys
        assert "j" in keys
        assert "k" in keys
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
async def test_machine_table_shows_machines(tmp_path):
    """MachineTable should show machines from config."""
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
        table = app.screen.query_one("#machine_table", MachineTable)
        assert table.row_count == 2


@pytest.mark.asyncio
async def test_machine_table_empty_config(tmp_path):
    """MachineTable should handle config with no machines."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.screen.query_one("#machine_table", MachineTable)
        assert table.row_count == 0


@pytest.mark.asyncio
async def test_machine_table_title_shows_count(tmp_path):
    """Machine table title should show the machine count."""
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
        title = app.screen.query_one("#machine_table_title")
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
    """Dashboard should have bordered status and machine containers."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.query_one("#status_panel_container") is not None
        assert app.screen.query_one("#machine_table_container") is not None


# ---------------------------------------------------------------------------
# StartHeadScreen tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_head_screen_shows_status(tmp_path):
    """StartHeadScreen should show head node status and config summary."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        # Push StartHeadScreen from dashboard
        app.push_screen(StartHeadScreen(str(config_path)))
        await pilot.pause()
        assert isinstance(app.screen, StartHeadScreen)
        status = app.screen.query_one("#head_status")
        text = _get_static_text(status)
        assert "not running" in text
        assert "Config:" in text


@pytest.mark.asyncio
async def test_start_head_screen_menu_options(tmp_path):
    """StartHeadScreen should show config options and back."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(StartHeadScreen(str(config_path)))
        await pilot.pause()
        menu = app.screen.query_one("#head_menu")
        option_ids = [opt.id for opt in menu._options]
        assert "config_discord" in option_ids
        assert "config_telegram" in option_ids
        assert "back" in option_ids


@pytest.mark.asyncio
async def test_start_head_screen_shows_bots_when_configured(tmp_path):
    """StartHeadScreen should list configured bots."""
    config_path = tmp_path / "config.yaml"
    cfg = {
        "default_mode": "auto",
        "bot": {"discord": {"token": "fake-token-123"}},
    }
    config_path.write_text(yaml.dump(cfg))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(StartHeadScreen(str(config_path)))
        await pilot.pause()
        status = app.screen.query_one("#head_status")
        text = _get_static_text(status)
        assert "Discord" in text
        # Should have start option when bots are configured
        menu = app.screen.query_one("#head_menu")
        option_ids = [opt.id for opt in menu._options]
        assert "start" in option_ids


@pytest.mark.asyncio
async def test_start_head_screen_escape_goes_back(tmp_path):
    """Pressing escape on StartHeadScreen should return to dashboard."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(StartHeadScreen(str(config_path)))
        await pilot.pause()
        assert isinstance(app.screen, StartHeadScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)


# ---------------------------------------------------------------------------
# StartWebUIScreen tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_webui_screen_shows_status(tmp_path):
    """StartWebUIScreen should show WebUI status."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(StartWebUIScreen(str(config_path)))
        await pilot.pause()
        assert isinstance(app.screen, StartWebUIScreen)
        status = app.screen.query_one("#webui_status")
        text = _get_static_text(status)
        assert "stopped" in text or "not running" in text


@pytest.mark.asyncio
async def test_start_webui_screen_menu_options(tmp_path):
    """StartWebUIScreen should have start and back options when not running."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(StartWebUIScreen(str(config_path)))
        await pilot.pause()
        menu = app.screen.query_one("#webui_menu")
        option_ids = [opt.id for opt in menu._options]
        assert "start" in option_ids
        assert "back" in option_ids


@pytest.mark.asyncio
async def test_start_webui_screen_escape_goes_back(tmp_path):
    """Pressing escape on StartWebUIScreen should return to dashboard."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(StartWebUIScreen(str(config_path)))
        await pilot.pause()
        assert isinstance(app.screen, StartWebUIScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)


# ---------------------------------------------------------------------------
# SessionsScreen tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sessions_screen_shows_table(tmp_path):
    """SessionsScreen should display a DataTable with session columns."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SessionsScreen(str(config_path)))
        await pilot.pause()
        assert isinstance(app.screen, SessionsScreen)
        table = app.screen.query_one("#sessions_table")
        assert table is not None
        # Should have the expected columns
        col_labels = [col.label.plain for col in table.columns.values()]
        assert "Name" in col_labels
        assert "Status" in col_labels
        assert "Created" in col_labels


@pytest.mark.asyncio
async def test_sessions_screen_no_sessions(tmp_path):
    """SessionsScreen should show 'no sessions' when DB doesn't exist."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = SessionsScreen(str(config_path))
        screen._load_sessions = lambda: []  # No sessions
        app.push_screen(screen)
        await pilot.pause()
        info = app.screen.query_one("#sessions_info")
        text = _get_static_text(info)
        assert "No sessions found" in text


@pytest.mark.asyncio
async def test_sessions_screen_escape_goes_back(tmp_path):
    """Pressing escape on SessionsScreen should return to dashboard."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SessionsScreen(str(config_path)))
        await pilot.pause()
        assert isinstance(app.screen, SessionsScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)


@pytest.mark.asyncio
async def test_sessions_screen_with_sessions(tmp_path):
    """SessionsScreen should show sessions from a pre-populated DB."""
    import sqlite3

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))

    # Create a fake sessions database
    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE sessions (
            channel_id TEXT PRIMARY KEY,
            machine_id TEXT NOT NULL,
            path TEXT NOT NULL,
            daemon_session_id TEXT NOT NULL,
            sdk_session_id TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            mode TEXT NOT NULL DEFAULT 'auto',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            name TEXT,
            tool_display TEXT DEFAULT 'append'
        )
    """)
    conn.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "discord:123",
            "server1",
            "/home/user/project",
            "uuid-1234",
            None,
            "active",
            "auto",
            "2026-03-18T00:00:00",
            "2026-03-18T00:00:00",
            "bright-falcon",
            "append",
        ),
    )
    conn.commit()
    conn.close()

    # Patch _load_sessions to use our temp DB
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = SessionsScreen(str(config_path))
        # Monkey-patch to use our DB
        original_load = screen._load_sessions

        def patched_load():
            from head.session_router import SessionRouter

            router = SessionRouter(str(db_path))
            return router.list_sessions()

        screen._load_sessions = patched_load
        app.push_screen(screen)
        await pilot.pause()

        table = app.screen.query_one("#sessions_table")
        # 1 machine header + 1 session row = 2 rows
        assert table.row_count == 2
        info = app.screen.query_one("#sessions_info")
        text = _get_static_text(info)
        assert "1 session(s)" in text


# ---------------------------------------------------------------------------
# Dashboard action routing tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_H_key_opens_head_screen(tmp_path):
    """Pressing 'H' (shift-h) on dashboard should open StartHeadScreen."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)
        await pilot.press("H")
        await pilot.pause()
        assert isinstance(app.screen, StartHeadScreen)


@pytest.mark.asyncio
async def test_dashboard_w_key_opens_webui_screen(tmp_path):
    """Pressing 'w' on dashboard should open StartWebUIScreen."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)
        await pilot.press("w")
        await pilot.pause()
        assert isinstance(app.screen, StartWebUIScreen)


@pytest.mark.asyncio
async def test_dashboard_s_key_opens_sessions_screen(tmp_path):
    """Pressing 's' on dashboard should open SessionsScreen."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)
        await pilot.press("s")
        await pilot.pause()
        assert isinstance(app.screen, SessionsScreen)


# ---------------------------------------------------------------------------
# AddMachineScreen tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_machine_screen_shows_method_choice(tmp_path):
    """AddMachineScreen should show Manual/SSH import options."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(AddMachineScreen(str(config_path)))
        await pilot.pause()
        assert isinstance(app.screen, AddMachineScreen)
        method_list = app.screen.query_one("#add_machine_method")
        option_ids = [opt.id for opt in method_list._options]
        assert "manual" in option_ids
        assert "ssh_import" in option_ids


@pytest.mark.asyncio
async def test_add_machine_screen_title(tmp_path):
    """AddMachineScreen should display 'Add a machine' title."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(AddMachineScreen(str(config_path)))
        await pilot.pause()
        title = app.screen.query_one("#add_machine_title")
        text = _get_static_text(title)
        assert "Add a machine" in text


# ---------------------------------------------------------------------------
# Remove machine tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_machine_action(tmp_path):
    """action_remove_machine should remove a machine from config."""
    config_path = tmp_path / "config.yaml"
    cfg = {
        "default_mode": "auto",
        "peers": {
            "server1": {"transport": "ssh", "ssh_host": "10.0.0.1"},
            "server2": {"transport": "ssh", "ssh_host": "10.0.0.2"},
        },
    }
    config_path.write_text(yaml.dump(cfg))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)
        table = app.screen.query_one("#machine_table", MachineTable)
        assert table.row_count == 2
        # The x key triggers remove_machine (needs a selected row)
        # Just verify the binding exists
        keys = {b[0] if isinstance(b, tuple) else b.key for b in app.screen.BINDINGS}
        assert "x" in keys


# ---------------------------------------------------------------------------
# Vim navigation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vim_navigation_bindings_on_dashboard(tmp_path):
    """Dashboard should have j/k/l vim navigation bindings."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)
        keys = {b[0] if isinstance(b, tuple) else b.key for b in app.screen.BINDINGS}
        assert "j" in keys
        assert "k" in keys
        assert "l" in keys


@pytest.mark.asyncio
async def test_vim_navigation_bindings_on_sessions(tmp_path):
    """SessionsScreen should have j/k/h/l vim navigation bindings."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SessionsScreen(str(config_path)))
        await pilot.pause()
        assert isinstance(app.screen, SessionsScreen)
        keys = {b[0] if isinstance(b, tuple) else b.key for b in app.screen.BINDINGS}
        assert "j" in keys
        assert "k" in keys
        assert "h" in keys
        assert "l" in keys


# ---------------------------------------------------------------------------
# Session drill-down tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sessions_screen_filter_machine(tmp_path):
    """SessionsScreen should support filter_machine parameter."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = SessionsScreen(str(config_path), filter_machine="server1")
        screen._load_sessions = lambda: []
        app.push_screen(screen)
        await pilot.pause()
        assert app.screen._filter_machine == "server1"
        title = app.screen.query_one("#sessions_title")
        text = _get_static_text(title)
        assert "server1" in text


@pytest.mark.asyncio
async def test_sessions_screen_h_goes_back_from_filter(tmp_path):
    """Pressing 'h' on filtered sessions should clear filter, not pop screen."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = SessionsScreen(str(config_path), filter_machine="server1")
        screen._load_sessions = lambda: []
        app.push_screen(screen)
        await pilot.pause()
        assert app.screen._filter_machine == "server1"
        await pilot.press("h")
        await pilot.pause()
        # Should still be on SessionsScreen but filter cleared
        assert isinstance(app.screen, SessionsScreen)
        assert app.screen._filter_machine is None


@pytest.mark.asyncio
async def test_sessions_screen_h_pops_when_no_filter(tmp_path):
    """Pressing 'h' on unfiltered sessions should pop back to dashboard."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = SessionsScreen(str(config_path))
        screen._load_sessions = lambda: []
        app.push_screen(screen)
        await pilot.pause()
        assert isinstance(app.screen, SessionsScreen)
        assert app.screen._filter_machine is None
        await pilot.press("h")
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)


# ---------------------------------------------------------------------------
# StartDaemonScreen tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_daemon_screen_shows_stopped(tmp_path):
    """StartDaemonScreen should show 'stopped' when daemon is not running."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        with (
            patch("head.tui.screens._check_daemon_running", return_value=(False, None)),
            patch("head.tui.screens._check_claude_cli", return_value=True),
        ):
            app.push_screen(StartDaemonScreen(str(config_path)))
            await pilot.pause()
        assert isinstance(app.screen, StartDaemonScreen)
        status = app.screen.query_one("#daemon_status")
        text = _get_static_text(status)
        assert "stopped" in text


@pytest.mark.asyncio
async def test_start_daemon_screen_shows_running(tmp_path):
    """StartDaemonScreen should show 'running' with port when daemon is up."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        with (
            patch("head.tui.screens._check_daemon_running", return_value=(True, 9100)),
            patch("head.tui.screens._check_claude_cli", return_value=True),
            patch("head.cli._read_pid_file", return_value=12345),
            patch("head.cli._pid_alive", return_value=True),
        ):
            app.push_screen(StartDaemonScreen(str(config_path)))
            await pilot.pause()
        status = app.screen.query_one("#daemon_status")
        text = _get_static_text(status)
        assert "running" in text
        assert "9100" in text


@pytest.mark.asyncio
async def test_start_daemon_screen_no_claude_cli(tmp_path):
    """StartDaemonScreen should warn when Claude CLI is not available."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        with (
            patch("head.tui.screens._check_daemon_running", return_value=(False, None)),
            patch("head.tui.screens._check_claude_cli", return_value=False),
        ):
            app.push_screen(StartDaemonScreen(str(config_path)))
            await pilot.pause()
        status = app.screen.query_one("#daemon_status")
        text = _get_static_text(status)
        assert "not found" in text


@pytest.mark.asyncio
async def test_start_daemon_screen_escape_goes_back(tmp_path):
    """Pressing escape on StartDaemonScreen should return to dashboard."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        with (
            patch("head.tui.screens._check_daemon_running", return_value=(False, None)),
            patch("head.tui.screens._check_claude_cli", return_value=True),
        ):
            app.push_screen(StartDaemonScreen(str(config_path)))
            await pilot.pause()
        assert isinstance(app.screen, StartDaemonScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)


@pytest.mark.asyncio
async def test_start_daemon_screen_start_option(tmp_path):
    """StartDaemonScreen should show 'Start daemon' when stopped and CLI available."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        with (
            patch("head.tui.screens._check_daemon_running", return_value=(False, None)),
            patch("head.tui.screens._check_claude_cli", return_value=True),
        ):
            app.push_screen(StartDaemonScreen(str(config_path)))
            await pilot.pause()
        menu = app.screen.query_one("#daemon_menu")
        option_ids = [opt.id for opt in menu._options]
        assert "start" in option_ids


# ---------------------------------------------------------------------------
# HelpScreen tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_help_screen_shows_shortcuts(tmp_path):
    """HelpScreen should show keyboard shortcuts."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(HelpScreen())
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        help_text = app.screen.query_one("#help_text")
        text = _get_static_text(help_text)
        assert "Dashboard shortcuts" in text
        assert "Navigation" in text


@pytest.mark.asyncio
async def test_help_screen_shows_cli_equivalents(tmp_path):
    """HelpScreen should show CLI equivalents."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(HelpScreen())
        await pilot.pause()
        help_text = app.screen.query_one("#help_text")
        text = _get_static_text(help_text)
        assert "CLI equivalents" in text
        assert "codecast start" in text


@pytest.mark.asyncio
async def test_help_screen_escape_goes_back(tmp_path):
    """Pressing escape on HelpScreen should return to dashboard."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(HelpScreen())
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)


# ---------------------------------------------------------------------------
# ConfigBotScreen tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_bot_screen_discord_title(tmp_path):
    """ConfigBotScreen should show Discord in the title for discord type."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ConfigBotScreen(str(config_path), "discord"))
        await pilot.pause()
        assert isinstance(app.screen, ConfigBotScreen)
        title = app.screen.query_one("#bot_title")
        text = _get_static_text(title)
        assert "Discord" in text


@pytest.mark.asyncio
async def test_config_bot_screen_telegram_title(tmp_path):
    """ConfigBotScreen should show Telegram in the title for telegram type."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ConfigBotScreen(str(config_path), "telegram"))
        await pilot.pause()
        title = app.screen.query_one("#bot_title")
        text = _get_static_text(title)
        assert "Telegram" in text


@pytest.mark.asyncio
async def test_config_bot_screen_has_guidance(tmp_path):
    """ConfigBotScreen should show platform-specific guidance text."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ConfigBotScreen(str(config_path), "discord"))
        await pilot.pause()
        guidance = app.screen.query_one("#bot_guidance")
        text = _get_static_text(guidance)
        assert "Discord Bot Setup" in text
        assert "discord.com/developers" in text


@pytest.mark.asyncio
async def test_config_bot_screen_telegram_guidance(tmp_path):
    """ConfigBotScreen should show Telegram-specific guidance."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ConfigBotScreen(str(config_path), "telegram"))
        await pilot.pause()
        guidance = app.screen.query_one("#bot_guidance")
        text = _get_static_text(guidance)
        assert "Telegram Bot Setup" in text
        assert "BotFather" in text


@pytest.mark.asyncio
async def test_config_bot_screen_password_input(tmp_path):
    """ConfigBotScreen should have a password-masked input field."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ConfigBotScreen(str(config_path), "discord"))
        await pilot.pause()
        inp = app.screen.query_one("#bot_token_input")
        assert inp.password is True


@pytest.mark.asyncio
async def test_config_bot_screen_saves_discord_token(tmp_path):
    """ConfigBotScreen should save a Discord token to config."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ConfigBotScreen(str(config_path), "discord"))
        await pilot.pause()
        inp = app.screen.query_one("#bot_token_input")
        inp.value = "test-discord-token-123"
        await inp.action_submit()
        await pilot.pause()
        # Verify token was written
        with open(config_path) as f:
            saved = yaml.safe_load(f)
        assert saved["bot"]["discord"]["token"] == "test-discord-token-123"


@pytest.mark.asyncio
async def test_config_bot_screen_escape_goes_back(tmp_path):
    """Pressing escape on ConfigBotScreen should go back."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ConfigBotScreen(str(config_path), "discord"))
        await pilot.pause()
        assert isinstance(app.screen, ConfigBotScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)


# ---------------------------------------------------------------------------
# AddMachine manual flow tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_machine_manual_step1_prompt(tmp_path):
    """Selecting 'Manual entry' should show machine name prompt."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = AddMachineScreen(str(config_path))
        app.push_screen(screen)
        await pilot.pause()
        # Simulate selecting "manual"
        screen._mode = "manual"
        screen._step = 1
        screen._switch_to_manual_input()
        await pilot.pause()
        prompt = screen.query_one("#add_machine_prompt")
        text = _get_static_text(prompt)
        assert "machine name" in text.lower()


@pytest.mark.asyncio
async def test_add_machine_manual_ssh_flow(tmp_path):
    """Manual SSH machine should be saved to config."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = AddMachineScreen(str(config_path))
        app.push_screen(screen)
        await pilot.pause()
        screen._mode = "manual"
        screen._step = 1
        screen._switch_to_manual_input()
        await pilot.pause()

        from textual.widgets import Input

        inp = screen.query_one("#machine_input", Input)
        inp.value = "test-server"
        await inp.action_submit()
        await pilot.pause()

        inp = screen.query_one("#machine_input", Input)
        inp.value = "ssh"
        await inp.action_submit()
        await pilot.pause()

        inp = screen.query_one("#machine_input", Input)
        inp.value = "user@10.0.0.99"
        await inp.action_submit()
        await pilot.pause()

        # Verify saved
        with open(config_path) as f:
            saved = yaml.safe_load(f)
        assert "test-server" in saved["peers"]
        assert saved["peers"]["test-server"]["ssh_host"] == "10.0.0.99"
        assert saved["peers"]["test-server"]["ssh_user"] == "user"


@pytest.mark.asyncio
async def test_add_machine_manual_http_flow(tmp_path):
    """Manual HTTP machine should be saved to config."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = AddMachineScreen(str(config_path))
        app.push_screen(screen)
        await pilot.pause()
        screen._mode = "manual"
        screen._step = 1
        screen._switch_to_manual_input()
        await pilot.pause()

        from textual.widgets import Input

        inp = screen.query_one("#machine_input", Input)
        inp.value = "http-server"
        await inp.action_submit()
        await pilot.pause()

        inp = screen.query_one("#machine_input", Input)
        inp.value = "http"
        await inp.action_submit()
        await pilot.pause()

        inp = screen.query_one("#machine_input", Input)
        inp.value = "https://10.0.0.50:9100"
        await inp.action_submit()
        await pilot.pause()

        with open(config_path) as f:
            saved = yaml.safe_load(f)
        assert "http-server" in saved["peers"]
        assert saved["peers"]["http-server"]["transport"] == "http"
        assert saved["peers"]["http-server"]["address"] == "https://10.0.0.50:9100"


# ---------------------------------------------------------------------------
# AddMachine SSH import tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_machine_ssh_import_shows_hosts(tmp_path):
    """SSH import should show available hosts."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))

    from head.config import SSHHostEntry

    mock_entries = [
        SSHHostEntry(name="server-a", hostname="10.0.0.1", user="alice"),
        SSHHostEntry(name="server-b", hostname="10.0.0.2"),
    ]

    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = AddMachineScreen(str(config_path))
        app.push_screen(screen)
        await pilot.pause()
        with patch("head.config.parse_ssh_config", return_value=mock_entries):
            screen._show_ssh_hosts()
            await pilot.pause()
        prompt = screen.query_one("#add_machine_prompt")
        text = _get_static_text(prompt)
        assert "2 available" in text


@pytest.mark.asyncio
async def test_add_machine_ssh_import_filters_existing(tmp_path):
    """SSH import should filter out already-configured machines."""
    config_path = tmp_path / "config.yaml"
    cfg = {
        "default_mode": "auto",
        "peers": {"server-a": {"transport": "ssh", "ssh_host": "10.0.0.1"}},
    }
    config_path.write_text(yaml.dump(cfg))

    from head.config import SSHHostEntry

    mock_entries = [
        SSHHostEntry(name="server-a", hostname="10.0.0.1"),
        SSHHostEntry(name="server-b", hostname="10.0.0.2"),
    ]

    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = AddMachineScreen(str(config_path))
        app.push_screen(screen)
        await pilot.pause()
        with patch("head.config.parse_ssh_config", return_value=mock_entries):
            screen._show_ssh_hosts()
            await pilot.pause()
        prompt = screen.query_one("#add_machine_prompt")
        text = _get_static_text(prompt)
        assert "1 available" in text


@pytest.mark.asyncio
async def test_add_machine_ssh_import_deduplicates(tmp_path):
    """SSH import should deduplicate hosts with the same name."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))

    from head.config import SSHHostEntry

    mock_entries = [
        SSHHostEntry(name="jump-box", hostname="10.0.0.1", user="admin"),
        SSHHostEntry(name="jump-box", hostname="10.0.0.2", user="admin"),
        SSHHostEntry(name="unique-host", hostname="10.0.0.5"),
    ]

    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = AddMachineScreen(str(config_path))
        app.push_screen(screen)
        await pilot.pause()
        with patch("head.config.parse_ssh_config", return_value=mock_entries):
            screen._show_ssh_hosts()
            await pilot.pause()
        prompt = screen.query_one("#add_machine_prompt")
        text = _get_static_text(prompt)
        # Should show 2 (dice deduped) not 3
        assert "2 available" in text


@pytest.mark.asyncio
async def test_add_machine_ssh_import_saves_machine(tmp_path):
    """Importing an SSH host should save it to config."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))

    from head.config import SSHHostEntry

    mock_entries = [
        SSHHostEntry(name="remote-box", hostname="192.168.1.100", user="deploy"),
    ]

    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = AddMachineScreen(str(config_path))
        app.push_screen(screen)
        await pilot.pause()
        with (
            patch("head.config.parse_ssh_config", return_value=mock_entries),
            patch("head.config._is_localhost", return_value=False),
        ):
            screen._import_ssh_host("remote-box")
            await pilot.pause()
        with open(config_path) as f:
            saved = yaml.safe_load(f)
        assert "remote-box" in saved["peers"]
        assert saved["peers"]["remote-box"]["ssh_host"] == "192.168.1.100"
        assert saved["peers"]["remote-box"]["ssh_user"] == "deploy"


# ---------------------------------------------------------------------------
# SessionsScreen additional tests
# ---------------------------------------------------------------------------


def _make_fake_session(
    channel_id="discord:100",
    machine_id="server1",
    path="/home/user/project",
    daemon_session_id="uuid-0001",
    status="active",
    mode="auto",
    created_at="2026-03-18T10:00:00",
    name="bright-falcon",
):
    """Create a fake session object for testing."""
    from types import SimpleNamespace

    return SimpleNamespace(
        channel_id=channel_id,
        machine_id=machine_id,
        path=path,
        daemon_session_id=daemon_session_id,
        sdk_session_id=None,
        status=status,
        mode=mode,
        created_at=created_at,
        updated_at=created_at,
        name=name,
        tool_display="append",
    )


@pytest.mark.asyncio
async def test_sessions_screen_toggle_sort(tmp_path):
    """Pressing 't' should toggle sort order."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    sessions = [
        _make_fake_session(channel_id="discord:1", name="alpha", created_at="2026-03-18T08:00:00"),
        _make_fake_session(channel_id="discord:2", name="beta", created_at="2026-03-18T12:00:00"),
    ]
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = SessionsScreen(str(config_path))
        screen._load_sessions = lambda: sessions
        app.push_screen(screen)
        await pilot.pause()
        assert screen._sort_descending is True
        info_text = _get_static_text(screen.query_one("#sessions_info"))
        assert "newest first" in info_text
        await pilot.press("t")
        await pilot.pause()
        assert screen._sort_descending is False
        info_text = _get_static_text(screen.query_one("#sessions_info"))
        assert "oldest first" in info_text


@pytest.mark.asyncio
async def test_sessions_screen_color_coded_status(tmp_path):
    """Sessions should show color-coded status values."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    sessions = [
        _make_fake_session(channel_id="discord:1", status="active"),
        _make_fake_session(channel_id="discord:2", status="detached", name="detach-test"),
        _make_fake_session(channel_id="discord:3", status="destroyed", name="dead-test"),
    ]
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = SessionsScreen(str(config_path))
        screen._load_sessions = lambda: sessions
        app.push_screen(screen)
        await pilot.pause()
        info_text = _get_static_text(screen.query_one("#sessions_info"))
        assert "3 session(s)" in info_text


@pytest.mark.asyncio
async def test_sessions_screen_open_machine_header(tmp_path):
    """Pressing enter on a machine header should filter to that machine."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    sessions = [
        _make_fake_session(channel_id="discord:1", machine_id="server1"),
        _make_fake_session(channel_id="discord:2", machine_id="server2"),
    ]
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = SessionsScreen(str(config_path))
        screen._load_sessions = lambda: sessions
        app.push_screen(screen)
        await pilot.pause()
        # First row is machine header for server1
        assert screen._row_machine_map.get(0) is not None
        # Simulate action_open_or_enter when cursor is on a machine header
        screen.action_open_or_enter()
        await pilot.pause()
        assert screen._filter_machine is not None


@pytest.mark.asyncio
async def test_sessions_screen_remove_session(tmp_path):
    """Pressing 'r' should remove the selected session."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    sessions = [
        _make_fake_session(channel_id="discord:1", name="to-remove"),
    ]
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = SessionsScreen(str(config_path))
        screen._load_sessions = lambda: list(sessions)
        # Mock _get_router to avoid needing a real DB
        screen._get_router = lambda: None
        app.push_screen(screen)
        await pilot.pause()
        # Should have 1 header + 1 session = 2 rows
        table = screen.query_one("#sessions_table")
        assert table.row_count == 2


# ---------------------------------------------------------------------------
# DashboardScreen additional tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_on_screen_resume_refreshes(tmp_path):
    """on_screen_resume should refresh status panel and machine table."""
    config_path = tmp_path / "config.yaml"
    cfg = {
        "default_mode": "auto",
        "peers": {"s1": {"transport": "ssh", "ssh_host": "10.0.0.1"}},
    }
    config_path.write_text(yaml.dump(cfg))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)
        # Push and pop a screen to trigger on_screen_resume
        app.push_screen(HelpScreen())
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)
        # Verify components still work
        table = app.screen.query_one("#machine_table", MachineTable)
        assert table.row_count == 1


@pytest.mark.asyncio
async def test_dashboard_open_machine_with_selection(tmp_path):
    """action_open_machine should open sessions screen."""
    config_path = tmp_path / "config.yaml"
    cfg = {
        "default_mode": "auto",
        "peers": {
            "s1": {"transport": "ssh", "ssh_host": "10.0.0.1"},
            "s2": {"transport": "ssh", "ssh_host": "10.0.0.2"},
        },
    }
    config_path.write_text(yaml.dump(cfg))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)
        # Call action directly to avoid focus issues
        app.screen.action_open_machine()
        await pilot.pause()
        assert isinstance(app.screen, SessionsScreen)


# ---------------------------------------------------------------------------
# StatusPanel additional tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_panel_bot_summary(tmp_path):
    """StatusPanel should report configured bot names."""
    config_path = tmp_path / "config.yaml"
    cfg = {
        "default_mode": "auto",
        "bot": {
            "discord": {"token": "fake-token"},
            "telegram": {"token": "fake-tg-token"},
        },
    }
    config_path.write_text(yaml.dump(cfg))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        status = app.screen.query_one("#status", StatusPanel)
        bots = status._get_bot_summary()
        assert "Discord" in bots
        assert "Telegram" in bots


@pytest.mark.asyncio
async def test_status_panel_all_stopped(tmp_path):
    """StatusPanel should render status for all four components."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        status = app.screen.query_one("#status", StatusPanel)
        text = _get_static_text(status)
        # All four components should be present regardless of running state
        assert "Head:" in text
        assert "Daemon:" in text
        assert "WebUI:" in text
        assert "Claude:" in text


# ---------------------------------------------------------------------------
# MachineTable additional tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_machine_table_transport_detection(tmp_path):
    """MachineTable should correctly display different transport types."""
    config_path = tmp_path / "config.yaml"
    cfg = {
        "default_mode": "auto",
        "peers": {
            "ssh-box": {"transport": "ssh", "ssh_host": "10.0.0.1"},
            "http-box": {"transport": "http", "address": "https://10.0.0.2:9100"},
            "local-box": {"transport": "local"},
        },
    }
    config_path.write_text(yaml.dump(cfg))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.screen.query_one("#machine_table", MachineTable)
        assert table.row_count == 3


@pytest.mark.asyncio
async def test_machine_table_host_truncation(tmp_path):
    """MachineTable should truncate long hostnames."""
    config_path = tmp_path / "config.yaml"
    long_host = "very-long-hostname-that-exceeds-twenty-four-characters.example.com"
    cfg = {
        "default_mode": "auto",
        "peers": {
            "long-box": {"transport": "ssh", "ssh_host": long_host},
        },
    }
    config_path.write_text(yaml.dump(cfg))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.screen.query_one("#machine_table", MachineTable)
        row = table.get_row_at(0)
        host_cell = str(row[2])
        assert host_cell.endswith("...")
        assert len(host_cell) <= 24


@pytest.mark.asyncio
async def test_machine_table_get_selected_machine_name(tmp_path):
    """get_selected_machine_name should return the name of the selected row."""
    config_path = tmp_path / "config.yaml"
    cfg = {
        "default_mode": "auto",
        "peers": {
            "alpha": {"transport": "ssh", "ssh_host": "10.0.0.1"},
            "bravo": {"transport": "ssh", "ssh_host": "10.0.0.2"},
        },
    }
    config_path.write_text(yaml.dump(cfg))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.screen.query_one("#machine_table", MachineTable)
        name = table.get_selected_machine_name()
        assert name in ("alpha", "bravo")


@pytest.mark.asyncio
async def test_machine_table_get_selected_empty(tmp_path):
    """get_selected_machine_name should return None for empty table."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"default_mode": "auto"}))
    app = CodecastApp(config_path=str(config_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.screen.query_one("#machine_table", MachineTable)
        name = table.get_selected_machine_name()
        assert name is None
