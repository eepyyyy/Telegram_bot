#!/usr/bin/env python3
"""
client_web/run.py

Quick launcher for the Client-Side Decryption Web Application.
Usage:
    python client_web/run.py
    python client_web/run.py --port 8090
"""
import argparse
import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from client_web.server import run_server

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Client-Side Decryption Web App")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8090)), help="Port (default: 8090)")
    args = parser.parse_args()

    print("=" * 60)
    print("  Apple Music Client-Side Decryption Web Application")
    print(f"  URL: http://localhost:{args.port}")
    print("=" * 60)
    run_server(host=args.host, port=args.port)
