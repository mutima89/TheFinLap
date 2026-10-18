"""Assumption schema, baseline data and validation for The Aurelia Grand.

ALL FIGURES ARE FICTIONAL TRAINING ASSUMPTIONS. They are chosen to be
internally plausible for a 150-room luxury hotel but they are not industry
benchmarks and must not be quoted as such.

Assumptions are a nested ``dict`` (JSON-serialisable so that scenarios can be
stored in SQLite and reproduced exactly). ``DRIVER_SPECS`` describes every
user-editable driver: its path, label, unit, valid range and help text. The
same specs drive input validation, the scenario editor and the audit trail.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 1

SEGMENTS = ["corporate", "leisure_direct", "leisure_ota", "group", "wholesale"]
SEGMENT_LABELS = {
    "corporate": "Corporate (negotiated)",
    "leisure_direct": "Leisure – direct",
    "leisure_ota": "Leisure – OTA",
    "group": "Group",
    "wholesale": "Wholesale",
}
DEPARTMENTS = ["rooms", "fnb", "spa", "events", "ag", "sm", "pom"]
DEPARTMENT_LABELS = {
    "rooms": "Rooms",
    "fnb": "Food & Beverage",
    "spa": "Spa & Wellness",
    "events": "Events & Banqueting",
    "ag": "Admin & General (Finance, HR, IT)",
    "sm": "Sales & Marketing",
    "pom": "Engineering & Maintenance",
}

# Saudi working week: Sunday–Thursday; weekend Friday–Saturday.
# Index 0 = Monday … 6 = Sunday (Python's weekday()).
_DOW_CORP = [1.15, 1.15, 1.10, 0.95, 0.45, 0.55, 1.15]
_DOW_LEIS = [0.80, 0.80, 0.85, 1.15, 1.35, 1.25, 0.80]
_DOW_FLAT = [1.0] * 7

BASELINE: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "meta": {
        "hotel_name": "The Aurelia Grand",
        "group_name": "Aurelia Hospitality Group",
        "start_month": "2027-01",
        "months": 36,
        "currency": "SAR",
        "fx_usd_per_sar": 0.2667,
        "data_note": "Fictional training data. Not real benchmarks.",
    },
    "rooms": {
        "total_rooms": 150,
        "out_of_order_rooms": 2,
        "demand_growth_pct": 0.03,
        "rate_growth_pct": 0.03,
        "seasonality": [1.15, 1.15, 1.10, 1.00, 0.95, 0.80, 0.70, 0.72, 0.95, 1.10, 1.15, 1.10],
        "seasonal_rate_flex": 0.5,
        "reference_rate_flex": 0.5,  # calibration: how the market reference rate moves with season
        "demand_noise_sd": 0.05,
        "random_seed": 2027,
        "overbooking_pct": 0.0,
        "walk_cost": 1500.0,
        "cancellation_resale_pct": 0.6,
        "no_show_charge_pct": 0.5,
        "group_blocks": [],
        "special_events": [
            {"name": "Capital Season Gala Week (fictional)", "month": 11, "start_day": 10, "end_day": 16,
             "multiplier": 1.6, "recurring": True},
            {"name": "Regional Investment Forum (fictional)", "month": 2, "start_day": 8, "end_day": 11,
             "multiplier": 1.45, "recurring": True},
        ],
    },
    "segments": {
        "corporate": {"published_rate": 1250.0, "discount_pct": 0.10, "base_demand": 45.0, "elasticity": -0.6,
                      "commission_pct": 0.03, "cancellation_pct": 0.08, "no_show_pct": 0.02, "los": 2.1,
                      "lead_days": 14, "dow": _DOW_CORP, "cap": None, "credit_pct": 0.60, "deposit_pct": 0.0,
                      "reference_rate": 1125.0},
        "leisure_direct": {"published_rate": 1400.0, "discount_pct": 0.0, "base_demand": 25.0, "elasticity": -1.6,
                           "commission_pct": 0.025, "cancellation_pct": 0.12, "no_show_pct": 0.03, "los": 2.6,
                           "lead_days": 30, "dow": _DOW_LEIS, "cap": None, "credit_pct": 0.0, "deposit_pct": 0.20,
                           "reference_rate": 1400.0},
        "leisure_ota": {"published_rate": 1400.0, "discount_pct": 0.05, "base_demand": 30.0, "elasticity": -1.9,
                        "commission_pct": 0.18, "cancellation_pct": 0.18, "no_show_pct": 0.04, "los": 2.3,
                        "lead_days": 21, "dow": _DOW_LEIS, "cap": None, "credit_pct": 0.0, "deposit_pct": 0.0,
                        "reference_rate": 1330.0},
        "group": {"published_rate": 950.0, "discount_pct": 0.0, "base_demand": 20.0, "elasticity": -0.9,
                  "commission_pct": 0.0, "cancellation_pct": 0.05, "no_show_pct": 0.01, "los": 3.0,
                  "lead_days": 90, "dow": _DOW_CORP, "cap": 40.0, "credit_pct": 0.80, "deposit_pct": 0.30,
                  "reference_rate": 950.0},
        "wholesale": {"published_rate": 800.0, "discount_pct": 0.0, "base_demand": 18.0, "elasticity": -1.2,
                      "commission_pct": 0.0, "cancellation_pct": 0.10, "no_show_pct": 0.02, "los": 3.5,
                      "lead_days": 60, "dow": _DOW_FLAT, "cap": 20.0, "credit_pct": 1.0, "deposit_pct": 0.0,
                      "reference_rate": 800.0},
    },
    "fnb": {
        "guests_per_room": 1.6,
        "breakfast_capture": 0.75, "breakfast_check": 140.0,
        "lunch_capture": 0.15, "lunch_check": 190.0,
        "dinner_capture": 0.30, "dinner_check": 320.0,
        "outside_covers_per_day": 135.0, "outside_check": 260.0,
        "beverage_share": 0.18,
        "food_cogs_pct": 0.30, "beverage_cogs_pct": 0.25,
        "other_expense_pct": 0.06,
        "variable_labour_per_cover": 12.0,
        "inventory_days": 20.0,
    },
    "spa": {
        "therapists": 10, "treatments_per_therapist_day": 5.0,
        "treatments_per_occupied_room": 0.08, "external_treatments_per_day": 6.0,
        "avg_treatment_price": 650.0, "product_cost_pct": 0.08,
        "therapist_commission_pct": 0.10, "other_expense_pct": 0.05,
    },
    "events": {
        "events_per_month": 22.0, "avg_attendees": 120.0, "fnb_per_attendee": 260.0,
        "room_rental_per_event": 9000.0, "av_per_event": 2500.0,
        "fnb_cost_pct": 0.33, "other_cost_pct": 0.08, "labour_per_attendee": 25.0,
        "credit_pct": 0.70,
    },
    "other_revenue": {"per_occupied_room": 45.0, "cost_pct": 0.35},
    "rooms_costs": {
        "housekeeping_per_occupied_room": 35.0, "guest_supplies_per_occupied_room": 55.0,
        "laundry_per_occupied_room": 30.0, "other_expense_pct": 0.02,
    },
    "payroll": {
        "on_cost_pct": 0.22, "overtime_pct": 0.05, "annual_increase_pct": 0.04,
        "headcount": {"rooms": 55, "fnb": 70, "spa": 14, "events": 10, "ag": 22, "sm": 9, "pom": 16},
        "monthly_salary": {"rooms": 6000.0, "fnb": 7500.0, "spa": 6500.0, "events": 7000.0, "ag": 12000.0,
                           "sm": 14000.0, "pom": 7500.0},
    },
    "undistributed": {
        "ag_fixed_monthly": 180000.0, "ag_pct_revenue": 0.01,
        "it_fixed_monthly": 90000.0,
        "marketing_monthly": 160000.0,
        "pom_fixed_monthly": 140000.0, "pom_pct_revenue": 0.012,
        "energy_fixed_kwh": 350000.0, "energy_kwh_per_occupied_room": 45.0, "energy_price_per_kwh": 0.30,
        "water_other_utilities_monthly": 60000.0,
        "card_share_of_revenue": 0.70, "card_fee_pct": 0.018,
        "cost_inflation_pct": 0.03,
    },
    "fees_fixed": {
        "base_mgmt_fee_pct": 0.03, "incentive_fee_pct_gop": 0.08,
        "insurance_monthly": 60000.0, "property_tax_lease_monthly": 150000.0,
    },
    "campaigns": [],
    "tax": {"vat_rate": 0.15, "vat_payment_lag_months": 1, "income_tax_rate": 0.20, "tax_payment_month": 4},
    "working_capital": {
        "dso_days": 45.0, "dpo_days": 40.0, "other_credit_pct": 0.10,
    },
    "capex": {
        "ffe_reserve_pct": 0.04, "ffe_life_years": 7,
        "projects": [],
    },
    "opening_balance": {
        "cash": 25_000_000.0, "accounts_receivable": 9_000_000.0, "inventory": 1_500_000.0,
        "accounts_payable": 7_000_000.0, "vat_payable": 2_500_000.0, "deferred_revenue": 2_000_000.0,
        "tax_payable": 4_000_000.0, "share_capital": 120_000_000.0,
        "fixed_assets": [
            {"name": "Building", "cost": 300_000_000.0, "accumulated": 60_000_000.0, "life_years": 50},
            {"name": "FF&E", "cost": 50_000_000.0, "accumulated": 25_000_000.0, "life_years": 7},
            {"name": "IT systems", "cost": 4_000_000.0, "accumulated": 2_000_000.0, "life_years": 4},
        ],
    },
    "financing": {
        "term_loan_opening": 140_000_000.0, "term_loan_rate": 0.06, "term_loan_monthly_repayment": 600_000.0,
        "revolver_limit": 40_000_000.0, "revolver_rate": 0.075, "minimum_cash": 15_000_000.0,
        "cash_interest_rate": 0.02, "dividend_payout_pct": 0.0, "dividend_month": 5,
    },
}


@dataclass(frozen=True)
class DriverSpec:
    path: str
    label: str
    unit: str  # currency | pct | number | int | rooms | ratio
    minimum: float
    maximum: float
    category: str
    help: str
    step: float = 1.0


def _seg_specs() -> list[DriverSpec]:
    out = []
    for s in SEGMENTS:
        lab = SEGMENT_LABELS[s]
        out += [
            DriverSpec(f"segments.{s}.published_rate", f"{lab}: published rate", "currency", 100, 20000,
                       "Revenue Management", "Rate before segment discount, excl. VAT.", 25),
            DriverSpec(f"segments.{s}.discount_pct", f"{lab}: discount", "pct", 0, 0.9, "Revenue Management",
                       "Discount off the published rate (rate fence).", 0.01),
            DriverSpec(f"segments.{s}.base_demand", f"{lab}: base demand (requests/day)", "number", 0, 500,
                       "Demand", "Unconstrained booking requests per day at the reference rate, before "
                       "seasonality, day-of-week and events.", 1),
            DriverSpec(f"segments.{s}.elasticity", f"{lab}: price elasticity", "ratio", -6, 0, "Demand",
                       "% change in demand for a 1% change in realised rate. Must be ≤ 0.", 0.1),
            DriverSpec(f"segments.{s}.commission_pct", f"{lab}: commission / distribution fee", "pct", 0, 0.5,
                       "Distribution", "Share of gross room revenue paid to the channel.", 0.005),
            DriverSpec(f"segments.{s}.cancellation_pct", f"{lab}: cancellation rate", "pct", 0, 0.9, "Demand",
                       "Share of accepted bookings cancelled before arrival.", 0.01),
            DriverSpec(f"segments.{s}.no_show_pct", f"{lab}: no-show rate", "pct", 0, 0.5, "Demand",
                       "Share of non-cancelled bookings that do not arrive.", 0.005),
        ]
    return out


DRIVER_SPECS: list[DriverSpec] = [
    DriverSpec("rooms.total_rooms", "Total rooms", "int", 1, 2000, "Capacity", "Physical room count.", 1),
    DriverSpec("rooms.out_of_order_rooms", "Out-of-order rooms (daily)", "int", 0, 2000, "Capacity",
               "Rooms unavailable for sale each day.", 1),
    DriverSpec("rooms.demand_growth_pct", "Annual demand growth", "pct", -0.5, 0.5, "Demand",
               "Year-on-year change in unconstrained demand.", 0.005),
    DriverSpec("rooms.rate_growth_pct", "Annual rate growth", "pct", -0.5, 0.5, "Revenue Management",
               "Year-on-year change in published rates (and the market reference rate).", 0.005),
    DriverSpec("rooms.seasonal_rate_flex", "Seasonal rate flex", "ratio", 0, 2, "Revenue Management",
               "How strongly rates follow seasonality (0 = flat pricing).", 0.1),
    DriverSpec("rooms.demand_noise_sd", "Daily demand volatility (σ)", "pct", 0, 0.5, "Demand",
               "Std. deviation of seeded daily demand noise. 0 = fully deterministic.", 0.01),
    DriverSpec("rooms.random_seed", "Random seed", "int", 0, 2**31 - 1, "Demand",
               "Seed for reproducible demand noise.", 1),
    DriverSpec("rooms.overbooking_pct", "Overbooking allowance", "pct", 0, 0.3, "Revenue Management",
               "Bookings accepted above available rooms (advanced).", 0.005),
    DriverSpec("rooms.walk_cost", "Cost per walked guest", "currency", 0, 20000, "Revenue Management",
               "Relocation & compensation cost when an overbooked guest is walked.", 50),
    DriverSpec("rooms.cancellation_resale_pct", "Resale of cancelled rooms", "pct", 0, 1, "Demand",
               "Share of cancelled rooms resold to remaining unmet demand.", 0.05),
    *_seg_specs(),
    DriverSpec("segments.group.cap", "Group ceiling (rooms/night)", "number", 0, 2000, "Revenue Management",
               "Maximum group rooms accepted per night (inventory allocation).", 1),
    DriverSpec("segments.wholesale.cap", "Wholesale allotment (rooms/night)", "number", 0, 2000,
               "Revenue Management", "Maximum wholesale rooms per night (inventory allocation).", 1),
    DriverSpec("fnb.breakfast_capture", "Breakfast capture", "pct", 0, 1.5, "Food & Beverage",
               "Breakfast covers per in-house guest.", 0.01),
    DriverSpec("fnb.dinner_capture", "Dinner capture", "pct", 0, 1.5, "Food & Beverage",
               "Dinner covers per in-house guest.", 0.01),
    DriverSpec("fnb.dinner_check", "Dinner average check", "currency", 0, 5000, "Food & Beverage",
               "Average spend per dinner cover.", 5),
    DriverSpec("fnb.outside_covers_per_day", "Outside (non-resident) covers per day", "number", 0, 2000,
               "Food & Beverage", "Restaurant covers from non-residents.", 1),
    DriverSpec("fnb.food_cogs_pct", "Food cost of sales", "pct", 0, 1, "Food & Beverage",
               "Food COGS as % of food revenue.", 0.005),
    DriverSpec("spa.therapists", "Spa therapists", "int", 0, 200, "Spa", "Therapist headcount.", 1),
    DriverSpec("spa.avg_treatment_price", "Average treatment price", "currency", 0, 10000, "Spa",
               "Average revenue per treatment.", 10),
    DriverSpec("spa.treatments_per_occupied_room", "Spa capture per occupied room", "ratio", 0, 2, "Spa",
               "Treatments per occupied room night.", 0.01),
    DriverSpec("events.events_per_month", "Events per month", "number", 0, 500, "Events",
               "Average events per month before seasonality.", 1),
    DriverSpec("events.fnb_per_attendee", "Banquet F&B per attendee", "currency", 0, 5000, "Events",
               "Average banquet food & beverage spend per attendee.", 5),
    DriverSpec("payroll.overtime_pct", "Overtime (% of base pay)", "pct", 0, 1, "Payroll",
               "Overtime premium as share of base salaries.", 0.005),
    DriverSpec("payroll.on_cost_pct", "Payroll on-costs", "pct", 0, 1, "Payroll",
               "Benefits, social insurance, housing and medical as % of base pay.", 0.01),
    DriverSpec("payroll.annual_increase_pct", "Annual salary increase", "pct", -0.2, 0.3, "Payroll",
               "Applied each January after the first year.", 0.005),
    *[DriverSpec(f"payroll.headcount.{d}", f"Headcount – {DEPARTMENT_LABELS[d]}", "int", 0, 2000, "Payroll",
                 "Full-time equivalent employees.", 1) for d in DEPARTMENTS],
    *[DriverSpec(f"payroll.monthly_salary.{d}", f"Avg monthly salary – {DEPARTMENT_LABELS[d]}", "currency", 0,
                 200000, "Payroll", "Average base pay per FTE per month.", 100) for d in DEPARTMENTS],
    DriverSpec("rooms_costs.housekeeping_per_occupied_room", "Housekeeping cost per occupied room", "currency",
               0, 2000, "Operating costs", "Variable cleaning labour/contractor cost.", 1),
    DriverSpec("rooms_costs.guest_supplies_per_occupied_room", "Guest supplies per occupied room", "currency",
               0, 2000, "Operating costs", "Amenities and consumables.", 1),
    DriverSpec("undistributed.marketing_monthly", "Base marketing spend (monthly)", "currency", 0, 1e8,
               "Operating costs", "Brand and digital marketing excluding campaigns.", 5000),
    DriverSpec("undistributed.energy_price_per_kwh", "Energy price per kWh", "currency", 0, 10,
               "Operating costs", "Unit cost of electricity (fictional tariff).", 0.01),
    DriverSpec("undistributed.energy_kwh_per_occupied_room", "Energy kWh per occupied room", "number", 0, 1000,
               "Operating costs", "Variable energy consumption.", 1),
    DriverSpec("undistributed.ag_fixed_monthly", "A&G fixed costs (monthly)", "currency", 0, 1e8,
               "Operating costs", "Non-payroll administrative costs.", 5000),
    DriverSpec("undistributed.cost_inflation_pct", "Annual cost inflation", "pct", -0.2, 0.5, "Operating costs",
               "Applied to fixed costs each year.", 0.005),
    DriverSpec("fees_fixed.base_mgmt_fee_pct", "Base management fee", "pct", 0, 0.2, "Fees & fixed charges",
               "% of total revenue paid to the operator.", 0.0025),
    DriverSpec("tax.vat_rate", "VAT rate", "pct", 0, 0.5, "Tax",
               "Output VAT charged on revenue (assumption; verify current law).", 0.005),
    DriverSpec("tax.income_tax_rate", "Income tax rate", "pct", 0, 0.6, "Tax",
               "Applied to positive taxable profit after loss relief (simplified).", 0.005),
    DriverSpec("working_capital.dso_days", "Days sales outstanding (credit sales)", "number", 0, 365,
               "Working capital", "Collection period for invoiced customers.", 1),
    DriverSpec("working_capital.dpo_days", "Days payables outstanding", "number", 0, 365, "Working capital",
               "Supplier payment period for non-payroll costs.", 1),
    DriverSpec("fnb.inventory_days", "F&B inventory days", "number", 0, 365, "Working capital",
               "Days of cost of sales held as stock.", 1),
    DriverSpec("capex.ffe_reserve_pct", "FF&E reserve (% revenue)", "pct", 0, 0.3, "Capital",
               "Ongoing replacement capex.", 0.005),
    DriverSpec("financing.term_loan_rate", "Term loan interest rate", "pct", 0, 0.5, "Financing",
               "Annual rate on the term loan.", 0.0025),
    DriverSpec("financing.minimum_cash", "Minimum cash balance", "currency", 0, 1e9, "Financing",
               "Revolver draws automatically to keep cash above this level.", 100000),
    DriverSpec("opening_balance.cash", "Opening cash", "currency", 0, 1e10, "Financing",
               "Cash at the start of the model.", 100000),
]
SPEC_BY_PATH = {s.path: s for s in DRIVER_SPECS}

# A short list of headline drivers used by the vertical-slice what-if panel.
HEADLINE_DRIVERS = [
    "segments.corporate.published_rate",
    "segments.leisure_direct.published_rate",
    "segments.leisure_ota.published_rate",
    "segments.leisure_ota.base_demand",
    "segments.corporate.base_demand",
    "rooms.out_of_order_rooms",
    "payroll.overtime_pct",
    "undistributed.energy_price_per_kwh",
    "undistributed.marketing_monthly",
]


def baseline() -> dict[str, Any]:
    """A deep copy of the baseline assumptions (never mutate ``BASELINE``)."""
    return copy.deepcopy(BASELINE)


def get_path(data: dict, path: str) -> Any:
    node: Any = data
    for part in path.split("."):
        if isinstance(node, list):
            node = node[int(part)]
        else:
            node = node[part]
    return node


def set_path(data: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    node: Any = data
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    last = parts[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value


class ValidationError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def coerce_value(path: str, value: Any) -> Any:
    spec = SPEC_BY_PATH.get(path)
    if spec is None:
        return value
    if value is None and path.endswith(".cap"):
        return None
    if spec.unit == "int":
        return int(round(float(value)))
    return float(value)


def validate(a: dict) -> list[str]:
    """Return a list of human-readable problems. Empty list = valid."""
    problems: list[str] = []
    for spec in DRIVER_SPECS:
        try:
            v = get_path(a, spec.path)
        except (KeyError, IndexError, TypeError):
            problems.append(f"Missing assumption: {spec.label} ({spec.path}).")
            continue
        if v is None and spec.path.endswith(".cap"):
            continue
        if not isinstance(v, (int, float)) or v != v:
            problems.append(f"{spec.label} must be a number.")
            continue
        if v < spec.minimum or v > spec.maximum:
            problems.append(f"{spec.label} = {v} is outside the valid range [{spec.minimum}, {spec.maximum}].")
    r = a["rooms"]
    if r["out_of_order_rooms"] > r["total_rooms"]:
        problems.append("Out-of-order rooms cannot exceed total rooms (negative inventory).")
    if len(r["seasonality"]) != 12 or any(x <= 0 for x in r["seasonality"]):
        problems.append("Seasonality needs 12 positive monthly factors.")
    for s in SEGMENTS:
        seg = a["segments"][s]
        if len(seg["dow"]) != 7 or any(x < 0 for x in seg["dow"]):
            problems.append(f"{SEGMENT_LABELS[s]}: day-of-week profile needs 7 non-negative factors.")
        if seg["cancellation_pct"] + seg["no_show_pct"] >= 1:
            problems.append(f"{SEGMENT_LABELS[s]}: cancellation + no-show rate must be below 100%.")
        if seg.get("reference_rate", 0) <= 0:
            problems.append(f"{SEGMENT_LABELS[s]}: reference rate must be positive.")
    meta = a["meta"]
    if not (1 <= int(meta["months"]) <= 120):
        problems.append("Model horizon must be 1–120 months.")
    for p in a["capex"]["projects"]:
        if p.get("amount", 0) < 0 or p.get("life_years", 1) <= 0:
            problems.append(f"Capex project '{p.get('name')}' needs a non-negative amount and positive life.")
    for c in a["campaigns"]:
        if c.get("segment") not in SEGMENTS:
            problems.append(f"Campaign '{c.get('name')}' targets an unknown segment.")
    return problems


def validate_or_raise(a: dict) -> None:
    problems = validate(a)
    if problems:
        raise ValidationError(problems)


def diff(a: dict, b: dict, prefix: str = "") -> list[tuple[str, Any, Any]]:
    """List (path, old, new) differences between two assumption trees."""
    out: list[tuple[str, Any, Any]] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            p = f"{prefix}.{k}" if prefix else str(k)
            if k not in a or k not in b:
                out.append((p, a.get(k), b.get(k)))
            else:
                out += diff(a[k], b[k], p)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b) and not any(
            isinstance(x, dict) for x in a + b):
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                out.append((f"{prefix}.{i}", x, y))
    elif a != b:
        out.append((prefix, a, b))
    return out


def to_json(a: dict) -> str:
    return json.dumps(a, sort_keys=True)


def from_json(s: str) -> dict:
    data = json.loads(s)
    return upgrade(data)


def upgrade(data: dict) -> dict:
    """Fill keys added in later versions from the baseline (forward compatibility)."""
    base = baseline()

    def merge(dst: dict, src: dict) -> None:
        for k, v in src.items():
            if k not in dst:
                dst[k] = copy.deepcopy(v)
            elif isinstance(v, dict) and isinstance(dst[k], dict):
                merge(dst[k], v)

    merge(data, base)
    data["schema_version"] = SCHEMA_VERSION
    return data
