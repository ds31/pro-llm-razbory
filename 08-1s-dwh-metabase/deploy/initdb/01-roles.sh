#!/bin/sh
# Первый запуск Postgres: служебная база Metabase и пользователь только для чтения витрин.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE DATABASE metabase;
CREATE ROLE metabase_reader LOGIN PASSWORD '${MB_READER_PASSWORD}';
GRANT CONNECT ON DATABASE dwh TO metabase_reader;
SQL
