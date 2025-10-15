# t-Ray-dingbot

Fully automatic trading bot for (Phemex) Futures using liquidations from Coinalyze to counter trade as a strategy. The bot currently uses 4 strategies: live, reversed, Grey and journaling. The position sizes for these strategies are full for live, reversed and grey, but minimal size for journaling.

## To get started

    python -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    python .

## Variables

Have the following variables in your .env file

    COINALYZE_SECRET_API_KEY=
    POSITION_PERCENTAGE=
    EXCHANGE_NAME=
    EXCHANGE_API_KEY=
    EXCHANGE_SECRET_KEY=

If you want to customize the different strategy (LIVE, REVERSED, GREY, JOURNALING) variables add the following to your liking:

    USE_[STRATEGY]_STRATEGY=
    [STRATEGY]_SL_PERCENTAGE=
    [STRATEGY]_TP_PERCENTAGE=
    [STRATEGY]_TRADING_DAYS=
    [STRATEGY]_TRADING_HOURS=


If you want to use a discord bot you must add the following variables:

    USE_DISCORD=true
    DISCORD_PRIVATE_KEY=
    DISCORD_CHANNEL_POSITIONS_ID=
    DISCORD_CHANNEL_HEARTBEAT_ID=
    DISCORD_CHANNEL_LIQUIDATIONS_ID=
    DISCORD_CHANNEL_TRADES_ID=

If you want to auto journal your trades you can run my other project https://github.com/rayvtoll/journal-backend and set it up using:

    USE_AUTO_JOURNALING=true
    JOURNAL_HOST_AND_PORT=
    JOURNALING_API_KEY=