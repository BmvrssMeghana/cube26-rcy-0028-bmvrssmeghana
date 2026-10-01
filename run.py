#!/usr/bin/env python
"""
AUDIX — AI-Powered Recovery Intelligence
Entry point. Run with: python run.py
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from recovery_manager.api.app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    host = os.environ.get("HOST", "0.0.0.0")

    print(f"\n  ⚡ AUDIX Recovery Intelligence")
    print(f"  ─────────────────────────────────────────────")
    print(f"  🌐 Landing Page    →  http://localhost:{port}/")
    print(f"  📊 App Workspace   →  http://localhost:{port}/app")
    print(f"  🎬 Demo            →  http://localhost:{port}/demo")
    print(f"  💊 Health Check    →  http://localhost:{port}/health")
    print(f"  ─────────────────────────────────────────────\n")

    app.run(host=host, port=port, debug=debug)
