-- Calendly booking RPCs for Zapier (no hosted webhook required)
-- Run after 20260803180000_calendly_r1_booking.sql (columns must exist)

create or replace function public.apply_calendly_booking(
  p_email text,
  p_start_time timestamptz,
  p_invitee_uri text default null,
  p_event_uri text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_email text := lower(trim(p_email));
  v_row public.candidates%rowtype;
  v_advanced boolean := false;
  v_from_stage text;
begin
  if v_email is null or v_email = '' then
    return jsonb_build_object('ok', false, 'reason', 'missing_email');
  end if;

  if p_invitee_uri is not null and length(trim(p_invitee_uri)) > 0 then
    select * into v_row
    from public.candidates
    where calendly_invitee_uri = trim(p_invitee_uri)
    limit 1;
  end if;

  if not found then
    select * into v_row
    from public.candidates
    where lower(trim(email)) = v_email
    order by
      case pipeline_stage
        when 'outreached' then 0
        when 'qualified' then 1
        when 'identified' then 2
        when 'round_1_scheduled' then 3
        else 9
      end,
      updated_at desc nulls last
    limit 1;
  end if;

  if not found then
    return jsonb_build_object('ok', false, 'reason', 'candidate_not_found', 'email', v_email);
  end if;

  v_from_stage := v_row.pipeline_stage;

  update public.candidates
  set
    r1_scheduled_at = p_start_time,
    calendly_invitee_uri = coalesce(nullif(trim(p_invitee_uri), ''), calendly_invitee_uri),
    calendly_event_uri = coalesce(nullif(trim(p_event_uri), ''), calendly_event_uri),
    updated_at = now()
  where id = v_row.id;

  if v_from_stage in ('identified', 'qualified', 'outreached') then
    update public.candidates
    set pipeline_stage = 'round_1_scheduled', updated_at = now()
    where id = v_row.id;
    v_advanced := true;

    begin
      insert into public.candidate_activities (candidate_id, activity_type, channel, actor, payload)
      values (
        v_row.id,
        'stage_changed',
        'calendly',
        'zapier',
        jsonb_build_object(
          'from', v_from_stage,
          'to', 'round_1_scheduled',
          'reason', 'calendly_invitee_created'
        )
      );
    exception
      when undefined_table then null;
    end;
  end if;

  begin
    insert into public.candidate_activities (candidate_id, activity_type, channel, actor, payload)
    values (
      v_row.id,
      'calendly_booked',
      'calendly',
      'zapier',
      jsonb_build_object(
        'email', v_email,
        'start_time', p_start_time,
        'invitee_uri', p_invitee_uri,
        'event_uri', p_event_uri,
        'stage_advanced', v_advanced
      )
    );
    update public.candidates
    set last_activity_at = now()
    where id = v_row.id;
  exception
    when undefined_table then null;
    when undefined_column then null;
  end;

  return jsonb_build_object(
    'ok', true,
    'candidate_id', v_row.id,
    'full_name', v_row.full_name,
    'advanced', v_advanced,
    'r1_scheduled_at', p_start_time
  );
end;
$$;

create or replace function public.apply_calendly_cancel(
  p_email text default null,
  p_invitee_uri text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_email text := lower(trim(coalesce(p_email, '')));
  v_row public.candidates%rowtype;
  v_reverted boolean := false;
  v_from_stage text;
begin
  if p_invitee_uri is not null and length(trim(p_invitee_uri)) > 0 then
    select * into v_row
    from public.candidates
    where calendly_invitee_uri = trim(p_invitee_uri)
    limit 1;
  end if;

  if not found and v_email <> '' then
    select * into v_row
    from public.candidates
    where lower(trim(email)) = v_email
    order by updated_at desc nulls last
    limit 1;
  end if;

  if not found then
    return jsonb_build_object(
      'ok', false,
      'reason', 'candidate_not_found',
      'email', nullif(v_email, '')
    );
  end if;

  v_from_stage := v_row.pipeline_stage;

  update public.candidates
  set
    r1_scheduled_at = null,
    calendly_invitee_uri = null,
    calendly_event_uri = null,
    updated_at = now()
  where id = v_row.id;

  if v_from_stage = 'round_1_scheduled' then
    update public.candidates
    set pipeline_stage = 'outreached', updated_at = now()
    where id = v_row.id;
    v_reverted := true;

    begin
      insert into public.candidate_activities (candidate_id, activity_type, channel, actor, payload)
      values (
        v_row.id,
        'stage_changed',
        'calendly',
        'zapier',
        jsonb_build_object(
          'from', v_from_stage,
          'to', 'outreached',
          'reason', 'calendly_invitee_canceled'
        )
      );
    exception
      when undefined_table then null;
    end;
  end if;

  begin
    insert into public.candidate_activities (candidate_id, activity_type, channel, actor, payload)
    values (
      v_row.id,
      'calendly_canceled',
      'calendly',
      'zapier',
      jsonb_build_object(
        'email', nullif(v_email, ''),
        'invitee_uri', p_invitee_uri,
        'stage_reverted', v_reverted
      )
    );
    update public.candidates
    set last_activity_at = now()
    where id = v_row.id;
  exception
    when undefined_table then null;
    when undefined_column then null;
  end;

  return jsonb_build_object(
    'ok', true,
    'candidate_id', v_row.id,
    'full_name', v_row.full_name,
    'reverted', v_reverted
  );
end;
$$;

revoke all on function public.apply_calendly_booking(text, timestamptz, text, text) from public;
revoke all on function public.apply_calendly_cancel(text, text) from public;
grant execute on function public.apply_calendly_booking(text, timestamptz, text, text) to service_role;
grant execute on function public.apply_calendly_cancel(text, text) to service_role;
