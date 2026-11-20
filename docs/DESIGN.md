# Design: Fund-Level Risk Analytics & Hedge Recommendations

This document describes the design of the code in `src/fund_analytics/`, organised by the
case study's Parts 1, 2 and 4. It describes only what the code does. Where the brief asks
about something the code doesn't cover, the section says so.

| Module | Contents |
|---|---|
| `models.py` | `Cashflow` (Pydantic model for one CSV row), `CashflowType`, `KNOWN_CURRENCIES`, the cleaning and validation rules |
| `loader.py` | `read_rows`, `validate_rows`, `load_cashflows`; the result types `Fix`, `Rejection`, `LoadResult`; the cross-row checks |
| `valuation.py` | `npv`, `xirr`, `nav_schedule` |
| `analytics.py` | `compute_analytics`; the result types `IrrLevel`, `IrrResult`, `NavSchedule` |
| `hedging.py` | `recommend_hedges`, `rolling_forwards`, `roll_dates`, `add_months`; the result types `HedgeTrade`, `HedgePlan` |
| `__main__.py` | Command-line report: `python -m fund_analytics <csv_path>` |

---

## Part 1: Schema Design

### 1.1 Cashflow

`Cashflow` in `models.py` is the only Pydantic model. Each field's alias is the CSV
column name.

```python
class CashflowType(StrEnum):
    INVESTMENT = "Investment"
    INTEREST = "Interest"
    PRINCIPAL_REPAYMENT = "Principal Repayment"


class Cashflow(BaseModel):
    model_config = ConfigDict(frozen=True, validate_by_name=True, validate_by_alias=True)

    id: int = Field(alias="ID", gt=0)
    fund_name: str = Field(alias="Fund Name", min_length=1)
    cashflow_date: date = Field(alias="Date")
    cashflow_type: CashflowType = Field(alias="Cashflow Type")
    local_currency: str = Field(alias="Local Currency")
    amount_local: Decimal = Field(alias="Cashflow Amount Local")
    amount_base: Decimal = Field(alias="Cashflow Amount Base")
    base_currency: str = Field(alias="Base Currency")
```

- `frozen=True`: a validated cashflow can't be changed afterwards.
- Amounts are `Decimal`. They are converted to `float` only when passed to the IRR, NAV and
  exposure maths in `analytics.py` and `hedging.py`. Results that are money amounts go back
  to `Decimal`: the NAV exit value (summed exactly) and each hedge notional (rounded to cents).
- The field validators that clean and check each value are listed in 2.4.

### 1.2 Validation results

`loader.py` returns a `LoadResult` with three lists: `valid` (`Cashflow` rows), `fixes`
(one `Fix(row_id, column, raw, cleaned)` per formatting fix) and `rejected` (one
`Rejection(row_id, reasons, raw)` per rejected row, keeping the row as read). How rows end
up in each list is in 2.4.

### 1.3 NAV schedule and IRR results

`analytics.py` defines the analytics outputs as frozen dataclasses.

```python
class IrrLevel(StrEnum):
    CURRENCY = "currency"
    FUND = "fund"


@dataclass(frozen=True)
class IrrResult:
    fund: str
    level: IrrLevel
    currency: str  # local currency, or the fund's base currency at fund level
    irr: float | None  # None when no IRR exists
    rejected_row_ids: tuple[str, ...]  # data-quality flag: rejected rows from this fund
    error: str | None = None  # why there is no IRR


@dataclass(frozen=True)
class NavSchedule:
    fund: str
    currency: str  # local currency; NAV values are in this currency
    irr: float | None  # the currency-level IRR used as the discount rate
    points: tuple[tuple[date, float], ...]  # (date, NAV) on every cashflow date
    exit_value: Decimal | None  # sum of the cashflows on the final date, exact
    rejected_row_ids: tuple[str, ...]
    error: str | None = None

    @property
    def passes_sanity_checks(self) -> bool: ...  # NAV(first date) = 0, NAV(last date) = exit value
```

### 1.4 FX hedge trade

`hedging.py` defines a recommended trade and the set of trades for one exposure, as
frozen dataclasses. They are recommendations only: nothing is booked or stored.

```python
@dataclass(frozen=True)
class HedgeTrade:  # one FX forward
    trade_date: date
    value_date: date  # 3 months after trade_date, or the last cashflow date
    sell_currency: str
    buy_currency: str
    notional_local: Decimal  # in the deal's local currency, whichever side it is on; rounded to cents


@dataclass(frozen=True)
class HedgePlan:  # all forwards for one (fund, local currency)
    fund: str
    local_currency: str
    base_currency: str
    trades: tuple[HedgeTrade, ...]
    rejected_row_ids: tuple[str, ...]  # the fund's data-quality flag, as on NavSchedule
    error: str | None = None  # why there are no trades (no IRR)
```

There is no forward rate field: the data has no market rates, so the rate is left to
execution.

### 1.5 Relationship to Fund, Deal and Currency

The code has no separate Fund, Deal or Currency entities. They appear as values on each
`Cashflow`:

- **Fund** is the `fund_name` string. Analytics are grouped by it. The loader requires
  every row of a fund to have the same `base_currency`; if they disagree, all of that
  fund's rows are rejected (`_reject_inconsistent_base_currency`).
- **Deal**: the CSV has no deal column. Each (fund, local currency) pair is treated as
  one deal, so "per currency" results are per (fund, local currency).
- **Currency** appears in two roles: `local_currency` (what the cashflow is paid in) and
  `base_currency` (what the fund reports in). Both must be in `KNOWN_CURRENCIES`, a fixed
  list of 13 ISO 4217 codes: USD, EUR, GBP, JPY, CHF, CAD, AUD, NZD, SEK, NOK, DKK, SGD,
  HKD. A `HedgePlan` exists only where the two differ: it sells the local currency and
  buys the base currency.

### 1.6 Schema evolution

What the code does when the input format changes:

- **An extra column** in the CSV is ignored. `read_rows` passes it through, and Pydantic
  ignores fields the model doesn't define.
- **A missing expected column** stops the load: `read_rows` raises
  `ValueError("<path>: missing columns [...]")` before any row is processed. The expected
  columns are derived from the model's aliases (`EXPECTED_COLUMNS`), so the model is the
  single definition of the format.
- **Column order** doesn't matter, because rows are read as dicts keyed by header name.
  Header names are stripped of surrounding spaces.
- **A new currency** is supported by adding it to `KNOWN_CURRENCIES`.
- **A new cashflow type** needs a new `CashflowType` member, and a decision on its sign in
  `_check_sign`, which currently requires Investment to be negative and every other type
  to be positive.

Database schema evolution is not covered by the code: it stores nothing.

#### In production (not implemented)

When the results move to a database, schema changes would be handled like this:

- **Database migrations in two phases** (e.g. with Alembic). First *expand*: add the new
  column as nullable and write to both the old and new columns. Then *contract*: drop the
  old column once nothing reads it. Neither step needs downtime.
- **Versioned ingestion contract.** Each uploaded batch records a `schema_version`, so an
  old batch can always be re-read under the rules it arrived with.
- **Traceable results.** Each computed result (IRR, NAV point, hedge trade) records the
  code version and the input batch that produced it, so a schema change never silently
  changes history.

---

## Part 2: Pipeline Design

### 2.1 Steps and dependencies

The pipeline runs in one process, in this order. Each step uses the output of the one
before it.

```
CSV file
  │  read_rows(path)                       loader.py
  ▼
rows (dicts) + malformed rows (Rejection)
  │  validate_rows(rows)                   loader.py
  │    ├─ Cashflow.model_validate(row)     models.py   (per row: clean or reject)
  │    ├─ _reject_duplicate_ids            loader.py   (cross-row)
  │    └─ _reject_inconsistent_base_currency
  ▼
LoadResult(valid, fixes, rejected)
  │  compute_analytics(result)             analytics.py
  │    ├─ xirr(flows)                      valuation.py
  │    └─ nav_schedule(flows, irr)         valuation.py
  ▼
list[IrrResult], list[NavSchedule]
  │  recommend_hedges(result, schedules)   hedging.py
  │    ├─ roll_dates(first, last)          hedging.py  (3-month grid)
  │    └─ npv(irr, later flows, date)      valuation.py (exposure on each roll date)
  ▼
list[HedgePlan]
  │  main()                                __main__.py
  ▼
printed report
```

```python
# What `python -m fund_analytics <csv_path>` does (simplified from __main__.py):


def main(argv):
    path = parse_args(argv).csv_path
    if not path.is_file():
        print("error: file not found", file=sys.stderr)
        return 1

    result = load_cashflows(path)  # read_rows + validate_rows; malformed rows added to rejected
    # printed inline in main(): row counts, then each Fix and each Rejection

    irrs, schedules = compute_analytics(result)
    # printed inline in main(): one line per IrrResult, plus _warning(...) when
    # rejected_row_ids is set ("WARNING incomplete data: rejected row(s) ...")
    print_nav_schedules(schedules)  # with OK/FAILED for the sanity checks
    print_hedges(recommend_hedges(result, schedules))  # one table per exposure
    return 0
```

### 2.2 Trigger mechanism

The pipeline is run by hand from the command line, with the CSV path as a required
argument:

```bash
uv run python -m fund_analytics data/CST_Case_Study_data.csv
make run                                   # same, on the sample file (DATA=path to override)
```

Not covered by this submission: automatic triggers (on upload or on a schedule) and
orchestration across steps or services.

### 2.3 Separation of concerns

Each module has one job, and imports only point one way (no module imports one that
imports it back):

| Module | Imports from the package |
|---|---|
| `__main__.py` | `analytics`, `hedging`, `loader` |
| `hedging.py` | `analytics`, `loader`, `valuation` |
| `analytics.py` | `loader`, `models`, `valuation` |
| `loader.py` | `models` |
| `models.py` | none (Pydantic only) |
| `valuation.py` | none (standard library only) |

- **`models.py`**: the rules for one row. It knows nothing about files or other rows.
- **`loader.py`**: reading the CSV and the checks that need several rows. It knows
  nothing about IRR or NAV.
- **`valuation.py`**: the maths. It works on lists of `(date, float)` pairs, imports only
  the standard library, and does no I/O.
- **`analytics.py`**: groups valid rows by fund and currency, calls `valuation.py`, and
  attaches the data-quality flags. It doesn't read files or print.
- **`hedging.py`**: turns NAV schedules into FX forwards. It uses `valuation.npv` for the
  exposure and knows nothing about files or printing.
- **`__main__.py`**: the only module that prints. It calls the other modules in order and
  formats their results; it does no calculations itself.

Data serving (an API or database for a web application) is not covered by this
submission.

### 2.4 Dirty data handling

Every problem goes into one of three tiers. The rule is to fix only formatting that has a
single possible meaning, and never to guess business data.

**Fixed and logged** (a `Fix` is recorded for each):

| Column | What is fixed |
|---|---|
| Fund Name | Extra or surrounding whitespace |
| Date | Stray characters at either end (spaces, tabs, `` ` ``, `'`, `"`), extra spaces, the `HH:MM:SS` format or no time instead of the standard `DD/MM/YYYY HH:MM`. The time is dropped |
| Cashflow Type | Case and whitespace (e.g. `" principal  repayment"`) |
| Local / Base Currency | Case and surrounding spaces (e.g. `" gbp "`) |
| Amounts | Spaces inside the number |

Thousands separators are accepted without logging a fix, so `"2,500,000"` and `2500000`
are both valid.

**Rejected** (a `Rejection` with reasons is recorded, and the row is not used):

| Check | Where |
|---|---|
| Wrong number of fields (e.g. an unquoted `2,500,000`) | `read_rows` |
| Missing value in any column (blank cells are read as missing) | `Cashflow` validators |
| ID not a positive integer | `Cashflow` |
| Unreadable date | `_parse_date` |
| Unknown cashflow type | `_parse_type` |
| Currency not in `KNOWN_CURRENCIES` (e.g. `GPB`, not corrected to `GBP`: changing a currency is a business-data change) | `_check_currency` |
| Amount not a number, or NaN or infinity | `_clean_amount` and Pydantic's `Decimal` parsing |
| Wrong sign or zero: Investment must be negative, other types positive, on both amounts | `_check_sign` |
| Duplicate ID: **every** row sharing it is rejected | `_reject_duplicate_ids` |
| More than one base currency in a fund: **every** row of that fund is rejected | `_reject_inconsistent_base_currency` |

Fixes are reported only for rows that end up valid. A fix on a row that is later rejected
by a cross-row check is dropped.

**Flagged** (results are computed, but marked incomplete):

- Analytics run on valid rows only.
- Every `IrrResult`, `NavSchedule` and `HedgePlan` of a fund carries that fund's
  `rejected_row_ids`.
  If a rejected row's fund name can't be read, the row flags every fund.
- If an IRR can't be computed (no negative or no positive cashflow, or no root between
  −99.99% and +1,000%), `irr` is `None`, `error` says why, and the other results still
  compute. The matching `HedgePlan` has no trades and the same `error`.

**File-level failures** stop the run: a missing file (the CLI exits with code 1) or a
missing expected column (`read_rows` raises).

On the sample file the result is 126 rows: 125 valid, 1 rejected (row 17, `GPB`) and
2 fixes (rows 21 and 51, dates). All four Fund I IRR results, its three NAV schedules
and its two hedge plans are flagged with row 17.

### 2.5 Idempotency

The code reads the CSV and prints a report. It writes nothing, so running it again has no
side effects. Running it twice on the same file gives the same output:

- Validation and analytics depend only on the file's contents. They don't use the
  current time or randomness.
- Rows are processed in file order, and results are sorted by fund and then by currency.
- IRR is solved by bisection with fixed bounds, tolerance and iteration limit, so the
  same cashflows always give the same rate.
- Hedge roll dates are computed from the first cashflow date, not from the clock.
- `Cashflow`, `Fix`, `Rejection`, `IrrResult`, `NavSchedule`, `HedgeTrade` and
  `HedgePlan` are immutable once created.

Idempotency for stored data or repeated uploads is not covered, because nothing is
stored.

### 2.6 Analytics method

- **IRR** (`xirr`): an annual rate on actual dates with a 365-day year, the Excel XIRR
  convention. It is solved by bisection between −99.99% and +1,000%.
  - **Currency-level:** per (fund, local currency), on `amount_local`.
  - **Fund-level:** per fund, on `amount_base` across all its currencies.
- **NAV** (`nav_schedule`): one point on each cashflow date *t*.
  NAV(t) = NPV at *t* of all cashflows dated **on or after** *t*, discounted at that
  currency's IRR. The cashflow on *t* counts as remaining, so NAV(t) is the value
  just before that day's payment.
- **Sanity checks** (`passes_sanity_checks`): NAV on the first date is 0, and NAV on the
  last date equals the exit value (the sum of the cashflows on that date), each within
  0.01. Discounting at the IRR of the same cashflows makes both hold by
  construction, so a failure points to a bug in the code, not to bad data. All six
  schedules in the sample file pass.

### 2.7 Hedge method

- **Which exposures:** each (fund, local currency) whose currency differs from the fund's
  base currency. In the sample: GBP and USD in both funds; EUR is the base currency.
- **Roll dates** (`roll_dates`, `add_months`): the first cashflow date, then every 3
  calendar months, until the last cashflow date. A month-end date stays a month-end
  (30/09 → 31/12 → 31/03 → 30/06), and a day that doesn't exist in a shorter month is
  moved to that month's last day. If a period would run past the last cashflow date, it
  ends on that date.
- **One forward per period:** trade date = start of the period, value date = end.
- **Notional:** 100% (`HEDGE_RATIO`) of the exposure on the trade date, where
  exposure = NPV at the trade date of the cashflows dated **strictly after** it,
  discounted at the currency's IRR. This is the value just after that day's cashflow.
  `NavSchedule` values can't be used directly: NAV(t) counts the cashflow on *t*, so
  NAV(0) = 0 and the investment date, when the exposure is largest, would get no hedge.
  The notional is rounded to cents (`NOTIONAL_UNIT`) for every currency, so a currency
  without a minor unit, such as JPY, still shows `.00`.
- **Direction:** a positive exposure sells the local currency and buys the base currency;
  a negative one does the reverse. An exposure below 0.01 (`MIN_NOTIONAL`) gives no trade.
- **Rate:** none. The data has no market rates.

On the sample file each plan has 20 forwards, from 30/09/2025 to 30/09/2030. The first
forward of each plan hedges the full investment (e.g. Fund I: sell 100,000,000 GBP and
200,000,000 USD for EUR).

---

## Part 4: Trade-offs made in the code

**Data validation**

| Choice | Alternative | Why | Cost |
|---|---|---|---|
| **Fix** formatting noise (spaces, stray characters, date variants) and log each fix | Reject anything not perfectly formatted | Formatting isn't business data; rejecting it would lose good cashflows | A cleaning rule could hide a real problem; mitigated by logging every fix |
| **Reject** anything ambiguous, including `GPB` | Auto-correct likely typos | Never guess financial data | Fund I loses one GBP coupon, so its results are incomplete |
| **Compute on valid rows and flag** the results (IRR, NAV and hedges) | Block every result touched by a rejected row | Delivers all results while making the gap visible | Flagged numbers are slightly wrong; Fund I's GBP hedges are sized on understated exposure |
| A rejected row **flags every result of its fund** | Flag only the matching currency (GBP) | Simple, and consistent with not guessing what `GPB` meant | Over-flags: Fund I's EUR and USD results are flagged though they're probably fine |

**Analytics**

| Choice | Alternative | Why | Cost |
|---|---|---|---|
| IRR on **actual dates / 365** | Equal quarterly periods | Standard (Excel XIRR); copes with uneven dates (quarters here are 90–92 days) | Harder to verify by hand |
| Currency IRR on **local** amounts; fund IRR on **base-currency** amounts | Everything in base currency | The local IRR is the asset's own return, free of FX | Results are in two currencies; the reader must know which is which |
| **Decimal** in the data model, **floats** inside the maths | Decimal everywhere, or float everywhere | Exact amounts in the validated data; root-finding needs floats; money outputs (exit value, hedge notional) go back to `Decimal` | A conversion step, and sub-cent noise in NAVs, hence the 0.01 tolerance |

**Hedging**

| Choice | Alternative | Why | Cost |
|---|---|---|---|
| Hedge the exposure **after** that day's cashflow | Hedge NAV(t) as scheduled | NAV(0) = 0 would leave the investment date unhedged | Two related numbers per date (NAV and exposure) that differ by that day's cashflow |
| Exposure **discounted at the currency's IRR** | Discount at a market rate | The only rate the code has; consistent with the NAV schedule | The notional is a model value, not a market value |
| **No forward rate**; notional only | Use the file's FX rate, or derive forwards from interest rates | The data has no market rates, so any rate would be made up | No base-currency amount is shown for the hedges |
| Each run recommends **every forward from scratch** | Net against existing trades | The code holds no trade records | Can't be used as-is to adjust an existing hedge book |