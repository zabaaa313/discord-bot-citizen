# 🛠️ Kreator Citizenów do FiveM — Bot Discord (Python)

W pełni zautomatyzowany bot (Python + discord.py), który:

- **Auto-konfiguruje serwer** po dołączeniu: rolę `Creator`, kategorię, kanał `#stworz-citizena`, kanał `#pobrane-paczki` i panel startowy z przyciskiem.
- **Kanał #mody-optymalizacja** z bazą sprawdzonych modów klienckich (embedy: nazwa, wpływ na FPS, link do strony moda) z **automatyczną weryfikacją linków** co 6 h.
- **Tworzy prywatne kanały** (system ticketów) per użytkownik.
- **Kreator citizena krok po kroku**: embedy ze zdjęciami poglądowymi, przyciski **Dodaj / Pomiń / Usuń**, menu do przeskakiwania kroków.
- **Kreator skinów broni**: select menu wyboru broni, galeria skinów ze zdjęciami, paczka ZIP z plikami `.ytd`/`.ydr`.
- **Backend**: pobiera pliki, buduje strukturę folderu `citizen` FiveM, pakuje do `.zip` i generuje link do pobrania.

## 📁 Struktura (wszystko na płasko — jak w prostym repo Pythonowym)

```
fivem-citizen-bot/
├── bot.py            # cały kod bota (konfiguracja w sekcji KONFIGURACJA na górze)
├── requirements.txt  # zależności Pythona
├── runtime.txt       # wersja Pythona (dla Render/Railway)
├── render.yaml       # blueprint do 1-klikowego deployu na Render
├── .env.example      # szablon konfiguracji (skopiuj jako .env)
├── README.md
├── LICENSE
└── SECURITY.md
```

## 📦 Instalacja lokalna

```bash
python -m venv venv
venv\Scripts\activate        # Windows  (Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env       # (Linux/Mac: cp) i wklej DISCORD_TOKEN + CLIENT_ID
python bot.py
```

## 🤖 Utworzenie bota na Discordzie

1. [discord.com/developers/applications](https://discord.com/developers/applications) → **New Application**.
2. Zakładka **Bot** → **Reset Token** → skopiuj do `.env` jako `DISCORD_TOKEN`.
3. Zakładka **OAuth2** → skopiuj **Client ID** do `.env`.
4. Zaproś bota (podmień `CLIENT_ID`):
   ```
   https://discord.com/oauth2/authorize?client_id=CLIENT_ID&permissions=1610883072&scope=bot%20applications.commands
   ```

## ☁️ Hosting 24/7 (Render — deploy z GitHub)

1. Wrzuć projekt na GitHub (bez `.env`!).
2. [render.com](https://render.com) → **New → Blueprint** → wybierz repo (plik `render.yaml` zrobi resztę).
3. W panelu uzupełnij `DISCORD_TOKEN`, `CLIENT_ID`, `PUBLIC_URL` (Render poda domenę `*.onrender.com` — wklej ją do `PUBLIC_URL`).

**Uwaga:** darmowy plan Rendera **usypia** procesy bez ruchu HTTP — do pracy 24/7 wybierz plan Starter (~7 USD/mies.). Alternatywnie tani VPS + `systemd`/`screen`:

```bash
screen -S bot
python bot.py
# Ctrl+A, D aby się odłączyć
```

## 🖼️ Własne grafiki i pliki modów

Cała konfiguracja jest na górze `bot.py`:

- **`STEPS`** — kroki kreatora citizena (`image` — zdjęcie poglądowe, `fileUrl` — link do pliku moda, `target` — ścieżka w strukturze citizen).
- **`OPTIMIZATION_MODS`** — mody na kanał `#mody-optymalizacja` (linki wstawiaj po ręcznej weryfikacji: GitHub, gta5-mods.com, forum.cfx.re — bot linkuje do strony moda, więc URL nie wygasa; bot co 6 h sprawdza sam, czy linki żyją).
- **`WEAPONS`** — bronie i skiny w kreatorze skinów.

Dodanie nowego kroku/broni = dopisanie wpisu do listy.

## 🔒 Bezpieczeństwo

- Paczki ZIP dostępne 24 h pod losowym tokenem (32 znaki), potem auto-usuwanie.
- Limit pobierania: 200 MB na plik.
- Sesje kreatora wygasają po 2 h bezczynności.
- `.env` nigdy nie trafia do repo (jest w `.gitignore`).

## ❓ FAQ

**Bot nie tworzy kanałów?** Sprawdź, czy jego rola jest wyżej niż role, które ma nadawać, i ma uprawnienia Manage Roles/Channels.

**Zdjęcia nie działają w embedach?** Discord wymaga publicznych URL-i — otwórz linki z `bot.py` w trybie incognito i sprawdź.

**Jak zmienić nazwy kanałów/ról?** Stałe `ROLE_*`, `CATEGORY_*`, `CH_*` na górze `bot.py`.
