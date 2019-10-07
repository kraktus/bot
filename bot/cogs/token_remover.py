import base64
import binascii
import logging
import re
import struct
from datetime import datetime

from discord import Colour, Message
from discord.ext.commands import Bot, Cog
from discord.utils import snowflake_time

from bot.cogs.modlog import ModLog
from bot.constants import Channels, Colours, Event, Icons

log = logging.getLogger(__name__)

DELETION_MESSAGE_TEMPLATE = (
    "Hey {mention}! I noticed you posted a seemingly valid Discord API "
    "token in your message and have removed your message. "
    "This means that your token has been **compromised**. "
    "Please change your token **immediately** at: "
    "<https://discordapp.com/developers/applications/me>\n\n"
    "Feel free to re-post it with the token removed. "
    "If you believe this was a mistake, please let us know!"
)
DISCORD_EPOCH_TIMESTAMP = datetime(2017, 1, 1)
TOKEN_EPOCH = 1_293_840_000
TOKEN_RE = re.compile(
    r"[^\s\.]+"     # Matches token part 1: The user ID string, encoded as base64
    r"\."           # Matches a literal dot between the token parts
    r"[^\s\.]+"     # Matches token part 2: The creation timestamp, as an integer
    r"\."           # Matches a literal dot between the token parts
    r"[^\s\.]+"     # Matches token part 3: The HMAC, unused by us, but check that it isn't empty
)


class TokenRemover(Cog):
    """Scans messages for potential discord.py bot tokens and removes them."""

    def __init__(self, bot: Bot):
        self.bot = bot

    @property
    def mod_log(self) -> ModLog:
        """Get currently loaded ModLog cog instance."""
        return self.bot.get_cog("ModLog")

    @Cog.listener()
    async def on_message(self, msg: Message) -> None:
        """
        Check each message for a string that matches Discord's token pattern.

        See: https://discordapp.com/developers/docs/reference#snowflakes
        """
        if self.is_token_in_message(msg):
            user_id, creation_timestamp, hmac = TOKEN_RE.search(msg.content).group(0).split('.')
            self.mod_log.ignore(Event.message_delete, msg.id)
            await msg.delete()
            await msg.channel.send(DELETION_MESSAGE_TEMPLATE.format(mention=msg.author.mention))

            message = (
                "Censored a seemingly valid token sent by "
                f"{msg.author} (`{msg.author.id}`) in {msg.channel.mention}, token was "
                f"`{user_id}.{creation_timestamp}.{'x' * len(hmac)}`"
            )
            log.debug(message)

            # Send pretty mod log embed to mod-alerts
            await self.mod_log.send_log_message(
                icon_url=Icons.token_removed,
                colour=Colour(Colours.soft_red),
                title="Token removed!",
                text=message,
                thumbnail=msg.author.avatar_url_as(static_format="png"),
                channel_id=Channels.mod_alerts,
            )

    def is_token_in_message(self, msg: Message) -> bool:
        """Check if `msg` contains a seemly valid token."""
        if msg.author.bot:
            return False

        maybe_match = TOKEN_RE.search(msg.content)
        if maybe_match is None:
            return False

        try:
            user_id, creation_timestamp, hmac = maybe_match.group(0).split('.')
        except ValueError:
            return False

        if self.is_valid_user_id(user_id) and self.is_valid_timestamp(creation_timestamp):
            return True

    @staticmethod
    def is_valid_user_id(b64_content: str) -> bool:
        """
        Check potential token to see if it contains a valid Discord user ID.

        See: https://discordapp.com/developers/docs/reference#snowflakes
        """
        b64_content += '=' * (-len(b64_content) % 4)

        try:
            content: bytes = base64.b64decode(b64_content)
            return content.decode('utf-8').isnumeric()
        except (binascii.Error, UnicodeDecodeError):
            return False

    @staticmethod
    def is_valid_timestamp(b64_content: str) -> bool:
        """
        Check potential token to see if it contains a valid timestamp.

        See: https://discordapp.com/developers/docs/reference#snowflakes
        """
        b64_content += '=' * (-len(b64_content) % 4)

        try:
            content = base64.urlsafe_b64decode(b64_content)
            snowflake = struct.unpack('i', content)[0]
        except (binascii.Error, struct.error):
            return False
        return snowflake_time(snowflake + TOKEN_EPOCH) < DISCORD_EPOCH_TIMESTAMP


def setup(bot: Bot) -> None:
    """Token Remover cog load."""
    bot.add_cog(TokenRemover(bot))
    log.info("Cog loaded: TokenRemover")
