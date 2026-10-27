-- SQL único de instalação. Execute com psql usando um administrador PostgreSQL.
-- A senha é lida de DB_PASSWORD; não coloque credenciais no repositório.
\set ON_ERROR_STOP on
\getenv banco DB_NAME
\if :{?banco}
\else
    \set banco mydatabase
\endif
\getenv senha_app DB_PASSWORD
\if :{?senha_app}
\else
    \echo 'Defina DB_PASSWORD antes de executar este arquivo.'
    \quit 1
\endif

-- CREATE DATABASE precisa ser executado fora de uma transação.
SELECT format('CREATE DATABASE %I', :'banco')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'banco')
\gexec
\connect :banco

BEGIN;
SET search_path TO public;

SELECT 'CREATE USER "client-app"'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'client-app')
\gexec
SELECT format('ALTER USER "client-app" WITH PASSWORD %L', :'senha_app')
\gexec

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
-- FIM_TABELAS

GRANT CONNECT ON DATABASE :"banco" TO "client-app";
GRANT USAGE ON SCHEMA public TO "client-app";
GRANT SELECT, INSERT ON TABLE
    alunos,
    envios,
    opcoes,
    perguntas,
    questionarios,
    respostas
TO "client-app";
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO "client-app";
COMMIT;
