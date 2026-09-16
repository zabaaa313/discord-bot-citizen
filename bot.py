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

 Wymagane zmienne w .env: DISCORD_TOKEN, CLIENT_ID, YOUTUBE_API_KEY, PUBLIC_URL
==============================================================================
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import json
import logging
import os
import random
import re
import shutil
import sys
import time
import traceback
import zipfile
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

load_dotenv()

# ============================================================================
# 1. KONFIGURACJA
# ============================================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
CLIENT_ID = os.getenv("CLIENT_ID", "").strip()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
HTTP_PORT = int(os.getenv("HTTP_PORT", "3000") or 3000)
PUBLIC_URL = (os.getenv("PUBLIC_URL") or f"http://localhost:{HTTP_PORT}").rstrip("/")
SKIN_INDEX_URL = os.getenv("SKIN_INDEX_URL", "").strip()

YT_SCAN_MINUTES = int(os.getenv("YT_SCAN_MINUTES", "15") or 15)
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
STEPS_PER_PAGE = max(5, int(os.getenv("STEPS_PER_PAGE", "24") or 24))

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

IMG_BASE = "https://i.imgur.com/"          # <-- PODMIEŃ na swoje zdjęcia
FILE_BASE = "https://example.com/presets/"  # <-- PODMIEŃ na swoje pliki modów

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
        "image": f"{IMG_BASE}{image}.jpeg",
        "file_url": f"{FILE_BASE}{url}",
        "file_name": file_name,
        "target": target,
    }


CITIZEN_STEPS: List[Dict[str, str]] = [
    # ---- GRUPA 1: ŚRODOWISKO ----
    _step(G1, "sky-clear", "Czyste niebo", "Jasne, czyste niebo bez mgły. +2-5 FPS.", "SKY_CLEAR", "sky_clear.xml", "timecycle_mod_1.xml", T_TIMECYCLE),
    _step(G1, "sky-dark", "Ciemne nocne niebo", "Gwiazdy i głęboka czerń w nocy. Bez wpływu na FPS — czysta estetyka.", "SKY_DARK", "sky_dark.xml", "timecycle_mod_1.xml", T_TIMECYCLE),
    _step(G1, "sun-soft", "Miękkie słońce (bez flary)", "Redukuje oślepiającą flarę i promienie. Lepszy komfort jazdy na wschód.", "SUN_SOFT", "sun_soft.xml", "timecycle_mod_2.xml", T_TIMECYCLE),
    _step(G1, "clouds-off", "Usuń chmury", "Płaskie niebo bez chmur. +3-7 FPS (mniej alpha-blend warstw).", "CLOUDS_OFF", "clouds_off.rpf", "cloudhats.rpf", "mods/x64c.rpf/levels/gta5"),
    # ---- GRUPA 2: WODA ----
    _step(G2, "water-clear", "Przezroczysta woda", "Czysta woda bez zieleniny. ~0 FPS, lepszy look przy wybrzeżu.", "WATER_CLEAR", "water_clear.xml", "water.xml", T_WATER),
    _step(G2, "water-fps", "Woda FPS boost", "Uproszczone fale i refleksy. +5-10 FPS nad wodą.", "WATER_FPS", "water_fps.xml", "water.xml", T_WATER),
    _step(G2, "colors-vivid", "Nasycone kolory", "Żywsze barwy otoczenia. 0 FPS — tylko korekcja kolorów.", "COLORS_VIVID", "colors_vivid.xml", "timecycle_mod_3.xml", T_TIMECYCLE),
    # ---- GRUPA 3: CIENIE ----
    _step(G3, "shadows-total", "Cienie TOTAL OFF", "Zero cieni (najbardziej agresywne). +20-35 FPS na słabszych GPU.", "SHADOWS_TOTAL", "shadows_total.xml", "shaders.xml", T_DATA),
    _step(G3, "shadows-partial", "Cienie PARTIAL (tylko postacie)", "Zostawia cienie postaci, usuwa resztę. +10-18 FPS, wygląda naturalnie.", "SHADOWS_PARTIAL", "shadows_partial.xml", "shaders.xml", T_DATA),
    _step(G3, "postfx-clean", "PostFX czyste", "Usuwa bloom/blur/chromatic aberration. +3-8 FPS i czytelniejszy obraz.", "POSTFX_CLEAN", "postfx_clean.xml", "postfx.xml", T_DATA),
    # ---- GRUPA 4: POJAZDY ----
    _step(G4, "props-remove", "Usuń niepotrzebne propsy z mapy", "Krzaki, śmieci, pudła — +8-15 FPS w centrum miasta.", "PROPS_OFF", "props_remove.rpf", "props_remove.rpf", "mods/update/x64/dlcpacks"),
    _step(G4, "windows-invisible", "Szyby niewidzialne", "Brak szyb w pojazdach (przezroczyste). +5-12 FPS przy dużym ruchu.", "WINDOWS_INVIS", "windows_invisible.ytd", "vehicle_shatter.ytd", "mods/x64e.rpf/models/cdimages/vehicles"),
    _step(G4, "tire-smoke-off", "Usuń dym spod opon", "Zero tire smoke (drift/hamowanie). +3-6 FPS przy driftach.", "TIRE_SMOKE_OFF", "tire_smoke_off.rpf", "vehiclefx.rpf", "mods/x64e.rpf/graphics"),
    _step(G4, "fire-sparks-off", "Usuń ogień i iskry", "Brak efektów ognia po wypadkach. +4-9 FPS w strzelaninach.", "FIRE_OFF", "fire_sparks_off.rpf", "vehicle_firefx.rpf", "mods/x64e.rpf/graphics"),
    # ---- GRUPA 5: POTATO ----
    _step(G5, "potato-full", "POTATO FULL (cała mapa plastelina)", "Tekstury budynków/terenu na low-poly. +25-50 FPS. Skiny broni i postaci zostają HD!", "POTATO_FULL", "potato_full.rpf", "potato_full.rpf", T_MODS),
    _step(G5, "potato-terrain", "POTATO tylko teren (trawa, krzaki, ulice)", "Uproszczenie natury i dróg. +12-22 FPS. Budynki zostają normalne.", "POTATO_TERRAIN", "potato_terrain.rpf", "potato_terrain.rpf", T_MODS),
    _step(G5, "grass-off", "Usuń trawę i krzaki", "Zero trawy (tylko ziemia/asfalt). +6-14 FPS w Los Santos.", "GRASS_OFF", "grass_off.rpf", "grass_off.rpf", T_MODS),
    # ---- GRUPA 6: KOMBAT ----
    _step(G6, "sound-bass", "Dźwięki broni bass boost", "Głębsze, mocniejsze strzały. 0 FPS — tylko audio.", "SOUND_BASS", "sound_bass.rpf", "weapon_sounds_bass.rpf", T_MODS),
    _step(G6, "sound-decibels", "Dźwięki cichsze (decybele down)", "Łagodniejsze dla uszu przy długich sesjach.", "SOUND_DECIBELS", "sound_decibels.rpf", "weapon_sounds_soft.rpf", T_MODS),
    _step(G6, "blood-anime", "Krew ANIME (kaskada)", "Efektowne tryskanie krwi jak w anime. Koszt FPS: ~2.", "BLOOD_ANIME", "blood_anime.dat", "bloodfx.dat", T_EFFECTS),
    _step(G6, "blood-minimal", "Krew mała kropka (minimal)", "Ledwie widoczna kropka. +1-3 FPS przy strzelaninach.", "BLOOD_MINIMAL", "blood_minimal.dat", "bloodfx.dat", T_EFFECTS),
    _step(G6, "blood-none", "Brak krwi", "Zero efektów krwi. +2-5 FPS i czystszy ekran.", "BLOOD_NONE", "blood_none.dat", "bloodfx.dat", T_EFFECTS),
    _step(G6, "hitmarker-custom", "Hitmarkery custom", "Wyraźne, kolorowe hitmarkery przy trafieniu. 0 FPS.", "HITMARKER", "hitmarkers.rpf", "hitmarkers.rpf", T_MODS),
    _step(G6, "crosshair-custom", "Crosshair custom", "Zmieniony celownik (kropka/krzyżyk, wybrany kolor).", "CROSSHAIR", "crosshair.rpf", "crosshair.rpf", T_MODS),
]

# ============================================================================
# 3. DANE: SKINY BRONI (.ytd/.ydr)
# ============================================================================

SKIN_BASE = "https://example.com/skins/"  # <-- PODMIEŃ na swoje pliki skinów


def _skin(sid: str, name: str, desc: str, image: str, url: str, file_name: str,
          target: str = T_WEAPONS_TEX) -> Dict[str, str]:
    """Buduje definicję jednego skina broni."""
    return {
        "id": sid,
        "name": name,
        "description": desc,
        "image": f"{IMG_BASE}{image}.jpeg",
        "file_url": f"{SKIN_BASE}{url}",
        "file_name": file_name,
        "target": target,
    }


WEAPON_CATEGORIES: List[Dict[str, Any]] = [
    {
        "id": "pistols",
        "name": "🔫 Pistolety",
        "weapons": [
            {"id": "pistol", "name": "Pistol", "skins": [
                _skin("pistol-blackops", "Black Ops", "Matowa czerń + zielone akcenty.", "PISTOL_BLACKOPS", "pistol_blackops.ytd", "w_pi_pistol.ytd"),
                _skin("pistol-desert", "Desert Tan", "Pustynny kamuflaż.", "PISTOL_DESERT", "pistol_desert.ytd", "w_pi_pistol.ytd"),
            ]},
            {"id": "heavypistol", "name": "Heavy Pistol", "skins": [
                _skin("heavypistol-chrome", "Chrome", "Chromowany połysk.", "HEAVY_CHROME", "heavypistol_chrome.ytd", "w_pi_histol.ytd"),
            ]},
            {"id": "appistol", "name": "AP Pistol", "skins": [
                _skin("appistol-carbon", "Carbon Fiber", "Węglowy wzór.", "AP_CARBON", "appistol_carbon.ytd", "w_pi_ap_pistol.ytd"),
            ]},
        ],
    },
    {
        "id": "smg",
        "name": "💥 SMG",
        "weapons": [
            {"id": "microsmg", "name": "Micro SMG", "skins": [
                _skin("microsmg-redline", "Redline", "Czerwone paski na czerni.", "MICRO_REDLINE", "microsmg_redline.ytd", "w_sb_microsmg.ytd"),
            ]},
            {"id": "smg", "name": "SMG", "skins": [
                _skin("smg-woodland", "Woodland", "Leśny kamuflaż.", "SMG_WOODLAND", "smg_woodland.ytd", "w_sb_smg.ytd"),
            ]},
        ],
    },
    {
        "id": "rifles",
        "name": "🎯 Karabiny",
        "weapons": [
            {"id": "carbine", "name": "Carbine Rifle", "skins": [
                _skin("carbine-tan", "Desert Tan", "Pustynny kamuflaż.", "CARBINE_TAN", "carbine_tan.ytd", "w_ar_carbine.ytd"),
            ]},
            {"id": "ak47", "name": "AK-47 (Assault Rifle)", "skins": [
                _skin("ak47-redline", "Redline", "Czerwone linie na czerni.", "AK_REDLINE", "ak47_redline.ytd", "w_ar_assaultrifle.ytd"),
            ]},
        ],
    },
    {
        "id": "shotguns",
        "name": "🦆 Strzelby",
        "weapons": [
            {"id": "pumpshotgun", "name": "Pump Shotgun", "skins": [
                _skin("pump-gold", "Gold Edition", "Złote wykończenie.", "PUMP_GOLD", "pump_gold.ytd", "w_sg_pumpshotgun.ytd"),
            ]},
        ],
    },
]

# ============================================================================
# 4. DANE: LIVE YOUTUBE FEED
# ============================================================================

YT_QUERIES: List[str] = [
    "FiveM FPS boost",
    "FiveM optimization mod rpf",
    "FiveM low end pc mods",
    "FiveM LagFix",
    "FiveM low poly citizen",
    "FiveM first person mod",
    "FiveM first person rpf",
    "FiveM potato graphics",
    "FiveM potato mod rpf",
    "FiveM weapon skins",
    "FiveM gun skins pack",
    "FiveM graphics mod rpf",
    "FiveM visual settings",
    "FiveM PvP map opti",
    "FiveM client side map",
    "FiveM car mods client side",
]

YT_CATEGORIES: List[Tuple[str, Tuple[str, ...]]] = [
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

ALLOW_EXT = {".rpf", ".ytd", ".ydr", ".yft", ".ymt", ".dat", ".xml", ".meta", ".txt", ".json", ".ini", ".cfg"}
REVIEW_EXT = {".asi", ".zip", ".rar", ".7z", ".oiv", ".cab"}
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


def file_key(item: Dict[str, str]) -> str:
    """Ścieżka docelowa pliku w paczce."""
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


def render_preview_html(items: Sequence[Dict[str, Any]], conflicts: Sequence[Dict[str, Any]] = (),
                        build: str = "", title: str = "Podgląd kombinacji") -> str:
    """Buduje stronę HTML z dokładnie wybraną kombinacją modyfikacji."""
    cards = []
    for item in items:
        tag = f'<span class="tag">{html.escape(str(item.get("group") or ""))}</span>' if item.get("group") else ""
        image = f'<img src="{html.escape(str(item.get("image") or ""))}" alt="podglad">' if item.get("image") else ""
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
        self.build_id = DEFAULT_BUILD_ID
        self.preview_token: Optional[str] = None
        self.created_at = time.time()
        self.last_activity = time.time()
        self.delivered_at: Optional[float] = None

    def touch(self) -> None:
        self.last_activity = time.time()

    def chosen_steps(self) -> List[Dict[str, str]]:
        """Wybrane kroki citizena w kolejności wyboru."""
        return [step for step in CITIZEN_STEPS if step["id"] in self.choices]

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
    if message and channel is not None:
        try:
            await channel.send(message)
        except discord.HTTPException:
            pass
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

        received = 0
        with open(dest, "wb") as fh:
            async for chunk in response.content.iter_chunked(64 * 1024):
                received += len(chunk)
                if received > MAX_DOWNLOAD_BYTES:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    raise ValueError(f"Plik przekracza limit {MAX_DOWNLOAD_MB} MB")
                fh.write(chunk)
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


async def process_items(workspace: Path, items: Sequence[Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    Buduje pliki we workspace: z lokalnego cache (natychmiast) albo z sieci.
    Liczy SHA-256 każdego pliku (manifest + HASHES.txt w paczce).
    """
    hashes: List[Dict[str, Any]] = []
    async with aiohttp.ClientSession(headers={"User-Agent": "FiveMModFoundry/2.0"}) as http:
        for item in items:
            url = item["file_url"]
            file_name = resolve_file_name(item)
            dest = workspace / item["target"] / file_name
            dest.parent.mkdir(parents=True, exist_ok=True)
            source = FILE_CACHE.lookup(url)
            if source is not None:
                fp_log.info("Cache HIT: %s -> %s", url, dest.relative_to(workspace))
            else:
                fp_log.info("Pobieram (raz, potem z cache): %s", url)
                source = await fetch_to_cache(http, url)
            await asyncio.to_thread(shutil.copyfile, source, dest)
            digest, size = sha256_file(dest)
            rel = dest.relative_to(workspace).as_posix()
            hashes.append({"path": rel, "sha256": digest, "size": size})
            fp_log.info("  ✓ %s (%.1f KB)", file_name, size / 1024)
            item["file_name"] = file_name
    return hashes


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
            hashes = await process_items(build_dir, items)
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
                    "pack_token": (token_record or {}).get("token")}
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
    link = f"{PUBLIC_URL}/download/{token}"
    session.delivered_at = time.time()

    lines = [
        f"**Pobierz:** [{result['zip_path'].name}]({link})",
        "",
        f"📦 Rozmiar: **{result['size'] / 1024 / 1024:.2f} MB**",
        f"📁 Plików: {result['file_count']}",
        f"🎮 Build: **{build['name']}**",
        f"🕒 Link ważny: **{DOWNLOAD_TTL_MINUTES} minut**",
        "",
        "**Instalacja:** rozpakuj i postępuj według `INSTRUKCJA.txt` "
        "(w paczce też `manifest.json` i `HASHES.txt`).",
    ]
    if conflicts:
        lines += ["", f"⚠️ Auto-rozwiązano **{len(conflicts)}** konflikt(ów) plików."]
    if session.preview_token:
        lines += ["", f"🖼️ [Podgląd kombinacji]({PUBLIC_URL}/preview/{session.preview_token})"]
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

    # Publikacja na kanale #centrum-pobierania
    guild = interaction.guild
    downloads_channel = discord.utils.get(guild.text_channels, name=CH_DOWNLOADS)
    if downloads_channel:
        try:
            await downloads_channel.send(f"<@{session.user_id}> Twoja paczka: {link}")
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


async def fetch_videos(http: aiohttp.ClientSession, query: str) -> List[Dict[str, Any]]:
    """Pobiera najnowsze filmy dla jednego zapytania."""
    published_after = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "key": YOUTUBE_API_KEY, "q": query, "part": "snippet", "type": "video",
        "order": "date", "publishedAfter": published_after, "maxResults": "10",
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
    """Skanuje YouTube i zwraca NOWE filmy z modami klienckimi."""
    if not YOUTUBE_API_KEY:
        raise YouTubeQuotaError("Brak YOUTUBE_API_KEY w .env")

    posted = _load_posted()
    candidates: List[Dict[str, Any]] = []
    async with aiohttp.ClientSession() as http:
        for query in YT_QUERIES:
            try:
                for video in await fetch_videos(http, query):
                    if video["id"] in posted or not passes_filter(video["title"], video["channel"]):
                        continue
                    video["category"] = classify_video(video["title"])
                    video["safe_links"] = safe_links_from_description(video["description"])
                    posted.add(video["id"])
                    candidates.append(video)
            except Exception as exc:  # noqa: BLE001
                yt_log.error('Blad zapytania "%s": %s', query, exc)
            await asyncio.sleep(0.3)

    if not candidates:
        return []

    seen: set = set()
    unique = [v for v in candidates if not (v["id"] in seen or seen.add(v["id"]))]
    unique.sort(key=lambda v: v["category"])
    _save_posted(posted)
    return unique[:30]


async def post_videos(bot: "FoundryBot", videos: Sequence[Dict[str, Any]]) -> int:
    """Wrzuca filmy na kanał #mody-optymalizacja-live każdego serwera."""
    posted = 0
    for guild in bot.guilds:
        channel = find_channel(guild, CAT_MODS, CH_MODS_LIVE)
        if not channel:
            continue
        for video in videos:
            links = video.get("safe_links") or []
            links_text = ("\n**🔗 Linki z opisu:**\n" + "\n".join(
                f"- [{link['host']}]({link['url']})" for link in links[:3])) if links else \
                "\n*Brak zweryfikowanych linków w opisie — sprawdź sam w filmie.*"
            embed = discord.Embed(
                title=f"🎬 [{video['category']}] {video['title'][:230]}",
                url=f"https://www.youtube.com/watch?v={video['id']}",
                description=(
                    f"**Kategoria:** `{video['category']}`\n"
                    f"**Kanał:** {video['channel']}\n"
                    f"**Opublikowano:** <t:{int(datetime.fromisoformat(video['published'].replace('Z', '+00:00')).timestamp())}:R>"
                    f"{links_text}\n\n⚠️ Sprawdź regulamin serwera, na którym grasz!"
                ),
                color=C_ORANGE, timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=video["thumbnail"])
            embed.set_footer(text="Live Mod Feed • tylko mody klienckie (client-side)")
            try:
                await channel.send(embed=embed)
                posted += 1
            except discord.HTTPException as exc:
                yt_log.warning("Nie wyslano na %s: %s", guild.name, exc)
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
                f"✅ Skan zakończony — wrzucono **{count}** nowych filmów"
                + (f", wysłano **{pings}** spersonalizowanych rekomendacji." if pings else "."))
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
    embed.set_image(url=step["image"])
    embed.set_footer(text=(
        "🔒 Preset ekskluzywny — zbuduj więcej paczek, aby odblokować" if locked
        else "Zdjęcie poglądowe efektu w grze • FiveM Mod Foundry"))
    return embed


def step_view(index: int, chosen: bool, locked: bool = False, level: int = 0) -> discord.ui.View:
    """Widok kroku: rząd przycisków + OSOBNY rząd select (Discord tego wymaga!)."""
    if locked:
        first = btn(f"citizen_locked:{index}", f"🔒 Wymaga poziomu {level}",
                    discord.ButtonStyle.secondary)
    else:
        first = btn(f"citizen_add:{index}",
                    "Dodano ✓ (kliknij, aby usunąć)" if chosen else "Dodaj do paczki",
                    discord.ButtonStyle.success if chosen else discord.ButtonStyle.primary,
                    "✅" if chosen else "➕")
    buttons = [
        first,
        btn(f"citizen_skip:{index}", "Pomiń", discord.ButtonStyle.secondary, "⏭️"),
        btn("citizen_summary", "Podsumowanie", discord.ButtonStyle.secondary, "📋"),
    ]
    jump = select(f"citizen_jump:{index}", "Przeskocz do innego kroku...", step_jump_options(index))
    return LayoutView(buttons, [jump])


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
    """Embed podsumowania citizena (+ konflikty)."""
    kept, dropped, conflicts = resolve_conflicts(session.chosen_steps())
    build = build_by_id(session.build_id)
    lines = [f"✅ **{s['name']}** — {s['description']}" for s in kept] or [
        "*Nie wybrano nic — wróć do kroków przyciskami powyżej.*"]
    if dropped:
        lines += ["", "⚠️ **Wykryto konflikty plików** — zainstalowany zostanie **ostatnio wybrany** wariant:"]
        lines += [f"• `{c['file']}` → **{c['winner']}** (pominięto: {', '.join(c['dropped'])})"
                  for c in conflicts]
    lines += ["", f"🎮 **Docelowy build GTA V:** {build['name']}"]
    embed = discord.Embed(title="📋 Podsumowanie Twojej paczki Citizen",
                          description="\n".join(lines), color=C_YELLOW)
    embed.set_footer(text="Kliknij „Zakończ tworzenie', aby zbudować ZIP.")
    return embed, conflicts


def publish_citizen_preview(session: Session, conflicts: Sequence[Dict[str, Any]]) -> Optional[str]:
    """Generuje podgląd kombinacji citizena (Live Before/After) i zwraca link."""
    kept, _dropped, _conflicts = resolve_conflicts(session.chosen_steps())
    if not kept:
        return None
    page = render_preview_html(kept, conflicts, build_by_id(session.build_id)["name"], "Podgląd citizena")
    session.preview_token = STORAGE.register_preview(page, "Podgląd citizena", session.user_id)
    return f"{PUBLIC_URL}/preview/{session.preview_token}"


def publish_skins_preview(session: Session, skins: Sequence[Dict[str, Any]]) -> Optional[str]:
    """Generuje podgląd wybranych skinów broni i zwraca link."""
    if not skins:
        return None
    page = render_preview_html(skins, [], build_by_id(session.build_id)["name"], "Podgląd skinów broni")
    session.preview_token = STORAGE.register_preview(page, "Podgląd skinów", session.user_id)
    return f"{PUBLIC_URL}/preview/{session.preview_token}"

# ============================================================================
# 19. KREATOR CITIZENA — wysyłanie kroków
# ============================================================================


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
    await channel.send(embed=step_embed(step, index, chosen, level),
                       view=step_view(index, chosen, locked, min_level_of(step)))


async def send_summary(channel: discord.abc.Messageable, session: Session) -> None:
    """Wysyła podsumowanie z linkiem do podglądu i wyborem buildu."""
    embed, conflicts = citizen_summary_embed(session)
    link = publish_citizen_preview(session, conflicts)
    if link:
        embed.add_field(name="🖼️ Podgląd kombinacji (live)",
                        value=f"[Otwórz podgląd w przeglądarce]({link})\nZobacz dokładnie, co wchodzi do paczki.")
    await channel.send(embed=embed, view=LayoutView(
        [btn("citizen_finish", "Zakończ tworzenie", discord.ButtonStyle.success, "📦"),
         btn("citizen_restart", "Zacznij od nowa", discord.ButtonStyle.secondary, "🔄"),
         btn("session_close", "Zamknij", discord.ButtonStyle.danger, "🔒")],
        [select("build_pick", "🎮 Docelowy build GTA V / FiveM...",
                [opt(b["name"], b["id"], b["note"], default=(b["id"] == session.build_id))
                 for b in GAME_BUILDS])],
    ))

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
    embed.set_image(url=skin["image"])
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
    rows.append(skin_nav_row())
    return LayoutView(*rows)


def skin_nav_row() -> List[discord.ui.Button]:
    """Przyciski nawigacji studia skinów."""
    return [
        btn("ws_back_to_weapons", "← Inna broń", discord.ButtonStyle.secondary, "🔫"),
        btn("ws_search_start", "🔎 Szukaj skinów (.rpf)", discord.ButtonStyle.secondary),
        btn("ws_summary", "Podsumowanie", discord.ButtonStyle.secondary, "📋"),
        btn("ws_finish", "Zakończ i zbuduj paczkę", discord.ButtonStyle.success, "📦"),
        btn("session_close", "Zamknij", discord.ButtonStyle.danger, "🔒"),
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
    await channel.send(embed=skin_embed(weapon, index, session), view=skin_view(weapon, index, session))


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
    """Podsumowanie paczki skinów + podgląd."""
    skins = session.collect_skins()
    build = build_by_id(session.build_id)
    embed = discord.Embed(
        title="📋 Podsumowanie paczki skinów",
        description="\n".join(f"✅ **{s['name']}** — {s.get('description') or ''}" for s in skins)
        or "*Nie wybrano żadnego skina.*", color=C_YELLOW)
    embed.add_field(name="🎮 Docelowy build GTA V", value=build["name"])
    link = publish_skins_preview(session, skins)
    if link:
        embed.add_field(name="🖼️ Podgląd kombinacji (live)",
                        value=f"[Otwórz podgląd w przeglądarce]({link})")
    embed.set_footer(text="Kliknij „Zakończ i zbuduj paczkę', aby wygenerować ZIP.")
    await channel.send(embed=embed, view=LayoutView(skin_nav_row()))

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

    # --- 📦 MOD FEED ---
    mods_cat = await ensure_category(guild, CAT_MODS)
    mods_ch = await ensure_text_channel(guild, mods_cat, CH_MODS_LIVE,
                                       "🔥 NOWE Mody klienckie z YouTube — na żywo.")
    await ensure_text_channel(guild, mods_cat, CH_HELP, "Masz problem z modem? Pisz tutaj.")

    if not await panel_exists(mods_ch, None):
        await mods_ch.send(embed=discord.Embed(
            title="📡 Live Mod Feed — jak to działa",
            description=(f"Bot **co {YT_SCAN_MINUTES} minut** sprawdza YouTube i wrzuca najnowsze "
                         "**mody klienckie**:\n"
                         "• ⚙️ OPTI / FPS boost packi\n"
                         "• 🥔 POTATO graphics (plastelina, low-poly mapa)\n"
                         "• 🎮 First person / low poly citizen\n"
                         "• 🔫 Skin packi do broni (.rpf)\n"
                         "• 🗺️ Mapy PvP client-side\n\n"
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


async def reset_server(guild: discord.Guild, executor: discord.abc.User) -> List[str]:
    """Usuwa strukturę stworzoną przez bota (kategorie, kanały emotkowe, role)."""
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


def system_panel_embed(guild: discord.Guild, executor: discord.abc.User) -> discord.Embed:
    """Embed panelu /system."""
    return discord.Embed(
        title="⚙️ Panel Systemowy — Zarządzanie serwerem",
        description=(f"**Serwer:** {guild.name}\n"
                     f"**Operator:** {executor.mention}\n\n"
                     "**Dostępne akcje:**\n"
                     "🎨 **Zbuduj design** — estetyczna przebudowa układu (emotki, kategorie, uprawnienia).\n"
                     "⚠️ **Reset serwera** — usuwa strukturę bota (podwójne potwierdzenie!).\n\n"
                     "**Zabezpieczenia:** tylko właściciel serwera lub Administrator.\n"
                     f"Każde użycie logowane do `#{CH_SYSLOG}`."),
        color=C_PURPLE, timestamp=datetime.now(timezone.utc))


def system_panel_view() -> discord.ui.View:
    """Przyciski panelu /system."""
    return LayoutView([
        btn("sys_build_design", "Zbuduj estetyczny design", discord.ButtonStyle.success, "🎨"),
        btn("sys_reset_start", "Wyczyść / Resetuj serwer", discord.ButtonStyle.danger, "⚠️"),
        btn("sys_refresh", "Odśwież panel", discord.ButtonStyle.secondary, "🔄"),
    ])


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
        return web.Response(text="404: Paczka nie istnieje lub wygasła.", status=404)
    STORAGE.mark_downloaded(token)
    http_log.info("Paczka %s pobierana przez HTTP (%s)", package["file_name"],
                  request.remote or "?")
    return web.FileResponse(package["file_path"], headers={
        "Content-Disposition": f'attachment; filename="{package["file_name"]}"',
        "Content-Type": "application/zip",
    })


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
                             "/health • /download/<token> • /preview/<token>\n"
                             "/api/pack/<token> • /api/profile/<discord_id> • /api/stats"))


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


async def http_api_stats(request: web.Request) -> web.Response:
    """GET /api/stats — statystyki bota (bez danych wrażliwych)."""
    queue = ZIP_QUEUE.info()
    return web.json_response({
        "ok": True,
        "creators": len(PROFILES),
        "steps": len(CITIZEN_STEPS),
        "weapons": len(all_weapons()),
        "packs_issued": len(PACK_TOKENS),
        "queue": {"waiting": queue["waiting"], "running": queue["running"],
                  "completed": queue["completed"], "failed": queue["failed"]},
        "cache": {"files": FILE_CACHE.stats()["files"],
                  "hits": FILE_CACHE.stats()["hits"],
                  "misses": FILE_CACHE.stats()["misses"]},
    })


def create_http_app() -> web.Application:
    """Tworzy aplikację aiohttp z trasami bota."""
    app = web.Application()
    app.router.add_get("/health", http_health)
    app.router.add_get("/download/{token}", http_download)
    app.router.add_get("/preview/{token}", http_preview)
    app.router.add_get("/api/pack/{token}", http_api_pack)
    app.router.add_get("/api/profile/{user_id}", http_api_profile)
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


async def report_user_error(interaction: discord.Interaction, exc: BaseException, where: str) -> None:
    """Czytelny komunikat dla gracza + automatyczne zgłoszenie dla administracji."""
    eid = await notify_error(f"Błąd obsługi: {where}", f"Komenda/akcja: `{where}`", exc, where,
                             getattr(interaction, "user", None))
    message = (f"😔 **Ups, coś poszło nie tak** (`{where}`).\n"
               "Nic nie zostało zepsute — spróbuj ponownie lub kliknij przycisk raz jeszcze.\n"
               f"Jeśli problem wraca, zgłoś administracji kod błędu: `{eid}`")
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


def handle_loop_exception(loop: asyncio.AbstractEventLoop, context: Dict[str, Any]) -> None:
    """Łapie wyjątki zadań w tle (np. pętli skanera), żeby bot nie umarł po cichu."""
    exc = context.get("exception")
    message = context.get("message") or "nieznany błąd pętli zdarzeń"
    err_log.error("Wyjątek pętli: %s (%s)", message, exc)
    try:
        asyncio.create_task(notify_error("Wyjątek w zadaniu w tle", str(message), exc, "asyncio"))
    except RuntimeError:
        pass


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
        http_log.info("Serwer HTTP na porcie %s (linki: %s/download/<token>)", HTTP_PORT, PUBLIC_URL)

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
        if not session or session.user_id != message.author.id or not session.search_mode:
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
                if (interaction.data or {}).get("custom_id") == "sys_reset_modal":
                    await handle_reset_modal(interaction)
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
                await handle_system_button(interaction, custom_id)
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
                await interaction.response.edit_message(embed=step_embed(step, index, chosen, level),
                                                       view=step_view(index, chosen, False))
                return

            if custom_id.startswith("citizen_skip:"):
                index = int(custom_id.split(":", 1)[1])
                await interaction.response.defer()
                await send_step(interaction.channel, session, index + 1)
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
                kept, _dropped, conflicts = resolve_conflicts(session.chosen_steps())
                await interaction.response.defer()
                await deliver_package(interaction, session, kept, "citizen", conflicts)
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
                await interaction.response.edit_message(embed=skin_embed(weapon, index, session, level),
                                                       view=skin_view(weapon, index, session))
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
                await interaction.response.edit_message(embed=skin_embed(weapon, index, session),
                                                       view=skin_view(weapon, index, session))
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
                await interaction.response.edit_message(embed=skin_embed(weapon, index, session),
                                                       view=skin_view(weapon, index, session))
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
                await interaction.response.edit_message(embed=skin_embed(weapon, index, session),
                                                       view=skin_view(weapon, index, session))
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
                skins = session.collect_skins()
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
                     "🖼️ **Podgląd kombinacji** — link do strony z Twoimi wyborami\n"
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
        embed.add_field(name="🖼️ Podgląd kombinacji (live)",
                        value=f"[Otwórz podgląd w przeglądarce]({PUBLIC_URL}/preview/{session.preview_token})")
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
        embed = discord.Embed(
            title="📋 Podsumowanie paczki skinów",
            description="\n".join(f"✅ **{s['name']}** — {s.get('description') or ''}" for s in skins)
            or "*Nie wybrano żadnego skina.*", color=C_YELLOW)
        embed.add_field(name="🎮 Docelowy build GTA V", value=build["name"])
        link = publish_skins_preview(session, skins)
        if link:
            embed.add_field(name="🖼️ Podgląd kombinacji (live)", value=f"[Otwórz podgląd]({link})")
        await interaction.response.edit_message(embed=embed, view=LayoutView(skin_nav_row()))
        return

    await interaction.response.send_message(f"✅ Docelowy build: **{build['name']}**", ephemeral=True)


async def handle_system_button(interaction: discord.Interaction, custom_id: str) -> None:
    """Obsługa przycisków panelu /system (z autoryzacją i logowaniem)."""
    if not is_authorized(interaction):
        await system_log(interaction.guild, "Próba akcji /system bez uprawnień",
                         interaction.user, custom_id)
        await interaction.response.send_message("⛔ Brak uprawnień.", ephemeral=True)
        return

    if custom_id == "sys_refresh":
        await interaction.response.edit_message(
            embed=system_panel_embed(interaction.guild, interaction.user), view=system_panel_view())
        return

    if custom_id == "sys_build_design":
        await interaction.response.defer(ephemeral=True)
        try:
            results = await build_aesthetic_design(interaction.guild, interaction.user)
            embed = discord.Embed(
                title="🎨 Design serwera przebudowany!",
                description=(f"Wykonano **{len(results)}** operacji:\n```\n"
                             + "\n".join(results[:20])
                             + (f"\n... i {len(results) - 20} więcej" if len(results) > 20 else "")
                             + "\n```\n\nPełny log w `#" + CH_SYSLOG + "`."),
                color=C_GREEN, timestamp=datetime.now(timezone.utc))
            await interaction.followup.send(embed=embed)
        except Exception as exc:  # noqa: BLE001
            sys_log.error("Blad budowania designu: %s", exc)
            await interaction.followup.send(f"❌ Błąd: {exc}", ephemeral=True)
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
        await interaction.response.send_message(embed=embed, ephemeral=True, view=LayoutView([
            btn("sys_reset_confirm", "Potwierdzam — chcę reset", discord.ButtonStyle.danger, "🔴"),
            btn("sys_reset_cancel", "Anuluj", discord.ButtonStyle.secondary, "✖️"),
        ]))
        return

    if custom_id == "sys_reset_cancel":
        await system_log(interaction.guild, "Reset anulowany przez użytkownika", interaction.user)
        await interaction.response.edit_message(content="✖️ Reset anulowany.", embed=None, view=None)
        return

    if custom_id == "sys_reset_confirm":
        modal = discord.ui.Modal(title="⚠️ Potwierdzenie resetu serwera", custom_id="sys_reset_modal")
        modal.add_item(discord.ui.TextInput(
            custom_id="sys_reset_text", label="Wpisz POTWIERDZAM wielkimi literami",
            style=discord.TextStyle.short, min_length=11, max_length=11,
            placeholder="POTWIERDZAM", required=True))
        await interaction.response.send_modal(modal)
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
    await interaction.response.defer(ephemeral=True)
    try:
        results = await reset_server(interaction.guild, interaction.user)
        embed = discord.Embed(
            title="💥 Serwer zresetowany",
            description=(f"Usunięto **{len(results)}** elementów struktury bota.\n```\n"
                         + "\n".join(results[:20])
                         + (f"\n... i {len(results) - 20} więcej" if len(results) > 20 else "")
                         + "\n```\n\nMożesz teraz zbudować nowy design przyciskiem 🎨 w `/system`."),
            color=C_ORANGE, timestamp=datetime.now(timezone.utc))
        await interaction.followup.send(embed=embed)
    except Exception as exc:  # noqa: BLE001
        sys_log.error("Blad resetu: %s", exc)
        await interaction.followup.send(f"❌ Błąd resetu: {exc}", ephemeral=True)


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
                     f"({megabytes(stats['freed_bytes'])} zwolnione)"),
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


@bot.tree.command(name="top", description="Ranking twórców — kto zbudował najwięcej paczek")
async def cmd_top(interaction: discord.Interaction) -> None:
    """Top 10 twórców według XP."""
    profiles_load()
    ranking = sorted(PROFILES.values(), key=lambda p: p.xp, reverse=True)[:10]
    if not ranking:
        await interaction.response.send_message("📭 Ranking jest pusty — bądź pierwszy!",
                                                ephemeral=True)
        return
    lines = []
    for index, profile in enumerate(ranking, start=1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(index, f"**{index}.**")
        lines.append(f"{medal} <@{profile.user_id}> — **{profile.rank['name']}** "
                     f"(poziom {profile.level}, {profile.xp} XP, {profile.builds} paczek)")
    embed = discord.Embed(title="🏆 Ranking twórców Foundry",
                          description="\n".join(lines), color=C_YELLOW)
    embed.set_footer(text="XP zdobywasz za budowanie paczek, wybory w kreatorze, wyszukiwanie i zgłoszenia")
    await interaction.response.send_message(embed=embed)


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


@bot.tree.command(name="xp", description="Nadaj lub odejmij XP twórcy (admin)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(uzytkownik="Gracz", ilosc="Ile XP dodać (może być ujemne)", powod="Powód")
async def cmd_xp(interaction: discord.Interaction, uzytkownik: discord.Member,
                 ilosc: app_commands.Range[int, -5000, 5000], powod: str = "korekta administracji") -> None:
    """Ręczna korekta XP (np. za pomoc w społeczności)."""
    profile = profile_get(uzytkownik)
    if profile is None:
        await interaction.response.send_message("❌ Nie udało się wczytać profilu.", ephemeral=True)
        return
    message = profile.add_xp("manual", amount=int(ilosc))
    profile.reports += 1 if ilosc < 0 else 0
    profiles_save()
    await system_log(interaction.guild, "Korekta XP", interaction.user,
                     f"{uzytkownik} ({uzytkownik.id}): {ilosc:+} XP — {powod}")
    text = (f"✅ {uzytkownik.mention}: **{ilosc:+} XP** — {powod}\n"
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
    """Panel /system: design serwera + reset + logi audytowe."""
    if not is_authorized(interaction):
        await system_log(interaction.guild, "Próba /system bez uprawnień", interaction.user,
                         f"ID: {interaction.user.id}")
        await interaction.response.send_message(
            "⛔ Tylko właściciel serwera lub Administrator może używać /system.", ephemeral=True)
        return
    await interaction.response.send_message(
        embed=system_panel_embed(interaction.guild, interaction.user),
        view=system_panel_view(), ephemeral=True)

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
    if not os.getenv("PUBLIC_URL"):
        core_log.warning("Brak PUBLIC_URL — linki do paczek wskażą localhost!")
    if not SKIN_INDEX_URL or "twoj-user" in SKIN_INDEX_URL:
        core_log.warning("Brak SKIN_INDEX_URL — wyszukiwarka skinów .rpf będzie pusta.")

    core_log.info("Startuję FiveM Mod Foundry (Python)...")
    try:
        bot.run(DISCORD_TOKEN, log_handler=None)
    except discord.LoginFailure:
        core_log.error("Niepoprawny DISCORD_TOKEN — sprawdź token w .env.")
        raise SystemExit(1)
    except KeyboardInterrupt:  # pragma: no cover
        core_log.warning("Zatrzymano bota (Ctrl+C).")


if __name__ == "__main__":
    main()
