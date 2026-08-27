from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr


# ---------- Auth ----------
class CandidateRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- Profile ----------
class ProfileOut(BaseModel):
    candidate_id: str
    identity: Dict[str, Any] = {}
    education: List[Dict[str, Any]] = []
    experience: List[Dict[str, Any]] = []
    projects: List[Dict[str, Any]] = []
    skills: Dict[str, Any] = {}
    career_preference: Dict[str, Any] = {}
    evidence: List[Dict[str, Any]] = []
    completeness_score: float = 0.0
    missing_fields: List[str] = []
    recommended_roles: List[Dict[str, Any]] = []
    selected_roles: List[str] = []

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    identity: Optional[Dict[str, Any]] = None
    education: Optional[List[Dict[str, Any]]] = None
    experience: Optional[List[Dict[str, Any]]] = None
    projects: Optional[List[Dict[str, Any]]] = None
    skills: Optional[Dict[str, Any]] = None
    career_preference: Optional[Dict[str, Any]] = None
    evidence: Optional[List[Dict[str, Any]]] = None


# ---------- Gap filling ----------
class GapAnswerIn(BaseModel):
    turn_id: str
    answer: str


class GapQuestionOut(BaseModel):
    turn_id: Optional[str]
    field_targeted: Optional[str]
    question: Optional[str]
    completeness_score: float
    missing_fields: List[str]
    done: bool


# ---------- Roles ----------
class RoleRecommendation(BaseModel):
    role_title: str
    fit_score: float
    reasoning: str
    seniority_estimate: str


class RoleSelectionIn(BaseModel):
    roles: List[str]


# ---------- Assessment ----------
class StartAssessmentIn(BaseModel):
    target_role: str


class AssessmentAnswerIn(BaseModel):
    session_id: str
    turn_id: str
    answer: str


class AssessmentQuestionOut(BaseModel):
    session_id: str
    turn_id: str
    sequence: int
    competency: Optional[str]
    difficulty: str
    question: str
    is_final: bool = False


# ---------- Benchmark ----------
class BenchmarkOut(BaseModel):
    target_role: str
    technical_fundamentals: float
    role_specific_knowledge: float
    practical_implementation: float
    project_depth: float
    problem_solving: float
    conceptual_clarity: float
    communication_quality: float
    profile_evidence_strength: float
    overall_readiness_score: float
    readiness_level: str
    strengths: List[str]
    weaknesses: List[str]
    improvement_plan: List[str]

    class Config:
        from_attributes = True
