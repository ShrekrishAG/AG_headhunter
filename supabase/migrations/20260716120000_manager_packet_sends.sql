-- Manager packet email sends (sales market distribution)

create table if not exists public.manager_packet_sends (
  id uuid primary key default gen_random_uuid(),
  candidate_key text not null,
  candidate_name text,
  candidate_email text,
  candidate_phone text,
  zr_candidate_id text,
  project_name text not null,
  market text not null,
  manager_email text not null,
  export_batch text,
  packet_id text,
  sendgrid_message_id text,
  sent_at timestamptz not null default now(),
  unique (candidate_key)
);

create index if not exists manager_packet_sends_manager_idx
  on public.manager_packet_sends (manager_email, sent_at desc);

create index if not exists manager_packet_sends_batch_idx
  on public.manager_packet_sends (export_batch);

create index if not exists manager_packet_sends_project_idx
  on public.manager_packet_sends (project_name);

alter table public.manager_packet_sends enable row level security;

drop policy if exists "deny_anon_manager_packets" on public.manager_packet_sends;
create policy "deny_anon_manager_packets" on public.manager_packet_sends
  for all to anon using (false);

drop policy if exists "deny_auth_manager_packets" on public.manager_packet_sends;
create policy "deny_auth_manager_packets" on public.manager_packet_sends
  for all to authenticated using (false);
