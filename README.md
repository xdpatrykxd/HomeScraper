# Belgian property watcher

HomeScraper monitors active Belgian homes for sale, applies YAML criteria, remembers notified matches in SQLite, and sends alerts through your own WhatsApp linked-device gateway.

```text
HomeScraper (Python) → HTTP → WAHA (Docker) → WhatsApp linked device → individual chats / your family group
```

## Run on Windows, macOS, Linux, or a VPS

Docker is the recommended setup. You do not need Python installed on the host. Supported CPUs are x86-64 and ARM64, including Apple Silicon and 64-bit Raspberry Pi installations.

### 1. Install Docker and open the project folder

| Machine | Install |
| --- | --- |
| Windows | [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/); use Linux containers. Run the commands in PowerShell. |
| macOS | [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/), choosing Apple Silicon or Intel. Run the commands in Terminal. |
| Linux / VPS | [Docker Engine](https://docs.docker.com/engine/install/) and the [Compose plugin](https://docs.docker.com/compose/install/linux/). |

Copy or extract this project into a folder named `HomeScraper`. Open a terminal in that folder. Start Docker Desktop if applicable, then check:

```bash
docker version
docker compose version
```

`docker version` must show a working server, not just a client. Keep the machine running and awake while you want alerts.

### 2. Initialize settings

**New installations only:** copy the example configuration. Do not overwrite an existing `.env`.

macOS / Linux:

```bash
cp .env.example .env
mkdir -p data
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
New-Item -ItemType Directory -Force data | Out-Null
```

Then run this command on any of those platforms:

```bash
docker run --rm -v "${PWD}:/work" -w /work python:3.12-slim python scripts/setup_env.py
```

It generates a private gateway API key and selects the gateway image for this machine's CPU. Rerunning it preserves your key, recipients, and search settings. If host Python is installed, `python3 scripts/setup_env.py` is an alternative.

Open `.env` in a text editor. Set your actual international phone numbers; the numbers below are examples to replace:

```dotenv
WHATSAPP_RECIPIENT_1=+32470123456
WHATSAPP_RECIPIENT_2=+32470987654
```

For group-only alerts, leave phone recipient variables blank and configure the group after pairing in step 4. Edit `config/filters.yaml` for your search; the supplied settings require a **terrace OR garden**.

### 3. Start the gateway and link WhatsApp

```bash
docker compose up -d whatsapp-gateway
docker compose build watcher
```

On macOS / Windows:

```bash
docker compose run --rm --no-deps watcher python -m app.gateway pair
```

On Linux / a VPS, use your user ID so you can read the saved QR file:

```bash
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" watcher python -m app.gateway pair
```

Open **`data/whatsapp-qr.png`** on another screen. On the sender's phone, choose **WhatsApp → Linked devices → Link a device**, then scan immediately. Only the sender account links to the gateway. Other recipients do not need to pair. Alerts to the sender's own number appear in its self-chat.

On a VPS, download the newly generated QR to your computer and open it there:

```bash
scp USER@SERVER:HomeScraper/data/whatsapp-qr.png .
```

Replace `USER`, `SERVER`, and the remote path as needed. A QR expires quickly; rerun `pair` and reopen the image if necessary. No public gateway port is needed.

Check the connection:

```bash
docker compose run --rm --no-deps watcher python -m app.gateway status
```

Continue when it reports **`WORKING`**. If WhatsApp shows an error but status is `WORKING` and the device is listed, it is already linked; there is no need to scan again.

### 4. Add group chats (optional)

Create a WhatsApp group with you and your wife, or use an existing group. The linked sender account must be a member and allowed to send messages. Discover its ID:

```bash
docker compose run --rm --no-deps watcher python -m app.gateway groups
```

This read-only command prints group IDs next to their names. Copy the desired ID into `.env`:

```dotenv
WHATSAPP_GROUP_IDS=120363123456789@g.us
```

**The number above is an example, not your group's ID.** Replace it with the actual numeric ID printed by the command. Copy only the ID column; do not include the group name, an invite link, angle brackets, or `YOUR_GROUP_ID`. For several groups, separate actual IDs with commas. Older IDs such as `32470123456-1234567890@g.us` are also supported.

After editing `.env`, apply it:

```bash
docker compose up -d --force-recreate watcher
```

Keep phone recipients configured to send to both individual chats and groups, or leave all phone recipient variables blank for group-only alerts. `WHATSAPP_RECIPIENTS` also accepts a comma-separated mixture of phone numbers and group IDs. Duplicate destinations receive only one alert per property.

**Adding a new destination sends all currently matching properties to that destination on its first real scan.** Previously accepted alerts to existing destinations stay remembered.

### 5. Test and start watching

The test command sends a message to **every configured phone and group**. The dry run previews property matches without sending or recording deliveries.

```bash
docker compose run --rm --no-deps watcher python -m app.main --test-whatsapp
docker compose run --rm --no-deps watcher python -m app.main --once --dry-run
docker compose up -d
docker compose logs -f watcher
```

Press Ctrl+C to leave the logs; the containers continue running. **The first real scan sends every currently matching property.** Later scans send only properties not already accepted for each destination.

### Daily operation and troubleshooting

```bash
# Stop both services; persisted data remains.
docker compose down
# Start again.
docker compose up -d
# Apply changed recipient settings from .env.
docker compose up -d --force-recreate watcher
# Apply updated Python code.
docker compose up -d --build watcher
# Inspect gateway problems.
docker compose logs --tail=100 whatsapp-gateway
```

Search criteria reload automatically before every scan. Changes to gateway settings require `docker compose up -d --force-recreate`. If port 3010 is occupied, change `WHATSAPP_GATEWAY_PORT`; also change `WHATSAPP_GATEWAY_URL` when using host Python.

If Docker cannot connect, start its daemon/Desktop and check `docker version`. An API-key rejection means the gateway and watcher need the same `WAHA_API_KEY`; recreate services after editing it. For an expired QR or failed pairing session, rerun `pair` to obtain a fresh code without deleting stored credentials. On Linux, use the user-ID pairing command above if the QR file cannot be opened. If a group is missing, confirm the linked account belongs to it; if sending is rejected, check its membership and whether only administrators may post.

If startup reports **“WhatsApp destination must be an international phone number … or a group ID …”**, check every nonempty `WHATSAPP_RECIPIENT_*`, `WHATSAPP_RECIPIENTS`, and `WHATSAPP_GROUP_IDS` value. Phones must use `+` followed by digits, without spaces or punctuation. Group IDs must be numeric IDs ending in `@g.us`, obtained from `groups`. A copied placeholder such as `YOUR_GROUP_ID@g.us` is invalid. The discovery command can still run while recipients are invalid. Correct `.env`, then recreate the watcher using the command above.

`[FILTER] 0 matching properties` means no properties passed the current criteria; it does not mean the source returned no listings. Preview with `docker compose run --rm --no-deps watcher python -m app.main --once --dry-run`. Check confirmed violations and the strict terrace/garden rule described below. Already accepted deliveries stay remembered even if you loosen the filters. Container logs use UTC by default; WhatsApp timestamps use your device's local timezone.

The gateway binds only to localhost; the watcher communicates over Docker's private network. Dashboard and Swagger are disabled because setup uses the CLI.

### Wipe the database and start over

From the project folder on macOS / Linux:

```bash
sh scripts/reset.sh --yes
```

On Windows PowerShell:

```powershell
.\scripts\reset.ps1 -Yes
```

The script builds the current watcher image, stops the watcher, removes the configured SQLite database and its journal files, then starts the watcher again. It clears remembered properties, per-destination deliveries, and cached translations. **Every currently matching property will be alerted again to every configured destination.** Any legacy translation cache is removed with the database; it is no longer used.

Your `.env`, search criteria, WhatsApp linked-device session, and messages already in WhatsApp remain intact. The gateway is not reset. If the reset fails, the script does not continue to restart the watcher; inspect the error and start it manually when resolved. Omitting `--yes` / `-Yes` prints instructions and does not reset anything.

For native Python on Linux/macOS, stop the native watcher first, then run:

```bash
python -m scripts.wipe_database --yes
python -m app.main
```

The reset refuses to run while another watcher holds the database lock. Do not delete the lock file to bypass this check. These commands wipe immediately; back up `data/listings.sqlite3` first if you want to retain the old records.

### Deploy to a VPS or move to another machine

For a **fresh installation**, transfer the project files, excluding `.env`, `.venv`, and runtime `data`. For example, create a code archive on macOS/Linux:

```bash
tar -czf homescraper-code.tar.gz app config scripts tests Dockerfile docker-compose.yml requirements.txt README.md .env.example .dockerignore .gitignore
scp homescraper-code.tar.gz USER@SERVER:
```

On the server, install Docker Engine and Compose using the links in step 1, then extract:

```bash
mkdir -p HomeScraper
tar -xzf homescraper-code.tar.gz -C HomeScraper
cd HomeScraper
```

Follow steps 2–5 on the server. All Compose commands are the same; use the Linux pairing command and download the QR as described above.

To **move an existing installation**, stop both services on the old machine first. Copy the project plus `.env`, `config`, and the entire `data` directory to the destination. This preserves `data/listings.sqlite3` (delivery records) and `data/whatsapp-sessions` (linked device). Rerun the initializer on the destination to select its CPU image, then run `docker compose up -d --build` and check gateway status. Pair again only if WhatsApp has unlinked the device. Keep the old installation stopped; do not run two copies of the same linked session.

For a backup, stop the containers and copy `.env`, `config`, and all of `data` to private storage. Keep the API key and linked-device session private. Restart with `docker compose up -d` afterward.

## Local Python 3.12+

Supported local platforms are Linux and macOS; on Windows use Docker.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# New install only:
cp .env.example .env
python3 scripts/setup_env.py
docker compose up -d whatsapp-gateway
python -m app.gateway pair
# Open data/whatsapp-qr.png and scan it from Linked devices.
python -m app.gateway status
python -m app.main --test-whatsapp
python -m app.main --once --dry-run
python -m app.main
```

`python -m app.main --once` runs one real scan. `--dry-run` prints matches repeatedly; combine it with `--once` for one preview. A dry run needs no recipient numbers, gateway key or linked device and writes nothing to SQLite. Only one sending watcher may use the same database at once.

## Search criteria

Edit `config/filters.yaml`. It reloads before every scan and is checked again immediately before each destination is sent an alert, including after message preparation. No restart is needed for criteria changes. All filters are optional; remove a key to disable it. Unknown values pass numeric bounds, allowed-value lists, and individual required/forbidden features. **`require_any` is the exception: at least one listed feature must be confirmed `true`.** For filters other than `require_any`, only a known value that violates a criterion excludes a property; unknown is never guessed as yes or no. `required.terrace: false` means “not required,” not “must have no terrace.” Price, area and bedroom thresholds are inclusive.

Supported criteria are listed in the complete [example YAML](config/filters.example.yaml). That file is a reference with all filters disabled; the watcher reads `config/filters.yaml`.

The current terrace/garden and building rules are:

```yaml
require_any: [terrace, garden]
max_building_floors: 4
forbidden:
  lift: true
```

`max_floor` limits the flat's own floor; `max_building_floors` limits Immoweb's reported building `floorCount`. A ground-floor flat in a building reporting five floors fails a four-floor building limit. We use the source count directly, without adding or subtracting a ground floor. A known flat floor above the maximum also rejects the listing, even if the building count is missing or contradictory. A reported building total below the flat’s floor is marked unknown rather than displayed as fact. A missing building floor count passes `max_building_floors`: only a known count above the cap is rejected. `min_building_floors` also allows a missing count. `forbidden.lift: true` excludes a confirmed lift; unknown lift status is allowed and remains displayed as unknown. A required lift allows unknown status too; it rejects a confirmed absence. These two criteria have been enabled in your current configuration.

For `require_any: [terrace, garden]`:

| Terrace | Garden | Result |
| --- | --- | --- |
| Yes | Yes, no, or unknown | Pass |
| No or unknown | Yes | Pass |
| No | No | Reject |
| No | Unknown | Reject |
| Unknown | No or unknown | Reject |

The detail page is checked before rejecting a candidate whose search card omitted these fields. If the detail page still confirms neither feature, no alert is sent. By contrast, an unknown lift or building height does not reject a listing. Confirmed lifts and known building floor counts above four do.

### Locations, types, and text

- `locations` and `postal_codes`: case-insensitive town names and quoted postcode strings; both apply when configured.
- `property_types`: `house`, `apartment`; an empty list allows both.
- `epc_allowed`: explicit energy labels, e.g. `[A, B, C, D]` (add `'A+'` separately if wanted).
- `include_keywords`: every nonblank phrase must appear in the original title/description.
- `exclude_keywords`: no nonblank phrase may appear in the original title/description.
- `sources`: booleans for `immoweb`, `zimmo`, `realo`; the latter two remain unimplemented placeholders.

Keyword checks are case-insensitive substring matching. They do not understand negation: “not rented” still contains “rented.” One usable original description is selected, preferring Dutch, then French, then the primary/English text. Placeholder descriptions such as `-` are ignored; different languages are never concatenated.

### Numeric ranges

Every field below supports both **`min_<field>` and `max_<field>`**, inclusive. Use `null` or omit the key to disable it. For example: `max_monthly_common_costs: 150`, `min_bathrooms: 1`, `max_building_floors: 4`. Only `floor` allows negative limits; all other limits must be nonnegative. Counts and years must be integers. A minimum larger than its maximum is rejected.

| Field | Meaning |
| --- | --- |
| `price` | Cena (€) |
| `surface_m2` | Powierzchnia (m²) |
| `price_per_m2` | Cena za m² (€/m²) |
| `bedrooms` | Sypialnie |
| `bathrooms` | Łazienki |
| `toilets` | Toalety |
| `shower_rooms` | Prysznice |
| `floor` | Piętro mieszkania |
| `building_floors` | Liczba kondygnacji budynku |
| `construction_year` | Rok budowy |
| `facades` | Liczba elewacji |
| `monthly_common_costs` | Miesięczne koszty wspólne (€) |
| `epc_value` | Zużycie energii (kWh/(m²·rok)) |
| `terrace_m2` | Powierzchnia tarasu (m²) |
| `garden_m2` | Powierzchnia ogrodu (m²) |
| `land_m2` | Powierzchnia działki (m²) |
| `living_room_m2` | Powierzchnia salonu (m²) |
| `kitchen_m2` | Powierzchnia kuchni (m²) |
| `indoor_parking_spaces` | Miejsca parkingowe wewnątrz |
| `outdoor_parking_spaces` | Miejsca parkingowe na zewnątrz |
| `closed_garage_boxes` | Zamknięte boksy garażowe |
| `habitable_units` | Liczba lokali mieszkalnych |

### Required, forbidden, or either/or features

All feature names below work in **`required`**, **`forbidden`**, and **`require_any`**:

- `required.<feature>: true`: rejects a confirmed absence; unknown passes.
- `forbidden.<feature>: true`: rejects a confirmed presence; unknown passes.
- `require_any: [terrace, garden]`: at least one alternative must be confirmed `true`. False/unknown alternatives alone do not pass. Unknown search-card values are checked on the detail page before deciding.
- `false` disables an individual requirement/prohibition; it never means the opposite.

A feature cannot be both required and forbidden. A `require_any` group whose every option is forbidden is rejected. Missing feature values pass individual required/forbidden rules, but do not satisfy `require_any`. Alerts continue to show unknown amenities as “brak danych,” not as confirmed features.

| Feature | Meaning |
| --- | --- |
| `terrace` | Taras |
| `garden` | Ogród |
| `garage` | Garaż |
| `parking` | Parking |
| `lift` | Winda |
| `balcony` | Balkon |
| `disabled_access` | Dostęp dla osób z niepełnosprawnością |
| `basement` | Piwnica |
| `attic` | Poddasze |
| `laundry_room` | Pralnia |
| `dressing_room` | Garderoba |
| `air_conditioning` | Klimatyzacja |
| `double_glazing` | Podwójne szyby |
| `heat_pump` | Pompa ciepła |
| `solar_panels` | Panele fotowoltaiczne |
| `solar_thermal_panels` | Kolektory słoneczne |
| `collective_water_heater` | Wspólny podgrzewacz wody |
| `swimming_pool` | Basen |
| `sauna` | Sauna |
| `jacuzzi` | Jacuzzi |
| `fireplace` | Kominek |
| `alarm` | Alarm |
| `armored_door` | Drzwi antywłamaniowe |
| `door_phone` | Domofon |
| `video_phone` | Wideodomofon |
| `concierge` | Portier |
| `syndicator` | Zarządca budynku |
| `heritage_protected` | Ochrona zabytkowa |
| `first_occupation` | Pierwsze zasiedlenie |
| `electrical_compliance_certificate` | Certyfikat zgodności instalacji elektrycznej |
| `asbestos_certificate` | Certyfikat azbestowy |
| `separate_electricity_meter` | Osobny licznik prądu |
| `separate_gas_meter` | Osobny licznik gazu |
| `separate_water_meter` | Osobny licznik wody |
| `construction_permit` | Pozwolenie na budowę |
| `planning_violation` | Naruszenie przepisów urbanistycznych |
| `priority_purchase_right` | Prawo pierwokupu |
| `investment_property` | Nieruchomość inwestycyjna |
| `life_annuity` | Sprzedaż dożywotnia |
| `new_build` | Nowe budownictwo |

A certificate flag means that a certificate is reported, not that the property is asbestos-free or otherwise safe. `disabled_access` reflects the advertised structured flag, not an independent accessibility assessment. There is no reliable structured field for an escalator, internal stairs, pets, neighborhood noise, or travel times; these are not guessed from descriptions or by AI.

### Allowed categorical values

Each field below has an **`<field>_allowed`** list, matched case-insensitively. An empty list disables the filter. Use the source's structured values, not translated prose. Examples: `heating_type_allowed: [GAS]`, `property_subtype_allowed: [GROUND_FLOOR]`, `flood_zone_allowed: [NON_FLOOD_ZONE]`, `flood_p_score_allowed: [A, B]`.

| Field | Meaning |
| --- | --- |
| `property_subtype` | Podtyp nieruchomości |
| `building_condition` | Stan budynku |
| `heating_type` | Rodzaj ogrzewania |
| `kitchen_type` | Rodzaj kuchni |
| `garden_orientation` | Orientacja ogrodu |
| `terrace_orientation` | Orientacja tarasu |
| `flood_zone` | Strefa zagrożenia powodziowego |
| `flood_p_score` | Ocena powodziowa działki |
| `flood_g_score` | Ocena powodziowa budynku |
| `province` | Prowincja |
| `district` | Okręg |
| `region` | Region |

Unknown or `NOT_SPECIFIED` categorical source values remain unknown. Source labels can change; the example YAML lists filter names, not a promise that every property provides every value. All expanded criteria are checked locally after applying the postal-code/price request constraints. Incomplete fields pass filters; confirmed contradictory values still exclude a listing. If no description is available, unmet include-keyword checks pass, while excluded phrases found in the available title still reject the listing.

City and postal-code filters both apply when both are present. The current configuration uses its postcode list as the search area (`locations: []`), up to €170,000, at least 55 m² and one bedroom, EPC A–D, with a **confirmed terrace or garden**. It excludes confirmed lifts and known building floor counts or flat floors above four; other missing values pass. Studios are classified under `apartment`; studios reporting zero bedrooms still fail `min_bedrooms: 1`. Edit `config/filters.yaml` to change these settings.

**Keep postal codes set for a fast local search.** Postal codes and price constraints are sent to Immoweb; all criteria are also checked locally. City-only searches currently scan nationwide results then filter locally, which can be expensive and encounter the site's result limits. Explicitly update/remove postal codes when changing towns.

Garage is interpreted conservatively as a closed parking box, not merely an indoor parking space. Parking counts outside 0–100 per advertised dwelling, fractional counts, and malformed values are treated as unknown. A value such as `1974` is not reinterpreted as a construction year. Known structured category codes are displayed in Polish; unsupported display codes are omitted rather than guessed. Missing amenity fields remain unknown; the scraper does not infer features from marketing prose.

## Source status

Immoweb was last checked with a live scan on 2 October 2026 from this development machine. Zimmo and Realo statuses below reflect the initial access checks on 1 October 2026.

| Source | Status | Implementation |
| --- | --- | --- |
| Immoweb | Working, live dry run verified | JSON embedded in public search attributes and `window.classified` detail data. Postal-code/price search, automatic pagination, detail availability checks for every candidate. |
| Zimmo | Disabled placeholder | Public search returned a Cloudflare browser challenge; no reliable unattended parser verified. |
| Realo | Disabled placeholder | Public search returned HTTP 403; no reliable public data parser verified. |

Enabling a placeholder logs a clear source error; it does not pretend to return zero properties. One failed source does not stop other sources. If all sources fail, the scan fails visibly. `--once` exits nonzero for a failed source or a rejected/uncertain send. Continuous mode logs errors and retries on the next scan.

The Immoweb parser uses current sale search results, excludes under-option, sold/rented, and explicit inactive flags and project clusters. Every candidate that passes the known search criteria is checked against its detail page before it can generate an alert, even when the search card already contains all criteria. This catches availability changes that search cards have not yet reflected. Detail failures skip that candidate for this scan. Pagination stops at the site's reported last page, empty results, or repeated results. Unexpected redirects/page numbers fail the scan rather than claiming complete coverage. Public websites may impose search caps, change markup, or block your VPS; this is not a guaranteed data feed. No CAPTCHA bypass or login is implemented. Search results can change during pagination and newly inserted properties will be found again on later scans.

Match counts change with listings and your criteria; there is no expected fixed number of matches. Fixtures are reduced snapshots of real public data with customer contact information excluded; they are test data, not a historical property database.

## Gateway configuration

The implementation uses the free WAHA Core HTTP API with its GOWS engine. One `default` session sends to individual chats and groups. There are no provider account credentials, sender API numbers, paid message templates, or template approval steps in HomeScraper.

| Variable | Purpose |
| --- | --- |
| `WAHA_API_KEY` | Shared private key generated by `scripts/setup_env.py`; sent as `X-Api-Key`. |
| `WAHA_IMAGE` | `devlikeapro/waha:noweb` for x86 servers; `devlikeapro/waha:noweb-arm` for ARM/Apple Silicon. |
| `WHATSAPP_GATEWAY_ENGINE` | `GOWS` by default. The browserless `noweb` images also include GOWS; the image tag does not fix the running engine. |
| `WHATSAPP_GATEWAY_PORT` | Host-local gateway port, default `3010`. |
| `WHATSAPP_GATEWAY_URL` | Host Python URL, default `http://127.0.0.1:3010`. Compose overrides it with `http://whatsapp-gateway:3000`. |
| `WHATSAPP_SESSION` | `default` for the free single-session gateway. |
| `WHATSAPP_GATEWAY_TIMEOUT_SECONDS` | HTTP timeout for the gateway, default `60`. |
| `WHATSAPP_RECIPIENT_1`, `WHATSAPP_RECIPIENT_2` | International phone numbers, e.g. `+32470123456`. |
| `WHATSAPP_RECIPIENTS` | Optional comma-separated phone numbers and group IDs; you can also add numbered variables. |
| `WHATSAPP_GROUP_IDS` | Optional comma-separated group IDs ending in `@g.us`. |

The legacy `whatsapp:+32...` phone notation remains accepted. Numbers are converted to WAHA chat IDs (`32...@c.us`) when sending and are deduplicated across input forms. Existing SQLite delivery recipient keys retain their identity.

After changing `.env`, recreate services: `docker compose up -d --force-recreate`. If changing the port for local Python, update both `WHATSAPP_GATEWAY_PORT` and `WHATSAPP_GATEWAY_URL`. `setup_env.py` chooses the image for the machine where you run it; rerun it on the destination VPS or set `WAHA_IMAGE` explicitly if moving between ARM and x86. The default image tags follow WAHA updates; you can set a version-specific tag or digest in `WAHA_IMAGE` for reproducible deployment.

Notifications use `POST /api/sendText`. They contain expanded Polish facts, the original-language title/description, and the direct listing URL. No AI service is involved. Link previews are enabled when WhatsApp can generate them. Listing images are not separately uploaded; the free Core deployment is configured for text alerts.

Pairing normally survives container restarts through the session volume. If WhatsApp unlinks the device, run `pair` again. WAHA is a linked-device integration, so its connection behavior follows WhatsApp Web rather than an official business messaging API.

Official references: [quick start](https://waha.devlike.pro/docs/overview/quick-start/), [sessions and QR authentication](https://waha.devlike.pro/docs/how-to/sessions/), [text message API](https://waha.devlike.pro/docs/how-to/send-messages/), [group API](https://waha.devlike.pro/docs/how-to/groups/), [session storage](https://waha.devlike.pro/docs/how-to/storages/).

## Polish alerts without AI

Alerts always use Polish labels and deterministic Polish names for known structured category codes. Numeric property facts come directly from the scraped fields and are never rewritten by a language model. Prices per m² use two decimal places where needed. Missing terrace, garden, garage, parking, and lift values are displayed as **“brak danych”**.

The listing title and one usable description stay in the original language. Descriptions are labelled **“Opis ogłoszenia (język oryginalny)”**. Dutch descriptions are preferred, then French, then usable primary/English text. Placeholder descriptions such as `-` are omitted. Languages are not concatenated.

**There is no AI translation and no OpenRouter request.** No AI API key is needed. Legacy `OPENROUTER_*` variables are ignored and can be removed from `.env`; old cached translations are not used. Existing delivery records remain intact, so this change does not resend accepted alerts.

A dry run previews the same Polish facts and original-language prose without sending or writing to SQLite. Text over 60,000 characters is deferred without truncation and logged as a notification error.

## Delivery and deduplication

SQLite primarily identifies a property by `(source, source_listing_id)` and falls back to its canonical URL. It records first/last seen for matches and a separate delivery state for each recipient. A seen match refreshes `last_seen`; changing its price does not trigger another accepted notification. Listings from different portals are not fuzzy-deduplicated.

Gateway acceptance is recorded immediately so a failure for one recipient cannot resend to the other. Explicit rejected requests or failures to establish a connection may retry on the next scan **only if the property still appears and matches**. There is no offline queue that sends disappeared listings.

A successful gateway response with a message ID is acceptance, not proof of recipient delivery. Network failures during submission and malformed/ambiguous responses may mean the message was already sent. To avoid repeat alerts, `sending` and `unknown` records are not automatically retried. Exactly-once delivery across an HTTP API and SQLite cannot be guaranteed; this conservative behavior can miss an alert in an ambiguous failure. Check the actual WhatsApp chat before resetting a delivery.

Inspect uncertain deliveries on the host:

```bash
python3 - <<'PY'
import sqlite3
with sqlite3.connect('data/listings.sqlite3') as db:
    for row in db.execute("SELECT listing_id,recipient,state,sid FROM deliveries WHERE state IN ('sending','unknown')"):
        print(row)
PY
```

The existing `sid` database column now stores the gateway message ID; its name is retained to preserve existing databases. Stop the watcher before manually resolving a record. If definitely not sent, change only that record to `rejected` in a SQLite client; the next matching active scan may retry it. If sent, change it to `accepted`. Do not erase the whole database to retry a single recipient.

## Runtime and verification

- `CHECK_INTERVAL_MINUTES=5`: delay after completing each scan.
- `REQUEST_CONCURRENCY=4`: bounded scraper HTTP concurrency, 1–16.
- `REQUEST_TIMEOUT_SECONDS=25`: scraper request timeout.
- `FILTERS_PATH=config/filters.yaml`, `DATABASE_PATH=data/listings.sqlite3`.

Sources run concurrently and detail requests are bounded. Search pagination is sequential. Scraper GETs use up to three attempts for transient failures; notification POSTs have no automatic retries. No sold/removed tracking or price histories are stored.

```bash
python -m unittest discover -s tests -v
# Or inside the watcher image:
docker compose run --rm --no-deps watcher python -m unittest discover -s tests -v
docker compose config --quiet
```

Offline tests cover Polish formatting, original-language descriptions without AI requests, inconsistent building floor counts, placeholder descriptions, implausible parking counts, category labels, under-option/sold flags, stale search-card availability, filtering, terrace-or-garden behavior, parsing, pagination, message formatting, phone/group payloads and authentication, paginated group discovery, mixed-destination deduplication, QR setup, disconnected-session handling, per-recipient failures, and suppression of ambiguous-send retries. Gateway requests in tests are mocked. Actual linked-device delivery needs your phone to scan the QR and a running Docker daemon.

## Project tree

```text
HomeScraper/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── filters.py
│   ├── criteria.py
│   ├── polish.py
│   ├── models.py
│   ├── notifier.py
│   ├── gateway.py
│   └── scrapers/
│       ├── __init__.py
│       ├── base.py
│       ├── immoweb.py
│       ├── zimmo.py
│       └── realo.py
├── config/
│   ├── filters.yaml
│   └── filters.example.yaml
├── data/
│   ├── .gitkeep
│   ├── listings.sqlite3       # Runtime
│   ├── whatsapp-qr.png       # Pairing command
│   └── whatsapp-sessions/    # Persisted linked device
├── scripts/
│   ├── setup_env.py
│   ├── wipe_database.py
│   ├── reset.sh
│   └── reset.ps1
├── tests/
│   ├── test_watcher.py
│   ├── test_gateway.py
│   ├── test_notifications.py
│   ├── test_reset.py
│   ├── test_extended_filters.py
│   └── fixtures/
│       ├── immoweb-search.html
│       ├── immoweb-detail.html
│       └── immoweb-inconsistent-floor.html
├── .env                      # Local, ignored
├── .env.example
├── .gitignore
├── .dockerignore
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```
