# t-Ray-dingbot

Fully automatic trading bot for (BloFin) Futures using liquidations from Coinalyze to counter trade as a strategy. The bot currently uses 1 strategy. 
For BloFin discount you can use my referral link if you like: TdkPZp

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

If you want to customize the strategy variables add the following to your liking:

    SL_PERCENTAGE=
    TP_PERCENTAGE=
    LIQUIDATION_DAYS=
    LIQUIDATION_HOURS=
    ENTRY_DAYS=
    ENTRY_HOURS=


If you want to use a discord bot you must add the following variables:

    USE_DISCORD=true
    DISCORD_PRIVATE_KEY=
    DISCORD_CHANNEL_POSITIONS_ID=
    DISCORD_CHANNEL_HEARTBEAT_ID=
    DISCORD_CHANNEL_LIQUIDATIONS_ID=
    DISCORD_CHANNEL_WATING_ID=
    DISCORD_CHANNEL_TRADES_ID=
