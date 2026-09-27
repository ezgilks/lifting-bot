"""Dashboard endpoints, exercised over ASGI against a real (SQLite) database."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import issue_token
from app.api.routes import router
from app.db import get_db
from app.models import ParseMethod, Unit, User
from app.queries import fetch_set_rows, log_bodyweight, save_workout
from app.schemas import ParsedSet

TODAY = date.today()
BENCH = 1


@pytest.fixture
async def client(seeded_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    api = FastAPI()
    api.include_router(router)
    api.dependency_overrides[get_db] = lambda: seeded_session
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token(user.id)}"}


async def log(
    session: AsyncSession,
    user: User,
    day: date,
    exercise_id: int,
    reps: int,
    weight: float | None,
    sets: int = 3,
) -> None:
    await save_workout(
        session,
        user,
        day,
        f"{sets}x{reps} {weight}",
        ParseMethod.rules,
        [(exercise_id, [ParsedSet(reps=reps, weight=weight, unit=Unit.lb)] * sets)],
    )


@pytest.fixture
async def history(seeded_session: AsyncSession, user: User) -> int:
    """Five weeks of steadily heavier bench, one session per week."""
    for weeks_ago, weight in enumerate([170.0, 175.0, 180.0, 185.0, 190.0]):
        await log(
            seeded_session, user, TODAY - timedelta(weeks=4 - weeks_ago), BENCH, 8, weight
        )
    return BENCH


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------


async def test_endpoints_require_a_token(client: AsyncClient):
    for path in ("/api/overview", "/api/exercises", "/api/stats/parser"):
        assert (await client.get(path)).status_code == 401


async def test_a_garbage_token_is_rejected(client: AsyncClient):
    response = await client.get("/api/overview", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


async def test_a_token_for_an_unknown_user_is_rejected(client: AsyncClient):
    response = await client.get(
        "/api/overview", headers={"Authorization": f"Bearer {issue_token(9999)}"}
    )
    assert response.status_code == 401


# --------------------------------------------------------------------------
# overview -- sets per week, no pounds lifted anywhere
# --------------------------------------------------------------------------


async def test_overview_is_empty_but_valid_before_any_workouts(
    client: AsyncClient, user: User
):
    body = (await client.get("/api/overview", headers=auth(user))).json()
    assert body["sessions_this_week"] == 0
    assert body["hard_sets_this_week"] == []
    assert body["total_hard_sets_this_week"] == 0
    assert body["stalled"] == []
    assert body["bodyweight"] is None
    assert len(body["weekly_hard_sets"]) == 12


async def test_overview_counts_hard_sets_not_pounds(
    client: AsyncClient, seeded_session: AsyncSession, user: User
):
    await log(seeded_session, user, TODAY, BENCH, 8, 185.0)

    body = (await client.get("/api/overview", headers=auth(user))).json()
    assert body["sessions_this_week"] == 1
    assert body["hard_sets_this_week"] == [{"muscle_group": "chest", "hard_sets": 3}]
    assert body["total_hard_sets_this_week"] == 3
    assert body["weekly_hard_sets"][-1]["hard_sets"] == {"chest": 3}
    assert body["weekly_hard_sets"][-1]["total_hard_sets"] == 3
    # The volume-load metric is gone for good.
    assert "volume_load_this_week" not in body
    assert "volume_trend" not in body


async def test_warmups_do_not_count_as_hard_sets(
    client: AsyncClient, seeded_session: AsyncSession, user: User
):
    await save_workout(
        seeded_session,
        user,
        TODAY,
        "bench warmup then work",
        ParseMethod.rules,
        [
            (
                BENCH,
                [
                    ParsedSet(reps=10, weight=135.0, unit=Unit.lb, is_warmup=True),
                    ParsedSet(reps=8, weight=185.0, unit=Unit.lb),
                ],
            )
        ],
    )
    body = (await client.get("/api/overview", headers=auth(user))).json()
    assert body["total_hard_sets_this_week"] == 1


async def test_overview_reports_the_latest_bodyweight(
    client: AsyncClient, seeded_session: AsyncSession, user: User
):
    await log_bodyweight(seeded_session, user.id, 187.0, Unit.lb, TODAY)
    body = (await client.get("/api/overview", headers=auth(user))).json()
    assert body["bodyweight"] == {
        "weight": 187.0,
        "unit": "lb",
        "recorded_on": TODAY.isoformat(),
    }


# --------------------------------------------------------------------------
# exercises
# --------------------------------------------------------------------------


async def test_exercise_list_only_covers_what_was_trained(
    client: AsyncClient, user: User, history: int
):
    body = (await client.get("/api/exercises", headers=auth(user))).json()
    assert len(body) == 1
    assert body[0]["name"] == "Barbell Bench Press"
    assert body[0]["session_count"] == 5
    assert body[0]["hard_sets"] == 15
    assert body[0]["top_weight"] == 190.0


async def test_exercise_detail_trends_on_real_top_set_weight(
    client: AsyncClient, user: User, history: int
):
    body = (await client.get(f"/api/exercises/{history}", headers=auth(user))).json()

    assert len(body["sessions"]) == 5
    assert [p["value"] for p in body["top_weight_series"]] == [
        170.0,
        175.0,
        180.0,
        185.0,
        190.0,
    ]
    assert body["top_weight_series"][-1]["reps"] == 8
    assert body["sessions"][-1]["top_weight"] == 190.0
    assert body["sessions"][-1]["hard_sets"] == 3

    # +5 lb per week, exactly.
    assert body["trend"]["slope_per_week"] == pytest.approx(5.0)
    assert body["trend"]["is_stalled"] is False

    # No estimated numbers and no PR table anywhere in the payload.
    assert "e1rm_series" not in body
    assert "prs" not in body

    assert body["next_target"]["kind"] == "increase"
    assert body["next_target"]["weight"] == pytest.approx(192.5)


async def test_exercise_detail_404s_for_untrained_exercises(
    client: AsyncClient, user: User, history: int
):
    assert (await client.get("/api/exercises/2", headers=auth(user))).status_code == 404


async def test_a_stalled_exercise_shows_up_on_the_overview(
    client: AsyncClient, seeded_session: AsyncSession, user: User
):
    for days_ago in (14, 7, 0):
        await log(seeded_session, user, TODAY - timedelta(days=days_ago), BENCH, 5, 225.0)

    body = (await client.get("/api/overview", headers=auth(user))).json()
    assert [item["name"] for item in body["stalled"]] == ["Barbell Bench Press"]

    detail = (await client.get(f"/api/exercises/{BENCH}", headers=auth(user))).json()
    assert detail["trend"]["is_stalled"] is True
    assert detail["next_target"]["kind"] == "deload"


# --------------------------------------------------------------------------
# editing
# --------------------------------------------------------------------------


async def set_ids(client: AsyncClient, user: User, exercise_id: int) -> list[int]:
    body = (await client.get(f"/api/exercises/{exercise_id}", headers=auth(user))).json()
    return [s["set_id"] for session in body["sessions"] for s in session["sets"]]


async def test_editing_a_set_changes_reps_and_weight(
    client: AsyncClient, seeded_session: AsyncSession, user: User
):
    await log(seeded_session, user, TODAY, BENCH, 1, 200.0, sets=1)
    (set_id,) = await set_ids(client, user, BENCH)

    response = await client.patch(
        f"/api/sets/{set_id}", json={"reps": 6, "weight": 205}, headers=auth(user)
    )
    assert response.status_code == 200
    assert response.json()["reps"] == 6
    assert response.json()["weight"] == 205.0

    rows = await fetch_set_rows(seeded_session, user.id)
    assert (rows[0].reps, rows[0].weight) == (6, 205.0)


async def test_a_partial_edit_leaves_other_fields_alone(
    client: AsyncClient, seeded_session: AsyncSession, user: User
):
    await log(seeded_session, user, TODAY, BENCH, 8, 185.0, sets=1)
    (set_id,) = await set_ids(client, user, BENCH)

    body = (
        await client.patch(f"/api/sets/{set_id}", json={"reps": 9}, headers=auth(user))
    ).json()
    assert body["reps"] == 9
    assert body["weight"] == 185.0


async def test_a_set_can_be_marked_bodyweight(
    client: AsyncClient, seeded_session: AsyncSession, user: User
):
    await log(seeded_session, user, TODAY, BENCH, 8, 185.0, sets=1)
    (set_id,) = await set_ids(client, user, BENCH)

    body = (
        await client.patch(
            f"/api/sets/{set_id}", json={"clear_weight": True}, headers=auth(user)
        )
    ).json()
    assert body["weight"] is None


async def test_deleting_a_set_renumbers_the_rest(
    client: AsyncClient, seeded_session: AsyncSession, user: User
):
    await log(seeded_session, user, TODAY, BENCH, 8, 185.0, sets=3)
    ids = await set_ids(client, user, BENCH)

    assert (await client.delete(f"/api/sets/{ids[0]}", headers=auth(user))).status_code == 204

    rows = await fetch_set_rows(seeded_session, user.id)
    assert len(rows) == 2
    assert [r.set_index for r in rows] == [1, 2]


async def test_deleting_the_last_set_removes_the_workout(
    client: AsyncClient, seeded_session: AsyncSession, user: User
):
    await log(seeded_session, user, TODAY, BENCH, 8, 185.0, sets=1)
    (set_id,) = await set_ids(client, user, BENCH)

    await client.delete(f"/api/sets/{set_id}", headers=auth(user))
    assert await fetch_set_rows(seeded_session, user.id) == []
    body = (await client.get("/api/overview", headers=auth(user))).json()
    assert body["sessions_this_week"] == 0


async def test_deleting_a_workout_removes_all_of_its_sets(
    client: AsyncClient, seeded_session: AsyncSession, user: User
):
    await log(seeded_session, user, TODAY, BENCH, 8, 185.0, sets=3)
    rows = await fetch_set_rows(seeded_session, user.id)
    workout_id = rows[0].workout_id

    response = await client.delete(f"/api/workouts/{workout_id}", headers=auth(user))
    assert response.status_code == 204
    assert await fetch_set_rows(seeded_session, user.id) == []


async def test_edits_require_a_token(client: AsyncClient, seeded_session: AsyncSession, user: User):
    await log(seeded_session, user, TODAY, BENCH, 8, 185.0, sets=1)
    (set_id,) = await set_ids(client, user, BENCH)
    assert (await client.patch(f"/api/sets/{set_id}", json={"reps": 5})).status_code == 401
    assert (await client.delete(f"/api/sets/{set_id}")).status_code == 401


async def test_one_user_cannot_touch_another_users_sets(
    client: AsyncClient, seeded_session: AsyncSession, user: User
):
    """Ownership is re-checked server-side; the id alone is not authority."""
    await log(seeded_session, user, TODAY, BENCH, 8, 185.0, sets=1)
    (set_id,) = await set_ids(client, user, BENCH)

    intruder = User(telegram_chat_id=999, display_name="Someone Else", unit=Unit.lb)
    seeded_session.add(intruder)
    await seeded_session.commit()
    await seeded_session.refresh(intruder)

    assert (
        await client.patch(
            f"/api/sets/{set_id}", json={"reps": 99}, headers=auth(intruder)
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/sets/{set_id}", headers=auth(intruder))
    ).status_code == 404

    rows = await fetch_set_rows(seeded_session, user.id)
    assert rows[0].reps == 8  # untouched


async def test_editing_an_unknown_set_is_a_404(client: AsyncClient, user: User):
    assert (
        await client.patch("/api/sets/12345", json={"reps": 5}, headers=auth(user))
    ).status_code == 404


async def test_rejected_edits_do_not_reach_the_database(
    client: AsyncClient, seeded_session: AsyncSession, user: User
):
    await log(seeded_session, user, TODAY, BENCH, 8, 185.0, sets=1)
    (set_id,) = await set_ids(client, user, BENCH)

    assert (
        await client.patch(f"/api/sets/{set_id}", json={"reps": 0}, headers=auth(user))
    ).status_code == 422
    assert (
        await client.patch(
            f"/api/sets/{set_id}", json={"nonsense": 1}, headers=auth(user)
        )
    ).status_code == 422

    rows = await fetch_set_rows(seeded_session, user.id)
    assert rows[0].reps == 8


# --------------------------------------------------------------------------
# parser stats
# --------------------------------------------------------------------------


async def test_parser_stats_counts_workouts_by_tier(
    client: AsyncClient, seeded_session: AsyncSession, user: User
):
    await log(seeded_session, user, TODAY, BENCH, 8, 185.0)
    await save_workout(
        seeded_session,
        user,
        TODAY,
        "five sets of eight on incline dumbbell press",
        ParseMethod.llm,
        [(4, [ParsedSet(reps=8, weight=60.0, unit=Unit.lb)] * 5)],
    )

    body = (await client.get("/api/stats/parser", headers=auth(user))).json()
    assert body["rules_hits"] == 1
    assert body["llm_hits"] == 1
    assert body["rules_share"] == pytest.approx(0.5)
