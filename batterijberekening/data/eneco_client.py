"""
Eneco energy provider API client for batterijberekening.
Based on the original eneco.py from nlitsme/EnergieLeveranciers.
"""

import json
import logging
import re
import urllib.parse
import urllib.request
import urllib.error
import http.cookiejar
import binascii
import base64
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
    warmth: float = 0.0
    tap_water: float = 0.0
    
    @property
    def total_electricity(self) -> float:
        return self.electricity_low + self.electricity_high
    
    @property
    def total_redelivery(self) -> float:
        return self.redelivery_low + self.redelivery_high


class EnecoClient:
    """Eneco API client for fetching hourly energy usage data."""
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or get_config()
        self.eneco_config = self.config.get('energy_provider', 'eneco')
        
        # API configuration
        self.api_key = self.eneco_config.get('api_key', '41ff1058fc7f4446b80db84e8857c347')
        self.base_url = self.eneco_config.get('base_url', 'https://api-digital.enecogroup.com')
        self.username = self.eneco_config.get('username', '')
        self.password = self.eneco_config.get('password', '')
        
        # Runtime state
        self.auth_token: Optional[str] = None
        self.customer_id: Optional[int] = None
        self.account_id: Optional[int] = None
        self.csrf_token: Optional[str] = None
        
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
            'apikey': self.api_key,
        }
        
        if self.auth_token:
            headers['Authorization'] = self.auth_token
        
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
    
    def _extract_token(self, html: bytes) -> Optional[str]:
        """Extract state token from HTML."""
        html_str = html.decode('utf-8')
        match = re.search(r'"stateToken":"(.*?)"', html_str)
        if match:
            return self._unescape_string(match.group(1))
        return None
    
    def _unescape_string(self, txt: str) -> str:
        """Unescape JavaScript unicode sequences."""
        return re.sub(r'\\x(\w\w)', lambda m: chr(int(m.group(1), 16)), txt)
    
    def _extract_customer_id_from_token(self, token: str) -> Optional[int]:
        """Extract customer ID from JWT token."""
        try:
            parts = token.split('.', 2)
            if len(parts) >= 2:
                payload = parts[1] + '===='
                import base64
                decoded = base64.urlsafe_b64decode(payload)
                props = json.loads(decoded)
                return props.get('klantnummer') or props.get('customerId')
        except Exception as e:
            self._log("Failed to extract customer ID from token:", e)
        return None
    
    def login(self) -> bool:
        """Authenticate with Eneco."""
        self._log("Starting Eneco login...")
        
        # Step 1: Get initial cookies
        self._http_request("https://www.eneco.nl/mijn-eneco/")
        
        # Step 2: Get CSRF token
        csrf_json = self._http_request("https://www.eneco.nl/api/auth/csrf/")
        self.csrf_token = csrf_json.get('csrfToken')
        if not self.csrf_token:
            logger.error("Failed to get CSRF token")
            return False
        
        # Step 3: Start Okta authentication
        auth_data = {
            'json': 'true',
            'csrfToken': self.csrf_token,
            'callbackUrl': '/mijn-eneco/',
        }
        auth_json = self._http_request(
            "https://www.eneco.nl/api/auth/signin/okta/",
            data=auth_data,
            method='POST'
        )
        
        # Step 4: Follow redirect
        html = self._http_request(auth_json.get('url', ''))
        token = self._extract_token(html)
        
        if not token:
            logger.error("Failed to get state token")
            return False
        
        # Step 5: Introspect and authenticate
        state = self._http_request(
            "https://inloggen.eneco.nl/idp/idx/introspect",
            data={'stateToken': token}
        )
        
        while True:
            if state.get('success'):
                break
            if 'remediation' not in state:
                logger.error("Authentication failed: no remediation")
                return False
            
            # Find challenge authenticator
            form = None
            for v in state.get('remediation', {}).get('value', []):
                if v.get('name') == 'challenge-authenticator':
                    form = v
                    break
            
            if not form:
                logger.error("Challenge authenticator not found")
                return False
            
            # Prepare credentials
            post_data = {}
            for v in form.get('value', []):
                value = None
                if 'value' in v:
                    value = v['value']
                else:
                    if v.get('name') == 'identifier':
                        value = self.username
                    elif v.get('name') == 'credentials':
                        value = {'passcode': self.password}
                
                if value is not None:
                    post_data[v['name']] = value
            
            state = self._http_request(form['href'], data=post_data)
        
        # Step 6: Get success token
        success_href = state.get('success', {}).get('href')
        if not success_href:
            logger.error("No success href in auth response")
            return False
        
        html2 = self._http_request(success_href)
        html2_str = html2.decode('utf-8') if isinstance(html2, bytes) else str(html2)
        
        # Extract ID token
        id_token_match = re.search(r'"idToken":"(.*?)"', html2_str)
        if id_token_match:
            self.auth_token = "Bearer " + self._unescape_string(id_token_match.group(1))
        else:
            logger.error("Failed to extract ID token")
            return False
        
        # Extract customer and account IDs
        cust_match = re.search(r'"customerId":(\d+)', html2_str)
        if cust_match:
            self.customer_id = int(cust_match.group(1))
        
        acc_match = re.search(r'"accountId":(\d+)', html2_str)
        if acc_match:
            self.account_id = int(acc_match.group(1))
        
        # Fallback: extract from token
        if not self.customer_id and self.auth_token:
            self.customer_id = self._extract_customer_id_from_token(self.auth_token[7:])
        
        logger.info(f"Login successful. Customer ID: {self.customer_id}, Account ID: {self.account_id}")
        return True
    
    def get_usage(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        """
        Get hourly usage data for a date range.
        
        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            
        Returns:
            List of raw API response objects
        """
        if not self.auth_token or not self.customer_id or not self.account_id:
            raise RuntimeError("Not authenticated. Call login() first.")
        
        all_data = []
        current = start_date
        
        # API returns max 7 days at a time for hourly data
        while current <= end_date:
            week_end = min(current + timedelta(days=6), end_date)
            
            params = {
                'aggregation': 'Week',
                'interval': 'Hour',
                'start': current.strftime('%Y-%m-%d'),
                'addBudget': 'true',
                'addWeather': 'true',
                'extrapolate': 'false',
            }
            
            url = (
                f"{self.base_url}/dxpweb/nl/eneco/customers/{self.customer_id}"
                f"/accounts/{self.account_id}/usages?"
                f"{urllib.parse.urlencode(params)}"
            )
            
            try:
                data = self._http_request(url)
                if data:
                    all_data.append(data)
            except Exception as e:
                logger.error(f"Failed to fetch usage for {current}: {e}")
            
            current = week_end + timedelta(days=1)
        
        return all_data


def create_eneco_client(config: Optional[Dict] = None) -> EnecoClient:
    """Factory function to create Eneco client."""
    return EnecoClient(config)