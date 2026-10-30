# Sistema de questionário

Aplicação com Flask, PostgreSQL/Psycopg, Tailwind CSS, painel de análise e relatório Power BI.
Permite cadastrar participantes, escolher questionários e responder todas as
perguntas em um único formulário. Cada navegador pode enviar uma vez por questionário.

## Configurar e executar

Requisitos: Python 3.14+, [uv](https://docs.astral.sh/uv/), PostgreSQL e seu cliente `psql`.
Node.js é necessário somente para recompilar o CSS, que já está incluído no projeto.

1. Instale as dependências e crie sua configuração local:

   ```powershell
   uv sync
   Copy-Item .env.example .env
   ```

2. Preencha `DB_PASSWORD` com a senha do usuário `client-app` e `SECRET_KEY` com
   uma chave aleatória. O `.env` é ignorado pelo Git. No ambiente local já configurado,
   preserve esse arquivo em vez de substituí-lo pelo exemplo.
   Gere uma chave com `uv run python -c "import secrets; print(secrets.token_hex(32))"`.

3. Prepare o banco usando um administrador:

   ```powershell
   uv run sis-questionario-db
   ```

   O comando pede a senha do administrador PostgreSQL e executa somente
   [`src/sis_questionario/banco.sql`](src/sis_questionario/banco.sql). Se o `psql`
   não estiver no PATH, informe `PSQL_PATH` no `.env`, por exemplo:
   `PSQL_PATH=C:/Program Files/PostgreSQL/18/bin/psql.exe`.

4. Inicie o aplicativo:

   ```powershell
   uv run sis-questionario
   ```

Abra http://127.0.0.1:5000. Pressione `Ctrl+C` para encerrar.

## SQL único e permissões

`banco.sql` reúne a criação do banco, do usuário `client-app`, das seis tabelas,
do índice contra envios duplicados e dos seguintes privilégios:

- `CONNECT` no banco configurado em `DB_NAME` (padrão: `mydatabase`).
- `USAGE` no schema `public` e nas sequências.
- `SELECT` e `INSERT` em `alunos`, `envios`, `opcoes`, `perguntas`, `questionarios` e `respostas`.

O SQL utiliza variáveis do **psql**, inclusive para receber `DB_PASSWORD` do
ambiente sem gravar a senha no arquivo versionado. Execute pelo comando acima
ou pelo `psql`, não pelo editor SQL do pgAdmin sem adaptação.

Reexecutar o script preserva os registros, atualiza a senha de `client-app` e
reaplica as concessões. Ele atende ao modelo atual; os scripts da arquitetura
antiga foram removidos. Não remove privilégios adicionais eventualmente concedidos
por um administrador a um usuário já existente.

O aplicativo não cria tabelas nem precisa de privilégios de administrador.
Na primeira execução, cadastra as perguntas do JSON usando `SELECT` e `INSERT`.
O cadastro de um e-mail existente retorna o aluno já registrado e preserva o nome
original, para funcionar sem `UPDATE`.

## Estrutura do projeto

```text
src/sis_questionario/
    app.py              # Rotas e criação do Flask
    bd_exec.py          # Consultas e gravação transacional
    config.py          # Leitura do .env
    setup_db.py        # Execução do SQL pelo administrador
    banco.sql          # Único arquivo SQL do projeto
    perguntas.json     # Carga inicial das perguntas
    templates/         # Páginas HTML
    static/css/app.css # Tailwind compilado
assets/tailwind.css    # Fonte dos estilos
docs/                  # Guia de análise e consultas de exemplo
tests/                 # Testes de integração
análise-dos-fatos.pbix  # Relatório Power BI preservado
```

As seis tabelas são `alunos`, `questionarios`, `perguntas`, `opcoes`, `envios` e
`respostas`, com IDs simples e chaves estrangeiras diretas. Envio e respostas são
salvos juntos; uma falha desfaz toda a transação. A aplicação valida a associação
entre questionário, pergunta e alternativa.

## Perguntas e outros questionários

O JSON cadastra o questionário `perfil` uma única vez. Reiniciar não duplica dados;
alterar o JSON não modifica perguntas já importadas. Para cadastrar outro questionário,
use um novo código:

```python
import json
from pathlib import Path
from sis_questionario.bd_exec import cadastrar_questionario

perguntas = json.loads(Path('satisfacao.json').read_text(encoding='utf-8'))
cadastrar_questionario('satisfacao', 'Pesquisa de satisfação', perguntas)
```

Preserve perguntas e alternativas que já têm respostas. Para desativar um
questionário, um administrador pode atualizar sua coluna `ativo`.

## Controle por navegador

Um cookie aleatório, com validade de um ano, identifica o navegador. O banco
impede repetir o mesmo identificador no mesmo questionário. Esse identificador
é separado da sessão Flask e permanece após reiniciar o app.
Limpar cookies, trocar de navegador ou usar uma nova sessão anônima permite
outro identificador. Isso não identifica o dispositivo físico nem autentica o aluno.
Envios anteriores ao recurso permanecem com identificador vazio.

## Painel de análise

Abra `/analise` ou o link **Análise · Acesso administrativo** no rodapé.
O painel usa o mesmo banco PostgreSQL e não exige migrações ou serviços adicionais.
Mostra também questionários inativos, para manter os resultados históricos disponíveis.

O acesso fica desabilitado até configurar `ADMIN_PASSWORD_HASH` no `.env`.
Gere o hash com a senha digitada de forma oculta:

```powershell
uv run python -c "from getpass import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass('Senha de administrador: ')))"
```

Copie o resultado completo para `ADMIN_PASSWORD_HASH` e reinicie a aplicação.
Não grave a senha em texto puro. Preserve uma `SECRET_KEY` aleatória e estável.
Ao hospedar com HTTPS, configure `SESSION_COOKIE_SECURE=true`; no localhost HTTP,
mantenha `false`. Não exponha o login por HTTP fora do computador local.

A sessão administrativa dura uma hora. Sair encerra a sessão atual; mudar o hash
da senha invalida as sessões administrativas anteriores. Login e logout validam
um token de formulário; cinco senhas incorretas bloqueiam novas tentativas por IP
por até cinco minutos. Esse limite fica na memória de cada processo; se a aplicação
passar a usar vários processos, aplique também um limite compartilhado no proxy.
As páginas administrativas não são armazenadas em cache. O painel e seus dados
são entregues juntos por uma rota protegida, sem endpoint de dados público.

Para explorar:

- Escolha o questionário e clique em **Abrir**. Isso limpa os filtros anteriores.
- No questionário de perfil, filtre por **Jogo escolhido** e clique em **Aplicar**.
  Esse controle corresponde à pergunta 11 da carga inicial `perfil`.
- Clique em qualquer alternativa nos gráficos para filtrar todos os resultados.
  Escolhas de perguntas diferentes são combinadas com **E**; uma nova escolha na
  mesma pergunta substitui a anterior. Clicar na escolha selecionada remove o filtro.
- Remova os filtros pelos marcadores ou use **Limpar filtros**.
- Confira contagens e percentuais do grupo e a tabela com até 50 envios por página.
  Os filtros permanecem na URL e na paginação; links compartilhados exigem login.

Cada contagem representa **envios**, não pessoas únicas. Todos os percentuais usam
o número de envios selecionados como denominador; respostas ausentes aparecem como
“—” na tabela e não entram nas barras. Datas usam `America/Sao_Paulo`.
A tabela não inclui nomes, e-mails nem identificadores de navegador.

## Power BI

O arquivo [`análise-dos-fatos.pbix`](análise-dos-fatos.pbix) faz parte do repositório.
No Power BI, configure a fonte PostgreSQL com os valores de `DB_HOST`, `DB_PORT`,
`DB_NAME` e o usuário `client-app`. Informe a senha da sua configuração local.
Consulte [o guia de relacionamentos e medidas](docs/power-bi.md) e
[as consultas SQL de exemplo](docs/consultas.md).

## Estilos

O CSS é local e não depende de CDN. Para recompilar após mudar as classes HTML:

```powershell
npm ci
npm run build:css
```

Durante a edição, use `npm run watch:css`. O fluxo usa o
[Tailwind CLI](https://tailwindcss.com/docs/installation/tailwind-cli).

## Testes

Os testes usam um administrador em uma conexão separada para criar schemas e
roles temporárias, revertidos ao final. A aplicação continua usando `client-app`.

```powershell
$env:TEST_DATABASE_URL = 'postgresql://administrador:SENHA@localhost:5432/mydatabase'
uv run python -m unittest discover -s tests -v
```

Sem essa variável, os testes de integração são ignorados. Eles verificam o fluxo
de envio, validação, bloqueio por navegador e execução com apenas `SELECT` e `INSERT`.
Os testes de autenticação e renderização do painel rodam mesmo sem banco de testes.
Com `TEST_DATABASE_URL`, também são verificados os cruzamentos de respostas,
percentuais, paginação e isolamento entre questionários.

## Arquivos para o GitHub

Inclua código, `banco.sql`, `.env.example`, lockfiles, CSS compilado e o `.pbix`.
O `.gitignore` exclui `.env`, dependências, caches, logs e prévias locais.
O projeto foi preparado localmente; criar o repositório e fazer o push são etapas separadas.
