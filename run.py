#!/usr/bin/env python
"""
Entry point for the Recovery Manager.
Run with: python run.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from recovery_manager.api.app import app

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  ⚡ Recovery Manager  →  http://localhost:{port}/")
    print(f"  📊 API health check →  http://localhost:{port}/api/health\n")
    app.run(host="0.0.0.0", port=port, debug=True)
