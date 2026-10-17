-- One row per session with what its hits show: how many, how long the pages stayed open, which
-- tracker recorded them, where the visit landed and whether it was local development.

with sessions as (

    select * from {{ ref('stg_shynet_db__sessions') }}

),

hits as (

    select * from {{ ref('stg_shynet_db__hits') }}

),

activity as (

    select
        session_id,
        count(*) as session_hit_count,
        cast(sum(heartbeat_count) as bigint) as session_heartbeat_count,
        count(*) filter (where tracker_type = 'PIXEL') as pixel_hit_count,
        -- The first hit's values, keeping nulls (arg_min would skip to a later hit's referrer)
        arg_min_null(page_location, (hit_started_at, hit_id)) as landing_page_location,
        arg_min_null(hit_referrer_url, (hit_started_at, hit_id)) as referrer_url,
        coalesce(
            bool_or(regexp_matches(page_location, '^(https?://(localhost|127\.\d+\.\d+\.\d+|0\.0\.0\.0|\[::1\])[:/]|file:)')),
            false
        ) as is_development_session,
        md5(string_agg(record_id, ',' order by record_id)) as hit_record_ids_hash
    from hits
    group by session_id

)

select
    sessions.session_id,
    sessions.service_id,
    sessions.session_started_at,
    sessions.session_last_seen_at,
    epoch(sessions.session_last_seen_at - sessions.session_started_at) as session_duration_seconds,
    sessions.user_agent,
    sessions.browser,
    sessions.device,
    sessions.device_type,
    sessions.operating_system,
    sessions.asn_organization,
    sessions.visitor_country,
    sessions.visitor_time_zone,
    sessions.is_bounce,
    coalesce(activity.session_hit_count, 0) as session_hit_count,
    coalesce(activity.session_heartbeat_count, 0) as session_heartbeat_count,
    coalesce(activity.pixel_hit_count, 0) as pixel_hit_count,
    activity.landing_page_location,
    activity.referrer_url,
    coalesce(activity.is_development_session, false) as is_development_session,
    sessions.loaded_at,
    sessions.record_id,
    activity.hit_record_ids_hash

from sessions
left join activity using (session_id)
