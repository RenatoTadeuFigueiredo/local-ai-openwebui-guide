from __future__ import annotations

import concurrent.futures
from pathlib import Path

import pytest

from browser_hitl import store as store_module
from browser_hitl.store import (
    AGENT_ACTIVE,
    HUMAN_ACTIVE,
    READY_TO_RESUME,
    WAITING_FOR_HUMAN,
    Conflict,
    Locked,
    NotFound,
    Store,
)


def make_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "state.db", tmp_path / "audit.jsonl")
    store.initialize()
    return store


def create_session(store: Store, user_id: str = "user-a") -> dict:
    profile = store.provision_profile(user_id, user_id, f"{user_id}@example.com")
    return store.create_or_resume_session(user_id, "chat-1", "https://example.com", profile["runtime_slot"])


def test_access_email_change_revokes_active_takeover(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = create_session(store)
    token, _grant, _waiting = store.issue_takeover(
        session["session_id"], session["user_id"], session["epoch"], 300
    )
    grant, _human = store.redeem_takeover(token, 999_999_999_999)

    profile = store.provision_profile(
        session["user_id"],
        "Renamed",
        "replacement@example.com",
    )
    assert profile["_revoked_session_ids"] == [session["session_id"]]
    ready = store.session(session["session_id"], session["user_id"])
    assert ready["state"] == READY_TO_RESUME
    with pytest.raises(NotFound):
        store.active_grant(grant["grant_id"])


def test_profile_and_session_are_scoped_to_immutable_user(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session_a = create_session(store, "user-a")
    create_session(store, "user-b")

    with pytest.raises(NotFound):
        store.session(session_a["session_id"], "user-b")

    with pytest.raises(NotFound):
        store.assert_agent(session_a["session_id"], "user-b", session_a["epoch"])


def test_opening_existing_session_preserves_current_url(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = create_session(store)
    store.set_url(
        session["session_id"],
        session["user_id"],
        session["epoch"],
        "https://example.com/current",
    )

    reopened = store.create_or_resume_session(
        session["user_id"],
        "chat-2",
        "https://example.org/new-request",
        session["runtime_slot"],
    )
    assert reopened["session_id"] == session["session_id"]
    assert reopened["current_url"] == "https://example.com/current"
    assert reopened["chat_id"] == "chat-2"


def test_takeover_fences_agent_until_explicit_resume(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = create_session(store)
    token, grant, waiting = store.issue_takeover(
        session["session_id"], session["user_id"], session["epoch"], 300
    )
    assert waiting["state"] == WAITING_FOR_HUMAN
    assert waiting["epoch"] == session["epoch"] + 1

    with pytest.raises(Locked):
        store.assert_agent(session["session_id"], session["user_id"], session["epoch"])

    redeemed, human = store.redeem_takeover(token, 999_999_999_999)
    assert redeemed["status"] == "REDEEMED"
    assert human["state"] == HUMAN_ACTIVE

    with pytest.raises(Locked):
        store.assert_agent(session["session_id"], session["user_id"], human["epoch"])

    completed, ready = store.complete_takeover(redeemed["grant_id"])
    assert completed["status"] == "COMPLETED"
    assert ready["state"] == READY_TO_RESUME

    with pytest.raises(Conflict):
        store.assert_agent(session["session_id"], session["user_id"], ready["epoch"])

    resumed = store.resume_agent(session["session_id"], session["user_id"])
    assert resumed["state"] == AGENT_ACTIVE
    assert resumed["epoch"] == ready["epoch"] + 1
    store.assert_agent(session["session_id"], session["user_id"], resumed["epoch"])


def test_takeover_grant_is_stored_hashed(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = create_session(store)
    token, grant, _ = store.issue_takeover(
        session["session_id"], session["user_id"], session["epoch"], 300
    )
    assert token not in store.path.read_bytes().decode("utf-8", "ignore")
    assert grant["token_hash"] != token


def test_parallel_redemption_has_exactly_one_winner(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = create_session(store)
    token, _grant, _ = store.issue_takeover(
        session["session_id"], session["user_id"], session["epoch"], 300
    )

    def redeem() -> str:
        try:
            store.redeem_takeover(token, 999_999_999_999)
            return "ok"
        except (NotFound, Conflict):
            return "rejected"

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        outcomes = list(pool.map(lambda _: redeem(), range(20)))

    assert outcomes.count("ok") == 1
    assert outcomes.count("rejected") == 19


def test_restart_recovers_human_state_fail_closed(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = create_session(store)
    token, _grant, _ = store.issue_takeover(
        session["session_id"], session["user_id"], session["epoch"], 300
    )
    _grant, human = store.redeem_takeover(token, 999_999_999_999)
    assert human["state"] == HUMAN_ACTIVE

    assert store.recover_fail_closed() == 1
    recovered = store.session(session["session_id"], session["user_id"])
    assert recovered["state"] == READY_TO_RESUME
    with pytest.raises(NotFound):
        store.complete_takeover(_grant["grant_id"])


def test_operator_can_abort_unredeemed_takeover(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = create_session(store)
    token, _grant, _ = store.issue_takeover(
        session["session_id"], session["user_id"], session["epoch"], 300
    )
    assert store.abort_pending_takeovers() == 1
    recovered = store.session(session["session_id"], session["user_id"])
    assert recovered["state"] == READY_TO_RESUME
    with pytest.raises(NotFound):
        store.redeem_takeover(token, 999_999_999_999)


def test_operator_can_abort_redeemed_takeover(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = create_session(store)
    token, _grant, _waiting = store.issue_takeover(
        session["session_id"], session["user_id"], session["epoch"], 300
    )
    grant, _human = store.redeem_takeover(token, 999_999_999_999)
    assert store.abort_pending_takeovers() == 1
    recovered = store.session(session["session_id"], session["user_id"])
    assert recovered["state"] == READY_TO_RESUME
    with pytest.raises(NotFound):
        store.active_grant(grant["grant_id"])


def test_unredeemed_expired_grant_recovers_to_ready(tmp_path: Path, monkeypatch) -> None:
    current_time = 10_000
    monkeypatch.setattr(store_module, "now", lambda: current_time)
    store = make_store(tmp_path)
    session = create_session(store)
    token, _grant, waiting = store.issue_takeover(
        session["session_id"], session["user_id"], session["epoch"], 5
    )

    current_time += 6
    assert store.expire_issued_takeovers() == 1
    recovered = store.session(session["session_id"], session["user_id"])
    assert recovered["state"] == READY_TO_RESUME
    assert recovered["epoch"] == waiting["epoch"] + 1
    assert store.expire_issued_takeovers() == 0
    with pytest.raises(NotFound):
        store.redeem_takeover(token, 999_999_999_999)


def test_active_session_status_lazily_expires_unredeemed_grant(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current_time = 20_000
    monkeypatch.setattr(store_module, "now", lambda: current_time)
    store = make_store(tmp_path)
    session = create_session(store)
    store.issue_takeover(
        session["session_id"], session["user_id"], session["epoch"], 5
    )

    current_time += 6
    status = store.active_session_for_user(session["user_id"])
    assert status["state"] == READY_TO_RESUME


def test_redeemed_takeover_remains_completable_after_link_deadline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current_time = 30_000
    monkeypatch.setattr(store_module, "now", lambda: current_time)
    store = make_store(tmp_path)
    session = create_session(store)
    token, _grant, _waiting = store.issue_takeover(
        session["session_id"], session["user_id"], session["epoch"], 5
    )
    _grant, human = store.redeem_takeover(token, 999_999_999_999)

    current_time += 60
    with pytest.raises(NotFound):
        store.grant_by_token(token)
    assert store.active_grant(_grant["grant_id"])[1]["state"] == HUMAN_ACTIVE
    _grant, ready = store.complete_takeover(_grant["grant_id"])
    assert ready["state"] == READY_TO_RESUME
    assert ready["epoch"] == human["epoch"] + 1


def test_active_takeover_deadline_recovers_fail_closed(tmp_path: Path, monkeypatch) -> None:
    current_time = 40_000
    monkeypatch.setattr(store_module, "now", lambda: current_time)
    store = make_store(tmp_path)
    session = create_session(store)
    token, _grant, _waiting = store.issue_takeover(
        session["session_id"], session["user_id"], session["epoch"], 300
    )
    grant, human = store.redeem_takeover(token, current_time + 10)
    assert store.active_grant(grant["grant_id"])[1]["state"] == HUMAN_ACTIVE

    current_time += 11
    with pytest.raises(NotFound, match="expired"):
        store.active_grant(grant["grant_id"])
    ready = store.session(session["session_id"], session["user_id"])
    assert ready["state"] == READY_TO_RESUME
    assert ready["epoch"] == human["epoch"] + 1


def test_status_reconciles_expired_active_takeover(tmp_path: Path, monkeypatch) -> None:
    current_time = 50_000
    monkeypatch.setattr(store_module, "now", lambda: current_time)
    store = make_store(tmp_path)
    session = create_session(store)
    token, _grant, _waiting = store.issue_takeover(
        session["session_id"], session["user_id"], session["epoch"], 300
    )
    store.redeem_takeover(token, current_time + 5)

    current_time += 6
    status = store.active_session_for_user(session["user_id"])
    assert status["state"] == READY_TO_RESUME


def test_ready_check_does_not_issue_agent_lease(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = create_session(store)
    token, _grant, _waiting = store.issue_takeover(
        session["session_id"], session["user_id"], session["epoch"], 300
    )
    _grant, _human = store.redeem_takeover(token, 999_999_999_999)
    _grant, ready = store.complete_takeover(_grant["grant_id"])

    checked = store.assert_ready_to_resume(session["session_id"], session["user_id"])
    assert checked["state"] == READY_TO_RESUME
    assert checked["epoch"] == ready["epoch"]
    assert store.session(session["session_id"], session["user_id"])["state"] == READY_TO_RESUME


def test_assert_human_requires_current_human_epoch(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = create_session(store)
    token, _grant, waiting = store.issue_takeover(
        session["session_id"], session["user_id"], session["epoch"], 300
    )
    _grant, human = store.redeem_takeover(token, 999_999_999_999)
    assert store.assert_human(session["session_id"], human["epoch"])["state"] == HUMAN_ACTIVE
    with pytest.raises(Conflict):
        store.assert_human(session["session_id"], waiting["epoch"] + 1)

    store.complete_takeover(_grant["grant_id"])
    with pytest.raises(Conflict):
        store.assert_human(session["session_id"], human["epoch"])


def test_runtime_slots_are_unique_and_bounded(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    slots = [
        store.provision_profile(
            f"user-{index}",
            f"User {index}",
            f"user-{index}@example.com",
        )["runtime_slot"]
        for index in range(5)
    ]
    assert slots == [0, 1, 2, 3, 4]
    with pytest.raises(Conflict):
        store.provision_profile("user-6", "User 6", "user-6@example.com")
