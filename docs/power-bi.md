# Análise com as tabelas do banco

Conecte o Power BI ao PostgreSQL usando o host, a porta e o banco do `.env`
(padrão: `localhost:5432`, banco `mydatabase`), usuário `client-app` e a senha
da sua configuração local. Importe as seis tabelas:
`alunos`, `questionarios`, `perguntas`, `opcoes`, `envios` e `respostas`.
Não há views ou tabelas analíticas adicionais.

## Relacionamentos

Use este mapa com filtro em uma direção, do lado 1 para o lado muitos:

| Lado 1 | Lado muitos |
|---|---|
| `alunos[id_aluno]` | `envios[id_aluno]` |
| `questionarios[id_questionario]` | `envios[id_questionario]` |
| `envios[id_envio]` | `respostas[id_envio]` |
| `perguntas[id_pergunta]` | `opcoes[id_pergunta]` |
| `opcoes[id_opcao]` | `respostas[id_opcao]` |

Confira os relacionamentos automáticos: para este modelo, mantenha somente
os cinco acima ativos. Não ative também `questionarios → perguntas` ou
`perguntas → respostas`, pois criariam caminhos de filtro duplicados.
As respectivas colunas continuam no banco para o funcionamento do aplicativo.

## Medidas básicas

```dax
Total de envios = COUNTROWS(envios)

Total de respostas = COUNTROWS(respostas)

Participantes = DISTINCTCOUNT(envios[id_aluno])

Envios por resposta = DISTINCTCOUNT(respostas[id_envio])
```

Use `perguntas[enunciado]` para selecionar a pergunta,
`opcoes[texto]` nas categorias do gráfico e `Total de respostas` nos valores.
Os filtros de pergunta e opção atingem `respostas`, mas não retornam a `envios`.
Para contar envios com uma determinada escolha, use `Envios por resposta`.
Um formulário com 11 perguntas corresponde a um envio e 11 respostas.

Use `envios[data_envio]` para filtrar o período. A coluna PostgreSQL preserva
o fuso horário; para gerar uma data local em SQL, use
`(data_envio AT TIME ZONE 'America/Sao_Paulo')::date`.

As [consultas SQL de exemplo](consultas.md) mostram como contar envios,
listar respostas com os nomes e contar escolhas por alternativa.
