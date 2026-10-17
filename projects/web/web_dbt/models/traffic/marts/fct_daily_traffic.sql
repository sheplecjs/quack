with daily_stats as (

    select * from {{ ref('stg_shynet__daily_stats') }}

)

select
    service_id,
    traffic_date,
    session_count,
    hit_count,
    bounce_rate,
    avg_session_seconds,
    avg_load_time_ms,
    avg_hits_per_session,
    loaded_at,
    record_id

from daily_stats
order by service_id, traffic_date
