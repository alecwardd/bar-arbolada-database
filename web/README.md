# Bar Arbolada Manager Analytics

Private, read-only management dashboard published through OpenAI Sites. The
visual language follows the existing Streamlit dashboards while the data path
remains deliberately separate:

```text
authorized Sites user -> same-origin BFF -> Cloudflare Access
  -> local FastAPI read API -> local PostgreSQL
```

## Local development

Prerequisite: Node.js 22.13 or newer.

```bash
npm install
npm run dev
npm run build
npm test
```

Create an ignored `.env.local` with:

```dotenv
BAR_API_BASE_URL=http://127.0.0.1:8600
MANAGER_API_TOKEN=<local development token>
RESEND_API_KEY=<optional local Resend key>
FEEDBACK_TO_EMAIL=<your inbox>
FEEDBACK_FROM_EMAIL=Bar Arbolada Analytics <onboarding@resend.dev>
```

Production additionally requires an HTTPS API URL, Cloudflare Access service
credentials, an HMAC audit key, an exact email-to-role map, Resend feedback
secrets, and a private Sites access policy. Secrets are server-side only; the
browser calls `/api/manager/*`, `/api/me`, and `/api/feedback` on the same
origin. See `../planning-documents/sites-manager-dashboard-runbook.md` for
setup, deployment, rotation, and rollback.
