# Sistema de questionário

> A execução local e os containers usam FastAPI, Uvicorn e pool assíncrono do Psycopg 3. Consulte [Docker e Compose](docs/docker-render.md) e [a migração para ASGI](docs/fastapi-migration.md).

Aplicação com FastAPI, PostgreSQL/Psycopg, Tailwind CSS e painel de análise integrado.
Permite cadastrar participantes, escolher questionários e responder todas as
perguntas em um único formulário. Cada navegador pode enviar uma vez por questionário.

## Docker e Render

Consulte [o guia Docker, Docker Hub e Render](docs/docker-render.md) para executar
as variantes `clean-image` (banco novo sem questionários) e `test-image` (Perfil
pronto, sem respostas fictícias), configurar a senha administrativa pelo Compose
e publicar em `gabrielgventura/sis-questionario`. As duas variantes preservam
dados existentes e usam uma conta PostgreSQL restrita criada pelo provisionador.

## Configurar e executar

Requisitos: Python 3.14+, [uv](https://docs.astral.sh/uv/) e PostgreSQL em execução.
O cliente `psql` e `PSQL_PATH` não são necessários: Psycopg conecta diretamente ao servidor.
Node.js só é necessário para recompilar o CSS.

Após clonar, com o PostgreSQL local configurado com usuário e senha `postgres`:

```powershell
uv sync
uv run sis-questionario
```

Abra http://127.0.0.1:5000. Pressione `Ctrl+C` para encerrar.

O comando padrão prepara as tabelas e inicia sem cadastrar questionários. Em
um banco novo, o sistema fica vazio, pronto para importar questionários no admin.
Para iniciar com o **Questionário de Perfil** e sua classificação prontos:

```powershell
uv run sis-questionario-perfil
```

Os dois comandos preparam o banco automaticamente. O comando com Perfil cadastra
somente o questionário, sem participantes fictícios. Reexecutá-lo não duplica ou
sobrescreve perguntas existentes. Iniciar pelo comando padrão depois disso
preserva os questionários e respostas; nenhum comando de inicialização apaga dados.
`uv run sis-questionario-db` permanece disponível para preparar somente a estrutura.

O `.env` é opcional. Os padrões locais são `DB_HOST=localhost`, `DB_PORT=5432`,
`DB_NAME=mydatabase`, `DB_USER=postgres` e `DB_PASSWORD=postgres`.
Para personalizar, copie `.env.example` para `.env` e altere os valores.
Variáveis do ambiente têm prioridade. Preserve um `.env` existente.
Para usar um administrador separado no setup, defina `DB_ADMIN_USER` e
`DB_ADMIN_PASSWORD`; por padrão ele usa as credenciais de conexão do app.
O comando usa a senha configurada, sem prompt, e não altera a senha do servidor.

Essas credenciais padrão são para desenvolvimento local. Na hospedagem, configure
credenciais próprias e uma `SECRET_KEY` estável e aleatória:
`uv run python -c "import secrets; print(secrets.token_hex(32))"`.

## Preparação do banco

O setup cria o banco se necessário e aplica `src/sis_questionario/banco.sql`
em uma transação. Reexecutar preserva os registros e reaplica a estrutura.
O SQL é SQL PostgreSQL comum, sem comandos específicos do `psql`.
O usuário do setup precisa poder criar o banco e suas tabelas.
O setup não cria usuários; `DB_USER` deve existir no servidor.

Somente `sis-questionario-perfil` cadastra o Perfil usando `SELECT` e `INSERT`.
Criar a aplicação FastAPI diretamente não prepara nem popula o banco. Em uma
hospedagem com conta restrita, execute a preparação como administrador antes
de servir a aplicação com `sis_questionario.app:create_app`. Conceda `CONNECT` no banco,
`USAGE` no schema `public` e nas sequências, e `SELECT` e `INSERT` nas seis tabelas.

## Painel administrativo

Para experimentar os gráficos com dados fictícios, execute
[`docs/popular_perfil.sql`](docs/popular_perfil.sql) no banco da aplicação pelo
editor SQL do pgAdmin. Prepare as tabelas antes com `uv run sis-questionario-db`.
O script usa INSERTs para cadastrar o questionário de perfil, suas perguntas e
alternativas, 120 participantes fictícios e 1.320 respostas. Pode ser reexecutado
sem duplicar os envios de exemplo e não altera respostas existentes. Os envios
fictícios incluem resultados de `perfil_v1`, permitindo testar o gráfico
de perfis e seus filtros. Reexecutar preenche resultados ausentes de exemplos
antigos apenas quando suas respostas correspondem às do script, preservando
resultados já salvos e a configuração de devolutiva do admin. Os dados
de exemplo passam a fazer parte das estatísticas do painel.

Acesse http://127.0.0.1:5000/admin para abrir a página inicial administrativa.
Ela oferece **Análise de respostas** (`/admin/analise`) e **Gerenciar questionários**
(`/admin/questionarios`). A análise mantém os gráficos, filtros e exportação de
resultados. O gerenciamento lista os questionários cadastrados, com busca por
título ou código e filtro de status. A importação e a exportação JSON estão
disponíveis no [formato versionado de questionário](docs/formato-questionario.md),
com estrutura salva em `questionarios.documento` (JSONB). Há um
[exemplo completo do Perfil](docs/questionario_perfil.json) e um
[JSON Schema](docs/questionario.schema.json). A importação não sobrescreve códigos
existentes; para importar uma cópia, altere o código no arquivo. Execute
`uv run sis-questionario-db` para migrar os questionários existentes antes de usar.
Se `algoritmo` estiver preenchido, selecione também o JSON de regras solicitado
pelo formulário. Use [perfil.template.json](docs/perfil.template.json) como modelo.
O servidor valida e salva os dois arquivos na mesma transação; **Exportar algoritmo**
permite baixar as regras para reutilizá-las em uma nova importação.
A exclusão continua apenas como prévia. Sua janela informa que a futura ação
também removerá os envios e as respostas associados.

O painel exige
uma senha própria, independente das credenciais do PostgreSQL. Para habilitar:

1. Gere o hash da senha (o comando solicita a senha sem exibi-la):

   ```powershell
   uv run python -c "from getpass import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass('Admin password: ')))"
   ```

2. Copie o resultado inteiro para `ADMIN_PASSWORD_HASH` no `.env`. Configure também
   uma `SECRET_KEY` aleatória e estável, conforme as instruções acima.
3. Reinicie o aplicativo e entre em `/admin`. Sem o hash, o acesso fica desabilitado.

Selecione um questionário, inclusive inativo, para visualizar um gráfico de pizza
por pergunta, com legendas coloridas clicáveis ao lado. O título é o enunciado; cada alternativa mostra sua contagem e o
percentual das respostas representadas naquele gráfico, incluindo contagens zero.
Os gráficos usam recursos locais do navegador, sem CDN ou biblioteca externa.

Clique em uma legenda para filtrar as respostas dos mesmos envios em todos os
gráficos. Várias alternativas na mesma pergunta significam **ou**; perguntas
diferentes significam **e**. Todos os gráficos consideram todos os filtros,
inclusive os da própria pergunta. Ao selecionar uma única alternativa, ela
representa 100% da pizza da pergunta se houver envios correspondentes. Com várias
alternativas selecionadas, elas dividem a pizza conforme suas contagens. Sem
envios correspondentes, a pizza mostra “Sem respostas”, sem percentuais artificiais.
As opções com zero respostas permanecem na legenda para permitir novos filtros.
As legendas exibem até oito opções por vez, com rolagem suave para acessar as
demais. Inicialmente, aparecem da maior para a menor porcentagem. O botão acima
da legenda inverte entre ordem crescente e decrescente, independentemente por
gráfico. A ordem escolhida é mantida ao filtrar ou atualizar durante a sessão
do painel, sem alterar as cores das opções. Empates mantêm a ordem original.
Textos longos aparecem completos ao passar o mouse sobre a opção.
Cada fatia possui uma linha apontando para seu percentual fora da pizza;
opções sem respostas continuam na legenda, sem criar fatias artificiais.

Clique novamente para desmarcar, remova uma etiqueta de filtro ou use **Limpar
filtros**. **Atualizar** busca novos envios preservando os filtros. As alternativas
também são botões acessíveis pelo teclado. O painel só retorna dados agregados,
sem nomes ou e-mails. Use **Sair** para encerrar o acesso administrativo.

## Exportar gráficos

No admin, clique em **Exportar gráficos**. Ao abrir, o painel marca **Exportar
com filtro atual** quando houver seleções de respostas ou perfis; caso contrário,
marca **Exportar simples**. As duas opções são exclusivas. O modo simples ignora
todos os filtros; o modo com filtro atual mantém inclusive filtros de perguntas
que não foram escolhidas para exportar.

Escolha PDF (padrão), CSV ou JSON em **Saída de exportação**. No menu colapsável,
**Todos** é a seleção padrão e inclui o gráfico de perfis quando disponível.
Selecione questões individuais para exportar apenas parte dos gráficos; selecionar
todas individualmente volta para **Todos**. Sem seleção, a exportação fica
desabilitada. Cada gráfico mantém sua ordenação e as cores das alternativas.

O PDF inclui pizzas, todas as legendas e tabelas de contagens e percentuais,
com paginação. CSV (UTF-8 com BOM, separado por ponto e vírgula) e JSON exportam
os dados agregados. Todos os formatos identificam questionário, instante de
geração em UTC, modo e filtros aplicados, sem nomes ou e-mails de participantes.
As opções são capturadas ao clicar em **Exportar**, e as contagens são consultadas
novamente no banco em um único snapshot. O download exige autenticação de admin.

A geração de PDF usa ReportLab; após atualizar, execute `uv sync` para instalar
as dependências novas.

## Devolutiva e classificação de perfis

Depois de atualizar o código, execute `uv run sis-questionario-db` antes de
reiniciar o aplicativo. A migração adiciona a configuração nos questionários e
um resultado JSON por envio, sem remover dados. O Questionário de Perfil recebe
o algoritmo `perfil_v1` e a devolutiva habilitada na primeira migração.
Reexecutar o setup preserva a escolha posterior do administrador.

No admin, selecione o questionário e marque ou desmarque **Exibir o perfil ao
participante após responder**. O cálculo e o armazenamento continuam ativos
quando a exibição está desabilitada. Questionários sem algoritmo mantêm apenas
a confirmação de envio. Outros classificadores exigem implementação própria;
não basta associar o algoritmo de Perfil a perguntas diferentes.

O resultado é salvo com as respostas na mesma transação, incluindo a versão,
as pontuações dos cinco perfis, a quantidade de associações +20 e os vencedores.
Vence a maior pontuação; em empate, vence quem tiver mais associações +20;
persistindo o empate, o resultado é **Perfil misto**. Valores negativos são
preservados. A conclusão mostra os pontos e permite atualizar a página na mesma
sessão, verificando também o identificador do navegador. Não há consulta pública
por número do envio.

O painel inclui o gráfico **Perfis dos participantes**, mesmo com a devolutiva
desativada. Suas legendas filtram as respostas das perguntas, e os filtros das
perguntas também atualizam os perfis. Perfis selecionados combinam por **ou**;
o conjunto combina por **e** com as perguntas. Cada envio misto conta uma vez
em **Perfil misto**. Envios sem resultado salvo aparecem em **Sem classificação**;
o aplicativo não os recalcula automaticamente. O script de exemplos agora inclui
a classificação e pode preencher resultados ausentes dos seus próprios envios.

Os pesos do Perfil original estão em `src/sis_questionario/perfil_v1.json`.
Questionários importados usam seu próprio arquivo de algoritmo, salvo em
`questionarios.regras_algoritmo`, inclusive quando se chama `perfil_v1`.
Pesos e nomes dos perfis são associados aos textos das perguntas e alternativas,
sem depender dos IDs do banco. A referência
original está em [perfil-regras-originais.md](docs/perfil-regras-originais.md).
Interpretações adotadas: Educação dá +10 a Tecnológicos, +20 aos demais exceto
Otakus; comida dá +5 a todos, e Prato popular soma mais +10 a Tecnológicos.
Adições e subtrações são cumulativas, inclusive nas duas opções de jogos.
A pergunta 5 continua permitindo uma única resposta. Mudanças futuras nos pesos
devem criar uma nova versão para preservar o significado dos resultados salvos.

Com uma conta PostgreSQL restrita, o controle do admin precisa também de
`UPDATE (exibir_resultado, documento)` em `questionarios`; o fluxo de participação continua
funcionando apenas com `SELECT` e `INSERT`, além das permissões de sequências.

## Estrutura do projeto

```text
src/sis_questionario/
    app.py              # Rotas e criação do FastAPI
    bd_exec.py          # Consultas e gravação transacional
    config.py          # Leitura do .env
    setup_db.py        # Execução do SQL pelo administrador
    banco.sql          # Único arquivo SQL do projeto
    perguntas.json     # Carga opcional do Questionário de Perfil
    perfil_v1.json     # Pesos versionados da classificação
    templates/         # Páginas HTML
    static/css/app.css # Tailwind compilado
assets/tailwind.css    # Fonte dos estilos
docs/                  # Guia de análise e consultas de exemplo
tests/                 # Testes de integração
```

As seis tabelas são `alunos`, `questionarios`, `perguntas`, `opcoes`, `envios` e
`respostas`, com IDs simples e chaves estrangeiras diretas. Envio e respostas são
salvos juntos; uma falha desfaz toda a transação. A aplicação valida a associação
entre questionário, pergunta e alternativa.

## Perguntas e outros questionários

O comando `uv run sis-questionario-perfil` usa o JSON para cadastrar `perfil`
uma única vez. O comando padrão não faz essa carga. Reiniciar não duplica dados;
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
é separado da sessão assinada e permanece após reiniciar o app.
Limpar cookies, trocar de navegador ou usar uma nova sessão anônima permite
outro identificador. Isso não identifica o dispositivo físico nem autentica o aluno.
Envios anteriores ao recurso permanecem com identificador vazio.

## Power BI

Relatórios externos podem ser criados conectando ao PostgreSQL; não é necessário
um arquivo Power BI para executar o sistema. Configure a fonte com `DB_HOST`, `DB_PORT`,
`DB_NAME` e o usuário configurado em `DB_USER`. Informe a senha da sua configuração local.
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

O servidor local usa Uvicorn, com um worker por padrão e um pool PostgreSQL
assíncrono por worker. Consulte [execução e pools](docs/fastapi-migration.md)
para configuração, compatibilidade com Windows e escopo dos containers legados.

Os testes usam um administrador em uma conexão separada para criar schemas e
roles temporárias, revertidos ao final. Os testes verificam também uma conta restrita.

```powershell
$env:TEST_DATABASE_URL = 'postgresql://administrador:SENHA@localhost:5432/mydatabase'
uv run python -m unittest discover -s tests -v
```

Sem essa variável, os testes de integração são ignorados. Eles verificam o fluxo
de envio, validação, bloqueio por navegador e execução com apenas `SELECT` e `INSERT`.

## Arquivos para o GitHub

Inclua código, `banco.sql`, `.env.example`, lockfiles, CSS compilado, testes e `docs/`.
O `.gitignore` exclui `.env`, dependências, caches, logs e prévias locais.
Os arquivos de build de CSS são preservados para manutenção; Node.js não é
necessário em tempo de execução. Artefatos externos e duplicatas sem uso foram
removidos; o conteúdo de `docs/` foi mantido, com nomes institucionais neutralizados.

## Compatibilidade de versões

A classificação passa a usar `perfil_v1`. A preparação migra automaticamente os
identificadores antigos nas configurações, documentos JSONB e resultados salvos,
sem recalcular pontos ou alterar respostas. Arquivos JSON exportados pela versão
anterior também são normalizados durante a importação. Os pesos permanecem iguais.
