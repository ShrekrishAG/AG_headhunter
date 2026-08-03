-- Calendly R1 booking sync (invitee.created / canceled webhooks)

alter table public.candidates
  add column if not exists r1_scheduled_at timestamptz,
  add column if not exists calendly_invitee_uri text,
  add column if not exists calendly_event_uri text;

create index if not exists candidates_email_lower_idx
  on public.candidates (lower(email));

create index if not exists candidates_calendly_invitee_uri_idx
  on public.candidates (calendly_invitee_uri)
  where calendly_invitee_uri is not null;

create index if not exists candidates_r1_scheduled_at_idx
  on public.candidates (r1_scheduled_at)
  where r1_scheduled_at is not null;
