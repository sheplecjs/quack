-- One row per security per trading day once it has a company version: the analyst target and forecast
-- earnings in effect that day, measured against the day's close.
--
-- Point in time: a company version counts from the trading day after it was loaded, until the day it was
-- replaced, so a figure is never used before it was known (as with available_from_date for economic data).
--
-- Forecast earnings per share come from the provider's own ratios: trailing EPS x trailing P/E is the price
-- they were calculated at, and that price / forward P/E is the forecast EPS. Measuring it against each day's
-- close then gives a daily forward P/E and earnings yield.
--
-- The earnings yield spread subtracts the var long_rate_indicator series (the 10-year Treasury yield) known
-- that day: a rough equity risk premium.

with prices as (

    select ticker_symbol, trading_date, close_price, record_id
    from {{ ref('fct_daily_prices') }}

),

companies as (

    select
        ticker_symbol,
        cast(valid_from as date) as loaded_date,
        cast(valid_to as date) as replaced_date,
        analyst_target_price,
        dividend_per_share,
        diluted_eps_ttm,
        diluted_eps_ttm * trailing_pe / nullif(forward_pe, 0) as forward_eps,
        shares_outstanding,
        record_id
    from {{ ref('dim_companies') }}

),

long_rate as (

    select trading_date, value as annual_yield, record_id
    from {{ ref('int_alpha_vantage__indicators_as_of_daily') }}
    where indicator = '{{ var("long_rate_indicator") }}'

)

select
    prices.ticker_symbol,
    prices.trading_date,
    prices.close_price,
    companies.analyst_target_price,
    companies.analyst_target_price / prices.close_price - 1 as implied_upside,
    companies.dividend_per_share,
    companies.forward_eps,
    companies.forward_eps * companies.shares_outstanding as forward_earnings,
    prices.close_price / nullif(companies.forward_eps, 0) as forward_pe_at_close,
    companies.forward_eps / nullif(companies.diluted_eps_ttm, 0) - 1 as implied_earnings_growth,
    companies.forward_eps / prices.close_price as earnings_yield,
    companies.forward_eps / prices.close_price - long_rate.annual_yield as earnings_yield_spread,
    prices.record_id as price_record_id,
    companies.record_id as company_record_id,
    long_rate.record_id as indicator_record_id

from prices
inner join companies
    on companies.ticker_symbol = prices.ticker_symbol
    and companies.loaded_date < prices.trading_date
    and (companies.replaced_date is null or prices.trading_date <= companies.replaced_date)
left join long_rate on long_rate.trading_date = prices.trading_date

order by prices.ticker_symbol, prices.trading_date
