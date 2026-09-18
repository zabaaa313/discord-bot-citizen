"""
==============================================================================
 KREATOR WWW „STUDIO" — nowoczesny interfejs klikania (ZERO wpisywania kodów)
==============================================================================
 Jedna strona, trzy kolumny, wszystko klikalne:

   ┌───────────┬──────────────────────────────┬──────────────────────┐
   │ ZAKŁADKI  │  SIATKA KAFli (wszystkie     │  TWÓJ BUILD          │
   │ (grupy /  │  opcje danej zakładki naraz) │  grupowany po PLIKU  │
   │  bronie)  │  klik = dodaj / usuń         │  + „Zbuduj paczkę"   │
   └───────────┴──────────────────────────────┴──────────────────────┘

 Co robi sam bot (bez pytania gracza):
   • przy kliknięciu DOBIERA plik docelowy, generator i parametry,
   • pilnuje konfliktów — opcja pisząca do tego samego pliku ZASTĘPUJE
     poprzednią (np. drugi skin tej samej broni, drugie niebo),
   • SCALA opcje komponowalne (krew + kill effect + head effect -> jeden
     `bloodfx.dat`); panel build pokazuje to wprost: „⚡ 3 scalone".

 Stan trzyma serwer (WEB_SESSIONS), więc odświeżenie strony nic nie gubi.
 Interakcje idą przez JSON API, dzięki czemu wybór jest natychmiastowy
 (bez przeładowania strony). Bez JS działa stary, formularzowy fallback.

 Trasy (podpinane w bot.py):
   GET  /create                       — wybór kreatora
   GET  /create/citizen?user=ID       — nowa sesja citizena
   GET  /create/skins?user=ID         — nowa sesja skinów
   GET  /create/<kind>/<token>/page   — strona studio
   GET  /create/<kind>/<token>/{action}/{value}  — fallback bez JS
   POST /create/finish/<token>        — budowa paczki ZIP
   GET  /api/create/<token>/state     — stan (JSON)
   POST /api/create/<token>/toggle    — wybór / odznaczenie
   POST /api/create/<token>/tab       — aktywna zakładka
   POST /api/create/<token>/clear     — wyczyść wybory
==============================================================================
"""

from __future__ import annotations

import html
import json
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence

# ============================================================================
# 1. STAN SESJI WEBOWYCH
# ============================================================================

WEB_SESSIONS: Dict[str, Dict[str, Any]] = {}
WEB_SESSION_TTL = 4 * 60 * 60  # 4 h


def web_session_create(kind: str, user_id: str) -> str:
    """Tworzy sesję kreatora WWW. kind: 'citizen' albo 'skins'."""
    token = uuid.uuid4().hex[:16]
    WEB_SESSIONS[token] = {
        "kind": kind,            # citizen | skins
        "user_id": str(user_id),
        "created": time.time(),
        "updated": time.time(),
        "citizen_ids": [],       # wybrane kroki citizena (id)
        "skin_ids": [],          # wybrane skiny (id)
        "tab": "",               # aktywna zakładka (grupa / broń)
        "weapon": "pistol",      # zgodność ze starymi linkami
    }
    _web_gc()
    return token


def web_session_get(token: str) -> Optional[Dict[str, Any]]:
    sess = WEB_SESSIONS.get(token)
    if sess and time.time() - sess["updated"] < WEB_SESSION_TTL:
        sess["updated"] = time.time()
        return sess
    if sess:
        WEB_SESSIONS.pop(token, None)
    return None


def _web_gc() -> None:
    now = time.time()
    dead = [t for t, s in WEB_SESSIONS.items() if now - s["updated"] > WEB_SESSION_TTL]
    for token in dead:
        WEB_SESSIONS.pop(token, None)


# ============================================================================
# 2. STAN WYBORU — kafle, klucze plików, automatyczne zastępowanie
# ============================================================================

def creator_item(sid: str, tab: str, name: str, desc: str, file: str, img: str,
                 key: str, tags: Optional[Sequence[str]] = None,
                 locked: bool = False, level: int = 0) -> Dict[str, Any]:
    """
    Kafelek kreatora. `key` to KLUCZ PLIKU DOCELOWEGO (np. citizens/.../sggd.xml):
    opcje z tym samym kluczem wzajemnie się zastępują (jedna broń = jeden skin,
    jedno niebo = jeden sggd.xml). Opcje komponowalne mają różne klucze
    (np. `bloodfx.dat` i `bloodfx.dat#kill_style`) i dlatego się SCALAJĄ.
    """
    return {
        "id": sid, "tab": tab, "name": name, "desc": desc,
        "file": file, "img": img, "key": key,
        # `base` = plik docelowy BEZ slotu — po nim grupujemy scalenia w panelu
        # (krew + kill effect + head effect => jedna pozycja „bloodfx.dat”).
        "base": str(key).split("#", 1)[0],
        "tags": list(tags or []), "locked": bool(locked), "level": int(level or 0),
    }


def chosen_ids(sess: Dict[str, Any]) -> List[str]:
    """Lista wybranych id dla tej sesji (citizen albo skiny)."""
    return sess["citizen_ids"] if sess.get("kind") == "citizen" else sess["skin_ids"]


def toggle_item(sess: Dict[str, Any], items: Sequence[Dict[str, Any]],
                item_id: str) -> Dict[str, Any]:
    """
    Wybiera / odznacza kafelek. Bot SAM:
      • blokuje opcje zablokowane rangą,
      • usuwa inne opcje piszące do tego samego pliku („zastąpiło"),
      • raportuje pliki, które po zmianie są scalane z kilku opcji.
    """
    ids = chosen_ids(sess)
    item = next((i for i in items if i["id"] == item_id), None)
    if item is None:
        return {"ok": False, "error": "nieznana opcja", "name": "", "replaced": [],
                "added": False, "merged_files": []}
    if item.get("locked"):
        return {"ok": False, "error": f"wymaga poziomu {item.get('level') or 1}",
                "name": item["name"], "replaced": [], "added": False,
                "merged_files": []}

    if item_id in ids:                      # klik = odznaczenie
        ids.remove(item_id)
        return {"ok": True, "added": False, "name": item["name"],
                "replaced": [], "merged_files": merged_files(items, ids)}

    replaced: List[str] = []
    for other in items:                     # automatyczne zastąpienie
        if other["id"] == item_id or other["id"] not in ids:
            continue
        if other.get("key") == item.get("key"):
            ids.remove(other["id"])
            replaced.append(other["name"])
    ids.append(item_id)
    return {"ok": True, "added": True, "name": item["name"],
            "replaced": replaced, "merged_files": merged_files(items, ids)}


def clear_items(sess: Dict[str, Any]) -> None:
    """Czyści wszystkie wybory tej sesji."""
    chosen_ids(sess).clear()


def _base(item: Dict[str, Any]) -> str:
    """Plik docelowy bez slotu (krew i kill/head dzielą jeden `bloodfx.dat`)."""
    return str(item.get("base") or str(item.get("key", "")).split("#", 1)[0])


def merged_files(items: Sequence[Dict[str, Any]], ids: Sequence[str]) -> List[str]:
    """Pliki, które po tej zmianie są składane z więcej niż jednej opcji."""
    want = set(ids)
    counts: Dict[str, int] = {}
    display: Dict[str, str] = {}
    for item in items:
        if item["id"] not in want:
            continue
        base = _base(item)
        counts[base] = counts.get(base, 0) + 1
        display.setdefault(base, item["file"])
    return [display[b] for b, n in counts.items() if n > 1]


def output_groups(items: Sequence[Dict[str, Any]],
                  chosen: Sequence[str]) -> List[Dict[str, Any]]:
    """
    Wybrane opcje pogrupowane po PLIKU DOCELOWYM (panel „Twój build”).
    Pozycja z kilkoma opcjami = plik, który bot SCALA w całość (np. krew +
    kill effect + head effect -> jeden `effects/bloodfx.dat`).
    """
    want = set(chosen)
    groups: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if item["id"] not in want:
            continue
        base = _base(item)
        grp = groups.setdefault(base, {
            "key": base, "file": item["file"], "items": [],
        })
        grp["items"].append({"id": item["id"], "name": item["name"],
                             "tab": item["tab"], "tags": item.get("tags") or []})
    out = sorted(groups.values(), key=lambda g: g["file"])
    for grp in out:
        grp["merged"] = len(grp["items"]) > 1
    return out


# Zakładka z gotowymi presetami (bundlami) — jedno kliknięcie = cały build.
BUNDLE_TAB = "__bundles"


def bundle_payload(bundles: Sequence[Dict[str, Any]],
                   items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Presety dla studia: kroki → nazwy, liczba plików i podglądy."""
    by_id = {i["id"]: i for i in items}
    out: List[Dict[str, Any]] = []
    for bundle in bundles:
        steps = [s for s in (bundle.get("steps") or []) if s in by_id]
        if not steps:
            continue
        files: List[str] = []
        for sid in steps:
            path = by_id[sid].get("file") or ""
            if path and path not in files:
                files.append(path)
        out.append({
            "id": bundle["id"], "name": bundle.get("name"),
            "icon": bundle.get("icon") or "⚡", "desc": bundle.get("desc") or "",
            "count": len(steps), "files": files, "steps": steps,
            "img": by_id[steps[0]].get("img") or "",
            "names": [by_id[sid].get("name") for sid in steps[:8]],
        })
    return out


def apply_bundle(sess: Dict[str, Any], items: Sequence[Dict[str, Any]],
                 steps: Sequence[str]) -> Dict[str, Any]:
    """
    Włącza CAŁY preset: dodaje jego opcje, a konflikty (ten sam plik docelowy)
    rozwiązuje automatycznie — stare opcje tego pliku wypadają. Bez klikania
    kilkunastu kafli i bez wpisywania czegokolwiek.
    """
    ids = chosen_ids(sess)
    replaced: List[str] = []
    added: List[str] = []
    locked: List[str] = []
    for sid in steps:
        item = next((i for i in items if i["id"] == sid), None)
        if item is None:
            continue
        if item.get("locked"):
            locked.append(str(item.get("name")))
            continue
        for other in items:                       # auto-zastąpienie tego samego pliku
            if other["id"] == sid or other["id"] not in ids:
                continue
            if other.get("key") == item.get("key"):
                ids.remove(other["id"])
                replaced.append(other["name"])
        if sid not in ids:
            ids.append(sid)
            added.append(item["name"])
    return {"ok": True, "added": added, "replaced": replaced, "locked": locked,
            "merged_files": merged_files(items, ids)}


def build_state(kind: str, token: str, sess: Dict[str, Any],
                items: Sequence[Dict[str, Any]],
                bundles: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Kompletny stan dla strony (bootstrap JSON + odpowiedź API)."""
    chosen = chosen_ids(sess)
    want = set(chosen)
    preset_list = bundle_payload(bundles or [], items)
    tabs: List[Dict[str, Any]] = []
    seen: Dict[str, Dict[str, Any]] = {}
    for item in items:
        tab = seen.get(item["tab"])
        if tab is None:
            tab = {"id": item["tab"], "label": tab_label(item["tab"]),
                   "icon": tab_icon(item["tab"]), "total": 0, "chosen": 0}
            seen[item["tab"]] = tab
            tabs.append(tab)
        tab["total"] += 1
        if item["id"] in want:
            tab["chosen"] += 1

    if preset_list:                # presety zawsze pierwsze — start „na gotowe”
        tabs.insert(0, {"id": BUNDLE_TAB, "label": "Gotowe presety", "icon": "⚡",
                        "total": len(preset_list), "chosen": 0})

    active = sess.get("tab") or ""
    if active != BUNDLE_TAB and active not in seen:
        active = tabs[0]["id"] if tabs else ""

    ui_items = [dict(i, chosen=(i["id"] in want),
                     tabIcon=seen[i["tab"]]["icon"] if i["tab"] in seen else "•")
                for i in items]
    outputs = output_groups(items, chosen)
    return {
        "ok": True,
        "token": token,
        "kind": kind,
        "tabs": tabs,
        "items": ui_items,
        "bundles": preset_list,
        "bundleTab": BUNDLE_TAB if preset_list else "",
        "chosen": list(chosen),
        "activeTab": active,
        "outputs": outputs,
        "stats": {
            "chosen": len(chosen),
            "total": len(items),
            "files": len(outputs),
            "merged": sum(1 for g in outputs if g["merged"]),
        },
    }


# ============================================================================
# 3. NARZĘDZIA — etykiety zakładek
# ============================================================================

# Ikony zakładek: dobierane po słowie kluczowym z nazwy grupy
_TAB_ICONS = (
    ("niebo", "🌤"), ("sky", "🌤"), ("skydome", "🌤"),
    ("słońce", "☀️"), ("księżyc", "🌙"), ("sun", "☀️"), ("moon", "🌙"),
    ("grafika", "🎨"), ("postfx", "🎨"), ("kolory", "🎨"),
    ("pogoda", "🌧"), ("deszcz", "🌧"), ("weather", "🌧"), ("śnieg", "❅"),
    ("kombat", "🩸"), ("krew", "🩸"), ("kill", "💀"), ("head", "🎯"),
    ("czas", "⏰"), ("time", "⏰"), ("chmury", "☁️"), ("clouds", "☁️"),
    ("woda", "💧"), ("water", "💧"), ("mgła", "🌫"), ("fog", "🌫"),
    ("światło", "💡"), ("light", "💡"), ("blur", "🎞"), ("dof", "🎞"),
    ("visual", "⚙️"), ("hud", "🖥"), ("wydajność", "🚀"), ("fps", "🚀"),
    ("eksplozje", "💥"), ("ogień", "🔥"), ("fire", "🔥"), ("dym", "💨"),
    ("strzału", "🔫"), ("traces", "🔫"), ("opony", "🛞"), ("drift", "🛞"),
    ("czyściej", "🚫"), ("śladów", "🚫"), ("dodatkowe", "✨"),
)


def tab_icon(tab: str) -> str:
    """Ikona zakładki: motyw grupy (albo 🔫 dla zakładek z broniami)."""
    low = str(tab).lower()
    for keyword, icon in _TAB_ICONS:
        if keyword in low:
            return icon
    return "🔫"


# Skróty, które zostają WIELKIMI literami w etykietach zakładek
_LABEL_ACRONYMS = {"DOF", "FPS", "HUD", "UI", "PVP", "RPF", "3D", "LOD", "SSAO", "FOV"}


def _label_words(text: str) -> List[str]:
    """Słowa do etykiety: bez emoji, numerków i nawiasowych dopisków."""
    words: List[str] = []
    for part in text.split():
        if part.startswith("(") or part.endswith(")"):
            continue                                  # dopiski w nawiasach precz
        if not part[:1].isalnum() or part[:1].isdigit():
            continue                                  # emoji / numerki / spójniki
        words.append(part)
    return words


def _pretty_label(label: str) -> str:
    """Kapitalizacja nagłówka grupy: „SŁOŃCE I KSIĘŻYC” → „Słońce i Księżyc”."""
    parts: List[str] = []
    for word in label.split():
        if word in _LABEL_ACRONYMS:
            parts.append(word)
        else:
            parts.append(word.capitalize() if (word.isalpha() and word.isupper()) else word)
    return " ".join(parts).replace(" I ", " i ")


def tab_label(tab: str) -> str:
    """
    Krótka, czysta nazwa zakładki (bez numerków, emoji i dopisków):
      '1️⃣ NIEBO — skydome i custom nieba'  ->  'Niebo'
      '4️⃣ SŁOŃCE I KSIĘŻYC'                ->  'Słońce i Księżyc'
      '🖥 HUD / UI'                        ->  'HUD / UI'
      '🚫 CZYŚCIEJ (BEZ ŚLADÓW)'           ->  'Czyściej'
      'Pistol Mk II'                       ->  'Pistol Mk II' (bez zmian)
    """
    text = str(tab).strip()
    if "—" not in text and not text[:1].isdigit() and text[:1].isalnum():
        return text                                   # nazwa broni — zostawiamy jak jest
    head = text.split("—", 1)[0] if "—" in text else text
    sep = " / " if " / " in head else " "
    label = sep.join(_label_words(head)).strip()
    return _pretty_label(label) if label else head.strip()


def citizen_groups(steps: Sequence[Dict[str, Any]]) -> List[str]:
    """Grupy citizena w kolejności występowania (zgodność ze starym API)."""
    seen: List[str] = []
    for step in steps:
        group = step.get("group", "")
        if group not in seen:
            seen.append(group)
    return seen


def group_label(group: str) -> str:
    """Skrót grupy do zakładki (zgodność ze starym API)."""
    return f"{tab_icon(group)} {tab_label(group)}"


def _slug(text: str) -> str:
    return str(text).replace("/", "-").replace(" ", "+").strip()


def unslug(text: str) -> str:
    return str(text).replace("+", " ")


def _group_count(steps: Sequence[Dict[str, Any]], group: str, chosen: set) -> str:
    total = sum(1 for s in steps if s.get("group") == group)
    picked = sum(1 for s in steps if s.get("group") == group and s["id"] in chosen)
    return f"{picked}/{total}" if picked else str(total)


# ============================================================================
# 4. DESIGN — jeden arkusz stylów dla całego studia
# ============================================================================

CREATE_CSS = """
:root{
 --bg:#05060b; --bg2:#0a0d16; --panel:rgba(17,21,33,.78); --solid:#111521;
 --elev:#161c2c; --line:rgba(255,255,255,.07); --line2:rgba(255,255,255,.15);
 --txt:#eef2ff; --mut:#93a0c0; --acc:#57f287; --acc2:#22c55e; --brand:#7c5cff;
 --brand2:#38bdf8; --warn:#ffd166; --danger:#ff5c6c; --r:18px; --r2:14px;
 --shadow:0 22px 60px rgba(0,0,0,.6);
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--txt);min-height:100vh;
 font-family:'Segoe UI',system-ui,-apple-system,'Inter',sans-serif;
 -webkit-font-smoothing:antialiased;overflow-x:hidden}
a{color:inherit;text-decoration:none}
code{font-family:'JetBrains Mono',ui-monospace,Consolas,monospace}

/* tło: delikatne orby */
.orbs{position:fixed;inset:0;overflow:hidden;pointer-events:none;z-index:0}
.orbs span{position:absolute;border-radius:50%;filter:blur(90px);opacity:.30}
.orbs span:nth-child(1){width:520px;height:520px;background:#7c5cff;top:-180px;left:-120px}
.orbs span:nth-child(2){width:460px;height:460px;background:#38bdf8;top:20%;right:-160px;opacity:.18}
.orbs span:nth-child(3){width:420px;height:420px;background:#57f287;bottom:-200px;left:35%;opacity:.14}

/* ---------- nagłówek ---------- */
header.top{position:sticky;top:0;z-index:60;display:flex;align-items:center;gap:18px;
 padding:12px 22px;background:rgba(8,10,17,.82);backdrop-filter:blur(14px);
 border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:12px;min-width:0}
.brand .logo{width:42px;height:42px;border-radius:13px;display:grid;place-items:center;
 font-size:21px;background:linear-gradient(135deg,var(--brand),var(--brand2));
 box-shadow:0 10px 26px rgba(124,92,255,.35)}
.brand b{display:block;font-size:15.5px;letter-spacing:.2px}
.brand span{display:block;font-size:12px;color:var(--mut);white-space:nowrap;overflow:hidden;
 text-overflow:ellipsis;max-width:46vw}
.hstats{margin-left:auto;display:flex;gap:10px;align-items:center}
.hchip{background:var(--elev);border:1px solid var(--line);border-radius:99px;
 padding:7px 14px;font-size:12.5px;color:var(--mut);white-space:nowrap}
.hchip b{color:var(--txt)}
.hchip.acc b{color:var(--acc)}

/* ---------- układ ---------- */
.app{position:relative;z-index:1;display:grid;gap:20px;align-items:start;
 grid-template-columns:236px minmax(0,1fr) 330px;padding:20px 22px 90px;max-width:1620px;margin:0 auto}

/* ---------- szyna zakładek ---------- */
.rail{position:sticky;top:82px;display:flex;flex-direction:column;gap:6px}
.railbtn{display:flex;align-items:center;gap:10px;width:100%;text-align:left;
 background:transparent;border:1px solid transparent;border-radius:var(--r2);
 padding:11px 12px;color:var(--mut);font:inherit;font-size:13.5px;cursor:pointer;
 transition:.15s;position:relative}
.railbtn:hover{background:rgba(255,255,255,.04);color:var(--txt)}
.railbtn.on{background:linear-gradient(90deg,rgba(124,92,255,.22),rgba(56,189,248,.06));
 border-color:rgba(124,92,255,.4);color:#fff;font-weight:600}
.railbtn.on:before{content:"";position:absolute;left:-2px;top:20%;bottom:20%;width:3px;
 border-radius:3px;background:linear-gradient(180deg,var(--brand),var(--brand2))}
.railbtn .ric{font-size:16px}
.railbtn .rlb{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.railbtn .rn{font-size:11px;background:rgba(255,255,255,.06);border-radius:99px;
 padding:3px 8px;color:var(--mut)}
.railbtn .rn.sel{background:rgba(87,242,135,.16);color:var(--acc);font-weight:700}

/* ---------- scena ---------- */
.stage{min-width:0}
.pagehead{margin-bottom:14px}
.pagehead h2{font-size:23px;font-weight:800;letter-spacing:.2px}
.pagehead p{color:var(--mut);font-size:13.5px;margin-top:4px}
.toolbar{display:flex;gap:10px;align-items:center;margin-bottom:16px;flex-wrap:wrap}
.search{flex:1;min-width:220px;display:flex;align-items:center;gap:9px;
 background:var(--panel);border:1px solid var(--line);border-radius:99px;padding:10px 16px}
.search:focus-within{border-color:rgba(124,92,255,.55);box-shadow:0 0 0 3px rgba(124,92,255,.12)}
.search input{flex:1;background:transparent;border:0;outline:0;color:var(--txt);
 font:inherit;font-size:13.5px}
.search input::placeholder{color:#5f6c8c}
.search kbd{font-size:10.5px;color:#5f6c8c;border:1px solid var(--line2);
 border-radius:6px;padding:2px 6px}
.chip{background:var(--panel);border:1px solid var(--line);border-radius:99px;
 padding:10px 16px;color:var(--mut);font:inherit;font-size:13px;cursor:pointer;transition:.15s}
.chip:hover{color:var(--txt);border-color:var(--line2)}
.chip.on{background:rgba(87,242,135,.14);border-color:rgba(87,242,135,.45);color:var(--acc);
 font-weight:600}

/* ---------- siatka kafli ---------- */
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(232px,1fr))}
.tile{position:relative;display:flex;flex-direction:column;text-align:left;padding:0;
 background:linear-gradient(165deg,#141a2a,#0d111d);border:1px solid var(--line);
 border-radius:var(--r);overflow:hidden;cursor:pointer;color:var(--txt);font:inherit;
 /* content-visibility: przeglądarka nie liczy layoutu i malowania kafli
    poza ekranem — zakładka ze 106 kaflami przewija się płynnie. */
 content-visibility:auto;contain-intrinsic-size:auto 300px;
 transition:transform .16s ease,border-color .16s ease,box-shadow .16s ease;
 animation:pop .34s cubic-bezier(.2,.9,.3,1) both}
@keyframes pop{from{opacity:0;transform:translateY(10px) scale(.985)}to{opacity:1;transform:none}}
.tile:hover{transform:translateY(-4px);border-color:rgba(124,92,255,.55);
 box-shadow:0 18px 44px rgba(0,0,0,.55)}
.tile.on{border-color:var(--acc);
 box-shadow:0 0 0 1px var(--acc),0 14px 34px rgba(87,242,135,.16)}
.tile.on:hover{border-color:var(--acc)}
.tile.locked{opacity:.55;cursor:not-allowed}
.tile .shot{position:relative;display:block;aspect-ratio:16/10;overflow:hidden;
 background:linear-gradient(135deg,#1b2237,#0f1420)}
.tile .shot img{width:100%;height:100%;object-fit:cover;display:block;
 transition:transform .35s ease;transform-origin:center}
.tile:hover .shot img{transform:scale(1.07)}
.tile .shot.noimg:after{content:"🖼";position:absolute;inset:0;display:grid;
 place-items:center;font-size:30px;opacity:.25}
.tile .shade{position:absolute;inset:0;
 background:linear-gradient(180deg,rgba(5,6,11,0) 40%,rgba(5,6,11,.78))}
.tile .tick{position:absolute;top:10px;right:10px;width:30px;height:30px;border-radius:50%;
 display:grid;place-items:center;font-size:15px;font-weight:800;
 background:rgba(8,10,17,.72);border:1px solid var(--line2);color:#c7d2ee;
 backdrop-filter:blur(6px);transition:.15s}
.tile:hover .tick{background:rgba(124,92,255,.9);color:#fff;border-color:transparent}
.tile.on .tick{background:var(--acc);border-color:transparent;color:#052e14}
.tile .tbadge{position:absolute;top:10px;left:10px;font-size:10.5px;font-weight:700;
 letter-spacing:.4px;text-transform:uppercase;background:rgba(8,10,17,.75);
 border:1px solid var(--line2);border-radius:99px;padding:4px 9px;color:#c7d2ee;
 backdrop-filter:blur(6px);max-width:62%;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.tile .tbody{display:flex;flex-direction:column;gap:6px;padding:13px 15px 15px;flex:1}
.tile b{font-size:14.5px;font-weight:700;line-height:1.3}
.tile .tdesc{color:var(--mut);font-size:12.5px;line-height:1.5;display:-webkit-box;
 -webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;transition:.2s}
.tile:hover .tdesc{-webkit-line-clamp:4}
.tile .tfile{margin-top:auto;padding-top:9px;font-size:11px;color:#7d89a8;
 font-family:ui-monospace,Consolas,monospace;white-space:nowrap;overflow:hidden;
 text-overflow:ellipsis}
.tile.on .tfile{color:rgba(87,242,135,.75)}

/* ---------- gotowe presety (bundle) ---------- */
.sectionhead{margin:0 0 14px;font-size:13px;color:var(--mut);line-height:1.6}
.sectionhead b{color:var(--fg)}
.bcard{position:relative;display:flex;flex-direction:column;gap:12px;padding:18px;
 border:1px solid var(--line);border-radius:var(--r);background:
 linear-gradient(160deg,rgba(124,92,255,.14),rgba(255,255,255,.028));
 box-shadow:var(--shadow);animation:pop .32s both}
.bcard:hover{border-color:rgba(124,92,255,.5);transform:translateY(-3px);transition:.2s}
.bcard .bhead{display:flex;align-items:center;gap:12px}
.bcard .bic{width:46px;height:46px;border-radius:14px;display:grid;place-items:center;
 font-size:24px;background:rgba(255,255,255,.06);border:1px solid var(--line)}
.bcard h3{margin:0;font-size:16px}
.bcard .bmeta{font-size:11.5px;color:#7d89a8;font-weight:600}
.bcard p{margin:0;color:var(--mut);font-size:12.8px;line-height:1.6}
.bcard .chips{display:flex;flex-wrap:wrap;gap:6px}
.bcard .bchip{font-size:11px;padding:3px 9px;border-radius:99px;
 background:rgba(255,255,255,.05);border:1px solid var(--line);color:#c9d3f0}
.bcard .bfiles{font-size:11px;color:#7d89a8;font-family:ui-monospace,Consolas,monospace}
.bcard .apply{margin-top:auto}
.bcard.on .apply{background:rgba(87,242,135,.16);color:#57f287;border-color:rgba(87,242,135,.4)}

/* ---------- panel build ---------- */
.panel{position:sticky;top:82px;background:var(--panel);backdrop-filter:blur(14px);
 border:1px solid var(--line);border-radius:var(--r);padding:16px;display:flex;
 flex-direction:column;gap:12px;max-height:calc(100vh - 116px);box-shadow:var(--shadow)}
.phead{display:flex;align-items:center;gap:10px;font-size:14px}
.phead b{font-weight:700}
.pill{background:linear-gradient(135deg,var(--brand),var(--brand2));border-radius:99px;
 padding:2px 11px;font-size:12px;font-weight:800;color:#fff}
.out{overflow-y:auto;flex:1;display:flex;flex-direction:column;gap:10px;min-height:60px;
 scrollbar-width:thin}
.out::-webkit-scrollbar{width:7px}
.out::-webkit-scrollbar-thumb{background:rgba(255,255,255,.12);border-radius:8px}
.outgrp{background:rgba(255,255,255,.031);border:1px solid var(--line);border-radius:var(--r2);
 padding:10px 11px}
.outhead{display:flex;align-items:center;gap:8px;margin-bottom:7px}
.outhead code{font-size:10.5px;color:var(--brand2);flex:1;overflow:hidden;
 text-overflow:ellipsis;white-space:nowrap}
.merged{font-size:10.5px;font-weight:800;color:#052e14;background:var(--warn);
 border-radius:99px;padding:2px 8px;white-space:nowrap}
.outitem{display:flex;align-items:center;gap:8px;font-size:12.5px;padding:5px 0;
 border-top:1px solid rgba(255,255,255,.05)}
.outitem i{font-style:normal;font-size:13px}
.outitem .rm{margin-left:auto;background:rgba(255,92,108,.13);color:var(--danger);
 border:0;border-radius:8px;width:22px;height:22px;cursor:pointer;font-size:12px;
 display:grid;place-items:center;transition:.15s}
.outitem .rm:hover{background:var(--danger);color:#fff}
.outempty{color:var(--mut);font-size:12.5px;line-height:1.6;padding:12px 4px}
.outempty span{color:#6f7c9c;font-size:11.5px}
.hint{font-size:11px;color:#6f7c9c;line-height:1.6}

/* ---------- przyciski ---------- */
.btn{border:0;border-radius:13px;padding:13px 22px;font:inherit;font-size:14px;
 font-weight:700;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;
 gap:8px;transition:transform .08s,filter .15s,opacity .15s}
.btn:active{transform:scale(.975)}
.btn:disabled{opacity:.42;cursor:not-allowed}
.btn.primary{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#04260f}
.btn.primary:hover:not(:disabled){filter:brightness(1.1)}
.btn.ghost{background:rgba(255,255,255,.05);color:var(--txt);border:1px solid var(--line2)}
.btn.ghost:hover:not(:disabled){background:rgba(255,255,255,.1)}
.btn.warn{background:linear-gradient(135deg,var(--brand),var(--brand2));color:#fff}
.btn.wide{width:100%}
.btn.busy{filter:saturate(.6)}

/* ---------- komunikaty ---------- */
#toasts{position:fixed;right:20px;bottom:22px;z-index:200;display:flex;
 flex-direction:column;gap:9px;max-width:340px}
.toast{background:rgba(17,21,33,.96);border:1px solid var(--line2);border-left:3px solid var(--acc);
 border-radius:12px;padding:11px 14px;font-size:13px;box-shadow:var(--shadow);
 animation:slide .25s ease both}
.toast.warn{border-left-color:var(--warn)}
.toast.err{border-left-color:var(--danger)}
@keyframes slide{from{opacity:0;transform:translateX(30px)}to{opacity:1;transform:none}}

/* ---------- pasek mobilny ---------- */
.mobar{display:none}

/* ---------- strony: start i „gotowe" ---------- */
.wrap{position:relative;z-index:1;max-width:1100px;margin:0 auto;padding:40px 22px 80px}
.hero{text-align:center;padding:52px 20px 34px}
.hero .big{font-size:60px;line-height:1;margin-bottom:16px;
 filter:drop-shadow(0 12px 30px rgba(124,92,255,.45))}
.hero h1{font-size:34px;font-weight:800;letter-spacing:.3px;margin-bottom:12px;
 background:linear-gradient(120deg,#fff,#a9b8ff);-webkit-background-clip:text;
 -webkit-text-fill-color:transparent;background-clip:text}
.hero p{color:var(--mut);font-size:15px;max-width:640px;margin:0 auto 26px;line-height:1.6}
.cards{display:grid;gap:20px;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));margin-top:30px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:22px;padding:26px;
 display:flex;flex-direction:column;gap:14px;transition:.18s;position:relative;overflow:hidden}
.card:hover{transform:translateY(-4px);border-color:rgba(124,92,255,.5);box-shadow:var(--shadow)}
.card .ic{width:54px;height:54px;border-radius:16px;display:grid;place-items:center;
 font-size:26px;background:linear-gradient(135deg,rgba(124,92,255,.3),rgba(56,189,248,.18))}
.card h3{font-size:19px;font-weight:800}
.card p{color:var(--mut);font-size:13.5px;line-height:1.6}
.card ul{list-style:none;display:flex;flex-direction:column;gap:7px;margin:4px 0 8px}
.card li{font-size:13px;color:#c3cde8;display:flex;gap:8px;align-items:center}
.card li:before{content:"✓";color:var(--acc);font-weight:800}
.steps{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
 margin-top:34px}
.step{background:rgba(255,255,255,.03);border:1px solid var(--line);border-radius:16px;padding:18px}
.step b{display:block;font-size:13.5px;margin-bottom:6px}
.step span{color:var(--mut);font-size:12.5px;line-height:1.55}
.done{text-align:center;padding:46px 20px}
.done .big{font-size:64px;margin-bottom:14px}
.done h1{font-size:29px;font-weight:800;margin-bottom:10px}
.done p{color:var(--mut);margin-bottom:24px}
.done .actions{display:flex;gap:12px;justify-content:center;flex-wrap:wrap}
.sumbox{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);
 padding:18px 20px;text-align:left;max-width:660px;margin:0 auto 26px}
.sumbox h4{font-size:12px;text-transform:uppercase;letter-spacing:.12em;color:var(--mut);
 margin-bottom:12px}
.sumbox .row{display:flex;align-items:center;gap:10px;padding:8px 0;
 border-top:1px solid rgba(255,255,255,.05);font-size:13px}
.sumbox .row:first-of-type{border-top:0}
.sumbox .row code{font-size:11px;color:var(--brand2);flex:1;overflow:hidden;
 text-overflow:ellipsis;white-space:nowrap}
.sumbox .row .tags{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.sumbox .tg{background:rgba(124,92,255,.16);border-radius:99px;padding:3px 9px;font-size:11px}
footer{position:relative;z-index:1;text-align:center;color:#5f6c8c;font-size:11.5px;
 padding:22px;opacity:.85}
.empty{grid-column:1/-1;text-align:center;padding:60px 20px;color:var(--mut);
 background:rgba(255,255,255,.02);border:1px dashed var(--line2);border-radius:var(--r)}
.empty .big{font-size:44px;margin-bottom:12px}
.empty b{display:block;font-size:16px;color:var(--txt);margin-bottom:6px}

/* ---------- responsywność ---------- */
@media(max-width:1240px){
 .app{grid-template-columns:200px minmax(0,1fr) 300px}
}
@media(max-width:1080px){
 .app{grid-template-columns:1fr;padding-bottom:110px}
 .rail{position:static;flex-direction:row;overflow-x:auto;gap:8px;padding-bottom:6px;
  scrollbar-width:none}
 .rail::-webkit-scrollbar{display:none}
 .railbtn{width:auto;white-space:nowrap;flex:0 0 auto}
 .railbtn.on:before{left:18%;right:18%;top:auto;bottom:3px;width:auto;height:3px}
 .panel{position:static;max-height:none}
 .mobar{display:flex;position:fixed;left:0;right:0;bottom:0;z-index:70;gap:12px;
  align-items:center;justify-content:space-between;padding:12px 18px;
  background:rgba(8,10,17,.94);backdrop-filter:blur(14px);border-top:1px solid var(--line)}
 .mobar span{font-size:13px;color:var(--mut)}
 .mobar b{color:var(--acc);font-size:15px}
 .hbuild{display:none}
}
@media(max-width:640px){
 .grid{grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
 .brand b{font-size:14px}.brand span{display:none}
 .hero h1{font-size:26px}.hstats{display:none}
 .app{padding:14px 14px 110px;gap:14px}
 #toasts{left:14px;right:14px;bottom:78px;max-width:none}
}
@media(prefers-reduced-motion:reduce){
 *{animation:none!important;transition:none!important;scroll-behavior:auto!important}
}
"""

BASE_SHELL = """<!DOCTYPE html>
<html lang="pl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — FiveM Mod Foundry</title>
<style>{css}</style></head>
<body>
<div class="orbs"><span></span><span></span><span></span></div>
<header class="top">
 <div class="brand"><span class="logo">🏭</span>
  <div><b>FiveM Mod Foundry</b><span>{title}</span></div></div>
 <div class="hstats"><span class="hchip">{chip}</span></div>
</header>
<main>{main}</main>
<footer>Wygenerowano przez bota • paczka ZIP ląduje na Discordzie i tutaj</footer>
</body></html>"""


def _page(title: str, chip: str, main_html: str) -> str:
    """Prosta strona w designie studia (start, „paczka gotowa", błędy)."""
    return BASE_SHELL.format(title=html.escape(title), css=CREATE_CSS,
                             chip=html.escape(chip), main=main_html)


# ============================================================================
# 5. STRONA STUDIO — shell + logika po stronie przeglądarki
# ============================================================================

STUDIO_JS = r"""
(function(){
  var BOOT = window.__BOOT__;
  var TOKEN = BOOT.token;
  var $ = function(s){ return document.querySelector(s); };
  var ESC = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
  function esc(s){ return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){ return ESC[c]; }); }
  function shortFile(f){
    return String(f || '').replace('citizen/common/data/', '').replace(/^mods\//, '');
  }

  var ITEMS = BOOT.items || [];
  var BUNDLES = BOOT.bundles || [];
  var BUN = BOOT.bundleTab || '';
  var BY_ID = {};
  ITEMS.forEach(function(i){ BY_ID[i.id] = i; });
  var S = {
    chosen: new Set(BOOT.chosen || []),
    tab: BOOT.activeTab || (BOOT.tabs[0] ? BOOT.tabs[0].id : ''),
    q: '', only: false
  };

  /* ---------- liczby ---------- */
  function tabStats(){
    var m = {};
    ITEMS.forEach(function(i){
      var t = m[i.tab] || (m[i.tab] = {total:0, sel:0});
      t.total++;
      if (S.chosen.has(i.id)) t.sel++;
    });
    return m;
  }
  /* Panel grupuje po PLIKU DOCELOWYM (`base`, bez slotu) — dlatego krew, kill
     i head effect pokazują się jako JEDNA pozycja „bloodfx.dat: ⚡ 3 scalone”. */
  function currentOutputs(){
    var g = new Map();
    ITEMS.forEach(function(i){
      if (!S.chosen.has(i.id)) return;
      var k = i.base || i.key;
      if (!g.has(k)) g.set(k, {key:k, file:i.file, items:[]});
      g.get(k).items.push(i);
    });
    return Array.from(g.values()).sort(function(a,b){ return a.file.localeCompare(b.file); });
  }

  /* ---------- render: szyna zakładek ---------- */
  function renderRail(){
    var st = tabStats();
    $('#rail').innerHTML = (BOOT.tabs || []).map(function(t){
      var s = st[t.id] || {total:t.total, sel:0};
      return '<button type="button" class="railbtn' + (t.id === S.tab ? ' on' : '') + '"'
        + ' data-tab="' + esc(t.id) + '">'
        + '<span class="ric">' + t.icon + '</span>'
        + '<span class="rlb">' + esc(t.label) + '</span>'
        + '<span class="rn' + (s.sel ? ' sel' : '') + '">' + (s.sel ? s.sel + '/' : '') + s.total + '</span>'
        + '</button>';
    }).join('');
  }

  /* ---------- render: siatka kafli ---------- */
  function tile(i, idx){
    var on = S.chosen.has(i.id);
    var tag = (i.tags && i.tags.length) ? '<span class="tbadge">' + esc(i.tags[0]) + '</span>' : '';
    var lock = i.locked ? '<span class="tbadge">🔒 poziom ' + (i.level||1) + '</span>' : tag;
    return '<button type="button" class="tile' + (on ? ' on' : '') + (i.locked ? ' locked' : '')
      + '" data-id="' + esc(i.id) + '" style="animation-delay:' + Math.min(idx*16, 320) + 'ms"'
      + ' title="' + esc(i.name) + ' — ' + (on ? 'kliknij, aby usunąć' : 'kliknij, aby dodać') + '">'
      + '<span class="shot"><img loading="lazy" decoding="async" width="480" height="270"'
      + ' src="' + esc(i.img) + '" alt="">'
      + '<span class="shade"></span>' + lock
      + '<span class="tick">' + (on ? '✓' : (i.locked ? '🔒' : '+')) + '</span></span>'
      + '<span class="tbody"><b>' + esc(i.name) + '</b>'
      + '<span class="tdesc">' + esc(i.desc) + '</span>'
      + '<span class="tfile">📄 ' + esc(shortFile(i.file)) + '</span></span></button>';
  }

  /* ---------- render: GOTOWE PRESETY (jedno kliknięcie = cały build) ---------- */
  function bundleCard(b, idx){
    var have = (b.steps || []).filter(function(s){ return S.chosen.has(s); }).length;
    var done = have >= b.count && b.count > 0;
    var names = (b.names || []).map(function(n){
      return '<span class="bchip">' + esc(n) + '</span>';
    }).join('');
    return '<article class="bcard' + (done ? ' on' : '') + '"'
      + ' style="animation-delay:' + Math.min(idx*30, 300) + 'ms">'
      + '<div class="bhead"><span class="bic">' + esc(b.icon) + '</span>'
      + '<div><h3>' + esc(b.name) + '</h3>'
      + '<span class="bmeta">' + b.count + ' opcji · ' + b.files.length + ' plików'
      + (done ? ' · ✓ aktywny' : (have ? ' · ' + have + '/' + b.count + ' wybranych' : ''))
      + '</span></div></div>'
      + '<p>' + esc(b.desc) + '</p>'
      + (names ? '<div class="chips">' + names + '</div>' : '')
      + '<div class="bfiles">📦 ' + (b.files || []).map(shortFile).join(' · ') + '</div>'
      + '<button type="button" class="btn primary apply" data-bundle="' + esc(b.id) + '">'
      + (done ? '↻ Zastosuj ponownie' : '⚡ Zastosuj preset jednym klikiem') + '</button>'
      + '</article>';
  }

  function renderBundles(){
    var grid = $('#grid');
    var intro = '<div class="sectionhead">⚡ <b>Gotowe presety</b> — klikasz jeden kafel '
      + 'i bot sam dobiera wszystkie pliki, generatory i zależności '
      + '(niebo, czas, pogoda, krew, kill effect…). Nic nie wpisujesz.</div>';
    grid.innerHTML = intro + BUNDLES.map(bundleCard).join('');
    var bar = $('#toolbar');
    if (bar) bar.style.display = 'none';
  }

  function applyBundle(id){
    if (busy) return;
    var b = BUNDLES.filter(function(x){ return x.id === id; })[0];
    if (!b) return;
    busy = true;
    toast('⏳ Nakładam preset: ' + b.name);
    api('/bundle', {id:id}).then(function(d){
      busy = false;
      if (!d || !d.ok){ toast('⚠️ ' + ((d && d.error) || 'Nie udało się nałożyć presetu'), 'err'); return; }
      applyChosen(new Set(d.chosen || []));
      toast('⚡ Preset „' + b.name + '” nałożony (' + (d.added || []).length + ' opcji)', '');
      (d.replaced || []).slice(0, 4).forEach(function(nm){
        toast('🔄 „' + nm + '” zastąpione — ten sam plik docelowy', 'warn');
      });
      (d.merged_files || []).forEach(function(f){
        toast('⚡ Bot scala plik: ' + shortFile(f));
      });
      (d.locked || []).slice(0, 3).forEach(function(nm){
        toast('🔒 „' + nm + '” wymaga wyższej rangi — pominięte', 'warn');
      });
    }).catch(function(){
      busy = false;
      toast('⚠️ Brak połączenia z botem — spróbuj ponownie', 'err');
    });
  }

  function renderGrid(){
    var bar = $('#toolbar');
    if (bar) bar.style.display = (S.tab === BUN) ? 'none' : '';
    if (S.tab === BUN){ renderBundles(); return; }
    var q = S.q.trim().toLowerCase();
    var list = ITEMS.filter(function(i){ return i.tab === S.tab; });
    if (S.only) list = list.filter(function(i){ return S.chosen.has(i.id); });
    if (q) list = list.filter(function(i){
      return (i.name + ' ' + i.desc + ' ' + i.file).toLowerCase().indexOf(q) >= 0;
    });
    var grid = $('#grid');
    if (!list.length){
      grid.innerHTML = '<div class="empty"><div class="big">🔍</div><b>Nic tu nie ma</b>'
        + '<span>' + (S.only ? 'Nie wybrałeś jeszcze nic w tej zakładce.'
        : (q ? 'Brak wyników dla „' + esc(S.q) + '”.' : 'Ta zakładka jest pusta.')) + '</span></div>';
      return;
    }
    grid.innerHTML = list.map(tile).join('');
    grid.querySelectorAll('img').forEach(function(img){
      img.addEventListener('error', function(){
        img.style.display = 'none';
        img.parentElement.classList.add('noimg');
      });
    });
  }

  /* ---------- render: panel „Twój build" ---------- */
  function renderPanel(){
    var outs = currentOutputs(), n = S.chosen.size;
    $('#pcount').textContent = n;
    if ($('#mcount')) $('#mcount').textContent = n;
    if ($('#statfiles')) $('#statfiles').textContent = outs.length;
    if ($('#hchosen')) $('#hchosen').textContent = n;

    if (!outs.length){
      $('#out').innerHTML = '<div class="outempty">🫙 Kliknij kafelek, a bot sam dobierze pliki,'
        + ' generator i zależności.<br><span>Wybrane pliki pokażą się tutaj — pogrupowane po pliku docelowym.</span></div>';
    } else {
      $('#out').innerHTML = outs.map(function(g){
        return '<div class="outgrp"><div class="outhead"><code>' + esc(shortFile(g.file)) + '</code>'
          + (g.items.length > 1 ? '<span class="merged">⚡ ' + g.items.length + ' scalone</span>' : '')
          + '</div>' + g.items.map(function(it){
            return '<span class="outitem"><i>' + ((BY_ID[it.id] && BY_ID[it.id].tabIcon) || '•') + '</i>'
              + esc(it.name)
              + '<button type="button" class="rm" data-rm="' + esc(it.id) + '" title="Usuń">✕</button></span>';
          }).join('') + '</div>';
      }).join('');
    }
    var build = $('#build');
    if (build) build.disabled = !n;
    var clr = $('#clear');
    if (clr) clr.disabled = !n;
    var mb = $('#mbuild');
    if (mb) mb.disabled = !n;
  }

  function render(){ renderRail(); renderGrid(); renderPanel(); }

  /* ---------- szybkie odświeżenie: tylko zmienione kafle ----------
     Kliknięcie NIE odbudowuje już całej siatki (przy 106 kaflach to było
     odtwarzanie 106 obrazków i przeliczanie layoutu). Zmieniamy tylko te kafle,
     których dotyczy zmiana — klik jest natychmiastowy. */
  function changedIds(before, after){
    var out = [];
    before.forEach(function(id){ if (!after.has(id)) out.push(id); });
    after.forEach(function(id){ if (!before.has(id)) out.push(id); });
    return out;
  }

  function paintTiles(ids){
    if (!ids.length) return;
    var want = {};
    ids.forEach(function(id){ want[id] = true; });
    var nodes = document.querySelectorAll('#grid .tile');
    for (var i = 0; i < nodes.length; i++){
      var el = nodes[i];
      if (!want[el.getAttribute('data-id')]) continue;
      var on = S.chosen.has(el.getAttribute('data-id'));
      el.classList.toggle('on', on);
      var tick = el.querySelector('.tick');
      if (tick) tick.textContent = on ? '✓' : (el.classList.contains('locked') ? '🔒' : '+');
    }
  }

  function applyChosen(next){
    var before = S.chosen;
    S.chosen = next;
    if (S.only){          // filtr „tylko wybrane”: trzeba przeliczyć listę kafli
      renderGrid(); renderRail(); renderPanel(); return;
    }
    paintTiles(changedIds(before, next));
    renderRail(); renderPanel();
  }

  /* ---------- toasty ---------- */
  function toast(msg, kind){
    var box = $('#toasts');
    var el = document.createElement('div');
    el.className = 'toast' + (kind ? ' ' + kind : '');
    el.innerHTML = esc(msg);
    box.appendChild(el);
    setTimeout(function(){
      el.style.transition = 'opacity .3s, transform .3s';
      el.style.opacity = '0';
      el.style.transform = 'translateX(24px)';
      setTimeout(function(){ el.remove(); }, 320);
    }, 3400);
  }

  /* ---------- komunikacja z botem ---------- */
  function api(path, body){
    return fetch('/api/create/' + TOKEN + path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body || {})
    }).then(function(r){ return r.json(); });
  }

  var busy = false;   // tylko dla ciężkich akcji (preset), nie dla zwykłych klików
  var clickSeq = 0;   // kolejność klików: wolno klikać szybko, stare odpowiedzi ignorujemy
  /* Klik: zaznaczenie widać NATYCHMIAST (bez czekania na serwer), a bot zapisuje
     wybór w tle. Gdy bot zmieni coś jeszcze (np. zastąpi opcję tego samego pliku),
     dosyła pełny stan i podświetlamy tylko zmienione kafle — bez odbudowy siatki. */
  function toggle(id){
    var it = BY_ID[id];
    if (!it) return;
    if (it.locked){
      toast('🔒 „' + it.name + '” odblokujesz na poziomie ' + (it.level||1)
            + ' — buduj paczki i zbieraj XP', 'warn');
      return;
    }
    var wasOn = S.chosen.has(id);
    var next = new Set(S.chosen);
    if (wasOn) next.delete(id); else next.add(id);
    applyChosen(next);
    var mine = ++clickSeq;
    api('/toggle', {id:id}).then(function(d){
      if (mine !== clickSeq) return;          // odpowiedź starszego kliku — nie cofamy nowszych
      if (!d || !d.ok){ toast('⚠️ ' + ((d && d.error) || 'Nie udało się zapisać'), 'err');
        var back = new Set(S.chosen);
        if (wasOn) back.add(id); else back.delete(id);
        applyChosen(back); return; }
      applyChosen(new Set(d.chosen || []));
      toast((d.added ? '✅ Dodano: ' : '➖ Usunięto: ') + d.name, d.added ? '' : '');
      (d.replaced || []).forEach(function(nm){
        toast('🔄 „' + nm + '” zastąpione — ten sam plik docelowy', 'warn');
      });
      (d.merged_files || []).forEach(function(f){
        toast('⚡ Bot scala plik: ' + shortFile(f));
      });
    }).catch(function(){
      if (mine !== clickSeq) return;
      toast('⚠️ Brak połączenia z botem — spróbuj ponownie', 'err');
      var back = new Set(S.chosen);
      if (wasOn) back.add(id); else back.delete(id);
      applyChosen(back);
    });
  }

  /* ---------- zdarzenia ---------- */
  document.addEventListener('click', function(e){
    var bo = e.target.closest('.bcard .apply') || e.target.closest('[data-bundle]');
    if (bo){ e.stopPropagation(); applyBundle(bo.dataset.bundle); return; }
    var tile = e.target.closest('.tile');
    if (tile){ toggle(tile.dataset.id); return; }
    var rm = e.target.closest('.rm');
    if (rm){ e.stopPropagation(); toggle(rm.dataset.rm); return; }
    var rb = e.target.closest('.railbtn');
    if (rb){
      S.tab = rb.dataset.tab;
      renderRail(); renderGrid();
      api('/tab', {tab:S.tab}).catch(function(){});
      window.scrollTo({top:0, behavior:'smooth'});
    }
  });

  document.addEventListener('keydown', function(e){
    if (e.key === 'Escape'){
      var box = $('#q');
      if (box && box.value){ box.value = ''; S.q = ''; renderGrid(); box.blur(); }
    }
  });

  document.addEventListener('DOMContentLoaded', function(){
    var q = $('#q');
    var qTimer = null;
    if (q) q.addEventListener('input', function(){
      S.q = q.value;
      if (qTimer) clearTimeout(qTimer);            // filtr nie liczy się przy każdym znaku
      qTimer = setTimeout(renderGrid, 120);
    });
    var only = $('#only');
    if (only) only.addEventListener('click', function(){
      S.only = !S.only;
      only.classList.toggle('on', S.only);
      renderGrid();
    });
    var build = $('#build-form');
    if (build) build.addEventListener('submit', function(){
      var b = $('#build');
      if (b){ b.textContent = '⏳ Buduję paczkę…'; b.classList.add('busy'); b.disabled = true; }
    });
    var mb = $('#mbuild');
    if (mb) mb.addEventListener('click', function(){
      var f = $('#build-form');
      if (f) f.submit();
    });
    var clr = $('#clear');
    if (clr) clr.addEventListener('click', function(){
      if (!confirm('Usunąć wszystkie wybory?')) return;
      api('/clear', {}).then(function(){
        applyChosen(new Set());
        toast('🗑 Wyczyszczono wybory');
      });
    });
    render();
  });
})();
"""

_STUDIO_HTML = """<!DOCTYPE html>
<html lang="pl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%%TITLE%% — FiveM Mod Foundry</title>
<style>%%CSS%%</style></head>
<body>
<div class="orbs"><span></span><span></span><span></span></div>
<header class="top">
 <div class="brand"><span class="logo">%%LOGO%%</span>
  <div><b>%%TITLE%%</b><span>%%SUBTITLE%%</span></div></div>
 <div class="hstats">
   <span class="hchip">🗂 <b id="statfiles">0</b> plików</span>
   <span class="hchip acc">🎯 <b id="hchosen">0</b> wybranych</span>
 </div>
 <form method="post" action="/create/finish/%%TOKEN%%" class="hbuild">
   <button class="btn primary" type="submit">📦 Zbuduj paczkę</button>
 </form>
</header>

<div class="app">
 <aside class="rail" id="rail" aria-label="Zakładki"></aside>

 <main class="stage">
  <div class="pagehead">
   <h2>%%HEADLINE%%</h2>
   <p>%%SUBTITLE%%</p>
  </div>
  <div class="toolbar" id="toolbar">
   <label class="search"><span>🔍</span>
    <input id="q" placeholder="Filtruj opcje w tej zakładce…" autocomplete="off">
    <kbd>esc</kbd></label>
   <button type="button" class="chip" id="only">★ Tylko wybrane</button>
  </div>
  <div class="grid" id="grid"></div>
 </main>

 <aside class="panel">
  <div class="phead"><b>🧩 Twój build</b><span class="pill" id="pcount">0</span></div>
  <div class="out" id="out"></div>
  <form method="post" action="/create/finish/%%TOKEN%%" id="build-form">
   <button class="btn primary wide" id="build" type="submit">📦 Zbuduj paczkę ZIP</button>
  </form>
  <button class="btn ghost wide" id="clear" type="button">🗑 Wyczyść wszystko</button>
  <p class="hint">Klik na kafelek = dodaj / usuń. Nic nie wpisujesz: bot sam wybiera pliki,
     scala krew z kill/head effectem i pilnuje konfliktów (nowa opcja tego samego pliku
     zastępuje poprzednią).</p>
 </aside>
</div>

<div class="mobar">
 <span>🎯 <b id="mcount">0</b> wybranych</span>
 <button class="btn primary" id="mbuild" type="button">📦 Buduj paczkę</button>
</div>
<div id="toasts"></div>
<script>window.__BOOT__ = %%BOOTJSON%%;</script>
<script>%%JS%%</script>
</body></html>"""


def render_creator_page(kind: str, token: str, sess: Dict[str, Any],
                        items: Sequence[Dict[str, Any]], *,
                        title: str = "", subtitle: str = "",
                        logo: str = "🏭", headline: str = "",
                        bundles: Optional[Sequence[Dict[str, Any]]] = None) -> str:
    """Strona studio: zakładki + siatka wszystkich opcji + panel build."""
    state = build_state(kind, token, sess, items, bundles)
    boot = json.dumps(state, ensure_ascii=False).replace("</", "<\\/")
    page = _STUDIO_HTML
    page = page.replace("%%CSS%%", CREATE_CSS)
    page = page.replace("%%JS%%", STUDIO_JS)
    page = page.replace("%%BOOTJSON%%", boot)
    page = page.replace("%%TITLE%%", html.escape(title or "Kreator"))
    page = page.replace("%%SUBTITLE%%", html.escape(subtitle))
    page = page.replace("%%HEADLINE%%", html.escape(headline or title or "Kreator"))
    page = page.replace("%%LOGO%%", logo)
    page = page.replace("%%TOKEN%%", html.escape(token))
    return page


def _citizen_bundles() -> List[Dict[str, Any]]:
    """Presety citizena (z citizen_mods) — bezpiecznie, gdy moduł nie istnieje."""
    try:
        import citizen_mods  # lokalny import: brak cyklicznych zależności
        return list(citizen_mods.BUNDLES)
    except Exception:  # noqa: BLE001 — brak modułu nie może ubić kreatora
        return []


def render_citizen_page(token: str, sess: Dict[str, Any],
                        items: Sequence[Dict[str, Any]]) -> str:
    """Kreator citizena — presety + grupy jako zakładki, wszystkie opcje naraz."""
    return render_creator_page(
        "citizen", token, sess, items,
        title="Citizen Studio", logo="🌤",
        headline="Kreator Citizena",
        subtitle="Niebo, czas, pogoda, krew, traces i kombat — klikasz kafle, "
                 "bot sam dobiera pliki i scala efekty.",
        bundles=_citizen_bundles())


def render_skins_page(token: str, sess: Dict[str, Any],
                      items: Sequence[Dict[str, Any]]) -> str:
    """Kreator skinów — zakładka per broń, siatka wszystkich skinów."""
    return render_creator_page(
        "skins", token, sess, items,
        title="Skin Studio", logo="🔫",
        headline="Kreator Skinów broni",
        subtitle="Pistolety i ich wykończenia. Na jedną broń wchodzi jeden skin — "
                 "wybranie kolejnego automatycznie zastępuje poprzedni.")


# ============================================================================
# 6. STRONA STARTOWA + EKRAN „PACZKA GOTOWA"
# ============================================================================

def render_home_page(user_id: str) -> str:
    main = """
<div class="wrap">
 <div class="hero">
  <div class="big">🏭</div>
  <h1>FiveM Mod Foundry Studio</h1>
  <p>Kompletny kreator paczek dla FiveM: zbuduj własnego citizena (niebo, słońce,
     grafika, pogoda, krew, kill i head effect) albo dobierz skiny do pistoletów.
     Wszystko klikasz — nic nie wpisujesz.</p>
  <div class="cards">
   <a class="card" href="/create/citizen?user=%USER%">
    <div class="ic">🌤</div>
    <h3>Citizen Studio</h3>
    <p>Pełny zestaw plików citizena — te same pliki, zmienione wartości.</p>
    <ul>
     <li>100+ custom nieb z prawdziwym podglądem</li>
     <li>Słońce, księżyc, grafika i pogoda</li>
     <li>Krew, kill effect i head effect (scalane w jeden plik)</li>
    </ul>
    <span class="btn primary wide">Otwórz Citizen Studio</span>
   </a>
   <a class="card" href="/create/skins?user=%USER%">
    <div class="ic">🔫</div>
    <h3>Skin Studio</h3>
    <p>Wykończenia dla pistoletów — jeden skin na broń, wybierasz z galerii.</p>
    <ul>
     <li>5 broni: Pistol, Mk II, Vintage, SNS i SNS Mk II</li>
     <li>Po 25 wykończeń na broń</li>
     <li>Podgląd broni w kolorach skina</li>
    </ul>
    <span class="btn warn wide">Otwórz Skin Studio</span>
   </a>
  </div>
  <div class="steps">
   <div class="step"><b>1. Klikasz kafle</b>
    <span>Każda opcja ma podgląd 1:1 z gry i plik docelowy, który dostaniesz w paczce.</span></div>
   <div class="step"><b>2. Bot dobiera zależności</b>
    <span>Konflikty rozwiązują się same — nowa opcja tego samego pliku zastępuje starą,
        a krew + kill + head effect ladują w jednym pliku.</span></div>
   <div class="step"><b>3. Budujesz paczkę</b>
    <span>ZIP z plikami, HASHES.txt i instrukcją — link dostajesz na stronie i na Discordzie.</span></div>
  </div>
 </div>
</div>"""
    return _page("Wybierz kreator", "start", main.replace("%USER%", html.escape(user_id)))


def render_pack_done(token: str, download_url: str, kind: str,
                     count: int, size_mb: float,
                     outputs: Optional[Sequence[Dict[str, Any]]] = None,
                     merged: int = 0) -> str:
    rows = ""
    for grp in (outputs or []):
        names = "".join(f'<span class="tg">{html.escape(str(i["name"]))}</span>'
                        for i in grp.get("items", []))
        badge = ('<span class="merged">⚡ scalone</span>' if grp.get("merged") else "")
        rows += (f'<div class="row"><code>{html.escape(_dfile(grp.get("file", "")))}</code>'
                 f'{badge}<span class="tags">{names}</span></div>')
    summary = ""
    if rows:
        title = ("⚡ Tak bot dobrał i scalił pliki" if merged else
                 "📦 Pliki, które znajdą się w paczce")
        summary = f'<div class="sumbox"><h4>{title}</h4>{rows}</div>'
    main = f"""
<div class="wrap">
 <div class="done">
  <div class="big">✅</div>
  <h1>Paczka gotowa!</h1>
  <p>{count} plików • {size_mb:.1f} MB • hasze SHA-256 w HASHES.txt</p>
  <div class="actions">
   <a class="btn primary" href="{html.escape(download_url)}">⬇️ Pobierz paczkę ZIP</a>
   <a class="btn ghost" href="/create/{html.escape(kind)}">🏗️ Buduj kolejną</a>
   <a class="btn ghost" href="/create">🏠 Wybór kreatora</a>
  </div>
 </div>
 {summary}
</div>"""
    return _page("Paczka gotowa", f"{count} plików", main)


def _dfile(path: str) -> str:
    """Krótka ścieżka pliku do podsumowania."""
    return str(path).replace("citizen/common/data/", "").replace("mods/", "").replace("#", " → ")
