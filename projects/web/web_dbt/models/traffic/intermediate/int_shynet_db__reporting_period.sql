-- The days the share marts cover, per service: from the first day with sessions to the last complete day
-- before the latest load. Today (still in progress) is left out, so it can't skew a share.

with sessions as (

    select * from {{ ref('fct_sessions') }}

),

latest_load as (

    select cast(timezone('{{ var("shynet_time_zone") }}', max(loaded_at)) as date) - 1 as last_complete_date
    from sessions

)

select
    sessions.service_id,
    min(sessions.traffic_date) as period_start_date,
    any_value(latest_load.last_complete_date) as period_end_date

from sessions
cross join latest_load
group by sessions.service_id
