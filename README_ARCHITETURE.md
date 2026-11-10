**sis-questionario is a Flask monolith:** one Python application serves questionnaire pages, handles submissions, provides the admin dashboard, and accesses PostgreSQL directly.

```text
Browser
  │ HTML forms + JavaScript requests
  ▼
Flask routes ── Jinja templates + CSS/JavaScript
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
| `app.py` | Flask factory, participant routes, sessions, browser identification, health check |
| `admin.py` | Admin login, questionnaire management, analysis, export endpoints |
| `bd_exec.py` | Parameterized SQL queries and transactional writes; no ORM |
| `database_pool.py` | Bounded PostgreSQL connection pools and cleanup |
| `perfis.py` | Profile classification using versioned weights in `perfil_v1.json` |
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

A participant enters their information, selects a questionnaire, answers the entire form, and submits once. The server validates the answers, optionally calculates a profile, and saves the submission. A browser UUID cookie plus a database uniqueness constraint prevents repeat submissions for the same questionnaire. Flask sessions use signed cookies.

There are two execution paths:

| Mode | Runtime |
|---|---|
| Local `uv run` | Flask development server with native threads and connection pooling |
| Container deployment | Gunicorn with gevent, CPU-aware worker count, and a separate pool per worker |

Dependencies are managed through `pyproject.toml` and `uv.lock`, targeting Python 3.14. Docker provides clean and Profile-seeded variants; Compose runs them with PostgreSQL locally. `render.yaml` describes **paid Starter web and paid PostgreSQL**, independently of your actual Free deployment.

Reports and PDF generation run synchronously in web requests. There is currently no background job queue or measured concurrent-user capacity.