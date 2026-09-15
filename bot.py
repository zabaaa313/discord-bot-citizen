"""
Kreator Citizenów do FiveM — Bot Discord (discord.py)

Funkcje:
- Auto-konfiguracja serwera (role, kategorie, kanały, panel z przyciskiem)
- Kanał #mody-optymalizacja z bazą sprawdzonych modów + weryfikacja linków
- Prywatne kanały (tickety) per użytkownik
- Kreator citizena krok po kroku (embedy ze zdjęciami, przyciski)
- Kreator skinów broni (select menu, galeria skinów)
- Pobieranie plików, budowa struktury citizen, pakowanie ZIP
- Serwer HTTP z linkami do pobierania paczek

Uruchomienie:  python bot.py   (konfiguracja w .env, wzór: .env.example)
"""

import asyncio
import io
import json
import logging
import os
import secrets
import zipfile
import shutil
import ssl
import tempfile
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field

import discord
from discord import app_commands
from dotenv import load_dotenv

# ==============================================================
#  KONFIGURACJA
# ==============================================================

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
HTTP_PORT = int(os.getenv("HTTP_PORT", "3000"))
PUBLIC_URL = os.getenv("PUBLIC_URL") or f"http://localhost:{HTTP_PORT}"

ROLE_CREATOR = "Creator"
ROLE_BUILDING = "Tworzenie citizena"
CATEGORY_MAIN = "FIVEM CITIZEN CREATOR"
CATEGORY_TICKETS = "TWOJE CITIZENY"
CH_MAIN = "stworz-citizena"
CH_DOWNLOADS = "pobrane-paczki"
CH_MODS = "mody-optymalizacja"

SESSION_TTL_S = 2 * 60 * 60          # sesje wygasają po 2h
DOWNLOAD_TTL_S = 24 * 60 * 60        # paczki ZIP dostępne 24h
MODS_CHECK_INTERVAL_S = 6 * 60 * 60  # weryfikacja linków modów co 6h
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024  # limit pojedynczego pobrania (200 MB)

COLOR_BLUE = 0x5865F2
COLOR_GREEN = 0x57F287
COLOR_YELLOW = 0xFEE75C
COLOR_ORANGE = 0xE67E22

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("citizen-bot")

DOWNLOADS_DIR = "downloads"
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


# ==============================================================
#  BAZA KROKÓW KREATORA CITIZENA
#  (image/fileUrl - PODMIEŃ na własne, zweryfikowane linki!)
# ==============================================================

STEPS = [
    {
        "id": "sky",
        "name": "Niebo",
        "description": "Zmienia wygląd nieba - bardziej realistyczne, ciemniejsze nocne niebo.",
        "image": "https://i.imgur.com/ZMIJFjr.jpeg",  # PODMIEŃ
        "mode": "file",
        "fileUrl": "https://example.com/mods/timecycle_mod_1.xml",  # PODMIEŃ
        "fileName": "timecycle_mod_1.xml",
        "target": "citizen/common/data/timecycle",
    },
    {
        "id": "shadows",
        "name": "Usunięcie cieni",
        "description": "Wyłącza cienie dynamiczne - większy FPS na słabszych PC.",
        "image": "https://i.imgur.com/SHADOW1.jpeg",  # PODMIEŃ
        "mode": "file",
        "fileUrl": "https://example.com/mods/shaders.xml",  # PODMIEŃ
        "fileName": "shaders.xml",
        "target": "citizen/common/data",
    },
    {
        "id": "water",
        "name": "Woda",
        "description": "Czystsza, bardziej przezroczysta woda.",
        "image": "https://i.imgur.com/WATER1.jpeg",  # PODMIEŃ
        "mode": "file",
        "fileUrl": "https://example.com/mods/water.xml",  # PODMIEŃ
        "fileName": "water.xml",
        "target": "citizen/common/data/levels/gta5",
    },
    {
        "id": "blood",
        "name": "Krew",
        "description": "Realistyczny efekt krwi.",
        "image": "https://i.imgur.com/BLOOD1.jpeg",  # PODMIEŃ
        "mode": "file",
        "fileUrl": "https://example.com/mods/bloodfx.dat",  # PODMIEŃ
        "fileName": "bloodfx.dat",
        "target": "citizen/common/data/effects/pc",
    },
]

# ==============================================================
#  BAZA MODÓW OPTYMALIZACYJNYCH (kanał #mody-optymalizacja)
#  Bot NIE przeszukuje internetu sam - linki wstawiasz po ręcznej
#  weryfikacji (GitHub, gta5-mods.com, forum.cfx.re), a bot co 6h
#  sprawdza automatycznie, czy linki jeszcze żyją.
# ==============================================================

OPTIMIZATION_MODS = [
    {
        "id": "fps-boost-pack",
        "name": "FPS Boost Pack (tymczasowo przykładowy wpis)",
        "description": "Zestaw poprawek timecycle i draw distance zwiększający FPS na średnich PC.",
        "fpsImpact": "+10-25 FPS na średnich konfiguracjach",
        "pageUrl": "https://www.gta5-mods.com/misc/fps-boost-pack",  # PODMIEŃ
        "thumbnail": "https://i.imgur.com/ZMIJFjr.jpeg",  # PODMIEŃ
        "author": "—",
    },
    {
        "id": "no-shadows",
        "name": "No Dynamic Shadows (tymczasowo przykładowy wpis)",
        "description": "Wyłącza cienie dynamiczne - duży zysk FPS na słabszych kartach.",
        "fpsImpact": "+15-30 FPS na GPU klasy GTX 1050",
        "pageUrl": "https://www.gta5-mods.com/misc/no-dynamic-shadows",  # PODMIEŃ
        "thumbnail": "https://i.imgur.com/SHADOW1.jpeg",  # PODMIEŃ
        "author": "—",
    },
]

# ==============================================================
#  BAZA BRONI I SKINÓW (kreator skinów broni)
# ==============================================================

WEAPONS = [
    {
        "id": "pistol",
        "name": "Pistol",
        "skins": [
            {
                "id": "pistol-blackops",
                "name": "Black Ops",
                "description": "Czarny matowy skin z zielonymi akcentami.",
                "image": "https://i.imgur.com/SKIN1.jpeg",  # PODMIEŃ
                "fileUrl": "https://example.com/skins/w_pistol_blackops.ytd",  # PODMIEŃ
                "fileName": "w_pi_pistol.ytd",
                "target": "citizen/common.rpf/data/props/weapons",
            },
            {
                "id": "pistol-desert",
                "name": "Desert Tan",
                "description": "Pustynny kamuflaż.",
                "image": "https://i.imgur.com/SKIN2.jpeg",  # PODMIEŃ
                "fileUrl": "https://example.com/skins/w_pistol_desert.ytd",  # PODMIEŃ
                "fileName": "w_pi_pistol.ytd",
                "target": "citizen/common.rpf/data/props/weapons",
            },
        ],
    },
    {
        "id": "heavypistol",
        "name": "Heavy Pistol",
        "skins": [
            {
                "id": "heavypistol-chrome",
                "name": "Chrome",
                "description": "Chromowany połysk.",
                "image": "https://i.imgur.com/SKIN3.jpeg",  # PODMIEŃ
                "fileUrl": "https://example.com/skins/w_heavypistol_chrome.ytd",  # PODMIEŃ
                "fileName": "w_pi_histol.ytd",
                "target": "citizen/common.rpf/data/props/weapons",
            },
        ],
    },
    {
        "id": "appistol",
        "name": "AP Pistol",
        "skins": [
            {
                "id": "appistol-carbon",
                "name": "Carbon Fiber",
                "description": "Węglowy wzór.",
                "image": "https://i.imgur.com/SKIN4.jpeg",  # PODMIEŃ
                "fileUrl": "https://example.com/skins/w_appistol_carbon.ytd",  # PODMIEŃ
                "fileName": "w_pi_ap_pistol.ytd",
                "target": "citizen/common.rpf/data/props/weapons",
            },
        ],
    },
    {
        "id": "carbine",
        "name": "Carbine Rifle",
        "skins": [
            {
                "id": "carbine-woodland",
                "name": "Woodland",
                "description": "Leśny kamuflaż.",
                "image": "https://i.imgur.com/SKIN5.jpeg",  # PODMIEŃ
                "fileUrl": "https://example.com/skins/w_carbine_woodland.ytd",  # PODMIEŃ
                "fileName": "w_ar_carbine.ytd",
                "target": "citizen/common.rpf/data/props/weapons",
            },
        ],
    },
    {
        "id": "ak47",
        "name": "AK-47 (Assault Rifle)",
        "skins": [
            {
                "id": "ak47-redline",
                "name": "Redline",
                "description": "Czerwone linie na czerni.",
                "image": "https://i.imgur.com/SKIN6.jpeg",  # PODMIEŃ
                "fileUrl": "https://example.com/skins/w_ak47_redline.ytd",  # PODMIEŃ
                "fileName": "w_ar_assaultrifle.ytd",
                "target": "citizen/common.rpf/data/props/weapons",
            },
        ],
    },
]


# ==============================================================
#  SESJE KREATORA (w pamięci)
# ==============================================================

@dataclass
class Session:
    user_id: int
    guild_id: int
    channel_id: int
    choices: dict = field(default_factory=dict)        # step_id -> True
    weapon_skins: dict = field(default_factory=dict)   # weapon_id -> skin_id
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)


SESSIONS: dict[int, Session] = {}  # channel_id -> Session


def get_session(channel_id: int) -> Session | None:
    s = SESSIONS.get(channel_id)
    if s:
        s.last_activity = time.time()
    return s


async def session_cleaner():
    """Usuwa wygasłe sesje (2h bezczynności)."""
    while True:
        await asyncio.sleep(600)
        now = time.time()
        expired = [cid for cid, s in SESSIONS.items() if now - s.last_activity > SESSION_TTL_S]
        for cid in expired:
            SESSIONS.pop(cid, None)
            log.info("Wygasła sesja na kanale %s", cid)


# ==============================================================
#  POBIERANIE PLIKÓW + PAKOWANIE ZIP
# ==============================================================

def download_file(url: str, dest_path: str) -> None:
    """Pobiera plik z URL (obsługa przekierowań, limit rozmiaru)."""
    req = urllib.request.Request(url, headers={"User-Agent": "FiveMCitizenBot/1.0"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp, open(dest_path, "wb") as out:
        received = 0
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            received += len(chunk)
            if received > MAX_DOWNLOAD_BYTES:
                raise ValueError("Plik przekracza limit rozmiaru")
            out.write(chunk)


def build_citizen_zip(session: Session, chosen: list[dict]) -> tuple[str, bytes, int]:
    """
    Buduje strukturę citizen w pamięci, pobiera pliki i pakuje do ZIP.
    Zwraca (token, zawartość_zip, liczba_plików).
    """
    token = secrets.token_hex(16)
    buf = io.BytesIO()
    file_count = 0
    tmpdir = tempfile.mkdtemp(prefix="citizen-")
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for step in chosen:
                target = step["target"].rstrip("/") + "/"
                if step.get("mode") == "resource":
                    # ZIP z modem: pobierz do tmp i rozpakuj do struktury
                    tmp_zip = os.path.join(tmpdir, "mod.zip")
                    download_file(step["fileUrl"], tmp_zip)
                    with zipfile.ZipFile(tmp_zip) as mz:
                        for name in mz.namelist():
                            if name.endswith("/"):
                                continue
                            data = mz.read(name)
                            inner = name.split("/", 1)[1] if "/" in name else name
                            zf.writestr(target + inner, data)
                            file_count += 1
                else:
                    data = _download_bytes(step["fileUrl"])
                    zf.writestr(target + step["fileName"], data)
                    file_count += 1

            # Instrukcja instalacji
            instrukcja = [
                "=== TWOJA PACZKA CITIZEN ===",
                f"Wygenerowano: {time.strftime('%Y-%m-%d %H:%M:%S')}",
                "",
                "Wybrane modyfikacje:",
                *[f" - {s['name']}: {s.get('description', '')}" for s in chosen],
                "",
                "Instalacja:",
                "1. Rozpakuj pliki do folderu FiveM (zachowaj strukturę folderów).",
                "2. Uruchom ponownie FiveM.",
            ]
            zf.writestr("INSTRUKCJA.txt", "\n".join(instrukcja))
            file_count += 1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return token, buf.getvalue(), file_count


def _download_bytes(url: str) -> bytes:
    """Pobiera plik do pamięci (dla małych plików tekstowych)."""
    req = urllib.request.Request(url, headers={"User-Agent": "FiveMCitizenBot/1.0"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
        data = resp.read(MAX_DOWNLOAD_BYTES + 1)
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ValueError("Plik przekracza limit rozmiaru")
    return data


# Magazyn paczek: token -> { data, fileName, created_at }
PENDING_DOWNLOADS: dict[str, dict] = {}


async def downloads_cleaner():
    """Usuwa wygasłe paczki ZIP (24h)."""
    while True:
        await asyncio.sleep(1800)
        now = time.time()
        expired = [t for t, d in PENDING_DOWNLOADS.items() if now - d["created_at"] > DOWNLOAD_TTL_S]
        for t in expired:
            PENDING_DOWNLOADS.pop(t, None)
            log.info("Usunięto wygasłą paczkę %s", t)


# ==============================================================
#  SERWER HTTP (linki do pobierania paczek)
# ==============================================================

async def handle_download(request):
    from aiohttp import web

    token = request.match_info["token"]
    dl = PENDING_DOWNLOADS.get(token)
    if not dl:
        return web.Response(status=404, text="404: Paczka nie istnieje lub wygasła.")
    return web.Response(
        body=dl["data"],
        content_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{dl["fileName"]}"'},
    )


async def handle_health(request):
    from aiohttp import web

    return web.Response(text="ok")


async def start_http_server():
    from aiohttp import web

    app = web.Application()
    app.router.add_get("/download/{token}", handle_download)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HTTP_PORT)
    await site.start()
    log.info("🌐 Serwer HTTP na porcie %s (paczki: %s/download/<token>)", HTTP_PORT, PUBLIC_URL)


# ==============================================================
#  WERYFIKACJA LINKÓW MODÓW
# ==============================================================

MODS_HEALTH: dict[str, dict] = {}  # mod_id -> { ok, status, checked_at }


def check_url(url: str) -> dict:
    """HEAD request z fallbackiem GET - czy link żyje."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FiveMCitizenBot/1.0"})
        ctx = ssl.create_default_context()
        # HEAD bywa blokowany przez hostingi - fallback na GET z ograniczeniem
        method = "HEAD"
        for _ in range(2):
            try:
                req2 = urllib.request.Request(url, method=method, headers={"User-Agent": "FiveMCitizenBot/1.0"})
                with urllib.request.urlopen(req2, timeout=10, context=ctx) as resp:
                    return {"ok": True, "status": resp.status}
            except urllib.error.HTTPError as e:
                if e.code in (301, 302, 303, 307, 308):
                    # urllib sam obsługuje redirecty przy GET
                    method = "GET"
                    continue
                return {"ok": False, "status": e.code}
        return {"ok": False, "status": 0}
    except Exception:
        return {"ok": False, "status": 0}


async def verify_all_mods():
    for mod in OPTIMIZATION_MODS:
        result = await asyncio.to_thread(check_url, mod["pageUrl"])
        MODS_HEALTH[mod["id"]] = {**result, "checked_at": time.time()}
        if not result["ok"]:
            log.warning("⚠️  Mod '%s' - link nieosiągalny (HTTP %s)", mod["name"], result["status"])


# ==============================================================
#  BOT DISCORD
# ==============================================================

intents = discord.Intents.default()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


# ---------- PANEL I KONFIGURACJA SERWERA ----------

def build_panel() -> tuple[discord.Embed, discord.ui.View]:
    embed = discord.Embed(
        title="🛠️ Kreator Citizenów — FiveM",
        description=(
            "Kliknij **„Zacznij tworzyć citizena\"** poniżej, aby uruchomić kreatora.\n\n"
            "Bot stworzy prywatny kanał, na którym krok po kroku wybierzesz modyfikacje\n"
            "(niebo, cienie, woda, krew itp.), a następnie automatycznie pobierze pliki\n"
            "i zbuduje gotową paczkę `.zip` do wgrania do FiveM."
        ),
        color=COLOR_BLUE,
        timestamp=discord.utils.utcnow(),
    )
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(
        label="Zacznij tworzyć citizena", style=discord.ButtonStyle.primary,
        emoji="🛠️", custom_id="create_citizen",
    ))
    return embed, view


async def setup_guild(guild: discord.Guild):
    log.info("⚙️  Konfiguracja serwera: %s", guild.name)

    # Role
    creator_role = discord.utils.get(guild.roles, name=ROLE_CREATOR)
    if not creator_role:
        creator_role = await guild.create_role(name=ROLE_CREATOR, colour=discord.Colour(COLOR_BLUE), reason="Auto-konfiguracja")
    building_role = discord.utils.get(guild.roles, name=ROLE_BUILDING)
    if not building_role:
        await guild.create_role(name=ROLE_BUILDING, colour=discord.Colour(COLOR_GREEN), reason="Auto-konfiguracja")

    # Kategoria + kanały
    category = discord.utils.get(guild.categories, name=CATEGORY_MAIN)
    if not category:
        category = await guild.create_category(CATEGORY_MAIN)

    main_channel = discord.utils.get(category.text_channels, name=CH_MAIN)
    if not main_channel:
        main_channel = await category.create_text_channel(
            CH_MAIN, topic="Kliknij przycisk poniżej, aby rozpocząć tworzenie własnego citizena."
        )

    downloads_channel = discord.utils.get(category.text_channels, name=CH_DOWNLOADS)
    if not downloads_channel:
        await category.create_text_channel(CH_DOWNLOADS, topic="Bot publikuje tutaj linki do pobrania gotowych paczek.")

    # Kanał modów optymalizacyjnych
    await setup_mods_channel(guild, category)

    # Panel startowy
    embed, view = build_panel()
    async for msg in main_channel.history(limit=10):
        if msg.author == bot.user and msg.embeds and "Kreator Citizenów" in (msg.embeds[0].title or ""):
            break
    else:
        await main_channel.send(embed=embed, view=view)

    log.info("✅ Konfiguracja serwera %s zakończona.", guild.name)


# ---------- KANAŁ MODÓW OPTYMALIZACYJNYCH ----------

async def setup_mods_channel(guild: discord.Guild, category: discord.CategoryChannel | None):
    mods_channel = discord.utils.get(category.text_channels, name=CH_MODS) if category else None
    if not mods_channel:
        mods_channel = await guild.create_text_channel(
            CH_MODS,
            topic="Sprawdzone mody optymalizacyjne (klienckie) do FiveM - tylko pliki do folderu gry.",
            category=category,
        )
    await verify_all_mods()
    await post_mods_list(mods_channel)


async def post_mods_list(channel: discord.TextChannel):
    """Wysyła (po czyszczeniu) listę modów na kanale."""
    try:
        async for msg in channel.history(limit=100):
            if msg.author == bot.user:
                await msg.delete()
    except discord.Forbidden:
        pass

    header = discord.Embed(
        title="⚡ Mody optymalizacyjne — FiveM (klient)",
        description=(
            "Poniżej **zweryfikowane** mody klienckie - pliki wgrywane do folderu gry\n"
            "(`mods` / `citizen`), **nie** skrypty serwerowe.\n\n"
            "🔗 Każdy link prowadzi do **strony moda** (stabilny URL, nie wygasa).\n"
            f"🕒 Ostatnia weryfikacja linków: <t:{int(time.time())}:R>"
        ),
        color=COLOR_BLUE,
    )
    await channel.send(embed=header)

    for mod in OPTIMIZATION_MODS:
        health = MODS_HEALTH.get(mod["id"], {"ok": True, "status": 0})
        emoji = "✅" if health["ok"] else "⚠️"
        embed = discord.Embed(
            title=f"{emoji} {mod['name']}",
            description=mod["description"],
            color=COLOR_GREEN if health["ok"] else COLOR_YELLOW,
        )
        embed.add_field(name="📈 Wpływ na FPS", value=mod["fpsImpact"], inline=True)
        embed.add_field(name="🏷️ Typ", value="Klient (folder gry)", inline=True)
        embed.add_field(name="👤 Autor", value=mod["author"], inline=True)
        embed.set_thumbnail(url=mod["thumbnail"])
        footer = "Link zweryfikowany przez bota" if health["ok"] else f"⚠️ Link nieosiągalny (HTTP {health['status']})"
        embed.set_footer(text=footer)
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Pobierz ze strony", style=discord.ButtonStyle.link, url=mod["pageUrl"]))
        await channel.send(embed=embed, view=view)


async def mods_refresher():
    """Cykliczna weryfikacja linków + odświeżanie kanałów modów."""
    await bot.wait_until_ready()
    while True:
        await asyncio.sleep(MODS_CHECK_INTERVAL_S)
        try:
            await verify_all_mods()
            for guild in bot.guilds:
                category = discord.utils.get(guild.categories, name=CATEGORY_MAIN)
                mods_channel = discord.utils.get(category.text_channels, name=CH_MODS) if category else None
                if mods_channel:
                    await post_mods_list(mods_channel)
        except Exception as e:
            log.error("Błąd odświeżania modów: %s", e)


# ---------- TICKETY (prywatne kanały) ----------

async def create_ticket_channel(interaction: discord.Interaction) -> Session:
    guild = interaction.guild
    user = interaction.user

    building_role = discord.utils.get(guild.roles, name=ROLE_BUILDING)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True, attach_files=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            attach_files=True, manage_messages=True,
        ),
    }
    if building_role:
        overwrites[building_role] = discord.PermissionOverwrite(view_channel=False)

    safe_name = "".join(c if c.isalnum() or c == "-" else "-" for c in user.name.lower())[:20]
    tickets_cat = discord.utils.get(guild.categories, name=CATEGORY_TICKETS)
    channel = await guild.create_text_channel(
        f"citizen-{safe_name}",
        overwrites=overwrites,
        category=tickets_cat,
    )
    if building_role:
        try:
            await user.add_roles(building_role, reason="Sesja tworzenia citizena")
        except discord.Forbidden:
            pass

    session = Session(user_id=user.id, guild_id=guild.id, channel_id=channel.id)
    SESSIONS[channel.id] = session
    return channel, session


async def send_mode_selection(channel: discord.TextChannel, session: Session):
    """Powitanie + wybór trybu: citizen albo skiny broni."""
    embed = discord.Embed(
        title=f"👋 Cześć <@{session.user_id}>!",
        description=(
            "To Twój **prywatny kanał kreatora**.\n\n"
            "Wybierz co chcesz stworzyć:\n"
            "🛠️ **Citizen** — modyfikacje wizualne (niebo, cienie, woda, krew...),\n"
            "🔫 **Skiny broni** — personalizacja wyglądu broni (.ytd/.ydr).\n\n"
            "**Możesz w każdej chwili przerwać** — użyj `/zamknij`."
        ),
        color=COLOR_GREEN,
    )
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Citizen (mody wizualne)", style=discord.ButtonStyle.primary, emoji="🛠️", custom_id="mode_citizen"))
    view.add_item(discord.ui.Button(label="Skiny broni", style=discord.ButtonStyle.secondary, emoji="🔫", custom_id="mode_weapons"))
    await channel.send(embed=embed, view=view)


async def cleanup_session(bot_client, session: Session, reason: str):
    guild = bot_client.get_guild(session.guild_id)
    if guild:
        building_role = discord.utils.get(guild.roles, name=ROLE_BUILDING)
        member = guild.get_member(session.user_id)
        if building_role and member:
            try:
                await member.remove_roles(building_role, reason="Koniec sesji")
            except discord.Forbidden:
                pass
        channel = guild.get_channel(session.channel_id)
        if channel:
            try:
                await channel.send(f"🔒 Sesja zakończona: {reason}")
                await asyncio.sleep(3)
                await channel.delete(reason="Koniec sesji kreatora citizena")
            except discord.Forbidden:
                pass
    SESSIONS.pop(session.channel_id, None)


# ---------- KREATOR CITIZENA (krok po kroku) ----------

def build_step_embed(step: dict, index: int, chosen: bool) -> discord.Embed:
    embed = discord.Embed(
        title=f"Krok {index + 1}/{len(STEPS)} — {step['name']}",
        description=f"**{step['name']}**\n{step['description']}\n\n{'✅ **Dodano do paczki.**' if chosen else '⬜ *Nie dodano.*'}",
        color=COLOR_GREEN if chosen else COLOR_BLUE,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_image(url=step["image"])
    embed.set_footer(text="Wybierz akcję poniżej")
    return embed


def build_step_view(index: int, chosen: bool) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    step_id = STEPS[index]["id"]
    view.add_item(discord.ui.Button(
        label="Dodano ✓ (kliknij, aby usunąć)" if chosen else "Dodaj to",
        style=discord.ButtonStyle.success if chosen else discord.ButtonStyle.primary,
        emoji="➕", custom_id=f"step_add:{index}",
    ))
    view.add_item(discord.ui.Button(label="Pomiń", style=discord.ButtonStyle.secondary, emoji="⏭️", custom_id=f"step_skip:{index}"))
    view.add_item(discord.ui.Button(label="Usuń z paczki", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id=f"step_remove:{index}"))
    return view


def build_step_jump_view(current: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    options = [
        discord.SelectOption(label=f"{i + 1}. {s['name']}", value=str(i), default=(i == current))
        for i, s in enumerate(STEPS)
    ]
    select = discord.ui.Select(placeholder="Przeskocz do innego kroku...", options=options, custom_id="step_jump")
    view.add_item(select)
    return view


async def send_step(channel: discord.TextChannel, session: Session, index: int):
    if index >= len(STEPS):
        return await send_summary(channel, session)
    step = STEPS[index]
    chosen = step["id"] in session.choices
    await channel.send(
        embed=build_step_embed(step, index, chosen),
        view=build_step_view(index, chosen),
    )


async def send_summary(channel: discord.TextChannel, session: Session):
    chosen_steps = [s for s in STEPS if s["id"] in session.choices]
    embed = discord.Embed(
        title="📋 Podsumowanie Twojego citizena",
        description=(
            "\n".join(f"✅ **{s['name']}** — {s['description']}" for s in chosen_steps)
            or "*Nie wybrano żadnej modyfikacji.*"
        ),
        color=COLOR_YELLOW,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text="Kliknij „Zakończ tworzenie\", aby zbudować paczkę ZIP.")

    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Zakończ tworzenie", style=discord.ButtonStyle.success, emoji="📦", custom_id="finish_build"))
    view.add_item(discord.ui.Button(label="Zacznij od nowa", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="restart_wizard"))
    view.add_item(discord.ui.Button(label="Zamknij", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_session"))
    await channel.send(embed=embed, view=view)


async def finish_build(interaction: discord.Interaction, session: Session, chosen: list[dict]):
    """Buduje paczkę i wysyła link."""
    await interaction.response.defer()
    try:
        token, zip_data, file_count = await asyncio.to_thread(build_citizen_zip, session, chosen)
        file_name = f"citizen-{session.user_id}-{int(time.time())}.zip"
        PENDING_DOWNLOADS[token] = {"data": zip_data, "fileName": file_name, "created_at": time.time()}
        link = f"{PUBLIC_URL}/download/{token}"

        embed = discord.Embed(
            title="✅ Twoja paczka jest gotowa!",
            description=(
                f"**Pobierz paczkę:** [{file_name}]({link})\n\n"
                f"📦 Rozmiar: **{len(zip_data) / 1024 / 1024:.2f} MB**\n"
                f"🕒 Link ważny: **24 godziny**\n"
                f"📁 Zawartość: {file_count} plik(ów)\n\n"
                "**Jak zainstalować:**\n"
                "1. Pobierz paczkę ZIP.\n"
                "2. Rozpakuj do folderu `mods` w FiveM (lub wg instrukcji w paczce).\n"
                "3. Uruchom ponownie FiveM."
            ),
            color=COLOR_GREEN,
            timestamp=discord.utils.utcnow(),
        )
        await interaction.followup.send(embed=embed)

        # Publikacja na kanale pobranych paczek
        guild = interaction.guild
        downloads_ch = discord.utils.get(
            discord.utils.get(guild.categories, name=CATEGORY_MAIN).text_channels,
            name=CH_DOWNLOADS,
        ) if discord.utils.get(guild.categories, name=CATEGORY_MAIN) else None
        if downloads_ch:
            await downloads_ch.send(content=f"<@{session.user_id}> Twoja paczka: {link}")

        close_view = discord.ui.View(timeout=None)
        close_view.add_item(discord.ui.Button(label="Zamknij kanał", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_session"))
        await interaction.channel.send(content="Gotowe! Kliknij poniżej, aby zamknąć ten kanał.", view=close_view)
    except Exception as e:
        log.exception("Błąd budowania paczki")
        await interaction.followup.send(f"❌ Błąd budowania paczki: {e}")


# ---------- KREATOR SKINÓW BRONI ----------

async def send_weapon_select(channel: discord.TextChannel, session: Session):
    embed = discord.Embed(
        title="🔫 Kreator skinów broni — wybierz broń",
        description=(
            "Z listy poniżej wybierz broń, dla której chcesz dobrać skin.\n"
            "Po wyborze zobaczysz dostępne skiny ze zdjęciami poglądowymi.\n\n"
            "💡 Możesz zmodyfikować wiele broni — po prostu wracaj do tego menu."
        ),
        color=COLOR_ORANGE,
    )
    options = [
        discord.SelectOption(label=w["name"], value=w["id"], description=f"{len(w['skins'])} skin(ów) dostępnych")
        for w in WEAPONS
    ]
    select = discord.ui.Select(placeholder="Wybierz broń...", options=options, custom_id="ws_weapon_select")
    view = discord.ui.View(timeout=None)
    view.add_item(select)
    view.add_item(discord.ui.Button(label="Zakończ i zbuduj paczkę", style=discord.ButtonStyle.success, emoji="📦", custom_id="ws_finish"))
    view.add_item(discord.ui.Button(label="Anuluj kreatora skinów", style=discord.ButtonStyle.danger, emoji="✖️", custom_id="ws_cancel"))
    await channel.send(embed=embed, view=view)


def build_skin_embed(weapon: dict, skin_index: int, chosen_skin_id: str | None) -> discord.Embed:
    skin = weapon["skins"][skin_index]
    is_chosen = chosen_skin_id == skin["id"]
    embed = discord.Embed(
        title=f"🔫 {weapon['name']} — {skin['name']}",
        description=(
            f"**{skin['name']}** — {skin['description']}\n\n"
            f"{'✅ **Ten skin jest w Twojej paczce.**' if is_chosen else '⬜ *Nie wybrano.*'}"
        ),
        color=COLOR_GREEN if is_chosen else COLOR_ORANGE,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_image(url=skin["image"])
    return embed


def build_skin_nav_view(weapon: dict, skin_index: int, chosen: bool) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    wid = weapon["id"]
    skin = weapon["skins"][skin_index]
    view.add_item(discord.ui.Button(label="◀ Wróć", style=discord.ButtonStyle.secondary, custom_id=f"ws_prev:{wid}:{skin_index}"))
    view.add_item(discord.ui.Button(
        label="Wybrano ✓" if chosen else "Wybierz ten skin",
        style=discord.ButtonStyle.success if chosen else discord.ButtonStyle.primary,
        emoji="✅", custom_id=f"ws_choose:{wid}:{skin_index}",
    ))
    view.add_item(discord.ui.Button(label="Dalej ▶", style=discord.ButtonStyle.secondary, custom_id=f"ws_next:{wid}:{skin_index}"))
    return view


def build_skin_finish_view() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="← Inna broń", style=discord.ButtonStyle.secondary, emoji="🔫", custom_id="ws_back_to_weapons"))
    view.add_item(discord.ui.Button(label="Zakończ i zbuduj paczkę", style=discord.ButtonStyle.success, emoji="📦", custom_id="ws_finish"))
    return view


async def send_skin_gallery(channel: discord.TextChannel, session: Session, weapon: dict):
    chosen_skin_id = session.weapon_skins.get(weapon["id"])
    skin_index = 0
    if chosen_skin_id:
        for i, s in enumerate(weapon["skins"]):
            if s["id"] == chosen_skin_id:
                skin_index = i
                break

    # Menu wyboru skina + nawigacja
    menu_view = discord.ui.View(timeout=None)
    options = [
        discord.SelectOption(label=s["name"], value=s["id"], description=s["description"][:100], default=(s["id"] == chosen_skin_id))
        for s in weapon["skins"]
    ]
    menu_view.add_item(discord.ui.Select(
        placeholder="Wybierz skin...", options=options, custom_id=f"ws_skin_select:{weapon['id']}"
    ))
    await channel.send(
        embed=build_skin_embed(weapon, skin_index, chosen_skin_id),
        view=menu_view,
    )
    await channel.send(view=build_skin_nav_view(weapon, skin_index, chosen_skin_id == weapon["skins"][skin_index]["id"]))
    await channel.send(view=build_skin_finish_view())


async def update_skin_message(interaction: discord.Interaction, weapon: dict, skin_index: int, session: Session):
    """Podmienia embed i przyciski w bieżącej wiadomości galerii."""
    chosen_skin_id = session.weapon_skins.get(weapon["id"])
    menu_view = discord.ui.View(timeout=None)
    options = [
        discord.SelectOption(label=s["name"], value=s["id"], description=s["description"][:100], default=(s["id"] == chosen_skin_id))
        for s in weapon["skins"]
    ]
    menu_view.add_item(discord.ui.Select(
        placeholder="Wybierz skin...", options=options, custom_id=f"ws_skin_select:{weapon['id']}"
    ))
    await interaction.response.edit_message(
        embed=build_skin_embed(weapon, skin_index, chosen_skin_id),
        view=menu_view,
    )
    # Nawigacja i finish - jako podążające wiadomości (prostota > elegancja tutaj)
    await interaction.channel.send(view=build_skin_nav_view(weapon, skin_index, chosen_skin_id == weapon["skins"][skin_index]["id"]))
    await interaction.channel.send(view=build_skin_finish_view())


# ==============================================================
#  OBSŁUGA INTERAKCJI (przyciski + menu)
# ==============================================================

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if not (interaction.is_button() or interaction.is_select()):
        return
    custom_id = interaction.data.get("custom_id", "")
    try:
        session = get_session(interaction.channel_id)

        # ---- Panel główny ----
        if custom_id == "create_citizen" and session is None:
            existing = next((s for s in SESSIONS.values() if s.user_id == interaction.user.id and s.guild_id == interaction.guild_id), None)
            if existing:
                return await interaction.response.send_message(
                    f"❌ Masz już otwartą sesję tworzenia: <#{existing.channel_id}>. Zakończ ją lub użyj /zamknij.",
                    ephemeral=True,
                )
            await interaction.response.defer(ephemeral=True)
            channel, session = await create_ticket_channel(interaction)
            await interaction.followup.send(f"✅ Twój prywatny kanał: <#{channel.id}>", ephemeral=True)
            return await send_mode_selection(channel, session)

        if session is None or session.user_id != interaction.user.id:
            if custom_id.startswith(("step_", "finish_", "ws_", "mode_", "close_session")):
                return await interaction.response.send_message("❌ Sesja wygasła lub to nie Twoja sesja.", ephemeral=True)
            return

        # ---- Wybór trybu ----
        if custom_id == "mode_citizen":
            await interaction.response.defer()
            return await send_step(interaction.channel, session, 0)

        if custom_id == "mode_weapons":
            await interaction.response.defer()
            return await send_weapon_select(interaction.channel, session)

        # ---- Kreator citizena ----
        if custom_id.startswith("step_add:") or custom_id.startswith("step_remove:"):
            _, idx = custom_id.split(":")
            idx = int(idx)
            step = STEPS[idx]
            if custom_id.startswith("step_add:"):
                session.choices[step["id"]] = True
            else:
                session.choices.pop(step["id"], None)
            await interaction.response.edit_message(
                embed=build_step_embed(step, idx, step["id"] in session.choices),
                view=build_step_view(idx, step["id"] in session.choices),
            )
            return

        if custom_id.startswith("step_skip:"):
            _, idx = custom_id.split(":")
            await interaction.response.defer()
            return await send_step(interaction.channel, session, int(idx) + 1)

        if interaction.is_select() and custom_id == "step_jump":
            idx = int(interaction.data["values"][0])
            await interaction.response.defer()
            return await send_step(interaction.channel, session, idx)

        # ---- Podsumowanie / zakończenie ----
        if custom_id == "finish_build":
            chosen = [s for s in STEPS if s["id"] in session.choices]
            if not chosen:
                return await interaction.response.send_message("❌ Nie wybrano żadnej modyfikacji — nie ma czego pakować.", ephemeral=True)
            return await finish_build(interaction, session, chosen)

        if custom_id == "restart_wizard":
            session.choices.clear()
            await interaction.response.send_message("🔄 Od nowa!", ephemeral=True)
            return await send_step(interaction.channel, session, 0)

        # ---- Kreator skinów broni ----
        if interaction.is_select() and custom_id == "ws_weapon_select":
            weapon = next(w for w in WEAPONS if w["id"] == interaction.data["values"][0])
            await interaction.response.defer()
            return await send_skin_gallery(interaction.channel, session, weapon)

        if interaction.is_select() and custom_id.startswith("ws_skin_select:"):
            wid = custom_id.split(":")[1]
            weapon = next(w for w in WEAPONS if w["id"] == wid)
            skin_id = interaction.data["values"][0]
            session.weapon_skins[weapon["id"]] = skin_id
            skin_index = next(i for i, s in enumerate(weapon["skins"]) if s["id"] == skin_id)
            await update_skin_message(interaction, weapon, skin_index, session)
            return

        if custom_id.startswith("ws_prev:") or custom_id.startswith("ws_next:"):
            _, wid, idx = custom_id.split(":")
            weapon = next(w for w in WEAPONS if w["id"] == wid)
            idx = int(idx)
            new_idx = (idx + 1) % len(weapon["skins"]) if custom_id.startswith("ws_next:") else (idx - 1 + len(weapon["skins"])) % len(weapon["skins"])
            await update_skin_message(interaction, weapon, new_idx, session)
            return

        if custom_id.startswith("ws_choose:"):
            _, wid, idx = custom_id.split(":")
            weapon = next(w for w in WEAPONS if w["id"] == wid)
            idx = int(idx)
            skin = weapon["skins"][idx]
            # Toggle
            if session.weapon_skins.get(weapon["id"]) == skin["id"]:
                session.weapon_skins.pop(weapon["id"], None)
            else:
                session.weapon_skins[weapon["id"]] = skin["id"]
            await update_skin_message(interaction, weapon, idx, session)
            return

        if custom_id == "ws_back_to_weapons":
            await interaction.response.defer()
            return await send_weapon_select(interaction.channel, session)

        if custom_id == "ws_cancel":
            session.weapon_skins.clear()
            return await interaction.response.send_message("✖️ Kreator skinów anulowany.", ephemeral=True)

        if custom_id == "ws_finish":
            if not session.weapon_skins:
                return await interaction.response.send_message("❌ Nie wybrano żadnego skina.", ephemeral=True)
            chosen = []
            for wid, sid in session.weapon_skins.items():
                weapon = next(w for w in WEAPONS if w["id"] == wid)
                skin = next(s for s in weapon["skins"] if s["id"] == sid)
                chosen.append({
                    "id": skin["id"],
                    "name": f"{weapon['name']} — {skin['name']}",
                    "description": skin["description"],
                    "mode": "file",
                    "fileUrl": skin["fileUrl"],
                    "fileName": skin["fileName"],
                    "target": skin["target"],
                })
            return await finish_build(interaction, session, chosen)

        # ---- Zamknięcie ----
        if custom_id == "close_session":
            await interaction.response.send_message("🔒 Zamykam...", ephemeral=True)
            return await cleanup_session(bot, session, "Zamknięto przez użytkownika")

    except Exception:
        log.exception("Błąd obsługi interakcji")
        try:
            if interaction.response.is_done():
                await interaction.followup.send("❌ Wystąpił błąd.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Wystąpił błąd.", ephemeral=True)
        except Exception:
            pass


# ==============================================================
#  KOMENDY SLASH
# ==============================================================

@tree.command(name="panel", description="Wysyła panel kreatora citizena na bieżący kanał")
@app_commands.default_permissions(administrator=True)
async def cmd_panel(interaction: discord.Interaction):
    embed, view = build_panel()
    await interaction.response.send_message(embed=embed, view=view)


@tree.command(name="zamknij", description="Zamyka sesję kreatora na tym kanale")
async def cmd_zamknij(interaction: discord.Interaction):
    session = get_session(interaction.channel_id)
    if not session:
        return await interaction.response.send_message("❌ To nie jest kanał sesji kreatora.", ephemeral=True)
    await interaction.response.send_message("🔒 Zamykanie sesji...")
    await cleanup_session(bot, session, "Zamknięto komendą /zamknij")


# ==============================================================
#  START
# ==============================================================

@bot.event
async def on_ready():
    log.info("🤖 Zalogowano jako %s", bot.user)
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Kreator Citizenów FiveM"))
    await tree.sync()
    for guild in bot.guilds:
        try:
            await setup_guild(guild)
        except Exception as e:
            log.error("❌ Konfiguracja serwera %s nieudana: %s", guild.name, e)

    asyncio.create_task(session_cleaner())
    asyncio.create_task(downloads_cleaner())
    asyncio.create_task(mods_refresher())
    await start_http_server()


if not DISCORD_TOKEN:
    raise SystemExit(
        "❌ Brak DISCORD_TOKEN! Utwórz plik .env (wzór: .env.example) i wklej token bota."
    )

bot.run(DISCORD_TOKEN)
