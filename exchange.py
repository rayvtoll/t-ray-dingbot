from copy import deepcopy
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
from typing import List, Tuple

from discord_client import USE_DISCORD, get_discord_table


TICKER: str = "BTC/USDT:USDT"
EXCHANGE_PRICE_PRECISION: int = config(
    "EXCHANGE_PRICE_PRECISION", cast=int, default="1"
)
BINANCE_EXCHANGE = ccxt.binance()


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
    POSITION_PERCENTAGE = config("POSITION_PERCENTAGE", cast=float, default="1.0")
    logger.info(f"{POSITION_PERCENTAGE=}")

# strategy
SL_PERCENTAGE = config("SL_PERCENTAGE", cast=float, default="1")
logger.info(f"{SL_PERCENTAGE=}")
TP_PERCENTAGE = config("TP_PERCENTAGE", cast=float, default="4")
logger.info(f"{TP_PERCENTAGE=}")
ENTRY_DAYS = config("ENTRY_DAYS", cast=Csv(int), default="0,1,2,3,4,5,6")
logger.info(f"{ENTRY_DAYS=}")
ENTRY_HOURS = config(
    "ENTRY_HOURS",
    cast=Csv(int),
    default="0,5,7,8,9,10,11,12,13,16,17,18,19,21,23",
)
logger.info(f"{ENTRY_HOURS=}")


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

    async def get_last_candle(self, now: datetime) -> Candle | None:
        """Get the last candle from Binance exchange"""

        try:
            now_minus_5m = now.replace(
                minute=now.minute - now.minute % 5, second=0, microsecond=0
            ) - timedelta(minutes=5)
            last_candles = await BINANCE_EXCHANGE.fetch_ohlcv(
                symbol=TICKER,
                timeframe="5m",
                since=int(now_minus_5m.timestamp() * 1000),
                limit=2,
            )
            candle: Candle = Candle(*last_candles[0])
            logger.info(f"{candle=}")
            return candle
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

            # calculate position size
            if USE_FIXED_RISK:
                usdt_size: float = FIXED_RISK_EX_FEES * SL_PERCENTAGE * LEVERAGE
            else:
                usdt_size: float = (
                    total_balance / (SL_PERCENTAGE * LEVERAGE)
                ) * POSITION_PERCENTAGE
            position_size: float = round(usdt_size / price * LEVERAGE * 1000, 1)

        except Exception as e:
            position_size = 0.1
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
        if not hasattr(self, "_position_size"):
            self._position_size = position_size
            logger.info(f"Initial {self._position_size=}")
            return

        # set the position sizes if they have changed
        if position_size != self._position_size:
            logger.info(f"{position_size=}")
            self._position_size = position_size

    @property
    def position_size(self) -> int:
        """Get the position size for the exchange"""

        return self._position_size

    async def handle_position_to_open(
        self, position_to_open: PositionToOpen, last_candle: Candle
    ) -> None:
        """Handle 1 position inside self.positions_to_open"""

        long_above: bool = (
            position_to_open.long_above
            and last_candle.close > position_to_open.long_above
        )
        short_below: bool = (
            position_to_open.short_below
            and last_candle.close < position_to_open.short_below
        )
        cancel_above: bool = (
            position_to_open.cancel_above
            and last_candle.close > position_to_open.cancel_above
        )
        cancel_below: bool = (
            position_to_open.cancel_below
            and last_candle.close < position_to_open.cancel_below
        )

        # should the trade be canceled due to price moving above cancel_above?
        if cancel_above or cancel_below:
            self.positions_to_open.remove(position_to_open)
            canceling_position_log_info = {
                "_id": position_to_open._id,
                "price": (
                    f"$ {round(last_candle.close, EXCHANGE_PRICE_PRECISION):,} is "
                    + (f"above" if cancel_above else "below")
                    + f" $ {round((position_to_open.cancel_above if cancel_above else position_to_open.cancel_below), EXCHANGE_PRICE_PRECISION):,}"
                ),
                "status": "canceled",
                "reason": "price moved beyond 'no order' threshold",
            }
            logger.info(f"{canceling_position_log_info=}")
            if USE_DISCORD:
                self.discord_message_queue.append(
                    DiscordMessage(
                        channel_id=DISCORD_CHANNEL_WAITING_ID,
                        messages=[get_discord_table(canceling_position_log_info)],
                    )
                )
            return

        # are conditions not met to open a position?
        if not long_above and not short_below:
            logger.info(
                f"Conditions for {position_to_open._id} not met to open position around {last_candle.close=}"
            )
            for position in self.positions_to_open:
                if position._id == position_to_open._id:
                    if not position.past_first_candle:
                        position.past_first_candle = True
            return

        # at this point, we either enter or cancel
        self.positions_to_open.remove(position_to_open)

        # skip if we have not yet passed the first candle after confirmation
        if not position_to_open.past_first_candle:
            canceling_position_log_info = {
                "_id": position_to_open._id,
                "price": (
                    f"$ {round(last_candle.close, EXCHANGE_PRICE_PRECISION):,} is "
                    + (f"above" if long_above else "below")
                    + f" $ {round((position_to_open.long_above if long_above else position_to_open.short_below), EXCHANGE_PRICE_PRECISION):,}"
                ),
                "status": "canceled",
                "reason": "need at least 2 candles after confirmation",
            }
            logger.info(f"{canceling_position_log_info=}")
            if USE_DISCORD:
                self.discord_message_queue.append(
                    DiscordMessage(
                        channel_id=DISCORD_CHANNEL_WAITING_ID,
                        messages=[get_discord_table(canceling_position_log_info)],
                    )
                )
            return

        # if outside entry days/hours, do not open position
        if (
            self.scanner.now.weekday() not in ENTRY_DAYS
            or self.scanner.now.hour not in ENTRY_HOURS
        ):
            not_entering_position_log_info = {
                "_id": position_to_open._id,
                "price": (
                    f"$ {round(last_candle.close, EXCHANGE_PRICE_PRECISION):,} is "
                    + ("above" if long_above else "below")
                    + f" $ {round(position_to_open.long_above if long_above else position_to_open.short_below, EXCHANGE_PRICE_PRECISION):,}"
                ),
                "status": "canceled",
                "reason": "outside entry days / hours",
            }
            if USE_DISCORD:
                self.discord_message_queue.append(
                    DiscordMessage(
                        channel_id=DISCORD_CHANNEL_WAITING_ID,
                        messages=[get_discord_table(not_entering_position_log_info)],
                    )
                )
            return

        # long_above or short_below conditions met, open position
        logger.info(
            f"Conditions met to open {'LONG' if long_above else 'SHORT'} "
            + f"position around {last_candle.close=}"
        )
        if USE_DISCORD:
            prive_above_or_below = (
                position_to_open.long_above
                if long_above
                else position_to_open.short_below
            )
            entering_position_log_info = {
                "_id": position_to_open._id,
                "price": (
                    f"$ {round(last_candle.close, EXCHANGE_PRICE_PRECISION):,} is "
                    + ("above" if long_above else "below")
                    + f" $ {round(prive_above_or_below, EXCHANGE_PRICE_PRECISION):,}"
                ),
                "status": "entering " + (LONG if long_above else SHORT),
            }
            self.discord_message_queue.append(
                DiscordMessage(
                    channel_id=DISCORD_CHANNEL_WAITING_ID,
                    messages=[get_discord_table(entering_position_log_info)],
                )
            )

        price, stoploss_price, takeprofit_price = await self.limit_order_placement(
            direction=LONG if long_above else SHORT,
            amount=self.position_size,
            stoploss_percentage=SL_PERCENTAGE,
            takeprofit_percentage=TP_PERCENTAGE,
        )

        if USE_DISCORD:
            await self.post_trade_to_discord(
                _id=position_to_open.liquidation._id,
                direction=LONG if long_above else SHORT,
                price=price,
                stoploss_price=stoploss_price,
                takeprofit_price=takeprofit_price,
                amount=self.position_size,
            )

    async def check_if_entry_orders_are_closed(self) -> None:
        """Check if entry limit orders are filled to place take profit limit orders"""

        # check if limit entry order is filled
        try:
            # get closed orders info
            orders_info = await self.exchange.fetch_closed_orders(
                symbol=TICKER,
                since=int((datetime.now() - timedelta(hours=24)).timestamp() * 1000),
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

        for tp_limit_order_to_place in deepcopy(self.tp_limit_orders_to_place):
            await self.handle_tp_limit_order_to_place(
                orders_info=orders_info,
                tp_limit_order_to_place=tp_limit_order_to_place,
            )

    async def handle_tp_limit_order_to_place(
        self, orders_info: dict, tp_limit_order_to_place: TPLimitOrderToPlace
    ) -> None:
        """Handle take profit limit order placement after entry order is filled"""

        # loop over closed orders to find the one matching our limit order
        for order_info in orders_info:
            if (
                str(order_info.get("id")) == str(tp_limit_order_to_place.order_id)
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

    async def handle_liquidation(
        self, liquidation: Liquidation, last_candle: Candle
    ) -> None:
        """Handle 1 liquidation inside self.liquidation_set.liquidations"""

        liquidation_datetime: datetime = datetime.fromtimestamp(
            liquidation.candle.timestamp / 1000
        )
        # check if confirmation is within 2 candles after liquidation candle
        if liquidation_datetime < (
            self.scanner.now.replace(second=0, microsecond=0) - timedelta(minutes=15)
        ):
            logger.info(f"Removing old liquidation: {liquidation._id}")
            self.liquidation_set.liquidations.remove(liquidation)
            return

        # if reaction to liquidation is strong, add it to positions to open
        if await self.reaction_to_liquidation_is_strong(liquidation, last_candle.close):
            now = self.scanner.now.replace(second=0, microsecond=0)
            candles_before_confirmation = (
                int(round((now - liquidation_datetime).total_seconds() / 300, 0)) - 1
            )
            self.liquidation_set.liquidations.remove(liquidation)

            long_above = short_below = cancel_above = cancel_below = None
            if liquidation.direction == LONG:
                short_below = round(last_candle.close * 0.995, EXCHANGE_PRICE_PRECISION)
                if candles_before_confirmation > 1:
                    cancel_above = round(
                        last_candle.close * 1.005, EXCHANGE_PRICE_PRECISION
                    )
                else:
                    long_above = round(
                        last_candle.close * 1.005, EXCHANGE_PRICE_PRECISION
                    )
            elif liquidation.direction == SHORT:
                long_above = round(last_candle.close * 1.005, EXCHANGE_PRICE_PRECISION)
                if candles_before_confirmation > 1:
                    cancel_below = round(
                        last_candle.close * 0.995, EXCHANGE_PRICE_PRECISION
                    )
                else:
                    short_below = round(
                        last_candle.close * 0.995, EXCHANGE_PRICE_PRECISION
                    )

            position_to_open = PositionToOpen(
                _id=liquidation._id,
                liquidation=liquidation,
                candles_before_confirmation=candles_before_confirmation,
                long_above=long_above,
                short_below=short_below,
                cancel_above=cancel_above,
                cancel_below=cancel_below,
                past_first_candle=False,
            )
            self.positions_to_open.append(position_to_open)
            if USE_DISCORD:
                position_to_enter_log_info = position_to_open.init_message_dict()
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

    async def run_loop(self, last_candle: Candle) -> None:
        """Run the loop for the exchange"""

        for position_to_open in deepcopy(self.positions_to_open):
            await self.handle_position_to_open(position_to_open, last_candle)

        if self.tp_limit_orders_to_place:
            await self.check_if_entry_orders_are_closed()

        # loop over detected liquidations
        for liquidation in deepcopy(self.liquidation_set.liquidations):
            await self.handle_liquidation(liquidation, last_candle)

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
