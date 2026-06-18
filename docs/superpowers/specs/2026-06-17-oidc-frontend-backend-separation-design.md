# HappyImage OIDC Login and Frontend/Backend Separation Design

Date: 2026-06-17

## Summary

HappyImage will add first-party web login through a generic OpenID Connect provider and split the product into two required services: a FastAPI backend service and a separate frontend service. The web application will use secure HttpOnly cookie sessions. The OpenAI-compatible API will continue to use Bearer tokens so existing external clients remain compatible.

This design is specifically for HappyImage user login. It does not replace or redesign the existing OpenAI upstream account OAuth import flow under `/api/accounts/oauth/*`.

## Goals

- Add generic OIDC login for HappyImage web users.
- Automatically create a normal HappyImage user on first successful OIDC login.
- Give newly created OIDC users `0` image quota by default.
- Preserve existing admin access through local admin login and access keys as a recovery path.
- Use HttpOnly cookie sessions for browser UI requests.
- Keep `/v1/*` OpenAI-compatible API access based on `Authorization: Bearer <token>`.
- Make frontend and backend separate required services in Docker and local development.
- Support OIDC configuration from environment variables, `config.json`, and an admin settings UI with secret redaction.

## Non-Goals

- Do not redesign the OpenAI upstream account OAuth import and refresh flow.
- Do not support multiple OIDC providers in the first version.
- Do not map OIDC groups or claims to admin roles.
- Do not map OIDC claims to quota grants beyond a configurable default quota.
- Do not store provider refresh tokens for long-lived upstream identity sessions.
- Do not implement provider-side logout.
- Do not keep the one-container backend-serves-frontend deployment as the primary path.

## Current Context

The current codebase has one FastAPI app that exposes both OpenAI-compatible routes and admin/frontend-facing routes. It also serves a static Next.js export from `web_dist` when present. The frontend already has a separate `web` project and uses `web/src/constants/common-env.ts` to choose a backend base URL in development.

Authentication is currently centered on Bearer-style access keys:

- `services.auth_service.AuthService` stores admin and user key records through the configured storage backend.
- `api.support.require_identity()` accepts the legacy `HAPPYIMAGE_AUTH_KEY` admin token or a stored auth key.
- `/api/auth/login` supports local admin/password style login and access-key login.
- The frontend stores the current key/session in IndexedDB through `web/src/store/auth.ts`.
- User quota is already attached to user auth key records and enforced by image routes.

The repository also contains `services.oauth_login_service`, but that service is for importing OpenAI upstream account tokens into the account pool. It is not the same auth domain as HappyImage user login.

## Recommended Approach

Use an Auth Session Gateway approach.

The backend owns OIDC protocol handling and browser session creation. The frontend only redirects users to backend login endpoints and reads the current session from backend APIs. Browser authentication and external API authentication become separate but compatible channels:

- Web UI: OIDC login -> backend session -> HttpOnly cookie.
- External API clients: existing Bearer tokens -> `/v1/*`.

This is preferred over returning a Bearer token to the frontend because it avoids exposing the primary web session token to JavaScript. It is also preferred over a full identity-provider mapping layer because group, role, and quota mapping would make the first version much larger and riskier than needed.

## Architecture

### Services

`happyimage-api` is the backend service. It contains FastAPI routes, storage access, image APIs, OIDC callback handling, session cookie handling, and OpenAI-compatible `/v1/*` APIs. It no longer serves the frontend static export as the main deployment path.

`happyimage-web` is the frontend service. It serves the Next.js static export or another lightweight frontend runtime. It does not contain OIDC secrets. It sends browser requests to `NEXT_PUBLIC_API_BASE_URL`.

### Backend Auth Boundaries

Add an `OAuthProviderService` for generic OIDC behavior:

- Load OIDC configuration.
- Fetch and cache discovery metadata.
- Build authorize URLs with `state`, `nonce`, and PKCE.
- Store short-lived login transaction data.
- Exchange callback `code` for provider tokens.
- Validate required token response fields.
- Read stable user claims from `id_token` and/or `userinfo`.
- Enforce allowed email domains.

Add a `WebSessionService` for HappyImage browser sessions:

- Create signed server-side or stateless signed sessions.
- Set and clear the web session cookie.
- Resolve a cookie session into the same identity shape used by existing auth checks.
- Keep session duration configurable.
- Avoid storing provider access tokens in the browser.

Extend existing auth identity records to support OIDC-created users:

- `auth_provider`: initially `oidc`.
- `auth_subject`: stable OIDC `sub`.
- `email`: provider email when available.
- `external_name`: provider display name when available.
- `image_quota`: default `0` unless configured otherwise.

Existing user management continues to list and manage these users. Admins can recharge, disable, or delete OIDC-created users through the current user management flow.

### API Auth Policy

Routes under `/api/*` should accept either a valid web session cookie or a valid Bearer token, depending on endpoint needs. This allows the separated frontend to use cookies while existing admin tooling and migration workflows can still use Bearer tokens.

Routes under `/v1/*` continue to require Bearer authentication. They should not treat a browser cookie as API authentication. This keeps API clients predictable and avoids accidental ambient browser auth for OpenAI-compatible calls.

## Login Data Flow

1. The frontend login page shows an OIDC login button when backend session/config status reports OIDC as enabled.
2. The user clicks the OIDC login button.
3. The frontend calls `POST /api/auth/oidc/start` with an optional safe `next` path.
4. The backend verifies OIDC is enabled, creates a login transaction, and returns an authorize URL.
5. The frontend navigates the browser to the authorize URL.
6. The OIDC provider redirects back to `GET /api/auth/oidc/callback?code=...&state=...`.
7. The backend validates `state`, PKCE, and `nonce`.
8. The backend exchanges the authorization code for tokens.
9. The backend extracts `sub`, `email`, `email_verified`, and display name claims.
10. The backend enforces the allowed email-domain configuration when configured.
11. If an auth key user is already bound to `(auth_provider="oidc", auth_subject=sub)`, that user is loaded.
12. If no binding exists, the backend creates a new `role=user` record with default image quota `0`.
13. If the matching user is disabled, login is rejected.
14. The backend creates a HappyImage web session cookie and redirects to the configured frontend base URL plus a safe relative path.
15. The frontend calls `GET /api/auth/session` to load the current user and route the user to `/image`.

Admin local login remains available. Admins can use local credentials or access-key login even if OIDC is misconfigured.

## Session Data Flow

The frontend calls `GET /api/auth/session` during app boot and route guards. A valid cookie returns the same public identity shape used by the current login response:

```json
{
  "ok": true,
  "role": "user",
  "subject_id": "abc123",
  "name": "Alice",
  "image_quota": 0,
  "user": {
    "id": "abc123",
    "name": "Alice",
    "role": "user",
    "image_quota": 0
  }
}
```

`POST /api/auth/logout` clears the HappyImage session cookie and returns success. It does not redirect to the OIDC provider logout endpoint.

When a session is missing, expired, invalid, or references a deleted/disabled user, `/api/auth/session` returns `401`. The frontend clears its local UI session state and sends the user to `/login`.

## Configuration

Environment variables have highest priority, followed by `config.json`. The admin settings UI can update runtime configuration where supported, but secrets are never exposed back to the frontend.

Backend configuration:

- `HAPPYIMAGE_FRONTEND_BASE_URL`: public frontend origin, such as `https://image.example.com`.
- `HAPPYIMAGE_API_BASE_URL`: public backend origin, such as `https://api.example.com`.
- `HAPPYIMAGE_CORS_ORIGINS`: allowed frontend origins. Defaults to `HAPPYIMAGE_FRONTEND_BASE_URL` when set.
- `HAPPYIMAGE_SESSION_SECRET`: secret used to sign or encrypt web sessions.
- `HAPPYIMAGE_SESSION_COOKIE_NAME`: defaults to `happyimage_session`.
- `HAPPYIMAGE_SESSION_MAX_AGE_SECONDS`: browser session lifetime.
- `HAPPYIMAGE_OIDC_ENABLED`: enables OIDC login.
- `HAPPYIMAGE_OIDC_ISSUER`: OIDC issuer base URL.
- `HAPPYIMAGE_OIDC_CLIENT_ID`: OAuth client ID.
- `HAPPYIMAGE_OIDC_CLIENT_SECRET`: OAuth client secret.
- `HAPPYIMAGE_OIDC_SCOPES`: defaults to `openid profile email`.
- `HAPPYIMAGE_OIDC_ALLOWED_EMAIL_DOMAINS`: comma-separated email domain allowlist. Empty means no domain restriction.
- `HAPPYIMAGE_OIDC_DEFAULT_IMAGE_QUOTA`: default quota for auto-created OIDC users. The first version uses `0`.

Frontend configuration:

- `NEXT_PUBLIC_API_BASE_URL`: public backend base URL.

The settings page should add an OAuth/OIDC card that shows:

- enabled status,
- issuer,
- client ID,
- scopes,
- allowed email domains,
- default image quota,
- client secret status as configured or not configured.

When saving OIDC settings, an empty client secret means "leave the existing secret unchanged." A non-empty client secret replaces the stored value.

## Cookie and CORS Policy

Production cross-origin deployment requires HTTPS. When frontend and backend are on different sites, the session cookie must use:

- `HttpOnly`,
- `Secure`,
- `SameSite=None`,
- a path appropriate for API routes.

The API must enable CORS credentials only for configured origins. It should not use wildcard origins when credentials are enabled.

Local development can relax cookie security:

- frontend: `http://127.0.0.1:3000`,
- backend: `http://127.0.0.1:8000`,
- non-secure cookie allowed only in development mode,
- CORS origin set to the local frontend URL.

## Docker and Deployment

The deployment will move to two services:

- `happyimage-api`: Python/FastAPI backend, default exposed port `8000`.
- `happyimage-web`: frontend static service, default exposed port `3000`.

The backend image should remove the frontend build stage from its required runtime path. The frontend image should build and serve the Next.js export separately.

`docker-compose.yml` should start both services by default. The frontend service receives `NEXT_PUBLIC_API_BASE_URL`. The backend service receives storage, auth, OIDC, session, and CORS configuration.

Migration steps in documentation:

1. Update to the new compose file.
2. Set `HAPPYIMAGE_AUTH_KEY` for admin recovery.
3. Set `HAPPYIMAGE_SESSION_SECRET`.
4. Set `HAPPYIMAGE_FRONTEND_BASE_URL`.
5. Set `HAPPYIMAGE_API_BASE_URL`.
6. Configure OIDC issuer, client ID, and client secret.
7. Configure provider redirect URI as `<HAPPYIMAGE_API_BASE_URL>/api/auth/oidc/callback`.
8. Start `happyimage-api` and `happyimage-web`.
9. Verify backend health at `/health?format=json`.
10. Verify frontend login and session loading.

## Error Handling

If OIDC is disabled, the frontend hides the OAuth login option. Direct calls to OIDC start should return a clear error.

If discovery, token exchange, or userinfo retrieval fails, the backend logs a redacted diagnostic and returns a user-safe login failure message.

If `state`, `nonce`, or PKCE validation fails, the backend rejects the callback, clears the temporary login transaction, and asks the user to restart login.

If the email domain is not allowed, login is rejected before user creation.

If a matching OIDC user is disabled, login is rejected with a disabled-account message.

If an existing local user has the same email but is not bound to the OIDC subject, the first version does not auto-merge the accounts. It rejects login with an instruction to ask an administrator to resolve the account. This avoids account takeover through email-only matching.

If the session cookie is missing or expired, `/api/auth/session` returns `401` and the frontend redirects to `/login`.

## Compatibility

Existing external API clients that use Bearer tokens continue to work with `/v1/*`.

Existing admin recovery through `HAPPYIMAGE_AUTH_KEY` continues to work.

Existing user key records remain valid. OIDC-created users are represented as normal user records with additional identity-binding metadata.

The current OpenAI upstream account OAuth import flow remains available under account management and is not renamed in the first version. Documentation should distinguish "HappyImage OIDC login" from "OpenAI account OAuth import."

## Testing

Backend tests should cover:

- OIDC configuration parsing and secret redaction.
- OIDC disabled behavior.
- authorize URL generation with state, nonce, and PKCE.
- callback validation for state, nonce, and PKCE.
- token exchange and claim extraction using a mocked provider.
- allowed email-domain enforcement.
- first-login user creation with `role=user` and `image_quota=0`.
- repeated OIDC login reuses the same user by provider subject.
- disabled OIDC user cannot log in.
- same-email different-subject conflict is rejected.
- web session cookie can authenticate `/api/*`.
- Bearer token still authenticates `/v1/*`.
- cookie session does not authenticate `/v1/*`.

Frontend tests or build checks should cover:

- login page shows OIDC login only when enabled.
- OIDC start redirects through the backend-provided URL.
- session boot uses `GET /api/auth/session`.
- `401` from session or protected APIs returns the user to `/login`.
- API requests use `NEXT_PUBLIC_API_BASE_URL` and include credentials for cookie sessions.

Deployment verification should cover:

- `docker compose up` starts separate web and API services.
- API health check passes.
- frontend can reach the configured backend.
- CORS credentials work only for configured origins.
- OIDC redirect URI examples match the backend public base URL.

## Implementation Boundaries

The implementation should be staged to reduce risk:

1. Add backend session and OIDC services behind feature flags.
2. Extend auth storage normalization to preserve OIDC metadata.
3. Add cookie-aware auth resolution for `/api/*` while keeping Bearer behavior.
4. Update frontend login/session handling to support cookie sessions.
5. Split Docker build and compose services.
6. Add settings UI and secret redaction.
7. Update deployment documentation and regression tests.

The first implementation plan should avoid unrelated refactors. In particular, it should not restructure the OpenAI account pool OAuth flow unless a direct naming conflict must be resolved.

## Acceptance Criteria

- A user can log into HappyImage through a configured generic OIDC provider.
- The first successful OIDC login creates a normal user with `0` image quota.
- The web UI authenticates with an HttpOnly cookie session.
- `/v1/*` remains Bearer-token based and does not accept web cookies as authentication.
- Admin local login or access-key login still works as a recovery path.
- Frontend and backend run as separate Docker services.
- OIDC secrets are never embedded in the frontend bundle or returned unmasked by settings APIs.
- CORS with credentials is restricted to configured frontend origins.
- Existing OpenAI upstream account OAuth import remains functionally separate.

## Risks and Mitigations

- Risk: Cross-origin cookies fail in production if HTTPS or SameSite settings are wrong.
  Mitigation: Document HTTPS as required for cross-site production deployments and add explicit CORS/cookie tests.

- Risk: OIDC misconfiguration locks users out.
  Mitigation: Preserve local admin login and access-key login as recovery paths.

- Risk: Email-only account merging can cause account takeover.
  Mitigation: Bind users by provider subject and reject same-email conflicts in the first version.

- Risk: Splitting Docker services breaks existing single-container deployment expectations.
  Mitigation: Treat this as an intentional breaking deployment change and document migration steps clearly.

- Risk: OIDC login and OpenAI account OAuth import are confused because both use OAuth language.
  Mitigation: Use distinct names in code and documentation: "HappyImage OIDC login" and "OpenAI account OAuth import."
