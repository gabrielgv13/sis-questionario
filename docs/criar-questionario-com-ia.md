# Criar questionários com inteligência artificial

Envie à IA o [template JSON](questionario.template.json) e as instruções abaixo.
Informe o tema, o objetivo, o público e a quantidade desejada de perguntas.
O [JSON Schema](questionario.schema.json) pode acompanhar esses arquivos para
complementar a validação estrutural.

## Prompt para copiar

```text
Crie um questionário importável no SIS Questionário, usando o template JSON anexo.

Tema: [descreva o tema]
Objetivo: [descreva o que deseja conhecer pelas respostas]
Público: [descreva o público e o nível de linguagem]
Quantidade de perguntas: [informe de 1 a 100]
Alternativas por pergunta: [informe de 2 a 100]
Disponibilizar aos participantes ao importar: [sim ou não]

Requisitos do arquivo:
- Retorne somente um objeto JSON válido, sem Markdown, comentários ou explicações.
- Substitua todos os textos de exemplo. Não inclua instruções dentro do JSON.
- Mantenha exatamente os campos do template; não acrescente campos extras.
- schema_version deve ser o inteiro 1.
- codigo deve identificar o questionário: use de 1 a 80 caracteres, começando
  com letra minúscula de a a z ou número. Nos demais caracteres, use somente
  letras minúsculas sem acentos, números, hífen ou sublinhado. Não use espaços.
  O código precisa ser diferente dos questionários já cadastrados.
- titulo deve ser um texto não vazio com até 300 caracteres.
- ativo deve ser true se o questionário deve ficar disponível aos participantes
  ao importar; caso contrário, false. Não use strings "true" ou "false".
- Para um questionário novo, mantenha algoritmo: null e exibir_resultado: false.
  O sistema não aceita classificadores novos, pontuações ou resultados definidos
  livremente neste arquivo. Não reutilize perfil_v1 para perguntas novas.
- perguntas deve ter de 1 a 100 objetos, cada um com somente enunciado e opcoes.
- Cada enunciado deve ser distinto, não vazio e ter até 2.000 caracteres.
- opcoes deve ser uma lista de 2 a 100 textos não vazios, distintos dentro da
  pergunta, com até 500 caracteres por alternativa.
- Cada pergunta permite escolher somente uma alternativa. Não crie perguntas
  abertas, respostas múltiplas, condicionais ou campos de resposta correta.
- Faça perguntas claras e neutras, adequadas ao público. Evite alternativas
  sobrepostas; quando pertinente, inclua "Outro" ou "Não se aplica".
- A ordem nos arrays define a ordem de apresentação. Não inclua IDs ou ordem.
- Não inclua respostas de participantes, dados pessoais, credenciais ou pesos.
- Não use chaves duplicadas, vírgulas finais, NaN ou Infinity.
- O resultado deve poder ser salvo como .json UTF-8 e ter no máximo 1 MiB.

Antes de responder, confira os campos, tipos, limites e unicidade das perguntas
e alternativas. Entregue somente o JSON final.
```

## Usar o resultado

Salve a resposta em um arquivo `.json`, revise as perguntas e importe em
**Admin → Gerenciar questionários → Importar questionário**. O servidor valida
o arquivo antes de salvar qualquer dado. Importar não sobrescreve questionários:
para criar outra versão ou uma cópia, use um novo `codigo`.

O template usa `ativo: false` para representar um rascunho. Para disponibilizar
o questionário aos participantes, defina `ativo: true` antes de importar; a
interface atual não tem um controle para alterar esse status depois.

Para reproduzir o Questionário de Perfil com sua classificação existente, use
[questionario_perfil.json](questionario_perfil.json). Alterar suas perguntas ou
alternativas exige revisar e implementar outro classificador na aplicação.
