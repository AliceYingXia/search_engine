# Project Goal

---

# **Business Proposal: Natural Language Semantic Search for Acumen**

## **Executive Summary**

Currently, the Acumen platform relies on SQL-based querying for recipe discovery. While powerful, this requires users to have technical knowledge of the underlying schema. We propose the integration of a Natural Language Search (NLS) feature, allowing users to discover recipes and specific logic steps using plain English. This shift from "querying data" to "asking questions" will democratize access and significantly reduce the time-to-value for our customers.

---

## **Strategic Motivations**

* **Lowering the Technical Barrier**: By removing the SQL requirement, we enable non-technical business users (Project Managers, HR, Operations) to find automations without needing assistance from technical teams.
* **Improved Discoverability & Reuse**: Organizations often recreate recipes because they cannot find existing ones. Semantic search identifies intent, helping users find and reuse existing assets, which reduces redundant work.
* **Accelerated Onboarding**: New users can navigate complex end-to-end workflows immediately by searching for business outcomes rather than learning table structures.
* **Contextual Intelligence**: Unlike keyword matching, semantic search understands the relationship between business terms (e.g., "onboarding" relating to "hiring" and "provisioning"), providing more accurate results.

---

## **Scope**

The feature will support three distinct search intents to cater to different user needs. Crucially, the search scope is strictly limited to the customer's own recipes. The system must ensure that users can only retrieve results they have permission to access.

## Category 1: Process-Oriented Search (Macro)

* **User:** Business users (Project Managers, HR, Operations)
* **Intent:** Broad discovery of recipes involved in end-to-end business workflows.
* **Goal:** Map high-level business processes to a comprehensive list of supporting recipes.

## Category 2: Action-Oriented Search (Micro)

* **User:** Business and technical users
* **Intent:** Targeted discovery of specific business actions or discrete tasks.
* **Goal:** Find a specific automation that performs a precise function or connects specific apps.

## Category 3: Dependency-Oriented Search (Impact Analysis)

* **User:** Platform admins, integration engineers, connector developers
* **Intent:** Given a known technical artifact — such as a connector action, a field/datapill, or an API endpoint — find all recipes that depend on it.
* **Goal:** Enable safe change management by surfacing the full impact surface before a change is made.
* **Current Scope Note:** Full precision for this category requires step-level indexing, which is planned for a future phase. In the current phase using recipe-level summaries, results will provide a useful but partial signal. Category 3 is included here to define the intent and seed dataset structure; full evaluation benchmarking will be aligned to the step-level indexing milestone.

---

# Evaluation Framework

---

# **Evaluation Framework**

To ensure this feature meets enterprise standards, we need the Business Technology (BT) team to help define and validate our **dual-evaluation metrics**.

## **1\. Offline Evaluation (Ground Truth & Synthetic Testing)**

This is where we need your immediate expertise to build the "Gold Standard" for the model before it goes live.

* **Seed Dataset Creation:** Providing real-world query-to-recipe mappings.
* **Synthetic Data Audit:** Reviewing LLM-generated evaluation datasets based on your seeds to ensure the "distilled" logic remains accurate.
* **Relevance Benchmarking:** Defining what constitutes a "Strong" vs. "Weak" match to help us calculate **Precision** and **Recall**.

## **2\. Online Evaluation (User Success Metrics)**

Once the feature is live, we will move to online evaluation to track real-world performance. We would like to collaborate with you to define these success signals, which may include:

* **Click-Through Rate (CTR):** Does the user click one of the top 3 suggested recipes?
* **Success Rate:** Does the user open a recipe and *not* perform a different search immediately after?
* **Search Refinement:** How often do users have to rephrase their natural language query?

---

# **Request for Expert Seed Dataset**

## **What We Need From You**

We are requesting seed examples across all three categories to kickstart the **Offline Evaluation**:

* **5 Examples for Category 1** (Process-Oriented / Macro)
* **5 Examples for Category 2** (Action-Oriented / Micro)
* **5 Examples for Category 3** (Dependency-Oriented / Impact Analysis) *(lower priority — can be deferred to align with step-level indexing milestone)*
* *Note: Volume is negotiable based on your team's bandwidth.*

## **Data Statistics & Environment Scope**

To help us architect the retrieval system, please provide:

1. **Recipe Volume:** An estimate of the average and maximum number of recipes a typical customer has.
2. **Strict Partitioning:** Confirming that all results must be pulled exclusively from the customer's own library.

## **Comprehensive Mapping is Critical**

For every query, please list **all** recipes and steps within the customer's environment that satisfy the request. If a relevant asset is omitted from your list but retrieved by the AI, the model will be penalized incorrectly during evaluation.

---

## **Seed Dataset Structure & Examples**

| Relevance Tag | Definition |
| :---- | :---- |
| **Strongly Related** | The primary recipe/step designed specifically for this task. |
| **Weakly Related** | Recipes that are tangentially involved or provide supporting data. |

#### **Example 1: Category 1 (Process-Oriented)**

**Query:** *"Which recipes handle our employee onboarding?"*

| Recipe ID | Description/Logic | Relevance Tag |
| :---- | :---- | :---- |
| RECIPE\_001 | **Workday to Okta:** Provisions new user accounts. | Strongly Related |
| RECIPE\_002 | **ServiceNow Ticket:** Creates "New Hardware" request. | Strongly Related |
| RECIPE\_099 | **Slack Notification:** General "Welcome" bot. | Weakly Related |

#### **Example 2: Category 2 (Action-Oriented)**

**Query:** *"How do we notify the team when a NetSuite invoice is overdue?"*

| Recipe ID | Step Name / ID | Description/Logic | Relevance Tag |
| :---- | :---- | :---- | :---- |
| RECIPE\_102 | Step 4: Post to Slack | **Conditional:** If Status \== 'Overdue' \-\> Send Slack | Strongly Related |
| RECIPE\_102 | Step 1: Search Records | **Trigger:** Polls NetSuite for all updated invoices. | Weakly Related |
| RECIPE\_105 | Step 2: Sync Email | **Email Sync:** Archives NetSuite comms to Gmail. | Weakly Related |

#### **Example 3: Category 3 (Dependency-Oriented — Field Change)**

**Query:** *"If I update the picklist for Salesforce.Opportunity.Country, which recipes will be affected?"*

| Recipe ID | Step ID | Connector | Action / Field / Endpoint | Usage Type | Relevance Tag |
| :---- | :---- | :---- | :---- | :---- | :---- |
| RECIPE\_045 | Step 3: Update Record | Salesforce | Update Object: Opportunity.Country | Write | Strongly Related |
| RECIPE\_078 | Step 1: New/Updated Record | Salesforce | Trigger on Opportunity.Country | Trigger | Strongly Related |
| RECIPE\_031 | Step 2: Search Records | Salesforce | Filters/Branches on Opportunity.Country | Read | Weakly Related |

> **Note on Usage Type:** This field distinguishes how a recipe interacts with the artifact — whether it **writes** to it, **reads** from it, or uses it as a **trigger** condition. This is especially useful for impact analysis: a schema change typically breaks recipes that *write* to a field, while a picklist value change may affect recipes that *filter or branch* on that field. Capturing this distinction helps prioritize which recipes need immediate attention.

#### **Example 4: Category 3 (Dependency-Oriented — API/SDK Change)**

**Query:** *"An internal API is changing schema. I need to find all recipes that use a specific SDK action (GET acme.com/customers endpoint)."*

| Recipe ID | Step ID | Connector | Action / Field / Endpoint | Usage Type | Relevance Tag |
| :---- | :---- | :---- | :---- | :---- | :---- |
| RECIPE\_112 | Step 1: HTTP Request | HTTP SDK | GET acme.com/customers | Read | Strongly Related |
| RECIPE\_089 | Step 3: HTTP Request | HTTP SDK | GET acme.com/customers | Read | Strongly Related |
| RECIPE\_056 | Step 2: HTTP Request | HTTP SDK | GET acme.com/customers?filter=active | Read | Weakly Related |

---

## **Why Your Input Matters**

* **Defining "Success":** Your input on offline and online metrics ensures the AI is optimized for actual business value, not just keyword accuracy.
* **Eliminating False Negatives:** Comprehensive mapping ensures the model is rewarded for finding all valid assets.
* **Fine-Tuning Rank:** Your relevance tags teach the model to prioritize the most helpful answers at the top of the search results.

---

# More Sample Queries

## **Category 1 — Find Recipes by Business Process**

The user describes a business process or workflow. The system should return a ranked list of recipes that contribute to that process.

Expected output: recipe list, ranked by relevance, with process classification label.

### **Quote-to-Cash**

1. Which recipes are involved in the Quote-to-Cash process?
2. Find all automations that handle order creation from Salesforce to NetSuite.
3. What recipes are part of the sales order fulfillment workflow?
4. Show me the recipes that run when a Salesforce opportunity is closed-won.
5. Which automations handle invoice generation after a sale is confirmed?

### **Procure-to-Pay**

6. Which recipes are involved in the Procure-to-Pay process?
7. Find automations that handle purchase order approval and downstream actions.
8. What recipes run when a vendor invoice is received?
9. Which automations are part of the supplier onboarding workflow?

### **Employee Lifecycle**

10. Find all recipes involved in employee onboarding.
11. Which automations run when a new hire is created in Workday?
12. Show me the recipes that handle employee offboarding across HR and IT systems.
13. What recipes are triggered when an employee changes department or role?
14. Which automations handle deprovisioning of access when an employee leaves?

### **Lead-to-Revenue**

15. Find recipes that are part of the lead management process.
16. Which automations handle lead routing and assignment in Salesforce?
17. What recipes run when a marketing qualified lead is converted to a contact?

### **General / Cross-process**

18. Which recipes are involved in customer master data synchronization?
19. Find all automations that are part of the financial close process.
20. What recipes handle reconciliation between systems at end of month?

---

## **Category 2 — Find Recipes by Specific Action or Outcome**

The user describes a discrete business action or outcome — a specific thing that should happen, not a full workflow. The query is not tied to a named process. The result may be one recipe or several, and multiple matches are expected and valid (e.g., different teams may have built recipes for the same action, or the action may appear as a step in multiple independent flows).

Expected output: ranked list of matching recipes with confidence score. "Not found" is a valid result.

### **Notifications & Alerts**

1. Is there an automation that sends a Slack notification when an invoice is overdue?
2. Which recipe sends an email alert when a Workato job fails?
3. Is there a recipe that notifies the sales team in Slack when a deal is closed-won?
4. Find the automation that pages the on-call engineer when a critical recipe errors.
5. Is there a recipe that sends a daily summary of new leads to the sales manager?

### **Data Sync**

6. Is there a recipe that syncs customer data between Salesforce and HubSpot?
7. Which recipe keeps the employee headcount table in sync between Workday and the data warehouse?
8. Find the automation that replicates Salesforce Account updates to NetSuite Customer records.
9. Is there a recipe that syncs product catalog data from the ERP to the e-commerce platform?
10. Which recipe updates the CRM when a support ticket is resolved in Zendesk?

### **Record Creation**

11. Which recipe creates a NetSuite vendor bill when a PO is approved in Coupa?
12. Is there an automation that creates a Jira ticket when a Salesforce case is escalated?
13. Which recipe creates a Workday position when a headcount request is approved?
14. Find the recipe that creates a NetSuite Sales Order when a Salesforce Opportunity closes.
15. Is there a recipe that creates an onboarding checklist in Asana when a new hire starts?

### **Data Transformation & Enrichment**

16. Which recipe enriches new Salesforce leads with data from Clearbit?
17. Is there an automation that converts currency values before writing to NetSuite?
18. Find the recipe that maps Salesforce opportunity stages to NetSuite order statuses.
19. Which recipe normalizes phone number formats when syncing contacts between systems?

### **Approvals & Routing**

20. Is there a recipe that routes purchase requisitions for approval based on spend threshold?
21. Which automation assigns incoming support tickets to the correct team based on category?
22. Find the recipe that escalates overdue approvals to a manager after 48 hours.

---

## **Category 3 — Find Recipes by Technical Dependency (Impact Analysis)**

The user knows a specific technical artifact is changing — a connector action, a field/datapill, or an API endpoint — and needs to find all recipes that depend on it. The goal is to understand the blast radius before making the change.

Expected output: ranked list of affected recipes and steps, with usage type (Write / Read / Trigger). "Not found" is a valid result.

> **Current Limitation:** In the current phase, search is powered by recipe-level summaries. Results for this category will provide a useful but partial signal. Full precision requires step-level indexing, which is planned for a future phase.

### **Connector Action Changes**

1. Which recipes use the Workday *Call Operation: Add Additional Job* action?
2. Find all recipes that use the Salesforce *Query Records (Legacy)* action.
3. Which automations use the NetSuite *Search Records* action?
4. Is there a recipe that uses the ServiceNow *Create Record* action for incident management?
5. Find all recipes that trigger on the Workday *New/Updated Worker* event.

### **Field / Datapill Changes**

6. If I update the `Custom_Status__c` field in my Salesforce Opportunity object, which recipes are impacted?
7. Which recipes reference the `Employee.Department` datapill from Workday?
8. If I add a new required field to the NetSuite Sales Order object, which recipes write to it?
9. If I update the picklist for `Salesforce.Opportunity.Country`, which recipes will be affected?
10. Find all recipes that map the `Invoice.DueDate` field from NetSuite.

### **API / SDK Endpoint Changes**

11. An internal API is changing schema. I need to find all recipes that use a specific SDK action (`GET acme.com/customers` endpoint).
12. Find all recipes that use an HTTP action hitting `/api/v1/orders`.
13. If the `/api/v2/employees` endpoint schema changes, which recipes are affected?
14. Which recipes use an SDK action against the `POST acme.com/invoices` endpoint?
