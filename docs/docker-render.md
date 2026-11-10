# Docker, Compose e publicação

As imagens executam FastAPI com Uvicorn e pool assíncrono do Psycopg 3.
O provisionamento continua separado do servidor web. Não há Gunicorn, gevent
ou monkey patch no runtime.

## Variantes e volumes

| Variante | Banco novo | Banco existente |
|---|---|---|
| `clean` | Tabelas vazias | Aplica migrações e preserva os dados |
| `test` | Questionário de Perfil com regras, sem respostas fictícias | Preserva dados e cadastra o Perfil de forma idempotente |

Cada perfil Compose mantém sua rede, PostgreSQL 18 e volumes de dados e segredos.
Os nomes continuam `clean-db`, `test-db`, `clean-secrets` e `test-secrets`.
Mantenha também o mesmo nome de projeto Compose ao atualizar um stack existente:
um nome diferente seleciona outro conjunto de volumes.

O PostgreSQL não publica portas no host. O provisionador espera o banco saudável,
cria/verifica a conta restrita, aplica `banco.sql`, incluindo `regras_algoritmo`,
e só então libera a inicialização do web. O processo web nunca executa DDL.
Não é necessário conceder UPDATE nas regras: a importação salva questionário e
algoritmo juntos por INSERT, e duplicatas não sobrescrevem dados.

## Executar localmente

Requisitos: Docker Engine/Desktop com Compose v2, BuildKit e containers Linux.
Copie `.env.docker.example` para `.env.docker.local` e preencha os segredos.
Preserve o `.env` já usado na execução local do Python.

```powershell
docker compose --env-file .env.docker.local --profile clean config --quiet
docker compose --env-file .env.docker.local --profile clean up --build -d --wait
# http://127.0.0.1:5000/admin

docker compose --env-file .env.docker.local --profile test up --build -d --wait
# http://127.0.0.1:5001/admin
```

O runtime usa UID/GID 10001, sistema de arquivos somente leitura no Compose,
`/tmp` temporário, capabilities removidas e segredo do banco montado somente
para leitura. A senha `sis_app` é gerada na primeira preparação e preservada no
volume de segredos, com modo 0600. Não remova esse volume mantendo o banco.
Alterar `POSTGRES_PASSWORD` não altera a senha de um banco já inicializado.

O login aceita `ADMIN_PASSWORD` ou `ADMIN_PASSWORD_HASH`; o hash tem prioridade.
No segundo caso, deixe a senha vazia no arquivo de ambiente. `SECRET_KEY` deve
ser estável e ter pelo menos 32 caracteres. O Compose não fornece `DB_ADMIN_*`
ao web, e o entrypoint remove essas variáveis caso existam em outro ambiente.

## Servidor, proxy e conexões

O entrypoint valida os segredos e usa exec para iniciar
`python -m sis_questionario.server`. O padrão interno é `0.0.0.0:10000`.
Reload é recusado nos containers. Logs seguem para stdout/stderr.

| Variável | Padrão Compose | Uso |
|---|---|---|
| `WEB_WORKERS` | `1` | Processos Uvicorn |
| `WEB_SHUTDOWN_TIMEOUT` | `30` | Segundos para concluir requisições na parada |
| `WEB_STOP_GRACE_PERIOD` | `45s` | Prazo do Docker antes de forçar a parada |
| `COOKIE_SECURE` | `0` | Use `1` em acesso HTTPS |
| `TRUST_PROXY` | `0` | Use `1` somente atrás de proxy confiável |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1,::1` | IPs/redes autorizados a encaminhar headers |
| `DB_POOL_MIN_SIZE` | `0` | Conexões mínimas por processo |
| `DB_POOL_MAX_SIZE` | `2` | Conexões máximas por processo |
| `DB_POOL_TIMEOUT` | `5` | Espera máxima por conexão, em segundos |
| `DB_POOL_MAX_WAITING` | `32` | Limite da fila por processo |

O lifespan abre e fecha um `AsyncConnectionPool` por processo. Uma operação
confirma sua transação em sucesso e faz rollback em falha. Conexões retornam
ao pool antes de gerar relatórios. CLI e provisionamento usam conexões síncronas
diretas. O healthcheck `/healthz` verifica banco e esquema, inclusive com mínimo
zero; falhas retornam 503 sem detalhes internos.

Mantenha `WEB_STOP_GRACE_PERIOD` maior que `WEB_SHUTDOWN_TIMEOUT`, com margem
para fechar o pool. Mais workers exigem mais memória e conexões; o orçamento é
`réplicas × workers × DB_POOL_MAX_SIZE`, mais migração e administração. Não há
cálculo automático de workers por CPU nem suporte a `WEB_CPU_CORES`.

Para HTTP local, use `COOKIE_SECURE=0` e `TRUST_PROXY=0`. Com proxy HTTPS,
configure `COOKIE_SECURE=1`, `TRUST_PROXY=1` e as origens reais do proxy em
`FORWARDED_ALLOW_IPS`. Não use confiança irrestrita em redes que permitam
acesso direto de clientes não confiáveis ao servidor.

## Build de produção e validação

Os dois Dockerfiles têm os targets `build`, `validation` e `runtime`.
O último é o padrão. O build usa uv 0.13.5 e o lockfile congelado; dependências
são instaladas antes de copiar o código para aproveitar o cache. O runtime
recebe somente o ambiente Python instalado, com pacote não editável e seus
templates, arquivos estáticos, SQL e regras. Não recebe uv, testes, documentos,
HTTPX, PyYAML ou credenciais de build.

O target `validation` contém os testes, documentos e dependências de
desenvolvimento em uma imagem separada. Execute-o somente contra um banco
descartável: a suíte cria schemas, bancos e roles temporários.

```powershell
docker compose --env-file .env.docker.local -f compose.yaml -f compose.validation.yaml --profile clean --profile validation build validate
docker compose --env-file .env.docker.local -f compose.yaml -f compose.validation.yaml --profile clean --profile validation run --rm validate
node tests/test_import_ui.cjs
```

O launcher de validação monta o DSN escapando senhas com caracteres especiais.
O diretório de trabalho `/app` contém os caminhos relativos usados nos testes.
Os testes JavaScript executam fora do runtime; Node.js não integra as imagens.

## Atualizar um stack existente

Faça backup do PostgreSQL e preserve o arquivo de ambiente, o nome do projeto
e os volumes. Construa as novas imagens; pare o web antes de migrar; execute
os provisionadores novamente e recrie o web:

```powershell
docker compose --env-file .env.docker.local --profile clean --profile test build --pull
docker compose --env-file .env.docker.local --profile clean --profile test stop web-clean web-test
docker compose --env-file .env.docker.local --profile clean run --rm prepare-clean
docker compose --env-file .env.docker.local --profile test run --rm prepare-test
docker compose --env-file .env.docker.local --profile clean --profile test up -d --wait
```

Use somente os perfis já existentes na sua instalação. A migração adiciona as
regras de algoritmo sem apagar envios nem alterar senhas. Após atualizar,
verifique login, importação dos dois JSONs, resultado do participante e
exportação. Questionários legados continuam compatíveis conforme
[o formato de importação](formato-questionario.md).

`docker compose down` preserva os volumes. Não use `down --volumes` para
atualização ou rollback.

## CI e publicação

`.github/workflows/docker-publish.yml` valida pull requests e pushes nas branches
configuradas. Constrói ambas as variantes e o target de testes, confere seus
bancos iniciais, executa a suíte no PostgreSQL com autenticação por senha e
verifica o fluxo HTTP completo. Os checks incluem importação de regras,
exportações, sessões preservadas após reprovisionamento/recriação, dois workers,
parada graciosa e recuperação após indisponibilidade do banco.

O script `tests/docker_stack_check.py` usa um stack descartável e salva cookies
de teste em `.uv-cache/stack-state.json`, ignorado pelo Git. Não o execute contra
uma instalação de produção.

Publicar exige execução manual em `main` com `publish=true` e o secret
`DOCKERHUB_TOKEN`. O workflow publica somente após todos os testes, usando as
mesmas imagens runtime testadas. São mantidas as tags `clean`, `test`,
`clean-<commit>` e `test-<commit>` em `gabrielgventura/sis-questionario`.
Uma execução comum, inclusive manual com o padrão `publish=false`, não publica.

As imagens históricas registradas em 03/11/2026, commit
`a5ab37cb09e35ada115d092fda18386d762d4359`, antecedem esta migração ASGI.
O [workflow histórico](https://github.com/gabrielgv13/sis-questionario/actions/runs/41687039017)
não valida as imagens desta versão. Os novos builds precisam passar pelo CI.

Para voltar a uma tag compatível, configure `IMAGE_SUFFIX=-<commit>` no arquivo
de ambiente, execute `docker compose ... pull` e depois `up -d --no-build --wait`.
Confirme a compatibilidade do esquema antes de voltar a uma versão antiga;
restaurar backup é uma operação separada. Não remova os volumes.

## Render

O `render.yaml` mantém os planos, a região e o PostgreSQL existentes. O entrypoint
da nova imagem já inicia Uvicorn; o pré-deploy permanece
`/app/.venv/bin/sis-questionario-provision` e o healthcheck permanece `/healthz`.
Foram explicitados um worker e o prazo de encerramento. Configure
`FORWARDED_ALLOW_IPS` com as origens confiáveis do proxy do ambiente.

Em imagem de registry, selecione a tag imutável ou digest validado e faça redeploy
explicitamente. Não há publicação nem implantação automática como parte de uma
alteração local. Os segredos administrativos do pré-deploy no Render continuam
compartilhando a configuração do serviço: o entrypoint os remove antes de servir,
mas operadores ainda podem acessá-los no painel. Para isolamento completo, use
provisionamento externo e retire essas variáveis do serviço web.

Referências: [builds multi-stage](https://docs.docker.com/build/building/multi-stage/),
[ordem dos serviços Compose](https://docs.docker.com/compose/how-tos/startup-order/),
[Uvicorn em Docker](https://uvicorn.dev/deployment/docker/).
