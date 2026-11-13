# quack

> **Work in progress.** This repository showcases full-stack data engineering: ingestion, modelling, testing,
> documentation and reporting on DuckDB, run locally or on a schedule in AWS.

## Stack

| Layer | Tool |
|---|---|
| Environment | [uv](https://docs.astral.sh/uv/) workspace (Python 3.14), [Task](https://taskfile.dev/) runner |
| Ingestion | [dlt](https://dlthub.com/), with pydantic-validated config, from the [Alpha Vantage](https://www.alphavantage.co/) and [Shynet](https://github.com/milesmcc/shynet) APIs |
| Storage | [DuckDB](https://duckdb.org/) |
| Transformation | [dbt](https://www.getdbt.com/) (dbt-duckdb): staging, intermediate and mart layers with enforced contracts |
| Semantic layer | dbt semantic models, metrics and saved queries, queried with [MetricFlow](https://docs.getdbt.com/docs/build/about-metricflow) (`mf`) |
| Reporting | [dbt charts](https://dbtcharts.com/) (`dct`) boards, exported as static HTML; [marimo](https://marimo.io/) notebooks for exploration |
| Quality | ruff, ty, pytest, yamllint, detect-secrets; dbt data and unit tests |
| Packaging | Docker: one image per project, from the root `Dockerfile` |
| Infrastructure | [AWS CDK](https://docs.aws.amazon.com/cdk/) (Python) with [cdk-nag](https://github.com/cdklabs/cdk-nag): ECS Fargate tasks orchestrated by Step Functions, EventBridge Scheduler, S3 |
| CI/CD | GitHub Actions, authenticated to AWS with OIDC (no stored keys) |

## Repository structure

```
quack/
├── projects/
│   ├── financial/              # Market and macroeconomic data project
│   │   ├── src/financial/      # financial-load and financial-metrics CLIs, shared DuckDB destination
│   │   │   └── ingestion/      # one dlt source per subpackage, e.g. alpha_vantage/
│   │   ├── src/notebooks/      # marimo notebooks
│   │   ├── tests/              # pytest suite for the pipeline
│   │   ├── financial_dbt/      # dbt project
│   │   │   ├── models/         # one folder per domain (e.g. assets/): staging/, intermediate/, marts/
│   │   │   ├── seeds/          # e.g. the portfolio holdings
│   │   │   ├── tests/          # custom generic tests
│   │   │   └── charts/         # dbt charts report boards; _metrics.yml is generated from the saved queries
│   └── web/                    # Web analytics project
│       ├── src/web/            # web-load CLI; ingestion/shynet/ loads a Shynet instance
│       ├── tests/
│       └── web_dbt/            # dbt project: traffic domain and data dictionary
├── packages/runtime/           # quack-run: runs a pipeline step against S3 in a container
├── src/quack/                  # the CDK app: stacks/ for GitHub OIDC, storage and the pipeline
├── tests/infra/                # CDK assertion and cdk-nag tests
├── .github/workflows/          # CI, deploy, destroy-ephemeral
├── Dockerfile                  # one image per project (--build-arg PROJECT=<name>)
├── cdk.json                    # CDK app entry point and deployment settings (the `quack` context)
├── Taskfile.yml                # setup, checks, tests, Docker and CDK tasks
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
3. **Measure:** a semantic layer defines risk metrics (beta, alpha, correlation, volatility, the Sharpe ratio)
   for each holding and the whole portfolio against a benchmark index fund, queryable over any period.
4. **Report:** a portfolio performance report with an overview, a risk and return page and one page per
   holding, exported as linked static HTML.
5. **Document:** a data dictionary model, built from dbt's graph, lists every column in the project with its
   concept, lineage, tests and any declared divergence.

Column documentation follows a **Declared Divergence** practice, described in [CLAUDE.md](CLAUDE.md): each
concept is defined once, and any difference from it has to be declared explicitly.

### Semantic layer and risk metrics

`fct_daily_returns_vs_benchmark` holds one row per return series, benchmark and trading day. A return series is
a holding or the whole portfolio. Each row has the series' daily return, the benchmark's, and the risk-free
return over the same days, from the 3-month Treasury bill rate. The benchmark is SPY, set in the `benchmarks`
seed. The portfolio's return is weighted by the previous day's position values, so buying a holding isn't
counted as a gain.

The `benchmark_returns` semantic model, declared on that model in `models/assets/_assets.yml`, defines these
metrics:

| Metric | Meaning |
|---|---|
| `benchmark_beta` | How far the series moves with the benchmark, both measured above the risk-free rate |
| `benchmark_correlation` | Correlation with the benchmark, from -1 to 1 |
| `annualized_alpha` | Yearly return above what the series' beta and the benchmark's return predict |
| `annualized_excess_return` | Average return above the risk-free rate, as a yearly fraction |
| `benchmark_annualized_excess_return` | The benchmark's own excess return over the same days |
| `annualized_volatility` | Standard deviation of the daily return, scaled to a year |
| `sharpe_ratio` | Excess return per unit of volatility |
| `benchmark_return_days` | Trading days in the period with returns for both the series and the benchmark |

How they're calculated:

- **Built from sums.** Beta, correlation and volatility aren't additive, so each is derived from additive sums:
  returns, their squares and their cross products. That keeps them correct over any period chosen at query
  time, from a month to all history.
- **Short periods are left empty.** Every metric except `benchmark_return_days` is null for a period of fewer
  than 20 trading days.
- **Yearly figures** scale daily ones over 252 trading days.
- **Rolling beta is a column, not a metric.** A rolling 60-day beta depends on the order of the days, so it's
  the mart column `beta_60_day` instead.

**Querying with MetricFlow.** `mf` reads the semantic manifest from dbt's `target/`. Run it from the dbt
project, with the same environment as dbt:

```bash
cd projects/financial/financial_dbt
export DBT_PROFILES_DIR=.. DUCKDB_PATH=../../../data/financial/data.duckdb

uv run dbt parse --no-partial-parse                       # writes target/semantic_manifest.json
uv run mf list metrics                                    # every metric, with the dimensions it can use
uv run mf list dimensions --metrics benchmark_beta        # what benchmark_beta can be grouped by
```

For example, the portfolio's beta, alpha and Sharpe ratio for each calendar month:

```bash
uv run mf query \
  --metrics benchmark_return_days,benchmark_beta,annualized_alpha,sharpe_ratio \
  --group-by benchmark_return_day__return_series,metric_time__month \
  --where "{{ Dimension('benchmark_return_day__return_series') }} = 'Portfolio'" \
  --order metric_time__month
```

```
metric_time__month    benchmark_return_day__return_series      benchmark_return_days    benchmark_beta    sharpe_ratio    annualized_alpha
--------------------  -------------------------------------  -----------------------  ----------------  --------------  ------------------
2026-06-01T00:00:00   Portfolio                                                    4
2026-07-01T00:00:00   Portfolio                                                   22         -0.121099        3.40817            0.588377
2026-08-01T00:00:00   Portfolio                                                   21          0.288169        5.5676             0.578972
2026-09-01T00:00:00   Portfolio                                                   21          0.403292        0.361104           0.0904172
2026-10-01T00:00:00   Portfolio                                                   22          0.212995        2.31293            0.255659
2026-11-01T00:00:00   Portfolio                                                    9
```

June and November are empty: each has fewer than 20 trading days in the data. Other ways to query:

- **Another grain:** swap `metric_time__month` for `metric_time__quarter` or `metric_time__year`, or drop it for
  all history.
- **Other series:** drop the `--where` to see every holding.
- **By benchmark:** group by the `benchmark` entity, as in `--group-by benchmark_return_day__return_series,benchmark`.
- **See the SQL:** add `--explain` to print the SQL MetricFlow generates instead of running it.
- **Run a saved query** from the domain YAML: `uv run mf query --saved-query risk_all_history`.

**In the reports.** dbt charts runs SQL, not semantic-layer queries. `financial-metrics update`, run from the dbt
project after `dbt parse`, compiles each saved query with MetricFlow into
`financial_dbt/charts/_metrics.yml`. The risk and return board (`charts/risk.yml`) extends that file, so every
figure on it has a single definition in the semantic layer. `financial-metrics check` fails while the file is
out of date, and `render_reports.sh` runs it before rendering.

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

## Running on AWS

The CDK app in `src/quack` runs each project's pipeline on a schedule: load, dbt build, then render, each as
an ECS Fargate task. It has three stacks, each with its own lifecycle:

| Stack | Holds | Lifecycle |
|---|---|---|
| `QuackGithubOidc` | GitHub OIDC provider; a deploy role (the `aws` environment) and a read-only diff role (pull requests) | Deployed once by hand |
| `QuackStorage` | Data bucket (`<project>/data.duckdb`, versioned), artifacts bucket (`<project>/report/`, `<project>/dbt/`), logs bucket (S3 access logs, VPC flow logs), one secret per project, the alert topic | Persistent: termination-protected, every resource retained |
| `QuackPipeline` | VPC (private subnets with egress through one NAT gateway, S3 gateway endpoint, flow logs), ECS cluster, and per project: image, task definition, state machine, schedule, failure alert rule | Ephemeral: deployed each weekday morning, destroyed each evening |

```
EventBridge Scheduler ─▶ Step Functions: Load ─▶ Build ─▶ Render   (one ECS Fargate task each)
                                           │        │        │
                       data bucket ◀── pull/push  pull/push  pull ──▶ artifacts bucket (reports, dbt docs)
                 failure ─▶ EventBridge rule ─▶ SNS alert topic (QuackStorage)
```

- **The stacks share nothing through CloudFormation exports.** The storage stack publishes its identifiers as
  SSM parameters under `/quack/storage/`, and the pipeline stack reads them at deploy time. Either can be
  deployed or destroyed without the other.
- **State lives in S3.** DuckDB can't write to S3 directly, and dlt keeps its pipeline state inside the
  database, so each step pulls `data.duckdb`, runs, and pushes it back with a conditional write
  (`quack-run`, in `packages/runtime`). If another run changed the file in the meantime, the push fails
  instead of overwriting it. Nothing is pushed when a step fails.
- **Least privilege.** Each project's task role reaches only its own `<project>/` prefix, its execution
  role only its own secret. The GitHub roles can only assume the CDK bootstrap roles, and only from this
  repository's `aws` environment (deploys) or its pull requests (diffs).
- **cdk-nag** (AWS Solutions rules) runs on every synth. Each accepted finding is acknowledged with a reason
  in the construct it's about, and `tests/infra` fails if a new one isn't.

### Setting up

Once, with administrator credentials for the target account and region:

1. `task cdk:bootstrap`.
2. `task cdk:deploy:oidc`. If the account already has a GitHub OIDC provider, set its ARN as
   `github_oidc_provider_arn` in `cdk.json` first.
3. `task cdk:deploy -- QuackStorage`, then set each project's secret. They're created with placeholder
   values, which the pipelines reject:

   ```bash
   aws secretsmanager put-secret-value --secret-id <arn> \
     --secret-string '{"SOURCES__ALPHA_VANTAGE__API_KEY": "..."}'
   ```

   The secret ARNs are in SSM at `/quack/storage/projects/<project>/secret-arn`. Each project's keys are
   listed in `cdk.json`.
4. In GitHub, create an environment named `aws`, limited to the `main` branch. Add repository variables
   `AWS_REGION`, `AWS_DEPLOY_ROLE_ARN` and `AWS_DIFF_ROLE_ARN`, from step 2's `DeployRoleArn` and
   `DiffRoleArn` outputs.
5. Optionally, set `alert_email` in `cdk.json` and confirm the subscription email.

### CI/CD

| Workflow | Runs | Does |
|---|---|---|
| `ci.yml` | Pull requests, pushes to `main` | `task ci`, then `cdk synth` (cdk-nag); on pull requests, `cdk diff` against AWS in the job summary |
| `deploy.yml` | 08:00 UTC on weekdays, pushes to `main`, by hand | Deploys `QuackStorage` and `QuackPipeline`. A push outside 08:00-20:00 UTC on a weekday deploys storage only |
| `destroy-ephemeral.yml` | 20:00 UTC daily, by hand | Destroys `QuackPipeline` only |

Deploy and destroy share a concurrency group, so they never overlap. The pipelines' schedules in `cdk.json`
(09:00 and 09:30 UTC on weekdays) fall inside the window the pipeline stack exists.

### Operating

```bash
task cdk:synth                 # synth and cdk-nag, no credentials needed
task cdk:diff                  # against what's deployed
task cdk:destroy:ephemeral     # take the pipeline stack down now
```

- **Run a pipeline now:** start an execution of its state machine (`FinancialPipeline...` in the Step Functions
  console, or `aws stepfunctions start-execution`).
- **Roll back the database:** restore an earlier version of `<project>/data.duckdb` in the data bucket.
  Replaced versions are kept for 30 days (`noncurrent_version_days`).
- **Logs:** each project's tasks log to their own CloudWatch log group, the state machines to another.
- **VPC flow logs** go to the logs bucket as Parquet under `vpc-flow-logs/AWSLogs/aws-account-id=<id>/aws-service=vpcflowlogs/aws-region=<region>/year=/month=/day=/hour=/`,
  so they outlive the pipeline stack. The Hive-style partitions suit an Athena table with partition projection.
- **Cost:** while it exists, the pipeline stack's main fixed cost is the NAT gateway. Fargate is billed only
  while a step runs. Destroying the stack each evening leaves only S3, Secrets Manager and KMS charges.

