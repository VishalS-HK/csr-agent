# CSR Agent

## Customer authentication

Customers log in with Supabase Auth. Each API request carries the Supabase
access token as `Authorization: Bearer <token>`. The app checks the token's
signature against the project's public keys
(`$SUPABASE_URL/auth/v1/.well-known/jwks.json`, ES256), its expiry, audience
and issuer. It then uses the token's `sub` to look up the matching
`app.customers.external_auth_subject`. Identity always comes from the token,
never from the request body or the model.

| Result | Status |
| --- | --- |
| Missing, invalid or expired token | 401 |
| Valid login, but no linked customer | 403 |
| Signing keys or database unreachable | 503 |

### Give the seeded customers logins

Set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in `.env`, then:

```sh
python scripts/link_auth_users.py --password 'pick-a-test-password'
```

Run it again after `python scripts/seed_data.py --reset`, because the reset
empties `app.customers` and with it the links.

### Get a test token

Use the project's **publishable** (or legacy anon) key from Project Settings →
API Keys:

```sh
curl -s "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: <publishable-key>" -H "Content-Type: application/json" \
  -d '{"email": "asha@example.com", "password": "pick-a-test-password"}' \
  | python -c "import json,sys; print(json.load(sys.stdin)['access_token'])"
```

The token is valid for about an hour.
