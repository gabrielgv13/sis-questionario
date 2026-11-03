# Plano de Docker e hospedagem no Render

Data: 03/11/2026. Estado: planejamento; imagens e infraestrutura ainda não implementadas.

Atualização: implementação em `feat/docker-render`; consultar `docs/docker-render.md`
e a atualização em `CONTINUIDADE.md` para estado e validações. A publicação no
Docker Hub passa a usar GitHub Actions por solicitação do usuário. O texto abaixo
preserva o plano original para referência, incluindo critérios ainda dependentes
de execução em containers e de uma conta Render.

## Objetivo e referências do projeto

Entregar duas variantes Docker do Flask/PostgreSQL, com senha administrativa
configurável, provisionamento automático de uma conta PostgreSQL restrita e
publicação em um subdomínio `onrender.com`.

O `CONTINUIDADE.md` foi usado como registro de contexto, conferido com README,
`pyproject.toml`, `setup_db.py`, `app.py`, `bd_exec.py` e `banco.sql`.
Suas sugestões não ampliam o pedido atual. Este plano preserva `.env`, `docs/`
e os dados existentes. O estado Git estava sem alterações no início da análise.

## 1. Organização das imagens

Estrutura proposta, com contexto de build na raiz do repositório:

```text
images/
  clean-image/Dockerfile
  test-image/Dockerfile
  common/entrypoint.py
compose.yaml
.dockerignore
.env.docker.example
render.yaml
docs/docker-render.md
```

As pastas conterão receitas de build; imagens compiladas ficam no Docker local
ou em um registry, e não como arquivos binários no Git.

| Variante | Estado em um banco novo | Reinicialização |
| --- | --- | --- |
| clean-image | Estrutura pronta, sem questionários, participantes, envios ou respostas | Preserva todos os dados existentes |
| test-image | Questionário de Perfil ativo, 11 perguntas e 120 alternativas; sem participantes, envios ou respostas | Carga idempotente; preserva respostas e configurações |

O modo test-image significa questionário pronto para uso, sem dados fictícios.
Não executar `docs/popular_perfil.sql`. Nenhuma variante limpa um banco existente.
Usar bancos/volumes distintos para experimentar as duas variantes sem misturar dados.

Construir ambas com Python 3.14, instalação por `uv sync --frozen` e dependências
fixadas no lockfile. Acrescentar Gunicorn às dependências e atualizar `uv.lock`.
Compartilhar a lógica de execução para evitar divergências entre Dockerfiles.
Rodar como usuário Linux sem root; usar CSS já compilado, sem Node em runtime.
Excluir `.env`, `.git`, `.venv`, caches, dumps e credenciais do contexto Docker.
Não conectar ao banco nem embutir senhas durante o build.

## 2. Separar provisionamento e servidor web

Hoje os CLIs preparam o banco, mas não criam usuários. A factory Flask já permite
iniciar sem executar migrações. Implementar um comando específico de provisionamento:

1. Validar configuração e aguardar PostgreSQL com tentativas limitadas.
2. Conectar com credenciais de preparação e criar o banco apenas no ambiente local,
   se necessário. No Render, usar diretamente o banco já provisionado pelo serviço.
3. Serializar preparações concorrentes com lock PostgreSQL.
4. Aplicar as migrações idempotentes com a conta proprietária das tabelas.
5. Criar a role de aplicação se ausente e aplicar os privilégios mínimos.
6. Na variante test-image, carregar o Perfil idempotentemente usando a preparação.
7. Encerrar a conexão administrativa antes de iniciar o servidor.

O servidor deve executar apenas `sis_questionario.app:create_app()` pelo Gunicorn,
ligado em `0.0.0.0:$PORT`. Não usar o servidor de desenvolvimento Flask.
O processo web não deve receber credenciais administrativas. Em Compose, usar um
serviço de preparação separado; no Render, uma etapa de preparação ou job separado
com escopo próprio de segredos. Verificar disponibilidade dessa execução no plano
escolhido antes de finalizar o Blueprint.

## 3. Conta PostgreSQL automática

Criar por padrão uma role `sis_app` com senha forte gerada por `secrets`, sem
SUPERUSER, CREATEDB, CREATEROLE, REPLICATION, BYPASSRLS ou propriedade dos objetos.
Ela não deve herdar a role de preparação. Permitir nome configurável validado.

Para automação local, um serviço inicializador gera a senha se ausente e a grava
em arquivo de um volume de segredos compartilhado apenas com o app. O app lê esse
arquivo por `DB_PASSWORD_FILE`. Preservar o segredo em reinicializações; não gerar
ou trocar a senha a cada start. Permitir `DB_PASSWORD` explícita como alternativa,
sem gravar senhas no Git ou imprimir valores em logs.

No Render, gerar uma senha estável pelo mecanismo de segredos do Blueprint e
fornecê-la ao provisionador e ao app. O provisionador cria automaticamente a role
com essa senha. Não depender do disco efêmero do web service para persistir segredos.
Se uma role preexistente não corresponder à configuração, falhar com diagnóstico
sem senha; rotação deve ser uma operação explícita.

Privilégios iniciais da role compartilhada pelo runtime:

- CONNECT no banco e USAGE no schema da aplicação.
- SELECT nas seis tabelas para os fluxos existentes.
- INSERT nas seis tabelas: participação e importação administrativa de questionários.
- USAGE nas sequências necessárias aos INSERTs.
- UPDATE somente em `questionarios(exibir_resultado, documento)` para a devolutiva.
- Sem DELETE, TRUNCATE, CREATE de objetos ou alterações de estrutura.

Em um banco novo dedicado, retirar CREATE de PUBLIC no schema e verificar os
privilégios herdados; não modificar permissões de bancos compartilhados sem análise.
Reaplicar grants para objetos novos após cada migração, mantendo a propriedade
com o preparador. Usar `psycopg.sql.Identifier` para nomes dinâmicos e parâmetros
para valores quando suportados. Não montar comandos SQL com entradas HTTP.

Uma senha e uma conta restrita não impedem SQL injection por si sós: a prevenção
depende de consultas parametrizadas e validação. Preservar o padrão já observado
em `bd_exec.py` e testar entradas maliciosas como texto literal. As permissões
reduzem o impacto de uma vulnerabilidade; a role ainda acessa dados necessários
ao sistema. O participante nunca recebe credenciais PostgreSQL no navegador.

## 4. Variáveis e Docker Compose

| Variável proposta | Uso |
| --- | --- |
| ADMIN_PASSWORD | Senha do login web, convertida em hash em memória antes da factory |
| ADMIN_PASSWORD_HASH | Alternativa compatível com o mecanismo atual; definir precedência explícita |
| SECRET_KEY | Chave estável obrigatória na hospedagem |
| DB_HOST / DB_PORT / DB_NAME | Destino PostgreSQL |
| DB_USER | Role restrita, padrão `sis_app` |
| DB_PASSWORD / DB_PASSWORD_FILE | Senha explícita ou arquivo gerado pelo inicializador |
| DB_ADMIN_USER / DB_ADMIN_PASSWORD | Apenas preparação; nunca passadas ao serviço web |
| DB_SSLMODE | Política de TLS da conexão PostgreSQL |
| PORT | Porta HTTP interna |

O Compose deve declarar ADMIN_PASSWORD e SECRET_KEY por interpolação obrigatória,
sem valores fracos de fallback. Não sobrescrever o `.env` atual; documentar uso de
um arquivo local separado, ignorado pelo Git. O hash não deve aparecer em logs.
Manter o login indisponível ou falhar claramente quando a configuração estiver ausente.

Criar serviços PostgreSQL, preparação e web, com healthcheck do banco e web
dependendo do sucesso da preparação. Usar perfis `clean` e `test`, cada qual com
banco/volume próprio. Publicar apenas a porta HTTP por padrão; PostgreSQL acessível
pela rede interna Docker. Documentar comandos de build, start, logs e parada,
sem recomendar remoção de volumes como parte da inicialização.

## 5. Render e HTTPS

Criar um Web Service Docker para a variante selecionada e um Render Postgres
na mesma região. Configurar `dockerfilePath` para o Dockerfile escolhido e
contexto de build na raiz. O Compose servirá ao ambiente local; modelar os
serviços de hospedagem em `render.yaml`.

O serviço receberá um endereço `https://<nome-disponível>.onrender.com`.
O nome final depende de disponibilidade. Usar a conexão interna ao Postgres,
com credenciais da role restrita no app. Restringir conexões externas do banco.
Adicionar suporte coerente a conexão/SSL em setup e runtime; não interpretar
a URL administrativa fornecida pelo provedor como credencial permanente do app.

Antes de concluir a automação, verificar na instância Render os privilégios de
criação de roles da conta provisionada. Não presumir superusuário. Se a conta
não tiver CREATEROLE, exigir provisionamento compatível pelo provedor e registrar
o bloqueio, sem iniciar o app com a conta proprietária como alternativa silenciosa.

Configurar tratamento do proxy HTTPS confiável, cookie de sessão Secure e cookie
de dispositivo Secure na hospedagem. Respeitar o número conhecido de proxies;
não confiar indiscriminadamente em headers enviados pelo cliente. Manter cookies
locais compatíveis com HTTP de desenvolvimento.

Adicionar `/healthz` com verificação curta de disponibilidade do banco, sem expor
dados ou segredos. Definir timeout, workers adequados aos recursos e logs em stdout.
Persistir dados no Postgres, sem depender do filesystem do container. Documentar
backup, restauração e rollback com migrações compatíveis; confirmar custos e
retenção do plano escolhido antes de criar recursos.

## 6. Ordem de execução e critérios de aceite

1. Implementar configuração de segredos, conexão/SSL e provisionamento restrito.
2. Acrescentar Gunicorn, healthcheck e configuração de HTTPS/proxy.
3. Criar `images/`, Dockerfiles, `.dockerignore`, Compose e exemplo de variáveis.
4. Criar Blueprint Render e guia operacional, incluindo preparação separada.
5. Validar em bancos descartáveis e atualizar README/CONTINUIDADE com resultados reais.

Verificações necessárias:

- Build das duas imagens e validação do Compose e Blueprint.
- Banco novo clean com zero registros nas seis tabelas.
- Banco novo test com Perfil ativo, 11 perguntas e 120 alternativas; zero alunos,
  envios e respostas. Abrir o formulário e concluir um envio real de teste.
- Login com a senha configurada, rejeição de senha incorreta e manutenção de CSRF.
- Importação/exportação, análise e controle de devolutiva funcionando como `sis_app`.
- Provas de que a role restrita não cria/altera/remove tabelas, cria roles,
  executa TRUNCATE ou atualiza colunas não autorizadas.
- Entradas com aspas e fragmentos SQL armazenadas/tratadas como dados.
- Reinício e reprovisionamento sem apagar respostas, duplicar Perfil, trocar senha
  automaticamente ou substituir configurações existentes.
- Falha de preparação impede o web de iniciar; inicializações concorrentes seguras.
- Ausência de `.env` e segredos nas camadas da imagem, logs e ambiente do processo web.
- Suíte existente com `TEST_DATABASE_URL` apontando somente para banco isolado;
  registrar testes ignorados ou limitações de Docker/Render disponíveis.
- Smoke test HTTPS no Render, cookies Secure, healthcheck e persistência após redeploy.

Entrega deste estágio: plano revisável. Este documento não cria containers,
não altera bancos e não publica serviços. A implementação e o deploy serão
registrados separadamente quando executados.

## Fontes oficiais consultadas

- [Docker no Render](https://render.com/docs/docker)
- [Web Services: subdomínio, porta e HTTPS](https://render.com/docs/web-services)
- [Criação e conexão do Render Postgres](https://render.com/docs/postgresql-creating-connecting)
- [Referência do Blueprint](https://render.com/docs/blueprint-spec)
- [Flask no Render e Gunicorn](https://render.com/docs/deploy-flask)
