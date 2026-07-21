"""
Vattenfall API response parser for batterijberekening.
Parses the new Vattenfall API (api.mvf.consumptions.v0) hourly consumption data.
"""

import json
from datetime import datetime
from typing import Dict, List, Any
import logging

logger = logging.getLogger(__name__)


def parse_vattenfall_hourly(data: List[Dict]) -> List[Dict]:
    """
    Parse Vattenfall hourly consumption API response.
    
    Expected response format from HAR:
    [
        {
            "date": "2026-07-18T15:00:00.000Z",
            "value": 0.123,
            "unit": "kWh",
            "type": "Consumption",
            "tariff": "High"  # or "Low"
        },
        ...
    ]
    
    Or similar structure with electricity consumption/redelivery.
    """
    parsed = []
    
    for item in data:
        try:
            # Parse timestamp
            timestamp_str = item.get('date') or item.get('timestamp') or item.get('datetime')
            if not timestamp_str:
                continue
            
            # Handle various timestamp formats
            timestamp = parse_timestamp(timestamp_str)
            
            # Extract values
            value = float(item.get('value') or item.get('consumption') or item.get('usage') or 0)
            unit = item.get('unit', 'kWh')
            reading_type = item.get('type', '').lower()
            tariff = item.get('tariff', '').lower()
            
            if unit != 'kWh':
                logger.warning(f"Unexpected unit: {unit}, assuming kWh")
            
            # Determine which field to populate
            record = {
                'timestamp': timestamp,
                'electricity_low': 0.0,
                'electricity_high': 0.0,
                'redelivery_low': 0.0,
                'redelivery_high': 0.0,
                'produced': 0.0,
            }
            
            if reading_type == 'production' or reading_type == 'solar':
                record['produced'] = value
            elif reading_type == 'consumption' or reading_type == 'electricity':
                if tariff == 'low' or tariff == 'dal':
                    record['electricity_low'] = value
                elif tariff == 'high' or tariff == 'hoog':
                    record['electricity_high'] = value
                else:
                    # If no tariff specified, add to high by default
                    record['electricity_high'] = value
                    
            elif reading_type == 'redelivery' or reading_type == 'generated':
                if tariff == 'low' or tariff == 'dal':
                    record['redelivery_low'] = value
                elif tariff == 'high' or tariff == 'hoog':
                    record['redelivery_high'] = value
                else:
                    record['redelivery_high'] = value
            
            parsed.append(record)
            
        except Exception as e:
            logger.warning(f"Failed to parse Vattenfall item {item}: {e}")
            continue
    
    # Group by timestamp (multiple readings may have same timestamp)
    return aggregate_by_timestamp(parsed)


def parse_timestamp(ts_str: str) -> datetime:
    """Parse various timestamp formats from Vattenfall API."""
    formats = [
        '%Y-%m-%dT%H:%M:%S.%fZ',      # 2026-07-18T15:00:00.000Z
        '%Y-%m-%dT%H:%M:%SZ',          # 2026-07-18T15:00:00Z
        '%Y-%m-%dT%H:%M:%S%z',         # 2026-07-18T15:00:00+02:00
        '%Y-%m-%d %H:%M:%S',           # 2026-07-18 15:00:00
        '%Y-%m-%d',                    # 2026-07-18
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    
    # Try with dateutil if available
    try:
        from dateutil import parser
        return parser.parse(ts_str)
    except ImportError:
        pass
    
    raise ValueError(f"Cannot parse timestamp: {ts_str}")


def aggregate_by_timestamp(records: List[Dict]) -> List[Dict]:
    """Combine multiple readings with the same timestamp."""
    from collections import defaultdict
    
    grouped = defaultdict(lambda: {
        'timestamp': None,
        'electricity_low': 0.0,
        'electricity_high': 0.0,
        'redelivery_low': 0.0,
        'redelivery_high': 0.0,
        'produced': 0.0,
    })
    
    for r in records:
        ts = r['timestamp']
        grouped[ts]['timestamp'] = ts
        for key in ['electricity_low', 'electricity_high', 'redelivery_low', 'redelivery_high', 'produced']:
            grouped[ts][key] += r.get(key, 0.0)
    
    # Sort by timestamp
    return [v for _, v in sorted(grouped.items())]


def aggregate_daily(hourly: List[Dict]) -> List[Dict]:
    """Aggregate hourly data to daily totals."""
    from collections import defaultdict
    
    daily = defaultdict(lambda: {
        'date': None,
        'electricity_low': 0.0,
        'electricity_high': 0.0,
        'redelivery_low': 0.0,
        'redelivery_high': 0.0,
        'produced': 0.0,
    })
    
    for h in hourly:
        date_key = h['timestamp'].date()
        daily[date_key]['date'] = date_key
        for key in ['electricity_low', 'electricity_high', 'redelivery_low', 'redelivery_high', 'produced']:
            daily[date_key][key] += h.get(key, 0.0)
    
    return [v for _, v in sorted(daily.items())]


def print_summary(hourly: List[Dict]) -> None:
    """Print a human-readable summary of hourly data."""
    if not hourly:
        print("No data to summarize")
        return
    
    daily = aggregate_daily(hourly)
    
    print(f"\n{'Date':<12} {'Elec Low':>10} {'Elec High':>10} {'Redel Low':>10} {'Redel High':>10} {'Produced':>10}")
    print("-" * 68)
    
    for d in daily:
        date_str = d['date'].strftime('%Y-%m-%d')
        print(f"{date_str:<12} {d['electricity_low']:>10.3f} {d['electricity_high']:>10.3f} "
              f"{d['redelivery_low']:>10.3f} {d['redelivery_high']:>10.3f} {d['produced']:>10.3f}")
    
    # Totals
    total_elec = sum(d['electricity_low'] + d['electricity_high'] for d in daily)
    total_redel = sum(d['redelivery_low'] + d['redelivery_high'] for d in daily)
    total_prod = sum(d['produced'] for d in daily)
    
    print("-" * 68)
    print(f"{'TOTAL':<12} {sum(d['electricity_low'] for d in daily):>10.3f} {sum(d['electricity_high'] for d in daily):>10.3f} "
          f"{sum(d['redelivery_low'] for d in daily):>10.3f} {sum(d['redelivery_high'] for d in daily):>10.3f} {total_prod:>10.3f}")
    print(f"\nTotal electricity consumed: {total_elec:.3f} kWh")
    print(f"Total redelivery: {total_redel:.3f} kWh")
    print(f"Total produced: {total_prod:.3f} kWh")
    print(f"Net consumption: {total_elec - total_redel:.3f} kWh")


def save_to_json(hourly: List[Dict], filepath: str) -> None:
    """Save hourly data to JSON file."""
    serializable = []
    for h in hourly:
        d = h.copy()
        d['timestamp'] = h['timestamp'].isoformat()
        serializable.append(d)
    
    with open(filepath, 'w') as f:
        json.dump(serializable, f, indent=2)


def load_from_json(filepath: str) -> List[Dict]:
    """Load hourly data from JSON file."""
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    for d in data:
        d['timestamp'] = datetime.fromisoformat(d['timestamp'])
    
    return data