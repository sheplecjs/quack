-- Each security's daily return beside its benchmark's and the risk-free return, one row per security,
-- benchmark and trading day: the inputs to beta, alpha, correlation and the Sharpe ratio.
--
-- Every security is paired with every benchmark in the benchmarks seed except itself, on the days both
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
        securities.ticker_symbol,
        benchmarks.ticker_symbol as benchmark_ticker_symbol,
        securities.trading_date,
        securities.daily_return,
        benchmark_prices.daily_return as benchmark_daily_return,
        risk_free.annual_yield * (securities.trading_date - securities.previous_trading_date) / 365.0
            as risk_free_return,
        securities.record_id as price_record_id,
        benchmark_prices.record_id as benchmark_price_record_id,
        risk_free.record_id as indicator_record_id
    from prices as securities
    cross join benchmarks
    inner join prices as benchmark_prices
        on benchmark_prices.ticker_symbol = benchmarks.ticker_symbol
        and benchmark_prices.trading_date = securities.trading_date
        and benchmark_prices.previous_trading_date = securities.previous_trading_date
    left join risk_free on risk_free.trading_date = securities.trading_date
    where securities.ticker_symbol <> benchmarks.ticker_symbol
        and securities.daily_return is not null
        and benchmark_prices.daily_return is not null

)

select
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
    benchmark_price_record_id,
    indicator_record_id

from paired
window beta_window as (
    partition by ticker_symbol, benchmark_ticker_symbol
    order by trading_date
    rows between 59 preceding and current row
)
order by ticker_symbol, benchmark_ticker_symbol, trading_date
