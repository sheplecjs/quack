with hourly_stats as (

    select * from {{ ref('stg_shynet__hourly_stats') }}

)

select
    service_id,
    traffic_date,
    traffic_hour,
    session_count,
    hit_count,
    loaded_at,
    record_id

from hourly_stats
order by service_id, traffic_hour
