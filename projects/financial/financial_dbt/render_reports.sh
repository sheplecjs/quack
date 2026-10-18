# Render this project's dbt charts boards into one folder: every board as HTML, so the boards' relative
# links (portfolio.html <-> asset_<ticker>.html, data_dictionary.html) resolve, and the landing board as
# PNG too. Run from this directory with the dbt profile's environment set. Used by `task report` and the
# image's render step (the root Dockerfile and src/quack/stacks/project_pipeline.py).
#
#   bash render_reports.sh <output folder>
set -euo pipefail

out="${1:?usage: render_reports.sh <output folder>}"
mkdir -p "$out"  # dct doesn't create it

dct render charts/portfolio.yml charts/asset_*.yml charts/data_dictionary.yml --format html --output "$out/{stem}.html"
dct render charts/portfolio.yml --format png --output "$out/{stem}.png"
