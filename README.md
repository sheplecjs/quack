# quack

> **Work in progress.** This repository showcases full-stack data engineering: ingestion, modelling, testing,
> documentation and reporting, all running locally on DuckDB.

## Stack

| Layer | Tool |
|---|---|
| Environment | [uv](https://docs.astral.sh/uv/) workspace (Python 3.14), [Task](https://taskfile.dev/) runner |
| Ingestion | [dlt](https://dlthub.com/), with pydantic-validated config, from the [Alpha Vantage](https://www.alphavantage.co/) API |
| Storage | [DuckDB](https://duckdb.org/) |
| Transformation | [dbt](https://www.getdbt.com/) (dbt-duckdb): staging, intermediate and mart layers with enforced contracts |
| Reporting | [dbt charts](https://dbtcharts.com/) (`dct`) boards, exported as static HTML; [marimo](https://marimo.io/) notebooks for exploration |
| Quality | ruff, ty, pytest, yamllint, detect-secrets; dbt data and unit tests |
| Packaging | Docker, per project |

## Repository structure

```
quack/
├── projects/
│   └── financial/              # Market and macroeconomic data project
│       ├── src/financial/      # dlt source and pipeline (financial-load CLI)
│       ├── src/notebooks/      # marimo notebooks
│       ├── tests/              # pytest suite for the pipeline
│       ├── financial_dbt/      # dbt project
│       │   ├── models/         # one folder per domain: staging/, intermediate/, marts/
│       │   ├── seeds/          # e.g. the portfolio holdings
│       │   ├── tests/          # custom generic tests
│       │   └── charts/         # dbt charts report boards
│       └── Dockerfile
├── src/quack/                  # workspace root package
├── Taskfile.yml                # setup, checks, tests, Docker tasks
└── CLAUDE.md                   # conventions, including the dbt documentation practice
```

Each project under `projects/` is a uv workspace member with its own dependencies. Local data lives in `data/`,
which is not committed.

## The financial project

1. **Ingest:** `financial-load` pulls daily prices, company fundamentals (versioned over time) and US economic
   indicators from Alpha Vantage into DuckDB.
2. **Model:** dbt stages, types and tests the raw data. It then builds point-in-time marts: economic data is
   joined to trading days only once it would have been available. It also builds a portfolio of the configured
   holdings.
3. **Report:** a portfolio performance report with an overview and one page per holding, exported as linked
   static HTML.

Column documentation follows a **Declared Divergence** practice, described in [CLAUDE.md](CLAUDE.md): each
concept is defined once, and any difference from it has to be declared explicitly.

## Getting started

```bash
task setup    # install Python and all dependencies
task ci       # lint, format, type check, YAML, secrets and tests
```

The pipeline needs an Alpha Vantage API key in `projects/financial/.dlt/secrets.toml`, under
`[sources.alpha_vantage]` as `api_key`.
