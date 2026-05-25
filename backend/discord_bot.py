"""
Discord Bot — Agentop Agent Interface
======================================
Talk to your Agentop agents via Discord, like NetworkChuck's OpenClaw setup.

Architecture:
    Discord message → Bot → POST /chat (Lex router) → Agent → Response → Discord reply

Usage:
    python -m backend.discord_bot                # Standalone
    # Or import and start alongside FastAPI:
    from backend.discord_bot import start_bot
    asyncio.create_task(start_bot())

Required env vars:
    DISCORD_BOT_TOKEN       — Bot token from discord.com/developers
    DISCORD_CHANNEL_IDS     — Comma-separated channel IDs to listen in (optional, all if empty)
    AGENTOP_API_URL         — Backend URL (default: http://localhost:8000)

IMPORTANT — MESSAGE_CONTENT PRIVILEGED INTENT:
    If the bot is connected but not responding to messages, you must enable the
    "Message Content Intent" in Discord Developer Portal:
    1. Go to https://discord.com/developers/applications
    2. Select your bot application → Bot tab
    3. Under "Privileged Gateway Intents", enable "MESSAGE CONTENT INTENT"
    4. Save and restart the bot.
    Without this, Discord sends all message.content as empty strings (silent failure).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from backend.auth import build_auth_headers

# Load .env if present (needed for standalone mode)
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    from dotenv import load_dotenv

    load_dotenv(_env_path)

try:
    import discord
    from discord import Intents, Message
    from discord import app_commands

    HAS_DISCORD = True
except ImportError:
    discord = None  # type: ignore[assignment]
    Intents = None  # type: ignore[assignment,misc]
    Message = None  # type: ignore[assignment,misc]
    app_commands = None  # type: ignore[assignment]
    HAS_DISCORD = False

try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    HAS_HTTPX = False

logger = logging.getLogger("agentop.discord")

# ---------------------------------------------------------------------------
# Singleton lock — prevent multiple bot instances
# ---------------------------------------------------------------------------
_PID_FILE = Path(__file__).resolve().parent.parent / ".discord_bot.pid"


def _acquire_lock() -> bool:
    """Prevent multiple bot instances by writing a PID file."""
    if _PID_FILE.exists():
        try:
            old_pid = int(_PID_FILE.read_text().strip())
            # Check if that process is still alive
            os.kill(old_pid, 0)
            logger.error(f"Another bot instance is running (PID {old_pid}). Kill it first or delete {_PID_FILE}")
            return False
        except (ProcessLookupError, ValueError):
            # Old process is dead — stale PID file
            pass
    _PID_FILE.write_text(str(os.getpid()))
    return True


def _release_lock() -> None:
    """Remove PID file on shutdown."""
    try:
        if _PID_FILE.exists() and _PID_FILE.read_text().strip() == str(os.getpid()):
            _PID_FILE.unlink()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DISCORD_BOT_TOKEN: str = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_IDS: list[int] = [
    int(cid.strip()) for cid in os.getenv("DISCORD_CHANNEL_IDS", "").split(",") if cid.strip().isdigit()
]
AGENTOP_API_URL: str = os.getenv("AGENTOP_API_URL", "http://localhost:8000")
MAX_DISCORD_LENGTH: int = 2000  # Discord message limit
BOT_PREFIX: str = os.getenv("DISCORD_BOT_PREFIX", "!")
ALLOWED_ROLE_IDS: list[int] = [
    int(rid.strip()) for rid in os.getenv("DISCORD_ALLOWED_ROLES", "").split(",") if rid.strip().isdigit()
]
# Security alert channel — set DISCORD_SECURITY_CHANNEL_ID in .env
SECURITY_CHANNEL_ID: int | None = (
    int(os.getenv("DISCORD_SECURITY_CHANNEL_ID", "").strip())
    if os.getenv("DISCORD_SECURITY_CHANNEL_ID", "").strip().isdigit()
    else None
)
ALERT_POLL_INTERVAL: int = int(os.getenv("DISCORD_ALERT_POLL_SECONDS", "30"))

# News intel channel — auto-created on startup if not found
NEWS_CHANNEL_NAME: str = os.getenv("DISCORD_NEWS_CHANNEL_NAME", "news-intel")
NEWS_CHANNEL_ID: int | None = (
    int(os.getenv("DISCORD_NEWS_CHANNEL_ID", "").strip())
    if os.getenv("DISCORD_NEWS_CHANNEL_ID", "").strip().isdigit()
    else None
)
NEWS_POLL_INTERVAL: int = int(os.getenv("DISCORD_NEWS_POLL_SECONDS", "21600"))  # 6 hours

# Content report channel — receives daily AI optimization reports for @lexmakesit
CONTENT_CHANNEL_NAME: str = os.getenv("DISCORD_CONTENT_CHANNEL_NAME", "content-report")
CONTENT_CHANNEL_ID: int | None = (
    int(os.getenv("DISCORD_CONTENT_CHANNEL_ID", "").strip())
    if os.getenv("DISCORD_CONTENT_CHANNEL_ID", "").strip().isdigit()
    else None
)
CONTENT_REPORT_PATH = (
    Path(__file__).resolve().parent.parent / "content_creation_pack" / "carousel_queue" / "optimization_report.md"
)
CONTENT_POLL_INTERVAL: int = int(os.getenv("DISCORD_CONTENT_POLL_SECONDS", "3600"))  # 1 hour

# Comment farm channel — engagement drafts for target creators
COMMENT_FARM_CHANNEL_NAME: str = os.getenv("DISCORD_COMMENT_FARM_CHANNEL_NAME", "comment-farm")
COMMENT_FARM_CHANNEL_ID: int | None = (
    int(os.getenv("DISCORD_COMMENT_FARM_CHANNEL_ID", "").strip())
    if os.getenv("DISCORD_COMMENT_FARM_CHANNEL_ID", "").strip().isdigit()
    else None
)
COMMENT_FARM_PATH = Path(__file__).resolve().parent.parent / "content_creation_pack" / "carousel_queue"

# Agent shortcuts — type !devops, !soul, !security etc.
AGENT_ALIASES: dict[str, str] = {
    "soul": "soul_core",
    "devops": "devops_agent",
    "monitor": "monitor_agent",
    "security": "security_agent",
    "code": "code_review_agent",
    "data": "data_agent",
    "cs": "cs_agent",
    "it": "it_agent",
    "knowledge": "knowledge_agent",
    "gsd": "gsd_agent",
    "healer": "self_healer_agent",
    "comms": "comms_agent",
}


# ---------------------------------------------------------------------------
# Discord Client
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Durable Discord Post History
# ---------------------------------------------------------------------------
# Orchad-readable record of everything the bot posts to Discord channels.
# Kept as a JSON-lines file so it survives restarts and is easy to query.

_DISCORD_POST_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "agents" / "discord_post_history.jsonl"


def _log_discord_post(record: dict) -> None:
    """Append a structured record of a Discord channel send to the durable log."""
    import datetime as _dt

    try:
        _DISCORD_POST_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record.setdefault("logged_at", _dt.datetime.utcnow().isoformat() + "Z")
        with _DISCORD_POST_LOG_PATH.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception as _exc:
        logger.warning(f"[DiscordPostLog] Failed to write record: {_exc}")


def get_discord_post_history(
    event_type: str | None = None,
    channel_name: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return recent Discord post records filtered by event_type and/or channel_name."""
    if not _DISCORD_POST_LOG_PATH.exists():
        return []
    try:
        lines = _DISCORD_POST_LOG_PATH.read_text().splitlines()
        records = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if event_type and rec.get("event_type") != event_type:
                continue
            if channel_name and rec.get("channel_name") != channel_name:
                continue
            records.append(rec)
            if len(records) >= limit:
                break
        return records
    except Exception as _exc:
        logger.warning(f"[DiscordPostLog] Failed to read history: {_exc}")
        return []


_ClientBase = discord.Client if HAS_DISCORD else object  # type: ignore[union-attr]


class AgentopBot(_ClientBase):  # type: ignore[misc, valid-type]
    """Discord bot that routes messages to Agentop agents."""

    def __init__(self) -> None:
        intents = Intents.default()  # type: ignore[union-attr]
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)  # type: ignore[union-attr]
        self._http_client: Any = None
        self._conversation_agents: dict[int, str] = {}  # channel_id → last agent
        self._rate_limits: dict[int, float] = {}  # user_id → last msg time
        self._rate_limit_seconds: float = 2.0
        self._handled_messages: set[int] = set()  # dedup guard: message IDs already processed
        self._news_channel_id: int | None = NEWS_CHANNEL_ID  # resolved on ready
        self._delivered_news_ids: set[str] = self._load_delivered_news_ids()  # dedup for news delivery
        self._content_channel_id: int | None = CONTENT_CHANNEL_ID  # resolved on ready
        self._last_content_report_mtime: float = 0.0  # track report file changes
        self._empty_content_warned: bool = False  # warn once about MESSAGE_CONTENT intent
        self._comment_farm_channel_id: int | None = COMMENT_FARM_CHANNEL_ID  # resolved on ready
        self._register_slash_commands()

    def _register_slash_commands(self) -> None:
        """Register all /slash commands on the CommandTree."""

        @self.tree.command(name="ask", description="Ask any Agentop agent a question (auto-routes)")
        @app_commands.describe(message="Your question or task")  # type: ignore[union-attr]
        async def slash_ask(interaction: Any, message: str) -> None:
            await interaction.response.defer(thinking=True)
            await self._handle_chat_interaction(interaction, message, agent_id="auto")

        @self.tree.command(name="soul", description="Reflect on goals, trust, or system health")
        @app_commands.describe(message="Your question")  # type: ignore[union-attr]
        async def slash_soul(interaction: Any, message: str) -> None:
            await interaction.response.defer(thinking=True)
            await self._handle_chat_interaction(interaction, message, agent_id="soul_core")

        @self.tree.command(name="devops", description="CI/CD, git, deployment questions")
        @app_commands.describe(message="Your question")  # type: ignore[union-attr]
        async def slash_devops(interaction: Any, message: str) -> None:
            await interaction.response.defer(thinking=True)
            await self._handle_chat_interaction(interaction, message, agent_id="devops_agent")

        @self.tree.command(name="security", description="CVE checks, secret scanning, vulnerability questions")
        @app_commands.describe(message="Your question")  # type: ignore[union-attr]
        async def slash_security(interaction: Any, message: str) -> None:
            await interaction.response.defer(thinking=True)
            await self._handle_chat_interaction(interaction, message, agent_id="security_agent")

        @self.tree.command(name="monitor", description="System health, logs, and metrics")
        @app_commands.describe(message="Your question")  # type: ignore[union-attr]
        async def slash_monitor(interaction: Any, message: str) -> None:
            await interaction.response.defer(thinking=True)
            await self._handle_chat_interaction(interaction, message, agent_id="monitor_agent")

        @self.tree.command(name="code", description="Code review, PR review, pattern enforcement")
        @app_commands.describe(message="Your question")  # type: ignore[union-attr]
        async def slash_code(interaction: Any, message: str) -> None:
            await interaction.response.defer(thinking=True)
            await self._handle_chat_interaction(interaction, message, agent_id="code_review_agent")

        @self.tree.command(name="knowledge", description="Search the Agentop knowledge base")
        @app_commands.describe(query="What to search for")  # type: ignore[union-attr]
        async def slash_knowledge(interaction: Any, query: str) -> None:
            await interaction.response.defer(thinking=True)
            await self._handle_chat_interaction(interaction, query, agent_id="knowledge_agent")

        @self.tree.command(name="data", description="ETL, schema, SQLite queries")
        @app_commands.describe(message="Your question")  # type: ignore[union-attr]
        async def slash_data(interaction: Any, message: str) -> None:
            await interaction.response.defer(thinking=True)
            await self._handle_chat_interaction(interaction, message, agent_id="data_agent")

        @self.tree.command(name="farm", description="Generate engagement comment drafts for an Instagram post")
        @app_commands.describe(url="Instagram post URL")  # type: ignore[union-attr]
        async def slash_farm(interaction: Any, url: str) -> None:
            await interaction.response.defer(thinking=True)
            # Re-use _cmd_farm but need a message-like object — create an interaction wrapper
            await self._handle_farm_interaction(interaction, url)

        @self.tree.command(name="news", description="Show latest AI & security news")
        @app_commands.describe(topic="Optional topic filter (e.g. deepseek, cybersecurity)")  # type: ignore[union-attr]
        async def slash_news(interaction: Any, topic: str = "") -> None:
            await interaction.response.defer(thinking=True)
            await self._handle_news_interaction(interaction, topic)

        @self.tree.command(name="status", description="Show Agentop system health")
        async def slash_status(interaction: Any) -> None:
            await interaction.response.defer(thinking=True)
            await self._handle_status_interaction(interaction)

        @self.tree.command(name="help", description="Show all available commands")
        async def slash_help(interaction: Any) -> None:
            embed = discord.Embed(  # type: ignore[union-attr]
                title="🤖 Agentop — Command Reference",
                description="Slash commands (/) or prefix commands (!). @mention me to chat freely.",
                color=0x00FFC8,
            )
            embed.add_field(
                name="💬 Chat agents",
                value="`/ask` `/soul` `/devops` `/security` `/monitor` `/code` `/knowledge` `/data`",
                inline=False,
            )
            embed.add_field(name="📲 Content", value="`/farm <url>` — Instagram comment drafts", inline=False)
            embed.add_field(name="📰 News", value="`/news [topic]` — AI & security news feed", inline=False)
            embed.add_field(name="📊 Status", value="`/status` — system health", inline=False)
            embed.add_field(
                name="⚡ Tip",
                value="@mention me anywhere to chat without a command prefix.",
                inline=False,
            )
            await interaction.response.send_message(embed=embed)

    async def setup_hook(self) -> None:
        self._http_client = httpx.AsyncClient(  # type: ignore[union-attr]
            timeout=120.0,
            headers=build_auth_headers(),
        )
        logger.info("Agentop Discord bot initialized")
        # Sync slash commands. Guild sync is instant (dev); global takes up to 1h on first run.
        # Set DISCORD_DEV_GUILD_ID in .env for instant registration during development.
        _dev_guild_id = os.getenv("DISCORD_DEV_GUILD_ID", "").strip()
        if _dev_guild_id.isdigit():
            _guild = discord.Object(id=int(_dev_guild_id))  # type: ignore[union-attr]
            self.tree.copy_global_to(guild=_guild)
            await self.tree.sync(guild=_guild)
            logger.info(f"Slash commands synced to dev guild {_dev_guild_id} (instant)")
        else:
            await self.tree.sync()
            logger.info("Slash commands synced globally (up to 1h to propagate)")
        # Start security alert poller if channel is configured
        if SECURITY_CHANNEL_ID:
            self.loop.create_task(self._security_alert_poller())
            logger.info(f"Security alert poller started → channel {SECURITY_CHANNEL_ID}")
        # Start news intel poller — channel resolved in on_ready after guilds load
        self.loop.create_task(self._news_intel_poller())
        # Start content report poller — posts daily AI optimization reports
        self.loop.create_task(self._content_report_poller())
        # Set up comment farm webhook URL for comment_farm.py cron script
        farm_webhook = os.getenv("DISCORD_COMMENT_FARM_WEBHOOK_URL", "")
        if farm_webhook:
            logger.info("[CommentFarm] Webhook URL configured for #comment-farm")

    async def close(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
        await super().close()

    async def on_ready(self) -> None:
        assert self.user is not None
        logger.info(f"Bot connected as {self.user} (ID: {self.user.id})")
        logger.info(f"Guilds: {[g.name for g in self.guilds]}")
        if DISCORD_CHANNEL_IDS:
            logger.info(f"Listening in channels: {DISCORD_CHANNEL_IDS}")
        else:
            logger.info("Listening in ALL channels (no filter)")
        # Warn clearly if MESSAGE_CONTENT intent may not be enabled
        intents = self._connection.intents  # type: ignore[attr-defined]
        if not getattr(intents, "message_content", False):
            logger.warning(
                "⚠️  MESSAGE_CONTENT INTENT IS OFF — bot will not see message text. "
                "Enable 'Message Content Intent' in Discord Developer Portal → "
                "https://discord.com/developers/applications → Bot → Privileged Gateway Intents"
            )
        await self.change_presence(
            activity=discord.Activity(  # type: ignore[union-attr]
                type=discord.ActivityType.listening,  # type: ignore[union-attr]
                name="your commands | !help",
            )
        )
        # Auto-create #news-intel channel if not already resolved
        if self._news_channel_id is None:
            await self._ensure_news_channel()
        # Auto-create #content-report channel if not already resolved
        if self._content_channel_id is None:
            await self._ensure_content_channel()
        # Setup #comment-farm channel and post intro
        await self._ensure_comment_farm_channel()

    async def on_message(self, message: Any) -> None:
        # Ignore own messages
        if message.author == self.user:
            return

        # Ignore bots
        if message.author.bot:
            return

        content = message.content.strip()
        if not content:
            # Warn once if we're consistently getting empty content from real users.
            # Root cause: MESSAGE_CONTENT privileged intent not enabled in Discord portal.
            if not self._empty_content_warned:
                self._empty_content_warned = True
                logger.warning(
                    "⚠️  Received message with empty content from %s in #%s. "
                    "If bot is not responding to ANY messages, enable 'Message Content Intent' at: "
                    "https://discord.com/developers/applications → Bot → Privileged Gateway Intents",
                    message.author,
                    getattr(message.channel, "name", message.channel.id),
                )
            return

        # Dedup guard — prevent double-processing same message
        if message.id in self._handled_messages:
            return
        self._handled_messages.add(message.id)
        # Keep set bounded (last 1000 messages)
        if len(self._handled_messages) > 1000:
            self._handled_messages = set(list(self._handled_messages)[-500:])

        # #comment-farm: auto-detect Instagram URLs dropped raw (no !farm prefix needed)
        # Bypass the DISCORD_CHANNEL_IDS filter for this channel so it always works.
        is_comment_farm = (
            self._comment_farm_channel_id is not None and message.channel.id == self._comment_farm_channel_id
        )
        if is_comment_farm:
            ig_url_match = re.search(r"https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[A-Za-z0-9_-]+/?", content)
            if ig_url_match and not content.startswith(BOT_PREFIX):
                await self._cmd_farm(message, ig_url_match.group(0))
                return

        # Channel filter — applied after comment-farm bypass above
        if DISCORD_CHANNEL_IDS and message.channel.id not in DISCORD_CHANNEL_IDS:
            logger.debug(
                f"[Bot] Ignored message in #{getattr(message.channel, 'name', message.channel.id)} "
                f"(not in DISCORD_CHANNEL_IDS). Add channel or clear DISCORD_CHANNEL_IDS to listen everywhere."
            )
            return

        # Role-based access control (if configured)
        if ALLOWED_ROLE_IDS and isinstance(message.author, discord.Member):  # type: ignore[union-attr]
            user_roles = {r.id for r in message.author.roles}
            if not user_roles & set(ALLOWED_ROLE_IDS):
                return

        # Rate limiting per user
        now = time.monotonic()
        last = self._rate_limits.get(message.author.id, 0.0)
        if now - last < self._rate_limit_seconds:
            return
        self._rate_limits[message.author.id] = now

        # --- Command routing ---
        if content.startswith(BOT_PREFIX):
            await self._handle_command(message, content[len(BOT_PREFIX) :])
        elif self.user and self.user.mentioned_in(message):
            # @mention the bot to talk
            clean = re.sub(r"<@!?\d+>", "", content).strip()
            if clean:
                await self._handle_chat(message, clean, agent_id="auto")

    # -------------------------------------------------------------------------
    # Security Alert Push — polls backend, delivers to #security channel
    # -------------------------------------------------------------------------

    async def _security_alert_poller(self) -> None:
        """
        Background loop: poll /security/alerts/pending every ALERT_POLL_INTERVAL
        seconds and send new alerts to the configured security channel.

        Runs forever while the bot is alive (Kubernetes keeps it up).
        """
        await self.wait_until_ready()
        channel = self.get_channel(SECURITY_CHANNEL_ID)  # type: ignore[arg-type]
        if channel is None:
            logger.warning(
                f"[SecurityPoller] Channel {SECURITY_CHANNEL_ID} not found. "
                "Check DISCORD_SECURITY_CHANNEL_ID and bot channel permissions."
            )
            return

        logger.info(f"[SecurityPoller] Active — posting to #{getattr(channel, 'name', SECURITY_CHANNEL_ID)}")

        while not self.is_closed():
            try:
                await self._fetch_and_deliver_alerts(channel)
            except Exception as exc:
                logger.warning(f"[SecurityPoller] Cycle error (non-fatal): {exc}")
            await asyncio.sleep(ALERT_POLL_INTERVAL)

    async def _fetch_and_deliver_alerts(self, channel: Any) -> None:
        """Fetch pending alerts from backend and send each to the security channel."""
        if not self._http_client:
            return

        resp = await self._http_client.get(f"{AGENTOP_API_URL}/security/alerts/pending")
        if resp.status_code != 200:
            return

        data = resp.json()
        alerts: list[dict] = data.get("alerts", [])
        if not alerts:
            return

        delivered_ids: list[str] = []
        for alert in alerts:
            try:
                embed = _format_alert_embed(alert)
                await channel.send(embed=embed)
                delivered_ids.append(alert.get("alert_id", ""))
                logger.info(f"[SecurityPoller] Delivered alert {alert.get('alert_id')} — {alert.get('severity')}")
                _log_discord_post({
                    "event_type": "DISCORD_ALERT_POSTED",
                    "channel_name": "security-alerts",
                    "channel_id": getattr(channel, "id", None),
                    "title": alert.get("message", alert.get("title", ""))[:200],
                    "severity": alert.get("severity", ""),
                    "alert_id": alert.get("alert_id", ""),
                })
            except Exception as exc:
                logger.warning(f"[SecurityPoller] Failed to send alert: {exc}")

        # Ack delivered alerts
        if delivered_ids:
            try:
                await self._http_client.post(
                    f"{AGENTOP_API_URL}/security/alerts/ack",
                    json={"alert_ids": [aid for aid in delivered_ids if aid]},
                )
            except Exception as exc:
                logger.warning(f"[SecurityPoller] Ack failed (non-fatal): {exc}")

    # -------------------------------------------------------------------------
    # News Intelligence Channel — auto-create + smart delivery
    # -------------------------------------------------------------------------

    async def _ensure_news_channel(self) -> None:
        """
        Find or create #news-intel (NEWS_CHANNEL_NAME) across all guilds.
        Sets self._news_channel_id to the first found/created channel.
        """
        for guild in self.guilds:
            # Try to find existing channel by name
            existing = discord.utils.get(  # type: ignore[union-attr]
                guild.text_channels, name=NEWS_CHANNEL_NAME
            )
            if existing:
                self._news_channel_id = existing.id
                logger.info(f"[NewsIntel] Found existing #{NEWS_CHANNEL_NAME} ({existing.id}) in {guild.name}")
                return

            # Create it
            try:
                topic = (
                    "AI & cybersecurity news intel — auto-updated every 10 min. "
                    "Sources: Google, Anthropic, OpenAI, DeepSeek, Qwen, ByteDance, "
                    "ModelScope, ArXiv, SecurityWeek, CISA + more. "
                    "🖥️ Software  ⚙️ Hardware  🔒 Security  📚 Research"
                )
                new_ch = await guild.create_text_channel(NEWS_CHANNEL_NAME, topic=topic)
                await new_ch.set_permissions(
                    guild.me,
                    read_messages=True,
                    send_messages=True,
                    embed_links=True,
                    read_message_history=True,
                )
                self._news_channel_id = new_ch.id
                logger.info(f"[NewsIntel] Created #{NEWS_CHANNEL_NAME} ({new_ch.id}) in {guild.name}")
                await new_ch.send(
                    embed=discord.Embed(  # type: ignore[union-attr]
                        title="📡 News Intel — Online",
                        description=(
                            "This channel receives automated AI & security news every 10 minutes.\n\n"
                            "**Category badges:**\n"
                            "🖥️ Software — model releases, APIs, frameworks\n"
                            "⚙️ Hardware — GPUs, chips, data center\n"
                            "🔒 Security — CVEs, breaches, advisories\n"
                            "📚 Research — ArXiv papers, benchmarks\n\n"
                            "Type `!news [topic]` anywhere to pull on demand."
                        ),
                        color=0x3B82F6,
                    )
                )
                return
            except discord.Forbidden:  # type: ignore[union-attr]
                logger.warning(
                    f"[NewsIntel] No Manage Channels permission in {guild.name} — "
                    "set DISCORD_NEWS_CHANNEL_ID manually or grant the bot permission."
                )

    # -------------------------------------------------------------------------
    # Content Report Channel — daily AI optimization report for @lexmakesit
    # -------------------------------------------------------------------------

    async def _ensure_content_channel(self) -> None:
        """Find or create #content-report across all guilds."""
        for guild in self.guilds:
            existing = discord.utils.get(  # type: ignore[union-attr]
                guild.text_channels, name=CONTENT_CHANNEL_NAME
            )
            if existing:
                self._content_channel_id = existing.id
                logger.info(f"[ContentReport] Found existing #{CONTENT_CHANNEL_NAME} ({existing.id}) in {guild.name}")
                return
            try:
                new_ch = await guild.create_text_channel(
                    CONTENT_CHANNEL_NAME,
                    topic=(
                        "Daily AI content optimization reports for @lexmakesit Instagram. "
                        "Engagement analytics, hook rewrites, posting recommendations — powered by local Ollama."
                    ),
                )
                await new_ch.set_permissions(
                    guild.me,
                    read_messages=True,
                    send_messages=True,
                    embed_links=True,
                    read_message_history=True,
                )
                self._content_channel_id = new_ch.id
                logger.info(f"[ContentReport] Created #{CONTENT_CHANNEL_NAME} ({new_ch.id}) in {guild.name}")
                await new_ch.send(
                    embed=discord.Embed(  # type: ignore[union-attr]
                        title="📊 Content Report — Online",
                        description=(
                            "This channel receives **daily AI content optimization reports** for @lexmakesit.\n\n"
                            "**What you'll see here:**\n"
                            "📈 Instagram post performance rankings\n"
                            "🎯 Hook rewrites for upcoming posts\n"
                            "💡 Engagement pattern insights\n"
                            "📋 Slide count and timing recommendations\n\n"
                            "*Reports generated daily at 9am by local Ollama (llama3.2)*"
                        ),
                        color=0x00FFC8,
                    )
                )
                return
            except discord.Forbidden:  # type: ignore[union-attr]
                logger.warning(
                    f"[ContentReport] No Manage Channels permission in {guild.name} — "
                    "set DISCORD_CONTENT_CHANNEL_ID manually or grant the bot permission."
                )

    async def _content_report_poller(self) -> None:
        """
        Background loop: checks if optimization_report.md has been updated,
        then posts a summary embed to #content-report.
        Polls every CONTENT_POLL_INTERVAL seconds (default 1h).
        """
        await self.wait_until_ready()
        await asyncio.sleep(10)  # Let on_ready channel setup finish
        logger.info(
            f"[ContentReport] Poller active — channel={self._content_channel_id}, interval={CONTENT_POLL_INTERVAL}s"
        )

        while not self.is_closed():
            try:
                await self._deliver_content_report()
            except Exception as exc:
                logger.warning(f"[ContentReport] Poller cycle error (non-fatal): {exc}")
            await asyncio.sleep(CONTENT_POLL_INTERVAL)

    async def _deliver_content_report(self) -> None:
        """Post a new optimization_report.md to #content-report if it's been updated."""
        if not self._content_channel_id:
            return
        if not CONTENT_REPORT_PATH.exists():
            return

        mtime = CONTENT_REPORT_PATH.stat().st_mtime
        if mtime <= self._last_content_report_mtime:
            return  # No new report

        channel = self.get_channel(self._content_channel_id)
        if channel is None:
            return

        try:
            text = CONTENT_REPORT_PATH.read_text()
            embed = _format_content_report_embed(text)
            await channel.send(embed=embed)
            self._last_content_report_mtime = mtime
            logger.info("[ContentReport] Posted new optimization report to #content-report")
            _log_discord_post({
                "event_type": "DISCORD_CONTENT_REPORT_POSTED",
                "channel_name": CONTENT_CHANNEL_NAME,
                "channel_id": self._content_channel_id,
                "title": "Content Optimization Report",
                "preview": text[:200],
            })
        except Exception as exc:
            logger.warning(f"[ContentReport] Failed to post report: {exc}")

    # -------------------------------------------------------------------------
    # Comment Farm Channel — engagement drafts for target creators
    # -------------------------------------------------------------------------

    async def _ensure_comment_farm_channel(self) -> None:
        """Find or create #comment-farm across all guilds."""
        # If ID is hardcoded in env, use it directly
        if COMMENT_FARM_CHANNEL_ID:
            ch = self.get_channel(COMMENT_FARM_CHANNEL_ID)
            if ch:
                self._comment_farm_channel_id = COMMENT_FARM_CHANNEL_ID
                logger.info(f"[CommentFarm] Using channel from env ID ({COMMENT_FARM_CHANNEL_ID})")
                await self._post_farm_intro(ch)
                return
            else:
                logger.warning(
                    f"[CommentFarm] get_channel({COMMENT_FARM_CHANNEL_ID}) returned None — checking guild channels"
                )
        for guild in self.guilds:
            logger.info(f"[CommentFarm] Guild '{guild.name}' channels: {[c.name for c in guild.text_channels]}")
            existing = discord.utils.get(  # type: ignore[union-attr]
                guild.text_channels, name=COMMENT_FARM_CHANNEL_NAME
            )
            if existing:
                self._comment_farm_channel_id = existing.id
                logger.info(f"[CommentFarm] Found #{COMMENT_FARM_CHANNEL_NAME} ({existing.id})")
                await self._post_farm_intro(existing)
                return
            try:
                new_ch = await guild.create_text_channel(
                    COMMENT_FARM_CHANNEL_NAME,
                    topic=(
                        "Engagement drafts for target creators. "
                        "Use !farm <instagram_url> to get instant comment drafts for any post. "
                        "New post alerts appear here automatically."
                    ),
                )
                await new_ch.set_permissions(
                    guild.me,
                    read_messages=True,
                    send_messages=True,
                    embed_links=True,
                    read_message_history=True,
                )
                self._comment_farm_channel_id = new_ch.id
                logger.info(f"[CommentFarm] Created #{COMMENT_FARM_CHANNEL_NAME} ({new_ch.id})")
                await self._post_farm_intro(new_ch)
                return
            except discord.Forbidden:  # type: ignore[union-attr]
                logger.warning(f"[CommentFarm] No Manage Channels permission in {guild.name}")

    async def _post_farm_intro(self, channel: Any) -> None:
        """Post the creator list and instructions to #comment-farm (once per session)."""
        try:
            await channel.send(embed=await self._build_creator_list_embed())
            await channel.send(
                embed=discord.Embed(  # type: ignore[union-attr]
                    title="💬 Comment Farm — Ready",
                    description=(
                        "**How to use:**\n"
                        f"`{BOT_PREFIX}farm <instagram_post_url>` — instant comment drafts\n\n"
                        "**Strategy:**\n"
                        "• Comment within **30 min** of a post going live\n"
                        "• Target accounts with **10k–200k** followers (not mega accounts)\n"
                        "• Aim for **5-10 quality comments/day**\n"
                        "• Reply to replies — threads get more visibility\n\n"
                        "*New post alerts will appear here automatically when detected.*"
                    ),
                    color=0x00FFC8,
                )
            )
        except Exception as exc:
            logger.warning(f"[CommentFarm] Could not post intro: {exc}")

    async def _build_creator_list_embed(self) -> Any:
        """Build an embed listing all tracked target creators."""
        try:
            accounts = json.loads((COMMENT_FARM_PATH / "target_accounts.json").read_text())
            active = [a for a in accounts if a.get("active")]
            lines = [f"• **[@{a['handle']}]({a['profile_url']})** — {a.get('note', '')}" for a in active]
            return discord.Embed(  # type: ignore[union-attr]
                title="👀 Tracked Creators (9)",
                description="\n".join(lines),
                color=0x7C3AED,
            )
        except Exception:
            return discord.Embed(title="👀 Tracked Creators", description="See target_accounts.json", color=0x7C3AED)  # type: ignore[union-attr]

    async def _cmd_farm(self, message: Any, url: str) -> None:
        """!farm <instagram_url> — generate comment drafts for a post."""
        import re as _re
        import subprocess

        if not url:
            await message.reply(
                f"**Usage:** `{BOT_PREFIX}farm <instagram_post_url>`\n"
                "Example: `!farm https://instagram.com/p/ABC123/`\n\n"
                "Posts instant comment drafts to this channel."
            )
            return

        # Validate it looks like an Instagram URL
        if "instagram.com" not in url:
            await message.reply("❌ That doesn't look like an Instagram URL.")
            return

        async with message.channel.typing():
            try:
                # Run comment_farm.py in subprocess with the URL
                farm_script = str(COMMENT_FARM_PATH.parent / "comment_farm.py")
                result = await self.loop.run_in_executor(
                    None,
                    lambda: subprocess.run(
                        ["python3", farm_script, "--post", url],
                        capture_output=True,
                        text=True,
                        timeout=120,
                        env={**os.environ},
                    ),
                )
                output = result.stdout + result.stderr

                # If webhook is configured, comment_farm.py already posted to Discord
                webhook = os.getenv("DISCORD_COMMENT_FARM_WEBHOOK_URL", "")
                if webhook:
                    await message.reply("✅ Comment drafts posted to **#comment-farm**")
                    return

                # Otherwise parse the output and post here
                lines = output.strip().split("\n")
                draft_lines = [line for line in lines if _re.match(r"^\d+\.", line.strip())]
                if draft_lines:
                    # Extract handle from URL
                    handle_match = _re.search(r"@(\w[\w.]+)", output)
                    handle = handle_match.group(1) if handle_match else "creator"

                    embed = discord.Embed(  # type: ignore[union-attr]
                        title=f"💬 Comment drafts for @{handle}",
                        description=f"**[Open post →]({url})**",
                        color=0x00FFC8,
                    )
                    options = "\n".join(f"`{line.strip()}`" for line in draft_lines[:3])
                    embed.add_field(name="📋 Copy one of these:", value=options, inline=False)
                    embed.set_footer(text="Post within 30 min for max visibility")

                    channel = self.get_channel(self._comment_farm_channel_id or message.channel.id)
                    if channel and channel.id != message.channel.id:
                        await channel.send(embed=embed)
                        await message.reply(f"✅ Drafts posted to <#{channel.id}>")
                    else:
                        await message.reply(embed=embed)
                else:
                    await message.reply("⚠️ Couldn't generate drafts. Check Ollama is running.")

            except Exception as e:
                logger.exception("farm command error")
                await message.reply(f"❌ Error: {type(e).__name__}: {str(e)[:100]}")

    async def _news_intel_poller(self) -> None:
        """
        Background loop: fetch /news/latest every NEWS_POLL_INTERVAL seconds,
        deliver new high-relevance items to #news-intel with smart category embeds.
        """
        await self.wait_until_ready()
        # Give on_ready channel setup a moment to complete
        await asyncio.sleep(5)
        logger.info(f"[NewsIntel] Poller active — channel={self._news_channel_id}, interval={NEWS_POLL_INTERVAL}s")

        while not self.is_closed():
            try:
                await self._deliver_news()
            except Exception as exc:
                logger.warning(f"[NewsIntel] Poller cycle error (non-fatal): {exc}")
            await asyncio.sleep(NEWS_POLL_INTERVAL)

    _DELIVERED_IDS_PATH = (
        Path(__file__).parent.parent / "data" / "agents" / "knowledge_agent" / "news_intel" / "delivered_ids.json"
    )

    def _load_delivered_news_ids(self) -> set[str]:
        """Load persisted delivered IDs so restarts don't re-post old articles."""
        try:
            if self._DELIVERED_IDS_PATH.exists():
                return set(json.loads(self._DELIVERED_IDS_PATH.read_text()))
        except Exception:
            pass
        # First run — seed with all currently known IDs so we don't flood on boot
        try:
            latest = Path(__file__).parent.parent / "data" / "agents" / "knowledge_agent" / "news_intel" / "latest.json"
            if latest.exists():
                items = json.loads(latest.read_text()).get("items", [])
                ids = {i["id"] for i in items if "id" in i}
                logger.info(f"[NewsIntel] Seeded {len(ids)} existing IDs on first boot — no flood")
                return ids
        except Exception:
            pass
        return set()

    def _save_delivered_news_ids(self) -> None:
        try:
            self._DELIVERED_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._DELIVERED_IDS_PATH.write_text(json.dumps(list(self._delivered_news_ids)))
        except Exception:
            pass

    async def _deliver_news(self) -> None:
        """Fetch high-relevance items from /news/latest and post to news channel."""
        if not self._http_client or not self._news_channel_id:
            return

        channel = self.get_channel(self._news_channel_id)
        if channel is None:
            return

        try:
            resp = await self._http_client.get(
                f"{AGENTOP_API_URL}/news/latest",
                params={"high_relevance_only": "true", "limit": "20"},
            )
            if resp.status_code != 200:
                return
        except Exception:
            return

        items: list[dict] = resp.json().get("items", [])
        new_items = [i for i in items if i.get("id") not in self._delivered_news_ids]
        if not new_items:
            return

        for item in new_items[:5]:  # max 5 per cycle to avoid spam
            try:
                embed = _format_news_embed(item)
                # Add AI synthesis insight
                insight = await _ollama_news_insight(
                    title=item.get("title", ""),
                    summary=item.get("summary", ""),
                    topics=item.get("topics", []),
                )
                if insight:
                    embed.add_field(name="🤖 Agentop Take", value=insight[:900], inline=False)
                await channel.send(embed=embed)
                self._delivered_news_ids.add(item["id"])
                logger.info(f"[NewsIntel] Delivered [{item.get('category', '?')}] {item.get('title', '?')[:60]}")
                # Durable log so Orchad can answer "what was posted to Discord?"
                _log_discord_post({
                    "event_type": "DISCORD_NEWS_POSTED",
                    "channel_name": NEWS_CHANNEL_NAME,
                    "channel_id": self._news_channel_id,
                    "title": item.get("title", "")[:200],
                    "category": item.get("category", ""),
                    "source_url": item.get("url", ""),
                    "news_id": item.get("id", ""),
                    "timestamp": item.get("published_at", ""),
                })
            except Exception as exc:
                logger.warning(f"[NewsIntel] Embed send failed: {exc}")

        # Keep dedup set bounded
        if len(self._delivered_news_ids) > 2000:
            self._delivered_news_ids = set(list(self._delivered_news_ids)[-1000:])
        self._save_delivered_news_ids()

    async def _handle_command(self, message: Any, raw: str) -> None:
        parts = raw.strip().split(None, 1)
        cmd = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""

        if cmd == "help":
            await self._send_help(message)

        elif cmd == "agents":
            await self._send_agent_list(message)

        elif cmd == "status":
            await self._send_status(message)

        elif cmd == "ask" and args:
            await self._handle_chat(message, args, agent_id="auto")

        elif cmd in AGENT_ALIASES:
            if args:
                await self._handle_chat(message, args, agent_id=AGENT_ALIASES[cmd])
            else:
                await message.reply(f"Usage: `{BOT_PREFIX}{cmd} <your message>`\nRoutes to **{AGENT_ALIASES[cmd]}**")

        elif cmd == "agent" and args:
            # !agent <agent_id> <message>
            agent_parts = args.split(None, 1)
            if len(agent_parts) == 2:
                await self._handle_chat(message, agent_parts[1], agent_id=agent_parts[0])
            else:
                await message.reply(f"Usage: `{BOT_PREFIX}agent <agent_id> <message>`")

        elif cmd == "news":
            await self._cmd_news(message, args)

        # --- Channel management commands ---
        elif cmd == "create-channel":
            await self._cmd_create_channel(message, args)

        elif cmd == "join-channel":
            await self._cmd_join_channel(message, args)

        elif cmd == "leave-channel":
            await self._cmd_leave_channel(message, args)

        elif cmd == "list-channels":
            await self._cmd_list_channels(message)

        elif cmd == "farm":
            await self._cmd_farm(message, args)

        else:
            # Default: treat as auto-routed message
            full_text = f"{cmd} {args}".strip() if args else cmd
            if full_text:
                await self._handle_chat(message, full_text, agent_id="auto")

    # -------------------------------------------------------------------------
    # News intelligence command
    # -------------------------------------------------------------------------

    async def _cmd_news(self, message: Any, args: str) -> None:
        """!news [topic] — show latest high-relevance news items."""
        try:
            from backend.news.intel_scraper import LATEST_JSON, get_latest_digest

            topic = args.strip().lower() or None

            if not LATEST_JSON.exists():
                await message.reply(
                    "No news data yet — the watcher runs every 6h. Wait for the first cycle or restart the backend."
                )
                return

            items = get_latest_digest(limit=10, topic=topic)
            if not items:
                qualifier = f" for topic `{topic}`" if topic else ""
                await message.reply(f"No news items found{qualifier}.")
                return

            embed = discord.Embed(  # type: ignore[union-attr]
                title=f"📰 News Intel{' — ' + topic.title() if topic else ''}",
                description=f"Latest {len(items)} items (newest last)",
                color=0x3B82F6,
            )
            # Show high-relevance items first
            items_sorted = sorted(
                items, key=lambda i: (not i.get("high_relevance"), i.get("fetched_at", "")), reverse=True
            )
            for item in items_sorted[:8]:
                title = item.get("title", "?")[:100]
                url = item.get("url", "")
                source = item.get("source_name", "?")
                category = item.get("category", "general")
                cat_emoji = _CATEGORY_META.get(category, _CATEGORY_META["general"])[0]
                flag = "⭐ " if item.get("high_relevance") else ""
                value = f"{flag}{cat_emoji}  [{title}]({url})" if url else f"{flag}{cat_emoji}  {title}"
                embed.add_field(name=source, value=value[:1024], inline=False)

            embed.set_footer(text="Use !news <topic> to filter — e.g. !news deepseek, !news cybersecurity")
            await message.reply(embed=embed)

        except Exception as exc:
            logger.exception("news command error")
            await message.reply(f"❌ News command error: {exc}")

    # -------------------------------------------------------------------------
    # Channel management commands
    # Requires bot to have Manage Channels + Manage Permissions in Discord
    # -------------------------------------------------------------------------

    def _find_channel(self, guild: Any, name_or_id: str) -> Any:
        """Find a text channel by name or ID string. Returns None if not found."""
        name_or_id = name_or_id.strip().lstrip("#")
        # Try by ID first
        if name_or_id.isdigit():
            ch = guild.get_channel(int(name_or_id))
            if ch and hasattr(ch, "type") and str(ch.type) in ("text", "ChannelType.text"):
                return ch
        # Try by name (case-insensitive)
        for ch in guild.text_channels:
            if ch.name.lower() == name_or_id.lower():
                return ch
        return None

    async def _cmd_create_channel(self, message: Any, args: str) -> None:
        """!create-channel <name> [category] — create a new text channel."""
        if not message.guild:
            await message.reply("This command only works inside a server.")
            return
        channel_name = args.strip().replace(" ", "-").lower()
        if not channel_name:
            await message.reply(f"Usage: `{BOT_PREFIX}create-channel <channel-name>`")
            return
        try:
            new_ch = await message.guild.create_text_channel(channel_name)
            # Auto-add the bot to the new channel with read+write
            await new_ch.set_permissions(
                message.guild.me,
                read_messages=True,
                send_messages=True,
                embed_links=True,
                read_message_history=True,
            )
            await message.reply(f"✅ Created **#{new_ch.name}** and joined it (<#{new_ch.id}>)")
            logger.info(f"[ChannelMgmt] Created #{new_ch.name} ({new_ch.id}) in {message.guild.name}")
        except discord.Forbidden:  # type: ignore[union-attr]
            await message.reply(
                "❌ Missing permission: **Manage Channels**.\n"
                "Go to Server Settings → Roles → OpenClaw → enable *Manage Channels*."
            )
        except Exception as e:
            logger.exception("create-channel error")
            await message.reply(f"❌ Error creating channel: {e}")

    async def _cmd_join_channel(self, message: Any, args: str) -> None:
        """!join-channel <name-or-id> — add the bot to an existing channel."""
        if not message.guild:
            await message.reply("This command only works inside a server.")
            return
        if not args.strip():
            await message.reply(f"Usage: `{BOT_PREFIX}join-channel <#channel-name-or-id>`")
            return
        ch = self._find_channel(message.guild, args)
        if ch is None:
            await message.reply(f"❌ Channel `{args.strip()}` not found.")
            return
        try:
            await ch.set_permissions(
                message.guild.me,
                read_messages=True,
                send_messages=True,
                embed_links=True,
                read_message_history=True,
            )
            await message.reply(f"✅ Joined **#{ch.name}** (<#{ch.id}>)")
            await ch.send("👋 OpenClaw joined this channel. I'm listening.")
            logger.info(f"[ChannelMgmt] Joined #{ch.name} ({ch.id}) in {message.guild.name}")
        except discord.Forbidden:  # type: ignore[union-attr]
            await message.reply(
                "❌ Missing permission: **Manage Permissions** (Manage Roles).\n"
                "Go to Server Settings → Roles → OpenClaw → enable *Manage Roles*."
            )
        except Exception as e:
            logger.exception("join-channel error")
            await message.reply(f"❌ Error joining channel: {e}")

    async def _cmd_leave_channel(self, message: Any, args: str) -> None:
        """!leave-channel <name-or-id> — remove the bot's permission override from a channel."""
        if not message.guild:
            await message.reply("This command only works inside a server.")
            return
        if not args.strip():
            await message.reply(f"Usage: `{BOT_PREFIX}leave-channel <#channel-name-or-id>`")
            return
        ch = self._find_channel(message.guild, args)
        if ch is None:
            await message.reply(f"❌ Channel `{args.strip()}` not found.")
            return
        try:
            await ch.set_permissions(message.guild.me, overwrite=None)
            await message.reply(f"✅ Left **#{ch.name}** (permission override removed)")
            logger.info(f"[ChannelMgmt] Left #{ch.name} ({ch.id}) in {message.guild.name}")
        except discord.Forbidden:  # type: ignore[union-attr]
            await message.reply("❌ Missing permission: **Manage Permissions** (Manage Roles).")
        except Exception as e:
            logger.exception("leave-channel error")
            await message.reply(f"❌ Error leaving channel: {e}")

    async def _cmd_list_channels(self, message: Any) -> None:
        """!list-channels — list all text channels and whether the bot is in them."""
        if not message.guild:
            await message.reply("This command only works inside a server.")
            return
        channels = message.guild.text_channels
        if not channels:
            await message.reply("No text channels found.")
            return
        lines = [f"**Text channels in {message.guild.name} ({len(channels)} total):**"]
        for ch in channels:
            # Check if bot has explicit permission override
            overwrite = ch.overwrites_for(message.guild.me)
            bot_in = overwrite.read_messages is True or overwrite.send_messages is True
            marker = "🟢" if bot_in else "⚪"
            lines.append(f"{marker} <#{ch.id}> `#{ch.name}`")
        text = "\n".join(lines)
        if len(text) > 1900:
            text = text[:1900] + "\n*...truncated*"
        await message.reply(text)

    async def _handle_chat(self, message: Any, text: str, agent_id: str = "auto") -> None:
        """Send message to Agentop backend and relay response."""
        if not self._http_client:
            await message.reply("Bot not fully initialized yet.")
            return

        # Show typing indicator while processing
        async with message.channel.typing():
            try:
                # Inject Discord context so agents give concise, accurate answers
                discord_prefix = (
                    "[DISCORD CONTEXT] You are responding via Discord. Rules: "
                    "1) Keep responses under 500 characters. "
                    "2) Do NOT hallucinate tool calls or agent names. "
                    "3) Only reference agents: soul_core, devops_agent, monitor_agent, "
                    "self_healer_agent, code_review_agent, security_agent, data_agent, "
                    "comms_agent, cs_agent, it_agent, knowledge_agent. "
                    "4) Be direct and helpful. No verbose preamble. "
                    "5) Apply Ordo reasoning: classify the lane (dev/eval/arch/positioning), "
                    "state confidence, and if confidence <0.65 say what you need to be sure. "
                    "6) If your answer relies on retrieved documents cite them briefly (e.g. \u2018per config.py\u2019). "
                    "[/DISCORD CONTEXT]\n\n"
                )
                payload: dict[str, Any] = {
                    "agent_id": agent_id,
                    "message": discord_prefix + text,
                    "context": {
                        "source": "discord",
                        "user": str(message.author),
                        "user_id": str(message.author.id),
                        "channel": str(message.channel),
                        "channel_id": str(message.channel.id),
                        "guild": str(getattr(message.guild, "name", "DM")),
                    },
                }

                resp = await self._http_client.post(
                    f"{AGENTOP_API_URL}/chat",
                    json=payload,
                )

                if resp.status_code == 200:
                    data = resp.json()
                    agent_name = data.get("agent_id", agent_id)
                    response_text = data.get("message", "No response.")
                    drift = data.get("drift_status", "GREEN")
                    ordo = data.get("ordo_trace") or {}
                    sources = data.get("sources") or []

                    # Strip any echoed Discord context prefix from response
                    response_text = re.sub(
                        r"\[DISCORD CONTEXT\].*?\[/DISCORD CONTEXT\]\s*",
                        "",
                        response_text,
                        flags=re.DOTALL,
                    ).strip()

                    # Truncate overly verbose responses for Discord
                    if len(response_text) > 1800:
                        response_text = response_text[:1800] + "\n\n*...truncated for Discord*"

                    # --- Ordo reasoning badge ---
                    ordo_footer = ""
                    if ordo:
                        conf = ordo.get("confidence", 0.0)
                        lane = ordo.get("lane", "")
                        inferred = ordo.get("inferred", False)
                        if conf >= 0.75:
                            conf_icon = "🟢"
                        elif conf >= 0.5:
                            conf_icon = "🟡"
                        else:
                            conf_icon = "🔴"
                        inferred_tag = " *(inferred)*" if inferred else ""
                        ordo_footer = f"\n-# {conf_icon} {int(conf * 100)}% confidence · {lane}{inferred_tag}"

                    # --- RAG source citations ---
                    sources_footer = ""
                    if sources:
                        cited = ", ".join(f"`{s}`" for s in sources[:3])
                        sources_footer = f"\n-# 📚 Sources: {cited}"

                    # Format response with agent attribution
                    header = f"**[{agent_name}]**"
                    if drift != "GREEN":
                        header += f" ⚠️ Drift: {drift}"

                    full_response = f"{header}\n{response_text}{ordo_footer}{sources_footer}"

                    # Track conversation agent for context
                    self._conversation_agents[message.channel.id] = agent_name

                    # Split long messages (Discord 2000 char limit)
                    await self._send_long(message, full_response)

                elif resp.status_code == 400:
                    detail = resp.json().get("detail", "Bad request")
                    await message.reply(f"⚠️ {detail}")
                elif resp.status_code == 503:
                    await message.reply("🔧 Agentop backend is starting up. Try again in a moment.")
                else:
                    await message.reply(f"❌ Backend error ({resp.status_code}): {resp.text[:200]}")

            except httpx.ConnectError:  # type: ignore[union-attr]
                await message.reply(f"🔌 Can't reach Agentop backend. Is it running?\nExpected at: `{AGENTOP_API_URL}`")
            except httpx.TimeoutException:  # type: ignore[union-attr]
                await message.reply("⏱️ Agent took too long to respond (>120s). Try a simpler question.")
            except Exception as e:
                logger.exception("Discord chat handler error")
                await message.reply(f"❌ Unexpected error: {type(e).__name__}")

    async def _send_long(self, message: Any, text: str) -> None:
        """Send a message, splitting if over Discord's 2000 char limit."""
        chunks = _split_message(text, MAX_DISCORD_LENGTH)
        for i, chunk in enumerate(chunks):
            if i == 0:
                await message.reply(chunk)
            else:
                await message.channel.send(chunk)

    # -------------------------------------------------------------------------
    # Slash command interaction handlers
    # Interactions use followup.send() after defer(), not message.reply()
    # -------------------------------------------------------------------------

    async def _handle_chat_interaction(self, interaction: Any, text: str, agent_id: str) -> None:
        """Handle a slash command chat interaction — mirrors _handle_chat but uses interaction API."""
        if not self._http_client:
            await interaction.followup.send("Bot not fully initialized yet.")
            return
        try:
            discord_prefix = (
                "[DISCORD CONTEXT] You are responding via Discord. Rules: "
                "1) Keep responses under 500 characters. "
                "2) Do NOT hallucinate tool calls or agent names. "
                "3) Only reference valid Agentop agents. "
                "4) Be direct and helpful. No verbose preamble. "
                "5) Apply Ordo reasoning: classify the lane, state confidence, "
                "and if confidence <0.65 say what you need to be sure. "
                "6) If your answer relies on retrieved documents cite them briefly. "
                "[/DISCORD CONTEXT]\n\n"
            )
            payload: dict[str, Any] = {
                "agent_id": agent_id,
                "message": discord_prefix + text,
                "context": {
                    "source": "discord_slash",
                    "user": str(interaction.user),
                    "user_id": str(interaction.user.id),
                    "channel": str(interaction.channel),
                    "channel_id": str(interaction.channel_id),
                    "guild": str(getattr(interaction.guild, "name", "DM")),
                },
            }
            resp = await self._http_client.post(f"{AGENTOP_API_URL}/chat", json=payload)
            if resp.status_code == 200:
                data = resp.json()
                agent_name = data.get("agent_id", agent_id)
                response_text = data.get("message", "No response.")
                ordo = data.get("ordo_trace") or {}
                sources = data.get("sources") or []

                response_text = re.sub(
                    r"\[DISCORD CONTEXT\].*?\[/DISCORD CONTEXT\]\s*", "", response_text, flags=re.DOTALL
                ).strip()
                if len(response_text) > 1800:
                    response_text = response_text[:1800] + "\n\n*...truncated for Discord*"

                ordo_footer = ""
                if ordo:
                    conf = ordo.get("confidence", 0.0)
                    lane = ordo.get("lane", "")
                    inferred = ordo.get("inferred", False)
                    conf_icon = "🟢" if conf >= 0.75 else "🟡" if conf >= 0.5 else "🔴"
                    inferred_tag = " *(inferred)*" if inferred else ""
                    ordo_footer = f"\n-# {conf_icon} {int(conf * 100)}% confidence · {lane}{inferred_tag}"

                sources_footer = ""
                if sources:
                    cited = ", ".join(f"`{s}`" for s in sources[:3])
                    sources_footer = f"\n-# 📚 Sources: {cited}"

                full_response = f"**[{agent_name}]**\n{response_text}{ordo_footer}{sources_footer}"
                # Slash commands: send as chunks via followup
                chunks = _split_message(full_response, MAX_DISCORD_LENGTH)
                for chunk in chunks:
                    await interaction.followup.send(chunk)
            else:
                await interaction.followup.send(f"❌ Backend error ({resp.status_code}): {resp.text[:200]}")
        except Exception as exc:
            logger.exception("Slash command chat handler error")
            await interaction.followup.send(f"❌ Error: {type(exc).__name__}: {str(exc)[:100]}")

    async def _handle_farm_interaction(self, interaction: Any, url: str) -> None:
        """Handle /farm slash command."""
        if "instagram.com" not in url:
            await interaction.followup.send("❌ That doesn't look like an Instagram URL.")
            return
        import subprocess
        farm_script = str(COMMENT_FARM_PATH.parent / "comment_farm.py")
        try:
            result = await self.loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["python3", farm_script, "--post", url],
                    capture_output=True, text=True, timeout=120, env={**os.environ},
                ),
            )
            output = result.stdout + result.stderr
            lines = output.strip().split("\n")
            draft_lines = [line for line in lines if re.match(r"^\d+\.", line.strip())]
            if draft_lines:
                handle_match = re.search(r"@(\w[\w.]+)", output)
                handle = handle_match.group(1) if handle_match else "creator"
                embed = discord.Embed(  # type: ignore[union-attr]
                    title=f"💬 Comment drafts for @{handle}",
                    description=f"**[Open post →]({url})**",
                    color=0x00FFC8,
                )
                options = "\n".join(f"`{line.strip()}`" for line in draft_lines[:3])
                embed.add_field(name="📋 Copy one of these:", value=options, inline=False)
                embed.set_footer(text="Post within 30 min for max visibility")
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send("⚠️ Couldn't generate drafts. Check Ollama is running.")
        except Exception as exc:
            await interaction.followup.send(f"❌ Error: {type(exc).__name__}: {str(exc)[:100]}")

    async def _handle_news_interaction(self, interaction: Any, topic: str) -> None:
        """Handle /news slash command."""
        import json as _json
        try:
            news_file = Path(__file__).parent.parent / "data" / "agents" / "knowledge_agent" / "news_intel" / "latest.json"
            if not news_file.exists():
                await interaction.followup.send("📭 No news cached yet. Check back after the next poll cycle (10 min).")
                return
            items: list[dict] = _json.loads(news_file.read_text())
            if topic:
                items = [i for i in items if topic.lower() in (i.get("title", "") + " ".join(i.get("topics", []))).lower()]
            embed = discord.Embed(  # type: ignore[union-attr]
                title=f"📰 News Intel{' — ' + topic.title() if topic else ''}",
                description=f"Latest {min(len(items), 8)} items",
                color=0x3B82F6,
            )
            for item in items[:8]:
                title = item.get("title", "?")[:100]
                url = item.get("url", "")
                source = item.get("source_name", "?")
                flag = "⭐ " if item.get("high_relevance") else ""
                value = f"{flag}[{title}]({url})" if url else f"{flag}{title}"
                embed.add_field(name=source, value=value[:1024], inline=False)
            await interaction.followup.send(embed=embed)
        except Exception as exc:
            await interaction.followup.send(f"❌ News error: {exc}")

    async def _handle_status_interaction(self, interaction: Any) -> None:
        """Handle /status slash command."""
        if not self._http_client:
            await interaction.followup.send("Bot not fully initialized yet.")
            return
        try:
            resp = await self._http_client.get(f"{AGENTOP_API_URL}/health", timeout=10)
            if resp.status_code == 200:
                health = resp.json()
                status = health.get("status", "unknown")
                llm_ok = health.get("llm_available", False)
                agents = health.get("agents_active", 0)
                model = health.get("model", "unknown")
                color = 0x00FF88 if status == "healthy" else 0xFF6600
                embed = discord.Embed(  # type: ignore[union-attr]
                    title=f"{'✅' if status == 'healthy' else '⚠️'} Agentop — {status.title()}",
                    color=color,
                )
                embed.add_field(name="LLM", value=f"{'✅' if llm_ok else '❌'} {model}", inline=True)
                embed.add_field(name="Agents active", value=str(agents), inline=True)
                embed.add_field(name="Backend", value=f"`{AGENTOP_API_URL}`", inline=True)
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send(f"❌ Health check failed ({resp.status_code})")
        except Exception as exc:
            await interaction.followup.send(f"❌ Can't reach backend: {exc}")

    async def _send_help(self, message: Any) -> None:
        embed = discord.Embed(  # type: ignore[union-attr]
            title="Agentop — Discord Agent Interface",
            description="Talk to your local AI agents via Discord.",
            color=0x3B82F6,
        )
        embed.add_field(
            name="Quick Start",
            value=(
                f"`{BOT_PREFIX}ask <question>` — Auto-route via Lex\n"
                f"`@{self.user} <question>` — Same (mention me)\n"
                f"`{BOT_PREFIX}soul <message>` — Talk to Soul Core\n"
                f"`{BOT_PREFIX}devops <message>` — Talk to DevOps\n"
                f"`{BOT_PREFIX}gsd <task>` — Get Stuff Done agent"
            ),
            inline=False,
        )
        embed.add_field(
            name="All Agent Shortcuts",
            value="\n".join(f"`{BOT_PREFIX}{alias}` → {agent}" for alias, agent in sorted(AGENT_ALIASES.items())),
            inline=False,
        )
        embed.add_field(
            name="Utility",
            value=(
                f"`{BOT_PREFIX}agents` — List all available agents\n"
                f"`{BOT_PREFIX}status` — Backend health check\n"
                f"`{BOT_PREFIX}news [topic]` — Latest AI/security news (e.g. `!news deepseek`)\n"
                f"`{BOT_PREFIX}help` — This message"
            ),
            inline=False,
        )
        embed.add_field(
            name="Channel Management",
            value=(
                f"`{BOT_PREFIX}create-channel <name>` — Create a text channel + auto-join\n"
                f"`{BOT_PREFIX}join-channel <#name-or-id>` — Add bot to existing channel\n"
                f"`{BOT_PREFIX}leave-channel <#name-or-id>` — Remove bot from channel\n"
                f"`{BOT_PREFIX}list-channels` — List all channels (🟢 = bot present)\n"
                "*Requires Manage Channels + Manage Roles bot permissions*"
            ),
            inline=False,
        )
        embed.set_footer(text="Agentop — Local-first multi-agent system")
        await message.reply(embed=embed)

    async def _send_agent_list(self, message: Any) -> None:
        if not self._http_client:
            await message.reply("Bot not initialized.")
            return
        try:
            resp = await self._http_client.get(f"{AGENTOP_API_URL}/agents")
            if resp.status_code == 200:
                agents = resp.json()
                if isinstance(agents, list):
                    lines = [f"**Available Agents ({len(agents)}):**"]
                    for a in agents:
                        name = a if isinstance(a, str) else a.get("agent_id", a.get("id", "?"))
                        role = "" if isinstance(a, str) else f" — {a.get('role', '')[:60]}"
                        lines.append(f"• `{name}`{role}")
                    await message.reply("\n".join(lines))
                else:
                    await message.reply(f"Agents: {json.dumps(agents)[:1500]}")
            else:
                await message.reply(f"Backend returned {resp.status_code}")
        except Exception as e:
            await message.reply(f"Error fetching agents: {e}")

    async def _send_status(self, message: Any) -> None:
        if not self._http_client:
            await message.reply("Bot not initialized.")
            return
        try:
            resp = await self._http_client.get(f"{AGENTOP_API_URL}/health")
            if resp.status_code == 200:
                data = resp.json()
                embed = discord.Embed(  # type: ignore[union-attr]
                    title="Agentop Status",
                    color=0x22C55E,  # green
                )
                embed.add_field(name="Status", value=data.get("status", "ok"), inline=True)
                embed.add_field(name="Backend", value=AGENTOP_API_URL, inline=True)
                await message.reply(embed=embed)
            else:
                await message.reply(f"⚠️ Backend unhealthy ({resp.status_code})")
        except httpx.ConnectError:  # type: ignore[union-attr]
            await message.reply("🔌 Backend unreachable")
        except Exception as e:
            await message.reply(f"Error: {e}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_alert_embed(alert: dict) -> Any:
    """Format a security or news alert as a Discord embed."""
    alert_type = alert.get("type", "UNKNOWN")

    # News intel digest gets its own lighter treatment
    if alert_type == "NEWS_INTEL_DIGEST":
        raw = alert.get("raw", {})
        items: list[dict] = raw.get("items", [])
        embed = discord.Embed(  # type: ignore[union-attr]
            title="📰 News Intel — High Relevance Items",
            description=raw.get("description", "New high-relevance AI/security news")[:300],
            color=0x3B82F6,  # blue
        )
        for item in items[:5]:
            title = item.get("title", "?")[:100]
            url = item.get("url", "")
            source = item.get("source_name", "?")
            topics = ", ".join(item.get("topics", []))
            embed.add_field(
                name=f"{source}",
                value=f"[{title}]({url})\n*{topics}*" if url else f"{title}\n*{topics}*",
                inline=False,
            )
        embed.set_footer(text=f"Received: {alert.get('received_at', 'unknown')}")
        return embed

    # Standard security alert
    severity = alert.get("severity", "MEDIUM")
    color_map = {"CRITICAL": 0xFF0000, "HIGH": 0xFF6600, "MEDIUM": 0xFFAA00}
    color = color_map.get(severity, 0xFFAA00)
    severity_emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡"}.get(severity, "🟡")

    alert_type = alert.get("type", "UNKNOWN")
    # Human-readable type labels
    type_labels = {
        "SECRET_FOUND": "Hard-coded secret detected",
        "CVE": "Known vulnerability (CVE)",
        "INJECTION": "Possible injection attack",
        "DRIFT": "Architecture drift detected",
        "ANOMALY": "Anomalous behavior detected",
        "POLICY_VIOLATION": "Policy violation",
    }
    readable_type = type_labels.get(alert_type, alert_type.replace("_", " ").title())

    summary = alert.get("summary", "").strip()
    detail = alert.get("detail", alert.get("raw_detail", "")).strip()
    agent_id = alert.get("agent_id", "unknown")
    file_ref = alert.get("file", alert.get("path", ""))

    # Build title
    title = f"{severity_emoji} {severity} — {readable_type}"

    # Build description: summary first, then file ref if present
    description_parts = []
    if summary:
        description_parts.append(summary[:300])
    if file_ref:
        description_parts.append(f"**File:** `{file_ref}`")
    description = "\n".join(description_parts) if description_parts else "No summary available."

    embed = discord.Embed(  # type: ignore[union-attr]
        title=title,
        description=description,
        color=color,
    )

    # What this means
    meaning_map = {
        "SECRET_FOUND": (
            "A secret key, token, or password may be hard-coded in your source files. "
            "If this reaches a public repo it can be exploited immediately."
        ),
        "CVE": (
            "A dependency you use has a known security vulnerability with a published exploit. "
            "Attackers can target this if your service is exposed."
        ),
        "INJECTION": (
            "Someone may be attempting to inject malicious commands through user input. "
            "This could lead to data leakage or remote code execution."
        ),
        "DRIFT": (
            "Your running system no longer matches the expected architecture. "
            "This may cause unpredictable behavior or security gaps."
        ),
    }
    meaning = meaning_map.get(alert_type, "Review the details above and investigate the source.")
    embed.add_field(name="💡 What this means", value=meaning, inline=False)

    # What to do
    action_map = {
        "SECRET_FOUND": "1. Rotate the exposed secret immediately.\n2. Remove it from code and use `.env`.\n3. Audit git history with `git log -p | grep <secret>`.",
        "CVE": "1. Run `pip list --outdated` or `npm audit`.\n2. Update the affected package.\n3. Redeploy after patching.",
        "INJECTION": "1. Check recent `/chat` requests in `data/dpo/chat_failures_*.jsonl`.\n2. Review `backend/security_middleware.py` logs.\n3. Block or rate-limit the source IP if needed.",
        "DRIFT": "1. Run `GET /health` to compare expected vs actual state.\n2. Restart affected agents via `/agent-control/restart`.\n3. Review `docs/DRIFT_GUARD.md` for invariants.",
    }
    action = action_map.get(alert_type, "Review `backend/logs/system.jsonl` and the agent that raised this alert.")
    embed.add_field(name="🔧 What to do", value=action, inline=False)

    # Technical details (collapsed into one small field)
    tech_parts = [f"Agent: `{agent_id}`"]
    if detail:
        tech_parts.append(f"Detail: {detail[:200]}")
    alert_id = alert.get("alert_id", "")
    if alert_id:
        tech_parts.append(f"ID: `{alert_id[:12]}`")
    embed.add_field(name="🔍 Technical", value="\n".join(tech_parts), inline=False)

    embed.set_footer(text=f"Received: {alert.get('received_at', 'unknown')} · Alert raised by {agent_id}")
    return embed


async def _ollama_news_insight(title: str, summary: str, topics: list[str]) -> str:
    """
    Call local Ollama to generate a 2-3 sentence insight on how this article
    relates to Agentop or what action to take. Returns empty string on any failure.
    """
    import httpx as _httpx

    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "llama3.2:3b-instruct-q8_0")

    topic_str = ", ".join(topics[:4]) if topics else "AI"
    prompt = (
        f"You are a concise AI analyst for Agentop, a local multi-agent system. "
        f"Given this news item, write exactly 2-3 sentences covering: "
        f"(1) what's notable about it, and (2) one concrete way Agentop or its operator could act on or benefit from this. "
        f"Be specific. No fluff. No intro phrases like 'This article'.\n\n"
        f"Title: {title}\n"
        f"Topics: {topic_str}\n"
        f"Summary: {summary or 'N/A'}\n\n"
        f"Insight:"
    )
    try:
        async with _httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{ollama_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False, "options": {"num_predict": 120}},
            )
            if resp.status_code == 200:
                text = resp.json().get("response", "").strip()
                # Truncate to 3 sentences max for the embed field limit
                sentences = [s.strip() for s in text.replace("\n", " ").split(".") if s.strip()]
                return ". ".join(sentences[:3]) + ("." if sentences else "")
    except Exception:
        pass
    return ""


_CATEGORY_META: dict[str, tuple[str, int]] = {
    # category → (emoji label, embed color)
    "software": ("🖥️ Software", 0x3B82F6),  # blue
    "hardware": ("⚙️ Hardware", 0xF97316),  # orange
    "security": ("🔒 Security", 0xEF4444),  # red
    "research": ("📚 Research", 0x8B5CF6),  # purple
    "general": ("📰 General", 0x6B7280),  # gray
}


def _format_news_embed(item: dict) -> Any:
    """Format a single news item as a smart category-tagged Discord embed."""
    category = item.get("category", "general")
    label, color = _CATEGORY_META.get(category, _CATEGORY_META["general"])
    title = item.get("title", "Untitled")[:200]
    url = item.get("url", "")
    summary = item.get("summary", "")[:300]
    source = item.get("source_name", "Unknown Source")
    topics = item.get("topics", [])
    high_rel = item.get("high_relevance", False)

    embed = discord.Embed(  # type: ignore[union-attr]
        title=f"{label}{'  ⭐' if high_rel else ''}  —  {title}",
        url=url or None,
        description=summary if summary else None,
        color=color,
    )
    embed.set_author(name=source)
    if topics:
        embed.set_footer(text="  ·  ".join(f"#{t}" for t in topics[:5]))
    return embed


def _format_content_report_embed(report_text: str) -> Any:
    """Format an optimization_report.md as a Discord embed summary."""
    import re as _re

    # Pull date from the first heading line: "# @lexmakesit ... Report\n*Generated: 2026-04-09 ...*"
    date_match = _re.search(r"\*Generated:\s*([^|]+)", report_text)
    generated = date_match.group(1).strip() if date_match else "latest"

    # Count posts analyzed
    posts_match = _re.search(r"Posts analyzed:\s*(\d+)", report_text)
    posts_count = posts_match.group(1) if posts_match else "?"

    embed = discord.Embed(  # type: ignore[union-attr]
        title="📊 Daily Content Optimization Report",
        description=f"*Generated: {generated} · {posts_count} posts analyzed*",
        color=0x00FFC8,
    )

    # Extract the "What's working" section
    working_match = _re.search(r"\*\*What.s working\*\*(.*?)(?=\*\*What to fix\*\*|\Z)", report_text, _re.DOTALL)
    if working_match:
        working_text = working_match.group(1).strip()[:900]
        embed.add_field(name="✅ What's Working", value=working_text or "—", inline=False)

    # Extract "What to fix"
    fix_match = _re.search(
        r"\*\*What to fix\*\*(.*?)(?=\*\*Caption rewrites\*\*|\*\*Slide count\*\*|\Z)",
        report_text,
        _re.DOTALL,
    )
    if fix_match:
        fix_text = fix_match.group(1).strip()[:900]
        embed.add_field(name="🔧 What to Fix", value=fix_text or "—", inline=False)

    # Extract "Caption rewrites"
    rewrites_match = _re.search(
        r"\*\*Caption rewrites\*\*(.*?)(?=\*\*Slide count\*\*|\*\*One unconventional\*\*|\Z)",
        report_text,
        _re.DOTALL,
    )
    if rewrites_match:
        rewrites_text = rewrites_match.group(1).strip()[:900]
        embed.add_field(name="✏️ Hook Rewrites", value=rewrites_text or "—", inline=False)

    # Extract "One unconventional insight"
    insight_match = _re.search(r"\*\*One unconventional insight\*\*(.*?)(?=\n##|\Z)", report_text, _re.DOTALL)
    if insight_match:
        insight_text = insight_match.group(1).strip()[:500]
        embed.add_field(name="💡 Unconventional Insight", value=insight_text or "—", inline=False)

    embed.set_footer(text="Run `python3 content_creation_pack/content_optimizer.py --print` for full report")
    return embed


def _split_message(text: str, limit: int = 2000) -> list[str]:
    """Split text into chunks respecting Discord's message size limit."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break

        # Try to split at newline
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1 or split_at < limit // 2:
            # Try space
            split_at = text.rfind(" ", 0, limit)
        if split_at == -1 or split_at < limit // 2:
            split_at = limit

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_bot_instance: AgentopBot | None = None


async def start_bot() -> None:
    """Start the Discord bot (call from asyncio context)."""
    global _bot_instance
    if not HAS_DISCORD:
        logger.warning("discord.py not installed — Discord bot disabled. pip install discord.py")
        return
    if not DISCORD_BOT_TOKEN:
        logger.warning("DISCORD_BOT_TOKEN not set — Discord bot disabled. Set it in .env to enable.")
        return
    if not _acquire_lock():
        logger.error("Another bot instance is already running. Aborting.")
        return

    _bot_instance = AgentopBot()
    try:
        await _bot_instance.start(DISCORD_BOT_TOKEN)
    except discord.LoginFailure:  # type: ignore[union-attr]
        logger.error("Invalid DISCORD_BOT_TOKEN — bot cannot log in")
    except Exception:
        logger.exception("Discord bot crashed")
    finally:
        _release_lock()


def run_bot() -> None:
    """Run the Discord bot standalone (blocking)."""
    if not HAS_DISCORD:
        print("ERROR: discord.py not installed. Run: pip install discord.py")
        return
    if not DISCORD_BOT_TOKEN:
        print(
            "ERROR: DISCORD_BOT_TOKEN not set.\n"
            "1. Go to https://discord.com/developers/applications\n"
            "2. Create an application → Bot → Copy token\n"
            "3. Add to .env: DISCORD_BOT_TOKEN=your_token_here\n"
            "4. Enable MESSAGE CONTENT INTENT in Bot settings\n"
            "5. Invite bot with: OAuth2 → URL Generator → bot scope → Send Messages + Read Messages\n"
        )
        return

    if not HAS_HTTPX:
        print("ERROR: httpx not installed. Run: pip install httpx")
        return

    if not _acquire_lock():
        print("ERROR: Another bot instance is already running.")
        print(f"If this is wrong, delete {_PID_FILE}")
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    import atexit

    atexit.register(_release_lock)
    bot = AgentopBot()
    bot.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    run_bot()
