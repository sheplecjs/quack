-- Each country's share of a traffic group's sessions per month, per service. The most common countries over
-- the reporting period keep their own row; the rest are grouped as Other, and sessions whose country isn't
-- known as Unknown. Every country group appears in every month a traffic group has sessions, so stacked
-- charts stay whole. Development sessions are left out. Shares only: no session counts.

with periods as (

    select * from {{ ref('int_shynet_db__reporting_period') }}

),

sessions as (

    select
        sessions.*,
        cast(date_trunc('month', sessions.traffic_date) as date) as month_start,
        periods.period_start_date,
        periods.period_end_date
    from {{ ref('fct_sessions') }} as sessions
    inner join periods using (service_id)
    where sessions.traffic_group in ('human', 'bot')
        and sessions.traffic_date between periods.period_start_date and periods.period_end_date

),

-- Countries ranked by sessions over the whole period, humans and bots together, so a country keeps the same
-- group (and color) in both
ranked_countries as (

    select
        service_id,
        visitor_country,
        row_number() over (partition by service_id order by count(*) desc, visitor_country) as country_rank
    from sessions
    where visitor_country is not null
    group by service_id, visitor_country

),

grouped as (

    select
        sessions.*,
        case
            when sessions.visitor_country is null then 'Unknown'
            when ranked_countries.country_rank <= {{ var('top_countries') }} then sessions.visitor_country
            else 'Other'
        end as country_group,
        -- Named countries by rank, then Other, then Unknown: a stable order for legends and colors
        case
            when sessions.visitor_country is null then {{ var('top_countries') }} + 2
            when ranked_countries.country_rank <= {{ var('top_countries') }} then ranked_countries.country_rank
            else {{ var('top_countries') }} + 1
        end as country_group_rank
    from sessions
    left join ranked_countries using (service_id, visitor_country)

),

months as (

    select distinct
        service_id,
        month_start,
        month_start >= period_start_date
            and last_day(month_start) <= period_end_date as is_complete_month
    from grouped

),

country_groups as (

    select distinct service_id, country_group, cast(country_group_rank as integer) as country_group_rank from grouped

),

traffic_groups as (

    select * from (values ('human'), ('bot')) as traffic_groups (traffic_group)

),

counts as (

    select
        service_id,
        month_start,
        traffic_group,
        country_group,
        count(*) as session_count,
        md5(string_agg(record_id, ',' order by record_id)) as record_ids_hash
    from grouped
    group by all

)

select
    months.service_id,
    months.month_start,
    months.is_complete_month,
    traffic_groups.traffic_group,
    country_groups.country_group,
    country_groups.country_group_rank,
    coalesce(counts.session_count, 0) / sum(coalesce(counts.session_count, 0)) over (
        partition by months.service_id, months.month_start, traffic_groups.traffic_group
    ) as country_session_share,
    counts.record_ids_hash

from months
cross join traffic_groups
inner join country_groups on country_groups.service_id = months.service_id
left join counts
    on counts.service_id = months.service_id
    and counts.month_start = months.month_start
    and counts.traffic_group = traffic_groups.traffic_group
    and counts.country_group = country_groups.country_group
-- A traffic group with no sessions in a month has no shares that month
qualify sum(coalesce(counts.session_count, 0)) over (
    partition by months.service_id, months.month_start, traffic_groups.traffic_group
) > 0
order by months.service_id, months.month_start, traffic_groups.traffic_group, country_groups.country_group
