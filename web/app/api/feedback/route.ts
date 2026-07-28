import { createHmac, randomUUID } from "node:crypto";
import type { NextRequest } from "next/server";
import { resolveManagerAccess } from "../../lib/manager-access";

export const dynamic = "force-dynamic";

const MAX_MESSAGE = 4_000;
const MAX_SUBJECT = 120;
const KINDS = new Set(["feedback", "suggestion"]);

function json(message: string, status: number, requestId?: string) {
  return Response.json(
    { message },
    {
      status,
      headers: {
        "cache-control": "private, no-store",
        ...(requestId ? { "x-request-id": requestId } : {}),
      },
    },
  );
}

export async function POST(request: NextRequest) {
  const requestId = randomUUID();
  const access = resolveManagerAccess(request);
  if (!access) {
    return json("You are not authorized to send feedback.", 403, requestId);
  }

  const resendKey = process.env.RESEND_API_KEY;
  const feedbackTo = process.env.FEEDBACK_TO_EMAIL;
  const auditKey = process.env.BAR_AUDIT_HASH_KEY;
  if (!resendKey || !feedbackTo) {
    return json(
      "Feedback email is not configured yet. Please contact the owner directly.",
      503,
      requestId,
    );
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return json("Feedback payload was invalid.", 400, requestId);
  }

  const record =
    body && typeof body === "object" && !Array.isArray(body)
      ? (body as Record<string, unknown>)
      : {};
  const kind = typeof record.kind === "string" ? record.kind.trim().toLowerCase() : "";
  const subject =
    typeof record.subject === "string" ? record.subject.trim().slice(0, MAX_SUBJECT) : "";
  const message =
    typeof record.message === "string" ? record.message.trim().slice(0, MAX_MESSAGE) : "";

  if (!KINDS.has(kind) || message.length < 8) {
    return json(
      "Please choose Feedback or Suggestion and include a short message.",
      400,
      requestId,
    );
  }

  const actor = auditKey
    ? createHmac("sha256", auditKey).update(access.email).digest("hex").slice(0, 24)
    : "unhashed";
  const label = kind === "suggestion" ? "Suggestion" : "Feedback";
  const mailSubject =
    subject || `[Bar Arbolada] ${label} from ${access.role}`;
  const text = [
    `${label} from a private analytics viewer`,
    `Role: ${access.role}`,
    `Actor: ${actor}`,
    `Request: ${requestId}`,
    "",
    message,
  ].join("\n");

  try {
    const upstream = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        authorization: `Bearer ${resendKey}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        from: process.env.FEEDBACK_FROM_EMAIL || "Bar Arbolada Analytics <onboarding@resend.dev>",
        to: [feedbackTo],
        subject: mailSubject,
        text,
      }),
      signal: AbortSignal.timeout(10_000),
    });

    if (!upstream.ok) {
      console.info(
        JSON.stringify({
          event: "manager_feedback_failed",
          request_id: requestId,
          actor,
          role: access.role,
          status: upstream.status,
        }),
      );
      return json("Could not send feedback right now. Please try again later.", 502, requestId);
    }

    console.info(
      JSON.stringify({
        event: "manager_feedback_sent",
        request_id: requestId,
        actor,
        role: access.role,
        kind,
      }),
    );
    return Response.json(
      { message: "Thank you — your note was sent." },
      {
        status: 200,
        headers: {
          "cache-control": "private, no-store",
          "x-request-id": requestId,
        },
      },
    );
  } catch {
    return json("Could not send feedback right now. Please try again later.", 502, requestId);
  }
}
