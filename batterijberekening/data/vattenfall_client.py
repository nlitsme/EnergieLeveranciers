"""
Vattenfall energy provider API client for batterijberekening.
Based on the new Vattenfall API (api.mvf.consumptions.v0) as captured from browser HAR.

The API is purely token-based, no browser session cookies needed.
Token expires every 2 hours — re-extract from browser dev tools when needed.
"""

import json
import logging
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from batterijberekening.utils.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class HourlyReading:
    """Single hourly electricity reading."""
    timestamp: datetime
    electricity_low: float = 0.0
    electricity_high: float = 0.0
    redelivery_low: float = 0.0
    redelivery_high: float = 0.0
    produced: float = 0.0
    gas: float = 0.0
    
    @property
    def total_electricity(self) -> float:
        return self.electricity_low + self.electricity_high
    
    @property
    def total_redelivery(self) -> float:
        return self.redelivery_low + self.redelivery_high


class VattenfallClient:
    """Vattenfall API client for fetching hourly energy usage data.
    
    Uses Bearer token auth (2h expiry) + Ocp-Apim-Subscription-Key + vf-context.
    No browser session cookies needed — the API is purely token-based.
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or get_config()
        self.vattenfall_config = self.config.get('energy_provider', {}).get('vattenfall', {})
        
        # API configuration
        self.api_key = self.vattenfall_config.get('api_key', 'ed989141b5c34d138dba4a3ce1dbe046')
        self.base_url = self.vattenfall_config.get('base_url', 'https://api.vattenfall.nl/api/mvf/consumptions/v0')
        self.auth_token = self.vattenfall_config.get('auth_token', '')
        self.vf_context = self.vattenfall_config.get('vf_context', '')
        
        if not self.auth_token:
            raise RuntimeError(
                "Vattenfall auth_token not set. "
                "Set VATTENFALL_AUTH_TOKEN in .env or config.yaml.\n"
                "Get a fresh token from browser dev tools:\n"
                "  1. Open https://www.vattenfall.nl/mijn-vattenfall/\n"
                "  2. DevTools → Network → filter 'consumptions'\n"
                "  3. Copy 'Authorization: Bearer ***' value"
            )
        
        # HTTP setup — no cookie jar needed, purely token-based
        self.opener = urllib.request.build_opener()
    
    def _log(self, *args):
        if self.config.get('logging', {}).get('level') == 'DEBUG':
            logger.debug(*args)
    
    def _build_headers(self) -> Dict[str, str]:
        """Build request headers matching the browser HAR exactly."""
        headers = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'nl,en-US;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Referer': 'https://www.vattenfall.nl/',
            'Origin': 'https://www.vattenfall.nl',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0',
            'Connection': 'keep-alive',
            'TE': 'trailers',
            'Ocp-Apim-Subscription-Key': self.api_key,
            'Authorization': f'Bearer {self.auth_token}',
        }
        
        if self.vf_context:
            headers['vf-context'] = self.vf_context
        
        return headers
    
    def _http_request(self, url: str, method: str = 'GET') -> Any:
        """Make HTTP request with proper headers matching the browser HAR."""
        self._log(">", url)
        
        headers = self._build_headers()
        req = urllib.request.Request(url, data=None, headers=headers, method=method)
        
        for attempt in range(3):
            try:
                response = self.opener.open(req, timeout=30)
                response_data = response.read()
                
                content_type = response.headers.get('content-type', '')
                if 'application/json' in content_type:
                    result = json.loads(response_data)
                    self._log(json.dumps(result, indent=2)[:500])
                    return result
                return response_data
                
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    logger.error(
                        "Vattenfall API returned 401 Unauthorized.\n"
                        "Your auth token has expired (2h validity).\n"
                        "Get a fresh token:\n"
                        "  1. Open https://www.vattenfall.nl/mijn-vattenfall/\n"
                        "  2. DevTools → Network → filter 'consumptions'\n"
                        "  3. Copy 'Authorization: Bearer ***' value\n"
                        "  4. Update .env: VATTENFALL_AUTH_TOKEN=<new_token>"
                    )
                    raise
                logger.error(f"HTTP {e.code}: {e.reason} for {url}")
                if attempt == 2:
                    raise
            except Exception as e:
                self._log("Error:", e)
                if attempt == 2:
                    raise
        
        return None
    
    def get_hourly_consumption(self, end_date: datetime, amount: int = 72) -> List[Dict]:
        """
        Get hourly electricity consumption data.
        
        Args:
            end_date: End date for data (API returns data backwards from this date)
            amount: Number of hours to fetch (max 72 per request based on HAR)
            
        Returns:
            List of hourly consumption data objects
        """
        end_date_str = end_date.strftime('%Y-%m-%d')
        params = {
            'amount': str(amount),
            'endDate': end_date_str,
        }
        
        url = f"{self.base_url}/consumptions/products/Electricity/Hour?{urllib.parse.urlencode(params)}"
        
        try:
            data = self._http_request(url)
            if data:
                return data if isinstance(data, list) else [data]
        except Exception as e:
            logger.error(f"Failed to fetch hourly consumption for {end_date_str}: {e}")
        
        return []
    
    def get_monthly_consumption(self, end_date: datetime, amount: int = 14) -> List[Dict]:
        """
        Get monthly electricity consumption data.
        
        Args:
            end_date: End date for data
            amount: Number of months to fetch
            
        Returns:
            List of monthly consumption data objects
        """
        end_date_str = end_date.strftime('%Y-%m-%d')
        params = {
            'amount': str(amount),
            'endDate': end_date_str,
        }
        
        url = f"{self.base_url}/consumptions/products/Electricity/Month?{urllib.parse.urlencode(params)}"
        
        try:
            data = self._http_request(url)
            if data:
                return data if isinstance(data, list) else [data]
        except Exception as e:
            logger.error(f"Failed to fetch monthly consumption for {end_date_str}: {e}")
        
        return []
    
    def get_usage(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        """
        Get usage data for a date range by making multiple API calls.
        
        The API fetches backwards from end_date with max 72 hours per call.
        We iterate backwards from end_date to start_date.
        """
        all_data = []
        current_end = end_date
        
        while current_end > start_date:
            hours_needed = int((current_end - start_date).total_seconds() / 3600) + 1
            amount = min(72, hours_needed)
            
            data = self.get_hourly_consumption(current_end, amount)
            if data:
                all_data.extend(data)
            
            current_end -= timedelta(hours=amount)
            
            import time
            time.sleep(0.5)
        
        return all_data


def create_vattenfall_client(config: Optional[Dict] = None) -> VattenfallClient:
    """Factory function to create Vattenfall client."""
    return VattenfallClient(config)