# Self-hosted accounts

Self-hosted mode uses local username/password accounts. Cloud mode keeps its
existing magic-link, Google, billing, and user identity flows unchanged.

## First startup

Set these values in `openshorts/.env` before starting Docker Compose:

```dotenv
LOCAL_AUTH_ENABLED=true
JWT_SECRET=<random secret with at least 32 characters>
INITIAL_ADMIN_PASSWORD=<private bootstrap password with at least 8 characters>
```

On the first start, MyClipper creates `francisco082` as the one bootstrap
administrator and forces a password change after login. The password is hashed
with Argon2; the configured password is never saved. The bootstrap password is
accepted only for this forced-change login; every later password must have at
least 12 characters. Later starts never reset
that account's password or settings. Existing unowned self-hosted projects are
assigned to this bootstrap administrator once so they remain accessible.

Generate `JWT_SECRET` with a cryptographically secure random generator and keep
both values out of source control. The SQLite database and refresh sessions live
in the persistent Docker volume `local_auth_data`. Back it up with the rest of
the deployment data. Do not remove that volume when rebuilding the images.

The default refresh cookie is HttpOnly, SameSite=Lax, and Secure whenever the
request or `PUBLIC_API_URL` uses HTTPS. Set `AUTH_COOKIE_SECURE=true` when TLS
terminates upstream and the backend itself only sees HTTP.

## Sessions and users

Access JWTs last 15 minutes. A seven-day HttpOnly refresh cookie rotates on each
use. Reuse of a revoked token revokes its refresh-token family. Password changes,
resets, account deactivation, and expiration revoke active refresh sessions.
Passwords require at least 12 characters.

The administrator can manage accounts from the profile menu. Only `admin` and
`user` roles exist; the final active administrator cannot be disabled or
demoted. Accounts are deactivated rather than deleted, and an expired account
is automatically deactivated on its next access.

To temporarily restore the previous unauthenticated self-hosted behavior, set
`LOCAL_AUTH_ENABLED=false`. Private API calls are protected while local auth is
enabled; `/api/config`, health checks, and the intentionally public `/api/tools`
utilities remain public.

After configuring `.env`, build and start as usual:

```sh
docker compose up -d --build
```
