with trading_days as (

    select distinct trading_date from {{ ref('stg_alpha_vantage__daily_prices') }}

),

observations as (

    select * from {{ ref('int_alpha_vantage__economic_observations') }}
    where value is not null

),

trading_days_by_indicator as (

    select trading_days.trading_date, indicators.indicator
    from trading_days
    cross join (select distinct indicator from observations) as indicators

)

select
    days.trading_date,
    observations.indicator,
    observations.series_name,
    observations.series_interval,
    observations.series_unit,
    observations.period_start_date,
    observations.available_from_date,
    observations.value,
    observations.record_id

from trading_days_by_indicator as days
asof join observations
    on observations.indicator = days.indicator
    and days.trading_date >= observations.available_from_date
