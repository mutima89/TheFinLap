"""Season mode: deterministic turns on the real engine, honest bridges, persistence."""
import json

import pytest

from aurelia.game import events as E
from aurelia.game import season as S
from aurelia.model.assumptions import validate
from aurelia.persistence.db import Database


def _ids(cards):
    return [(c.id, c.title, c.body) for c in cards]


def test_briefing_is_deterministic_and_well_formed():
    a, b = S.new_season(11), S.new_season(11)
    for _ in range(12):
        ca, cb = S.briefing(a), S.briefing(b)
        assert _ids(ca) == _ids(cb)
        kinds = [c.kind for c in ca]
        assert kinds.count("market") == 1 and 1 <= sum(k in ("decision", "issue") for k in kinds) <= 2
        for c in ca:
            if c.kind in ("decision", "issue"):
                assert 2 <= len(c.choices) <= 3 and c.default_choice
        S.close_month(a, S.Levers.default())
        S.close_month(b, S.Levers.default())
    assert a.to_dict() == b.to_dict()


def test_fixed_market_cards_in_february_and_november():
    s = S.new_season(5)
    seen = {}
    while not s.finished:
        seen[s.month] = [c.id for c in S.briefing(s)]
        S.close_month(s, S.Levers.default())
    assert "forum" in seen[2] and "gala" in seen[11]


def test_full_season_default_play_engine_checks_and_exact_bridge():
    s = S.new_season(3)
    while not s.finished:
        rec = S.close_month(s, S.Levers.default())
        assert rec.actual["checks_passed"], rec.label
        total = sum(v for _, v in rec.bridge)
        assert total == pytest.approx(rec.actual["ebitda"] - rec.budget["ebitda"], abs=1e-6)
        assert [lab for lab, _ in rec.bridge][-1] == "Other costs and fees"
        assert rec.verdict in ("beat", "on", "missed") and rec.owner_quote
        assert 0 <= s.confidence <= 100 and 1.0 <= s.guest_score <= 5.0
        assert rec.measured
    assert s.month == 13 and len(s.history) == 12
    review = S.final_review(s)
    assert review["grade"] in "ABCDE" and review["months_played"] == 12
    assert "not a qualification" in review["note"]
    assert "Season closer" in s.earned


def test_month_assumptions_are_valid():
    s = S.new_season(8)
    for _ in range(4):
        cards = S.briefing(s)
        choices = {c.id: c.choices[-1].id for c in cards if c.choices}
        outs = S._resolve(s, cards, choices, None)
        a = S._assumptions(s, S.Levers.default(), outs, noise=True)
        assert validate(a) == []
        S.close_month(s, S.Levers.default(), choices)


def test_round_trip_mid_season_continues_identically():
    a = S.new_season(21)
    for _ in range(5):
        S.close_month(a, S.Levers.default())
    b = S.Season.from_dict(json.loads(json.dumps(a.to_dict())))
    lv = S.Levers.default()
    lv.rate_position["corporate"] = 0.05
    ra, rb = S.close_month(a, lv), S.close_month(b, lv)
    assert ra.to_dict() == rb.to_dict()


def test_projection_range_ordered_and_hides_uncertain_outcome():
    s = S.new_season(4)
    for _ in range(3):
        p = S.project(s, S.Levers.default())
        assert p.low <= p.likely <= p.high
        assert p.budget_ebitda == pytest.approx(S.budget(s.month)["ebitda"])
        assert set(p.kpis) >= {"occupancy", "adr", "revpar", "ebitda", "closing_cash", "guest_score"}
        S.close_month(s, S.Levers.default())


def test_rate_hike_reduces_occupancy():
    s = S.new_season(9)
    hi = S.Levers.default()
    hi.rate_position = {k: 0.20 for k in hi.rate_position}
    assert S.project(s, hi).kpis["occupancy"] < S.project(s, S.Levers.default()).kpis["occupancy"]


def test_levers_are_clamped():
    lv = S.Levers({"corporate": 0.9}, "luxury", 9e9).clamped()
    assert lv.rate_position["corporate"] == 0.20 and lv.staffing == "standard" and lv.marketing == 400_000


def test_deferred_issue_can_surface_later():
    surfaced = False
    for seed in range(40):
        s = S.new_season(seed)
        while s.month <= 9 and not surfaced:
            cards = S.briefing(s)
            if any(c.kind == "consequence" for c in cards):
                cons = next(c for c in cards if c.kind == "consequence")
                rec = S.close_month(s, S.Levers.default())
                assert any(t == "bad" for t, _ in rec.carried) and "Defer" in rec.owner_quote
                surfaced = True
                break
            choices = {c.id: ("defer" if c.id == "chiller" else "patch" if c.id == "lift" else c.default_choice)
                       for c in cards if c.choices}
            S.close_month(s, S.Levers.default(), choices)
        if surfaced:
            assert cons.id in ("chiller_fail", "lift_fail")
            break
    assert surfaced


def test_counter_offer_outcome_is_seeded():
    s1, s2 = S.new_season(77), S.new_season(77)
    o1 = E.CARDS["group"].resolve("counter", E.CARDS["group"].make(S._rng(1, 3, "g"), 3), S._rng(1, 3, "x"))
    o2 = E.CARDS["group"].resolve("counter", E.CARDS["group"].make(S._rng(1, 3, "g"), 3), S._rng(1, 3, "x"))
    assert o1.resolved == o2.resolved and o1.resolved
    assert s1.to_dict() == s2.to_dict()


def test_objectives_titles_and_series():
    s = S.new_season(2)
    objs = S.objectives(s)
    assert len(objs) == 4 and objs[0].value_text == "Not started" and objs[0].status == "on_track"
    for _ in range(3):
        S.close_month(s, S.Levers.default())
    q1 = S.objectives(s, quarter=0)
    assert all(o.status in ("met", "missed") for o in q1)
    assert all(0.0 <= o.progress <= 1.0 for o in q1)
    ser = S.season_series(s)
    assert len(ser["budget"]) == 12 and ser["played"][:3] == [True] * 3 and ser["actual"][3] is None
    assert ser["current"] == 4
    assert S.title_for(0) == ("Finance Trainee", "Revenue Analyst I", 0, 300)
    assert S.title_for(10_000)[0] == "Area CFO" and S.title_for(10_000)[1] is None


def test_save_and_load(tmp_path):
    db = Database(tmp_path / "s.db")
    assert S.load(db) is None
    s = S.new_season(12)
    S.close_month(s, S.Levers.default())
    S.save(db, s)
    t = S.load(db)
    assert t is not None and t.to_dict() == s.to_dict()
    db.close()


def test_cash_floor_ends_season():
    s = S.new_season(1)
    for _ in range(3):
        S.close_month(s, S.Levers.default())
    s.cash = S.CASH_FLOOR + 1000  # April pays the annual tax, so cash falls
    rec = S.close_month(s, S.Levers.default())
    assert rec.actual["net_cash_flow"] < 0
    assert s.finished and s.over_reason == "cash"
    assert "season is over" in rec.owner_quote
    assert S.final_review(s)["grade"] == "E" and S.briefing(s) == []
    with pytest.raises(ValueError):
        S.close_month(s, S.Levers.default())
