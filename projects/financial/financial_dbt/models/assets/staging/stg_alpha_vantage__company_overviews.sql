with source as (

    select * from {{ source('alpha_vantage', 'company_overviews') }}

)

select
    -- Profile
    cast(symbol as varchar) as ticker_symbol,
    cast({{ av_null('asset_type') }} as varchar) as asset_type,
    cast({{ av_null('name') }} as varchar) as company_name,
    cast({{ av_null('description') }} as varchar) as business_description,
    cast({{ av_null('cik') }} as varchar) as central_index_key,
    cast({{ av_null('exchange') }} as varchar) as listing_exchange,
    cast({{ av_null('currency') }} as varchar) as currency,
    cast({{ av_null('country') }} as varchar) as country,
    cast({{ av_null('sector') }} as varchar) as sector,
    cast({{ av_null('industry') }} as varchar) as industry,
    cast({{ av_null('address') }} as varchar) as address,
    cast({{ av_null('official_site') }} as varchar) as official_site,
    cast({{ av_null('fiscal_year_end') }} as varchar) as fiscal_year_end,
    cast({{ av_null('latest_quarter') }} as date) as latest_quarter,

    -- Fundamentals
    cast({{ av_null('market_capitalization') }} as bigint) as market_capitalization,
    cast({{ av_null('ebitda') }} as bigint) as ebitda,
    cast({{ av_null('pe_ratio') }} as double) as pe_ratio,
    cast({{ av_null('peg_ratio') }} as double) as peg_ratio,
    cast({{ av_null('book_value') }} as double) as book_value,
    cast({{ av_null('dividend_per_share') }} as double) as dividend_per_share,
    cast({{ av_null('dividend_yield') }} as double) as dividend_yield,
    cast({{ av_null('eps') }} as double) as eps,
    cast({{ av_null('revenue_per_share_ttm') }} as double) as revenue_per_share_ttm,
    cast({{ av_null('profit_margin') }} as double) as profit_margin,
    cast({{ av_null('operating_margin_ttm') }} as double) as operating_margin_ttm,
    cast({{ av_null('return_on_assets_ttm') }} as double) as return_on_assets_ttm,
    cast({{ av_null('return_on_equity_ttm') }} as double) as return_on_equity_ttm,
    cast({{ av_null('revenue_ttm') }} as bigint) as revenue_ttm,
    cast({{ av_null('gross_profit_ttm') }} as bigint) as gross_profit_ttm,
    cast({{ av_null('diluted_epsttm') }} as double) as diluted_eps_ttm,
    cast({{ av_null('quarterly_earnings_growth_yoy') }} as double) as quarterly_earnings_growth_yoy,
    cast({{ av_null('quarterly_revenue_growth_yoy') }} as double) as quarterly_revenue_growth_yoy,
    cast({{ av_null('analyst_target_price') }} as double) as analyst_target_price,
    cast({{ av_null('analyst_rating_strong_buy') }} as integer) as analyst_rating_strong_buy,
    cast({{ av_null('analyst_rating_buy') }} as integer) as analyst_rating_buy,
    cast({{ av_null('analyst_rating_hold') }} as integer) as analyst_rating_hold,
    cast({{ av_null('analyst_rating_sell') }} as integer) as analyst_rating_sell,
    cast({{ av_null('analyst_rating_strong_sell') }} as integer) as analyst_rating_strong_sell,
    cast({{ av_null('trailing_pe') }} as double) as trailing_pe,
    cast({{ av_null('forward_pe') }} as double) as forward_pe,
    cast({{ av_null('price_to_sales_ratio_ttm') }} as double) as price_to_sales_ratio_ttm,
    cast({{ av_null('price_to_book_ratio') }} as double) as price_to_book_ratio,
    cast({{ av_null('ev_to_revenue') }} as double) as ev_to_revenue,
    cast({{ av_null('ev_to_ebitda') }} as double) as ev_to_ebitda,
    cast({{ av_null('beta') }} as double) as beta,
    cast({{ av_null('_52_week_high') }} as double) as high_52_week,
    cast({{ av_null('_52_week_low') }} as double) as low_52_week,
    cast({{ av_null('_50_day_moving_average') }} as double) as moving_average_50_day,
    cast({{ av_null('_200_day_moving_average') }} as double) as moving_average_200_day,
    cast({{ av_null('shares_outstanding') }} as bigint) as shares_outstanding,
    cast({{ av_null('shares_float') }} as bigint) as shares_float,
    cast({{ av_null('percent_insiders') }} as double) / 100 as percent_insiders,  -- 0-100 to fraction
    cast({{ av_null('percent_institutions') }} as double) / 100 as percent_institutions,  -- 0-100 to fraction
    cast({{ av_null('dividend_date') }} as date) as dividend_date,
    cast({{ av_null('ex_dividend_date') }} as date) as ex_dividend_date,

    -- Lineage
    to_timestamp(cast(_dlt_load_id as double)) as loaded_at,
    cast(_dlt_id as varchar) as record_id,

    -- Versioning (scd2)
    cast(_dlt_valid_from as timestamp with time zone) as valid_from,
    cast(_dlt_valid_to as timestamp with time zone) as valid_to

from source
