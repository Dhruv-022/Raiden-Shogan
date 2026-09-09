import os
import re
import json
import asyncio
import datetime
import discord
from discord.ext import commands

DATA_FILE = "tickets.json"
BOT_OWNER_ID = 757990668357599302

# Expanded, Case-Insensitive Banned Words & Slurs List
BANNED_WORDS = [
    "chut", "chutiya", "chutiyap", "madarchod", "behanchod", "bhenchod", "benchod", "bhosdike", "bhosda",
    "gand", "gandu", "gandfaad", "gaand", "land", "lund", "lauda", "loda", "lode", "randi", "rand", "mc", "bc",
    "fuck", "fucking", "fucked", "fucker", "motherfuck", "motherfucker", "bitch", "bastard", "asshole", "dick",
    "pussy", "cunt", "cock", "slut", "whore", "boob", "boobs", "tits", "sex", "sux", "kutta", "kamina"
]

def load_tickets():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_tickets(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def contains_banned_word(text: str) -> bool:
    if not text:
        return False
    text_lowered = text.lower()
    for word in BANNED_WORDS:
        pattern = rf"\b{re.escape(word.lower())}\b"
        if re.search(pattern, text_lowered):
            return True
    return False


class TicketSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.category_id = int(os.getenv("CATEGORY_ID", 0))
        self.max_tickets = int(os.getenv("MAX_TICKETS", 12))
        
        # Parses comma-separated STAFF_ROLE_IDS into a list of integers
        role_ids_raw = os.getenv("STAFF_ROLE_IDS", "")
        self.staff_role_ids = [int(rid.strip()) for rid in role_ids_raw.split(",") if rid.strip().isdigit()]

    def is_staff_or_owner(self, member: discord.Member, permission_attr: str = "manage_channels") -> bool:
        if member.id == BOT_OWNER_ID:
            return True
        if hasattr(member, "roles"):
            if any(role.id in self.staff_role_ids for role in member.roles):
                return True
        if hasattr(member, "guild_permissions"):
            return getattr(member.guild_permissions, permission_attr, False)
        return False

    async def get_origin_channel(self, channel_id: int):
        channel = self.bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return None
        return channel

    async def convert_attachments(self, attachments):
        files = []
        for attachment in attachments:
            try:
                file = await attachment.to_file()
                files.append(file)
            except discord.HTTPException:
                pass
        return files

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        if message.content.startswith("!"):
            return

        tickets = load_tickets()
        user_id = str(message.author.id)

        # -------------------------------------------------------------
        # 1. STAFF REPLYING FROM INSIDE A TICKET CHANNEL
        # -------------------------------------------------------------
        for uid, data in tickets.items():
            if data["staff_channel_id"] == message.channel.id:
                # Check banned words for staff members
                if contains_banned_word(message.content):
                    await message.channel.send(
                        f"⚡ {message.author.mention} **Your message contains a blocked word. Kindly show some respect to your position as a staff member.**"
                    )
                    return

                target_user = message.guild.get_member(int(uid))
                origin_channel = await self.get_origin_channel(data["origin_channel_id"])

                if origin_channel and target_user:
                    try:
                        staff_files = await self.convert_attachments(message.attachments)
                        content = f"{target_user.mention} {message.content}" if message.content else target_user.mention

                        await origin_channel.send(content=content, files=staff_files)
                        await message.add_reaction("⚡")
                    except discord.Forbidden:
                        await message.add_reaction("❌")
                        await message.channel.send(
                            f"⚡ **Decree:** Missing permission to transmit decree to <#{data['origin_channel_id']}>."
                        )
                    except discord.HTTPException as e:
                        await message.add_reaction("❌")
                        await message.channel.send(f"⚡ Failed to send message: {e}")
                else:
                    await message.channel.send("⚡ Could not find the original channel or user.")
                return

        # -------------------------------------------------------------
        # 2. USER MENTIONING BOT IN PUBLIC / VOICE CHAT
        # -------------------------------------------------------------
        if self.bot.user in message.mentions:
            clean_content = message.content.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip()
            user_files = await self.convert_attachments(message.attachments)
            
            user_used_banned_word = contains_banned_word(clean_content)

            if user_used_banned_word:
                await message.channel.send(f"⚠️ {message.author.mention} **You have used an inappropriate word.**")

            # A. User already has an active ticket -> Forward message
            if user_id in tickets:
                staff_channel = self.bot.get_channel(tickets[user_id]["staff_channel_id"])
                if staff_channel:
                    tickets[user_id]["origin_channel_id"] = message.channel.id
                    save_tickets(tickets)

                    embed_color = discord.Color.red() if user_used_banned_word else discord.Color.purple()
                    embed_title = "🚨 Moderation Action Required — Inappropriate Language Detected" if user_used_banned_word else None

                    embed = discord.Embed(
                        title=embed_title,
                        description=clean_content or "*(Attachment attached)*",
                        color=embed_color
                    )
                    embed.set_author(name=f"Transmission from {message.author}", icon_url=message.author.display_avatar.url)
                    
                    await staff_channel.send(embed=embed, files=user_files)
                    await message.add_reaction("📥")
                else:
                    del tickets[user_id]
                    save_tickets(tickets)

            # B. User has NO active ticket -> Create new ticket channel
            if user_id not in tickets:
                if len(tickets) >= self.max_tickets:
                    await message.channel.send(
                        f"⚡ **Inquiry Limit Reached:** The Shogunate is currently addressing **{len(tickets)}/{self.max_tickets}** ongoing matters. "
                        "Please state your business again shortly."
                    )
                    await message.add_reaction("⏳")
                    return

                # Fetch category via cache or API fallback
                category = message.guild.get_channel(self.category_id)
                if not category:
                    try:
                        category = await message.guild.fetch_channel(self.category_id)
                    except (discord.NotFound, discord.HTTPException):
                        category = None

                if not category or not isinstance(category, discord.CategoryChannel):
                    await message.channel.send(f"⚡ **Error:** Category ID `{self.category_id}` is invalid or resolved as `{type(category).__name__}`.")
                    return

                # Build channel permission overwrites (STAFF & BOT ONLY)
                overwrites = {
                    message.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    message.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                }

                # Explicitly add your developer user account
                dev_user = message.guild.get_member(BOT_OWNER_ID)
                if dev_user:
                    overwrites[dev_user] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

                # Dynamically grant access to all staff roles defined in .env
                for role_id in self.staff_role_ids:
                    role = message.guild.get_role(role_id)
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

                clean_username = message.author.name.lower().replace(" ", "-")
                channel_name = f"ticket-{clean_username}-{user_id[-4:]}"

                try:
                    staff_channel = await message.guild.create_text_channel(
                        name=channel_name,
                        category=category,
                        overwrites=overwrites
                    )

                    tickets[user_id] = {
                        "staff_channel_id": staff_channel.id,
                        "origin_channel_id": message.channel.id
                    }
                    save_tickets(tickets)

                    embed_color = discord.Color.red() if user_used_banned_word else discord.Color.purple()
                    embed_title = "🚨 Moderation Action Required — Inappropriate Language Detected" if user_used_banned_word else "⚡ New Shogunate Inquiry"

                    embed = discord.Embed(
                        title=embed_title,
                        description=clean_content or "*(Attachment attached)*",
                        color=embed_color
                    )
                    embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
                    embed.set_footer(text="Type your reply here. Use !close to seal and terminate this inquiry.")
                    
                    await staff_channel.send(
                        content=f"@here New inquiry received from {message.author.mention}", 
                        embed=embed, 
                        files=user_files
                    )
                    await message.add_reaction("⚡")

                except discord.HTTPException as e:
                    await message.channel.send(f"⚡ Failed to create ticket channel: `{e}`")

    @commands.command()
    async def close(self, ctx):
        tickets = load_tickets()
        target_user_id = None

        for uid, data in list(tickets.items()):
            if data["staff_channel_id"] == ctx.channel.id:
                target_user_id = uid
                break

        if not target_user_id:
            await ctx.send("⚡ This command can only be executed inside an active ticket channel.")
            return

        del tickets[target_user_id]
        save_tickets(tickets)

        await ctx.send("⚡ **Inquiry Sealed.** Terminating channel in 3 seconds...")
        await discord.utils.sleep_until(discord.utils.utcnow() + datetime.timedelta(seconds=3))
        await ctx.channel.delete()

    @commands.command(name="closeall")
    async def close_all_tickets(self, ctx: commands.Context):
        if not self.is_staff_or_owner(ctx.author, "manage_channels"):
            await ctx.send("⚡ You lack the required authority to close all inquiries.")
            return

        category = ctx.guild.get_channel(self.category_id)
        if not category:
            try:
                category = await ctx.guild.fetch_channel(self.category_id)
            except (discord.NotFound, discord.HTTPException):
                category = None

        if not category or not isinstance(category, discord.CategoryChannel):
            await ctx.send("⚡ Ticket category not found or invalid CATEGORY_ID.")
            return

        tickets = load_tickets()
        ticket_channels = [ch for ch in category.text_channels if ch.name.startswith("ticket-")]

        if not ticket_channels and not tickets:
            await ctx.send("⚡ No active ticket channels or records found to close.")
            return

        status_msg = await ctx.send(f"⚡ Terminating **{len(ticket_channels)}** active ticket channel(s)... Please hold.")

        for channel in ticket_channels:
            try:
                await channel.delete()
                await asyncio.sleep(0.5)
            except discord.HTTPException:
                pass

        save_tickets({})

        try:
            await status_msg.edit(content="⚡ **Shogunate Sweep Complete:** All active tickets have been closed and purged.")
        except discord.NotFound:
            pass

    @commands.command(name="delete", aliases=["purge", "clear"])
    async def purge_messages(self, ctx: commands.Context, amount: int = None):
        """Purges up to 44 messages from the current channel."""
        if not self.is_staff_or_owner(ctx.author, "manage_messages"):
            await ctx.send("⚡ **Decree:** You lack the required authority to purge messages.")
            return

        if amount is None or amount <= 0:
            await ctx.send("⚡ Please specify a valid number of messages to purge (e.g., `!delete 10` or `@Raiden Shogun delete 10`).")
            return

        purge_count = min(amount, 44)

        try:
            await ctx.message.delete()
            deleted = await ctx.channel.purge(limit=purge_count)

            confirm_msg = await ctx.send(f"⚡ **Shogunate Purge:** Cleared `{len(deleted)}` message(s).")
            await asyncio.sleep(3)
            await confirm_msg.delete()

        except discord.Forbidden:
            await ctx.send("⚡ **Error:** I lack the `Manage Messages` permission in this channel.")
        except discord.HTTPException as e:
            await ctx.send(f"⚡ **Error during purge:** `{e}`")

async def setup(bot):
    await bot.add_cog(TicketSystem(bot))