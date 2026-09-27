with source as (

    select * from {{ source('alpha_vantage', 'economic_indicators') }}

)

select
    cast(indicator as varchar) as indicator,
    cast(name as varchar) as series_name,
    cast("interval" as varchar) as series_interval,
    cast(unit as varchar) as series_unit,
    cast("date" as date) as period_start_date,
    cast(value as double) as value,
    to_timestamp(cast(_dlt_load_id as double)) as loaded_at,
    cast(_dlt_id as varchar) as record_id

from source
