# Consultas para analisar o banco

```sql
-- Quantidade de preenchimentos por questionário, incluindo questionários sem envios.
SELECT q.id_questionario, q.titulo, COUNT(e.id_envio) AS total_envios
FROM questionarios q
LEFT JOIN envios e ON e.id_questionario = q.id_questionario
GROUP BY q.id_questionario, q.titulo
ORDER BY q.titulo;

-- Respostas com seus nomes: uma linha por pergunta respondida em um envio.
SELECT e.id_envio, a.nome AS aluno, q.titulo AS questionario,
       e.data_envio AT TIME ZONE 'America/Sao_Paulo' AS data_envio,
       p.enunciado AS pergunta, o.texto AS resposta
FROM respostas r
JOIN envios e ON e.id_envio = r.id_envio
JOIN alunos a ON a.id_aluno = e.id_aluno
JOIN questionarios q ON q.id_questionario = e.id_questionario
JOIN perguntas p ON p.id_pergunta = r.id_pergunta
JOIN opcoes o ON o.id_opcao = r.id_opcao
ORDER BY e.id_envio, p.ordem;

-- Escolhas por alternativa, incluindo alternativas que ainda não foram escolhidas.
SELECT q.titulo AS questionario, p.enunciado AS pergunta, o.texto AS alternativa,
       COUNT(r.id_resposta) AS total_respostas
FROM questionarios q
JOIN perguntas p ON p.id_questionario = q.id_questionario
JOIN opcoes o ON o.id_pergunta = p.id_pergunta
LEFT JOIN respostas r ON r.id_pergunta = p.id_pergunta AND r.id_opcao = o.id_opcao
GROUP BY q.id_questionario, q.titulo, p.id_pergunta, p.enunciado, p.ordem,
         o.id_opcao, o.texto, o.ordem
ORDER BY q.titulo, p.ordem, o.ordem;
```
