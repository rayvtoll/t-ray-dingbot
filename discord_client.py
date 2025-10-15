from typing import List, Tuple
from decouple import config
import discord
from logger import logger
import yaml


USE_DISCORD = config("USE_DISCORD", cast=bool, default=False)
logger.info(f"{USE_DISCORD=}")
if USE_DISCORD:
    DISCORD_CHANNEL_POSITIONS_ID = config("DISCORD_CHANNEL_POSITIONS_ID", cast=int)
    DISCORD_CHANNEL_HEARTBEAT_ID = config("DISCORD_CHANNEL_HEARTBEAT_ID", cast=int)
    DISCORD_CHANNEL_LIQUIDATIONS_ID = config(
        "DISCORD_CHANNEL_LIQUIDATIONS_ID", cast=int
    )
    DISCORD_CHANNEL_TRADES_ID = config("DISCORD_CHANNEL_TRADES_ID", cast=int)
    DISCORD_PRIVATE_KEY = config("DISCORD_PRIVATE_KEY")
    USE_AT_EVERYONE = config("USE_AT_EVERYONE", cast=bool, default=False)


def get_discord_table(obj: dict) -> str:
    """Convert a dictionary to a discord friendly table"""

    return f"```{yaml.dump(obj, default_flow_style=False)}```"


def get_formatted_unordered_list(obj: dict, nested: bool = False) -> str:
    """Convert a dictionary to a discord friendly unordered list"""

    formatted_string = ""
    for key, value in obj.items():
        if isinstance(value, dict):
            formatted_string += f"\n**{key}**:\n{get_formatted_unordered_list(value)}\n"
        elif isinstance(value, list):
            formatted_string += f"- **{key}**: {', '.join(str(i) for i in value)}\n"
        else:
            formatted_string += f"- **{key}**: {value}\n"
    return formatted_string


def post_to_discord(message_queue: List[Tuple[int, List[str], bool]]) -> None:
    """Post messages to discord and empty the message queue"""

    intents = discord.Intents.default()
    intents.messages = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        try:
            for channel_id, messages, at_everyone in message_queue:
                channel = client.get_channel(channel_id)
                if at_everyone:
                    await channel.send(f"@everyone\n")
                for message in messages:
                    await channel.send(f"{message}")
        except Exception as e:
            logger.error(f"Failed to post to Discord: {e}")
        finally:
            await client.close()

    try:
        client.run(token=DISCORD_PRIVATE_KEY, log_handler=None)
    except Exception as e:
        logger.error(f"Failed to post to Discord: {e}")
