# web

Web analytics for my own sites, starting with traffic to my profile website from a self-hosted
[Shynet](https://github.com/milesmcc/shynet) instance.

## Ingestion

`web-load shynet` loads the [Shynet dashboard API](https://github.com/milesmcc/shynet/blob/master/GUIDE.md#api)
into the `shynet` schema of `data/web/data.duckdb`.

The API serves the dashboard's aggregates, not raw sessions and hits, so the pipeline asks for one day at a time.
Each day's response fills every table:

| Table | Grain | From the response |
|---|---|---|
| `services` | service | `name`, `uuid`, `link` |
| `daily_stats` | service, day | session and hit counts, bounce rate, average session duration, load time and hits per session |
| `hourly_stats` | service, hour | the dashboard chart, which Shynet makes hourly for ranges under three days |
| `daily_locations`, `daily_referrers` | service, day, page / referrer | hits per page; sessions started per referrer (top 300 each) |
| `daily_countries`, `daily_operating_systems`, `daily_browsers`, `daily_devices`, `daily_device_types` | service, day, value | sessions started per value (top 300 each) |

Every table is upserted on its primary key. A run resumes from the last day loaded, minus `lookback_days`
(default 3), so partial days (today, or a time zone ahead of UTC) are completed by later runs. Days are calendar
days in the Shynet server's `TIME_ZONE`.

```bash
uv run web-load shynet                                                  # resume from the last day loaded
uv run web-load shynet --start-date 2025-01-01 --end-date 2025-12-31    # backfill a window
uv run web-load shynet --resources daily_stats hourly_stats --refresh   # drop and reload from initial_start_date
```

### Configuration

`.dlt/config.toml`, under `[sources.shynet]`: optionally `service_uuids`, `initial_start_date` and
`lookback_days`.

The instance URL and API key go in `.dlt/secrets.toml` (not committed). Find the key in Shynet under your
account's API settings:

```toml
[sources.shynet]
base_url = "https://shynet.example.com"  # the instance root, https only
api_key = "<paste-your-shynet-api-key-here>"
```

### Shynet database

`web-load shynet-db` reads Shynet's `analytics_session` and `analytics_hit` tables straight from its Postgres
into the `shynet_db` schema, as `sessions` and `hits`. Unlike the API, this gives one row per session and per hit,
which session-level analysis such as bot classification needs.

- It connects as a read-only role that can select only the columns it loads: no `ip`, `latitude`, `longitude` or
  `identifier`, and no other tables. Every query names its columns, since `select *` is refused.
- Rows are read incrementally on `last_seen`, with a one-hour lag for late commits, and upserted on their primary
  keys. Rows deleted in Shynet are kept.
- The connection must require TLS: the pipeline refuses a URL without `sslmode=require` (or `verify-ca` /
  `verify-full`).

```toml
[sources.shynet_db]
credentials = "postgresql://<reader>:<password>@<host>/<database>?sslmode=require"
```

```bash
uv run web-load shynet-db                       # rows changed since the last load
uv run web-load shynet-db --refresh             # drop and reload everything
```

## dbt

`web_dbt/` follows the repo's Declared Divergence practice (see the root `CLAUDE.md`). One domain, `traffic`,
holds both sources, a staging view per source table, and the marts `dim_services`, `fct_daily_traffic`,
`fct_hourly_traffic`, `fct_sessions` and `mart_daily_sessions_by_class`. The `dictionary` domain holds the data
dictionary.

### Bot classification

`fct_sessions` flags each session with independent bot signals and a heuristic `traffic_class`:

| Class | Rule (first that applies) |
|---|---|
| `development` | a hit on a local address (localhost, 127.x, file:) |
| `declared_bot` | the user agent says it's a bot (`seeds/bot_user_agent_patterns.csv`, or Shynet's ROBOT) |
| `likely_bot` | JavaScript never ran, a long-outdated Chrome, or a malformed user agent; or a hosting network or burst backed by a single no-engagement hit or each other |
| `possible_bot` | a hosting network (`seeds/hosting_network_patterns.csv`) or a burst, alone |
| `human` | none of the above |

It's an estimate, not a verdict: each signal's concept description states its limitations. In short, it undercounts
bots, because Shynet only sees clients that run its script or load its pixel, and a bot with a current browser
user agent on a residential network looks human. It can also overcount them, catching people on VPNs, corporate
networks or old managed browsers.

The two pattern lists are dbt seeds, and every row records where it came from (see
[seed_sources/README.md](seed_sources/README.md)):

- `bot_user_agent_patterns.csv` is generated from [crawler-user-agents](https://github.com/monperrus/crawler-user-agents)
  (MIT) at a pinned commit, plus local patterns for what it misses: `task seeds:update PROJECT=web`.
- `hosting_network_patterns.csv` is maintained by hand, with a source and a note on each row.

Two variables in `dbt_project.yml` tune it: `shynet_time_zone` (the Shynet server's `TIME_ZONE`, so session days
match the API's; a singular test checks they agree) and `outdated_chrome_releases`.

```bash
cd projects/web/web_dbt
export DBT_PROFILES_DIR=.. DUCKDB_PATH=../../../data/web/data.duckdb
uv run dbt deps
uv run dbt build
```
