# Formato JSON de questionário — versão 1

Para criar um arquivo novo, use o [template](questionario.template.json).
Para definir a classificação, use também o [template de algoritmo](perfil.template.json).
Para gerar questionários com IA, consulte o [guia com prompt pronto](criar-questionario-com-ia.md).

O gerenciamento importa arquivos `.json` UTF-8 de até 1 MiB. O documento é
armazenado integralmente como estrutura JSONB em `questionarios.documento`.
Espaçamento, BOM e ordem das chaves do arquivo não são preservados pelo JSONB;
a ordem das perguntas e das alternativas é preservada. A importação cria também
as linhas de `perguntas` e `opcoes`, na mesma transação. Quando houver algoritmo,
seu segundo arquivo também será validado e salvo em `questionarios.regras_algoritmo`.

Exemplo mínimo:

```json
{
  "schema_version": 1,
  "codigo": "satisfacao",
  "titulo": "Pesquisa de satisfação",
  "ativo": true,
  "algoritmo": null,
  "exibir_resultado": false,
  "perguntas": [
    {
      "enunciado": "Como foi sua experiência?",
      "opcoes": ["Boa", "Regular", "Ruim"]
    }
  ]
}
```

Todos os campos acima são obrigatórios; campos extras não são aceitos.
Não inclua IDs do banco, respostas, participantes, credenciais ou resultados.
Cada pergunta permite escolher uma alternativa. A posição nos arrays determina
a ordem de apresentação, sem exigir o campo `ordem`.

## Validação

- `schema_version`: inteiro `1`.
- `codigo`: 1 a 80 caracteres, começando com letra minúscula ou número;
  demais caracteres podem ser letras minúsculas, números, `_` e `-`.
- `titulo`: texto não vazio com até 300 caracteres.
- `ativo` e `exibir_resultado`: booleanos JSON (`true` ou `false`).
- `perguntas`: 1 a 100 perguntas com enunciados distintos e não vazios,
  de até 2.000 caracteres cada.
- `opcoes`: 2 a 100 textos distintos e não vazios, de até 500 caracteres cada.
- `algoritmo`: `null` ou um identificador não vazio de até 80 caracteres.
  Um identificador exige um arquivo JSON de algoritmo separado, inclusive
  quando o identificador for `perfil_v1`. Para habilitar a devolutiva,
  um algoritmo validado é obrigatório.

O [JSON Schema](questionario.schema.json) descreve o formato. O servidor também
verifica duplicatas desconsiderando espaços nas extremidades e a compatibilidade
com o classificador. Chaves JSON repetidas e números especiais são rejeitados.

## Questionário de Perfil

O arquivo [questionario_perfil.json](questionario_perfil.json) é o exemplo completo
no formato v1. Ao selecioná-lo, o formulário solicita um segundo arquivo:
[`src/sis_questionario/perfil_v1.json`](../src/sis_questionario/perfil_v1.json).
Seu campo `version` corresponde ao identificador `perfil_v1` do questionário.
O arquivo é obrigatório na importação; o servidor não reutiliza regras internas
com o mesmo nome. As regras ficam vinculadas a esse questionário no banco.

## Arquivo de algoritmo

O [perfil.template.json](perfil.template.json) usa as mesmas perguntas e
alternativas do template de questionário. Copie o valor de `version` para
`algoritmo` no questionário para usar os dois juntos. Cada arquivo aceita até
1 MiB e deve ser JSON UTF-8, sem chaves repetidas.

- `version`: identificador igual ao campo `algoritmo` do questionário.
- `profiles`: objeto de 1 a 32 identificadores de perfil e seus nomes de exibição.
  Use letras minúsculas, números e `_` nos identificadores, começando por letra,
  com até 80 caracteres. Nomes têm até 300 caracteres. `misto` e
  `sem_classificacao` são reservados.
- `questions`: todas as perguntas do questionário, uma vez cada. `title` deve
  ser exatamente o `enunciado`. `options` deve conter exatamente os textos das
  alternativas, inclusive acentos e espaços. A ordem pode ser diferente.
- Cada alternativa contém `add` e `subtract`, ambos com todos os perfis.
  `add` aceita inteiros de 0 a 1.000.000. `subtract` aceita inteiros de
  -1.000.000 a 0: uma subtração de cinco pontos deve ser escrita como `-5`.

O cálculo soma `add + subtract` das respostas escolhidas para cada perfil.
Vence o maior total; em empate, vence quem tiver mais respostas com `add: 20`.
Persistindo o empate, o resultado é `misto`. O servidor verifica a cobertura
completa das perguntas, alternativas e perfis, os tipos/limites numéricos e
executa dois cálculos de teste antes de salvar. Não são importadas funções ou
código executável; essa validação não atesta a qualidade científica dos pesos.

Questionários antigos de `perfil_v1` sem regras salvas continuam funcionando
com as regras legadas. Novas importações sempre exigem o segundo arquivo.

O arquivo interno `src/sis_questionario/perguntas.json` permanece como fonte da
carga opcional; o comando `uv run sis-questionario-perfil` o converte para o
documento v1 ao cadastrar o Perfil. `uv run sis-questionario` inicia sem essa carga.
Para importar manualmente, use o exemplo completo ou um arquivo exportado pelo
gerenciamento, em vez dessa lista interna.

## Importação, exportação e atualização

Em **Gerenciar questionários**, escolha **Importar questionário**, selecione
o arquivo e, se o campo `algoritmo` estiver preenchido, selecione também o arquivo
solicitado. A confirmação fica bloqueada até a seleção dos arquivos necessários.
O servidor valida os dois mesmo quando a API é chamada diretamente.
Códigos existentes geram um erro sem sobrescrever dados.
Para duplicar um questionário exportado, altere seu `codigo` antes de importar.
Não há perguntas, alternativas ou documentos parcialmente salvos se a operação
falhar. Questionários importados com `ativo: false` aparecem no gerenciamento,
mas não ficam disponíveis aos participantes.

**Exportar JSON** baixa a estrutura e as configurações atuais sem incluir envios
ou respostas. **Exportar algoritmo** baixa separadamente os pesos cadastrados,
para uma nova importação junto com o questionário. A configuração da devolutiva
atualiza também o JSONB salvo.
Importação e exportação exigem sessão administrativa; a importação exige token
CSRF. A exclusão continua desabilitada nesta etapa.

Em bancos existentes, execute `uv run sis-questionario-db` antes de iniciar a
versão atualizada. A migração cria `documento` e `regras_algoritmo` e preenche documentos ausentes
usando os dados já cadastrados, sem recriar perguntas ou remover respostas.
Com uma conta restrita, o controle de devolutiva precisa de
`UPDATE (exibir_resultado, documento)` em `questionarios`.
