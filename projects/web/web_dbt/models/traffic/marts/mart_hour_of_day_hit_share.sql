-- Each hour of the day's share of a traffic group's hits over the reporting period, per service, in the
-- Shynet server's time zone. All 24 hours appear for both groups. Development hits are left out. Shares
-- only: no hit counts.

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

hours as (

    select periods.service_id, periods.period_start_date, periods.period_end_date, cast(hour_of_day as integer) as hour_of_day
    from periods, range(24) as hours (hour_of_day)

),

groups as (

    select * from (values ('human'), ('bot')) as groups (traffic_group)

),

counts as (

    select
        service_id,
        hour_of_day,
        traffic_group,
        count(*) as hit_count,
        md5(string_agg(record_id, ',' order by record_id)) as record_ids_hash
    from hits
    group by all

)

select
    hours.service_id,
    hours.period_start_date,
    hours.period_end_date,
    hours.hour_of_day,
    groups.traffic_group,
    coalesce(counts.hit_count, 0)
        / sum(coalesce(counts.hit_count, 0)) over (partition by hours.service_id, groups.traffic_group)
        as hour_of_day_hit_share,
    counts.record_ids_hash

from hours
cross join groups
left join counts
    on counts.service_id = hours.service_id
    and counts.hour_of_day = hours.hour_of_day
    and counts.traffic_group = groups.traffic_group
order by hours.service_id, groups.traffic_group, hours.hour_of_day
