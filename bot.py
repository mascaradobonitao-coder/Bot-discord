import os
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix=["+", "!"], intents=intents)

@bot.event
async def on_ready():
    print(f"Online como {bot.user}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    await ctx.send("Erro ao executar comando.")

@bot.command()
async def ping(ctx):
    await ctx.send(f"Pong! {round(bot.latency * 1000)}ms")

@bot.command()
async def help(ctx):
    cmds = [c.name for c in bot.commands]
    await ctx.send("Comandos: " + ", ".join(cmds))

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    print("ERRO: DISCORD_TOKEN não definido")
    exit()

bot.run(TOKEN)

import io
from datetime import datetime
from discord.ui import View, Button

ticket_config = {
    "category_id": None,
    "staff_roles": set()
}

class TicketPanel(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Abrir Ticket", style=discord.ButtonStyle.green, custom_id="open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: Button):
        guild = interaction.guild
        category = guild.get_channel(ticket_config["category_id"])
        if not category:
            await interaction.response.send_message("Categoria não configurada.", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True)
        }

        for role_id in ticket_config["staff_roles"]:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            category=category,
            overwrites=overwrites
        )

        view = TicketControls()
        await channel.send(f"{interaction.user.mention}", view=view)
        await interaction.response.send_message(f"Ticket criado: {channel.mention}", ephemeral=True)

class TicketControls(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Atender", style=discord.ButtonStyle.blurple, custom_id="claim_ticket")
    async def claim(self, interaction: discord.Interaction, button: Button):
        if not any(role.id in ticket_config["staff_roles"] for role in interaction.user.roles):
            await interaction.response.send_message("Sem permissão.", ephemeral=True)
            return
        await interaction.channel.send(f"{interaction.user.mention} assumiu o ticket.")
        await interaction.response.defer()

    @discord.ui.button(label="Encaminhar DM", style=discord.ButtonStyle.gray, custom_id="send_log")
    async def send_log(self, interaction: discord.Interaction, button: Button):
        if not any(role.id in ticket_config["staff_roles"] for role in interaction.user.roles):
            await interaction.response.send_message("Sem permissão.", ephemeral=True)
            return

        messages = []
        async for msg in interaction.channel.history(limit=None, oldest_first=True):
            content = f"[{msg.created_at.strftime('%d/%m/%Y %H:%M')}] {msg.author}: {msg.content}"
            if msg.attachments:
                content += " | ANEXOS: " + ", ".join(a.url for a in msg.attachments)
            messages.append(content)

        text = "\n".join(messages)
        file = discord.File(io.BytesIO(text.encode()), filename="ticket.txt")

        try:
            await interaction.user.send(file=file)
            await interaction.response.send_message("Conversa enviada na sua DM.", ephemeral=True)
        except:
            await interaction.response.send_message("Erro ao enviar DM.", ephemeral=True)

    @discord.ui.button(label="Fechar", style=discord.ButtonStyle.red, custom_id="close_ticket")
    async def close(self, interaction: discord.Interaction, button: Button):
        if not any(role.id in ticket_config["staff_roles"] for role in interaction.user.roles):
            await interaction.response.send_message("Sem permissão.", ephemeral=True)
            return
        await interaction.response.send_message("Fechando ticket...")
        await interaction.channel.delete()

@bot.command()
async def painel(ctx):
    view = TicketPanel()
    await ctx.send("Clique para abrir ticket:", view=view)

@bot.command()
async def setcategoria(ctx, categoria: discord.CategoryChannel):
    ticket_config["category_id"] = categoria.id
    await ctx.send("Categoria definida.")

@bot.command()
async def addstaff(ctx, role: discord.Role):
    ticket_config["staff_roles"].add(role.id)
    await ctx.send("Cargo adicionado.")

@bot.command()
async def removestaff(ctx, role: discord.Role):
    ticket_config["staff_roles"].discard(role.id)
    await ctx.send("Cargo removido.")

@bot.event
async def on_ready():
    bot.add_view(TicketPanel())
    bot.add_view(TicketControls())
    print(f"Online como {bot.user}")

import json
import os

CONFIG_FILE = "config.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"category_id": None, "staff_roles": []}
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config():
    with open(CONFIG_FILE, "w") as f:
        json.dump(ticket_config, f)

ticket_config = load_config()

@bot.command()
async def setcategoria(ctx, categoria: discord.CategoryChannel):
    ticket_config["category_id"] = categoria.id
    save_config()
    await ctx.send("Categoria definida.")

@bot.command()
async def addstaff(ctx, role: discord.Role):
    if role.id not in ticket_config["staff_roles"]:
        ticket_config["staff_roles"].append(role.id)
        save_config()
    await ctx.send("Cargo adicionado.")

@bot.command()
async def removestaff(ctx, role: discord.Role):
    if role.id in ticket_config["staff_roles"]:
        ticket_config["staff_roles"].remove(role.id)
        save_config()
    await ctx.send("Cargo removido.")

@bot.command()
async def config(ctx):
    categoria = ticket_config["category_id"]
    staffs = ticket_config["staff_roles"]

    cat = f"<#{categoria}>" if categoria else "Não definida"
    roles = " ".join(f"<@&{r}>" for r in staffs) if staffs else "Nenhum"

    await ctx.send(f"Categoria: {cat}\nStaff: {roles}")

import time

XP_FILE = "xp.json"
xp_data = {}
cooldown = {}

def load_xp():
    global xp_data
    if os.path.exists(XP_FILE):
        with open(XP_FILE, "r") as f:
            xp_data = json.load(f)
    else:
        xp_data = {}

def save_xp():
    with open(XP_FILE, "w") as f:
        json.dump(xp_data, f)

def get_level(xp):
    level = 0
    while xp >= (level + 1) * 100:
        level += 1
    return level

load_xp()

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = str(message.author.id)
    now = time.time()

    if user_id in cooldown and now - cooldown[user_id] < 5:
        await bot.process_commands(message)
        return

    cooldown[user_id] = now

    if user_id not in xp_data:
        xp_data[user_id] = {"xp": 0, "level": 0}

    xp_data[user_id]["xp"] += 10

    xp = xp_data[user_id]["xp"]
    old_level = xp_data[user_id]["level"]
    new_level = get_level(xp)

    if new_level > old_level:
        xp_data[user_id]["level"] = new_level
        await message.channel.send(f"{message.author.mention} subiu para level {new_level}!")

    save_xp()
    await bot.process_commands(message)

@bot.command()
async def rank(ctx, member: discord.Member = None):
    member = member or ctx.author
    user_id = str(member.id)

    if user_id not in xp_data:
        await ctx.send("Sem dados.")
        return

    xp = xp_data[user_id]["xp"]
    level = xp_data[user_id]["level"]

    await ctx.send(f"{member.mention} | Level: {level} | XP: {xp}")

@bot.command()
async def leaderboard(ctx):
    sorted_users = sorted(xp_data.items(), key=lambda x: x[1]["xp"], reverse=True)[:10]

    text = ""
    for i, (user_id, data) in enumerate(sorted_users, start=1):
        user = await bot.fetch_user(int(user_id))
        text += f"{i}. {user.name} - Level {data['level']} ({data['xp']} XP)\n"

    await ctx.send(text if text else "Sem dados.")

@bot.command()
async def resetxp(ctx, member: discord.Member):
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("Sem permissão.")
        return

    user_id = str(member.id)
    xp_data[user_id] = {"xp": 0, "level": 0}
    save_xp()

    await ctx.send("XP resetado.")

@bot.command()
async def criarserver(ctx, modo: str = "normal"):
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("Sem permissão.")
        return

    limpar = False

    if modo.lower() == "limpar":
        await ctx.send("Digite CONFIRMAR para apagar canais e categorias.")
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        
        try:
            confirm = await bot.wait_for("message", timeout=30, check=check)
        except:
            await ctx.send("Tempo esgotado.")
            return
        
        if confirm.content != "CONFIRMAR":
            await ctx.send("Cancelado.")
            return
        
        limpar = True

    await ctx.send("Envie o modelo do servidor:")

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        msg = await bot.wait_for("message", timeout=120, check=check)
    except:
        await ctx.send("Tempo esgotado.")
        return

    if limpar:
        for channel in ctx.guild.channels:
            try:
                await channel.delete()
            except:
                pass

        for category in ctx.guild.categories:
            try:
                await category.delete()
            except:
                pass

    linhas = msg.content.split("\n")
    categoria_atual = None
    total_categorias = 0
    total_canais = 0

    for linha in linhas:
        linha = linha.strip()

        if not linha:
            continue

        if linha.startswith("*"):
            nome_categoria = linha[1:].strip()
            categoria_atual = await ctx.guild.create_category(nome_categoria)
            total_categorias += 1

        elif linha.startswith('"') and categoria_atual:
            nome = linha[1:].strip()

            privado = "[privado]" in nome
            nome = nome.replace("[privado]", "").strip().replace(" ", "-")

            overwrites = None

            if privado:
                overwrites = {
                    ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    ctx.author: discord.PermissionOverwrite(view_channel=True)
                }

            await ctx.guild.create_text_channel(nome, category=categoria_atual, overwrites=overwrites)
            total_canais += 1

    await ctx.send(f"Servidor criado.\nCategorias: {total_categorias}\nCanais: {total_canais}")
