"""
Configuration utility for batterijberekening.
Loads config from config.yaml and .env file.
"""

import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional

import yaml
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

# Cache for config
_config_cache: Optional[Dict] = None


def get_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load configuration from config.yaml and environment variables.
    
    Priority: environment variables > config.yaml > defaults
    """
    global _config_cache
    
    if _config_cache is not None:
        return _config_cache
    
    # Default config path
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / 'config.yaml'
    else:
        config_path = Path(config_path)
    
    # Load from YAML
    config = {}
    if config_path.exists():
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f) or {}
    else:
        logging.warning(f"Config file not found: {config_path}")
    
    # Override with environment variables
    config = _apply_env_overrides(config)
    
    _config_cache = config
    return config


def _apply_env_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    """Apply environment variable overrides to config."""
    # Energy provider
    if os.getenv('ENERGY_PROVIDER'):
        provider = os.getenv('ENERGY_PROVIDER')
        config.setdefault('energy_provider', {})['provider'] = provider
    
    # Eneco credentials
    eneco = config.setdefault('energy_provider', {}).setdefault('eneco', {})
    if os.getenv('ENECO_USERNAME'):
        eneco['username'] = os.getenv('ENECO_USERNAME')
    if os.getenv('ENECO_PASSWORD'):
        eneco['password'] = os.getenv('ENECO_PASSWORD')
    if os.getenv('ENECO_API_KEY'):
        eneco['api_key'] = os.getenv('ENECO_API_KEY')
    
    # Vattenfall credentials
    vattenfall = config.setdefault('energy_provider', {}).setdefault('vattenfall', {})
    if os.getenv('VATTENFALL_AUTH_TOKEN'):
        vattenfall['auth_token'] = os.getenv('VATTENFALL_AUTH_TOKEN')
    if os.getenv('VATTENFALL_CUSTOMER_ID'):
        vattenfall['customer_id'] = os.getenv('VATTENFALL_CUSTOMER_ID')
    if os.getenv('VATTENFALL_API_KEY'):
        vattenfall['api_key'] = os.getenv('VATTENFALL_API_KEY')
    if os.getenv('VATTENFALL_VF_CONTEXT'):
        vattenfall['vf_context'] = os.getenv('VATTENFALL_VF_CONTEXT')
    
    # Timezone
    if os.getenv('TIMEZONE'):
        config.setdefault('timezone', {})['zone'] = os.getenv('TIMEZONE')
    
    # Data settings
    if os.getenv('YEARS_BACK'):
        config.setdefault('data', {})['years_back'] = int(os.getenv('YEARS_BACK'))
    if os.getenv('DATA_DIR'):
        config.setdefault('data', {})['data_dir'] = os.getenv('DATA_DIR')
    if os.getenv('OUTPUT_DIR'):
        config.setdefault('data', {})['output_dir'] = os.getenv('OUTPUT_DIR')
    
    # Logging
    if os.getenv('LOG_LEVEL'):
        config.setdefault('logging', {})['level'] = os.getenv('LOG_LEVEL')
    if os.getenv('LOG_FILE'):
        config.setdefault('logging', {})['file'] = os.getenv('LOG_FILE')
    
    return config


def reload_config() -> Dict[str, Any]:
    """Force reload configuration."""
    global _config_cache
    _config_cache = None
    return get_config()