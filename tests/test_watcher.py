import copy
import html
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import httpx
from pydantic import ValidationError
from app.config import Filters, Settings
from app.database import Database
from app.filters import matches, needs_details
from app.models import Property, canonical_url
from app.notifier import Notifier, RejectedSend, AmbiguousSend, format_polish_message
from app.scrapers.immoweb import normalize, parse_search, parse_detail, ImmowebScraper
from app.scrapers.base import SourceError
from app.main import scan
from app.gateway import WhatsAppGateway, GatewayError, chat_id

FIXTURES = Path(__file__).parent / 'fixtures'


def property(**kwargs):
    return Property(**({'source': 'immoweb', 'source_listing_id': '123', 'url': 'https://example.com/listing/123',
                       'city': 'Wilrijk', 'price': 319000, 'surface_m2': 98, 'bedrooms': 3,
                       'epc': 'B', 'property_type': 'apartment'} | kwargs))


def page(rows, number=1, count=2, size=1):
    return f'<iw-search :results=\'{html.escape(json.dumps(rows), quote=True)}\' :page="{number}" :count="{count}" :items-per-page="{size}"></iw-search>'


class FilterTests(unittest.TestCase):
    def test_defaults_and_price_per_area(self):
        self.assertTrue(matches(property(), Filters()))
        self.assertAlmostEqual(property().price_per_m2, 3255.1020408163267)
        self.assertIsNone(property(surface_m2=0).price_per_m2)
        self.assertIsNone(property(price=None).price_per_m2)

    def test_all_criteria(self):
        f = Filters(locations=['wilrijk'], postal_codes=['2610'], min_price=300000, max_price=350000,
                    min_surface_m2=80, min_bedrooms=2, epc_allowed=['b'], property_types=['apartment'],
                    required={'terrace': True, 'garden': True, 'garage': True, 'parking': True, 'lift': True})
        p = property(postal_code='2610', terrace=True, garden=True, garage=True, parking=True, lift=True)
        self.assertTrue(matches(p, f))
        for field, value in [('city', 'Antwerp'), ('postal_code', '2000'), ('price', 400000), ('price', 200000),
                             ('surface_m2', 50), ('bedrooms', 1), ('epc', 'D'), ('property_type', 'house'),
                             ('terrace', False), ('garden', False), ('garage', False), ('parking', False), ('lift', False)]:
            with self.subTest(field=field, value=value):
                other = copy.copy(p)
                setattr(other, field, value)
                self.assertFalse(matches(other, f))
                setattr(other, field, None)
                self.assertTrue(matches(other, f))
                self.assertTrue(matches(other, f, allow_unknown=True))

    def test_unknowns_and_false_requirements(self):
        p = property(epc=None)
        f = Filters(epc_allowed=['A', 'B'])
        self.assertTrue(needs_details(p, f))
        self.assertTrue(matches(p, f, allow_unknown=True))
        self.assertTrue(matches(p, f))
        self.assertTrue(matches(property(terrace=True), Filters(required={'terrace': False})))

    def test_keywords_and_validation(self):
        self.assertFalse(matches(property(description='Reeds VERHUURD'), Filters(exclude_keywords=['verhuurd'])))
        for settings in [{'max_price': -1}, {'min_price': 20, 'max_price': 10}, {'max_prce': 100}, {'sources': {'typo': True}}, {'required': {'garden': 'false'}}]:
            with self.subTest(settings=settings), self.assertRaises(ValidationError):
                Filters.model_validate(settings)


    def test_terrace_or_garden(self):
        f = Filters(require_any=['terrace', 'garden'])
        cases = [
            (True, False, True, True, False),
            (False, True, True, True, False),
            (True, True, True, True, False),
            (True, None, True, True, False),
            (None, True, True, True, False),
            (False, False, False, False, False),
            (False, None, False, True, True),
            (None, False, False, True, True),
            (None, None, False, True, True),
        ]
        for terrace, garden, final, candidate, details in cases:
            with self.subTest(terrace=terrace, garden=garden):
                p = property(terrace=terrace, garden=garden)
                self.assertEqual(matches(p, f), final)
                self.assertEqual(matches(p, f, allow_unknown=True), candidate)
                self.assertEqual(needs_details(p, f), details)
        self.assertTrue(matches(property(terrace=False, garden=False), Filters()))
        self.assertFalse(matches(property(terrace=True, garden=False),
                                 Filters(require_any=['terrace', 'garden'], required={'garden': True})))
        with self.assertRaises(ValidationError):
            Filters(require_any=['terace'])


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')

    def tearDown(self):
        self.db.close()

    def test_id_and_canonical_fallback(self):
        first = self.db.observe(property())
        self.db.conn.execute("UPDATE listings SET last_seen='old'")
        self.assertEqual(first, self.db.observe(property(url='https://example.com/new-slug/123')))
        self.assertNotEqual(self.db.conn.execute('SELECT last_seen FROM listings').fetchone()[0], 'old')
        self.assertEqual(first, self.db.observe(property(source_listing_id=None, url='https://example.com/listing/123/?utm_source=test#photo')))
        self.assertNotEqual(first, self.db.observe(property(source='other', url='https://other.com/123')))
        self.assertEqual(canonical_url('https://example.com/?id=1&utm_source=x'), 'https://example.com?id=1')

    def test_per_recipient_and_uncertain_sends(self):
        key = self.db.observe(property())
        self.assertTrue(self.db.claim(key, 'one'))
        self.assertFalse(self.db.claim(key, 'one'))
        self.db.delivery(key, 'one', 'accepted', 'SM123')
        self.assertFalse(self.db.claim(key, 'one'))
        self.assertTrue(self.db.claim(key, 'two'))
        self.db.delivery(key, 'two', 'rejected')
        self.assertTrue(self.db.claim(key, 'two'))
        self.db.delivery(key, 'two', 'unknown')
        self.assertFalse(self.db.claim(key, 'two'))
        self.db.complete(key, ['one', 'two'])
        self.assertEqual(self.db.conn.execute('SELECT notification_sent FROM listings').fetchone()[0], 0)
        self.db.delivery(key, 'two', 'accepted', 'SM456')
        self.db.complete(key, ['one', 'two'])
        self.assertEqual(self.db.conn.execute('SELECT notification_sent FROM listings').fetchone()[0], 1)


class ParserTests(unittest.TestCase):
    def test_search_fixture(self):
        rows, pages, current = parse_search((FIXTURES / 'immoweb-search.html').read_text())
        self.assertEqual((len(rows), pages, current), (2, 3, 1))
        p = normalize(rows[0])
        self.assertEqual(p.postal_code, '2610')
        self.assertEqual(p.price, 295000)
        self.assertIsNone(p.garden)
        self.assertIn(str(rows[0]['id']), p.url)
        rows[0]['flags']['main'] = 'sold'
        self.assertIsNone(normalize(rows[0]))
        rows[0]['flags']['main'] = 'new'
        rows[0]['transaction']['type'] = 'FOR_RENT'
        self.assertIsNone(normalize(rows[0]))

    def test_detail_fixture(self):
        p = parse_detail((FIXTURES / 'immoweb-detail.html').read_text())
        self.assertEqual(p.source_listing_id, '21883664')
        self.assertEqual(p.epc, 'A')
        self.assertEqual(p.bathrooms, 1)
        self.assertEqual(p.description, 'Gerenoveerde woning met tuin.')
        self.assertFalse(p.lift)
        self.assertIsNone(p.garage)

    def test_unavailable_flags(self):
        rows, _, _ = parse_search((FIXTURES / 'immoweb-search.html').read_text())
        for flag in ('isUnderOption', 'isSoldOrRented'):
            for enabled in (False, True):
                row = copy.deepcopy(rows[0])
                row['flags'][flag] = enabled
                detail = '<script>window.classified = ' + json.dumps(row) + ';</script>'
                self.assertEqual(normalize(row) is None, enabled)
                self.assertEqual(parse_detail(detail) is None, enabled)

    def test_challenge_is_not_empty_results(self):
        for parser in (parse_search, parse_detail):
            with self.assertRaises(SourceError):
                parser('<html>Just a moment...</html>')
        self.assertEqual(parse_search(page([], count=0))[0], [])


class AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_pagination_and_repeat(self):
        rows, _, _ = parse_search((FIXTURES / 'immoweb-search.html').read_text())
        for repeated in [False, True]:
            requested = []
            def handler(request):
                if '/search/' not in request.url.path:
                    row = next(r for r in rows if str(r['id']) == request.url.path.rsplit('/', 1)[-1])
                    return httpx.Response(200, text='<script>window.classified = ' + json.dumps(row) + ';</script>')
                n = int(request.url.params['page'])
                requested.append(n)
                return httpx.Response(200, text=page([rows[0 if repeated else n-1]], n, count=2))
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                result = await ImmowebScraper(client).search(Filters())
            self.assertEqual(requested, [1, 2])
            self.assertEqual(len(result), 1 if repeated else 2)

    async def test_verify_candidate_availability_even_with_complete_search_data(self):
        rows, _, _ = parse_search((FIXTURES / 'immoweb-search.html').read_text())
        # Use the same ID in both fixtures for this routing test.
        rows[0]['id'] = 21883664
        for criteria, expected in [(Filters(), 2), (Filters(max_price=1), 1), (Filters(required={'lift': True}), 2)]:
            requests = []
            def handler(request):
                requests.append(request)
                return httpx.Response(200, text=page([rows[0]], count=1) if '/search/' in request.url.path else (FIXTURES / 'immoweb-detail.html').read_text())
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                await ImmowebScraper(client).search(criteria)
            self.assertEqual(len(requests), expected)

    async def test_stale_search_card_is_excluded_when_detail_under_option(self):
        rows, _, _ = parse_search((FIXTURES / 'immoweb-search.html').read_text())
        row = rows[0]
        row['flags']['isUnderOption'] = False
        detail = copy.deepcopy(row)
        detail['flags']['isUnderOption'] = True
        def handler(request):
            if '/search/' in request.url.path:
                return httpx.Response(200, text=page([row], count=1))
            return httpx.Response(200, text='<script>window.classified = ' + json.dumps(detail) + ';</script>')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            self.assertEqual(await ImmowebScraper(client).search(Filters()), [])

    async def test_gateway_format_payload_and_failure(self):
        s = SimpleNamespace(gateway_url='http://gateway:3000', gateway_key='secret',
                            gateway_session='default', gateway_timeout=60)
        p = property(title='Apartment', terrace=True, image_url='https://example.com/photo.jpg')
        msg = format_polish_message(p, {'title': p.title, 'description': p.description})
        self.assertIn('3255,1 €/m²', msg)
        self.assertIn('Taras: tak', msg)
        self.assertNotIn('None', msg)
        self.assertTrue(msg.endswith(p.url))
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(201, json={'id': 'true_32470222222@c.us_MESSAGE1', 'ack': 1})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            n = Notifier(s, client)
            self.assertEqual(await n.send(p, '+32470222222'), 'true_32470222222@c.us_MESSAGE1')
            self.assertEqual(json.loads(calls[0].content), {
                'session': 'default', 'chatId': '32470222222@c.us', 'text': msg, 'linkPreview': True})
            self.assertEqual(calls[0].url.path, '/api/sendText')
            self.assertEqual(calls[0].headers['X-Api-Key'], 'secret')
            self.assertNotIn('Authorization', calls[0].headers)
        for status, error in [(400, RejectedSend), (401, RejectedSend), (429, RejectedSend),
                              (408, AmbiguousSend), (503, AmbiguousSend), (302, AmbiguousSend)]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(status))) as client:
                with self.assertRaises(error):
                    await Notifier(s, client).send(p, '+32470222222')

    async def test_scan_partial_failure_retry_and_dry_run(self):
        class FakeScraper:
            def __init__(self, *args): pass
            async def search(self, config): return [property()]
        settings = SimpleNamespace(filters=lambda: Filters(sources={'immoweb': True}), concurrency=2,
                                   recipients=['+32470111111', '+32470222222'], gateway_url='http://gateway:3000',
                                   gateway_key='secret', gateway_session='default', gateway_timeout=60)
        calls = []
        def handler(request):
            if request.method == 'GET':
                return httpx.Response(200, json={'name': 'default', 'status': 'WORKING'})
            recipient = json.loads(request.content)['chatId']
            calls.append(recipient)
            if len(calls) == 2:
                return httpx.Response(400, json={'message': 'Rejected'})
            return httpx.Response(201, json={'id': 'true_32470111111@c.us_MESSAGE1'})
        db = Database(':memory:')
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with patch.dict('app.main.SCRAPERS', {'immoweb': FakeScraper}):
                    with patch('builtins.print'):
                        await scan(settings, client, None, True)
                    self.assertEqual(calls, [])
                    await scan(settings, client, db, False)
                    await scan(settings, client, db, False)
                    await scan(settings, client, db, False)
                    self.assertEqual(calls, ['32470111111@c.us', '32470222222@c.us', '32470222222@c.us'])
        finally:
            db.close()


if __name__ == '__main__':
    unittest.main()
