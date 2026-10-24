// ==UserScript==
// @name         HomeScraper Immoweb sender
// @namespace    local.homescraper
// @version      1.0.0
// @description  Send visible Immoweb search listings to your HomeScraper API
// @match        https://www.immoweb.be/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @connect      localhost
// @connect      www.immoweb.be
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  // Set this to the bearer token configured as INGEST_API_TOKEN in HomeScraper's .env.
  const API_URL = 'http://127.0.0.1:8787/api/listings';
  const API_TOKEN = 'REPLACE_WITH_INGEST_API_TOKEN';

  function first(...values) {
    return values.find(value => value !== undefined && value !== null && value !== '') ?? null;
  }

  function number(value) {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string') {
      const parsed = Number(value.replace(/[^\d.,-]/g, '').replace(',', '.'));
      return Number.isFinite(parsed) ? parsed : null;
    }
    return null;
  }

  function bool(value) {
    return typeof value === 'boolean' ? value : null;
  }

  function cardListing(card) {
    const id = String(first(card.id, card.classified?.id, card.property?.id, card.guid) ?? '');
    if (!id) return null;
    const property = card.property ?? card;
    const tx = card.transaction ?? {};
    const location = property.location ?? card.location ?? {};
    const sale = tx.sale ?? {};
    const cert = tx.certificates ?? {};
    const pictures = card.media?.pictures ?? [];
    const kind = String(first(property.type, card.propertyType, 'apartment')).toLowerCase();
    const city = first(location.locality, location.city);
    const postal = first(location.postalCode, location.postal_code);
    const url = `https://www.immoweb.be/en/classified/${kind}/for-sale/${encodeURIComponent(String(city ?? 'belgium').toLowerCase())}/${postal ?? '0000'}/${encodeURIComponent(id)}`;
    const data = {
      source_listing_id: id,
      url: first(card.url, card.detailUrl, url),
      title: first(property.title, card.title, `${kind} in ${city ?? 'Belgium'}`),
      address: [location.street, location.number, location.box].filter(Boolean).join(' ') || null,
      postal_code: postal == null ? null : String(postal),
      city,
      price: number(first(sale.price, card.price?.mainValue, card.price)),
      surface_m2: number(first(property.netHabitableSurface, property.surface, card.surface)),
      bedrooms: number(first(property.bedroomCount, card.bedroomCount)),
      bathrooms: number(first(property.bathroomCount, card.bathroomCount)),
      property_type: kind,
      epc: first(cert.epcScore, tx.certificate, card.epc),
      epc_value: number(cert.primaryEnergyConsumptionPerSqm),
      terrace: bool(property.hasTerrace),
      terrace_m2: number(property.terraceSurface),
      garden: bool(property.hasGarden),
      garden_m2: number(property.gardenSurface),
      garage: null,
      parking: null,
      lift: bool(property.hasLift),
      floor: number(location.floor),
      description: first(property.description, property.salesPitch?.text, card.description),
      image_url: first(pictures[0]?.largeUrl, pictures[0]?.mediumUrl, card.image),
    };
    return data.url && data.url.startsWith('https://www.immoweb.be/') ? data : null;
  }

  function findListings() {
    const found = new Map();
    for (const node of document.querySelectorAll('[\\:results], [data-results]')) {
      const raw = node.getAttribute(':results') ?? node.getAttribute('data-results');
      if (!raw) continue;
      try {
        const parsed = JSON.parse(raw.replaceAll('&quot;', '"').replaceAll('&amp;', '&'));
        const rows = Array.isArray(parsed) ? parsed : parsed.listings;
        if (Array.isArray(rows)) rows.forEach(row => {
          const listing = cardListing(row);
          if (listing) found.set(listing.source_listing_id, listing);
        });
      } catch (_) { /* Ignore unrelated page attributes. */ }
    }
    for (const anchor of document.querySelectorAll('a[href*="/classified/"]')) {
      const match = anchor.href.match(/\/classified\/[^/]+\/for-sale\/[^/]+\/[^/]+\/(\d+)/);
      if (!match || found.has(match[1])) continue;
      const card = anchor.closest('article, [data-testid], li, [class*="card"], [class*="Card"]') ?? anchor.parentElement;
      const text = card?.innerText ?? anchor.innerText ?? '';
      const price = text.match(/(?:€\s*)?([\d. ]{4,})\s*€/);
      const surface = text.match(/([\d.,]+)\s*m²/i);
      const beds = text.match(/(\d+)\s*(?:bedroom| slaapkamer| chambre)/i);
      const image = card?.querySelector('img')?.src ?? null;
      found.set(match[1], {
        source_listing_id: match[1], url: anchor.href,
        title: anchor.innerText.trim() || text.split('\n').map(s => s.trim()).find(Boolean) || null,
        price: price ? number(price[1]) : null,
        surface_m2: surface ? number(surface[1]) : null,
        bedrooms: beds ? number(beds[1]) : null,
        image_url: image,
      });
    }
    return [...found.values()];
  }

  function detailListing(listing, html) {
    const match = html.match(/window\.classified\s*=\s*/);
    if (!match) return listing;
    let data;
    const jsonText = html.slice(match.index + match[0].length).match(/^\s*(\{[\s\S]*\})\s*;/);
    try { data = jsonText ? JSON.parse(jsonText[1]) : null; }
    catch (_) { return listing; }
    const p = data.property ?? {};
    const loc = p.location ?? {};
    const tx = data.transaction ?? {};
    const sale = tx.sale ?? {};
    const cert = tx.certificates ?? {};
    const counts = [p.parkingCountIndoor, p.parkingCountOutdoor, p.parkingCountClosedBox];
    const knownCounts = counts.filter(v => Number.isFinite(v));
    return {
      ...listing,
      title: first(p.title, listing.title),
      address: [loc.street, loc.number, loc.box].filter(Boolean).join(' ') || listing.address,
      postal_code: loc.postalCode == null ? listing.postal_code : String(loc.postalCode),
      city: first(loc.locality, listing.city),
      price: number(first(sale.price, data.price?.mainValue, listing.price)),
      surface_m2: number(first(p.netHabitableSurface, listing.surface_m2)),
      bedrooms: number(first(p.bedroomCount, listing.bedrooms)),
      bathrooms: number(first(p.bathroomCount, listing.bathrooms)),
      property_type: String(first(p.type, listing.property_type, 'apartment')).toLowerCase(),
      epc: first(cert.epcScore, tx.certificate, listing.epc),
      epc_value: number(cert.primaryEnergyConsumptionPerSqm),
      terrace: bool(p.hasTerrace) ?? (Number(p.terraceSurface) > 0 ? true : null),
      terrace_m2: number(p.terraceSurface),
      garden: bool(p.hasGarden) ?? (Number(p.gardenSurface) > 0 ? true : null),
      garden_m2: number(p.gardenSurface),
      garage: Number.isFinite(p.parkingCountClosedBox) ? p.parkingCountClosedBox > 0 : null,
      parking: knownCounts.some(v => v > 0) ? true : (knownCounts.length === 3 ? false : null),
      lift: bool(p.hasLift), floor: number(loc.floor),
      description: first(p.alternativeDescriptions?.nl, p.alternativeDescriptions?.fr, p.description, listing.description),
    };
  }

  function send(listing) {
    GM_xmlhttpRequest({
      method: 'POST', url: API_URL,
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${API_TOKEN}` },
      data: JSON.stringify({ listing }),
      onload: response => console.info('[HomeScraper]', listing.source_listing_id, response.status, response.responseText),
      onerror: error => console.error('[HomeScraper] API request failed', error),
    });
  }

  const listings = findListings();
  listings.forEach((listing, index) => {
    // Fetch the detail page through the user's browser to fill in fields that
    // Immoweb omits from search cards. Throttle requests to avoid hammering it.
    setTimeout(() => GM_xmlhttpRequest({
      method: 'GET', url: listing.url,
      onload: response => send(detailListing(listing, response.responseText)),
      onerror: () => send(listing),
    }), index * 900);
  });
  console.info(`[HomeScraper] Sent ${listings.length} Immoweb listings to the local API.`);
})();
