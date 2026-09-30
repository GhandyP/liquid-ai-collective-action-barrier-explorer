# D1 — Synthetic European Election Abstention Demo

A local Streamlit prototype for reviewing possible barriers in one fictional case. Its outputs are hypotheses for a facilitator, not findings about real voters, individuals, or causes.

## Setup and offline run

From the repository root:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The app defaults to **mock** mode and uses its bundled synthetic fixture. This path works offline and needs no API key. Run the offline tests with:

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

The implementation assumes the `typesafe-sdk` / `TypeSafeClient` `system_one` contract at `https://api.liquid.ai`. SDK compatibility, that contract, and model availability remain unverified until a configured live smoke test succeeds. Live failures remain errors and never fall back to mock output. `.env.example` is intentionally absent; never commit credentials.

## What the prototype shows

It evaluates six independent, potentially co-existing hypotheses: **perception gap**, **values conflict**, **response-efficacy gap**, **collective-efficacy gap**, **structural/capability barrier**, and **insufficient evidence**. Probabilities are independent and do not sum to one.

Focus-group themes and aggregate survey evidence are shown separately. Focus-group themes do not estimate prevalence. Survey counts are shown over the valid-response denominator; item-missing responses remain separate, and fixture validation checks response counts against that denominator.

Local triage statuses are **leading** (one hypothesis crosses the illustrative high threshold), **mixed** (multiple do), **possible** (one or more cross the low threshold), **insufficient** (evidence is inadequate), **unsupported** (none crosses the low threshold; this does not establish absence), and **unavailable** (no valid result). Optional live **Score** and **Choice** outputs may also be shown; Choice is only a suggested diagnostic probe. Human review can remain pending or be marked confirmed, corrected, or rejected, with a reason for completed decisions. Review state is held in the Streamlit session only.

## Data and limits

The app loads only the fictional fixture in `data/synthetic_cases.json`. Local PDFs under `data/external/` are ignored and excluded from the app and fixtures. The prototype is limited to synthetic cases and summarized focus-group themes plus aggregate survey evidence: do not enter raw transcripts or recordings, respondent-level rows, personal or confidential data, or information for individual profiling. It has no persistent storage and makes no causal claims. Triage thresholds are illustrative and unvalidated; neither synthetic examples nor outputs establish real-world prevalence, causes, or model accuracy.

See [D1.md](D1.md) for the design plan and [data/README.md](data/README.md) for source provenance and limitations.
