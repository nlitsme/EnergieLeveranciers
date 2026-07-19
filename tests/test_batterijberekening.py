"""
Unit tests for batterijberekening.
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import pytz

from batterijberekening.data.timeseries import TimeSeriesBuilder
from batterijberekening.analysis.battery import BatterySizer, BatterySizingResult


class TestTimeSeriesBuilder:
    """Tests for TimeSeriesBuilder."""
    
    @pytest.fixture
    def builder(self):
        """Create a TimeSeriesBuilder with test config."""
        config = {
            'timezone': {'zone': 'Europe/Amsterdam'},
            'data': {
                'years_back': 2,
                'data_dir': 'data/raw',
                'output_dir': 'data/processed',
            },
            'night_consumption': {
                'solar_threshold_pct': 0.01,
                'min_hours_per_day': 24,
            },
            'energy_provider': {'provider': 'eneco'},
            'plotting': {'interactive': {'enabled': False}},
        }
        return TimeSeriesBuilder(config)
    
    @pytest.fixture
    def sample_hourly_data(self):
        """Create sample hourly consumption and solar data."""
        tz = pytz.timezone('Europe/Amsterdam')
        dates = pd.date_range('2024-01-01', '2024-01-10 23:00', freq='h', tz=tz)
        
        # Consumption: higher at night, lower during day
        consumption = np.ones(len(dates)) * 0.5
        consumption[(dates.hour >= 7) & (dates.hour <= 22)] = 0.3  # Daytime lower
        consumption[(dates.hour >= 18) & (dates.hour <= 23)] = 0.8  # Evening peak
        
        # Solar: zero at night, peak at noon
        solar = np.zeros(len(dates))
        solar[(dates.hour >= 8) & (dates.hour <= 16)] = np.sin(
            (dates.hour[(dates.hour >= 8) & (dates.hour <= 16)] - 8) * np.pi / 8
        ) * 2.0  # Peak ~2 kWh
        
        consumption_df = pd.DataFrame({'consumption_kwh': consumption}, index=dates)
        solar_df = pd.DataFrame({'solar_kwh': solar}, index=dates)
        
        return consumption_df, solar_df
    
    def test_build_daily_dataframe(self, builder, sample_hourly_data):
        """Test building daily DataFrame from hourly data."""
        consumption_df, solar_df = sample_hourly_data
        
        daily_df = builder.build_daily_dataframe(consumption_df, solar_df)
        
        assert isinstance(daily_df, pd.DataFrame)
        assert len(daily_df) == 10  # 10 days
        assert 'consumption_h00' in daily_df.columns
        assert 'consumption_h23' in daily_df.columns
        assert 'solar_h00' in daily_df.columns
        assert 'solar_h23' in daily_df.columns
        assert len(daily_df.columns) == 48  # 24 hours × 2 variables
    
    def test_calculate_night_consumption(self, builder, sample_hourly_data):
        """Test night consumption calculation."""
        consumption_df, solar_df = sample_hourly_data
        
        daily_df = builder.build_daily_dataframe(consumption_df, solar_df)
        daily_df = builder.calculate_night_consumption(daily_df)
        
        assert 'night_consumption_kwh' in daily_df.columns
        assert 'max_solar_kwh' in daily_df.columns
        assert 'total_consumption_kwh' in daily_df.columns
        assert 'total_solar_kwh' in daily_df.columns
        
        # Night consumption should be > 0
        assert (daily_df['night_consumption_kwh'] > 0).all()
        
        # Should be less than total consumption
        assert (daily_df['night_consumption_kwh'] <= daily_df['total_consumption_kwh']).all()
    
    def test_compute_monthly_quantiles(self, builder, sample_hourly_data):
        """Test monthly quantile computation."""
        consumption_df, solar_df = sample_hourly_data
        
        daily_df = builder.build_daily_dataframe(consumption_df, solar_df)
        daily_df = builder.calculate_night_consumption(daily_df)
        quantiles_df = builder.compute_monthly_quantiles(daily_df)
        
        assert isinstance(quantiles_df, pd.DataFrame)
        assert len(quantiles_df) == 1  # One month
        assert 'q05' in quantiles_df.columns
        assert 'q25' in quantiles_df.columns
        assert 'q50' in quantiles_df.columns
        assert 'q75' in quantiles_df.columns
        assert 'q95' in quantiles_df.columns
        
        # Quantiles should be ordered
        row = quantiles_df.iloc[0]
        assert row['q05'] <= row['q25'] <= row['q50'] <= row['q75'] <= row['q95']


class TestBatterySizer:
    """Tests for BatterySizer."""
    
    @pytest.fixture
    def sizer(self):
        """Create a BatterySizer with test config."""
        config = {
            'battery': {
                'battery_cost_per_kwh': 600,
                'energy_price_per_kwh': 0.30,
                'feedin_tariff_per_kwh': 0.08,
                'roundtrip_efficiency': 0.90,
                'dod_limit': 0.90,
                'min_capacity_percentile': 0.05,
                'recommended_capacity_percentile': 0.50,
                'max_capacity_percentile': 0.95,
            }
        }
        return BatterySizer(config)
    
    @pytest.fixture
    def sample_daily_data(self):
        """Create sample daily data with night consumption."""
        dates = pd.date_range('2024-01-01', '2024-12-31', freq='D')
        # Night consumption varying by season
        night_consumption = 5 + 3 * np.sin(2 * np.pi * dates.dayofyear / 365) + np.random.normal(0, 0.5, len(dates))
        night_consumption = np.maximum(night_consumption, 0.5)
        
        df = pd.DataFrame({'night_consumption_kwh': night_consumption}, index=dates)
        return df
    
    def test_calculate_sizing(self, sizer, sample_daily_data):
        """Test battery capacity calculation for percentiles."""
        night_consumption = sample_daily_data['night_consumption_kwh']
        
        capacities = sizer.calculate_sizing(night_consumption)
        
        assert 0.05 in capacities
        assert 0.50 in capacities
        assert 0.95 in capacities
        
        # Capacities should be ordered
        assert capacities[0.05] <= capacities[0.50] <= capacities[0.95]
        
        # Should be positive
        assert all(c > 0 for c in capacities.values())
    
    def test_calculate_payback(self, sizer):
        """Test payback period calculation."""
        battery_cap = 10.0  # kWh
        annual_night = 2000  # kWh
        
        payback, low, high = sizer.calculate_payback(battery_cap, annual_night)
        
        assert payback > 0
        # Check ±50% uncertainty band (within floating point precision)
        assert abs(low - payback * 0.5) < 0.2
        assert abs(high - payback * 1.5) < 0.2
        assert low <= payback <= high
    
    def test_analyze(self, sizer, sample_daily_data):
        """Test full analysis pipeline."""
        result = sizer.analyze(sample_daily_data)
        
        assert isinstance(result, BatterySizingResult)
        assert result.min_capacity_kwh > 0
        assert result.recommended_capacity_kwh > 0
        assert result.max_capacity_kwh > 0
        assert result.min_capacity_kwh <= result.recommended_capacity_kwh <= result.max_capacity_kwh
        assert result.payback_years > 0
        assert result.payback_years_lower <= result.payback_years <= result.payback_years_upper
        assert result.annual_night_consumption_kwh > 0
        assert result.battery_cost_eur > 0
    
    def test_generate_report(self, sizer, sample_daily_data):
        """Test report generation."""
        result = sizer.analyze(sample_daily_data)
        report = sizer.generate_report(result)
        
        assert isinstance(report, str)
        assert 'Batterij Dimensionering' in report
        assert f'{result.recommended_capacity_kwh:.1f} kWh' in report
        assert f'{result.payback_years:.1f} jaar' in report
        assert 'Terugverdientijd' in report


class TestNightConsumptionEdgeCases:
    """Test edge cases for night consumption calculation."""
    
    @pytest.fixture
    def builder(self):
        config = {
            'timezone': {'zone': 'Europe/Amsterdam'},
            'data': {'data_dir': 'data/raw', 'output_dir': 'data/processed'},
            'night_consumption': {'solar_threshold_pct': 0.01, 'min_hours_per_day': 24},
            'energy_provider': {'provider': 'eneco'},
        }
        return TimeSeriesBuilder(config)
    
    def test_no_solar_day(self, builder):
        """Test night consumption when no solar production at all."""
        tz = pytz.timezone('Europe/Amsterdam')
        dates = pd.date_range('2024-01-01', periods=24, freq='h', tz=tz)
        
        consumption = np.ones(24) * 0.5
        solar = np.zeros(24)
        
        consumption_df = pd.DataFrame({'consumption_kwh': consumption}, index=dates)
        solar_df = pd.DataFrame({'solar_kwh': solar}, index=dates)
        
        daily_df = builder.build_daily_dataframe(consumption_df, solar_df)
        daily_df = builder.calculate_night_consumption(daily_df)
        
        # All hours are night, so night consumption = total consumption
        assert daily_df['night_consumption_kwh'].iloc[0] == 12.0  # 24h × 0.5
    
    def test_all_solar_day(self, builder):
        """Test night consumption when solar exceeds consumption all day."""
        tz = pytz.timezone('Europe/Amsterdam')
        dates = pd.date_range('2024-06-15', periods=24, freq='h', tz=tz)
        
        consumption = np.ones(24) * 0.3
        # Solar > consumption during day
        solar = np.zeros(24)
        solar[(dates.hour >= 8) & (dates.hour <= 16)] = 2.0
        
        consumption_df = pd.DataFrame({'consumption_kwh': consumption}, index=dates)
        solar_df = pd.DataFrame({'solar_kwh': solar}, index=dates)
        
        daily_df = builder.build_daily_dataframe(consumption_df, solar_df)
        daily_df = builder.calculate_night_consumption(daily_df)
        
        # Night hours should only be when solar <= 1% of max (0.02)
        # Max solar = 2.0, threshold = 0.02
        # Night hours = 0-7, 17-23 = 15 hours
        # Night consumption = 15 × 0.3 = 4.5
        night_cons = daily_df['night_consumption_kwh'].iloc[0]
        assert night_cons == pytest.approx(4.5, rel=0.1)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])