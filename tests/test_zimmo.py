import unittest
from unittest.mock import AsyncMock
import asyncio

from app.scrapers.zimmo import ZimmoScraper
from app.models import Property
from app.config import Filters
from app.scrapers.base import SourceError


class TestZimmoScraper(unittest.IsolatedAsyncioTestCase):
    
    async def test_scraper_instantiation(self):
        """Test that Zimmo scraper can be instantiated"""
        client = AsyncMock()
        scraper = ZimmoScraper(client)
        self.assertIsInstance(scraper, ZimmoScraper)
        
    async def test_search_raises_source_error(self):
        """Test that search raises a SourceError due to Cloudflare challenge"""
        client = AsyncMock()
        scraper = ZimmoScraper(client)
        
        # Test with mock config
        config = type('Config', (), {
            'postal_codes': [],
            'min_price': None,
            'max_price': None,
            'property_types': ['house']
        })()
        
        # The search method is async, so we need to await it
        with self.assertRaises(SourceError) as context:
            # This will raise SourceError since implementation doesn't work yet
            await scraper.search(config)
            
        # We expect a SourceError or similar error due to Cloudflare protection
        self.assertIn("Cloudflare", str(context.exception))
        
    async def test_scraper_structure(self):
        """Test that the scraper structure is consistent with other scrapers"""
        client = AsyncMock()
        scraper = ZimmoScraper(client)
        
        # Check we have the required methods
        self.assertTrue(hasattr(scraper, 'search'))
        self.assertTrue(callable(getattr(scraper, 'search')))
        self.assertTrue(hasattr(scraper, 'get'))
        self.assertTrue(callable(getattr(scraper, 'get')))


if __name__ == '__main__':
    unittest.main()