"""
Run the admin server directly.

Usage:
    python -m src.admin
    python -m src.admin --port 8000
    python -m src.admin --no-browser
"""

import argparse
import sys

from .server import run_server


def main():
    parser = argparse.ArgumentParser(description="Continuity Orchestrator Admin Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    parser.add_argument("--port", type=int, default=5050, help="Port (default: 5050)")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    
    args = parser.parse_args()
    
    run_server(
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
        debug=args.debug,
    )


if __name__ == "__main__":
    main()
