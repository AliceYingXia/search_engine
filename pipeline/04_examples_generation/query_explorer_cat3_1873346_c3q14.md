# Example - 1873346_c3q14

---

## Query

> If the Salesforce **update_sobject** action updating the Account fields **At_Risk_Reason__c**, **At_Risk_Status__c**, **Last_QBR_Done_On__c**, **Last_Onsite_Visit__c**, **Customer_Live__c**, and **Embedded_Type__c** changes, which recipes will be affected?

---

## Ground-Truth Strong List (1 recipes)

- `1873346_53594265_v8`

---

## hybrid retrieval: fts-english+Qwen3-Embedding-8B+instruct

### `1873346_53594265_v8`

Connectors: airtable, email, salesforce
Steps:
- trigger: airtable / new_or_updated_record
  - try [error handling]
    - action: salesforce / search_sobjects
      fields: sobject_name, limit, Id, field_list
    - if [and: greater_than]
      - try [error handling]
        - action: salesforce / **update_sobject**
          fields: sobject_name, id, **At_Risk_Reason__c**, **At_Risk_Status__c**, **Last_QBR_Done_On__c**, **Last_Onsite_Visit__c**, **Customer_Live__c**, **Embedded_Type__c**, (+1 more)
        - action: airtable / update_record
          fields: base_id, table_id, id, fldZQnXwj8GAfTXBu, fld6KOzfxgdmMBh2j
        - catch [error handler]
          - action: airtable / update_record
            fields: base_id, table_id, id, fldZQnXwj8GAfTXBu
    - catch [error handler]
      - action: email / send_mail
        fields: email_type, to, subject, body
      - stop

### `8621_45073029_v1`

Connectors: clock, csv_parser, logger, salesforce, workato_internal_error_monitoring_connector_800229_1677904813, workato_list, workato_recipe_function, workato_smart_list
Steps:
- trigger: clock / scheduled_event
  - try [error handling]
    - action: salesforce / search_sobjects_soql_bulk_csv
      fields: include_deleted_records, include_header, custom_select_clause, sobject_name, query, fields
    - action: workato_smart_list / create_list_from_csv
      fields: file_encoded_type, headers, col_sep, list_source, list_name, csv_schema_json, primary_index
    - action: workato_smart_list / query_list
      fields: csv, headers, col_sep, sql, result_schema_json
    - action: workato_list / create_list
      fields: size
    - foreach [loop]
      - action: logger / log_message
        fields: message
      - action: workato_smart_list / query_list
        fields: csv, headers, col_sep, sql, result_schema_json, output_schema_by
      - action: workato_recipe_function / call_recipe
        fields: flow_id, parameters
      - if [and: greater_than]
        - action: logger / log_message
          fields: message, user_logs_enabled
        - action: logger / log_message
          fields: message
        - action: workato_smart_list / query_list
          fields: csv, headers, col_sep, sql, result_schema_json
    - action: workato_smart_list / query_list
      fields: csv, headers, col_sep, sql, result_schema_json
    - action: workato_smart_list / query_list
      fields: csv, headers, col_sep, sql, result_schema_json
    - if [and: greater_than]
      - action: csv_parser / create_csv_lines
        fields: create_header_line, column_separator, force_quotes, column_labels, lines
      - action: salesforce / update_bulk_job
        fields: csv_data, object, advanced, records, auto_mapping
      - else
        - foreach [loop]
          - action: salesforce / **update_sobject**
            fields: sobject_name, id, Lead__c, Account__c, Contact__c
    - catch [error handler]
      - action: workato_internal_error_monitoring_connector_800229_1677904813 / publish_failed_job
        fields: recipe_id, job_id, repeat_count, calling_job_id, calling_recipe_id, error, attempt_automated_recovery, is_repeat, (+2 more)

### `1873346_63519497_v1`

Connectors: clock, py_eval, salesforce, slack_bot, workato_service, workato_variable
Steps:
- trigger: clock / scheduled_event
  - action: salesforce / search_sobjects_soql
    fields: limit, sobject_name, query, field_list
  - foreach [loop]
    - action: salesforce / search_sobjects
      fields: limit, sobject_name, table_list, field_list, SBQQ__Account__c
    - foreach [loop]
      - if [and: equals_to, blank]
        - action: salesforce / **update_sobject**
          fields: sobject_name, id, Create_Partner_Account__c
        - action: workato_service / call_service
          fields: flow_id, request
        - action: salesforce / search_sobjects
          fields: limit, sobject_name, Id, field_list
        - action: salesforce / **update_sobject**
          fields: sobject_name, id, NDA_Signed__c, Partner_Agreement_Signed__c, Partner_Referral_Discount__c, Recurring_Referral_Payments__c, Partner_Classification__c, Partner_Pod__c, (+2 more)
        - action: slack_bot / post_bot_message
          fields: channel, blocks
      - if [and: equals_to, blank]
        - action: salesforce / search_sobjects
          fields: limit, sobject_name, AccountId, field_list
        - foreach [loop]
          - if [and: present, equals_to, equals_to]
            - foreach [loop]
              - action: salesforce / get_combined_attachment
                fields: Id
              - action: py_eval / invoke_custom_py_code
                fields: code, name, code_input, code_output_schema_json
              - action: workato_variable / declare_list
                fields: name, list_item_schema_json, list_items
              - foreach [loop]
                - if [or: is_true, is_true, is_true]
                  - action: salesforce / **update_sobject**
                    fields: sobject_name, id, Create_Partner_Account__c
                  - action: workato_service / call_service
                    fields: flow_id, request
                  - action: salesforce / search_sobjects
                    fields: limit, sobject_name, Id, field_list
                  - action: salesforce / **update_sobject**
                    fields: sobject_name, id, NDA_Signed__c, Partner_Agreement_Signed__c, Partner_Referral_Discount__c, Recurring_Referral_Payments__c, Partner_Classification__c, Partner_Pod__c, (+2 more)
                  - action: slack_bot / post_bot_message
                    fields: channel, blocks

### `136763_23099454_v8`

Connectors: email, google_sheets, intercom, lookup_table, salesforce, slack_bot, snowflake, workato_finance_workspace_connector_800229_1672734979, workato_list, workato_recipe_function, workato_template, workato_variable
Steps:
- trigger: workato_recipe_function / execute
  - try [error handling]
    - action: workato_variable / declare_variable
      fields: variables
    - action: workato_recipe_function / call_recipe
      fields: flow_id
    - action: snowflake / search_rows_sql
      fields: sql, limit, output_schema
    - if [and: greater_than]
      - stop
    - action: snowflake / run_custom_sql
      fields: sql, update_only, output_schema
    - action: salesforce / search_sobjects
      fields: sobject_name, limit, table_list, field_list, Id
    - action: workato_recipe_function / call_recipe
      fields: flow_id, parameters
    - if [and: present]
      - action: workato_recipe_function / call_recipe
        fields: flow_id, parameters
    - action: snowflake / search_rows_sql
      fields: sql, limit, output_schema
    - action: google_sheets / add_spreadsheet_row_v4
      fields: team_drives, is_top_left, spreadsheet, sheet, data
    - foreach [loop]
      - if [and: not_contains]
        - action: workato_list / accumulate_list_items
          fields: name, list_item
    - action: salesforce / search_sobjects
      fields: sobject_name, limit, AccountId, table_list, Status, field_list
    - foreach [loop]
      - action: salesforce / search_sobjects
        fields: sobject_name, limit, table_list, field_list, SBQQSC__ServiceContract__c
      - foreach [loop]
        - action: lookup_table / search_entries
          fields: lookup_table_id, parameters
        - if [and: equals_to]
          - action: workato_list / accumulate_list_items
            fields: name, list_item
    - action: workato_variable / declare_variable
      fields: variables
    - if [and: present]
      - action: salesforce / search_sobjects
        fields: sobject_name, limit, table_list, Id, field_list
      - if [and: equals_to]
        - action: workato_finance_workspace_connector_800229_1672734979 / list_past_due_invoices_on_churn_oppty
          fields: oppty_id
        - action: workato_variable / update_variables
          fields: name, unpaid_invoices_html, close_date_formatted, email_subject
        - action: workato_template / create_document
          fields: template_id, template_input
    - if [and: blank]
      - action: workato_template / create_document
        fields: template_id, template_input
    - action: email / send_mail
      fields: email_type, to, body, subject
    - foreach [loop]
      - action: intercom / search_user
        fields: user_id
      - if [and: present]
        - action: intercom / update_user
          fields: user_id, unsubscribed_from_emails
        - action: workato_list / accumulate_list_items
          fields: name, list_item
    - if [and: greater_than]
      - action: slack_bot / post_bot_message
        fields: advanced, blocks, channel
    - catch [error handler]
      - action: workato_recipe_function / call_recipe
        fields: flow_id, parameters

### `800219_23099317_v1`

Connectors: lookup_table, salesforce, workato_recipe_function
Steps:
- trigger: workato_recipe_function / execute
  - try [error handling]
    - if [or: present, present, present, present, present]
      - action: lookup_table / search_entries
        fields: lookup_table_id, parameters
      - if [and: greater_than]
        - foreach [loop]
          - action: lookup_table / delete_entry
            fields: ignore_not_found, id, lookup_table_id
      - if [or: equals_to]
        - action: lookup_table / add_entry
          fields: lookup_table_id, parameters
      - action: lookup_table / update_entry
        fields: ignore_not_found, lookup_table_id, id, parameters
    - action: salesforce / search_sobjects
      fields: limit, sobject_name, field_list, Email__c
    - if [and: blank]
      - action: salesforce / create_custom_object
        fields: sobject_name, Email__c, Name
    - try [error handling]
      - action: salesforce / **update_sobject**
        fields: sobject_name, id, Name, Freshdesk_User_ID__c, Intercom_Admin_ID__c, Slack_Handle__c, Status__c, Salesforce_User__c
      - catch [error handler]
        - if [and: not_contains, not_contains, not_contains]
          - stop
    - action: lookup_table / search_entries
      fields: lookup_table_id, parameters
    - if [and: greater_than]
      - foreach [loop]
        - action: lookup_table / delete_entry
          fields: ignore_not_found, id, lookup_table_id
    - if [or: equals_to]
      - action: lookup_table / add_entry
        fields: lookup_table_id, parameters
    - action: lookup_table / update_entry
      fields: ignore_not_found, lookup_table_id, id, parameters
    - action: workato_recipe_function / return_result
      fields: result
    - catch [error handler]
      - action: workato_recipe_function / call_recipe
        fields: flow_id, parameters

---

## dense/Qwen3-Embedding-8B+instruct

### `1873346_53594265_v8`

Connectors: airtable, email, salesforce
Steps:
- trigger: airtable / new_or_updated_record
  - try [error handling]
    - action: salesforce / search_sobjects
      fields: sobject_name, limit, Id, field_list
    - if [and: greater_than]
      - try [error handling]
        - action: salesforce / **update_sobject**
          fields: sobject_name, id, **At_Risk_Reason__c**, **At_Risk_Status__c**, **Last_QBR_Done_On__c**, **Last_Onsite_Visit__c**, **Customer_Live__c**, **Embedded_Type__c**, (+1 more)
        - action: airtable / update_record
          fields: base_id, table_id, id, fldZQnXwj8GAfTXBu, fld6KOzfxgdmMBh2j
        - catch [error handler]
          - action: airtable / update_record
            fields: base_id, table_id, id, fldZQnXwj8GAfTXBu
    - catch [error handler]
      - action: email / send_mail
        fields: email_type, to, subject, body
      - stop

### `3382944_63360187_v12`

Connectors: salesforce, workato_db_table, workato_genie, workato_variable
Steps:
- trigger: workato_genie / start_workflow
  - action: workato_variable / declare_variable
    fields: variables
  - action: salesforce / **update_sobject**
    fields: sobject_name, id, Status, Description
  - if [and: present]
    - action: workato_db_table / get_records
      fields: order_direction, limit, table_id, filters
    - if [and: present]
      - action: workato_db_table / update_record
        fields: table_id, record_id, parameters
  - action: salesforce / search_sobjects
    fields: limit, sobject_name, field_list, Id
  - action: workato_genie / workflow_return_result
    fields: result

### `84762_64584801_v24`

Connectors: logger, rest, salesforce, workato_db_table, workato_genie
Steps:
- trigger: workato_genie / start_workflow
  - action: salesforce / search_sobjects_soql
    fields: limit, sobject_name, query, field_list
  - if [or: greater_than, is_true]
    - action: rest / make_request_v2
      fields: request_name, request, response, wait_for_response
    - action: salesforce / **update_sobject**
      fields: sobject_name, id
    - action: logger / log_message
      fields: user_logs_enabled, message
  - action: workato_db_table / add_record
    fields: table_id, parameters
  - action: workato_genie / workflow_return_result
    fields: result

### `1873346_63519497_v1`

Connectors: clock, py_eval, salesforce, slack_bot, workato_service, workato_variable
Steps:
- trigger: clock / scheduled_event
  - action: salesforce / search_sobjects_soql
    fields: limit, sobject_name, query, field_list
  - foreach [loop]
    - action: salesforce / search_sobjects
      fields: limit, sobject_name, table_list, field_list, SBQQ__Account__c
    - foreach [loop]
      - if [and: equals_to, blank]
        - action: salesforce / **update_sobject**
          fields: sobject_name, id, Create_Partner_Account__c
        - action: workato_service / call_service
          fields: flow_id, request
        - action: salesforce / search_sobjects
          fields: limit, sobject_name, Id, field_list
        - action: salesforce / **update_sobject**
          fields: sobject_name, id, NDA_Signed__c, Partner_Agreement_Signed__c, Partner_Referral_Discount__c, Recurring_Referral_Payments__c, Partner_Classification__c, Partner_Pod__c, (+2 more)
        - action: slack_bot / post_bot_message
          fields: channel, blocks
      - if [and: equals_to, blank]
        - action: salesforce / search_sobjects
          fields: limit, sobject_name, AccountId, field_list
        - foreach [loop]
          - if [and: present, equals_to, equals_to]
            - foreach [loop]
              - action: salesforce / get_combined_attachment
                fields: Id
              - action: py_eval / invoke_custom_py_code
                fields: code, name, code_input, code_output_schema_json
              - action: workato_variable / declare_list
                fields: name, list_item_schema_json, list_items
              - foreach [loop]
                - if [or: is_true, is_true, is_true]
                  - action: salesforce / **update_sobject**
                    fields: sobject_name, id, Create_Partner_Account__c
                  - action: workato_service / call_service
                    fields: flow_id, request
                  - action: salesforce / search_sobjects
                    fields: limit, sobject_name, Id, field_list
                  - action: salesforce / **update_sobject**
                    fields: sobject_name, id, NDA_Signed__c, Partner_Agreement_Signed__c, Partner_Referral_Discount__c, Recurring_Referral_Payments__c, Partner_Classification__c, Partner_Pod__c, (+2 more)
                  - action: slack_bot / post_bot_message
                    fields: channel, blocks

### `8621_45073029_v1`

Connectors: clock, csv_parser, logger, salesforce, workato_internal_error_monitoring_connector_800229_1677904813, workato_list, workato_recipe_function, workato_smart_list
Steps:
- trigger: clock / scheduled_event
  - try [error handling]
    - action: salesforce / search_sobjects_soql_bulk_csv
      fields: include_deleted_records, include_header, custom_select_clause, sobject_name, query, fields
    - action: workato_smart_list / create_list_from_csv
      fields: file_encoded_type, headers, col_sep, list_source, list_name, csv_schema_json, primary_index
    - action: workato_smart_list / query_list
      fields: csv, headers, col_sep, sql, result_schema_json
    - action: workato_list / create_list
      fields: size
    - foreach [loop]
      - action: logger / log_message
        fields: message
      - action: workato_smart_list / query_list
        fields: csv, headers, col_sep, sql, result_schema_json, output_schema_by
      - action: workato_recipe_function / call_recipe
        fields: flow_id, parameters
      - if [and: greater_than]
        - action: logger / log_message
          fields: message, user_logs_enabled
        - action: logger / log_message
          fields: message
        - action: workato_smart_list / query_list
          fields: csv, headers, col_sep, sql, result_schema_json
    - action: workato_smart_list / query_list
      fields: csv, headers, col_sep, sql, result_schema_json
    - action: workato_smart_list / query_list
      fields: csv, headers, col_sep, sql, result_schema_json
    - if [and: greater_than]
      - action: csv_parser / create_csv_lines
        fields: create_header_line, column_separator, force_quotes, column_labels, lines
      - action: salesforce / update_bulk_job
        fields: csv_data, object, advanced, records, auto_mapping
      - else
        - foreach [loop]
          - action: salesforce / **update_sobject**
            fields: sobject_name, id, Lead__c, Account__c, Contact__c
    - catch [error handler]
      - action: workato_internal_error_monitoring_connector_800229_1677904813 / publish_failed_job
        fields: recipe_id, job_id, repeat_count, calling_job_id, calling_recipe_id, error, attempt_automated_recovery, is_repeat, (+2 more)

---

## keyword/ilike

### `1873346_53594265_v8`

Connectors: airtable, email, salesforce
Steps:
- trigger: airtable / new_or_updated_record
  - try [error handling]
    - action: salesforce / search_sobjects
      fields: sobject_name, limit, Id, field_list
    - if [and: greater_than]
      - try [error handling]
        - action: salesforce / **update_sobject**
          fields: sobject_name, id, **At_Risk_Reason__c**, **At_Risk_Status__c**, **Last_QBR_Done_On__c**, **Last_Onsite_Visit__c**, **Customer_Live__c**, **Embedded_Type__c**, (+1 more)
        - action: airtable / update_record
          fields: base_id, table_id, id, fldZQnXwj8GAfTXBu, fld6KOzfxgdmMBh2j
        - catch [error handler]
          - action: airtable / update_record
            fields: base_id, table_id, id, fldZQnXwj8GAfTXBu
    - catch [error handler]
      - action: email / send_mail
        fields: email_type, to, subject, body
      - stop

---

## pgfts/english

### `1873346_53594265_v8`

Connectors: airtable, email, salesforce
Steps:
- trigger: airtable / new_or_updated_record
  - try [error handling]
    - action: salesforce / search_sobjects
      fields: sobject_name, limit, Id, field_list
    - if [and: greater_than]
      - try [error handling]
        - action: salesforce / **update_sobject**
          fields: sobject_name, id, **At_Risk_Reason__c**, **At_Risk_Status__c**, **Last_QBR_Done_On__c**, **Last_Onsite_Visit__c**, **Customer_Live__c**, **Embedded_Type__c**, (+1 more)
        - action: airtable / update_record
          fields: base_id, table_id, id, fldZQnXwj8GAfTXBu, fld6KOzfxgdmMBh2j
        - catch [error handler]
          - action: airtable / update_record
            fields: base_id, table_id, id, fldZQnXwj8GAfTXBu
    - catch [error handler]
      - action: email / send_mail
        fields: email_type, to, subject, body
      - stop

### `2436037_45178430_v28`

Connectors: clock, corporate_api_connector_748504_1686073406, google_sheets, logger, lookup_table, marketo, outreach_read_only__connector_2436037_1708847647, rest, salesforce, slack_bot, workato_internal_api_connector_2436037_1708847652, workato_list, workato_recipe_function, workato_service, workato_smart_list, workato_variable, workato_webhooks, zoom_info_connector_2436037_1710162847
Steps:
- trigger: workato_webhooks / new_event
  - if [or: contains, contains, contains]
    - stop
  - action: workato_recipe_function / call_recipe
    fields: flow_id, parameters
  - if [and: contains]
    - stop
  - action: workato_recipe_function / call_recipe
    fields: flow_id, parameters
  - if [and: contains]
    - stop
  - if [and: is_not_true]
    - action: clock / wait_for_interval
      fields: interval
  - try [error handling]
    - action: outreach_read_only__connector_2436037_1708847647 / search_prospects
      fields: emails
    - catch [error handler]
  - action: lookup_table / search_entries
    fields: lookup_table_id, parameters
  - action: lookup_table / get_entries
    fields: lookup_table_id
  - if [and: greater_than]
    - if [and: equals_to]
      - action: lookup_table / get_entries
        fields: lookup_table_id
      - foreach [loop]
        - action: workato_list / accumulate_list_items
          fields: name, list_item
      - action: workato_smart_list / create_list
        fields: list_source, list_name, force
      - action: workato_smart_list / query_list
        fields: csv, headers, col_sep, sql, result_schema_json, output_schema_by
      - action: logger / log_message
        fields: message, user_logs_enabled
      - action: lookup_table / update_entry
        fields: ignore_not_found, lookup_table_id, id, parameters
      - action: workato_internal_api_connector_2436037_1708847652 / create_person_in_outreach
        fields: first_name, last_name, email, company, owner, sequence, phone
      - action: slack_bot / post_bot_message
        fields: channel, text, message, attachment_fields
      - stop
    - if [and: equals_to]
      - action: lookup_table / search_entries
        fields: lookup_table_id, parameters
      - if [and: equals_to]
        - action: workato_internal_api_connector_2436037_1708847652 / create_person_in_outreach
          fields: first_name, last_name, email, company, owner, sequence, phone
        - action: slack_bot / post_bot_message
          fields: channel, text, message, attachment_fields
        - stop
    - if [and: equals_to]
      - action: lookup_table / search_entries
        fields: lookup_table_id, parameters
      - if [and: equals_to]
        - action: workato_internal_api_connector_2436037_1708847652 / create_person_in_outreach
          fields: first_name, last_name, email, company, owner, sequence, phone
        - action: slack_bot / post_bot_message
          fields: channel, text, message, attachment_fields
        - stop
    - if [and: equals_to]
      - action: lookup_table / search_entries
        fields: lookup_table_id, parameters
      - if [and: equals_to, equals_to]
        - if [and: greater_than]
          - action: outreach_read_only__connector_2436037_1708847647 / search_sequence_states
            fields: prospect_id
          - if [and: greater_than]
            - foreach [loop]
              - if [and: contains]
                - if [and: equals_to]
                  - action: slack_bot / post_bot_message
                    fields: channel, text, message, attachment_fields
                  - stop
        - action: workato_internal_api_connector_2436037_1708847652 / create_person_in_outreach
          fields: first_name, last_name, email, company, owner, sequence, phone
        - action: slack_bot / post_bot_message
          fields: channel, text, message, attachment_fields
        - stop
      - action: lookup_table / search_entries
        fields: lookup_table_id, parameters
      - if [and: equals_to, blank]
        - action: workato_internal_api_connector_2436037_1708847652 / create_person_in_outreach
          fields: first_name, last_name, email, company, owner, sequence, phone
        - action: slack_bot / post_bot_message
          fields: channel, text, message, attachment_fields
        - stop
    - if [and: equals_to]
      - action: workato_variable / declare_variable
        fields: variables
      - action: workato_variable / declare_variable
        fields: variables
      - action: workato_variable / declare_variable
        fields: variables
      - action: salesforce / search_sobjects
        fields: sobject_name, limit, Email, field_list
      - if [and: greater_than]
        - action: workato_variable / update_variables
          fields: name, country
        - action: workato_variable / update_variables
          fields: name, employee_size
      - if [or: blank, blank]
        - try [error handling]
          - action: zoom_info_connector_2436037_1710162847 / enrich_object
            fields: object, companyName
          - if [and: greater_than]
            - if [and: blank]
              - action: workato_variable / update_variables
                fields: name, country
            - action: workato_variable / update_variables
              fields: name, employee_size
          - catch [error handler]
      - if [and: greater_than, present]
        - action: workato_variable / update_variables
          fields: name, job_title, lead_id
        - action: workato_variable / update_variables
          fields: name, company_name
      - action: salesforce / search_sobjects
        fields: sobject_name, limit, Domain__c, field_list
      - if [and: greater_than]
        - action: salesforce / search_sobjects
          fields: limit, sobject_name, field_list, Id
        - action: workato_variable / update_variables
          fields: name, company_name, current_arr, segment
        - action: workato_variable / update_variables
          fields: name, expansion_sdr, new_logo_sdr
        - action: salesforce / search_sobjects
          fields: limit, sobject_name, field_list, Id
        - if [and: present]
          - action: workato_variable / update_variables
            fields: name, sales_team
          - if [or: not_contains, not_contains, not_contains]
            - action: workato_variable / update_variables
              fields: name, named_account
      - action: salesforce / search_sobjects
        fields: limit, sobject_name, field_list, Email
      - if [and: greater_than]
        - action: workato_variable / update_variables
          fields: name, job_title, contact_id
        - action: salesforce / search_sobjects
          fields: limit, sobject_name, field_list, Id
        - action: workato_variable / update_variables
          fields: name, company_name, current_arr, segment
        - action: workato_variable / update_variables
          fields: name, expansion_sdr, new_logo_sdr
        - action: salesforce / search_sobjects
          fields: limit, sobject_name, field_list, Id
        - if [and: present]
          - action: workato_variable / update_variables
            fields: name, sales_team
          - if [or: not_contains, not_contains, not_contains]
            - action: workato_variable / update_variables
              fields: name, named_account
      - if [and: present]
        - if [or: contains, contains]
          - action: lookup_table / search_entries
            fields: lookup_table_id, parameters
          - action: workato_internal_api_connector_2436037_1708847652 / create_person_in_outreach
            fields: first_name, last_name, email, company, owner, sequence, phone
          - action: slack_bot / post_bot_message
            fields: channel, text, message, attachment_fields
          - stop
      - if [and: equals_to]
        - action: lookup_table / search_entries
          fields: lookup_table_id, parameters
        - action: workato_internal_api_connector_2436037_1708847652 / create_person_in_outreach
          fields: first_name, last_name, email, company, owner, sequence, phone
        - action: slack_bot / post_bot_message
          fields: channel, text, message, attachment_fields
        - stop
      - if [and: present, present]
        - if [and: greater_than, equals_to]
          - if [and: present]
            - if [and: present]
              - action: salesforce / create_custom_object
                fields: sobject_name, CampaignId, ContactId
              - else
                - action: salesforce / create_custom_object
                  fields: sobject_name, CampaignId, LeadId
            - action: workato_service / call_service
              fields: flow_id, request
            - action: corporate_api_connector_748504_1686073406 / search_object
              fields: object
            - action: salesforce / search_sobjects
              fields: limit, sobject_name, field_list, Id
            - action: salesforce / search_sobjects
              fields: sobject_name, Campaign__c, limit, Email__c
            - action: workato_service / call_service
              fields: flow_id, request
            - action: rest / make_request_v2
              fields: request_name, request, response, wait_for_response
            - stop
      - if [or: blank, equals_to]
        - if [and: present]
          - if [and: equals_to]
            - if [and: present]
              - try [error handling]
                - action: salesforce / create_custom_object
                  fields: sobject_name, CampaignId, ContactId
                - catch [error handler]
              - else
                - try [error handling]
                  - action: salesforce / create_custom_object
                    fields: sobject_name, CampaignId, LeadId
                  - catch [error handler]
            - action: workato_service / call_service
              fields: flow_id, request
            - action: corporate_api_connector_748504_1686073406 / search_object
              fields: object, email
            - action: salesforce / search_sobjects
              fields: sobject_name, Campaign__c, limit, Email__c
            - action: workato_service / call_service
              fields: flow_id, request
            - action: rest / make_request_v2
              fields: request_name, request, response, wait_for_response
            - stop
        - if [and: present, present]
          - if [and: contains, greater_than]
            - if [and: present]
              - try [error handling]
                - action: salesforce / create_custom_object
                  fields: sobject_name, CampaignId, ContactId
                - catch [error handler]
              - else
                - try [error handling]
                  - action: salesforce / create_custom_object
                    fields: sobject_name, CampaignId, LeadId
                  - catch [error handler]
            - action: workato_service / call_service
              fields: flow_id, request
            - action: corporate_api_connector_748504_1686073406 / search_object
              fields: object, email
            - action: salesforce / search_sobjects
              fields: sobject_name, Campaign__c, limit, Email__c
            - action: workato_service / call_service
              fields: flow_id, request
            - action: rest / make_request_v2
              fields: request_name, request, response, wait_for_response
            - stop
      - if [and: equals_to]
        - if [and: present]
          - if [and: contains, greater_than]
            - action: salesforce / search_sobjects
              fields: limit, sobject_name, field_list, Id
            - action: workato_internal_api_connector_2436037_1708847652 / create_person_in_outreach
              fields: first_name, last_name, email, company, owner, sequence, phone
            - action: slack_bot / post_bot_message
              fields: channel, text, message, attachment_fields
            - stop
        - if [and: present]
          - action: salesforce / search_sobjects
            fields: limit, sobject_name, field_list, Id
          - action: workato_internal_api_connector_2436037_1708847652 / create_person_in_outreach
            fields: first_name, last_name, email, company, owner, sequence, phone
          - action: slack_bot / post_bot_message
            fields: channel, text, message, attachment_fields
          - stop
        - action: workato_variable / update_variables
          fields: name, named_account
  - action: lookup_table / search_entries
    fields: lookup_table_id, parameters
  - action: marketo / search_objects_action
    fields: object, filterType, filterValues, fields
  - if [or: present, present]
    - action: workato_variable / declare_variable
      fields: variables
  - if [and: present]
    - action: lookup_table / search_entries
      fields: lookup_table_id, parameters
    - if [and: greater_than]
      - action: google_sheets / search_spreadsheet_rows_v4_new
        fields: team_drives, spreadsheet, count, sheet, data
      - action: workato_internal_api_connector_2436037_1708847652 / create_person_in_outreach
        fields: first_name, last_name, email, company, owner, sequence, phone
      - action: slack_bot / post_bot_message
        fields: channel, text, message, attachment_fields
      - stop
  - action: workato_internal_api_connector_2436037_1708847652 / create_person_in_outreach
    fields: first_name, last_name, email, company, owner, sequence, phone
  - action: slack_bot / post_bot_message
    fields: channel, text, message, attachment_fields
  - stop

### `136763_23099454_v8`

Connectors: email, google_sheets, intercom, lookup_table, salesforce, slack_bot, snowflake, workato_finance_workspace_connector_800229_1672734979, workato_list, workato_recipe_function, workato_template, workato_variable
Steps:
- trigger: workato_recipe_function / execute
  - try [error handling]
    - action: workato_variable / declare_variable
      fields: variables
    - action: workato_recipe_function / call_recipe
      fields: flow_id
    - action: snowflake / search_rows_sql
      fields: sql, limit, output_schema
    - if [and: greater_than]
      - stop
    - action: snowflake / run_custom_sql
      fields: sql, update_only, output_schema
    - action: salesforce / search_sobjects
      fields: sobject_name, limit, table_list, field_list, Id
    - action: workato_recipe_function / call_recipe
      fields: flow_id, parameters
    - if [and: present]
      - action: workato_recipe_function / call_recipe
        fields: flow_id, parameters
    - action: snowflake / search_rows_sql
      fields: sql, limit, output_schema
    - action: google_sheets / add_spreadsheet_row_v4
      fields: team_drives, is_top_left, spreadsheet, sheet, data
    - foreach [loop]
      - if [and: not_contains]
        - action: workato_list / accumulate_list_items
          fields: name, list_item
    - action: salesforce / search_sobjects
      fields: sobject_name, limit, AccountId, table_list, Status, field_list
    - foreach [loop]
      - action: salesforce / search_sobjects
        fields: sobject_name, limit, table_list, field_list, SBQQSC__ServiceContract__c
      - foreach [loop]
        - action: lookup_table / search_entries
          fields: lookup_table_id, parameters
        - if [and: equals_to]
          - action: workato_list / accumulate_list_items
            fields: name, list_item
    - action: workato_variable / declare_variable
      fields: variables
    - if [and: present]
      - action: salesforce / search_sobjects
        fields: sobject_name, limit, table_list, Id, field_list
      - if [and: equals_to]
        - action: workato_finance_workspace_connector_800229_1672734979 / list_past_due_invoices_on_churn_oppty
          fields: oppty_id
        - action: workato_variable / update_variables
          fields: name, unpaid_invoices_html, close_date_formatted, email_subject
        - action: workato_template / create_document
          fields: template_id, template_input
    - if [and: blank]
      - action: workato_template / create_document
        fields: template_id, template_input
    - action: email / send_mail
      fields: email_type, to, body, subject
    - foreach [loop]
      - action: intercom / search_user
        fields: user_id
      - if [and: present]
        - action: intercom / update_user
          fields: user_id, unsubscribed_from_emails
        - action: workato_list / accumulate_list_items
          fields: name, list_item
    - if [and: greater_than]
      - action: slack_bot / post_bot_message
        fields: advanced, blocks, channel
    - catch [error handler]
      - action: workato_recipe_function / call_recipe
        fields: flow_id, parameters

### `8621_45073029_v1`

Connectors: clock, csv_parser, logger, salesforce, workato_internal_error_monitoring_connector_800229_1677904813, workato_list, workato_recipe_function, workato_smart_list
Steps:
- trigger: clock / scheduled_event
  - try [error handling]
    - action: salesforce / search_sobjects_soql_bulk_csv
      fields: include_deleted_records, include_header, custom_select_clause, sobject_name, query, fields
    - action: workato_smart_list / create_list_from_csv
      fields: file_encoded_type, headers, col_sep, list_source, list_name, csv_schema_json, primary_index
    - action: workato_smart_list / query_list
      fields: csv, headers, col_sep, sql, result_schema_json
    - action: workato_list / create_list
      fields: size
    - foreach [loop]
      - action: logger / log_message
        fields: message
      - action: workato_smart_list / query_list
        fields: csv, headers, col_sep, sql, result_schema_json, output_schema_by
      - action: workato_recipe_function / call_recipe
        fields: flow_id, parameters
      - if [and: greater_than]
        - action: logger / log_message
          fields: message, user_logs_enabled
        - action: logger / log_message
          fields: message
        - action: workato_smart_list / query_list
          fields: csv, headers, col_sep, sql, result_schema_json
    - action: workato_smart_list / query_list
      fields: csv, headers, col_sep, sql, result_schema_json
    - action: workato_smart_list / query_list
      fields: csv, headers, col_sep, sql, result_schema_json
    - if [and: greater_than]
      - action: csv_parser / create_csv_lines
        fields: create_header_line, column_separator, force_quotes, column_labels, lines
      - action: salesforce / update_bulk_job
        fields: csv_data, object, advanced, records, auto_mapping
      - else
        - foreach [loop]
          - action: salesforce / **update_sobject**
            fields: sobject_name, id, Lead__c, Account__c, Contact__c
    - catch [error handler]
      - action: workato_internal_error_monitoring_connector_800229_1677904813 / publish_failed_job
        fields: recipe_id, job_id, repeat_count, calling_job_id, calling_recipe_id, error, attempt_automated_recovery, is_repeat, (+2 more)

### `800229_23099450_v7`

Connectors: google_drive, json_parser, lookup_table, salesforce, slack, slack_bot, snowflake, workato_custom_code, workato_recipe_function, workato_variable
Steps:
- trigger: workato_recipe_function / execute
  - try [error handling]
    - action: workato_variable / declare_variable
      fields: variables
    - action: snowflake / run_custom_sql
      fields: sql, output_schema, update_only
    - action: workato_variable / declare_variable
      fields: variables
    - action: workato_variable / declare_list
      fields: name, list_item_schema_json
    - if [and: present]
      - action: workato_recipe_function / call_recipe
        fields: flow_id, parameters
      - if [and: equals_to]
        - if [and: is_true, less_than]
          - action: workato_variable / update_variables
            fields: name, current_stage
        - action: workato_variable / declare_variable
          fields: variables
        - if [or: present, present]
          - if [and: present]
            - action: salesforce / search_sobjects
              fields: sobject_name, limit, field_list, table_list, Id
          - action: salesforce / search_sobjects
            fields: sobject_name, limit, field_list, table_list, Id
          - if [and: present]
            - action: slack / get_user_by_email
              fields: email
            - if [and: blank]
              - action: slack / get_user_by_email
                fields: email
            - if [or: present, present]
              - action: workato_variable / update_variables
                fields: name, account_executive_slack_id, account_executive_slack_name, account_executive_slack_email
          - if [or: present]
            - action: slack / get_user_by_email
              fields: email
            - if [and: blank]
              - action: slack / get_user_by_email
                fields: email
            - if [or: present, present]
              - action: workato_variable / update_variables
                fields: name, csm_slack_id, csm_slack_name, csm_slack_email
        - if [and: blank, blank]
          - if [and: present]
            - action: slack / get_user_by_email
              fields: email
            - if [or: present]
              - action: workato_variable / update_variables
                fields: name, account_executive_slack_id, account_executive_slack_email, account_executive_slack_name
          - if [and: blank]
            - stop
        - if [and: equals_to]
          - if [and: present, not_equals_to]
            - action: workato_variable / update_variables
              fields: name, approver_conversation_id, approver_conversation_name
            - else
              - action: workato_variable / update_variables
                fields: name, current_stage
        - if [and: equals_to]
          - if [and: present, not_equals_to]
            - action: workato_variable / update_variables
              fields: name, approver_conversation_id, approver_conversation_name
            - else
              - action: workato_variable / update_variables
                fields: name, current_stage
          - action: workato_variable / insert_to_list
            fields: location, name, list_item
        - if [and: equals_to]
          - action: workato_variable / update_variables
            fields: name, approver_conversation_id, approver_conversation_name
          - action: workato_variable / insert_to_list_batch
            fields: location, name, list_items
        - if [and: blank]
          - action: workato_variable / insert_to_list_batch
            fields: location, name, list_items
      - if [and: contains]
        - if [and: equals_to]
          - action: workato_variable / update_variables
            fields: name, approver_conversation_id, approver_conversation_name
          - action: workato_variable / insert_to_list_batch
            fields: location, name, list_items
    - if [and: present]
      - action: snowflake / search_rows_sql
        fields: sql, limit, output_schema
      - if [and: starts_with]
        - action: workato_recipe_function / call_recipe
          fields: flow_id, parameters, dynamic_config
        - action: workato_variable / update_variables
          fields: name, approver_conversation_id
      - if [and: present, present]
        - action: json_parser / parse_json
          fields: sample_document, document
        - foreach [loop]
          - action: workato_variable / declare_variable
            fields: variables
          - action: google_drive / __adhoc_http_action
            fields: mnemonic, verb, response_type, path, input, output
          - action: lookup_table / search_entries
            fields: lookup_table_id, parameters
          - if [and: equals_to]
            - stop
          - action: google_drive / download_file_contents
            fields: fileId
      - action: slack / get_user_by_email
        fields: email
      - action: workato_variable / declare_list
        fields: name, list_item_schema_json, list_items
      - action: workato_variable / declare_variable
        fields: variables
      - action: workato_variable / declare_list
        fields: name, list_item_schema_json, list_items
      - try [error handling]
        - action: workato_custom_code / invoke_custom_ruby_code
          fields: code, name, code_input, code_output_schema_json
        - catch [error handler]
          - stop
      - action: slack_bot / post_bot_message
        fields: channel, blocks, message, attachment_fields
      - if [and: present]
        - action: slack_bot / upload_file
          fields: channels, thread_ts, file, title, filename, filetype, initial_comment
      - if [and: greater_than]
        - action: slack_bot / post_bot_message
          fields: advanced, channel, blocks
    - action: workato_recipe_function / return_result
      fields: result
    - catch [error handler]
      - stop

---

## Source Recipe (flow\_id=53594265)

Connectors: airtable, email, salesforce
Steps:
- trigger: airtable / new_or_updated_record
  - try [error handling]
    - action: salesforce / search_sobjects
      fields: sobject_name, limit, Id, field_list
    - if [and: greater_than]
      - try [error handling]
        - action: salesforce / **update_sobject**
          fields: sobject_name, id, **At_Risk_Reason__c**, **At_Risk_Status__c**, **Last_QBR_Done_On__c**, **Last_Onsite_Visit__c**, **Customer_Live__c**, **Embedded_Type__c**, (+1 more)
        - action: airtable / update_record
          fields: base_id, table_id, id, fldZQnXwj8GAfTXBu, fld6KOzfxgdmMBh2j
        - catch [error handler]
          - action: airtable / update_record
            fields: base_id, table_id, id, fldZQnXwj8GAfTXBu
    - catch [error handler]
      - action: email / send_mail
        fields: email_type, to, subject, body
      - stop
