set -euo pipefail

dbt build

# Static export: every board into one folder, so the boards' relative links
# (portfolio.html <-> asset_<ticker>.html) resolve. dct doesn't create the folder.
mkdir -p /data/report
dct render charts/portfolio.yml charts/asset_*.yml charts/data_dictionary.yml --format html --output '/data/report/{stem}.html'
dct render charts/portfolio.yml --format png --output '/data/report/portfolio.png'
