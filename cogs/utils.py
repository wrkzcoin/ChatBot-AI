import re
from discord.ext import commands, tasks
import discord
import traceback, sys
import aiomysql
from aiomysql.cursors import DictCursor
import time


def check_regex(given: str):
    try:
        re.compile(given)
        is_valid = True
    except re.error:
        is_valid = False
    return is_valid


# Cog class
class Utils(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot: commands.Bot = bot
        self.db_pool = None

    async def open_connection(self):
        try:
            if self.db_pool is None:
                self.db_pool = await aiomysql.create_pool(
                    host=self.bot.config['mysql']['host'], port=3306, minsize=1, maxsize=2,
                    user=self.bot.config['mysql']['user'], password=self.bot.config['mysql']['password'],
                    db=self.bot.config['mysql']['db'], cursorclass=DictCursor, autocommit=True
                )
        except Exception:
            traceback.print_exc(file=sys.stdout)

    async def log_to_channel(self, channel_id: int, content: str) -> None:
        try:
            channel = self.bot.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(content)
                except Exception as e:
                    traceback.print_exc(file=sys.stdout)
        except Exception as e:
            traceback.print_exc(file=sys.stdout)

    async def get_bot_perm(self, guild):
        try:
            get_bot_user = guild.get_member(self.bot.user.id)
            return dict(get_bot_user.guild_permissions)
        except Exception as e:
            traceback.print_exc(file=sys.stdout)
        return None

    async def get_user_perms(self, guild, user_id):
        try:
            get_user = guild.get_member(user_id)
            return dict(get_user.guild_permissions)
        except Exception as e:
            traceback.print_exc(file=sys.stdout)
        return None

    async def is_managed_message(self, guild, user_id):
        try:
            get_user = guild.get_member(user_id)
            check_perm = dict(get_user.guild_permissions)
            if check_perm and (check_perm['manage_channels'] is True) or \
                (check_perm['manage_messages'] is True):
                return True
        except Exception as e:
            traceback.print_exc(file=sys.stdout)
        return False

    async def is_moderator(self, guild, user_id):
        """
        Sample permission dict
        {
            'create_instant_invite': True,
            'kick_members': False,
            'ban_members': False,
            'administrator': True,
            'manage_channels': True,
            'manage_guild': True,
            'add_reactions': True,
            'view_audit_log': True,
            'priority_speaker': False,
            'stream': True,
            'view_channel': True,
            'send_messages': True,
            'send_tts_messages': True,
            'manage_messages': False,
            'embed_links': True,
            'attach_files': True,
            'read_message_history': True,
            'mention_everyone': True,
            'external_emojis': True,
            'view_guild_insights': False,
            'connect': True,
            'speak': True,
            'mute_members': False,
            'deafen_members': False,
            'move_members': False,
            'use_voice_activation': True,
            'change_nickname': True,
            'manage_nicknames': False,
            'manage_roles': True,
            'manage_webhooks': False,
            'manage_emojis': False,
            'use_slash_commands': True,
            'request_to_speak': True,
            'manage_events': False,
            'manage_threads': False,
            'create_public_threads': False,
            'create_private_threads': False,
            'external_stickers': False,
            'send_messages_in_threads': False,
            'start_embedded_activities': False,
            'moderate_members': False}
        """
        try:
            get_user = guild.get_member(user_id)
            check_perm = dict(get_user.guild_permissions)
            if check_perm and (check_perm['manage_channels'] is True) or \
                (check_perm['ban_members'] is True):
                return True
        except Exception as e:
            traceback.print_exc(file=sys.stdout)
        return False

    async def get_user_queue(
        self, user_id: str, user_server: str, duration: int=3600
    ):
        try:
            lap_duration = int(time.time()) - duration
            await self.open_connection()
            async with self.db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    sql = """
                    SELECT COUNT(*) AS q FROM `chat_queues`
                    WHERE `user_id`=%s AND `user_server`=%s AND `started`>%s
                    """
                    await cur.execute(sql, (user_id, user_server, lap_duration))
                    result = await cur.fetchone()
                    if result:
                        return result['q']
        except Exception:
            traceback.print_exc(file=sys.stdout)
        return 0

    async def insert_queue_chat(
        self, user_id: str, user_server: str, asked: str, guild_id: int
    ):
        try:
            await self.open_connection()
            async with self.db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    sql = """
                    INSERT INTO `chat_queues` (`user_id`, `user_server`, `guild_id`, `started`, `asked`)
                    VALUES (%s, %s, %s, %s, %s);
                    """
                    await cur.execute(sql, (user_id, user_server, guild_id, int(time.time()), asked))
                    await conn.commit()
                    return True
        except Exception:
            traceback.print_exc(file=sys.stdout)
        return False

    async def get_user_chats(
        self, user_id: str, user_server: str, duration: int=3600
    ):
        try:
            lap_duration = int(time.time()) - duration
            await self.open_connection()
            async with self.db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    sql = """
                    SELECT COUNT(*) AS q FROM `chat_messages`
                    WHERE `user_id`=%s AND `user_server`=%s AND `started`>%s
                    """
                    await cur.execute(sql, (user_id, user_server, lap_duration))
                    result = await cur.fetchone()
                    if result:
                        return result['q']
        except Exception:
            traceback.print_exc(file=sys.stdout)
        return 0

    async def insert_chat_msg(
        self, user_id: str, user_server: str, data_id: str, convo_id: str, asked: str, 
        raw_response: str, response: str, started: int, finished: int, guild_id: str
    ):
        try:
            await self.open_connection()
            async with self.db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    sql = """
                    INSERT INTO `chat_messages` (`user_id`, `user_server`, `guild_id`, `data_id`, `convo_id`, 
                    `time`, `asked`, `raw_response`, `response`,
                    `started`, `finished`)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                    """
                    await cur.execute(sql, (
                        user_id, user_server, guild_id, data_id, convo_id, finished - started,
                        asked, raw_response, response, started, finished
                    ))
                    await conn.commit()
                    return True
        except Exception:
            traceback.print_exc(file=sys.stdout)
        return False

    @commands.Cog.listener()
    async def on_ready(self):
        pass

    async def cog_load(self) -> None:
        pass

    async def cog_unload(self) -> None:
        pass

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Utils(bot))