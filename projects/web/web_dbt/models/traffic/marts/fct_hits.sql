-- One row per Shynet hit (page view), with its session's traffic class and the local hour and weekday it
-- started in, for hit-level analysis.

with hits as (

    select * from {{ ref('stg_shynet_db__hits') }}

),

sessions as (

    select session_id, traffic_class, traffic_group from {{ ref('fct_sessions') }}

),

localised as (

    select
        *,
        timezone('{{ var("shynet_time_zone") }}', hit_started_at) as local_started_at
    from hits

)

select
    localised.hit_id,
    localised.session_id,
    localised.service_id,
    cast(localised.local_started_at as date) as traffic_date,
    cast(hour(localised.local_started_at) as integer) as hour_of_day,
    cast(isodow(localised.local_started_at) as integer) as day_of_week,
    localised.hit_started_at,
    localised.hit_last_seen_at,
    localised.is_initial_hit,
    localised.heartbeat_count,
    localised.tracker_type,
    localised.page_location,
    localised.hit_referrer_url,
    localised.load_time_ms,
    sessions.traffic_class,
    sessions.traffic_group,
    localised.loaded_at,
    localised.record_id

from localised
left join sessions using (session_id)
order by localised.service_id, localised.hit_started_at
