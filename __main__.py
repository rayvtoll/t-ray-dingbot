from asyncio import run, sleep
from copy import deepcopy
from datetime import datetime

from logger import logger
from misc import Candle, DiscordMessage, Liquidation, LiquidationSet
import threading
from typing import List

from coinalyze_scanner import CoinalyzeScanner, COINALYZE_LIQUIDATION_URL
from discord_client import USE_DISCORD, get_discord_table
from exchange import Exchange, TICKER, LEVERAGE


if USE_DISCORD:
    from coinalyze_scanner import (
        INTERVAL,
        N_MINUTES_TIMEDELTA,
        MINIMAL_LIQUIDATION,
        MINIMAL_NR_OF_LIQUIDATIONS,
        LIQUIDATION_DAYS,
        LIQUIDATION_HOURS,
    )
    from discord_client import post_to_discord, DISCORD_CHANNEL_HEARTBEAT_ID
    from exchange import (
        USE_FIXED_RISK,
        SL_PERCENTAGE,
        TP_PERCENTAGE,
        FORBIDDEN_NR_OF_CANDLES_BEFORE_ENTRY,
    )

    DISCORD_SETTINGS = dict(
        use_fixed_risk=USE_FIXED_RISK,
        leverage=LEVERAGE,
        n_minutes_timedelta=N_MINUTES_TIMEDELTA,
        minimal_nr_of_liquidations=MINIMAL_NR_OF_LIQUIDATIONS,
        minimal_liquidation=MINIMAL_LIQUIDATION,
        interval=INTERVAL,
        sl_percentage=SL_PERCENTAGE,
        tp_percentage=TP_PERCENTAGE,
        liquidation_days=LIQUIDATION_DAYS,
        liquidation_hours=LIQUIDATION_HOURS,
        forbidden_nr_of_candles_before_entry=FORBIDDEN_NR_OF_CANDLES_BEFORE_ENTRY,
    )

    if USE_FIXED_RISK:
        from exchange import FIXED_RISK_EX_FEES

        DISCORD_SETTINGS["fixed_risk_ex_fees"] = FIXED_RISK_EX_FEES
    else:
        from exchange import POSITION_PERCENTAGE

        DISCORD_SETTINGS["position_percentage"] = POSITION_PERCENTAGE


LIQUIDATIONS: List[Liquidation] = []
LIQUIDATION_SET: LiquidationSet = LiquidationSet(liquidations=LIQUIDATIONS)


async def main() -> None:
    first_run = True

    # enable scanner
    scanner = CoinalyzeScanner(datetime.now(), LIQUIDATION_SET)
    await scanner.set_symbols()

    # enable exchange
    exchange = Exchange(LIQUIDATION_SET, scanner)
    scanner.exchange = exchange

    for direction in ["long", "short"]:
        await exchange.set_leverage(
            symbol=TICKER,
            leverage=LEVERAGE,
            direction=direction,
        )

    # start the bot
    info = "Starting / Restarting the bot"
    logger.info(info + "...")
    logger.info(
        "BTC markets that will be scanned: %s", ", ".join(scanner.symbols.split(","))
    )
    if USE_DISCORD:
        DISCORD_SETTINGS["symbols"] = scanner.symbols.split(",")
        exchange.discord_message_queue.append(
            DiscordMessage(
                channel_id=DISCORD_CHANNEL_HEARTBEAT_ID,
                messages=[
                    f"{info} with settings:\n{get_discord_table(DISCORD_SETTINGS)}"
                ],
            )
        )

    while True:
        now = datetime.now()

        if (now.minute % 5 == 0 and now.second == 0) or first_run:

            # disable first_run if needed
            if first_run:
                first_run = False

            # update scanner time
            scanner.now = now
            last_candle: Candle | None = await exchange.get_last_candle(now)
            if last_candle:

                # run strategy for the exchange on LIQUIDATIONS list
                await exchange.run_loop(last_candle)

                # check for fresh liquidations and add to LIQUIDATIONS list
                await scanner.handle_liquidation_set(
                    last_candle,
                    await scanner.handle_coinalyze_url(COINALYZE_LIQUIDATION_URL),
                )

                # log liquidations if any
                if LIQUIDATIONS:
                    logger.info(f"{LIQUIDATIONS=}")

            await sleep(0.99)

        if now.minute % 5 == 3 and now.second == 0:

            # fetch open positions and orders from the exchange
            await exchange.get_open_positions()

            await sleep(0.99)

        if now.minute % 5 == 4 and now.second == 0:

            # recalculate position sizes based on current balance
            await exchange.set_position_sizes()

            await sleep(0.99)

        if USE_DISCORD and (now.hour % 12 == 8 and now.minute == 1 and now.second == 0):

            # send heartbeat message to discord
            exchange.discord_message_queue.append(
                DiscordMessage(channel_id=DISCORD_CHANNEL_HEARTBEAT_ID, messages=["."])
            )

            # update symbols in scanner
            await scanner.set_symbols()

            await sleep(0.99)

        if USE_DISCORD and exchange.discord_message_queue:

            # post messages to discord from the queue
            message_queue = deepcopy(exchange.discord_message_queue)
            exchange.discord_message_queue.clear()
            threading.Thread(
                target=post_to_discord,
                kwargs=dict(message_queue=message_queue),
            ).start()

            await sleep(0.99)

        await sleep(0.01)


if __name__ == "__main__":
    run(main())
