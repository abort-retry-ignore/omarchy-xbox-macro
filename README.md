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
hd2-macro on
hd2-macro doctor
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

While it runs you can keep the pad connected but ignore hotkeys — handy when
you tab out to type:

```bash
hd2-macro disarm      # or press ScrollLock (bound to "toggle")
hd2-macro arm
hd2-macro panic       # release every button right now (bound to Pause)
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
"pad:RECORD" = "reinforce"                # Xbox share button, no permissions needed
F13          = "reinforce"                # a [stratagems] entry
F14          = "strat:UDRLU"              # a literal code
F15          = "macro:turtle_up"          # a [macros.*] block
F16          = "press:A 300"              # hold A for 300ms
SCROLLLOCK   = "toggle"                   # arm/disarm
PAUSE        = "panic"
```

There are three ways to trigger a macro. Pick whichever suits you:

**Hyprland binds (recommended, zero setup).** Needs no permissions and Hyprland
swallows the key, so it never leaks into the game. In
`~/.config/hypr/bindings.lua`:

```lua
o.bind("SUPER + 1", "Reinforce", "hd2-macro run reinforce")
o.bind("SUPER + 2", "500kg",     "hd2-macro run eagle_500kg")
```

**Controller buttons.** `"pad:RECORD"` binds the Xbox Series X|S share button,
which xCloud doesn't use. These come through the passthrough grab you already
have, so no extra permissions, and the button is *consumed* — never forwarded
to the game. Any control name works: `pad:BACK`, `pad:GUIDE`, `pad:RS`, …

**Keyboard hotkeys (needs the `input` group).** Reading keyboards directly
requires `sudo usermod -aG input $USER` and a re-login, because udev only grants
`uaccess` ACLs on joysticks, not keyboards. That group lets any program running
as you read all keyboard input, so only do it if you want it. The daemon does
*not* grab the keyboard, so these keys still reach Chromium — use `F13`–`F24`,
which no physical key sends (remap spare mouse buttons to them). Key names are
evdev `KEY_*` names without the prefix:

```bash
python -c "import evdev; print(sorted(k for k in evdev.ecodes.ecodes if k.startswith('KEY_')))"
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

```toml
[stratagem]
hold_button = "LB"      # stratagem button on an Xbox pad
hold_mode   = "hold"    # "hold" while entering, or "tap" to open the menu
pre_ms      = 150       # settle after opening
post_ms     = 120       # pause before releasing
# throw_button   = "RT" # uncomment to auto-throw once the code is in
# throw_delay_ms = 250
```

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
| `/dev/uinput` not writable | you're on a remote or inactive session; `loginctl` seat must be active |
| no keyboards listed by `doctor` | `sudo usermod -aG input $USER`, then log out and back in — or use Hyprland binds / `pad:` buttons |
| macros half-register | lower `timing.speed` to `0.7`, raise `press_ms` |
| hotkey also types into the game | use an `F13`–`F24` key, or bind it in Hyprland instead |

No rumble: the virtual pad doesn't advertise force feedback, because
forwarding `UI_FF_UPLOAD` requests back to the real pad isn't implemented.

## License

MIT
