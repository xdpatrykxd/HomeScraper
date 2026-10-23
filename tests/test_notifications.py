import unittest
from types import SimpleNamespace

import httpx

from app.models import Property
from app.notifier import Notifier, format_polish_message


class NotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_ai_key_does_not_trigger_requests_or_translation(self):
        settings = SimpleNamespace(gateway_url='http://gateway', gateway_key='test',
            gateway_session='default', gateway_timeout=60, openrouter_key='unused-legacy-key')
        p = Property('immoweb', '123', 'https://example.com/123', description='Een woning met terras.',
                     price=120000, terrace=True, lift=None)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: self.fail('Unexpected HTTP request'))) as client:
            text = await Notifier(settings, client).prepare(p)
        self.assertIn('NOWA NIERUCHOMOŚĆ', text)
        self.assertIn('Winda: brak danych', text)
        self.assertIn('Opis ogłoszenia (język oryginalny):', text)
        self.assertIn(p.description, text)
        self.assertNotIn('tłumaczenie automatyczne', text)

    def test_polish_categories_and_readable_numeric_facts(self):
        p = Property('immoweb', '123', 'https://example.com/123', price=149000, surface_m2=65,
                     building_condition='GOOD', heating_type='FUELOIL', property_subtype='FLAT_STUDIO',
                     kitchen_type='SEMI_EQUIPPED', terrace_orientation='SOUTH', flood_zone='NON_FLOOD_ZONE',
                     floor=0, garden=False)
        text = format_polish_message(p, {})
        for value in ('dobry', 'olej opałowy', 'kawalerka', 'częściowo wyposażona', 'południe',
                      'poza strefą powodziową', '2292,31', 'Piętro: 0', 'Ogród: nie'):
            self.assertIn(value, text)
        self.assertNotIn('FUELOIL', text)
