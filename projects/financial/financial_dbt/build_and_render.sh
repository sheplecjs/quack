set -euo pipefail

dbt build
dct render charts/analytics.yml --format html --output /data/analytics.html
