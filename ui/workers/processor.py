"""
Worker de processamento de PDFs chamado pela UI.

Pipeline por PDF (igual ao main.py):
    1. SHA-256 do arquivo                          (Camada 1 de dedup)
    2. Classifier PyMuPDF                          (tipos de pagina + CNPJ)
    3. Parser da capa
    4. Documento da capa                           (Camada 2 de dedup)
    5. Parser B3 e A4
    6. Nota fiscal por fatura                      (Camada 3 de dedup)
    7. Validacao de integridade
    8. Persistencia transacional no SQLite
    9. Registra arquivo_processado

Se o banco nao estiver disponivel, cai em modo dry-run automaticamente e
avisa no log — nada quebra.
"""
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal


# =============================================================
# Helpers de serializacao (dataclass -> dict)
# =============================================================

def _f(v):
    return float(v) if v is not None else None


def _serializar_fatura(f):
    return {
        "nota_fiscal": f.nota_fiscal,
        "fatura_numero": f.fatura_numero,
        "instalacao": f.instalacao,
        "nome_unidade": f.nome_unidade,
        "nome": f.nome,
        "endereco": f.endereco,
        "bairro": f.bairro,
        "municipio": f.municipio,
        "unidade_leitura": f.unidade_leitura,
        "conj_contrato": f.conj_contrato,
        "local": f.local,
        "empresa": f.empresa,
        "referencia": f.referencia,
        "classe_principal": f.classe_principal,
        "classe_consumo": f.classe_consumo,
        "tensao": f.tensao,
        "fase": _f(f.fase),
        "data_faturamento": str(f.data_faturamento) if f.data_faturamento else "",
        "dias_faturamento": f.dias_faturamento,
        "data_leitura_anterior": str(f.data_leitura_anterior) if f.data_leitura_anterior else "",
        "data_leitura_atual": str(f.data_leitura_atual) if f.data_leitura_atual else "",
        "data_apresentacao": str(f.data_apresentacao) if f.data_apresentacao else "",
        "data_vencimento": str(f.data_vencimento) if f.data_vencimento else "",
        "data_recolhimento": str(f.data_recolhimento) if f.data_recolhimento else "",
        "hash_code": f.hash_code,
        "valor": _f(f.valor) or 0,
        "dias": f.dias_faturamento,
        "data_leitura": str(f.data_leitura_atual) if f.data_leitura_atual else "",
        "consumo_kwh": float(sum(
            (v.quantidade or 0) for v in f.valores_faturados
            if v.descricao and v.descricao.startswith("Consumo")
        )),
        "tributos": [
            {"tipo": t.tipo, "base_calculo": _f(t.base_calculo),
             "aliquota": _f(t.aliquota), "valor": _f(t.valor)}
            for t in f.tributos
        ],
        "valores_faturados": [
            {"descricao": v.descricao, "quantidade": _f(v.quantidade),
             "preco": _f(v.preco), "valor": _f(v.valor)}
            for v in f.valores_faturados
        ],
        "valores_medidos": [
            {"especie": v.especie, "medidor": v.medidor,
             "constante": _f(v.constante), "perc_fp": _f(v.perc_fp),
             "leitura_anterior": _f(v.leitura_anterior),
             "leitura_atual": _f(v.leitura_atual),
             "medido": _f(v.medido), "faturado": _f(v.faturado)}
            for v in f.valores_medidos
        ],
    }


# =============================================================
# Worker
# =============================================================

class ProcessadorWorker(QThread):
    log = Signal(str, str)           # (texto, nivel)
    progresso = Signal(int, int)     # (atual, total)
    fatura_progresso = Signal(str, int, int)  # pdf_name, extraidas, esperadas
    arquivo_concluido = Signal(object) # dados do pdf processado
    concluido = Signal(object)         # estatisticas finais
    banco_atualizado = Signal()      # emit apos pelo menos 1 commit

    def __init__(self, pdfs: list, persistir: bool = True,
                 reprocessar_documentos: bool = False):
        """
        :param persistir: se True (default), grava no banco. Se False ou se o
                          banco estiver offline, roda em dry-run (so extrai e
                          mostra no log).
        :param reprocessar_documentos: se True, antes de processar cada PDF
                          tenta remover do banco a agrupadora com o mesmo
                          documento (via repository.reprocessar_documento),
                          permitindo reimportar PDFs ja importados.
        """
        super().__init__()
        self.pdfs = pdfs
        self.persistir = persistir
        self.reprocessar_documentos = reprocessar_documentos
        self._cancel = False

    def cancelar(self):
        """Solicita cancelamento cooperativo do processamento."""
        self._cancel = True
        # QThread.requestInterruption sinaliza via API nativa do Qt;
        # eh util para callers externos (ex.: closeEvent da MainWindow).
        self.requestInterruption()

    def _deve_cancelar(self) -> bool:
        return self._cancel or self.isInterruptionRequested()

    # ----------------------------------------------------

    def run(self):
        # O coletor de lixo cíclico do Python, ao disparar DENTRO desta QThread,
        # pode tocar/finalizar objetos Qt/PySide (que têm afinidade de thread) e
        # causar "access violation" durante a leitura de PDF (crash sem log no
        # app empacotado). Desligamos o GC automático durante o processamento —
        # o refcounting continua liberando a maior parte da memória — e
        # reabilitamos ao final.
        import gc
        _gc_ativo = gc.isenabled()
        gc.disable()
        try:
            self._executar()
        finally:
            if _gc_ativo:
                gc.enable()

    def _executar(self):
        import gc
        root = Path(__file__).resolve().parent.parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        # Imports protegidos: se um componente nativo (ex.: PyMuPDF/`fitz`,
        # que depende do runtime do Visual C++) falhar ao carregar na máquina
        # do cliente, NÃO deixamos a exceção subir na QThread — isso derrubaria
        # o app inteiro. Em vez disso, logamos e encerramos limpo.
        try:
            from utils.file_manager import calcular_hash_sha256
            from parser.classifier import classificar_pdf
            from parser.capa_parser import parsear_capa
            from parser.detalhe_parser import parsear_pagina_b3, parsear_pagina_a4
            from validator.integrity import validar_tudo
            import fitz  # PyMuPDF — abrimos 1x e reutilizamos
            import pdfplumber
        except Exception as e:
            traceback.print_exc()
            self.log.emit(
                f"✗ Falha ao carregar os componentes de leitura de PDF: {e}. "
                f"No cliente, instale o 'Microsoft Visual C++ Redistributable (x64)'.",
                "error",
            )
            self.concluido.emit({
                "importados": 0, "duplicados_hash": 0, "duplicados_doc": 0,
                "duplicados_nf": 0, "erros": len(self.pdfs), "faturas_total": 0,
                "warnings": 0, "persistido": False,
            })
            return

        # Tentar conectar no banco
        session = None
        detector = None
        if self.persistir:
            try:
                from db.connection import get_session, testar_conexao
                from dedup.detector import DuplicataDetector
                testar_conexao()
                session = get_session()
                detector = DuplicataDetector(session)
                self.log.emit("● Banco conectado — modo persistência ativo", "ok")
            except Exception as e:
                self.log.emit(
                    f"⚠ Banco indisponível ({e}). Rodando em dry-run.", "warn"
                )
                session = None
                detector = None

        stats = {
            "importados": 0,
            "duplicados_hash": 0,
            "duplicados_doc": 0,
            "duplicados_nf": 0,
            "erros": 0,
            "faturas_total": 0,
            "warnings": 0,
            "persistido": False,
        }

        houve_commit = False

        for i, pdf in enumerate(self.pdfs, 1):
            if self._deve_cancelar():
                self.log.emit(f"⏹ Cancelado antes de {pdf.name}", "warn")
                break
            # Coleta de lixo controlada entre PDFs (estado limpo) — limita a
            # memória em pastas grandes sem o GC automático disparar mid-parse.
            gc.collect()
            self.progresso.emit(i, len(self.pdfs))
            self.log.emit(f"── {pdf.name} ──", "title")

            try:
                # ---- Hash (Camada 1) ----
                file_hash = calcular_hash_sha256(pdf)
                tamanho = pdf.stat().st_size

                if detector is not None:
                    r = detector.verificar_por_hash(file_hash)
                    if r.eh_duplicata:
                        self.log.emit(f"⊘ DUP-HASH: {r.mensagem}", "warn")
                        try:
                            from db.repository import registrar_arquivo
                            registrar_arquivo(
                                session, pdf.name, file_hash,
                                resultado="duplicado_hash",
                                tamanho_bytes=tamanho,
                                documento=r.documento_existente,
                            )
                            session.commit()
                        except Exception:
                            session.rollback()
                        stats["duplicados_hash"] += 1
                        continue

                if self._deve_cancelar():
                    self.log.emit(f"⏹ Cancelado em {pdf.name} (pre-classifier)", "warn")
                    break

                # ---- Classifier + parser capa (abrimos fitz 1x) ----
                try:
                    fitz_doc = fitz.open(str(pdf))
                except Exception as ex:
                    raise RuntimeError(f"Erro ao abrir PDF: {ex}")
                try:
                    cls = classificar_pdf(pdf, doc=fitz_doc)
                    if cls.erro:
                        raise RuntimeError(f"classifier: {cls.erro}")
                    if not cls.eh_equatorial:
                        raise RuntimeError("PDF não é da Equatorial Pará")

                    capa = parsear_capa(pdf, doc=fitz_doc)
                finally:
                    fitz_doc.close()
                self.log.emit(
                    f"Capa: {capa.complemento} | doc {capa.documento} | "
                    f"R$ {capa.valor_total} | {capa.qtd_faturas_esperada} faturas",
                    "info",
                )

                # ---- Reprocessamento explicito ----
                # Se o usuario pediu reprocessar_documentos e este doc ja existe
                # no banco, removemos agrupadora + faturas + registro de arquivo
                # ANTES de rodar as camadas 2/3 de dedup. Assim o PDF pode ser
                # reimportado do zero sem cair em DUP-DOC.
                if (self.reprocessar_documentos and session is not None
                        and capa.documento):
                    try:
                        from db.repository import reprocessar_documento
                        removido = reprocessar_documento(session, capa.documento)
                        if removido:
                            session.commit()
                            self.log.emit(
                                f"♻ Reprocesso: doc {capa.documento} removido "
                                f"do banco — sera reimportado",
                                "warn",
                            )
                    except Exception as ex:
                        session.rollback()
                        self.log.emit(
                            f"⚠ Falha ao limpar doc {capa.documento} para "
                            f"reprocesso: {ex}",
                            "warn",
                        )

                # ---- Documento (Camada 2) ----
                if detector is not None and capa.documento:
                    r = detector.verificar_documento(capa.documento)
                    if r.eh_duplicata:
                        self.log.emit(f"⊘ DUP-DOC: {r.mensagem}", "warn")
                        try:
                            from db.repository import registrar_arquivo
                            registrar_arquivo(
                                session, pdf.name, file_hash,
                                resultado="duplicado_doc",
                                tamanho_bytes=tamanho,
                                documento=capa.documento,
                                agrupadora_id=r.agrupadora_id,
                            )
                            session.commit()
                        except Exception:
                            session.rollback()
                        stats["duplicados_doc"] += 1
                        continue

                # ---- Parsers B3 / A4 (+ Camada 3) ----
                faturas = []
                with pdfplumber.open(str(pdf)) as pdf_obj:
                    for p in cls.paginas:
                        if p.tipo == "detalhe_b3":
                            for f in parsear_pagina_b3(pdf_obj.pages[p.numero], p.numero):
                                if detector and f.nota_fiscal:
                                    r = detector.verificar_nota_fiscal(f.nota_fiscal)
                                    if r.eh_duplicata:
                                        self.log.emit(
                                            f"  ↳ nota {f.nota_fiscal} já existe (skip)",
                                            "warn",
                                        )
                                        stats["duplicados_nf"] += 1
                                        continue
                                faturas.append(f)
                        elif p.tipo == "detalhe_a4":
                            f = parsear_pagina_a4(pdf_obj.pages[p.numero], p.numero)
                            if f is None:
                                continue
                            if detector and f.nota_fiscal:
                                r = detector.verificar_nota_fiscal(f.nota_fiscal)
                                if r.eh_duplicata:
                                    self.log.emit(
                                        f"  ↳ nota {f.nota_fiscal} já existe (skip)",
                                        "warn",
                                    )
                                    stats["duplicados_nf"] += 1
                                    continue
                            faturas.append(f)

                self.fatura_progresso.emit(
                    pdf.name, len(faturas), capa.qtd_faturas_esperada or 0
                )

                # ---- Validacao ----
                resumo = validar_tudo(capa, faturas, eh_equatorial=cls.eh_equatorial)
                vs = resumo.estatisticas()
                self.log.emit(
                    f"Validação: OK={vs['ok']} WARN={vs['warn']} ERRO={vs['erro']}",
                    "info",
                )
                if not resumo.pode_persistir:
                    for e in resumo.erros:
                        self.log.emit(f"  ✗ {e.mensagem}", "error")
                    raise RuntimeError(
                        "Validação estrutural falhou — não persiste"
                    )

                # ---- Persistencia transacional ----
                if session is not None:
                    try:
                        from db.repository import (
                            salvar_agrupadora, salvar_fatura_individual,
                            registrar_arquivo, atualizar_status_agrupadora,
                        )
                        ag = salvar_agrupadora(session, capa, arquivo_origem=pdf.name)
                        erros_fatura = []
                        for f in faturas:
                            try:
                                salvar_fatura_individual(session, ag.id, f)
                            except Exception as ex:
                                erros_fatura.append(f"NF {f.nota_fiscal}: {ex}")

                        status = "incompleta" if erros_fatura else "completa"
                        atualizar_status_agrupadora(
                            session, ag.id, status,
                            faturas_importadas=len(faturas) - len(erros_fatura),
                            faturas_com_erro=len(erros_fatura),
                            erros_log="\n".join(erros_fatura) if erros_fatura else None,
                        )
                        registrar_arquivo(
                            session, pdf.name, file_hash,
                            resultado="importado",
                            tamanho_bytes=tamanho,
                            documento=capa.documento,
                            agrupadora_id=ag.id,
                        )
                        session.commit()
                        houve_commit = True
                        self.log.emit(
                            f"✓ Persistido: {len(faturas)} fatura(s) "
                            + ("com erros" if erros_fatura else "OK"),
                            "ok",
                        )
                    except Exception as e:
                        session.rollback()
                        raise RuntimeError(f"erro ao persistir: {e}")

                stats["importados"] += 1
                stats["faturas_total"] += len(faturas)
                stats["warnings"] += vs["warn"]

                # Emit item para UI em tempo real
                item = {
                    "pdf": pdf.name,
                    "hash": file_hash[:16],
                    "capa": {
                        "documento": capa.documento,
                        "complemento": capa.complemento,
                        "referencia": capa.referencia,
                        "conta_contrato": capa.conta_contrato,
                        "valor_total": float(capa.valor_total or 0),
                        "qtd_esperada": capa.qtd_faturas_esperada,
                    },
                    "faturas_extraidas": len(faturas),
                    "validacao": vs,
                    "warnings": [
                        {"camada": w.camada, "tipo": w.tipo, "nota": w.fatura_nota,
                         "mensagem": w.mensagem}
                        for w in resumo.warnings
                    ],
                    "erros": [
                        {"camada": e.camada, "tipo": e.tipo, "mensagem": e.mensagem}
                        for e in resumo.erros
                    ],
                    "faturas": [_serializar_fatura(f) for f in faturas],
                }
                self.arquivo_concluido.emit(item)

            except Exception as e:
                stats["erros"] += 1
                self.log.emit(f"✗ ERRO em {pdf.name}: {e}", "error")
                traceback.print_exc()
                if session is not None:
                    try:
                        session.rollback()
                        from db.repository import registrar_arquivo
                        registrar_arquivo(
                            session, pdf.name,
                            calcular_hash_sha256(pdf) if pdf.exists() else "",
                            resultado="erro",
                            tamanho_bytes=pdf.stat().st_size if pdf.exists() else 0,
                        )
                        session.commit()
                    except Exception:
                        session.rollback()

        if session is not None:
            try:
                session.close()
            except Exception:
                pass

        stats["persistido"] = houve_commit
        if houve_commit:
            self.banco_atualizado.emit()
        self.concluido.emit(stats)
