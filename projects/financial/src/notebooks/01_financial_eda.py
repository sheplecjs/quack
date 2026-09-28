import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium")

with app.setup:
    import duckdb
    import marimo as mo

    conn = duckdb.connect("../../data/financial/data.duckdb")


@app.cell
def _():
    _df = mo.sql(
        """
        SELECT
           *
        FROM
            alpha_vantage_staging.daily_prices
        WHERE symbol = 'JNJ'
        ORDER BY 1
        """,
        engine=conn,  # ty: ignore[invalid-argument-type]
    )


if __name__ == "__main__":
    app.run()
