-- Accord Group resume evaluation (ZipRecruiter TGC sales hiring)

create extension if not exists "pgcrypto";

create table public.roles (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  title text not null,
  created_at timestamptz not null default now()
);

create table public.candidates (
  id uuid primary key default gen_random_uuid(),
  role_id uuid not null references public.roles(id) on delete cascade,
  full_name text not null,
  email text,
  phone text,
  linkedin_url text,
  current_title text,
  current_company text,
  source text,
  market text,
  ziprecruiter_project_id text,
  pipeline_stage text not null default 'identified',
  disposition text,
  notes text,
  personal_network_contact text,
  resume_url text,
  avatar_url text,
  r1_invite_sent_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.r1_evaluations (
  id uuid primary key default gen_random_uuid(),
  candidate_id uuid not null references public.candidates(id) on delete cascade,
  interviewer text not null check (interviewer in ('regional_manager', 'recruiter')),
  interview_date date not null default current_date,
  score_sales_track_record smallint check (score_sales_track_record between 1 and 4),
  score_communication smallint check (score_communication between 1 and 4),
  score_work_ethic smallint check (score_work_ethic between 1 and 4),
  score_market_fit smallint check (score_market_fit between 1 and 4),
  score_leadership_potential smallint check (score_leadership_potential between 1 and 4),
  score_culture_fit smallint check (score_culture_fit between 1 and 4),
  gate_valid_license boolean,
  gate_us_work_auth boolean,
  gate_employment_history boolean,
  gate_market_willingness boolean,
  evidence_sales_track_record text,
  evidence_communication text,
  evidence_work_ethic text,
  evidence_market_fit text,
  evidence_leadership_potential text,
  evidence_culture_fit text,
  debrief_notes text,
  vote text check (vote in ('advance', 'hold', 'pass')),
  weighted_score numeric(3,2) generated always as (
    case
      when score_sales_track_record is null
        or score_communication is null
        or score_work_ethic is null
        or score_market_fit is null
        or score_leadership_potential is null
        or score_culture_fit is null
      then null
      else round(
        score_sales_track_record * 0.25
        + score_communication * 0.20
        + score_work_ethic * 0.20
        + score_market_fit * 0.15
        + score_leadership_potential * 0.10
        + score_culture_fit * 0.10,
        2
      )
    end
  ) stored,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (candidate_id, interviewer)
);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger candidates_updated_at
  before update on public.candidates
  for each row execute function public.set_updated_at();

create trigger r1_evaluations_updated_at
  before update on public.r1_evaluations
  for each row execute function public.set_updated_at();

insert into public.roles (slug, title)
values ('sales-representative', 'Sales Representative (TGC)');

create index candidates_role_stage_idx on public.candidates (role_id, pipeline_stage);
create index candidates_market_idx on public.candidates (market);
create index r1_evaluations_candidate_idx on public.r1_evaluations (candidate_id);

alter table public.roles enable row level security;
alter table public.candidates enable row level security;
alter table public.r1_evaluations enable row level security;

create policy "deny_anon_roles" on public.roles for all to anon using (false);
create policy "deny_anon_candidates" on public.candidates for all to anon using (false);
create policy "deny_anon_r1" on public.r1_evaluations for all to anon using (false);

create policy "deny_auth_roles" on public.roles for all to authenticated using (false);
create policy "deny_auth_candidates" on public.candidates for all to authenticated using (false);
create policy "deny_auth_r1" on public.r1_evaluations for all to authenticated using (false);

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('resumes', 'resumes', true, 10485760, array['application/pdf'])
on conflict (id) do update
  set public = excluded.public,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'avatars',
  'avatars',
  true,
  5242880,
  array['image/jpeg', 'image/png', 'image/webp']
)
on conflict (id) do update
  set public = excluded.public,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

create policy "Public resume read"
  on storage.objects
  for select
  to public
  using (bucket_id = 'resumes');

create policy "Public avatar read"
  on storage.objects
  for select
  to public
  using (bucket_id = 'avatars');
