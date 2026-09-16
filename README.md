# 🏭 FiveM Mod Foundry — bot Discord (Python)

Autonomiczny bot do budowania paczek **klienckich** FiveM (foldery `citizen/` i `mods/`,
**zero skryptów serwerowych**) + kreator skinów broni + live feed modów z YouTube
+ panel zarządzania serwerem `/system`.

Napisany w **Pythonie** (discord.py 2.x). Cała logika mieści się w jednym pliku `bot.py`.

---

## ✨ Co robi bot

| Moduł | Opis |
|---|---|
| 🏗️ **Auto-setup serwera** | Po dołączeniu tworzy role, kategorie, kanały i panele (bez duplikatów po restarcie) |
| 🛠️ **Kreator Citizenów** | Prywatny kanał-ticket → **24 opcje w 6 grupach** → ZIP + link (ważny 60 min) |
| 🔫 **Kreator Skinów Broni** | Kategorie → broń → galeria skinów ze zdjęciami w grze → paczka `mods/x64e.rpf/...` |
| 🔎 **Wyszukiwarka skinów** | Zewnętrzny indeks JSON, przyjmuje **wyłącznie pliki `.rpf`** |
| 📡 **Live YouTube Feed** | YouTube Data API v3 co 15 min, filtr serwerówek/cheatów, kategorie, linki z opisów |
| 🔐 **Skan bezpieczeństwa** | Blokada `.exe/.bat/.dll/.lua`…, pliki ryzykowne (`.asi`, archiwa) → zgoda administratora |
| 🧩 **Anty-konflikt plików** | Dwa mody nadpisujące ten sam plik → zostaje ostatnio wybrany (ochrona przed crashem GTA V) |
| 🖼️ **Podgląd kombinacji** | Link `/preview/<token>` — strona z dokładnie Twoją kombinacją i zdjęciami |
| 🎮 **Wersjonowanie paczek** | Wybór buildu GTA V (`/build`), zapis w `manifest.json`, powiadomienia o zmianach |
| 🧾 **Manifest + hashe** | Każda paczka zawiera `manifest.json` i `HASHES.txt` (SHA-256 każdego pliku) |
| ⚙️ **Panel `/system`** | Estetyczna przebudowa serwera + reset z potrójnym potwierdzeniem + logi audytowe |

---

## 📁 Struktura plików

```
fivem-citizen-bot/
├── bot.py             ← CAŁY bot (konfiguracja, kreatory, ZIP, YouTube, HTTP, /system)
├── requirements.txt   ← biblioteki: discord.py, aiohttp, python-dotenv
├── runtime.txt        ← wersja Pythona dla Render/Railway (3.11.9)
├── render.yaml        ← 1-klikowy deploy na Render + zmienne środowiskowe
├── .env.example       ← szablon konfiguracji (skopiuj jako .env)
├── .gitignore         ← chroni tokeny i dane runtime
├── start.bat          ← uruchamianie na Windows (dwuklik)
└── README.md          ← ten plik
```

---

## 🚀 Szybki start (Windows)

1. Zainstaluj **Python 3.11+** → <https://www.python.org/downloads/>
   *(zaznacz „Add Python to PATH” w instalatorze!)*
2. Kliknij dwuklikiem **`start.bat`** — skrypt sam zainstaluje biblioteki, utworzy `.env`
   i otworzy go w Notatniku.
3. Uzupełnij `.env` (punkty niżej), zapisz i uruchom `start.bat` ponownie.

### Ręcznie (Windows / Linux / VPS)

```bash
pip install -r requirements.txt
cp .env.example .env      # Windows: copy .env.example .env
nano .env                 # wpisz tokeny (patrz niżej)
python bot.py             # start bota
```

---

## 🔑 Konfiguracja tokenów

### 1. Discord (wymagane)

1. <https://discord.com/developers/applications> → **New Application**
2. **Bot** → **Reset Token** → skopiuj do `DISCORD_TOKEN`
3. **General Information** → **Application ID** → skopiuj do `CLIENT_ID`
4. **Bot** → **Privileged Gateway Intents** → włącz **MESSAGE CONTENT INTENT**
   *(potrzebny do wyszukiwarki skinów `.rpf`)*
5. Zaproszenie bota (podmień `CLIENT_ID`):

```
https://discord.com/oauth2/authorize?client_id=CLIENT_ID&permissions=1610883072&scope=bot%20applications.commands
```

**Ważne:** rola bota musi być **wyżej** w hierarchii niż `Członek` i `Tworzenie w toku`,
inaczej przyciski ról i prywatne kanały zwrócą błąd uprawnień.

### 2. YouTube Data API v3 (live feed)

1. <https://console.cloud.google.com/> → nowy projekt
2. **APIs & Services → Library** → **YouTube Data API v3** → **Enable**
3. **Credentials → Create credentials → API key** → skopiuj do `YOUTUBE_API_KEY`

Bez klucza bot działa dalej — tylko kanał `#mody-optymalizacja-live` nie dostaje nowych filmów.

### 3. PUBLIC_URL (krytyczne!)

Adres, pod którym **gracze** pobiorą paczki:

| Gdzie hostujesz | PUBLIC_URL |
|---|---|
| Twój komputer (testy) | `http://localhost:3000` |
| VPS | `http://IP_SERWERA:3000` |
| VPS + domena (zalecane) | `https://bot.twojadomena.pl` |
| Render | `https://twoja-usluga.onrender.com` |

Bez tego linki wskazują `localhost` i nikt nie pobierze paczki.

### 4. SKIN_INDEX_URL (wyszukiwarka skinów)

Link do pliku JSON z Twoim indeksem skinów:

```json
[
  {
    "id": "ak47-redline",
    "name": "AK-47 Redline",
    "description": "Czerwone linie na czarnym korpusie",
    "imageUrl": "https://.../ak-redline.jpg",
    "fileUrl": "https://.../ak47_redline.rpf",
    "author": "twoj-nick",
    "tags": ["ak47", "red"]
  }
]
```

Przyjmowane są **wyłącznie** pliki kończące się na `.rpf`.

---

## 🎮 Jak korzysta z tego gracz

1. `#witaj` → **✅ Zaznacz się** (dostaje rolę).
2. `#stworz-citizena` → **Zacznij tworzyć citizena** → bot tworzy **prywatny kanał**.
3. Przechodzi 24 opcje (niebo, woda, cienie, pojazdy, potato, kombat) — każda ma
   zdjęcie efektu w grze i przyciski **➕ Dodaj / ⏭️ Pomiń / 📋 Podsumowanie** + menu przeskoku.
4. Wybiera **docelowy build GTA V** i klika **📦 Zakończ tworzenie**.
5. Dostaje **link do ZIP** (ważny 60 min) + link do **podglądu kombinacji**.
6. Paczka zawiera `citizen/`, `mods/`, `INSTRUKCJA.txt`, `manifest.json`, `HASHES.txt`.
7. Kanał zamyka się sam (15 min po wygenerowaniu paczki) albo przyciskiem 🔒.

---

## 🛠️ Komendy

| Komenda | Kto | Opis |
|---|---|---|
| `/panel` | Admin | Panel kreatora citizenów na bieżącym kanale |
| `/panel_skins` | Admin | Panel kreatora skinów broni |
| `/skanuj` | Admin | Wymusza skan YouTube tu i teraz |
| `/build wersja` | Admin | Ustawia docelowy build GTA V (powiadamia o potrzebie regeneracji paczek) |
| `/system` | Owner/Admin | Design serwera + reset (3 zabezpieczenia) + logi |
| `/zamknij` | Właściciel sesji | Zamyka jego kanał sesji |
| `/status` | Wszyscy | Kolejka, sesje, paczki, zgłoszenia, build |

---

## 🖥️ Hosting 24/7 (bez włączonego komputera)

### Wariant A — Render (najprościej)

1. Wrzuć repo na GitHub (instrukcja niżej).
2. <https://render.com> → **New → Blueprint** → wskaż repo (Render przeczyta `render.yaml`).
3. Uzupełnij sekrety: `DISCORD_TOKEN`, `CLIENT_ID`, `YOUTUBE_API_KEY`, `PUBLIC_URL`, `SKIN_INDEX_URL`.

⚠️ Na darmowym planie Render usypia usługę — bot Discord musi działać 24/7, więc wybierz plan płatny.

### Wariant B — VPS (najtaniej, pełna kontrola)

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git screen
git clone https://github.com/TWOJ-LOGIN/fivem-citizen-bot.git
cd fivem-citizen-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env      # uzupełnij tokeny + PUBLIC_URL
screen -S bot                          # sesja w tle
python bot.py                          # Ctrl+A, D = wyjście z sesji (bot dalej działa)
```

Podgląd logów: `screen -r bot`. Zatrzymanie: `Ctrl+C` w sesji.

---

## 📤 Wgranie na GitHub (bez znajomości gita)

1. Wypakuj folder i wejdź na <https://github.com/new>.
2. Nazwij repozytorium (np. `fivem-citizen-bot`) → **Create repository** (bez README).
3. Kliknij **„uploading an existing file"** → przeciągnij całą zawartość folderu → **Commit changes**.
4. Sprawdź, czy widzisz pliki: `bot.py`, `requirements.txt`, `runtime.txt`, `render.yaml`
   (plus ukryte `.env.example`, `.gitignore` — włącz **Widok → Ukryte elementy** w Eksploratorze).

Nigdy nie wgrywaj pliku `.env` — jest chroniony przez `.gitignore`.

---

## 🧪 Weryfikacja

```bash
python -m py_compile bot.py     # sprawdzenie składni
python bot.py                   # start; brak tokenów = czytelny komunikat
```

Bot przy starcie sam waliduje konfigurację i wypisuje, czego brakuje w `.env`.

---

## ⚠️ Co musisz uzupełnić sam (uczciwie)

1. **`IMG_BASE`, `FILE_BASE` i `SKIN_BASE`** w `bot.py` (sekcja KONFIGURACJA/DANE) to
   **placeholdery** (`https://i.imgur.com/`, `https://example.com/...`) — bot nie wymyśli
   za Ciebie legalnych plików modów ani zdjęć poglądowych. Podmień je na własne.
   W miejscach do zmiany znajdziesz komentarz `PODMIEŃ`.
2. **`SKIN_INDEX_URL`** — bez własnego indeksu wyszukiwarka skinów zwróci „indeks pusty".
3. **Prawa do modów** — bot tylko pakuje pliki z linków, które mu podasz.
4. **Regulamin serwerów FiveM** — mody klienckie (`.rpf` w `mods/`) są dozwolone na jednych
   serwerach, a blokowane na innych. Paczki zawierają ostrzeżenie, ale odpowiedzialność
   jest po stronie gracza.

---

## 🧹 Sprzątanie i limity (ochrona serwera)

| Zasób | Domyślny TTL | Zmienna |
|---|---|---|
| Link do paczki ZIP | 60 min | `DOWNLOAD_TTL_MINUTES` |
| Kanał sesji po paczce | 15 min | `CHANNEL_CLEANUP_MINUTES` |
| Sesja bezczynna | 120 min | `SESSION_TTL_MINUTES` |
| Zgłoszenie bezpieczeństwa | 1440 min | `APPROVAL_TTL_MINUTES` |
| Plik moda | 200 MB | `MAX_DOWNLOAD_MB` |
| Równoległe ZIP-y | 2 | `ZIP_QUEUE_CONCURRENCY` |

Porzucone katalogi `temp_sessions/` są czyszczone cyklicznie, także po restarcie bota.

---

## 📄 Licencja

MIT — korzystaj i modyfikuj dowolnie. Mody klienckie pobierasz na własną odpowiedzialność.
