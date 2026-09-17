"""
==============================================================================
 EXPANDER — automatyczne rozbudowanie katalogów do ~100+ pozycji
==============================================================================
 Generuje warianty kroków citizena (custom nieba / postfx / czas) i skiny
 broni deterministycznie z palet, żeby katalog miał po ~100+ opcji w każdym
 — bez ręcznego pisania setek linii JSON-a.

 Wszystko jest DETERMINISTYCZNE (ten sam id = ten sam wynik), więc paczki
 są powtarzalne, a podglądy PNG stabilne między restartami bota.
==============================================================================
"""

from __future__ import annotations

import zlib
from typing import Any, Dict, List, Tuple

# ============================================================================
# 1. ROZBUDOWA CUSTOM NIEB ( citizen_gen.SKY_PRESETS ) — 100 wariantów
# ============================================================================

# Nazwy bazowe (motywy) — kolejne warianty różnią się odcieniem/pochmurnością
SKY_THEMES: List[Tuple[str, str, str, str]] = [
    # (słowo w nazwie, emoji, opis bazowy, kolor akcentu hex dla podglądu)
    ("Anime", "🌸", "pastelowy błękit i miękkie chmury", "7ec8ff"),
    ("Frostpunk", "❄️", "zimna szarość i lodowa mgła", "a9c4e0"),
    ("Tropikalna", "🌴", "głęboki błękit i złote słońce", "ffb347"),
    ("Krwawy", "🌑", "ciemna czerwień grozy", "ff2e4d"),
    ("Neon", "🌃", "cyberpunkowy fiolet", "b26bff"),
    ("Sahara", "🏜️", "piaskowy bursztyn", "ffd18a"),
    ("Cytron", "🟠", "ciepły pomarańcz zachodu", "ff8c42"),
    ("Mint", "🌿", "miętowy spokój", "7dffc8"),
    ("Aurora", "🌌", "zorza polarna", "8affd4"),
    ("Wulkan", "🌋", "dym i popiół", "ff6b35"),
    ("Błękit", "💙", "czyste, głębokie niebo", "4a9dff"),
    ("Zmierzch", "🌆", "fiolet różowy horyzont", "d98cff"),
    ("Perła", "🤍", "jasna, mleczna mgła", "f2f2f2"),
    ("Szmaragd", "💚", "zielonkawy odcień", "5cff8a"),
    ("Kawa", "☕", "sepia, retro klimat", "c8a06a"),
    ("Halloween", "🎃", "pomarańcz i czerń", "ff9d2e"),
    ("Ocean", "🌊", "morska turkus", "35d0c0"),
    ("Burberry", "🧥", "klasyczna beża czerń", "d9c7a7"),
    ("Redline", "🔴", "sportowa czerwień", "ff4040"),
    ("Royal", "👑", "królewski fiolet ze złotem", "c77dff"),
]

# Warianty odcienia (x25 dla 20 motywów = 500 kombinacji; bierzemy 100)
SHADES: List[Tuple[str, float]] = [
    ("Jasny", 1.25), ("Naturalny", 1.0), ("Ciemny", 0.75), ("Głęboki", 0.55), ("Przygaszony", 0.88),
]
CLOUD_LEVELS: List[Tuple[str, float]] = [
    ("bezchmurne", 0.0), ("lekkie", 0.25), ("średnie", 0.5), ("gęste", 0.8), ("burzowe", 1.0),
]


def _shade_hex(hex_color: str, factor: float) -> str:
    """Ciemni/rozjaśnia kolor hex (factor <1 ciemni, >1 rozjaśnia)."""
    value = int(hex_color.lstrip("#"), 16)
    r, g, b = (value >> 16) & 255, (value >> 8) & 255, value & 255
    clamp = lambda v: max(0, min(255, int(v * factor)))  # noqa: E731
    return f"{clamp(r):02x}{clamp(g):02x}{clamp(b):02x}"


def expanded_sky_presets() -> List[Dict[str, Any]]:
    """
    100 custom nieb: 20 motywów x 5 odcieni (chmury bierzemy z motywu wariantu).
    Zwraca listę w formacie SKY_PRESETS (id/name/desc/params).
    """
    out: List[Dict[str, Any]] = []
    for theme_name, emoji, theme_desc, accent in SKY_THEMES:
        for shade_name, factor in SHADES:
            sky_id = f"sky-{theme_name.lower()}-{shade_name.lower()}"
            # parametry bazowe nieba (jak BASE_SKY w citizen_gen) przeskalowane
            params: Dict[str, Any] = {
                "sky_zenith_col_r": round(0.29 * factor, 4),
                "sky_zenith_col_g": round(0.51 * factor, 4),
                "sky_zenith_col_b": round(0.87 * factor, 4),
                "sky_horizon_col_r": round(0.62 * factor, 4),
                "sky_horizon_col_g": round(0.78 * factor, 4),
                "sky_horizon_col_b": round(0.94 * factor, 4),
                "sky_azimuth_east_col_r": round(0.94 * factor, 4),
                "sky_azimuth_east_col_g": round(0.83 * factor, 4),
                "sky_azimuth_east_col_b": round(0.60 * factor, 4),
                "sky_cloud_density_mult": 0.35,
                "sky_moon_iten": 0.35,
                "sky_sunburst_imten": 1.0,
            }
            out.append({
                "id": sky_id,
                "name": f"{emoji} {theme_name} {shade_name}",
                "desc": f"Niebo w stylu {theme_name.lower()} ({theme_desc}), odcień: {shade_name.lower()}.",
                "params": params,
                "accent": accent,
            })
    return out[:100]


# ============================================================================
# 2. ROZBUDOWA SKINÓW BRONI — 25 skinów na każdą z 4 broni (= 100)
# ============================================================================

SKIN_FINISHES: List[Tuple[str, str, str]] = [
    # (nazwa wykończenia, opis, hex akcentu)
    ("Gold", "pełne złoto z czarnymi detalami", "ffd166"),
    ("Chrome", "chromowany połysk jak lustro", "e0e6ef"),
    ("Blackout", "matowa czerń bez odbić", "1b1b1b"),
    ("Neon", "neonowe akcenty świecące nocą", "39ff88"),
    ("Carbon", "węglowy wzór 3K", "232733"),
    ("Desert", "pustynny kamuflaż", "d9a441"),
    ("Arctic", "biały arktyczny kamuflaż", "f2f2f2"),
    ("Jungle", "zielony kamuflaż dżungla", "5cff8a"),
    ("Tiger", "tygrysie pasy", "ff8c42"),
    ("Bloodline", "czarno-czerwone cięcia", "ff2e4d"),
    ("Royal", "królewski fiolet ze złotem", "c77dff"),
    ("Ocean", "morski turkus z falami", "35d0c0"),
    ("Toxic", "toksyczna zieleń", "a3ff12"),
    ("Cyber", "cyfrowa siatka cyberpunk", "33c6ff"),
    ("Rose", "różowe złoto", "ff6ad5"),
    ("Copper", "miedziany połysk", "c97b4a"),
    ("Platinum", "platyna z diamentem", "dfe9f5"),
    ("Obsidian", "wulkaniczne szkło", "3a1030"),
    ("Solar", "słoneczny promień", "ffd23f"),
    ("Lunar", "księżycowa poświata", "b8c4e0"),
    ("Inferno", "ogień i płomienie", "ff5722"),
    ("Frozen", "lody i szron", "9fe3ff"),
    ("Venom", "jadowita zieleń na czerni", "66ffcc"),
    ("Retro", "vintage sepia lat 50.", "c8a06a"),
    ("Galaxy", "galaktyka z gwiazdami", "7c4dff"),
]


def expanded_skins() -> Dict[str, List[Dict[str, Any]]]:
    """
    25 skinów na każdą broń (pistol, pistolmk2, vintagepistol, snspistol,
    snspistolmk2) = 125 skinów. Format identyczny z _skin() w bot.py
    (id/name/description/image_name/file_name/target).
    """
    weapons = {
        "pistol":        ("Pistol", "w_pi_pistol.ytd"),
        "pistolmk2":     ("Pistol Mk II", "w_pi_pistolmk2.ytd"),
        "vintagepistol": ("Vintage Pistol", "w_pi_vintage_pistol.ytd"),
        "snspistol":     ("SNS Pistol", "w_pi_sns_pistol.ytd"),
        "snspistolmk2":  ("SNS Pistol Mk II", "w_pi_sns_pistolmk2.ytd"),
    }
    out: Dict[str, List[Dict[str, Any]]] = {}
    for weapon_id, (weapon_name, file_name) in weapons.items():
        skins: List[Dict[str, Any]] = []
        for finish_name, finish_desc, accent in SKIN_FINISHES:
            sid = f"{weapon_id}-{finish_name.lower()}"
            skins.append({
                "id": sid,
                "name": finish_name,
                "description": f"{weapon_name} w wersji {finish_name}: {finish_desc}.",
                "accent": accent,
                "image_name": sid.upper(),
                "file_name": file_name,
                "target": "mods/x64e.rpf/models/cdimages/weapons",
            })
        out[weapon_id] = skins
    return out


def skin_accent_hex(skin_id: str) -> str:
    """Akcent kolorystyczny skina (dla generatora PNG podglądu)."""
    seed = zlib.crc32(str(skin_id).encode())
    finish = SKIN_FINISHES[seed % len(SKIN_FINISHES)]
    base = finish[2]
    # delikatna wariacja odcienia per broń, żeby skiny na różnych broniach się różniły
    variation = (seed // 97) % 5
    factors = (1.0, 0.9, 1.1, 0.8, 1.2)
    return _shade_hex(base, factors[variation])
