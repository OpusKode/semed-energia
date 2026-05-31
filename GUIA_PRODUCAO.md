# Guia de Produção — SEMED Energia

Como transformar o sistema em um programa instalável no Windows, publicá-lo no GitHub e fazer com que ele **se atualize sozinho** a cada inicialização.

Este guia assume que você **nunca fez isso antes**. Siga na ordem.

---

## Visão geral (o que vai acontecer)

1. O código vira um **executável** com o PyInstaller (`SEMED Energia.exe` + uma pasta de apoio).
2. Esse executável é embrulhado num **instalador** (Inno Setup) que o cliente roda uma vez.
3. O código fica num **repositório privado no GitHub**.
4. Toda vez que você publica uma **release** nova, o GitHub Actions gera o pacote automaticamente.
5. Ao abrir, o programa **consulta o GitHub, baixa a versão nova e se atualiza**, reiniciando sozinho.

Os **dados do cliente** (banco, faturas, logs) ficam em `%LOCALAPPDATA%\SEMED Energia\` e **nunca** são apagados por uma atualização.

---

## Mudanças já aplicadas no projeto

Estas alterações já foram feitas para deixar o sistema pronto:

- **Banco migrado de PostgreSQL para SQLite** (arquivo único, sem servidor). Veja `config.py` e `db/connection.py`. O banco é criado automaticamente na primeira execução.
- **Dados do usuário separados do programa**: em produção vão para `%LOCALAPPDATA%\SEMED Energia\` (gravável e preservado em updates).
- **`version.py`**: a versão do app (fonte única da verdade).
- **`updater.py` + `update_config.py`**: o mecanismo de auto-atualização.
- **`.gitignore`**: impede que dados reais e segredos (`.env`, faturas, banco) vão para o GitHub.
- **`semed.spec`** (PyInstaller), **`installer/semed.iss`** (Inno Setup) e **`.github/workflows/release.yml`** (CI).
- **Repositório `OpusKode/semed-energia` (privado)** já criado; a branch `main` é **protegida** (sem push direto — só por **Pull Request**) e os **commits são padronizados** (Conventional Commits, validados por hook local + CI `pr-checks.yml`). O passo a passo de como enviar uma alteração está em **"Contribuindo"** no `README.md`.

> ⚠️ **Atenção aos dados atuais.** Hoje seus dados estão no PostgreSQL. Ao mudar para SQLite, o banco começa **vazio**. Para reconstituir o histórico, rode o reimport a partir das faturas:
> `python scripts/reimport_historico.py` (ele lê a pasta `FATURAS - SEMED/`).
> Se preferir manter o Postgres só na sua máquina de desenvolvimento, defina a variável `SEMED_DB_URL` apontando para ele — o cliente continua no SQLite.

---

## Pré-requisitos (instale uma vez na sua máquina)

1. **Git** — https://git-scm.com/download/win
2. **Conta no GitHub** — https://github.com
3. **Python 3.11 (64-bit)** — https://www.python.org/downloads/ (marque "Add to PATH")
4. **Inno Setup 6** — https://jrsoftware.org/isdl.php

---

## Parte 1 — Criar o repositório privado e subir o código

> ✅ **Já feito nesta configuração:** o repositório `OpusKode/semed-energia` (privado) existe e a `main` já foi enviada. A partir daqui, **alterações entram por Pull Request** — `push` direto na `main` é bloqueado (ver Parte 4 e "Contribuindo" no `README.md`). Os passos abaixo ficam como referência para recriar do zero.

1. No GitHub: **New repository** → nome `semed-energia` → **Private** → *Create* (não marque "Add README").
2. No terminal, dentro da pasta do projeto:

   ```bash
   git init
   git add .
   git commit -m "Versão inicial para produção"
   git branch -M main
   git remote add origin https://github.com/SEU_USUARIO/semed-energia.git
   git push -u origin main
   ```

3. Confira no GitHub que **não** subiram a pasta `FATURAS - SEMED/`, `.env`, nem arquivos `.db` (o `.gitignore` cuida disso).

---

## Parte 2 — Configurar o auto-update

### 2.1 Apontar o app para o seu repositório

> ✅ **Já configurado:** `update_config.py` aponta para `OpusKode / semed-energia`.

O arquivo **`update_config.py`** define o destino:

```python
GITHUB_OWNER = "OpusKode"      # usuário/organização no GitHub
GITHUB_REPO  = "semed-energia"
```

### 2.2 Gerar o token de leitura (repositório privado)

Como o repositório é privado, o programa precisa de um **token** para baixar atualizações.

1. GitHub → **Settings** (do seu perfil) → **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → *Generate new token*.
2. **Resource owner**: você/sua organização. **Repository access**: *Only select repositories* → `semed-energia`.
3. **Permissions** → *Repository permissions* → **Contents: Read-only**.
4. Gere e **copie** o token (começa com `github_pat_...`).

Esse token vai num arquivo **`update_token.txt`** colocado ao lado do executável (o instalador o inclui). **Nunca** faça commit dele — o `.gitignore` já o ignora, mas confirme.

> Segurança: o token é somente-leitura e restrito a um repositório. É o suficiente para o app baixar updates, sem permitir alterações.

---

## Parte 3 — Gerar o executável e o instalador (primeira distribuição)

Faça isto na sua máquina Windows (o cliente não precisa de nada disso).

1. Crie um ambiente e instale as dependências de build:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements-build.txt
   ```

2. Gere o executável:

   ```bash
   pyinstaller semed.spec --noconfirm
   ```

   Resultado: `dist\SEMED Energia\SEMED Energia.exe` (com a pasta `_internal`).

3. Coloque o token junto do executável (sem o token, o auto-update do repositório
   **privado** não baixa). Com o token recém-copiado do GitHub (Parte 2.2),
   leia-o do clipboard — assim ele não passa pelo terminal nem pelo histórico:

   ```powershell
   Get-Clipboard | Set-Content -Path "dist\SEMED Energia\update_token.txt" -NoNewline -Encoding utf8
   ```

   Confira sem exibir o token (esperado: `True / True / ~90+`):

   ```powershell
   $t = (Get-Content "dist\SEMED Energia\update_token.txt" -Raw).Trim()
   "existe=$([bool]$t)  prefixo_ok=$($t.StartsWith('github_pat_'))  tamanho=$($t.Length)"
   ```

   > Alternativa: **Bloco de Notas** → salvar como `update_token.txt` (UTF-8), só o token.
   > Evite `echo token > arquivo` (grava em UTF-16 e corrompe a leitura). O app
   > tolera BOM (lê com `utf-8-sig`). O `.gitignore` já ignora `update_token.txt`.

4. Gere o instalador — pela interface (abra **`installer\semed.iss`** e **Compile** / F9)
   **ou** por linha de comando:

   ```powershell
   & "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" ".\installer\semed.iss"
   ```

   Saída: `installer\Output\SEMED-Energia-Setup-1.0.0.exe` (já com o token embutido).

5. **Esse `Setup.exe` é o que você entrega ao cliente.** Ele instala, cria o atalho e pronto.

> Teste antes de entregar: instale numa máquina/área limpa, abra, e confirme que o banco é criado em `%LOCALAPPDATA%\SEMED Energia\`.
>
> ⚠️ **Recompile o instalador sempre DEPOIS de colocar o token** — confira que o
> `LastWriteTime` do `Setup.exe` é posterior ao do `update_token.txt`. O token
> **sobrevive** a atualizações (o `robocopy` do updater não apaga arquivos ausentes no zip novo).

---

## Parte 4 — Publicar uma ATUALIZAÇÃO (toda vez que houver melhorias)

A `main` é protegida: a mudança entra **por Pull Request** e só então você cria a tag. O resto é automático.

1. Faça as mudanças numa branch e **suba a versão** em `version.py` (ex.: `1.0.0` → `1.0.1`):

   ```bash
   git checkout main && git pull
   git checkout -b chore/release-1.0.1
   # edite version.py:  __version__ = "1.0.1"
   git commit -am "chore(release): 1.0.1"
   git push -u origin chore/release-1.0.1
   gh pr create --base main --fill
   ```

2. Os checks do PR (`pr-title` + `sanity`) ficam verdes → faça **Squash and merge** pela interface.

3. Com a `main` atualizada, crie e empurre a **tag** (com `v` na frente):

   ```bash
   git checkout main && git pull
   git tag v1.0.1
   git push origin v1.0.1        # o hook libera tags; só bloqueia push direto na main
   ```

4. O **GitHub Actions** (`release.yml`) confere `tag == version.py`, builda o `.exe`, gera o `SEMED-Energia-windows.zip` e publica a **release** `v1.0.1`. Acompanhe com `gh run watch`.
5. Na próxima vez que **qualquer cliente** abrir o programa, ele detecta a versão nova, baixa (autenticado com o token), pergunta se quer atualizar, troca os arquivos e reinicia. ✅

> A tag **tem que bater** com `version.py` (o workflow falha de propósito se não bater).
>
> **1ª release:** pode ser direto `v1.0.0`, sem bump (o `version.py` já está em 1.0.0):
> `git checkout main && git pull && git tag v1.0.0 && git push origin v1.0.0`.

---

## Como funciona a auto-atualização (resumo técnico)

- Ao abrir, `ui/app.py` chama `updater.verificar()`.
- Ele consulta `releases/latest` no GitHub, compara com `version.__version__`.
- Se a remota for maior, baixa o `.zip` da release (autenticado com o token).
- Pergunta ao usuário; se aceito, extrai para uma pasta temporária e dispara um `.bat` que, após o app fechar, copia os arquivos novos por cima da instalação e reabre o programa.
- Falhou a internet/token? O app **abre normalmente** — a atualização nunca trava o uso.

---

## Solução de problemas

- **O app fechava sozinho ao importar uma fatura.** A partir desta versão isso não deve mais acontecer: erros inesperados na tela viram um aviso (e o programa continua aberto), e qualquer falha é gravada em
  `%LOCALAPPDATA%\SEMED Energia\logs\erros_ui.log`. Abra esse arquivo (ou peça ao cliente) para ver a causa exata.
  - Se o log mencionar falha ao carregar `fitz` / `_mupdf` / `DLL load failed`, instale na máquina o **Microsoft Visual C++ Redistributable (x64)**: <https://aka.ms/vs/17/release/vc_redist.x64.exe>
- **Importar uma pasta inteira:** na tela *Processar faturas*, use **Importar pasta…** para enfileirar de uma vez todos os PDFs de uma pasta (incluindo subpastas).

---

## Onde ficam os dados do cliente

```
%LOCALAPPDATA%\SEMED Energia\
├── semed_energia.db        ← banco SQLite (todos os dados)
├── entrada\  processados\  duplicados\  erros\
└── logs\
```

Atualizações tocam **apenas** os arquivos do programa em `C:\Program Files\SEMED Energia\`, nunca esta pasta. Para backup, basta copiar o `.db`.

---

## Checklist rápido

- [ ] Repositório privado criado e código no GitHub (sem dados/segredos).
- [ ] `update_config.py` com OWNER/REPO corretos.
- [ ] Token fine-grained (Contents: Read-only) gerado.
- [ ] `pyinstaller semed.spec --noconfirm` rodou sem erro.
- [ ] `update_token.txt` colocado em `dist\SEMED Energia\`.
- [ ] Instalador compilado no Inno Setup e testado numa máquina limpa.
- [ ] Hooks locais ativos: `git config core.hooksPath .githooks` (commit-msg + pre-push).
- [ ] Para cada nova versão: bump de `version.py` **via PR** → merge → `git tag vX.Y.Z` → `git push origin vX.Y.Z`.
