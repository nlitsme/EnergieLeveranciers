"""
Vattenfall energy provider API client for batterijberekening.
Based on the original vattenfall.py from nlitsme/EnergieLeveranciers.
"""

import json
import logging
import urllib.parse
import urllib.request
import urllib.error
import http.cookiejar
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
    """Vattenfall API client for fetching hourly energy usage data."""
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or get_config()
        self.vattenfall_config = self.config.get('energy_provider', 'vattenfall')
        
        # API configuration
        self.api_key = self.vattenfall_config.get('api_key', 'f5406a12dbdd41a2ad8e0de5a69d9e00')
        self.base_url = self.vattenfall_config.get('base_url', 'https://api.vattenfall.nl/api/mijnnuonprd/v2')
        self.auth_token = self.vattenfall_config.get('auth_token', '')
        self.customer_id = self.vattenfall_config.get('customer_id', '')
        
        # HTTP setup
        self.cookie_jar = http.cookiejar.CookieJar()
        handlers = [urllib.request.HTTPCookieProcessor(self.cookie_jar)]
        self.opener = urllib.request.build_opener(*handlers)
    
    def _log(self, *args):
        if self.config.get('logging', 'level') == 'DEBUG':
            logger.debug(*args)
    
    def _http_request(self, url: str, data: Optional[Dict] = None, method: str = 'GET') -> Any:
        """Make HTTP request with proper headers."""
        self._log(">", url)
        
        headers = {
            'Content-Type': 'application/json',
            'Ocp-Apim-Subscription-Key': self.api_key,
        }
        
        if self.auth_token:
            headers['Authorization'] = "Bearer " + self.auth_token
        
        req_data = None
        if data:
            req_data = json.dumps(data).encode('utf-8')
        
        req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
        
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
                self._log("!", str(e))
                if attempt == 2:
                    raise
            except Exception as e:
                self._log("Error:", e)
                if attempt == 2:
                    raise
        
        return None
    
    def get_usage(self, start_date: datetime, end_date: datetime, interval: int = 5) -> List[Dict]:
        """
        Get hourly usage data for a date range.
        
        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            interval: 5 = hourly, 3 = daily, 1 = monthly, 6 = yearly
            
        Returns:
            List of raw API response objects
        """
        if not self.auth_token or not self.customer_id:
            raise RuntimeError("Not authenticated. Set auth_token and customer_id in config.")
        
        all_data = []
        current = start_date
        chunk_days = 7 if interval == 5 else 31 if interval == 3 else 366
        
        while current <= end_date:
            chunk_end = min(current + timedelta(days=chunk_days - 1), end_date)
            
            start_str = current.strftime('%Y-%m-%d')
            end_str = chunk_end.strftime('%Y-%m-%d')
            
            params = {
                'Interval': interval,
                'GetAggregatedResults': False,
                'GetAmountDetails': False,
                'GetAmounts': True,
                'GetRoundedAmounts': False,
                'GetComparedConsumption': False,
                'DateFrom': start_str,
                'DateTo': end_str,
            }
            
            url = f"{self.base_url}/consumptions/consumptions/{self.customer_id}/{interval}/?{urllib.parse.urlencode(params)}"
            
            try:
                data = self._http_request(url)
                if data:
                    all_data.append(data)
            except Exception as e:
                logger.error(f"Failed to fetch usage for {start_str} to {end_str}: {e}")
            
            current = chunk_end + timedelta(days=1)
        
        return all_data


def create_vattenfall_client(config: Optional[Dict] = None) -> VattenfallClient:
    """Factory function to create Vattenfall client."""
    return VattenfallClient(config)