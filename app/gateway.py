"""WAHA HTTP client and linked-device setup commands."""
import argparse
import asyncio
import logging
from pathlib import Path
from urllib.parse import quote

import httpx


class GatewayError(RuntimeError):
    pass


class RejectedSend(Exception):
    """Gateway explicitly refused the request; a later scan may retry."""


class AmbiguousSend(Exception):
    """A send may have reached WhatsApp; never retry automatically."""


def chat_id(number: str) -> str:
    # Accept the existing phone-number notation so delivery records retain their identity.
    from app.notifier import whatsapp
    recipient = whatsapp(number)
    return recipient if recipient.endswith('@g.us') else recipient.removeprefix('whatsapp:+') + '@c.us'


def parse_groups(data):
    """Normalize documented engine-specific group lists without exposing members."""
    from app.notifier import whatsapp
    if isinstance(data, list):
        rows = [(None, group) for group in data]
    elif isinstance(data, dict):
        rows = list(data.items())
    else:
        raise GatewayError('Invalid gateway group-list response')
    groups = []
    for key, group in rows:
        if not isinstance(group, dict):
            raise GatewayError('Invalid group object in gateway response')
        group_id = group.get('JID') or group.get('id') or key
        if isinstance(group_id, dict):
            group_id = group_id.get('_serialized')
        try:
            if not isinstance(group_id, str) or not whatsapp(group_id).endswith('@g.us'):
                raise ValueError()
            group_id = whatsapp(group_id)
        except ValueError as exc:
            raise GatewayError('Invalid group ID in gateway response') from exc
        name = group.get('Name') or group.get('subject') or group.get('name') or 'Unnamed group'
        if not isinstance(name, str):
            raise GatewayError('Invalid group name in gateway response')
        groups.append({'id': group_id, 'name': name})
    return groups


class WhatsAppGateway:
    def __init__(self, settings, client):
        self.settings = settings
        self.client = client
        self.base_url = settings.gateway_url.rstrip('/')
        self.session = quote(settings.gateway_session, safe='')
        self.headers = {'X-Api-Key': settings.gateway_key, 'Accept': 'application/json'}

    async def request(self, method, path, **kwargs):
        try:
            return await self.client.request(method, self.base_url + path,
                headers=self.headers, timeout=self.settings.gateway_timeout,
                follow_redirects=False, **kwargs)
        except httpx.RequestError as exc:
            raise GatewayError('WhatsApp gateway unreachable; start the gateway and check WHATSAPP_GATEWAY_URL') from exc

    @staticmethod
    def check(response, action):
        if response.status_code in {401, 403}:
            raise GatewayError('WhatsApp gateway rejected the API key; check WAHA_API_KEY')
        if not response.is_success:
            raise GatewayError(f'WhatsApp gateway {action} failed (HTTP {response.status_code}); check gateway logs')

    async def status(self):
        response = await self.request('GET', f'/api/sessions/{self.session}')
        if response.status_code == 404:
            return None
        self.check(response, 'session lookup')
        try:
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get('status'), str):
                raise ValueError('Missing session status')
            return data['status']
        except ValueError as exc:
            raise GatewayError('Invalid gateway session response') from exc

    async def ensure_ready(self):
        status = await self.status()
        if status != 'WORKING':
            raise GatewayError(f'WhatsApp session {self.settings.gateway_session!r} is {status or "not created"}; run python -m app.gateway pair and scan its QR code')

    async def list_groups(self, page_size=100):
        await self.ensure_ready()
        groups = {}
        offset = 0
        while True:
            response = await self.request('GET', f'/api/{self.session}/groups', params={
                'limit': page_size, 'offset': offset, 'sortBy': 'id', 'sortOrder': 'asc',
                'exclude': 'participants',
            })
            self.check(response, 'group listing')
            try:
                page = parse_groups(response.json())
            except ValueError as exc:
                raise GatewayError('Invalid gateway group-list JSON') from exc
            if page and all(group['id'] in groups for group in page):
                raise GatewayError('Gateway repeated a group-list page; group discovery is incomplete')
            groups.update((group['id'], group) for group in page)
            if len(page) < page_size:
                return list(groups.values())
            offset += len(page)

    async def pair(self, qr_path: Path, wait_seconds=30):
        status = await self.status()
        if status is None:
            response = await self.request('POST', '/api/sessions', json={
                'name': self.settings.gateway_session, 'start': True,
            })
            self.check(response, 'session creation')
        elif status == 'STOPPED':
            response = await self.request('POST', f'/api/sessions/{self.session}/start')
            self.check(response, 'session start')
        elif status == 'FAILED':
            # Pairing attempts expire and leave NOWEB in FAILED. Restart the session
            # without deleting its stored credentials, then request its current QR.
            response = await self.request('POST', f'/api/sessions/{self.session}/restart')
            self.check(response, 'session restart')
        deadline = asyncio.get_running_loop().time() + wait_seconds
        while True:
            status = await self.status()
            if status == 'WORKING':
                print('WhatsApp session WORKING — already linked.')
                return
            if status in {'SCAN_QR_CODE', 'SCAN_QR'}:
                response = await self.request('GET', f'/api/{self.session}/auth/qr',
                                              params={'format': 'image'})
                self.check(response, 'QR fetch')
                try:
                    # WAHA returns a base64 PNG when Accept is application/json.
                    import base64
                    data = response.json()
                    png = base64.b64decode(data['data'], validate=True)
                    if not png.startswith(b'\x89PNG\r\n\x1a\n'):
                        raise ValueError('Not a PNG image')
                except (ValueError, KeyError, TypeError) as exc:
                    raise GatewayError('Invalid gateway QR image response') from exc
                qr_path.parent.mkdir(parents=True, exist_ok=True)
                qr_path.write_bytes(png)
                qr_path.chmod(0o600)
                print(f'QR saved to {qr_path}. Open it and scan from WhatsApp → Linked devices → Link a device.')
                print('Run the status command after scanning. If the QR expires, run pair again.')
                return
            if status not in {'STARTING', 'STOPPED', None}:
                raise GatewayError(f'Session is {status}; inspect gateway logs for the required authentication step')
            if asyncio.get_running_loop().time() >= deadline:
                raise GatewayError(f'Session is still {status}; run pair again once the gateway finishes starting')
            await asyncio.sleep(1)

    async def send_text(self, text, recipient):
        # This POST has no automatic retries, including after a network timeout.
        payload = {'session': self.settings.gateway_session, 'chatId': chat_id(recipient),
                   'text': text, 'linkPreview': True}
        try:
            response = await self.client.post(self.base_url + '/api/sendText', json=payload,
                headers=self.headers, timeout=self.settings.gateway_timeout, follow_redirects=False)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise RejectedSend('Could not connect to WhatsApp gateway; no send request was submitted') from exc
        except httpx.RequestError as exc:
            raise AmbiguousSend('Gateway connection failed during submission; check the WhatsApp chat before retrying') from exc
        if 400 <= response.status_code < 500 and response.status_code != 408:
            raise RejectedSend(f'WhatsApp gateway rejected request (HTTP {response.status_code})')
        if not response.is_success:
            raise AmbiguousSend(f'Unexpected gateway HTTP {response.status_code}; check gateway logs and the WhatsApp chat')
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError('Expected a message object')
            message_id = result.get('id')
            if not isinstance(message_id, str) or not message_id.strip():
                raise ValueError('Missing message ID')
        except ValueError as exc:
            raise AmbiguousSend('Invalid gateway send response; check the WhatsApp chat before retrying') from exc
        if result.get('ack') == -1:
            raise RejectedSend('WhatsApp reported a failed message acknowledgement')
        return message_id


async def run(args):
    from app.config import Settings
    settings = Settings()
    settings.validate_gateway()
    async with httpx.AsyncClient() as client:
        gateway = WhatsAppGateway(settings, client)
        if args.command == 'pair':
            path = args.qr_file or settings.database_path.parent / 'whatsapp-qr.png'
            await gateway.pair(path)
            return 0
        if args.command == 'groups':
            groups = await gateway.list_groups()
            if not groups:
                print('No groups found. Add the linked sender account to your group in WhatsApp, then run this command again.')
            for group in groups:
                print(f"{group['id']}\t{' '.join(group['name'].split())}")
            return 0
        status = await gateway.status()
        print(f'WhatsApp session {settings.gateway_session}: {status or "not created"}')
        return 0 if status == 'WORKING' else 1


def main():
    parser = argparse.ArgumentParser(description='Set up the linked WhatsApp device (WAHA)')
    parser.add_argument('command', choices=['pair', 'status', 'groups'])
    parser.add_argument('--qr-file', type=Path, help='QR PNG output path (default: data/whatsapp-qr.png)')
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except (ValueError, OSError, GatewayError) as exc:
        logging.error('%s', exc)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
