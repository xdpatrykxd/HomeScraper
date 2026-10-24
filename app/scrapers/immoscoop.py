import asyncio
import json
import logging
import math
import re
from urllib.parse import quote
from bs4 import BeautifulSoup
from app.models import Property
from app.filters import matches
from app.criteria import FEATURES, NUMERIC, CHOICES
from .base import PropertyScraper, SourceError

log = logging.getLogger(__name__)

def clean_description(text):
    if not isinstance(text, str):
        return None
    text = BeautifulSoup(text, 'html.parser').get_text(' ', strip=True)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', ' ', text).strip()
    if text.casefold() in {'', '-', '--', '/', '.', 'n/a', 'na', 'none', 'null'}:
        return None
    return text

def description_from(p):
    alternatives = p.get('alternativeDescriptions') or {}
    # Prefer the original Dutch/French prose over placeholder English translations.
    for text in [alternatives.get('nl'), alternatives.get('fr'), p.get('description'), alternatives.get('en')]:
        cleaned = clean_description(text)
        if cleaned:
            return cleaned
    return None

def parking_count(value):
    # Counts refer to the advertised dwelling. Never guess that a year-like value
    # is a construction year or allow it to establish the presence of parking.
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value == int(value) and 0 <= value <= 100:
        return int(value)
    return None

def value_at(data, path):
    for key in path.split('.'):
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data

def extra_fields(p, t, flags):
    result = {}
    for field, (path, _) in FEATURES.items():
        if path and field not in {'terrace', 'garden', 'lift'}:
            value = value_at(p, path)
            result[field] = value if isinstance(value, bool) else None
    for field, (path, _, _, integer) in NUMERIC.items():
        if path and field not in {'surface_m2', 'bedrooms', 'bathrooms', 'floor', 'monthly_common_costs', 'terrace_m2', 'garden_m2'}:
            value = value_at(p, path)
            valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            result[field] = value if valid and (not integer or int(value) == value) else None
    for field, (path, _) in CHOICES.items():
        value = value_at(p, path)
        result[field] = value if isinstance(value, str) and value.strip() and value.upper() not in {'UNKNOWN', 'NOT_SPECIFIED'} else None
    for field, value in [('investment_property', (t.get('investor') or {}).get('isInvestmentProperty')),
                          ('life_annuity', flags.get('isLifeAnnuitySale')),
                          ('new_build', flags.get('isNewlyBuilt'))]:
        result[field] = value if isinstance(value, bool) else None
    if (t.get('sale') or {}).get('lifeAnnuity'):
        result['life_annuity'] = True
    return result

def normalize(data):
    p, t = data.get('property') or {}, data.get('transaction') or {}
    flags = data.get('flags') or {}
    flag_text = json.dumps(flags).lower()
    if (t.get('type') != 'FOR_SALE'
            or flags.get('isUnderOption') is True
            or flags.get('isSoldOrRented') is True
            or any(f'"{word}"' in flag_text for word in ('sold', 'rented', 'expired', 'removed', 'under_option', 'under option', 'underoption'))):
        return None
    if p.get('type') not in {'HOUSE', 'APARTMENT'} or data.get('id') is None:
        return None  # Project clusters are not individual properties.
    p = dict(p)
    for field in ('parkingCountIndoor', 'parkingCountOutdoor', 'parkingCountClosedBox'):
        p[field] = parking_count(p.get(field))
    loc = p.get('location') or {}
    building = p.get('building') or {}
    floor, total = loc.get('floor'), building.get('floorCount')
    if (isinstance(floor, (int, float)) and isinstance(total, (int, float))
            and floor > total):
        p['building'] = {**building, 'floorCount': None}
        log.warning('[IMMOSCOOP] %s: building floor count contradicts flat floor; treating total as unknown', data['id'])
    sale, cert = t.get('sale') or {}, t.get('certificates') or {}
    city, postal = loc.get('locality'), loc.get('postalCode')
    kind = p['type'].lower()
    url = f'https://www.immoscoop.be/en/classified/{kind}/for-sale/{quote((city or "belgium").lower(), safe="")}/{postal or "0000"}/{data["id"]}'
    pics = (data.get('media') or {}).get('pictures') or []
    description = description_from(p)
    if sale.get('lifeAnnuity'):
        description = (description or '') + ' lijfrente life annuity'
    if (t.get('investor') or {}).get('isInvestmentProperty'):
        description = (description or '') + ' investment property opbrengsteigendom'
    counts = [p.get('parkingCountIndoor'), p.get('parkingCountOutdoor'), p.get('parkingCountClosedBox')]
    parking = True if any(x is not None and x > 0 for x in counts) else (False if all(x is not None for x in counts) else None)
    def feature(name, surface):
        value = p.get(name)
        return value if value is not None else (True if (p.get(surface) or 0) > 0 else None)
    price = sale.get('price')
    if price is None:
        price = (data.get('price') or {}).get('mainValue')
    if t.get('hidePrice') or (data.get('price') or {}).get('hidePrice'):
        price = None
    return Property(source='immoscoop', source_listing_id=str(data['id']), url=url,
        title=p.get('title') or f'{kind.title()} in {city or "Belgium"}',
        address=' '.join(str(loc[k]) for k in ('street', 'number', 'box') if loc.get(k)) or None,
        postal_code=str(postal) if postal else None, city=city, price=price,
        surface_m2=p.get('netHabitableSurface'), bedrooms=p.get('bedroomCount'), bathrooms=p.get('bathroomCount'),
        property_type=kind, epc=cert.get('epcScore') or t.get('certificate'), epc_value=cert.get('primaryEnergyConsumptionPerSqm'),
        terrace=feature('hasTerrace', 'terraceSurface'), terrace_m2=p.get('terraceSurface'),
        garden=feature('hasGarden', 'gardenSurface'), garden_m2=p.get('gardenSurface'),
        garage=p['parkingCountClosedBox'] > 0 if p.get('parkingCountClosedBox') is not None else None,
        parking=parking, lift=p.get('hasLift'), floor=loc.get('floor'), monthly_common_costs=p.get('monthlyCosts'),
        description=description, image_url=(pics[0].get('largeUrl') or pics[0].get('mediumUrl')) if pics else None,
        **extra_fields(p, t, flags))

def parse_search(html):
    soup = BeautifulSoup(html, 'html.parser')
    # Looking for search results div with data attribute
    node = soup.find('div', {'data-testid': 'ad-search-results'})

    if not node:
        # Try alternative selector approach
        node = next((n for n in soup.find_all() if n.has_attr(':results')), None)

    if not node:
        raise SourceError('Immoscoop search data missing (challenge or changed page format)')

    try:
        # Try to get search data from various attribute formats that Immoweb uses
        data = {}
        if hasattr(node, 'get'):
            result_data = node.get('data-search-results')
            if not result_data:
                result_data = node.get(':results')
            if not result_data:
                result_data = node.get('__vnode__')

            if result_data:
                data = json.loads(result_data)

        count = int(node.get('data-search-count', 0)) or len(data.get('listings', []))
        size = int(node.get('data-search-pagesize', 10))
        page = int(node.get('data-search-page', 1))

        if not isinstance(data, dict) or 'listings' not in data:
            raise ValueError("Invalid search data format")

        listings = data.get('listings', [])
        return listings, math.ceil(count / size) if size > 0 else 1, page
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        # If parsing failed, let's try to find the json data manually from html
        try:
            # Look for window variables that contain search data
            pattern = r'window\._config\s*=\s*(\{.*?\});'
            match = re.search(pattern, html, re.DOTALL)
            if match:
                config_data = json.loads(match.group(1))
                if 'search' in config_data and 'results' in config_data['search']:
                    return config_data['search']['results'], 0, 1
        except:
            pass

        raise SourceError('Invalid Immoscoop pagination or listing data')

def parse_detail(html):
    # Try to find window.variable containing the classified data
    match = re.search(r'window\.classified\s*=\s*', html)
    if not match:
        # Try alternative patterns
        pattern = r'window\._data\s*=\s*(.*?);'
        match = re.search(pattern, html, re.DOTALL)

    if not match:
        raise SourceError('Immoscoop detail data missing - no classified window variable found')

    try:
        # Get everything after the matched variable
        json_str = html[match.end():]
        start_idx = json_str.find('{')
        if start_idx != -1:
            json_str = json_str[start_idx:].split(';', 1)[0]  # Get content to first semicolon

        data = json.loads(json_str)
        return normalize(data)
    except (ValueError, TypeError) as exc:
        raise SourceError('Invalid Immoscoop detail data') from exc

class ImmoscoopScraper(PropertyScraper):
    async def search(self, config):
        # Use direct HTTP; the caller can use the Tampermonkey fallback if blocked.
        params = {'countries': 'BE', 'orderBy': 'newest'}
        if config.postal_codes:
            params['postalCodes'] = ','.join(config.postal_codes)
        for name, value in [('minPrice', config.min_price), ('maxPrice', config.max_price)]:
            if value is not None:
                params[name] = f'{value:g}'
        types = config.property_types
        kind = types[0].lower() if len(types) == 1 else 'house-and-apartment'

        url = 'https://www.immoscoop.be/en/search/' + (kind + '/for-sale' if kind != 'house-and-apartment' else 'house-and-apartment/for-sale')

        collected, seen = [], set()
        page = 1

        while True:
            try:
                # Using browser automation to get search results
                html = await self.get(url, params={**params, 'page': page})

                rows, last_page, actual_page = parse_search(html)
                if actual_page != page:
                    raise SourceError(f'Immoscoop returned page {actual_page} instead of {page}; coverage incomplete')
                fresh = [d for d in rows if d.get('id') is not None and str(d['id']) not in seen]
                if not rows or not fresh:
                    if rows:
                        log.warning('[IMMOSCOOP] Results repeat at page %d; stopping pagination', page)
                    break
                for data in fresh:
                    seen.add(str(data['id']))
                    prop = normalize(data)
                    if prop:
                        collected.append(prop)
                if page >= last_page:
                    break
                page += 1
            except SourceError:
                raise

        log.info('[IMMOSCOOP] %d active listings found across %d pages', len(collected), page)

        # Filter results by configured criteria
        candidates = [p for p in collected if matches(p, config, allow_unknown=True)]

        # Perform detailed fetching to get complete property info
        async def enrich(p):
            # Search cards can lag behind availability changes on the detail page.
            # Verify every candidate before returning it for an alert, even when
            # the search card already supplies all enabled criteria.
            try:
                html = await self.get(p.url)
                detail = parse_detail(html)
                if detail is None or detail.source_listing_id != p.source_listing_id:
                    return None
                return detail
            except SourceError as exc:
                log.warning('[IMMOSCOOP] Skipping %s: availability/details unavailable (%s)', p.source_listing_id, exc)
                return None

        # Bound tasks as well as concurrent connections.
        enriched = []
        for start in range(0, len(candidates), 16):
            enriched.extend(await asyncio.gather(*(enrich(p) for p in candidates[start:start + 16])))

        # Filter the results again after enrichment and return matching properties
        final_matches = [p for p in enriched if p is not None and matches(p, config)]
        return final_matches
