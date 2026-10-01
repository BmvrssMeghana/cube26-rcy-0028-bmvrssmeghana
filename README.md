# AUDIX — AI-Powered Recovery Intelligence

**Evidence-backed recovery intelligence for Amazon fee & reimbursement claims.**

## Quick Start

```bash
# 1. Clone repository
git clone https://github.com/BmvrssMeghana/cube26-rcy-0028-bmvrssmeghana.git
cd cube26-rcy-0028-bmvrssmeghana

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy environment config
cp .env.example .env
# Edit .env with your DATABASE_URL

# 4. Start server
python run.py
```

Open http://localhost:5000 → Public landing page  
Open http://localhost:5000/app → AUDIX workspace dashboard

---

## Product Structure

| Route | Description |
|-------|-------------|
| `/` | Public landing page |
| `/app` | AUDIX workspace (dashboard, charges, claims) |
| `/demo` | Interactive synthetic demo |
| `/login` | Sign in |
| `/signup` | Register |
| `/about` | About AUDIX |
| `/privacy` | Privacy policy |
| `/terms` | Terms of service |

---

## Architecture

```
Browser (Public Landing + /app Dashboard)
   ↓
Flask Backend (recovery_manager/api/app.py)
   ↓
Agent Pipeline (recovery_manager/engine/)
  ├── ingestor.py        → Fee + upstream CSV parsing
  ├── evidence_matcher.py → Upstream entity resolution  
  ├── sla_engine.py      → Policy Time Machine (V1/V2)
  ├── classifier.py      → 0-100 Claimability scoring
  └── runner.py          → End-to-end orchestration
   ↓
PostgreSQL Database (recovery_manager/db/)
```

### Agent Roles
1. **Intake & Entity Agent** — normalizes charge line IDs, SKU/FNSKU, org scoping
2. **Policy RAG Agent** — selects V1 or V2 policy window by charge posted date
3. **Evidence Retriever Agent** — matches upstream custody records (Receiving→Prep→Pack→Returns)
4. **Recovery Decision Agent** — computes 0-100 claimability score + priority level
5. **Review & Critique Agent** — generates human-readable dispute language

**Deterministic Trust Layer**: Rule engine + SLA validation + duplicate suppression + SHA-256 audit hash

---

## Environment Variables

Copy `.env.example` to `.env`:

```
PORT=5000
DATABASE_URL=postgresql://user:pass@localhost:5432/recovery_db
CORS_ORIGINS=http://localhost:5000
JWT_SECRET=<change-in-production>
LLM_API_KEY=<server-side-only-never-expose>
```

**NEVER** expose `LLM_API_KEY` in frontend code. All LLM calls are server-side only.

---

## Production Deployment

### Backend (Render / Railway / Cloud Run)

```bash
# Start command
python run.py

# Health check endpoint
GET /health
```

### Environment
- Python 3.11+
- PostgreSQL (managed recommended: Neon, Supabase, Railway)
- Set `FLASK_DEBUG=false` in production
- Set `CORS_ORIGINS=https://your-domain.com`

---

## Security

- ✅ CORS restricted by `CORS_ORIGINS` env var
- ✅ Security headers: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`
- ✅ File upload validated: extension, MIME, 10MB limit
- ✅ SHA-256 cryptographic audit on every decision
- ✅ Multi-tenant `org_id` data isolation
- ✅ No LLM API keys in frontend code

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Production health check |
| GET | `/api/run` | Run analysis on sample data |
| POST | `/api/upload` | Upload CSVs and run analysis |
| GET | `/api/policy` | SLA policy rules (V1/V2) |
| GET | `/api/demo` | Synthetic demo response |
| GET | `/api/orgs` | Available organisations |
| GET | `/api/charge/<id>` | Charge detail + evidence |
| GET | `/api/claim-package/<id>` | Claim package JSON |
| POST | `/api/review` | Human override submission |

---

## License

AUDIX is proprietary software — built for evidence-backed Amazon FBA recovery.
