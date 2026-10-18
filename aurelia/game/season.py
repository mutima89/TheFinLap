"""Season mode: run The Aurelia Grand for one financial year (FY2027), one month per turn.

How a month is simulated
    Each turn the player sets ``Levers`` (rate position against today's published rate per segment, staffing
    level, marketing spend) and answers the month's briefing cards. The month's assumption tree is the Base case
    plus the levers, the effects of this month's cards, effects carried from earlier months (``persistent``) and any
    deferred risk that has materialised. The full engine (``aurelia.model.engine``) runs on that tree and only
    month *m* of model year 1 is read, so every reported figure comes from the same calculation graph and passes the
    same integrity checks as the rest of the application.

    The budget for month *m* is the Base case with standard levers, no card effects and no demand noise. The
    projection shown before the player commits uses the same deterministic demand (no noise); its low/high range
    scales all demand by ±7%/6% and assumes uncertain negotiations go against/for the player. The actual month adds
    the engine's seeded daily demand noise, so actual results differ from the projection by market variation that
    the player could not know in advance.

Season cash
    Each month's run starts from the Base case opening balance sheet, so balance-sheet effects of earlier turns are
    not carried by the engine. The season therefore tracks cash itself: opening cash plus the sum of each played
    month's net cash flow (engine month *m* of that turn's run). This is a simplification (working-capital timing
    of earlier decisions is not carried) and is documented in the user guide.

All names and numbers are fictional training assumptions, not benchmarks.
"""
from __future__ import annotations

import copy
import json
import random
import time
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any

from ..model.assumptions import SEGMENTS, SEGMENT_LABELS
from ..model.engine import SimulationResult, simulate
from ..model.scenarios import baseline
from . import events as E

SETTING_KEY = "season_v1"
YEAR = 2027
MONTHS = 12
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December"]
CASH_FLOOR = 20_000_000.0
CONTINGENCY = 60_000.0  # monthly repairs & one-off allowance carried in the budget
TRANSIENT = ("corporate", "leisure_direct", "leisure_ota")
STAFFING = {"lean": 0.90, "standard": 1.0, "premium": 1.08}
STAFFED_DEPTS = ("rooms", "fnb", "spa", "events", "pom")
DIRECT_TARGET = 0.20
GUEST_TARGET = 4.5
TITLES = [(0, "Finance Trainee"), (300, "Revenue Analyst I"), (700, "Revenue Analyst II"),
          (1200, "Finance Manager"), (1800, "Director of Finance"), (2500, "Area CFO")]
OWNER = "Layla Rahman"


# ------------------------------------------------------------------------------------------------ data classes
@dataclass
class Levers:
    rate_position: dict[str, float] = field(default_factory=lambda: {s: 0.0 for s in SEGMENTS})
    staffing: str = "standard"
    marketing: float = 0.0

    @staticmethod
    def default() -> "Levers":
        return Levers(marketing=base_marketing())

    def clamped(self) -> "Levers":
        rp = {s: max(-0.20, min(0.20, float(self.rate_position.get(s, 0.0)))) for s in SEGMENTS}
        st = self.staffing if self.staffing in STAFFING else "standard"
        return Levers(rp, st, max(0.0, min(400_000.0, float(self.marketing))))

    def to_dict(self) -> dict:
        return {"rate_position": dict(self.rate_position), "staffing": self.staffing, "marketing": self.marketing}

    @staticmethod
    def from_dict(d: dict) -> "Levers":
        return Levers(dict(d.get("rate_position", {})), d.get("staffing", "standard"),
                      float(d.get("marketing", base_marketing()))).clamped()


@dataclass
class Projection:
    low: float
    likely: float
    high: float
    budget_ebitda: float
    kpis: dict[str, float]


@dataclass
class Objective:
    label: str
    value_text: str
    progress: float
    status: str  # met | on_track | at_risk | missed


@dataclass
class MonthRecord:
    month: int
    label: str
    levers: dict
    choices: dict
    cards: list[dict]
    actual: dict
    budget: dict
    bridge: list
    measured: list
    unexplained: list
    verdict: str
    confidence_delta: int
    guest_delta: float
    xp_gained: int
    achievements: list
    carried: list
    owner_quote: str
    cash: float
    confidence: int
    guest_score: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Season:
    seed: int
    month: int = 1
    history: list = field(default_factory=list)
    confidence: int = 60
    guest_score: float = 4.4
    xp: int = 0
    flags: dict = field(default_factory=dict)
    persistent: list = field(default_factory=list)  # {"from", "to", "effect", "label"}
    risks: list = field(default_factory=list)       # {"month", "p", "id", "title", "body", "effect", ...}
    cash: float = 0.0
    over_reason: str = ""
    earned: list = field(default_factory=list)      # achievement titles already awarded
    objectives_met: int = 0

    @property
    def finished(self) -> bool:
        return self.month > MONTHS or bool(self.over_reason)

    @property
    def label(self) -> str:
        return month_label(min(self.month, MONTHS))

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Season":
        known = {f for f in Season.__dataclass_fields__}
        return Season(**{k: copy.deepcopy(v) for k, v in d.items() if k in known})


def month_label(m: int) -> str:
    return f"{MONTH_NAMES[m - 1]} {YEAR}"


def new_season(seed: int | None = None) -> Season:
    if seed is None:
        seed = int(time.time() * 1000) % 1_000_000
    return Season(seed=int(seed), cash=_plan()["opening_balance"]["cash"])


def load(db) -> Season | None:
    d = db.get_setting(SETTING_KEY)
    return Season.from_dict(d) if d else None


def save(db, season: Season) -> None:
    db.set_setting(SETTING_KEY, season.to_dict())


def _rng(seed: int, month: int, tag: str) -> random.Random:
    return random.Random(f"{seed}:{month}:{tag}")


class _Fixed(random.Random):
    """Stands in for the season RNG in projections: uncertain outcomes resolve at a chosen quantile."""

    def __init__(self, value: float):
        super().__init__(0)
        self._v = value

    def random(self) -> float:  # noqa: D401
        return self._v


# ------------------------------------------------------------------------------------------------ engine runs
@lru_cache(maxsize=1)
def _plan_json() -> str:
    a = baseline()
    a["meta"]["months"] = MONTHS
    a["rooms"]["demand_noise_sd"] = 0.0
    return json.dumps(a)


def _plan() -> dict:
    return json.loads(_plan_json())


def base_marketing() -> float:
    return float(_plan()["undistributed"]["marketing_monthly"])


@lru_cache(maxsize=256)
def _run_json(js: str) -> SimulationResult:
    return simulate(json.loads(js), validate=False)


def run(a: dict) -> SimulationResult:
    return _run_json(json.dumps(a, sort_keys=True))


@lru_cache(maxsize=1)
def _budget_result() -> SimulationResult:
    a = _plan()
    _apply_levers(a, Levers.default(), 1, 4.4)
    a["undistributed"]["pom_fixed_monthly"] += CONTINGENCY
    return run(a)


def _month_kpis(r: SimulationResult, m: int) -> dict:
    sl = slice(m - 1, m)
    k = r.kpis(sl)
    occ = float(r.s("occupied_rooms")[m - 1])
    out = {key: (float(v) if v is not None else 0.0) for key, v in k.items()}
    out["room_nights"] = occ
    out["seg_room_nights"] = {s: float(r.segments[s]["room_nights"][m - 1]) for s in SEGMENTS}
    out["direct_share"] = out["seg_room_nights"]["leisure_direct"] / occ if occ else 0.0
    out["net_cash_flow"] = float(r.s("net_cash_flow")[m - 1])
    out["labour"] = _labour(r, m)
    out["checks_passed"] = r.all_checks_passed
    return out


def _labour(r: SimulationResult, m: int) -> float:
    i = m - 1
    pay = sum(float(r.s(f"payroll_{d}")[i]) for d in ("rooms", "fnb", "spa", "events", "ag", "sm", "pom"))
    return pay + float(r.s("fnb_labour")[i]) - float(r.s("payroll_fnb")[i])


def budget(m: int) -> dict:
    return _month_kpis(_budget_result(), m)


# ------------------------------------------------------------------------------------------------ effects
def apply_effect(a: dict, eff: dict, month: int) -> None:
    """Apply one card effect (see ``events`` module docstring) to an assumption tree for ``month``."""
    for s, mlt in eff.get("seg_demand", {}).items():
        a["segments"][s]["base_demand"] *= float(mlt)
    for s, mlt in eff.get("seg_rate", {}).items():
        a["segments"][s]["published_rate"] *= float(mlt)
    for s, add in eff.get("seg_discount", {}).items():
        a["segments"][s]["discount_pct"] = min(0.9, a["segments"][s]["discount_pct"] + float(add))
    for ev in eff.get("events", []):
        a["rooms"]["special_events"].append({"name": ev["name"], "month": month, "start_day": ev["start_day"],
                                             "end_day": ev["end_day"], "multiplier": ev["multiplier"],
                                             "recurring": False, "year": YEAR})
    for b in eff.get("group_blocks", []):
        a["rooms"]["group_blocks"].append({"name": "Season group", "start_date": f"{YEAR}-{month:02d}-{b['day']:02d}",
                                           "nights": int(b["nights"]), "rooms": float(b["rooms"]),
                                           "rate": float(b["rate"]), "fnb_per_room_night": float(b.get("fnb", 0))})
    if eff.get("one_off"):
        a["undistributed"]["pom_fixed_monthly"] += float(eff["one_off"])
    if eff.get("ooo_rooms"):
        a["rooms"]["out_of_order_rooms"] = min(a["rooms"]["total_rooms"],
                                               a["rooms"]["out_of_order_rooms"] + int(eff["ooo_rooms"]))
    if eff.get("fnb_cogs"):
        a["fnb"]["food_cogs_pct"] = min(0.9, a["fnb"]["food_cogs_pct"] + float(eff["fnb_cogs"]))


def _apply_levers(a: dict, lv: Levers, month: int, guest: float) -> None:
    lv = lv.clamped()
    for s in SEGMENTS:
        a["segments"][s]["published_rate"] *= 1 + lv.rate_position[s]
    f = STAFFING[lv.staffing]
    for d in STAFFED_DEPTS:
        a["payroll"]["headcount"][d] = int(round(a["payroll"]["headcount"][d] * f))
    base_mk = base_marketing()
    a["undistributed"]["marketing_monthly"] = lv.marketing
    # About 40% of a marketing change works this month; the rest is carried to next month at close.
    a["segments"]["leisure_direct"]["base_demand"] *= 1 + _marketing_lift(lv.marketing, base_mk) * 0.4
    # Reputation: the guest score moves leisure demand more than corporate demand.
    rep = guest - 4.4
    for s, k in (("leisure_direct", 0.12), ("leisure_ota", 0.10), ("corporate", 0.05)):
        a["segments"][s]["base_demand"] *= max(0.5, 1 + k * rep)


def _marketing_lift(mk: float, base_mk: float) -> float:
    return max(-0.10, min(0.15, 0.25 * (mk - base_mk) / base_mk)) if base_mk else 0.0


def briefing(season: Season) -> list[E.CardInstance]:
    """This month's cards: a materialised risk (if any), one market card and one or two decisions/issues."""
    if season.finished:
        return []
    m = season.month
    rng = _rng(season.seed, m, "briefing")
    used = {c["id"] for rec in season.history for c in rec["cards"]}
    out: list[E.CardInstance] = []
    for risk in season.risks:
        if risk["month"] == m and _rng(season.seed, m, risk["id"]).random() < risk["p"]:
            out.append(E.consequence_card(risk))
    fixed = {2: "forum", 11: "gala"}
    if m in fixed:
        mk = E.CARDS[fixed[m]]
    else:
        pool = [c for c in E.MARKET if m in c.months and c.id not in fixed.values() and c.id not in used] \
            or [c for c in E.MARKET if m in c.months and c.id not in fixed.values()]
        mk = rng.choices(pool, weights=[c.weight for c in pool])[0]
    out.append(mk.instance(_rng(season.seed, m, mk.id), m))
    pool: list[E.CardDef] = []
    for lookback in (3, 1, 0):  # avoid repeating recent cards, but never leave a month without a decision
        recent = {c["id"] for rec in season.history[max(0, len(season.history) - lookback):]
                  for c in rec["cards"]} \
            if lookback else set()
        pool = [c for c in E.DECISIONS + E.ISSUES if m in c.months and c.requires(season.flags)
                and c.id not in recent and not (c.once and c.id in used)]
        if pool:
            break
    n = 2 if rng.random() < 0.5 else 1
    for _ in range(min(n, len(pool))):
        c = rng.choices(pool, weights=[x.weight for x in pool])[0]
        pool.remove(c)
        out.append(c.instance(_rng(season.seed, m, c.id), m))
    return out


def _resolve(season: Season, cards: list[E.CardInstance], choices: dict, quantile: float | None) -> dict:
    """Outcome per card. ``quantile`` None = the real (seeded) outcome; else a fixed draw for projections."""
    out = {}
    for c in cards:
        if c.kind == "consequence":
            risk = c.params["risk"]
            out[c.id] = E.Outcome(effect=risk["effect"], guest=risk.get("guest", 0.0),
                                  confidence=risk.get("confidence", 0), carried=[("bad", risk["title"] + ".")])
            continue
        d = E.CARDS[c.id]
        ch = choices.get(c.id) or c.default_choice or ""
        if c.choices and ch not in {x.id for x in c.choices}:
            ch = c.default_choice
        r = _rng(season.seed, season.month, c.id + ":outcome") if quantile is None else _Fixed(quantile)
        out[c.id] = d.resolve(ch, c.params, r)
    return out


def _assumptions(season: Season, levers: Levers, outcomes: dict, noise: bool, demand_scale: float = 1.0,
                 skip_one_off: bool = False) -> dict:
    m = season.month
    a = _plan()
    _apply_levers(a, levers, m, season.guest_score)
    effects = [p["effect"] for p in season.persistent if p["from"] <= m <= p["to"]]
    if season.flags.get("marketing_carry"):
        effects.append({"seg_demand": {"leisure_direct": 1 + season.flags["marketing_carry"]}})
    effects += [o.effect for o in outcomes.values()]
    for eff in effects:
        if skip_one_off and eff.get("one_off"):
            eff = {k: v for k, v in eff.items() if k != "one_off"}
        apply_effect(a, eff, m)
    if skip_one_off:  # counterfactual: the budget's contingency instead of the month's actual one-offs
        a["undistributed"]["pom_fixed_monthly"] += CONTINGENCY
    if demand_scale != 1.0:
        for s in SEGMENTS:
            a["segments"][s]["base_demand"] *= demand_scale
    if noise:
        a["rooms"]["demand_noise_sd"] = 0.05
        a["rooms"]["random_seed"] = (season.seed * 97 + m) % 2_000_000_000
    return a


def _guest_next(season: Season, lv: Levers, occupancy: float, outcomes: dict) -> float:
    lv = lv.clamped()
    target = 4.4
    if lv.staffing == "lean":
        target -= 0.30 if occupancy > 0.85 else 0.15
    elif lv.staffing == "premium":
        target += 0.12
    avg_rate = sum(lv.rate_position[s] for s in TRANSIENT) / len(TRANSIENT)
    target -= 0.4 * max(0.0, avg_rate - 0.05)
    target -= 0.05 * int(season.flags.get("deferred", 0) > 0)
    g = season.guest_score + 0.5 * (target - season.guest_score) + sum(o.guest for o in outcomes.values())
    return round(max(1.0, min(5.0, g)), 2)


# ------------------------------------------------------------------------------------------------ projection
def project(season: Season, levers: Levers, choices: dict | None = None) -> Projection:
    """Expected month before committing, with a low/high range. Never reveals uncertain outcomes."""
    choices = choices or {}
    cards = briefing(season)
    m = min(season.month, MONTHS)
    likely_o = _resolve(season, cards, choices, 0.5)
    r = run(_assumptions(season, levers, likely_o, noise=False))
    lo = run(_assumptions(season, levers, _resolve(season, cards, choices, 0.999), False, 0.93))
    hi = run(_assumptions(season, levers, _resolve(season, cards, choices, 0.0), False, 1.06))
    k = _month_kpis(r, m)
    vals = sorted([float(lo.s("ebitda")[m - 1]), k["ebitda"], float(hi.s("ebitda")[m - 1])])
    kp = {"occupancy": k["occupancy"], "adr": k["adr"], "revpar": k["revpar"], "ebitda": k["ebitda"],
          "closing_cash": season.cash + k["net_cash_flow"],
          "guest_score": _guest_next(season, levers, k["occupancy"], likely_o)}
    return Projection(vals[0], k["ebitda"], vals[2], budget(m)["ebitda"], kp)


# ------------------------------------------------------------------------------------------------ month close
def _bridge(a: dict, b: dict, one_off: float, marketing: float) -> list:
    rate = (a["adr"] - b["adr"]) * a["room_nights"]
    vol = (a["room_nights"] - b["room_nights"]) * b["adr"]
    other_rev = (a["total_revenue"] - a["rooms_revenue"]) - (b["total_revenue"] - b["rooms_revenue"])
    payroll = -(a["labour"] - b["labour"])
    lines = [("Room rate", rate), ("Room volume", vol), ("Other departments' revenue", other_rev),
             ("Payroll", payroll), ("Marketing", marketing), ("One-offs vs contingency", one_off)]
    known = sum(v for _, v in lines)
    lines.append(("Other costs and fees", (a["ebitda"] - b["ebitda"]) - known))
    return [(lab, float(v)) for lab, v in lines]


def _sar(v: float) -> str:
    sign = "−" if v < 0 else "+"
    v = abs(v)
    return f"{sign}SAR {v / 1e6:,.2f}m" if v >= 1e6 else f"{sign}SAR {v / 1e3:,.0f}k"


def _statements(season: Season, lv: Levers, a: dict, b: dict, outcomes: dict, cards: list) -> tuple[list, list]:
    measured, unexplained = [], []
    measured.append(f"ADR was SAR {a['adr']:,.0f} against a budget of SAR {b['adr']:,.0f}; on "
                    f"{a['room_nights']:,.0f} room nights that is {_sar((a['adr'] - b['adr']) * a['room_nights'])}.")
    measured.append(f"Room nights were {a['room_nights']:,.0f} against {b['room_nights']:,.0f} budgeted, worth "
                    f"{_sar((a['room_nights'] - b['room_nights']) * b['adr'])} at budget ADR.")
    if lv.staffing != "standard":
        measured.append(f"{lv.staffing.capitalize()} staffing changed labour cost by "
                        f"{_sar(-(a['labour'] - b['labour']))} against budget.")
    touched: set[str] = set()
    broad = False
    for s in SEGMENTS:
        if abs(lv.rate_position[s]) > 1e-9:
            touched.add(s)
    for o in outcomes.values():
        for key in ("seg_demand", "seg_rate", "seg_discount"):
            touched |= set(o.effect.get(key, {}))
        broad |= bool(o.effect.get("events") or o.effect.get("group_blocks") or o.effect.get("ooo_rooms"))
    for p in season.persistent:
        if p["from"] <= season.month <= p["to"]:
            for key in ("seg_demand", "seg_rate", "seg_discount"):
                touched |= set(p["effect"].get(key, {}))
    if abs(lv.marketing - base_marketing()) > 1 or season.flags.get("marketing_carry"):
        touched.add("leisure_direct")
    for s in SEGMENTS:
        an, bn = a["seg_room_nights"][s], b["seg_room_nights"][s]
        if bn <= 0:
            continue
        ch = an / bn - 1
        if s in touched and abs(ch) > 0.02:
            measured.append(f"{SEGMENT_LABELS[s]} room nights moved {ch:+.0%}, in the direction the model's "
                            f"price response and your decisions for that segment predict.")
        elif s not in touched and abs(ch) > (0.08 if broad else 0.04):
            unexplained.append(f"{SEGMENT_LABELS[s]} room nights were {ch:+.0%} against budget with no decision "
                               f"of yours aimed at that segment. The data does not say why: it may be displacement "
                               f"by other business or ordinary market variation. Check with Sales before naming a "
                               f"cause.")
    for c in cards:
        o = outcomes[c.id]
        if o.resolved:
            measured.append(f"{c.title}: {o.resolved}")
    return measured, unexplained


def _quote(rec: dict, season: Season, outcomes: dict, cards: list, lv: Levers) -> str:
    if season.over_reason:
        return ("Cash fell through the floor the lenders set. I have to take this to the owners; the season is "
                "over.")
    if any(c.kind == "consequence" for c in cards):
        return "Deferring that repair cost us more than fixing it would have. Fix problems when they are small."
    bridge = dict(rec["bridge"])
    avg_rate = sum(lv.rate_position[s] for s in TRANSIENT) / len(TRANSIENT)
    q = ""
    if rec["verdict"] == "beat":
        q = ("That is the discipline I want: you priced the demand properly." if bridge["Room rate"] > 0
             and avg_rate > 0.02 else "A good month. Keep costs where they are and keep the rate honest.")
    elif rec["verdict"] == "on":
        q = "On budget. I would like to see you find some upside next month."
    elif bridge["Room volume"] < 0 and avg_rate > 0.05:
        q = "You priced guests away. A full house at the right price beats an empty one at a high price."
    elif any(c.id == "ota_promo" and outcomes[c.id].effect for c in cards):
        q = "Discounting through the OTAs did not pay for itself. Show me the net rate, not the volume."
    else:
        q = "We missed the budget. Tell me what you will change, and what you still need to find out."
    if rec["guest_delta"] <= -0.1:
        q += " And watch the guest score: the owners read the reviews too."
    return q


def close_month(season: Season, levers: Levers, choices: dict | None = None) -> MonthRecord:
    """Simulate the month with the real outcomes, score it and advance the season."""
    if season.finished:
        raise ValueError("The season is finished.")
    choices = dict(choices or {})
    lv = levers.clamped()
    m = season.month
    cards = briefing(season)
    for c in cards:
        if c.choices and choices.get(c.id) not in {x.id for x in c.choices}:
            choices[c.id] = c.default_choice
    outcomes = _resolve(season, cards, choices, None)
    r = run(_assumptions(season, lv, outcomes, noise=True))
    r0 = run(_assumptions(season, lv, outcomes, noise=True, skip_one_off=True))
    a, b = _month_kpis(r, m), budget(m)
    one_off = float(r.s("ebitda")[m - 1] - r0.s("ebitda")[m - 1])
    marketing = -(lv.marketing - base_marketing())
    bridge = _bridge(a, b, one_off, marketing)
    var = (a["ebitda"] - b["ebitda"]) / abs(b["ebitda"]) if b["ebitda"] else 0.0
    verdict = "beat" if var >= 0.01 else ("on" if var > -0.01 else "missed")
    old_guest = season.guest_score
    guest = _guest_next(season, lv, a["occupancy"], outcomes)
    delta = (6 if var >= 0.03 else 4 if verdict == "beat" else 1 if verdict == "on"
             else -2 if var > -0.03 else -4 if var > -0.06 else -7)
    if guest - old_guest <= -0.1:
        delta -= 2
    delta += sum(o.confidence for o in outcomes.values())

    # advance state
    season.cash += a["net_cash_flow"]
    season.guest_score = guest
    season.confidence = max(0, min(100, season.confidence + delta))
    for o in outcomes.values():
        for k, v in o.flags.items():
            season.flags[k] = season.flags.get(k, 0) + v if k in ("group_relation", "ota_promos") else v
        for p in o.persistent:
            season.persistent.append({"from": m + 1, "to": m + p["months"], "effect": p["effect"],
                                      "label": p["label"]})
        for rk in o.risks:
            season.risks.append({**{k: v for k, v in rk.items() if k != "in"}, "month": m + rk["in"]})
    if any(c.kind == "consequence" for c in cards):
        season.flags["deferred"] = max(0, season.flags.get("deferred", 0) - 1)
    lift = _marketing_lift(lv.marketing, base_marketing()) * 0.6
    season.flags["marketing_carry"] = round(lift, 4) if abs(lift) > 1e-6 else 0
    if season.cash < CASH_FLOOR:
        season.over_reason = "cash"

    # achievements and xp
    ach = []
    avg_rate = sum(lv.rate_position[s] for s in TRANSIENT) / len(TRANSIENT)

    def award(title, desc, ok):
        if ok and title not in season.earned:
            season.earned.append(title)
            ach.append((title, desc))

    award("Rate discipline", "Raised rate without giving up occupancy.",
          avg_rate >= 0.04 and a["occupancy"] >= b["occupancy"] - 0.02 and bridge[0][1] > 0)
    award("Cost control", "Beat budget with labour and costs below plan.",
          verdict != "missed" and bridge[3][1] + bridge[6][1] > 0)
    award("Guest champion", "Guest score of 4.6 or higher.", guest >= 4.6)
    award("Group strategist", "Won a group at a better rate by negotiating.",
          any(c.id == "group" and choices.get("group") == "counter" and outcomes[c.id].effect for c in cards))
    recent = [h["verdict"] for h in season.history[-2:]] + [verdict]
    award("Steady hand", "Three months in a row without missing budget.",
          len(recent) == 3 and "missed" not in recent)
    award("Season closer", "Played all twelve months.", m == MONTHS and not season.over_reason)
    xp = 50 + {"beat": 100, "on": 40, "missed": 0}[verdict] + 30 * len(ach)

    carried = [tuple(t) for o in outcomes.values() for t in o.carried]
    if abs(lift) > 1e-6:
        carried.append(("info", f"Marketing of SAR {lv.marketing / 1000:,.0f}k "
                                f"{'lifts' if lift > 0 else 'lowers'} website demand next month."))
    measured, unexplained = _statements(season, lv, a, b, outcomes, cards)
    spent = sum(float(o.effect.get("one_off", 0)) for o in outcomes.values())
    measured.append(f"Repairs and one-offs cost SAR {spent / 1000:,.0f}k against a SAR {CONTINGENCY / 1000:,.0f}k "
                    f"budget contingency: {_sar(one_off)} of EBITDA.")

    rec = MonthRecord(m, month_label(m), lv.to_dict(), choices, [c.to_dict() for c in cards], a, b, bridge,
                      measured, unexplained, verdict, delta, round(guest - old_guest, 2), xp, ach, carried, "",
                      season.cash, season.confidence, guest)
    d = rec.to_dict()
    rec.owner_quote = _quote(d, season, outcomes, cards, lv)
    season.history.append(json.loads(json.dumps(rec.to_dict())))  # JSON-normal form (lists, not tuples)
    season.month += 1
    if m % 3 == 0 or season.finished:
        met = sum(o.status == "met" for o in objectives(season, quarter=(m - 1) // 3))
        season.objectives_met += met
        bonus = 40 * met
        season.history[-1]["xp_gained"] += bonus
        rec.xp_gained += bonus
        xp += bonus
    season.xp += xp
    return rec


# ------------------------------------------------------------------------------------------------ progress views
def objectives(season: Season, quarter: int | None = None) -> list[Objective]:
    q = (min(season.month, MONTHS) - 1) // 3 if quarter is None else quarter
    months = range(3 * q + 1, 3 * q + 4)
    recs = [h for h in season.history if h["month"] in months]
    done = len(recs) == 3 or (season.finished and recs)
    out: list[Objective] = []

    def status(ok: bool) -> str:
        return ("met" if ok else "missed") if done else ("on_track" if ok else "at_risk")

    act = sum(h["actual"]["ebitda"] for h in recs)
    bud = sum(h["budget"]["ebitda"] for h in recs)
    if recs:
        out.append(Objective(f"EBITDA at or above budget for Q{q + 1}", _sar(act - bud),
                             max(0.0, min(1.0, act / bud)) if bud > 0 else 0.0, status(act >= bud)))
    else:
        out.append(Objective(f"EBITDA at or above budget for Q{q + 1}", "Not started", 0.0, "on_track"))
    rn = sum(h["actual"]["room_nights"] for h in recs)
    direct = sum(h["actual"]["seg_room_nights"]["leisure_direct"] for h in recs)
    share = direct / rn if rn else 0.0
    out.append(Objective(f"Website bookings at least {DIRECT_TARGET:.0%} of room nights",
                         f"{share:.0%}" if recs else "Not started", min(1.0, share / DIRECT_TARGET) if recs else 0.0,
                         status(share >= DIRECT_TARGET) if recs else "on_track"))
    low = min([h["cash"] for h in season.history] or [season.cash])
    out.append(Objective(f"Cash never below SAR {CASH_FLOOR / 1e6:.0f}m", f"Low SAR {low / 1e6:,.1f}m",
                         1.0 if low >= CASH_FLOOR else 0.0, "missed" if low < CASH_FLOOR else status(True)))
    out.append(Objective(f"Guest score at least {GUEST_TARGET}", f"{season.guest_score:.1f}",
                         min(1.0, season.guest_score / GUEST_TARGET), status(season.guest_score >= GUEST_TARGET)))
    return out


def title_for(xp: int) -> tuple[str, str | None, int, int | None]:
    idx = max(i for i, (lo, _) in enumerate(TITLES) if xp >= lo)
    nxt = TITLES[idx + 1] if idx + 1 < len(TITLES) else None
    return TITLES[idx][1], (nxt[1] if nxt else None), TITLES[idx][0], (nxt[0] if nxt else None)


def season_series(season: Season) -> dict[str, Any]:
    played = {h["month"]: h for h in season.history}
    return {
        "labels": [n[:3] for n in MONTH_NAMES],
        "budget": [budget(m)["ebitda"] for m in range(1, MONTHS + 1)],
        "actual": [played[m]["actual"]["ebitda"] if m in played else None for m in range(1, MONTHS + 1)],
        "played": [m in played for m in range(1, MONTHS + 1)],
        "verdict": [played[m]["verdict"] if m in played else None for m in range(1, MONTHS + 1)],
        "current": season.month if not season.finished else None,
    }


def final_review(season: Season) -> dict:
    h = season.history
    act = sum(x["actual"]["ebitda"] for x in h)
    bud = sum(x["budget"]["ebitda"] for x in h)
    var = (act - bud) / abs(bud) if bud else 0.0
    c = season.confidence
    if season.over_reason:
        grade = "E"
    elif c >= 80 and var >= 0.03:
        grade = "A"
    elif c >= 65 and var >= 0:
        grade = "B"
    elif c >= 50 or var >= -0.03:
        grade = "C"
    elif c >= 35:
        grade = "D"
    else:
        grade = "E"
    best = max(h, key=lambda x: x["actual"]["ebitda"] - x["budget"]["ebitda"]) if h else None
    worst = min(h, key=lambda x: x["actual"]["ebitda"] - x["budget"]["ebitda"]) if h else None
    title = title_for(season.xp)[0]
    lines = [f"EBITDA SAR {act / 1e6:,.2f}m against a budget of SAR {bud / 1e6:,.2f}m ({var:+.1%}).",
             f"Owner confidence ended at {c}; guest score {season.guest_score:.1f}.",
             f"{season.objectives_met} quarterly objectives met; {len(season.earned)} skills earned."]
    if season.over_reason:
        lines.insert(0, "The season ended early because cash fell below the lenders' floor.")
    return {"grade": grade, "ebitda": act, "budget": bud, "variance_pct": var, "months_played": len(h),
            "best_month": best["label"] if best else None, "worst_month": worst["label"] if worst else None,
            "objectives_met": season.objectives_met, "title": title, "confidence": c,
            "guest_score": season.guest_score, "summary": lines,
            "note": "Practice feedback in a fictional simulation, not a qualification."}
