-- One row per calendar day, with no gaps: the semantic layer's time spine and the trading calendar.
--
-- Covers every date the data uses: from the earliest economic observation or trading day to
-- calendar_future_years (a project var) past the latest trading day, so projections to a future date
-- have a calendar to land on.
--
-- A trading day is a date with a price for any loaded ticker, so market holidays come from the data.
-- The trading columns are null outside the loaded price history, where whether the market traded is
-- unknown.

with trading_days as (

    select
        trading_date,
        row_number() over (order by trading_date) as trading_day_number
    from (select distinct trading_date from {{ ref('fct_daily_prices') }})

),

bounds as (

    select
        least(
            (select min(trading_date) from trading_days),
            (select min(period_start_date) from {{ ref('fct_economic_indicators') }})
        ) as first_date,
        (select min(trading_date) from trading_days) as first_trading_date,
        (select max(trading_date) from trading_days) as last_trading_date

),

calendar as (

    select
        cast(unnest(generate_series(
            first_date,
            last_trading_date + to_years({{ var('calendar_future_years') }}),
            interval 1 day
        )) as date) as calendar_date
    from bounds

),

days as (

    select
        calendar.calendar_date,
        calendar.calendar_date between bounds.first_trading_date and bounds.last_trading_date
            as in_price_history,
        trading_days.trading_date,
        trading_days.trading_day_number
    from calendar
    cross join bounds
    left join trading_days on trading_days.trading_date = calendar.calendar_date

)

select
    calendar_date,
    case when in_price_history then trading_date is not null end as is_trading_day,
    trading_day_number,
    case when in_price_history then
        last_value(trading_date ignore nulls) over (order by calendar_date)
    end as as_of_trading_date

from days
order by calendar_date
