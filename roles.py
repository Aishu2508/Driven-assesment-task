from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.schemas import RoleSelectionIn
from app.utils.security import get_current_candidate
from app.services.role_recommendation import recommend_roles
from app.services.completeness import is_complete_enough

router = APIRouter(prefix="/roles", tags=["roles"])


@router.post("/recommend")
def get_role_recommendations(
    db: Session = Depends(get_db),
    current_candidate: models.Candidate = Depends(get_current_candidate),
):
    profile = (
        db.query(models.CandidateProfile)
        .filter(models.CandidateProfile.candidate_id == current_candidate.id)
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    if not is_complete_enough(profile.completeness_score):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Profile completeness ({profile.completeness_score:.0%}) is below the "
                "threshold needed for meaningful role recommendations. Finish gap-filling first."
            ),
        )

    roles = recommend_roles({
        "identity": profile.identity, "education": profile.education,
        "experience": profile.experience, "projects": profile.projects,
        "skills": profile.skills, "career_preference": profile.career_preference,
        "evidence": profile.evidence,
    })
    profile.recommended_roles = roles
    db.commit()
    return {"recommended_roles": roles}


@router.post("/select")
def select_roles(
    payload: RoleSelectionIn,
    db: Session = Depends(get_db),
    current_candidate: models.Candidate = Depends(get_current_candidate),
):
    if not (1 <= len(payload.roles) <= 3):
        raise HTTPException(status_code=400, detail="Select between 1 and 3 roles")

    profile = (
        db.query(models.CandidateProfile)
        .filter(models.CandidateProfile.candidate_id == current_candidate.id)
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    profile.selected_roles = payload.roles
    db.commit()
    return {"selected_roles": profile.selected_roles}
