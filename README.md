# tax-monitor

Denní DPH monitor. Každý pracovní den v 06:00 CZ projde tři zdroje, vybere nové
položky a pošle přehled emailem na `leitnerczechia@gmail.com`.

## Zdroje

| Zdroj   | URL                                                                 | Co sleduje                                    |
| ------- | ------------------------------------------------------------------- | --------------------------------------------- |
| NSS     | https://vyhledavac.nssoud.cz/                                       | Agenda Afs, Oblast úpravy = Daně - daň z přidané hodnoty (číselník id 164) |
| GFŘ     | https://www.financnisprava.gov.cz/cs/financni-sprava/novinky        | Novinky obsahující "DPH"                      |
| EUR-Lex | https://eur-lex.europa.eu/ (advanced search RSS)                    | Nové rozsudky SDEU s frází "value added tax" |

## Jak to funguje

1. `main.py` postupně volá `scrapers.fetch_nss()`, `fetch_gfr()`, `fetch_eurlex()`.
2. Každá scrap. funkce vrací `list[ScrapedItem]`; chyby jsou izolované —
   když spadne jeden zdroj, ostatní stále proběhnou.
3. Dedup vrstva (`db.py`, SQLite `state.db`) pamatuje, co už bylo odesláno.
4. `emailer.py` pošle přehled přes Gmail SMTP (465, SSL). Pokud nejsou žádné
   nové položky, pošle email *"Žádné nové DPH novinky za posledních 24 hodin"*.
5. GitHub Actions workflow (`.github/workflows/daily.yml`) spouští job
   `0 4 * * 1-5` a `0 5 * * 1-5` UTC — pokrývá oba DST stavy. `main.py` se chová
   idempotentně (`runs.run_date` v DB), takže pošle email právě jednou denně.

## Lokální spuštění

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export GMAIL_USER=leitnerczechia@gmail.com
export GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx   # viz níže
export RECIPIENT=leitnerczechia@gmail.com
python main.py
```

## Soubory

```
tax-monitor/
├── main.py                      # orchestrátor
├── db.py                        # SQLite (seen_items, runs)
├── emailer.py                   # Gmail SMTP
├── scrapers/
│   ├── base.py                  # ScrapedItem dataclass
│   ├── nss.py
│   ├── gfr.py
│   └── eurlex.py
├── requirements.txt
├── state.db                     # vytvoří se automaticky při prvním běhu
└── .github/workflows/daily.yml  # GitHub Actions cron
```

## Známé problémy

- **gfr.py používá keyword filtr "dph"** (viz `DPH_TERMS` ve `scrapers/gfr.py`),
  který běží jen nad titulkem + kontextem na listing stránce. To vede k false
  positives (novinka jen mimochodem zmíní DPH) i false negatives (relevantní
  novinka, která v titulku nemá "DPH" ani "daň z přidané hodnoty").
  Plánovaný fix: přejít na filtrování podle tagu/URL-segmentu přes
  `financnisprava.gov.cz/cs/dane/dan-z-pridane-hodnoty/` nebo přes RSS feed
  s kategorií DPH.

---

## Nasazení — krok za krokem

### 1) Vytvoř Gmail App Password

App Password je 16znakový token, který Gmail používá místo hesla pro SMTP
klienty. Nejde o hlavní heslo k účtu.

1. Otevři https://myaccount.google.com/security a u účtu
   `leitnerczechia@gmail.com` zapni **2-Step Verification** (pokud ještě není).
2. Jdi na https://myaccount.google.com/apppasswords .
3. V poli *App name* napiš `tax-monitor` a klikni **Create**.
4. Google zobrazí 16znakový token ve tvaru `abcd efgh ijkl mnop`. **Zkopíruj
   ho teď — znovu ho neukáže.**

### 2) Inicializuj lokální git repo a nahraj na GitHub

```bash
cd ~/projekty/tax-monitor

git init -b main
git add .
git commit -m "Initial tax-monitor"

# Vytvoř prázdný privátní repozitář na GitHubu — buď přes web (github.com/new),
# nebo přes gh CLI:
gh repo create tax-monitor --private --source=. --remote=origin --push
```

Pokud používáš webové UI:
1. github.com/new → jméno `tax-monitor`, Private, **bez** README/gitignore/license.
2. Zkopíruj URL (`git@github.com:<user>/tax-monitor.git`) a:
   ```bash
   git remote add origin git@github.com:<user>/tax-monitor.git
   git push -u origin main
   ```

### 3) Nastav GitHub Secrets

Na stránce repozitáře: **Settings → Secrets and variables → Actions → New repository secret**.

Vytvoř **dva** secrets:

| Název secretu         | Hodnota                                                |
| --------------------- | ------------------------------------------------------ |
| `GMAIL_USER`          | `leitnerczechia@gmail.com`                             |
| `GMAIL_APP_PASSWORD`  | 16znakový App Password z kroku 1 (bez mezer)          |

Nebo přes CLI:

```bash
gh secret set GMAIL_USER --body "leitnerczechia@gmail.com"
gh secret set GMAIL_APP_PASSWORD --body "abcdefghijklmnop"   # bez mezer
```

### 4) Povol workflow a otestuj ručně

1. V repu: **Actions** → pokud se zeptá *"I understand my workflows, go ahead
   and enable them"*, klikni **Enable**.
2. Vyber workflow **Daily VAT Digest** → **Run workflow** → **main** → **Run**.
3. Sleduj log. Měl by proběhnout do 2 minut a ty bys měl/a dostat email.

Pokud email nepřijde:
- Zkontroluj log kroku *Run monitor*.
- Nejčastější příčina je špatně vložený App Password (musí být bez mezer).
- Gmail SMTP vrací `535-5.7.8 Username and Password not accepted` → přegeneruj App Password.

### 5) Cron běží sám

Od teď workflow běží automaticky:
- Po–Pá 04:00 UTC (léto — 06:00 CEST)
- Po–Pá 05:00 UTC (zima — 06:00 CET)

`main.py` kontroluje aktuální pražský čas i zda už dnes běžel, takže email
dostaneš přesně jednou denně, vždy v 06:00 místního.

### 6) Údržba

- **state.db** — commituje se automaticky z workflow, takže paměť "co už
  bylo odesláno" přežije i když GitHub runner zmizí.
- **Selektor se rozbil** — pokud některý zdroj přestane posílat položky,
  zkontroluj, jestli nezměnili strukturu stránky. Scrapery jsou v
  `scrapers/*.py` a loguji chyby (viz Actions logy).
- **Přidání zdroje** — vytvoř `scrapers/<jmeno>.py` vracející `list[ScrapedItem]`
  a zavolej ho v `main.py`.
