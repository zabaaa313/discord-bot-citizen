"""
==============================================================================
 FIVEM MOD FOUNDRY — bot Discord (Python / discord.py 2.x)
==============================================================================
 Kreator Citizenow + Kreator Skinow Broni + Live Mod Feed (YouTube)
 + panel /system (design i reset serwera) + skan bezpieczenstwa plikow.

 Zasada: TYLKO mody klienckie (foldery citizen/ i mods/ w FiveM.app).
 ZERO skryptow serwerowych (.lua jest blokowane).

 Uruchomienie:
   pip install -r requirements.txt
   cp .env.example .env      (Windows: copy .env.example .env)
   python bot.py

 Wymagane zmienne w .env: DISCORD_TOKEN, CLIENT_ID, YOUTUBE_API_KEY
 (PUBLIC_URL opcjonalny — bez niego paczki i podglądy lecą jako załączniki Discorda,
  a hostingi Render/Railway/Fly nadają adres publiczny same)
==============================================================================
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import math
import hmac
import html
import io
import json
import logging
import os
import random
import re
import shutil
import struct
import sys
import threading
import time
import traceback
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import partial
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import aiohttp
import discord
from aiohttp import web
from discord import app_commands
from dotenv import load_dotenv

# Generator plików citizena (te same pliki, zmienione wartości)
import citizen_gen
from citizen_gen import (
    CITIZEN_GENERATED_STEPS,
    SKY_PRESETS,
    generate_citizen_file,
    sky_preset_params,
)
# Palety nowych opcji (krew, efekt strzału, opony) — jedno źródło prawdy dla
# generatora plików ORAZ podglądów w kreatorze (kafelek = realny kolor w grze).
import citizen_mods
from citizen_mods import (
    BLOOD_COLOURS, BLOOD_SIZES, TRACE_COLOURS, TRACE_SIZES, WHEEL_COLOURS,
)
# Kreator WWW — studio z zakładkami, siatką kafli i auto-doborem plików
import web_creator
from web_creator import (
    WEB_SESSIONS,
    web_session_create,
    web_session_get,
    render_citizen_page,
    render_skins_page,
    render_home_page,
    render_pack_done,
    creator_item,
    apply_bundle,
    build_state,
    toggle_item,
    clear_items,
    chosen_ids,
    output_groups,
)

# .env szukamy najpierw obok pliku bot.py (działa też, gdy plik leży na Pulpicie),
# potem w katalogu bieżącym — jak dotychczas.
load_dotenv(Path(__file__).parent / ".env")
load_dotenv()

# ============================================================================
# 1. KONFIGURACJA
# ============================================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
CLIENT_ID = os.getenv("CLIENT_ID", "").strip()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
# Port: hostingi (Render/Railway/Fly/Heroku/Azure) podają PORT — musi mieć
# priorytet nad HTTP_PORT, bo na tym porcie działa healthcheck i linki paczek.
HTTP_PORT = int(os.getenv("PORT") or os.getenv("HTTP_PORT") or "3000")


def _clean_url(raw: Optional[str]) -> str:
    """Normalizuje adres z ENV (dokłada https:// i ucina końcowy ukośnik)."""
    value = (raw or "").strip().rstrip("/")
    if value and not value.startswith(("http://", "https://")):
        value = "https://" + value
    return value


def host_is_local(url: str) -> bool:
    """Czy adres wskazuje maszynę lokalną (taki link jest bezużyteczny dla graczy)?"""
    return (urlparse(url).hostname or "").lower() in (
        "", "localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]")


def detect_public_url(port: int) -> Tuple[str, str]:
    """
    Adres publiczny bota: PUBLIC_URL z .env, a gdy go brak (albo wskazuje localhost)
    — adres nadany przez hosting. Zwraca (adres, źródło).
    """
    railway = os.getenv("RAILWAY_PUBLIC_DOMAIN") or os.getenv("RAILWAY_STATIC_URL")
    fly = f"{os.getenv('FLY_APP_NAME')}.fly.dev" if os.getenv("FLY_APP_NAME") else ""
    heroku = (f"{os.getenv('HEROKU_APP_NAME')}.herokuapp.com"
              if os.getenv("HEROKU_APP_NAME") else "")
    candidates: Tuple[Tuple[Optional[str], str], ...] = (
        (os.getenv("PUBLIC_URL"), "PUBLIC_URL (.env)"),
        (os.getenv("RENDER_EXTERNAL_URL"), "RENDER_EXTERNAL_URL (Render)"),
        (railway, "RAILWAY_PUBLIC_DOMAIN (Railway)"),
        (fly, "FLY_APP_NAME (Fly.io)"),
        (heroku, "HEROKU_APP_NAME (Heroku)"),
        (os.getenv("KOYEB_PUBLIC_DOMAIN"), "KOYEB_PUBLIC_DOMAIN (Koyeb)"),
        (os.getenv("WEBSITE_HOSTNAME"), "WEBSITE_HOSTNAME (Azure)"),
    )
    for raw, source in candidates:            # najpierw prawdziwy, publiczny adres
        url = _clean_url(raw)
        if url and not host_is_local(url):
            return url, source
    for raw, source in candidates:            # potem cokolwiek (np. jawny localhost)
        url = _clean_url(raw)
        if url:
            return url, source
    return f"http://localhost:{port}", "domyślnie localhost"


PUBLIC_URL, PUBLIC_URL_SOURCE = detect_public_url(HTTP_PORT)
SKIN_INDEX_URL = os.getenv("SKIN_INDEX_URL", "").strip()

YT_SCAN_MINUTES = int(os.getenv("YT_SCAN_MINUTES", "15") or 15)
# Skaner bierze filmy z ostatnich YT_MAX_AGE_DAYS dni (domyślnie 2 tygodnie).
YT_MAX_AGE_DAYS = max(1, int(os.getenv("YT_MAX_AGE_DAYS", "14") or 14))
# Ile zapytań na jeden skan (rotacja) — chroni darmowy limit YouTube API.
YT_QUERIES_PER_RUN = max(4, int(os.getenv("YT_QUERIES_PER_RUN", "10") or 10))
# Pauza skanera po wyczerpaniu limitu YouTube API.
YT_QUOTA_BACKOFF_MINUTES = max(0, int(os.getenv("YT_QUOTA_BACKOFF_MINUTES", "60") or 60))
ZIP_QUEUE_CONCURRENCY = int(os.getenv("ZIP_QUEUE_CONCURRENCY", "2") or 2)
DOWNLOAD_TTL_MINUTES = int(os.getenv("DOWNLOAD_TTL_MINUTES", "60") or 60)
SESSION_TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "120") or 120)
CHANNEL_CLEANUP_MINUTES = int(os.getenv("CHANNEL_CLEANUP_MINUTES", "15") or 15)
APPROVAL_TTL_MINUTES = int(os.getenv("APPROVAL_TTL_MINUTES", "1440") or 1440)
MAX_DOWNLOAD_MB = int(os.getenv("MAX_DOWNLOAD_MB", "200") or 200)
MAX_DOWNLOAD_BYTES = MAX_DOWNLOAD_MB * 1024 * 1024
DEFAULT_BUILD_ID = os.getenv("GAME_BUILD", "latest").strip() or "latest"

# --- Cache plikow bazowych (paczki buduja sie w ulamku sekundy) ---
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "1").strip().lower() not in ("0", "false", "no")
CACHE_TTL_HOURS = int(os.getenv("CACHE_TTL_HOURS", "72") or 72)
# --- Garbage Collector (auto-czyszczenie dysku) ---
DELETE_AFTER_DOWNLOAD_MINUTES = int(os.getenv("DELETE_AFTER_DOWNLOAD_MINUTES", "10") or 10)
GC_INTERVAL_MINUTES = int(os.getenv("GC_INTERVAL_MINUTES", "2") or 2)
# --- Powiadomienia o bledach (webhook Discorda) ---
ERROR_WEBHOOK_URL = os.getenv("ERROR_WEBHOOK_URL", "").strip()
# --- Kolejka: informuj gracza o pozycji w kolejce ---
QUEUE_NOTIFY = os.getenv("QUEUE_NOTIFY", "1").strip().lower() not in ("0", "false", "no")
# --- Paginacja (Discord limituje select do 25 opcji) ---
SKINS_PER_PAGE = max(5, int(os.getenv("SKINS_PER_PAGE", "24") or 24))
SEARCH_RESULTS_PER_PAGE = max(3, int(os.getenv("SEARCH_RESULTS_PER_PAGE", "8") or 8))
STEPS_PER_PAGE = max(25, int(os.getenv("STEPS_PER_PAGE", "25") or 25))
# --- Własne pliki graczy (przycisk 📎) — bez hostingu, prosto z Discorda ---
UPLOAD_MAX_MB = max(1, int(os.getenv("UPLOAD_MAX_MB", "25") or 25))
UPLOAD_MAX_FILES = max(1, int(os.getenv("UPLOAD_MAX_FILES", "20") or 20))
# --- Wysyłka paczek bez hostingu: załączniki Discorda (fallback dla localhost) ---
DISCORD_ATTACH_MB = max(1, int(os.getenv("DISCORD_ATTACH_MB", "8") or 8))
DISCORD_ATTACH_BYTES = DISCORD_ATTACH_MB * 1024 * 1024
DISCORD_MAX_ATTACHMENTS = 10

ROOT = Path(__file__).parent.resolve()
DOWNLOADS_DIR = ROOT / "downloads"
WORKSPACES_DIR = ROOT / "temp_sessions"
LOGS_DIR = ROOT / "logs"
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / "cache"
POSTED_FILE = ROOT / "posted_videos.json"
BUILD_STATE_FILE = DATA_DIR / "build.json"

for _d in (DOWNLOADS_DIR, WORKSPACES_DIR, LOGS_DIR, DATA_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Nazwy rol / kategorii / kanalow ---
ROLE_CREATOR = "@Creator"
ROLE_MEMBER = "Członek"
ROLE_BUILDING = "Tworzenie w toku"

CAT_INFO = "📢 START"
CAT_CITIZEN = "🏭 CITIZEN FOUNDRY"
CAT_TICKETS = "TWOJE PACZKI"
CAT_SKINS = "🔫 WEAPON SKIN STUDIO"
CAT_MODS = "📦 MOD FEED"

CH_WELCOME = "witaj"
CH_RULES = "regulamin"
CH_CITIZEN = "stworz-citizena"
CH_SKINS = "skiny-broni"
CH_MODS_LIVE = "mody-optymalizacja-live"
CH_DOWNLOADS = "centrum-pobierania"
CH_HELP = "pomoc"
CH_SYSLOG = "logi-system"

# --- Kanały tematyczne live feedu (kategoria CAT_MODS) ---
#   Każdy film z YouTube trafia na kanał pasujący do jego kategorii.
CH_FEED_MODS = "mody-opti"          # mody klienckie: opti/potato/fpv/mapy/auta/grafika
CH_FEED_SKINS = "skiny-rpf"         # skin packi i tekstury .rpf do broni
CH_FEED_PC = "opti-kompa"           # optymalizacja komputera pod FiveM (Windows/GPU/ping)

# --- Kolory embedow ---
C_BLUE = 0x5865F2
C_GREEN = 0x57F287
C_YELLOW = 0xFEE75C
C_ORANGE = 0xE67E22
C_RED = 0xED4245
C_PURPLE = 0x9B59B6

# --- Wersje gry (wersjonowanie paczek) ---
GAME_BUILDS: List[Dict[str, str]] = [
    {"id": "latest", "name": "Najnowszy GTA V / FiveM", "note": "Zgodny z aktualnym patchem — zalecany."},
    {"id": "3411", "name": "GTA V build 3411 (1.69)", "note": "Świeży patch, często wymagany na serwerach."},
    {"id": "3258", "name": "GTA V build 3258 (1.68)", "note": "Stabilny, szeroko wspierany."},
    {"id": "3095", "name": "GTA V build 3095 (1.67)", "note": "Starszy, ale wciąż popularny."},
    {"id": "2944", "name": "GTA V build 2944 (1.66 legacy)", "note": "Dla starszych setupów i słabych PC."},
]

# ============================================================================
# 2. DANE: KREATOR CITIZENA (24 opcje w 6 grupach)
#    Zdjęcia i linki do plików to PLACEHOLDERY — PODMIEŃ na własne!
# ============================================================================

# IMG_BASE: zostaw puste, a bot wygeneruje własne podglądy (PNG, zawsze działają).
# Jeśli masz własne zdjęcia, ustaw np. IMG_BASE=https://twoj-host.pl/img/
IMG_BASE = os.getenv("IMG_BASE", "").strip()
if IMG_BASE and not IMG_BASE.endswith("/"):
    IMG_BASE += "/"
# FILE_BASE: skąd bot bierze pliki presetów (puste = tylko własne pliki graczy)
FILE_BASE = os.getenv("FILE_BASE", "").strip()

G1 = "1️⃣ ŚRODOWISKO — Niebo i timecycle"
G2 = "2️⃣ WODA — czysta / FPS boost"
G3 = "3️⃣ CIENIE — całkowite lub partial"
G4 = "4️⃣ POJAZDY — propsy, szyby, dym, ogień"
G5 = "5️⃣ POTATO — mapa low-poly, skiny nietknięte"
G6 = "6️⃣ KOMBAT — dźwięki, krew, hitmarkery, celownik"

T_TIMECYCLE = "citizen/common/data/timecycle"
T_DATA = "citizen/common/data"
T_WATER = "citizen/common/data/levels/gta5"
T_EFFECTS = "citizen/common/data/effects/pc"
T_MODS = "mods"
T_WEAPONS_TEX = "mods/x64e.rpf/models/cdimages/weapons"


def _step(group: str, sid: str, name: str, desc: str, image: str,
          url: str, file_name: str, target: str) -> Dict[str, str]:
    """Buduje definicję jednego kroku kreatora citizena."""
    return {
        "group": group,
        "id": sid,
        "name": name,
        "description": desc,
        # Puste = obrazek generuje bot (zawsze działa). Własne zdjęcie ustawisz
        # w ENV IMG_BASE (wtedy budowane jest z nazwy w polu `image_name`).
        "image": f"{IMG_BASE}{image}.jpeg" if IMG_BASE else "",
        "image_name": image,
        # Puste FILE_BASE = nie mamy hostingu presetów: krok jest opisany,
        # a gracz wgrywa własny plik (przycisk 📎 Własny plik).
        "file_url": f"{FILE_BASE}{url}" if FILE_BASE else "",
        "file_name": file_name,
        "target": target,
    }


# ============================================================================
# 2. DANE: KREATOR CITIZENA — PLIKI GENEROWANE (przeskany czysty citizen)
#    Zamiast martwych placeholderów example.com bot SAM BUDUJE pliki paczki
#    (timecycle/sggd.xml, weather.xml, time.xml, visualsettings.dat, bloodfx.dat)
#    — dokładnie te same pliki co w citizen/common/data, tylko ze zmienionymi
#    wartościami. Definicje kroków + custom nieba są w citizen_gen.py.
# ============================================================================

CITIZEN_STEPS: List[Dict[str, Any]] = CITIZEN_GENERATED_STEPS


# ============================================================================
# 3. DANE: SKINY BRONI (.ytd/.ydr)
# ============================================================================

# SKIN_BASE: hosting Twoich plików skinów (.ytd/.ydr). Puste = skiny z katalogu
# są tylko opisami, a gracz wgrywa własny plik przyciskiem 📎 Własny skin.
SKIN_BASE = os.getenv("SKIN_BASE", "").strip()


def _skin(sid: str, name: str, desc: str, image: str, url: str, file_name: str,
          target: str = T_WEAPONS_TEX) -> Dict[str, str]:
    """Buduje definicję jednego skina broni (grafika generowana, chyba że IMG_BASE)."""
    return {
        "id": sid,
        "name": name,
        "description": desc,
        "image": f"{IMG_BASE}{image}.jpeg" if IMG_BASE else "",
        "image_name": image,
        "file_url": f"{SKIN_BASE}{url}" if SKIN_BASE else "",
        "file_name": file_name,
        "target": target,
    }


# UWAGA: lista celowo OGRANICZONA do 4+1 broni (życzenie użytkownika):
#   pistol / pistolmk2 / vintagepistol / snspistol / snspistolmk2.
# Każda broń ma 25 skinów z EXPANDERA (Gold, Chrome, Neon, Galaxy...) = 125 skinów.


def _expanded_weapon_categories() -> List[Dict[str, Any]]:
    """Buduje katalog broni ze skinami z citizen_expand (25 skinów na broń)."""
    try:
        from citizen_expand import expanded_skins
        expanded = expanded_skins()
    except ImportError:  # pragma: no cover
        expanded = {}
    weapons = [
        ("pistol", "Pistol", "w_pi_pistol.ytd"),
        ("pistolmk2", "Pistol Mk II", "w_pi_pistolmk2.ytd"),
        ("vintagepistol", "Vintage Pistol", "w_pi_vintage_pistol.ytd"),
        ("snspistol", "SNS Pistol", "w_pi_sns_pistol.ytd"),
        ("snspistolmk2", "SNS Pistol Mk II", "w_pi_sns_pistolmk2.ytd"),
    ]
    out_weapons: List[Dict[str, Any]] = []
    for weapon_id, weapon_name, file_name in weapons:
        skins = expanded.get(weapon_id) or []
        out_weapons.append({
            "id": weapon_id, "name": weapon_name,
            "skins": [_skin(s["id"], s["name"], s["description"], s["image_name"],
                            file_name.replace(".ytd", "") + "_" + s["name"].lower() + ".ytd",
                            file_name)
                      for s in skins],
        })
    return [{"id": "pistols", "name": "🔫 Pistolety", "weapons": out_weapons}]


WEAPON_CATEGORIES: List[Dict[str, Any]] = _expanded_weapon_categories()

# ============================================================================
# 4. DANE: LIVE YOUTUBE FEED
# ============================================================================

YT_QUERIES: List[str] = [
    # --- optymalizacja komputera (opti kompa) ---
    "FiveM opti kompa",
    "optymalizacja komputera FiveM",
    "FiveM optymalizacja ustawien",
    "FiveM fps boost windows 11",
    "FiveM boost fps nvidia",
    "FiveM stutter fix",
    "FiveM lag fix pc",
    "FiveM ping boost",
    "jak zwiekszyc fps w fivem",
    # --- mody klienckie / opti packi ---
    "FiveM FPS boost",
    "FiveM optimization mod rpf",
    "FiveM opti pack client side",
    "FiveM low end pc mods",
    "FiveM LagFix",
    "FiveM low poly citizen",
    "FiveM first person mod",
    "FiveM first person rpf",
    "FiveM potato graphics",
    "FiveM potato mod rpf",
    "FiveM graphics mod rpf",
    "FiveM visual settings",
    "FiveM client side mods",
    # --- mapy i auta (client-side) ---
    "FiveM PvP map opti",
    "FiveM client side map",
    "FiveM car mods client side",
    # --- skiny broni (.rpf) ---
    "FiveM weapon skins",
    "FiveM gun skins pack",
    "FiveM skiny broni rpf",
    "FiveM weapon texture pack rpf",
]

YT_CATEGORIES: List[Tuple[str, Tuple[str, ...]]] = [
    # OPTI KOMPA musi być PIERWSZE — inaczej "opti" z kategorii OPTI przechwyci
    # tytuły o optymalizacji komputera i film trafi na zły kanał.
    ("OPTI KOMPA", ("opti kompa", "optymalizacja komputera", "optymalizacja pc", "opti pc",
                    "fps boost pc", "boost fps pc", "windows 11", "windows 10", "nvidia",
                    "geforce", "amd software", "gpu", "cpu", "stutter", "ping boost",
                    "latency", "ssd", "komputer", "ustawienia pc", "game boost")),
    ("POTATO", ("potato",)),
    ("FIRST PERSON", ("first person", "fpv", "first-person", "low poly citizen")),
    ("SKINY BRONI", ("skin", "weapon", "gun", "texture", "broni")),
    ("MAPY", ("map", "mlo", "pvp", "place", "miejsce")),
    ("AUTA", ("car", "vehicle", "add-on")),
    ("GRAFIKA", ("graphics", "visual", "shaders", "grafika", "realistic", "citizen")),
    ("OPTI", ("optimiz", "opti", "fps boost", "lagfix", "low end", "performance", "optymaliz")),
]

YT_BLACKLIST: Tuple[str, ...] = (
    "script", "esx", "qbcore", "qb-core", "vrp", "server side", "serwerowy",
    "txadmin", "how to make", "jak zrobic serwer", "fivem server tutorial",
    "mod menu", "executor", "injector", "hack", "cheat", "giveaway",
)

# Domeny zaufane dla linkow z opisow filmow
SAFE_HOSTS = {
    "github.com", "raw.githubusercontent.com", "objects.githubusercontent.com",
    "cdn.discordapp.com", "media.discordapp.net", "drive.google.com", "mega.nz",
    "www.mediafire.com", "download944.mediafire.com", "gta5-mods.com",
    "www.gta5-mods.com", "files.gta5-mods.com", "gitlab.com", "www.dropbox.com",
    "dl.dropboxusercontent.com",
}
BLOCKED_HOSTS = {
    "bit.ly", "tinyurl.com", "adf.ly", "shorte.st", "ouo.io", "linkvertise.com",
    "discord.gg",
}

# ============================================================================
# 5. LOGGER
# ============================================================================

LOG_FILE = LOGS_DIR / "bot.log"
_logger = logging.getLogger("foundry")
_logger.setLevel(logging.DEBUG)
if not _logger.handlers:
    _fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
    _sh = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    _fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    _fh.setFormatter(_fmt)
    _logger.addHandler(_sh)
    _logger.addHandler(_fh)


def log(name: str) -> logging.Logger:
    """Zwraca logger podmodułu."""
    return _logger.getChild(name)


core_log = log("Core")

# ============================================================================
# 6. BEZPIECZEŃSTWO PLIKÓW (anti-malware)
# ============================================================================

# Surowych tekstur (.dds/.png/.jpg) nie blokujemy, ale wymagają zgody admina
# i przechodzą przez walidator anty-crash (wymiary + szacowany VRAM).
ALLOW_EXT = {".rpf", ".ytd", ".ydr", ".yft", ".ymt", ".dat", ".xml", ".meta", ".txt", ".json", ".ini", ".cfg"}
REVIEW_EXT = {".asi", ".zip", ".rar", ".7z", ".oiv", ".cab", ".dds", ".png", ".jpg", ".jpeg"}
BLOCK_EXT = {
    ".exe", ".bat", ".cmd", ".com", ".scr", ".pif", ".msi", ".msp", ".dll", ".sys",
    ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".ps1", ".psm1", ".jar", ".lnk",
    ".url", ".apk", ".app", ".dmg", ".sh", ".bash", ".py", ".rb", ".pl", ".php",
    ".reg", ".hta", ".cpl", ".gadget", ".inf", ".iso", ".img", ".vhd", ".lua", ".sql", ".env",
}


def scan_filename(file_name: str) -> Dict[str, str]:
    """Skanuje nazwę pliku. Zwraca {'level': allow|review|block, 'ext', 'reason'}."""
    name = (file_name or "").strip().lower()
    if not name:
        return {"level": "block", "ext": "", "reason": "Brak nazwy pliku"}
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if ext in BLOCK_EXT:
        extra = " (skrypty serwerowe są poza zakresem bota)" if ext == ".lua" else ""
        return {"level": "block", "ext": ext, "reason": f"Zablokowane rozszerzenie {ext}{extra}"}
    if ext in REVIEW_EXT:
        return {"level": "review", "ext": ext, "reason": f"{ext} wymaga ręcznej zgody administratora"}
    if ext in ALLOW_EXT:
        return {"level": "allow", "ext": ext, "reason": "Bezpieczny plik gry"}
    return {"level": "review", "ext": ext or "?", "reason": f"Nieznane rozszerzenie {ext or '?'} — wymaga zgody"}


def scan_url(url: str) -> Dict[str, str]:
    """Skanuje plik wskazany przez URL (nazwa pliku z adresu)."""
    name = file_name_from_url(url)
    result = scan_filename(name)
    result["file_name"] = name
    return result


def file_name_from_url(url: str) -> str:
    """Wyciąga nazwę pliku z URL (bez query stringa)."""
    try:
        return Path(urlparse(url).path).name
    except Exception:  # pragma: no cover
        return (url or "").split("?")[0].rsplit("/", 1)[-1]


def sha256_file(path: Path) -> Tuple[str, int]:
    """Liczy SHA-256 pliku (strumieniowo). Zwraca (hash, rozmiar)."""
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 256), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def hash_directory(directory: Path) -> List[Dict[str, Any]]:
    """Liczy hashe wszystkich plików w katalogu (rekurencyjnie)."""
    out: List[Dict[str, Any]] = []
    for file_path in sorted(directory.rglob("*")):
        if file_path.is_file():
            digest, size = sha256_file(file_path)
            rel = file_path.relative_to(directory).as_posix()
            out.append({"path": rel, "sha256": digest, "size": size})
    return out


def hashes_to_text(hashes: Sequence[Dict[str, Any]], build_name: str = "", user_id: str = "") -> str:
    """Zawartość pliku HASHES.txt w paczce."""
    lines = [
        "=== WERYFIKACJA PACZKI (SHA-256) ===",
        f"Wygenerowano: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    if build_name:
        lines.append(f"Docelowy build GTA V: {build_name}")
    if user_id:
        lines.append(f"Sesja użytkownika: {user_id}")
    lines += [
        "",
        "Każda linia: <sha256>  <ścieżka w paczce>",
        "Jeśli hash pliku po pobraniu się nie zgadza — NIE instaluj paczki.",
        "",
    ]
    lines += [f"{h['sha256']}  {h['path']}" for h in hashes]
    return "\n".join(lines)

# ============================================================================
# 7. CONFLICT RESOLVER (dwa mody nadpisujące ten sam plik)
# ============================================================================

conf_log = log("Conflicts")

# Pary (gen_file, slot) — kroki dzielące ten sam plik, ale NIE kolidujące:
# każdy slot to osobne "pokrętło" pliku, a wszystkie scalają się w JEDEN plik
# (np. krew + rozmiar krwi + kolor głowy + headshot → jeden bloodfx.dat).
# Kolejność jest STAŁA (tuple) — klucze plików muszą być deterministyczne.
_COMPOSABLE_SLOTS: Tuple[str, ...] = (
    "blood_colour", "blood_size", "head_colour", "head_size",
    "trace_colour", "trace_size", "wheel_colour",
    "kill_color", "kill_style", "kill_blur",
)


def _gen_slot(item: Dict[str, str]) -> str:
    """Osobne „pokrętło” pliku, które ustawia ten krok (kroki komponowalne)."""
    params = item.get("gen_params") or {}
    for slot in _COMPOSABLE_SLOTS:
        if slot in params:
            return f"{item.get('gen_file')}#{slot}"
    return str(item.get("gen_file") or "")


def file_key(item: Dict[str, str]) -> str:
    """Ścieżka docelowa pliku w paczce (dla plików generowanych: citizen/...)."""
    if item.get("generated"):
        return f"citizen/common/data/{_gen_slot(item) or 'plik'}"
    target = (item.get("target") or "mods").strip("/")
    return f"{target}/{item.get('file_name') or 'plik'}"


def resolve_conflicts(chosen: Sequence[Dict[str, str]]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], List[Dict[str, Any]]]:
    """
    Wykrywa konflikty plików i wybiera ostatnio wskazany wariant.
    Zwraca (kept, dropped, conflicts).
    """
    groups: Dict[str, List[Tuple[int, Dict[str, str]]]] = {}
    for index, item in enumerate(chosen):
        groups.setdefault(file_key(item), []).append((index, item))

    kept: List[Tuple[int, Dict[str, str]]] = []
    dropped: List[Dict[str, str]] = []
    conflicts: List[Dict[str, Any]] = []

    for key, entries in groups.items():
        winner_index, winner = entries[-1]
        kept.append((winner_index, winner))
        if len(entries) > 1:
            losers = [item for _, item in entries[:-1]]
            dropped.extend(losers)
            conflicts.append({
                "file": key,
                "winner": winner["name"],
                "dropped": [item["name"] for item in losers],
                "candidates": [item["name"] for _, item in entries],
            })
            conf_log.warning(
                "Konflikt pliku %s: %s — zostaje: %s",
                key, " vs ".join(item["name"] for _, item in entries), winner["name"],
            )

    kept.sort(key=lambda pair: pair[0])
    return [item for _, item in kept], dropped, conflicts


def conflicts_to_text(conflicts: Sequence[Dict[str, Any]]) -> str:
    """Czytelny opis konfliktów do INSTRUKCJA.txt."""
    return "\n".join(
        f" • Plik: {c['file']}\n"
        f"   wybrano: {', '.join(c['candidates'])}\n"
        f"   ZAINSTALOWANO: {c['winner']}\n"
        f"   pominięto (unikanie crashu): {', '.join(c['dropped'])}"
        for c in conflicts
    )

# ============================================================================
# 8. WERYFIKACJA LINKÓW Z OPISÓW FILMÓW
# ============================================================================

link_log = log("ExtractLinks")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")


def extract_urls(text: str) -> List[str]:
    """Wyciąga wszystkie URL-e z tekstu."""
    return URL_RE.findall(text or "")


def verify_url(url: str) -> Dict[str, Any]:
    """Sprawdza, czy domena jest zaufana. Zwraca {'safe', 'host', 'reason'}."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https":
            return {"safe": False, "host": host, "reason": "Brak HTTPS"}
        if host in BLOCKED_HOSTS:
            return {"safe": False, "host": host, "reason": "Domena zablokowana (maskowanie/phishing)"}
        is_safe = (
            host in SAFE_HOSTS
            or host.endswith(".gta5-mods.com")
            or host.endswith(".github.com")
            or host.endswith(".gitlab.com")
            or host.endswith(".discordapp.com")
            or host.endswith(".dropboxusercontent.com")
        )
        if not is_safe:
            return {"safe": False, "host": host, "reason": "Domena spoza listy zaufanych"}
        return {"safe": True, "host": host}
    except Exception:
        return {"safe": False, "host": "?", "reason": "Nieprawidłowy URL"}


def safe_links_from_description(description: str) -> List[Dict[str, str]]:
    """Zwraca TYLKO bezpieczne linki z opisu filmu."""
    out: List[Dict[str, str]] = []
    for url in extract_urls(description):
        verdict = verify_url(url)
        if verdict["safe"]:
            out.append({"url": url, "host": verdict["host"]})
        else:
            link_log.debug("Odrzucono %s (%s)", url, verdict["reason"])
    return out

# ============================================================================
# 9. PODGLĄD KOMBINACJI (Live Before/After) — generator HTML
# ============================================================================

PREVIEW_CSS = """
:root{--bg:#0f1117;--card:#181b25;--line:#262b3a;--txt:#e6e8ef;--muted:#9aa3b5;--acc:#57f287;--blue:#5865f2;--yellow:#fee75c}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font-family:'Segoe UI',system-ui,sans-serif}
header{padding:28px 20px;background:linear-gradient(120deg,#5865f2,#9b59b6)}
h1{margin:0;font-size:22px}
.sub{opacity:.85;margin-top:6px;font-size:13px}
.wrap{max-width:1100px;margin:0 auto;padding:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;display:flex;flex-direction:column}
.card img{width:100%;height:190px;object-fit:cover;background:#0b0d13}
.card .body{padding:12px 14px;flex:1}
.name{font-weight:600;margin-bottom:6px}
.desc{color:var(--muted);font-size:13px;line-height:1.45}
.tag{display:inline-block;font-size:11px;padding:2px 8px;border-radius:99px;background:#1d2340;color:#9db4ff;margin-bottom:8px}
.box{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:16px}
.box h2{margin:0 0 8px;font-size:15px}
ul{margin:6px 0 0 18px;padding:0;line-height:1.6;font-size:13px;color:var(--muted)}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:#c8d0e0}
footer{color:var(--muted);font-size:12px;padding:22px;text-align:center}
"""

# ============================================================================
# 9.3. GENERATOR PODGLĄDÓW (PNG bez zewnętrznych bibliotek)
#   Wcześniej zdjęcia szły z zewnętrznego hostingu i były martwe (placeholder),
#   a Discord nie wyświetla SVG. Dlatego każdy krok kreatora i każdy skin ma
#   obrazek generowany lokalnie ze swojej palety — zawsze działa offline.
#   Ten sam PNG obsługuje: embed (attachment:// albo /img/...), stronę podglądu
#   (data URI) i endpoint /img/<klucz>.png.
# ============================================================================

img_log = log("Podglady")
PREVIEW_W, PREVIEW_H = 640, 360
BLOOK = 4  # rozmiar bloku renderowania podglądów (4x4 px = gładko i szybko)
# Podglądy w galeriach są małe (kafel ma ~230-480 px szerokości), więc zapisujemy
# je w 75% rozmiaru renderu. Kafel waży ~3x mniej i wczytuje się ~3x szybciej,
# a oko nie widzi różnicy (patrz test "podglad jest zoptymalizowany").
PREVIEW_OUT_SCALE = float(os.getenv("PREVIEW_OUT_SCALE") or "0.75")
# Wersja katalogu cache podglądów: nowy filtr PNG + mniejszy rozmiar.
# Stara wersja (cache/step_previews) jest jednorazowo przeliczana w tle.
PREVIEW_CACHE_VERSION = "step_previews_v2"
_IMAGE_CACHE: Dict[str, bytes] = {}
# Równoległe rendery podglądów (poza pętlą zdarzeń) — serwer zostaje responsywny,
# gdy pierwszy gracz otwiera zakładkę z 100+ kaflami.
_PREVIEW_THREADS = max(2, int(os.getenv("PREVIEW_THREADS") or "4"))
_PREVIEW_POOL = ThreadPoolExecutor(max_workers=_PREVIEW_THREADS, thread_name_prefix="preview")
_preview_gate: Optional[asyncio.Semaphore] = None


def preview_gate() -> asyncio.Semaphore:
    """Limit jednoczesnych renderów podglądów (leniwe tworzenie — wymaga pętli)."""
    global _preview_gate
    if _preview_gate is None:
        _preview_gate = asyncio.Semaphore(_PREVIEW_THREADS)
    return _preview_gate

# Palety kroków citizena: (niebo, ziemia, akcent) — pokazują efekt opcji.
STEP_COLORS: Dict[str, Tuple[str, str, str]] = {
    "sky-clear": ("3aa0ff", "7a9b3f", "ffffff"),
    "sky-dark": ("0b1026", "141c2e", "ffd479"),
    "sun-soft": ("6fa8dc", "8a9a5b", "ffe9b0"),
    "clouds-off": ("3f7fd0", "86a04a", "dfefff"),
    "water-clear": ("2f8bd0", "1f6fa8", "9fe3ff"),
    "water-fps": ("3b7ec4", "255d90", "bfe8ff"),
    "colors-vivid": ("ff9a3c", "3fa34d", "ffd166"),
    "shadows-total": ("c8d8e8", "d9d2b8", "ffffff"),
    "shadows-partial": ("8fa8c0", "9a9a7a", "e8e8e8"),
    "postfx-clean": ("dfe9f5", "b9bfa3", "ffffff"),
    "props-remove": ("9fd0ef", "b5b09a", "cfd6c4"),
    "windows-invisible": ("8ab6e0", "9aa08a", "ffffff"),
    "tire-smoke-off": ("b9c6d4", "8d8d84", "e2e2e2"),
    "fire-sparks-off": ("c9d3dd", "8a8a80", "efe6d0"),
    "potato-full": ("7fd0ff", "6ab04c", "ffd23f"),
    "potato-terrain": ("8ad4ff", "7bbf55", "ffe066"),
    "grass-off": ("9fd7f5", "a8a48f", "d9d3bd"),
    "sound-bass": ("1b2233", "3a2a1a", "ff8c2b"),
    "sound-decibels": ("232a38", "3a3a46", "ffd8a8"),
    "blood-anime": ("2a0d14", "3a1220", "ff2e6a"),
    "blood-minimal": ("3a1d22", "4a2a2e", "ff6b81"),
    "blood-none": ("2c2c2e", "3a3a3c", "dcdcdc"),
    "hitmarker-custom": ("20232c", "2c3038", "ff4d4d"),
    "crosshair-custom": ("1d2027", "282c34", "7cff6b"),
}

# Palety skinów broni: (metal, akcent) — dobierane deterministycznie po id skina.
SKIN_PALETTES: Tuple[Tuple[str, str], ...] = (
    ("14161c", "39ff88"), ("1b1b1b", "ff2e4d"), ("232733", "33c6ff"),
    ("2b2118", "d9a441"), ("101820", "ff6ad5"), ("1f1f1f", "f2f2f2"),
    ("182028", "9dff4d"), ("241a12", "ff9d2e"), ("111418", "7c4dff"),
    ("2a2a2a", "00e5c0"), ("1a2418", "a3ff12"), ("20141c", "ff4fa3"),
    ("3b2f12", "ffd166"), ("0f1a24", "00b3ff"), ("2c1216", "ff8c42"),
    ("1c1f14", "b8ff2e"), ("26202e", "c77dff"), ("152018", "66ffcc"),
)

# Warianty grafiki skina (0 = pas, 1 = kamuflaż, 2 = szachownica).
SKIN_PATTERNS = 3


def _rgb(value: str) -> Tuple[int, int, int]:
    """Zamienia '#rrggbb' na krotkę RGB."""
    text = str(value).lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    if len(text) != 6:
        return (40, 44, 52)
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return (40, 44, 52)


def _mix(first: Tuple[int, int, int], second: Tuple[int, int, int],
         ratio: float) -> Tuple[int, int, int]:
    """Miesza dwa kolory (ratio 0 = pierwszy, 1 = drugi)."""
    ratio = max(0.0, min(1.0, ratio))
    return tuple(int(first[i] + (second[i] - first[i]) * ratio) for i in range(3))  # type: ignore[return-value]


def _row_bytes(row: Sequence[Tuple[int, int, int]]) -> bytes:
    """Wiersz pikseli RGB jako bajty (szybkie — konwersja w C, bez pętli po pikselach)."""
    return b"".join(bytes(px) for px in row)


def png_downscale(rows: Sequence[Sequence[Tuple[int, int, int]]],
                  factor: float) -> List[List[Tuple[int, int, int]]]:
    """
    Pomniejszenie obrazu metodą pudełkową (średnia z bloku).

    Podgląd renderujemy w pełnej rozdzielczości (ładniejsze krawędzie słońca
    i chmur), a zapisujemy mniejszy — dzięki temu kafel w galerii waży ~3x
    mniej bajtów i tyle samo szybciej się wczytuje.
    """
    if factor >= 0.999 or not rows:
        return list(rows)
    height, width = len(rows), len(rows[0])
    if not height or not width:
        return list(rows)
    new_h = max(1, int(height * factor))
    new_w = max(1, int(width * factor))
    if new_h == height and new_w == width:
        return list(rows)
    out: List[List[Tuple[int, int, int]]] = []
    for ty in range(new_h):
        y0 = ty * height // new_h
        y1 = max(y0 + 1, (ty + 1) * height // new_h)
        line: List[Tuple[int, int, int]] = []
        for tx in range(new_w):
            x0 = tx * width // new_w
            x1 = max(x0 + 1, (tx + 1) * width // new_w)
            red = green = blue = count = 0
            for yy in range(y0, y1):
                src = rows[yy]
                for xx in range(x0, x1):
                    pixel = src[xx]
                    red += pixel[0]
                    green += pixel[1]
                    blue += pixel[2]
                    count += 1
            line.append((red // count, green // count, blue // count))
        out.append(line)
    return out


def png_encode(rows: Sequence[Sequence[Tuple[int, int, int]]],
               scale: Optional[float] = None) -> bytes:
    """
    Koduje piksele RGB do PNG (zlib + CRC) — bez Pillow, czysty stdlib.

    Filtr „Up” (2) zamiast „brak” (0): niebo to pionowy gradient, więc różnice
    między sąsiednimi wierszami są malutkie i zlib kompresuje je ~2.5x lepiej.
    To ten sam obraz, tylko mniejszy plik — a mniejszy plik = szybsza galeria.
    """
    rows = png_downscale(rows, PREVIEW_OUT_SCALE if scale is None else scale)
    height = len(rows)
    width = len(rows[0]) if height else 0
    raw = bytearray()
    previous = bytes(width * 3)
    for row in rows:
        line = _row_bytes(row)
        raw.append(2)  # filtr 2 = Up (różnica względem wiersza wyżej)
        raw += bytes((a - b) & 255 for a, b in zip(line, previous))
        previous = line

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (len(data).to_bytes(4, "big") + kind + data
                + zlib.crc32(kind + data).to_bytes(4, "big"))

    header = (width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0]))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


def png_meta(data: bytes) -> Tuple[int, int]:
    """Rozmiar PNG (bez dekodowania pikseli) — do statystyk i migracji cache."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return 0, 0
    return (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))


def png_decode_rows(data: bytes) -> Optional[List[List[Tuple[int, int, int]]]]:
    """
    Rozpakowuje PNG RGB 8-bit (wszystkie filtry) do wierszy pikseli.

    Używane tylko przez jednorazową migrację starego cache podglądów, żeby nie
    renderować 278 obrazków od zera po aktualizacji.
    """
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos, idat, width, height, depth, colour = 8, bytearray(), 0, 0, 0, 0
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", body[:10])
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
        pos += 12 + length
    if not width or not height or depth != 8 or colour != 2:
        return None
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error:
        return None
    stride = width * 3
    rows: List[List[Tuple[int, int, int]]] = []
    prev = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        if start + stride > len(raw):
            return None
        filt = raw[start]
        line = bytearray(raw[start + 1:start + 1 + stride])
        if filt == 1:
            for i in range(3, stride):
                line[i] = (line[i] + line[i - 3]) & 255
        elif filt == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif filt == 3:
            for i in range(stride):
                left = line[i - 3] if i >= 3 else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif filt == 4:
            for i in range(stride):
                left = line[i - 3] if i >= 3 else 0
                up = prev[i]
                up_left = prev[i - 3] if i >= 3 else 0
                estimate = left + up - up_left
                pa, pb, pc = (abs(estimate - left), abs(estimate - up),
                              abs(estimate - up_left))
                pred = left if (pa <= pb and pa <= pc) else (up if pb <= pc else up_left)
                line[i] = (line[i] + pred) & 255
        elif filt != 0:
            return None
        prev = line
        rows.append([tuple(line[x * 3:x * 3 + 3]) for x in range(width)])
    return rows


def _rect(buf: List[List[Tuple[int, int, int]]], x0: int, y0: int, x1: int, y1: int,
          color: Tuple[int, int, int]) -> None:
    """Prostokąt (z przycięciem do obszaru obrazka)."""
    height, width = len(buf), len(buf[0])
    for y in range(max(0, y0), min(height, y1)):
        row = buf[y]
        for x in range(max(0, x0), min(width, x1)):
            row[x] = color


def _disc(buf: List[List[Tuple[int, int, int]]], cx: int, cy: int, radius: int,
          color: Tuple[int, int, int]) -> None:
    """Koło (słońce/księżyc na podglądzie)."""
    height, width = len(buf), len(buf[0])
    for y in range(max(0, cy - radius), min(height, cy + radius)):
        for x in range(max(0, cx - radius), min(width, cx + radius)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius:
                buf[y][x] = color


def _f01(value: float) -> int:
    """Parametr sggd (0..1+) na kanał 0-255."""
    return max(0, min(255, int(round(float(value) * 255))))


def _cloud_cover(density: float, seed: int) -> float:
    """Deterministyczne pokrycie chmurami 0..1 na bazie gęstości z sggd."""
    rng = random.Random(seed)
    return max(0.0, min(1.0, density * (0.75 + rng.random() * 0.5)))


def sky_png(params: Dict[str, float], seed: int = 0, *, rain: float = 0.0,
            grade: Optional[str] = None, storm: bool = False, blood: float = 0.0,
            blood_head: float = 0.0, sun: str = "mid", moon_big: bool = False,
            blood_rgb: Optional[Tuple[int, int, int]] = None,
            trace_rgb: Optional[Tuple[int, int, int]] = None,
            trace_scale: float = 1.0,
            wheel_rgb: Optional[Tuple[int, int, int]] = None,
            water_rgb: Optional[Tuple[int, int, int]] = None,
            fog_amount: float = 0.0,
            smoke: float = 0.0,
            fire: float = 0.0,
            scorch: bool = True,
            blur_amount: float = 0.0,
            moon_rgb: Optional[Tuple[int, int, int]] = None,
            sun_rgb: Optional[Tuple[int, int, int]] = None,
            sun_scale: float = 1.0,
            cloud_tint: Optional[Tuple[int, int, int]] = None,
            ground_glow: Optional[Tuple[int, int, int]] = None,
            ground_glow_strength: float = 0.35) -> bytes:
    """
    REALISTYCZNY podgląd nieba z parametrów sggd.xml (to co gracz zobaczy w grze):
      • gradient zenith -> horizon z realnych kolorów (sky_zenith_col, sky_horizon_col)
      • poświata azymutalna przy horyzoncie (sky_azimuth_east/west/transition)
      • słońce (intensywność) i KSIĘŻYC (sky_moon_iten, sky_moon_disc_size)
      • CHMURY — deterministyczne kłęby, gęstość wg sky_cloud_density_mult
    """
    rng = random.Random(seed or 7)
    zenith = (_f01(params.get("sky_zenith_col_r", .3)),
              _f01(params.get("sky_zenith_col_g", .5)),
              _f01(params.get("sky_zenith_col_b", .9)))
    horizon = (_f01(params.get("sky_horizon_col_r", .6)),
               _f01(params.get("sky_horizon_col_g", .75)),
               _f01(params.get("sky_horizon_col_b", .95)))
    east = (_f01(params.get("sky_azimuth_east_col_r", .9)),
            _f01(params.get("sky_azimuth_east_col_g", .8)),
            _f01(params.get("sky_azimuth_east_col_b", .6)))
    west = (_f01(params.get("sky_azimuth_west_col_r", .85)),
            _f01(params.get("sky_azimuth_west_col_g", .7)),
            _f01(params.get("sky_azimuth_west_col_b", .55)))

    moon_inten = max(0.0, min(1.0, float(params.get("sky_moon_iten", .35))))
    moon_size = float(params.get("sky_moon_disc_size", 1.0))
    sun_glow = max(0.2, min(2.5, float(params.get("sky_sunburst_imten", 1.0))))
    density = max(0.0, min(1.0, float(params.get("sky_cloud_density_mult", .35))))
    if moon_big:                      # podgląd „Wielki księżyc”
        moon_inten = max(moon_inten, 0.9)
        moon_size = max(moon_size, 2.2)
    if storm:                         # podgląd „Klimat burzowy”
        density = max(density, 0.9)

    horizon_y = int(PREVIEW_H * 0.78)
    ground = _mix((24, 28, 34), horizon, 0.35)   # ciemna sylwetka terenu

    buf: List[List[Tuple[int, int, int]]] = [[zenith for _ in range(PREVIEW_W)]
                                             for _ in range(PREVIEW_H)]

    # --- gradient nieba: zenith na górze -> horizon przy linii ---
    for y in range(horizon_y):
        t = y / max(1, horizon_y)
        row_color = _mix(zenith, horizon, t ** 0.9)
        _rect(buf, 0, y, PREVIEW_W, y + 1, row_color)

    # --- poświata azymutalna (wschód=złoto przy słońcu, zachód chłodniejszy) ---
    sun_x = int(PREVIEW_W * 0.72)
    sun_y_factor = {"high": 0.14, "mid": 0.30, "low": 0.74}.get(sun, 0.30)
    sun_y = int(horizon_y * sun_y_factor)
    glow_radius = PREVIEW_W * 0.45 * sun_glow
    for y in range(0, horizon_y, BLOOK):        # pętla po blokach 4x4 (glow i tak jest gładki)
        for x in range(0, PREVIEW_W, BLOOK):
            xm, ym = min(x + BLOOK // 2, PREVIEW_W - 1), min(y + BLOOK // 2, horizon_y - 1)
            dist_sun = ((xm - sun_x) ** 2 + (ym - sun_y) ** 2) ** 0.5
            glow = max(0.0, 1.0 - dist_sun / glow_radius)
            col = _mix(buf[ym][xm], east, glow * 0.55) if glow > 0 else buf[ym][xm]
            dist_h = (horizon_y - ym) / max(1, horizon_y)
            if xm < PREVIEW_W * 0.25 and dist_h < 0.35:
                col = _mix(col, west, (0.35 - dist_h) * 1.2)
            for yy in range(y, min(y + BLOOK, horizon_y)):
                row = buf[yy]
                for xx in range(x, min(x + BLOOK, PREVIEW_W)):
                    row[xx] = col

    # --- chmury (deterministyczne kłęby, alpha wg gęstości) ---
    if density > 0.02:
        cover = _cloud_cover(density, seed or 7)
        puffs = int(10 + cover * 42)
        for _ in range(puffs):
            cx, cy = rng.randint(-40, PREVIEW_W + 40), rng.randint(8, horizon_y - 30)
            base_r = rng.randint(14, 40)
            shade = _mix((250, 250, 252), _mix(east, (60, 70, 95), 0.5), rng.random() * 0.7)
            if cloud_tint is not None:                   # kolor custom chmur
                shade = _mix(shade, cloud_tint, 0.55)
            for part in range(rng.randint(4, 9)):
                px = cx + rng.randint(-int(base_r * 1.6), int(base_r * 1.6))
                py = cy + rng.randint(-base_r // 2, base_r // 2)
                pr = max(6, int(base_r * (0.4 + rng.random() * 0.7)))
                # rozmycie: malujemy 3 warstwy o rosnącym promieniu i malejącej sile
                for ring, strength in ((pr, 0.16), (int(pr * 0.8), 0.3), (int(pr * 0.55), 0.5)):
                    _disc_soft(buf, px, py, ring, shade, strength, limit_y=horizon_y)

    # --- słońce (tarcza + halo) ---
    sun_r = max(4, int(15 * sun_glow * max(0.3, min(3.0, sun_scale))))
    sun_col = _mix(sun_rgb or east, (255, 252, 235), 0.45)
    _disc_soft(buf, sun_x, sun_y, int(sun_r * 2.4), _mix(sun_col, (255, 250, 220), 0.5), 0.35,
               limit_y=horizon_y)
    _disc(buf, sun_x, sun_y, sun_r, _mix(sun_col, (255, 255, 240), 0.85))

    # --- księżyc (widoczny wg intensywności; duży gdy moon_disc_size > 1) ---
    if moon_inten > 0.05:
        moon_x, moon_y = int(PREVIEW_W * 0.18), int(horizon_y * 0.28)
        moon_r = max(7, int(13 * moon_size * max(0.3, min(3.0, sun_scale))))
        glow_m = _mix((200, 210, 255), (255, 255, 255), moon_inten)
        if moon_rgb is not None:
            glow_m = _mix(glow_m, moon_rgb, 0.75)
        _disc_soft(buf, moon_x, moon_y, int(moon_r * 2.0), glow_m, 0.30 * moon_inten, limit_y=horizon_y)
        _disc(buf, moon_x, moon_y, moon_r,
              _mix(_mix((225, 230, 245), (255, 255, 255), moon_inten),
                   moon_rgb or (225, 230, 245), 0.65))
        # cień/krater dla realizmu
        _disc(buf, moon_x + moon_r // 3, moon_y - moon_r // 4, max(2, moon_r // 4),
              _mix(glow_m, (140, 150, 180), 0.35))

    # --- ziemia (sylwetka + odbicie koloru horyzontu) ---
    _rect(buf, 0, horizon_y, PREVIEW_W, PREVIEW_H, ground)
    # prosty krajobraz: wzgórza
    hill_h = int((PREVIEW_H - horizon_y) * 0.35)
    for x in range(PREVIEW_W):
        h = hill_h // 2 + int((hill_h / 2) * (1 + math.sin(x * 0.02 + seed % 7)))
        _rect(buf, x, horizon_y + hill_h - h, x + 1, PREVIEW_H, _mix(ground, (8, 9, 12), 0.45))

    # --- POŚWIATA / TONACJA TERENU (światła uliczne, kałuże, cienie) ---
    if ground_glow is not None:
        strength = max(0.0, min(1.0, ground_glow_strength))
        for y in range(horizon_y, PREVIEW_H):
            t = 1.0 - (y - horizon_y) / max(1, PREVIEW_H - horizon_y)
            row = buf[y]
            for x in range(PREVIEW_W):
                row[x] = _mix(row[x], ground_glow, strength * (0.35 + 0.65 * t))

    # --- WODA (water_* z MATOL.xml): pas wody w realnym kolorze z pliku ---
    if water_rgb is not None:
        top = horizon_y + int((PREVIEW_H - horizon_y) * 0.42)
        for y in range(top, PREVIEW_H):
            t = (y - top) / max(1, PREVIEW_H - top)
            water_col = _mix(_mix(water_rgb, (255, 255, 255), 0.22),
                             _mix(water_rgb, (0, 0, 0), 0.5), t)
            row = buf[y]
            for x in range(PREVIEW_W):
                row[x] = _mix(row[x], water_col, 0.88)
        for x in range(PREVIEW_W):                       # refleks słońca na wodzie
            if abs(x - sun_x) < 3:
                for y in range(top, PREVIEW_H, 6):
                    buf[y][x] = _mix(buf[y][x], (255, 250, 225), 0.4)

    # --- MGŁA (fog_*): biała zasłona rośnie przy ziemi ---
    if fog_amount > 0:
        amount = max(0.0, min(1.0, fog_amount))
        fog_col = _mix((206, 212, 222), horizon, 0.25)
        for y in range(horizon_y, PREVIEW_H):
            t = 1.0 - (y - horizon_y) / max(1, PREVIEW_H - horizon_y)
            strength = min(1.0, amount * (0.4 + 0.7 * t))
            row = buf[y]
            for x in range(PREVIEW_W):
                row[x] = _mix(row[x], fog_col, strength)
        for y in range(int(horizon_y * 0.55), horizon_y):
            row = buf[y]
            for x in range(PREVIEW_W):
                row[x] = _mix(row[x], fog_col, amount * 0.45)

    # --- OGIEŃ / EKSPLOZJE (fire_*, expl_*) ---
    if fire > 0:
        rng_f = random.Random((seed or 7) + 626)
        power = max(0.35, min(3.0, fire))
        for _ in range(int(3 + 5 * power)):
            cx = rng_f.randint(30, PREVIEW_W - 30)
            cy = rng_f.randint(horizon_y + 4, PREVIEW_H - 8)
            radius = rng_f.randint(9, int(14 + 20 * power))
            if scorch:                                   # ślad przypalenia
                _disc_soft(buf, cx, cy, int(radius * 1.5), (28, 24, 22), 0.5)
            _disc_soft(buf, cx, cy, int(radius * 1.9), (255, 140, 35), 0.4)
            _disc_soft(buf, cx, cy, radius, (255, 196, 80), 0.85)
            _disc(buf, cx, cy, max(3, radius // 3), (255, 246, 205))

    # --- DYM (smoke-off / cząstki otoczenia) ---
    if smoke > 0:
        rng_s = random.Random((seed or 7) + 313)
        for _ in range(int(16 * max(0.3, min(2.0, smoke)))):
            cx = rng_s.randint(20, PREVIEW_W - 20)
            cy = rng_s.randint(int(horizon_y * 0.35), PREVIEW_H - 10)
            _disc_soft(buf, cx, cy, rng_s.randint(13, 32), (122, 124, 130), 0.34)

    # --- KREW (podgląd efektów kombat: baza + kill + head razem) ---
    if blood > 0 or blood_head > 0:
        rng_b = random.Random((seed or 7) + 991)
        ground_hits = int(12 * min(1.5, blood))
        head_hits = int(7 * blood_head)
        for i in range(ground_hits + head_hits):
            if i < ground_hits:      # plamy na ziemi/wzgórzach (kill + baza)
                cx = rng_b.randint(15, PREVIEW_W - 15)
                cy = rng_b.randint(horizon_y + 8, PREVIEW_H - 6)
                r = rng_b.randint(5, int(10 + 24 * min(1.0, blood + 0.2)))
            else:                    # trysk w powietrzu (headshot)
                cx = rng_b.randint(int(PREVIEW_W * 0.3), int(PREVIEW_W * 0.7))
                cy = rng_b.randint(int(horizon_y * 0.30), horizon_y - 25)
                r = rng_b.randint(4, int(8 + 18 * blood_head))
            tint = blood_rgb or (200, 20, 20)
            col = _mix(_mix(tint, (20, 0, 0), 0.35), _mix(tint, (255, 255, 255), 0.45),
                       rng_b.random() * 0.5)
            _disc_soft(buf, cx, cy, r, col, 0.8)
        if blood > 0:                # poświata sceny w kolorze wybranej krwi
            tint = blood_rgb or (200, 20, 20)
            for y in range(horizon_y, PREVIEW_H):
                row = buf[y]
                for x in range(PREVIEW_W):
                    row[x] = _mix(row[x], _mix(tint, (0, 0, 0), 0.55),
                                  0.16 * min(1.2, blood))

    # --- EFEKT STRZAŁU (weaponfx.dat): dziury po kulach + smugi w kolorze COL_TINT
    if trace_rgb is not None:
        rng_t = random.Random((seed or 7) + 4242)
        holes = int(9 * max(0.4, min(3.0, trace_scale)))
        for _ in range(holes):
            cx = rng_t.randint(20, PREVIEW_W - 20)
            cy = rng_t.randint(horizon_y + 6, PREVIEW_H - 6)
            radius = max(2, int(rng_t.randint(4, 9) * min(3.0, trace_scale)))
            _disc_soft(buf, cx, cy, radius, trace_rgb, 0.8)
        for _ in range(int(5 * max(0.4, min(3.0, trace_scale)))):
            x0 = rng_t.randint(0, PREVIEW_W - 34)
            y0 = rng_t.randint(8, max(9, int(horizon_y * 0.65)))
            length = rng_t.randint(16, 34)
            for i in range(length):
                xx, yy = x0 + i, y0 + i // 2
                if i % 2 == 0 and 0 <= yy < horizon_y and 0 <= xx < PREVIEW_W:
                    buf[yy][xx] = _mix(buf[yy][xx], trace_rgb, 0.65)

    # --- ŚLADY OPON (wheelfx.dat): dwa pasy skidmarków w kolorze COL_TINT ---
    if wheel_rgb is not None:
        for lane, base_y in ((0, 0.30), (1, 0.62)):
            y0 = horizon_y + int((PREVIEW_H - horizon_y) * base_y)
            for x in range(24, PREVIEW_W - 24):
                yy = y0 + int(7 * math.sin(x * 0.025 + lane * 1.7))
                if horizon_y <= yy < PREVIEW_H:
                    buf[yy][x] = _mix(buf[yy][x], wheel_rgb, 0.85)
                    if yy + 1 < PREVIEW_H:
                        buf[yy + 1][x] = _mix(buf[yy + 1][x], wheel_rgb, 0.45)

    # --- BURZA: przyciemnienie + DESZCZ (krople widoczne jak w grze) ---
    if storm:
        for y in range(PREVIEW_H):
            row = buf[y]
            for x in range(PREVIEW_W):
                row[x] = _mix(row[x], (34, 40, 56), 0.30)
    if rain > 0.02:
        rng_r = random.Random((seed or 7) + 517)
        col_r = _mix(horizon, (200, 220, 245), 0.6)
        for _ in range(int(rain * 320)):
            x0 = rng_r.randint(0, PREVIEW_W - 8)
            y0 = rng_r.randint(0, PREVIEW_H - 22)
            for i in range(rng_r.randint(9, 20)):
                xx, yy = x0 + i // 3, y0 + i
                if 0 <= yy < PREVIEW_H and 0 <= xx < PREVIEW_W:
                    buf[yy][xx] = _mix(buf[yy][xx], col_r, 0.45)

    # --- GRADING POSTFX (vivid / cold / film) — jak timecycle_mods_4 ---
    # Grading blokami 4x4 px (środek bloku jako reprezentant) — wizualnie gładkie,
    # a ~16x szybsze niż per-piksel.
    if grade in ("vivid", "cold", "film"):
        cx, cy = PREVIEW_W / 2, PREVIEW_H / 2
        dmax = (cx * cx + cy * cy) ** 0.5
        STEP = 4
        for gy in range(0, PREVIEW_H, STEP):
            y1 = min(gy + STEP, PREVIEW_H)
            for gx in range(0, PREVIEW_W, STEP):
                x1 = min(gx + STEP, PREVIEW_W)
                xm, ym = min(gx + STEP // 2, PREVIEW_W - 1), min(gy + STEP // 2, PREVIEW_H - 1)
                out = _pixel_grade(grade, buf[ym][xm], xm, ym, cx, cy, dmax)
                for y in range(gy, y1):
                    row = buf[y]
                    for x in range(gx, x1):
                        row[x] = out

    # --- BLUR / DOF / LENS (blur_*) — rozmycie + delikatna winieta ---
    if blur_amount > 0:
        buf = _blur(buf, 2 if blur_amount < 1.5 else 4)
        cx, cy = PREVIEW_W / 2, PREVIEW_H / 2
        dmax = (cx * cx + cy * cy) ** 0.5
        for y in range(0, PREVIEW_H, 3):
            row = buf[y]
            for x in range(0, PREVIEW_W, 3):
                d = (((x - cx) ** 2 + (y - cy) ** 2) ** 0.5) / dmax
                col = _mix(row[x], (0, 0, 0), 0.22 * d * d * min(1.5, blur_amount))
                for yy in range(y, min(y + 3, PREVIEW_H)):
                    for xx in range(x, min(x + 3, PREVIEW_W)):
                        buf[yy][xx] = col

    return png_encode(buf)


def _blur(buf: List[List[Tuple[int, int, int]]], radius: int) -> List[List[Tuple[int, int, int]]]:
    """Szybki box-blur (osobno X i Y) — podglądy blur/DOF jak w grze."""
    if radius < 1:
        return buf
    height, width = len(buf), len(buf[0])
    tmp: List[List[Tuple[int, int, int]]] = [[(0, 0, 0)] * width for _ in range(height)]
    for y in range(height):
        row = buf[y]
        for x in range(width):
            r = g = b = n = 0
            for dx in range(-radius, radius + 1):
                xx = min(width - 1, max(0, x + dx))
                pr, pg, pb = row[xx]
                r += pr
                g += pg
                b += pb
                n += 1
            tmp[y][x] = (r // n, g // n, b // n)
    out: List[List[Tuple[int, int, int]]] = [[(0, 0, 0)] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            r = g = b = n = 0
            for dy in range(-radius, radius + 1):
                yy = min(height - 1, max(0, y + dy))
                pr, pg, pb = tmp[yy][x]
                r += pr
                g += pg
                b += pb
                n += 1
            out[y][x] = (r // n, g // n, b // n)
    return out


def _pixel_grade(grade: str, rgb: Tuple[int, int, int], x: int, y: int,
                 cx: float, cy: float, dmax: float) -> Tuple[int, int, int]:
    """Grading dla pojedynczego piksela (fallback poza siatką LUT)."""
    r0, g0, b0 = rgb
    if grade == "vivid":
        l = (r0 + g0 + b0) // 3
        return (max(0, min(255, int(l + (r0 - l) * 1.45))),
                max(0, min(255, int(l + (g0 - l) * 1.45))),
                max(0, min(255, int(l + (b0 - l) * 1.45))))
    if grade == "cold":
        return _mix((r0, g0, b0), (150, 180, 235), 0.16)
    d = (((x - cx) ** 2 + (y - cy) ** 2) ** 0.5) / dmax
    r, g, b = r0, g0, b0
    if (r + g + b) // 3 < 110:
        r, g, b = _mix((r, g, b), (60, 80, 92), 0.22)
    f = 1.0 - 0.45 * d * d
    return (max(0, min(255, int(r * f))),
            max(0, min(255, int(g * f))),
            max(0, min(255, int(b * f))))


def _disc_soft(buf: List[List[Tuple[int, int, int]]], cx: int, cy: int, radius: int,
               color: Tuple[int, int, int], strength: float, limit_y: Optional[int] = None) -> None:
    """Miękkie koło (glow/chmura): mieszanie z tłem o sile `strength` (0..1)."""
    strength = max(0.0, min(1.0, strength))
    bottom = limit_y if limit_y is not None else len(buf)
    r2 = radius * radius
    for y in range(max(0, cy - radius), min(bottom, cy + radius + 1)):
        for x in range(max(0, cx - radius), min(len(buf[0]), cx + radius + 1)):
            d2 = (x - cx) ** 2 + (y - cy) ** 2
            if d2 <= r2:
                # feather na krawędzi
                edge = 1.0 - (d2 / r2) ** 0.5
                buf[y][x] = _mix(buf[y][x], color, min(1.0, strength * (0.35 + 0.65 * edge)))


def scene_png(sky: str, ground: str, accent: str, horizon: float = 0.62) -> bytes:
    """Krajobraz: gradient nieba, podłoga, budynki i słońce w kolorze akcentu."""
    top, bottom, key = _rgb(sky), _rgb(ground), _rgb(accent)
    buf = [[_rgb(sky) for _ in range(PREVIEW_W)] for _ in range(PREVIEW_H)]
    line = int(PREVIEW_H * horizon)
    for y in range(line):
        _rect(buf, 0, y, PREVIEW_W, y + 1, _mix(top, _mix(top, bottom, 0.35), y / max(1, line)))
    _rect(buf, 0, line, PREVIEW_W, PREVIEW_H, bottom)
    _disc(buf, int(PREVIEW_W * 0.78), int(line * 0.34), 26, key)
    # trzy budynki z oknami
    for index, (bx, bw, bh) in enumerate(((70, 96, 150), (196, 74, 110), (300, 120, 190))):
        building = _mix(bottom, (18, 18, 22), 0.45)
        _rect(buf, bx, line - bh, bx + bw, line, building)
        for wy in range(line - bh + 12, line - 12, 22):
            for wx in range(bx + 10, bx + bw - 10, 24):
                _rect(buf, wx, wy, wx + 12, wy + 10, key if (wx + wy + index) % 3 else _mix(key, building, 0.4))
    # droga z przodu
    _rect(buf, 0, line + int((PREVIEW_H - line) * 0.55), PREVIEW_W, PREVIEW_H, _mix(bottom, (10, 10, 12), 0.5))
    return png_encode(buf)


def weapon_png(metal: str, accent: str, pattern: int = 0) -> bytes:
    """
    Podgląd skina: sylwetka broni w kolorach skina (na ciemnym tle).

    `pattern` daje 3 warianty grafiki, żeby każdy skin w galerii wyglądał inaczej:
    pas (0), kamuflaż z plam (1) albo szachownica (2).
    """
    base, key = _rgb(metal), _rgb(accent)
    background = _rgb("0e1116")
    buf = [[background for _ in range(PREVIEW_W)] for _ in range(PREVIEW_H)]
    for y in range(PREVIEW_H):
        _rect(buf, 0, y, PREVIEW_W, y + 1, _mix(background, _rgb("1c2230"), y / PREVIEW_H))
    dark = _mix(base, (0, 0, 0), 0.35)
    light = _mix(base, (255, 255, 255), 0.18)
    # korpus
    _rect(buf, 150, 150, 470, 186, base)
    _rect(buf, 150, 186, 470, 196, dark)
    # lufa + tłumik
    _rect(buf, 470, 158, 590, 178, base)
    _rect(buf, 578, 152, 600, 184, dark)
    # chwyt
    for i in range(9):
        _rect(buf, 196 + i * 3, 196 + i * 12, 236 + i * 3, 210 + i * 12, dark if i % 2 else base)
    # magazynek + spust
    _rect(buf, 300, 196, 344, 274, base)
    _rect(buf, 306, 202, 338, 268, key)
    _rect(buf, 250, 196, 268, 232, dark)
    _rect(buf, 236, 224, 300, 234, dark)
    # --- wzór skina ---
    variant = pattern % SKIN_PATTERNS
    if variant == 1:            # kamuflaż: plamy na korpusie i lufie
        for i in range(8):
            _disc(buf, 168 + i * 38, 166 + (i % 3) * 8, 9 + (i % 3), _mix(base, key, 0.55))
            _disc(buf, 478 + (i % 4) * 28, 166 + (i % 2) * 6, 6, _mix(base, key, 0.4))
    elif variant == 2:          # szachownica
        for i in range(150, 470, 24):
            for j in range(150, 196, 12):
                if (i // 24 + j // 12) % 2:
                    _rect(buf, i, j, i + 12, j + 12, _mix(base, key, 0.7))
    else:                       # pas + podkreślenie
        _rect(buf, 150, 166, 470, 174, key)
        _rect(buf, 150, 176, 470, 179, light)
    # muszka i szczerbinka
    _rect(buf, 452, 142, 462, 152, dark)
    _rect(buf, 176, 142, 186, 152, dark)
    # kolba
    _rect(buf, 60, 156, 150, 192, dark)
    return png_encode(buf)


def _safe_key(key: str) -> str:
    """Bezpieczny klucz obrazka (tylko litery, cyfry i myślniki)."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", str(key)).strip("-").lower()
    return cleaned[:60] or "podglad"


def step_image_key(step: Dict[str, Any]) -> str:
    return f"step-{_safe_key(step.get('id', 'krok'))}"


def skin_image_key(weapon: Dict[str, Any], skin: Dict[str, Any]) -> str:
    return f"skin-{_safe_key(skin.get('id', 'skin'))}"


def _catalog_preview(base: Dict[str, float], params: Dict[str, Any],
                     step: Dict[str, Any], seed: int) -> Optional[bytes]:
    """
    Podgląd dla nowych grup katalogu (krew, efekt strzału, opony, czas, woda,
    mgła, światło, postfx, blur, eksplozje, dym, visual settings…).

    Render liczymy WPROST z parametrów kroku — kafel pokazuje dokładnie ten
    kolor/efekt, który generator wpisze do pliku w paczce. Zwraca None, gdy krok
    nie należy do żadnej z tych grup (wtedy działa podgląd awaryjny).
    """
    # --- KREW (effects/bloodfx.dat) ---
    if params.get("blood_colour") or params.get("blood_size"):
        rgb = BLOOD_COLOURS.get(str(params.get("blood_colour")), (200, 20, 20))
        scale = float(BLOOD_SIZES.get(str(params.get("blood_size")), 1.0))
        return sky_png(base, seed=seed, blood=scale, blood_rgb=rgb)

    # --- EFEKT STRZAŁU (effects/weaponfx.dat) ---
    if params.get("trace_colour") or params.get("trace_size"):
        rgb = TRACE_COLOURS.get(str(params.get("trace_colour")), (230, 230, 230))
        scale = float(TRACE_SIZES.get(str(params.get("trace_size")), 1.0))
        return sky_png(base, seed=seed, trace_rgb=rgb, trace_scale=scale)

    # --- OPONY / DRIFT (effects/wheelfx.dat) ---
    if params.get("wheel_colour"):
        rgb = WHEEL_COLOURS.get(str(params.get("wheel_colour")), (12, 12, 12))
        return sky_png(base, seed=seed, wheel_rgb=rgb)

    # --- BEZ DEKALI (effects/decals.dat) ---
    if str(params.get("decals_style") or "") == "clear":
        sky = dict(base)
        sky["sky_cloud_density_mult"] = 0.22
        return sky_png(sky, seed=seed)

    # --- CZAS (levels/gta5/time.xml): zawsze dzień / zawsze noc / złota godzina ---
    if params.get("time_mode"):
        sky, sun, moon_big = _sky_for_time(base, str(params["time_mode"]))
        return sky_png(sky, seed=seed, sun=sun, moon_big=moon_big)

    # --- POGODA (levels/gta5/weather.xml) ---
    if params.get("weather_style"):
        rain, storm, density = _WEATHER_PREVIEW.get(str(params["weather_style"]),
                                                   (0.0, False, 0.4))
        sky = dict(base)
        sky["sky_cloud_density_mult"] = density
        return sky_png(sky, seed=seed, rain=rain, storm=storm)

    # --- SŁOŃCE / KSIĘŻYC (MATOL.xml) ---
    if params.get("sun_style"):
        style = str(params["sun_style"])
        sky = dict(base)
        sun = "high" if style == "soft" else "mid"
        if style == "golden":
            sun = "low"
        if style == "rays-off":
            sky["sky_sunburst_imten"] = 0.35
        return sky_png(sky, seed=seed, sun=sun, sun_rgb=_SUN_RGB.get(style),
                       sun_scale=1.25 if style == "warm" else 1.0)
    if params.get("moon_style"):
        style = str(params["moon_style"])
        sky = dict(base)
        sky["sky_moon_iten"] = 0.95
        if style == "small":
            sky["sky_moon_disc_size"] = 0.6
        return sky_png(sky, seed=seed, moon_big=(style == "huge"),
                       moon_rgb=_MOON_RGB.get(style))

    # --- CHMURY (MATOL / clouds.xml / cloudkeyframes.xml) ---
    if params.get("cloud_matol"):
        sky = dict(base)
        sky["sky_cloud_density_mult"] = _CLOUD_DENSITY.get(str(params["cloud_matol"]), 0.35)
        return sky_png(sky, seed=seed)
    if params.get("cloud_color"):
        return sky_png(base, seed=seed,
                       cloud_tint=_CLOUD_TINT.get(str(params["cloud_color"])))
    if params.get("clouds_geom"):
        density = {"high": 0.3, "low": 0.55, "big": 0.75, "small": 0.4,
                   "fast": 0.45}.get(str(params["clouds_geom"]), 0.4)
        sky = dict(base)
        sky["sky_cloud_density_mult"] = density
        return sky_png(sky, seed=seed)
    if params.get("clouds_key"):
        density = {"dense": 0.95, "sparse": 0.25, "fast": 0.5,
                   "slow": 0.6}.get(str(params["clouds_key"]), 0.4)
        sky = dict(base)
        sky["sky_cloud_density_mult"] = density
        return sky_png(sky, seed=seed)

    # --- WODA (MATOL.xml) ---
    if params.get("water_style"):
        return sky_png(base, seed=seed,
                       water_rgb=_WATER_RGB.get(str(params["water_style"])))

    # --- MGŁA (MATOL.xml) ---
    if params.get("fog_style"):
        amount = _FOG_AMOUNT.get(str(params["fog_style"]), 0.0)
        return sky_png(base, seed=seed, fog_amount=amount)

    # --- ŚWIATŁO (MATOL.xml): nocne miasto, latarnie, ped-light ---
    if params.get("light_style"):
        style = str(params["light_style"])
        glow = _LIGHT_RGB.get(style)
        sky, _sun, _big = _sky_for_time(base, "always-night")
        strength = 0.12 if style == "street-off" else 0.45
        return sky_png(sky, seed=seed, ground_glow=glow, ground_glow_strength=strength)

    # --- KOLORY / POSTFX (timecycle_mods_4.xml) ---
    if params.get("postfx_style"):
        grade = _POSTFX_GRADE.get(str(params["postfx_style"]))
        return sky_png(base, seed=seed, grade=grade)

    # --- BLUR / DOF / LENS ---
    if params.get("blur_style"):
        amount = _BLUR_AMOUNT.get(str(params["blur_style"]), 0.5)
        return sky_png(base, seed=seed, blur_amount=amount)

    # --- KILL EFFECT (kolor + siła + blur) ---
    if params.get("kill_color") or params.get("kill_style") or params.get("kill_blur"):
        rgb = _KILL_RGB.get(str(params.get("kill_color")), _KILL_RGB.get("red"))
        level = _KILL_LEVEL.get(str(params.get("kill_style")), 0.9)
        blur = _KILL_BLUR.get(str(params.get("kill_blur")), 0.0)
        return sky_png(base, seed=seed, blood=level, blood_rgb=rgb, blur_amount=blur)

    # --- EKSPLOZJE / OGIERŃ ---
    if params.get("expl_scale") or params.get("expl_count") or params.get("expl_scorch"):
        power = _EXPL_POWER.get(str(params.get("expl_scale")), 1.0)
        if str(params.get("expl_count") or "") == "more":
            power *= 1.4
        elif str(params.get("expl_count") or "") == "less":
            power *= 0.6
        scorch = str(params.get("expl_scorch") or "") != "off"
        return sky_png(base, seed=seed, fire=power, scorch=scorch)
    if params.get("fire_style"):
        power = _FIRE_POWER.get(str(params["fire_style"]), 0.8)
        return sky_png(base, seed=seed, fire=power)

    # --- DYM I CZĄSTKI ---
    if params.get("smoke_style") or params.get("particle_style"):
        smoke = 1.0 if params.get("smoke_style") else 0.0
        if params.get("particle_style"):
            smoke = 1.6 if str(params["particle_style"]) == "all-off" else 1.2
        return sky_png(base, seed=seed, smoke=smoke, cloud_tint=(120, 122, 130))

    # --- VISUAL SETTINGS: deszcz, cykl, słońce, chmury, cienie, kałuże ---
    if params.get("rain_vis"):
        rain = _VISUAL_RAIN.get(str(params["rain_vis"]), 0.4)
        sky = dict(base)
        sky["sky_cloud_density_mult"] = max(0.45, rain)
        return sky_png(sky, seed=seed, rain=rain,
                       ground_glow=(150, 170, 210) if rain > 0 else None,
                       ground_glow_strength=0.18)
    if params.get("cycle_vis"):
        sky, sun, big = _sky_for_time(base, "dynamic")
        return sky_png(sky, seed=seed, sun=sun, moon_big=big)
    if params.get("sun_vis"):
        style = str(params["sun_vis"])
        scale = {"big": 1.8, "small": 0.55, "glow": 1.4}.get(style, 1.0)
        sky = dict(base)
        sky["sky_sunburst_imten"] = 1.6 if style == "glow" else sky.get("sky_sunburst_imten", 1.0)
        return sky_png(sky, seed=seed, sun_scale=scale, sun_rgb=(255, 240, 200))
    if params.get("cloud_vis"):
        density = {"motion-off": 0.6, "fast": 0.5, "slow": 0.7}.get(str(params["cloud_vis"]), 0.5)
        sky = dict(base)
        sky["sky_cloud_density_mult"] = density
        return sky_png(sky, seed=seed)
    if params.get("shadow_vis"):
        on = str(params["shadow_vis"]) == "on"
        return sky_png(base, seed=seed, sun_scale=1.2 if on else 0.9,
                       ground_glow=(0, 0, 0) if on else (70, 70, 80),
                       ground_glow_strength=0.35)
    if params.get("puddle_vis"):
        on = str(params["puddle_vis"]) == "on"
        return sky_png(base, seed=seed, rain=0.25 if on else 0.0,
                       ground_glow=(120, 150, 200) if on else None,
                       ground_glow_strength=0.3)
    if params.get("car_vis"):
        on = str(params["car_vis"]) == "interior-on"
        sky, _s, _b = _sky_for_time(base, "always-night")
        return sky_png(sky, seed=seed,
                       ground_glow=(255, 200, 140) if on else (40, 45, 60),
                       ground_glow_strength=0.3)
    if params.get("dof_vis"):
        return sky_png(base, seed=seed, blur_amount=0.5)

    # --- WYDAJNOŚĆ (FPS) — czysty, „odchudzony” obraz ---
    if params.get("fps_style"):
        sky = dict(base)
        sky["sky_cloud_density_mult"] = 0.12
        sky["sky_sunburst_imten"] = 0.4
        return sky_png(sky, seed=seed)

    # --- HUD / UI — schematyczne ujęcie menu ---
    if params.get("hud_style"):
        return scene_png("1b2130", "39405a", "7aa2ff", horizon=0.72)

    # --- VISUAL SETTINGS: pozostałe (drobne przełączniki) ---
    if any(key.endswith("_vis") for key in params):
        return scene_png("22304a", "4a5a44", "ffd166", horizon=0.66)
    return None


def _step_seed(step: Dict[str, Any]) -> int:
    """Deterministyczne ziarno podglądu (ten sam krok = ten sam obrazek)."""
    return zlib.crc32(str(step.get("id", "")).encode())


# Katalog podglądów (wersjonowany) + blokady, żeby dwóch graczy nie renderowało
# tego samego obrazka równolegle po restarcie bota.
PREVIEW_DIR = CACHE_DIR / PREVIEW_CACHE_VERSION
LEGACY_PREVIEW_DIR = CACHE_DIR / "step_previews"
_PREVIEW_LOCKS: Dict[str, threading.Lock] = {}
_PREVIEW_LOCKS_GUARD = threading.Lock()


def _preview_lock(key: str) -> threading.Lock:
    with _PREVIEW_LOCKS_GUARD:
        lock = _PREVIEW_LOCKS.get(key)
        if lock is None:
            lock = _PREVIEW_LOCKS[key] = threading.Lock()
        return lock


def write_preview(path: Path, data: bytes) -> bool:
    """Zapis podglądu na dysk (błąd dysku nie może ubić renderu)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return True
    except OSError:  # noqa: BLE001 — brak miejsca/praw = działamy dalej z pamięci
        return False


def convert_preview(data: bytes) -> Optional[bytes]:
    """Stary podgląd (filtr 0, pełny rozmiar) → nowy format (mniejszy, filtr Up)."""
    rows = png_decode_rows(data)
    if rows is None:
        return None
    return png_encode(rows)


def step_image(step: Dict[str, Any]) -> bytes:
    """
    PNG podglądu kroku citizena (pamięć → dysk `cache/step_previews_v2` → render).
    KAŻDY krok pokazuje efekt TAK JAK W GRZE, na wspólnym rendererze sky_png:
      • nieba         — kolory zenith/horizon/azimuth + chmury + księżyc z sggd
      • słońce/księżyc— pozycja tarczy / wielkość księżyca
      • pogoda        — zachmurzenie, burza, deszcz
      • postfx        — grading vivid/cold/film na całej scenie
      • kombat        — plamy krwi na ziemi (kill) i w powietrzu (headshot)

    Render jest kosztowny (~2-4 s), więc wynik zapisujemy na dysku w wersji
    pomniejszonej i mocniej skompresowanej — kafel waży ~3x mniej, a po restarcie
    bota podglądy ładują się z dysku w milisekundach.
    """
    key = step_image_key(step)
    cached = _IMAGE_CACHE.get(key)
    if cached is not None:
        return cached

    disk = PREVIEW_DIR / f"{key}.png"
    if disk.exists():
        data = disk.read_bytes()
        if data[:4] == b"\x89PNG":
            _IMAGE_CACHE[key] = data
            return data

    with _preview_lock(key):
        cached = _IMAGE_CACHE.get(key)  # inny wątek mógł już zdążyć policzyć
        if cached is not None:
            return cached

        legacy = LEGACY_PREVIEW_DIR / f"{key}.png"
        if legacy.exists():            # cache ze starszej wersji — przeliczamy
            try:
                converted = convert_preview(legacy.read_bytes())
            except OSError:
                converted = None
            if converted is not None:
                _IMAGE_CACHE[key] = converted
                write_preview(disk, converted)
                return converted

        png = _render_step_image(step)
        _IMAGE_CACHE[key] = png
        write_preview(disk, png)
        return png


def preview_cache_stats() -> Dict[str, int]:
    """Ile podglądów jest policzonych w pamięci / na dysku (dla /api/stats)."""
    try:
        on_disk = sum(1 for _ in PREVIEW_DIR.glob("*.png"))
    except OSError:
        on_disk = 0
    return {"memory": len(_IMAGE_CACHE), "disk": on_disk, "steps": len(CITIZEN_STEPS)}


def migrate_preview_cache() -> int:
    """
    Jednorazowe przeliczenie starego cache podglądów (`cache/step_previews`)
    na nowy format: mniejszy obraz + filtr Up. Dzięki temu po aktualizacji bot
    nie renderuje 278 obrazków od zera — konwertuje gotowe w ~1 minutę.
    """
    if not LEGACY_PREVIEW_DIR.exists():
        return 0
    converted = 0
    for path in sorted(LEGACY_PREVIEW_DIR.glob("*.png")):
        target = PREVIEW_DIR / path.name
        if target.exists():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        new_data = convert_preview(data)
        if new_data is None or not write_preview(target, new_data):
            continue
        converted += 1
    if converted:
        img_log.info("Przeliczono %s podglądów na nowy (mniejszy) format.", converted)
    return converted


def prewarm_previews() -> int:
    """
    Dogrzanie podglądów w tle: brakujące obrazki renderują się zanim gracz
    otworzy zakładkę, więc kafle pojawiają się od razu (a nie po 2-4 s każdy).
    """
    rendered = 0
    for step in CITIZEN_STEPS:
        key = step_image_key(step)
        if key in _IMAGE_CACHE or (PREVIEW_DIR / f"{key}.png").exists():
            continue
        if (LEGACY_PREVIEW_DIR / f"{key}.png").exists():
            continue                    # migracja zajmie się tym plikiem
        try:
            step_image(step)
            rendered += 1
        except Exception as exc:  # noqa: BLE001 — dogrzewanie nie może ubić bota
            img_log.warning("Nie dogrzano podglądu %s: %s", step.get("id"), exc)
            continue
        time.sleep(0.05)                # oddychamy — pętla zdarzeń i gracze mają priorytet
    if rendered:
        img_log.info("Dogrzano %s podglądów kroków citizena.", rendered)
    return rendered


def start_preview_worker() -> Optional[threading.Thread]:
    """
    Wątek w tle: najpierw konwertuje stary cache, potem dogrzewa brakujące
    podglądy. Sterowanie: PREWARM_PREVIEWS=0 wyłącza (np. na słabym VPS-ie).
    """
    if str(os.getenv("PREWARM_PREVIEWS", "1")).strip().lower() in {"0", "false", "no", "off"}:
        img_log.info("Dogrzewanie podglądów wyłączone (PREWARM_PREVIEWS=0).")
        return None

    def worker() -> None:
        try:
            migrate_preview_cache()
            prewarm_previews()
        except Exception as exc:  # noqa: BLE001
            img_log.warning("Dogrzewanie podglądów przerwane: %s", exc)

    thread = threading.Thread(target=worker, name="preview-warmup", daemon=True)
    thread.start()
    return thread


# ---------------------------------------------------------------------------
# PALETY PODGLĄDÓW — kafelek pokazuje DOKŁADNIE ten kolor/efekt, który trafi
# do pliku w paczce (te same wartości, których używa generator z citizen_mods).
# ---------------------------------------------------------------------------

_WATER_RGB = {"clean": (46, 118, 158), "dark": (10, 22, 32), "mirror": (96, 150, 186),
              "calm": (34, 92, 132), "storm": (24, 64, 96), "no-foam": (40, 104, 144)}
_FOG_AMOUNT = {"off": 0.0, "light": 0.35, "dense": 0.7, "horror": 0.95, "no-volume": 0.15}
_CLOUD_TINT = {"white": (250, 250, 252), "pink": (255, 190, 215), "purple": (200, 160, 255),
               "red": (255, 150, 130), "cyan": (150, 235, 245), "green": (170, 245, 170)}
_CLOUD_DENSITY = {"off": 0.0, "dense": 0.9, "soft": 0.45, "cotton": 0.7,
                  "dark": 0.8, "golden": 0.5}
_POSTFX_GRADE = {"vivid": "vivid", "film": "film", "cold": "cold", "contrast": "film",
                 "desat": "film", "neutral": None, "bloom-off": "vivid",
                 "vignette-off": None}
_BLUR_AMOUNT = {"motion-off": 0.6, "screen-off": 0.9, "dof-off": 0.5, "lens-off": 0.4,
                "chroma-off": 0.3, "bokeh-off": 0.9, "all-off": 1.5}
_LIGHT_RGB = {"street-bright": (255, 220, 150), "street-off": (12, 12, 16),
              "night-bright": (200, 212, 240), "ped-visible": (255, 200, 180),
              "warm": (255, 190, 120), "cold": (170, 205, 255),
              "interiors": (255, 226, 172)}
_WEATHER_PREVIEW = {"always-sunny": (0.0, False, 0.15), "always-rain": (0.9, False, 0.85),
                    "stormy": (0.8, True, 0.95), "always-fog": (0.0, False, 0.6),
                    "smog": (0.0, False, 0.7), "snow": (0.6, False, 0.8),
                    "xmas": (0.5, False, 0.7), "balanced": (0.0, False, 0.4)}
_TIME_MODES = {"always-day": (1.0, "high", False), "always-night": (0.22, "mid", True),
               "golden": (0.95, "low", False), "sunrise": (0.8, "low", False),
               "dynamic": (1.0, "mid", False)}
_KILL_RGB = {name: tuple(int(round(c * 255)) for c in data["ped"])
             for name, data in citizen_mods.KILL_COLORS.items()}
_KILL_LEVEL = {"subtle": 0.4, "normal": 0.85, "strong": 1.4, "extreme": 2.1, "off": 0.0}
_KILL_BLUR = {"off": 0.0, "soft": 0.6, "strong": 1.4}
_FIRE_POWER = {"short": 0.6, "long": 1.1, "eternal": 1.8, "off": 0.0}
_EXPL_POWER = {"tiny": 0.5, "big": 1.2, "huge": 1.9, "insane": 2.6}
_MOON_RGB = {"red": (235, 90, 80), "blue": (150, 190, 255), "huge": None, "small": None,
             "dark": (120, 120, 140)}
_SUN_RGB = {"warm": (255, 205, 130), "cold": (205, 225, 255), "golden": (255, 180, 80),
            "soft": (255, 250, 235), "rays-off": (255, 250, 235)}
_VISUAL_RAIN = {"off": 0.0, "light": 0.35, "heavy": 0.75, "insane": 1.0}


def _sky_for_time(base: Dict[str, float], mode: str) -> Tuple[Dict[str, float], str, bool]:
    """Niebo dla trybu czasu (time.xml): jasność, słońce/księżyc, barwy pory dnia."""
    mult, sun, moon_big = _TIME_MODES.get(mode, (1.0, "mid", False))
    sky = dict(base)
    if mult != 1.0:
        for name, value in list(sky.items()):
            if name.endswith(("_col_r", "_col_g", "_col_b")):
                sky[name] = max(0.0, float(value) * mult)
    if mode == "golden":
        sky.update({"sky_horizon_col_r": 0.98, "sky_horizon_col_g": 0.70,
                    "sky_horizon_col_b": 0.38, "sky_azimuth_east_col_r": 1.0,
                    "sky_azimuth_east_col_g": 0.60, "sky_azimuth_east_col_b": 0.22})
    elif mode == "sunrise":
        sky.update({"sky_horizon_col_r": 0.92, "sky_horizon_col_g": 0.72,
                    "sky_horizon_col_b": 0.80, "sky_azimuth_east_col_r": 1.0,
                    "sky_azimuth_east_col_g": 0.72, "sky_azimuth_east_col_b": 0.58})
    elif mode == "always-night":
        sky.update({"sky_moon_iten": 0.95, "sky_moon_disc_size": 1.7,
                    "sky_cloud_density_mult": 0.22})
    return sky, sun, moon_big


def _render_step_image(step: Dict[str, Any]) -> bytes:
    """Właściwy render podglądu kroku (wolna ścieżka, raz na krok)."""
    key = step_image_key(step)
    if key not in _IMAGE_CACHE:
        params = step.get("gen_params") or {}
        sid = str(step.get("id", ""))
        seed = _step_seed(step)
        base = sky_preset_params("sky-anime")  # neutralna scena bazowa dla efektów

        # 0) NOWE OPCJE (krew, traces, opony, dekale, czas, woda, mgła, światło…)
        #    — podgląd liczony WPROST z parametrów kroku, więc kafel nie kłamie.
        preview = _catalog_preview(base, params, step, seed)
        if preview is not None:
            return preview

        if step.get("gen_file") == "timecycle/MATOL.xml" and params.get("sky_preset"):
            # niebo: dokładne parametry presetu (+ clouds off/dense)
            sky_params = sky_preset_params(str(params["sky_preset"]), params)
            return sky_png(sky_params, seed=seed)
        elif sid == "sun-always-noon":
            return sky_png(base, seed=seed, sun="high")
        elif sid == "sun-low-golden":
            gold = dict(base)
            gold.update({"sky_horizon_col_r": 0.95, "sky_horizon_col_g": 0.72,
                         "sky_horizon_col_b": 0.42, "sky_azimuth_east_col_r": 1.0,
                         "sky_azimuth_east_col_g": 0.62, "sky_azimuth_east_col_b": 0.25})
            return sky_png(gold, seed=seed, sun="low")
        elif sid == "moon-huge":
            return sky_png(base, seed=seed, moon_big=True)
        elif sid == "weather-always-clear":
            clear = dict(base)
            clear["sky_cloud_density_mult"] = 0.18
            return sky_png(clear, seed=seed)
        elif sid == "weather-stormy":
            return sky_png(base, seed=seed, storm=True, rain=0.85)
        elif sid == "rain-off":
            return sky_png(base, seed=seed, rain=0.0)
        elif sid == "rain-heavy":
            return sky_png(base, seed=seed, rain=1.0)
        elif sid == "postfx-vivid":
            return sky_png(base, seed=seed, grade="vivid")
        elif sid == "postfx-cold":
            return sky_png(base, seed=seed, grade="cold")
        elif sid == "postfx-film":
            return sky_png(base, seed=seed, grade="film")
        elif sid == "blood-anime":
            return sky_png(base, seed=seed, blood=1.0)
        elif sid == "blood-minimal":
            return sky_png(base, seed=seed, blood=0.35)
        elif sid == "blood-none":
            return sky_png(base, seed=seed, blood=0.0)
        elif sid == "kill-extreme":
            return sky_png(base, seed=seed, blood=1.0)
        elif sid == "kill-strong":
            return sky_png(base, seed=seed, blood=0.6)
        elif sid == "kill-off":
            return sky_png(base, seed=seed, blood=0.0)
        elif sid == "head-massive":
            return sky_png(base, seed=seed, blood_head=1.0)
        elif sid == "head-big":
            return sky_png(base, seed=seed, blood_head=0.6)
        elif sid == "head-off":
            return sky_png(base, seed=seed, blood_head=0.0)
        else:
            # pozostałe (chmury-off/dense mają sky_preset=None) — schemat z palety
            sky, ground, accent = STEP_COLORS.get(sid, ("4a9dff", "6f8f45", "ffd166"))
            return scene_png(sky, ground, accent)
    # fallback: schematyczny krajobraz
    sky, ground, accent = STEP_COLORS.get(str(step.get("id")), ("4a9dff", "6f8f45", "ffd166"))
    return scene_png(sky, ground, accent)


def skin_image(weapon: Dict[str, Any], skin: Dict[str, Any]) -> bytes:
    """PNG podglądu skina broni (paleta i wzór dobierane deterministycznie po id)."""
    key = skin_image_key(weapon, skin)
    if key not in _IMAGE_CACHE:
        seed = zlib.crc32(str(skin.get("id", "")).encode())
        metal, accent = SKIN_PALETTES[seed % len(SKIN_PALETTES)]
        _IMAGE_CACHE[key] = weapon_png(metal, accent, (seed // len(SKIN_PALETTES)) % SKIN_PATTERNS)
    return _IMAGE_CACHE[key]


def image_bytes_for(key: str) -> Optional[bytes]:
    """PNG po kluczu (`step-...` / `skin-...`) — dla endpointu /img/."""
    clean = _safe_key(str(key).replace(".png", ""))  # .png zdejmujemy PRZED czyszczeniem
    if clean in _IMAGE_CACHE:
        return _IMAGE_CACHE[clean]
    if clean.startswith("step-"):
        for step in CITIZEN_STEPS:
            if step_image_key(step) == clean:
                return step_image(step)
    if clean.startswith("skin-"):
        for weapon in all_weapons():
            for skin in weapon["skins"]:
                if skin_image_key(weapon, skin) == clean:
                    return skin_image(weapon, skin)
    return None


async def image_bytes_async(key: str) -> Optional[bytes]:
    """
    Podgląd policzony poza pętlą zdarzeń.

    Render nieba to 2-4 s pracy w Pythonie — gdyby liczył się w wątku serwera,
    w tym czasie strona i wybory gracza STAŁYBY w miejscu. Tutaj render idzie do
    puli wątków (max PREVIEW_THREADS naraz), a serwer dalej obsługuje kliknięcia.
    """
    clean = _safe_key(str(key).replace(".png", ""))
    cached = _IMAGE_CACHE.get(clean)
    if cached is not None:
        return cached
    loop = asyncio.get_running_loop()
    async with preview_gate():
        return await loop.run_in_executor(_PREVIEW_POOL, image_bytes_for, key)


def public_image_url(key: str) -> str:
    """Adres obrazka na serwerze bota (PUBLIC_URL + /img)."""
    return f"{PUBLIC_URL}/img/{_safe_key(key)}.png"


def public_url_is_public() -> bool:
    """Czy PUBLIC_URL wskazuje publiczny adres (a nie localhost)?"""
    return not host_is_local(PUBLIC_URL)


def embed_image_ref(key: str) -> str:
    """URL do embeda: publiczny /img/... albo załącznik `attachment://`."""
    if public_url_is_public():
        return public_image_url(key)
    return f"attachment://{_safe_key(key)}.png"


def image_attachment(key: str, data: bytes) -> Optional[discord.File]:
    """Załącznik z podglądem (tylko gdy nie mamy publicznego URL-a)."""
    if public_url_is_public():
        return None
    return discord.File(io.BytesIO(data), filename=f"{_safe_key(key)}.png")


def public_download_url(token: str) -> Optional[str]:
    """Link HTTP do paczki — TYLKO gdy PUBLIC_URL jest publiczny (localhost = None)."""
    return f"{PUBLIC_URL}/download/{token}" if public_url_is_public() else None


def public_preview_url(token: Optional[str]) -> Optional[str]:
    """Link HTTP do podglądu — TYLKO gdy PUBLIC_URL jest publiczny (localhost = None)."""
    if not token or not public_url_is_public():
        return None
    return f"{PUBLIC_URL}/preview/{token}"


def preview_attachment(token: Optional[str]) -> Optional[discord.File]:
    """Podgląd kombinacji jako plik HTML (gdy nie ma publicznego URL-a)."""
    if not token or public_url_is_public():
        return None
    preview = STORAGE.get_preview(token)
    if not preview:
        return None
    data = io.BytesIO(str(preview.get("html") or "").encode("utf-8"))
    return discord.File(data, filename=f"podglad-{token[:8]}.html")


def split_package_for_discord(zip_path: Path, limit_bytes: int) -> List[Path]:
    """
    Dzieli paczkę na części mieszczące się w limicie załącznika Discorda.

    Każda część to osobny ZIP z tymi samymi ścieżkami w środku, więc po wypakowaniu
    wszystkich części do jednego folderu powstaje komplet. Gdy paczka mieści się
    w limicie — zwraca oryginał (bez kopiowania).
    """
    zip_path = Path(zip_path)
    try:
        if zip_path.stat().st_size <= limit_bytes:
            return [zip_path]
    except OSError as exc:
        fp_log.warning("Brak paczki do wyslania (%s): %s", zip_path, exc)
        return []
    parts: List[Path] = []
    try:
        with zipfile.ZipFile(zip_path) as source:
            groups: List[List[zipfile.ZipInfo]] = []
            current: List[zipfile.ZipInfo] = []
            current_size = 0
            for info in source.infolist():
                if info.is_dir():
                    continue
                entry_size = max(int(info.compress_size or 0), 1)
                if current and current_size + entry_size > limit_bytes:
                    groups.append(current)
                    current, current_size = [], 0
                current.append(info)
                current_size += entry_size
            if current:
                groups.append(current)
            total = len(groups)
            for number, group in enumerate(groups, start=1):
                part = zip_path.with_name(
                    f"{zip_path.stem}-czesc{number}z{total}{zip_path.suffix}")
                with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as target:
                    for info in group:
                        target.writestr(info, source.read(info.filename))
                parts.append(part)
    except (OSError, zipfile.BadZipFile) as exc:
        fp_log.warning("Nie podzielono paczki %s: %s", zip_path.name, exc)
        return []
    return parts


def delivery_header_lines(file_name: str, size_bytes: int, file_count: int, build_name: str,
                          link: Optional[str], ttl_minutes: int) -> List[str]:
    """Nagłówek wiadomości z paczką: link HTTP albo informacja o załączniku."""
    if link:
        lines = [f"**Pobierz:** [{file_name}]({link})", "",
                 f"🕒 Link ważny: **{ttl_minutes} minut** "
                 "(potem uruchom paczkę jeszcze raz przyciskiem 📦 Zakończ)."]
    else:
        lines = ["📎 **Paczka leci w załączniku poniżej** — zapisz plik i rozpakuj.",
                 "💡 Stały link do pobrania pojawi się, gdy ustawisz `PUBLIC_URL` na publiczny "
                 "adres bota (Render/Railway nadają go same — szczegóły w START-TUTAJ.txt)."]
    lines += [
        "",
        f"📦 Rozmiar: **{size_bytes / 1024 / 1024:.2f} MB**",
        f"📁 Plików: {file_count}",
        f"🎮 Build: **{build_name}**",
        "",
        "**Instalacja:** rozpakuj i postępuj według `INSTRUKCJA.txt` "
        "(w paczce też `manifest.json` i `HASHES.txt`).",
    ]
    return lines


async def send_package_attachments(channel: Optional[discord.abc.Messageable], zip_path: Path,
                                   *, preview_token: Optional[str] = None) -> bool:
    """
    Wysyła paczkę jako załącznik(i) Discorda — pobieranie działa bez publicznego URL-a.

    Paczki większe niż limit Discorda są dzielone na części i wysyłane partiami po 10
    plików; podgląd kombinacji (HTML) leci razem z pierwszą partią.
    """
    if channel is None:
        return False
    parts = await asyncio.to_thread(split_package_for_discord,
                                    Path(zip_path), DISCORD_ATTACH_BYTES)
    parts = [Path(p) for p in parts if Path(p).exists()]
    if not parts:
        return False
    note = ("📦 **Twoja paczka** — zapisz plik z załącznika i rozpakuj."
            if len(parts) == 1 else
            f"📦 **Twoja paczka w {len(parts)} częściach** — pobierz **wszystkie** i wypakuj "
            "do tego samego folderu (np. `Z:\\FiveM`). Kolejność nie ma znaczenia.")
    preview = preview_attachment(preview_token)
    if preview is not None:
        note += "\n🖼️ Podgląd kombinacji: otwórz dołączony plik HTML w przeglądarce."
    sent = 0
    for start in range(0, len(parts), DISCORD_MAX_ATTACHMENTS):
        batch = parts[start:start + DISCORD_MAX_ATTACHMENTS]
        files: List[discord.File] = []
        try:
            files = [discord.File(p, filename=p.name) for p in batch]
            if start == 0 and preview is not None:
                files.append(preview)
            await channel.send(content=note if start == 0 else None, files=files)
            sent += len(batch)
        except discord.HTTPException as exc:
            fp_log.error("Nie wyslano czesci paczki jako zalacznika: %s", exc)
            break
        except OSError as exc:
            fp_log.error("Blad pliku przy wysylce paczki: %s", exc)
            break
        finally:
            for handle in files:
                try:
                    handle.close()
                except Exception:  # noqa: BLE001 — zamknięcie nie może wywalić wysyłki
                    pass
    return sent > 0 and sent >= len(parts)


def item_image_data_uri(item: Dict[str, Any]) -> str:
    """Obrazek pozycji jako data URI (do strony podglądu, bez hostingu)."""
    step_id = str(item.get("id") or "")
    weapon_id = str(item.get("weapon_id") or "")
    if weapon_id and step_id:
        weapon = find_weapon(weapon_id)
        if weapon:
            for skin in weapon["skins"]:
                if skin["id"] == step_id:
                    data = skin_image(weapon, skin)
                    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")
    for step in CITIZEN_STEPS:
        if step["id"] == step_id:
            data = step_image(step)
            return "data:image/png;base64," + base64.b64encode(data).decode("ascii")
    return ""


def render_preview_html(items: Sequence[Dict[str, Any]], conflicts: Sequence[Dict[str, Any]] = (),
                        build: str = "", title: str = "Podgląd kombinacji") -> str:
    """Buduje stronę HTML z dokładnie wybraną kombinacją modyfikacji."""
    cards = []
    for item in items:
        tag = f'<span class="tag">{html.escape(str(item.get("group") or ""))}</span>' if item.get("group") else ""
        source = str(item.get("image") or "") or item_image_data_uri(item)
        image = f'<img src="{html.escape(source)}" alt="podglad">' if source else ""
        cards.append(
            f'<div class="card">{image}<div class="body">{tag}'
            f'<div class="name">{html.escape(str(item.get("name") or ""))}</div>'
            f'<div class="desc">{html.escape(str(item.get("description") or ""))}</div>'
            f"</div></div>"
        )

    conflict_box = ""
    if conflicts:
        entries = "".join(
            f'<li><span class="mono">{html.escape(c["file"])}</span><br>'
            f'wybrano: {html.escape(", ".join(c["candidates"]))}<br>'
            f'<b>zainstalowano: {html.escape(c["winner"])}</b><br>'
            f'pominięto: {html.escape(", ".join(c["dropped"]))}</li>'
            for c in conflicts
        )
        conflict_box = (
            '<div class="box"><h2>⚠️ Wykryte konflikty plików (auto-rozwiązane)</h2>'
            f"<ul>{entries}</ul></div>"
        )

    return f"""<!doctype html>
<html lang="pl"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} — FiveM Mod Foundry</title>
<style>{PREVIEW_CSS}</style>
</head><body>
<header><div class="wrap">
<h1>🏭 {html.escape(title)}</h1>
<div class="sub">FiveM Mod Foundry • podgląd wygenerowany automatycznie{' • build: ' + html.escape(build) if build else ''}</div>
</div></header>
<div class="wrap">
<div class="box"><h2>📦 Twoja kombinacja ({len(items)} pozycji)</h2>
<div class="desc">Dokładnie te modyfikacje wejdą do paczki ZIP. Zdjęcia pokazują efekt w grze.</div></div>
{conflict_box}
<div class="grid">{''.join(cards) or '<div class="box"><div class="desc">Brak wybranych pozycji.</div></div>'}</div>
</div>
<footer>Mody klienckie działają tylko na serwerach, które ich nie blokują — sprawdź regulamin swojego serwera.<br>
Link wygasa automatycznie razem z paczką ({DOWNLOAD_TTL_MINUTES} min od wygenerowania).</footer>
</body></html>"""

# ============================================================================
# 9.5. CACHE PLIKÓW BAZOWYCH (mniej pobierania = szybsze paczki)
# ============================================================================

cache_log = log("FileCache")


class FileCache:
    """
    Lokalny cache czystych plików bazowych.

    Zamiast pobierać ten sam mod z internetu przy każdej paczce, bot zapisuje
    go raz w folderze `cache/` i przy kolejnych zamówieniach kopiuje lokalnie
    (dziesiątki razy szybciej niż pobieranie z sieci).

    Klucz cache = SHA-1 z adresu URL, więc zmiana linku w konfiguracji sama
    unieważnia stary wpis. Wpisy starsze niż CACHE_TTL_HOURS są usuwane.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(url: str) -> str:
        """Klucz cache dla adresu URL."""
        return hashlib.sha1((url or "").encode("utf-8")).hexdigest()

    def path_for(self, url: str) -> Path:
        """Ścieżka pliku w cache (z zachowaniem rozszerzenia)."""
        extension = Path(urlparse(url).path).suffix.lower() or ".bin"
        return self.directory / f"{self.key(url)}{extension}"

    def lookup(self, url: str) -> Optional[Path]:
        """Zwraca ścieżkę z cache (albo None, gdy trzeba pobrać z sieci)."""
        if not CACHE_ENABLED:
            return None
        path = self.path_for(url)
        try:
            if not path.exists():
                self.misses += 1
                return None
            age_hours = (time.time() - path.stat().st_mtime) / 3600
            if age_hours > CACHE_TTL_HOURS:
                path.unlink(missing_ok=True)
                self.misses += 1
                return None
        except OSError:
            self.misses += 1
            return None
        self.hits += 1
        return path

    def store(self, url: str, source: Path) -> Optional[Path]:
        """Zapisuje pobrany plik do cache."""
        if not CACHE_ENABLED:
            return None
        target = self.path_for(url)
        try:
            if target.exists() and target.resolve() == Path(source).resolve():
                return target
            shutil.copyfile(source, target)
            cache_log.info("Cache: zapisano %s (%.1f KB)", target.name,
                           target.stat().st_size / 1024)
            return target
        except OSError as exc:
            cache_log.warning("Nie zapisano do cache: %s", exc)
            return None

    def files(self) -> List[Path]:
        """Pliki w cache."""
        return [p for p in self.directory.glob("*") if p.is_file()]

    def size_bytes(self) -> int:
        """Rozmiar cache w bajtach."""
        total = 0
        for path in self.files():
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return total

    def sweep(self) -> int:
        """Usuwa przeterminowane wpisy. Zwraca liczbę zwolnionych bajtów."""
        freed = 0
        for path in self.files():
            try:
                if time.time() - path.stat().st_mtime > CACHE_TTL_HOURS * 3600:
                    freed += path.stat().st_size
                    path.unlink(missing_ok=True)
            except OSError:
                continue
        if freed:
            cache_log.info("Cache: zwolniono %.1f MB", freed / 1024 / 1024)
        return freed

    def clear(self) -> int:
        """Czyści cały cache. Zwraca zwolnione bajty."""
        freed = 0
        for path in self.files():
            try:
                freed += path.stat().st_size
                path.unlink(missing_ok=True)
            except OSError:
                continue
        return freed

    def stats(self) -> Dict[str, Any]:
        """Statystyki cache (do /status)."""
        return {
            "enabled": CACHE_ENABLED,
            "files": len(self.files()),
            "bytes": self.size_bytes(),
            "hits": self.hits,
            "misses": self.misses,
            "ttl_hours": CACHE_TTL_HOURS,
        }


FILE_CACHE = FileCache(CACHE_DIR)


# ============================================================================
# 10. STORAGE — paczki ZIP i podglądy (TTL + auto-sprzątanie)
# ============================================================================

store_log = log("Storage")


def new_token() -> str:
    """Kryptograficznie losowy token (32 znaki hex) — linków nie da się zgadnąć."""
    return os.urandom(16).hex()


def directory_size_bytes(directory: Path) -> int:
    """Rozmiar katalogu w bajtach (rekurencyjnie, odporne na bledy IO)."""
    total = 0
    if not directory.exists():
        return 0
    for path in directory.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


class Storage:
    """
    Magazyn paczek ZIP i podglądów HTML z automatycznym wygasaniem
    oraz Garbage Collectorem (auto-czyszczenie dysku).

    Cykl życia paczki:
      1. wygenerowana -> link ważny DOWNLOAD_TTL_MINUTES,
      2. pobrana przez gracza -> usuwana DELETE_AFTER_DOWNLOAD_MINUTES po pobraniu,
      3. kanał sesji zamknięty -> natychmiastowe usunięcie paczek użytkownika,
      4. wygasła bez pobrania -> usuwana przez GC.
    """

    def __init__(self) -> None:
        self.packages: Dict[str, Dict[str, Any]] = {}
        self.previews: Dict[str, Dict[str, Any]] = {}
        self.gc_runs = 0
        self.freed_bytes = 0
        self.deleted_packages = 0

    # --- paczki ---
    def register(self, file_path: Path, file_name: str, size: int, file_count: int,
                 user_id: int, workspace: Optional[Path] = None) -> str:
        token = new_token()
        self.packages[token] = {
            "file_path": Path(file_path), "file_name": file_name, "size": size,
            "file_count": file_count, "user_id": user_id,
            "workspace": Path(workspace) if workspace else None,
            "created_at": time.time(), "downloaded_at": None, "downloads": 0,
        }
        return token

    def get(self, token: str) -> Optional[Dict[str, Any]]:
        return self.packages.get(token)

    def mark_downloaded(self, token: str) -> None:
        """Oznacza pierwszą pełną wysyłkę paczki — od tego czasu liczy się TTL."""
        package = self.packages.get(token)
        if not package:
            return
        package["downloads"] = package.get("downloads", 0) + 1
        if not package.get("downloaded_at"):
            package["downloaded_at"] = time.time()
            store_log.info("Paczka %s pobrana — usunę ja za %s min",
                           package["file_name"], DELETE_AFTER_DOWNLOAD_MINUTES)

    def remove(self, token: str, reason: str = "TTL") -> None:
        pkg = self.packages.pop(token, None)
        if not pkg:
            return
        freed = 0
        file_path = Path(pkg["file_path"])
        try:
            if file_path.exists():
                freed += file_path.stat().st_size
                file_path.unlink()
        except OSError as exc:
            store_log.warning("Nie usunieto ZIPa: %s", exc)
        if pkg.get("workspace"):
            freed += directory_size_bytes(Path(pkg["workspace"]))
            shutil.rmtree(pkg["workspace"], ignore_errors=True)
        self.freed_bytes += freed
        self.deleted_packages += 1
        store_log.info("Usunieto paczke %s (%s, zwolniono %.2f MB)",
                       pkg["file_name"], reason, freed / 1024 / 1024)

    def remove_user_packages(self, user_id: int, reason: str = "kanał zamknięty") -> int:
        """Usuwa wszystkie paczki użytkownika (np. gdy zamknie kanał sesji)."""
        tokens = [t for t, p in self.packages.items() if p.get("user_id") == user_id]
        for token in tokens:
            self.remove(token, reason)
        return len(tokens)

    # --- podglądy ---
    def register_preview(self, html_text: str, title: str, user_id: int) -> str:
        token = new_token()
        self.previews[token] = {
            "html": html_text, "title": title, "user_id": user_id, "created_at": time.time(),
        }
        return token

    def get_preview(self, token: str) -> Optional[Dict[str, Any]]:
        return self.previews.get(token)

    # --- GARBAGE COLLECTOR ---
    def sweep(self) -> Dict[str, Any]:
        """
        Pełny cykl czyszczenia dysku.
        Zwraca raport ze statystykami (ile usunięto, ile zwolniono).
        """
        now = time.time()
        self.gc_runs += 1
        removed = 0
        freed_before = self.freed_bytes

        # 1. Paczki pobrane — kasujemy DELETE_AFTER_DOWNLOAD_MINUTES po pobraniu
        for token, package in list(self.packages.items()):
            downloaded_at = package.get("downloaded_at")
            if downloaded_at and now - downloaded_at > DELETE_AFTER_DOWNLOAD_MINUTES * 60:
                self.remove(token, "pobrana paczka")
                removed += 1

        # 2. Paczki niepobrane — kasujemy po DOWNLOAD_TTL_MINUTES
        for token, package in list(self.packages.items()):
            if now - package["created_at"] > DOWNLOAD_TTL_MINUTES * 60:
                self.remove(token, "wygasly link")
                removed += 1

        # 3. Podglądy
        for token in [t for t, p in self.previews.items()
                      if now - p["created_at"] > DOWNLOAD_TTL_MINUTES * 60]:
            self.previews.pop(token, None)

        # 4. Puste/porzucone katalogi robocze (także po restarcie bota)
        session_ttl = SESSION_TTL_MINUTES * 60
        for directory in list(WORKSPACES_DIR.glob("*")):
            try:
                if not directory.is_dir():
                    continue
                active = any(s.workspace == directory for s in SESSIONS.values())
                if not active and now - directory.stat().st_mtime > session_ttl:
                    self.freed_bytes += directory_size_bytes(directory)
                    shutil.rmtree(directory, ignore_errors=True)
                    store_log.info("GC: usunieto porzucony workspace %s", directory.name)
            except OSError:
                continue

        # 5. Katalogi budowy pozostawione przez przerwane zadania (starsze niż 1 h)
        for directory in list(WORKSPACES_DIR.glob("*/build-*")):
            try:
                if directory.is_dir() and now - directory.stat().st_mtime > 3600:
                    self.freed_bytes += directory_size_bytes(directory)
                    shutil.rmtree(directory, ignore_errors=True)
                    store_log.info("GC: usunieto osierocony build %s", directory.name)
            except OSError:
                continue

        # 6. Sieroty w downloads/ — ZIP-y zostawione przez crash / twardy restart
        known_zips = {Path(p["file_path"]).resolve() for p in self.packages.values()}
        for path in list(DOWNLOADS_DIR.glob("*.zip")):
            try:
                if path.resolve() in known_zips:
                    continue
                if now - path.stat().st_mtime > DOWNLOAD_TTL_MINUTES * 60:
                    freed = path.stat().st_size
                    path.unlink(missing_ok=True)
                    self.freed_bytes += freed
                    store_log.info("GC: usunieto osierocony ZIP %s (%.2f MB)",
                                   path.name, freed / 1024 / 1024)
            except OSError:
                continue

        # 7. Cache plików bazowych
        cache_freed = FILE_CACHE.sweep()

        report = {
            "removed": removed,
            "freed_bytes": (self.freed_bytes - freed_before) + cache_freed,
            "cache_freed_bytes": cache_freed,
            "runs": self.gc_runs,
        }
        if report["freed_bytes"]:
            store_log.info("GC: usunieto %s paczek, zwolniono %.2f MB",
                           removed, report["freed_bytes"] / 1024 / 1024)
        return report

    def disk_usage(self) -> Dict[str, int]:
        """Zużycie dysku przez bota (do /status i /czysc)."""
        return {
            "downloads": directory_size_bytes(DOWNLOADS_DIR),
            "workspaces": directory_size_bytes(WORKSPACES_DIR),
            "cache": directory_size_bytes(CACHE_DIR),
            "logs": directory_size_bytes(LOGS_DIR),
        }

    def stats(self) -> Dict[str, Any]:
        return {
            "packages": len(self.packages),
            "previews": len(self.previews),
            "downloaded": sum(1 for p in self.packages.values() if p.get("downloaded_at")),
            "deleted": self.deleted_packages,
            "freed_bytes": self.freed_bytes,
            "gc_runs": self.gc_runs,
        }


STORAGE = Storage()

# ============================================================================
# 11. SESJE UŻYTKOWNIKÓW (prywatne kanały-tickety)
# ============================================================================

sess_log = log("Sessions")


class Session:
    """Stan jednej sesji kreatora (per użytkownik / kanał)."""

    def __init__(self, user_id: int, guild_id: int, channel_id: int) -> None:
        self.user_id = user_id
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.workspace = WORKSPACES_DIR / str(user_id)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.mode: Optional[str] = None          # 'citizen' | 'weapons'
        self.search_mode = False
        self.choices: List[str] = []             # kolejność wyboru = kolejność konfliktów
        self.weapon_skins: Dict[str, str] = {}   # weapon_id -> skin_id
        self.external_skins: Dict[str, Dict[str, str]] = {}
        self.search_results: List[Dict[str, Any]] = []
        self.search_query = ""                  # ostatnia fraza (paginacja wyników)
        self.search_page = 0                    # aktualna strona wyników
        self.searches_awarded: List[str] = []   # frazy, za które już dodano XP
        self.validation_issues: List[Dict[str, Any]] = []   # raport walidatora anty-crash
        self.fatal_skipped: List[str] = []                  # pliki odrzucone jako crash-prone
        self.build_id = DEFAULT_BUILD_ID
        self.preview_token: Optional[str] = None
        # Własne pliki gracza (przycisk 📎): plik wgrany na kanał sesji trafia
        # do paczki bez żadnego hostingu — bot kopiuje go lokalnie.
        self.uploads: List[Dict[str, Any]] = []
        self.upload_armed = False               # czekamy na załącznik gracza
        self.upload_target = "mods"             # gdzie zainstalować plik
        self.upload_kind = "citizen"            # 'citizen' | 'weapons'
        self.created_at = time.time()
        self.last_activity = time.time()
        self.delivered_at: Optional[float] = None

    def touch(self) -> None:
        self.last_activity = time.time()

    def chosen_steps(self) -> List[Dict[str, str]]:
        """Wybrane kroki citizena W KOLEJNOŚCI WYBORU (nie katalogu)."""
        by_id = {step["id"]: step for step in CITIZEN_STEPS}
        return [by_id[cid] for cid in self.choices if cid in by_id]

    def collect_skins(self) -> List[Dict[str, Any]]:
        """Wybrane skiny broni: z bazy + z wyszukiwarki .rpf."""
        out: List[Dict[str, Any]] = []
        for weapon in all_weapons():
            skin_id = self.weapon_skins.get(weapon["id"])
            if not skin_id:
                continue
            for skin in weapon["skins"]:
                if skin["id"] == skin_id:
                    out.append({**skin, "name": f"{weapon['name']} — {skin['name']}"})
        for skin in self.external_skins.values():
            out.append({
                "id": skin.get("id", ""), "name": skin.get("name", "Skin"),
                "description": skin.get("description", ""), "image": skin.get("imageUrl", ""),
                "file_url": skin.get("fileUrl", ""), "file_name": None,
                "target": skin.get("target") or "mods",
            })
        return out

    def collect_uploads(self) -> List[Dict[str, Any]]:
        """Własne pliki gracza w formacie pozycji paczki (kopiowane z dysku)."""
        return [dict(upload) for upload in self.uploads]

    def package_items(self, kind: str = "citizen") -> List[Dict[str, Any]]:
        """Wszystko, co wchodzi do paczki: presety (citizen) + skiny + własne pliki."""
        kept: List[Dict[str, Any]] = []
        if kind == "citizen":
            kept, _dropped, _conflicts = resolve_conflicts(self.chosen_steps())
        return list(kept) + self.collect_skins() + self.collect_uploads()


SESSIONS: Dict[int, Session] = {}


def session_create(user_id: int, guild_id: int, channel_id: int) -> Session:
    """Tworzy sesję dla użytkownika."""
    session = Session(user_id, guild_id, channel_id)
    SESSIONS[channel_id] = session
    sess_log.info("Nowa sesja user=%s channel=%s", user_id, channel_id)
    return session


def session_get(channel_id: int) -> Optional[Session]:
    """Pobiera sesję kanału (odświeżając czas aktywności)."""
    session = SESSIONS.get(channel_id)
    if session:
        session.touch()
    return session


def session_close(channel_id: int) -> None:
    """Usuwa sesję z pamięci (workspace sprząta storage po TTL)."""
    session = SESSIONS.pop(channel_id, None)
    if session:
        sess_log.info("Sesja zakonczona user=%s", session.user_id)


def session_by_user(user_id: int, guild_id: int) -> Optional[Session]:
    """Szuka aktywnej sesji użytkownika na serwerze."""
    for session in SESSIONS.values():
        if session.user_id == user_id and session.guild_id == guild_id:
            return session
    return None

# ============================================================================
# 12. ZGODY ADMINISTRATORA (pliki ryzykowne: .asi, archiwa)
# ============================================================================

appr_log = log("Approvals")


class Approval:
    """Zgłoszenie pliku ryzykownego do ręcznej akceptacji."""

    def __init__(self, file_url: str, file_name: str, reason: str,
                 user_id: int, guild_id: int, channel_id: int) -> None:
        self.id = "".join(random.choice("0123456789abcdef") for _ in range(8))
        self.file_url = file_url
        self.file_name = file_name
        self.reason = reason
        self.user_id = user_id
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.status = "pending"
        self.created_at = time.time()
        self.decided_at: Optional[float] = None


APPROVALS: Dict[str, Approval] = {}


def approval_request(file_url: str, file_name: str, reason: str,
                     user_id: int, guild_id: int, channel_id: int) -> Approval:
    """Tworzy zgłoszenie (albo zwraca istniejące oczekujące dla tego pliku)."""
    for approval in APPROVALS.values():
        if approval.file_url == file_url and approval.status == "pending":
            return approval
    approval = Approval(file_url, file_name, reason, user_id, guild_id, channel_id)
    APPROVALS[approval.id] = approval
    appr_log.warning("Zgloszenie #%s: %s (%s)", approval.id, file_name, reason)
    return approval


def approval_is_approved(file_url: str) -> bool:
    """Czy plik został już zaakceptowany przez administratora."""
    return any(a.file_url == file_url and a.status == "approved" for a in APPROVALS.values())


def approval_decide(approval_id: str, status: str) -> Optional[Approval]:
    """Ustawia decyzję administratora."""
    approval = APPROVALS.get(approval_id)
    if not approval:
        return None
    approval.status = status
    approval.decided_at = time.time()
    appr_log.info("Zgloszenie #%s -> %s", approval_id, status)
    return approval


def approvals_pending() -> List[Approval]:
    """Lista oczekujących zgłoszeń."""
    return [a for a in APPROVALS.values() if a.status == "pending"]


def approvals_sweep() -> None:
    """Usuwa zamknięte zgłoszenia starsze niż TTL."""
    now = time.time()
    ttl = APPROVAL_TTL_MINUTES * 60
    for key in [k for k, a in APPROVALS.items()
                if a.status != "pending" and now - (a.decided_at or a.created_at) > ttl]:
        APPROVALS.pop(key, None)

# ============================================================================
# 13. WERSJONOWANIE PACZEK (build GTA V)
# ============================================================================


def build_by_id(build_id: str) -> Dict[str, str]:
    """Zwraca definicję buildu (albo domyślny)."""
    for build in GAME_BUILDS:
        if build["id"] == build_id:
            return build
    return GAME_BUILDS[0]


def build_state_get() -> Optional[Dict[str, Any]]:
    """Odczytuje zapisany stan buildu."""
    try:
        return json.loads(BUILD_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_state_set(build_id: str, updated_by: str = "system") -> Dict[str, Any]:
    """Zapisuje aktywny build."""
    state = {"build_id": build_id, "updated_by": updated_by,
             "updated_at": datetime.now(timezone.utc).isoformat()}
    try:
        BUILD_STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        core_log.warning("Nie zapisano stanu buildu: %s", exc)
    return state

# ============================================================================
# 13.5. PROFILE GRACZY — XP, RANGI, ODZNAKI, PREFERENCJE, TOKENY PACZEK
#    (Creator Economy: aktywność = odblokowane, ekskluzywne presety)
# ============================================================================

profile_log = log("Profiles")

PROFILES_FILE = DATA_DIR / "profiles.json"
PACKS_FILE = DATA_DIR / "packs.json"
SECRET_FILE = DATA_DIR / "secret.key"

# --- konfiguracja systemu XP i rekomendacji ---
SMART_PINGS = os.getenv("SMART_PINGS", "1").strip().lower() not in ("0", "false", "no")
SMART_PING_COOLDOWN_MINUTES = int(os.getenv("SMART_PING_COOLDOWN_MINUTES", "180") or 180)
SMART_PING_MIN_SCORE = int(os.getenv("SMART_PING_MIN_SCORE", "6") or 6)
PRIORITY_LANE = os.getenv("PRIORITY_LANE", "1").strip().lower() not in ("0", "false", "no")
PRIORITY_LEVEL = int(os.getenv("PRIORITY_LEVEL", "1") or 1)
PERSONALIZE_PACKS = os.getenv("PERSONALIZE_PACKS", "1").strip().lower() not in ("0", "false", "no")

# Rangi twórców — im więcej budujesz, tym więcej odblokowujesz.
RANKS: List[Dict[str, Any]] = [
    {"level": 0, "name": "Nowicjusz", "xp": 0,
     "perk": "Podstawowe presety citizena i cała baza skinów."},
    {"level": 1, "name": "Rzemieślnik", "xp": 60,
     "perk": "Priorytetowa ścieżka w kolejce ZIP — Twoja paczka startuje nawet w tłoku."},
    {"level": 2, "name": "Konstruktor", "xp": 160,
     "perk": "Ekskluzywne presety: nocne niebo, woda FPS, POTATO teren, krew ANIME, dźwięki bass."},
    {"level": 3, "name": "Inżynier", "xp": 340,
     "perk": "POTATO FULL, custom crosshair i ekskluzywne skiny broni (.rpf)."},
    {"level": 4, "name": "Weteran", "xp": 640,
     "perk": "Odznaki na profilu i pierwszeństwo w testowaniu nowych presetów."},
    {"level": 5, "name": "Master Modder", "xp": 1100,
     "perk": "Wszystko odblokowane + prywatne rekomendacje modów na priv."},
]

XP_EVENTS: Dict[str, int] = {
    "build": 30,      # zbudowana paczka
    "option": 4,      # każda wybrana opcja w paczce
    "skin": 8,        # skin broni w paczce
    "search": 3,      # użycie wyszukiwarki .rpf
    "rate": 12,       # ocena skina / moda
    "report": 25,     # zgłoszenie błędu lub podejrzanego pliku
    "session": 10,    # ukończona sesja kreatora
    "daily": 15,      # pierwsza aktywność danego dnia
    "share": 6,       # podgląd/paczka wysłana dalej
}

# Ekskluzywne presety citizena (id kroku -> wymagany poziom twórcy)
EXCLUSIVE_STEPS: Dict[str, int] = {
    "sky-dark": 2,
    "water-fps": 2,
    "shadows-total": 3,
    "potato-terrain": 2,
    "potato-full": 3,
    "sound-bass": 2,
    "blood-anime": 2,
    "crosshair-custom": 3,
}
for _step_def in CITIZEN_STEPS:
    _step_def["min_level"] = EXCLUSIVE_STEPS.get(_step_def["id"], 0)

# Ekskluzywne skiny broni (id skina -> wymagany poziom)
EXCLUSIVE_SKINS: Dict[str, int] = {
    "heavypistol-chrome": 2,
    "smg-woodland": 2,
    "ak47-redline": 3,
    "pump-gold": 4,
}
for _category in WEAPON_CATEGORIES:
    for _weapon_def in _category["weapons"]:
        for _skin_def in _weapon_def["skins"]:
            _skin_def["min_level"] = EXCLUSIVE_SKINS.get(_skin_def["id"], 0)

BADGES: Dict[str, str] = {
    "pierwsza-paczka": "🥇 Pierwsza paczka — witamy w Foundry!",
    "konstruktor-10": "🏗️ 10 zbudowanych paczek citizen",
    "mistrz-25": "🏆 25 zbudowanych paczek",
    "zlota-bron": "🔫 5 skinów broni w paczkach",
    "odkrywca": "🔎 Odkrywca — użyłeś wyszukiwarki .rpf",
    "analityk": "🛡️ Analityk bezpieczeństwa — zgłoszenie podejrzanego pliku",
    "wszechstronny": "🧩 Wszechstronny — opcje z 6 grup w jednej paczce",
    "zna-buildy": "🎮 Zna buildy — paczki pod 3 różne wersje GTA V",
}


def level_for_xp(xp: int) -> int:
    """Poziom wynikający z XP (progi z RANKS)."""
    level = 0
    for rank in RANKS:
        if xp >= rank["xp"]:
            level = rank["level"]
    return level


def rank_for_level(level: int) -> Dict[str, Any]:
    """Definicja rangi dla poziomu."""
    return RANKS[max(0, min(int(level), len(RANKS) - 1))]


class Profile:
    """Profil twórcy: XP, ranga, odznaki, preferencje i historia paczek."""

    MAX_HISTORY = 20

    def __init__(self, user_id: int, username: str = "") -> None:
        self.user_id = int(user_id)
        self.username = username
        self.xp = 0
        self.builds = 0
        self.skins_picked = 0
        self.searches = 0
        self.reports = 0
        self.badges: List[str] = []
        self.preferences: Dict[str, int] = {}
        self.history: List[Dict[str, Any]] = []
        self.builds_seen: List[str] = []
        self.dm_opt_in = True
        self.last_dm_at = 0.0
        self.last_seen = 0.0
        self.days: List[str] = []

    # --- ranga ---
    @property
    def level(self) -> int:
        return level_for_xp(self.xp)

    @property
    def rank(self) -> Dict[str, Any]:
        return rank_for_level(self.level)

    def next_rank(self) -> Optional[Dict[str, Any]]:
        """Najbliższa ranga do zdobycia (albo None na maksie)."""
        for rank in RANKS:
            if rank["xp"] > self.xp:
                return rank
        return None

    def progress_line(self) -> str:
        """Pasek postępu do następnej rangi."""
        nxt = self.next_rank()
        if not nxt:
            return f"**{self.rank['name']}** (maksymalny poziom) • {self.xp} XP"
        span = max(1, nxt["xp"] - self.rank["xp"])
        done = max(0, self.xp - self.rank["xp"])
        filled = max(0, min(10, round(done / span * 10)))
        return (f"**{self.rank['name']}** (poziom {self.level}) • **{self.xp} XP**\n"
                f"`{'█' * filled}{'░' * (10 - filled)}` {done}/{span} XP do rangi "
                f"**{nxt['name']}**")

    # --- XP i odznaki ---
    def add_xp(self, event: str, amount: Optional[int] = None) -> Optional[str]:
        """Dodaje XP. Zwraca komunikat o awansie (albo None)."""
        before = self.level
        self.xp += int(XP_EVENTS.get(event, 0) if amount is None else amount)
        after = self.level
        if after > before:
            return (f"🎉 **Awans!** <@{self.user_id}> osiągnął poziom **{after}** — "
                    f"ranga **{rank_for_level(after)['name']}**\n"
                    f"🔓 Odblokowane: {rank_for_level(after)['perk']}")
        return None

    def remember(self, tags: Sequence[str], weight: int = 1) -> None:
        """Zapamiętuje preferencje gracza (podstawa rekomendacji modów)."""
        for tag in tags:
            key = str(tag).strip().lower()
            if key:
                self.preferences[key] = self.preferences.get(key, 0) + weight

    def top_tags(self, limit: int = 4) -> List[str]:
        """Najmocniejsze preferencje gracza."""
        return [tag for tag, _ in sorted(self.preferences.items(), key=lambda kv: kv[1],
                                        reverse=True)[:limit]]

    def badge(self, name: str) -> bool:
        """Przyznaje odznakę (zwraca True, jeśli to nowa odznaka)."""
        if name in self.badges or name not in BADGES:
            return False
        self.badges.append(name)
        return True

    def badges_text(self) -> str:
        return "\n".join(BADGES[b] for b in self.badges if b in BADGES) or "*Brak odznak — czas zacząć!*"

    def add_history(self, entry: Dict[str, Any]) -> None:
        """Historia paczek (maks. MAX_HISTORY) — do rekomendacji i statystyk."""
        self.history.insert(0, entry)
        del self.history[self.MAX_HISTORY:]

    def remember_build(self, build_id: str) -> None:
        if build_id and build_id not in self.builds_seen:
            self.builds_seen.append(build_id)
            del self.builds_seen[:-10]

    def touch_day(self) -> bool:
        """Zwraca True, jeśli to pierwsza aktywność gracza danego dnia."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.last_seen = time.time()
        if today in self.days:
            return False
        self.days.append(today)
        del self.days[:-60]
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id, "username": self.username, "xp": self.xp,
            "builds": self.builds, "skins": self.skins_picked, "searches": self.searches,
            "reports": self.reports, "badges": self.badges, "preferences": self.preferences,
            "history": self.history, "builds_seen": self.builds_seen,
            "dm_opt_in": self.dm_opt_in, "last_dm_at": self.last_dm_at,
            "last_seen": self.last_seen, "days": self.days,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Profile":
        profile = cls(int(data.get("user_id", 0)), data.get("username", ""))
        profile.xp = int(data.get("xp", 0))
        profile.builds = int(data.get("builds", 0))
        profile.skins_picked = int(data.get("skins", 0))
        profile.searches = int(data.get("searches", 0))
        profile.reports = int(data.get("reports", 0))
        profile.badges = list(data.get("badges") or [])
        profile.preferences = {str(k): int(v) for k, v in (data.get("preferences") or {}).items()}
        profile.history = list(data.get("history") or [])
        profile.builds_seen = list(data.get("builds_seen") or [])
        profile.dm_opt_in = bool(data.get("dm_opt_in", True))
        profile.last_dm_at = float(data.get("last_dm_at", 0.0))
        profile.last_seen = float(data.get("last_seen", 0.0))
        profile.days = list(data.get("days") or [])
        return profile


PROFILES: Dict[int, Profile] = {}
_profiles_loaded = False


def profiles_load(force: bool = False) -> None:
    """Wczytuje profile z data/profiles.json (raz na start bota)."""
    global _profiles_loaded
    if _profiles_loaded and not force:
        return
    _profiles_loaded = True
    try:
        raw = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for item in raw if isinstance(raw, list) else raw.values():
        try:
            profile = Profile.from_dict(item)
            PROFILES[profile.user_id] = profile
        except Exception as exc:  # noqa: BLE001
            profile_log.warning("Nie wczytano profilu: %s", exc)
    profile_log.info("Profile: wczytano %s graczy (poziom max: %s)",
                     len(PROFILES), max((p.level for p in PROFILES.values()), default=0))


def profiles_save() -> None:
    """Zapisuje profile atomowo (plik tymczasowy + podmiana)."""
    try:
        PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = PROFILES_FILE.with_suffix(".json.tmp")
        temp.write_text(json.dumps([p.to_dict() for p in PROFILES.values()],
                                   ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temp, PROFILES_FILE)
    except OSError as exc:
        profile_log.error("Nie zapisano profili: %s", exc)


def profile_get(user: Optional[discord.abc.User], create: bool = True) -> Optional[Profile]:
    """Profil gracza (tworzy nowy, jeśli nie istnieje)."""
    profiles_load()
    if user is None:
        return None
    profile = PROFILES.get(int(user.id))
    if profile is None and create:
        profile = Profile(int(user.id), str(getattr(user, "name", "") or user))
        PROFILES[profile.user_id] = profile
    if profile is not None:
        profile.username = str(getattr(user, "name", "") or profile.username)
    return profile


def profile_by_id(user_id: int) -> Optional[Profile]:
    """Profil po ID gracza (bez tworzenia nowego) — np. dla kroków kreatora."""
    profiles_load()
    return PROFILES.get(int(user_id))


async def award_xp(profile: Optional[Profile], event: str,
                   channel: Optional[discord.abc.Messageable] = None,
                   amount: Optional[int] = None, reason: str = "") -> Optional[str]:
    """Nadaje XP, zapisuje profil i ogłasza awans na kanale sesji."""
    if profile is None:
        return None
    message = profile.add_xp(event, amount)
    profiles_save()
    if message:
        if channel is not None:
            try:
                await channel.send(message)
            except discord.HTTPException:
                pass
        # Most do FiveM: awans gracza prosto na czat w grze
        await bridge_notify("🏅 Awans twórcy",
                            f"{profile.username or profile.user_id} osiągnął rangę "
                            f"{profile.rank['name']} (poziom {profile.level}, {profile.xp} XP)",
                            kind="level", meta={"user_id": profile.user_id,
                                                "level": profile.level})
    profile_log.info("XP %s (+%s) dla %s %s", event,
                     XP_EVENTS.get(event, amount), profile.user_id, reason)
    return message


def min_level_of(item: Dict[str, Any]) -> int:
    """Wymagany poziom twórcy dla preseta/skina."""
    try:
        return int(item.get("min_level", 0) or 0)
    except (TypeError, ValueError):
        return 0


def is_locked(profile: Optional[Profile], item: Dict[str, Any]) -> bool:
    """Czy preset jest zablokowany dla tego gracza?"""
    return (profile.level if profile else 0) < min_level_of(item)


def lock_text(item: Dict[str, Any]) -> str:
    """Opis blokady pokazywany graczowi."""
    level = min_level_of(item)
    return (f"🔒 **Preset dla rangi {rank_for_level(level)['name']}** (poziom {level})\n"
            "Buduj paczki i oceniaj mody, żeby zdobyć XP i go odblokować.")


# --- podpis paczek i tokeny personalizacji ---

PACK_TOKENS: Dict[str, Dict[str, Any]] = {}


def pack_secret() -> bytes:
    """Trwały sekret do podpisu paczek (nie zmienia się między restartami)."""
    try:
        secret = SECRET_FILE.read_bytes()
        if len(secret) >= 16:
            return secret
    except OSError:
        pass
    secret = os.urandom(32)
    try:
        SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        SECRET_FILE.write_bytes(secret)
    except OSError as exc:
        profile_log.warning("Nie zapisano sekretu paczek: %s", exc)
    return secret


def pack_sign(payload: Dict[str, Any]) -> str:
    """HMAC-SHA256 paczki — pozwala serwerowi FiveM sprawdzić, kto ją wygenerował."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(pack_secret(), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def packs_load() -> None:
    """Wczytuje wydane tokeny paczek (żeby /api działało po restarcie)."""
    try:
        raw = json.loads(PACKS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for token, record in raw.items() if isinstance(raw, dict) else []:
        try:
            PACK_TOKENS[str(token)] = dict(record)
        except (TypeError, ValueError):
            continue
    profile_log.info("Tokeny paczek: %s aktywnych", len(PACK_TOKENS))


def packs_save() -> None:
    """Zapisuje tokeny paczek (ostatnie 500, żeby plik nie puchł)."""
    try:
        PACKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        newest = dict(sorted(PACK_TOKENS.items(), key=lambda kv: kv[1].get("created_at", 0),
                             reverse=True)[:500])
        PACK_TOKENS.clear()
        PACK_TOKENS.update(newest)
        temp = PACKS_FILE.with_suffix(".json.tmp")
        temp.write_text(json.dumps(PACK_TOKENS, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temp, PACKS_FILE)
    except OSError as exc:
        profile_log.error("Nie zapisano tokenów paczek: %s", exc)


def pack_token_create(profile: Profile, session: Session, kind: str,
                      items: Sequence[Dict[str, Any]], build: Dict[str, str]) -> Dict[str, Any]:
    """Tworzy unikalny, podpisany token paczki (personalizacja + weryfikacja)."""
    token = f"FM-{os.urandom(4).hex().upper()}"
    payload = {
        "token": token,
        "kind": kind,
        "user_id": profile.user_id,
        "username": profile.username,
        "level": profile.level,
        "rank": profile.rank["name"],
        "build": build["id"],
        "build_name": build["name"],
        "items": [{"id": i.get("id"), "name": i.get("name")} for i in items],
        "created_at": int(time.time()),
    }
    record = {**payload, "signature": pack_sign(payload), "downloads": 0}
    PACK_TOKENS[token] = record
    packs_save()
    return record


def pack_token_get(token: str) -> Optional[Dict[str, Any]]:
    """Token paczki + weryfikacja podpisu."""
    record = PACK_TOKENS.get(token)
    if not record:
        return None
    payload = {k: v for k, v in record.items() if k not in ("signature", "downloads")}
    record = dict(record)
    record["valid"] = pack_sign(payload) == record.get("signature")
    return record


def write_personalization(workspace: Path, profile: Profile, kind: str,
                          items: Sequence[Dict[str, Any]], build: Dict[str, str],
                          token_record: Dict[str, Any]) -> List[Path]:
    """
    Wrzuca do paczki unikalne metadane twórcy (FOUNDRY-PROFILE.json + PROFILE.txt).

    Dzięki temu każda paczka jest inna i możliwe jest sprawdzenie jej
    pochodzenia (podpis HMAC) — a serwer FiveM może po tokenie rozpoznać autora.
    """
    if not PERSONALIZE_PACKS:
        return []
    payload = dict(token_record)
    payload["generated_by"] = "FiveM Mod Foundry"
    payload["user"] = {"id": profile.user_id, "name": profile.username,
                       "xp": profile.xp, "builds": profile.builds,
                       "preferences": profile.top_tags(6)}
    payload["pack"] = {"kind": kind, "build": build["id"],
                       "item_count": len(items)}

    json_path = workspace / "FOUNDRY-PROFILE.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "=" * 62,
        "  PACZKA PERSONALIZOWANA — FIVEM MOD FOUNDRY",
        "=" * 62,
        f"  Twórca  : {profile.username or profile.user_id} (ID {profile.user_id})",
        f"  Ranga   : {profile.rank['name']} (poziom {profile.level}, {profile.xp} XP)",
        f"  Token   : {token_record['token']}",
        f"  Podpis  : {token_record['signature'][:32]}…",
        f"  Build   : {build['name']}",
        f"  Typ     : {'citizen' if kind == 'citizen' else 'skiny broni'}",
        f"  Pozycji : {len(items)}",
        "",
        "  Paczka jest unikalna — metadane i podpis znajdują się też w pliku",
        "  FOUNDRY-PROFILE.json. Token możesz podać administracji serwera, żeby",
        "  potwierdzić pochodzenie paczki.",
        "=" * 62,
    ]
    text_path = workspace / "PROFILE.txt"
    text_path.write_text("\n".join(lines), encoding="utf-8")
    return [json_path, text_path]


# --- inteligentne rekomendacje (dopasowanie modów do preferencji) ---

TAG_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    ("sky", ("niebo", "grafika")),
    ("clouds", ("grafika", "optymalizacja")),
    ("sun", ("grafika", "niebo")),
    ("water", ("woda", "grafika")),
    ("colors", ("grafika",)),
    ("shadows", ("optymalizacja", "cienie")),
    ("postfx", ("optymalizacja", "grafika")),
    ("props", ("optymalizacja", "mapy")),
    ("windows", ("optymalizacja", "pojazdy")),
    ("tire", ("pojazdy", "optymalizacja")),
    ("fire", ("pojazdy", "optymalizacja")),
    ("potato", ("potato", "optymalizacja")),
    ("grass", ("potato", "mapy")),
    ("sound", ("dźwięk",)),
    ("blood", ("krew",)),
    ("hitmarker", ("hud",)),
    ("crosshair", ("hud",)),
]

CATEGORY_TAGS: Dict[str, Tuple[str, ...]] = {
    "OPTI": ("optymalizacja", "fps"),
    "OPTI KOMPA": ("optymalizacja", "fps"),
    "POTATO": ("potato", "optymalizacja"),
    "FIRST PERSON": ("first person", "hud"),
    "SKINY BRONI": ("skiny-broni",),
    "MAPY": ("mapy", "pvp"),
    "GRAFIKA": ("grafika", "niebo"),
    "AUTA": ("pojazdy",),
    "INNE": (),
}

VIDEO_KEYWORDS: Tuple[str, ...] = ("potato", "first person", "fps", "krew", "hud", "crosshair",
                                  "mapy", "skiny-broni", "niebo", "optymalizacja", "woda",
                                  "pojazdy", "grafika")


def tags_for_step(step_id: str) -> List[str]:
    """Tagi preferencji dla wybranej opcji kreatora (podstawa rekomendacji)."""
    for prefix, tags in TAG_RULES:
        if step_id.startswith(prefix):
            return list(tags)
    return ["citizen"]


def video_tags(video: Dict[str, Any]) -> List[str]:
    """Tagi moda z YouTube (kategoria + słowa z tytułu)."""
    tags = list(CATEGORY_TAGS.get(str(video.get("category", "INNE")), ()))
    title = str(video.get("title") or "").lower()
    tags += [keyword for keyword in VIDEO_KEYWORDS if keyword in title]
    return list(dict.fromkeys(tags))


def recommend_score(profile: Profile, tags: Sequence[str]) -> int:
    """Trafność moda dla gracza = suma jego preferencji dla tagów moda."""
    return sum(profile.preferences.get(tag, 0) for tag in tags)


def recommend_profiles(tags: Sequence[str], min_score: Optional[int] = None,
                       limit: int = 3) -> List[Tuple[int, Profile]]:
    """Zwraca najlepiej dopasowanych graczy (score, profil), którzy chcą powiadomień."""
    threshold = SMART_PING_MIN_SCORE if min_score is None else min_score
    scored: List[Tuple[int, Profile]] = []
    for profile in PROFILES.values():
        if not profile.dm_opt_in:
            continue
        score = recommend_score(profile, tags)
        if score >= threshold:
            scored.append((score, profile))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[:limit]


async def send_smart_pings(bot_instance: "FoundryBot",
                           videos: Sequence[Dict[str, Any]]) -> int:
    """
    Inteligentne powiadomienia: nowy mod trafia na priv tylko do graczy, których
    zapamiętane wybory (np. POTATO + optymalizacja) pasują do jego tagów.
    Zabezpieczenia: zgoda gracza (/ustawienia), limit na skan i cooldown.
    """
    if not SMART_PINGS or not videos:
        return 0
    now = time.time()
    sent = 0
    for video in videos:
        tags = video_tags(video)
        if not tags:
            continue
        for score, profile in recommend_profiles(tags, limit=3):
            if sent >= 10:  # nigdy więcej niż 10 DM-ów na jeden skan
                return sent
            if now - profile.last_dm_at < SMART_PING_COOLDOWN_MINUTES * 60:
                continue
            user = bot_instance.get_user(profile.user_id)
            if user is None:
                try:
                    user = await bot_instance.fetch_user(profile.user_id)
                except discord.HTTPException:
                    continue
            embed = discord.Embed(
                title=f"🎯 Nowy mod dla Ciebie: {video['title'][:180]}",
                url=f"https://www.youtube.com/watch?v={video['id']}",
                description=(f"Kategoria: **{video.get('category', 'MOD')}** • dopasowanie: **{score} pkt**\n"
                             f"Twoje preferencje: {', '.join(profile.top_tags(4)) or 'brak'}\n\n"
                             f"Kanał: {video.get('channel', '?')}"),
                color=C_PURPLE, timestamp=datetime.now(timezone.utc))
            if video.get("thumbnail"):
                embed.set_thumbnail(url=video["thumbnail"])
            embed.set_footer(text="Rekomendacja na podstawie Twoich wyborów w kreatorze • /ustawienia")
            try:
                await user.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                profile.dm_opt_in = False  # zamknięte DM-y — nie próbuj ponownie
                continue
            profile.last_dm_at = now
            sent += 1
    if sent:
        profiles_save()
        profile_log.info("Smart pingi: wyslano %s rekomendacji", sent)
    return sent

# ============================================================================
# 14. KOLEJKA ZADAŃ (chroni serwer przy pakowaniu ZIP-ów)
# ============================================================================


queue_log = log("Queue")


class TaskQueue:
    """
    Kolejka FIFO z ograniczoną równoległością (asyncio.Semaphore).

    Chroni serwer przed przeciążeniem: pakowanie ZIP-ów zajmuje CPU i dysk,
    więc przy ZIP_QUEUE_CONCURRENCY=2 maksymalnie 2 paczki liczą się naraz,
    a reszta czeka w kolejce. Gracz dostaje informację o swojej pozycji
    („Twoja paczka jest w kolejce (pozycja 2)...”) i wie, że bot go nie pominął.
    """

    def __init__(self, concurrency: int = 2, name: str = "ZIP") -> None:
        self.name = name
        self.concurrency_limit = max(1, concurrency)
        self._sem = asyncio.Semaphore(self.concurrency_limit)
        # Priority lane: gracze od rangi PRIORITY_LEVEL dostają jedno dodatkowe
        # miejsce, więc nie czekają w ogonku za tłumem.
        self._priority_sem = asyncio.Semaphore(1) if PRIORITY_LANE else None
        self.waiting = 0
        self.running = 0
        self.completed = 0
        self.failed = 0
        self.priority_jobs = 0
        self.total_wait_seconds = 0.0

    @property
    def busy(self) -> int:
        """Ile zadań jest aktualnie przetwarzanych."""
        return self.running

    async def add(self, coro_func, *args,
                  on_queued=None, on_start=None, priority: bool = False, **kwargs):
        """
        Wykonuje zadanie w kolejce i zwraca jego wynik.

        on_queued(position) — wywoływane od razu, gdy zadanie trafi do kolejki
                              (position > 1 oznacza, że trzeba poczekać),
        on_start(wait_seconds) — wywoływane w momencie rozpoczęcia pracy,
        priority — zadanie z priority lane (wyższe rangi twórców) startuje
                   nawet wtedy, gdy zwykła kolejka jest zajęta.
        """
        self.waiting += 1
        # Pozycja = zadania już pakowane + te zakolejkowane przede mną.
        # (liczenie samego `waiting` myliłoby, gdy pierwsze zadanie zdąży już
        # wejść do semafora — drugi gracz widziałby pozycję 1 zamiast 2)
        position = self.waiting + self.running
        enqueued_at = time.time()

        if on_queued is not None:
            try:
                await on_queued(position)
            except Exception as exc:  # noqa: BLE001
                queue_log.warning("on_queued zawiodlo: %s", exc)

        try:
            if priority and self._priority_sem is not None:
                self.priority_jobs += 1
                queue_log.info("Zadanie PRIORYTETOWE (%s) — startuje poza zwykla kolejka", self.name)
                async with self._priority_sem:
                    return await self._run(coro_func, position, enqueued_at, on_start,
                                           args, kwargs, lane=True)
            return await self._run(coro_func, position, enqueued_at, on_start, args, kwargs)
        except Exception:
            self.failed += 1
            raise
        finally:
            self.running -= 1
            if self.waiting < 0:  # zabezpieczenie przed rozjazdem licznika
                self.waiting = 0

    async def _run(self, coro_func, position: int, enqueued_at: float, on_start,
                   args: tuple, kwargs: dict, lane: bool = False):
        """
        Wykonanie zadania.

        lane=True to priority lane (wyższe rangi twórców) — omija zwykły semafor,
        więc nie stoi w kolejce za zadaniami, które dopiero czekają.
        """
        if lane:
            return await self._execute(coro_func, position, enqueued_at, on_start, args, kwargs)
        async with self._sem:
            return await self._execute(coro_func, position, enqueued_at, on_start, args, kwargs)

    async def _execute(self, coro_func, position: int, enqueued_at: float, on_start,
                       args: tuple, kwargs: dict):
        """Właściwa praca zadania (pomiar czasu oczekiwania + statystyki)."""
        self.waiting -= 1
        self.running += 1
        wait_seconds = time.time() - enqueued_at
        self.total_wait_seconds += wait_seconds
        if position > 1:
            queue_log.info("Zadanie z kolejki startuje po %.1f s (bylo %s przed nim)",
                           wait_seconds, position - 1)
        if on_start is not None:
            try:
                await on_start(wait_seconds)
            except Exception as exc:  # noqa: BLE001
                queue_log.warning("on_start zawiodlo: %s", exc)
        result = await coro_func(*args, **kwargs)
        self.completed += 1
        return result

    async def run_all(self, jobs: Sequence[Any], concurrency: Optional[int] = None) -> List[Any]:
        """Uruchamia wiele zadań (np. pre-cache) z ograniczoną równoległością."""
        limit = concurrency or self.concurrency_limit
        semaphore = asyncio.Semaphore(max(1, limit))
        results: List[Any] = []

        async def worker(index: int, job) -> None:
            async with semaphore:
                try:
                    results.append(await job())
                except Exception as exc:  # noqa: BLE001
                    self.failed += 1
                    queue_log.warning("Zadanie %s w kolejce %s nieudane: %s", index, self.name, exc)

        await asyncio.gather(*[worker(i, job) for i, job in enumerate(jobs)])
        return results

    def info(self) -> Dict[str, Any]:
        """Statystyki kolejki (do /status)."""
        average = self.total_wait_seconds / self.completed if self.completed else 0.0
        return {
            "name": self.name,
            "waiting": self.waiting,
            "running": self.running,
            "completed": self.completed,
            "failed": self.failed,
            "concurrency": self.concurrency_limit,
            "average_wait": average,
            "priority_jobs": self.priority_jobs,
        }


ZIP_QUEUE = TaskQueue(ZIP_QUEUE_CONCURRENCY, "ZIP")

# ============================================================================
# 15. PROCESOR PLIKÓW — pobieranie, struktura citizen/mods, manifest, ZIP
# ============================================================================

fp_log = log("FileProcessor")


class ApprovalRequired(Exception):
    """Plik wymaga zgody administratora (poziom 'review')."""

    def __init__(self, scan: Dict[str, str], file_url: str) -> None:
        super().__init__(f"Plik {scan.get('file_name', '?')} wymaga zgody administratora ({scan.get('reason')})")
        self.scan = scan
        self.file_url = file_url


async def download_file(http: aiohttp.ClientSession, url: str, dest: Path,
                        redirects_left: int = 5) -> Path:
    """Pobiera plik strumieniowo (limit rozmiaru, przekierowania, skan bezpieczeństwa)."""
    scan = scan_url(url)
    if scan["level"] == "block":
        raise ValueError(f"⛔ Zablokowany plik: {scan['reason']}")
    if scan["level"] == "review" and not approval_is_approved(url):
        raise ApprovalRequired(scan, url)

    dest.parent.mkdir(parents=True, exist_ok=True)
    async with http.get(url, allow_redirects=False) as response:
        if response.status in (301, 302, 303, 307, 308) and response.headers.get("Location"):
            if redirects_left <= 0:
                raise ValueError("Za dużo przekierowań")
            new_url = str(response.url.join(response.headers["Location"]))
            return await download_file(http, new_url, dest, redirects_left - 1)
        if response.status != 200:
            raise ValueError(f"HTTP {response.status} przy {url}")

        expected = 0
        try:
            expected = int(response.headers.get("Content-Length") or 0)
        except ValueError:
            expected = 0

        received = 0
        with open(dest, "wb") as fh:
            async for chunk in response.content.iter_chunked(64 * 1024):
                received += len(chunk)
                if received > MAX_DOWNLOAD_BYTES:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    raise ValueError(f"Plik przekracza limit {MAX_DOWNLOAD_MB} MB")
                fh.write(chunk)

    # ANTY-CRASH: urwane pobranie to najczęstsza przyczyna crashu GTA V
    if expected and received != expected:
        dest.unlink(missing_ok=True)
        raise ValueError(f"Niekompletne pobranie ({received} z {expected} bajtów) — spróbuj ponownie")
    if received == 0:
        dest.unlink(missing_ok=True)
        raise ValueError("Pusty plik (0 bajtów) — odrzucono")
    return dest


def resolve_file_name(item: Dict[str, str]) -> str:
    """Ustala bezpieczną nazwę pliku docelowego."""
    configured = item.get("file_name")
    if configured and scan_filename(configured)["level"] != "block":
        return configured
    from_url = file_name_from_url(item.get("file_url", ""))
    if from_url and scan_filename(from_url)["level"] != "block":
        return from_url
    return from_url or "plik.bin"


async def fetch_to_cache(http: aiohttp.ClientSession, url: str) -> Path:
    """
    Zwraca ścieżkę pliku w lokalnym cache, pobierając go TYLKO raz.

    Kolejny gracz, który wybierze ten sam mod, dostaje go z dysku — dlatego
    budowanie paczki spada z kilkudziesięciu sekund do ułamka sekundy.
    """
    cached = FILE_CACHE.lookup(url)
    if cached is not None:
        return cached

    target = FILE_CACHE.path_for(url)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + ".part")
    try:
        await download_file(http, url, staging)          # skan bezpieczeństwa w środku
        await asyncio.to_thread(os.replace, staging, target)
    except Exception:
        await asyncio.to_thread(lambda: staging.unlink(missing_ok=True))
        raise
    cache_log.info("Cache: pobrano i zapisano %s (%.1f KB)", target.name,
                   target.stat().st_size / 1024)
    return target


# ============================================================================
# 15.5. WALIDATOR PLIKÓW GRY (anti-crash) + AUTO-PATCHER
#    Sprawdza strukturę .rpf/.ytd/.ydr/.dds/.xml i naprawia to, co da się
#    bezpiecznie naprawić (BOM, końce linii, deklaracja XML, mipmapy w DDS
#    przez Pillow — jeśli jest zainstalowany).
# ============================================================================

validator_log = log("Validator")

MAX_TEXTURE_DIMENSION = int(os.getenv("MAX_TEXTURE_DIMENSION", "4096") or 4096)
MAX_TEXTURE_VRAM_MB = int(os.getenv("MAX_TEXTURE_VRAM_MB", "64") or 64)
AUTO_PATCH_FILES = os.getenv("AUTO_PATCH_FILES", "1").strip().lower() not in ("0", "false", "no")

RSC7_MAGIC = b"RSC7"
RPF7_MAGIC = b"RPF7"
DDS_MAGIC = b"DDS "
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
TGA_FOOTER = b"TRUEVISION-XFILE"

# Formaty, które trzeba przepuścić przez walidację (reszta: tylko rozmiar)
BINARY_TEXTURE_EXT = {".ytd", ".ydr", ".yft", ".ymt", ".rpf", ".dds"}
TEXT_CONFIG_EXT = {".xml", ".meta", ".dat", ".ini", ".cfg", ".txt", ".json"}


def _dds_info(data: bytes) -> Dict[str, Any]:
    """Czyta nagłówek DDS: wymiary, mipmapy, format i szacowany VRAM."""
    info: Dict[str, Any] = {"dds": True}
    if len(data) < 128:
        return {"dds": True, "broken": True}
    flags = int.from_bytes(data[8:12], "little")
    height = int.from_bytes(data[12:16], "little")
    width = int.from_bytes(data[16:20], "little")
    mipmaps = int.from_bytes(data[28:32], "little") or 1
    fourcc = data[84:88]
    info.update({"width": width, "height": height, "mipmaps": mipmaps,
                 "format": fourcc.decode("ascii", "replace").strip() or "RAW",
                 "header_flags": flags})
    # VRAM: DXT/BC = 1 bajt na piksel, RAW = 4 bajty na piksel (szacunek)
    per_pixel = 1.0 if fourcc[:1] in (b"D", b"A", b"B") else 4.0
    base = width * height * per_pixel
    info["vram_mb"] = round(base * (4 / 3 if mipmaps > 1 else 1) / 1024 / 1024, 2)
    if width <= 0 or height <= 0 or width > 32768 or height > 32768:
        info["broken"] = True
    return info


def _rpf_info(data: bytes) -> Dict[str, Any]:
    """
    Sprawdza nagłówek archiwum RPF7.

    GTA V nie czyta zaszyfrowanych archiwów bez klucza, więc dla nich
    ograniczamy się do walidacji nagłówka i spójności tabeli (najczęstszy
    problem to urwany plik — i to wyłapujemy).
    """
    info: Dict[str, Any] = {"rpf": True}
    if len(data) < 16:
        return {"rpf": True, "broken": True, "reason": "nagłówek RPF7 ucięty"}
    entry_count = int.from_bytes(data[4:8], "little")
    names_length = int.from_bytes(data[8:12], "little")
    encryption = int.from_bytes(data[12:16], "little")
    info.update({"entries": entry_count, "names_length": names_length,
                 "encryption": encryption})
    toc_end = 16 + entry_count * 16
    names_end = toc_end + names_length
    if entry_count > 5_000_000 or names_length > 200_000_000:
        return {**info, "broken": True, "reason": "nagłówek RPF7 wygląda na uszkodzony"}
    if toc_end > len(data):
        return {**info, "broken": True,
                "reason": f"tabela plików (TOC) wychodzi poza archiwum — plik urwany?",
                "toc_end": toc_end, "size": len(data)}
    if names_end > len(data):
        return {**info, "broken": True,
                "reason": "tabela nazw wychodzi poza archiwum — plik urwany?",
                "names_end": names_end, "size": len(data)}
    if encryption:
        info["encrypted"] = True
        info["reason"] = ("archiwum zaszyfrowane (AES) — struktura nagłówka poprawna, "
                          "pełna weryfikacja zawartości niemożliwa")
    return info


def _rsc7_info(data: bytes) -> Dict[str, Any]:
    """Sprawdza nagłówek zasobu RSC7 (.ytd/.ydr/.yft/.ymt)."""
    info: Dict[str, Any] = {"rsc7": True, "size": len(data)}
    if len(data) < 16:
        return {**info, "broken": True, "reason": "nagłówek RSC7 ucięty"}
    version = int.from_bytes(data[4:8], "little")
    system_flags = int.from_bytes(data[8:12], "little")
    graphics_flags = int.from_bytes(data[12:16], "little")
    info.update({"version": version, "system_flags": system_flags,
                 "graphics_flags": graphics_flags})
    if version not in (2, 3, 4, 5):
        info["warning"] = f"nietypowa wersja zasobu RSC7 (v{version})"
    if system_flags == 0 and graphics_flags == 0:
        info["broken"] = True
        info["reason"] = "nagłówek RSC7 bez flag zasobu (uszkodzony plik)"
    return info


def analyze_binary(path: Path) -> Dict[str, Any]:
    """
    Analizuje plik gry i zwraca raport pod kątem ryzyka crashu.

    Zwraca dict: {severity: 'ok'|'warn'|'crash', reason, details, fixes}
    severity 'crash' oznacza, że plik NIE może trafić do paczki (bot go pominie).
    """
    report: Dict[str, Any] = {"file": path.name, "severity": "ok", "reason": "",
                              "details": {}, "fixes": [], "bytes": 0}
    try:
        size = path.stat().st_size
    except OSError as exc:
        return {**report, "severity": "crash", "reason": f"nie mogę odczytać pliku ({exc})"}
    report["bytes"] = size
    if size == 0:
        return {**report, "severity": "crash", "reason": "plik ma 0 bajtów"}

    try:
        with open(path, "rb") as handle:
            head = handle.read(128)
    except OSError as exc:
        return {**report, "severity": "crash", "reason": f"błąd odczytu ({exc})"}

    suffix = path.suffix.lower()

    is_png = head.startswith(PNG_MAGIC)
    is_jpeg = head.startswith(JPEG_MAGIC)
    is_zip = head[:2] == b"PK"

    # 1. Treść nie pasuje do rozszerzenia (częsta przyczyna crashu)
    image_ext = {".png", ".jpg", ".jpeg"}
    archive_ext = {".zip", ".rar", ".7z", ".oiv", ".cab"}
    if (is_png or is_jpeg) and suffix not in image_ext:
        kind = "obraz PNG" if is_png else "obraz JPEG"
        return {**report, "severity": "crash",
                "reason": f"zawartość to {kind}, a plik nazywa się `{path.name}` — "
                          "gra nie odczyta takiego pliku (crash przy starcie).",
                "details": {"detected": kind}}
    if is_zip and suffix not in archive_ext:
        return {**report, "severity": "crash",
                "reason": f"zawartość to archiwum ZIP, a plik nazywa się `{path.name}` — "
                          "gra nie odczyta takiego pliku (crash przy starcie).",
                "details": {"detected": "archiwum ZIP"}}

    # 1b. Prawdziwy obraz (np. surowa tekstura .png/.jpg) — sprawdź wymiary
    if is_png:
        with open(path, "rb") as handle:
            header = handle.read(24)
        width = int.from_bytes(header[16:20], "big") if len(header) >= 24 else 0
        height = int.from_bytes(header[20:24], "big") if len(header) >= 24 else 0
        report["details"].update({"image": "png", "width": width, "height": height})
        if width <= 0 or height <= 0:
            return {**report, "severity": "crash", "reason": "uszkodzony nagłówek PNG"}
        if max(width, height) > MAX_TEXTURE_DIMENSION:
            report["severity"] = ("crash" if max(width, height) > MAX_TEXTURE_DIMENSION * 2
                                  else "warn")
            report["reason"] = (f"obraz {width}x{height} przekracza zalecane "
                                f"{MAX_TEXTURE_DIMENSION}px — ryzyko out-of-memory")
        return report
    if is_jpeg:
        report["details"].update({"image": "jpeg", "bytes_mb": round(size / 1024 / 1024, 2)})
        if size > 12 * 1024 * 1024:
            report["severity"] = "warn"
            report["reason"] = (f"obraz JPEG ma {size / 1024 / 1024:.1f} MB — "
                                "duże tekstury podnoszą zużycie VRAM")
        return report

    # 2. Surowa tekstura DDS (np. wgrana zamiast .ytd)
    if head.startswith(DDS_MAGIC):
        with open(path, "rb") as handle:
            data = handle.read(160)
        info = _dds_info(data)
        report["details"].update(info)
        if info.get("broken"):
            return {**report, "severity": "crash", "reason": "uszkodzony nagłówek DDS"}
        if info["width"] > MAX_TEXTURE_DIMENSION or info["height"] > MAX_TEXTURE_DIMENSION:
            severity = "crash" if max(info["width"], info["height"]) > MAX_TEXTURE_DIMENSION * 2 else "warn"
            report["severity"] = severity
            report["reason"] = (f"tekstura {info['width']}x{info['height']} — powyżej zalecanych "
                                f"{MAX_TEXTURE_DIMENSION}px (ryzyko out-of-memory / crashu)")
        if info.get("vram_mb", 0) > MAX_TEXTURE_VRAM_MB:
            if report["severity"] != "crash":
                report["severity"] = "warn"
            report["reason"] = (report["reason"] or "") + \
                f" VRAM ~{info['vram_mb']} MB (budżet {MAX_TEXTURE_VRAM_MB} MB)."
        if info.get("mipmaps", 1) <= 1:
            report["details"]["no_mipmaps"] = True
            if report["severity"] == "ok":
                report["severity"] = "warn"
                report["reason"] = "brak mipmap — większe zużycie VRAM i migotanie tekstur"
        return report

    # 3. Zasób RSC7 (standardowy format .ytd/.ydr/.yft)
    if head.startswith(RSC7_MAGIC):
        info = _rsc7_info(head)
        report["details"].update(info)
        if info.get("broken"):
            return {**report, "severity": "crash", "reason": info.get("reason", "uszkodzony RSC7")}
        if info.get("warning"):
            report["severity"] = "warn"
            report["reason"] = info["warning"]
        return report

    # 4. Archiwum RPF7
    if head.startswith(RPF7_MAGIC):
        with open(path, "rb") as handle:
            data = handle.read(64 * 1024)
        info = _rpf_info(data)
        report["details"].update(info)
        if info.get("broken"):
            return {**report, "severity": "crash", "reason": info.get("reason", "uszkodzony RPF7")}
        if info.get("encrypted"):
            report["severity"] = "warn"
            report["reason"] = info["reason"]
        return report

    # 5. Rozszerzenia z rozszerzeniem .rpf/.ytd/.ydr, ale bez znanego nagłówka
    if suffix in BINARY_TEXTURE_EXT:
        if size < 1024:
            return {**report, "severity": "crash",
                    "reason": (f"plik ma tylko {size} B — to nie może być pełny zasób gry "
                               "(prawdopodobnie urwane pobranie lub strona HTML zamiast pliku)")}
        return {**report, "severity": "warn",
                "reason": "nieznany nagłówek zasobu — zaimportowany przez inne narzędzie, "
                          "zweryfikuj go w OpenIV/CodeWalkerze"}

    # 6. Pliki konfiguracyjne (XML/DAT/INI) — tu naprawy są naprawdę bezpieczne
    if suffix in TEXT_CONFIG_EXT:
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError:
            return {**report, "severity": "ok", "details": {"binary_config": True},
                    "reason": "plik binarny — pomijam analizę tekstową"}
        except OSError as exc:
            return {**report, "severity": "crash", "reason": f"błąd odczytu ({exc})"}
        if suffix in (".xml", ".meta"):
            try:
                import xml.etree.ElementTree as element_tree
                element_tree.fromstring(text.strip().encode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                report["severity"] = "warn"
                report["reason"] = f"XML nie jest poprawny ({type(exc).__name__}: {str(exc)[:80]})"
        return report

    return report


def autopatch_file(path: Path, report: Dict[str, Any]) -> List[str]:
    """
    Bezpieczne, automatyczne naprawy (na miejscu):
      • usunięcie BOM i normalizacja końców linii w XML/META/INI/CFG,
      • dodanie deklaracji XML, jeśli jej brakuje,
      • dociągnięcie mipmap / zmniejszenie zbyt dużej tekstury DDS lub obrazu
        (tylko jeśli Pillow jest zainstalowany).
    Zwraca listę wykonanych napraw.
    """
    fixes: List[str] = []
    if not AUTO_PATCH_FILES:
        return fixes
    suffix = path.suffix.lower()
    try:
        if suffix in {".xml", ".meta", ".ini", ".cfg"}:
            raw = path.read_bytes()
            # utf-8-sig zdejmuje BOM z treści (sama flaga „changed" to za mało!)
            text = raw.decode("utf-8-sig", errors="ignore")
            changed = False
            if raw.startswith(b"\xef\xbb\xbf"):
                changed = True
                fixes.append("usunięto BOM (GTA V potrafi się na nim wyłożyć)")
            if "\r\n" in text:
                text = text.replace("\r\n", "\n")
                changed = True
                fixes.append("zamieniono końce linii CRLF -> LF")
            if suffix in {".xml", ".meta"} and not text.lstrip().startswith("<?xml"):
                text = '<?xml version="1.0" encoding="UTF-8"?>\n' + text
                changed = True
                fixes.append("dodano deklarację XML")
            if changed:
                # Zapis przez bajty — Windows nie zamieni nam LF z powrotem na CRLF
                path.write_bytes(text.encode("utf-8"))
        elif suffix in {".dds", ".png", ".jpg", ".jpeg"}:
            dimensions = report.get("details") or {}
            too_big = (suffix == ".dds" and max(dimensions.get("width", 0), dimensions.get("height", 0)) > MAX_TEXTURE_DIMENSION) \
                or (suffix in {".png", ".jpg", ".jpeg"} and dimensions.get("broken"))
            if too_big:
                try:
                    from PIL import Image  # type: ignore
                except Exception:
                    return fixes
                with Image.open(path) as image:
                    if max(image.size) > MAX_TEXTURE_DIMENSION:
                        ratio = MAX_TEXTURE_DIMENSION / max(image.size)
                        new_size = (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
                        image.resize(new_size).save(path)
                        fixes.append(f"zmniejszono teksturę do {new_size[0]}x{new_size[1]} (Pillow)")
    except Exception as exc:  # noqa: BLE001
        validator_log.warning("Auto-patch %s nieudany: %s", path.name, exc)
    return fixes


async def process_items(workspace: Path, items: Sequence[Dict[str, str]],
                        session: Optional["Session"] = None) -> List[Dict[str, Any]]:
    """
    Buduje pliki we workspace: z lokalnego cache (natychmiast) albo z sieci,
    a następnie przepuszcza każdy plik przez WALIDATOR ANTY-CRASH.

    Pliki klasy 'crash' są pomijane (i raportowane graczowi oraz administracji),
    żeby paczka nie wysypała gry. Liczone są SHA-256 wszystkich plików paczki.
    """
    hashes: List[Dict[str, Any]] = []
    async with aiohttp.ClientSession(headers={"User-Agent": "FiveMModFoundry/3.0"}) as http:
        for item in items:
            file_name = resolve_file_name(item)
            dest = workspace / item["target"] / file_name
            dest.parent.mkdir(parents=True, exist_ok=True)

            # 0) Plik GENEROWANY przez bota (citizen: te same pliki, zmienione wartości).
            #   Ścieżka docelowa to pełna relatywna ścieżka w citizen/ — dlatego tu nadpisujemy dest.
            if item.get("generated"):
                gen_rel = str(item.get("gen_file") or "")
                content = await asyncio.to_thread(generate_citizen_file, gen_rel, item.get("gen_params") or {})
                if content is None:
                    fp_log.error("Brak generatora dla %s (krok %s) — pomijam", gen_rel, item.get("id"))
                    if session is not None:
                        session.fatal_skipped.append(f"{item.get('name') or gen_rel} (brak generatora)")
                    continue
                dest = workspace / "citizen" / "common" / "data" / gen_rel
                # Kroki KOMPOZYCYJNE (kill/head effect + blood) piszą do tego samego
                # pliku — każdy w osobnym przebiegu, więc plik jest nadpisywany.
                # Rozwiązanie: merge parametrów z pliku merge-state w workspace.
                merge_state_path = workspace / ".gen_merge.json"
                merge_state: Dict[str, Any] = {}
                if merge_state_path.exists():
                    try:
                        merge_state = json.loads(merge_state_path.read_text(encoding="utf-8"))
                    except Exception:  # noqa: BLE001
                        merge_state = {}
                key = str(dest.relative_to(workspace / "citizen" / "common" / "data").as_posix())
                merged_params = dict(merge_state.get(key) or {})
                merged_params.update(item.get("gen_params") or {})
                merge_state[key] = merged_params
                merge_state_path.write_text(json.dumps(merge_state), encoding="utf-8")
                # Generuj ponownie z PEŁNYM zestawem parametrów (krew + kill + head razem)
                content = await asyncio.to_thread(generate_citizen_file, gen_rel, merged_params)
                if content is None:
                    fp_log.error("Brak generatora dla %s (krok %s) — pomijam", gen_rel, item.get("id"))
                    if session is not None:
                        session.fatal_skipped.append(f"{item.get('name') or gen_rel} (brak generatora)")
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(dest.write_text, content, encoding="utf-8", newline="\r\n")
                digest, size = sha256_file(dest)
                rel = dest.relative_to(workspace).as_posix()
                # Dodaj hash tylko raz (przy ostatnim kroku danego pliku hash jest finalny)
                hashes = [h for h in hashes if h["path"] != rel]
                hashes.append({"path": rel, "sha256": digest, "size": size})
                fp_log.info("  ✓ [GEN] %s (%.1f KB, params: %s)", rel, size / 1024,
                            ", ".join(f"{k}={v}" for k, v in merged_params.items()))
                item["file_name"] = dest.name
                continue

            # 1) Własny plik gracza (wgrany na kanał sesji) — kopiujemy lokalnie.
            local = str(item.get("local_path") or "")
            own_file = bool(local) and Path(local).is_file()
            if own_file:
                source = Path(local)
                fp_log.info("Własny plik gracza: %s -> %s", source.name, dest.relative_to(workspace))
            else:
                url = str(item.get("file_url") or "")
                if not url:
                    # Presety bez hostingu: nic do pobrania — gracz wgra własny plik.
                    fp_log.warning("  ⚠ %s pominięty — brak pliku źródłowego presetów.", file_name)
                    if session is not None:
                        session.fatal_skipped.append(f"{item.get('name') or file_name} (brak pliku — wgraj własny)")
                    continue
                source = FILE_CACHE.lookup(url)
                if source is not None:
                    fp_log.info("Cache HIT: %s -> %s", url, dest.relative_to(workspace))
                else:
                    fp_log.info("Pobieram (raz, potem z cache): %s", url)
                    try:
                        source = await fetch_to_cache(http, url)
                    except Exception as exc:  # noqa: BLE001
                        fp_log.warning("Nie pobrano %s: %s", url, exc)
                        if session is not None:
                            session.fatal_skipped.append(
                                f"{item.get('name') or file_name} "
                                "(nie pobrano z hostingu — wgraj własny plik przyciskiem 📎)")
                        continue
            await asyncio.to_thread(shutil.copyfile, source, dest)

            # --- ANTY-CRASH: walidacja + auto-patch ---
            report = await asyncio.to_thread(analyze_binary, dest)
            fixes = await asyncio.to_thread(autopatch_file, dest, report)
            if fixes:
                report["fixes"] = fixes
                fp_log.info("  🔧 %s: %s", file_name, "; ".join(fixes))
            if report["severity"] == "crash" and own_file:
                # Własny plik gracza zawsze zostaje w paczce — gracz świadomie go wgrał.
                # Zamiast cichego odrzucenia dostaje ostrzeżenie przy pliku w raporcie.
                fp_log.warning("  ⚠ %s: własny plik gracza z ostrzeżeniem — %s",
                               file_name, report["reason"])
                report["severity"] = "warn"
                report["reason"] = (f"własny plik gracza — zostawiony mimo ostrzeżenia "
                                    f"walidatora: {report['reason']}")
            if report["severity"] == "crash":
                fp_log.error("  ⛔ %s odrzucony: %s", file_name, report["reason"])
                dest.unlink(missing_ok=True)
                if session is not None:
                    session.validation_issues.append(report)
                    session.fatal_skipped.append(item.get("name") or file_name)
                continue
            if session is not None and report["severity"] == "warn":
                session.validation_issues.append(report)

            digest, size = sha256_file(dest)
            rel = dest.relative_to(workspace).as_posix()
            hashes.append({"path": rel, "sha256": digest, "size": size})
            fp_log.info("  ✓ %s (%.1f KB)", file_name, size / 1024)
            item["file_name"] = file_name
    return hashes


def validation_report_text(title: str, issues: Sequence[Dict[str, Any]],
                           skipped: Sequence[str], file_count: int) -> str:
    """Raport walidacji dołączany do paczki (VALIDACJA-PACZKI.txt)."""
    lines = [
        "=" * 62,
        f"  WALIDACJA PACZKI — {title}",
        "=" * 62,
        f"  Sprawdzonych plików: {file_count}",
        f"  Ostrzeżenia: {sum(1 for i in issues if i.get('severity') == 'warn')}",
        f"  Odrzucone (ryzyko crashu): {len(skipped)}",
        "",
    ]
    if skipped:
        lines += ["ODRZUCONE PLIKI (nie weszły do paczki):"]
        lines += [f"  ⛔ {name}" for name in skipped]
        lines += ["", "Dlaczego: bot wykrył w nich struktury, które najczęściej "
                      "wysypują GTA V (urwany zasób, zła nazwa formatu, zbyt duża tekstura)."]
    if issues:
        lines += ["", "OSTRZEŻENIA (plik w paczce, ale warto wiedzieć):"]
        for issue in issues:
            icon = "⛔" if issue.get("severity") == "crash" else "⚠️"
            lines.append(f"  {icon} {issue.get('file')}: {issue.get('reason')}")
            for fix in issue.get("fixes") or []:
                lines.append(f"      🔧 auto-naprawa: {fix}")
    if not issues and not skipped:
        lines.append("  ✅ Wszystkie pliki przeszły walidację bez uwag.")
    lines += ["", "Walidator sprawdza: nagłówki RSC7 (.ytd/.ydr), tabelę archiwum RPF7,",
              "wymiary i VRAM tekstur DDS, poprawność XML/META oraz zgodność treści",
              "z rozszerzeniem pliku. Auto-naprawy są zapisywane powyżej przy pliku."]
    return "\n".join(lines)


def all_configured_items() -> List[Dict[str, str]]:
    """
    Wszystkie pliki, jakich bot może potrzebować: kroki citizena + skiny broni.
    Używane przez pre-cache (żeby pierwsze paczki graczy były natychmiastowe).
    """
    items: List[Dict[str, str]] = [
        {"id": step["id"], "name": step["name"], "file_url": step["file_url"],
         "file_name": step["file_name"], "target": step["target"]}
        for step in CITIZEN_STEPS
    ]
    items += [
        {"id": skin["id"], "name": f"{weapon['name']} — {skin['name']}",
         "file_url": skin["file_url"], "file_name": skin["file_name"], "target": skin["target"]}
        for weapon in all_weapons() for skin in weapon["skins"]
    ]
    return items


async def precache_items(items: Optional[Sequence[Dict[str, str]]] = None) -> Dict[str, int]:
    """
    Wstępne pobranie plików bazowych do cache (uruchamiane przy starcie bota
    i przyciskiem w /cache). Pierwszy gracz po restarcie i tak dostaje paczkę
    szybko, bo pliki leżą już na dysku.
    """
    if not CACHE_ENABLED:
        cache_log.info("Cache wyłączony (CACHE_ENABLED=0) — pomijam pre-cache.")
        return {"ok": 0, "failed": 0, "skipped": 0}

    configured = list(items or all_configured_items())
    placeholders = [item for item in configured
                    if "example.com" in (item.get("file_url") or "")]
    configured = [item for item in configured if item not in placeholders]
    if not configured:
        cache_log.warning(
            "Cache: pre-cache pominięty — %s pozycji nadal ma przykładowe adresy "
            "(PODMIEŃ IMG_BASE/FILE_BASE/SKIN_BASE w bot.py).", len(placeholders))
        return {"ok": 0, "failed": 0, "skipped": len(placeholders)}
    if placeholders:
        cache_log.warning("Cache: pomijam %s pozycji z przykładowymi adresami.", len(placeholders))

    todo = [item for item in configured
            if item.get("file_url") and not FILE_CACHE.lookup(item["file_url"])]
    if not todo:
        cache_log.info("Cache: wszystko już na dysku (%s plików).", len(FILE_CACHE.files()))
        return {"ok": 0, "failed": 0, "skipped": len(configured)}

    cache_log.info("Cache: wstępnie pobieram %s plików (max %s naraz)...",
                   len(todo), min(4, ZIP_QUEUE.concurrency_limit + 2))
    ok = 0
    failed = 0

    async with aiohttp.ClientSession(headers={"User-Agent": "FiveMModFoundry/2.0"}) as http:
        async def one(item: Dict[str, str]) -> None:
            nonlocal ok, failed
            try:
                await fetch_to_cache(http, item["file_url"])
                ok += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                cache_log.warning("Cache: nie pobrano %s (%s)",
                                  item.get("name") or item.get("file_url"), exc)

        await ZIP_QUEUE.run_all(
            [partial(one, item) for item in todo],
            concurrency=min(4, ZIP_QUEUE.concurrency_limit + 2),
        )

    cache_log.info("Cache: gotowe — %s pobranych, %s błędów, %.1f MB na dysku.",
                   ok, failed, FILE_CACHE.size_bytes() / 1024 / 1024)
    return {"ok": ok, "failed": failed, "skipped": 0}


def write_manifests(workspace: Path, hashes: Sequence[Dict[str, Any]], build: Dict[str, str],
                    user_id: int, kind: str, choices: Sequence[Dict[str, Any]],
                    conflicts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Zapisuje manifest.json i HASHES.txt w paczce."""
    manifest = {
        "generator": "FiveM Mod Foundry (Python)",
        "version": "2.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "game_build": build["name"],
        "game_build_id": build["id"],
        "user_id": user_id,
        "files": list(hashes),
        "choices": list(choices),
        "conflicts": [{"file": c["file"], "winner": c["winner"], "dropped": c["dropped"]} for c in conflicts],
    }
    (workspace / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (workspace / "HASHES.txt").write_text(
        hashes_to_text(hashes, build["name"], str(user_id)), encoding="utf-8")
    return manifest


def instruction_text(title: str, choices: Sequence[Dict[str, Any]],
                     conflicts: Sequence[Dict[str, Any]], build: Dict[str, str], kind: str) -> str:
    """Treść pliku INSTRUKCJA.txt w paczce."""
    lines = [
        f"=== {title} (FiveM, client-side) ===",
        f"Wygenerowano: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Docelowy build GTA V: {build['name']}",
        "",
        "Wybrane modyfikacje:",
    ]
    lines += [f" - {c['name']}" + (f": {c['description']}" if c.get("description") else "") for c in choices]
    lines += [
        "",
        "Instalacja:",
        "1. Otwórz folder FiveM:",
        "   Windows: %LOCALAPPDATA%\\FiveM\\FiveM.app",
        "2. Foldery z tej paczki przenieś DO WEWNĄTRZ folderu FiveM.app:",
        "   - citizen/  -> FiveM.app/citizen/   (zachowaj strukturę!)",
        "   - mods/     -> FiveM.app/mods/      (utwórz folder, jeśli nie istnieje)",
        "3. Pliki .rpf/.dat/.xml podmieniają presety wizualne (nie usuwaj update.rpf).",
        "4. Uruchom FiveM i wejdź na serwer.",
        "",
        "Weryfikacja integralności:",
        " - manifest.json  — lista plików, build i konfiguracja paczki",
        " - HASHES.txt     — sumy SHA-256 każdego pliku (sprawdź przed instalacją)",
    ]
    if conflicts:
        lines += [
            "",
            "⚠️ WYKRYTE KONFLIKTY PLIKÓW (auto-rozwiązane):",
            conflicts_to_text(conflicts),
            "",
            "Dlaczego: dwa mody nadpisywałyby ten sam plik — drugi nadpisałby pierwszy,",
            "a przy plikach .xml/.dat mogłoby to uszkodzić grę (crash przy starcie).",
        ]
    lines += [
        "",
        "⚠️ Mody klienckie działają tylko na serwerach, które ich nie blokują.",
        "   Sprawdź regulamin swojego serwera przed instalacją.",
    ]
    return "\n".join(lines)


def zip_directory(source: Path, out_path: Path) -> int:
    """Pakuje katalog do ZIP. Zwraca rozmiar pliku w bajtach."""
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file_path in sorted(source.rglob("*")):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(source).as_posix())
    return out_path.stat().st_size


def count_files(directory: Path) -> int:
    """Liczy pliki w katalogu (rekurencyjnie)."""
    return sum(1 for p in directory.rglob("*") if p.is_file())


def safe_rmtree(directory: Path, allowed_root: Path) -> bool:
    """Usuwa katalog tylko wewnątrz dozwolonego roota."""
    try:
        resolved = directory.resolve()
        root = allowed_root.resolve()
    except OSError:
        return False
    if root != resolved and root not in resolved.parents:
        fp_log.warning("Odmowa usuniecia poza rootem: %s", resolved)
        return False
    shutil.rmtree(resolved, ignore_errors=True)
    return True


async def deliver_package(interaction: discord.Interaction, session: Session,
                          items: Sequence[Dict[str, Any]], kind: str,
                          conflicts: Sequence[Dict[str, Any]]) -> None:
    """
    Buduje paczkę (przez kolejkę ZIP), rejestruje ją w storage i wysyła link.
    kind: 'citizen' | 'weapons'
    """
    if not items:
        await interaction.followup.send("❌ Nie wybrano nic do pakowania.", ephemeral=True)
        return

    build = build_by_id(session.build_id)
    profile = profile_get(getattr(interaction, "user", None))
    fp_log.info("User %s: pakowanie %s pozycji (%s)", session.user_id, len(items), kind)

    async def build_package() -> Dict[str, Any]:
        build_dir = session.workspace / f"build-{kind}-{int(time.time() * 1000)}"
        build_dir.mkdir(parents=True, exist_ok=True)
        try:
            hashes = await process_items(build_dir, items, session)

            # ANTY-CRASH: raport walidacji plików gry trafia do paczki
            validation_path = build_dir / "VALIDACJA-PACZKI.txt"
            validation_path.write_text(
                validation_report_text(
                    "PACZKA CITIZEN" if kind == "citizen" else "PACZKA SKINÓW BRONI",
                    session.validation_issues, session.fatal_skipped, len(hashes)),
                encoding="utf-8")
            validation_digest, validation_size = sha256_file(validation_path)
            hashes.append({"path": "VALIDACJA-PACZKI.txt", "sha256": validation_digest,
                           "size": validation_size})

            # Personalizacja: unikalny token + podpis + metadane twórcy w paczce
            token_record = None
            if profile is not None:
                token_record = await asyncio.to_thread(
                    pack_token_create, profile, session, kind, items, build)
                extra = await asyncio.to_thread(
                    write_personalization, build_dir, profile, kind, items, build, token_record)
                for path in extra:
                    digest, extra_size = sha256_file(path)
                    hashes.append({"path": path.relative_to(build_dir).as_posix(),
                                   "sha256": digest, "size": extra_size})
            write_manifests(build_dir, hashes, build, session.user_id, kind, items, conflicts)
            (build_dir / "INSTRUKCJA.txt").write_text(
                instruction_text(
                    "TWOJA PACZKA CITIZEN" if kind == "citizen" else "TWOJA PACZKA SKINÓW BRONI",
                    items, conflicts, build, kind,
                ), encoding="utf-8")
            zip_path = DOWNLOADS_DIR / f"{kind}-{session.user_id}-{int(time.time())}.zip"
            size = await asyncio.to_thread(zip_directory, build_dir, zip_path)
            file_count = count_files(build_dir)
            return {"zip_path": zip_path, "size": size, "file_count": file_count,
                    "pack_token": (token_record or {}).get("token"),
                    "skipped": list(session.fatal_skipped),
                    "warnings": [i for i in session.validation_issues if i.get("severity") == "warn"]}
        finally:
            await asyncio.to_thread(safe_rmtree, build_dir, session.workspace)

    queue_note: Dict[str, int] = {"position": 1}

    async def on_queued(position: int) -> None:
        """Mówi graczowi, że bot go nie pominął i ile ma czekać."""
        if not QUEUE_NOTIFY:
            return
        queue_note["position"] = position
        if position > 1:
            average = (ZIP_QUEUE.total_wait_seconds / ZIP_QUEUE.completed) if ZIP_QUEUE.completed else 0.0
            eta = f" Szacowany czas oczekiwania: ~**{max(1, int(average))} s**." if average else ""
            await interaction.followup.send(
                f"⏳ Twoja paczka jest w kolejce — **pozycja {position}** "
                f"(pakuję maksymalnie {ZIP_QUEUE.concurrency_limit} naraz).{eta}", ephemeral=True)
        else:
            await interaction.followup.send("🔨 Pakuję Twoją paczkę... (zwykle kilka sekund)",
                                           ephemeral=True)

    async def on_start(wait_seconds: float) -> None:
        """Informuje, gdy po oczekiwaniu w kolejce startuje pakowanie."""
        if not QUEUE_NOTIFY or wait_seconds < 3 or queue_note["position"] <= 1:
            return
        try:
            await interaction.followup.send(
                f"✅ Kolejka wolna — kończę pakowanie (czekałem {wait_seconds:.0f} s).", ephemeral=True)
        except discord.HTTPException:
            pass

    priority = bool(PRIORITY_LANE and profile is not None and profile.level >= PRIORITY_LEVEL)
    try:
        result = await ZIP_QUEUE.add(build_package, on_queued=on_queued, on_start=on_start,
                                     priority=priority)
    except ApprovalRequired as exc:
        await request_approval(interaction, session, exc)
        return
    except Exception as exc:  # noqa: BLE001
        eid = await notify_error("Błąd budowania paczki",
                                 f"kind={kind}, pozycji={len(items)}, user={session.user_id}",
                                 exc, "deliver_package", getattr(interaction, "user", None))
        try:
            await interaction.followup.send(
                "😔 **Ups, coś poszło nie tak podczas pakowania paczki.**\n"
                "Twoje wybory nie przepadły — kliknij **📦 Zakończ** jeszcze raz.\n"
                f"Jeśli błąd wraca, zgłoś administracji kod: `{eid}`", ephemeral=True)
        except discord.HTTPException:
            pass
        return

    token = STORAGE.register(result["zip_path"], result["zip_path"].name, result["size"],
                             result["file_count"], session.user_id, workspace=session.workspace)
    link = public_download_url(token)
    attach_package = link is None      # brak publicznego URL-a → wysyłka załącznikiem
    session.delivered_at = time.time()

    lines = delivery_header_lines(result["zip_path"].name, result["size"],
                                  result["file_count"], build["name"], link,
                                  DOWNLOAD_TTL_MINUTES)
    if conflicts:
        lines += ["", f"⚠️ Auto-rozwiązano **{len(conflicts)}** konflikt(ów) plików."]

    # ANTY-CRASH: informacja o walidacji + auto-naprawach
    skipped = result.get("skipped") or []
    warnings = result.get("warnings") or []
    fixes = [fix for issue in session.validation_issues for fix in (issue.get("fixes") or [])]
    if skipped:
        lines += ["", f"⛔ **Odrzucono {len(skipped)} plików** (ryzyko crashu gry): "
                      f"{', '.join(skipped[:3])}{'…' if len(skipped) > 3 else ''}",
                  "Szczegóły w `VALIDACJA-PACZKI.txt` — wybierz inny wariant moda."]
    if warnings:
        lines += ["", f"🩺 Walidator zgłosił **{len(warnings)}** ostrzeżeń "
                      "(szczegóły w `VALIDACJA-PACZKI.txt`)."]
    if fixes:
        lines += ["", f"🔧 **Auto-naprawy wykonane przez bota:** {len(fixes)}",
                  "• " + "\n• ".join(fixes[:4])]
    if not skipped and not warnings and not fixes:
        lines += ["", "🩺 Walidacja anty-crash: **wszystkie pliki OK** ✅"]

    preview_link = public_preview_url(session.preview_token)
    if preview_link:
        lines += ["", f"🖼️ [Podgląd kombinacji]({preview_link})"]
    elif session.preview_token:
        lines += ["", "🖼️ Podgląd kombinacji — plik HTML w załączniku."]
    if result.get("pack_token"):
        lines += ["", f"🎫 **Twój token paczki:** `{result['pack_token']}` — "
                      "unikalny podpis tej paczki (możesz podać go administracji serwera)."]

    embed = discord.Embed(
        title="✅ Twoja paczka jest gotowa!" if kind == "citizen" else "✅ Twoja paczka skinów jest gotowa!",
        description="\n".join(lines), color=C_GREEN, timestamp=datetime.now(timezone.utc),
    )
    if profile is not None:
        embed.set_footer(text=(f"Wygenerowano dla {profile.username or profile.user_id} • "
                               f"{profile.rank['name']} (poziom {profile.level})"))
    await interaction.followup.send(embed=embed)

    # Bez publicznego URL-a paczkę wysyłamy załącznikiem — pobieranie musi działać
    # także na localhostcie (np. bot na VPS bez domeny albo w trakcie testów).
    if attach_package:
        if await send_package_attachments(interaction.channel, result["zip_path"],
                                          preview_token=session.preview_token):
            STORAGE.mark_downloaded(token)   # dysk zwolni się szybciej (GC po pobraniu)
        else:
            fp_log.error("Paczki %s nie wyslano jako zalacznika", result["zip_path"].name)
            try:
                await interaction.channel.send(
                    "⚠️ Nie udało się wysłać paczki jako załącznika Discorda. "
                    "Paczka czeka na serwerze bota — poproś administrację "
                    f"(`{result['zip_path'].name}`).")
            except discord.HTTPException:
                pass

    # --- Creator Economy: XP, odznaki, preferencje, historia ---
    if profile is not None:
        profile.builds += 1
        if kind == "citizen":
            profile.remember([tag for item in items for tag in tags_for_step(str(item.get("id", "")))])
            groups = {step["group"] for step in session.chosen_steps()}
            if len(groups) >= 6:
                if profile.badge("wszechstronny"):
                    await interaction.channel.send(f"🧩 Nowa odznaka: {BADGES['wszechstronny']}")
        else:
            profile.skins_picked += len(items)
            profile.remember(["skiny-broni"] * len(items))
            if profile.skins_picked >= 5 and profile.badge("zlota-bron"):
                await interaction.channel.send(f"🔫 Nowa odznaka: {BADGES['zlota-bron']}")
        profile.remember_build(build["id"])
        if len(profile.builds_seen) >= 3 and profile.badge("zna-buildy"):
            await interaction.channel.send(f"🎮 Nowa odznaka: {BADGES['zna-buildy']}")
        profile.add_history({
            "at": int(time.time()), "kind": kind, "build": build["id"],
            "token": result.get("pack_token"),
            "items": [str(i.get("id")) for i in items],
        })
        profile.badge("pierwsza-paczka")
        if profile.builds >= 10:
            profile.badge("konstruktor-10")
        if profile.builds >= 25:
            profile.badge("mistrz-25")
        profiles_save()

        await award_xp(profile, "build", interaction.channel, reason=f"paczka {kind}")
        await award_xp(profile, "option", interaction.channel,
                       amount=XP_EVENTS["option"] * len(items), reason="wybrane opcje")
        await award_xp(profile, "session", interaction.channel, reason="zakończona sesja")

    # ANTY-CRASH: odrzucone pliki trafiają do administracji (może podmienić źródło)
    if result.get("skipped"):
        await notify_error(
            "Walidator odrzucił pliki w paczce",
            (f"Gracz: <@{session.user_id}> • typ: {kind}\n"
             f"Odrzucone: {', '.join(str(s) for s in result['skipped'][:5])}\n"
             "Powód: struktura pliku wskazywała na ryzyko crashu GTA V."),
            None, "validator")

    # Most do FiveM: informacja o nowej paczce (in-game / kolejka dla resource'a)
    await bridge_notify(
        "📦 Nowa paczka Foundry",
        (f"{profile.username if profile else session.user_id} wygenerował paczkę "
         f"*{kind}* — {result['file_count']} plików, {result['size'] / 1024 / 1024:.1f} MB"
         + (f" • token `{result['pack_token']}`" if result.get("pack_token") else "")),
        kind="pack",
        meta={"user_id": session.user_id, "token": result.get("pack_token"), "kind": kind})

    # Publikacja na kanale #centrum-pobierania
    guild = interaction.guild
    downloads_channel = discord.utils.get(guild.text_channels, name=CH_DOWNLOADS)
    if downloads_channel:
        try:
            await downloads_channel.send(
                f"<@{session.user_id}> Twoja paczka: {link}" if link else
                f"<@{session.user_id}> paczka `{result['zip_path'].name}` została wysłana "
                "na kanał sesji jako załącznik.")
        except discord.HTTPException:
            pass

    close_view = LayoutView(discord.ui.Button(custom_id="session_close", label="Zamknij kanał",
                                             style=discord.ButtonStyle.danger, emoji="🔒"))
    await interaction.channel.send(
        f"Gotowe! Kliknij, aby zamknąć kanał (auto-zamknięcie po {CHANNEL_CLEANUP_MINUTES} min).",
        view=close_view,
    )

# ============================================================================
# 16. LIVE YOUTUBE FEED (YouTube Data API v3)
# ============================================================================

yt_log = log("YouTube")


class YouTubeQuotaError(Exception):
    """Brak limitów / klucza API YouTube."""


def _load_posted() -> set:
    """Wczytuje ID już opublikowanych filmów."""
    try:
        return set(json.loads(POSTED_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_posted(posted: set) -> None:
    """Zapisuje ID opublikowanych filmów (maks. 5000)."""
    try:
        POSTED_FILE.write_text(json.dumps(list(posted)[-5000:]), encoding="utf-8")
    except OSError as exc:
        yt_log.warning("Nie zapisano posted_videos.json: %s", exc)


def passes_filter(title: str, channel: str = "") -> bool:
    """Filtr: odrzuca serwerówki, cheaty i clickbaity."""
    text = f"{title} {channel}".lower()
    return not any(bad in text for bad in YT_BLACKLIST)


def classify_video(title: str) -> str:
    """Rozpoznaje kategorię moda po tytule filmu."""
    text = title.lower()
    for name, keywords in YT_CATEGORIES:
        if any(keyword in text for keyword in keywords):
            return name
    return "INNE"


# ---------------------------------------------------------------------------
# Rozdzielenie feedu na kanały tematyczne + rotacja zapytań
# ---------------------------------------------------------------------------

FEED_CHANNELS: Dict[str, str] = {
    "OPTI KOMPA": CH_FEED_PC,
    "SKINY BRONI": CH_FEED_SKINS,
    "POTATO": CH_FEED_MODS,
    "FIRST PERSON": CH_FEED_MODS,
    "OPTI": CH_FEED_MODS,
    "MAPY": CH_FEED_MODS,
    "AUTA": CH_FEED_MODS,
    "GRAFIKA": CH_FEED_MODS,
    "INNE": CH_MODS_LIVE,
}

FEED_CHANNEL_TOPICS: Dict[str, str] = {
    CH_FEED_MODS: "⚙️ Mody OPTI / FPS / potato / first person / mapy / auta z YouTube.",
    CH_FEED_SKINS: "🔫 Skin packi i tekstury .rpf do broni — najnowsze z YouTube.",
    CH_FEED_PC: "🖥️ Optymalizacja komputera pod FiveM: Windows, GPU, stutter, ping.",
    CH_MODS_LIVE: "📡 Reszta modów klienckich + archiwum feedu.",
}


def feed_channel_for(category: str) -> str:
    """Nazwa kanału, na który trafia film z danej kategorii."""
    return FEED_CHANNELS.get(category, CH_FEED_MODS)


def yt_recency_cutoff(days: Optional[int] = None) -> str:
    """Data graniczna ISO dla YouTube (domyślnie YT_MAX_AGE_DAYS wstecz, czyli 2 tygodnie)."""
    span = YT_MAX_AGE_DAYS if days is None else max(1, int(days))
    return (datetime.now(timezone.utc) - timedelta(days=span)).strftime("%Y-%m-%dT%H:%M:%SZ")


def yt_published_ts(published: str) -> int:
    """Timestamp publikacji filmu (0, gdy YouTube nie podał daty)."""
    try:
        return int(datetime.fromisoformat(str(published).replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return 0


def days_ago(published: str) -> int:
    """Ile dni temu opublikowano film (0 = dzisiaj / brak daty)."""
    stamp = yt_published_ts(published)
    if not stamp:
        return 0
    return max(0, int((time.time() - stamp) // 86400))


# Rotacja zapytań: jedno zapytanie YouTube kosztuje 100 z 10 000 darmowych
# jednostek na dobę, więc skanujemy porcjami — cały zestaw obraca się w kółko.
_yt_query_cursor = {"value": 0}
_yt_quota_block = {"until": 0.0, "count": 0}


def next_query_batch(queries: Optional[Sequence[str]] = None) -> List[str]:
    """Kolejna porcja zapytań do przeskanowania (rotacja)."""
    pool = list(queries if queries is not None else YT_QUERIES)
    if not pool:
        return []
    size = min(YT_QUERIES_PER_RUN, len(pool))
    start = _yt_query_cursor["value"] % len(pool)
    batch = [pool[(start + offset) % len(pool)] for offset in range(size)]
    _yt_query_cursor["value"] = (start + size) % len(pool)
    return batch


def yt_quota_blocked() -> bool:
    """True, gdy skaner odpoczywa po wyczerpaniu limitu YouTube API."""
    return time.time() < _yt_quota_block["until"]


def yt_quota_minutes_left() -> int:
    """Ile minut zostało do końca pauzy po limicie (0 = brak pauzy)."""
    left = _yt_quota_block["until"] - time.time()
    return max(0, int(left // 60) + 1) if left > 0 else 0


def yt_register_quota_error() -> int:
    """Wstrzymuje skan na YT_QUOTA_BACKOFF_MINUTES i zwraca liczbę takich zdarzeń z rzędu."""
    _yt_quota_block["count"] += 1
    _yt_quota_block["until"] = time.time() + YT_QUOTA_BACKOFF_MINUTES * 60
    return _yt_quota_block["count"]


def yt_reset_quota_block() -> None:
    """Zdejmuje pauzę (udany skan = limit znów działa)."""
    _yt_quota_block["until"] = 0.0
    _yt_quota_block["count"] = 0


async def fetch_videos(http: aiohttp.ClientSession, query: str) -> List[Dict[str, Any]]:
    """Pobiera najnowsze filmy dla jednego zapytania (z ostatnich YT_MAX_AGE_DAYS dni)."""
    published_after = yt_recency_cutoff()
    params = {
        "key": YOUTUBE_API_KEY, "q": query, "part": "snippet", "type": "video",
        "order": "date", "publishedAfter": published_after, "maxResults": "15",
        "relevanceLanguage": "pl",
    }
    async with http.get("https://www.googleapis.com/youtube/v3/search", params=params) as response:
        if response.status != 200:
            body = await response.text()
            raise YouTubeQuotaError(f"YouTube API HTTP {response.status}: {body[:200]}")
        data = await response.json()
    videos = []
    for item in data.get("items", []):
        video_id = (item.get("id") or {}).get("videoId")
        if not video_id:
            continue
        snippet = item.get("snippet", {})
        title = (snippet.get("title") or "") \
            .replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
        videos.append({
            "id": video_id, "title": title,
            "channel": snippet.get("channelTitle", ""),
            "published": snippet.get("publishedAt", ""),
            "description": snippet.get("description") or "",
            "thumbnail": ((snippet.get("thumbnails") or {}).get("medium") or {}).get("url")
            or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        })
    return videos


async def scan_videos() -> List[Dict[str, Any]]:
    """
    Skanuje YouTube i zwraca NOWE filmy z ostatnich YT_MAX_AGE_DAYS dni
    (mody klienckie + skiny .rpf + optymalizacja komputera).

    Każdy film dostaje kategorię i nazwę kanału, na który ma trafić, oraz
    `days_ago` — sortujemy od najświeższych, żeby feed był aktualny.
    """
    if not YOUTUBE_API_KEY:
        raise YouTubeQuotaError("Brak YOUTUBE_API_KEY w .env")
    if yt_quota_blocked():
        yt_log.info("Skan wstrzymany — limit YouTube API, jeszcze %s min.", yt_quota_minutes_left())
        return []

    queries = next_query_batch()
    yt_log.info("Skan YouTube: %s zapytan (ostatnie %s dni).", len(queries), YT_MAX_AGE_DAYS)
    posted = _load_posted()
    candidates: List[Dict[str, Any]] = []
    quota_error = False
    async with aiohttp.ClientSession() as http:
        for query in queries:
            try:
                for video in await fetch_videos(http, query):
                    if video["id"] in posted or not passes_filter(video["title"], video["channel"]):
                        continue
                    video["category"] = classify_video(video["title"])
                    video["channel_name"] = feed_channel_for(video["category"])
                    video["days_ago"] = days_ago(video.get("published", ""))
                    video["safe_links"] = safe_links_from_description(video["description"])
                    posted.add(video["id"])
                    candidates.append(video)
            except YouTubeQuotaError as exc:
                quota_error = True
                yt_log.error('Limit YouTube przy "%s": %s', query, exc)
            except Exception as exc:  # noqa: BLE001
                yt_log.error('Blad zapytania "%s": %s', query, exc)
            await asyncio.sleep(0.3)

    if quota_error:
        count = yt_register_quota_error()
        yt_log.warning("Limit YouTube API wyczerpany (%s. raz) — pauza %s min.",
                       count, YT_QUOTA_BACKOFF_MINUTES)
    else:
        yt_reset_quota_block()

    if not candidates:
        return []

    seen: set = set()
    unique = [v for v in candidates if not (v["id"] in seen or seen.add(v["id"]))]
    unique.sort(key=lambda v: (v.get("days_ago", 0), v["category"]))
    _save_posted(posted)
    return unique[:30]


async def post_videos(bot: "FoundryBot", videos: Sequence[Dict[str, Any]]) -> int:
    """
    Rozdziela filmy na kanały tematyczne każdego serwera:

    • 🔫 #skiny-rpf — skin packi i tekstury .rpf do broni,
    • ⚙️ #mody-opti — opti/potato/first person/mapy/auta/grafika,
    • 🖥️ #opti-kompa — optymalizacja komputera (Windows, GPU, stutter, ping),
    • 📡 #mody-optymalizacja-live — reszta i archiwum feedu.

    Brakujące kanały bot tworzy sam.
    """
    posted = 0
    per_channel: Dict[str, int] = {}
    posted_titles: List[str] = []
    for guild in bot.guilds:
        category = discord.utils.get(guild.categories, name=CAT_MODS)
        if category is None:
            try:
                category = await ensure_category(guild, CAT_MODS)
            except discord.HTTPException as exc:
                yt_log.warning("Nie utworzono kategorii %s na %s: %s", CAT_MODS, guild.name, exc)
                continue
        for video in videos:
            channel_name = str(video.get("channel_name")
                               or feed_channel_for(str(video.get("category"))))
            channel = find_channel(guild, CAT_MODS, channel_name)
            if channel is None:
                try:
                    channel = await ensure_text_channel(
                        guild, category, channel_name, FEED_CHANNEL_TOPICS.get(channel_name, ""))
                except discord.HTTPException as exc:
                    yt_log.warning("Nie utworzono kanalu #%s na %s: %s", channel_name, guild.name, exc)
                    continue

            links = video.get("safe_links") or []
            links_text = ("\n**🔗 Linki z opisu:**\n" + "\n".join(
                f"- [{link['host']}]({link['url']})" for link in links[:3])) if links else \
                "\n*Brak zweryfikowanych linków w opisie — sprawdź sam w filmie.*"
            published_ts = yt_published_ts(video.get("published", ""))
            embed = discord.Embed(
                title=f"🎬 [{video['category']}] {video['title'][:230]}",
                url=f"https://www.youtube.com/watch?v={video['id']}",
                description=(
                    f"**Kategoria:** `{video['category']}` • **kanał docelowy:** #{channel_name}\n"
                    f"**Autor:** {video['channel']}\n"
                    f"**Opublikowano:** <t:{published_ts}:R>"
                    + (f" (świeże — {video['days_ago']} dni temu)" if video.get("days_ago") else "")
                    + f"{links_text}\n\n⚠️ Sprawdź regulamin serwera, na którym grasz!"
                ),
                color=C_ORANGE, timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=video["thumbnail"])
            embed.set_footer(text=f"Live Mod Feed • ostatnie {YT_MAX_AGE_DAYS} dni • "
                                  "tylko mody klienckie (client-side)")
            try:
                await channel.send(embed=embed)
                posted += 1
                per_channel[channel_name] = per_channel.get(channel_name, 0) + 1
                posted_titles.append(str(video.get("title"))[:80])
            except discord.HTTPException as exc:
                yt_log.warning("Nie wyslano na #%s (%s): %s", channel_name, guild.name, exc)
    if posted:
        summary = ", ".join(f"#{name}: {count}" for name, count in sorted(per_channel.items()))
        yt_log.info("Feed: %s filmow (%s).", posted, summary)
        await bridge_notify(
            "🎬 Nowe mody w feedzie",
            f"Wrzucono {posted} filmów ({summary}): " + "; ".join(posted_titles[:3]),
            kind="mods", meta={"count": posted, "channels": per_channel})
    return posted


async def run_scan(bot: "FoundryBot", interaction: Optional[discord.Interaction] = None) -> None:
    """Pełny skan + publikacja (używane też przez /skanuj)."""
    try:
        videos = await scan_videos()
        count = await post_videos(bot, videos)
        yt_log.info("Skan YouTube: %s nowych filmow.", count)
        pings = await send_smart_pings(bot, videos)
        if pings:
            yt_log.info("Smart pingi: %s spersonalizowanych rekomendacji na priv.", pings)
        if interaction:
            await interaction.followup.send(
                f"✅ Skan zakończony — wrzucono **{count}** nowych filmów "
                f"(z ostatnich **{YT_MAX_AGE_DAYS} dni**) na kanały "
                f"#{CH_FEED_SKINS}, #{CH_FEED_MODS} i #{CH_FEED_PC}"
                + (f", wysłano **{pings}** spersonalizowanych rekomendacji." if pings else ".")
                + (f"\n⏳ Limit YouTube API — kolejny skan za ~{yt_quota_minutes_left()} min."
                   if yt_quota_blocked() else ""))
    except Exception as exc:  # noqa: BLE001
        yt_log.error("Blad skanera: %s", exc)
        if interaction:
            await interaction.followup.send(f"❌ Błąd skanera: {exc}", ephemeral=True)


async def scanner_loop(bot: "FoundryBot") -> None:
    """Pętla live feedu (co YT_SCAN_MINUTES)."""
    await bot.wait_until_ready()
    await asyncio.sleep(20)
    while not bot.is_closed():
        await run_scan(bot)
        await asyncio.sleep(YT_SCAN_MINUTES * 60)

# ============================================================================
# 17. WYSZUKIWARKA SKINÓW (.rpf TYLKO)
# ============================================================================

skin_log = log("SkinSearcher")
_index_cache: List[Dict[str, Any]] = []
_index_cached_at = 0.0


def is_rpf(file_url: str) -> bool:
    """Czy plik kończy się na .rpf (krytyczny filtr)?"""
    if not file_url:
        return False
    try:
        return urlparse(file_url).path.lower().endswith(".rpf")
    except Exception:
        return file_url.lower().split("?")[0].endswith(".rpf")


async def load_index() -> List[Dict[str, Any]]:
    """Ładuje zewnętrzny indeks skinów (z cache 15 min)."""
    global _index_cache, _index_cached_at
    if _index_cache and time.time() - _index_cached_at < 15 * 60:
        return _index_cache
    if not SKIN_INDEX_URL or "twoj-user" in SKIN_INDEX_URL:
        skin_log.warning("SKIN_INDEX_URL nie skonfigurowany — wyszukiwarka pusta.")
        return []
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": "FiveMModFoundry/2.0"}) as http:
            async with http.get(SKIN_INDEX_URL) as response:
                if response.status != 200:
                    raise ValueError(f"HTTP {response.status}")
                data = await response.json(content_type=None)
        if not isinstance(data, list):
            raise ValueError("Indeks nie jest tablicą JSON")
        _index_cache = data
        _index_cached_at = time.time()
        skin_log.info("Indeks skinów załadowany: %s pozycji", len(data))
        return data
    except Exception as exc:  # noqa: BLE001
        skin_log.error("Blad ladowania indeksu: %s", exc)
        return []


def _normalize(text: str) -> str:
    """Lower-case + usunięcie znaków specjalnych."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())).strip()


def _score(item: Dict[str, Any], tokens: Sequence[str]) -> int:
    """Trafność wyniku (0 = brak dopasowania)."""
    name = _normalize(item.get("name", ""))
    desc = _normalize(item.get("description", ""))
    tags = " ".join(_normalize(t) for t in (item.get("tags") or []))
    author = _normalize(item.get("author", ""))
    score = 0
    for token in tokens:
        if token in name:
            score += 10
        elif token in tags:
            score += 5
        elif token in desc:
            score += 3
        elif token in author:
            score += 2
        else:
            return 0
    return score


# Broń, których dotyczy wyszukiwarka skinów .rpf (życzenie użytkownika):
#   pistol / pistolmk2 / vintagepistol / snspistol (+ snspistolmk2).
ALLOWED_WEAPON_IDS = {"pistol", "pistolmk2", "vintagepistol", "snspistol", "snspistolmk2"}
ALLOWED_WEAPON_TOKENS = tuple(sorted(ALLOWED_WEAPON_IDS))


async def search_skins(query: str) -> Dict[str, Any]:
    """Wyszukuje skiny w indeksie — zwraca TYLKO pliki .rpf."""
    if not query or len(query.strip()) < 2:
        return {"error": "Zapytanie musi mieć min. 2 znaki."}
    index = await load_index()
    if not index:
        return {"error": "Indeks skinów pusty lub nieosiągalny. Sprawdź SKIN_INDEX_URL w .env."}
    tokens = [t for t in _normalize(query).split(" ") if t]
    if not tokens:
        return {"error": "Zapytanie po normalizacji jest puste."}
    results = []
    for item in index:
        if not is_rpf(item.get("fileUrl", "")):
            continue
        # LIMIT BRONI: tylko pistol / pistolmk2 / vintagepistol / snspistol (+ Mk II).
        haystack = " ".join((
            _normalize(item.get("name", "")), _normalize(item.get("description", "")),
            " ".join(_normalize(t) for t in (item.get("tags") or [])),
            _normalize(item.get("weapon", "")), _normalize(item.get("id", "")),
        ))
        if not any(token in haystack for token in ALLOWED_WEAPON_TOKENS):
            continue
        score = _score(item, tokens)
        if score > 0:
            results.append({**item, "score": score})
    results.sort(key=lambda i: i["score"], reverse=True)
    return {"results": results[:10]}

# ============================================================================
# 18. WIDOKI (tylko layout — logikę obsługuje router on_interaction)
# ============================================================================


class LayoutView(discord.ui.View):
    """
    Widok zawierający wyłącznie komponenty układu.

    Logika jest w jednym miejscu (FoundryBot.on_interaction → router po
    custom_id), dlatego elementy nie mają callbacków. Dzięki temu przyciski
    działają też po restarcie bota (Discord nadal zna custom_id).
    """

    def __init__(self, *rows: Any) -> None:
        super().__init__(timeout=None)
        for row_index, row in enumerate(rows):
            items = row if isinstance(row, (list, tuple)) else [row]
            for item in items:
                item.row = row_index
                self.add_item(item)


def btn(custom_id: str, label: str, style: discord.ButtonStyle = discord.ButtonStyle.secondary,
        emoji: Optional[str] = None) -> discord.ui.Button:
    """Skrót do tworzenia przycisku."""
    return discord.ui.Button(custom_id=custom_id, label=label[:80], style=style, emoji=emoji)


def opt(label: str, value: str, description: Optional[str] = None,
        default: bool = False) -> discord.SelectOption:
    """Skrót do tworzenia opcji select menu."""
    return discord.SelectOption(label=label[:100], value=value[:100],
                                description=(description or "")[:100] or None, default=default)


def select(custom_id: str, placeholder: str, options: Sequence[discord.SelectOption]) -> discord.ui.Select:
    """Skrót do tworzenia menu wyboru (maks. 25 opcji)."""
    return discord.ui.Select(custom_id=custom_id, placeholder=placeholder[:150],
                             options=list(options)[:25])


def all_weapons() -> List[Dict[str, Any]]:
    """Wszystkie bronie z kategorii (spłaszczone)."""
    return [weapon for category in WEAPON_CATEGORIES for weapon in category["weapons"]]


def find_weapon(weapon_id: str) -> Optional[Dict[str, Any]]:
    """Znajduje broń po ID."""
    return next((w for w in all_weapons() if w["id"] == weapon_id), None)


def short_group(group: str) -> str:
    """Krótka nazwa grupy do etykiety selecta."""
    return re.sub(r"^[^\s]+\s*", "", group).split("—")[0].strip()[:20]


def page_count(total: int, per_page: int) -> int:
    """Ile stron potrzeba dla danej liczby elementów (Discord: max 25 na select)."""
    return max(1, (max(0, total) + per_page - 1) // per_page)


def step_jump_options(index: int) -> List[discord.SelectOption]:
    """
    Opcje selecta „przeskocz do kroku”.

    Discord pozwala na 25 opcji, więc przy większej liczbie kroków pokazujemy
    okno STEPS_PER_PAGE wokół bieżącego kroku (paginacja zamiast ucięcia listy).
    """
    total = len(CITIZEN_STEPS)
    if total <= 25:
        indices = range(total)
    else:
        span = min(STEPS_PER_PAGE, 25)
        start = max(0, min(index - span // 2, total - span))
        indices = range(start, start + span)
    return [opt(f"{short_group(CITIZEN_STEPS[i]['group'])}: {CITIZEN_STEPS[i]['name']}", str(i),
                f"{i + 1}/{total}", default=(i == index)) for i in indices]


def step_embed(step: Dict[str, str], index: int, chosen: bool, level: int = 99) -> discord.Embed:
    """
    Embed jednego kroku kreatora citizena (ze zdjęciem efektu w grze).

    Presety ekskluzywne (EXCLUSIVE_STEPS) pokazują się z blokadą 🔒 dopóki
    gracz nie zdobędzie wymaganego poziomu twórcy.
    """
    locked = level < min_level_of(step)
    description = f"**{step['name']}**\n{step['description']}\n\n"
    if locked:
        description += lock_text(step)
    elif chosen:
        description += "✅ **Dodano do Twojej paczki.**"
    else:
        description += "⬜ *Nie dodano — kliknij „Dodaj do paczki'.*"
    embed = discord.Embed(
        title=f"{step['group']} — {index + 1}/{len(CITIZEN_STEPS)}",
        description=description,
        color=C_YELLOW if locked else (C_GREEN if chosen else C_BLUE),
    )
    embed.set_image(url=embed_image_ref(step_image_key(step)))
    embed.set_footer(text=(
        "🔒 Preset ekskluzywny — zbuduj więcej paczek, aby odblokować" if locked
        else "Podgląd generowany przez bota • własny plik dodasz przyciskiem 📎"))
    return embed


def build_select_view(session: Session) -> discord.ui.View:
    """
    Widok kroku: TYLKO przyciski (żadnej rozwijanej listy ani przewijania).

    Opcje pokazują się **jedna po drugiej** i bot pyta o każdą z osobna:

    1. ➕ Dodaj do paczki / ✅ Dodano (kliknięcie zabiera lub przywraca),\n
    2. ◀ Wstecz / ⏭ Pomiń i dalej / ▶ Dalej — przejście do kolejnej opcji,\n
    3. 📎 Własny plik, 📋 Podsumowanie, 🔒 Zamknij.

    Dzięki temu gracz nie szuka niczego na liście — klika i leci dalej.
    """
    if locked:
        first = btn(f"citizen_locked:{index}", f"🔒 Wymaga poziomu {level}",
                    discord.ButtonStyle.secondary)
    else:
        first = btn(f"citizen_add:{index}",
                    "✅ Dodano (kliknij, aby usunąć)" if chosen else "➕ Dodaj do paczki",
                    discord.ButtonStyle.danger if chosen else discord.ButtonStyle.success,
                    "✅" if chosen else "➕")
    nav: List[discord.ui.Button] = []
    if index > 0:
        nav.append(btn(f"citizen_back:{index}", "◀ Wstecz", discord.ButtonStyle.secondary))
    nav.append(btn(f"citizen_skip:{index}", "⏭ Pomiń i dalej", discord.ButtonStyle.secondary))
    nav.append(btn(f"citizen_next:{index}", "▶ Dalej", discord.ButtonStyle.primary))
    tools = [
        btn("citizen_upload", "📎 Własny plik", discord.ButtonStyle.secondary),
        btn("citizen_summary", "📋 Podsumowanie", discord.ButtonStyle.secondary),
        btn("session_close", "🔒 Zamknij", discord.ButtonStyle.danger),
    ]
    return LayoutView([first], nav, tools)


def web_creator_link(user_id: int, kind: str = "citizen") -> str:
    """
    Adres kreatora WWW dla gracza (przekierowanie z Discorda na stronę).
    """
    return f"{PUBLIC_URL}/create/{kind}?user={user_id}"


def web_link_button(user_id: int, kind: str = "citizen") -> discord.ui.Button:
    """Przycisk-link „🌐 Otwórz w przeglądarce” — prowadzi do kreatora WWW."""
    return discord.ui.Button(label="🌐 Otwórz w przeglądarce (duże zdjęcia)",
                             url=web_creator_link(user_id, kind), row=4)


def step_view(index: int, chosen: bool, locked: bool = False, level: int = 0,
              user_id: int = 0) -> discord.ui.View:
    """
    Widok kroku: TYLKO przyciski (żadnej rozwijanej listy ani przewijania).

    Opcje pokazują się **jedna po drugiej** i bot pyta o każdą z osobna:\n

    1. ➕ Dodaj do paczki / ✅ Dodano (kliknięcie zabiera lub przywraca),\n
    2. ◀ Wstecz / ⏭ Pomiń i dalej / ▶ Dalej — przejście do kolejnej opcji,\n
    3. 🌐 Otwórz w przeglądarce — ten sam krok na ładnej stronie WWW,\n    4. 📎 Własny plik, 📋 Podsumowanie, 🔒 Zamknij.

    Dzięki temu gracz nie szuka niczego na liście — klika i leci dalej.
    """
    if locked:
        first = btn(f"citizen_locked:{index}", f"🔒 Wymaga poziomu {level}",
                    discord.ButtonStyle.secondary)
    else:
        first = btn(f"citizen_add:{index}",
                    "✅ Dodano (kliknij, aby usunąć)" if chosen else "➕ Dodaj do paczki",
                    discord.ButtonStyle.danger if chosen else discord.ButtonStyle.success,
                    "✅" if chosen else "➕")
    nav: List[discord.ui.Button] = []
    if index > 0:
        nav.append(btn(f"citizen_back:{index}", "◀ Wstecz", discord.ButtonStyle.secondary))
    nav.append(btn(f"citizen_skip:{index}", "⏭ Pomiń i dalej", discord.ButtonStyle.secondary))
    nav.append(btn(f"citizen_next:{index}", "▶ Dalej", discord.ButtonStyle.primary))
    tools = [
        btn("citizen_upload", "📎 Własny plik", discord.ButtonStyle.secondary),
        web_link_button(user_id, "citizen"),
        btn("citizen_summary", "📋 Podsumowanie", discord.ButtonStyle.secondary),
        btn("session_close", "🔒 Zamknij", discord.ButtonStyle.danger),
    ]
    return LayoutView([first], nav, tools)


def build_select_view(session: Session) -> discord.ui.View:
    """Select menu wyboru docelowego buildu GTA V."""
    return LayoutView([select(
        "build_pick", "🎮 Docelowy build GTA V / FiveM...",
        [opt(b["name"], b["id"], b["note"], default=(b["id"] == session.build_id)) for b in GAME_BUILDS],
    )])


def summary_view() -> discord.ui.View:
    """Widok podsumowania citizena."""
    return LayoutView([
        btn("citizen_finish", "Zakończ tworzenie", discord.ButtonStyle.success, "📦"),
        btn("citizen_restart", "Zacznij od nowa", discord.ButtonStyle.secondary, "🔄"),
        btn("session_close", "Zamknij", discord.ButtonStyle.danger, "🔒"),
    ])


def ticket_view(session: Session, with_mode: bool = True) -> discord.ui.View:
    """Widok startowy ticketa: tryb (opcjonalnie) + wybór buildu."""
    rows: List[Any] = []
    if with_mode:
        rows.append([
            btn("mode_citizen", "Citizen (mody wizualne)", discord.ButtonStyle.primary, "🛠️"),
            btn("mode_weapons", "Skiny broni", discord.ButtonStyle.secondary, "🔫"),
        ])
    rows.append([select(
        "build_pick", "🎮 Docelowy build GTA V / FiveM...",
        [opt(b["name"], b["id"], b["note"], default=(b["id"] == session.build_id)) for b in GAME_BUILDS],
    )])
    return LayoutView(*rows)


def citizen_summary_embed(session: Session) -> Tuple[discord.Embed, List[Dict[str, Any]]]:
    """Embed podsumowania citizena (presety + skiny broni + własne pliki + konflikty)."""
    kept, dropped, conflicts = resolve_conflicts(session.chosen_steps())
    skins = session.collect_skins()
    uploads = session.collect_uploads()
    build = build_by_id(session.build_id)
    total = len(kept) + len(skins) + len(uploads)

    lines: List[str] = []
    if kept:
        lines.append(f"🎨 **Presety citizena ({len(kept)}):**")
        # Przy dużej liczbie opcji (katalog 100+) pokazujemy tylko pierwszych 20
        # nazw — reszta jest w kreatorze WWW; embed ma limit 4096 znaków.
        show_desc = len(kept) <= 20
        visible = kept if show_desc else kept[:20]
        lines += [f"✅ **{s['name']}**" + (f" — {s['description']}" if show_desc else "")
                  for s in visible]
        if len(kept) > 20:
            lines.append(f"…oraz {len(kept) - 20} więcej (pełna lista w paczce)")
    if skins:
        lines.append("")
        lines.append(f"🔫 **Skiny broni ({len(skins)}):**")
        lines += [f"✅ **{s['name']}** — {s.get('description') or ''}" for s in skins[:15]]
    if uploads:
        lines.append("")
        lines.append(f"📎 **Własne pliki ({len(uploads)}):**")
        lines += [f"• `{u['name']}` ({u.get('size', 0) / 1024:.0f} KB) → `{u['target']}`"
                  for u in uploads[:15]]
    if not total:
        lines = ["*Nie wybrano jeszcze nic.*",
                 "⬅️ Dodawaj opcje przyciskami **➕ Dodaj do paczki** / **⏭ Pomiń** "
                 "(pokazują się jedna po drugiej), a swój plik wrzucisz przyciskiem **📎 Własny plik**."]
    else:
        lines.append("")
        lines.append(f"📦 **Pozycji w paczce:** {total} "
                     f"(presety: {len(kept)}, skiny: {len(skins)}, własne pliki: {len(uploads)})")
    if dropped:
        lines += ["", "⚠️ **Wykryto konflikty plików** — zainstalowany zostanie **ostatnio wybrany** wariant:"]
        # Przy wielu konfliktach skracamy wiersz (limit 4096 znaków na embed)
        max_conf = 12 if len(kept) > 40 else 25
        max_dropped = 5 if len(kept) > 40 else 8
        lines += [f"• `{c['file']}` → **{c['winner']}** (pominięto: {', '.join(c['dropped'][:max_dropped])}"
                  + (f" …+{len(c['dropped']) - max_dropped}" if len(c['dropped']) > max_dropped else "") + ")"
                  for c in conflicts[:max_conf]]
        if len(conflicts) > max_conf:
            lines.append(f"• …i {len(conflicts) - max_conf} innych konfliktów (ostatni wybór wygrywa)")
    lines += ["", f"🎮 **Docelowy build GTA V:** {build['name']}"]
    # Twarda granica Discorda: 4096 znaków na opis embeda.
    desc = "\n".join(lines)
    if len(desc) > 4096:
        desc = desc[:4020].rsplit("\n", 1)[0] + "\n…(skrócono — pełna lista jest w wygenerowanej paczce)"
    embed = discord.Embed(title="📋 Podsumowanie Twojej paczki Citizen",
                          description=desc, color=C_YELLOW)
    embed.set_footer(text="📦 Zbuduj paczkę = ZIP • 📎 = Twój własny plik • ◀ Wróć = kolejne opcje")
    return embed, conflicts


def publish_citizen_preview(session: Session, conflicts: Sequence[Dict[str, Any]]) -> Optional[str]:
    """Generuje podgląd całej paczki citizena (presety + skiny + własne pliki)."""
    items = session.package_items("citizen")
    if not items:
        return None
    page = render_preview_html(items, conflicts, build_by_id(session.build_id)["name"], "Podgląd citizena")
    session.preview_token = STORAGE.register_preview(page, "Podgląd citizena", session.user_id)
    return public_preview_url(session.preview_token)


def publish_skins_preview(session: Session, skins: Sequence[Dict[str, Any]]) -> Optional[str]:
    """Generuje podgląd wybranych skinów broni i zwraca link."""
    if not skins:
        return None
    page = render_preview_html(skins, [], build_by_id(session.build_id)["name"], "Podgląd skinów broni")
    session.preview_token = STORAGE.register_preview(page, "Podgląd skinów", session.user_id)
    return public_preview_url(session.preview_token)

# ============================================================================
# 18b. WŁASNE PLIKI GRACZA (📎) — bez hostingu, prosto z Discorda
# ============================================================================

upload_log = log("Uploads")

# (cel instalacji, etykieta przycisku)
UPLOAD_TARGETS: Tuple[Tuple[str, str], ...] = (
    (T_MODS, "📦 Mod / paczka (.rpf/.zip)"),
    (T_WEAPONS_TEX, "🔫 Tekstura broni (.ytd/.ydr)"),
    (T_DATA, "🧩 Ustawienia (.xml/.dat/.meta)"),
    (T_EFFECTS, "🎬 Efekty (krew/iskry/ogień)"),
    ("mods/update/x64/dlcpacks", "👕 Model postaci / pojazdu"),
)

UPLOAD_EXTENSIONS: Tuple[str, ...] = (
    ".rpf", ".ytd", ".ydr", ".ydd", ".xml", ".dat", ".meta", ".zip", ".oiv",
    ".asi", ".ini", ".png", ".jpg", ".jpeg", ".webp",
)
UPLOAD_IMAGE_EXT: Tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp", ".gif")
UPLOAD_UA = {"User-Agent": "FiveMModFoundry/3.0"}


def upload_target_label(target: str) -> str:
    """Ładna nazwa celu instalacji pliku."""
    return dict(UPLOAD_TARGETS).get(target, target or T_MODS)


def uploads_dir(session: Session) -> Path:
    """Katalog na własne pliki gracza (w jego workspace)."""
    path = session.workspace / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_upload_name(name: str) -> str:
    """Bezpieczna nazwa pliku z załącznika (bez ścieżek i dziwnych znaków)."""
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(str(name)).name).strip("._")
    return (clean or "plik.bin")[:80]


def upload_target_buttons() -> discord.ui.View:
    """Przyciski wyboru celu instalacji (bez rozwijanych list — same przyciski)."""
    rows: List[List[discord.ui.Button]] = []
    current: List[discord.ui.Button] = []
    for target, label in UPLOAD_TARGETS:
        current.append(btn(f"upload_target:{target}", label, discord.ButtonStyle.secondary))
        if len(current) == 3:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    rows.append([btn("upload_cancel", "✖ Anuluj", discord.ButtonStyle.danger)])
    return LayoutView(*rows)


def upload_prompt_embed(session: Session, target: str = "") -> discord.Embed:
    """Instrukcja: wybierz cel, potem wyślij plik jako załącznik (albo link)."""
    formats = ".rpf .ytd .ydr .ydd .xml .dat .meta .zip .png .jpg"
    if not target:
        return discord.Embed(
            title="📎 Własny plik — gdzie ma trafić?",
            description=("Wybierz przyciskiem miejsce instalacji, a potem **wyślij plik jako "
                         "załącznik na tym kanale** (możesz też wkleić sam link).\n\n"
                         f"• Maksymalny rozmiar: **{UPLOAD_MAX_MB} MB** na plik\n"
                         f"• Maksymalnie **{UPLOAD_MAX_FILES}** własnych plików w paczce\n"
                         f"• Formaty: {formats}"),
            color=C_PURPLE)
    return discord.Embed(
        title=f"📎 Wyślij plik — cel: {upload_target_label(target)}",
        description=("**Wyślij plik jako załącznik na tym kanale** — bot pobierze go na swój dysk "
                     "i włoży do Twojej paczki (nic nie musisz hostować).\n\n"
                     f"📁 Cel instalacji: `{target}`\n"
                     f"📏 Limit: **{UPLOAD_MAX_MB} MB** • formaty: {formats}\n\n"
                     "Wklejenie linku do pliku (`https://...`) też zadziała.\n"
                     "Nie chcesz? Kliknij **✖ Anuluj**."),
        color=C_GREEN)


def register_upload(session: Session, name: str, data: bytes, target: str,
                    url: str = "") -> Optional[Dict[str, Any]]:
    """Zapisuje własny plik gracza na dysk i zwraca pozycję paczki."""
    try:
        dest = uploads_dir(session) / name
        dest.write_bytes(data)
    except OSError as exc:
        upload_log.error("Nie zapisano pliku %s: %s", name, exc)
        return None
    extension = Path(name).suffix.lower()
    record: Dict[str, Any] = {
        "id": f"upload-{len(session.uploads) + 1}",
        "name": name,
        "description": f"własny plik gracza — {upload_target_label(target)}",
        "group": "📎 Własne pliki",
        "target": target,
        "local_path": str(dest),
        "file_name": name,
        "file_url": "",
        "image": "",
        "size": len(data),
        "url": url,
        "is_image": extension in UPLOAD_IMAGE_EXT,
        "kind": session.upload_kind,
    }
    session.uploads.append(record)
    upload_log.info("Upload user=%s %s -> %s (%.1f KB)",
                    session.user_id, name, target, len(data) / 1024)
    return record


async def fetch_upload_link(session: Session, url: str, target: str) -> Optional[Dict[str, Any]]:
    """Pobiera plik z linku wklejonego przez gracza i dodaje go do paczki."""
    limit = UPLOAD_MAX_MB * 1024 * 1024
    name = safe_upload_name(file_name_from_url(url) or "plik.bin")
    if Path(name).suffix.lower() not in UPLOAD_EXTENSIONS:
        return None
    try:
        async with aiohttp.ClientSession(headers=UPLOAD_UA) as http:
            async with http.get(url, timeout=aiohttp.ClientTimeout(total=45)) as response:
                if response.status != 200:
                    return None
                data = await response.content.read(limit + 1)
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        upload_log.warning("Nie pobrano pliku z linku %.60s: %s", url, exc)
        return None
    if not data or len(data) > limit:
        return None
    return register_upload(session, name, data, target, url)


async def deliver_upload_report(channel: discord.abc.Messageable, session: Session,
                               added: Sequence[Dict[str, Any]],
                               rejected: Sequence[str]) -> None:
    """Raport po wgraniu: co weszło do paczki, co odpadło + przyciski dalej."""
    lines = ([f"✅ **Dodano do paczki ({len(added)}):**"]
             + [f"• `{u['name']}` ({u.get('size', 0) / 1024:.1f} KB) → `{u['target']}`"
                for u in added]) if added else ["⚠️ Nie dodano żadnego pliku."]
    if rejected:
        lines += ["", "❌ **Odrzucone:**"] + [f"• {item}" for item in rejected]
    lines += ["", f"📎 Własnych plików w paczce: **{len(session.uploads)}**"]
    embed = discord.Embed(title="📎 Własne pliki", description="\n".join(lines),
                          color=C_GREEN if added else C_YELLOW)
    image = next((u["url"] for u in reversed(list(added)) if u.get("is_image") and u.get("url")), "")
    if image:
        embed.set_image(url=image)
    embed.set_footer(text="Wrzuć kolejny plik przyciskiem 📎 albo wróć do kreatora ▶")
    rows: List[Any] = [[
        btn("citizen_upload", "📎 Dodaj kolejny", discord.ButtonStyle.primary),
        btn("upload_done", "▶ Wróć do kreatora", discord.ButtonStyle.success),
    ], [
        btn("citizen_summary", "📋 Podsumowanie", discord.ButtonStyle.secondary),
        btn("session_close", "🔒 Zamknij", discord.ButtonStyle.danger),
    ]]
    try:
        await channel.send(embed=embed, view=LayoutView(*rows))
    except discord.HTTPException as exc:
        sys_log.warning("Nie wyslano raportu wlasnych plikow: %s", exc)


async def handle_upload_message(message: discord.Message, session: Session) -> bool:
    """
    Obsługuje własne pliki gracza (przycisk 📎): załączniki albo linki.

    Zwraca True, gdy wiadomość była próbą wgrania pliku (i została obsłużona).
    """
    files = list(message.attachments)
    links = [] if files else re.findall(r"https?://\S+", message.content or "")
    if not files and not links:
        return False
    target = session.upload_target or T_MODS
    session.upload_armed = False
    added: List[Dict[str, Any]] = []
    rejected: List[str] = []

    for source in files:
        name = safe_upload_name(source.filename)
        extension = Path(name).suffix.lower()
        if len(session.uploads) >= UPLOAD_MAX_FILES:
            rejected.append(f"`{name}` — limit {UPLOAD_MAX_FILES} własnych plików w paczce")
            continue
        if extension not in UPLOAD_EXTENSIONS:
            rejected.append(f"`{name}` — nieobsługiwany format ({extension or 'brak'})")
            continue
        data = await source.read()
        if not data:
            rejected.append(f"`{name}` — plik jest pusty")
            continue
        if len(data) > UPLOAD_MAX_MB * 1024 * 1024:
            rejected.append(f"`{name}` — większy niż {UPLOAD_MAX_MB} MB")
            continue
        record = register_upload(session, name, data, target, source.url)
        if record:
            added.append(record)
        else:
            rejected.append(f"`{name}` — nie udało się zapisać na dysku")

    for link in links[:3]:
        record = await fetch_upload_link(session, link, target)
        if record:
            added.append(record)
        else:
            rejected.append(f"`{link[:70]}` — nie udało się pobrać (zły link, format lub rozmiar)")

    try:
        await message.delete()
    except discord.HTTPException:
        pass
    await deliver_upload_report(message.channel, session, added, rejected)
    return True


# ============================================================================
# 19. KREATOR CITIZENA — wysyłanie kroków
# ============================================================================


async def send_with_image(channel: discord.abc.Messageable, *, key: str, data: bytes,
                          embed: discord.Embed, view: discord.ui.View,
                          content: Optional[str] = None) -> None:
    """Wysyła wiadomość z wygenerowanym podglądem (załącznik, gdy brak PUBLIC_URL)."""
    file = image_attachment(key, data)
    try:
        if file is None:
            await channel.send(content=content, embed=embed, view=view)
        else:
            await channel.send(content=content, embed=embed, view=view, file=file)
    except discord.HTTPException as exc:
        sys_log.warning("Nie wyslano wiadomosci z podgladem (%s): %s", key, exc)


async def edit_with_image(interaction: discord.Interaction, *, key: str, data: bytes,
                          embed: discord.Embed, view: discord.ui.View) -> None:
    """
    Edytuje wiadomość z nowym podglądem.

    Discord nie pozwala dopiąć pliku do edycji tak jak do nowej wiadomości,
    dlatego próbujemy `attachments=[file]`, a gdy wersja biblioteki tego nie
    wspiera — edytujemy sam embed (obrazek z /img/ nadal działa).
    """
    file = image_attachment(key, data)
    if file is not None:
        try:
            await interaction.response.edit_message(embed=embed, view=view, attachments=[file])
            return
        except TypeError:
            pass
        except discord.HTTPException as exc:
            sys_log.warning("Edycja z podgladem nieudana (%s) — bez pliku.", exc)
    await interaction.response.edit_message(embed=embed, view=view)


async def send_step(channel: discord.abc.Messageable, session: Session, index: int) -> None:
    """Wysyła krok kreatora (albo podsumowanie, gdy kroki się skończyły)."""
    if index >= len(CITIZEN_STEPS):
        await send_summary(channel, session)
        return
    step = CITIZEN_STEPS[index]
    chosen = step["id"] in session.choices
    profile = profile_by_id(session.user_id)
    level = profile.level if profile else 0
    locked = level < min_level_of(step)
    await send_with_image(channel, key=step_image_key(step), data=step_image(step),
                          embed=step_embed(step, index, chosen, level),
                          view=step_view(index, chosen, locked, min_level_of(step), session.user_id))


async def send_summary(channel: discord.abc.Messageable, session: Session) -> None:
    """Wysyła podsumowanie z linkiem do podglądu i wyborem buildu."""
    embed, conflicts = citizen_summary_embed(session)
    link = publish_citizen_preview(session, conflicts)
    if link:
        embed.add_field(name="🖼️ Podgląd kombinacji (live)",
                        value=f"[Otwórz podgląd w przeglądarce]({link})\nZobacz dokładnie, co wchodzi do paczki.")
    else:
        embed.add_field(name="🖼️ Podgląd kombinacji",
                        value="Plik HTML z podglądem dokładnie tej kombinacji dołączymy "
                              "do gotowej paczki (brak publicznego `PUBLIC_URL`).")
    pozycje = len(session.choices) + len(session.collect_skins()) + len(session.uploads)
    rows: List[Any] = [[
        btn("citizen_finish", f"📦 Zbuduj paczkę ({pozycje})", discord.ButtonStyle.success),
        btn("citizen_restart", "🔄 Zacznij od nowa", discord.ButtonStyle.secondary),
        btn("session_close", "🔒 Zamknij", discord.ButtonStyle.danger),
    ], [
        btn("citizen_upload", "📎 Dodaj własny plik", discord.ButtonStyle.secondary),
        btn("citizen_back:0", "◀ Wróć do 1. opcji", discord.ButtonStyle.secondary),
    ], [select("build_pick", "🎮 Docelowy build GTA V / FiveM...",
               [opt(b["name"], b["id"], b["note"], default=(b["id"] == session.build_id))
                for b in GAME_BUILDS])]]
    await channel.send(embed=embed, view=LayoutView(*rows))

# ============================================================================
# 20. WEAPON SKIN STUDIO — widoki
# ============================================================================


def skin_page_of(index: int) -> int:
    """Numer strony galerii (0-based) dla danego indeksu skina."""
    return max(0, index) // SKINS_PER_PAGE


def skin_embed(weapon: Dict[str, Any], skin_index: int, session: Session,
               level: int = 99) -> discord.Embed:
    """Embed skina ze zdjęciem w grze (z informacją o stronie galerii i blokadzie rangi)."""
    skin = weapon["skins"][skin_index]
    chosen = session.weapon_skins.get(weapon["id"]) == skin["id"]
    locked = level < min_level_of(skin)
    if locked:
        status = lock_text(skin)
    else:
        status = "✅ **Ten skin jest w Twojej paczce.**" if chosen else "⬜ *Nie wybrano.*"
    embed = discord.Embed(
        title=f"🔫 {weapon['name']} — {skin['name']}",
        description=(f"**{skin['name']}** — {skin['description']}\n\n" + status
                     + f"\n\n🎮 Build paczki: **{build_by_id(session.build_id)['name']}**"),
        color=C_YELLOW if locked else (C_GREEN if chosen else C_PURPLE),
    )
    embed.set_image(url=embed_image_ref(skin_image_key(weapon, skin)))
    total_pages = page_count(len(weapon["skins"]), SKINS_PER_PAGE)
    embed.set_footer(text=(f"Skin {skin_index + 1}/{len(weapon['skins'])} • strona "
                           f"{skin_page_of(skin_index) + 1}/{total_pages} • "
                           "zdjęcie skina nałożonego na broń"))
    return embed


def skin_view(weapon: Dict[str, Any], skin_index: int, session: Session) -> discord.ui.View:
    """
    Widok galerii skina: przyciski + osobny rząd select + paginacja.

    Discord pozwala na maks. 25 opcji w menu, więc przy większej liczbie skinów
    lista jest dzielona na strony (SKINS_PER_PAGE), a gracz przełącza je
    przyciskami — żaden skin nie jest ucinany.
    """
    skins = weapon["skins"]
    skin_index = max(0, min(skin_index, len(skins) - 1))
    skin = skins[skin_index]
    chosen = session.weapon_skins.get(weapon["id"]) == skin["id"]
    page = skin_page_of(skin_index)
    total_pages = page_count(len(skins), SKINS_PER_PAGE)
    start = page * SKINS_PER_PAGE
    end = min(start + SKINS_PER_PAGE, len(skins))
    profile = profile_by_id(session.user_id)
    level = profile.level if profile else 0
    locked = level < min_level_of(skin)

    buttons = [
        btn(f"ws_prev:{weapon['id']}:{skin_index}", "◀ Wróć", discord.ButtonStyle.secondary),
        (btn(f"ws_locked:{weapon['id']}:{skin_index}", f"🔒 Wymaga poziomu {min_level_of(skin)}",
             discord.ButtonStyle.secondary) if locked else
         btn(f"ws_choose:{weapon['id']}:{skin_index}",
             "Wybrano ✓ (odznacz)" if chosen else "Wybierz ten skin",
             discord.ButtonStyle.success if chosen else discord.ButtonStyle.primary, "✅")),
        btn(f"ws_next:{weapon['id']}:{skin_index}", "Dalej ▶", discord.ButtonStyle.secondary),
    ]
    picker = select(f"ws_skin_select:{weapon['id']}",
                    f"Wybierz skin z listy (strona {page + 1}/{total_pages})...",
                    [opt(f"{'🔒 ' if level < min_level_of(skins[i]) else ''}{i + 1}. {skins[i]['name']}",
                         str(i), skins[i]["description"], default=(i == skin_index))
                     for i in range(start, end)])
    rows: List[Any] = [buttons, [picker]]
    page_buttons = []
    if page > 0:
        page_buttons.append(btn(f"ws_page:{weapon['id']}:{page - 1}",
                                f"« Strona {page}/{total_pages}", discord.ButtonStyle.secondary))
    if page < total_pages - 1:
        page_buttons.append(btn(f"ws_page:{weapon['id']}:{page + 1}",
                                f"Strona {page + 2}/{total_pages} »", discord.ButtonStyle.secondary))
    if page_buttons:
        rows.append(page_buttons)
    rows.extend(skin_nav_row())
    # Discord limit: 5 rzędów (0-4) — web link doklejamy tylko gdy jest wolny rząd.
    if len(rows) < 5:
        rows.append([web_link_button(session.user_id, "skins")])
    return LayoutView(*rows)


def skin_nav_row() -> List[List[discord.ui.Button]]:
    """Przyciski nawigacji studia skinów (dwa rzędy — Discord: maks. 5 w rzędzie)."""
    return [
        [
            btn("ws_back_to_weapons", "← Inna broń", discord.ButtonStyle.secondary, "🔫"),
            btn("ws_search_start", "🔎 Szukaj (.rpf)", discord.ButtonStyle.secondary),
            btn("ws_upload", "📎 Własny skin", discord.ButtonStyle.secondary),
        ],
        [
            btn("ws_summary", "Podsumowanie", discord.ButtonStyle.secondary, "📋"),
            btn("ws_finish", "Zakończ i zbuduj paczkę", discord.ButtonStyle.success, "📦"),
            btn("session_close", "Zamknij", discord.ButtonStyle.danger, "🔒"),
        ],
    ]


async def send_category_menu(channel: discord.abc.Messageable, session: Session) -> None:
    """Menu kategorii broni."""
    embed = discord.Embed(
        title="🔫 Weapon Skin Studio — wybierz kategorię",
        description="\n".join(
            ["Dostępne kategorie broni:"]
            + [f"{c['name']} — {len(c['weapons'])} broni" for c in WEAPON_CATEGORIES]
            + ["", "Po wyborze broni zobaczysz galerię skinów ze zdjęciami w grze.",
               "Nie widzisz swojego skina? Użyj **🔎 Szukaj skinów (.rpf)** w galerii."]
        ), color=C_PURPLE)
    view = LayoutView([select("ws_category", "Kategoria broni...",
                              [opt(c["name"], c["id"], f"{len(c['weapons'])} broni w kategorii")
                               for c in WEAPON_CATEGORIES])])
    await channel.send(embed=embed, view=view)


async def send_weapon_list(channel: discord.abc.Messageable, session: Session, category_id: str) -> None:
    """Lista broni w kategorii."""
    category = next((c for c in WEAPON_CATEGORIES if c["id"] == category_id), None)
    if not category:
        return
    embed = discord.Embed(title=f"{category['name']} — wybierz broń", color=C_PURPLE)
    view = LayoutView([select(f"ws_weapon:{category_id}", "Wybierz broń...",
                              [opt(w["name"], w["id"], f"{len(w['skins'])} skin(ów) dostępnych")
                               for w in category["weapons"]])])
    await channel.send(embed=embed, view=view)


async def send_skin_gallery(channel: discord.abc.Messageable, session: Session,
                            weapon: Dict[str, Any]) -> None:
    """Galeria skinów wybranej broni."""
    index = 0
    chosen_id = session.weapon_skins.get(weapon["id"])
    if chosen_id:
        for i, skin in enumerate(weapon["skins"]):
            if skin["id"] == chosen_id:
                index = i
                break
    skin = weapon["skins"][index]
    await send_with_image(channel, key=skin_image_key(weapon, skin), data=skin_image(weapon, skin),
                          embed=skin_embed(weapon, index, session),
                          view=skin_view(weapon, index, session))


async def show_skin(interaction: discord.Interaction, weapon: Dict[str, Any], index: int,
                    session: Session, level: Optional[int] = None) -> None:
    """Odświeża podgląd skina w tej samej wiadomości (razem z wygenerowaną grafiką)."""
    skins = weapon["skins"]
    index = max(0, min(index, len(skins) - 1))
    skin = skins[index]
    if level is None:
        profile = profile_by_id(session.user_id)
        level = profile.level if profile else 0
    await edit_with_image(interaction, key=skin_image_key(weapon, skin),
                          data=skin_image(weapon, skin),
                          embed=skin_embed(weapon, index, session, level),
                          view=skin_view(weapon, index, session))


async def send_search_prompt(channel: discord.abc.Messageable) -> None:
    """Zachęta do wpisania frazy (tryb wyszukiwania)."""
    embed = discord.Embed(
        title="🔎 Wyszukiwarka skinów (.rpf)",
        description=("Wpisz frazę, np.:\n`pistol redline`, `ak47 wood`, `chrome heavy`\n\n"
                     "Bot przeszuka zewnętrzny indeks skinów i pokaże **tylko pliki .rpf** "
                     "(inne formaty są automatycznie odrzucane).\n\n"
                     "**Wpisz teraz** frazę jako zwykłą wiadomość na tym kanale."),
        color=C_PURPLE)
    await channel.send(embed=embed, view=LayoutView(
        [btn("ws_search_stop", "Zakończ wyszukiwanie", discord.ButtonStyle.secondary, "✖️")]))


async def process_search_query(channel: discord.abc.Messageable, session: Session, query: str) -> None:
    """Wysyła wyniki wyszukiwania jako select menu."""
    result = await search_skins(query)
    if result.get("error"):
        await channel.send(embed=discord.Embed(title="❌ Wyszukiwarka",
                                              description=result["error"], color=C_RED))
        return
    results = result["results"]
    if not results:
        await channel.send(embed=discord.Embed(
            title="🔍 Brak wyników",
            description=f"Nie znaleziono skinów **.rpf** dla frazy: `{query}`", color=C_YELLOW))
        return

    session.search_results = results
    session.search_query = query
    await send_search_page(channel, session, page=0)

    # Creator Economy: XP za korzystanie z wyszukiwarki (raz na frazę w sesji)
    profile = profile_by_id(session.user_id)
    if profile is not None:
        query_key = query.strip().lower()
        if query_key not in session.searches_awarded:
            session.searches_awarded.append(query_key)
            del session.searches_awarded[:-20]
            profile.searches += 1
            if profile.badge("odkrywca"):
                await channel.send(f"🔎 Nowa odznaka: {BADGES['odkrywca']}")
            await award_xp(profile, "search", channel, reason="wyszukiwarka .rpf")


async def send_search_page(channel: discord.abc.Messageable, session: Session, page: int = 0) -> None:
    """
    Wyniki wyszukiwania .rpf z paginacją.

    Menu Discorda ma limit 25 opcji, dlatego wyniki dzielone są na strony
    (SEARCH_RESULTS_PER_PAGE), a przyciski przełączają strony bez powtarzania
    zapytania do indeksu.
    """
    results = session.search_results
    if not results:
        return
    total_pages = page_count(len(results), SEARCH_RESULTS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    session.search_page = page
    start = page * SEARCH_RESULTS_PER_PAGE
    end = min(start + SEARCH_RESULTS_PER_PAGE, len(results))

    description = "\n\n".join(
        f"**{i + 1}. {r.get('name', 'Skin')}** — {r.get('description') or 'bez opisu'}\n"
        f"Autor: {r.get('author') or '—'} • `{file_name_from_url(r.get('fileUrl', ''))}`"
        for i, r in enumerate(results[start:end], start=start)
    )
    embed = discord.Embed(title=f"🔎 Wyniki dla: {session.search_query} ({len(results)})",
                          description=description, color=C_GREEN)
    embed.set_footer(text=(f"Strona {page + 1}/{total_pages} • wyniki {start + 1}-{end} "
                           f"z {len(results)} • wybierz z menu poniżej"))
    rows: List[Any] = [[select("ws_search_pick", "Wybierz skin do paczki (.rpf)...",
                              [opt(r.get("name", "Skin"), str(i),
                                   r.get("description") or "bez opisu")
                               for i, r in enumerate(results[start:end], start=start)])]]
    page_buttons = []
    if page > 0:
        page_buttons.append(btn(f"ws_search_page:{page - 1}",
                                f"« Poprzednie ({page}/{total_pages})", discord.ButtonStyle.secondary))
    if page < total_pages - 1:
        page_buttons.append(btn(f"ws_search_page:{page + 1}",
                                f"Następne ({page + 2}/{total_pages}) »", discord.ButtonStyle.secondary))
    if page_buttons:
        rows.append(page_buttons)
    await channel.send(embed=embed, view=LayoutView(*rows))


async def send_skins_summary(channel: discord.abc.Messageable, session: Session) -> None:
    """Podsumowanie paczki skinów + własne pliki gracza + podgląd kombinacji."""
    skins = session.collect_skins()
    uploads = session.collect_uploads()
    build = build_by_id(session.build_id)
    lines = [f"✅ **{s['name']}** — {s.get('description') or ''}" for s in skins]
    if uploads:
        lines += ["", f"📎 **Własne pliki ({len(uploads)}):**"]
        lines += [f"• `{u['name']}` ({u.get('size', 0) / 1024:.0f} KB) → `{u['target']}`"
                  for u in uploads[:15]]
    if not lines:
        lines = ["*Nie wybrano żadnego skina.*",
                 "Wybierz skin w galerii, wyszukaj plik .rpf (🔎) albo wrzuć swój przyciskiem 📎 Własny skin."]
    embed = discord.Embed(title="📋 Podsumowanie paczki skinów",
                          description="\n".join(lines), color=C_YELLOW)
    embed.add_field(name="🎮 Docelowy build GTA V", value=build["name"])
    embed.add_field(name="📦 Pozycji w paczce",
                    value=f"**{len(skins) + len(uploads)}** (skiny: {len(skins)}, własne: {len(uploads)})")
    link = publish_skins_preview(session, list(skins) + uploads)
    if link:
        embed.add_field(name="🖼️ Podgląd kombinacji (live)",
                        value=f"[Otwórz podgląd w przeglądarce]({link})")
    else:
        embed.add_field(name="🖼️ Podgląd kombinacji",
                        value="Plik HTML z podglądem dołączymy do gotowej paczki "
                              "(brak publicznego `PUBLIC_URL`).")
    embed.set_footer(text="Kliknij „Zakończ i zbuduj paczkę”, aby wygenerować ZIP.")
    await channel.send(embed=embed, view=LayoutView(*skin_nav_row()))

# ============================================================================
# 21. TICKETY, SETUP SERWERA, PANEL /system
# ============================================================================

setup_log = log("Setup")
sys_log = log("System")


def find_channel(guild: discord.Guild, category_name: str, channel_name: str) -> Optional[discord.TextChannel]:
    """Znajduje kanał tekstowy w danej kategorii."""
    category = discord.utils.get(guild.categories, name=category_name)
    for channel in guild.text_channels:
        if channel.name == channel_name and (category is None or channel.category_id == category.id):
            return channel
    return None


async def ensure_category(guild: discord.Guild, name: str) -> discord.CategoryChannel:
    """Tworzy kategorię (z poprawnym typem!)."""
    category = discord.utils.get(guild.categories, name=name)
    if not category:
        category = await guild.create_category(name=name, reason="Auto-setup FiveM Mod Foundry")
    return category


async def ensure_text_channel(guild: discord.Guild, category: discord.CategoryChannel,
                             name: str, topic: str) -> discord.TextChannel:
    """Tworzy kanał tekstowy w kategorii (jeśli nie istnieje)."""
    channel = find_channel(guild, category.name, name)
    if not channel:
        channel = await guild.create_text_channel(name=name, category=category, topic=topic,
                                                  reason="Auto-setup FiveM Mod Foundry")
    return channel


async def ensure_role(guild: discord.Guild, name: str, color: int) -> discord.Role:
    """Tworzy rolę, jeśli nie istnieje."""
    role = discord.utils.get(guild.roles, name=name)
    if not role:
        role = await guild.create_role(name=name, colour=discord.Colour(color),
                                       reason="Auto-setup FiveM Mod Foundry")
    return role


async def panel_exists(channel: discord.TextChannel, custom_id: Optional[str]) -> bool:
    """
    Czy panel już wisi na kanale? (anty-duplikaty po restarcie)
    custom_id=None oznacza "dowolna wiadomość bota" (panele bez przycisków).
    """
    try:
        async for message in channel.history(limit=30):
            if message.author.id != channel.guild.me.id:
                continue
            if custom_id is None:
                return True
            for row in message.components:
                for child in row.children:
                    if getattr(child, "custom_id", None) == custom_id:
                        return True
    except discord.HTTPException:
        return False
    return False


async def ensure_panel(channel: discord.TextChannel, custom_id: str, embed: discord.Embed,
                       view: discord.ui.View) -> None:
    """Wysyła panel tylko jeśli jeszcze go nie ma."""
    if not await panel_exists(channel, custom_id):
        await channel.send(embed=embed, view=view)


async def setup_guild(guild: discord.Guild) -> None:
    """Buduje pełną strukturę serwera: role, kategorie, kanały i panele."""
    setup_log.info("Buduję strukturę serwera: %s", guild.name)

    await ensure_role(guild, ROLE_MEMBER, C_BLUE)
    await ensure_role(guild, ROLE_CREATOR, C_PURPLE)
    await ensure_role(guild, ROLE_BUILDING, C_GREEN)

    # --- 📢 START ---
    info_cat = await ensure_category(guild, CAT_INFO)
    welcome = await ensure_text_channel(guild, info_cat, CH_WELCOME, "Zaznacz się i korzystaj z kreatorów.")
    rules = await ensure_text_channel(guild, info_cat, CH_RULES, "Regulamin — obowiązkowo.")

    await ensure_panel(
        welcome, "take_role",
        discord.Embed(
            title=f"👋 Witaj na {guild.name}!",
            description=("Twoje centrum modyfikacji klienckich do FiveM:\n\n"
                         "🏭 **CITIZEN FOUNDRY** — buduj paczkę (niebo, woda, cienie, potato...)\n"
                         "🔫 **WEAPON SKIN STUDIO** — personalizuj wygląd broni (.ytd/.ydr)\n"
                         "📦 **MOD FEED** — najnowsze mody klienckie z YouTube na żywo\n\n"
                         "Kliknij poniżej, aby zaznaczyć się i korzystać z pełni serwera."),
            color=C_BLUE),
        LayoutView([btn("take_role", "Zaznacz się (pobierz rolę)", discord.ButtonStyle.success, "✅")]),
    )

    if not await panel_exists(rules, None):
        await rules.send(embed=discord.Embed(
            title="📜 Regulamin serwera",
            description=("1. **Szanuj innych** — zero toksyczności i hejtu.\n"
                         "2. **Bez spamu** — nie flooduj kanałów i ticketów.\n"
                         "3. **Mody na własną odpowiedzialność** — sprawdzaj regulamin serwera FiveM.\n"
                         "4. **Bez wirusów/scamów** — podejrzane linki = ban.\n"
                         "5. **Pomagaj sobie** — kanał #pomoc do dyspozycji społeczności.\n"
                         "6. **Admin ma rację** — decyzje administracji ostateczne."),
            color=C_YELLOW).set_footer(text="Wejście na serwer = akceptacja regulaminu."))

    # --- 🏭 CITIZEN FOUNDRY ---
    citizen_cat = await ensure_category(guild, CAT_CITIZEN)
    citizen_ch = await ensure_text_channel(guild, citizen_cat, CH_CITIZEN, "Panel kreatora citizena.")
    await ensure_text_channel(guild, citizen_cat, CH_DOWNLOADS, "Gotowe paczki ZIP użytkowników.")

    await ensure_panel(
        citizen_ch, "create_citizen",
        discord.Embed(
            title="🏭 Kreator Citizenów — FiveM",
            description=(f"Kliknij **„Zacznij tworzyć citizena'**, aby uruchomić kreatora.\n\n"
                         f"Prywatny kanał + **{len(CITIZEN_STEPS)} opcji** w 6 grupach:\n"
                         "  1️⃣ Niebo / Timecycle\n"
                         "  2️⃣ Woda i kolory\n"
                         "  3️⃣ Cienie i postfx\n"
                         "  4️⃣ Pojazdy (propsy, szyby, dym, ogień)\n"
                         "  5️⃣ POTATO (mapa low-poly)\n"
                         "  6️⃣ Kombat (dźwięki, krew, hitmarkery)\n\n"
                         "Na końcu gotowa paczka `.zip` z linkiem ważnym 60 minut + podgląd kombinacji."),
            color=C_BLUE),
        LayoutView([btn("create_citizen", "Zacznij tworzyć citizena", discord.ButtonStyle.primary, "🛠️")]),
    )

    # --- 🔫 WEAPON SKIN STUDIO ---
    skins_cat = await ensure_category(guild, CAT_SKINS)
    skins_ch = await ensure_text_channel(guild, skins_cat, CH_SKINS, "Kreator skinów broni.")

    await ensure_panel(
        skins_ch, "create_weapon_skins",
        discord.Embed(
            title="🔫 Weapon Skin Studio",
            description=("Kliknij **„Stwórz skiny broni'**, aby uruchomić studio.\n\n"
                         "Kategorie: Pistolety / SMG / Karabiny / Strzelby.\n"
                         "Galeria skinów ze zdjęciami **nałożonymi na broń w grze**.\n"
                         "Wyszukiwarka zewnętrzna przyjmuje wyłącznie pliki `.rpf`.\n"
                         "Gotowa paczka `.zip` do folderu `mods/x64e.rpf/...`."),
            color=C_PURPLE),
        LayoutView([btn("create_weapon_skins", "Stwórz skiny broni", discord.ButtonStyle.primary, "🔫")]),
    )

    # --- 📦 MOD FEED (kanały tematyczne live feedu) ---
    mods_cat = await ensure_category(guild, CAT_MODS)
    mods_ch = await ensure_text_channel(guild, mods_cat, CH_MODS_LIVE,
                                       "🔥 Archiwum feedu — reszta modów klienckich z YouTube.")
    feed_mods = await ensure_text_channel(guild, mods_cat, CH_FEED_MODS,
                                          FEED_CHANNEL_TOPICS[CH_FEED_MODS])
    feed_skins = await ensure_text_channel(guild, mods_cat, CH_FEED_SKINS,
                                          FEED_CHANNEL_TOPICS[CH_FEED_SKINS])
    feed_pc = await ensure_text_channel(guild, mods_cat, CH_FEED_PC,
                                       FEED_CHANNEL_TOPICS[CH_FEED_PC])
    await ensure_text_channel(guild, mods_cat, CH_HELP, "Masz problem z modem? Pisz tutaj.")

    if not await panel_exists(mods_ch, None):
        await mods_ch.send(embed=discord.Embed(
            title="📡 Live Mod Feed — jak to działa",
            description=(f"Bot **co {YT_SCAN_MINUTES} minut** skanuje YouTube i wrzuca filmy "
                         f"z ostatnich **{YT_MAX_AGE_DAYS} dni**:\n"
                         f"• {feed_skins.mention} — skin packi i tekstury **.rpf** do broni\n"
                         f"• {feed_mods.mention} — mody OPTI / FPS / potato / first person / mapy / auta\n"
                         f"• {feed_pc.mention} — **optymalizacja komputera**: Windows, GPU, stutter, ping\n\n"
                         "Kategorię bot rozpoznaje po tytule filmu; niesklasyfikowane trafiają tutaj "
                         "(na archiwum).\n\n"
                         "**Filtry:** odrzucamy skrypty serwerowe (ESX/QBCore/.lua), cheaty i clickbaity.\n\n"
                         "⚠️ Mody klienckie wrzucasz do folderu `mods` w `FiveM.app` i działają na "
                         "serwerach, które ich nie blokują."),
            color=C_ORANGE))

    # --- 🔍 KANAŁ LOGÓW (tylko admini) ---
    if not discord.utils.get(guild.text_channels, name=CH_SYSLOG):
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        await guild.create_text_channel(
            name=CH_SYSLOG, category=info_cat, topic="🔍 Logi /system i zgłoszenia bezpieczeństwa.",
            overwrites=overwrites, reason="Auto-setup FiveM Mod Foundry")

    # --- TWOJE PACZKI (kategoria ticketów) ---
    await ensure_category(guild, CAT_TICKETS)
    setup_log.info("Struktura %s gotowa.", guild.name)


async def get_admin_log_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    """Kanał logów administracyjnych (tworzy, jeśli brak)."""
    channel = discord.utils.get(guild.text_channels, name=CH_SYSLOG)
    if channel:
        return channel
    info_cat = discord.utils.get(guild.categories, name=CAT_INFO)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
    }
    return await guild.create_text_channel(
        name=CH_SYSLOG, category=info_cat, topic="🔍 Logi /system i zgłoszenia bezpieczeństwa.",
        overwrites=overwrites, reason="Auto-setup FiveM Mod Foundry")


async def system_log(guild: discord.Guild, action: str, executor: discord.abc.User,
                     details: str = "") -> None:
    """Zapisuje wpis audytowy na kanale logów."""
    try:
        channel = await get_admin_log_channel(guild)
        embed = discord.Embed(
            title="🔍 Log systemowy",
            description=(f"**Akcja:** {action}\n"
                         f"**Wykonał:** {executor.mention} ({executor})\n"
                         f"**Data:** <t:{int(time.time())}:F>"
                         + (f"\n\n**Szczegóły:**\n{details}" if details else "")),
            color=C_YELLOW, timestamp=datetime.now(timezone.utc))
        await channel.send(embed=embed)
    except Exception as exc:  # noqa: BLE001
        sys_log.error("Nie zapisano loga systemowego: %s", exc)


# ============================================================================
# 21.4.1. OSTATNIA OPERACJA /SYSTEM — raport do odzyskania jednym klikiem
#   Długie akcje /system (design, reset, Ghost Copy) mogą zakończyć się już po
#   zniknięciu kanału, z którego je uruchomiono (Discord: 400/10003 Unknown
#   Channel) — wtedy admin nie widzi wyniku. Dlatego każdą operację zapisujemy
#   w data/system_last_op.json: przycisk 🔁 pokaże raport, a ↻ Ponów powtórzy
#   akcję bez szukania po logach.
# ============================================================================

sys_op_log = log("SysOps")
SYS_OP_FILE = DATA_DIR / "system_last_op.json"
LAST_SYS_OPS: Dict[str, Dict[str, Any]] = {}

SYS_OP_LABELS = {
    "build_design": "🎨 Zbuduj estetyczny design",
    "reset": "⚠️ Reset serwera",
    "apply_template": "👻 Zastosuj szablon",
    "clone_guild": "👻 Klon z innego serwera",
}


def sys_ops_load() -> None:
    """Wczytuje raporty operacji /system (odporne na brak i uszkodzony plik)."""
    LAST_SYS_OPS.clear()
    try:
        raw = json.loads(SYS_OP_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(raw, dict):
        for guild_id, record in raw.items():
            if isinstance(record, dict) and record.get("action"):
                LAST_SYS_OPS[str(guild_id)] = record


def sys_ops_save() -> None:
    """Zapisuje raporty na dysk — błąd zapisu tylko logujemy."""
    try:
        SYS_OP_FILE.write_text(json.dumps(LAST_SYS_OPS, indent=2, ensure_ascii=False),
                               encoding="utf-8")
    except OSError as exc:
        sys_op_log.warning("Nie zapisano historii operacji /system: %s", exc)


def sys_op_record(guild_id: Optional[int], action: str, *, ok: bool, headline: str,
                  detail: str = "", user_id: Optional[int] = None,
                  extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Zapisuje wynik ostatniej operacji /system na danym serwerze."""
    record = {
        "action": action,
        "label": SYS_OP_LABELS.get(action, action),
        "ok": bool(ok),
        "headline": str(headline)[:300],
        "detail": str(detail)[:4000],
        "user_id": int(user_id) if user_id else None,
        "at": int(time.time()),
        "extra": dict(extra or {}),
    }
    if guild_id is not None:
        LAST_SYS_OPS[str(guild_id)] = record
        sys_ops_save()
    sys_op_log.info("[%s] %s (%s)", action, record["headline"], "ok" if ok else "błąd")
    return record


def sys_op_last(guild_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """Raport ostatniej operacji /system na serwerze (albo None)."""
    if guild_id is None:
        return None
    return LAST_SYS_OPS.get(str(guild_id))


def sys_op_embed(record: Dict[str, Any]) -> discord.Embed:
    """Embed z raportem operacji — do pokazania po fakcie (np. gdy kanał zniknął)."""
    when = int(record.get("at") or 0)
    lines = [line for line in str(record.get("detail") or "").splitlines() if line.strip()]
    embed = discord.Embed(
        title=f"{'✅' if record.get('ok') else '❌'} {record.get('label') or 'Operacja /system'}",
        description=(f"**Status:** {'zakończona' if record.get('ok') else 'przerwana'}\n"
                     f"**Wynik:** {record.get('headline') or '—'}\n"
                     f"**Kiedy:** <t:{when}:F> (<t:{when}:R>)"
                     + (f"\n**Wykonał:** <@{record['user_id']}>" if record.get("user_id") else "")),
        color=C_GREEN if record.get("ok") else C_RED,
        timestamp=datetime.now(timezone.utc))
    if lines:
        text = "\n".join(lines[:20])
        if len(lines) > 20:
            text += f"\n... i {len(lines) - 20} więcej"
        embed.add_field(name="Szczegóły", value=f"```\n{text[:1000]}\n```", inline=False)
    embed.set_footer(text=(f"Kanał zniknął? Raport masz tutaj i w #{CH_SYSLOG} — "
                           "przycisk ↻ Ponów powtórzy operację."))
    return embed


def sys_op_view(record: Optional[Dict[str, Any]] = None) -> discord.ui.View:
    """Przyciski raportu: ponowienie operacji + odświeżenie raportu."""
    record = record or {}
    buttons = [btn("sys_last_op", "Odśwież raport", discord.ButtonStyle.secondary, "🔄")]
    if record.get("action"):
        buttons.insert(0, btn("sys_repeat_last", "Ponów operację",
                              discord.ButtonStyle.primary, "↻"))
    return LayoutView(buttons)


sys_ops_load()


def is_authorized(interaction: discord.Interaction) -> bool:
    """Dostęp do /system: właściciel serwera albo Administrator."""
    if not interaction.guild:
        return False
    if interaction.user.id == interaction.guild.owner_id:
        return True
    member = interaction.user
    return bool(getattr(member, "guild_permissions", None)
                and member.guild_permissions.administrator)


DESIGN_LAYOUT: List[Tuple[str, List[Tuple[str, str]]]] = [
    ("🌐・OGÓLNE", [
        ("🌐・ogólny", "Rozmowy o wszystkim i o niczym."),
        ("💬・chat", "Luźna dyskusja społeczności."),
        ("📢・ogłoszenia", "Ważne komunikaty administracji."),
        ("🖼️・media", "Screenshoty, klipy, memy."),
    ]),
    ("🎨・KREATORY", [
        ("🎨・kreator-citizen", "Panel Citizen Foundry — buduj paczkę kliencką."),
        ("🔫・skiny-broni", "Weapon Skin Studio — personalizacja broni."),
        ("📥・pobieranie", "Gotowe paczki ZIP użytkowników."),
    ]),
    ("⚙️・OPTYMALIZACJA", [
        ("⚙️・optymalizacja", "Mody FPS, potato graphics, tuning."),
        ("📡・nowe-mody", "Live feed z YouTube — najnowsze mody klienckie."),
        ("❓・pomoc", "Masz problem z modem? Pisz tutaj."),
    ]),
    ("🔍・ADMINISTRACJA", [
        ("📜・regulamin", "Zasady serwera."),
        ("🔍・logi-system", "Audyt komend /system."),
    ]),
]

ADMIN_CATEGORY = "🔍・ADMINISTRACJA"


async def build_aesthetic_design(guild: discord.Guild, executor: discord.abc.User) -> List[str]:
    """Przebudowuje serwer na estetyczny układ (emotki, kategorie, uprawnienia)."""
    results: List[str] = []

    if not discord.utils.get(guild.roles, name=ROLE_MEMBER):
        await guild.create_role(name=ROLE_MEMBER, colour=discord.Colour(C_BLUE),
                                reason="Design: rola bazowa")
        results.append(f"+ rola {ROLE_MEMBER}")

    for category_name, channels in DESIGN_LAYOUT:
        category = discord.utils.get(guild.categories, name=category_name)
        if not category:
            category = await guild.create_category(name=category_name,
                                                   reason="Design: kategoria")
            results.append(f"+ kategoria {category_name}")
        for channel_name, topic in channels:
            if find_channel(guild, category_name, channel_name):
                continue
            channel = await guild.create_text_channel(name=channel_name, category=category,
                                                      topic=topic, reason="Design: kanał")
            results.append(f"+ kanał {channel_name}")
            # Kanały administracyjne chowamy przed @everyone
            if category_name == ADMIN_CATEGORY:
                try:
                    await channel.set_permissions(guild.default_role, view_channel=False,
                                                  send_messages=False)
                except discord.HTTPException as exc:
                    sys_log.warning("Uprawnienia %s: %s", channel_name, exc)

    await system_log(guild, "Zbuduj estetyczny design", executor, "\n".join(results))
    return results


async def reset_server(guild: discord.Guild, executor: discord.abc.User,
                       keep_channel_id: Optional[int] = None) -> List[str]:
    """
    Usuwa strukturę stworzoną przez bota (kategorie, kanały emotkowe, role).

    `keep_channel_id` to kanał, z którego uruchomiono reset — nie kasujemy go,
    żeby bot miał gdzie wysłać podsumowanie (inaczej Discord zwraca
    400/10003 Unknown Channel i admin nie widzi wyniku operacji).
    """
    results: List[str] = []
    categories_to_remove = [
        CAT_INFO, CAT_CITIZEN, CAT_TICKETS, CAT_SKINS, CAT_MODS,
        "🌐・OGÓLNE", "🎨・KREATORY", "⚙️・OPTYMALIZACJA", "🔍・ADMINISTRACJA",
    ]
    for name in categories_to_remove:
        category = discord.utils.get(guild.categories, name=name)
        if not category:
            continue
        for channel in list(category.channels):
            if keep_channel_id and channel.id == keep_channel_id:
                results.append(f"= zachowano kanał {channel.name} (tu kliknięto reset)")
                continue
            try:
                await channel.delete(reason="Reset serwera (/system)")
            except discord.HTTPException:
                pass
        try:
            await category.delete(reason="Reset serwera (/system)")
            results.append(f"- kategoria {name}")
        except discord.HTTPException:
            pass

    emoji_pattern = re.compile(r"^[^\w\s]+・")
    for channel in list(guild.text_channels):
        if keep_channel_id and channel.id == keep_channel_id:
            continue
        if emoji_pattern.match(channel.name):
            try:
                await channel.delete(reason="Reset serwera (/system)")
                results.append(f"- kanał {channel.name}")
            except discord.HTTPException:
                pass

    for role_name in (ROLE_MEMBER, ROLE_CREATOR, ROLE_BUILDING):
        role = discord.utils.get(guild.roles, name=role_name)
        if role and not role.is_default() and role < guild.me.top_role:
            try:
                await role.delete(reason="Reset serwera (/system)")
                results.append(f"- rola {role_name}")
            except discord.HTTPException:
                pass

    await system_log(guild, "RESET SERWERA", executor, "\n".join(results))
    return results


# ============================================================================
# 21.5. GHOST COPY — klonowanie struktury serwera (jeden klik)
#    Eksport całej struktury (role + uprawnienia, kategorie, kanały, nadpisania)
#    do szablonu JSON i odtworzenie jej na dowolnym serwerze.
# ============================================================================

ghost_log = log("GhostCopy")
TEMPLATES_DIR = DATA_DIR / "templates"
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
COPY_CONFIRM_WORD = "KOPIUJ"


def _overwrites_to_json(overwrites: Any) -> Dict[str, Dict[str, int]]:
    """Zapisuje nadpisania uprawnień kluczem = nazwa roli (ID się nie przenoszą)."""
    out: Dict[str, Dict[str, int]] = {}
    for target, overwrite in (overwrites or {}).items():
        is_default = bool(getattr(target, "is_default", lambda: False)())
        key = "@everyone" if is_default else f"@{getattr(target, 'name', '?')}"
        try:
            allow, deny = overwrite.pair()
        except Exception:  # noqa: BLE001
            continue
        out[key] = {"allow": int(allow.value), "deny": int(deny.value)}
    return out


def export_guild_layout(guild: discord.Guild) -> Dict[str, Any]:
    """
    Zrzut struktury serwera do JSON: role (z uprawnieniami i kolorem),
    kategorie, kanały (temat, nsfw, slowmode) i nadpisania uprawnień.
    """
    layout: Dict[str, Any] = {
        "source": {"id": guild.id, "name": guild.name,
                   "exported_at": datetime.now(timezone.utc).isoformat()},
        "roles": [], "categories": [], "channels": [],
    }
    for role in sorted(guild.roles, key=lambda r: r.position):
        if role.is_default() or role.managed:
            continue
        layout["roles"].append({
            "name": role.name, "color": role.color.value, "hoist": role.hoist,
            "mentionable": role.mentionable, "position": role.position,
            "permissions": role.permissions.value,
        })
    for category in guild.categories:
        layout["categories"].append({
            "name": category.name, "position": category.position,
            "overwrites": _overwrites_to_json(category.overwrites),
        })
    for channel in guild.channels:
        if isinstance(channel, discord.CategoryChannel):
            continue
        entry: Dict[str, Any] = {
            "name": channel.name,
            "type": "voice" if isinstance(channel, discord.VoiceChannel) else "text",
            "category": channel.category.name if channel.category else None,
            "position": channel.position,
            "overwrites": _overwrites_to_json(channel.overwrites),
        }
        if isinstance(channel, discord.TextChannel):
            entry.update({"topic": channel.topic, "nsfw": channel.nsfw,
                          "slowmode": channel.slowmode_delay})
        layout["channels"].append(entry)
    return layout


def template_path(name: str) -> Path:
    """Bezpieczna ścieżka szablonu (bez wychodzenia z katalogu)."""
    safe = re.sub(r"[^a-z0-9_-]", "-", (name or "").strip().lower())[:40] or "szablon"
    return TEMPLATES_DIR / f"{safe}.json"


def template_save(name: str, layout: Dict[str, Any]) -> Path:
    """Zapisuje szablon struktury serwera."""
    path = template_path(name)
    path.write_text(json.dumps(layout, ensure_ascii=False, indent=1), encoding="utf-8")
    ghost_log.info("Zapisano szablon %s (%s rol, %s kanalow)", path.name,
                   len(layout.get("roles") or []), len(layout.get("channels") or []))
    return path


def template_list() -> List[str]:
    """Nazwy zapisanych szablonów."""
    return sorted(path.stem for path in TEMPLATES_DIR.glob("*.json"))


def template_load(name: str) -> Optional[Dict[str, Any]]:
    """Wczytuje szablon (None, gdy brak lub uszkodzony)."""
    path = template_path(name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError) as exc:
        ghost_log.warning("Nie wczytano szablonu %s: %s", name, exc)
        return None


def _permissions_from_json(overwrites: Any,
                           role_map: Dict[str, discord.Role]) -> Dict[Any, discord.PermissionOverwrite]:
    """Buduje nadpisania uprawnień dla nowego serwera (mapowanie po nazwach ról)."""
    mapping: Dict[Any, discord.PermissionOverwrite] = {}
    for key, data in (overwrites or {}).items():
        target = role_map.get(key)
        if target is None:
            continue
        try:
            allow = discord.Permissions(int((data or {}).get("allow", 0)))
            deny = discord.Permissions(int((data or {}).get("deny", 0)))
            mapping[target] = discord.PermissionOverwrite.from_pair(allow, deny)
        except Exception:  # noqa: BLE001
            continue
    return mapping


async def apply_guild_layout(guild: discord.Guild, layout: Dict[str, Any], *,
                             create_roles: bool = True,
                             reason: str = "Ghost Copy") -> Dict[str, Any]:
    """
    Odtwarza strukturę z szablonu: role -> kategorie -> kanały (z nadpisaniami).
    Nic nie usuwa — istniejące elementy są pomijane, brakujące tworzone.
    """
    report: Dict[str, Any] = {"roles": [], "categories": [], "channels": [], "errors": []}
    role_map: Dict[str, discord.Role] = {"@everyone": guild.default_role}

    if create_roles:
        for entry in sorted(layout.get("roles") or [], key=lambda r: r.get("position", 0)):
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            existing = discord.utils.get(guild.roles, name=name)
            if existing:
                role_map[f"@{name}"] = existing
                continue
            try:
                role = await guild.create_role(
                    name=name, colour=discord.Colour(int(entry.get("color", 0))),
                    hoist=bool(entry.get("hoist")), mentionable=bool(entry.get("mentionable")),
                    permissions=discord.Permissions(int(entry.get("permissions", 0))), reason=reason)
                role_map[f"@{name}"] = role
                report["roles"].append(name)
            except discord.HTTPException as exc:
                report["errors"].append(f"rola {name}: {exc}")
    else:
        for role in guild.roles:
            role_map[f"@{role.name}"] = role

    category_map: Dict[str, discord.CategoryChannel] = {}
    for entry in sorted(layout.get("categories") or [], key=lambda c: c.get("position", 0)):
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        existing_category = discord.utils.get(guild.categories, name=name)
        if existing_category:
            category_map[name] = existing_category
            continue
        try:
            category = await guild.create_category(
                name=name, overwrites=_permissions_from_json(entry.get("overwrites"), role_map),
                reason=reason)
            category_map[name] = category
            report["categories"].append(name)
        except discord.HTTPException as exc:
            report["errors"].append(f"kategoria {name}: {exc}")

    existing_names = {(channel.name, channel.category.name if channel.category else None)
                      for channel in guild.channels}
    for entry in layout.get("channels") or []:
        name = str(entry.get("name") or "").strip()
        category_name = entry.get("category")
        if not name or (name, category_name) in existing_names:
            continue
        try:
            overwrites = _permissions_from_json(entry.get("overwrites"), role_map)
            category = category_map.get(category_name or "") if category_name else None
            if entry.get("type") == "voice":
                await guild.create_voice_channel(name=name, category=category,
                                                 overwrites=overwrites, reason=reason)
            else:
                await guild.create_text_channel(
                    name=name, category=category, overwrites=overwrites,
                    topic=(entry.get("topic") or None),
                    nsfw=bool(entry.get("nsfw")),
                    slowmode_delay=int(entry.get("slowmode") or 0), reason=reason)
            report["channels"].append(name)
        except discord.HTTPException as exc:
            report["errors"].append(f"kanał {name}: {exc}")

    ghost_log.info("Ghost Copy: %s rol, %s kategorii, %s kanałow, %s błędów",
                   len(report["roles"]), len(report["categories"]),
                   len(report["channels"]), len(report["errors"]))
    return report


async def clone_guild_structure(source: discord.Guild, target: discord.Guild,
                                executor: discord.abc.User,
                                save_as: str = "") -> Dict[str, Any]:
    """Kopiuje strukturę jednego serwera na drugi (z opcjonalnym zapisem szablonu)."""
    layout = export_guild_layout(source)
    if save_as:
        template_save(save_as, layout)
    report = await apply_guild_layout(target, layout, reason=f"Ghost Copy od {executor}")
    report["source"] = f"{source.name} ({source.id})"
    return report


def ghost_report_embed(title: str, report: Dict[str, Any]) -> discord.Embed:
    """Embed z wynikiem operacji Ghost Copy."""
    embed = discord.Embed(title=title, color=C_GREEN, timestamp=datetime.now(timezone.utc),
                          description=(f"**Źródło:** {report.get('source', 'szablon')}\n\n"
                                       f"👥 Role utworzone: **{len(report.get('roles') or [])}**\n"
                                       f"🗂️ Kategorie: **{len(report.get('categories') or [])}**\n"
                                       f"💬 Kanały: **{len(report.get('channels') or [])}**\n"
                                       f"⚠️ Błędy: **{len(report.get('errors') or [])}**"))
    created = ((report.get("roles") or []) + (report.get("categories") or [])
               + (report.get("channels") or []))
    if created:
        embed.add_field(name="Utworzone elementy", inline=False,
                        value="```\n" + "\n".join(created[:20]) +
                              (f"\n... i {len(created) - 20} więcej" if len(created) > 20 else "") + "\n```")
    if report.get("errors"):
        embed.add_field(name="Błędy (sprawdź uprawnienia bota)", inline=False,
                        value="```\n" + "\n".join(str(e) for e in report["errors"][:8]) + "\n```")
    return embed


def system_panel_embed(guild: discord.Guild, executor: discord.abc.User) -> discord.Embed:
    """Embed panelu /system."""
    templates = template_list()
    last = sys_op_last(getattr(guild, "id", None))
    if last:
        last_line = (f"🕒 **Ostatnia operacja:** {last.get('label')} — "
                     f"{'✅' if last.get('ok') else '❌'} <t:{int(last.get('at') or 0)}:R>\n\n")
    else:
        last_line = "🕒 **Ostatnia operacja:** brak\n\n"
    return discord.Embed(
        title="⚙️ Panel Systemowy — Zarządzanie serwerem",
        description=(f"**Serwer:** {guild.name}\n"
                     f"**Operator:** {executor.mention}\n\n"
                     "**Dostępne akcje:**\n"
                     "🎨 **Zbuduj design** — estetyczna przebudowa układu (emotki, kategorie, uprawnienia).\n"
                     "👻 **Ghost Copy** — zapisz/sklonuj całą strukturę (role, kanały, uprawnienia).\n"
                     "⚠️ **Reset serwera** — usuwa strukturę bota (podwójne potwierdzenie!).\n"
                     "🔁 **Ostatnia operacja** — raport ostatniej akcji + ponowienie jednym klikiem\n"
                     "  (ratunek, gdy kanał zniknął w trakcie operacji).\n\n"
                     f"📁 **Szablony Ghost Copy:** {len(templates)} "
                     + (f"({', '.join(templates[:5])})" if templates else "*(brak — zapisz pierwszy przyciskiem 💾)*")
                     + "\n\n" + last_line
                     + "**Zabezpieczenia:** tylko właściciel serwera lub Administrator.\n"
                     f"Każde użycie logowane do `#{CH_SYSLOG}`."),
        color=C_PURPLE, timestamp=datetime.now(timezone.utc))


def system_panel_view(templates: Optional[Sequence[str]] = None) -> discord.ui.View:
    """Przyciski panelu /system (+ szablony Ghost Copy)."""
    rows: List[Any] = [
        [btn("sys_build_design", "Zbuduj estetyczny design", discord.ButtonStyle.success, "🎨"),
         btn("sys_reset_start", "Wyczyść / Resetuj serwer", discord.ButtonStyle.danger, "⚠️"),
         btn("sys_refresh", "Odśwież panel", discord.ButtonStyle.secondary, "🔄")],
        [btn("sys_template_save", "Zapisz szablon", discord.ButtonStyle.secondary, "💾"),
         btn("sys_clone_from", "Sklonuj z innego serwera", discord.ButtonStyle.primary, "👻"),
         btn("sys_last_op", "Ostatnia operacja", discord.ButtonStyle.secondary, "🔁")],
    ]
    names = list(templates if templates is not None else template_list())[:24]
    if names:
        rows.append([select("sys_template_pick", "👻 Ghost Copy — zastosuj szablon...",
                            [opt(f"Zastosuj: {name}", f"tpl:{name}",
                                 "Odtworzy role, kategorie i kanały z szablonu")
                             for name in names])])
    return LayoutView(*rows)


def parse_modal_value(interaction: discord.Interaction, field_id: str) -> str:
    """Wyciąga wartość pola z modala (bez obiektu ModalSubmitInteraction)."""
    for row in interaction.data.get("components", []):
        for child in row.get("components", []):
            if child.get("custom_id") == field_id:
                return str(child.get("value", ""))
    return ""


async def request_approval(interaction: discord.Interaction, session: Session,
                           error: ApprovalRequired) -> None:
    """Tworzy zgłoszenie bezpieczeństwa i powiadamia administratorów."""
    scan = error.scan
    approval = approval_request(error.file_url, scan.get("file_name", "?"),
                                scan.get("reason", "wymaga weryfikacji"), session.user_id,
                                interaction.guild_id, session.channel_id)

    embed = discord.Embed(
        title="🔐 Plik wymaga zgody administratora",
        description=(f"Plik **{scan.get('file_name', '?')}** został zatrzymany przez skan bezpieczeństwa:\n"
                     f"> {scan.get('reason')}\n\nNumer zgłoszenia: `#{approval.id}`\n"
                     "Administrator został powiadomiony. Po akceptacji kliknij ponownie **📦 Zakończ**."\
                     "\n\nTo zabezpieczenie chroni Twoją paczkę przed plikami wykonywalnymi."),
        color=C_YELLOW)
    await interaction.followup.send(embed=embed)

    try:
        admin_channel = await get_admin_log_channel(interaction.guild)
        admin_embed = discord.Embed(
            title="🔐 Zgłoszenie bezpieczeństwa — wymagana decyzja",
            description=(f"**Zgłoszenie:** `#{approval.id}`\n"
                         f"**Plik:** `{approval.file_name}`\n**Powód:** {approval.reason}\n"
                         f"**URL:** {approval.file_url[:200]}\n"
                         f"**Zgłaszający:** <@{approval.user_id}>\n"
                         f"**Kanał sesji:** <#{approval.channel_id}>"),
            color=C_RED, timestamp=datetime.now(timezone.utc))
        await admin_channel.send(embed=admin_embed, view=LayoutView([
            btn(f"sec_approve:{approval.id}", "Zezwól na instalację", discord.ButtonStyle.success, "✅"),
            btn(f"sec_reject:{approval.id}", "Odrzuć plik", discord.ButtonStyle.danger, "⛔"),
        ]))
    except Exception as exc:  # noqa: BLE001
        sys_log.error("Nie wyslano zgloszenia na kanal admina: %s", exc)


async def handle_approval_button(interaction: discord.Interaction, custom_id: str) -> None:
    """Obsługa ✅ Zezwól / ⛔ Odrzuć."""
    if not is_authorized(interaction):
        await interaction.response.send_message(
            "⛔ Tylko właściciel serwera lub Administrator może decydować o plikach.", ephemeral=True)
        return

    action, approval_id = custom_id.split(":", 1)
    approval = APPROVALS.get(approval_id)
    if not approval:
        await interaction.response.send_message("❌ Zgłoszenie nie istnieje lub wygasło.", ephemeral=True)
        return
    if approval.status != "pending":
        await interaction.response.send_message(
            f"ℹ️ To zgłoszenie jest już rozpatrzone ({approval.status}).", ephemeral=True)
        return

    approved = action == "sec_approve"
    approval_decide(approval_id, "approved" if approved else "rejected")
    embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds \
        else discord.Embed(title="Zgłoszenie")
    embed.color = C_GREEN if approved else C_RED
    embed.set_footer(text=f"{'✅ ZEZWOLONO' if approved else '⛔ ODRZUCONO'} przez {interaction.user}")
    await interaction.response.edit_message(embed=embed, view=None)

    await system_log(interaction.guild,
                     "Zgłoszenie bezpieczeństwa ZAAKCEPTOWANE" if approved else "Zgłoszenie bezpieczeństwa ODRZUCONE",
                     interaction.user, f"#{approval_id} — {approval.file_name}\n{approval.reason}\nURL: {approval.file_url}")

    # Creator Economy: XP i odznaka dla administratora za ochronę społeczności
    admin_profile = profile_get(interaction.user)
    if admin_profile is not None:
        admin_profile.reports += 1
        await award_xp(admin_profile, "report", interaction.channel,
                       reason="decyzja o pliku ryzykownym")
        if not approved and admin_profile.badge("analityk"):
            try:
                await interaction.followup.send(f"🛡️ Nowa odznaka: {BADGES['analityk']}",
                                                ephemeral=True)
            except discord.HTTPException:
                pass

    channel = interaction.guild.get_channel(approval.channel_id)
    if channel:
        message = (f"<@{approval.user_id}> ✅ Administrator **zezwolił** na plik `{approval.file_name}`. "
                   "Kliknij **📦 Zakończ**, aby dokończyć paczkę." if approved else
                   f"<@{approval.user_id}> ⛔ Administrator **odrzucił** plik `{approval.file_name}`. "
                   "Wybierz inny wariant moda.")
        try:
            await channel.send(message)
        except discord.HTTPException:
            pass

# ============================================================================
# 22. SERWER HTTP (linki do paczek i podglądów)
# ============================================================================

http_log = log("HTTP")


async def http_health(request: web.Request) -> web.Response:
    """Healthcheck dla hostingu (Render/Railway/VPS)."""
    return web.Response(text="ok")


async def http_download(request: web.Request) -> web.StreamResponse:
    """
    GET /download/<token> — paczka ZIP.

    Pobranie uruchamia Garbage Collector: paczka i workspace gracza zostaną
    usunięte po DELETE_AFTER_DOWNLOAD_MINUTES (domyślnie 10 min), żeby dysk
    VPS-a się nie zapychał.
    """
    token = request.match_info["token"]
    package = STORAGE.get(token)
    if not package:
        return web.Response(text="404: Paczka nie istnieje lub wygasła — "
                                 "uruchom paczkę jeszcze raz w bocie.", status=404)
    if not Path(package["file_path"]).is_file():
        STORAGE.remove(token, "brak pliku na dysku")
        http_log.warning("Link %s wskazuje plik, ktorego juz nie ma (wyczyszczony dysk).", token[:8])
        return web.Response(text="410: Paczka została już usunięta z serwera — "
                                 "uruchom paczkę jeszcze raz w bocie.", status=410)
    STORAGE.mark_downloaded(token)
    http_log.info("Paczka %s pobierana przez HTTP (%s)", package["file_name"],
                  request.remote or "?")
    return web.FileResponse(package["file_path"], headers={
        "Content-Disposition": f'attachment; filename="{package["file_name"]}"',
        "Content-Type": "application/zip",
    })


async def http_image(request: web.Request) -> web.Response:
    """
    GET /img/<klucz>.png — podgląd kroku citizena lub skina broni.

    Szybkie, bo:
      • render idzie do puli wątków (nie blokuje innych żądań),
      • wynik leży w pamięci i na dysku (kolejne wejścia = natychmiast),
      • ETag + długi Cache-Control — przeglądarka bierze obrazek z własnego cache
        i po odświeżeniu strony dostaje tylko 304 (zero bajtów obrazka).
    """
    data = await image_bytes_async(request.match_info.get("key", ""))
    if not data:
        return web.Response(text="404: brak podglądu", status=404)
    etag = '"%s"' % hashlib.sha1(data).hexdigest()[:20]
    headers = {"Cache-Control": "public, max-age=604800, immutable", "ETag": etag}
    if request.headers.get("If-None-Match") == etag:
        return web.Response(status=304, headers=headers)
    return web.Response(body=data, content_type="image/png", headers=headers)


async def http_preview(request: web.Request) -> web.Response:
    """GET /preview/<token> — podgląd kombinacji (Live Before/After)."""
    preview = STORAGE.get_preview(request.match_info["token"])
    if not preview:
        return web.Response(text="<h1>404</h1><p>Podgląd nie istnieje lub wygasł.</p>",
                            content_type="text/html", status=404)
    return web.Response(text=preview["html"], content_type="text/html")


async def http_root(request: web.Request) -> web.Response:
    """GET / — informacja."""
    return web.Response(text=("FiveM Mod Foundry — bot działa.\n"
                             "/health • /download/<token> • /preview/<token> • /create\n"
                             "/api/pack/<token> • /api/profile/<discord_id> • /api/stats"))


# ============================================================================
# KREATOR WWW — strony /create/... (citizen i skiny, 1 opcja na ekran)
# ============================================================================

web_log = log("WebCreator")


def _citizen_img_url(step: Dict[str, Any]) -> str:
    """Duży podgląd kroku na stronie (endpoint /img/...)."""
    return f"/img/{step_image_key(step)}.png"


def _skin_img_url(weapon: Dict[str, Any], skin: Dict[str, Any]) -> str:
    return f"/img/{skin_image_key(weapon, skin)}.png"


def _creator_profile(user_id: str) -> Optional[Profile]:
    """Profil gracza (do blokad rangowych kafli) — None, gdy brak danych."""
    try:
        if str(user_id).isdigit():
            return profile_by_id(int(user_id))
    except Exception:  # noqa: BLE001 — brak profilu nie może ubić kreatora
        pass
    return None


def citizen_ui_items(user_id: str = "") -> List[Dict[str, Any]]:
    """
    Kafle kreatora citizena. Bot SAM wylicza pod tym spodem:
      • plik docelowy (`file`) — ścieżka, którą gracz dostanie w paczce,
      • klucz konfliktu (`key`) — opcje z tym samym kluczem zastępują się,
      • blokady rangowe (`locked`/`level`).
    """
    profile = _creator_profile(user_id)
    out: List[Dict[str, Any]] = []
    for step in CITIZEN_STEPS:
        out.append(creator_item(
            sid=step["id"], tab=step["group"], name=step["name"],
            desc=step["description"],
            file=f"citizen/common/data/{step['gen_file']}",
            img=_citizen_img_url(step),
            key=file_key(step),
            tags=[short_group(step["group"])],
            locked=is_locked(profile, step),
            level=min_level_of(step)))
    return out


def skin_ui_items(user_id: str = "") -> List[Dict[str, Any]]:
    """Kafle skinów: zakładka = broń, klucz = plik .ytd (jeden skin na broń)."""
    profile = _creator_profile(user_id)
    out: List[Dict[str, Any]] = []
    for weapon in all_weapons():
        for skin in weapon["skins"]:
            out.append(creator_item(
                sid=skin["id"], tab=weapon["name"], name=skin["name"],
                desc=skin.get("description") or f"Wykończenie dla {weapon['name']}.",
                file=file_key(skin), img=_skin_img_url(weapon, skin),
                key=file_key(skin), tags=[weapon["name"]],
                locked=is_locked(profile, skin),
                level=min_level_of(skin)))
    return out


def creator_ui_items(kind: str, user_id: str = "") -> List[Dict[str, Any]]:
    """Kafle wybranego kreatora (kind: 'citizen' / 'skins')."""
    return citizen_ui_items(user_id) if kind == "citizen" else skin_ui_items(user_id)


def _creator_items_for_session(sess: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Kafle sesji + ustawienie domyślnej zakładki (żeby odświeżenie jej nie gubiło)."""
    items = creator_ui_items(str(sess.get("kind", "citizen")), sess.get("user_id", ""))
    tabs = {i["tab"] for i in items}
    stored = sess.get("tab")
    if stored not in tabs and stored != web_creator.BUNDLE_TAB:
        # Citizen startuje od „Gotowych presetów” (jedno kliknięcie = cały build),
        # skiny — od pierwszego pistoletu.
        if sess.get("kind") == "citizen" and items:
            sess["tab"] = web_creator.BUNDLE_TAB
        else:
            sess["tab"] = items[0]["tab"] if items else ""
    return items


async def http_create_home(request: web.Request) -> web.Response:
    """GET /create — start kreatora (wybór: citizen albo skiny)."""
    user_id = request.query.get("user", "anon")
    return web.Response(text=render_home_page(user_id), content_type="text/html")


async def http_create_citizen(request: web.Request) -> web.Response:
    """GET /create/citizen?user=ID — nowa sesja kreatora citizena."""
    user_id = request.query.get("user", "anon")
    token = web_session_create("citizen", user_id)
    raise web.HTTPFound(f"/create/citizen/{token}/page")


async def http_create_skins(request: web.Request) -> web.Response:
    """GET /create/skins?user=ID — nowa sesja kreatora skinów."""
    user_id = request.query.get("user", "anon")
    token = web_session_create("skins", user_id)
    raise web.HTTPFound(f"/create/skins/{token}/page")


async def _web_session_or_404(request: web.Request) -> Optional[Dict[str, Any]]:
    token = request.match_info["token"]
    sess = web_session_get(token)
    if not sess:
        return None
    return sess


def _expired_page() -> web.Response:
    return web.Response(
        text="<meta charset='utf-8'><body style='font-family:sans-serif;background:#0b0d13;"
             "color:#e8ecf7;display:grid;place-items:center;height:100vh'>"
             "<div style='text-align:center'><h1>⌛ Sesja wygasła</h1>"
             "<p>Wróć do bota na Discordzie i kliknij przycisk ponownie.</p></div>",
        content_type="text/html", status=410)


async def http_citizen_page(request: web.Request) -> web.Response:
    """GET /create/citizen/{token}/page — studio: zakładki + siatka kafli."""
    sess = await _web_session_or_404(request)
    if not sess:
        return _expired_page()
    return web.Response(text=render_citizen_page(
        request.match_info["token"], sess, _creator_items_for_session(sess)),
        content_type="text/html")


def _citizen_step_by_id(step_id: str) -> Optional[Dict[str, Any]]:
    return next((s for s in CITIZEN_STEPS if s["id"] == step_id), None)


def _toggle_id(ids: List[str], step_id: str) -> None:
    """Klik na kartę: wybiera albo odznacza opcję (zachowuje kolejność wyboru)."""
    if step_id in ids:
        ids.remove(step_id)
    else:
        ids.append(step_id)


async def http_citizen_action(request: web.Request) -> web.Response:
    """
    GET /create/citizen/{token}/{action}/{value} — fallback bez JavaScriptu.
      action=tab    — ustaw zakładkę (value = slug grupy)
      action=toggle — wybierz/odznacz opcję (value = id kroku)

    Korzysta z TEJ SAMEJ logiki co API (auto-zastępowanie plików), więc wynik
    jest identyczny niezależnie od tego, czy gracz ma włączony JS.
    """
    sess = await _web_session_or_404(request)
    if not sess:
        return _expired_page()
    token = request.match_info["token"]
    action = request.match_info["action"]
    value = request.match_info.get("value") or request.match_info.get("index", "")
    items = _creator_items_for_session(sess)
    if action == "toggle" and value:
        toggle_item(sess, items, value)
        raise web.HTTPFound(f"/create/citizen/{token}/page")
    if action == "tab" and value:
        sess["tab"] = web_creator.unslug(value)
    raise web.HTTPFound(f"/create/citizen/{token}/page")


async def http_skins_page(request: web.Request) -> web.Response:
    """GET /create/skins/{token}/page — zakładka broni + siatka skinów."""
    sess = await _web_session_or_404(request)
    if not sess:
        return _expired_page()
    return web.Response(text=render_skins_page(
        request.match_info["token"], sess, _creator_items_for_session(sess)),
        content_type="text/html")


async def http_skins_action(request: web.Request) -> web.Response:
    """
    GET /create/skins/{token}/{action}/{value} — fallback bez JavaScriptu.
      action=weapon — przełącz zakładkę broni (value = id broni)
      action=toggle — wybierz/odznacz skin (value = id skina)
    """
    sess = await _web_session_or_404(request)
    if not sess:
        return _expired_page()
    token = request.match_info["token"]
    action = request.match_info["action"]
    value = request.match_info.get("value") or request.match_info.get("index", "")
    items = _creator_items_for_session(sess)
    if action == "weapon" and value:
        weapon = find_weapon(value)
        if weapon is not None:
            sess["weapon"] = value
            sess["tab"] = weapon["name"]
    elif action == "toggle" and value:
        toggle_item(sess, items, value)
    raise web.HTTPFound(f"/create/skins/{token}/page")


async def http_create_finish(request: web.Request) -> web.Response:
    """
    POST /create/finish/{token} — buduje paczkę z wyborów z kreatora WWW
    (przycisk „📦 Zbuduj paczkę” w panelu bocznym). Zwraca ekran z linkiem.
    """
    sess = await _web_session_or_404(request)
    if not sess:
        return _expired_page()
    if request.method == "GET":
        # stare linki GET -> pokaz kreator (bez budowy)
        raise web.HTTPFound(f"/create/{sess['kind']}/{request.match_info['token']}/page")

    # Budowa paczki w połowie synchronicznie (to endpoint HTTP — krótkie operacje OK)
    workspace = WORKSPACES_DIR / f"web-{sess['user_id']}-{int(time.time())}"
    workspace.mkdir(parents=True, exist_ok=True)
    kind = sess["kind"]
    # Podsumowanie auto-doboru: co bot scalił i jakie pliki trafiły do paczki.
    ui_items = creator_ui_items(kind, sess.get("user_id", ""))
    outputs = output_groups(ui_items, chosen_ids(sess))
    merged_count = sum(1 for grp in outputs if grp.get("merged"))
    try:
        if kind == "citizen":
            items = [dict(s) for s in CITIZEN_STEPS if s["id"] in sess["citizen_ids"]]
            items, _dropped, _conflicts = resolve_conflicts(items)
            kind_for_pack = "citizen"
        else:
            items = []
            for weapon in WEAPON_CATEGORIES:
                for skin in weapon["skins"]:
                    if skin["id"] in sess["skin_ids"]:
                        items.append({**skin, "name": f"{weapon['name']} — {skin['name']}"})
            kind_for_pack = "weapons"
        hashes = await process_items(workspace, items, None)
        if not hashes:
            return web.Response(text="<meta charset='utf-8'><body style='font-family:sans-serif;"
                                     "background:#0b0d13;color:#ed4245;display:grid;place-items:center;"
                                     "height:100vh'><h1>Brak plików do paczki — wybierz coś 🙂</h1>",
                                content_type="text/html")
        zip_name = f"paczka-{kind}-{int(time.time())}.zip"
        zip_path = workspace.parent / zip_name
        await asyncio.to_thread(zip_directory, workspace, zip_path)
        size = zip_path.stat().st_size
        file_count = count_files(workspace)
        dl_token = STORAGE.register(zip_path, zip_name, size, file_count,
                                    int(sess["user_id"]) if sess["user_id"].isdigit() else 0,
                                    workspace)
        public = public_download_url(dl_token)
        download_url = public if public else f"/download/{dl_token}"  # localhost: link względny
    except Exception as exc:  # noqa: BLE001
        await notify_error("Kreator WWW: błąd budowy paczki", str(exc), exc, "web_finish")
        return web.Response(text="<meta charset='utf-8'><body style='font-family:sans-serif;"
                                 "background:#0b0d13;color:#ed4245;display:grid;place-items:center;"
                                 "height:100vh'><h1>Coś się posypało — spróbuj ponownie.</h1>",
                            content_type="text/html", status=500)
    return web.Response(text=render_pack_done(
        request.match_info["token"], download_url, kind, file_count,
        size / (1024 * 1024), outputs, merged_count),
        content_type="text/html")


# ----------------------------------------------------------------------------
# API KREATORA (JSON) — natychmiastowy wybór bez przeładowania strony
# ----------------------------------------------------------------------------

def _expired_json() -> web.Response:
    return web.json_response({"ok": False, "error": "sesja wygasła — otwórz kreator z bota"},
                             status=410)


async def http_api_creator_state(request: web.Request) -> web.Response:
    """GET /api/create/<token>/state — pełny stan studia (zakładki, kafle, wybory)."""
    sess = await _web_session_or_404(request)
    if not sess:
        return _expired_json()
    kind = sess["kind"]
    return web.json_response(build_state(kind, request.match_info["token"], sess,
                                         _creator_items_for_session(sess),
                                         citizen_mods.BUNDLES))


async def http_api_creator_toggle(request: web.Request) -> web.Response:
    """
    POST /api/create/<token>/toggle  {id}

    Bot sam: blokuje opcje zablokowane rangą, zastępuje opcje piszące do tego
    samego pliku i mówi, które pliki właśnie scalił z kilku opcji.
    """
    sess = await _web_session_or_404(request)
    if not sess:
        return _expired_json()
    kind = sess["kind"]
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001 — zły JSON = brak zmian
        data = {}
    items = _creator_items_for_session(sess)
    result = toggle_item(sess, items, str((data or {}).get("id") or ""))
    state = build_state(kind, request.match_info["token"], sess, items)
    return web.json_response({
        "ok": result.get("ok", False),
        "error": result.get("error", ""),
        "added": result.get("added", False),
        "name": result.get("name", ""),
        "replaced": result.get("replaced", []),
        "merged_files": result.get("merged_files", []),
        "chosen": state["chosen"],
        "stats": state["stats"],
    })


async def http_api_creator_bundle(request: web.Request) -> web.Response:
    """
    POST /api/create/<token>/bundle  {id}

    Nakłada CAŁY gotowy preset (np. „PVP / Tryhard”, „Krwawy Księżyc”): dodaje
    wszystkie jego opcje, a konflikty rozwiązuje automatycznie — gracz nie
    klika kilkunastu kafli i nic nie wpisuje.
    """
    sess = await _web_session_or_404(request)
    if not sess:
        return _expired_json()
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001 — zły JSON = brak zmian
        data = {}
    bundle_id = str((data or {}).get("id") or "")
    bundle = next((b for b in citizen_mods.BUNDLES if b["id"] == bundle_id), None)
    if bundle is None:
        return web.json_response({"ok": False, "error": "nieznany preset"})
    items = _creator_items_for_session(sess)
    result = apply_bundle(sess, items, bundle.get("steps") or [])
    state = build_state(sess["kind"], request.match_info["token"], sess, items)
    return web.json_response({
        "ok": result.get("ok", False),
        "added": result.get("added", []),
        "replaced": result.get("replaced", []),
        "locked": result.get("locked", []),
        "merged_files": result.get("merged_files", []),
        "chosen": state["chosen"],
        "stats": state["stats"],
    })


async def http_api_creator_tab(request: web.Request) -> web.Response:
    """POST /api/create/<token>/tab  {tab} — zapamiętuje aktywną zakładkę."""
    sess = await _web_session_or_404(request)
    if not sess:
        return _expired_json()
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        data = {}
    tab = str((data or {}).get("tab") or "")
    items = _creator_items_for_session(sess)
    if tab in {i["tab"] for i in items}:
        sess["tab"] = tab
    return web.json_response({"ok": True, "tab": sess.get("tab", "")})


async def http_api_creator_clear(request: web.Request) -> web.Response:
    """POST /api/create/<token>/clear — czyści wszystkie wybory."""
    sess = await _web_session_or_404(request)
    if not sess:
        return _expired_json()
    clear_items(sess)
    return web.json_response({"ok": True, "chosen": []})


async def http_api_creator_pack(request: web.Request) -> web.Response:
    """GET /api/create/<token>/pack — co bot zbuduje (pliki + scalenia)."""
    sess = await _web_session_or_404(request)
    if not sess:
        return _expired_json()
    kind = sess["kind"]
    state = build_state(kind, request.match_info["token"], sess,
                        _creator_items_for_session(sess))
    return web.json_response({"ok": True, "outputs": state["outputs"],
                              "stats": state["stats"]})


def _page_html(title: str, chip: str, main_html: str) -> str:
    """Dostęp do _page z web_creator (render końcowy)."""
    return web_creator._page(title, chip, main_html)


async def http_api_pack(request: web.Request) -> web.Response:
    """
    GET /api/pack/<token> — weryfikacja paczki dla serwera FiveM.

    Zwraca metadane paczki i status podpisu HMAC. Mini-resource na serwerze
    może tym sprawdzić, kto wygenerował paczkę (np. żeby nadać rangę w grze):
      PerformHttpRequest(url .. "/api/pack/" .. token, cb, "GET")
    """
    record = pack_token_get(request.match_info["token"].strip().upper())
    if not record:
        return web.json_response({"ok": False, "error": "nieznany token"}, status=404)
    return web.json_response({"ok": True, **record})


async def http_api_profile(request: web.Request) -> web.Response:
    """GET /api/profile/<discord_id> — publiczne podsumowanie profilu twórcy."""
    try:
        user_id = int(request.match_info["user_id"])
    except ValueError:
        return web.json_response({"ok": False, "error": "zły identyfikator"}, status=400)
    profile = profile_by_id(user_id)
    if profile is None:
        return web.json_response({"ok": False, "error": "brak profilu"}, status=404)
    payload = {
        "ok": True, "user_id": profile.user_id, "username": profile.username,
        "level": profile.level, "rank": profile.rank["name"], "xp": profile.xp,
        "builds": profile.builds, "badges": [BADGES[b] for b in profile.badges if b in BADGES],
    }
    return web.json_response(payload)


async def http_api_bridge_inbox(request: web.Request) -> web.Response:
    """
    GET /api/bridge/inbox?after=<id> — kolejka zdarzeń dla resource'a FiveM.

    Przykład w Lua (fxmanifest: `dependency 'foundry_bridge'`):
      PerformHttpRequest(API .. "/api/bridge/inbox?after=" .. lastId, function(code, body)
        for _, event in ipairs(json.decode(body)) do
          TriggerClientEvent('chat:addMessage', -1, { args = { event.title, event.message } })
          lastId = event.id
        end
      end, "GET", "")
    """
    try:
        after = int(request.query.get("after", "0") or 0)
    except ValueError:
        after = 0
    try:
        limit = min(100, max(1, int(request.query.get("limit", "50") or 50)))
    except ValueError:
        limit = 50
    return web.json_response({"ok": True, "events": bridge_pending(after, limit),
                              "next_after": BRIDGE_INBOX[-1]["id"] if BRIDGE_INBOX else after})


async def http_api_bridge_send(request: web.Request) -> web.Response:
    """POST /api/bridge/send — wiadomość z gry na Discord (wymaga tokenu mostu)."""
    if FIVEM_BRIDGE_TOKEN and request.headers.get("X-Foundry-Token") != FIVEM_BRIDGE_TOKEN:
        return web.json_response({"ok": False, "error": "zły token mostu"}, status=403)
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"ok": False, "error": "oczekuję JSON"}, status=400)
    author = str(payload.get("author", ""))[:64]
    message = str(payload.get("message", ""))[:1500]
    if not message:
        return web.json_response({"ok": False, "error": "brak treści"}, status=400)
    delivered = await bridge_relay_to_discord(bot, author, message,
                                              str(payload.get("source", "gra"))[:32])
    return web.json_response({"ok": delivered,
                              "error": None if delivered else "brak kanału na Discordzie"},
                             status=200 if delivered else 503)


async def http_api_bridge_status(request: web.Request) -> web.Response:
    """GET /api/bridge/status — stan mostu (push/pull)."""
    return web.json_response({
        "ok": True,
        "push_url": bool(FIVEM_BRIDGE_URL),
        "token_set": bool(FIVEM_BRIDGE_TOKEN),
        "channel": BRIDGE_CHANNEL_NAME,
        "queued": len(BRIDGE_INBOX),
        "last_id": BRIDGE_INBOX[-1]["id"] if BRIDGE_INBOX else 0,
    })


async def http_api_stats(request: web.Request) -> web.Response:
    """GET /api/stats — statystyki bota (bez danych wrażliwych)."""
    queue = ZIP_QUEUE.info()
    return web.json_response({
        "ok": True,
        "creators": len(PROFILES),
        "steps": len(CITIZEN_STEPS),
        "weapons": len(all_weapons()),
        "packs_issued": len(PACK_TOKENS),
        "previews": preview_cache_stats(),
        "queue": {"waiting": queue["waiting"], "running": queue["running"],
                  "completed": queue["completed"], "failed": queue["failed"]},
        "cache": {"files": FILE_CACHE.stats()["files"],
                  "hits": FILE_CACHE.stats()["hits"],
                  "misses": FILE_CACHE.stats()["misses"]},
    })


# Typy odpowiedzi, które warto kompresować (HTML studia = 167 kB -> 24 kB).
_GZIP_TYPES = ("text/html", "text/plain", "text/css", "application/json",
               "application/javascript", "text/javascript", "image/svg+xml")
_GZIP_MIN_BYTES = 900


@web.middleware
async def gzip_middleware(request: web.Request, handler) -> web.StreamResponse:
    """
    Kompresja stron i JSON (gzip). Strona studia to głównie JSON stanu i arkusze
    stylów — po kompresji schodzi z ~166 kB do ~25 kB, więc ładuje się kilka razy
    szybciej, zwłaszcza na telefonie i słabym łączu.
    """
    response = await handler(request)
    if not isinstance(response, web.Response) or response.body is None:
        return response
    if response.headers.get("Content-Encoding"):
        return response
    ctype = (response.content_type or "").split(";")[0].strip().lower()
    if ctype not in _GZIP_TYPES or len(response.body) < _GZIP_MIN_BYTES:
        return response
    if "gzip" not in request.headers.get("Accept-Encoding", "").lower():
        return response
    packed = zlib.compress(response.body, 5)
    if len(packed) >= len(response.body):
        return response
    response.body = packed
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Vary"] = "Accept-Encoding"
    if "Content-Length" in response.headers:
        del response.headers["Content-Length"]  # aiohttp policzy je od nowa
    return response


def create_http_app() -> web.Application:
    """Tworzy aplikację aiohttp z trasami bota."""
    app = web.Application(middlewares=[gzip_middleware])
    app.router.add_get("/health", http_health)
    app.router.add_get("/download/{token}", http_download)
    app.router.add_get("/preview/{token}", http_preview)
    app.router.add_get("/img/{key}", http_image)
    app.router.add_get("/create", http_create_home)
    app.router.add_get("/create/citizen", http_create_citizen)
    app.router.add_get("/create/citizen/{token}/page", http_citizen_page)
    app.router.add_get("/create/citizen/{token}/{action}/{value}", http_citizen_action)
    app.router.add_get("/create/skins", http_create_skins)
    app.router.add_get("/create/skins/{token}/page", http_skins_page)
    app.router.add_get("/create/skins/{token}/{action}/{value}", http_skins_action)
    app.router.add_get("/create/finish/{token}", http_create_finish)  # GET = redirect do kreatora
    app.router.add_post("/create/finish/{token}", http_create_finish)  # POST = buduje paczkę
    # JSON API studia (natychmiastowy wybór bez przeładowania strony)
    app.router.add_get("/api/create/{token}/state", http_api_creator_state)
    app.router.add_post("/api/create/{token}/toggle", http_api_creator_toggle)
    app.router.add_post("/api/create/{token}/bundle", http_api_creator_bundle)
    app.router.add_post("/api/create/{token}/tab", http_api_creator_tab)
    app.router.add_post("/api/create/{token}/clear", http_api_creator_clear)
    app.router.add_get("/api/create/{token}/pack", http_api_creator_pack)
    app.router.add_get("/api/pack/{token}", http_api_pack)
    app.router.add_get("/api/profile/{user_id}", http_api_profile)
    app.router.add_get("/api/bridge/inbox", http_api_bridge_inbox)
    app.router.add_get("/api/bridge/status", http_api_bridge_status)
    app.router.add_post("/api/bridge/send", http_api_bridge_send)
    app.router.add_get("/api/stats", http_api_stats)
    app.router.add_get("/", http_root)
    return app

# ============================================================================
# 23. BOT — tickety, router interakcji, komendy, pętle w tle
# ============================================================================

ticket_log = log("Tickets")

# ============================================================================
# 22.5. GLOBALNA OBSŁUGA BŁĘDÓW (webhook + kanał administracji)
# ============================================================================

err_log = log("Errors")
admin_log = log("Admin")
ERROR_ID_CHARS = "0123456789abcdef"


def new_error_id() -> str:
    """Krótki kod błędu — gracz podaje go w zgłoszeniu, admin znajduje w logach."""
    return "".join(random.choice(ERROR_ID_CHARS) for _ in range(6))


async def notify_error(title: str, detail: str = "", exc: Optional[BaseException] = None,
                       where: str = "", user: Optional[discord.abc.User] = None,
                       color: int = C_RED) -> str:
    """
    Jedno miejsce na wszystkie błędy bota:
      1. konsola + logs/bot.log,
      2. webhook (ERROR_WEBHOOK_URL) — jeśli ustawiony,
      3. embed na kanale #logi-system każdego serwera.
    Zwraca kod błędu, który gracz może podać administracji.
    """
    eid = new_error_id()
    trace = ""
    if exc is not None:
        trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-1500:]
    err_log.error("[%s] %s | %s | %s\n%s", eid, title, where, detail, trace)

    embed = discord.Embed(title=f"🚨 {title}", color=color,
                          timestamp=datetime.now(timezone.utc),
                          description=(detail or "—")[:2000])
    embed.add_field(name="Kod błędu", value=f"`{eid}`", inline=True)
    if where:
        embed.add_field(name="Miejsce", value=f"`{where}`"[:1024], inline=True)
    if user is not None:
        embed.add_field(name="Użytkownik", value=f"{user} (`{getattr(user, 'id', '?')}`)", inline=True)
    if exc is not None:
        embed.add_field(name="Wyjątek",
                        value=f"```{type(exc).__name__}: {str(exc)[:200]}```", inline=False)
    if trace:
        embed.add_field(name="Traceback (fragment)", value=f"```{trace[:1000]}```", inline=False)

    await _deliver_admin_embed(embed)
    return eid


async def _deliver_admin_embed(embed: discord.Embed) -> None:
    """Wysyła embed na webhook (jeśli ustawiony) i na kanał #logi-system każdego serwera."""
    if ERROR_WEBHOOK_URL:
        try:
            async with aiohttp.ClientSession() as http:
                await http.post(ERROR_WEBHOOK_URL, timeout=aiohttp.ClientTimeout(total=10),
                                json={"username": "FiveM Mod Foundry", "embeds": [embed.to_dict()]})
        except Exception as webhook_exc:  # noqa: BLE001
            err_log.warning("Webhook nie zadziałał: %s", webhook_exc)
    try:
        for guild in (bot.guilds if bot else []):
            channel = await get_admin_log_channel(guild)
            if channel:
                await channel.send(embed=embed)
    except Exception as log_exc:  # noqa: BLE001
        err_log.warning("Nie wysłano powiadomienia na kanał: %s", log_exc)


async def notify_admin(title: str, detail: str = "", color: int = C_BLUE) -> None:
    """Powiadomienie (nie błąd) na kanał administracji + webhook: np. 'bot wstał'."""
    admin_log.info("[ADMIN] %s | %s", title, detail)
    embed = discord.Embed(title=title, description=(detail or "—")[:2000], color=color,
                          timestamp=datetime.now(timezone.utc))
    await _deliver_admin_embed(embed)


# ---------------------------------------------------------------------------
# 22.5.1. BEZPIECZNE WYSYŁANIE ODPOWIEDZI (Unknown Channel / wygasły token)
#   Discord zwraca 400/10003 "Unknown Channel", gdy kanał, z którego kliknięto
#   przycisk, przestał istnieć w trakcie długiej operacji (reset/design usuwa
#   kanały, drugi admin może skasować kanał równolegle). Wysyłka nie może wtedy
#   wywalić handlera — inaczej jeden klik generuje drugie zgłoszenie błędu
#   ("During handling of the above exception...") zamiast czytelnej informacji.
#   Dodatkowo, gdy kanał zniknął, wynik leci na priv autora akcji,
#   a jeśli priv jest zamknięty — na kanał #logi-system.
# ---------------------------------------------------------------------------

GONE_CHANNEL_CODES = {10003, 10013}


def _is_channel_gone_error(exc: BaseException) -> bool:
    """Czy wyjątek Discorda oznacza 'kanał już nie istnieje'?"""
    if getattr(exc, "code", None) in GONE_CHANNEL_CODES:
        return True
    text = f"{type(exc).__name__} {exc}".lower()
    return "unknown channel" in text or "unknown channel" in str(getattr(exc, "text", "")).lower()


def interaction_channel_gone(interaction: discord.Interaction) -> bool:
    """True, gdy kanał interakcji zniknął z serwera (bot go już nie widzi)."""
    guild = getattr(interaction, "guild", None)
    channel_id = getattr(interaction, "channel_id", None)
    getter = getattr(guild, "get_channel_or_thread", None)
    if guild is None or not channel_id or getter is None:
        return False
    return getter(channel_id) is None


async def _deliver_fallback(interaction: discord.Interaction, *, content: Optional[str] = None,
                           embed: Optional[discord.Embed] = None, view: Any = None,
                           where: str = "interakcja") -> None:
    """Awaryjna dostawa wyniku: priv autora akcji, a potem kanał #logi-system."""
    note = ("ℹ️ Kanał, na którym klikałeś, zniknął albo odpowiedź nie mogła do niego dotrzeć — "
            "wynik wysyłam tutaj. Pełny log jest w `#" + CH_SYSLOG + "`, a raport ostatniej "
            "operacji odzyskasz przyciskiem 🔁 w `/system`.")
    body = f"{content}\n\n{note}" if content else note

    user = getattr(interaction, "user", None)
    if user is not None:
        try:
            await user.send(content=body, embed=embed, view=view)
            return
        except discord.HTTPException as exc:
            sys_log.warning("Fallback na priv nie dotarł (%s): %s", where, exc)

    guild = getattr(interaction, "guild", None)
    if guild is not None:
        try:
            channel = await get_admin_log_channel(guild)
            if channel:
                await channel.send(content=body, embed=embed)
        except Exception as exc:  # noqa: BLE001
            sys_log.warning("Fallback na #%s nieudany (%s): %s", CH_SYSLOG, where, exc)


async def safe_reply(interaction: discord.Interaction, *, content: Optional[str] = None,
                     embed: Optional[discord.Embed] = None, view: Any = None,
                     ephemeral: bool = True, where: str = "interakcja") -> bool:
    """
    Odpowiada na interakcję tak, by awaria wysyłki nie przerwała handlera.

    1. Najpierw normalna odpowiedź (`response` → `followup`).
    2. Gdy kanał/kanał docelowy zniknął (10003), wynik idzie fallbackiem
       (`_deliver_fallback`), więc użytkownik NIE zostaje bez informacji.
    3. Nigdy nie podnosi wyjątku — zwraca True (wysłano) / False (fallback).
    """
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content=content, embed=embed, view=view,
                                            ephemeral=ephemeral)
        else:
            await interaction.response.send_message(content=content, embed=embed, view=view,
                                                    ephemeral=ephemeral)
        return True
    except discord.InteractionResponded:
        try:
            await interaction.followup.send(content=content, embed=embed, view=view,
                                            ephemeral=ephemeral)
            return True
        except discord.HTTPException as exc:
            sys_log.warning("Nie wysłano odpowiedzi (%s): %s", where, exc)
    except discord.HTTPException as exc:
        if _is_channel_gone_error(exc):
            sys_log.warning("Odpowiedź (%s) nie dotarła — kanał już nie istnieje: %s", where, exc)
        else:
            sys_log.warning("Nie wysłano odpowiedzi (%s): %s", where, exc)
    except Exception as exc:  # noqa: BLE001
        sys_log.warning("Nie wysłano odpowiedzi (%s): %s", where, exc)

    await _deliver_fallback(interaction, content=content, embed=embed, view=view, where=where)
    return False


async def safe_defer(interaction: discord.Interaction, *, ephemeral: bool = True,
                     thinking: bool = False, where: str = "interakcja") -> bool:
    """`response.defer()` odporne na podwójne kliknięcie i na zniknięcie kanału."""
    try:
        await interaction.response.defer(ephemeral=ephemeral, thinking=thinking)
        return True
    except discord.InteractionResponded:
        return True
    except discord.HTTPException as exc:
        if _is_channel_gone_error(exc):
            sys_log.warning("defer (%s) — kanał już nie istnieje: %s", where, exc)
        else:
            sys_log.warning("defer (%s) nieudany: %s", where, exc)
        return False
    except Exception as exc:  # noqa: BLE001
        sys_log.warning("defer (%s) nieudany: %s", where, exc)
        return False


async def safe_modal(interaction: discord.Interaction, modal: discord.ui.Modal,
                     where: str = "interakcja") -> bool:
    """Otwiera okno modalne; gdy się nie da, informuje autora akcji poza kanałem."""
    try:
        await interaction.response.send_modal(modal)
        return True
    except discord.InteractionResponded:
        return True
    except discord.HTTPException as exc:
        sys_log.warning("Modal (%s) nie wysłany: %s", where, exc)
    except Exception as exc:  # noqa: BLE001
        sys_log.warning("Modal (%s) nie wysłany: %s", where, exc)
    await _deliver_fallback(interaction,
                            content="❌ Nie udało się otworzyć okna potwierdzenia. "
                                    "Spróbuj ponownie z innego kanału.",
                            where=where)
    return False


async def report_user_error(interaction: discord.Interaction, exc: BaseException, where: str) -> None:
    """Czytelny komunikat dla gracza + automatyczne zgłoszenie dla administracji."""
    eid = await notify_error(f"Błąd obsługi: {where}", f"Komenda/akcja: `{where}`", exc, where,
                             getattr(interaction, "user", None))
    message = (f"😔 **Ups, coś poszło nie tak** (`{where}`).\n"
               "Nic nie zostało zepsute — spróbuj ponownie lub kliknij przycisk raz jeszcze.\n"
               f"Jeśli problem wraca, zgłoś administracji kod błędu: `{eid}`")
    # safe_reply: brak kanału/perms już nie wywala obsługi błędu drugim wyjątkiem.
    await safe_reply(interaction, content=message, ephemeral=True, where=where)


def handle_loop_exception(loop: asyncio.AbstractEventLoop, context: Dict[str, Any]) -> None:
    """Łapie wyjątki zadań w tle (np. pętli skanera), żeby bot nie umarł po cichu."""
    exc = context.get("exception")
    message = context.get("message") or "nieznany błąd pętli zdarzeń"
    err_log.error("Wyjątek pętli: %s (%s)", message, exc)
    try:
        asyncio.create_task(notify_error("Wyjątek w zadaniu w tle", str(message), exc, "asyncio"))
    except RuntimeError:
        pass

# ============================================================================
# 22.6. MOST DISCORD <-> FIVEM (dwukierunkowa komunikacja z grą)
#    Kierunek 1 (bot -> gra): kolejka do odpytania przez resource (pull)
#                             + opcjonalny POST na FIVEM_BRIDGE_URL (push).
#    Kierunek 2 (gra -> bot): POST /api/bridge/send -> kanał na Discordzie.
# ============================================================================

bridge_log = log("Bridge")

FIVEM_BRIDGE_URL = os.getenv("FIVEM_BRIDGE_URL", "").strip()
FIVEM_BRIDGE_TOKEN = os.getenv("FIVEM_BRIDGE_TOKEN", "").strip()
BRIDGE_CHANNEL_NAME = os.getenv("BRIDGE_CHANNEL", "most-foundry").strip() or "most-foundry"
BRIDGE_INBOX_LIMIT = int(os.getenv("BRIDGE_INBOX_LIMIT", "100") or 100)

BRIDGE_INBOX: List[Dict[str, Any]] = []
_bridge_seq = {"value": 0}


def bridge_record(title: str, message: str, kind: str = "info",
                  meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Dodaje zdarzenie do kolejki mostu (do odbioru przez serwer FiveM)."""
    _bridge_seq["value"] += 1
    record = {"id": _bridge_seq["value"], "at": int(time.time()), "title": title,
              "message": message, "kind": kind, "meta": dict(meta or {})}
    BRIDGE_INBOX.append(record)
    del BRIDGE_INBOX[:-BRIDGE_INBOX_LIMIT]
    return record


async def bridge_notify(title: str, message: str, kind: str = "info",
                        meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Wysyła zdarzenie bota do serwera FiveM.

    • Zawsze ląduje w kolejce (tryb PULL): resource odpytuje
      `GET /api/bridge/inbox?after=<id>` — działa nawet za NAT-em.
    • Jeśli ustawisz FIVEM_BRIDGE_URL, bot dodatkowo wysyła POST (tryb PUSH)
      z nagłówkiem `X-Foundry-Token`, więc resource dostaje zdarzenie od razu.
    """
    record = bridge_record(title, message, kind, meta)
    bridge_log.info("[%s] %s | %s", kind, title, message)
    if FIVEM_BRIDGE_URL:
        headers = {"Content-Type": "application/json"}
        if FIVEM_BRIDGE_TOKEN:
            headers["X-Foundry-Token"] = FIVEM_BRIDGE_TOKEN
        try:
            async with aiohttp.ClientSession() as http:
                await http.post(FIVEM_BRIDGE_URL, json=record, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=8))
        except Exception as exc:  # noqa: BLE001
            bridge_log.warning("Push do FiveM nieudany (%s) — zdarzenie czeka w kolejce.", exc)
    return record


def bridge_pending(after_id: int = 0, limit: int = 50) -> List[Dict[str, Any]]:
    """Zdarzenia nowsze niż `after_id` (dla resource'a w grze)."""
    try:
        threshold = int(after_id)
    except (TypeError, ValueError):
        threshold = 0
    return [record for record in BRIDGE_INBOX if record["id"] > threshold][:max(1, limit)]


async def bridge_relay_to_discord(bot_instance: "FoundryBot", author: str, message: str,
                                  source: str = "gra") -> bool:
    """Drugi kierunek mostu: wiadomość z serwera FiveM trafia na Discord."""
    for guild in bot_instance.guilds:
        channel = (discord.utils.get(guild.text_channels, name=BRIDGE_CHANNEL_NAME)
                   or find_channel(guild, CAT_MODS, CH_MODS_LIVE))
        if channel is None:
            continue
        embed = discord.Embed(
            title="🎮 Wiadomość z serwera FiveM",
            description=(message or "")[:2000] or "—",
            color=C_BLUE, timestamp=datetime.now(timezone.utc))
        embed.set_footer(text=f"Źródło: {source} • {author or 'nieznany'}")
        try:
            await channel.send(embed=embed)
            bridge_log.info("Przekazano wiadomosc z gry na #%s", channel.name)
            return True
        except discord.HTTPException as exc:
            bridge_log.warning("Nie przekazano wiadomosci z gry: %s", exc)
    return False


class FoundryBot(discord.Client):
    """Klient Discorda z wbudowanym serwerem HTTP i zadaniami w tle."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True  # wyszukiwarka skinów (.rpf) — user wpisuje frazę
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.http_runner: Optional[web.AppRunner] = None

    # ------------------------------------------------------------------ start
    async def setup_hook(self) -> None:
        # 1. Serwer HTTP (linki do paczek i podglądów)
        self.http_runner = web.AppRunner(create_http_app())
        await self.http_runner.setup()
        await web.TCPSite(self.http_runner, "0.0.0.0", HTTP_PORT).start()
        http_log.info("Serwer HTTP na porcie %s (adres: %s, zrodlo: %s)",
                      HTTP_PORT, PUBLIC_URL, PUBLIC_URL_SOURCE)
        if not public_url_is_public():
            http_log.warning(
                "Adres publiczny to '%s' — linki /download/ i /preview/ nie zadziałają "
                "u graczy, więc paczki i podglądy polecą jako załączniki Discorda. "
                "Ustaw PUBLIC_URL na publiczny adres bota, aby działały zwykłe linki.",
                PUBLIC_URL)

        # 1b. Dogrzewanie podglądów w tle (konwersja starego cache + render brakujących),
        #     żeby pierwszy gracz nie czekał na obrazki kafli.
        start_preview_worker()

        # 2. Komendy slash
        try:
            synced = await self.tree.sync()
            core_log.info("Zarejestrowano %s komend slash.", len(synced))
        except discord.HTTPException as exc:
            core_log.error("Blad rejestracji komend: %s", exc)

        # 3. Globalny łapacz wyjątków zadań w tle
        asyncio.get_running_loop().set_exception_handler(handle_loop_exception)

        # 3.5. Profile twórców i tokeny paczek (Creator Economy)
        profiles_load()
        packs_load()

        # 4. Zadania w tle
        asyncio.create_task(scanner_loop(self))
        asyncio.create_task(sweeper_loop(self))
        asyncio.create_task(precache_items())          # zapas plików = natychmiastowe paczki
        asyncio.create_task(_heartbeat_loop())         # watchdog 24/7: godzinny heartbeat

    async def on_ready(self) -> None:
        core_log.info("Zalogowano jako %s", self.user)
        if self.user:
            await self.change_presence(activity=discord.Activity(
                type=discord.ActivityType.watching, name="FiveM Mod Foundry"))

        # Wersjonowanie: czy build zmienił się od ostatniego uruchomienia?
        previous = build_state_get()
        if not previous:
            build_state_set(DEFAULT_BUILD_ID, "first-start")
        elif previous.get("build_id") != DEFAULT_BUILD_ID:
            core_log.warning("Build zmieniony: %s -> %s", previous.get("build_id"), DEFAULT_BUILD_ID)
            await announce_build_change(previous.get("build_id", "?"), DEFAULT_BUILD_ID)

        for guild in self.guilds:
            try:
                await setup_guild(guild)
            except Exception as exc:  # noqa: BLE001
                await notify_error("Błąd konfiguracji serwera", f"Serwer: {guild.name} ({guild.id})",
                                   exc, "setup_guild")
                core_log.error("Setup %s: %s", guild.name, exc)

        cache = FILE_CACHE.stats()
        core_log.info("Cache: %s plików, %.1f MB (hity: %s, pobrania: %s)",
                      cache["files"], cache["bytes"] / 1024 / 1024, cache["hits"], cache["misses"])
        core_log.info("✅ Bot gotowy.")
        await notify_admin(
            "🟢 Bot uruchomiony",
            (f"Serwery: **{len(self.guilds)}** • Opcje citizena: **{len(CITIZEN_STEPS)}** "
             f"• Broni w bazie: **{len(all_weapons())}**\n"
             f"Kolejka ZIP: **{ZIP_QUEUE.concurrency_limit}** równolegle • "
             f"Cache plików: **{cache['files']}** ({cache['bytes'] / 1024 / 1024:.1f} MB)\n"
             f"Most FiveM: **{'push+pull' if FIVEM_BRIDGE_URL else 'pull'}** "
             f"(`/api/bridge/inbox`) • walidator anty-crash: "
             f"**{'włączony' if AUTO_PATCH_FILES else 'tylko raport'}**\n"
             f"Paczki: **{STORAGE.stats()['packages']}** • Podglądy: **{STORAGE.stats()['previews']}**"),
            C_GREEN)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        try:
            await setup_guild(guild)
            core_log.info("Dołączono i skonfigurowano %s", guild.name)
        except Exception as exc:  # noqa: BLE001
            core_log.error("Setup nowego serwera: %s", exc)
            await notify_error("Błąd setupu nowego serwera", f"Serwer: {guild.name} ({guild.id})",
                               exc, "on_guild_join")

    async def on_error(self, event_method: str, /, *args: Any, **kwargs: Any) -> None:
        """Łapie błędy zdarzeń discord.py (np. on_message) i raportuje je administracji."""
        exc = sys.exc_info()[1]
        err_log.error("Błąd zdarzenia %s: %s", event_method, exc, exc_info=True)
        await notify_error(f"Błąd zdarzenia `{event_method}`", "Zdarzenie Discorda zgłosiło wyjątek.",
                           exc, event_method)

    # -------------------------------------------------------- wiadomości (.rpf)
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        session = session_get(message.channel.id)
        if not session or session.user_id != message.author.id:
            return
        # 1) Własne pliki gracza (przycisk 📎) — załącznik albo wklejony link.
        if session.upload_armed:
            try:
                if await handle_upload_message(message, session):
                    return
            except Exception as exc:  # noqa: BLE001
                upload_log.error("Blad obslugi wlasnego pliku: %s", exc, exc_info=True)
        if not session.search_mode:
            return
        query = message.content.strip()
        if len(query) < 2 or query.startswith("/"):
            return
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        try:
            await process_search_query(message.channel, session, query)
        except Exception as exc:  # noqa: BLE001
            eid = await notify_error("Błąd wyszukiwarki skinów", f"Fraza: `{query[:80]}`", exc,
                                     "process_search_query", message.author)
            try:
                await message.channel.send(
                    f"😔 Wyszukiwarka nie odpowiedziała poprawnie. Spróbuj ponownie "
                    f"lub wpisz inną frazę (kod: `{eid}`).", delete_after=30)
            except discord.HTTPException:
                pass

    # ------------------------------------------------------------------ router
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """
        JEDEN router wszystkich komponentów (przyciski, selecty, modale).

        Dzięki temu logika jest w jednym miejscu, a custom_id zawiera cały stan
        (np. `citizen_add:7`, `ws_choose:ak47:0`) — przyciski działają też po
        restarcie bota, a wygasła sesja dostaje czytelny komunikat zamiast ciszy.
        """
        try:
            interaction_type = interaction.type
            if interaction_type == discord.InteractionType.application_command:
                return  # komendy slash obsługuje drzewo komend

            if interaction_type == discord.InteractionType.modal_submit:
                modal_id = str((interaction.data or {}).get("custom_id", ""))
                if modal_id == "sys_reset_modal":
                    await handle_reset_modal(interaction)
                elif modal_id == "sys_save_modal":
                    await handle_ghost_save_modal(interaction)
                elif modal_id == "sys_clone_modal":
                    await handle_ghost_clone_modal(interaction)
                elif modal_id.startswith("sys_apply_modal:"):
                    await handle_ghost_apply_modal(interaction,
                                                   modal_id.split(":", 1)[1])
                return

            if interaction_type != discord.InteractionType.component:
                return

            data = interaction.data or {}
            custom_id = str(data.get("custom_id", ""))
            component_type = data.get("component_type")
            values = data.get("values") or []
            if component_type not in (2, 3):
                return

            # --- akcje bez sesji ---
            if custom_id == "take_role":
                await handle_take_role(interaction)
                return
            if custom_id == "settings_toggle_dm":
                await handle_settings_toggle(interaction)
                return
            if custom_id == "create_citizen":
                await create_ticket(interaction, "citizen")
                return
            if custom_id == "create_weapon_skins":
                await create_ticket(interaction, "weapons")
                return
            if custom_id.startswith("sys_"):
                await handle_system_button(interaction, custom_id, values)
                return
            if custom_id.startswith(("sec_approve:", "sec_reject:")):
                await handle_approval_button(interaction, custom_id)
                return

            # --- akcje sesyjne ---
            session = session_get(interaction.channel_id)
            if not session or session.user_id != interaction.user.id:
                await interaction.response.send_message(
                    "❌ Sesja wygasła lub to nie Twoja sesja. Kliknij ponownie przycisk na kanale panelu.",
                    ephemeral=True)
                return

            if custom_id == "session_close":
                await interaction.response.send_message("🔒 Zamykam sesję (kanał zniknie za 3 s)...",
                                                       ephemeral=True)
                await asyncio.sleep(3)
                await close_session(self, session, "Koniec sesji (/zamknij)")
                return

            if custom_id == "build_pick":
                await handle_build_pick(interaction, session, values)
                return

            if custom_id == "mode_citizen":
                session.mode = "citizen"
                await interaction.response.defer()
                await send_step(interaction.channel, session, 0)
                return

            if custom_id == "mode_weapons":
                session.mode = "weapons"
                await interaction.response.defer()
                await send_category_menu(interaction.channel, session)
                return

            # --- przyciski/selecty kreatora citizena ---
            if custom_id.startswith(("citizen_add:", "citizen_locked:")):
                index = int(custom_id.split(":", 1)[1])
                step = CITIZEN_STEPS[index]
                profile = profile_by_id(session.user_id)
                level = profile.level if profile else 0
                if level < min_level_of(step):
                    await interaction.response.send_message(
                        f"{lock_text(step)}\n\nTwój poziom: **{level}** • XP: "
                        f"**{profile.xp if profile else 0}** — buduj paczki i oceniaj mody "
                        "(`/profil`, `/top`).", ephemeral=True)
                    return
                if step["id"] in session.choices:
                    session.choices.remove(step["id"])
                else:
                    session.choices.append(step["id"])
                chosen = step["id"] in session.choices
                await edit_with_image(interaction, key=step_image_key(step), data=step_image(step),
                                      embed=step_embed(step, index, chosen, level),
                                      view=step_view(index, chosen, False, 0, session.user_id))
                return

            if custom_id.startswith("citizen_skip:"):
                # „Pomiń i dalej” = nie chcę tej opcji (cofa wybór, jeśli był) i idziemy dalej.
                index = int(custom_id.split(":", 1)[1])
                step = CITIZEN_STEPS[index]
                if step["id"] in session.choices:
                    session.choices.remove(step["id"])
                await interaction.response.defer()
                await send_step(interaction.channel, session, index + 1)
                return

            if custom_id.startswith("citizen_next:"):
                # „Dalej” = zostaw wybór taki, jaki jest, i pokaż kolejną opcję.
                index = int(custom_id.split(":", 1)[1])
                await interaction.response.defer()
                await send_step(interaction.channel, session, index + 1)
                return

            if custom_id.startswith("citizen_back:"):
                index = int(custom_id.split(":", 1)[1])
                await interaction.response.defer()
                await send_step(interaction.channel, session, max(0, index - 1))
                return

            # --- własne pliki gracza (📎) ---
            if custom_id == "citizen_upload":
                session.upload_kind = "citizen"
                session.upload_armed = True
                session.upload_target = session.upload_target or T_MODS
                await interaction.response.send_message(
                    embed=upload_prompt_embed(session), view=upload_target_buttons(), ephemeral=True)
                return

            if custom_id == "ws_upload":
                session.upload_kind = "weapons"
                session.upload_armed = True
                session.upload_target = T_WEAPONS_TEX
                await interaction.response.send_message(
                    embed=upload_prompt_embed(session), view=upload_target_buttons(), ephemeral=True)
                return

            if custom_id.startswith("upload_target:"):
                session.upload_target = custom_id.split(":", 1)[1] or T_MODS
                session.upload_armed = True
                await interaction.response.edit_message(
                    embed=upload_prompt_embed(session, session.upload_target),
                    view=LayoutView([btn("upload_cancel", "✖ Anuluj", discord.ButtonStyle.danger)]))
                return

            if custom_id == "upload_cancel":
                session.upload_armed = False
                await interaction.response.edit_message(
                    embed=discord.Embed(title="✖ Anulowano",
                                        description="Własny plik nie został dodany.",
                                        color=C_BLUE), view=None)
                return

            if custom_id == "upload_done":
                await interaction.response.defer()
                if session.upload_kind == "weapons":
                    await send_skins_summary(interaction.channel, session)
                else:
                    await send_summary(interaction.channel, session)
                return

            if custom_id.startswith("citizen_jump:"):
                await interaction.response.defer()
                await send_step(interaction.channel, session, int(values[0]))
                return

            if custom_id == "citizen_summary":
                await interaction.response.defer()
                await send_summary(interaction.channel, session)
                return

            if custom_id == "citizen_restart":
                session.choices.clear()
                await interaction.response.defer()
                await send_step(interaction.channel, session, 0)
                return

            if custom_id == "citizen_finish":
                items = session.package_items("citizen")
                _kept, _dropped, conflicts = resolve_conflicts(session.chosen_steps())
                await interaction.response.defer()
                await deliver_package(interaction, session, items, "citizen", conflicts)
                return

            # --- Weapon Skin Studio ---
            if custom_id == "ws_category":
                await interaction.response.defer()
                await send_weapon_list(interaction.channel, session, values[0])
                return

            if custom_id.startswith("ws_weapon:"):
                category_id = custom_id.split(":", 1)[1]
                category = next((c for c in WEAPON_CATEGORIES if c["id"] == category_id), None)
                weapon = next((w for w in (category or {}).get("weapons", []) if w["id"] == values[0]), None)
                await interaction.response.defer()
                if weapon:
                    await send_skin_gallery(interaction.channel, session, weapon)
                return

            if custom_id.startswith("ws_skin_select:"):
                weapon = find_weapon(custom_id.split(":", 1)[1])
                if not weapon:
                    await interaction.response.defer()
                    return
                index = int(values[0])
                skin = weapon["skins"][index]
                profile = profile_by_id(session.user_id)
                level = profile.level if profile else 0
                if level < min_level_of(skin):
                    await interaction.response.send_message(
                        f"{lock_text(skin)}\n\nTwój poziom: **{level}**.", ephemeral=True)
                    return
                session.weapon_skins[weapon["id"]] = skin["id"]
                await show_skin(interaction, weapon, index, session, level)
                return

            if custom_id.startswith(("ws_prev:", "ws_next:")):
                action, weapon_id, index_str = custom_id.split(":")
                weapon = find_weapon(weapon_id)
                if not weapon:
                    await interaction.response.defer()
                    return
                total = len(weapon["skins"])
                index = int(index_str)
                index = (index + 1) % total if action == "ws_next" else (index - 1) % total
                await show_skin(interaction, weapon, index, session)
                return

            if custom_id.startswith("ws_page:"):
                _action, weapon_id, page_str = custom_id.split(":")
                weapon = find_weapon(weapon_id)
                if not weapon:
                    await interaction.response.defer()
                    return
                total_pages = page_count(len(weapon["skins"]), SKINS_PER_PAGE)
                page = max(0, min(int(page_str), total_pages - 1))
                index = page * SKINS_PER_PAGE
                chosen_id = session.weapon_skins.get(weapon["id"])
                if chosen_id:
                    for i, skin in enumerate(weapon["skins"]):
                        if skin["id"] == chosen_id and skin_page_of(i) == page:
                            index = i
                            break
                await show_skin(interaction, weapon, index, session)
                return

            if custom_id.startswith(("ws_choose:", "ws_locked:")):
                _action, weapon_id, index_str = custom_id.split(":")
                weapon = find_weapon(weapon_id)
                if not weapon:
                    await interaction.response.defer()
                    return
                index = int(index_str)
                skin = weapon["skins"][index]
                profile = profile_by_id(session.user_id)
                level = profile.level if profile else 0
                if level < min_level_of(skin):
                    await interaction.response.send_message(
                        f"{lock_text(skin)}\n\nTwój poziom: **{level}** — ekskluzywne skiny "
                        "odblokowują się wraz z rangą twórcy.", ephemeral=True)
                    return
                if session.weapon_skins.get(weapon["id"]) == skin["id"]:
                    session.weapon_skins.pop(weapon["id"], None)
                else:
                    session.weapon_skins[weapon["id"]] = skin["id"]
                await show_skin(interaction, weapon, index, session)
                return

            if custom_id == "ws_back_to_weapons":
                await interaction.response.defer()
                await send_category_menu(interaction.channel, session)
                return

            if custom_id == "ws_search_start":
                session.search_mode = True
                await interaction.response.defer()
                await send_search_prompt(interaction.channel)
                return

            if custom_id == "ws_search_stop":
                session.search_mode = False
                await interaction.response.defer()
                await interaction.channel.send("✖️ Tryb wyszukiwania wyłączony.")
                return

            if custom_id == "ws_search_pick":
                index = int(values[0])
                if index >= len(session.search_results):
                    await interaction.response.send_message("❌ Wyniki wygasły — wyszukaj ponownie.",
                                                           ephemeral=True)
                    return
                skin = session.search_results[index]
                if not is_rpf(skin.get("fileUrl", "")):
                    await interaction.response.send_message("❌ Ten plik nie jest .rpf — odrzucono.",
                                                           ephemeral=True)
                    return
                session.external_skins[skin.get("id") or f"ext-{index}"] = skin
                embed = discord.Embed(
                    title="✅ Skin dodany do paczki",
                    description=(f"**{skin.get('name', 'Skin')}** — {skin.get('description') or 'bez opisu'}\n"
                                 f"**Plik:** `{file_name_from_url(skin.get('fileUrl', ''))}` (tylko .rpf ✓)\n"
                                 f"**Autor:** {skin.get('author') or '—'}\n\n"
                                 "Kliknij **📦 Zakończ i zbuduj paczkę**, aby spakować."),
                    color=C_GREEN)
                if skin.get("imageUrl"):
                    embed.set_thumbnail(url=skin["imageUrl"])
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            if custom_id.startswith("ws_search_page:"):
                page = int(custom_id.split(":", 1)[1])
                await interaction.response.defer()
                await send_search_page(interaction.channel, session, page=page)
                return

            if custom_id.startswith("ws_quick_add:"):
                _action, weapon_id, index_str = custom_id.split(":")
                weapon = find_weapon(weapon_id)
                if not weapon:
                    await interaction.response.defer()
                    return
                index = max(0, min(int(index_str), len(weapon["skins"]) - 1))
                skin = weapon["skins"][index]
                profile = profile_by_id(session.user_id)
                level = profile.level if profile else 0
                if level < min_level_of(skin):
                    await interaction.response.send_message(
                        f"{lock_text(skin)}\n\nTwój poziom: **{level}**.", ephemeral=True)
                    return
                already = session.weapon_skins.get(weapon["id"]) == skin["id"]
                if already:
                    session.weapon_skins.pop(weapon["id"], None)
                else:
                    session.weapon_skins[weapon["id"]] = skin["id"]
                await interaction.response.send_message(
                    ("♻️ Usunięto z paczki: " if already else "✅ Dodano do paczki: ")
                    + f"**{weapon['name']} — {skin['name']}**\n"
                    "Paczkę zbudujesz przyciskiem **📦 Zakończ i zbuduj paczkę** w galerii.",
                    ephemeral=True)
                return

            if custom_id == "ws_summary":
                await interaction.response.defer()
                await send_skins_summary(interaction.channel, session)
                return

            if custom_id == "ws_finish":
                skins = session.collect_skins() + session.collect_uploads()
                await interaction.response.defer()
                await deliver_package(interaction, session, skins, "weapons", [])
                return

        except Exception as exc:  # noqa: BLE001
            where = locals().get("custom_id") or "interakcja"
            core_log.error("Blad interakcji (%s): %s", where, exc, exc_info=True)
            await report_user_error(interaction, exc, str(where))


bot = FoundryBot()

# ============================================================================
# 24. TICKETY I POMOCNICZE AKCJE
# ============================================================================


async def handle_take_role(interaction: discord.Interaction) -> None:
    """Przycisk 'Zaznacz się' — nadaje rolę Członek."""
    role = discord.utils.get(interaction.guild.roles, name=ROLE_MEMBER)
    if not role:
        await interaction.response.send_message("❌ Rola nie istnieje.", ephemeral=True)
        return
    try:
        await interaction.user.add_roles(role, reason="Self-role")
        await interaction.response.send_message("✅ Dostałeś rolę!", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ Bot nie ma uprawnień (przesuń jego rolę wyżej w hierarchii).", ephemeral=True)


async def handle_settings_toggle(interaction: discord.Interaction) -> None:
    """Przycisk w /ustawienia — włącz/wyłącz rekomendacje modów na priv."""
    profile = profile_get(interaction.user)
    if profile is None:
        await interaction.response.send_message("❌ Nie udało się wczytać profilu.", ephemeral=True)
        return
    profile.dm_opt_in = not profile.dm_opt_in
    profiles_save()
    state = "włączone ✅" if profile.dm_opt_in else "wyłączone ⛔"
    label = "⛔ Wyłącz rekomendacje na priv" if profile.dm_opt_in else "✅ Włącz rekomendacje na priv"
    embed = discord.Embed(
        title="⚙️ Ustawienia zaktualizowane",
        description=(f"Rekomendacje modów na priv: **{state}**\n\n"
                     + ("Bot będzie podsyłać mody dopasowane do Twoich wyborów."
                        if profile.dm_opt_in else
                        "Bot nie będzie już wysyłać Ci wiadomości prywatnych.")),
        color=C_GREEN if profile.dm_opt_in else C_YELLOW)
    await interaction.response.edit_message(
        embed=embed,
        view=LayoutView([btn("settings_toggle_dm", label,
                             discord.ButtonStyle.secondary if profile.dm_opt_in
                             else discord.ButtonStyle.success)]))


async def close_session(bot_instance: FoundryBot, session: Session, reason: str) -> None:
    """Zamyka kanał sesji, zdejmuje rolę tymczasową i czyści stan."""
    guild = bot_instance.get_guild(session.guild_id)
    session_close(session.channel_id)
    if not guild:
        return
    role = discord.utils.get(guild.roles, name=ROLE_BUILDING)
    member = guild.get_member(session.user_id)
    if role and member:
        try:
            await member.remove_roles(role, reason="Koniec sesji")
        except discord.HTTPException:
            pass
    channel = guild.get_channel(session.channel_id)
    if channel:
        try:
            await channel.delete(reason=reason)
        except discord.HTTPException:
            pass


async def create_ticket(interaction: discord.Interaction, start_mode: str) -> None:
    """Tworzy prywatny kanał sesji (ticket) dla użytkownika."""
    guild, user = interaction.guild, interaction.user
    existing = session_by_user(user.id, guild.id)
    if existing:
        await interaction.response.send_message(
            f"❌ Masz już otwartą sesję: <#{existing.channel_id}>. Użyj `/zamknij`.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    building_role = discord.utils.get(guild.roles, name=ROLE_BUILDING)
    tickets_category = discord.utils.get(guild.categories, name=CAT_TICKETS)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                          read_message_history=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                             read_message_history=True, manage_messages=True),
    }
    if building_role:
        overwrites[building_role] = discord.PermissionOverwrite(view_channel=False)

    safe_name = re.sub(r"[^a-z0-9-]", "-", user.name.lower())[:20] or "user"
    channel = await guild.create_text_channel(
        name=f"foundry-{safe_name}", category=tickets_category, overwrites=overwrites,
        topic=f"Prywatna sesja kreatora — {user}")

    if building_role:
        try:
            await user.add_roles(building_role, reason="Sesja kreatora")
        except discord.HTTPException:
            pass

    session = session_create(user.id, guild.id, channel.id)
    session.mode = start_mode
    session.build_id = DEFAULT_BUILD_ID

    # Creator Economy: profil, codzienne XP, ranga
    profile = profile_get(user)
    if profile is not None:
        daily = profile.touch_day()
        profiles_save()
        if daily:
            await award_xp(profile, "daily", channel, reason="pierwsza aktywność dnia")

    await interaction.followup.send(f"✅ Twój prywatny kanał: {channel.mention}")

    embed = discord.Embed(
        title=f"👋 Witaj {user.display_name}!",
        description=("To Twój **prywatny kanał Foundry** — nikt inny go nie widzi.\n\n"
                     + ("🔫 Tryb **Weapon Skin Studio** aktywny — poniżej menu."
                        if start_mode == "weapons"
                        else "🛠️ Tryb **Citizen Foundry** aktywny — poniżej menu.") +
                     "\n\n🛠️ **Citizen** — 24 opcje w 6 grupach (niebo, woda, cienie, pojazdy, potato, kombat)\n"
                     "🔫 **Skiny broni** — kategorie, galeria, wyszukiwarka .rpf\n"
                     "🖼️ **Podgląd kombinacji** — strona z Twoimi wyborami "
                     "(a gdy brak publicznego adresu — plik HTML przy paczce)\n"
                     f"🎮 **Build paczki:** {build_by_id(session.build_id)['name']}\n\n"
                     f"Przerwij: `/zamknij` lub przycisk 🔒 (auto-zamknięcie po "
                     f"{CHANNEL_CLEANUP_MINUTES} min od wygenerowania paczki)."),
        color=C_GREEN)
    if profile is not None:
        embed.add_field(name="🏅 Twoja ranga twórcy", value=profile.progress_line(), inline=False)
        locked = [s for s in CITIZEN_STEPS if profile.level < min_level_of(s)]
        if locked:
            names = ", ".join(s["name"].split(" (")[0] for s in locked[:4])
            embed.add_field(name=f"🔒 Ekskluzywne presety ({len(locked)})",
                            value=f"Czekają na wyższy poziom: {names}…\n"
                                  "Buduj paczki, aby zdobyć XP — szczegóły: `/profil`", inline=False)
    await channel.send(content=user.mention, embed=embed,
                       view=ticket_view(session, with_mode=(start_mode != "weapons")))

    if start_mode == "weapons":
        await send_category_menu(channel, session)


async def handle_build_pick(interaction: discord.Interaction, session: Session,
                            values: Sequence[str]) -> None:
    """Zmiana docelowego buildu GTA V (z podsumowania albo z kanału ticketa)."""
    session.build_id = values[0]
    build = build_by_id(session.build_id)
    title = ""
    if interaction.message and interaction.message.embeds:
        title = interaction.message.embeds[0].title or ""

    if "Podsumowanie Twojej paczki Citizen" in title:
        embed, conflicts = citizen_summary_embed(session)
        kept, _dropped, _conflicts = resolve_conflicts(session.chosen_steps())
        page = render_preview_html(kept, conflicts, build["name"], "Podgląd citizena")
        session.preview_token = STORAGE.register_preview(page, "Podgląd citizena", session.user_id)
        preview_live = public_preview_url(session.preview_token)
        embed.add_field(name="🖼️ Podgląd kombinacji (live)",
                        value=(f"[Otwórz podgląd w przeglądarce]({preview_live})" if preview_live
                               else "Plik HTML dołączymy do gotowej paczki "
                                    "(brak publicznego `PUBLIC_URL`)."))
        await interaction.response.edit_message(embed=embed, view=LayoutView(
            [btn("citizen_finish", "Zakończ tworzenie", discord.ButtonStyle.success, "📦"),
             btn("citizen_restart", "Zacznij od nowa", discord.ButtonStyle.secondary, "🔄"),
             btn("session_close", "Zamknij", discord.ButtonStyle.danger, "🔒")],
            [select("build_pick", "🎮 Docelowy build GTA V / FiveM...",
                    [opt(b["name"], b["id"], b["note"], default=(b["id"] == session.build_id))
                     for b in GAME_BUILDS])]))
        return

    if "Podsumowanie paczki skinów" in title:
        skins = session.collect_skins()
        uploads = session.collect_uploads()
        lines = [f"✅ **{s['name']}** — {s.get('description') or ''}" for s in skins]
        if uploads:
            lines += ["", f"📎 **Własne pliki ({len(uploads)}):**"]
            lines += [f"• `{u['name']}` → `{u['target']}`" for u in uploads[:15]]
        embed = discord.Embed(
            title="📋 Podsumowanie paczki skinów",
            description="\n".join(lines) or "*Nie wybrano żadnego skina.*", color=C_YELLOW)
        embed.add_field(name="🎮 Docelowy build GTA V", value=build["name"])
        embed.add_field(name="📦 Pozycji w paczce",
                        value=f"**{len(skins) + len(uploads)}** (skiny: {len(skins)}, własne: {len(uploads)})")
        link = publish_skins_preview(session, list(skins) + uploads)
        if link:
            embed.add_field(name="🖼️ Podgląd kombinacji (live)", value=f"[Otwórz podgląd]({link})")
        else:
            embed.add_field(name="🖼️ Podgląd kombinacji",
                            value="Plik HTML dołączymy do gotowej paczki.")
        await interaction.response.edit_message(embed=embed, view=LayoutView(*skin_nav_row()))
        return

    await interaction.response.send_message(f"✅ Docelowy build: **{build['name']}**", ephemeral=True)


def ghost_save_modal() -> discord.ui.Modal:
    """Modal zapisu obecnej struktury serwera jako szablonu."""
    modal = discord.ui.Modal(title="💾 Zapisz szablon serwera (Ghost Copy)",
                             custom_id="sys_save_modal")
    modal.add_item(discord.ui.TextInput(
        custom_id="sys_save_name", label="Nazwa szablonu", max_length=40,
        placeholder="np. fivem-community", required=True))
    return modal


async def handle_ghost_save_modal(interaction: discord.Interaction) -> None:
    """Zapisuje strukturę serwera do szablonu (Ghost Copy)."""
    if not is_authorized(interaction):
        await interaction.response.send_message("⛔ Brak uprawnień.", ephemeral=True)
        return
    name = parse_modal_value(interaction, "sys_save_name").strip()
    if not name:
        await interaction.response.send_message("❌ Podaj nazwę szablonu.", ephemeral=True)
        return
    await safe_defer(interaction, ephemeral=True, where="sys_save_modal")
    layout = export_guild_layout(interaction.guild)
    path = template_save(name, layout)
    await system_log(interaction.guild, "Ghost Copy — zapis szablonu", interaction.user,
                     f"{path.name}: {len(layout['roles'])} rol, {len(layout['categories'])} kategorii, "
                     f"{len(layout['channels'])} kanałów")
    await safe_reply(interaction, where="sys_save_modal", ephemeral=True, content=(
        f"💾 **Szablon zapisany:** `{path.stem}`\n"
        f"👥 Role: **{len(layout['roles'])}** • 🗂️ Kategorie: **{len(layout['categories'])}** "
        f"• 💬 Kanały: **{len(layout['channels'])}**\n\n"
        "Zastosuj go na innym serwerze przez `/ghost` → wybór z listy lub "
        f"`/ghost akcja:klonuj serwer:<ID>`."))


def ghost_apply_modal(name: str, roles: int, channels: int) -> discord.ui.Modal:
    """Modal potwierdzenia zastosowania szablonu."""
    modal = discord.ui.Modal(title=f"👻 Zastosuj szablon: {name[:40]}",
                             custom_id=f"sys_apply_modal:{name[:40]}")
    modal.add_item(discord.ui.TextInput(
        custom_id="sys_apply_text", label=f"Wpisz {COPY_CONFIRM_WORD}, aby potwierdzić",
        placeholder=f"Szablon ma {roles} rol i {channels} kanałów", max_length=20))
    return modal


async def handle_ghost_apply_modal(interaction: discord.Interaction, name: str) -> None:
    """Odtwarza strukturę z szablonu na obecnym serwerze."""
    if not is_authorized(interaction):
        await interaction.response.send_message("⛔ Brak uprawnień.", ephemeral=True)
        return
    typed = parse_modal_value(interaction, "sys_apply_text").strip().upper()
    layout = template_load(name)
    if layout is None:
        await interaction.response.send_message("❌ Szablon nie istnieje.", ephemeral=True)
        return
    if typed != COPY_CONFIRM_WORD:
        await interaction.response.send_message(
            f"❌ Potwierdzenie niepoprawne (`{typed}`) — musisz wpisać `{COPY_CONFIRM_WORD}`. "
            "Nic nie zmieniono.", ephemeral=True)
        return
    await safe_defer(interaction, ephemeral=True, where=f"sys_apply_modal:{name}")
    try:
        report = await apply_guild_layout(interaction.guild, layout,
                                          reason=f"Ghost Copy z szablonu {name} ({interaction.user})")
        sys_op_record(getattr(interaction, "guild_id", None), "apply_template", ok=True,
                      headline=(f"Szablon `{name}`: +{len(report['roles'])} rol, "
                                f"+{len(report['categories'])} kategorii, "
                                f"+{len(report['channels'])} kanałów"),
                      detail="\n".join(str(e) for e in (report.get("errors") or [])),
                      user_id=interaction.user.id, extra={"template": name})
        await system_log(interaction.guild, "Ghost Copy — zastosowano szablon", interaction.user,
                         f"{name}: +{len(report['roles'])} rol, +{len(report['categories'])} kategorii, "
                         f"+{len(report['channels'])} kanałów, błędy: {len(report['errors'])}")
        await safe_reply(interaction, where=f"sys_apply_modal:{name}", ephemeral=True,
                         embed=ghost_report_embed(f"👻 Szablon `{name}` zastosowany", report))
    except Exception as exc:  # noqa: BLE001
        sys_log.error("Blad Ghost Copy (szablon %s): %s", name, exc)
        record = sys_op_record(getattr(interaction, "guild_id", None), "apply_template",
                               ok=False, headline=f"Operacja przerwana: {exc}",
                               detail=str(exc), user_id=interaction.user.id,
                               extra={"template": name})
        await safe_reply(interaction, where=f"sys_apply_modal:{name}", ephemeral=True,
                         embed=sys_op_embed(record))


def ghost_clone_modal() -> discord.ui.Modal:
    """Modal klonowania struktury z innego serwera (po ID)."""
    modal = discord.ui.Modal(title="👻 Sklonuj strukturę innego serwera",
                             custom_id="sys_clone_modal")
    modal.add_item(discord.ui.TextInput(
        custom_id="sys_clone_guild", label="ID serwera źródłowego",
        placeholder="np. 123456789012345678 (bot musi na nim być)", max_length=24))
    modal.add_item(discord.ui.TextInput(
        custom_id="sys_clone_name", label="Zapisz też jako szablon (opcjonalnie)",
        placeholder="np. wzor-community", max_length=40, required=False))
    modal.add_item(discord.ui.TextInput(
        custom_id="sys_clone_text", label=f"Wpisz {COPY_CONFIRM_WORD}, aby potwierdzić", max_length=20))
    return modal


async def handle_ghost_clone_modal(interaction: discord.Interaction) -> None:
    """Klonuje strukturę innego serwera na obecny (wymaga bota na obu)."""
    if not is_authorized(interaction):
        await interaction.response.send_message("⛔ Brak uprawnień.", ephemeral=True)
        return
    typed = parse_modal_value(interaction, "sys_clone_text").strip().upper()
    if typed != COPY_CONFIRM_WORD:
        await interaction.response.send_message(
            f"❌ Potwierdzenie niepoprawne — wpisz `{COPY_CONFIRM_WORD}`. Nic nie zmieniono.",
            ephemeral=True)
        return
    raw_id = parse_modal_value(interaction, "sys_clone_guild").strip()
    save_as = parse_modal_value(interaction, "sys_clone_name").strip()
    try:
        source_id = int(re.sub(r"[^0-9]", "", raw_id))
    except ValueError:
        await interaction.response.send_message("❌ To nie wygląda na ID serwera.", ephemeral=True)
        return
    await safe_defer(interaction, ephemeral=True, where="sys_clone_modal")
    source = bot.get_guild(source_id)
    if source is None:
        await safe_reply(interaction, where="sys_clone_modal", ephemeral=True, content=(
            "❌ Bot nie jest na tym serwerze — dodaj go tam i spróbuj ponownie "
            "(albo zapisz strukturę jako szablon tam, gdzie bot jest, i użyj `/ghost`)."))
        return
    try:
        report = await clone_guild_structure(source, interaction.guild, interaction.user, save_as)
        sys_op_record(getattr(interaction, "guild_id", None), "clone_guild", ok=True,
                      headline=(f"Klon z {source.name} ({source.id}): "
                                f"+{len(report['roles'])} rol, +{len(report['channels'])} kanałów"),
                      detail="\n".join(str(e) for e in (report.get("errors") or [])),
                      user_id=interaction.user.id,
                      extra={"source": source.id, "save_as": save_as})
        await system_log(interaction.guild, "Ghost Copy — klon z innego serwera", interaction.user,
                         f"źródło: {source.name} ({source.id}), +{len(report['roles'])} rol, "
                         f"+{len(report['channels'])} kanałów")
        await safe_reply(interaction, where="sys_clone_modal", ephemeral=True,
                         embed=ghost_report_embed(f"👻 Sklonowano strukturę z {source.name}", report))
    except Exception as exc:  # noqa: BLE001
        sys_log.error("Blad Ghost Copy (klon z %s): %s", source_id, exc)
        record = sys_op_record(getattr(interaction, "guild_id", None), "clone_guild", ok=False,
                               headline=f"Operacja przerwana: {exc}", detail=str(exc),
                               user_id=interaction.user.id,
                               extra={"source": source_id, "save_as": save_as})
        await safe_reply(interaction, where="sys_clone_modal", ephemeral=True,
                         embed=sys_op_embed(record))


def reset_confirm_modal() -> discord.ui.Modal:
    """Modal potwierdzenia resetu (wspólny dla ⚠️ Reset i ↻ Ponów operację)."""
    modal = discord.ui.Modal(title="⚠️ Potwierdzenie resetu serwera", custom_id="sys_reset_modal")
    modal.add_item(discord.ui.TextInput(
        custom_id="sys_reset_text", label="Wpisz POTWIERDZAM wielkimi literami",
        style=discord.TextStyle.short, min_length=11, max_length=11,
        placeholder="POTWIERDZAM", required=True))
    return modal


async def handle_system_button(interaction: discord.Interaction, custom_id: str,
                               values: Sequence[str] = ()) -> None:
    """Obsługa przycisków panelu /system (z autoryzacją i logowaniem)."""
    if not is_authorized(interaction):
        await system_log(interaction.guild, "Próba akcji /system bez uprawnień",
                         interaction.user, custom_id)
        await interaction.response.send_message("⛔ Brak uprawnień.", ephemeral=True)
        return

    if custom_id == "sys_refresh":
        embed = system_panel_embed(interaction.guild, interaction.user)
        view = system_panel_view(template_list())
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.HTTPException as exc:
            # np. wiadomość panelu już nie istnieje — wysyłamy panel od nowa
            sys_log.warning("Odświeżenie panelu nieudane: %s", exc)
            await safe_reply(interaction, embed=embed, view=view, ephemeral=True,
                             where=custom_id)
        return

    if custom_id == "sys_template_save":
        await safe_modal(interaction, ghost_save_modal(), where=custom_id)
        return

    if custom_id == "sys_clone_from":
        await safe_modal(interaction, ghost_clone_modal(), where=custom_id)
        return

    if custom_id == "sys_template_pick":
        value = str(values[0]) if values else ""
        name = value.split(":", 1)[1] if ":" in value else ""
        layout = template_load(name)
        if not layout:
            await interaction.response.send_message("❌ Szablon nie istnieje.", ephemeral=True)
            return
        await safe_modal(interaction,
                         ghost_apply_modal(name, len(layout.get("roles") or []),
                                           len(layout.get("channels") or [])),
                         where=custom_id)
        return

    if custom_id == "sys_build_design":
        await run_design_build(interaction, custom_id)
        return

    if custom_id == "sys_last_op":
        await handle_last_op(interaction)
        return

    if custom_id == "sys_repeat_last":
        await handle_repeat_last(interaction)
        return

    if custom_id == "sys_reset_start":
        embed = discord.Embed(
            title="⚠️ UWAGA — Operacja NIEODWRACALNA",
            description=("Zamierzasz usunąć **całą strukturę serwera stworzoną przez bota**:\n\n"
                         "• Kategorie: START, CITIZEN FOUNDRY, WEAPON SKIN STUDIO, MOD FEED, TWOJE PACZKI,\n"
                         "  oraz estetyczne (🌐・OGÓLNE, 🎨・KREATORY itd.)\n"
                         "• Wszystkie kanały w tych kategoriach\n"
                         f"• Role: {ROLE_MEMBER}, {ROLE_CREATOR}, {ROLE_BUILDING}\n\n"
                         "**To NIE usuwa**: kanałów spoza listy ani własnych kanałów administracji.\n\n"
                         "**Aby potwierdzić, kliknij 🔴 Potwierdzam i wpisz `POTWIERDZAM`** w okienku."),
            color=C_RED)
        await safe_reply(interaction, embed=embed, ephemeral=True, where=custom_id,
                         view=LayoutView([
                             btn("sys_reset_confirm", "Potwierdzam — chcę reset",
                                 discord.ButtonStyle.danger, "🔴"),
                             btn("sys_reset_cancel", "Anuluj", discord.ButtonStyle.secondary, "✖️"),
                         ]))
        return

    if custom_id == "sys_reset_cancel":
        await system_log(interaction.guild, "Reset anulowany przez użytkownika", interaction.user)
        try:
            await interaction.response.edit_message(content="✖️ Reset anulowany.",
                                                    embed=None, view=None)
        except discord.HTTPException as exc:
            sys_log.warning("Anulowanie resetu — nie edytowano wiadomości: %s", exc)
            await safe_reply(interaction, content="✖️ Reset anulowany.", ephemeral=True,
                             where=custom_id)
        return

    if custom_id == "sys_reset_confirm":
        await safe_modal(interaction, reset_confirm_modal(), where=custom_id)
        return


async def handle_reset_modal(interaction: discord.Interaction) -> None:
    """Krok 3 resetu: weryfikacja wpisanego słowa POTWIERDZAM."""
    if not is_authorized(interaction):
        await interaction.response.send_message("⛔ Brak uprawnień.", ephemeral=True)
        return
    typed = parse_modal_value(interaction, "sys_reset_text").strip().upper()
    if typed != "POTWIERDZAM":
        await interaction.response.send_message(
            f"❌ Niepoprawne potwierdzenie: `{typed}`. Reset anulowany.", ephemeral=True)
        return
    # Kanał, z którego kliknięto reset, zostaje — inaczej nie mamy gdzie
    # wysłać podsumowania (Discord: 400/10003 Unknown Channel).
    keep_channel_id = interaction.channel_id
    await safe_defer(interaction, ephemeral=True, where="sys_reset_modal")
    try:
        results = await reset_server(interaction.guild, interaction.user, keep_channel_id)
        record = sys_op_record(getattr(interaction, "guild_id", None), "reset", ok=True,
                               headline=f"Usunięto {len(results)} elementów struktury bota",
                               detail="\n".join(results), user_id=interaction.user.id)
        await safe_reply(interaction, embed=sys_op_embed(record), ephemeral=False,
                         where="sys_reset_modal")
    except Exception as exc:  # noqa: BLE001
        sys_log.error("Blad resetu: %s", exc)
        record = sys_op_record(getattr(interaction, "guild_id", None), "reset", ok=False,
                               headline=f"Reset przerwany: {exc}", detail=str(exc),
                               user_id=interaction.user.id)
        await safe_reply(interaction, embed=sys_op_embed(record), ephemeral=True,
                         where="sys_reset_modal")


async def run_design_build(interaction: discord.Interaction, where: str = "sys_build_design") -> None:
    """
    Buduje estetyczny design i zapisuje raport.

    Ten sam kod obsługuje 🎨 z panelu i ↻ „Ponów operację”, więc po zniknięciu
    kanału admin odzyskuje wynik jednym klikiem.
    """
    if interaction_channel_gone(interaction):
        sys_log.warning("Kanał akcji %s już nie istnieje — wynik pójdzie fallbackiem.", where)
    await safe_defer(interaction, ephemeral=True, where=where)
    try:
        results = await build_aesthetic_design(interaction.guild, interaction.user)
        record = sys_op_record(getattr(interaction, "guild_id", None), "build_design", ok=True,
                               headline=f"Wykonano {len(results)} operacji",
                               detail="\n".join(results), user_id=interaction.user.id,
                               extra={"count": len(results)})
        await safe_reply(interaction, embed=sys_op_embed(record), ephemeral=False, where=where)
    except Exception as exc:  # noqa: BLE001
        sys_log.error("Blad budowania designu: %s", exc)
        record = sys_op_record(getattr(interaction, "guild_id", None), "build_design", ok=False,
                               headline=f"Operacja przerwana: {exc}", detail=str(exc),
                               user_id=interaction.user.id)
        # Raport błędu trafia też na kanał logów, żeby nie zginął razem z kanałem akcji
        await system_log(interaction.guild, "Zbuduj estetyczny design — BŁĄD",
                         interaction.user, str(exc)[:500])
        await safe_reply(interaction, embed=sys_op_embed(record), ephemeral=True, where=where)


async def handle_last_op(interaction: discord.Interaction) -> None:
    """🔁 Raport ostatniej operacji /system (ratunek po 10003 Unknown Channel)."""
    if not is_authorized(interaction):
        await safe_reply(interaction, content="⛔ Brak uprawnień.", where="sys_last_op")
        return
    record = sys_op_last(getattr(interaction, "guild_id", None))
    if not record:
        await safe_reply(interaction, where="sys_last_op", content=(
            "📭 **Brak zapisanej operacji na tym serwerze.**\n"
            "Raport pojawi się tutaj po 🎨 designie, ⚠️ resecie albo 👻 Ghost Copy."))
        return
    await safe_reply(interaction, embed=sys_op_embed(record), view=sys_op_view(record),
                     ephemeral=True, where="sys_last_op")


async def handle_repeat_last(interaction: discord.Interaction) -> None:
    """↻ Ponawia ostatnią operację /system (reset zawsze wymaga wpisania POTWIERDZAM)."""
    if not is_authorized(interaction):
        await safe_reply(interaction, content="⛔ Brak uprawnień.", where="sys_repeat_last")
        return
    record = sys_op_last(getattr(interaction, "guild_id", None))
    action = (record or {}).get("action")
    if not action:
        await safe_reply(interaction, where="sys_repeat_last",
                         content="📭 Nie ma czego ponawiać — brak zapisanej operacji.")
        return

    if action == "build_design":
        await run_design_build(interaction, where="sys_repeat_last")
        return

    if action == "reset":
        # Reset jest nieodwracalny — ponowienie też wymaga wpisania POTWIERDZAM.
        await safe_modal(interaction, reset_confirm_modal(), where="sys_repeat_last")
        return

    extra = record.get("extra") or {}
    if action == "apply_template":
        name = str(extra.get("template") or "")
        layout = template_load(name) if name else None
        if not layout:
            await safe_reply(interaction, where="sys_repeat_last", content=(
                f"❌ Szablon `{name or '?'}` już nie istnieje — zapisz go ponownie "
                "przyciskiem 💾, a potem zastosuj z listy."))
            return
        await safe_modal(interaction,
                         ghost_apply_modal(name, len(layout.get("roles") or []),
                                           len(layout.get("channels") or [])),
                         where="sys_repeat_last")
        return

    if action == "clone_guild":
        await safe_modal(interaction, ghost_clone_modal(), where="sys_repeat_last")
        return

    await safe_reply(interaction, where="sys_repeat_last",
                     content="❌ Tej operacji nie da się ponowić automatycznie.")


async def announce_build_change(previous_id: str, new_id: str) -> None:
    """Powiadamia kanały modów, że paczki wymagają regeneracji."""
    previous = build_by_id(previous_id)
    new_build = build_by_id(new_id)
    embed = discord.Embed(
        title="🔔 Zmiana wersji gry — paczki wymagają aktualizacji",
        description=(f"**Poprzedni build:** {previous['name']}\n"
                     f"**Nowy build:** {new_build['name']}\n\n"
                     "Nowy patch GTA V / FiveM może psuć starsze citizeny i mody klienckie.\n"
                     "**Wygeneruj paczki ponownie** — bot zapisze w nich nowy build w `manifest.json`."),
        color=C_YELLOW, timestamp=datetime.now(timezone.utc))
    for guild in bot.guilds:
        channel = find_channel(guild, CAT_MODS, CH_MODS_LIVE)
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass
    build_state_set(new_id, "announce")


async def sweeper_loop(bot_instance: FoundryBot) -> None:
    """Sprzątanie: TTL paczek, sesji i auto-zamykanie kanałów."""
    await bot_instance.wait_until_ready()
    while not bot_instance.is_closed():
        try:
            STORAGE.sweep()
            approvals_sweep()
            now = time.time()
            for session in list(SESSIONS.values()):
                if session.delivered_at and now - session.delivered_at > CHANNEL_CLEANUP_MINUTES * 60:
                    core_log.info("Auto-zamkniecie kanalu sesji user=%s", session.user_id)
                    await close_session(bot_instance, session, "Auto-zamknięcie po generowaniu paczki")
                elif now - session.last_activity > SESSION_TTL_MINUTES * 60:
                    core_log.warning("Sesja wygasla user=%s", session.user_id)
                    await close_session(bot_instance, session, "Sesja wygasła (bezczynność)")
        except Exception as exc:  # noqa: BLE001
            core_log.error("Blad sweepera: %s", exc)
            await notify_error("Błąd pętli sprzątania", "Garbage collector zgłosił wyjątek.", exc,
                               "sweeper_loop")
        await asyncio.sleep(120)

# ============================================================================
# 25. KOMENDY SLASH
# ============================================================================


@bot.tree.command(name="panel", description="Wysyła panel kreatora citizena na ten kanał")
@app_commands.default_permissions(administrator=True)
async def cmd_panel(interaction: discord.Interaction) -> None:
    """Panel Citizen Foundry (admin)."""
    embed = discord.Embed(
        title="🏭 Citizen Foundry — FiveM",
        description=(f"Kliknij przycisk poniżej, aby rozpocząć tworzenie paczki klienckiej.\n"
                     f"{len(CITIZEN_STEPS)} opcji w 6 grupach + podgląd kombinacji + paczka ZIP."),
        color=C_BLUE)
    await interaction.response.send_message(
        embed=embed, view=LayoutView([
            btn("create_citizen", "Zacznij tworzyć citizena", discord.ButtonStyle.primary, "🛠️")]))


@bot.tree.command(name="panel_skins", description="Wysyła panel kreatora skinów broni")
@app_commands.default_permissions(administrator=True)
async def cmd_panel_skins(interaction: discord.Interaction) -> None:
    """Panel Weapon Skin Studio (admin)."""
    embed = discord.Embed(
        title="🔫 Weapon Skin Studio",
        description="Kliknij przycisk poniżej, aby rozpocząć personalizację broni.",
        color=C_PURPLE)
    await interaction.response.send_message(
        embed=embed, view=LayoutView([
            btn("create_weapon_skins", "Stwórz skiny broni", discord.ButtonStyle.primary, "🔫")]))


async def skin_autocomplete(interaction: discord.Interaction,
                           current: str) -> List[app_commands.Choice[str]]:
    """Autocomplete skinów broni — szukanie w locie bez wpisywania pełnej nazwy."""
    needle = (current or "").strip().lower()
    choices: List[app_commands.Choice[str]] = []
    for weapon in all_weapons():
        for index, skin in enumerate(weapon["skins"]):
            label = f"{weapon['name']} — {skin['name']}"
            haystack = f"{label} {weapon['id']} {skin['id']} {skin['description']}".lower()
            if needle and needle not in haystack:
                continue
            choices.append(app_commands.Choice(name=label[:100], value=f"{weapon['id']}:{index}"))
            if len(choices) >= 25:
                return choices
    return choices


@bot.tree.command(name="skin", description="Znajdź skin broni z podglądem (autocomplete)")
@app_commands.describe(skin="Zacznij pisać nazwę broni lub skina (np. ak47, chrome)...")
@app_commands.autocomplete(skin=skin_autocomplete)
async def cmd_skin(interaction: discord.Interaction, skin: str) -> None:
    """Szybkie znalezienie skina: podgląd + jednym klikiem dodanie do paczki."""
    try:
        weapon_id, index_str = skin.split(":", 1)
        index = int(index_str)
    except ValueError:
        await interaction.response.send_message("❌ Wybierz skin z listy podpowiedzi.", ephemeral=True)
        return
    weapon = find_weapon(weapon_id)
    if not weapon or not 0 <= index < len(weapon["skins"]):
        await interaction.response.send_message("❌ Nie znaleziono tego skina.", ephemeral=True)
        return
    chosen = weapon["skins"][index]
    session = session_get(interaction.channel_id)
    embed = discord.Embed(
        title=f"🔫 {weapon['name']} — {chosen['name']}",
        description=(f"{chosen['description']}\n\n"
                     f"**Plik:** `{chosen['file_name']}`\n"
                     f"**Lokalizacja w grze:** `{chosen['target']}`"),
        color=C_PURPLE)
    embed.set_image(url=chosen["image"])
    view: Optional[discord.ui.View] = None
    if session and session.user_id == interaction.user.id:
        embed.set_footer(text="Kliknij poniżej, aby dodać tego skina do swojej paczki.")
        view = LayoutView([btn(f"ws_quick_add:{weapon['id']}:{index}", "➕ Dodaj do mojej paczki",
                               discord.ButtonStyle.success)])
    else:
        embed.set_footer(text="Otwórz kreatora (/panel), aby zbudować paczkę z tym skinem.")
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def step_autocomplete(interaction: discord.Interaction,
                           current: str) -> List[app_commands.Choice[str]]:
    """Autocomplete kroków kreatora citizena (nazwa opcji lub grupa)."""
    needle = (current or "").strip().lower()
    choices: List[app_commands.Choice[str]] = []
    for index, step in enumerate(CITIZEN_STEPS):
        label = f"{short_group(step['group'])}: {step['name']}"
        if needle and needle not in f"{label} {step['description']}".lower():
            continue
        choices.append(app_commands.Choice(name=label[:100], value=str(index)))
        if len(choices) >= 25:
            break
    return choices


@bot.tree.command(name="krok", description="Przeskocz do wybranego kroku kreatora citizena (autocomplete)")
@app_commands.describe(krok="Zacznij pisać nazwę opcji (np. cienie, potato, krew)...")
@app_commands.autocomplete(krok=step_autocomplete)
async def cmd_step(interaction: discord.Interaction, krok: str) -> None:
    """Skok do konkretnego kroku w aktywnej sesji — zamiast klikać „Pomiń” 20 razy."""
    session = session_get(interaction.channel_id)
    if not session or session.user_id != interaction.user.id:
        await interaction.response.send_message(
            "❌ Ta komenda działa w Twoim prywatnym kanale sesji (otwórz go przyciskiem w /panel).",
            ephemeral=True)
        return
    index = max(0, min(int(krok), len(CITIZEN_STEPS) - 1))
    await interaction.response.defer()
    await send_step(interaction.channel, session, index)


@bot.tree.command(name="skanuj", description="Wymusza skan najnowszych modów z YouTube")
@app_commands.default_permissions(administrator=True)
async def cmd_scan(interaction: discord.Interaction) -> None:
    """Ręczny skan YouTube (admin)."""
    await interaction.response.defer()
    await run_scan(bot, interaction)


@bot.tree.command(name="zamknij", description="Zamyka Twoją sesję kreatora na tym kanale")
async def cmd_close(interaction: discord.Interaction) -> None:
    """Zamknięcie kanału sesji (właściciel sesji)."""
    session = session_get(interaction.channel_id)
    if not session:
        await interaction.response.send_message("❌ To nie jest kanał sesji.", ephemeral=True)
        return
    await interaction.response.send_message("🔒 Zamykam sesję (kanał zniknie za 3 s)...", ephemeral=True)
    await asyncio.sleep(3)
    await close_session(bot, session, "Koniec sesji (/zamknij)")


@bot.tree.command(name="status", description="Statystyki bota (kolejka, sesje, paczki, build)")
async def cmd_status(interaction: discord.Interaction) -> None:
    """Statystyki bota."""
    stats = STORAGE.stats()
    cache = FILE_CACHE.stats()
    disk = STORAGE.disk_usage()
    queue = ZIP_QUEUE.info()
    megabytes = lambda value: f"{value / 1024 / 1024:.1f} MB"  # noqa: E731
    embed = discord.Embed(
        title="📊 Status FiveM Mod Foundry",
        description=(f"⚙️ **Kolejka ZIP:** {queue['completed']} wykonanych, {queue['failed']} nieudanych "
                     f"• teraz {queue['running']}/{queue['concurrency']}, czeka {queue['waiting']}\n"
                     f"📦 Paczki aktywne: **{stats['packages']}** • podglądy: **{stats['previews']}**\n"
                     f"👥 Sesje aktywne: **{len(SESSIONS)}**\n"
                     f"🔐 Zgłoszenia bezpieczeństwa: **{len(approvals_pending())}** oczekujących\n"
                     f"🎮 Docelowy build: **{build_by_id(DEFAULT_BUILD_ID)['name']}**\n"
                     f"🧩 Opcji citizena: **{len(CITIZEN_STEPS)}** • "
                     f"🔫 broni: **{len(all_weapons())}** ({len(WEAPON_CATEGORIES)} kategorie)\n\n"
                     f"🗃️ **Cache plików:** {cache['files']} plików ({megabytes(cache['bytes'])}) — "
                     f"hity: {cache['hits']}, pobrania: {cache['misses']}\n"
                     f"🏅 **Twórcy (XP):** {len(PROFILES)} profili • "
                     f"tokeny paczek: **{len(PACK_TOKENS)}** • priorytetowe zadania: "
                     f"{queue['priority_jobs']}\n"
                     f"🧹 **Dysk:** paczki {megabytes(disk['downloads'])}, "
                     f"sesje {megabytes(disk['workspaces'])}, cache {megabytes(disk['cache'])}, "
                     f"logi {megabytes(disk['logs'])}\n"
                     f"♻️ GC: {stats['gc_runs']} cykli, usunięto {stats['deleted']} paczek "
                     f"({megabytes(stats['freed_bytes'])} zwolnione)\n\n"
                     f"🛡️ **Watchdog 24/7:** {'🟢 aktywny' if WATCHDOG_ENABLED else '🔴 wyłączony'} • "
                     f"restarty: **{WATCHDOG_RESTARTS}** • ostatnia awaria: "
                     f"{WATCHDOG_LAST_CRASH.splitlines()[0][:60] if WATCHDOG_LAST_CRASH else 'brak'}"),
        color=C_BLUE)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="profil", description="Twój profil twórcy: ranga, XP, odznaki i preferencje")
@app_commands.describe(uzytkownik="Sprawdź profil innego gracza (opcjonalnie)")
async def cmd_profile(interaction: discord.Interaction,
                      uzytkownik: Optional[discord.Member] = None) -> None:
    """Profil twórcy — XP, ranga, odznaki, preferencje i historia paczek."""
    target = uzytkownik or interaction.user
    profile = profile_get(target)
    if profile is None:
        await interaction.response.send_message("❌ Nie udało się wczytać profilu.", ephemeral=True)
        return
    profiles_save()
    next_rank = profile.next_rank()
    embed = discord.Embed(
        title=f"🏅 Profil twórcy — {target.display_name if hasattr(target, 'display_name') else target}",
        description=profile.progress_line(), color=C_PURPLE)
    embed.add_field(name="📊 Statystyki", inline=True, value=(
        f"📦 Paczki: **{profile.builds}**\n"
        f"🔫 Skiny: **{profile.skins_picked}**\n"
        f"🔎 Szukania .rpf: **{profile.searches}**\n"
        f"🛡️ Zgłoszenia: **{profile.reports}**"))
    embed.add_field(name="🎯 Twoje preferencje", inline=False, value=(
        ", ".join(f"{tag} ({count})" for tag, count in
                  sorted(profile.preferences.items(), key=lambda kv: kv[1], reverse=True)[:5])
        or "*jeszcze brak — zbuduj pierwszą paczkę*"))
    embed.add_field(name="🏆 Odznaki", value=profile.badges_text(), inline=False)
    if next_rank:
        embed.add_field(name="🔓 Następna ranga", value=(
            f"**{next_rank['name']}** przy {next_rank['xp']} XP\n{next_rank['perk']}"), inline=False)
    if profile.history:
        last = profile.history[0]
        when = datetime.fromtimestamp(last.get("at", 0), timezone.utc)
        embed.add_field(name="🕒 Ostatnia paczka", value=(
            f"`{last.get('kind')}` • build `{last.get('build')}` • "
            f"{len(last.get('items') or [])} pozycji • <t:{int(when.timestamp())}:R>"), inline=False)
    dm_state = "włączone" if profile.dm_opt_in else "wyłączone"
    embed.set_footer(text=f"Rekomendacje modów na priv: {dm_state} • zmień komendą /ustawienia")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="xp", description="Nadaj lub odejmij XP graczowi — @mention, nie lista")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(gracz="@mention lub ID gracza (nawet jeśli nie jest na serwerze)",
                       ilosc="Ile XP dodać (+) lub odjąć (−)", powod="Krótka nota")
async def cmd_xp(interaction: discord.Interaction, gracz: str,
                  ilosc: app_commands.Range[int, -5000, 5000],
                  powod: str = "korekta zarządu") -> None:
    user_id = _id_from_handle(gracz)
    try:
        target = await interaction.client.fetch_user(user_id)
    except Exception:
        target = None

    if isinstance(interaction.guild, discord.Guild):
        server_target = interaction.guild.get_member(user_id) or target
    else:
        server_target = target

    target = target if server_target is None else server_target

    if target is None:
        await interaction.response.send_message(
            f"❌ Nie znalazłem gracza `{gracz}` — sprawdź ID lub użyj @mention.", ephemeral=True)
        return

    profile = profile_get(target)
    if profile is None:
        await interaction.response.send_message("❌ Nie udało się wczytać profilu.", ephemeral=True)
        return

    message = profile.add_xp("manual", amount=int(ilosc))
    profile.reports += 1 if ilosc < 0 else 0
    profiles_save()

    mention = getattr(target, "mention", str(target))
    if hasattr(target, "name"):
        mention += f" ({target.name})"
    await system_log(interaction.guild, "Korekta XP", interaction.user,
                     f"{mention}: {ilosc:+} XP — {powod}")

    text = (f"✅ {mention}: **{ilosc:+} XP** — {powod}\n"
            f"Teraz: **{profile.xp} XP** (ranga {profile.rank['name']}, poziom {profile.level})")
    if message:
        text += f"\n{message}"
    await interaction.response.send_message(text)


def _id_from_handle(handle: str) -> int:
    h = handle.strip()
    if h.startswith("<@!") and h.endswith(">"):
        return int(h[3:-1])
    if h.startswith("<@"):
        return int(h[2:-1])
    m = re.fullmatch(r"0*([1-9][0-9]{0,18})", h)
    if m:
        return int(m.group(1))
    raise ValueError("To nie wygląda na ID gracza (powinno być @mention lub cyferki).")


@bot.tree.command(name="ustawienia", description="Ustawienia profilu: rekomendacje modów na priv")
async def cmd_settings(interaction: discord.Interaction) -> None:
    """Panel ustawień twórcy (np. wyłączenie smart pingów)."""
    profile = profile_get(interaction.user)
    if profile is None:
        await interaction.response.send_message("❌ Nie udało się wczytać profilu.", ephemeral=True)
        return
    profiles_save()
    state = "włączone ✅" if profile.dm_opt_in else "wyłączone ⛔"
    embed = discord.Embed(
        title="⚙️ Twoje ustawienia twórcy",
        description=(f"**Rekomendacje modów na priv:** {state}\n\n"
                     "Bot pamięta Twoje wybory w kreatorze (np. POTATO + optymalizacja, "
                     "krew anime, dźwięki bass) i gdy skaner YouTube znajdzie nowy mod "
                     "pasujący do Twojego stylu — wyśle Ci go na priv.\n\n"
                     "Zmienisz to przyciskiem poniżej (`/profil` pokaże Twoje preferencje)."),
        color=C_BLUE)
    label = "⛔ Wyłącz rekomendacje na priv" if profile.dm_opt_in else "✅ Włącz rekomendacje na priv"
    await interaction.response.send_message(
        embed=embed, ephemeral=True,
        view=LayoutView([btn("settings_toggle_dm", label,
                             discord.ButtonStyle.secondary if profile.dm_opt_in
                             else discord.ButtonStyle.success)]))


@bot.tree.command(name="exp", description="Nadaj lub odejmij XP graczowi (ID/mention) — bez listy wybierania")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(gracz="ID lub @mention gracza — nie musi być na tym serwerze",
                       ilosc="Ile XP dodać (+) lub odjąć (−)", powod="Krótka nota")
async def cmd_exp_new_style(interaction: discord.Interaction, gracz: str,
                          ilosc: app_commands.Range[int, -5000, 5000],
                          powod: str = "korekta zarządu") -> None:
    user_id = _id_from_handle(gracz)
    try:
        target = await interaction.client.fetch_user(user_id)
    except Exception:
        target = None

    if isinstance(interaction.guild, discord.Guild):
        server_target = interaction.guild.get_member(user_id) or target
    else:
        server_target = target

    target = target if server_target is None else server_target

    if target is None:
        await interaction.response.send_message(
            f"❌ Nie znalazłem gracza `{gracz}` — sprawdź ID albo użyj @mention.", ephemeral=True)
        return

    profile = profile_get(target)
    if profile is None:
        await interaction.response.send_message("❌ Nie udało się wczytać profilu.", ephemeral=True)
        return

    message = profile.add_xp("manual", amount=int(ilosc))
    profile.reports += 1 if ilosc < 0 else 0
    profiles_save()

    mention = getattr(target, "mention", str(target))
    if hasattr(target, "name"):
        mention += f" ({target.name})"
    await system_log(interaction.guild, "Korekta XP", interaction.user,
                     f"{mention}: {ilosc:+} XP — {powod}")

    text = (f"✅ {mention}: **{ilosc:+} XP** — {powod}\n"
            f"Teraz: **{profile.xp} XP** (ranga {profile.rank['name']}, poziom {profile.level})")
    if message:
        text += f"\n{message}"
    await interaction.response.send_message(text)


@bot.tree.command(name="pakiet", description="Sprawdź token paczki (kto ją wygenerował) — admin")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(token="Token z paczki, np. FM-1A2B3C4D")
async def cmd_pack_lookup(interaction: discord.Interaction, token: str) -> None:
    """Weryfikacja pochodzenia paczki po tokenie (podpis HMAC)."""
    record = pack_token_get(token.strip().upper())
    if not record:
        await interaction.response.send_message("❌ Nie znam takiego tokenu paczki.", ephemeral=True)
        return
    items = record.get("items") or []
    embed = discord.Embed(
        title=f"🎫 Token {record['token']}",
        description=("✅ Podpis zgodny — paczka pochodzi z tego bota." if record.get("valid")
                     else "⛔ **Podpis niezgodny** — token został zmodyfikowany!"),
        color=C_GREEN if record.get("valid") else C_RED)
    embed.add_field(name="Twórca", value=f"<@{record.get('user_id')}> (`{record.get('user_id')}`)")
    embed.add_field(name="Ranga", value=f"{record.get('rank')} (poziom {record.get('level')})")
    embed.add_field(name="Typ / build", value=f"{record.get('kind')} • `{record.get('build')}`")
    embed.add_field(name="Pozycje", value="\n".join(f"• {i.get('name')}" for i in items[:10]) or "—")
    embed.add_field(name="Utworzono", value=f"<t:{record.get('created_at')}:R>")
    embed.set_footer(text="Ten sam wynik zwraca API: /api/pack/<token>")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="cache", description="Cache plików bazowych: status, zapas, czyszczenie (admin)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(akcja="Co zrobić z cache plików")
@app_commands.choices(akcja=[
    app_commands.Choice(name="Status cache", value="status"),
    app_commands.Choice(name="Pobierz zapas plików (szybsze paczki)", value="prefetch"),
    app_commands.Choice(name="Wyczyść cache", value="clear"),
])
async def cmd_cache(interaction: discord.Interaction, akcja: app_commands.Choice[str]) -> None:
    """Zarządzanie lokalnym cache plików bazowych (bez ponownego pobierania z netu)."""
    await interaction.response.defer(ephemeral=True)
    if akcja.value == "clear":
        freed = FILE_CACHE.clear()
        await system_log(interaction.guild, "Wyczyszczono cache plików", interaction.user,
                         f"zwolniono {freed / 1024 / 1024:.1f} MB")
        await interaction.followup.send(
            f"🧹 Cache wyczyszczony — zwolniono **{freed / 1024 / 1024:.1f} MB**.\n"
            "Pliki zostaną pobrane ponownie przy najbliższej potrzebie.", ephemeral=True)
        return

    if akcja.value == "prefetch":
        await interaction.followup.send("⏳ Pobieram zapas plików do cache (zajmie chwilę)...",
                                       ephemeral=True)
        result = await precache_items()
        cache = FILE_CACHE.stats()
        await interaction.followup.send(
            f"✅ Pre-cache gotowy: **{result['ok']}** pobranych, **{result['failed']}** błędów, "
            f"**{result['skipped']}** już było.\n"
            f"Na dysku: **{cache['files']}** plików ({cache['bytes'] / 1024 / 1024:.1f} MB).",
            ephemeral=True)
        return

    cache = FILE_CACHE.stats()
    await interaction.followup.send(
        f"🗃️ **Cache:** {'włączony' if cache['enabled'] else 'wyłączony'} (TTL {cache['ttl_hours']} h)\n"
        f"Plików: **{cache['files']}** ({cache['bytes'] / 1024 / 1024:.1f} MB)\n"
        f"Trafienia / pobrania z sieci: **{cache['hits']} / {cache['misses']}**",
        ephemeral=True)


@bot.tree.command(name="czysc", description="Ręczne sprzątanie dysku: ZIP-y, sesje, cache (admin)")
@app_commands.default_permissions(administrator=True)
async def cmd_clean(interaction: discord.Interaction) -> None:
    """Uruchamia Garbage Collector na żądanie i pokazuje, ile miejsca zwolnił."""
    await interaction.response.defer(ephemeral=True)
    before = STORAGE.disk_usage()
    report = STORAGE.sweep()
    after = STORAGE.disk_usage()
    freed = max(0, sum(before.values()) - sum(after.values()))
    await system_log(interaction.guild, "Ręczne sprzątanie dysku", interaction.user,
                     f"usunięto {report['removed']} paczek, zwolniono {freed / 1024 / 1024:.1f} MB")
    await interaction.followup.send(
        f"🧹 **Sprzątanie zakończone.**\n"
        f"Usunięte paczki: **{report['removed']}**\n"
        f"Zwolnione miejsce: **{freed / 1024 / 1024:.1f} MB** "
        f"(w tym cache: {report['cache_freed_bytes'] / 1024 / 1024:.1f} MB)\n"
        f"Dysk bota teraz: **{sum(after.values()) / 1024 / 1024:.1f} MB**", ephemeral=True)


@bot.tree.command(name="build", description="Ustawia docelowy build GTA V dla nowych paczek")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(wersja="Docelowa wersja gry")
@app_commands.choices(wersja=[app_commands.Choice(name=b["name"][:100], value=b["id"])
                              for b in GAME_BUILDS])
async def cmd_build(interaction: discord.Interaction, wersja: app_commands.Choice[str]) -> None:
    """Zmiana aktywnego buildu GTA V (admin)."""
    global DEFAULT_BUILD_ID
    previous = DEFAULT_BUILD_ID
    DEFAULT_BUILD_ID = wersja.value
    build_state_set(DEFAULT_BUILD_ID, str(interaction.user))
    await system_log(interaction.guild, "Zmiana buildu GTA V", interaction.user,
                     f"{previous} -> {DEFAULT_BUILD_ID}")
    await interaction.response.send_message(
        f"✅ Docelowy build ustawiony na: **{build_by_id(DEFAULT_BUILD_ID)['name']}**.\n"
        "Nowe sesje będą generować paczki pod ten build.", ephemeral=True)
    if previous != DEFAULT_BUILD_ID:
        embed = discord.Embed(
            title="🔔 Zmieniono build paczek",
            description=(f"**Było:** {build_by_id(previous)['name']}\n"
                         f"**Jest:** {build_by_id(DEFAULT_BUILD_ID)['name']}\n\n"
                         "Paczki wygenerowane pod poprzedni build mogą wymagać regeneracji."),
            color=C_YELLOW)
        channel = find_channel(interaction.guild, CAT_MODS, CH_MODS_LIVE)
        if channel:
            await channel.send(embed=embed)


@bot.tree.command(name="system", description="Panel zarządzania serwerem (właściciel/Admin)")
@app_commands.default_permissions(administrator=True)
async def cmd_system(interaction: discord.Interaction) -> None:
    """Panel /system: design serwera + Ghost Copy + reset + logi audytowe."""
    if not is_authorized(interaction):
        await system_log(interaction.guild, "Próba /system bez uprawnień", interaction.user,
                         f"ID: {interaction.user.id}")
        await interaction.response.send_message(
            "⛔ Tylko właściciel serwera lub Administrator może używać /system.", ephemeral=True)
        return
    await interaction.response.send_message(
        embed=system_panel_embed(interaction.guild, interaction.user),
        view=system_panel_view(template_list()), ephemeral=True)


@bot.tree.command(name="ghost", description="Ghost Copy: zapisz/sklonuj strukturę serwera (admin)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(akcja="panel / lista / zapisz / zastosuj / klonuj",
                       nazwa="Nazwa szablonu (dla zapisz/zastosuj)",
                       serwer="ID serwera źródłowego (dla klonuj)")
@app_commands.choices(akcja=[
    app_commands.Choice(name="Panel Ghost Copy", value="panel"),
    app_commands.Choice(name="Lista szablonów", value="lista"),
    app_commands.Choice(name="Zapisz ten serwer jako szablon", value="zapisz"),
    app_commands.Choice(name="Zastosuj szablon", value="zastosuj"),
    app_commands.Choice(name="Sklonuj z innego serwera", value="klonuj"),
])
async def cmd_ghost(interaction: discord.Interaction,
                    akcja: Optional[app_commands.Choice[str]] = None,
                    nazwa: str = "", serwer: str = "") -> None:
    """Ghost Copy: pełny klon struktury serwera (role, kategorie, kanały, uprawnienia)."""
    if not is_authorized(interaction):
        await system_log(interaction.guild, "Próba /ghost bez uprawnień", interaction.user,
                         f"ID: {interaction.user.id}")
        await interaction.response.send_message("⛔ Brak uprawnień.", ephemeral=True)
        return

    action = akcja.value if akcja else "panel"
    if action == "panel":
        embed = discord.Embed(
            title="👻 Ghost Copy — klonowanie serwera",
            description=("**Co potrafi Ghost Copy:**\n"
                         "💾 zapisuje całą strukturę (role z uprawnieniami, kategorie, kanały, "
                         "nadpisania, tematy) jako szablon JSON,\n"
                         "👻 odtwarza ją na dowolnym serwerze — role, permisje i układ 1:1,\n"
                         "🌐 potrafi sklonować strukturę innego serwera, na którym jest bot.\n\n"
                         f"**Zapisane szablony ({len(template_list())}):** "
                         + (", ".join(f"`{n}`" for n in template_list()[:8]) if template_list()
                            else "*brak*")
                         + "\n\nKażda operacja wymaga wpisania "
                           f"`{COPY_CONFIRM_WORD}` i jest logowana."),
            color=C_PURPLE)
        await interaction.response.send_message(embed=embed, view=system_panel_view(template_list()),
                                                ephemeral=True)
        return

    if action == "lista":
        names = template_list()
        lines = []
        for name in names[:20]:
            layout = template_load(name) or {}
            source = (layout.get("source") or {}).get("name", "?")
            lines.append(f"• `{name}` — z **{source}**, {len(layout.get('roles') or [])} rol, "
                         f"{len(layout.get('categories') or [])} kategorii, "
                         f"{len(layout.get('channels') or [])} kanałów")
        await interaction.response.send_message(
            embed=discord.Embed(title=f"📁 Szablony Ghost Copy ({len(names)})",
                                description="\n".join(lines) or "*Brak szablonów — zapisz pierwszy.*",
                                color=C_BLUE), ephemeral=True)
        return

    if action == "zapisz":
        if not nazwa:
            await interaction.response.send_message("❌ Podaj nazwę: `/ghost akcja:zapisz nazwa:moj-szablon`.",
                                                    ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        layout = export_guild_layout(interaction.guild)
        path = template_save(nazwa, layout)
        await system_log(interaction.guild, "Ghost Copy — zapis szablonu", interaction.user, path.name)
        await interaction.followup.send(
            f"💾 Szablon `{path.stem}` zapisany ({len(layout['roles'])} rol, "
            f"{len(layout['channels'])} kanałów).", ephemeral=True)
        return

    if action == "zastosuj":
        if not nazwa:
            await interaction.response.send_message("❌ Podaj nazwę szablonu: `/ghost akcja:zastosuj nazwa:...`.",
                                                    ephemeral=True)
            return
        layout = template_load(nazwa)
        if not layout:
            await interaction.response.send_message("❌ Nie znam takiego szablonu.", ephemeral=True)
            return
        await interaction.response.send_modal(
            ghost_apply_modal(nazwa, len(layout.get("roles") or []), len(layout.get("channels") or [])))
        return

    if action == "klonuj":
        if not re.sub(r"[^0-9]", "", serwer or ""):
            await interaction.response.send_message("❌ Podaj ID serwera: `/ghost akcja:klonuj serwer:123...`.",
                                                    ephemeral=True)
            return
        await interaction.response.send_modal(ghost_clone_modal())
        return

# ============================================================================
# 26. START
# ============================================================================


def main() -> None:
    """Walidacja konfiguracji i start bota."""
    problems = []
    if not DISCORD_TOKEN:
        problems.append("DISCORD_TOKEN — token bota z Discord Developer Portal")
    if not CLIENT_ID:
        problems.append("CLIENT_ID — Application ID z Discord Developer Portal")
    if problems:
        print("\n❌ BRAK KONFIGURACJI w pliku .env:")
        for problem in problems:
            print(f"   • {problem}")
        print("\n👉 Skopiuj .env.example do .env i uzupełnij wartości.")
        print("   Instrukcja: README.md / START-TUTAJ.txt\n")
        raise SystemExit(1)

    if not YOUTUBE_API_KEY:
        core_log.warning("Brak YOUTUBE_API_KEY — live feed YouTube nieaktywny.")
    if public_url_is_public():
        core_log.info("Adres publiczny bota: %s (źródło: %s)", PUBLIC_URL, PUBLIC_URL_SOURCE)
    else:
        core_log.warning(
            "PUBLIC_URL = %s wskazuje localhost — linki /download/ i /preview/ nie zadziałają "
            "u graczy. Paczki i podglądy będą wysyłane jako załączniki Discorda "
            "(fallback działa od razu). Ustaw PUBLIC_URL na publiczny adres bota, np. "
            "https://twoj-bot.onrender.com — szczegóły w START-TUTAJ.txt.", PUBLIC_URL)
    if not SKIN_INDEX_URL or "twoj-user" in SKIN_INDEX_URL:
        core_log.warning("Brak SKIN_INDEX_URL — wyszukiwarka skinów .rpf będzie pusta.")

    core_log.info("Startuję FiveM Mod Foundry (Python)...")
    try:
        bot.run(DISCORD_TOKEN, log_handler=None)
    except discord.LoginFailure:
        core_log.error("Niepoprawny DISCORD_TOKEN — sprawdź token w .env.")
        raise SystemExit(1)


# ----------------------------------------------------------------------------
# WATCHDOG 24/7 — bot ZAWSZE włączony (całość w kodzie, zero zewnętrznych skryptów)
#
#   • awaria / crash / utrata internetu   -> restart po WATCHDOG_RESTART_DELAY s
#   • brak tokenów lub zły token w .env   -> czeka WATCHDOG_CONFIG_DELAY s,
#     PRZEŁADOWUJE .env i próbuje dalej (wpiszesz tokeny = bot sam wstaje)
#   • czyste zamknięcie bez Ctrl+C        -> też restart (bot nigdy sam nie gaśnie)
#   • godzinny heartbeat do logs/bot.log  -> widać, że bot cały czas żyje
#   • licznik restartów + ostatnia awaria widoczne w komendzie /status
#   • JEDYNY sposób zatrzymania: Ctrl+C w oknie bota
#   • wyłączenie watchdoga: WATCHDOG_ENABLED=0 w .env
# ----------------------------------------------------------------------------

WATCHDOG_ENABLED = os.getenv("WATCHDOG_ENABLED", "1").strip().lower() not in ("0", "false", "no")
WATCHDOG_RESTART_DELAY = max(5, int(os.getenv("WATCHDOG_RESTART_DELAY", "15") or 15))
WATCHDOG_CONFIG_DELAY = max(30, int(os.getenv("WATCHDOG_CONFIG_DELAY", "60") or 60))
WATCHDOG_HEARTBEAT_MINUTES = max(0, int(os.getenv("WATCHDOG_HEARTBEAT_MINUTES", "60") or 60))

WATCHDOG_STARTED_AT = time.time()
WATCHDOG_RESTARTS = 0
WATCHDOG_LAST_CRASH: str = ""
_STOP_REQUESTED = False  # flaga Ctrl+C (discord.py połyka KeyboardInterrupt)

try:  # noqa: E402 — sygnały są dostępne tylko na pełnym interpreterze
    import signal
except ImportError:  # pragma: no cover
    signal = None  # type: ignore[assignment]


def _watchdog_sigint(signum: int, frame: Any) -> None:
    """Ctrl+C ustawia flagę stopu — jedyny legalny sposób wyłączenia bota."""
    global _STOP_REQUESTED
    _STOP_REQUESTED = True


def _watchdog_reload_env() -> bool:
    """
    Przeładowuje .env i odświeża tokeny w globalnych zmiennych.
    Zwraca True, gdy konfiguracja wygląda kompletna.
    Dzięki temu bot podniesie się sam, gdy user dopisze tokeny do .env.
    """
    global DISCORD_TOKEN, CLIENT_ID, YOUTUBE_API_KEY, SKIN_INDEX_URL
    load_dotenv(override=True)
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
    CLIENT_ID = os.getenv("CLIENT_ID", "").strip()
    YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
    SKIN_INDEX_URL = os.getenv("SKIN_INDEX_URL", "").strip()
    return bool(DISCORD_TOKEN and CLIENT_ID)


async def _heartbeat_loop() -> None:
    """Godzinny heartbeat do logu — świadczy, że bot cały czas działa."""
    interval = max(1, WATCHDOG_HEARTBEAT_MINUTES) * 60
    await asyncio.sleep(30)
    while True:
        uptime_h = (time.time() - WATCHDOG_STARTED_AT) / 3600
        last = (WATCHDOG_LAST_CRASH.splitlines() or ["brak"])[0][:100]
        core_log.info("Watchdog heartbeat: bot działa, uptime %.1f h, restarty: %s, ostatnia awaria: %s",
                      uptime_h, WATCHDOG_RESTARTS, last)
        await asyncio.sleep(interval)


def _watchdog() -> None:
    """Uruchamia bota w nieskończonej pętli — nigdy nie zostaje wyłączony."""
    global WATCHDOG_RESTARTS, WATCHDOG_LAST_CRASH
    if signal is not None:
        try:
            signal.signal(signal.SIGINT, _watchdog_sigint)
        except (ValueError, OSError):  # pragma: no cover — nie w głównym wątku
            pass
    attempt = 0
    _watchdog_reload_env()
    while True:
        attempt += 1
        config_problem = False
        try:
            main()
            # bot.run() zwrócił bez wyjątku — gdy to NIE był Ctrl+C, podnosimy dalej
            if _STOP_REQUESTED:
                core_log.warning(
                    "Watchdog: zatrzymano ręcznie (Ctrl+C) — kończę. Uptime: %.1f h, restarty: %s.",
                    (time.time() - WATCHDOG_STARTED_AT) / 3600, WATCHDOG_RESTARTS)
                return
            core_log.warning("Watchdog: bot został zamknięty bez Ctrl+C — podnoszę go ponownie.")
        except KeyboardInterrupt:
            if _STOP_REQUESTED:
                core_log.warning("Watchdog: zatrzymano ręcznie (Ctrl+C) — kończę.")
                return
            core_log.warning("Watchdog: przerwano bez flagi stopu — podnoszę bota ponownie.")
        except SystemExit as exc:
            # Brak tokenów / zły token: NIE poddajemy się — czekamy na poprawkę .env
            # i próbujemy dalej (przed kolejną próbą przeładowujemy .env).
            config_problem = True
            WATCHDOG_LAST_CRASH = f"SystemExit({exc.code})"
            core_log.error(
                "Watchdog: problem z konfiguracją (kod %s) — czekam na poprawkę .env "
                "i ponawiam próbę co %s s. Bot pozostaje włączony.",
                exc.code, WATCHDOG_CONFIG_DELAY)
        except Exception:
            WATCHDOG_RESTARTS += 1
            WATCHDOG_LAST_CRASH = traceback.format_exc(limit=3)
            core_log.error("Watchdog: awaria #%s:\n%s", attempt, WATCHDOG_LAST_CRASH)

        if not WATCHDOG_ENABLED:
            core_log.error("Watchdog wyłączony (WATCHDOG_ENABLED=0) — kończę po awarii.")
            return

        delay = WATCHDOG_CONFIG_DELAY if config_problem else WATCHDOG_RESTART_DELAY
        _watchdog_reload_env()               # świeże tokeny z .env bez restartu komputera
        if config_problem and DISCORD_TOKEN and CLIENT_ID:
            core_log.info("Watchdog: .env wygląda uzupełniony — restartuję natychmiast.")
            delay = 1
        core_log.warning("Watchdog: restart bota za %s s (próba #%s, dotychczasowe restarty: %s).",
                         delay, attempt, WATCHDOG_RESTARTS)
        time.sleep(delay)


if __name__ == "__main__":
    _watchdog()
