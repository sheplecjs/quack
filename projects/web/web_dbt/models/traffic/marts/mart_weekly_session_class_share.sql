-- Each traffic class's share of a service's sessions per week (Monday start), with every class present in
-- every week that has sessions, so stacked charts don't break. Development sessions are left out of the
-- total. Shares only: no session counts.

with sessions as (

    select
        sessions.*,
        cast(date_trunc('week', sessions.traffic_date) as date) as week_start,
        period.period_start_date,
        period.period_end_date
    from {{ ref('fct_sessions') }} as sessions
    inner join {{ ref('int_shynet_db__reporting_period') }} as period using (service_id)
    where sessions.traffic_group <> 'development'
        and sessions.traffic_date between period.period_start_date and period.period_end_date

),

weeks as (

    select distinct service_id, week_start, period_start_date, period_end_date
    from sessions

),

classes as (

    select * from (values
        ('bot', 'declared_bot'), ('bot', 'likely_bot'), ('bot', 'possible_bot'), ('human', 'human')
    ) as classes (traffic_group, traffic_class)

),

counts as (

    select
        service_id,
        week_start,
        traffic_class,
        count(*) as session_count,
        md5(string_agg(record_id, ',' order by record_id)) as record_ids_hash
    from sessions
    group by all

)

select
    weeks.service_id,
    weeks.week_start,
    weeks.week_start >= weeks.period_start_date
        and weeks.week_start + 6 <= weeks.period_end_date as is_complete_week,
    classes.traffic_group,
    classes.traffic_class,
    coalesce(counts.session_count, 0)
        / sum(coalesce(counts.session_count, 0)) over (partition by weeks.service_id, weeks.week_start)
        as session_share,
    counts.record_ids_hash

from weeks
cross join classes
left join counts
    on counts.service_id = weeks.service_id
    and counts.week_start = weeks.week_start
    and counts.traffic_class = classes.traffic_class
order by weeks.service_id, weeks.week_start, classes.traffic_class
