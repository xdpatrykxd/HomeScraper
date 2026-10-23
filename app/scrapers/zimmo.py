import asyncio
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
        log.warning('[ZIMMO] %s: building floor count contradicts flat floor; treating total as unknown', data['id'])
    sale, cert = t.get('sale') or {}, t.get('certificates') or {}
    city, postal = loc.get('locality'), loc.get('postalCode')
    kind = p['type'].lower()
    url = f'https://www.zimmo.be/en/classified/{kind}/for-sale/{quote((city or "belgium").lower(), safe="")}/{postal or "0000"}/{data["id"]}'
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
    return Property(source='zimmo', source_listing_id=str(data['id']), url=url,
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


async def parse_search(html):
    """Parse search results from Zimmo's HTML structure."""
    soup = BeautifulSoup(html, 'html.parser')
    # This is a placeholder - actual Zimmo HTML parsing would go here
    # Currently, since Cloudflare blocks normal access, this is just a template
    
    # Placeholder: assume we can parse like Immoweb but with Zimmo's expected structure
    return [], 0, 1


async def parse_detail(html):
    """Parse detail page from Zimmo."""
    # Placeholder - actual parsing would depend on Zimmo's HTML structure
    return None


class ZimmoScraper(PropertyScraper):
    async def search(self, config):
        # Zimmo.be is currently protected by Cloudflare and requires browser bypass
        # This method follows the same structure as other scrapers but cannot function
        # without accessing real data due to protection measures
        
        # In a working implementation, we would:
        # 1. Make requests to zimmo.be search URLs
        # 2. Extract property listing data from response pages
        # 3. Parse those listings into individual Property objects via normalize()
        # 4. Handle pagination properly
        
        raise SourceError('Adapter unavailable: public search returned a Cloudflare browser challenge during verification. No bypass implemented.')