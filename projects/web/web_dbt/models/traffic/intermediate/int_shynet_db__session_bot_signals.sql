-- One row per session with each bot signal as its own flag, and the patterns that set the
-- pattern-based ones. fct_sessions combines them into a traffic class.

with sessions as (

    select * from {{ ref('int_shynet_db__session_activity') }}

),

user_agent_patterns as (

    select * from {{ ref('bot_user_agent_patterns') }}

),

network_patterns as (

    select * from {{ ref('hosting_network_patterns') }}

),

-- The best matching pattern per user agent (not per session, so each distinct user agent is matched
-- against the patterns once): a named bot before a generic one, then alphabetical. Patterns are
-- case-sensitive, as crawler-user-agents writes them; local ones opt out with (?i).
user_agent_matches as (

    select
        user_agents.user_agent,
        first(patterns.user_agent_pattern order by patterns.bot_category = 'generic', patterns.user_agent_pattern)
            as user_agent_pattern,
        first(patterns.bot_category order by patterns.bot_category = 'generic', patterns.user_agent_pattern)
            as bot_category,
        first(patterns.user_agent_pattern_source order by patterns.bot_category = 'generic', patterns.user_agent_pattern)
            as user_agent_pattern_source,
        first(patterns.user_agent_pattern_note order by patterns.bot_category = 'generic', patterns.user_agent_pattern)
            as user_agent_pattern_note
    from (select distinct user_agent from sessions) as user_agents
    inner join user_agent_patterns as patterns
        on regexp_matches(user_agents.user_agent, patterns.user_agent_pattern)
    group by user_agents.user_agent

),

network_matches as (

    select
        networks.asn_organization,
        first(patterns.asn_pattern order by patterns.asn_pattern) as asn_pattern,
        first(patterns.network_category order by patterns.asn_pattern) as network_category,
        first(patterns.asn_pattern_source order by patterns.asn_pattern) as asn_pattern_source,
        first(patterns.asn_pattern_note order by patterns.asn_pattern) as asn_pattern_note
    from (select distinct asn_organization from sessions) as networks
    inner join network_patterns as patterns
        on regexp_matches(networks.asn_organization, patterns.asn_pattern, 'i')
    group by networks.asn_organization

),

sessions_in_context as (

    select
        *,
        -- Sessions on this service with this user agent on this network within 10 minutes either
        -- side. Shynet merges an IP address's hits on a service into one session for 30 minutes, so
        -- these came from different addresses. (Sessions are per service: one visitor on several
        -- sites makes one session on each, which mustn't count as a burst.)
        count(*) over (
            partition by service_id, user_agent, asn_organization
            order by session_started_at
            range between interval 10 minutes preceding and interval 10 minutes following
        ) as nearby_session_count,
        -- regexp_extract returns '' without a match
        cast(nullif(regexp_extract(user_agent, '(?:Chrome|CriOS)/(\d+)\.', 1), '') as integer) as chrome_major
    from sessions

)

select
    sessions_in_context.session_id,
    user_agent_matches.user_agent_pattern,
    user_agent_matches.user_agent_pattern_source,
    user_agent_matches.user_agent_pattern_note,
    case
        when user_agent_matches.bot_category is not null then user_agent_matches.bot_category
        when sessions_in_context.device_type = 'ROBOT' then 'other'
    end as bot_category,
    network_matches.asn_pattern,
    network_matches.asn_pattern_source,
    network_matches.asn_pattern_note,
    network_matches.network_category,
    user_agent_matches.user_agent_pattern is not null or sessions_in_context.device_type = 'ROBOT' as is_declared_bot,
    network_matches.asn_pattern is not null as is_hosting_network,
    sessions_in_context.session_hit_count > 0
        and sessions_in_context.pixel_hit_count = sessions_in_context.session_hit_count as is_pixel_only,
    coalesce(
        (
            sessions_in_context.browser in ('Chrome', 'Chrome Mobile', 'Chrome Mobile iOS')
            and sessions_in_context.chrome_major
                < {{ expected_chrome_major('sessions_in_context.session_started_at') }} - {{ var('outdated_chrome_releases') }}
        )
        or regexp_matches(lower(sessions_in_context.user_agent), 'msie |trident/'),
        false
    ) as is_outdated_browser,
    sessions_in_context.user_agent is null
        or length(sessions_in_context.user_agent) < 30
        or not contains(sessions_in_context.user_agent, '(') as is_malformed_user_agent,
    sessions_in_context.nearby_session_count >= 3 as is_burst_session,
    sessions_in_context.session_hit_count = 1
        and sessions_in_context.session_heartbeat_count = 0 as is_no_engagement,
    sessions_in_context.loaded_at,
    sessions_in_context.record_id

from sessions_in_context
left join user_agent_matches using (user_agent)
left join network_matches using (asn_organization)
