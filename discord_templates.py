"""
Discord_Printer_Templates_1_5.py
Multi-channel Discord → thermal receipt printer with per-channel templates.

Channel templates
  To-Do  (0) → HeckTasks header (skull glyphs, divider style)
  Notes  (0) → HeckNotes header
  General(0) → No header — plain text only
"""

import asyncio
import io
from datetime import datetime

import requests
import discord
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageWin
import win32ui


DISCORD_TOKEN  = "YOUR_BOT_TOKEN_HERE"          # paste your new bot token here

PRINTER_NAME   = "XP-80C"
FONT_PATH      = "cour.ttf"
FONT_BOLD      = "courbd.ttf"

MAX_MSG_LENGTH = 500
ALLOWED_USERS  = []                             # list of user IDs to whitelist,

# Channel  template mapping
# Template names: "task" | "notes" | "plain"

CHANNEL_CONFIG = {
    0: "task",    # To-Do
    0: "notes",   # Notes
    0: "plain",   # General Printer
}


PRINTER_DPI  = 203
PAPER_MM     = 80
PAPER_PX     = int(PAPER_MM / 25.4 * PRINTER_DPI)   # ≈ 638 px
MARGIN_PX    = 10
TEXT_PX      = PAPER_PX - 2 * MARGIN_PX
FONT_SIZE       = 36
SKULL_FONT_SIZE = 10       # skull size in points — adjust independently of header text
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

# Extra pixels (at 4x scale) to push skulls down so the top doesn't clip.
# Increase if the skull top is still cut off; decrease if there's too much gap.
SKULL_Y_OFFSET = 20

def draw_skull_header(draw, text: str, font_text, font_skull,
                      paper_w: int, y: int):
    """
    Render  💀  <text>  💀  centred on the line, using font_skull for the glyphs
    and font_text for the label.  All coords are at hi-res (4x) scale.
    SKULL_Y_OFFSET shifts the skulls down relative to the text so the top
    of the glyph doesn't clip — tune it at the top of this section.
    """
    SKULL = "\U0001F480"
    gap   = int(font_text.size * 0.4)   # small gap between skull and text

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


def _render_ops(ops, paper_w, margin, line_h) -> tuple[Image.Image, int]:
    """Render a list of (text, font, align) ops at 4× scale. Returns (image, y)."""
    S = RENDER_SCALE
    total_h = len(ops) * line_h + line_h * 2
    hi_res  = Image.new("RGB", (paper_w, total_h), "white")
    draw    = ImageDraw.Draw(hi_res)
    y       = margin // 2
    for text, font, align in ops:
        x = (paper_w - font.getlength(text)) / 2 if align == "center" else margin
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
    font_skull = load_skull_font(size=FONT_SIZE)
    DIVIDER    = "─" * int(text_w / (FONT_SIZE * S * 0.62))

    # The skull header line is drawn manually; everything else goes through ops.
    # We reserve one line_h slot at the top for it via a blank placeholder.
    ops = []

    def add(text, bold=False, align="left", small=False):
        ops.append((text, font_sm if small else (font_b if bold else font_n), align))

    def div():
        add(DIVIDER)

    add("",   align="center")                                    # skull header placeholder
    add(timestamp.strftime("%A, %B %d %Y"), align="center", small=True)
    add(timestamp.strftime("@ %I:%M %p"),   align="center", small=True)
    div()

    if content.strip():
        for paragraph in content.splitlines():
            if not paragraph.strip():
                add(" ")
                continue
            for line in word_wrap(paragraph, font_n, text_w):
                add(line)
        div()

    hi_res, y = _render_ops(ops, paper_w, margin, line_h)

    draw = ImageDraw.Draw(hi_res)
    draw_skull_header(draw, "HeckTasks", font_b, font_skull,
                      paper_w, margin // 2)

    output = _downsample(hi_res, PAPER_PX, y)
    return _attach_images(output, attachment_imgs)


def build_notes(author: str, content: str, timestamp: datetime,
                attachment_imgs: list) -> Image.Image:
    S       = RENDER_SCALE
    paper_w = PAPER_PX * S
    margin  = MARGIN_PX * S
    text_w  = TEXT_PX * S
    line_h  = (FONT_SIZE + 6) * S

    font_n  = load_font(bold=False)
    font_b  = load_font(bold=True)
    font_sm = load_font(bold=False, size=FONT_SIZE - 8)
    DIVIDER = "─" * int(text_w / (FONT_SIZE * S * 0.62))

    ops = []

    def add(text, bold=False, align="left", small=False):
        ops.append((text, font_sm if small else (font_b if bold else font_n), align))

    def div():
        add(DIVIDER)

    add("HeckNotes", bold=True, align="center")
    add(timestamp.strftime("%A, %B %d %Y"), align="center", small=True)
    add(timestamp.strftime("@ %I:%M %p"),   align="center", small=True)
    div()

    if content.strip():
        for paragraph in content.splitlines():
            if not paragraph.strip():
                add(" ")
                continue
            for line in word_wrap(paragraph, font_n, text_w):
                add(line)
        div()

    hi_res, y = _render_ops(ops, paper_w, margin, line_h)
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


intents = discord.Intents.default()
intents.message_content = True
client  = discord.Client(intents=intents)

SUPPORTED_IMG_TYPES = (".jpg", ".jpeg", ".png", ".gif", ".webp")

@client.event
async def on_ready():
    watching = ", ".join(str(cid) for cid in CHANNEL_CONFIG)
    print(f" Bot ready: {client.user}")
    print(f"   Watching channels: {watching}")

@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return
    if message.channel.id not in CHANNEL_CONFIG:
        return
    if ALLOWED_USERS and message.author.id not in ALLOWED_USERS:
        return

    template = CHANNEL_CONFIG[message.channel.id]
    content  = message.content

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

        await asyncio.get_event_loop().run_in_executor(None, prepare)
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
