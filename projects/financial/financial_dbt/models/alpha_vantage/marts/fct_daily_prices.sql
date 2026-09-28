with prices as (

    select * from {{ ref('stg_alpha_vantage__daily_prices') }}

)

select
    ticker_symbol,
    trading_date,
    open_price,
    high_price,
    low_price,
    close_price,
    trade_volume,
    close_price / lag(close_price) over by_ticker - 1 as daily_return,
    100 * close_price / first_value(close_price) over by_ticker as close_index,
    loaded_at,
    record_id

from prices
window by_ticker as (partition by ticker_symbol order by trading_date)
order by ticker_symbol, trading_date
