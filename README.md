# D1 — European Election Abstention Diagnostic Prototype

A local Streamlit prototype for reviewing possible barriers in two cases: a fictional synthetic demonstration and an explicitly curated real-evidence example. Its outputs are hypotheses for a facilitator, not findings about real voters, individuals, or causes.

## Setup and offline run

From the repository root:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The sidebar has two independent selectors:

- **Case:** `Synthetic demonstration` or `Curated real evidence`.
- **Run mode:** `mock` or `live`.

The default is mock mode, which works offline and needs no API key. Choosing the curated case does not enable live mode; the case and run mode are selected independently. The curated case is a manually prepared, bounded structured summary from two published European Parliament reports: a 2009 post-electoral survey and 2012 abstention focus groups. The raw PDFs and broader archive remain local and ignored; the app does not ingest or send those files.

Run the offline tests with:

```sh
python -m pytest -q
```

## Optional live mode

Live mode is an explicit selection in the app and requires `LIQUID_API_KEY`. `D1_MODEL` is optional; the adapter defaults to `d1:free`.

```sh
export LIQUID_API_KEY='your-key'
# Optional:
export D1_MODEL='d1:free'
streamlit run app.py
```

You can instead keep these variables in an ignored local `.env` file and load them into the shell before launching. The app reads process environment variables; it does not load `.env` itself. For a POSIX shell:

```sh
set -a
. ./.env
set +a
streamlit run app.py
```

The `typesafe-sdk` / `TypeSafeClient` `system_one` setup follows Liquid's official Decision Models documentation for `https://api.liquid.ai`. A configured live API/model call has not yet been smoke-tested. Live failures remain errors and never fall back to mock output. `.env.example` is intentionally absent; never commit credentials.

## What the prototype shows

It evaluates six independent, potentially co-existing hypotheses: **perception gap**, **values conflict**, **response-efficacy gap**, **collective-efficacy gap**, **structural/capability barrier**, and **insufficient evidence**. Probabilities are independent and do not sum to one.

Focus-group themes and aggregate survey evidence are shown separately. Focus-group themes are exploratory and do not estimate prevalence. In the synthetic fixture, survey counts use the fixture's valid-response denominator and item-missing responses remain separate. The curated survey record instead preserves rounded, published multi-select percentages for non-voters (a base reported as 57% of the total sample). Up to three responses were allowed, so percentages need not sum to 100%; the source facts used here provide no respondent count, and none is invented.

Local triage statuses are **leading** (one hypothesis crosses the illustrative high threshold), **mixed** (multiple do), **possible** (one or more cross the low threshold), **insufficient** (evidence is inadequate), **unsupported** (none crosses the low threshold; this does not establish absence), and **unavailable** (no valid result). Optional live **Score** and **Choice** outputs may also be shown; Choice is only a suggested diagnostic probe. Human review can remain pending or be marked confirmed, corrected, or rejected, with a reason for completed decisions. Review state is held in the Streamlit session only.

## Data and limits

The app loads the fictional fixture in `data/synthetic_cases.json` or the manually curated structured case in `data/curated_cases.json`. Local published PDFs and archive files under `data/external/` remain ignored and are excluded from the app and fixtures. The curated record contains paraphrased qualitative themes and an aggregate survey distribution with provenance and limitations; it is not raw report text, a respondent-level dataset, or a merged participant sample.

Do not enter raw transcripts or recordings, respondent-level rows, personal or confidential data, or information for individual profiling. The prototype has no persistent storage and makes no causal claims. Triage thresholds are illustrative and unvalidated; neither synthetic examples nor the curated aggregates establish real-world prevalence, causes, or model accuracy. Outputs are hypotheses for human review, not causes or judgments about individuals.

See [D1.md](D1.md) for the design plan and [data/README.md](data/README.md) for source provenance and limitations.
