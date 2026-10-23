from .base import PropertyScraper, SourceError


class ZimmoScraper(PropertyScraper):
    async def search(self, config):
        raise SourceError('Adapter unavailable: public search returned a Cloudflare browser challenge during verification. No bypass implemented.')
