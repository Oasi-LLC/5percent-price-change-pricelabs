import click
from datetime import datetime, timedelta
import logging
from typing import List, Dict, Optional
from .api_client import PriceLabsAPI
from .price_calculator import calculate_adjusted_price
from .config import LOG_FORMAT, LOG_LEVEL
from .logging_setup import setup_logging, log_price_update, log_error
import typer

# Setup logging
logging.basicConfig(
    level=LOG_LEVEL,
    format=LOG_FORMAT
)
logger = logging.getLogger(__name__)

app = typer.Typer()
price_logger, error_logger = setup_logging()

def setup_api_client() -> PriceLabsAPI:
    """Initialize and return API client"""
    try:
        return PriceLabsAPI()
    except Exception as e:
        logger.error(f"Failed to initialize API client: {e}")
        raise

def get_active_listings(api_client: PriceLabsAPI, pms: Optional[str] = None) -> List[Dict]:
    """
    Retrieve active listings from PriceLabs
    
    Args:
        api_client: Initialized PriceLabs API client
        pms: Optional PMS filter (e.g., 'cloudbeds', 'hostaway')
    
    Returns:
        List of active listings
    """
    try:
        listings = api_client.get_listings()
        # Filter for active (non-hidden) listings
        active_listings = [
            listing for listing in listings
            if not listing.get('isHidden', True) 
            and listing.get('push_enabled', False)
            and (not pms or listing.get('pms') == pms)
        ]
        logger.info(f"Found {len(active_listings)} active listings")
        return active_listings
    except Exception as e:
        logger.error(f"Failed to retrieve listings: {e}")
        raise

@click.group()
def cli():
    """PriceLabs price adjustment tool"""
    pass

@cli.command()
@click.option('--pms', help='Filter by PMS (e.g., cloudbeds, hostaway)')
def list(pms: Optional[str]):
    """List all active listings"""
    try:
        api_client = setup_api_client()
        listings = get_active_listings(api_client, pms)
        
        for listing in listings:
            click.echo(f"ID: {listing['id']}")
            click.echo(f"Name: {listing['name']}")
            click.echo(f"PMS: {listing['pms']}")
            click.echo(f"Base Price: ${listing.get('base', 'N/A')}")
            click.echo(f"Last Updated: {listing.get('last_date_pushed', 'Never')}")
            click.echo("-" * 50)
            
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()

@cli.command()
@click.option('--listing-id', multiple=True, help='Specific listing ID(s) to update. Can be specified multiple times.')
@click.option('--increase', is_flag=True, help='Increase prices by 5%', default=False)
@click.option('--decrease', is_flag=True, help='Decrease prices by 5%', default=False)
@click.option('--all', 'update_all', is_flag=True, help='Update all active listings')
def update(listing_id: tuple = None, increase: bool = False, decrease: bool = False, update_all: bool = False):
    """Update prices for active listings"""
    if increase and decrease:
        click.echo("Error: Cannot specify both --increase and --decrease flags", err=True)
        raise click.Abort()
        
    if not increase and not decrease:
        click.echo("Error: Must specify either --increase or --decrease flag", err=True)
        raise click.Abort()

    if listing_id and update_all:
        click.echo("Error: Cannot specify both --listing-id and --all flags", err=True)
        raise click.Abort()

    if not listing_id and not update_all:
        click.echo("Error: Must specify either --listing-id or --all flag", err=True)
        raise click.Abort()

    client = PriceLabsAPI()
    
    try:
        listings = client.get_listings()
        # Filter for active (non-hidden) listings
        active_listings = [
            listing for listing in listings
            if not listing.get('isHidden', True) 
            and listing.get('push_enabled', False)
        ]
        
        if not update_all:
            # Convert listing_id tuple to list of strings
            listing_ids = [str(lid) for lid in listing_id]
            active_listings = [l for l in active_listings if str(l.get('id')) in listing_ids]
            if not active_listings:
                log_error(error_logger, str(listing_ids), "N/A", "N/A", "N/A", "N/A", 0.0, 0.0, "USD", f"No listings found with IDs: {listing_ids}")
                return

        logger.info(f"Processing {len(active_listings)} listings...")
        
        for listing in active_listings:
            listing_id = str(listing.get('id'))
            listing_name = listing.get('name', 'N/A')
            pms_name = listing.get('pms', 'N/A')
            currency = listing.get('currency', 'USD')
            min_stay = listing.get('min_stay', 1)
            min_price = listing.get('min_price', 0)
            max_price = listing.get('max_price', 0)
            
            logger.info(f"Processing {listing_name} (ID: {listing_id}) using PMS: {pms_name}")
            
            try:
                overrides = client.get_listing_overrides(listing_id, pms=pms_name)
            except Exception as e:
                log_error(
                    error_logger,
                    listing_id=listing_id,
                    listing_name=listing_name,
                    pms_name=pms_name,
                    start_date="N/A",
                    end_date="N/A",
                    old_price=0.0,
                    new_price=0.0,
                    currency=currency,
                    error_reason=f"Failed to fetch overrides: {str(e)}"
                )
                continue
            
            adjusted_overrides = []
            for override in overrides.get('overrides', []):
                if override.get('price_type') != 'fixed':
                    continue
                    
                try:
                    old_price = float(override.get('price', 0))
                    if old_price > 0:
                        new_price = calculate_adjusted_price(old_price, increase=increase)
                        
                        adjusted_override = {
                            'date': override['date'],
                            'price': str(int(new_price)),  # Convert to integer string
                            'price_type': 'fixed',
                            'currency': override.get('currency', currency),
                            'min_stay': override.get('min_stay', min_stay)
                        }
                        adjusted_overrides.append(adjusted_override)
                        
                        # Log the price update
                        log_price_update(
                            price_logger,
                            listing_id=listing_id,
                            listing_name=listing_name,
                            pms_name=pms_name,
                            start_date=override['date'],
                            end_date=override['date'],
                            price=new_price,
                            currency=currency,
                            price_type='fixed',
                            minimum_stay=override.get('min_stay', min_stay),
                            minimum_price=min_price,
                            maximum_price=max_price,
                            check_in=override.get('check_in', ''),
                            check_out=override.get('check_out', ''),
                            reason="Increase" if increase else "Decrease"
                        )
                except Exception as e:
                    log_error(
                        error_logger,
                        listing_id=listing_id,
                        listing_name=listing_name,
                        pms_name=pms_name,
                        start_date=override.get('date', 'N/A'),
                        end_date=override.get('date', 'N/A'),
                        old_price=float(override.get('price', 0)),
                        new_price=0.0,
                        currency=currency,
                        error_reason=f"Failed to process override: {str(e)}"
                    )
            
            if adjusted_overrides:
                try:
                    client.update_listing_overrides(listing_id, adjusted_overrides, pms=pms_name)
                    logger.info(f"Successfully updated {len(adjusted_overrides)} prices for {listing_name}")
                except Exception as e:
                    log_error(
                        error_logger,
                        listing_id=listing_id,
                        listing_name=listing_name,
                        pms_name=pms_name,
                        start_date="N/A",
                        end_date="N/A",
                        old_price=0.0,
                        new_price=0.0,
                        currency=currency,
                        error_reason=f"Failed to update overrides: {str(e)}"
                    )
    except Exception as e:
        log_error(error_logger, "N/A", "N/A", "N/A", "N/A", "N/A", 0.0, 0.0, "USD", f"Failed to retrieve listings: {str(e)}")
        return

if __name__ == "__main__":
    cli() 