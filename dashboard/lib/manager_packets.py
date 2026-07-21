"""Build and email fair manager packets from ZipRecruiter sales exports."""

from __future__ import annotations

import csv
import io
import random
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from supabase import Client

from lib.app_config import get_config
from lib.communications_status import outbound_sends_enabled
from lib.constants import DASHBOARD_ROOT
from lib.email_utils import normalize_email
from lib.manager_markets import MarketManagers, configured_projects, resolve_market
from lib.r1_email_invite import sendgrid_configured

EXPORTS_ROOT = DASHBOARD_ROOT.parent / "slack-zr-agent" / "exports"
PACKET_CSV_FIELDS = ("name", "email", "phone", "project_name", "market")


@dataclass
class ExportCandidate:
    name: str
    email: str
    phone: str
    project_name: str
    project_id: str
    candidate_id: str
    resume_filename: str
    exported_at: str
    export_batch: str
    resume_path: Path | None = None
    score: int | None = None

    @property
    def candidate_key(self) -> str:
        zr_id = (self.candidate_id or "").strip()
        if zr_id:
            return f"zr:{zr_id}"
        email = normalize_email(self.email) or ""
        if email:
            return f"email:{email}"
        phone = re.sub(r"\D", "", self.phone or "")
        if phone:
            return f"phone:{phone}"
        return f"name:{self.name.strip().lower()}|{self.project_name.strip().lower()}"


@dataclass
class ManagerPacket:
    market: str
    project_name: str
    manager_email: str
    candidates: list[ExportCandidate] = field(default_factory=list)
    export_batch: str = ""

    @property
    def packet_id(self) -> str:
        safe_market = re.sub(r"[^\w\-]+", "_", self.market)[:40]
        safe_manager = self.manager_email.split("@")[0]
        return f"{self.export_batch}_{safe_market}_{safe_manager}"


@dataclass
class AssignmentPreview:
    export_batch: str
    packets: list[ManagerPacket]
    excluded_already_sent: int
    skipped_unknown_project: int
    total_candidates: int


def list_export_batches(exports_root: Path = EXPORTS_ROOT, *, limit: int = 30) -> list[dict[str, Any]]:
    if not exports_root.is_dir():
        return []
    batches: list[dict[str, Any]] = []
    for path in sorted(exports_root.iterdir(), reverse=True):
        csv_path = path / "candidates.csv"
        if not path.is_dir() or not csv_path.is_file():
            continue
        count = 0
        with csv_path.open(newline="", encoding="utf-8") as handle:
            count = sum(1 for _ in csv.DictReader(handle))
        batches.append(
            {
                "batch": path.name,
                "path": path,
                "candidate_count": count,
                "created_display": _format_batch_label(path.name),
            }
        )
        if len(batches) >= limit:
            break
    return batches


def _format_batch_label(batch: str) -> str:
    try:
        dt = datetime.strptime(batch, "%Y-%m-%d_%H%M%S")
        return dt.strftime("%b %d, %Y · %I:%M %p").lstrip("0").replace(" 0", " ")
    except ValueError:
        return batch


def load_export_candidates(export_dir: Path) -> list[ExportCandidate]:
    csv_path = export_dir / "candidates.csv"
    resumes_dir = export_dir / "resumes"
    if not csv_path.is_file():
        return []
    rows: list[ExportCandidate] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            resume_name = (row.get("resume_filename") or "").strip()
            resume_path = resumes_dir / resume_name if resume_name else None
            if resume_path and not resume_path.is_file():
                resume_path = None
            rows.append(
                ExportCandidate(
                    name=(row.get("name") or "").strip(),
                    email=(row.get("email") or "").strip(),
                    phone=(row.get("phone") or "").strip(),
                    project_name=(row.get("project_name") or "").strip(),
                    project_id=(row.get("project_id") or "").strip(),
                    candidate_id=(row.get("candidate_id") or "").strip(),
                    resume_filename=resume_name,
                    exported_at=(row.get("exported_at") or "").strip(),
                    export_batch=export_dir.name,
                    resume_path=resume_path,
                )
            )
    return rows


def tracking_available(sb: Client) -> bool:
    try:
        sb.table("manager_packet_sends").select("id").limit(1).execute()
        return True
    except Exception:
        return False


def load_sent_candidate_keys(sb: Client) -> set[str]:
    if not tracking_available(sb):
        return set()
    rows = sb.table("manager_packet_sends").select("candidate_key").execute().data or []
    return {str(row["candidate_key"]) for row in rows if row.get("candidate_key")}


def load_recent_sends(sb: Client, *, limit: int = 100) -> list[dict]:
    if not tracking_available(sb):
        return []
    return (
        sb.table("manager_packet_sends")
        .select("*")
        .order("sent_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )


def attach_scores_from_supabase(sb: Client, candidates: list[ExportCandidate]) -> None:
    """Best-effort score lookup from candidate notes for fair split only."""
    try:
        rows = (
            sb.table("candidates")
            .select("email, phone, notes, full_name")
            .execute()
            .data
            or []
        )
    except Exception:
        return

    by_email: dict[str, int] = {}
    by_phone: dict[str, int] = {}
    score_re = re.compile(r"(\d+)\s*/\s*100")
    for row in rows:
        notes = row.get("notes") or ""
        match = score_re.search(notes)
        if not match:
            continue
        score = int(match.group(1))
        email = normalize_email(row.get("email") or "")
        phone = re.sub(r"\D", "", row.get("phone") or "")
        if email:
            by_email[email] = score
        if phone:
            by_phone[phone] = score

    for candidate in candidates:
        email = normalize_email(candidate.email)
        phone = re.sub(r"\D", "", candidate.phone or "")
        if email and email in by_email:
            candidate.score = by_email[email]
        elif phone and phone in by_phone:
            candidate.score = by_phone[phone]


def snake_assign(
    candidates: list[ExportCandidate],
    manager_emails: list[str],
    *,
    rng: random.Random | None = None,
) -> dict[str, list[ExportCandidate]]:
    if not manager_emails:
        return {}
    rng = rng or random.Random()
    managers = list(manager_emails)
    rng.shuffle(managers)

    ranked = sorted(
        candidates,
        key=lambda c: (c.score is not None, c.score or 0, c.name.lower()),
        reverse=True,
    )
    packets: dict[str, list[ExportCandidate]] = {email: [] for email in managers}
    n = len(managers)
    for i, candidate in enumerate(ranked):
        round_num = i // n
        pos = i % n
        if round_num % 2 == 1:
            pos = n - 1 - pos
        packets[managers[pos]].append(candidate)
    return packets


def build_assignment_preview(
    sb: Client,
    export_dir: Path,
    *,
    seed: int | None = None,
) -> AssignmentPreview:
    candidates = load_export_candidates(export_dir)
    attach_scores_from_supabase(sb, candidates)
    sent_keys = load_sent_candidate_keys(sb)
    configured = {p.lower() for p in configured_projects()}

    excluded = 0
    skipped = 0
    by_project: dict[str, list[ExportCandidate]] = {}

    for candidate in candidates:
        market = resolve_market(candidate.project_name)
        if market is None or candidate.project_name.lower() not in configured:
            if candidate.project_name:
                skipped += 1
            continue
        if candidate.candidate_key in sent_keys:
            excluded += 1
            continue
        by_project.setdefault(market.project, []).append(candidate)

    rng = random.Random(seed if seed is not None else export_dir.name)
    packets: list[ManagerPacket] = []
    for project_name, project_candidates in sorted(by_project.items()):
        market = resolve_market(project_name)
        if market is None:
            continue
        assigned = snake_assign(
            project_candidates, list(market.manager_emails), rng=rng
        )
        for manager_email, assigned_candidates in assigned.items():
            if not assigned_candidates:
                continue
            packets.append(
                ManagerPacket(
                    market=market.market,
                    project_name=market.project,
                    manager_email=manager_email,
                    candidates=assigned_candidates,
                    export_batch=export_dir.name,
                )
            )

    packets.sort(key=lambda p: (p.market, p.manager_email))
    return AssignmentPreview(
        export_batch=export_dir.name,
        packets=packets,
        excluded_already_sent=excluded,
        skipped_unknown_project=skipped,
        total_candidates=len(candidates),
    )


def build_packet_zip(packet: ManagerPacket) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        csv_buffer = io.StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=PACKET_CSV_FIELDS)
        writer.writeheader()
        for candidate in packet.candidates:
            writer.writerow(
                {
                    "name": candidate.name,
                    "email": candidate.email,
                    "phone": candidate.phone,
                    "project_name": candidate.project_name,
                    "market": packet.market,
                }
            )
        archive.writestr("candidates.csv", csv_buffer.getvalue())
        for candidate in packet.candidates:
            if candidate.resume_path and candidate.resume_path.is_file():
                archive.write(
                    candidate.resume_path,
                    arcname=f"resumes/{candidate.resume_filename or candidate.resume_path.name}",
                )
    return buffer.getvalue()


def _candidate_lines(packet: ManagerPacket, *, limit: int = 40) -> tuple[str, str]:
    lines: list[str] = []
    for candidate in packet.candidates[:limit]:
        email = (candidate.email or "").strip() or "(no email)"
        phone = (candidate.phone or "").strip() or "(no phone)"
        lines.append(f"• {candidate.name}\n  {email}\n  {phone}")
    more = ""
    if len(packet.candidates) > limit:
        more = f"\n• …and {len(packet.candidates) - limit} more (see CSV)"
    return "\n".join(lines), more


def _manager_email_subject(packet: ManagerPacket, *, test_mode: bool = False) -> str:
    prefix = "[TEST] " if test_mode else ""
    return f"{prefix}Accord candidates — {packet.market} — {packet.export_batch[:10]}"


def _manager_email_body(
    packet: ManagerPacket,
    *,
    test_mode: bool = False,
    intended_manager: str | None = None,
) -> str:
    names, more = _candidate_lines(packet)
    test_note = ""
    if test_mode:
        test_note = (
            f"\n[TEST MODE] Intended GM recipient: {intended_manager or packet.manager_email}\n"
            "This email was redirected for testing. Candidates were NOT marked as sent.\n"
        )
    return (
        f"Hi,\n\n"
        f"{test_note}"
        f"Attached is your candidate packet for {packet.market} "
        f"({packet.project_name}).\n\n"
        f"Candidates in this packet: {len(packet.candidates)}\n"
        f"Export batch: {packet.export_batch}\n\n"
        f"{names}{more}\n\n"
        f"The zip includes candidates.csv plus resume PDFs.\n\n"
        f"— Accord Recruiting"
    )


REQUIRED_PACKET_COPY_EMAILS = (
    "shreya@dollfamilyoffice.com",
    "randonkent@roofally.com",
)


def packet_copy_emails() -> list[str]:
    """BCC list for recruiting on live GM packets (comma-separated config)."""
    raw_value = get_config("MANAGER_PACKET_COPY_EMAIL")
    # Streamlit secrets sometimes return a list for comma-like values.
    if isinstance(raw_value, (list, tuple)):
        parts = [str(part) for part in raw_value]
    else:
        raw = (
            str(raw_value).strip()
            if raw_value
            else "shreya@dollfamilyoffice.com,randonkent@roofally.com"
        )
        parts = raw.replace(";", ",").split(",")

    emails: list[str] = []
    seen: set[str] = set()
    for part in parts:
        email = normalize_email(part)
        if not email or email.lower() in seen:
            continue
        seen.add(email.lower())
        emails.append(email)

    # Always include required recruiting copies even if config is stale/partial.
    for required in REQUIRED_PACKET_COPY_EMAILS:
        email = normalize_email(required)
        if not email or email.lower() in seen:
            continue
        seen.add(email.lower())
        emails.append(email)
    return emails


def packet_copy_email() -> str | None:
    """Backward-compatible single copy address (first configured BCC)."""
    emails = packet_copy_emails()
    return emails[0] if emails else None


@dataclass
class PacketEmailPreview:
    to_email: str
    bcc_emails: list[str]
    subject: str
    body: str
    test_mode: bool
    attachment_name: str
    missing_required_bcc: list[str]


def preview_packet_email(
    packet: ManagerPacket,
    *,
    redirect_to: str | None = None,
) -> PacketEmailPreview:
    """Build the exact To/BCC/subject/body that send_packet_email will use."""
    test_mode = bool(redirect_to)
    to_email = normalize_email(redirect_to or packet.manager_email) or (
        redirect_to or packet.manager_email
    )
    to_lower = to_email.lower()
    bcc_emails = []
    if not test_mode:
        for copy_to in packet_copy_emails():
            if copy_to.lower() == to_lower:
                continue
            bcc_emails.append(copy_to)

    required = [normalize_email(e) or e.lower() for e in REQUIRED_PACKET_COPY_EMAILS]
    present = {e.lower() for e in bcc_emails}
    # In test mode BCC is intentionally off — flag required as missing for live check.
    if test_mode:
        missing = list(REQUIRED_PACKET_COPY_EMAILS)
    else:
        missing = [email for email in required if email not in present]

    return PacketEmailPreview(
        to_email=to_email,
        bcc_emails=bcc_emails,
        subject=_manager_email_subject(packet, test_mode=test_mode),
        body=_manager_email_body(
            packet, test_mode=test_mode, intended_manager=packet.manager_email
        ),
        test_mode=test_mode,
        attachment_name=f"{packet.packet_id}.zip",
        missing_required_bcc=missing,
    )


def verify_copy_recipients_for_packets(
    packets: list[ManagerPacket],
    *,
    redirect_to: str | None = None,
) -> dict[str, Any]:
    """Confirm required recruiting BCC addresses are on every live packet email."""
    previews = [
        preview_packet_email(packet, redirect_to=redirect_to) for packet in packets
    ]
    required = [normalize_email(e) or e.lower() for e in REQUIRED_PACKET_COPY_EMAILS]
    configured = packet_copy_emails()
    configured_set = {e.lower() for e in configured}
    missing_from_config = [e for e in required if e not in configured_set]

    packets_missing: list[dict[str, Any]] = []
    if not redirect_to:
        for packet, preview in zip(packets, previews):
            if preview.missing_required_bcc:
                packets_missing.append(
                    {
                        "manager": packet.manager_email,
                        "market": packet.market,
                        "missing": preview.missing_required_bcc,
                    }
                )

    all_ok = not missing_from_config and not packets_missing and not redirect_to
    return {
        "configured_bcc": configured,
        "required_bcc": list(REQUIRED_PACKET_COPY_EMAILS),
        "missing_from_config": missing_from_config,
        "packets_missing": packets_missing,
        "test_mode": bool(redirect_to),
        "all_ok": all_ok,
        "previews": previews,
    }


def send_packet_email(
    packet: ManagerPacket,
    zip_bytes: bytes,
    *,
    redirect_to: str | None = None,
) -> str:
    if not outbound_sends_enabled():
        raise RuntimeError("Outbound sends are disabled (OUTBOUND_SENDS_ENABLED=false).")
    if not sendgrid_configured():
        raise RuntimeError("SendGrid not configured.")

    api_key = get_config("SENDGRID_API_KEY")
    from_email = get_config("SENDGRID_FROM_EMAIL")
    from_name = get_config("SENDGRID_FROM_NAME", "Accord Group Recruiting")
    intended = packet.manager_email
    to_email = normalize_email(redirect_to or packet.manager_email)
    if not to_email:
        raise ValueError(f"Invalid manager email: {redirect_to or packet.manager_email}")
    test_mode = bool(redirect_to)

    import base64
    import logging

    import sendgrid
    from sendgrid.helpers.mail import (
        Attachment,
        Bcc,
        Disposition,
        Email,
        FileContent,
        FileName,
        FileType,
        Mail,
        Personalization,
        To,
    )

    subject = _manager_email_subject(packet, test_mode=test_mode)
    body = _manager_email_body(
        packet, test_mode=test_mode, intended_manager=intended
    )
    message = Mail(
        from_email=Email(from_email, from_name),
        subject=subject,
        plain_text_content=body,
    )

    personalization = Personalization()
    personalization.add_to(To(to_email))

    # Live GM sends: BCC recruiting so they get a full copy of each packet.
    bcc_emails: list[str] = []
    if not test_mode:
        to_lower = to_email.lower()
        for copy_to in packet_copy_emails():
            if copy_to.lower() == to_lower:
                continue
            personalization.add_bcc(Bcc(copy_to))
            bcc_emails.append(copy_to)

    message.add_personalization(personalization)
    logging.getLogger(__name__).info(
        "Sending manager packet to=%s bcc=%s market=%s batch=%s",
        to_email,
        bcc_emails,
        packet.market,
        packet.export_batch,
    )

    encoded = base64.b64encode(zip_bytes).decode()
    attachment = Attachment(
        FileContent(encoded),
        FileName(f"{packet.packet_id}.zip"),
        FileType("application/zip"),
        Disposition("attachment"),
    )
    message.attachment = attachment
    client = sendgrid.SendGridAPIClient(api_key)
    response = client.send(message)
    return response.headers.get("X-Message-Id", str(response.status_code))


def log_packet_send(sb: Client, packet: ManagerPacket, *, message_id: str) -> None:
    if not tracking_available(sb):
        raise RuntimeError(
            "manager_packet_sends table missing — apply migration "
            "supabase/migrations/20260716120000_manager_packet_sends.sql"
        )
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for candidate in packet.candidates:
        rows.append(
            {
                "candidate_key": candidate.candidate_key,
                "candidate_name": candidate.name,
                "candidate_email": candidate.email or None,
                "candidate_phone": candidate.phone or None,
                "zr_candidate_id": candidate.candidate_id or None,
                "project_name": packet.project_name,
                "market": packet.market,
                "manager_email": packet.manager_email,
                "export_batch": packet.export_batch,
                "packet_id": packet.packet_id,
                "sendgrid_message_id": message_id,
                "sent_at": now,
            }
        )
    if rows:
        sb.table("manager_packet_sends").upsert(rows, on_conflict="candidate_key").execute()


def send_all_packets(
    sb: Client,
    packets: list[ManagerPacket],
    *,
    redirect_to: str | None = None,
    record_sends: bool = True,
) -> tuple[list[str], list[str]]:
    """Returns (success_messages, error_messages).

    redirect_to: send every packet to this address (test mode).
    record_sends: when False, skip never-send-twice logging (use for tests).
    """
    successes: list[str] = []
    errors: list[str] = []
    for packet in packets:
        if not packet.candidates:
            continue
        try:
            zip_bytes = build_packet_zip(packet)
            message_id = send_packet_email(
                packet, zip_bytes, redirect_to=redirect_to
            )
            if record_sends:
                log_packet_send(sb, packet, message_id=message_id)
            dest = redirect_to or packet.manager_email
            label = (
                f"{dest} (intended {packet.manager_email}) · {packet.market} · "
                f"{len(packet.candidates)} candidates"
                if redirect_to
                else f"{packet.manager_email} · {packet.market} · {len(packet.candidates)} candidates"
            )
            successes.append(label)
        except Exception as exc:
            errors.append(f"{packet.manager_email} ({packet.market}): {exc}")
    return successes, errors
