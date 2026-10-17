-- Each weekday's share of a traffic group's hits in an average week of the reporting period, per service.
-- Hits are averaged per occurrence of each weekday before taking shares, so a weekday that occurs once more
-- in the period doesn't look busier for it. All seven days appear for both groups. Development hits are
-- left out. Shares only: no hit counts.

with periods as (

    select * from {{ ref('int_shynet_db__reporting_period') }}

),

hits as (

    select hits.*
    from {{ ref('fct_hits') }} as hits
    inner join periods using (service_id)
    where hits.traffic_group in ('human', 'bot')
        and hits.traffic_date between periods.period_start_date and periods.period_end_date

),

-- How many times each weekday occurs in each service's period
weekdays as (

    select
        periods.service_id,
        any_value(periods.period_start_date) as period_start_date,
        any_value(periods.period_end_date) as period_end_date,
        cast(isodow(days.day) as integer) as day_of_week,
        any_value(strftime(days.day, '%A')) as day_of_week_name,
        count(*) as occurrences
    from periods,
        unnest(generate_series(periods.period_start_date, periods.period_end_date, interval 1 day)) as days (day)
    group by periods.service_id, isodow(days.day)

),

groups as (

    select * from (values ('human'), ('bot')) as groups (traffic_group)

),

counts as (

    select
        service_id,
        day_of_week,
        traffic_group,
        count(*) as hit_count,
        md5(string_agg(record_id, ',' order by record_id)) as record_ids_hash
    from hits
    group by all

),

averaged as (

    select
        weekdays.*,
        groups.traffic_group,
        coalesce(counts.hit_count, 0) / weekdays.occurrences as hits_per_occurrence,
        counts.record_ids_hash
    from weekdays
    cross join groups
    left join counts
        on counts.service_id = weekdays.service_id
        and counts.day_of_week = weekdays.day_of_week
        and counts.traffic_group = groups.traffic_group

)

select
    service_id,
    period_start_date,
    period_end_date,
    day_of_week,
    day_of_week_name,
    traffic_group,
    hits_per_occurrence / sum(hits_per_occurrence) over (partition by service_id, traffic_group)
        as day_of_week_hit_share,
    record_ids_hash

from averaged
order by service_id, traffic_group, day_of_week
