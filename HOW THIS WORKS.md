# How HomeScraper works

HomeScraper checks Belgian property listings against configurable criteria and sends new matches to WhatsApp. This document describes the scraping, data, and WhatsApp parts of the system.

## System layout

```text
Immoweb ──HTTP──> Python watcher ──HTTP──> WAHA gateway ──linked device──> WhatsApp chats/groups
                         │                         │
                         ├── filters.yaml          └── persisted session files
                         └── SQLite listing and delivery records
```

Docker Compose runs two services: `watcher` and `whatsapp-gateway`. The watcher uses Python and `httpx` for asynchronous HTTP, BeautifulSoup for HTML parsing, and SQLite for state. WAHA is a separate service that maintains the WhatsApp linked-device session. Its host port is bound to `127.0.0.1`; within Compose, the watcher reaches it at `http://whatsapp-gateway:3000`.

## Scraping flow

### Search and pagination

The scan loop in `app/main.py` loads `config/filters.yaml` at the start of every scan. Enabled source adapters run concurrently. Immoweb is the implemented source; the Zimmo and Realo adapters currently return explicit errors because their public pages could not be accessed reliably during verification.

The Immoweb adapter in `app/scrapers/immoweb.py` requests the public sale search page with country, supported property type, postal codes, price bounds, and page number. The scraper reads structured JSON embedded in the page's `:results` attribute, along with the site's result count, page size, and current page. It follows pages until the reported last page, no results, or repeated listing IDs. An unexpected page number or malformed pagination is treated as an incomplete scan.

HTTP GETs are concurrency limited. Transient network errors and selected server responses (429 and 5xx) are retried up to three times with a short delay. Other HTTP errors become source errors. There is no login, CAPTCHA bypass, or browser automation.

### Normalization and detail checks

Search records are normalized into the shared `Property` model (`app/models.py`). The adapter keeps individual houses and apartments for sale, and drops records marked sold, rented, expired, removed, or under option, as well as project clusters. It maps source fields into typed values and constructs the direct listing URL.

Candidates that could match the configured criteria are fetched individually from their detail pages. Immoweb's `window.classified` data is parsed and normalized again. This confirms current availability and retrieves detail fields that may be missing from search cards. Detail failures or listings that are no longer eligible are skipped for that scan. Detail requests are also bounded in batches.

The filter engine (`app/filters.py`) evaluates the normalized fields locally. Price and postal code are also applied to the search request. Most missing values remain unknown and pass a criterion; a required feature must be explicitly true, and at least one `require_any` alternative must be confirmed true. The watcher reloads the filter file before each send as well, so a criteria edit during a long scan can prevent a stale match from being sent.

Each source failure is logged while other enabled sources may still succeed. If all enabled sources fail, the scan fails visibly; an unavailable adapter is not treated as a successful empty result.

## WhatsApp flow

### Gateway and linked session

The `whatsapp-gateway` Compose service runs WAHA Core using its GOWS engine. The session is named `default` by default. WAHA's HTTP API key is shared through `WAHA_API_KEY`; the Python client sends it in the `X-Api-Key` header. Pairing creates or starts the WAHA session, obtains a QR image, and saves it at `data/whatsapp-qr.png`. The user scans it from WhatsApp's **Linked devices** screen. Session files persist in `data/whatsapp-sessions/` across container restarts.

Before sending, the watcher checks that the session status is `WORKING`. Phone destinations are configured as international numbers. Group destinations use WhatsApp group IDs ending in `@g.us`. The sender's linked account must be in a group to send there; recipients do not need to pair devices.

### Message submission

`app/notifier.py` builds a text message from the normalized listing and its original title/description. `app/gateway.py` converts phone numbers to WhatsApp chat IDs (`...@c.us`) and submits the text to WAHA's `POST /api/sendText` endpoint with link previews enabled. The gateway uses no automatic POST retries because a timed-out submission may already have reached WhatsApp.

The periodic scan interval is configured by `CHECK_INTERVAL_MINUTES` (five minutes by default). `python -m app.main --once` runs one scan. `--dry-run` prints the messages that would be sent without contacting WhatsApp or changing SQLite. The gateway CLI also supports pairing, status checks, group discovery, and sending a test message; see `README.md` for the exact commands.

## Persistence and duplicate control

`data/listings.sqlite3` stores listings and per-recipient delivery states. A listing is keyed primarily by `(source, source_listing_id)` and secondarily by canonical URL. Seeing the same listing again updates its `last_seen` timestamp. A price change does not create a new listing or trigger a repeat alert to a recipient whose delivery was already accepted.

Before making a send request, the watcher records that recipient's state as `sending`. If WAHA returns a valid message ID, the state becomes `accepted`. A clear rejection becomes `rejected` and may be retried on a later scan, while the listing still appears and matches. A timeout or malformed response that leaves the send outcome uncertain becomes `unknown` and is not automatically retried. This avoids duplicate messages when the request may have been accepted, but can require manual inspection of WhatsApp for ambiguous cases. Gateway acceptance does not prove the recipient received or read the message.

The database is also protected by a process lock so two watchers do not use it at the same time. The linked-device session and `.env` contain private credentials and should be kept private.

## Relevant code and configuration

| Path | Responsibility |
| --- | --- |
| `app/main.py` | Scan loop, source coordination, matching, and per-recipient send lifecycle |
| `app/scrapers/base.py` | Shared asynchronous HTTP handling, concurrency limits, and transient GET retries |
| `app/scrapers/immoweb.py` | Immoweb search parsing, pagination, normalization, and detail checks |
| `app/scrapers/zimmo.py`, `app/scrapers/realo.py` | Explicit unavailable-source adapters |
| `app/models.py` | Normalized property fields and canonical URL handling |
| `app/filters.py`, `app/criteria.py` | Local filtering rules and supported criteria |
| `app/database.py` | SQLite schema and listing/delivery state updates |
| `app/notifier.py` | WhatsApp destination validation and message construction |
| `app/gateway.py` | WAHA API client, pairing, status, groups, and text sends |
| `config/filters.yaml` | Search criteria and enabled sources |
| `docker-compose.yml` | Watcher/gateway services, ports, volumes, and runtime configuration |
| `data/listings.sqlite3` | Runtime listing and delivery database |
| `data/whatsapp-sessions/` | Persistent WAHA linked-device session |

## Operational limits

The scraper consumes public website pages, not a guaranteed data feed. Site markup, result limits, network access, or anti-automation measures can change; a listing may therefore be missed or delayed. The current verified source is Immoweb. SQLite does not maintain price history or a historical sold/removed feed.

For installation, initial configuration, and exact operating commands, see [`README.md`](README.md).
