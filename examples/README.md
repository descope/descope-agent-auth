# Examples

Small, runnable agents that exercise the SDK against a real Descope project. Each
script is self-contained, reads its config from environment variables, and prints
what it got back.

## Setup

1. Have a Descope project with an **Outbound App / Connection** configured (e.g.
   `github`) and/or a **Resource** registered.
2. Copy the env template and fill it in:
   ```bash
   cp .env.example .env
   ```
3. Run an example (see each language folder below). Both honor the same variables.

## Environment variables

| Variable | Used by | Meaning |
| --- | --- | --- |
| `DESCOPE_PROJECT_ID` | all | Your Descope project id (`P2…`). |
| `DESCOPE_BASE_URL` | all | Optional. Defaults to `https://api.descope.com`. |
| `DESCOPE_USER_JWT` | user examples | A **user's** Descope access token. Required to fetch a user-level Connection token. |
| `DESCOPE_USER_IDENTIFIER` | user examples | The user id / login id whose token you're fetching. |
| `DESCOPE_CLIENT_ID` / `DESCOPE_CLIENT_SECRET` | autonomous example | The agent's OAuth client credentials (its identity in your Agent Directory). |
| `CONNECTION_NAME` | all | Connection to fetch (default `github`, or `slack` for the tenant example). |
| `TENANT_ID` | autonomous example | Tenant whose org-shared (tenant-level) token to fetch. |
| `RESOURCE` | autonomous example | Resource URN to mint a Resource token for (e.g. `urn:my-api`). |

> **Why two credential styles?** A user-level Connection token can only be fetched
> with the **user's** token (or a management key); an **autonomous** agent
> (client credentials, no user) can mint Resource tokens and fetch **tenant-level**
> Connection tokens, but not a user's. The examples are split along that line.

## Python

```bash
cd python
pip install -r requirements.txt          # installs descope-agent-auth
set -a; source ../.env; set +a           # load env vars

python user_connection.py                # fetch a user's Connection token (+ connect-URL flow)
python autonomous_agent.py               # Resource token + tenant-level Connection token
python tool_ergonomic.py                 # the @with_connection tool wrapper
```

## TypeScript

```bash
cd typescript
npm install                              # installs @descope/agent-auth + tsx

npm run user        -- # or: npx tsx --env-file=../.env userConnection.ts
npm run autonomous  -- # npx tsx --env-file=../.env autonomousAgent.ts
```

(Node 20+ reads `.env` via `--env-file`; the npm scripts wire that up for you.)
