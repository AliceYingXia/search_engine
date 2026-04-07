# Example - 8621_c3q20

---

## Query

> If the **workato_db_table** **get_records** action changes (**table_id**/**order_by_field_id**/filters/**continuation_token**), which recipes will be affected?

---

## Ground-Truth Strong List (6 recipes)

- `136763_23098236_v2`
- `136763_61448486_v1`
- `136763_61818873_v14`
- `1672048_15022103_v41`
- `50737_56093655_v83`
- `8621_63733901_v36`

---

## hybrid retrieval: fts-english+Qwen3-Embedding-8B+instruct

### `384059_52352657_v71`

Connectors: **workato_db_table**, workato_recipe_function, workato_smart_list, workato_variable
Steps:
- trigger: workato_recipe_function / execute
  - if [and: equals_to]
    - action: workato_variable / declare_list
      fields: name, list_item_schema_json
    - if [and: present]
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - action: workato_variable / insert_to_list
        fields: location, name, list_item
      - else
        - action: **workato_db_table** / **get_records**
          fields: order_direction, limit, **table_id**, filters
        - foreach [loop]
          - action: **workato_db_table** / **get_records**
            fields: order_direction, limit, **table_id**, filters
          - action: workato_variable / insert_to_list
            fields: location, name, list_item
    - action: workato_recipe_function / return_result
      fields: result
  - if [and: equals_to]
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - action: workato_variable / declare_variable
      fields: variables
    - if [and: greater_than]
      - action: workato_variable / declare_list
        fields: name, list_item_schema_json, list_items
      - action: workato_smart_list / create_list
        fields: list_source, list_name
      - action: workato_smart_list / query_list
        fields: output_schema_by, csv, headers, col_sep, sql, result_schema_json
      - action: workato_variable / update_variables
        fields: name, new_line_number
    - action: **workato_db_table** / add_record
      fields: **table_id**, parameters
    - if [and: greater_than]
      - foreach [loop]
        - action: **workato_db_table** / upsert_record
          fields: **table_id**, primary_field_id, parameters
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - action: workato_recipe_function / return_result
      fields: result
  - if [and: equals_to]
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - if [and: equals_to]
      - action: **workato_db_table** / update_record
        fields: **table_id**, record_id, parameters
      - if [and: greater_than]
        - action: **workato_db_table** / **get_records**
          fields: order_direction, limit, **table_id**, filters
        - foreach [loop]
          - action: **workato_db_table** / delete_record
            fields: **table_id**, record_id
        - foreach [loop]
          - action: **workato_db_table** / upsert_record
            fields: **table_id**, primary_field_id, parameters
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - action: workato_recipe_function / return_result
        fields: result
      - else
        - action: workato_recipe_function / return_result
          fields: result
  - if [and: equals_to]
    - if [and: present]
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - action: **workato_db_table** / delete_record
        fields: **table_id**, record_id
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - if [and: greater_than]
        - foreach [loop]
          - action: **workato_db_table** / delete_record
            fields: **table_id**, record_id
      - action: workato_recipe_function / return_result
        fields: result
      - else
        - action: **workato_db_table** / **get_records**
          fields: order_direction, limit, **table_id**, filters
        - foreach [loop]
          - action: **workato_db_table** / delete_record
            fields: **table_id**, record_id
          - action: **workato_db_table** / **get_records**
            fields: order_direction, limit, **table_id**, filters
          - if [and: greater_than]
            - foreach [loop]
              - action: **workato_db_table** / delete_record
                fields: **table_id**, record_id
    - action: workato_recipe_function / return_result
      fields: result

### `804586_47150941_v29`

Connectors: workato_api_platform, **workato_db_table**, workato_recipe_function
Steps:
- trigger: workato_api_platform / receive_request
  - action: **workato_db_table** / **get_records**
    fields: order_direction, limit, **table_id**, filters
  - if [and: equals_to]
    - action: workato_api_platform / return_response
      fields: http_status_code
  - try [error handling]
    - action: **workato_db_table** / update_record
      fields: **table_id**, record_id, parameters
    - if [and: is_true]
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - if [and: greater_than]
        - action: **workato_db_table** / update_record
          fields: **table_id**, parameters, record_id
        - else
          - action: **workato_db_table** / add_record
            fields: **table_id**, parameters
    - foreach [loop]
      - if [and: present]
        - action: workato_recipe_function / call_recipe_async
          fields: flow_id, parameters
    - action: workato_api_platform / return_response
      fields: http_status_code, response
    - catch [error handler]
      - action: workato_api_platform / return_response
        fields: http_status_code, response

### `602425_66687816_v1`

Connectors: **workato_db_table**, workato_recipe_function, workato_workflow_task
Steps:
- trigger: workato_workflow_task / new_requests_realtime
  - action: workato_recipe_function / call_recipe
    fields: flow_id, parameters
  - if [and: present]
    - action: **workato_db_table** / update_record
      fields: **table_id**, record_id, parameters
    - action: workato_workflow_task / change_workflow_stage
      fields: project_id, record_id, workflow_stage_id
    - stop
  - action: **workato_db_table** / update_record
    fields: **table_id**, record_id, parameters
  - foreach [loop]
    - action: **workato_db_table** / add_record
      fields: **table_id**, parameters
  - action: workato_workflow_task / human_review_on_existing_record
    fields: send_email_notification, app_id, record_id, workflow_stage_id, page_id, due_in_days, name, email
  - if [and: is_true]
    - action: **workato_db_table** / update_record
      fields: **table_id**, record_id, parameters
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - foreach [loop]
      - action: **workato_db_table** / update_record
        fields: **table_id**, record_id, parameters
    - action: workato_workflow_task / change_workflow_stage
      fields: project_id, record_id, workflow_stage_id
    - action: workato_recipe_function / call_recipe_async
      fields: flow_id, parameters
    - stop
    - elsif [and: is_true]
      - action: workato_workflow_task / change_workflow_stage
        fields: project_id, record_id, workflow_stage_id
      - action: **workato_db_table** / update_record
        fields: **table_id**, record_id, parameters
    - elsif [and: is_not_true]
      - action: workato_workflow_task / change_workflow_stage
        fields: project_id, record_id, workflow_stage_id
      - action: **workato_db_table** / update_record
        fields: **table_id**, record_id, parameters

### `136763_64449339_v4`

Connectors: workato_api_connector_800229_1671762493, **workato_db_table**, workato_recipe_function, workato_variable
Steps:
- trigger: workato_recipe_function / execute
  - action: workato_api_connector_800229_1671762493 / list_object
    fields: object, per_page
  - action: workato_variable / declare_list
    fields: name, list_item_schema_json, list_items
  - repeat [loop]
    - action: workato_api_connector_800229_1671762493 / list_object
      fields: object, per_page, page
    - if [and: greater_than]
      - action: workato_variable / insert_to_list_batch
        fields: location, name, list_items
    - while_condition [and: equals_to]
  - action: workato_variable / declare_list
    fields: name, list_item_schema_json
  - action: workato_variable / declare_variable
    fields: variables
  - repeat [loop]
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters, **continuation_token**
    - if [and: greater_than]
      - action: **workato_db_table** / delete_records_batch
        fields: **table_id**, records
    - action: workato_variable / update_variables
      fields: name, table_truncation_page_token
    - while_condition [and: present]
  - action: workato_recipe_function / call_recipe
    fields: flow_id, parameters, dynamic_config
  - if [and: greater_than]
    - action: workato_variable / insert_to_list_batch
      fields: location, name, list_items
    - if [and: is_true]
      - action: workato_recipe_function / return_result
        fields: result
    - action: **workato_db_table** / create_records_batch
      fields: **table_id**, records
    - repeat [loop]
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - foreach [loop]
        - action: workato_recipe_function / call_recipe
          fields: flow_id, dynamic_config, parameters
        - if [and: greater_than]
          - action: **workato_db_table** / create_records_batch
            fields: **table_id**, records
          - action: workato_variable / insert_to_list_batch
            fields: location, name, list_items
        - try [error handling]
          - action: **workato_db_table** / delete_record
            fields: **table_id**, record_id
          - catch [error handler]
            - if [and: not_equals_to]
              - stop
      - while_condition [and: greater_than]
  - action: workato_recipe_function / return_result
    fields: result

### `973497_53963798_v104`

Connectors: json_parser, py_eval, workato_api_platform, **workato_db_table**, workato_recipe_function, workato_variable
Steps:
- trigger: workato_api_platform / receive_request
  - action: workato_variable / declare_list
    fields: name, list_item_schema_json
  - action: workato_variable / declare_variable
    fields: variables
  - try [error handling]
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - if [and: equals_to]
      - if [and: not_equals_to, not_contains, not_equals_to]
        - action: **workato_db_table** / **get_records**
          fields: order_direction, limit, **table_id**, filters
        - if [and: greater_than]
          - action: workato_variable / update_variables
            fields: name, persona_tags
          - else
            - action: **workato_db_table** / **get_records**
              fields: order_direction, limit, **table_id**, filters
            - action: workato_variable / update_variables
              fields: name, persona_tags
        - action: py_eval / invoke_custom_py_code
          fields: code, name, code_output_schema_json, code_input
        - action: workato_recipe_function / call_recipe
          fields: flow_id, parameters
        - action: workato_variable / insert_to_list_batch
          fields: location, name, list_items
        - action: workato_recipe_function / call_recipe_async
          fields: flow_id, parameters
        - action: **workato_db_table** / upsert_record
          fields: **table_id**, primary_field_id, parameters
        - else
          - action: workato_api_platform / return_response
            fields: http_status_code, response
      - else
        - action: json_parser / parse_json
          fields: sample_document, document
        - action: workato_variable / insert_to_list_batch
          fields: location, name, list_items
    - action: workato_api_platform / return_response
      fields: http_status_code, response
    - catch [error handler]
      - action: workato_api_platform / return_response
        fields: http_status_code, response

---

## dense/Qwen3-Embedding-8B+instruct

### `804586_47150941_v29`

Connectors: workato_api_platform, **workato_db_table**, workato_recipe_function
Steps:
- trigger: workato_api_platform / receive_request
  - action: **workato_db_table** / **get_records**
    fields: order_direction, limit, **table_id**, filters
  - if [and: equals_to]
    - action: workato_api_platform / return_response
      fields: http_status_code
  - try [error handling]
    - action: **workato_db_table** / update_record
      fields: **table_id**, record_id, parameters
    - if [and: is_true]
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - if [and: greater_than]
        - action: **workato_db_table** / update_record
          fields: **table_id**, parameters, record_id
        - else
          - action: **workato_db_table** / add_record
            fields: **table_id**, parameters
    - foreach [loop]
      - if [and: present]
        - action: workato_recipe_function / call_recipe_async
          fields: flow_id, parameters
    - action: workato_api_platform / return_response
      fields: http_status_code, response
    - catch [error handler]
      - action: workato_api_platform / return_response
        fields: http_status_code, response

### `384059_52352657_v71`

Connectors: **workato_db_table**, workato_recipe_function, workato_smart_list, workato_variable
Steps:
- trigger: workato_recipe_function / execute
  - if [and: equals_to]
    - action: workato_variable / declare_list
      fields: name, list_item_schema_json
    - if [and: present]
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - action: workato_variable / insert_to_list
        fields: location, name, list_item
      - else
        - action: **workato_db_table** / **get_records**
          fields: order_direction, limit, **table_id**, filters
        - foreach [loop]
          - action: **workato_db_table** / **get_records**
            fields: order_direction, limit, **table_id**, filters
          - action: workato_variable / insert_to_list
            fields: location, name, list_item
    - action: workato_recipe_function / return_result
      fields: result
  - if [and: equals_to]
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - action: workato_variable / declare_variable
      fields: variables
    - if [and: greater_than]
      - action: workato_variable / declare_list
        fields: name, list_item_schema_json, list_items
      - action: workato_smart_list / create_list
        fields: list_source, list_name
      - action: workato_smart_list / query_list
        fields: output_schema_by, csv, headers, col_sep, sql, result_schema_json
      - action: workato_variable / update_variables
        fields: name, new_line_number
    - action: **workato_db_table** / add_record
      fields: **table_id**, parameters
    - if [and: greater_than]
      - foreach [loop]
        - action: **workato_db_table** / upsert_record
          fields: **table_id**, primary_field_id, parameters
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - action: workato_recipe_function / return_result
      fields: result
  - if [and: equals_to]
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - if [and: equals_to]
      - action: **workato_db_table** / update_record
        fields: **table_id**, record_id, parameters
      - if [and: greater_than]
        - action: **workato_db_table** / **get_records**
          fields: order_direction, limit, **table_id**, filters
        - foreach [loop]
          - action: **workato_db_table** / delete_record
            fields: **table_id**, record_id
        - foreach [loop]
          - action: **workato_db_table** / upsert_record
            fields: **table_id**, primary_field_id, parameters
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - action: workato_recipe_function / return_result
        fields: result
      - else
        - action: workato_recipe_function / return_result
          fields: result
  - if [and: equals_to]
    - if [and: present]
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - action: **workato_db_table** / delete_record
        fields: **table_id**, record_id
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - if [and: greater_than]
        - foreach [loop]
          - action: **workato_db_table** / delete_record
            fields: **table_id**, record_id
      - action: workato_recipe_function / return_result
        fields: result
      - else
        - action: **workato_db_table** / **get_records**
          fields: order_direction, limit, **table_id**, filters
        - foreach [loop]
          - action: **workato_db_table** / delete_record
            fields: **table_id**, record_id
          - action: **workato_db_table** / **get_records**
            fields: order_direction, limit, **table_id**, filters
          - if [and: greater_than]
            - foreach [loop]
              - action: **workato_db_table** / delete_record
                fields: **table_id**, record_id
    - action: workato_recipe_function / return_result
      fields: result

### `69943_63763557_v15`

Connectors: **workato_db_table**, workato_genie, workato_recipe_function
Steps:
- trigger: workato_genie / start_workflow
  - action: **workato_db_table** / **get_records**
    fields: order_direction, limit, **table_id**, filters
  - if [and: equals_to]
    - action: **workato_db_table** / update_record
      fields: **table_id**, record_id, parameters
    - action: workato_recipe_function / call_recipe_async
      fields: flow_id, parameters
    - else
      - stop
  - action: workato_genie / workflow_return_result
    fields: result

### `136763_52738101_v5`

Connectors: workato_app, **workato_db_table**, workato_recipe_function
Steps:
- trigger: workato_recipe_function / execute
  - action: **workato_db_table** / **get_records**
    fields: order_direction, limit, **table_id**, filters, **order_by_field_id**
  - if [and: equals_to]
    - action: workato_app / list_jobs
      fields: status, recipe_id
    - action: workato_app / rerun_jobs
      fields: recipe_id, jobs
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters, **order_by_field_id**
    - if [and: equals_to]
      - stop
  - action: workato_recipe_function / return_result
    fields: result

### `804586_49506728_v10`

Connectors: py_eval, workato_api_platform, **workato_db_table**
Steps:
- trigger: workato_api_platform / receive_request
  - action: **workato_db_table** / **get_records**
    fields: order_direction, limit, **table_id**, filters
  - if [and: equals_to]
    - action: workato_api_platform / return_response
      fields: http_status_code
  - try [error handling]
    - action: py_eval / invoke_custom_py_code
      fields: code, name, code_input, code_output_schema_json
    - action: workato_api_platform / return_response
      fields: http_status_code, response
    - catch [error handler]
      - action: workato_api_platform / return_response
        fields: http_status_code, response

---

## keyword/ilike

### `136763_50417983_v1`

Connectors: clock, logger, **workato_db_table**, workato_list, workato_variable
Steps:
- trigger: clock / scheduled_event
  - action: workato_variable / declare_variable
    fields: variables
  - repeat [loop]
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, **order_by_field_id**, filters, **continuation_token**
    - foreach [loop]
      - if [and: greater_than]
        - action: **workato_db_table** / delete_record
          fields: **table_id**, record_id
        - action: logger / log_message
          fields: message, user_logs_enabled, log_level
        - action: workato_list / accumulate_list_items
          fields: name, list_item
    - action: workato_variable / update_variables
      fields: name, next_page_token
    - while_condition [and: present]

### `1873346_47040880_v7`

Connectors: clock, csv_parser, google_sheets, lookup_table, salesforce, slack_bot, **workato_db_table**, workato_smart_list, workato_variable
Steps:
- trigger: clock / scheduled_event
  - action: workato_variable / declare_variable
    fields: variables
  - action: lookup_table / search_entries
    fields: lookup_**table_id**, parameters
  - repeat [loop]
    - try [error handling]
      - action: slack_bot / __adhoc_http_action
        fields: mnemonic, verb, response_type, path, input, output
      - catch [error handler]
        - stop
    - action: csv_parser / create_csv_lines
      fields: create_header_line, column_separator, force_quotes, column_labels, lines
    - action: workato_smart_list / insert_rows_from_csv
      fields: file_encoded_type, col_sep, list_source, list_name, headers, csv_schema_json, primary_index, secondary_index, (+1 more)
    - action: workato_variable / update_variables
      fields: name, cursor
    - while_condition [or: present]
  - repeat [loop]
    - try [error handling]
      - action: salesforce / search_sobjects_soql
        fields: limit, sobject_name, query, table_list, field_list, offset
      - catch [error handler]
        - stop
    - action: csv_parser / create_csv_lines
      fields: create_header_line, column_separator, force_quotes, column_labels, lines
    - action: workato_smart_list / insert_rows_from_csv
      fields: file_encoded_type, headers, col_sep, list_source, list_name, csv_schema_json, primary_index, create_table_if_not_exist
    - action: workato_variable / update_variables
      fields: name, cursor
    - while_condition [and: present]
  - if [and: equals_to]
    - action: workato_smart_list / query_list
      fields: headers, col_sep, output_schema_by, csv, sql, result_schema_json
    - action: workato_smart_list / create_list
      fields: list_source, list_name, primary_index, secondary_index
  - if [and: equals_to]
    - repeat [loop]
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters, **order_by_field_id**, **continuation_token**
      - action: csv_parser / create_csv_lines
        fields: create_header_line, column_separator, force_quotes, column_labels, lines
      - action: workato_smart_list / insert_rows_from_csv
        fields: list_source, create_table_if_not_exist, file_encoded_type, col_sep, list_name, csv_schema_json, primary_index, secondary_index, (+1 more)
      - action: workato_variable / update_variables
        fields: name, cursor
      - while_condition [and: present]
    - action: workato_smart_list / query_list
      fields: output_schema_by, csv, headers, col_sep, sql, result_schema_json
  - if [and: greater_than]
    - repeat [loop]
      - try [error handling]
        - action: slack_bot / __adhoc_http_action
          fields: mnemonic, verb, request_type, response_type, path, input, output
        - catch [error handler]
          - stop
      - action: csv_parser / create_csv_lines
        fields: create_header_line, column_separator, force_quotes, column_labels, lines
      - action: workato_smart_list / insert_rows_from_csv
        fields: create_table_if_not_exist, file_encoded_type, headers, col_sep, list_source, list_name, csv_schema_json, primary_index, (+1 more)
      - action: workato_variable / update_variables
        fields: name, cursor
      - while_condition [and: present]
    - action: workato_smart_list / query_list
      fields: output_schema_by, csv, headers, col_sep, sql, result_schema_json
    - if [and: greater_than]
      - try [error handling]
        - action: google_sheets / add_row_v4_bulk
          fields: team_drives, is_top_left, spreadsheet_id, sheet_name, column_headers, rows
        - catch [error handler]
          - stop
      - action: lookup_table / update_entry
        fields: ignore_not_found, id, lookup_**table_id**, parameters

### `804586_51482000_v7`

Connectors: app_installer_connector_3165547_1715007439, file_connector, workato_api_connector_748504_1684743862, **workato_db_table**, workato_files, workato_recipe_function, workato_variable
Steps:
- trigger: workato_recipe_function / execute
  - try [error handling]
    - action: **workato_db_table** / update_record
      fields: **table_id**, record_id, parameters
    - if [and: is_true]
      - action: app_installer_connector_3165547_1715007439 / complete_package_build
        fields: resume_token, job_url, error
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - foreach [loop]
      - action: **workato_db_table** / delete_record
        fields: **table_id**, record_id
    - foreach [loop]
      - action: **workato_db_table** / upsert_record
        fields: **table_id**, primary_field_id, parameters
    - if [and: present]
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - action: **workato_db_table** / upsert_record
        fields: **table_id**, primary_field_id, parameters
    - action: workato_recipe_function / call_recipe
      fields: flow_id, parameters
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters, **order_by_field_id**
    - action: workato_variable / declare_variable
      fields: variables
    - try [error handling]
      - action: workato_files / delete_directory
        fields: directory_path
      - catch [error handler]
        - if [and: not_contains]
          - stop
    - if [and: present]
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - foreach [loop]
        - action: **workato_db_table** / delete_record
          fields: **table_id**, record_id
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
    - action: workato_files / ensure_dir_exists
      fields: directory_name, directory_path
    - action: **workato_db_table** / upsert_record
      fields: **table_id**, parameters, primary_field_id
    - action: workato_variable / update_variables
      fields: name, package_version_record_id
    - action: **workato_db_table** / update_record
      fields: **table_id**, record_id, parameters
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - foreach [loop]
      - action: **workato_db_table** / delete_record
        fields: **table_id**, record_id
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - foreach [loop]
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters, **order_by_field_id**
      - if [and: equals_to]
        - stop
      - action: **workato_db_table** / upsert_record
        fields: **table_id**, primary_field_id, parameters
    - action: workato_recipe_function / call_recipe
      fields: flow_id, parameters
    - action: workato_api_connector_748504_1684743862 / __adhoc_http_action
      fields: mnemonic, verb, response_type, path, input, output, response_headers
    - action: workato_api_connector_748504_1684743862 / __adhoc_http_action
      fields: mnemonic, verb, response_type, path, output, response_headers
    - if [and: present]
      - try [error handling]
        - action: workato_api_connector_748504_1684743862 / __adhoc_http_action
          fields: mnemonic, verb, response_type, path, output, response_headers, input
        - catch [error handler]
          - if [and: contains]
            - stop
          - stop
    - action: workato_api_connector_748504_1684743862 / list_object
      fields: object
    - action: workato_variable / declare_list
      fields: name, list_item_schema_json
    - if [and: is_true, is_not_true]
      - try [error handling]
        - action: workato_files / delete_directory
          fields: directory_path
        - catch [error handler]
          - if [and: not_contains]
            - stop
      - action: workato_files / ensure_dir_exists
        fields: directory_name, directory_path
      - action: workato_variable / insert_to_list_batch
        fields: location, name, list_items
    - if [and: greater_than]
      - action: workato_variable / insert_to_list_batch
        fields: location, name, list_items
    - if [and: greater_than]
      - action: workato_variable / insert_to_list_batch
        fields: location, name, list_items
    - if [and: greater_than]
      - action: workato_variable / insert_to_list_batch
        fields: location, name, list_items
    - if [and: greater_than]
      - action: workato_variable / insert_to_list_batch
        fields: location, name, list_items
    - if [and: greater_than]
      - action: workato_variable / insert_to_list_batch
        fields: location, name, list_items
    - if [and: greater_than]
      - action: workato_variable / insert_to_list_batch
        fields: location, name, list_items
    - if [and: greater_than]
      - action: workato_variable / insert_to_list_batch
        fields: location, name, list_items
    - if [and: greater_than]
      - action: workato_variable / insert_to_list_batch
        fields: location, name, list_items
    - action: workato_variable / declare_list
      fields: name, list_item_schema_json
    - if [and: is_true]
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
    - if [and: not_contains]
      - action: workato_variable / declare_variable
        fields: variables
      - repeat [loop]
        - action: workato_api_connector_748504_1684743862 / list_object
          fields: object, per_page, parent_id, page
        - foreach [loop]
          - if [and: equals_to]
            - action: workato_variable / update_variables
              fields: name, project_folder_name
        - while_condition [and: blank, equals_to]
      - if [and: blank]
        - stop
      - action: **workato_db_table** / upsert_record
        fields: **table_id**, parameters, primary_field_id
    - foreach [loop]
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - if [or: equals_to, not_contains]
        - action: workato_recipe_function / call_recipe
          fields: flow_id, parameters
        - if [and: greater_than]
          - action: workato_variable / insert_to_list_batch
            fields: location, name, list_items
    - action: workato_variable / declare_list
      fields: name, list_item_schema_json
    - if [and: greater_than]
      - action: workato_variable / insert_to_list_batch
        fields: location, name, list_items
    - if [and: greater_than]
      - action: workato_variable / insert_to_list_batch
        fields: location, name, list_items
    - if [and: greater_than]
      - action: workato_variable / insert_to_list_batch
        fields: location, name, list_items
    - action: workato_variable / declare_list
      fields: name, list_item_schema_json
    - if [and: greater_than]
      - action: workato_recipe_function / call_recipe
        fields: flow_id, parameters
      - action: workato_variable / insert_to_list_batch
        fields: location, name, list_items
    - foreach [loop]
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - if [and: present]
        - action: workato_variable / declare_list
          fields: name, list_item_schema_json
        - action: workato_variable / declare_variable
          fields: variables
        - repeat [loop]
          - action: **workato_db_table** / **get_records**
            fields: order_direction, limit, **table_id**, **continuation_token**, filters
          - action: workato_variable / update_variables
            fields: name, page_token
          - foreach [loop]
            - if [and: contains]
              - action: workato_variable / insert_to_list
                fields: location, name, list_item
          - while_condition [and: equals_to]
        - if [and: greater_than]
          - action: workato_recipe_function / call_recipe
            fields: flow_id, parameters
          - action: workato_variable / insert_to_list_batch
            fields: location, name, list_items
    - if [and: greater_than]
      - action: workato_api_connector_748504_1684743862 / __adhoc_http_action
        fields: mnemonic, verb, request_type, response_type, path, input, output
      - action: workato_api_connector_748504_1684743862 / export_package
        fields: id
      - action: file_connector / read_file
        fields: base64_encode, is_large, url
      - action: workato_files / store_file
        fields: is_csv_file, schema_type, csv_has_header, csv_delimiter, csv_quote, encoding, file_name, content, (+1 more)
      - action: **workato_db_table** / update_record
        fields: **table_id**, record_id, parameters
    - foreach [loop]
      - if [and: not_contains]
        - action: **workato_db_table** / delete_record
          fields: **table_id**, record_id
    - action: workato_recipe_function / call_recipe_async
      fields: flow_id, parameters
    - action: app_installer_connector_3165547_1715007439 / complete_package_build
      fields: resume_token, job_url, package_version_id
    - catch [error handler]
      - action: app_installer_connector_3165547_1715007439 / complete_package_build
        fields: resume_token, job_url, error

### `8621_63733901_v36`

Connectors: csv_parser, **workato_db_table**, workato_genie, workato_transformations, workato_variable
Steps:
- trigger: workato_genie / start_workflow
  - action: workato_variable / declare_list
    fields: list_item_schema_json, name
  - action: workato_variable / declare_variable
    fields: variables
  - repeat [loop]
    - if [and: blank, blank]
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, **order_by_field_id**, **continuation_token**
      - action: workato_variable / insert_to_list_batch
        fields: location, name, list_items
      - elsif [and: present, blank]
        - action: **workato_db_table** / **get_records**
          fields: order_direction, limit, **table_id**, **order_by_field_id**, **continuation_token**, filters
        - action: workato_variable / insert_to_list_batch
          fields: location, name, list_items
      - elsif [and: present, blank]
        - action: **workato_db_table** / **get_records**
          fields: order_direction, limit, **table_id**, **order_by_field_id**, **continuation_token**, filters
        - action: workato_variable / insert_to_list_batch
          fields: location, name, list_items
      - else
        - action: **workato_db_table** / **get_records**
          fields: order_direction, limit, **table_id**, **order_by_field_id**, **continuation_token**, filters
        - action: workato_variable / insert_to_list_batch
          fields: location, name, list_items
    - action: workato_variable / update_variables
      fields: name, token
    - while_condition [and: present]
  - action: csv_parser / create_csv_lines
    fields: create_header_line, column_separator, force_quotes, column_labels, lines
  - action: workato_transformations / query_data
    fields: output, sources, query
  - action: csv_parser / parse_csv
    fields: col_sep, skip_first_line, column_value_by, quote_char, csv_content, header_schema
  - action: workato_variable / declare_variable
    fields: variables
  - action: workato_genie / workflow_return_result
    fields: result

---

## pgfts/english

### `50737_56890803_v18`

Connectors: email, scheduler__connector_4280146_1738893942, **workato_db_table**, workato_decision_engine, workato_recipe_function, workato_variable, workato_workflow_task
Steps:
- trigger: workato_recipe_function / execute
  - try [error handling]
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - action: **workato_db_table** / update_record
      fields: **table_id**, record_id, parameters
    - action: workato_variable / declare_variable
      fields: variables
    - if [and: contains]
      - action: workato_variable / update_variables
        fields: name, year, month, quarter
      - action: workato_variable / update_variables
        fields: name, financial_quarter, financial_year
      - action: workato_recipe_function / call_recipe
        fields: flow_id, parameters
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
      - action: **workato_db_table** / update_record
        fields: **table_id**, parameters, record_id
      - action: workato_variable / update_variables
        fields: name, email_message
      - else
        - action: scheduler__connector_4280146_1738893942 / wait
          fields: time
        - action: **workato_db_table** / **get_records**
          fields: order_direction, limit, **table_id**, filters
        - foreach [loop]
          - if [and: blank]
            - action: workato_recipe_function / call_recipe
              fields: flow_id, parameters
          - action: workato_variable / update_variables
            fields: name, year, month, quarter
          - action: workato_variable / update_variables
            fields: name, financial_quarter, financial_year
          - action: **workato_db_table** / update_record
            fields: **table_id**, parameters, record_id
          - action: workato_variable / update_variables
            fields: name, email_message
    - action: email / send_mail
      fields: email_type, to, body, subject
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - if [and: contains]
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
    - action: workato_decision_engine / execute_model
      fields: model_id, input
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - action: workato_workflow_task / human_review_on_existing_record
      fields: send_email_notification, app_id, record_id, name, workflow_stage_id, due_in_days, reassignable, email
    - if [or: is_true, is_true]
      - action: workato_variable / update_variables
        fields: name, status
      - action: workato_workflow_task / change_workflow_stage
        fields: record_id, project_id, workflow_stage_id
      - else
        - action: workato_variable / update_variables
          fields: name, status
        - action: workato_workflow_task / change_workflow_stage
          fields: record_id, project_id, workflow_stage_id
    - if [and: not_equals_to]
      - action: workato_recipe_function / call_recipe
        fields: flow_id, parameters
    - if [and: present]
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, filters
    - action: **workato_db_table** / update_record
      fields: **table_id**, record_id, parameters
    - if [and: contains]
      - action: **workato_db_table** / update_record
        fields: **table_id**, record_id, parameters
      - else
        - action: **workato_db_table** / **get_records**
          fields: order_direction, limit, **table_id**, filters
        - foreach [loop]
          - action: **workato_db_table** / update_record
            fields: **table_id**, record_id, parameters
    - if [and: present]
      - action: workato_variable / update_variables
        fields: name, email_message
    - action: workato_variable / declare_variable
      fields: variables
    - action: email / send_mail
      fields: email_type, to, subject, body
    - catch [error handler]
      - stop

### `69943_59239995_v61`

Connectors: corporate_api_connector_800219_1685935602, email, **workato_db_table**, workato_recipe_function, workato_workflow_task
Steps:
- trigger: workato_workflow_task / updated_requests_realtime
  - if [and: is_true]
    - stop
  - action: workato_recipe_function / call_recipe
    fields: flow_id, parameters
  - action: **workato_db_table** / update_record
    fields: **table_id**, record_id, parameters
  - action: workato_workflow_task / human_review_on_existing_record
    fields: reassignable, app_id, record_id, workflow_stage_id, name, user_group_id, send_email_notification, due_in_days
  - action: **workato_db_table** / update_record
    fields: **table_id**, record_id, parameters
  - action: workato_workflow_task / get_requests
    fields: order_direction, limit, app_id, expires_at, creator_id, creator_email, stage_id, stage_name, (+7 more)
  - if [and: is_true]
    - action: workato_workflow_task / change_workflow_stage
      fields: project_id, record_id, workflow_stage_id
    - action: workato_recipe_function / call_recipe
      fields: flow_id, parameters
    - if [and: is_true]
      - action: **workato_db_table** / update_record
        fields: **table_id**, record_id, parameters
      - action: workato_workflow_task / change_workflow_stage
        fields: project_id, record_id, workflow_stage_id
      - else
        - action: workato_workflow_task / change_workflow_stage
          fields: project_id, record_id, workflow_stage_id
        - action: workato_recipe_function / call_recipe
          fields: flow_id, parameters
        - action: workato_workflow_task / update_request
          fields: app_id, record_id, parameters
        - action: workato_workflow_task / human_review_on_existing_record
          fields: reassignable, app_id, record_id, workflow_stage_id, name, due_in_days, send_email_notification, email
        - if [and: present]
          - action: workato_workflow_task / change_workflow_stage
            fields: project_id, record_id, workflow_stage_id
    - else
      - action: workato_workflow_task / update_request
        fields: app_id, record_id, parameters
      - action: workato_workflow_task / human_review_on_existing_record
        fields: send_email_notification, reassignable, app_id, record_id, workflow_stage_id, name, email, due_in_days
      - action: corporate_api_connector_800219_1685935602 / get_object
        fields: object, email
      - action: email / send_mail
        fields: email_type, to, subject, body

### `804586_47168222_v59`

Connectors: app_installer_connector_3165547_1715007439, engineering_open_ai_connector_3165547_1724861071, jira, json_parser, rest, **workato_db_table**, workato_recipe_function, workato_variable, workato_workflow_task
Steps:
- trigger: workato_workflow_task / new_requests_realtime
  - action: **workato_db_table** / **get_records**
    fields: order_direction, limit, **table_id**, filters
  - if [and: greater_than]
    - action: workato_workflow_task / complete_task
      fields: status, app_id, record_id, completed_by
  - if [and: equals_to, not_contains]
    - stop
  - if [and: equals_to]
    - stop
  - if [and: blank]
    - action: **workato_db_table** / update_record
      fields: **table_id**, record_id, parameters
  - action: workato_variable / declare_list
    fields: name, list_item_schema_json
  - if [and: present]
    - action: json_parser / parse_json
      fields: sample_document, document
    - action: workato_variable / insert_to_list_batch
      fields: location, name, list_items
  - if [and: is_true, not_contains]
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - action: workato_variable / insert_to_list
      fields: location, name, list_item
  - if [and: is_true, not_contains]
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - action: workato_variable / insert_to_list
      fields: location, name, list_item
  - if [and: is_true, not_contains]
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - action: workato_variable / insert_to_list
      fields: location, name, list_item
  - action: **workato_db_table** / update_record
    fields: **table_id**, record_id, parameters
  - action: workato_workflow_task / human_review_on_existing_record
    fields: app_id, record_id, workflow_stage_id, name, user_group_id, due_in_days, page_id, send_email_notification
  - if [and: is_true]
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - if [and: equals_to]
      - action: **workato_db_table** / add_record
        fields: **table_id**, parameters
    - if [and: blank]
      - action: app_installer_connector_3165547_1715007439 / create_object
        fields: object, name
      - action: app_installer_connector_3165547_1715007439 / create_object
        fields: object, api_client_id, name, api_collection_ids, active, auth_type
      - action: **workato_db_table** / update_record
        fields: **table_id**, record_id, parameters
    - if [and: blank]
      - action: jira / create_issue
        fields: project_issuetype, description, summary
      - action: workato_recipe_function / call_recipe
        fields: flow_id, parameters
      - action: **workato_db_table** / update_record
        fields: **table_id**, record_id, parameters
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - if [and: equals_to]
      - action: **workato_db_table** / add_record
        fields: **table_id**, parameters
    - if [and: equals_to, blank]
      - action: engineering_open_ai_connector_3165547_1724861071 / create_project
        fields: project_name
      - action: **workato_db_table** / update_record
        fields: **table_id**, record_id, parameters
    - action: **workato_db_table** / update_record
      fields: **table_id**, record_id, parameters
    - foreach [loop]
      - action: **workato_db_table** / upsert_record
        fields: **table_id**, primary_field_id, parameters
  - action: workato_workflow_task / human_review_on_existing_record
    fields: send_email_notification, app_id, workflow_stage_id, record_id, name, user_group_id, page_id, due_in_days, (+1 more)
  - if [and: is_true, present]
    - action: rest / make_request_v2
      fields: request_name, request, response, wait_for_response
  - action: **workato_db_table** / update_record
    fields: **table_id**, record_id, parameters
  - action: workato_workflow_task / change_workflow_stage
    fields: project_id, record_id, workflow_stage_id

### `602425_66687816_v1`

Connectors: **workato_db_table**, workato_recipe_function, workato_workflow_task
Steps:
- trigger: workato_workflow_task / new_requests_realtime
  - action: workato_recipe_function / call_recipe
    fields: flow_id, parameters
  - if [and: present]
    - action: **workato_db_table** / update_record
      fields: **table_id**, record_id, parameters
    - action: workato_workflow_task / change_workflow_stage
      fields: project_id, record_id, workflow_stage_id
    - stop
  - action: **workato_db_table** / update_record
    fields: **table_id**, record_id, parameters
  - foreach [loop]
    - action: **workato_db_table** / add_record
      fields: **table_id**, parameters
  - action: workato_workflow_task / human_review_on_existing_record
    fields: send_email_notification, app_id, record_id, workflow_stage_id, page_id, due_in_days, name, email
  - if [and: is_true]
    - action: **workato_db_table** / update_record
      fields: **table_id**, record_id, parameters
    - action: **workato_db_table** / **get_records**
      fields: order_direction, limit, **table_id**, filters
    - foreach [loop]
      - action: **workato_db_table** / update_record
        fields: **table_id**, record_id, parameters
    - action: workato_workflow_task / change_workflow_stage
      fields: project_id, record_id, workflow_stage_id
    - action: workato_recipe_function / call_recipe_async
      fields: flow_id, parameters
    - stop
    - elsif [and: is_true]
      - action: workato_workflow_task / change_workflow_stage
        fields: project_id, record_id, workflow_stage_id
      - action: **workato_db_table** / update_record
        fields: **table_id**, record_id, parameters
    - elsif [and: is_not_true]
      - action: workato_workflow_task / change_workflow_stage
        fields: project_id, record_id, workflow_stage_id
      - action: **workato_db_table** / update_record
        fields: **table_id**, record_id, parameters

### `69943_60939422_v2`

Connectors: salesforce, **workato_db_table**, workato_mapper, workato_recipe_function, workato_workflow_task
Steps:
- trigger: salesforce / new_outbound_message
  - action: **workato_db_table** / **get_records**
    fields: order_direction, limit, **table_id**, filters
  - if [and: not_equals_to]
    - foreach [loop]
      - action: salesforce / search_sobjects
        fields: limit, sobject_name, table_list, field_list, Id
      - if [and: not_equals_to]
        - if [or: equals_to, equals_to, is_true]
          - action: workato_recipe_function / call_recipe
            fields: flow_id, parameters
          - if [and: not_equals_to]
            - action: workato_mapper / map
              fields: workato_schema_id, data
            - action: **workato_db_table** / update_record
              fields: record_id, **table_id**, parameters
            - action: workato_workflow_task / change_workflow_stage
              fields: record_id, project_id, workflow_stage_id
            - action: workato_recipe_function / call_recipe
              fields: flow_id, parameters
            - action: workato_workflow_task / human_review_on_existing_record
              fields: send_email_notification, reassignable, record_id, app_id, workflow_stage_id, name, email, due_in_days
            - action: **workato_db_table** / update_record
              fields: record_id, **table_id**, parameters
            - action: workato_workflow_task / change_workflow_stage
              fields: project_id, record_id, workflow_stage_id
    - else
      - stop

---

## Source Recipe (flow\_id=63733901)

Connectors: csv_parser, **workato_db_table**, workato_genie, workato_transformations, workato_variable
Steps:
- trigger: workato_genie / start_workflow
  - action: workato_variable / declare_list
    fields: list_item_schema_json, name
  - action: workato_variable / declare_variable
    fields: variables
  - repeat [loop]
    - if [and: blank, blank]
      - action: **workato_db_table** / **get_records**
        fields: order_direction, limit, **table_id**, **order_by_field_id**, **continuation_token**
      - action: workato_variable / insert_to_list_batch
        fields: location, name, list_items
      - elsif [and: present, blank]
        - action: **workato_db_table** / **get_records**
          fields: order_direction, limit, **table_id**, **order_by_field_id**, **continuation_token**, filters
        - action: workato_variable / insert_to_list_batch
          fields: location, name, list_items
      - elsif [and: present, blank]
        - action: **workato_db_table** / **get_records**
          fields: order_direction, limit, **table_id**, **order_by_field_id**, **continuation_token**, filters
        - action: workato_variable / insert_to_list_batch
          fields: location, name, list_items
      - else
        - action: **workato_db_table** / **get_records**
          fields: order_direction, limit, **table_id**, **order_by_field_id**, **continuation_token**, filters
        - action: workato_variable / insert_to_list_batch
          fields: location, name, list_items
    - action: workato_variable / update_variables
      fields: name, token
    - while_condition [and: present]
  - action: csv_parser / create_csv_lines
    fields: create_header_line, column_separator, force_quotes, column_labels, lines
  - action: workato_transformations / query_data
    fields: output, sources, query
  - action: csv_parser / parse_csv
    fields: col_sep, skip_first_line, column_value_by, quote_char, csv_content, header_schema
  - action: workato_variable / declare_variable
    fields: variables
  - action: workato_genie / workflow_return_result
    fields: result
