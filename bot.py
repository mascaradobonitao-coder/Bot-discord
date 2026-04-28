import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import Button, View, Modal, TextInput, Select
import json
import re
import sqlite3
import hashlib
import time
from collections import defaultdict, deque
import os
import asyncio
import random
import string
import shutil
import platform
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('Bot')

DAILY_MIN = 500
DAILY_MAX = 1500
WORK_MIN = 100
WORK_MAX = 600
XP_MIN = 10
XP_MAX = 25

PROFISSOES = [
    'Desenvolvedor 💻', 'Designer 🎨', 'Streamer 🎮', 'YouTuber 📹',
    'Músico 🎵', 'Chef 👨‍🍳', 'Médico 👨‍⚕️', 'Professor 👨‍🏫',
    'Engenheiro 👷', 'Advogado ⚖️', 'Policial 👮', 'Bombeiro 🚒'
]

TIERS = {
    1: {'nome': 'Ovo',     'emoji': '🥚', 'requisito': 0},
    2: {'nome': 'Pintinho', 'emoji': '🐥', 'requisito': 10000},
    3: {'nome': 'Frango',  'emoji': '🐤', 'requisito': 50000},
    4: {'nome': 'Águia',   'emoji': '🦅', 'requisito': 200000},
    5: {'nome': 'Lenda',   'emoji': '👑', 'requisito': 1000000},
}

LEAGUE_LIMITS = {'2v2': 4, '3v3': 6, '4v4': 8}

LEAGUE_RULES = [
    '1. Respeite todos os participantes',
    '2. Sem trapaças ou exploits',
    '3. O admin tem a palavra final',
    '4. Seja pontual nos jogos',
    '5. Screenshots/vídeos são bem-vindos como prova',
    '6. Em caso de desconexão, o jogo deve ser refeito',
    '7. Comportamento tóxico resulta em desqualificação',
    '8. Respeite o resultado, ganhar ou perder faz parte',
]

JSON_FILES = [
    'config_data.json', 'users_data.json', 'verification_data.json',
    'warnings_data.json', 'ban_data.json', 'cases_data.json',
    'mute_data.json', 'logs_data.json', 'leagues_data.json',
    'league_members.json', 'league_config.json', 'economy_data.json',
    'levels_data.json', 'cooldowns_data.json', 'giveaways_data.json',
    'polls_data.json', 'suggestions_data.json', 'reports_data.json',
    'appeals_data.json', 'tags_data.json', 'events_data.json',
    'reminders_data.json', 'tickets_data.json', 'ticket_config.json',
    'stats_data.json', 'announce_config.json',
]


class DiscordBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix='!', intents=intents, help_command=None)
        self.start_time = datetime.now()
        self.verification_codes: Dict[str, Any] = {}
        self.mensagens_processadas: int = 0
        self.versao = '3.0.0'
        # ── Caches em memória ─────────────────────────────
        self._xp_cache: Dict[str, Any] = {}          # gid:uid -> level data
        self._config_cache: Dict[str, Any] = {}       # gid -> config
        self._config_dirty: set = set()               # guilds com config alterada
        self._invites_cache: Dict[str, Any] = {}
        # ── Anti-spam por usuário ─────────────────────────
        self._spam_tracker: Dict[str, deque] = defaultdict(deque)  # gid:uid -> deque de timestamps
        self._spam_warn: Dict[str, int] = defaultdict(int)          # gid:uid -> contagem de warns
        # ── Anti-raid ────────────────────────────────────
        self._join_tracker: Dict[str, deque] = defaultdict(deque)  # gid -> deque de timestamps de join
        self._raid_active: Dict[str, bool] = defaultdict(bool)      # gid -> raid ativo?
        # ── Verificação 2 etapas ──────────────────────────
        self.verify_step1: Dict[str, Any] = {}  # uid -> {code, ts, attempts}
        self.verify_step2: Dict[str, Any] = {}  # uid -> {roblox, ts}
        self._init_json()
        self._init_db()

    def _init_json(self):
        for f in JSON_FILES:
            if not os.path.exists(f):
                with open(f, 'w', encoding='utf-8') as fp:
                    json.dump({}, fp, indent=4)

    def _init_db(self):
        """Inicializa SQLite para dados de alta frequência (economia, XP, cooldowns)."""
        self.db = sqlite3.connect('bot_data.db', check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')  # WAL = mais rápido, menos travamentos
        self.db.execute('PRAGMA synchronous=NORMAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS economy (
                guild_id TEXT, user_id TEXT, coins INTEGER DEFAULT 0,
                bank INTEGER DEFAULT 0, total_earned INTEGER DEFAULT 0,
                last_daily TEXT, last_work TEXT,
                PRIMARY KEY (guild_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS levels (
                guild_id TEXT, user_id TEXT, level INTEGER DEFAULT 1,
                xp INTEGER DEFAULT 0, messages INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS cooldowns (
                guild_id TEXT, user_id TEXT, command TEXT, used_at TEXT,
                PRIMARY KEY (guild_id, user_id, command)
            );
        ''')
        self.db.commit()


bot = DiscordBot()


def load_json(filename: str) -> Dict[str, Any]:
    try:
        if not os.path.exists(filename):
            return {}
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f'Erro ao carregar {filename}: {e}')
        return {}


def save_json(filename: str, data: Dict[str, Any]) -> bool:
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f'Erro ao salvar {filename}: {e}')
        return False


def embed_ok(titulo: str, desc: str, user: Optional[discord.User] = None) -> discord.Embed:
    e = discord.Embed(title=f'✅ {titulo}', description=desc, color=0x2ECC71, timestamp=datetime.now())
    if user:
        e.set_footer(text=f'Solicitado por {user.name}', icon_url=user.display_avatar.url)
    return e


def embed_err(titulo: str, desc: str, user: Optional[discord.User] = None) -> discord.Embed:
    e = discord.Embed(title=f'❌ {titulo}', description=desc, color=0xE74C3C, timestamp=datetime.now())
    if user:
        e.set_footer(text=f'Solicitado por {user.name}', icon_url=user.display_avatar.url)
    return e


def embed_info(titulo: str, desc: str, user: Optional[discord.User] = None) -> discord.Embed:
    e = discord.Embed(title=f'ℹ️ {titulo}', description=desc, color=0x3498DB, timestamp=datetime.now())
    if user:
        e.set_footer(text=f'Solicitado por {user.name}', icon_url=user.display_avatar.url)
    return e


def embed_warn(titulo: str, desc: str, user: Optional[discord.User] = None) -> discord.Embed:
    e = discord.Embed(title=f'⚠️ {titulo}', description=desc, color=0xF39C12, timestamp=datetime.now())
    if user:
        e.set_footer(text=f'Solicitado por {user.name}', icon_url=user.display_avatar.url)
    return e


def is_admin_league(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    cfg = load_json('config_data.json').get(str(member.guild.id), {})
    role_id = cfg.get('admin_role_id')
    if role_id:
        return any(str(r.id) == str(role_id) for r in member.roles)
    return False


def is_verified(guild_id: str, user_id: str) -> bool:
    data = load_json('users_data.json')
    return data.get(guild_id, {}).get(user_id, {}).get('verified', False)


def pode_moderar(mod: discord.Member, alvo: discord.Member) -> bool:
    if mod.id == mod.guild.owner_id:
        return True
    if mod.id == alvo.id or alvo.id == mod.guild.owner_id:
        return False
    return mod.top_role.position > alvo.top_role.position


def bot_pode_moderar(bot_member: discord.Member, alvo: discord.Member) -> bool:
    if alvo.id == alvo.guild.owner_id:
        return False
    return bot_member.top_role.position > alvo.top_role.position


def gerar_codigo() -> str:
    return ''.join(random.choices(string.digits, k=6))


def verificar_alt(guild_id: str, roblox_username: str) -> Optional[str]:
    data = load_json('users_data.json')
    roblox_lower = roblox_username.lower()
    for uid, info in data.get(guild_id, {}).items():
        if info.get('roblox_username', '').lower() == roblox_lower:
            return uid
    return None


def gerar_league_id(guild_id: str) -> str:
    data = load_json('leagues_data.json').get(guild_id, {})
    if not data:
        return '1'
    return str(max(int(k) for k in data.keys()) + 1)


def is_league_full(guild_id: str, league_id: str) -> bool:
    members = load_json('league_members.json').get(guild_id, {}).get(league_id, {})
    leagues = load_json('leagues_data.json').get(guild_id, {}).get(league_id, {})
    if not leagues:
        return False
    return len(members) >= LEAGUE_LIMITS.get(leagues.get('modo', '2v2'), 4)


def gerar_case_id(guild_id: str) -> int:
    data = load_json('cases_data.json').get(guild_id, {})
    if not data:
        return 1
    return max(int(k) for k in data.keys()) + 1


def registrar_case(guild_id: str, tipo: str, usuario: discord.Member, moderador: discord.Member, motivo: str, duracao: Optional[str] = None) -> int:
    data = load_json('cases_data.json')
    if guild_id not in data:
        data[guild_id] = {}
    cid = gerar_case_id(guild_id)
    data[guild_id][str(cid)] = {
        'case_id': cid, 'tipo': tipo,
        'usuario_id': str(usuario.id), 'usuario_name': usuario.name,
        'moderador_id': str(moderador.id), 'moderador_name': moderador.name,
        'motivo': motivo, 'duracao': duracao,
        'timestamp': datetime.now().isoformat()
    }
    save_json('cases_data.json', data)
    return cid


# ── SQLite helpers (economia, XP, cooldowns) ─────────────────────────────────
def get_user_economy(guild_id: str, user_id: str) -> Dict[str, Any]:
    try:
        row = bot.db.execute(
            'SELECT coins, bank, total_earned, last_daily, last_work FROM economy WHERE guild_id=? AND user_id=?',
            (guild_id, user_id)
        ).fetchone()
        if row:
            return {'coins': row[0], 'bank': row[1], 'total_earned': row[2], 'last_daily': row[3], 'last_work': row[4]}
        bot.db.execute(
            'INSERT OR IGNORE INTO economy (guild_id, user_id) VALUES (?, ?)', (guild_id, user_id)
        )
        bot.db.commit()
        return {'coins': 0, 'bank': 0, 'total_earned': 0, 'last_daily': None, 'last_work': None}
    except Exception as e:
        logger.error(f'get_user_economy: {e}')
        return {'coins': 0, 'bank': 0, 'total_earned': 0, 'last_daily': None, 'last_work': None}


def save_user_economy(guild_id: str, user_id: str, econ: Dict[str, Any]):
    try:
        bot.db.execute(
            '''INSERT INTO economy (guild_id, user_id, coins, bank, total_earned, last_daily, last_work)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET
               coins=excluded.coins, bank=excluded.bank, total_earned=excluded.total_earned,
               last_daily=excluded.last_daily, last_work=excluded.last_work''',
            (guild_id, user_id, econ.get('coins', 0), econ.get('bank', 0),
             econ.get('total_earned', 0), econ.get('last_daily'), econ.get('last_work'))
        )
        bot.db.commit()
    except Exception as e:
        logger.error(f'save_user_economy: {e}')


def get_user_level(guild_id: str, user_id: str) -> Dict[str, Any]:
    # Primeiro checar cache em memória
    key = f'{guild_id}:{user_id}'
    cache = getattr(bot, '_xp_cache', {})
    if key in cache:
        return cache[key]
    try:
        row = bot.db.execute(
            'SELECT level, xp, messages FROM levels WHERE guild_id=? AND user_id=?',
            (guild_id, user_id)
        ).fetchone()
        if row:
            data = {'level': row[0], 'xp': row[1], 'messages': row[2]}
        else:
            bot.db.execute('INSERT OR IGNORE INTO levels (guild_id, user_id) VALUES (?, ?)', (guild_id, user_id))
            bot.db.commit()
            data = {'level': 1, 'xp': 0, 'messages': 0}
        cache[key] = data
        bot._xp_cache = cache
        return data
    except Exception as e:
        logger.error(f'get_user_level: {e}')
        return {'level': 1, 'xp': 0, 'messages': 0}


def save_user_level(guild_id: str, user_id: str, lv: Dict[str, Any]):
    try:
        bot.db.execute(
            '''INSERT INTO levels (guild_id, user_id, level, xp, messages) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET
               level=excluded.level, xp=excluded.xp, messages=excluded.messages''',
            (guild_id, user_id, lv.get('level', 1), lv.get('xp', 0), lv.get('messages', 0))
        )
        bot.db.commit()
    except Exception as e:
        logger.error(f'save_user_level: {e}')


def pode_usar_cmd_db(guild_id: str, user_id: str, cmd: str, cooldown: int) -> Tuple[bool, Optional[int]]:
    try:
        row = bot.db.execute(
            'SELECT used_at FROM cooldowns WHERE guild_id=? AND user_id=? AND command=?',
            (guild_id, user_id, cmd)
        ).fetchone()
        if not row:
            return True, None
        decorrido = (datetime.now() - datetime.fromisoformat(row[0])).total_seconds()
        if decorrido >= cooldown:
            return True, None
        return False, int(cooldown - decorrido)
    except Exception:
        return True, None


def registrar_cooldown_db(guild_id: str, user_id: str, cmd: str):
    try:
        bot.db.execute(
            '''INSERT INTO cooldowns (guild_id, user_id, command, used_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(guild_id, user_id, command) DO UPDATE SET used_at=excluded.used_at''',
            (guild_id, user_id, cmd, datetime.now().isoformat())
        )
        bot.db.commit()
    except Exception as e:
        logger.error(f'registrar_cooldown_db: {e}')


# ── Config cache ──────────────────────────────────────────────────────────────
def get_config(guild_id: str) -> Dict[str, Any]:
    """Retorna config do servidor com cache em memória."""
    cache = getattr(bot, '_config_cache', {})
    if guild_id in cache:
        return cache[guild_id]
    data = load_json('config_data.json').get(guild_id, {})
    cache[guild_id] = data
    bot._config_cache = cache
    return data


def save_config(guild_id: str, cfg: Dict[str, Any]):
    """Salva config no cache e marca como dirty para flush."""
    cache = getattr(bot, '_config_cache', {})
    cache[guild_id] = cfg
    bot._config_cache = cache
    dirty = getattr(bot, '_config_dirty', set())
    dirty.add(guild_id)
    bot._config_dirty = dirty


def xp_para_level(nivel: int) -> int:
    return nivel * 100


def calcular_tier(total: int) -> int:
    for t in range(5, 0, -1):
        if total >= TIERS[t]['requisito']:
            return t
    return 1


# Alias para compatibilidade com código existente
def pode_usar_cmd(guild_id: str, user_id: str, cmd: str, cooldown: int) -> Tuple[bool, Optional[int]]:
    return pode_usar_cmd_db(guild_id, user_id, cmd, cooldown)


def registrar_cooldown(guild_id: str, user_id: str, cmd: str):
    registrar_cooldown_db(guild_id, user_id, cmd)


def formatar_uptime(start: datetime) -> str:
    delta = datetime.now() - start
    h, r = divmod(int(delta.total_seconds()), 3600)
    m, s = divmod(r, 60)
    d, h = divmod(h, 24)
    return f'{d}d {h}h {m}m {s}s'


async def log_canal(guild: discord.Guild, tipo: str, dados: Dict[str, Any]):
    data = load_json('logs_data.json')
    gid = str(guild.id)
    if gid not in data:
        data[gid] = []
    data[gid].append({'tipo': tipo, 'timestamp': datetime.now().isoformat(), 'dados': dados})
    if len(data[gid]) > 1000:
        data[gid] = data[gid][-1000:]
    save_json('logs_data.json', data)
    cfg = load_json('config_data.json').get(gid, {})
    ch_id = cfg.get('log_channel_id')
    if ch_id:
        try:
            ch = guild.get_channel(int(ch_id))
            if ch:
                cores = {'join': 0x2ECC71, 'leave': 0xE74C3C, 'ban': 0x922B21, 'unban': 0x2ECC71,
                         'kick': 0xE67E22, 'mute': 0xD35400, 'unmute': 0x95A5A6, 'role_change': 0x3498DB}
                emojis = {'join': '📥', 'leave': '📤', 'ban': '🔨', 'unban': '🔓',
                          'kick': '👢', 'mute': '🔇', 'unmute': '🔊', 'role_change': '🎭'}
                e = discord.Embed(
                    title=f"{emojis.get(tipo, '📋')} {tipo.replace('_', ' ').title()}",
                    color=cores.get(tipo, 0x3498DB), timestamp=datetime.now()
                )
                for k, v in dados.items():
                    e.add_field(name=k.replace('_', ' ').title(), value=str(v), inline=True)
                await ch.send(embed=e)
        except Exception as ex:
            logger.error(f'Erro log canal: {ex}')


async def notificar_mod(usuario: discord.Member, tipo: str, motivo: str, mod: discord.Member, duracao: Optional[str] = None):
    titulos = {
        'warn': '⚠️ Você Recebeu um Aviso',
        'kick': '👢 Você Foi Expulso',
        'ban': '🔨 Você Foi Banido',
        'tempban': '⏰ Você Foi Banido Temporariamente',
        'mute': '🔇 Você Foi Silenciado',
        'unmute': '🔊 Silenciamento Removido',
        'unban': '🔓 Você Foi Desbanido'
    }
    cores = {
        'warn': 0xF39C12, 'kick': 0xE74C3C, 'ban': 0x922B21,
        'tempban': 0xE74C3C, 'mute': 0xD35400, 'unmute': 0x2ECC71, 'unban': 0x2ECC71
    }
    try:
        e = discord.Embed(
            title=titulos.get(tipo, '📋 Ação de Moderação'),
            description=f'Uma ação foi tomada contra você no servidor **{usuario.guild.name}**',
            color=cores.get(tipo, 0x3498DB), timestamp=datetime.now()
        )
        e.add_field(name='🛡️ Moderador', value=mod.name, inline=True)
        e.add_field(name='📋 Motivo', value=motivo, inline=False)
        if duracao:
            e.add_field(name='⏰ Duração', value=duracao, inline=True)
        if usuario.guild.icon:
            e.set_thumbnail(url=usuario.guild.icon.url)
        e.set_footer(text=f'Servidor: {usuario.guild.name}')
        await usuario.send(embed=e)
    except discord.Forbidden:
        pass


async def log_moderacao(guild: discord.Guild, tipo: str, usuario: discord.Member, mod: discord.Member, motivo: str, case_id: int, duracao: Optional[str] = None):
    cfg = load_json('config_data.json').get(str(guild.id), {})
    ch_id = cfg.get('log_channel_id')
    if not ch_id:
        return
    ch = guild.get_channel(int(ch_id))
    if not ch:
        return
    cores = {'warn': 0xF39C12, 'kick': 0xE74C3C, 'ban': 0x922B21,
             'tempban': 0xE74C3C, 'mute': 0xD35400, 'unmute': 0x2ECC71, 'unban': 0x2ECC71}
    emojis_t = {'warn': '⚠️', 'kick': '👢', 'ban': '🔨', 'tempban': '⏰',
                'mute': '🔇', 'unmute': '🔊', 'unban': '🔓'}
    titulos_t = {'warn': 'Aviso Aplicado', 'kick': 'Membro Expulso', 'ban': 'Membro Banido',
                 'tempban': 'Ban Temporário', 'mute': 'Membro Silenciado',
                 'unmute': 'Silenciamento Removido', 'unban': 'Membro Desbanido'}
    e = discord.Embed(
        title=f"{emojis_t.get(tipo, '📋')} {titulos_t.get(tipo, 'Ação')}",
        color=cores.get(tipo, 0x3498DB), timestamp=datetime.now()
    )
    e.add_field(name='👤 Usuário', value=f'{usuario.mention}\n`{usuario.id}`', inline=True)
    e.add_field(name='🛡️ Moderador', value=f'{mod.mention}\n`{mod.id}`', inline=True)
    e.add_field(name='📋 Case', value=f'`#{case_id}`', inline=True)
    e.add_field(name='📝 Motivo', value=motivo, inline=False)
    if duracao:
        e.add_field(name='⏰ Duração', value=duracao, inline=True)
    e.set_thumbnail(url=usuario.display_avatar.url)
    e.set_footer(text=f'Moderador: {mod.name}')
    try:
        await ch.send(embed=e)
    except Exception as ex:
        logger.error(f'Erro log mod: {ex}')


@bot.event
async def on_ready():
    logger.info(f'Bot conectado: {bot.user} (ID: {bot.user.id})')
    logger.info(f'Servidores: {len(bot.guilds)}')
    bot._xp_cache = {}
    bot._invites_cache = {}
    bot._config_cache = {}
    bot._config_dirty = set()
    bot._spam_tracker = defaultdict(deque)
    bot._spam_warn = defaultdict(int)
    bot._join_tracker = defaultdict(deque)
    bot._raid_active = defaultdict(bool)
    bot.verify_step1 = {}
    bot.verify_step2 = {}
    try:
        synced = await bot.tree.sync()
        logger.info(f'{len(synced)} comandos sincronizados')
    except Exception as e:
        logger.error(f'Erro ao sincronizar: {e}')
    for t in [task_codigos_expirados, task_bans_temporarios, task_mutes_temporarios,
              task_giveaways, task_lembretes, task_backup, task_flush_xp, task_flush_config]:
        if not t.is_running():
            t.start()
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name='🔒 /verify | /ajuda'),
        status=discord.Status.online
    )
    # Cache de convites
    for guild in bot.guilds:
        try:
            invites = await guild.invites()
            bot._invites_cache[str(guild.id)] = {inv.code: inv.uses or 0 for inv in invites}
        except Exception:
            pass
    logger.info('Bot pronto!')


@bot.event
async def on_error(event, *args, **kwargs):
    logger.error(f'Erro no evento {event}', exc_info=True)


@bot.event
async def on_member_join(member: discord.Member):
    gid = str(member.guild.id)
    uid = str(member.id)
    age = (datetime.now() - member.created_at.replace(tzinfo=None)).days
    cfg = get_config(gid)
    antiraid = cfg.get('antiraid', {})

    # ── Anti-Raid ─────────────────────────────────────────────────────────────
    if antiraid.get('ativo'):
        # Bloqueio por idade de conta
        min_dias = antiraid.get('min_conta_dias', 0)
        if min_dias and age < min_dias:
            try:
                await member.send(
                    f'⛔ Sua conta Discord precisa ter no mínimo **{min_dias} dias** '
                    f'para entrar neste servidor. Sua conta tem **{age}** dias.'
                )
            except Exception:
                pass
            try:
                await member.kick(reason=f'Anti-Raid: conta nova ({age}d < {min_dias}d)')
            except Exception:
                pass
            return

        # Rastrear velocidade de joins
        agora = time.time()
        fila = bot._join_tracker[gid]
        fila.append(agora)
        janela = antiraid.get('janela_segundos', 10)
        while fila and agora - fila[0] > janela:
            fila.popleft()
        limite = antiraid.get('max_joins', 5)

        if len(fila) >= limite:
            acao_raid = antiraid.get('acao', 'kick')
            if not bot._raid_active[gid]:
                bot._raid_active[gid] = True
                log_ch_id = cfg.get('log_channel_id')
                if log_ch_id:
                    lch = member.guild.get_channel(int(log_ch_id))
                    if lch:
                        try:
                            alerta = discord.Embed(
                                title='🚨 RAID DETECTADO!',
                                description=(
                                    f'**{len(fila)}** membros entraram em **{janela}s**!\n'
                                    f'Ação automática: **{acao_raid.upper()}**'
                                ),
                                color=0xFF0000, timestamp=datetime.now()
                            )
                            await lch.send('@here', embed=alerta)
                        except Exception:
                            pass
                if acao_raid == 'lockdown':
                    asyncio.create_task(_raid_lockdown(member.guild, cfg))

            try:
                aviso = '⛔ Você foi removido automaticamente por proteção anti-raid. Tente entrar mais tarde.'
                await member.send(aviso)
            except Exception:
                pass
            try:
                if acao_raid == 'ban':
                    await member.ban(reason='Anti-Raid automático', delete_message_days=0)
                else:
                    await member.kick(reason='Anti-Raid automático')
            except Exception:
                pass
            return

    await log_canal(member.guild, 'join', {
        'usuario': f'{member.name} ({member.id})',
        'conta_criada': member.created_at.strftime('%d/%m/%Y'),
        'dias_conta': age
    })

    # Rastrear quem convidou o membro
    invited_by = None
    try:
        invites_antes = bot._invites_cache.get(gid, {})
        invites_agora = {inv.code: inv for inv in await member.guild.invites()}
        for code, inv in invites_agora.items():
            if (inv.uses or 0) > invites_antes.get(code, 0) and inv.inviter:
                invited_by = str(inv.inviter.id)
                break
        bot._invites_cache[gid] = {inv.code: inv.uses or 0 for inv in invites_agora.values()}
    except Exception:
        pass

    users = load_json('users_data.json')
    users.setdefault(gid, {})[uid] = {
        'username': member.name, 'verified': False, 'warnings': 0,
        'joined_at': member.joined_at.isoformat() if member.joined_at else datetime.now().isoformat(),
        'account_created': member.created_at.isoformat(),
        'is_new_account': age < 7, 'invited_by': invited_by
    }
    save_json('users_data.json', users)

    # Auto-role
    autorole_id = cfg.get('autorole_id')
    if autorole_id:
        autorole = member.guild.get_role(int(autorole_id))
        if autorole:
            try:
                await member.add_roles(autorole, reason='Auto-role')
            except Exception:
                pass

    # Mensagem de boas-vindas no canal de verificação
    ch_id = cfg.get('verification_channel_id')
    if not ch_id:
        return
    e = discord.Embed(
        title='🔒 Verificação Necessária',
        description=f'Olá {member.mention}! Para acessar o servidor, verifique sua conta Roblox.',
        color=0x5865F2, timestamp=datetime.now()
    )
    instrucoes = (
        '**Etapa 1:** Use `/verify` para gerar seu código\n'
        '**Etapa 2:** Use `/verify_code <código> <username_roblox>` para confirmar\n'
        '**Etapa 3:** Use `/verify_confirm` para concluir\n\n'
        '✅ Após verificado você terá acesso completo!'
    )
    e.add_field(name='📝 Como verificar (3 etapas):', value=instrucoes, inline=False)
    if age < 7:
        e.add_field(name='⚠️ Conta Nova', value=f'Conta criada há apenas **{age}** dia(s). Verificação reforçada ativa.', inline=False)
    if member.guild.icon:
        e.set_thumbnail(url=member.guild.icon.url)
    ch = member.guild.get_channel(int(ch_id))
    if ch:
        try:
            await ch.send(f'{member.mention}', embed=e, delete_after=300)
        except Exception:
            pass


async def _raid_lockdown(guild: discord.Guild, cfg: Dict):
    """Ativa lockdown temporário de N minutos durante raid."""
    duracao_min = cfg.get('antiraid', {}).get('lockdown_minutos', 5)
    log_ch_id = cfg.get('log_channel_id')
    for ch in guild.text_channels:
        try:
            ow = ch.overwrites_for(guild.default_role)
            ow.send_messages = False
            await ch.set_permissions(guild.default_role, overwrite=ow)
            await asyncio.sleep(0.3)
        except Exception:
            pass
    if log_ch_id:
        lch = guild.get_channel(int(log_ch_id))
        if lch:
            try:
                await lch.send(f'🔒 **Lockdown anti-raid ativado por {duracao_min} minutos.**')
            except Exception:
                pass
    await asyncio.sleep(duracao_min * 60)
    gid = str(guild.id)
    bot._raid_active[gid] = False
    for ch in guild.text_channels:
        try:
            ow = ch.overwrites_for(guild.default_role)
            ow.send_messages = None
            await ch.set_permissions(guild.default_role, overwrite=ow)
            await asyncio.sleep(0.3)
        except Exception:
            pass
    if log_ch_id:
        lch = guild.get_channel(int(log_ch_id))
        if lch:
            try:
                await lch.send('🔓 Lockdown anti-raid encerrado. Servidor voltou ao normal.')
            except Exception:
                pass


@bot.event
async def on_member_remove(member: discord.Member):
    await log_canal(member.guild, 'leave', {
        'usuario': f'{member.name} ({member.id})',
        'tempo': str(datetime.now() - member.joined_at.replace(tzinfo=None)) if member.joined_at else '?'
    })


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if before.roles != after.roles:
        added = [r.name for r in after.roles if r not in before.roles]
        removed = [r.name for r in before.roles if r not in after.roles]
        if added or removed:
            await log_canal(after.guild, 'role_change', {
                'usuario': f'{after.name} ({after.id})',
                'adicionados': ', '.join(added) or 'Nenhum',
                'removidos': ', '.join(removed) or 'Nenhum'
            })


# ── Padrões de link para antilink ────────────────────────────────────────────
_LINK_PATTERN = re.compile(
    r'(https?://|www\.|discord\.gg/|discord\.com/invite/|t\.me/)',
    re.IGNORECASE
)


async def _processar_antispam(message: discord.Message, cfg: Dict) -> bool:
    """Retorna True se mensagem foi bloqueada por spam."""
    antispam = cfg.get('antispam', {})
    if not antispam.get('ativo'):
        return False

    gid = str(message.guild.id)
    uid = str(message.author.id)
    key = f'{gid}:{uid}'

    # Ignorar admins e moderadores
    if message.author.guild_permissions.manage_messages:
        return False

    # Cargo imune
    imune_id = antispam.get('cargo_imune_id')
    if imune_id:
        if any(str(r.id) == imune_id for r in message.author.roles):
            return False

    max_msg = antispam.get('max_mensagens', 5)
    janela = antispam.get('janela_segundos', 5)
    acao = antispam.get('acao', 'delete')

    agora = time.time()
    fila = bot._spam_tracker[key]
    fila.append(agora)

    # Remover timestamps fora da janela
    while fila and agora - fila[0] > janela:
        fila.popleft()

    if len(fila) < max_msg:
        return False

    # SPAM DETECTADO
    fila.clear()
    bot._spam_tracker[key] = fila

    # Deletar mensagens recentes do usuário
    try:
        async for msg in message.channel.history(limit=50):
            if msg.author == message.author:
                try:
                    await msg.delete()
                except Exception:
                    pass
    except Exception:
        pass

    if acao == 'mute':
        try:
            await message.author.timeout(timedelta(minutes=5), reason='Anti-Spam: flood detectado')
        except Exception:
            pass
        try:
            await message.channel.send(
                f'🔇 {message.author.mention} foi silenciado por **5 minutos** por spam.',
                delete_after=8
            )
        except Exception:
            pass
    elif acao == 'kick':
        try:
            await message.author.kick(reason='Anti-Spam: flood excessivo')
        except Exception:
            pass
    else:  # delete / alert
        try:
            await message.channel.send(
                f'⚠️ {message.author.mention} pare de fazer spam!',
                delete_after=6
            )
        except Exception:
            pass

    log_ch_id = cfg.get('log_channel_id')
    if log_ch_id:
        lch = message.guild.get_channel(int(log_ch_id))
        if lch:
            try:
                e = discord.Embed(title='🚫 Anti-Spam Ativado', color=0xE74C3C, timestamp=datetime.now())
                e.add_field(name='👤 Usuário', value=f'{message.author.mention} (`{message.author.id}`)', inline=True)
                e.add_field(name='📍 Canal', value=message.channel.mention, inline=True)
                e.add_field(name='⚡ Ação', value=acao.upper(), inline=True)
                await lch.send(embed=e)
            except Exception:
                pass
    return True


async def _processar_antilink(message: discord.Message, cfg: Dict) -> bool:
    """Retorna True se mensagem foi bloqueada por link."""
    antilink = cfg.get('antilink', {})
    if not antilink.get('ativo'):
        return False
    if not _LINK_PATTERN.search(message.content):
        return False

    # Ignorar admins e moderadores
    if message.author.guild_permissions.manage_messages:
        return False

    # Canal permitido
    canal_perm_id = antilink.get('canal_permitido_id')
    if canal_perm_id and str(message.channel.id) == canal_perm_id:
        return False

    # Permitir links do Discord se configurado
    if antilink.get('permitir_discord'):
        content = message.content
        # Checar se é só link Discord (sem outros links)
        cleaned = re.sub(r'https?://discord\.(?:gg|com)/\S+', '', content, flags=re.IGNORECASE)
        if not _LINK_PATTERN.search(cleaned):
            return False

    # Cargo imune
    imune_id = antilink.get('cargo_imune_id')
    if imune_id:
        if any(str(r.id) == imune_id for r in message.author.roles):
            return False

    acao = antilink.get('acao', 'delete_warn')

    try:
        await message.delete()
    except Exception:
        pass

    if acao in ('delete_warn', 'delete_mute'):
        try:
            await message.channel.send(
                f'🔗 {message.author.mention} links não são permitidos aqui!',
                delete_after=6
            )
        except Exception:
            pass

    if acao == 'delete_mute':
        try:
            await message.author.timeout(timedelta(minutes=10), reason='Anti-Link: link postado')
        except Exception:
            pass

    log_ch_id = cfg.get('log_channel_id')
    if log_ch_id:
        lch = message.guild.get_channel(int(log_ch_id))
        if lch:
            try:
                e = discord.Embed(title='🔗 Anti-Link Ativado', color=0xF39C12, timestamp=datetime.now())
                e.add_field(name='👤 Usuário', value=f'{message.author.mention} (`{message.author.id}`)', inline=True)
                e.add_field(name='📍 Canal', value=message.channel.mention, inline=True)
                e.add_field(name='💬 Conteúdo', value=message.content[:100], inline=False)
                await lch.send(embed=e)
            except Exception:
                pass
    return True


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    bot.mensagens_processadas += 1
    gid = str(message.guild.id)
    uid = str(message.author.id)

    # Carregar config do cache
    cfg = get_config(gid)

    # ── Anti-Spam ─────────────────────────────────────────────────────────────
    try:
        blocked = await _processar_antispam(message, cfg)
        if blocked:
            return  # mensagem já tratada, não processar mais
    except Exception as ex:
        logger.error(f'Erro antispam: {ex}')

    # ── Anti-Link ─────────────────────────────────────────────────────────────
    try:
        blocked = await _processar_antilink(message, cfg)
        if blocked:
            return
    except Exception as ex:
        logger.error(f'Erro antilink: {ex}')

    # ── XP (cache em memória, SQLite a cada 20 msgs) ─────────────────────────
    try:
        key = f'{gid}:{uid}'
        cache = bot._xp_cache
        if key not in cache:
            cache[key] = get_user_level(gid, uid)
        lv = cache[key]
        lv['xp'] = lv.get('xp', 0) + random.randint(XP_MIN, XP_MAX)
        lv['messages'] = lv.get('messages', 0) + 1
        xp_needed = xp_para_level(lv.get('level', 1))
        if lv['xp'] >= xp_needed:
            lv['level'] = lv.get('level', 1) + 1
            lv['xp'] -= xp_needed
            e = discord.Embed(
                title='🎉 Level Up!',
                description=f'{message.author.mention} subiu para o nível **{lv["level"]}**!',
                color=0xF1C40F
            )
            e.set_thumbnail(url=message.author.display_avatar.url)
            try:
                await message.channel.send(embed=e, delete_after=10)
            except Exception:
                pass
        # Flush a cada 20 mensagens → SQLite
        if lv['messages'] % 20 == 0:
            save_user_level(gid, uid, lv)
    except Exception as ex:
        logger.error(f'Erro XP: {ex}')

    await bot.process_commands(message)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    msg = None
    if isinstance(error, app_commands.MissingPermissions):
        perms = ', '.join(error.missing_permissions)
        msg = embed_err('Sem Permissão', f'Você precisa da permissão: **{perms}**', interaction.user)
    elif isinstance(error, app_commands.BotMissingPermissions):
        perms = ', '.join(error.missing_permissions)
        msg = embed_err('Bot Sem Permissão', f'Preciso da permissão: **{perms}**\nVerifique as permissões do bot no servidor.', interaction.user)
    elif isinstance(error, app_commands.CommandOnCooldown):
        msg = embed_warn('Cooldown', f'Aguarde **{error.retry_after:.1f}s** antes de usar este comando.', interaction.user)
    elif isinstance(error, app_commands.CommandInvokeError):
        original = error.original
        if isinstance(original, discord.Forbidden):
            msg = embed_err('Sem Permissão', 'O bot não tem permissão para executar esta ação. Verifique:\n• Hierarquia de cargos\n• Permissões do bot no canal/servidor', interaction.user)
        elif isinstance(original, discord.NotFound):
            msg = embed_err('Não Encontrado', 'O recurso solicitado não foi encontrado.', interaction.user)
        else:
            logger.error(f'Erro de comando: {error}')
            msg = embed_err('Erro Interno', f'Ocorreu um erro inesperado. Tente novamente.', interaction.user)
    else:
        logger.error(f'Erro de comando não tratado: {error}')
        msg = embed_err('Erro', 'Ocorreu um erro ao executar este comando.', interaction.user)

    if msg:
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=msg, ephemeral=True)
            else:
                await interaction.followup.send(embed=msg, ephemeral=True)
        except Exception:
            pass


# ─── SISTEMA DE VERIFICAÇÃO ──────────────────────────────────────────────────

def _gerar_fingerprint(user: discord.Member) -> str:
    """Fingerprint baseado no Discord ID (que codifica timestamp de criação).
    IDs criados no mesmo período têm bits altos similares — proxy de mesma sessão/IP."""
    # Snowflake: bits 22+ = milissegundos desde 2015-01-01
    ts_ms = (user.id >> 22) + 1420070400000
    bucket = ts_ms // (3600_000 * 6)  # agrupa em janelas de 6 horas
    return str(bucket)


def _checar_alt(guild_id: str, user: discord.Member, roblox_username: str) -> Optional[str]:
    """Retorna ID do usuário original se detectar alt, None caso contrário.
    Critérios: mesmo username Roblox OU fingerprint de criação muito próximo (< 6h)
    em conta nova (< 30 dias).
    """
    data = load_json('users_data.json')
    uid = str(user.id)
    roblox_lower = roblox_username.strip().lower()
    fp = _gerar_fingerprint(user)
    account_age = (datetime.now() - user.created_at.replace(tzinfo=None)).days

    for oid, info in data.get(guild_id, {}).items():
        if oid == uid or not info.get('verified'):
            continue
        # 1) Mesmo username Roblox → alt confirmada
        if info.get('roblox_username', '').lower() == roblox_lower:
            return oid
        # 2) Fingerprint igual + conta nova → suspeita de alt
        if info.get('account_fp') == fp and account_age < 30:
            return oid
    return None


@bot.tree.command(name='verify', description='🔒 Inicia a verificação — receba seu código')
async def cmd_verify(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    gid = str(interaction.guild.id)
    cfg = load_json('config_data.json').get(gid, {})

    # Checar se já verificado pelo cargo ou pelo JSON
    rid = cfg.get('verified_role_id')
    if rid:
        r = interaction.guild.get_role(int(rid))
        if r and r in interaction.user.roles:
            await interaction.response.send_message(
                embed=embed_warn('Já Verificado', 'Você já está verificado e tem acesso ao servidor!', interaction.user),
                ephemeral=True)
            return
    if is_verified(gid, uid):
        await interaction.response.send_message(
            embed=embed_warn('Já Verificado', 'Você já está verificado!', interaction.user), ephemeral=True)
        return

    # Código já gerado e ainda válido?
    if uid in bot.verification_codes:
        info = bot.verification_codes[uid]
        expiry = info['timestamp'] + timedelta(minutes=15)
        if datetime.now() < expiry:
            mins = max(1, int((expiry - datetime.now()).total_seconds() / 60))
            e = discord.Embed(title='🔑 Código Já Gerado', color=0xF39C12, timestamp=datetime.now())
            e.add_field(name='Código', value=f'```{info["code"]}```', inline=False)
            e.add_field(name='⏰ Expira em', value=f'{mins} min', inline=True)
            e.add_field(name='🔄 Tentativas', value=f'{3 - info["attempts"]}/3', inline=True)
            e.add_field(name='📝 Como usar', value='`/verify_code <código> <username_roblox>`', inline=False)
            await interaction.response.send_message(embed=e, ephemeral=True)
            return

    codigo = gerar_codigo()
    bot.verification_codes[uid] = {'code': codigo, 'timestamp': datetime.now(), 'attempts': 0}

    e = discord.Embed(
        title='🔒 Verificação — Passo 1 de 2',
        description=f'Olá {interaction.user.mention}! Seu código de verificação foi gerado.',
        color=0x5865F2, timestamp=datetime.now()
    )
    e.add_field(name='🔑 Código', value=f'```{codigo}```', inline=False)
    e.add_field(name='⏰ Válido por', value='15 minutos', inline=True)
    e.add_field(name='🔄 Tentativas', value='3', inline=True)
    e.add_field(
        name='📝 Próximo passo',
        value='Use o comando abaixo com seu **username exato do Roblox**:\n`/verify_code <código> <username_roblox>`',
        inline=False
    )
    e.set_footer(text='Este código é pessoal — não compartilhe!')
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(name='verify_code', description='✅ Confirma o código e conclui a verificação')
@app_commands.describe(codigo='Código de 6 dígitos recebido em /verify', roblox_username='Seu username exato no Roblox')
async def cmd_verify_code(interaction: discord.Interaction, codigo: str, roblox_username: str):
    uid = str(interaction.user.id)
    gid = str(interaction.guild.id)
    cfg = load_json('config_data.json').get(gid, {})

    if is_verified(gid, uid):
        await interaction.response.send_message(
            embed=embed_warn('Já Verificado', 'Você já está verificado!', interaction.user), ephemeral=True)
        return

    if uid not in bot.verification_codes:
        await interaction.response.send_message(
            embed=embed_err('Sem Código', 'Use `/verify` primeiro para gerar seu código.', interaction.user), ephemeral=True)
        return

    info = bot.verification_codes[uid]

    # Expirado?
    if datetime.now() > info['timestamp'] + timedelta(minutes=15):
        bot.verification_codes.pop(uid, None)
        await interaction.response.send_message(
            embed=embed_err('Código Expirado', 'Código expirou (15 min). Use `/verify` para gerar um novo.', interaction.user), ephemeral=True)
        return

    # Tentativas esgotadas?
    if info['attempts'] >= 3:
        bot.verification_codes.pop(uid, None)
        await interaction.response.send_message(
            embed=embed_err('Bloqueado', '3 tentativas erradas. Use `/verify` para um novo código.', interaction.user), ephemeral=True)
        return

    # Código errado?
    if codigo.strip() != info['code']:
        info['attempts'] += 1
        restantes = 3 - info['attempts']
        if restantes == 0:
            bot.verification_codes.pop(uid, None)
            await interaction.response.send_message(
                embed=embed_err('Código Errado', 'Última tentativa usada. Use `/verify` para novo código.', interaction.user), ephemeral=True)
        else:
            await interaction.response.send_message(
                embed=embed_err('Código Incorreto', f'Código errado! Tentativas restantes: **{restantes}/3**', interaction.user), ephemeral=True)
        return

    # ── Verificar alt ──────────────────────────────────────────────────────────
    alt_id = _checar_alt(gid, interaction.user, roblox_username)
    if alt_id and alt_id != uid:
        alts_liberadas = cfg.get('alts_liberadas', [])
        if uid not in alts_liberadas:
            account_age = (datetime.now() - interaction.user.created_at.replace(tzinfo=None)).days
            log_ch_id = cfg.get('log_channel_id')
            if log_ch_id:
                lch = interaction.guild.get_channel(int(log_ch_id))
                if lch:
                    try:
                        alerta = discord.Embed(title='🚨 ALT Detectada — Verificação Bloqueada', color=0xE74C3C, timestamp=datetime.now())
                        alerta.add_field(name='👤 Usuário', value=f'{interaction.user.mention}\n`{interaction.user.id}`', inline=True)
                        alerta.add_field(name='📅 Conta criada', value=f'Há {account_age} dias', inline=True)
                        alerta.add_field(name='🎮 Roblox tentado', value=f'`{roblox_username}`', inline=True)
                        alerta.add_field(name='🔗 Possível alt de', value=f'<@{alt_id}>', inline=True)
                        alerta.add_field(name='✅ Para liberar', value=f'Use `/liberar_alt {interaction.user.id}`', inline=False)
                        await lch.send(embed=alerta)
                    except Exception:
                        pass
            await interaction.response.send_message(
                embed=embed_err('🚨 Verificação Bloqueada',
                    'Sua conta foi identificada como possível **alt**.\nContate a administração.', interaction.user),
                ephemeral=True)
            return

    # ── Etapa 2 OK — salvar estado para verify_confirm (etapa 3) ─────────────
    bot.verification_codes.pop(uid, None)
    bot.verify_step2[uid] = {'roblox': roblox_username.strip(), 'ts': datetime.now()}

    e = discord.Embed(
        title='✅ Etapa 2/3 Concluída!',
        description=f'Username Roblox **`{roblox_username.strip()}`** aceito!\n\nAgora complete a **etapa final**:',
        color=0xF39C12, timestamp=datetime.now()
    )
    e.add_field(name='🛡️ Etapa 3 — Confirmar identidade', value='Use o comando:\n`/verify_confirm`\n\nVocê tem **10 minutos** para concluir.', inline=False)
    e.set_footer(text='Última etapa — não feche o Discord!')
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(name='verify_channel', description='⚙️ Define o canal exclusivo de verificação (bloqueia resto para não verificados)')
@app_commands.describe(
    canal='Canal que NÃO verificados poderão ver (apenas esse)',
    verified_role='Cargo dado após verificação',
    member_role='Cargo Membro dado junto (opcional)'
)
@app_commands.checks.has_permissions(administrator=True)
async def cmd_verify_channel(interaction: discord.Interaction, canal: discord.TextChannel, verified_role: discord.Role, member_role: Optional[discord.Role] = None):
    await interaction.response.defer(ephemeral=True)
    gid = str(interaction.guild.id)
    cfg = load_json('config_data.json')
    cfg.setdefault(gid, {})
    cfg[gid]['verification_channel_id'] = str(canal.id)
    cfg[gid]['verified_role_id'] = str(verified_role.id)
    if member_role:
        cfg[gid]['member_role_id'] = str(member_role.id)
    save_json('config_data.json', cfg)

    erros = 0
    processados = 0

    # Iterar sobre todos os canais do servidor
    for ch in interaction.guild.channels:
        if not isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel)):
            continue
        try:
            if ch.id == canal.id:
                # Canal de verificação: @everyone pode ver mas não enviar
                await ch.set_permissions(interaction.guild.default_role,
                    view_channel=True, send_messages=False, read_message_history=True)
                # Verificados não precisam ver esse canal necessariamente
                await ch.set_permissions(verified_role, view_channel=True, send_messages=False)
            else:
                # Outros canais: @everyone não vê, verificados veem
                await ch.set_permissions(interaction.guild.default_role, view_channel=False)
                await ch.set_permissions(verified_role, view_channel=True, send_messages=True)
                if member_role and member_role.id != verified_role.id:
                    await ch.set_permissions(member_role, view_channel=True, send_messages=True)
            processados += 1
        except discord.Forbidden:
            erros += 1
        except Exception as ex:
            logger.error(f'Erro ao configurar permissão de {ch.name}: {ex}')
            erros += 1

        await asyncio.sleep(0.3)  # Rate limit — essencial no Termux

    # Enviar mensagem de boas-vindas no canal
    try:
        bv = discord.Embed(
            title='🔒 Verificação Necessária',
            description=(
                'Para acessar o servidor, você precisa verificar sua conta.\n\n'
                '**Como verificar:**\n'
                '1️⃣ Digite `/verify` para receber seu código\n'
                '2️⃣ Digite `/verify_code <código> <username_roblox>` para confirmar\n\n'
                '✅ Após verificado, você terá acesso completo!'
            ),
            color=0x5865F2
        )
        if interaction.guild.icon:
            bv.set_thumbnail(url=interaction.guild.icon.url)
        bv.set_footer(text='🔍 Sistema anti-alt ativo')
        await canal.send(embed=bv)
    except Exception:
        pass

    resultado = f'Canal de verificação: {canal.mention}\nCargo Verificado: {verified_role.mention}'
    if member_role:
        resultado += f'\nCargo Membro: {member_role.mention}'
    resultado += f'\n\n✅ {processados} canal(is) configurado(s).'
    if erros:
        resultado += f'\n⚠️ {erros} canal(is) com erro (verifique hierarquia do bot).'

    await interaction.followup.send(embed=embed_ok('Sistema de Verificação Configurado!', resultado, interaction.user), ephemeral=True)


@bot.tree.command(name='liberar_alt', description='🔓 Libera um usuário bloqueado por detecção de alt (Admin)')
@app_commands.describe(usuario_id='ID do usuário a liberar')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_liberar_alt(interaction: discord.Interaction, usuario_id: str):
    gid = str(interaction.guild.id)
    cfg = load_json('config_data.json')
    cfg.setdefault(gid, {})
    alts = cfg[gid].get('alts_liberadas', [])
    if usuario_id not in alts:
        alts.append(usuario_id)
    cfg[gid]['alts_liberadas'] = alts
    save_json('config_data.json', cfg)
    save_config(gid, cfg[gid])
    await interaction.response.send_message(
        embed=embed_ok('Alt Liberada', f'Usuário `{usuario_id}` pode verificar mesmo com detecção de alt.\nEle deve usar `/verify` novamente.', interaction.user),
        ephemeral=True
    )


@bot.tree.command(name='verify_confirm', description='🛡️ Etapa 3 de verificação — confirma sua identidade')
async def cmd_verify_confirm(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    gid = str(interaction.guild.id)
    cfg = get_config(gid)

    # Etapa 2 (roblox) precisa ter sido feita
    step2 = bot.verify_step2.get(uid)
    if not step2:
        await interaction.response.send_message(
            embed=embed_err('Etapa Incompleta', 'Complete as etapas anteriores:\n`/verify` → `/verify_code` → `/verify_confirm`', interaction.user),
            ephemeral=True
        )
        return

    # Expirado?
    if datetime.now() > step2['ts'] + timedelta(minutes=10):
        bot.verify_step2.pop(uid, None)
        await interaction.response.send_message(
            embed=embed_err('Expirado', 'Confirmação expirou. Reinicie com `/verify`.', interaction.user),
            ephemeral=True
        )
        return

    roblox_username = step2['roblox']
    fp = _gerar_fingerprint(interaction.user)

    # Registrar verificação
    users = load_json('users_data.json')
    users.setdefault(gid, {}).setdefault(uid, {})
    users[gid][uid].update({
        'verified': True,
        'verified_at': datetime.now().isoformat(),
        'roblox_username': roblox_username,
        'account_fp': fp,
        'username': interaction.user.name
    })
    save_json('users_data.json', users)
    bot.verify_step2.pop(uid, None)

    # Dar cargos
    cargos_dados = []
    for key in ['verified_role_id', 'member_role_id']:
        rid = cfg.get(key)
        if not rid:
            continue
        r = interaction.guild.get_role(int(rid))
        if not r:
            continue
        try:
            await interaction.user.add_roles(r, reason='Verificação concluída')
            cargos_dados.append(r.name)
        except discord.Forbidden:
            logger.warning(f'Sem permissão para dar cargo {r.name}')
        except Exception as ex:
            logger.error(f'Erro ao dar cargo: {ex}')

    e = discord.Embed(
        title='✅ Verificação Concluída! (3/3)',
        description=f'Bem-vindo(a) ao servidor, {interaction.user.mention}! 🎉\nSua identidade foi confirmada com sucesso.',
        color=0x2ECC71, timestamp=datetime.now()
    )
    e.add_field(name='🎮 Roblox', value=f'`{roblox_username}`', inline=True)
    e.add_field(name='📅 Verificado em', value=datetime.now().strftime('%d/%m/%Y %H:%M'), inline=True)
    if cargos_dados:
        e.add_field(name='🎭 Cargos', value=' • '.join(f'`{c}`' for c in cargos_dados), inline=False)
    e.set_thumbnail(url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e, ephemeral=True)
    await log_canal(interaction.guild, 'verificacao', {
        'usuario': f'{interaction.user.name} ({interaction.user.id})',
        'roblox': roblox_username,
        'cargos': ', '.join(cargos_dados) or 'Nenhum'
    })


@bot.tree.command(name='set_verified_role', description='⚙️ Define cargos de verificado e membro')
@app_commands.describe(verified_role='Cargo Verificado', member_role='Cargo Membro (opcional)')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_set_verified_role(interaction: discord.Interaction, verified_role: discord.Role, member_role: Optional[discord.Role] = None):
    gid = str(interaction.guild.id)
    cfg = load_json('config_data.json')
    cfg.setdefault(gid, {})
    cfg[gid]['verified_role_id'] = str(verified_role.id)
    if member_role:
        cfg[gid]['member_role_id'] = str(member_role.id)
    save_json('config_data.json', cfg)
    desc = f'Cargo Verificado: {verified_role.mention}'
    if member_role:
        desc += f'\nCargo Membro: {member_role.mention}'
    await interaction.response.send_message(embed=embed_ok('Cargos Configurados', desc, interaction.user))


@bot.tree.command(name='set_admin_role', description='⚙️ Define o cargo de admin de League')
@app_commands.describe(cargo='Cargo com permissão de criar Leagues')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_set_admin_role(interaction: discord.Interaction, cargo: discord.Role):
    gid = str(interaction.guild.id)
    cfg = load_json('config_data.json')
    if gid not in cfg:
        cfg[gid] = {}
    cfg[gid]['admin_role_id'] = str(cargo.id)
    save_json('config_data.json', cfg)
    await interaction.response.send_message(embed=embed_ok('Cargo Admin Configurado', f'{cargo.mention} pode criar Leagues!', interaction.user))


@bot.tree.command(name='set_log_channel', description='⚙️ Define o canal de logs')
@app_commands.describe(canal='Canal de logs')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_set_log_channel(interaction: discord.Interaction, canal: discord.TextChannel):
    gid = str(interaction.guild.id)
    cfg = load_json('config_data.json')
    if gid not in cfg:
        cfg[gid] = {}
    cfg[gid]['log_channel_id'] = str(canal.id)
    save_json('config_data.json', cfg)
    await interaction.response.send_message(embed=embed_ok('Canal de Logs Configurado', f'Logs serão enviados em {canal.mention}', interaction.user))
    teste = discord.Embed(title='✅ Sistema de Logs Ativado', description='Este canal receberá todos os logs do servidor.', color=0x2ECC71, timestamp=datetime.now())
    await canal.send(embed=teste)


@bot.tree.command(name='set_mod_role', description='⚙️ Define o cargo de moderador')
@app_commands.describe(cargo='Cargo de moderador')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_set_mod_role(interaction: discord.Interaction, cargo: discord.Role):
    gid = str(interaction.guild.id)
    cfg = load_json('config_data.json')
    if gid not in cfg:
        cfg[gid] = {}
    cfg[gid]['mod_role_id'] = str(cargo.id)
    save_json('config_data.json', cfg)
    await interaction.response.send_message(embed=embed_ok('Cargo Mod Configurado', f'{cargo.mention} é agora o cargo de moderador!', interaction.user))


@bot.tree.command(name='whitelist', description='✅ Adiciona usuário à whitelist')
@app_commands.describe(usuario='Usuário a adicionar', motivo='Motivo')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_whitelist(interaction: discord.Interaction, usuario: discord.Member, motivo: str):
    gid = str(interaction.guild.id)
    uid = str(usuario.id)
    cfg = load_json('config_data.json')
    if gid not in cfg:
        cfg[gid] = {}
    if 'whitelist' not in cfg[gid]:
        cfg[gid]['whitelist'] = {}
    cfg[gid]['whitelist'][uid] = {'motivo': motivo, 'por': str(interaction.user.id), 'timestamp': datetime.now().isoformat()}
    save_json('config_data.json', cfg)
    await interaction.response.send_message(embed=embed_ok('Whitelist', f'{usuario.mention} adicionado.\n**Motivo:** {motivo}', interaction.user))


@bot.tree.command(name='check_user', description='🔍 Informações de um usuário no servidor')
@app_commands.describe(usuario='Usuário a verificar')
async def cmd_check_user(interaction: discord.Interaction, usuario: discord.Member):
    gid = str(interaction.guild.id)
    uid = str(usuario.id)
    users = load_json('users_data.json')
    warnings = load_json('warnings_data.json')
    cfg = load_json('config_data.json')
    e = discord.Embed(title=f'🔍 {usuario.name}', color=0x3498DB, timestamp=datetime.now())
    e.set_thumbnail(url=usuario.display_avatar.url)
    age_a = (datetime.now() - usuario.created_at.replace(tzinfo=None)).days
    e.add_field(name='👤 Usuário', value=f'{usuario.mention}\n`{usuario.id}`', inline=True)
    e.add_field(name='📅 Conta', value=f'{usuario.created_at.strftime("%d/%m/%Y")}\n({age_a} dias)', inline=True)
    if usuario.joined_at:
        age_s = (datetime.now() - usuario.joined_at.replace(tzinfo=None)).days
        e.add_field(name='📥 No Servidor', value=f'{usuario.joined_at.strftime("%d/%m/%Y")}\n({age_s} dias)', inline=True)
    verificado = is_verified(gid, uid)
    roblox = users.get(gid, {}).get(uid, {}).get('roblox_username', 'Não vinculado')
    e.add_field(name='✅ Verificado', value='✅ Sim' if verificado else '❌ Não', inline=True)
    e.add_field(name='🎮 Roblox', value=f'`{roblox}`', inline=True)
    avisos = len(warnings.get(gid, {}).get(uid, []))
    e.add_field(name='⚠️ Avisos', value=f'`{avisos}`', inline=True)
    na_wl = uid in cfg.get(gid, {}).get('whitelist', {})
    e.add_field(name='⭐ Whitelist', value='✅ Sim' if na_wl else '❌ Não', inline=True)
    if len(usuario.roles) > 1:
        e.add_field(name='🎭 Cargo Top', value=usuario.top_role.mention, inline=True)
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


class EntrarLeagueModal(Modal, title='Entrar na League'):
    nick_ingame = TextInput(label='Nick In-Game', placeholder='Seu nick no jogo (ex: PlayerXYZ)', max_length=50)

    def __init__(self, league_id: str, guild_id: str):
        super().__init__()
        self.league_id = league_id
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        lid = self.league_id
        gid = self.guild_id
        nick = self.nick_ingame.value.strip()
        leagues = load_json('leagues_data.json')
        if gid not in leagues or lid not in leagues[gid]:
            await interaction.response.send_message(embed=embed_err('Não Encontrada', 'League não encontrada.', interaction.user), ephemeral=True)
            return
        league = leagues[gid][lid]
        if league['status'] != 'ativa':
            await interaction.response.send_message(embed=embed_err('Inativa', 'Esta league não está mais ativa.', interaction.user), ephemeral=True)
            return
        members_data = load_json('league_members.json')
        if uid in members_data.get(gid, {}).get(lid, {}):
            await interaction.response.send_message(embed=embed_warn('Já Participando', 'Você já está nesta league!', interaction.user), ephemeral=True)
            return
        if is_league_full(gid, lid):
            await interaction.response.send_message(embed=embed_err('League Cheia', 'Esta league está cheia.', interaction.user), ephemeral=True)
            return
        if gid not in members_data:
            members_data[gid] = {}
        if lid not in members_data[gid]:
            members_data[gid][lid] = {}
        members_data[gid][lid][uid] = {'nick_ingame': nick, 'joined_at': datetime.now().isoformat(), 'discord_name': interaction.user.name}
        save_json('league_members.json', members_data)
        thread_id = league.get('thread_id')
        if thread_id:
            try:
                thread = interaction.guild.get_thread(int(thread_id))
                if thread:
                    await thread.add_user(interaction.user)
                    count = len(members_data[gid][lid])
                    limit = LEAGUE_LIMITS.get(league['modo'], 4)
                    entry = discord.Embed(
                        title='➕ Novo Participante',
                        description=f'{interaction.user.mention} entrou na league! ({count}/{limit})',
                        color=0x2ECC71, timestamp=datetime.now()
                    )
                    entry.add_field(name=f'🎮 Nick ({league.get("jogo","?")})', value=f'`{nick}`', inline=True)
                    await thread.send(embed=entry)
                    if count >= limit:
                        full_e = discord.Embed(title='🟢 League Completa!', description='Todos os jogadores entraram. Boa sorte a todos!', color=0xF1C40F)
                        await thread.send(embed=full_e)
            except Exception as ex:
                logger.error(f'Erro thread league: {ex}')
        await interaction.response.send_message(
            embed=embed_ok('Entrou!', f'Você entrou na **League #{lid}**!\n**Nick:** `{nick}`', interaction.user),
            ephemeral=True
        )


class EntrarLeagueView(View):
    def __init__(self, league_id: str, guild_id: str):
        super().__init__(timeout=None)
        self.league_id = league_id
        self.guild_id = guild_id

    @discord.ui.button(label='➕ Entrar na League', style=discord.ButtonStyle.green, emoji='⚔️')
    async def entrar(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(EntrarLeagueModal(self.league_id, self.guild_id))


@bot.tree.command(name='league', description='⚔️ Cria uma nova league/partida competitiva')
@app_commands.describe(
    jogo='Jogo da league',
    modo='Modo (ex: 2v2, 3v3, 5v5)',
    link_privado='Link do lobby/servidor privado'
)
@app_commands.choices(jogo=[
    app_commands.Choice(name='Roblox', value='Roblox'),
    app_commands.Choice(name='Valorant', value='Valorant'),
    app_commands.Choice(name='Free Fire', value='Free Fire'),
    app_commands.Choice(name='Fortnite', value='Fortnite'),
    app_commands.Choice(name='League of Legends', value='League of Legends'),
    app_commands.Choice(name='CS2', value='CS2'),
    app_commands.Choice(name='Minecraft', value='Minecraft'),
    app_commands.Choice(name='Outro', value='Outro'),
])
@app_commands.choices(modo=[
    app_commands.Choice(name='1v1', value='1v1'),
    app_commands.Choice(name='2v2', value='2v2'),
    app_commands.Choice(name='3v3', value='3v3'),
    app_commands.Choice(name='4v4', value='4v4'),
    app_commands.Choice(name='5v5', value='5v5'),
])
async def cmd_league(interaction: discord.Interaction, jogo: str, modo: str, link_privado: str):
    if not is_admin_league(interaction.user):
        await interaction.response.send_message(embed=embed_err('Sem Permissão', 'Você não tem permissão para criar leagues!', interaction.user), ephemeral=True)
        return
    await interaction.response.defer()
    gid = str(interaction.guild.id)
    lid = gerar_league_id(gid)
    LEAGUE_LIMITS_EXT = {'1v1': 2, '2v2': 4, '3v3': 6, '4v4': 8, '5v5': 10}
    limite = LEAGUE_LIMITS_EXT.get(modo, 4)
    lc = load_json('league_config.json').get(gid, {})
    channel = interaction.guild.get_channel(int(lc['league_channel_id'])) if 'league_channel_id' in lc else interaction.channel
    JOGO_EMOJIS = {'Roblox': '🎮', 'Valorant': '🎯', 'Free Fire': '🔥', 'Fortnite': '⛏️', 'League of Legends': '⚔️', 'CS2': '💣', 'Minecraft': '⛏️', 'Outro': '🕹️'}
    emoji_jogo = JOGO_EMOJIS.get(jogo, '🕹️')
    try:
        thread = await channel.create_thread(
            name=f'{emoji_jogo} league-{lid} {jogo} {modo}',
            type=discord.ChannelType.public_thread,
            auto_archive_duration=1440,
            reason=f'League por {interaction.user.name}'
        )
        await thread.add_user(interaction.user)
        rules_e = discord.Embed(
            title=f'{emoji_jogo} League #{lid} — {jogo} {modo}',
            description=f'League criada por {interaction.user.mention}',
            color=0xF1C40F, timestamp=datetime.now()
        )
        rules_e.add_field(name='🎮 Jogo', value=jogo, inline=True)
        rules_e.add_field(name='⚔️ Modo', value=modo, inline=True)
        rules_e.add_field(name='👥 Vagas', value=f'0/{limite}', inline=True)
        rules_e.add_field(name='📜 Regras', value='\n'.join(LEAGUE_RULES), inline=False)
        rules_e.set_footer(text=f'League ID: {lid}')
        rm = await thread.send(embed=rules_e)
        await rm.pin()
    except Exception as ex:
        logger.error(f'Erro criar thread: {ex}')
        await interaction.followup.send(embed=embed_err('Erro', f'Não foi possível criar o tópico: {ex}', interaction.user), ephemeral=True)
        return
    leagues = load_json('leagues_data.json')
    if gid not in leagues:
        leagues[gid] = {}
    leagues[gid][lid] = {
        'id': lid, 'creator_id': str(interaction.user.id), 'creator_name': interaction.user.name,
        'jogo': jogo, 'modo': modo, 'link_privado': link_privado,
        'limite': limite, 'status': 'ativa', 'thread_id': str(thread.id),
        'created_at': datetime.now().isoformat(), 'vencedor': None
    }
    save_json('leagues_data.json', leagues)
    e = discord.Embed(
        title=f'{emoji_jogo} League #{lid} — {jogo} {modo}',
        description=f'Criada por {interaction.user.mention}\nClique em **Entrar na League** para participar!',
        color=0xF1C40F, timestamp=datetime.now()
    )
    e.add_field(name='🎮 Jogo', value=jogo, inline=True)
    e.add_field(name='⚔️ Modo', value=modo, inline=True)
    e.add_field(name='👥 Vagas', value=f'0/{limite}', inline=True)
    e.add_field(name='🔗 Link do Lobby', value=f'```{link_privado}```', inline=False)
    e.add_field(name='💬 Tópico', value=thread.mention, inline=False)
    e.set_footer(text=f'League ID: {lid} | {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.followup.send(embed=e, view=EntrarLeagueView(lid, gid))


@bot.tree.command(name='joinleague', description='➕ Adiciona um usuário à league (Admin)')
@app_commands.describe(usuario='Usuário a adicionar', league_id='ID da league', nick_ingame='Nick do jogador no jogo')
async def cmd_joinleague(interaction: discord.Interaction, usuario: discord.Member, league_id: str, nick_ingame: str):
    if not is_admin_league(interaction.user):
        await interaction.response.send_message(embed=embed_err('Sem Permissão', 'Sem permissão.', interaction.user), ephemeral=True)
        return
    gid = str(interaction.guild.id)
    leagues = load_json('leagues_data.json')
    if gid not in leagues or league_id not in leagues[gid]:
        await interaction.response.send_message(embed=embed_err('Não Encontrada', f'League #{league_id} não existe.', interaction.user), ephemeral=True)
        return
    league = leagues[gid][league_id]
    if league['status'] != 'ativa':
        await interaction.response.send_message(embed=embed_err('Inativa', 'League não está ativa.', interaction.user), ephemeral=True)
        return
    members_data = load_json('league_members.json')
    if str(usuario.id) in members_data.get(gid, {}).get(league_id, {}):
        await interaction.response.send_message(embed=embed_warn('Já Participando', f'{usuario.mention} já está na league.', interaction.user), ephemeral=True)
        return
    limite = league.get('limite', LEAGUE_LIMITS.get(league.get('modo', '2v2'), 4))
    if len(members_data.get(gid, {}).get(league_id, {})) >= limite:
        await interaction.response.send_message(embed=embed_err('Cheia', 'League está cheia.', interaction.user), ephemeral=True)
        return
    if gid not in members_data:
        members_data[gid] = {}
    if league_id not in members_data[gid]:
        members_data[gid][league_id] = {}
    members_data[gid][league_id][str(usuario.id)] = {'nick_ingame': nick_ingame, 'joined_at': datetime.now().isoformat(), 'discord_name': usuario.name, 'added_by': str(interaction.user.id)}
    save_json('league_members.json', members_data)
    thread_id = league.get('thread_id')
    if thread_id:
        try:
            thread = interaction.guild.get_thread(int(thread_id))
            if thread:
                await thread.add_user(usuario)
                en = discord.Embed(title='➕ Membro Adicionado', description=f'{usuario.mention} adicionado por {interaction.user.mention}', color=0x3498DB, timestamp=datetime.now())
                en.add_field(name=f'🎮 Nick ({league.get("jogo","?")})', value=f'`{nick_ingame}`', inline=True)
                await thread.send(embed=en)
        except Exception as ex:
            logger.error(f'Erro thread joinleague: {ex}')
    count = len(members_data[gid][league_id])
    re = embed_ok('Adicionado', f'{usuario.mention} adicionado à League #{league_id}!', interaction.user)
    re.add_field(name=f'🎮 Nick ({league.get("jogo","?")})', value=f'`{nick_ingame}`', inline=True)
    re.add_field(name='👥 Participantes', value=f'{count}/{limite}', inline=True)
    await interaction.response.send_message(embed=re)


@bot.tree.command(name='kickleague', description='➖ Remove um usuário da league (Admin)')
@app_commands.describe(usuario='Usuário a remover', league_id='ID da league')
async def cmd_kickleague(interaction: discord.Interaction, usuario: discord.Member, league_id: str):
    if not is_admin_league(interaction.user):
        await interaction.response.send_message(embed=embed_err('Sem Permissão', 'Sem permissão.', interaction.user), ephemeral=True)
        return
    gid = str(interaction.guild.id)
    leagues = load_json('leagues_data.json')
    members_data = load_json('league_members.json')
    if gid not in leagues or league_id not in leagues[gid]:
        await interaction.response.send_message(embed=embed_err('Não Encontrada', f'League #{league_id} não existe.', interaction.user), ephemeral=True)
        return
    if str(usuario.id) not in members_data.get(gid, {}).get(league_id, {}):
        await interaction.response.send_message(embed=embed_err('Não Encontrado', f'{usuario.mention} não está nesta league.', interaction.user), ephemeral=True)
        return
    del members_data[gid][league_id][str(usuario.id)]
    save_json('league_members.json', members_data)
    thread_id = leagues[gid][league_id].get('thread_id')
    if thread_id:
        try:
            thread = interaction.guild.get_thread(int(thread_id))
            if thread:
                await thread.remove_user(usuario)
                out = discord.Embed(title='➖ Membro Removido', description=f'{usuario.mention} removido por {interaction.user.mention}', color=0xE74C3C, timestamp=datetime.now())
                await thread.send(embed=out)
        except Exception as ex:
            logger.error(f'Erro thread kickleague: {ex}')
    await interaction.response.send_message(embed=embed_ok('Removido', f'{usuario.mention} removido da League #{league_id}.', interaction.user))


@bot.tree.command(name='leaguelist', description='📋 Lista todas as leagues ativas')
async def cmd_leaguelist(interaction: discord.Interaction):
    gid = str(interaction.guild.id)
    leagues = load_json('leagues_data.json')
    members_data = load_json('league_members.json')
    ativas = {lid: l for lid, l in leagues.get(gid, {}).items() if l['status'] == 'ativa'}
    if not ativas:
        await interaction.response.send_message(embed=embed_info('Nenhuma League', 'Não há leagues ativas no momento.', interaction.user))
        return
    e = discord.Embed(title='📋 Leagues Ativas', description=f'**{len(ativas)}** league(s) ativa(s)', color=0xF1C40F, timestamp=datetime.now())
    for lid, league in list(ativas.items())[:10]:
        count = len(members_data.get(gid, {}).get(lid, {}))
        limite = league.get('limite', LEAGUE_LIMITS.get(league.get('modo', '2v2'), 4))
        jogo = league.get('jogo', 'N/A')
        modo = league.get('modo', 'N/A')
        e.add_field(
            name=f'⚔️ League #{lid} — {jogo}',
            value=f'**Modo:** {modo}\n**Jogadores:** {count}/{limite}\n**Criador:** <@{league["creator_id"]}>',
            inline=True
        )
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='league_info', description='ℹ️ Informações detalhadas de uma league')
@app_commands.describe(league_id='ID da league')
async def cmd_league_info(interaction: discord.Interaction, league_id: str):
    gid = str(interaction.guild.id)
    leagues = load_json('leagues_data.json')
    members_data = load_json('league_members.json')
    if gid not in leagues or league_id not in leagues[gid]:
        await interaction.response.send_message(embed=embed_err('Não Encontrada', f'League #{league_id} não existe.', interaction.user), ephemeral=True)
        return
    league = leagues[gid][league_id]
    jogo = league.get('jogo', 'N/A')
    modo = league.get('modo', 'N/A')
    limite = league.get('limite', LEAGUE_LIMITS.get(modo, 4))
    count = len(members_data.get(gid, {}).get(league_id, {}))
    e = discord.Embed(title=f'⚔️ League #{league_id} — {jogo}', color=0x3498DB, timestamp=datetime.now())
    e.add_field(name='🎮 Jogo', value=jogo, inline=True)
    e.add_field(name='⚔️ Modo', value=modo, inline=True)
    e.add_field(name='📊 Status', value=league['status'].title(), inline=True)
    e.add_field(name='👤 Criador', value=f'<@{league["creator_id"]}>', inline=True)
    e.add_field(name='📅 Criada', value=datetime.fromisoformat(league['created_at']).strftime('%d/%m/%Y %H:%M'), inline=True)
    e.add_field(name='👥 Participantes', value=f'{count}/{limite}', inline=True)
    e.add_field(name='🔗 Link do Lobby', value=f'```{league["link_privado"]}```', inline=False)
    thread_id = league.get('thread_id')
    if thread_id:
        thread = interaction.guild.get_thread(int(thread_id))
        if thread:
            e.add_field(name='💬 Tópico', value=thread.mention, inline=False)
    if league['status'] == 'encerrada' and league.get('vencedor'):
        e.add_field(name='🏆 Vencedor', value=league['vencedor'], inline=False)
    e.set_footer(text=f'League ID: {league_id}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='league_members', description='👥 Lista membros de uma league')
@app_commands.describe(league_id='ID da league')
async def cmd_league_members(interaction: discord.Interaction, league_id: str):
    gid = str(interaction.guild.id)
    leagues = load_json('leagues_data.json')
    members_data = load_json('league_members.json')
    if gid not in leagues or league_id not in leagues[gid]:
        await interaction.response.send_message(embed=embed_err('Não Encontrada', f'League #{league_id} não existe.', interaction.user), ephemeral=True)
        return
    league = leagues[gid][league_id]
    jogo = league.get('jogo', 'Jogo')
    modo = league.get('modo', 'N/A')
    limite = league.get('limite', LEAGUE_LIMITS.get(modo, 4))
    members = members_data.get(gid, {}).get(league_id, {})
    if not members:
        await interaction.response.send_message(embed=embed_info('Sem Membros', f'League #{league_id} não tem membros ainda.', interaction.user))
        return
    e = discord.Embed(
        title=f'👥 League #{league_id} — {jogo}',
        description=f'**Modo:** {modo} | **Participantes:** {len(members)}/{limite}',
        color=0x3498DB, timestamp=datetime.now()
    )
    for i, (uid, info) in enumerate(members.items(), 1):
        joined = datetime.fromisoformat(info['joined_at']).strftime('%d/%m/%Y %H:%M')
        nick = info.get('nick_ingame') or info.get('roblox_username', 'N/A')
        e.add_field(name=f'{i}. {info["discord_name"]}', value=f'<@{uid}>\n🎮 `{nick}`\n📅 {joined}', inline=True)
    e.set_footer(text=f'League ID: {league_id}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='endleague', description='🏁 Encerra uma league e declara vencedor')
@app_commands.describe(league_id='ID da league', vencedor='Time/jogador vencedor')
async def cmd_endleague(interaction: discord.Interaction, league_id: str, vencedor: str):
    if not is_admin_league(interaction.user):
        await interaction.response.send_message(embed=embed_err('Sem Permissão', 'Sem permissão.', interaction.user), ephemeral=True)
        return
    gid = str(interaction.guild.id)
    leagues = load_json('leagues_data.json')
    if gid not in leagues or league_id not in leagues[gid]:
        await interaction.response.send_message(embed=embed_err('Não Encontrada', f'League #{league_id} não existe.', interaction.user), ephemeral=True)
        return
    league = leagues[gid][league_id]
    league.update({'status': 'encerrada', 'vencedor': vencedor, 'ended_at': datetime.now().isoformat(), 'ended_by': str(interaction.user.id)})
    save_json('leagues_data.json', leagues)
    thread_id = league.get('thread_id')
    if thread_id:
        try:
            thread = interaction.guild.get_thread(int(thread_id))
            if thread:
                end_e = discord.Embed(title='🏁 League Encerrada!', color=0xF1C40F, timestamp=datetime.now())
                end_e.add_field(name='🏆 Vencedor', value=vencedor, inline=False)
                end_e.add_field(name='🎯 Modo', value=league['modo'], inline=True)
                members_data = load_json('league_members.json')
                members = members_data.get(gid, {}).get(league_id, {})
                if members:
                    end_e.add_field(name='👥 Participantes', value=', '.join(f'<@{uid}>' for uid in members.keys()), inline=False)
                end_e.set_footer(text=f'Encerrada por {interaction.user.name}')
                await thread.send(embed=end_e)
                await thread.edit(archived=True, locked=True)
        except Exception as ex:
            logger.error(f'Erro arquivar thread: {ex}')
    re = embed_ok('League Encerrada', f'League #{league_id} encerrada!', interaction.user)
    re.add_field(name='🏆 Vencedor', value=vencedor, inline=True)
    re.add_field(name='🎯 Modo', value=league['modo'], inline=True)
    await interaction.response.send_message(embed=re)


@bot.tree.command(name='setup_league_channel', description='⚙️ Define o canal padrão para leagues')
@app_commands.describe(canal='Canal onde leagues serão criadas')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_setup_league_channel(interaction: discord.Interaction, canal: discord.TextChannel):
    gid = str(interaction.guild.id)
    lc = load_json('league_config.json')
    if gid not in lc:
        lc[gid] = {}
    lc[gid]['league_channel_id'] = str(canal.id)
    save_json('league_config.json', lc)
    await interaction.response.send_message(embed=embed_ok('Canal Configurado', f'{canal.mention} configurado para leagues!', interaction.user))

@bot.tree.command(name='warn', description='⚠️ Avisa um membro')
@app_commands.describe(usuario='Usuário a avisar', motivo='Motivo do aviso')
@app_commands.checks.has_permissions(moderate_members=True)
async def cmd_warn(interaction: discord.Interaction, usuario: discord.Member, motivo: str):
    gid = str(interaction.guild.id)
    uid = str(usuario.id)
    if not pode_moderar(interaction.user, usuario):
        await interaction.response.send_message(embed=embed_err('Hierarquia', 'Você não pode moderar este usuário.', interaction.user), ephemeral=True)
        return
    warnings = load_json('warnings_data.json')
    if gid not in warnings:
        warnings[gid] = {}
    if uid not in warnings[gid]:
        warnings[gid][uid] = []
    warnings[gid][uid].append({'motivo': motivo, 'mod': str(interaction.user.id), 'timestamp': datetime.now().isoformat()})
    save_json('warnings_data.json', warnings)
    cid = registrar_case(gid, 'warn', usuario, interaction.user, motivo)
    await notificar_mod(usuario, 'warn', motivo, interaction.user)
    await log_moderacao(interaction.guild, 'warn', usuario, interaction.user, motivo, cid)
    total = len(warnings[gid][uid])
    e = embed_ok('Aviso Aplicado', f'{usuario.mention} recebeu um aviso.\n**Motivo:** {motivo}\n**Total de avisos:** {total}', interaction.user)
    e.add_field(name='📋 Case', value=f'`#{cid}`', inline=True)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='warnings', description='📋 Lista os avisos de um membro')
@app_commands.describe(usuario='Usuário para verificar')
async def cmd_warnings(interaction: discord.Interaction, usuario: discord.Member):
    gid = str(interaction.guild.id)
    uid = str(usuario.id)
    warnings = load_json('warnings_data.json')
    lista = warnings.get(gid, {}).get(uid, [])
    if not lista:
        await interaction.response.send_message(embed=embed_info('Sem Avisos', f'{usuario.mention} não tem avisos.', interaction.user))
        return
    e = discord.Embed(title=f'⚠️ Avisos de {usuario.name}', description=f'Total: **{len(lista)}** avisos', color=0xF39C12, timestamp=datetime.now())
    e.set_thumbnail(url=usuario.display_avatar.url)
    for i, w in enumerate(lista[-10:], 1):
        mod_id = w.get('mod', '?')
        ts = datetime.fromisoformat(w['timestamp']).strftime('%d/%m/%Y %H:%M')
        e.add_field(name=f'#{i} — {ts}', value=f'**Motivo:** {w["motivo"]}\n**Mod:** <@{mod_id}>', inline=False)
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='clearwarns', description='🗑️ Remove todos os avisos de um membro')
@app_commands.describe(usuario='Usuário para limpar avisos')
@app_commands.checks.has_permissions(moderate_members=True)
async def cmd_clearwarns(interaction: discord.Interaction, usuario: discord.Member):
    gid = str(interaction.guild.id)
    uid = str(usuario.id)
    warnings = load_json('warnings_data.json')
    total = len(warnings.get(gid, {}).get(uid, []))
    if gid in warnings:
        warnings[gid][uid] = []
    save_json('warnings_data.json', warnings)
    await interaction.response.send_message(embed=embed_ok('Avisos Removidos', f'{total} avisos de {usuario.mention} foram removidos.', interaction.user))


@bot.tree.command(name='removewarn', description='🗑️ Remove um aviso específico')
@app_commands.describe(usuario='Usuário', numero='Número do aviso (1, 2, 3...)')
@app_commands.checks.has_permissions(moderate_members=True)
async def cmd_removewarn(interaction: discord.Interaction, usuario: discord.Member, numero: int):
    gid = str(interaction.guild.id)
    uid = str(usuario.id)
    warnings = load_json('warnings_data.json')
    lista = warnings.get(gid, {}).get(uid, [])
    if not lista:
        await interaction.response.send_message(embed=embed_err('Sem Avisos', f'{usuario.mention} não tem avisos.', interaction.user), ephemeral=True)
        return
    if numero < 1 or numero > len(lista):
        await interaction.response.send_message(embed=embed_err('Inválido', f'Número deve ser entre 1 e {len(lista)}.', interaction.user), ephemeral=True)
        return
    removido = lista.pop(numero - 1)
    warnings[gid][uid] = lista
    save_json('warnings_data.json', warnings)
    await interaction.response.send_message(embed=embed_ok('Aviso Removido', f'Aviso #{numero} de {usuario.mention} removido.\n**Motivo era:** {removido["motivo"]}', interaction.user))


@bot.tree.command(name='ban', description='🔨 Bane permanentemente um membro')
@app_commands.describe(usuario='Usuário a banir', motivo='Motivo do ban', deletar_msgs='Deletar mensagens (dias, 0-7)')
@app_commands.checks.has_permissions(ban_members=True)
async def cmd_ban(interaction: discord.Interaction, usuario: discord.Member, motivo: str, deletar_msgs: int = 0):
    if not pode_moderar(interaction.user, usuario):
        await interaction.response.send_message(embed=embed_err('Hierarquia', 'Você não pode banir este usuário.', interaction.user), ephemeral=True)
        return
    bot_member = interaction.guild.get_member(bot.user.id)
    if not bot_pode_moderar(bot_member, usuario):
        await interaction.response.send_message(embed=embed_err('Bot Sem Permissão', 'O bot não pode banir este usuário.', interaction.user), ephemeral=True)
        return
    gid = str(interaction.guild.id)
    cid = registrar_case(gid, 'ban', usuario, interaction.user, motivo)
    ban_data = load_json('ban_data.json')
    if gid not in ban_data:
        ban_data[gid] = {}
    ban_data[gid][str(usuario.id)] = {'tipo': 'permanente', 'motivo': motivo, 'mod': str(interaction.user.id), 'timestamp': datetime.now().isoformat()}
    save_json('ban_data.json', ban_data)
    await notificar_mod(usuario, 'ban', motivo, interaction.user)
    await usuario.ban(reason=f'[Case #{cid}] {motivo}', delete_message_days=min(deletar_msgs, 7))
    await log_moderacao(interaction.guild, 'ban', usuario, interaction.user, motivo, cid)
    e = embed_ok('Membro Banido', f'{usuario.mention} foi banido permanentemente.\n**Motivo:** {motivo}', interaction.user)
    e.add_field(name='📋 Case', value=f'`#{cid}`', inline=True)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='tempban', description='⏰ Bane temporariamente um membro')
@app_commands.describe(usuario='Usuário a banir', duracao='Duração (ex: 1d, 12h, 30m)', motivo='Motivo')
@app_commands.checks.has_permissions(ban_members=True)
async def cmd_tempban(interaction: discord.Interaction, usuario: discord.Member, duracao: str, motivo: str):
    if not pode_moderar(interaction.user, usuario):
        await interaction.response.send_message(embed=embed_err('Hierarquia', 'Você não pode banir este usuário.', interaction.user), ephemeral=True)
        return
    duracao_lower = duracao.lower()
    segundos = 0
    if 'd' in duracao_lower:
        try:
            segundos += int(duracao_lower.split('d')[0]) * 86400
        except ValueError:
            pass
    if 'h' in duracao_lower:
        try:
            part = duracao_lower.split('h')[0].split('d')[-1]
            segundos += int(part) * 3600
        except ValueError:
            pass
    if 'm' in duracao_lower:
        try:
            part = duracao_lower.split('m')[0].split('h')[-1].split('d')[-1]
            segundos += int(part) * 60
        except ValueError:
            pass
    if segundos <= 0:
        await interaction.response.send_message(embed=embed_err('Duração Inválida', 'Use: `1d`, `12h`, `30m` ou combinações como `1d12h`.', interaction.user), ephemeral=True)
        return
    gid = str(interaction.guild.id)
    expiry = datetime.now() + timedelta(seconds=segundos)
    cid = registrar_case(gid, 'tempban', usuario, interaction.user, motivo, duracao)
    ban_data = load_json('ban_data.json')
    if gid not in ban_data:
        ban_data[gid] = {}
    ban_data[gid][str(usuario.id)] = {'tipo': 'temporario', 'motivo': motivo, 'mod': str(interaction.user.id), 'timestamp': datetime.now().isoformat(), 'expiry': expiry.isoformat(), 'duracao': duracao}
    save_json('ban_data.json', ban_data)
    await notificar_mod(usuario, 'tempban', motivo, interaction.user, duracao)
    await usuario.ban(reason=f'[Case #{cid}] {motivo} | Duração: {duracao}')
    await log_moderacao(interaction.guild, 'tempban', usuario, interaction.user, motivo, cid, duracao)
    e = embed_ok('Ban Temporário', f'{usuario.mention} foi banido por **{duracao}**.\n**Motivo:** {motivo}', interaction.user)
    e.add_field(name='📋 Case', value=f'`#{cid}`', inline=True)
    e.add_field(name='⏰ Expira', value=expiry.strftime('%d/%m/%Y %H:%M'), inline=True)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='unban', description='🔓 Desbane um usuário')
@app_commands.describe(user_id='ID do usuário a desbanir', motivo='Motivo')
@app_commands.checks.has_permissions(ban_members=True)
async def cmd_unban(interaction: discord.Interaction, user_id: str, motivo: str = 'Sem motivo especificado'):
    try:
        user = await bot.fetch_user(int(user_id))
    except Exception:
        await interaction.response.send_message(embed=embed_err('Não Encontrado', f'Usuário com ID `{user_id}` não encontrado.', interaction.user), ephemeral=True)
        return
    gid = str(interaction.guild.id)
    try:
        await interaction.guild.unban(user, reason=motivo)
    except discord.NotFound:
        await interaction.response.send_message(embed=embed_err('Não Banido', f'{user.name} não está banido.', interaction.user), ephemeral=True)
        return
    ban_data = load_json('ban_data.json')
    if gid in ban_data and user_id in ban_data[gid]:
        del ban_data[gid][user_id]
        save_json('ban_data.json', ban_data)
    cid = registrar_case(gid, 'unban', interaction.guild.get_member(user.id) or user, interaction.user, motivo)
    await log_canal(interaction.guild, 'unban', {'usuario': f'{user.name} ({user.id})', 'motivo': motivo, 'mod': interaction.user.name})
    e = embed_ok('Usuário Desbanido', f'**{user.name}** foi desbanido.\n**Motivo:** {motivo}', interaction.user)
    e.add_field(name='📋 Case', value=f'`#{cid}`', inline=True)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='mute', description='🔇 Silencia um membro')
@app_commands.describe(usuario='Usuário a silenciar', duracao='Duração (ex: 1h, 30m)', motivo='Motivo')
@app_commands.checks.has_permissions(moderate_members=True)
async def cmd_mute(interaction: discord.Interaction, usuario: discord.Member, duracao: str, motivo: str):
    if not pode_moderar(interaction.user, usuario):
        await interaction.response.send_message(embed=embed_err('Hierarquia', 'Você não pode silenciar este usuário.', interaction.user), ephemeral=True)
        return
    duracao_lower = duracao.lower()
    segundos = 0
    if 'd' in duracao_lower:
        try:
            segundos += int(duracao_lower.split('d')[0]) * 86400
        except ValueError:
            pass
    if 'h' in duracao_lower:
        try:
            part = duracao_lower.split('h')[0].split('d')[-1]
            segundos += int(part) * 3600
        except ValueError:
            pass
    if 'm' in duracao_lower:
        try:
            part = duracao_lower.split('m')[0].split('h')[-1].split('d')[-1]
            segundos += int(part) * 60
        except ValueError:
            pass
    if segundos <= 0:
        await interaction.response.send_message(embed=embed_err('Duração Inválida', 'Use: `1h`, `30m`, `1d12h`.', interaction.user), ephemeral=True)
        return
    if segundos > 2419200:
        await interaction.response.send_message(embed=embed_err('Muito Longo', 'Mute máximo é de 28 dias.', interaction.user), ephemeral=True)
        return
    gid = str(interaction.guild.id)
    expiry = datetime.now() + timedelta(seconds=segundos)
    try:
        await usuario.timeout(timedelta(seconds=segundos), reason=f'{motivo}')
    except Exception as ex:
        await interaction.response.send_message(embed=embed_err('Erro', f'Não foi possível silenciar: {ex}', interaction.user), ephemeral=True)
        return
    mute_data = load_json('mute_data.json')
    if gid not in mute_data:
        mute_data[gid] = {}
    mute_data[gid][str(usuario.id)] = {'motivo': motivo, 'mod': str(interaction.user.id), 'timestamp': datetime.now().isoformat(), 'expiry': expiry.isoformat(), 'duracao': duracao}
    save_json('mute_data.json', mute_data)
    cid = registrar_case(gid, 'mute', usuario, interaction.user, motivo, duracao)
    await notificar_mod(usuario, 'mute', motivo, interaction.user, duracao)
    await log_moderacao(interaction.guild, 'mute', usuario, interaction.user, motivo, cid, duracao)
    e = embed_ok('Membro Silenciado', f'{usuario.mention} foi silenciado por **{duracao}**.\n**Motivo:** {motivo}', interaction.user)
    e.add_field(name='📋 Case', value=f'`#{cid}`', inline=True)
    e.add_field(name='⏰ Expira', value=expiry.strftime('%d/%m/%Y %H:%M'), inline=True)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='unmute', description='🔊 Remove o silenciamento de um membro')
@app_commands.describe(usuario='Usuário a dessilenciar', motivo='Motivo')
@app_commands.checks.has_permissions(moderate_members=True)
async def cmd_unmute(interaction: discord.Interaction, usuario: discord.Member, motivo: str = 'Remoção manual'):
    if not usuario.is_timed_out():
        await interaction.response.send_message(embed=embed_err('Não Silenciado', f'{usuario.mention} não está silenciado.', interaction.user), ephemeral=True)
        return
    gid = str(interaction.guild.id)
    await usuario.timeout(None, reason=motivo)
    mute_data = load_json('mute_data.json')
    if gid in mute_data and str(usuario.id) in mute_data[gid]:
        del mute_data[gid][str(usuario.id)]
        save_json('mute_data.json', mute_data)
    cid = registrar_case(gid, 'unmute', usuario, interaction.user, motivo)
    await log_moderacao(interaction.guild, 'unmute', usuario, interaction.user, motivo, cid)
    await interaction.response.send_message(embed=embed_ok('Silenciamento Removido', f'{usuario.mention} foi dessilenciado.\n**Motivo:** {motivo}', interaction.user))


@bot.tree.command(name='kick', description='👢 Expulsa um membro do servidor')
@app_commands.describe(usuario='Usuário a expulsar', motivo='Motivo')
@app_commands.checks.has_permissions(kick_members=True)
async def cmd_kick(interaction: discord.Interaction, usuario: discord.Member, motivo: str):
    if not pode_moderar(interaction.user, usuario):
        await interaction.response.send_message(embed=embed_err('Hierarquia', 'Você não pode expulsar este usuário.', interaction.user), ephemeral=True)
        return
    gid = str(interaction.guild.id)
    cid = registrar_case(gid, 'kick', usuario, interaction.user, motivo)
    await notificar_mod(usuario, 'kick', motivo, interaction.user)
    await usuario.kick(reason=f'[Case #{cid}] {motivo}')
    await log_moderacao(interaction.guild, 'kick', usuario, interaction.user, motivo, cid)
    e = embed_ok('Membro Expulso', f'{usuario.mention} foi expulso.\n**Motivo:** {motivo}', interaction.user)
    e.add_field(name='📋 Case', value=f'`#{cid}`', inline=True)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='case', description='📋 Mostra informações de um case')
@app_commands.describe(case_id='Número do case')
@app_commands.checks.has_permissions(moderate_members=True)
async def cmd_case(interaction: discord.Interaction, case_id: int):
    gid = str(interaction.guild.id)
    cases = load_json('cases_data.json')
    case = cases.get(gid, {}).get(str(case_id))
    if not case:
        await interaction.response.send_message(embed=embed_err('Não Encontrado', f'Case #{case_id} não existe.', interaction.user), ephemeral=True)
        return
    emojis_c = {'warn': '⚠️', 'kick': '👢', 'ban': '🔨', 'tempban': '⏰', 'mute': '🔇', 'unmute': '🔊', 'unban': '🔓'}
    e = discord.Embed(title=f'{emojis_c.get(case["tipo"], "📋")} Case #{case_id}', color=0x3498DB, timestamp=datetime.now())
    e.add_field(name='👤 Usuário', value=f'<@{case["usuario_id"]}>\n`{case["usuario_name"]}`', inline=True)
    e.add_field(name='🛡️ Moderador', value=f'<@{case["moderador_id"]}>\n`{case["moderador_name"]}`', inline=True)
    e.add_field(name='📋 Tipo', value=case['tipo'].title(), inline=True)
    e.add_field(name='📝 Motivo', value=case['motivo'], inline=False)
    if case.get('duracao'):
        e.add_field(name='⏰ Duração', value=case['duracao'], inline=True)
    e.add_field(name='📅 Data', value=datetime.fromisoformat(case['timestamp']).strftime('%d/%m/%Y %H:%M'), inline=True)
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='cases', description='📋 Lista os últimos cases do servidor')
@app_commands.describe(usuario='Filtrar por usuário (opcional)')
@app_commands.checks.has_permissions(moderate_members=True)
async def cmd_cases(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
    gid = str(interaction.guild.id)
    cases = load_json('cases_data.json').get(gid, {})
    if not cases:
        await interaction.response.send_message(embed=embed_info('Sem Cases', 'Não há cases registrados.', interaction.user))
        return
    lista = list(cases.values())
    if usuario:
        lista = [c for c in lista if c['usuario_id'] == str(usuario.id)]
    lista.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    titulo = f'📋 Últimos Cases{f" de {usuario.name}" if usuario else ""}'
    e = discord.Embed(title=titulo, description=f'Total: **{len(lista)}** case(s)', color=0x3498DB, timestamp=datetime.now())
    emojis_c = {'warn': '⚠️', 'kick': '👢', 'ban': '🔨', 'tempban': '⏰', 'mute': '🔇', 'unmute': '🔊', 'unban': '🔓'}
    for case in lista[:10]:
        emoji = emojis_c.get(case['tipo'], '📋')
        ts = datetime.fromisoformat(case['timestamp']).strftime('%d/%m/%Y %H:%M')
        e.add_field(name=f'`#{case["case_id"]}` {emoji} {case["tipo"].title()} — {ts}', value=f'**Usuário:** <@{case["usuario_id"]}>\n**Motivo:** {case["motivo"]}\n**Mod:** <@{case["moderador_id"]}>', inline=False)
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='slowmode', description='🐌 Define o modo lento do canal')
@app_commands.describe(segundos='Segundos de delay (0 para desativar)', canal='Canal (padrão: atual)')
@app_commands.checks.has_permissions(manage_channels=True)
async def cmd_slowmode(interaction: discord.Interaction, segundos: int, canal: Optional[discord.TextChannel] = None):
    ch = canal or interaction.channel
    if segundos < 0 or segundos > 21600:
        await interaction.response.send_message(embed=embed_err('Inválido', 'Valor deve ser entre **0** e **21600** segundos (6h).', interaction.user), ephemeral=True)
        return
    # Checar se bot tem permissão no canal alvo
    bot_perms = ch.permissions_for(interaction.guild.me)
    if not bot_perms.manage_channels:
        await interaction.response.send_message(embed=embed_err('Bot Sem Permissão', f'Não tenho permissão de **Gerenciar Canais** em {ch.mention}.', interaction.user), ephemeral=True)
        return
    try:
        await ch.edit(slowmode_delay=segundos)
    except discord.Forbidden:
        await interaction.response.send_message(embed=embed_err('Sem Permissão', f'Não consigo editar {ch.mention}. Verifique a hierarquia do bot.', interaction.user), ephemeral=True)
        return
    except Exception as ex:
        await interaction.response.send_message(embed=embed_err('Erro', f'Não foi possível alterar o slowmode: {ex}', interaction.user), ephemeral=True)
        return
    if segundos == 0:
        await interaction.response.send_message(embed=embed_ok('Slowmode Desativado', f'Modo lento removido de {ch.mention}.', interaction.user))
    else:
        await interaction.response.send_message(embed=embed_ok('Slowmode Ativado', f'Modo lento de **{segundos}s** ativado em {ch.mention}.', interaction.user))


@bot.tree.command(name='purge', description='🗑️ Deleta mensagens do canal')
@app_commands.describe(quantidade='Quantidade de mensagens (1-100)', usuario='Deletar só de um usuário (opcional)')
@app_commands.checks.has_permissions(manage_messages=True)
async def cmd_purge(interaction: discord.Interaction, quantidade: int, usuario: Optional[discord.Member] = None):
    if quantidade < 1 or quantidade > 100:
        await interaction.response.send_message(embed=embed_err('Inválido', 'Quantidade deve ser entre 1 e 100.', interaction.user), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    if usuario:
        def check(m):
            return m.author == usuario
        deleted = await interaction.channel.purge(limit=quantidade, check=check)
    else:
        deleted = await interaction.channel.purge(limit=quantidade)
    await interaction.followup.send(embed=embed_ok('Mensagens Deletadas', f'`{len(deleted)}` mensagens deletadas{f" de {usuario.mention}" if usuario else ""}.', interaction.user), ephemeral=True)


@bot.tree.command(name='clear', description='🗑️ Deleta uma quantidade específica de mensagens (max 1000)')
@app_commands.describe(quantidade='Quantidade de mensagens para deletar (1-1000)')
@app_commands.checks.has_permissions(manage_messages=True)
async def cmd_clear(interaction: discord.Interaction, quantidade: int):
    if quantidade < 1 or quantidade > 1000:
        await interaction.response.send_message(embed=embed_err('Inválido', 'A quantidade deve ser entre **1** e **1000**.', interaction.user), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    total_deletado = 0
    restante = quantidade
    while restante > 0:
        lote = min(restante, 100)
        try:
            deleted = await interaction.channel.purge(limit=lote)
            total_deletado += len(deleted)
            restante -= len(deleted)
            if len(deleted) < lote:
                break  # Não há mais mensagens
        except discord.HTTPException:
            break
        if restante > 0:
            await asyncio.sleep(0.5)
    await interaction.followup.send(
        embed=embed_ok('Clear Concluído', f'`{total_deletado}` mensagem(ns) deletada(s) em {interaction.channel.mention}.', interaction.user),
        ephemeral=True
    )


@bot.tree.command(name='lock', description='🔒 Tranca um canal (impede membros de enviar mensagens)')
@app_commands.describe(canal='Canal a trancar (padrão: atual)', motivo='Motivo')
@app_commands.checks.has_permissions(manage_channels=True)
async def cmd_lock(interaction: discord.Interaction, canal: Optional[discord.TextChannel] = None, motivo: str = 'Sem motivo'):
    ch = canal or interaction.channel
    bot_perms = ch.permissions_for(interaction.guild.me)
    if not bot_perms.manage_channels:
        await interaction.response.send_message(embed=embed_err('Bot Sem Permissão', f'Não tenho permissão de **Gerenciar Canais** em {ch.mention}.', interaction.user), ephemeral=True)
        return
    try:
        overwrite = ch.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await ch.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f'{interaction.user.name}: {motivo}')
    except discord.Forbidden:
        await interaction.response.send_message(embed=embed_err('Sem Permissão', f'Não consigo trancar {ch.mention}. Verifique a hierarquia.', interaction.user), ephemeral=True)
        return
    except Exception as ex:
        await interaction.response.send_message(embed=embed_err('Erro', str(ex), interaction.user), ephemeral=True)
        return
    e = discord.Embed(title='🔒 Canal Trancado', description=f'{ch.mention} foi trancado.\n**Motivo:** {motivo}', color=0xE74C3C, timestamp=datetime.now())
    e.set_footer(text=f'Por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='unlock', description='🔓 Destranca um canal')
@app_commands.describe(canal='Canal a destrancar (padrão: atual)')
@app_commands.checks.has_permissions(manage_channels=True)
async def cmd_unlock(interaction: discord.Interaction, canal: Optional[discord.TextChannel] = None):
    ch = canal or interaction.channel
    bot_perms = ch.permissions_for(interaction.guild.me)
    if not bot_perms.manage_channels:
        await interaction.response.send_message(embed=embed_err('Bot Sem Permissão', f'Não tenho permissão de **Gerenciar Canais** em {ch.mention}.', interaction.user), ephemeral=True)
        return
    try:
        overwrite = ch.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await ch.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    except discord.Forbidden:
        await interaction.response.send_message(embed=embed_err('Sem Permissão', f'Não consigo destrancar {ch.mention}.', interaction.user), ephemeral=True)
        return
    e = discord.Embed(title='🔓 Canal Destrancado', description=f'{ch.mention} foi destrancado.', color=0x2ECC71, timestamp=datetime.now())
    e.set_footer(text=f'Por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='lockdown', description='🔒 Tranca todos os canais do servidor')
@app_commands.describe(motivo='Motivo do lockdown')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_lockdown(interaction: discord.Interaction, motivo: str = 'Lockdown do servidor'):
    await interaction.response.defer()
    count = 0
    erros = 0
    for ch in interaction.guild.text_channels:
        bot_perms = ch.permissions_for(interaction.guild.me)
        if not bot_perms.manage_channels:
            erros += 1
            continue
        try:
            overwrite = ch.overwrites_for(interaction.guild.default_role)
            overwrite.send_messages = False
            await ch.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=motivo)
            count += 1
            await asyncio.sleep(0.3)  # evitar rate limit
        except Exception:
            erros += 1
    e = discord.Embed(title='🔒 LOCKDOWN ATIVADO', description=f'**{count}** canais trancados.\n**Motivo:** {motivo}', color=0xE74C3C, timestamp=datetime.now())
    if erros:
        e.add_field(name='⚠️ Erros', value=f'{erros} canais não processados (sem permissão)', inline=False)
    e.set_footer(text=f'Por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.followup.send(embed=e)


@bot.tree.command(name='unlockdown', description='🔓 Remove o lockdown do servidor')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_unlockdown(interaction: discord.Interaction):
    await interaction.response.defer()
    count = 0
    erros = 0
    for ch in interaction.guild.text_channels:
        bot_perms = ch.permissions_for(interaction.guild.me)
        if not bot_perms.manage_channels:
            erros += 1
            continue
        try:
            overwrite = ch.overwrites_for(interaction.guild.default_role)
            overwrite.send_messages = None
            await ch.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            count += 1
            await asyncio.sleep(0.3)
        except Exception:
            erros += 1
    e = discord.Embed(title='🔓 LOCKDOWN REMOVIDO', description=f'**{count}** canais destrancados.', color=0x2ECC71, timestamp=datetime.now())
    if erros:
        e.add_field(name='⚠️ Erros', value=f'{erros} canais não processados', inline=False)
    e.set_footer(text=f'Por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.followup.send(embed=e)


@bot.tree.command(name='nick', description='✏️ Altera o apelido de um membro')
@app_commands.describe(usuario='Usuário', novo_nick='Novo apelido (deixe vazio para remover)')
@app_commands.checks.has_permissions(manage_nicknames=True)
async def cmd_nick(interaction: discord.Interaction, usuario: discord.Member, novo_nick: str = ''):
    if usuario.id == interaction.guild.owner_id:
        await interaction.response.send_message(embed=embed_err('Sem Permissão', 'Não posso alterar o apelido do dono do servidor.', interaction.user), ephemeral=True)
        return
    bot_member = interaction.guild.me
    if bot_member.top_role <= usuario.top_role:
        await interaction.response.send_message(embed=embed_err('Hierarquia', 'Meu cargo precisa estar acima do cargo do usuário para alterar o apelido.', interaction.user), ephemeral=True)
        return
    antigo = usuario.display_name
    try:
        await usuario.edit(nick=novo_nick if novo_nick else None, reason=f'Nick alterado por {interaction.user.name}')
    except discord.Forbidden:
        await interaction.response.send_message(embed=embed_err('Sem Permissão', 'Não tenho permissão para alterar este apelido.', interaction.user), ephemeral=True)
        return
    except Exception as ex:
        await interaction.response.send_message(embed=embed_err('Erro', str(ex), interaction.user), ephemeral=True)
        return
    if novo_nick:
        await interaction.response.send_message(embed=embed_ok('Nick Alterado', f'{usuario.mention}: `{antigo}` → `{novo_nick}`', interaction.user))
    else:
        await interaction.response.send_message(embed=embed_ok('Nick Removido', f'Nick de {usuario.mention} removido. Voltou para `{usuario.name}`.', interaction.user))


@bot.tree.command(name='addrole', description='➕ Adiciona um cargo a um membro')
@app_commands.describe(usuario='Usuário', cargo='Cargo a adicionar')
@app_commands.checks.has_permissions(manage_roles=True)
async def cmd_addrole(interaction: discord.Interaction, usuario: discord.Member, cargo: discord.Role):
    if cargo in usuario.roles:
        await interaction.response.send_message(embed=embed_warn('Já Tem', f'{usuario.mention} já tem o cargo {cargo.mention}.', interaction.user), ephemeral=True)
        return
    if cargo >= interaction.guild.me.top_role:
        await interaction.response.send_message(embed=embed_err('Hierarquia', f'Não posso adicionar {cargo.mention} pois ele está igual ou acima do meu cargo.', interaction.user), ephemeral=True)
        return
    if cargo >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message(embed=embed_err('Hierarquia', f'Você não pode dar um cargo igual ou acima do seu.', interaction.user), ephemeral=True)
        return
    try:
        await usuario.add_roles(cargo, reason=f'Adicionado por {interaction.user.name}')
    except discord.Forbidden:
        await interaction.response.send_message(embed=embed_err('Sem Permissão', 'Não tenho permissão para adicionar este cargo.', interaction.user), ephemeral=True)
        return
    await interaction.response.send_message(embed=embed_ok('Cargo Adicionado', f'{cargo.mention} adicionado a {usuario.mention}.', interaction.user))


@bot.tree.command(name='removerole', description='➖ Remove um cargo de um membro')
@app_commands.describe(usuario='Usuário', cargo='Cargo a remover')
@app_commands.checks.has_permissions(manage_roles=True)
async def cmd_removerole(interaction: discord.Interaction, usuario: discord.Member, cargo: discord.Role):
    if cargo not in usuario.roles:
        await interaction.response.send_message(embed=embed_warn('Não Tem', f'{usuario.mention} não tem o cargo {cargo.mention}.', interaction.user), ephemeral=True)
        return
    if cargo >= interaction.guild.me.top_role:
        await interaction.response.send_message(embed=embed_err('Hierarquia', f'Não posso remover {cargo.mention} pois ele está igual ou acima do meu cargo.', interaction.user), ephemeral=True)
        return
    try:
        await usuario.remove_roles(cargo, reason=f'Removido por {interaction.user.name}')
    except discord.Forbidden:
        await interaction.response.send_message(embed=embed_err('Sem Permissão', 'Não tenho permissão para remover este cargo.', interaction.user), ephemeral=True)
        return
    await interaction.response.send_message(embed=embed_ok('Cargo Removido', f'{cargo.mention} removido de {usuario.mention}.', interaction.user))


class TicketOptionSelect(Select):
    def __init__(self, opcoes: List[Dict[str, str]]):
        options = [
            discord.SelectOption(
                label=op['nome'][:25],
                description=op.get('descricao', '')[:50],
                emoji='🎫',
                value=str(i)
            )
            for i, op in enumerate(opcoes)
        ]
        super().__init__(placeholder='📂 Escolha o tipo de ticket...', options=options, custom_id='ticket_select')
        self.opcoes = opcoes

    async def callback(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        uid = str(interaction.user.id)
        idx = int(self.values[0])
        opcao = self.opcoes[idx]
        cfg = load_json('ticket_config.json').get(gid, {})
        tickets = load_json('tickets_data.json')
        # Verificar ticket já aberto
        for tid, t in tickets.get(gid, {}).items():
            if t.get('user_id') == uid and t.get('status') == 'aberto':
                ch = interaction.guild.get_channel(int(tid))
                if ch:
                    await interaction.response.send_message(embed=embed_warn('Ticket Já Aberto', f'Você já tem um ticket aberto: {ch.mention}', interaction.user), ephemeral=True)
                    return
        cat_id = cfg.get('ticket_category_id')
        category = interaction.guild.get_channel(int(cat_id)) if cat_id else None
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True)
        }
        # Adicionar até 5 cargos responsáveis
        for role_id in cfg.get('ticket_roles', []):
            r = interaction.guild.get_role(int(role_id))
            if r:
                overwrites[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        # Fallback cargo mod
        mod_id = cfg.get('ticket_mod_role_id') or load_json('config_data.json').get(gid, {}).get('mod_role_id')
        if mod_id:
            mr = interaction.guild.get_role(int(mod_id))
            if mr and mr not in overwrites:
                overwrites[mr] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        ticket_num = len(tickets.get(gid, {})) + 1
        nome_tipo = opcao['nome'].lower().replace(' ', '-')[:20]
        try:
            ch = await interaction.guild.create_text_channel(
                name=f'ticket-{ticket_num:04d}-{nome_tipo}',
                overwrites=overwrites,
                category=category,
                topic=f'{opcao["nome"]} | {interaction.user.name} ({interaction.user.id})'
            )
        except Exception as ex:
            await interaction.response.send_message(embed=embed_err('Erro', f'Não foi possível criar o ticket: {ex}', interaction.user), ephemeral=True)
            return
        if gid not in tickets:
            tickets[gid] = {}
        tickets[gid][str(ch.id)] = {
            'user_id': uid, 'username': interaction.user.name,
            'status': 'aberto', 'tipo': opcao['nome'],
            'created_at': datetime.now().isoformat(), 'numero': ticket_num
        }
        save_json('tickets_data.json', tickets)
        e = discord.Embed(
            title=f'🎫 {opcao["nome"]} — Ticket #{ticket_num:04d}',
            description=f'Olá {interaction.user.mention}!\n\n{opcao.get("descricao", "Descreva seu problema abaixo.")}\n\nUm membro da equipe irá te atender em breve.',
            color=0x3498DB, timestamp=datetime.now()
        )
        e.set_footer(text=f'Aberto por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
        await ch.send(f'{interaction.user.mention}', embed=e, view=TicketCloseView(str(ch.id)))
        # Mencionar roles responsáveis
        roles_mencionar = []
        for role_id in cfg.get('ticket_roles', []):
            r = interaction.guild.get_role(int(role_id))
            if r:
                roles_mencionar.append(r.mention)
        if roles_mencionar:
            await ch.send(' '.join(roles_mencionar))
        await interaction.response.send_message(embed=embed_ok('Ticket Criado!', f'Seu ticket foi aberto: {ch.mention}', interaction.user), ephemeral=True)
        log_ch_id = load_json('config_data.json').get(gid, {}).get('log_channel_id')
        if log_ch_id:
            lch = interaction.guild.get_channel(int(log_ch_id))
            if lch:
                le = discord.Embed(title='🎫 Novo Ticket', description=f'{interaction.user.mention} abriu ticket **{opcao["nome"]}** em {ch.mention}', color=0x3498DB, timestamp=datetime.now())
                await lch.send(embed=le)


class TicketPanelView(View):
    def __init__(self, opcoes: List[Dict[str, str]]):
        super().__init__(timeout=None)
        self.add_item(TicketOptionSelect(opcoes))


class TicketCloseView(View):
    def __init__(self, channel_id: str):
        super().__init__(timeout=None)
        self.channel_id = channel_id

    @discord.ui.button(label='🔒 Fechar Ticket', style=discord.ButtonStyle.red, custom_id='ticket_close')
    async def fechar(self, interaction: discord.Interaction, button: Button):
        gid = str(interaction.guild.id)
        ch_id = str(interaction.channel.id)
        tickets = load_json('tickets_data.json')
        ticket = tickets.get(gid, {}).get(ch_id)
        if not ticket:
            await interaction.response.send_message(embed=embed_err('Erro', 'Ticket não encontrado.', interaction.user), ephemeral=True)
            return
        cfg = load_json('ticket_config.json').get(gid, {})
        is_mod = interaction.user.guild_permissions.manage_channels
        for role_id in cfg.get('ticket_roles', []):
            r = interaction.guild.get_role(int(role_id))
            if r and r in interaction.user.roles:
                is_mod = True
        mod_id = cfg.get('ticket_mod_role_id') or load_json('config_data.json').get(gid, {}).get('mod_role_id')
        if mod_id:
            mr = interaction.guild.get_role(int(mod_id))
            if mr and mr in interaction.user.roles:
                is_mod = True
        if not is_mod and ticket.get('user_id') != str(interaction.user.id):
            await interaction.response.send_message(embed=embed_err('Sem Permissão', 'Apenas o dono do ticket ou responsáveis podem fechar.', interaction.user), ephemeral=True)
            return
        tickets[gid][ch_id].update({'status': 'fechado', 'closed_at': datetime.now().isoformat(), 'closed_by': str(interaction.user.id)})
        save_json('tickets_data.json', tickets)
        e = discord.Embed(title='🔒 Ticket Fechado', description=f'Fechado por {interaction.user.mention}.\nCanal será deletado em 5 segundos.', color=0xE74C3C, timestamp=datetime.now())
        await interaction.response.send_message(embed=e)
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f'Ticket fechado por {interaction.user.name}')
        except Exception as ex:
            logger.error(f'Erro ao deletar canal ticket: {ex}')


@bot.tree.command(name='setup_tickets', description='🎫 Cria um painel de tickets com opções personalizadas')
@app_commands.describe(
    canal='Canal onde o painel será enviado',
    titulo='Título do painel',
    descricao='Descrição do painel',
    opcoes='Opções separadas por | ex: Suporte:Preciso de ajuda|Report:Reportar usuário',
    categoria='Categoria para os tickets (opcional)',
    imagem_url='URL de imagem/banner do painel (opcional)'
)
@app_commands.checks.has_permissions(administrator=True)
async def cmd_setup_tickets(interaction: discord.Interaction, canal: discord.TextChannel, titulo: str, descricao: str, opcoes: str, categoria: Optional[discord.CategoryChannel] = None, imagem_url: str = ''):
    gid = str(interaction.guild.id)
    # Parsear opções: "Nome:Descrição|Nome2:Descrição2"
    lista_opcoes = []
    for parte in opcoes.split('|'):
        parte = parte.strip()
        if ':' in parte:
            nome, desc = parte.split(':', 1)
            lista_opcoes.append({'nome': nome.strip()[:25], 'descricao': desc.strip()[:100]})
        elif parte:
            lista_opcoes.append({'nome': parte[:25], 'descricao': 'Clique para abrir um ticket.'})
    if not lista_opcoes:
        await interaction.response.send_message(embed=embed_err('Opções Inválidas', 'Use o formato: `Suporte:Descrição|Outro:Descrição`', interaction.user), ephemeral=True)
        return
    if len(lista_opcoes) > 5:
        lista_opcoes = lista_opcoes[:5]
    cfg = load_json('ticket_config.json')
    if gid not in cfg:
        cfg[gid] = {}
    if categoria:
        cfg[gid]['ticket_category_id'] = str(categoria.id)
    cfg[gid]['ticket_opcoes'] = lista_opcoes
    save_json('ticket_config.json', cfg)
    e = discord.Embed(title=f'🎫 {titulo}', description=descricao, color=0x5865F2, timestamp=datetime.now())
    for op in lista_opcoes:
        e.add_field(name=f'🎫 {op["nome"]}', value=op['descricao'], inline=True)
    if imagem_url:
        e.set_image(url=imagem_url)
    e.set_footer(text=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
    await canal.send(embed=e, view=TicketPanelView(lista_opcoes))
    await interaction.response.send_message(embed=embed_ok('Painel de Tickets Criado!', f'Painel enviado em {canal.mention} com {len(lista_opcoes)} opção(ões)!', interaction.user))


@bot.tree.command(name='set_ticket_roles', description='⚙️ Define até 5 cargos responsáveis por tickets')
@app_commands.describe(cargo1='Cargo 1', cargo2='Cargo 2 (opcional)', cargo3='Cargo 3 (opcional)', cargo4='Cargo 4 (opcional)', cargo5='Cargo 5 (opcional)')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_set_ticket_roles(interaction: discord.Interaction, cargo1: discord.Role, cargo2: Optional[discord.Role] = None, cargo3: Optional[discord.Role] = None, cargo4: Optional[discord.Role] = None, cargo5: Optional[discord.Role] = None):
    gid = str(interaction.guild.id)
    cfg = load_json('ticket_config.json')
    if gid not in cfg:
        cfg[gid] = {}
    roles = [str(cargo1.id)]
    nomes = [cargo1.mention]
    for r in [cargo2, cargo3, cargo4, cargo5]:
        if r:
            roles.append(str(r.id))
            nomes.append(r.mention)
    cfg[gid]['ticket_roles'] = roles
    save_json('ticket_config.json', cfg)
    await interaction.response.send_message(embed=embed_ok('Cargos de Ticket Definidos', f'Cargos responsáveis: {", ".join(nomes)}', interaction.user))


@bot.tree.command(name='announce', description='📢 Faz um anúncio em embed com imagem opcional')
@app_commands.describe(canal='Canal do anúncio', titulo='Título', mensagem='Mensagem', cor='Cor hex (ex: FF5733)', mencionar='Mencionar @everyone ou @here', imagem_url='URL de imagem (opcional)')
@app_commands.choices(mencionar=[
    app_commands.Choice(name='@everyone', value='everyone'),
    app_commands.Choice(name='@here', value='here'),
    app_commands.Choice(name='Nenhum', value='none'),
])
@app_commands.checks.has_permissions(manage_guild=True)
async def cmd_announce(interaction: discord.Interaction, canal: discord.TextChannel, titulo: str, mensagem: str, cor: str = '3498DB', mencionar: str = 'none', imagem_url: str = ''):
    await interaction.response.defer(ephemeral=True)
    try:
        color_int = int(cor.lstrip('#'), 16)
    except ValueError:
        color_int = 0x3498DB
    e = discord.Embed(title=titulo, description=mensagem, color=color_int, timestamp=datetime.now())
    e.set_footer(text=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
    if imagem_url:
        e.set_image(url=imagem_url)
    mencao = ''
    if mencionar == 'everyone':
        mencao = '@everyone'
    elif mencionar == 'here':
        mencao = '@here'
    await canal.send(content=mencao if mencao else None, embed=e)
    await interaction.followup.send(embed=embed_ok('Anúncio Enviado', f'Anúncio enviado em {canal.mention}!', interaction.user), ephemeral=True)


@bot.tree.command(name='embed', description='📝 Envia uma mensagem embed customizada')
@app_commands.describe(canal='Canal', titulo='Título', descricao='Descrição', cor='Cor hex (ex: 3498DB)', rodape='Rodapé (opcional)')
@app_commands.checks.has_permissions(manage_messages=True)
async def cmd_embed(interaction: discord.Interaction, canal: discord.TextChannel, titulo: str, descricao: str, cor: str = '3498DB', rodape: str = ''):
    try:
        color_int = int(cor.lstrip('#'), 16)
    except ValueError:
        color_int = 0x3498DB
    e = discord.Embed(title=titulo, description=descricao, color=color_int, timestamp=datetime.now())
    if rodape:
        e.set_footer(text=rodape)
    await canal.send(embed=e)
    await interaction.response.send_message(embed=embed_ok('Embed Enviado', f'Embed enviado em {canal.mention}!', interaction.user), ephemeral=True)


@bot.tree.command(name='balance', description='💰 Mostra o saldo')
@app_commands.describe(usuario='Usuário (opcional)')
async def cmd_balance(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
    alvo = usuario or interaction.user
    gid = str(interaction.guild.id)
    uid = str(alvo.id)
    econ = get_user_economy(gid, uid)
    total = econ['coins'] + econ['bank']
    tier = calcular_tier(econ.get('total_earned', total))
    tier_info = TIERS[tier]
    e = discord.Embed(title=f'💰 Carteira de {alvo.name}', color=0xF1C40F, timestamp=datetime.now())
    e.set_thumbnail(url=alvo.display_avatar.url)
    e.add_field(name='👛 Carteira', value=f'🪙 **{econ["coins"]:,}** moedas', inline=True)
    e.add_field(name='🏦 Banco', value=f'🪙 **{econ["bank"]:,}** moedas', inline=True)
    e.add_field(name='💎 Total', value=f'🪙 **{total:,}** moedas', inline=True)
    e.add_field(name=f'🏆 Tier — {tier_info["emoji"]} {tier_info["nome"]}', value=f'Tier {tier}/5', inline=False)
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='daily', description='🎁 Resgata seu bônus diário')
async def cmd_daily(interaction: discord.Interaction):
    gid = str(interaction.guild.id)
    uid = str(interaction.user.id)
    pode, resto = pode_usar_cmd(gid, uid, 'daily', 86400)
    if not pode:
        h, r = divmod(resto, 3600)
        m, s = divmod(r, 60)
        await interaction.response.send_message(embed=embed_warn('Cooldown', f'Próximo daily em: **{h}h {m}m {s}s**', interaction.user), ephemeral=True)
        return
    econ = get_user_economy(gid, uid)
    ganho = random.randint(DAILY_MIN, DAILY_MAX)
    streak = econ.get('daily_streak', 0) + 1
    bonus = int(ganho * 0.1 * min(streak, 7))
    total_ganho = ganho + bonus
    econ['coins'] += total_ganho
    econ['total_earned'] = econ.get('total_earned', 0) + total_ganho
    econ['daily_streak'] = streak
    save_user_economy(gid, uid, econ)
    registrar_cooldown(gid, uid, 'daily')
    e = discord.Embed(title='🎁 Daily Resgatado!', color=0x2ECC71, timestamp=datetime.now())
    e.set_thumbnail(url=interaction.user.display_avatar.url)
    e.add_field(name='🪙 Base', value=f'**{ganho:,}** moedas', inline=True)
    e.add_field(name='🔥 Streak Bônus', value=f'+**{bonus:,}** moedas (×{streak} dias)', inline=True)
    e.add_field(name='✨ Total', value=f'**{total_ganho:,}** moedas', inline=True)
    e.add_field(name='👛 Carteira', value=f'🪙 {econ["coins"]:,}', inline=False)
    e.set_footer(text=f'Streak: {streak} dia(s) consecutivo(s)! 🔥', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='work', description='💼 Trabalhe e ganhe moedas')
async def cmd_work(interaction: discord.Interaction):
    gid = str(interaction.guild.id)
    uid = str(interaction.user.id)
    pode, resto = pode_usar_cmd(gid, uid, 'work', 3600)
    if not pode:
        m, s = divmod(resto, 60)
        await interaction.response.send_message(embed=embed_warn('Cooldown', f'Próximo trabalho em: **{m}m {s}s**', interaction.user), ephemeral=True)
        return
    econ = get_user_economy(gid, uid)
    ganho = random.randint(WORK_MIN, WORK_MAX)
    profissao = random.choice(PROFISSOES)
    econ['coins'] += ganho
    econ['total_earned'] = econ.get('total_earned', 0) + ganho
    save_user_economy(gid, uid, econ)
    registrar_cooldown(gid, uid, 'work')
    frases = [
        f'Você trabalhou como **{profissao}** e ganhou',
        f'Excelente trabalho como **{profissao}**! Você recebeu',
        f'Você concluiu seu turno como **{profissao}** e ganhou',
    ]
    e = discord.Embed(title='💼 Trabalho Concluído!', description=f'{random.choice(frases)} **{ganho:,}** moedas!', color=0x2ECC71, timestamp=datetime.now())
    e.set_thumbnail(url=interaction.user.display_avatar.url)
    e.add_field(name='👛 Carteira', value=f'🪙 {econ["coins"]:,}', inline=False)
    e.set_footer(text='Cooldown: 1 hora', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='deposit', description='🏦 Deposita moedas no banco')
@app_commands.describe(quantidade='Quantidade a depositar (ou "tudo")')
async def cmd_deposit(interaction: discord.Interaction, quantidade: str):
    gid = str(interaction.guild.id)
    uid = str(interaction.user.id)
    econ = get_user_economy(gid, uid)
    if quantidade.lower() in ('tudo', 'all', 'max'):
        valor = econ['coins']
    else:
        try:
            valor = int(quantidade)
        except ValueError:
            await interaction.response.send_message(embed=embed_err('Inválido', 'Digite um número ou "tudo".', interaction.user), ephemeral=True)
            return
    if valor <= 0:
        await interaction.response.send_message(embed=embed_err('Inválido', 'Valor deve ser maior que 0.', interaction.user), ephemeral=True)
        return
    if valor > econ['coins']:
        await interaction.response.send_message(embed=embed_err('Saldo Insuficiente', f'Você tem apenas **{econ["coins"]:,}** moedas na carteira.', interaction.user), ephemeral=True)
        return
    econ['coins'] -= valor
    econ['bank'] += valor
    save_user_economy(gid, uid, econ)
    e = embed_ok('Depósito Realizado', f'**{valor:,}** moedas depositadas no banco!', interaction.user)
    e.add_field(name='👛 Carteira', value=f'🪙 {econ["coins"]:,}', inline=True)
    e.add_field(name='🏦 Banco', value=f'🪙 {econ["bank"]:,}', inline=True)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='withdraw', description='💵 Saca moedas do banco')
@app_commands.describe(quantidade='Quantidade a sacar (ou "tudo")')
async def cmd_withdraw(interaction: discord.Interaction, quantidade: str):
    gid = str(interaction.guild.id)
    uid = str(interaction.user.id)
    econ = get_user_economy(gid, uid)
    if quantidade.lower() in ('tudo', 'all', 'max'):
        valor = econ['bank']
    else:
        try:
            valor = int(quantidade)
        except ValueError:
            await interaction.response.send_message(embed=embed_err('Inválido', 'Digite um número ou "tudo".', interaction.user), ephemeral=True)
            return
    if valor <= 0:
        await interaction.response.send_message(embed=embed_err('Inválido', 'Valor deve ser maior que 0.', interaction.user), ephemeral=True)
        return
    if valor > econ['bank']:
        await interaction.response.send_message(embed=embed_err('Saldo Insuficiente', f'Você tem apenas **{econ["bank"]:,}** no banco.', interaction.user), ephemeral=True)
        return
    econ['bank'] -= valor
    econ['coins'] += valor
    save_user_economy(gid, uid, econ)
    e = embed_ok('Saque Realizado', f'**{valor:,}** moedas sacadas do banco!', interaction.user)
    e.add_field(name='👛 Carteira', value=f'🪙 {econ["coins"]:,}', inline=True)
    e.add_field(name='🏦 Banco', value=f'🪙 {econ["bank"]:,}', inline=True)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='transfer', description='💸 Transfere moedas para outro usuário')
@app_commands.describe(usuario='Usuário receptor', quantidade='Quantidade a transferir')
async def cmd_transfer(interaction: discord.Interaction, usuario: discord.Member, quantidade: int):
    if usuario.bot or usuario.id == interaction.user.id:
        await interaction.response.send_message(embed=embed_err('Inválido', 'Destino inválido.', interaction.user), ephemeral=True)
        return
    if quantidade <= 0:
        await interaction.response.send_message(embed=embed_err('Inválido', 'Valor deve ser maior que 0.', interaction.user), ephemeral=True)
        return
    gid = str(interaction.guild.id)
    uid_from = str(interaction.user.id)
    uid_to = str(usuario.id)
    econ_from = get_user_economy(gid, uid_from)
    if quantidade > econ_from['coins']:
        await interaction.response.send_message(embed=embed_err('Saldo Insuficiente', f'Você tem apenas **{econ_from["coins"]:,}** moedas.', interaction.user), ephemeral=True)
        return
    econ_to = get_user_economy(gid, uid_to)
    taxa = int(quantidade * 0.02)
    valor_final = quantidade - taxa
    econ_from['coins'] -= quantidade
    econ_to['coins'] += valor_final
    save_user_economy(gid, uid_from, econ_from)
    save_user_economy(gid, uid_to, econ_to)
    e = embed_ok('Transferência Realizada', f'Você transferiu **{valor_final:,}** moedas para {usuario.mention}!', interaction.user)
    e.add_field(name='💸 Enviado', value=f'🪙 {quantidade:,}', inline=True)
    e.add_field(name='🏦 Taxa (2%)', value=f'🪙 {taxa:,}', inline=True)
    e.add_field(name='✅ Recebido', value=f'🪙 {valor_final:,}', inline=True)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='leaderboard', description='🏆 Ranking de mais ricos')
async def cmd_leaderboard(interaction: discord.Interaction):
    gid = str(interaction.guild.id)
    econ = load_json('economy_data.json').get(gid, {})
    if not econ:
        await interaction.response.send_message(embed=embed_info('Sem Dados', 'Nenhum dado de economia ainda.', interaction.user))
        return
    ranking = sorted(econ.items(), key=lambda x: x[1].get('coins', 0) + x[1].get('bank', 0), reverse=True)[:10]
    e = discord.Embed(title='🏆 Top 10 Mais Ricos', color=0xF1C40F, timestamp=datetime.now())
    medals = ['🥇', '🥈', '🥉'] + ['🏅'] * 7
    for i, (uid, data) in enumerate(ranking):
        total = data.get('coins', 0) + data.get('bank', 0)
        e.add_field(name=f'{medals[i]} #{i+1} — <@{uid}>', value=f'🪙 **{total:,}** moedas', inline=False)
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='slots', description='🎰 Jogue no caça-níqueis')
@app_commands.describe(aposta='Valor da aposta')
async def cmd_slots(interaction: discord.Interaction, aposta: int):
    gid = str(interaction.guild.id)
    uid = str(interaction.user.id)
    econ = get_user_economy(gid, uid)
    if aposta <= 0 or aposta > econ['coins']:
        await interaction.response.send_message(embed=embed_err('Aposta Inválida', f'Aposta inválida. Saldo: **{econ["coins"]:,}**', interaction.user), ephemeral=True)
        return
    simbolos = ['🍎', '🍊', '🍋', '🍇', '⭐', '💎', '7️⃣']
    resultado = [random.choice(simbolos) for _ in range(3)]
    linha = ' | '.join(resultado)
    if resultado[0] == resultado[1] == resultado[2]:
        if resultado[0] == '7️⃣':
            mult, msg = 10, '🎉 **JACKPOT! TRÊS 7s!**'
        elif resultado[0] == '💎':
            mult, msg = 5, '💎 **TRÊS DIAMANTES!**'
        else:
            mult, msg = 3, '🎊 **TRÊS IGUAIS!**'
        ganho = aposta * mult
        econ['coins'] += ganho - aposta
        econ['total_earned'] = econ.get('total_earned', 0) + ganho
        cor = 0x2ECC71
    elif resultado[0] == resultado[1] or resultado[1] == resultado[2]:
        ganho = int(aposta * 0.5)
        econ['coins'] += ganho - aposta
        msg = '🍀 **Par! Ganhou metade!**'
        cor = 0xF39C12
    else:
        ganho = 0
        econ['coins'] -= aposta
        msg = '❌ **Perdeu!**'
        cor = 0xE74C3C
    save_user_economy(gid, uid, econ)
    e = discord.Embed(title='🎰 Caça-Níqueis', description=f'`[ {linha} ]`\n\n{msg}', color=cor, timestamp=datetime.now())
    e.add_field(name='💰 Aposta', value=f'🪙 {aposta:,}', inline=True)
    e.add_field(name='🎁 Resultado', value=f'🪙 {ganho:,}', inline=True)
    e.add_field(name='👛 Carteira', value=f'🪙 {econ["coins"]:,}', inline=True)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='coinflip', description='🪙 Jogue cara ou coroa')
@app_commands.describe(escolha='Cara ou Coroa', aposta='Valor da aposta')
@app_commands.choices(escolha=[
    app_commands.Choice(name='Cara', value='cara'),
    app_commands.Choice(name='Coroa', value='coroa'),
])
async def cmd_coinflip(interaction: discord.Interaction, escolha: str, aposta: int):
    gid = str(interaction.guild.id)
    uid = str(interaction.user.id)
    econ = get_user_economy(gid, uid)
    if aposta <= 0 or aposta > econ['coins']:
        await interaction.response.send_message(embed=embed_err('Aposta Inválida', f'Aposta inválida. Saldo: **{econ["coins"]:,}**', interaction.user), ephemeral=True)
        return
    resultado = random.choice(['cara', 'coroa'])
    if resultado == escolha:
        econ['coins'] += aposta
        econ['total_earned'] = econ.get('total_earned', 0) + aposta
        e = embed_ok('Você Ganhou! 🪙', f'**Resultado:** {resultado.title()}\nVocê apostou **{escolha}** e ganhou **{aposta:,}** moedas!', interaction.user)
    else:
        econ['coins'] -= aposta
        e = embed_err('Você Perdeu!', f'**Resultado:** {resultado.title()}\nVocê apostou **{escolha}** e perdeu **{aposta:,}** moedas.', interaction.user)
    save_user_economy(gid, uid, econ)
    e.add_field(name='👛 Carteira', value=f'🪙 {econ["coins"]:,}', inline=False)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='dice', description='🎲 Jogue dados')
@app_commands.describe(aposta='Valor da aposta', numero='Número que você aposta (1-6)')
async def cmd_dice(interaction: discord.Interaction, aposta: int, numero: int):
    gid = str(interaction.guild.id)
    uid = str(interaction.user.id)
    econ = get_user_economy(gid, uid)
    if aposta <= 0 or aposta > econ['coins']:
        await interaction.response.send_message(embed=embed_err('Aposta Inválida', f'Saldo: **{econ["coins"]:,}**', interaction.user), ephemeral=True)
        return
    if numero < 1 or numero > 6:
        await interaction.response.send_message(embed=embed_err('Inválido', 'Número deve ser entre 1 e 6.', interaction.user), ephemeral=True)
        return
    resultado = random.randint(1, 6)
    dados = ['⚀', '⚁', '⚂', '⚃', '⚄', '⚅']
    if resultado == numero:
        ganho = aposta * 5
        econ['coins'] += ganho
        econ['total_earned'] = econ.get('total_earned', 0) + ganho
        e = embed_ok('Acertou! 🎲', f'{dados[resultado-1]} Saiu **{resultado}**! Você apostou em **{numero}** e ganhou **{ganho:,}** moedas!', interaction.user)
    else:
        econ['coins'] -= aposta
        e = embed_err('Errou! 🎲', f'{dados[resultado-1]} Saiu **{resultado}**. Você apostou em **{numero}** e perdeu **{aposta:,}** moedas.', interaction.user)
    save_user_economy(gid, uid, econ)
    e.add_field(name='👛 Carteira', value=f'🪙 {econ["coins"]:,}', inline=False)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='rng', description='🔢 Adivinhe o número (1-10)')
@app_commands.describe(aposta='Valor da aposta', numero='Número que você aposta (1-10)')
async def cmd_rng(interaction: discord.Interaction, aposta: int, numero: int):
    gid = str(interaction.guild.id)
    uid = str(interaction.user.id)
    econ = get_user_economy(gid, uid)
    if aposta <= 0 or aposta > econ['coins']:
        await interaction.response.send_message(embed=embed_err('Aposta Inválida', f'Saldo: **{econ["coins"]:,}**', interaction.user), ephemeral=True)
        return
    if numero < 1 or numero > 10:
        await interaction.response.send_message(embed=embed_err('Inválido', 'Número deve ser entre 1 e 10.', interaction.user), ephemeral=True)
        return
    resultado = random.randint(1, 10)
    if resultado == numero:
        ganho = aposta * 8
        econ['coins'] += ganho
        econ['total_earned'] = econ.get('total_earned', 0) + ganho
        e = embed_ok('Acertou! 🎯', f'O número era **{resultado}**! Você apostou em **{numero}** e ganhou **{ganho:,}** moedas!', interaction.user)
    else:
        econ['coins'] -= aposta
        e = embed_err('Errou!', f'O número era **{resultado}**. Você apostou em **{numero}** e perdeu **{aposta:,}** moedas.', interaction.user)
    save_user_economy(gid, uid, econ)
    e.add_field(name='👛 Carteira', value=f'🪙 {econ["coins"]:,}', inline=False)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='level', description='📊 Mostra seu nível atual')
@app_commands.describe(usuario='Usuário (opcional)')
async def cmd_level(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
    alvo = usuario or interaction.user
    gid = str(interaction.guild.id)
    uid = str(alvo.id)
    lv = get_user_level(gid, uid)
    xp_needed = xp_para_level(lv['level'])
    progress = lv['xp'] / xp_needed
    bars = 20
    filled = int(bars * progress)
    bar = '█' * filled + '░' * (bars - filled)
    percent = int(progress * 100)
    e = discord.Embed(title=f'📊 Nível de {alvo.name}', color=0x9B59B6, timestamp=datetime.now())
    e.set_thumbnail(url=alvo.display_avatar.url)
    e.add_field(name='🌟 Nível', value=f'**{lv["level"]}**', inline=True)
    e.add_field(name='✨ XP', value=f'**{lv["xp"]:,}** / **{xp_needed:,}**', inline=True)
    e.add_field(name='💬 Mensagens', value=f'**{lv.get("messages", 0):,}**', inline=True)
    e.add_field(name=f'📈 Progresso — {percent}%', value=f'`[{bar}]`', inline=False)
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='rank', description='🏅 Ranking de XP do servidor')
async def cmd_rank(interaction: discord.Interaction):
    gid = str(interaction.guild.id)
    levels = load_json('levels_data.json').get(gid, {})
    if not levels:
        await interaction.response.send_message(embed=embed_info('Sem Dados', 'Nenhum dado de nível ainda.', interaction.user))
        return
    ranking = sorted(levels.items(), key=lambda x: (x[1].get('level', 1), x[1].get('xp', 0)), reverse=True)[:10]
    e = discord.Embed(title='🏅 Ranking de XP', color=0x9B59B6, timestamp=datetime.now())
    medals = ['🥇', '🥈', '🥉'] + ['🏅'] * 7
    for i, (uid, data) in enumerate(ranking):
        e.add_field(name=f'{medals[i]} #{i+1} — <@{uid}>', value=f'Nível **{data.get("level", 1)}** | XP: **{data.get("xp", 0):,}**', inline=False)
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='tier', description='👑 Mostra seu tier econômico')
@app_commands.describe(usuario='Usuário (opcional)')
async def cmd_tier(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
    alvo = usuario or interaction.user
    gid = str(interaction.guild.id)
    uid = str(alvo.id)
    econ = get_user_economy(gid, uid)
    total = econ.get('total_earned', econ['coins'] + econ['bank'])
    tier = calcular_tier(total)
    tier_info = TIERS[tier]
    e = discord.Embed(title=f'👑 Tier de {alvo.name}', description=f'{tier_info["emoji"]} **{tier_info["nome"]}** (Tier {tier}/5)', color=0xF1C40F, timestamp=datetime.now())
    e.set_thumbnail(url=alvo.display_avatar.url)
    e.add_field(name='💰 Total Ganho', value=f'🪙 {total:,}', inline=True)
    if tier < 5:
        prox = TIERS[tier + 1]
        falta = prox['requisito'] - total
        e.add_field(name=f'⬆️ Próximo: {prox["emoji"]} {prox["nome"]}', value=f'Faltam 🪙 **{falta:,}**', inline=True)
    e.add_field(name='📊 Todos os Tiers', value='\n'.join(f'{TIERS[t]["emoji"]} Tier {t} — {TIERS[t]["nome"]} | 🪙 {TIERS[t]["requisito"]:,}' for t in range(1, 6)), inline=False)
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='give_coins', description='💰 Dá moedas a um usuário (Admin)')
@app_commands.describe(usuario='Usuário', quantidade='Quantidade')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_give_coins(interaction: discord.Interaction, usuario: discord.Member, quantidade: int):
    if quantidade <= 0:
        await interaction.response.send_message(embed=embed_err('Inválido', 'Quantidade deve ser maior que 0.', interaction.user), ephemeral=True)
        return
    gid = str(interaction.guild.id)
    uid = str(usuario.id)
    econ = get_user_economy(gid, uid)
    econ['coins'] += quantidade
    econ['total_earned'] = econ.get('total_earned', 0) + quantidade
    save_user_economy(gid, uid, econ)
    await interaction.response.send_message(embed=embed_ok('Moedas Adicionadas', f'**{quantidade:,}** moedas adicionadas a {usuario.mention}!\n**Nova carteira:** 🪙 {econ["coins"]:,}', interaction.user))


@bot.tree.command(name='remove_coins', description='💸 Remove moedas de um usuário (Admin)')
@app_commands.describe(usuario='Usuário', quantidade='Quantidade')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_remove_coins(interaction: discord.Interaction, usuario: discord.Member, quantidade: int):
    gid = str(interaction.guild.id)
    uid = str(usuario.id)
    econ = get_user_economy(gid, uid)
    if quantidade > econ['coins']:
        quantidade = econ['coins']
    econ['coins'] -= quantidade
    save_user_economy(gid, uid, econ)
    await interaction.response.send_message(embed=embed_ok('Moedas Removidas', f'**{quantidade:,}** moedas removidas de {usuario.mention}.\n**Nova carteira:** 🪙 {econ["coins"]:,}', interaction.user))

class ParticipateGiveawayView(View):
    def __init__(self, giveaway_id: str, guild_id: str):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        self.guild_id = guild_id

    @discord.ui.button(label='🎉 Participar', style=discord.ButtonStyle.green, custom_id='giveaway_join')
    async def participar(self, interaction: discord.Interaction, button: Button):
        gid = self.guild_id
        gw_id = self.giveaway_id
        uid = str(interaction.user.id)
        data = load_json('giveaways_data.json')
        gw = data.get(gid, {}).get(gw_id)
        if not gw:
            await interaction.response.send_message(embed=embed_err('Erro', 'Sorteio não encontrado.', interaction.user), ephemeral=True)
            return
        if gw.get('status') != 'ativo':
            await interaction.response.send_message(embed=embed_err('Encerrado', 'Este sorteio já acabou.', interaction.user), ephemeral=True)
            return
        if uid in gw.get('participantes', []):
            await interaction.response.send_message(embed=embed_warn('Já Participando', 'Você já está participando!', interaction.user), ephemeral=True)
            return
        if 'participantes' not in gw:
            gw['participantes'] = []
        gw['participantes'].append(uid)
        save_json('giveaways_data.json', data)
        count = len(gw['participantes'])
        await interaction.response.send_message(embed=embed_ok('Inscrito!', f'Você está participando do sorteio!\n**Total de participantes:** {count}', interaction.user), ephemeral=True)


@bot.tree.command(name='giveaway', description='🎉 Cria um sorteio')
@app_commands.describe(duracao='Duração em minutos', premio='Prêmio do sorteio', vencedores='Número de vencedores')
@app_commands.checks.has_permissions(manage_guild=True)
async def cmd_giveaway(interaction: discord.Interaction, duracao: int, premio: str, vencedores: int = 1):
    if duracao <= 0:
        await interaction.response.send_message(embed=embed_err('Inválido', 'Duração deve ser maior que 0.', interaction.user), ephemeral=True)
        return
    gid = str(interaction.guild.id)
    data = load_json('giveaways_data.json')
    if gid not in data:
        data[gid] = {}
    gw_id = str(len(data[gid]) + 1)
    expiry = datetime.now() + timedelta(minutes=duracao)
    data[gid][gw_id] = {
        'premio': premio, 'vencedores': vencedores, 'status': 'ativo',
        'criador': str(interaction.user.id), 'expiry': expiry.isoformat(),
        'channel_id': str(interaction.channel.id), 'participantes': [],
        'message_id': None
    }
    save_json('giveaways_data.json', data)
    e = discord.Embed(
        title='🎉 SORTEIO!',
        description=f'**Prêmio:** {premio}\n\nClique em **🎉 Participar** para entrar!',
        color=0xF1C40F, timestamp=expiry
    )
    e.add_field(name='⏰ Encerra em', value=f'<t:{int(expiry.timestamp())}:R>', inline=True)
    e.add_field(name='🏆 Vencedores', value=str(vencedores), inline=True)
    e.add_field(name='👤 Criado por', value=interaction.user.mention, inline=True)
    e.set_footer(text=f'Sorteio ID: {gw_id} | Participe clicando no botão!')
    view = ParticipateGiveawayView(gw_id, gid)
    await interaction.response.send_message(embed=e, view=view)
    msg = await interaction.original_response()
    data[gid][gw_id]['message_id'] = str(msg.id)
    save_json('giveaways_data.json', data)


@bot.tree.command(name='giveaway_end', description='🏁 Encerra um sorteio imediatamente')
@app_commands.describe(giveaway_id='ID do sorteio')
@app_commands.checks.has_permissions(manage_guild=True)
async def cmd_giveaway_end(interaction: discord.Interaction, giveaway_id: str):
    gid = str(interaction.guild.id)
    data = load_json('giveaways_data.json')
    gw = data.get(gid, {}).get(giveaway_id)
    if not gw:
        await interaction.response.send_message(embed=embed_err('Não Encontrado', f'Sorteio #{giveaway_id} não encontrado.', interaction.user), ephemeral=True)
        return
    if gw.get('status') != 'ativo':
        await interaction.response.send_message(embed=embed_err('Já Encerrado', 'Este sorteio já foi encerrado.', interaction.user), ephemeral=True)
        return
    participantes = gw.get('participantes', [])
    vencedores_ids = []
    if participantes:
        qtd = min(gw['vencedores'], len(participantes))
        vencedores_ids = random.sample(participantes, qtd)
    gw['status'] = 'encerrado'
    gw['vencedores_finais'] = vencedores_ids
    save_json('giveaways_data.json', data)
    if vencedores_ids:
        mencoes = ', '.join(f'<@{v}>' for v in vencedores_ids)
        e = embed_ok('Sorteio Encerrado!', f'**Prêmio:** {gw["premio"]}\n\n🏆 **Vencedor(es):** {mencoes}\n\n🎉 Parabéns!', interaction.user)
    else:
        e = embed_warn('Sorteio Encerrado', f'**Prêmio:** {gw["premio"]}\n\nNenhum participante.', interaction.user)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='poll', description='📊 Cria uma enquete')
@app_commands.describe(pergunta='Pergunta da enquete', opcoes='Opções separadas por vírgula (ex: Sim,Não,Talvez)', duracao='Duração em minutos (0 = sem limite)')
@app_commands.checks.has_permissions(manage_messages=True)
async def cmd_poll(interaction: discord.Interaction, pergunta: str, opcoes: str, duracao: int = 0):
    opcoes_lista = [o.strip() for o in opcoes.split(',') if o.strip()]
    if len(opcoes_lista) < 2:
        await interaction.response.send_message(embed=embed_err('Inválido', 'Mínimo de 2 opções, separadas por vírgula.', interaction.user), ephemeral=True)
        return
    if len(opcoes_lista) > 9:
        await interaction.response.send_message(embed=embed_err('Inválido', 'Máximo de 9 opções.', interaction.user), ephemeral=True)
        return
    emojis_num = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']
    gid = str(interaction.guild.id)
    data = load_json('polls_data.json')
    if gid not in data:
        data[gid] = {}
    poll_id = str(len(data[gid]) + 1)
    expiry = (datetime.now() + timedelta(minutes=duracao)).isoformat() if duracao > 0 else None
    data[gid][poll_id] = {
        'pergunta': pergunta, 'opcoes': opcoes_lista, 'votos': {str(i): [] for i in range(len(opcoes_lista))},
        'criador': str(interaction.user.id), 'status': 'ativo',
        'channel_id': str(interaction.channel.id), 'expiry': expiry, 'message_id': None
    }
    save_json('polls_data.json', data)
    desc = '\n'.join(f'{emojis_num[i]} {opt}' for i, opt in enumerate(opcoes_lista))
    e = discord.Embed(title=f'📊 {pergunta}', description=desc, color=0x3498DB, timestamp=datetime.now())
    if duracao > 0:
        exp = datetime.now() + timedelta(minutes=duracao)
        e.add_field(name='⏰ Encerra em', value=f'<t:{int(exp.timestamp())}:R>', inline=True)
    e.add_field(name='👤 Criada por', value=interaction.user.mention, inline=True)
    e.set_footer(text=f'Enquete ID: {poll_id} | Use as reações para votar')
    await interaction.response.send_message(embed=e)
    msg = await interaction.original_response()
    for i in range(len(opcoes_lista)):
        await msg.add_reaction(emojis_num[i])
    data[gid][poll_id]['message_id'] = str(msg.id)
    save_json('polls_data.json', data)


@bot.tree.command(name='report', description='🚨 Reporta um problema ou usuário')
@app_commands.describe(usuario='Usuário a reportar', motivo='Motivo do report')
async def cmd_report(interaction: discord.Interaction, usuario: discord.Member, motivo: str):
    gid = str(interaction.guild.id)
    cfg = load_json('config_data.json').get(gid, {})
    ch_id = cfg.get('reports_channel_id')
    if not ch_id:
        await interaction.response.send_message(embed=embed_err('Não Configurado', 'Canal de reports não configurado. Use `/setup_reports`.', interaction.user), ephemeral=True)
        return
    ch = interaction.guild.get_channel(int(ch_id))
    if not ch:
        await interaction.response.send_message(embed=embed_err('Canal Inválido', 'Canal de reports não encontrado.', interaction.user), ephemeral=True)
        return
    data = load_json('reports_data.json')
    if gid not in data:
        data[gid] = {}
    rep_id = str(len(data[gid]) + 1)
    e = discord.Embed(title=f'🚨 Report #{rep_id}', color=0xE74C3C, timestamp=datetime.now())
    e.set_author(name=f'Reportado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    e.add_field(name='👤 Reportado', value=f'{usuario.mention}\n`{usuario.id}`', inline=True)
    e.add_field(name='📝 Motivo', value=motivo, inline=False)
    e.set_thumbnail(url=usuario.display_avatar.url)
    e.set_footer(text=f'Report de {interaction.user.name} ({interaction.user.id})')
    await ch.send(embed=e)
    data[gid][rep_id] = {'usuario_id': str(usuario.id), 'reporter_id': str(interaction.user.id), 'motivo': motivo, 'timestamp': datetime.now().isoformat()}
    save_json('reports_data.json', data)
    await interaction.response.send_message(embed=embed_ok('Report Enviado', 'Seu report foi enviado para a equipe de moderação.', interaction.user), ephemeral=True)


@bot.tree.command(name='setup_reports', description='⚙️ Configura o canal de reports')
@app_commands.describe(canal='Canal de reports')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_setup_reports(interaction: discord.Interaction, canal: discord.TextChannel):
    gid = str(interaction.guild.id)
    cfg = load_json('config_data.json')
    if gid not in cfg:
        cfg[gid] = {}
    cfg[gid]['reports_channel_id'] = str(canal.id)
    save_json('config_data.json', cfg)
    await interaction.response.send_message(embed=embed_ok('Canal Configurado', f'Canal de reports: {canal.mention}', interaction.user))


@bot.tree.command(name='tag', description='🏷️ Cria uma tag')
@app_commands.describe(nome='Nome da tag', conteudo='Conteúdo da tag')
@app_commands.checks.has_permissions(manage_messages=True)
async def cmd_tag_create(interaction: discord.Interaction, nome: str, conteudo: str):
    gid = str(interaction.guild.id)
    data = load_json('tags_data.json')
    if gid not in data:
        data[gid] = {}
    nome_lower = nome.lower()
    if nome_lower in data[gid]:
        await interaction.response.send_message(embed=embed_err('Já Existe', f'Tag `{nome}` já existe. Use `/tag_edit` para editar.', interaction.user), ephemeral=True)
        return
    data[gid][nome_lower] = {'nome': nome, 'conteudo': conteudo, 'criador': str(interaction.user.id), 'timestamp': datetime.now().isoformat(), 'usos': 0}
    save_json('tags_data.json', data)
    await interaction.response.send_message(embed=embed_ok('Tag Criada', f'Tag `{nome}` criada com sucesso!', interaction.user))


@bot.tree.command(name='tag_get', description='📖 Mostra o conteúdo de uma tag')
@app_commands.describe(nome='Nome da tag')
async def cmd_tag_get(interaction: discord.Interaction, nome: str):
    gid = str(interaction.guild.id)
    data = load_json('tags_data.json')
    tag = data.get(gid, {}).get(nome.lower())
    if not tag:
        await interaction.response.send_message(embed=embed_err('Não Encontrada', f'Tag `{nome}` não existe.', interaction.user), ephemeral=True)
        return
    tag['usos'] = tag.get('usos', 0) + 1
    save_json('tags_data.json', data)
    e = discord.Embed(title=f'🏷️ {tag["nome"]}', description=tag['conteudo'], color=0x3498DB, timestamp=datetime.now())
    e.set_footer(text=f'Usos: {tag["usos"]}')
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='tag_delete', description='🗑️ Deleta uma tag')
@app_commands.describe(nome='Nome da tag')
@app_commands.checks.has_permissions(manage_messages=True)
async def cmd_tag_delete(interaction: discord.Interaction, nome: str):
    gid = str(interaction.guild.id)
    data = load_json('tags_data.json')
    if nome.lower() not in data.get(gid, {}):
        await interaction.response.send_message(embed=embed_err('Não Encontrada', f'Tag `{nome}` não existe.', interaction.user), ephemeral=True)
        return
    del data[gid][nome.lower()]
    save_json('tags_data.json', data)
    await interaction.response.send_message(embed=embed_ok('Tag Deletada', f'Tag `{nome}` deletada.', interaction.user))


@bot.tree.command(name='tag_list', description='📋 Lista todas as tags do servidor')
async def cmd_tag_list(interaction: discord.Interaction):
    gid = str(interaction.guild.id)
    data = load_json('tags_data.json').get(gid, {})
    if not data:
        await interaction.response.send_message(embed=embed_info('Sem Tags', 'Não há tags criadas.', interaction.user))
        return
    e = discord.Embed(title='🏷️ Tags do Servidor', description=f'Total: **{len(data)}** tag(s)', color=0x3498DB, timestamp=datetime.now())
    tags_txt = ', '.join(f'`{nome}`' for nome in list(data.keys())[:50])
    e.add_field(name='📋 Tags', value=tags_txt, inline=False)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='reminder', description='⏰ Cria um lembrete')
@app_commands.describe(minutos='Em quantos minutos lembrar', mensagem='Mensagem do lembrete')
async def cmd_reminder(interaction: discord.Interaction, minutos: int, mensagem: str):
    if minutos <= 0 or minutos > 10080:
        await interaction.response.send_message(embed=embed_err('Inválido', 'Minutos deve ser entre 1 e 10080 (7 dias).', interaction.user), ephemeral=True)
        return
    gid = str(interaction.guild.id)
    data = load_json('reminders_data.json')
    if gid not in data:
        data[gid] = {}
    rem_id = str(len(data[gid]) + 1)
    expiry = datetime.now() + timedelta(minutes=minutos)
    data[gid][rem_id] = {
        'user_id': str(interaction.user.id), 'channel_id': str(interaction.channel.id),
        'mensagem': mensagem, 'expiry': expiry.isoformat(), 'status': 'ativo'
    }
    save_json('reminders_data.json', data)
    e = embed_ok('Lembrete Criado!', f'Vou te lembrar em **{minutos} minuto(s)**!\n**Mensagem:** {mensagem}', interaction.user)
    e.add_field(name='⏰ Horário', value=f'<t:{int(expiry.timestamp())}:f>', inline=True)
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(name='invites', description='📨 Mostra quem convidou um membro (ou seus próprios convites)')
@app_commands.describe(usuario='Usuário para verificar (padrão: você mesmo)')
async def cmd_invites(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
    alvo = usuario or interaction.user
    await interaction.response.defer()
    try:
        guild_invites = await interaction.guild.invites()
    except discord.Forbidden:
        await interaction.followup.send(embed=embed_err('Sem Permissão', 'O bot precisa da permissão **Manage Guild** para ver convites.', interaction.user), ephemeral=True)
        return
    # Convites criados pelo alvo
    meus_convites = [inv for inv in guild_invites if inv.inviter and inv.inviter.id == alvo.id]
    total_usos = sum(inv.uses or 0 for inv in meus_convites)
    e = discord.Embed(
        title=f'📨 Convites de {alvo.display_name}',
        color=0x5865F2, timestamp=datetime.now()
    )
    e.set_thumbnail(url=alvo.display_avatar.url)
    e.add_field(name='🔗 Total de Links', value=f'`{len(meus_convites)}`', inline=True)
    e.add_field(name='✅ Total de Usos', value=f'`{total_usos}`', inline=True)
    if meus_convites:
        detalhes = []
        for inv in sorted(meus_convites, key=lambda x: x.uses or 0, reverse=True)[:5]:
            exp = f' (expira <t:{int(inv.expires_at.timestamp())}:R>)' if inv.expires_at else ''
            detalhes.append(f'`{inv.code}` — {inv.uses or 0} uso(s){exp}')
        e.add_field(name='🔑 Links (top 5)', value='\n'.join(detalhes), inline=False)
    # Verificar quem convidou o alvo (por dados salvos)
    users_data = load_json('users_data.json')
    gid = str(interaction.guild.id)
    info_alvo = users_data.get(gid, {}).get(str(alvo.id), {})
    invitado_por = info_alvo.get('invited_by')
    if invitado_por:
        e.add_field(name='👤 Foi convidado por', value=f'<@{invitado_por}>', inline=False)
    else:
        e.add_field(name='👤 Foi convidado por', value='Desconhecido (entrou antes do rastreamento)', inline=False)
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.followup.send(embed=e)


@bot.tree.command(name='votacao_cargo', description='🗳️ Cria uma votação com botões que dão/removem cargos ao clicar')
@app_commands.describe(
    titulo='Título da votação',
    descricao='Descrição da votação',
    cargo1='Cargo da opção 1',
    label1='Nome do botão 1',
    cargo2='Cargo da opção 2 (opcional)',
    label2='Nome do botão 2 (opcional)',
    cargo3='Cargo da opção 3 (opcional)',
    label3='Nome do botão 3 (opcional)'
)
@app_commands.checks.has_permissions(manage_roles=True)
async def cmd_votacao_cargo(interaction: discord.Interaction, titulo: str, descricao: str, cargo1: discord.Role, label1: str, cargo2: Optional[discord.Role] = None, label2: Optional[discord.Role] = None, cargo3: Optional[discord.Role] = None, label3: Optional[discord.Role] = None):
    opcoes = [(cargo1, label1)]
    if cargo2 and label2:
        opcoes.append((cargo2, str(label2)))
    if cargo3 and label3:
        opcoes.append((cargo3, str(label3)))

    class VotacaoCargoView(View):
        def __init__(self):
            super().__init__(timeout=None)
            cores = [discord.ButtonStyle.blurple, discord.ButtonStyle.green, discord.ButtonStyle.red]
            emojis = ['🔵', '🟢', '🔴']
            for i, (cargo, label) in enumerate(opcoes):
                btn = Button(
                    label=f'{emojis[i]} {label}',
                    style=cores[i % len(cores)],
                    custom_id=f'votcargo_{cargo.id}'
                )
                async def callback(inter: discord.Interaction, c=cargo, lbl=label):
                    if c in inter.user.roles:
                        await inter.user.remove_roles(c, reason='Votação de cargo')
                        await inter.response.send_message(
                            embed=embed_info('Cargo Removido', f'O cargo **{c.name}** foi removido de você.', inter.user),
                            ephemeral=True
                        )
                    else:
                        await inter.user.add_roles(c, reason='Votação de cargo')
                        await inter.response.send_message(
                            embed=embed_ok('Cargo Adicionado', f'Você recebeu o cargo **{c.name}**! Clique novamente para remover.', inter.user),
                            ephemeral=True
                        )
                btn.callback = callback
                self.add_item(btn)

    e = discord.Embed(
        title=f'🗳️ {titulo}',
        description=f'{descricao}\n\n💡 *Clique para receber/remover o cargo correspondente.*',
        color=0x9B59B6, timestamp=datetime.now()
    )
    for cargo, label in opcoes:
        e.add_field(name=label, value=cargo.mention, inline=True)
    e.set_footer(text=f'Criado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e, view=VotacaoCargoView())


@bot.tree.command(name='ping', description='🏓 Mostra a latência do bot')
async def cmd_ping(interaction: discord.Interaction):
    lat = round(bot.latency * 1000)
    if lat < 100:
        emoji, cor, status = '🟢', 0x2ECC71, 'Excelente'
    elif lat < 200:
        emoji, cor, status = '🟡', 0xF1C40F, 'Bom'
    else:
        emoji, cor, status = '🔴', 0xE74C3C, 'Alto'
    e = discord.Embed(title=f'{emoji} Pong!', description=f'Latência: **{lat}ms** — {status}', color=cor, timestamp=datetime.now())
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='botinfo', description='🤖 Informações completas do bot')
async def cmd_botinfo(interaction: discord.Interaction):
    total_users = sum(g.member_count for g in bot.guilds)
    total_channels = sum(len(g.channels) for g in bot.guilds)
    uptime = formatar_uptime(bot.start_time)
    e = discord.Embed(title='🤖 Informações do Bot', description='Bot Discord Premium — Sistema Completo', color=0x3498DB, timestamp=datetime.now())
    e.set_thumbnail(url=bot.user.display_avatar.url)
    e.add_field(name='📋 Básico', value=f'**Nome:** {bot.user.name}\n**ID:** `{bot.user.id}`\n**Versão:** `{bot.versao}`', inline=True)
    e.add_field(name='📊 Estatísticas', value=f'**Servidores:** {len(bot.guilds)}\n**Usuários:** {total_users:,}\n**Canais:** {total_channels:,}', inline=True)
    e.add_field(name='⚙️ Sistema', value=f'**Comandos:** {len(bot.tree.get_commands())}\n**Latência:** {round(bot.latency * 1000)}ms\n**Uptime:** {uptime}', inline=True)
    e.add_field(name='💻 Tecnologia', value=f'**Python:** {platform.python_version()}\n**Discord.py:** {discord.__version__}\n**SO:** {platform.system()}', inline=False)
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='serverinfo', description='📊 Informações do servidor')
async def cmd_serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    e = discord.Embed(title=f'📊 {guild.name}', color=0x3498DB, timestamp=datetime.now())
    if guild.icon:
        e.set_thumbnail(url=guild.icon.url)
    e.add_field(name='📋 Básico', value=f'**ID:** `{guild.id}`\n**Dono:** {guild.owner.mention}\n**Criado:** {guild.created_at.strftime("%d/%m/%Y")}', inline=False)
    text_ch = len([c for c in guild.channels if isinstance(c, discord.TextChannel)])
    voice_ch = len([c for c in guild.channels if isinstance(c, discord.VoiceChannel)])
    bots = len([m for m in guild.members if m.bot])
    humans = guild.member_count - bots
    e.add_field(name='👥 Membros', value=f'**Total:** {guild.member_count:,}\n**Humanos:** {humans:,}\n**Bots:** {bots}', inline=True)
    e.add_field(name='💬 Canais', value=f'**Total:** {len(guild.channels)}\n**Texto:** {text_ch}\n**Voz:** {voice_ch}', inline=True)
    e.add_field(name='🎭 Outros', value=f'**Cargos:** {len(guild.roles)}\n**Emojis:** {len(guild.emojis)}\n**Boosts:** {guild.premium_subscription_count}', inline=True)
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='userinfo', description='👤 Informações de um usuário')
@app_commands.describe(usuario='Usuário (opcional)')
async def cmd_userinfo(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
    alvo = usuario or interaction.user
    e = discord.Embed(title=f'👤 {alvo.name}', color=alvo.color if alvo.color != discord.Color.default() else discord.Color.blue(), timestamp=datetime.now())
    e.set_thumbnail(url=alvo.display_avatar.url)
    age_a = (datetime.now() - alvo.created_at.replace(tzinfo=None)).days
    e.add_field(name='📋 Básico', value=f'**Nome:** {alvo.name}\n**ID:** `{alvo.id}`\n**Bot:** {"Sim" if alvo.bot else "Não"}', inline=True)
    e.add_field(name='📅 Conta', value=f'**Criada:** {alvo.created_at.strftime("%d/%m/%Y")}\n({age_a} dias)', inline=True)
    if alvo.joined_at:
        age_s = (datetime.now() - alvo.joined_at.replace(tzinfo=None)).days
        e.add_field(name='📥 Servidor', value=f'**Entrou:** {alvo.joined_at.strftime("%d/%m/%Y")}\n({age_s} dias)', inline=True)
    if len(alvo.roles) > 1:
        roles = [r.mention for r in alvo.roles[1:]]
        roles_txt = ', '.join(roles[:8]) + (f' +{len(roles)-8}' if len(roles) > 8 else '')
        e.add_field(name=f'🎭 Cargos ({len(roles)})', value=roles_txt, inline=False)
        e.add_field(name='👑 Top Cargo', value=alvo.top_role.mention, inline=True)
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='avatar', description='🖼️ Mostra o avatar de um usuário')
@app_commands.describe(usuario='Usuário (opcional)')
async def cmd_avatar(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
    alvo = usuario or interaction.user
    e = discord.Embed(title=f'🖼️ Avatar de {alvo.name}', color=0x3498DB, timestamp=datetime.now())
    e.set_image(url=alvo.display_avatar.url)
    e.add_field(name='🔗 Link', value=f'[PNG]({alvo.display_avatar.replace(format="png").url}) | [JPG]({alvo.display_avatar.replace(format="jpg").url}) | [WEBP]({alvo.display_avatar.replace(format="webp").url})', inline=False)
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='ajuda', description='📚 Menu de ajuda completo')
async def cmd_ajuda(interaction: discord.Interaction):
    e = discord.Embed(title='📚 Menu de Ajuda', description='Todos os sistemas disponíveis no bot', color=0x9B59B6, timestamp=datetime.now())
    e.add_field(
        name='🔒 Verificação',
        value='`/verify` `/verify_code` `/check_user`\n`/whitelist` `/remove_whitelist`',
        inline=True
    )
    e.add_field(
        name='⚙️ Configuração',
        value='`/setup_verification` `/set_verified_role`\n`/set_log_channel` `/set_admin_role` `/set_mod_role`',
        inline=True
    )
    e.add_field(
        name='⚔️ League',
        value='`/league` `/joinleague` `/kickleague`\n`/leaguelist` `/league_info` `/league_members` `/endleague`\n`/setup_league_channel`',
        inline=True
    )
    e.add_field(
        name='🛡️ Moderação',
        value='`/warn` `/warnings` `/clearwarns` `/removewarn`\n`/ban` `/tempban` `/unban` `/kick` `/mute` `/unmute`\n`/case` `/cases` `/nick` `/addrole` `/removerole`\n`/purge` `/slowmode` `/lock` `/unlock` `/lockdown` `/unlockdown`',
        inline=True
    )
    e.add_field(
        name='🎫 Tickets',
        value='`/setup_tickets`',
        inline=True
    )
    e.add_field(
        name='📢 Comunicados',
        value='`/announce` `/embed`',
        inline=True
    )
    e.add_field(
        name='💰 Economia',
        value='`/balance` `/daily` `/work` `/deposit` `/withdraw`\n`/transfer` `/leaderboard` `/give_coins` `/remove_coins`',
        inline=True
    )
    e.add_field(
        name='🎲 Jogos',
        value='`/slots` `/coinflip` `/dice` `/rng`',
        inline=True
    )
    e.add_field(
        name='📊 Níveis',
        value='`/level` `/rank` `/tier`',
        inline=True
    )
    e.add_field(
        name='🎉 Eventos',
        value='`/giveaway` `/giveaway_end` `/poll`\n`/event` `/event_list` `/reminder`',
        inline=True
    )
    e.add_field(
        name='📋 Comunidade',
        value='`/report` `/tag` `/tag_get` `/tag_delete` `/tag_list`',
        inline=True
    )
    e.add_field(
        name='ℹ️ Informações',
        value='`/ping` `/botinfo` `/serverinfo` `/userinfo` `/avatar`',
        inline=True
    )
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='help', description='❓ Ajuda sobre um comando específico')
@app_commands.describe(comando='Nome do comando')
async def cmd_help(interaction: discord.Interaction, comando: str):
    cmd_info = {
        'verify': ('🔒 Verificação', 'Inicia o processo de verificação. Gera um código único de 6 dígitos.\n**Uso:** `/verify`'),
        'verify_code': ('✅ Verificação', 'Confirma o código e vincula seu username do Roblox.\n**Uso:** `/verify_code [codigo] [roblox_username]`'),
        'league': ('⚔️ League', 'Cria uma nova league com tópico automático.\n**Uso:** `/league [modo] [servidor] [link_privado]`\n**Modos:** 2v2, 3v3, 4v4'),
        'warn': ('⚠️ Moderação', 'Aplica um aviso a um membro.\n**Uso:** `/warn [usuario] [motivo]`\n**Permissão:** Moderate Members'),
        'ban': ('🔨 Moderação', 'Bane permanentemente um membro.\n**Uso:** `/ban [usuario] [motivo] [deletar_msgs]`\n**Permissão:** Ban Members'),
        'tempban': ('⏰ Moderação', 'Bane temporariamente. Formatos: `1d`, `12h`, `30m`\n**Uso:** `/tempban [usuario] [duracao] [motivo]`'),
        'mute': ('🔇 Moderação', 'Silencia um membro por tempo determinado.\n**Uso:** `/mute [usuario] [duracao] [motivo]`'),
        'giveaway': ('🎉 Sorteio', 'Cria um sorteio com botão interativo.\n**Uso:** `/giveaway [duracao] [premio] [vencedores]`'),
        'announce': ('📢 Anúncio', 'Envia anúncio em embed em qualquer canal.\n**Uso:** `/announce [canal] [titulo] [mensagem] [cor] [mencionar]`'),
        'daily': ('🎁 Economia', 'Resgate bônus diário. Streak aumenta o bônus!\n**Uso:** `/daily` | **Cooldown:** 24h'),
        'work': ('💼 Economia', 'Trabalhe para ganhar moedas.\n**Uso:** `/work` | **Cooldown:** 1h'),
        'slots': ('🎰 Jogos', 'Caça-níqueis. Par = 0.5x | 3 iguais = 3x | 💎 = 5x | 7️⃣ = 10x\n**Uso:** `/slots [aposta]`'),
        'setup_tickets': ('🎫 Tickets', 'Configura o sistema de tickets com painel interativo.\n**Uso:** `/setup_tickets [canal] [categoria] [cargo_mod]`'),
    }
    cmd_lower = comando.lower().lstrip('/')
    info = cmd_info.get(cmd_lower)
    if not info:
        await interaction.response.send_message(embed=embed_err('Não Encontrado', f'Nenhuma ajuda para `{comando}`. Use `/ajuda` para ver todos os comandos.', interaction.user), ephemeral=True)
        return
    e = discord.Embed(title=info[0], description=info[1], color=0x9B59B6, timestamp=datetime.now())
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='set_welcome_channel', description='⚙️ Define o canal de boas-vindas')
@app_commands.describe(canal='Canal de boas-vindas')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_set_welcome_channel(interaction: discord.Interaction, canal: discord.TextChannel):
    gid = str(interaction.guild.id)
    cfg = load_json('config_data.json')
    if gid not in cfg:
        cfg[gid] = {}
    cfg[gid]['welcome_channel_id'] = str(canal.id)
    save_json('config_data.json', cfg)
    await interaction.response.send_message(embed=embed_ok('Canal de Boas-vindas', f'Boas-vindas serão enviadas em {canal.mention}!', interaction.user))


@bot.tree.command(name='resetlevel', description='🔄 Reseta o nível de um usuário (Admin)')
@app_commands.describe(usuario='Usuário a resetar')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_resetlevel(interaction: discord.Interaction, usuario: discord.Member):
    gid = str(interaction.guild.id)
    uid = str(usuario.id)
    data = load_json('levels_data.json')
    if gid in data and uid in data[gid]:
        data[gid][uid] = {'level': 1, 'xp': 0, 'messages': 0}
        save_json('levels_data.json', data)
    await interaction.response.send_message(embed=embed_ok('Nível Resetado', f'O nível de {usuario.mention} foi resetado para 1.', interaction.user))


@bot.tree.command(name='setlevel', description='⚙️ Define o nível de um usuário (Admin)')
@app_commands.describe(usuario='Usuário', nivel='Nível a definir')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_setlevel(interaction: discord.Interaction, usuario: discord.Member, nivel: int):
    if nivel < 1 or nivel > 1000:
        await interaction.response.send_message(embed=embed_err('Inválido', 'Nível deve ser entre 1 e 1000.', interaction.user), ephemeral=True)
        return
    gid = str(interaction.guild.id)
    uid = str(usuario.id)
    lv = get_user_level(gid, uid)
    lv['level'] = nivel
    lv['xp'] = 0
    save_user_level(gid, uid, lv)
    await interaction.response.send_message(embed=embed_ok('Nível Definido', f'O nível de {usuario.mention} foi definido para **{nivel}**.', interaction.user))


@bot.tree.command(name='setup_config', description='⚙️ Exibe a configuração atual do servidor')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_setup_config(interaction: discord.Interaction):
    gid = str(interaction.guild.id)
    cfg = load_json('config_data.json').get(gid, {})
    e = discord.Embed(title='⚙️ Configuração do Servidor', color=0x3498DB, timestamp=datetime.now())
    campos = [
        ('verification_channel_id', '🔒 Canal de Verificação'),
        ('log_channel_id', '📋 Canal de Logs'),
        ('verified_role_id', '✅ Cargo Verificado'),
        ('mod_role_id', '🛡️ Cargo Moderador'),
        ('admin_role_id', '👑 Cargo Admin League'),
        ('suggestions_channel_id', '💡 Canal de Sugestões'),
        ('reports_channel_id', '🚨 Canal de Reports'),
        ('appeals_channel_id', '📝 Canal de Apelos'),
        ('welcome_channel_id', '👋 Canal de Boas-vindas'),
        ('goodbye_channel_id', '👋 Canal de Despedidas'),
    ]
    for key, nome in campos:
        val = cfg.get(key)
        if val:
            obj = interaction.guild.get_channel(int(val)) or interaction.guild.get_role(int(val))
            txt = obj.mention if obj else f'`{val}` (não encontrado)'
        else:
            txt = '❌ Não configurado'
        e.add_field(name=nome, value=txt, inline=True)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='ban_list', description='📋 Lista usuários banidos (Mod)')
@app_commands.checks.has_permissions(ban_members=True)
async def cmd_ban_list(interaction: discord.Interaction):
    await interaction.response.defer()
    bans = [entry async for entry in interaction.guild.bans(limit=20)]
    if not bans:
        await interaction.followup.send(embed=embed_info('Sem Bans', 'Nenhum usuário banido.', interaction.user))
        return
    e = discord.Embed(title='🔨 Usuários Banidos', description=f'{len(bans)} banimento(s) (mostrando 20)', color=0xE74C3C, timestamp=datetime.now())
    for ban in bans[:15]:
        e.add_field(
            name=f'{ban.user.name} (`{ban.user.id}`)',
            value=f'**Motivo:** {ban.reason or "Sem motivo"}',
            inline=False
        )
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.followup.send(embed=e)


@bot.tree.command(name='mute_list', description='📋 Lista usuários silenciados (Mod)')
@app_commands.checks.has_permissions(moderate_members=True)
async def cmd_mute_list(interaction: discord.Interaction):
    gid = str(interaction.guild.id)
    mute_data = load_json('mute_data.json').get(gid, {})
    if not mute_data:
        await interaction.response.send_message(embed=embed_info('Sem Mutes', 'Nenhum usuário silenciado.', interaction.user))
        return
    e = discord.Embed(title='🔇 Usuários Silenciados', description=f'{len(mute_data)} silenciamento(s)', color=0xF39C12, timestamp=datetime.now())
    for uid, info in list(mute_data.items())[:10]:
        expiry = datetime.fromisoformat(info['expiry'])
        e.add_field(
            name=f'<@{uid}>',
            value=f'**Motivo:** {info.get("motivo", "?")}\n**Expira:** <t:{int(expiry.timestamp())}:R>\n**Mod:** <@{info.get("mod", "?")}>',
            inline=True
        )
    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='reaction_role_setup', description='🎭 Configura reaction roles em uma mensagem')
@app_commands.describe(
    mensagem_id='ID da mensagem',
    emoji='Emoji para reagir',
    cargo='Cargo a ser dado',
    canal='Canal da mensagem'
)
@app_commands.checks.has_permissions(administrator=True)
async def cmd_reaction_role_setup(interaction: discord.Interaction, mensagem_id: str, emoji: str, cargo: discord.Role, canal: Optional[discord.TextChannel] = None):
    """
    Configura um sistema de reaction role em uma mensagem existente.
    Quando um membro reagir com o emoji especificado, receberá o cargo.
    """
    ch = canal or interaction.channel
    try:
        msg = await ch.fetch_message(int(mensagem_id))
    except Exception:
        await interaction.response.send_message(
            embed=embed_err('Não Encontrado', f'Mensagem `{mensagem_id}` não encontrada em {ch.mention}.', interaction.user),
            ephemeral=True
        )
        return
    gid = str(interaction.guild.id)
    data = load_json('config_data.json')
    if gid not in data:
        data[gid] = {}
    if 'reaction_roles' not in data[gid]:
        data[gid]['reaction_roles'] = {}
    key = f'{ch.id}_{mensagem_id}'
    if key not in data[gid]['reaction_roles']:
        data[gid]['reaction_roles'][key] = {}
    data[gid]['reaction_roles'][key][emoji] = str(cargo.id)
    save_json('config_data.json', data)
    try:
        await msg.add_reaction(emoji)
    except Exception as ex:
        await interaction.response.send_message(
            embed=embed_err('Emoji Inválido', f'Não foi possível adicionar a reação: {ex}', interaction.user),
            ephemeral=True
        )
        return
    e = embed_ok(
        'Reaction Role Configurado',
        f'Emoji: {emoji}\nCargo: {cargo.mention}\nMensagem: [#{ch.name}]({msg.jump_url})',
        interaction.user
    )
    await interaction.response.send_message(embed=e)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """Processa adição de reações para reaction roles."""
    if payload.user_id == bot.user.id:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    gid = str(guild.id)
    data = load_json('config_data.json')
    rr = data.get(gid, {}).get('reaction_roles', {})
    key = f'{payload.channel_id}_{payload.message_id}'
    if key not in rr:
        return
    emoji_str = str(payload.emoji)
    role_id = rr[key].get(emoji_str)
    if not role_id:
        return
    role = guild.get_role(int(role_id))
    member = guild.get_member(payload.user_id)
    if role and member:
        try:
            await member.add_roles(role, reason='Reaction Role')
        except Exception as ex:
            logger.error(f'Erro reaction role add: {ex}')


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    """Processa remoção de reações para reaction roles."""
    if payload.user_id == bot.user.id:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    gid = str(guild.id)
    data = load_json('config_data.json')
    rr = data.get(gid, {}).get('reaction_roles', {})
    key = f'{payload.channel_id}_{payload.message_id}'
    if key not in rr:
        return
    emoji_str = str(payload.emoji)
    role_id = rr[key].get(emoji_str)
    if not role_id:
        return
    role = guild.get_role(int(role_id))
    member = guild.get_member(payload.user_id)
    if role and member:
        try:
            await member.remove_roles(role, reason='Reaction Role removido')
        except Exception as ex:
            logger.error(f'Erro reaction role remove: {ex}')


@bot.tree.command(name='reaction_role_remove', description='🗑️ Remove um reaction role')
@app_commands.describe(mensagem_id='ID da mensagem', emoji='Emoji do reaction role a remover')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_reaction_role_remove(interaction: discord.Interaction, mensagem_id: str, emoji: str):
    """Remove um reaction role específico de uma mensagem."""
    gid = str(interaction.guild.id)
    data = load_json('config_data.json')
    rr = data.get(gid, {}).get('reaction_roles', {})
    key = None
    for k in rr:
        if mensagem_id in k:
            key = k
            break
    if not key or emoji not in rr.get(key, {}):
        await interaction.response.send_message(
            embed=embed_err('Não Encontrado', f'Reaction role com emoji `{emoji}` na mensagem `{mensagem_id}` não encontrado.', interaction.user),
            ephemeral=True
        )
        return
    del rr[key][emoji]
    if not rr[key]:
        del rr[key]
    save_json('config_data.json', data)
    await interaction.response.send_message(
        embed=embed_ok('Reaction Role Removido', f'Reaction role `{emoji}` removido da mensagem `{mensagem_id}`.', interaction.user)
    )


@bot.tree.command(name='autorole', description='⚙️ Define cargo automático para novos membros')
@app_commands.describe(cargo='Cargo a ser dado automaticamente', remover='Remove o autorole em vez de definir')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_autorole(interaction: discord.Interaction, cargo: Optional[discord.Role] = None, remover: bool = False):
    """
    Configura um cargo para ser dado automaticamente quando um novo membro entra.
    Use sem cargo e com remover=True para desativar.
    """
    gid = str(interaction.guild.id)
    data = load_json('config_data.json')
    if gid not in data:
        data[gid] = {}
    if remover:
        data[gid].pop('autorole_id', None)
        save_json('config_data.json', data)
        await interaction.response.send_message(embed=embed_ok('Autorole Removido', 'Cargo automático desativado.', interaction.user))
        return
    if not cargo:
        await interaction.response.send_message(embed=embed_err('Inválido', 'Forneça um cargo ou use `remover=True`.', interaction.user), ephemeral=True)
        return
    data[gid]['autorole_id'] = str(cargo.id)
    save_json('config_data.json', data)
    await interaction.response.send_message(embed=embed_ok('Autorole Configurado', f'{cargo.mention} será dado automaticamente a novos membros!', interaction.user))


@bot.tree.command(name='antispam_setup', description='⚙️ Configura o anti-spam (funcional no on_message)')
@app_commands.describe(
    ativo='Ativar (True) ou Desativar (False)',
    max_mensagens='Máximo de mensagens antes de agir (padrão: 5)',
    janela_segundos='Janela de tempo em segundos para contar msgs (padrão: 5)',
    acao='Ação ao detectar spam',
    cargo_imune='Cargo imune ao anti-spam'
)
@app_commands.choices(acao=[
    app_commands.Choice(name='Deletar mensagens + aviso', value='delete'),
    app_commands.Choice(name='Deletar + Mutar 5 min', value='mute'),
    app_commands.Choice(name='Deletar + Kickar', value='kick'),
])
@app_commands.checks.has_permissions(administrator=True)
async def cmd_antispam_setup(
    interaction: discord.Interaction,
    ativo: bool = True,
    max_mensagens: int = 5,
    janela_segundos: int = 5,
    acao: str = 'delete',
    cargo_imune: Optional[discord.Role] = None
):
    gid = str(interaction.guild.id)
    cfg = load_json('config_data.json')
    cfg.setdefault(gid, {})
    cfg[gid]['antispam'] = {
        'ativo': ativo,
        'max_mensagens': max(2, min(max_mensagens, 30)),
        'janela_segundos': max(2, min(janela_segundos, 60)),
        'acao': acao,
        'cargo_imune_id': str(cargo_imune.id) if cargo_imune else None
    }
    save_json('config_data.json', cfg)
    save_config(gid, cfg[gid])  # Atualizar cache

    status = '✅ Ativado' if ativo else '❌ Desativado'
    e = embed_ok('Anti-Spam Configurado', f'Status: **{status}**\n\n🔍 **Agora funciona de verdade!** O bot monitorará todas as mensagens.', interaction.user)
    e.add_field(name='📊 Limite', value=f'**{max_mensagens}** msgs em **{janela_segundos}s**', inline=True)
    e.add_field(name='⚡ Ação', value=acao.upper(), inline=True)
    if cargo_imune:
        e.add_field(name='🛡️ Cargo Imune', value=cargo_imune.mention, inline=True)
    e.add_field(name='ℹ️ Info', value='Admins e moderadores (Gerenciar Mensagens) são sempre imunes.', inline=False)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='antilink_setup', description='⚙️ Configura o anti-link (funcional no on_message)')
@app_commands.describe(
    ativo='Ativar (True) ou Desativar (False)',
    acao='Ação ao detectar link',
    cargo_imune='Cargo imune ao filtro de links',
    permitir_discord='Permitir links do próprio Discord (convites)',
    canal_permitido='Canal onde links são sempre permitidos (opcional)'
)
@app_commands.choices(acao=[
    app_commands.Choice(name='Deletar mensagem', value='delete'),
    app_commands.Choice(name='Deletar + Avisar', value='delete_warn'),
    app_commands.Choice(name='Deletar + Mutar 10 min', value='delete_mute'),
])
@app_commands.checks.has_permissions(administrator=True)
async def cmd_antilink_setup(
    interaction: discord.Interaction,
    ativo: bool = True,
    acao: str = 'delete_warn',
    cargo_imune: Optional[discord.Role] = None,
    permitir_discord: bool = False,
    canal_permitido: Optional[discord.TextChannel] = None
):
    gid = str(interaction.guild.id)
    cfg = load_json('config_data.json')
    cfg.setdefault(gid, {})
    cfg[gid]['antilink'] = {
        'ativo': ativo,
        'acao': acao,
        'cargo_imune_id': str(cargo_imune.id) if cargo_imune else None,
        'permitir_discord': permitir_discord,
        'canal_permitido_id': str(canal_permitido.id) if canal_permitido else None
    }
    save_json('config_data.json', cfg)
    save_config(gid, cfg[gid])  # Atualizar cache

    status = '✅ Ativado' if ativo else '❌ Desativado'
    e = embed_ok('Anti-Link Configurado', f'Status: **{status}**\n\n🔍 **Agora funciona de verdade!** Links serão bloqueados automaticamente.', interaction.user)
    e.add_field(name='⚡ Ação', value=acao.upper(), inline=True)
    e.add_field(name='🔗 Links Discord', value='Permitidos' if permitir_discord else 'Bloqueados', inline=True)
    if cargo_imune:
        e.add_field(name='🛡️ Cargo Imune', value=cargo_imune.mention, inline=True)
    if canal_permitido:
        e.add_field(name='📍 Canal Livre', value=canal_permitido.mention, inline=True)
    e.add_field(name='ℹ️ Info', value='Admins e moderadores (Gerenciar Mensagens) são sempre imunes.', inline=False)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='antiraid_setup', description='🛡️ Configura o sistema anti-raid completo')
@app_commands.describe(
    ativo='Ativar (True) ou Desativar (False)',
    acao='O que fazer com membros durante raid',
    max_joins='Quantos joins em X segundos dispara o anti-raid (padrão: 5)',
    janela_segundos='Janela de tempo para contar os joins (padrão: 10)',
    min_conta_dias='Bloquear contas com menos de X dias (0 = desativado)',
    lockdown_minutos='Minutos de lockdown ao detectar raid (se ação = lockdown)'
)
@app_commands.choices(acao=[
    app_commands.Choice(name='Kickar membros do raid', value='kick'),
    app_commands.Choice(name='Banir membros do raid', value='ban'),
    app_commands.Choice(name='Ativar lockdown temporário', value='lockdown'),
    app_commands.Choice(name='Apenas alertar no log', value='alert'),
])
@app_commands.checks.has_permissions(administrator=True)
async def cmd_antiraid_setup(
    interaction: discord.Interaction,
    ativo: bool = True,
    acao: str = 'kick',
    max_joins: int = 5,
    janela_segundos: int = 10,
    min_conta_dias: int = 0,
    lockdown_minutos: int = 5
):
    gid = str(interaction.guild.id)
    cfg = load_json('config_data.json')
    cfg.setdefault(gid, {})
    cfg[gid]['antiraid'] = {
        'ativo': ativo,
        'acao': acao,
        'max_joins': max(2, min(max_joins, 50)),
        'janela_segundos': max(3, min(janela_segundos, 60)),
        'min_conta_dias': max(0, min_conta_dias),
        'lockdown_minutos': max(1, min(lockdown_minutos, 60))
    }
    save_json('config_data.json', cfg)
    save_config(gid, cfg[gid])

    # Reset tracker
    bot._join_tracker[gid] = deque()
    bot._raid_active[gid] = False

    status = '✅ Ativado' if ativo else '❌ Desativado'
    e = embed_ok('Anti-Raid Configurado', f'Status: **{status}**', interaction.user)
    e.add_field(name='⚡ Ação', value=acao.upper(), inline=True)
    e.add_field(name='📊 Gatilho', value=f'**{max_joins}** joins em **{janela_segundos}s**', inline=True)
    if min_conta_dias:
        e.add_field(name='🛡️ Idade mínima', value=f'**{min_conta_dias}** dias', inline=True)
    if acao == 'lockdown':
        e.add_field(name='🔒 Lockdown', value=f'**{lockdown_minutos}** minutos', inline=True)
    e.add_field(
        name='ℹ️ Como funciona',
        value=(
            f'Se **{max_joins}+** membros entrarem em **{janela_segundos}s** → raid detectado\n'
            f'Ação automática: **{acao.upper()}**\n'
            f'Alertas vão para o canal de log configurado'
        ),
        inline=False
    )
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='criar_canal', description='📋 Cria um novo canal de texto')
@app_commands.describe(nome='Nome do canal', categoria='Categoria (opcional)', topico='Tópico do canal (opcional)')
@app_commands.checks.has_permissions(manage_channels=True)
async def cmd_criar_canal(interaction: discord.Interaction, nome: str, categoria: Optional[discord.CategoryChannel] = None, topico: str = ''):
    """Cria um novo canal de texto no servidor."""
    try:
        ch = await interaction.guild.create_text_channel(
            nome, category=categoria, topic=topico if topico else None,
            reason=f'Criado por {interaction.user.name}'
        )
        await interaction.response.send_message(embed=embed_ok('Canal Criado', f'Canal {ch.mention} criado!', interaction.user))
    except Exception as ex:
        await interaction.response.send_message(embed=embed_err('Erro', f'Não foi possível criar: {ex}', interaction.user), ephemeral=True)


@bot.tree.command(name='deletar_canal', description='🗑️ Deleta um canal (Admin)')
@app_commands.describe(canal='Canal a deletar', motivo='Motivo')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_deletar_canal(interaction: discord.Interaction, canal: discord.TextChannel, motivo: str = 'Sem motivo'):
    """Deleta um canal de texto permanentemente."""
    nome = canal.name
    try:
        await canal.delete(reason=f'Deletado por {interaction.user.name}: {motivo}')
        await interaction.response.send_message(embed=embed_ok('Canal Deletado', f'Canal `#{nome}` foi deletado.\n**Motivo:** {motivo}', interaction.user))
    except Exception as ex:
        await interaction.response.send_message(embed=embed_err('Erro', f'Não foi possível deletar: {ex}', interaction.user), ephemeral=True)


@bot.tree.command(name='criar_cargo', description='🎭 Cria um novo cargo')
@app_commands.describe(nome='Nome do cargo', cor='Cor hex (ex: FF5733)', hoisted='Mostrar separado na lista', mencionavel='Permitir mencionar')
@app_commands.checks.has_permissions(manage_roles=True)
async def cmd_criar_cargo(interaction: discord.Interaction, nome: str, cor: str = '000000', hoisted: bool = False, mencionavel: bool = False):
    """Cria um novo cargo no servidor com as configurações especificadas."""
    try:
        color_int = int(cor.lstrip('#'), 16)
    except ValueError:
        color_int = 0
    try:
        role = await interaction.guild.create_role(
            name=nome, color=discord.Color(color_int),
            hoist=hoisted, mentionable=mencionavel,
            reason=f'Criado por {interaction.user.name}'
        )
        e = embed_ok('Cargo Criado', f'Cargo {role.mention} criado!', interaction.user)
        e.add_field(name='🎨 Cor', value=f'`#{cor.upper().lstrip("#")}`', inline=True)
        e.add_field(name='📌 Hoisted', value='Sim' if hoisted else 'Não', inline=True)
        e.add_field(name='🔗 Mencionável', value='Sim' if mencionavel else 'Não', inline=True)
        await interaction.response.send_message(embed=e)
    except Exception as ex:
        await interaction.response.send_message(embed=embed_err('Erro', f'Não foi possível criar: {ex}', interaction.user), ephemeral=True)


@bot.tree.command(name='deletar_cargo', description='🗑️ Deleta um cargo (Admin)')
@app_commands.describe(cargo='Cargo a deletar', motivo='Motivo')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_deletar_cargo(interaction: discord.Interaction, cargo: discord.Role, motivo: str = 'Sem motivo'):
    """Deleta um cargo do servidor permanentemente."""
    nome = cargo.name
    try:
        await cargo.delete(reason=f'Deletado por {interaction.user.name}: {motivo}')
        await interaction.response.send_message(embed=embed_ok('Cargo Deletado', f'Cargo `{nome}` foi deletado.\n**Motivo:** {motivo}', interaction.user))
    except Exception as ex:
        await interaction.response.send_message(embed=embed_err('Erro', f'Não foi possível deletar: {ex}', interaction.user), ephemeral=True)


@bot.tree.command(name='cargo_cor', description='🎨 Altera a cor de um cargo')
@app_commands.describe(cargo='Cargo a alterar', cor='Nova cor hex (ex: FF5733)')
@app_commands.checks.has_permissions(manage_roles=True)
async def cmd_cargo_cor(interaction: discord.Interaction, cargo: discord.Role, cor: str):
    try:
        color_int = int(cor.lstrip('#'), 16)
    except ValueError:
        await interaction.response.send_message(embed=embed_err('Cor Inválida', 'Use formato hex, ex: `FF5733` ou `#FF5733`.', interaction.user), ephemeral=True)
        return
    if cargo >= interaction.guild.me.top_role:
        await interaction.response.send_message(embed=embed_err('Hierarquia', 'Não posso editar um cargo acima do meu.', interaction.user), ephemeral=True)
        return
    antiga = str(cargo.color)
    try:
        await cargo.edit(color=discord.Color(color_int), reason=f'Cor alterada por {interaction.user.name}')
    except discord.Forbidden:
        await interaction.response.send_message(embed=embed_err('Sem Permissão', 'Não tenho permissão para editar este cargo.', interaction.user), ephemeral=True)
        return
    e = embed_ok('Cor Alterada', f'Cor do cargo {cargo.mention} alterada!', interaction.user)
    e.add_field(name='Antiga', value=f'`{antiga}`', inline=True)
    e.add_field(name='Nova', value=f'`#{cor.upper().lstrip("#")}`', inline=True)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name='massrole_add', description='➕ Adiciona cargo a todos os membros (Admin)')
@app_commands.describe(cargo='Cargo a adicionar', filtro_cargo='Só membros com este cargo (opcional)')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_massrole_add(interaction: discord.Interaction, cargo: discord.Role, filtro_cargo: Optional[discord.Role] = None):
    await interaction.response.defer()
    if cargo >= interaction.guild.me.top_role:
        await interaction.followup.send(embed=embed_err('Hierarquia', 'Não posso gerenciar este cargo (está acima do meu).', interaction.user))
        return
    if filtro_cargo:
        membros = [m for m in filtro_cargo.members if not m.bot and cargo not in m.roles]
    else:
        membros = [m for m in interaction.guild.members if not m.bot and cargo not in m.roles]
    count = 0
    erros = 0
    for member in membros:
        try:
            await member.add_roles(cargo, reason=f'Mass role por {interaction.user.name}')
            count += 1
            await asyncio.sleep(0.3)  # rate limit
        except Exception:
            erros += 1
    e = embed_ok('Mass Role Concluído', f'{cargo.mention} adicionado a **{count}** membro(s).', interaction.user)
    if erros:
        e.add_field(name='❌ Erros', value=f'{erros} membro(s) não processados', inline=True)
    if filtro_cargo:
        e.add_field(name='🎭 Filtro', value=filtro_cargo.mention, inline=True)
    await interaction.followup.send(embed=e)


@bot.tree.command(name='massrole_remove', description='➖ Remove cargo de todos os membros (Admin)')
@app_commands.describe(cargo='Cargo a remover')
@app_commands.checks.has_permissions(administrator=True)
async def cmd_massrole_remove(interaction: discord.Interaction, cargo: discord.Role):
    await interaction.response.defer()
    if cargo >= interaction.guild.me.top_role:
        await interaction.followup.send(embed=embed_err('Hierarquia', 'Não posso gerenciar este cargo (está acima do meu).', interaction.user))
        return
    membros = [m for m in cargo.members if not m.bot]
    count = 0
    erros = 0
    for member in membros:
        try:
            await member.remove_roles(cargo, reason=f'Mass role remove por {interaction.user.name}')
            count += 1
            await asyncio.sleep(0.3)
        except Exception:
            erros += 1
    e = embed_ok('Mass Role Removido', f'{cargo.mention} removido de **{count}** membro(s).', interaction.user)
    if erros:
        e.add_field(name='❌ Erros', value=f'{erros} não processados', inline=True)
    await interaction.followup.send(embed=e)


@bot.tree.command(name='security_status', description='🛡️ Mostra o status dos sistemas de segurança do servidor')
@app_commands.checks.has_permissions(manage_guild=True)
async def cmd_security_status(interaction: discord.Interaction):
    gid = str(interaction.guild.id)
    cfg = get_config(gid)
    antispam = cfg.get('antispam', {})
    antilink = cfg.get('antilink', {})
    antiraid = cfg.get('antiraid', {})

    def status(d): return '✅ Ativo' if d.get('ativo') else '❌ Inativo'

    e = discord.Embed(title='🛡️ Status de Segurança', color=0x5865F2, timestamp=datetime.now())
    e.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)

    # Anti-Spam
    spam_txt = f'{status(antispam)}'
    if antispam.get('ativo'):
        spam_txt += f'\nLimite: **{antispam.get("max_mensagens",5)}** msgs/{antispam.get("janela_segundos",5)}s'
        spam_txt += f'\nAção: **{antispam.get("acao","delete").upper()}**'
    e.add_field(name='🚫 Anti-Spam', value=spam_txt, inline=True)

    # Anti-Link
    link_txt = f'{status(antilink)}'
    if antilink.get('ativo'):
        link_txt += f'\nAção: **{antilink.get("acao","delete_warn").upper()}**'
    e.add_field(name='🔗 Anti-Link', value=link_txt, inline=True)

    # Anti-Raid
    raid_txt = f'{status(antiraid)}'
    if antiraid.get('ativo'):
        raid_txt += f'\nGatilho: **{antiraid.get("max_joins",5)}** joins/{antiraid.get("janela_segundos",10)}s'
        raid_txt += f'\nAção: **{antiraid.get("acao","kick").upper()}**'
        raid_txt += f'\nIdade mínima: **{antiraid.get("min_conta_dias",0)}d**'
        raid_active = bot._raid_active.get(gid, False)
        if raid_active:
            raid_txt += '\n🚨 **RAID ATIVO AGORA!**'
    e.add_field(name='🛡️ Anti-Raid', value=raid_txt, inline=True)

    # Verificação
    v_ch = cfg.get('verification_channel_id')
    v_role = cfg.get('verified_role_id')
    ver_txt = f'Canal: {"<#" + v_ch + ">" if v_ch else "❌ Não configurado"}'
    ver_txt += f'\nCargo: {"<@&" + v_role + ">" if v_role else "❌ Não configurado"}'
    e.add_field(name='🔒 Verificação', value=ver_txt, inline=False)

    e.set_footer(text=f'Solicitado por {interaction.user.name}', icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=e)


@tasks.loop(minutes=30)
async def task_codigos_expirados():
    try:
        agora = datetime.now()
        expirados = [uid for uid, info in bot.verification_codes.items() if agora > info['timestamp'] + timedelta(hours=1)]
        for uid in expirados:
            del bot.verification_codes[uid]
        if expirados:
            logger.info(f'{len(expirados)} código(s) expirado(s) removido(s)')
    except Exception as e:
        logger.error(f'Erro task codigos: {e}')


@tasks.loop(minutes=5)
async def task_bans_temporarios():
    try:
        ban_data = load_json('ban_data.json')
        agora = datetime.now()
        for gid, users in ban_data.items():
            guild = bot.get_guild(int(gid))
            if not guild:
                continue
            para_desbanir = []
            for uid, info in users.items():
                if info.get('tipo') != 'temporario':
                    continue
                expiry = info.get('expiry')
                if expiry and agora > datetime.fromisoformat(expiry):
                    para_desbanir.append(uid)
            for uid in para_desbanir:
                try:
                    user = await bot.fetch_user(int(uid))
                    await guild.unban(user, reason='Ban temporário expirado')
                    del ban_data[gid][uid]
                    await log_canal(guild, 'unban', {'usuario': f'{user.name} ({user.id})', 'motivo': 'Ban temporário expirado'})
                    logger.info(f'Ban temporário expirado: {user.name}')
                except Exception as ex:
                    logger.error(f'Erro unban {uid}: {ex}')
        save_json('ban_data.json', ban_data)
    except Exception as e:
        logger.error(f'Erro task bans: {e}')


@tasks.loop(minutes=5)
async def task_mutes_temporarios():
    try:
        mute_data = load_json('mute_data.json')
        agora = datetime.now()
        for gid, users in mute_data.items():
            guild = bot.get_guild(int(gid))
            if not guild:
                continue
            para_desmutar = []
            for uid, info in users.items():
                expiry = info.get('expiry')
                if expiry and agora > datetime.fromisoformat(expiry):
                    para_desmutar.append(uid)
            for uid in para_desmutar:
                try:
                    member = guild.get_member(int(uid))
                    if member and member.is_timed_out():
                        await member.timeout(None, reason='Mute expirado')
                        del mute_data[gid][uid]
                        await log_canal(guild, 'unmute', {'usuario': f'{member.name}', 'motivo': 'Mute expirado'})
                except Exception as ex:
                    logger.error(f'Erro unmute {uid}: {ex}')
        save_json('mute_data.json', mute_data)
    except Exception as e:
        logger.error(f'Erro task mutes: {e}')


@tasks.loop(minutes=1)
async def task_giveaways():
    try:
        data = load_json('giveaways_data.json')
        agora = datetime.now()
        for gid, giveaways in data.items():
            for gw_id, gw in giveaways.items():
                if gw.get('status') != 'ativo':
                    continue
                expiry = datetime.fromisoformat(gw['expiry'])
                if agora < expiry:
                    continue
                participantes = gw.get('participantes', [])
                vencedores_ids = []
                if participantes:
                    qtd = min(gw['vencedores'], len(participantes))
                    vencedores_ids = random.sample(participantes, qtd)
                gw['status'] = 'encerrado'
                gw['vencedores_finais'] = vencedores_ids
                try:
                    guild = bot.get_guild(int(gid))
                    if guild:
                        ch = guild.get_channel(int(gw['channel_id']))
                        if ch:
                            if vencedores_ids:
                                mencoes = ', '.join(f'<@{v}>' for v in vencedores_ids)
                                e = discord.Embed(title='🎉 Sorteio Encerrado!', description=f'**Prêmio:** {gw["premio"]}\n\n🏆 **Vencedor(es):** {mencoes}\n\n🎉 Parabéns!', color=0xF1C40F, timestamp=datetime.now())
                            else:
                                e = discord.Embed(title='🎉 Sorteio Encerrado', description=f'**Prêmio:** {gw["premio"]}\n\nNenhum participante.', color=0xE74C3C, timestamp=datetime.now())
                            await ch.send(embed=e)
                except Exception as ex:
                    logger.error(f'Erro ao encerrar giveaway: {ex}')
        save_json('giveaways_data.json', data)
    except Exception as e:
        logger.error(f'Erro task giveaways: {e}')


@tasks.loop(minutes=1)
async def task_lembretes():
    try:
        data = load_json('reminders_data.json')
        agora = datetime.now()
        for gid, reminders in data.items():
            for rem_id, rem in reminders.items():
                if rem.get('status') != 'ativo':
                    continue
                expiry = datetime.fromisoformat(rem['expiry'])
                if agora < expiry:
                    continue
                rem['status'] = 'enviado'
                try:
                    guild = bot.get_guild(int(gid))
                    if guild:
                        ch = guild.get_channel(int(rem['channel_id']))
                        user = guild.get_member(int(rem['user_id']))
                        if ch and user:
                            e = discord.Embed(title='⏰ Lembrete!', description=rem['mensagem'], color=0xF39C12, timestamp=datetime.now())
                            e.set_footer(text=f'Lembrete de {user.name}', icon_url=user.display_avatar.url)
                            await ch.send(f'{user.mention}', embed=e)
                except Exception as ex:
                    logger.error(f'Erro ao enviar lembrete: {ex}')
        save_json('reminders_data.json', data)
    except Exception as e:
        logger.error(f'Erro task lembretes: {e}')


@tasks.loop(hours=1)
async def task_backup():
    try:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        bdir = f'backups/auto_{ts}'
        os.makedirs(bdir, exist_ok=True)
        count = 0
        for f in os.listdir('.'):
            if f.endswith('.json'):
                shutil.copy2(f, os.path.join(bdir, f))
                count += 1
        logger.info(f'Backup automático: {count} arquivos em {bdir}')
        backups = sorted([d for d in os.listdir('backups') if d.startswith('auto_')]) if os.path.exists('backups') else []
        if len(backups) > 48:
            for old in backups[:-48]:
                try:
                    shutil.rmtree(os.path.join('backups', old))
                except Exception:
                    pass
    except Exception as e:
        logger.error(f'Erro task backup: {e}')


@tasks.loop(minutes=5)
async def task_flush_xp():
    """Salva o cache de XP em memória para o SQLite a cada 5 minutos."""
    try:
        cache = bot._xp_cache
        if not cache:
            return
        count = 0
        for key, lv in list(cache.items()):
            gid, uid = key.split(':', 1)
            save_user_level(gid, uid, lv)
            count += 1
        if count:
            logger.info(f'XP flush: {count} usuários salvos')
    except Exception as e:
        logger.error(f'Erro task flush XP: {e}')


@tasks.loop(minutes=2)
async def task_flush_config():
    """Salva configs alteradas (dirty) para o JSON a cada 2 minutos."""
    try:
        dirty = getattr(bot, '_config_dirty', set())
        if not dirty:
            return
        cfg_all = load_json('config_data.json')
        cache = getattr(bot, '_config_cache', {})
        for gid in list(dirty):
            if gid in cache:
                cfg_all[gid] = cache[gid]
        save_json('config_data.json', cfg_all)
        bot._config_dirty = set()
        logger.info(f'Config flush: {len(dirty)} servidor(es)')
    except Exception as e:
        logger.error(f'Erro task flush config: {e}')


@task_codigos_expirados.before_loop
@task_bans_temporarios.before_loop
@task_mutes_temporarios.before_loop
@task_giveaways.before_loop
@task_lembretes.before_loop
@task_backup.before_loop
@task_flush_xp.before_loop
@task_flush_config.before_loop
async def before_tasks():
    await bot.wait_until_ready()


if __name__ == '__main__':
    import os
    TOKEN = os.environ.get('DISCORD_TOKEN', '')

    if not TOKEN:
        print('=' * 60)
        print('  ERRO: Variável de ambiente DISCORD_TOKEN não definida!')
        print('  No Railway: vá em Variables e adicione DISCORD_TOKEN')
        print('  Localmente: export DISCORD_TOKEN=seu_token_aqui')
        print('=' * 60)
        exit(1)

    try:
        logger.info('Iniciando Bot...')
        bot.run(TOKEN, log_handler=None)
    except discord.LoginFailure:
        logger.error('Token inválido! Verifique o DISCORD_TOKEN.')
    except KeyboardInterrupt:
        logger.info('Bot encerrado.')
    except Exception as e:
        logger.error(f'Erro ao iniciar: {e}')
