-- The database's sessions, counted per day in var('shynet_time_zone'), should match the dashboard API's
-- daily session_count. A mismatch on complete days means the time zone var differs from the Shynet
-- server's TIME_ZONE (or one source is stale). Today and yesterday are skipped: either source can
-- be mid-day.

with database_days as (

    select service_id, traffic_date, sum(session_count) as session_count
    from {{ ref('mart_daily_sessions_by_class') }}
    group by all

),

api_days as (

    select service_id, traffic_date, session_count
    from {{ ref('fct_daily_traffic') }}

)

select
    api_days.service_id,
    api_days.traffic_date,
    api_days.session_count as api_session_count,
    coalesce(database_days.session_count, 0) as database_session_count

from api_days
left join database_days using (service_id, traffic_date)
where api_days.traffic_date < current_date - 1
    and api_days.session_count <> coalesce(database_days.session_count, 0)
