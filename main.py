from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.database import Base, engine
from app.routers import auth, resume, profile, gap_fill, roles, assessment, benchmark

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AI-Powered Candidate Intelligence and Job Readiness Platform",
    description="Phase 1: profile building, gap filling, role recommendation, adaptive assessment.",
    version="0.1.0",
)


def custom_openapi():
    """
    FastAPI auto-adds a generic 422 "Validation Error" response (and its
    HTTPValidationError/ValidationError schemas) to every endpoint that takes a
    body/query/path parameter. That's noise in Swagger UI for this API, so this
    strips the 422 entry from each operation's responses and drops the two
    unused schemas from the components section after the schema is built.
    """
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    for path in schema.get("paths", {}).values():
        for operation in path.values():
            operation.get("responses", {}).pop("422", None)

    schemas = schema.get("components", {}).get("schemas", {})
    schemas.pop("HTTPValidationError", None)
    schemas.pop("ValidationError", None)

    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi

# Allow the local Vite dev server / frontend to call this API directly.
# Tighten allow_origins to your real frontend domain(s) before deploying.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(resume.router)
app.include_router(profile.router)
app.include_router(gap_fill.router)
app.include_router(roles.router)
app.include_router(assessment.router)
app.include_router(benchmark.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
