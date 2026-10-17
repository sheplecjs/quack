"""Shynet: daily web traffic stats from a self-hosted Shynet instance's dashboard API."""

from web.ingestion.shynet.config import ShynetConfig
from web.ingestion.shynet.pipeline import load_shynet
from web.ingestion.shynet.source import shynet_source

__all__ = ["ShynetConfig", "load_shynet", "shynet_source"]
