import os
import re
import requests
import discord
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from discord import app_commands
from discord.ext import commands
from bs4 import BeautifulSoup
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TB_SLUG = "28xgk8liiv8o"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


def normalize_member_name(name: str) -> str:
    # TB Clan Tools docs say spaces become underscores on member URLs
    return name.strip().replace(" ", "_")


def get_member_url(member_name: str) -> str:
    safe_name = normalize_member_name(member_name)
    return f"https://tbclantools.com/p/{TB_SLUG}/members/{safe_name}"


def extract_stat_from_text(text: str, label: str) -> str | None:
    """
    Fallback text matcher.
    Tries to find patterns like:
    Points 12345
    Chests 678
    """
    pattern = rf"{label}\s*[:\-]?\s*([\d,]+)"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


async def fetch_member_stats(member_name: str) -> dict:
    url = get_member_url(member_name)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)

        text = await page.locator("body").inner_text()
        await browser.close()

    print("\n===== PLAYER PAGE TEXT =====\n")
    print(text[:4000])
    print("\n============================\n")

    points = None
    chests = None
    lines = text.splitlines()

    print("\n===== MATCH LINES =====")
    for line in lines:
        low = line.lower().strip()

        if "point" in low or "chest" in low:
            print(line)

        if "chest" in low and not chests:
            match = re.search(r'([\d,]+)\s*/\s*([\d,]+)\s*chests?', line, re.IGNORECASE)
            if match:
                chests = match.group(1)
            else:
                match = re.search(r'([\d,]+)\s*chests?', line, re.IGNORECASE)
                if match:
                    chests = match.group(1)

        if "point" in low and not points:
            match = re.search(
                r'([\d,.]+(?:[kKmM])?)\s*(?:/\s*[\d,.]+(?:[kKmM])?)?\s*points?',
                line,
                re.IGNORECASE
            )
            if match:
                points = match.group(1)

    print("=======================\n")

    return {
        "member": member_name,
        "url": url,
        "points": points,
        "chests": chests,
        "found_anything": bool(points or chests),
    }
async def fetch_dashboard_targets() -> dict:
    url = f"https://tbclantools.com/p/{TB_SLUG}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)

        text = await page.locator("body").inner_text()
        await browser.close()

    print("\n===== DASHBOARD TEXT =====\n")
    print(text[:6000])
    print("\n==========================\n")

    current_points = None
    target_points = None
    percent = None
    status = None

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for i, line in enumerate(lines):
        if line.upper() == "CLAN WEEKLY PROGRESS":
            block = lines[i:i+6]

            print("\n===== CLAN WEEKLY PROGRESS BLOCK =====")
            for b in block:
                print(b)
            print("======================================\n")

            for b in block:
                match = re.search(
                    r'([\d,.]+(?:[kKmM])?)\s*/\s*([\d,.]+(?:[kKmM])?)',
                    b,
                    re.IGNORECASE
                )
                if match and not current_points:
                    current_points = match.group(1)
                    target_points = match.group(2)

                if re.fullmatch(r'\d+%', b) and not percent:
                    percent = b

                if any(word in b.lower() for word in ["exceeded", "behind", "on track", "critical"]):
                    status = b

            break

    return {
        "url": url,
        "current_points": current_points,
        "target_points": target_points,
        "percent": percent,
        "status": status,
    }
async def fetch_weekly_player_stats(member_name: str) -> dict:
    url = f"https://tbclantools.com/p/{TB_SLUG}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)

        text = await page.locator("body").inner_text()
        await browser.close()

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    print("\n===== WEEKLY PLAYER SEARCH =====")
    print(f"Searching for: {member_name}")
    print("================================\n")

    target_name = member_name.strip().lower()

    for i, line in enumerate(lines):
        if line.lower() == target_name:
            points = None
            chests = None
            status = None
            percent = None

            # Look at the next few lines after the player's name
            block = lines[i:i+8]

            print("\n===== PLAYER BLOCK =====")
            for b in block:
                print(b)
            print("========================\n")

            for b in block:
                low = b.lower()

                if "points" not in low and re.search(r'[\d,.]+[kKmM]?\s*/\s*[\d,.]+[kKmM]?', b) and not points:
                    points = b

                if "chest" in low and not chests:
                    chests = b

                if ("over!" in low or "to go" in low or "behind" in low or "exceeded" in low) and not status:
                    status = b

                if re.fullmatch(r'\d+%', b) and not percent:
                    percent = b

            return {
                "member": member_name,
                "points": points,
                "chests": chests,
                "status": status,
                "percent": percent,
                "found": True,
            }

    return {
        "member": member_name,
        "points": None,
        "chests": None,
        "status": None,
        "percent": None,
        "found": False,
    }
async def fetch_weekly_progress_players() -> list[dict]:
    url = f"https://tbclantools.com/p/{TB_SLUG}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)

        text = await page.locator("body").inner_text()
        await browser.close()

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    players = []
    in_section = False
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.startswith("WEEKLY PROGRESS ("):
            in_section = True
            i += 1
            continue

        if in_section and line.startswith("SUMMARY"):
            break

        if in_section:
            # Skip icon-only lines like 🎯
            if len(line) <= 2:
                i += 1
                continue

            # Player names are usually followed by points/chests/status/percent
            if i + 3 < len(lines):
                name = line
                points_line = lines[i + 1]
                chests_line = lines[i + 2]
                status_line = lines[i + 3]
                percent_line = lines[i + 4] if i + 4 < len(lines) else ""

                if "/" in points_line and "chest" in chests_line.lower():
                    percent_match = re.search(r'(\d+)%', percent_line)
                    percent_value = int(percent_match.group(1)) if percent_match else None

                    players.append({
                        "name": name,
                        "points": points_line,
                        "chests": chests_line,
                        "status": status_line,
                        "percent": percent_value,
                        "percent_text": percent_line if percent_match else "Not found",
                    })

                    i += 5
                    continue

        i += 1

    print("\n===== WEEKLY PROGRESS PLAYERS =====")
    for p in players[:10]:
        print(p)
    print("===================================\n")

    return players


async def fetch_at_risk_players() -> list[dict]:
    url = f"https://tbclantools.com/p/{TB_SLUG}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)

        text = await page.locator("body").inner_text()
        await browser.close()

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    players = []
    in_section = False
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.startswith("AT-RISK PLAYERS"):
            in_section = True
            i += 1
            continue

        if in_section and (
            line.startswith("In-Game Chat Messages")
            or line.startswith("Powered by")
        ):
            break

        if in_section:
            # Skip icon-only lines
            if len(line) <= 2:
                i += 1
                continue

            if i + 2 < len(lines):
                name = line
                points_line = lines[i + 1]
                percent_line = lines[i + 2]
                status_line = lines[i + 3] if i + 3 < len(lines) else ""

                percent_match = re.search(r'(\d+)%', percent_line)
                if percent_match and "/" in points_line:
                    players.append({
                        "name": name,
                        "points": points_line,
                        "percent": int(percent_match.group(1)),
                        "percent_text": percent_line,
                        "status": status_line,
                    })
                    i += 4
                    continue

        i += 1

    print("\n===== AT RISK PLAYERS =====")
    for p in players[:10]:
        print(p)
    print("===========================\n")

    return players
@bot.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {bot.user}")


@tree.command(name="showpoints", description="Show a player's points from TB Clan Tools")
@app_commands.describe(user="The player name as shown in TB Clan Tools")
async def showpoints(interaction: discord.Interaction, user: str):
    await interaction.response.defer()

    try:
        stats = await fetch_member_stats(user)

        if not stats["points"]:
            await interaction.followup.send(
                f"I couldn't find points for **{user}**.\n"
                f"Page checked: {stats['url']}"
            )
            return

        await interaction.followup.send(
            f"**{user}** has **{stats['points']} points**.\n"
            f"{stats['url']}"
        )
    except Exception as e:
        await interaction.followup.send(f"Error fetching points: `{e}`")


@tree.command(name="showchests", description="Show a player's chest count from TB Clan Tools")
@app_commands.describe(user="The player name as shown in TB Clan Tools")
async def showchests(interaction: discord.Interaction, user: str):
    await interaction.response.defer()

    try:
        stats = await fetch_member_stats(user)

        if not stats["chests"]:
            await interaction.followup.send(
                f"I couldn't find chests for **{user}**.\n"
                f"Page checked: {stats['url']}"
            )
            return

        await interaction.followup.send(
            f"**{user}** has **{stats['chests']} chests**.\n"
            f"{stats['url']}"
        )
    except Exception as e:
        await interaction.followup.send(f"Error fetching chests: `{e}`")


@tree.command(name="showstats", description="Show a player's chest stats from TB Clan Tools")
@app_commands.describe(user="The player name as shown in TB Clan Tools")
async def showstats(interaction: discord.Interaction, user: str):
    await interaction.response.defer()

    try:
        stats = await fetch_member_stats(user)

        if not stats["found_anything"]:
            await interaction.followup.send(f"I couldn't find stats for **{user}**.")
            return

        points = stats["points"] or "Not found on player page"
        chests = stats["chests"] or "Not found"

        embed = discord.Embed(
            title=f"Stats for {user}",
            color=discord.Color.green()
        )

        embed.add_field(name="Points", value=points, inline=True)
        embed.add_field(name="Chests", value=chests, inline=True)

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"Error fetching stats: `{e}`")


@tree.command(name="weeklytargets", description="Show current weekly clan target progress")
async def weeklytargets(interaction: discord.Interaction):
    await interaction.response.defer()

    try:
        stats = await fetch_dashboard_targets()

        current_points = stats["current_points"] or "Not found"
        target_points = stats["target_points"] or "Not found"
        percent = stats["percent"] or "Not found"
        status = stats["status"] or "Not found"

        embed = discord.Embed(
            title="Clan Weekly Targets",
            color=discord.Color.purple()
        )

        embed.add_field(name="Current Points", value=current_points, inline=True)
        embed.add_field(name="Target Points", value=target_points, inline=True)
        embed.add_field(name="Completion", value=percent, inline=True)
        embed.add_field(name="Status", value=status, inline=False)

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"Error fetching weekly targets: `{e}`")

@tree.command(name="weeklyplayer", description="Show weekly target stats for one player")
@app_commands.describe(user="The player name as shown on the weekly targets dashboard")
async def weeklyplayer(interaction: discord.Interaction, user: str):
    await interaction.response.defer()

    try:
        stats = await fetch_weekly_player_stats(user)

        if not stats["found"]:
            await interaction.followup.send(f"I couldn't find weekly target stats for **{user}**.")
            return

        embed = discord.Embed(
            title=f"Weekly Target Stats for {user}",
            color=discord.Color.orange()
        )

        embed.add_field(name="Points", value=stats["points"] or "Not found", inline=False)
        embed.add_field(name="Chests", value=stats["chests"] or "Not found", inline=False)
        embed.add_field(name="Status", value=stats["status"] or "Not found", inline=False)
        embed.add_field(name="Completion", value=stats["percent"] or "Not found", inline=False)

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"Error fetching weekly player stats: `{e}`")

@tree.command(name="weeklytop", description="Show top weekly performers")
async def weeklytop(interaction: discord.Interaction):
    await interaction.response.defer()

    try:
        players = await fetch_weekly_progress_players()

        if not players:
            await interaction.followup.send("I couldn't find weekly progress players.")
            return

        players = [p for p in players if p["percent"] is not None]
        players.sort(key=lambda p: p["percent"], reverse=True)

        top_players = players[:5]

        embed = discord.Embed(
            title="Top Weekly Performers",
            color=discord.Color.gold()
        )

        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]

        for idx, player in enumerate(top_players):
            embed.add_field(
                name=f"{medals[idx]} {player['name']}",
                value=(
                    f"Points: {player['points']}\n"
                    f"Chests: {player['chests']}\n"
                    f"Status: {player['status']}\n"
                    f"Completion: {player['percent_text']}"
                ),
                inline=False
            )

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"Error fetching weekly top players: `{e}`")

@tree.command(name="weeklyrisk", description="Show at-risk players from the weekly targets dashboard")
async def weeklyrisk(interaction: discord.Interaction):
    await interaction.response.defer()

    try:
        players = await fetch_at_risk_players()

        if not players:
            await interaction.followup.send("I couldn't find any at-risk players.")
            return

        embed = discord.Embed(
            title="At-Risk Players",
            color=discord.Color.red()
        )

        for player in players[:10]:
            embed.add_field(
                name=f"⚠ {player['name']}",
                value=(
                    f"Points: {player['points']}\n"
                    f"Completion: {player['percent_text']}\n"
                    f"Status: {player['status']}"
                ),
                inline=False
            )

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"Error fetching at-risk players: `{e}`")
        
@tree.command(name="weeklybehind", description="Show players below 100% completion")
async def weeklybehind(interaction: discord.Interaction):
    await interaction.response.defer()

    try:
        players = await fetch_weekly_progress_players()

        if not players:
            await interaction.followup.send("I couldn't find weekly progress players.")
            return

        behind_players = [
            p for p in players
            if p["percent"] is not None and p["percent"] < 100
        ]

        behind_players.sort(key=lambda p: p["percent"])

        if not behind_players:
            await interaction.followup.send("Nobody is behind target right now.")
            return

        embed = discord.Embed(
            title="Players Behind Target",
            color=discord.Color.orange()
        )

        for player in behind_players[:10]:
            embed.add_field(
                name=f"{player['name']}",
                value=(
                    f"Points: {player['points']}\n"
                    f"Chests: {player['chests']}\n"
                    f"Status: {player['status']}\n"
                    f"Completion: {player['percent_text']}"
                ),
                inline=False
            )

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"Error fetching players behind target: `{e}`")

bot.run(DISCORD_TOKEN)