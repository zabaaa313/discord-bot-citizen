"""
==============================================================================
 KREATOR WWW — ładna strona tworzenia paczek (citizen + skiny broni)
==============================================================================
 Bot przekierowuje gracza z Discorda na stronę:
   /create/citizen?user=ID   — kreator citizena (krok po kroku, 1 opcja/ekran)
   /create/skins?user=ID     — kreator skinów broni (1 skin/ekran + podgląd)

 Zasada działania: JEDNA opcja na ekranie — duże zdjęcie, opis, przyciski
   [✅ Wybieram]  [⏭ Pomiń]  [◀ Wróć]  [📦 Zbuduj paczkę]
 Stan wyboru trzymany po stronie serwera (WEB_SESSIONS), więc odświeżenie
 strony nie gubi postępu. Na końcu gracz dostaje paczkę ZIP przez zwykły
 /download/<token> (te same zabezpieczenia co w bocie Discord).
==============================================================================
"""

from __future__ import annotations

import html
import json
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
# 2. DESIGN — wspólny CSS (ciemny motyw w klimacie bota)
# ============================================================================

CREATE_CSS = """
:root{--bg:#0b0d13;--card:#141826;--card2:#1a2033;--line:#2a3350;--txt:#e8ecf7;
--muted:#93a0bd;--acc:#57f287;--acc2:#5865f2;--warn:#fee75c;--danger:#ed4245;--gold:#ffd166}
*{box-sizing:border-box;margin:0;padding:0}
body{background:radial-gradient(1200px 700px at 70% -10%,#1a2340 0%,var(--bg) 60%);
color:var(--txt);font-family:'Segoe UI',system-ui,-apple-system,sans-serif;min-height:100vh;
display:flex;flex-direction:column;align-items:center}
header{width:100%;padding:18px 28px;display:flex;align-items:center;gap:14px;
background:rgba(20,24,38,.8);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
header .logo{width:38px;height:38px;border-radius:10px;background:linear-gradient(135deg,var(--acc2),#9b59b6);
display:grid;place-items:center;font-size:20px}
header h1{font-size:17px;font-weight:600}
header .step-chip{margin-left:auto;background:var(--card2);border:1px solid var(--line);
padding:6px 14px;border-radius:99px;font-size:13px;color:var(--muted)}
main{width:100%;max-width:980px;padding:28px 20px 60px;flex:1}
.progress{display:flex;gap:6px;margin:0 0 26px}
.progress div{height:6px;flex:1;border-radius:99px;background:var(--card2);overflow:hidden}
.progress div.done{background:linear-gradient(90deg,var(--acc2),var(--acc))}
.option-card{background:var(--card);border:1px solid var(--line);border-radius:18px;
overflow:hidden;box-shadow:0 18px 50px rgba(0,0,0,.45)}
.option-card img{width:100%;height:auto;display:block;aspect-ratio:16/9;object-fit:cover}
.option-card .body{padding:26px 30px 30px}
.option-card .group{font-size:12px;letter-spacing:.14em;text-transform:uppercase;
color:var(--acc);font-weight:700;margin-bottom:10px}
.option-card h2{font-size:26px;margin-bottom:10px;font-weight:700}
.option-card p{color:var(--muted);line-height:1.65;font-size:15px;max-width:64ch}
.option-card .meta{margin-top:16px;display:flex;gap:10px;flex-wrap:wrap}
.tag{font-size:12px;background:var(--card2);border:1px solid var(--line);
padding:5px 12px;border-radius:99px;color:var(--muted)}
.tag.ok{color:var(--acc);border-color:rgba(87,242,135,.35)}
.actions{display:flex;gap:12px;margin-top:26px;flex-wrap:wrap}
button,.btn{cursor:pointer;border:0;border-radius:12px;padding:14px 26px;font-size:15px;
font-weight:600;font-family:inherit;text-decoration:none;display:inline-flex;
align-items:center;gap:8px;transition:transform .08s,filter .15s}
button:active{transform:scale(.97)}
.btn-primary{background:linear-gradient(135deg,var(--acc),#3ecf70);color:#08280f}
.btn-ghost{background:var(--card2);color:var(--txt);border:1px solid var(--line)}
.btn-warn{background:linear-gradient(135deg,var(--gold),#e6b73c);color:#332604}
.btn-danger{background:linear-gradient(135deg,var(--danger),#c93a3d);color:#fff}
button:hover,.btn:hover{filter:brightness(1.12)}
.choice-banner{margin:22px 0 0;padding:14px 18px;border-radius:12px;font-size:14px;
background:rgba(87,242,135,.08);border:1px solid rgba(87,242,135,.3);color:var(--acc);
display:none}
.choice-banner.show{display:block}
.done-panel{text-align:center;padding:60px 20px}
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
footer{color:var(--muted);font-size:12px;padding:20px;text-align:center;opacity:.7}
.weapon-tabs{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}
.weapon-tabs a{padding:9px 18px;border-radius:99px;font-size:13px;text-decoration:none;
background:var(--card2);color:var(--muted);border:1px solid var(--line)}
.weapon-tabs a.active{background:var(--acc2);color:#fff;border-color:var(--acc2)}
@media(max-width:640px){.option-card .body{padding:20px}.option-card h2{font-size:21px}}
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
# 3. KREATOR CITIZENA — jeden krok na ekran
# ============================================================================

def render_citizen_page(token: str, sess: Dict[str, Any], steps: List[Dict[str, Any]],
                        image_url_for, msg: str = "") -> str:
    """
    Renderuje stronę jednego kroku citizena.
    image_url_for(step) -> URL do dużego podglądu PNG (serwer bota /img/...).
    """
    idx = len(sess["citizen_ids"])
    done = idx >= len(steps)
    chip = f"Krok {min(idx + 1, len(steps))}/{len(steps)} • wybrano {len(sess['citizen_ids'])}"

    if done:
        items = "".join(
            f"<li><b>{html.escape(s['name'])}</b><span>{html.escape(short_group)}</span></li>"
            for s, short_group in (
                (st, st.get("group", "").split("—")[0].strip()) for st in steps
                if st["id"] in sess["citizen_ids"])
        )
        main = f"""
<div class="done-panel">
  <div class="big">📦</div>
  <h2>Gotowe! Wybrano {len(sess['citizen_ids'])} opcji</h2>
  <p>Kliknij poniżej, a paczka ZIP (citizen/common/data — te same pliki, zmienione wartości)
     zbuduje się i pojawi do pobrania + na Discordzie.</p>
  <div class="summary"><h3>Twoje wybory</h3><ul>{items or '<li><i>brak — tylko własne pliki</i></li>'}</ul></div>
  <div class="actions" style="justify-content:center">
    <a class="btn btn-primary" href="/create/finish/{token}">📦 Zbuduj paczkę</a>
    <a class="btn btn-ghost" href="/create/citizen?user={sess['user_id']}">🔄 Od nowa</a>
  </div>
</div>"""
        return _page("Citizen — gotowe", chip, main)

    step = steps[idx]
    chosen_count = len(sess["citizen_ids"])
    progress_cells = "".join(
        f'<div class="{"done" if i < idx else ""}"></div>' for i in range(len(steps)))
    main = f"""
<div class="progress">{progress_cells}</div>
<div class="option-card">
  <img src="{html.escape(image_url_for(step))}" alt="podgląd">
  <div class="body">
    <div class="group">{html.escape(step.get('group', ''))}</div>
    <h2>{html.escape(step['name'])}</h2>
    <p>{html.escape(step['description'])}</p>
    <div class="meta">
      <span class="tag">📄 plik: {html.escape(str(step.get('gen_file') or step.get('file_name') or '—'))}</span>
      <span class="tag">⚙️ generowany przez bota</span>
    </div>
    <div class="actions">
      <a class="btn btn-primary" href="/create/citizen/{token}/pick/{idx}">✅ Wybieram</a>
      <a class="btn btn-ghost" href="/create/citizen/{token}/skip/{idx}">⏭ Pomiń</a>
      <a class="btn btn-ghost" href="/create/citizen/{token}/back/{idx}">◀ Wróć</a>
    </div>
    <div class="choice-banner{' show' if msg else ''}">{html.escape(msg)}</div>
  </div>
</div>"""
    return _page("Kreator Citizena", chip, main)


# ============================================================================
# 4. KREATOR SKINÓW — jeden skin na ekran, wybór broni zakładkami
# ============================================================================

def render_skins_page(token: str, sess: Dict[str, Any], weapons: List[Dict[str, Any]],
                      image_url_for, msg: str = "") -> str:
    """Jeden skin na ekran: duży podgląd broni, opis, wybieram/pomiń/wróć."""
    weapon = next((w for w in weapons if w["id"] == sess["weapon"]), weapons[0])
    skins = weapon["skins"]
    idx = len(sess["skin_ids"])
    done = idx >= len(skins)
    total = sum(len(w["skins"]) for w in weapons)
    chip = (f"{weapon['name']} • skin {min(idx + 1, len(skins))}/{len(skins)} • "
            f"wybrano {len(sess['skin_ids'])}/{total}")

    tabs = "".join(
        f'<a class="{"active" if w["id"] == weapon["id"] else ""}" '
        f'href="/create/skins/{token}/weapon/{w["id"]}">{html.escape(w["name"])}</a>'
        for w in weapons)

    if done:
        chosen = [(wid, sk) for wid, sk in
                  ((w["id"], next((s for s in w["skins"] if s["id"] == sid), None))
                   for w in weapons for sid in sess["skin_ids"]) if sk]
        items = "".join(
            f"<li><b>{html.escape(wname)}</b><span>{html.escape(sk['name'])}</span></li>"
            for wid, sk in chosen
            for wname in [next(w["name"] for w in weapons if w["id"] == wid)])
        main = f"""
<div class="done-panel">
  <div class="big">🔫</div>
  <h2>Wybrano {len(chosen)} skinów</h2>
  <p>Paczka ZIP z .ytd do wrzucenia w <b>mods/x64e.rpf/models/cdimages/weapons</b>.</p>
  <div class="summary"><h3>Twoje skiny</h3><ul>{items or '<li><i>nic nie wybrano</i></li>'}</ul></div>
  <div class="actions" style="justify-content:center">
    <a class="btn btn-primary" href="/create/finish/{token}">📦 Zbuduj paczkę</a>
    <a class="btn btn-ghost" href="/create/skins?user={sess['user_id']}">🔄 Od nowa</a>
  </div>
</div>"""
        return _page("Skiny — gotowe", chip, main)

    skin = skins[idx]
    main = f"""
<div class="weapon-tabs">{tabs}</div>
<div class="option-card">
  <img src="{html.escape(image_url_for(weapon, skin))}" alt="podgląd skina">
  <div class="body">
    <div class="group">{html.escape(weapon['name'])}</div>
    <h2>{html.escape(skin['name'])}</h2>
    <p>{html.escape(skin['description'])}</p>
    <div class="meta">
      <span class="tag">📄 plik: {html.escape(str(skin.get('file_name') or '—'))}</span>
      <span class="tag ok">✅ do paczki: {len(sess['skin_ids'])}</span>
    </div>
    <div class="actions">
      <a class="btn btn-primary" href="/create/skins/{token}/pick/{idx}">✅ Wybieram</a>
      <a class="btn btn-ghost" href="/create/skins/{token}/skip/{idx}">⏭ Pomiń</a>
      <a class="btn btn-ghost" href="/create/skins/{token}/back/{idx}">◀ Wróć</a>
    </div>
    <div class="choice-banner{' show' if msg else ''}">{html.escape(msg)}</div>
  </div>
</div>"""
    return _page("Kreator Skinów", chip, main)


# ============================================================================
# 5. STRONA STARTOWA (wybór: citizen czy skiny)
# ============================================================================

def render_home_page(user_id: str) -> str:
    main = f"""
<div class="done-panel" style="padding-top:80px">
  <div class="big">🏭</div>
  <h2>Co budujemy dzisiaj?</h2>
  <p>Kreator poprowadzi Cię krok po kroku — jedna opcja na ekran,
     duży podgląd, opis i przycisk dalej.</p>
  <div class="actions" style="justify-content:center;margin-top:34px">
    <a class="btn btn-primary" href="/create/citizen?user={user_id}">🏭 Citizen (niebo, pogoda, kombat…)</a>
    <a class="btn btn-warn" href="/create/skins?user={user_id}">🔫 Skiny broni (4 pistolety)</a>
  </div>
</div>"""
    return _page("Wybierz kreator", "start", main)
