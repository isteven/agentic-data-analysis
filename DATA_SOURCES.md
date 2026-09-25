# Data Sources

## Overview

Six files from two government sources: **data.gov.sg** (Singapore's open data portal)
and **MOM** (Ministry of Manpower). All are public, aggregate statistics with no
personal data (see [Privacy](#privacy)).

**The files in `backend/data/incoming/` are mock data.** They started as real public
downloads and were then curated: data.gov.sg examples swapped for new ones, MOM
workbooks trimmed to the single sheet used. They aren't byte-identical to what the
source sites serve today.

`backend/data/manifest.yaml` is the catalog of what gets loaded. Entries carry
**metadata only** (source, title, file, format, topics). How values relate to each
other and which rows are safe to add up isn't written per dataset; it's inferred from
the numbers at ingest (see [How the data is understood](#how-the-data-is-understood)).

## Datasets

### From data.gov.sg

| Manifest id | Contents | Coverage | Local file |
|---|---|---|---|
| `retrenchment_by_residential_status` | Retrenchments (total / resident / non-resident) and incidence per 1,000 employees | 2007-2025, one row per year | `data_gov_sg/NumberandIncidenceofRetrenchmentbyResidentialStatusAnnual.csv` |
| `mrt_to_junior_college_travel` | Travel time (minutes) and distance (km) from each of 189 MRT/LRT stations to each of 18 junior colleges / Millennia Institute | No time dimension: a complete 189 x 18 matrix | `data_gov_sg/TravellingDistancebetweenMRTLRTStationtoJuniorCollegesMillenniaInstitute.csv` |
| `graduate_employment_survey` | Employment rates and salaries by university, school and degree | 2013-2024 | `data_gov_sg/GraduateEmploymentSurveyNTUNUSSITSMUSUSSSUTD.csv` |

The travel-time file is deliberately unlike the others: no year column and no measure
that makes sense to add up. It checks that nothing in the pipeline assumes every
dataset is a yearly time series.

### From MOM (Ministry of Manpower)

| Manifest id | Contents | Year | Local file |
|---|---|---|---|
| `mom_usual_hours_by_occupation_2023` | Employed residents (thousands) by sex, usual hours worked and occupation | 2023 | `mom/LFR2023_SectionF.xlsx` |
| `mom_usual_hours_by_occupation_2024` | same | 2024 | `mom/LFR2024_SectionF.xlsx` |
| `mom_usual_hours_by_occupation_2025` | same | 2025 | `mom/LFR2025_SectionF.xlsx` |

Originals: `https://stats.mom.gov.sg/iMAS_Tables1/LabourForce/LabourForce_<year>/LFR<year>_SectionF.xlsx`.
The published workbooks hold 13 tables (`F1`-`F13`); the local copies keep only `F2`,
the one loaded. The three files share a manifest `group`, so they become one combined
view with a `year` column (taken from the manifest, since the sheet has none).

### Formats

CSV (data.gov.sg) and Excel (MOM). The data.gov.sg live API client
(`backend/app/data/api_client.py`: Datastore Search, pagination, retry with timeout,
fallback to the local file) is built, but **no current dataset uses `mode: api`**:
the one that did (job vacancy by industry) was removed in the dataset swap.

## How the data is understood

Nothing about a specific dataset is hardcoded on the query path. At ingest the seed
script parses each file, then the profiler (`backend/app/data/profiler.py`) and
structure inference (`backend/app/data/structure.py`) work out, from the values alone:

| Question | How it's answered | Example in this data |
|---|---|---|
| What is each column? | Text → dimension; whole numbers within 1900-2100 → time; a number that pairs 1:1 with a text column (a code for a name) → dimension; other numbers → measure | Postal codes are dimensions, not measures |
| Which values are totals of others? | A value equal to the sum of other values in every cell (within 3 rounding units, at least 5 cells) is their parent; one that is also ≥ every other value is a grand total | MOM `Total` rows in `sex`, `hours_bucket`, `occupation` |
| Which values overlap? | Values outside a grand total's breakdown | MOM `More Than 48 Hours` overlaps the 45-49 … 60+ buckets |
| Parallel classifications? | Two separate groups of values with equal sums; the group covering fewer cells is dropped | (none in the current files) |
| Classification changes over time? | A new era starts when a column's set of values changes; an era whose relations don't form a clean tree is marked unverified | (none in the current files) |
| Can a measure be summed? | Only if some column proves it (a parent equals the sum of its parts); otherwise non-additive | MOM `value` additive; rates, means, medians, travel times not |

The results are stored in each dataset's `schema_profile`. The typed views in the
`data` schema use them to expose only rows that are safe to add up: lowest-level
values only, with `<column>_level_N` parent columns when there is a hierarchy.

Checked against published figures: the MOM view adds up to 2312.0 / 2325.4 / 2339.8
thousand for 2023-2025 against published totals of 2312.2 / 2326.1 / 2339.6. The small
gap is rounding in the individual cells plus a few suppressed ones.

## Data quality

Handled:

- **Missing-value markers** (`-`, `na`, `N.A.` and similar) become missing, never 0.
  Treating "figure withheld" as zero would understate the statistics. The graduate
  survey alone has 768 `na` cells.
- **Leading-zero codes** (e.g. postal code `039193`) are kept as text; reading them as
  numbers turns them into different, invalid codes. 342 station codes are affected.
- **MOM sheet footers**: parsing stops at the first fully blank row, before the
  `Source:` / `Note:` block.

Known, not yet handled:

- **Graduate survey degree names carry footnote markers** (`**`, `#`) in 181 rows, so
  one programme can appear under more than one name.
- **Totals stored as separate columns** (`retrench_total` next to `retrench_resident`
  and `retrench_non_resident`) aren't recognised yet: structure inference compares
  values within a column, not across columns. Those measures are treated as
  non-additive for now. Resident + non-resident differs from the total by ±10 in 6 of
  19 years, from rounding.
- **Rounding adds up**: sums over lowest-level rows can differ slightly from a published
  total (see above).

## Privacy

All datasets are public, aggregate statistics: no names, identifiers or row-level
personal data. Postal codes identify public stations and schools, not people.

A production system handling non-public data would need further controls (access
control, data classification, PII scanning at ingest); see the Innovation Assessment.

## LLM provider setup

Not a dataset, but a setup dependency: the AWS Bedrock provider (optional; OpenAI alone
is enough for local development) needs an AWS account, Bedrock model-access approval
for the chosen model, and IAM credentials with `bedrock:InvokeModel`. See
`backend/.env.example`.
