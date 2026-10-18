"""KPI definitions shared by every screen, report and exercise.

Each KPI has one definition and one formula string shown to users "on demand".
Calculation helpers return ``None`` when a KPI is undefined (for example ADR
when no rooms were sold) so that the UI can show "n/a" instead of a fake zero.
"""
from __future__ import annotations

from dataclasses import dataclass

from .finance import safe_div


@dataclass(frozen=True)
class KPI:
    key: str
    name: str
    formula: str
    unit: str  # currency | pct | number | rooms
    nature: str  # higher_better | lower_better | context
    description: str


KPI_DEFINITIONS: dict[str, KPI] = {
    k.key: k
    for k in [
        KPI("occupancy", "Occupancy", "Occupied rooms ÷ Available rooms (after out-of-order)", "pct",
            "context", "Share of sellable rooms that were occupied. High occupancy at a low rate can destroy value."),
        KPI("adr", "ADR (gross)", "Gross room revenue ÷ Occupied rooms", "currency", "context",
            "Average daily rate actually achieved per occupied room, before distribution costs, excluding VAT."),
        KPI("net_adr", "Net ADR", "(Gross room revenue − Commissions & distribution fees) ÷ Occupied rooms", "currency",
            "higher_better", "Rate the hotel keeps after paying OTAs, wholesalers' channels and booking fees."),
        KPI("revpar", "RevPAR", "Gross room revenue ÷ Available rooms  (= Occupancy × ADR)", "currency",
            "higher_better", "Room revenue per available room. Combines rate and occupancy."),
        KPI("net_revpar", "Net RevPAR", "Net room revenue ÷ Available rooms", "currency", "higher_better",
            "RevPAR after distribution costs."),
        KPI("trevpar", "TRevPAR", "Total operating revenue ÷ Available rooms", "currency", "higher_better",
            "Total revenue (all departments) per available room."),
        KPI("goppar", "GOPPAR", "Gross operating profit ÷ Available rooms", "currency", "higher_better",
            "Profitability per available room; captures cost efficiency as well as revenue."),
        KPI("gop_margin", "GOP margin", "Gross operating profit ÷ Total operating revenue", "pct", "higher_better",
            "Share of revenue left after departmental and undistributed expenses."),
        KPI("ebitda", "EBITDA", "GOP − Management fees − Fixed charges", "currency", "higher_better",
            "Earnings before interest, tax, depreciation and amortisation."),
        KPI("ebitda_margin", "EBITDA margin", "EBITDA ÷ Total operating revenue", "pct", "higher_better",
            "EBITDA as a share of revenue."),
        KPI("labour_cost_pct", "Payroll % of revenue", "Total payroll & related ÷ Total operating revenue", "pct",
            "lower_better", "Labour productivity indicator. Must be read alongside activity levels."),
        KPI("fnb_cogs_pct", "F&B cost of sales %", "F&B cost of sales ÷ F&B revenue", "pct", "lower_better",
            "Food and beverage material cost ratio."),
        KPI("spa_utilisation", "Spa utilisation", "Treatments delivered ÷ Treatment capacity", "pct", "context",
            "How much therapist capacity was sold."),
        KPI("ota_share", "OTA share of room nights", "OTA room nights ÷ Total room nights", "pct", "context",
            "Dependence on online travel agents. Higher share usually means higher distribution cost."),
        KPI("cash_conversion", "Cash conversion", "Operating cash flow ÷ EBITDA", "pct", "higher_better",
            "How much of EBITDA turns into operating cash in the period."),
        KPI("dso", "Days sales outstanding", "Accounts receivable ÷ (Billings incl. VAT) × days", "number",
            "lower_better", "How long customers take to pay."),
        KPI("cancellation_rate", "Cancellation rate", "Cancelled bookings ÷ Gross bookings accepted", "pct",
            "lower_better", "Share of accepted bookings that cancelled before arrival."),
    ]
}


def occupancy(occupied_rooms: float, available_rooms: float) -> float | None:
    if available_rooms is not None and available_rooms < 0:
        raise ValueError("Available rooms cannot be negative.")
    if occupied_rooms is not None and available_rooms and occupied_rooms > available_rooms + 1e-9:
        raise ValueError("Occupied rooms cannot exceed available rooms.")
    return safe_div(occupied_rooms, available_rooms)


def adr(room_revenue: float, occupied_rooms: float) -> float | None:
    return safe_div(room_revenue, occupied_rooms)


def revpar(room_revenue: float, available_rooms: float) -> float | None:
    return safe_div(room_revenue, available_rooms)


def net_adr(room_revenue: float, distribution_cost: float, occupied_rooms: float) -> float | None:
    return safe_div(room_revenue - distribution_cost, occupied_rooms)


def goppar(gop: float, available_rooms: float) -> float | None:
    return safe_div(gop, available_rooms)


def fmt_value(value: float | None, unit: str, currency: str = "SAR", decimals: int | None = None) -> str:
    """Format a KPI for display. ``None`` renders as 'n/a'."""
    if value is None:
        return "n/a"
    if unit == "pct":
        return f"{value * 100:.{1 if decimals is None else decimals}f}%"
    if unit == "currency":
        d = 0 if decimals is None else decimals
        if abs(value) >= 1_000_000 and decimals is None:
            return f"{currency} {value / 1_000_000:,.2f}m"
        return f"{currency} {value:,.{d}f}"
    if unit == "rooms":
        return f"{value:,.0f}"
    return f"{value:,.{1 if decimals is None else decimals}f}"
