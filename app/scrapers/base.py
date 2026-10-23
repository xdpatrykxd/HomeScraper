import asyncio
from abc import ABC, abstractmethod
import httpx


class SourceError(Exception):
    pass


class PropertyScraper(ABC):
    def __init__(self, client, concurrency=4):
        self.client = client
        self.semaphore = asyncio.Semaphore(concurrency)

    async def get(self, url, **kwargs):
        for attempt in range(3):
            try:
                async with self.semaphore:
                    response = await self.client.get(url, **kwargs)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    retry = response.headers.get('Retry-After', '')
                    await asyncio.sleep(min(float(retry), 30) if retry.isdigit() else 2 ** attempt)
                    continue
                response.raise_for_status()
                return response.text
            except httpx.RequestError:
                if attempt == 2:
                    raise SourceError('Network failure after three attempts') from None
                await asyncio.sleep(2 ** attempt)
            except httpx.HTTPStatusError as exc:
                raise SourceError(f'HTTP {exc.response.status_code}; public access unavailable') from None

    @abstractmethod
    async def search(self, config):
        """Return current normalized listings or raise SourceError."""
