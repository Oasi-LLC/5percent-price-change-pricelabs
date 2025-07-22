from typing import List, Dict, Optional
import logging
from config import ADJUSTMENT_PERCENTAGE

logger = logging.getLogger(__name__)

def calculate_adjusted_price(price: float, increase: bool = True) -> float:
    """
    Calculate adjusted price based on percentage and round to integer
    
    Args:
        price: Current price
        increase: Whether to increase or decrease
    
    Returns:
        Adjusted price as integer
    """
    adjustment = 1 + (ADJUSTMENT_PERCENTAGE / 100 * (1 if increase else -1))
    return round(price * adjustment)  # Round to integer 