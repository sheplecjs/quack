import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium")

with app.setup:
    import marimo as mo
    from financial import pipelines


@app.cell
def _():
    pipelines.main()
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
