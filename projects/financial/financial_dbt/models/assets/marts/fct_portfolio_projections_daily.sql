-- One row per holding, trading day and projection horizon (the projection_horizons seed): what the position
-- would be worth, and earn in dividends, at the horizon if its analyst target is reached.
--
-- Analyst targets look 12 months ahead, so the implied return is compounded to each horizon at a steady
-- rate: close x (target / close) ^ (months / 12). A 24-month horizon extends that rate past the target.
-- Dividends accrue at the current yearly dividend per share. These are projections, not forecasts of the
-- provider's own.

with positions as (

    select ticker_symbol, trading_date, shares_held, close_price, position_value, price_record_id
    from {{ ref('fct_portfolio_positions_daily') }}

),

targets as (

    select ticker_symbol, trading_date, analyst_target_price, dividend_per_share, company_record_id
    from {{ ref('fct_price_targets_daily') }}

),

horizons as (

    select horizon_months from {{ ref('projection_horizons') }}

),

projected as (

    select
        positions.ticker_symbol,
        positions.trading_date,
        horizons.horizon_months,
        cast(positions.trading_date + to_months(horizons.horizon_months) as date) as horizon_date,
        positions.shares_held,
        positions.close_price,
        positions.position_value,
        targets.analyst_target_price,
        positions.close_price
            * power(targets.analyst_target_price / positions.close_price, horizons.horizon_months / 12.0)
            as projected_price,
        coalesce(positions.shares_held * targets.dividend_per_share * horizons.horizon_months / 12.0, 0)
            as projected_dividends,
        positions.price_record_id,
        targets.company_record_id
    from positions
    inner join targets
        on targets.ticker_symbol = positions.ticker_symbol
        and targets.trading_date = positions.trading_date
    cross join horizons

)

select
    ticker_symbol,
    trading_date,
    horizon_months,
    horizon_date,
    shares_held,
    close_price,
    position_value,
    analyst_target_price,
    projected_price,
    shares_held * projected_price as projected_position_value,
    shares_held * projected_price - position_value as projected_price_gain,
    projected_dividends,
    (shares_held * projected_price - position_value + projected_dividends) / position_value
        as projected_total_return,
    price_record_id,
    company_record_id

from projected
order by ticker_symbol, trading_date, horizon_months
