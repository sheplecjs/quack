"""Alpha Vantage: daily prices, company fundamentals and US economic indicators."""

from financial.ingestion.alpha_vantage.config import AlphaVantageConfig
from financial.ingestion.alpha_vantage.pipeline import load_alpha_vantage
from financial.ingestion.alpha_vantage.source import alpha_vantage_source

__all__ = ["AlphaVantageConfig", "alpha_vantage_source", "load_alpha_vantage"]
