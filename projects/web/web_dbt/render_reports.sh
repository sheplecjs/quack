# Render this project's dbt charts boards into one folder: every board as HTML, so the boards' relative
# links (traffic.html <-> data_dictionary.html) resolve, and the landing board as PNG too. Run from this
# directory with the dbt profile's environment set. Used by `task report`.
#
#   bash render_reports.sh <output folder>
set -euo pipefail

out="${1:?usage: render_reports.sh <output folder>}"
mkdir -p "$out"  # dct doesn't create it

dct render charts/traffic.yml charts/data_dictionary.yml --format html --output "$out/{stem}.html"
dct render charts/traffic.yml --format png --output "$out/{stem}.png"
