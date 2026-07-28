"use client";

import { useState, type FormEvent } from "react";

type FeedbackDialogProps = {
  open: boolean;
  onClose: () => void;
};

export function FeedbackDialog({ open, onClose }: FeedbackDialogProps) {
  const [kind, setKind] = useState<"feedback" | "suggestion">("feedback");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [error, setError] = useState("");

  if (!open) return null;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("sending");
    setError("");
    try {
      const response = await fetch("/api/feedback", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          accept: "application/json",
          "content-type": "application/json",
        },
        body: JSON.stringify({ kind, subject, message }),
      });
      const body = (await response.json().catch(() => ({}))) as { message?: string };
      if (!response.ok) {
        setStatus("error");
        setError(body.message ?? "Could not send your note.");
        return;
      }
      setStatus("sent");
      setSubject("");
      setMessage("");
    } catch {
      setStatus("error");
      setError("Could not send your note.");
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation" onClick={onClose}>
      <div
        className="dialog-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="feedback-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="dialog-heading">
          <div>
            <p className="eyebrow">Partner notes</p>
            <h2 id="feedback-title">Send feedback</h2>
          </div>
          <button type="button" className="ghost-button" onClick={onClose}>
            Close
          </button>
        </div>

        {status === "sent" ? (
          <div className="dialog-success">
            <strong>Thank you.</strong>
            <p>Your note was sent to the Bar Arbolada team.</p>
            <button type="button" onClick={onClose}>
              Done
            </button>
          </div>
        ) : (
          <form className="feedback-form" onSubmit={(event) => void onSubmit(event)}>
            <div className="segmented" role="group" aria-label="Note type">
              <button
                type="button"
                className={kind === "feedback" ? "active" : ""}
                aria-pressed={kind === "feedback"}
                onClick={() => setKind("feedback")}
              >
                Feedback
              </button>
              <button
                type="button"
                className={kind === "suggestion" ? "active" : ""}
                aria-pressed={kind === "suggestion"}
                onClick={() => setKind("suggestion")}
              >
                Suggestion
              </button>
            </div>

            <label>
              Subject <span>(optional)</span>
              <input
                value={subject}
                onChange={(event) => setSubject(event.target.value)}
                maxLength={120}
                placeholder="What should we look at?"
              />
            </label>

            <label>
              Message
              <textarea
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                maxLength={4000}
                rows={6}
                required
                minLength={8}
                placeholder="Tell us what is useful, confusing, or missing."
              />
            </label>

            {status === "error" ? <p className="form-error">{error}</p> : null}

            <div className="dialog-actions">
              <button type="button" className="ghost-button" onClick={onClose}>
                Cancel
              </button>
              <button type="submit" disabled={status === "sending"}>
                {status === "sending" ? "Sending…" : "Send note"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
