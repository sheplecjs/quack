{#- The Chrome major version current at a timestamp. Chrome 130 shipped on 2024-10-15 and Chrome ships a
    new major every four weeks, so this drifts by a version or two over the years: use it with a
    generous tolerance, not as an exact release calendar. -#}

{% macro expected_chrome_major(at) -%}
    130 + floor(datediff('day', date '2024-10-15', cast({{ at }} as date)) / 28)
{%- endmacro %}
