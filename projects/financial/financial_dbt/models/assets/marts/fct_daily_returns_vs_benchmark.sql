-- Each return series' daily return beside its benchmark's and the risk-free return, one row per series,
-- benchmark and trading day: the inputs to beta, alpha, correlation and the Sharpe ratio.
--
-- A return series is a security (every loaded ticker) or the whole portfolio ('Portfolio', which can't
-- collide with a ticker: tickers are upper case). The portfolio's return is weighted by the previous
-- day's position values, over the positions held on both days, so buying a new holding isn't a gain.
--
-- Every series is paired with every benchmark in the benchmarks seed except itself, on the days both
-- returns cover the same period (the same previous close), so a day one of them missed is left out
-- rather than compared across different spans.
--
-- The risk-free return accrues the annual yield of the var risk_free_indicator series in effect on the
-- trading day over the calendar days since the previous close, so a Monday covers the weekend.

with prices as (

    select
        ticker_symbol,
        trading_date,
        lag(trading_date) over (partition by ticker_symbol order by trading_date) as previous_trading_date,
        daily_return,
        record_id
    from {{ ref('fct_daily_prices') }}

),

positions as (

    select
        trading_date,
        position_value,
        lag(position_value) over (partition by ticker_symbol order by trading_date) as previous_position_value,
        price_record_id
    from {{ ref('fct_portfolio_positions_daily') }}

),

portfolio as (

    select
        trading_date,
        lag(trading_date) over (order by trading_date) as previous_trading_date,
        daily_return,
        price_record_ids_hash
    from (
        select
            trading_date,
            sum(position_value) filter (where previous_position_value is not null)
                / sum(previous_position_value) - 1 as daily_return,
            -- Audit hash: sorted, comma-separated price record ids (see CLAUDE.md, Lineage concepts)
            md5(string_agg(price_record_id, ',' order by price_record_id)
                filter (where previous_position_value is not null)) as price_record_ids_hash
        from positions
        group by trading_date
    )

),

series as (

    select
        ticker_symbol as return_series,
        ticker_symbol,
        trading_date,
        previous_trading_date,
        daily_return,
        record_id as price_record_id,
        cast(null as varchar) as price_record_ids_hash
    from prices

    union all

    select
        'Portfolio' as return_series,
        cast(null as varchar) as ticker_symbol,
        trading_date,
        previous_trading_date,
        daily_return,
        cast(null as varchar) as price_record_id,
        price_record_ids_hash
    from portfolio

),

benchmarks as (

    select ticker_symbol from {{ ref('benchmarks') }}

),

risk_free as (

    select trading_date, value as annual_yield, record_id
    from {{ ref('int_alpha_vantage__indicators_as_of_daily') }}
    where indicator = '{{ var("risk_free_indicator") }}'

),

paired as (

    select
        series.return_series,
        series.ticker_symbol,
        benchmarks.ticker_symbol as benchmark_ticker_symbol,
        series.trading_date,
        series.daily_return,
        benchmark_prices.daily_return as benchmark_daily_return,
        risk_free.annual_yield * (series.trading_date - series.previous_trading_date) / 365.0
            as risk_free_return,
        series.price_record_id,
        series.price_record_ids_hash,
        benchmark_prices.record_id as benchmark_price_record_id,
        risk_free.record_id as indicator_record_id
    from series
    cross join benchmarks
    inner join prices as benchmark_prices
        on benchmark_prices.ticker_symbol = benchmarks.ticker_symbol
        and benchmark_prices.trading_date = series.trading_date
        and benchmark_prices.previous_trading_date = series.previous_trading_date
    left join risk_free on risk_free.trading_date = series.trading_date
    where series.return_series <> benchmarks.ticker_symbol
        and series.daily_return is not null
        and benchmark_prices.daily_return is not null

)

select
    return_series,
    ticker_symbol,
    benchmark_ticker_symbol,
    trading_date,
    daily_return,
    benchmark_daily_return,
    risk_free_return,
    case when count(*) over beta_window = 60 then
        regr_slope(daily_return - risk_free_return, benchmark_daily_return - risk_free_return) over beta_window
    end as beta_60_day,
    price_record_id,
    price_record_ids_hash,
    benchmark_price_record_id,
    indicator_record_id

from paired
window beta_window as (
    partition by return_series, benchmark_ticker_symbol
    order by trading_date
    rows between 59 preceding and current row
)
order by return_series, benchmark_ticker_symbol, trading_date
