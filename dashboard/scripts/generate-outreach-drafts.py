#!/usr/bin/env python3
"""Generate reference outreach drafts for qualified, not-yet-contacted candidates."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

DASHBOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DASHBOARD))
load_dotenv(DASHBOARD / ".env")

from lib.agent_prescreen import parse_agent_recommendation, parse_agent_score  # noqa: E402
from lib.candidate_activity import has_outreach_draft, is_contacted, log_outreach_draft_generated  # noqa: E402
from lib.constants import ROLE_SLUG  # noqa: E402
from lib.r1_draft_llm import redraft_r1_email, redraft_r1_sms  # noqa: E402
from lib.r1_invite import get_calendly_r1_url  # noqa: E402


def should_generate_draft(candidate: dict) -> bool:
    if candidate.get("pipeline_stage") != "qualified":
        return False
    if is_contacted(candidate):
        return False
    score = parse_agent_score(candidate)
    rec = parse_agent_recommendation(candidate)
    if score is None or not rec:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate reference outreach drafts")
    parser.add_argument("--export-batch", default="", help="ZipRecruiter export folder name")
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Missing Supabase credentials", file=sys.stderr)
        return 1

    calendly_url = get_calendly_r1_url()
    if not calendly_url:
        print("Missing CALENDLY_R1_URL — skip draft generation", file=sys.stderr)
        return 0

    sb = create_client(url, key)
    role_id = sb.table("roles").select("id").eq("slug", ROLE_SLUG).execute().data[0]["id"]
    rows = (
        sb.table("candidates")
        .select("*")
        .eq("role_id", role_id)
        .eq("pipeline_stage", "qualified")
        .execute()
        .data
    )

    generated = skipped = 0
    ready: list[dict] = []
    export_batch = args.export_batch.strip() or None

    for candidate in rows:
        if not should_generate_draft(candidate):
            continue
        if has_outreach_draft(sb, candidate["id"]):
            skipped += 1
            continue
        try:
            sms_body = redraft_r1_sms(candidate, calendly_url)
            email_subject, email_body = redraft_r1_email(candidate, calendly_url)
            log_outreach_draft_generated(
                sb,
                candidate["id"],
                sms_body=sms_body,
                email_subject=email_subject,
                email_body=email_body,
                export_batch=export_batch,
            )
            generated += 1
            ready.append(candidate)
            print(f"Draft: {candidate['full_name']}", flush=True)
        except Exception as exc:
            print(f"Draft failed for {candidate['full_name']}: {exc}", file=sys.stderr)

    print(f"Drafts — {generated} generated, {skipped} already had drafts", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
