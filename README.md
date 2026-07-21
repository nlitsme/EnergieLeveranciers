# batterijberekening

Home battery sizing and analysis based on hourly electricity consumption and solar production data from Dutch energy providers (Eneco, Vattenfall).

## Overview

This tool fetches your historical hourly electricity consumption and solar production data (teruglevering) from your energy provider's API, calculates your night-time consumption (when solar production is negligible), and determines optimal battery sizing with payback period calculations.

### Features

- **Data Fetching**: Pull 2+ years of hourly data from Eneco or Vattenfall APIs
- **Time Series Construction**: Build daily DataFrames with hours as columns (handling DST correctly)
- **Night Consumption Metric**: Calculate daily consumption during hours with ≤1% of daily peak solar production
- **Monthly Analysis**: Boxplots and quantile ribbon plots of night consumption by month
- **Battery Sizing**: Compute min/recommended/max capacity based on percentiles (P5/P50/P95)
- **Payback Calculation**: Estimate payback period with ±50% uncertainty band
- **Interactive Visualizations**: Plotly-based HTML plots with hover tooltips
- **Exports**: Parquet, CSV, JSON, and Markdown reports

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/batterijberekening.git
cd batterijberekening

# Install in development mode
pip install -e ".[dev]"
```

## Configuration

Copy the example config and set your credentials:

```bash
cp config.yaml.example config.yaml
# Edit config.yaml with your settings
```

Or use environment variables (recommended for secrets):

```bash
export ENERGY_PROVIDER=eneco  # or vattenfall
export ENECO_USERNAME=your@email.com
export ENECO_PASSWORD=yourpassword
# For Vattenfall:
export VATTENFALL_AUTH_TOKEN=your_bearer_token  # Expires every 2h, re-extract from browser
export VATTENFALL_CUSTOMER_ID=0025431819
export VATTENFALL_VF_CONTEXT=0025431819:003015847385
export VATTENFALL_API_KEY=ed989141b5c34d138dba4a3ce1dbe046
```

### Config Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `energy_provider.provider` | "eneco" or "vattenfall" | "eneco" |
| `data.years_back` | Years of history to fetch | 2 |
| `night_consumption.solar_threshold_pct` | Solar threshold for "night" hours | 0.01 (1%) |
| `battery.battery_cost_per_kwh` | Installed battery cost €/kWh | 600 |
| `battery.energy_price_per_kwh` | Grid electricity price €/kWh | 0.30 |
| `battery.feedin_tariff_per_kwh` | Feed-in tariff €/kWh | 0.08 |
| `battery.roundtrip_efficiency` | Battery round-trip efficiency | 0.90 |
| `battery.dod_limit` | Depth of discharge limit | 0.90 |

## Usage

### Full Analysis Pipeline

```bash
# Run complete analysis (fetch data, process, analyze, plot)
batterijberekening

# Force re-fetch from API
batterijberekening --force-fetch

# Skip plot generation
batterijberekening --no-plots

# Use different provider
batterijberekening --provider vattenfall

# Test Vattenfall API connection (check if token works)
batterijberekening --provider vattenfall --check-api

# Refresh Vattenfall token (after extracting from browser)
./scripts/refresh-vattenfall-token.sh eyJraWQ...<new_token>

# More years of data
batterijberekening --years 3
```

### Step-by-Step

```bash
# 1. Only fetch data from API
batterijberekening --fetch-only

# 2. Run analysis on existing data
batterijberekening --no-plots
```

### Python API

```python
from batterijberekening import TimeSeriesBuilder, BatterySizer, create_plotter

# Build time series from raw data
builder = TimeSeriesBuilder()
consumption_df, solar_df = builder.parse_eneco_data(raw_data)
daily_df = builder.build_daily_dataframe(consumption_df, solar_df)
daily_df = builder.calculate_night_consumption(daily_df)
quantiles_df = builder.compute_monthly_quantiles(daily_df)

# Battery sizing
sizer = BatterySizer()
result = sizer.analyze(daily_df)
print(f"Recommended: {result.recommended_capacity_kwh:.1f} kWh")
print(f"Payback: {result.payback_years:.1f} years")

# Plots
plotter = create_plotter()
plotter.save_all_plots(daily_df, quantiles_df)
```

## Output Files

```
output/
├── plots/
│   ├── monthly_boxplot_night_consumption.png
│   ├── quantile_ribbon_night_consumption.png
│   ├── quantile_ribbon_smoothed_w3.png
│   ├── interactive_quantile_ribbon.html
│   └── interactive_monthly_boxplot.html
├── exports/
│   ├── battery_sizing_result.json
│   ├── battery_sizing_report.md
│   ├── night_consumption_daily.parquet
│   └── monthly_quantiles.parquet
└── processed/
    ├── night_consumption_daily.parquet
    └── monthly_quantiles.parquet
```

## Methodology

### Night Consumption Definition

Hours are classified as "night" (no solar production) when:
```
solar_production ≤ 1% × max(solar_production_for_that_day)
```

This relative threshold avoids noise from early morning/late evening low production.

### Battery Sizing

For each percentile P of daily night consumption:
```
Battery Capacity (kWh) = Night_Consumption_P / (roundtrip_efficiency × dod_limit)
```

- **P5 (Min)**: Covers 95% of nights
- **P50 (Recommended)**: Covers median night  
- **P95 (Max)**: Covers 95% of nights

### Payback Calculation

```
Annual Savings = min(usable_capacity × 365, annual_night_consumption) × (energy_price - feedin_tariff)
Payback = battery_cost / annual_savings
Uncertainty: ±50%
```

## Testing

```bash
# Run tests
pytest

# With coverage
pytest --cov=batterijberekening
```

## Project Structure

```
batterijberekening/
├── batterijberekening/
│   ├── __init__.py
│   ├── main.py                 # CLI entry point
│   ├── data/
│   │   ├── __init__.py
│   │   ├── eneco_client.py     # Eneco API client
│   │   ├── vattenfall_client.py # Vattenfall API client
│   │   └── timeseries.py       # Time series processing
│   ├── analysis/
│   │   ├── __init__.py
│   │   └── battery.py          # Battery sizing & payback
│   ├── plotting/
│   │   ├── __init__.py
│   │   └── plots.py            # Visualization
│   └── utils/
│       ├── __init__.py
│       └── config.py           # Configuration management
├── config.yaml                 # Configuration
├── pyproject.toml             # Package config
├── requirements.txt           # Dependencies
└── README.md                  # This file
```

## License

MIT License - see LICENSE file for details.

## Acknowledgements

Based on the energy provider API clients from [nlitsme/EnergieLeveranciers](https://github.com/nlitsme/EnergieLeveranciers) by Willem Hengeveld.