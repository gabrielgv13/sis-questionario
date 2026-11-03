# Banco manual, Docker e Render

## Preparar pelo pgAdmin

1. Crie um Render Postgres e abra sua pagina Info. Anote banco, usuario
   proprietario, senha, porta e hostname externo completo.
2. Em Networking, permita o IP publico do seu computador. O Blueprint deste
   repositorio desativa conexoes externas inicialmente (`ipAllowList: []`),
   portanto adicione seu IP antes de conectar pelo pgAdmin local.
3. No pgAdmin, registre um servidor com os dados externos, banco de manutencao
   igual ao banco criado e SSL mode `require`.
4. Selecione esse banco e abra o Query Tool. Abra o arquivo
   [`src/sis_questionario/banco.sql`](../src/sis_questionario/banco.sql).
5. Substitua a senha na variavel `senha` no inicio do arquivo por um segredo
   aleatorio de pelo menos 24 caracteres. Se houver apostrofos, duplique-os no
   literal SQL. Execute o arquivo inteiro, incluindo BEGIN e COMMIT.
6. Configure o web com DB_USER=sis_app e DB_PASSWORD igual a essa senha.

O arquivo unico cria as seis tabelas, sequencias, indice de envio unico,
colunas e migracoes de bancos antigos, a role restrita e todas as permissoes.
Nao cria outro banco: o destino e sempre o banco selecionado no pgAdmin.
Nao insere questionarios, participantes ou respostas ficticias.
Reexecutar preserva registros e a senha de sis_app existente. A senha informada
no arquivo so e usada na primeira criacao; em bancos existentes, use a senha
atual em DB_PASSWORD. Uma role existente com privilegios elevados ou proprietaria
de objetos e recusada. O script exige propriedade dos objetos e CREATEROLE.
Se ocorrer erro, execute ROLLBACK antes de corrigir e executar novamente.
Use em banco dedicado: o script remove CREATE de PUBLIC no schema public.

O acesso externo usa TLS; o web na mesma regiao deve usar os dados internos.
Veja a [documentacao de conexoes do Render](https://render.com/docs/postgresql-creating-connecting).

## Servico web no Render

Use `render.yaml` para criar os recursos ou configure um Web Service Docker
com `images/clean-image/Dockerfile`. Para imagem publicada, use uma tag que
contenha estas alteracoes; imagens antigas ainda executam o provisionador.

| Variavel | Valor |
| --- | --- |
| DB_HOST / DB_PORT / DB_NAME | Dados internos do Render Postgres |
| DB_USER | sis_app |
| DB_PASSWORD | Senha definida no SQL (informada manualmente no Blueprint) |
| DB_SSLMODE | require |
| ADMIN_PASSWORD | Senha do painel web, independente do PostgreSQL |
| SECRET_KEY | Segredo estavel com pelo menos 32 caracteres |
| COOKIE_SECURE / TRUST_PROXY | 1 |

Deixe **Pre-Deploy Command vazio** e **Health Check Path = /healthz**.
Remova DB_ADMIN_USER, DB_ADMIN_PASSWORD e DB_PASSWORD_FILE de servicos antigos.
Execute o SQL antes de iniciar o web; um deploy iniciado antes disso pode
falhar no healthcheck, exigindo novo deploy depois da preparacao.
Nao e necessario dar credenciais proprietarias ao processo Python.
Nas proximas atualizacoes de esquema, reaplique o SQL como proprietario.
Os recursos do Blueprint usam planos pagos.

## Docker local

Copie `.env.docker.example` para `.env.docker.local` e configure os quatro
segredos. DB_PASSWORD deve corresponder a senha de sis_app no SQL.

```powershell
docker compose --env-file .env.docker.local --profile clean up -d db-clean
# pgAdmin: localhost:5433, banco sis_questionario, usuario sis_owner,
# senha POSTGRES_PASSWORD. Execute banco.sql e depois:
docker compose --env-file .env.docker.local --profile clean up --build -d web-clean
# http://localhost:5000
```

O perfil test usa db-test em localhost:5434 e web-test em localhost:5001.
Prepare-o pelo mesmo procedimento, trocando clean por test nos comandos.
As duas imagens iniciam exclusivamente o web e exigem banco preparado.
Para carregar o Questionario de Perfil, importe `docs/questionario_perfil.json`
no admin. Para demonstracoes com respostas ficticias, execute separadamente
`docs/popular_perfil.sql` como proprietario; nunca e executado automaticamente.

Os volumes preservam dados ao reiniciar. `docker compose down` tambem preserva
volumes; a opcao --volumes apaga-os. Para novas imagens:

```powershell
docker build -f images/clean-image/Dockerfile -t gabrielgventura/sis-questionario:clean .
docker build -f images/test-image/Dockerfile -t gabrielgventura/sis-questionario:test .
```

A CI prepara bancos de teste explicitamente com psql e executa a suite antes
de publicar. A aplicacao recebe SELECT/INSERT nas seis tabelas, USAGE nas
sequencias e UPDATE somente em questionarios(exibir_resultado, documento).
Use TEST_DATABASE_URL somente em servidor isolado; os testes de integracao
criam e removem bancos e roles descartaveis.
