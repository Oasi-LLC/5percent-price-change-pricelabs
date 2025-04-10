import os
import requests
from typing import List, Dict, Optional
from datetime import datetime
import logging
from dotenv import load_dotenv
from .config import API_KEY, BASE_URL

logger = logging.getLogger(__name__)

class PriceLabsAPI:
    def __init__(self):
        self.api_key = API_KEY
        if not self.api_key:
            raise ValueError("PRICELABS_API_KEY environment variable is required")
        
        self.base_url = BASE_URL
        self.session = requests.Session()
        self.session.headers.update({
            'X-API-Key': self.api_key,
            'Content-Type': 'application/json'
        })

    def get_listings(self) -> List[Dict]:
        """Get all active listings"""
        response = self.session.get(f"{self.base_url}/listings")
        response.raise_for_status()
        
        # Log the response for debugging
        logger.debug(f"API Response: {response.json()}")
        
        data = response.json()
        return data.get('listings', []) if isinstance(data, dict) else []

    def get_listing_overrides(self, listing_id: str, pms: str = None) -> Dict:
        """Fetch overrides for a specific listing"""
        try:
            params = {}
            if pms:
                params['pms'] = pms
                
            response = self.session.get(
                f"{self.base_url}/listings/{listing_id}/overrides",
                params=params
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching overrides for listing {listing_id}: {e}")
            raise PriceLabsAPIError(f"Error fetching overrides: {e}")

    def update_listing_overrides(
        self,
        listing_id: str,
        overrides: List[Dict],
        pms: str = None,
        update_children: bool = False
    ) -> Dict:
        """
        Update listing overrides with new prices
        
        Args:
            listing_id: The ID of the listing to update
            overrides: List of override objects with required fields:
                      date, price, price_type, currency, min_stay
            pms: PMS name (e.g. "cloudbeds", "hostaway", "ownerrez")
            update_children: Whether to update child listings
        """
        try:
            payload = {
                "update_children": update_children,
                "overrides": overrides
            }
            if pms:
                payload['pms'] = pms
            
            logger.debug(f"Sending update request for listing {listing_id}")
            logger.debug(f"Request URL: {self.base_url}/listings/{listing_id}/overrides")
            logger.debug(f"Headers: {self.session.headers}")
            logger.debug(f"Payload: {payload}")

            response = self.session.post(
                f"{self.base_url}/listings/{listing_id}/overrides",
                json=payload
            )
            
            logger.debug(f"Response status code: {response.status_code}")
            logger.debug(f"Response content: {response.content}")
            
            if not response.ok:
                error_detail = response.json() if response.content else "No error details"
                logger.error(f"API error response: {error_detail}")
                logger.error(f"Response headers: {response.headers}")
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error updating overrides for listing {listing_id}: {e}")
            raise PriceLabsAPIError(f"Error updating overrides: {e}")

    def _validate_override(self, override: Dict) -> bool:
        """Validate override object has all required fields"""
        required_fields = ["date", "price", "price_type", "currency", "min_stay"]
        return all(field in override for field in required_fields)

    def update_listing(self, listing_id: str, data: Dict) -> Dict:
        """Update a listing's pricing"""
        response = self.session.put(f"{self.base_url}/listings/{listing_id}", json=data)
        response.raise_for_status()
        return response.json()

class PriceLabsAPIError(Exception):
    """Custom exception for API errors"""
    pass

def handle_api_error(response: requests.Response) -> None:
    """Handle API error responses with appropriate logging"""
    error_msg = f"API error: {response.status_code}"
    try:
        error_details = response.json()
        error_msg += f" - {error_details.get('message', '')}"
    except ValueError:
        pass
    
    if response.status_code == 400:
        raise PriceLabsAPIError(f"Invalid request parameters: {error_msg}")
    elif response.status_code == 401:
        raise PriceLabsAPIError(f"Authentication failed: {error_msg}")
    elif response.status_code == 404:
        raise PriceLabsAPIError(f"Listing not found: {error_msg}")
    elif response.status_code == 429:
        raise PriceLabsAPIError(f"Rate limit exceeded: {error_msg}")
    else:
        raise PriceLabsAPIError(error_msg) 