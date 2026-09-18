"""
==============================================================================
 citizen_patch.py — PATCHER PLIKÓW CITIZENA (baza: paczka z citizen.rar)
==============================================================================
Zamiast wymyślać pliki od zera, bierzemy PRAWDZIWE pliki z paczki
(`citizen_templates/`, skopiowane z citizen.rar) i zmieniamy w nich WARTOŚCI.
Dzięki temu paczka gracza jest zgodna z grą: te same tabele, te same nagłówki,
tylko inne liczby („te same pliki, zmienione wartości").

Zawartość szablonów (analiza citizen.rar):
  timecycle/MATOL.xml              426 parametrów × 13 kluczy czasowych
                                   (niebo, chmury, słońce, księżyc, woda, mgła,
                                   światło, postfx, blur/dof/lens, lod/ssao)
  timecycle/timecycle_mods_4.xml   252 modyfikatory, w tym KILL EFFECT
                                   (`hud_def_desat_cold_kill` — opisany przez
                                   autorów paczki komentarzami po polsku)
  visualsettings.dat               tabele key=value (deszcz, pogoda, niebo,
                                   cienie, kałuże, światła pojazdów, dof)
  clouds.xml / cloudkeyframes.xml  chmury: pozycja, skala, gęstość, prędkość
  effects/explosionfx.dat          tabela eksplozji (SCALE, SCORCH, NUMBER…)
  effects/firefx.dat               tabela ognia (FLAM, BURN TIME, BURN STR)
  effects/entityfx.dat             cząstki otoczenia (dym, para, kurz)
  ui/pausemenu.xml                 układ menu pauzy (HUD/UI)

Wszystkie funkcje są czyste (tekst → tekst) i zachowują liczbę wartości
w danym znaczniku, więc plik dalej ma dokładnie tyle kluczy, ile oczekuje gra.
==============================================================================
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

TEMPLATE_DIR = Path(__file__).parent / "citizen_templates"

# Szablony są też WKLEJONE w citizen_templates_data.py, więc bot działa z samych
# plików .py — folder `citizen_templates/` jest opcjonalny (jeśli istnieje, ma
# pierwszeństwo: łatwiej podmienić pojedynczy szablon).
try:  # pragma: no cover — brak modułu = korzystamy tylko z folderu
    import citizen_templates_data as _embedded
    if not getattr(_embedded, "DATA", None):
        _embedded = None
    # noqa: SIM105
except Exception:  # noqa: BLE001
    _embedded = None

# ---------------------------------------------------------------------------
# 0. WCZYTYWANIE SZABLONÓW
# ---------------------------------------------------------------------------


def template_exists(rel: str) -> bool:
    if (TEMPLATE_DIR / rel).is_file():
        return True
    return bool(_embedded is not None and rel in _embedded.DATA)


@lru_cache(maxsize=64)
def load(rel: str) -> Optional[str]:
    """
    Zwraca treść szablonu (bez zmiany końców linii — piszemy potem \\r\\n).

    Kolejność: folder `citizen_templates/`, a gdy go nie ma — wbudowane dane
    z `citizen_templates_data.py`. None, gdy szablonu nie ma nigdzie.
    """
    path = TEMPLATE_DIR / rel
    if path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    if _embedded is not None:
        return _embedded.template_text(rel)
    return None


def templates_available() -> List[str]:
    """Lista dostępnych szablonów (diagnostyka/testy)."""
    if TEMPLATE_DIR.is_dir():
        return sorted(p.relative_to(TEMPLATE_DIR).as_posix()
                      for p in TEMPLATE_DIR.rglob("*") if p.is_file())
    if _embedded is not None:
        return _embedded.paths()
    return []


def templates_source() -> str:
    """Skąd bot bierze szablony: 'folder' / 'wbudowane w .py' / 'brak'."""
    if TEMPLATE_DIR.is_dir() and any(TEMPLATE_DIR.rglob("*")):
        return "folder"
    if _embedded is not None:
        return "wbudowane w .py"
    return "brak"


# ---------------------------------------------------------------------------
# 1. XML — ZNACZNIKI (<tag>wartości</tag>)
# ---------------------------------------------------------------------------

def tag_values(text: str, tag: str) -> List[List[float]]:
    """Wszystkie wartości danego znacznika (lista list float, kolejność pliku)."""
    out: List[List[float]] = []
    for raw in re.findall(rf"<{re.escape(tag)}>(.*?)</{re.escape(tag)}>", text, re.DOTALL):
        vals: List[float] = []
        for part in raw.split():
            try:
                vals.append(float(part))
            except ValueError:
                pass
        out.append(vals)
    return out


def _fmt(value: float) -> str:
    """Format liczby jak w plikach Citizen Makers (3 miejsca po kropce)."""
    return f"{float(value):.3f}"


def set_tag(text: str, tag: str, values: Sequence[float],
            only: Optional[int] = None) -> str:
    """
    Ustawia wartości znacznika w KAŻDYM wystąpieniu (albo tylko w wybranym).
    Liczba wartości jest dopasowana do oryginału: jeśli w pliku było 13 kluczy,
    a podano mniej — ostatnia wartość jest powtarzana (stała w czasie).
    Gdy znacznika nie ma w pliku — zwraca tekst bez zmian (bezpieczne).
    """
    vals = [float(v) for v in values] or [0.0]
    counter = {"i": 0}

    def repl(match: "re.Match[str]") -> str:
        idx = counter["i"]
        counter["i"] += 1
        if only is not None and idx != only:
            return match.group(0)
        count = len(match.group(2).split()) or len(vals)
        filled = (vals * ((count // len(vals)) + 1))[:count]
        body = " ".join(_fmt(v) for v in filled)
        return f"{match.group(1)} {body} {match.group(3)}"

    pattern = rf"(<{re.escape(tag)}>)(.*?)(</{re.escape(tag)}>)"
    return re.sub(pattern, repl, text, flags=re.DOTALL)


def set_tag_map(text: str, mapping: Dict[str, Sequence[float]]) -> str:
    """Ustawia wiele znaczników naraz."""
    for tag, values in mapping.items():
        text = set_tag(text, tag, values)
    return text


def scale_tag(text: str, tag: str, factor: float,
              vmin: Optional[float] = None, vmax: Optional[float] = None) -> str:
    """Mnoży wartości znacznika przez `factor` (z opcjonalnym ograniczeniem)."""
    def func(orig: Sequence[float]) -> Sequence[float]:
        out = []
        for value in orig:
            new = value * factor
            if vmin is not None:
                new = max(vmin, new)
            if vmax is not None:
                new = min(vmax, new)
            out.append(new)
        return out

    return set_tag_func(text, tag, func)


def set_tag_func(text: str, tag: str, func: Callable[[Sequence[float]], Sequence[float]]) -> str:
    """Przekształca wartości znacznika funkcją (na każdym wystąpieniu)."""
    def repl(match: "re.Match[str]") -> str:
        vals: List[float] = []
        for part in match.group(2).split():
            try:
                vals.append(float(part))
            except ValueError:
                pass
        if not vals:
            return match.group(0)
        new_vals = list(func(vals))
        body = " ".join(_fmt(v) for v in new_vals)
        return f"{match.group(1)} {body} {match.group(3)}"

    pattern = rf"(<{re.escape(tag)}>)(.*?)(</{re.escape(tag)}>)"
    return re.sub(pattern, repl, text, flags=re.DOTALL)


def set_attr(text: str, tag: str, attr: str, value: float,
             occurrence: Optional[int] = None) -> str:
    """
    Ustawia atrybut znacznika (np. <mScale x="…"> w clouds.xml).
    `occurrence` = numer wystąpienia znacznika (None = wszystkie).
    """
    counter = {"i": 0}

    def repl(match: "re.Match[str]") -> str:
        idx = counter["i"]
        counter["i"] += 1
        if occurrence is not None and idx != occurrence:
            return match.group(0)
        body = match.group(1)
        pattern = rf'(\s{re.escape(attr)}\s*=\s*")([^"]*)(")'
        if re.search(pattern, body):
            return re.sub(pattern, lambda m: f"{m.group(1)}{_fmt(value)}{m.group(3)}", body,
                          count=1)
        return body

    pattern = rf"(<{re.escape(tag)}\b[^>]*>)"
    return re.sub(pattern, repl, text)


# ---------------------------------------------------------------------------
# 2. visualsettings.dat — TABELE key=value
# ---------------------------------------------------------------------------

def set_kv(text: str, key: str, value: float) -> str:
    """Ustawia wartość klucza (`rain.NumberParticles 0` → nowa liczba)."""
    return set_kv_many(text, {key: value})


def set_kv_many(text: str, mapping: Dict[str, float]) -> str:
    for key, value in mapping.items():
        pattern = rf"^(\s*{re.escape(key)})(\s+)(\S+)(\s*)$"

        def repl(match: "re.Match[str]") -> str:
            return f"{match.group(1)}{match.group(2)}{_fmt(value)}{match.group(4)}"

        text = re.sub(pattern, repl, text, count=1, flags=re.MULTILINE)
    return text


def scale_kv(text: str, key: str, factor: float,
             vmin: Optional[float] = None, vmax: Optional[float] = None) -> str:
    """Mnoży wartość klucza (np. moc deszczu ×2)."""
    pattern = rf"^(\s*{re.escape(key)})(\s+)(\S+)(\s*)$"

    def repl(match: "re.Match[str]") -> str:
        try:
            value = float(match.group(3)) * factor
        except ValueError:
            return match.group(0)
        if vmin is not None:
            value = max(vmin, value)
        if vmax is not None:
            value = min(vmax, value)
        return f"{match.group(1)}{match.group(2)}{_fmt(value)}{match.group(4)}"

    return re.sub(pattern, repl, text, count=1, flags=re.MULTILINE)


def kv_value(text: str, key: str) -> Optional[float]:
    """Odczyt wartości klucza (testy/weryfikacja)."""
    match = re.search(rf"^\s*{re.escape(key)}\s+(\S+)\s*$", text, re.MULTILINE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 3. TABELE .dat (kolumny rozdzielane spacjami/tabami)
# ---------------------------------------------------------------------------

def _rebuild_row(line: str, tokens: List[str]) -> str:
    """Składa wiersz tabeli .dat (tab-separated — tak jak oryginał)."""
    indent = line[:len(line) - len(line.lstrip())]
    return indent + "\t".join(tokens) + "\n"


def patch_table(text: str, prefix: str, column: int,
                factor: Optional[float] = None, value: Optional[float] = None,
                vmin: Optional[float] = None, vmax: Optional[float] = None,
                contains: Optional[Iterable[str]] = None) -> str:
    """
    Zmienia jedną kolumnę we wszystkich wierszach tabeli .dat, które zaczynają
    się od `prefix` (np. 'EXP_VFXTAG_').

    column — numer kolumny (0 = pierwsza)
    factor — mnożnik wartości   |  value — wartość na sztywno
    contains — patrz tylko na wiersze zawierające któryś z tych fragmentów
    """
    needles = [n.upper() for n in (contains or [])]
    lines = text.split("\n")
    for i, line in enumerate(lines):
        tokens = line.split()
        if not tokens or not tokens[0].startswith(prefix):
            continue
        if needles and not any(n in line.upper() for n in needles):
            continue
        if column >= len(tokens):
            continue
        try:
            current = float(tokens[column])
        except ValueError:
            continue
        new = value if value is not None else current * (factor if factor is not None else 1.0)
        if vmin is not None:
            new = max(vmin, new)
        if vmax is not None:
            new = min(vmax, new)
        tokens[column] = _fmt(new)
        lines[i] = _rebuild_row(line, tokens)
    return "\n".join(lines)


def patch_last_column(text: str, prefixes: Sequence[str],
                      contains: Optional[Iterable[str]] = None,
                      value: float = 0.0) -> str:
    """
    Zeruje OSTATNIĄ liczbę w wierszach danych tabel (próg/rate cząstek) —
    używane do wyłączania dymu, kurzu i cząstek otoczenia.
    """
    needles = [n.upper() for n in (contains or [])]
    lines = text.split("\n")
    for i, line in enumerate(lines):
        tokens = line.split()
        if not tokens or not any(tokens[0].startswith(p) for p in prefixes):
            continue
        if needles and not any(n in line.upper() for n in needles):
            continue
        for idx in range(len(tokens) - 1, 0, -1):
            try:
                float(tokens[idx])
            except ValueError:
                continue
            tokens[idx] = _fmt(value)
            lines[i] = _rebuild_row(line, tokens)
            break
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3b. TABELE .dat — KOMÓRKI ROZDZIELANE TAB-EM (bloodfx, weaponfx, wheelfx…)
#     W tych plikach jedna komórka może zawierać KILKA liczb rozdzielonych
#     spacjami (np. kolor „080 080 085 080”), więc zwykły split() nie wystarcza.
# ---------------------------------------------------------------------------


def _split_cells(line: str) -> Tuple[List[str], List[str]]:
    """Dzieli linię na (komórki, separatory) — separatory zachowane 1:1."""
    parts = re.split(r"(\t+)", line)
    cells = parts[0::2]
    seps = parts[1::2] + [""]
    return cells, seps


def _join_cells(cells: Sequence[str], seps: Sequence[str]) -> str:
    out = []
    for i, cell in enumerate(cells):
        out.append(cell)
        out.append(seps[i] if i < len(seps) else "")
    return "".join(out)


_TOKEN_RE = re.compile(r"-?\d+(?:\.\d+)?")


def row_tokens(line: str) -> List[str]:
    """Wszystkie liczby wiersza w kolejności (struktura tabeli .dat)."""
    return _TOKEN_RE.findall(line)


def patch_row_tokens(text: str, line_pred: Callable[[str], bool],
                     start: int, count: int,
                     func: Callable[[List[float]], Sequence[float]],
                     integer: bool = False,
                     skip_first_cell: bool = True) -> str:
    """
    Podmienia `count` LICZB wiersza począwszy od `start` (licząc wszystkie liczby).

    `skip_first_cell=True` pomija NAZWĘ w pierwszej komórce (np. „SPINE0” zawiera
    cyfrę, która inaczej przesunęłaby numerację liczb). Reszta wiersza jest
    przepisywana 1:1 — taby, spacje i grupowanie komórek zostają nietknięte.
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if not line_pred(line):
            continue
        base = 0
        if skip_first_cell:
            tab = line.find("\t")
            if tab < 0:
                continue
            base = tab + 1
        matches = list(_TOKEN_RE.finditer(line, base))
        if len(matches) < start + count:
            continue
        values = [float(m.group(0)) for m in matches[start:start + count]]
        new_values = list(func(values))
        out: List[str] = [line[:base]]
        last = base
        for offset, match in enumerate(matches[start:start + count]):
            out.append(line[last:match.start()])
            value = new_values[offset] if offset < len(new_values) else values[offset]
            if abs(value - values[offset]) < 1e-9:
                out.append(match.group(0))          # bez zmian — nic nie ruszamy
            else:
                out.append(str(int(round(value))) if integer else _fmt(value))
            last = match.end()
        out.append(line[last:])
        lines[i] = "".join(out)
    return "\n".join(lines)


def _values(cell: str) -> Optional[List[float]]:
    """Liczby z komórki (None, gdy komórka nie jest w całości liczbami)."""
    tokens = cell.split()
    if not tokens:
        return None
    try:
        return [float(t) for t in tokens]
    except ValueError:
        return None


def patch_cell_func(text: str, line_pred: Callable[[str], bool],
                    cell_pred: Callable[[Sequence[float]], bool],
                    func: Callable[[List[float]], Sequence[float]],
                    only_first: bool = True) -> str:
    """
    Podmienia liczby w PASUJĄCEJ KOMÓRCE wierszy tabeli .dat.

    line_pred — które wiersze brać (np. tylko środki tabeli krwi)
    cell_pred — które komórki (np. ta, w której wszystkie liczby ≤ 255)
    func      — co zrobić z liczbami komórki
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if not line_pred(line):
            continue
        cells, seps = _split_cells(line)
        touched = False
        for j, cell in enumerate(cells):
            values = _values(cell)
            if not values or not cell_pred(values):
                continue
            new_values = list(func(values))
            pad = cell[:1] if cell[:1] in " \t" else ""
            cells[j] = pad + " ".join(_fmt(v) for v in new_values)
            touched = True
            if only_first:
                break
        if touched:
            lines[i] = _join_cells(cells, seps)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. KONKRETNE PACZE POD GRUPY OPCJI
# ---------------------------------------------------------------------------

# Kolumny tabeli eksplozji (nagłówek pliku: TYPE + 8 nazw PTFX + wartości)
EXP_COL_SCALE = 9
EXP_COL_SCORCH = 10
EXP_COL_NUMBER = 11
EXP_COL_RANGE = 12

# Kolumny tabeli ognia: MATERIAL FLAM BURN_TIME BURN_STR FX_NAME
FIRE_COL_FLAM = 1
FIRE_COL_TIME = 2
FIRE_COL_STRENGTH = 3


def explosion_scale(text: str, factor: float, vmax: float = 20.0) -> str:
    """Siła eksplozji — mnoży kolumnę SCALE (i lekko rozszerza RANGE)."""
    text = patch_table(text, "EXP_VFXTAG_", EXP_COL_SCALE, factor=factor, vmin=0.0, vmax=vmax)
    text = patch_table(text, "EXP_VFXTAG_", EXP_COL_RANGE, factor=1.0 + (factor - 1.0) * 0.5,
                       vmin=0.0)
    return text


def explosion_scorch(text: str, value: float) -> str:
    """Ślad po eksplozji (SCORCH) — 0 = brak przypalenia."""
    return patch_table(text, "EXP_VFXTAG_", EXP_COL_SCORCH, value=value, vmin=0.0)


def explosion_count(text: str, value: float) -> str:
    """Liczba eksplozji (NUMBER) — więcej = efektowniej."""
    return patch_table(text, "EXP_VFXTAG_", EXP_COL_NUMBER, value=value, vmin=0.0)


# -------------------------------- KREW (effects/bloodfx.dat) ---------------
# Budowa wiersza tabeli krwi (analiza citizen.rar):
#   [0] NAZWA_KOŚCI  [1] flaga (0 / 062)  [2..5] KOLOR RGBA (0–255)
#   [6..8] odcień plamy  [9] ROZMIAR plamy (295)  … [10..] ID efektów
# Pozycje liczb są STAŁE dla wszystkich wierszy, choć grupowanie komórek
# (taby) różni się między wierszami — dlatego patchujemy po pozycji liczby.

# (bez nazwy kości i bez wiodącej flagi: 0 = kolor, 1..4 = RGBA, 8 = rozmiar)
BLOOD_TOKEN_COLOUR = 1
BLOOD_TOKEN_SIZE = 8


def _is_blood_row(line: str) -> bool:
    """Wiersz danych tabeli krwi (pomija nagłówki BLOODFX_* i komentarze)."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or stripped.startswith("BLOODFX"):
        return False
    name = stripped.split()[0]
    if not name.replace("_", "").isalnum() or not name.isupper():
        return False
    body = line.split("\t", 1)[1] if "\t" in line else ""
    return len(row_tokens(body)) >= 20


def blood_colour(text: str, rgb: Sequence[float], alpha: float = 255.0) -> str:
    """
    KOLOR KRWI (RGBA 0–255) dla wszystkich kości — czerwona, ciemna, anime,
    niebieska/plazma, zielona itd. Wartości są zapisywane jak w paczce (0–255).
    """
    red, green, blue = (float(c) for c in rgb)
    return patch_row_tokens(text, _is_blood_row, BLOOD_TOKEN_COLOUR, 4,
                            lambda _v: [red, green, blue, alpha], integer=True)


def blood_size(text: str, factor: float, vmin: float = 50.0,
               vmax: float = 1200.0) -> str:
    """ROZMIAR PLAMY KRWI — skaluje wartość 295 (rozmiar śladu), bez koloru."""
    if abs(factor - 1.0) < 1e-9:
        return text
    return patch_row_tokens(text, _is_blood_row, BLOOD_TOKEN_SIZE, 1,
                            lambda v: [min(vmax, max(vmin, v[0] * factor))],
                            integer=True)


def _is_head_row(line: str) -> bool:
    """Wiersz tabeli krwi dla GŁOWY (HEAD) — pod niego idzie HEAD EFFECT."""
    if not _is_blood_row(line):
        return False
    return line.strip().split()[0].upper().startswith("HEAD")


def blood_head_colour(text: str, rgb: Sequence[float], alpha: float = 255.0) -> str:
    """HEAD EFFECT: kolor krwi tylko z trafienia w głowę (wiersz HEAD)."""
    red, green, blue = (float(c) for c in rgb)
    return patch_row_tokens(text, _is_head_row, BLOOD_TOKEN_COLOUR, 4,
                            lambda _v: [red, green, blue, alpha], integer=True)


def blood_head_size(text: str, factor: float, vmin: float = 20.0,
                    vmax: float = 1200.0) -> str:
    """HEAD EFFECT: rozmiar krwi z trafienia w głowę (wiersz HEAD)."""
    if abs(factor - 1.0) < 1e-9:
        return text
    return patch_row_tokens(text, _is_head_row, BLOOD_TOKEN_SIZE, 1,
                            lambda v: [min(vmax, max(vmin, v[0] * factor))],
                            integer=True)


# ------------------------ EFEKT STRZAŁU (effects/weaponfx.dat) -------------

def _weapon_info_row(line: str) -> bool:
    """Wiersz tabeli DECAL INFO (efekt strzału) — zaczyna się od ID."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    first = stripped.split()[0]
    return first.isdigit() and len(stripped.split("\t")) >= 10


def _is_tint_cell(values: Sequence[float]) -> bool:
    """Początek COL_TINT: dwie liczby 0–255 w jednej komórce (R G)."""
    return len(values) == 2 and all(0.0 <= v <= 255.0 for v in values)


def weaponfx_tint(text: str, rgb: Sequence[float], alpha: float = 255.0) -> str:
    """
    KOLOR EFEKTU STRZAŁU (traces/ślady po kulach) — kolumna COL_TINT.
    Układ wiersza: … RANGE | „R G” | B | A | SIZE MIN | SIZE MAX …
    """
    red, green, blue = (float(c) for c in rgb)
    lines = text.split("\n")
    in_info = False
    changed = 0
    for i, line in enumerate(lines):
        if "WEAPONFX_INFO_START" in line:
            in_info = True
            continue
        if "WEAPONFX_INFO_END" in line:
            in_info = False
            continue
        if not in_info or not _weapon_info_row(line):
            continue
        cells, seps = _split_cells(line)
        for j, cell in enumerate(cells):
            values = _values(cell)
            if not values or not _is_tint_cell(values):
                continue
            pad = cell[:1] if cell[:1] in " \t" else ""
            cells[j] = f"{pad}{int(red)} {int(green)}"
            # kolejne dwie komórki to B i A
            for k, new_value in enumerate((blue, alpha), start=1):
                if j + k >= len(cells):
                    break
                sub = _values(cells[j + k])
                if sub and len(sub) == 1:
                    pad2 = cells[j + k][:1] if cells[j + k][:1] in " \t" else ""
                    cells[j + k] = f"{pad2}{int(new_value)}"
            lines[i] = _join_cells(cells, seps)
            changed += 1
            break
    return "\n".join(lines)


def weaponfx_size(text: str, factor: float, vmin: float = 0.05,
                  vmax: float = 200.0) -> str:
    """
    ROZMIAR ŚLADU PO KULI — skaluje dwie liczby SIZE (MIN/MAX) zaraz za kolorem.
    """
    if abs(factor - 1.0) < 1e-9:
        return text
    lines = text.split("\n")
    in_info = False
    for i, line in enumerate(lines):
        if "WEAPONFX_INFO_START" in line:
            in_info = True
            continue
        if "WEAPONFX_INFO_END" in line:
            in_info = False
            continue
        if not in_info or not _weapon_info_row(line):
            continue
        cells, seps = _split_cells(line)
        colour_at = None
        for j, cell in enumerate(cells):
            values = _values(cell)
            if values and _is_tint_cell(values):
                colour_at = j
                break
        if colour_at is None:
            continue
        # kolumnę koloru tworzą: „R G” | B | A — pomijamy B i A, skalujemy SIZE MIN/MAX
        seen_channels = 0
        scaled = 0
        for j in range(colour_at + 1, len(cells)):
            values = _values(cells[j])
            if not values or len(values) != 1:
                continue
            if seen_channels < 2:
                seen_channels += 1
                continue
            new = min(vmax, max(vmin, values[0] * factor))
            if abs(new - values[0]) >= 1e-9:
                pad = cells[j][:1] if cells[j][:1] in " \t" else ""
                cells[j] = f"{pad}{_fmt(new)}"
            scaled += 1
            if scaled >= 2:
                break
        if scaled:
            lines[i] = _join_cells(cells, seps)
    return "\n".join(lines)


# ------------------------------ OPONY (effects/wheelfx.dat) ---------------

def _wheel_info_row(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or stripped.startswith("VEHFX"):
        return False
    tokens = stripped.split()
    return bool(tokens) and tokens[0].isupper() and len(stripped.split("\t")) >= 12


def wheelfx_tint(text: str, rgb: Sequence[float]) -> str:
    """KOLOR ŚLADÓW OPON (skidmarki) — kolumna COL_TINT w tabeli VEHFX_INFO."""
    red, green, blue = (float(c) for c in rgb)
    in_info = False
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if "VEHFX_INFO_START" in line:
            in_info = True
            continue
        if "VEHFX_INFO_END" in line:
            in_info = False
            continue
        if not in_info or not _wheel_info_row(line):
            continue
        cells, seps = _split_cells(line)
        for j, cell in enumerate(cells):
            values = _values(cell)
            if not values or not _is_tint_cell(values):
                continue
            pad = cell[:1] if cell[:1] in " \t" else ""
            cells[j] = f"{pad}{int(red)} {int(green)}"
            if j + 1 < len(cells):
                sub = _values(cells[j + 1])
                if sub and len(sub) == 1:
                    pad2 = cells[j + 1][:1] if cells[j + 1][:1] in " \t" else ""
                    cells[j + 1] = f"{pad2}{int(blue)}"
            lines[i] = _join_cells(cells, seps)
            break
    return "\n".join(lines)


# ------------------------------ DEKALE (effects/decals.dat) ---------------

def decals_clear(text: str) -> str:
    """
    Usuwa definicje dekali (śladów po kulach/oponach) — zostaje PUSTA tabela.
    Format zgodny z paczką (nagłówek + DECAL_DEF_START/END).
    """
    return ("9.00\n\n\n"
            "# ID - 0001-9999\n\n\n"
            "DECAL_DEF_START\n\n\n"
            "DECAL_DEF_END\n")


def fire_power(text: str, factor: float) -> str:
    """
    Ogień: mnoży FLAM / BURN TIME / BURN STR dla wszystkich materiałów.
    Wiersze tabeli FIREFX_INFO mają dokładnie 5 kolumn (FX_NAME na końcu).
    """
    lines = text.split("\n")
    inside = False
    for i, line in enumerate(lines):
        if "FIREFX_INFO_START" in line:
            inside = True
            continue
        if not inside:
            continue
        tokens = line.split()
        if len(tokens) != 5 or not tokens[4].startswith(("fire_map", "fire_maps")):
            continue
        try:
            flam, burn_time, burn_str = (float(tokens[FIRE_COL_FLAM]),
                                         float(tokens[FIRE_COL_TIME]),
                                         float(tokens[FIRE_COL_STRENGTH]))
        except ValueError:
            continue
        tokens[FIRE_COL_FLAM] = _fmt(max(0.0, min(5.0, flam * factor)))
        tokens[FIRE_COL_TIME] = _fmt(max(0.0, min(5.0, burn_time * factor)))
        tokens[FIRE_COL_STRENGTH] = _fmt(max(0.0, min(5.0, burn_str * factor)))
        lines[i] = _rebuild_row(line, tokens)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. MENU PAUZY / HUD (ui/pausemenu.xml)
# ---------------------------------------------------------------------------

_PAUSE_KEYS = ("MinimapBG", "GalleryBG", "MIDDLE_AVATAR_BG", "RIGHT_AVATAR_BG")


def pausemenu_hide_backgrounds(text: str, hide: Sequence[str] = _PAUSE_KEYS) -> str:
    """
    Czyste menu pauzy: zeruje rozmiar teł (minimapa/galeria/awatary).
    Zero w vSize = element przestaje być widoczny (układ menu zostaje).
    """
    for key in hide:
        pattern = (rf'(<Item key="{re.escape(key)}">)(.*?)(</Item>)')

        def repl(match: "re.Match[str]") -> str:
            body = re.sub(r'(<vSize\b[^>]*?x\s*=\s*")[^"]*(")', r"\g<1>0.000\g<2>",
                          match.group(2))
            body = re.sub(r'(<vSize\b[^>]*?y\s*=\s*")[^"]*(")', r"\g<1>0.000\g<2>", body)
            return match.group(1) + body + match.group(3)

        text = re.sub(pattern, repl, text, flags=re.DOTALL)
    return text


def pausemenu_scale(text: str, factor: float) -> str:
    """Skaluje rozmiary elementów menu pauzy (mniejsza/większa szata graficzna)."""
    def repl(match: "re.Match[str]") -> str:
        def num(m: "re.Match[str]") -> str:
            try:
                value = float(m.group(2)) * factor
            except ValueError:
                return m.group(0)
            return f"{m.group(1)}{_fmt(value)}{m.group(3)}"

        return re.sub(r'([xy]\s*=\s*")(-?[\d.]+)(")', num, match.group(1))

    return re.sub(r'(<vSize\b[^>]*>)', repl, text)


# ---------------------------------------------------------------------------
# 6. PODSUMOWANIE — które pliki umiemy spatchować
# ---------------------------------------------------------------------------

PATCHED_FILES: Dict[str, str] = {
    "timecycle/MATOL.xml": "niebo, chmury, słońce/księżyc, woda, mgła, światło, postfx, render",
    "timecycle/timecycle_mods_1.xml": "light pollution, zasięgi rysowania, bloom, next-gen",
    "timecycle/timecycle_mods_2.xml": "oświetlenie wnętrz i scenerii, next-gen",
    "timecycle/timecycle_mods_3.xml": "oświetlenie wnętrz (v_*), mgła w budynkach",
    "timecycle/timecycle_mods_4.xml": "kill effect (kolor, intensywność, blur)",
    "effects/bloodfx.dat": "kolor i rozmiar krwi (per kość)",
    "effects/weaponfx.dat": "efekt strzału: kolor śladu, rozmiar po kuli, czas życia",
    "effects/wheelfx.dat": "kolor śladów opon, dym z opon",
    "effects/decals.dat": "dekale świata (ślad po kuli, opony)",
    "effects/visualsettings.dat": "cząstki efektów, detale brudu",
    "visualsettings.dat": "deszcz, cykl pogody, chmury, cienie, kałuże, światła pojazdów",
    "clouds.xml": "pozycja i skala chmur, jakość warstw",
    "cloudkeyframes.xml": "gęstość i prędkość chmur (klatki kluczowe)",
    "effects/explosionfx.dat": "siła eksplozji, przypalenie, liczba wybuchów",
    "effects/firefx.dat": "czas i siła palenia",
    "effects/entityfx.dat": "cząstki otoczenia: dym, para, kurz",
    "ui/pausemenu.xml": "menu pauzy / HUD",
}


def patched_file_list() -> List[str]:
    """Pliki, które potrafimy zmodyfikować (do dokumentacji i testów)."""
    return list(PATCHED_FILES.keys())


def demo_report() -> Tuple[int, int]:
    """Diagnostyka: (ile szablonów dostępnych, ile plików patchowalnych)."""
    return len(templates_available()), len(PATCHED_FILES)
