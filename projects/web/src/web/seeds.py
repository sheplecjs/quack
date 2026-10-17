"""The `web-seeds` CLI: regenerate and check the dbt seeds that classify bot traffic.

- `bot_user_agent_patterns.csv` is generated: the crawler-user-agents list
  (https://github.com/monperrus/crawler-user-agents, MIT) at a pinned commit, plus the local
  patterns in seed_sources/ for what it misses. Every row records its source and a note.
- `hosting_network_patterns.csv` is maintained by hand (published hosting lists are keyed by AS
  number, which Shynet doesn't store), so it's only checked: every row needs a source and a note.

Patterns are checked by DuckDB, whose RE2 engine is what dbt matches them with.
"""

import argparse
import csv
import io
import os
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import duckdb
from dlt.sources.helpers import requests

from web import PROJECT_DIR

SEEDS_DIR = PROJECT_DIR / "web_dbt" / "seeds"
SOURCES_DIR = PROJECT_DIR / "seed_sources"
BOT_SEED = SEEDS_DIR / "bot_user_agent_patterns.csv"
HOSTING_SEED = SEEDS_DIR / "hosting_network_patterns.csv"
LOCAL_BOT_PATTERNS = SOURCES_DIR / "bot_user_agent_patterns.local.csv"
UPSTREAM_LICENSE = SEEDS_DIR / "licenses" / "crawler-user-agents.LICENSE"

UPSTREAM_REPO = "monperrus/crawler-user-agents"
UPSTREAM_FILE = "crawler-user-agents.json"

# crawler-user-agents tag -> bot_category, most specific first: an entry with several tags takes
# the first listed here (e.g. an AI search bot tagged search-engine and ai-crawler is ai_crawler)
TAG_CATEGORIES = {
    "ai-crawler": "ai_crawler",
    "search-engine": "search_crawler",
    "seo": "seo_crawler",
    "social-preview": "social_preview",
    "monitoring": "monitoring",
    "scanner": "security_scanner",
    "advertising": "advertising",
    "feed-reader": "feed_reader",
    "archiver": "archiver",
    "academic": "academic",
    "browser-automation": "automation_tool",
    "http-library": "automation_tool",
}
# Local-only categories: generic is a fallback that ranks below every named bot
LOCAL_CATEGORIES = frozenset({*TAG_CATEGORIES.values(), "generic"})
NETWORK_CATEGORIES = frozenset(
    {"cloud_hosting", "vpn_proxy", "security_scanner", "crawler_operator"}
)

BOT_COLUMNS = (
    "user_agent_pattern",
    "bot_category",
    "user_agent_pattern_source",
    "user_agent_pattern_note",
)
HOSTING_COLUMNS = (
    "asn_pattern",
    "network_category",
    "asn_pattern_source",
    "asn_pattern_note",
)


class SeedError(Exception):
    """Raised when a seed or one of its sources is invalid."""


@dataclass(frozen=True)
class BotPattern:
    pattern: str
    category: str
    source: str
    note: str

    def row(self) -> dict[str, str]:
        return dict(
            zip(BOT_COLUMNS, (self.pattern, self.category, self.source, self.note))
        )


def _clean(text: str) -> str:
    return " ".join(text.split())


def regex_errors(patterns: Iterable[str]) -> dict[str, str]:
    """Patterns DuckDB's RE2 can't compile, with the error for each."""
    errors = {}
    with duckdb.connect() as conn:
        for pattern in patterns:
            try:
                conn.execute("select regexp_matches('', ?)", [pattern])
            except duckdb.Error as e:
                errors[pattern] = str(e).splitlines()[0]
    return errors


def matches(patterns: Sequence[str], text: str) -> list[str]:
    """The patterns that match `text`, as dbt will match them (RE2, case-sensitive unless (?i))."""
    if not patterns:
        return []
    with duckdb.connect() as conn:
        rows = conn.execute(
            "select pattern from unnest(?) as t(pattern) where regexp_matches(?, pattern)",
            [list(patterns), text],
        ).fetchall()
    return [pattern for (pattern,) in rows]


def fetch_upstream(ref: str) -> tuple[str, list[dict], str]:
    """crawler-user-agents' entries and licence at `ref`, and the commit it resolved to."""
    commit = requests.get(
        f"https://api.github.com/repos/{UPSTREAM_REPO}/commits/{ref}",
        headers={"Accept": "application/vnd.github+json"},
        timeout=30,
    ).json()["sha"]
    raw = f"https://raw.githubusercontent.com/{UPSTREAM_REPO}/{commit}"
    entries = requests.get(f"{raw}/{UPSTREAM_FILE}", timeout=60).json()
    license_text = requests.get(f"{raw}/LICENSE", timeout=30).text
    return commit, entries, license_text


def upstream_patterns(entries: Iterable[dict], commit: str) -> list[BotPattern]:
    """Map upstream entries to seed rows, skipping (with a warning) any RE2 can't compile."""
    entries = list(entries)
    errors = regex_errors(entry["pattern"] for entry in entries)
    patterns = []
    for entry in entries:
        if entry["pattern"] in errors:
            print(
                f"skipped upstream pattern {entry['pattern']!r}: {errors[entry['pattern']]}"
            )
            continue
        tags = entry.get("tags") or []
        unknown = [tag for tag in tags if tag not in TAG_CATEGORIES]
        if unknown or not tags:
            raise SeedError(
                f"upstream pattern {entry['pattern']!r} has tags {tags}; "
                "map each new tag in TAG_CATEGORIES"
            )
        tag = min(tags, key=list(TAG_CATEGORIES).index)
        patterns.append(
            BotPattern(
                pattern=entry["pattern"],
                category=TAG_CATEGORIES[tag],
                source=f"crawler-user-agents@{commit[:12]}",
                note=_clean(entry.get("description") or entry.get("url") or ""),
            )
        )
    return patterns


def read_csv(path: Path, columns: Sequence[str]) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != tuple(columns):
            raise SeedError(
                f"{path.name}: expected columns {list(columns)}, got {reader.fieldnames}"
            )
        return list(reader)


def local_patterns(upstream: Sequence[BotPattern]) -> list[BotPattern]:
    """The local patterns, checked; warns about any whose example upstream now recognises."""
    rows = read_csv(
        LOCAL_BOT_PATTERNS,
        ("user_agent_pattern", "bot_category", "reason", "example_user_agent"),
    )
    errors = regex_errors(row["user_agent_pattern"] for row in rows)
    valid = [
        row
        for row in rows
        if row["user_agent_pattern"] not in errors and row["example_user_agent"]
    ]
    examples = [r["example_user_agent"] for r in valid]
    self_matched: set[str] = set()
    covered: dict[str, str] = {}
    with duckdb.connect() as conn:
        if valid:
            # Each valid row's own pattern against its own example (the two lists unnest in step)
            self_matched = {
                pattern
                for (pattern,) in conn.execute(
                    "select pattern from (select unnest(?::varchar[]) as pattern, unnest(?::varchar[]) as example) "
                    "where regexp_matches(example, pattern)",
                    [[r["user_agent_pattern"] for r in valid], examples],
                ).fetchall()
            }
        if valid and upstream:
            # Every example against every upstream pattern, in one pass
            covered = dict(
                conn.execute(
                    "select example, min(pattern) from (select unnest(?::varchar[]) as example), "
                    "(select unnest(?::varchar[]) as pattern) where regexp_matches(example, pattern) group by example",
                    [examples, [p.pattern for p in upstream]],
                ).fetchall()
            )

    problems = []
    patterns = []
    for row in rows:
        pattern, category, example = (
            row["user_agent_pattern"],
            row["bot_category"],
            row["example_user_agent"],
        )
        if pattern in errors:
            problems.append(f"{pattern!r}: {errors[pattern]}")
            continue
        if category not in LOCAL_CATEGORIES:
            problems.append(f"{pattern!r}: unknown bot_category {category!r}")
        if not row["reason"].strip():
            problems.append(f"{pattern!r}: needs a reason")
        if pattern not in self_matched:
            problems.append(f"{pattern!r}: needs an example_user_agent that it matches")
        elif category != "generic" and example in covered:
            print(
                f"local pattern {pattern!r} is now covered upstream by {covered[example]!r}; consider removing it"
            )
        patterns.append(BotPattern(pattern, category, "local", _clean(row["reason"])))
    if problems:
        raise SeedError(f"{LOCAL_BOT_PATTERNS.name}:\n  " + "\n  ".join(problems))
    return patterns


def bot_seed_rows(patterns: Sequence[BotPattern]) -> list[dict[str, str]]:
    """Seed rows: upstream then local, each sorted, so regenerating gives small, reviewable diffs."""
    return [
        p.row()
        for p in sorted(patterns, key=lambda p: (p.source == "local", p.pattern))
    ]


def write_atomically(path: Path, text: str) -> None:
    """Write via a temporary file, so a failure never leaves a half-written file behind."""
    path.parent.mkdir(exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, newline="")
    os.replace(temporary, path)


def csv_text(rows: Sequence[dict[str, str]], columns: Sequence[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def summarise_changes(
    before: Sequence[dict[str, str]], after: Sequence[BotPattern]
) -> str:
    old = {row["user_agent_pattern"]: row["bot_category"] for row in before}
    new = {p.pattern: p.category for p in after}
    added = sorted(new.keys() - old.keys())
    removed = sorted(old.keys() - new.keys())
    recategorised = sorted(k for k in old.keys() & new.keys() if old[k] != new[k])
    lines = [
        f"{len(new)} patterns: {len(added)} added, {len(removed)} removed, {len(recategorised)} recategorised"
    ]
    for label, keys in (
        ("added", added),
        ("removed", removed),
        ("recategorised", recategorised),
    ):
        lines.extend(f"  {label}: {key}" for key in keys[:10])
        if len(keys) > 10:
            lines.append(f"  ... and {len(keys) - 10} more {label}")
    return "\n".join(lines)


def update(ref: str) -> str:
    """Regenerate the bot seed from upstream at `ref` plus the local patterns.

    Everything is validated before anything is written, so a failed update leaves the committed
    seed and licence untouched.
    """
    commit, entries, license_text = fetch_upstream(ref)
    upstream = upstream_patterns(entries, commit)
    local = local_patterns(upstream)
    rows = bot_seed_rows([*upstream, *local])
    problems = check_rows(
        BOT_SEED.name, rows, BOT_COLUMNS, LOCAL_CATEGORIES
    ) + check_rows(
        HOSTING_SEED.name,
        read_csv(HOSTING_SEED, HOSTING_COLUMNS),
        HOSTING_COLUMNS,
        NETWORK_CATEGORIES,
    )
    if problems:
        raise SeedError("nothing written:\n" + "\n".join(problems))

    # Only the pattern and category are compared, so an older column layout still reads
    before = []
    if BOT_SEED.exists():
        with BOT_SEED.open(newline="") as f:
            before = list(csv.DictReader(f))
    write_atomically(BOT_SEED, csv_text(rows, BOT_COLUMNS))
    write_atomically(UPSTREAM_LICENSE, license_text)
    return f"crawler-user-agents@{commit}\n" + summarise_changes(
        before, [*upstream, *local]
    )


def check_rows(
    name: str,
    rows: Sequence[dict[str, str]],
    columns: Sequence[str],
    categories: frozenset[str],
) -> list[str]:
    """Problems with a seed's rows: regexes, duplicates, categories, and each row's source and note."""
    pattern, category, source, note = columns
    errors = regex_errors(row[pattern] for row in rows)
    counts = Counter(row[pattern] for row in rows)
    problems = []
    for row in rows:
        label = f"{name}: {row[pattern]!r}"
        if row[pattern] in errors:
            problems.append(f"{label}: {errors[row[pattern]]}")
        if counts[row[pattern]] > 1:
            problems.append(f"{label}: listed {counts[row[pattern]]} times")
        if row[category] not in categories:
            problems.append(f"{label}: unknown {category} {row[category]!r}")
        if not row[source].strip() or not row[note].strip():
            problems.append(f"{label}: needs a {source} and a {note}")
    return problems


def check() -> str:
    """Check both seeds as committed: columns, categories, regexes, and every row's source and note."""
    problems = check_rows(
        BOT_SEED.name, read_csv(BOT_SEED, BOT_COLUMNS), BOT_COLUMNS, LOCAL_CATEGORIES
    ) + check_rows(
        HOSTING_SEED.name,
        read_csv(HOSTING_SEED, HOSTING_COLUMNS),
        HOSTING_COLUMNS,
        NETWORK_CATEGORIES,
    )
    if problems:
        raise SeedError("\n".join(problems))
    return "seeds ok"


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Regenerate and check the bot classification seeds."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    update_parser = commands.add_parser(
        "update",
        help="Regenerate bot_user_agent_patterns.csv from crawler-user-agents and the local patterns",
    )
    update_parser.add_argument(
        "--ref",
        default="master",
        help="crawler-user-agents branch, tag or commit (default: master)",
    )
    commands.add_parser("check", help="Check both seeds without fetching anything")
    args = parser.parse_args(argv)

    if args.command == "update":
        print(update(args.ref))
    print(check())


if __name__ == "__main__":
    main()
