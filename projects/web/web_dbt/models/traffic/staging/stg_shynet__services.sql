with source as (

    select * from {{ source('shynet', 'services') }}

)

select
    cast(uuid as varchar) as service_id,
    cast(name as varchar) as service_name,
    cast({{ shynet_null('link') }} as varchar) as service_url,
    to_timestamp(cast(_dlt_load_id as double)) as loaded_at,
    cast(_dlt_id as varchar) as record_id

from source
