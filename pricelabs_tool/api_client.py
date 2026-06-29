import os
import requests
from typing import List, Dict, Optional
from datetime import datetime
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


from pricelabs_tool.bookings import booking_info_by_date_from_rows


class PriceLabsAPI:
    def __init__(self):
        self.api_key = os.getenv("PRICELABS_API_KEY")
        if not self.api_key:
            raise ValueError("PRICELABS_API_KEY environment variable is required")

        self.base_url = os.getenv("API_BASE_URL", "https://api.pricelabs.co/v1")
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

    def get_booking_status_by_listing(
        self, listings: List[Dict]
    ) -> Dict[str, Dict[str, Dict]]:
        """
        Fetch booking info per date via POST /listing_prices.

        Args:
            listings: [{"id": "...", "pms": "..."}, ...]

        Returns:
            {listing_id: {date: {booking_status, available?}, ...}, ...}
        """
        payload_listings = [
            {"id": str(item["id"]), "pms": item["pms"]}
            for item in listings
            if item.get("id") and item.get("pms")
        ]
        if not payload_listings:
            return {}

        try:
            response = self.session.post(
                f"{self.base_url}/listing_prices",
                json={"listings": payload_listings},
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            logger.error("Error fetching listing prices for booking status: %s", e)
            raise PriceLabsAPIError(f"Error fetching listing prices: {e}")

        by_listing: Dict[str, Dict[str, Dict]] = {}
        requested_ids = {str(item["id"]) for item in payload_listings}
        for item in data if isinstance(data, list) else []:
            listing_id = str(item.get("id", ""))
            if not listing_id:
                continue
            if item.get("error") or item.get("error_status"):
                error = item.get("error") or item.get("error_status")
                logger.warning(
                    "Skipping booking status for listing %s: %s",
                    listing_id,
                    error,
                )
                by_listing[listing_id] = {}
                continue
            by_listing[listing_id] = booking_info_by_date_from_rows(
                item.get("data", [])
            )
        for listing_id in requested_ids:
            by_listing.setdefault(listing_id, {})
        return by_listing

    def get_booking_status_for_listing(
        self, listing_id: str, pms: str
    ) -> Dict[str, Dict]:
        """Fetch booking info per date for a single listing."""
        result = self.get_booking_status_by_listing([{"id": listing_id, "pms": pms}])
        return result.get(str(listing_id), {})

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