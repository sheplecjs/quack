with source as (

    select * from {{ source('shynet', 'daily_device_types') }}

)

select
    cast(service_uuid as varchar) as service_id,
    cast("date" as date) as traffic_date,
    cast(device_type as varchar) as device_type,
    cast(count as bigint) as session_count,
    to_timestamp(cast(_dlt_load_id as double)) as loaded_at,
    cast(_dlt_id as varchar) as record_id

from source
