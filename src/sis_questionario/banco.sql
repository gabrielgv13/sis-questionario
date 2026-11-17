-- Estrutura aplicada pelo setup_db usando Psycopg.
SET search_path TO public;

-- INICIO_TABELAS
CREATE TABLE IF NOT EXISTS alunos (
    id_aluno SERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS questionarios (
    id_questionario SERIAL PRIMARY KEY,
    codigo TEXT NOT NULL UNIQUE,
    titulo TEXT NOT NULL,
    ativo BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS perguntas (
    id_pergunta SERIAL PRIMARY KEY,
    id_questionario INTEGER NOT NULL REFERENCES questionarios(id_questionario),
    enunciado TEXT NOT NULL,
    ordem INTEGER NOT NULL,
    UNIQUE (id_questionario, ordem)
);

CREATE TABLE IF NOT EXISTS opcoes (
    id_opcao SERIAL PRIMARY KEY,
    id_pergunta INTEGER NOT NULL REFERENCES perguntas(id_pergunta),
    texto TEXT NOT NULL,
    ordem INTEGER NOT NULL,
    UNIQUE (id_pergunta, ordem)
);

CREATE TABLE IF NOT EXISTS envios (
    id_envio SERIAL PRIMARY KEY,
    id_aluno INTEGER NOT NULL REFERENCES alunos(id_aluno),
    id_questionario INTEGER NOT NULL REFERENCES questionarios(id_questionario),
    id_dispositivo UUID,
    data_envio TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Atualiza também instalações que já têm envios sem identificador.
ALTER TABLE envios ADD COLUMN IF NOT EXISTS id_dispositivo UUID;
CREATE UNIQUE INDEX IF NOT EXISTS envios_dispositivo_questionario_unico
    ON envios (id_dispositivo, id_questionario);

CREATE TABLE IF NOT EXISTS respostas (
    id_resposta SERIAL PRIMARY KEY,
    id_envio INTEGER NOT NULL REFERENCES envios(id_envio),
    id_pergunta INTEGER NOT NULL REFERENCES perguntas(id_pergunta),
    id_opcao INTEGER NOT NULL REFERENCES opcoes(id_opcao),
    UNIQUE (id_envio, id_pergunta)
);
-- A configuração da devolutiva é independente do algoritmo usado nos envios.
ALTER TABLE questionarios ADD COLUMN IF NOT EXISTS algoritmo TEXT;
-- Scoring rules belong to the questionnaire and are saved atomically on import.
ALTER TABLE questionarios ADD COLUMN IF NOT EXISTS regras_algoritmo JSONB;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = current_schema() AND table_name = 'questionarios'
                     AND column_name = 'exibir_resultado') THEN
        ALTER TABLE questionarios ADD COLUMN exibir_resultado BOOLEAN NOT NULL DEFAULT FALSE;
        UPDATE questionarios SET algoritmo = 'perfil_v1', exibir_resultado = TRUE
        WHERE codigo = 'perfil';
    END IF;
END $$;
ALTER TABLE envios ADD COLUMN IF NOT EXISTS resultado JSONB;
ALTER TABLE questionarios ADD COLUMN IF NOT EXISTS documento JSONB;
-- Normaliza o identificador histórico sem recalcular os resultados salvos.
DO $$
DECLARE
    anterior TEXT := convert_from(decode('70657266696c5f736573695f7631', 'hex'), 'UTF8');
BEGIN
    UPDATE questionarios SET algoritmo = 'perfil_v1' WHERE algoritmo = anterior;
    UPDATE questionarios SET documento = jsonb_set(documento, '{algoritmo}', '"perfil_v1"'::jsonb)
    WHERE documento->>'algoritmo' = anterior;
    UPDATE envios SET resultado = jsonb_set(resultado, '{version}', '"perfil_v1"'::jsonb)
    WHERE resultado->>'version' = anterior;
END $$;
-- Guarda a estrutura dos questionários existentes sem recriar perguntas ou respostas.
UPDATE questionarios q SET documento = jsonb_build_object(
    'schema_version', 1, 'codigo', q.codigo, 'titulo', q.titulo, 'ativo', q.ativo,
    'algoritmo', q.algoritmo, 'exibir_resultado', q.exibir_resultado,
    'perguntas', COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'enunciado', p.enunciado, 'opcoes', COALESCE((SELECT jsonb_agg(o.texto ORDER BY o.ordem)
        FROM opcoes o WHERE o.id_pergunta = p.id_pergunta), '[]'::jsonb)) ORDER BY p.ordem)
        FROM perguntas p WHERE p.id_questionario = q.id_questionario), '[]'::jsonb))
WHERE q.documento IS NULL;
-- FIM_TABELAS
