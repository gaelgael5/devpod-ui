"""Moteur d'automates (port docflow) : contrats OpenAPI + runner à curseur.

Un automate consomme le journal durable `app_event` par curseur et, pour un event
retenu, résout puis appelle une opération d'un contrat OpenAPI (anti-SSRF, secrets
vault résolus à l'exécution, anti-rejeu, debounce, stop_chain, historique/rejeu).
"""
