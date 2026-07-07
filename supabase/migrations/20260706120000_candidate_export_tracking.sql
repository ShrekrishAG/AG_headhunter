-- ZipRecruiter export batch + per-candidate export timestamp

alter table public.candidates
  add column if not exists exported_at timestamptz,
  add column if not exists export_batch text;

create index if not exists candidates_export_batch_idx
  on public.candidates (export_batch);

create index if not exists candidates_exported_at_idx
  on public.candidates (exported_at desc);
