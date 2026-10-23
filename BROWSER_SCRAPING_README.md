# Browser-Based Scrolling Implementation

This document explains how to implement browser automation for Cloudflare-protected Belgian real estate sites.

## Approach Overview

To successfully scrape sites like immovlan.be, immoscoop.be, and immomarkt.be we use:

1. **Playwright** - Headless browser automation with Cloudflare bypass capabilities
2. **Browser Configuration** - Settings that mimic real browser behavior 
3. **Retry Logic** - Handle temporary Cloudflare challenges

## Implementation Details

### 1. Dependencies

Add Playwright to requirements:
```txt
playwright>=1.30,<1.31
```

Install with:
```bash
pip install playwright
playwright install chromium
```

### 2. Key Features of Browser Scraper

- **Cloudflare Bypass**: Custom headers and browser configuration
- **Retry Logic**: Handle network challenges gracefully  
- **Rate Limiting**: Respects site loading requirements
- **Error Handling**: Graceful failure with informative messages

### 3. Testing Strategy

1. Set rate limiting to minimal requests (e.g., 1-2 per minute)
2. Use random delays between requests 
3. Monitor for browser automation detection
4. Log page content for verification

### 4. Example Usage in Code

```python
# Test approach - would be run with limited frequency
from app.scrapers.immovlan import ImmovlanScraper
import asyncio

async def test_immovlan():
    client = httpx.AsyncClient()
    scraper = ImmovlanScraper(client)
    
    # Configure minimal search parameters 
    config = type('Config', (), {
        'postal_codes': [],
        'min_price': None,
        'max_price': None,  
        'property_types': ['house']
    })()
    
    try:
        result = await scraper.search(config)  
        print("Scraping successful!")
    except SourceError as e:
        print(f"Failed: {e}")
```

## Important Considerations

### Rate Limits
- Start with very slow requests (10+ seconds between)
- Monitor for IP blocking  
- Consider using rotating proxies if needed

### Legal Considerations
- Check each site's robots.txt and terms of service 
- Respect fair use guidelines
- Consider official APIs or partnerships instead of scraping

### Performance Optimization
- Use browser context reuse when possible  
- Implement smart caching of successful requests
- Monitor execution times carefully

## Testing Procedure

1. **Phase 1**: Run with minimal request frequency (1-2 per hour) 
2. **Phase 2**: If successful, gradually increase to normal usage
3. **Phase 3**: Add proper error handling and logging for production

This implementation follows the existing code patterns in the project while adding cloud-aware capabilities for scraping protected sites.