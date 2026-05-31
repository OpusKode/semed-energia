# SEMED Energia

Importador e analisador de faturas de energia elétrica (Equatorial Pará) para a **Secretaria Municipal de Educação de Ananindeua (SEMED)**.

---

## Requisitos

- Python 3.11+ (embute SQLite ≥ 3.39, necessário para window functions / `NULLS LAST`)
- Banco: **SQLite** (arquivo local, criado automaticamente — sem servidor). Em dev é possível apontar para um PostgreSQL via `SEMED_DB_URL`.
- Dependências: `pip install -r requirements.txt`

---

## Uso básico

### Modo normal — processa `entrada/`

Coloque PDFs em `entrada/` e execute:

```bash
python main.py
python main.py --dry-run      # sem DB, sem mover arquivos
python main.py --no-move      # persiste no banco mas não move os PDFs
python main.py --pasta outra/ # pasta de entrada alternativa
```

---

## Modo histórico

Importa o acervo completo de `FATURAS - SEMED/` sem precisar mover arquivos manualmente. O sistema detecta automaticamente o formato de cada mês/agrupadora e gera PDFs lógicos prontos para o parser.

### Formatos suportados

| Formato | Quando ocorre | O que o sistema faz |
|---|---|---|
| `unico` | 1 PDF com capa + detalhes (2023-2026) | Passa direto |
| `fragmentado` | Capa e detalhes em arquivos separados (2020-2022) | Funde num único PDF lógico |
| `consolidado` | 1 PDF gigante com várias agrupadoras (2024-OUT, 2025-JUL) | Divide em N PDFs lógicos |
| `pasta_mista` | Pasta com duplicatas, comprovantes e relações (2024-FEV) | Seleciona capa+detalhe válidos |

### Layouts de fatura suportados

| Versão | Anos | Campos extras |
|---|---|---|
| `v2020` | 2020-2021 | `Correção Monetária`, `Multa`, `Juros`, `Adicional Band. Amarela/Vermelha` |
| `v2022` | 2022-2023 | `Devolução ICMS LC 194/22`, 4ª agrupadora (SEMED-IV) |
| `v2026` | 2024-2026 | Layout moderno (referência) |

### Sintaxe

```bash
# Toda a árvore histórica
python main.py --modo historico --raiz "FATURAS - SEMED"

# Um ano específico
python main.py --modo historico --raiz "FATURAS - SEMED/EQUATORIAL - FATURAS - 2020"

# Um mês específico
python main.py --modo historico --raiz "FATURAS - SEMED/EQUATORIAL - FATURAS - 2024/10-OUTUBRO-2024"

# Dry-run (sem DB, sem persistir)
python main.py --modo historico --raiz "FATURAS - SEMED" --dry-run
```

### O que acontece

1. **Scanner** (`ingest/scanner.py`) percorre a hierarquia `ano/mês/agrupadora` e detecta grupos de arquivos.
2. **Detector** (`ingest/detector_formato.py`) classifica cada grupo: `unico`, `fragmentado`, `consolidado` ou `pasta_mista`.
3. **Splitter** (`ingest/splitter.py`) divide PDFs consolidados em N PDFs lógicos (1 por agrupadora), usando "FATURA AGRUPADORA" + número de documento como delimitador de capa.
4. **Merger** (`ingest/merger.py`) funde PDFs fragmentados (capa + detalhes) num único PDF lógico.
5. **Classifier pasta** (`ingest/classifier_pasta.py`) descarta comprovantes/relatórios e escolhe o arquivo mais completo em pastas mistas.
6. **Orquestrador** (`ingest/orquestrador.py`) materializa os PDFs lógicos e emite `LoteAgrupadora` para o parser.
7. O parser existente (`parser/`) processa cada PDF lógico normalmente.

### Auditoria

O campo `arquivo_origem` no banco registra o **caminho original** dentro de `FATURAS - SEMED/` (não o nome do PDF lógico gerado), facilitando rastrear de qual arquivo físico veio cada agrupadora importada.

### Comportamento de erros

- Exceções por lote individual são **logadas e ignoradas** — o loop continua para o próximo lote.
- Lotes com formato `desconhecido` são logados com `WARNING` e pulados.
- O relatório final exibe contagem de erros, lotes importados e avisos de validação.

---

## Scripts de administração

### Snapshot do banco
```bash
python scripts/snapshot_db.py
# Saída: snapshots/snap_AAAA-MM-DD_HHMMSS.json
```

### Reimport histórico completo
```bash
python scripts/reimport_historico.py              # interativo, 2020–2026
python scripts/reimport_historico.py --dry-run    # só detecta lotes, sem persistir
python scripts/reimport_historico.py --ano 2026   # só um ano
python scripts/reimport_historico.py --no-confirm # sem pausa interativa (CI/CD)
```

### Comparar snapshots (antes vs. depois)
```bash
python scripts/comparar_snapshots.py snapshots/snap_antes.json snapshots/snap_depois.json
```

### Backfill temporal (campos ano/mes/complemento_norm)
```bash
psql -d <banco> -f scripts/backfill_temporal.sql
```

---

## Estrutura de pastas

```
entrada/          PDFs aguardando processamento (modo normal)
processados/      PDFs importados com sucesso
duplicados/       PDFs já existentes no banco
erros/            PDFs que falharam no parser
logs/             Logs diários (semed_YYYY-MM-DD.log)
snapshots/        Snapshots JSON do banco (pré/pós reimport)
scripts/          Scripts de administração e manutenção
  snapshot_db.py         Exporta estado do banco para JSON
  reimport_historico.py  Reimporta acervo histórico 2020–2026
  comparar_snapshots.py  Compara dois snapshots
  backfill_temporal.sql  Preenche ano/mes/complemento_norm legados
ingest/           Módulo de pré-processamento histórico (Fase 1)
  scanner.py       Varre a hierarquia FATURAS - SEMED/
  detector_formato.py  Classifica: unico/fragmentado/consolidado/pasta_mista
  splitter.py      Divide PDFs consolidados em N PDFs lógicos
  merger.py        Funde PDFs fragmentados num único PDF lógico
  classifier_pasta.py  Filtra comprovantes/relações em pastas mistas
  orquestrador.py  API pública — gera LoteAgrupadora por agrupadora
parser/           Extração de dados dos PDFs (suporta layouts 2020–2026)
  version_detector.py  Detecta versão do layout (v2020/v2022/v2026)
  capa_parser.py   Parser multi-versão da capa da fatura agrupadora
  detalhe_parser.py    Parser dos blocos B3/A4 de faturas individuais
  patterns.py      Patterns regex por versão de layout
db/               Modelos, repositório e conexão SQLite (PostgreSQL via override)
  models.py        FaturaAgrupadora, FaturaIndividual, Tributo, …
  connection.py    Engine + init_db() (cria tabelas e views)
  views_sqlite.py  As 7 views analíticas (Power BI) em sintaxe SQLite
  repository.py    CRUD + consultas hierárquicas e temporais
  migrations/      DDL legado de PostgreSQL (não usado no caminho SQLite)
validator/        Validação de integridade dos dados extraídos
ui/               Interface gráfica (PySide6)
  pages/           Páginas da aplicação
    agrupadoras_page.py  Árvore Ano > Mês > Agrupadora
    dashboard_page.py    Dashboard analítico (6 seções)
    unidade_page.py      Histórico e análise por instalação
  workers/         Workers assíncronos (QThread)
    aggregators.py       DashboardAggregator, SerieHistorica,
                         Decomposicao, YoY, CoberturaWorker
    anomaly_detector.py  Detecção de anomalias e alertas
  widgets/
    filtros_temporais.py  Barra de filtros reutilizável
```

---

## Testes

```bash
pytest -q                           # suíte completa
pytest tests/test_smoke.py          # valida comportamento atual contra goldens
pytest tests/test_ingest.py         # testa o módulo de ingestão (Fase 1)
pytest tests/test_smoke.py --update-golden  # atualiza goldens após mudanças intencionais
```

> ℹ️ As fixtures (`tests/fixtures/`) e os goldens (`tests/golden/`) são **dados reais e não versionados**. Num clone novo, recrie-os localmente seguindo `tests/fixtures/README.md` antes de rodar os testes de parsing.

---

## Contribuindo — como enviar uma alteração

A branch `main` é **protegida**: ninguém dá `push` direto nela — toda mudança entra por **Pull Request (PR)**.

> **Como a proteção é aplicada:** a proteção *server-side* do GitHub (branch protection / rulesets) exige **GitHub Pro** em repositório privado. Enquanto o repo estiver no plano Free, a regra "sem push direto na `main`" é garantida **localmente** pelo hook `.githooks/pre-push` (habilite-o — passo abaixo). No servidor, o repositório já está em **Squash and merge** apenas. Migrando para Pro/Team, dá para ligar a proteção server-side em segundos (ver o fim desta seção).

### 1. Crie uma branch a partir da `main`

Use um prefixo coerente com o tipo da mudança:

```bash
git checkout main && git pull
git checkout -b feat/exportar-pdf      # ou: fix/leitura-bandeira-2020, docs/atualiza-guia, …
```

### 2. Faça commits no padrão Conventional Commits

Formato: **`<tipo>(escopo opcional): <descrição no imperativo>`**

| Tipo | Quando usar |
|---|---|
| `feat` | nova funcionalidade |
| `fix` | correção de bug |
| `docs` | só documentação |
| `style` | formatação (sem mudar lógica) |
| `refactor` | refatoração sem mudar comportamento |
| `perf` | melhoria de performance |
| `test` | adiciona/ajusta testes |
| `build` | build, empacotamento, dependências |
| `ci` | integração contínua |
| `chore` | tarefas diversas |
| `revert` | reverte um commit |

Exemplos:

```
feat(updater): baixar release via asset autenticado
fix(parser): corrigir bandeira no layout 2020
docs(readme): explicar fluxo de PR
feat(db)!: migrar de PostgreSQL para SQLite      # "!" sinaliza mudança incompatível
```

**Ative os hooks locais (uma vez por clone):**

```bash
git config core.hooksPath .githooks
```

Isso liga dois hooks:
- `commit-msg` — recusa commits fora do padrão Conventional Commits.
- `pre-push` — recusa `push` direto na `main` (emergência: `ALLOW_MAIN_PUSH=1 git push origin main`).

### 3. Abra o Pull Request

```bash
git push -u origin feat/exportar-pdf
gh pr create --base main --fill        # ou abra pela interface do GitHub
```

- O **título do PR** também deve seguir Conventional Commits — ele vira o commit da `main` (usamos **Squash and merge**).
- O CI (`.github/workflows/pr-checks.yml`) valida o título do PR e roda uma checagem de sanidade (compila tudo + cria o schema SQLite com as views). Os dois checks precisam ficar verdes.

### 4. Merge

Com os checks verdes, faça **Squash and merge** pela interface. A `main` mantém histórico limpo: 1 commit por PR, todos no padrão.

### 5. Publicar uma release (gera instalador + auto-update)

Depois que a mudança está na `main`:

```bash
# 1) suba a versão em version.py  ->  __version__ = "1.0.1"  (via PR também)
# 2) com a main atualizada, marque a tag:
git checkout main && git pull
git tag v1.0.1
git push origin v1.0.1
```

O workflow `release.yml` builda o `.exe`, gera o `SEMED-Energia-windows.zip` e publica a release — que os clientes baixam no próximo arranque. **A tag tem que bater com `version.py`** (o workflow falha de propósito se divergir).

### Proteção server-side (opcional — requer GitHub Pro/Team)

Em repositório **privado**, branch protection e rulesets exigem plano pago. Após o upgrade, ligue a proteção (PR obrigatório, sem push direto nem para admins, checks obrigatórios) com:

```bash
gh api -X PUT repos/OpusKode/semed-energia/branches/main/protection --input - <<'JSON'
{
  "required_status_checks": { "strict": true, "contexts": ["pr-title", "sanity"] },
  "enforce_admins": true,
  "required_pull_request_reviews": { "required_approving_review_count": 0 },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_linear_history": true
}
JSON
```

A partir daí o GitHub passa a recusar pushes diretos no servidor e a exigir que os checks `pr-title` e `sanity` fiquem verdes antes do merge — tornando o hook `pre-push` redundante (mas inofensivo).
