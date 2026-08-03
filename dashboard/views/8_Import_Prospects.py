"""Import prospect candidates from CSV (+ optional resumes) for Pipeline outreach."""

from __future__ import annotations

import re
from datetime import date

import pandas as pd
import streamlit as st

from lib.agent_prescreen import parse_agent_recommendation, parse_agent_score
from lib.agent_prescreen_runner import (
    prescreen_candidate_from_text,
    resolve_scoring_text,
)
from lib.constants import APP_NAME, get_selected_role_slug, get_selected_role_title
from lib.llm_client import llm_configured
from lib.prospect_import import (
    ALL_COLUMNS,
    classify_duplicates,
    instructions_markdown,
    match_resume_path,
    new_import_batch_id,
    parse_prospect_csv,
    role_id_for_slug,
    save_uploaded_resumes,
    scoring_source_label,
    template_csv_bytes,
    upsert_prospect,
)
from lib.rubric import qualifies_for_pipeline
from lib.supabase_client import get_supabase

st.title("Import prospects")
st.caption(
    f"{APP_NAME} · {get_selected_role_title()} · "
    "CSV + resumes/LinkedIn → Pipeline (SMS & email ready)"
)

role_slug = get_selected_role_slug()
sb = get_supabase()

try:
    role_id = role_id_for_slug(sb, role_slug)
except Exception as exc:
    st.error(str(exc))
    st.stop()

st.info(
    f"Imports apply to the sidebar **Position**: `{get_selected_role_title()}`. "
    "Switch Position before uploading if needed."
)

with st.expander("CSV format & resume naming", expanded=True):
    st.markdown(instructions_markdown(role_slug))
    st.download_button(
        "Download CSV template",
        data=template_csv_bytes(),
        file_name="prospect_import_template.csv",
        mime="text/csv",
        type="primary",
    )
    st.caption("Columns: " + ", ".join(ALL_COLUMNS))

st.subheader("1. Upload files")
csv_file = st.file_uploader("Prospect CSV", type=["csv"], key="prospect_csv")
resume_files = st.file_uploader(
    "Resume PDFs (optional, multiple)",
    type=["pdf"],
    accept_multiple_files=True,
    key="prospect_resumes",
)

score_after = st.checkbox(
    "Score after import (resume → LinkedIn paste → LinkedIn URL → skip)",
    value=True,
)
auto_update_dupes = st.checkbox(
    "Process without asking — auto-update existing candidates with the same email or phone",
    value=False,
)

if not csv_file:
    st.stop()

prospects, file_errors = parse_prospect_csv(csv_file.getvalue(), role_slug=role_slug)
if file_errors:
    for err in file_errors:
        st.error(err)
    st.stop()

uploaded_map: dict = {}
if resume_files:
    uploaded_map = save_uploaded_resumes(
        [(f.name, f.getvalue()) for f in resume_files],
        role_slug=role_slug,
    )
    st.caption(f"Saved {len(resume_files)} resume PDF(s) to `imports/inbox/Prospects/`.")

valid = [p for p in prospects if p.is_valid]
invalid = [p for p in prospects if not p.is_valid]

st.subheader("2. Preview")
m1, m2, m3 = st.columns(3)
m1.metric("Rows", len(prospects))
m2.metric("Valid", len(valid))
m3.metric("Invalid", len(invalid))

preview_rows = []
for p in prospects:
    resume_path = match_resume_path(p, uploaded_map)
    preview_rows.append(
        {
            "Row": p.row_number,
            "Name": p.full_name,
            "Email": p.email,
            "Phone": p.phone or "—",
            "Source": p.source,
            "Imported": p.date_imported,
            "Resume": resume_path.name if resume_path else (p.resume_filename or "—"),
            "LinkedIn": "yes" if p.linkedin_url or p.linkedin_text else "—",
            "Status": "OK" if p.is_valid else "; ".join(p.errors),
            "Warnings": "; ".join(p.warnings) if p.warnings else "—",
        }
    )
st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)

if invalid:
    st.warning(f"{len(invalid)} row(s) have errors and will be skipped.")

fresh, dupes = classify_duplicates(sb, role_id=role_id, prospects=valid)
st.write(
    f"**{len(fresh)}** new · **{len(dupes)}** email already in "
    f"`{get_selected_role_title()}`"
)

dupe_actions: dict[str, str] = {}
if dupes and not auto_update_dupes:
    st.subheader("3. Duplicates — choose Skip or Update")
    st.caption("Same email already exists for this position.")
    action_rows = []
    for hit in dupes:
        key = hit.prospect.email.lower()
        default = st.session_state.get(f"dupe_action_{key}", "Update")
        action_rows.append(
            {
                "Email": hit.prospect.email,
                "Incoming": hit.prospect.full_name,
                "Existing": hit.existing.get("full_name"),
                "Existing stage": hit.existing.get("pipeline_stage"),
                "Action": default,
            }
        )
    edited = st.data_editor(
        pd.DataFrame(action_rows),
        column_config={
            "Action": st.column_config.SelectboxColumn(
                "Action",
                options=["Update", "Skip"],
                required=True,
            )
        },
        disabled=["Email", "Incoming", "Existing", "Existing stage"],
        hide_index=True,
        use_container_width=True,
        key="prospect_dupe_editor",
    )
    for _, row in edited.iterrows():
        dupe_actions[str(row["Email"]).lower()] = str(row["Action"]).lower()
elif dupes and auto_update_dupes:
    st.info(f"Auto-update enabled — {len(dupes)} existing candidate(s) will be updated.")
    for hit in dupes:
        dupe_actions[hit.prospect.email.lower()] = "update"


def _apply_score_notes(row: dict, prospect, source: str) -> tuple[int | None, str | None]:
    score = parse_agent_score(row, role_slug=role_slug)
    rec = parse_agent_recommendation(row, role_slug=role_slug)
    if score is None or not rec:
        return None, None
    note = (
        f"Resume pre-screen {date.today().isoformat()} · "
        f"{score}/100 · {rec} · via {scoring_source_label(source)}"
    )
    old = (row.get("notes") or "").strip()
    if re.search(r"Resume pre-screen \d{4}-\d{2}-\d{2}", old):
        new_notes = re.sub(
            r"Resume pre-screen \d{4}-\d{2}-\d{2} · [^\n]+",
            note,
            old,
        )
    else:
        new_notes = f"{note}\n\n{old}".strip() if old else note
    patch: dict = {"notes": new_notes}
    if row.get("pipeline_stage") in ("identified", "qualified"):
        patch["pipeline_stage"] = (
            "qualified"
            if qualifies_for_pipeline(score, rec, role_slug=role_slug)
            else "identified"
        )
    sb.table("candidates").update(patch).eq("id", row["id"]).execute()
    return score, rec


st.subheader("4. Import")
if st.button("Import into Pipeline", type="primary", disabled=not valid):
    inserted = updated = skipped = scored = score_skipped = 0
    score_notes: list[str] = []
    import_batch = new_import_batch_id()
    progress = st.progress(0.0)
    work_items: list[tuple] = [(p, None) for p in fresh]
    for hit in dupes:
        action = dupe_actions.get(hit.prospect.email.lower(), "skip")
        if action == "update" or auto_update_dupes:
            work_items.append((hit.prospect, hit.existing))
        else:
            skipped += 1

    total = max(len(work_items), 1)
    for i, (prospect, existing) in enumerate(work_items):
        resume_path = match_resume_path(prospect, uploaded_map)
        try:
            row = upsert_prospect(
                sb,
                role_id=role_id,
                role_slug=role_slug,
                prospect=prospect,
                existing=existing,
                resume_path=resume_path,
                import_batch=import_batch,
            )
            if existing:
                updated += 1
            else:
                inserted += 1

            if score_after:
                text, source = resolve_scoring_text(
                    resume_path=resume_path,
                    linkedin_text=prospect.linkedin_text,
                    linkedin_url=prospect.linkedin_url,
                )
                if not text:
                    score_skipped += 1
                    score_notes.append(
                        f"• {prospect.full_name}: skipped scoring (no resume/LinkedIn text)"
                    )
                elif not llm_configured():
                    score_skipped += 1
                    score_notes.append(
                        f"• {prospect.full_name}: skipped scoring (OPENAI_API_KEY missing)"
                    )
                else:
                    try:
                        prescreen_candidate_from_text(
                            row,
                            source_text=text,
                            role_slug=role_slug,
                            text_source=source,
                        )
                        score, rec = _apply_score_notes(row, prospect, source)
                        if score is not None and rec:
                            scored += 1
                            score_notes.append(
                                f"• {prospect.full_name}: {score}/100 · {rec} "
                                f"({scoring_source_label(source)})"
                            )
                        else:
                            score_skipped += 1
                            score_notes.append(
                                f"• {prospect.full_name}: scored file written but parse failed"
                            )
                    except Exception as exc:
                        score_skipped += 1
                        score_notes.append(
                            f"• {prospect.full_name}: score failed — {exc}"
                        )
        except Exception as exc:
            st.error(f"Failed {prospect.full_name}: {exc}")
        progress.progress((i + 1) / total)

    st.success(
        f"Import done — batch `{import_batch}` · {inserted} inserted, "
        f"{updated} updated, {skipped} skipped"
        + (f", {scored} scored, {score_skipped} scoring skipped" if score_after else "")
    )
    for line in score_notes[:40]:
        st.write(line)
    if len(score_notes) > 40:
        st.caption(f"…and {len(score_notes) - 40} more")
    st.info(
        f"Open **Pipeline** and filter by import batch `{import_batch}` "
        "to SMS/email these candidates."
    )
