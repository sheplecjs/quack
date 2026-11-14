from financial import metrics


def test_render_writes_one_block_scalar_query_per_saved_query():
    rendered = metrics.render(
        {
            "risk_all_history": ("Risk figures, all history", "SELECT 1   \n\nFROM t"),
            "risk_by_month": ('Per "month"', "SELECT 2"),
        }
    )
    assert rendered.startswith(metrics.HEADER)
    assert (
        '  risk_all_history:\n    notes: "Risk figures, all history"\n    sql: |\n'
        in rendered
    )
    assert (
        '    notes: "Per \\"month\\""' in rendered
    )  # descriptions are JSON-quoted, so YAML-safe
    # Trailing whitespace is stripped (yamllint), and blank lines stay blank
    assert "      SELECT 1\n\n      FROM t\n" in rendered
    assert all(line == line.rstrip() for line in rendered.splitlines())


def test_load_manifest_drops_the_database_from_relations(tmp_path):
    relation = {
        "database": "data",
        "schema_name": "main",
        "alias": "fct",
        "relation_name": '"data"."main"."fct"',
    }
    path = tmp_path / "semantic_manifest.json"
    path.write_text(
        metrics.json.dumps(
            {
                "semantic_models": [{"node_relation": dict(relation)}],
                "project_configuration": {
                    "time_spines": [{"node_relation": dict(relation)}]
                },
            }
        )
    )
    manifest = metrics._load_manifest(path)
    for node_relation in (
        manifest["semantic_models"][0]["node_relation"],
        manifest["project_configuration"]["time_spines"][0]["node_relation"],
    ):
        assert node_relation["database"] is None
        assert node_relation["relation_name"] == '"main"."fct"'
