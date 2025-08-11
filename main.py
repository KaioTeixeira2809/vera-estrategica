from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict

app = FastAPI()

class ProjetoData(BaseModel):
    nome: str
    kpis: Dict[str, float]
    status: str
    stakeholders: List[str]
    tipo_contrato: str
    riscos: List[str]
    observacoes: str

class EstrategiaData(BaseModel):
    pilares: List[str]
    metas: Dict[str, str]

class AnaliseRequest(BaseModel):
    dados_projeto: ProjetoData
    dados_estrategicos: EstrategiaData

@app.post("/analisar-projeto")
async def analisar_projeto(payload: AnaliseRequest):
    projeto = payload.dados_projeto
    estrategia = payload.dados_estrategicos

    relatorio = {
        "relatorio": f"📄 Relatório Executivo de Análise Preditiva do Projeto: {projeto.nome}",
        "status": projeto.status,
        "avanço_físico": f"{projeto.kpis.get('fisico', 0)*100:.0f}%",
        "avanço_financeiro": f"{projeto.kpis.get('financeiro', 0)*100:.0f}%",
        "riscos_declarados": "Não" if not projeto.riscos else "Sim",
        "observacoes": projeto.observacoes,
        "kpis": {
            "CPI": projeto.kpis.get("cpi", 0),
            "SPI": projeto.kpis.get("spi", 0),
            "Índice de Risco": "Alto" if projeto.kpis.get("spi", 0) < 0.8 else "Moderado",
            "Status Geral": "Crítico" if projeto.kpis.get("spi", 0) < 0.8 else "Estável"
        },
        "diagnostico_estrategico": [
            "SPI abaixo de 0.8 indica atraso no cronograma.",
            "Ausência de riscos declarados pode mascarar gargalos operacionais.",
            "Ritmo acelerado pode comprometer a qualidade da instalação."
        ],
        "tipologia_contratual": f"Contrato do tipo {projeto.tipo_contrato}, com penalidades por atraso e cláusulas restritas de força maior.",
        "stakeholders": [
            {"Stakeholder": s, "Interesse": "Alto", "Influência": "Médio"} for s in projeto.stakeholders
        ],
        "projecao_impactos": [
            "Atraso de até 60 dias",
            "Risco de não conformidade ambiental",
            "Pressão de investidores por revisão de metas"
        ],
        "plano_retomada": [
            {"Fase": "Fase 1", "Ação": "Auditoria de qualidade", "Prazo Estimado": "+5 dias"},
            {"Fase": "Fase 2", "Ação": "Replanejamento técnico", "Prazo Estimado": "+7 dias"},
            {"Fase": "Fase 3", "Ação": "Ajustes operacionais", "Prazo Estimado": "+15 dias"}
        ],
        "metricas_sucesso": [
            "SPI ≥ 0.85 até o próximo marco",
            "Zero não conformidades ambientais",
            "Satisfação dos stakeholders ≥ 90%"
        ],
        "conclusao_executiva": f"O projeto '{projeto.nome}' apresenta risco operacional oculto. A gestão deve agir preventivamente para evitar impactos reputacionais e garantir a entrega com qualidade e sustentabilidade."
    }

    return relatorio
