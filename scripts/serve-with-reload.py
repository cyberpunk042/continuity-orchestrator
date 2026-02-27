#!/usr/bin/env python3
"""Flask dev server wrapper with spacebar-to-reload.

Uses Python's tty/termios/select — the proper way to handle
single-keypress detection on Unix.

Usage:
    python scripts/serve-with-reload.py [--debug] [extra args...]
"""

import os
import signal
import subprocess
import sys
import time


_proc = None


def _hard_kill():
    """Kill Flask fast (for reload — no need for graceful shutdown)."""
    global _proc
    if _proc is None:
        return
    try:
        os.killpg(os.getpgid(_proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            _proc.terminate()
        except Exception:
            pass
    try:
        _proc.wait(timeout=3)
    except Exception:
        try:
            os.killpg(os.getpgid(_proc.pid), signal.SIGKILL)
        except Exception:
            pass
    _proc = None


def _graceful_shutdown():
    """Send SIGINT so Flask runs its shutdown hooks (vault lock, atexit, etc.)."""
    global _proc
    if _proc is None:
        return
    try:
        os.killpg(os.getpgid(_proc.pid), signal.SIGINT)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            _proc.send_signal(signal.SIGINT)
        except Exception:
            pass
    try:
        _proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        # If graceful didn't work after 10s, force kill
        _hard_kill()
    _proc = None


def main():
    global _proc
    args = sys.argv[1:]

    # If stdin isn't a terminal (piped, CI, etc.), just run directly
    if not sys.stdin.isatty():
        proc = subprocess.Popen([sys.executable, "-u", "-m", "src.admin"] + args)
        sys.exit(proc.wait())

    import select
    import termios
    import tty

    old_settings = termios.tcgetattr(sys.stdin)

    def restore_terminal():
        try:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        except Exception:
            pass

    def on_quit(signum=None, frame=None):
        """Ctrl+C / SIGTERM — graceful shutdown then exit."""
        restore_terminal()
        _graceful_shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, on_quit)
    signal.signal(signal.SIGTERM, on_quit)

    try:
        tty.setcbreak(sys.stdin.fileno())

        first_run = True
        while True:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"

            # On reload, skip browser open (it's already open)
            cmd_args = list(args)
            if not first_run and "--no-browser" not in cmd_args:
                cmd_args.append("--no-browser")

            _proc = subprocess.Popen(
                [sys.executable, "-m", "src.admin"] + cmd_args,
                stdin=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
            first_run = False

            reloading = False
            while _proc.poll() is None:
                rlist, _, _ = select.select([sys.stdin], [], [], 0.5)
                if rlist:
                    ch = sys.stdin.read(1)
                    if ch == " ":
                        restore_terminal()
                        print("\n\033[0;36m♻  Reloading server...\033[0m\n")
                        _hard_kill()
                        reloading = True
                        time.sleep(0.5)
                        tty.setcbreak(sys.stdin.fileno())
                        break
                    elif ch == "q":
                        restore_terminal()
                        print("\n\033[0;33mQuitting...\033[0m\n")
                        _graceful_shutdown()
                        return

            if not reloading:
                _proc = None
                break

    finally:
        _graceful_shutdown()
        restore_terminal()


if __name__ == "__main__":
    main()
