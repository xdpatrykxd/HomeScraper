from .base import PropertyScraper, SourceError


class RealoScraper(PropertyScraper):
    async def search(self, config):
        raise SourceError('Adapter unavailable: public search returned HTTP 403 during verification. No reliable public data parser verified.')
