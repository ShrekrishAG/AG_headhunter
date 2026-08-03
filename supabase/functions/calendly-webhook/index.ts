/**
 * Calendly → Headhunter Pipeline
 * POST /functions/v1/calendly-webhook
 *
 * Deploy (JWT verify off — Calendly cannot send a Supabase JWT):
 *   supabase functions deploy calendly-webhook --no-verify-jwt
 *
 * Secrets:
 *   CALENDLY_WEBHOOK_SIGNING_KEY  (from Calendly webhook subscription)
 * SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY are injected automatically.
 */

import { createClient } from "https://esm.sh/@supabase/supabase-js@2.49.1";

const enc = new TextEncoder();

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let out = 0;
  for (let i = 0; i < a.length; i++) out |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return out === 0;
}

async function verifyCalendlySignature(
  rawBody: string,
  header: string | null,
  signingKey: string,
  toleranceSec = 300,
): Promise<boolean> {
  if (!header || !signingKey) return false;
  const parts: Record<string, string> = {};
  for (const chunk of header.split(",")) {
    const [k, ...rest] = chunk.split("=");
    if (k && rest.length) parts[k.trim()] = rest.join("=").trim();
  }
  const timestamp = parts["t"];
  const signature = parts["v1"];
  if (!timestamp || !signature) return false;
  const ts = Number(timestamp);
  if (!Number.isFinite(ts)) return false;
  if (Math.abs(Math.floor(Date.now() / 1000) - ts) > toleranceSec) return false;

  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(signingKey),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const mac = await crypto.subtle.sign(
    "HMAC",
    key,
    enc.encode(`${timestamp}.${rawBody}`),
  );
  const expected = [...new Uint8Array(mac)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return timingSafeEqual(expected, signature);
}

type CalendlyBody = {
  event?: string;
  payload?: {
    email?: string;
    name?: string;
    uri?: string;
    scheduled_event?: {
      uri?: string;
      start_time?: string;
    };
    start_time?: string;
  };
};

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return Response.json({
      ok: true,
      service: "calendly-webhook",
      signing_key_configured: Boolean(
        Deno.env.get("CALENDLY_WEBHOOK_SIGNING_KEY")?.trim(),
      ),
    });
  }

  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  const rawBody = await req.text();
  const signingKey = Deno.env.get("CALENDLY_WEBHOOK_SIGNING_KEY")?.trim() ?? "";
  const skipVerify =
    (Deno.env.get("CALENDLY_SKIP_SIGNATURE_VERIFY") || "").toLowerCase() ===
      "true" ||
    Deno.env.get("CALENDLY_SKIP_SIGNATURE_VERIFY") === "1";

  if (signingKey && !skipVerify) {
    const header = req.headers.get("Calendly-Webhook-Signature");
    const valid = await verifyCalendlySignature(rawBody, header, signingKey);
    if (!valid) {
      return Response.json({ ok: false, reason: "invalid_signature" }, {
        status: 401,
      });
    }
  } else if (!signingKey && !skipVerify) {
    return Response.json(
      { ok: false, reason: "signing_key_not_configured" },
      { status: 503 },
    );
  }

  let body: CalendlyBody;
  try {
    body = JSON.parse(rawBody) as CalendlyBody;
  } catch {
    return Response.json({ ok: false, reason: "invalid_json" }, { status: 400 });
  }

  const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
  if (!supabaseUrl || !serviceKey) {
    return Response.json({ ok: false, reason: "supabase_env_missing" }, {
      status: 500,
    });
  }

  const sb = createClient(supabaseUrl, serviceKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  const event = (body.event || "").trim();
  const invitee = body.payload || {};
  const email = (invitee.email || "").trim().toLowerCase();
  const inviteeUri = (invitee.uri || "").trim() || null;
  const eventUri = (invitee.scheduled_event?.uri || "").trim() || null;
  const startTime =
    (invitee.scheduled_event?.start_time || invitee.start_time || "").trim() ||
    null;

  try {
    if (event === "invitee.created") {
      if (!email || !startTime) {
        return Response.json({
          ok: false,
          event,
          reason: "missing_email_or_start_time",
        });
      }
      const { data, error } = await sb.rpc("apply_calendly_booking", {
        p_email: email,
        p_start_time: startTime,
        p_invitee_uri: inviteeUri,
        p_event_uri: eventUri,
      });
      if (error) {
        console.error("apply_calendly_booking", error);
        return Response.json(
          { ok: false, event, reason: error.message },
          { status: 500 },
        );
      }
      // Always 200 when handled (including candidate_not_found) — avoid Calendly retry storms
      return Response.json({ event, ...(data as Record<string, unknown>) });
    }

    if (event === "invitee.canceled") {
      const { data, error } = await sb.rpc("apply_calendly_cancel", {
        p_email: email || null,
        p_invitee_uri: inviteeUri,
      });
      if (error) {
        console.error("apply_calendly_cancel", error);
        return Response.json(
          { ok: false, event, reason: error.message },
          { status: 500 },
        );
      }
      return Response.json({ event, ...(data as Record<string, unknown>) });
    }

    return Response.json({ ok: true, event, reason: "ignored" });
  } catch (err) {
    console.error(err);
    return Response.json({ ok: false, reason: "handler_error" }, { status: 500 });
  }
});
