"""CSV prospect import — non-ZipRecruiter candidates for Pipeline outreach."""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from supabase import Client

from lib.constants import DASHBOARD_ROOT, role_rubric_for_slug, role_title_for_slug
from lib.email_utils import EMAIL_RE
from lib.phone_utils import normalize_phone_us
from lib.resume_slug import full_name_to_resume_slug

logger = logging.getLogger(__name__)

TEMPLATE_PATH = DASHBOARD_ROOT / "templates" / "prospect_import_template.csv"
PROSPECT_INBOX = DASHBOARD_ROOT.parent / "imports" / "inbox" / "Prospects"


def normalize_import_email(raw: str | None) -> str | None:
    """Accept emails for prospect CSV (template may use example.com)."""
    if not raw:
        return None
    value = raw.strip().lower().rstrip(".,;)")
    match = EMAIL_RE.search(value)
    return match.group(0) if match else None


# Headers that must exist (email/phone cells may be blank — need ≥1 contact value).
REQUIRED_COLUMNS = ("full_name", "email", "phone", "source", "date_imported")
OPTIONAL_COLUMNS = (
    "linkedin_url",
    "linkedin_text",
    "market",
    "current_title",
    "current_company",
    "resume_filename",
    "notes",
)
ALL_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

COLUMN_ALIASES = {
    "name": "full_name",
    "full name": "full_name",
    "candidate": "full_name",
    "candidate_name": "full_name",
    "e-mail": "email",
    "mail": "email",
    "mobile": "phone",
    "phone_number": "phone",
    "cellphone": "phone",
    "imported_at": "date_imported",
    "import_date": "date_imported",
    "date imported": "date_imported",
    "date_imported": "date_imported",
    "linkedin": "linkedin_url",
    "linkedin_profile": "linkedin_url",
    "linkedin url": "linkedin_url",
    "profile_url": "linkedin_url",
    "linkedin_notes": "linkedin_text",
    "linkedin paste": "linkedin_text",
    "profile_text": "linkedin_text",
    "resume": "resume_filename",
    "resume_file": "resume_filename",
    "filename": "resume_filename",
    "title": "current_title",
    "company": "current_company",
}


@dataclass
class ProspectRow:
    full_name: str
    email: str
    phone: str | None
    source: str
    date_imported: str
    linkedin_url: str | None = None
    linkedin_text: str | None = None
    market: str | None = None
    current_title: str | None = None
    current_company: str | None = None
    resume_filename: str | None = None
    notes: str | None = None
    row_number: int = 0
    resume_slug: str = ""
    expected_resume_name: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors


@dataclass
class DuplicateHit:
    prospect: ProspectRow
    existing: dict[str, Any]
    action: str = "ask"  # ask | update | skip


def template_csv_bytes() -> bytes:
    if TEMPLATE_PATH.is_file():
        return TEMPLATE_PATH.read_bytes()
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(ALL_COLUMNS))
    writer.writeheader()
    return buffer.getvalue().encode("utf-8")


def resume_filename_for(
    full_name: str,
    *,
    role_slug: str,
    import_date: str | None = None,
) -> str:
    """Canonical resume name: YYYY-MM-DD-{prefix}-{lastname-firstname}.pdf"""
    day = (import_date or date.today().isoformat())[:10]
    prefix = role_rubric_for_slug(role_slug).get("resume_role_prefix") or "sales-rep"
    slug = full_name_to_resume_slug(full_name)
    return f"{day}-{prefix}-{slug}.pdf"


def _normalize_header(value: str) -> str:
    key = (value or "").strip().lower().replace("-", "_")
    key = re.sub(r"\s+", " ", key)
    spaced = key.replace("_", " ")
    if key in COLUMN_ALIASES:
        return COLUMN_ALIASES[key]
    if spaced in COLUMN_ALIASES:
        return COLUMN_ALIASES[spaced]
    return key.replace(" ", "_")


def _parse_import_date(raw: str) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%b %d %Y", "%B %d %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    # Already ISO-ish with time
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def parse_prospect_csv(
    raw: bytes | str,
    *,
    role_slug: str,
) -> tuple[list[ProspectRow], list[str]]:
    """Parse CSV bytes into prospect rows. Returns (rows, file_errors)."""
    file_errors: list[str] = []
    if isinstance(raw, bytes):
        text = raw.decode("utf-8-sig", errors="replace")
    else:
        text = raw

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return [], ["CSV has no header row."]

    mapped_headers = {_normalize_header(h): h for h in reader.fieldnames if h}
    missing = [col for col in REQUIRED_COLUMNS if col not in mapped_headers]
    if missing:
        file_errors.append(
            "Missing required column(s): "
            + ", ".join(missing)
            + ". Expected headers: "
            + ", ".join(ALL_COLUMNS)
        )
        return [], file_errors

    rows: list[ProspectRow] = []
    for index, raw_row in enumerate(reader, start=2):
        values = {
            canon: (raw_row.get(original) or "").strip()
            for canon, original in mapped_headers.items()
        }
        name = values.get("full_name", "")
        email = normalize_import_email(values.get("email", "")) or ""
        phone = normalize_phone_us(values.get("phone"))
        source = values.get("source", "")
        date_imported = _parse_import_date(values.get("date_imported", "")) or ""
        linkedin_url = values.get("linkedin_url") or None
        linkedin_text = values.get("linkedin_text") or None
        resume_filename = values.get("resume_filename") or None

        prospect = ProspectRow(
            full_name=name,
            email=email,
            phone=phone,
            source=source or "Manual import",
            date_imported=date_imported or date.today().isoformat(),
            linkedin_url=linkedin_url,
            linkedin_text=linkedin_text,
            market=values.get("market") or None,
            current_title=values.get("current_title") or None,
            current_company=values.get("current_company") or None,
            resume_filename=resume_filename,
            notes=values.get("notes") or None,
            row_number=index,
            resume_slug=full_name_to_resume_slug(name) if name else "",
        )
        prospect.expected_resume_name = (
            resume_filename
            or resume_filename_for(
                name, role_slug=role_slug, import_date=prospect.date_imported
            )
            if name
            else ""
        )

        if not name:
            prospect.errors.append("full_name is required")

        raw_phone = values.get("phone", "")
        if raw_phone and not phone:
            if email:
                prospect.warnings.append(
                    "phone invalid — ignored (email present for contact)"
                )
                phone = None
                prospect.phone = None
            else:
                prospect.errors.append(
                    "phone is invalid (use US 10-digit or +1…)"
                )
        elif not email and not phone:
            prospect.errors.append(
                "email or phone is required (at least one contact method)"
            )
        else:
            if not email:
                prospect.warnings.append(
                    "email missing — email outreach blocked; duplicates matched by phone"
                )
            if not phone:
                prospect.warnings.append(
                    "phone missing — SMS outreach will be blocked"
                )

        if not source:
            prospect.warnings.append("source blank — defaulted to Manual import")
        if not values.get("date_imported"):
            prospect.warnings.append(
                f"date_imported blank — using {prospect.date_imported}"
            )
        elif not _parse_import_date(values.get("date_imported", "")):
            prospect.errors.append(
                "date_imported must be YYYY-MM-DD (or MM/DD/YYYY)"
            )
        if not prospect.linkedin_url and not prospect.linkedin_text and not resume_filename:
            prospect.warnings.append(
                "no resume_filename / linkedin_url / linkedin_text — scoring will be skipped"
            )

        rows.append(prospect)
    return rows, file_errors


def find_existing_by_email(
    sb: Client,
    *,
    role_id: str,
    email: str,
) -> dict[str, Any] | None:
    email_key = normalize_import_email(email)
    if not email_key:
        return None
    rows = (
        sb.table("candidates")
        .select("*")
        .eq("role_id", role_id)
        .ilike("email", email_key)
        .limit(5)
        .execute()
        .data
    )
    for row in rows or []:
        if normalize_import_email(row.get("email") or "") == email_key:
            return row
    return None


def find_existing_by_phone(
    sb: Client,
    *,
    role_id: str,
    phone: str | None,
) -> dict[str, Any] | None:
    phone_key = normalize_phone_us(phone) if phone else None
    if not phone_key:
        return None
    rows = (
        sb.table("candidates")
        .select("*")
        .eq("role_id", role_id)
        .eq("phone", phone_key)
        .limit(5)
        .execute()
        .data
    )
    for row in rows or []:
        if normalize_phone_us(row.get("phone") or "") == phone_key:
            return row
    return None


def find_existing_prospect(
    sb: Client,
    *,
    role_id: str,
    prospect: ProspectRow,
) -> dict[str, Any] | None:
    """Match duplicates by email first, then phone."""
    if prospect.email:
        hit = find_existing_by_email(sb, role_id=role_id, email=prospect.email)
        if hit:
            return hit
    if prospect.phone:
        return find_existing_by_phone(sb, role_id=role_id, phone=prospect.phone)
    return None


def classify_duplicates(
    sb: Client,
    *,
    role_id: str,
    prospects: list[ProspectRow],
) -> tuple[list[ProspectRow], list[DuplicateHit]]:
    fresh: list[ProspectRow] = []
    dupes: list[DuplicateHit] = []
    for prospect in prospects:
        if not prospect.is_valid:
            continue
        existing = find_existing_prospect(sb, role_id=role_id, prospect=prospect)
        if existing:
            dupes.append(DuplicateHit(prospect=prospect, existing=existing, action="ask"))
        else:
            fresh.append(prospect)
    return fresh, dupes


def save_uploaded_resumes(
    files: list[tuple[str, bytes]],
    *,
    role_slug: str,
) -> dict[str, Path]:
    """Save uploaded resume PDFs into imports/inbox/Prospects. Returns name→path."""
    PROSPECT_INBOX.mkdir(parents=True, exist_ok=True)
    saved: dict[str, Path] = {}
    for filename, data in files:
        name = Path(filename).name
        if not name.lower().endswith(".pdf"):
            continue
        dest = PROSPECT_INBOX / name
        dest.write_bytes(data)
        saved[name.lower()] = dest
        saved[name] = dest
    return saved


def match_resume_path(
    prospect: ProspectRow,
    uploaded: dict[str, Path],
) -> Path | None:
    candidates = [
        prospect.resume_filename,
        prospect.expected_resume_name,
    ]
    for name in candidates:
        if not name:
            continue
        path = uploaded.get(name) or uploaded.get(name.lower())
        if path and path.is_file():
            return path
    # Fuzzy: any uploaded file ending with -{slug}.pdf
    slug = prospect.resume_slug
    if slug:
        for path in uploaded.values():
            if path.name.lower().endswith(f"-{slug}.pdf"):
                return path
    return None


def _import_note(prospect: ProspectRow, role_slug: str, *, import_batch: str | None = None) -> str:
    bits = [
        f"Prospect import {prospect.date_imported}",
        f"source={prospect.source}",
        f"role={role_slug}",
    ]
    if import_batch:
        bits.append(f"import_batch={import_batch}")
    if prospect.notes:
        bits.append(prospect.notes)
    return " · ".join(bits)


def new_import_batch_id() -> str:
    """Timestamp batch id, same shape as ZipRecruiter export folders."""
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def upsert_prospect(
    sb: Client,
    *,
    role_id: str,
    role_slug: str,
    prospect: ProspectRow,
    existing: dict[str, Any] | None = None,
    resume_path: Path | None = None,
    import_batch: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "full_name": prospect.full_name,
        "email": prospect.email or None,
        "phone": prospect.phone or None,
        "source": prospect.source,
        "linkedin_url": prospect.linkedin_url,
        "market": prospect.market,
        "current_title": prospect.current_title,
        "current_company": prospect.current_company,
    }
    if import_batch:
        payload["import_batch"] = import_batch
    note_line = _import_note(prospect, role_slug, import_batch=import_batch)
    if existing:
        old_notes = (existing.get("notes") or "").strip()
        if note_line not in old_notes:
            payload["notes"] = f"{note_line}\n\n{old_notes}".strip() if old_notes else note_line
        # Don't wipe pipeline stage on update
        row = (
            sb.table("candidates")
            .update(payload)
            .eq("id", existing["id"])
            .execute()
            .data[0]
        )
    else:
        payload.update(
            {
                "role_id": role_id,
                "pipeline_stage": "identified",
                "notes": note_line,
            }
        )
        row = sb.table("candidates").insert(payload).execute().data[0]

    # Ensure profile stub exists for scoring / Pipeline
    profile_dir = (
        DASHBOARD_ROOT.parent
        / "candidates"
        / role_slug
        / full_name_to_resume_slug(prospect.full_name)
    )
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_path = profile_dir / "profile.md"
    if not profile_path.is_file():
        profile_path.write_text(
            _pending_profile_markdown(prospect, role_slug=role_slug, resume_path=resume_path),
            encoding="utf-8",
        )
    elif resume_path or prospect.linkedin_text or prospect.linkedin_url:
        # Keep existing scored profiles; only refresh pending stubs.
        text = profile_path.read_text(encoding="utf-8")
        if "Pending resume pre-screen" in text or "Pending agent pre-screen" in text:
            profile_path.write_text(
                _pending_profile_markdown(
                    prospect, role_slug=role_slug, resume_path=resume_path
                ),
                encoding="utf-8",
            )
    return row


def _pending_profile_markdown(
    prospect: ProspectRow,
    *,
    role_slug: str,
    resume_path: Path | None,
) -> str:
    email_line = f"**Email:** {prospect.email}  \n" if prospect.email else ""
    phone_line = f"**Phone:** {prospect.phone}  \n" if prospect.phone else ""
    linkedin = prospect.linkedin_url or "—"
    resume_note = resume_path.name if resume_path else (prospect.resume_filename or "—")
    linkedin_block = ""
    if prospect.linkedin_text:
        linkedin_block = f"\n## LinkedIn paste\n\n{prospect.linkedin_text.strip()}\n"
    return f"""# Candidate profile

**Role slug:** {role_slug}  
**Name:** {prospect.full_name}  
**Current title / company:** {(prospect.current_title or '—')} · {(prospect.current_company or '—')}  
**LinkedIn:** {linkedin}  
{email_line}{phone_line}**Source:** {prospect.source}  
**Stage:** Identified  
**Market:** {prospect.market or '—'}  
**Resume file:** {resume_note}  
**Last updated:** {date.today().isoformat()}

## Summary

Pending resume pre-screen.
{linkedin_block}
## Scorecard

Pending agent pre-screen.

## Next step

- Import complete — score when resume or LinkedIn text is available
"""


def scoring_source_label(source: str) -> str:
    return {
        "resume": "resume PDF",
        "linkedin_text": "LinkedIn paste",
        "linkedin_fetch": "LinkedIn URL fetch",
        "none": "none",
    }.get(source, source)


def role_id_for_slug(sb: Client, role_slug: str) -> str:
    rows = sb.table("roles").select("id, slug").eq("slug", role_slug).execute().data
    if not rows:
        raise RuntimeError(
            f"Role `{role_slug}` is missing in Supabase. "
            f"Apply the role migration or insert the role first."
        )
    return rows[0]["id"]


def instructions_markdown(role_slug: str) -> str:
    prefix = role_rubric_for_slug(role_slug).get("resume_role_prefix") or "sales-rep"
    title = role_title_for_slug(role_slug)
    example = resume_filename_for("Jane Smith", role_slug=role_slug)
    return f"""
### CSV columns

**Required**
- `full_name` — candidate name
- `source` — e.g. Indeed, Referral, LinkedIn, Career fair
- `date_imported` — `YYYY-MM-DD`
- **Contact:** at least one of `email` or `phone` (both columns should be present; blank the one you don't have)

**Contact columns**
- `email` — preferred for email outreach; used first for duplicate detection
- `phone` — US number for SMS (`+19135551234` or `9135551234`); used for duplicates when email is blank

**Optional (recommended)**
- `linkedin_url` — profile URL when no resume
- `linkedin_text` — paste About + Experience (best LinkedIn scoring signal)
- `market` — e.g. Wichita KS, KC MO
- `current_title`, `current_company`
- `resume_filename` — exact PDF name if it doesn't follow the convention below
- `notes` — free text for recruiters

### Resume filename format

```
YYYY-MM-DD-{prefix}-{{lastname}}-{{firstname}}.pdf
```

For **{title}** use prefix `{prefix}`.

Example: `{example}`

Upload PDFs with the CSV. Matching order:
1. `resume_filename` column
2. Canonical name above
3. Any uploaded file ending in `-{{lastname}}-{{firstname}}.pdf`

### Scoring order

1. Resume PDF text  
2. `linkedin_text` column  
3. Best-effort fetch from `linkedin_url`  
4. If none work → **skip scoring** (candidate still lands in Pipeline for SMS/email)
"""
