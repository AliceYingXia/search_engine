"""
check_description_consistency.py
==================================

Uses GPT-4o to verify whether the LLM-generated description fields
(usage, short_user_intent, verbose_user_intent) are consistent with
the recipe_summary extracted directly from the raw recipe JSON.

What this script does
---------------------
1. Rebuilds the 801-row recipe-level DataFrame from:
     - 02_cleaning/cleaned/*_tracking.json
     - 02_cleaning/cleaned/*_semantic.json
     - data/gpt-5.2-*_descriptions_recipe.parquet
2. For each recipe, sends ONE GPT-4o call containing:
     - recipe_summary  (ground truth — structural)
     - short_user_intent, usage, verbose_user_intent  (LLM-generated)
   The model returns a JSON consistency assessment for each field.
3. Writes results to consistency_results.csv (one row per recipe).
4. Resumes from a checkpoint file if interrupted.

Output columns
--------------
  flow_id, version_no, author_id
  short_user_intent_ok    : bool  — is short_user_intent consistent?
  usage_ok                : bool  — is usage consistent?
  verbose_user_intent_ok  : bool  — is verbose_user_intent consistent?
  short_user_intent_issue : str   — brief reason if not ok (else empty)
  usage_issue             : str   — brief reason if not ok (else empty)
  verbose_user_intent_issue: str  — brief reason if not ok (else empty)
  all_ok                  : bool  — True only if all three are ok

Usage
-----
    python check_description_consistency.py
"""

import csv
import json
import os
import re
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from openai import OpenAI
import pandas as pd

# ---------------------------------------------------------------------------
# Paths & config
# ---------------------------------------------------------------------------
BASE_DIR     = Path(__file__).parent
CLEANED_DIR  = BASE_DIR.parent / "02_cleaning" / "cleaned"
DATA_DIR     = BASE_DIR.parent / "data"
ENV_PATH     = BASE_DIR.parent.parent / "workato-msga-temp" / "workato-msga-temp" / ".env"
OUTPUT_PATH  = BASE_DIR / "consistency_results.csv"
CHECKPOINT   = BASE_DIR / "consistency_checkpoint.json"

MODEL = "gpt-4o"

DESCRIPTIONS_GLOB = "gpt-5.2-*_bt_prod_descriptions_recipe.parquet"

load_dotenv(ENV_PATH)


# ---------------------------------------------------------------------------
# Build recipe DataFrame (same logic as notebook cell xw97uo7c57)
# ---------------------------------------------------------------------------

def load_recipe_df() -> pd.DataFrame:
    tracking_rows = []
    for tf in sorted(CLEANED_DIR.glob("*_tracking.json")):
        trk   = json.loads(tf.read_text())
        steps = trk.get("steps", [])
        tracking_rows.append({
            "flow_id":    trk["flow_id"],
            "version_no": trk["version_no"],
            "author_id":  trk["author_id"],
        })

    semantic_rows = []
    for sf in sorted(CLEANED_DIR.glob("*_semantic.json")):
        sem = json.loads(sf.read_text())
        semantic_rows.append({
            "flow_id":        sem["flow_id"],
            "version_no":     sem["version_no"],
            "recipe_summary": sem.get("recipe_summary", ""),
        })

    desc_files = sorted(DATA_DIR.glob(DESCRIPTIONS_GLOB))
    if not desc_files:
        raise FileNotFoundError(f"No descriptions parquet found matching {DESCRIPTIONS_GLOB} in {DATA_DIR}")
    df_desc = pd.read_parquet(desc_files[0])

    df = (
        pd.DataFrame(tracking_rows)
        .merge(pd.DataFrame(semantic_rows), on=["flow_id", "version_no"], how="left")
        .merge(df_desc[["flow_id", "short_user_intent", "usage", "verbose_user_intent"]],
               on="flow_id", how="left")
    )
    return df


# ---------------------------------------------------------------------------
# LLM consistency check
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a quality-control reviewer for Workato automation recipe descriptions.

You will be given:
  1. recipe_summary — the ground truth: a structural outline of the recipe extracted
     directly from the raw recipe JSON. It lists the connectors used and a step-by-step
     tree of the recipe's actions. This is always accurate.
  2. Three LLM-generated description fields:
       short_user_intent    — one sentence: what the user wants this recipe to do
       usage                — a paragraph: when and why a user would use this recipe
       verbose_user_intent  — a full paragraph: detailed natural-language user intent

For each of the three fields, decide:
  - consistent: true  — the field accurately reflects what the recipe does
                         (minor paraphrasing or added context is fine)
  - consistent: false — the field contradicts the recipe structure, mentions connectors
                         or actions not present in the recipe, or describes a
                         fundamentally different process

Return a single JSON object with this exact structure:
{
  "short_user_intent":     { "consistent": true/false, "issue": "<brief reason if false, else empty string>" },
  "usage":                 { "consistent": true/false, "issue": "<brief reason if false, else empty string>" },
  "verbose_user_intent":   { "consistent": true/false, "issue": "<brief reason if false, else empty string>" }
}

Return ONLY valid JSON — no markdown fences, no explanation."""


def check_consistency(client: OpenAI, row: dict) -> dict | None:
    """
    Send one GPT-4o call for a single recipe.
    Returns parsed dict or None on failure.
    """
    user_msg = (
        f"recipe_summary:\n{row['recipe_summary']}\n\n"
        f"short_user_intent:\n{row['short_user_intent']}\n\n"
        f"usage:\n{row['usage']}\n\n"
        f"verbose_user_intent:\n{row['verbose_user_intent']}"
    )

    for attempt in range(2):
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.0,
            max_tokens=400,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if attempt == 0:
                print("    JSON parse error — retrying ...")
                time.sleep(1)
            else:
                print("    JSON parse error on retry — skipping")
                return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

FIELDNAMES = [
    "flow_id", "version_no", "author_id",
    "short_user_intent_ok", "usage_ok", "verbose_user_intent_ok",
    "short_user_intent_issue", "usage_issue", "verbose_user_intent_issue",
    "all_ok",
]


def main():
    # Load checkpoint (set of already-processed flow_ids)
    done: set[int] = set()
    if CHECKPOINT.exists():
        done = set(json.loads(CHECKPOINT.read_text()))
        print(f"Resuming — {len(done)} recipes already processed.\n")

    client = OpenAI(
        api_key=os.getenv("DIRECT_OPENAI_API_KEY"),
        http_client=httpx.Client(verify=False),
    )

    print("Building recipe DataFrame ...")
    df = load_recipe_df()
    print(f"  {len(df)} recipes loaded\n")

    # Open CSV in append mode if resuming, write mode otherwise
    write_header = not OUTPUT_PATH.exists() or len(done) == 0
    csv_file = OUTPUT_PATH.open("a" if not write_header else "w", newline="", encoding="utf-8")
    writer   = csv.DictWriter(csv_file, fieldnames=FIELDNAMES)
    if write_header:
        writer.writeheader()

    total     = len(df)
    processed = len(done)

    try:
        for _, row in df.iterrows():
            flow_id = int(row["flow_id"])
            if flow_id in done:
                continue

            processed += 1
            print(f"[{processed:03d}/{total}] flow_id={flow_id}  author={row['author_id']} ...",
                  end=" ", flush=True)

            result = check_consistency(client, row)

            if result is None:
                # Skip and don't mark as done — will retry on next run
                print("SKIPPED")
                continue

            sui  = result.get("short_user_intent",   {})
            usg  = result.get("usage",               {})
            vui  = result.get("verbose_user_intent", {})

            sui_ok  = bool(sui.get("consistent", True))
            usg_ok  = bool(usg.get("consistent", True))
            vui_ok  = bool(vui.get("consistent", True))
            all_ok  = sui_ok and usg_ok and vui_ok

            status = "OK" if all_ok else f"ISSUES({'+'.join(k for k, v in [('SUI', sui_ok), ('USG', usg_ok), ('VUI', vui_ok)] if not v)})"
            print(status)

            writer.writerow({
                "flow_id":                   flow_id,
                "version_no":                int(row["version_no"]),
                "author_id":                 int(row["author_id"]),
                "short_user_intent_ok":      sui_ok,
                "usage_ok":                  usg_ok,
                "verbose_user_intent_ok":    vui_ok,
                "short_user_intent_issue":   sui.get("issue", ""),
                "usage_issue":               usg.get("issue", ""),
                "verbose_user_intent_issue": vui.get("issue", ""),
                "all_ok":                    all_ok,
            })
            csv_file.flush()

            done.add(flow_id)
            CHECKPOINT.write_text(json.dumps(sorted(done)))

    finally:
        csv_file.close()

    # Summary
    results = pd.read_csv(OUTPUT_PATH)
    n        = len(results)
    all_ok   = results["all_ok"].sum()
    sui_ok   = results["short_user_intent_ok"].sum()
    usg_ok   = results["usage_ok"].sum()
    vui_ok   = results["verbose_user_intent_ok"].sum()

    print("\n" + "=" * 60)
    print(f"Done.  {n} recipes assessed.")
    print(f"  All fields consistent      : {all_ok:4d} / {n}  ({100*all_ok/n:.1f}%)")
    print(f"  short_user_intent OK       : {sui_ok:4d} / {n}  ({100*sui_ok/n:.1f}%)")
    print(f"  usage OK                   : {usg_ok:4d} / {n}  ({100*usg_ok/n:.1f}%)")
    print(f"  verbose_user_intent OK     : {vui_ok:4d} / {n}  ({100*vui_ok/n:.1f}%)")
    print(f"\n  Output  : {OUTPUT_PATH}")

    # Print first few inconsistencies
    issues = results[~results["all_ok"]]
    if not issues.empty:
        print(f"\n  Sample inconsistencies ({min(5, len(issues))} of {len(issues)}):")
        for _, r in issues.head(5).iterrows():
            print(f"\n  flow_id={r['flow_id']}  author={r['author_id']}")
            if not r["short_user_intent_ok"]:
                print(f"    short_user_intent: {r['short_user_intent_issue']}")
            if not r["usage_ok"]:
                print(f"    usage:             {r['usage_issue']}")
            if not r["verbose_user_intent_ok"]:
                print(f"    verbose:           {r['verbose_user_intent_issue']}")


if __name__ == "__main__":
    main()
