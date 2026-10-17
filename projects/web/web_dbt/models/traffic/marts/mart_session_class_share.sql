-- Each traffic class's share of a service's sessions over the whole reporting period. Development sessions
-- are left out of the total. Shares only: no session counts.

with sessions as (

    select sessions.*, period.period_start_date, period.period_end_date
    from {{ ref('fct_sessions') }} as sessions
    inner join {{ ref('int_shynet_db__reporting_period') }} as period using (service_id)
    where sessions.traffic_group <> 'development'
        and sessions.traffic_date between period.period_start_date and period.period_end_date

)

select
    service_id,
    any_value(period_start_date) as period_start_date,
    any_value(period_end_date) as period_end_date,
    traffic_group,
    traffic_class,
    count(*) / sum(count(*)) over (partition by service_id) as session_share,
    md5(string_agg(record_id, ',' order by record_id)) as record_ids_hash

from sessions
group by service_id, traffic_group, traffic_class
order by service_id, traffic_class
