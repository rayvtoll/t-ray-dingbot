import ccxt.pro as ccxt
from coinalyze_scanner import CoinalyzeScanner
from datetime import datetime, timedelta
from decouple import config, Csv
from logger import logger
from misc import (
    Candle,
    DiscordMessage,
    Liquidation,
    LiquidationSet,
    PositionToOpen,
    TPLimitOrderToPlace,
)
import requests
from typing import List, Tuple

from discord_client import USE_DISCORD, get_discord_table


TICKER: str = "BTC/USDT:USDT"
EXCHANGE_PRICE_PRECISION: int = config(
    "EXCHANGE_PRICE_PRECISION", cast=int, default="1"
)

# Strategy types
LIVE = "live"
JOURNALING = "journaling"

# Order Directions
LONG = "long"
SHORT = "short"


if USE_DISCORD:
    from discord_client import (
        USE_AT_EVERYONE,
        DISCORD_CHANNEL_TRADES_ID,
        DISCORD_CHANNEL_POSITIONS_ID,
        DISCORD_CHANNEL_HEARTBEAT_ID,
        DISCORD_CHANNEL_WAITING_ID,
    )

USE_AUTO_JOURNALING = config("USE_AUTO_JOURNALING", cast=bool, default="false")
logger.info(f"{USE_AUTO_JOURNALING=}")
if USE_AUTO_JOURNALING:
    JOURNAL_HOST_AND_PORT = config(
        "JOURNAL_HOST_AND_PORT", default="http://127.0.0.1:8000"
    )
    JOURNALING_API_KEY = config("JOURNALING_API_KEY")

# exchange settings
EXCHANGE_NAME = config("EXCHANGE_NAME", default="blofin")
EXCHANGE_API_KEY = config("EXCHANGE_API_KEY")
EXCHANGE_SECRET_KEY = config("EXCHANGE_SECRET_KEY")
EXCHANGE_PASSPHRASE = config("EXCHANGE_PASSPHRASE")
EXCHANGE_CONFIG = {
    "apiKey": EXCHANGE_API_KEY,
    "secret": EXCHANGE_SECRET_KEY,
    "password": EXCHANGE_PASSPHRASE,
}

# trade settings
LEVERAGE = config("LEVERAGE", cast=int, default="25")
logger.info(f"{LEVERAGE=}")
USE_FIXED_RISK = config("USE_FIXED_RISK", cast=bool, default=False)
logger.info(f"{USE_FIXED_RISK=}")
if USE_FIXED_RISK:
    FIXED_RISK_EX_FEES = config("FIXED_RISK_EX_FEES", cast=float, default="50.0")
    logger.info(f"{FIXED_RISK_EX_FEES=}")
else:
    POSITION_PERCENTAGE = config("POSITION_PERCENTAGE", cast=float, default="0.5")
    logger.info(f"{POSITION_PERCENTAGE=}")

# live strategy
USE_LIVE_STRATEGY = config("USE_LIVE_STRATEGY", cast=bool, default="true")
logger.info(f"{USE_LIVE_STRATEGY=}")
if USE_LIVE_STRATEGY:
    LIVE_SL_PERCENTAGE = config("LIVE_SL_PERCENTAGE", cast=float, default="1")
    logger.info(f"{LIVE_SL_PERCENTAGE=}")
    LIVE_TP_PERCENTAGE = config("LIVE_TP_PERCENTAGE", cast=float, default="4")
    logger.info(f"{LIVE_TP_PERCENTAGE=}")
    LIVE_TRADING_DAYS = config(
        "LIVE_TRADING_DAYS", cast=Csv(int), default="0,1,2,3,4,5,6"
    )
    logger.info(f"{LIVE_TRADING_DAYS=}")
    LIVE_TRADING_HOURS = config(
        "LIVE_TRADING_HOURS",
        cast=Csv(int),
        default="2,3,4,10,11,12,13,14,15,16,17,18,19",
    )
    logger.info(f"{LIVE_TRADING_HOURS=}")

# journaling strategy
USE_JOURNALING_STRATEGY = config("USE_JOURNALING_STRATEGY", cast=bool, default="true")
logger.info(f"{USE_JOURNALING_STRATEGY=}")
if USE_JOURNALING_STRATEGY:
    JOURNALING_SL_PERCENTAGE = config(
        "JOURNALING_SL_PERCENTAGE", cast=float, default="0.25"
    )
    logger.info(f"{JOURNALING_SL_PERCENTAGE=}")
    JOURNALING_TP_PERCENTAGE = config(
        "JOURNALING_TP_PERCENTAGE", cast=float, default="0.5"
    )
    logger.info(f"{JOURNALING_TP_PERCENTAGE=}")
    JOURNALING_TRADING_DAYS = config(
        "JOURNALING_TRADING_DAYS", cast=Csv(int), default="0,1,2,3,4,5,6"
    )
    logger.info(f"{JOURNALING_TRADING_DAYS=}")
    JOURNALING_TRADING_HOURS = config(
        "JOURNALING_TRADING_HOURS",
        cast=Csv(int),
        default="0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23",
    )
    logger.info(f"{JOURNALING_TRADING_HOURS=}")


class Exchange:
    """Exchange class to handle the exchange"""

    def __init__(
        self, liquidation_set: LiquidationSet, scanner: CoinalyzeScanner
    ) -> None:
        self.exchange: ccxt.Exchange = getattr(ccxt, EXCHANGE_NAME)(
            config=EXCHANGE_CONFIG
        )
        self.liquidation_set: LiquidationSet = liquidation_set
        self.tp_limit_orders_to_place: List[TPLimitOrderToPlace] = []
        self.positions_to_open: List[PositionToOpen] = []
        self.positions: List[dict] = []
        self.market_sl_orders: List[dict] = []
        self.limit_orders: List[dict] = []
        self.scanner: CoinalyzeScanner = scanner
        self.discord_message_queue: List[DiscordMessage] = []

    async def get_open_positions(self) -> List[dict]:
        """Get open positions from the exchange"""

        # get open positions info
        try:
            positions = await self.exchange.fetch_positions(symbols=[TICKER])
            open_positions = [
                {
                    "amount": f"{position.get("info", {}).get("positions")} contract(s)",
                    "direction": position.get("info", {}).get("positionSide", ""),
                    "price": f"$ {round(float(position.get("info", {}).get("averagePrice", 0.0)), EXCHANGE_PRICE_PRECISION):,}",
                    "liquidation_price": f"$ {round(float(position.get("info", {}).get("liquidationPrice", 0.0)), EXCHANGE_PRICE_PRECISION):,}",
                }
                for position in positions
            ]
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            open_positions = []
            if USE_DISCORD:
                self.discord_message_queue.append(
                    DiscordMessage(
                        channel_id=DISCORD_CHANNEL_HEARTBEAT_ID,
                        messages=[
                            "Error fetching positions from exchange:",
                            str(e),
                        ],
                    )
                )

        # get open market tpsl orders
        try:
            open_orders = await self.exchange.fetch_open_orders(params={"tpsl": True})
            market_sl_orders_info = [
                {
                    "amount": f"{order.get("info", {}).get("size")} contract(s)",
                    "direction": order.get("info", {}).get("positionSide", ""),
                    "price": (
                        f"$ {round(float(order.get("info", {}).get("slTriggerPrice", 0.0)), EXCHANGE_PRICE_PRECISION):,}"
                        if order.get("info", {}).get("slTriggerPrice")
                        else "-"
                    ),
                }
                for order in open_orders
            ]
        except Exception as e:
            logger.error(f"Error fetching open orders: {e}")
            market_sl_orders_info = []
            if USE_DISCORD:
                self.discord_message_queue.append(
                    DiscordMessage(
                        channel_id=DISCORD_CHANNEL_HEARTBEAT_ID,
                        messages=[
                            "Error fetching open orders from exchange:",
                            str(e),
                        ],
                    )
                )

        # get open limit orders
        try:
            open_orders = await self.exchange.fetch_open_orders()
            limit_orders_info = [
                {
                    "amount": f"{order.get("amount", 0.0)} contract(s)",
                    "direction": order.get("info", {}).get("side", ""),
                    "price": f"$ {round(float(order.get("info", {}).get("price", 0.0)), EXCHANGE_PRICE_PRECISION):,}",
                }
                for order in open_orders
            ]
        except Exception as e:
            logger.error(f"Error fetching open limit orders: {e}")
            limit_orders_info = []
            if USE_DISCORD:
                self.discord_message_queue.append(
                    DiscordMessage(
                        channel_id=DISCORD_CHANNEL_HEARTBEAT_ID,
                        messages=[
                            "Error fetching open limit orders from exchange:",
                            str(e),
                        ],
                    )
                )

        # only log and post to discord if there are changes
        if (
            self.positions != open_positions
            or self.market_sl_orders != market_sl_orders_info
            or self.limit_orders != limit_orders_info
        ):
            self.market_sl_orders = market_sl_orders_info
            self.limit_orders = limit_orders_info
            self.positions = open_positions
            if not any(self.market_sl_orders or self.limit_orders or self.positions):
                open_positions_and_orders = ["No open positions / orders."]
            else:
                stripes = [40 * "-"]
                open_positions_and_orders = (
                    stripes
                    + ["Position(s):"]
                    + (
                        [get_discord_table(position) for position in self.positions]
                        if self.positions
                        else ["```-```"]
                    )
                    + ["Market SL order(s):"]
                    + (
                        [get_discord_table(order) for order in self.market_sl_orders]
                        if self.market_sl_orders
                        else ["```-```"]
                    )
                    + ["Limit order(s):"]
                    + (
                        [get_discord_table(order) for order in self.limit_orders]
                        if self.limit_orders
                        else ["```-```"]
                    )
                    + stripes
                )

            logger.info(f"{open_positions_and_orders=}")
            if USE_DISCORD:
                self.discord_message_queue.append(
                    DiscordMessage(
                        channel_id=DISCORD_CHANNEL_POSITIONS_ID,
                        messages=open_positions_and_orders,
                    )
                )

    async def set_leverage(self, symbol: str, leverage: int, direction: str) -> None:
        """Set the leverage for the exchange"""

        try:
            logger.info(
                await self.exchange.set_leverage(
                    symbol=symbol,
                    leverage=leverage,
                    params={"marginMode": "isolated", "positionSide": direction},
                )
            )
        except Exception as e:
            logger.warning(f"Error settings leverage: {e}")

    async def get_last_candle(self) -> Candle | None:
        """Get the last candle for the exchange"""

        try:

            last_candles = await self.exchange.fetch_ohlcv(
                symbol=TICKER,
                timeframe="5m",
                since=None,
                limit=2,
            )
            last_candle: Candle = Candle(*last_candles[-1])
            logger.info(f"{last_candle=}")
            return last_candle
        except Exception as e:
            logger.error(f"Error fetching ohlcv: {e}")
            if USE_DISCORD:
                self.discord_message_queue.append(
                    DiscordMessage(
                        channel_id=DISCORD_CHANNEL_HEARTBEAT_ID,
                        messages=[
                            "Error fetching ohlcv from exchange:",
                            str(e),
                        ],
                    )
                )
            return None

    async def set_position_sizes(self) -> None:
        """Set the position size for the exchange"""

        try:
            # fetch balance and bid/ask
            balance: dict = await self.exchange.fetch_balance()
            total_balance: float = balance.get("USDT", {}).get("total", 1)
            price = await self.get_price()

            # calculate live position size
            if USE_LIVE_STRATEGY:
                if USE_FIXED_RISK:
                    live_usdt_size: float = (
                        FIXED_RISK_EX_FEES * LIVE_SL_PERCENTAGE * LEVERAGE
                    )
                else:
                    live_usdt_size: float = (
                        total_balance / (LIVE_SL_PERCENTAGE * LEVERAGE)
                    ) * POSITION_PERCENTAGE
                live_position_size: float = round(
                    live_usdt_size / price * LEVERAGE * 1000, 1
                )

            # journaling position size is a fixed small size for now
            journaling_position_size: float = 0.1

        except Exception as e:
            if USE_LIVE_STRATEGY:
                live_position_size = 0.1
            if USE_JOURNALING_STRATEGY:
                journaling_position_size = 0.1
            logger.error(f"Error setting position size: {e}")
            if USE_DISCORD:
                self.discord_message_queue.append(
                    DiscordMessage(
                        channel_id=DISCORD_CHANNEL_HEARTBEAT_ID,
                        messages=[
                            "Error setting position size:",
                            str(e),
                        ],
                    )
                )

        # set the position sizes if they are not set yet
        if (USE_LIVE_STRATEGY and not hasattr(self, "_live_position_size")) or (
            USE_JOURNALING_STRATEGY and not hasattr(self, "_journaling_position_size")
        ):
            if USE_LIVE_STRATEGY:
                self._live_position_size = live_position_size
            if USE_JOURNALING_STRATEGY:
                self._journaling_position_size = journaling_position_size
            logger.info(
                f"Initial "
                + (f"{self._live_position_size=} - " if USE_LIVE_STRATEGY else "")
                + (
                    f"{self._journaling_position_size=}"
                    if USE_JOURNALING_STRATEGY
                    else ""
                )
            )
            return

        # set the position sizes if they have changed
        if (USE_LIVE_STRATEGY and (live_position_size != self._live_position_size)) or (
            USE_JOURNALING_STRATEGY
            and (journaling_position_size != self._journaling_position_size)
        ):
            logger.info(
                (f"{live_position_size=} - " if USE_LIVE_STRATEGY else "")
                + (f"{journaling_position_size=} - " if USE_JOURNALING_STRATEGY else "")
            )

            if USE_LIVE_STRATEGY:
                self._live_position_size = live_position_size
            if USE_JOURNALING_STRATEGY:
                self._journaling_position_size = journaling_position_size

    @property
    def live_position_size(self) -> int:
        """Get the live position size for the exchange"""

        return self._live_position_size

    @property
    def journaling_position_size(self) -> int:
        """Get the journaling position size for the exchange"""

        return self._journaling_position_size

    async def run_loop(self) -> None:
        """Run the loop for the exchange"""

        # get price from ticker
        price = await self.get_price()

        # if price is None, skip processing
        if price is None:
            return

        for position_to_open in self.positions_to_open:

            # are conditions not met to open a position?
            if not (price > position_to_open.long_above) and not (
                price < position_to_open.short_below
            ):
                logger.info(
                    "Conditions not met to open position: "
                    + f"{price=}, {position_to_open.long_above=}, {position_to_open.short_below=}"
                )
                continue

            self.positions_to_open.remove(position_to_open)
            logger.info(
                f"Conditions met to open {'LONG' if price > position_to_open.long_above else 'SHORT'} "
                + f"position around {price=}"
            )
            if USE_DISCORD and position_to_open.strategy_type != JOURNALING:
                prive_above_or_below = (
                    position_to_open.long_above
                    if price > position_to_open.long_above
                    else position_to_open.short_below
                )
                entering_position_log_info = {
                    "_id": position_to_open._id,
                    "price": (
                        f"$ {round(price, EXCHANGE_PRICE_PRECISION):,} is "
                        + ("above" if price > position_to_open.long_above else "below")
                        + f" $ {round(prive_above_or_below, EXCHANGE_PRICE_PRECISION):,}"
                    ),
                    "entering": (
                        "long" if price > position_to_open.long_above else "short"
                    ),
                }
                if USE_DISCORD:
                    self.discord_message_queue.append(
                        DiscordMessage(
                            channel_id=DISCORD_CHANNEL_WAITING_ID,
                            messages=[get_discord_table(entering_position_log_info)],
                        )
                    )

            await self.apply_strategy(
                strategy_type=position_to_open.strategy_type,
                liquidation=position_to_open.liquidation,
                direction=LONG if price > position_to_open.long_above else SHORT,
            )

        if self.tp_limit_orders_to_place:

            # check if limit order is filled
            try:
                # get closed orders info
                orders_info = await self.exchange.fetch_closed_orders(
                    symbol=TICKER,
                    since=int(
                        (datetime.now() - timedelta(hours=12)).timestamp() * 1000
                    ),
                    limit=100,
                )
            except Exception as e:
                orders_info = []
                logger.error(f"Error fetching order info: {e}")
                if USE_DISCORD:
                    self.discord_message_queue.append(
                        DiscordMessage(
                            channel_id=DISCORD_CHANNEL_HEARTBEAT_ID,
                            messages=[
                                "Error fetching closed order info from exchange:",
                                str(e),
                            ],
                        )
                    )

            for tp_limit_order_to_place in self.tp_limit_orders_to_place:

                # loop over closed orders to find the one matching our limit order
                for order_info in orders_info:
                    if (
                        str(order_info.get("id"))
                        == str(tp_limit_order_to_place.order_id)
                        and order_info.get("info", {}).get("state") == "filled"
                    ):
                        logger.info(f"Limit order filled, time to add take profit")
                        self.tp_limit_orders_to_place.remove(tp_limit_order_to_place)

                        # add take profit limit order
                        try:
                            await self.exchange.create_order(
                                symbol=TICKER,
                                type="limit",
                                side=(
                                    "buy"
                                    if tp_limit_order_to_place.direction == SHORT
                                    else "sell"
                                ),
                                amount=tp_limit_order_to_place.amount,
                                price=tp_limit_order_to_place.takeprofit_price,
                                params=dict(
                                    marginMode="isolated",
                                    positionSide=tp_limit_order_to_place.direction,
                                    reduceOnly=True,
                                ),
                            )
                        except Exception as e:
                            logger.error(f"Error placing take profit order: {e}")
                            if USE_DISCORD:
                                self.discord_message_queue.append(
                                    DiscordMessage(
                                        channel_id=DISCORD_CHANNEL_HEARTBEAT_ID,
                                        messages=[
                                            "Error placing take profit order:",
                                            str(e),
                                        ],
                                    )
                                )

        # loop over detected liquidations
        for liquidation in self.liquidation_set.liquidations:

            # if reaction to liquidation is strong, add it to positions to open
            if await self.reaction_to_liquidation_is_strong(liquidation, price):
                liquidation_datetime = self.scanner.now.replace(
                    second=0, microsecond=0
                ) - timedelta(minutes=10)
                if USE_LIVE_STRATEGY and (
                    liquidation_datetime.weekday() in LIVE_TRADING_DAYS
                    and liquidation_datetime.hour in LIVE_TRADING_HOURS
                ):
                    strategy_type = LIVE
                elif USE_JOURNALING_STRATEGY and (
                    liquidation_datetime.weekday() in JOURNALING_TRADING_DAYS
                    and liquidation_datetime.hour in JOURNALING_TRADING_HOURS
                ):
                    strategy_type = JOURNALING
                else:
                    logger.info(
                        "Outside trading hours/days, not adding position to open."
                    )
                    continue
                long_above = round(price * 1.005, EXCHANGE_PRICE_PRECISION)
                short_below = round(price * 0.995, EXCHANGE_PRICE_PRECISION)
                self.positions_to_open.append(
                    PositionToOpen(
                        _id=liquidation._id,
                        strategy_type=strategy_type,
                        liquidation=liquidation,
                        long_above=long_above,
                        short_below=short_below,
                    )
                )
                if USE_DISCORD and strategy_type != JOURNALING:
                    position_to_enter_log_info = {
                        "_id": liquidation._id,
                        "long above": f"$ {long_above:,}",
                        "short below": f"$ {short_below:,}",
                    }
                    logger.info(f"{position_to_enter_log_info=}")
                    self.discord_message_queue.append(
                        DiscordMessage(
                            channel_id=DISCORD_CHANNEL_WAITING_ID,
                            messages=[
                                get_discord_table(position_to_enter_log_info),
                            ],
                            at_everyone=USE_AT_EVERYONE,
                        )
                    )
        self.liquidation_set.liquidations.clear()

    async def reaction_to_liquidation_is_strong(
        self, liquidation: Liquidation, price: float
    ) -> bool:
        """Check if the reaction to the liquidation is strong enough to place an
        order"""

        if (liquidation.direction == LONG and price > liquidation.candle.high) or (
            liquidation.direction == SHORT and price < liquidation.candle.low
        ):
            return True
        return False

    async def apply_strategy(
        self,
        strategy_type: str,
        liquidation: Liquidation,
        direction: str,
    ) -> bool:
        """Apply the strategy during trading hours and days"""

        if USE_LIVE_STRATEGY and strategy_type == LIVE:
            amount = self.live_position_size
            strategy_type = LIVE
            stoploss_percentage = LIVE_SL_PERCENTAGE
            takeprofit_percentage = LIVE_TP_PERCENTAGE
            post_to_discord = True
        elif USE_JOURNALING_STRATEGY and strategy_type == JOURNALING:
            amount = self.journaling_position_size
            strategy_type = JOURNALING
            stoploss_percentage = JOURNALING_SL_PERCENTAGE
            takeprofit_percentage = JOURNALING_TP_PERCENTAGE
            post_to_discord = False
        else:
            logger.info("Outside trading hours/days, not applying strategy.")
            return False

        price, stoploss_price, takeprofit_price = await self.limit_order_placement(
            direction=direction,
            amount=amount,
            stoploss_percentage=stoploss_percentage,
            takeprofit_percentage=takeprofit_percentage,
        )

        if USE_AUTO_JOURNALING:
            await self.log_to_backend(
                direction=direction,
                liquidation=liquidation,
                price=price,
                stoploss_price=stoploss_price,
                takeprofit_price=takeprofit_price,
                amount=round(amount / 1000, 4),
                strategy_type=strategy_type,
            )

        if USE_DISCORD and post_to_discord:
            await self.post_trade_to_discord(
                _id=liquidation._id,
                direction=direction,
                price=price,
                stoploss_price=stoploss_price,
                takeprofit_price=takeprofit_price,
                amount=amount,
            )

        return True

    async def get_sl_and_tp_price(
        self,
        direction: str,
        price: float,
        stoploss_percentage: float,
        takeprofit_percentage: float,
    ) -> tuple[float, float]:
        """Calculate stop loss and take profit prices based on the liquidation
        direction"""

        stoploss_price = (
            round(price * (1 - (stoploss_percentage / 100)), EXCHANGE_PRICE_PRECISION)
            if direction == LONG
            else round(
                price * (1 + (stoploss_percentage / 100)), EXCHANGE_PRICE_PRECISION
            )
        )
        takeprofit_price = (
            round(price * (1 + (takeprofit_percentage / 100)), EXCHANGE_PRICE_PRECISION)
            if direction == LONG
            else round(
                price * (1 - (takeprofit_percentage / 100)), EXCHANGE_PRICE_PRECISION
            )
        )
        return stoploss_price, takeprofit_price

    async def get_price(self) -> float | None:
        """Get the current price from the exchange ticker"""

        try:
            ticker_data = await self.exchange.fetch_ticker(symbol=TICKER)
            return ticker_data["last"]
        except Exception as e:
            logger.error(f"Error fetching ticker: {e}")
            if USE_DISCORD:
                self.discord_message_queue.append(
                    DiscordMessage(
                        channel_id=DISCORD_CHANNEL_HEARTBEAT_ID,
                        messages=[
                            "Error fetching ticker from exchange:",
                            str(e),
                        ],
                    )
                )
            return None

    async def limit_order_placement(
        self,
        direction: str,
        amount: float,
        stoploss_percentage: float,
        takeprofit_percentage: float,
    ) -> Tuple[float, float, float]:
        """Process the order placement for the strategy using a market order

        Returns:
            Tuple[float, float, float]: The price, stoploss price, and takeprofit price
        """

        logger.info(f"Placing {direction} order")
        order = None

        try:
            price = await self.get_price()
            price = (
                round(price * 1.0001, EXCHANGE_PRICE_PRECISION)
                if direction == SHORT
                else round(price * 0.9999, EXCHANGE_PRICE_PRECISION)
            )
            stoploss_price, takeprofit_price = await self.get_sl_and_tp_price(
                direction, price, stoploss_percentage, takeprofit_percentage
            )
            order: dict = await self.exchange.create_order(
                symbol=TICKER,
                type="limit",
                side="buy" if direction == LONG else "sell",
                amount=amount,
                price=price,
                params=dict(
                    marginMode="isolated",
                    positionSide=direction,
                    stopLoss=dict(reduceOnly=True, triggerPrice=stoploss_price),
                ),
            )

            # add to tp limit orders to place list
            self.tp_limit_orders_to_place.append(
                TPLimitOrderToPlace(
                    order_id=str(order.get("id")),
                    direction=direction,
                    amount=amount,
                    takeprofit_price=takeprofit_price,
                )
            )
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            if USE_DISCORD:
                self.discord_message_queue.append(
                    DiscordMessage(
                        channel_id=DISCORD_CHANNEL_HEARTBEAT_ID,
                        messages=[
                            "Error placing order:",
                            str(e),
                        ],
                    )
                )
        return price, stoploss_price, takeprofit_price

    async def post_trade_to_discord(
        self,
        _id: str,
        direction: str,
        price: float,
        stoploss_price: float,
        takeprofit_price: float,
        amount: float,
    ) -> None:
        """Post the order details to discord"""
        try:
            order_log_info = dict(
                _id=_id,
                amount=f"{amount} contract(s)",
                direction=direction,
                price=f"$ {round(price, EXCHANGE_PRICE_PRECISION):,}",
                stop_loss=f"$ {round(stoploss_price, EXCHANGE_PRICE_PRECISION):,}",
                take_profit=f"$ {round(takeprofit_price, EXCHANGE_PRICE_PRECISION):,}",
            )
            logger.info(f"{order_log_info=}")
            if USE_DISCORD:
                self.discord_message_queue.append(
                    DiscordMessage(
                        channel_id=DISCORD_CHANNEL_TRADES_ID,
                        messages=[
                            f"{get_discord_table(order_log_info)}",
                        ],
                        at_everyone=USE_AT_EVERYONE,
                    )
                )
        except Exception as e:
            logger.error(f"Error posting order to discord: {e}")
            if USE_DISCORD:
                self.discord_message_queue.append(
                    DiscordMessage(
                        channel_id=DISCORD_CHANNEL_HEARTBEAT_ID,
                        messages=[
                            "Error logging order:",
                            str(e),
                        ],
                    )
                )

    async def log_to_backend(
        self,
        direction: str,
        liquidation: Liquidation,
        price: float,
        stoploss_price: float,
        takeprofit_price: float,
        amount: float,
        strategy_type: str,
    ) -> None:
        """Log the order details to the backend"""

        try:
            response = None
            try:
                data = dict(
                    start=f"{self.scanner.now.replace(second=0, microsecond=0)}",
                    entry_price=price,
                    candles_before_entry=1,
                    side=direction.upper(),
                    amount=amount,
                    take_profit_price=takeprofit_price,
                    stop_loss_price=stoploss_price,
                    liquidation_amount=int(
                        self.liquidation_set.total_amount(liquidation.direction)
                    ),
                    strategy_type=strategy_type,
                    nr_of_liquidations=liquidation.nr_of_liquidations,
                )
                response = requests.post(
                    f"{JOURNAL_HOST_AND_PORT}/api/positions/",
                    headers={"Authorization": f"Api-Key {JOURNALING_API_KEY}"},
                    data=data,
                )
                response.raise_for_status()
                logger.info(f"Position journaled: {response.json()}")
            except Exception as e:
                logger.error(
                    f"Error journaling position 1/2: {response.content if response else 'No response'}"
                )
                logger.error(f"Error journaling position 2/2: {e}")
                if USE_DISCORD:
                    self.discord_message_queue.append(
                        DiscordMessage(
                            channel_id=DISCORD_CHANNEL_HEARTBEAT_ID,
                            messages=[
                                "Error journaling position:",
                                str(e),
                            ],
                        )
                    )

        except Exception as e:
            logger.error(f"Error logging order: {e}")
            if USE_DISCORD:
                self.discord_message_queue.append(
                    DiscordMessage(
                        channel_id=DISCORD_CHANNEL_HEARTBEAT_ID,
                        messages=[
                            "Error logging order to backend:",
                            str(e),
                        ],
                    )
                )
