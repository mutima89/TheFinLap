# Calculations and assumptions

This document explains the conventions behind the numbers. The full list of line-item formulas, all 91 drivers
with their baseline values and allowed ranges, the KPI definitions and the integrity checks is generated from the
code in [CALCULATION_REFERENCE_GENERATED.md](CALCULATION_REFERENCE_GENERATED.md).

**Every value in the simulator is a fictional training assumption.** The figures are chosen to be internally
consistent and plausible for teaching; they are not real hotel data, not market benchmarks, and not tax or legal
advice. Every one of them is editable in the Scenario Lab.

## 1. Time, currency and units

* Horizon: 36 months starting January 2027 (model years 1–3 = FY2027–FY2029). Room demand is simulated **daily**
  (1,096 days) and aggregated to months; everything else is monthly.
* Currency: **SAR**. USD display multiplies by the fixed fictional rate `meta.fx_usd_per_sar` = 0.2667. Conversion
  is presentation only; calculations run in SAR.
* Revenue and costs are shown **excluding VAT**. Amounts are not rounded inside the engine; tables round for
  display only. Integrity checks use a tolerance of SAR 0.01 per month.
* Percentages are stored as fractions (0.15 = 15%).

## 2. Operating model (summary)

| Area | How it works |
|---|---|
| Room demand | For each day and segment: base demand × monthly seasonality × day-of-week factor × special-event multiplier × annual growth × (realised rate ÷ reference rate)^elasticity × campaign uplift × seeded log-normal noise |
| Rates | Published rate × (1 − discount) × seasonality^rate flex × annual rate growth × post-renovation uplift |
| Inventory | Available = total rooms − out-of-order − renovation rooms. Contracted group blocks are committed first; then segments are accepted in booking-window order (longest lead first) up to available × (1 + overbooking %) and any segment cap |
| Wash | Cancellations = accepted × cancellation %; no-shows = (accepted − cancelled) × no-show %; a share of cancelled rooms is resold to unmet late demand |
| Overbooking | Expected walked guests from a normal approximation of arrival uncertainty; each walk costs `rooms.walk_cost` |
| Rooms department | Commissions (segment rate + campaign extra) are a rooms expense; variable cost per occupied room (housekeeping, supplies, laundry); rooms payroll |
| F&B | In-house covers = occupied rooms × guests per room × capture rate per meal, plus outside covers; average checks; food and beverage cost of sales; variable labour per cover plus fixed F&B payroll |
| Spa | Treatments demanded (per occupied room + external) capped by therapist capacity; product cost and therapist commission |
| Events | Events per month × attendees × F&B spend + room rental + AV; event costs and labour |
| Payroll | Headcount × monthly salary × (1 + overtime) × (1 + on-costs) × (1 + annual increase)^year, by department |
| Undistributed | A&G, sales & marketing (incl. campaign spend), maintenance, utilities (fixed + per occupied room kWh × price), IT, card fees; fixed elements inflate annually |
| Fees and fixed charges | Base management fee 3% of total revenue + incentive fee 8% of GOP (if positive); insurance and property tax/lease |
| Profit levels | Departmental profit → GOP = departmental profit − undistributed → EBITDA = GOP − management fees − fixed charges |

## 3. VAT

* VAT rate 15% (fictional default, `tax.vat_rate`). Revenue in the P&L is **net of VAT**.
* Output VAT = total revenue × rate. It is a liability (`vat_payable`), paid with a one-month lag
  (`tax.vat_payment_lag_months`).
* Receivables are carried **including** VAT (customers owe the gross amount). Input VAT on purchases is not
  modelled separately; costs are treated as net amounts.
* The revenue-to-cash bridge shows revenue → + VAT → gross billings → − change in receivables → + change in
  deposits → cash received.

## 4. Working capital

* Receivables = credit sales (segment credit share, events credit share, other departments' credit share) × (1 +
  VAT), converted to a balance with DSO days. Inventory from F&B cost of sales and inventory days. Payables from
  non-payroll costs and DPO days. Advance deposits (deferred revenue) = next month's segment revenue × deposit %.
* A **positive** change in receivables or inventory **reduces** operating cash flow; a positive change in
  payables, VAT payable, deposits or tax payable **increases** it.

## 5. Capex and depreciation

* FF&E reserve capex = 4% of revenue each month (`capex.ffe_reserve_pct`), depreciated over 7 years.
* Projects (renovations, equipment) have a month, amount and life; optional rooms out of order for N months and
  rate/demand uplifts after completion.
* Opening fixed assets (building, FF&E, IT) depreciate straight-line over their remaining lives.

## 6. Financing, tax and the three statements

The financial statements are produced in **one forward pass with no circular references**:

* Interest expense = **opening** term loan × rate ÷ 12 + **opening** revolver × rate ÷ 12. Interest income =
  opening cash × cash rate ÷ 12. Using opening balances is a deliberate simplification that avoids circularity.
* Term loan: SAR 140m opening at 6%, repaid SAR 600k per month.
* Revolver: drawn automatically when cash would fall below the **minimum cash** (SAR 15m) up to its limit (SAR
  40m, 7.5%), and repaid from cash above the minimum. If the revolver is exhausted, cash can fall below the
  minimum; if it would fall below zero, the shortfall is recorded as a **funding gap** and the model warns that the
  plan is not financeable as configured.
* Income tax 20% (fictional) on year-to-date profit before tax after losses brought forward; the accrual is
  trued up monthly; the prior year's tax is paid in April. Dividends (0% payout by default) are paid in May from
  prior-year net income.
* Balance sheet: cash + receivables + inventory + fixed assets = payables + VAT payable + deposits + tax payable +
  term loan + revolver + share capital + retained earnings. Opening retained earnings are the balancing figure of
  the opening balance sheet.

## 7. Integrity checks (every run)

Balance sheet balances; cash, retained earnings, term loan, revolver and fixed-asset roll-forwards; revenue,
contribution, EBITDA and income statement reconciliations; segment revenue sums to room revenue; occupied ≤
available; booking reconciliation (accepted − cancelled − no-shows − walked = occupied); available rooms ≥ 0. A
failed check is shown on the Statements page and in Settings → Integrity check; the self-test fails if any
reference scenario fails a check.

## 8. FP&A conventions

* Variance = actual − budget (or forecast). Classification: for revenue and profit lines a positive variance is
  favourable; for cost lines a positive variance is unfavourable; a context note explains when higher
  activity-driven costs accompany higher revenue.
* Materiality: a variance is material when it reaches **both** the absolute threshold (default SAR 250,000) and
  the percentage threshold (default 5%), or when it reaches three times the absolute threshold whatever its
  percentage. Both thresholds are configurable in Settings.
* Price/volume/mix: rate variance = (actual rate − budget rate) × actual volume; volume variance = (actual volume
  − budget volume) × budget rate; mix isolates the effect of segment proportions.
* Flexible budget: fixed costs at budget, variable costs at budget rates × actual activity; spending variance =
  actual − flexed.
* Explanations quantify drivers that the data measures (for example "OTA room nights +21% vs budget; average
  commission 7.1% vs 5.8%") and list separately what must be confirmed. Correlation or an unexplained remainder is
  never presented as a cause.
* Run-rate = YTD × 12 ÷ months elapsed. It ignores seasonality, which is why the latest estimate is preferred. Latest estimate = actual months +
  working scenario for the remaining months. Rolling forecast = next N months from the working scenario.
* Forecast accuracy: MAPE = mean(|actual − forecast| ÷ actual); bias = mean(forecast − actual), positive meaning
  over-forecasting.

## 9. Investment appraisal

For each case the engine runs with and without the project:

```
FCF_0 = − capex (− initial working capital where relevant)
FCF_t = ΔEBITDA_t − tax rate × (ΔEBITDA_t − tax depreciation_t) − Δworking capital_t
```

Years 1–3 come from the engine; later years extend year 3 at the stated growth (an explicit, editable
assumption). Working capital is released in the final year. A terminal value (Gordon growth: CF × (1 + g) ÷
(r − g)) is added only for going-concern cases (the acquisition). Discount rates are fictional defaults (9–11%).
NPV discounts year-end flows; IRR reports multiple roots or none when cash-flow signs change more than once;
MIRR uses stated finance and reinvestment rates; payback interpolates within the year.

## 10. Sensitivity and Monte Carlo

Every sensitivity re-runs the full engine. A demand multiplier applies to every segment's base demand. Monte
Carlo samples selected drivers from normal, triangular or uniform distributions (shown on screen) with a visible
seed (default 42) and iteration count; the same inputs reproduce the same results. Outputs are percentiles of
scenario outcomes under those assumptions, not forecasts.

## 11. Grading and competency rules

**Excel Lab.** Each task scores 70% value + 30% method. Value: correct within tolerance (full), close (partial),
wrong or missing (none). Method: a live formula, the expected functions, no hard-coded inputs. The grader
recalculates supported functions itself because openpyxl does not calculate formulas; if its result differs from
the value Excel saved, the cell is flagged. Unsupported functions are graded on the saved value. Reconciliation
checks (for example "Bookings revenue = Daily revenue", "balance sheet balances") are reported separately. The
user's file is copied before grading and never modified.

**Decision Room.** Overall = 20% numerical accuracy + 20% evidence + 30% judgement + 15% risk + 15%
communication.
* Numerical: within 5% (or SAR 20k) of the engine result = 100%; within 15% = 60%; right direction only = 25%.
* Evidence: F1 score of the drivers you ticked vs the relevant drivers (50%), quoting a number (25%), having viewed
  the evidence and run the comparison (25%).
* Judgement: the option's quality (set per case) plus 20 points when your justification states the condition that
  makes a weaker option defensible.
* Risk: generic risk language and case-specific risks (up to two of each).
* Communication: recommendation in the first sentence, 40–180 words, a number, and a next step or owner.

**Learning path.** Pass mark 70%. Guided/independent exercise score = 100% − 15% per hint (minimum 50%), 30% if the
solution was revealed. Competency check: share of questions answered correctly, no hints. Competency levels:
*Demonstrated* needs at least two practical passes (≥70%), at least one hint-free, and a weighted score ≥70%;
quiz-type evidence alone is capped at *Developing*. Activity weights: check 0.5, guided 0.5, independent 1.0,
applied/workbook/decision 1.5, capstone 2.0.

**Capstone.** Each of the ten steps scores 0–100% with its own rubric (numeric tolerances, rule selection F1,
method choice, text rubrics with required elements and length); the overall score is the average once all ten
steps are submitted.

All scores are practice feedback generated by rules in this application. They are not an accredited
qualification or a guarantee of employment.

## 12. The fictional "actual world"

FP&A actuals, decision outcomes and the capstone are generated by the same engine from a different assumption
set, so the learner can discover real drivers. The FP&A actual world (`analysis/fpa.py`) differs from the Base
case by: a different demand random seed; a key corporate account lost from April 2027 (−18% corporate demand); an
unbudgeted OTA promotion March–September 2027 (+30% OTA demand, +3 points commission, SAR 60k a month); overtime
9% instead of 5%; four extra F&B staff; energy SAR 0.33/kWh instead of 0.30; food cost 32% instead of 30%; DSO 55
days instead of 45; spa capture 0.065 instead of 0.08 treatments per occupied room. These events are fictional.
