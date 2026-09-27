{#- Alpha Vantage returns text placeholders for missing values. Null exactly these before a strict
    cast, so any other unexpected value fails the build instead of silently becoming null. -#}

{% macro av_null(column_name) -%}
    nullif(nullif({{ column_name }}, 'None'), '-')
{%- endmacro %}
