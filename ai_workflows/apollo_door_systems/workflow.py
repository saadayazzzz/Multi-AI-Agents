"""Demo: Lead-to-Quote-to-Compliance Agent, built for Apollo Door Systems.

Why this workflow: Jerry Richards (Founder, Apollo Door Systems) posted on
LinkedIn that running the company solo means wearing every hat, and that he
uses Claude Code + Notion by hand to handle incoming leads, invoicing,
quotes, and compliance items. This agent automates exactly that manual
triage: it reads an incoming RFQ in plain English, extracts the structured
job details, drafts a priced quote, flags the compliance items a commercial
door job typically needs to check, and produces the record ready to drop
into his existing Notion back office.

This is a sales demo/prototype, not wired into his real systems (no access
to his actual pricing, inventory, or Notion workspace) - it runs on a
realistic sample RFQ so it can be shown in a pitch. Swapping the sample
input for a real inbound email/form and his real price list is the only
change needed to make it live.

Run: python ai_workflows/apollo_door_systems/workflow.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agents.llm import json_out  # noqa: E402

# --------------------------------------------------------------------------- #
# A realistic inbound lead - this is what would normally land in Jerry's
# inbox or a website contact form. In production this is the only thing
# that changes per lead; everything below runs on whatever text comes in.
# --------------------------------------------------------------------------- #
SAMPLE_RFQ = """
From: ops.manager@brightline-warehousing.com
Subject: Quote request - warehouse loading dock doors

Hi, we're expanding our Columbus, OH distribution center and need to add
4 insulated roll-up doors (14ft x 16ft) for the new loading dock bays, plus
replace 2 existing high-speed fabric doors that got damaged in a forklift
incident. We'd also like motion-sensor safety edges on all of them since
we had a near-miss last month. Looking to get this installed within 6 weeks
if possible - we're ramping up for peak season. Can you send a quote and
let us know what permits/inspections we'd need to handle on our end?

Thanks,
Dana Whitfield
Operations Manager, Brightline Warehousing
"""

# Illustrative mock price list - stand-in for Jerry's real pricing. This is
# the one place that needs his actual numbers to go live.
_PRICE_LIST = {
    "insulated_rollup_door": {"unit_price": 4200, "install_per_unit": 1100},
    "high_speed_fabric_door": {"unit_price": 6800, "install_per_unit": 1500},
    "motion_sensor_safety_edge": {"unit_price": 650, "install_per_unit": 150},
}

_EXTRACT_SYS = (
    "You extract structured job details from an inbound commercial door "
    "systems RFQ email for Apollo Door Systems. Only use what's literally "
    "in the email - never invent a detail, quantity, or deadline it doesn't "
    "state. If something isn't mentioned, leave it null/empty."
)

_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "customer_name": {"type": "string"},
        "customer_company": {"type": "string"},
        "site_location": {"type": ["string", "null"]},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_type": {
                        "type": "string",
                        "enum": [
                            "insulated_rollup_door",
                            "high_speed_fabric_door",
                            "motion_sensor_safety_edge",
                            "other",
                        ],
                    },
                    "description": {"type": "string"},
                    "quantity": {"type": "integer"},
                },
                "required": ["item_type", "description", "quantity"],
                "additionalProperties": False,
            },
        },
        "requested_timeline": {"type": ["string", "null"]},
        "stated_reason_or_context": {
            "type": ["string", "null"],
            "description": "why now - e.g. expansion, incident, safety concern",
        },
        "compliance_flags_mentioned": {
            "type": "array",
            "items": {"type": "string"},
            "description": "anything the customer themselves raised about "
            "permits, inspections, or safety",
        },
    },
    "required": [
        "customer_name", "customer_company", "site_location", "line_items",
        "requested_timeline", "stated_reason_or_context", "compliance_flags_mentioned",
    ],
    "additionalProperties": False,
}

# Rule-based, not LLM-generated: real permit/code requirements vary by
# jurisdiction, and an agent confidently inventing specific code citations
# would be actively dangerous to hand a customer. This is an illustrative
# checklist of the categories a commercial door job typically needs to
# check - a real deployment would point each one at Jerry's actual
# jurisdiction-specific reference, not guess the citation.
_COMPLIANCE_RULES = [
    (
        "insulated_rollup_door",
        "Building permit typically required for new/modified loading dock openings - verify with the local building department before install.",
    ),
    (
        "high_speed_fabric_door",
        "Fire separation / UL rating check if the door sits on a fire-rated wall assembly.",
    ),
    (
        "motion_sensor_safety_edge",
        "ANSI/DASMA safety standards apply to powered doors with sensor edges - confirm the sensor model's listing before install.",
    ),
]


def extract_job_details(rfq_text: str) -> dict:
    return json_out(_EXTRACT_SYS, rfq_text, _EXTRACT_SCHEMA, max_tokens=2000)


def draft_quote(job: dict) -> dict:
    lines = []
    subtotal = 0
    for item in job["line_items"]:
        pricing = _PRICE_LIST.get(item["item_type"])
        if not pricing:
            lines.append(
                {
                    "description": item["description"],
                    "quantity": item["quantity"],
                    "unit_price": None,
                    "line_total": None,
                    "note": "needs manual pricing - not in the standard catalog",
                }
            )
            continue
        qty = item["quantity"]
        unit_total = pricing["unit_price"] + pricing["install_per_unit"]
        line_total = unit_total * qty
        subtotal += line_total
        lines.append(
            {
                "description": item["description"],
                "quantity": qty,
                "unit_price": unit_total,
                "line_total": line_total,
                "note": None,
            }
        )
    return {"lines": lines, "subtotal": subtotal}


def compliance_checklist(job: dict) -> list[str]:
    item_types = {item["item_type"] for item in job["line_items"]}
    flags = [note for item_type, note in _COMPLIANCE_RULES if item_type in item_types]
    for extra in job.get("compliance_flags_mentioned") or []:
        flags.append(f"Customer raised directly: {extra}")
    return flags


def to_notion_ready_record(job: dict, quote: dict, compliance: list[str]) -> dict:
    """Shape matching what would get pushed into Jerry's existing Notion
    back office - same idea as this project's own outreach/notion_sync.py."""
    return {
        "Customer": job["customer_company"] or job["customer_name"],
        "Contact": job["customer_name"],
        "Site": job["site_location"] or "",
        "Requested timeline": job["requested_timeline"] or "",
        "Why now": job["stated_reason_or_context"] or "",
        "Quote subtotal": f"${quote['subtotal']:,}",
        "Compliance items to check": compliance,
        "Status": "quote drafted - needs Jerry's review before sending",
    }


def run_demo() -> None:
    print("=" * 70)
    print("APOLLO DOOR SYSTEMS - Lead-to-Quote-to-Compliance Agent (demo)")
    print("=" * 70)
    print("\n[1] Incoming RFQ:")
    print(SAMPLE_RFQ.strip())

    print("\n[2] Extracting structured job details...")
    job = extract_job_details(SAMPLE_RFQ)
    print(f"    Customer: {job['customer_name']} ({job['customer_company']})")
    print(f"    Site: {job['site_location']}")
    print(f"    Timeline requested: {job['requested_timeline']}")
    print(f"    Why now: {job['stated_reason_or_context']}")
    print(f"    Line items: {len(job['line_items'])}")
    for item in job["line_items"]:
        print(f"      - {item['quantity']}x {item['description']}")

    print("\n[3] Drafting quote...")
    quote = draft_quote(job)
    for line in quote["lines"]:
        if line["line_total"] is not None:
            print(f"    {line['quantity']}x {line['description']:<45} ${line['line_total']:>8,}")
        else:
            print(f"    {line['quantity']}x {line['description']:<45} {line['note']}")
    print(f"    {'SUBTOTAL':<50} ${quote['subtotal']:>8,}")

    print("\n[4] Compliance checklist (illustrative - verify against local code):")
    compliance = compliance_checklist(job)
    for flag in compliance:
        print(f"    - {flag}")

    print("\n[5] Record ready for Notion:")
    record = to_notion_ready_record(job, quote, compliance)
    for k, v in record.items():
        print(f"    {k}: {v}")

    print("\n" + "=" * 70)
    print("Done. In production this writes straight into Jerry's Notion")
    print("workspace via the Notion API, the same way this project already")
    print("syncs outreach leads (see outreach/notion_sync.py).")
    print("=" * 70)


if __name__ == "__main__":
    run_demo()
