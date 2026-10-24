# Tampermonkey Immoweb sender

This is a browser-assisted fallback for Immoweb when the direct HTTP adapter is blocked. The normal watcher continues to use direct HTTP for enabled sources. This script reads listing data from the Immoweb page you open and submits it to HomeScraper's authenticated ingest API.

## Configure the API

Add a long random secret and your regular WhatsApp settings to `.env`:

```env
INGEST_API_TOKEN=replace-with-a-long-random-secret
INGEST_API_HOST=127.0.0.1
INGEST_API_PORT=8787
WAHA_API_KEY=your-gateway-key
WHATSAPP_RECIPIENTS=+32470111111
```

Run HomeScraper with `python -m app.main`. The API listens only on loopback by default at `http://127.0.0.1:8787/api/listings`. With an ingest token configured, the watcher enables the API and continues its normal scheduled HTTP scans. Listings submitted by the script are deduplicated, checked against `config/filters.yaml`, and sent through the existing WhatsApp gateway.

## Install the userscript

1. Open Tampermonkey and choose **Create a new script**.
2. Replace the editor contents with `homescraper-immoweb.user.js` and save.
3. In that file, replace `REPLACE_WITH_INGEST_API_TOKEN` with the same token as `INGEST_API_TOKEN`.
4. Open an Immoweb search results page. The script submits listing cards it can read from the page.

The script uses `GM_xmlhttpRequest`, which allows a userscript to post to the local API across browser origins. Keep the API bound to loopback unless you have configured a trusted HTTPS reverse proxy. Do not expose the token in a public API endpoint or share the userscript after inserting your token.

The Immoweb page structure can change. The script prefers embedded search result JSON and falls back to listing links for IDs and URLs; fields missing from search cards remain unknown, so configured filters can reject listings that do not contain enough information.
