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
import html
import json
import logging
import os
import random
import re
import shutil
import time
import zipfile
from datetime import datetime, timedelta, timezone
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

ROOT = Path(__file__).parent.resolve()
DOWNLOADS_DIR = ROOT / "downloads"
WORKSPACES_DIR = ROOT / "temp_sessions"
LOGS_DIR = ROOT / "logs"
DATA_DIR = ROOT / "data"
POSTED_FILE = ROOT / "posted_videos.json"
BUILD_STATE_FILE = DATA_DIR / "build.json"

for _d in (DOWNLOADS_DIR, WORKSPACES_DIR, LOGS_DIR, DATA_DIR):
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
# 10. STORAGE — paczki ZIP i podglądy (TTL + auto-sprzątanie)
# ============================================================================

store_log = log("Storage")


def new_token() -> str:
    """Kryptograficznie losowy token (32 znaki hex) — linków nie da się zgadnąć."""
    return os.urandom(16).hex()


class Storage:
    """Magazyn paczek ZIP i podglądów HTML z automatycznym wygasaniem."""

    def __init__(self) -> None:
        self.packages: Dict[str, Dict[str, Any]] = {}
        self.previews: Dict[str, Dict[str, Any]] = {}

    # --- paczki ---
    def register(self, file_path: Path, file_name: str, size: int, file_count: int,
                 user_id: str, workspace: Optional[Path] = None) -> str:
        token = new_token()
        self.packages[token] = {
            "file_path": Path(file_path), "file_name": file_name, "size": size,
            "file_count": file_count, "user_id": user_id,
            "workspace": Path(workspace) if workspace else None,
            "created_at": time.time(),
        }
        return token

    def get(self, token: str) -> Optional[Dict[str, Any]]:
        return self.packages.get(token)

    def remove(self, token: str) -> None:
        pkg = self.packages.pop(token, None)
        if not pkg:
            return
        try:
            Path(pkg["file_path"]).unlink(missing_ok=True)
        except OSError as exc:
            store_log.warning("Nie usunieto ZIPa: %s", exc)
        if pkg.get("workspace"):
            shutil.rmtree(pkg["workspace"], ignore_errors=True)
        store_log.info("Usunieto paczke %s (TTL)", pkg["file_name"])

    # --- podglądy ---
    def register_preview(self, html_text: str, title: str, user_id: str) -> str:
        token = new_token()
        self.previews[token] = {
            "html": html_text, "title": title, "user_id": user_id, "created_at": time.time(),
        }
        return token

    def get_preview(self, token: str) -> Optional[Dict[str, Any]]:
        return self.previews.get(token)

    # --- sprzątanie ---
    def sweep(self) -> None:
        now = time.time()
        ttl = DOWNLOAD_TTL_MINUTES * 60
        for token in [t for t, p in self.packages.items() if now - p["created_at"] > ttl]:
            self.remove(token)
        for token in [t for t, p in self.previews.items() if now - p["created_at"] > ttl]:
            self.previews.pop(token, None)
        # porzucone workspace po restarcie bota
        session_ttl = SESSION_TTL_MINUTES * 60
        for directory in WORKSPACES_DIR.glob("*"):
            if directory.is_dir() and now - directory.stat().st_mtime > session_ttl:
                shutil.rmtree(directory, ignore_errors=True)
                store_log.info("Porzadki: usunieto porzucony workspace %s", directory.name)

    def stats(self) -> Dict[str, int]:
        return {"packages": len(self.packages), "previews": len(self.previews)}


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
# 14. KOLEJKA ZADAŃ (chroni serwer przy pakowaniu ZIP-ów)
# ============================================================================


class TaskQueue:
    """Kolejka FIFO z ograniczoną równoległością (asyncio.Semaphore)."""

    def __init__(self, concurrency: int = 2) -> None:
        self._sem = asyncio.Semaphore(max(1, concurrency))
        self.completed = 0
        self.failed = 0

    @property
    def concurrency(self) -> int:
        return self._sem._value  # informacyjnie (wolne sloty)

    async def add(self, coro_func, *args, **kwargs):
        """Wykonuje zadanie w kolejce i zwraca jego wynik."""
        async with self._sem:
            try:
                result = await coro_func(*args, **kwargs)
                self.completed += 1
                return result
            except Exception:
                self.failed += 1
                raise


ZIP_QUEUE = TaskQueue(ZIP_QUEUE_CONCURRENCY)

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


async def process_items(workspace: Path, items: Sequence[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Pobiera pozycje do workspace i liczy ich hashe."""
    hashes: List[Dict[str, Any]] = []
    async with aiohttp.ClientSession(headers={"User-Agent": "FiveMModFoundry/2.0"}) as http:
        for item in items:
            file_name = resolve_file_name(item)
            dest = workspace / item["target"] / file_name
            fp_log.info("Pobieram: %s -> %s", item["file_url"], dest)
            await download_file(http, item["file_url"], dest)
            digest, size = sha256_file(dest)
            rel = dest.relative_to(workspace).as_posix()
            hashes.append({"path": rel, "sha256": digest, "size": size})
            fp_log.info("  ✓ %s (%.1f KB)", file_name, size / 1024)
            item["file_name"] = file_name
    return hashes


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
    fp_log.info("User %s: pakowanie %s pozycji (%s)", session.user_id, len(items), kind)

    async def build_package() -> Dict[str, Any]:
        build_dir = session.workspace / f"build-{kind}-{int(time.time() * 1000)}"
        build_dir.mkdir(parents=True, exist_ok=True)
        try:
            hashes = await process_items(build_dir, items)
            write_manifests(build_dir, hashes, build, session.user_id, kind, items, conflicts)
            (build_dir / "INSTRUKCJA.txt").write_text(
                instruction_text(
                    "TWOJA PACZKA CITIZEN" if kind == "citizen" else "TWOJA PACZKA SKINÓW BRONI",
                    items, conflicts, build, kind,
                ), encoding="utf-8")
            zip_path = DOWNLOADS_DIR / f"{kind}-{session.user_id}-{int(time.time())}.zip"
            size = await asyncio.to_thread(zip_directory, build_dir, zip_path)
            file_count = count_files(build_dir)
            return {"zip_path": zip_path, "size": size, "file_count": file_count}
        finally:
            await asyncio.to_thread(safe_rmtree, build_dir, session.workspace)

    try:
        result = await ZIP_QUEUE.add(build_package)
    except ApprovalRequired as exc:
        await request_approval(interaction, session, exc)
        return
    except Exception as exc:  # noqa: BLE001
        fp_log.error("Blad budowania paczki: %s", exc)
        await interaction.followup.send(f"❌ Błąd budowania paczki: {exc}", ephemeral=True)
        return

    token = STORAGE.register(result["zip_path"], result["zip_path"].name, result["size"],
                             result["file_count"], session.user_id)
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

    embed = discord.Embed(
        title="✅ Twoja paczka jest gotowa!" if kind == "citizen" else "✅ Twoja paczka skinów jest gotowa!",
        description="\n".join(lines), color=C_GREEN, timestamp=datetime.now(timezone.utc),
    )
    await interaction.followup.send(embed=embed)

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
        count = await post_videos(bot, await scan_videos())
        yt_log.info("Skan YouTube: %s nowych filmow.", count)
        if interaction:
            await interaction.followup.send(f"✅ Skan zakończony — wrzucono **{count}** nowych filmów.")
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


def step_embed(step: Dict[str, str], index: int, chosen: bool) -> discord.Embed:
    """Embed jednego kroku kreatora citizena (ze zdjęciem efektu w grze)."""
    embed = discord.Embed(
        title=f"{step['group']} — {index + 1}/{len(CITIZEN_STEPS)}",
        description=(f"**{step['name']}**\n{step['description']}\n\n"
                     + ("✅ **Dodano do Twojej paczki.**" if chosen
                        else "⬜ *Nie dodano — kliknij „Dodaj do paczki'.*")),
        color=C_GREEN if chosen else C_BLUE,
    )
    embed.set_image(url=step["image"])
    embed.set_footer(text="Zdjęcie poglądowe efektu w grze • FiveM Mod Foundry")
    return embed


def step_view(index: int, chosen: bool) -> discord.ui.View:
    """Widok kroku: rząd przycisków + OSOBNY rząd select (Discord tego wymaga!)."""
    buttons = [
        btn(f"citizen_add:{index}",
            "Dodano ✓ (kliknij, aby usunąć)" if chosen else "Dodaj do paczki",
            discord.ButtonStyle.success if chosen else discord.ButtonStyle.primary,
            "✅" if chosen else "➕"),
        btn(f"citizen_skip:{index}", "Pomiń", discord.ButtonStyle.secondary, "⏭️"),
        btn("citizen_summary", "Podsumowanie", discord.ButtonStyle.secondary, "📋"),
    ]
    jump = select(
        f"citizen_jump:{index}", "Przeskocz do innego kroku...",
        [opt(f"{short_group(s['group'])}: {s['name']}", str(i), default=(i == index))
         for i, s in enumerate(CITIZEN_STEPS)],
    )
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
    await channel.send(embed=step_embed(step, index, chosen), view=step_view(index, chosen))


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


def skin_embed(weapon: Dict[str, Any], skin_index: int, session: Session) -> discord.Embed:
    """Embed skina ze zdjęciem w grze."""
    skin = weapon["skins"][skin_index]
    chosen = session.weapon_skins.get(weapon["id"]) == skin["id"]
    embed = discord.Embed(
        title=f"🔫 {weapon['name']} — {skin['name']}",
        description=(f"**{skin['name']}** — {skin['description']}\n\n"
                     + ("✅ **Ten skin jest w Twojej paczce.**" if chosen else "⬜ *Nie wybrano.*")
                     + f"\n\n🎮 Build paczki: **{build_by_id(session.build_id)['name']}**"),
        color=C_GREEN if chosen else C_PURPLE,
    )
    embed.set_image(url=skin["image"])
    embed.set_footer(text="Realne zdjęcie skina nałożonego na broń • Weapon Skin Studio")
    return embed


def skin_view(weapon: Dict[str, Any], skin_index: int, session: Session) -> discord.ui.View:
    """Widok galerii skina: przyciski + osobny rząd select."""
    skin = weapon["skins"][skin_index]
    chosen = session.weapon_skins.get(weapon["id"]) == skin["id"]
    buttons = [
        btn(f"ws_prev:{weapon['id']}:{skin_index}", "◀ Wróć", discord.ButtonStyle.secondary),
        btn(f"ws_choose:{weapon['id']}:{skin_index}",
            "Wybrano ✓ (odznacz)" if chosen else "Wybierz ten skin",
            discord.ButtonStyle.success if chosen else discord.ButtonStyle.primary, "✅"),
        btn(f"ws_next:{weapon['id']}:{skin_index}", "Dalej ▶", discord.ButtonStyle.secondary),
    ]
    picker = select(f"ws_skin_select:{weapon['id']}", "Wybierz skin z listy...",
                    [opt(s["name"], str(i), s["description"], default=(i == skin_index))
                     for i, s in enumerate(weapon["skins"])])
    return LayoutView(buttons, [picker], skin_nav_row())


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
    description = "\n\n".join(
        f"**{i + 1}. {r.get('name', 'Skin')}** — {r.get('description') or 'bez opisu'}\n"
        f"Autor: {r.get('author') or '—'} • `{file_name_from_url(r.get('fileUrl', ''))}`"
        for i, r in enumerate(results)
    )
    embed = discord.Embed(title=f"🔎 Wyniki dla: {query} ({len(results)})",
                          description=description, color=C_GREEN)
    page = LayoutView([select("ws_search_pick", "Wybierz skin do paczki...",
                              [opt(r.get("name", "Skin"), str(i),
                                   r.get("description") or "bez opisu")
                               for i, r in enumerate(results)])])
    await channel.send(embed=embed, view=page)


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
    """GET /download/<token> — paczka ZIP."""
    package = STORAGE.get(request.match_info["token"])
    if not package:
        return web.Response(text="404: Paczka nie istnieje lub wygasła.", status=404)
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
    return web.Response(text="FiveM Mod Foundry — bot działa. /health, /download/<token>, /preview/<token>")


def create_http_app() -> web.Application:
    """Tworzy aplikację aiohttp z trasami bota."""
    app = web.Application()
    app.router.add_get("/health", http_health)
    app.router.add_get("/download/{token}", http_download)
    app.router.add_get("/preview/{token}", http_preview)
    app.router.add_get("/", http_root)
    return app

# ============================================================================
# 23. BOT — tickety, router interakcji, komendy, pętle w tle
# ============================================================================

ticket_log = log("Tickets")


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

        # 3. Zadania w tle
        asyncio.create_task(scanner_loop(self))
        asyncio.create_task(sweeper_loop(self))

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
                core_log.error("Setup %s: %s", guild.name, exc)
        core_log.info("✅ Bot gotowy.")

    async def on_guild_join(self, guild: discord.Guild) -> None:
        try:
            await setup_guild(guild)
            core_log.info("Dołączono i skonfigurowano %s", guild.name)
        except Exception as exc:  # noqa: BLE001
            core_log.error("Setup nowego serwera: %s", exc)

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
            core_log.error("Blad wyszukiwarki: %s", exc)

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
            if custom_id.startswith("citizen_add:"):
                index = int(custom_id.split(":", 1)[1])
                step = CITIZEN_STEPS[index]
                if step["id"] in session.choices:
                    session.choices.remove(step["id"])
                else:
                    session.choices.append(step["id"])
                chosen = step["id"] in session.choices
                await interaction.response.edit_message(embed=step_embed(step, index, chosen),
                                                       view=step_view(index, chosen))
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
                session.weapon_skins[weapon["id"]] = weapon["skins"][index]["id"]
                await interaction.response.edit_message(embed=skin_embed(weapon, index, session),
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

            if custom_id.startswith("ws_choose:"):
                _action, weapon_id, index_str = custom_id.split(":")
                weapon = find_weapon(weapon_id)
                if not weapon:
                    await interaction.response.defer()
                    return
                index = int(index_str)
                skin = weapon["skins"][index]
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
            core_log.error("Blad interakcji (%s): %s", custom_id if "custom_id" in locals() else "?", exc,
                           exc_info=True)
            try:
                payload = {"content": "❌ Wystąpił błąd.", "ephemeral": True}
                if interaction.response.is_done():
                    await interaction.followup.send(**payload)
                else:
                    await interaction.response.send_message(**payload)
            except discord.HTTPException:
                pass


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
    embed = discord.Embed(
        title="📊 Status FiveM Mod Foundry",
        description=(f"⚙️ Kolejka ZIP: **{ZIP_QUEUE.completed}** zadań wykonanych, "
                     f"**{ZIP_QUEUE.failed}** nieudanych\n"
                     f"📦 Paczki aktywne: **{stats['packages']}**\n"
                     f"🖼️ Podglądy aktywne: **{stats['previews']}**\n"
                     f"👥 Sesje aktywne: **{len(SESSIONS)}**\n"
                     f"🔐 Zgłoszenia bezpieczeństwa: **{len(approvals_pending())}** oczekujących\n"
                     f"🎮 Docelowy build: **{build_by_id(DEFAULT_BUILD_ID)['name']}**\n"
                     f"🧩 Opcji citizena: **{len(CITIZEN_STEPS)}**\n"
                     f"🔫 Broni w bazie: **{len(all_weapons())}** ({len(WEAPON_CATEGORIES)} kategorie)"),
        color=C_BLUE)
    await interaction.response.send_message(embed=embed, ephemeral=True)


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
