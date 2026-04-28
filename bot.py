"""
╔══════════════════════════════════════════════════════════════╗
║          DISCORD BOT — SISTEMA COMPLETO                      ║
║  Tickets | XP | Economia | Moderação | Diversão              ║
║  Compatível com Railway + discord.py 2.x                     ║
╚══════════════════════════════════════════════════════════════╝
"""

import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import aiosqlite
import json
import os
import random
import datetime
import logging
import io
import aiohttp
from typing import Optional

# ══════════════════════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("Bot")

# ══════════════════════════════════════════════════════════════
#  CONSTANTES
# ══════════════════════════════════════════════════════════════
CONFIG_FILE      = "config.json"
DB_FILE          = "database.db"
TOKEN            = os.environ.get("DISCORD_TOKEN", "")

XP_PER_MESSAGE   = 10
XP_COOLDOWN      = 60          # segundos entre ganhos de XP
LEVEL_BASE       = 100         # XP para o nível 1
LEVEL_MULTIPLIER = 1.5         # multiplicador por nível

DAILY_AMOUNT     = 500
WORK_MIN         = 100
WORK_MAX         = 400

# ══════════════════════════════════════════════════════════════
#  GERENCIADOR DE CONFIGURAÇÃO (JSON por guild)
# ══════════════════════════════════════════════════════════════
def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_config(data: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_guild_config(guild_id: int) -> dict:
    return load_config().get(str(guild_id), {})

def set_guild_config(guild_id: int, key: str, value):
    cfg = load_config()
    gid = str(guild_id)
    if gid not in cfg:
        cfg[gid] = {}
    cfg[gid][key] = value
    save_config(cfg)

# ══════════════════════════════════════════════════════════════
#  BANCO DE DADOS (SQLite assíncrono)
# ══════════════════════════════════════════════════════════════
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS xp (
                user_id     INTEGER,
                guild_id    INTEGER,
                xp          INTEGER DEFAULT 0,
                level       INTEGER DEFAULT 0,
                last_msg    REAL    DEFAULT 0,
                PRIMARY KEY (user_id, guild_id)
            );
            CREATE TABLE IF NOT EXISTS economy (
                user_id     INTEGER,
                guild_id    INTEGER,
                balance     INTEGER DEFAULT 0,
                last_daily  REAL    DEFAULT 0,
                last_work   REAL    DEFAULT 0,
                PRIMARY KEY (user_id, guild_id)
            );
            CREATE TABLE IF NOT EXISTS warns (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER,
                guild_id     INTEGER,
                moderator_id INTEGER,
                reason       TEXT,
                timestamp    REAL
            );
            CREATE TABLE IF NOT EXISTS tickets (
                channel_id    INTEGER PRIMARY KEY,
                guild_id      INTEGER,
                user_id       INTEGER,
                ticket_type   TEXT,
                status        TEXT DEFAULT 'open',
                attendant_id  INTEGER,
                created_at    REAL,
                ticket_number INTEGER
            );
            CREATE TABLE IF NOT EXISTS ticket_counter (
                guild_id INTEGER PRIMARY KEY,
                count    INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS shop (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id   INTEGER,
                item_name  TEXT,
                item_price INTEGER,
                role_id    INTEGER
            );
        """)
        await db.commit()
    log.info("Banco de dados inicializado.")

# ══════════════════════════════════════════════════════════════
#  HELPERS — XP
# ══════════════════════════════════════════════════════════════
def xp_for_level(level: int) -> int:
    return int(LEVEL_BASE * (LEVEL_MULTIPLIER ** level))

async def get_xp(user_id: int, guild_id: int) -> dict:
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT xp, level, last_msg FROM xp WHERE user_id=? AND guild_id=?",
            (user_id, guild_id),
        ) as cur:
            row = await cur.fetchone()
    if row:
        return {"xp": row[0], "level": row[1], "last_msg": row[2]}
    return {"xp": 0, "level": 0, "last_msg": 0.0}

async def add_xp(user_id: int, guild_id: int, amount: int) -> tuple[bool, int, int]:
    """Adiciona XP e retorna (leveled_up, old_level, new_level)."""
    data     = await get_xp(user_id, guild_id)
    new_xp   = data["xp"] + amount
    old_lvl  = data["level"]
    new_lvl  = old_lvl

    while new_xp >= xp_for_level(new_lvl):
        new_xp -= xp_for_level(new_lvl)
        new_lvl += 1

    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            """
            INSERT INTO xp (user_id, guild_id, xp, level, last_msg)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, guild_id) DO UPDATE SET
                xp=excluded.xp, level=excluded.level
            """,
            (user_id, guild_id, new_xp, new_lvl, data["last_msg"]),
        )
        await db.commit()

    return new_lvl > old_lvl, old_lvl, new_lvl

# ══════════════════════════════════════════════════════════════
#  HELPERS — ECONOMIA
# ══════════════════════════════════════════════════════════════
async def get_balance(user_id: int, guild_id: int) -> dict:
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT balance, last_daily, last_work FROM economy WHERE user_id=? AND guild_id=?",
            (user_id, guild_id),
        ) as cur:
            row = await cur.fetchone()
    if row:
        return {"balance": row[0], "last_daily": row[1], "last_work": row[2]}
    return {"balance": 0, "last_daily": 0.0, "last_work": 0.0}

async def add_balance(user_id: int, guild_id: int, amount: int):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            """
            INSERT INTO economy (user_id, guild_id, balance)
            VALUES (?, ?, MAX(0, ?))
            ON CONFLICT(user_id, guild_id) DO UPDATE SET
                balance = MAX(0, balance + ?)
            """,
            (user_id, guild_id, amount, amount),
        )
        await db.commit()

async def _set_eco_ts(user_id: int, guild_id: int, field: str, ts: float):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            f"""
            INSERT INTO economy (user_id, guild_id, {field})
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, guild_id) DO UPDATE SET {field}=?
            """,
            (user_id, guild_id, ts, ts),
        )
        await db.commit()

# ══════════════════════════════════════════════════════════════
#  HELPERS — TICKETS
# ══════════════════════════════════════════════════════════════
async def next_ticket_number(guild_id: int) -> int:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            """
            INSERT INTO ticket_counter (guild_id, count) VALUES (?, 1)
            ON CONFLICT(guild_id) DO UPDATE SET count = count + 1
            """,
            (guild_id,),
        )
        await db.commit()
        async with db.execute(
            "SELECT count FROM ticket_counter WHERE guild_id=?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row else 1

async def save_ticket(channel_id, guild_id, user_id, ticket_type, ticket_number):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO tickets
                (channel_id, guild_id, user_id, ticket_type, status, created_at, ticket_number)
            VALUES (?, ?, ?, ?, 'open', ?, ?)
            """,
            (channel_id, guild_id, user_id, ticket_type,
             datetime.datetime.now().timestamp(), ticket_number),
        )
        await db.commit()

async def get_ticket(channel_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT * FROM tickets WHERE channel_id=?", (channel_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return {
        "channel_id":    row[0], "guild_id":      row[1],
        "user_id":       row[2], "ticket_type":   row[3],
        "status":        row[4], "attendant_id":  row[5],
        "created_at":    row[6], "ticket_number": row[7],
    }

async def update_ticket(channel_id: int, **kwargs):
    if not kwargs:
        return
    sets   = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [channel_id]
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(f"UPDATE tickets SET {sets} WHERE channel_id=?", values)
        await db.commit()

# ══════════════════════════════════════════════════════════════
#  HELPERS — LOGS & TRANSCRIPT
# ══════════════════════════════════════════════════════════════
async def send_log(guild: discord.Guild, embed: discord.Embed, file: discord.File = None):
    cfg        = get_guild_config(guild.id)
    channel_id = cfg.get("log_channel")
    if not channel_id:
        return
    ch = guild.get_channel(channel_id)
    if not ch:
        return
    try:
        if file:
            await ch.send(embed=embed, file=file)
        else:
            await ch.send(embed=embed)
    except Exception as e:
        log.warning(f"Falha ao enviar log: {e}")

async def build_transcript(channel: discord.TextChannel, ticket: dict) -> bytes:
    lines = []
    sep   = "=" * 60

    lines += [
        sep,
        f"TRANSCRIPT — Ticket #{ticket.get('ticket_number', '?')}",
        f"Tipo    : {ticket.get('ticket_type', '?')}",
        f"Canal   : #{channel.name}",
        f"Servidor: {channel.guild.name}",
        f"Criado  : {datetime.datetime.fromtimestamp(ticket.get('created_at', 0)).strftime('%d/%m/%Y %H:%M:%S')}",
        f"Gerado  : {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
        sep,
        "",
    ]

    messages = [m async for m in channel.history(limit=None, oldest_first=True)]
    for msg in messages:
        ts     = msg.created_at.strftime("%H:%M")
        name   = msg.author.display_name
        prefix = f"[{ts}] {name}"

        if msg.content:
            lines.append(f"{prefix}: {msg.content}")
        for emb in msg.embeds:
            lines.append(f"{prefix}: [EMBED: {emb.title or 'sem título'}]")
        for att in msg.attachments:
            lines.append(f"{prefix}: [IMG]: {att.url}")

    return "\n".join(lines).encode("utf-8")

def _staff_check(interaction: discord.Interaction) -> bool:
    """Retorna True se o usuário é staff ou admin."""
    if interaction.user.guild_permissions.administrator:
        return True
    cfg = get_guild_config(interaction.guild.id)
    for key in ("staff_role", "ticket_role"):
        rid = cfg.get(key)
        if rid:
            role = interaction.guild.get_role(rid)
            if role and role in interaction.user.roles:
                return True
    return False

# ══════════════════════════════════════════════════════════════
#  VIEWS — PAINEL DE TICKET
# ══════════════════════════════════════════════════════════════
class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🎫 Abrir Suporte",
        style=discord.ButtonStyle.primary,
        custom_id="ticket:suporte",
    )
    async def open_support(self, interaction: discord.Interaction, _: discord.ui.Button):
        await _create_ticket(interaction, "SUPORTE")

    @discord.ui.button(
        label="💰 Abrir Compra",
        style=discord.ButtonStyle.success,
        custom_id="ticket:compra",
    )
    async def open_purchase(self, interaction: discord.Interaction, _: discord.ui.Button):
        await _create_ticket(interaction, "COMPRA")


# ══════════════════════════════════════════════════════════════
#  VIEWS — AÇÕES DO TICKET
# ══════════════════════════════════════════════════════════════
class TicketActionsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    # ── ✅ ATENDER ─────────────────────────────────────────────
    @discord.ui.button(
        label="✅ Atender",
        style=discord.ButtonStyle.success,
        custom_id="ticket:attend",
    )
    async def attend(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _staff_check(interaction):
            return await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)

        ticket = await get_ticket(interaction.channel.id)
        if not ticket:
            return await interaction.response.send_message("❌ Ticket não encontrado.", ephemeral=True)

        if ticket.get("attendant_id"):
            att = interaction.guild.get_member(ticket["attendant_id"])
            name = att.display_name if att else "alguém"
            return await interaction.response.send_message(
                f"❌ Já está sendo atendido por **{name}**.", ephemeral=True
            )

        await update_ticket(interaction.channel.id, attendant_id=interaction.user.id, status="attending")

        embed = discord.Embed(
            title="✅ Atendimento Iniciado",
            description=f"{interaction.user.mention} está atendendo este ticket.",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(),
        )
        await interaction.response.send_message(embed=embed)

        log_embed = discord.Embed(
            title="👤 Atendimento Iniciado",
            description=(
                f"**Ticket:** #{ticket['ticket_number']}\n"
                f"**Atendente:** {interaction.user.mention}\n"
                f"**Canal:** {interaction.channel.mention}"
            ),
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now(),
        )
        await send_log(interaction.guild, log_embed)

    # ── 🔒 FECHAR ──────────────────────────────────────────────
    @discord.ui.button(
        label="🔒 Fechar",
        style=discord.ButtonStyle.secondary,
        custom_id="ticket:close",
    )
    async def close(self, interaction: discord.Interaction, _: discord.ui.Button):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket:
            return await interaction.response.send_message("❌ Ticket não encontrado.", ephemeral=True)

        is_owner = interaction.user.id == ticket["user_id"]
        if not is_owner and not _staff_check(interaction):
            return await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)

        view  = _ConfirmCloseView(ticket)
        embed = discord.Embed(
            title="🔒 Fechar Ticket?",
            description="Confirma o encerramento deste atendimento?",
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # ── 📩 ENCAMINHAR DM ───────────────────────────────────────
    @discord.ui.button(
        label="📩 Encaminhar DM",
        style=discord.ButtonStyle.primary,
        custom_id="ticket:dm",
    )
    async def send_dm(self, interaction: discord.Interaction, _: discord.ui.Button):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket:
            return await interaction.response.send_message("❌ Ticket não encontrado.", ephemeral=True)

        is_owner = interaction.user.id == ticket["user_id"]
        if not is_owner and not _staff_check(interaction):
            return await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        raw  = await build_transcript(interaction.channel, ticket)
        buf  = io.BytesIO(raw)
        file = discord.File(buf, filename=f"transcript-{ticket['ticket_number']}.txt")

        # Destinatário: atendente → dono do ticket
        target_id = ticket.get("attendant_id") or ticket["user_id"]
        target    = interaction.guild.get_member(target_id)

        dm_embed = discord.Embed(
            title=f"📩 Transcript — Ticket #{ticket['ticket_number']}",
            description=(
                f"**Tipo:** {ticket['ticket_type']}\n"
                f"**Canal:** #{interaction.channel.name}\n"
                f"**Servidor:** {interaction.guild.name}"
            ),
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now(),
        )

        sent_to = "ninguém"
        if target:
            try:
                await target.send(embed=dm_embed, file=file)
                sent_to = target.mention
            except discord.Forbidden:
                pass

        await interaction.followup.send(f"📩 Transcript enviado para {sent_to}.", ephemeral=True)

        # Envia cópia ao canal de logs
        buf.seek(0)
        log_file  = discord.File(buf, filename=f"transcript-{ticket['ticket_number']}.txt")
        log_embed = discord.Embed(
            title="📋 Transcript Enviado via DM",
            description=(
                f"**Ticket:** #{ticket['ticket_number']}\n"
                f"**Enviado para:** {sent_to}\n"
                f"**Por:** {interaction.user.mention}"
            ),
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.now(),
        )
        await send_log(interaction.guild, log_embed, file=log_file)

    # ── 🗑️ DELETAR ─────────────────────────────────────────────
    @discord.ui.button(
        label="🗑️ Deletar",
        style=discord.ButtonStyle.danger,
        custom_id="ticket:delete",
    )
    async def delete(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not _staff_check(interaction):
            return await interaction.response.send_message("❌ Apenas staff pode deletar tickets.", ephemeral=True)

        ticket = await get_ticket(interaction.channel.id)
        if not ticket:
            return await interaction.response.send_message("❌ Ticket não encontrado.", ephemeral=True)

        await interaction.response.send_message("🗑️ Deletando canal em 3 segundos...")

        raw  = await build_transcript(interaction.channel, ticket)
        buf  = io.BytesIO(raw)
        file = discord.File(buf, filename=f"transcript-{ticket['ticket_number']}.txt")

        log_embed = discord.Embed(
            title="🗑️ Ticket Deletado",
            description=(
                f"**Ticket:** #{ticket['ticket_number']}\n"
                f"**Tipo:** {ticket['ticket_type']}\n"
                f"**Deletado por:** {interaction.user.mention}"
            ),
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(),
        )
        await send_log(interaction.guild, log_embed, file=file)

        await asyncio.sleep(3)
        try:
            await interaction.channel.delete(reason=f"Ticket deletado por {interaction.user}")
        except discord.Forbidden:
            await interaction.channel.send("❌ Sem permissão para deletar o canal.")
        except Exception as e:
            log.error(f"Erro ao deletar ticket: {e}")


class _ConfirmCloseView(discord.ui.View):
    def __init__(self, ticket: dict):
        super().__init__(timeout=60)
        self.ticket = ticket

    @discord.ui.button(label="✅ Confirmar", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button):
        ticket  = self.ticket
        channel = interaction.channel

        await update_ticket(channel.id, status="closed")

        # Remove permissão de envio do dono
        owner = interaction.guild.get_member(ticket["user_id"])
        if owner:
            try:
                await channel.set_permissions(owner, send_messages=False, read_messages=True)
            except Exception:
                pass

        closed_embed = discord.Embed(
            title="🔒 Ticket Fechado",
            description=(
                f"Fechado por {interaction.user.mention}.\n"
                "Use **🗑️ Deletar** para apagar ou **📩 DM** para receber o transcript."
            ),
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(),
        )
        await interaction.response.edit_message(embed=closed_embed, view=None)
        await channel.send(embed=closed_embed)

        # Transcript → logs
        raw  = await build_transcript(channel, ticket)
        buf  = io.BytesIO(raw)
        file = discord.File(buf, filename=f"transcript-{ticket['ticket_number']}.txt")

        log_embed = discord.Embed(
            title="🔒 Ticket Fechado",
            description=(
                f"**Ticket:** #{ticket['ticket_number']}\n"
                f"**Tipo:** {ticket['ticket_type']}\n"
                f"**Fechado por:** {interaction.user.mention}"
            ),
            color=discord.Color.orange(),
            timestamp=datetime.datetime.now(),
        )
        await send_log(interaction.guild, log_embed, file=file)

        # DM ao dono do ticket
        if owner:
            try:
                buf.seek(0)
                dm_file  = discord.File(buf, filename=f"transcript-{ticket['ticket_number']}.txt")
                dm_embed = discord.Embed(
                    title=f"🔒 Seu ticket #{ticket['ticket_number']} foi fechado",
                    description=(
                        f"**Servidor:** {interaction.guild.name}\n"
                        f"**Tipo:** {ticket['ticket_type']}\n"
                        "Segue o transcript em anexo."
                    ),
                    color=discord.Color.red(),
                    timestamp=datetime.datetime.now(),
                )
                await owner.send(embed=dm_embed, file=dm_file)
            except discord.Forbidden:
                pass

        self.stop()

    @discord.ui.button(label="❌ Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Cancelado.", embed=None, view=None)
        self.stop()


# ══════════════════════════════════════════════════════════════
#  LÓGICA DE CRIAÇÃO DE TICKET
# ══════════════════════════════════════════════════════════════
async def _create_ticket(interaction: discord.Interaction, ticket_type: str):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    user  = interaction.user
    cfg   = get_guild_config(guild.id)

    # Verifica ticket já aberto
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT channel_id FROM tickets WHERE guild_id=? AND user_id=? AND status IN ('open','attending')",
            (guild.id, user.id),
        ) as cur:
            row = await cur.fetchone()
    if row:
        ch = guild.get_channel(row[0])
        if ch:
            return await interaction.followup.send(
                f"❌ Você já tem um ticket aberto: {ch.mention}", ephemeral=True
            )

    # Categoria
    category = None
    cat_id   = cfg.get("ticket_category")
    if cat_id:
        category = guild.get_channel(cat_id)

    ticket_num = await next_ticket_number(guild.id)

    # Permissões do canal
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(
            read_messages=True, send_messages=True,
            attach_files=True, embed_links=True,
        ),
        guild.me: discord.PermissionOverwrite(
            read_messages=True, send_messages=True,
            manage_channels=True, manage_messages=True,
        ),
    }
    for key in ("staff_role", "ticket_role"):
        rid = cfg.get(key)
        if rid:
            role = guild.get_role(rid)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    read_messages=True, send_messages=True,
                    attach_files=True, embed_links=True,
                )

    channel_name = f"ticket-{user.name.lower().replace(' ', '-')[:20]}-{ticket_num}"
    try:
        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            reason=f"Ticket #{ticket_num} — {user}",
        )
    except discord.Forbidden:
        return await interaction.followup.send("❌ Sem permissão para criar canal.", ephemeral=True)
    except Exception as e:
        log.error(f"Erro ao criar canal de ticket: {e}")
        return await interaction.followup.send(f"❌ Erro inesperado: {e}", ephemeral=True)

    await save_ticket(channel.id, guild.id, user.id, ticket_type, ticket_num)

    color = discord.Color.blue() if ticket_type == "SUPORTE" else discord.Color.green()
    icon  = "🎫" if ticket_type == "SUPORTE" else "💰"

    embed = discord.Embed(
        title=f"{icon} Ticket de {ticket_type} — #{ticket_num}",
        description=(
            f"Olá {user.mention}, bem-vindo ao seu ticket!\n\n"
            f"**Tipo:** {ticket_type}\n"
            f"**Criado por:** {user.mention}\n"
            f"**Data:** {datetime.datetime.now().strftime('%d/%m/%Y às %H:%M')}\n\n"
            "Nossa equipe irá atendê-lo em breve.\n"
            "Descreva seu problema ou solicitação abaixo. 👇"
        ),
        color=color,
        timestamp=datetime.datetime.now(),
    )
    embed.set_footer(text=f"Ticket #{ticket_num} • {guild.name}")

    await channel.send(content=user.mention, embed=embed, view=TicketActionsView())
    await interaction.followup.send(f"✅ Ticket criado com sucesso: {channel.mention}", ephemeral=True)

    log_embed = discord.Embed(
        title="🎫 Ticket Criado",
        description=(
            f"**Ticket:** #{ticket_num}\n"
            f"**Tipo:** {ticket_type}\n"
            f"**Usuário:** {user.mention}\n"
            f"**Canal:** {channel.mention}"
        ),
        color=discord.Color.green(),
        timestamp=datetime.datetime.now(),
    )
    await send_log(guild, log_embed)
    log.info(f"Ticket #{ticket_num} criado por {user} em {guild.name}")


# ══════════════════════════════════════════════════════════════
#  BOT — SETUP
# ══════════════════════════════════════════════════════════════
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

_xp_cooldowns: dict[tuple, float] = {}  # (user_id, guild_id) → timestamp


# ══════════════════════════════════════════════════════════════
#  EVENTOS
# ══════════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    await init_db()

    # Registra views persistentes (sobrevivem a reinicializações)
    bot.add_view(TicketPanelView())
    bot.add_view(TicketActionsView())

    try:
        synced = await bot.tree.sync()
        log.info(f"✅ {len(synced)} comando(s) slash sincronizados.")
    except Exception as e:
        log.error(f"Erro ao sincronizar comandos: {e}")

    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="os tickets 🎫")
    )
    log.info(f"🤖 Bot online como {bot.user} (ID: {bot.user.id})")
    log.info(f"📡 Servidores: {len(bot.guilds)}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    # ─── XP por mensagem com cooldown ──────────────────────────
    key  = (message.author.id, message.guild.id)
    now  = datetime.datetime.now().timestamp()
    last = _xp_cooldowns.get(key, 0.0)

    if now - last >= XP_COOLDOWN:
        _xp_cooldowns[key] = now
        gained = random.randint(XP_PER_MESSAGE - 3, XP_PER_MESSAGE + 5)
        leveled, _, new_level = await add_xp(message.author.id, message.guild.id, gained)

        # Atualiza timestamp no banco
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute(
                "UPDATE xp SET last_msg=? WHERE user_id=? AND guild_id=?",
                (now, message.author.id, message.guild.id),
            )
            await db.commit()

        if leveled:
            embed = discord.Embed(
                title="🎉 Level Up!",
                description=f"{message.author.mention} subiu para o **Nível {new_level}**! 🚀",
                color=discord.Color.gold(),
            )
            try:
                await message.channel.send(embed=embed, delete_after=15)
            except Exception:
                pass

            # Cargo por nível, se configurado
            cfg = get_guild_config(message.guild.id)
            rid = cfg.get("level_roles", {}).get(str(new_level))
            if rid:
                role = message.guild.get_role(rid)
                if role:
                    try:
                        await message.author.add_roles(role, reason=f"Level {new_level}")
                    except Exception:
                        pass

    await bot.process_commands(message)


@bot.event
async def on_member_join(member: discord.Member):
    cfg = get_guild_config(member.guild.id)
    cid = cfg.get("welcome_channel")
    if not cid:
        return
    ch = member.guild.get_channel(cid)
    if not ch:
        return

    embed = discord.Embed(
        title=f"👋 Bem-vindo(a), {member.display_name}!",
        description=(
            f"Seja bem-vindo(a) ao **{member.guild.name}**, {member.mention}!\n\n"
            f"Você é o membro **#{member.guild.member_count}**.\n"
            "Leia as regras e aproveite a comunidade! 🎮"
        ),
        color=discord.Color.green(),
        timestamp=datetime.datetime.now(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    if member.guild.icon:
        embed.set_footer(text=member.guild.name, icon_url=member.guild.icon.url)
    try:
        await ch.send(embed=embed)
    except Exception as e:
        log.warning(f"Falha ao enviar boas-vindas: {e}")


# ══════════════════════════════════════════════════════════════
#  CHECAGEM — STAFF
# ══════════════════════════════════════════════════════════════
def mod_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        if _staff_check(interaction):
            return True
        raise app_commands.MissingPermissions(["staff"])
    return app_commands.check(predicate)


# ══════════════════════════════════════════════════════════════
#  COMANDOS — CONFIGURAÇÃO
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="set_staff_role", description="Define o cargo de staff")
@app_commands.describe(cargo="Cargo de staff")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_set_staff_role(interaction: discord.Interaction, cargo: discord.Role):
    set_guild_config(interaction.guild.id, "staff_role", cargo.id)
    await interaction.response.send_message(f"✅ Cargo de **staff** definido: {cargo.mention}", ephemeral=True)


@bot.tree.command(name="set_ticket_role", description="Define o cargo de atendente de tickets")
@app_commands.describe(cargo="Cargo de atendente")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_set_ticket_role(interaction: discord.Interaction, cargo: discord.Role):
    set_guild_config(interaction.guild.id, "ticket_role", cargo.id)
    await interaction.response.send_message(f"✅ Cargo de **atendente** definido: {cargo.mention}", ephemeral=True)


@bot.tree.command(name="set_support_role", description="Define o cargo de suporte (alias)")
@app_commands.describe(cargo="Cargo de suporte")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_set_support_role(interaction: discord.Interaction, cargo: discord.Role):
    set_guild_config(interaction.guild.id, "ticket_role", cargo.id)
    await interaction.response.send_message(f"✅ Cargo de **suporte** definido: {cargo.mention}", ephemeral=True)


@bot.tree.command(name="set_log_channel", description="Define o canal de logs")
@app_commands.describe(canal="Canal de logs")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_set_log_channel(interaction: discord.Interaction, canal: discord.TextChannel):
    set_guild_config(interaction.guild.id, "log_channel", canal.id)
    await interaction.response.send_message(f"✅ Canal de **logs** definido: {canal.mention}", ephemeral=True)


@bot.tree.command(name="set_ticket_category", description="Define a categoria dos tickets")
@app_commands.describe(categoria="Categoria dos tickets")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_set_ticket_category(interaction: discord.Interaction, categoria: discord.CategoryChannel):
    set_guild_config(interaction.guild.id, "ticket_category", categoria.id)
    await interaction.response.send_message(f"✅ Categoria de **tickets** definida: **{categoria.name}**", ephemeral=True)


@bot.tree.command(name="set_welcome_channel", description="Define o canal de boas-vindas")
@app_commands.describe(canal="Canal de boas-vindas")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_set_welcome_channel(interaction: discord.Interaction, canal: discord.TextChannel):
    set_guild_config(interaction.guild.id, "welcome_channel", canal.id)
    await interaction.response.send_message(f"✅ Canal de **boas-vindas** definido: {canal.mention}", ephemeral=True)


@bot.tree.command(name="config", description="Exibe as configurações atuais do servidor")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_config(interaction: discord.Interaction):
    cfg   = get_guild_config(interaction.guild.id)
    guild = interaction.guild

    def role_str(rid):
        if not rid:
            return "❌ Não definido"
        r = guild.get_role(rid)
        return r.mention if r else f"❌ Removido (ID {rid})"

    def ch_str(cid):
        if not cid:
            return "❌ Não definido"
        c = guild.get_channel(cid)
        return c.mention if c else f"❌ Removido (ID {cid})"

    embed = discord.Embed(
        title="⚙️ Configurações do Servidor",
        color=discord.Color.blurple(),
        timestamp=datetime.datetime.now(),
    )
    embed.add_field(name="👥 Cargo Staff",       value=role_str(cfg.get("staff_role")),    inline=True)
    embed.add_field(name="🎫 Cargo Atendente",   value=role_str(cfg.get("ticket_role")),   inline=True)
    embed.add_field(name="📋 Canal Logs",        value=ch_str(cfg.get("log_channel")),     inline=True)
    embed.add_field(name="📁 Categoria Tickets", value=ch_str(cfg.get("ticket_category")), inline=True)
    embed.add_field(name="👋 Canal Boas-vindas", value=ch_str(cfg.get("welcome_channel")), inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  COMANDOS — TICKETS
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="ticketpanel", description="Envia o painel de abertura de tickets")
@app_commands.checks.has_permissions(manage_channels=True)
async def cmd_ticketpanel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎫 Central de Atendimento",
        description=(
            "Precisa de ajuda ou quer adquirir algo? Abra um ticket!\n\n"
            "**🎫 Suporte** — Dúvidas, bugs, problemas\n"
            "**💰 Compra** — Produtos e serviços\n\n"
            "Selecione uma opção abaixo:"
        ),
        color=discord.Color.blurple(),
        timestamp=datetime.datetime.now(),
    )
    embed.set_footer(text="Clique no botão para abrir um ticket")
    await interaction.response.send_message(embed=embed, view=TicketPanelView())


# ══════════════════════════════════════════════════════════════
#  COMANDOS — XP / RANK
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="rank", description="Veja seu nível e progresso de XP")
@app_commands.describe(usuario="Usuário (opcional)")
async def cmd_rank(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
    target = usuario or interaction.user
    data   = await get_xp(target.id, interaction.guild.id)

    needed   = xp_for_level(data["level"])
    progress = int((data["xp"] / needed) * 20) if needed else 20
    bar      = "█" * progress + "░" * (20 - progress)

    # Posição no ranking
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            """
            SELECT COUNT(*) FROM xp
            WHERE guild_id=? AND (level > ? OR (level = ? AND xp >= ?))
            """,
            (interaction.guild.id, data["level"], data["level"], data["xp"]),
        ) as cur:
            pos = (await cur.fetchone())[0]

    embed = discord.Embed(
        title=f"📊 Rank — {target.display_name}",
        color=discord.Color.gold(),
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="🏆 Nível",     value=f"**{data['level']}**",        inline=True)
    embed.add_field(name="🏅 Posição",   value=f"**#{pos}**",                  inline=True)
    embed.add_field(name="⭐ XP",        value=f"**{data['xp']:,} / {needed:,}**", inline=True)
    embed.add_field(name="📈 Progresso", value=f"`{bar}`", inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="leaderboard", description="Top 10 usuários por XP do servidor")
async def cmd_leaderboard(interaction: discord.Interaction):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT user_id, level, xp FROM xp WHERE guild_id=? ORDER BY level DESC, xp DESC LIMIT 10",
            (interaction.guild.id,),
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        return await interaction.response.send_message("❌ Nenhum dado ainda.", ephemeral=True)

    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
    lines  = []
    for i, (uid, lvl, xp_val) in enumerate(rows):
        member = interaction.guild.get_member(uid)
        name   = member.display_name if member else f"Usuário {uid}"
        lines.append(f"{medals[i]} **{name}** — Nível **{lvl}** · {xp_val:,} XP")

    embed = discord.Embed(
        title=f"🏆 Leaderboard — {interaction.guild.name}",
        description="\n".join(lines),
        color=discord.Color.gold(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="setlevelrole", description="Atribui um cargo para um nível específico")
@app_commands.describe(nivel="Nível", cargo="Cargo a conceder")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_setlevelrole(interaction: discord.Interaction, nivel: int, cargo: discord.Role):
    cfg = get_guild_config(interaction.guild.id)
    lr  = cfg.get("level_roles", {})
    lr[str(nivel)] = cargo.id
    set_guild_config(interaction.guild.id, "level_roles", lr)
    await interaction.response.send_message(
        f"✅ Nível **{nivel}** → {cargo.mention}", ephemeral=True
    )


# ══════════════════════════════════════════════════════════════
#  COMANDOS — ECONOMIA
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="balance", description="Veja seu saldo ou o de outro usuário")
@app_commands.describe(usuario="Usuário (opcional)")
async def cmd_balance(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
    target = usuario or interaction.user
    data   = await get_balance(target.id, interaction.guild.id)
    embed  = discord.Embed(
        title=f"💰 Saldo — {target.display_name}",
        description=f"**{data['balance']:,}** 🪙",
        color=discord.Color.gold(),
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="daily", description="Colete seu bônus diário (24h de cooldown)")
async def cmd_daily(interaction: discord.Interaction):
    data     = await get_balance(interaction.user.id, interaction.guild.id)
    now      = datetime.datetime.now().timestamp()
    cooldown = 86_400  # 24h

    remaining = cooldown - (now - data["last_daily"])
    if remaining > 0:
        h, rem = divmod(int(remaining), 3600)
        m      = rem // 60
        return await interaction.response.send_message(
            f"⏳ Próximo daily em **{h}h {m}m**.", ephemeral=True
        )

    bonus = DAILY_AMOUNT + random.randint(0, 200)
    await add_balance(interaction.user.id, interaction.guild.id, bonus)
    await _set_eco_ts(interaction.user.id, interaction.guild.id, "last_daily", now)

    embed = discord.Embed(
        title="✅ Daily Coletado!",
        description=f"Você recebeu **{bonus:,}** 🪙\nVolte amanhã para mais!",
        color=discord.Color.green(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="work", description="Trabalhe para ganhar moedas (1h de cooldown)")
async def cmd_work(interaction: discord.Interaction):
    data     = await get_balance(interaction.user.id, interaction.guild.id)
    now      = datetime.datetime.now().timestamp()
    cooldown = 3_600  # 1h

    remaining = cooldown - (now - data["last_work"])
    if remaining > 0:
        m = int(remaining // 60)
        return await interaction.response.send_message(
            f"⏳ Próximo trabalho em **{m}min**.", ephemeral=True
        )

    jobs = [
        "programou um bot incrível", "fez uma entrega relâmpago",
        "ganhou no poker online", "vendeu scripts exclusivos",
        "completou uma missão secreta", "tocou guitarra na praça",
        "venceu um torneio de chess.com",
    ]
    earned = random.randint(WORK_MIN, WORK_MAX)
    await add_balance(interaction.user.id, interaction.guild.id, earned)
    await _set_eco_ts(interaction.user.id, interaction.guild.id, "last_work", now)

    embed = discord.Embed(
        title="💼 Trabalho Concluído!",
        description=f"Você **{random.choice(jobs)}** e ganhou **{earned:,}** 🪙",
        color=discord.Color.green(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="transfer", description="Transfira moedas para outro usuário")
@app_commands.describe(usuario="Destinatário", valor="Quantia a transferir")
async def cmd_transfer(interaction: discord.Interaction, usuario: discord.Member, valor: int):
    if valor <= 0:
        return await interaction.response.send_message("❌ Valor deve ser positivo.", ephemeral=True)
    if usuario.bot or usuario.id == interaction.user.id:
        return await interaction.response.send_message("❌ Destinatário inválido.", ephemeral=True)

    data = await get_balance(interaction.user.id, interaction.guild.id)
    if data["balance"] < valor:
        return await interaction.response.send_message(
            f"❌ Saldo insuficiente. Você tem **{data['balance']:,}** 🪙", ephemeral=True
        )

    await add_balance(interaction.user.id, interaction.guild.id, -valor)
    await add_balance(usuario.id, interaction.guild.id, valor)

    embed = discord.Embed(
        title="💸 Transferência Realizada",
        description=(
            f"**De:** {interaction.user.mention}\n"
            f"**Para:** {usuario.mention}\n"
            f"**Valor:** {valor:,} 🪙"
        ),
        color=discord.Color.green(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="shop", description="Veja os itens disponíveis na loja")
async def cmd_shop(interaction: discord.Interaction):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT id, item_name, item_price, role_id FROM shop WHERE guild_id=?",
            (interaction.guild.id,),
        ) as cur:
            items = await cur.fetchall()

    if not items:
        return await interaction.response.send_message("🏪 A loja está vazia.", ephemeral=True)

    embed = discord.Embed(title="🏪 Loja do Servidor", color=discord.Color.gold())
    for iid, name, price, rid in items:
        role = interaction.guild.get_role(rid) if rid else None
        extra = f" → {role.mention}" if role else ""
        embed.add_field(name=f"#{iid} · {name}", value=f"**{price:,}** 🪙{extra}", inline=False)
    embed.set_footer(text="Use /buy <id> para comprar")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="buy", description="Compre um item da loja pelo ID")
@app_commands.describe(item_id="ID do item (use /shop para ver)")
async def cmd_buy(interaction: discord.Interaction, item_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT item_name, item_price, role_id FROM shop WHERE id=? AND guild_id=?",
            (item_id, interaction.guild.id),
        ) as cur:
            item = await cur.fetchone()

    if not item:
        return await interaction.response.send_message("❌ Item não encontrado.", ephemeral=True)

    name, price, rid = item
    data = await get_balance(interaction.user.id, interaction.guild.id)
    if data["balance"] < price:
        return await interaction.response.send_message(
            f"❌ Saldo insuficiente. Você tem **{data['balance']:,}** 🪙", ephemeral=True
        )

    await add_balance(interaction.user.id, interaction.guild.id, -price)

    if rid:
        role = interaction.guild.get_role(rid)
        if role:
            try:
                await interaction.user.add_roles(role, reason=f"Compra loja: {name}")
            except Exception:
                pass

    embed = discord.Embed(
        title="✅ Compra Realizada!",
        description=f"Você adquiriu **{name}** por **{price:,}** 🪙",
        color=discord.Color.green(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="additem", description="Adiciona um item à loja")
@app_commands.describe(nome="Nome do item", preco="Preço em moedas", cargo="Cargo concedido (opcional)")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_additem(
    interaction: discord.Interaction, nome: str, preco: int, cargo: Optional[discord.Role] = None
):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT INTO shop (guild_id, item_name, item_price, role_id) VALUES (?, ?, ?, ?)",
            (interaction.guild.id, nome, preco, cargo.id if cargo else None),
        )
        await db.commit()
    await interaction.response.send_message(
        f"✅ **{nome}** adicionado à loja por **{preco:,}** 🪙.", ephemeral=True
    )


@bot.tree.command(name="removeitem", description="Remove um item da loja")
@app_commands.describe(item_id="ID do item")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_removeitem(interaction: discord.Interaction, item_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "DELETE FROM shop WHERE id=? AND guild_id=?", (item_id, interaction.guild.id)
        )
        await db.commit()
    await interaction.response.send_message(f"✅ Item #{item_id} removido.", ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  COMANDOS — MODERAÇÃO
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="ban", description="Bane um usuário do servidor")
@app_commands.describe(usuario="Usuário a ser banido", motivo="Motivo")
@mod_check()
async def cmd_ban(interaction: discord.Interaction, usuario: discord.Member, motivo: str = "Sem motivo"):
    if usuario.top_role >= interaction.user.top_role and not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Hierarquia insuficiente.", ephemeral=True)
    try:
        await usuario.ban(reason=f"{motivo} | Mod: {interaction.user}")
        embed = discord.Embed(
            title="🔨 Usuário Banido",
            description=f"**Usuário:** {usuario.mention}\n**Motivo:** {motivo}\n**Mod:** {interaction.user.mention}",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed)
        await send_log(interaction.guild, embed)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Sem permissão para banir.", ephemeral=True)


@bot.tree.command(name="kick", description="Expulsa um usuário do servidor")
@app_commands.describe(usuario="Usuário", motivo="Motivo")
@mod_check()
async def cmd_kick(interaction: discord.Interaction, usuario: discord.Member, motivo: str = "Sem motivo"):
    if usuario.top_role >= interaction.user.top_role and not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Hierarquia insuficiente.", ephemeral=True)
    try:
        await usuario.kick(reason=f"{motivo} | Mod: {interaction.user}")
        embed = discord.Embed(
            title="👢 Usuário Expulso",
            description=f"**Usuário:** {usuario.mention}\n**Motivo:** {motivo}\n**Mod:** {interaction.user.mention}",
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed)
        await send_log(interaction.guild, embed)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)


@bot.tree.command(name="mute", description="Silencia um usuário temporariamente")
@app_commands.describe(usuario="Usuário", minutos="Duração em minutos", motivo="Motivo")
@mod_check()
async def cmd_mute(
    interaction: discord.Interaction,
    usuario: discord.Member,
    minutos: app_commands.Range[int, 1, 40320] = 10,
    motivo: str = "Sem motivo",
):
    try:
        until = discord.utils.utcnow() + datetime.timedelta(minutes=minutos)
        await usuario.timeout(until, reason=f"{motivo} | Mod: {interaction.user}")
        embed = discord.Embed(
            title="🔇 Usuário Silenciado",
            description=(
                f"**Usuário:** {usuario.mention}\n"
                f"**Duração:** {minutos}min\n"
                f"**Motivo:** {motivo}\n"
                f"**Mod:** {interaction.user.mention}"
            ),
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed)
        await send_log(interaction.guild, embed)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)


@bot.tree.command(name="unmute", description="Remove o timeout de um usuário")
@app_commands.describe(usuario="Usuário")
@mod_check()
async def cmd_unmute(interaction: discord.Interaction, usuario: discord.Member):
    try:
        await usuario.timeout(None)
        await interaction.response.send_message(f"✅ {usuario.mention} desmutado.")
    except discord.Forbidden:
        await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)


@bot.tree.command(name="clear", description="Apaga mensagens do canal")
@app_commands.describe(quantidade="Quantidade de mensagens (1–100)")
@mod_check()
async def cmd_clear(interaction: discord.Interaction, quantidade: app_commands.Range[int, 1, 100] = 10):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=quantidade)
    await interaction.followup.send(f"✅ **{len(deleted)}** mensagem(ns) apagada(s).", ephemeral=True)


@bot.tree.command(name="warn", description="Registra um aviso para um usuário")
@app_commands.describe(usuario="Usuário", motivo="Motivo do aviso")
@mod_check()
async def cmd_warn(interaction: discord.Interaction, usuario: discord.Member, motivo: str):
    ts = datetime.datetime.now().timestamp()
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT INTO warns (user_id, guild_id, moderator_id, reason, timestamp) VALUES (?, ?, ?, ?, ?)",
            (usuario.id, interaction.guild.id, interaction.user.id, motivo, ts),
        )
        await db.commit()
        async with db.execute(
            "SELECT COUNT(*) FROM warns WHERE user_id=? AND guild_id=?",
            (usuario.id, interaction.guild.id),
        ) as cur:
            total = (await cur.fetchone())[0]

    embed = discord.Embed(
        title="⚠️ Aviso Registrado",
        description=(
            f"**Usuário:** {usuario.mention}\n"
            f"**Motivo:** {motivo}\n"
            f"**Mod:** {interaction.user.mention}\n"
            f"**Total de avisos:** {total}"
        ),
        color=discord.Color.yellow(),
    )
    await interaction.response.send_message(embed=embed)
    await send_log(interaction.guild, embed)

    # DM ao usuário avisado
    try:
        dm_embed = discord.Embed(
            title=f"⚠️ Aviso — {interaction.guild.name}",
            description=f"**Motivo:** {motivo}\n**Total de avisos:** {total}",
            color=discord.Color.yellow(),
        )
        await usuario.send(embed=dm_embed)
    except discord.Forbidden:
        pass


@bot.tree.command(name="warns", description="Lista os avisos de um usuário")
@app_commands.describe(usuario="Usuário")
@mod_check()
async def cmd_warns(interaction: discord.Interaction, usuario: discord.Member):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT moderator_id, reason, timestamp FROM warns WHERE user_id=? AND guild_id=? ORDER BY timestamp DESC LIMIT 10",
            (usuario.id, interaction.guild.id),
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        return await interaction.response.send_message(f"✅ {usuario.mention} não possui avisos.", ephemeral=True)

    embed = discord.Embed(title=f"⚠️ Avisos — {usuario.display_name}", color=discord.Color.yellow())
    for i, (mid, reason, ts) in enumerate(rows, 1):
        mod = interaction.guild.get_member(mid)
        dt  = datetime.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")
        embed.add_field(
            name=f"#{i} — {dt}",
            value=f"**Motivo:** {reason}\n**Mod:** {mod.mention if mod else f'ID {mid}'}",
            inline=False,
        )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="clearwarns", description="Remove todos os avisos de um usuário")
@app_commands.describe(usuario="Usuário")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_clearwarns(interaction: discord.Interaction, usuario: discord.Member):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "DELETE FROM warns WHERE user_id=? AND guild_id=?",
            (usuario.id, interaction.guild.id),
        )
        await db.commit()
    await interaction.response.send_message(f"✅ Avisos de {usuario.mention} removidos.", ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  COMANDOS — DIVERSÃO
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="8ball", description="Faça uma pergunta à bola mágica")
@app_commands.describe(pergunta="Sua pergunta")
async def cmd_8ball(interaction: discord.Interaction, pergunta: str):
    respostas = [
        "✅ Com certeza!", "✅ Definitivamente sim.", "✅ Sem dúvidas.",
        "✅ Sim, pode apostar!", "✅ Parece muito provável.",
        "🤔 Não sei dizer agora.", "🤔 Tente novamente.", "🤔 Difícil de prever.",
        "🤔 Melhor não contar com isso por enquanto.",
        "❌ Não acho que sim.", "❌ Minha resposta é não.", "❌ Perspectivas ruins.",
    ]
    embed = discord.Embed(title="🎱 Bola 8 Mágica", color=discord.Color.dark_blue())
    embed.add_field(name="❓ Pergunta", value=pergunta, inline=False)
    embed.add_field(name="🎱 Resposta", value=random.choice(respostas), inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="ship", description="Calcula a compatibilidade entre dois usuários")
@app_commands.describe(usuario1="Primeiro usuário", usuario2="Segundo usuário")
async def cmd_ship(
    interaction: discord.Interaction, usuario1: discord.Member, usuario2: discord.Member
):
    seed = usuario1.id + usuario2.id
    random.seed(seed)
    pct = random.randint(0, 100)
    random.seed()

    if pct >= 80:   emoji, comment = "💕", "Match perfeito! 🔥"
    elif pct >= 60: emoji, comment = "💖", "Muito compatíveis!"
    elif pct >= 40: emoji, comment = "💛", "Tem potencial..."
    elif pct >= 20: emoji, comment = "🤍", "Precisa de trabalho."
    else:           emoji, comment = "💔", "Péssima combinação!"

    filled = int(pct / 5)
    bar    = "❤️" * filled + "🖤" * (20 - filled)

    embed = discord.Embed(
        title=f"{emoji} {usuario1.display_name} ❤️ {usuario2.display_name}",
        description=f"**{pct}%** de compatibilidade!\n{comment}\n\n{bar}",
        color=discord.Color.red(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="meme", description="Receba um meme aleatório do Reddit")
async def cmd_meme(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://meme-api.com/gimme", timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return await interaction.followup.send("❌ API indisponível.", ephemeral=True)
                data = await resp.json()

        embed = discord.Embed(
            title=data.get("title", "Meme"),
            url=data.get("postLink", ""),
            color=discord.Color.random(),
        )
        embed.set_image(url=data.get("url", ""))
        embed.set_footer(text=f"👍 {data.get('ups', 0):,} · r/{data.get('subreddit', 'memes')}")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        log.error(f"Erro em /meme: {e}")
        await interaction.followup.send("❌ Não foi possível buscar um meme.", ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  COMANDOS — UTILITÁRIOS
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="ping", description="Latência do bot")
async def cmd_ping(interaction: discord.Interaction):
    ms    = round(bot.latency * 1000)
    color = discord.Color.green() if ms < 100 else discord.Color.yellow() if ms < 200 else discord.Color.red()
    embed = discord.Embed(title="🏓 Pong!", description=f"Latência: **{ms}ms**", color=color)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="avatar", description="Exibe o avatar de um usuário")
@app_commands.describe(usuario="Usuário (opcional)")
async def cmd_avatar(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
    target = usuario or interaction.user
    embed  = discord.Embed(title=f"🖼️ Avatar — {target.display_name}", color=discord.Color.blurple())
    embed.set_image(url=target.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="serverinfo", description="Informações detalhadas do servidor")
async def cmd_serverinfo(interaction: discord.Interaction):
    g = interaction.guild
    embed = discord.Embed(
        title=f"📋 {g.name}",
        color=discord.Color.blurple(),
        timestamp=datetime.datetime.now(),
    )
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name="👑 Dono",      value=g.owner.mention if g.owner else "N/A", inline=True)
    embed.add_field(name="👥 Membros",   value=f"{g.member_count:,}",                 inline=True)
    embed.add_field(name="📅 Criado em", value=g.created_at.strftime("%d/%m/%Y"),     inline=True)
    embed.add_field(name="💬 Canais",    value=len(g.text_channels),                  inline=True)
    embed.add_field(name="🎙️ Voz",      value=len(g.voice_channels),                 inline=True)
    embed.add_field(name="🎭 Cargos",    value=len(g.roles),                          inline=True)
    embed.set_footer(text=f"ID: {g.id}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="userinfo", description="Informações de um usuário")
@app_commands.describe(usuario="Usuário (opcional)")
async def cmd_userinfo(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
    t     = usuario or interaction.user
    roles = [r.mention for r in reversed(t.roles) if r.name != "@everyone"][:8]

    embed = discord.Embed(
        title=f"👤 {t.display_name}",
        color=t.color,
        timestamp=datetime.datetime.now(),
    )
    embed.set_thumbnail(url=t.display_avatar.url)
    embed.add_field(name="🆔 ID",         value=t.id,                                                   inline=True)
    embed.add_field(name="📅 Conta",      value=t.created_at.strftime("%d/%m/%Y"),                     inline=True)
    embed.add_field(name="📥 Entrou em",  value=t.joined_at.strftime("%d/%m/%Y") if t.joined_at else "N/A", inline=True)
    embed.add_field(name=f"🎭 Cargos ({len(roles)})", value=" ".join(roles) or "Nenhum", inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="help", description="Lista todos os comandos disponíveis")
async def cmd_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 Comandos Disponíveis",
        color=discord.Color.blurple(),
        timestamp=datetime.datetime.now(),
    )
    embed.add_field(
        name="⚙️ Configuração",
        value="`/config` `/set_staff_role` `/set_ticket_role` `/set_log_channel` `/set_ticket_category` `/set_welcome_channel`",
        inline=False,
    )
    embed.add_field(
        name="🎫 Tickets",
        value="`/ticketpanel`",
        inline=False,
    )
    embed.add_field(
        name="💬 XP / Rank",
        value="`/rank` `/leaderboard` `/setlevelrole`",
        inline=False,
    )
    embed.add_field(
        name="💰 Economia",
        value="`/balance` `/daily` `/work` `/transfer` `/shop` `/buy` `/additem` `/removeitem`",
        inline=False,
    )
    embed.add_field(
        name="🛠️ Moderação",
        value="`/ban` `/kick` `/mute` `/unmute` `/clear` `/warn` `/warns` `/clearwarns`",
        inline=False,
    )
    embed.add_field(
        name="😂 Diversão",
        value="`/meme` `/8ball` `/ship`",
        inline=False,
    )
    embed.add_field(
        name="🔧 Utilitários",
        value="`/ping` `/avatar` `/serverinfo` `/userinfo` `/help`",
        inline=False,
    )
    embed.set_footer(text="Bot de tickets profissional")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  TRATAMENTO GLOBAL DE ERROS
# ══════════════════════════════════════════════════════════════
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ Você não tem permissão para usar este comando."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = "❌ Eu não tenho as permissões necessárias para executar isso."
    elif isinstance(error, app_commands.CommandOnCooldown):
        msg = f"⏳ Aguarde **{error.retry_after:.1f}s** antes de usar novamente."
    elif isinstance(error, app_commands.CheckFailure):
        msg = "❌ Você não tem permissão para usar este comando."
    else:
        msg = f"❌ Ocorreu um erro inesperado: `{type(error).__name__}`"
        log.error(f"Erro no comando '{interaction.command}': {error}", exc_info=True)

    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if not TOKEN:
        log.critical("❌ DISCORD_TOKEN não encontrado! Defina a variável de ambiente.")
        raise SystemExit(1)

    log.info("🚀 Iniciando bot...")
    bot.run(TOKEN, log_handler=None)
