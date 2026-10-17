with source as (

    select * from {{ source('shynet', 'daily_stats') }}

)

select
    cast(service_uuid as varchar) as service_id,
    cast("date" as date) as traffic_date,
    cast(session_count as bigint) as session_count,
    cast(hit_count as bigint) as hit_count,
    cast(bounce_rate_pct as double) / 100 as bounce_rate,
    cast(avg_session_duration as double) as avg_session_seconds,
    cast(avg_load_time as double) as avg_load_time_ms,
    cast(avg_hits_per_session as double) as avg_hits_per_session,
    to_timestamp(cast(_dlt_load_id as double)) as loaded_at,
    cast(_dlt_id as varchar) as record_id

from source
