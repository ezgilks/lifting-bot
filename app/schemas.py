"""Pydantic schemas: parser output, LLM contract, and API responses."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import Equipment, MuscleGroup, ParseMethod, Unit

# --------------------------------------------------------------------------
# Parser output (shared by the rules parser and the LLM fallback)
# --------------------------------------------------------------------------


class ParsedSet(BaseModel):
    """A single set as understood by the parser, before exercise resolution."""

    model_config = ConfigDict(frozen=True)

    reps: int = Field(ge=1, le=1000)
    weight: float | None = Field(default=None, ge=0, le=2000)
    unit: Unit = Unit.lb
    rpe: float | None = Field(default=None, ge=1, le=10)
    is_warmup: bool = False


class ParsedExercise(BaseModel):
    """One exercise mentioned in a message, with its sets in order."""

    name_raw: str = Field(min_length=1, max_length=120)
    sets: list[ParsedSet] = Field(min_length=1)


class ParsedWorkout(BaseModel):
    exercises: list[ParsedExercise] = Field(min_length=1)
    parse_method: ParseMethod


# --------------------------------------------------------------------------
# LLM contract — the exact JSON shape the model is asked to emit
# --------------------------------------------------------------------------


class LlmSet(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Nullable on purpose: a message can name a weight without a rep count.
    # Forcing an int here made the model invent one on retry.
    reps: int | None = Field(default=None, ge=1, le=1000)
    weight: float | None = Field(default=None, ge=0, le=2000)
    unit: Unit | None = None
    rpe: float | None = Field(default=None, ge=1, le=10)
    is_warmup: bool = False

    @field_validator("weight", "rpe", mode="before")
    @classmethod
    def _blank_to_none(cls, v: object) -> object:
        # Models occasionally emit "" or "null" instead of JSON null.
        if isinstance(v, str) and v.strip().lower() in {"", "null", "none", "bw"}:
            return None
        return v


class LlmExercise(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=120)
    sets: list[LlmSet] = Field(min_length=1)


class LlmWorkout(BaseModel):
    """Top-level LLM response. An empty list means "no workout data here"."""

    model_config = ConfigDict(extra="forbid")

    exercises: list[LlmExercise]


# --------------------------------------------------------------------------
# API responses
# --------------------------------------------------------------------------


class MuscleGroupSets(BaseModel):
    muscle_group: MuscleGroup
    hard_sets: int


class WeekPoint(BaseModel):
    iso_week: str
    week_start: date
    sessions: int
    hard_sets: dict[MuscleGroup, int]
    total_hard_sets: int


class StalledExercise(BaseModel):
    exercise_id: int
    name: str
    slope_per_week: float
    sessions: int


class BodyweightPoint(BaseModel):
    weight: float
    unit: Unit
    recorded_on: date


class OverviewResponse(BaseModel):
    unit: Unit
    sessions_this_week: int
    hard_sets_this_week: list[MuscleGroupSets]
    total_hard_sets_this_week: int
    total_hard_sets_last_week: int
    weekly_hard_sets: list[WeekPoint]
    current_streak_days: int
    stalled: list[StalledExercise]
    bodyweight: BodyweightPoint | None


class ExerciseSummary(BaseModel):
    id: int
    name: str
    muscle_group: MuscleGroup
    equipment: Equipment
    session_count: int
    hard_sets: int
    last_trained_on: date | None
    top_weight: float | None


class SetDetail(BaseModel):
    set_id: int
    set_index: int
    reps: int
    weight: float | None
    unit: Unit
    rpe: float | None
    is_warmup: bool


class SessionDetail(BaseModel):
    workout_id: int
    performed_on: date
    sets: list[SetDetail]
    hard_sets: int
    top_weight: float | None
    top_reps: int | None


class SeriesPoint(BaseModel):
    performed_on: date
    value: float
    reps: int | None = None


class TrendInfo(BaseModel):
    slope_per_week: float | None
    intercept: float | None
    sessions: int
    is_stalled: bool
    first_session_on: date | None


class NextTargetResponse(BaseModel):
    kind: str
    weight: float | None
    unit: Unit
    target_reps: int
    sets: int
    reason: str


class ExerciseDetailResponse(BaseModel):
    id: int
    name: str
    muscle_group: MuscleGroup
    equipment: Equipment
    unit: Unit
    sessions: list[SessionDetail]
    top_weight_series: list[SeriesPoint]
    trend: TrendInfo
    next_target: NextTargetResponse | None


class SetUpdate(BaseModel):
    """Partial edit of one set. Omitted fields are left untouched."""

    model_config = ConfigDict(extra="forbid")

    reps: int | None = Field(default=None, ge=1, le=1000)
    weight: float | None = Field(default=None, ge=0, le=2000)
    rpe: float | None = Field(default=None, ge=1, le=10)
    is_warmup: bool | None = None
    # Explicit nulling, which an omitted field cannot express.
    clear_weight: bool = False
    clear_rpe: bool = False


class ParserStatsResponse(BaseModel):
    rules_hits: int
    llm_hits: int
    rules_share: float
    process_rules_hits: int
    process_llm_hits: int
    process_llm_failures: int
