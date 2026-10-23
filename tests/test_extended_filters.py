import json
import re
import unittest
from pathlib import Path

from pydantic import ValidationError

from app.config import Filters
from app.criteria import FEATURES, NUMERIC, CHOICES
from app.filters import matches, needs_details
from app.models import Property
from app.scrapers.immoweb import normalize


def home(**kwargs):
    return Property('immoweb', '123', 'https://example.com/123', **kwargs)


class ExtendedFiltersTests(unittest.TestCase):
    def test_registered_source_paths_reach_property_fields(self):
        html = (Path(__file__).parent / 'fixtures/immoweb-detail.html').read_text()
        match = re.search(r'window\.classified\s*=\s*', html)
        row = json.JSONDecoder().raw_decode(html[match.end():])[0]
        def set_path(path, value):
            node = row['property']
            parts = path.split('.')
            for key in parts[:-1]:
                if not isinstance(node.get(key), dict):
                    node[key] = {}
                node = node[key]
            node[parts[-1]] = value
        for field, (path, _) in FEATURES.items():
            if path:
                set_path(path, True)
        for field, (path, _, _, _) in NUMERIC.items():
            if path:
                set_path(path, 7)
        for field, (path, _) in CHOICES.items():
            set_path(path, 'TEST_VALUE')
        p = normalize(row)
        for field, (path, _) in FEATURES.items():
            if path:
                self.assertIs(getattr(p, field), True, field)
        for field, (path, _, _, _) in NUMERIC.items():
            if path:
                self.assertEqual(getattr(p, field), 7, field)
        for field in CHOICES:
            self.assertEqual(getattr(p, field), 'TEST_VALUE', field)

    def test_every_numeric_bound_and_unknown(self):
        for field in NUMERIC:
            for bound in ('min', 'max'):
                with self.subTest(field=field, bound=bound):
                    f = Filters(**{f'{bound}_{field}': 4})
                    p = home(**({field: 4} if field != 'price_per_m2' else {'price': 40, 'surface_m2': 10}))
                    self.assertTrue(matches(p, f))
                    p = home(**({field: 3 if bound == 'min' else 5} if field != 'price_per_m2' else
                                {'price': 30 if bound == 'min' else 50, 'surface_m2': 10}))
                    self.assertFalse(matches(p, f))
                    missing_height_allowed = field == 'building_floors' and bound == 'max'
                    self.assertTrue(matches(home(), f))
                    self.assertTrue(matches(home(), f, allow_unknown=True))
                    self.assertEqual(needs_details(home(), f), not missing_height_allowed)

    def test_every_feature_supports_required_forbidden_and_any(self):
        for field in FEATURES:
            with self.subTest(field=field):
                yes, no, unknown = home(**{field: True}), home(**{field: False}), home()
                required = Filters(required={field: True})
                forbidden = Filters(forbidden={field: True})
                self.assertTrue(matches(yes, required))
                self.assertFalse(matches(no, required))
                self.assertTrue(matches(no, forbidden))
                self.assertFalse(matches(yes, forbidden))
                for f in (required, forbidden, Filters(require_any=[field])):
                    missing_lift_allowed = field == 'lift' and f is forbidden
                    self.assertEqual(matches(unknown, f), not bool(f.require_any))
                    self.assertTrue(matches(unknown, f, allow_unknown=True))
                    self.assertEqual(needs_details(unknown, f), not missing_lift_allowed)

    def test_every_choice_is_case_insensitive_and_unknown_passes(self):
        for field in CHOICES:
            f = Filters(**{field + '_allowed': ['gas']})
            self.assertTrue(matches(home(**{field: 'GAS'}), f))
            self.assertFalse(matches(home(**{field: 'OTHER'}), f))
            self.assertTrue(matches(home(), f))
            self.assertTrue(needs_details(home(), f))

    def test_height_is_not_flat_floor_and_lift_is_explicitly_absent(self):
        f = Filters(max_building_floors=4, forbidden={'lift': True})
        self.assertTrue(matches(home(floor=0, building_floors=4, lift=False), f))
        self.assertFalse(matches(home(floor=0, building_floors=5, lift=False), f))
        self.assertTrue(matches(home(floor=0, building_floors=None, lift=False), f))
        self.assertFalse(matches(home(building_floors=None, lift=True), f))
        self.assertTrue(matches(home(building_floors=None, lift=None), f))
        self.assertTrue(matches(home(building_floors=None), Filters(min_building_floors=1)))
        self.assertTrue(matches(home(building_floors=3, lift=None), f))
        self.assertFalse(matches(home(building_floors=5, lift=None), f))
        self.assertTrue(matches(home(floor=-1), Filters(min_floor=-1, max_floor=0)))

    def test_high_flat_cannot_bypass_building_cap_with_wrong_or_missing_total(self):
        f = Filters(max_building_floors=4)
        for total in (1, None, 17):
            self.assertFalse(matches(home(floor=8, building_floors=total), f))
            self.assertFalse(matches(home(floor=8, building_floors=total), f, allow_unknown=True))
        self.assertTrue(matches(home(floor=2, building_floors=None), f))
        self.assertTrue(matches(home(floor=None, building_floors=None), f))

    def test_deurne_listing_inconsistent_floor_regression(self):
        html = (Path(__file__).parent / 'fixtures/immoweb-inconsistent-floor.html').read_text()
        match = re.search(r'window\.classified\s*=\s*', html)
        row = json.JSONDecoder().raw_decode(html[match.end():])[0]
        p = normalize(row)
        self.assertEqual(p.source_listing_id, '21809885')
        self.assertEqual(p.floor, 8)
        self.assertIsNone(p.building_floors)
        self.assertFalse(matches(p, Filters(max_building_floors=4, require_any=['terrace', 'garden'])))

    def test_conflicts_and_invalid_ranges(self):
        for field in NUMERIC:
            with self.assertRaises(ValidationError):
                Filters(**{'min_' + field: 5, 'max_' + field: 4})
        for data in ({'required': {'lift': True}, 'forbidden': {'lift': True}},
                     {'require_any': ['terrace', 'garden'], 'forbidden': {'terrace': True, 'garden': True}},
                     {'forbidden': {'lift': 'true'}}, {'require_any': ['escalator']}):
            with self.assertRaises(ValidationError):
                Filters(**data)

    def test_parser_maps_nested_data_without_inventing_missing_values(self):
        html = (Path(__file__).parent / 'fixtures/immoweb-detail.html').read_text()
        match = re.search(r'window\.classified\s*=\s*', html)
        row = json.JSONDecoder().raw_decode(html[match.end():])[0]
        row['property']['location']['floor'] = 0
        row['property']['building']['floorCount'] = 5
        row['property']['building']['condition'] = 'GOOD'
        row['property']['propertyCertificates'] = {'hasAsbestosCertificate': True}
        p = normalize(row)
        self.assertEqual((p.floor, p.building_floors, p.construction_year), (0, 5, 1919))
        self.assertEqual(p.heating_type, 'GAS')
        self.assertTrue(p.asbestos_certificate)
        self.assertFalse(p.disabled_access)
        self.assertIsNone(p.outdoor_parking_spaces)
        row['property']['building']['floorCount'] = None
        row['property']['energy']['heatingType'] = 'NOT_SPECIFIED'
        row['property']['hasDisabledAccess'] = 'false'
        p = normalize(row)
        self.assertIsNone(p.building_floors)
        self.assertIsNone(p.heating_type)
        self.assertIsNone(p.disabled_access)

    def test_placeholder_description_uses_one_original_language_and_sanitizes_parking(self):
        html = (Path(__file__).parent / 'fixtures/immoweb-detail.html').read_text()
        match = re.search(r'window\.classified\s*=\s*', html)
        row = json.JSONDecoder().raw_decode(html[match.end():])[0]
        p = row['property']
        p['description'] = '-'
        p['alternativeDescriptions'] = {'nl': 'Een studio met terras.', 'fr': 'Un studio avec terrasse.'}
        p['parkingCountIndoor'] = 1974
        p['parkingCountOutdoor'] = None
        result = normalize(row)
        self.assertEqual(result.description, 'Een studio met terras.')
        self.assertIsNone(result.indoor_parking_spaces)
        self.assertIsNone(result.parking)
        p['parkingCountOutdoor'] = 1
        self.assertTrue(normalize(row).parking)
        p['alternativeDescriptions'] = {'nl': '-', 'fr': '/'}
        self.assertIsNone(normalize(row).description)

    def test_included_keywords_require_all_and_wait_for_detail(self):
        f = Filters(include_keywords=['quiet', 'renovated'])
        self.assertTrue(matches(home(description='Quiet and RENOVATED'), f))
        self.assertFalse(matches(home(description='quiet'), f))
        self.assertTrue(matches(home(), f))
        self.assertTrue(matches(home(), f, allow_unknown=True))
