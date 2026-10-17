set -euo pipefail

dbt build

# The static docs page, as `task dbt:build` makes it: one self-contained file, with the absolute project path
# that seeds record replaced
dbt docs generate --static
mkdir -p /data/report
sed 's|"root_path": "'"$PWD"'"|"root_path": "."|g' "${DBT_TARGET_PATH:-target}/static_index.html" > /data/report/dbt_docs.html

# The same boards and formats as `task report`
bash render_reports.sh /data/report
