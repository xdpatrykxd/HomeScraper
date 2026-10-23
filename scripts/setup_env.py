"""Initialize local gateway settings without exposing or replacing existing recipients."""
from pathlib import Path
import platform
import re
import secrets


def setup(path=Path('.env')):
    if not path.exists():
        path.write_text(Path('.env.example').read_text())
    lines = path.read_text().splitlines()
    # Remove obsolete provider credentials when migrating an existing installation.
    lines = [line for line in lines if not re.match(r'\s*(?:export\s+)?TWILIO_[A-Z_]+\s*=', line)
             and not ('Approved WhatsApp template required' in line)]

    def value(name):
        for line in reversed(lines):
            match = re.match(rf'\s*(?:export\s+)?{re.escape(name)}\s*=\s*(.*)', line)
            if match:
                return match[1].strip().strip('"\'')
        return ''

    def set_value(name, text):
        nonlocal lines
        lines = [line for line in lines if not re.match(rf'\s*(?:export\s+)?{re.escape(name)}\s*=', line)]
        lines.append(f'{name}={text}')

    if not value('WAHA_API_KEY'):
        set_value('WAHA_API_KEY', secrets.token_hex(32))
    arm = platform.machine().lower() in {'arm64', 'aarch64'}
    image = value('WAHA_IMAGE')
    if not image or image in {'devlikeapro/waha:noweb', 'devlikeapro/waha:noweb-arm'}:
        desired_image = 'devlikeapro/waha:noweb-arm' if arm else 'devlikeapro/waha:noweb'
        if image != desired_image:
            set_value('WAHA_IMAGE', desired_image)
    defaults = {
        'WHATSAPP_GATEWAY_ENGINE': 'GOWS',
        'WHATSAPP_GATEWAY_URL': 'http://127.0.0.1:3010',
        'WHATSAPP_GATEWAY_PORT': '3010',
        'WHATSAPP_SESSION': 'default',
        'WHATSAPP_GATEWAY_TIMEOUT_SECONDS': '60',
    }
    for name, default in defaults.items():
        if not value(name):
            set_value(name, default)
    path.write_text('\n'.join(lines) + '\n')
    path.chmod(0o600)
    print(f'{path} configured for the local WhatsApp gateway. Existing recipients and search settings preserved.')
    print('Start whatsapp-gateway and follow README.md to pair and configure phone or group destinations.')


if __name__ == '__main__':
    setup()
