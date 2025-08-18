from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class TextoRequest(BaseModel):
    texto: str

def gerar_relatorio_executivo(texto: str) -> str:
    # Simulação de geração de relatório preditivo completo com base no texto
    # Em produção, aqui seria feita uma chamada a um modelo de linguagem (LLM)
    
    # Seções do relatório
    status_geral = "✅ Status Geral:\nO projeto está em andamento com desempenho moderado. Indicadores sugerem atenção preventiva."
    
    diagnostico = (
        "🔍 Diagnóstico de Performance:\n"
        "CPI indica custo acima do planejado. SPI mostra atraso no cronograma. "
        "Avanço físico e financeiro estão próximos, mas abaixo da meta. "
        "Contrato por preço unitário exige controle rigoroso. Risco médio identificado."
    )
    
    impactos = (
        "📈 Projeção de Impactos:\n"
        "Possíveis atrasos de até 2 meses e acréscimos de custo de 5 a 10%. "
        "Impacto operacional moderado e risco de comprometimento de metas estratégicas."
    )
    
    recomendacoes = (
        "🎯 Recomendações Estratégicas:\n"
        "Revisar cronograma e renegociar entregas. Estabelecer metas de CPI > 0.95 e SPI > 0.98. "
        "Aumentar supervisão e comunicação entre áreas envolvidas."
    )
    
    pilares_eck = (
        "🏛️ Avaliação de Pilar ECK:\n"
        "O projeto se enquadra no Pilar K (Alocação de Capital), pois visa reforço de infraestrutura com impacto direto na geração de valor. "
        "Também contribui para Pilar E (Excelência Organizacional) ao exigir alinhamento entre áreas. "
        "Não se enquadra diretamente no Pilar C (Foco no Cliente), pois não há interface direta com o consumidor final."
    )
    
    conclusao = (
        "🧠 Conclusão Executiva:\n"
        "O projeto apresenta riscos moderados e oportunidades de melhoria. "
        "Recomenda-se foco em capital e excelência organizacional para garantir entrega com eficiência e valor estratégico."
    )
    
    relatorio = (
        f"{status_geral}\n\n"
        f"{diagnostico}\n\n"
        f"{impactos}\n\n"
        f"{recomendacoes}\n\n"
        f"{pilares_eck}\n\n"
        f"{conclusao}"
    )
    
    return relatorio

@app.post("/analisar-projeto-texto")
async def analisar_projeto_texto(payload: TextoRequest):
    texto = payload.texto
    relatorio = gerar_relatorio_executivo(texto)
    return {"conclusao_executiva": relatorio}

