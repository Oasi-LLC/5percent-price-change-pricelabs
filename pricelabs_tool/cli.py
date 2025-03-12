import click

@click.command()
@click.argument('listing_id')
@click.option('--increase/--decrease', default=True, help='Increase or decrease prices')
def adjust_prices(listing_id, increase):
    """Adjust prices for a listing"""
    api = PriceLabsAPI()
    result = api.adjust_listing_prices(listing_id, increase)
    click.echo(f"Price adjustment {'increased' if increase else 'decreased'} by 5%")
    click.echo(f"Updated {len(result['overrides'])} prices") 