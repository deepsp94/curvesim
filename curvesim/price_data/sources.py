"""
Helper functions for the different data sources we pull from.
"""

from curvesim.logging import get_logger
from curvesim.network import coingecko as _coingecko

logger = get_logger(__name__)


def coingecko(addresses, symbols, chain="mainnet", days=60, end=None):
    """
    Fetch CoinGecko price data for specified coins.

    Parameters
    ----------
    addresses : list of str
        List of addresses to fetch data for.
    symbols : list of str
        List of symbols. May be used to fetch data if addresses are not found.
    chain : str, optional
        Blockchain network to consider. Default is "mainnet".
    days : int, optional
        Number of past days to fetch data for. Default is 60.
    end : int, optional
        End timestamp for the data in seconds since epoch.
        If None, the end time will be the current time. Default is None.

    Returns
    -------
    tuple of (dict, dict, int)
        Tuple of prices, volumes, and pzero (fixed as 0 for this function).
    """
    logger.info("Fetching CoinGecko price data...")
    prices, volumes = _coingecko.pool_prices(
        addresses, symbols, "usd", days, chain=chain, end=end
    )
    pzero = 0

    return prices, volumes, pzero
