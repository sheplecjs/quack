# quack

A uv workspace of analytics projects. Each project lives under `projects/`, e.g.
`projects/financial`, which has a dlt pipeline in `src/financial` and a dbt project in `financial_dbt`.

- Run `task setup` (or `uv sync --all-packages --all-groups`) to install the environment. A plain
  `uv sync` removes the member projects' dependencies and breaks the root-level checks.
- Run `task check` for lint, format, types, YAML and secrets, and `task ci` to add tests.

## dbt documentation: Declared Divergence

Use this practice by default for all dbt properties YAML. The principle: **sameness is the default, and every
difference is declared, in the layer that says what kind of difference it is.** An undeclared difference is a bug.

Reference example: `projects/financial/financial_dbt/models/alpha_vantage/_alpha_vantage.yml`.

### File layout

One properties file per **domain**, holding the domain's source(s) and every staging and mart model built from them:

```
models/<domain>/_<domain>.yml                       # anchors (concept bank), sources, models, unit tests
models/<domain>/staging/stg_<domain>__<table>.sql
models/<domain>/marts/...
```

Don't split properties by layer (sources / staging / marts). Drift follows lineage, and anchors only
resolve within one file, so a split by layer cuts exactly the links the anchors need to span. SQL files
*are* split into layer folders: the domain YAML describes models in any folder, and layer settings
(materialization, contracts) are configured per folder in `dbt_project.yml`.

### The three layers

| Layer | Form | An override means |
|---|---|---|
| `anchors:` (concept bank) | Full definitions | n/a: this is the fully realised state |
| `sources:` | `<<: *concept` plus `name` / `data_type` / `description` | The source system differs from the concept here |
| `models:` (staging, marts) | Bare `*concept`, or `<<: *concept` plus `data_tests` only | This test applies at this grain |

#### 1. Concept bank (`anchors:`)

The top-level `anchors:` key holds every concept as it appears in the finished models.

```yaml
anchors:
  - &trade_volume
    name: trade_volume
    description: Number of shares traded
    data_type: bigint
```

- **Anchor name = concept name = final column name.**
- **Every concept has `name`, `description` and `data_type`.** Use DuckDB's own type names, not aliases:
  `varchar` not `text`/`string`, `double` not `float8`.
- **Every concept carries its identity in `config.meta`:** `concept` (= its name) and `concept_group` (the bank
  section heading it sits under, e.g. `Prices`). Anchors are resolved when the YAML is parsed, so this meta is
  the only way a concept is visible in dbt's graph. The merge copies it onto every use, including renamed source
  columns, and the data dictionary relies on it.

  ```yaml
  - &trade_volume
    name: trade_volume
    config:
      meta:
        concept: trade_volume
        concept_group: Prices
    description: Number of shares traded
    data_type: bigint
  ```
- **Percentages are fractions** (0.041 = 4.1%), whatever scale the source uses. Staging converts 0-100 values,
  and the source override's description records the raw scale.
- **Name concepts by meaning, not by source column.** Use `company_name` and `series_name`, not two concepts
  called `name`.
- **No `data_tests` in the bank.** Sources inherit everything the bank holds, so a bank-level test would run
  against raw data that staging hasn't cleaned yet.
- **A derived column is a new concept.** If a mart aggregates, renames for business use, or changes a
  column's meaning or grain, add a new bank entry (e.g. `&weekly_trade_volume`); don't override an
  existing one.

#### 2. Sources: overrides record where the source system diverges

```yaml
sources:
  - name: alpha_vantage
    tables:
      - name: daily_prices
        columns:
          - <<: *trade_volume
            name: volume
```

- Override only the keys where the raw data differs from the concept: `name` (a rename in staging),
  `data_type` (a cast in staging), or `description` (a source quirk, e.g. text placeholders for missing values).
- Taken together, a source's overrides are the spec for its staging model. Every `name` override
  should correspond to a rename in `stg_*.sql`, and every `data_type` override to a cast. Keep them in step.
- A source column that no model carries forward is defined inline at the source, not in the bank. The bank
  holds only concepts that exist in the finished models.
- **Every source table carries `data_tests: [declared_types_match]`.** It compares the declared columns (after
  overrides) with the real table and reports each column as `type_mismatch`, `missing` or `undeclared`.
  Types are compared by name, case-insensitively, which is why the bank uses DuckDB's own type names.
- Other source-level `data_tests` are allowed for assumptions about the raw data (e.g. the source's grain).

#### 3. Models: overrides are tactical data tests

```yaml
models:
  - name: stg_alpha_vantage__company_overviews
    columns:
      - <<: *ticker_symbol
        data_tests: [unique, not_null]   # one row per symbol at this grain

      - *company_name
```

- Use a bare alias whenever the column is exactly the concept.
- An override in a model may add `data_tests` and nothing else. Changing `name`, `description` or
  `data_type` here means the column is a new concept (see the concept bank rules).
- Choose where each test goes. The same concept can be unique at one grain and repeated at another,
  e.g. `ticker_symbol` in `stg_alpha_vantage__company_overviews` vs `stg_alpha_vantage__daily_prices`.
- Tests that span columns (composite keys with `dbt_utils.unique_combination_of_columns`, row-level
  expressions with `dbt_utils.expression_is_true`) go in the model's own `data_tests`, not on a column.
- List a model's columns in the order its SQL selects them.

### Staging layer

One view per source table, named `stg_<source>__<table>`. A staging model **implements its source's
overrides**: every `name` override is a rename, every `data_type` override is a cast, and every output
column is a bare concept from the bank. No joins, aggregation, filtering, deduplication or business logic.

- **Cast every column explicitly**, even when the source type already matches:
  `cast(close as double) as close_price`. The SQL then reads as a complete mapping, and upstream type
  drift is caught here.
- **Use strict `cast`, never `try_cast`.** `try_cast` hides unexpected values by turning them into nulls.
  Null only the known placeholders, with a source-specific macro, then cast strictly so anything else
  fails the build:
  `cast({{ av_null('pe_ratio') }} as double) as pe_ratio`.
- **Derive the lineage concepts:** `to_timestamp(cast(_dlt_load_id as double)) as loaded_at` and
  `cast(_dlt_id as varchar) as record_id`.
- **Don't deduplicate.** Surface duplicate keys with tests instead of hiding them.
- **Quote source columns that are SQL keywords**, e.g. `"date"` and `"interval"`.

Tests in staging:

- **Types are enforced by a contract:** `+contract: {enforced: true}` on the staging folder in `dbt_project.yml`.
  Staging columns are bare concepts, so the contract checks the output against the bank on every build.
  `declared_types_match` on the sources covers the other half: raw tables against the source overrides.
- **Grain:** a unique key test on every model (`unique` for single-column keys, `unique_combination_of_columns`
  for composite keys), plus `unique` + `not_null` on `record_id` for upserted tables. Versioned tables use
  `(key, valid_from)` as the key, `unique` on the key filtered to `valid_to is null` (one current version),
  and `not_null` only on `record_id`.
- **Source assumptions:** `not_null` on required values, `accepted_values` on small fixed sets, and
  `expression_is_true` for internal consistency (e.g. a price bar's low ≤ open, close ≤ high).
- **References between staging models:** use `relationships`, with a comment where orphans are expected
  (ETFs have no company overview).
- **Unit tests** (`unit_tests:` in the domain YAML) cover the cleaning logic: placeholders become nulls
  and real values cast correctly.
- **Not in staging:** freshness (sources), business rules, checks across models, audit-hash checks
  (marts).

Test configuration (`data_tests:` in `dbt_project.yml`) applies to every test in the project:
- **Severity is `warn`:** a failing test is reported but doesn't stop `dbt build` or skip downstream models.
  Only contracts and unit tests stop a build.
- **Failing rows are kept** as a view per test in the default audit schema, `<target schema>_dbt_test__audit`
  (`main_dbt_test__audit` locally). Query a test's view to see what failed.
- **Don't set `severity` on individual tests** unless it differs from the default: set `error` on a test
  whose failure must block the build.

### Intermediate and marts layers

- **Intermediate** (`int_<domain>__<purpose>`, views) holds each step that does something hard once, e.g.
  aligning grains. It's shared by several marts. Don't join everything into one wide intermediate table:
  mixed grains fan out, and snapshot data joined to history implies history that doesn't exist.
- **Marts** (tables) are `dim_*` (entities, possibly versioned), `fct_*` (events or observations at their native
  grain) and `mart_*` (chart- or consumer-ready, denormalised). Sort each mart with an `order by` on the
  columns it's usually filtered by (ticker, date) so DuckDB can skip blocks.
- **Contracts are enforced on every layer.** Derived columns are new concepts in the bank (e.g. `daily_return`,
  `close_index`, `available_from_date`), so every model's output is declared.
- **Point in time.** Economic observations join to trading days by `available_from_date` (the day after the
  period ends), never by period start, and an `available_from_date <= trading_date` test guards against
  look-ahead. Versioned records join by `valid_from` / `valid_to`.
- **Carry lineage through.** A mart that combines sources keeps each source's id under its own concept
  (`price_record_id`, `indicator_record_id`) with a `relationships` test back to the fact it came from.

### Lineage concepts

Every model carries its load lineage as two bank concepts, mapped at the source from dlt's own columns:

| Concept | Source column | Source override | Staging expression |
|---|---|---|---|
| `loaded_at` (`timestamp with time zone`) | `_dlt_load_id` | `name`, `data_type: varchar` | `to_timestamp(cast(_dlt_load_id as double))` |
| `record_id` (`varchar`) | `_dlt_id` | `name` | `_dlt_id` |

Versioned (`scd2`) tables also carry `valid_from` and `valid_to` (`timestamp with time zone`), mapped from
`_dlt_valid_from` / `_dlt_valid_to` with a `name` override. `valid_to` is null for the current version.

Models that aggregate rows can't carry `record_id`. They carry a hash of their contributing ids as a
separate concept (e.g. `&record_ids_hash`), so any aggregate row can be checked against its inputs:

```sql
md5(string_agg(record_id, ',' order by record_id)) as record_ids_hash
```

- **Sort before hashing** (`order by record_id`). Without a sort the hash depends on row order and is
  not reproducible.
- **Use the same function, separator and ordering everywhere**, and state them in the concept's
  description. An auditor re-runs the grouping on the upstream model and compares hashes.
- **The hash confirms which rows went into an aggregate; it can't identify them.** To find the rows,
  re-run the grouping upstream.

**What the audit path guarantees** depends on each resource's dlt merge strategy:

| Resource | Strategy | `_dlt_id` (`record_id`) is | Grain |
|---|---|---|---|
| `daily_prices`, `economic_indicators` | `upsert` | a hash of the primary key | one row per key |
| `company_overviews` | `scd2`, `merge_key="symbol"` | a hash of the row's content | one row per key per version |

Under `upsert`:
- **`record_id` identifies a record, not a version.** It stays the same across loads for the same key,
  even when the row's values change, e.g. a restated closing price.
- **An aggregate hash proves which records went into it, not which values.** If upstream values are
  corrected but the set of keys is the same, the hash doesn't change.
- **`loaded_at` is the time the row was last written, not when it first arrived.** Every re-fetched row
  is rewritten, changed or not, so for resources that refetch history it tracks the latest load.
- **Primary keys must be unique within a load.** `upsert` doesn't deduplicate its input: a key that
  appears twice in one batch loads as two rows with the same key and the same `record_id`, and no
  error is raised. The pydantic config rejects duplicate symbols, and a unique-key test in staging
  catches anything else.

Under `scd2`:
- **`record_id` identifies the values.** A change writes a new version with a new id; the old version gets
  a `valid_to`. An aggregate hash over versioned rows therefore proves which values went in.
- **`record_id` is not unique.** If values revert to an earlier state, the new version repeats the old
  version's id. The key is `(ticker_symbol, valid_from)`; test `record_id` for `not_null` only.
- **Unchanged rows aren't rewritten,** so `loaded_at` is when the version was first seen, and the table's
  own load ids stop advancing when nothing changes. Source freshness uses the pipeline's load log instead
  (`loaded_at_query` on `_dlt_loads`).
- **`merge_key` limits retirement to the keys in the load,** so a partial run (`--symbols`) doesn't retire
  other companies. The flip side: a symbol the API stops returning keeps its last version as current.
- **Join to prices as of a date** with `valid_from <= date and (valid_to is null or date < valid_to)`,
  or use `valid_to is null` for the current version only.

For every strategy:
- **Hashes are reproducible across builds and loads.** Neither strategy deletes rows, so every id a mart
  has stored still exists upstream. Incremental models may carry `record_id` and hashes derived from it.
- **Changing a resource's strategy needs a reload of that resource:**
  `uv run financial-load --resources <resource> --refresh` drops its table and state before loading.

### Why

- **DRY.** Each concept is defined once; every source and model using it picks up changes.
- **Differences have to be explicit.** With copies, definitions that should match drift apart slightly
  and nobody notices. Here they can't drift, and every difference is an override whose layer says what it
  is: a trait of the source system, or a testing decision.
- **Tests are placed tactically.** Each test is a deliberate decision about a grain, not a copy that got
  duplicated or forgotten.
- **The YAML specifies the transformation.** Source overrides are a source-to-target mapping, so staging
  SQL can be reviewed line by line against them.

### YAML mechanics

- **Anchors resolve within one YAML document only.** They don't carry across files or across a `---`
  separator. Concepts shared between domains need a dbt `{% docs %}` block, referenced with
  `description: "{{ doc('concept') }}"`.
- **dbt accepts the top-level `anchors:` key** without warnings. Keep it first in the file so every
  anchor is defined before any alias uses it.
- **Merges are shallow.** `<<:` replaces whole keys. This is why the bank carries no tests: a model's
  `data_tests` override never has an inherited list to lose.
- **Layout:** separate column entries with a blank line, and keep blank lines free of whitespace
  (yamllint's `trailing-spaces` rule rejects it).

### Data dictionary

`models/dictionary/marts/mart_data_dictionary.sql` walks dbt's graph at compile time and writes one row per
documented column of every source, seed and model: its concept, domain, layer, node, lineage, tests, and
whether it's renamed, retyped or redescribed relative to its concept. A concept's canonical definition is the
most common one among the models using it. Rebuild the dictionary after changing any YAML documentation.

### What's enforced

- **Types:** source tables by `declared_types_match`; every model by its contract.
- **Declared Divergence, by the data dictionary's tests:**
  - every documented column is anchored to a concept (`concept` not null);
  - every concept is used by at least one model (`concept_description` not null);
  - models never rename, retype or redescribe a concept;
  - models agree on each concept (`has_concept_conflict` is false).
- **Not enforced:** that a source override actually differs from its concept. A redundant override looks the
  same as a bare alias once the YAML is parsed.

Check a change by hand against the rules above.
