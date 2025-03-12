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

def process_listing_adjustments(
    api_client: PriceLabsAPI,
    listing_id: str,
    increase: bool,
    start_date: Optional[datetime] = None,
    days: int = 30
) -> Dict:
    """
    Process price adjustments for a single listing
    
    Args:
        api_client: Initialized PriceLabs API client
        listing_id: ID of the listing to adjust
        increase: Whether to increase (True) or decrease (False) prices
        start_date: Starting date for adjustments
        days: Number of days to adjust
    
    Returns:
        Dictionary with adjustment results
    """
    try:
        # Get current overrides
        current_overrides = api_client.get_listing_overrides(listing_id)
        logger.debug(f"Current overrides for listing {listing_id}: {current_overrides}")
        
        # Get all existing fixed-price overrides
        existing_overrides = [
            override for override in current_overrides.get('overrides', [])
            if override.get('price_type') == 'fixed'
        ]
        
        if not existing_overrides:
            logger.info("No existing overrides found to adjust")
            return {'overrides': []}
        
        # Filter by date range if start_date is provided
        if start_date:
            end_date = start_date + timedelta(days=days) if days else None
            existing_overrides = [
                override for override in existing_overrides
                if datetime.strptime(override['date'], "%Y-%m-%d") >= start_date
                and (not end_date or datetime.strptime(override['date'], "%Y-%m-%d") < end_date)
            ]
        
        # Calculate adjusted prices and preserve ALL override fields
        adjusted_overrides = []
        for override in existing_overrides:
            try:
                current_price = float(override.get('price', 0))
                if current_price > 0:
                    adjusted_price = calculate_adjusted_price(current_price, increase)
                    
                    # Create new override preserving ALL original fields
                    adjusted_override = override.copy()  # Preserve all original fields
                    adjusted_override.update({
                        'price': str(int(adjusted_price)),  # Convert to integer string
                        'price_type': 'fixed'  # Ensure price_type is set
                    })
                    
                    adjusted_overrides.append(adjusted_override)
                    logger.debug(f"Adjusted override for {override['date']}: {adjusted_override}")
            except (ValueError, TypeError) as e:
                logger.error(f"Error processing price for date {override.get('date')}: {e}")
                continue
        
        if not adjusted_overrides:
            logger.warning("No valid overrides to update after processing")
            return {'overrides': []}
            
        logger.debug(f"Sending adjusted overrides to PriceLabs: {adjusted_overrides}")
        
        # Update prices in PriceLabs
        result = api_client.update_listing_overrides(
            listing_id=listing_id,
            overrides=adjusted_overrides
        )
        
        logger.info(f"Successfully adjusted prices for listing {listing_id}")
        logger.debug(f"PriceLabs API response: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to process adjustments for listing {listing_id}: {e}")
        raise

@click.group()
def cli():
    """PriceLabs price adjustment tool"""
    pass

@cli.command()
@click.option('--listing-id', help='Specific listing ID to adjust')
@click.option('--pms', help='Filter by PMS (e.g., cloudbeds, hostaway)')
@click.option('--increase/--decrease', default=True, help='Increase or decrease prices')
@click.option('--days', type=int, help='Optional: Number of days to adjust (only used with --start-date)')
@click.option('--start-date', help='Optional: Start date for adjustments (YYYY-MM-DD format)')
def adjust(listing_id: Optional[str], pms: Optional[str], increase: bool, days: Optional[int], start_date: Optional[str]):
    """Adjust prices for listings"""
    try:
        api_client = setup_api_client()
        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
        
        if listing_id:
            # Process single listing
            result = process_listing_adjustments(
                api_client,
                listing_id,
                increase,
                start_date_obj,
                days
            )
            click.echo(f"Adjusted prices for listing {listing_id}")
        else:
            # Process all active listings
            listings = get_active_listings(api_client, pms)
            for listing in listings:
                try:
                    result = process_listing_adjustments(
                        api_client,
                        listing['id'],
                        increase,
                        start_date_obj,
                        days
                    )
                    click.echo(f"Adjusted prices for {listing['name']} ({listing['id']})")
                except Exception as e:
                    click.echo(f"Failed to adjust {listing['name']}: {e}")
                    continue
        
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()

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
@click.option('--dry-run', is_flag=True, help='Preview changes without applying them')
def update(listing_id: tuple = None, increase: bool = False, decrease: bool = False, dry_run: bool = False):
    """Update prices for active listings"""
    if increase and decrease:
        click.echo("Error: Cannot specify both --increase and --decrease flags", err=True)
        raise click.Abort()
        
    if not increase and not decrease:
        click.echo("Error: Must specify either --increase or --decrease flag", err=True)
        raise click.Abort()

    client = PriceLabsAPI()
    
    try:
        listings = client.get_listings()
    except Exception as e:
        log_error(error_logger, "N/A", "N/A", "N/A", "N/A", "N/A", 0.0, 0.0, "USD", f"Failed to retrieve listings: {str(e)}")
        return
    
    if listing_id:
        # Convert listing_id tuple to list of strings
        listing_ids = [str(lid) for lid in listing_id]
        listings = [l for l in listings if str(l.get('id')) in listing_ids]
        if not listings:
            log_error(error_logger, str(listing_ids), "N/A", "N/A", "N/A", "N/A", 0.0, 0.0, "USD", f"No listings found with IDs: {listing_ids}")
            return
    
    for listing in listings:
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
        
        # Update overrides in PriceLabs if not a dry run
        if adjusted_overrides and not dry_run:
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

if __name__ == "__main__":
    cli() 