"""
Base class for browser-based scrapers that can handle Cloudflare protections.
This implements the patterns for using headless browsers to bypass security.
"""
import asyncio
import logging
import time
from typing import List, Optional, Dict, Any
from playwright.async_api import async_playwright, Playwright, BrowserContext, Page
from app.scrapers.base import PropertyScraper, SourceError

log = logging.getLogger(__name__)

class BrowserScraper(PropertyScraper):
    """Base class for crawlers that use browser automation to bypass Cloudflare"""
    
    def __init__(self, client):
        super().__init__(client)
        self.playwright_instance: Optional[Playwright] = None
        self.browser_context: Optional[BrowserContext] = None
        self.last_request_time: float = 0
        self.request_interval: float = 3600  # Default 1 hour between requests
        
    def set_request_interval(self, seconds: int):
        """Set minimum time between requests (default 1 hour)"""
        self.request_interval = seconds
        
    async def _ensure_min_interval(self):
        """Ensure minimum time interval between requests"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.request_interval:
            sleep_time = self.request_interval - time_since_last
            log.info("Waiting %d seconds to respect rate limit", int(sleep_time))
            await asyncio.sleep(sleep_time)
            
        self.last_request_time = time.time()
    
    async def _setup_browser(self) -> BrowserContext:
        """Setup browser context with proper headers and settings"""
        if not self.playwright_instance:
            self.playwright_instance = await async_playwright().start()
            
        # Launch browser (headless)
        browser = await self.playwright_instance.chromium.launch(
            headless=True,
            timeout=30000  # 30 second timeout for browser operations
        )
        
        # Create context with realistic settings  
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='en-US', 
            timezone_id='Europe/Brussels'
        )
        
        # Add custom headers that mimic real browser behavior
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
        """)
        
        return context
    
    async def _teardown_browser(self):
        """Clean up browser resources"""
        try:
            if self.browser_context:
                await self.browser_context.close()
            if self.playwright_instance:
                await self.playwright_instance.stop()
        except Exception as e:
            log.warning("Error during browser teardown: %s", e)
    
    async def _get_page_content(self, url: str, max_retries: int = 3) -> str:
        """Retrieve page content with retry logic"""
        
        # Enforce minimum interval between requests
        await self._ensure_min_interval()
        
        for attempt in range(max_retries):
            try:
                if not self.browser_context:
                    self.browser_context = await self._setup_browser()
                
                page = await self.browser_context.new_page()
                
                # Navigate to the URL with proper timeout
                await page.goto(url, wait_until='networkidle', timeout=30000)
                
                # Wait for page to load properly (allowing for JavaScript execution)
                await page.wait_for_timeout(2000)
                
                html_content = await page.content()
                
                await page.close()
                
                # Verify we got some content
                if html_content and len(html_content) > 100:
                    return html_content
                else:
                    log.warning("Page returned minimal content on attempt %d", attempt + 1)
                    
            except Exception as e:
                log.warning("Error fetching page (attempt %d): %s", attempt + 1, str(e))
                if attempt < max_retries - 1:  # Don't wait on last attempt
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                else:
                    raise SourceError(f"Browser scraping failed after {max_retries} attempts: {str(e)}")
        
        raise SourceError("Failed to retrieve content from browser after all retries")

    async def search(self, config):
        """
        Placeholder for specific implementation in child classes.
        This method should be overridden by implementing classes.
        For Cloudflare-protected sites, will use browser automation.
        """
        raise NotImplementedError("This must be implemented by child classes")