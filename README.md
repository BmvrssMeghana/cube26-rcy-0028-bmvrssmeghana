```markdown
# AUDIX — AI-Powered Recovery Intelligence

> **Evidence-backed, rule-grounded, traceable decisions for Amazon FBA fee & reimbursement recovery.**

AUDIX is an **agentic AI Recovery Manager** that analyzes Amazon fee and reimbursement charges against operational evidence and applicable policy rules to identify **defensible recovery opportunities**.

The system connects financial charges with the documented product journey across **Receiving, Prep, Pack, and Returns**, while enforcing policy, filing-window, duplicate, and claim-value checks.

---

## Problem

Sellers and e-commerce operators receive fees, reimbursements, and financial adjustments that may appear long after the operational event that caused them.

By that point, the evidence needed to validate or dispute the charge may be distributed across multiple operational systems.

This creates three core problems:

| Challenge | Impact |
|---|---|
| **Charges are isolated** | Financial reports do not contain the operational context needed to validate a charge |
| **Evidence is fragmented** | Receiving, preparation, packing, and return records are difficult to connect to individual charges |
| **Policy is complex** | Eligibility, filing windows, and reimbursement rules vary by charge type and applicable policy version |
| **Manual investigation** | Reviewing every charge against historical evidence does not scale |
| **Unsupported AI claims** | AI systems can generate convincing explanations without actual supporting evidence |
| **Poor traceability** | A recovery decision may not retain the evidence and rules used to reach it |

The result is a difficult question:

> **Is this charge actually defensible based on the rules and evidence available?**

---

## Solution

AUDIX answers that question using a **rule-grounded, evidence-first agentic architecture**.

```text
RULES + EVIDENCE
       ↓
AGENTIC ANALYSIS
       ↓
VERIFIED DECISION
       ↓
CLAIM / DO NOT CLAIM / HUMAN REVIEW
```

AUDIX does not optimize for the number of claims generated.

It optimizes for **defensible recovery**.

If evidence is missing, conflicting, or insufficient, AUDIX can explicitly return:

```text
SILENT — INSUFFICIENT EVIDENCE
```

rather than inventing a justification.

---

## Key Capabilities

- Fee and reimbursement report ingestion
- Charge parsing and normalization
- Shipment / Order / SKU / Unit entity resolution
- Policy and rule routing
- Evidence retrieval across upstream operational records
- Evidence validation and field-level citations
- Contradiction and support analysis
- SLA and filing-window validation
- Duplicate and already-reimbursed detection
- Claim amount validation
- Claimability assessment
- Self-critique of proposed recovery decisions
- Human review routing
- Evidence-backed claim package generation
- Complete decision audit trail
- Synthetic demo environment

---

## Agentic Architecture

![AUDIX Agentic Architecture](docs/architecture.png)

AUDIX uses a **hybrid agentic + deterministic architecture**.

### Agentic Layer

| Agent | Responsibility |
|---|---|
| **Intake & Entity Agent** | Parses charges and resolves Unit, SKU, Shipment and Order relationships |
| **Policy & Routing Agent** | Determines the applicable policy and evaluation scope |
| **Evidence Agent** | Retrieves, validates and compares relevant operational evidence |
| **Recovery Decision Agent** | Reasons over evidence, policy and recovery conditions |
| **Review & Critique Agent** | Challenges weak decisions and routes ambiguous cases for human review |

### Deterministic Trust Layer

Critical financial and policy operations are enforced deterministically:

- Policy rules
- SLA / filing windows
- Claim amounts
- Duplicate checks
- Reimbursement checks
- Evidence references
- Decision integrity
- Audit records

The design deliberately separates:

> **AI for reasoning from deterministic logic for financial and policy correctness.**

---

## Evidence Foundation

AUDIX consumes evidence generated throughout the product lifecycle:

- **Receiving Records**
- **Prep Records**
- **Pack Records**
- **Returns Records**

A charge is therefore evaluated against the operational evidence associated with the relevant unit, SKU, shipment, or order rather than being analyzed in isolation.

---

## Decision Model

Every charge receives a structured outcome.

| Verdict | Meaning |
|---|---|
| **CONTRADICTED** | Available evidence conflicts with the reason for the charge |
| **SUPPORTED** | Available evidence supports the charge |
| **SILENT** | No sufficient evidence exists to establish a defensible claim |
| **UNCERTAIN** | Evidence or applicable conditions are ambiguous or conflicting |
| **DUPLICATE SUPPRESSED** | A matching claim or reimbursement has already been identified |

A claim is not generated merely because a charge exists.

---

## Example

### Charge

```text
Charge ID: TC-01
Unit: U-TEST-01
Charge Type: Inbound Defect Fee
Amount: $2.50
```

### Evidence

```text
Prep Record: PRP-01

polybag_present_sealed = yes
suffocation_warning = legible
fnsku_label_placement = flat
```

### AUDIX Result

```text
VERDICT: CONTRADICTED

Potential Claim: $2.50

Reason:
Available preparation evidence indicates that the
required preparation conditions were satisfied.

Evidence:
PRP-01
```

The resulting decision retains the connection between the **charge, rule, evidence, and outcome**.

---

## Traceability

Every decision is designed to retain:

- Charge identifier
- Resolved entity information
- Applicable policy/rule
- Policy version
- Evidence records
- Evidence fields used
- Evidence timestamps
- Filing-window information
- Claim amount
- Decision
- Analysis run
- Audit information

AUDIX can therefore answer:

> **What was charged?**

> **Which rule was applied?**

> **What evidence was used?**

> **Why was the charge considered claimable or not?**

---

## Safety & Decision Integrity

AUDIX follows a strict evidence policy:

**No invented evidence.**

**No unsupported claims.**

**No forced conclusions.**

**No automatic claim when evidence is insufficient.**

When evidence does not support a conclusion, the system preserves uncertainty and routes the case for review where appropriate.

---

## Project Structure

```text
cube26-rcy-0028-bmvrssmeghana/
│
├── run.py
├── requirements.txt
├── .env.example
├── README.md
├── ARCHITECTURE.md
│
├── data/
│   ├── fee_report.csv
│   └── upstream/
│       ├── receiving.csv
│       ├── prep.csv
│       ├── pack.csv
│       └── returns.csv
│
└── recovery_manager/
    │
    ├── api/
    │   └── app.py
    │
    ├── engine/
    │   ├── runner.py
    │   ├── ingestor.py
    │   ├── evidence_matcher.py
    │   ├── sla_engine.py
    │   └── classifier.py
    │
    ├── db/
    │   └── database.py
    │
    └── ui/
        ├── index.html
        ├── app.js
        ├── style.css
        └── logo.svg
```

---

## Setup

### Requirements

- Python 3.11+
- PostgreSQL
- Valid LLM API key for AI-generated reasoning

### Installation

```bash
git clone https://github.com/BmvrssMeghana/cube26-rcy-0028-bmvrssmeghana.git

cd cube26-rcy-0028-bmvrssmeghana

pip install -r requirements.txt

cp .env.example .env
```

Configure the required environment variables in `.env`.

Then start AUDIX:

```bash
python run.py
```

---

## Application

| URL | Purpose |
|---|---|
| `/` | Public AUDIX landing page |
| `/app` | AUDIX recovery workspace |
| `/demo` | Synthetic interactive demonstration |
| `/health` | Application health check |

---

## Using AUDIX

### Upload Analysis

From the AUDIX workspace:

1. Upload the Fee / Reimbursement Report.
2. Upload available Receiving, Prep, Pack and Returns records.
3. Run the analysis.
4. Review the resulting decisions.
5. Open individual charges to inspect evidence, policy and reasoning.
6. Generate a claim package where applicable.

### Sample Analysis

AUDIX also provides sample data for demonstrating the complete recovery pipeline without requiring real seller data.

### REST API

```text
GET  /api/run
POST /api/upload
GET  /api/charge/<charge_id>
GET  /api/claim-package/<charge_id>
POST /api/review
```

---

## Security & Data Handling

AUDIX is designed so that LLM API credentials remain server-side.

Sensitive configuration is supplied through environment variables rather than committed to source code.

The public demo uses synthetic data and does not expose real seller records.

For production deployment, authentication, organisation-level access control, persistent file storage, and additional infrastructure hardening should be enabled according to the deployment environment.

---

## Limitations

- AUDIX operates on exported reports and supplied operational records; it does not directly access Amazon Seller Central.
- AUDIX generates evidence-backed claim packages but does not directly submit claims to Amazon.
- The quality of recovery decisions depends on the completeness and correctness of available operational evidence.
- Ambiguous cases may require human review.
- LLM-generated explanations require a configured server-side API provider.
- The included demo uses synthetic data.

---

## Design Philosophy

AUDIX is built around a simple principle:

> **A recovery claim is only as strong as the evidence and rules supporting it.**

Rather than treating an LLM response as the final authority, AUDIX combines:

**Policy + Evidence + Deterministic Validation + Agentic Reasoning + Human Review**

to produce recovery decisions that are **defensible, traceable, and explainable**.

---

## License

This project is developed as part of the Cube Hackathon.
```