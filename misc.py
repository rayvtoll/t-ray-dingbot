from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
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

    amount: int
    direction: str
    time: int
    nr_of_liquidations: int
    candle: Candle
    time_frame: str = "5m"  # Default time frame

    def to_dict(self) -> dict:
        """Convert the Liquidation instance to a json dumpable dictionary."""

        liquidation_dict = deepcopy(self.__dict__)
        liquidation_dict["amount"] = f"$ {round(self.amount, 2):,}"
        liquidation_dict["volume"] = self.candle.volume
        del liquidation_dict["time"]
        del liquidation_dict["candle"]
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
