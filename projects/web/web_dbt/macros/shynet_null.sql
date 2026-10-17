{#- Shynet stores an empty string where a text value is unknown or absent: no referrer, no GeoIP country,
    no service link. Null exactly that before a strict cast. -#}

{% macro shynet_null(column_name) -%}
    nullif({{ column_name }}, '')
{%- endmacro %}
