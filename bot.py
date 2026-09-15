"""
KREATOR CITIZENÓW DO FIVEM + SKANER NAJNOWSZYCH MODÓW Z YOUTUBE
================================================================
- Naprawione brak reakcji: trwałe widoki (Persistent Views + DynamicItem),
  więc przyciski działają NAWET PO RESTARTCIE bota.
- Skaner mody: co 30 min przeszukuje YouTube (filtry: .rpf, optymalizacja,
  potato graphics, mapy PvP) i wrzuca NAJNOWSZE filmy na #najnowsze-mody.
- Kreator citizena + kreator skinów broni + paczki ZIP z linkami.

Konfiguracja: plik .env (wzór w .env.example) -> DISCORD_TOKEN
Uruchomienie: python bot.py
"""

import asyncio
import io
import json
import logging
import os
import re
import secrets
import shutil
import ssl
import tempfile
import time
import urllib.parse
import urllib.request
import urllib.error
import zipfile

import discord
from discord import app_commands
from discord.ui import DynamicItem, Button, Select, View
from dotenv import load_dotenv

# ==============================================================
#  KONFIGURACJA
# ==============================================================

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
HTTP_PORT = int(os.getenv("HTTP_PORT", "3000"))
PUBLIC_URL = os.getenv("PUBLIC_URL") or f"http://localhost:{HTTP_PORT}"

ROLE_BUILDING = "Tworzenie citizena"
ROLE_MEMBER = "Członek"
CATEGORY_MAIN = "🛠️ CITIZEN MAKER"
CATEGORY_TICKETS = "TWOJE CITIZENY"
CATEGORY_SKINS = "🔫 SKIN MAKER"
CATEGORY_MODS = "📦 WSZYSTKIE MODY"
CATEGORY_INFO = "📢 START"
CH_MAIN = "stworz-citizena"
CH_DOWNLOADS = "pobrane-paczki"
CH_MODS = "najnowsze-mody"
CH_WELCOME = "witaj"
CH_RULES = "regulamin"
CH_ANNOUNCE = "ogłoszenia"
CH_SKINS = "stworz-skin"
CH_ALL_MODS = "wszystkie-mody"
CH_HELP = "pomoc"

SESSION_TTL_S = 2 * 60 * 60
DOWNLOAD_TTL_S = 24 * 60 * 60
YT_SCAN_INTERVAL_S = 30 * 60          # skan YouTube co 30 minut
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024

COLOR_BLUE = 0x5865F2
COLOR_GREEN = 0x57F287
COLOR_YELLOW = 0xFEE75C
COLOR_ORANGE = 0xE67E22
COLOR_RED = 0xED4245

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("citizen-bot")

DOWNLOADS_DIR = "downloads"
os.makedirs(DOWNLOADS_DIR, exist_ok=True)
POSTED_FILE = "posted_videos.json"

# ==============================================================
#  KREATOR CITIZENA — KROKI
#  fileUrl = bezpośredni link do pliku moda (PODMIEŃ na własne!)
# ==============================================================

STEPS = [
    {
        "id": "opti-pack",
        "name": "Paczka optymalizacji (OPTI)",
        "description": "Zestaw plików .rpf i timecycle podnoszący FPS - wrzucasz do folderu mods.",
        "image": "https://i.imgur.com/ZMIJFjr.jpeg",  # PODMIEŃ
        "fileUrl": "https://example.com/mods/opti_pack.rpf",  # PODMIEŃ
        "fileName": "opti_pack.rpf",
        "target": "mods",
    },
    {
        "id": "potato",
        "name": "Ustawienia POTATO (max FPS)",
        "description": "Skrajne ustawienia graficzne 'potato' - gra wygląda słabo, ale lata na każdym PC.",
        "image": "https://i.imgur.com/SHADOW1.jpeg",  # PODMIEŃ
        "fileUrl": "https://example.com/mods/graphics_potato.rpf",  # PODMIEŃ
        "fileName": "graphics_potato.rpf",
        "target": "mods",
    },
    {
        "id": "map-pvp",
        "name": "Mapa OPTI pod PvP",
        "description": "Zoptymalizowana mapa/miejsce pod PvP - mniej obiektów, więcej FPS w strefach walki.",
        "image": "https://i.imgur.com/WATER1.jpeg",  # PODMIEŃ
        "fileUrl": "https://example.com/mods/pvp_map_opti.rpf",  # PODMIEŃ
        "fileName": "pvp_map_opti.rpf",
        "target": "mods",
    },
    {
        "id": "shadows",
        "name": "Usunięcie cieni",
        "description": "Wyłącza cienie dynamiczne - duży zysk FPS na słabszych kartach.",
        "image": "https://i.imgur.com/BLOOD1.jpeg",  # PODMIEŃ
        "fileUrl": "https://example.com/mods/no_shadows.rpf",  # PODMIEŃ
        "fileName": "no_shadows.rpf",
        "target": "mods",
    },
]

# ==============================================================
#  KREATOR SKINÓW BRONI
# ==============================================================

WEAPONS = [
    {
        "id": "pistol",
        "name": "Pistol",
        "skins": [
            {"id": "pistol-blackops", "name": "Black Ops", "description": "Czarny matowy skin z zielonymi akcentami.",
             "image": "https://i.imgur.com/SKIN1.jpeg", "fileUrl": "https://example.com/skins/pistol_blackops.rpf",
             "fileName": "pistol_blackops.rpf", "target": "mods"},
            {"id": "pistol-desert", "name": "Desert Tan", "description": "Pustynny kamuflaż.",
             "image": "https://i.imgur.com/SKIN2.jpeg", "fileUrl": "https://example.com/skins/pistol_desert.rpf",
             "fileName": "pistol_desert.rpf", "target": "mods"},
        ],
    },
    {
        "id": "heavypistol",
        "name": "Heavy Pistol",
        "skins": [
            {"id": "heavypistol-chrome", "name": "Chrome", "description": "Chromowany połysk.",
             "image": "https://i.imgur.com/SKIN3.jpeg", "fileUrl": "https://example.com/skins/heavypistol_chrome.rpf",
             "fileName": "heavypistol_chrome.rpf", "target": "mods"},
        ],
    },
    {
        "id": "appistol",
        "name": "AP Pistol",
        "skins": [
            {"id": "appistol-carbon", "name": "Carbon Fiber", "description": "Węglowy wzór.",
             "image": "https://i.imgur.com/SKIN4.jpeg", "fileUrl": "https://example.com/skins/appistol_carbon.rpf",
             "fileName": "appistol_carbon.rpf", "target": "mods"},
        ],
    },
    {
        "id": "carbine",
        "name": "Carbine Rifle",
        "skins": [
            {"id": "carbine-woodland", "name": "Woodland", "description": "Leśny kamuflaż.",
             "image": "https://i.imgur.com/SKIN5.jpeg", "fileUrl": "https://example.com/skins/carbine_woodland.rpf",
             "fileName": "carbine_woodland.rpf", "target": "mods"},
        ],
    },
    {
        "id": "ak47",
        "name": "AK-47 (Assault Rifle)",
        "skins": [
            {"id": "ak47-redline", "name": "Redline", "description": "Czerwone linie na czerni.",
             "image": "https://i.imgur.com/SKIN6.jpeg", "fileUrl": "https://example.com/skins/ak47_redline.rpf",
             "fileName": "ak47_redline.rpf", "target": "mods"},
        ],
    },
]

# ==============================================================
#  ZAPYTANIA SKANERA YOUTUBE (mody klienckie .rpf do folderu mods)
# ==============================================================

YT_QUERIES = [
    "FiveM optimization mod rpf",
    "FiveM optymalizacja mody mods folder",
    "FiveM potato graphics settings",
    "FiveM PvP map opti",
    "FiveM fps boost pack 2025",
    "GTA5 FiveM best client mods rpf",
    "FiveM LagFix mod",
]

# ==============================================================
#  SESJE
# ==============================================================

class Session:
    def __init__(self, user_id, guild_id, channel_id):
        self.user_id = user_id
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.choices = set()               # id kroków citizena
        self.weapon_skins = {}             # weapon_id -> skin_id
        self.created_at = time.time()
        self.last_activity = time.time()


SESSIONS = {}  # channel_id -> Session


def get_session(channel_id):
    s = SESSIONS.get(channel_id)
    if s:
        s.last_activity = time.time()
    return s


# ==============================================================
#  POBIERANIE + ZIP
# ==============================================================

def _open_ctx(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FiveMCitizenBot/2.0",
        "Accept-Language": "pl,en;q=0.9",
    })
    ctx = ssl.create_default_context()
    return urllib.request.urlopen(req, timeout=30, context=ctx)


def download_bytes(url: str) -> bytes:
    with _open_ctx(url) as resp:
        data = resp.read(MAX_DOWNLOAD_BYTES + 1)
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ValueError("Plik przekracza limit rozmiaru")
    return data


def build_citizen_zip(chosen: list) -> tuple:
    """Buduje strukturę paczki FiveM (folder mods) w pamięci. Zwraca (token, bytes, count)."""
    token = secrets.token_hex(16)
    buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for step in chosen:
            target = (step["target"].rstrip("/") + "/")
            zf.writestr(target + step["fileName"], b"")
            count += 1
        instr = [
            "=== TWOJA PACZKA CITIZEN (FiveM) ===",
            f"Wygenerowano: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "Wybrane mody:",
            *[f" - {s['name']}: {s.get('description', '')}" for s in chosen],
            "",
            "Instalacja:",
            "1. Otwórz folder FiveM (np. C:/Users/.../AppData/Local/FiveM/FiveM.app).",
            "2. Wrzuć pliki .rpf do folderu 'mods' (utwórz go, jeśli nie ma).",
            "3. Uruchom ponownie FiveM.",
            "",
            "UWAGA: mody klienckie działają na serwerach, które nie blokują",
            "modyfikacji plików client-side. Na niektórych serwerach może być",
            "to zabronione - sprawdź regulamin serwera!",
        ]
        zf.writestr("INSTRUKCJA.txt", "\n".join(instr))
        count += 1
    return token, buf.getvalue(), count


PENDING_DOWNLOADS = {}  # token -> {data, fileName, created_at}


# ==============================================================
#  SERWER HTTP (linki do paczek)
# ==============================================================

async def start_http_server():
    from aiohttp import web

    async def handle_download(request):
        dl = PENDING_DOWNLOADS.get(request.match_info["token"])
        if not dl:
            return web.Response(status=404, text="404: Paczka nie istnieje lub wygasla.")
        return web.Response(
            body=dl["data"],
            content_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{dl["fileName"]}"'},
        )

    async def handle_health(request):
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/download/{token}", handle_download)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HTTP_PORT)
    await site.start()
    log.info("Serwer HTTP na porcie %s", HTTP_PORT)


# ==============================================================
#  SKANER YOUTUBE — NAJNOWSZE MODY
# ==============================================================

def load_posted() -> set:
    try:
        with open(POSTED_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_posted(posted: set):
    try:
        with open(POSTED_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(posted)[-2000:], f)
    except Exception as e:
        log.warning("Nie zapisalem posted_videos.json: %s", e)


def yt_search(query: str) -> list:
    """Scrapuje wyniki YouTube (filtry: ostatni tydzień). Zwraca listę filmów."""
    url = ("https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
           + "&sp=EgQIAxAB")  # filtr: przesłane w tym tygodniu
    try:
        with _open_ctx(url) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        log.warning("YouTube search error (%s): %s", query, e)
        return []

    m = re.search(r"var ytInitialData\s*=\s*(\{.*?\});</script>", html)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []

    videos = []

    def walk(node):
        if isinstance(node, dict):
            if "videoRenderer" in node:
                vr = node["videoRenderer"]
                vid = vr.get("videoId")
                if not vid:
                    return
                title = "".join(
                    r.get("text", "") for r in vr.get("title", {}).get("runs", [])
                )
                published = vr.get("publishedTimeText", {}).get("simpleText", "")
                channel = vr.get("ownerText", {}).get("runs", [{}])[0].get("text", "?")
                length = vr.get("lengthText", {}).get("simpleText", "")
                views = vr.get("viewCountText", {}).get("simpleText", "")
                videos.append({
                    "id": vid,
                    "title": title or "(bez tytułu)",
                    "published": published,
                    "channel": channel,
                    "length": length,
                    "views": views,
                })
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return videos


async def scan_youtube_and_post(bot):
    """Skanuje wszystkie zapytania i wrzuca NOWE filmy na #najnowsze-mody."""
    posted = load_posted()
    new_videos = []
    for query in YT_QUERIES:
        results = await asyncio.to_thread(yt_search, query)
        for v in results:
            if v["id"] not in posted:
                new_videos.append(v)
                posted.add(v["id"])

    if not new_videos:
        log.info("Skan YouTube: brak nowych filmów.")
        return 0

    # Deduplikacja po ID (różne zapytania mogą dać ten sam film)
    seen = set()
    unique = []
    for v in new_videos:
        if v["id"] not in seen:
            seen.add(v["id"])
            unique.append(v)

    save_posted(posted)

    posted_count = 0
    for guild in bot.guilds:
        category = discord.utils.get(guild.categories, name=CATEGORY_MAIN)
        channel = discord.utils.get(category.text_channels, name=CH_MODS) if category else None
        if not channel:
            continue
        for v in unique[:20]:  # max 20 filmów na cykl, żeby nie spamować
            embed = discord.Embed(
                title=f"🎬 {v['title'][:250]}",
                url=f"https://www.youtube.com/watch?v={v['id']}",
                description=(
                    f"**Kanał:** {v['channel']}\n"
                    f"**Opublikowano:** {v['published'] or '—'}\n"
                    f"**Wyświetlenia:** {v['views'] or '—'}\n\n"
                    "Wrzuć pliki z opisu filmu do folderu `mods` w FiveM.\n"
                    "⚠️ Sprawdź regulamin serwera, na którym grasz!"
                ),
                color=COLOR_ORANGE,
            )
            embed.set_thumbnail(url=f"https://i.ytimg.com/vi/{v['id']}/hqdefault.jpg")
            try:
                await channel.send(embed=embed)
                posted_count += 1
            except discord.Forbidden:
                pass
    log.info("Skan YouTube: wrzucono %s nowych filmów.", posted_count)
    return posted_count


async def yt_scanner_loop(bot):
    await bot.wait_until_ready()
    # Pierwszy skan po 20 s od startu
    await asyncio.sleep(20)
    while True:
        try:
            await scan_youtube_and_post(bot)
        except Exception:
            log.exception("Blad skanera YouTube")
        await asyncio.sleep(YT_SCAN_INTERVAL_S)


# ==============================================================
#  TRWAŁE WIDOKI — NAPRAWA "BOT NIE REAGUJE"
#  Przyciski ze stanem w custom_id = DynamicItem (działają po restarcie).
#  Przyciski statyczne = Persistent View zarejestrowane w setup_hook.
# ==============================================================

bot = discord.Client(intents=discord.Intents.default())
tree = app_commands.CommandTree(bot)


# ---------- Statyczny panel główny ----------

class PanelView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Button(
            label="Zacznij tworzyć citizena", style=discord.ButtonStyle.primary,
            emoji="🛠️", custom_id="create_citizen",
        ))


# ---------- Wybór trybu w ticketcie ----------

class ModeView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Button(label="Citizen (mody wizualne)", style=discord.ButtonStyle.primary, emoji="🛠️", custom_id="mode_citizen"))
        self.add_item(Button(label="Skiny broni", style=discord.ButtonStyle.secondary, emoji="🔫", custom_id="mode_weapons"))


# ---------- Podsumowanie / zamknięcie ----------

class SummaryView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Button(label="Zakończ tworzenie", style=discord.ButtonStyle.success, emoji="📦", custom_id="finish_build"))
        self.add_item(Button(label="Zacznij od nowa", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="restart_wizard"))
        self.add_item(Button(label="Zamknij", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_session"))


class CloseChannelView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Button(label="Zamknij kanał", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_session"))


# ---------- Dynamiczne przyciski kreatora (stan w custom_id) ----------

class StepButton(DynamicItem[Button], template=r"step_(?P<action>add|skip|remove):(?P<idx>\d+)"):
    def __init__(self, action: str, idx: int):
        labels = {"add": ("➕", "Dodaj to", discord.ButtonStyle.primary),
                  "skip": ("⏭️", "Pomiń", discord.ButtonStyle.secondary),
                  "remove": ("🗑️", "Usuń z paczki", discord.ButtonStyle.danger)}
        emoji, label, style = labels[action]
        super().__init__(Button(label=label, style=style, emoji=emoji, custom_id=f"step_{action}:{idx}"))
        self.action = action
        self.idx = idx

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["action"], int(match["idx"]))

    async def callback(self, interaction):
        session = get_session(interaction.channel_id)
        if not session or session.user_id != interaction.user.id:
            return await interaction.response.send_message("❌ Sesja wygasła lub to nie Twoja sesja.", ephemeral=True)
        if self.idx >= len(STEPS):
            return await interaction.response.defer()

        step = STEPS[self.idx]
        if self.action == "add":
            session.choices.add(step["id"])
        elif self.action == "remove":
            session.choices.discard(step["id"])

        if self.action == "skip":
            await interaction.response.defer()
            return await send_step(interaction.channel, session, self.idx + 1)

        await interaction.response.edit_message(
            embed=build_step_embed(self.idx, step["id"] in session.choices),
            view=build_step_view(self.idx),
        )


class JumpSelect(DynamicItem[Select], template=r"step_jump_select"):
    def __init__(self, current: int):
        options = [
            discord.SelectOption(label=f"{i + 1}. {s['name']}", value=str(i), default=(i == current))
            for i, s in enumerate(STEPS)
        ]
        super().__init__(Select(placeholder="Przeskocz do innego kroku...", options=options, custom_id="step_jump_select"))
        self.current = current

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(0)

    async def callback(self, interaction):
        session = get_session(interaction.channel_id)
        if not session or session.user_id != interaction.user.id:
            return await interaction.response.send_message("❌ Sesja wygasła.", ephemeral=True)
        idx = int(self.values[0])
        await interaction.response.defer()
        await send_step(interaction.channel, session, idx)


# ---------- Kreator skinów: nawigacja i wybór ----------

class SkinNavButton(DynamicItem[Button], template=r"ws_(?P<action>prev|next|choose):(?P<wid>[a-z0-9_]+):(?P<idx>\d+)"):
    def __init__(self, action: str, wid: str, idx: int):
        labels = {
            "prev": ("◀ Wróć", discord.ButtonStyle.secondary, None),
            "next": ("Dalej ▶", discord.ButtonStyle.secondary, None),
            "choose": ("Wybierz ten skin", discord.ButtonStyle.primary, "✅"),
        }
        label, style, emoji = labels[action]
        super().__init__(Button(label=label, style=style, emoji=emoji, custom_id=f"ws_{action}:{wid}:{idx}"))
        self.action, self.wid, self.idx = action, wid, idx

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["action"], match["wid"], int(match["idx"]))

    def _weapon(self):
        return next((w for w in WEAPONS if w["id"] == self.wid), None)

    async def callback(self, interaction):
        session = get_session(interaction.channel_id)
        weapon = self._weapon()
        if not session or session.user_id != interaction.user.id or not weapon:
            return await interaction.response.send_message("❌ Sesja wygasła.", ephemeral=True)

        if self.action == "prev":
            self.idx = (self.idx - 1) % len(weapon["skins"])
        elif self.action == "next":
            self.idx = (self.idx + 1) % len(weapon["skins"])
        elif self.action == "choose":
            skin = weapon["skins"][self.idx]
            if session.weapon_skins.get(weapon["id"]) == skin["id"]:
                session.weapon_skins.pop(weapon["id"], None)  # toggle off
            else:
                session.weapon_skins[weapon["id"]] = skin["id"]

        await interaction.response.edit_message(
            embed=build_skin_embed(weapon, self.idx, session),
            view=build_skin_view(weapon, self.idx),
        )


class SkinSelect(DynamicItem[Select], template=r"ws_skin_select:(?P<wid>[a-z0-9_]+)"):
    def __init__(self, wid: str):
        weapon = next((w for w in WEAPONS if w["id"] == wid), WEAPONS[0])
        super().__init__(Select(
            placeholder="Wybierz skin...",
            options=[discord.SelectOption(label=s["name"], value=s["id"], description=s["description"][:100]) for s in weapon["skins"]],
            custom_id=f"ws_skin_select:{wid}",
        ))
        self.wid = wid

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["wid"])

    async def callback(self, interaction):
        session = get_session(interaction.channel_id)
        weapon = next((w for w in WEAPONS if w["id"] == self.wid), None)
        if not session or session.user_id != interaction.user.id or not weapon:
            return await interaction.response.send_message("❌ Sesja wygasła.", ephemeral=True)
        skin_id = self.values[0]
        session.weapon_skins[weapon["id"]] = skin_id
        idx = next(i for i, s in enumerate(weapon["skins"]) if s["id"] == skin_id)
        await interaction.response.edit_message(
            embed=build_skin_embed(weapon, idx, session),
            view=build_skin_view(weapon, idx),
        )


class WeaponSelect(Select):
    """Statyczny select broni (persistent)."""

    def __init__(self):
        super().__init__(
            placeholder="Wybierz broń...",
            options=[discord.SelectOption(label=w["name"], value=w["id"], description=f"{len(w['skins'])} skin(ow)") for w in WEAPONS],
            custom_id="ws_weapon_select",
        )

    async def callback(self, interaction):
        session = get_session(interaction.channel_id)
        if not session or session.user_id != interaction.user.id:
            return await interaction.response.send_message("❌ Sesja wygasła.", ephemeral=True)
        weapon = next((w for w in WEAPONS if w["id"] == self.values[0]), None)
        if not weapon:
            return await interaction.response.defer()
        await interaction.response.edit_message(
            embed=build_skin_embed(weapon, 0, session),
            view=build_skin_view(weapon, 0),
        )


class WeaponMenuView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(WeaponSelect())


class SkinFinishView(View):
    """Przyciski: inna broń / zbuduj / anuluj (persistent, stan w sesji)."""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Button(label="← Inna broń", style=discord.ButtonStyle.secondary, emoji="🔫", custom_id="ws_back_to_weapons"))
        self.add_item(Button(label="Zakończ i zbuduj paczkę", style=discord.ButtonStyle.success, emoji="📦", custom_id="ws_finish"))
        self.add_item(Button(label="Anuluj kreatora skinów", style=discord.ButtonStyle.danger, emoji="✖️", custom_id="ws_cancel"))


# ==============================================================
#  HANDLERY STATYCZNYCH PRZYCISKÓW (przez on_interaction)
#  Prościej i pewniej niż wyciąganie view z message.
# ==============================================================

async def handle_create_citizen(interaction, start_mode: str | None = None):
    existing = next(
        (s for s in SESSIONS.values() if s.user_id == interaction.user.id and s.guild_id == interaction.guild_id),
        None,
    )
    if existing:
        return await interaction.response.send_message(
            f"❌ Masz juz otwarta sesje: <#{existing.channel_id}>. Uzyj /zamknij.",
            ephemeral=True,
        )
    await interaction.response.defer(ephemeral=True)

    guild, user = interaction.guild, interaction.user
    building_role = discord.utils.get(guild.roles, name=ROLE_BUILDING)
    if not building_role:
        building_role = await guild.create_role(name=ROLE_BUILDING, colour=discord.Colour(COLOR_GREEN))

    tickets_cat = discord.utils.get(guild.categories, name=CATEGORY_TICKETS)
    if not tickets_cat:
        tickets_cat = await guild.create_category(CATEGORY_TICKETS)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
    }
    if building_role:
        overwrites[building_role] = discord.PermissionOverwrite(view_channel=False)

    safe = "".join(c if c.isalnum() or c == "-" else "-" for c in user.name.lower())[:20]
    channel = await guild.create_text_channel(f"citizen-{safe}", overwrites=overwrites, category=tickets_cat)
    try:
        await user.add_roles(building_role)
    except discord.Forbidden:
        pass

    session = Session(user.id, guild.id, channel.id)
    SESSIONS[channel.id] = session

    await interaction.followup.send(f"✅ Twoj prywatny kanal: <#{channel.id}>", ephemeral=True)

    embed = discord.Embed(
        title=f"👋 Cześć {user.name}!",
        description=(
            "To Twoj **prywatny kanal kreatora**.\n\n"
            "Wybierz co chcesz stworzyc:\n"
            "🛠️ **Citizen** - mody .rpf do folderu mods (opti, potato, mapy PvP),\n"
            "🔫 **Skiny broni** - personalizacja wygladu broni.\n\n"
            "W kazdej chwili przerwij: `/zamknij`."
        ),
        color=COLOR_GREEN,
    )

    # Jesli panel przekazal start_mode (np. z kanalu Skin Maker), od razu startujemy
    if start_mode == "weapons":
        await channel.send(embed=embed)  # samo powitanie bez wyboru trybu
        skin_embed = discord.Embed(
            title="🔫 Kreator skinow broni",
            description="Wybierz bron z listy, potem preskakuj skiny strzalkami i wybieraj.",
            color=COLOR_ORANGE,
        )
        return await channel.send(embed=skin_embed, view=WeaponMenuView())

    await channel.send(embed=embed, view=ModeView())


async def handle_finish_build(interaction, session):
    # Skąd wziąć wybory: citizen albo skiny
    chosen = []
    if session.choices:
        chosen = [s for s in STEPS if s["id"] in session.choices]
    elif session.weapon_skins:
        for wid, sid in session.weapon_skins.items():
            weapon = next((w for w in WEAPONS if w["id"] == wid), None)
            skin = next((s for s in weapon["skins"] if s["id"] == sid), None) if weapon else None
            if skin:
                chosen.append({"name": f"{weapon['name']} — {skin['name']}", "description": skin["description"],
                               "fileUrl": skin["fileUrl"], "fileName": skin["fileName"], "target": skin["target"]})

    if not chosen:
        return await interaction.response.send_message("❌ Nie wybrano nic - nie ma czego pakowac.", ephemeral=True)

    await interaction.response.defer()
    try:
        token, zip_data, count = await asyncio.to_thread(build_citizen_zip, chosen)
        file_name = f"citizen-{session.user_id}-{int(time.time())}.zip"
        PENDING_DOWNLOADS[token] = {"data": zip_data, "fileName": file_name, "created_at": time.time()}
        link = f"{PUBLIC_URL}/download/{token}"

        embed = discord.Embed(
            title="✅ Twoja paczka jest gotowa!",
            description=(
                f"**Pobierz:** [{file_name}]({link})\n\n"
                f"📦 Rozmiar: **{len(zip_data) / 1024 / 1024:.2f} MB**\n"
                f"🕒 Link wazny: **24 godziny**\n"
                f"📁 Plikow: {count}\n\n"
                "**Instalacja:**\n"
                "1. Pobierz ZIP.\n"
                "2. Wrzuc pliki do folderu `mods` w FiveM.\n"
                "3. Zrestartuj FiveM."
            ),
            color=COLOR_GREEN,
        )
        await interaction.followup.send(embed=embed)

        guild = interaction.guild
        category = discord.utils.get(guild.categories, name=CATEGORY_MAIN)
        dl_ch = discord.utils.get(category.text_channels, name=CH_DOWNLOADS) if category else None
        if dl_ch:
            await dl_ch.send(content=f"<@{session.user_id}> Twoja paczka: {link}")

        await interaction.channel.send(content="Gotowe! Kliknij, aby zamknac kanal.", view=CloseChannelView())
    except Exception as e:
        log.exception("Blad budowania paczki")
        await interaction.followup.send(f"❌ Blad budowania paczki: {e}")


async def handle_static_button(interaction) -> bool:
    """Obsluga statycznych custom_id. Zwraca True jeśli obsłużono."""
    cid = interaction.data.get("custom_id", "")
    session = get_session(interaction.channel_id)

    # --- Self-role: pobierz rolę Członek (bez sesji) ---
    if cid == "take_role":
        guild = interaction.guild
        role = discord.utils.get(guild.roles, name=ROLE_MEMBER)
        if role is None:
            role = await guild.create_role(name=ROLE_MEMBER, colour=discord.Colour(COLOR_BLUE))
        try:
            await interaction.user.add_roles(role, reason="Self-role na kanale witaj")
            await interaction.response.send_message("✅ Dostales role — korzystaj z kreatorow!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Bot nie ma uprawnien do nadania roli (przesun jego role wyzej).", ephemeral=True)
        return True

    # --- Skan modow wymuszony przez uzytkownika (bez sesji) ---
    if cid == "scan_now":
        await interaction.response.defer(ephemeral=True)
        count = await scan_youtube_and_post(bot)
        await interaction.followup.send(f"✅ Skan zakonczony — wrzucono {count} nowych filmow.", ephemeral=True)
        return True

    # --- Panel kreatora skinow z glownego kanalu (tworzy sesje w ticketcie) ---
    if cid == "create_weapon_skins":
        await handle_create_citizen(interaction, start_mode="weapons")
        return True

    if cid == "create_citizen":
        await handle_create_citizen(interaction)
        return True

    if cid in ("mode_citizen", "mode_weapons", "step_jump_select", "ws_weapon_select",
               "ws_back_to_weapons", "ws_finish", "ws_cancel", "finish_build",
               "restart_wizard", "close_session"):
        if not session or session.user_id != interaction.user.id:
            await interaction.response.send_message("❌ Sesja wygasla lub to nie Twoja sesja.", ephemeral=True)
            return True

        if cid == "mode_citizen":
            await interaction.response.defer()
            await send_step(interaction.channel, session, 0)
        elif cid == "mode_weapons":
            await interaction.response.defer()
            await interaction.channel.send(
                embed=discord.Embed(
                    title="🔫 Kreator skinow broni",
                    description="Wybierz bron z listy, potem preskakuj skiny strzalkami i wybieraj.",
                    color=COLOR_ORANGE,
                ),
                view=WeaponMenuView(),
            )
        elif cid == "ws_finish":
            await handle_finish_build(interaction, session)
        elif cid == "ws_back_to_weapons":
            await interaction.response.defer()
            await interaction.channel.send("🔫 Wybierz bron:", view=WeaponMenuView())
        elif cid == "ws_cancel":
            session.weapon_skins.clear()
            await interaction.response.send_message("✖️ Kreator skinow anulowany.", ephemeral=True)
        elif cid == "restart_wizard":
            session.choices.clear()
            await interaction.response.send_message("🔄 Od nowa!", ephemeral=True)
            await send_step(interaction.channel, session, 0)
        elif cid == "close_session":
            await interaction.response.send_message("🔒 Zamkam...", ephemeral=True)
            await cleanup_session(interaction, session, "Zamknieto przez uzytkownika")
        return True

    return False


# ==============================================================
#  RENDEROWANIE WIDOKÓW KREATORA
# ==============================================================

def build_step_embed(idx: int, chosen: bool) -> discord.Embed:
    step = STEPS[idx]
    embed = discord.Embed(
        title=f"Krok {idx + 1}/{len(STEPS)} — {step['name']}",
        description=(
            f"**{step['name']}**\n{step['description']}\n\n"
            f"{'✅ **Dodano do paczki.**' if chosen else '⬜ *Nie dodano.*'}"
        ),
        color=COLOR_GREEN if chosen else COLOR_BLUE,
    )
    embed.set_image(url=step["image"])
    return embed


def build_step_view(idx: int) -> View:
    view = View(timeout=None)
    view.add_item(StepButton("add", idx))
    view.add_item(StepButton("skip", idx))
    view.add_item(StepButton("remove", idx))
    view.add_item(JumpSelect(idx))
    return view


async def send_step(channel, session, idx: int):
    if idx >= len(STEPS):
        return await send_summary(channel, session)
    step = STEPS[idx]
    await channel.send(
        embed=build_step_embed(idx, step["id"] in session.choices),
        view=build_step_view(idx),
    )


async def send_summary(channel, session):
    chosen = [s for s in STEPS if s["id"] in session.choices]
    embed = discord.Embed(
        title="📋 Podsumowanie Twojego citizena",
        description="\n".join(f"✅ **{s['name']}**" for s in chosen) or "*Nie wybrano nic.*",
        color=COLOR_YELLOW,
    )
    await channel.send(embed=embed, view=SummaryView())


def build_skin_embed(weapon, idx: int, session) -> discord.Embed:
    skin = weapon["skins"][idx]
    is_chosen = session.weapon_skins.get(weapon["id"]) == skin["id"]
    embed = discord.Embed(
        title=f"🔫 {weapon['name']} — {skin['name']}",
        description=(
            f"**{skin['name']}** — {skin['description']}\n\n"
            f"{'✅ **Ten skin jest w Twojej paczce.**' if is_chosen else '⬜ *Nie wybrano.*'}"
        ),
        color=COLOR_GREEN if is_chosen else COLOR_ORANGE,
    )
    embed.set_image(url=skin["image"])
    return embed


def build_skin_view(weapon, idx: int) -> View:
    view = View(timeout=None)
    view.add_item(SkinSelect(weapon["id"]))
    view.add_item(SkinNavButton("prev", weapon["id"], idx))
    view.add_item(SkinNavButton("choose", weapon["id"], idx))
    view.add_item(SkinNavButton("next", weapon["id"], idx))
    return view


# ==============================================================
#  SETUP SERWERA / CLEANUP
# ==============================================================

async def cleanup_session(interaction, session, reason):
    guild = interaction.client.get_guild(session.guild_id)
    if guild:
        member = guild.get_member(session.user_id)
        role = discord.utils.get(guild.roles, name=ROLE_BUILDING)
        if member and role:
            try:
                await member.remove_roles(role)
            except discord.Forbidden:
                pass
        channel = guild.get_channel(session.channel_id)
        if channel:
            try:
                await asyncio.sleep(3)
                await channel.delete(reason=reason)
            except discord.Forbidden:
                pass
    SESSIONS.pop(session.channel_id, None)


async def _panel_exists(channel, custom_id: str) -> bool:
    """Sprawdza, czy bot juz wyslal panel z danym przyciskiem (unikanie duplikatow)."""
    async for msg in channel.history(limit=30):
        if msg.author == bot.user:
            for row in msg.components:
                for child in row.children:
                    if getattr(child, "custom_id", None) == custom_id:
                        return True
    return False


async def setup_guild(guild):
    """Buduje PELNA strukture serwera w stylu duzych hubow:
    📢 START (witaj, regulamin, ogloszenia)
    🛠️ CITIZEN MAKER (stworz-citizena, pobrane-paczki)
    🔫 SKIN MAKER (stworz-skin)
    📦 WSZYSTKIE MODY (najnowsze-mody, wszystkie-mody, pomoc)
    """
    log.info("⚙️ Buduje strukture serwera: %s", guild.name)

    # ---- Rola samo-przypisywalna (self-role) ----
    member_role = discord.utils.get(guild.roles, name=ROLE_MEMBER)
    if not member_role:
        member_role = await guild.create_role(name=ROLE_MEMBER, colour=discord.Colour(COLOR_BLUE))

    # ============================================
    # 📢 START — witaj / regulamin / ogloszenia
    # ============================================
    info_cat = discord.utils.get(guild.categories, name=CATEGORY_INFO)
    if not info_cat:
        info_cat = await guild.create_category(CATEGORY_INFO)

    welcome_ch = discord.utils.get(info_cat.text_channels, name=CH_WELCOME)
    if not welcome_ch:
        welcome_ch = await info_cat.create_text_channel(CH_WELCOME, topic="Witaj na serwerze! Zaznacz sie rola i korzystaj z kreatorow.")

    rules_ch = discord.utils.get(info_cat.text_channels, name=CH_RULES)
    if not rules_ch:
        rules_ch = await info_cat.create_text_channel(CH_RULES, topic="Regulamin serwera - zapoznaj sie obowiazkowo.")

    if not discord.utils.get(info_cat.text_channels, name=CH_ANNOUNCE):
        await info_cat.create_text_channel(CH_ANNOUNCE, topic="Wazne ogloszenia i aktualizacje bota.")

    # Embed powitalny + przycisk self-role
    if not await _panel_exists(welcome_ch, "take_role"):
        embed = discord.Embed(
            title=f"👋 Witaj na {guild.name}!",
            description=(
                "Twoje centrum modyfikacji do FiveM:\n\n"
                "🛠️ **CITIZEN MAKER** — buduj wlasna paczke citizena (opti, potato, mapy PvP),\n"
                "🔫 **SKIN MAKER** — personalizuj wyglad broni,\n"
                "📦 **WSZYSTKIE MODY** — najnowsze mody .rpf z YouTube, gotowe do folderu `mods`.\n\n"
                "Kliknij ponizej, aby zaznaczyc sie i korzystac z wszystkiego."
            ),
            color=COLOR_BLUE,
        )
        view = View(timeout=None)
        view.add_item(Button(label="Zaznacz sie (pobierz role)", style=discord.ButtonStyle.success, emoji="✅", custom_id="take_role"))
        await welcome_ch.send(embed=embed, view=view)

    # Regulamin
    if not await _panel_exists(rules_ch, "rules_posted"):
        rules_embed = discord.Embed(
            title="📜 Regulamin serwera",
            description=(
                "1. **Szanuj innych** — zero toksycznosci, rasizmu, hejtu.\n"
                "2. **Bez spamu** — nie flooduj kanalow i ticketow.\n"
                "3. **Mody na wlasna odpowiedzialnosc** — sprawdzaj regulamin serwera FiveM, na ktorym grasz.\n"
                "4. **Bez wirusow/scamow** — nie wrzucaj podejrzanych linkow (ban bez ostrzezenia).\n"
                "5. **Pomagaj sobie** — kanal #pomoc jest do dyspozycji spolecznosci.\n"
                "6. **Admin ma racje** — decyzje administracji sa ostateczne.\n\n"
                "Naruszenie regulaminu = mute/kick/ban."
            ),
            color=COLOR_YELLOW,
        )
        rules_embed.set_footer(text="Przyjecie regulaminu = wejscie na serwer.")
        await rules_ch.send(embed=rules_embed)

    # ============================================
    # 🛠️ CITIZEN MAKER
    # ============================================
    category = discord.utils.get(guild.categories, name=CATEGORY_MAIN)
    if not category:
        category = await guild.create_category(CATEGORY_MAIN)

    main_ch = discord.utils.get(category.text_channels, name=CH_MAIN)
    if not main_ch:
        main_ch = await category.create_text_channel(CH_MAIN, topic="Kliknij przycisk, aby rozpoczac tworzenie citizena.")

    if not discord.utils.get(category.text_channels, name=CH_DOWNLOADS):
        await category.create_text_channel(CH_DOWNLOADS, topic="Linki do gotowych paczek ZIP.")

    # ============================================
    # 🔫 SKIN MAKER
    # ============================================
    skins_cat = discord.utils.get(guild.categories, name=CATEGORY_SKINS)
    if not skins_cat:
        skins_cat = await guild.create_category(CATEGORY_SKINS)

    skins_ch = discord.utils.get(skins_cat.text_channels, name=CH_SKINS)
    if not skins_ch:
        skins_ch = await skins_cat.create_text_channel(CH_SKINS, topic="Kreator skinow broni - wybierz bron i skonfiguruj wyglad.")

    if not await _panel_exists(skins_ch, "create_weapon_skins"):
        embed = discord.Embed(
            title="🔫 Kreator Skinów Broni",
            description=(
                "Kliknij **„Stworz skiny broni\"**, aby uruchomic kreatora.\n\n"
                "Wybierasz bron (Pistol, AK-47 itd.), przegladasz skiny\n"
                "ze zdjeciami, a bot pakuje pliki do paczki ZIP\n"
                "gotowej do folderu `mods`."
            ),
            color=COLOR_ORANGE,
        )
        view = View(timeout=None)
        view.add_item(Button(label="Stworz skiny broni", style=discord.ButtonStyle.primary, emoji="🔫", custom_id="create_weapon_skins"))
        await skins_ch.send(embed=embed, view=view)

    # ============================================
    # 📦 WSZYSTKIE MODY
    # ============================================
    mods_cat = discord.utils.get(guild.categories, name=CATEGORY_MODS)
    if not mods_cat:
        mods_cat = await guild.create_category(CATEGORY_MODS)

    if not discord.utils.get(mods_cat.text_channels, name=CH_MODS):
        await mods_cat.create_text_channel(CH_MODS, topic="Najnowsze mody klienckie z YouTube (auto-skan co 30 min).")

    allmods_ch = discord.utils.get(mods_cat.text_channels, name=CH_ALL_MODS)
    if not allmods_ch:
        allmods_ch = await mods_cat.create_text_channel(CH_ALL_MODS, topic="Baza sprawdzonych modow - opti, potato, mapy PvP.")

    if not discord.utils.get(mods_cat.text_channels, name=CH_HELP):
        await mods_cat.create_text_channel(CH_HELP, topic="Masz problem z modem? Pisz tutaj.")

    # Panel 'wszystkie mody' - przycisk wymuszajacy skan dla kazdego
    if not await _panel_exists(allmods_ch, "scan_now"):
        embed = discord.Embed(
            title="📦 Jak wgrywac mody?",
            description=(
                "1. Znajdz mod na kanale **#najnowsze-mody** (auto z YouTube).\n"
                "2. Pobierz plik `.rpf` z linku z opisu filmu.\n"
                "3. Wrzuc do folderu **mods** w FiveM:\n"
                "   `FiveM.app/mods/nazwa_moda.rpf`\n"
                "4. Zrestartuj FiveM.\n\n"
                "⚠️ Mody klienckie dzialaja tylko na serwerach, ktore ich nie blokuja!"
            ),
            color=COLOR_GREEN,
        )
        view = View(timeout=None)
        view.add_item(Button(label="Sprawdz najnowsze mody", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="scan_now"))
        await allmods_ch.send(embed=embed, view=view)

    # Panel startowy - unikaj duplikatów
    async for msg in main_ch.history(limit=20):
        if msg.author == bot.user and any(c.custom_id == "create_citizen" for row in msg.components for c in row.children if hasattr(c, "custom_id")):
            break
    else:
        embed = discord.Embed(
            title="🛠️ Kreator Citizenów — FiveM",
            description=(
                "Kliknij **„Zacznij tworzyć citizena\"**, aby uruchomic kreatora.\n\n"
                "Bot stworzy prywatny kanal, na którym wybierzesz mody .rpf\n"
                "(opti, potato, mapy PvP, skiny broni), a nastepnie zbuduje\n"
                "gotowa paczke ZIP do folderu `mods` w FiveM."
            ),
            color=COLOR_BLUE,
        )
        await main_ch.send(embed=embed, view=PanelView())

    # Od razu skanuj i wrzuc najnowsze mody na kanal
    try:
        await scan_youtube_and_post(bot)
    except Exception:
        log.exception("Blad pierwszego skanu modow")


async def session_cleaner():
    await bot.wait_until_ready()
    while True:
        await asyncio.sleep(600)
        now = time.time()
        expired = [cid for cid, s in SESSIONS.items() if now - s.last_activity > SESSION_TTL_S]
        for cid in expired:
            SESSIONS.pop(cid, None)

        now = time.time()
        expired_dl = [t for t, d in PENDING_DOWNLOADS.items() if now - d["created_at"] > DOWNLOAD_TTL_S]
        for t in expired_dl:
            PENDING_DOWNLOADS.pop(t, None)


# ==============================================================
#  EVENTY I KOMENDY
# ==============================================================

@bot.event
async def on_interaction(interaction):
    """Router statycznych przycisków (te z trwałych widoków).

    Uwaga: standardowe discord.py NIE ma metod is_button()/is_select() na
    Interaction. Sprawdzamy typ interakcji i component_type z danych:
      - interaction.type == discord.InteractionType.component  (komponent UI)
      - interaction.data['component_type'] == 2 -> przycisk (Button)
      - interaction.data['component_type'] == 3 -> select (StringSelect)
      - interaction.type == discord.InteractionType.application_command -> komenda slash
    """
    # 1) Czy to interakcja komponentu (przycisk/select) w ogóle?
    if interaction.type != discord.InteractionType.component:
        return

    data = interaction.data or {}
    component_type = data.get("component_type")

    # 2) Reagujemy tylko na przyciski (2). Selecty (3+) mają własne callbacki
    #    w klasach DynamicItem/Select - tu ich nie ruszamy.
    if component_type != 2:
        return

    try:
        cid = data.get("custom_id", "")
        # Dynamiczne (step_*, ws_*) mają własne callbacki - tu tylko statyczne.
        if cid.startswith("step_") or cid.startswith("ws_skin_select"):
            return
        await handle_static_button(interaction)
    except Exception:
        log.exception("Blad interakcji")
        try:
            if interaction.response.is_done():
                await interaction.followup.send("❌ Blad.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Blad.", ephemeral=True)
        except Exception:
            pass


@bot.event
async def on_guild_join(guild):
    try:
        await setup_guild(guild)
    except Exception:
        log.exception("Blad konfiguracji serwera %s", guild.name)


@bot.event
async def on_ready():
    log.info("🤖 Zalogowano jako %s (bot dziala)", bot.user)
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Kreator Citizenow FiveM"))
    for guild in bot.guilds:
        try:
            await setup_guild(guild)
        except Exception:
            log.exception("Blad konfiguracji serwera %s", guild.name)


@tree.command(name="panel", description="Wysyla panel kreatora na biezacy kanal")
@app_commands.default_permissions(administrator=True)
async def cmd_panel(interaction):
    embed = discord.Embed(
        title="🛠️ Kreator Citizenów — FiveM",
        description="Kliknij przycisk ponizej, aby rozpoczac.",
        color=COLOR_BLUE,
    )
    await interaction.response.send_message(embed=embed, view=PanelView())


@tree.command(name="zamknij", description="Zamyka sesje kreatora na tym kanale")
async def cmd_zamknij(interaction):
    session = get_session(interaction.channel_id)
    if not session:
        return await interaction.response.send_message("❌ To nie jest kanal sesji.", ephemeral=True)
    await interaction.response.send_message("🔒 Zamkanie sesji...")
    await cleanup_session(interaction, session, "Zamknieto komenda /zamknij")


@tree.command(name="skanuj", description="Reczne uruchomienie skanera najnowszych modow z YouTube")
@app_commands.default_permissions(administrator=True)
async def cmd_skanuj(interaction):
    await interaction.response.defer()
    count = await scan_youtube_and_post(bot)
    await interaction.followup.send(f"✅ Skan zakonczony — wrzucono {count} nowych filmow.")


def setup_hook_impl():
    """Rejestracja trwałych widoków i dynamicznych itemów + sync komend."""
    bot.add_view(PanelView())
    bot.add_view(ModeView())
    bot.add_view(SummaryView())
    bot.add_view(CloseChannelView())
    bot.add_view(WeaponMenuView())
    bot.add_view(SkinFinishView())
    bot.add_dynamic_items(StepButton, JumpSelect, SkinNavButton, SkinSelect)


async def _real_setup_hook():
    setup_hook_impl()
    await tree.sync()
    log.info("✅ Komendy zsynchronizowane, trwale widoki zarejestrowane.")


bot.setup_hook = _real_setup_hook


# ==============================================================
#  START
# ==============================================================

if not DISCORD_TOKEN:
    raise SystemExit("❌ Brak DISCORD_TOKEN! Utworz plik .env (wzor: .env.example).")

async def main():
    async with bot:
        await bot.login(DISCORD_TOKEN)
        asyncio.create_task(session_cleaner())
        asyncio.create_task(yt_scanner_loop(bot))
        await start_http_server()  # fire-and-forget (aiohttp AppRunner trzyma petle zywa)
        await bot.connect()


asyncio.run(main())
