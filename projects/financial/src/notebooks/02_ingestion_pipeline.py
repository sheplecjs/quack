import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium")

with app.setup:
    from financial.ingestion.alpha_vantage import load_alpha_vantage


@app.cell
def _():
    print(load_alpha_vantage())


if __name__ == "__main__":
    app.run()
