from app.models import Property
from app.config import Filters
from app.criteria import NUMERIC, CHOICES


def matches(p: Property, f: Filters, *, allow_unknown=False) -> bool:
    def compare(value, condition):
        return True if value is None else condition(value)
    for field in NUMERIC:
        for bound in ('min', 'max'):
            limit = getattr(f, f'{bound}_{field}')
            if (field == 'building_floors' and bound == 'max' and limit is not None
                    and p.floor is not None and p.floor > limit):
                return False  # A flat above the cap cannot be in a shorter building.
            # The height cap excludes known tall buildings, not unreported heights.
            if field == 'building_floors' and bound == 'max' and p.building_floors is None:
                continue
            if limit is not None and not compare(getattr(p, field), lambda v: v >= limit if bound == 'min' else v <= limit):
                return False
    for field, allowed in [('city', f.locations), ('postal_code', f.postal_codes),
                            ('property_type', f.property_types), ('epc', f.epc_allowed),
                            *((field, getattr(f, field + '_allowed')) for field in CHOICES)]:
        if allowed and not compare(getattr(p, field), lambda v: str(v).strip().casefold() in {str(a).strip().casefold() for a in allowed}):
            return False
    for field, required in f.required.model_dump().items():
        if required and not compare(getattr(p, field), lambda v: v is True):
            return False
    for field, forbidden in f.forbidden.model_dump().items():
        if field == 'lift' and p.lift is None:
            continue  # Exclude confirmed lifts, without assuming unreported means present.
        if forbidden and not compare(getattr(p, field), lambda v: v is False):
            return False
    if f.require_any and not any(getattr(p, field) is True for field in f.require_any):
        # Search cards may omit amenities; allow candidates to reach the detail
        # check, but final matches require a confirmed positive alternative.
        if not (allow_unknown and any(getattr(p, field) is None for field in f.require_any)):
            return False
    text = ' '.join(v for v in (p.title, p.description) if v).casefold()
    if f.include_keywords and not p.description:
        return not any(word.casefold() in text for word in f.exclude_keywords if word.strip())
    return (all(word.casefold() in text for word in f.include_keywords if word.strip())
            and not any(word.casefold() in text for word in f.exclude_keywords if word.strip()))


def needs_details(p: Property, f: Filters) -> bool:
    fields = [(field, getattr(f, 'min_' + field) is not None or getattr(f, 'max_' + field) is not None) for field in NUMERIC]
    fields = [(field, f.min_building_floors is not None if field == 'building_floors' else enabled)
              for field, enabled in fields]
    fields += [(field, bool(getattr(f, field + '_allowed'))) for field in CHOICES]
    fields += [('epc', bool(f.epc_allowed)), ('city', bool(f.locations)), ('postal_code', bool(f.postal_codes))]
    fields += list(f.required.model_dump().items())
    fields += [(field, enabled) for field, enabled in f.forbidden.model_dump().items() if field != 'lift']
    any_needs_details = bool(f.require_any) and not any(
        getattr(p, field) is True for field in f.require_any
    ) and any(getattr(p, field) is None for field in f.require_any)
    return any(enabled and getattr(p, field) is None for field, enabled in fields) or any_needs_details or bool((f.exclude_keywords or f.include_keywords) and p.description is None)
