# Changelog

Version numbers were reassigned for release (the old scheme bumped the
minor version for bugfixes); the original number is in parentheses. The
notes below are from each script's own version history.

## 1.13.0  (originally 1.20)

Added the Board channel (hecknet/board web form -> Discord webhook -> printer)
to CHANNEL_CONFIG, mapped to a new "board" template. build_board currently
delegates to build_borrow (skull header + date/time + body); the web form body
carries ":: THE BOARD ::" / handle / "- hecknet/board". Its own seam so board
slips can diverge from borrow later.

## 1.12.1  (originally 1.19)

Borrow template no longer prints its own "Borrow Request" title or "via
hecknet/stacks" line — the web form's message body already carries ":: BORROW
REQUEST ::" and "- hecknet/stacks", so those were doubling up on the slip. Kept
the 💀 HeckNet 💀 skull header + date/time; the message body supplies the rest.

## 1.12.0  (originally 1.18)

Gave the Borrow channel its own template (build_borrow) matching the HeckNotes
house style: skull header, "Borrow Request" title, date/time, dividers. Channel
remapped from "plain" to "borrow".

## 1.11.0  (originally 1.17)

Added Borrow channel (hecknet/stacks web form -> Discord webhook -> printer) to
CHANNEL_CONFIG, using the plain template.

## 1.10.2  (originally 1.16)

Fixed asyncio.get_event_loop() deprecation (now get_running_loop()). Added outer
try/except in _run_delay so errors are logged rather than silently swallowed.
Added success logging for print and Discord notify steps to confirm each stage
fired correctly.

## 1.10.1  (originally 1.15)

Fixed UnicodeEncodeError when launched via HeckNet Manager. Added
sys.stdout/stderr.reconfigure(encoding="utf-8") so emoji in console output works
correctly under subprocess PIPE.

## 1.10.0  (originally 1.14)

Delayed prints now persist across restarts via pending_delays.json. On startup any
pending delays are reloaded and rescheduled; missed delays (bot was down when they
were due) fire immediately on restart. When a delay fires, the bot also posts a 🕐
Reminder message to the same Discord channel alongside printing the receipt.

## 1.9.1  (originally 1.13.1)

Delay parsing corrections and rejection of past datetimes.

## 1.9.0  (originally 1.13)

Added !delay command to To-Do channel. Supports two formats: !delay (DDMMYY HH:MM)
message — prints at a specific date/time !delay 1 week message — prints after a
relative duration Relative units: seconds/minutes/hours/days/weeks/months. Bot
reacts 🕐 on success. Work Order number generated at print time. Rejects past
datetimes with a warning.

## 1.8.1  (originally 1.12.1)

Timer parsing and reaction handling corrections.

## 1.8.0  (originally 1.12)

Added timer channel. Type "!timer 10 minutes" (or any number +
minutes/mins/min/m/hours/hr/h/seconds/sec/s) to schedule a print. Bot reacts ⏱️ on
start, prints 💀 HeckNet 💀 / "Time's Up Bucko!" receipt when the timer fires.
Channel ID set via TIMER_CHANNEL_ID.

## 1.7.0  (originally 1.11)

Notes channel reworked to match To-Do layout. Header is now 💀 HeckNet 💀 / divider
/ Memorandum / date / time / divider / body / divider. HeckNotes label retired.

## 1.6.0  (originally 1.10)

Simplified Work Order number: replaced daily sequence counter with 24hr time
(HHMM), giving format DDMMYYHHmm (e.g. 1605262109). Removed date line beneath the
work order number.

## 1.5.0  (originally 1.9)

Reworked To-Do template: header changed from HeckTasks to HeckNet (with flanking
skulls). Added Work Order number in format DDMMYYNN (e.g. 16052601 for the first
order on May 16 2026). Counter resets daily and increments per print. Layout: 💀
HeckNet 💀 / divider / Work Order XXXXXXXX / timestamp / divider / body / divider.

## 1.4.2  (originally 1.8)

Fixed skulls floating above the heading text. SKULL_Y_OFFSET now correctly shifts
skull draw position downward relative to the text y, so skulls sit level with the
heading rather than above it. top_pad still prevents canvas clipping
independently.

## 1.4.1  (originally 1.7)

Fixed SKULL_Y_OFFSET having no effect. Root cause was canvas clipping not offset
logic. Now adds top_pad to the canvas in _render_ops so the skull has room above
it; SKULL_Y_OFFSET controls that padding.

## 1.4.0  (originally 1.6)

Added skull glyphs to HeckNotes header to match HeckTasks.

## 1.3.0  (originally 1.5)

Added SKULL_FONT_SIZE constant so skull size can be tuned independently of the
header text (FONT_SIZE). Fixed bug where load_skull_font was called with FONT_SIZE
instead of SKULL_FONT_SIZE.

## 1.2.0  (originally 1.4)

Fixed skull top clipping. Added SKULL_Y_OFFSET constant (tune as needed) to shift
skull glyphs down relative to the text baseline without affecting the "HeckTasks"
label position.

## 1.1.2  (originally 1.3)

Switched skull glyph from ☠ (U+2620, skull & crossbones) to 💀 (U+1F480, plain
skull). Now uses Segoe UI Emoji (seguiemj.ttf) which ships with Windows 10+.

## 1.1.1  (originally 1.2)

Fixed skull glyphs rendering as boxes. Courier lacks U+2620 so skulls are now
rendered separately using DejaVu Sans Mono (falls back to Segoe UI Symbol) and
composited onto the header line at 4× scale.

## 1.1.0  (originally 1.1)

Removed FROM/author lines from all templates (single-user channels). Renamed TASK
template to HeckTasks; redesigned to match HeckNotes header style (dividers, full
date/time format). Added ☠ skull glyphs (U+2620) on either side of HeckTasks
header.

## 1.0.0  (originally 1.0)

Initial release.

