"""
Plotting module for batterijberekening.
Creates boxplots, ribbon plots, and interactive visualizations.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import json

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

from batterijberekening.utils.config import get_config

logger = logging.getLogger(__name__)


class Plotter:
    """Creates all visualizations for battery sizing analysis."""
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or get_config()
        self.plot_config = self.config.get('plotting', {})
        
        # Style settings
        self.style = self.plot_config.get('style', 'whitegrid')
        self.palette = self.plot_config.get('palette', 'viridis')
        self.figsize = self.plot_config.get('figsize', [12, 8])
        self.dpi = self.plot_config.get('dpi', 150)
        
        # Colors
        self.median_color = self.plot_config.get('median_color', '#2E86AB')
        self.iqr_color = self.plot_config.get('iqr_color', '#A23B72')
        self.outer_color = self.plot_config.get('outer_color', '#F18F01')
        
        # Font sizes
        self.title_size = self.plot_config.get('title_size', 16)
        self.label_size = self.plot_config.get('label_size', 14)
        self.tick_size = self.plot_config.get('tick_size', 12)
        self.legend_size = self.plot_config.get('legend_size', 11)
        
        # Output directories
        data_config = self.config.get('data', {})
        self.plots_dir = Path(data_config.get('plots_dir', 'output/plots'))
        self.plots_dir.mkdir(parents=True, exist_ok=True)
        
        self.exports_dir = Path(data_config.get('exports_dir', 'output/exports'))
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        
        # Set seaborn style
        sns.set_style(self.style)
        sns.set_palette(self.palette)
    
    def plot_monthly_boxplots(
        self,
        daily_df: pd.DataFrame,
        night_col: str = 'night_consumption_kwh',
        save: bool = True,
        show: bool = False,
    ) -> plt.Figure:
        """
        Create monthly boxplots of night consumption.
        
        Args:
            daily_df: DataFrame with daily data including night_consumption_kwh
            night_col: Column name for night consumption
            save: Whether to save the plot
            show: Whether to display the plot
            
        Returns:
            Matplotlib figure
        """
        # Ensure we have month column
        df = daily_df.copy()
        if 'month' not in df.columns:
            df['month'] = df.index.to_period('M').astype(str)
        
        # Create figure
        fig, ax = plt.subplots(figsize=self.figsize, dpi=self.dpi)
        
        # Create boxplot using seaborn
        sns.boxplot(
            data=df,
            x='month',
            y=night_col,
            ax=ax,
            palette=self.palette,
            showfliers=True,
            flierprops={'marker': 'o', 'markersize': 3, 'alpha': 0.5},
        )
        
        # Formatting
        ax.set_title(
            f'Maandelijkse Boxplot van Nachverbruik ({night_col})',
            fontsize=self.title_size,
            fontweight='bold',
        )
        ax.set_xlabel('Maand (YYYY-MM)', fontsize=self.label_size)
        ax.set_ylabel('Nachverbruik (kWh)', fontsize=self.label_size)
        ax.tick_params(axis='x', rotation=45, labelsize=self.tick_size)
        ax.tick_params(axis='y', labelsize=self.tick_size)
        
        # Add overall median line
        overall_median = df[night_col].median()
        ax.axhline(
            y=overall_median,
            color='red',
            linestyle='--',
            linewidth=1.5,
            label=f'Overall Mediaan: {overall_median:.2f} kWh',
        )
        ax.legend(fontsize=self.legend_size, loc='upper right')
        
        plt.tight_layout()
        
        if save:
            output_path = self.plots_dir / 'monthly_boxplot_night_consumption.png'
            fig.savefig(output_path, dpi=self.dpi, bbox_inches='tight')
            logger.info(f"Saved boxplot to {output_path}")
        
        if show:
            plt.show()
        else:
            plt.close(fig)
        
        return fig
    
    def plot_quantile_ribbon(
        self,
        quantiles_df: pd.DataFrame,
        quantiles: List[float] = [0.05, 0.25, 0.5, 0.75, 0.95],
        save: bool = True,
        show: bool = False,
    ) -> plt.Figure:
        """
        Create ribbon plot of quantiles over time.
        
        Args:
            quantiles_df: DataFrame with monthly quantiles (index=month, columns=quantiles)
            quantiles: List of quantile values to plot
            save: Whether to save the plot
            show: Whether to display the plot
            
        Returns:
            Matplotlib figure
        """
        fig, ax = plt.subplots(figsize=self.figsize, dpi=self.dpi)
        
        # Ensure index is datetime-like for proper ordering
        if not isinstance(quantiles_df.index, pd.DatetimeIndex):
            try:
                quantiles_df.index = pd.PeriodIndex(quantiles_df.index, freq='M').to_timestamp()
            except Exception:
                pass
        
        # Sort by index
        quantiles_df = quantiles_df.sort_index()
        
        # Get x values (months as numeric for plotting)
        x = np.arange(len(quantiles_df))
        x_labels = [idx.strftime('%Y-%m') if hasattr(idx, 'strftime') else str(idx) for idx in quantiles_df.index]
        
        # Colors for bands
        outer_alpha = 0.15
        iqr_alpha = 0.3
        
        # Outer band (0.05 - 0.95)
        if 0.05 in quantiles_df.columns and 0.95 in quantiles_df.columns:
            ax.fill_between(
                x,
                quantiles_df[0.05],
                quantiles_df[0.95],
                color=self.outer_color,
                alpha=outer_alpha,
                label='5e-95e percentiel',
            )
        
        # IQR band (0.25 - 0.75)
        if 0.25 in quantiles_df.columns and 0.75 in quantiles_df.columns:
            ax.fill_between(
                x,
                quantiles_df[0.25],
                quantiles_df[0.75],
                color=self.iqr_color,
                alpha=iqr_alpha,
                label='IQR (25e-75e percentiel)',
            )
        
        # Median line
        if 0.5 in quantiles_df.columns:
            ax.plot(
                x,
                quantiles_df[0.5],
                color=self.median_color,
                linewidth=2.5,
                label='Mediaan (50e percentiel)',
                zorder=5,
            )
        
        # Additional quantile lines
        for q in quantiles:
            if q in quantiles_df.columns and q not in [0.05, 0.25, 0.5, 0.75, 0.95]:
                ax.plot(
                    x,
                    quantiles_df[q],
                    '--',
                    alpha=0.5,
                    linewidth=1,
                    label=f'{int(q*100)}e percentiel',
                )
        
        # Formatting
        ax.set_title(
            'Maandelijkse Kwartielen van Nachverbruik (Ribbon Plot)',
            fontsize=self.title_size,
            fontweight='bold',
        )
        ax.set_xlabel('Maand', fontsize=self.label_size)
        ax.set_ylabel('Nachverbruik (kWh)', fontsize=self.label_size)
        
        # X-axis ticks
        tick_step = max(1, len(x) // 12)
        ax.set_xticks(x[::tick_step])
        ax.set_xticklabels(x_labels[::tick_step], rotation=45, fontsize=self.tick_size)
        ax.tick_params(axis='y', labelsize=self.tick_size)
        
        ax.legend(fontsize=self.legend_size, loc='upper left')
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        if save:
            output_path = self.plots_dir / 'quantile_ribbon_night_consumption.png'
            fig.savefig(output_path, dpi=self.dpi, bbox_inches='tight')
            logger.info(f"Saved ribbon plot to {output_path}")
        
        if show:
            plt.show()
        else:
            plt.close(fig)
        
        return fig
    
    def plot_quantile_ribbon_smoothed(
        self,
        quantiles_df: pd.DataFrame,
        window: int = 3,
        quantiles: List[float] = [0.05, 0.25, 0.5, 0.75, 0.95],
        save: bool = True,
        show: bool = False,
    ) -> plt.Figure:
        """
        Create ribbon plot with smoothed quantile trends.
        
        Args:
            quantiles_df: DataFrame with monthly quantiles
            window: Rolling window size in months
            quantiles: List of quantile values
            save: Whether to save
            show: Whether to show
            
        Returns:
            Matplotlib figure
        """
        # Apply rolling smoothing
        smoothed = quantiles_df.rolling(window=window, center=True, min_periods=1).mean()
        
        fig, ax = plt.subplots(figsize=self.figsize, dpi=self.dpi)
        
        x = np.arange(len(smoothed))
        x_labels = [idx.strftime('%Y-%m') if hasattr(idx, 'strftime') else str(idx) for idx in smoothed.index]
        
        outer_alpha = 0.15
        iqr_alpha = 0.3
        
        # Outer band
        if 0.05 in smoothed.columns and 0.95 in smoothed.columns:
            ax.fill_between(
                x,
                smoothed[0.05],
                smoothed[0.95],
                color=self.outer_color,
                alpha=outer_alpha,
                label=f'5e-95e percentiel (gesmoord, window={window})',
            )
        
        # IQR band
        if 0.25 in smoothed.columns and 0.75 in smoothed.columns:
            ax.fill_between(
                x,
                smoothed[0.25],
                smoothed[0.75],
                color=self.iqr_color,
                alpha=iqr_alpha,
                label=f'IQR (gesmoord, window={window})',
            )
        
        # Median
        if 0.5 in smoothed.columns:
            ax.plot(
                x,
                smoothed[0.5],
                color=self.median_color,
                linewidth=3,
                label='Mediaan (gesmoord)',
                zorder=5,
            )
        
        # Also plot raw median as thin line for reference
        if 0.5 in quantiles_df.columns:
            ax.plot(
                x,
                quantiles_df[0.5],
                color=self.median_color,
                linewidth=1,
                alpha=0.4,
                linestyle=':',
                label='Mediaan (raw)',
                zorder=3,
            )
        
        ax.set_title(
            f'Gesmoorde Maandelijkse Kwartielen van Nachverbruik (Rolling window={window} maanden)',
            fontsize=self.title_size,
            fontweight='bold',
        )
        ax.set_xlabel('Maand', fontsize=self.label_size)
        ax.set_ylabel('Nachverbruik (kWh)', fontsize=self.label_size)
        
        tick_step = max(1, len(x) // 12)
        ax.set_xticks(x[::tick_step])
        ax.set_xticklabels(x_labels[::tick_step], rotation=45, fontsize=self.tick_size)
        ax.tick_params(axis='y', labelsize=self.tick_size)
        
        ax.legend(fontsize=self.legend_size, loc='upper left')
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        if save:
            output_path = self.plots_dir / f'quantile_ribbon_smoothed_w{window}.png'
            fig.savefig(output_path, dpi=self.dpi, bbox_inches='tight')
            logger.info(f"Saved smoothed ribbon plot to {output_path}")
        
        if show:
            plt.show()
        else:
            plt.close(fig)
        
        return fig
    
    def create_interactive_ribbon(
        self,
        quantiles_df: pd.DataFrame,
        daily_df: Optional[pd.DataFrame] = None,
        night_col: str = 'night_consumption_kwh',
        quantiles: List[float] = [0.05, 0.25, 0.5, 0.75, 0.95],
        window: int = 3,
        save: bool = True,
    ) -> go.Figure:
        """
        Create interactive Plotly ribbon plot with hover tooltips.
        
        Args:
            quantiles_df: Monthly quantiles DataFrame
            daily_df: Optional daily data for hover details
            night_col: Night consumption column name
            quantiles: Quantile values
            window: Smoothing window
            save: Whether to save as HTML
            
        Returns:
            Plotly figure
        """
        # Apply smoothing
        smoothed = quantiles_df.rolling(window=window, center=True, min_periods=1).mean()
        
        # Ensure proper index
        if not isinstance(smoothed.index, pd.DatetimeIndex):
            try:
                smoothed.index = pd.PeriodIndex(smoothed.index, freq='M').to_timestamp()
            except Exception:
                pass
        
        fig = go.Figure()
        
        # X axis
        x_vals = smoothed.index
        x_labels = [d.strftime('%Y-%m') for d in x_vals]
        
        # Overall median line
        if daily_df is not None and night_col in daily_df.columns:
            overall_median = daily_df[night_col].median()
            fig.add_hline(
                y=overall_median,
                line_dash='dash',
                line_color='red',
                line_width=1.5,
                annotation_text=f'Algemene mediaan: {overall_median:.2f} kWh',
                annotation_position='top right',
            )
        
        # Outer band (0.05 - 0.95)
        if 0.05 in smoothed.columns and 0.95 in smoothed.columns:
            fig.add_trace(go.Scatter(
                x=list(x_vals) + list(x_vals[::-1]),
                y=list(smoothed[0.95]) + list(smoothed[0.05][::-1]),
                fill='toself',
                fillcolor=f'rgba(241, 143, 1, 0.15)',
                line=dict(color='rgba(255,255,255,0)'),
                hoverinfo='skip',
                showlegend=True,
                name='5e-95e percentiel (gesmoord)',
                legendgroup='outer',
            ))
        
        # IQR band (0.25 - 0.75)
        if 0.25 in smoothed.columns and 0.75 in smoothed.columns:
            fig.add_trace(go.Scatter(
                x=list(x_vals) + list(x_vals[::-1]),
                y=list(smoothed[0.75]) + list(smoothed[0.25][::-1]),
                fill='toself',
                fillcolor=f'rgba(162, 59, 114, 0.3)',
                line=dict(color='rgba(255,255,255,0)'),
                hoverinfo='skip',
                showlegend=True,
                name='IQR 25e-75e percentiel (gesmoord)',
                legendgroup='iqr',
            ))
        
        # Median line
        if 0.5 in smoothed.columns:
            fig.add_trace(go.Scatter(
                x=x_vals,
                y=smoothed[0.5],
                mode='lines',
                line=dict(color=self.median_color, width=3),
                name='Mediaan (50e percentiel, gesmoord)',
                hovertemplate='Maand: %{x|%Y-%m}<br>Mediaan nachtverbruik: %{y:.2f} kWh<extra></extra>',
            ))
        
        # Raw quantiles as thin lines for reference
        for q in quantiles:
            if q in quantiles_df.columns and q not in [0.05, 0.25, 0.5, 0.75, 0.95]:
                fig.add_trace(go.Scatter(
                    x=quantiles_df.index,
                    y=quantiles_df[q],
                    mode='lines',
                    line=dict(dash='dot', width=1, color='gray'),
                    name=f'{int(q*100)}e percentiel (raw)',
                    opacity=0.5,
                    hovertemplate=f'Maand: %{{x|%Y-%m}}<br>{int(q*100)}e perc: %{{y:.2f}} kWh<extra></extra>',
                ))
        
        # Add daily data points for hover (if provided)
        if daily_df is not None and night_col in daily_df.columns:
            # Sample daily data for hover (don't plot all points)
            sample_df = daily_df[[night_col]].copy()
            sample_df['month'] = sample_df.index.to_period('M')
            
            # Add monthly stats as hover info
            for month in sample_df['month'].unique():
                month_data = sample_df[sample_df['month'] == month][night_col]
                if len(month_data) > 0:
                    stats_text = (
                        f'Maand: {month}<br>'
                        f'Aantal dagen: {len(month_data)}<br>'
                        f'Mediaan: {month_data.median():.2f} kWh<br>'
                        f'Gemiddelde: {month_data.mean():.2f} kWh<br>'
                        f'Min: {month_data.min():.2f} kWh<br>'
                        f'Max: {month_data.max():.2f} kWh<br>'
                        f'Std: {month_data.std():.2f} kWh'
                    )
                    # Add invisible trace for hover
                    fig.add_trace(go.Scatter(
                        x=[month.to_timestamp()],
                        y=[month_data.median()],
                        mode='markers',
                        marker=dict(size=0, opacity=0),
                        hovertemplate=stats_text + '<extra></extra>',
                        showlegend=False,
                    ))
        
        # Layout
        fig.update_layout(
            title=dict(
                text='Interactieve Maandelijkse Kwartielen van Nachverbruik',
                font=dict(size=18),
                x=0.5,
            ),
            xaxis=dict(
                title='Maand',
                tickformat='%Y-%m',
                tickangle=45,
                showgrid=True,
                gridcolor='rgba(0,0,0,0.1)',
            ),
            yaxis=dict(
                title='Nachverbruik (kWh)',
                showgrid=True,
                gridcolor='rgba(0,0,0,0.1)',
            ),
            legend=dict(
                x=0.01,
                y=0.99,
                bgcolor='rgba(255,255,255,0.9)',
                bordercolor='rgba(0,0,0,0.2)',
                borderwidth=1,
            ),
            hovermode='x unified',
            template='plotly_white',
            width=1000,
            height=600,
        )
        
        if save:
            output_path = self.plots_dir / 'interactive_quantile_ribbon.html'
            fig.write_html(str(output_path))
            logger.info(f"Saved interactive plot to {output_path}")
        
        return fig
    
    def create_interactive_boxplot(
        self,
        daily_df: pd.DataFrame,
        night_col: str = 'night_consumption_kwh',
        save: bool = True,
    ) -> go.Figure:
        """Create interactive boxplot with Plotly."""
        df = daily_df.copy()
        if 'month' not in df.columns:
            df['month'] = df.index.to_period('M').astype(str)
        
        fig = go.Figure()
        
        # Add boxplot for each month
        for month in sorted(df['month'].unique()):
            month_data = df[df['month'] == month][night_col].dropna()
            if len(month_data) > 0:
                fig.add_trace(go.Box(
                    y=month_data,
                    name=month,
                    boxpoints='outliers',
                    marker_color=px.colors.sequential.Viridis[
                        hash(month) % len(px.colors.sequential.Viridis)
                    ],
                    hovertemplate=f'Maand: {month}<br>Nachtverbruik: %{{y:.2f}} kWh<extra></extra>',
                ))
        
        # Overall median line
        overall_median = df[night_col].median()
        fig.add_hline(
            y=overall_median,
            line_dash='dash',
            line_color='red',
            annotation_text=f'Algemene mediaan: {overall_median:.2f} kWh',
            annotation_position='top right',
        )
        
        fig.update_layout(
            title=dict(
                text='Interactieve Maandelijkse Boxplot van Nachverbruik',
                font=dict(size=18),
                x=0.5,
            ),
            xaxis=dict(title='Maand', tickangle=45),
            yaxis=dict(title='Nachverbruik (kWh)'),
            showlegend=False,
            template='plotly_white',
            width=1000,
            height=600,
        )
        
        if save:
            output_path = self.plots_dir / 'interactive_monthly_boxplot.html'
            fig.write_html(str(output_path))
            logger.info(f"Saved interactive boxplot to {output_path}")
        
        return fig
    
    def save_all_plots(
        self,
        daily_df: pd.DataFrame,
        quantiles_df: pd.DataFrame,
        night_col: str = 'night_consumption_kwh',
    ) -> Dict[str, Path]:
        """Generate and save all standard plots."""
        outputs = {}
        
        # Static boxplot
        fig1 = self.plot_monthly_boxplots(daily_df, night_col, save=True, show=False)
        outputs['boxplot'] = self.plots_dir / 'monthly_boxplot_night_consumption.png'
        
        # Static ribbon plot
        fig2 = self.plot_quantile_ribbon(quantiles_df, save=True, show=False)
        outputs['ribbon'] = self.plots_dir / 'quantile_ribbon_night_consumption.png'
        
        # Smoothed ribbon plot
        window = self.config.get('analysis', {}).get('smoothing_window', 3)
        fig3 = self.plot_quantile_ribbon_smoothed(quantiles_df, window=window, save=True, show=False)
        outputs['ribbon_smoothed'] = self.plots_dir / f'quantile_ribbon_smoothed_w{window}.png'
        
        # Interactive plots
        if self.plot_config.get('interactive', {}).get('enabled', True):
            fig4 = self.create_interactive_ribbon(quantiles_df, daily_df, night_col, save=True)
            outputs['interactive_ribbon'] = self.plots_dir / 'interactive_quantile_ribbon.html'
            
            fig5 = self.create_interactive_boxplot(daily_df, night_col, save=True)
            outputs['interactive_boxplot'] = self.plots_dir / 'interactive_monthly_boxplot.html'
        
        return outputs


def create_plotter(config: Optional[Dict] = None) -> Plotter:
    """Factory function to create Plotter instance."""
    return Plotter(config)