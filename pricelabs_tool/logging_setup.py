import logging
import os
from datetime import datetime
from pathlib import Path

def write_header(file_path: str, header: str):
    """Write header to file if it doesn't exist or is empty"""
    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        with open(file_path, 'w') as f:
            f.write(header + "\n")

def setup_logging():
    """Configure logging for price updates and errors"""
    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Get current timestamp for log files
    current_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    
    # Define log file paths with timestamp
    price_log_path = f"logs/pricing_updates_{current_timestamp}.log"
    error_log_path = f"logs/errors_{current_timestamp}.log"
    
    # Define headers
    price_header = "Timestamp\tListingId\tListingName\tPMSName\tReason\tStartDate\tEndDate\tPrice\tCurrency\tPriceType\tMinimumStay\tMinimumPrice\tMaximumPrice\tUpdatedAt\tCheckIn\tCheckOut"
    error_header = "Timestamp\tListingId\tListingName\tPMSName\tStartDate\tEndDate\tOldPrice\tNewPrice\tCurrency\tErrorDetails"
    
    # Write headers to new files
    write_header(price_log_path, price_header)
    write_header(error_log_path, error_header)
    
    # Configure price updates logger
    price_logger = logging.getLogger('price_updates')
    price_logger.setLevel(logging.INFO)
    # Remove any existing handlers
    price_logger.handlers = []
    price_handler = logging.FileHandler(price_log_path, mode='a')
    price_formatter = logging.Formatter('%(asctime)s\t%(listing_id)s\t%(listing_name)s\t%(pms_name)s\t%(reason)s\t%(start_date)s\t%(end_date)s\t%(price)s\t%(currency)s\t%(price_type)s\t%(minimum_stay)s\t%(minimum_price)s\t%(maximum_price)s\t%(updated_at)s\t%(check_in)s\t%(check_out)s',
                                      datefmt='%Y-%m-%d %H:%M:%S')
    price_handler.setFormatter(price_formatter)
    price_logger.addHandler(price_handler)
    price_logger.propagate = False
    
    # Configure error logger
    error_logger = logging.getLogger('error_log')
    error_logger.setLevel(logging.ERROR)
    # Remove any existing handlers
    error_logger.handlers = []
    error_handler = logging.FileHandler(error_log_path, mode='a')
    error_formatter = logging.Formatter('%(asctime)s\t%(listing_id)s\t%(listing_name)s\t%(pms_name)s\t%(start_date)s\t%(end_date)s\t%(old_price)s\t%(new_price)s\t%(currency)s\t%(error_reason)s',
                                      datefmt='%Y-%m-%d %H:%M:%S')
    error_handler.setFormatter(error_formatter)
    error_logger.addHandler(error_handler)
    error_logger.propagate = False
    
    return price_logger, error_logger

def log_price_update(logger, listing_id: str, listing_name: str, pms_name: str,
                    start_date: str, end_date: str, price: float, currency: str,
                    price_type: str = 'fixed', minimum_stay: int = 1,
                    minimum_price: float = None, maximum_price: float = None,
                    check_in: str = '', check_out: str = '',
                    reason: str = "Price Update"):
    """Log a price update with detailed information"""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info("", extra={
        'listing_id': listing_id,
        'listing_name': listing_name,
        'pms_name': pms_name,
        'reason': reason,
        'start_date': start_date,
        'end_date': end_date,
        'price': f"${price:.2f}",
        'currency': currency,
        'price_type': price_type,
        'minimum_stay': str(minimum_stay),
        'minimum_price': f"${minimum_price:.2f}" if minimum_price else "N/A",
        'maximum_price': f"${maximum_price:.2f}" if maximum_price else "N/A",
        'updated_at': current_time,
        'check_in': check_in if check_in else '',
        'check_out': check_out if check_out else ''
    })

def log_error(logger, listing_id: str, listing_name: str, pms_name: str,
              start_date: str, end_date: str, old_price: float, new_price: float,
              currency: str, error_reason: str):
    """Log an error with detailed information"""
    logger.error("", extra={
        'listing_id': listing_id,
        'listing_name': listing_name,
        'pms_name': pms_name,
        'start_date': start_date,
        'end_date': end_date,
        'old_price': f"${old_price:.2f}",
        'new_price': f"${new_price:.2f}",
        'currency': currency,
        'error_reason': error_reason
    }) 