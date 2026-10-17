with source as (

    select * from {{ source('shynet_db', 'hits') }}

)

select
    cast(id as bigint) as hit_id,
    cast(session_id as varchar) as session_id,
    cast(service_id as varchar) as service_id,
    cast(initial as boolean) as is_initial_hit,
    cast(start_time as timestamp with time zone) as hit_started_at,
    cast(last_seen as timestamp with time zone) as hit_last_seen_at,
    cast(heartbeats as bigint) as heartbeat_count,
    cast(tracker as varchar) as tracker_type,
    cast({{ shynet_null('location') }} as varchar) as page_location,
    cast({{ shynet_null('referrer') }} as varchar) as hit_referrer_url,
    cast(load_time as double) as load_time_ms,
    to_timestamp(cast(_dlt_load_id as double)) as loaded_at,
    cast(_dlt_id as varchar) as record_id

from source
