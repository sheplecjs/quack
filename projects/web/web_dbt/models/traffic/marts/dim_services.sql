with services as (

    select * from {{ ref('stg_shynet__services') }}

)

select
    service_id,
    service_name,
    service_url,
    loaded_at,
    record_id

from services
order by service_name
