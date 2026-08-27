import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.utils.security import get_current_candidate
from app.services.rag_service import retrieve_candidate_knowledge
from app.services.adaptive_assessment import generate_next_question, evaluate_answer
from app.services.benchmarking import generate_benchmark

router = APIRouter(prefix="/assessment", tags=["assessment"])

# Assessment rules
MAX_QUESTIONS_HARD_CAP = 3
PASSING_SCORE = 0.65


def _history_for_llm(session: models.AssessmentSession) -> list:
    return [
        {
            "sequence": t.sequence,
            "competency": t.competency,
            "difficulty": t.difficulty,
            "question": t.question,
            "answer": t.answer,
            "correctness_score": t.correctness_score,
        }
        for t in sorted(session.turns, key=lambda x: x.sequence)
    ]


def _calculate_assessment_score(
    session: models.AssessmentSession,
) -> float:
    """
    Calculate the final assessment score from all answered questions.

    Scores are expected to be between 0.0 and 1.0.
    Example:
        Q1 = 0.70
        Q2 = 0.60
        Q3 = 0.80
        Final = 0.70
    """

    answered_turns = [
        t for t in session.turns
        if t.answer is not None
    ]

    if not answered_turns:
        return 0.0

    scores = [
        float(t.correctness_score or 0.0)
        for t in answered_turns
    ]

    score = sum(scores) / len(scores)

    # Keep score safely between 0 and 1
    return max(0.0, min(score, 1.0))


@router.post(
    "/start",
    response_model=schemas.AssessmentQuestionOut,
)
def start_assessment(
    payload: schemas.StartAssessmentIn,
    db: Session = Depends(get_db),
    current_candidate: models.Candidate = Depends(get_current_candidate),
):
    profile = (
        db.query(models.CandidateProfile)
        .filter(
            models.CandidateProfile.candidate_id
            == current_candidate.id
        )
        .first()
    )

    if not profile:
        raise HTTPException(
            status_code=404,
            detail="Profile not found",
        )

    session = models.AssessmentSession(
        candidate_id=current_candidate.id,
        target_role=payload.target_role,
        current_difficulty="medium",
    )

    db.add(session)
    db.commit()
    db.refresh(session)

    return _ask_next(db, session, profile)


@router.post(
    "/answer",
    response_model=schemas.AssessmentQuestionOut,
)
def answer_question(
    payload: schemas.AssessmentAnswerIn,
    db: Session = Depends(get_db),
    current_candidate: models.Candidate = Depends(get_current_candidate),
):
    turn = (
        db.query(models.AssessmentTurn)
        .filter(
            models.AssessmentTurn.id == payload.turn_id
        )
        .first()
    )

    session = (
        db.query(models.AssessmentSession)
        .filter(
            models.AssessmentSession.id == payload.session_id,
            models.AssessmentSession.candidate_id
            == current_candidate.id,
        )
        .first()
    )

    if not turn or not session:
        raise HTTPException(
            status_code=404,
            detail="Assessment turn/session not found",
        )

    # Do not allow answers after assessment completion
    if session.status == "completed":
        raise HTTPException(
            status_code=400,
            detail="Assessment session is already completed",
        )

    # Do not allow the same question to be answered twice
    if turn.answer is not None:
        raise HTTPException(
            status_code=400,
            detail="This assessment turn has already been answered",
        )

    # Evaluate candidate's answer
    evaluation = evaluate_answer(
        session.target_role,
        turn.competency or "",
        turn.difficulty,
        turn.question,
        payload.answer,
    )

    # Get score safely
    score = float(
        evaluation.get("correctness_score", 0.0)
    )

    # Support both:
    # 0.75 = 75%
    # 75 = 75%
    if score > 1:
        score = score / 100

    # Keep score between 0 and 1
    score = max(0.0, min(score, 1.0))

    turn.answer = payload.answer
    turn.correctness_score = score
    turn.evaluation_notes = evaluation.get(
        "notes",
        "",
    )

    session.current_difficulty = evaluation.get(
        "recommended_next_difficulty",
        session.current_difficulty,
    )

    db.commit()
    db.refresh(session)

    profile = (
        db.query(models.CandidateProfile)
        .filter(
            models.CandidateProfile.candidate_id
            == current_candidate.id
        )
        .first()
    )

    # =========================================================
    # HARD LIMIT: MAXIMUM 3 QUESTIONS
    # =========================================================
    if turn.sequence >= MAX_QUESTIONS_HARD_CAP:

        _finalize_session(
            db,
            session,
            profile,
        )

        return schemas.AssessmentQuestionOut(
            session_id=session.id,
            turn_id=turn.id,
            sequence=turn.sequence,
            competency=turn.competency,
            difficulty=turn.difficulty,
            question="Assessment complete. Benchmark generated.",
            is_final=True,
        )

    # Generate next question
    return _ask_next(
        db,
        session,
        profile,
    )


def _ask_next(
    db: Session,
    session: models.AssessmentSession,
    profile: models.CandidateProfile,
):
    db.refresh(session)

    # Next question number
    sequence = len(session.turns) + 1

    # Never allow Question 4+
    if sequence > MAX_QUESTIONS_HARD_CAP:

        _finalize_session(
            db,
            session,
            profile,
        )

        last_turn = sorted(
            session.turns,
            key=lambda x: x.sequence,
        )[-1]

        return schemas.AssessmentQuestionOut(
            session_id=session.id,
            turn_id=last_turn.id,
            sequence=last_turn.sequence,
            competency=last_turn.competency,
            difficulty=last_turn.difficulty,
            question="Assessment complete. Benchmark generated.",
            is_final=True,
        )

    evidence_query = (
        f"experience and projects relevant to "
        f"{session.target_role}"
    )

    profile_evidence = retrieve_candidate_knowledge(
        session.candidate_id,
        evidence_query,
        top_k=5,
    )

    q = generate_next_question(
        target_role=session.target_role,
        profile_evidence=profile_evidence,
        history=_history_for_llm(session),
        current_difficulty=session.current_difficulty,
        sequence=sequence,
    )

    turn = models.AssessmentTurn(
        session_id=session.id,
        sequence=sequence,
        competency=q.get("competency"),
        difficulty=q.get(
            "difficulty",
            session.current_difficulty,
        ),
        question=q["question"],
    )

    db.add(turn)
    db.commit()
    db.refresh(turn)

    # Question 3 is always the final question
    is_final = sequence >= MAX_QUESTIONS_HARD_CAP

    return schemas.AssessmentQuestionOut(
        session_id=session.id,
        turn_id=turn.id,
        sequence=turn.sequence,
        competency=turn.competency,
        difficulty=turn.difficulty,
        question=turn.question,
        is_final=is_final,
    )


def _finalize_session(
    db: Session,
    session: models.AssessmentSession,
    profile: models.CandidateProfile,
):
    # =========================================================
    # CALCULATE ACTUAL SCORE FROM CANDIDATE ANSWERS
    # =========================================================

    assessment_score = _calculate_assessment_score(
        session
    )

    # =========================================================
    # 65% PASSING THRESHOLD
    # =========================================================

    passed = assessment_score >= PASSING_SCORE

    if passed:
        readiness_level = "Ready"
    else:
        readiness_level = "Needs Improvement"

    # Complete session
    session.status = "completed"
    session.completed_at = dt.datetime.utcnow()

    db.commit()
    db.refresh(session)

    # Profile evidence for benchmark generation
    profile_dict = {
        "projects": profile.projects,
        "experience": profile.experience,
        "evidence": profile.evidence,
    }

    # Generate qualitative benchmark information
    benchmark_data = generate_benchmark(
        session.target_role,
        _history_for_llm(session),
        profile_dict,
    )

    # =========================================================
    # SAVE BENCHMARK
    #
    # The numeric scores are based on the candidate's actual
    # assessment answers, NOT a fixed 0.95 score.
    # =========================================================

    benchmark = models.Benchmark(
        session_id=session.id,
        candidate_id=session.candidate_id,
        target_role=session.target_role,

        technical_fundamentals=assessment_score,
        role_specific_knowledge=assessment_score,
        practical_implementation=assessment_score,
        project_depth=assessment_score,
        problem_solving=assessment_score,
        conceptual_clarity=assessment_score,
        communication_quality=assessment_score,
        profile_evidence_strength=assessment_score,

        overall_readiness_score=assessment_score,

        readiness_level=readiness_level,

        strengths=benchmark_data.get(
            "strengths",
            [],
        ),

        weaknesses=benchmark_data.get(
            "weaknesses",
            [],
        ),

        improvement_plan=benchmark_data.get(
            "improvement_plan",
            [],
        ),
    )

    db.add(benchmark)
    db.commit()