"""
Modelos SQLAlchemy para o banco SEMED Energia.
Espelham exatamente o DDL em db/migrations/001_initial.sql.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Column, Integer, SmallInteger, String, Date, DateTime, Numeric, Text,
    BigInteger, ForeignKey, UniqueConstraint,
)
from sqlalchemy import JSON
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class ArquivoProcessado(Base):
    __tablename__ = "arquivo_processado"

    id = Column(Integer, primary_key=True)
    nome_original = Column(String(500), nullable=False)
    nome_padronizado = Column(String(500))
    hash_sha256 = Column(String(64), nullable=False, unique=True)
    tamanho_bytes = Column(BigInteger)
    documento = Column(String(20))
    agrupadora_id = Column(Integer, ForeignKey("fatura_agrupadora.id", ondelete="SET NULL"))
    processado_em = Column(DateTime, default=datetime.now)
    resultado = Column(String(20), nullable=False)

    agrupadora = relationship("FaturaAgrupadora", back_populates="arquivos")


class FaturaAgrupadora(Base):
    __tablename__ = "fatura_agrupadora"

    id = Column(Integer, primary_key=True)
    documento = Column(String(20), nullable=False, unique=True)
    referencia = Column(String(10), nullable=False)
    complemento = Column(String(50))
    conta_contrato = Column(String(20))
    cliente_nome = Column(String(200))
    cliente_cnpj = Column(String(20))
    parceiro_negocio = Column(String(20))
    emissao = Column(Date)
    apresentacao = Column(Date)
    vencimento = Column(Date)
    valor_total = Column(Numeric(15, 2))
    qtd_faturas_esperada = Column(Integer)

    # Energia/Tributos consolidados
    consumo_qtd = Column(Numeric(15, 2))
    consumo_valor = Column(Numeric(15, 2))
    consumo_ponta_qtd = Column(Numeric(15, 2))
    consumo_ponta_valor = Column(Numeric(15, 2))
    consumo_fp_qtd = Column(Numeric(15, 2))
    consumo_fp_valor = Column(Numeric(15, 2))
    demanda_ativa_qtd = Column(Numeric(15, 2))
    demanda_ativa_valor = Column(Numeric(15, 2))
    demanda_ultra_qtd = Column(Numeric(15, 2))
    demanda_ultra_valor = Column(Numeric(15, 2))
    consumo_reat_exc_qtd = Column(Numeric(15, 2))
    consumo_reat_exc_valor = Column(Numeric(15, 2))
    consumo_reat_exc_np_qtd = Column(Numeric(15, 2))
    consumo_reat_exc_np_valor = Column(Numeric(15, 2))
    consumo_reat_exc_fp_qtd = Column(Numeric(15, 2))
    consumo_reat_exc_fp_valor = Column(Numeric(15, 2))
    adicional_bandeira = Column(Numeric(15, 2))
    icms_total = Column(Numeric(15, 2))
    cofins_total = Column(Numeric(15, 2))
    pis_total = Column(Numeric(15, 2))
    subtotal_1 = Column(Numeric(15, 2))

    # Lançamentos e Serviços
    trib_reter_irpj = Column(Numeric(15, 2))
    trib_reter_pis = Column(Numeric(15, 2))
    trib_reter_cofins = Column(Numeric(15, 2))
    trib_reter_csll = Column(Numeric(15, 2))
    credito_dic_fic_dmic = Column(Numeric(15, 2))
    cip_ilum_pub = Column(Numeric(15, 2))
    subtotal_2 = Column(Numeric(15, 2))

    # Demonstrativo
    demo_energia = Column(Numeric(15, 2))
    demo_transmissao = Column(Numeric(15, 2))
    demo_distribuicao = Column(Numeric(15, 2))
    demo_enc_setoriais = Column(Numeric(15, 2))
    demo_tributos = Column(Numeric(15, 2))
    demo_soma = Column(Numeric(15, 2))

    # ICMS Composição
    icms_base_calculo = Column(Numeric(15, 2))
    icms_aliquota = Column(Numeric(8, 4))
    icms_valor = Column(Numeric(15, 2))

    # Campos históricos (Fase 2) — ver migration 004_campos_historicos.sql
    # Layout 2020/2021: bandeira tarifária separada por cor
    bandeira_amarela     = Column(Numeric(15, 2))
    bandeira_vermelha    = Column(Numeric(15, 2))
    # Layout 2020/2021: encargos por atraso de pagamento
    correcao_monetaria   = Column(Numeric(15, 2))
    multa                = Column(Numeric(15, 2))
    juros                = Column(Numeric(15, 2))
    # Layout 2022+: crédito de devolução ICMS LC 194/2022
    devolucao_icms_lc194 = Column(Numeric(15, 2))
    # Layout 2024+: diferença de bandeira tarifária
    diferenca_bandeira   = Column(Numeric(15, 2))
    # Versão de layout detectada pelo parser
    versao_layout        = Column(String(10))

    # Hierarquia temporal (Fase 3) — ver migration 005_indexacao_temporal.sql
    ano              = Column(SmallInteger)
    mes              = Column(SmallInteger)
    complemento_norm = Column(String(20))

    __table_args__ = (
        UniqueConstraint("ano", "mes", "complemento_norm", name="ux_ag_ano_mes_comp"),
    )

    # Controle
    status = Column(String(20), nullable=False, default="pendente")
    faturas_importadas = Column(Integer, default=0)
    faturas_com_erro = Column(Integer, default=0)
    arquivo_origem = Column(String(500))
    importado_em = Column(DateTime, default=datetime.now)
    atualizado_em = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    erros_log = Column(Text)

    # Relacionamentos
    faturas = relationship("FaturaIndividual", back_populates="agrupadora",
                           cascade="all, delete-orphan")
    arquivos = relationship("ArquivoProcessado", back_populates="agrupadora")
    validacoes = relationship("ValidacaoResultado", back_populates="agrupadora",
                              cascade="all, delete-orphan",
                              foreign_keys="ValidacaoResultado.agrupadora_id")

    def __repr__(self):
        return f"<Agrupadora {self.documento} | {self.complemento} | {self.referencia}>"


class FaturaIndividual(Base):
    __tablename__ = "fatura_individual"

    id = Column(Integer, primary_key=True)
    agrupadora_id = Column(Integer, ForeignKey("fatura_agrupadora.id", ondelete="CASCADE"),
                           nullable=False)
    nota_fiscal = Column(String(30), nullable=False, unique=True)
    fatura_numero = Column(String(30))
    instalacao = Column(String(20), nullable=False)
    nome_unidade = Column(String(200))
    endereco = Column(String(300))
    bairro = Column(String(100))
    municipio = Column(String(100))
    unidade_leitura = Column(String(20))
    conj_contrato = Column(String(20))
    classe_principal = Column(String(10))
    classe_consumo = Column(String(20))
    tensao = Column(String(5))
    fase = Column(Numeric(4, 2))
    data_faturamento = Column(Date)
    dias_faturamento = Column(Integer)
    data_leitura_anterior = Column(Date)
    data_leitura_atual = Column(Date)
    hash_code = Column(String(100))
    data_apresentacao = Column(Date)
    data_vencimento = Column(Date)
    data_recolhimento = Column(Date)
    valor = Column(Numeric(15, 2))
    # Soma dos `valor_faturado` cuja descricao comeca com "Consumo".
    # Persistido (em vez de recomputado a cada carga da UI) para evitar
    # custo O(N) por fatura em `carregar_itens_da_base`.
    consumo_kwh = Column(Numeric(15, 2))
    importado_em = Column(DateTime, default=datetime.now)

    # Relacionamentos
    agrupadora = relationship("FaturaAgrupadora", back_populates="faturas")
    tributos = relationship("Tributo", back_populates="fatura",
                            cascade="all, delete-orphan")
    valores_faturados = relationship("ValorFaturado", back_populates="fatura",
                                     cascade="all, delete-orphan")
    valores_medidos = relationship("ValorMedido", back_populates="fatura",
                                   cascade="all, delete-orphan")
    validacoes = relationship("ValidacaoResultado", back_populates="fatura",
                              cascade="all, delete-orphan",
                              foreign_keys="ValidacaoResultado.fatura_individual_id")

    def __repr__(self):
        return f"<Fatura {self.nota_fiscal} | {self.nome_unidade} | R${self.valor}>"


class Tributo(Base):
    __tablename__ = "tributo"

    id = Column(Integer, primary_key=True)
    fatura_individual_id = Column(Integer, ForeignKey("fatura_individual.id", ondelete="CASCADE"),
                                  nullable=False)
    tipo = Column(String(20), nullable=False)
    base_calculo = Column(Numeric(15, 2))
    aliquota = Column(Numeric(8, 4))
    valor = Column(Numeric(15, 2))

    fatura = relationship("FaturaIndividual", back_populates="tributos")


class ValorFaturado(Base):
    __tablename__ = "valor_faturado"

    id = Column(Integer, primary_key=True)
    fatura_individual_id = Column(Integer, ForeignKey("fatura_individual.id", ondelete="CASCADE"),
                                  nullable=False)
    descricao = Column(String(100), nullable=False)
    quantidade = Column(Numeric(15, 2))
    preco = Column(Numeric(15, 6))
    valor = Column(Numeric(15, 2))

    fatura = relationship("FaturaIndividual", back_populates="valores_faturados")


class ValorMedido(Base):
    __tablename__ = "valor_medido"

    id = Column(Integer, primary_key=True)
    fatura_individual_id = Column(Integer, ForeignKey("fatura_individual.id", ondelete="CASCADE"),
                                  nullable=False)
    especie = Column(String(10), nullable=False)
    medidor = Column(String(30))
    constante = Column(Numeric(10, 2))
    perc_fp = Column(Numeric(6, 2))
    leitura_anterior = Column(Numeric(15, 2))
    leitura_atual = Column(Numeric(15, 2))
    medido = Column(Numeric(15, 2))
    faturado = Column(Numeric(15, 2))

    fatura = relationship("FaturaIndividual", back_populates="valores_medidos")


class LogImportacao(Base):
    __tablename__ = "log_importacao"

    id = Column(Integer, primary_key=True)
    arquivo = Column(String(500), nullable=False)
    inicio = Column(DateTime, nullable=False)
    fim = Column(DateTime)
    status = Column(String(20))
    total_arquivos = Column(Integer)
    importados = Column(Integer)
    duplicados = Column(Integer)
    com_erro = Column(Integer)
    mensagem = Column(Text)
    detalhes = Column(JSON)


class ValidacaoResultado(Base):
    __tablename__ = "validacao_resultado"

    id = Column(Integer, primary_key=True)
    agrupadora_id = Column(Integer, ForeignKey("fatura_agrupadora.id", ondelete="CASCADE"))
    fatura_individual_id = Column(Integer, ForeignKey("fatura_individual.id", ondelete="CASCADE"))
    camada = Column(Integer, nullable=False)
    tipo = Column(String(50), nullable=False)
    resultado = Column(String(10), nullable=False)
    valor_esperado = Column(Numeric(15, 2))
    valor_encontrado = Column(Numeric(15, 2))
    diferenca = Column(Numeric(15, 2))
    mensagem = Column(Text)
    validado_em = Column(DateTime, default=datetime.now)

    agrupadora = relationship("FaturaAgrupadora", back_populates="validacoes",
                              foreign_keys=[agrupadora_id])
    fatura = relationship("FaturaIndividual", back_populates="validacoes",
                          foreign_keys=[fatura_individual_id])
