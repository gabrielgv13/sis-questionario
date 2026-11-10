**sis-questionario is a FastAPI monolith:** one Python application serves questionnaire pages, handles submissions, provides the admin dashboard, and accesses PostgreSQL directly through Psycopg 3 async connections.

```text
Browser
  │ HTML forms + JavaScript requests
  ▼
FastAPI routes ── Jinja templates + CSS/JavaScript
  │
  ├── Questionnaire validation and profile classification
  ├── Admin analysis and PDF/CSV/JSON exports
  │
  ▼
Database helpers → connection pool → PostgreSQL
```

The main source files under `src/sis_questionario/` are:

| File | Responsibility |
|---|---|
| `app.py` | FastAPI factory, participant routes, sessions, browser identification, health check |
| `admin.py` | Admin login, questionnaire management, analysis, export endpoints |
| `bd_exec.py` / `bd_async.py` | Synchronous CLI queries and async web transactions; no ORM |
| `async_pool.py` | Per-application async PostgreSQL pool managed by FastAPI lifespan |
| `server.py` | Uvicorn launcher and process/proxy configuration |
| `perfis.py` / `algoritmo_json.py` | Classification and validation of imported scoring rules |
| `questionario_json.py` | Validates questionnaire JSON imports |
| `exportacao.py` | Generates JSON, CSV, and ReportLab PDF reports |
| `config.py` | Loads `.env` and database connection settings |
| `setup_db.py` / `banco.sql` | Creates and updates the database structure |
| `provision.py` | Deployment provisioning and restricted database account |
| `templates/` / `static/` | Server-rendered Jinja pages, CSS, and JavaScript |

The database has six core tables:

- `questionarios` → `perguntas` → `opcoes`: questionnaire definitions.
- `alunos` → `envios` → `respostas`: participants, submissions, and answers.

JSONB columns also store questionnaire documents and classification results. Submission and answer writes happen in one transaction: failure rolls everything back.

A participant enters their information, selects a questionnaire, answers the entire form, and submits once. The server validates the answers, optionally calculates a profile, and saves the submission. A browser UUID cookie plus a database uniqueness constraint prevents repeat submissions for the same questionnaire. Starlette sessions use signed cookies. Algorithm JSON files are required when importing a questionnaire that declares an algorithm; rules are validated and stored with that questionnaire.

There are two execution paths:

| Mode | Runtime |
|---|---|
| Local `uv run` | Uvicorn with async PostgreSQL connections and a pool per process |
| Container deployment | Uvicorn with explicit worker count, separate provisioner and a pool per worker |

Dependencies are managed through `pyproject.toml` and `uv.lock`, targeting Python 3.14. Docker provides clean and Profile-seeded variants; Compose runs them with PostgreSQL locally. `render.yaml` describes **paid Starter web and paid PostgreSQL**, independently of your actual Free deployment.

Report generation and templates run in threads; database work is async and releases its connection before report generation. There is currently no background job queue or measured concurrent-user capacity. Docker validation uses a separate target with development dependencies; the runtime image contains only the installed application and its dependencies.
