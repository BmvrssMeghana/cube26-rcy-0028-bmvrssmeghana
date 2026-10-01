"""
PostgreSQL Database Layer — Recovery Manager
Manages database connection, table creation, data seeding from CSVs,
and persistent claim audit log storage.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT_DIR / "data"
UPSTREAM_DIR = DATA_DIR / "upstream"

# Connection parameters
PG_HOST = os.environ.get("POSTGRES_HOST", "localhost")
PG_PORT = int(os.environ.get("POSTGRES_PORT", 5432))
PG_USER = os.environ.get("POSTGRES_USER", "postgres")
PG_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "root")
PG_DBNAME = os.environ.get("POSTGRES_DB", "recovery_db")


def get_pg_connection(dbname: str | None = None):
    """Establish connection to PostgreSQL."""
    if not PSYCOPG2_AVAILABLE:
        raise RuntimeError("psycopg2 is not installed.")
    
    target_db = dbname or PG_DBNAME
    return psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        dbname=target_db
    )


def ensure_database_exists():
    """Create the target database if it does not already exist."""
    if not PSYCOPG2_AVAILABLE:
        return False
    try:
        # Connect to default 'postgres' database to check/create target database
        conn = psycopg2.connect(
            host=PG_HOST,
            port=PG_PORT,
            user=PG_USER,
            password=PG_PASSWORD,
            dbname="postgres"
        )
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (PG_DBNAME,))
        exists = cur.fetchone()
        if not exists:
            cur.execute(f'CREATE DATABASE "{PG_DBNAME}";')
            print(f"[DB] Created database '{PG_DBNAME}' in PostgreSQL.")
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB Warning] Could not ensure database '{PG_DBNAME}': {e}")
        return False


def init_db_schema():
    """Create schema tables for fee charges, upstream records, and recovery claims."""
    if not ensure_database_exists():
        return False

    try:
        conn = get_pg_connection()
        cur = conn.cursor()

        # 1. Fee charges table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS fee_charges (
                line_id VARCHAR(100) PRIMARY KEY,
                report_type VARCHAR(100),
                unit_id VARCHAR(100),
                org_id VARCHAR(100),
                sku VARCHAR(100),
                fnsku VARCHAR(100),
                fba_shipment_id VARCHAR(100),
                order_id VARCHAR(100),
                charge_type VARCHAR(100),
                quantity INT,
                amount_usd NUMERIC(10, 2),
                posted_date VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 2. Receiving table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS upstream_receiving (
                record_id VARCHAR(100) PRIMARY KEY,
                unit_id VARCHAR(100),
                org_id VARCHAR(100),
                po_number VARCHAR(100),
                po_line VARCHAR(50),
                supplier VARCHAR(150),
                sku VARCHAR(100),
                asin VARCHAR(100),
                product_title TEXT,
                qty_ordered INT,
                qty_received INT,
                identity_match VARCHAR(20),
                carton_damage VARCHAR(100),
                unit_damage VARCHAR(100),
                photo_refs TEXT,
                operator_id VARCHAR(100),
                captured_at VARCHAR(50)
            );
        """)

        # 3. Prep table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS upstream_prep (
                record_id VARCHAR(100) PRIMARY KEY,
                unit_id VARCHAR(100),
                org_id VARCHAR(100),
                work_order_id VARCHAR(100),
                fba_shipment_id VARCHAR(100),
                sku VARCHAR(100),
                asin VARCHAR(100),
                fnsku VARCHAR(100),
                prep_price_usd NUMERIC(10, 2),
                polybag_present_sealed VARCHAR(50),
                suffocation_warning VARCHAR(50),
                fnsku_label_placement VARCHAR(50),
                original_barcode_covered VARCHAR(50),
                photo_refs TEXT,
                operator_id VARCHAR(100),
                captured_at VARCHAR(50)
            );
        """)

        # 4. Pack table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS upstream_pack (
                record_id VARCHAR(100) PRIMARY KEY,
                unit_id VARCHAR(100),
                org_id VARCHAR(100),
                outbound_shipment_id VARCHAR(100),
                sku VARCHAR(100),
                fnsku VARCHAR(100),
                units_packed INT,
                pack_status VARCHAR(50),
                operator_id VARCHAR(100),
                captured_at VARCHAR(50)
            );
        """)

        # 5. Returns table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS upstream_returns (
                record_id VARCHAR(100) PRIMARY KEY,
                unit_id VARCHAR(100),
                org_id VARCHAR(100),
                order_id VARCHAR(100),
                ordered_sku VARCHAR(100),
                ordered_asin VARCHAR(100),
                identity_match VARCHAR(20),
                observed_state VARCHAR(100),
                operator_disposition VARCHAR(100),
                photo_refs TEXT,
                operator_id VARCHAR(100),
                captured_at VARCHAR(50)
            );
        """)

        # 6. Claim audit log table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS claim_audit_logs (
                id SERIAL PRIMARY KEY,
                line_id VARCHAR(100),
                unit_id VARCHAR(100),
                org_id VARCHAR(100),
                charge_type VARCHAR(100),
                amount_usd NUMERIC(10, 2),
                verdict VARCHAR(50),
                confidence_score NUMERIC(5, 2),
                claim_amount NUMERIC(10, 2),
                sla_status VARCHAR(50),
                dispute_rationale TEXT,
                evidence_summary JSONB,
                duplicate_flag VARCHAR(100),
                evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 7. Human Overrides Audit Log (USP #14 & USP #15)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS human_overrides (
                id SERIAL PRIMARY KEY,
                line_id VARCHAR(100),
                engine_verdict VARCHAR(50),
                human_override VARCHAR(50),
                reviewer_id VARCHAR(100),
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        conn.commit()
        cur.close()
        conn.close()
        print("[DB] PostgreSQL database tables initialized successfully.")
        return True
    except Exception as e:
        print(f"[DB Error] Schema initialization failed: {e}")
        return False


def seed_data_from_csvs():
    """Populate PostgreSQL database from data/ and data/upstream/ CSV files if tables are empty."""
    import csv

    if not PSYCOPG2_AVAILABLE:
        return False

    try:
        conn = get_pg_connection()
        cur = conn.cursor()

        # Seed fee_charges
        cur.execute("SELECT COUNT(*) FROM fee_charges;")
        if cur.fetchone()[0] == 0:
            fee_file = DATA_DIR / "fee_report_sample.csv"
            if fee_file.exists():
                with open(fee_file, newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        cur.execute("""
                            INSERT INTO fee_charges 
                            (line_id, report_type, unit_id, org_id, sku, fnsku, fba_shipment_id, order_id, charge_type, quantity, amount_usd, posted_date)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (line_id) DO NOTHING;
                        """, (
                            r.get("line_id", ""), r.get("report_type", ""), r.get("unit_id", ""),
                            r.get("org_id", ""), r.get("sku", ""), r.get("fnsku", ""),
                            r.get("fba_shipment_id", ""), r.get("order_id", ""), r.get("charge_type", ""),
                            int(r.get("quantity", 1) or 1), float(r.get("amount_usd", 0.0) or 0.0),
                            r.get("posted_date", "")
                        ))
                print("[DB Seed] Seeded fee_charges from CSV.")

        # Seed upstream_receiving
        cur.execute("SELECT COUNT(*) FROM upstream_receiving;")
        if cur.fetchone()[0] == 0:
            rcv_file = UPSTREAM_DIR / "receiving_sample.csv"
            if rcv_file.exists():
                with open(rcv_file, newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        cur.execute("""
                            INSERT INTO upstream_receiving 
                            (record_id, unit_id, org_id, po_number, po_line, supplier, sku, asin, product_title, qty_ordered, qty_received, identity_match, carton_damage, unit_damage, photo_refs, operator_id, captured_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (record_id) DO NOTHING;
                        """, (
                            r.get("record_id", ""), r.get("unit_id", ""), r.get("org_id", ""),
                            r.get("po_number", ""), r.get("po_line", ""), r.get("supplier", ""),
                            r.get("sku", ""), r.get("asin", ""), r.get("product_title", ""),
                            int(r.get("qty_ordered", 0) or 0), int(r.get("qty_received", 0) or 0),
                            r.get("identity_match", ""), r.get("carton_damage", ""), r.get("unit_damage", ""),
                            r.get("photo_refs", ""), r.get("operator_id", ""), r.get("captured_at", "")
                        ))
                print("[DB Seed] Seeded upstream_receiving from CSV.")

        # Seed upstream_prep
        cur.execute("SELECT COUNT(*) FROM upstream_prep;")
        if cur.fetchone()[0] == 0:
            prp_file = UPSTREAM_DIR / "prep_sample.csv"
            if prp_file.exists():
                with open(prp_file, newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        cur.execute("""
                            INSERT INTO upstream_prep 
                            (record_id, unit_id, org_id, work_order_id, fba_shipment_id, sku, asin, fnsku, prep_price_usd, polybag_present_sealed, suffocation_warning, fnsku_label_placement, original_barcode_covered, photo_refs, operator_id, captured_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (record_id) DO NOTHING;
                        """, (
                            r.get("record_id", ""), r.get("unit_id", ""), r.get("org_id", ""),
                            r.get("work_order_id", ""), r.get("fba_shipment_id", ""), r.get("sku", ""),
                            r.get("asin", ""), r.get("fnsku", ""), float(r.get("prep_price_usd", 0.0) or 0.0),
                            r.get("polybag_present_sealed", ""), r.get("suffocation_warning", ""),
                            r.get("fnsku_label_placement", ""), r.get("original_barcode_covered", ""),
                            r.get("photo_refs", ""), r.get("operator_id", ""), r.get("captured_at", "")
                        ))
                print("[DB Seed] Seeded upstream_prep from CSV.")

        # Seed upstream_pack
        cur.execute("SELECT COUNT(*) FROM upstream_pack;")
        if cur.fetchone()[0] == 0:
            pck_file = UPSTREAM_DIR / "pack_sample.csv"
            if pck_file.exists():
                with open(pck_file, newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        cur.execute("""
                            INSERT INTO upstream_pack 
                            (record_id, unit_id, org_id, outbound_shipment_id, sku, fnsku, units_packed, pack_status, operator_id, captured_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (record_id) DO NOTHING;
                        """, (
                            r.get("record_id", ""), r.get("unit_id", ""), r.get("org_id", ""),
                            r.get("outbound_shipment_id", ""), r.get("sku", ""), r.get("fnsku", ""),
                            int(r.get("units_packed", 0) or 0), r.get("pack_status", ""),
                            r.get("operator_id", ""), r.get("captured_at", "")
                        ))
                print("[DB Seed] Seeded upstream_pack from CSV.")

        # Seed upstream_returns
        cur.execute("SELECT COUNT(*) FROM upstream_returns;")
        if cur.fetchone()[0] == 0:
            rtn_file = UPSTREAM_DIR / "returns_sample.csv"
            if rtn_file.exists():
                with open(rtn_file, newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        cur.execute("""
                            INSERT INTO upstream_returns 
                            (record_id, unit_id, org_id, order_id, ordered_sku, ordered_asin, identity_match, observed_state, operator_disposition, photo_refs, operator_id, captured_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (record_id) DO NOTHING;
                        """, (
                            r.get("record_id", ""), r.get("unit_id", ""), r.get("org_id", ""),
                            r.get("order_id", ""), r.get("ordered_sku", ""), r.get("ordered_asin", ""),
                            r.get("identity_match", ""), r.get("observed_state", ""),
                            r.get("operator_disposition", ""), r.get("photo_refs", ""),
                            r.get("operator_id", ""), r.get("captured_at", "")
                        ))
                print("[DB Seed] Seeded upstream_returns from CSV.")

        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB Seed Error] {e}")
        return False


def save_claim_audit_logs(decisions: list[dict[str, Any]]):
    """Persist run decision audit logs into PostgreSQL."""
    if not PSYCOPG2_AVAILABLE:
        return
    try:
        conn = get_pg_connection()
        cur = conn.cursor()
        for d in decisions:
            cur.execute("""
                INSERT INTO claim_audit_logs 
                (line_id, unit_id, org_id, charge_type, amount_usd, verdict, confidence_score, claim_amount, sla_status, dispute_rationale, evidence_summary, duplicate_flag)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """, (
                d.get("line_id", ""), d.get("unit_id", ""), d.get("org_id", ""),
                d.get("charge_type", ""), float(d.get("amount_usd", 0.0) or 0.0),
                d.get("verdict", ""), float(d.get("confidence_score", 1.0) or 1.0),
                float(d.get("claim_amount", 0.0) or 0.0), d.get("sla_status", ""),
                d.get("dispute_rationale", "") or d.get("reasoning", ""),
                json.dumps(d.get("evidence_summary", {})),
                d.get("duplicate_flag", "")
            ))
        conn.commit()
        cur.close()
        conn.close()
        print(f"[DB Audit] Persisted {len(decisions)} claim audit decisions to PostgreSQL.")
    except Exception as e:
        print(f"[DB Audit Error] Failed to save claim logs: {e}")


def save_human_override(line_id: str, engine_verdict: str, human_override: str, reviewer_id: str = "human_operator", reason: str = "") -> bool:
    """Save an append-only human override audit log without mutating engine decisions."""
    if not PSYCOPG2_AVAILABLE:
        return False
    try:
        conn = get_pg_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO human_overrides (line_id, engine_verdict, human_override, reviewer_id, reason)
            VALUES (%s, %s, %s, %s, %s);
        """, (line_id, engine_verdict, human_override, reviewer_id, reason))
        conn.commit()
        cur.close()
        conn.close()
        print(f"[DB Override] Saved human override for {line_id}: {human_override}")
        return True
    except Exception as e:
        print(f"[DB Override Error] Failed to save override: {e}")
        return False
