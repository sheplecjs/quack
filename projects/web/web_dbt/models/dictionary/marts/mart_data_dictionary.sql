{#-
    The data dictionary, built from dbt's parsed graph at compile time: one row per documented column of every
    source, seed and model in this project.

    Each column's concept comes from `meta.concept`, which every concept in a domain's bank carries and which
    the YAML merge copies onto every use of it. A concept's canonical definition is taken from the models that
    use it: under Declared Divergence, models reference the bank unchanged, while sources and seeds declare
    where the raw data differs.

    The rows only change when YAML does, so rebuild this model after documentation changes.
-#}

{%- set rows = [] -%}

{%- if execute -%}

    {#- Tests per (node, column), and which columns are in one of the node's unique keys -#}
    {%- set column_tests = {} -%}
    {%- set unique_keys = [] -%}
    {%- for test in graph.nodes.values() if test.resource_type == 'test' and test.attached_node -%}
        {%- set test_name = test.test_metadata.name if test.test_metadata else test.name -%}
        {%- set kwargs = test.test_metadata.kwargs if test.test_metadata else {} -%}
        {%- set test_columns = [test.column_name] if test.column_name
            else (kwargs.get('combination_of_columns') or []) -%}
        {%- for column in test_columns -%}
            {%- set key = test.attached_node ~ '|' ~ (column | lower) -%}
            {%- if key not in column_tests -%}{%- do column_tests.update({key: []}) -%}{%- endif -%}
            {%- if test_name not in column_tests[key] -%}{%- do column_tests[key].append(test_name) -%}{%- endif -%}
            {#- A filtered unique test (e.g. one current version) isn't a key of the whole node -#}
            {%- if test_name in ('unique', 'unique_combination_of_columns') and not test.config.get('where') -%}
                {%- do unique_keys.append(key) -%}
            {%- endif -%}
        {%- endfor -%}
    {%- endfor -%}

    {%- set nodes = (graph.sources.values() | list) + (graph.nodes.values() | list) -%}
    {%- for node in nodes
        if node.resource_type in ('source', 'seed', 'model', 'snapshot') and node.package_name == project_name -%}

        {%- if node.resource_type == 'source' -%}
            {%- set node_name = node.source_name ~ '.' ~ node.name -%}
            {%- set path_parts = node.original_file_path.split('/') -%}
            {%- set layer = 'source' -%}
            {%- set relation = node.schema ~ '.' ~ node.identifier -%}
            {%- set materialization = 'source' -%}
        {%- else -%}
            {%- set node_name = node.name -%}
            {#- Seeds are described in a domain's YAML, so their domain comes from the properties file -#}
            {%- set properties_path = (node.patch_path or node.original_file_path).split('://')[-1] -%}
            {%- set path_parts = (node.original_file_path if node.resource_type == 'model' else properties_path).split('/') -%}
            {%- set layer = path_parts[2] if node.resource_type == 'model' and path_parts | length > 3
                else node.resource_type -%}
            {%- set relation = node.schema ~ '.' ~ node.alias -%}
            {%- set materialization = node.config.materialized -%}
        {%- endif -%}
        {%- set domain = path_parts[1] if path_parts | length > 2 else none -%}

        {%- set upstream = [] -%}
        {%- for parent in (node.depends_on.nodes if node.depends_on is defined else []) -%}
            {%- do upstream.append(parent.split('.')[2:] | join('.')) -%}
        {%- endfor -%}

        {%- for column in node.columns.values() -%}
            {%- set key = node.unique_id ~ '|' ~ (column.name | lower) -%}
            {%- do rows.append([
                column.meta.get('concept'),
                column.meta.get('concept_group'),
                domain,
                layer,
                node.resource_type,
                node.unique_id,
                node_name,
                relation,
                node.description,
                materialization,
                upstream | sort | join(', ') or none,
                loop.index,
                column.name,
                column.description,
                column.data_type,
                column_tests.get(key, []) | sort | join(', ') or none,
                key in unique_keys,
            ]) -%}
        {%- endfor -%}
    {%- endfor -%}

{%- endif %}

with documented_columns as (

    {%- if rows %}

    select * from (values
        {%- for row in rows %}
        ({% for value in row -%}
            {%- if value is none -%}null
            {%- elif value is sameas true -%}true
            {%- elif value is sameas false -%}false
            {%- elif value is number -%}{{ value }}
            {%- else -%}'{{ value | string | replace("'", "''") }}'
            {%- endif -%}
            {{- ", " if not loop.last -}}
        {%- endfor %}){{ "," if not loop.last }}
        {%- endfor %}
    ) as documented (
        concept, concept_group, domain, layer, resource_type, node_id, node_name, node_relation,
        node_description, materialization, upstream_nodes, column_position, column_name, column_description,
        column_data_type, column_tests, is_unique_key
    )

    {%- else %}

    {#- Parse time: no graph yet, so an empty result with the same columns -#}
    select
        null as concept, null as concept_group, null as domain, null as layer, null as resource_type,
        null as node_id, null as node_name, null as node_relation, null as node_description,
        null as materialization, null as upstream_nodes, null as column_position, null as column_name,
        null as column_description, null as column_data_type, null as column_tests, null as is_unique_key
    where false

    {%- endif %}

),

-- Each distinct way the models define a concept. Under Declared Divergence there is exactly one.
concept_variants as (

    select
        concept,
        column_description,
        lower(column_data_type) as column_data_type,
        count(*) as usages
    from documented_columns
    where resource_type = 'model' and concept is not null
    group by all

),

ranked_variants as (

    select
        *,
        row_number() over (
            partition by concept order by usages desc, column_description, column_data_type
        ) as variant_rank,
        count(*) over (partition by concept) as variant_count
    from concept_variants

),

-- Canonical definition: the most common variant, ties broken by text so the choice is stable.
-- A lone divergent model is then flagged, not the models that agree with the bank.
concepts as (

    select
        concept,
        column_description as concept_description,
        column_data_type as concept_data_type,
        variant_count > 1 as has_concept_conflict
    from ranked_variants
    where variant_rank = 1

)

select
    cast(documented_columns.concept as varchar) as concept,
    cast(documented_columns.concept_group as varchar) as concept_group,
    cast(concepts.concept_description as varchar) as concept_description,
    cast(concepts.concept_data_type as varchar) as concept_data_type,
    cast(documented_columns.domain as varchar) as domain,
    cast(documented_columns.layer as varchar) as layer,
    cast(documented_columns.resource_type as varchar) as resource_type,
    cast(documented_columns.node_id as varchar) as node_id,
    cast(documented_columns.node_name as varchar) as node_name,
    cast(documented_columns.node_relation as varchar) as node_relation,
    cast(documented_columns.node_description as varchar) as node_description,
    cast(documented_columns.materialization as varchar) as materialization,
    cast(documented_columns.upstream_nodes as varchar) as upstream_nodes,
    cast(documented_columns.column_position as integer) as column_position,
    cast(documented_columns.column_name as varchar) as column_name,
    cast(documented_columns.column_description as varchar) as column_description,
    cast(documented_columns.column_data_type as varchar) as column_data_type,
    cast(documented_columns.column_tests as varchar) as column_tests,
    cast(documented_columns.is_unique_key as boolean) as is_unique_key,
    -- Declared divergences from the concept: expected at sources and seeds, never in models
    documented_columns.column_name is distinct from documented_columns.concept as is_renamed,
    lower(documented_columns.column_data_type) is distinct from lower(concepts.concept_data_type) as is_retyped,
    documented_columns.column_description is distinct from concepts.concept_description as is_redescribed,
    coalesce(concepts.has_concept_conflict, false) as has_concept_conflict

from documented_columns
left join concepts on concepts.concept = documented_columns.concept

order by domain, concept_group, concept, resource_type, node_name
