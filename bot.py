import os
import re
import io
import asyncio
import requests
import discord
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from discord import app_commands
from discord.ext import commands, tasks
from bs4 import BeautifulSoup
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TB_SLUG = "28xgk8liiv8o"
REPORT_CHANNEL_ID = 1482403704555573430

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
playwright_instance = None
browser_instance = None


async def start_browser():
    global playwright_instance, browser_instance

    if playwright_instance is None:
        playwright_instance = await async_playwright().start()

    if browser_instance is None or not browser_instance.is_connected():
        browser_instance = await playwright_instance.chromium.launch(headless=True)
        print("Shared Playwright browser started.")


async def ensure_browser():
    global playwright_instance, browser_instance

    if playwright_instance is None:
        playwright_instance = await async_playwright().start()

    if browser_instance is None or not browser_instance.is_connected():
        browser_instance = await playwright_instance.chromium.launch(headless=True)
        print("Shared Playwright browser restarted.")


async def get_page_text(url: str, *, wait_until: str = "domcontentloaded", timeout: int = 30000, extra_wait_ms: int = 1200) -> str:
    await ensure_browser()

    global browser_instance
    last_error = None

    for attempt in range(2):
        page = None
        try:
            page = await browser_instance.new_page()
            await page.goto(url, wait_until=wait_until, timeout=timeout)
            if extra_wait_ms:
                await page.wait_for_timeout(extra_wait_ms)
            return await page.locator("body").inner_text()
        except Exception as e:
            last_error = e
            print(f"get_page_text attempt {attempt + 1} failed for {url}: {e}")

            try:
                if page is not None:
                    await page.close()
            except:
                pass

            if attempt == 0:
                try:
                    if browser_instance is not None:
                        await browser_instance.close()
                except:
                    pass
                browser_instance = None
                await ensure_browser()
                continue

            raise
        finally:
            try:
                if page is not None:
                    await page.close()
            except:
                pass

    raise last_error


async def stop_browser():
    global playwright_instance, browser_instance

    if browser_instance is not None:
        await browser_instance.close()
        browser_instance = None

    if playwright_instance is not None:
        await playwright_instance.stop()
        playwright_instance = None

    print("Shared Playwright browser stopped.")


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
    text = await get_page_text(url, wait_until="domcontentloaded", timeout=30000, extra_wait_ms=1500)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    lower_lines = [line.lower() for line in lines]

    def value_before(label: str, max_lookback: int = 2):
        label = label.lower()
        for i, line in enumerate(lower_lines):
            if line == label:
                for j in range(1, max_lookback + 1):
                    if i - j >= 0:
                        candidate = lines[i - j].strip()
                        if candidate and candidate.lower() != label:
                            return candidate
        return None

    def pair_after(label: str, max_lookahead: int = 3):
        label = label.lower()
        for i, line in enumerate(lower_lines):
            if line == label:
                first = None
                second = None
                k = 1
                while i + k < len(lines) and k <= max_lookahead + 2:
                    candidate = lines[i + k].strip()
                    if candidate:
                        if first is None:
                            first = candidate
                        elif second is None:
                            second = candidate
                            break
                    k += 1
                return first, second
        return None, None

    total_chests = value_before("Total Chests")
    total_score = value_before("Total Score")
    active_days = value_before("Active Days")
    daily_average = value_before("Daily Average")

    weekly_change_value, weekly_change_sub = pair_after("Weekly Change")
    thirty_day_chests_value, thirty_day_chests_sub = pair_after("30-Day Chests")
    current_streak_value, current_streak_sub = pair_after("Current Streak")
    best_streak_value, best_streak_sub = pair_after("Best Streak")
    rank_value, rank_sub = pair_after("Rank (Chests)")
    vs_clan_avg_value, vs_clan_avg_sub = pair_after("vs Clan Avg")
    best_day_value, best_day_sub = pair_after("Best Day")
    consistency_value, consistency_sub = pair_after("Consistency")

    found_anything = any([
        total_chests, total_score, active_days, daily_average,
        weekly_change_value, thirty_day_chests_value, current_streak_value,
        best_streak_value, rank_value, vs_clan_avg_value, best_day_value,
        consistency_value
    ])

    return {
        "member": member_name,
        "url": url,
        "found_anything": found_anything,

        "total_chests": total_chests,
        "total_score": total_score,
        "active_days": active_days,
        "daily_average": daily_average,

        "weekly_change_value": weekly_change_value,
        "weekly_change_sub": weekly_change_sub,

        "thirty_day_chests_value": thirty_day_chests_value,
        "thirty_day_chests_sub": thirty_day_chests_sub,

        "current_streak_value": current_streak_value,
        "current_streak_sub": current_streak_sub,

        "best_streak_value": best_streak_value,
        "best_streak_sub": best_streak_sub,

        "rank_value": rank_value,
        "rank_sub": rank_sub,

        "vs_clan_avg_value": vs_clan_avg_value,
        "vs_clan_avg_sub": vs_clan_avg_sub,

        "best_day_value": best_day_value,
        "best_day_sub": best_day_sub,

        "consistency_value": consistency_value,
        "consistency_sub": consistency_sub,
    }
async def fetch_dashboard_targets() -> dict:
    url = f"https://tbclantools.com/p/{TB_SLUG}"
    text = await get_page_text(url, wait_until="networkidle", timeout=30000, extra_wait_ms=1200)

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
    text = await get_page_text(url, wait_until="networkidle", timeout=30000, extra_wait_ms=1200)

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
    text = await get_page_text(url, wait_until="networkidle", timeout=30000, extra_wait_ms=1200)

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
async def build_auto_report_embed():
    weekly_players = await fetch_weekly_progress_players()
    risk_players = await fetch_at_risk_players()

    weekly_players = [p for p in weekly_players if p.get("percent") is not None]
    weekly_players.sort(key=lambda p: p["percent"], reverse=True)

    risk_players = [p for p in risk_players if p.get("percent") is not None]
    risk_players.sort(key=lambda p: p["percent"])

    top_10 = weekly_players[:10]
    risk_10 = risk_players[:10]

    embed = discord.Embed(
        title="Clan 3-Day Progress Report",
        description="Automatic weekly progress update",
        color=discord.Color.blue()
    )

    if top_10:
        top_text = "\n".join(
            f"**{i+1}. {p['name']}** — {p['percent_text']}"
            for i, p in enumerate(top_10)
        )
    else:
        top_text = "No weekly player data found."

    if risk_10:
        risk_text = "\n".join(
            f"**{i+1}. {p['name']}** — {p['percent_text']}"
            for i, p in enumerate(risk_10)
        )
    else:
        risk_text = "No at-risk player data found."

    embed.add_field(name="Top 10 Weekly Users", value=top_text[:1024], inline=False)
    embed.add_field(name="Top 10 At-Risk Users", value=risk_text[:1024], inline=False)

    return embed
def normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


async def fetch_roster_names() -> list[str]:
    players = await fetch_weekly_progress_players()

    names: list[str] = []
    seen = set()

    for p in players:
        name = p.get("name", "").strip()
        if not name:
            continue

        key = normalize_name(name)
        if key in seen:
            continue

        seen.add(key)
        names.append(name)

    return names


async def member_has_chest(member_name: str, chest_key: str) -> bool:
    await ensure_browser()

    global browser_instance
    url = get_member_url(member_name)
    page = await browser_instance.new_page()

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        print(f"\n--- CHECKING {member_name} for {chest_key} ---")
        await page.wait_for_timeout(1200)

        # Try closing any popup/modal if present
        close_button = page.locator("button").filter(has_text="Close")
        if await close_button.count() > 0:
            try:
                await close_button.first.click(timeout=1000)
                await page.wait_for_timeout(300)
            except:
                pass

        # Fallback: press Escape in case a modal is open
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(200)
        except:
            pass

        # Find the Chest History search box by scrolling until it appears
        search_box = None

        for _ in range(80):
            exact_box = page.locator("input[placeholder='Search chests...']")
            if await exact_box.count() > 0:
                try:
                    if await exact_box.first.is_visible():
                        search_box = exact_box.first
                        break
                except:
                    pass

            fallback_box = page.locator("input[placeholder*='Search']")
            if await fallback_box.count() > 0:
                try:
                    if await fallback_box.first.is_visible():
                        search_box = fallback_box.first
                        break
                except:
                    pass

            await page.mouse.wheel(0, 2500)
            await page.wait_for_timeout(700)

        if search_box is None:
            print(f"Search box not found for {member_name} - using fallback scan")

            target_key = chest_key.strip().lower()
            last_snapshot = ""
            unchanged_rounds = 0

            for _ in range(40):
                body_text = await page.locator("body").inner_text()
                lines = [line.strip().lower() for line in body_text.splitlines() if line.strip()]

                if target_key in lines:
                    print(f"Fallback found {target_key} for {member_name}")
                    return True

                snapshot = "\n".join(lines[-250:])
                if snapshot == last_snapshot:
                    unchanged_rounds += 1
                else:
                    unchanged_rounds = 0
                    last_snapshot = snapshot

                if unchanged_rounds >= 4:
                    break

                await page.mouse.wheel(0, 2500)
                await page.wait_for_timeout(600)

            return False

        print(f"Search box FOUND for {member_name}")

        # Type into the real search box so the site's filter actually runs
        await search_box.focus()
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await search_box.type(chest_key, delay=40)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(1200)

        # Give filtered results time to load in
        for _ in range(12):
            body_text = await page.locator("body").inner_text()
            body_lower = body_text.lower()

            if chest_key.lower() in body_lower:
                break

            if "loading more chests" in body_lower:
                await page.mouse.wheel(0, 1800)
                await page.wait_for_timeout(700)
            else:
                await page.wait_for_timeout(500)

        body_text = await page.locator("body").inner_text()
        lines = [line.strip().lower() for line in body_text.splitlines() if line.strip()]

        print(f"Found {len(lines)} visible lines for {member_name}")
        for line in lines[-80:]:
            print(repr(line))

        target_key = chest_key.strip().lower()
        print(f"Exact target key: {target_key}")
        print(f"Exact match result: {target_key in lines}")

        return target_key in lines

    except Exception as e:
        print(f"member_has_chest error for {member_name}: {e}")
        return False

    finally:
        await page.close()


async def find_members_missing_chest(chest_key: str) -> tuple[list[str], list[str]]:
    roster = await fetch_roster_names()

    has_chest: list[str] = []
    missing: list[str] = []

    for name in roster:
        try:
            found = await member_has_chest(name, chest_key)
            if found:
                has_chest.append(name)
            else:
                missing.append(name)
        except Exception as e:
            print(f"Error checking {name} for {chest_key}: {e}")
            missing.append(name)

    return has_chest, missing

async def check_member_for_chest(name: str, chest: str, semaphore: asyncio.Semaphore):
    async with semaphore:
        found = await member_has_chest(name, chest)
        return name, found
    
async def recheck_member_for_chest(name: str, chest: str):
    found = await member_has_chest(name, chest)
    return name, found

@bot.event
async def on_ready():
    await start_browser()
    await tree.sync()
    print(f"Logged in as {bot.user}")

@tree.command(name="showtotalpoints", description="Show a player's points from TB Clan Tools")
@app_commands.describe(user="The player name as shown in TB Clan Tools")
async def showpoints(interaction: discord.Interaction, user: str):
    await interaction.response.defer()

    try:
        stats = await fetch_member_stats(user)

        if not stats["found_anything"] or not stats["total_score"]:
            await interaction.followup.send(
                f"I couldn't find points for **{user}**.\n"
                f"Page checked: {stats['url']}"
            )
            return

        await interaction.followup.send(
            f"**{user}** has **{stats['total_score']} total score**.\n"
            f"{stats['url']}"
        )

    except Exception as e:
        print(f"Error fetching points: {e}")
        await interaction.followup.send("Error fetching points. Check Railway logs.")


@tree.command(name="showtotalchests", description="Show a player's total chest count from TB Clan Tools")
@app_commands.describe(user="The player name as shown in TB Clan Tools")
async def showchests(interaction: discord.Interaction, user: str):
    await interaction.response.defer()

    try:
        stats = await fetch_member_stats(user)

        if not stats["found_anything"] or not stats["total_chests"]:
            await interaction.followup.send(
                f"I couldn't find chests for **{user}**.\n"
                f"Page checked: {stats['url']}"
            )
            return

        await interaction.followup.send(
            f"**{user}** has **{stats['total_chests']} total chests**.\n"
            f"{stats['url']}"
        )

    except Exception as e:
        print(f"Error fetching chests: {e}")
        await interaction.followup.send("Error fetching chests. Check Railway logs.")


@tree.command(name="showstats", description="Show a player's full stats from TB Clan Tools")
@app_commands.describe(user="The player name as shown in TB Clan Tools")
async def showstats(interaction: discord.Interaction, user: str):
    await interaction.response.defer()

    try:
        stats = await fetch_member_stats(user)

        if not stats["found_anything"]:
            await interaction.followup.send(f"I couldn't find stats for **{user}**.")
            return

        embed = discord.Embed(
            title=f"Stats for {user}",
            color=discord.Color.green(),
            url=stats["url"]
        )

        embed.add_field(
            name="Overview",
            value=(
                f"**Total Chests:** {stats['total_chests'] or 'Not found'}\n"
                f"**Total Score:** {stats['total_score'] or 'Not found'}\n"
                f"**Active Days:** {stats['active_days'] or 'Not found'}\n"
                f"**Daily Average:** {stats['daily_average'] or 'Not found'}"
            ),
            inline=False
        )

        embed.add_field(
            name="Weekly Change",
            value=(
                f"**Value:** {stats['weekly_change_value'] or 'Not found'}\n"
                f"**Detail:** {stats['weekly_change_sub'] or 'Not found'}"
            ),
            inline=True
        )

        embed.add_field(
            name="30-Day Chests",
            value=(
                f"**Value:** {stats['thirty_day_chests_value'] or 'Not found'}\n"
                f"**Detail:** {stats['thirty_day_chests_sub'] or 'Not found'}"
            ),
            inline=True
        )

        embed.add_field(
            name="Current Streak",
            value=(
                f"**Value:** {stats['current_streak_value'] or 'Not found'}\n"
                f"**Detail:** {stats['current_streak_sub'] or 'Not found'}"
            ),
            inline=True
        )

        embed.add_field(
            name="Best Streak",
            value=(
                f"**Value:** {stats['best_streak_value'] or 'Not found'}\n"
                f"**Detail:** {stats['best_streak_sub'] or 'Not found'}"
            ),
            inline=True
        )

        embed.add_field(
            name="Rank",
            value=(
                f"**Value:** {stats['rank_value'] or 'Not found'}\n"
                f"**Detail:** {stats['rank_sub'] or 'Not found'}"
            ),
            inline=True
        )

        embed.add_field(
            name="vs Clan Average",
            value=(
                f"**Value:** {stats['vs_clan_avg_value'] or 'Not found'}\n"
                f"**Detail:** {stats['vs_clan_avg_sub'] or 'Not found'}"
            ),
            inline=True
        )

        embed.add_field(
            name="Best Day",
            value=(
                f"**Value:** {stats['best_day_value'] or 'Not found'}\n"
                f"**Detail:** {stats['best_day_sub'] or 'Not found'}"
            ),
            inline=True
        )

        embed.add_field(
            name="Consistency",
            value=(
                f"**Value:** {stats['consistency_value'] or 'Not found'}\n"
                f"**Detail:** {stats['consistency_sub'] or 'Not found'}"
            ),
            inline=True
        )

        await interaction.followup.send(embed=embed)

    except Exception as e:
        print(f"Error fetching full stats: {e}")
        await interaction.followup.send("Error fetching stats. Check Railway logs.")


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
        print(f"Error fetching points: {e}")
        await interaction.followup.send("Error fetching points. Check Railway logs.")

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
            title=f"Weekly Target Stats for {stats['member']}",
            color=discord.Color.orange()
        )

        embed.add_field(name="Points", value=stats["points"] or "Not found", inline=False)
        embed.add_field(name="Chests", value=stats["chests"] or "Not found", inline=False)
        embed.add_field(name="Status", value=stats["status"] or "Not found", inline=False)
        embed.add_field(name="Completion", value=stats["percent"] or "Not found", inline=False)

        if stats.get("duplicate"):
            embed.set_footer(text="Duplicate player names detected on the website. Showing the first exact match found.")

        await interaction.followup.send(embed=embed)

    except Exception as e:
        print(f"Error fetching points: {e}")
        await interaction.followup.send("Error fetching points. Check Railway logs.")

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
        print(f"Error fetching points: {e}")
        await interaction.followup.send("Error fetching points. Check Railway logs.")

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
        print(f"Error fetching points: {e}")
        await interaction.followup.send("Error fetching points. Check Railway logs.")
        
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
        print(f"Error fetching points: {e}")
        await interaction.followup.send("Error fetching points. Check Railway logs.")

@tree.command(name="weeklyreport", description="Post the current automatic report")
async def weeklyreport(interaction: discord.Interaction):
    await interaction.response.defer()

    try:
        embed = await build_auto_report_embed()
        await interaction.followup.send(embed=embed)

    except Exception as e:
        print(f"weeklyreport error: {e}")
        await interaction.followup.send("Error generating report. Check Railway logs.")

@tree.command(name="missingchest", description="Show members missing a specific chest")
@app_commands.describe(chest="Chest source key, for example jormungandr_shop")
async def missingchest(interaction: discord.Interaction, chest: str):
    await interaction.response.defer()

    try:
        roster = await fetch_roster_names()
        total_members = len(roster)

        has_chest: list[str] = []
        missing: list[str] = []

        semaphore = asyncio.Semaphore(2)

        tasks_list = [
            check_member_for_chest(name, chest, semaphore)
            for name in roster
        ]

        completed = 0

        for coro in asyncio.as_completed(tasks_list):
            name, found = await coro
            completed += 1

            if found:
                has_chest.append(name)
            else:
                missing.append(name)

        # Recheck only the initially-missing players to reduce false negatives
        if missing:
            print(f"Rechecking {len(missing)} initially-missing players...")

            retry_missing = []
            retry_has_chest = []

            for name in missing:
                try:
                    result_name, found = await recheck_member_for_chest(name, chest)
                    if found:
                        retry_has_chest.append(result_name)
                    else:
                        retry_missing.append(result_name)
                except Exception as e:
                    print(f"Recheck failed for {name}: {e}")
                    retry_missing.append(name)

            # Move re-found players out of missing list
            has_chest.extend(retry_has_chest)
            missing = retry_missing

        has_chest = sorted(set(has_chest), key=str.lower)
        missing = sorted(set(missing), key=str.lower)
        embed = discord.Embed(
            title=f"Missing Chest Report: {chest}",
            color=discord.Color.orange()
        )
        embed.add_field(name="Total Members", value=str(total_members), inline=True)
        embed.add_field(name="Have Chest", value=str(len(has_chest)), inline=True)
        embed.add_field(name="Missing Chest", value=str(len(missing)), inline=True)

        preview = "\n".join(f"- {name}" for name in missing[:20]) or "Nobody missing this chest."
        embed.add_field(
            name="Missing Members (first 20)",
            value=preview[:1024],
            inline=False
        )

        await interaction.followup.send(embed=embed)

        if missing:
            txt = "Members missing chest: " + chest + "\n\n" + "\n".join(missing)
            file_obj = io.BytesIO(txt.encode("utf-8"))
            await interaction.followup.send(
                file=discord.File(file_obj, filename=f"missing_{chest}.txt")
            )

    except Exception as e:
        print(f"missingchest error: {e}")
        await interaction.followup.send("Error running missingchest. Check Railway logs.")
    

bot.run(DISCORD_TOKEN)