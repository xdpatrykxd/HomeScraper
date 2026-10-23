from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith('utm_') and k.lower() not in {'fbclid', 'gclid'}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip('/'), urlencode(sorted(query)), ''))


@dataclass
class Property:
    source: str
    source_listing_id: str | None
    url: str
    title: str | None = None
    address: str | None = None
    postal_code: str | None = None
    city: str | None = None
    price: float | None = None
    surface_m2: float | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    property_type: str | None = None
    epc: str | None = None
    epc_value: float | None = None
    terrace: bool | None = None
    terrace_m2: float | None = None
    garden: bool | None = None
    garden_m2: float | None = None
    garage: bool | None = None
    parking: bool | None = None
    lift: bool | None = None
    floor: int | None = None
    monthly_common_costs: float | None = None
    description: str | None = None
    image_url: str | None = None

    balcony: bool | None = None
    disabled_access: bool | None = None
    basement: bool | None = None
    attic: bool | None = None
    laundry_room: bool | None = None
    dressing_room: bool | None = None
    air_conditioning: bool | None = None
    double_glazing: bool | None = None
    heat_pump: bool | None = None
    solar_panels: bool | None = None
    solar_thermal_panels: bool | None = None
    collective_water_heater: bool | None = None
    swimming_pool: bool | None = None
    sauna: bool | None = None
    jacuzzi: bool | None = None
    fireplace: bool | None = None
    alarm: bool | None = None
    armored_door: bool | None = None
    door_phone: bool | None = None
    video_phone: bool | None = None
    concierge: bool | None = None
    syndicator: bool | None = None
    heritage_protected: bool | None = None
    first_occupation: bool | None = None
    electrical_compliance_certificate: bool | None = None
    asbestos_certificate: bool | None = None
    separate_electricity_meter: bool | None = None
    separate_gas_meter: bool | None = None
    separate_water_meter: bool | None = None
    construction_permit: bool | None = None
    planning_violation: bool | None = None
    priority_purchase_right: bool | None = None
    investment_property: bool | None = None
    life_annuity: bool | None = None
    new_build: bool | None = None
    toilets: int | None = None
    shower_rooms: int | None = None
    building_floors: int | None = None
    construction_year: int | None = None
    facades: int | None = None
    land_m2: float | None = None
    living_room_m2: float | None = None
    kitchen_m2: float | None = None
    indoor_parking_spaces: int | None = None
    outdoor_parking_spaces: int | None = None
    closed_garage_boxes: int | None = None
    habitable_units: int | None = None
    property_subtype: str | None = None
    building_condition: str | None = None
    heating_type: str | None = None
    kitchen_type: str | None = None
    garden_orientation: str | None = None
    terrace_orientation: str | None = None
    flood_zone: str | None = None
    flood_p_score: str | None = None
    flood_g_score: str | None = None
    province: str | None = None
    district: str | None = None
    region: str | None = None

    @property
    def price_per_m2(self):
        return self.price / self.surface_m2 if self.price is not None and self.surface_m2 and self.surface_m2 > 0 else None

    @property
    def id(self):
        return f'{self.source}:{self.source_listing_id}' if self.source_listing_id else canonical_url(self.url)
