-- What kind of bots declare themselves: each bot category's share of a service's declared-bot sessions over
-- the reporting period. Shares only: no session counts.

with sessions as (

    select sessions.*, period.period_start_date, period.period_end_date
    from {{ ref('fct_sessions') }} as sessions
    inner join {{ ref('int_shynet_db__reporting_period') }} as period using (service_id)
    where sessions.traffic_class = 'declared_bot'
        and sessions.traffic_date between period.period_start_date and period.period_end_date

)

select
    service_id,
    any_value(period_start_date) as period_start_date,
    any_value(period_end_date) as period_end_date,
    bot_category,
    count(*) / sum(count(*)) over (partition by service_id) as declared_bot_session_share,
    md5(string_agg(record_id, ',' order by record_id)) as record_ids_hash

from sessions
group by service_id, bot_category
order by service_id, bot_category
