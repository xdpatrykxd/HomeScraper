# Home Scraper Agent

A Python-based property listing scraper with support for multiple Belgian real estate platforms including Immoweb, Zimmo, and Realo.

## Architecture

This project implements a multi-source property scraping system designed to:
- Collect property listings from various Belgian real estate websites
- Normalize data into consistent Property models 
- Apply configurable filters for targeted search results
- Send alerts via WhatsApp using a gateway service

### Scraper Structure

Scrapers are implemented as classes inheriting from `PropertyScraper` in `app/scrapers/base.py`:
- `ImmowebScraper`: Implements parsing for Immoweb listings  
- `ZimmoScraper`: Implements parsing for Zimmo listings
- `RealoScraper`: Implements parsing for Realo listings

Each scraper follows a consistent pattern of fetching HTML, parsing data structures, and normalizing results into standardized Property objects.

## Getting Started

### Requirements

- Python 3.10+
- pip packages (see requirements.txt)

## Usage 

### Configuration

Create `.env` file with:
```
# WhatsApp Gateway Configuration
WAHA_API_KEY=your_gateway_key
WHATSAPP_RECIPIENTS=+32470111111
WHATSAPP_GROUP_IDS=group_id@example.com

# Monitoring Settings  
CHECK_INTERVAL_MINUTES=5
MAX_CONCURRENT_SCRAPERS=2
```

### Running the Scraper

```
python app/main.py
```

## Development

- Scraper implementations are located in `app/scrapers/`
- Unit tests in `tests/` directory
- Sample fixtures for testing in `tests/fixtures/`

### Adding New Sources

1. Create a new scraper class in `app/scrapers/newsource.py` 
2. Inherit from `PropertyScraper`
3. Implement the `search()` method which returns list of `Property` objects
4. Add to the scrapers mapping in `app/main.py`