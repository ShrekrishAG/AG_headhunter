-- Candidate activity log + outreach counters on candidates

create table if not exists public.candidate_activities (
  id uuid primary key default gen_random_uuid(),
  candidate_id uuid not null references public.candidates(id) on delete cascade,
  activity_type text not null,
  channel text,
  actor text not null default 'dashboard',
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists candidate_activities_candidate_idx
  on public.candidate_activities (candidate_id, created_at desc);

create index if not exists candidate_activities_type_idx
  on public.candidate_activities (activity_type);

alter table public.candidates
  add column if not exists sms_outreach_count int not null default 0,
  add column if not exists email_outreach_count int not null default 0,
  add column if not exists last_sms_at timestamptz,
  add column if not exists last_email_at timestamptz,
  add column if not exists last_activity_at timestamptz;

alter table public.candidate_activities enable row level security;

drop policy if exists "deny_anon_activities" on public.candidate_activities;
create policy "deny_anon_activities" on public.candidate_activities for all to anon using (false);

drop policy if exists "deny_auth_activities" on public.candidate_activities;
create policy "deny_auth_activities" on public.candidate_activities for all to authenticated using (false);
