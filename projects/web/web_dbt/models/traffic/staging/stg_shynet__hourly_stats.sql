with source as (

    select * from {{ source('shynet', 'hourly_stats') }}

)

select
    cast(service_uuid as varchar) as service_id,
    cast("date" as date) as traffic_date,
    cast("hour" as timestamp with time zone) as traffic_hour,
    cast(session_count as bigint) as session_count,
    cast(hit_count as bigint) as hit_count,
    to_timestamp(cast(_dlt_load_id as double)) as loaded_at,
    cast(_dlt_id as varchar) as record_id

from source
