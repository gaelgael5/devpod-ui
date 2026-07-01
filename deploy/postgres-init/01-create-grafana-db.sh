#!/bin/bash
# Crée la base "grafana" si elle n'existe pas encore.
# Ce script est exécuté par le container Postgres au premier démarrage du volume.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE grafana'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'grafana')\gexec
EOSQL
