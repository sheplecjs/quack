select
    *,
    valid_to is null as is_current

from {{ ref('stg_alpha_vantage__company_overviews') }}

order by ticker_symbol, valid_from
