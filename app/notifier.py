import re
from app.gateway import WhatsAppGateway, RejectedSend, AmbiguousSend
from app.models import Property
from app.criteria import FEATURES, NUMERIC, CHOICES
from app.polish import polish_code


class MessageError(RuntimeError):
    pass


def format_polish_message(p, source_text):
    lines = ['🏠 NOWA NIERUCHOMOŚĆ']
    fields = [('address', '📍 Adres', ''), ('city', 'Miejscowość', ''),
              ('postal_code', 'Kod pocztowy', ''), ('price', '💰 Cena', ' €'),
              ('surface_m2', '📐 Powierzchnia', ' m²'), ('price_per_m2', 'Cena za m²', ' €/m²'),
              ('bedrooms', '🛏 Sypialnie', ''), ('bathrooms', '🛁 Łazienki', ''),
              ('epc', '⚡ Klasa EPC', ''), ('epc_value', 'Zużycie energii', ' kWh/(m²·rok)'),
              ('floor', 'Piętro', ''), ('monthly_common_costs', 'Miesięczne koszty wspólne', ' €'),
              ('terrace_m2', 'Powierzchnia tarasu', ' m²'), ('garden_m2', 'Powierzchnia ogrodu', ' m²')]
    if p.property_type:
        lines.append('Typ: ' + {'house': 'dom', 'apartment': 'mieszkanie'}.get(p.property_type, p.property_type))
    for field, label, unit in fields:
        value = getattr(p, field)
        if value is not None:
            value = (f'{value:.2f}'.rstrip('0').rstrip('.').replace('.', ',')
                     if isinstance(value, (int, float)) else str(value))
            lines.append(f'{label}: {value}{unit}')
    for field, label in [('terrace', 'Taras'), ('garden', 'Ogród'), ('garage', 'Garaż'),
                         ('parking', 'Parking'), ('lift', 'Winda')]:
        value = getattr(p, field)
        lines.append(f'{label}: ' + ('tak' if value is True else 'nie' if value is False else 'brak danych'))
    existing_numbers = {field for field, _, _ in fields}
    for field, (_, label, unit, _) in NUMERIC.items():
        value = getattr(p, field)
        if field not in existing_numbers and value is not None:
            lines.append(f'{label}: {value:g}{unit}')
    for field, (_, label) in FEATURES.items():
        value = getattr(p, field)
        if field not in {'terrace', 'garden', 'garage', 'parking', 'lift'} and value is not None:
            lines.append(f'{label}: ' + ('tak' if value else 'nie'))
    for field, (_, label) in CHOICES.items():
        value = getattr(p, field)
        if value is not None:
            display = polish_code(field, value)
            if display is not None:
                lines.append(f'{label}: {display}')
    if source_text.get('title'):
        lines += ['', source_text['title']]
    if source_text.get('description'):
        lines += ['', 'Opis ogłoszenia (język oryginalny):', source_text['description']]
    return '\n'.join(lines + ['', p.url])



def whatsapp(number):
    """Canonical recipient key, compatible with existing SQLite delivery records."""
    number = number.strip().removeprefix('whatsapp:')
    if re.fullmatch(r'[1-9]\d*(?:-\d+)?@g\.us', number):
        return number
    if not re.fullmatch(r'\+[1-9]\d{6,14}', number):
        raise ValueError('WhatsApp destination must be an international phone number (+32470123456) or a group ID (120363123456789@g.us)')
    return 'whatsapp:' + number


class Notifier:
    def __init__(self, settings, client, db=None):
        self.gateway = WhatsAppGateway(settings, client)
        self.messages = {}

    async def prepare(self, p):
        if p.id not in self.messages:
            self.messages[p.id] = format_polish_message(p, {'title': p.title, 'description': p.description})
            if len(self.messages[p.id]) > 60000:
                self.messages.pop(p.id)
                raise MessageError('Listing exceeds the alert text limit; alert deferred without truncation')
        return self.messages[p.id]

    async def ensure_ready(self):
        await self.gateway.ensure_ready()

    async def send(self, p: Property, recipient: str):
        return await self.gateway.send_text(await self.prepare(p), recipient)
