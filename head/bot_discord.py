"""
Discord Bot implementation for Remote Claude.

Uses discord.py (v2) with slash commands and message handling.
"""

import asyncio
import logging
from typing import Any, Optional

import discord
from discord.ext import commands

from .config import Config, DiscordConfig
from .ssh_manager import SSHManager
from .session_router import SessionRouter
from .daemon_client import DaemonClient
from .bot_base import BotBase
from .message_formatter import split_message

logger = logging.getLogger(__name__)


class DiscordBot(BotBase):
    """Discord bot implementation."""

    def __init__(
        self,
        ssh_manager: SSHManager,
        session_router: SessionRouter,
        daemon_client: DaemonClient,
        config: Config,
    ):
        super().__init__(ssh_manager, session_router, daemon_client, config)
        self.discord_config: Optional[DiscordConfig] = config.bot.discord

        if not self.discord_config:
            raise ValueError("Discord config not found in config.yaml")

        # Set up discord intents
        intents = discord.Intents.default()
        intents.message_content = True

        self.bot = commands.Bot(
            command_prefix="!",  # Prefix commands (not used, we use slash-style in messages)
            intents=intents,
            help_command=None,  # We provide our own help
        )

        # Store channel objects for sending messages
        self._channels: dict[str, discord.abc.Messageable] = {}
        # Store message objects for editing
        self._messages: dict[int, discord.Message] = {}

        self._setup_events()

    def _setup_events(self) -> None:
        """Register Discord event handlers."""

        @self.bot.event
        async def on_ready() -> None:
            logger.info(f"Discord bot logged in as {self.bot.user}")
            if self.bot.user:
                logger.info(f"Bot ID: {self.bot.user.id}")

        @self.bot.event
        async def on_message(message: discord.Message) -> None:
            # Ignore bot's own messages
            if message.author == self.bot.user:
                return

            # Ignore messages from other bots
            if message.author.bot:
                return

            # Check if channel is allowed
            if self.discord_config and self.discord_config.allowed_channels:
                if message.channel.id not in self.discord_config.allowed_channels:
                    return

            # Build channel ID
            channel_id = f"discord:{message.channel.id}"

            # Cache channel for sending
            self._channels[channel_id] = message.channel

            # Handle the input
            await self.handle_input(channel_id, message.content)

    def _get_channel_id(self, channel: discord.abc.Messageable) -> str:
        """Get our internal channel ID from a Discord channel."""
        if isinstance(channel, (discord.TextChannel, discord.DMChannel, discord.Thread)):
            return f"discord:{channel.id}"
        return f"discord:{id(channel)}"

    async def send_message(self, channel_id: str, text: str) -> Any:
        """Send a message to a Discord channel."""
        channel = self._channels.get(channel_id)
        if not channel:
            logger.warning(f"Channel not found: {channel_id}")
            return None

        # Split long messages
        chunks = split_message(text, max_len=2000)
        last_msg = None

        for chunk in chunks:
            try:
                last_msg = await channel.send(chunk)
            except discord.HTTPException as e:
                logger.error(f"Failed to send message: {e}")
                # Try sending without formatting if it fails
                try:
                    plain = chunk.replace("**", "").replace("`", "").replace("```", "")
                    last_msg = await channel.send(plain[:2000])
                except discord.HTTPException:
                    logger.error(f"Failed to send even plain message to {channel_id}")

        return last_msg

    async def edit_message(self, channel_id: str, message_obj: Any, text: str) -> None:
        """Edit an existing Discord message."""
        if not isinstance(message_obj, discord.Message):
            return

        try:
            # Truncate if too long for a single message edit
            if len(text) > 2000:
                text = text[:1997] + "..."

            await message_obj.edit(content=text)
        except discord.HTTPException as e:
            logger.warning(f"Failed to edit message: {e}")
            # If edit fails, try sending as new message
            try:
                channel = self._channels.get(channel_id)
                if channel:
                    await channel.send(text[:2000])
            except Exception:
                pass
        except discord.NotFound:
            # Message was deleted
            pass

    async def start(self) -> None:
        """Start the Discord bot."""
        if not self.discord_config:
            raise ValueError("Discord config not set")

        token = self.discord_config.token
        if not token:
            raise ValueError("Discord token is empty. Set DISCORD_TOKEN environment variable.")

        logger.info("Starting Discord bot...")
        await self.bot.start(token)

    async def stop(self) -> None:
        """Stop the Discord bot."""
        logger.info("Stopping Discord bot...")
        await self.bot.close()
