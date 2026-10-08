-- The whole portfolio, one row per trading day. Sums fct_portfolio_positions_daily; returns are
-- recomputed from the sums (not averaged), so they're weighted by position size.

with positions as (

    select * from {{ ref('fct_portfolio_positions_daily') }}

),

daily as (

    select
        trading_date,
        count(*) as position_count,
        sum(position_value) as portfolio_value,
        sum(cost_basis) as portfolio_cost_basis,
        sum(estimated_dividends) as portfolio_estimated_dividends,
        -- Audit hash: sorted, comma-separated price record ids (see CLAUDE.md, Lineage concepts)
        md5(string_agg(price_record_id, ',' order by price_record_id)) as price_record_ids_hash
    from positions
    group by trading_date

)

select
    trading_date,
    position_count,
    portfolio_value,
    portfolio_cost_basis,
    portfolio_value - portfolio_cost_basis as portfolio_unrealized_gain,
    portfolio_value / portfolio_cost_basis - 1 as portfolio_price_return,
    portfolio_estimated_dividends,
    (portfolio_value + portfolio_estimated_dividends) / portfolio_cost_basis - 1 as portfolio_total_return,
    portfolio_value / lag(portfolio_value) over (order by trading_date) - 1 as portfolio_daily_return,
    price_record_ids_hash

from daily
order by trading_date
