# HomeScraper Tampermonkey fallback

The scheduled watcher tries direct HTTP first. When a property site blocks direct requests, install this userscript in Tampermonkey and open its search results in your browser. It supports Immoweb, Zimmo, Realo, Immovlan, Immoscoop, and Immomarkt. It reads listing cards and, when possible, listing detail pages through the browser, then submits them to HomeScraper's authenticated API.

## Configure the API

Set a private token and your WhatsApp gateway settings in `.env`:

```env
INGEST_API_TOKEN=replace-with-a-long-random-secret
INGEST_API_HOST=127.0.0.1
INGEST_API_PORT=8787
WAHA_API_KEY=your-gateway-key
WHATSAPP_RECIPIENTS=+32470111111
```

Run HomeScraper with `python -m app.main`. The API listens on `http://127.0.0.1:8787/api/listings`. Submitted listings are checked against `config/filters.yaml`, deduplicated, and sent through the existing WhatsApp gateway.

## Install

1. Open Tampermonkey and choose **Create a new script**.
2. Copy the contents of `homescraper.user.js` into the editor and save.
3. Replace `REPLACE_WITH_INGEST_API_TOKEN` with the same token from `.env`.
4. Open any page on one of the supported property sites. The script reads the enabled sources and filters from the watcher, opens a filtered sale search for each enabled site in the same tab, scrolls the results, visits each listing, and follows result pagination (up to 100 pages per site).

The script uses `GM_xmlhttpRequest` only for its authenticated local API calls. It navigates the visible tab through site search results and details, scrolling the rendered pages as it goes. It uses common filter URL parameters; each portal may support a different subset, and the watcher still applies every filter before sending. The API binds to loopback by default. Do not expose it publicly or share a userscript containing your token. Listing page structures differ and can change; missing fields remain unknown and may cause the configured filters to reject a listing.
