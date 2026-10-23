import unittest
from unittest.mock import AsyncMock
import asyncio

from app.scrapers.immomarkt import ImmomarktScraper
from app.models import Property
from app.config import Filters
from app.scrapers.base import SourceError


class TestImmomarktScraper(unittest.IsolatedAsyncioTestCase):
    
    async def test_scraper_instantiation(self):
        """Test that Immomarkt scraper can be instantiated"""
        client = AsyncMock()
        scraper = ImmomarktScraper(client)
        self.assertIsInstance(scraper, ImmomarktScraper)
        
    async def test_search_raises_source_error(self):
        """Test that search raises a SourceError due to Cloudflare/authorization issues"""
        client = AsyncMock()
        scraper = ImmomarktScraper(client)
        
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
            
        # We expect a SourceError related to the Cloudflare protection or API restriction 
        self.assertIn("Cloudflare", str(context.exception) or "adapter unavailable" in str(context.exception).lower())
        
    async def test_scraper_structure(self):
        """Test that the scraper structure is consistent with other scrapers"""
        client = AsyncMock()
        scraper = ImmomarktScraper(client)
        
        # Check we have the required methods
        self.assertTrue(hasattr(scraper, 'search'))
        self.assertTrue(callable(getattr(scraper, 'search')))
        self.assertTrue(hasattr(scraper, 'get'))
        self.assertTrue(callable(getattr(scraper, 'get')))


if __name__ == '__main__':
    unittest.main()