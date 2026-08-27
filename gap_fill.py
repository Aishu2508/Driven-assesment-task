from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.utils.security import get_current_candidate

from app.services.completeness import (
    compute_completeness,
    is_complete_enough,
)

from app.services.gap_filling import (
    generate_next_gap_question,
    apply_gap_answer,
)

from app.services.rag_service import ingest_candidate_text


router = APIRouter(
    prefix="/gap-fill",
    tags=["gap-fill"],
)


# ============================================================
# PROFILE HELPER
# ============================================================

def _profile_dict(
    profile: models.CandidateProfile,
) -> dict:
    """
    Convert SQLAlchemy CandidateProfile into the dictionary
    expected by completeness and gap-filling services.
    """

    return {
        "identity": profile.identity or {},
        "education": profile.education or [],
        "experience": profile.experience or [],
        "projects": profile.projects or [],
        "skills": profile.skills or {},
        "career_preference": profile.career_preference or {},
        "evidence": profile.evidence or [],
    }


# ============================================================
# GET PROFILE
# ============================================================

def _get_profile(
    db: Session,
    candidate_id: str,
) -> models.CandidateProfile:

    profile = (
        db.query(models.CandidateProfile)
        .filter(
            models.CandidateProfile.candidate_id
            == candidate_id
        )
        .first()
    )

    if not profile:
        raise HTTPException(
            status_code=404,
            detail="Profile not found",
        )

    return profile


# ============================================================
# GET NEXT GAP QUESTION
# ============================================================

@router.get(
    "/next-question",
    response_model=schemas.GapQuestionOut,
)
def get_next_question(
    db: Session = Depends(get_db),
    current_candidate: models.Candidate = Depends(
        get_current_candidate
    ),
):

    profile = _get_profile(
        db,
        current_candidate.id,
    )

    profile_data = _profile_dict(profile)

    # --------------------------------------------------------
    # Calculate current completeness
    # --------------------------------------------------------

    score, missing = compute_completeness(
        profile_data
    )

    profile.completeness_score = score
    profile.missing_fields = missing

    db.commit()

    # --------------------------------------------------------
    # Check whether gap filling is complete
    # --------------------------------------------------------

    if is_complete_enough(score) or not missing:

        return schemas.GapQuestionOut(
            turn_id=None,
            field_targeted=None,
            question=None,
            completeness_score=score,
            missing_fields=missing,
            done=True,
        )

    # --------------------------------------------------------
    # Generate next question
    # --------------------------------------------------------

    next_q = generate_next_gap_question(
        profile_data,
        missing,
    )

    if not next_q:
        return schemas.GapQuestionOut(
            turn_id=None,
            field_targeted=None,
            question=None,
            completeness_score=score,
            missing_fields=missing,
            done=True,
        )

    field_targeted = next_q.get(
        "field_targeted"
    )

    question = next_q.get(
        "question"
    )

    if not field_targeted or not question:

        return schemas.GapQuestionOut(
            turn_id=None,
            field_targeted=None,
            question=None,
            completeness_score=score,
            missing_fields=missing,
            done=True,
        )

    # --------------------------------------------------------
    # Safety check
    #
    # Never allow the LLM to target a field that is not
    # actually missing.
    # --------------------------------------------------------

    if field_targeted not in missing:

        print(
            f"[GAP-FILL] Invalid target returned by LLM: "
            f"{field_targeted}"
        )

        return schemas.GapQuestionOut(
            turn_id=None,
            field_targeted=None,
            question=None,
            completeness_score=score,
            missing_fields=missing,
            done=True,
        )

    # --------------------------------------------------------
    # Save conversation turn
    # --------------------------------------------------------

    turn = models.GapConversationTurn(
        candidate_id=current_candidate.id,
        field_targeted=field_targeted,
        question=question,
    )

    db.add(turn)
    db.commit()
    db.refresh(turn)

    return schemas.GapQuestionOut(
        turn_id=turn.id,
        field_targeted=turn.field_targeted,
        question=turn.question,
        completeness_score=score,
        missing_fields=missing,
        done=False,
    )


# ============================================================
# SUBMIT GAP ANSWER
# ============================================================

@router.post(
    "/answer",
    response_model=schemas.GapQuestionOut,
)
def submit_answer(
    payload: schemas.GapAnswerIn,
    db: Session = Depends(get_db),
    current_candidate: models.Candidate = Depends(
        get_current_candidate
    ),
):

    # --------------------------------------------------------
    # Find question turn
    # --------------------------------------------------------

    turn = (
        db.query(models.GapConversationTurn)
        .filter(
            models.GapConversationTurn.id
            == payload.turn_id,
            models.GapConversationTurn.candidate_id
            == current_candidate.id,
        )
        .first()
    )

    if not turn:
        raise HTTPException(
            status_code=404,
            detail="Question turn not found",
        )

    # --------------------------------------------------------
    # Prevent duplicate answers
    # --------------------------------------------------------

    if turn.answer is not None:
        raise HTTPException(
            status_code=400,
            detail="This question has already been answered",
        )

    # --------------------------------------------------------
    # Validate answer
    # --------------------------------------------------------

    if not payload.answer or not payload.answer.strip():

        raise HTTPException(
            status_code=400,
            detail="Answer cannot be empty",
        )

    # --------------------------------------------------------
    # Save candidate answer
    # --------------------------------------------------------

    turn.answer = payload.answer

    db.commit()
    db.refresh(turn)

    # --------------------------------------------------------
    # Get candidate profile
    # --------------------------------------------------------

    profile = _get_profile(
        db,
        current_candidate.id,
    )

    profile_data = _profile_dict(profile)

    # --------------------------------------------------------
    # DEBUG: Profile BEFORE
    # --------------------------------------------------------

    print(
        "\n[GAP-FILL] ============================="
    )

    print(
        "[GAP-FILL] Profile BEFORE:"
    )

    print(
        profile_data
    )

    print(
        "[GAP-FILL] Target field:"
    )

    print(
        turn.field_targeted
    )

    print(
        "[GAP-FILL] Candidate answer:"
    )

    print(
        payload.answer
    )

    # --------------------------------------------------------
    # Apply answer ONLY to targeted field
    # --------------------------------------------------------

    updated_profile = apply_gap_answer(
        profile_data,
        turn.field_targeted or "",
        turn.question,
        payload.answer,
    )

    # --------------------------------------------------------
    # DEBUG: Profile AFTER
    # --------------------------------------------------------

    print(
        "[GAP-FILL] Profile AFTER:"
    )

    print(
        updated_profile
    )

    # --------------------------------------------------------
    # Update only known profile sections
    # --------------------------------------------------------

    allowed_fields = [
        "identity",
        "education",
        "experience",
        "projects",
        "skills",
        "career_preference",
        "evidence",
    ]

    for field in allowed_fields:

        if field in updated_profile:

            setattr(
                profile,
                field,
                updated_profile[field],
            )

    # --------------------------------------------------------
    # Make SQLAlchemy notice JSON changes
    # --------------------------------------------------------

    db.flush()

    # --------------------------------------------------------
    # Add answer to RAG
    # --------------------------------------------------------

    try:

        ingest_candidate_text(
            current_candidate.id,
            source="gap_answer",
            text=payload.answer,
        )

    except Exception as exc:

        # RAG failure must NOT prevent profile updating.

        print(
            f"\n[GAP-FILL] RAG ingestion failed: {exc}"
        )

    # --------------------------------------------------------
    # Recalculate completeness AFTER profile update
    # --------------------------------------------------------

    refreshed_profile_data = _profile_dict(
        profile
    )

    score, missing = compute_completeness(
        refreshed_profile_data
    )

    profile.completeness_score = score
    profile.missing_fields = missing

    db.commit()
    db.refresh(profile)

    # --------------------------------------------------------
    # DEBUG: Completeness
    # --------------------------------------------------------

    print(
        f"\n[GAP-FILL] Completeness score: {score}"
    )

    print(
        f"[GAP-FILL] Missing fields: {missing}"
    )

    # --------------------------------------------------------
    # Determine whether gap filling is complete
    # --------------------------------------------------------

    done = (
        is_complete_enough(score)
        or not missing
    )

    print(
        f"[GAP-FILL] Done: {done}"
    )

    print(
        "[GAP-FILL] =============================\n"
    )

    # --------------------------------------------------------
    # If complete, return completion response
    # --------------------------------------------------------

    if done:

        return schemas.GapQuestionOut(
            turn_id=turn.id,
            field_targeted=turn.field_targeted,
            question=turn.question,
            completeness_score=score,
            missing_fields=missing,
            done=True,
        )

    # --------------------------------------------------------
    # Generate NEXT question automatically
    # --------------------------------------------------------

    next_q = generate_next_gap_question(
        refreshed_profile_data,
        missing,
    )

    if not next_q:

        return schemas.GapQuestionOut(
            turn_id=turn.id,
            field_targeted=turn.field_targeted,
            question=turn.question,
            completeness_score=score,
            missing_fields=missing,
            done=False,
        )

    next_field = next_q.get(
        "field_targeted"
    )

    next_question = next_q.get(
        "question"
    )

    # --------------------------------------------------------
    # Safety check for next field
    # --------------------------------------------------------

    if (
        not next_field
        or not next_question
        or next_field not in missing
    ):

        return schemas.GapQuestionOut(
            turn_id=turn.id,
            field_targeted=turn.field_targeted,
            question=turn.question,
            completeness_score=score,
            missing_fields=missing,
            done=False,
        )

    # --------------------------------------------------------
    # Save next conversation turn
    # --------------------------------------------------------

    next_turn = models.GapConversationTurn(
        candidate_id=current_candidate.id,
        field_targeted=next_field,
        question=next_question,
    )

    db.add(next_turn)
    db.commit()
    db.refresh(next_turn)

    # --------------------------------------------------------
    # Return NEXT question
    # --------------------------------------------------------

    return schemas.GapQuestionOut(
        turn_id=next_turn.id,
        field_targeted=next_turn.field_targeted,
        question=next_turn.question,
        completeness_score=score,
        missing_fields=missing,
        done=False,
    )