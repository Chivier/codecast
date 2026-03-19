"""Screen classes for the Codecast TUI."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, OptionList, Static
from textual.widgets.option_list import Option

from .widgets import MachineTable, StatusPanel

logger = logging.getLogger(__name__)

LOGO = r"""[bold cyan]
   ___          _                    _
  / __\___   __| | ___  ___ __ _ ___| |_
 / /  / _ \ / _` |/ _ \/ __/ _` / __| __|
/ /__| (_) | (_| |  __/ (_| (_| \__ \ |_
\____/\___/ \__,_|\___|\___\__,_|___/\__|[/bold cyan]"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_claude_cli() -> bool:
    """Return True if the claude CLI binary is on PATH."""
    return shutil.which("claude") is not None


def _check_daemon_running() -> tuple[bool, int | None]:
    """Check if a local daemon is running via port file + health check.

    Uses the same helpers as CLI and StatusPanel for consistency.
    """
    from head.cli import _daemon_healthy, _read_port_file

    port = _read_port_file()
    if port is None:
        return False, None
    return _daemon_healthy(port), port


def _load_config(config_path: str):
    """Try to load config; return None on failure."""
    try:
        from head.config import load_config_v2

        return load_config_v2(config_path)
    except Exception as exc:
        logger.warning("Failed to load config from %s: %s", config_path, exc)
        return None


# ---------------------------------------------------------------------------
# Setup Wizard
# ---------------------------------------------------------------------------

_WIZARD_OPTIONS = [
    Option("Start local daemon", id="start_daemon"),
    Option("Add a remote machine", id="add_machine"),
    Option("Configure Discord bot", id="config_discord"),
    Option("Configure Telegram bot", id="config_telegram"),
    Option("Skip setup", id="skip"),
]


class SetupWizardScreen(Screen):
    """First-run setup wizard shown when no config exists."""

    BINDINGS = [("q", "quit_app", "Quit")]

    def __init__(self, config_path: str, version: str = "") -> None:
        super().__init__()
        self.config_path = config_path
        self.version = version

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static(
                f"Welcome to Codecast! {self.version}\nNo configuration found. Starting setup wizard.\n",
                id="welcome",
            ),
            Static("What would you like to set up?", id="wizard_prompt"),
            OptionList(*_WIZARD_OPTIONS, id="wizard_menu"),
            id="wizard_container",
        )
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option.id
        if option_id == "skip":
            self.app.exit()
        elif option_id == "start_daemon":
            self.app.push_screen(StartDaemonScreen(self.config_path))
        elif option_id == "add_machine":
            self.app.push_screen(AddMachineScreen(self.config_path))
        elif option_id == "config_discord":
            self.app.push_screen(ConfigBotScreen(self.config_path, "discord"))
        elif option_id == "config_telegram":
            self.app.push_screen(ConfigBotScreen(self.config_path, "telegram"))

    def action_quit_app(self) -> None:
        self.app.exit()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


class DashboardScreen(Screen):
    """Main dashboard shown when a config already exists."""

    BINDINGS = [
        ("d", "toggle_daemon", "Daemon"),
        ("H", "start_head", "Head"),
        ("w", "start_webui", "WebUI"),
        ("a", "add_machine", "Add Machine"),
        ("s", "sessions", "Sessions"),
        ("x", "remove_machine", "Remove Machine"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("up", "cursor_up", "Up"),
        ("l", "open_machine", "Enter"),
        ("right", "open_machine", "Enter"),
        ("enter", "open_machine", "Enter"),
        ("escape", "quit_app", "Quit"),
        ("question_mark", "show_help", "Help"),
        ("q", "quit_app", "Quit"),
    ]

    def __init__(self, config_path: str, version: str = "") -> None:
        super().__init__()
        self.config_path = config_path
        self.version = version

    def compose(self) -> ComposeResult:
        yield Header()

        cfg = _load_config(self.config_path)
        machine_count = len(cfg.peers) if cfg else 0

        yield Vertical(
            Static(LOGO, id="logo"),
            Vertical(
                Static("[bold cyan]Status[/bold cyan]", id="status_panel_title"),
                StatusPanel(config_path=self.config_path, id="status"),
                id="status_panel_container",
            ),
            Vertical(
                Static(
                    f"[bold cyan]Machines[/bold cyan] [bold white]({machine_count} configured)[/bold white]",
                    id="machine_table_title",
                ),
                MachineTable(self.config_path, id="machine_table"),
                id="machine_table_container",
            ),
            id="dashboard_container",
        )
        yield Footer()

    def action_toggle_daemon(self) -> None:
        self.app.push_screen(StartDaemonScreen(self.config_path))

    def action_start_head(self) -> None:
        self.app.push_screen(StartHeadScreen(self.config_path))

    def action_start_webui(self) -> None:
        self.app.push_screen(StartWebUIScreen(self.config_path))

    def action_add_machine(self) -> None:
        self.app.push_screen(AddMachineScreen(self.config_path))

    def action_sessions(self) -> None:
        self.app.push_screen(SessionsScreen(self.config_path))

    def action_remove_machine(self) -> None:
        try:
            table = self.query_one("#machine_table", MachineTable)
        except Exception:
            return
        name = table.get_selected_machine_name()
        if not name:
            self.notify("No machine selected.", severity="warning")
            return
        try:
            from head.config import load_config_v2, remove_machine_from_config

            cfg = load_config_v2(self.config_path)
            remove_machine_from_config(cfg, name)
            table.refresh_machines()
            title = self.query_one("#machine_table_title", Static)
            title.update(f"[bold cyan]Machines[/bold cyan] [bold white]({table.machine_count} configured)[/bold white]")
            self.notify(f"Removed machine: {name}")
        except Exception as exc:
            self.notify(f"Failed to remove machine: {exc}", severity="error")

    def action_cursor_down(self) -> None:
        try:
            table = self.query_one("#machine_table", MachineTable)
            table.action_cursor_down()
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        try:
            table = self.query_one("#machine_table", MachineTable)
            table.action_cursor_up()
        except Exception:
            pass

    def action_open_machine(self) -> None:
        """Open sessions screen filtered to the selected machine."""
        try:
            table = self.query_one("#machine_table", MachineTable)
        except Exception:
            return
        name = table.get_selected_machine_name()
        if name:
            self.app.push_screen(SessionsScreen(self.config_path, filter_machine=name))
        else:
            self.app.push_screen(SessionsScreen(self.config_path))

    def on_screen_resume(self) -> None:
        """Refresh status panel and machine table when returning from a sub-screen."""
        try:
            self.query_one("#status", StatusPanel).refresh_status()
        except Exception:
            pass
        try:
            table = self.query_one("#machine_table", MachineTable)
            table.refresh_machines()
            title = self.query_one("#machine_table_title", Static)
            title.update(f"[bold cyan]Machines[/bold cyan] [bold white]({table.machine_count} configured)[/bold white]")
        except Exception:
            pass

    def action_show_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_quit_app(self) -> None:
        self.app.exit()


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------


class HelpScreen(Screen):
    """Help screen showing available keyboard shortcuts and commands."""

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        help_text = (
            "[bold]Codecast TUI — Help[/bold]\n"
            "\n"
            "[bold]Dashboard shortcuts:[/bold]\n"
            "  [cyan]d[/cyan]  Start / stop the local daemon\n"
            "  [cyan]H[/cyan]  Start / stop the head node (Discord/Telegram/Lark bots)\n"
            "  [cyan]w[/cyan]  Start / stop the web UI\n"
            "  [cyan]a[/cyan]  Add a new machine\n"
            "  [cyan]x[/cyan]  Remove selected machine\n"
            "  [cyan]s[/cyan]  View active sessions\n"
            "  [cyan]?[/cyan]  Show this help screen\n"
            "  [cyan]q[/cyan]  Quit\n"
            "\n"
            "[bold]Navigation:[/bold]\n"
            "  [cyan]j / ↓[/cyan]     Move cursor down\n"
            "  [cyan]k / ↑[/cyan]     Move cursor up\n"
            "  [cyan]l / → / Enter[/cyan]  Open machine sessions\n"
            "  [cyan]h / ← / Esc[/cyan]   Go back\n"
            "\n"
            "[bold]Sessions view:[/bold]\n"
            "  [cyan]t[/cyan]         Toggle sort (newest/oldest)\n"
            "  [cyan]r / Del[/cyan]   Remove selected session\n"
            "\n"
            "[bold]CLI equivalents:[/bold]\n"
            "  codecast start       Start the daemon\n"
            "  codecast stop        Stop the daemon\n"
            "  codecast head start  Start the head node\n"
            "  codecast status      Show component status\n"
            "  codecast peers       List configured machines\n"
            "  codecast sessions    List active sessions\n"
        )
        yield Vertical(
            Static(help_text, id="help_text"),
            id="head_container",
        )
        yield Footer()

    def action_go_back(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Start / Stop Head Node
# ---------------------------------------------------------------------------


class StartHeadScreen(Screen):
    """Screen for starting or stopping the head node."""

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, config_path: str) -> None:
        super().__init__()
        self.config_path = config_path

    def compose(self) -> ComposeResult:
        from head.cli import _HEAD_PID_FILE, _pid_alive, _read_pid_file

        yield Header()

        head_pid = _read_pid_file(_HEAD_PID_FILE)
        head_running = head_pid is not None and _pid_alive(head_pid)

        cfg = _load_config(self.config_path)

        # Build config summary
        bots_configured: list[str] = []
        if cfg and cfg.bot:
            if cfg.bot.discord and getattr(cfg.bot.discord, "token", None):
                bots_configured.append("Discord")
            if cfg.bot.telegram and getattr(cfg.bot.telegram, "token", None):
                bots_configured.append("Telegram")
            if getattr(cfg.bot, "lark", None) and getattr(cfg.bot.lark, "app_id", None):
                bots_configured.append("Lark")

        peers = getattr(cfg, "peers", {}) or {} if cfg else {}

        summary_lines = []
        if head_running:
            summary_lines.append(f"Head node is [bold green]● running[/bold green] [dim](pid={head_pid})[/dim]")
        else:
            summary_lines.append("Head node is [bold red]○ stopped[/bold red]")
        summary_lines.append(f"[bold]Config:[/bold]   {self.config_path}")
        summary_lines.append(
            f"[bold]Bots:[/bold]     {', '.join(bots_configured) if bots_configured else '[dim]none[/dim]'}"
        )
        summary_lines.append(f"[bold]Machines:[/bold] {len(peers)} configured")

        options: list[Option] = []
        if head_running:
            options.append(Option("Stop head node", id="stop"))
        elif bots_configured:
            options.append(Option("Start head node", id="start"))
        options.append(Option("Configure Discord token", id="config_discord"))
        options.append(Option("Configure Telegram token", id="config_telegram"))
        options.append(Option("Back", id="back"))

        yield Vertical(
            Static("\n".join(summary_lines), id="head_status"),
            OptionList(*options, id="head_menu"),
            id="head_container",
        )
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option.id
        if option_id == "back":
            self.app.pop_screen()
        elif option_id == "start":
            self._start_head()
        elif option_id == "stop":
            self._stop_head()
        elif option_id == "config_discord":
            self.app.push_screen(ConfigBotScreen(self.config_path, "discord"))
        elif option_id == "config_telegram":
            self.app.push_screen(ConfigBotScreen(self.config_path, "telegram"))

    def _start_head(self) -> None:
        try:
            subprocess.Popen(
                [sys.executable, "-m", "head.cli", "head", "start", "-y", "-c", self.config_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.notify("Head node starting...")
        except Exception as exc:
            self.notify(f"Failed to start head: {exc}")
        self.app.pop_screen()

    def _stop_head(self) -> None:
        import signal

        from head.cli import _HEAD_PID_FILE, _pid_alive, _read_pid_file

        pid = _read_pid_file(_HEAD_PID_FILE)
        if pid is not None and _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
                self.notify("Head node stopped.")
            except ProcessLookupError:
                self.notify("Head node already stopped.")
            _HEAD_PID_FILE.unlink(missing_ok=True)
        else:
            self.notify("Head node is not running.")
        self.app.pop_screen()

    def action_go_back(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Start / Stop Daemon
# ---------------------------------------------------------------------------


class StartDaemonScreen(Screen):
    """Screen for starting or stopping the local daemon."""

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, config_path: str) -> None:
        super().__init__()
        self.config_path = config_path

    def compose(self) -> ComposeResult:
        from head.cli import _DAEMON_PID_FILE, _pid_alive, _read_pid_file

        yield Header()
        daemon_running, daemon_port = _check_daemon_running()
        daemon_pid = _read_pid_file(_DAEMON_PID_FILE)
        claude_available = _check_claude_cli()

        if daemon_running:
            pid_part = f" [dim](pid={daemon_pid})[/dim]" if daemon_pid and _pid_alive(daemon_pid) else ""
            msg = (
                f"Daemon is [bold green]● running[/bold green] on port [bold white]{daemon_port}[/bold white]{pid_part}"
            )
        elif not claude_available:
            msg = "[bold red]✗[/bold red] Claude CLI not found on PATH.\nInstall Claude CLI first to run the daemon."
        else:
            msg = "Daemon is [bold red]○ stopped[/bold red]. Claude CLI is [green]available[/green]."

        options: list[Option] = []
        if daemon_running:
            options.append(Option("Stop daemon", id="stop"))
            options.append(Option("Restart daemon", id="restart"))
        elif claude_available:
            options.append(Option("Start daemon", id="start"))
        options.append(Option("Back", id="back"))

        yield Vertical(
            Static(msg, id="daemon_status"),
            OptionList(*options, id="daemon_menu"),
            id="daemon_container",
        )
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option.id
        if option_id == "back":
            self.app.pop_screen()
        elif option_id == "start":
            self._start_daemon()
        elif option_id == "stop":
            self._stop_daemon()
        elif option_id == "restart":
            self._stop_daemon_only()
            self._start_daemon()

    def _start_daemon(self) -> None:
        """Start daemon as subprocess (non-blocking)."""
        try:
            cmd = [sys.executable, "-m", "head.cli", "start"]
            if self.config_path:
                cmd.extend(["-c", self.config_path])
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.notify("Daemon starting...")
        except Exception as exc:
            self.notify(f"Failed to start daemon: {exc}")
        self.app.pop_screen()

    def _stop_daemon_only(self) -> None:
        """Stop daemon without popping screen (for restart)."""
        import signal as sig

        from head.cli import _DAEMON_PID_FILE, _PORT_FILE, _pid_alive, _read_pid_file

        daemon_pid = _read_pid_file(_DAEMON_PID_FILE)
        if daemon_pid is not None and _pid_alive(daemon_pid):
            try:
                os.kill(daemon_pid, sig.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            try:
                subprocess.run(["pkill", "-f", "codecast-daemon"], check=False)
            except FileNotFoundError:
                pass
        _DAEMON_PID_FILE.unlink(missing_ok=True)
        _PORT_FILE.unlink(missing_ok=True)

    def _stop_daemon(self) -> None:
        """Stop daemon and return to dashboard."""
        self._stop_daemon_only()
        self.notify("Daemon stopped.")
        self.app.pop_screen()

    def action_go_back(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Add Machine
# ---------------------------------------------------------------------------


class AddMachineScreen(Screen):
    """Screen for adding a new machine (manual or SSH import)."""

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, config_path: str) -> None:
        super().__init__()
        self.config_path = config_path
        self._step = 0
        self._machine_name = ""
        self._transport = ""
        self._mode = ""  # "manual" or "ssh_import"

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static("Add a machine\n", id="add_machine_title"),
            Static("Choose method:", id="add_machine_prompt"),
            OptionList(
                Option("Manual entry", id="manual"),
                Option("Import from SSH config", id="ssh_import"),
                id="add_machine_method",
            ),
            id="add_machine_container",
        )
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option.id
        if option_id == "manual":
            self._mode = "manual"
            self._step = 1
            self._switch_to_manual_input()
        elif option_id == "ssh_import":
            self._mode = "ssh_import"
            self._show_ssh_hosts()
        elif option_id and option_id.startswith("ssh_host:"):
            self._import_ssh_host(option_id[len("ssh_host:") :])

    def _switch_to_manual_input(self) -> None:
        """Replace option list with manual input fields."""
        prompt = self.query_one("#add_machine_prompt", Static)
        prompt.update("Enter machine name:")
        try:
            method_list = self.query_one("#add_machine_method", OptionList)
            method_list.remove()
        except Exception:
            pass
        container = self.query_one("#add_machine_container", Vertical)
        container.mount(Input(placeholder="e.g. my-server", id="machine_input"))

    def _show_ssh_hosts(self) -> None:
        """Show available SSH hosts from ~/.ssh/config."""
        try:
            from head.config import load_config_v2, parse_ssh_config

            ssh_entries = parse_ssh_config()
            cfg = load_config_v2(self.config_path) if Path(self.config_path).exists() else None
            existing = set((cfg.peers or {}).keys()) if cfg else set()
        except Exception:
            ssh_entries = []
            existing = set()

        # Filter out already-configured machines and deduplicate by name
        seen: set[str] = set()
        available: list = []
        for e in ssh_entries:
            if e.name not in existing and e.name not in seen:
                seen.add(e.name)
                available.append(e)

        prompt = self.query_one("#add_machine_prompt", Static)
        method_list = self.query_one("#add_machine_method", OptionList)

        if not available:
            prompt.update("No new SSH hosts found in ~/.ssh/config.")
            method_list.clear_options()
            return

        prompt.update(f"Select SSH host to import ({len(available)} available):")
        method_list.clear_options()
        for entry in available:
            host_info = entry.hostname or entry.name
            if entry.user:
                host_info = f"{entry.user}@{host_info}"
            method_list.add_option(Option(f"{entry.name} ({host_info})", id=f"ssh_host:{entry.name}"))

    def _import_ssh_host(self, host_name: str) -> None:
        """Import an SSH host from ssh config as a machine."""
        from head.config import Config, PeerConfig, load_config_v2, parse_ssh_config, save_config_v2

        ssh_entries = parse_ssh_config()
        entry = next((e for e in ssh_entries if e.name == host_name), None)
        if not entry:
            self.notify(f"SSH host '{host_name}' not found.", severity="error")
            self.app.pop_screen()
            return

        try:
            cfg = load_config_v2(self.config_path)
        except FileNotFoundError:
            cfg = Config()

        hostname = entry.hostname or entry.name
        # Check if this is a localhost machine
        try:
            from head.config import _is_localhost

            is_local = _is_localhost(hostname)
        except Exception:
            is_local = hostname in ("localhost", "127.0.0.1", "::1")

        if is_local:
            peer = PeerConfig(id=host_name, transport="local")
        else:
            peer = PeerConfig(
                id=host_name,
                transport="ssh",
                ssh_host=hostname,
                ssh_user=entry.user,
                proxy_jump=entry.proxy_jump,
            )

        cfg.peers[host_name] = peer
        Path(self.config_path).parent.mkdir(parents=True, exist_ok=True)
        save_config_v2(cfg, self.config_path)
        self.notify(f"Machine '{host_name}' imported from SSH config.")
        self.app.pop_screen()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if not value:
            return

        if self._step == 1:
            self._machine_name = value
            self._step = 2
            prompt = self.query_one("#add_machine_prompt", Static)
            prompt.update("Transport (http / ssh):")
            inp = self.query_one("#machine_input", Input)
            inp.value = ""
            inp.placeholder = "ssh"
        elif self._step == 2:
            self._transport = value if value in ("http", "ssh") else "ssh"
            self._step = 3
            prompt = self.query_one("#add_machine_prompt", Static)
            if self._transport == "http":
                prompt.update("Address (e.g. https://host:9100):")
            else:
                prompt.update("SSH host (e.g. user@host):")
            inp = self.query_one("#machine_input", Input)
            inp.value = ""
            inp.placeholder = ""
        elif self._step == 3:
            self._save_machine(value)
            self.notify(f"Machine '{self._machine_name}' added.")
            self.app.pop_screen()

    def _save_machine(self, address: str) -> None:
        from head.config import Config, PeerConfig, load_config_v2, save_config_v2

        try:
            cfg = load_config_v2(self.config_path)
        except FileNotFoundError:
            cfg = Config()

        if self._transport == "http":
            peer = PeerConfig(id=self._machine_name, transport="http", address=address)
        else:
            parts = address.split("@", 1)
            if len(parts) == 2:
                user, host = parts
            else:
                user, host = None, parts[0]
            peer = PeerConfig(
                id=self._machine_name,
                transport="ssh",
                ssh_host=host,
                ssh_user=user,
            )
        cfg.peers[self._machine_name] = peer
        Path(self.config_path).parent.mkdir(parents=True, exist_ok=True)
        save_config_v2(cfg, self.config_path)

    def action_go_back(self) -> None:
        self.app.pop_screen()


# Keep backward-compatible alias
AddPeerScreen = AddMachineScreen


# ---------------------------------------------------------------------------
# Configure Bot
# ---------------------------------------------------------------------------


_DISCORD_GUIDANCE = (
    "[bold]Discord Bot Setup[/bold]\n"
    "\n"
    "1. Go to [cyan]https://discord.com/developers/applications[/cyan]\n"
    "2. Click [bold]New Application[/bold] → name it (e.g. Codecast)\n"
    "3. Go to [bold]Bot[/bold] tab → click [bold]Reset Token[/bold] → copy the token\n"
    "4. Enable [bold]Message Content Intent[/bold] under Privileged Intents\n"
    "5. Go to [bold]OAuth2 → URL Generator[/bold] → select [cyan]bot[/cyan] scope\n"
    "6. Select permissions: Send Messages, Read Message History, Use Slash Commands\n"
    "7. Copy the generated URL and open it to invite the bot to your server\n"
)

_TELEGRAM_GUIDANCE = (
    "[bold]Telegram Bot Setup[/bold]\n"
    "\n"
    "1. Open Telegram and message [cyan]@BotFather[/cyan]\n"
    "2. Send [bold]/newbot[/bold] and follow the prompts to name your bot\n"
    "3. Copy the API token BotFather gives you (format: [dim]123456:ABC-DEF...[/dim])\n"
    "4. Optionally send [bold]/setcommands[/bold] to register bot commands\n"
)


class ConfigBotScreen(Screen):
    """Screen for configuring a bot (Discord or Telegram)."""

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, config_path: str, bot_type: str = "discord") -> None:
        super().__init__()
        self.config_path = config_path
        self.bot_type = bot_type

    def compose(self) -> ComposeResult:
        yield Header()
        guidance = _DISCORD_GUIDANCE if self.bot_type == "discord" else _TELEGRAM_GUIDANCE
        if self.bot_type == "discord":
            placeholder = "Paste Discord bot token (e.g. MTIz...)"
        else:
            placeholder = "Paste Telegram bot token (e.g. 123456:ABC-DEF...)"
        yield Vertical(
            Static(f"Configure {self.bot_type.capitalize()} bot\n", id="bot_title"),
            Static(guidance, id="bot_guidance"),
            Static(f"Enter {self.bot_type} bot token:", id="bot_prompt"),
            Input(placeholder=placeholder, password=True, id="bot_token_input"),
            id="bot_config_container",
        )
        yield Footer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        token = event.value.strip()
        if not token:
            return
        self._save_bot_token(token)
        self.notify(f"{self.bot_type.capitalize()} bot configured.")
        self.app.pop_screen()

    def _save_bot_token(self, token: str) -> None:
        from head.config import (
            Config,
            DiscordConfig,
            TelegramConfig,
            load_config_v2,
            save_config_v2,
        )

        try:
            cfg = load_config_v2(self.config_path)
        except FileNotFoundError:
            cfg = Config()

        if self.bot_type == "discord":
            cfg.bot.discord = DiscordConfig(token=token)
        else:
            cfg.bot.telegram = TelegramConfig(token=token)

        Path(self.config_path).parent.mkdir(parents=True, exist_ok=True)
        save_config_v2(cfg, self.config_path)

    def action_go_back(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


class SessionsScreen(Screen):
    """Screen for viewing sessions from the SessionRouter database."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("h", "go_back", "Back"),
        ("left", "go_back", "Back"),
        ("t", "toggle_sort", "Toggle sort"),
        ("r", "remove_session", "Remove"),
        ("delete", "remove_session", "Remove"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("up", "cursor_up", "Up"),
        ("l", "open_or_enter", "Enter"),
        ("right", "open_or_enter", "Enter"),
        ("enter", "open_or_enter", "Enter"),
    ]

    def __init__(self, config_path: str, filter_machine: str | None = None) -> None:
        super().__init__()
        self.config_path = config_path
        self._sort_descending = True  # newest first by default
        self._sessions: list = []
        self._row_session_map: dict[int, object] = {}  # row index -> Session
        self._row_machine_map: dict[int, str] = {}  # row index -> machine_id (header rows)
        self._filter_machine: str | None = filter_machine

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static("[bold cyan]Sessions[/bold cyan]\n", id="sessions_title"),
            DataTable(id="sessions_table"),
            Static("", id="sessions_info"),
            id="sessions_container",
        )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#sessions_table", DataTable)
        table.add_columns("Name", "Path", "Mode", "Status", "Created")
        table.cursor_type = "row"
        self._sessions = self._load_sessions()
        self._populate_sessions(table)

    def _populate_sessions(self, table: DataTable) -> None:
        table.clear()
        self._row_session_map.clear()
        self._row_machine_map.clear()
        info = self.query_one("#sessions_info", Static)
        title = self.query_one("#sessions_title", Static)

        sessions = self._sessions
        if self._filter_machine:
            sessions = [s for s in sessions if s.machine_id == self._filter_machine]
            title.update(
                f"[bold cyan]Sessions[/bold cyan] — [bold white]{self._filter_machine}[/bold white]"
                " [dim](← back)[/dim]\n"
            )
        else:
            title.update("[bold cyan]Sessions[/bold cyan]\n")

        if not sessions:
            info.update("[dim]No sessions found.[/dim]")
            return

        # Sort by created_at
        sessions_sorted = sorted(
            sessions,
            key=lambda s: s.created_at or "",
            reverse=self._sort_descending,
        )

        # Group by machine
        from collections import OrderedDict

        grouped: OrderedDict[str, list] = OrderedDict()
        for s in sessions_sorted:
            grouped.setdefault(s.machine_id, []).append(s)

        row_idx = 0
        for machine_id, machine_sessions in grouped.items():
            if not self._filter_machine:
                # Machine header row (only in all-machines view)
                table.add_row(
                    f"[bold cyan]▸ {machine_id}[/bold cyan]",
                    "",
                    "",
                    "",
                    "",
                    key=f"header_{machine_id}",
                )
                self._row_machine_map[row_idx] = machine_id
                row_idx += 1

            for s in machine_sessions:
                created = s.created_at[:16].replace("T", " ") if s.created_at else ""
                path_display = s.path if len(s.path) <= 30 else "..." + s.path[-27:]
                indent = "  " if not self._filter_machine else ""
                # Color-code status
                status = s.status
                if status == "active":
                    status_display = "[bold green]active[/bold green]"
                elif status == "detached":
                    status_display = "[yellow]detached[/yellow]"
                elif status == "destroyed":
                    status_display = "[red]destroyed[/red]"
                else:
                    status_display = f"[dim]{status}[/dim]"
                table.add_row(
                    f"{indent}[bold]{s.name or s.daemon_session_id[:8]}[/bold]",
                    f"[dim]{path_display}[/dim]",
                    f"[cyan]{s.mode}[/cyan]",
                    status_display,
                    f"[dim]{created}[/dim]",
                    key=f"session_{s.channel_id}",
                )
                self._row_session_map[row_idx] = s
                row_idx += 1

        sort_label = "newest first" if self._sort_descending else "oldest first"
        filter_info = f" | Machine: {self._filter_machine}" if self._filter_machine else ""
        info.update(f"[dim]{len(sessions)} session(s) | Sort: {sort_label} (t) | Remove (r/del){filter_info}[/dim]")

    def _load_sessions(self):
        """Load sessions from the SessionRouter SQLite database."""
        try:
            from head.session_router import SessionRouter

            candidates = [
                Path.home() / ".codecast" / "sessions.db",
                Path(__file__).parent.parent / "sessions.db",
            ]
            for db_path in candidates:
                if db_path.exists():
                    router = SessionRouter(str(db_path))
                    return router.list_sessions()
        except Exception as exc:
            logger.warning("Failed to load sessions: %s", exc)
        return []

    def _get_router(self):
        """Get a SessionRouter instance, or None."""
        try:
            from head.session_router import SessionRouter

            candidates = [
                Path.home() / ".codecast" / "sessions.db",
                Path(__file__).parent.parent / "sessions.db",
            ]
            for db_path in candidates:
                if db_path.exists():
                    return SessionRouter(str(db_path))
        except Exception:
            pass
        return None

    def action_toggle_sort(self) -> None:
        self._sort_descending = not self._sort_descending
        table = self.query_one("#sessions_table", DataTable)
        self._populate_sessions(table)

    def action_remove_session(self) -> None:
        table = self.query_one("#sessions_table", DataTable)
        if table.row_count == 0:
            return
        cursor_row = table.cursor_row
        session = self._row_session_map.get(cursor_row)
        if session is None:
            # Cursor is on a machine header row
            self.notify("Select a session row to remove.", severity="warning")
            return
        router = self._get_router()
        if router:
            router.destroy(session.channel_id)
            self._sessions = [s for s in self._sessions if s.channel_id != session.channel_id]
            self._populate_sessions(table)
            name = session.name or session.daemon_session_id[:8]
            self.notify(f"Removed session: {name}")
        else:
            self.notify("Cannot find session database.", severity="error")

    def action_cursor_down(self) -> None:
        try:
            table = self.query_one("#sessions_table", DataTable)
            table.action_cursor_down()
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        try:
            table = self.query_one("#sessions_table", DataTable)
            table.action_cursor_up()
        except Exception:
            pass

    def action_open_or_enter(self) -> None:
        """Open a machine's sessions when on a header row."""
        if self._filter_machine:
            return
        table = self.query_one("#sessions_table", DataTable)
        if table.row_count == 0:
            return
        cursor_row = table.cursor_row
        machine_id = self._row_machine_map.get(cursor_row)
        if machine_id:
            self._filter_machine = machine_id
            self._populate_sessions(table)

    def action_go_back(self) -> None:
        if self._filter_machine:
            # Go back to all-machines view
            self._filter_machine = None
            table = self.query_one("#sessions_table", DataTable)
            self._populate_sessions(table)
        else:
            self.app.pop_screen()


# ---------------------------------------------------------------------------
# Start / Stop WebUI
# ---------------------------------------------------------------------------


class StartWebUIScreen(Screen):
    """Screen for starting or stopping the WebUI."""

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, config_path: str) -> None:
        super().__init__()
        self.config_path = config_path

    def compose(self) -> ComposeResult:
        from head.cli import _WEBUI_PID_FILE, _WEBUI_PORT_FILE, _pid_alive, _read_pid_file

        yield Header()

        webui_pid = _read_pid_file(_WEBUI_PID_FILE)
        webui_port = _read_pid_file(_WEBUI_PORT_FILE)
        webui_running = webui_pid is not None and _pid_alive(webui_pid)

        if webui_running:
            msg = (
                f"WebUI is [bold green]● running[/bold green]"
                f" on [bold white]http://127.0.0.1:{webui_port}[/bold white]"
                f" [dim](pid={webui_pid})[/dim]"
            )
        else:
            msg = "WebUI is [bold red]○ stopped[/bold red]"

        options: list[Option] = []
        if webui_running:
            options.append(Option("Stop WebUI", id="stop"))
        else:
            options.append(Option("Start WebUI", id="start"))
        options.append(Option("Back", id="back"))

        yield Vertical(
            Static(msg, id="webui_status"),
            OptionList(*options, id="webui_menu"),
            id="webui_container",
        )
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option.id
        if option_id == "back":
            self.app.pop_screen()
        elif option_id == "start":
            self._start_webui()
        elif option_id == "stop":
            self._stop_webui()

    def _start_webui(self) -> None:
        try:
            cmd = [sys.executable, "-m", "head.cli", "webui", "start"]
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.notify("WebUI starting...")
        except Exception as exc:
            self.notify(f"Failed to start WebUI: {exc}")
        self.app.pop_screen()

    def _stop_webui(self) -> None:
        from head.cli import _webui_stop

        try:
            _webui_stop()
            self.notify("WebUI stopped.")
        except Exception as exc:
            self.notify(f"Failed to stop WebUI: {exc}")
        self.app.pop_screen()

    def action_go_back(self) -> None:
        self.app.pop_screen()
