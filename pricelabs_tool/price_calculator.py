from typing import List, Dict, Optional
import logging
from pricelabs_tool.config import ADJUSTMENT_PERCENTAGE

logger = logging.getLogger(__name__)

def calculate_adjusted_price(price: float, increase: bool = True) -> float:
    """
    Adjust the price by the configured percentage.
    Args:
        price: The original price
        increase: If True, increase by percentage; else decrease
    Returns:
        Adjusted price
    """
    if increase:
        return price * (1 + ADJUSTMENT_PERCENTAGE / 100)
    else:
        return price * (1 - ADJUSTMENT_PERCENTAGE / 100) 