with observations as (

    select * from {{ ref('stg_alpha_vantage__economic_indicators') }}

)

select
    indicator,
    series_name,
    series_interval,
    series_unit,
    period_start_date,
    cast(
        period_start_date + case series_interval
            when 'daily' then interval 1 day
            when 'weekly' then interval 7 day
            when 'monthly' then interval 1 month
            when 'quarterly' then interval 3 month
            when 'semiannual' then interval 6 month
            when 'annual' then interval 1 year
        end
    as date) as available_from_date,
    value,
    loaded_at,
    record_id

from observations
