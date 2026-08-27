from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.utils.security import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=schemas.Token, status_code=status.HTTP_201_CREATED)
def register(payload: schemas.CandidateRegister, db: Session = Depends(get_db)):
    existing = db.query(models.Candidate).filter(models.Candidate.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    candidate = models.Candidate(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)

    # Create an empty profile shell immediately so downstream modules always have one.
    profile = models.CandidateProfile(candidate_id=candidate.id)
    db.add(profile)
    db.commit()

    token = create_access_token(subject=candidate.id)
    return schemas.Token(access_token=token)


@router.post("/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """
    Accepts standard OAuth2 password-flow form data (username + password), where
    `username` is the candidate's email. This shape is required so Swagger UI's
    built-in "Authorize" button (and any standard OAuth2 client) works out of the
    box against this endpoint, since OAuth2PasswordBearer's tokenUrl always POSTs
    form-encoded username/password here - never JSON.
    """
    candidate = db.query(models.Candidate).filter(models.Candidate.email == form_data.username).first()
    if not candidate or not verify_password(form_data.password, candidate.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(subject=candidate.id)
    return schemas.Token(access_token=token)
