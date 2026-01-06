from datetime import datetime, timedelta
from decouple import config, Csv
from functools import cached_property

from discord_client import USE_DISCORD

if USE_DISCORD:
    from discord_client import (
        get_discord_table,
        DISCORD_CHANNEL_LIQUIDATIONS_ID,
        DISCORD_CHANNEL_HEARTBEAT_ID,
    )
from logger import logger
from misc import Candle, DiscordMessage, Liquidation, LiquidationSet
import requests
from typing import List


COINALYZE_SECRET_API_KEY = config("COINALYZE_SECRET_API_KEY")
COINALYZE_LIQUIDATION_URL = "https://api.coinalyze.net/v1/liquidation-history"
FUTURE_MARKETS_URL = "https://api.coinalyze.net/v1/future-markets"

MINIMAL_NR_OF_LIQUIDATIONS = config("MINIMAL_NR_OF_LIQUIDATIONS", default="1", cast=int)
logger.info(f"{MINIMAL_NR_OF_LIQUIDATIONS=}")
MINIMAL_LIQUIDATION = config("MINIMAL_LIQUIDATION", default="2000", cast=int)
logger.info(f"{MINIMAL_LIQUIDATION=}")
N_MINUTES_TIMEDELTA = config("N_MINUTES_TIMEDELTA", default="5", cast=int)
logger.info(f"{N_MINUTES_TIMEDELTA=}")
INTERVAL = config("INTERVAL", default="5min")
logger.info(f"{INTERVAL=}")
LIQUIDATION_DAYS = config("LIQUIDATION_DAYS", cast=Csv(int), default="0,1,2,3,4")
logger.info(f"{LIQUIDATION_DAYS=}")
LIQUIDATION_HOURS = config(
    "LIQUIDATION_HOURS",
    cast=Csv(int),
    default="2,3,4,5,15,16,17,18",
)
logger.info(f"{LIQUIDATION_HOURS=}")


class CoinalyzeScanner:
    """Scans coinalyze to notify for changes in open interest and liquidations through
    text to speech"""

    def __init__(self, now: datetime, liquidation_set: LiquidationSet) -> None:
        self.now = now
        self.liquidation_set = liquidation_set
        self.exchange = None

    @property
    def params(self) -> dict:
        """Returns the parameters for the request to the API"""
        rounded_now: datetime = self.now.replace(second=0, microsecond=0)
        return {
            "symbols": self.symbols,
            "from": int(
                datetime.timestamp(rounded_now - timedelta(minutes=N_MINUTES_TIMEDELTA))
            ),
            "to": int(datetime.timestamp(rounded_now)),
            "interval": INTERVAL,
        }

    @cached_property
    def symbols(self) -> str:
        """Returns the symbols for the request to the API"""
        return self._symbols

    async def set_symbols(self) -> None:
        """Returns the symbols for the request to the API"""
        symbols = []
        if hasattr(self, "_symbols"):
            symbols = self._symbols.split(",")
        for market in await self.handle_coinalyze_url(
            url=FUTURE_MARKETS_URL, include_params=False, symbols=True
        ):
            if (symbol := market.get("symbol", "").upper()).startswith("BTCUSD"):
                symbols.append(symbol)
        self._symbols = ",".join(list(set(symbols)))

    async def handle_liquidation_set(self, candle: Candle, symbols: list) -> None:
        """Handle the liquidation set and check for liquidations

        Args:
            history (dict): history of the liquidation
        """

        total_long, total_short = 0, 0
        l_time = symbols[0].get("t") if len(symbols) else 0
        nr_of_liquidations = 0
        for history in symbols:
            long = history.get("l")
            total_long += long
            if long > 100:
                nr_of_liquidations += 1
            short = history.get("s")
            total_short += short
            if short > 100:
                nr_of_liquidations += 1

        discord_liquidations: List[Liquidation] = []
        if (
            total_long > MINIMAL_LIQUIDATION
            and nr_of_liquidations >= MINIMAL_NR_OF_LIQUIDATIONS
        ):
            long_liquidation = Liquidation(
                _id=str(
                    "l-"
                    + datetime.fromtimestamp(candle.timestamp / 1000).strftime("%H%M")
                ),
                amount=total_long,
                direction="long",
                time=l_time,
                nr_of_liquidations=nr_of_liquidations,
                candle=candle,
                on_liquidation_days=(
                    datetime.fromtimestamp(candle.timestamp / 1000).weekday()
                    in LIQUIDATION_DAYS
                ),
                during_liquidation_hours=(
                    datetime.fromtimestamp(candle.timestamp / 1000).hour
                    in LIQUIDATION_HOURS
                ),
            )
            if (
                long_liquidation.on_liquidation_days
                and long_liquidation.during_liquidation_hours
            ):
                self.liquidation_set.liquidations.insert(0, long_liquidation)
            discord_liquidations.append(long_liquidation)
        if (
            total_short > MINIMAL_LIQUIDATION
            and nr_of_liquidations >= MINIMAL_NR_OF_LIQUIDATIONS
        ):
            short_liquidation = Liquidation(
                _id=str(
                    "s-"
                    + datetime.fromtimestamp(candle.timestamp / 1000).strftime("%H%M")
                ),
                amount=total_short,
                direction="short",
                time=l_time,
                nr_of_liquidations=nr_of_liquidations,
                candle=candle,
                on_liquidation_days=(
                    datetime.fromtimestamp(candle.timestamp / 1000).weekday()
                    in LIQUIDATION_DAYS
                ),
                during_liquidation_hours=(
                    datetime.fromtimestamp(candle.timestamp / 1000).hour
                    in LIQUIDATION_HOURS
                ),
            )
            if (
                short_liquidation.on_liquidation_days
                and short_liquidation.during_liquidation_hours
            ):
                self.liquidation_set.liquidations.insert(0, short_liquidation)
            discord_liquidations.append(short_liquidation)
        if USE_DISCORD and discord_liquidations:
            self.exchange.discord_message_queue.append(
                DiscordMessage(
                    channel_id=DISCORD_CHANNEL_LIQUIDATIONS_ID,
                    messages=[
                        get_discord_table(liquidation.to_dict())
                        for liquidation in discord_liquidations
                    ],
                )
            )

    async def handle_coinalyze_url(
        self, url: str, include_params: bool = True, symbols: bool = False
    ) -> List[dict]:
        """Handle the url and check for liquidations

        Args:
            url (str): url to check for liquidations
        """
        try:
            response = requests.get(
                url,
                headers={"api_key": COINALYZE_SECRET_API_KEY},
                params=self.params if include_params else {},
            )
            response.raise_for_status()
            response_json = response.json()
            if response_json and not symbols:
                logger.info(f"COINALYZE: {response_json}")
        except Exception as e:
            logger.error(str(e))
            if USE_DISCORD:
                self.exchange.discord_message_queue.append(
                    DiscordMessage(
                        channel_id=DISCORD_CHANNEL_HEARTBEAT_ID,
                        messages=[
                            "Error fetching liquidations from Coinalyze:",
                            str(e),
                        ],
                    )
                )
            return []

        if not len(response_json):
            return []

        if symbols:
            return response_json

        return [
            symbol.get("history")[0]
            for symbol in response_json
            if symbol.get("history")
        ]
