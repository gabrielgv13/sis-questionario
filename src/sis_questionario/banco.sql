-- ALL IN ONE: execute este arquivo inteiro no Query Tool do pgAdmin.
-- Conecte ao banco JA CRIADO pelo Render, usando a conta proprietaria.
-- Edite apenas a senha abaixo e use a mesma senha em DB_PASSWORD no web.
-- DB_USER deve ser sis_app. Nao use a conta proprietaria no web.
-- Reexecutavel: preserva dados e nao troca a senha de uma role existente.
BEGIN;
SET LOCAL search_path TO public;
SET LOCAL lock_timeout = '30s';
SELECT pg_advisory_xact_lock(734190261);

DO $setup$
DECLARE
    senha TEXT := 'SUBSTITUA_POR_UMA_SENHA_ALEATORIA_COM_24_OU_MAIS_CARACTERES';
    existente RECORD;
BEGIN
    IF senha LIKE 'SUBSTITUA_%' OR length(senha) < 24 THEN
        RAISE EXCEPTION 'Edite a senha de sis_app no inicio do arquivo (minimo 24 caracteres).';
    END IF;
    IF current_user = 'sis_app' THEN
        RAISE EXCEPTION 'Execute como proprietario do banco, nao como sis_app.';
    END IF;
    SELECT * INTO existente FROM pg_roles WHERE rolname = 'sis_app';
    IF FOUND THEN
        IF NOT existente.rolcanlogin OR existente.rolsuper OR existente.rolcreatedb OR existente.rolcreaterole
           OR existente.rolreplication OR existente.rolbypassrls
           OR EXISTS (SELECT 1 FROM pg_auth_members WHERE member = existente.oid)
           OR EXISTS (SELECT 1 FROM pg_class WHERE relowner = existente.oid)
           OR EXISTS (SELECT 1 FROM pg_database WHERE datdba = existente.oid)
           OR EXISTS (SELECT 1 FROM pg_namespace WHERE nspowner = existente.oid) THEN
            RAISE EXCEPTION 'sis_app existente possui privilegios ou propriedade incompativeis.';
        END IF;
        -- A senha existente e preservada; configure DB_PASSWORD com essa senha.
    ELSE
        EXECUTE format('CREATE ROLE sis_app LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L', senha);
    END IF;
END $setup$;

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

-- Permissoes da aplicacao: sem DDL, DELETE ou TRUNCATE.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM sis_app;
DO $permissions$
BEGIN
    EXECUTE format('REVOKE CREATE ON DATABASE %I FROM sis_app', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO sis_app', current_database());
END $permissions$;
GRANT USAGE ON SCHEMA public TO sis_app;
REVOKE ALL ON alunos, questionarios, perguntas, opcoes, envios, respostas FROM sis_app;
GRANT SELECT, INSERT ON alunos, questionarios, perguntas, opcoes, envios, respostas TO sis_app;
GRANT UPDATE (exibir_resultado, documento) ON questionarios TO sis_app;
GRANT USAGE ON SEQUENCE alunos_id_aluno_seq, questionarios_id_questionario_seq,
    perguntas_id_pergunta_seq, opcoes_id_opcao_seq, envios_id_envio_seq,
    respostas_id_resposta_seq TO sis_app;
COMMIT;
