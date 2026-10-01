# AUDIX — AI-Powered Recovery Intelligence

> **Evidence-backed, rule-grounded, traceable decisions for Amazon FBA fee & reimbursement recovery.**

---

## Problem Understanding

Amazon FBA sellers routinely face erroneous charges — inbound receiving discrepancies, lost inventory, damaged goods, incorrect weight/dimension fees, and improper return dispositions. The scale of these charges is significant: mid-to-large sellers can lose tens of thousands of dollars annually to charges they never validate.

The core challenges are:

| Challenge | Impact |
|-----------|--------|
| **No evidence linkage** | Charges are reviewed in isolation without cross-referencing upstream operational records |
| **Policy complexity** | Amazon's reimbursement rules changed between V1 (pre-March 2025) and V2 (post-March 2025) — most tools apply one blindly |
| **Manual bottleneck** | Human review of each charge is time-consuming, error-prone, and unscalable |
| **Hallucinated claims** | AI-only systems fabricate justifications without verifiable evidence, creating legal and financial risk |
| **No audit trail** | Decisions cannot be defended to Amazon without a traceable, documented evidence chain |

---

## Solution Overview

**AUDIX** is an agentic AI recovery intelligence system that applies a deterministic, rule-grounded pipeline to every charge:

```
RULE + EVIDENCE → VERIFIABLE DECISION → CLAIM / DO NOT CLAIM / HUMAN REVIEW
```

**Key design principle:** AUDIX never fabricates a claim. Every decision is traceable to:
- The exact charge record
- The applicable Amazon policy rule (V1 or V2, by date)
- The upstream operational evidence (Receiving → Prep → Pack → Returns)
- The specific evidence fields used
- The custody window and time checks
- A SHA-256 cryptographic audit hash

### What AUDIX Does
1. **Ingests** fee/reimbursement reports and upstream operational CSVs
2. **Resolves** each charge to a unit identity (FNSKU, ASIN, shipment ID)
3. **Selects** the correct policy version based on charge posted date
4. **Retrieves** all relevant custody evidence across the 4 upstream stages
5. **Scores** claimability (0–100) with priority classification (CRITICAL / HIGH / MEDIUM / LOW)
6. **Generates** human-readable dispute language and claim packages
7. **Routes** ambiguous cases to a dedicated human review queue

---

## Setup Instructions

### Prerequisites
- Python 3.11+
- PostgreSQL (local or managed: Neon, Supabase, Railway)

### Installation

```bash
# 1. Clone
git clone https://github.com/BmvrssMeghana/cube26-rcy-0028-bmvrssmeghana.git
cd cube26-rcy-0028-bmvrssmeghana

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — set DATABASE_URL at minimum

# 4. Start server
python run.py
```

### Accessing the Application

| URL | Description |
|-----|-------------|
| `http://localhost:5000/` | Public landing page |
| `http://localhost:5000/app` | AUDIX workspace dashboard |
| `http://localhost:5000/demo` | Interactive synthetic demo |
| `http://localhost:5000/health` | Production health check |

---

## Usage Instructions

### Option 1 — Upload CSVs via Dashboard
1. Navigate to `http://localhost:5000/app`
2. Go to **Upload** in the sidebar
3. Upload your Fee/Reimbursement Report CSV + Upstream data CSVs
4. Click **Run Analysis** — results appear in the dashboard

### Option 2 — Use Sample Data
1. Navigate to `http://localhost:5000/app`
2. Click **Run Sample Analysis** from the dashboard
3. AUDIX runs on pre-loaded sample data in `data/`

### Option 3 — REST API
```bash
# Run analysis on sample data
GET /api/run

# Upload and analyze custom CSVs
POST /api/upload  (multipart: fee_report, receiving, prep, pack, returns)

# Get charge detail
GET /api/charge/<charge_id>

# Get claim package
GET /api/claim-package/<charge_id>

# Submit human override
POST /api/review  { charge_id, decision, notes }
```

### Reading Results

Each charge gets a **Verdict**:
| Verdict | Meaning |
|---------|---------|
| `Supported (Legit)` | Amazon charged correctly — do not dispute |
| `Contradicted (Claim)` | Evidence directly contradicts the charge — file claim |
| `Silent (No Evidence)` | No upstream evidence found — risky to claim |
| `Uncertain (Review)` | Conflicting signals — needs human review |
| `Duplicate Suppressed` | Claim already filed for this charge |

Each result includes a **Claimability Score** (0–100) and **Priority Level** to help prioritize which claims to file first.

---

## Assumptions & Limitations

### Assumptions
- Input CSVs follow the Amazon Seller Central export schema (or the upstream operational format used by the connected warehouse/3PL system)
- Charge posted dates are used to determine policy version (V1: before March 10, 2025 / V2: on or after March 10, 2025)
- FNSKU or shipment_id is used as the primary linking key between fee reports and upstream records
- The `data/upstream/` directory contains Receiving, Prep, Pack, and Returns CSVs

### Limitations
- AUDIX does not submit claims to Amazon directly — it generates the dispute language and claim package for human submission
- AUDIX does not have access to real-time Amazon Seller Central data; it operates on exported reports
- The LLM component (for human-readable reasoning generation) requires a valid API key configured server-side
- Multi-org isolation is implemented but full authentication (login/signup) is scaffolded for demo purposes; production deployment requires completing the auth flow
- The demo mode uses synthetic data and does not reflect live Amazon data

---

## Project Structure

```
cube26-rcy-0028-bmvrssmeghana/
├── run.py                          # Entry point
├── requirements.txt
├── .env.example                    # Environment configuration template
├── README.md
├── ARCHITECTURE.md
├── data/
│   ├── fee_report.csv              # Sample Amazon fee report
│   └── upstream/
│       ├── receiving.csv
│       ├── prep.csv
│       ├── pack.csv
│       └── returns.csv
└── recovery_manager/
    ├── api/
    │   └── app.py                  # Flask API + UI routes
    ├── engine/
    │   ├── runner.py               # End-to-end orchestration
    │   ├── ingestor.py             # CSV parsing + normalization
    │   ├── evidence_matcher.py     # Upstream entity resolution
    │   ├── sla_engine.py           # Policy Time Machine (V1/V2)
    │   └── classifier.py          # Claimability scoring
    ├── db/
    │   └── database.py             # PostgreSQL schema + queries
    └── ui/
        ├── index.html              # SPA shell
        ├── app.js                  # Client-side routing + UI logic
        ├── style.css               # Design system + component styles
        └── logo.svg                # Brand asset
```
