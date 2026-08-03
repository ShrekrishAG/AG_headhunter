-- Add General Manager (Roofing / Sales) role for dashboard + pipeline filtering

insert into public.roles (slug, title)
values ('general-manager', 'General Manager (Roofing / Sales)')
on conflict (slug) do update
set title = excluded.title;
