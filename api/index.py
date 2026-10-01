"""
Vercel entry point for AUDIX.
Imports the Flask app and exposes it as `app` for Vercel's Python runtime.
"""
import sys
import os
from pathlib import Path

# Add repo root to path so recovery_manager package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recovery_manager.api.app import app

# Vercel uses `app` as the WSGI handler
handler = app
