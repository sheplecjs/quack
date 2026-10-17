set -euo pipefail

dbt build

# The same boards and formats as `task report`
bash render_reports.sh /data/report
