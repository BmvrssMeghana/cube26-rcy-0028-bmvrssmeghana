"""
Flask API — Recovery Manager
Serves the UI and exposes the engine over HTTP.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, send_file
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from recovery_manager.engine.runner import run_from_files, run_from_text
from recovery_manager.engine.ingestor import _load_csv, parse_fee_report, build_upstream_index
from recovery_manager.engine.evidence_matcher import match_charge
from recovery_manager.engine.sla_engine import CLAIM_POLICY, compute_sla

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
UPSTREAM_DIR = DATA_DIR / "upstream"

app = Flask(__name__, static_folder=str(UI_DIR), static_url_path="")
CORS(app)


# ── UI ───────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(str(UI_DIR), "index.html")


@app.route("/<path:path>")
def static_files(path):
    fp = UI_DIR / path
    if fp.exists():
        return send_from_directory(str(UI_DIR), path)
    return send_from_directory(str(UI_DIR), "index.html")


# ── Health ────────────────────────────────────────────────

@app.route("/api/health")
def health():
    db_status = "disabled"
    try:
        from recovery_manager.db.database import PSYCOPG2_AVAILABLE, get_pg_connection
        if PSYCOPG2_AVAILABLE:
            conn = get_pg_connection()
            conn.close()
            db_status = "connected (PostgreSQL)"
    except Exception as e:
        db_status = f"error ({e})"

    return jsonify({"status": "ok", "version": "1.0.0", "database": db_status})


@app.route("/api/db/init", methods=["POST", "GET"])
def db_init():
    try:
        from recovery_manager.db.database import init_db_schema, seed_data_from_csvs
        s_ok = init_db_schema()
        d_ok = seed_data_from_csvs()
        return jsonify({"status": "success", "schema_init": s_ok, "data_seeded": d_ok})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Auto-initialize database schema on startup
try:
    from recovery_manager.db.database import init_db_schema, seed_data_from_csvs
    init_db_schema()
    seed_data_from_csvs()
except Exception as _db_err:
    print(f"[App DB Warning] Initial DB setup skipped: {_db_err}")


# ── Run on sample data ────────────────────────────────────

@app.route("/api/run", methods=["GET"])
def run_sample():
    org = request.args.get("org") or None
    try:
        result = run_from_files(org_id_filter=org)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Upload ────────────────────────────────────────────────

@app.route("/api/upload", methods=["POST"])
def upload_and_run():
    def _read(key: str) -> str:
        f = request.files.get(key)
        return f.read().decode("utf-8", errors="replace") if f else ""

    fee_text = _read("fee_report")
    if not fee_text:
        return jsonify({"error": "fee_report file is required"}), 400

    org = request.form.get("org") or None
    try:
        result = run_from_text(
            fee_text=fee_text,
            receiving_text=_read("receiving"),
            prep_text=_read("prep"),
            pack_text=_read("pack"),
            returns_text=_read("returns"),
            org_id_filter=org,
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Charge detail ─────────────────────────────────────────

@app.route("/api/charge/<line_id>")
def charge_detail(line_id: str):
    fee_rows = _load_csv(DATA_DIR / "fee_report_sample.csv")
    rcv_rows = _load_csv(UPSTREAM_DIR / "receiving_sample.csv")
    prp_rows = _load_csv(UPSTREAM_DIR / "prep_sample.csv")
    pck_rows = _load_csv(UPSTREAM_DIR / "pack_sample.csv")
    rtn_rows = _load_csv(UPSTREAM_DIR / "returns_sample.csv")

    charges = parse_fee_report(fee_rows)
    upstream_index = build_upstream_index(rcv_rows, prp_rows, pck_rows, rtn_rows)

    charge = next((c for c in charges if c.line_id == line_id), None)
    if charge is None:
        return jsonify({"error": f"Charge {line_id!r} not found"}), 404

    upstream = upstream_index.get(charge.unit_id)
    bundle = match_charge(charge, upstream)

    from dataclasses import asdict
    return jsonify({
        "charge": asdict(charge),
        "upstream_found": bundle.upstream_found,
        "evidence_fields": [asdict(f) for f in bundle.fields],
        "raw_upstream": bundle.raw_upstream,
    })


# ── SLA policy ────────────────────────────────────────────

@app.route("/api/policy")
def policy():
    return jsonify(CLAIM_POLICY)


# ── Orgs ──────────────────────────────────────────────────

@app.route("/api/orgs")
def orgs():
    rows = _load_csv(DATA_DIR / "fee_report_sample.csv")
    org_set = sorted({r.get("org_id", "") for r in rows if r.get("org_id")})
    return jsonify(org_set)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    print(f"\n  Recovery Manager API → http://localhost:{port}")
    print(f"  UI                  → http://localhost:{port}/\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
