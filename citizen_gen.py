"""
==============================================================================
 GENERATOR PLIKÓW CITIZENA (na podstawie paczki z citizen.rar)
==============================================================================
 Zasada: TE SAME pliki co w paczce, tylko ze zmienionymi wartościami.
 Bot nie wymyśla plików od zera — bierze szablony z `citizen_templates/`
 (skopiowane z citizen.rar: MATOL.xml, timecycle_mods_4.xml, visualsettings.dat,
 clouds.xml, cloudkeyframes.xml, explosionfx.dat, firefx.dat, entityfx.dat,
 ui/pausemenu.xml) i patchuje w nich konkretne parametry.

 Pliki generowane/patchowane (ścieżki jak w citizen/common/data):
   • timecycle/MATOL.xml              — niebo, chmury, słońce/księżyc, woda,
                                        mgła, światło, postfx, blur, wydajność
   • levels/gta5/time.xml             — CZAS (zawsze dzień / zawsze noc / cykl)
   • levels/gta5/weather.xml          — POGODA (pełny cykl, naprawiony)
   • visualsettings.dat               — deszcz, cykl pogody, chmury, cienie…
   • clouds.xml / cloudkeyframes.xml  — geometria i gęstość chmur
   • timecycle/timecycle_mods_4.xml   — KILL EFFECT (kolor, siła, blur)
   • effects/bloodfx.dat              — krew (anime / minimalna / brak)
   • effects/explosionfx.dat          — siła eksplozji, przypalenia
   • effects/firefx.dat               — czas i siła palenia
   • effects/entityfx.dat             — dym, para, kurz, cząstki otoczenia
   • ui/pausemenu.xml                 — HUD / menu pauzy

 Nieba NIE są pobierane z YouTube — parametry nieba siedzą w MATOL.xml i bot
 ustawia je sam, z krzywą dzień/noc (13 kluczy czasowych z paczki).
==============================================================================
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import citizen_mods
import citizen_patch as cp

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
G_SKY = "1️⃣ NIEBO — skydome i custom nieba"
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


CITIZEN_GENERATED_STEPS: List[Dict[str, Any]] = []

# ------ 1. NIEBO: 6 curated stylów + ~100 motywów (wszystkie piszą MATOL.xml) ---

_SKY_CURATED: Tuple[str, ...] = ("sky-anime", "sky-frostpunk", "sky-tropical",
                                 "sky-bloodmoon", "sky-neon", "sky-clean-fps")


def _sky_step(preset_id: str, name: str, desc: str, image: str,
              step_id: str = "", extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Krok nieba. Parametry presetu (dzień + noc) są wpisane WPROST do kroku,
    dzięki czemu generator nie musi znać katalogu presetów (brak cyklicznych
    importów), a scalanie parametrów w proces_items działa jak dla innych plików.
    """
    params: Dict[str, Any] = dict(sky_preset_params(preset_id))
    params["sky_preset"] = preset_id
    if extra:
        params.update(extra)
    if step_id:
        sid = step_id
    elif preset_id.startswith("sky-"):
        sid = f"sky-preset-{preset_id[4:]}"
    else:
        sid = preset_id
    return _gen_step(G_SKY, sid, name, desc, image,
                     citizen_mods.MOD_FILES["matol"], params)


for _pid in _SKY_CURATED:
    _preset = SKY_PRESETS_BY_ID[_pid]
    CITIZEN_GENERATED_STEPS.append(_sky_step(
        _pid, _preset["name"], _preset["desc"],
        "SKY_" + _pid[4:].upper().replace("-", "_")))

# --- ROZBUDOWA do ~100 custom nieb (deterministyczne warianty motywów) ---
try:
    from citizen_expand import expanded_sky_presets
    for _sky in expanded_sky_presets():
        if _sky["id"] not in SKY_PRESETS_BY_ID:
            continue
        CITIZEN_GENERATED_STEPS.append(_sky_step(
            _sky["id"], f"Niebo {_sky['name']}", _sky["desc"],
            _sky["id"].upper().replace("-", "_"), step_id=f"sky-x-{_sky['id']}"))
except ImportError:  # pragma: no cover — plik opcjonalny
    pass

# --- 2..17. POZOSTAŁE OPCJE CITIZENA (z citizen_mods: czas, pogoda, woda, mgła,
#     światło, postfx, blur, kill/head effect, eksplozje, dym, HUD, FPS) ---
CITIZEN_GENERATED_STEPS += citizen_mods.MOD_STEPS

# ============================================================================
# 4. GENERATORY — funkcje produkujące zawartość plików
# ============================================================================

GEN_LOG_NAME = "CitizenGen"


def _fmt(v: float) -> str:
    """Format liczby jak w oryginalnych plikach R* (4 miejsca, kropka)."""
    return f"{float(v):.4f}"


# ------------------------------------------------------------- weather.xml --
# Style pogody: nazwa → wagi typów w cyklu (TimeMult). Zgodne z formatem paczki.
WEATHER_STYLES: Dict[str, Dict[str, int]] = {
    "always-sunny": {"EXTRASUNNY": 80, "CLEAR": 20},
    "always-rain": {"RAIN": 85, "THUNDER": 10, "CLEARING": 5},
    "stormy": {"EXTRASUNNY": 15, "CLEAR": 10, "CLOUDS": 15, "OVERCAST": 20,
               "RAIN": 20, "THUNDER": 15, "CLEARING": 5},
    "always-fog": {"FOGGY": 85, "SMOG": 15},
    "smog": {"SMOG": 70, "FOGGY": 25, "OVERCAST": 5},
    "snow": {"SNOW": 65, "BLIZZARD": 25, "SNOWLIGHT": 10},
    "xmas": {"XMAS": 80, "SNOW": 15, "SNOWLIGHT": 5},
    "balanced": {"EXTRASUNNY": 30, "CLEAR": 15, "CLOUDS": 10, "OVERCAST": 10,
                 "RAIN": 10, "THUNDER": 5, "CLEARING": 5, "FOGGY": 5, "SMOG": 5},
}

_WEATHER_CLOUDS = {
    "always-sunny": "CLEARclouds", "always-rain": "HEAVYclouds", "stormy": "HEAVYclouds",
    "always-fog": "SMOGclouds", "smog": "SMOGclouds", "snow": "SNOWYclouds",
    "xmas": "HALLOWEENclouds", "balanced": "HEAVYclouds",
}


def _weather_weights(style: str) -> Dict[str, int]:
    """Wagi typów pogody dla danego stylu (0 = typ nie występuje)."""
    table = WEATHER_STYLES.get(style) or WEATHER_STYLES["balanced"]
    full = {name: 0 for name in (
        "EXTRASUNNY", "CLEAR", "CLOUDS", "SMOG", "FOGGY", "OVERCAST", "RAIN",
        "THUNDER", "CLEARING", "NEUTRAL", "SNOW", "BLIZZARD", "SNOWLIGHT",
        "XMAS", "HALLOWEEN")}
    full.update(table)
    return full


def _cloud_set_for_weather(style: str) -> str:
    """Domyślne chmury dla stylu pogody (CloudSettingsName z paczki)."""
    return _WEATHER_CLOUDS.get(style, "HEAVYclouds")



def generate_weather_xml(params: Dict[str, Any]) -> str:
    """
    Pogoda. WAŻNE: czysty citizen ma BROKEN weather.xml — jest tam tylko
    EXTRASUNNY z HALLOWEENclouds (dlatego u graczy bywa 'zepsute niebo').
    Bot generuje PEŁNY, poprawny cykl pogodowy.
    """
    style = params.get("style", "always-sunny")

    # Pełny zestaw typów pogody GTA V z wagami (prawdopodobieństwami) per styl
    # weight = jak często dany typ pada w cyklu
    weights = _weather_weights(style)

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
        lines.append(f'    <TimeCycleFilename>COMMON:/DATA/TIMECYCLE/MATOL.XML</TimeCycleFilename>')
        lines.append(f'    <CloudSettingsName>{_cloud_set_for_weather(style)}</CloudSettingsName>')
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
    # --- patchowane pliki z paczki (te same pliki, zmienione wartości) ---
    "timecycle/MATOL.xml": citizen_mods.generate_matol_xml,
    "timecycle/timecycle_mods_4.xml": citizen_mods.generate_mods4_xml,
    "visualsettings.dat": citizen_mods.generate_visualsettings_dat,
    "clouds.xml": citizen_mods.generate_clouds_xml,
    "cloudkeyframes.xml": citizen_mods.generate_cloudkeyframes_xml,
    "effects/explosionfx.dat": citizen_mods.generate_explosionfx_dat,
    "effects/firefx.dat": citizen_mods.generate_firefx_dat,
    "effects/entityfx.dat": citizen_mods.generate_entityfx_dat,
    "ui/pausemenu.xml": citizen_mods.generate_pausemenu_xml,
    "effects/bloodfx.dat": citizen_mods.generate_bloodfx_dat,
    "effects/weaponfx.dat": citizen_mods.generate_weaponfx_dat,
    "effects/wheelfx.dat": citizen_mods.generate_wheelfx_dat,
    "effects/decals.dat": citizen_mods.generate_decals_dat,
    # --- pliki budowane w całości (małe, w pełni znany format) ---
    "levels/gta5/time.xml": citizen_mods.generate_time_xml,
    "levels/gta5/weather.xml": generate_weather_xml,
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
