-- Shynet draws the hourly chart from the same sessions and hits as the day's totals, so each day's hours
-- add up to it. A mismatch means the two tables were loaded from different fetches of the day, e.g. a
-- partial `--resources` run; reloading both resources fixes it.

with hourly as (

    select
        service_id,
        traffic_date,
        sum(session_count) as session_count,
        sum(hit_count) as hit_count
    from {{ ref('fct_hourly_traffic') }}
    group by all

)

select
    daily.service_id,
    daily.traffic_date,
    daily.session_count,
    hourly.session_count as hourly_session_count,
    daily.hit_count,
    hourly.hit_count as hourly_hit_count

from {{ ref('fct_daily_traffic') }} as daily
left join hourly using (service_id, traffic_date)
where daily.session_count is distinct from coalesce(hourly.session_count, 0)
    or daily.hit_count is distinct from coalesce(hourly.hit_count, 0)
