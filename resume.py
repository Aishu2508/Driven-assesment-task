import os
import shutil
import uuid

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.config import settings
from app.utils.security import get_current_candidate
from app.utils.pdf_extract import extract_text_from_file
from app.services.resume_parser import parse_resume_text
from app.services.rag_service import ingest_candidate_text
from app.services.completeness import compute_completeness

router = APIRouter(prefix="/resume", tags=["resume"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}


@router.post("/upload")
def upload_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_candidate: models.Candidate = Depends(get_current_candidate),
):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    # Stage 2: Save the original resume.
    stored_name = f"{current_candidate.id}_{uuid.uuid4().hex}{ext}"
    stored_path = os.path.join(settings.resume_storage_dir, stored_name)
    with open(stored_path, "wb") as out_file:
        shutil.copyfileobj(file.file, out_file)

    # Stage 3: Resume parsing - extract raw text, then structure it via LLM.
    raw_text = extract_text_from_file(stored_path)
    if not raw_text:
        raise HTTPException(status_code=422, detail="Could not extract text from the uploaded file")

    resume_record = models.Resume(
        candidate_id=current_candidate.id, file_path=stored_path, raw_text=raw_text
    )
    db.add(resume_record)
    db.commit()

    structured = parse_resume_text(raw_text)

    # Stage 4: RAG ingestion - store retrievable candidate knowledge.
    chunks_ingested = ingest_candidate_text(current_candidate.id, source="resume", text=raw_text)

    # Stage 5 (kick-off): merge structured data into the profile and score completeness.
    profile = (
        db.query(models.CandidateProfile)
        .filter(models.CandidateProfile.candidate_id == current_candidate.id)
        .first()
    )
    if profile is None:
        profile = models.CandidateProfile(candidate_id=current_candidate.id)
        db.add(profile)

    profile.identity = structured.get("identity", {}) or profile.identity
    profile.education = structured.get("education", []) or profile.education
    profile.experience = structured.get("experience", []) or profile.experience
    profile.projects = structured.get("projects", []) or profile.projects
    profile.skills = structured.get("skills", {}) or profile.skills
    profile.career_preference = structured.get("career_preference", {}) or profile.career_preference
    profile.evidence = structured.get("evidence", []) or profile.evidence

    score, missing = compute_completeness({
        "identity": profile.identity, "education": profile.education,
        "experience": profile.experience, "projects": profile.projects,
        "skills": profile.skills, "career_preference": profile.career_preference,
        "evidence": profile.evidence,
    })
    profile.completeness_score = score
    profile.missing_fields = missing

    db.commit()
    db.refresh(profile)

    return {
        "resume_id": resume_record.id,
        "chunks_ingested_to_rag": chunks_ingested,
        "completeness_score": profile.completeness_score,
        "missing_fields": profile.missing_fields,
    }
