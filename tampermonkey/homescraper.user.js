// ==UserScript==
// @name         HomeScraper property sender
// @namespace    local.homescraper
// @version      3.0.0
// @description  Send listings from supported Belgian property sites to HomeScraper
// @match        https://*.immoweb.be/*
// @match        https://immoweb.be/*
// @match        https://*.zimmo.be/*
// @match        https://zimmo.be/*
// @match        https://*.realo.be/*
// @match        https://realo.be/*
// @match        https://*.immovlan.be/*
// @match        https://immovlan.be/*
// @match        https://*.immoscoop.be/*
// @match        https://immoscoop.be/*
// @match        https://*.immomarkt.be/*
// @match        https://immomarkt.be/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @connect      localhost
// @connect      immoweb.be
// @connect      zimmo.be
// @connect      realo.be
// @connect      immovlan.be
// @connect      immoscoop.be
// @connect      immomarkt.be
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  const API_URL = 'http://127.0.0.1:8787/api/listings';
  const API_TOKEN = 'REPLACE_WITH_INGEST_API_TOKEN';
  const DOMAINS = {
    'immoweb.be': 'immoweb', 'zimmo.be': 'zimmo', 'realo.be': 'realo',
    'immovlan.be': 'immovlan', 'immoscoop.be': 'immoscoop', 'immomarkt.be': 'immomarkt',
  };
  const domain = Object.keys(DOMAINS).find(host => location.hostname === host || location.hostname.endsWith(`.${host}`));
  if (!domain) return;
  const source = DOMAINS[domain];

  const first = (...values) => values.find(value => value !== undefined && value !== null && value !== '') ?? null;
  function number(value) {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value !== 'string') return null;
    const cleaned = value.replace(/[^\d,.-]/g, '').replace(/\.(?=\d{3}(?:\D|$))/g, '').replace(',', '.');
    const parsed = Number(cleaned);
    return Number.isFinite(parsed) ? parsed : null;
  }
  function priceFromText(text) {
    const amount = '(?:\\d{1,3}(?:[.\\s\\u00a0\\u202f]\\d{3})+|\\d{4,})(?:,\\d{1,2})?';
    const prefix = text.match(new RegExp(`(?:€|EUR)\\s*(${amount})`, 'i'));
    const suffix = prefix ? null : text.match(new RegExp(`(${amount})\\s*(?:€|EUR)`, 'i'));
    const value = prefix?.[1] ?? suffix?.[1];
    const parsed = number(value);
    // Residential listing cards sometimes put the surface/bedroom number
    // beside a currency marker. Reject implausibly small amounts as bad parses.
    return parsed !== null && parsed >= 10000 ? parsed : null;
  }
  function titleOrNull(value) {
    const title = typeof value === 'string' ? value.trim() : '';
    return title && !/^(?:apartment|appartement|house|huis|woning|maison)\s+(?:for sale|te koop|à vendre)$/i.test(title) ? title : null;
  }
  function pathId(url) {
    const parts = new URL(url).pathname.split('/').filter(Boolean);
    const last = parts.at(-1) ?? '';
    if (/^(page|zoeken|search|te-koop|for-sale|appartement|huis|woning)$/i.test(last)) return '';
    return (last.match(/\d{4,}|[A-Z]{2,}\d{2,}/i) ?? [last])[0];
  }
  function listingUrl(raw, baseUrl = location.href) {
    try {
      const url = new URL(raw, baseUrl);
      if (url.protocol !== 'https:' || !Object.keys(DOMAINS).some(d => url.hostname === d || url.hostname.endsWith(`.${d}`))) return null;
      return url.href;
    } catch (_) { return null; }
  }
  function parseCard(anchor, baseUrl) {
    const url = listingUrl(anchor.getAttribute('href') || anchor.href, baseUrl);
    if (!url) return null;
    const id = pathId(url);
    if (!id || id.length < 4) return null;
    const card = anchor.closest('article, li, [data-testid], [class*="card"], [class*="Card"], [class*="result"], [class*="Result"]') ?? anchor.parentElement;
    const text = (card?.innerText ?? anchor.innerText ?? '').replace(/\s+/g, ' ').trim();
    if (!text || text.length < 8) return null;
    const areaMatch = text.match(/([\d.,]+)\s*m(?:²|2)/i);
    const bedsMatch = text.match(/(\d+)\s*(?:slaapkamers?|chambres?|bedrooms?)/i);
    const postMatch = text.match(/\b([1-9]\d{3})\b/);
    const image = card?.querySelector('img')?.src ?? null;
    const kindText = `${anchor.innerText} ${text}`.toLowerCase();
    const propertyType = /huis|house|maison|villa/.test(kindText) ? 'house' : /appartement|apartment|appart/.test(kindText) ? 'apartment' : null;
    return {
      source, source_listing_id: id, url,
      title: titleOrNull(anchor.innerText.trim()),
      postal_code: postMatch?.[1] ?? null,
      price: priceFromText(text),
      surface_m2: number(areaMatch?.[1]), bedrooms: number(bedsMatch?.[1]),
      property_type: propertyType, image_url: image,
    };
  }
  function extractObjects(value, out = []) {
    if (!value || typeof value !== 'object') return out;
    if (Array.isArray(value)) { value.forEach(item => extractObjects(item, out)); return out; }
    if (value['@type'] && (/Residence|House|Apartment|Product|Offer|RealEstateListing/i.test(String(value['@type'])))) out.push(value);
    Object.values(value).forEach(item => extractObjects(item, out));
    return out;
  }
  function detailData(html, listing) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    if (source === 'immoweb') {
      const marker = html.match(/window\.classified\s*=\s*/);
      const jsonText = marker && html.slice(marker.index + marker[0].length).match(/^\s*(\{[\s\S]*?\})\s*;/);
      if (jsonText) {
        try {
          const classified = JSON.parse(jsonText[1]);
          const p = classified.property ?? {};
          const loc = p.location ?? {};
          const tx = classified.transaction ?? {};
          const sale = tx.sale ?? {};
          const cert = tx.certificates ?? {};
          const prices = classified.price ?? {};
          const pictures = classified.media?.pictures ?? [];
          const counts = [p.parkingCountIndoor, p.parkingCountOutdoor, p.parkingCountClosedBox];
          const knownCounts = counts.filter(value => Number.isFinite(value));
          const type = String(p.type ?? '').toLowerCase();
          return {
            ...listing,
            title: titleOrNull(first(p.title, listing.title)),
            description: first(p.alternativeDescriptions?.nl, p.alternativeDescriptions?.fr, p.description, p.salesPitch?.text, listing.description),
            address: [loc.street, loc.number, loc.box].filter(Boolean).join(' ') || listing.address,
            city: first(loc.locality, listing.city),
            postal_code: loc.postalCode == null ? listing.postal_code : String(loc.postalCode),
            price: tx.hidePrice || prices.hidePrice ? null : number(first(sale.price, prices.mainValue, listing.price)),
            surface_m2: number(p.netHabitableSurface) ?? listing.surface_m2,
            bedrooms: number(p.bedroomCount) ?? listing.bedrooms,
            bathrooms: number(p.bathroomCount),
            property_type: type === 'house' ? 'house' : type === 'apartment' ? 'apartment' : listing.property_type,
            epc: first(cert.epcScore, tx.certificate),
            epc_value: number(cert.primaryEnergyConsumptionPerSqm),
            terrace: typeof p.hasTerrace === 'boolean' ? p.hasTerrace : (number(p.terraceSurface) > 0 ? true : null),
            terrace_m2: number(p.terraceSurface),
            garden: typeof p.hasGarden === 'boolean' ? p.hasGarden : (number(p.gardenSurface) > 0 ? true : null),
            garden_m2: number(p.gardenSurface),
            garage: Number.isFinite(p.parkingCountClosedBox) ? p.parkingCountClosedBox > 0 : null,
            parking: knownCounts.some(value => value > 0) ? true : (knownCounts.length === 3 ? false : null),
            lift: typeof p.hasLift === 'boolean' ? p.hasLift : null,
            floor: number(loc.floor), building_floors: number(p.building?.floorCount),
            image_url: first(pictures[0]?.largeUrl, pictures[0]?.mediumUrl, listing.image_url),
          };
        } catch (_) { /* fall back to JSON-LD below */ }
      }
    }
    const all = [];
    for (const node of doc.querySelectorAll('script[type="application/ld+json"]')) {
      try { extractObjects(JSON.parse(node.textContent), all); } catch (_) { /* malformed or unrelated JSON-LD */ }
    }
    const ld = all.find(item => /Residence|House|Apartment|Product|RealEstateListing/i.test(String(item['@type']))) ?? {};
    const offers = ld.offers ?? {};
    const address = ld.address ?? {};
    const geoAddress = address.address ?? address;
    const text = doc.body?.innerText ?? '';
    const price = first(offers.price, ld.price, priceFromText(text));
    const livingArea = ld.floorSize?.value ?? ld.floorSize;
    const beds = first(ld.numberOfBedrooms, ld.numberOfRooms);
    const pcode = first(geoAddress.postalCode, text.match(/\b([1-9]\d{3})\s+[A-ZÀ-ÿ]/i)?.[1]);
    const description = first(ld.description, doc.querySelector('meta[name="description"]')?.content, '');
    function explicitFeature(terms) {
      const regex = new RegExp(`(?:${terms})(?:\\s+[^.\\n]{0,50})?`, 'i');
      const found = regex.exec(description);
      if (!found) return null;
      const before = description.slice(Math.max(0, found.index - 25), found.index);
      return /(?:geen|niet|zonder|no|without|sans|pas de)\s*$/i.test(before) ? false : true;
    }
    const terrace = explicitFeature('terras|terrace|terrasse|balcon|balcony');
    const garden = explicitFeature('tuin|garden|jardin');
    const epc = text.match(/(?:EPC|PEB|EPB)\s*[:\-]?\s*(A\+{0,2}|A|B|C|D|E|F|G)\b/i)?.[1]?.toUpperCase();
    return {
      ...listing,
      title: titleOrNull(first(ld.name, doc.querySelector('h1')?.innerText, listing.title)),
      description: first(description, null),
      city: first(geoAddress.addressLocality, geoAddress.city),
      address: first(geoAddress.streetAddress),
      postal_code: pcode == null ? listing.postal_code : String(pcode),
      price: number(price) !== null && number(price) >= 10000 ? number(price) : priceFromText(text), surface_m2: number(livingArea) ?? listing.surface_m2,
      bedrooms: number(beds) ?? listing.bedrooms,
      property_type: first(/house|woning|maison/i.test(String(ld['@type'])) ? 'house' : /apartment|flat/i.test(String(ld['@type'])) ? 'apartment' : null, listing.property_type),
      epc: first(ld.energyEfficiencyScaleMin, epc),
      terrace, garden,
      image_url: first(Array.isArray(ld.image) ? ld.image[0] : ld.image, listing.image_url),
    };
  }
  function request(method, url, options = {}) {
    return new Promise((resolve, reject) => GM_xmlhttpRequest({
      method, url, timeout: 30000, ...options,
      onload: response => response.status >= 200 && response.status < 300 ? resolve(response) : reject(new Error(`HTTP ${response.status}`)),
      onerror: reject, ontimeout: () => reject(new Error('request timed out')),
    }));
  }
  function pageListings(doc, pageUrl) {
    const found = new Map();
    for (const anchor of doc.querySelectorAll('a[href]')) {
      const listing = parseCard(anchor, pageUrl);
      if (listing && !found.has(listing.source_listing_id)) found.set(listing.source_listing_id, listing);
    }
    return [...found.values()];
  }
  function nextPage(doc, currentUrl) {
    const candidates = [...doc.querySelectorAll('a[href]')];
    const next = candidates.find(a => a.rel?.toLowerCase().split(/\s+/).includes('next') ||
      /next|volgende|suivant|suivante/i.test(`${a.innerText} ${a.getAttribute('aria-label')} ${a.title}`) ||
      /^(›|»|→)$/i.test((a.innerText || '').trim()));
    if (next) {
      const url = listingUrl(next.getAttribute('href'), currentUrl);
      if (url && url !== currentUrl) return url;
    }
    const current = new URL(currentUrl);
    const currentPage = Number(current.searchParams.get('page') || current.searchParams.get('pagina') || current.searchParams.get('p'));
    if (Number.isInteger(currentPage) && currentPage > 0) {
      const numbered = candidates.find(a => (a.innerText || '').trim() === String(currentPage + 1));
      if (numbered) {
        const url = listingUrl(numbered.getAttribute('href'), currentUrl);
        if (url && url !== currentUrl) return url;
      }
      const pageKey = ['page', 'pagina', 'p'].find(key => current.searchParams.has(key));
      if (pageKey && doc.querySelector('a[rel="next"], [class*="pagination"], [class*="Pagination"]')) {
        current.searchParams.set(pageKey, String(currentPage + 1));
        return current.href;
      }
    }
    return null;
  }
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  async function submitListing(listing) {
    try {
      const response = await request('GET', listing.url);
      listing = detailData(response.responseText, listing);
    } catch (error) {
      console.warn('[HomeScraper] Detail fetch failed; submitting card fields', listing.source_listing_id, error);
    }
    try {
      const response = await request('POST', API_URL, {
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${API_TOKEN}` },
        data: JSON.stringify({ listing }),
      });
      console.info('[HomeScraper]', source, listing.source_listing_id, response.status, response.responseText);
    } catch (error) {
      console.error('[HomeScraper] API request failed', error);
    }
  }
  async function crawl() {
    let currentUrl = location.href;
    const seenPages = new Set();
    const seenListings = new Set();
    let pageCount = 0;
    while (currentUrl && !seenPages.has(currentUrl) && pageCount < 100) {
      seenPages.add(currentUrl);
      let doc;
      if (pageCount === 0) doc = document;
      else {
        try {
          const response = await request('GET', currentUrl);
          doc = new DOMParser().parseFromString(response.responseText, 'text/html');
        } catch (error) {
          console.error('[HomeScraper] Could not load results page', currentUrl, error);
          break;
        }
      }
      const listings = pageListings(doc, currentUrl).filter(item => !seenListings.has(item.source_listing_id));
      listings.forEach(item => seenListings.add(item.source_listing_id));
      console.info(`[HomeScraper] ${source}: page ${pageCount + 1}, ${listings.length} new listings`);
      for (let start = 0; start < listings.length; start += 3) {
        await Promise.all(listings.slice(start, start + 3).map(async (listing, index) => {
          await delay(index * 350);
          await submitListing(listing);
        }));
        await delay(500);
      }
      const next = nextPage(doc, currentUrl);
      if (!next || seenPages.has(next)) break;
      currentUrl = next;
      pageCount += 1;
      await delay(700);
    }
    console.info(`[HomeScraper] ${source}: finished ${pageCount + 1} page(s), ${seenListings.size} listing(s).`);
  }
  crawl().catch(error => console.error('[HomeScraper] Crawl failed', error));
})();
