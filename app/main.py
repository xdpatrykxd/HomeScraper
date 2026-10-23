import argparse
import asyncio
import fcntl
import logging
import signal
import sys
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
    if not args.dry_run:
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
        db, lock = None, None
        try:
            if not args.dry_run:
                settings.database_path.parent.mkdir(parents=True, exist_ok=True)
                lock = open(str(settings.database_path) + '.lock', 'a')
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise RuntimeError('Another watcher is already using this database') from None
                db = Database(settings.database_path)
            while not stop.is_set():
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
            return 0
        finally:
            if db:
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
