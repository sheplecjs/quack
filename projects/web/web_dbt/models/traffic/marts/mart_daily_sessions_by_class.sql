-- Sessions per service per day per traffic class, e.g. for charting the bot share over time.

with sessions as (

    select * from {{ ref('fct_sessions') }}

)

select
    service_id,
    traffic_date,
    traffic_class,
    count(*) as session_count,
    md5(string_agg(record_id, ',' order by record_id)) as record_ids_hash

from sessions
group by service_id, traffic_date, traffic_class
order by service_id, traffic_date, traffic_class
