# Data Sources

## Overview

This application uses six real government datasets from two agencies: **data.gov.sg**
(Singapore's open data portal) and **MOM** (Ministry of Manpower). All datasets are
public, aggregate-level statistics — no individual-level records, no PII (see
[Privacy](#privacy) below).

Extraction is **file-based by default, with a per-dataset opt-in to live API queries**
(see [Extraction mode](#extraction-mode-file-vs-api) below) — not the older "always
download files" design some earlier planning notes describe. The authoritative catalog
of what's actually loaded, and how, is `backend/data/manifest.yaml`; this document
explains and narrates that catalog.

## Datasets

### From data.gov.sg

| # | Title | Dataset ID | Mode | Local file |
|---|---|---|---|---|
| 1 | Number of Retrenched Employees by Industry and Occupational Group | `d_6d1fcbd205b908c27c174db08432346a` | file | `backend/data/incoming/data_gov_sg/NumberofRetrenchedEmployeesbyIndustryandOccupationAnnual.csv` |
| 2 | Number of Job Vacancy by Industry and Occupation - Annual | `d_889d11a2b0a53b235abb64e3f4e0a47b` | **api** (file fallback) | `backend/data/incoming/data_gov_sg/NumberofJobVacancybyIndustryandOccupationAnnual.csv` |
| 3 | Graduate Employment Survey - NTU, NUS, SIT, SMU, SUSS & SUTD | `d_3c55210de27fcccda2ed0c63fdd2b352` | file | `backend/data/incoming/data_gov_sg/GraduateEmploymentSurveyNTUNUSSITSMUSUSSSUTD.csv` |

Source pages:
- https://data.gov.sg/datasets/d_6d1fcbd205b908c27c174db08432346a/view
- https://data.gov.sg/datasets/d_889d11a2b0a53b235abb64e3f4e0a47b/view
- https://data.gov.sg/datasets/d_3c55210de27fcccda2ed0c63fdd2b352/view

All three are CSV, obtained via data.gov.sg's Datastore Search API
(`GET https://data.gov.sg/api/action/datastore_search?resource_id=<id>`), which is free
and requires no authentication.

### From MOM (Ministry of Manpower)

| # | Title | Year | Sheet used | Local file |
|---|---|---|---|---|
| 4 | Usual Hours Worked, by Occupation and Sex | 2023 | `F2` | `backend/data/incoming/mom/LFR2023_SectionF.xlsx` |
| 5 | Usual Hours Worked, by Occupation and Sex | 2024 | `F2` | `backend/data/incoming/mom/LFR2024_SectionF.xlsx` |
| 6 | Usual Hours Worked, by Occupation and Sex | 2025 | `F2` | `backend/data/incoming/mom/LFR2025_SectionF.xlsx` |

Source pages (direct `.xlsx` downloads, no API):
- https://stats.mom.gov.sg/iMAS_Tables1/LabourForce/LabourForce_2023/LFR2023_SectionF.xlsx
- https://stats.mom.gov.sg/iMAS_Tables1/LabourForce/LabourForce_2024/LFR2024_SectionF.xlsx
- https://stats.mom.gov.sg/iMAS_Tables1/LabourForce/LabourForce_2025/LFR2025_SectionF.xlsx

**A 2022 edition of this dataset was deliberately excluded.** That file
(`LFR2022_T66_78.xlsx`) uses a different table-numbering scheme (`T66`-`T78` instead of
`F1`-`F13` used in 2023-2025) for the same 13 tables in the same order, and its title
strings carry a "(JUNE 2022)" point-in-time qualifier the later years don't. Rather than
special-case one year's naming/methodology divergence, it was dropped entirely — 2023,
2024, and 2025 are structurally identical to each other and were cross-verified to have
consistent overlapping figures (e.g. the 2022 column in both the 2023 and the excluded
2022 file matches). This trade cleaner, more reliable code for one year less of coverage.

**Only the `F2` sheet is loaded from each file**, not all 13 (`F1`-`F13`). Each MOM Excel
file contains 13 tables covering the same "usual hours worked" survey sliced by
different dimensions (by sex, by occupation, by industry, by age, by qualification,
etc.). `F2` ("usual hours worked, by occupation and sex") was chosen because it adds a
genuinely new analytical dimension the data.gov.sg CSVs don't have — both of those are
already sliced by industry x occupation, so an industry-focused MOM table (`F3`) would
mostly duplicate what's already available, whereas an occupation x hours-worked cut
opens new cross-dataset questions (e.g. correlating long working hours with
retrenchment/vacancy patterns in the same occupation). The other 12 sheets per file are
not currently ingested.

## Extraction mode: file vs. API

Each dataset in `backend/data/manifest.yaml` declares its own `mode`:

- **`mode: file`** (5 of 6 datasets) — the dataset is parsed once from the local file by
  a one-time seed script (`backend/scripts/seed_datasets.py`) and loaded into Postgres.
  Used for datasets with known, specific structural messiness (see
  [Data quality](#data-quality-handling) below) that benefits from deterministic,
  pre-written cleaning rules rather than being re-interpreted on every query.
- **`mode: api`** (job vacancy dataset only) — queried live, per request, against
  data.gov.sg's Datastore Search API using the dataset's `resource_id`, with `filters`
  and pagination. If the live call fails for any reason (network error, non-200,
  malformed response), the system transparently falls back to the equivalent local CSV
  file (`api_fallback: file` in the manifest) rather than failing the request — this is
  surfaced to the user as "showing cached data" rather than silently swapped.

This is a genuinely reliable, low-risk API in practice: it was live-tested directly
(not just assumed from documentation) — `filters`, pagination, and the endpoint all
behaved exactly as documented, and 13/13 test requests succeeded from a normal network,
including requests with no special headers. (An earlier test run from a different,
more restrictive network environment saw intermittent blocking, which is why the file
fallback exists as a safety net — but the API itself is not the unreliable part.)

Only this one dataset's fixed `resource_id` is ever queried live — there is no
free-text/keyword dataset search or discovery against data.gov.sg's API. That capability
was considered and deliberately rejected: data.gov.sg's `q` search parameter has
documentation that contradicts at least one independently reported real-world behavior,
and would introduce an unbounded, harder-to-verify query surface for no benefit here,
since the datasets this application uses are already known and fixed in advance.

## Data quality handling

Two sentinel values appear throughout these datasets and are handled explicitly, never
silently coerced to zero:

- **`-`** (data.gov.sg / MOM convention) marks a suppressed, negligible, or unavailable
  figure. It converts to a real missing value (`NaN`), not `0` — treating it as zero
  would understate real statistics (e.g. "no vacancies" vs. "figure withheld" are very
  different claims).
- **`na`** (Graduate Employment Survey convention, ~400 occurrences) marks the same kind
  of thing — typically a program/cohort too small to report a reliable statistic — and
  is handled the same way.

Other known, deliberately-handled issues in the source data:

- **Retrenchment dataset classification break**: the industry x occupation
  classification used in the retrenchment CSV changed partway through its 1998-2025
  span (84 rows/year in 1998-1999, 129 in 2000-2005, stabilizing at 126/year from 2006
  onward). Only years from **2006 onward** are loaded, to avoid analyzing across an
  unreconciled classification change.
- **MOM sheet footers**: every MOM sheet has a multi-row footer (`Source:`, `Note:`,
  footnote text) after the actual data. Parsing stops at the first fully blank row,
  which reliably separates data from footer in every sheet checked.
- **Graduate Employment Survey degree-name footnote markers**: degree names carry
  inconsistently formatted footnote markers (`**`, `#`, and combinations, with
  inconsistent spacing/ordering). These are stripped before `degree` is used as a
  grouping or join key, so the same program doesn't fragment into multiple
  apparently-distinct categories.

## Privacy

All six datasets are public, aggregate-level government statistics — industry,
occupation, university, or cohort-level figures, not individual records. No dataset
loaded by this application contains names, identifiers, addresses, or any other
row-level personal data. No PII is expected to flow through this pipeline as a result.

A production system extending beyond these six aggregate datasets would need additional
controls (row-level access controls, data classification tagging, PII scanning on
ingest) that this build intentionally does not implement — see the Innovation
Assessment write-up for further discussion.

## Multi-cloud LLM setup dependency

Unrelated to the datasets above, but documented here per the spec's data-sources
guidance: using the AWS Bedrock LLM provider (optional; OpenAI alone is sufficient for
local development) requires an AWS account, Bedrock model-access approval for the
chosen model, and IAM credentials with `bedrock:InvokeModel` permission. This is a
setup step the user must provision themselves — see `.env.example` and
`LLM_ENABLE_BEDROCK`.

## Future work: further live API expansion

Live API extraction is already partially built (the job vacancy dataset, see above),
not merely a future idea. What remains genuinely deferred:

- **SingStat Table Builder API** live integration — not implemented. Its search-matching
  semantics (case sensitivity, substring vs. exact matching) could not be confirmed from
  any available documentation, and this was not independently verified before deciding
  to defer it. Before building this, that behavior should be confirmed via direct calls,
  not assumed.
- **Additional data.gov.sg datasets in `api` mode** — the retrenchment and graduate
  survey datasets currently stay in `file` mode by design (their known data-quality
  issues benefit from deterministic pre-cleaning), but nothing prevents adding more
  `api`-mode entries for other pre-vetted `resource_id`s if a need arises.
- **Free-text/dynamic dataset discovery** — deliberately out of scope; see
  [Extraction mode](#extraction-mode-file-vs-api) above.
