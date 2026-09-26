# Innovation Assessment

*How I would evolve the platform to serve policy researchers in secure government environments.*

The platform rests on one rule: **LLMs decide what to compute, the database computes, and code checks the result.** No number in a report is ever typed by a model. Every proposal below keeps that rule, and each one starts from something observed or measured while building this version.

## 1. Trust: show your working, and ask instead of guessing

**What I saw.** The number validator guarantees the report matches the query result. It cannot tell whether the result answers the question. In 9 of 10 stored runs, "Which university had the highest graduate employment rate?" was answered from a single degree's 100% rate: plausible, grounded, and wrong. The reviewer agent only caught this kind of error reliably (0/3 → 3/3 in isolated tests) once the intent step wrote the method into the question ("averaged across its degrees"). Stating the method explicitly worked better than any amount of prompt wording.

**Proposals.**
- **An answer receipt on every report:** the agreed reading of the question, the SQL, the datasets with their file hashes, what one row of each view is, and the result of each check (numbers verified, reviewer verdict). The receipt is stored immutably and exportable with the report, so a researcher can defend a figure in a briefing.
- **Clarify, don't guess.** Today the intent step picks one reading of an ambiguous question. Instead, it should ask when two readings give different numbers (e.g. "share of women working 60+ hours": out of all women, or out of all 60+ hour workers?). The researcher's choice becomes the agreed reading that the planner and reviewer both work from.
- **Every mistake becomes a regression test.** Each wrong answer found in review was added to the LLM eval suite, which now passes 24/24. Make this routine: a "flag this answer" button creates an eval case, and the suite runs before any model or prompt change goes live.

## 2. Agents that adapt to messy, changing data

**What I saw.** Nothing in the query path knows dataset or column names. Structure (totals, hierarchies, classification breaks) is inferred from the numbers at ingest, and a new file needs no code. The weak spots are where models are inconsistent. "The last five years" resolved to 2019–2023 in one run and 2019–2024 in another. The intent step once declined "How many worked 60+ hours?" because it couldn't see that a `60 Hours & Over` band existed.

**Proposals.**
- **Move deterministic decisions out of the model.** Resolve relative time in code, from each dataset's coverage. The model should only mark that a range is relative.
- **A semantic catalog.** Listing column values in the prompt fixed the false refusal, but it won't scale to hundreds of datasets. Embed dataset descriptions, column meanings and dimension values in a vector index. The coordinator then retrieves candidates instead of reading the whole catalog.
- **Data contracts and drift detection at ingest.** Compare each new file's profile with the previous one: renamed columns, new classification schemes (SSIC/SSOC revisions), changed sheet layouts (already a recurring issue with MOM files). Quarantine a changed era, with a note to the data owner, rather than mixing it silently. The API client already falls back to a cached file; add schema snapshots, so a changed API is detected rather than just failing.
- **Reuse verified work.** Cache the verified SQL keyed by the agreed reading, so the same question gets the same answer in seconds without new LLM calls.

## 3. Security and compliance for government use

**What exists.** Planner SQL runs read-only, as a role that can see only the generated views, after a gate that allows only single `SELECT`s. Questions are rate-limited per client. Secrets live in per-service environment files. All data is public and aggregate. But every question and schema still leaves the environment for OpenAI or Bedrock.

**Proposals.**
- **Deploy on the Government on Commercial Cloud (GCC)**, with Bedrock reached in-region over VPC endpoints and no internet egress. The provider factory already supports this; it's a configuration choice.
- **Classification-aware routing.** Tag each dataset in the manifest (e.g. Official (Open) vs Restricted). Restricted data only ever goes to in-region or self-hosted models, and suppression of small cells (as MOM does with `-`) is enforced by the SQL gate, not left to the prompt.
- **Identity and audit:** SSO with role-based access per dataset, and an append-only audit log of every question, SQL statement and dataset touched. The answer receipt from section 1 is most of that record already.
- **Prompt-injection containment.** Dataset values now appear in prompts. The blast radius is small, because the model's only action is a gated, read-only `SELECT`. Treat data values strictly as quoted data, and keep tools this narrow as new ones are added.

## 4. Scale, resilience and cost

**What I measured** (load test with a mocked LLM):
- **Overhead:** the stack itself adds under 0.5 s per run.
- **Throughput:** it scales almost linearly with workers (3 workers: 2.9×).
- **The real limit is LLM quota:** about 12 gpt-4o calls a minute on the test account.
- **Fallback:** it works per call and appears in the trace.
- **Tokens:** exact counts per call. One finding: OpenAI served 1,024 of about 1,100 input tokens from its prompt cache on the planner's repeated steps.

**Proposals.**
- **Autoscale workers on queue depth**, and add a circuit breaker so a provider that failed with an auth or quota error is skipped for the rest of a run.
- **Spend where it earns accuracy.** The SQL planner moved to the quality tier because the fast model failed multi-step questions. The next step is escalation: start fast, and switch to quality only on a retry or a reviewer rejection, justified by eval results rather than guesswork. Reorder prompts so the stable part (schema, rules) comes first and hits the provider's cache.
- **Budgets from the token data:** per-team monthly budgets and alerts, since every call is already recorded with its model and tokens.
- **Large datasets:** materialize the generated views (JSON-backed views measured 2–7× slower than typed tables), and push filters into the data.gov.sg API where it allows.

**Observability.** Logs are already structured JSON with the `run_id` on every line, plus a readiness check. In production, feed them to Loki/Grafana, add OpenTelemetry or LangSmith tracing (environment variables only), and alert on readiness failures, error rates and token spend.

## 5. Collaboration across research teams

**Today** each chat holds one question, and History is shared by everyone using a deployment.

**Proposals.**
- **Team workspaces:** shareable analysis links that carry the answer receipt, plus comments on reports.
- **Follow-up questions with memory.** Retrieve earlier findings as structured facts, not model summaries, so "and for women only?" builds on verified numbers instead of paraphrased ones.
- **A verified-analyses library.** A senior analyst can mark an answer as verified. It then becomes a reusable template for colleagues and a regression case for the agents.
- **Briefing export:** the chart, the report and its citations, straight into the ministry's briefing template.

## Priorities

| Order | Change | Why first |
|---|---|---|
| 1 | Answer receipt; clarifying questions | Trust is what decides adoption; both build on existing agents |
| 2 | GCC deployment; classification-aware routing; SSO and audit | Required before any non-public data can be used |
| 3 | Deterministic time resolution; drift detection | Removes the most common inconsistencies at the source |
| 4 | Semantic catalog; verified-answer cache | Needed once the catalog grows past what fits in a prompt |
| 5 | Workspaces; follow-ups with memory; verified library | Turns individual answers into shared team knowledge |
