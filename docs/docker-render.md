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
