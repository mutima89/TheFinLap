"""The Aurelia Grand business simulation engine.

One call to :func:`simulate` turns an assumption tree into a fully linked set of
results: daily room demand and inventory, monthly departmental P&L, USALI-style
operating statement, three-statement model (income statement, balance sheet,
cash flow) and integrity checks.

Design principles
-----------------
* Deterministic: the only randomness is seeded daily demand noise generated
  from ``rooms.random_seed`` with a fixed shape, so the same assumptions always
  reproduce the same results, and changing an unrelated input never reshuffles
  the noise.
* Explainable: every output line item has a plain-language formula in the
  calculation graph (see :mod:`aurelia.model.graph`).
* Constrained: occupancy can never exceed available rooms (except where the
  user deliberately overbooks, in which case expected walked guests are
  removed and costed), and inventory can never be negative.
* No circularity: interest is charged on opening balances, so the revolver
  and cash sweep resolve in a single forward pass.

See ``docs/MODEL_REFERENCE.md`` for the complete specification.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import pandas as pd

from .assumptions import SEGMENTS, DEPARTMENTS, validate_or_raise, to_json
from .graph import CalcGraph, LineItem

G = CalcGraph()

# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


@dataclass
class Context:
    a: dict
    months: pd.PeriodIndex
    dim: np.ndarray  # days in month
    year_idx: np.ndarray  # 0,0,..,1,1..
    moy: np.ndarray  # month of year 1..12
    days: pd.DatetimeIndex
    day_month: np.ndarray  # month index of each day
    warnings: list[str] = field(default_factory=list)

    @property
    def M(self) -> int:
        return len(self.months)

    def growth(self, rate: float) -> np.ndarray:
        return (1.0 + rate) ** self.year_idx

    def month_index(self, label: str) -> int | None:
        """Index of a 'YYYY-MM' label within the horizon, or None."""
        try:
            p = pd.Period(label, "M")
        except Exception:  # noqa: BLE001
            return None
        idx = (p - self.months[0]).n
        return idx if 0 <= idx < self.M else None


def build_context(a: dict) -> Context:
    meta = a["meta"]
    start = pd.Period(meta["start_month"], "M")
    months = pd.period_range(start, periods=int(meta["months"]), freq="M")
    days = pd.date_range(months[0].start_time, months[-1].end_time.normalize(), freq="D")
    day_month = np.asarray((days.year - start.year) * 12 + (days.month - start.month))
    dim = np.array([p.days_in_month for p in months], dtype=float)
    year_idx = np.arange(len(months)) // 12
    moy = np.array([p.month for p in months])
    return Context(a, months, dim, year_idx, moy, days, day_month)


def _monthly(ctx: Context, daily: np.ndarray) -> np.ndarray:
    return np.bincount(ctx.day_month, weights=daily, minlength=ctx.M)


def _li(key, label, formula, unit="currency", inputs=None, nature="context"):
    return LineItem(key, label, formula, unit, inputs=inputs or [], nature=nature)


# Normal distribution helpers (no SciPy dependency)
_erf = np.frompyfunc(math.erf, 1, 1)


def _norm_cdf(z: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + _erf(z / math.sqrt(2.0)).astype(float))


def _norm_pdf(z: np.ndarray) -> np.ndarray:
    return np.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)


@lru_cache(maxsize=32)
def _noise_matrix(seed: int, n_days: int, n_seg: int) -> np.ndarray:
    """Standard-normal draws with a FIXED shape so results are reproducible."""
    rng = np.random.default_rng(int(seed))
    return rng.standard_normal((n_days, n_seg))


# ---------------------------------------------------------------------------
# Rooms: daily demand, inventory and revenue
# ---------------------------------------------------------------------------

ROOM_OUTPUTS = [
    _li("available_rooms", "Available room nights", "(Total rooms − out-of-order rooms − renovation rooms) × days",
        "rooms", ["rooms.total_rooms", "rooms.out_of_order_rooms", "capex.projects"]),
    _li("room_demand", "Unconstrained room demand (requests)",
        "Σ segments: base demand × seasonality × day-of-week × events × growth × (rate ÷ reference)^elasticity "
        "× campaign uplift × seeded noise", "rooms",
        ["segments.*.base_demand", "segments.*.elasticity", "rooms.seasonality", "rooms.special_events"]),
    _li("bookings_accepted", "Bookings accepted",
        "Requests accepted in booking-window order until (available × (1 + overbooking)) or the segment cap is "
        "reached, plus resold cancelled rooms", "rooms", ["rooms.overbooking_pct", "segments.*.cap"]),
    _li("cancellations", "Cancelled bookings", "Accepted bookings × cancellation rate", "rooms",
        ["segments.*.cancellation_pct"]),
    _li("no_shows", "No-shows", "(Accepted − cancelled) × no-show rate", "rooms", ["segments.*.no_show_pct"]),
    _li("walked_guests", "Walked guests (overbooking)",
        "E[max(0, arrivals − available)] using a normal approximation of arrival uncertainty", "rooms",
        ["rooms.overbooking_pct"]),
    _li("occupied_rooms", "Occupied room nights", "Arrivals − walked guests (never above available rooms)",
        "rooms"),
    _li("rooms_revenue", "Room revenue (gross, excl. VAT)", "Σ segments: occupied room nights × realised rate",
        "currency", ["segments.*.published_rate", "segments.*.discount_pct", "rooms.rate_growth_pct"], "revenue"),
    _li("commissions", "Commissions & distribution fees", "Σ segments: room revenue × commission rate",
        "currency", ["segments.*.commission_pct", "campaigns"], "expense"),
    _li("no_show_fees", "No-show fee revenue", "No-shows × realised rate × share charged", "currency",
        ["rooms.no_show_charge_pct"], "revenue"),
    _li("walk_costs", "Walk costs", "Walked guests × cost per walk", "currency", ["rooms.walk_cost"], "expense"),
    _li("unmet_demand", "Turned-away demand (denials)", "Requests − bookings accepted", "rooms"),
]


@G.node("rooms", deps=[], outputs=ROOM_OUTPUTS, description="Daily rooms demand, constrained inventory and revenue.")
def _rooms(ctx: Context, v: dict) -> dict:
    a = ctx.a
    r = a["rooms"]
    nd = len(ctx.days)
    dm = ctx.day_month
    moy_d = ctx.days.month.to_numpy()
    dow_d = ctx.days.weekday.to_numpy()
    year_d = ctx.year_idx[dm]
    season = np.asarray(r["seasonality"], dtype=float)[moy_d - 1]

    # Available rooms per day, including renovation out-of-order blocks.
    avail = np.full(nd, float(r["total_rooms"] - r["out_of_order_rooms"]))
    rate_uplift = np.ones(nd)
    demand_uplift = np.ones(nd)
    for p in a["capex"]["projects"]:
        mi = ctx.month_index(p.get("month", ""))
        if mi is None:
            continue
        ooo = float(p.get("ooo_rooms", 0) or 0)
        dur = int(p.get("ooo_months", 0) or 0)
        if ooo and dur:
            mask = (dm >= mi) & (dm < mi + dur)
            avail[mask] -= ooo
        done = mi + dur
        if p.get("rate_uplift_pct"):
            rate_uplift[dm >= done] *= 1 + float(p["rate_uplift_pct"])
        if p.get("demand_uplift_pct"):
            demand_uplift[dm >= done] *= 1 + float(p["demand_uplift_pct"])
    if (avail < 0).any():
        ctx.warnings.append("Out-of-order and renovation rooms exceed total rooms on some days; "
                            "available inventory was floored at zero.")
    avail = np.maximum(avail, 0.0)

    # Special events (demand compression)
    event_mult = np.ones(nd)
    years = sorted(set(ctx.days.year))
    for ev in r.get("special_events", []):
        for y in (years if ev.get("recurring", True) else [ev.get("year", years[0])]):
            mask = (ctx.days.year == y) & (ctx.days.month == int(ev["month"])) & (
                ctx.days.day >= int(ev["start_day"])) & (ctx.days.day <= int(ev["end_day"]))
            event_mult[np.asarray(mask)] *= float(ev["multiplier"])

    # Campaigns: monthly uplift and extra commission per segment
    camp_uplift = {s: np.ones(ctx.M) for s in SEGMENTS}
    camp_comm = {s: np.zeros(ctx.M) for s in SEGMENTS}
    for c in a["campaigns"]:
        mi = ctx.month_index(c.get("start_month", ""))
        if mi is None or c.get("segment") not in SEGMENTS:
            continue
        end = min(ctx.M, mi + int(c.get("months", 1)))
        camp_uplift[c["segment"]][mi:end] *= 1 + float(c.get("demand_uplift_pct", 0))
        camp_comm[c["segment"]][mi:end] += float(c.get("extra_commission_pct", 0))

    noise = _noise_matrix(int(r["random_seed"]), nd, len(SEGMENTS))
    sd = float(r["demand_noise_sd"])
    rate_growth = (1 + r["rate_growth_pct"]) ** year_d
    demand_growth = (1 + r["demand_growth_pct"]) ** year_d

    seg_rate, seg_demand = {}, {}
    for j, s in enumerate(SEGMENTS):
        sg = a["segments"][s]
        rate = sg["published_rate"] * (1 - sg["discount_pct"]) * season ** r["seasonal_rate_flex"] \
            * rate_growth * rate_uplift
        ref = sg["reference_rate"] * season ** r.get("reference_rate_flex", 0.5) * rate_growth * rate_uplift
        price_ratio = np.where(ref > 0, rate / ref, 1.0)
        dow = np.asarray(sg["dow"], dtype=float)[dow_d]
        mult_noise = np.exp(sd * noise[:, j] - 0.5 * sd * sd) if sd > 0 else 1.0
        d = (sg["base_demand"] * season * dow * event_mult * demand_growth * demand_uplift
             * np.power(np.maximum(price_ratio, 1e-9), sg["elasticity"])
             * camp_uplift[s][dm] * mult_noise)
        seg_rate[s] = rate
        seg_demand[s] = np.maximum(d, 0.0)

    # Contracted group blocks (e.g. a group request being evaluated for displacement) are
    # committed first: they are assumed to be signed before transient demand books.
    block = np.zeros(nd)
    block_rate = np.zeros(nd)
    block_fnb = np.zeros(nd)
    for b in r.get("group_blocks", []):
        try:
            start_d = pd.Timestamp(b["start_date"])
        except Exception:  # noqa: BLE001
            continue
        mask = np.asarray((ctx.days >= start_d) & (ctx.days < start_d + pd.Timedelta(days=int(b["nights"]))))
        block[mask] += float(b["rooms"])
        block_rate[mask] = float(b["rate"])
        block_fnb[mask] += float(b["rooms"]) * float(b.get("fnb_per_room_night", 0.0))
    block_taken = np.minimum(block, avail)
    if (block > avail + 1e-9).any():
        ctx.warnings.append("A contracted group block exceeds available rooms on some nights; it was capped.")
    block_fnb = np.where(block > 0, block_fnb * np.divide(block_taken, block, out=np.zeros(nd), where=block > 0), 0)

    # Acceptance in booking-window order (longest lead first)
    order = sorted(SEGMENTS, key=lambda s: -a["segments"][s]["lead_days"])
    limit = avail * (1 + r["overbooking_pct"])
    remaining = np.maximum(limit - block_taken, 0)
    acc = {}
    for s in order:
        cap = a["segments"][s].get("cap")
        if cap is not None and s == "group":
            cap_arr = np.maximum(float(cap) - block_taken, 0)
        else:
            cap_arr = None if cap is None else np.full(nd, float(cap))
        want = seg_demand[s] if cap_arr is None else np.minimum(seg_demand[s], cap_arr)
        take = np.minimum(want, remaining)
        acc[s] = take
        remaining -= take

    cxl = {s: acc[s] * a["segments"][s]["cancellation_pct"] for s in SEGMENTS}
    ns = {s: (acc[s] - cxl[s]) * a["segments"][s]["no_show_pct"] for s in SEGMENTS}
    shows = {s: acc[s] - cxl[s] - ns[s] for s in SEGMENTS}

    # Resale of cancelled rooms to unmet demand, shortest lead first (late bookers).
    freed = sum(cxl.values()) * r["cancellation_resale_pct"]
    resold = {}
    for s in reversed(order):
        cap = a["segments"][s].get("cap")
        unmet = seg_demand[s] - acc[s]
        if cap is not None:
            cap_s = float(cap) - (block_taken if s == "group" else 0.0)
            unmet = np.minimum(unmet, np.maximum(cap_s - acc[s], 0))
        take = np.minimum(np.maximum(unmet, 0), freed)
        resold[s] = take
        freed = freed - take
        shows[s] = shows[s] + take * (1 - a["segments"][s]["no_show_pct"])
        ns[s] = ns[s] + take * a["segments"][s]["no_show_pct"]
        acc[s] = acc[s] + take

    mu = sum(shows.values())
    # Expected walks only arise when bookings on hand exceed available rooms.
    avail_t = avail - block_taken  # capacity left for transient & non-contracted business
    over = (mu > avail_t) | (sum(acc.values()) - sum(cxl.values()) > avail_t + 1e-9)
    # Arrival uncertainty: each booking on hand shows with probability p_s (binomial variance).
    var = 0.0
    for s in SEGMENTS:
        p_show = np.where(acc[s] > 0, shows[s] / np.where(acc[s] > 0, acc[s], 1), 0.0)
        var = var + acc[s] * p_show * (1 - p_show)
    sigma = np.sqrt(np.maximum(var, 1e-9))
    z = (mu - avail_t) / sigma
    exp_walk = (mu - avail_t) * _norm_cdf(z) + sigma * _norm_pdf(z)
    walks = np.where(over, np.clip(exp_walk, 0, mu), 0.0)
    keep = np.where(mu > 0, 1 - walks / np.where(mu > 0, mu, 1), 1.0)
    occ_seg = {s: shows[s] * keep for s in SEGMENTS}
    # Add the contracted block to the group segment (it is not subject to cancellation in this model).
    shows_total_block = block_taken
    occ_seg["group"] = occ_seg["group"] + shows_total_block
    acc["group"] = acc["group"] + block_taken
    occupied = np.minimum(sum(occ_seg.values()), avail)

    camp_comm_d = {s: camp_comm[s][dm] for s in SEGMENTS}
    rev_seg = {s: occ_seg[s] * seg_rate[s] for s in SEGMENTS}
    rev_seg["group"] = rev_seg["group"] - block_taken * seg_rate["group"] + block_taken * block_rate
    comm_seg = {s: rev_seg[s] * (a["segments"][s]["commission_pct"] + camp_comm_d[s]) for s in SEGMENTS}
    nsfee = sum(ns[s] * seg_rate[s] for s in SEGMENTS) * r["no_show_charge_pct"]

    daily = pd.DataFrame({"date": ctx.days, "month_idx": dm, "available": avail, "occupied": occupied,
                          "walks": walks, "event_multiplier": event_mult})
    for s in SEGMENTS:
        daily[f"{s}_demand"] = seg_demand[s]
        daily[f"{s}_accepted"] = acc[s]
        daily[f"{s}_cancelled"] = cxl[s]
        daily[f"{s}_no_show"] = ns[s]
        daily[f"{s}_rooms"] = occ_seg[s]
        daily[f"{s}_rate"] = np.divide(rev_seg[s], occ_seg[s], out=seg_rate[s].copy(), where=occ_seg[s] > 0)
        daily[f"{s}_revenue"] = rev_seg[s]
        daily[f"{s}_commission"] = comm_seg[s]
    ctx.daily = daily  # type: ignore[attr-defined]

    seg_monthly = {}
    for s in SEGMENTS:
        seg_monthly[s] = {
            "demand": _monthly(ctx, seg_demand[s]), "accepted": _monthly(ctx, acc[s]),
            "cancelled": _monthly(ctx, cxl[s]), "no_show": _monthly(ctx, ns[s]),
            "room_nights": _monthly(ctx, occ_seg[s]), "revenue": _monthly(ctx, rev_seg[s]),
            "commission": _monthly(ctx, comm_seg[s]),
        }
    ctx.segments = seg_monthly  # type: ignore[attr-defined]
    ctx.block_fnb = _monthly(ctx, block_fnb)  # type: ignore[attr-defined]
    daily["group_block"] = block_taken

    return {
        "available_rooms": _monthly(ctx, avail),
        "room_demand": _monthly(ctx, sum(seg_demand.values())),
        "bookings_accepted": _monthly(ctx, sum(acc.values())),
        "cancellations": _monthly(ctx, sum(cxl.values())),
        "no_shows": _monthly(ctx, sum(ns.values())),
        "walked_guests": _monthly(ctx, walks),
        "occupied_rooms": _monthly(ctx, occupied),
        "rooms_revenue": _monthly(ctx, sum(rev_seg.values())),
        "commissions": _monthly(ctx, sum(comm_seg.values())),
        "no_show_fees": _monthly(ctx, nsfee),
        "walk_costs": _monthly(ctx, walks * r["walk_cost"]),
        "unmet_demand": _monthly(ctx, sum(seg_demand.values()) - sum(acc.values())),
    }


# ---------------------------------------------------------------------------
# Payroll
# ---------------------------------------------------------------------------

PAYROLL_OUTPUTS = [
    _li(f"payroll_{d}", f"Payroll & related – {d}",
        "Headcount × monthly salary × (1 + overtime) × (1 + on-costs) × (1 + annual increase)^year", "currency",
        [f"payroll.headcount.{d}", f"payroll.monthly_salary.{d}", "payroll.overtime_pct", "payroll.on_cost_pct"],
        "expense") for d in DEPARTMENTS
]


@G.node("payroll", deps=[], outputs=PAYROLL_OUTPUTS, description="Fixed payroll by department.")
def _payroll(ctx: Context, v: dict) -> dict:
    p = ctx.a["payroll"]
    esc = ctx.growth(p["annual_increase_pct"])
    factor = (1 + p["overtime_pct"]) * (1 + p["on_cost_pct"])
    return {f"payroll_{d}": p["headcount"][d] * p["monthly_salary"][d] * factor * esc * np.ones(ctx.M)
            for d in DEPARTMENTS}


# ---------------------------------------------------------------------------
# Food & beverage
# ---------------------------------------------------------------------------

@G.node("fnb", deps=["occupied_rooms", "payroll_fnb"], outputs=[
    _li("guest_nights", "In-house guest nights", "Occupied rooms × guests per room", "number",
        ["fnb.guests_per_room"]),
    _li("fnb_covers", "Restaurant covers",
        "Guest nights × (breakfast + lunch + dinner capture) + outside covers/day × days × √seasonality", "number",
        ["fnb.breakfast_capture", "fnb.dinner_capture", "fnb.outside_covers_per_day"]),
    _li("fnb_revenue", "F&B revenue (outlets)", "Σ meal periods: covers × average check × price growth", "currency",
        ["fnb.breakfast_check", "fnb.dinner_check", "fnb.outside_check"], "revenue"),
    _li("fnb_cogs", "F&B cost of sales", "Food revenue × food cost % + beverage revenue × beverage cost %",
        "currency", ["fnb.food_cogs_pct", "fnb.beverage_cogs_pct"], "expense"),
    _li("fnb_other_exp", "F&B other expenses", "F&B revenue × other expense %", "currency",
        ["fnb.other_expense_pct"], "expense"),
    _li("fnb_labour", "F&B payroll (fixed + variable)", "Fixed F&B payroll + covers × variable labour per cover",
        "currency", ["fnb.variable_labour_per_cover"], "expense"),
], description="Restaurant demand from in-house guests and outside diners.")
def _fnb(ctx: Context, v: dict) -> dict:
    f = ctx.a["fnb"]
    season = np.asarray(ctx.a["rooms"]["seasonality"])[ctx.moy - 1]
    price = ctx.growth(ctx.a["rooms"]["rate_growth_pct"])
    infl = ctx.growth(ctx.a["undistributed"]["cost_inflation_pct"])
    gn = v["occupied_rooms"] * f["guests_per_room"]
    bf, lu, di = gn * f["breakfast_capture"], gn * f["lunch_capture"], gn * f["dinner_capture"]
    outside = f["outside_covers_per_day"] * ctx.dim * np.sqrt(season)
    rev = (bf * f["breakfast_check"] + lu * f["lunch_check"] + di * f["dinner_check"]
           + outside * f["outside_check"]) * price
    bev = rev * f["beverage_share"]
    food = rev - bev
    covers = bf + lu + di + outside
    return {
        "guest_nights": gn, "fnb_covers": covers, "fnb_revenue": rev,
        "fnb_cogs": food * f["food_cogs_pct"] + bev * f["beverage_cogs_pct"],
        "fnb_other_exp": rev * f["other_expense_pct"],
        "fnb_labour": v["payroll_fnb"] + covers * f["variable_labour_per_cover"] * infl,
    }


@G.node("spa", deps=["occupied_rooms", "payroll_spa"], outputs=[
    _li("spa_capacity", "Spa treatment capacity", "Therapists × treatments per therapist per day × days", "number",
        ["spa.therapists", "spa.treatments_per_therapist_day"]),
    _li("spa_treatments", "Spa treatments", "min(capacity, occupied rooms × capture + external per day × days)",
        "number", ["spa.treatments_per_occupied_room", "spa.external_treatments_per_day"]),
    _li("spa_revenue", "Spa revenue", "Treatments × average treatment price × price growth", "currency",
        ["spa.avg_treatment_price"], "revenue"),
    _li("spa_costs", "Spa direct costs (excl. payroll)", "Revenue × (product cost % + therapist commission % + other %)",
        "currency", ["spa.product_cost_pct", "spa.therapist_commission_pct", "spa.other_expense_pct"], "expense"),
], description="Spa demand constrained by therapist capacity.")
def _spa(ctx: Context, v: dict) -> dict:
    s = ctx.a["spa"]
    cap = s["therapists"] * s["treatments_per_therapist_day"] * ctx.dim
    demand = v["occupied_rooms"] * s["treatments_per_occupied_room"] + s["external_treatments_per_day"] * ctx.dim
    tr = np.minimum(cap, demand)
    rev = tr * s["avg_treatment_price"] * ctx.growth(ctx.a["rooms"]["rate_growth_pct"])
    return {"spa_capacity": cap, "spa_treatments": tr, "spa_revenue": rev,
            "spa_costs": rev * (s["product_cost_pct"] + s["therapist_commission_pct"] + s["other_expense_pct"])}


@G.node("events", deps=["payroll_events", "rooms_revenue"], outputs=[
    _li("event_count", "Events held", "Events per month × seasonality^0.7", "number", ["events.events_per_month"]),
    _li("event_attendees", "Event attendees", "Events × average attendees", "number", ["events.avg_attendees"]),
    _li("events_revenue", "Events & banqueting revenue",
        "Attendees × banquet F&B per attendee + events × (room rental + AV) × price growth", "currency",
        ["events.fnb_per_attendee", "events.room_rental_per_event", "events.av_per_event"], "revenue"),
    _li("events_costs", "Events direct costs (incl. variable labour)",
        "Banquet F&B × F&B cost % + revenue × other cost % + attendees × labour per attendee", "currency",
        ["events.fnb_cost_pct", "events.other_cost_pct", "events.labour_per_attendee"], "expense"),
    _li("events_fnb_revenue", "Banquet F&B revenue", "Attendees × banquet F&B per attendee × price growth",
        "currency", [], "revenue"),
], description="Meetings, weddings and banqueting.")
def _events(ctx: Context, v: dict) -> dict:
    e = ctx.a["events"]
    season = np.asarray(ctx.a["rooms"]["seasonality"])[ctx.moy - 1]
    price = ctx.growth(ctx.a["rooms"]["rate_growth_pct"])
    infl = ctx.growth(ctx.a["undistributed"]["cost_inflation_pct"])
    n = e["events_per_month"] * season ** 0.7
    att = n * e["avg_attendees"]
    fnb = att * e["fnb_per_attendee"] * price + getattr(ctx, "block_fnb", 0.0)
    rev = fnb + n * (e["room_rental_per_event"] + e["av_per_event"]) * price
    costs = fnb * e["fnb_cost_pct"] + rev * e["other_cost_pct"] + att * e["labour_per_attendee"] * infl
    return {"event_count": n, "event_attendees": att, "events_revenue": rev, "events_costs": costs,
            "events_fnb_revenue": fnb}


@G.node("other_ops", deps=["occupied_rooms", "no_show_fees"], outputs=[
    _li("other_revenue", "Other operated revenue", "Occupied rooms × other revenue per room × price growth + "
        "no-show fees", "currency", ["other_revenue.per_occupied_room"], "revenue"),
    _li("other_costs", "Other operated costs", "Ancillary revenue (excl. no-show fees) × cost %", "currency",
        ["other_revenue.cost_pct"], "expense"),
], description="Laundry, transport, parking and other ancillary income.")
def _other(ctx: Context, v: dict) -> dict:
    o = ctx.a["other_revenue"]
    anc = v["occupied_rooms"] * o["per_occupied_room"] * ctx.growth(ctx.a["rooms"]["rate_growth_pct"])
    return {"other_revenue": anc + v["no_show_fees"], "other_costs": anc * o["cost_pct"]}


# ---------------------------------------------------------------------------
# Departmental results & undistributed expenses
# ---------------------------------------------------------------------------

@G.node("rooms_dept", deps=["rooms_revenue", "occupied_rooms", "commissions", "walk_costs", "payroll_rooms"],
        outputs=[
            _li("rooms_variable_costs", "Rooms variable costs",
                "Occupied rooms × (housekeeping + guest supplies + laundry) × inflation + room revenue × other %",
                "currency", ["rooms_costs.housekeeping_per_occupied_room",
                             "rooms_costs.guest_supplies_per_occupied_room"], "expense"),
            _li("rooms_expenses", "Rooms department expenses",
                "Rooms payroll + variable costs + commissions & distribution + walk costs", "currency", [], "expense"),
            _li("rooms_profit", "Rooms departmental profit", "Room revenue − rooms department expenses", "currency",
                [], "revenue"),
        ], description="Rooms department P&L (USALI-style: commissions are a rooms expense).")
def _rooms_dept(ctx: Context, v: dict) -> dict:
    rc = ctx.a["rooms_costs"]
    infl = ctx.growth(ctx.a["undistributed"]["cost_inflation_pct"])
    var = v["occupied_rooms"] * (rc["housekeeping_per_occupied_room"] + rc["guest_supplies_per_occupied_room"]
                                 + rc["laundry_per_occupied_room"]) * infl + v["rooms_revenue"] * rc["other_expense_pct"]
    exp = v["payroll_rooms"] + var + v["commissions"] + v["walk_costs"]
    return {"rooms_variable_costs": var, "rooms_expenses": exp, "rooms_profit": v["rooms_revenue"] - exp}


@G.node("dept_profit", deps=["fnb_revenue", "fnb_cogs", "fnb_other_exp", "fnb_labour", "spa_revenue", "spa_costs",
                             "payroll_spa", "events_revenue", "events_costs", "payroll_events", "other_revenue",
                             "other_costs", "rooms_revenue", "rooms_profit", "rooms_expenses"],
        outputs=[
            _li("fnb_profit", "F&B departmental profit", "F&B revenue − cost of sales − payroll − other", "currency",
                [], "revenue"),
            _li("spa_profit", "Spa departmental profit", "Spa revenue − direct costs − spa payroll", "currency", [],
                "revenue"),
            _li("events_profit", "Events departmental profit", "Events revenue − direct costs − events payroll",
                "currency", [], "revenue"),
            _li("other_profit", "Other operated profit", "Other revenue − other costs", "currency", [], "revenue"),
            _li("total_revenue", "Total operating revenue", "Rooms + F&B + Spa + Events + Other", "currency", [],
                "revenue"),
            _li("total_dept_expenses", "Total departmental expenses", "Σ departmental expenses", "currency", [],
                "expense"),
            _li("total_dept_profit", "Total departmental profit", "Σ departmental profit", "currency", [], "revenue"),
        ], description="Departmental contribution.")
def _dept(ctx: Context, v: dict) -> dict:
    fnb_exp = v["fnb_cogs"] + v["fnb_other_exp"] + v["fnb_labour"]
    spa_exp = v["spa_costs"] + v["payroll_spa"]
    ev_exp = v["events_costs"] + v["payroll_events"]
    out = {
        "fnb_profit": v["fnb_revenue"] - fnb_exp,
        "spa_profit": v["spa_revenue"] - spa_exp,
        "events_profit": v["events_revenue"] - ev_exp,
        "other_profit": v["other_revenue"] - v["other_costs"],
    }
    out["total_revenue"] = (v["rooms_revenue"] + v["fnb_revenue"] + v["spa_revenue"] + v["events_revenue"]
                            + v["other_revenue"])
    out["total_dept_expenses"] = v["rooms_expenses"] + fnb_exp + spa_exp + ev_exp + v["other_costs"]
    out["total_dept_profit"] = v["rooms_profit"] + out["fnb_profit"] + out["spa_profit"] + out["events_profit"] \
        + out["other_profit"]
    return out


@G.node("undistributed", deps=["total_revenue", "occupied_rooms", "payroll_ag", "payroll_sm", "payroll_pom"],
        outputs=[
            _li("card_fees", "Credit card fees", "Revenue × (1 + VAT) × card share × card fee %", "currency",
                ["undistributed.card_fee_pct", "undistributed.card_share_of_revenue"], "expense"),
            _li("ag_expense", "Administrative & general", "A&G payroll + fixed × inflation + revenue × A&G % + card fees",
                "currency", ["undistributed.ag_fixed_monthly", "undistributed.ag_pct_revenue"], "expense"),
            _li("it_expense", "Information & telecom systems", "IT fixed × inflation", "currency",
                ["undistributed.it_fixed_monthly"], "expense"),
            _li("campaign_spend", "Marketing campaign spend", "Σ active campaigns: spend per month", "currency",
                ["campaigns"], "expense"),
            _li("sm_expense", "Sales & marketing", "S&M payroll + base marketing × inflation + campaign spend",
                "currency", ["undistributed.marketing_monthly"], "expense"),
            _li("pom_expense", "Property operation & maintenance",
                "POM payroll + fixed × inflation + revenue × POM %", "currency",
                ["undistributed.pom_fixed_monthly", "undistributed.pom_pct_revenue"], "expense"),
            _li("energy_kwh", "Energy consumption (kWh)", "Fixed kWh + occupied rooms × kWh per room", "number",
                ["undistributed.energy_fixed_kwh", "undistributed.energy_kwh_per_occupied_room"]),
            _li("utilities_expense", "Utilities", "kWh × price per kWh × inflation + water & other × inflation",
                "currency", ["undistributed.energy_price_per_kwh"], "expense"),
            _li("total_undistributed", "Total undistributed expenses", "A&G + IT + S&M + POM + Utilities", "currency",
                [], "expense"),
        ], description="Undistributed operating expenses.")
def _undist(ctx: Context, v: dict) -> dict:
    u = ctx.a["undistributed"]
    infl = ctx.growth(u["cost_inflation_pct"])
    vat = ctx.a["tax"]["vat_rate"]
    card = v["total_revenue"] * (1 + vat) * u["card_share_of_revenue"] * u["card_fee_pct"]
    ag = v["payroll_ag"] + u["ag_fixed_monthly"] * infl + v["total_revenue"] * u["ag_pct_revenue"] + card
    it = u["it_fixed_monthly"] * infl * np.ones(ctx.M)
    camp = np.zeros(ctx.M)
    for c in ctx.a["campaigns"]:
        mi = ctx.month_index(c.get("start_month", ""))
        if mi is None:
            continue
        camp[mi:min(ctx.M, mi + int(c.get("months", 1)))] += float(c.get("spend_per_month", 0))
    sm = v["payroll_sm"] + u["marketing_monthly"] * infl + camp
    pom = v["payroll_pom"] + u["pom_fixed_monthly"] * infl + v["total_revenue"] * u["pom_pct_revenue"]
    kwh = u["energy_fixed_kwh"] * ctx.dim / 30.0 + v["occupied_rooms"] * u["energy_kwh_per_occupied_room"]
    util = kwh * u["energy_price_per_kwh"] * infl + u["water_other_utilities_monthly"] * infl
    return {"card_fees": card, "ag_expense": ag, "it_expense": it, "campaign_spend": camp, "sm_expense": sm,
            "pom_expense": pom, "energy_kwh": kwh, "utilities_expense": util,
            "total_undistributed": ag + it + sm + pom + util}


@G.node("gop_ebitda", deps=["total_revenue", "total_dept_profit", "total_undistributed"], outputs=[
    _li("gop", "Gross operating profit (GOP)", "Total departmental profit − total undistributed expenses",
        "currency", [], "revenue"),
    _li("mgmt_fees", "Management fees", "Revenue × base fee % + max(GOP, 0) × incentive fee %", "currency",
        ["fees_fixed.base_mgmt_fee_pct", "fees_fixed.incentive_fee_pct_gop"], "expense"),
    _li("fixed_charges", "Fixed charges (insurance, property tax / lease)", "(Insurance + property tax/lease) × "
        "inflation", "currency", ["fees_fixed.insurance_monthly", "fees_fixed.property_tax_lease_monthly"], "expense"),
    _li("ebitda", "EBITDA", "GOP − management fees − fixed charges", "currency", [], "revenue"),
], description="Gross operating profit and EBITDA.")
def _gop(ctx: Context, v: dict) -> dict:
    f = ctx.a["fees_fixed"]
    infl = ctx.growth(ctx.a["undistributed"]["cost_inflation_pct"])
    gop = v["total_dept_profit"] - v["total_undistributed"]
    fees = v["total_revenue"] * f["base_mgmt_fee_pct"] + np.maximum(gop, 0) * f["incentive_fee_pct_gop"]
    fixed = (f["insurance_monthly"] + f["property_tax_lease_monthly"]) * infl
    return {"gop": gop, "mgmt_fees": fees, "fixed_charges": fixed, "ebitda": gop - fees - fixed}


# ---------------------------------------------------------------------------
# Capital expenditure and fixed assets
# ---------------------------------------------------------------------------

@G.node("capex", deps=["total_revenue"], outputs=[
    _li("capex", "Capital expenditure", "FF&E reserve % × revenue + planned project spend", "currency",
        ["capex.ffe_reserve_pct", "capex.projects"], "expense"),
    _li("depreciation", "Depreciation", "Straight-line: cost ÷ (useful life × 12) per month from the month after "
        "acquisition, until fully depreciated", "currency", ["opening_balance.fixed_assets", "capex.ffe_life_years"],
        "expense"),
    _li("fa_gross_opening", "Fixed assets – opening net book value", "Prior month closing NBV", "currency"),
    _li("fa_nbv", "Fixed assets – net book value", "Opening NBV + capex − depreciation", "currency", [], "balance"),
], description="Capex schedule and fixed-asset roll-forward.")
def _capex(ctx: Context, v: dict) -> dict:
    a = ctx.a
    M = ctx.M
    capex = v["total_revenue"] * a["capex"]["ffe_reserve_pct"]
    vintages = []  # (month acquired, amount, life months)
    ffe_life = int(a["capex"]["ffe_life_years"]) * 12
    for m in range(M):
        vintages.append((m, capex[m], ffe_life))
    proj = np.zeros(M)
    for p in a["capex"]["projects"]:
        mi = ctx.month_index(p.get("month", ""))
        if mi is None:
            continue
        proj[mi] += float(p["amount"])
        vintages.append((mi, float(p["amount"]), int(p.get("life_years", 10)) * 12))
    capex = capex + proj
    dep = np.zeros(M)
    opening_nbv = 0.0
    for fa in a["opening_balance"]["fixed_assets"]:
        nbv = fa["cost"] - fa["accumulated"]
        opening_nbv += nbv
        monthly = fa["cost"] / (fa["life_years"] * 12)
        remaining = nbv
        for m in range(M):
            d = min(monthly, remaining)
            dep[m] += d
            remaining -= d
    for (m0, amt, life) in vintages:
        if amt <= 0:
            continue
        monthly = amt / life
        end = min(M, m0 + 1 + life)
        dep[m0 + 1:end] += monthly
    nbv = opening_nbv + np.cumsum(capex - dep)
    opening = np.concatenate([[opening_nbv], nbv[:-1]])
    return {"capex": capex, "depreciation": dep, "fa_gross_opening": opening, "fa_nbv": nbv}


# ---------------------------------------------------------------------------
# Working capital (independent of financing, so computed before the cash loop)
# ---------------------------------------------------------------------------

def balance_from_days(flows: np.ndarray, dim: np.ndarray, days: float) -> np.ndarray:
    """Closing balance equal to the last ``days`` days of a monthly flow.

    Months before the model start are assumed to equal month 1 (steady state).
    """
    M = len(flows)
    out = np.zeros(M)
    for m in range(M):
        remaining, k, bal = float(days), m, 0.0
        while remaining > 1e-12:
            if k >= 0:
                take = min(remaining, dim[k])
                bal += flows[k] * take / dim[k]
            else:
                take = min(remaining, dim[0])
                bal += flows[0] * take / dim[0]
            remaining -= take
            k -= 1
        out[m] = bal
    return out


@G.node("working_capital", deps=["rooms_revenue", "fnb_revenue", "spa_revenue", "events_revenue", "other_revenue",
                                 "total_revenue", "fnb_cogs", "fnb_other_exp", "spa_costs", "events_costs",
                                 "other_costs", "rooms_variable_costs", "commissions", "ag_expense", "card_fees",
                                 "it_expense", "sm_expense", "pom_expense", "utilities_expense", "mgmt_fees",
                                 "fixed_charges", "payroll_ag", "payroll_sm", "payroll_pom", "events_fnb_revenue"],
        outputs=[
            _li("vat_output", "VAT collected (output VAT)", "Total revenue × VAT rate", "currency", ["tax.vat_rate"]),
            _li("gross_billings", "Gross billings incl. VAT", "Total revenue + VAT collected", "currency"),
            _li("accounts_receivable", "Accounts receivable", "Credit billings over the last DSO days", "currency",
                ["working_capital.dso_days", "segments.*.credit_pct"], "balance"),
            _li("inventory", "Inventory (F&B)", "F&B and banquet cost of sales over the last inventory days",
                "currency", ["fnb.inventory_days"], "balance"),
            _li("accounts_payable", "Accounts payable", "Non-payroll costs over the last DPO days", "currency",
                ["working_capital.dpo_days"], "balance"),
            _li("vat_payable", "VAT payable", "Output VAT of the last N months (paid N months later)", "currency",
                ["tax.vat_payment_lag_months"], "balance"),
            _li("deferred_revenue", "Advance deposits (deferred revenue)",
                "Σ segments: next month's room revenue × deposit %", "currency", ["segments.*.deposit_pct"], "balance"),
        ], description="Receivables, payables, inventory, VAT and deposits.")
def _wc(ctx: Context, v: dict) -> dict:
    a = ctx.a
    vat = a["tax"]["vat_rate"]
    wc = a["working_capital"]
    segs = ctx.segments  # type: ignore[attr-defined]
    credit = sum(segs[s]["revenue"] * a["segments"][s]["credit_pct"] for s in SEGMENTS)
    credit = credit + v["events_revenue"] * a["events"]["credit_pct"] + (
        v["fnb_revenue"] + v["spa_revenue"] + v["other_revenue"]) * wc["other_credit_pct"]
    credit = credit * (1 + vat)
    ar = balance_from_days(credit, ctx.dim, wc["dso_days"])
    cogs = v["fnb_cogs"] + v["events_fnb_revenue"] * a["events"]["fnb_cost_pct"]
    inv = balance_from_days(cogs, ctx.dim, a["fnb"]["inventory_days"])
    non_payroll = (v["fnb_cogs"] + v["fnb_other_exp"] + v["spa_costs"] + v["events_costs"] + v["other_costs"]
                   + v["rooms_variable_costs"] + v["commissions"] + (v["ag_expense"] - v["payroll_ag"] - v["card_fees"])
                   + v["it_expense"] + (v["sm_expense"] - v["payroll_sm"]) + (v["pom_expense"] - v["payroll_pom"])
                   + v["utilities_expense"] + v["mgmt_fees"] + v["fixed_charges"])
    ap = balance_from_days(non_payroll, ctx.dim, wc["dpo_days"])
    vat_out = v["total_revenue"] * vat
    lag = int(a["tax"]["vat_payment_lag_months"])
    vat_pay = np.array([vat_out[max(0, m - lag + 1):m + 1].sum() if lag > 0 else 0.0 for m in range(ctx.M)])
    deposits = np.zeros(ctx.M)
    for s in SEGMENTS:
        rev = segs[s]["revenue"]
        nxt = np.concatenate([rev[1:], rev[-1:]])
        deposits += nxt * a["segments"][s]["deposit_pct"]
    return {"vat_output": vat_out, "gross_billings": v["total_revenue"] + vat_out, "accounts_receivable": ar,
            "inventory": inv, "accounts_payable": ap, "vat_payable": vat_pay, "deferred_revenue": deposits}


# ---------------------------------------------------------------------------
# Financing, tax and the three statements (single forward pass, no circularity)
# ---------------------------------------------------------------------------

FIN_OUTPUTS = [
    _li("interest_expense", "Interest expense", "Opening term loan × rate ÷ 12 + opening revolver × rate ÷ 12",
        "currency", ["financing.term_loan_rate", "financing.revolver_rate"], "expense"),
    _li("interest_income", "Interest income", "Opening cash × cash rate ÷ 12", "currency",
        ["financing.cash_interest_rate"], "revenue"),
    _li("ebit", "EBIT", "EBITDA − depreciation", "currency", [], "revenue"),
    _li("ebt", "Profit before tax", "EBIT − interest expense + interest income", "currency", [], "revenue"),
    _li("tax_expense", "Income tax expense",
        "Rate × max(0, YTD profit before tax − losses brought forward) − tax already accrued this year", "currency",
        ["tax.income_tax_rate"], "expense"),
    _li("net_income", "Net income", "Profit before tax − tax expense", "currency", [], "revenue"),
    _li("tax_payable", "Tax payable", "Opening + tax expense − tax paid (paid in the payment month for the prior "
        "year)", "currency", ["tax.tax_payment_month"], "balance"),
    _li("tax_paid", "Tax paid", "Prior-year accrued tax paid in the payment month", "currency"),
    _li("dividends", "Dividends paid", "Prior-year net income × payout % (in the dividend month)", "currency",
        ["financing.dividend_payout_pct"]),
    _li("term_loan", "Term loan balance", "Opening − scheduled repayment", "currency",
        ["financing.term_loan_opening", "financing.term_loan_monthly_repayment"], "balance"),
    _li("term_repayment", "Term loan repayment", "min(scheduled repayment, opening balance)", "currency"),
    _li("revolver", "Revolver balance", "Draw to keep cash ≥ minimum cash (up to limit); repay from excess cash",
        "currency", ["financing.minimum_cash", "financing.revolver_limit"], "balance"),
    _li("revolver_draw", "Revolver draw / (repayment)", "Revolver closing − opening", "currency"),
    _li("cfo", "Cash flow from operations",
        "Net income + depreciation − ΔAR − Δinventory + ΔAP + ΔVAT payable + Δdeposits + Δtax payable", "currency"),
    _li("cfi", "Cash flow from investing", "− Capex", "currency"),
    _li("cff", "Cash flow from financing", "Revolver draw − term repayment − dividends", "currency"),
    _li("net_cash_flow", "Net cash flow", "CFO + CFI + CFF", "currency"),
    _li("cash", "Cash", "Opening cash + net cash flow", "currency", ["opening_balance.cash"], "balance"),
    _li("cash_opening", "Opening cash", "Prior month closing cash", "currency"),
    _li("retained_earnings", "Retained earnings", "Opening + net income − dividends", "currency", [], "balance"),
    _li("share_capital", "Share capital", "Constant", "currency", ["opening_balance.share_capital"], "balance"),
    _li("total_assets", "Total assets", "Cash + AR + inventory + fixed assets NBV", "currency", [], "balance"),
    _li("total_liabilities", "Total liabilities", "AP + VAT payable + deposits + tax payable + term loan + revolver",
        "currency", [], "balance"),
    _li("total_equity", "Total equity", "Share capital + retained earnings", "currency", [], "balance"),
    _li("balance_check", "Balance check (assets − liabilities − equity)", "Must be 0", "currency"),
    _li("cash_receipts", "Cash receipts from customers", "Gross billings − ΔAR + Δdeposits", "currency"),
    _li("funding_gap", "Funding gap", "Cash shortfall below zero after revolver is exhausted", "currency"),
]


@G.node("financials", deps=["ebitda", "depreciation", "capex", "fa_nbv", "accounts_receivable", "inventory",
                            "accounts_payable", "vat_payable", "deferred_revenue", "gross_billings"],
        outputs=FIN_OUTPUTS, description="Debt, tax, cash and the balance sheet.")
def _financials(ctx: Context, v: dict) -> dict:
    a = ctx.a
    ob = a["opening_balance"]
    fin = a["financing"]
    tax = a["tax"]
    M = ctx.M
    out = {li.key: np.zeros(M) for li in FIN_OUTPUTS}

    opening_nbv = sum(fa["cost"] - fa["accumulated"] for fa in ob["fixed_assets"])
    open_assets = ob["cash"] + ob["accounts_receivable"] + ob["inventory"] + opening_nbv
    open_liab = (ob["accounts_payable"] + ob["vat_payable"] + ob["deferred_revenue"] + ob["tax_payable"]
                 + fin["term_loan_opening"])
    re_open = open_assets - open_liab - ob["share_capital"]
    ctx.opening = {  # type: ignore[attr-defined]
        "cash": ob["cash"], "accounts_receivable": ob["accounts_receivable"], "inventory": ob["inventory"],
        "fa_nbv": opening_nbv, "accounts_payable": ob["accounts_payable"], "vat_payable": ob["vat_payable"],
        "deferred_revenue": ob["deferred_revenue"], "tax_payable": ob["tax_payable"],
        "term_loan": fin["term_loan_opening"], "revolver": 0.0, "share_capital": ob["share_capital"],
        "retained_earnings": re_open,
    }

    cash, term, rev, re = ob["cash"], fin["term_loan_opening"], 0.0, re_open
    taxpay = ob["tax_payable"]
    prev = {"ar": ob["accounts_receivable"], "inv": ob["inventory"], "ap": ob["accounts_payable"],
            "vat": ob["vat_payable"], "dep": ob["deferred_revenue"]}
    ytd_ebt = 0.0
    ytd_tax = 0.0
    loss_bf = 0.0
    prior_year_tax = ob["tax_payable"]
    prior_year_ni = 0.0
    year_ni = 0.0
    year_tax_accrued = 0.0

    for m in range(M):
        moy = int(ctx.moy[m])
        if moy == 1 and m > 0:
            # Year end: roll losses forward, reset YTD accumulators.
            loss_bf = max(0.0, loss_bf - ytd_ebt)
            prior_year_tax = year_tax_accrued
            prior_year_ni = year_ni
            ytd_ebt = ytd_tax = year_ni = year_tax_accrued = 0.0

        int_exp = term * fin["term_loan_rate"] / 12 + rev * fin["revolver_rate"] / 12
        int_inc = max(cash, 0.0) * fin["cash_interest_rate"] / 12
        ebit = v["ebitda"][m] - v["depreciation"][m]
        ebt = ebit - int_exp + int_inc
        ytd_ebt += ebt
        target_tax = tax["income_tax_rate"] * max(0.0, ytd_ebt - loss_bf)
        tax_exp = target_tax - ytd_tax
        ytd_tax = target_tax
        year_tax_accrued += tax_exp
        ni = ebt - tax_exp
        year_ni += ni

        paid = 0.0
        if moy == int(tax["tax_payment_month"]):
            paid = max(0.0, min(prior_year_tax, taxpay))
            prior_year_tax = 0.0
        taxpay_new = taxpay + tax_exp - paid

        div = 0.0
        if moy == int(fin["dividend_month"]) and m >= 12 and prior_year_ni > 0:
            div = prior_year_ni * fin["dividend_payout_pct"]

        ar, inv, ap = v["accounts_receivable"][m], v["inventory"][m], v["accounts_payable"][m]
        vat, dep_bal = v["vat_payable"][m], v["deferred_revenue"][m]
        cfo = (ni + v["depreciation"][m] - (ar - prev["ar"]) - (inv - prev["inv"]) + (ap - prev["ap"])
               + (vat - prev["vat"]) + (dep_bal - prev["dep"]) + (taxpay_new - taxpay))
        cfi = -v["capex"][m]
        repay = min(fin["term_loan_monthly_repayment"], term)
        pre = cash + cfo + cfi - repay - div
        draw = 0.0
        if pre < fin["minimum_cash"]:
            draw = min(fin["revolver_limit"] - rev, fin["minimum_cash"] - pre)
            draw = max(draw, 0.0)
        elif rev > 0:
            draw = -min(rev, pre - fin["minimum_cash"])
        cff = draw - repay - div
        cash_new = cash + cfo + cfi + cff

        out["cash_opening"][m] = cash
        out["interest_expense"][m] = int_exp
        out["interest_income"][m] = int_inc
        out["ebit"][m] = ebit
        out["ebt"][m] = ebt
        out["tax_expense"][m] = tax_exp
        out["net_income"][m] = ni
        out["tax_paid"][m] = paid
        out["tax_payable"][m] = taxpay_new
        out["dividends"][m] = div
        out["term_repayment"][m] = repay
        out["term_loan"][m] = term - repay
        out["revolver_draw"][m] = draw
        out["revolver"][m] = rev + draw
        out["cfo"][m] = cfo
        out["cfi"][m] = cfi
        out["cff"][m] = cff
        out["net_cash_flow"][m] = cfo + cfi + cff
        out["cash"][m] = cash_new
        out["funding_gap"][m] = max(0.0, -cash_new)
        out["retained_earnings"][m] = re + ni - div
        out["share_capital"][m] = ob["share_capital"]
        out["cash_receipts"][m] = v["gross_billings"][m] - (ar - prev["ar"]) + (dep_bal - prev["dep"])

        cash, term, rev, re, taxpay = cash_new, term - repay, rev + draw, re + ni - div, taxpay_new
        prev = {"ar": ar, "inv": inv, "ap": ap, "vat": vat, "dep": dep_bal}

    out["total_assets"] = out["cash"] + v["accounts_receivable"] + v["inventory"] + v["fa_nbv"]
    out["total_liabilities"] = (v["accounts_payable"] + v["vat_payable"] + v["deferred_revenue"] + out["tax_payable"]
                                + out["term_loan"] + out["revolver"])
    out["total_equity"] = out["share_capital"] + out["retained_earnings"]
    out["balance_check"] = out["total_assets"] - out["total_liabilities"] - out["total_equity"]
    if (out["funding_gap"] > 0).any():
        first = int(np.argmax(out["funding_gap"] > 0))
        ctx.warnings.append(f"Cash turns negative in {ctx.months[first]} even after the revolver is fully drawn "
                            "(funding gap). The plan is not financeable as configured.")
    elif (out["cash"] < fin["minimum_cash"] - 1).any():
        first = int(np.argmax(out["cash"] < fin["minimum_cash"] - 1))
        ctx.warnings.append(f"Cash falls below the minimum cash target in {ctx.months[first]} "
                            "because the revolver limit is exhausted.")
    return out


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass
class Check:
    name: str
    passed: bool
    max_abs_error: float
    detail: str


@dataclass
class SimulationResult:
    assumptions: dict
    months: pd.PeriodIndex
    series: dict[str, np.ndarray]
    segments: dict[str, dict[str, np.ndarray]]
    daily: pd.DataFrame
    opening: dict[str, float]
    warnings: list[str]
    checks: list[Check] = field(default_factory=list)

    # ---- convenience -----------------------------------------------------
    def s(self, key: str) -> np.ndarray:
        return self.series[key]

    @property
    def month_labels(self) -> list[str]:
        return [str(p) for p in self.months]

    def window(self, start: int = 0, end: int | None = None) -> slice:
        return slice(start, self.months.size if end is None else end)

    def total(self, key: str, sl: slice | None = None) -> float:
        return float(self.series[key][sl or slice(None)].sum())

    def kpis(self, sl: slice | None = None) -> dict[str, float | None]:
        from ..core.kpis import safe_div
        sl = sl or slice(None)
        t = lambda k: float(self.series[k][sl].sum())  # noqa: E731
        avail, occ, rr = t("available_rooms"), t("occupied_rooms"), t("rooms_revenue")
        rev = t("total_revenue")
        payroll = sum(t(f"payroll_{d}") for d in DEPARTMENTS) + t("fnb_labour") - t("payroll_fnb")
        ota_rn = float(self.segments["leisure_ota"]["room_nights"][sl].sum())
        acc = t("bookings_accepted")
        return {
            "occupancy": safe_div(occ, avail),
            "adr": safe_div(rr, occ),
            "net_adr": safe_div(rr - t("commissions"), occ),
            "revpar": safe_div(rr, avail),
            "net_revpar": safe_div(rr - t("commissions"), avail),
            "trevpar": safe_div(rev, avail),
            "goppar": safe_div(t("gop"), avail),
            "gop_margin": safe_div(t("gop"), rev),
            "ebitda": t("ebitda"),
            "ebitda_margin": safe_div(t("ebitda"), rev),
            "labour_cost_pct": safe_div(payroll, rev),
            "fnb_cogs_pct": safe_div(t("fnb_cogs"), t("fnb_revenue")),
            "spa_utilisation": safe_div(t("spa_treatments"), t("spa_capacity")),
            "ota_share": safe_div(ota_rn, occ),
            "cash_conversion": safe_div(t("cfo"), t("ebitda")),
            "cancellation_rate": safe_div(t("cancellations"), acc),
            "total_revenue": rev,
            "rooms_revenue": rr,
            "gop": t("gop"),
            "net_income": t("net_income"),
            "occupied_rooms": occ,
            "available_rooms": avail,
            "closing_cash": float(self.series["cash"][sl][-1]) if self.series["cash"][sl].size else None,
            "contribution": t("total_dept_profit"),
        }

    def annual(self, key: str) -> dict[int, float]:
        years = np.array([p.year for p in self.months])
        return {int(y): float(self.series[key][years == y].sum()) for y in np.unique(years)}

    def year_slice(self, year_number: int) -> slice:
        """Slice for model year 1, 2, 3 …"""
        return slice((year_number - 1) * 12, min(self.months.size, year_number * 12))

    @property
    def all_checks_passed(self) -> bool:
        return all(c.passed for c in self.checks)


def _checks(ctx: Context, v: dict) -> list[Check]:
    tol = 0.01  # one halala (SAR 0.01)
    out: list[Check] = []

    def add(name, err, detail):
        e = float(np.max(np.abs(err))) if np.size(err) else 0.0
        out.append(Check(name, e <= tol, e, detail))

    add("Balance sheet balances", v["balance_check"], "Total assets − total liabilities − total equity = 0")
    open_cash = np.concatenate([[ctx.opening["cash"]], v["cash"][:-1]])  # type: ignore[attr-defined]
    add("Cash roll-forward", open_cash + v["net_cash_flow"] - v["cash"], "Opening cash + net cash flow = closing cash")
    open_re = np.concatenate([[ctx.opening["retained_earnings"]], v["retained_earnings"][:-1]])  # type: ignore
    add("Retained earnings roll-forward", open_re + v["net_income"] - v["dividends"] - v["retained_earnings"],
        "Opening RE + net income − dividends = closing RE")
    open_debt = np.concatenate([[ctx.opening["term_loan"]], v["term_loan"][:-1]])  # type: ignore
    add("Term loan roll-forward", open_debt - v["term_repayment"] - v["term_loan"], "Opening − repayment = closing")
    open_rev = np.concatenate([[0.0], v["revolver"][:-1]])
    add("Revolver roll-forward", open_rev + v["revolver_draw"] - v["revolver"], "Opening + draws = closing")
    add("Fixed asset roll-forward", v["fa_gross_opening"] + v["capex"] - v["depreciation"] - v["fa_nbv"],
        "Opening NBV + capex − depreciation = closing NBV")
    add("Revenue reconciliation", v["total_revenue"] - (v["rooms_revenue"] + v["fnb_revenue"] + v["spa_revenue"]
                                                        + v["events_revenue"] + v["other_revenue"]),
        "Total revenue = Σ departmental revenue")
    add("Contribution reconciliation", v["total_dept_profit"] - (v["total_revenue"] - v["total_dept_expenses"]),
        "Departmental profit = revenue − departmental expenses")
    add("EBITDA reconciliation", v["ebitda"] - (v["total_dept_profit"] - v["total_undistributed"] - v["mgmt_fees"]
                                                - v["fixed_charges"]), "EBITDA = dept. profit − undistributed − fees "
                                                                       "− fixed charges")
    segs = ctx.segments  # type: ignore[attr-defined]
    rr = sum(segs[s]["revenue"] for s in SEGMENTS)
    add("Room revenue by segment reconciles", rr - v["rooms_revenue"], "Σ segment revenue = room revenue")
    over = np.maximum(v["occupied_rooms"] - v["available_rooms"], 0)
    add("Room inventory: occupied ≤ available", over, "No month sells more rooms than available")
    booked = v["bookings_accepted"] - v["cancellations"] - v["no_shows"] - v["walked_guests"] - v["occupied_rooms"]
    add("Booking reconciliation (rooms)", booked,
        "Accepted − cancelled − no-shows − walked = occupied room nights")
    neg = np.minimum(v["available_rooms"], 0)
    add("Room inventory non-negative", neg, "Available rooms ≥ 0")
    ni_check = v["ebitda"] - v["depreciation"] - v["interest_expense"] + v["interest_income"] - v["tax_expense"] \
        - v["net_income"]
    add("Income statement integrity", ni_check, "EBITDA − D&A − interest + interest income − tax = net income")
    return out


def simulate(a: dict, validate: bool = True) -> SimulationResult:
    """Run the full model for an assumption tree."""
    if validate:
        validate_or_raise(a)
    ctx = build_context(a)
    v = G.evaluate(ctx)
    res = SimulationResult(a, ctx.months, v, ctx.segments, ctx.daily, ctx.opening,  # type: ignore[attr-defined]
                           ctx.warnings)
    res.checks = _checks(ctx, v)
    if not res.all_checks_passed:
        res.warnings.append("One or more model integrity checks failed – results are unreliable.")
    return res


@lru_cache(maxsize=16)
def _cached(js: str) -> SimulationResult:
    import json
    return simulate(json.loads(js))


def simulate_cached(a: dict) -> SimulationResult:
    """Memoised simulation keyed by the exact assumption JSON (safe: results are immutable by convention)."""
    return _cached(to_json(a))
