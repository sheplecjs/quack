import pytest
from web import seeds

COMMIT = "9345a7ad9c49cd0fbd880eb5a84ed1f358fc6a97"  # pragma: allowlist secret (a public git commit)


def entry(pattern, *tags, description="A bot"):
    return {
        "pattern": pattern,
        "tags": list(tags),
        "description": description,
        "url": "https://example.com",
    }


def test_committed_seeds_pass_the_check():
    assert seeds.check() == "seeds ok"


def test_upstream_entries_become_rows_with_their_source():
    (row,) = seeds.upstream_patterns([entry("Googlebot\\/", "search-engine")], COMMIT)
    assert row == seeds.BotPattern(
        "Googlebot\\/", "search_crawler", "crawler-user-agents@9345a7ad9c49", "A bot"
    )


def test_the_most_specific_tag_wins():
    (row,) = seeds.upstream_patterns(
        [entry("AISearchBot", "search-engine", "ai-crawler")], COMMIT
    )
    assert row.category == "ai_crawler"


@pytest.mark.parametrize("tags", [(), ("brand-new-tag",)])
def test_an_unmapped_tag_stops_the_update(tags):
    with pytest.raises(seeds.SeedError, match="TAG_CATEGORIES"):
        seeds.upstream_patterns([entry("SomeBot", *tags)], COMMIT)


def test_patterns_re2_cannot_compile_are_skipped(capsys):
    rows = seeds.upstream_patterns(
        [entry("(?=lookahead)Bot", "seo"), entry("GoodBot", "seo")], COMMIT
    )
    assert [row.pattern for row in rows] == ["GoodBot"]
    assert "skipped upstream pattern" in capsys.readouterr().out


def test_matching_is_case_sensitive_unless_opted_out():
    assert seeds.matches(["bingbot"], "Mozilla/5.0 (compatible; bingbot/2.0)") == [
        "bingbot"
    ]
    assert seeds.matches(["BingBot"], "Mozilla/5.0 (compatible; bingbot/2.0)") == []
    assert seeds.matches(["(?i)BingBot"], "Mozilla/5.0 (compatible; bingbot/2.0)") == [
        "(?i)BingBot"
    ]


@pytest.fixture
def local_file(tmp_path, monkeypatch):
    path = tmp_path / "local.csv"
    monkeypatch.setattr(seeds, "LOCAL_BOT_PATTERNS", path)

    def write(*rows):
        path.write_text(
            "user_agent_pattern,bot_category,reason,example_user_agent\n"
            + "".join(",".join(row) + "\n" for row in rows)
        )

    return write


def test_local_patterns_need_an_example_they_match(local_file):
    local_file(("^Java/", "automation_tool", "Java HTTP client", "curl/8.0"))
    with pytest.raises(seeds.SeedError, match="example_user_agent that it matches"):
        seeds.local_patterns([])


def test_local_patterns_need_a_reason_and_a_known_category(local_file):
    local_file(("^Java/", "made_up", "", "Java/17"))
    with pytest.raises(seeds.SeedError) as excinfo:
        seeds.local_patterns([])
    assert "unknown bot_category" in str(excinfo.value)
    assert "needs a reason" in str(excinfo.value)


def test_a_local_pattern_upstream_now_covers_is_flagged(local_file, capsys):
    local_file(("^Java/", "automation_tool", "Java HTTP client", "Java/17"))
    upstream = [
        seeds.BotPattern("Java\\/", "automation_tool", "crawler-user-agents@x", "Java")
    ]
    (row,) = seeds.local_patterns(upstream)
    assert row == seeds.BotPattern(
        "^Java/", "automation_tool", "local", "Java HTTP client"
    )
    assert "now covered upstream" in capsys.readouterr().out


def test_the_change_summary_counts_additions_removals_and_recategorisations():
    before = [
        {"user_agent_pattern": "OldBot", "bot_category": "seo_crawler"},
        {"user_agent_pattern": "SameBot", "bot_category": "seo_crawler"},
    ]
    after = [
        seeds.BotPattern("SameBot", "monitoring", "local", "n"),
        seeds.BotPattern("NewBot", "seo_crawler", "local", "n"),
    ]
    assert seeds.summarise_changes(before, after).splitlines()[0] == (
        "2 patterns: 1 added, 1 removed, 1 recategorised"
    )


@pytest.fixture
def seed_copy(tmp_path, monkeypatch):
    """Point the seed and licence at copies, so update() can't touch the committed files."""
    seed = tmp_path / "bot_user_agent_patterns.csv"
    license_file = tmp_path / "licenses" / "crawler-user-agents.LICENSE"
    seed.write_bytes(seeds.BOT_SEED.read_bytes())
    license_file.parent.mkdir()
    license_file.write_bytes(seeds.UPSTREAM_LICENSE.read_bytes())
    monkeypatch.setattr(seeds, "BOT_SEED", seed)
    monkeypatch.setattr(seeds, "UPSTREAM_LICENSE", license_file)
    return seed, license_file


def committed_upstream_entries():
    """The committed seed's upstream rows, back in crawler-user-agents' form."""
    tag_for = {
        category: tag for tag, category in reversed(seeds.TAG_CATEGORIES.items())
    }
    return [
        {
            "pattern": row["user_agent_pattern"],
            "tags": [tag_for[row["bot_category"]]],
            "description": row["user_agent_pattern_note"],
        }
        for row in seeds.read_csv(seeds.BOT_SEED, seeds.BOT_COLUMNS)
        if row["user_agent_pattern_source"] != "local"
    ]


def test_regenerating_from_the_same_upstream_reproduces_the_seed(
    seed_copy, monkeypatch
):
    seed, license_file = seed_copy
    committed = seeds.BOT_SEED.read_bytes()
    monkeypatch.setattr(
        seeds,
        "fetch_upstream",
        lambda ref: (COMMIT, committed_upstream_entries(), "MIT licence text"),
    )
    summary = seeds.update("master")

    assert seed.read_bytes() == committed
    assert license_file.read_text() == "MIT licence text"
    assert "0 added, 0 removed, 0 recategorised" in summary


def test_a_failed_update_writes_nothing(seed_copy, monkeypatch):
    seed, license_file = seed_copy
    before = (seed.read_bytes(), license_file.read_bytes())
    duplicated = [entry("SameBot", "seo"), entry("SameBot", "monitoring")]
    monkeypatch.setattr(
        seeds, "fetch_upstream", lambda ref: (COMMIT, duplicated, "new licence")
    )

    with pytest.raises(seeds.SeedError, match="nothing written"):
        seeds.update("master")
    assert (seed.read_bytes(), license_file.read_bytes()) == before
    assert not list(seed.parent.glob("*.tmp"))
