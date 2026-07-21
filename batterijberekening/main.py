"""
Main CLI entry point for batterijberekening.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

from batterijberekening.data.eneco_client import create_eneco_client
from batterijberekening.data.vattenfall_client import create_vattenfall_client
from batterijberekening.data.timeseries import TimeSeriesBuilder
from batterijberekening.analysis.battery import BatterySizer, BatterySizingResult
from batterijberekening.plotting.plots import create_plotter
from batterijberekening.utils.config import get_config, reload_config

logger = logging.getLogger(__name__)


def setup_logging(config: dict):
    """Configure logging from config."""
    log_config = config.get('logging', {})
    level = getattr(logging, log_config.get('level', 'INFO').upper())
    
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if log_config.get('file'):
        log_file = Path(log_config['file'])
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        level=level,
        format=log_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'),
        handlers=handlers,
    )


def fetch_data(args, config: dict) -> pd.DataFrame:
    """Fetch energy data from provider API."""
    provider = config.get('energy_provider', {}).get('provider', 'eneco')
    years_back = config.get('data', {}).get('years_back', 2)
    
    end_date = pd.Timestamp.now(tz='Europe/Amsterdam').normalize()
    start_date = end_date - pd.DateOffset(years=years_back)
    
    logger.info(f"Fetching {years_back} years of data from {start_date.date()} to {end_date.date()}")
    
    if provider == 'eneco':
        client = create_eneco_client(config)
        if not client.login():
            raise RuntimeError("Failed to login to Eneco")
        # Fetch data in chunks
        # ... implement based on client
    elif provider == 'vattenfall':
        client = create_vattenfall_client(config)
        # Fetch data
        logger.info("Fetching Vattenfall hourly consumption data...")
        raw_data = client.get_usage(start_date.to_pydatetime(), end_date.to_pydatetime())
        logger.info(f"Fetched {len(raw_data)} data chunks from Vattenfall API")
        # Parse and convert to DataFrame
        from batterijberekening.data.vattenfall_summarize import parse_vattenfall_hourly
        hourly_data = parse_vattenfall_hourly(raw_data)
        if hourly_data:
            df = pd.DataFrame(hourly_data)
            df.set_index('timestamp', inplace=True)
            return df
        else:
            logger.warning("No data returned from Vattenfall API")
    else:
        raise ValueError(f"Unknown provider: {provider}")
    
    # For now, return empty - will be implemented with actual API calls
    logger.warning("Data fetching not fully implemented yet - using sample data")
    return pd.DataFrame()


def run_analysis(args, config: dict):
    """Run the complete analysis pipeline."""
    logger.info("Starting battery sizing analysis...")
    
    # Build time series
    builder = TimeSeriesBuilder(config)
    
    # Try to load existing data first
    data_dir = Path(config.get('data', {}).get('data_dir', 'data/raw'))
    processed_dir = Path(config.get('data', {}).get('output_dir', 'data/processed'))
    
    daily_df = None
    quantiles_df = None
    
    if not args.force_fetch:
        # Try to load processed data
        daily_path = processed_dir / 'night_consumption_daily.parquet'
        quantiles_path = processed_dir / 'monthly_quantiles.parquet'
        if daily_path.exists():
            logger.info(f"Loading existing daily data from {daily_path}")
            daily_df = pd.read_parquet(daily_path)
        if quantiles_path.exists():
            logger.info(f"Loading existing quantiles from {quantiles_path}")
            quantiles_df = pd.read_parquet(quantiles_path)
    
    if daily_df is None or args.force_fetch:
        logger.info("Building time series from raw data...")
        daily_df, quantiles_df = builder.run_full_pipeline()
    
    logger.info(f"Daily data shape: {daily_df.shape}")
    logger.info(f"Night consumption stats:\n{daily_df['night_consumption_kwh'].describe()}")
    
    # Battery sizing
    sizer = BatterySizer(config)
    result = sizer.analyze(daily_df)
    
    # Output results
    logger.info("\n" + "="*50)
    logger.info("BATTERY SIZING RESULTS")
    logger.info("="*50)
    logger.info(f"Minimum capacity (P{int(result.min_capacity_percentile*100)}): {result.min_capacity_kwh:.1f} kWh")
    logger.info(f"Recommended capacity (P{int(result.recommended_capacity_percentile*100)}): {result.recommended_capacity_kwh:.1f} kWh")
    logger.info(f"Maximum capacity (P{int(result.max_capacity_percentile*100)}): {result.max_capacity_kwh:.1f} kWh")
    logger.info(f"\nAnnual night consumption: {result.annual_night_consumption_kwh:.1f} kWh")
    logger.info(f"Annual savings potential: €{result.annual_savings_potential_eur:,.0f}")
    logger.info(f"Battery cost (recommended): €{result.battery_cost_eur:,.0f}")
    logger.info(f"Payback period: {result.payback_years:.1f} years ({result.payback_years_lower:.1f} - {result.payback_years_upper:.1f})")
    logger.info("="*50)
    
    # Save results
    output_dir = Path(config.get('data', {}).get('exports_dir', 'output/exports'))
    output_dir.mkdir(parents=True, exist_ok=True)
    
    result_path = output_dir / 'battery_sizing_result.json'
    with open(result_path, 'w') as f:
        f.write(result.to_json())
    logger.info(f"Saved results to {result_path}")
    
    # Generate markdown report
    report_path = output_dir / 'battery_sizing_report.md'
    with open(report_path, 'w') as f:
        f.write(sizer.generate_report(result))
    logger.info(f"Saved report to {report_path}")
    
    # Generate plots
    if not args.no_plots:
        logger.info("Generating plots...")
        plotter = create_plotter(config)
        plotter.save_all_plots(daily_df, quantiles_df)
        logger.info("Plots saved to output/plots/")
    
    return result


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='batterijberekening - Home battery sizing analysis from energy data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  batterijberekening                    # Run full analysis
  batterijberekening --fetch-only       # Only fetch data from API
  batterijberekening --no-plots         # Skip plot generation
  batterijberekening --force-fetch      # Force re-fetch from API
  batterijberekening --check-api        # Test API connection (Vattenfall)
  batterijberekening --provider vattenfall --check-api  # Test Vattenfall token
        """
    )
    
    parser.add_argument('--fetch-only', action='store_true',
                       help='Only fetch data from API, skip analysis')
    parser.add_argument('--no-plots', action='store_true',
                       help='Skip plot generation')
    parser.add_argument('--force-fetch', action='store_true',
                       help='Force re-fetch data from API')
    parser.add_argument('--config', type=str, default='config.yaml',
                       help='Path to config file')
    parser.add_argument('--provider', choices=['eneco', 'vattenfall'],
                       help='Override energy provider')
    parser.add_argument('--years', type=int, default=2,
                       help='Years of historical data to fetch')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable debug logging')
    parser.add_argument('--check-api', action='store_true',
                       help='Test API connection and return status')
    
    args = parser.parse_args()
    
    # Load config
    config = get_config(args.config)
    
    # Override config from CLI
    if args.provider:
        config.setdefault('energy_provider', {})['provider'] = args.provider
    if args.years:
        config.setdefault('data', {})['years_back'] = args.years
    if args.verbose:
        config.setdefault('logging', {})['level'] = 'DEBUG'
    
    # Setup logging
    setup_logging(config)
    
    try:
        if args.check_api:
            # Test API connection
            provider = config.get('energy_provider', {}).get('provider', 'eneco')
            if provider == 'vattenfall':
                client = create_vattenfall_client(config)
                from datetime import datetime, timedelta
                test_data = client.get_hourly_consumption(datetime.now(), 1)
                if test_data:
                    logger.info(f"✅ API connection OK — got {len(test_data)} items")
                    logger.info(f"   Sample: {json.dumps(test_data[0], indent=2)[:500]}")
                else:
                    logger.warning("⚠️  API returned empty data (token might be expired)")
            else:
                logger.warning(f"--check-api not implemented for provider '{provider}'")
            return
        
        if args.fetch_only:
            fetch_data(args, config)
            logger.info("Data fetch complete")
        else:
            run_analysis(args, config)
            logger.info("Analysis complete!")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=args.verbose)
        sys.exit(1)


if __name__ == '__main__':
    main()