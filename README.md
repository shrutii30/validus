# Fund-Level Risk Analytics: Validus Case Study

A Python module that ingests projected deal cashflows, validates and cleans them with
Pydantic, computes **IRR** (per currency and per fund) and a **NAV schedule** per
currency for each fund, and recommends **FX hedges**: 3-month rolling FX forwards at 100%
of each non-base-currency exposure.

---

## Quick start

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                                   # install Python 3.11 + dependencies
uv run python -m fund_analytics data/CST_Case_Study_data.csv
uv run pytest                                             # 81 tests
```

The CSV path is a required argument, so the tool runs on any file with the same columns.

Or with `make`:

```bash
make install     # uv sync
make run         # report on the sample data (DATA=path to override)
make check       # ruff lint + format check, mypy --strict, pytest
make format      # auto-fix lint issues and format
```

---

## Approach

```
CSV ──► loader.py ──► models.py ──► valid rows ──► analytics.py ──► hedging.py ──► report
        (read rows,   (Pydantic:     + fixes          (IRR, NAV       (3-month
         cross-row     clean or      + rejections      schedules)      FX forwards)
         checks)       reject)                             └─ valuation.py (NPV, IRR, NAV)
```

1. **Load** (`loader.py`): reads the CSV with Python's `csv` module. Blank cells become
   missing values. Amounts are accepted with or without thousands separators
   (`"2,500,000"` or `2500000`). Only a number with commas *and* no quotes
   (`2,500,000`) is rejected, because the commas split it into extra CSV fields and the
   row no longer has the expected number of columns.
2. **Validate and clean** (`models.py`): one Pydantic `Cashflow` model per row.
   - **Fix** unambiguous formatting noise (stray spaces and characters, date-format
     variants, case) and **log every fix**.
   - **Reject** anything that would require guessing business data (unknown currency,
     unreadable date, non-numeric amount, wrong sign for the cashflow type, missing value),
     **with a reason**.
   - Cross-row checks in the loader: unique IDs, one base currency per fund.
3. **IRR** (`valuation.py`): annual rate on actual dates with a 365-day year (the Excel XIRR
   convention), solved by bisection.
   - **Currency-level**: per (fund, currency) on local-currency amounts.
   - **Fund-level**: per fund on base-currency (EUR) amounts.
4. **NAV schedule** (`valuation.py`): on each cashflow date *t*,
   NAV(t) = NPV at *t* of all cashflows dated **on or after** *t*, discounted at that
   currency's IRR. Counting the cashflow on *t* itself is what makes the brief's checks
   hold: NAV(0) = 0 and final NAV = exit value. Both are checked at runtime.
5. **FX hedges** (`hedging.py`): for each currency that differs from the fund's base
   currency, one FX forward per 3-month period from the first to the last cashflow date
   (month-ends stay month-ends: 30/09 → 31/12 → 31/03 ...). Each forward sells the local
   currency for the base currency, with a notional of 100% of the exposure on its trade
   date. The exposure is the NPV of the cashflows dated **after** that date, discounted at
   the currency's IRR. NAV(t) can't be used directly: it counts that day's cashflow, so
   NAV(0) = 0 and the investment date would get no hedge. No forward rate is given,
   because the data has no market rates.
6. **Data-quality flags**: analytics and hedges run on valid rows only, and every result
   lists its fund's rejected rows, so incomplete results are impossible to miss.

Amounts are stored as `Decimal` and converted to float only inside the maths.

---

## Data issues found

| Row ID | Column | Raw value | Handling |
|--------|--------|-----------|----------|
| 17 | Local Currency | `GPB` | **Rejected**: unknown currency. Not auto-corrected to `GBP`, since changing a currency is a business-data change the client must confirm |
| 21 | Date | `" 30/09/2030  00:00:00"` | **Fixed** and logged: extra spaces, seconds |
| 51 | Date | ``"30/09/2027  00:00:00`"`` | **Fixed** and logged: extra spaces, seconds, trailing backtick |
| 27 | Cashflow Amount Local | `3000000` | **Accepted**: no thousands separators, unlike every other amount (`"3,000,000"`) |
| 51 | Cashflow Amount Local | `6000000` | **Accepted**: same as row 27 |

Thousands separators are a normal number format, so they are parsed silently rather than
logged (otherwise 250 of 252 amounts would appear as "fixes").

---

## Results

```
CST_Case_Study_data.csv: 126 rows, 125 valid, 1 rejected, 2 fixes
```

**IRR** (actual dates, 365-day year):

| Fund | EUR | GBP | USD | Fund level (EUR) |
|------|-----|-----|-----|------------------|
| Fund I ⚠ | 7.8870% | 9.4771% | 12.0515% | 9.9233% |
| Fund II | 7.8870% | 9.9507% | 12.0515% | 10.0476% |

⚠ All Fund I results are flagged *incomplete*: rejected row 17 belongs to Fund I, and
flags are set per fund, not per currency. The effect is
visible: Fund I GBP (9.48%) is lower than the otherwise identical Fund II GBP (9.95%)
because one coupon is missing.

**NAV schedules**: 6 schedules (2 funds × 3 currencies). All pass both sanity checks.
Fund I GBP has 20 points instead of 21 (no 30/09/2029, row 17's date), and its NAV dips
below par before that gap: a concrete example of how one bad row distorts the numbers.

IRRs sit slightly below the simple coupon rates (e.g. EUR 7.89% vs 2% × 4 quarters
compounded = 8.24%) because each loan pays 19 coupons, not 20: there is no interest in
the final quarter.

**FX hedges**: 4 plans (Fund I and Fund II, each in GBP and USD; EUR is the base currency,
so EUR deals need none), each with 20 forwards from 30/09/2025 to 30/09/2030. The first
forward of each plan hedges the full investment:

| Fund | Sell GBP for EUR | Sell USD for EUR |
|------|------------------|------------------|
| Fund I ⚠ | 100,000,000.00 | 200,000,000.00 |
| Fund II | 140,000,000.00 | 280,000,000.00 |

Later notionals drift slightly below par (e.g. Fund I GBP 97.7m for the last quarter),
because the loans pay no coupon in the final quarter. Fund I's hedge plans carry the
same row-17 warning as its IRR and NAV.

---

## Key assumptions

### About the brief

| Assumption | Basis |
|---|---|
| Analytics are computed **per fund for both funds**, not only Fund I | The task says "compute risk analytics per fund"; Fund I, named in Part 3, is included |
| NAV(t) counts cashflows dated **on or after** *t*, so it is the value just before that day's cashflow is paid | The only reading under which both of the brief's checks hold: NAV(0) = 0 and final NAV = exit value |
| "NAV schedule per currency" means per (fund, local currency), in local currency, discounted at that currency's IRR. There is no fund-level NAV | Wording of the brief |
| IRR is an annual rate on actual dates with a 365-day year (the Excel XIRR convention) | Standard in private credit; the quarters in the data are 90–92 days long |
| Hedges are 3-month rolling FX forwards at 100% of exposure, one per 3-month period from the first to the last cashflow date | As requested; a month-end start keeps month-end roll dates, which matches the sample's quarter-end cashflow dates |
| The exposure hedged on a date is the value **after** that day's cashflow (NPV of later cashflows at the currency's IRR) | NAV(t) counts that day's cashflow, so NAV(0) = 0 would give no hedge on the investment date |
| No forward rates are produced | The data has no market rates; the rate is left to execution |
| Deals in the fund's base currency are not hedged | They carry no FX risk |
| The input is a CSV file | As the brief states |

### About the data

| Assumption | Basis |
|---|---|
| Dates are **DD/MM/YYYY**, not MM/DD/YYYY | Every day value is 30 or 31, which can't be a month |
| The time part of a date carries no meaning and is dropped | Every row is `00:00` or `00:00:00` |
| `GPB` is an error, but it is **not** assumed to mean `GBP` | Changing a currency is a business-data change the client must confirm |
| Investment is negative; Interest and Principal Repayment are positive, in both local and base amounts | True for every row in the sample; enforced as a rule |
| Each fund has exactly one base currency | True in the sample (EUR); enforced as a rule |
| Each (fund, local currency) pair is one deal | The CSV has no Deal column, and each pair has exactly one Investment and one Principal Repayment |
| Base amounts were converted at **one fixed FX rate per currency** (GBP→EUR 1.14573786, USD→EUR 0.85106383) | Every row's base/local ratio matches its currency's rate, up to rounding to whole units. So the fund-level IRR contains no FX movement: it is the return if FX stays at that rate |
| No interest is paid in the final quarter (only principal on 30/09/2030) | All six loans have 19 coupons, not 20. Treated as intended, not as missing data. This is why the IRRs sit slightly below the compounded coupon rates (e.g. EUR 7.89% vs 8.24%) |
| Fund names are matched exactly after removing extra spaces, so `Fund I` ≠ `fund i` | Changing a fund name's case would be a guess about which fund it is |
| Currencies are limited to 13 ISO 4217 codes: USD, EUR, GBP, JPY, CHF, CAD, AUD, NZD, SEK, NOK, DKK, SGD, HKD | Covers the sample and common private-credit currencies. Any other code is rejected; to support one, add it to `KNOWN_CURRENCIES` in `models.py` |
| The file is UTF-8 (a byte-order mark from Excel is accepted) | The sample is plain UTF-8 |

---

## Production Considerations

- In a live platform, quarantined rows would be routed to a **staging table and an
  exception-review UI**, and hedge generation for the affected fund/currency would be
  **held until resolved**, rather than computing with warnings as this module does. This
  avoids acting on understated exposure (un-hedged risk).

---

## Project layout

```
src/fund_analytics/
  models.py      Pydantic Cashflow model: per-field cleaning and validation
  loader.py      CSV reading, cross-row checks, fixes and rejections
  valuation.py   NPV, IRR (XIRR convention) and NAV schedule
  analytics.py   Per-fund IRR and NAV results with data-quality flags
  hedging.py     FX hedge recommendations: 3-month rolling forwards at 100% of exposure
  __main__.py    Command-line report
tests/           81 pytest tests
data/            Sample cashflow CSV
docs/            Design document, trade-offs and assumptions
```
