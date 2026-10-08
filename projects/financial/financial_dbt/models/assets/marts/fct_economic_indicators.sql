select * from {{ ref('int_alpha_vantage__economic_observations') }}
order by indicator, period_start_date
