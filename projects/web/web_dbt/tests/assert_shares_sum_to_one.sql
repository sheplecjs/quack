-- Every set of shares in the share marts covers its whole total: each sums to 1 within its denominator.

with share_totals as (

    select 'mart_session_class_share' as mart, service_id, null as share_set, sum(session_share) as total
    from {{ ref('mart_session_class_share') }}
    group by all

    union all

    select 'mart_weekly_session_class_share', service_id, cast(week_start as varchar), sum(session_share)
    from {{ ref('mart_weekly_session_class_share') }}
    group by all

    union all

    select 'mart_declared_bot_category_share', service_id, null, sum(declared_bot_session_share)
    from {{ ref('mart_declared_bot_category_share') }}
    group by all

    union all

    select 'mart_weekly_hit_share', service_id, traffic_group, sum(hit_share)
    from {{ ref('mart_weekly_hit_share') }}
    group by all

    union all

    select 'mart_hour_of_day_hit_share', service_id, traffic_group, sum(hour_of_day_hit_share)
    from {{ ref('mart_hour_of_day_hit_share') }}
    group by all

    union all

    select 'mart_day_of_week_hit_share', service_id, traffic_group, sum(day_of_week_hit_share)
    from {{ ref('mart_day_of_week_hit_share') }}
    group by all

    union all

    select 'mart_monthly_country_session_share', service_id, cast(month_start as varchar) || ' ' || traffic_group,
        sum(country_session_share)
    from {{ ref('mart_monthly_country_session_share') }}
    group by all

)

select *
from share_totals
where abs(total - 1) > 1e-9
