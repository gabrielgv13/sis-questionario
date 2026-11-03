# Formato JSON de questionário — versão 1

Para criar um arquivo novo, use o [template](questionario.template.json).
Para gerar questionários com IA, consulte o [guia com prompt pronto](criar-questionario-com-ia.md).

O gerenciamento importa arquivos `.json` UTF-8 de até 1 MiB. O documento é
armazenado integralmente como estrutura JSONB em `questionarios.documento`.
Espaçamento, BOM e ordem das chaves do arquivo não são preservados pelo JSONB;
a ordem das perguntas e das alternativas é preservada. A importação cria também
as linhas de `perguntas` e `opcoes`, na mesma transação.

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
- `algoritmo`: `null` ou `"perfil_v1"`. Para habilitar a devolutiva,
  um algoritmo suportado é obrigatório.

O [JSON Schema](questionario.schema.json) descreve o formato. O servidor também
verifica duplicatas desconsiderando espaços nas extremidades e a compatibilidade
com o classificador. Chaves JSON repetidas e números especiais são rejeitados.

## Questionário de Perfil

O arquivo [questionario_perfil.json](questionario_perfil.json) é o exemplo completo
no formato v1. O classificador é referenciado pelo nome `perfil_v1`; seus
pesos continuam versionados no código da aplicação. Não são importadas funções
ou regras executáveis. Para esse algoritmo, as perguntas e alternativas precisam
corresponder exatamente aos textos esperados; podem estar em outra ordem.

O arquivo interno `src/sis_questionario/perguntas.json` permanece como fonte da
carga opcional; o comando `uv run sis-questionario-perfil` o converte para o
documento v1 ao cadastrar o Perfil. `uv run sis-questionario` inicia sem essa carga.
Para importar manualmente, use o exemplo completo ou um arquivo exportado pelo
gerenciamento, em vez dessa lista interna.

## Importação, exportação e atualização

Em **Gerenciar questionários**, escolha **Importar questionário**, selecione
o arquivo e confirme. Códigos existentes geram um erro sem sobrescrever dados.
Para duplicar um questionário exportado, altere seu `codigo` antes de importar.
Não há perguntas, alternativas ou documentos parcialmente salvos se a operação
falhar. Questionários importados com `ativo: false` aparecem no gerenciamento,
mas não ficam disponíveis aos participantes.

**Exportar JSON** baixa a estrutura e as configurações atuais sem incluir envios
ou respostas. A configuração da devolutiva atualiza também o JSONB salvo.
Importação e exportação exigem sessão administrativa; a importação exige token
CSRF. A exclusão continua desabilitada nesta etapa.

Em bancos existentes, execute `uv run sis-questionario-db` antes de iniciar a
versão atualizada. A migração cria `documento` e preenche documentos ausentes
usando os dados já cadastrados, sem recriar perguntas ou remover respostas.
Com uma conta restrita, o controle de devolutiva precisa de
`UPDATE (exibir_resultado, documento)` em `questionarios`.
