with source as (

    select * from {{ source('shynet', 'daily_referrers') }}

)

select
    cast(service_uuid as varchar) as service_id,
    cast("date" as date) as traffic_date,
    cast({{ shynet_null('referrer') }} as varchar) as referrer_url,
    cast(count as bigint) as referral_count,
    to_timestamp(cast(_dlt_load_id as double)) as loaded_at,
    cast(_dlt_id as varchar) as record_id

from source
