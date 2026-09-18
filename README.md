# omarchy-xbox-macro

Virtual Xbox 360 controller + keyboard-triggered macro sequences for
**Xbox Cloud Gaming in Chromium**, built for Helldivers 2 stratagems on
[Omarchy](https://omarchy.org) (Arch + Hyprland + Wayland).

Press `F13` → the daemon holds `LB`, taps `↑↓→←↑` on the d-pad, releases.
Reinforce called, without memorising a single code.

## Why a fake Xbox 360 pad?

xbox.com/play only accepts a controller that Chromium maps to the W3C
**"standard" gamepad mapping**. On Linux, Chromium selects that mapping from the
device's USB vendor/product ID, reads state from the legacy `/dev/input/jsN`
node, and ignores anything it doesn't recognise.

So generic virtual-input tools don't work here:

| tool | why not |
|---|---|
| `input-remapper` | emits a device named after itself → no standard mapping → xCloud ignores it |
| `evsieve` | same, plus no timed macro sequences |
| AntiMicroX / antimicro | maps gamepad → keyboard, the opposite direction |
| `wtype` / `ydotool` | keyboard/mouse only; xCloud wants gamepad input |

`hd2-macro` creates a uinput device with `045e:028e` and the exact capability
set of the kernel `xpad` driver, in the same order — so the resulting `jsN`
axis/button numbering is byte-identical to a real wired Xbox 360 controller.
Chromium can't tell the difference.

## Only one controller

If you also play with a real pad, the browser would see two gamepads (yours and
the virtual one) and xCloud gets confused about which to use. Two mechanisms
keep it at exactly one:

**1. Passthrough (on by default).** The daemon takes an exclusive `EVIOCGRAB`
on your real controller and re-emits every button, stick and trigger through
the virtual pad, rescaling axis ranges as needed (Xbox Series X|S triggers are
0–1023, an Xbox 360's are 0–255). A grab is *device-wide* in the kernel — not
just the evdev node — so the real pad's own `jsN` node goes completely silent:

```
ungrabbed -> joydev saw 2 events
GRABBED   -> joydev saw 0 events
ungrabbed -> joydev saw 2 events
```

You keep playing normally; macros are merged into the same stream. A macro
overrides a control only while it holds it, then falls back to whatever you're
physically pressing, so it can never eat a button out from under you.

**2. `hd2-macro hide` (one-off, needs sudo).** The grabbed pad is silent but its
`jsN` node still exists, and Chromium lists connected-but-idle gamepads. This
installs `/etc/udev/rules.d/72-hd2-macro-hide.rules`, which drops the `uaccess`
tag and sets `MODE="0600"` on that pad's **joydev node only** — Chromium can no
longer open it, so it vanishes from the gamepad list, while the evdev node stays
readable so hd2-macro can still grab and forward it.

```bash
hd2-macro devices     # what the browser can actually see
hd2-macro hide        # hide every physical pad's js node
hd2-macro hide Xbox   # or just one, by name fragment or vid:pid
hd2-macro unhide      # undo
```

```
node            vid:pid     kind      browser   name
/dev/input/js0  045e:0b12   physical  hidden    Microsoft Xbox Series S|X Controller
/dev/input/js1  045e:028e   virtual   VISIBLE   Microsoft X-Box 360 pad

the browser would see 1 gamepad(s)
```

If you have no real controller, neither applies — set `passthrough.enabled =
false` and skip `hide`.

## Requirements

- `python-evdev` (`sudo pacman -S python-evdev`)
- `joydev` kernel module (loaded by default on Arch)
- write access to `/dev/uinput`

On Omarchy the last one already works: udev tags `uinput` with `uaccess`, so
logind grants your active session an ACL. Same for joysticks, which is how the
passthrough grab works unprivileged. No sudo, no group changes, no udev rule —
unless you want keyboard hotkeys or `hide`. `hd2-macro doctor` confirms it all.

## Install

```bash
git clone <this repo> ~/Work/omarchy-xbox-macro
cd ~/Work/omarchy-xbox-macro
./hd2-macro install     # config + ~/.local/bin symlink + systemd user unit
hd2-macro grant         # let this session read keyboards (for keyboard hotkeys)
hd2-macro hide          # keep a real controller out of the browser's gamepad list
hd2-macro on
hd2-macro doctor
```

The two `sudo` steps are optional and independently reversible (`revoke` /
`unhide`); skip `grant` if you only use `pad:` buttons, and `hide` if you have
no real controller. A clean run ends with:

```
permissions
  [ok] /dev/uinput writable
  [ok] joydev module loaded
config
  [ok] hotkey names valid  13 bound
  [ok] keyboards readable  Logitech G915 TKL ...
gamepads
       /dev/input/js0  physical hidden   Microsoft Xbox Series S|X Controller
       /dev/input/js1  virtual  VISIBLE  Microsoft X-Box 360 pad
  [ok] browser sees exactly one gamepad
daemon
  [ok] running

all good
```

`install` copies `config.example.toml` to `~/.config/hd2-macro/config.toml` and
never overwrites it afterwards (use `--force` if you want the defaults back).

## Turning it on and off

```bash
hd2-macro on          # start          (systemctl --user start hd2-macro)
hd2-macro off         # stop, pad disappears
hd2-macro toggle      # flip
hd2-macro status
systemctl --user enable hd2-macro     # start at login
```

While it runs, `ALT+SHIFT+M` (or `hd2-macro disarm`) suspends the hotkeys while
keeping the pad connected — handy when you tab out to type:

```bash
hd2-macro disarm      # ignore hotkeys
hd2-macro arm
hd2-macro panic       # release every button right now
```

Each of those raises an Omarchy notification, so you always know which mode
you're in without checking a terminal:

| | | |
|---|---|---|
| 󰖺 | **Macros armed** | 10 hotkeys live |
| 󰖻 | **Macros disarmed** | Keyboard back to normal |
| 󰜺 | **Panic** | All buttons released |

They go through `omarchy notification send` (falling back to `notify-send`
elsewhere) and reuse a single notification id, so toggling updates one toast
instead of stacking a new one each time. Configure or silence them:

```toml
[notify]
enabled    = true
timeout_ms = 1800

[notify.glyphs]             # any Nerd Font glyph
armed    = "\U000F05BA"     # nf-md-microsoft_xbox_controller
disarmed = "\U000F05BB"     # nf-md-microsoft_xbox_controller_off
panic    = "\U000F073A"     # nf-md-cancel
```

## Using it with xCloud

1. `hd2-macro on`
2. Open `https://www.xbox.com/play` in Chromium and start Helldivers 2.
3. **Click the page, then run `hd2-macro wake`** (or press any real gamepad
   button). Browsers only expose a gamepad to a page after input arrives while
   that page is focused — until then `navigator.getGamepads()` is empty and
   xCloud shows no controller.
4. Check it's seen: visit `chrome://device-log` or
   [hardwaretester.com/gamepad](https://hardwaretester.com/gamepad) — it should
   read `Xbox 360 Controller (STANDARD GAMEPAD Vendor: 045e Product: 028e)`.
5. Press your hotkeys with the game focused.

If xCloud stops responding to macros mid-session, `hd2-macro panic` then
`hd2-macro wake`.

## Configuration

Everything lives in `~/.config/hd2-macro/config.toml`. After editing:

```bash
systemctl --user restart hd2-macro
hd2-macro list        # review hotkeys / stratagems / macros
```

### Hotkeys

```toml
[hotkeys]
1 = "reinforce"                 # a [stratagems] entry
2 = "resupply"
3 = "strat:URDDD"               # a literal code, no entry needed
4 = "macro:turtle_up"           # a [macros.*] block
5 = "press:A 300"               # hold A for 300ms

"ALT+SHIFT+M" = "toggle"        # arm/disarm every other hotkey
"ALT+SHIFT+P" = "panic"         # release every button
"pad:RECORD"  = "panic"         # Xbox share button
```

The shipped config maps the whole digit row `1`–`0` to ten stratagems. Swap the
names for your loadout.

**Keys** are evdev `KEY_*` names minus the prefix, optionally with `CTRL`,
`ALT`, `SHIFT` or `SUPER` joined by `+`. Don't guess — press the key and let it
tell you:

```bash
hd2-macro keys      # prints the config-ready name of whatever you press
```

Matching is **exact**, so bindings can't shadow each other: `1` fires on a bare
`1` only, never on `Shift+1` or `Ctrl+1`. The daemon doesn't grab the keyboard,
so keys still reach the focused app and typing works normally.

`ALT+SHIFT+M` toggles all the other hotkeys off and on without stopping the
daemon or disconnecting the pad. It's deliberately conflict-free: Hyprland only
binds `M` with SUPER held (`SUPER+SHIFT+M`, `SUPER+SHIFT+ALT+M`), and
Chromium's `Alt+Shift+<letter>` accelerators cover I B A R T C P X Z W — not M
(checked in `chrome/browser/ui/accelerator_table.cc`).

**Keyboard hotkeys need read access to keyboards.** udev grants `uaccess` ACLs
on joysticks but not keyboards, so one of:

```bash
hd2-macro grant                 # recommended: takes effect immediately
sudo usermod -aG input $USER    # traditional: needs a full logout
```

`grant` installs a udev rule extending the same `uaccess` tagging udev already
applies to joysticks. It's both more convenient and tighter than the group: the
ACL is granted only to whoever is physically logged in at the seat and is
released on logout, whereas `input` group membership applies to every session
including SSH. Undo with `hd2-macro revoke`.

Either way, any program running as you can then read all keyboard input — worth
knowing before enabling it. Two alternatives that need no privileges at all:
`pad:` buttons (routed through the passthrough grab you already have, and
consumed rather than forwarded to the game), or Hyprland binds calling
`hd2-macro run <name>`.

### Scoping hotkeys to the game

By default hotkeys fire whenever the daemon is running, in any window. To
restrict them to the xCloud tab, match on the focused window's class or title
(Hyprland only — the daemon watches `.socket2.sock`):

```toml
[focus]
only_when = ["xbox.com"]
```

### Timing

xCloud samples the pad at ~60Hz and ships input over the network, so presses
shorter than roughly 60ms get dropped. Defaults are deliberately relaxed:

```toml
[timing]
press_ms = 80     # hold per press
gap_ms   = 60     # pause between presses
speed    = 1.0    # global multiplier; 0.7 when your connection is bad
```

Misfiring stratagems? Lower `speed` to `0.7` first — it stretches every
duration at once.

### The stratagem routine

```
hold LB → wait pre_ms → tap the code → wait post_ms → release LB → throw
```

```toml
[stratagem]
hold_button = "LB"      # stratagem button on an Xbox pad
hold_mode   = "hold"    # "hold" while entering, or "tap" to open the menu
pre_ms      = 250       # after opening the menu, before the first direction
post_ms     = 200       # after the last direction, before releasing

throw_button   = "RT"   # HD2 Fire — without this the diver just holds the beacon
throw_delay_ms = 300
throw_ms       = 120
```

**The padding either side is not cosmetic**, and the two ends fail differently.

`pre_ms` guards the start. The D-pad is only the stratagem keypad *while the
menu is open*; outside it HD2 binds:

| D-pad | outside the stratagem menu |
|---|---|
| Up | Quick Stim |
| Right | **Grenade** |
| Down | Use Backpack Function |
| Left | Emote / spectate |

A direction landing before the menu has opened comes out as a weapon action.

`post_ms` guards the end, and wants to be **small**. HD2 closes the stratagem
menu the moment a valid code lands and the diver draws the beacon. A hold
button still down after that re-opens the menu, and releasing it with an empty
code buffer stows the beacon you just drew — the diver *"selects the orb, then
switches back to rifle"*. It is measured from the final direction's release,
with no trailing gap, so the default 80ms puts LB up ~159ms after the
completing press.

Tune either end live, without editing the config or restarting:

```bash
hd2-macro run reinforce --post 40      # release LB sooner
hd2-macro run reinforce --pre 400      # give the menu longer to open
hd2-macro run reinforce --speed 0.5    # stretch everything, to watch it happen
```

If it works slowed down, it is timing — lower `timing.speed` or raise
`pre_ms`/`post_ms`. If it still misbehaves, the code itself is wrong.

### Macro DSL

```toml
[macros.turtle_up]
steps = [
  "strat DURRU",    # machine gun sentry
  "wait 600",
  "strat DLUR",     # minefield
  "wait 600",
  "strat DDLRLR",   # shield relay
]
```

| step | meaning |
|---|---|
| `press <CTL> [ms]` | tap a control (default `timing.press_ms`) |
| `down <CTL>` / `up <CTL>` | hold / release |
| `wait <ms>` | pause |
| `code <UDLR…>` | d-pad sequence only |
| `strat <UDLR…\|name>` | full routine: hold, code, release |
| `axis <LT\|RT> <0-255> [ms]` | analogue trigger |
| `stick <L\|R> <x> <y> [ms]` | `-1.0 … 1.0` |
| `repeat <n> <step…>` | loop |
| `neutral` | release everything |

Controls: `A B X Y LB RB LT RT BACK START GUIDE LS RS UP DOWN LEFT RIGHT`.

Firing a macro cancels whichever one is still running, and every macro ends by
returning the pad to neutral — a crashed or killed daemon can never leave a
button stuck down.

## One keypress, one macro

A single physical keypress can surface on **several** event nodes at once --
one Logitech Unifying/Lightspeed receiver here exposes three that all carry the
digit row:

```
!! same hardware usb-0000:0a:00.0-3:
     /dev/input/event4   Logitech K540/K545
     /dev/input/event9   Logitech K540/K545
     /dev/input/event10  Logitech MX Master 3
```

Every duplicate used to re-trigger the macro, and each re-trigger *cancelled*
the one in flight -- which releases the stratagem hold button and presses it
again. HD2 reads that second press as a cancel and stows the beacon you just
drew, so a stratagem would be selected and then instantly lost. Two defaults
prevent it:

```toml
[timing]
debounce_ms = 300      # ignore repeat triggers of the same macro
on_busy     = "ignore" # never cancel and restart a macro mid-sequence
```

Set `on_busy = "restart"` only if you want a new macro to interrupt a running
one, and accept that it will cancel a stratagem in progress.

## Stratagem codes

`config.example.toml` ships the common Helldivers 2 codes. **Verify them
against your loadout** — Arrowhead adjusts codes between patches, and you only
need the ones you actually bring.

## Troubleshooting

```bash
hd2-macro doctor                      # permissions, joydev, config, hotkeys
journalctl --user -u hd2-macro -f     # live log
hd2-macro daemon                      # run in the foreground instead
```

| symptom | fix |
|---|---|
| no gamepad on the page | focus the tab, `hd2-macro wake` |
| xCloud sees two controllers | `hd2-macro devices`, then `hd2-macro hide` |
| real controller stops working | that's the grab — it's being forwarded; check `hd2-macro status` shows `passthrough=<name>` |
| hotkeys do nothing | `hd2-macro status` — if `armed=False`, press `ALT+SHIFT+M` |
| `/dev/uinput` not writable | you're on a remote or inactive session; `loginctl` seat must be active |
| no keyboards listed by `doctor` | `hd2-macro grant` (or `sudo usermod -aG input $USER` + re-login) |
| keyboard plugged in mid-session | give it a few seconds; the daemon rescans every 3s |
| don't know a key's name | `hd2-macro keys` |
| macros half-register | lower `timing.speed` to `0.7`, raise `press_ms` |
| character reverts to rifle / throws a grenade or stim after a stratagem | a d-pad input leaked outside the menu \| macros half-register | lower `timing.speed` to `0.7`, raise `press_ms` |mdash; raise `pre_ms` and `post_ms` |
| want it thrown automatically | set `throw_button = "RT"` (off by default, so the orb stays in hand) |

No rumble: the virtual pad doesn't advertise force feedback, because
forwarding `UI_FF_UPLOAD` requests back to the real pad isn't implemented.

## License

MIT
