from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class TextoRequest(BaseModel):
    texto: str

@app.post("/analisar-projeto-texto")
async def analisar_projeto_texto(payload: TextoRequest):
    texto = payload.texto

    # Simulação simples de interpretação do texto
    if "CPI" in texto and "SPI" in texto:
        conclusao = (
            "📄 Relatório Executivo:\n\n"
            "O projeto apresenta indicadores de desempenho que requerem atenção. "
            "Recomenda-se análise detalhada dos riscos e replanejamento estratégico. "
            "A gestão deve agir preventivamente para evitar impactos reputacionais e garantir a entrega com qualidade e sustentabilidade."
        )
    else:
        conclusao = (
            "📄 Relatório Executivo:\n\n"
            "Dados insuficientes para gerar uma conclusão executiva. "
            "Por favor, revise as informações fornecidas e tente novamente."
        )

    return {"conclusao_executiva": conclusao}
