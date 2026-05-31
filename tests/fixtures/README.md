# Fixtures — PDFs representativos para smoke tests

Cada subpasta cobre um padrão observado em `FATURAS - SEMED/` que o sistema precisa entender. São cópias de **arquivos reais** e, por isso, **não são versionadas** (estão no `.gitignore`, junto com `tests/golden/`). Para rodar os testes de parsing num clone novo, recrie cada pasta localmente a partir de `FATURAS - SEMED/` usando a coluna "Origem" da tabela abaixo e depois gere os goldens (ver "Como atualizar").

| Pasta | Origem | Padrão que ilustra | Comportamento esperado **hoje** | Comportamento esperado **após Fase 2** |
|---|---|---|---|---|
| `2020_fragmentado/` | `2020/10-OUTUBRO-2020/SEMED I - OUTUBRO 2020/` | 1 agrupadora repartida em `1.pdf` (capa, 1 página), `2.pdf` (detalhes, várias páginas), `3.pdf` (extra) | Cada PDF é processado isoladamente; só `1.pdf` é reconhecido como capa | Os 3 PDFs são fundidos pelo `ingest/merger.py` em **1** agrupadora |
| `2021_fragmentado_4agr/` | `2021/1 - JANEIRO-2021/SEMED IV - JANEIRO/` | Mesma estrutura fragmentada, **mas 4ª agrupadora** (`SEMED 4`) e com campos antigos (Correção Monetária, Multa, Juros, Adicional Band. Amarela/Vermelha) | Falha parcial: classifier reconhece capa mas patterns não pegam os campos antigos | Fundido + parser v2020 extrai todos os campos |
| `2022_unico_4agr/` | `2022/1 - JANEIRO-2022/SEMED - IV.PDF` | 1 PDF único da 4ª agrupadora | Funciona razoavelmente; alguns campos antigos podem faltar | Tudo extraído com parser v2022 |
| `2023_unico/` | `2023/1-JANEIRO-2023/SEMED-I.PDF` | Caso "feliz" antigo: 1 PDF, 3 agrupadoras (sem IV), layout próximo do moderno | Deve funcionar bem hoje | Sem regressão |
| `2024_pasta_misturada/` | `2024/2-FEVEREIRO-2024/1/` | Pasta com 5 PDFs: capa, relações, versões duplicadas | Sistema tenta processar cada PDF independente; gera erros e duplicatas | `ingest/classifier_pasta.py` mantém só capa+relação, gera 1 agrupadora |
| `2024_consolidado/` | `2024/10-OUTUBRO-2024/10-OUTUBRO-SEMED-I-II-III-2024.pdf` | 1 PDF com **6 ocorrências** de "FATURA AGRUPADORA" (3 capas reais + 3 fichas de compensação) | Só a primeira capa é parseada; demais ignoradas | `ingest/splitter.py` divide em 3 PDFs lógicos = 3 agrupadoras |
| `2025_consolidado/` | `2025/JULHO-2025/7-JULHO-EQUATORIAL-2025.pdf` | Mesma situação consolidada de 2024 | Idem | Splitter cobre |
| `2026_referencia/` | `2026/JANEIRO - 2026/SEMED-I.pdf` | Modelo "happy path" para o qual o parser foi calibrado | Funciona | Continua funcionando (regression guard) |

## Como atualizar

Se um novo padrão aparecer no histórico, crie uma nova pasta aqui com:

1. Nome auto-explicativo (`AAAA_caracteristica`).
2. Os PDFs mínimos para ilustrar o padrão.
3. Uma linha nesta tabela.
4. Rode `pytest tests/test_smoke.py --update-golden` para registrar o estado atual.
