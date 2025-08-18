from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class TextoRequest(BaseModel):
    texto: str

@app.post("/analisar-projeto-texto")
async def analisar_projeto_texto(payload: TextoRequest):
    texto = payload.texto

    # Simulação de interpretação avançada do texto
    # Extração de dados básicos
    nome_projeto = "Projeto não identificado"
    cpi = spi = fisico = financeiro = contrato = stakeholders = observacoes = pilar = "Não informado"

    linhas = texto.splitlines()
    for linha in linhas:
        if "Nome do Projeto" in linha:
            nome_projeto = linha.split(":", 1)[-1].strip()
        elif "CPI" in linha:
            cpi = linha.split(":", 1)[-1].strip()
        elif "SPI" in linha:
            spi = linha.split(":", 1)[-1].strip()
        elif "Avanço Físico" in linha:
            fisico = linha.split(":", 1)[-1].strip()
        elif "Avanço Financeiro" in linha:
            financeiro = linha.split(":", 1)[-1].strip()
        elif "Tipo de Contrato" in linha:
            contrato = linha.split(":", 1)[-1].strip()
        elif "Stakeholders" in linha:
            stakeholders = linha.split(":", 1)[-1].strip()
        elif "Observações" in linha:
            observacoes = linha.split(":", 1)[-1].strip()
        elif "Pilar" in linha:
            pilar = linha.split(":", 1)[-1].strip()

    # Geração do relatório formatado
    relatorio = f"""📊 Relatório Executivo Preditivo – Projeto “{nome_projeto}”

✅ Status Geral
CPI (Índice de Desempenho de Custo): {cpi}
SPI (Índice de Desempenho de Cronograma): {spi}
Avanço Físico: {fisico}
Avanço Financeiro: {financeiro}
Tipo de Contrato: {contrato}
Stakeholders: {stakeholders}
Status Atual: Em andamento, com risco identificado.
Observação: {observacoes}

📈 Diagnóstico de Performance
Custo: CPI em {cpi} indica necessidade de atenção ao controle orçamentário.
Prazo: SPI em {spi} sugere atraso no cronograma.
Execução Física/Financeira: Avanço físico ({fisico}) e financeiro ({financeiro}) indicam progresso moderado.
Contrato: Tipo de contrato "{contrato}" requer atenção à gestão de escopo e custos.
Risco: Avaliação baseada nas observações indica risco relevante.

📅 Projeção de Impactos
Curto Prazo: Possibilidade de atrasos adicionais e pressão sobre custos.
Médio Prazo: Potencial impacto na entrega e metas estratégicas.
Stakeholders: {stakeholders} devem intensificar monitoramento e comunicação.

🧭 Recomendações Estratégicas
Revisar cronograma e renegociar entregas.
Estabelecer metas de CPI ≥ 0.90 e SPI ≥ 0.95.
Reforçar integração entre áreas e controle de produtividade.

🏛 Avaliação de Pilar ECK
Pilar declarado: {pilar}

Justificativa:
O projeto apresenta características que podem se enquadrar em múltiplos pilares. A classificação como "{pilar}" deve ser avaliada considerando os objetivos estratégicos, disciplina financeira e eficiência organizacional.

✅ Resumo Executivo Final
O Projeto “{nome_projeto}” apresenta riscos moderados e oportunidades de melhoria. Recomenda-se foco estratégico no Pilar "{pilar}" com ações corretivas para garantir entrega com eficiência e valor.
"""

    return {"conclusao_executiva": relatorio}

