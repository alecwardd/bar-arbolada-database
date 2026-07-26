# Manager API relay

This Cloudflare Worker is the narrow public edge in front of the private
manager API. Its Workers VPC binding routes only to `127.0.0.1:8600` through
the `bar-arbolada-managers` Cloudflare Tunnel.

The Worker:

- accepts only `GET`;
- permits only manager dashboard and health/readiness paths;
- requires two long relay credentials in the existing
  `CF-Access-Client-Id` and `CF-Access-Client-Secret` request headers;
- passes the separate API bearer token only to the local FastAPI service;
- never receives PostgreSQL credentials; and
- strips cookies and unrelated upstream headers from responses.

The two Worker secrets are named `RELAY_CLIENT_ID` and
`RELAY_CLIENT_SECRET`. The matching values live only in the Sites production
environment as `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET`.

Run `npm test` in this directory before deployment. Deploy with Wrangler only
after the VPC service binding in `wrangler.jsonc` has been verified against the
intended tunnel and loopback port.
