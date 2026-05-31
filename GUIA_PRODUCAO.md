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

Abra **`update_config.py`** e edite:

```python
GITHUB_OWNER = "SEU_USUARIO_OU_ORG"   # seu usuário/organização no GitHub
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

3. Coloque o token junto do executável (para os updates funcionarem no cliente).
   Use o **Bloco de Notas** (Arquivo → Salvar como → `update_token.txt`, contendo
   só o token) **ou** o PowerShell com codificação explícita:

   ```powershell
   "SEU_TOKEN_AQUI" | Out-File -Encoding utf8 "dist\SEMED Energia\update_token.txt"
   ```

   > Evite `echo token > arquivo` no PowerShell: ele grava em UTF-16 e pode
   > corromper a leitura. O app lê o arquivo tolerando BOM (utf-8-sig).

4. Gere o instalador: abra **`installer\semed.iss`** no Inno Setup e clique **Compile** (F9).
   Saída: `installer\Output\SEMED-Energia-Setup-1.0.0.exe`.

5. **Esse `Setup.exe` é o que você entrega ao cliente.** Ele instala, cria o atalho e pronto.

> Teste antes de entregar: instale numa máquina/área limpa, abra, e confirme que o banco é criado em `%LOCALAPPDATA%\SEMED Energia\`.

---

## Parte 4 — Publicar uma ATUALIZAÇÃO (toda vez que houver melhorias)

Depois da primeira entrega, atualizar é simples e **automático**:

1. Faça suas mudanças no código.
2. **Suba o número da versão** em `version.py` (ex.: `1.0.0` → `1.0.1`).
3. Faça commit e crie a **tag** correspondente (com `v` na frente):

   ```bash
   git add .
   git commit -m "Correções e melhorias"
   git tag v1.0.1
   git push origin main --tags
   ```

4. O **GitHub Actions** (workflow `release.yml`) builda sozinho, gera o `SEMED-Energia-windows.zip` e publica a **release** `v1.0.1`.
5. Na próxima vez que **qualquer cliente** abrir o programa, ele detecta a versão nova, baixa, pergunta se quer atualizar, troca os arquivos e reinicia. ✅

> A tag **tem que bater** com `version.py` (o workflow falha de propósito se não bater, para evitar erro).

---

## Como funciona a auto-atualização (resumo técnico)

- Ao abrir, `ui/app.py` chama `updater.verificar()`.
- Ele consulta `releases/latest` no GitHub, compara com `version.__version__`.
- Se a remota for maior, baixa o `.zip` da release (autenticado com o token).
- Pergunta ao usuário; se aceito, extrai para uma pasta temporária e dispara um `.bat` que, após o app fechar, copia os arquivos novos por cima da instalação e reabre o programa.
- Falhou a internet/token? O app **abre normalmente** — a atualização nunca trava o uso.

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
- [ ] Para cada nova versão: subir `version.py`, commit, `git tag vX.Y.Z`, push.
