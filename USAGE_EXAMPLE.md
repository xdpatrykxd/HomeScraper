# Usage Example: Browser-Based Scraping with Rate Limiting

## Configuring Time-Based Caps

You can set specific time intervals between requests using the `set_request_interval()` method:

### Example 1: 2-hour cap between requests
```python
from app.scrapers.immovlan import ImmovlanScraper
from app.scrapers.immoscoop import ImmoscoopScraper  
from app.scrapers.immomarkt import ImmomarktScraper

# Create scrapers with custom request intervals (in seconds)
immovlan_scraper = ImmovlanScraper(httpx.AsyncClient())
immovlan_scraper.set_request_interval(7200)  # 2 hours between requests

immoscoop_scraper = ImmoscoopScraper(httpx.AsyncClient()) 
immoscoop_scraper.set_request_interval(7200)  # 2 hours between requests

immomarkt_scraper = ImmomarktScraper(httpx.AsyncClient())
immomarkt_scraper.set_request_interval(7200)  # 2 hours between requests
```

### Example 2: 6-hour cap (for more conservative approach)
```python
# For maximum safety, set 6-hour intervals
immovlan_scraper.set_request_interval(21600)  # 6 hours
immoscoop_scraper.set_request_interval(21600)  # 6 hours  
immomarkt_scraper.set_request_interval(21600)  # 6 hours
```

### Example 3: Configuration-based approach
```python
import os

# Set via environment variable
REQUEST_INTERVAL = int(os.getenv('REQUEST_INTERVAL_SECONDS', '3600'))  # Default 1 hour

scraper = ImmovlanScraper(httpx.AsyncClient())
scraper.set_request_interval(REQUEST_INTERVAL)
```

## How Rate Limiting Works in Practice

The rate limiting implements:

### 1. **Minimum Time Between Requests**
- Before each request, checks if minimum time has passed
- Automatically waits if needed to respect the cap

### 2. **Exponential Backoff on Failures**
- If a request fails, will retry with increasing delays
- Still respects the rate limiting even during retries

### 3. **Logging Information**
```python
# Sample log output when waiting for rate limit:
# INFO: Waiting 3598 seconds to respect rate limit
```

## Integration with Existing Code

In your normal scanning process, the time limiting is automatic:

```python
async def scan(settings, client, db, dry_run):
    # ... existing code ...
    
    # All scrapers now respect their configured intervals automatically
    for name in enabled:
        if name in SCRAPERS:
            scraper = SCRAPERS[name](client)
            
            # Set custom intervals if needed
            if name == 'immovlan':
                scraper.set_request_interval(7200)  # 2-hour cap
            elif name == 'immoscoop': 
                scraper.set_request_interval(10800)  # 3-hour cap
                
            # Scanning happens with automatic rate limiting
            await scraper.search(config)
```

## Recommended Settings by Site

| Site | Recommended Cap | Reason |
|------|----------------|---------|
| immovlan.be | 2-3 hours | Moderated site, less aggressive |
| immoscoop.be | 3-4 hours | More sensitive to traffic |
| immomarkt.be | 2-6 hours | Most protection, conservative approach |

The time-based approach is particularly effective because:

1. **Prevents IP blocking** - Never exceeds the specified cap
2. **Reduces detection risk** - Looks like natural slow browsing behavior  
3. **Maintains reliability** - Requests are never skipped due to rate limits
4. **Adaptable** - Easy to adjust based on site response or monitoring