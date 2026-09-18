"""
==============================================================================
 citizen_mods.py — NOWE OPCJE CITIZENA (katalog + generatory)
==============================================================================
Wszystko oparte na PRAWDZIWYCH plikach z paczki (citizen.rar → citizen_templates)
i patchowane przez `citizen_patch`. Dzięki temu jeden plik obsługuje WIELE opcji
naraz (np. niebo + woda + mgła + światło → jeden `MATOL.xml`), bo bot scala
parametry kroków piszących do tego samego pliku.

Grupy (zakładki w studiu WWW) odpowiadają kategoriom z paczki:
  ⏰ CZAS (always day / always night), 🌦 POGODA, ☀️ SŁOŃCE I KSIĘŻYC, ☁️ CHMURY,
  💧 WODA, 🌫 MGŁA, 💡 ŚWIATŁO, 🎨 KOLORY (POSTFX), 🖼 BLUR/DOF/LENS,
  ⚙️ VISUAL SETTINGS, 🩸 KREW, 💀 KILL EFFECT, 🎯 HEAD EFFECT,
  💥 EKSPLOZJE I OGIEŃ, 💨 DYM I CZĄSTKI, 🖥 HUD/UI, 🚀 WYDAJNOŚĆ (FPS)
==============================================================================
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import citizen_patch as cp

# ============================================================================
# 1. NAGŁÓWKI PLIKÓW (krótka stopka generatora — paczka zostaje „czysta")
# ============================================================================

STAMP = "<!-- FiveM Mod Foundry — te same pliki, zmienione wartości -->"


def _stamp_xml(text: str) -> str:
    """Dokłada komentarz generatora zaraz po deklaracji XML."""
    for marker in ('<?xml version="1.0" encoding="UTF-8"?>',
                   '<?xml version="1.0" encoding="utf-8"?>'):
        if text.startswith(marker):
            return marker + "\n" + STAMP + text[len(marker):]
    return STAMP + "\n" + text


def _stamp_dat(text: str) -> str:
    return text


# ============================================================================
# 2. MATOL.xml — NIEBO, CHMURY, WODA, MGŁA, ŚWIATŁO, POSTFX, BLUR, FPS
#    Klucze czasowe w paczce (13 kolumn) — budujemy z nich krzywą dzień/noc.
# ============================================================================

MATOL_HOURS: Tuple[int, ...] = (0, 5, 6, 7, 10, 12, 16, 17, 18, 19, 20, 21, 22)
# 1.0 = pełna noc, 0.0 = pełny dzień (waga przy interpolacji kolorów)
NIGHT_WEIGHT: Tuple[float, ...] = (1.0, 0.55, 0.30, 0.10, 0.0, 0.0,
                                   0.0, 0.05, 0.20, 0.45, 0.70, 0.85, 1.0)

CLOUD_SETTINGS = {
    "default": "HEAVYclouds",
    "heavy": "HEAVYclouds",
    "hallow": "HALLOWEENclouds",
    "smog": "SMOGclouds",
    "clear": "CLEARclouds",
    "snow": "SNOWYclouds",
    "wispy": "WISPclouds",
}


def _night_of(colour: Sequence[float], depth: float = 0.80) -> Tuple[float, float, float]:
    """Nocna wersja koloru: mocno ciemniejsza z niebieskim dolnym światłem."""
    r, g, b = (float(c) for c in colour)
    return (r * (1.0 - depth) + 0.010 * depth,
            g * (1.0 - depth) + 0.020 * depth,
            b * (1.0 - depth) + 0.055 * depth)


def _curve(day: Sequence[float], night: Optional[Sequence[float]] = None,
           night_strength: float = 1.0) -> List[float]:
    """13 wartości: dzień ↔ noc wg godzin z paczki."""
    d = [float(c) for c in day]
    n = [float(c) for c in (night if night is not None else _night_of(d))]
    out: List[float] = []
    for w in NIGHT_WEIGHT:
        k = min(1.0, w * night_strength)
        out.extend(d[i] * (1.0 - k) + n[i] * k for i in range(3))
    return out


def matol_sky_map(sky: Dict[str, float]) -> Dict[str, Sequence[float]]:
    """
    Mapowanie kolorów z presetu nieba na znaczniki MATOL.xml.
    Uwaga: w paczce pasmo horyzontu to `sky_zenith_transition_*`, a nie
    `sky_horizon_*` — dlatego preset „horizon” trafia tam.
    """
    zr, zg, zb = (sky.get("sky_zenith_col_r", 0.29), sky.get("sky_zenith_col_g", 0.51),
                  sky.get("sky_zenith_col_b", 0.87))
    hr, hg, hb = (sky.get("sky_horizon_col_r", 0.62), sky.get("sky_horizon_col_g", 0.78),
                  sky.get("sky_horizon_col_b", 0.94))
    er, eg, eb = (sky.get("sky_azimuth_east_col_r", 0.94), sky.get("sky_azimuth_east_col_g", 0.83),
                  sky.get("sky_azimuth_east_col_b", 0.60))
    wr, wg, wb = (sky.get("sky_azimuth_west_col_r", 0.85), sky.get("sky_azimuth_west_col_g", 0.72),
                  sky.get("sky_azimuth_west_col_b", 0.58))
    tr, tg, tb = (sky.get("sky_azimuth_transition_col_r", 0.80), sky.get("sky_azimuth_transition_col_g", 0.75),
                  sky.get("sky_azimuth_transition_col_b", 0.70))
    z_int = float(sky.get("sky_zenith_col_inten", 1.0))
    h_int = float(sky.get("sky_horizon_col_inten", 1.0))
    return {
        "sky_zenith_col_r": _curve((zr, 0.0, 0.0)),
        "sky_zenith_col_g": _curve((zg, 0.0, 0.0)),
        "sky_zenith_col_b": _curve((zb, 0.0, 0.0)),
        "sky_zenith_col_inten": _curve((z_int, z_int, z_int), (0.25, 0.25, 0.25)),
        "sky_zenith_transition_col_r": _curve((hr, 0.0, 0.0)),
        "sky_zenith_transition_col_g": _curve((hg, 0.0, 0.0)),
        "sky_zenith_transition_col_b": _curve((hb, 0.0, 0.0)),
        "sky_zenith_transition_col_inten": _curve((h_int, h_int, h_int), (0.30, 0.30, 0.30)),
        "sky_azimuth_east_col_r": _curve((er, 0.0, 0.0)),
        "sky_azimuth_east_col_g": _curve((eg, 0.0, 0.0)),
        "sky_azimuth_east_col_b": _curve((eb, 0.0, 0.0)),
        "sky_azimuth_west_col_r": _curve((wr, 0.0, 0.0)),
        "sky_azimuth_west_col_g": _curve((wg, 0.0, 0.0)),
        "sky_azimuth_west_col_b": _curve((wb, 0.0, 0.0)),
        "sky_azimuth_transition_col_r": _curve((tr, 0.0, 0.0)),
        "sky_azimuth_transition_col_g": _curve((tg, 0.0, 0.0)),
        "sky_azimuth_transition_col_b": _curve((tb, 0.0, 0.0)),
        "sky_cloud_density_mult": _curve((float(sky.get("sky_cloud_density_mult", 0.35)),) * 3),
        "sky_cloud_gen_frequency": _curve((float(sky.get("sky_cloud_gen_frequency", 1.3)),) * 3),
        "sky_cloud_gen_scale": _curve((float(sky.get("sky_cloud_gen_scale", 40.0)),) * 3),
        "sky_cloud_gen_threshold": _curve((float(sky.get("sky_cloud_gen_threshold", 0.15)),) * 3),
        "sky_cloud_gen_softness": _curve((float(sky.get("sky_cloud_gen_softness", 0.5)),) * 3),
        "sky_moon_iten": _curve((float(sky.get("sky_moon_iten", 0.35)),) * 3),
        "sky_moon_disc_size": _curve((float(sky.get("sky_moon_disc_size", 1.0)),) * 3),
    }


# --- CHMURY (MATOL: gęstość i wygląd chmur) ---
def _cloud_matol(style: str) -> Dict[str, Sequence[float]]:
    if style == "off":
        return {"sky_cloud_density_mult": [0.0] * 13, "sky_cloud_gen_threshold": [1.0] * 13}
    if style == "dense":
        return {"sky_cloud_density_mult": [1.0] * 13, "sky_cloud_gen_threshold": [0.05] * 13,
                "sky_cloud_gen_softness": [0.30] * 13}
    if style == "soft":
        return {"sky_cloud_gen_softness": [0.85] * 13, "sky_cloud_gen_scale": [70.0] * 13}
    if style == "cotton":
        return {"sky_cloud_gen_scale": [22.0] * 13, "sky_cloud_gen_softness": [0.65] * 13,
                "sky_cloud_gen_threshold": [0.10] * 13}
    if style == "dark":
        return {"sky_cloud_base_strength": [1.0] * 13, "sky_cloud_shadow_strength": [1.0] * 13,
                "sky_cloud_base_col_r": [0.10] * 13, "sky_cloud_base_col_g": [0.10] * 13,
                "sky_cloud_base_col_b": [0.12] * 13}
    if style == "golden":
        return {"sky_cloud_base_col_r": [1.0] * 13, "sky_cloud_base_col_g": [0.72] * 13,
                "sky_cloud_base_col_b": [0.42] * 13, "sky_cloud_base_strength": [0.9] * 13}
    return {}


def _cloud_colour(style: str) -> Dict[str, Sequence[float]]:
    """Kolor chmur (custom-clouds / kolor-custom-chmur z paczki)."""
    table = {
        "white": (0.95, 0.96, 1.00), "pink": (1.00, 0.78, 0.86), "purple": (0.72, 0.62, 1.00),
        "red": (1.00, 0.55, 0.45), "cyan": (0.62, 0.92, 1.00), "green": (0.68, 1.00, 0.75),
    }
    rgb = table.get(style)
    if rgb is None:
        return {}
    r, g, b = rgb
    dark = (r * 0.25, g * 0.25, b * 0.30)
    return {
        "sky_cloud_base_col_r": _curve((r, 0.0, 0.0), (dark[0],) * 3),
        "sky_cloud_base_col_g": _curve((g, 0.0, 0.0), (dark[1],) * 3),
        "sky_cloud_base_col_b": _curve((b, 0.0, 0.0), (dark[2],) * 3),
        "sky_cloud_mid_col_r": _curve((r, 0.0, 0.0), (dark[0],) * 3),
        "sky_cloud_mid_col_g": _curve((g, 0.0, 0.0), (dark[1],) * 3),
        "sky_cloud_mid_col_b": _curve((b, 0.0, 0.0), (dark[2],) * 3),
    }


# --- SŁOŃCE / KSIĘŻYC ---
def _sun_style(style: str) -> Dict[str, Sequence[float]]:
    if style == "warm":
        return {"light_dir_col_r": _curve((1.0, 0.85, 0.62)), "light_ray_col_r": _curve((1.0, 0.78, 0.45)),
                "light_ray_mult": _curve((1.5, 1.5, 1.5))}
    if style == "cold":
        return {"light_dir_col_r": _curve((0.85, 0.92, 1.0)), "light_ray_col_r": _curve((0.80, 0.90, 1.0)),
                "light_ray_mult": _curve((1.2, 1.2, 1.2))}
    if style == "golden":
        return {"light_dir_col_r": _curve((1.0, 0.72, 0.35)), "light_ray_col_r": _curve((1.0, 0.62, 0.25)),
                "light_ray_length": _curve((1.6, 1.6, 1.6)), "light_ray_mult": _curve((1.8, 1.8, 1.8)),
                "sun_direction_z": _curve((0.25, 0.25, 0.25))}
    if style == "soft":
        return {"light_ray_mult": _curve((0.5, 0.5, 0.5)), "light_ray_inten": _curve((0.5, 0.5, 0.5)),
                "light_falloff_mult": _curve((1.4, 1.4, 1.4))}
    if style == "rays-off":
        return {"light_ray_mult": [0.0] * 13, "light_ray_inten": [0.0] * 13}
    return {}


def _moon_style(style: str) -> Dict[str, Sequence[float]]:
    if style == "huge":
        return {"sky_moon_disc_size": [2.6] * 13, "sky_moon_iten": [1.0] * 13}
    if style == "small":
        return {"sky_moon_disc_size": [0.55] * 13, "sky_moon_iten": [0.25] * 13}
    if style == "red":
        return {"sky_moon_col_r": [1.0] * 13, "sky_moon_col_g": [0.25] * 13, "sky_moon_col_b": [0.18] * 13,
                "sky_moon_disc_size": [1.8] * 13, "sky_moon_iten": [0.9] * 13}
    if style == "blue":
        return {"sky_moon_col_r": [0.70] * 13, "sky_moon_col_g": [0.80] * 13, "sky_moon_col_b": [1.0] * 13,
                "sky_moon_iten": [0.7] * 13}
    if style == "dark":
        return {"sky_moon_iten": [0.05] * 13}
    return {}


# --- WODA ---
def _water_style(style: str) -> Dict[str, Sequence[float]]:
    if style == "clean":
        return {"water_specular_intensity": _curve((1.6, 1.6, 1.6)),
                "water_foglight": _curve((1.0, 1.0, 1.0)),
                "water_fogstreaming": _curve((1.0, 1.0, 1.0))}
    if style == "dark":
        return {"water_specular_intensity": _curve((0.35, 0.35, 0.35)),
                "water_foglight": _curve((0.20, 0.20, 0.20))}
    if style == "mirror":
        return {"water_reflection": _curve((1.0, 1.0, 1.0)),
                "water_reflection_far_clip": _curve((1200.0, 1200.0, 1200.0)),
                "water_reflection_distant_light_intensity": _curve((1.5, 1.5, 1.5)),
                "water_specular_intensity": _curve((2.2, 2.2, 2.2))}
    if style == "calm":
        return {"wind_speed_mult": _curve((0.0, 0.0, 0.0)),
                "water_foam_intensity_mult": _curve((0.0, 0.0, 0.0)),
                "water_drying_speed_mult": _curve((3.0, 3.0, 3.0))}
    if style == "storm":
        return {"wind_speed_mult": _curve((2.5, 2.5, 2.5)),
                "water_foam_intensity_mult": _curve((2.0, 2.0, 2.0))}
    if style == "no-foam":
        return {"water_foam_intensity_mult": _curve((0.0, 0.0, 0.0))}
    return {}


# --- MGŁA ---
def _fog_style(style: str) -> Dict[str, Sequence[float]]:
    base = {"fog_density": None}
    if style == "off":
        return {"fog_density": [0.0] * 13, "fog_start": [900.0] * 13,
                "fogvolume_density": [0.0] * 13}
    if style == "light":
        return {"fog_density": _curve((0.10, 0.10, 0.10)), "fog_start": _curve((260.0, 260.0, 260.0))}
    if style == "dense":
        return {"fog_density": _curve((0.65, 0.65, 0.65)), "fog_start": _curve((60.0, 60.0, 60.0))}
    if style == "horror":
        return {"fog_density": _curve((1.6, 1.6, 1.6)), "fog_start": _curve((18.0, 18.0, 18.0)),
                "fog_col_r": _curve((0.55, 0.58, 0.62)), "fog_col_g": _curve((0.58, 0.60, 0.64)),
                "fog_col_b": _curve((0.62, 0.64, 0.70))}
    if style == "no-volume":
        return {"fogvolume_density": [0.0] * 13}
    del base
    return {}


# --- ŚWIATŁO ---
def _light_style(style: str) -> Dict[str, Sequence[float]]:
    if style == "street-bright":
        return {"light_artificial_ext_down_intensity": _curve((2.2, 2.2, 2.2)),
                "light_artificial_ext_up_intensity": _curve((1.8, 1.8, 1.8)),
                "light_falloff_mult": _curve((1.6, 1.6, 1.6))}
    if style == "street-off":
        return {"light_artificial_ext_down_intensity": [0.0] * 13,
                "light_artificial_ext_up_intensity": [0.0] * 13}
    if style == "night-bright":
        return {"light_natural_amb_up_intensity": _curve((0.30, 0.30, 0.30), (1.4, 1.4, 1.4)),
                "light_natural_amb_down_intensity": _curve((0.25, 0.25, 0.25), (1.2, 1.2, 1.2)),
                "dark_intensity": _curve((0.0, 0.0, 0.0), (0.35, 0.35, 0.35))}
    if style == "ped-visible":
        return {"light_ped_rim_mult": _curve((2.0, 2.0, 2.0)),
                "light_amb_occ_mult_ped": _curve((0.55, 0.55, 0.55))}
    if style == "warm":
        return {"light_artificial_ext_down_col_r": [1.0] * 13, "light_artificial_ext_down_col_g": [0.80] * 13,
                "light_artificial_ext_down_col_b": [0.52] * 13,
                "light_artificial_int_down_col_r": [1.0] * 13, "light_artificial_int_down_col_g": [0.82] * 13,
                "light_artificial_int_down_col_b": [0.55] * 13}
    if style == "cold":
        return {"light_artificial_ext_down_col_r": [0.70] * 13, "light_artificial_ext_down_col_g": [0.82] * 13,
                "light_artificial_ext_down_col_b": [1.0] * 13,
                "light_artificial_int_down_col_r": [0.72] * 13, "light_artificial_int_down_col_g": [0.84] * 13,
                "light_artificial_int_down_col_b": [1.0] * 13}
    if style == "interiors":
        return {"light_amb_occ_mult": _curve((0.35, 0.35, 0.35)),
                "light_amb_down_wrap": _curve((1.0, 1.0, 1.0))}
    return {}


# --- POSTFX (kolory) ---
def _postfx_style(style: str) -> Dict[str, Sequence[float]]:
    if style == "vivid":
        return {"postfx_intensity_bloom": _curve((0.45, 0.45, 0.45)),
                "postfx_desaturation": [0.0] * 13,
                "postfx_vignetting_intensity": _curve((0.15, 0.15, 0.15))}
    if style == "cold":
        return {"postfx_shift_col_r": [0.82] * 13, "postfx_shift_col_g": [0.90] * 13,
                "postfx_shift_col_b": [1.0] * 13, "postfx_shift_cutoff": [0.25] * 13}
    if style == "film":
        return {"postfx_intensity_bloom": _curve((0.30, 0.30, 0.30)),
                "postfx_vignetting_intensity": _curve((0.45, 0.45, 0.45)),
                "postfx_vignetting_radius": _curve((1.2, 1.2, 1.2)),
                "postfx_noise": _curve((0.04, 0.04, 0.04))}
    if style == "contrast":
        return {"postfx_tonemap_filmic_b": _curve((0.28, 0.28, 0.28)),
                "postfx_tonemap_filmic_c": _curve((0.42, 0.42, 0.42)),
                "postfx_tonemap_filmic_d": _curve((0.44, 0.44, 0.44)),
                "postfx_tonemap_filmic_e": _curve((0.02, 0.02, 0.02))}
    if style == "desat":
        return {"postfx_desaturation": [0.55] * 13}
    if style == "bloom-off":
        return {"postfx_intensity_bloom": [0.0] * 13}
    if style == "vignette-off":
        return {"postfx_vignetting_intensity": [0.0] * 13}
    if style == "neutral":
        return {"postfx_desaturation": [0.0] * 13, "postfx_shift_cutoff": [999.0] * 13,
                "postfx_intensity_bloom": _curve((0.0, 0.0, 0.0))}
    return {}


# --- BLUR / DOF / LENS ---
def _blur_style(style: str) -> Dict[str, Sequence[float]]:
    if style == "motion-off":
        return {"blur_vignetting_intensity": [0.0] * 13, "blur_vignetting_radius": [0.0] * 13}
    if style == "screen-off":
        return {"screen_blur_intensity": [0.0] * 13}
    if style == "dof-off":
        return {"dof_far": [0.0] * 13, "dof_blur_far": [0.0] * 13}
    if style == "lens-off":
        return {"lens_dist_coeff": [0.0] * 13, "lens_artefacts_intensity": [0.0] * 13,
                "lens_dirt_intensity": [0.0] * 13}
    if style == "chroma-off":
        return {"chrom_aberration_coeff": [0.0] * 13, "chrom_aberration_coeff2": [0.0] * 13}
    if style == "bokeh-off":
        return {"bokeh_intensity": [0.0] * 13}
    if style == "all-off":
        return {"blur_vignetting_intensity": [0.0] * 13, "screen_blur_intensity": [0.0] * 13,
                "dof_far": [0.0] * 13, "dof_blur_far": [0.0] * 13,
                "lens_artefacts_intensity": [0.0] * 13, "lens_dist_coeff": [0.0] * 13}
    return {}


# --- WYDAJNOŚĆ (FPS) ---
def _fps_style(style: str) -> Dict[str, Sequence[float]]:
    if style == "ssao-off":
        return {"ssao_inten": [0.0] * 13, "ssao_qs_strength": [0.0] * 13, "ssao_cp_strength": [0.0] * 13}
    if style == "reflections-off":
        return {"water_reflection": [0.0] * 13, "reflection_quality": [0.0] * 13,
                "water_reflection_lod_range_enabled": [0.0] * 13}
    if style == "sprites-off":
        return {"sprite_brightness": [0.0] * 13, "sprite_distant_light_twinkle": [0.0] * 13}
    if style == "lod-low":
        return {"lod_mult_hd": [0.55] * 13, "lod_mult_lod": [0.45] * 13,
                "lod_mult_slod2": [0.35] * 13}
    if style == "light-low":
        return {"light_dynamic_bake_tweak": [1.0] * 13, "light_natural_push": [0.0] * 13}
    return {}


# --- generator: jeden MATOL.xml ze wszystkich rodzin -------------------------
def generate_matol_xml(params: Dict[str, Any]) -> Optional[str]:
    """
    Jeden plik `timecycle/MATOL.xml` z SCALONYCH opcji: niebo, chmury, słońce,
    księżyc, woda, mgła, światło, postfx, blur/dof/lens, wydajność.
    """
    text = cp.load("timecycle/MATOL.xml")
    if text is None:
        return None

    sky_keys = {k: v for k, v in params.items() if str(k).startswith("sky_") and isinstance(v, (int, float))}
    if sky_keys:
        text = cp.set_tag_map(text, matol_sky_map({k: float(v) for k, v in sky_keys.items()}))

    for key, table in (("cloud_matol", _cloud_matol), ("cloud_color", _cloud_colour),
                       ("sun_style", _sun_style), ("moon_style", _moon_style),
                       ("water_style", _water_style), ("fog_style", _fog_style),
                       ("light_style", _light_style), ("postfx_style", _postfx_style),
                       ("blur_style", _blur_style), ("fps_style", _fps_style)):
        value = params.get(key)
        if value:
            text = cp.set_tag_map(text, table(str(value)))
    return _stamp_xml(text)


# ============================================================================
# 3. time.xml — CZAS (zawsze dzień / zawsze noc / złota godzina / dynamiczny)
#    Format 1:1 z paczki: mode="dynamic|static" + próbki godzin.
# ============================================================================

TIME_MODES: Dict[str, Dict[str, Any]] = {
    "dynamic": {"mode": "dynamic", "samples": [(0, 0, 4)]},
    "always-day": {"mode": "static", "samples": [(12, 12, 24)]},
    "always-night": {"mode": "static", "samples": [(0, 0, 24)]},
    "golden": {"mode": "static", "samples": [(18, 18, 24)]},
    "sunrise": {"mode": "static", "samples": [(6, 6, 24)]},
    "noon-only": {"mode": "static", "samples": [(12, 12, 24)]},
}


def generate_time_xml(params: Dict[str, Any]) -> str:
    """time.xml w formacie paczki (+ tryby: zawsze dzień / zawsze noc)."""
    spec = TIME_MODES.get(str(params.get("time_mode") or "dynamic"), TIME_MODES["dynamic"])
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        STAMP,
        f'<time_data version="1.000000" mode="{spec["mode"]}">',
    ]
    for hour, name_hour, duration in spec["samples"]:
        lines.append(f'  <sample name="{int(name_hour):02d}:00" hour="{int(hour)}" '
                     f'duration="{int(duration)}" uw_tc_mod="underwater"/>')
    lines.append('</time_data>')
    return "\n".join(lines) + "\n"


# ============================================================================
# 4. visualsettings.dat — DESZCZ, CYKL POGODY, CHMURY, CIENIE, KAŁUŻE…
#    Patchujemy szablon (tabela klucz=wartość), więc gra dostaje pełny plik.
# ============================================================================

VISUAL_FAMILIES: Dict[str, Dict[str, Dict[str, float]]] = {
    "rain_vis": {
        "off": {"rain.NumberParticles": 0, "rain.diffuse": 0, "rain.ambient": 0,
                "rain.wrapScale": 0, "rain.fadeInScale": 0},
        "light": {"rain.NumberParticles": 450, "rain.diffuse": 0.55, "rain.ambient": 0.45,
                  "rain.wrapScale": 0.35, "rain.fadeInScale": 0.5, "rain.UseLitShader": 1},
        "heavy": {"rain.NumberParticles": 2200, "rain.diffuse": 1, "rain.ambient": 0.9,
                  "rain.wrapScale": 1, "rain.fadeInScale": 1, "rain.UseLitShader": 1},
        "insane": {"rain.NumberParticles": 5200, "rain.diffuse": 1.4, "rain.ambient": 1.2,
                   "rain.wrapScale": 1.4, "rain.fadeInScale": 1.6, "rain.UseLitShader": 1},
    },
    "cycle_vis": {
        "fast": {"weather.CycleDuration": 90},
        "normal": {"weather.CycleDuration": 240},
        "slow": {"weather.CycleDuration": 900},
        "frozen": {"weather.CycleDuration": 100000},
    },
    "sun_vis": {
        "big": {"sky.sun.centreStart": 0, "sky.sun.centreEnd": 0, "sky.sunAxiasX": 1,
                "sky.sunAxiasY": 1},
        "small": {"sky.sun.centreStart": 0, "sky.sun.centreEnd": 0, "sky.sunAxiasX": 0,
                  "sky.sunAxiasY": 0},
        "glow": {"sky.cloudInscatteringRange": 2400, "sky.cloudEdgeSmooth": 220,
                 "sky.sun.centreStart": 0, "sky.sun.centreEnd": 0},
    },
    "cloud_vis": {
        "warp-off": {"sky.cloudWarp": 0, "sky.GameCloudSpeed": 0},
        "fast": {"sky.GameCloudSpeed": 3.5, "sky.cloudWarp": 1.4},
        "slow": {"sky.GameCloudSpeed": 0.25, "sky.cloudWarp": 0.5},
        "motion-off": {"sky.GameCloudSpeed": 0},
    },
    "shadow_vis": {
        "off": {"shadows.cloudtexture.scale": 0, "shadows.cloudtexture.rangemin": 0,
                "shadows.cloudtexture.rangemax": 0},
        "on": {"shadows.cloudtexture.scale": 1, "shadows.cloudtexture.rangemin": 40,
               "shadows.cloudtexture.rangemax": 400},
    },
    "puddle_vis": {
        "off": {"puddles.amount": 0, "puddles.reflection": 0, "puddle.amount": 0,
                "puddle.reflection": 0, "puddle.createdist": 0, "puddle.raindist": 0},
        "on": {"puddles.amount": 1, "puddles.reflection": 1, "puddle.amount": 1,
               "puddle.reflection": 1},
    },
    "car_vis": {
        "interior-on": {"car.interiorlight.intensity": 1, "car.interiorlight.radius": 1,
                        "car.interiorlight.night.emissive.on": 1, "car.interiorlight.day.emissive.on": 1},
        "interior-off": {"car.interiorlight.intensity": 0, "car.interiorlight.radius": 0,
                         "car.interiorlight.night.emissive.on": 0, "car.interiorlight.day.emissive.on": 0},
    },
    "dof_vis": {
        "off": {"adaptivedof.enabled": 0},
        "on": {"adaptivedof.enabled": 1},
    },
    "particles_vis": {
        "shadows-off": {"particles.shadowintensity": 0},
    },
}


def generate_visualsettings_dat(params: Dict[str, Any]) -> Optional[str]:
    """visualsettings.dat (szablon paczki) z nałożonymi opcjami deszczu itd."""
    text = cp.load("visualsettings.dat")
    if text is None:
        return None
    mapping: Dict[str, float] = {}
    for family, table in VISUAL_FAMILIES.items():
        value = params.get(family)
        if value and str(value) in table:
            mapping.update(table[str(value)])
    if mapping:
        text = cp.set_kv_many(text, mapping)
    return _stamp_dat(text)


# ============================================================================
# 5. timecycle_mods_4.xml — KILL EFFECT (kolor, intensywność, blur, desat)
#    Autorzy paczki opisali ten modifier komentarzami (hud_def_desat_cold_kill).
# ============================================================================

KILL_MODIFIER = "hud_def_desat_cold_kill"

# kolor: (foreground postfx, ped light, light ray, vignette bg)
KILL_COLORS: Dict[str, Dict[str, Tuple[float, float, float]]] = {
    "blue":   {"fg": (0.039, 0.270, 0.796), "ped": (0.20, 0.55, 1.00), "ray": (0.039, 0.27, 0.80), "bg": (0.0, 0.03, 0.10)},
    "red":    {"fg": (0.796, 0.090, 0.090), "ped": (1.00, 0.20, 0.20), "ray": (0.80, 0.09, 0.09), "bg": (0.10, 0.0, 0.0)},
    "green":  {"fg": (0.150, 0.796, 0.250), "ped": (0.30, 1.00, 0.40), "ray": (0.15, 0.80, 0.25), "bg": (0.0, 0.10, 0.02)},
    "purple": {"fg": (0.520, 0.150, 0.796), "ped": (0.70, 0.35, 1.00), "ray": (0.52, 0.15, 0.80), "bg": (0.05, 0.0, 0.10)},
    "gold":   {"fg": (0.796, 0.620, 0.120), "ped": (1.00, 0.85, 0.30), "ray": (0.80, 0.62, 0.12), "bg": (0.10, 0.07, 0.0)},
    "acid":   {"fg": (0.620, 0.796, 0.050), "ped": (0.80, 1.00, 0.10), "ray": (0.62, 0.80, 0.05), "bg": (0.05, 0.10, 0.0)},
    "white":  {"fg": (0.850, 0.870, 0.900), "ped": (1.00, 1.00, 1.00), "ray": (0.85, 0.87, 0.90), "bg": (0.10, 0.10, 0.10)},
    "black":  {"fg": (0.020, 0.020, 0.020), "ped": (0.10, 0.10, 0.10), "ray": (0.02, 0.02, 0.02), "bg": (0.0, 0.0, 0.0)},
}

# intensywność kill effectu
KILL_LEVELS: Dict[str, Dict[str, float]] = {
    "subtle":   {"vignette_intensity": 0.35, "vignette_radius": 3.0, "desaturation": 0.15},
    "normal":   {"vignette_intensity": 0.90, "vignette_radius": 6.5, "desaturation": 0.70},
    "strong":   {"vignette_intensity": 1.60, "vignette_radius": 12.0, "desaturation": 1.60},
    "extreme":  {"vignette_intensity": 2.60, "vignette_radius": 20.0, "desaturation": 2.40},
    "off":      {"vignette_intensity": 0.0, "vignette_radius": 0.0, "desaturation": 0.0},
}

KILL_BLUR: Dict[str, Dict[str, float]] = {
    "off":    {"blur_vignetting_intensity": 0.0, "screen_blur_intensity": 0.0, "blur_vignetting_radius": 0.0},
    "soft":   {"blur_vignetting_intensity": 0.35, "screen_blur_intensity": 0.12, "blur_vignetting_radius": 2.0},
    "strong": {"blur_vignetting_intensity": 1.60, "screen_blur_intensity": 0.60, "blur_vignetting_radius": 6.0},
}


def _modifier_span(text: str, name: str) -> Optional[Tuple[int, int]]:
    """Granice zawartości <modifier name="...">…</modifier> w pliku mods_4."""
    start = text.find(f'name="{name}"')
    if start < 0:
        return None
    open_end = text.find(">", start)
    close_start = text.find("</modifier>", open_end)
    if open_end < 0 or close_start < 0:
        return None
    return open_end + 1, close_start


def _set_in_modifier(text: str, name: str, mapping: Dict[str, Sequence[float]]) -> str:
    """Ustawia znaczniki TYLKO w obrębie jednego modyfikatora (np. kill effectu)."""
    span = _modifier_span(text, name)
    if span is None:
        return text
    start, end = span
    body = text[start:end]
    body = cp.set_tag_map(body, mapping)
    return text[:start] + body + text[end:]


def generate_mods4_xml(params: Dict[str, Any]) -> Optional[str]:
    """
    timecycle_mods_4.xml (szablon paczki, 252 modyfikatory) — podmienia tylko
    parametry KILL EFFECTU: kolor, intensywność, blur, desaturację.
    """
    text = cp.load("timecycle/timecycle_mods_4.xml")
    if text is None:
        return None

    mapping: Dict[str, Sequence[float]] = {}
    colour = KILL_COLORS.get(str(params.get("kill_color") or ""))
    if colour:
        fg, ped, ray, bg = colour["fg"], colour["ped"], colour["ray"], colour["bg"]
        mapping.update({
            "postfx_correct_col_r": [fg[0], 0.0], "postfx_correct_col_g": [fg[1], 0.0],
            "postfx_correct_col_b": [fg[2], 0.0],
            "postfx_shift_col_r": [fg[0], 1.0], "postfx_shift_col_g": [fg[1], 1.0],
            "postfx_shift_col_b": [fg[2], 1.0],
            "ped_light_col_r": [ped[0] * 255.0, 0.0], "ped_light_col_g": [ped[1] * 255.0, 0.0],
            "ped_light_col_b": [ped[2] * 255.0, 0.0],
            "light_ray_col_r": [ray[0], 1.0], "light_ray_col_g": [ray[1], 1.0],
            "light_ray_col_b": [ray[2], 1.0],
            "postfx_vignetting_col_r": [bg[0], 0.0], "postfx_vignetting_col_g": [bg[1], 0.0],
            "postfx_vignetting_col_b": [bg[2], 0.0],
        })

    level = KILL_LEVELS.get(str(params.get("kill_style") or ""))
    if level:
        mapping.update({
            "postfx_vignetting_intensity": [level["vignette_intensity"], 0.0],
            "postfx_vignetting_radius": [level["vignette_radius"], 0.0],
            "postfx_desaturation": [level["desaturation"], 0.0],
        })

    blur = KILL_BLUR.get(str(params.get("kill_blur") or ""))
    if blur:
        mapping.update({tag: [value, 0.0] for tag, value in blur.items()})

    if mapping:
        text = _set_in_modifier(text, KILL_MODIFIER, mapping)
        # kolor gradingu hud (usunięcie zimnego filtra pauzy, gdy kill effect off)
    if str(params.get("kill_style") or "") == "off":
        text = _set_in_modifier(text, KILL_MODIFIER, {
            "postfx_vignetting_intensity": [0.0, 0.0], "postfx_desaturation": [0.0, 0.0],
            "blur_vignetting_intensity": [0.0, 0.0], "screen_blur_intensity": [0.0, 0.0],
        })
    return _stamp_xml(text)


# ============================================================================
# 6. CHMURY — clouds.xml (geometria) + cloudkeyframes.xml (gęstość/prędkość)
# ============================================================================

def generate_clouds_xml(params: Dict[str, Any]) -> Optional[str]:
    """clouds.xml — wysokość, rozmiar i jakość warstw chmur."""
    text = cp.load("clouds.xml")
    if text is None:
        return None
    style = str(params.get("clouds_geom") or "")
    if style == "high":
        text = cp.set_attr(text, "mScale", "z", 2600.0)
        text = cp.set_attr(text, "mPosition", "z", 60.0)
    elif style == "low":
        text = cp.set_attr(text, "mScale", "z", 900.0)
        text = cp.set_attr(text, "mPosition", "z", 12.0)
    elif style == "big":
        text = cp.set_attr(text, "mScale", "x", 3200.0)
        text = cp.set_attr(text, "mScale", "y", 3200.0)
    elif style == "small":
        text = cp.set_attr(text, "mScale", "x", 900.0)
        text = cp.set_attr(text, "mScale", "y", 900.0)
    elif style == "cheap":
        text = cp.set_attr(text, "mCostFactor", "value", 0.0)
    elif style == "rich":
        text = cp.set_attr(text, "mCostFactor", "value", 1.0)
    elif style == "no-rotate":
        text = cp.set_attr(text, "mRotationScale", "value", 0.0)
        text = cp.set_attr(text, "mRotation", "z", 0.0)
    elif style == "rotate":
        text = cp.set_attr(text, "mRotationScale", "value", 1.0)
    return _stamp_xml(text)


def generate_cloudkeyframes_xml(params: Dict[str, Any]) -> Optional[str]:
    """
    cloudkeyframes.xml — klatki kluczowe chmur: gęstość (cloud coverage),
    rozmycie i prędkość przewijania chmur w ciągu dnia.
    """
    text = cp.load("cloudkeyframes.xml")
    if text is None:
        return None
    style = str(params.get("clouds_key") or "")
    if style == "sparse":
        text = cp.scale_tag(text, "formation_cloud", 0.45, vmin=0.0)
        text = cp.scale_tag(text, "density", 0.5, vmin=0.0)
    elif style == "dense":
        text = cp.scale_tag(text, "formation_cloud", 1.6, vmin=0.0)
        text = cp.scale_tag(text, "density", 1.5, vmin=0.0)
    elif style == "fast":
        text = cp.scale_tag(text, "cloud_speed", 2.5, vmin=0.0)
        text = cp.scale_tag(text, "speed", 2.5, vmin=0.0)
    elif style == "slow":
        text = cp.scale_tag(text, "cloud_speed", 0.3, vmin=0.0)
        text = cp.scale_tag(text, "speed", 0.3, vmin=0.0)
    elif style == "flat":
        text = cp.scale_tag(text, "cloud_density", 0.0, vmin=0.0)
    elif style == "thin":
        text = cp.scale_tag(text, "cloud_density", 0.4, vmin=0.0)
    return _stamp_xml(text)


# ============================================================================
# 7. EFEKTY: eksplozje, ogień, cząstki otoczenia, HUD
# ============================================================================

def generate_explosionfx_dat(params: Dict[str, Any]) -> Optional[str]:
    """explosionfx.dat — siła, przypalenie, liczba wybuchów, zasięg."""
    text = cp.load("effects/explosionfx.dat")
    if text is None:
        return None
    scale = str(params.get("expl_scale") or "")
    factors = {"tiny": 0.5, "small": 0.75, "big": 1.6, "huge": 2.5, "insane": 4.0}
    if scale in factors:
        text = cp.explosion_scale(text, factors[scale])
    if str(params.get("expl_scorch") or "") == "off":
        text = cp.explosion_scorch(text, 0.0)
    count = str(params.get("expl_count") or "")
    if count == "more":
        text = cp.explosion_count(text, 6.0)
    elif count == "less":
        text = cp.explosion_count(text, 0.0)
    return _stamp_dat(text)


def generate_firefx_dat(params: Dict[str, Any]) -> Optional[str]:
    """firefx.dat — czas i siła palenia (ogień na materiale)."""
    text = cp.load("effects/firefx.dat")
    if text is None:
        return None
    style = str(params.get("fire_style") or "")
    factors = {"short": 0.35, "long": 2.5, "eternal": 5.0, "off": 0.0}
    if style in factors:
        text = cp.fire_power(text, factors[style])
    return _stamp_dat(text)


def generate_entityfx_dat(params: Dict[str, Any]) -> Optional[str]:
    """
    entityfx.dat — cząstki otoczenia. `smoke_style=off` zeruje próg pojawiania
    się DYMU/PARY, `particle_style` wyłącza dodatkowo KURZ i cząstki otoczenia.
    """
    text = cp.load("effects/entityfx.dat")
    if text is None:
        return None
    changed = False
    if str(params.get("smoke_style") or "") == "off":
        text = cp.patch_last_column(text, ("AMB_",), contains=("SMOKE", "STEAM"))
        changed = True
    if str(params.get("particle_style") or "") == "dust-off":
        text = cp.patch_last_column(text, ("DST_",))
        changed = True
    elif str(params.get("particle_style") or "") == "ambient-off":
        text = cp.patch_last_column(text, ("AMB_",))
        changed = True
    elif str(params.get("particle_style") or "") == "all-off":
        text = cp.patch_last_column(text, ("AMB_",))
        text = cp.patch_last_column(text, ("DST_",))
        changed = True
    if not changed:
        return None
    return _stamp_dat(text)


def generate_pausemenu_xml(params: Dict[str, Any]) -> Optional[str]:
    """ui/pausemenu.xml — menu pauzy / HUD (czyste tło, skalowanie)."""
    text = cp.load("ui/pausemenu.xml")
    if text is None:
        return None
    style = str(params.get("hud_style") or "")
    if style == "clean":
        text = cp.pausemenu_hide_backgrounds(text)
    elif style == "clean-avatars":
        text = cp.pausemenu_hide_backgrounds(text, ("MIDDLE_AVATAR_BG", "RIGHT_AVATAR_BG"))
    elif style == "big":
        text = cp.pausemenu_scale(text, 1.15)
    elif style == "small":
        text = cp.pausemenu_scale(text, 0.85)
    else:
        return None
    return _stamp_xml(text)


# ============================================================================
# 7b. NOWE PLIKI Z PACZKI — KREW, EFEKT STRZAŁU, OPONY, DEKALE, CZĄSTKI FX
#     (bloodfx.dat, weaponfx.dat, wheelfx.dat, decals.dat, effects/visualsettings)
# ============================================================================

# Kolor krwi w skali 0–255 (tak jak w plikach Citizen Makers)
BLOOD_COLOURS: Dict[str, Tuple[int, int, int]] = {
    "red": (200, 20, 20), "dark": (70, 0, 0), "anime": (255, 70, 130),
    "plasma": (70, 130, 255), "toxic": (90, 255, 70), "black": (25, 25, 30),
    "white": (235, 235, 240), "gold": (255, 190, 40), "purple": (170, 60, 255),
}

BLOOD_SIZES: Dict[str, float] = {"more": 1.8, "huge": 2.4, "less": 0.5}

TRACE_COLOURS: Dict[str, Tuple[int, int, int]] = {
    "red": (255, 45, 45), "blue": (60, 130, 255), "green": (60, 255, 90),
    "pink": (255, 70, 190), "black": (25, 25, 25), "white": (255, 255, 255),
    "gold": (255, 200, 60), "toxic": (180, 255, 40),
}

TRACE_SIZES: Dict[str, float] = {"big": 2.0, "huge": 3.0, "small": 0.6}

WHEEL_COLOURS: Dict[str, Tuple[int, int, int]] = {
    "dark": (12, 12, 12), "white": (250, 250, 250), "neon": (255, 40, 220),
    "red": (220, 30, 30), "blue": (40, 90, 255),
}


HEAD_SIZES: Dict[str, float] = {"massive": 2.5, "big": 1.7, "off": 0.2}


def generate_bloodfx_dat(params: Dict[str, Any]) -> Optional[str]:
    """
    effects/bloodfx.dat — KREW + HEAD EFFECT. Patchuje PRAWDZIWĄ tabelę z paczki:
    kolor RGBA i rozmiar plamy dla wszystkich kości oraz OSOBNO dla głowy (HEAD),
    więc krew bazowa, kill effect i head effect składają się w jeden plik.
    """
    text = cp.load("effects/bloodfx.dat")
    if text is None:
        return None
    changed = False
    colour = str(params.get("blood_colour") or "")
    if colour in BLOOD_COLOURS:
        red, green, blue = BLOOD_COLOURS[colour]
        text = cp.blood_colour(text, (red, green, blue), 255.0)
        changed = True
    size = str(params.get("blood_size") or "")
    if size in BLOOD_SIZES:
        text = cp.blood_size(text, BLOOD_SIZES[size])
        changed = True
    head_colour = str(params.get("head_colour") or "")
    if head_colour in BLOOD_COLOURS:
        red, green, blue = BLOOD_COLOURS[head_colour]
        text = cp.blood_head_colour(text, (red, green, blue), 255.0)
        changed = True
    head_size = str(params.get("head_size") or "")
    if head_size in HEAD_SIZES:
        text = cp.blood_head_size(text, HEAD_SIZES[head_size])
        changed = True
    return text if changed else None


def generate_weaponfx_dat(params: Dict[str, Any]) -> Optional[str]:
    """
    effects/weaponfx.dat — EFEKT STRZAŁU (traces): kolor śladu po kuli
    (kolumna COL_TINT) oraz rozmiar dziury (SIZE MIN/MAX).
    """
    text = cp.load("effects/weaponfx.dat")
    if text is None:
        return None
    changed = False
    colour = str(params.get("trace_colour") or "")
    if colour in TRACE_COLOURS:
        red, green, blue = TRACE_COLOURS[colour]
        text = cp.weaponfx_tint(text, (red, green, blue), 255.0)
        changed = True
    size = str(params.get("trace_size") or "")
    if size in TRACE_SIZES:
        text = cp.weaponfx_size(text, TRACE_SIZES[size])
        changed = True
    return text if changed else None


def generate_wheelfx_dat(params: Dict[str, Any]) -> Optional[str]:
    """effects/wheelfx.dat — ślady opon / drift (kolor skidmarków)."""
    text = cp.load("effects/wheelfx.dat")
    if text is None:
        return None
    colour = str(params.get("wheel_colour") or "")
    if colour not in WHEEL_COLOURS:
        return None
    red, green, blue = WHEEL_COLOURS[colour]
    return cp.wheelfx_tint(text, (red, green, blue))


def generate_decals_dat(params: Dict[str, Any]) -> Optional[str]:
    """effects/decals.dat — czyszczenie definicji dekali (śladów po kulach)."""
    text = cp.load("effects/decals.dat")
    if text is None:
        return cp.decals_clear("")
    if str(params.get("decals_style") or "") == "clear":
        return cp.decals_clear(text)
    return None


# ============================================================================
# 8. KATALOG OPCJI (kroki kreatora dla studia WWW i Discorda)
# ============================================================================

G_TIME = "2️⃣ CZAS — zawsze dzień / zawsze noc"
G_WEATHER = "3️⃣ POGODA — deszcz, śnieg, mgła"
G_SUN = "4️⃣ SŁOŃCE I KSIĘŻYC"
G_CLOUDS = "5️⃣ CHMURY"
G_WATER = "6️⃣ WODA"
G_FOG = "7️⃣ MGŁA"
G_LIGHT = "8️⃣ ŚWIATŁO"
G_POSTFX = "9️⃣ KOLORY (POSTFX)"
G_BLUR = "🔟 BLUR / DOF / LENS"
G_VISUAL = "⚙️ VISUAL SETTINGS"
G_KILL = "💀 KILL EFFECT"
G_FX = "💥 EKSPLOZJE I OGIEŃ"
G_PARTICLES = "💨 DYM I CZĄSTKI"
G_HUD = "🖥 HUD / UI"
G_FPS = "🚀 WYDAJNOŚĆ (FPS)"
G_BLOOD = "🩸 KREW"
G_TRACE = "🔫 EFEKT STRZAŁU (TRACES)"
G_WHEEL = "🛞 OPONY / DRIFT"
G_HEAD = "🎯 HEAD EFFECT"
G_REMOVE = "🚫 CZYŚCIEJ (BEZ ŚLADÓW)"

MOD_FILES = {
    "matol": "timecycle/MATOL.xml",
    "time": "levels/gta5/time.xml",
    "weather": "levels/gta5/weather.xml",
    "visual": "visualsettings.dat",
    "clouds": "clouds.xml",
    "cloudkeys": "cloudkeyframes.xml",
    "mods4": "timecycle/timecycle_mods_4.xml",
    "explosion": "effects/explosionfx.dat",
    "fire": "effects/firefx.dat",
    "entity": "effects/entityfx.dat",
    "pause": "ui/pausemenu.xml",
    "blood": "effects/bloodfx.dat",
    "weapon": "effects/weaponfx.dat",
    "wheel": "effects/wheelfx.dat",
    "decals": "effects/decals.dat",
}


def _step(group: str, sid: str, name: str, desc: str, image: str,
          gen_file: str, gen_params: Dict[str, Any]) -> Dict[str, Any]:
    """Krok kreatora oparty na patcherze pliku z paczki."""
    return {
        "group": group, "id": sid, "name": name, "description": desc,
        "image": "", "image_name": image,
        "file_url": "", "file_name": None,
        "target": "citizen/common/data",
        "generated": True,
        "gen_file": gen_file,
        "gen_params": gen_params,
    }


MOD_STEPS: List[Dict[str, Any]] = [
    # ---------------- 2. CZAS ----------------
    _step(G_TIME, "time-always-day", "☀️ Zawsze dzień (Always Day)",
          "Time jest ZATRZYMANY na 12:00 — wieczne południe, słońce wysoko (time.xml mode=static).",
          "TIME_DAY", MOD_FILES["time"], {"time_mode": "always-day"}),
    _step(G_TIME, "time-always-night", "🌙 Zawsze noc (Always Night)",
          "Time ZATRZYMANY na 00:00 — wieczna noc, świeci księżyc i latarnie.",
          "TIME_NIGHT", MOD_FILES["time"], {"time_mode": "always-night"}),
    _step(G_TIME, "time-golden", "🌇 Zawsze złota godzina",
          "Time ZATRZYMANY na 18:00 — wieczny zachód słońca, ciepłe światło.",
          "TIME_GOLDEN", MOD_FILES["time"], {"time_mode": "golden"}),
    _step(G_TIME, "time-sunrise", "🌅 Zawsze świt",
          "Time ZATRZYMANY na 06:00 — wieczny wschód, mgiełka i zimne światło.",
          "TIME_SUNRISE", MOD_FILES["time"], {"time_mode": "sunrise"}),
    _step(G_TIME, "time-dynamic", "🕐 Normalny cykl dobowy",
          "Domyślny, płynny cykl dnia i nocy (time.xml mode=dynamic).",
          "TIME_DYNAMIC", MOD_FILES["time"], {"time_mode": "dynamic"}),

    # ---------------- 3. POGODA ----------------
    _step(G_WEATHER, "weather-always-sunny", "☀️ Zawsze słonecznie",
          "Cykl zdominowany przez EXTRASUNNY/CLEAR — pełne słońce, zero deszczu.",
          "WEATHER_CLEAR", MOD_FILES["weather"], {"weather_style": "always-sunny"}),
    _step(G_WEATHER, "weather-always-rain", "🌧️ Zawsze deszcz",
          "Cały czas pada — mokre ulice, szare niebo (RAIN 100%).",
          "WEATHER_RAIN", MOD_FILES["weather"], {"weather_style": "always-rain"}),
    _step(G_WEATHER, "weather-stormy", "⛈️ Klimat burzowy",
          "Częste burze z błyskawicami (THUNDER + RAIN + mocny wiatr).",
          "WEATHER_STORM", MOD_FILES["weather"], {"weather_style": "stormy"}),
    _step(G_WEATHER, "weather-always-fog", "🌫️ Zawsze mgła",
          "Gęsta mgła non stop (FOGGY) — klimat horroru/survivalu.",
          "WEATHER_FOG", MOD_FILES["weather"], {"weather_style": "always-fog"}),
    _step(G_WEATHER, "weather-smog", "🏭 Smog miejski",
          "SMOG na zmianę z FOGGY — brudne, ciężkie powietrze w mieście.",
          "WEATHER_SMOG", MOD_FILES["weather"], {"weather_style": "smog"}),
    _step(G_WEATHER, "weather-snow", "❄️ Zawsze śnieg",
          "Pada śnieg (SNOW/BLIZZARD) — zima w Los Santos.",
          "WEATHER_SNOW", MOD_FILES["weather"], {"weather_style": "snow"}),
    _step(G_WEATHER, "weather-xmas", "🎄 Święta (Xmas)",
          "Odświeżone XMAS + śnieg + świąteczne chmury w mieście.",
          "WEATHER_XMAS", MOD_FILES["weather"], {"weather_style": "xmas"}),
    _step(G_WEATHER, "weather-dynamic", "🌦️ Dynamiczna (jak w grze)",
          "Pełny, wyważony cykl 15 typów pogody — jak w oryginalnym R*.",
          "WEATHER_DYN", MOD_FILES["weather"], {"weather_style": "balanced"}),

    # ---------------- 4. SŁOŃCE I KSIĘŻYC ----------------
    _step(G_SUN, "sun-warm", "🌞 Ciepłe słońce",
          "Złote, ciepłe światło kierunkowe + intensywne promienie (MATOL).",
          "SUN_WARM", MOD_FILES["matol"], {"sun_style": "warm"}),
    _step(G_SUN, "sun-cold", "🧊 Zimne słońce",
          "Chłodne, ostre światło — surowy, poranny look.",
          "SUN_COLD", MOD_FILES["matol"], {"sun_style": "cold"}),
    _step(G_SUN, "sun-golden", "🌇 Złota godzina",
          "Bardzo ciepłe światło, długie promienie, słońce nisko.",
          "SUN_GOLDEN", MOD_FILES["matol"], {"sun_style": "golden"}),
    _step(G_SUN, "sun-soft", "☁️ Miękkie światło",
          "Słabe promienie, łagodne cienie — mniej 'ostrości' (FPS + look).",
          "SUN_SOFT", MOD_FILES["matol"], {"sun_style": "soft"}),
    _step(G_SUN, "sun-rays-off", "🚫 Bez promieni słońca",
          "Wyłącza god rays (light_ray) — czyściej i taniej dla GPU.",
          "SUN_NORAY", MOD_FILES["matol"], {"sun_style": "rays-off"}),
    _step(G_SUN, "moon-huge", "🌕 Wielki księżyc",
          "Duża, jasna tarcza księżyca (sky_moon_disc_size 2.6).",
          "MOON_HUGE", MOD_FILES["matol"], {"moon_style": "huge"}),
    _step(G_SUN, "moon-small", "🌘 Mały księżyc",
          "Ciemna noc — mały, słaby księżyc.",
          "MOON_SMALL", MOD_FILES["matol"], {"moon_style": "small"}),
    _step(G_SUN, "moon-red", "🌑 Krwawy księżyc",
          "Czerwona tarcza księżyca — klimat grozy (PVP).",
          "MOON_RED", MOD_FILES["matol"], {"moon_style": "red"}),
    _step(G_SUN, "moon-blue", "🔵 Błękitny księżyc",
          "Chłodny, niebieskawy księżyc — zimowa noc.",
          "MOON_BLUE", MOD_FILES["matol"], {"moon_style": "blue"}),
    _step(G_SUN, "moon-dark", "⚫ Ciemna noc",
          "Prawie brak księżyca — bardzo ciemne noce (hardcore).",
          "MOON_DARK", MOD_FILES["matol"], {"moon_style": "dark"}),

    # ---------------- 5. CHMURY ----------------
    _step(G_CLOUDS, "clouds-matol-off", "🚫 Chmury OFF",
          "Zero chmur na niebie (sky_cloud_density_mult = 0) + FPS w górę.",
          "CLOUDS_OFF", MOD_FILES["matol"], {"cloud_matol": "off"}),
    _step(G_CLOUDS, "clouds-matol-dense", "☁️ Chmury gęste",
          "Pełne, ciężkie zachmurzenie nad całym miastem.",
          "CLOUDS_DENSE", MOD_FILES["matol"], {"cloud_matol": "dense"}),
    _step(G_CLOUDS, "clouds-matol-soft", "🌤️ Chmury miękkie",
          "Rozmyte, malarskie chmury (duża skala, miękka krawędź).",
          "CLOUDS_SOFT", MOD_FILES["matol"], {"cloud_matol": "soft"}),
    _step(G_CLOUDS, "clouds-matol-cotton", "🍥 Chmury kłębiaste",
          "Małe, gęste kłęby jak z anime (mała skala, ostry próg).",
          "CLOUDS_COTTON", MOD_FILES["matol"], {"cloud_matol": "cotton"}),
    _step(G_CLOUDS, "clouds-matol-dark", "🌩️ Chmury burzowe",
          "Ciemne, ołowiane chmury z mocnym cieniem.",
          "CLOUDS_DARK", MOD_FILES["matol"], {"cloud_matol": "dark"}),
    _step(G_CLOUDS, "clouds-matol-golden", "🌅 Złote chmury",
          "Chmury podświetlone ciepłym światłem zachodu.",
          "CLOUDS_GOLDEN", MOD_FILES["matol"], {"cloud_matol": "golden"}),
    _step(G_CLOUDS, "clouds-color-white", "🎨 Kolor chmur: biały",
          "Klasyczna biel (custom-clouds z paczki).",
          "CLOUDC_WHITE", MOD_FILES["matol"], {"cloud_color": "white"}),
    _step(G_CLOUDS, "clouds-color-pink", "🎨 Kolor chmur: różowy",
          "Pastelowe, różowe chmury — styl anime.",
          "CLOUDC_PINK", MOD_FILES["matol"], {"cloud_color": "pink"}),
    _step(G_CLOUDS, "clouds-color-purple", "🎨 Kolor chmur: fioletowy",
          "Cyberpunkowy fiolet na niebie.",
          "CLOUDC_PURPLE", MOD_FILES["matol"], {"cloud_color": "purple"}),
    _step(G_CLOUDS, "clouds-color-red", "🎨 Kolor chmur: czerwony",
          "Czerwone chmury — klimat grozy/PVP.",
          "CLOUDC_RED", MOD_FILES["matol"], {"cloud_color": "red"}),
    _step(G_CLOUDS, "clouds-color-cyan", "🎨 Kolor chmur: turkusowy",
          "Lodowe, turkusowe chmury.",
          "CLOUDC_CYAN", MOD_FILES["matol"], {"cloud_color": "cyan"}),
    _step(G_CLOUDS, "clouds-color-green", "🎨 Kolor chmur: zielony",
          "Zielone, toksyczne chmury (eventy).",
          "CLOUDC_GREEN", MOD_FILES["matol"], {"cloud_color": "green"}),
    _step(G_CLOUDS, "clouds-geom-high", "⬆️ Chmury wysoko",
          "Chmury wysoko nad miastem — więcej nieba nad głową.",
          "CLOUDG_HIGH", MOD_FILES["clouds"], {"clouds_geom": "high"}),
    _step(G_CLOUDS, "clouds-geom-low", "⬇️ Chmury nisko",
          "Nisko zawieszone chmury — duszny, zamknięty klimat.",
          "CLOUDG_LOW", MOD_FILES["clouds"], {"clouds_geom": "low"}),
    _step(G_CLOUDS, "clouds-geom-big", "🔭 Chmury wielkie",
          "Ogromne płaty chmur pokrywające całe niebo.",
          "CLOUDG_BIG", MOD_FILES["clouds"], {"clouds_geom": "big"}),
    _step(G_CLOUDS, "clouds-geom-small", "🔎 Chmury małe",
          "Drobne chmurki — lekkie, 'letnie' niebo.",
          "CLOUDG_SMALL", MOD_FILES["clouds"], {"clouds_geom": "small"}),
    _step(G_CLOUDS, "clouds-geom-rich", "💎 Chmury HD (jakość max)",
          "Pełna jakość warstw chmur (kosztuje FPS).",
          "CLOUDG_RICH", MOD_FILES["clouds"], {"clouds_geom": "rich"}),
    _step(G_CLOUDS, "clouds-geom-cheap", "🪶 Chmury tanie (FPS)",
          "Minimalna jakość warstw — zysk klatek.",
          "CLOUDG_CHEAP", MOD_FILES["clouds"], {"clouds_geom": "cheap"}),
    _step(G_CLOUDS, "clouds-key-dense", "🌧️ Gęstość chmur: duża",
          "Klatki kluczowe chmur: gęste pokrycie nieba (cloudkeyframes.xml).",
          "CLOUDK_DENSE", MOD_FILES["cloudkeys"], {"clouds_key": "dense"}),
    _step(G_CLOUDS, "clouds-key-sparse", "🌤️ Gęstość chmur: mała",
          "Rzadkie chmury — dużo czystego nieba.",
          "CLOUDK_SPARSE", MOD_FILES["cloudkeys"], {"clouds_key": "sparse"}),
    _step(G_CLOUDS, "clouds-key-fast", "💨 Szybkie chmury",
          "Chmury przewijają się 2.5× szybciej.",
          "CLOUDK_FAST", MOD_FILES["cloudkeys"], {"clouds_key": "fast"}),
    _step(G_CLOUDS, "clouds-key-slow", "🐢 Wolne chmury",
          "Powolne, leniwe chmury (klimat spokoju).",
          "CLOUDK_SLOW", MOD_FILES["cloudkeys"], {"clouds_key": "slow"}),
    _step(G_CLOUDS, "clouds-key-flat", "⬜ Chmury płaskie",
          "Spłaszczenie struktury chmur (płaska warstwa).",
          "CLOUDK_FLAT", MOD_FILES["cloudkeys"], {"clouds_key": "flat"}),
    _step(G_CLOUDS, "clouds-key-thin", "🎏 Chmury cienkie",
          "Cienka warstwa chmur — delikatny efekt.",
          "CLOUDK_THIN", MOD_FILES["cloudkeys"], {"clouds_key": "thin"}),

    # ---------------- 6. WODA ----------------
    _step(G_WATER, "water-clean", "💎 Czysta woda",
          "Przejrzysta woda, mocny refleks i podświetlenie dna.",
          "WATER_CLEAN", MOD_FILES["matol"], {"water_style": "clean"}),
    _step(G_WATER, "water-dark", "🖤 Ciemna woda",
          "Ciemna, głęboka toń — mroczny klimat.",
          "WATER_DARK", MOD_FILES["matol"], {"water_style": "dark"}),
    _step(G_WATER, "water-mirror", "🪞 Lustro (odbicia)",
          "Maksymalne odbicia nieba i dalekich świateł w wodzie.",
          "WATER_MIRROR", MOD_FILES["matol"], {"water_style": "mirror"}),
    _step(G_WATER, "water-calm", "🧘 Spokojna woda",
          "Zero fal, zero piany — tafla jak szkło.",
          "WATER_CALM", MOD_FILES["matol"], {"water_style": "calm"}),
    _step(G_WATER, "water-storm", "🌊 Wzburzona woda",
          "Wysokie fale i dużo piany (sztorm).",
          "WATER_STORM", MOD_FILES["matol"], {"water_style": "storm"}),
    _step(G_WATER, "water-no-foam", "🚫 Woda bez piany",
          "Usuwa pianę przy brzegach.",
          "WATER_NOFOAM", MOD_FILES["matol"], {"water_style": "no-foam"}),

    # ---------------- 7. MGŁA ----------------
    _step(G_FOG, "fog-off", "🚫 Wyłącz mgłę",
          "Zero mgły — maksymalna widoczność (FPS + widok).",
          "FOG_OFF", MOD_FILES["matol"], {"fog_style": "off"}),
    _step(G_FOG, "fog-light", "🌤️ Mgła lekka",
          "Delikatna mgiełka na horyzoncie.",
          "FOG_LIGHT", MOD_FILES["matol"], {"fog_style": "light"}),
    _step(G_FOG, "fog-dense", "🌫️ Mgła gęsta",
          "Gęsta mgła ograniczająca widoczność.",
          "FOG_DENSE", MOD_FILES["matol"], {"fog_style": "dense"}),
    _step(G_FOG, "fog-horror", "👻 Mgła horror",
          "Bardzo gęsta, sina mgła — klimat horroru.",
          "FOG_HORROR", MOD_FILES["matol"], {"fog_style": "horror"}),
    _step(G_FOG, "fog-no-volume", "🚫 Bez mgły objętościowej",
          "Usuwa mgłę wolumetryczną (lightning/fogvolume).",
          "FOG_NOVOL", MOD_FILES["matol"], {"fog_style": "no-volume"}),

    # ---------------- 8. ŚWIATŁO ----------------
    _step(G_LIGHT, "light-street-bright", "💡 Latarnie mocne",
          "Mocniejsze światło latarni i neonów w mieście.",
          "LIGHT_STREET", MOD_FILES["matol"], {"light_style": "street-bright"}),
    _step(G_LIGHT, "light-street-off", "🔌 Latarnie OFF",
          "Wyłącza światło latarni (hardcore / horror).",
          "LIGHT_STREETOFF", MOD_FILES["matol"], {"light_style": "street-off"}),
    _step(G_LIGHT, "light-night-bright", "🌙 Jaśniejsze noce",
          "Podnosi światło otoczenia nocą — lepsza widoczność bez noktowizji.",
          "LIGHT_NIGHT", MOD_FILES["matol"], {"light_style": "night-bright"}),
    _step(G_LIGHT, "light-ped-visible", "🧍 Widoczni gracze",
          "Mocniejsza obwódka/rim na postaciach — łatwiej ich wypatrzeć.",
          "LIGHT_PED", MOD_FILES["matol"], {"light_style": "ped-visible"}),
    _step(G_LIGHT, "light-warm", "🟠 Ciepłe światła",
          "Pomarańczowe światła latarni i wnętrz (wieczorny klimat).",
          "LIGHT_WARM", MOD_FILES["matol"], {"light_style": "warm"}),
    _step(G_LIGHT, "light-cold", "🔵 Zimne światła",
          "Białe, chłodne światła (nowoczesne miasto / noc).",
          "LIGHT_COLD", MOD_FILES["matol"], {"light_style": "cold"}),
    _step(G_LIGHT, "light-interiors", "🏠 Jasne wnętrza",
          "Rozjaśnia wnętrza (ambient occlusion i wrap światła).",
          "LIGHT_INT", MOD_FILES["matol"], {"light_style": "interiors"}),

    # ---------------- 9. KOLORY (POSTFX) ----------------
    _step(G_POSTFX, "postfx-vivid", "🌈 Kolory vivid",
          "Nasycone kolory + lekki bloom (najpopularniejszy look).",
          "POSTFX_VIVID", MOD_FILES["matol"], {"postfx_style": "vivid"}),
    _step(G_POSTFX, "postfx-cold", "❄️ Klimat zimny",
          "Zimny filtr kolorystyczny (niebieski shift).",
          "POSTFX_COLD", MOD_FILES["matol"], {"postfx_style": "cold"}),
    _step(G_POSTFX, "postfx-film", "🎬 Kinowy look",
          "Filmowy tonemapping + winieta + ziarno.",
          "POSTFX_FILM", MOD_FILES["matol"], {"postfx_style": "film"}),
    _step(G_POSTFX, "postfx-contrast", "🌗 Wysoki kontrast",
          "Mocniejszy kontrast (filmic curve) — 'ostry' obraz.",
          "POSTFX_CONTRAST", MOD_FILES["matol"], {"postfx_style": "contrast"}),
    _step(G_POSTFX, "postfx-desat", "🩶 Wyprane kolory",
          "Celowa desaturacja — surowy, wojenny klimat.",
          "POSTFX_DESAT", MOD_FILES["matol"], {"postfx_style": "desat"}),
    _step(G_POSTFX, "postfx-bloom-off", "🚫 Bloom OFF",
          "Wyłącza bloom (mniej 'świecenia', oszczędza GPU).",
          "POSTFX_NOBLOOM", MOD_FILES["matol"], {"postfx_style": "bloom-off"}),
    _step(G_POSTFX, "postfx-vignette-off", "🚫 Winieta OFF",
          "Bez ciemnych rogów ekranu.",
          "POSTFX_NOVIG", MOD_FILES["matol"], {"postfx_style": "vignette-off"}),
    _step(G_POSTFX, "postfx-neutral", "⚪ Neutralne (jak R*)",
          "Czysty, naturalny obraz bez dodatków.",
          "POSTFX_NEUTRAL", MOD_FILES["matol"], {"postfx_style": "neutral"}),

    # ---------------- 10. BLUR / DOF / LENS ----------------
    _step(G_BLUR, "blur-motion-off", "🚫 Motion blur OFF",
          "Wyłącza rozmycie ruchu — obraz zawsze ostry.",
          "BLUR_MOTION", MOD_FILES["matol"], {"blur_style": "motion-off"}),
    _step(G_BLUR, "blur-screen-off", "🚫 Blur ekranu OFF",
          "Bez rozmycia całego ekranu (screen_blur_intensity).",
          "BLUR_SCREEN", MOD_FILES["matol"], {"blur_style": "screen-off"}),
    _step(G_BLUR, "blur-dof-off", "🚫 Depth of Field OFF",
          "Wyłącza rozmycie tła (DOF) — widzisz wszystko ostro.",
          "BLUR_DOF", MOD_FILES["matol"], {"blur_style": "dof-off"}),
    _step(G_BLUR, "blur-lens-off", "🚫 Efekty obiektywu OFF",
          "Bez brudu, zniekształceń i artefaktów soczewki.",
          "BLUR_LENS", MOD_FILES["matol"], {"blur_style": "lens-off"}),
    _step(G_BLUR, "blur-chroma-off", "🚫 Aberracja chromatyczna OFF",
          "Bez rozjeżdżania kolorów na krawędziach.",
          "BLUR_CHROMA", MOD_FILES["matol"], {"blur_style": "chroma-off"}),
    _step(G_BLUR, "blur-bokeh-off", "🚫 Bokeh OFF",
          "Bez efektu bokeh (krążki rozmycia).",
          "BLUR_BOKEH", MOD_FILES["matol"], {"blur_style": "bokeh-off"}),
    _step(G_BLUR, "blur-all-off", "🧼 Wszystko wyłączone (czysty obraz)",
          "Blur, DOF, soczewka i screen blur naraz OFF — max czytelności i FPS.",
          "BLUR_ALL", MOD_FILES["matol"], {"blur_style": "all-off"}),

    # ---------------- 11. VISUAL SETTINGS ----------------
    _step(G_VISUAL, "visual-rain-off", "🚫 Wyłącz deszcz",
          "rain.NumberParticles = 0 — zero kropel (FPS + czysto).",
          "RAIN_OFF", MOD_FILES["visual"], {"rain_vis": "off"}),
    _step(G_VISUAL, "visual-rain-light", "🌦️ Deszcz lekki",
          "Subtelny deszcz — mniej cząstek, delikatny efekt.",
          "RAIN_LIGHT", MOD_FILES["visual"], {"rain_vis": "light"}),
    _step(G_VISUAL, "visual-rain-heavy", "🌧️ Deszcz mocny",
          "Dużo cząstek, mokre ulice, mocny efekt deszczu.",
          "RAIN_HEAVY", MOD_FILES["visual"], {"rain_vis": "heavy"}),
    _step(G_VISUAL, "visual-rain-insane", "🌊 Deszcz ekstremalny",
          "Ulewa w stylu huraganu (5200 cząstek).",
          "RAIN_INSANE", MOD_FILES["visual"], {"rain_vis": "insane"}),
    _step(G_VISUAL, "visual-cycle-fast", "⏩ Szybka zmiana pogody",
          "Pogoda zmienia się co 90 s zamiast co 240 s.",
          "CYCLE_FAST", MOD_FILES["visual"], {"cycle_vis": "fast"}),
    _step(G_VISUAL, "visual-cycle-slow", "⏪ Wolna zmiana pogody",
          "Pogoda zmienia się co 15 minut.",
          "CYCLE_SLOW", MOD_FILES["visual"], {"cycle_vis": "slow"}),
    _step(G_VISUAL, "visual-cycle-frozen", "🧊 Pogoda bez zmian",
          "Cykl praktycznie zatrzymany — pogoda stoi w miejscu.",
          "CYCLE_FROZEN", MOD_FILES["visual"], {"cycle_vis": "frozen"}),
    _step(G_VISUAL, "visual-sun-big", "🔆 Duże słońce",
          "Powiększa tarczę słońca (sky.sun.centre/sunAxias).",
          "VIS_SUNBIG", MOD_FILES["visual"], {"sun_vis": "big"}),
    _step(G_VISUAL, "visual-sun-small", "🔅 Małe słońce",
          "Zmniejsza tarczę słońca — subtelniejsze niebo.",
          "VIS_SUNSMALL", MOD_FILES["visual"], {"sun_vis": "small"}),
    _step(G_VISUAL, "visual-sun-glow", "🌟 Poświata słońca",
          "Mocniejsza poświata (inscattering) wokół słońca.",
          "VIS_SUNGLOW", MOD_FILES["visual"], {"sun_vis": "glow"}),
    _step(G_VISUAL, "visual-cloud-motion-off", "🚫 Chmury bez ruchu",
          "Chmury stoją w miejscu (GameCloudSpeed = 0).",
          "VIS_CLOUDSTOP", MOD_FILES["visual"], {"cloud_vis": "motion-off"}),
    _step(G_VISUAL, "visual-cloud-fast", "💨 Chmury szybkie",
          "Chmury pędzą po niebie 3.5× szybciej.",
          "VIS_CLOUDFAST", MOD_FILES["visual"], {"cloud_vis": "fast"}),
    _step(G_VISUAL, "visual-cloud-slow", "🐌 Chmury wolne",
          "Chmury płyną powoli i leniwie.",
          "VIS_CLOUDSLOW", MOD_FILES["visual"], {"cloud_vis": "slow"}),
    _step(G_VISUAL, "visual-shadow-off", "🚫 Cienie chmur OFF",
          "Bez cieni rzucanych przez chmury (zysk FPS).",
          "VIS_SHADOWOFF", MOD_FILES["visual"], {"shadow_vis": "off"}),
    _step(G_VISUAL, "visual-shadow-on", "🌑 Cienie chmur ON",
          "Wyraźne cienie chmur na ziemi (klimat + FPS koszt).",
          "VIS_SHADOWON", MOD_FILES["visual"], {"shadow_vis": "on"}),
    _step(G_VISUAL, "visual-puddle-off", "🚫 Kałuże OFF",
          "Bez kałuż i ich odbić po deszczu (FPS + czysto).",
          "VIS_PUDDLEOFF", MOD_FILES["visual"], {"puddle_vis": "off"}),
    _step(G_VISUAL, "visual-puddle-on", "💧 Kałuże ON (odbicia)",
          "Mokre ulice z odbiciami po deszczu.",
          "VIS_PUDDLEON", MOD_FILES["visual"], {"puddle_vis": "on"}),
    _step(G_VISUAL, "visual-car-interior-on", "🚗 Światła w autach ON",
          "Podświetlenie wnętrz pojazdów (licznik, deska).",
          "VIS_CARON", MOD_FILES["visual"], {"car_vis": "interior-on"}),
    _step(G_VISUAL, "visual-car-interior-off", "🚗 Światła w autach OFF",
          "Bez podświetlenia wnętrz (czysto + FPS).",
          "VIS_CAROFF", MOD_FILES["visual"], {"car_vis": "interior-off"}),
    _step(G_VISUAL, "visual-dof-off", "🚫 Adaptacyjny DOF OFF",
          "Wyłącza adaptacyjne rozmycie (adaptivedof) w visualsettings.",
          "VIS_DOFOFF", MOD_FILES["visual"], {"dof_vis": "off"}),

    # ---------------- 13. KILL EFFECT ----------------
    _step(G_KILL, "kill-blue", "💙 Kill: niebieski",
          "Niebieski błysk i winieta po zabójstwie.",
          "KILL_BLUE", MOD_FILES["mods4"], {"kill_color": "blue"}),
    _step(G_KILL, "kill-red", "❤️ Kill: czerwony",
          "Czerwony błysk krwi po zabójstwie.",
          "KILL_RED", MOD_FILES["mods4"], {"kill_color": "red"}),
    _step(G_KILL, "kill-green", "💚 Kill: zielony",
          "Zielony błysk (kwasowy) po zabójstwie.",
          "KILL_GREEN", MOD_FILES["mods4"], {"kill_color": "green"}),
    _step(G_KILL, "kill-purple", "💜 Kill: fioletowy",
          "Fioletowy, cyberpunkowy efekt zabójstwa.",
          "KILL_PURPLE", MOD_FILES["mods4"], {"kill_color": "purple"}),
    _step(G_KILL, "kill-gold", "💛 Kill: złoty",
          "Złoty błysk — efekt 'legendy'.",
          "KILL_GOLD", MOD_FILES["mods4"], {"kill_color": "gold"}),
    _step(G_KILL, "kill-acid", "🧪 Kill: kwasowy",
          "Jaskrawy, kwasowy błysk po zabiciu.",
          "KILL_ACID", MOD_FILES["mods4"], {"kill_color": "acid"}),
    _step(G_KILL, "kill-white", "🤍 Kill: biały",
          "Czysty, biały błysk — minimalny i elegancki.",
          "KILL_WHITE", MOD_FILES["mods4"], {"kill_color": "white"}),
    _step(G_KILL, "kill-black", "🖤 Kill: czarny",
          "Czarna winieta — mroczny, 'cinematic' efekt.",
          "KILL_BLACK", MOD_FILES["mods4"], {"kill_color": "black"}),
    _step(G_KILL, "kill-subtle", "🔅 Siła: subtelna",
          "Delikatny efekt — ledwo zauważalny.",
          "KILL_SUBTLE", MOD_FILES["mods4"], {"kill_style": "subtle"}),
    _step(G_KILL, "kill-normal", "🔆 Siła: normalna",
          "Domyślny efekt z paczki (winieta 0.9, desat 0.7).",
          "KILL_NORMAL", MOD_FILES["mods4"], {"kill_style": "normal"}),
    _step(G_KILL, "kill-strong", "💥 Siła: mocna",
          "Mocna winieta i desaturacja po zabójstwie.",
          "KILL_STRONG", MOD_FILES["mods4"], {"kill_style": "strong"}),
    _step(G_KILL, "kill-extreme", "☠️ Siła: EXTREME",
          "Maksymalny efekt — pełny ekran w kolorze kill effectu.",
          "KILL_EXTREME", MOD_FILES["mods4"], {"kill_style": "extreme"}),
    _step(G_KILL, "kill-off", "🚫 Kill effect OFF",
          "Bez efektu po zabójstwie (czysty obraz).",
          "KILL_OFF", MOD_FILES["mods4"], {"kill_style": "off"}),
    _step(G_KILL, "kill-blur-off", "🚫 Blur kill effectu OFF",
          "Bez rozmycia ekranu w momencie zabicia.",
          "KILL_BLUROFF", MOD_FILES["mods4"], {"kill_blur": "off"}),
    _step(G_KILL, "kill-blur-soft", "🌫️ Blur kill effectu: miękki",
          "Lekkie rozmycie przy zabójstwie.",
          "KILL_BLURSOFT", MOD_FILES["mods4"], {"kill_blur": "soft"}),
    _step(G_KILL, "kill-blur-strong", "🌀 Blur kill effectu: mocny",
          "Mocne rozmycie ekranu przy zabójstwie.",
          "KILL_BLURSTRONG", MOD_FILES["mods4"], {"kill_blur": "strong"}),

    # ---------------- 14. EKSPLOZJE I OGIEŃ ----------------
    _step(G_FX, "expl-tiny", "🔉 Eksplozje małe (0.5×)",
          "Zmniejsza siłę (SCALE) i zasięg wybuchów — mniej chaosu.",
          "EXPL_TINY", MOD_FILES["explosion"], {"expl_scale": "tiny"}),
    _step(G_FX, "expl-big", "🔊 Eksplozje mocne (1.6×)",
          "Większe wybuchy — efektowniej na PVP.",
          "EXPL_BIG", MOD_FILES["explosion"], {"expl_scale": "big"}),
    _step(G_FX, "expl-huge", "💥 Eksplozje OGROMNE (2.5×)",
          "Podwójna+ skala wybuchów i szerszy zasięg.",
          "EXPL_HUGE", MOD_FILES["explosion"], {"expl_scale": "huge"}),
    _step(G_FX, "expl-insane", "☄️ Eksplozje EXTREME (4×)",
          "Ekstremalna siła wybuchów (uwaga na FPS).",
          "EXPL_INSANE", MOD_FILES["explosion"], {"expl_scale": "insane"}),
    _step(G_FX, "expl-scorch-off", "🚫 Bez przypaleń",
          "Wybuchy nie zostawiają śladów przypalenia (SCORCH = 0).",
          "EXPL_NOSCORCH", MOD_FILES["explosion"], {"expl_scorch": "off"}),
    _step(G_FX, "expl-count-more", "🔢 Więcej wybuchów",
          "Zwiększa liczbę eksplozji przy pojazdach (NUMBER = 6).",
          "EXPL_MORE", MOD_FILES["explosion"], {"expl_count": "more"}),
    _step(G_FX, "expl-count-less", "🔢 Mniej wybuchów",
          "Mniej jednoczesnych wybuchów (FPS + czytelność).",
          "EXPL_LESS", MOD_FILES["explosion"], {"expl_count": "less"}),
    _step(G_FX, "fire-short", "🔥 Ogień szybko gaśnie",
          "Krótszy czas i siła palenia materiałów (0.35×).",
          "FIRE_SHORT", MOD_FILES["fire"], {"fire_style": "short"}),
    _step(G_FX, "fire-long", "🔥 Ogień długo się pali",
          "Dłuższe, mocniejsze palenie (2.5×).",
          "FIRE_LONG", MOD_FILES["fire"], {"fire_style": "long"}),
    _step(G_FX, "fire-eternal", "🔥🔥 Ogień wieczny",
          "Ogień praktycznie nie gaśnie (5×).",
          "FIRE_ETERNAL", MOD_FILES["fire"], {"fire_style": "eternal"}),
    _step(G_FX, "fire-off", "🚫 Ogień bez rozprzestrzeniania",
          "Zeruje palenie — ogień się nie roznosi.",
          "FIRE_OFF", MOD_FILES["fire"], {"fire_style": "off"}),

    # ---------------- 15. DYM I CZĄSTKI ----------------
    _step(G_PARTICLES, "smoke-off", "🚭 Smok i para OFF",
          "Zeruje próg pojawiania się dymu i pary w otoczeniu.",
          "SMOKE_OFF", MOD_FILES["entity"], {"smoke_style": "off"}),
    _step(G_PARTICLES, "dust-off", "🌪️ Kurz i pył OFF",
          "Wyłącza kurz/drobne cząstki (DST_*) — czystszy obraz.",
          "DUST_OFF", MOD_FILES["entity"], {"particle_style": "dust-off"}),
    _step(G_PARTICLES, "ambient-off", "🌫️ Cząstki otoczenia OFF",
          "Wyłącza wszystkie cząstki ambientowe (AMB_*) — największy zysk FPS.",
          "AMBIENT_OFF", MOD_FILES["entity"], {"particle_style": "ambient-off"}),
    _step(G_PARTICLES, "particles-all-off", "🧹 Wszystkie cząstki OFF",
          "Dym, para, kurz i cząstki otoczenia naraz OFF.",
          "PARTICLES_ALL", MOD_FILES["entity"], {"smoke_style": "off", "particle_style": "all-off"}),

    # ---------------- 16. HUD / UI ----------------
    _step(G_HUD, "hud-clean", "🧼 Czyste menu pauzy",
          "Zeruje tła menu pauzy (minimapa/galeria) — przejrzysty HUD.",
          "HUD_CLEAN", MOD_FILES["pause"], {"hud_style": "clean"}),
    _step(G_HUD, "hud-clean-avatars", "👤 Bez tła awatarów",
          "Ukrywa tła postaci w menu pauzy (zostawia minimapę).",
          "HUD_AVATARS", MOD_FILES["pause"], {"hud_style": "clean-avatars"}),
    _step(G_HUD, "hud-big", "🔍 Większy interfejs",
          "Skaluje elementy menu pauzy +15%.",
          "HUD_BIG", MOD_FILES["pause"], {"hud_style": "big"}),
    _step(G_HUD, "hud-small", "🔎 Mniejszy interfejs",
          "Skaluje elementy menu pauzy −15%.",
          "HUD_SMALL", MOD_FILES["pause"], {"hud_style": "small"}),

    # ---------------- 17. WYDAJNOŚĆ (FPS) ----------------
    _step(G_FPS, "fps-ssao-off", "🚀 SSAO OFF",
          "Wyłącza ambient occlusion — duży zysk klatek.",
          "FPS_SSAO", MOD_FILES["matol"], {"fps_style": "ssao-off"}),
    _step(G_FPS, "fps-reflections-off", "🚀 Odbicia wody OFF",
          "Wyłącza odbicia w wodzie i ich zakresy LOD.",
          "FPS_REFL", MOD_FILES["matol"], {"fps_style": "reflections-off"}),
    _step(G_FPS, "fps-sprites-off", "🚀 Poświaty świateł OFF",
          "Wyłącza sprite'y/coronę dalekich świateł.",
          "FPS_SPRITES", MOD_FILES["matol"], {"fps_style": "sprites-off"}),
    _step(G_FPS, "fps-lod-low", "🚀 Mniejszy zasięg detali",
          "Obniża LOD (hd/lod/slod2) — więcej FPS w mieście.",
          "FPS_LOD", MOD_FILES["matol"], {"fps_style": "lod-low"}),
    _step(G_FPS, "fps-light-low", "🚀 Tańsze światło",
          "Upraszcza dynamiczne oświetlenie (light bake tweak).",
          "FPS_LIGHT", MOD_FILES["matol"], {"fps_style": "light-low"}),

    # ---------------- 18. KREW (effects/bloodfx.dat) ----------------
    _step(G_BLOOD, "blood-red", "🩸 Krew klasyczna (czerwona)",
          "Krwawa czerwień (R200 G20 B20) we wszystkich kościach — wygląda jak w FiveM PVP.",
          "BLOOD_RED", MOD_FILES["blood"], {"blood_colour": "red"}),
    _step(G_BLOOD, "blood-dark", "🩸 Krew ciemna (klimat horroru)",
          "Ciemna, gęsta krew (R70) — mrok i brutalny klimat.",
          "BLOOD_DARK", MOD_FILES["blood"], {"blood_colour": "dark"}),
    _step(G_BLOOD, "blood-anime", "🌸 Krew anime (jasny róż)",
          "Jaskrawy róż (R255 G70 B130) — styl anime / cel-shading.",
          "BLOOD_ANIME", MOD_FILES["blood"], {"blood_colour": "anime"}),
    _step(G_BLOOD, "blood-plasma", "🔵 Krew plazma (niebieska)",
          "Niebieska ciecz (R70 G130 B255) — sci-fi / cyberpunk.",
          "BLOOD_PLASMA", MOD_FILES["blood"], {"blood_colour": "plasma"}),
    _step(G_BLOOD, "blood-toxic", "☣️ Krew toksyczna (zielona)",
          "Toksyczna zieleń (R90 G255 B70) — zombie / survival.",
          "BLOOD_TOXIC", MOD_FILES["blood"], {"blood_colour": "toxic"}),
    _step(G_BLOOD, "blood-black", "⚫ Krew czarna (mrok / tryhard)",
          "Czarna ciecz (R25) — maksymalny kontrast na ekranie.",
          "BLOOD_BLACK", MOD_FILES["blood"], {"blood_colour": "black"}),
    _step(G_BLOOD, "blood-purple", "🟣 Krew fioletowa",
          "Fiolet (R170 G60 B255) — neonowy, klubowy klimat.",
          "BLOOD_PURPLE", MOD_FILES["blood"], {"blood_colour": "purple"}),
    _step(G_BLOOD, "blood-more", "💥 Więcej krwi (plamy 1.8×)",
          "Zwiększa rozmiar plam krwi (wartość 295 → ~530), bez zmiany koloru.",
          "BLOOD_MORE", MOD_FILES["blood"], {"blood_size": "more"}),
    _step(G_BLOOD, "blood-huge", "🩸💥 KRWI OPAD: czerwona + ogromne plamy",
          "Czerwona krew ORAZ plamy 2.4× naraz — wszystko scala się w jeden bloodfx.dat.",
          "BLOOD_HUGE", MOD_FILES["blood"], {"blood_colour": "red", "blood_size": "huge"}),
    _step(G_BLOOD, "blood-less", "🧹 Mniej krwi (dyskretna, 0.5×)",
          "Zmniejsza plamy krwi — czystszy obraz, mniej wizualnego szumu.",
          "BLOOD_LESS", MOD_FILES["blood"], {"blood_size": "less"}),

    # ---------------- 19. EFEKT STRZAŁU (effects/weaponfx.dat) ----------------
    _step(G_TRACE, "trace-red", "🔴 Ślady po kulach: czerwone",
          "Kolor tracersów/śladów po pociskach w kolumnie COL_TINT.",
          "TRACE_RED", MOD_FILES["weapon"], {"trace_colour": "red"}),
    _step(G_TRACE, "trace-blue", "🔵 Ślady po kulach: niebieskie",
          "Niebieskie ślady po kulach — wyraźne na ciemnym tle.",
          "TRACE_BLUE", MOD_FILES["weapon"], {"trace_colour": "blue"}),
    _step(G_TRACE, "trace-green", "🟢 Ślady po kulach: zielone",
          "Zielone ślady po kulach.",
          "TRACE_GREEN", MOD_FILES["weapon"], {"trace_colour": "green"}),
    _step(G_TRACE, "trace-pink", "🩷 Ślady po kulach: neonowy róż",
          "Różowe ślady — bardzo dobrze widoczne w PVP.",
          "TRACE_PINK", MOD_FILES["weapon"], {"trace_colour": "pink"}),
    _step(G_TRACE, "trace-toxic", "🧪 Ślady po kulach: toksyczne",
          "Kwasowo-limonkowe ślady (R180 G255 B40).",
          "TRACE_TOXIC", MOD_FILES["weapon"], {"trace_colour": "toxic"}),
    _step(G_TRACE, "trace-black", "⚫ Ślady po kulach: czarne (taktyczne)",
          "Czarne ślady — czysty, wojskowy look.",
          "TRACE_BLACK", MOD_FILES["weapon"], {"trace_colour": "black"}),
    _step(G_TRACE, "trace-big", "🕳 Duże dziury po kulach (2×)",
          "Podwaja rozmiar śladu po pocisku (SIZE MIN/MAX).",
          "TRACE_BIG", MOD_FILES["weapon"], {"trace_size": "big"}),
    _step(G_TRACE, "trace-huge", "🕳💥 Ogromne ślady (3×)",
          "Potrójny rozmiar śladów po kulach — „widać każdy strzał”.",
          "TRACE_HUGE", MOD_FILES["weapon"], {"trace_size": "huge"}),
    _step(G_TRACE, "trace-small", "🎯 Precyzyjne ślady (0.6×)",
          "Mniejsze ślady po kulach — mniej bałaganu na ścianach.",
          "TRACE_SMALL", MOD_FILES["weapon"], {"trace_size": "small"}),
    _step(G_TRACE, "trace-neon-red", "🌈 NEON: czerwone + duże",
          "Czerwone ślady ORAZ rozmiar 2× — scala się w jeden weaponfx.dat.",
          "TRACE_NEON", MOD_FILES["weapon"], {"trace_colour": "red", "trace_size": "big"}),

    # ---------------- 20. OPONY / DRIFT (effects/wheelfx.dat) ----------------
    _step(G_WHEEL, "wheel-dark", "🛞 Czarne ślady opon",
          "Klasyczne, ciemne skidmarki — jak w czystej grze.",
          "WHEEL_DARK", MOD_FILES["wheel"], {"wheel_colour": "dark"}),
    _step(G_WHEEL, "wheel-white", "⚪ Białe ślady (styl drift)",
          "Jasne ślady opon — efektownie wygląda przy paleniu gumy.",
          "WHEEL_WHITE", MOD_FILES["wheel"], {"wheel_colour": "white"}),
    _step(G_WHEEL, "wheel-neon", "🌈 Neonowe ślady opon",
          "Różowo-neonowe skidmarki — pod drift-miasta i roleplay.",
          "WHEEL_NEON", MOD_FILES["wheel"], {"wheel_colour": "neon"}),
    _step(G_WHEEL, "wheel-red", "🔴 Czerwone ślady opon",
          "Czerwone skidmarki — mocny, agresywny styl.",
          "WHEEL_RED", MOD_FILES["wheel"], {"wheel_colour": "red"}),

    # ---------------- 21. HEAD EFFECT (bloodfx.dat, wiersz HEAD) --------------
    _step(G_HEAD, "head-massive", "🎯 Headshot MASYWNY (2.5×)",
          "Trafienie w głowę daje spektakularny wytrysk — rozmiar krwi głowy ×2.5 "
          "(osobny wiersz HEAD w bloodfx.dat).",
          "HEAD_MASSIVE", MOD_FILES["blood"], {"head_size": "massive"}),
    _step(G_HEAD, "head-big", "🎯 Headshot wyraźny (1.7×)",
          "Wyraźniejsza krew z głowy, bez przesady — dobry balans na PVP.",
          "HEAD_BIG", MOD_FILES["blood"], {"head_size": "big"}),
    _step(G_HEAD, "head-red", "🎯 Headshot czerwony (krew głowy)",
          "Krew z głowy na jaskrawą czerwień (R255 G60 B60) — mocno widoczne trafienie.",
          "HEAD_RED", MOD_FILES["blood"], {"head_colour": "red"}),
    _step(G_HEAD, "head-white", "🎯 Headshot biały (flash)",
          "Biały wytrysk — czytelny „hit marker” wizualny.",
          "HEAD_WHITE", MOD_FILES["blood"], {"head_colour": "white"}),
    _step(G_HEAD, "head-toxic", "🎯 Headshot toksyczny",
          "Zielony wytrysk — styl zombie/survival.",
          "HEAD_TOXIC", MOD_FILES["blood"], {"head_colour": "toxic"}),
    _step(G_HEAD, "head-off", "🚫 Head effect OFF",
          "Minimalna krew z głowy (rozmiar 0.2×) — dla osób, które chcą czysty obraz.",
          "HEAD_OFF", MOD_FILES["blood"], {"head_size": "off"}),
    _step(G_HEAD, "head-combo", "🎯💥 HEADSHOT: czerwony + MASYWNY",
          "Czerwona krew głowy ORAZ rozmiar 2.5× naraz — maksymalny efekt headshota.",
          "HEAD_COMBO", MOD_FILES["blood"], {"head_colour": "red", "head_size": "massive"}),

    # ---------------- 22. CZYŚCIEJ — BEZ ŚLADÓW (decals) ----------------
    _step(G_REMOVE, "decals-clear", "🚫 Bez definicji dekali",
          "Czyści tabelę dekali (śladów po kulach/oponach) — lżejszy render i czystsza mapa.",
          "DECALS_OFF", MOD_FILES["decals"], {"decals_style": "clear"}),
]


# ============================================================================
# 9. ZESTAWY (BUNDLE) — jedno kliknięcie = gotowy, spójny build
# ============================================================================

BUNDLES: List[Dict[str, Any]] = [
    {
        "id": "bundle-pvp", "name": "⚔️ PVP / Tryhard", "icon": "⚔️",
        "desc": "Maksymalna czytelność: czyste niebo, bez mgły/blurów, "
                "mocne światła, kill effect EXTREME i mocne eksplozje.",
        "steps": ["sky-preset-clean-fps", "time-always-day", "weather-always-sunny",
                  "fog-off", "blur-all-off", "postfx-vivid", "light-street-bright",
                  "light-ped-visible", "kill-red", "kill-extreme", "kill-blur-off",
                  "expl-huge", "visual-rain-off", "clouds-matol-soft", "hud-clean"],
    },
    {
        "id": "bundle-cinematic", "name": "🎬 Kinowy look", "icon": "🎬",
        "desc": "Filmowa estetyka: złota godzina, chmury, mgła, winieta, "
                "miękkie słońce i kinowy grading.",
        "steps": ["sky-preset-tropical", "time-golden", "weather-always-sunny",
                  "sun-golden", "moon-huge", "clouds-matol-golden", "clouds-color-pink",
                  "fog-light", "postfx-film", "light-warm", "visual-cloud-slow",
                  "kill-black", "kill-normal", "fire-long"],
    },
    {
        "id": "bundle-maxfps", "name": "🚀 Max FPS", "icon": "🚀",
        "desc": "Wydajność przede wszystkim: bez SSAO, odbić, mgły, cząstek, "
                "dymu, blurów i chmur.",
        "steps": ["sky-preset-clean-fps", "clouds-matol-off", "fog-off", "fps-ssao-off",
                  "fps-reflections-off", "fps-sprites-off", "fps-lod-low",
                  "blur-all-off", "particles-all-off", "visual-rain-off",
                  "visual-shadow-off", "visual-puddle-off", "postfx-bloom-off",
                  "visual-car-interior-off"],
    },
    {
        "id": "bundle-night", "name": "🌃 Cyberpunk Night", "icon": "🌃",
        "desc": "Wieczna noc: neonowe niebo, wielki księżyc, mokre ulice "
                "i mocne neony miasta.",
        "steps": ["sky-preset-neon", "time-always-night", "weather-always-rain",
                  "moon-huge", "water-mirror", "fog-light", "light-street-bright",
                  "clouds-color-purple", "postfx-cold", "premium" if False else "kill-purple",
                  "kill-strong", "visual-rain-heavy", "visual-puddle-on"],
    },
    {
        "id": "bundle-winter", "name": "❄️ Zima / Święta", "icon": "❄️",
        "desc": "Śnieg, zimne światło, sina mgła i świąteczne chmury.",
        "steps": ["sky-preset-frostpunk", "weather-snow", "sun-cold", "fog-light",
                  "light-cold", "postfx-cold", "clouds-matol-dense",
                  "clouds-color-cyan", "visual-rain-light", "kill-white", "kill-normal"],
    },
    {
        "id": "bundle-bloodmoon", "name": "🌑 Krwawy Księżyc (PVP night)", "icon": "🌑",
        "desc": "Ciemna czerwień, krwawy księżyc, gęsta mgła i czerwony kill effect.",
        "steps": ["sky-preset-bloodmoon", "time-always-night", "moon-red", "fog-horror",
                  "kill-red", "kill-extreme", "kill-blur-strong", "light-street-off",
                  "water-dark", "postfx-contrast", "expl-huge"],
    },
]

BUNDLES_BY_ID: Dict[str, Dict[str, Any]] = {b["id"]: b for b in BUNDLES}
