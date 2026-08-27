# AI-Powered Candidate Intelligence and Job Readiness Platform — Phase 1

Full-stack implementation: a FastAPI backend (`app/`) and a React frontend (`frontend/`) that
walks a candidate through the entire Phase 1 pipeline from the spec:

```
Resume -> Parse -> Structure -> RAG Ingestion -> Detect Gaps -> Ask Questions ->
Complete Profile -> Recommend Roles -> Candidate Selects Roles -> Adaptive Assessment ->
Benchmark -> Identify Improvement Areas
```

## 1. Backend setup

```bash
cd candidate-platform
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# then edit .env and set ANTHROPIC_API_KEY
```

Run it:

```bash
uvicorn app.main:app --reload
```

API docs (interactive): http://localhost:8000/docs

SQLite database file and Chroma vector store are created automatically on first run in the
project folder. Swap `DATABASE_URL` in `.env` for a Postgres URL later with no code changes
(SQLAlchemy handles both).

## 2. Frontend setup

In a second terminal, with the backend already running on port 8000:

```bash
cd candidate-platform/frontend
npm install
npm run dev
```

Open http://localhost:5173 — the dev server proxies `/api/*` calls straight to the backend
(see `vite.config.js`), so no extra CORS setup is needed locally. The app walks through:
register/login → upload resume → answer gap-fill questions → pick recommended roles → take an
adaptive assessment per role → view the readiness benchmark, in one continuous flow.

For a production build: `npm run build` outputs static files to `frontend/dist/`, deployable to
any static host — just point it at your deployed backend URL and update `allow_origins` in
`app/main.py`'s CORS middleware to match your frontend's real domain.

## 3. End-to-end flow (matches the spec's 11 stages)

| # | Endpoint | Stage |
|---|----------|-------|
| 1 | `POST /auth/register`, `POST /auth/login` | Candidate login/registration |
| 2-4 | `POST /resume/upload` | Upload → parse → RAG ingestion (one call does all three) |
| 5 | `GET /profile/me` | View completeness score + missing fields |
| 6 | `GET /gap-fill/next-question` → `POST /gap-fill/answer` (loop) | Gap-filling conversation |
| 7 | `GET /profile/me` | Unified candidate profile |
| 8 | `POST /roles/recommend` | Role recommendation (~5 roles) |
| 9 | `POST /roles/select` | Candidate picks 1-3 roles |
| 10 | `POST /assessment/start` → `POST /assessment/answer` (loop) | Adaptive assessment |
| 11 | `GET /benchmark/session/{session_id}` | Readiness benchmark + improvement plan |

### Typical client sequence

1. `POST /auth/register` → get JWT, send as `Authorization: Bearer <token>` on every call after.
2. `POST /resume/upload` (multipart file) → profile auto-populated, completeness score returned.
3. Loop: `GET /gap-fill/next-question` → ask candidate → `POST /gap-fill/answer` → repeat until
   `"done": true`.
4. `POST /roles/recommend` → show ~5 roles to candidate.
5. `POST /roles/select` with 1-3 chosen role titles.
6. For each selected role: `POST /assessment/start {"target_role": "..."}` → loop
   `POST /assessment/answer` with the candidate's answer to each returned question until
   `"is_final": true`.
7. `GET /benchmark/session/{session_id}` → readiness score, dimension breakdown, strengths,
   weaknesses, and an improvement plan.

## 4. Design notes

- **Structured profile vs. RAG**: `CandidateProfile` (SQL/JSON columns) is the authoritative
  record used for completeness scoring, role recommendation, and benchmarking. Chroma
  (`app/services/rag_service.py`) stores chunked resume text and gap-fill answers separately, for
  retrieval-augmented context (e.g. pulling relevant project/experience snippets into assessment
  question generation). It intentionally never replaces the SQL profile.
- **Schema-driven completeness**: `app/schema_definitions.py` centralizes required/optional
  fields and category weights per the spec's Module 3 table. Change weights/fields there only.
- **Adaptive assessment**: each `POST /assessment/answer` call evaluates the just-submitted
  answer, adjusts difficulty per the spec's rules (correct→harder, partial→same-level follow-up,
  weak→easier/foundational), and generates the next question using the full turn history plus
  RAG-retrieved profile evidence — never a fixed question bank.
- **Benchmark**: computed only from real assessment turns + profile evidence (not just a
  correctness average), producing 8 dimension scores, an overall readiness score, a readiness
  label, and a concrete improvement plan (spec Module 8 / Section 12).
- **Auth** is a minimal JWT/bcrypt implementation sufficient for Phase 1; swap in your
  org's identity provider later without touching the pipeline modules.

## 5. Project layout

```
frontend/
  index.html, vite.config.js, package.json
  src/
    api.js                    Fetch wrapper (auth token, all endpoint calls)
    App.jsx                    Step orchestration (auth -> resume -> gapfill -> roles -> assessment -> benchmark)
    components/
      Login.jsx, ResumeUpload.jsx, GapFill.jsx, RoleRecommend.jsx, Assessment.jsx, Benchmark.jsx

app/
  main.py                 FastAPI app + router registration
  config.py                Environment-driven settings
  database.py               SQLAlchemy engine/session
  models.py                 ORM models (Candidate, Resume, CandidateProfile, ...)
  schemas.py                 Pydantic request/response models
  schema_definitions.py       Candidate info schema + completeness weights (Module 3)
  services/
    llm_service.py            Anthropic API wrapper (JSON-mode helper)
    resume_parser.py           Module 1: resume text -> structured JSON
    rag_service.py              Module 2: chunk/embed/retrieve via Chroma
    completeness.py              Module 3: completeness scoring
    gap_filling.py                 Module 4: next-question + answer merging
    role_recommendation.py          Module 6: role suggestions
    adaptive_assessment.py           Module 7: adaptive question gen + grading
    benchmarking.py                   Module 8: final benchmark generation
  routers/
    auth.py, resume.py, profile.py, gap_fill.py, roles.py, assessment.py, benchmark.py
  utils/
    security.py (JWT/password), pdf_extract.py (PDF/DOCX text extraction)
```

## 6. Out of scope (matches spec Section 15)

No recruiter portal, automatic job applications, external job crawling, interview scheduling,
offer management, payroll/onboarding, or LMS features are implemented here.
