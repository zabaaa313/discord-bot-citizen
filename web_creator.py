"""
==============================================================================
 KREATOR WWW — zakładki z siatkami opcji (citizen + skiny broni)
==============================================================================
 Strona kreatora (wersja "galeria"):
   /create/citizen?user=ID   — kreator citizena: ZAKŁADKI (Niebo, Słońce…),
                               w każdej zakładce SIATKA wszystkich opcji —
                               klik na kartę = wybór/odznaczenie. Bez pick/skip.
   /create/skins?user=ID     — kreator skinów: zakładka per broń, siatka skinów.

 Panel po prawej (przyklejony) pokazuje aktualne wybory + przycisk
 "Zbuduj paczkę" (POST /create/finish/{token}).
 Stan wyboru po stronie serwera (WEB_SESSIONS) — odświeżenie nic nie gubi.
==============================================================================
"""

from __future__ import annotations

import html
import time
import uuid
from typing import Any, Dict, List, Optional

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
        "weapon": "pistol",      # aktualna broń w kreatorze skinów
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
# 2. DESIGN — wspólny CSS (ciemny motyw, siatka kart, panel wyborów)
# ============================================================================

CREATE_CSS = """
:root{--bg:#0b0d13;--card:#141826;--card2:#1a2033;--line:#2a3350;--txt:#e8ecf7;
--muted:#93a0bd;--acc:#57f287;--acc2:#5865f2;--warn:#fee75c;--danger:#ed4245;--gold:#ffd166}
*{box-sizing:border-box;margin:0;padding:0}
body{background:radial-gradient(1200px 700px at 70% -10%,#1a2340 0%,var(--bg) 60%);
color:var(--txt);font-family:'Segoe UI',system-ui,-apple-system,sans-serif;min-height:100vh;
display:flex;flex-direction:column;align-items:center}
header{width:100%;padding:18px 28px;display:flex;align-items:center;gap:14px;
background:rgba(20,24,38,.85);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);
position:sticky;top:0;z-index:50}
header .logo{width:38px;height:38px;border-radius:10px;background:linear-gradient(135deg,var(--acc2),#9b59b6);
display:grid;place-items:center;font-size:20px}
header h1{font-size:17px;font-weight:600}
header .step-chip{margin-left:auto;background:var(--card2);border:1px solid var(--line);
padding:6px 14px;border-radius:99px;font-size:13px;color:var(--muted)}
main{width:100%;max-width:1280px;padding:24px 20px 80px;flex:1;display:flex;gap:26px;
align-items:flex-start}
.content{flex:1;min-width:0}
.layout{display:flex;gap:26px;align-items:flex-start}
.layout .content{flex:1;min-width:0}

/* --- zakładki grup --- */
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:22px;position:sticky;top:74px;
background:rgba(11,13,19,.92);backdrop-filter:blur(6px);padding:10px 4px;z-index:40;
border-radius:14px}
.tabs a{padding:10px 18px;border-radius:99px;font-size:13.5px;font-weight:600;text-decoration:none;
background:var(--card2);color:var(--muted);border:1px solid var(--line);transition:.15s}
.tabs a:hover{color:var(--txt);filter:brightness(1.15)}
.tabs a.active{background:linear-gradient(135deg,var(--acc2),#7b5cf0);color:#fff;border-color:var(--acc2);
box-shadow:0 6px 20px rgba(88,101,242,.35)}
.tabs a .n{opacity:.75;font-weight:400;margin-left:6px;font-size:12px}

/* --- siatka opcji --- */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px}
.tile{background:var(--card);border:2px solid var(--line);border-radius:16px;overflow:hidden;
cursor:pointer;text-decoration:none;color:var(--txt);display:flex;flex-direction:column;
transition:transform .12s,border-color .12s,box-shadow .12s;position:relative}
.tile:hover{transform:translateY(-3px);border-color:var(--acc2);
box-shadow:0 14px 34px rgba(0,0,0,.5)}
.tile.chosen{border-color:var(--acc);box-shadow:0 0 0 3px rgba(87,242,135,.18)}
.tile .imgwrap{position:relative;aspect-ratio:16/10;overflow:hidden;background:var(--card2)}
.tile img{width:100%;height:100%;object-fit:cover;display:block}
.tile .badge{position:absolute;top:10px;right:10px;background:var(--acc);color:#08280f;
font-size:11px;font-weight:800;padding:4px 10px;border-radius:99px;display:none}
.tile.chosen .badge{display:block}
.tile .body{padding:14px 16px 16px;display:flex;flex-direction:column;gap:6px;flex:1}
.tile h3{font-size:15.5px;font-weight:700;line-height:1.3}
.tile p{color:var(--muted);font-size:12.5px;line-height:1.5;
display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.tile .file{font-size:11px;color:var(--muted);opacity:.8;margin-top:auto;padding-top:8px}

/* --- panel wyborów (sidebar) --- */
aside{width:300px;flex-shrink:0;position:sticky;top:90px;background:var(--card);
border:1px solid var(--line);border-radius:16px;padding:18px 18px 20px;max-height:calc(100vh - 120px);
display:flex;flex-direction:column}
aside h3{font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.12em;
margin-bottom:12px}
aside .count{background:var(--acc2);color:#fff;font-weight:800;border-radius:99px;
padding:2px 10px;font-size:12px;margin-left:8px}
.chosen-list{overflow-y:auto;flex:1;margin:0 0 14px}
.chosen-list .grp{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;
margin:12px 0 6px}
.chosen-list .item{display:flex;justify-content:space-between;align-items:center;gap:8px;
padding:7px 0;border-bottom:1px solid var(--line);font-size:13.5px}
.chosen-list .item:last-child{border-bottom:0}
.chosen-list .item a{color:var(--danger);text-decoration:none;font-size:11px;white-space:nowrap;
padding:3px 8px;border-radius:8px;background:rgba(237,66,69,.12)}
.chosen-list .item a:hover{background:rgba(237,66,69,.25)}
.chosen-list .empty{color:var(--muted);font-size:13px;font-style:italic;padding:8px 0}
aside .btn{width:100%;justify-content:center}
aside .hint{font-size:11.5px;color:var(--muted);margin-top:10px;text-align:center}

/* --- przyciski --- */
button,.btn{cursor:pointer;border:0;border-radius:12px;padding:14px 26px;font-size:15px;
font-weight:600;font-family:inherit;text-decoration:none;display:inline-flex;
align-items:center;gap:8px;transition:transform .08s,filter .15s}
button:active{transform:scale(.97)}
.btn-primary{background:linear-gradient(135deg,var(--acc),#3ecf70);color:#08280f}
.btn-ghost{background:var(--card2);color:var(--txt);border:1px solid var(--line)}
.btn-warn{background:linear-gradient(135deg,var(--gold),#e6b73c);color:#332604}
.btn-danger{background:linear-gradient(135deg,var(--danger),#c93a3d);color:#fff}
.btn-danger{background:linear-gradient(135deg,var(--danger),#c93a3d);color:#fff}
button:hover,.btn:hover{filter:brightness(1.12)}

/* --- strony "gotowe" --- */
.done-panel{text-align:center;padding:50px 20px;width:100%}
.done-panel .big{font-size:64px;margin-bottom:18px}
.done-panel h2{font-size:30px;margin-bottom:12px}
.done-panel p{color:var(--muted);margin-bottom:28px}
.summary{background:var(--card);border:1px solid var(--line);border-radius:16px;
padding:20px 24px;text-align:left;max-width:640px;margin:0 auto 30px}
.summary h3{font-size:14px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;
margin-bottom:14px}
.summary ul{list-style:none}
.summary li{padding:9px 0;border-bottom:1px solid var(--line);font-size:14px;
display:flex;justify-content:space-between;gap:14px}
.summary li:last-child{border-bottom:0}
.summary li span{color:var(--muted)}

footer{color:var(--muted);font-size:12px;padding:20px;text-align:center;opacity:.7;width:100%}
@media(max-width:1000px){
 main{flex-direction:column}aside{width:100%;position:static;max-height:none}
 .layout{flex-direction:column}}
@media(max-width:640px){.grid{grid-template-columns:repeat(auto-fill,minmax(160px,1fr))}
 header h1{font-size:14px}}
"""

BASE_SHELL = """<!DOCTYPE html>
<html lang="pl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — FiveM Mod Foundry</title>
<style>{css}</style></head>
<body>
<header><div class="logo">🔫</div><h1>FiveM Mod Foundry — {title}</h1>
<div class="step-chip">{chip}</div></header>
<main>{main}</main>
<footer>Wygenerowano przez bota • paczka ZIP ląduje na Discordzie i tutaj</footer>
</body></html>"""


def _page(title: str, chip: str, main_html: str) -> str:
    return BASE_SHELL.format(title=html.escape(title), css=CREATE_CSS,
                             chip=chip, main=main_html)


# ============================================================================
# 3. POMOCNICZE — grupy citizena w kolejności zakładek
# ============================================================================

def citizen_groups(steps: List[Dict[str, Any]]) -> List[str]:
    """Lista grup citizena w kolejności występowania (dla zakładek)."""
    seen: List[str] = []
    for step in steps:
        g = step.get("group", "")
        if g not in seen:
            seen.append(g)
    return seen


def group_label(group: str) -> str:
    """Skrót grupy do zakładki (po emoji i myślniku)."""
    text = group.split("—", 1)[-1].strip()
    emoji = group.split(" ")[0]
    return f"{emoji} {text}"


# ============================================================================
# 4. KREATOR CITIZENA — zakładki + siatka opcji (bez pick/skip)
# ============================================================================

def render_citizen_page(token: str, sess: Dict[str, Any], steps: List[Dict[str, Any]],
                        image_url_for, group: str = "", msg: str = "") -> str:
    """
    Wszystkie opcje danej zakładki na jednym ekranie (siatka kart).
    Klik na kartę = wybór (albo zmiana/odznaczenie). Panel po prawej pokazuje wybory.
    """
    groups = citizen_groups(steps)
    active = group if group in groups else (groups[0] if groups else "")
    chosen = set(sess["citizen_ids"])

    tabs = "".join(
        f'<a class="{"active" if g == active else ""}" '
        f'href="/create/citizen/{token}/tab/{_slug(g)}">'
        f'{html.escape(group_label(g))}<span class="n">{_group_count(steps, g, chosen)}</span></a>'
        for g in groups)

    cards = "".join(_tile(step, image_url_for(step), step["id"] in chosen,
                          f"/create/citizen/{token}/toggle/{html.escape(step['id'])}")
                    for step in steps if step.get("group") == active)

    sidebar = _sidebar(token, sess, "citizen")
    main = f"""
<div class="layout">
 <div class="content">
  <div class="tabs">{tabs}</div>
  <div class="grid">{cards}</div>
 </div>
 {sidebar}
</div>
<div class="choice-banner{' show' if msg else ''}" style="display:{'block' if msg else 'none'};
margin:18px 0;padding:12px 18px;border-radius:12px;background:rgba(87,242,135,.1);
border:1px solid rgba(87,242,135,.3);color:var(--acc)">{html.escape(msg)}</div>"""
    chip = f"wybrano {len(chosen)} opcji"
    return _page("Kreator Citizena", chip, main)


# ============================================================================
# 5. KREATOR SKINÓW — zakładka per broń, siatka skinów
# ============================================================================

def render_skins_page(token: str, sess: Dict[str, Any], weapons: List[Dict[str, Any]],
                      image_url_for, msg: str = "") -> str:
    """Siatka wszystkich skinów wybranej broni — klik = wybór/odznaczenie."""
    weapon = next((w for w in weapons if w["id"] == sess["weapon"]), weapons[0])
    chosen = set(sess["skin_ids"])
    total = sum(len(w["skins"]) for w in weapons)

    tabs = "".join(
        f'<a class="{"active" if w["id"] == weapon["id"] else ""}" '
        f'href="/create/skins/{token}/weapon/{w["id"]}">{html.escape(w["name"])}'
        f'<span class="n">{len(w["skins"])}</span></a>'
        for w in weapons)

    cards = "".join(
        _tile({**skin, "group": weapon["name"]}, image_url_for(weapon, skin),
              skin["id"] in chosen, f"/create/skins/{token}/toggle/{html.escape(skin['id'])}")
        for skin in weapon["skins"])

    sidebar = _sidebar(token, sess, "skins", weapons=weapons)
    main = f"""
<div class="layout">
 <div class="content">
  <div class="tabs">{tabs}</div>
  <div class="grid">{cards}</div>
 </div>
 {sidebar}
</div>
<div class="choice-banner{' show' if msg else ''}" style="display:{'block' if msg else 'none'};
margin:18px 0;padding:12px 18px;border-radius:12px;background:rgba(87,242,135,.1);
border:1px solid rgba(87,242,135,.3);color:var(--acc)">{html.escape(msg)}</div>"""
    chip = f"{weapon['name']} • wybrano {len(chosen)}/{total} skinów"
    return _page("Kreator Skinów", chip, main)


# ============================================================================
# 6. KARTA OPCJI + PANEL WYBORÓW
# ============================================================================

def _tile(step: Dict[str, Any], image_url: str, chosen: bool, href: str) -> str:
    """Jedna karta opcji w siatce (klik = toggle)."""
    name = html.escape(str(step.get("name", "")))
    desc = html.escape(str(step.get("description", "")))
    group = html.escape(str(step.get("group", "")).split("—", 1)[-1].strip())
    file = html.escape(str(step.get("gen_file") or step.get("file_name") or ""))
    return f"""
<a class="tile{' chosen' if chosen else ''}" href="{href}" title="{name} — kliknij, aby {'odznaczyć' if chosen else 'wybrać'}">
  <div class="imgwrap"><img loading="lazy" src="{html.escape(image_url)}" alt="{name}">
    <span class="badge">✓ WYBRANE</span></div>
  <div class="body">
    <h3>{name}</h3>
    <p>{desc}</p>
    <span class="file">📄 {file}{' • ' + group if group else ''}</span>
  </div>
</a>"""


def _sidebar(token: str, sess: Dict[str, Any], kind: str,
             weapons: Optional[List[Dict[str, Any]]] = None) -> str:
    """Przyklejony panel: lista wyborów + budowa paczki."""
    names: List[str] = []
    if kind == "citizen":
        # (uwaga: kroki dostarczy bot — tu tylko id; nazwy resolver robi bot)
        names = list(sess["citizen_ids"])
    else:
        names = list(sess["skin_ids"])

    items_html = ""
    if names:
        for sid in names:
            label = _lookup_name(sess, kind, sid, weapons)
            items_html += (f'<div class="item"><span>{html.escape(label)}</span>'
                           f'<a href="/create/{kind}/{token}/toggle/{html.escape(sid)}" '
                           f'title="Usuń">✕</a></div>')
    else:
        items_html = '<div class="empty">Nic jeszcze nie wybrano — klikaj karty obok 👈</div>'

    count = len(names)
    return f"""
<aside>
  <h3>Twoje wybory <span class="count">{count}</span></h3>
  <div class="chosen-list">{items_html}</div>
  <form method="post" action="/create/finish/{token}">
    <button class="btn btn-primary" type="submit"{' disabled' if not count else ''}>📦 Zbuduj paczkę</button>
  </form>
  <div class="hint">Klik na kartę = wybór / odznaczenie</div>
</aside>"""


def _lookup_name(sess: Dict[str, Any], kind: str, sid: str,
                 weapons: Optional[List[Dict[str, Any]]]) -> str:
    """Nazwa opcji dla panelu (z cache sesji albo z id)."""
    cache = sess.setdefault("name_cache", {})
    if sid in cache:
        return str(cache[sid])
    if kind == "skins" and weapons:
        for w in weapons:
            for s in w["skins"]:
                if s["id"] == sid:
                    cache[sid] = f"{w['name']} — {s['name']}"
                    return str(cache[sid])
    return sid


# ============================================================================
# 7. STRONA STARTOWA + podsumowanie po budowie
# ============================================================================

def render_home_page(user_id: str) -> str:
    main = f"""
<div class="done-panel" style="padding-top:80px">
  <div class="big">🏭</div>
  <h2>Co budujemy dzisiaj?</h2>
  <p>Wybierasz z galerii — wszystkie opcje w zakładkach, klikasz co Ci się podoba,
     a na końcu budujesz paczkę ZIP.</p>
  <div class="actions" style="justify-content:center;margin-top:34px">
    <a class="btn btn-primary" href="/create/citizen?user={user_id}">🏭 Citizen (nieba, pogoda, kombat…)</a>
    <a class="btn btn-warn" href="/create/skins?user={user_id}">🔫 Skiny broni (5 pistoletów)</a>
  </div>
</div>"""
    return _page("Wybierz kreator", "start", main)


def render_pack_done(token: str, download_url: str, kind: str,
                     count: int, size_mb: float) -> str:
    main = f"""
<div class="done-panel">
  <div class="big">✅</div>
  <h2>Paczka gotowa!</h2>
  <p>{count} plików ({size_mb:.1f} MB) z Twoich wyborów — hasze SHA-256 w HASHES.txt.</p>
  <div class="actions" style="justify-content:center">
    <a class="btn btn-primary" href="{html.escape(download_url)}">⬇️ Pobierz paczkę</a>
    <a class="btn btn-ghost" href="/create">🏗️ Następna paczka</a>
  </div>
</div>"""
    return _page("Paczka gotowa", "zbudowano", main)


# ============================================================================
# 8. NARZĘDZIA
# ============================================================================

def _slug(text: str) -> str:
    """Bezpieczny slug grupy do URL (zachowuje emoji — nie koduje)."""
    return text.replace("/", "-").replace(" ", "+").strip()


def unslug(text: str) -> str:
    return text.replace("+", " ")


def _group_count(steps: List[Dict[str, Any]], group: str, chosen: set) -> str:
    """Licznik na zakładce: wybrane/wszystkie."""
    total = sum(1 for s in steps if s.get("group") == group)
    picked = sum(1 for s in steps if s.get("group") == group and s["id"] in chosen)
    return f"{picked}/{total}" if picked else str(total)
