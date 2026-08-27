from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.utils.security import get_current_candidate

router = APIRouter(prefix="/benchmark", tags=["benchmark"])


@router.get("/session/{session_id}", response_model=schemas.BenchmarkOut)
def get_benchmark_for_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_candidate: models.Candidate = Depends(get_current_candidate),
):
    benchmark = db.query(models.Benchmark).filter(
        models.Benchmark.session_id == session_id,
        models.Benchmark.candidate_id == current_candidate.id,
    ).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found (assessment may still be in progress)")
    return benchmark


@router.get("/all")
def list_my_benchmarks(
    db: Session = Depends(get_db),
    current_candidate: models.Candidate = Depends(get_current_candidate),
):
    benchmarks = db.query(models.Benchmark).filter(
        models.Benchmark.candidate_id == current_candidate.id
    ).all()
    return [schemas.BenchmarkOut.model_validate(b) for b in benchmarks]
