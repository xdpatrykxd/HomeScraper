# HomeScraper implementation summary

HomeScraper watches Belgian property listings, normalizes listing data, applies `config/filters.yaml`, and can deliver matches through the configured WhatsApp gateway.

## Retrieval

- Scheduled platform adapters use the shared direct HTTP client in `app/scrapers/base.py`.
- If a supported site blocks direct HTTP, the optional Tampermonkey script reads search and detail data in the user's browser and posts it to the local authenticated ingest API. It supports Immoweb, Zimmo, Realo, Immovlan, Immoscoop, and Immomarkt.
- Browser automation and Playwright have been removed from the runtime and Docker image.

## Tampermonkey ingest

- `POST /api/listings` accepts listings from the supported sites with a bearer token from `INGEST_API_TOKEN` and validates that each source matches the URL host.
- The API applies the current filters and sends qualifying properties through the existing WhatsApp delivery and deduplication flow.
- Configuration and installation steps are in `tampermonkey/README.md`.
