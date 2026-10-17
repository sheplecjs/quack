with source as (

    select * from {{ source('shynet_db', 'sessions') }}

)

select
    cast(uuid as varchar) as session_id,
    cast(service_id as varchar) as service_id,
    cast(start_time as timestamp with time zone) as session_started_at,
    cast(last_seen as timestamp with time zone) as session_last_seen_at,
    cast(user_agent as varchar) as user_agent,
    cast(browser as varchar) as browser,
    cast(device as varchar) as device,
    cast(device_type as varchar) as device_type,
    cast(os as varchar) as operating_system,
    cast({{ shynet_null('asn') }} as varchar) as asn_organization,
    cast({{ shynet_null('country') }} as varchar) as visitor_country,
    cast({{ shynet_null('time_zone') }} as varchar) as visitor_time_zone,
    cast(is_bounce as boolean) as is_bounce,
    to_timestamp(cast(_dlt_load_id as double)) as loaded_at,
    cast(_dlt_id as varchar) as record_id

from source
