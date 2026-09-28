{#-
    Compares the columns declared for a source or model (name and data_type in YAML) with the columns
    the relation actually has. Returns one row per problem:
      type_mismatch  declared and actual types differ
      missing        declared, but not in the relation
      undeclared     in the relation, but not documented
    Types are compared case-insensitively, so declare them with DuckDB's own names (varchar, not text).
    A declared column without a data_type is only checked for existence.
-#}

{% test declared_types_match(model) %}

{%- set ns = namespace(node=none, problems=[]) -%}

{%- if execute -%}
    {%- for candidate in (graph.sources.values() | list) + (graph.nodes.values() | list) -%}
        {%- set name = candidate.identifier if candidate.resource_type == 'source' else candidate.alias -%}
        {%- if name and (name | lower) == (model.identifier | lower)
            and (candidate.schema | lower) == (model.schema | lower) -%}
            {%- set ns.node = candidate -%}
        {%- endif -%}
    {%- endfor -%}
    {%- if ns.node is none -%}
        {{ exceptions.raise_compiler_error("declared_types_match: no source or model is defined for " ~ model) }}
    {%- endif -%}

    {%- set actual = {} -%}
    {%- for column in adapter.get_columns_in_relation(model) -%}
        {#- dtype is the database's own type name; data_type renders strings as character varying(256) -#}
        {%- do actual.update({column.name | lower: column.dtype | lower}) -%}
    {%- endfor -%}

    {%- set declared = {} -%}
    {%- for column in ns.node.columns.values() -%}
        {%- do declared.update({column.name | lower: (column.data_type or '') | lower}) -%}
    {%- endfor -%}

    {%- for name, declared_type in declared.items() -%}
        {%- if name not in actual -%}
            {%- do ns.problems.append([name, declared_type or none, none, 'missing']) -%}
        {%- elif declared_type and declared_type != actual[name] -%}
            {%- do ns.problems.append([name, declared_type, actual[name], 'type_mismatch']) -%}
        {%- endif -%}
    {%- endfor -%}
    {%- for name, actual_type in actual.items() if name not in declared -%}
        {%- do ns.problems.append([name, none, actual_type, 'undeclared']) -%}
    {%- endfor -%}
{%- endif -%}

{%- if ns.problems %}
select * from (values
    {%- for problem in ns.problems %}
    ({% for value in problem %}{{ "'" ~ value ~ "'" if value is not none else "null" }}{{ ", " if not loop.last }}{% endfor %}){{ "," if not loop.last }}
    {%- endfor %}
) as problems (column_name, declared_type, actual_type, issue)
{%- else %}
select
    cast(null as varchar) as column_name,
    cast(null as varchar) as declared_type,
    cast(null as varchar) as actual_type,
    cast(null as varchar) as issue
where false
{%- endif %}

{% endtest %}
