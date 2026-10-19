-- Private GM checklist links and "I contacted this person" marks.
-- Separate from the recruiting pipeline contacted status.

alter table public.manager_packet_sends
  add column if not exists checklist_token text;

alter table public.manager_packet_sends
  add column if not exists gm_contacted_at timestamptz;

create index if not exists manager_packet_sends_checklist_token_idx
  on public.manager_packet_sends (checklist_token);
