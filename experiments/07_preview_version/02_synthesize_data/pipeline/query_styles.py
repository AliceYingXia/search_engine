from dataclasses import dataclass


@dataclass
class QueryStyle:
    """
    All per-category configuration that varies between query styles.

    Swap this object to change how queries are generated, how relevance is
    defined, and how examples are evaluated — no other code changes needed.
    """
    name: str                    # e.g. "category1"  — used in file names
    query_id_prefix: str         # e.g. "q"  → query_id = "{author_id}_q{n}"
    system_prompt: str           # Phase 1: query generation prompt
    relevance_definitions: str   # Phase 2: label definitions injected into relevance prompt
    quality_system_prompt: str   # Eval:    query quality assessment prompt


# ---------------------------------------------------------------------------
# Category 1 — process-oriented queries
# ---------------------------------------------------------------------------

_CAT1_SYSTEM_PROMPT = """\
You are helping build an evaluation dataset for a semantic search system \
over Workato automation recipes.

Your task: given a recipe_summary, write exactly ONE Category 1 \
(process-oriented) search query that a non-technical business user might \
type to discover this recipe.

Category 1 queries describe a high-level business workflow or process — \
NOT a specific tool action or connector name.

Good examples:
  "Which recipes handle our employee onboarding?"
  "Find all automations involved in the Quote-to-Cash process."
  "What recipes run when a new hire is created in our HR system?"
  "Which automations are part of our monthly financial close?"
  "Which recipes are involved in customer master data synchronization?"
  "Find recipes that are part of the lead management process."

Rules:
  - One short sentence only — as a user would type in a search box.
  - Use plain business language (no connector names, no technical jargon).
  - Do not mention Workato.
  - Do not combine multiple requirements or clauses into one query.
  - Ground the query only in what recipe_summary shows.
  - Return only the query string — no quotes, no explanation."""

_CAT1_RELEVANCE_DEFINITIONS = """\
  Strongly Related : The recipe is a primary component of the business
                     process described by the query.
  Weakly Related   : The recipe plays a supporting or peripheral role
                     in that process.
  Not Related      : No meaningful connection to the query."""

_CAT1_QUALITY_PROMPT = """\
You are evaluating the quality of search queries in an evaluation dataset for \
a semantic search system over Workato automation recipes.

Category 1 queries describe a broad business process rather than a specific \
action. A good Category 1 query:
  - Is unambiguous and clearly written.
  - Describes a process or goal, not a specific system action.
  - Could plausibly match several different automation recipes.

You will be given a query and the recipe summary of the source recipe that \
generated it.

Return a single JSON object with exactly these keys:
  "clarity"     : "Good" | "Acceptable" | "Poor"
  "specificity" : "Good" | "Acceptable" | "Poor"
  "comment"     : one sentence explaining your ratings

Return ONLY valid JSON — no markdown fences, no explanation."""


# ---------------------------------------------------------------------------
# Category 2 — action-oriented queries
# ---------------------------------------------------------------------------

_CAT2_SYSTEM_PROMPT = """\
You are helping build an evaluation dataset for a semantic search system \
over Workato automation recipes.

Your task: given a recipe_summary, write exactly ONE Category 2 \
(action-oriented) search query that a business user might type to find \
this specific automation.

Category 2 queries describe a specific action or outcome — they name the \
concrete systems, the trigger, and the result. They are distinct from \
Category 1 queries, which describe broad business processes.

Good examples:
  "Is there an automation that sends a Slack notification when an invoice is overdue?"
  "Which recipe creates a NetSuite vendor bill when a PO is approved in Coupa?"
  "Find the automation that pages the on-call engineer when a critical recipe errors."
  "Is there a recipe that syncs customer data between Salesforce and HubSpot?"
  "Which recipe creates a Workday position when a headcount request is approved?"
  "Find the recipe that maps Salesforce opportunity stages to NetSuite order statuses."
  "Which recipe updates the CRM when a support ticket is resolved in Zendesk?"
  "Find the recipe that escalates overdue approvals to a manager after 48 hours."

Rules:
  - One short sentence only — as a user would type in a search box.
  - Be specific: name the systems, the trigger, and the outcome when evident.
  - Do not mention Workato.
  - Ground the query only in what the recipe summary shows.
  - Return only the query string — no quotes, no explanation."""

_CAT2_RELEVANCE_DEFINITIONS = """\
  Strongly Related : The recipe implements the exact automation described —
                     the trigger, action, and systems closely match the query.
  Weakly Related   : The recipe performs a similar or adjacent action but
                     differs in trigger, system, or outcome.
  Not Related      : No meaningful connection to the query."""

_CAT2_QUALITY_PROMPT = """\
You are evaluating the quality of search queries in an evaluation dataset for \
a semantic search system over Workato automation recipes.

Category 2 queries describe a specific action-oriented automation. A good \
Category 2 query:
  - Is unambiguous and clearly written.
  - Names concrete systems, trigger events, and outcomes.
  - Is specific enough to distinguish one automation from others.

You will be given a query and the recipe summary of the source recipe that \
generated it.

Return a single JSON object with exactly these keys:
  "clarity"     : "Good" | "Acceptable" | "Poor"
  "specificity" : "Good" | "Acceptable" | "Poor"
  "comment"     : one sentence explaining your ratings

Return ONLY valid JSON — no markdown fences, no explanation."""


# ---------------------------------------------------------------------------
# Category 3 — dependency / impact-surface queries
# ---------------------------------------------------------------------------

_CAT3_SYSTEM_PROMPT = """\
You are helping build an evaluation dataset for a semantic search system \
over Workato automation recipes.

Your task: given a recipe_summary, write exactly ONE Category 3 \
(dependency-oriented) search query that a platform admin, integration engineer, \
or connector developer might type to find all recipes that depend on a specific \
technical artifact — such as a connector action, a field/datapill, or an API \
endpoint — before making a change to it.

Category 3 queries name a concrete technical artifact (connector action, \
field name, datapill path, API endpoint, SDK action) and ask which recipes \
use or reference it. They are motivated by change-impact analysis, not by \
business process discovery.

Good examples:
  "If the Workday Call Operation: Add Additional Job action is updated, which recipes will be affected?"
  "If I update the Custom_Status__c field in my Salesforce Opportunity object, which recipes will be impacted?"
  "If the Employee.Department datapill from Workday is renamed, which recipes will be affected?"
  "If I update the picklist for Salesforce.Opportunity.Country, which recipes will be affected?"
  "If an internal API is changing schema, which recipes will be affected by the specific SDK action (GET acme.com/customers endpoint)?"
Rules:
  - One short sentence only — as a user would type in a search box.
  - Name the specific technical artifact: connector, action name, field, \
datapill path, or API endpoint.
  - Frame the query around dependency or impact ("which recipes use / \
reference / depend on / are affected by").
  - Do not mention Workato.
  - Ground the query only in what the recipe_summary shows.
  - Return only the query string — no quotes, no explanation."""

_CAT3_RELEVANCE_DEFINITIONS = """\
  Strongly Related : The recipe directly uses or references the exact \
technical artifact named in the query (the connector action, field, datapill, \
or endpoint is present in the recipe).
  Weakly Related   : The recipe interacts with the same connector or system \
but does not use the specific artifact named.
  Not Related      : No meaningful connection to the query."""

_CAT3_QUALITY_PROMPT = """\
You are evaluating the quality of search queries in an evaluation dataset for \
a semantic search system over Workato automation recipes.

Category 3 queries describe a dependency or change-impact lookup — they name \
a specific technical artifact and ask which recipes depend on it. A good \
Category 3 query:
  - Is unambiguous and clearly written.
  - Names a concrete technical artifact (connector action, field, datapill \
path, API endpoint, or SDK action).
  - Is framed around dependency or impact (not general process discovery).

You will be given a query and the recipe summary of the source recipe that \
generated it.

Return a single JSON object with exactly these keys:
  "clarity"     : "Good" | "Acceptable" | "Poor"
  "specificity" : "Good" | "Acceptable" | "Poor"
  "comment"     : one sentence explaining your ratings

Return ONLY valid JSON — no markdown fences, no explanation."""


# ---------------------------------------------------------------------------
# Pre-built instances
# ---------------------------------------------------------------------------

CAT1 = QueryStyle(
    name="category1",
    query_id_prefix="q",
    system_prompt=_CAT1_SYSTEM_PROMPT,
    relevance_definitions=_CAT1_RELEVANCE_DEFINITIONS,
    quality_system_prompt=_CAT1_QUALITY_PROMPT,
)

CAT2 = QueryStyle(
    name="category2",
    query_id_prefix="c2q",
    system_prompt=_CAT2_SYSTEM_PROMPT,
    relevance_definitions=_CAT2_RELEVANCE_DEFINITIONS,
    quality_system_prompt=_CAT2_QUALITY_PROMPT,
)

CAT3 = QueryStyle(
    name="category3",
    query_id_prefix="c3q",
    system_prompt=_CAT3_SYSTEM_PROMPT,
    relevance_definitions=_CAT3_RELEVANCE_DEFINITIONS,
    quality_system_prompt=_CAT3_QUALITY_PROMPT,
)
