with prices as (

    select * from {{ ref('fct_daily_prices') }}

),

indicators as (

    select * from {{ ref('int_alpha_vantage__indicators_as_of_daily') }}

),

companies as (

    select * from {{ ref('dim_companies') }}
    where is_current

)

select
    prices.trading_date,
    prices.ticker_symbol,
    companies.company_name,
    companies.sector,
    companies.industry,
    prices.close_price,
    prices.trade_volume,
    prices.daily_return,
    prices.close_index,
    indicators.indicator,
    indicators.series_name,
    indicators.series_unit,
    indicators.period_start_date,
    indicators.available_from_date,
    indicators.value,
    prices.record_id as price_record_id,
    indicators.record_id as indicator_record_id

from prices
inner join indicators on indicators.trading_date = prices.trading_date
left join companies on companies.ticker_symbol = prices.ticker_symbol

order by prices.ticker_symbol, prices.trading_date, indicators.indicator
