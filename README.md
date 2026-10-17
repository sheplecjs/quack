# quack

> **Work in progress.** This repository showcases full-stack data engineering: ingestion, modelling, testing,
> documentation and reporting, all running locally on DuckDB.

## Stack

| Layer | Tool |
|---|---|
| Environment | [uv](https://docs.astral.sh/uv/) workspace (Python 3.14), [Task](https://taskfile.dev/) runner |
| Ingestion | [dlt](https://dlthub.com/), with pydantic-validated config, from the [Alpha Vantage](https://www.alphavantage.co/) and [Shynet](https://github.com/milesmcc/shynet) APIs |
| Storage | [DuckDB](https://duckdb.org/) |
| Transformation | [dbt](https://www.getdbt.com/) (dbt-duckdb): staging, intermediate and mart layers with enforced contracts |
| Reporting | [dbt charts](https://dbtcharts.com/) (`dct`) boards, exported as static HTML; [marimo](https://marimo.io/) notebooks for exploration |
| Quality | ruff, ty, pytest, yamllint, detect-secrets; dbt data and unit tests |
| Packaging | Docker, per project |

## Repository structure

```
quack/
├── projects/
│   ├── financial/              # Market and macroeconomic data project
│   │   ├── src/financial/      # financial-load CLI and shared DuckDB destination
│   │   │   └── ingestion/      # one dlt source per subpackage, e.g. alpha_vantage/
│   │   ├── src/notebooks/      # marimo notebooks
│   │   ├── tests/              # pytest suite for the pipeline
│   │   ├── financial_dbt/      # dbt project
│   │   │   ├── models/         # one folder per domain (e.g. assets/): staging/, intermediate/, marts/
│   │   │   ├── seeds/          # e.g. the portfolio holdings
│   │   │   ├── tests/          # custom generic tests
│   │   │   └── charts/         # dbt charts report boards
│   │   └── Dockerfile
│   └── web/                    # Web analytics project
│       ├── src/web/            # web-load CLI; ingestion/shynet/ loads a Shynet instance
│       ├── tests/
│       └── web_dbt/            # dbt project: traffic domain and data dictionary
├── src/quack/                  # workspace root package
├── Taskfile.yml                # setup, checks, tests, Docker tasks
└── CLAUDE.md                   # conventions, including the dbt documentation practice
```

Each project under `projects/` is a uv workspace member with its own dependencies. Local data lives in `data/`,
which is not committed.

## The financial project

1. **Ingest:** `financial-load alpha-vantage` pulls daily prices, company fundamentals (versioned over time) and US economic
   indicators from Alpha Vantage into DuckDB.
2. **Model:** dbt stages, types and tests the raw data. It then builds point-in-time marts: economic data is
   joined to trading days only once it would have been available. It also builds a portfolio of the configured
   holdings.
3. **Report:** a portfolio performance report with an overview and one page per holding, exported as linked
   static HTML.
4. **Document:** a data dictionary model, built from dbt's graph, lists every column in the project with its
   concept, lineage, tests and any declared divergence.

Column documentation follows a **Declared Divergence** practice, described in [CLAUDE.md](CLAUDE.md): each
concept is defined once, and any difference from it has to be declared explicitly.

## The web project

`web-load shynet` loads daily traffic stats for my sites from a self-hosted Shynet instance. Then dbt stages them
into daily and hourly traffic marts. See [projects/web/README.md](projects/web/README.md).

## Getting started

```bash
task setup    # install Python and all dependencies
task ci       # lint, format, type check, YAML, secrets and tests
```

Project tasks take `PROJECT=<name>`, and prompt with a menu of projects when it's missing and there's a terminal:

```bash
task pipeline PROJECT=web                         # ingest every source, dbt build, render reports
task ingest PROJECT=web -- shynet-db --refresh    # one source, with its options
task dbt:build PROJECT=web -- --select fct_sessions+   # also writes data/web/report/dbt_docs.html
task profile:ingestion PROJECT=web                # the ingestion profile notebook
```

The pipeline needs an Alpha Vantage API key in `projects/financial/.dlt/secrets.toml`, under
`[sources.alpha_vantage]` as `api_key`. The web project needs a Shynet API key and base URL in `projects/web/.dlt/secrets.toml`,
under `[sources.shynet]` as `api_key` and `base_url`.
