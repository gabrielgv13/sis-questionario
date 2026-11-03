-- Dados ficticios para demonstrar os graficos e filtros do painel.
-- Execute no banco configurado em DB_NAME, apos executar banco.sql pelo pgAdmin.
-- Cria o questionario de perfil se necessario e 120 participantes ficticios.
-- Pode ser reexecutado: nao duplica os mesmos envios nem altera respostas existentes.
-- Inclui resultado JSONB do perfil_v1, calculado pelas regras da aplicacao.
-- Preenche resultados ausentes apenas nos envios ficticios compativeis deste script.
BEGIN;
SET LOCAL search_path TO public;

CREATE TEMP TABLE perfil_perguntas_exemplo (
    ordem INTEGER PRIMARY KEY,
    enunciado TEXT NOT NULL,
    alternativas TEXT[] NOT NULL
) ON COMMIT DROP;

INSERT INTO perfil_perguntas_exemplo (ordem, enunciado, alternativas) VALUES
    (1, 'Qual das matérias escolares abaixo você mais gosta de estudar e/ou tem mais interesse em aprender?', ARRAY['Biologia', 'Sociologia', 'Filosofia', 'Geografia', 'Física', 'Química', 'Matemática', 'Inglês', 'Artes', 'Português', 'Educação Física']),
    (2, 'Pensando no último livro que você leu, qual dos gêneros abaixo melhor descreve a história?', ARRAY['Ação', 'Aventura', 'Terror', 'Romance', 'Ficção Científica', 'Thriller', 'Suspense', 'Comédia']),
    (3, 'Quando você escolhe um filme para assistir no seu tempo livre, qual dos gêneros abaixo costuma preferir?', ARRAY['Ação', 'Aventura', 'Terror', 'Romance', 'Ficção Científica', 'Thriller', 'Suspense', 'Comédia']),
    (4, 'Qual dos estilos musicais abaixo você mais gosta de ouvir no dia a dia?', ARRAY['Samba', 'Bossa Nova', 'Gospel', 'Sertanejo', 'Eletrônica', 'Rock', 'Punk', 'Metal', 'Funk', 'Disco', 'Kpop']),
    (5, 'Entre as opções abaixo, que tipo de conteúdo você costuma buscar com mais frequência ao pesquisar na internet?', ARRAY['Tutoriais de estudo', 'Curiosidades', 'Notícias e atualidades', 'Ciência e tecnologia', 'Programação e informática', 'Jogos e dicas para jogar', 'Filmes, séries e animações', 'Música e artistas', 'Esportes e atividades físicas', 'Saúde e bem-estar', 'Receitas e culinária', 'Moda e beleza', 'Arte, desenho e fotografia', 'Livros e literatura', 'Viagens e lugares para conhecer', 'Animais e cuidados com pets', 'Profissões, cursos e mercado de trabalho', 'Produtos, preços e compras', 'Tutoriais de tarefas do dia a dia', 'Humor e memes', 'Outros assuntos']),
    (6, 'Qual das cores ou dos grupos de cores abaixo é o seu favorito, pensando nos seus gostos pessoais?', ARRAY['Preto', 'Branco', 'Azul', 'Vermelho', 'Verde', 'Amarelo', 'Laranja', 'Rosa', 'Roxo', 'Marrom', 'Cinza', 'Cores Pasteis']),
    (7, 'Em situações sociais, você se identifica mais como extrovertido, buscando conversar e interagir com outras pessoas, ou introvertido, preferindo momentos mais reservados e interações em grupos menores?', ARRAY['Extrovertido', 'Introvertido']),
    (8, 'Pensando na profissão que você sonha em exercer no futuro, em qual das áreas abaixo você mais gostaria de trabalhar?', ARRAY['Saúde', 'Veterinário', 'Educação', 'Metalúrgica', 'Elétrica', 'Automação', 'Redes de Computadores', 'Desenvolvimento de Software', 'Administração', 'Contabilidade', 'Pesquisa Científica', 'Segurança Pública', 'Serviços de Emergência (Bombeiros, Para-Médicos…)', 'Têxtil', 'Moda', 'Artes Visuais (Pintura, Desenho…)', 'Artes Cênicas (De cena: Dança, Teatro…)', 'Marketing', 'Design']),
    (9, 'Entre os alimentos, pratos e bebidas abaixo, qual você escolheria como seu favorito, considerando tanto as opções doces quanto as salgadas?', ARRAY['Brigadeiro', 'Sorvete', 'Milkshake', 'Pizza Doce', 'Pipoca Doce', 'Churros', 'Frutas', 'Salgadinho de festa', 'Salgadinho', 'Prato popular (Arroz e Feijão)', 'Macarronada', 'Strogonoff', 'Pizza', 'Hambúrguer', 'Sushi', 'Pipoca Salgada', 'Feijoada', 'Pão de Queijo']),
    (10, 'Qual dos animais abaixo você mais gostaria de ter como animal de estimação, independentemente de já ter um em casa?', ARRAY['Cachorro', 'Gato', 'Pássaro', 'Roedor', 'Réptil', 'Peixe', 'De Fazenda (Porco, Cabra, Bezerro)', 'Lebre / Coelho']),
    (11, 'Se você pudesse escolher um destes jogos para se divertir no seu tempo livre, qual preferiria jogar: The King Of Fighters, de luta, ou FIFA 20, de futebol?', ARRAY['The King Of Fighters', 'FIFA 20']);

INSERT INTO questionarios (codigo, titulo, algoritmo, exibir_resultado)
VALUES ('perfil', 'Questionário de perfil', 'perfil_v1', TRUE)
ON CONFLICT (codigo) DO NOTHING;

-- Preserva a escolha de exibir ou ocultar a devolutiva feita no admin.
UPDATE questionarios SET algoritmo = 'perfil_v1'
WHERE codigo = 'perfil' AND algoritmo IS NULL;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM questionarios
               WHERE codigo = 'perfil' AND algoritmo <> 'perfil_v1') THEN
        RAISE EXCEPTION 'O questionario perfil usa outro algoritmo. Operacao cancelada.';
    END IF;
END $$;

INSERT INTO perguntas (id_questionario, enunciado, ordem)
SELECT q.id_questionario, f.enunciado, f.ordem
FROM questionarios q CROSS JOIN perfil_perguntas_exemplo f
WHERE q.codigo = 'perfil'
ON CONFLICT (id_questionario, ordem) DO NOTHING;

INSERT INTO opcoes (id_pergunta, texto, ordem)
SELECT p.id_pergunta, a.texto, a.ordem
FROM questionarios q
JOIN perguntas p USING (id_questionario)
JOIN perfil_perguntas_exemplo f ON f.ordem = p.ordem
CROSS JOIN LATERAL unnest(f.alternativas) WITH ORDINALITY a(texto, ordem)
WHERE q.codigo = 'perfil'
ON CONFLICT (id_pergunta, ordem) DO NOTHING;

-- Nao associa respostas por posicao se o questionario existente foi modificado.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM questionarios q
        JOIN perguntas p USING (id_questionario)
        FULL JOIN perfil_perguntas_exemplo f ON f.ordem = p.ordem AND q.codigo = 'perfil'
        WHERE (q.codigo = 'perfil' OR f.ordem IS NOT NULL)
          AND (p.id_pergunta IS NULL OR f.ordem IS NULL OR p.enunciado <> f.enunciado
               OR ARRAY(SELECT o.texto FROM opcoes o WHERE o.id_pergunta = p.id_pergunta ORDER BY o.ordem) <> f.alternativas)
    ) THEN
        RAISE EXCEPTION 'O questionario perfil difere de perguntas.json. Nenhum dado foi gravado.';
    END IF;
END $$;

CREATE TEMP TABLE perfil_envios_exemplo (
    numero INTEGER PRIMARY KEY,
    escolhas INTEGER[] NOT NULL,
    resultado JSONB NOT NULL
) ON COMMIT DROP;

-- Cada linha e um participante; cada numero no array indica a ordem da
-- alternativa escolhida em uma das 11 perguntas. Os perfis possuem correlacoes
-- ficticias (ex.: interesse por tecnologia, artes ou esportes), com variacao.
-- Resultados versionados gerados de src/sis_questionario/perfil_v1.json.
INSERT INTO perfil_envios_exemplo (numero, escolhas, resultado) VALUES
    (1, ARRAY[1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], '{"version":"perfil_v1","scores":{"politico":115,"identitario":115,"tecnologico":25,"esportes":140,"otaku":75},"strong":{"politico":4,"identitario":4,"tecnologico":1,"esportes":6,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (2, ARRAY[2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2], '{"version":"perfil_v1","scores":{"politico":115,"identitario":105,"tecnologico":90,"esportes":115,"otaku":100},"strong":{"politico":3,"identitario":3,"tecnologico":2,"esportes":4,"otaku":3},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (3, ARRAY[3, 3, 3, 3, 3, 3, 2, 3, 3, 3, 2], '{"version":"perfil_v1","scores":{"politico":85,"identitario":145,"tecnologico":75,"esportes":40,"otaku":100},"strong":{"politico":2,"identitario":5,"tecnologico":1,"esportes":2,"otaku":3},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (4, ARRAY[4, 4, 4, 4, 4, 4, 2, 4, 4, 4, 2], '{"version":"perfil_v1","scores":{"politico":105,"identitario":75,"tecnologico":85,"esportes":60,"otaku":105},"strong":{"politico":3,"identitario":1,"tecnologico":3,"esportes":3,"otaku":4},"winners":["otaku"],"category":"otaku"}'::jsonb),
    (5, ARRAY[5, 5, 5, 5, 5, 5, 2, 5, 5, 5, 2], '{"version":"perfil_v1","scores":{"politico":10,"identitario":35,"tecnologico":145,"esportes":5,"otaku":70},"strong":{"politico":0,"identitario":1,"tecnologico":6,"esportes":1,"otaku":2},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (6, ARRAY[6, 6, 6, 6, 6, 6, 2, 6, 6, 6, 1], '{"version":"perfil_v1","scores":{"politico":30,"identitario":105,"tecnologico":95,"esportes":25,"otaku":115},"strong":{"politico":0,"identitario":4,"tecnologico":3,"esportes":1,"otaku":4},"winners":["otaku"],"category":"otaku"}'::jsonb),
    (7, ARRAY[7, 7, 7, 7, 7, 7, 1, 7, 7, 7, 2], '{"version":"perfil_v1","scores":{"politico":95,"identitario":105,"tecnologico":75,"esportes":90,"otaku":45},"strong":{"politico":3,"identitario":3,"tecnologico":2,"esportes":3,"otaku":1},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (8, ARRAY[8, 8, 8, 8, 8, 8, 2, 8, 8, 8, 2], '{"version":"perfil_v1","scores":{"politico":55,"identitario":115,"tecnologico":115,"esportes":45,"otaku":110},"strong":{"politico":0,"identitario":3,"tecnologico":3,"esportes":1,"otaku":3},"winners":["identitario","tecnologico"],"category":"misto"}'::jsonb),
    (9, ARRAY[9, 5, 5, 9, 9, 9, 2, 9, 9, 2, 2], '{"version":"perfil_v1","scores":{"politico":65,"identitario":85,"tecnologico":105,"esportes":55,"otaku":90},"strong":{"politico":2,"identitario":3,"tecnologico":4,"esportes":3,"otaku":2},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (10, ARRAY[10, 4, 4, 10, 10, 10, 2, 10, 10, 2, 1], '{"version":"perfil_v1","scores":{"politico":105,"identitario":135,"tecnologico":90,"esportes":50,"otaku":80},"strong":{"politico":4,"identitario":5,"tecnologico":3,"esportes":2,"otaku":3},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (11, ARRAY[11, 6, 1, 11, 11, 11, 1, 11, 11, 1, 2], '{"version":"perfil_v1","scores":{"politico":95,"identitario":135,"tecnologico":20,"esportes":125,"otaku":60},"strong":{"politico":3,"identitario":5,"tecnologico":0,"esportes":6,"otaku":2},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (12, ARRAY[4, 8, 3, 3, 12, 12, 2, 12, 12, 1, 2], '{"version":"perfil_v1","scores":{"politico":85,"identitario":105,"tecnologico":65,"esportes":95,"otaku":75},"strong":{"politico":2,"identitario":3,"tecnologico":1,"esportes":4,"otaku":2},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (13, ARRAY[7, 5, 5, 5, 13, 3, 2, 13, 13, 3, 1], '{"version":"perfil_v1","scores":{"politico":65,"identitario":75,"tecnologico":130,"esportes":10,"otaku":75},"strong":{"politico":2,"identitario":3,"tecnologico":5,"esportes":1,"otaku":1},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (14, ARRAY[9, 2, 1, 6, 14, 9, 2, 14, 14, 2, 1], '{"version":"perfil_v1","scores":{"politico":95,"identitario":145,"tecnologico":90,"esportes":50,"otaku":155},"strong":{"politico":3,"identitario":6,"tecnologico":2,"esportes":2,"otaku":5},"winners":["otaku"],"category":"otaku"}'::jsonb),
    (15, ARRAY[11, 8, 8, 5, 15, 4, 1, 15, 15, 1, 2], '{"version":"perfil_v1","scores":{"politico":75,"identitario":115,"tecnologico":70,"esportes":125,"otaku":55},"strong":{"politico":1,"identitario":3,"tecnologico":1,"esportes":5,"otaku":0},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (16, ARRAY[9, 3, 2, 3, 16, 5, 1, 16, 16, 1, 2], '{"version":"perfil_v1","scores":{"politico":105,"identitario":135,"tecnologico":65,"esportes":100,"otaku":115},"strong":{"politico":3,"identitario":5,"tecnologico":0,"esportes":4,"otaku":4},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (17, ARRAY[7, 5, 6, 7, 17, 6, 2, 17, 17, 4, 1], '{"version":"perfil_v1","scores":{"politico":55,"identitario":125,"tecnologico":95,"esportes":20,"otaku":115},"strong":{"politico":2,"identitario":6,"tecnologico":4,"esportes":2,"otaku":4},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (18, ARRAY[6, 4, 4, 3, 18, 9, 1, 18, 18, 2, 1], '{"version":"perfil_v1","scores":{"politico":110,"identitario":115,"tecnologico":65,"esportes":90,"otaku":100},"strong":{"politico":3,"identitario":3,"tecnologico":1,"esportes":2,"otaku":2},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (19, ARRAY[2, 1, 5, 4, 19, 11, 1, 19, 2, 7, 2], '{"version":"perfil_v1","scores":{"politico":125,"identitario":65,"tecnologico":80,"esportes":100,"otaku":65},"strong":{"politico":5,"identitario":2,"tecnologico":2,"esportes":5,"otaku":2},"winners":["politico"],"category":"politico"}'::jsonb),
    (20, ARRAY[6, 2, 2, 8, 20, 5, 1, 2, 7, 1, 2], '{"version":"perfil_v1","scores":{"politico":90,"identitario":115,"tecnologico":50,"esportes":160,"otaku":65},"strong":{"politico":3,"identitario":4,"tecnologico":0,"esportes":7,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (21, ARRAY[7, 3, 6, 5, 21, 3, 2, 8, 13, 7, 1], '{"version":"perfil_v1","scores":{"politico":45,"identitario":95,"tecnologico":105,"esportes":10,"otaku":85},"strong":{"politico":1,"identitario":4,"tecnologico":4,"esportes":1,"otaku":3},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (22, ARRAY[9, 4, 3, 6, 13, 9, 2, 16, 2, 2, 1], '{"version":"perfil_v1","scores":{"politico":95,"identitario":135,"tecnologico":80,"esportes":5,"otaku":145},"strong":{"politico":3,"identitario":5,"tecnologico":2,"esportes":0,"otaku":5},"winners":["otaku"],"category":"otaku"}'::jsonb),
    (23, ARRAY[3, 1, 1, 4, 15, 4, 1, 9, 14, 1, 2], '{"version":"perfil_v1","scores":{"politico":135,"identitario":155,"tecnologico":30,"esportes":170,"otaku":75},"strong":{"politico":4,"identitario":5,"tecnologico":0,"esportes":8,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (24, ARRAY[1, 2, 1, 5, 9, 10, 1, 2, 17, 4, 2], '{"version":"perfil_v1","scores":{"politico":75,"identitario":75,"tecnologico":45,"esportes":160,"otaku":60},"strong":{"politico":3,"identitario":3,"tecnologico":1,"esportes":8,"otaku":3},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (25, ARRAY[9, 5, 5, 5, 14, 11, 2, 8, 13, 5, 1], '{"version":"perfil_v1","scores":{"politico":35,"identitario":65,"tecnologico":135,"esportes":-25,"otaku":115},"strong":{"politico":1,"identitario":3,"tecnologico":5,"esportes":0,"otaku":4},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (26, ARRAY[9, 5, 4, 11, 13, 9, 2, 16, 18, 2, 1], '{"version":"perfil_v1","scores":{"politico":85,"identitario":125,"tecnologico":90,"esportes":-10,"otaku":125},"strong":{"politico":3,"identitario":5,"tecnologico":3,"esportes":0,"otaku":4},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (27, ARRAY[11, 1, 1, 4, 9, 8, 1, 1, 14, 1, 2], '{"version":"perfil_v1","scores":{"politico":105,"identitario":105,"tecnologico":25,"esportes":195,"otaku":75},"strong":{"politico":3,"identitario":3,"tecnologico":0,"esportes":9,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (28, ARRAY[4, 2, 4, 1, 16, 5, 1, 2, 7, 1, 2], '{"version":"perfil_v1","scores":{"politico":135,"identitario":85,"tecnologico":30,"esportes":125,"otaku":60},"strong":{"politico":5,"identitario":2,"tecnologico":0,"esportes":5,"otaku":2},"winners":["politico"],"category":"politico"}'::jsonb),
    (29, ARRAY[7, 1, 5, 5, 5, 3, 2, 8, 13, 3, 1], '{"version":"perfil_v1","scores":{"politico":45,"identitario":75,"tecnologico":150,"esportes":10,"otaku":85},"strong":{"politico":1,"identitario":3,"tecnologico":6,"esportes":1,"otaku":2},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (30, ARRAY[9, 4, 4, 6, 13, 9, 2, 16, 2, 2, 1], '{"version":"perfil_v1","scores":{"politico":115,"identitario":125,"tecnologico":75,"esportes":10,"otaku":145},"strong":{"politico":4,"identitario":4,"tecnologico":2,"esportes":0,"otaku":5},"winners":["otaku"],"category":"otaku"}'::jsonb),
    (31, ARRAY[11, 1, 4, 4, 17, 4, 2, 10, 11, 2, 1], '{"version":"perfil_v1","scores":{"politico":125,"identitario":145,"tecnologico":90,"esportes":125,"otaku":120},"strong":{"politico":4,"identitario":5,"tecnologico":3,"esportes":5,"otaku":4},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (32, ARRAY[3, 2, 7, 8, 10, 7, 1, 2, 7, 1, 2], '{"version":"perfil_v1","scores":{"politico":85,"identitario":115,"tecnologico":40,"esportes":135,"otaku":45},"strong":{"politico":2,"identitario":3,"tecnologico":0,"esportes":6,"otaku":1},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (33, ARRAY[7, 5, 5, 5, 5, 3, 2, 8, 16, 6, 1], '{"version":"perfil_v1","scores":{"politico":35,"identitario":65,"tecnologico":175,"esportes":-5,"otaku":75},"strong":{"politico":0,"identitario":2,"tecnologico":7,"esportes":0,"otaku":1},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (34, ARRAY[9, 4, 4, 6, 13, 9, 2, 16, 2, 7, 2], '{"version":"perfil_v1","scores":{"politico":125,"identitario":105,"tecnologico":55,"esportes":35,"otaku":130},"strong":{"politico":5,"identitario":3,"tecnologico":1,"esportes":2,"otaku":5},"winners":["otaku"],"category":"otaku"}'::jsonb),
    (35, ARRAY[5, 4, 1, 7, 14, 2, 1, 1, 12, 2, 2], '{"version":"perfil_v1","scores":{"politico":110,"identitario":115,"tecnologico":30,"esportes":95,"otaku":75},"strong":{"politico":4,"identitario":4,"tecnologico":1,"esportes":4,"otaku":3},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (36, ARRAY[1, 2, 2, 1, 10, 8, 1, 2, 9, 1, 1], '{"version":"perfil_v1","scores":{"politico":115,"identitario":105,"tecnologico":45,"esportes":160,"otaku":65},"strong":{"politico":4,"identitario":4,"tecnologico":0,"esportes":7,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (37, ARRAY[7, 5, 1, 5, 5, 3, 1, 8, 10, 2, 1], '{"version":"perfil_v1","scores":{"politico":75,"identitario":85,"tecnologico":150,"esportes":45,"otaku":60},"strong":{"politico":2,"identitario":3,"tecnologico":6,"esportes":2,"otaku":1},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (38, ARRAY[10, 4, 7, 6, 21, 7, 2, 12, 2, 2, 1], '{"version":"perfil_v1","scores":{"politico":105,"identitario":115,"tecnologico":60,"esportes":65,"otaku":85},"strong":{"politico":3,"identitario":3,"tecnologico":2,"esportes":1,"otaku":2},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (39, ARRAY[11, 1, 1, 9, 9, 4, 1, 1, 8, 1, 2], '{"version":"perfil_v1","scores":{"politico":115,"identitario":115,"tecnologico":10,"esportes":175,"otaku":65},"strong":{"politico":4,"identitario":4,"tecnologico":0,"esportes":8,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (40, ARRAY[8, 2, 2, 8, 10, 4, 2, 9, 7, 1, 1], '{"version":"perfil_v1","scores":{"politico":95,"identitario":165,"tecnologico":90,"esportes":105,"otaku":115},"strong":{"politico":3,"identitario":7,"tecnologico":2,"esportes":5,"otaku":4},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (41, ARRAY[7, 5, 5, 5, 5, 3, 2, 8, 13, 6, 1], '{"version":"perfil_v1","scores":{"politico":35,"identitario":65,"tecnologico":175,"esportes":-5,"otaku":75},"strong":{"politico":0,"identitario":2,"tecnologico":7,"esportes":0,"otaku":1},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (42, ARRAY[9, 4, 4, 8, 9, 12, 1, 16, 2, 2, 2], '{"version":"perfil_v1","scores":{"politico":105,"identitario":115,"tecnologico":45,"esportes":60,"otaku":95},"strong":{"politico":4,"identitario":3,"tecnologico":1,"esportes":3,"otaku":4},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (43, ARRAY[10, 1, 1, 2, 9, 6, 1, 1, 2, 1, 2], '{"version":"perfil_v1","scores":{"politico":115,"identitario":115,"tecnologico":15,"esportes":155,"otaku":65},"strong":{"politico":4,"identitario":4,"tecnologico":0,"esportes":7,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (44, ARRAY[1, 8, 1, 3, 10, 5, 1, 16, 3, 1, 1], '{"version":"perfil_v1","scores":{"politico":105,"identitario":125,"tecnologico":40,"esportes":135,"otaku":75},"strong":{"politico":3,"identitario":5,"tecnologico":0,"esportes":5,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (45, ARRAY[10, 5, 4, 7, 5, 3, 2, 8, 13, 2, 1], '{"version":"perfil_v1","scores":{"politico":75,"identitario":115,"tecnologico":115,"esportes":5,"otaku":85},"strong":{"politico":2,"identitario":4,"tecnologico":5,"esportes":0,"otaku":2},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (46, ARRAY[10, 2, 4, 4, 3, 3, 2, 14, 2, 2, 1], '{"version":"perfil_v1","scores":{"politico":125,"identitario":155,"tecnologico":75,"esportes":55,"otaku":115},"strong":{"politico":4,"identitario":5,"tecnologico":2,"esportes":2,"otaku":3},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (47, ARRAY[5, 1, 1, 4, 9, 4, 1, 1, 14, 1, 2], '{"version":"perfil_v1","scores":{"politico":100,"identitario":105,"tecnologico":40,"esportes":175,"otaku":75},"strong":{"politico":3,"identitario":3,"tecnologico":0,"esportes":8,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (48, ARRAY[1, 2, 2, 3, 10, 5, 1, 2, 7, 1, 2], '{"version":"perfil_v1","scores":{"politico":95,"identitario":105,"tecnologico":50,"esportes":185,"otaku":60},"strong":{"politico":3,"identitario":4,"tecnologico":0,"esportes":8,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (49, ARRAY[7, 5, 5, 1, 5, 3, 2, 8, 13, 2, 1], '{"version":"perfil_v1","scores":{"politico":55,"identitario":65,"tecnologico":160,"esportes":0,"otaku":75},"strong":{"politico":1,"identitario":2,"tecnologico":7,"esportes":0,"otaku":1},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (50, ARRAY[9, 4, 4, 1, 13, 9, 2, 16, 14, 2, 1], '{"version":"perfil_v1","scores":{"politico":125,"identitario":115,"tecnologico":60,"esportes":0,"otaku":135},"strong":{"politico":5,"identitario":4,"tecnologico":2,"esportes":0,"otaku":5},"winners":["otaku"],"category":"otaku"}'::jsonb),
    (51, ARRAY[6, 1, 2, 4, 16, 7, 1, 1, 14, 6, 2], '{"version":"perfil_v1","scores":{"politico":100,"identitario":115,"tecnologico":45,"esportes":175,"otaku":75},"strong":{"politico":3,"identitario":3,"tecnologico":0,"esportes":7,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (52, ARRAY[1, 2, 8, 3, 12, 5, 1, 2, 9, 1, 2], '{"version":"perfil_v1","scores":{"politico":85,"identitario":95,"tecnologico":45,"esportes":175,"otaku":50},"strong":{"politico":2,"identitario":3,"tecnologico":0,"esportes":7,"otaku":1},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (53, ARRAY[7, 5, 4, 5, 1, 3, 1, 8, 5, 2, 1], '{"version":"perfil_v1","scores":{"politico":85,"identitario":85,"tecnologico":140,"esportes":40,"otaku":70},"strong":{"politico":2,"identitario":2,"tecnologico":6,"esportes":1,"otaku":1},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (54, ARRAY[9, 8, 4, 9, 7, 9, 2, 16, 2, 7, 2], '{"version":"perfil_v1","scores":{"politico":125,"identitario":115,"tecnologico":55,"esportes":50,"otaku":130},"strong":{"politico":5,"identitario":4,"tecnologico":1,"esportes":2,"otaku":5},"winners":["otaku"],"category":"otaku"}'::jsonb),
    (55, ARRAY[11, 5, 1, 4, 9, 4, 1, 1, 18, 6, 2], '{"version":"perfil_v1","scores":{"politico":85,"identitario":85,"tecnologico":50,"esportes":160,"otaku":65},"strong":{"politico":2,"identitario":2,"tecnologico":1,"esportes":7,"otaku":1},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (56, ARRAY[1, 7, 7, 8, 10, 5, 1, 2, 17, 1, 1], '{"version":"perfil_v1","scores":{"politico":65,"identitario":95,"tecnologico":40,"esportes":135,"otaku":35},"strong":{"politico":1,"identitario":3,"tecnologico":0,"esportes":5,"otaku":0},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (57, ARRAY[7, 5, 5, 5, 5, 3, 2, 16, 13, 7, 1], '{"version":"perfil_v1","scores":{"politico":65,"identitario":75,"tecnologico":145,"esportes":5,"otaku":85},"strong":{"politico":2,"identitario":3,"tecnologico":6,"esportes":1,"otaku":2},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (58, ARRAY[9, 4, 4, 6, 13, 9, 2, 16, 2, 5, 1], '{"version":"perfil_v1","scores":{"politico":105,"identitario":115,"tecnologico":55,"esportes":0,"otaku":155},"strong":{"politico":4,"identitario":4,"tecnologico":1,"esportes":0,"otaku":6},"winners":["otaku"],"category":"otaku"}'::jsonb),
    (59, ARRAY[11, 1, 2, 4, 9, 4, 1, 12, 14, 7, 2], '{"version":"perfil_v1","scores":{"politico":135,"identitario":95,"tecnologico":30,"esportes":195,"otaku":65},"strong":{"politico":5,"identitario":3,"tecnologico":0,"esportes":9,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (60, ARRAY[1, 2, 2, 11, 19, 8, 1, 2, 7, 1, 2], '{"version":"perfil_v1","scores":{"politico":95,"identitario":115,"tecnologico":60,"esportes":160,"otaku":60},"strong":{"politico":3,"identitario":4,"tecnologico":0,"esportes":7,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (61, ARRAY[9, 8, 5, 5, 14, 3, 2, 13, 13, 7, 1], '{"version":"perfil_v1","scores":{"politico":95,"identitario":85,"tecnologico":100,"esportes":45,"otaku":105},"strong":{"politico":3,"identitario":3,"tecnologico":3,"esportes":2,"otaku":3},"winners":["otaku"],"category":"otaku"}'::jsonb),
    (62, ARRAY[9, 4, 7, 10, 13, 9, 2, 16, 2, 2, 1], '{"version":"perfil_v1","scores":{"politico":95,"identitario":135,"tecnologico":100,"esportes":5,"otaku":125},"strong":{"politico":3,"identitario":5,"tecnologico":3,"esportes":0,"otaku":4},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (63, ARRAY[11, 6, 4, 4, 9, 4, 1, 1, 14, 1, 2], '{"version":"perfil_v1","scores":{"politico":85,"identitario":95,"tecnologico":30,"esportes":150,"otaku":75},"strong":{"politico":2,"identitario":2,"tecnologico":0,"esportes":7,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (64, ARRAY[8, 6, 2, 5, 14, 3, 1, 2, 17, 1, 2], '{"version":"perfil_v1","scores":{"politico":95,"identitario":135,"tecnologico":80,"esportes":95,"otaku":105},"strong":{"politico":3,"identitario":5,"tecnologico":2,"esportes":5,"otaku":4},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (65, ARRAY[8, 5, 6, 5, 5, 4, 2, 8, 13, 2, 1], '{"version":"perfil_v1","scores":{"politico":35,"identitario":105,"tecnologico":165,"esportes":-5,"otaku":105},"strong":{"politico":0,"identitario":4,"tecnologico":7,"esportes":0,"otaku":3},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (66, ARRAY[7, 2, 4, 6, 13, 9, 2, 16, 8, 2, 1], '{"version":"perfil_v1","scores":{"politico":115,"identitario":135,"tecnologico":100,"esportes":30,"otaku":125},"strong":{"politico":4,"identitario":5,"tecnologico":3,"esportes":1,"otaku":4},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (67, ARRAY[11, 4, 1, 4, 9, 4, 1, 2, 14, 8, 1], '{"version":"perfil_v1","scores":{"politico":95,"identitario":95,"tecnologico":15,"esportes":140,"otaku":90},"strong":{"politico":3,"identitario":3,"tecnologico":0,"esportes":6,"otaku":3},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (68, ARRAY[1, 8, 7, 3, 10, 5, 1, 2, 7, 1, 2], '{"version":"perfil_v1","scores":{"politico":75,"identitario":85,"tecnologico":50,"esportes":165,"otaku":40},"strong":{"politico":1,"identitario":2,"tecnologico":0,"esportes":6,"otaku":0},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (69, ARRAY[8, 5, 5, 11, 21, 7, 1, 8, 13, 4, 1], '{"version":"perfil_v1","scores":{"politico":35,"identitario":95,"tecnologico":95,"esportes":35,"otaku":70},"strong":{"politico":1,"identitario":4,"tecnologico":4,"esportes":2,"otaku":2},"winners":["identitario","tecnologico"],"category":"misto"}'::jsonb),
    (70, ARRAY[9, 6, 3, 6, 18, 4, 2, 5, 2, 2, 1], '{"version":"perfil_v1","scores":{"politico":55,"identitario":125,"tecnologico":115,"esportes":25,"otaku":135},"strong":{"politico":0,"identitario":4,"tecnologico":3,"esportes":0,"otaku":4},"winners":["otaku"],"category":"otaku"}'::jsonb),
    (71, ARRAY[11, 1, 1, 1, 12, 4, 2, 9, 14, 1, 2], '{"version":"perfil_v1","scores":{"politico":115,"identitario":115,"tecnologico":25,"esportes":150,"otaku":90},"strong":{"politico":4,"identitario":4,"tecnologico":1,"esportes":7,"otaku":3},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (72, ARRAY[1, 2, 2, 9, 20, 11, 1, 2, 7, 8, 2], '{"version":"perfil_v1","scores":{"politico":105,"identitario":105,"tecnologico":45,"esportes":135,"otaku":70},"strong":{"politico":4,"identitario":4,"tecnologico":0,"esportes":6,"otaku":3},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (73, ARRAY[7, 8, 2, 3, 9, 3, 2, 8, 17, 7, 1], '{"version":"perfil_v1","scores":{"politico":85,"identitario":105,"tecnologico":115,"esportes":85,"otaku":85},"strong":{"politico":2,"identitario":4,"tecnologico":3,"esportes":3,"otaku":2},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (74, ARRAY[9, 4, 4, 6, 15, 9, 2, 16, 4, 6, 1], '{"version":"perfil_v1","scores":{"politico":95,"identitario":125,"tecnologico":65,"esportes":35,"otaku":145},"strong":{"politico":3,"identitario":4,"tecnologico":1,"esportes":1,"otaku":5},"winners":["otaku"],"category":"otaku"}'::jsonb),
    (75, ARRAY[3, 1, 1, 2, 4, 4, 1, 1, 14, 1, 1], '{"version":"perfil_v1","scores":{"politico":115,"identitario":125,"tecnologico":50,"esportes":120,"otaku":80},"strong":{"politico":3,"identitario":4,"tecnologico":1,"esportes":5,"otaku":2},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (76, ARRAY[1, 2, 2, 3, 10, 5, 1, 19, 7, 8, 1], '{"version":"perfil_v1","scores":{"politico":105,"identitario":105,"tecnologico":65,"esportes":125,"otaku":95},"strong":{"politico":4,"identitario":5,"tecnologico":1,"esportes":5,"otaku":4},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (77, ARRAY[9, 5, 5, 5, 5, 3, 2, 8, 13, 5, 2], '{"version":"perfil_v1","scores":{"politico":25,"identitario":45,"tecnologico":155,"esportes":0,"otaku":100},"strong":{"politico":0,"identitario":1,"tecnologico":6,"esportes":1,"otaku":3},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (78, ARRAY[9, 6, 3, 6, 13, 9, 1, 17, 14, 2, 2], '{"version":"perfil_v1","scores":{"politico":95,"identitario":135,"tecnologico":65,"esportes":40,"otaku":105},"strong":{"politico":3,"identitario":5,"tecnologico":1,"esportes":2,"otaku":3},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (79, ARRAY[11, 1, 1, 1, 20, 2, 2, 1, 14, 2, 1], '{"version":"perfil_v1","scores":{"politico":105,"identitario":105,"tecnologico":40,"esportes":115,"otaku":95},"strong":{"politico":3,"identitario":4,"tecnologico":2,"esportes":4,"otaku":3},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (80, ARRAY[11, 2, 2, 4, 20, 4, 1, 2, 7, 2, 2], '{"version":"perfil_v1","scores":{"politico":115,"identitario":115,"tecnologico":75,"esportes":175,"otaku":85},"strong":{"politico":3,"identitario":3,"tecnologico":1,"esportes":7,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (81, ARRAY[7, 5, 6, 1, 5, 3, 2, 8, 13, 2, 1], '{"version":"perfil_v1","scores":{"politico":55,"identitario":85,"tecnologico":140,"esportes":0,"otaku":85},"strong":{"politico":1,"identitario":3,"tecnologico":6,"esportes":0,"otaku":2},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (82, ARRAY[1, 4, 8, 6, 13, 2, 2, 16, 10, 2, 1], '{"version":"perfil_v1","scores":{"politico":115,"identitario":125,"tecnologico":80,"esportes":55,"otaku":100},"strong":{"politico":3,"identitario":4,"tecnologico":2,"esportes":1,"otaku":3},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (83, ARRAY[11, 4, 1, 11, 9, 3, 1, 1, 14, 1, 2], '{"version":"perfil_v1","scores":{"politico":95,"identitario":105,"tecnologico":15,"esportes":150,"otaku":65},"strong":{"politico":3,"identitario":3,"tecnologico":0,"esportes":7,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (84, ARRAY[1, 2, 2, 3, 10, 5, 1, 11, 3, 1, 2], '{"version":"perfil_v1","scores":{"politico":115,"identitario":125,"tecnologico":55,"esportes":185,"otaku":55},"strong":{"politico":4,"identitario":5,"tecnologico":0,"esportes":8,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (85, ARRAY[7, 5, 2, 8, 12, 3, 1, 8, 13, 2, 1], '{"version":"perfil_v1","scores":{"politico":75,"identitario":105,"tecnologico":110,"esportes":70,"otaku":60},"strong":{"politico":2,"identitario":4,"tecnologico":4,"esportes":3,"otaku":1},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (86, ARRAY[9, 4, 4, 6, 13, 8, 2, 16, 2, 2, 1], '{"version":"perfil_v1","scores":{"politico":125,"identitario":135,"tecnologico":75,"esportes":20,"otaku":145},"strong":{"politico":4,"identitario":4,"tecnologico":2,"esportes":0,"otaku":5},"winners":["otaku"],"category":"otaku"}'::jsonb),
    (87, ARRAY[11, 3, 8, 4, 9, 4, 2, 11, 14, 6, 1], '{"version":"perfil_v1","scores":{"politico":75,"identitario":125,"tecnologico":70,"esportes":110,"otaku":90},"strong":{"politico":1,"identitario":4,"tecnologico":1,"esportes":4,"otaku":2},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (88, ARRAY[1, 5, 2, 3, 10, 5, 1, 2, 13, 2, 2], '{"version":"perfil_v1","scores":{"politico":75,"identitario":85,"tecnologico":70,"esportes":150,"otaku":50},"strong":{"politico":2,"identitario":3,"tecnologico":2,"esportes":6,"otaku":1},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (89, ARRAY[7, 3, 5, 5, 5, 3, 2, 8, 13, 6, 1], '{"version":"perfil_v1","scores":{"politico":35,"identitario":85,"tecnologico":155,"esportes":-5,"otaku":85},"strong":{"politico":0,"identitario":3,"tecnologico":6,"esportes":0,"otaku":2},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (90, ARRAY[8, 3, 5, 6, 18, 9, 2, 11, 2, 2, 1], '{"version":"perfil_v1","scores":{"politico":65,"identitario":135,"tecnologico":125,"esportes":40,"otaku":120},"strong":{"politico":1,"identitario":5,"tecnologico":4,"esportes":1,"otaku":3},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (91, ARRAY[3, 1, 1, 4, 15, 6, 1, 15, 14, 1, 2], '{"version":"perfil_v1","scores":{"politico":105,"identitario":145,"tecnologico":25,"esportes":135,"otaku":75},"strong":{"politico":3,"identitario":5,"tecnologico":0,"esportes":7,"otaku":2},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (92, ARRAY[4, 8, 2, 11, 10, 5, 1, 13, 7, 1, 1], '{"version":"perfil_v1","scores":{"politico":115,"identitario":105,"tecnologico":40,"esportes":125,"otaku":45},"strong":{"politico":4,"identitario":4,"tecnologico":0,"esportes":5,"otaku":1},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (93, ARRAY[7, 5, 8, 5, 5, 9, 2, 6, 17, 7, 1], '{"version":"perfil_v1","scores":{"politico":45,"identitario":55,"tecnologico":155,"esportes":10,"otaku":65},"strong":{"politico":1,"identitario":2,"tecnologico":6,"esportes":1,"otaku":1},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (94, ARRAY[9, 4, 4, 6, 12, 2, 1, 4, 2, 2, 1], '{"version":"perfil_v1","scores":{"politico":115,"identitario":85,"tecnologico":60,"esportes":70,"otaku":90},"strong":{"politico":3,"identitario":2,"tecnologico":2,"esportes":2,"otaku":3},"winners":["politico"],"category":"politico"}'::jsonb),
    (95, ARRAY[5, 1, 1, 4, 9, 4, 1, 1, 7, 1, 2], '{"version":"perfil_v1","scores":{"politico":100,"identitario":105,"tecnologico":40,"esportes":175,"otaku":75},"strong":{"politico":3,"identitario":3,"tecnologico":0,"esportes":8,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (96, ARRAY[1, 2, 5, 2, 14, 5, 1, 16, 7, 4, 2], '{"version":"perfil_v1","scores":{"politico":105,"identitario":105,"tecnologico":55,"esportes":110,"otaku":100},"strong":{"politico":4,"identitario":4,"tecnologico":1,"esportes":5,"otaku":4},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (97, ARRAY[1, 5, 7, 11, 12, 9, 2, 8, 13, 8, 2], '{"version":"perfil_v1","scores":{"politico":25,"identitario":65,"tecnologico":90,"esportes":55,"otaku":75},"strong":{"politico":0,"identitario":2,"tecnologico":3,"esportes":3,"otaku":2},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (98, ARRAY[9, 1, 2, 11, 13, 9, 2, 2, 11, 2, 2], '{"version":"perfil_v1","scores":{"politico":85,"identitario":125,"tecnologico":75,"esportes":75,"otaku":110},"strong":{"politico":3,"identitario":5,"tecnologico":2,"esportes":4,"otaku":4},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (99, ARRAY[11, 1, 3, 8, 7, 4, 1, 10, 14, 1, 2], '{"version":"perfil_v1","scores":{"politico":115,"identitario":155,"tecnologico":35,"esportes":135,"otaku":80},"strong":{"politico":4,"identitario":6,"tecnologico":0,"esportes":6,"otaku":3},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (100, ARRAY[11, 6, 2, 11, 4, 5, 1, 2, 7, 1, 1], '{"version":"perfil_v1","scores":{"politico":65,"identitario":115,"tecnologico":45,"esportes":105,"otaku":60},"strong":{"politico":2,"identitario":5,"tecnologico":1,"esportes":5,"otaku":2},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (101, ARRAY[7, 5, 5, 5, 5, 3, 1, 8, 3, 5, 2], '{"version":"perfil_v1","scores":{"politico":45,"identitario":45,"tecnologico":145,"esportes":25,"otaku":55},"strong":{"politico":1,"identitario":1,"tecnologico":6,"esportes":2,"otaku":1},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (102, ARRAY[8, 1, 4, 6, 13, 9, 2, 16, 13, 3, 1], '{"version":"perfil_v1","scores":{"politico":105,"identitario":145,"tecnologico":75,"esportes":20,"otaku":145},"strong":{"politico":4,"identitario":6,"tecnologico":2,"esportes":1,"otaku":5},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (103, ARRAY[10, 1, 1, 4, 9, 7, 1, 5, 14, 1, 1], '{"version":"perfil_v1","scores":{"politico":115,"identitario":135,"tecnologico":40,"esportes":135,"otaku":70},"strong":{"politico":4,"identitario":5,"tecnologico":1,"esportes":6,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (104, ARRAY[1, 2, 5, 2, 6, 5, 1, 9, 7, 5, 2], '{"version":"perfil_v1","scores":{"politico":85,"identitario":85,"tecnologico":70,"esportes":115,"otaku":80},"strong":{"politico":3,"identitario":3,"tecnologico":2,"esportes":5,"otaku":3},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (105, ARRAY[7, 3, 5, 5, 5, 3, 2, 8, 13, 2, 2], '{"version":"perfil_v1","scores":{"politico":35,"identitario":75,"tecnologico":165,"esportes":10,"otaku":80},"strong":{"politico":0,"identitario":2,"tecnologico":7,"esportes":1,"otaku":2},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (106, ARRAY[9, 4, 4, 6, 13, 9, 1, 16, 16, 6, 1], '{"version":"perfil_v1","scores":{"politico":135,"identitario":125,"tecnologico":45,"esportes":35,"otaku":120},"strong":{"politico":5,"identitario":4,"tecnologico":0,"esportes":1,"otaku":4},"winners":["politico"],"category":"politico"}'::jsonb),
    (107, ARRAY[11, 2, 7, 4, 9, 4, 1, 1, 11, 1, 2], '{"version":"perfil_v1","scores":{"politico":95,"identitario":95,"tecnologico":55,"esportes":185,"otaku":65},"strong":{"politico":2,"identitario":2,"tecnologico":0,"esportes":8,"otaku":1},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (108, ARRAY[1, 3, 2, 9, 10, 2, 1, 6, 8, 5, 2], '{"version":"perfil_v1","scores":{"politico":85,"identitario":95,"tecnologico":40,"esportes":105,"otaku":60},"strong":{"politico":3,"identitario":4,"tecnologico":1,"esportes":5,"otaku":3},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (109, ARRAY[11, 5, 5, 5, 21, 10, 2, 8, 13, 2, 1], '{"version":"perfil_v1","scores":{"politico":25,"identitario":55,"tecnologico":140,"esportes":15,"otaku":65},"strong":{"politico":0,"identitario":2,"tecnologico":6,"esportes":1,"otaku":1},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (110, ARRAY[9, 4, 4, 6, 13, 9, 2, 16, 10, 2, 1], '{"version":"perfil_v1","scores":{"politico":115,"identitario":125,"tecnologico":85,"esportes":10,"otaku":145},"strong":{"politico":4,"identitario":4,"tecnologico":2,"esportes":0,"otaku":5},"winners":["otaku"],"category":"otaku"}'::jsonb),
    (111, ARRAY[11, 2, 1, 7, 9, 10, 2, 1, 14, 1, 2], '{"version":"perfil_v1","scores":{"politico":65,"identitario":105,"tecnologico":50,"esportes":135,"otaku":80},"strong":{"politico":2,"identitario":4,"tecnologico":1,"esportes":7,"otaku":3},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (112, ARRAY[1, 4, 2, 4, 2, 7, 1, 2, 7, 1, 2], '{"version":"perfil_v1","scores":{"politico":105,"identitario":105,"tecnologico":45,"esportes":165,"otaku":70},"strong":{"politico":3,"identitario":2,"tecnologico":0,"esportes":7,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (113, ARRAY[7, 5, 3, 5, 5, 3, 1, 13, 13, 2, 2], '{"version":"perfil_v1","scores":{"politico":75,"identitario":75,"tecnologico":120,"esportes":60,"otaku":55},"strong":{"politico":2,"identitario":2,"tecnologico":5,"esportes":3,"otaku":1},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (114, ARRAY[5, 4, 4, 6, 13, 9, 2, 16, 2, 2, 1], '{"version":"perfil_v1","scores":{"politico":110,"identitario":125,"tecnologico":75,"esportes":15,"otaku":125},"strong":{"politico":4,"identitario":4,"tecnologico":2,"esportes":0,"otaku":4},"winners":["identitario","otaku"],"category":"misto"}'::jsonb),
    (115, ARRAY[7, 4, 5, 9, 9, 4, 1, 1, 14, 2, 2], '{"version":"perfil_v1","scores":{"politico":95,"identitario":85,"tecnologico":70,"esportes":95,"otaku":55},"strong":{"politico":3,"identitario":2,"tecnologico":3,"esportes":4,"otaku":1},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (116, ARRAY[1, 3, 7, 3, 5, 5, 1, 2, 17, 6, 2], '{"version":"perfil_v1","scores":{"politico":65,"identitario":95,"tecnologico":60,"esportes":115,"otaku":50},"strong":{"politico":1,"identitario":3,"tecnologico":1,"esportes":4,"otaku":1},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (117, ARRAY[7, 5, 5, 5, 5, 3, 2, 8, 13, 2, 1], '{"version":"perfil_v1","scores":{"politico":35,"identitario":65,"tecnologico":185,"esportes":-5,"otaku":75},"strong":{"politico":0,"identitario":2,"tecnologico":8,"esportes":0,"otaku":1},"winners":["tecnologico"],"category":"tecnologico"}'::jsonb),
    (118, ARRAY[9, 4, 8, 11, 13, 9, 2, 16, 2, 7, 1], '{"version":"perfil_v1","scores":{"politico":105,"identitario":125,"tecnologico":60,"esportes":15,"otaku":115},"strong":{"politico":4,"identitario":5,"tecnologico":1,"esportes":1,"otaku":4},"winners":["identitario"],"category":"identitario"}'::jsonb),
    (119, ARRAY[2, 8, 3, 4, 17, 4, 1, 1, 14, 3, 2], '{"version":"perfil_v1","scores":{"politico":105,"identitario":105,"tecnologico":70,"esportes":115,"otaku":85},"strong":{"politico":3,"identitario":3,"tecnologico":1,"esportes":5,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb),
    (120, ARRAY[1, 2, 2, 3, 10, 5, 1, 2, 7, 1, 2], '{"version":"perfil_v1","scores":{"politico":95,"identitario":105,"tecnologico":50,"esportes":185,"otaku":60},"strong":{"politico":3,"identitario":4,"tecnologico":0,"esportes":8,"otaku":2},"winners":["esportes"],"category":"esportes"}'::jsonb);

INSERT INTO alunos (nome, email)
SELECT 'Participante ficticio ' || lpad(numero::text, 3, '0'),
       'perfil.exemplo.' || numero || '@example.invalid'
FROM perfil_envios_exemplo
ON CONFLICT (email) DO NOTHING;

INSERT INTO envios (id_aluno, id_questionario, id_dispositivo, data_envio, resultado)
SELECT a.id_aluno, q.id_questionario,
       md5('sis-questionario:perfil:exemplo:' || f.numero)::uuid,
       CURRENT_TIMESTAMP - (f.numero % 30) * INTERVAL '1 day', f.resultado
FROM perfil_envios_exemplo f
JOIN alunos a ON a.email = 'perfil.exemplo.' || f.numero || '@example.invalid'
CROSS JOIN questionarios q
WHERE q.codigo = 'perfil'
ON CONFLICT (id_dispositivo, id_questionario) DO NOTHING;

INSERT INTO respostas (id_envio, id_pergunta, id_opcao)
SELECT e.id_envio, p.id_pergunta, o.id_opcao
FROM perfil_envios_exemplo f
CROSS JOIN LATERAL unnest(f.escolhas) WITH ORDINALITY escolha(opcao, pergunta)
JOIN questionarios q ON q.codigo = 'perfil'
JOIN envios e ON e.id_questionario = q.id_questionario
             AND e.id_dispositivo = md5('sis-questionario:perfil:exemplo:' || f.numero)::uuid
JOIN perguntas p ON p.id_questionario = q.id_questionario AND p.ordem = escolha.pergunta
JOIN opcoes o ON o.id_pergunta = p.id_pergunta AND o.ordem = escolha.opcao
ON CONFLICT (id_envio, id_pergunta) DO NOTHING;

-- Compatibilidade com uma execucao anterior, que ainda nao gravava resultados.
-- Nao recalcula resultados existentes nem classifica respostas reais.
-- A verificacao das escolhas impede associar o perfil a respostas diferentes.
UPDATE envios e
SET resultado = f.resultado
FROM perfil_envios_exemplo f, questionarios q, alunos a
WHERE q.codigo = 'perfil'
  AND e.id_questionario = q.id_questionario
  AND e.id_dispositivo = md5('sis-questionario:perfil:exemplo:' || f.numero)::uuid
  AND e.id_aluno = a.id_aluno
  AND a.email = 'perfil.exemplo.' || f.numero || '@example.invalid'
  AND e.resultado IS NULL
  AND ARRAY(
      SELECT o.ordem FROM respostas r
      JOIN perguntas p ON p.id_pergunta = r.id_pergunta
      JOIN opcoes o ON o.id_opcao = r.id_opcao AND o.id_pergunta = p.id_pergunta
      WHERE r.id_envio = e.id_envio AND p.id_questionario = q.id_questionario
      ORDER BY p.ordem
  ) = f.escolhas
  AND (SELECT COUNT(*) FROM respostas r WHERE r.id_envio = e.id_envio) = cardinality(f.escolhas);

-- Mantem o documento portavel para questionarios criados por esta carga SQL.
UPDATE questionarios q SET documento = jsonb_build_object(
    'schema_version', 1, 'codigo', q.codigo, 'titulo', q.titulo, 'ativo', q.ativo,
    'algoritmo', q.algoritmo, 'exibir_resultado', q.exibir_resultado,
    'perguntas', (SELECT jsonb_agg(jsonb_build_object(
        'enunciado', p.enunciado, 'opcoes', (SELECT jsonb_agg(o.texto ORDER BY o.ordem)
        FROM opcoes o WHERE o.id_pergunta = p.id_pergunta)) ORDER BY p.ordem)
        FROM perguntas p WHERE p.id_questionario = q.id_questionario))
WHERE q.codigo = 'perfil' AND q.documento IS NULL;

COMMIT;
