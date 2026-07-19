"""
Time series data processing for batterijberekening.
Builds daily DataFrames from hourly consumption and solar data.
"""

import logging
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
import pytz

from batterijberekening.utils.config import get_config

logger = logging.getLogger(__name__)


class TimeSeriesBuilder:
    """Builds daily time series DataFrames from hourly energy data."""
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or get_config()
        self.data_config = self.config.get('data', {})
        self.tz_config = self.config.get('timezone', {})
        self.nc_config = self.config.get('night_consumption', {})
        
        # Timezone
        self.timezone = pytz.timezone(self.tz_config.get('zone', 'Europe/Amsterdam'))
        
        # Data paths
        self.data_dir = Path(self.data_config.get('data_dir', 'data'))
        self.output_dir = Path(self.data_config.get('output_dir', 'output'))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Settings
        self.years_back = self.data_config.get('years_back', 2)
        self.interval = self.data_config.get('interval', 'Hour')
        self.min_hours_per_day = self.nc_config.get('min_hours_per_day', 24)
        self.solar_threshold_pct = self.nc_config.get('solar_threshold_pct', 0.01)
        
        # Storage
        self._raw_data: List[Dict] = []
        self._daily_df: Optional[pd.DataFrame] = None
        self._consumption_df: Optional[pd.DataFrame] = None
        self._solar_df: Optional[pd.DataFrame] = None
    
    def load_raw_data(self, file_path: Union[str, Path]) -> List[Dict]:
        """Load raw API data from JSON lines file."""
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Data file not found: {file_path}")
        
        self._raw_data = []
        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                try:
                    self._raw_data.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        
        logger.info(f"Loaded {len(self._raw_data)} raw data records from {file_path}")
        return self._raw_data
    
    def parse_eneco_data(self, raw_data: List[Dict]) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Parse Eneco API response into hourly consumption and solar DataFrames.
        
        Returns:
            Tuple of (consumption_df, solar_df) with hourly data indexed by timestamp.
        """
        records = []
        
        for response in raw_data:
            if not response or 'data' not in response:
                continue
            
            for usage_week in response['data'].get('usages', []):
                for entry in usage_week.get('entries', []):
                    actual = entry.get('actual', {})
                    if not actual:
                        continue
                    
                    # Parse timestamp
                    date_str = actual.get('date', '')
                    try:
                        ts = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        # Convert to local timezone
                        ts = ts.astimezone(self.timezone)
                    except (ValueError, AttributeError):
                        continue
                    
                    # Extract electricity consumption (high + low tariff)
                    electricity = actual.get('electricity', {})
                    consumption = 0.0
                    if electricity:
                        consumption = (electricity.get('high', 0) or 0) + (electricity.get('low', 0) or 0)
                    
                    # Extract solar production (redelivery = teruglevering)
                    redelivery = actual.get('redelivery', {})
                    solar = 0.0
                    if redelivery:
                        solar = (redelivery.get('high', 0) or 0) + (redelivery.get('low', 0) or 0)
                    
                    # Extract produced (if available separately)
                    produced = actual.get('produced', {})
                    produced_val = 0.0
                    if produced:
                        produced_val = (produced.get('high', 0) or 0) + (produced.get('low', 0) or 0)
                    
                    # Use redelivery as solar proxy if produced not available
                    if produced_val > 0:
                        solar = produced_val
                    
                    records.append({
                        'timestamp': ts,
                        'consumption_kwh': consumption,
                        'solar_kwh': solar,
                        'produced_kwh': produced_val,
                    })
        
        if not records:
            logger.warning("No valid records found in Eneco data")
            return pd.DataFrame(), pd.DataFrame()
        
        df = pd.DataFrame(records)
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)
        
        # Resample to hourly frequency and handle DST
        df = df.asfreq('h')
        
        # Split into consumption and solar
        consumption_df = df[['consumption_kwh']].copy()
        solar_df = df[['solar_kwh', 'produced_kwh']].copy()
        
        logger.info(f"Parsed {len(consumption_df)} hourly consumption records")
        logger.info(f"Parsed {len(solar_df)} hourly solar records")
        
        return consumption_df, solar_df
    
    def parse_vattenfall_data(self, raw_data: List[Dict]) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Parse Vattenfall API response into hourly consumption and solar DataFrames.
        
        Returns:
            Tuple of (consumption_df, solar_df) with hourly data indexed by timestamp.
        """
        records = []
        
        for response in raw_data:
            if not response:
                continue
            
            consumption_header = response.get('ConsumptionHeaderSet', [])
            for header in consumption_header:
                product = header.get('Product', '')
                consumption_set = header.get('ConsumptionSet', [])
                
                for item in consumption_set:
                    date_str = item.get('DateFrom', '')
                    time_str = item.get('TimeFrom', '00:00')
                    delivery = float(item.get('DeliveryQuantity', 0) or 0)
                    redelivery = float(item.get('BackDeliveryQuantity', 0) or 0)
                    
                    try:
                        ts = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                        ts = self.timezone.localize(ts)
                    except (ValueError, TypeError):
                        continue
                    
                    records.append({
                        'timestamp': ts,
                        'product': product,
                        'consumption_kwh': delivery,
                        'solar_kwh': redelivery,
                    })
        
        if not records:
            logger.warning("No valid records found in Vattenfall data")
            return pd.DataFrame(), pd.DataFrame()
        
        df = pd.DataFrame(records)
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)
        
        # Check for multiple solar sources
        solar_sources = df[df['solar_kwh'] > 0]['product'].unique()
        if len(solar_sources) > 1:
            raise ValueError(
                f"Multiple solar sources detected: {solar_sources}. "
                "Please specify how to aggregate."
            )
        
        # Aggregate by timestamp (sum across products)
        consumption_df = df.groupby(df.index)['consumption_kwh'].sum().to_frame()
        solar_df = df.groupby(df.index)['solar_kwh'].sum().to_frame()
        
        # Resample to hourly
        consumption_df = consumption_df.asfreq('h')
        solar_df = solar_df.asfreq('h')
        
        logger.info(f"Parsed {len(consumption_df)} hourly consumption records (Vattenfall)")
        logger.info(f"Parsed {len(solar_df)} hourly solar records (Vattenfall)")
        
        return consumption_df, solar_df
    
    def build_daily_dataframe(
        self,
        consumption_df: pd.DataFrame,
        solar_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Build daily DataFrame with hours as columns.
        
        Each row = one day, each column = hour of day (0-23).
        Includes both consumption and solar production.
        """
        if consumption_df.empty or solar_df.empty:
            raise ValueError("Empty consumption or solar DataFrame")
        
        # Align indices
        common_index = consumption_df.index.intersection(solar_df.index)
        consumption_df = consumption_df.loc[common_index]
        solar_df = solar_df.loc[common_index]
        
        # Resample to daily frequency and pivot
        daily_dfs = []
        
        for name, df in [('consumption', consumption_df), ('solar', solar_df)]:
            col_name = df.columns[0]
            
            # Create date and hour columns
            df = df.copy()
            df['date'] = df.index.date
            df['hour'] = df.index.hour
            
            # Pivot: rows = dates, columns = hours
            pivot = df.pivot_table(
                index='date',
                columns='hour',
                values=col_name,
                aggfunc='first'
            )
            
            # Ensure all 24 hours present
            for h in range(24):
                if h not in pivot.columns:
                    pivot[h] = np.nan
            
            pivot = pivot.reindex(sorted(pivot.columns), axis=1)
            pivot.columns = [f"{name}_h{h:02d}" for h in pivot.columns]
            
            daily_dfs.append(pivot)
        
        # Combine
        daily_df = pd.concat(daily_dfs, axis=1)
        daily_df.index = pd.to_datetime(daily_df.index)
        daily_df.index.name = 'date'
        
        # Drop days with missing hours
        initial_count = len(daily_df)
        daily_df = daily_df.dropna(thresh=self.min_hours_per_day * 2)  # 2 variables per hour
        dropped = initial_count - len(daily_df)
        
        if dropped > 0:
            logger.warning(f"Dropped {dropped} days with insufficient hourly data")
            # Log dropped dates
            dropped_dates = set(pd.to_datetime(daily_df.index).date) ^ set(
                pd.to_datetime(daily_df.index).date
            )
            for d in dropped_dates:
                logger.warning(f"Dropped day {d}: insufficient hourly data")
        
        logger.info(f"Built daily DataFrame with {len(daily_df)} days and {len(daily_df.columns)} columns")
        
        self._daily_df = daily_df
        self._consumption_df = consumption_df
        self._solar_df = solar_df
        
        return daily_df
    
    def calculate_night_consumption(self, daily_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """
        Calculate night consumption metric for each day.
        
        Night hours = hours where solar production <= 1% of day's max solar production.
        
        Args:
            daily_df: Daily DataFrame with hourly columns. Uses self._daily_df if not provided.
            
        Returns:
            DataFrame with added 'night_consumption_kwh' column.
        """
        if daily_df is None:
            daily_df = self._daily_df
        
        if daily_df is None:
            raise ValueError("No daily DataFrame available. Call build_daily_dataframe first.")
        
        df = daily_df.copy()
        
        # Identify solar columns
        solar_cols = [c for c in df.columns if c.startswith('solar_h')]
        consumption_cols = [c for c in df.columns if c.startswith('consumption_h')]
        
        if not solar_cols or not consumption_cols:
            raise ValueError("Missing solar or consumption columns in daily DataFrame")
        
        night_consumption = []
        
        for idx, row in df.iterrows():
            # Get solar values for this day
            solar_values = row[solar_cols].values
            consumption_values = row[consumption_cols].values
            
            # Find max solar for the day
            max_solar = np.nanmax(solar_values)
            
            if max_solar <= 0 or np.isnan(max_solar):
                # No solar production at all - all hours are "night"
                threshold = 0
            else:
                threshold = max_solar * self.solar_threshold_pct
            
            # Identify night hours (solar <= threshold)
            night_mask = solar_values <= threshold
            
            # Sum consumption during night hours
            night_cons = np.nansum(consumption_values[night_mask])
            night_consumption.append(night_cons)
        
        df['night_consumption_kwh'] = night_consumption
        df['max_solar_kwh'] = df[solar_cols].max(axis=1)
        df['total_consumption_kwh'] = df[consumption_cols].sum(axis=1)
        df['total_solar_kwh'] = df[solar_cols].sum(axis=1)
        
        logger.info(f"Calculated night_consumption_kwh for {len(df)} days")
        logger.info(f"Night consumption range: {df['night_consumption_kwh'].min():.2f} - {df['night_consumption_kwh'].max():.2f} kWh")
        
        self._daily_df = df
        return df
    
    def get_monthly_groups(self, daily_df: Optional[pd.DataFrame] = None) -> pd.core.groupby.DataFrameGroupBy:
        """Group daily data by year-month."""
        if daily_df is None:
            daily_df = self._daily_df
        
        if daily_df is None:
            raise ValueError("No daily DataFrame available")
        
        df = daily_df.copy()
        df['year_month'] = df.index.strftime('%Y-%m')
        
        return df.groupby('year_month')
    
    def compute_monthly_quantiles(
        self,
        daily_df: Optional[pd.DataFrame] = None,
        quantiles: Optional[List[float]] = None,
    ) -> pd.DataFrame:
        """
        Compute quantiles of night_consumption_kwh for each month.
        
        Returns:
            DataFrame with index=YYYY-MM, columns=quantiles.
        """
        if daily_df is None:
            daily_df = self._daily_df
        
        if daily_df is None:
            raise ValueError("No daily DataFrame available")
        
        if quantiles is None:
            quantiles = [0.05, 0.25, 0.50, 0.75, 0.95]
        
        df = daily_df.copy()
        df['year_month'] = df.index.strftime('%Y-%m')
        
        quantile_dfs = []
        
        for ym, group in df.groupby('year_month'):
            q_values = group['night_consumption_kwh'].quantile(quantiles)
            q_values.name = ym
            quantile_dfs.append(q_values)
        
        result = pd.concat(quantile_dfs, axis=1).T
        result.index.name = 'year_month'
        result.columns = [f'q{int(q*100):02d}' for q in quantiles]
        
        logger.info(f"Computed monthly quantiles for {len(result)} months")
        
        return result
    
    def save_processed_data(
        self,
        daily_df: Optional[pd.DataFrame] = None,
        quantiles_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Path]:
        """Save processed data to output directory."""
        if daily_df is None:
            daily_df = self._daily_df
        
        output_files = {}
        
        # Save daily DataFrame
        daily_path = self.output_dir / 'night_consumption_daily.parquet'
        daily_df.to_parquet(daily_path)
        output_files['daily_parquet'] = daily_path
        
        daily_csv = self.output_dir / 'night_consumption_daily.csv'
        daily_df.to_csv(daily_csv)
        output_files['daily_csv'] = daily_csv
        
        # Save quantiles
        if quantiles_df is not None:
            quantiles_path = self.output_dir / 'monthly_quantiles.parquet'
            quantiles_df.to_parquet(quantiles_path)
            output_files['quantiles_parquet'] = quantiles_path
            
            quantiles_csv = self.output_dir / 'monthly_quantiles.csv'
            quantiles_df.to_csv(quantiles_csv)
            output_files['quantiles_csv'] = quantiles_csv
        
        logger.info(f"Saved processed data to {self.output_dir}")
        
        return output_files
    
    def run_full_pipeline(
        self,
        raw_data: Optional[List[Dict]] = None,
        provider: str = 'eneco',
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Run the complete pipeline from raw data to daily DataFrame and quantiles.
        
        Args:
            raw_data: Optional raw data to process. If not provided, loads from file.
            provider: Energy provider ('eneco' or 'vattenfall')
            
        Returns:
            Tuple of (daily_df, monthly_quantiles_df)
        """
        if raw_data is None:
            # Try to load from default raw data file
            raw_file = self.data_dir / 'raw_data.jsonl'
            if raw_file.exists():
                logger.info(f"Loading raw data from {raw_file}")
                raw_data = self.load_raw_data(raw_file)
            else:
                logger.warning("No raw data provided or found")
                return pd.DataFrame(), pd.DataFrame()
        
        if provider == 'eneco':
            consumption_df, solar_df = self.parse_eneco_data(raw_data)
        elif provider == 'vattenfall':
            consumption_df, solar_df = self.parse_vattenfall_data(raw_data)
        else:
            raise ValueError(f"Unknown provider: {provider}")
        
        daily_df = self.build_daily_dataframe(consumption_df, solar_df)
        daily_df = self.calculate_night_consumption(daily_df)
        quantiles_df = self.compute_monthly_quantiles(daily_df)
        
        self.save_processed_data(daily_df, quantiles_df)
        
        return daily_df, quantiles_df


def build_full_timeseries(
    raw_data: List[Dict],
    provider: str = 'eneco',
    config: Optional[Dict] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Convenience function to build full time series from raw data.
    
    Returns:
        Tuple of (daily_df, monthly_quantiles_df)
    """
    builder = TimeSeriesBuilder(config)
    
    if provider == 'eneco':
        consumption_df, solar_df = builder.parse_eneco_data(raw_data)
    elif provider == 'vattenfall':
        consumption_df, solar_df = builder.parse_vattenfall_data(raw_data)
    else:
        raise ValueError(f"Unknown provider: {provider}")
    
    daily_df = builder.build_daily_dataframe(consumption_df, solar_df)
    daily_df = builder.calculate_night_consumption(daily_df)
    quantiles_df = builder.compute_monthly_quantiles(daily_df)
    
    builder.save_processed_data(daily_df, quantiles_df)
    
    return daily_df, quantiles_df


# Need to import json for the load_raw_data method
import json