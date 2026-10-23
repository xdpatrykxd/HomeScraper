import os
from pathlib import Path
from typing import Annotated
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.criteria import FEATURES, NUMERIC, CHOICES

NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class Required(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    terrace: bool = False
    garden: bool = False
    garage: bool = False
    parking: bool = False
    lift: bool = False
    balcony: bool = False
    disabled_access: bool = False
    basement: bool = False
    attic: bool = False
    laundry_room: bool = False
    dressing_room: bool = False
    air_conditioning: bool = False
    double_glazing: bool = False
    heat_pump: bool = False
    solar_panels: bool = False
    solar_thermal_panels: bool = False
    collective_water_heater: bool = False
    swimming_pool: bool = False
    sauna: bool = False
    jacuzzi: bool = False
    fireplace: bool = False
    alarm: bool = False
    armored_door: bool = False
    door_phone: bool = False
    video_phone: bool = False
    concierge: bool = False
    syndicator: bool = False
    heritage_protected: bool = False
    first_occupation: bool = False
    electrical_compliance_certificate: bool = False
    asbestos_certificate: bool = False
    separate_electricity_meter: bool = False
    separate_gas_meter: bool = False
    separate_water_meter: bool = False
    construction_permit: bool = False
    planning_violation: bool = False
    priority_purchase_right: bool = False
    investment_property: bool = False
    life_annuity: bool = False
    new_build: bool = False


class Filters(BaseModel):
    model_config = ConfigDict(extra='forbid')
    locations: list[str] = []
    postal_codes: list[str] = []
    min_price: NonNegative | None = None
    max_price: NonNegative | None = None
    min_surface_m2: NonNegative | None = None
    min_bedrooms: Annotated[int, Field(ge=0)] | None = None
    property_types: list[str] = []
    epc_allowed: list[str] = []
    required: Required = Required()
    forbidden: Required = Required()
    require_any: list[str] = []
    include_keywords: list[str] = []
    exclude_keywords: list[str] = []
    sources: dict[str, bool] = {'immoweb': True, 'zimmo': False, 'realo': False}

    max_surface_m2: NonNegative | None = None
    min_price_per_m2: NonNegative | None = None
    max_price_per_m2: NonNegative | None = None
    max_bedrooms: Annotated[int, Field(ge=0)] | None = None
    min_bathrooms: Annotated[int, Field(ge=0)] | None = None
    max_bathrooms: Annotated[int, Field(ge=0)] | None = None
    min_toilets: Annotated[int, Field(ge=0)] | None = None
    max_toilets: Annotated[int, Field(ge=0)] | None = None
    min_shower_rooms: Annotated[int, Field(ge=0)] | None = None
    max_shower_rooms: Annotated[int, Field(ge=0)] | None = None
    min_floor: int | None = None
    max_floor: int | None = None
    min_building_floors: Annotated[int, Field(ge=0)] | None = None
    max_building_floors: Annotated[int, Field(ge=0)] | None = None
    min_construction_year: Annotated[int, Field(ge=0)] | None = None
    max_construction_year: Annotated[int, Field(ge=0)] | None = None
    min_facades: Annotated[int, Field(ge=0)] | None = None
    max_facades: Annotated[int, Field(ge=0)] | None = None
    min_monthly_common_costs: NonNegative | None = None
    max_monthly_common_costs: NonNegative | None = None
    min_epc_value: NonNegative | None = None
    max_epc_value: NonNegative | None = None
    min_terrace_m2: NonNegative | None = None
    max_terrace_m2: NonNegative | None = None
    min_garden_m2: NonNegative | None = None
    max_garden_m2: NonNegative | None = None
    min_land_m2: NonNegative | None = None
    max_land_m2: NonNegative | None = None
    min_living_room_m2: NonNegative | None = None
    max_living_room_m2: NonNegative | None = None
    min_kitchen_m2: NonNegative | None = None
    max_kitchen_m2: NonNegative | None = None
    min_indoor_parking_spaces: Annotated[int, Field(ge=0)] | None = None
    max_indoor_parking_spaces: Annotated[int, Field(ge=0)] | None = None
    min_outdoor_parking_spaces: Annotated[int, Field(ge=0)] | None = None
    max_outdoor_parking_spaces: Annotated[int, Field(ge=0)] | None = None
    min_closed_garage_boxes: Annotated[int, Field(ge=0)] | None = None
    max_closed_garage_boxes: Annotated[int, Field(ge=0)] | None = None
    min_habitable_units: Annotated[int, Field(ge=0)] | None = None
    max_habitable_units: Annotated[int, Field(ge=0)] | None = None
    property_subtype_allowed: list[str] = []
    building_condition_allowed: list[str] = []
    heating_type_allowed: list[str] = []
    kitchen_type_allowed: list[str] = []
    garden_orientation_allowed: list[str] = []
    terrace_orientation_allowed: list[str] = []
    flood_zone_allowed: list[str] = []
    flood_p_score_allowed: list[str] = []
    flood_g_score_allowed: list[str] = []
    province_allowed: list[str] = []
    district_allowed: list[str] = []
    region_allowed: list[str] = []

    @model_validator(mode='after')
    def validate_values(self):
        for name in NUMERIC:
            low, high = getattr(self, 'min_' + name), getattr(self, 'max_' + name)
            if low is not None and high is not None and low > high:
                raise ValueError(f'min_{name} exceeds max_{name}')
        if set(self.require_any) - FEATURES.keys():
            raise ValueError('Unknown feature in require_any')
        required = {name for name in FEATURES if getattr(self.required, name)}
        forbidden = {name for name in FEATURES if getattr(self.forbidden, name)}
        if required & forbidden:
            raise ValueError('A feature cannot be both required and forbidden')
        if self.require_any and set(self.require_any) <= forbidden:
            raise ValueError('All require_any alternatives are forbidden')
        if set(self.sources) - {'immoweb', 'zimmo', 'realo'}:
            raise ValueError('Unknown source name')
        if any(t.lower() not in {'house', 'apartment'} for t in self.property_types):
            raise ValueError('Supported property_types: house, apartment')
        if any(not p.isdigit() or len(p) != 4 for p in self.postal_codes):
            raise ValueError('postal_codes must be quoted four-digit Belgian postal codes')
        return self


class Settings:
    def __init__(self):
        load_dotenv()
        self.config_path = Path(os.getenv('FILTERS_PATH', 'config/filters.yaml'))
        self.database_path = Path(os.getenv('DATABASE_PATH', 'data/listings.sqlite3'))
        self.interval = float(os.getenv('CHECK_INTERVAL_MINUTES', '5'))
        self.timeout = float(os.getenv('REQUEST_TIMEOUT_SECONDS', '25'))
        self.concurrency = int(os.getenv('REQUEST_CONCURRENCY', '4'))
        import math
        if not all(math.isfinite(x) and x > 0 for x in (self.interval, self.timeout)) or not 1 <= self.concurrency <= 16:
            raise ValueError('Intervals/timeouts must be positive; concurrency must be 1–16')
        self.gateway_url = os.getenv('WHATSAPP_GATEWAY_URL', 'http://127.0.0.1:3010').strip().rstrip('/')
        self.gateway_key = os.getenv('WAHA_API_KEY', '').strip()
        self.gateway_session = os.getenv('WHATSAPP_SESSION', 'default').strip()
        self.gateway_timeout = float(os.getenv('WHATSAPP_GATEWAY_TIMEOUT_SECONDS', '60'))
        self.group_ids = [v.strip() for v in os.getenv('WHATSAPP_GROUP_IDS', '').split(',') if v.strip()]
        self.recipients = list(dict.fromkeys(
            [v.strip() for v in os.getenv('WHATSAPP_RECIPIENTS', '').split(',') if v.strip()] +
            [v.strip() for k, v in sorted(os.environ.items()) if k.startswith('WHATSAPP_RECIPIENT_') and v.strip()] +
            self.group_ids
        ))

    def filters(self):
        with self.config_path.open() as f:
            return Filters.model_validate(yaml.safe_load(f) or {})

    def validate_gateway(self):
        import math
        import re
        from urllib.parse import urlsplit
        url = urlsplit(self.gateway_url)
        if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('WHATSAPP_GATEWAY_URL must be an HTTP(S) base URL without credentials, query or fragment')
        if not self.gateway_key or self.gateway_key.startswith('sha512:'):
            raise ValueError('Set WAHA_API_KEY to a plain API key; run python3 scripts/setup_env.py to generate one')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', self.gateway_session):
            raise ValueError('WHATSAPP_SESSION must contain only letters, numbers, underscores or hyphens')
        if not math.isfinite(self.gateway_timeout) or self.gateway_timeout <= 0:
            raise ValueError('WHATSAPP_GATEWAY_TIMEOUT_SECONDS must be positive')

    def validate_whatsapp(self):
        self.validate_gateway()
        if not self.recipients:
            raise ValueError('Set WHATSAPP_RECIPIENTS, numbered WHATSAPP_RECIPIENT variables, or WHATSAPP_GROUP_IDS in .env')
        from app.notifier import whatsapp
        for number in self.recipients:
            whatsapp(number)
        if any(not whatsapp(group).endswith('@g.us') for group in self.group_ids):
            raise ValueError('WHATSAPP_GROUP_IDS must contain only group IDs ending in @g.us')
