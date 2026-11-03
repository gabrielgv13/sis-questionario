# Continuidade do desenvolvimento

Registro da sessão encerrada em **03/11/2026**, no fuso America/Sao_Paulo.
Este documento descreve o estado ao final da sessão. Antes de continuar, confira
os arquivos atuais e as alterações locais do usuário: este registro não substitui
o código nem garante o estado de um banco específico.

## Contexto e decisões do usuário

O projeto é um sistema de questionários com Flask e PostgreSQL, gerenciado com
`uv`. A interface e a documentação de uso são em português. Os objetivos desta
sessão foram facilitar a inicialização, criar análise administrativa interativa,
classificar as respostas do Questionário de Perfil, permitir exportações e
importações e organizar o repositório.

Decisões que devem ser preservadas:

- O comando padrão inicia sem carregar questionários em um banco novo.
- “Sistema limpo” não significa apagar um banco existente. Reiniciar preserva dados.
- Há um comando separado que prepara o Questionário de Perfil sem dados fictícios.
- A pasta `docs/` deve ser mantida.
- O conteúdo atual do repositório não deve ter nomes institucionais; o histórico
  Git não foi reescrito. O classificador atual chama-se `perfil_v1`.
- Os gráficos devem considerar todos os filtros, inclusive o da própria pergunta.
  A primeira implementação ignorava o filtro da própria pergunta; isso foi
  alterado expressamente pelo usuário. Não restaurar esse comportamento antigo.
- O usuário pediu inicialmente somente a interface de gerenciamento. Depois
  autorizou implementar importação/exportação JSON. A exclusão ainda é uma prévia.

## Ambiente e comandos

- Python 3.14+; shell utilizado: PowerShell no Windows.
- Dependências Python: Flask, `psycopg[binary]`, python-dotenv e ReportLab.
- PostgreSQL precisa estar instalado e em execução. Psycopg conecta diretamente;
  não depende de `psql`, de descoberta de executável ou de `PSQL_PATH`.
- `.env` é opcional, ignorado pelo Git e não deve ser exposto ou sobrescrito.
  Variáveis do ambiente têm prioridade sobre esse arquivo.
- Padrões de desenvolvimento: host `localhost`, porta `5432`, banco `mydatabase`,
  usuário `postgres`, senha `postgres`. Esses padrões não alteram a senha do servidor.
- `DB_ADMIN_USER` e `DB_ADMIN_PASSWORD` podem substituir as credenciais somente
  na preparação. Sem esses overrides, ela usa as credenciais de conexão do app.

```powershell
uv sync

# Prepara as tabelas e inicia sem cadastrar questionários automaticamente:
uv run sis-questionario

# Prepara as tabelas, instala o Perfil se ausente e inicia:
uv run sis-questionario-perfil

# Prepara somente a estrutura e aplica as migrações:
uv run sis-questionario-db
```

O endereço local é `http://127.0.0.1:5000`.
Os dois comandos que iniciam o servidor preparam o banco antes de servir o app.
Essa preparação exige uma conta com privilégios apropriados. Para hospedagem
com conta restrita, preparar separadamente e servir a factory
`sis_questionario.app:create_app`.

`create_app()` usa `inicializar=False` como padrão e não carrega o Perfil.
O parâmetro explícito de inicialização ainda existe por compatibilidade.
`bd_exec.inicializar_banco()` tem nome histórico: sua função é cadastrar o Perfil,
não preparar as tabelas. O CLI com Perfil chama essa função explicitamente.

## Alterações implementadas

### Preparação do banco

`setup_db.py` passou a usar Psycopg em vez de subprocesso/psql. Ele cria o banco
se necessário, fora de transação, e aplica `banco.sql` em uma transação.
O SQL não usa metacomandos do psql e pode ser executado como SQL PostgreSQL comum.

As tabelas continuam sendo `alunos`, `questionarios`, `perguntas`, `opcoes`,
`envios` e `respostas`. Novos campos importantes:

| Tabela | Campo | Finalidade |
| --- | --- | --- |
| questionarios | algoritmo | Referência opcional ao classificador versionado |
| questionarios | exibir_resultado | Controla a devolutiva ao participante |
| questionarios | documento JSONB | Estrutura importável/exportável do questionário |
| envios | resultado JSONB | Resultado individual persistido e versionado |

`banco.sql` tem migrações idempotentes. Elas preservam registros, preenchem
documentos JSONB ausentes a partir da estrutura existente e normalizam o
identificador histórico do classificador em configurações, documentos e
resultados. A migração do identificador não recalcula pontuações.
O identificador anterior está representado em hexadecimal na compatibilidade,
para não reintroduzir nomes institucionais em texto no projeto.

### Autenticação e navegação administrativa

Login administrativo independente das credenciais PostgreSQL, configurado com
`ADMIN_PASSWORD_HASH`. Sem hash configurado, o login retorna indisponibilidade.
Usar `SECRET_KEY` estável. Gere o hash sem mostrar a senha:

```powershell
uv run python -c "from getpass import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass('Admin password: ')))"
```

Rotas de páginas:

| Rota | Função |
| --- | --- |
| /admin/login | Login por senha |
| /admin e /admin/ | Dashboard inicial com duas opções |
| /admin/analise | Análise de respostas e perfis |
| /admin/questionarios | Gerenciamento de questionários |
| POST /admin/logout | Encerra a sessão |

As páginas compartilham navegação. O login leva à dashboard inicial, não
diretamente aos gráficos. Respostas administrativas usam `Cache-Control: no-store`.
As operações POST administrativas verificam token CSRF.

### Análise e gráficos

- Um gráfico por pergunta, usando o enunciado como título.
- Contagem e percentual de escolha por alternativa, incluindo alternativas zeradas.
- Gráficos de pizza em SVG local, sem Chart.js ou CDN.
- Linhas externas apontam das fatias para seus percentuais. O algoritmo de layout
  separa os rótulos por lado e evita sobreposição dentro do viewport calculado.
- Legendas com cores estáveis, botões acessíveis por teclado e até oito opções
  visíveis por vez. As demais ficam em rolagem suave; textos longos têm tooltip.
- Legendas começam em ordem decrescente de contagem/percentual. Um botão em cada
  gráfico inverte para crescente. Empates mantêm a ordem original. A escolha de
  ordenação é mantida por questionário/gráfico na página, inclusive ao atualizar.
- Seleções na mesma pergunta combinam por OU; perguntas diferentes combinam por E.
- As respostas são relacionadas por `id_envio`, não por participante. Isso evita
  cruzar respostas pertencentes a envios diferentes da mesma pessoa.
- Todos os gráficos aplicam todos os filtros. Se somente uma opção de uma pergunta
  estiver selecionada e houver resultados, ela representa 100% daquela pizza.
- Sem resultados, mostrar “Sem respostas”, sem criar percentuais artificiais.
- Filtros aparecem em etiquetas removíveis. Há limpar filtros e atualizar.
- Requisições antigas são canceladas/descartadas para evitar exibir dados obsoletos.
- A agregação acontece no PostgreSQL em snapshot `REPEATABLE READ READ ONLY`.
- O painel recebe dados agregados, sem nomes ou e-mails dos participantes.

### Classificação de Perfil e devolutiva

Os pesos estão em `src/sis_questionario/perfil_v1.json`. A implementação pura está
em `perfis.py`. São cinco perfis:

1. Contraculturais / Políticos.
2. Identitários / Melancólicos.
3. Tecnológicos / Digitais.
4. Estilos de Vida e Esportes.
5. Otakus.

As regras são associadas ao texto da pergunta e da alternativa, sem depender
dos IDs gerados pelo banco. A matriz cobre as 11 perguntas e 120 alternativas.
Há uma única resposta por pergunta, inclusive na pergunta de pesquisa na internet.

Regras adotadas ao interpretar o documento fornecido pelo usuário:

- Somar todas as adições e subtrações; preservar valores negativos.
- Vence a maior pontuação líquida.
- Em empate, comparar o número de respostas com associação +20 para os empatados.
- Persistindo o empate, retornar `misto` com a lista dos perfis envolvidos.
- Educação: +10 para Tecnológicos, +20 para os demais, exceto Otakus, que recebe 0.
- Comida: +5 para todos em qualquer alternativa; Prato popular soma mais +10
  para Tecnológicos, que recebe 15 nessa resposta.
- Nas opções de jogos, soma e subtração são cumulativas; +10 e -5 resultam em +5.

O resultado salvo tem `version`, `scores`, `strong`, `winners` e `category`.
É gravado no mesmo INSERT de envio, na transação das respostas. Não recalcular
resultados antigos automaticamente ao mudar regras. Alterações de pesos devem
criar outra versão do classificador.

O controle no admin habilita/desabilita a exibição ao participante, mas o cálculo
e o armazenamento continuam ativos. Na conclusão, a consulta verifica o envio
na sessão e o identificador do navegador. Atualizar a página preserva o resultado.
Não há consulta pública por número de envio. Questionários sem algoritmo mostram
somente a confirmação de participação.

O painel inclui um gráfico de perfis quando existe classificador configurado,
mesmo se a devolutiva estiver oculta. Os filtros são bidirecionais entre perfis e
respostas. `misto` é uma categoria única, sem duplicar envios; resultados ausentes
aparecem em `sem_classificacao`. Perfis selecionados combinam por OU entre si e
por E com as perguntas.

### Exportação de gráficos

O botão acima dos gráficos abre um painel com:

- Checkboxes exclusivos: “Exportar com filtro atual” e “Exportar simples”.
  Ao abrir, o padrão depende da existência de filtros de perguntas ou perfis.
- Formato PDF por padrão, com alternativas CSV e JSON.
- Checklist colapsável: “Todos” por padrão, incluindo perfis quando disponível.
  Selecionar questões desmarca Todos; selecionar todas individualmente consolida
  em Todos. Sem seleção, o download fica desabilitado.

Selecionar somente alguns gráficos não elimina filtros das outras perguntas
no modo filtrado. O modo simples ignora os filtros. Os parâmetros são capturados
no clique e as contagens são consultadas novamente no banco. O exportador mantém
as cores e a ordenação por gráfico, inclui título, instante em UTC e filtros.

- PDF: ReportLab, pizzas, legendas completas e tabelas paginadas.
- CSV: UTF-8 com BOM, delimitador ponto e vírgula, uma linha por alternativa,
  proteção de texto que poderia virar fórmula de planilha.
- JSON: metadados e gráficos estruturados, sem dados individuais.

O código está em `exportacao.py`. O endpoint de exportação exige sessão admin
e token CSRF, assim como as consultas POST do painel.

### Importação/exportação de questionários

Essa exportação é diferente da exportação de gráficos: transfere a definição
do questionário, sem respostas ou dados de participantes.

Formato v1 obrigatório:

```json
{
  "schema_version": 1,
  "codigo": "exemplo",
  "titulo": "Questionário de exemplo",
  "ativo": true,
  "algoritmo": null,
  "exibir_resultado": false,
  "perguntas": [
    {"enunciado": "Qual opção você prefere?", "opcoes": ["A", "B"]}
  ]
}
```

Regras principais:

- UTF-8, BOM opcional, máximo de 1 MiB; sem campos extras ou chaves repetidas.
- Código de 1 a 80 caracteres, minúsculas ASCII, números, hífen ou sublinhado,
  começando com letra ou número; título até 300 caracteres.
- De 1 a 100 perguntas distintas, enunciados até 2.000 caracteres.
- De 2 a 100 alternativas distintas por pergunta, textos até 500 caracteres.
- Textos vazios, nulos internos e Unicode inválido são rejeitados.
- Arrays determinam a ordem; não incluir IDs, campo ordem ou resposta correta.
- `algoritmo` é null ou `perfil_v1`; a devolutiva exige um algoritmo.
- O Perfil exige os textos conhecidos. Novas regras executáveis ou pesos
  arbitrários não são importados; classificadores adicionais exigem código.
- Códigos existentes retornam conflito, sem sobrescrita. Para duplicar, mudar o código.
- O documento validado é salvo em `questionarios.documento` como JSONB e as tabelas
  relacionadas são preenchidas na mesma transação. Falhas revertem tudo.
- JSONB preserva conteúdo e arrays, não o espaçamento nem a ordem das chaves.
- A configuração de devolutiva atualiza o documento salvo.
- Identificadores de algoritmo da versão anterior são normalizados ao importar.

Arquivos de referência:

- `docs/formato-questionario.md`: contrato detalhado.
- `docs/questionario.schema.json`: JSON Schema.
- `docs/questionario.template.json`: template importável para novos questionários.
- `docs/criar-questionario-com-ia.md`: prompt pronto e regras para geração por IA.
- `docs/questionario_perfil.json`: exemplo completo do Perfil no formato v1.

O template começa com `ativo: false`. Definir true antes de importar para
disponibilizar aos participantes; ainda não existe controle de status na interface.
O arquivo interno `perguntas.json` continua no formato de carga antigo e é
convertido para v1 pelo cadastro do Perfil; não é o template de importação.

### Dados fictícios

`docs/popular_perfil.sql` cria perguntas, alternativas, 120 participantes e envios
fictícios, e 1.320 respostas. Os resultados JSONB são snapshots compatíveis com
o classificador. Há cobertura de todas as alternativas.

O script é idempotente e não altera respostas existentes. Reexecutar preenche
resultados ausentes somente nos exemplos identificados pelo script cujas respostas
ainda correspondem às escolhas originais. Não substitui resultados salvos nem
classifica envios reais. Preserva a configuração de devolutiva e preenche o
documento JSONB ausente. Executá-lo altera as estatísticas do banco escolhido;
nenhum dos comandos de inicialização faz essa carga fictícia.

Em um momento da sessão esse arquivo ficou vazio no workspace, causando falhas
de dois testes. Depois ele foi restaurado e a suíte completa voltou a passar.
Ao retomar, não assumir que ele continua vazio nem restaurá-lo cegamente.

### Limpeza e neutralização do repositório

- Renomeados o arquivo de pesos para `perfil_v1.json` e a referência de regras
  para `docs/perfil-regras-originais.md`.
- Atualizados identificadores, mensagens, documentação, exemplos, schema e testes.
- Removido o relatório binário Power BI da raiz, que não era necessário ao sistema.
- Removida a cópia sem uso de `popular_perfil.sql` em `tests/`.
- Removidos caches Python em `src/` e `tests/` após a validação.
- Mantidos `docs/`, testes, lockfiles e fontes/configuração do Tailwind para manutenção.
- Mantidos `.env` e o ambiente local; nenhum segredo foi documentado aqui.
- A análise integrada é suficiente para executar o sistema; a documentação de
  consultas e integração externa com Power BI foi preservada.
- Não houve reescrita de histórico, commit, push ou publicação nesta sessão.

## Mapa dos arquivos de implementação

| Arquivo | Responsabilidade |
| --- | --- |
| src/sis_questionario/__init__.py | Entry points dos dois comandos que iniciam o servidor |
| src/sis_questionario/setup_db.py | Preparação administrativa do PostgreSQL |
| src/sis_questionario/banco.sql | Estrutura e migrações idempotentes |
| src/sis_questionario/app.py | Factory, fluxo do participante e conclusão |
| src/sis_questionario/bd_exec.py | Persistência, agregação e importação/exportação |
| src/sis_questionario/admin.py | Autenticação, páginas e endpoints administrativos |
| src/sis_questionario/perfis.py | Classificação e desempate |
| src/sis_questionario/perfil_v1.json | Pesos das 120 alternativas |
| src/sis_questionario/questionario_json.py | Leitura e validação do formato v1 |
| src/sis_questionario/exportacao.py | PDF, CSV e JSON dos gráficos |
| src/sis_questionario/static/js/admin.js | Gráficos, filtros, ordenação e painel de exportação |
| src/sis_questionario/static/js/admin_questionarios.js | Busca, diálogos e transferência de JSON |
| src/sis_questionario/static/css/admin.css | Estilos administrativos |
| src/sis_questionario/templates/admin*.html | Páginas, navegação e login administrativo |
| src/sis_questionario/templates/concluido.html | Devolutiva do participante |

Endpoints de dados relevantes, todos prefixados por `/admin`:

| Método e caminho | Uso |
| --- | --- |
| POST /api/results | Contagens e gráficos, incluindo filtros de perfis |
| POST /api/settings | Habilitar/desabilitar devolutiva |
| POST /api/export | Arquivo PDF, CSV ou JSON dos gráficos |
| POST /api/questionnaires/import | Upload multipart, campo file |
| GET /api/questionnaires/{id}/export | Download JSON da estrutura |

## Verificação realizada

Última suíte completa: **52 testes passaram**, usando PostgreSQL local e schemas
temporários isolados. O servidor foi acessado com os padrões locais de
desenvolvimento; não registrar credenciais reais de outros ambientes neste arquivo.

```powershell
$env:TEST_DATABASE_URL = 'postgresql://postgres:postgres@localhost:5432/postgres'
uv run python -m unittest discover -s tests -v
```

Os testes de integração são ignorados se `TEST_DATABASE_URL` não estiver definido.
Há testes de acesso administrativo, filtros, resultados e privacidade, regras e
desempates, JSON e reversão de importação, população fictícia, exportação e startup.
Os testes de startup verificam banco novo vazio, carga explícita idempotente,
preservação de respostas e migração de identificadores históricos.

Também passaram verificações de sintaxe dos dois arquivos JS. Foram executadas
checagens em Node com DOM simulado para seleção de exportação e para posicionar
rótulos de pizzas com 1, 2, 8 e 30 fatias. Não houve validação visual em navegador;
não tratar testes de sintaxe ou DOM simulado como prova de layout visual.

`uv sync --offline` foi executado e confirmou o registro dos três entry points.
O uv emitiu aviso de diferença entre sua própria versão e o intervalo de
`uv_build` no pyproject; a instalação concluiu normalmente. Não foi alterado esse
intervalo nesta sessão.

## Pendências e cuidados para retomar

1. **Excluir questionário ainda não foi implementado.** A janela explica a futura
   remoção de perguntas, alternativas, envios e respostas, mas a confirmação está
   desabilitada. Não há endpoint de exclusão. Planejar transação e autorização
   antes de conectar essa ação destrutiva.
2. Não há edição de perguntas ou controle de status ativo/inativo pela interface.
   O status é definido no JSON antes da importação ou alterado administrativamente
   no banco. Não confundir com o controle de exibição de resultado já funcional.
3. Não há suporte genérico a novos classificadores via JSON. O contrato v1 aceita
   somente questionários sem algoritmo ou com o classificador de Perfil existente.
4. Validar visualmente responsividade, modais, legendas longas, pizzas com muitas
   fatias e PDFs reais se a próxima tarefa depender de acabamento visual.
5. Configurações atuais do banco do usuário não foram auditadas. Os testes usaram
   schemas temporários; a existência dos testes não comprova que uma instalação
   específica já recebeu as migrações. Os comandos de startup as aplicam.
6. Dados reais não devem ser apagados para simular o modo limpo. Para testes
   manuais vazios, escolher um banco de desenvolvimento novo via `DB_NAME`.
7. Para conta restrita, a participação usa SELECT/INSERT e sequências. O admin
   de devolutiva também precisa de UPDATE nas colunas exibir_resultado e documento.
8. Não remover testes ou fontes de CSS apenas por não serem dependências de runtime:
   foram preservados explicitamente no plano de manutenção aprovado.
9. `pyproject.toml` ainda descreve análise no Power BI; a interface integrada está
   implementada e o relatório binário foi removido. É apenas uma descrição antiga.
10. Abas antigas do IDE ou arquivos em Downloads podem usar nomes/formatos antigos.
    Não recriar arquivos renomeados com base apenas nas abas abertas.

## Roteiro curto para outra IA

1. Ler este arquivo e o README; verificar alterações locais antes de editar.
2. Consultar `pyproject.toml`, `banco.sql` e o módulo da funcionalidade solicitada.
3. Preservar `.env`, os dados existentes e a pasta `docs/`.
4. Usar `uv run sis-questionario` para modo sem carga automática ou
   `uv run sis-questionario-perfil` para disponibilizar o Perfil.
5. Executar os testes pertinentes com banco de teste isolado, nunca limpar o banco real.
6. Atualizar este registro caso o estado funcional ou as decisões mudem.
