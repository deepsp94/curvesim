from numpy import array, isnan
from scipy.optimize import least_squares, root_scalar

from curvesim import utils
from curvesim.logging import get_logger
from curvesim.pipelines.templates.trader import Trader

logger = get_logger(__name__)


class VolumeLimitedArbitrageur(Trader):
    """
    Computes, executes, and reports out arbitrage trades.
    """

    def compute_trades(self, prices, volume_limits):
        """
        Computes trades to optimally arbitrage the pool, constrained by volume limits.

        Parameters
        ----------
        prices : pandas.Series
            Current market prices from the price_sampler.

        volume_limits : pandas.Series
            Current volume limits.

        Returns
        -------
        trades : list of tuples
            List of trades to perform.
            Trades are formatted as (coin_in, coin_out, trade_size).

        errors : numpy.ndarray
            Post-trade price error between pool price and market price.

        res : scipy.optimize.OptimizeResult
            Results object from the numerical optimizer.

        """
        trades, errors, res = multipair_optimal_arbitrage(
            self.pool, prices, volume_limits
        )
        return trades, errors, res


def multipair_optimal_arbitrage(pool, prices, limits):  # noqa: C901
    """
    Computes trades to optimally arbitrage the pool, constrained by volume limits.

    Parameters
    ----------
    pool :
        Simulation interface to a subclass of :class:`Pool`.

    prices : pandas.Series
        Current market prices from the price_sampler

    volume_limits : pandas.Series
        Current volume limits

    Returns
    -------
    trades : list of tuples
        List of trades to perform.
        Trades are formatted as (coin_i, coin_j, trade_size)

    errors : numpy.ndarray
        Post-trade price error between pool price and market price for each token pair.

    res : scipy.optimize.OptimizeResult
        Results object from the numerical optimizer.

    """
    init_trades = get_arb_trades(pool, prices)

    # Limit trade size, add size bounds
    limited_init_trades = []
    for t, limit in zip(init_trades, limits):
        size, pair, price_target = t
        i, j = pair
        limit = int(limit * 10**18)
        t = min(size, limit), pair, price_target, 0, limit + 1
        limited_init_trades.append(t)

    # Order trades in terms of expected size
    limited_init_trades = sorted(limited_init_trades, reverse=True, key=lambda t: t[0])
    sizes, coins, price_targets, lo, hi = zip(*limited_init_trades)

    def post_trade_price_error_multi(dxs, price_targets, coins):
        with pool.use_snapshot_context():
            for k, pair in enumerate(coins):
                i, j = pair

                if isnan(dxs[k]):
                    dx = 0
                else:
                    dx = int(dxs[k])

                if dx > 0:
                    pool.trade(i, j, dx)

            errors = []
            for k, pair in enumerate(coins):
                i, j = pair
                price = pool.price(i, j, use_fee=True)
                errors.append(price - price_targets[k])

        return errors

    # Find trades that minimize difference between
    # pool price and external market price
    trades = []
    try:
        res = least_squares(
            post_trade_price_error_multi,
            x0=sizes,
            args=(price_targets, coins),
            bounds=(lo, hi),
            gtol=10**-15,
            xtol=10**-15,
        )

        # Format trades into tuples, ignore if dx=0
        dxs = res.x

        for k, dx in enumerate(dxs):
            if isnan(dx):
                continue

            dx = int(dx)
            if dx > 0:
                i = coins[k][0]
                j = coins[k][1]
                trades.append((i, j, dx))

        errors = res.fun

    except Exception:
        logger.error(
            f"Optarbs args: x0: {sizes}, lo: {lo}, hi: {hi}, prices: {price_targets}",
            exc_info=True,
        )
        errors = array(
            post_trade_price_error_multi([0] * len(sizes), price_targets, coins)
        )
        res = []

    return trades, errors, res


def get_arb_trades(pool, prices):
    """
    Returns triples of "trades", one for each coin pair in `combo`.

    Each trade is a triple consisting of size, ordered coin-pair,
    and price target to move the pool price to.

    Parameters
    ----------
    pool: SimPool
        Pool to arbitrage on

    error_function: callable
        Error function that returns the difference between pool price and
        market price (p) after some trade (coin_i, coin_j, trade_size)

    prices : iterable
        External market prices for each coin-pair

    combos : iterable of tuples
        Ordered pairwise combinations of coin indices

    Returns
    -------
    trades: List[Tuple]
        List of triples (size, coins, price_target)
        "size": trade size
        "coins": in token, out token
        "price_target": price target for arbing the token pair
    """
    index_combos = utils.get_pairs(pool.number_of_coins)

    def post_trade_price_error(dx, i, j, price_target):
        with pool.use_snapshot_context():
            if dx > 0:
                pool.trade(i, j, dx)
            price = pool.price(i, j, use_fee=True)

        return price - price_target

    trades = []

    for k, pair in enumerate(index_combos):
        i, j = pair

        if pool.price(i, j) - prices[k] > 0:
            price = prices[k]
            in_index = i
            out_index = j
        elif pool.price(j, i) - 1 / prices[k] > 0:
            price = 1 / prices[k]
            in_index = j
            out_index = i
        else:
            trades.append((0, (i, j), prices[k]))
            continue

        high = pool.get_in_amount(in_index, out_index, out_balance_perc=0.01)
        bounds = (0, high)
        try:
            res = root_scalar(
                post_trade_price_error,
                args=(in_index, out_index, price),
                bracket=bounds,
                method="brentq",
            )
            size = int(res.root)
        except ValueError:
            pool_price = pool.price(in_index, out_index)
            logger.error(
                f"Opt_arb error: Pair: {(in_index, out_index)}, Pool price: {pool_price},"
                f"Target Price: {price}, Diff: {pool_price - price}"
            )
            size = 0

        trades.append((size, (in_index, out_index), price))

    return trades