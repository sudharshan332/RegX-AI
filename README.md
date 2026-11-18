# RegX-AI (Regression Dashboard)

RegX-AI is a web app for planning, running, and analyzing regression tests. It is a React frontend and a Flask backend, with LDAP login and team-scoped data.

**Docs:** architecture, integrations, and APIs are in [PROJECT_DOCUMENTATION_AND_ARCHITECTURE.md](PROJECT_DOCUMENTATION_AND_ARCHITECTURE.md). Agent orientation is in [AGENTS.md](AGENTS.md).

## Stack

- **Frontend:** React 19 in `src/` (Create React App). Dev server on port **3000**; `package.json` proxies API calls to port **5001**.
- **Backend:** Flask in `backend/test_flask.py`. JSON routes live under `/mcp/regression/`.
- **Auth:** LDAP (Active Directory) plus JWT. Login includes a team. The UI stays behind the login page until a session exists.
- **Storage:** JSON and CSV under `data/{TEAM}/`. Default teams are `CDP_FT` and `CDP_ST` (`teams.json`).

## Pages

Sidebar pages in `src/App.jsx`:

| Page | What it covers |
|------|----------------|
| Home | Regression overview by tag or task IDs, triage, QI |
| Release Dashboard | Release status and feature readiness |
| Run Plan | Scheduling, triggers, calendar, job profiles |
| Handover | New testcase onboarding (LST, Jira, Gerrit) |
| Testcase Management | Browse and tag testcases via TCMS |
| Triage Genie | Automated failure triage jobs |
| Failed Testcase Analysis | Rule-based and AI failure analysis |
| Run Report | QI analysis and email |
| Manage Job Profile | Create, clone, update, and migrate job profiles |
| Cursor AI | Interactive AI chat, skills, and per-user API keys |

## Prerequisites

- Node.js and npm
- Python 3

## Setup

```bash
npm install
pip install -r requirements.txt
```

Use `pip3` if `pip` is not available.

Create a `.env` in the project root (or export the same variables). Do not commit secrets.

| Variable | Role |
|----------|------|
| `REACT_APP_API_URL` | Frontend API base (no trailing slash). Read through `src/config.js`. For local dev the proxy is enough and this can stay unset. |
| `FLASK_HOST` | Bind address. Use `0.0.0.0` when other machines must reach the API. |
| `FLASK_PORT` | Backend port (default `5001`). |
| `FLASK_DEBUG` | Flask debug flag. |
| `SECRET_KEY` or `REGX_SECRET_KEY` | JWT signing secret. |
| `REGX_ENCRYPTION_KEY` | Fernet key for encrypted per-user API keys. |

Rebuild the frontend (`npm run build`) after changing `REACT_APP_API_URL` so the production bundle picks it up.

## Run

Backend (port 5001):

```bash
python3 backend/test_flask.py
```

or:

```bash
./start_backend.sh
```

Frontend (port 3000):

```bash
npm start
```

Start the backend before the UI. Open [http://localhost:3000](http://localhost:3000), sign in, and pick a team.

Production frontend:

```bash
npm run build
```

Serve the `build/` folder and point `REACT_APP_API_URL` at the running backend. Allow the frontend and backend ports through the firewall.

## Cursor bridge and RegX MCP

Flask and the React app are enough for the rest of the dashboard. Start these only for **Cursor AI** chat and **failed-test AI analysis**.

### Cursor bridge (required for those features)

From `cursor-bridge/`, `npm start` runs `start.sh` and listens on port **5002** (`CURSOR_BRIDGE_PORT`). Flask calls it at `CURSOR_BRIDGE_URL` (default `http://localhost:5002`).

The Cursor API key comes from the signed-in user’s saved keys, or from `CURSOR_API_KEY` in the environment. Do not commit the key.

```bash
cd cursor-bridge
npm start
```

### RegX MCP (optional)

From `cursor-bridge/`, `npm run start:mcp` runs `mcp-server.js` on port **5003**. Set `REGX_BACKEND_URL` to the Flask base (default `http://localhost:5001`) so the agent can call RegX data. The bridge attaches this server when MCP tools are enabled (`REGX_MCP_URL`, default `http://localhost:5003`).

```bash
cd cursor-bridge
REGX_BACKEND_URL="http://localhost:5001" npm run start:mcp
```

### Health checks

```bash
curl http://localhost:5002/health
curl http://localhost:5003/health
```

## Scripts

- `npm start` — development server with reload
- `npm test` — Jest test runner
- `npm run build` — production bundle in `build/`

## Code review

Push review updates to `refs/for/<branch>` (for example `refs/for/main`). Do not push directly to the integration branch.
