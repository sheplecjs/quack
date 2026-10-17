"""Profile a project's raw dlt datasets: load history, tables, and a column profile per table.

    uv run marimo edit notebooks/01_ingestion_profiles.py -- --project web

`--project` names a folder under data/ (the project's data/<project>/data.duckdb); without it, pick
one from the dropdown. The database is opened read-only, but DuckDB still locks the file, so close
the notebook before running the project's pipeline.
"""

import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium")

with app.setup:
    import math
    from pathlib import Path

    import altair as alt
    import duckdb
    import marimo as mo
    import polars as pl

    # The repo-level data/ folder, where each project keeps data/<project>/data.duckdb
    DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@app.cell
def _():
    mo.md("""
    # Ingestion profiles

    The raw tables each dlt pipeline has loaded into a project's local DuckDB database, as they
    land before dbt stages them.
    """)
    return


@app.cell
def _():
    projects = sorted(path.parent.name for path in DATA_DIR.glob("*/data.duckdb"))
    requested = mo.cli_args().get("project")
    mo.stop(
        not projects,
        mo.md(
            f"No project databases under `{DATA_DIR}`; run a project's pipeline first."
        ),
    )
    mo.stop(
        requested is not None and requested not in projects,
        mo.md(
            f"No database for project `{requested}`. Available: {', '.join(projects)}"
        ),
    )
    project = mo.ui.dropdown(projects, value=requested or projects[0], label="Project")
    project
    return (project,)


@app.cell
def _(project):
    db_path = DATA_DIR / project.value / "data.duckdb"
    conn = duckdb.connect(str(db_path), read_only=True)
    # A dlt dataset is a schema holding the pipeline's load log
    datasets = [
        row[0]
        for row in conn.sql(
            "select table_schema from information_schema.tables "
            "where table_name = '_dlt_loads' order by 1"
        ).fetchall()
    ]
    mo.stop(not datasets, mo.md(f"`{db_path}` has no dlt datasets."))
    dataset = mo.ui.dropdown(datasets, value=datasets[0], label="Dataset")
    dataset
    return conn, dataset


@app.cell
def _(conn, dataset):
    _loads = mo.sql(
        f"""
        select load_id, schema_name, status, inserted_at
        from "{dataset.value}"._dlt_loads
        order by inserted_at desc
        """,
        output=False,
        engine=conn,
    )
    mo.vstack([mo.md(f"## Loads into `{dataset.value}`"), _loads])
    return


@app.cell
def _(conn, dataset):
    tables = [
        row[0]
        for row in conn.execute(
            "select table_name from information_schema.tables "
            "where table_schema = ? and not starts_with(table_name, '_dlt') order by 1",
            [dataset.value],
        ).fetchall()
    ]
    mo.stop(not tables, mo.md(f"`{dataset.value}` has no tables yet."))
    _row_counts = " union all ".join(
        f"""
        select
            '{_table}' as table_name,
            count(*) as row_count,
            count(distinct _dlt_load_id) as load_count,
            to_timestamp(max(cast(_dlt_load_id as double))) as last_loaded_at
        from "{dataset.value}"."{_table}"
        """
        for _table in tables
    )
    _tables = mo.sql(
        f"select * from ({_row_counts}) order by table_name",
        output=False,
        engine=conn,
    )
    mo.vstack([mo.md(f"## Tables in `{dataset.value}`"), _tables])
    return (tables,)


@app.cell
def _(tables):
    table = mo.ui.dropdown(tables, value=tables[0], label="Table")
    table
    return (table,)


@app.cell
def _(conn, dataset, table):
    _profile = mo.sql(
        f'summarize "{dataset.value}"."{table.value}"',
        output=False,
        engine=conn,
    )
    mo.vstack(
        [
            mo.md(f"""
            ## `{dataset.value}.{table.value}`

            One row per column: type, range, distinct values (approximate) and the share of nulls.
            """),
            _profile,
        ]
    )
    return


@app.cell
def _(conn, dataset, table):
    # Numeric column -> whether it's an integer type, which gets whole-number bins
    numeric_columns = {
        name: data_type not in ("FLOAT", "DOUBLE")
        and not data_type.startswith("DECIMAL")
        for name, data_type in conn.execute(
            """
            select column_name, data_type
            from information_schema.columns
            where table_schema = ? and table_name = ?
                and not starts_with(column_name, '_dlt')
                and (data_type in ('TINYINT', 'SMALLINT', 'INTEGER', 'BIGINT', 'HUGEINT', 'UTINYINT',
                    'USMALLINT', 'UINTEGER', 'UBIGINT', 'UHUGEINT', 'FLOAT', 'DOUBLE')
                    or starts_with(data_type, 'DECIMAL'))
            order by ordinal_position
            """,
            [dataset.value, table.value],
        ).fetchall()
    }
    mo.stop(not numeric_columns, mo.md(f"`{table.value}` has no numeric columns."))
    column = mo.ui.dropdown(
        list(numeric_columns), value=next(iter(numeric_columns)), label="Numeric column"
    )
    bins = mo.ui.slider(5, 60, value=20, label="Bins", show_value=True)
    mo.vstack(
        [
            mo.md("""
            ### Numeric distributions

            Each row of the table is one sample: a day in the daily tables, an hour in an hourly one.
            """),
            mo.hstack([column, bins], justify="start"),
        ]
    )
    return bins, column, numeric_columns


@app.cell
def _(column, conn, dataset, table):
    _stats = mo.sql(
        f"""
        select
            count(*) as row_count,
            count("{column.value}") as value_count,
            count(*) - count("{column.value}") as null_count,
            count(distinct "{column.value}") as distinct_count,
            count(*) filter (where "{column.value}" = 0) as zero_count,
            min("{column.value}") as min_value,
            quantile_cont("{column.value}", 0.05) as p05,
            quantile_cont("{column.value}", 0.25) as p25,
            median("{column.value}") as median_value,
            quantile_cont("{column.value}", 0.75) as p75,
            quantile_cont("{column.value}", 0.95) as p95,
            max("{column.value}") as max_value,
            avg("{column.value}") as mean_value,
            stddev_samp("{column.value}") as stddev_value
        from "{dataset.value}"."{table.value}"
        """,
        output=False,
        engine=conn,
    )
    mo.vstack([mo.md(f"#### Summary of `{column.value}`"), _stats])
    return


@app.function
def histogram_bins(conn, source, column, is_integer, bin_count):
    """Equal-width bins over a numeric column's [min, max], with the rows in each; None if it has no values.

    Integers get whole-number bins [start, end), so a count column's bars line up with its values. A
    constant column is a single bin. Every bin is returned, including empty ones, so gaps show.
    """
    low, high = conn.sql(
        f'select min("{column}"), max("{column}") from {source}'
    ).fetchone()
    if low is None:
        return None
    if is_integer:
        width = max(1, math.ceil((high - low + 1) / bin_count))
        bin_count = math.ceil((high - low + 1) / width)
        edge_type = "bigint"
    else:
        low, high = float(low), float(high)
        width = (high - low) / bin_count or 1.0
        bin_count = bin_count if high > low else 1
        edge_type = "double"

    histogram = conn.sql(
        f"""
        with binned as (
            -- The top edge (max) belongs to the last bin
            select least(
                floor((cast("{column}" as double) - {low}) / {width}), {bin_count - 1}
            ) as bin
            from {source}
            where "{column}" is not null
        ),

        counts as (
            select bin, count(*) as row_count
            from binned
            group by bin
        ),

        bins as (
            select
                bin,
                cast({low} as {edge_type}) + bin * cast({width} as {edge_type}) as bin_start,
                cast({low} as {edge_type}) + (bin + 1) * cast({width} as {edge_type}) as bin_end
            from range({bin_count}) as r(bin)
        )

        select bins.bin_start, bins.bin_end, coalesce(counts.row_count, 0) as row_count
        from bins
        left join counts using (bin)
        order by bins.bin_start
        """
    ).pl()

    # Labels for tooltips and the table: whole numbers for integers (end inclusive), and
    # floats to the decimals that tell neighbouring bins apart
    edges = zip(histogram["bin_start"], histogram["bin_end"])
    if is_integer:
        labels = [
            f"{start:,}" if width == 1 else f"{start:,}–{end - 1:,}"
            for start, end in edges
        ]
    else:
        decimals = max(0, 1 - math.floor(math.log10(width)))
        labels = [f"{start:,.{decimals}f}–{end:,.{decimals}f}" for start, end in edges]
    return histogram.insert_column(0, pl.Series("bin_range", labels))


@app.function
def histogram_chart(histogram, column, is_integer, dark=False, height=260):
    """A single-series histogram of histogram_bins' output, with a tooltip on every bin."""
    # Series and ink tokens from the dataviz reference palette, stepped per theme
    series = "#3987e5" if dark else "#2a78d6"
    ink = "#c3c2b7" if dark else "#52514e"
    grid = "#383835" if dark else "#e4e3df"
    # One-value integer bins are drawn centred on their value, with whole-number ticks
    unit_bins = (
        is_integer and (histogram["bin_end"] - histogram["bin_start"]).max() == 1
    )
    offset = 0.5 if unit_bins else 0
    axis = alt.Axis(tickMinStep=1, format=",d") if is_integer else alt.Axis()
    base = (
        alt.Chart(histogram)
        .transform_calculate(
            x_start=f"datum.bin_start - {offset}", x_end=f"datum.bin_end - {offset}"
        )
        .encode(
            x=alt.X("x_start:Q", bin="binned", title=column, axis=axis),
            x2="x_end:Q",
        )
    )
    # Round the data end only. The explicit baseline (y2) is needed: without it, Vega-Lite drops
    # corner-radius bars that have binned x / x2 edges.
    bars = base.mark_bar(
        color=series, binSpacing=2, cornerRadiusTopLeft=4, cornerRadiusTopRight=4
    ).encode(  # ty: ignore[unresolved-attribute]
        y=alt.Y("row_count:Q", title="Rows"), y2=alt.datum(0)
    )
    # Full-height, invisible hit targets, so even a short or empty bin shows its tooltip
    targets = base.mark_bar(opacity=0, binSpacing=0).encode(  # ty: ignore[unresolved-attribute]
        y=alt.value(0),
        y2=alt.value(height),
        tooltip=[
            alt.Tooltip("bin_range:N", title=column),
            alt.Tooltip("row_count:Q", title="Rows", format=","),
        ],
    )
    return (
        alt.layer(bars, targets)
        .properties(title=f"Distribution of {column}", width="container", height=height)
        .configure_view(stroke=None)
        .configure_title(color=ink, anchor="start", fontWeight="normal")
        .configure_axis(
            labelColor=ink, titleColor=ink, gridColor=grid, domain=False, tickColor=grid
        )
    )


@app.cell
def _(bins, column, conn, dataset, numeric_columns, table):
    histogram = histogram_bins(
        conn,
        f'"{dataset.value}"."{table.value}"',
        column.value,
        numeric_columns[column.value],
        bins.value,
    )
    mo.stop(histogram is None, mo.md(f"`{column.value}` has no values to plot."))

    _chart = histogram_chart(
        histogram,
        column.value,
        numeric_columns[column.value],
        dark=mo.app_meta().theme == "dark",
    )
    mo.ui.tabs({"Histogram": _chart, "Table": histogram})
    return


@app.cell
def _(conn, dataset, table):
    _by_load = mo.sql(
        f"""
        select
            _dlt_load_id,
            to_timestamp(cast(_dlt_load_id as double)) as loaded_at,
            count(*) as row_count
        from "{dataset.value}"."{table.value}"
        group by all
        order by _dlt_load_id desc
        """,
        output=False,
        engine=conn,
    )
    mo.vstack(
        [
            mo.md("""
            ### Rows by load

            Which load last wrote each row. Upserted tables rewrite every row a run re-fetches, so
            recent rows move to the latest load.
            """),
            _by_load,
        ]
    )
    return


@app.cell
def _(conn, dataset, table):
    _sample = mo.sql(
        f'from "{dataset.value}"."{table.value}" limit 100',
        output=False,
        engine=conn,
    )
    mo.vstack([mo.md("### Sample rows"), _sample])
    return


if __name__ == "__main__":
    app.run()
