-- One row per holding per trading day from its purchase date. Holdings come from the
-- portfolio_holdings seed; each is bought at the close of its first trading day on or after the
-- purchase date.
--
-- Dividends are ESTIMATED: shares x trailing-twelve-month dividend per share (from the company's
-- current version), accrued evenly per calendar day held. No dividend payment history is loaded.

with holdings as (

    select * from {{ ref('portfolio_holdings') }}

),

prices as (

    select * from {{ ref('fct_daily_prices') }}

),

companies as (

    select * from {{ ref('dim_companies') }}
    where is_current

),

held_prices as (

    select
        holdings.ticker_symbol,
        holdings.shares_held,
        holdings.purchase_date,
        prices.trading_date,
        prices.close_price,
        prices.record_id,
        first_value(prices.close_price) over (
            partition by holdings.ticker_symbol order by prices.trading_date
        ) as purchase_price
    from holdings
    inner join prices
        on prices.ticker_symbol = holdings.ticker_symbol
        and prices.trading_date >= holdings.purchase_date

),

positions as (

    select
        held_prices.*,
        held_prices.shares_held * held_prices.close_price as position_value,
        held_prices.shares_held * held_prices.purchase_price as cost_basis,
        coalesce(
            held_prices.shares_held * companies.dividend_per_share
            * (held_prices.trading_date - held_prices.purchase_date) / 365.0,
            0
        ) as estimated_dividends
    from held_prices
    left join companies on companies.ticker_symbol = held_prices.ticker_symbol

)

select
    ticker_symbol,
    trading_date,
    shares_held,
    purchase_date,
    purchase_price,
    close_price,
    position_value,
    cost_basis,
    position_value - cost_basis as unrealized_gain,
    close_price / purchase_price - 1 as price_return,
    estimated_dividends,
    (position_value + estimated_dividends) / cost_basis - 1 as total_return,
    position_value / sum(position_value) over (partition by trading_date) as portfolio_weight,
    record_id as price_record_id

from positions
order by ticker_symbol, trading_date
