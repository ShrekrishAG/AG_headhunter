-- GM checklist: "Not interested" mark (separate from contacted).

alter table public.manager_packet_sends
  add column if not exists gm_not_interested_at timestamptz;
