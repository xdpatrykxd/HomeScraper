// ==UserScript==
// @name         HomeScraper property sender
// @namespace    local.homescraper
// @version      2.0.0
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
  function pathId(url) {
    const parts = new URL(url).pathname.split('/').filter(Boolean);
    const last = parts.at(-1) ?? '';
    if (/^(page|zoeken|search|te-koop|for-sale|appartement|huis|woning)$/i.test(last)) return '';
    return (last.match(/\d{4,}|[A-Z]{2,}\d{2,}/i) ?? [last])[0];
  }
  function listingUrl(raw) {
    try {
      const url = new URL(raw, location.href);
      if (url.protocol !== 'https:' || !Object.keys(DOMAINS).some(d => url.hostname === d || url.hostname.endsWith(`.${d}`))) return null;
      return url.href;
    } catch (_) { return null; }
  }
  function parseCard(anchor) {
    const url = listingUrl(anchor.href);
    if (!url) return null;
    const id = pathId(url);
    if (!id || id.length < 4) return null;
    const card = anchor.closest('article, li, [data-testid], [class*="card"], [class*="Card"], [class*="result"], [class*="Result"]') ?? anchor.parentElement;
    const text = (card?.innerText ?? anchor.innerText ?? '').replace(/\s+/g, ' ').trim();
    if (!text || text.length < 8) return null;
    const priceMatch = text.match(/(?:€\s*|EUR\s*)([\d.,\s]{4,})|([\d.,\s]{4,})\s*€/i);
    const areaMatch = text.match(/([\d.,]+)\s*m(?:²|2)/i);
    const bedsMatch = text.match(/(\d+)\s*(?:slaapkamers?|chambres?|bedrooms?)/i);
    const postMatch = text.match(/\b([1-9]\d{3})\b/);
    const image = card?.querySelector('img')?.src ?? null;
    const kindText = `${anchor.innerText} ${text}`.toLowerCase();
    const propertyType = /huis|house|maison|villa/.test(kindText) ? 'house' : /appartement|apartment|appart/.test(kindText) ? 'apartment' : null;
    return {
      source, source_listing_id: id, url,
      title: anchor.innerText.trim() || text.slice(0, 180),
      postal_code: postMatch?.[1] ?? null,
      price: number(priceMatch?.[1] ?? priceMatch?.[2]),
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
    const all = [];
    for (const node of doc.querySelectorAll('script[type="application/ld+json"]')) {
      try { extractObjects(JSON.parse(node.textContent), all); } catch (_) { /* malformed or unrelated JSON-LD */ }
    }
    const ld = all.find(item => /Residence|House|Apartment|Product|RealEstateListing/i.test(String(item['@type']))) ?? {};
    const offers = ld.offers ?? {};
    const address = ld.address ?? {};
    const geoAddress = address.address ?? address;
    const text = doc.body?.innerText ?? '';
    const price = first(offers.price, ld.price, text.match(/(?:€\s*|EUR\s*)([\d.,\s]{4,})/i)?.[1]);
    const livingArea = ld.floorSize?.value ?? ld.floorSize;
    const beds = first(ld.numberOfBedrooms, ld.numberOfRooms);
    const pcode = first(geoAddress.postalCode, text.match(/\b([1-9]\d{3})\s+[A-ZÀ-ÿ]/i)?.[1]);
    const terrace = /(?:terras|terrace|terrasse|balcon|balcony)/i.test(text) ? true : null;
    const garden = /(?:tuin|garden|jardin)/i.test(text) ? true : null;
    const epc = text.match(/(?:EPC|PEB|EPB)\s*[:\-]?\s*(A\+{0,2}|A|B|C|D|E|F|G)\b/i)?.[1]?.toUpperCase();
    return {
      ...listing,
      title: first(ld.name, doc.querySelector('h1')?.innerText, listing.title),
      description: first(ld.description, doc.querySelector('meta[name="description"]')?.content),
      city: first(geoAddress.addressLocality, geoAddress.city),
      address: first(geoAddress.streetAddress),
      postal_code: pcode == null ? listing.postal_code : String(pcode),
      price: number(price), surface_m2: number(livingArea) ?? listing.surface_m2,
      bedrooms: number(beds) ?? listing.bedrooms,
      property_type: first(/house|house|woning|maison/i.test(String(ld['@type'])) ? 'house' : null, listing.property_type),
      epc: first(ld.energyEfficiencyScaleMin, epc),
      terrace, garden,
      image_url: first(Array.isArray(ld.image) ? ld.image[0] : ld.image, listing.image_url),
    };
  }
  function send(listing) {
    GM_xmlhttpRequest({
      method: 'POST', url: API_URL,
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${API_TOKEN}` },
      data: JSON.stringify({ listing }),
      onload: response => console.info('[HomeScraper]', source, listing.source_listing_id, response.status, response.responseText),
      onerror: error => console.error('[HomeScraper] API request failed', error),
    });
  }

  const found = new Map();
  for (const anchor of document.querySelectorAll('a[href]')) {
    const listing = parseCard(anchor);
    if (listing && !found.has(listing.source_listing_id)) found.set(listing.source_listing_id, listing);
  }
  const listings = [...found.values()];
  listings.forEach((listing, index) => setTimeout(() => GM_xmlhttpRequest({
    method: 'GET', url: listing.url,
    onload: response => send(detailData(response.responseText, listing)),
    onerror: () => send(listing),
  }), index * 900));
  console.info(`[HomeScraper] Found ${listings.length} ${source} listings on this page.`);
})();
