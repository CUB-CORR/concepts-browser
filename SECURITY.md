# Security Policy

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Instead, use GitHub's
[private vulnerability reporting](../../security/advisories/new) for this repository.

We will acknowledge reports as quickly as we can and keep you informed of the fix's
progress. Please include a description of the issue, steps to reproduce, and the affected
version/commit.

## Scope notes for deployments

- Set strong values for `JWT_SECRET`, `BOOTSTRAP_ADMIN_PASSWORD`, `INTERNAL_TOKEN` and
  `APP_SHARED_SECRET`; never ship the defaults from `example.env`.
- Always set `LDAP_TLS_CA_CERTS_FILE` in production — an empty value disables LDAPS
  certificate validation and is intended for development only.
- Terminate TLS in front of both services with a reverse proxy; the containers speak plain
  HTTP.
