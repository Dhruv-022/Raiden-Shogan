import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Raiden Shogan is presented(Online) as {bot.user} (ID: {bot.user.id})")

async def main():
    async with bot:
        await bot.load_extension("cogs.ticket_system")
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())