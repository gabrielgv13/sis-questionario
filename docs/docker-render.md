# Docker, Docker Hub e Render

## Variantes e execução local

As receitas estão em `images/clean-image` e `images/test-image`. A primeira prepara
um banco novo sem questionários; a segunda acrescenta apenas o Questionário de
Perfil, ativo e com devolutiva. Nenhuma insere respostas fictícias ou apaga dados.
O estado fica no PostgreSQL, não na imagem. Conectar uma imagem clean a um banco
existente não o esvazia.

Requisitos locais: Docker Engine/Desktop com Compose v2 e containers Linux.
Copie `.env.docker.example` para `.env.docker.local`, preserve o `.env` existente
e substitua os três valores de exemplo por segredos próprios. Gere SECRET_KEY
com `uv run python -c "import secrets; print(secrets.token_hex(32))"`.

```powershell
docker compose --env-file .env.docker.local --profile clean up --build -d
# http://localhost:5000 e http://localhost:5000/admin

docker compose --env-file .env.docker.local --profile test up --build -d
# http://localhost:5001 e http://localhost:5001/admin
```

Cada perfil tem sua rede, banco e volume de segredos. PostgreSQL não publica porta
no host. `prepare-*` espera o healthcheck do banco e precisa terminar com sucesso
antes do web. O banco já é criado pelo container PostgreSQL; o provisionador cria
a role restrita, migra as tabelas e, no perfil test, cadastra o Perfil.

```powershell
docker compose --env-file .env.docker.local --profile clean logs prepare-clean web-clean
docker compose --env-file .env.docker.local --profile test logs prepare-test web-test
docker compose --env-file .env.docker.local --profile clean --profile test down
```

O comando `down` acima preserva volumes. Não acrescente `--volumes` para reiniciar.
A senha de `sis_app` é gerada automaticamente no primeiro provisionamento, guardada
com modo 0600 em volume próprio e montada somente para leitura pelo web. Não remova
esse volume enquanto mantiver o banco. Caso contrário, a senha nova não autenticará
na role existente. Para rotação, faça backup, altere explicitamente a senha PostgreSQL
com uma conta autorizada e atualize o segredo correspondente de forma coordenada.
Alterar POSTGRES_PASSWORD no arquivo não altera a senha de um banco já inicializado.

ADMIN_PASSWORD define a senha do login web, independente do PostgreSQL. A factory
gera seu hash em memória. Se ADMIN_PASSWORD_HASH também estiver definido, o hash
tem prioridade. SECRET_KEY precisa permanecer estável entre workers e reinícios.
As credenciais de preparação não são fornecidas aos containers web pelo Compose.

## Build e publicação no Docker Hub

Destino solicitado: `gabrielgventura/sis-questionario`. Tags propostas: `clean`
e `test`, além de tags versionadas para permitir rollback. Faça login localmente
com uma conta que tenha permissão de push nesse repositório; não grave tokens
no código ou no arquivo Compose.

Publicação validada em 03/11/2026, commit
`a5ab37cb09e35ada115d092fda18386d762d4359`. Ambas as imagens Linux/amd64 foram
construídas, iniciadas e testadas; **60 testes passaram sem skips**, mais os
checks de banco inicial, healthcheck e reinício. [Workflow concluído](https://github.com/gabrielgv13/sis-questionario/actions/runs/41687039017).

| Tag publicada | Digest |
| --- | --- |
| `gabrielgventura/sis-questionario:clean` | `sha256:e919931cdada1d7943e527d8793e4b9de097644b7355c4a37a114196fec4c344` |
| `gabrielgventura/sis-questionario:test` | `sha256:0f9c336425925c6ee9147991eef0fefce1f765dd925725eecc4f929729c3ba4f` |

As tags `clean-a5ab37cb09e35ada115d092fda18386d762d4359` e
`test-a5ab37cb09e35ada115d092fda18386d762d4359` apontam para os mesmos digests.

```powershell
docker login --username gabrielgventura
docker build --platform linux/amd64 -f images/clean-image/Dockerfile -t gabrielgventura/sis-questionario:clean .
docker build --platform linux/amd64 -f images/test-image/Dockerfile -t gabrielgventura/sis-questionario:test .
docker push gabrielgventura/sis-questionario:clean
docker push gabrielgventura/sis-questionario:test
```

Para publicar sem Docker instalado na máquina, o workflow
`.github/workflows/docker-publish.yml` executa em GitHub Actions. Cadastre o secret
`DOCKERHUB_TOKEN` com um token Docker Hub autorizado a gravar nesse repositório.
O login usa `gabrielgventura`. Um push em `feat/docker-render` ou `main` valida os
dois perfis e a suíte antes de publicar `clean`, `test` e as respectivas tags
versionadas `clean-<commit>` / `test-<commit>`. Também há execução manual pela aba
Actions quando o workflow estiver na branch padrão. Nenhum token é embutido na imagem.

As imagens executam como UID 10001, com Gunicorn em `0.0.0.0:$PORT` (10000 por
padrão). Não incluem PostgreSQL: use um serviço de banco persistente separado.
O comando padrão serve o web; o provisionamento é um comando separado:
`/app/.venv/bin/sis-questionario-provision`.

## Render com uma imagem publicada

No Render, escolha **New Web Service → Existing Image** e informe
`docker.io/gabrielgventura/sis-questionario:clean` ou a tag `test`. Para imagem
privada, configure também a credencial de leitura do registry no painel.
Crie um Render Postgres na mesma região, anote o nome do subdomínio atribuído
e configure estas variáveis no serviço:

| Variável | Valor |
| --- | --- |
| ADMIN_PASSWORD | Senha própria para o painel web |
| SECRET_KEY | Segredo aleatório estável, no mínimo 32 caracteres |
| DB_HOST / DB_PORT / DB_NAME | Host interno, porta e banco do Render Postgres |
| DB_USER | `sis_app` (diferente do proprietário) |
| DB_PASSWORD | Segredo aleatório estável, no mínimo 24 caracteres |
| DB_ADMIN_USER / DB_ADMIN_PASSWORD | Conta proprietária, usada pelo pré-deploy |
| DB_SSLMODE | `require` |
| COOKIE_SECURE / TRUST_PROXY | `1` em ambos |

Não defina DB_PASSWORD_FILE no Render. Configure **Pre-Deploy Command** como
`/app/.venv/bin/sis-questionario-provision` e **Health Check Path** como `/healthz`.
Mantenha o comando Docker padrão. O pré-deploy exige um plano pago e executa em
uma instância separada; uma falha impede o deploy. O nome disponível do serviço
determina `https://<nome>.onrender.com`.

O pré-deploy e o web compartilham a configuração do serviço no Render. O entrypoint
remove `DB_ADMIN_*` do ambiente antes de executar Gunicorn; os segredos continuam
acessíveis a operadores pelo painel/shell do serviço. Isso é uma limitação frente
ao escopo separado de segredos desejado no plano. Para isolamento completo,
execute o provisionador em um job externo confiável com acesso ao banco, retire
as variáveis administrativas do serviço web e remova seu Pre-Deploy Command.
Execute esse job antes de cada atualização que exija migrações.

A conta preparadora precisa de CREATEROLE e propriedade dos objetos. O código
recusa usar a mesma conta como aplicação. Se o provedor não permitir criar roles,
o provisionamento falha e deve ser resolvido com o provedor; não há fallback
para servir usando a conta proprietária.

Para deploy a partir do código, `render.yaml` oferece a mesma configuração com
imagem clean, Postgres dedicado, senhas aleatórias para a aplicação e conexão
externa do banco desabilitada. Para a variante Perfil, altere dockerfilePath
para `./images/test-image/Dockerfile` antes de criar a infraestrutura. Esse
Blueprint contém planos pagos; confira o custo no painel antes de aplicá-lo.

Imagens de registry exigem redeploy manual quando a tag é atualizada. Para garantir
reprodutibilidade, prefira uma tag versionada ou o digest publicado. Antes de
atualizar, faça backup do Postgres. Reverta o serviço para o digest anterior apenas
se o esquema continuar compatível; restaurar dados de backup deve ser planejado
separadamente. Não remova banco/volumes para realizar rollback.

## Concorrência e pools

As imagens usam Gunicorn com `worker_class=gevent`, sem preload da aplicação.
O worker aplica monkey patch antes de importar Psycopg e `psycopg_pool`;
`post_worker_init` abre o pool após o fork e verifica o patch de select,
threading e queue. `worker_exit` fecha o pool; a saída normal também tem um
fallback atexit. SIGKILL não executa hooks, mas o sistema fecha os sockets.
Não use `--preload` nem importe bibliotecas de banco em configuração do master.
Os comandos CLI e o provisionamento continuam abrindo conexões diretas.

`conectar()` retorna o contexto do pool no web: sucesso confirma a transação;
exceção desfaz; a conexão sempre volta ao pool, inclusive após falha de commit.
Conexões quebradas são descartadas e há verificação antes do empréstimo.
O pool pertence ao processo, nunca à requisição; não o feche em teardown do Flask.

| Variável | Padrão | Efeito |
| --- | --- | --- |
| `WEB_WORKERS` | calculado | Override inteiro positivo |
| `WEB_CPU_CORES` | ausente | Limite adicional positivo, quando o provedor não expõe a quota |
| `DB_POOL_MIN_SIZE` | `0` | Conexões iniciais por worker, abertas sob demanda |
| `DB_POOL_MAX_SIZE` | `2` | Máximo de conexões por worker |
| `DB_POOL_TIMEOUT` | `5` | Segundos máximos aguardando conexão |
| `DB_POOL_MAX_WAITING` | `32` | Máximo de clientes na fila por worker |

O cálculo é `max(1, floor(CPUs efetivas + 1))`. CPUs efetivas são o menor valor
entre afinidade, quotas cgroup v2 (`cpu.max`), v1 (`cpu.cfs_*`), ancestrais
visíveis e `WEB_CPU_CORES`, quando definido. Sem quota visível, usa afinidade
(ou contagem disponível do Python). Não usa automaticamente os cores físicos
do host quando há uma quota visível. Em montagens cgroup não convencionais,
informe `WEB_CPU_CORES` ou `WEB_WORKERS` explicitamente.

Para a hospedagem Render Free descrita neste projeto (0,1 CPU e 512 MB),
`floor(0.1 + 1) = 1`: um worker, máximo de duas conexões. Configure
`WEB_CPU_CORES=0.1` no painel se a quota não estiver exposta no contêiner.
Uma CPU resulta em dois workers. Mais processos não fornecem mais CPU.
O `render.yaml` continua descrevendo web Starter e PostgreSQL pagos; ele não
representa a implantação Free e não foi convertido para Free.

Orçamento de banco: `réplicas × WEB_WORKERS × DB_POOL_MAX_SIZE`, mais conexões
de migração, administração e outros clientes. Durante deploys pode haver
instâncias antigas e novas simultaneamente. Reserve essa margem no limite do
PostgreSQL. Há 64 conexões HTTP simultâneas por worker; isso não representa
64 consultas simultâneas nem uma capacidade comprovada de usuários.

Python 3.14 convencional (com GIL), Psycopg 3.3.6, psycopg-pool 3.3.3 e gevent
26.9.0 estão no lockfile. O gevent oferece suporte ao Python 3.14; o Psycopg
3 suporta gevent nativamente quando select é patchado. O patch antecipado de
threading e queue também torna cooperativas as esperas do pool. Não é necessário
psycogreen. Gunicorn/gevent são dependências do runtime Unix; o desenvolvimento
Windows e os comandos CLI não dependem do gevent.

Fontes: [compatibilidade gevent](https://www.gevent.org/install.html),
[Psycopg e gevent](https://www.psycopg.org/psycopg3/docs/advanced/async.html#gevent-support),
[transações no pool](https://www.psycopg.org/psycopg3/docs/advanced/pool.html).

A suíte inclui reutilização de conexão, commit, rollback, erro SQL, esgotamento,
quotas fracionárias, ciclo de vida e override. Em Linux com `TEST_DATABASE_URL`,
um subprocesso aplica o patch antes dos imports e verifica que `pg_sleep` e a
espera de pool não bloqueiam outros greenlets. O workflow `python-tests.yml`
executa a suíte com Python 3.14 e PostgreSQL 18. Isso não substitui um teste de
carga. PDFs continuam síncronos e usam CPU no worker; relatórios ainda executam
agregações por pergunta. Não há capacidade concorrente medida.

## Segurança e validação

A role do runtime tem SELECT/INSERT nas seis tabelas, USAGE em suas sequências e
UPDATE somente em `questionarios(exibir_resultado, documento)`. Não é proprietária
e não recebe DELETE, TRUNCATE, criação de roles ou DDL. A role atende também à
importação administrativa; ela não representa uma identidade individual por
participante. SQL parametrizado é a prevenção de SQL injection; permissões
restritas limitam o impacto, mas não substituem essa prevenção.

O provisionador é exclusivo de banco dedicado: remove CREATE de PUBLIC no schema
public e reaplica grants idempotentes. Não use contra um banco compartilhado sem
avaliar esse efeito. Credenciais existentes não são rotacionadas automaticamente.
A conferência de senha depende de autenticação por senha no PostgreSQL; servidores
configurados como `trust` não verificam a senha, inclusive em testes locais.

Valide o build e os dois perfis, conclua um envio, reinicie e confira sua persistência.
No Render, confira HTTPS, login, cookies Secure e `/healthz`. Para a suíte Python,
use `TEST_DATABASE_URL` em servidor de teste isolado, com CREATEDB/CREATEROLE para
os novos testes de provisionamento. Eles criam e removem bancos e roles descartáveis.
Nunca direcione a suíte a uma instalação de produção.

Fontes: [Docker no Render](https://render.com/docs/docker),
[imagens de registry](https://render.com/docs/deploying-an-image),
[pré-deploy](https://render.com/docs/deploys#pre-deploy-command),
[Web Services](https://render.com/docs/web-services) e
[Blueprint](https://render.com/docs/blueprint-spec).
