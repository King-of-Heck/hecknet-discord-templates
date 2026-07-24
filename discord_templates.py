"""
Multi-channel Discord printer.

Watches several Discord channels and prints each one with its own receipt
template - a work-order layout for To-Do, a memorandum layout for Notes, and
plain text for General.

Two scheduling commands are supported on the To-Do channel:

    !timer 10 minutes            print a reminder after a delay
    !delay (DDMMYY HH:MM) text   print at a specific date and time
    !delay 1 week text           print after a relative duration

Pending delays survive a restart; anything that came due while the bot was
down prints on startup.

    python discord_templates.py
"""

import asyncio
import io
import json
import uuid
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime, date

import requests
import discord
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageWin
import win32ui


def work_order_number(ts: datetime) -> str:
    """Returns a work order number from the message timestamp: DDMMYYHHmm."""
    return ts.strftime("%d%m%y%H%M")


DISCORD_TOKEN  = "YOUR_BOT_TOKEN_HERE"          # paste your new bot token here

PRINTER_NAME   = "XP-80C"
FONT_PATH      = "cour.ttf"
FONT_BOLD      = "courbd.ttf"

MAX_MSG_LENGTH = 2000
ALLOWED_USERS  = []                             # list of user IDs to whitelist,

# Channel  template mapping
# Template names: "task" | "notes" | "plain"

CHANNEL_CONFIG = {
    0: "task",    # To-Do
    0: "notes",   # Notes
    0: "plain",   # General Printer
}

TIMER_CHANNEL_ID = 0   # heck-timer channel


DELAYS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pending_delays.json")

def _load_delays() -> dict:
    if os.path.exists(DELAYS_FILE):
        try:
            with open(DELAYS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_delays(delays: dict):
    with open(DELAYS_FILE, "w", encoding="utf-8") as f:
        json.dump(delays, f, indent=2)

def _add_delay(delay_id: str, fire_at: datetime, body: str, channel_id: int):
    delays = _load_delays()
    delays[delay_id] = {
        "fire_at":    fire_at.isoformat(),
        "body":       body,
        "channel_id": channel_id,
    }
    _save_delays(delays)

def _remove_delay(delay_id: str):
    delays = _load_delays()
    delays.pop(delay_id, None)
    _save_delays(delays)


PRINTER_DPI  = 203
PAPER_MM     = 80
PAPER_PX     = int(PAPER_MM / 25.4 * PRINTER_DPI)   # ≈ 638 px
MARGIN_PX    = 10
TEXT_PX      = PAPER_PX - 2 * MARGIN_PX
FONT_SIZE       = 36
SKULL_FONT_SIZE = 24       # skull size in points — adjust independently of header text
RENDER_SCALE    = 4


def load_font(bold=False, size=None):
    size = size or FONT_SIZE
    path = FONT_BOLD if bold else FONT_PATH
    try:
        return ImageFont.truetype(path, size * RENDER_SCALE)
    except OSError:
        return ImageFont.load_default()

_SKULL_FONT_CANDIDATES = [
    "seguiemj.ttf",                     # Segoe UI Emoji — ships with Windows 10+
    "C:/Windows/Fonts/seguiemj.ttf",    # explicit path fallback
    "seguisym.ttf",                     # Segoe UI Symbol — older fallback
]

def load_skull_font(size=None):
    size = size or SKULL_FONT_SIZE
    for path in _SKULL_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size * RENDER_SCALE)
        except OSError:
            continue
    return load_font(bold=True, size=size)   # last resort: Courier (will box)

# Shifts skulls DOWN relative to the heading text (at 4x scale, so 4px = 1 printed px).
# Increase to push skulls lower; decrease toward 0 if they overshoot.
SKULL_Y_OFFSET = 40

def draw_skull_header(draw, text: str, font_text, font_skull,
                      paper_w: int, y: int):
    """
    Render  💀  <text>  💀  centred on the line, using font_skull for the glyphs
    and font_text for the label.  All coords are at hi-res (4x) scale.
    SKULL_Y_OFFSET shifts the skulls DOWN relative to the text baseline so they
    appear vertically centred alongside the heading rather than floating above it.
    """
    SKULL = "\U0001F480"
    gap   = int(font_text.size * 0.4)

    skull_w = int(font_skull.getlength(SKULL))
    text_w  = int(font_text.getlength(text))
    total_w = skull_w + gap + text_w + gap + skull_w

    x = (paper_w - total_w) // 2
    draw.text((x, y + SKULL_Y_OFFSET), SKULL, font=font_skull, fill="black")
    x += skull_w + gap
    draw.text((x, y), text, font=font_text, fill="black")
    x += text_w + gap
    draw.text((x, y + SKULL_Y_OFFSET), SKULL, font=font_skull, fill="black")


def fetch_and_dither_image(url: str, width_px: int = TEXT_PX) -> Image.Image:
    """Download, resize to paper width, Floyd-Steinberg dither to B&W."""
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content)).convert("RGB")
    w, h = img.size
    img = img.resize((width_px, int(h * width_px / w)), Image.LANCZOS)
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(1.8)
    img = ImageEnhance.Sharpness(img).enhance(2.0)
    img = img.convert("1", dither=Image.FLOYDSTEINBERG)
    return img.convert("RGB")


def word_wrap(text: str, font, max_width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        candidate = (line + " " + word).strip()
        if font.getlength(candidate) <= max_width:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines or [""]


def _render_ops(ops, paper_w, margin, line_h, top_pad: int = 0) -> tuple[Image.Image, int]:
    """Render a list of (text, font, align) ops at 4× scale. Returns (image, y).
    top_pad adds extra blank pixels above the first line (at hi-res scale) so
    tall glyphs like emoji don't clip at the top of the canvas."""
    S = RENDER_SCALE
    total_h = len(ops) * line_h + line_h * 2 + top_pad
    hi_res  = Image.new("RGB", (paper_w, total_h), "white")
    draw    = ImageDraw.Draw(hi_res)
    y       = margin // 2 + top_pad
    for text, font, align in ops:
        if align == "center":
            bbox = font.getbbox(text)
            tw = bbox[2] - bbox[0]
            x  = (paper_w - tw) / 2 - bbox[0]
        else:
            x = margin
        draw.text((x, y), text, font=font, fill="black")
        y += line_h
    return hi_res, y


def _downsample(hi_res: Image.Image, out_w: int, y_hi: int) -> Image.Image:
    S      = RENDER_SCALE
    out_h  = int(hi_res.height / S)
    output = hi_res.resize((out_w, out_h), Image.LANCZOS)
    output = ImageEnhance.Contrast(output).enhance(2.5).convert("L").convert("RGB")
    return output.crop((0, 0, out_w, int(y_hi / S) + 4))


def _attach_images(base: Image.Image, attachment_imgs: list) -> Image.Image:
    if not attachment_imgs:
        return base
    parts = [base]
    for img in attachment_imgs:
        parts.append(Image.new("RGB", (PAPER_PX, 6), "white"))
        parts.append(img)
    total_h = sum(p.size[1] for p in parts)
    combined = Image.new("RGB", (PAPER_PX, total_h), "white")
    py = 0
    for p in parts:
        combined.paste(p, (0, py))
        py += p.size[1]
    return combined


def build_task(author: str, content: str, timestamp: datetime,
               attachment_imgs: list) -> Image.Image:
    S       = RENDER_SCALE
    paper_w = PAPER_PX * S
    margin  = MARGIN_PX * S
    text_w  = TEXT_PX * S
    line_h  = (FONT_SIZE + 6) * S

    font_n     = load_font(bold=False)
    font_b     = load_font(bold=True)
    font_sm    = load_font(bold=False, size=FONT_SIZE - 8)
    font_skull = load_skull_font(size=SKULL_FONT_SIZE)
    DIVIDER    = "─" * int(text_w / (FONT_SIZE * S * 0.62))

    wo_number = work_order_number(timestamp)

    ops = []

    def add(text, bold=False, align="left", small=False):
        ops.append((text, font_sm if small else (font_b if bold else font_n), align))

    def div():
        add(DIVIDER)

    add("",   align="center")                              # skull header placeholder
    div()
    add(f"Work Order {wo_number}", bold=True, align="center")
    div()

    if content.strip():
        for paragraph in content.splitlines():
            if not paragraph.strip():
                add(" ")
                continue
            for line in word_wrap(paragraph, font_n, text_w):
                add(line)
        div()

    hi_res, y = _render_ops(ops, paper_w, margin, line_h, top_pad=SKULL_Y_OFFSET)

    draw = ImageDraw.Draw(hi_res)
    draw_skull_header(draw, "HeckNet", font_b, font_skull,
                      paper_w, margin // 2 + SKULL_Y_OFFSET)

    output = _downsample(hi_res, PAPER_PX, y)
    return _attach_images(output, attachment_imgs)


def build_notes(author: str, content: str, timestamp: datetime,
                attachment_imgs: list) -> Image.Image:
    S       = RENDER_SCALE
    paper_w = PAPER_PX * S
    margin  = MARGIN_PX * S
    text_w  = TEXT_PX * S
    line_h  = (FONT_SIZE + 6) * S

    font_n     = load_font(bold=False)
    font_b     = load_font(bold=True)
    font_sm    = load_font(bold=False, size=FONT_SIZE - 8)
    font_skull = load_skull_font(size=SKULL_FONT_SIZE)
    DIVIDER    = "─" * int(text_w / (FONT_SIZE * S * 0.62))

    ops = []

    def add(text, bold=False, align="left", small=False):
        ops.append((text, font_sm if small else (font_b if bold else font_n), align))

    def div():
        add(DIVIDER)

    # Layout:
    # HeckNet

    add("",   align="center")                              # skull header placeholder
    div()
    add("Memorandum", bold=True, align="center")
    add(timestamp.strftime("%A, %B %d %Y"), align="center", small=True)
    add(timestamp.strftime("@ %H:%M"),      align="center", small=True)
    div()

    if content.strip():
        for paragraph in content.splitlines():
            if not paragraph.strip():
                add(" ")
                continue
            for line in word_wrap(paragraph, font_n, text_w):
                add(line)
        div()

    hi_res, y = _render_ops(ops, paper_w, margin, line_h, top_pad=SKULL_Y_OFFSET)

    draw = ImageDraw.Draw(hi_res)
    draw_skull_header(draw, "HeckNet", font_b, font_skull,
                      paper_w, margin // 2 + SKULL_Y_OFFSET)

    output = _downsample(hi_res, PAPER_PX, y)
    return _attach_images(output, attachment_imgs)


def build_plain(author: str, content: str, timestamp: datetime,
                attachment_imgs: list) -> Image.Image:
    S       = RENDER_SCALE
    paper_w = PAPER_PX * S
    margin  = MARGIN_PX * S
    text_w  = TEXT_PX * S
    line_h  = (FONT_SIZE + 6) * S

    font_n  = load_font(bold=False)
    font_b  = load_font(bold=True)

    ops = []

    def add(text, bold=False, align="left"):
        ops.append((text, font_b if bold else font_n, align))

    if content.strip():
        for paragraph in content.splitlines():
            if not paragraph.strip():
                add(" ")
                continue
            for line in word_wrap(paragraph, font_n, text_w):
                add(line)
    else:
        add(" ")   # need at least one op so canvas has height

    hi_res, y = _render_ops(ops, paper_w, margin, line_h)
    output = _downsample(hi_res, PAPER_PX, y)
    return _attach_images(output, attachment_imgs)


def build_timer(duration_str: str, started_at: datetime, fired_at: datetime) -> Image.Image:
    """Prints when a !timer fires. Same HeckNet skull header, then Time's Up."""
    S       = RENDER_SCALE
    paper_w = PAPER_PX * S
    margin  = MARGIN_PX * S
    text_w  = TEXT_PX * S
    line_h  = (FONT_SIZE + 6) * S

    font_n     = load_font(bold=False)
    font_b     = load_font(bold=True)
    font_sm    = load_font(bold=False, size=FONT_SIZE - 8)
    font_skull = load_skull_font(size=SKULL_FONT_SIZE)
    DIVIDER    = "─" * int(text_w / (FONT_SIZE * S * 0.62))

    time_range = (f"{started_at.strftime('%H:%M')}"
                  f"-{fired_at.strftime('%H:%M')}")

    ops = []

    def add(text, bold=False, align="left", small=False):
        ops.append((text, font_sm if small else (font_b if bold else font_n), align))

    def div():
        add(DIVIDER, align="center")

    add("",                                    align="center")   # skull placeholder
    div()
    add("Time's Up Bucko!",   bold=True,       align="center")
    add(f"Timer: {duration_str}",              align="center", small=True)
    div()
    add(time_range,                            align="center", small=True)
    div()

    hi_res, y = _render_ops(ops, paper_w, margin, line_h, top_pad=SKULL_Y_OFFSET)
    draw = ImageDraw.Draw(hi_res)
    draw_skull_header(draw, "HeckNet", font_b, font_skull,
                      paper_w, margin // 2 + SKULL_Y_OFFSET)

    return _downsample(hi_res, PAPER_PX, y)


import re as _re

_TIMER_RE = _re.compile(
    r"!timer\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b",
    _re.IGNORECASE
)

def parse_timer_seconds(text: str):
    """
    Parse '!timer N unit' from message text.
    Returns (seconds: float, display_str: str) or None if no match.
    """
    m = _TIMER_RE.search(text)
    if not m:
        return None
    amount = float(m.group(1))
    unit   = m.group(2).lower()
    if unit.startswith("h"):
        seconds = amount * 3600
        label   = f"{amount:g} hour{'s' if amount != 1 else ''}"
    elif unit.startswith("m"):
        seconds = amount * 60
        label   = f"{amount:g} minute{'s' if amount != 1 else ''}"
    else:
        seconds = amount
        label   = f"{amount:g} second{'s' if amount != 1 else ''}"
    return seconds, label


_DELAY_ABS_RE = _re.compile(
    r"^!delay\s+\((\d{2})(\d{2})(\d{2})\s+(\d{2}):(\d{2})\)\s+(.+)$",
    _re.IGNORECASE | _re.DOTALL
)

_DELAY_REL_RE = _re.compile(
    r"^!delay\s+(\d+(?:\.\d+)?)\s*(months?|weeks?|days?|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\s+(.+)$",
    _re.IGNORECASE | _re.DOTALL
)

def parse_delay(text: str):
    """
    Parse !delay in two formats:
      Absolute: !delay (DDMMYY HH:MM) message
      Relative: !delay N unit message
                units: months/weeks/days/hours/minutes/seconds
    Returns (fire_at: datetime, message: str, label: str) or None if no match.
    """
    from datetime import timedelta

    m = _DELAY_ABS_RE.match(text.strip())
    if m:
        dd, mo, yy, hh, mm, body = m.groups()
        try:
            fire_at = datetime.strptime(f"{dd}{mo}{yy} {hh}:{mm}", "%d%m%y %H:%M")
            label = fire_at.strftime("%d %b %Y %H:%M")
            return fire_at, body.strip(), label
        except ValueError:
            return None

    m = _DELAY_REL_RE.match(text.strip())
    if m:
        amount_str, unit, body = m.groups()
        amount = float(amount_str)
        unit   = unit.lower()

        if unit.startswith("mo"):
            delta   = timedelta(days=amount * 30.44)
            label   = f"{amount:g} month{'s' if amount != 1 else ''}"
        elif unit.startswith("w"):
            delta   = timedelta(weeks=amount)
            label   = f"{amount:g} week{'s' if amount != 1 else ''}"
        elif unit.startswith("d"):
            delta   = timedelta(days=amount)
            label   = f"{amount:g} day{'s' if amount != 1 else ''}"
        elif unit.startswith("h"):
            delta   = timedelta(hours=amount)
            label   = f"{amount:g} hour{'s' if amount != 1 else ''}"
        elif unit.startswith("m"):
            delta   = timedelta(minutes=amount)
            label   = f"{amount:g} minute{'s' if amount != 1 else ''}"
        else:
            delta   = timedelta(seconds=amount)
            label   = f"{amount:g} second{'s' if amount != 1 else ''}"

        fire_at = datetime.now() + delta
        return fire_at, body.strip(), label

    return None

BUILDERS = {
    "task":  build_task,
    "notes": build_notes,
    "plain": build_plain,
}

def build_receipt(template: str, author: str, content: str,
                  timestamp: datetime, attachment_imgs: list) -> Image.Image:
    builder = BUILDERS.get(template, build_plain)
    return builder(author, content, timestamp, attachment_imgs)


def send_to_printer(img: Image.Image):
    hdc = win32ui.CreateDC()
    hdc.CreatePrinterDC(PRINTER_NAME)
    pw = hdc.GetDeviceCaps(110)
    if img.width != pw:
        img = img.resize((pw, int(img.height * pw / img.width)), Image.LANCZOS)
    hdc.StartDoc("Template Receipt")
    hdc.StartPage()
    ImageWin.Dib(img).draw(hdc.GetHandleOutput(), (0, 0, img.width, img.height))
    hdc.EndPage()
    hdc.EndDoc()
    hdc.DeleteDC()


def print_receipt(template, author, content, timestamp, attachment_imgs):
    send_to_printer(build_receipt(template, author, content, timestamp, attachment_imgs))


async def _run_delay(delay_id: str, seconds_until: float,
                     fire_at: datetime, body: str, channel_id: int):
    """Wait then print the delayed Work Order and post to Discord."""
    try:
        await asyncio.sleep(seconds_until)
        print_at = datetime.now().astimezone()
        print(f"Delayed print firing: '{body[:50]}'")

        loop = asyncio.get_running_loop()

        try:
            def print_it():
                print_receipt("task", "", body, print_at, [])
            await loop.run_in_executor(None, print_it)
            print(f"Delayed receipt printed.")
        except Exception as e:
            print(f"Delayed print error: {e}")

        try:
            channel = client.get_channel(channel_id)
            if channel:
                await channel.send(f"🕐 **Reminder:** {body}")
                print(f"Discord reminder sent.")
            else:
                print(f"Could not find channel {channel_id} to send reminder.")
        except Exception as e:
            print(f"Discord notify error: {e}")

        _remove_delay(delay_id)

    except asyncio.CancelledError:
        print(f"Delay task cancelled for: '{body[:50]}'")
    except Exception as e:
        print(f"Unexpected error in delay task: {e}")


intents = discord.Intents.default()
intents.message_content = True
client  = discord.Client(intents=intents)

SUPPORTED_IMG_TYPES = (".jpg", ".jpeg", ".png", ".gif", ".webp")

@client.event
async def on_ready():
    watching = ", ".join(str(cid) for cid in CHANNEL_CONFIG)
    print(f" Bot ready: {client.user}")
    print(f"   Watching channels: {watching}")

    delays = _load_delays()
    if delays:
        print(f"Reloading {len(delays)} pending delay(s)...")
    for delay_id, entry in list(delays.items()):
        fire_at   = datetime.fromisoformat(entry["fire_at"])
        body      = entry["body"]
        channel_id = entry["channel_id"]
        seconds_until = (fire_at - datetime.now()).total_seconds()
        if seconds_until <= 0:
            print(f"Missed delay '{body[:40]}' — firing now")
            seconds_until = 0
        else:
            print(f"Rescheduled '{body[:40]}' in {seconds_until/60:.0f} min")
        asyncio.create_task(_run_delay(delay_id, seconds_until, fire_at, body, channel_id))

@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return
    if ALLOWED_USERS and message.author.id not in ALLOWED_USERS:
        return

    if TIMER_CHANNEL_ID and message.channel.id == TIMER_CHANNEL_ID:
        result = parse_timer_seconds(message.content)
        if result is None:
            await message.add_reaction("❓")
            await message.reply(
                "Usage: `!timer 10 minutes` — supports minutes/hours/seconds",
                delete_after=15
            )
            return
        seconds, label = result
        await message.add_reaction("⏱️")
        print(f"⏱  Timer set: {label} ({seconds:.0f}s)")
        started_at = datetime.now().astimezone()

        async def fire_timer():
            await asyncio.sleep(seconds)
            fired_at = datetime.now().astimezone()
            print(f"⏱  Timer fired: {label}")
            try:
                def print_it():
                    send_to_printer(build_timer(label, started_at, fired_at))
                await asyncio.get_running_loop().run_in_executor(None, print_it)
            except Exception as e:
                print(f"Timer print error: {e}")

        asyncio.create_task(fire_timer())
        return

    if message.channel.id not in CHANNEL_CONFIG:
        return

    template = CHANNEL_CONFIG[message.channel.id]
    content  = message.content

    if template == "task" and content.strip().lower().startswith("!delay"):
        result = parse_delay(content)
        if result is None:
            await message.add_reaction("❓")
            await message.reply(
                "Usage:\n"
                "`!delay (DDMMYY HH:MM) message` — specific date/time\n"
                "`!delay 1 week message` — relative (seconds/minutes/hours/days/weeks/months)",
                delete_after=20
            )
            return

        fire_at, body, label = result
        now = datetime.now()
        seconds_until = (fire_at - now).total_seconds()

        if seconds_until <= 0:
            await message.add_reaction("❌")
            await message.reply(
                f"⚠️ That time ({fire_at.strftime('%d %b %Y %H:%M')}) is in the past.",
                delete_after=15
            )
            return

        await message.add_reaction("🕐")
        print(f"Delayed print scheduled: '{body[:50]}' in {label} "
              f"(fires at {fire_at.strftime('%d %b %Y %H:%M')})")

        delay_id = str(uuid.uuid4())
        _add_delay(delay_id, fire_at, body, message.channel.id)
        asyncio.create_task(_run_delay(delay_id, seconds_until, fire_at, body, message.channel.id))
        return

    image_attachments = [
        a for a in message.attachments
        if any(a.filename.lower().endswith(ext) for ext in SUPPORTED_IMG_TYPES)
    ]

    has_content = content.strip() or image_attachments
    if not has_content:
        return

    if len(content) > MAX_MSG_LENGTH:
        await message.reply(f"⚠️ Max {MAX_MSG_LENGTH} chars!", delete_after=10)
        return

    print(f"[{template.upper()}] {message.author.display_name}: {content[:60]}"
          + (f" + {len(image_attachments)} image(s)" if image_attachments else ""))

    try:
        def prepare():
            imgs = []
            for att in image_attachments:
                try:
                    imgs.append(fetch_and_dither_image(att.url))
                except Exception as e:
                    print(f"Could not load image {att.filename}: {e}")
            print_receipt(template, message.author.display_name, content,
                          message.created_at.astimezone(), imgs)

        await asyncio.get_running_loop().run_in_executor(None, prepare)
        await message.add_reaction("🖨️")

    except Exception as e:
        print(f"Error: {e}")
        await message.add_reaction("❌")
        await message.reply(f"⚠️ Print failed: {e}", delete_after=15)


if __name__ == "__main__":
    if DISCORD_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("Paste your bot token into DISCORD_TOKEN at the top of the file!")
        exit(1)
    client.run(DISCORD_TOKEN)
