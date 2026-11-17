# FastAPI, Uvicorn e PostgreSQL assíncrono

A aplicação web usa FastAPI com Uvicorn e `psycopg_pool.AsyncConnectionPool`.
As rotas mantêm URLs, formulários, validação, CSRF, downloads e proteção contra
respostas duplicadas da aplicação anterior.

## Executar localmente

```powershell
uv sync
uv run sis-questionario
```

O comando prepara o banco e inicia o Uvicorn em `http://127.0.0.1:5000`.
Para cadastrar o questionário de Perfil antes de iniciar, use
`uv run sis-questionario-perfil`. Preparação e cadastro ocorrem uma vez,
antes de abrir os workers, usando as ferramentas síncronas existentes.

Para servir um banco já preparado, sem executar setup:

```powershell
uv run python -m sis_questionario.server
```

Esse launcher configura um `SelectorEventLoop` no Windows, necessário ao Psycopg
assíncrono. Use-o também para reload ou múltiplos workers. Ao chamar Uvicorn
diretamente, especifique a mesma factory de loop:

```powershell
uv run uvicorn sis_questionario.app:create_app --factory --loop sis_questionario.server:loop_factory --host 127.0.0.1 --port 5000
```

As variáveis são carregadas do `.env`, sem substituir valores do ambiente:

| Variável | Padrão | Uso |
|---|---|---|
| `WEB_HOST` | `127.0.0.1` | Interface de escuta |
| `PORT` | `5000` | Porta HTTP |
| `WEB_WORKERS` | `1` | Processos Uvicorn |
| `WEB_RELOAD` | `0` | `1` ativa reload; exige um worker |
| `WEB_SHUTDOWN_TIMEOUT` | `30` | Segundos para encerramento gracioso |
| `TRUST_PROXY` | desativado | `1` habilita headers do proxy no Uvicorn |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1,::1` | Origens de proxy confiáveis |
| `COOKIE_SECURE` | desativado | `1` exige HTTPS para cookies de sessão |

Em acesso local HTTP, mantenha `COOKIE_SECURE=0`. Atrás de proxy HTTPS, configure
`COOKIE_SECURE=1`, `TRUST_PROXY=1` e as origens confiáveis do proxy. A aplicação
não interpreta mais `X-Forwarded-Proto` diretamente.

Múltiplos workers exigem `SECRET_KEY` estável com pelo menos 32 caracteres.
Cada processo e réplica mantém seu próprio pool; planeje o limite total como
`réplicas × WEB_WORKERS × DB_POOL_MAX_SIZE`, reservando conexões para manutenção.

## Banco e transações

`async_pool.py` cria um pool por instância no lifespan, com `open=False`,
`await pool.open()` e `await pool.close()` em `finally`. O pool não é global
nem compartilhado entre event loops ou processos.

`bd_async.py` recebe esse pool por uma dependência FastAPI. Cada operação usa
`async with pool.connection()`: sucesso confirma a transação; uma exceção
provoca rollback antes de devolver a conexão. O cadastro de envio e respostas
permanece atômico, e as análises mantêm `REPEATABLE READ READ ONLY`.
`bd_rules.py` compartilha validação e classificação com o código síncrono.

Os parâmetros `DB_POOL_MIN_SIZE`, `DB_POOL_MAX_SIZE`, `DB_POOL_TIMEOUT` e
`DB_POOL_MAX_WAITING` permanecem disponíveis, assim como a verificação de
conexões antes do uso. Com mínimo zero, iniciar o servidor não testa a conexão.
`/healthz` adquire uma conexão e consulta a tabela esperada, respondendo `503`
se o banco ou esquema estiver indisponível.

Esgotamento da fila/pool e falhas de conexão retornam `503` sem detalhes internos.
Consultas HTTP usam `await`; templates, hashing e geração de arquivos continuam
em threads. A conexão é liberada antes de gerar relatórios. Setup e
provisionamento continuam síncronos, sem `asyncio.run()` dentro de rotas.

As sessões usam cookies assinados do Starlette. Sessões Flask antigas exigem
novo login ou reinício do formulário; `id_dispositivo` continua compatível.

## Containers

As imagens clean e test usam o mesmo launcher Uvicorn, com binding interno
`0.0.0.0:10000`, reload desativado e provisionamento separado. Gunicorn, gevent
e o pool síncrono legado foram removidos. CLI e provisionamento continuam com
conexões síncronas diretas. Consulte [Docker e Compose](docker-render.md) para
builds, atualização dos volumes existentes e validação antes de publicar.

## Validação

```powershell
uv run python -m unittest discover -s tests -v
```

`TEST_DATABASE_URL` deve apontar para um banco descartável. A suíte de integração
cria schemas, bancos e roles temporários, exigindo as permissões correspondentes.
Sem essa variável, os testes PostgreSQL são ignorados. Os testes assíncronos usam
o loop compatível com Windows e cobrem commit, rollback, cancelamento,
esgotamento/recuperação do pool e o fluxo HTTP com conexões reais.

Os testes legados de rotas com transações síncronas não confirmadas usam um
adaptador exclusivo de testes; `test_async_database.py` exercita o repositório
assíncrono real. Os testes do servidor iniciam processos Uvicorn em portas
locais temporárias, incluindo múltiplos workers e reload.

Referências: [conexões assíncronas Psycopg](https://www.psycopg.org/psycopg3/docs/advanced/async.html),
[pool e lifespan FastAPI](https://www.psycopg.org/psycopg3/docs/advanced/pool.html),
[configuração Uvicorn](https://uvicorn.dev/settings/).
