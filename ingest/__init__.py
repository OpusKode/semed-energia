"""
Pré-processador de ingestão (Fase 1).

Transforma a bagunça de `FATURAS - SEMED/` em "PDFs lógicos" prontos para
o parser atual digerir, sem tocar em `parser/`.

API pública:
    from ingest.orquestrador import expandir_pasta_historica
"""
