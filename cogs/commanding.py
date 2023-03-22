from code import interact
import discord
from discord.ext import commands, tasks
from discord.ext.commands import Greedy, Context
from discord import app_commands
from discord.app_commands import checks, MissingPermissions
import re
from datetime import datetime
from typing import List, Optional, Literal
import traceback, sys
import time
import functools
import json
import aiohttp
import tiktoken
import requests
from cachetools import TTLCache
from cogs.utils import Utils

SERVER_BOT = "DISCORD"

# Cog class
class Commanding(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot: commands.Bot = bot
        self.utils = Utils(bot)
        self.cache_user_q = TTLCache(maxsize=20000, ttl=60.0)

        self.engine: str = self.bot.config['openai']['engine']
        self.max_tokens = self.bot.config['openai']['ai_max_tokens']
        self.temperature = self.bot.config['openai']['ai_temperature']
        self.system_prompt = "You are ChatGPT, a large language model trained by OpenAI. Respond conversationally"
        self.session = requests.Session()
        self.conversation: dict = {
            "default": [
                {
                    "role": "system",
                    "content": "You are ChatGPT, a large language model trained by OpenAI. Respond conversationally",
                },
            ],
        }

    # steal from: https://github.com/acheong08/ChatGPT/blob/main/src/revChatGPT/V3.py
    def add_to_conversation(
        self,
        message: str,
        role: str,
        convo_id: str = "default",
    ) -> None:
        """
        Add a message to the conversation
        """
        self.conversation[convo_id].append({"role": role, "content": message})

    def __truncate_conversation(self, convo_id: str = "default") -> None:
        """
        Truncate the conversation
        """
        while True:
            if (
                self.get_token_count(convo_id) > self.max_tokens
                and len(self.conversation[convo_id]) > 1
            ):
                # Don't remove the first message
                self.conversation[convo_id].pop(1)
            else:
                break

    def reset(self, convo_id: str = "default", system_prompt: str = None) -> None:
        """
        Reset the conversation
        """
        self.conversation[convo_id] = [
            {"role": "system", "content": system_prompt or self.system_prompt},
        ]

    # https://github.com/openai/openai-cookbook/blob/main/examples/How_to_count_tokens_with_tiktoken.ipynb
    def get_token_count(self, convo_id: str = "default") -> int:
        """
        Get token count
        """
        if self.engine not in [
            "gpt-3.5-turbo",
            "gpt-3.5-turbo-0301",
            "gpt-4",
            "gpt-4-0314",
            "gpt-4-32k",
            "gpt-4-32k-0314",
        ]:
            error = NotImplementedError(f"Unsupported engine {self.engine}")
            raise error

        tiktoken.model.MODEL_PREFIX_TO_ENCODING["gpt-4-"] = "cl100k_base"
        tiktoken.model.MODEL_TO_ENCODING["gpt-4"] = "cl100k_base"

        encoding = tiktoken.encoding_for_model(self.engine)

        num_tokens = 0
        for message in self.conversation[convo_id]:
            # every message follows <im_start>{role/name}\n{content}<im_end>\n
            num_tokens += 4
            for key, value in message.items():
                num_tokens += len(encoding.encode(value))
                if key == "name":  # if there's a name, the role is omitted
                    num_tokens += 1  # role is always required and always 1 token
        num_tokens += 2  # every reply is primed with <im_start>assistant
        return num_tokens

    def get_max_tokens(self, convo_id: str) -> int:
        """
        Get max tokens
        """
        return self.max_tokens - self.get_token_count(convo_id)

    def req_generate_text(self, config, convo_id):
        try:
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(config['openai']['key']),
            }
            json_data = {
                "model": self.engine,
                "messages": self.conversation[convo_id],
                "stream": True,
                "temperature": self.temperature,
                "n": 1,
                "user": "user",
                "max_tokens": self.get_max_tokens(convo_id=convo_id),
            }
            response = self.session.post(
                url, headers = headers, json = json_data, stream=True
            )
            if response.status_code == 200:
                response_text = response.text
                response_role: str = None
                full_response: str = ""
                data_id = None
                for line in response.iter_lines():
                    if not line:
                        continue
                    line = line.decode("utf-8")[6:] # Remove "data: "
                    if line == "[DONE]":
                        break
                    resp = json.loads(line)
                    data_id = resp['id']
                    choices = resp.get("choices")
                    if not choices:
                        continue
                    delta = choices[0].get("delta")
                    if not delta:
                        continue
                    if "role" in delta:
                        response_role = delta["role"]
                    if "content" in delta:
                        full_response += delta["content"]
                self.add_to_conversation(full_response, response_role, convo_id=convo_id)
                return {
                    "raw_response": response_text, "response": full_response, "data_id": data_id
                }
                # return response_dict["choices"][0]["text"]
            else:
                print("req_generate_text got status {}.".format(response.status))
                print(response)
        except Exception as e:
            traceback.print_exc(file=sys.stdout)
        return None

    async def send_message(self, message, user_message):
        started = int(time.time())
        author = message.author.id
        response = (f'> **{user_message}** - <@{str(author)}' + '> \n\n')
        convo_id = str(author) # id
        reply_loading = None

        # check if in cache
        key = str(author) + "_" + SERVER_BOT
        if key in self.cache_user_q and int(time.time()) - self.cache_user_q[key] < 60:
            await message.channel.send(
                content=f"<@{str(author)}>, 🔴 you have too recent queue in progress. Wait until it finishes!"
            )
            return
        # end of cache

        # check q
        check_q = await self.utils.get_user_queue(
            author, SERVER_BOT, 60
        )
        if check_q >= self.bot.config['discord']['max_q_per_mn']:
            await message.channel.send(
                content=f"<@{str(author)}>, you have a lot of queries per last minute. Cool down!"
            )
            return

        # check q
        check_q = await self.utils.get_user_chats(
            author, SERVER_BOT, 24*3600
        )
        if check_q >= self.bot.config['discord']['max_use_per_day']:
            await message.channel.send(
                content=f"<@{str(author)}>, you have a lot of queries per 24h. Do more tomorrow!"
            )
            return

        # check q
        check_q = await self.utils.get_user_chats(
            author, SERVER_BOT, 3600
        )
        if check_q >= self.bot.config['discord']['max_use_per_hour']:
            await message.channel.send(
                content=f"<@{str(author)}>, you have a lot of queries per last hour. Try again later!"
            )
            return

        # add to queue
        await self.utils.insert_queue_chat(
            author, SERVER_BOT, user_message, str(message.guild.id)
        )

        try:
            if hasattr(message, "response"):
                await message.response.defer()
            else:
                reply_loading = await message.reply(f"<@{str(author)}>, checking ⏳\n> {discord.utils.escape_markdown(user_message)}")
        except Exception as e:
            traceback.print_exc(file=sys.stdout)
        # Make conversation if it doesn't exist
        self.cache_user_q[key] = int(time.time())
        if convo_id not in self.conversation:
            self.reset(convo_id=convo_id, system_prompt=self.system_prompt)
        self.add_to_conversation(user_message, "user", convo_id=convo_id)
        self.__truncate_conversation(convo_id=convo_id)
        get_answer = functools.partial(
            self.req_generate_text, self.bot.config, convo_id=convo_id
        )
        get_response = await self.bot.loop.run_in_executor(None, get_answer)
        if get_response is None:
            await message.channel.send(
                content=f"<@{str(author)}>, error during fetching query. Try again later!"
            )
            del self.cache_user_q[key]
            return
        else:
            finished = int(time.time())
            await self.utils.insert_chat_msg(
                author, SERVER_BOT, get_response['data_id'], convo_id, user_message,
                get_response['raw_response'], get_response['response'], started, finished,
                str(message.guild.id)
            )

            if reply_loading is not None:
                await reply_loading.delete()
            response = f"{response}{get_response['response']}"
            char_limit = self.bot.config['discord']['char_limit']
            if len(response) > char_limit:
                # Split the response into smaller chunks of no more than 1900 characters each(Discord limit is 2000 per chunk)
                if "```" in response:
                    # Split the response if the code block exists
                    parts = response.split("```")
                    for i in range(len(parts)):
                        if i%2 == 0: # indices that are even are not code blocks
                            await message.channel.send(parts[i])
                        else: # Odd-numbered parts are code blocks
                            code_block = parts[i].split("\n")
                            formatted_code_block = ""
                            for line in code_block:
                                while len(line) > char_limit:
                                    # Split the line at the 50th character
                                    formatted_code_block += line[:char_limit] + "\n"
                                    line = line[char_limit:]
                                formatted_code_block += line + "\n"  # Add the line and seperate with new line

                            # Send the code block in a separate message
                            if (len(formatted_code_block) > char_limit+100):
                                code_block_chunks = [formatted_code_block[i:i+char_limit]
                                                    for i in range(0, len(formatted_code_block), char_limit)]
                                for chunk in code_block_chunks:
                                    await message.channel.send(f"```{chunk}```")
                            else:
                                await message.channel.send(f"```{formatted_code_block}```")
                else:
                    response_chunks = [response[i:i+char_limit] for i in range(0, len(response), char_limit)]
                    for chunk in response_chunks:
                        try:
                            await message.channel.send(chunk)
                        except Exception as e:
                            traceback.print_exc(file=sys.stdout)
            else:
                await message.channel.send(response)
        del self.cache_user_q[key]

    @app_commands.guild_only()
    @commands.hybrid_command(
        name="chat",
        description="Chat with Bot"
    )
    async def command_chat(
        self,
        ctx,
        message: str
    ) -> None:
        """ /chat <message> """
        # if not public
        if self.bot.config['discord']['is_private'] == 1 and ctx.author.id not in self.bot.config['discord']['testers']:
            return
        await self.send_message(ctx, message)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return
        else:
            if not hasattr(message, "guild"):
                return
            # if not public
            if self.bot.config['discord']['is_private'] == 1 and message.author.id not in self.bot.config['discord']['testers']:
                return
            if str(message.content).split(" ")[1].lower() in ["reload", "load", "donate", "sync"]:
                return
            if not self.bot.user.mentioned_in(message):
                return
            await self.send_message(message, str(message.content))

    @app_commands.guild_only()
    @commands.hybrid_command(
        name="sync",
        description="Sync commands"
    )
    @commands.is_owner()
    async def command_sync(
        self, ctx: Context, guilds: Greedy[discord.Object], spec: Optional[Literal["~", "*", "^"]] = None
    ) -> None:
        try:
            if not guilds:
                if spec == "~":
                    synced = await ctx.bot.tree.sync(guild=ctx.guild)
                elif spec == "*":
                    ctx.bot.tree.copy_global_to(guild=ctx.guild)
                    synced = await ctx.bot.tree.sync(guild=ctx.guild)
                elif spec == "^":
                    ctx.bot.tree.clear_commands(guild=ctx.guild)
                    await ctx.bot.tree.sync(guild=ctx.guild)
                    synced = []
                else:
                    synced = await ctx.bot.tree.sync()

                await ctx.send(
                    f"Synced {len(synced)} commands {'globally' if spec is None else 'to the current guild.'}"
                )
                return
            else:
                ret = 0
                for guild in guilds:
                    try:
                        await ctx.bot.tree.sync(guild=guild)
                    except discord.HTTPException:
                        pass
                    else:
                        ret += 1
                await ctx.send(f"Synced the tree to {ret}/{len(guilds)}.")
        except Exception as e:
            traceback.print_exc(file=sys.stdout)

    @commands.Cog.listener()
    async def on_ready(self):
        pass

    async def cog_load(self) -> None:
        pass

    async def cog_unload(self) -> None:
        pass

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Commanding(bot))
