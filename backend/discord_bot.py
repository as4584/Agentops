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
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

# Load .env if present (needed for standalone mode)
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    from dotenv import load_dotenv

    load_dotenv(_env_path)

try:
    import discord
    from discord import Intents, Message

    HAS_DISCORD = True
except ImportError:
    discord = None  # type: ignore[assignment]
    Intents = None  # type: ignore[assignment,misc]
    Message = None  # type: ignore[assignment,misc]
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
_ClientBase = discord.Client if HAS_DISCORD else object  # type: ignore[union-attr]


class AgentopBot(_ClientBase):  # type: ignore[misc]
    """Discord bot that routes messages to Agentop agents."""

    def __init__(self) -> None:
        intents = Intents.default()  # type: ignore[union-attr]
        intents.message_content = True
        super().__init__(intents=intents)
        self._http_client: Any = None
        self._conversation_agents: dict[int, str] = {}  # channel_id → last agent
        self._rate_limits: dict[int, float] = {}  # user_id → last msg time
        self._rate_limit_seconds: float = 2.0
        self._handled_messages: set[int] = set()  # dedup guard: message IDs already processed

    async def setup_hook(self) -> None:
        self._http_client = httpx.AsyncClient(timeout=120.0)  # type: ignore[union-attr]
        logger.info("Agentop Discord bot initialized")

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
        await self.change_presence(
            activity=discord.Activity(  # type: ignore[union-attr]
                type=discord.ActivityType.listening,  # type: ignore[union-attr]
                name="your commands | !help",
            )
        )

    async def on_message(self, message: Any) -> None:
        # Ignore own messages
        if message.author == self.user:
            return

        # Ignore bots
        if message.author.bot:
            return

        # Channel filter
        if DISCORD_CHANNEL_IDS and message.channel.id not in DISCORD_CHANNEL_IDS:
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

        content = message.content.strip()
        if not content:
            return

        # Dedup guard — prevent double-processing same message
        if message.id in self._handled_messages:
            return
        self._handled_messages.add(message.id)
        # Keep set bounded (last 1000 messages)
        if len(self._handled_messages) > 1000:
            self._handled_messages = set(list(self._handled_messages)[-500:])

        # --- Command routing ---
        if content.startswith(BOT_PREFIX):
            await self._handle_command(message, content[len(BOT_PREFIX) :])
        elif self.user and self.user.mentioned_in(message):
            # @mention the bot to talk
            clean = re.sub(r"<@!?\d+>", "", content).strip()
            if clean:
                await self._handle_chat(message, clean, agent_id="auto")

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

        else:
            # Default: treat as auto-routed message
            full_text = f"{cmd} {args}".strip() if args else cmd
            if full_text:
                await self._handle_chat(message, full_text, agent_id="auto")

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

                    # Format response with agent attribution
                    header = f"**[{agent_name}]**"
                    if drift != "GREEN":
                        header += f" ⚠️ Drift: {drift}"

                    full_response = f"{header}\n{response_text}"

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
                f"`{BOT_PREFIX}help` — This message"
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
