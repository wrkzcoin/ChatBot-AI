import sys
import traceback
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands


class Donate(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot: commands.Bot = bot


    @app_commands.command(
        name='donate',
        description="Show donation address to ChatBot"
    )
    async def slash_donate(
        self, interaction: discord.Interaction
    ) -> None:
        """ /donate """
        await interaction.response.send_message(f"{interaction.user.mention} loading donation info...")
        try:
            embed = discord.Embed(
                title='Donation',
                description="Thank you for checking. Any amount of donation is appreciated!",
                timestamp=datetime.now()
            )
            for k, v in self.bot.config['donate'].items():
                embed.add_field(name=k.upper(), value=v, inline=False)
            embed.set_footer(
                text=f'/donate | requested by {interaction.user.name}',
                icon_url=self.bot.user.display_avatar
            )
            embed.set_author(name=self.bot.user.name, icon_url=self.bot.user.display_avatar)
            await interaction.edit_original_response(content=None, embed=embed)
        except Exception:
            traceback.print_exc(file=sys.stdout)

    async def cog_load(self) -> None:
        pass

    async def cog_unload(self) -> None:
        pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Donate(bot))
