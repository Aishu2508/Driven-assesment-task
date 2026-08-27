# AI-Powered Candidate Intelligence & Job Readiness Platform

A FastAPI backend (+ React frontend) that takes a candidate from resume upload
through an AI-graded adaptive assessment to a final job-readiness benchmark.

```
Register/Login → Upload Resume → Parse & Structure → RAG Ingestion
     → Gap-Filling Q&A → Recommend Roles → Select Role(s)
     → Adaptive Assessment → Benchmark + Improvement Plan
```

---

## Table of Contents

1. [Tech Stack](#1-tech-stack)
2. [Setup](#2-setup)
3. [API Reference](#3-api-reference)
4. [End-to-End Flow](#4-end-to-end-flow)
5. [Design Notes](#5-design-notes)
6. [Project Layout](#6-project-layout)
7. [Out of Scope](#7-out-of-scope)

---

## 1. Tech Stack

| Technology | Purpose |
|---|---|
| Python / FastAPI | Backend REST API |
| SQLAlchemy + SQLite/PostgreSQL | Candidate, profile, and assessment data |
| Pydantic | Request/response validation |
| Anthropic Claude (LLM) | Resume parsing, gap-fill extraction, adaptive question generation, grading, benchmarking |
| Chroma (vector DB) | RAG — semantic retrieval of candidate evidence |
| React + Vite | Frontend |
| Swagger / OpenAPI | Interactive API docs |

---

## 2. Setup

### Backend

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

- Swagger UI: `http://127.0.0.1:8000/docs`
- Raw OpenAPI spec: `http://127.0.0.1:8000/openapi.json`

SQLite and the Chroma vector store are created automatically on first run.
Swap `DATABASE_URL` in `.env` for a Postgres URL later with no code changes.

> **Note on Swagger access:** `127.0.0.1:8000/docs` only works on the machine
> running the server. To let someone else (e.g. a reviewer) open Swagger
> remotely, deploy the API or expose it via a tunnel and share that URL instead.

### Frontend

In a second terminal, with the backend already running on port 8000:

```bash
cd candidate-platform/frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The dev server proxies `/api/*` to the backend
(see `vite.config.js`), so no extra CORS setup is needed locally.

Production build: `npm run build` → static files in `frontend/dist/`. Deploy
to any static host, point it at your deployed backend URL, and update
`allow_origins` in `app/main.py`'s CORS middleware to your real frontend domain.

---

## 3. API Reference

All endpoints except `/auth/register`, `/auth/login`, and `/health` require:

```
Authorization: Bearer <access_token>
```

### Authentication

**`POST /auth/register`**
```json
{ "email": "arjun@email.com", "password": "Test@12345", "full_name": "Arjun Patel" }
```
→ `201 Created`
```json
{ "access_token": "eyJhbGciOi...", "token_type": "bearer" }
```
Errors: `400` if email already registered.

**`POST /auth/login`** — OAuth2 password flow, **form-encoded**, not JSON (so
Swagger's Authorize button works out of the box):

| Field | Value |
|---|---|
| `username` | candidate's email |
| `password` | candidate's password |

→ `200 OK`, same token shape as register. Errors: `401` on bad credentials.

### Resume

**`POST /resume/upload`** — `multipart/form-data`, field `file` (`.pdf`, `.docx`, `.txt`).
Parses text, structures it via LLM, ingests into RAG, and merges into the profile.

→ `200 OK`
```json
{
  "resume_id": "b3f1c2...",
  "chunks_ingested_to_rag": 14,
  "completeness_score": 0.42,
  "missing_fields": ["identity.location", "experience.entry 1: company"]
}
```
Errors: `400` unsupported file type · `422` text could not be extracted.

### Profile

**`GET /profile/me`** → full structured profile + completeness state.
```json
{
  "candidate_id": "9c11...",
  "identity": {}, "education": [], "experience": [], "projects": [],
  "skills": {}, "career_preference": {}, "evidence": [],
  "completeness_score": 0.42,
  "missing_fields": ["identity.location"],
  "recommended_roles": [], "selected_roles": []
}
```
Errors: `404` no profile yet.

**`PATCH /profile/me`** — send only the fields to change:
```json
{ "identity": { "location": "Bengaluru, India" } }
```
→ `200 OK`, same shape as `GET /profile/me`. Errors: `404`.

### Gap Filling

**`GET /gap-fill/next-question`** → next missing field as a question, or `done: true`.
```json
{
  "turn_id": "1234...",
  "field_targeted": "experience.entry 1: company",
  "question": "What company did you work for?",
  "completeness_score": 0.42,
  "missing_fields": ["experience.entry 1: company"],
  "done": false
}
```
Errors: `404` no profile.

**`POST /gap-fill/answer`**
```json
{ "turn_id": "1234...", "answer": "I worked at ABC Technologies." }
```
→ same shape as above, recalculated. Errors: `404` unknown/foreign `turn_id`.

### Roles

**`POST /roles/recommend`** → requires completeness above threshold.
```json
{
  "recommended_roles": [
    { "role_title": "AI/ML Engineer", "fit_score": 0.88,
      "reasoning": "Strong PyTorch and RAG experience.", "seniority_estimate": "Mid-level" }
  ]
}
```
Errors: `404` no profile · `400` completeness too low.

**`POST /roles/select`**
```json
{ "roles": ["AI/ML Engineer", "Backend Engineer"] }
```
→ `{ "selected_roles": [...] }`. Errors: `400` not 1–3 roles · `404` no profile.

### Adaptive Assessment

**`POST /assessment/start`**
```json
{ "target_role": "AI/ML Engineer" }
```
→ `200 OK`
```json
{
  "session_id": "66a01705-bddf-4f60-abd1-ccefd2fa25ca",
  "turn_id": "2f1a...", "sequence": 1,
  "competency": "Machine Learning", "difficulty": "medium",
  "question": "Explain how you would handle fault tolerance in an AI system.",
  "is_final": false
}
```
Errors: `404` no profile.

**`POST /assessment/answer`**
```json
{
  "session_id": "66a01705-bddf-4f60-abd1-ccefd2fa25ca",
  "turn_id": "2f1a...",
  "answer": "I would use retries, monitoring, fallback mechanisms and redundant services..."
}
```
→ same shape as `/assessment/start`; `is_final: true` ends the session and
triggers benchmark generation automatically (fetch via `/benchmark/session/{id}`).
Length is adaptive with a hard cap of 12 questions. Errors: `404` unknown/foreign turn/session.

### Benchmark

**`GET /benchmark/session/{session_id}`**
```json
{
  "target_role": "AI/ML Engineer",
  "technical_fundamentals": 0.9167, "role_specific_knowledge": 0.9167,
  "practical_implementation": 0.9167, "project_depth": 0.9167,
  "problem_solving": 0.9167, "conceptual_clarity": 0.9167,
  "communication_quality": 0.9167, "profile_evidence_strength": 0.9167,
  "overall_readiness_score": 0.9167, "readiness_level": "Ready",
  "strengths": ["Strong understanding of fault tolerance in AI systems"],
  "weaknesses": [],
  "improvement_plan": ["Gain more experience with production ML deployment"]
}
```
Errors: `404` no benchmark yet (assessment may still be in progress).

**`GET /benchmark/all`** → array of every benchmark for the authenticated candidate.

**Readiness classification:** `overall_readiness_score >= 0.65` → `"Ready"`,
otherwise `"Needs Improvement"`.

### Health

**`GET /health`** (no auth) → `{ "status": "ok" }`

### Status Codes

| Status | Meaning |
|---|---|
| 200 | Success |
| 201 | Resource created (`/auth/register`) |
| 400 | Bad request (duplicate email, bad role count, profile not complete enough) |
| 401 | Invalid credentials / missing or invalid token |
| 404 | Resource not found (profile, turn, session, benchmark) |
| 500 | Unexpected server error |

> The generic **422 "Validation Error"** response that FastAPI auto-adds to
> every endpoint has been removed from the Swagger docs (see `custom_openapi()`
> in `app/main.py`) — it was pure clutter for this API. Malformed requests
> still return a real `422` at runtime; only the boilerplate doc entry is gone.

---

## 4. End-to-End Flow

| # | Endpoint | Stage |
|---|---|---|
| 1 | `POST /auth/register`, `POST /auth/login` | Candidate registration/login |
| 2 | `POST /resume/upload` | Upload → parse → RAG ingestion → profile merge |
| 3 | `GET /profile/me` | View completeness score + missing fields |
| 4 | `GET /gap-fill/next-question` ↔ `POST /gap-fill/answer` (loop) | Gap-filling conversation until `done: true` |
| 5 | `POST /roles/recommend` | Get ~5 suggested roles |
| 6 | `POST /roles/select` | Candidate picks 1–3 roles |
| 7 | `POST /assessment/start` ↔ `POST /assessment/answer` (loop) | Adaptive assessment per role until `is_final: true` |
| 8 | `GET /benchmark/session/{session_id}` | Readiness score, breakdown, strengths/weaknesses, improvement plan |

---

## 5. Design Notes

- **Structured profile vs. RAG.** `CandidateProfile` (SQL/JSON columns) is the
  authoritative record used for completeness scoring, role recommendation, and
  benchmarking. Chroma (`app/services/rag_service.py`) stores chunked resume
  text and gap-fill answers separately for retrieval-augmented context (e.g.
  pulling relevant project/experience snippets into assessment question
  generation). It never replaces the SQL profile.
- **Schema-driven completeness.** `app/schema_definitions.py` centralizes
  required/optional fields and category weights. Change weights/fields there only.
- **Adaptive assessment.** Each `POST /assessment/answer` evaluates the
  just-submitted answer, adjusts difficulty (correct → harder, partial → same
  level, weak → easier), and generates the next question from the full turn
  history plus RAG-retrieved profile evidence — never a fixed question bank.
- **Benchmark.** Computed from real assessment turns + profile evidence (not a
  simple correctness average), producing 8 dimension scores, an overall
  readiness score, a label, and a concrete improvement plan.
- **Auth** is a minimal JWT/bcrypt implementation sufficient for Phase 1; swap
  in your org's identity provider later without touching the pipeline modules.
- **Swagger cleanliness.** `app/main.py` overrides `openapi()` to strip the
  auto-generated 422 responses/schemas from the docs page (see [status codes](#status-codes) above).

---

## 6. Project Layout

```
frontend/
  index.html, vite.config.js, package.json
  src/
    api.js                     Fetch wrapper (auth token, all endpoint calls)
    App.jsx                    Step orchestration (auth -> resume -> gapfill -> roles -> assessment -> benchmark)
    components/
      Login.jsx, ResumeUpload.jsx, GapFill.jsx, RoleRecommend.jsx, Assessment.jsx, Benchmark.jsx

app/
  main.py                  FastAPI app, router registration, Swagger customization
  config.py                Environment-driven settings
  database.py               SQLAlchemy engine/session
  models.py                  ORM models (Candidate, Resume, CandidateProfile, ...)
  schemas.py                  Pydantic request/response models
  schema_definitions.py        Candidate info schema + completeness weights
  services/
    llm_service.py             Anthropic API wrapper (JSON-mode helper)
    resume_parser.py            Resume text -> structured JSON
    rag_service.py               Chunk/embed/retrieve via Chroma
    completeness.py               Completeness scoring
    gap_filling.py                  Next-question + answer merging
    role_recommendation.py           Role suggestions
    adaptive_assessment.py            Adaptive question gen + grading
    benchmarking.py                    Final benchmark generation
  routers/
    auth.py, resume.py, profile.py, gap_fill.py, roles.py, assessment.py, benchmark.py
  utils/
    security.py (JWT/password), pdf_extract.py (PDF/DOCX text extraction)
```

---

## 7. Out of Scope

No recruiter portal, automatic job applications, external job crawling,
interview scheduling, offer management, payroll/onboarding, or LMS features
are implemented here.
