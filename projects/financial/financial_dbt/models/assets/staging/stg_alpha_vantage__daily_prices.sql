with source as (

    select * from {{ source('alpha_vantage', 'daily_prices') }}

)

select
    cast(symbol as varchar) as ticker_symbol,
    cast("date" as date) as trading_date,
    cast(open as double) as open_price,
    cast(high as double) as high_price,
    cast(low as double) as low_price,
    cast(close as double) as close_price,
    cast(volume as bigint) as trade_volume,
    to_timestamp(cast(_dlt_load_id as double)) as loaded_at,
    cast(_dlt_id as varchar) as record_id

from source
