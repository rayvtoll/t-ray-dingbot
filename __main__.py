from asyncio import run, sleep
from copy import deepcopy
from datetime import datetime, timedelta
from logger import logger
from misc import Liquidation, LiquidationSet
import threading
from typing import List

from coinalyze_scanner import CoinalyzeScanner, COINALYZE_LIQUIDATION_URL
from discord_client import USE_DISCORD, get_discord_table
from exchange import Exchange, TICKER, LEVERAGE


if USE_DISCORD:
    from coinalyze_scanner import INTERVAL, N_MINUTES_TIMEDELTA
    from discord_client import post_to_discord, DISCORD_CHANNEL_HEARTBEAT_ID
    from exchange import (
        POSITION_PERCENTAGE,
        USE_LIVE_STRATEGY,
        LIVE_SL_PERCENTAGE,
        LIVE_TP_PERCENTAGE,
        LIVE_TRADING_DAYS,
        LIVE_TRADING_HOURS,
        USE_REVERSED_STRATEGY,
        REVERSED_SL_PERCENTAGE,
        REVERSED_TP_PERCENTAGE,
        REVERSED_TRADING_DAYS,
        REVERSED_TRADING_HOURS,
        USE_GREY_STRATEGY,
        GREY_SL_PERCENTAGE,
        GREY_TP_PERCENTAGE,
        GREY_TRADING_DAYS,
        GREY_TRADING_HOURS,
        USE_JOURNALING_STRATEGY,
        JOURNALING_SL_PERCENTAGE,
        JOURNALING_TP_PERCENTAGE,
        JOURNALING_TRADING_DAYS,
        JOURNALING_TRADING_HOURS,
    )
    from misc import MINIMAL_NR_OF_LIQUIDATIONS, MINIMAL_LIQUIDATION

    DISCORD_SETTINGS = dict(
        leverage=LEVERAGE,
        position_percentage=POSITION_PERCENTAGE,
        n_minutes_timedelta=N_MINUTES_TIMEDELTA,
        minimal_nr_of_liquidations=MINIMAL_NR_OF_LIQUIDATIONS,
        minimal_liquidation=MINIMAL_LIQUIDATION,
        interval=INTERVAL,
    )
    if USE_LIVE_STRATEGY:
        DISCORD_SETTINGS["live_sl_percentage"] = LIVE_SL_PERCENTAGE
        DISCORD_SETTINGS["live_tp_percentage"] = LIVE_TP_PERCENTAGE
        DISCORD_SETTINGS["live_trading_days"] = LIVE_TRADING_DAYS
        DISCORD_SETTINGS["live_trading_hours"] = LIVE_TRADING_HOURS

    if USE_REVERSED_STRATEGY:
        DISCORD_SETTINGS["reversed_sl_percentage"] = REVERSED_SL_PERCENTAGE
        DISCORD_SETTINGS["reversed_tp_percentage"] = REVERSED_TP_PERCENTAGE
        DISCORD_SETTINGS["reversed_trading_days"] = REVERSED_TRADING_DAYS
        DISCORD_SETTINGS["reversed_trading_hours"] = REVERSED_TRADING_HOURS

    if USE_JOURNALING_STRATEGY:
        DISCORD_SETTINGS["journaling_sl_percentage"] = JOURNALING_SL_PERCENTAGE
        DISCORD_SETTINGS["journaling_tp_percentage"] = JOURNALING_TP_PERCENTAGE
        DISCORD_SETTINGS["journaling_trading_days"] = JOURNALING_TRADING_DAYS
        DISCORD_SETTINGS["journaling_trading_hours"] = JOURNALING_TRADING_HOURS
    
    if USE_GREY_STRATEGY:
        DISCORD_SETTINGS["grey_sl_percentage"] = GREY_SL_PERCENTAGE
        DISCORD_SETTINGS["grey_tp_percentage"] = GREY_TP_PERCENTAGE
        DISCORD_SETTINGS["grey_trading_days"] = GREY_TRADING_DAYS
        DISCORD_SETTINGS["grey_trading_hours"] = GREY_TRADING_HOURS

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
            (
                DISCORD_CHANNEL_HEARTBEAT_ID,
                [f"{info} with settings:\n{get_discord_table(DISCORD_SETTINGS)}"],
                False,
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

            # run strategy for the exchange on LIQUIDATIONS list
            await exchange.run_loop()

            # check for fresh liquidations and add to LIQUIDATIONS list
            await scanner.handle_liquidation_set(
                await exchange.get_last_candle(),
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

            # remove old liquidations from the LIQUIDATIONS list
            exchange.liquidation_set.remove_old_liquidations(now + timedelta(minutes=1))

            # recalculate position sizes based on current balance
            await exchange.set_position_sizes()

            await sleep(0.99)

        if USE_DISCORD and (now.hour % 12 == 8 and now.minute == 1 and now.second == 0):

            # send heartbeat message to discord
            exchange.discord_message_queue.append(
                (DISCORD_CHANNEL_HEARTBEAT_ID, ["."], False)
            )

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
