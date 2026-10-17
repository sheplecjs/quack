with source as (

    select * from {{ source('shynet', 'daily_browsers') }}

)

select
    cast(service_uuid as varchar) as service_id,
    cast("date" as date) as traffic_date,
    cast(browser as varchar) as browser,
    cast(count as bigint) as session_count,
    to_timestamp(cast(_dlt_load_id as double)) as loaded_at,
    cast(_dlt_id as varchar) as record_id

from source
