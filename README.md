# AgentFramework

Multi-Agent SDLC orchestration platform built with **Python**, **LangGraph**, and **FastAPI**.  
Designed for .NET 8 teams using DDD/CQRS with Human-in-the-Loop (HITL) approval gates.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     FastAPI + Dashboard                           │
├─────────────────────────────────────────────────────────────────┤
│  Scenario 1: Feature Pipeline          Scenario 2: Incident     │
│  ┌──────────┐  ┌──────────┐           ┌──────────────────────┐  │
│  │  Atlas   │→ │  Forge   │           │       Aegis          │  │
│  │ (Analyst)│  │(Developer│           │ (Incident Analyst)   │  │
│  └──────────┘  └──────────┘           └──────────────────────┘  │
│       ↓              ↓                         ↓                │
│  ┌──────────┐  ┌──────────┐           Mattermost + Elastic     │
│  │ Sentinel │→ │   HITL   │→ Scribe    + Knowledge Service      │
│  │ (Review) │  │ (Merge)  │  (Docs)                             │
│  └──────────┘  └──────────┘                                     │
├─────────────────────────────────────────────────────────────────┤
│  Integrations: Jira | Confluence | GitLab | Mattermost | ES     │
└─────────────────────────────────────────────────────────────────┘
```

## Agents

| Agent | Role | Scenario |
|-------|------|----------|
| **Atlas** | Reads Jira task + PRD, decomposes into subtasks (≤1 day), creates Git branch | Feature Development |
| **Forge** | Implements subtasks using Knowledge Service, commits to GitLab | Feature Development |
| **Sentinel** | Creates MR, performs automated code review | Feature Development |
| **Scribe** | Updates Confluence documentation after merge | Feature Development |
| **Sage** | RAG knowledge agent — retrieves patterns, solutions, and best practices from ChromaDB | Knowledge / Feature / Incident |
| **Aegis** | Monitors Disaster channel, analyzes logs/traces, reports to Tech Lead | Incident Response |

## Branch Naming Convention

```
Feature/[task-key]-[short-description]
Example: Feature/ven-100-create-api-for-contract
```

## Quick Start

### 1. Install dependencies

```bash
cd AgentFramework
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e .
```

### 2. Configure environment

```bash
copy .env.example .env
# Edit .env with your on-premise service URLs and credentials
# Set USE_MOCK_INTEGRATIONS=true for local development without real services
```

### 3. Run the server

```bash
# Recommended (from project root)
python run_server.py

# Or explicitly:
uvicorn main:app --app-dir src --reload --host 127.0.0.1 --port 8080
```

Open:
- **Dashboard**: http://127.0.0.1:8080/
- **API Docs**: http://127.0.0.1:8080/docs
- **Health check**: http://127.0.0.1:8080/health

## API Endpoints

### Scenario 1 - Feature Development

```bash
# Start full pipeline (Atlas → Forge → Sentinel → HITL pause)
POST /api/v1/workflows/feature-development
{
  "task_key": "VEN-100",
  "subtask_index": 0,
  "tech_lead_email": "tech-lead@company.local"
}

# Approve merge (HITL) → triggers Scribe
POST /api/v1/hitl/{checkpoint_id}/resolve
{
  "action": "approve",
  "resolved_by": "tech-lead@company.local"
}
```

### Scenario 2 - Incident Analysis

```bash
POST /api/v1/workflows/incident-analysis
{
  "channel_id": null,
  "tech_lead_email": "tech-lead@company.local"
}
```

### Monitoring

```bash
GET  /api/v1/runs                    # List all agent runs
GET  /api/v1/runs/{run_id}/events    # Agent event timeline
GET  /api/v1/hitl/pending            # Pending HITL checkpoints
GET  /api/v1/dashboard/stats         # Dashboard statistics
GET  /api/v1/integrations/health     # Jira + GitLab connectivity
WS   /ws/dashboard                   # Real-time dashboard updates
```

## Project Structure (Vertical Slices)

```
src/
├── core/                          # Config, logging
├── shared/                        # Cross-cutting concerns
│   ├── integrations/              # Jira, GitLab, Confluence, etc.
│   ├── models/                    # Domain models
│   ├── persistence/               # SQLite repository
│   └── llm/                         # LLM factory
├── slices/
│   ├── feature_pipeline/          # Scenario 1
│   │   ├── agents/                # Atlas, Forge, Sentinel, Scribe
│   │   ├── models/
│   │   └── orchestrator.py
│   └── incident_response/         # Scenario 2
│       ├── agents/                # Aegis
│       ├── models/
│       └── orchestrator.py
├── api/                           # FastAPI routes
├── dashboard/                     # Web dashboard
└── main.py
```

## HITL Flow

1. Pipeline runs automatically through Atlas → Forge → Sentinel
2. Pipeline **pauses** at `final_merge_approval` checkpoint
3. Tech Lead reviews MR and automated code review in dashboard
4. On **approve**: Scribe updates Confluence, pipeline completes
5. On **reject**: Pipeline cancelled

## Integration Configuration

### Real Jira + GitLab (recommended setup)

You can connect Jira and GitLab independently while keeping other services mocked:

```env
USE_MOCK_INTEGRATIONS=true
USE_MOCK_JIRA=false
USE_MOCK_GITLAB=false

JIRA_URL=https://jira.company.local
JIRA_USERNAME=your.username
JIRA_API_TOKEN=your-password-or-pat
JIRA_VERIFY_SSL=false

GITLAB_URL=https://gitlab.company.local
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
GITLAB_PROJECT_PATH=your-group/your-repo
GITLAB_DEFAULT_BRANCH=develop
GITLAB_VERIFY_SSL=false
```

### Verify connectivity

```bash
# CLI
python scripts/test_integrations.py

# API
GET /api/v1/integrations/health
GET /api/v1/integrations/jira/issues/VEN-100
GET /api/v1/integrations/gitlab/project
GET /api/v1/integrations/gitlab/branches?search=Feature
```

### Knowledge Service (Sage RAG + ChromaDB)

Local vector store using **ChromaDB** (open-source, persistent at `./data/chroma`).

Collections:
- `code_patterns` — Code Patterns Repository
- `solutions` — Solution Database
- `error_patterns` — Error Patterns
- `best_practices` — Best Practices
- `historical_context` — Historical Context of similar tasks

```bash
# Stats
GET /api/v1/knowledge/stats

# Query (Sage RAG: retrieval + LLM synthesis)
POST /api/v1/knowledge/query
{"question": "How to implement CQRS command handler?", "top_k": 5, "synthesize": true}

# Ingest document
POST /api/v1/knowledge/ingest
{"collection": "code_patterns", "title": "My Pattern", "content": "...", "tags": ["cqrs"]}

# List / delete
GET /api/v1/knowledge/documents
DELETE /api/v1/knowledge/documents/{doc_id}
```

Dashboard panel **Sage Knowledge Base** supports query, ingest, stats, and document management.

Env:
```env
USE_LOCAL_KNOWLEDGE=true
USE_MOCK_KNOWLEDGE=false
KNOWLEDGE_CHROMA_PATH=./data/chroma
EMBEDDING_MODEL=text-embedding-3-small
```

Embeddings use OpenAI-compatible API when `LLM_API_KEY` is valid; otherwise Chroma's built-in local model (`all-MiniLM-L6-v2`).

### Jira on-premise notes

| Item | Details |
|------|---------|
| Auth | `JIRA_AUTH_TYPE=pat` with `JIRA_API_TOKEN` (Bearer PAT, no username required) |
| Auth (Cloud) | `JIRA_AUTH_TYPE=basic` with `JIRA_USERNAME` + `JIRA_API_TOKEN` |
| SSL | Set `JIRA_VERIFY_SSL=false` for internal CA / self-signed certs |
| Sub-tasks | Auto-detected; override with `JIRA_SUBTASK_ISSUE_TYPE=Sub-task` |
| PRD source | Attachment (filename contains `prd`), markdown attachment, or `JIRA_PRD_FIELD_ID` |
| ADF descriptions | Automatically converted to plain text (Jira 8.14+) |

Required Jira permissions for the service account:
- Browse projects
- Create issues (sub-tasks)
- Edit issues
- Add attachments (read)

### GitLab on-premise notes

| Item | Details |
|------|---------|
| Token | Personal Access Token or Project Access Token with `api` scope |
| Project | Use `GITLAB_PROJECT_PATH=group/repo` **or** `GITLAB_PROJECT_ID=123` |
| SSL | Set `GITLAB_VERIFY_SSL=false` for internal CA / self-signed certs |
| Branch | Created from `GITLAB_DEFAULT_BRANCH` (usually `develop`) |
| Commits | Uses `create` or `update` action per file automatically |

Required GitLab role: **Developer** or higher on the target project.

### All integrations (full production)

Set `USE_MOCK_INTEGRATIONS=false` and configure all services:

| Service | Env Variables |
|---------|--------------|
| Jira | `JIRA_URL`, `JIRA_USERNAME`, `JIRA_API_TOKEN`, `JIRA_VERIFY_SSL` |
| GitLab | `GITLAB_URL`, `GITLAB_TOKEN`, `GITLAB_PROJECT_PATH`, `GITLAB_VERIFY_SSL` |
| Confluence | `CONFLUENCE_URL`, `CONFLUENCE_USERNAME`, `CONFLUENCE_API_TOKEN` |
| Mattermost | `MATTERMOST_URL`, `MATTERMOST_TOKEN`, `MATTERMOST_DISASTER_CHANNEL_ID` |
| Elasticsearch | `ELASTICSEARCH_URL`, `ELASTICSEARCH_USERNAME`, `ELASTICSEARCH_PASSWORD` |
| Knowledge (local RAG) | `USE_LOCAL_KNOWLEDGE`, `KNOWLEDGE_CHROMA_PATH`, `EMBEDDING_MODEL`, `USE_MOCK_KNOWLEDGE` |
| Knowledge (external) | `KNOWLEDGE_SERVICE_URL`, `KNOWLEDGE_SERVICE_API_KEY` (when `USE_LOCAL_KNOWLEDGE=false`) |
| LLM | `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` |

## Tech Stack Alignment

Built to support your .NET 8 DDD/CQRS architecture:
- Agents understand MediatR, FluentValidation, vertical slices
- Knowledge Service (Sage + ChromaDB) provides domain/architecture context via RAG
- Branch naming follows your `Feature/[task]/[description]` convention
- Mock data includes Contract API and Payment incident examples
