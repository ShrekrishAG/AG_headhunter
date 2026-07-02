"""Full job description — dialog view (URL bookmark support)."""

from __future__ import annotations

from lib.constants import get_selected_role_slug
from lib.job_description_dialog import request_job_description_dialog

request_job_description_dialog(get_selected_role_slug())
