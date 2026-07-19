"""
Battery sizing and payoff calculation for batterijberekening.
"""

import logging
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple, Any
import json

import numpy as np
import pandas as pd

from batterijberekening.utils.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class BatterySizingResult:
    """Result of battery sizing analysis."""
    min_capacity_kwh: float
    recommended_capacity_kwh: float
    max_capacity_kwh: float
    
    min_capacity_percentile: float
    recommended_capacity_percentile: float
    max_capacity_percentile: float
    
    # Derived metrics
    annual_night_consumption_kwh: float
    annual_savings_potential_eur: float
    battery_cost_eur: float
    payback_years: float
    payback_years_lower: float
    payback_years_upper: float
    
    # Config used
    battery_cost_per_kwh: float
    energy_price_per_kwh: float
    feedin_tariff_per_kwh: float
    roundtrip_efficiency: float
    dod_limit: float
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BatterySizingResult':
        return cls(**data)


class BatterySizer:
    """Calculates optimal battery size based on night consumption patterns."""
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or get_config()
        self.battery_config = self.config.get('battery', {})
        
        # Price assumptions
        self.battery_cost_per_kwh = self.battery_config.get('battery_cost_per_kwh', 600)
        self.energy_price_per_kwh = self.battery_config.get('energy_price_per_kwh', 0.30)
        self.feedin_tariff_per_kwh = self.battery_config.get('feedin_tariff_per_kwh', 0.08)
        self.roundtrip_efficiency = self.battery_config.get('roundtrip_efficiency', 0.90)
        self.dod_limit = self.battery_config.get('dod_limit', 0.90)
        
        # Percentiles for sizing
        self.min_percentile = self.battery_config.get('min_capacity_percentile', 0.05)
        self.recommended_percentile = self.battery_config.get('recommended_capacity_percentile', 0.50)
        self.max_percentile = self.battery_config.get('max_capacity_percentile', 0.95)
    
    def calculate_sizing(
        self,
        night_consumption: pd.Series,
        percentiles: Optional[List[float]] = None,
    ) -> Dict[float, float]:
        """
        Calculate battery capacity for given percentiles of night consumption.
        
        The battery capacity needed is the night consumption at a given percentile,
        adjusted for round-trip efficiency and depth of discharge.
        
        Args:
            night_consumption: Series of daily night consumption values (kWh)
            percentiles: List of percentiles to calculate (default from config)
            
        Returns:
            Dictionary mapping percentile to required battery capacity (kWh)
        """
        if percentiles is None:
            percentiles = [
                self.min_percentile,
                self.recommended_percentile,
                self.max_percentile,
            ]
        
        # Clean data
        clean_data = night_consumption.dropna()
        if len(clean_data) == 0:
            raise ValueError("No valid night consumption data")
        
        # Calculate required battery capacity for each percentile
        # Capacity = night_consumption / (efficiency * dod_limit)
        # This gives the installed capacity needed
        adjustment_factor = self.roundtrip_efficiency * self.dod_limit
        
        results = {}
        for p in percentiles:
            night_kwh = clean_data.quantile(p)
            capacity_kwh = night_kwh / adjustment_factor
            results[p] = round(capacity_kwh, 2)
            logger.info(f"Percentile {p:.0%}: night consumption = {night_kwh:.2f} kWh, "
                       f"battery capacity = {capacity_kwh:.2f} kWh")
        
        return results
    
    def calculate_payback(
        self,
        battery_capacity_kwh: float,
        annual_night_consumption_kwh: float,
        battery_cost_per_kwh: Optional[float] = None,
        energy_price_per_kwh: Optional[float] = None,
        feedin_tariff_per_kwh: Optional[float] = None,
        roundtrip_efficiency: Optional[float] = None,
        dod_limit: Optional[float] = None,
    ) -> Tuple[float, float, float]:
        """
        Calculate battery payback period with uncertainty band.
        
        Payback = Battery Cost / Annual Savings
        Annual Savings = Energy Shifted * (Energy Price - Feed-in Tariff)
        
        The energy shifted is the minimum of:
        - Battery usable capacity * cycles per year
        - Annual night consumption
        
        Args:
            battery_capacity_kwh: Installed battery capacity in kWh
            annual_night_consumption_kwh: Total annual night consumption
            battery_cost_per_kwh: Cost per kWh installed capacity
            energy_price_per_kwh: Price of electricity from grid
            feedin_tariff_per_kwh: Feed-in tariff for solar export
            roundtrip_efficiency: Battery round-trip efficiency
            dod_limit: Depth of discharge limit
            
        Returns:
            Tuple of (payback_years, payback_lower, payback_upper) with ±50% uncertainty
        """
        # Use config defaults if not provided
        battery_cost_per_kwh = float(battery_cost_per_kwh or self.battery_cost_per_kwh)
        energy_price = float(energy_price_per_kwh or self.energy_price_per_kwh)
        feedin_tariff = float(feedin_tariff_per_kwh or self.feedin_tariff_per_kwh)
        efficiency = float(roundtrip_efficiency or self.roundtrip_efficiency)
        dod = float(dod_limit or self.dod_limit)
        
        # Battery cost
        battery_cost = battery_capacity_kwh * battery_cost_per_kwh
        
        # Usable capacity per cycle
        usable_capacity = battery_capacity_kwh * efficiency * dod
        
        # Cycles per year (daily cycling)
        cycles_per_year = 365
        
        # Maximum energy that can be shifted per year
        max_shiftable = usable_capacity * cycles_per_year
        
        # Actual energy shifted is limited by night consumption
        energy_shifted_per_year = min(max_shiftable, annual_night_consumption_kwh)
        
        # Savings per kWh shifted = energy price - feed-in tariff
        savings_per_kwh = energy_price - feedin_tariff
        
        if savings_per_kwh <= 0:
            logger.warning("Energy price <= feed-in tariff, no savings possible")
            return float('inf'), float('inf'), float('inf')
        
        annual_savings = energy_shifted_per_year * savings_per_kwh
        
        if annual_savings <= 0:
            return float('inf'), float('inf'), float('inf')
        
        payback_years = battery_cost / annual_savings
        
        # ±50% uncertainty band
        payback_lower = payback_years * 0.5
        payback_upper = payback_years * 1.5
        
        logger.info(f"Battery: {battery_capacity_kwh:.1f} kWh, Cost: €{battery_cost:,.0f}")
        logger.info(f"Annual night consumption: {annual_night_consumption_kwh:.1f} kWh")
        logger.info(f"Usable capacity/cycle: {usable_capacity:.1f} kWh")
        logger.info(f"Energy shifted/year: {energy_shifted_per_year:.1f} kWh")
        logger.info(f"Annual savings: €{annual_savings:,.0f}")
        logger.info(f"Payback: {payback_years:.1f} years ({payback_lower:.1f}-{payback_upper:.1f})")
        
        return round(payback_years, 1), round(payback_lower, 1), round(payback_upper, 1)
    
    def analyze(
        self,
        daily_df: pd.DataFrame,
        night_col: str = 'night_consumption_kwh',
    ) -> BatterySizingResult:
        """
        Perform complete battery sizing analysis.
        
        Args:
            daily_df: DataFrame with daily data including night consumption
            night_col: Column name for night consumption
            
        Returns:
            BatterySizingResult with all sizing and payback calculations
        """
        night_consumption = daily_df[night_col].dropna()
        
        if len(night_consumption) == 0:
            raise ValueError("No night consumption data available")
        
        # Calculate percentiles
        percentiles = [
            self.min_percentile,
            self.recommended_percentile,
            self.max_percentile,
        ]
        
        capacities = self.calculate_sizing(night_consumption, percentiles)
        
        min_cap = capacities[self.min_percentile]
        rec_cap = capacities[self.recommended_percentile]
        max_cap = capacities[self.max_percentile]
        
        # Annual night consumption
        annual_night = night_consumption.sum() * (365 / len(night_consumption))
        
        # Payback for recommended capacity
        payback, payback_low, payback_high = self.calculate_payback(
            battery_capacity_kwh=rec_cap,
            annual_night_consumption_kwh=annual_night,
        )
        
        # Annual savings potential
        usable_rec = rec_cap * self.roundtrip_efficiency * self.dod_limit
        energy_shifted = min(usable_rec * 365, annual_night)
        annual_savings = energy_shifted * (self.energy_price_per_kwh - self.feedin_tariff_per_kwh)
        
        result = BatterySizingResult(
            min_capacity_kwh=min_cap,
            recommended_capacity_kwh=rec_cap,
            max_capacity_kwh=max_cap,
            min_capacity_percentile=self.min_percentile,
            recommended_capacity_percentile=self.recommended_percentile,
            max_capacity_percentile=self.max_percentile,
            annual_night_consumption_kwh=round(annual_night, 1),
            annual_savings_potential_eur=round(annual_savings, 0),
            battery_cost_eur=round(rec_cap * self.battery_cost_per_kwh, 0),
            payback_years=payback,
            payback_years_lower=payback_low,
            payback_years_upper=payback_high,
            battery_cost_per_kwh=self.battery_cost_per_kwh,
            energy_price_per_kwh=self.energy_price_per_kwh,
            feedin_tariff_per_kwh=self.feedin_tariff_per_kwh,
            roundtrip_efficiency=self.roundtrip_efficiency,
            dod_limit=self.dod_limit,
        )
        
        return result
    
    def generate_report(self, result: BatterySizingResult) -> str:
        """Generate human-readable markdown report."""
        report = f"""# Batterij Dimensionering en Terugverdientijd Analyse

## Samenvatting

| Parameter | Waarde |
|-----------|--------|
| **Minimale capaciteit** (P{int(result.min_capacity_percentile*100)}) | {result.min_capacity_kwh:.1f} kWh |
| **Aanbevolen capaciteit** (P{int(result.recommended_capacity_percentile*100)}) | **{result.recommended_capacity_kwh:.1f} kWh** |
| **Maximale capaciteit** (P{int(result.max_capacity_percentile*100)}) | {result.max_capacity_kwh:.1f} kWh |

## Jaarlijks Nachverbruik
- **Totaal nachverbruik/jaar**: {result.annual_night_consumption_kwh:.0f} kWh
- **Gemiddeld per nacht**: {result.annual_night_consumption_kwh/365:.2f} kWh

## Kostenaannames
- **Batterijkosten**: €{result.battery_cost_per_kwh:,.0f}/kWh (geïnstalleerd)
- **Energieprijs**: €{result.energy_price_per_kwh:.2f}/kWh
- **Terugleververgoeding**: €{result.feedin_tariff_per_kwh:.2f}/kWh
- **Bespuring per kWh**: €{result.energy_price_per_kwh - result.feedin_tariff_per_kwh:.2f}/kWh
- **Rendement (heenu terug)**: {result.roundtrip_efficiency*100:.0f}%
| **Diepte ontlading**: {result.dod_limit*100:.0f}% |

## Investeringsanalyse (Aanbevolen capaciteit: {result.recommended_capacity_kwh:.1f} kWh)

| Item | Waarde |
|------|--------|
| Batterijkosten | €{result.battery_cost_eur:,.0f} |
| Jaarlijkse besparing (theoretisch max) | €{result.annual_savings_potential_eur:,.0f} |
| **Terugverdientijd** | **{result.payback_years:.1f} jaar** |
| Onzekerheidsmarge (±50%) | {result.payback_years_lower:.1f} - {result.payback_years_upper:.1f} jaar |

## Interpretatie

### Hoe worden de capaciteiten bepaald?
De batterijcapaciteit wordt berekend op basis van de nachtelijk elektriciteitsverbruikverdeling:
- **P5 (Minimaal)**: Dekket 95% van de nachten → kleine batterij, lage dekking
- **P50 (Aanbevolen)**: Dekket de mediaan nacht → balans tussen kost en dekking
- **P95 (Maximaal)**: Dekket 95% van de nachten → grote batterij, hoge dekking

Formule: `Capaciteit = Nachtverbruik_percentiel / (Rendement × Diepte_ontlading)`

### Terugverdientijd
De terugverdientijd is een schatting gebaseerd op:
1. Dagelijkse cyclering van de batterij (365 cycli/jaar)
2. Verschil tussen energietarief en terugleververgoeding
3. Batterijrendement en diepte-ontlading limiet

**Let op**: De ±50% onzekerheidsmarge rekening houdt met:
- Seizoensinvloeden (minder zonne-energie in winter)
- Batterijdegradatie over de jaren
- Veranderende energieprijzen
- Daadwerkelijk gebruikspatroon

### Aanbeveling
Voor een typisch huishouden met een aanbevolen capaciteit van **{result.recommended_capacity_kwh:.1f} kWh**:
- Investeringsbedrag: ~€{result.battery_cost_eur:,.0f}
- Verwachte terugverdientijd: **{result.payback_years:.1f} jaar** (bereik: {result.payback_years_lower:.1f}-{result.payback_years_upper:.1f} jaar)
- Jaarlijkse besparing: ~€{result.annual_savings_potential_eur:,.0f}

*Rapport gegenereerd op: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}*
"""
        return report


def create_battery_sizer(config: Optional[Dict] = None) -> BatterySizer:
    """Factory function to create BatterySizer instance."""
    return BatterySizer(config)