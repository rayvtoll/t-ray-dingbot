from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List
from logger import logger


@dataclass
class Candle:
    """Candle class to hold the candle data"""

    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    time_frame: str = "5m"  # Default time frame


@dataclass
class Liquidation:
    """Liquidation class to hold the liquidation data"""

    _id: str
    amount: int
    direction: str
    time: int
    nr_of_liquidations: int
    candle: Candle
    on_liquidation_days: bool
    during_liquidation_hours: bool
    time_frame: str = "5m"  # Default time frame

    def to_dict(self) -> dict:
        """Convert the Liquidation instance to a json dumpable dictionary."""

        liquidation_dict = deepcopy(self.__dict__)
        liquidation_dict["amount"] = f"$ {round(self.amount, 2):,}"
        del liquidation_dict["time"]
        del liquidation_dict["candle"]
        del liquidation_dict["time_frame"]
        del liquidation_dict["nr_of_liquidations"]
        return liquidation_dict


@dataclass
class LiquidationSet:
    """LiquidationSet class to hold a set of liquidations"""

    liquidations: list[Liquidation]

    def total_liquidations(self, direction: str) -> int:
        """Return the total number of liquidations in the set for a given direction."""

        return sum(
            liquidation.nr_of_liquidations
            for liquidation in self.liquidations
            if liquidation.direction == direction
        )

    def total_amount(self, direction: str) -> int:
        """Return the total amount of liquidations in the set for a given direction."""

        return sum(
            liquidation.amount
            for liquidation in self.liquidations
            if liquidation.direction == direction
        )

    def to_dict(self) -> dict:
        """Convert the LiquidationSet instance to a json dumpable dictionary."""

        return dict(
            liquidations=[liquidation.to_dict() for liquidation in self.liquidations]
        )

    def remove_old_liquidations(self, now: datetime) -> None:
        """Remove liquidations older than 10 minutes (5m + beginning of candle = 10)."""

        try:
            for liquidation in self.liquidations:
                now_rounded = now.replace(second=0, microsecond=0)
                if liquidation.time < (now_rounded - timedelta(minutes=10)).timestamp():
                    self.liquidations.remove(liquidation)
        except Exception as e:
            logger.error(f"Error removing old liquidations: {e}")
            self.liquidations = []


@dataclass
class PositionToOpen:
    """PositionToOpen class to hold the position to open data"""

    _id: str
    liquidation: Liquidation
    candles_before_confirmation: int
    long_above: float | None
    cancel_above: float | None
    short_below: float | None
    cancel_below: float | None

    def init_message_dict(self) -> dict:
        """Initialize the message dictionary for the position to open."""

        message_dict = dict(_id=self._id)
        message_dict["candles before confirmation"] = self.candles_before_confirmation
        if self.long_above:
            message_dict["long above"] = f"$ {self.long_above:,}"
        if self.cancel_above:
            message_dict["no order above"] = f"$ {self.cancel_above:,}"
        if self.short_below:
            message_dict["short below"] = f"$ {self.short_below:,}"
        if self.cancel_below:
            message_dict["no order below"] = f"$ {self.cancel_below:,}"
        return message_dict


@dataclass
class DiscordMessage:
    """DiscordMessage class to hold the discord message data"""

    channel_id: str
    messages: List[str]
    at_everyone: bool = False


@dataclass
class TPLimitOrderToPlace:
    """TPLimitOrderToPlace class to hold the take profit limit order data"""

    order_id: str
    direction: str
    amount: float
    takeprofit_price: float
