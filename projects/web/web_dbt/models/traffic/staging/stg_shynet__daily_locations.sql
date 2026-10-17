with source as (

    select * from {{ source('shynet', 'daily_locations') }}

)

select
    cast(service_uuid as varchar) as service_id,
    cast("date" as date) as traffic_date,
    cast({{ shynet_null('location') }} as varchar) as page_location,
    cast(count as bigint) as hit_count,
    to_timestamp(cast(_dlt_load_id as double)) as loaded_at,
    cast(_dlt_id as varchar) as record_id

from source
