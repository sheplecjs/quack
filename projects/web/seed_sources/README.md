# Seed sources

Inputs for the generated dbt seeds in `web_dbt/seeds/`. Regenerate with `task seeds:update PROJECT=web`
(`uv run web-seeds update`), review the printed diff, and commit the seed with its source. `uv run web-seeds check`
validates both seeds without fetching anything; the test suite runs it too.

If a seed's columns change, rebuild once with `task dbt:build PROJECT=web -- --full-refresh`: dbt loads a seed into
its existing table and won't add columns otherwise.

## `bot_user_agent_patterns.local.csv`

Bot user-agent patterns that [crawler-user-agents](https://github.com/monperrus/crawler-user-agents) misses.
`web-seeds update` appends them to its patterns to build `bot_user_agent_patterns.csv`, with
`user_agent_pattern_source` = `local` and the reason as the note.

| Column | Meaning |
|---|---|
| `user_agent_pattern` | RE2 regular expression, case-sensitive unless it starts with `(?i)` |
| `bot_category` | One of the seed's categories; `generic` ranks below every named bot |
| `reason` | Why it's here: what it recognises, and why upstream doesn't cover it |
| `example_user_agent` | A user agent it must match. `web-seeds update` fails if it doesn't, and warns when an upstream pattern starts matching it, so the local row can be dropped |

Prefer contributing a missing bot to crawler-user-agents and keeping a local row only until it's released.

## `hosting_network_patterns.csv`

Not generated: it's maintained by hand in `web_dbt/seeds/`. Published hosting lists are keyed by AS number,
but Shynet only stores MaxMind's organisation name, and mapping one to the other needs MaxMind's GeoLite2-ASN
data. Every row records `asn_pattern_source` (where the entry comes from) and `asn_pattern_note` (what the
network is); `web-seeds check` fails a row without them.
