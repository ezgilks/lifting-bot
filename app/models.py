"""SQLAlchemy ORM models."""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# JSONB on Postgres, plain JSON on SQLite (used by the test suite).
AliasList = JSON().with_variant(JSONB(), "postgresql")


class MuscleGroup(str, enum.Enum):
    chest = "chest"
    back = "back"
    quads = "quads"
    hamstrings = "hamstrings"
    glutes = "glutes"
    shoulders = "shoulders"
    biceps = "biceps"
    triceps = "triceps"
    calves = "calves"
    core = "core"
    full_body = "full_body"


class Equipment(str, enum.Enum):
    barbell = "barbell"
    dumbbell = "dumbbell"
    machine = "machine"
    cable = "cable"
    bodyweight = "bodyweight"
    other = "other"


class Unit(str, enum.Enum):
    lb = "lb"
    kg = "kg"


class ParseMethod(str, enum.Enum):
    rules = "rules"
    llm = "llm"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Telegram chat ids exceed 32 bits for some chat types.
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    unit: Mapped[Unit] = mapped_column(
        SAEnum(Unit, name="unit"), default=Unit.lb, nullable=False
    )
    timezone: Mapped[str] = mapped_column(
        String(64), default="America/New_York", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    workouts: Mapped[list[Workout]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    bodyweights: Mapped[list[BodyweightEntry]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def today(self) -> date:
        """Current date in the user's own timezone."""
        try:
            zone = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            zone = ZoneInfo("UTC")
        return datetime.now(zone).date()


class Exercise(Base):
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(AliasList, default=list, nullable=False)
    muscle_group: Mapped[MuscleGroup] = mapped_column(
        SAEnum(MuscleGroup, name="muscle_group"), nullable=False
    )
    equipment: Mapped[Equipment] = mapped_column(
        SAEnum(Equipment, name="equipment"), nullable=False
    )
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )


class Workout(Base):
    __tablename__ = "workouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    performed_on: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    source_message: Mapped[str] = mapped_column(String(4000), nullable=False)
    parse_method: Mapped[ParseMethod] = mapped_column(
        SAEnum(ParseMethod, name="parse_method"), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="workouts")
    sets: Mapped[list[SetEntry]] = relationship(
        back_populates="workout",
        cascade="all, delete-orphan",
        order_by="SetEntry.id",
    )

    __table_args__ = (Index("ix_workouts_user_performed", "user_id", "performed_on"),)


class SetEntry(Base):
    __tablename__ = "set_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workout_id: Mapped[int] = mapped_column(
        ForeignKey("workouts.id", ondelete="CASCADE"), nullable=False
    )
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercises.id", ondelete="RESTRICT"), nullable=False
    )
    set_index: Mapped[int] = mapped_column(Integer, nullable=False)
    reps: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    unit: Mapped[Unit] = mapped_column(SAEnum(Unit, name="unit"), nullable=False)
    rpe: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    is_warmup: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    workout: Mapped[Workout] = relationship(back_populates="sets")
    exercise: Mapped[Exercise] = relationship(lazy="joined")

    __table_args__ = (Index("ix_set_entries_exercise_workout", "exercise_id", "workout_id"),)


class BodyweightEntry(Base):
    __tablename__ = "bodyweight_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    recorded_on: Mapped[date] = mapped_column(Date, nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    unit: Mapped[Unit] = mapped_column(SAEnum(Unit, name="unit"), nullable=False)

    user: Mapped[User] = relationship(back_populates="bodyweights")

    __table_args__ = (Index("ix_bodyweight_user_recorded", "user_id", "recorded_on"),)
