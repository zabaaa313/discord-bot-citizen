"""
==============================================================================
 GENERATOR PLIKÓW CITIZENA
==============================================================================
 Bot BUDUJE pliki paczki na podstawie przeskanowanego, czystego citizena
 (FiveM.app\\citizen). Zasada: TE SAME pliki, tylko ze zmienionymi wartościami.

 Pliki generowane (dokładna struktura jak w citizen/common/data):
   • timecycle/sggd.xml          — główne niebo (cycle EXTRASUNNY)
   • levels/gta5/weather.xml     — pogoda (naprawia broken EXTRASUNNY)
   • levels/gta5/time.xml        — słońce/księżyc (sun_roll, moon_roll)
   • visualsettings.dat          — deszcz, chmury, bloom, sun glare
   • effects/bloodfx.dat         — krew (anime / minimal / brak)

 Nieba NIE są z YouTube — parametry nieba siedzą w sggd.xml i bot je
 ustawia sam (to jest poprawny, techniczny sposób na custom niebo).
==============================================================================
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ============================================================================
# 1. CZYSTE NIEBO — parametry bazowe (przeskane z czystego citizena)
#    To jest "neutralny" stan; każde custom niebo zmienia tylko te wartości.
# ============================================================================

BASE_SKY: Dict[str, float] = {
    "sky_zenith_col_r": 0.29, "sky_zenith_col_g": 0.51, "sky_zenith_col_b": 0.87,
    "sky_zenith_col_inten": 1.0,
    "sky_horizon_col_r": 0.62, "sky_horizon_col_g": 0.78, "sky_horizon_col_b": 0.94,
    "sky_horizon_col_inten": 1.0,
    "sky_azimuth_east_col_r": 0.94, "sky_azimuth_east_col_g": 0.83, "sky_azimuth_east_col_b": 0.60,
    "sky_azimuth_east_col_inten": 1.0,
    "sky_azimuth_west_col_r": 0.85, "sky_azimuth_west_col_g": 0.72, "sky_azimuth_west_col_b": 0.58,
    "sky_azimuth_west_col_inten": 1.0,
    "sky_azimuth_transition_col_r": 0.80, "sky_azimuth_transition_col_g": 0.75, "sky_azimuth_transition_col_b": 0.70,
    "sky_azimuth_transition_col_inten": 1.0,
    "sky_cloud_density_mult": 0.35, "sky_cloud_gen_frequency": 1.3,
    "sky_cloud_gen_scale": 40.0, "sky_cloud_gen_threshold": 0.15,
    "sky_cloud_gen_softness": 0.5,
    "sky_moon_iten": 0.35, "sky_moon_disc_size": 1.0,
    "sky_sunburst_imten": 1.0,
}

# ============================================================================
# 2. KATALOG CUSTOM NIEB — gotowe stylistyki (zmieniają tylko parametry nieba)
# ============================================================================

SKY_PRESETS: List[Dict[str, Any]] = [
    {
        "id": "sky-clean-fps",
        "name": "☀️ Czyste + FPS",
        "desc": "Naturalne, jasne niebo bez mgły. Najbliżej 'czystego citizena', ale lżejsze dla GPU.",
        "params": {
            "sky_zenith_col_r": 0.29, "sky_zenith_col_g": 0.51, "sky_zenith_col_b": 0.87,
            "sky_horizon_col_r": 0.62, "sky_horizon_col_g": 0.78, "sky_horizon_col_b": 0.94,
            "sky_cloud_density_mult": 0.20,
            "sky_azimuth_east_col_r": 0.94, "sky_azimuth_east_col_g": 0.83, "sky_azimuth_east_col_b": 0.60,
        },
    },
    {
        "id": "sky-anime",
        "name": "🌸 Niebo Anime (Makoto Shinkai)",
        "desc": "Pastelowy błękit, mocno nasycone chmury, mocny sunburst. Styl 'Your Name'.",
        "params": {
            "sky_zenith_col_r": 0.25, "sky_zenith_col_g": 0.55, "sky_zenith_col_b": 0.98,
            "sky_horizon_col_r": 0.85, "sky_horizon_col_g": 0.92, "sky_horizon_col_b": 1.00,
            "sky_azimuth_east_col_r": 1.00, "sky_azimuth_east_col_g": 0.88, "sky_azimuth_east_col_b": 0.55,
            "sky_cloud_density_mult": 0.75,
            "sky_cloud_gen_softness": 0.85,
            "sky_sunburst_imten": 1.6,
        },
    },
    {
        "id": "sky-frostpunk",
        "name": "❄️ Frostpunk",
        "desc": "Zimna, lodowa mgła i szaroniebieskie niebo. Klimat mrozu i śniegu.",
        "params": {
            "sky_zenith_col_r": 0.55, "sky_zenith_col_g": 0.65, "sky_zenith_col_b": 0.85,
            "sky_horizon_col_r": 0.75, "sky_horizon_col_g": 0.82, "sky_horizon_col_b": 0.88,
            "sky_azimuth_east_col_r": 0.85, "sky_azimuth_east_col_g": 0.92, "sky_azimuth_east_col_b": 1.00,
            "sky_cloud_density_mult": 0.55,
        },
    },
    {
        "id": "sky-tropical",
        "name": "🌴 Tropikalna Majówka",
        "desc": "Głęboki błękit, złote słońce, soczyste chmury. Wakacyjny klimat Vice City.",
        "params": {
            "sky_zenith_col_r": 0.15, "sky_zenith_col_g": 0.42, "sky_zenith_col_b": 0.95,
            "sky_horizon_col_r": 0.95, "sky_horizon_col_g": 0.85, "sky_horizon_col_b": 0.55,
            "sky_azimuth_east_col_r": 1.00, "sky_azimuth_east_col_g": 0.75, "sky_azimuth_east_col_b": 0.35,
            "sky_cloud_density_mult": 0.45,
            "sky_sunburst_imten": 1.4,
        },
    },
    {
        "id": "sky-bloodmoon",
        "name": "🌑 Krwawy Księżyc",
        "desc": "Ciemnoczerwone niebo i wielki księżyc. PVP-owy klimat grozy.",
        "params": {
            "sky_zenith_col_r": 0.18, "sky_zenith_col_g": 0.04, "sky_zenith_col_b": 0.06,
            "sky_horizon_col_r": 0.45, "sky_horizon_col_g": 0.10, "sky_horizon_col_b": 0.08,
            "sky_azimuth_east_col_r": 0.60, "sky_azimuth_east_col_g": 0.15, "sky_azimuth_east_col_b": 0.10,
            "sky_cloud_density_mult": 0.60,
            "sky_moon_iten": 0.90, "sky_moon_disc_size": 2.2,
        },
    },
    {
        "id": "sky-neon",
        "name": "🌃 Neon City",
        "desc": "Cyberpunkowy fiolet z pomarańczowym horyzontem. Nocne zagonki do chmurowego miasta.",
        "params": {
            "sky_zenith_col_r": 0.10, "sky_zenith_col_g": 0.08, "sky_zenith_col_b": 0.25,
            "sky_horizon_col_r": 0.45, "sky_horizon_col_g": 0.20, "sky_horizon_col_b": 0.55,
            "sky_azimuth_east_col_r": 1.00, "sky_azimuth_east_col_g": 0.45, "sky_azimuth_east_col_b": 0.20,
            "sky_cloud_density_mult": 0.30,
        },
    },
]

# --- ROZBUDOWA do ~100 custom nieb (deterministyczne warianty motywów) ---
try:
    from citizen_expand import expanded_sky_presets
    _extra_skies = expanded_sky_presets()
    _existing_ids = {p["id"] for p in SKY_PRESETS}
    SKY_PRESETS.extend([p for p in _extra_skies if p["id"] not in _existing_ids])
except ImportError:  # pragma: no cover — plik opcjonalny
    pass

SKY_PRESETS_BY_ID: Dict[str, Dict[str, Any]] = {p["id"]: p for p in SKY_PRESETS}


def sky_preset_params(sky_preset_id: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """
    Parametry nieba po nałożeniu presetu na BASE_SKY (+ opcjonalne overrides).
    Używane przez renderer podglądu (/img) — karta pokazuje JAK NIEBO WYGLĄDA W GRZE.
    """
    sky: Dict[str, float] = dict(BASE_SKY)
    preset = SKY_PRESETS_BY_ID.get(sky_preset_id)
    if preset:
        sky.update(preset.get("params") or {})
    if extra:
        for key, value in extra.items():
            if isinstance(value, (int, float)):
                sky[key] = float(value)
    if (extra or {}).get("clouds") == "off":
        sky["sky_cloud_density_mult"] = 0.0
    elif (extra or {}).get("clouds") == "dense":
        sky["sky_cloud_density_mult"] = 1.0
    return sky

# ============================================================================
# 3. DEFINICJE KROKÓW CITIZENA (generowane — nie pobierane)
#    Każdy krok opisuje, CO generować: (plik, funkcja, parametry).
# ============================================================================

# Grupy (bez zmian względem starych, żeby nie psuć UX)
G_SKY = "1️⃣ NIEBO — custom nieba i pogoda"
G_TIME = "2️⃣ SŁOŃCE I KSIĘŻYC — kąt, kolor, czas"
G_POSTFX = "3️⃣ GRAFIKA — bloom, ekspozycja, nasycenie"
G_WEATHER = "4️⃣ POGODA — deszcz, śnieg, mgła"
G_BLOOD = "5️⃣ KOMBAT — krew"
G_MISC = "6️⃣ DODATKOWE — drobne poprawki"


def _gen_step(group: str, sid: str, name: str, desc: str, image: str,
              gen_file: str, gen_params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Krok kreatora oparty na GENERATORZE (zamiast pliku z hostingu).

    gen_file:  relatywna ścieżka w citizen/common/data (np. 'timecycle/sggd.xml')
    gen_params: co generator ma zmienić (np. {'sky_preset': 'sky-anime'})
    """
    return {
        "group": group, "id": sid, "name": name, "description": desc,
        "image": "", "image_name": image,
        "file_url": "",            # nie pobieramy — generujemy
        "file_name": None,
        "target": "citizen/common/data",
        "generated": True,         # flaga dla process_items
        "gen_file": gen_file,
        "gen_params": gen_params,
    }


CITIZEN_GENERATED_STEPS: List[Dict[str, Any]] = [
    # ---------- 1. NIEBO (custom nieba — automatycznie ~100 wariantów) ----------
    # Ręcznie curated 6 + automatyczne warianty z citizen_expand (100 motywów).
    # Generowane w pętli poniżej listy (see CITIZEN_GENERATED_STEPS += ...).
    _gen_step(G_SKY, "sky-preset-anime", "Niebo Anime", "Pastelowy błękit + mocne chmury (styl Shinkai).",
              "SKY_ANIME", "timecycle/sggd.xml", {"sky_preset": "sky-anime"}),
    _gen_step(G_SKY, "sky-preset-frostpunk", "Niebo Frostpunk", "Zimna szarość i lodowa mgła.",
              "SKY_FROSTPUNK", "timecycle/sggd.xml", {"sky_preset": "sky-frostpunk"}),
    _gen_step(G_SKY, "sky-preset-tropical", "Niebo Tropikalne", "Głęboki błękit + złote słońce.",
              "SKY_TROPICAL", "timecycle/sggd.xml", {"sky_preset": "sky-tropical"}),
    _gen_step(G_SKY, "sky-preset-bloodmoon", "Krwawy Księżyc", "Ciemna czerwień + wielki księżyc (PVP).",
              "SKY_BLOODMOON", "timecycle/sggd.xml", {"sky_preset": "sky-bloodmoon"}),
    _gen_step(G_SKY, "sky-preset-neon", "Neon City", "Cyberpunkowy fiolet + pomarańczowy horyzont.",
              "SKY_NEON", "timecycle/sggd.xml", {"sky_preset": "sky-neon"}),
    _gen_step(G_SKY, "sky-preset-clean", "Czyste + FPS", "Naturalne niebo, mniej chmur = więcej FPS.",
              "SKY_CLEAN", "timecycle/sggd.xml", {"sky_preset": "sky-clean-fps"}),

    # ---------- 2. SŁOŃCE / KSIĘŻYC / CZAS ----------
    _gen_step(G_TIME, "sun-always-noon", "Zawsze południe", "Słońce wysoko, stały jasny dzień (sun_roll=0).",
              "SUN_NOON", "levels/gta5/time.xml", {"sun_roll": 0, "mode": "dynamic"}),
    _gen_step(G_TIME, "sun-low-golden", "Złota godzina na stałe", "Słońce nisko — wieczorny klimat zawsze.",
              "SUN_GOLDEN", "levels/gta5/time.xml", {"sun_roll": 78, "mode": "dynamic"}),
    _gen_step(G_TIME, "moon-huge", "Wielki księżyc", "Duży, jasny księżyc nocą (moon_roll=-60, duży offset).",
              "MOON_HUGE", "levels/gta5/time.xml", {"moon_roll": -60, "moon_wobble_amp": 0.6}),

    # ---------- 3. GRAFIKA (postfx / bloom / exposure) ----------
    _gen_step(G_POSTFX, "postfx-vivid", "Kolory vivid", "Nasycone kolory (timecycle_mods_4.xml).",
              "POSTFX_VIVID", "timecycle/timecycle_mods_4.xml", {"style": "vivid"}),
    _gen_step(G_POSTFX, "postfx-cold", "Klimat zimny", "Zimne, desaturowane kolory (mods_4).",
              "POSTFX_COLD", "timecycle/timecycle_mods_4.xml", {"style": "cold"}),
    _gen_step(G_POSTFX, "postfx-film", "Kinowy look", "Filmowa ekspozycja + winieta (mods_4).",
              "POSTFX_FILM", "timecycle/timecycle_mods_4.xml", {"style": "film"}),

    # ---------- 4. POGODA ----------
    _gen_step(G_WEATHER, "weather-always-clear", "Zawsze słonecznie", "Naprawia broken EXTRASUNNY — pełny cycle pogodowy z dominującym słońcem.",
              "WEATHER_CLEAR", "levels/gta5/weather.xml", {"style": "always-sunny"}),
    _gen_step(G_WEATHER, "weather-stormy", "Klimat burzowy", "Częste burze i deszcz (cykl pogodowy).",
              "WEATHER_STORM", "levels/gta5/weather.xml", {"style": "stormy"}),
    _gen_step(G_WEATHER, "rain-off", "Wyłącz deszcz", "rain.NumberParticles=0 — zero kropel (FPS boost).",
              "RAIN_OFF", "visualsettings.dat", {"style": "rain-off"}),
    _gen_step(G_WEATHER, "rain-heavy", "Deszcz mocny", "Więcej cząsteczek deszczu, mokre ulice.",
              "RAIN_HEAVY", "visualsettings.dat", {"style": "rain-heavy"}),

    # ---------- 5. KOMBAT ----------
    _gen_step(G_BLOOD, "blood-anime", "Krew ANIME", "Duże tryskanie krwi (bloodfx.dat).",
              "BLOOD_ANIME", "effects/bloodfx.dat", {"style": "anime"}),
    _gen_step(G_BLOOD, "blood-minimal", "Krew minimalna", "Małe plamy, mniej efektów.",
              "BLOOD_MIN", "effects/bloodfx.dat", {"style": "minimal"}),
    _gen_step(G_BLOOD, "blood-none", "Brak krwi", "Zero efektów krwi (czystszy ekran).",
              "BLOOD_NONE", "effects/bloodfx.dat", {"style": "none"}),

    # KILL EFFECT — jak wygląda krew w momencie zabicia (SPINE/NECK, BulletLarge)
    _gen_step(G_BLOOD, "kill-extreme", "💀 Kill: EXTREME", "Ogromny wytrysk krwi przy zabiciu (x3 plamy).",
              "KILL_EXTREME", "effects/bloodfx.dat", {"kill_style": "extreme"}),
    _gen_step(G_BLOOD, "kill-strong", "💀 Kill: Strong", "Mocna krew przy zabiciu (x2 plamy).",
              "KILL_STRONG", "effects/bloodfx.dat", {"kill_style": "strong"}),
    _gen_step(G_BLOOD, "kill-off", "💀 Kill: Wyłączony", "Bez dodatkowej krwi przy zabiciu.",
              "KILL_OFF", "effects/bloodfx.dat", {"kill_style": "off"}),

    # HEAD EFFECT — strzał w głowę (wiersz HEAD, NonFatalHeadshot)
    _gen_step(G_BLOOD, "head-massive", "🎯 Head: MASSIVE", "Spektakularny efekt headshota (x2.5 plamy).",
              "HEAD_MASSIVE", "effects/bloodfx.dat", {"head_style": "massive"}),
    _gen_step(G_BLOOD, "head-big", "🎯 Head: Big", "Wyraźny efekt strzału w głowę (x1.7 plamy).",
              "HEAD_BIG", "effects/bloodfx.dat", {"head_style": "big"}),
    _gen_step(G_BLOOD, "head-off", "🎯 Head: Wyłączony", "Bez dodatkowego efektu headshota.",
              "HEAD_OFF", "effects/bloodfx.dat", {"head_style": "off"}),

    # ---------- 6. DODATKOWE ----------
    _gen_step(G_MISC, "clouds-off", "Chmury OFF", "Czyste niebo bez chmur (sky_cloud_density_mult=0).",
              "CLOUDS_OFF", "timecycle/sggd.xml", {"sky_preset": None, "clouds": "off"}),
    _gen_step(G_MISC, "clouds-dense", "Chmury gęste", "Więcej chmur (dramatyczne niebo).",
              "CLOUDS_DENSE", "timecycle/sggd.xml", {"sky_preset": None, "clouds": "dense"}),
]

# --- DOKLEJKA: automatyczne warianty custom nieb (citizen_expand) ---
try:
    from citizen_expand import expanded_sky_presets
    _preset_ids = {p["id"] for p in SKY_PRESETS}
    for _sky in expanded_sky_presets():
        if _sky["id"] in _preset_ids and not any(
                s.get("gen_params", {}).get("sky_preset") == _sky["id"]
                for s in CITIZEN_GENERATED_STEPS):
            CITIZEN_GENERATED_STEPS.append(_gen_step(
                G_SKY, f"sky-x-{_sky['id']}", f"Niebo {_sky['name']}", _sky["desc"],
                _sky["id"].upper(), "timecycle/sggd.xml", {"sky_preset": _sky["id"]}))
except ImportError:  # pragma: no cover
    pass

# ============================================================================
# 4. GENERATORY — funkcje produkujące zawartość plików
# ============================================================================

GEN_LOG_NAME = "CitizenGen"


def _fmt(v: float) -> str:
    """Format liczby jak w oryginalnych plikach R* (4 miejsca, kropka)."""
    return f"{float(v):.4f}"


# ---------------------------------------------------------------- sggd.xml --
def generate_sggd_xml(params: Dict[str, Any]) -> str:
    """
    Główne niebo. Buduje pełny <cycle name="EXTRASUNNY"> z parametrami nieba.
    Struktura zgodna z czystym citizenem (cycle per typ pogody).
    """
    sky: Dict[str, float] = dict(BASE_SKY)
    sky_preset_id = params.get("sky_preset")
    if sky_preset_id and sky_preset_id in SKY_PRESETS_BY_ID:
        sky.update(SKY_PRESETS_BY_ID[sky_preset_id]["params"])

    if params.get("clouds") == "off":
        sky["sky_cloud_density_mult"] = 0.0
    elif params.get("clouds") == "dense":
        sky["sky_cloud_density_mult"] = 1.0

    # Kluczowe grupy parametrów nieba (wszystkie 13 slotów czasowych = ta sama wartość
    # — stabilne niebo przez cały dzień; to robi też czysty citizen).
    groups = {
        "sky_zenith_col": ["r", "g", "b"],
        "sky_horizon_col": ["r", "g", "b"],
        "sky_azimuth_east_col": ["r", "g", "b"],
        "sky_azimuth_west_col": ["r", "g", "b"],
        "sky_azimuth_transition_col": ["r", "g", "b"],
    }

    def const_line(tag: str, value: float) -> str:
        vals = " ".join(_fmt(value) for _ in range(13))
        return f"\t\t\t<{tag}> {vals} </{tag}>"

    lines: List[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append("<!-- FiveM Mod Foundry — generator nieba (citizen/common/data/timecycle/sggd.xml) -->")
    lines.append('<CTimeCycleModificationData>')
    lines.append('\t<cycle name="EXTRASUNNY">')

    # kolory nieba (3 kanały per grupa)
    for group, channels in groups.items():
        for ch in channels:
            key = f"{group}_{ch}"
            value = sky.get(key, 0.0)
            inten_key = f"{group}_inten"
            lines.append(const_line(key, value))
        lines.append(const_line(f"{group}_inten", sky.get(f"{group}_inten", 1.0)))

    # chmury
    for key in ("sky_cloud_density_mult", "sky_cloud_gen_frequency", "sky_cloud_gen_scale",
                "sky_cloud_gen_threshold", "sky_cloud_gen_softness"):
        lines.append(const_line(key, sky.get(key, 0.0)))

    # księżyc i sunburst
    lines.append(const_line("sky_moon_iten", sky.get("sky_moon_iten", 0.35)))
    lines.append(const_line("sky_moon_disc_size", sky.get("sky_moon_disc_size", 1.0)))
    lines.append(const_line("sky_sunburst_imten", sky.get("sky_sunburst_imten", 1.0)))

    lines.append('\t</cycle>')
    lines.append('</CTimeCycleModificationData>')
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------- weather.xml --
def generate_weather_xml(params: Dict[str, Any]) -> str:
    """
    Pogoda. WAŻNE: czysty citizen ma BROKEN weather.xml — jest tam tylko
    EXTRASUNNY z HALLOWEENclouds (dlatego u graczy bywa 'zepsute niebo').
    Bot generuje PEŁNY, poprawny cykl pogodowy.
    """
    style = params.get("style", "always-sunny")

    # Pełny zestaw typów pogody GTA V z wagami (prawdopodobieństwami) per styl
    # weight = jak często dany typ pada w cyklu
    if style == "always-sunny":
        weights = {"EXTRASUNNY": 80, "CLEAR": 15, "CLOUDS": 5, "SMOG": 0, "FOGGY": 0,
                   "OVERCAST": 0, "RAIN": 0, "THUNDER": 0, "CLEARING": 0, "NEUTRAL": 0, "SNOW": 0, "BLIZZARD": 0,
                   "SNOWLIGHT": 0, "XMAS": 0, "HALLOWEEN": 0}
    elif style == "stormy":
        weights = {"EXTRASUNNY": 15, "CLEAR": 10, "CLOUDS": 15, "OVERCAST": 20,
                   "RAIN": 20, "THUNDER": 15, "CLEARING": 5, "FOGGY": 0, "SMOG": 0,
                   "NEUTRAL": 0, "SNOW": 0, "BLIZZARD": 0, "SNOWLIGHT": 0, "XMAS": 0, "HALLOWEEN": 0}
    else:  # balanced
        weights = {"EXTRASUNNY": 30, "CLEAR": 15, "CLOUDS": 10, "OVERCAST": 10,
                   "RAIN": 10, "THUNDER": 5, "CLEARING": 5, "FOGGY": 5, "SMOG": 5,
                   "NEUTRAL": 0, "SNOW": 0, "BLIZZARD": 0, "SNOWLIGHT": 0, "XMAS": 0, "HALLOWEEN": 0}

    # Uproszczony opis każdego typu (to NIE jest pełny weather.xml R*, ale
    # spójny i poprawny XML — poprawia broken EXTRASUNNY)
    defaults = {
        "EXTRASUNNY": dict(sun=1, cloud=0, wind_min=0, wind_max=0, rain=0, snow=0, fog=0, lightning=False),
        "CLEAR":      dict(sun=1, cloud=0, wind_min=0, wind_max=1, rain=0, snow=0, fog=0, lightning=False),
        "CLOUDS":     dict(sun=0, cloud=1, wind_min=0, wind_max=1, rain=0, snow=0, fog=0, lightning=False),
        "SMOG":       dict(sun=0, cloud=0, wind_min=0, wind_max=0, rain=0, snow=0, fog=1, lightning=False),
        "FOGGY":      dict(sun=0, cloud=0, wind_min=0, wind_max=0, rain=0, snow=0, fog=1, lightning=False),
        "OVERCAST":   dict(sun=0, cloud=1, wind_min=1, wind_max=2, rain=0, snow=0, fog=0, lightning=False),
        "RAIN":       dict(sun=0, cloud=1, wind_min=1, wind_max=2, rain=1, snow=0, fog=0, lightning=False),
        "THUNDER":    dict(sun=0, cloud=1, wind_min=2, wind_max=4, rain=1, snow=0, fog=0, lightning=True),
        "CLEARING":   dict(sun=1, cloud=1, wind_min=0, wind_max=1, rain=0, snow=0, fog=0, lightning=False),
        "NEUTRAL":    dict(sun=0, cloud=0, wind_min=0, wind_max=1, rain=0, snow=0, fog=0, lightning=False),
        "SNOW":       dict(sun=0, cloud=1, wind_min=0, wind_max=1, rain=0, snow=1, fog=0, lightning=False),
        "BLIZZARD":   dict(sun=0, cloud=1, wind_min=2, wind_max=4, rain=0, snow=1, fog=1, lightning=False),
        "SNOWLIGHT":  dict(sun=0, cloud=1, wind_min=0, wind_max=1, rain=0, snow=1, fog=0, lightning=False),
        "XMAS":       dict(sun=0, cloud=1, wind_min=0, wind_max=1, rain=0, snow=1, fog=0, lightning=False),
        "HALLOWEEN":  dict(sun=0, cloud=1, wind_min=0, wind_max=0, rain=0, snow=0, fog=1, lightning=False),
    }

    lines: List[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append("<!-- FiveM Mod Foundry — generator pogody (citizen/common/data/levels/gta5/weather.xml) -->")
    lines.append('<CContentsOfWeatherXmlFile>')
    lines.append('  <VersionNumber value="1.000000"/>')
    lines.append('  <WeatherGpuFx>')
    lines.append('  </WeatherGpuFx>')
    lines.append('  <WeatherTypes>')

    for wtype, weight in weights.items():
        if weight <= 0:
            continue
        d = defaults[wtype]
        lines.append('  <Item>')
        lines.append(f'    <Name>{wtype}</Name>')
        lines.append(f'    <Sun value="{d["sun"]}"/>')
        lines.append(f'    <Cloud value="{d["cloud"]}"/>')
        lines.append(f'    <WindMin value="{d["wind_min"]}"/>')
        lines.append(f'    <WindMax value="{d["wind_max"]}"/>')
        lines.append(f'    <Rain value="{d["rain"]}"/>')
        lines.append(f'    <Snow value="{d["snow"]}"/>')
        lines.append(f'    <SnowMist value="0"/>')
        lines.append(f'    <Fog value="{d["fog"]}"/>')
        lines.append(f'    <RippleBumpiness value="0" />')
        lines.append(f'    <RippleMinBumpiness value="0" />')
        lines.append(f'    <RippleMaxBumpiness value="0" />')
        lines.append(f'    <RippleBumpinessWindScale value="0" />')
        lines.append(f'    <RippleScale value="0" />')
        lines.append(f'    <RippleSpeed value="0" />')
        lines.append(f'    <RippleVelocityTransfer value="0" />')
        lines.append(f'    <OceanBumpiness value="0" />')
        lines.append(f'    <DeepOceanScale value="0" />')
        lines.append(f'    <OceanNoiseMinAmplitude value="0" />')
        lines.append(f'    <OceanWaveAmplitude value="0" />')
        lines.append(f'    <ShoreWaveAmplitude value="0" />')
        lines.append(f'    <OceanWaveWindScale value="0" />')
        lines.append(f'    <ShoreWaveWindScale value="0" />')
        lines.append(f'    <OceanWaveMinAmplitude value="0" />')
        lines.append(f'    <ShoreWaveMaxAmplitude value="0" />')
        lines.append(f'    <OceanFoamIntensity value="0" />')
        lines.append(f'    <OceanFoamScale value="0" />')
        lines.append(f'    <RippleDisturb value="0" />')
        lines.append(f'    <Lightning value="{"true" if d["lightning"] else "false"}"/>')
        lines.append(f'    <Sandstorm value="false"/>')
        lines.append(f'    <OldSettingName>-</OldSettingName>')
        lines.append(f'    <DropSettingName>-</DropSettingName>')
        lines.append(f'    <MistSettingName>-</MistSettingName>')
        lines.append(f'    <GroundSettingName>-</GroundSettingName>')
        # cykl: waga danego typu = szansa wystąpienia (TimeMult)
        lines.append(f'    <TimeCycleFilename>COMMON:/DATA/TIMECYCLE/sggd.xml</TimeCycleFilename>')
        lines.append(f'    <CloudSettingsName>HALLOWEENclouds</CloudSettingsName>')
        lines.append('  </Item>')

    lines.append('  </WeatherTypes>')
    lines.append('  <WeatherCycles>')

    for wtype, weight in weights.items():
        if weight <= 0:
            continue
        lines.append(f'    <Item>')
        lines.append(f'      <CycleName>{wtype}</CycleName>')
        lines.append(f'      <TimeMult value="{weight}" />')
        lines.append(f'    </Item>')

    lines.append('  </WeatherCycles>')
    lines.append('</CContentsOfWeatherXmlFile>')
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------- time.xml --
def generate_time_xml(params: Dict[str, Any]) -> str:
    """Słońce / księżyc — struktura zgodna z czystym citizenem."""
    sun_roll = params.get("sun_roll", 122)
    moon_roll = params.get("moon_roll", -122)
    moon_amp = params.get("moon_wobble_amp", 0.2)
    mode = params.get("mode", "dynamic")

    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- FiveM Mod Foundry — generator czasu (citizen/common/data/levels/gta5/time.xml) -->",
        f'<time_data version="1.000000" mode="{mode}">',
        f'  <suninfo sun_roll="{int(sun_roll)}" sun_yaw="0"/>',
        f'  <mooninfo moon_roll="{int(moon_roll)}" moon_wobble_freq="2" '
        f'moon_wobble_amp="{_fmt(moon_amp)}" moon_wobble_offset="0.375"/>',
        '  <sample name="00:00" hour="0" duration="4" uw_tc_mod="underwater"/>',
        '</time_data>',
    ]) + "\n"


# -------------------------------------------------------- visualsettings.dat --
def generate_visualsettings_dat(params: Dict[str, Any]) -> str:
    """Deszcz / pogoda detale. Struktura: 'sekcja.wartosc liczba' jak w R*."""
    style = params.get("style", "default")
    if style == "rain-off":
        rain_particles = 0
        rain_alpha = 0.0
        puddle = 0.0
    elif style == "rain-heavy":
        rain_particles = 1200
        rain_alpha = 1.0
        puddle = 1.0
    else:
        rain_particles = 500
        rain_alpha = 0.7
        puddle = 0.5

    lines: List[str] = []
    lines.append("<!-- FiveM Mod Foundry — generator visualsettings.dat -->")
    lines.append("")
    lines.append(f"rain.NumberParticles {rain_particles}")
    lines.append("rain.UseLitShader 1")
    lines.append("rain.gravity.x 0")
    lines.append("rain.gravity.y 0")
    lines.append("rain.gravity.z -1")
    lines.append(f"rain.fadeInScale {rain_alpha}")
    lines.append(f"rain.diffuse {rain_alpha}")
    lines.append(f"rain.ambient {rain_alpha}")
    lines.append("rain.wrapScale 0")
    lines.append("rain.wrapBias 0")
    lines.append("rain.defaultlight.red 0.8")
    lines.append("rain.defaultlight.green 0.8")
    lines.append("rain.defaultlight.blue 0.85")
    lines.append("rain.defaultlight.alpha 1")
    lines.append("")
    lines.append(f"puddle.createdist {puddle}")
    lines.append(f"puddle.raindist {puddle}")
    lines.append(f"puddle.amount {puddle}")
    lines.append(f"puddle.reflection {puddle}")
    lines.append("")
    lines.append("sky.sun.centreStart 0.5")
    lines.append("sky.sun.centreEnd 1.0")
    lines.append("sky.cloudWarp 1.0")
    lines.append("sky.cloudInscatteringRange 1000.0")
    lines.append("sky.cloudEdgeSmooth 100.0")
    lines.append("sky.GameCloudSpeed 1.0")
    lines.append("")
    return "\n".join(lines) + "\n"


# ------------------------------------------------ timecycle_mods_4.xml --
# Czysty citizen ma w timecycle_mods_4.xml jeden modifier 'hud_def_desat_cold_kill'
# (winieta + tonemapping). Bot nadpisuje go własnymi stylami look'u gry.

def _mods4_modifier(name: str, entries: List[Tuple[str, float]]) -> str:
    """Pojedynczy <modifier> w formacie timecycle_mods_4 (wartość + delta 0.000)."""
    body = "".join(
        f"    <{tag}>{_fmt(val)} 0.000</{tag}>\n" for tag, val in entries
    )
    return (f'  <modifier name="{name}" numMods="{len(entries)}" userFlags="0">\n'
            f"{body}  </modifier>\n")


def generate_timecycle_mods4_xml(params: Dict[str, Any]) -> str:
    """Globalny look gry: vivid / cold / film (struktura jak oryginalny mods_4)."""
    style = params.get("style", "vivid")
    if style == "vivid":
        entries = [
            ("postfx_correct_col_r", 1.10), ("postfx_correct_col_g", 1.08), ("postfx_correct_col_b", 1.02),
            ("postfx_decontrast", -0.15), ("postfx_bright", 0.02), ("postfx_exposure", 0.10),
            ("postfx_intensity_bloom", 0.25),
        ]
        name = "foundry_vivid"
    elif style == "cold":
        entries = [
            ("postfx_correct_col_r", 0.92), ("postfx_correct_col_g", 1.00), ("postfx_correct_col_b", 1.12),
            ("postfx_desat", 0.25), ("postfx_exposure", -0.05),
            ("postfx_vignetting_intensity", 0.60), ("postfx_vignetting_radius", 10.0),
        ]
        name = "foundry_cold"
    else:  # film
        entries = [
            ("postfx_exposure", -0.08),
            ("postfx_tonemap_filmic_a", 4.0), ("postfx_tonemap_filmic_b", 0.30),
            ("postfx_tonemap_filmic_c", 0.64), ("postfx_tonemap_filmic_d", 0.384),
            ("postfx_tonemap_filmic_e", 0.01), ("postfx_tonemap_filmic_f", 0.10),
            ("postfx_tonemap_filmic_w", 4.0),
            ("postfx_vignetting_intensity", 1.0), ("postfx_vignetting_radius", 11.5),
            ("postfx_vignetting_contrast", 0.04),
        ]
        name = "foundry_film"
    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- FiveM Mod Foundry — generator look'u gry (timecycle_mods_4.xml) -->",
        '<timecycle_modifier_data version="1.000000">',
        _mods4_modifier(name, entries).rstrip("\n"),
        '</timecycle_modifier_data>',
    ]) + "\n"


# ------------------------------------------------------------- bloodfx.dat --
_BLOOD_ROWS = [
    "BUTTOCKS", "THIGH_LEFT", "SHIN_LEFT", "FOOT_LEFT", "THIGH_RIGHT", "SHIN_RIGHT", "FOOT_RIGHT",
    "SPINE0", "SPINE1", "SPINE2", "SPINE3", "CLAVICLE_LEFT", "UPPER_ARM_LEFT", "LOWER_ARM_LEFT",
    "HAND_LEFT", "CLAVICLE_RIGHT", "UPPER_ARM_RIGHT", "LOWER_ARM_RIGHT", "HAND_RIGHT",
    "NECK", "HEAD", "ANIMAL_DEFAULT",
]

# Wiersze liczące się przy KILL EFFECT (krwawienie w momencie zabicia)
_KILL_ROWS = {"SPINE0", "SPINE1", "SPINE2", "SPINE3", "BUTTOCKS", "NECK"}


def _blood_row(bone: str, scale: int, force: int, head_scale: int, kill_force: int) -> str:
    """
    Jeden wiersz tabeli BLOODFX (format zgodny z czystym citizenem).

    • wiersz HEAD dostaje osobną skalę (HEAD EFFECT — strzał w głowę)
    • wiersze SPINE/NECK/BUTTOCKS dostają kill_force (KILL EFFECT)
    """
    s = scale
    if bone == "HEAD":
        s = head_scale if head_scale else scale
    elif bone in _KILL_ROWS:
        force = max(force, kill_force)
    return (
        f"{bone}\t\t\t0 {s:03d} {s:03d} {s:03d} {s:03d}\t"
        f"{force:03d} {force:03d} {force:03d} 295\t{force:03d}\t\t"
        f"108 {force:03d} 201\t\t105 105 0   0   105\t\t0\t301 402\t402\t\t900\t950"
    )


def generate_bloodfx_dat(params: Dict[str, Any]) -> str:
    """
    Krew + KILL EFFECT + HEAD EFFECT (jeden plik bloodfx.dat).

    params:
      style      — anime / minimal / none (bazowa krew)
      kill_style — efekt przy zabiciu: extreme / strong / normal / off
      head_style — efekt trafienia w głowę: massive / big / normal / off
    """
    style = params.get("style", "default")
    if style == "anime":
        scale, force = 160, 200
    elif style == "minimal":
        scale, force = 40, 50
    else:  # none / default
        scale, force = 0, 0

    # KILL EFFECT — siła wytrysku krwi przy zabiciu (SPINE/NECK/BUTTOCKS)
    kill_style = params.get("kill_style") or "normal"
    kill_force_map = {"extreme": 400, "strong": 280, "normal": force, "off": 0}
    kill_force = kill_force_map.get(kill_style, force)

    # HEAD EFFECT — osobna skala wiersza HEAD (strzał w głowę)
    head_style = params.get("head_style") or "normal"
    head_scale_map = {"massive": 250, "big": 180, "normal": scale, "off": 0}
    head_scale = head_scale_map.get(head_style, scale)

    lines: List[str] = []
    lines.append(f"{max(scale, head_scale) / 10:.2f}")
    lines.append("")
    lines.append("BLOODFX_TABLE_ALIVE_START")
    for bone in _BLOOD_ROWS:
        lines.append(_blood_row(bone, scale, force, head_scale, kill_force))
    lines.append("BLOODFX_TABLE_ALIVE_END")
    lines.append("")
    lines.append("BLOODFX_TABLE_DEAD_START")
    lines.append("BLOODFX_TABLE_DEAD_END")
    lines.append("")
    lines.append("BLOODFX_TABLE_ALIVE_MP_START")
    for bone in _BLOOD_ROWS:
        lines.append(_blood_row(bone, scale, force, head_scale, kill_force))
    lines.append("BLOODFX_TABLE_ALIVE_MP_END")
    lines.append("")
    lines.append("BLOODFX_TABLE_DEAD_MP_START")
    lines.append("BLOODFX_TABLE_DEAD_MP_END")
    lines.append("")
    lines.append("BLOODFX_ENTRY_INFO_START")
    # 105 = NonFatalHeadshot: HEAD EFFECT skaluje też rozmiar plam po strzale w głowę
    head_entry_scale = {"massive": 2.5, "big": 1.7, "normal": 1.0, "off": 0.0}.get(head_style, 1.0)
    lines.append(
        f"105\t\t{head_entry_scale:.1f}\t\t1010\t1010\t1015\t1015\t0\t\t0\t\t50  0\t0\t\t"
        f"0.7\t\t\t0.8\t\t\t20.0\t10.0\t4\t\t2\t\t0.25\t0.6\t\t0.01\t0.6\t\t1.8\t\t1.2\t\t1.8\t\t0.8\t\t1.8\t\t1.2\t\t1.8\t\t-1.0\t-1.0\t0.3\t\t0.01\t0.5\t\t0.5\t\t"
        f"exp_xs_ray    \t\t\texp_xs_ray      \t\texp_xs_ray      \t\texp_xs_ray    \t\t\t"
        f"0.5\t\t\t1.0\t\tNonFatalHeadshot\t\tArmorBullet\t\t\t\tArmorBullet"
    )
    # 505 = BulletLarge: KILL EFFECT skaluje plamy po śmiertelnych strzałach
    kill_entry_scale = {"extreme": 3.0, "strong": 2.0, "normal": 1.0, "off": 0.0}.get(kill_style, 1.0)
    lines.append(
        f"505\t\t{kill_entry_scale:.1f}\t\t1010\t1010\t1015\t1015\t0\t\t0\t\t50  0\t0\t\t"
        f"0.7\t\t\t0.8\t\t\t20.0\t10.0\t4\t\t2\t\t0.25\t0.6\t\t0.01\t0.6\t\t1.8\t\t1.2\t\t1.8\t\t0.8\t\t1.8\t\t1.2\t\t1.8\t\t-1.0\t-1.0\t0.3\t\t0.01\t0.5\t\t0.5\t\t"
        f"exp_xs_ray    \t\t   \texp_xs_ray      \t\texp_xs_ray      \t\texp_xs_ray    \t\t\t"
        f"0.7\t\t\t1.0\t\tBulletLarge\t\t\t\tArmorBullet\t\t\t\tArmorBullet"
    )
    lines.append("BLOODFX_ENTRY_INFO_END")
    lines.append("")
    lines.append("BLOODFX_EXIT_INFO_START")
    lines.append("BLOODFX_EXIT_INFO_END")
    lines.append("")
    return "\n".join(lines) + "\n"


# ============================================================================
# 5. ROUTER GENERATORÓW — jeden wpis dla process_items
# ============================================================================

_GENERATORS = {
    "timecycle/sggd.xml": generate_sggd_xml,
    "timecycle/timecycle_mods_4.xml": generate_timecycle_mods4_xml,
    "levels/gta5/weather.xml": generate_weather_xml,
    "levels/gta5/time.xml": generate_time_xml,
    "visualsettings.dat": generate_visualsettings_dat,
    "effects/bloodfx.dat": generate_bloodfx_dat,
}


def generate_citizen_file(gen_file: str, params: Dict[str, Any]) -> Optional[str]:
    """Zwraca ZAWARTOŚĆ generowanego pliku albo None, gdy brak generatora."""
    factory = _GENERATORS.get(gen_file)
    if factory is None:
        return None
    return factory(params or {})


def all_generated_files() -> List[str]:
    """Lista plików, które umiemy wygenerować (do docs/INSTRUKCJA)."""
    return sorted(_GENERATORS.keys())
