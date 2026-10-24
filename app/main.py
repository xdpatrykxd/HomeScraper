import argparse
import asyncio
import fcntl
import hmac
import json
import logging
import signal
import sys
import threading
from dataclasses import fields
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import httpx
from app.config import Settings
from app.database import Database
from app.filters import matches
from app.models import Property
from app.notifier import Notifier, RejectedSend, AmbiguousSend, MessageError, whatsapp
from app.scrapers.immoweb import ImmowebScraper
from app.scrapers.zimmo import ZimmoScraper
from app.scrapers.realo import RealoScraper
from app.scrapers.immovlan import ImmovlanScraper
from app.scrapers.immoscoop import ImmoscoopScraper
from app.scrapers.immomarkt import ImmomarktScraper

log = logging.getLogger(__name__)
SCRAPERS = {'immoweb': ImmowebScraper, 'zimmo': ZimmoScraper, 'realo': RealoScraper, 'immovlan': ImmovlanScraper, 'immoscoop': ImmoscoopScraper, 'immomarkt': ImmomarktScraper}
SOURCE_HOSTS = {
    'immoweb': {'immoweb.be'}, 'zimmo': {'zimmo.be'}, 'realo': {'realo.be'},
    'immovlan': {'immovlan.be'}, 'immoscoop': {'immoscoop.be'}, 'immomarkt': {'immomarkt.be'},
}


def ingest_missing_fields(p, config):
    missing = []
    if not p.title:
        missing.append('title')
    if (config.include_keywords or config.exclude_keywords) and not p.description:
        missing.append('description')
    if (config.min_price is not None or config.max_price is not None) and p.price is None:
        missing.append('price')
    if (config.min_surface_m2 is not None or config.max_surface_m2 is not None) and p.surface_m2 is None:
        missing.append('surface_m2')
    if (config.min_bedrooms is not None or config.max_bedrooms is not None) and p.bedrooms is None:
        missing.append('bedrooms')
    if config.postal_codes and p.postal_code is None:
        missing.append('postal_code')
    if config.property_types and p.property_type is None:
        missing.append('property_type')
    if config.require_any and not any(getattr(p, name) is True for name in config.require_any):
        missing.append('confirmed ' + ' or '.join(config.require_any))
    return missing


def serve_ingest(settings, client, db, loop):
    if not settings.ingest_token:
        raise ValueError('Set INGEST_API_TOKEN to enable the Tampermonkey ingest API')
    allowed = {field.name for field in fields(Property)}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            log.info('[INGEST] ' + fmt, *args)

        def respond(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != '/api/listings':
                return self.respond(404, {'error': 'not found'})
            if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + settings.ingest_token):
                return self.respond(401, {'error': 'unauthorized'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 2 or length > 1_000_000:
                    raise ValueError('body size must be 2..1000000 bytes')
                raw = json.loads(self.rfile.read(length))
                data = raw.get('listing') if isinstance(raw, dict) else None
                if not isinstance(data, dict) or set(data) - allowed:
                    raise ValueError('listing object has invalid fields')
                from urllib.parse import urlsplit
                source = data.get('source')
                host = (urlsplit(str(data.get('url', ''))).hostname or '').lower()
                if source not in SOURCE_HOSTS or not any(host == domain or host.endswith('.' + domain) for domain in SOURCE_HOSTS[source]):
                    raise ValueError('listing source and URL host do not match a supported property site')
                if urlsplit(str(data.get('url', ''))).scheme != 'https' or not data.get('source_listing_id'):
                    raise ValueError('listing requires an ID and an HTTPS listing URL')
                p = Property(**data)
                config = settings.filters()
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.respond(400, {'error': str(exc)})
            missing = ingest_missing_fields(p, config)
            if not config.sources.get(source, False):
                return self.respond(200, {'accepted': True, 'matched': False, 'reason': 'source disabled in filters'})
            if missing:
                return self.respond(200, {'accepted': True, 'matched': False, 'missing': missing})
            if p.price is not None and p.price < 10000:
                return self.respond(200, {'accepted': True, 'matched': False, 'reason': 'price below residential sanity floor'})
            if not matches(p, config):
                return self.respond(200, {'accepted': True, 'matched': False})
            try:
                asyncio.run_coroutine_threadsafe(deliver(settings, client, db, p), loop).result()
            except Exception as exc:
                log.error('[INGEST] Delivery failed: %s', exc)
                return self.respond(503, {'error': 'delivery failed'})
            return self.respond(200, {'accepted': True, 'matched': True, 'id': p.id})

    server = ThreadingHTTPServer((settings.ingest_host, settings.ingest_port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name='listing-ingest', daemon=True).start()
    log.info('[INGEST] Listening on %s:%d', settings.ingest_host, settings.ingest_port)
    return server


async def deliver(settings, client, db, p):
    recipients = list(dict.fromkeys(whatsapp(r) for r in settings.recipients))
    if not recipients:
        raise RuntimeError('No WhatsApp recipients configured')
    notifier = Notifier(settings, client, db)
    await notifier.ensure_ready()
    listing_id = db.observe(p)
    if not any(db.pending(listing_id, recipient) for recipient in recipients):
        return
    try:
        await notifier.prepare(p)
    except MessageError as exc:
        log.error('[NOTIFICATION] %s: %s', p.source_listing_id, exc)
        return
    for index, recipient in enumerate(recipients, 1):
        if not matches(p, settings.filters()):
            break
        if not db.claim(listing_id, recipient):
            continue
        try:
            sid = await notifier.send(p, recipient)
        except RejectedSend as exc:
            db.delivery(listing_id, recipient, 'rejected')
            log.error('[WHATSAPP] Recipient %d: %s', index, exc)
        except AmbiguousSend as exc:
            db.delivery(listing_id, recipient, 'unknown')
            log.error('[WHATSAPP] Recipient %d: %s; automatic retry suppressed', index, exc)
        else:
            db.delivery(listing_id, recipient, 'accepted', sid)
            log.info('[WHATSAPP] Accepted for recipient %d (%s)', index, sid)
    db.complete(listing_id, recipients)


async def scan(settings, client, db, dry_run):
    config = settings.filters()  # Reload criteria each cycle.
    enabled = [name for name, enabled in config.sources.items() if enabled]
    if not enabled:
        raise ValueError('Enable at least one property source in filters.yaml')
    results = await asyncio.gather(*(SCRAPERS[name](client, settings.concurrency).search(config) for name in enabled), return_exceptions=True)
    success = 0
    properties = {}
    for name, result in zip(enabled, results):
        if isinstance(result, Exception):
            log.error('[%s] %s', name.upper(), result)
            continue
        success += 1
        properties.update((p.id, p) for p in result)
    if not success:
        raise RuntimeError('All enabled sources failed; no successful scan')
    matching = [p for p in properties.values() if matches(p, config)]
    log.info('[FILTER] %d matching properties', len(matching))
    notifier = Notifier(settings, client, db)
    if matching and not dry_run:
        # Check before claiming any deliveries so an unpaired device cannot strand alerts.
        await notifier.ensure_ready()
    deliveries_ok = True
    recipients = list(dict.fromkeys(whatsapp(r) for r in settings.recipients))
    for p in matching:
        if dry_run:
            print(await notifier.prepare(p), '\n', flush=True)
            continue
        listing_id = db.observe(p)
        if not any(db.pending(listing_id, recipient) for recipient in recipients):
            continue
        try:
            await notifier.prepare(p)
        except MessageError as exc:
            deliveries_ok = False
            log.error('[NOTIFICATION] %s: %s', p.source_listing_id, exc)
            continue
        for index, recipient in enumerate(recipients, 1):
            # A scan can take long enough for the user to edit criteria.
            # Revalidate against the latest file before each irreversible send.
            if not matches(p, settings.filters()):
                log.info('[FILTER] %s skipped: latest criteria no longer match', p.source_listing_id)
                break
            if not db.claim(listing_id, recipient):
                continue
            log.info('[NEW] %s %s', p.title, f'€{p.price:g}' if p.price is not None else '')
            try:
                sid = await notifier.send(p, recipient)
            except RejectedSend as exc:
                deliveries_ok = False
                db.delivery(listing_id, recipient, 'rejected')
                log.error('[WHATSAPP] Recipient %d: %s', index, exc)
            except AmbiguousSend as exc:
                deliveries_ok = False
                db.delivery(listing_id, recipient, 'unknown')
                log.error('[WHATSAPP] Recipient %d: %s; automatic retry suppressed', index, exc)
            else:
                db.delivery(listing_id, recipient, 'accepted', sid)
                log.info('[WHATSAPP] Accepted for recipient %d (%s)', index, sid)
        db.complete(listing_id, recipients)
    return success == len(enabled) and deliveries_ok


async def run(args):
    settings = Settings()
    if not args.dry_run and not settings.ingest_token:
        settings.validate_whatsapp()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    async with httpx.AsyncClient(timeout=settings.timeout, follow_redirects=True,
                                 limits=httpx.Limits(max_connections=settings.concurrency),
                                 headers={'User-Agent': 'BelgianPropertyWatcher/1.0 (private property search)'}) as client:
        if args.test_whatsapp:
            notifier = Notifier(settings, client)
            await notifier.ensure_ready()
            test = Property('test', 'test', 'https://www.immoweb.be/', title='Property watcher test', city='Belgium')
            for index, recipient in enumerate(dict.fromkeys(whatsapp(r) for r in settings.recipients), 1):
                sid = await notifier.send(test, recipient)
                log.info('[WHATSAPP] Test accepted for recipient %d (%s)', index, sid)
            return 0
        db, lock, ingest_server = None, None, None
        scheduled_scanning = True
        try:
            if not args.dry_run:
                settings.database_path.parent.mkdir(parents=True, exist_ok=True)
                lock = open(str(settings.database_path) + '.lock', 'a')
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise RuntimeError('Another watcher is already using this database') from None
                db = Database(settings.database_path)
                if settings.ingest_token:
                    ingest_server = serve_ingest(settings, client, db, asyncio.get_running_loop())
                    try:
                        settings.validate_whatsapp()
                    except ValueError as exc:
                        log.warning('[INGEST] API is active; scheduled scanning disabled: %s', exc)
                        scheduled_scanning = False
            while scheduled_scanning and not stop.is_set():
                try:
                    healthy = await scan(settings, client, db, args.dry_run)
                except Exception as exc:
                    log.error('[SCAN] %s', exc)
                    healthy = False
                if args.once:
                    return 0 if healthy else 1
                log.info('[SLEEP] Next scan in %g minutes', settings.interval)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=settings.interval * 60)
                except TimeoutError:
                    pass
            if not scheduled_scanning:
                await stop.wait()
            return 0
        finally:
            if db:
                if ingest_server:
                    ingest_server.shutdown()
                db.close()
            if lock:
                lock.close()


def main():
    parser = argparse.ArgumentParser(description='Watch active Belgian properties')
    parser.add_argument('--once', action='store_true', help='Run one scan')
    parser.add_argument('--dry-run', action='store_true', help='Print matches without sending or writing to SQLite')
    parser.add_argument('--test-whatsapp', action='store_true', help='Send a test to configured recipients')
    args = parser.parse_args()
    if args.test_whatsapp and (args.dry_run or args.once):
        parser.error('--test-whatsapp cannot be combined with --dry-run or --once')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    try:
        return asyncio.run(run(args))
    except (ValueError, RuntimeError, OSError, RejectedSend, AmbiguousSend) as exc:
        log.error('%s', exc)
        return 1


if __name__ == '__main__':
    sys.exit(main())
