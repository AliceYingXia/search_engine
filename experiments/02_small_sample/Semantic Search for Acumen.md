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

The feature will support two distinct search intents to cater to different user needs. Crucially, the search scope is strictly limited to the customer’s own recipes. The system must ensure that users can only retrieve results they have permission to access.

## Category 1: Process-Oriented Search (Macro)

* Intent: Broad discovery of recipes involved in end-to-end business workflows.  
* Goal: Map high-level business processes to a comprehensive list of supporting recipes.

## Category 2: Action-Oriented Search (Micro)

* Intent: Targeted discovery of specific business actions or discrete tasks.  
* Goal: Find a specific automation that performs a precise function or connects specific apps.

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

We are requesting **10 seed examples** to kickstart the **Offline Evaluation**:

* **5 Examples for Category 1** (Process-Oriented / Macro)  
* **5 Examples for Category 2** (Action-Oriented / Micro)  
* *Note: This volume is negotiable based on your team’s bandwidth.*

## **Data Statistics & Environment Scope**

To help us architect the retrieval system, please provide:

1. **Recipe Volume:** An estimate of the average and maximum number of recipes a typical customer has.  
2. **Strict Partitioning:** Confirming that all results must be pulled exclusively from the customer’s own library.

## **Comprehensive Mapping is Critical**

For every query, please list **all** recipes and steps within the customer’s environment that satisfy the request. If a relevant asset is omitted from your list but retrieved by the AI, the model will be penalized incorrectly during evaluation.

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

---

## **Why Your Input Matters**

* **Defining "Success":** Your input on offline and online metrics ensures the AI is optimized for actual business value, not just keyword accuracy.  
* **Eliminating False Negatives:** Comprehensive mapping ensures the model is rewarded for finding all valid assets.  
* **Fine-Tuning Rank:** Your relevance tags teach the model to prioritize the most helpful answers at the top of the search results.

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

