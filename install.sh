#!/usr/bin/env bash
#
# hd2-macro installer.
#
# Does everything needed to go from a fresh clone to a running daemon:
# packages, kernel modules, udev rules, config, systemd unit. Safe to
# re-run; it never overwrites an existing config.
#
#   ./install.sh                 # interactive, asks before privileged steps
#   ./install.sh --yes           # accept every default, no prompts
#   ./install.sh --no-grant      # skip the udev rules
#   ./install.sh --no-hide       # leave physical pads visible to the browser
#   ./install.sh --no-enable     # do not start at login
#   ./install.sh --uninstall     # undo everything this script did

set -euo pipefail

APP=hd2-macro
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HERE/$APP"

ASSUME_YES=0
DO_GRANT=1
DO_HIDE=1
DO_ENABLE=1
UNINSTALL=0

# ---------------------------------------------------------------- output ---
if [[ -t 1 ]]; then
  B=$'\e[1m'; R=$'\e[31m'; G=$'\e[32m'; Y=$'\e[33m'; D=$'\e[2m'; N=$'\e[0m'
else
  B=''; R=''; G=''; Y=''; D=''; N=''
fi
step() { printf '\n%s==>%s %s%s%s\n' "$B" "$N" "$B" "$*" "$N"; }
ok()   { printf '    %s[ok]%s %s\n' "$G" "$N" "$*"; }
warn() { printf '    %s[--]%s %s\n' "$Y" "$N" "$*"; }
die()  { printf '\n%s[XX]%s %s\n' "$R" "$N" "$*" >&2; exit 1; }
note() { printf '    %s%s%s\n' "$D" "$*" "$N"; }

ask() {
  # ask "question" -> 0 for yes. Defaults to yes.
  [[ $ASSUME_YES == 1 ]] && return 0
  local reply
  read -r -p "    $1 [Y/n] " reply </dev/tty || return 1
  [[ -z $reply || $reply =~ ^[Yy] ]]
}

# ------------------------------------------------------------------ args ---
for arg in "$@"; do
  case "$arg" in
    -y|--yes)    ASSUME_YES=1 ;;
    --no-grant)  DO_GRANT=0 ;;
    --no-hide)   DO_HIDE=0 ;;
    --no-enable) DO_ENABLE=0 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help)   awk 'NR>1 && /^#/ {sub(/^# ?/,""); print; next} NR>1 {exit}' \
                     "${BASH_SOURCE[0]}"; exit 0 ;;
    *)           die "unknown option: $arg  (try --help)" ;;
  esac
done

[[ $EUID -eq 0 ]] && die "run this as your normal user, not root. It will ask for sudo when needed."
[[ -x $BIN ]] || die "cannot find $BIN -- run this from inside the cloned repo"

# ------------------------------------------------------------- uninstall ---
if [[ $UNINSTALL == 1 ]]; then
  step "Removing $APP"
  systemctl --user disable --now "$APP.service" 2>/dev/null || true
  "$BIN" revoke  || true
  "$BIN" unhide  || true
  rm -f "$HOME/.local/bin/$APP" "$HOME/.config/systemd/user/$APP.service"
  sudo rm -f /etc/modules-load.d/$APP.conf
  systemctl --user daemon-reload || true
  ok "removed binary, unit and udev rules"
  note "your config is kept at ~/.config/$APP/config.toml"
  exit 0
fi

printf '%s%s installer%s\n' "$B" "$APP" "$N"
note "$HERE"

# ------------------------------------------------------------ privileges ---
NEED_SUDO=0
[[ $DO_GRANT == 1 || $DO_HIDE == 1 ]] && NEED_SUDO=1
if [[ $NEED_SUDO == 1 ]]; then
  step "Privileges"
  if sudo -n true 2>/dev/null; then
    ok "sudo available"
  else
    note "udev rules and kernel modules need root; you will be asked once"
    sudo -v || die "sudo is required (or re-run with --no-grant --no-hide)"
  fi
  # keep the sudo timestamp warm for the rest of the run
  while true; do sudo -n true 2>/dev/null; sleep 50; kill -0 "$$" 2>/dev/null || exit; done &
  SUDO_KEEPALIVE=$!
  trap 'kill $SUDO_KEEPALIVE 2>/dev/null || true' EXIT
fi

# ---------------------------------------------------------- dependencies ---
step "Dependencies"
command -v python3 >/dev/null || die "python3 not found"
ok "python3 $(python3 -c 'import sys;print(".".join(map(str,sys.version_info[:3])))')"

if python3 -c 'import evdev' 2>/dev/null; then
  ok "python-evdev present"
else
  source /etc/os-release 2>/dev/null || true
  case "${ID:-}${ID_LIKE:-}" in
    *arch*|*omarchy*) PKG=(sudo pacman -S --needed --noconfirm python-evdev) ;;
    *debian*|*ubuntu*) PKG=(sudo apt-get install -y python3-evdev) ;;
    *fedora*|*rhel*)   PKG=(sudo dnf install -y python3-evdev) ;;
    *)                 PKG=() ;;
  esac
  if [[ ${#PKG[@]} -eq 0 ]]; then
    die "install python-evdev with your package manager, then re-run"
  fi
  warn "python-evdev missing, installing: ${PKG[*]}"
  ask "install it now?" || die "python-evdev is required"
  "${PKG[@]}" || die "package install failed"
  python3 -c 'import evdev' 2>/dev/null || die "python-evdev still not importable"
  ok "python-evdev installed"
fi

# -------------------------------------------------------- kernel modules ---
step "Kernel modules"
# NB: no `lsmod | grep -q` here. grep -q exits on the first match, lsmod then
# dies on SIGPIPE, and `set -o pipefail` reports the whole pipeline as failed.
for m in uinput joydev; do
  if [[ -d /sys/module/$m ]]; then
    ok "$m loaded"
  elif [[ $NEED_SUDO == 1 ]] && sudo modprobe "$m" 2>/dev/null; then
    ok "$m loaded"
  else
    warn "$m not loaded (sudo modprobe $m)"
  fi
done
if [[ $NEED_SUDO == 1 ]] && [[ ! -f /etc/modules-load.d/$APP.conf ]]; then
  printf 'uinput\njoydev\n' | sudo tee /etc/modules-load.d/$APP.conf >/dev/null
  ok "will load at boot (/etc/modules-load.d/$APP.conf)"
fi

# ------------------------------------------------- config, symlink, unit ---
step "Installing $APP"
if [[ -f "$HOME/.config/$APP/config.toml" ]]; then
  note "existing config kept; 'hd2-macro install --force' resets it to defaults"
fi
"$BIN" install >/dev/null || die "hd2-macro install failed"
ok "config, ~/.local/bin/$APP symlink and systemd user unit"

case ":$PATH:" in
  *":$HOME/.local/bin:"*) ok "~/.local/bin is on PATH" ;;
  *) warn "~/.local/bin is NOT on PATH -- add it to your shell profile:"
     note 'export PATH="$HOME/.local/bin:$PATH"' ;;
esac

# ------------------------------------------------------------ udev rules ---
if [[ $DO_GRANT == 1 ]]; then
  step "Device access"
  DOCTOR_OUT="$("$BIN" doctor 2>/dev/null || true)"
  if [[ -w /dev/uinput && $DOCTOR_OUT == *"keyboards readable"* ]]; then
    ok "/dev/uinput writable and keyboards readable already"
  else
    note "/dev/uinput must be writable to create the virtual pad."
    note "Keyboard hotkeys also need read access to keyboard event nodes."
    note "Both are granted with a uaccess udev rule, scoped to the user"
    note "logged in at this seat. Undo any time with: $APP revoke"
    if ask "install the udev rules?"; then
      "$BIN" grant >/dev/null || warn "grant reported a problem, see '$APP doctor'"
      [[ -w /dev/uinput ]] && ok "/dev/uinput writable" || warn "/dev/uinput still not writable"
    else
      warn "skipped -- the daemon cannot start without /dev/uinput access"
    fi
  fi
fi

# ------------------------------------------------- hide real controllers ---
if [[ $DO_HIDE == 1 ]]; then
  step "Gamepads"
  DEVICES_OUT="$("$BIN" devices || true)"
  printf '%s\n' "$DEVICES_OUT" | sed 's/^/    /'
  if [[ $DEVICES_OUT == *"physical  VISIBLE"* ]]; then
    note "A physical pad visible to the browser means xCloud sees two"
    note "controllers once the virtual one appears. Hiding its joydev node"
    note "fixes that; the pad keeps working, merged in via passthrough."
    if ask "hide physical pads from the browser?"; then
      "$BIN" hide >/dev/null && ok "hidden (undo with: $APP unhide)"
    else
      warn "skipped -- run '$APP hide' later if xCloud gets confused"
    fi
  else
    ok "nothing to hide"
  fi
fi

# ---------------------------------------------------------------- start ---
step "Starting"
if [[ $DO_ENABLE == 1 ]]; then
  systemctl --user enable "$APP.service" >/dev/null 2>&1 && ok "enabled at login" \
    || warn "could not enable at login"
fi
systemctl --user restart "$APP.service" 2>/dev/null || true
sleep 2
if systemctl --user is-active --quiet "$APP.service"; then
  ok "running"
else
  warn "not running -- journalctl --user -u $APP -n 20"
fi

# --------------------------------------------------------------- verify ---
step "Verifying"
set +e
"$BIN" doctor
RC=$?
set -e

printf '\n'
if [[ $RC -eq 0 ]]; then
  printf '%sReady.%s Open xbox.com/play in Chromium, click the page, then run:\n' "$G" "$N"
  printf '    %s wake\n' "$APP"
  printf '\nHotkeys:  %s list      Mute/unmute:  ALT+SHIFT+M      Stop:  %s off\n' "$APP" "$APP"
else
  printf '%sSome checks failed above.%s Fix those, then re-run: %s doctor\n' "$Y" "$N" "$APP"
fi
exit $RC
