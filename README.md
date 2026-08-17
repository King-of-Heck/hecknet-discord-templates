# Discord Templates

Multi-channel Discord bot that prints to an XP-80C, with a different receipt template per channel.

Watches several Discord channels and prints each with its own receipt layout.

| Channel | Layout |
|---|---|
| To-Do | HeckNet header, work order number, dividers, body |
| Notes | Memorandum header with date and time |
| General | Plain text, no header |
| Borrow (optional) | HeckNet header, "Borrow Request" title, date and time, body |

The work order number is `DDMMYYHHmm`, generated at print time.

## Scheduling

On the To-Do channel:

    !timer 10 minutes             print a reminder after a delay
    !delay (220526 14:30) text    print at a specific date and time
    !delay 1 week text            print after a relative duration

Relative units accepted: seconds, minutes, hours, days, weeks, months. Past
datetimes are rejected.

Pending delays are written to `pending_delays.json` and reloaded on startup.
Anything that came due while the bot was down prints immediately. When a delay
fires the bot also posts a reminder back to the channel.

## Setup

1. Create a bot at the [Discord Developer Portal](https://discord.com/developers/applications),
   enable the Message Content intent, and invite it to your server.
2. Put the token in `DISCORD_TOKEN`. Prefer an environment variable over
   editing the file.
3. Enable Developer Mode in Discord, right-click each channel, Copy ID, and
   fill in `TODO_CHANNEL_ID`, `NOTES_CHANNEL_ID`, `GENERAL_CHANNEL_ID` and
   `TIMER_CHANNEL_ID`.
4. Optionally set `BORROW_CHANNEL_ID` to print borrow requests that a web
   form posts to that channel through a Discord webhook. Leave it at 0 to skip it.

## Requirements

- Windows. Printing goes through the Win32 GDI API.
- Python 3.10 or later.
- An 80mm thermal printer installed as a Windows printer. Built against an
  XP-80C at 203 DPI; other 80mm printers should work if the DPI matches.

```bash
pip install -r requirements.txt
```

Set `PRINTER_NAME` in `discord_templates.py` to the printer's name as it appears in
Settings > Printers & scanners.

Receipts are rendered as images at 4x and downsampled before printing, which
is what keeps the text dark and legible on a thermal head. Courier is used
throughout; glyphs Courier lacks are composited from Segoe UI Emoji.

## Running

```bash
python discord_templates.py
```

## Versioning

Tagged releases, with the change notes in [CHANGELOG.md](CHANGELOG.md).

## Licence

MIT. See [LICENSE](LICENSE).
