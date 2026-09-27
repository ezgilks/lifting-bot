"""Built-in exercise catalog and idempotent seeding."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Equipment, Exercise, MuscleGroup

logger = logging.getLogger(__name__)

# (canonical_name, aliases, muscle_group, equipment)
CATALOG: list[tuple[str, list[str], MuscleGroup, Equipment]] = [
    # --- chest ---
    (
        "Barbell Bench Press",
        ["bench", "bench press", "bb bench", "flat bench", "bp", "barbell bench"],
        MuscleGroup.chest,
        Equipment.barbell,
    ),
    (
        "Incline Barbell Bench Press",
        ["incline bench", "incline barbell bench", "incline bp", "incline press"],
        MuscleGroup.chest,
        Equipment.barbell,
    ),
    (
        "Dumbbell Bench Press",
        ["db bench", "dumbbell bench", "flat db press", "db press", "dumbbell press"],
        MuscleGroup.chest,
        Equipment.dumbbell,
    ),
    (
        "Incline Dumbbell Press",
        ["incline db press", "incline db bench", "incline dbs", "incline dumbbells"],
        MuscleGroup.chest,
        Equipment.dumbbell,
    ),
    (
        "Machine Chest Press",
        ["chest press", "machine press", "chest press machine", "hammer chest press"],
        MuscleGroup.chest,
        Equipment.machine,
    ),
    (
        "Cable Fly",
        ["cable flye", "cable flies", "cable crossover", "crossovers", "flys"],
        MuscleGroup.chest,
        Equipment.cable,
    ),
    (
        "Dumbbell Fly",
        ["db fly", "dumbbell flye", "db flies", "chest fly"],
        MuscleGroup.chest,
        Equipment.dumbbell,
    ),
    (
        "Pec Deck",
        ["pec dec", "pec deck machine", "butterfly machine", "machine fly"],
        MuscleGroup.chest,
        Equipment.machine,
    ),
    (
        "Push Up",
        ["pushup", "pushups", "push ups", "press ups"],
        MuscleGroup.chest,
        Equipment.bodyweight,
    ),
    (
        "Dip",
        ["dips", "chest dip", "parallel bar dips", "weighted dips"],
        MuscleGroup.chest,
        Equipment.bodyweight,
    ),
    # --- back ---
    (
        "Deadlift",
        ["dl", "deads", "conventional deadlift", "dead lift", "bb deadlift"],
        MuscleGroup.back,
        Equipment.barbell,
    ),
    (
        "Barbell Row",
        ["bb row", "bent over row", "barbell rows", "pendlay row", "bor"],
        MuscleGroup.back,
        Equipment.barbell,
    ),
    (
        "Dumbbell Row",
        ["db row", "one arm row", "single arm row", "dumbbell rows"],
        MuscleGroup.back,
        Equipment.dumbbell,
    ),
    (
        "Seated Cable Row",
        ["cable row", "seated row", "low row", "machine row"],
        MuscleGroup.back,
        Equipment.cable,
    ),
    (
        "Lat Pulldown",
        ["pulldown", "lat pull down", "pulldowns", "lats"],
        MuscleGroup.back,
        Equipment.cable,
    ),
    (
        "Pull Up",
        ["pullup", "pullups", "pull ups", "wide grip pullups"],
        MuscleGroup.back,
        Equipment.bodyweight,
    ),
    (
        "Chin Up",
        ["chinup", "chinups", "chin ups", "underhand pullups"],
        MuscleGroup.back,
        Equipment.bodyweight,
    ),
    (
        "T-Bar Row",
        ["tbar row", "tbar", "landmine row", "t bar rows"],
        MuscleGroup.back,
        Equipment.barbell,
    ),
    (
        "Chest Supported Row",
        ["chest supported rows", "csr", "seal row", "incline db row"],
        MuscleGroup.back,
        Equipment.machine,
    ),
    (
        "Straight Arm Pulldown",
        ["straight arm pushdown", "lat pushdown", "cable pullover"],
        MuscleGroup.back,
        Equipment.cable,
    ),
    (
        "Rack Pull",
        ["rack pulls", "block pull", "partial deadlift"],
        MuscleGroup.back,
        Equipment.barbell,
    ),
    (
        "Face Pull",
        ["face pulls", "rear delt cable pull", "cable face pull"],
        MuscleGroup.back,
        Equipment.cable,
    ),
    # --- quads ---
    (
        "Back Squat",
        ["squat", "squats", "bb squat", "barbell squat", "high bar squat", "low bar squat"],
        MuscleGroup.quads,
        Equipment.barbell,
    ),
    (
        "Front Squat",
        ["front squats", "fs", "front rack squat"],
        MuscleGroup.quads,
        Equipment.barbell,
    ),
    (
        "Leg Press",
        ["leg press machine", "legpress", "45 degree leg press"],
        MuscleGroup.quads,
        Equipment.machine,
    ),
    (
        "Hack Squat",
        ["hack squats", "machine hack squat", "hacks"],
        MuscleGroup.quads,
        Equipment.machine,
    ),
    (
        "Leg Extension",
        ["leg extensions", "quad extension", "leg ext", "knee extension"],
        MuscleGroup.quads,
        Equipment.machine,
    ),
    (
        "Bulgarian Split Squat",
        ["bss", "split squat", "bulgarians", "rear foot elevated split squat"],
        MuscleGroup.quads,
        Equipment.dumbbell,
    ),
    (
        "Walking Lunge",
        ["lunges", "walking lunges", "lunge", "db lunges"],
        MuscleGroup.quads,
        Equipment.dumbbell,
    ),
    (
        "Goblet Squat",
        ["goblet squats", "gobletsquat", "db goblet squat"],
        MuscleGroup.quads,
        Equipment.dumbbell,
    ),
    (
        "Step Up",
        ["step ups", "stepup", "box step up"],
        MuscleGroup.quads,
        Equipment.dumbbell,
    ),
    # --- hamstrings ---
    (
        "Romanian Deadlift",
        ["rdl", "rdls", "romanian dl", "stiff leg deadlift", "sldl"],
        MuscleGroup.hamstrings,
        Equipment.barbell,
    ),
    (
        "Lying Leg Curl",
        ["leg curl", "leg curls", "hamstring curl", "lying hamstring curl"],
        MuscleGroup.hamstrings,
        Equipment.machine,
    ),
    (
        "Seated Leg Curl",
        ["seated hamstring curl", "seated curls machine", "seated leg curls"],
        MuscleGroup.hamstrings,
        Equipment.machine,
    ),
    (
        "Good Morning",
        ["good mornings", "gm", "barbell good morning"],
        MuscleGroup.hamstrings,
        Equipment.barbell,
    ),
    (
        "Nordic Curl",
        ["nordics", "nordic ham curl", "nordic hamstring curl"],
        MuscleGroup.hamstrings,
        Equipment.bodyweight,
    ),
    # --- glutes ---
    (
        "Hip Thrust",
        ["hip thrusts", "barbell hip thrust", "thrusts", "glute bridge"],
        MuscleGroup.glutes,
        Equipment.barbell,
    ),
    (
        "Cable Kickback",
        ["glute kickback", "cable kickbacks", "kickbacks"],
        MuscleGroup.glutes,
        Equipment.cable,
    ),
    (
        "Hip Abduction",
        ["abduction machine", "hip abductor", "abductors", "glute machine"],
        MuscleGroup.glutes,
        Equipment.machine,
    ),
    (
        "Sumo Deadlift",
        ["sumo dl", "sumo deads", "sumo"],
        MuscleGroup.glutes,
        Equipment.barbell,
    ),
    # --- shoulders ---
    (
        "Overhead Press",
        ["ohp", "military press", "standing press", "shoulder press", "strict press"],
        MuscleGroup.shoulders,
        Equipment.barbell,
    ),
    (
        "Seated Dumbbell Shoulder Press",
        ["db shoulder press", "seated db press", "dumbbell ohp", "db overhead press"],
        MuscleGroup.shoulders,
        Equipment.dumbbell,
    ),
    (
        "Lateral Raise",
        ["lat raise", "side raise", "laterals", "lateral raises", "side lateral raise"],
        MuscleGroup.shoulders,
        Equipment.dumbbell,
    ),
    (
        "Rear Delt Fly",
        ["reverse fly", "rear delt flye", "rear delts", "reverse pec deck"],
        MuscleGroup.shoulders,
        Equipment.dumbbell,
    ),
    (
        "Arnold Press",
        ["arnolds", "arnold presses", "arnold db press"],
        MuscleGroup.shoulders,
        Equipment.dumbbell,
    ),
    (
        "Upright Row",
        ["upright rows", "cable upright row", "bb upright row"],
        MuscleGroup.shoulders,
        Equipment.barbell,
    ),
    (
        "Barbell Shrug",
        ["shrugs", "shrug", "db shrugs", "trap shrugs"],
        MuscleGroup.shoulders,
        Equipment.barbell,
    ),
    # --- biceps ---
    (
        "Barbell Curl",
        ["curls", "curl", "bb curl", "bicep curl", "straight bar curl"],
        MuscleGroup.biceps,
        Equipment.barbell,
    ),
    (
        "Dumbbell Curl",
        ["db curl", "db curls", "dumbbell curls", "alternating curls"],
        MuscleGroup.biceps,
        Equipment.dumbbell,
    ),
    (
        "Hammer Curl",
        ["hammers", "hammer curls", "neutral grip curl", "db hammer curl"],
        MuscleGroup.biceps,
        Equipment.dumbbell,
    ),
    (
        "Preacher Curl",
        ["preacher curls", "ez preacher curl", "machine preacher curl"],
        MuscleGroup.biceps,
        Equipment.machine,
    ),
    (
        "Cable Curl",
        ["cable curls", "rope curl", "cable bicep curl"],
        MuscleGroup.biceps,
        Equipment.cable,
    ),
    (
        "Incline Dumbbell Curl",
        ["incline curls", "incline db curl", "incline bicep curl"],
        MuscleGroup.biceps,
        Equipment.dumbbell,
    ),
    # --- triceps ---
    (
        "Close Grip Bench Press",
        ["cgbp", "close grip bench", "close grip press"],
        MuscleGroup.triceps,
        Equipment.barbell,
    ),
    (
        "Triceps Pushdown",
        ["pushdown", "pushdowns", "tricep pushdown", "rope pushdown", "cable pushdown"],
        MuscleGroup.triceps,
        Equipment.cable,
    ),
    (
        "Skullcrusher",
        ["skull crusher", "skullcrushers", "lying tricep extension", "ez skullcrusher"],
        MuscleGroup.triceps,
        Equipment.barbell,
    ),
    (
        "Overhead Triceps Extension",
        ["overhead extension", "tricep extension", "ohe", "cable overhead extension"],
        MuscleGroup.triceps,
        Equipment.cable,
    ),
    (
        "Triceps Kickback",
        ["tricep kickback", "db kickback", "tricep kickbacks"],
        MuscleGroup.triceps,
        Equipment.dumbbell,
    ),
    # --- calves ---
    (
        "Standing Calf Raise",
        ["calf raise", "calf raises", "standing calves", "calves"],
        MuscleGroup.calves,
        Equipment.machine,
    ),
    (
        "Seated Calf Raise",
        ["seated calves", "seated calf raises", "soleus raise"],
        MuscleGroup.calves,
        Equipment.machine,
    ),
    # --- core ---
    (
        "Hanging Leg Raise",
        ["leg raises", "hanging leg raises", "hlr", "hanging knee raise"],
        MuscleGroup.core,
        Equipment.bodyweight,
    ),
    (
        "Cable Crunch",
        ["cable crunches", "rope crunch", "kneeling cable crunch"],
        MuscleGroup.core,
        Equipment.cable,
    ),
    (
        "Plank",
        ["planks", "front plank", "elbow plank"],
        MuscleGroup.core,
        Equipment.bodyweight,
    ),
    (
        "Ab Wheel Rollout",
        ["ab wheel", "rollouts", "ab rollout"],
        MuscleGroup.core,
        Equipment.other,
    ),
    (
        "Russian Twist",
        ["russian twists", "twists", "seated twist"],
        MuscleGroup.core,
        Equipment.other,
    ),
    # --- full body ---
    (
        "Power Clean",
        ["clean", "cleans", "power cleans", "hang clean"],
        MuscleGroup.full_body,
        Equipment.barbell,
    ),
    (
        "Clean and Jerk",
        ["c&j", "clean and jerks", "cj"],
        MuscleGroup.full_body,
        Equipment.barbell,
    ),
    (
        "Snatch",
        ["snatches", "power snatch", "hang snatch"],
        MuscleGroup.full_body,
        Equipment.barbell,
    ),
    (
        "Farmer Carry",
        ["farmers walk", "farmer walk", "farmers carry", "carries"],
        MuscleGroup.full_body,
        Equipment.dumbbell,
    ),
    (
        "Kettlebell Swing",
        ["kb swing", "kb swings", "swings", "kettlebell swings"],
        MuscleGroup.full_body,
        Equipment.other,
    ),
    (
        "Burpee",
        ["burpees", "up downs", "squat thrust"],
        MuscleGroup.full_body,
        Equipment.bodyweight,
    ),
]


async def seed_exercises(session: AsyncSession) -> int:
    """Insert any built-in catalog entries the database is missing.

    Idempotent, and additive rather than all-or-nothing: entries added to
    ``CATALOG`` after the first boot still reach an existing database.
    Custom exercises and edited rows are never touched.

    Returns the number of rows inserted.
    """
    known = set(
        (
            await session.scalars(
                select(Exercise.canonical_name).where(Exercise.is_custom.is_(False))
            )
        ).all()
    )
    missing = [entry for entry in CATALOG if entry[0] not in known]
    if not missing:
        logger.info("Exercise catalog up to date (%s built-in exercises)", len(known))
        return 0

    session.add_all(
        [
            Exercise(
                canonical_name=name,
                aliases=aliases,
                muscle_group=group,
                equipment=equipment,
                is_custom=False,
                owner_user_id=None,
            )
            for name, aliases, group, equipment in missing
        ]
    )
    await session.commit()
    logger.info(
        "Seeded %s exercises: %s", len(missing), ", ".join(entry[0] for entry in missing)
    )
    return len(missing)
