-- GM checklist: "Interested" mark (alongside contacted / not interested).

alter table public.manager_packet_sends
  add column if not exists gm_interested_at timestamptz;
