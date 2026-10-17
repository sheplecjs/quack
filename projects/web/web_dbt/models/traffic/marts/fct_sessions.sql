-- One row per Shynet session, with its activity, each bot signal, and a traffic class. The class is
-- a heuristic: see the traffic_class concept for how it's decided and what it can't see.

with sessions as (

    select * from {{ ref('int_shynet_db__session_activity') }}

),

signals as (

    select * from {{ ref('int_shynet_db__session_bot_signals') }}

),

classified as (

    select
        sessions.*,
        signals.bot_category,
        signals.network_category,
        signals.is_declared_bot,
        signals.is_hosting_network,
        signals.is_pixel_only,
        signals.is_outdated_browser,
        signals.is_malformed_user_agent,
        signals.is_burst_session,
        signals.is_no_engagement,
        nullif(concat_ws(', ',
            case when signals.is_declared_bot then 'declared_bot' end,
            case when signals.is_pixel_only then 'pixel_only' end,
            case when signals.is_outdated_browser then 'outdated_browser' end,
            case when signals.is_malformed_user_agent then 'malformed_user_agent' end,
            case when signals.is_hosting_network then 'hosting_network' end,
            case when signals.is_burst_session then 'burst' end,
            case when signals.is_no_engagement then 'no_engagement' end
        ), '') as bot_signals,
        case
            when sessions.is_development_session then 'development'
            when signals.is_declared_bot then 'declared_bot'
            -- One strong signal, or a moderate signal backed by another
            when signals.is_pixel_only or signals.is_outdated_browser or signals.is_malformed_user_agent
                or (signals.is_hosting_network and (signals.is_burst_session or signals.is_no_engagement))
                or (signals.is_burst_session and signals.is_no_engagement)
                then 'likely_bot'
            when signals.is_hosting_network or signals.is_burst_session then 'possible_bot'
            else 'human'
        end as traffic_class
    from sessions
    inner join signals using (session_id)

)

select
    session_id,
    service_id,
    cast(timezone('{{ var("shynet_time_zone") }}', session_started_at) as date) as traffic_date,
    session_started_at,
    session_last_seen_at,
    session_duration_seconds,
    user_agent,
    browser,
    device,
    device_type,
    operating_system,
    asn_organization,
    visitor_country,
    visitor_time_zone,
    is_bounce,
    session_hit_count,
    session_heartbeat_count,
    pixel_hit_count,
    landing_page_location,
    referrer_url,
    traffic_class,
    case
        when traffic_class in ('declared_bot', 'likely_bot', 'possible_bot') then 'bot'
        else traffic_class
    end as traffic_group,
    bot_signals,
    bot_category,
    network_category,
    is_development_session,
    is_declared_bot,
    is_pixel_only,
    is_outdated_browser,
    is_malformed_user_agent,
    is_hosting_network,
    is_burst_session,
    is_no_engagement,
    loaded_at,
    record_id,
    hit_record_ids_hash

from classified
order by service_id, session_started_at
