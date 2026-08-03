-- Prospect import batch tracking (Pipeline filter)

alter table public.candidates
  add column if not exists import_batch text;

create index if not exists candidates_import_batch_idx
  on public.candidates (import_batch)
  where import_batch is not null;
