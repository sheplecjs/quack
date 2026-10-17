-- Each week's share of a traffic group's hits over the reporting period, per service, for the shape of hit
-- volume over time without the volume itself. Every week in the period appears for both groups, with a
-- zero share when the group had no hits. Development hits are left out. Shares only: no hit counts.

with periods as (

    select * from {{ ref('int_shynet_db__reporting_period') }}

),

hits as (

    select hits.*, cast(date_trunc('week', hits.traffic_date) as date) as week_start
    from {{ ref('fct_hits') }} as hits
    inner join periods using (service_id)
    where hits.traffic_group in ('human', 'bot')
        and hits.traffic_date between periods.period_start_date and periods.period_end_date

),

weeks as (

    select
        periods.service_id,
        weeks.week_start,
        weeks.week_start >= periods.period_start_date
            and weeks.week_start + 6 <= periods.period_end_date as is_complete_week
    from periods,
        (
            -- generate_series yields timestamps; the weeks are dates
            select cast(unnest(generate_series(
                date_trunc('week', periods.period_start_date), date_trunc('week', periods.period_end_date), interval 7 day
            )) as date) as week_start
        ) as weeks

),

groups as (

    select * from (values ('human'), ('bot')) as groups (traffic_group)

),

counts as (

    select
        service_id,
        week_start,
        traffic_group,
        count(*) as hit_count,
        md5(string_agg(record_id, ',' order by record_id)) as record_ids_hash
    from hits
    group by all

)

select
    weeks.service_id,
    weeks.week_start,
    weeks.is_complete_week,
    groups.traffic_group,
    coalesce(counts.hit_count, 0)
        / sum(coalesce(counts.hit_count, 0)) over (partition by weeks.service_id, groups.traffic_group)
        as hit_share,
    counts.record_ids_hash

from weeks
cross join groups
left join counts
    on counts.service_id = weeks.service_id
    and counts.week_start = weeks.week_start
    and counts.traffic_group = groups.traffic_group
order by weeks.service_id, weeks.week_start, groups.traffic_group
