# User guide

Aurelia Finance Lab puts you in the finance team of **The Aurelia Grand**, a fictional 150-room luxury hotel.
Everything you see is calculated live by one financial engine from a set of assumptions you can change. All
figures are fictional training data, not industry benchmarks.

## 1. First start

The first time the app opens, a short tour explains what is fictional, where your data is stored and lets you
pick the theme and currency. You can replay it from **Settings and Data → Show welcome tour again**.

The window has a navigation list on the left (grouped Business, Analysis, Practice, Output), a search box at the
top, the working scenario name, a currency selector (SAR or USD) and a theme button.

| Shortcut | Action |
|---|---|
| Ctrl+K | Search lessons, KPIs, drivers, models, decision cases and the glossary |
| Ctrl+Z / Ctrl+Y | Undo / redo a driver change |
| Ctrl+S | Save the working draft into the current scenario |
| Ctrl+T | Toggle light/dark theme |
| Ctrl+1 … Ctrl+9 | Jump to the first nine pages |
| F1 | Help |

## 2. Suggested route

1. Read the **Dashboard**.
2. In the **Scenario Lab**, change a room rate, a demand assumption and a cost; watch revenue, EBITDA and cash move.
3. Start **Learning Path → Stage 1**. Each topic ends with an applied task and a competency check; when every
   topic of a stage has both, the next stage unlocks.
4. Use **Revenue Management, FP&A, Statements, Workbench, Risk** and **Investment** while you study the matching
   stages.
5. Practise judgement in the **Executive Decision Room**, then complete the **Capstone**.
6. Export your **portfolio** from Reports.

## 3. Business pages

### Dashboard
Eight KPI cards (occupancy, ADR, RevPAR, total revenue, GOP, EBITDA, net income, closing cash) for the chosen
period, compared with the comparison scenario. Click a card to open the analysis behind it. Charts show revenue
and EBITDA by month, occupancy/ADR/RevPAR, departmental contribution and cash/debt. Panels show the budget and
forecast status, your next learning objective, open decisions, recent work and your competency levels.

### Scenario Lab
Every assumption is a **driver** with a label, unit, allowed range and help text (91 drivers in groups such as
Capacity, Demand, Pricing, Channels, F&B, Payroll, Costs, Working capital, Financing). Change a value and the
whole model recalculates.

* Invalid values (outside the range, wrong type) are rejected with a message and the previous value is kept.
* Every change is written to the **audit trail** and auto-saved as a **draft**, so closing the app loses nothing.
* **Save** writes the draft into the current scenario; **Save as** creates a new scenario. The three reference
  scenarios (Base, Upside, Downside) are protected; save your changes under a new name.
* **Checkpoints** store a named snapshot you can return to. **Revert** discards the draft; **Reset to baseline**
  returns every driver to the Base case. **Clone**, **Rename** and **Delete** manage your own scenarios.
* Choose a **comparison scenario** to see differences on every page.

### Revenue Management
Segment and channel economics (gross ADR, commission, net ADR, contribution per room night), booking pace and
pickup, group **displacement** analysis (the engine runs with and without the block), an engine-evaluated rate
search, a minimum-length-of-stay exercise, an overbooking risk table and forecast accuracy (MAPE, bias).

### FP&A and Variances
* **Budget** = the budget scenario (default Base case). **Actuals** = the fictional "real" year, produced by the
  same engine from hidden actual-world assumptions, up to the close month. **Latest estimate** = actuals plus the
  working scenario for the remaining months.
* Variance = actual − budget. **F/U** depends on the nature of the line (more revenue is favourable, more cost is
  unfavourable) and a context note explains cases where activity drives cost.
* **Materiality** (default SAR 250,000 and 5%, change in Settings) marks which variances need explanation.
* **Explanations** list the quantified drivers behind each material variance and, separately, the causes that
  the data cannot confirm. The app never states a cause the data does not establish.
* The **flexible budget** restates variable costs at actual activity, separating volume from efficiency.
* Record **action plans** (owner, due date, status) and save dated **forecast versions** of the latest estimate,
  which move through draft → submitted → approved or rejected, with the approver's name recorded.

### Financial Statements
USALI-style operating statement, income statement, balance sheet, cash flow statement and a revenue-to-cash
bridge, monthly or annual. The **Integrity checks** tab shows the 14 checks run on every calculation (balance
sheet balances, cash and debt roll-forwards, segment and departmental reconciliations, room inventory).

## 4. Analysis pages

### Modelling Workbench
Models A–H (revenue drivers, departmental profit, operating statement, three statements, 36-month forecast,
working capital, capex, unit economics). The **dependency viewer** shows which drivers feed a line item and what
it feeds. You can define **custom formulas** over engine outputs (a safe expression language, no code execution);
the app warns about models that would be fragile.

### Sensitivity and Risk
One-way and two-way tables, a tornado chart, break-even demand, scenario comparison, **Monte Carlo** and forecast
error. Monte Carlo shows its distributions, random seed and iteration count; the same inputs give the same
result. Its output is a range of outcomes *under the stated assumptions*, not a prediction.

### Investment Cases
Six business cases (room refurbishment, couples' hammam suite, chiller repair vs replace, direct-booking
marketing, in-house laundry, acquisition of the fictional 80-room Aurelia Oasis Resort). Each runs the engine
with and without the project and turns the difference into after-tax incremental cash flows. Results: NPV, IRR
(with a warning for multiple or missing IRRs), MIRR, payback, discounted payback, profitability index and
sensitivities. Every parameter is editable.

## 5. Practice pages

### Executive Decision Room
Nine cases, each taken through seven steps:

1. **Inspect the evidence** (KPIs and case-specific tables).
2. **Identify the drivers** (tick the ones that matter; some listed drivers are red herrings).
3–5. **Analyse, compare and quantify**: *Run comparison* shows each option's component lines from the engine;
   the total is hidden until you submit. *Load the starting position into the Scenario Lab* lets you explore it.
6. **Recommend** an option and enter your estimate of its effect.
7. **Justify** in an executive note (40–180 words works best).

The rubric scores **numerical accuracy** (20%), **evidence quality** (20%), **commercial judgement** (30%),
**risk awareness** (15%) and **communication** (15%), with feedback for each. Then the **outcome** is revealed:
what the result would have been in the "real" world of the case, and what an experienced analyst would
investigate next. Several options are defensible in most cases; stating the condition that makes your choice
right earns credit. The rubric is rule-based: it checks structure, numbers, drivers and risk language and cannot
judge prose like a person.

### Learning Path
Nine stages: financial literacy and operating drivers; Excel analysis and model construction; hotel revenue
management; management accounting and variances; budgeting and rolling forecasts; financial statement modelling
and cash flow; investment appraisal and scenarios; commercial finance and business partnering; executive
communication and the integrated capstone.

Each topic has tabs:
* **Learn**: concept, business context, a worked example calculated live from the engine, the common mistake, how
  to interpret the result and alternative approaches.
* **Guided exercise** (hints available) → **Independent exercise** (hints lower the score) → **Applied task** (in
  the simulator, the Excel Lab, the Decision Room or the Capstone) → **Competency check** (no hints, 70% to pass).
  Each step unlocks when the previous one is passed.
* **Coach & progress**: the offline coach diagnoses common errors (wrong sign, ×100 percentage slips, thousands
  vs units, and topic-specific mistakes), gives progressive hints, explains any KPI from the current scenario and
  recommends topics based on your recurring mistakes.

A competency is **Demonstrated** only with at least two practical passes (independent exercise, applied task,
workbook, decision or capstone step) scoring at least 70%, at least one of them without hints, and a weighted
score of at least 70%. Quiz answers alone can only reach **Developing**.

### Excel Lab
1. **Generate** the four workbooks (Revenue KPIs, Variance Analysis, Three-Statement, Investment Appraisal) into
   a folder of your choice. Existing files are never overwritten; a numbered copy is created instead. Tick the
   box to also create the completed **reference** workbooks.
2. Complete the yellow cells in Excel using formulas.
3. **Grade**: choose your file. The app copies it into its data folder and grades the copy; your original is
   never modified. Each task is marked correct, partly correct, wrong or missing, scored 70% on the value and 30%
   on the method (live formula, expected functions, no hard-coded numbers), with feedback on known mistakes and
   reconciliation checks. Click a row for the coach's explanation.

openpyxl, the library used to read workbooks, reads formulas but does not calculate them. The app therefore
recalculates supported formulas with its own documented calculator (the function list is shown on the page) and
compares them with the values Excel saved. Cells using other functions are graded on Excel's saved value and
flagged; if a file was saved by a program that stores no results, those cells cannot be checked.

### Capstone
A fictional 2028 dataset with deliberate defects (duplicates, inconsistent labels, numbers stored as text, a
missing value, an impossible value, a sign error, an entry keyed in thousands) plus control totals and a budget.
Ten steps: validate the data, build the KPIs, reconcile to budget, forecast the next quarter, integrated
financial analysis, evaluate two investments, quantify risk, design an owner dashboard, write the executive
recommendation, and defend it in a meeting. Each step is scored and saved; the overall score appears when all ten
are submitted. *Export the dataset* writes the CSV files.

## 6. Reports
* **Monthly management report** with seven sections: executive summary; actual, budget and forecast; material
  variances; evidence-supported explanations; forward-looking risks; recommended corrective actions; action owners
  and due dates. Preview, then save as HTML or PDF. Actions come from the FP&A action plans; suggested actions
  that have no owner yet are marked "assign a name".
* **Statements to Excel** (annual or monthly), **variance tables to Excel**, **scenario comparison to Excel**.
* **Portfolio**: your competency profile, completed topics, model outputs, scenarios and assumptions, decision
  rationale, workbook grades, capstone results, action plans and forecast versions, as HTML, PDF and JSON, with the
  statement that it is practice feedback, not a qualification.

## 7. Settings and Data
* Theme, currency (USD uses the fixed fictional rate in the assumptions), FP&A close month and materiality.
* **Your data**: the folder path, *Open folder*, **Back up** (one `.db` file), **Restore** (the backup is
  validated first, you confirm, and a safety copy of current data is made), **Export/Import scenarios** (JSON).
* **Integrity check**: database checks plus the 14 model checks for every saved scenario.
* **Reset all data**: confirm, then type `RESET`. A safety backup is written first.

## 8. Where your data is

`%APPDATA%\AureliaFinanceLab\` on Windows (for example `C:\Users\<you>\AppData\Roaming\AureliaFinanceLab`):
`aurelia.db` (everything), `graded\` (copies of workbooks you graded), `diagnostics\` (self-test reports) and any
safety backups. Uninstalling is deleting the program folder; delete this folder too to remove your data.
