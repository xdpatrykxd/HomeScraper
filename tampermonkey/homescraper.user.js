// ==UserScript==
// @name         HomeScraper property sender
// @namespace    local.homescraper
// @version      3.5.0
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
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @connect      localhost
// @connect      immoweb.be
// @connect      zimmo.be
// @connect      realo.be
// @connect      immovlan.be
// @connect      immoscoop.be
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  const API_URL = 'http://127.0.0.1:8787/api/listings';
  const CONFIG_URL = 'http://127.0.0.1:8787/api/browser-config';
  const API_TOKEN = 'NBBDYOGZ_Y3KYhU9lFuC6z2JZIdB9U3VjP0dF6vp2l0';
  const DOMAINS = {
    'immoweb.be': 'immoweb', 'zimmo.be': 'zimmo', 'realo.be': 'realo',
    'immovlan.be': 'immovlan', 'immoscoop.be': 'immoscoop',
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
    return title && !/^(?:apartment|appartement|house|huis|woning|maison|flat|flat studio|ground floor|duplex|villa|penthouse|studio)(?:\s+(?:for sale|te koop|à vendre))?$/i.test(title) ? title : null;
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
  function dutchImmowebUrl(raw, baseUrl = location.href) {
    const url = new URL(raw, baseUrl);
    if (source === 'immoweb') url.pathname = url.pathname.replace(/^\/en(?=\/)/i, '/nl');
    return url.href;
  }
  function parseCard(anchor, baseUrl) {
    let url = listingUrl(anchor.getAttribute('href') || anchor.href, baseUrl);
    if (!url) return null;
    const parsedUrl = new URL(url);
    if (source === 'immoweb') {
      if (!/^\/(?:en|nl)\/(?:classified|zoekertje)\/[^/]+\/(?:for-sale|for-rent|te-koop|te-huur)\/[^/]+\/\d{4}\/\d{6,}\/?$/i.test(parsedUrl.pathname)) return null;
      url = dutchImmowebUrl(url, baseUrl);
    }
    const id = pathId(url);
    if (!id || id.length < 5) return null;
    const card = anchor.closest('article, li, [data-testid], [class*="card"], [class*="Card"], [class*="result"], [class*="Result"]') ?? anchor.parentElement;
    const text = (card?.innerText ?? anchor.innerText ?? '').replace(/\s+/g, ' ').trim();
    if (!text || text.length < 8 || (!priceFromText(text) && !/\d+\s*(?:slaapkamers?|chambres?|bedrooms?)/i.test(text))) return null;
    const areaMatch = text.match(/([\d.,]+)\s*m(?:²|2)/i);
    const bedsMatch = text.match(/(\d+)\s*(?:slaapkamers?|chambres?|bedrooms?)/i);
    const postMatch = text.match(/\b([1-9]\d{3})\b/);
    const image = card?.querySelector('img')?.src ?? null;
    const kindText = `${anchor.innerText} ${text} ${parsedUrl.pathname}`.toLowerCase();
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
  function immowebVisibleData(doc, listing) {
    const detail = doc.querySelector('.classified__description');
    const rows = [...doc.querySelectorAll('.classified-table tr')];
    function tableValue(labelPattern) {
      const row = rows.find(item => labelPattern.test((item.querySelector('th')?.innerText ?? '').replace(/\s+/g, ' ').trim()));
      return row?.querySelector('td')?.innerText.replace(/\s+/g, ' ').trim() ?? null;
    }
    function yesNo(labelPattern) {
      const value = tableValue(labelPattern);
      if (/^(yes|ja|oui)$/i.test(value ?? '')) return true;
      if (/^(no|nee|non)$/i.test(value ?? '')) return false;
      return null;
    }
    function matchedNumber(text, regex) {
      const match = (text ?? '').match(regex);
      return match ? number(match[1]) : null;
    }
    const info = doc.querySelector('.classified__information--property')?.innerText ?? '';
    const priceText = doc.querySelector('.classified__price')?.innerText ?? '';
    const addressRows = [...doc.querySelectorAll('.classified__information--address-row')].map(row => row.innerText.replace(/\s+/g, ' ').trim());
    const location = (addressRows[1] ?? '').match(/\b([1-9]\d{3})\b\s*(?:—|-)?\s*(.*)$/);
    const description = detail?.innerText.replace(/\s+/g, ' ').trim() ?? null;
    const epc = tableValue(/^(?:EPC\/PEB label|EPC\/EPC label|Energy class|EPC)$/i);
    const price = priceFromText(priceText);
    return {
      ...listing,
      title: titleOrNull(detail?.querySelector('strong')?.innerText) || titleOrNull(doc.querySelector('.classified__title')?.innerText),
      description,
      address: addressRows[0] ?? null,
      postal_code: location?.[1] ?? listing.postal_code,
      city: location?.[2] || listing.city,
      price,
      surface_m2: matchedNumber(info, /([\d.,]+)\s*m(?:²|2)/i) ?? number(tableValue(/^(?:Usable floor area|Livable area|Living area)$/i)),
      bedrooms: matchedNumber(info, /(\d+)\s*(?:bedrooms?|slaapkamers?|chambres?)/i) ?? number(tableValue(/^Bedrooms?$/i)),
      bathrooms: number(tableValue(/^Bathrooms?$/i)),
      property_type: /house|huis|woning|maison/i.test(listing.url) ? 'house' : /apartment|appartement/i.test(listing.url) ? 'apartment' : listing.property_type,
      epc: epc && !/not specified|niet opgegeven/i.test(epc) ? epc.toUpperCase() : null,
      epc_value: number(tableValue(/^Primary energy consumption$/i)),
      terrace: yesNo(/^Terrace$/i), terrace_m2: number(tableValue(/^Terrace area$/i)),
      garden: yesNo(/^Garden$/i), garden_m2: number(tableValue(/^Garden area$/i)),
      lift: yesNo(/^(?:Elevator|Lift)$/i),
      garage: yesNo(/^(?:Garage|Garage boxes?)$/i),
      floor: number(tableValue(/^Floor$/i)),
      building_floors: number(tableValue(/^(?:Number of floors|Building floors)$/i)),
    };
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
      const visible = immowebVisibleData(doc, listing);
      if (visible.price !== null || visible.surface_m2 !== null || visible.description) return visible;
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
      if (url && url !== currentUrl) return source === 'immoweb' ? dutchImmowebUrl(url, currentUrl) : url;
    }
    const current = new URL(currentUrl);
    const currentPage = Number(current.searchParams.get('page') || current.searchParams.get('pagina') || current.searchParams.get('p'));
    if (Number.isInteger(currentPage) && currentPage > 0) {
      const numbered = candidates.find(a => (a.innerText || '').trim() === String(currentPage + 1));
      if (numbered) {
        const url = listingUrl(numbered.getAttribute('href'), currentUrl);
        if (url && url !== currentUrl) return source === 'immoweb' ? dutchImmowebUrl(url, currentUrl) : url;
      }
      const pageKey = ['page', 'pagina', 'p'].find(key => current.searchParams.has(key));
      if (pageKey && doc.querySelector('a[rel="next"], [class*="pagination"], [class*="Pagination"]')) {
        current.pathname = source === 'immoweb' ? current.pathname.replace(/^\/en(?=\/)/i, '/nl') : current.pathname;
        current.searchParams.set(pageKey, String(currentPage + 1));
        return current.href;
      }
    }
    return null;
  }
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  const FLOW_PREFIX = 'HOMESCRAPER_VISIBLE_FLOW:';
  const FLOW_STORAGE_KEY = 'homescraper.visible-flow';
  function readFlow() {
    try {
      const url = new URL(location.href), encoded = url.searchParams.get('__hsf');
      if (encoded) {
        const flow = JSON.parse(decodeURIComponent(escape(atob(encoded))));
        url.searchParams.delete('__hsf'); history.replaceState(null, '', url.href);
        return flow;
      }
      if (window.name.startsWith(FLOW_PREFIX)) return JSON.parse(window.name.slice(FLOW_PREFIX.length));
      const stored = sessionStorage.getItem(FLOW_STORAGE_KEY);
      return stored ? JSON.parse(stored) : null;
    } catch (_) { return null; }
  }
  function saveFlow(flow) { const value = JSON.stringify(flow); window.name = FLOW_PREFIX + value; sessionStorage.setItem(FLOW_STORAGE_KEY, value); }
  function clearFlow() { if (window.name.startsWith(FLOW_PREFIX)) window.name = ''; sessionStorage.removeItem(FLOW_STORAGE_KEY); }
  function flowLink(url, flow) {
    const target = new URL(url);
    target.searchParams.set('__hsf', btoa(unescape(encodeURIComponent(JSON.stringify(flow)))));
    return target.href;
  }
  async function browserConfig() {
    const response = await request('GET', CONFIG_URL, { headers: { Authorization: `Bearer ${API_TOKEN}` } });
    return JSON.parse(response.responseText);
  }
  function filteredSearchUrls(site, config) {
    const hosts = { immoweb: 'www.immoweb.be', zimmo: 'www.zimmo.be', realo: 'www.realo.be', immovlan: 'www.immovlan.be', immoscoop: 'www.immoscoop.be' };
    const types = config.property_types?.length ? config.property_types : [null];
    return types.map(type => {
      const paths = {
        immoweb: `/nl/zoeken/${type === 'apartment' ? 'appartement' : type === 'house' ? 'huis' : 'huis-en-appartement'}/te-koop`,
        zimmo: `/nl/zoek/te-koop${type ? `/${type === 'apartment' ? 'appartement' : 'huis'}` : ''}`,
        realo: `/nl/search${type ? `/${type === 'apartment' ? 'appartement' : 'huis'}/te-koop` : ''}`,
        immovlan: `/nl/vastgoed/${type === 'apartment' ? 'appartement' : 'huis'}`,
        immoscoop: '/zoeken/query',
      };
      const url = new URL(paths[site], `https://${hosts[site]}`);
      const params = url.searchParams;
      if (site === 'immoweb') {
        if (config.postal_codes?.length) params.set('postalCodes', config.postal_codes.join(','));
        if (config.min_price != null) params.set('minPrice', String(config.min_price));
        if (config.max_price != null) params.set('maxPrice', String(config.max_price));
        if (config.min_surface_m2 != null) params.set('minSurface', String(config.min_surface_m2));
        if (config.min_bedrooms != null) params.set('minBedroomCount', String(config.min_bedrooms));
        params.set('orderBy', 'newest'); params.set('page', '1');
      } else if (site === 'immovlan') {
        params.set('transactiontypes', 'te-koop,in-openbare-verkoop');
      } else if (site === 'immoscoop') {
        params.set('offerType', 'te-koop');
        params.set('drawOnMap', '1');
        if (type) params.set('propertyType', type === 'apartment' ? 'appartement' : 'woonhuis');
      } else if (site === 'realo') {
        params.set('way', 'SALE');
        if (config.postal_codes?.length) params.set('q', config.postal_codes.join(' '));
        if (config.min_price != null) params.set('priceMin', String(config.min_price));
        if (config.max_price != null) params.set('priceMax', String(config.max_price));
        if (config.min_bedrooms != null) params.set('bedroomsMin', String(config.min_bedrooms));
      }
      return url.href;
    });
  }
  async function crawl() {
    let flow = readFlow();
    if (!flow) {
      try {
        const config = await browserConfig();
        const sites = Object.keys(DOMAINS).map(host => DOMAINS[host]).filter(site => config.sources?.[site]);
        const searches = sites.flatMap(site => filteredSearchUrls(site, config).map(url => ({ site, url })));
        if (!searches.length) return console.warn('[HomeScraper] No enabled source in filters.yaml.');
        flow = { mode: 'results', searches, searchIndex: 0, config };
        saveFlow(flow);
        location.assign(flowLink(searches[0].url, flow));
        return;
      } catch (error) {
        console.error('[HomeScraper] Could not load watcher filters', error);
        return;
      }
    }
    const search = flow.searches?.[flow.searchIndex];
    if (search?.site !== source) {
      if (!search) { clearFlow(); console.info('[HomeScraper] Finished all enabled sources.'); return; }
      location.assign(flowLink(search.url, flow));
      return;
    }
    if (flow?.mode === 'detail') {
      const listing = flow.queue[flow.index];
      if (listing && new URL(location.href).pathname.endsWith(new URL(listing.url).pathname)) {
        const enriched = source === 'immoweb' ? immowebVisibleData(document, listing) : detailData(document.documentElement.outerHTML, listing);
        await postListing(enriched);
      }
      flow.index += 1;
      if (flow.index < flow.queue.length) {
        saveFlow(flow);
        location.assign(flow.queue[flow.index].url);
      } else {
        const resultUrl = flow.resultsUrl;
        flow.mode = 'results'; flow.queue = []; flow.index = 0;
        saveFlow(flow);
        location.assign(resultUrl);
      }
      return;
    }
    if (flow?.mode === 'results' && (flow.pageUrl === location.href || flow.pageUrl == null)) {
      // Returning to results after detail visits; collect the next result batch.
      flow.pageUrl = location.href;
    } else {
      flow = { mode: 'results', pageUrl: location.href, seen: [], pages: 0 };
    }
    if (flow.pages >= 100) {
      flow.searchIndex += 1; flow.pageUrl = null; flow.seen = []; flow.pages = 0;
      const nextSearch = flow.searches?.[flow.searchIndex];
      if (nextSearch) { saveFlow(flow); location.assign(flowLink(nextSearch.url, flow)); }
      else { clearFlow(); console.info('[HomeScraper] Finished all enabled sources and property types.'); }
      return;
    }
    await humanScroll();
    const seen = new Set(flow.seen || []);
    const listings = pageListings(document, location.href).filter(item => !seen.has(item.source_listing_id));
    listings.forEach(item => seen.add(item.source_listing_id));
    flow.seen = [...seen];
    flow.resultsUrl = location.href;
    flow.queue = listings;
    flow.index = 0;
    flow.mode = 'detail';
    if (listings.length) {
      saveFlow(flow);
      console.info(`[HomeScraper] ${source}: visiting ${listings.length} visible-page listings in this tab.`);
      location.assign(listings[0].url);
      return;
    }
    const next = nextPage(document, location.href);
    if (next && next !== flow.pageUrl) {
      flow.pages += 1; flow.pageUrl = next; flow.resultsUrl = next; flow.mode = 'results';
      saveFlow(flow);
      console.info(`[HomeScraper] ${source}: clicking through to next results page.`);
      location.assign(next);
      return;
    }
    flow.searchIndex += 1;
    flow.mode = 'results'; flow.pageUrl = null; flow.resultsUrl = null; flow.seen = []; flow.pages = 0;
    const nextSearch = flow.searches?.[flow.searchIndex];
    if (nextSearch) {
      saveFlow(flow);
      location.assign(flowLink(nextSearch.url, flow));
    } else {
      clearFlow();
      console.info('[HomeScraper] Finished all enabled sources and property types.');
    }
  }
  async function postListing(listing) {
    try {
      const response = await request('POST', API_URL, {
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${API_TOKEN}` },
        data: JSON.stringify({ listing }),
      });
      console.info('[HomeScraper]', source, listing.source_listing_id, response.status, response.responseText);
    } catch (error) { console.error('[HomeScraper] API request failed', error); }
  }
  async function humanScroll() {
    const step = Math.max(400, Math.floor(window.innerHeight * 0.72));
    let y = 0, stablePasses = 0, priorEnd = 0;
    while (stablePasses < 2) {
      const end = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
      if (end <= priorEnd) stablePasses += 1;
      else stablePasses = 0;
      priorEnd = end;
      if (y >= end) y = Math.max(0, end - window.innerHeight);
      window.scrollTo({ top: y, behavior: 'smooth' });
      await delay(180 + Math.random() * 180);
      y += step;
      if (y > end + step) await delay(500);
    }
    await delay(700);
    window.scrollTo({ top: 0, behavior: 'smooth' });
    await delay(500);
  }
  crawl().catch(error => console.error('[HomeScraper] Crawl failed', error));
})();
