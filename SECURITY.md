# Bezpieczeństwo

## Zgłaszanie luk

Jeśli znajdziesz lukę bezpieczeństwa w tym projekcie (np. wyciek tokena,
brak autoryzacji na endpointach download), **nie otwieraj publicznego issue**.
Napisz do właściciela repo prywatnie (GitHub → Security → Report a vulnerability)
lub przez kontakt podany w profilu.

## Dobre praktyki przy korzystaniu z bota

- **Nigdy nie commituj pliku `.env`** — zawiera token bota Discord. Wyciek tokena
  = pełna kontrola nad botem. Jeśli token wyciekł, natychmiast zresetuj go w
  [Discord Developer Portal](https://discord.com/developers/applications) → Bot → Reset Token.
- Endpoint `/download/:token` jest chroniony losowym 32-znakowym tokenem, ale
  każdy, kto zna link, może pobrać paczkę — nie publikuj linków publicznie.
- Weryfikuj ręcznie każdy link dodawany do bazy modów (`src/config.js`) — bot
  sprawdza tylko dostępność HTTP, nie treść pliku.
- Dystrybucja cudzych plików modów bez zgody autorów może naruszać ich licencje.

## Zakres

Raportuj: uwierzytelnianie, obsługę uploadu/pobierania plików, uprawnienia kanałów
Discorda, obsługę sekretów.
Nie raportuj: błędów stylu kodu, braku funkcji.
