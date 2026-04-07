# Example - 804586_c3q10

---

## Query

> Which recipes depend on the **workato_go_connector_3535597_1749827549** **send_message** action (fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate)?

---

## Ground-Truth Strong List (1 recipes)

- `804586_63319297_v11`

---

## hybrid retrieval: fts-english+Qwen3-Embedding-8B+instruct

### `804586_63319297_v11`

Connectors: work_genie_connector_3535597_1715305794, workato_files, **workato_go_connector_3535597_1749827549**
Steps:
- trigger: work_genie_connector_3535597_1715305794 / process_event
  - if [and: equals_to, equals_to]
    - foreach [loop]
      - if [and: present]
        - action: **workato_go_connector_3535597_1749827549** / **send_message**
          fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
      - if [and: present]
        - action: workato_files / create_shareable_link
          fields: scope, file_path
        - action: **workato_go_connector_3535597_1749827549** / **send_message**
          fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
  - if [and: equals_to]
    - action: work_genie_connector_3535597_1715305794 / get_process_action
      fields: function_type_id, function_id
    - if [and: equals_to]
      - action: **workato_go_connector_3535597_1749827549** / **send_message**
        fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
    - if [and: equals_to]
      - action: **workato_go_connector_3535597_1749827549** / **send_message**
        fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
    - if [and: equals_to]
      - action: **workato_go_connector_3535597_1749827549** / **send_message**
        fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
  - action: work_genie_connector_3535597_1715305794 / acknowledge_process_event
    fields: function_type_id, result

### `3000083_51901364_v24`

Connectors: csv_parser, email, google_drive, google_sheets, json_parser, logger, lookup_table, open_ai, py_eval, salesforce, slack_bot, workato_db_table, workato_list, workato_recipe_function, workato_variable, workato_workflow_task
Steps:
- trigger: workato_workflow_task / new_requests_realtime
  - action: workato_variable / declare_variable
    fields: variables
  - action: slack_bot / get_user_by_email
    fields: email
  - if [and: present]
    - try [error handling]
      - action: salesforce / search_sobjects
        fields: limit, sobject_name, Id, table_list, field_list
      - action: workato_variable / declare_variable
        fields: variables
      - action: workato_variable / update_variables
        fields: name, segment
      - action: salesforce / search_sobjects
        fields: sobject_name, limit, field_list, Email
      - if [and: not_equals_to]
        - action: workato_variable / declare_variable
          fields: variables
        - action: salesforce / search_sobjects
          fields: limit, sobject_name, Id, field_list
        - if [and: not_equals_to]
          - action: slack_bot / get_user_by_email
            fields: email
          - action: slack_bot / post_bot_message
            fields: channel, message
      - catch [error handler]
        - action: workato_variable / update_variables
          fields: user_error_message, name, user_error_**message_body**, error_message
        - action: workato_recipe_function / call_recipe
          fields: flow_id, parameters
        - stop
    - if [and: present]
      - action: workato_workflow_task / update_request
        fields: app_id, record_id, parameters, workflow_stage_id
      - else
        - action: workato_variable / update_variables
          fields: user_error_message, name, user_error_**message_body**, error_message
        - action: workato_recipe_function / call_recipe
          fields: flow_id, parameters
        - stop
  - if [and: contains]
    - try [error handling]
      - action: workato_workflow_task / update_request
        fields: app_id, record_id, workflow_stage_id
      - action: slack_bot / post_bot_message
        fields: channel, message
      - action: py_eval / invoke_custom_py_code
        fields: code, name, code_input, code_output_schema_json
      - action: google_drive / __adhoc_http_action
        fields: mnemonic, verb, request_type, response_type, path, input, output, request_headers, (+1 more)
      - action: google_drive / __adhoc_http_action
        fields: mnemonic, verb, response_type, response_headers, path
      - action: csv_parser / parse_csv
        fields: col_sep, skip_first_line, column_value_by, quote_char, csv_content, header_schema
      - action: open_ai / chat_completion
        fields: message_type, messages, model
      - action: json_parser / parse_json
        fields: sample_document, document
      - action: slack_bot / post_bot_message
        fields: channel, text
      - action: workato_variable / declare_variable
        fields: variables
      - try [error handling]
        - foreach [loop]
          - if [and: present]
            - action: workato_variable / declare_variable
              fields: variables
            - action: lookup_table / search_entries
              fields: parameters, lookup_table_id
            - if [and: blank]
              - action: workato_recipe_function / call_recipe
                fields: flow_id, parameters
              - action: workato_list / accumulate_list_items
                fields: name, list_item
              - action: workato_variable / update_variables
                fields: name, total_questions, total_answers, total_ai_answers
        - catch [error handler]
          - action: workato_variable / update_variables
            fields: user_error_message, name, user_error_**message_body**, error_message
          - action: workato_recipe_function / call_recipe
            fields: flow_id, parameters
          - action: workato_workflow_task / update_request
            fields: app_id, record_id, workflow_stage_id, parameters
          - stop
      - action: google_drive / copy_file
        fields: fileId, name, parents
      - action: google_drive / copy_file
        fields: fileId, name, parents
      - action: google_sheets / __adhoc_http_action
        fields: mnemonic, request_type, response_type, verb, path, input, output, response_headers
      - action: workato_variable / declare_variable
        fields: variables
      - action: workato_db_table / add_record
        fields: table_id, parameters
      - action: workato_workflow_task / update_request
        fields: app_id, record_id, parameters, workflow_stage_id
      - action: slack_bot / post_bot_message
        fields: channel, message
      - action: email / send_mail
        fields: email_type, to, subject, body
      - action: workato_recipe_function / call_recipe
        fields: flow_id, parameters
      - catch [error handler]
        - action: logger / log_message
          fields: user_logs_enabled, message
        - action: workato_workflow_task / update_request
          fields: app_id, record_id, workflow_stage_id, parameters
        - action: slack_bot / post_bot_message
          fields: channel, message
        - action: slack_bot / post_bot_message
          fields: message, channel, text
    - else
      - action: email / send_mail
        fields: email_type, to, subject, body
      - action: workato_variable / update_variables
        fields: user_error_message, name, user_error_**message_body**, error_message
      - action: workato_workflow_task / update_request
        fields: app_id, record_id, workflow_stage_id, parameters
      - action: workato_recipe_function / call_recipe
        fields: flow_id, parameters

### `207034_65253302_v6`

Connectors: slack, slack_bot, workato_recipe_function
Steps:
- trigger: workato_recipe_function / execute
  - if [and: is_not_true]
    - action: slack / get_user_by_email
      fields: email
    - action: slack_bot / post_bot_message
      fields: channel, message

### `136763_50144444_v349`

Connectors: gmail, jira, jira_service_desk, open_ai, salesforce, slack_bot, workato_db_table, workato_internal_error_monitoring_connector_748504_1689301088, workato_recipe_function, workato_variable
Steps:
- trigger: workato_recipe_function / execute
  - try [error handling]
    - action: salesforce / search_sobjects_soql_v2
      fields: limit, query, output_schema
    - if [and: equals_to]
      - action: salesforce / update_sobject
        fields: sobject_name, id, OwnerId
      - action: salesforce / search_sobjects
        fields: limit, sobject_name, table_list, field_list, Id
    - action: workato_variable / declare_variable
      fields: variables
    - action: slack_bot / get_user_by_email
      fields: email
    - action: salesforce / search_sobjects
      fields: Id, limit, sobject_name, field_list
    - action: salesforce / __adhoc_http_action
      fields: mnemonic, verb, response_type, path
    - action: salesforce / search_sobjects
      fields: sobject_name, limit, Id, field_list
    - if [and: blank, blank]
      - stop
    - action: workato_variable / declare_variable
      fields: variables
    - action: jira / find_user
      fields: query
    - action: jira_service_desk / create_customer_request
      fields: requestTypeId, requestFieldValues, serviceDeskId, raiseOnBehalfOf
    - action: workato_db_table / get_records
      fields: order_direction, limit, table_id, filters, order_by_field_id
    - foreach [loop]
      - action: jira / __adhoc_http_action
        fields: mnemonic, verb, request_type, response_type, path, input
    - action: workato_db_table / upsert_record
      fields: table_id, primary_field_id, parameters
    - if [and: equals_to]
      - action: workato_recipe_function / call_recipe
        fields: flow_id, parameters
    - action: workato_recipe_function / return_result
      fields: result
    - catch [error handler]
      - try [error handling]
        - action: workato_variable / declare_variable
          fields: variables
        - action: open_ai / categorise_text
          fields: text, category_type, object_schema, model
        - action: slack_bot / get_user_by_email
          fields: email
        - if [and: equals_to]
          - if [and: present]
            - action: slack_bot / post_bot_message
              fields: channel, blocks
          - action: gmail / send_mail
            fields: email_type, to, subject, body
          - stop
        - if [and: equals_to]
          - if [and: present]
            - action: slack_bot / post_bot_message
              fields: channel, blocks
          - action: gmail / send_mail
            fields: email_type, to, subject, body
        - catch [error handler]
          - action: workato_internal_error_monitoring_connector_748504_1689301088 / publish_failed_job
            fields: attempt_automated_recovery, recipe_id, job_id, repeat_count, calling_job_id, calling_recipe_id, is_repeat, is_test, (+3 more)
          - stop

### `384059_62968617_v3`

Connectors: gmail, lookup_table, slack_bot, workato_pub_sub, workato_recipe_function
Steps:
- trigger: workato_pub_sub / subscribe_to_topic
  - action: workato_recipe_function / call_recipe
    fields: flow_id, parameters
  - action: lookup_table / update_entry
    fields: ignore_not_found, lookup_table_id, id, parameters
  - action: gmail / send_mail
    fields: email_type, to, subject, body, from
  - action: slack_bot / get_user_by_email
    fields: email
  - if [and: present]
    - action: slack_bot / post_bot_message
      fields: channel, blocks, text

---

## dense/Qwen3-Embedding-8B+instruct

### `804586_63319297_v11`

Connectors: work_genie_connector_3535597_1715305794, workato_files, **workato_go_connector_3535597_1749827549**
Steps:
- trigger: work_genie_connector_3535597_1715305794 / process_event
  - if [and: equals_to, equals_to]
    - foreach [loop]
      - if [and: present]
        - action: **workato_go_connector_3535597_1749827549** / **send_message**
          fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
      - if [and: present]
        - action: workato_files / create_shareable_link
          fields: scope, file_path
        - action: **workato_go_connector_3535597_1749827549** / **send_message**
          fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
  - if [and: equals_to]
    - action: work_genie_connector_3535597_1715305794 / get_process_action
      fields: function_type_id, function_id
    - if [and: equals_to]
      - action: **workato_go_connector_3535597_1749827549** / **send_message**
        fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
    - if [and: equals_to]
      - action: **workato_go_connector_3535597_1749827549** / **send_message**
        fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
    - if [and: equals_to]
      - action: **workato_go_connector_3535597_1749827549** / **send_message**
        fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
  - action: work_genie_connector_3535597_1715305794 / acknowledge_process_event
    fields: function_type_id, result

### `207034_65253302_v6`

Connectors: slack, slack_bot, workato_recipe_function
Steps:
- trigger: workato_recipe_function / execute
  - if [and: is_not_true]
    - action: slack / get_user_by_email
      fields: email
    - action: slack_bot / post_bot_message
      fields: channel, message

### `384059_62968617_v3`

Connectors: gmail, lookup_table, slack_bot, workato_pub_sub, workato_recipe_function
Steps:
- trigger: workato_pub_sub / subscribe_to_topic
  - action: workato_recipe_function / call_recipe
    fields: flow_id, parameters
  - action: lookup_table / update_entry
    fields: ignore_not_found, lookup_table_id, id, parameters
  - action: gmail / send_mail
    fields: email_type, to, subject, body, from
  - action: slack_bot / get_user_by_email
    fields: email
  - if [and: present]
    - action: slack_bot / post_bot_message
      fields: channel, blocks, text

### `1672047_18452821_v8`

Connectors: email, slack, slack_bot, workato_internal_workspace_connector_1672048_1681810578, workato_pub_sub, workato_variable
Steps:
- trigger: workato_pub_sub / subscribe_to_topic
  - action: workato_variable / declare_list
    fields: name, list_item_schema_json
  - if [and: present]
    - action: slack / get_user_by_email
      fields: email
  - if [and: blank]
    - if [and: blank]
      - stop
    - if [and: present]
      - action: slack_bot / post_bot_message
        fields: channel, blocks, message, attachment_fields
      - else
        - action: email / send_mail
          fields: email_type, to, subject, body
    - stop
  - action: workato_variable / declare_variable
    fields: variables
  - action: workato_internal_workspace_connector_1672048_1681810578 / submit_trial_request
    fields: contact_email, contact_first_name, contact_last_name, source, data_center_alpha2code, requester_email
  - action: workato_internal_workspace_connector_1672048_1681810578 / acknowledge_trial_request
    fields: coordinator_email, recruiter_email, job_title, candidate_personal_email, candidate_first_name, candidate_last_name

### `50737_66420669_v4`

Connectors: marketo, slack_bot, workato_webhooks
Steps:
- trigger: workato_webhooks / new_event
  - action: marketo / search_objects_action
    fields: object, filterType, filterValues, fields
  - action: slack_bot / post_bot_message
    fields: channel, blocks

---

## keyword/ilike

### `804586_63319297_v11`

Connectors: work_genie_connector_3535597_1715305794, workato_files, **workato_go_connector_3535597_1749827549**
Steps:
- trigger: work_genie_connector_3535597_1715305794 / process_event
  - if [and: equals_to, equals_to]
    - foreach [loop]
      - if [and: present]
        - action: **workato_go_connector_3535597_1749827549** / **send_message**
          fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
      - if [and: present]
        - action: workato_files / create_shareable_link
          fields: scope, file_path
        - action: **workato_go_connector_3535597_1749827549** / **send_message**
          fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
  - if [and: equals_to]
    - action: work_genie_connector_3535597_1715305794 / get_process_action
      fields: function_type_id, function_id
    - if [and: equals_to]
      - action: **workato_go_connector_3535597_1749827549** / **send_message**
        fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
    - if [and: equals_to]
      - action: **workato_go_connector_3535597_1749827549** / **send_message**
        fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
    - if [and: equals_to]
      - action: **workato_go_connector_3535597_1749827549** / **send_message**
        fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
  - action: work_genie_connector_3535597_1715305794 / acknowledge_process_event
    fields: function_type_id, result

---

## pgfts/english

### `804586_63319297_v11`

Connectors: work_genie_connector_3535597_1715305794, workato_files, **workato_go_connector_3535597_1749827549**
Steps:
- trigger: work_genie_connector_3535597_1715305794 / process_event
  - if [and: equals_to, equals_to]
    - foreach [loop]
      - if [and: present]
        - action: **workato_go_connector_3535597_1749827549** / **send_message**
          fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
      - if [and: present]
        - action: workato_files / create_shareable_link
          fields: scope, file_path
        - action: **workato_go_connector_3535597_1749827549** / **send_message**
          fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
  - if [and: equals_to]
    - action: work_genie_connector_3535597_1715305794 / get_process_action
      fields: function_type_id, function_id
    - if [and: equals_to]
      - action: **workato_go_connector_3535597_1749827549** / **send_message**
        fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
    - if [and: equals_to]
      - action: **workato_go_connector_3535597_1749827549** / **send_message**
        fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
    - if [and: equals_to]
      - action: **workato_go_connector_3535597_1749827549** / **send_message**
        fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
  - action: work_genie_connector_3535597_1715305794 / acknowledge_process_event
    fields: function_type_id, result

### `3000083_51901364_v24`

Connectors: csv_parser, email, google_drive, google_sheets, json_parser, logger, lookup_table, open_ai, py_eval, salesforce, slack_bot, workato_db_table, workato_list, workato_recipe_function, workato_variable, workato_workflow_task
Steps:
- trigger: workato_workflow_task / new_requests_realtime
  - action: workato_variable / declare_variable
    fields: variables
  - action: slack_bot / get_user_by_email
    fields: email
  - if [and: present]
    - try [error handling]
      - action: salesforce / search_sobjects
        fields: limit, sobject_name, Id, table_list, field_list
      - action: workato_variable / declare_variable
        fields: variables
      - action: workato_variable / update_variables
        fields: name, segment
      - action: salesforce / search_sobjects
        fields: sobject_name, limit, field_list, Email
      - if [and: not_equals_to]
        - action: workato_variable / declare_variable
          fields: variables
        - action: salesforce / search_sobjects
          fields: limit, sobject_name, Id, field_list
        - if [and: not_equals_to]
          - action: slack_bot / get_user_by_email
            fields: email
          - action: slack_bot / post_bot_message
            fields: channel, message
      - catch [error handler]
        - action: workato_variable / update_variables
          fields: user_error_message, name, user_error_**message_body**, error_message
        - action: workato_recipe_function / call_recipe
          fields: flow_id, parameters
        - stop
    - if [and: present]
      - action: workato_workflow_task / update_request
        fields: app_id, record_id, parameters, workflow_stage_id
      - else
        - action: workato_variable / update_variables
          fields: user_error_message, name, user_error_**message_body**, error_message
        - action: workato_recipe_function / call_recipe
          fields: flow_id, parameters
        - stop
  - if [and: contains]
    - try [error handling]
      - action: workato_workflow_task / update_request
        fields: app_id, record_id, workflow_stage_id
      - action: slack_bot / post_bot_message
        fields: channel, message
      - action: py_eval / invoke_custom_py_code
        fields: code, name, code_input, code_output_schema_json
      - action: google_drive / __adhoc_http_action
        fields: mnemonic, verb, request_type, response_type, path, input, output, request_headers, (+1 more)
      - action: google_drive / __adhoc_http_action
        fields: mnemonic, verb, response_type, response_headers, path
      - action: csv_parser / parse_csv
        fields: col_sep, skip_first_line, column_value_by, quote_char, csv_content, header_schema
      - action: open_ai / chat_completion
        fields: message_type, messages, model
      - action: json_parser / parse_json
        fields: sample_document, document
      - action: slack_bot / post_bot_message
        fields: channel, text
      - action: workato_variable / declare_variable
        fields: variables
      - try [error handling]
        - foreach [loop]
          - if [and: present]
            - action: workato_variable / declare_variable
              fields: variables
            - action: lookup_table / search_entries
              fields: parameters, lookup_table_id
            - if [and: blank]
              - action: workato_recipe_function / call_recipe
                fields: flow_id, parameters
              - action: workato_list / accumulate_list_items
                fields: name, list_item
              - action: workato_variable / update_variables
                fields: name, total_questions, total_answers, total_ai_answers
        - catch [error handler]
          - action: workato_variable / update_variables
            fields: user_error_message, name, user_error_**message_body**, error_message
          - action: workato_recipe_function / call_recipe
            fields: flow_id, parameters
          - action: workato_workflow_task / update_request
            fields: app_id, record_id, workflow_stage_id, parameters
          - stop
      - action: google_drive / copy_file
        fields: fileId, name, parents
      - action: google_drive / copy_file
        fields: fileId, name, parents
      - action: google_sheets / __adhoc_http_action
        fields: mnemonic, request_type, response_type, verb, path, input, output, response_headers
      - action: workato_variable / declare_variable
        fields: variables
      - action: workato_db_table / add_record
        fields: table_id, parameters
      - action: workato_workflow_task / update_request
        fields: app_id, record_id, parameters, workflow_stage_id
      - action: slack_bot / post_bot_message
        fields: channel, message
      - action: email / send_mail
        fields: email_type, to, subject, body
      - action: workato_recipe_function / call_recipe
        fields: flow_id, parameters
      - catch [error handler]
        - action: logger / log_message
          fields: user_logs_enabled, message
        - action: workato_workflow_task / update_request
          fields: app_id, record_id, workflow_stage_id, parameters
        - action: slack_bot / post_bot_message
          fields: channel, message
        - action: slack_bot / post_bot_message
          fields: message, channel, text
    - else
      - action: email / send_mail
        fields: email_type, to, subject, body
      - action: workato_variable / update_variables
        fields: user_error_message, name, user_error_**message_body**, error_message
      - action: workato_workflow_task / update_request
        fields: app_id, record_id, workflow_stage_id, parameters
      - action: workato_recipe_function / call_recipe
        fields: flow_id, parameters

### `136763_50144444_v349`

Connectors: gmail, jira, jira_service_desk, open_ai, salesforce, slack_bot, workato_db_table, workato_internal_error_monitoring_connector_748504_1689301088, workato_recipe_function, workato_variable
Steps:
- trigger: workato_recipe_function / execute
  - try [error handling]
    - action: salesforce / search_sobjects_soql_v2
      fields: limit, query, output_schema
    - if [and: equals_to]
      - action: salesforce / update_sobject
        fields: sobject_name, id, OwnerId
      - action: salesforce / search_sobjects
        fields: limit, sobject_name, table_list, field_list, Id
    - action: workato_variable / declare_variable
      fields: variables
    - action: slack_bot / get_user_by_email
      fields: email
    - action: salesforce / search_sobjects
      fields: Id, limit, sobject_name, field_list
    - action: salesforce / __adhoc_http_action
      fields: mnemonic, verb, response_type, path
    - action: salesforce / search_sobjects
      fields: sobject_name, limit, Id, field_list
    - if [and: blank, blank]
      - stop
    - action: workato_variable / declare_variable
      fields: variables
    - action: jira / find_user
      fields: query
    - action: jira_service_desk / create_customer_request
      fields: requestTypeId, requestFieldValues, serviceDeskId, raiseOnBehalfOf
    - action: workato_db_table / get_records
      fields: order_direction, limit, table_id, filters, order_by_field_id
    - foreach [loop]
      - action: jira / __adhoc_http_action
        fields: mnemonic, verb, request_type, response_type, path, input
    - action: workato_db_table / upsert_record
      fields: table_id, primary_field_id, parameters
    - if [and: equals_to]
      - action: workato_recipe_function / call_recipe
        fields: flow_id, parameters
    - action: workato_recipe_function / return_result
      fields: result
    - catch [error handler]
      - try [error handling]
        - action: workato_variable / declare_variable
          fields: variables
        - action: open_ai / categorise_text
          fields: text, category_type, object_schema, model
        - action: slack_bot / get_user_by_email
          fields: email
        - if [and: equals_to]
          - if [and: present]
            - action: slack_bot / post_bot_message
              fields: channel, blocks
          - action: gmail / send_mail
            fields: email_type, to, subject, body
          - stop
        - if [and: equals_to]
          - if [and: present]
            - action: slack_bot / post_bot_message
              fields: channel, blocks
          - action: gmail / send_mail
            fields: email_type, to, subject, body
        - catch [error handler]
          - action: workato_internal_error_monitoring_connector_748504_1689301088 / publish_failed_job
            fields: attempt_automated_recovery, recipe_id, job_id, repeat_count, calling_job_id, calling_recipe_id, is_repeat, is_test, (+3 more)
          - stop

### `1873345_44211838_v1`

Connectors: email, logger, lookup_table, salesforce, workato_internal_api_connector_1873346_1683875419, workato_internal_error_monitoring_connector_748504_1689301088, workato_list, workato_recipe_function, workato_service, workato_smart_list, workato_template
Steps:
- trigger: salesforce / scheduled_sobject_soql_query
  - try [error handling]
    - foreach [loop]
      - action: lookup_table / search_entries
        fields: lookup_table_id, parameters
      - if [and: equals_to]
        - if [or: is_true, is_true, is_true]
          - action: lookup_table / add_entry
            fields: lookup_table_id, parameters
    - foreach [loop]
      - action: workato_list / accumulate_list_items
        fields: name, list_item
    - action: logger / log_message
      fields: message
    - action: lookup_table / get_entries
      fields: lookup_table_id
    - if [and: not_equals_to]
      - foreach [loop]
        - action: workato_list / accumulate_list_items
          fields: name, list_item
      - action: workato_smart_list / create_list
        fields: list_source, list_name, primary_index
      - action: workato_smart_list / query_list
        fields: csv, headers, col_sep, sql, result_schema_json
      - if [and: not_equals_to]
        - foreach [loop]
          - action: lookup_table / delete_entry
            fields: ignore_not_found, lookup_table_id, id
      - action: lookup_table / get_entries
        fields: lookup_table_id
      - if [and: not_equals_to]
        - foreach [loop]
          - action: logger / log_message
            fields: message
          - if [and: greater_than, less_than, less_than]
            - action: salesforce / search_sobjects_soql
              fields: limit, sobject_name, field_list, query
            - if [and: not_equals_to]
              - action: salesforce / search_sobjects
                fields: limit, sobject_name, field_list, OpportunityId
              - action: workato_recipe_function / call_recipe
                fields: flow_id, parameters
              - if [or: not_contains]
                - action: lookup_table / delete_entry
                  fields: ignore_not_found, lookup_table_id, id
                - else
                  - try [error handling]
                    - action: workato_service / call_service
                      fields: flow_id, request
                    - catch [error handler]
                  - if [and: not_contains]
                    - try [error handling]
                      - action: workato_internal_api_connector_1873346_1683875419 / sync_and_extract_gong_emails
                        fields: AE_email, meeting_attended_date, gong_call_id
                      - catch [error handler]
                    - if [and: contains]
                      - if [and: equals_to]
                        - action: logger / log_message
                          fields: message
                        - action: workato_template / create_document
                          fields: template_id, template_input
                        - action: email / send_mail
                          fields: email_type, to, subject, body, cc
                        - action: lookup_table / update_entry
                          fields: ignore_not_found, lookup_table_id, id, parameters
                        - action: workato_list / accumulate_list_items
                          fields: name, list_item
                        - else
                          - if [and: equals_to]
                            - action: workato_recipe_function / call_recipe
                              fields: flow_id, parameters
                            - action: logger / log_message
                              fields: message, user_logs_enabled
                            - action: workato_template / create_document
                              fields: template_id, template_input
                            - action: email / send_mail
                              fields: email_type, to, subject, body, cc
                            - action: lookup_table / update_entry
                              fields: ignore_not_found, lookup_table_id, id, parameters
                            - action: workato_list / accumulate_list_items
                              fields: name, list_item
                      - else
                    - else
            - else
              - if [or: is_true, is_true, is_true]
                - action: workato_list / accumulate_list_items
                  fields: name, list_item
                - action: lookup_table / delete_entry
                  fields: lookup_table_id, ignore_not_found, id
    - catch [error handler]
      - action: workato_internal_error_monitoring_connector_748504_1689301088 / publish_failed_job
        fields: recipe_id, job_id, repeat_count, calling_job_id, calling_recipe_id, error, started_at, attempt_automated_recovery, (+3 more)

### `1672048_18452736_v30`

Connectors: corporate_api_connector_748504_1686073406, email, lookup_table, namely_connector_1672048_1686316621, slack_bot, snowflake, workato_bt_ops_workspace_connector_1672048_1686319146, workato_internal_workspace_connector_1672048_1681810578, workato_list, workato_recipe_function, workato_template, workato_variable
Steps:
- trigger: slack_bot / bot_command_v2
  - action: slack_bot / post_bot_message
    fields: channel, advanced, blocks
  - action: workato_recipe_function / call_recipe_async
    fields: flow_id, parameters
  - if [and: blank]
    - action: workato_internal_workspace_connector_1672048_1681810578 / evaluate_default_apps
      fields: evaluation_type, workato_email
  - action: workato_variable / declare_variable
    fields: variables
  - action: slack_bot / post_bot_message
    fields: channel, advanced, blocks, message
  - action: workato_recipe_function / call_recipe
    fields: flow_id, parameters
  - action: corporate_api_connector_748504_1686073406 / search_object
    fields: object, team_id, limit
  - if [and: not_equals_to]
    - stop
  - action: corporate_api_connector_748504_1686073406 / update_object
    fields: object, employee_id_update, team_id
  - action: namely_connector_1672048_1686316621 / update_employee_profile
    fields: profiles, id
  - action: workato_variable / declare_list
    fields: name, list_item_schema_json
  - foreach [loop]
    - action: lookup_table / search_entries
      fields: lookup_table_id, parameters
    - if [and: blank]
      - stop
    - action: snowflake / search_rows_sql
      fields: limit, offset, sql, output_schema, parameters
    - action: workato_variable / declare_variable
      fields: variables
    - if [and: present]
      - action: corporate_api_connector_748504_1686073406 / search_object
        fields: object, app_id, limit, approval_stage
      - if [and: not_equals_to, not_contains]
        - action: workato_list / accumulate_list_items
          fields: name, list_item
        - action: workato_internal_workspace_connector_1672048_1681810578 / log_new_app_request
          fields: beneficiary_id, requester_id, app_id, next_approval_stage, requested_provdate, timezone, justification, app_name
        - action: workato_variable / update_variables
          fields: name, log_into_snowflake
    - if [and: is_true]
      - if [or: not_equals_to, is_true]
        - action: corporate_api_connector_748504_1686073406 / search_object
          fields: object, employee_id, app_id
        - if [and: equals_to]
          - action: corporate_api_connector_748504_1686073406 / create_object
            fields: object, employee_id, app_id, status, provision_date, external_user, service_account
          - else
            - action: corporate_api_connector_748504_1686073406 / update_object
              fields: object, app_user_id, username, status, admin_access, last_active, provision_date, deprovision_date, (+5 more)
        - action: corporate_api_connector_748504_1686073406 / search_object
          fields: object, advanced, app_id, access_inherent, status
        - foreach [loop]
          - action: corporate_api_connector_748504_1686073406 / search_object
            fields: object, employee_id, app_access_level_id
          - if [and: equals_to]
            - action: corporate_api_connector_748504_1686073406 / create_object
              fields: object, employee_id, status, provision_date, app_access_level_id
            - else
              - action: corporate_api_connector_748504_1686073406 / update_object
                fields: object, app_user_id, username, status, provision_date, deprovision_date, employee_id_update, app_access_level_id_update
    - action: workato_variable / insert_to_list
      fields: location, name, list_item
  - if [and: present]
    - action: lookup_table / search_entries
      fields: lookup_table_id, parameters
    - if [and: not_equals_to]
      - stop
  - action: workato_recipe_function / call_recipe
    fields: flow_id, parameters
  - if [and: not_equals_to]
    - stop
  - action: workato_recipe_function / call_recipe
    fields: flow_id, parameters
  - if [and: equals_to]
    - action: workato_recipe_function / call_recipe
      fields: flow_id, parameters
    - action: workato_variable / declare_variable
      fields: variables
    - action: workato_template / create_document
      fields: template_id, template_input
    - action: workato_bt_ops_workspace_connector_1672048_1686319146 / create_sycomp_case
      fields: email, personal_email, mailing_address, contact_number, macbook_selection
    - foreach [loop]
      - action: email / send_mail
        fields: email_type, to, body, subject
      - if [and: present]
        - action: slack_bot / post_bot_message
          fields: channel, blocks, message, attachment_fields
  - action: workato_recipe_function / call_recipe
    fields: flow_id, parameters

---

## Source Recipe (flow\_id=63319297)

Connectors: work_genie_connector_3535597_1715305794, workato_files, **workato_go_connector_3535597_1749827549**
Steps:
- trigger: work_genie_connector_3535597_1715305794 / process_event
  - if [and: equals_to, equals_to]
    - foreach [loop]
      - if [and: present]
        - action: **workato_go_connector_3535597_1749827549** / **send_message**
          fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
      - if [and: present]
        - action: workato_files / create_shareable_link
          fields: scope, file_path
        - action: **workato_go_connector_3535597_1749827549** / **send_message**
          fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
  - if [and: equals_to]
    - action: work_genie_connector_3535597_1715305794 / get_process_action
      fields: function_type_id, function_id
    - if [and: equals_to]
      - action: **workato_go_connector_3535597_1749827549** / **send_message**
        fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
    - if [and: equals_to]
      - action: **workato_go_connector_3535597_1749827549** / **send_message**
        fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
    - if [and: equals_to]
      - action: **workato_go_connector_3535597_1749827549** / **send_message**
        fields: **event_type**, **message_body**, **user_email**, **agentic_user_jwt**, traceparent, tracestate
  - action: work_genie_connector_3535597_1715305794 / acknowledge_process_event
    fields: function_type_id, result
