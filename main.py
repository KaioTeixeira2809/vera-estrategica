from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import unicodedata
import html

# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# Vera Estratégica API - v1.3.0 (Kaio)
# - Divergência de Pilar: declarado x sugerido (inferido)
# - Duas opções de Próximos Passos: (Recomendado) e (Atual/declarado)
# - Seção "Riscos-chave identificados" (bullets claros)
# - Retorno compatível com A360: conclusao_executiva (TXT) + MD + HTML
# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

app = FastAPI(title="Vera Estratégica API", version="1.3.0")

# -------------------------------------------------------------------------
# Models
# -------------------------------------------------------------------------
class TextoRequest(BaseModel):
    texto: str

class ProjetoRequest(BaseModel):
    nome_projeto: Optional[str] = None
    cpi: Optional[str] = None
    spi: Optional[str] = None
    avanco_fisico: Optional[str] = None
    avanco_financeiro: Optional[str] = None
    tipo_contrato: Optional[str] = None
    stakeholders: Optional[str] = None
    observacoes: Optional[str] = None
    pilar: Optional[str] = None

# -------------------------------------------------------------------------
# Helpers de normalização e parsing
# -------------------------------------------------------------------------
def normalize(s: Optional[str]) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.lower().strip()

def to_number(s: Optional[str]) -> Optional[float]:
    """Aceita '0,88', '0.88', '1.234,56', '45%' etc."""
    if s is None:
        return None
    s = s.strip().replace(" ", "")
    s = s.replace("%", "")
    # 1.234,56 -> 1234.56
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except:
        return None

def percent_to_number(s: Optional[str]) -> Optional[float]:
    """Converte '45%' -> 45.0; '45' -> 45.0"""
    if s is None:
        return None
    s = s.strip()
    if s.endswith("%"):
        s = s[:-1]
    return to_number(s)

def parse_from_text(texto: str) -> Dict[str, str]:
    # Rótulos esperados (sem acento, minúsculo)
    rotulos = {
        "nome do projeto": "nome_projeto",
        "cpi": "cpi",
        "spi": "spi",
        "avanco fisico": "avanco_fisico",
        "avanco financeiro": "avanco_financeiro",
        "tipo de contrato": "tipo_contrato",
        "stakeholders": "stakeholders",
        "observacoes": "observacoes",
        "pilar": "pilar",
    }
    campos = {
        "nome_projeto": "Não informado",
        "cpi": "Não informado",
        "spi": "Não informado",
        "avanco_fisico": "Não informado",
        "avanco_financeiro": "Não informado",
        "tipo_contrato": "Não informado",
        "stakeholders": "Não informado",
        "observacoes": "Não informado",
        "pilar": "Não informado",
    }
    for raw in texto.splitlines():
        linha = raw.strip()
        if ":" not in linha:
            continue
        rotulo, valor = linha.split(":", 1)
        r_norm = normalize(rotulo)
        if r_norm in rotulos:
            campos[rotulos[r_norm]] = valor.strip()
    return campos

# -------------------------------------------------------------------------
# Heurísticas: risco, pilar e próximos passos
# -------------------------------------------------------------------------
def calcular_score_risco(campos_num: Dict[str, Optional[float]], observacoes: str, trace: List[str]) -> float:
    score = 0.0
    cpi = campos_num.get("cpi_num")
    spi = campos_num.get("spi_num")
    fis = campos_num.get("avanco_fisico_num")
    fin = campos_num.get("avanco_financeiro_num")

    # CPI
    if cpi is not None:
        if cpi < 0.85:
            score += 5; trace.append("CPI<0,85: +5")
        elif cpi < 0.90:
            score += 3; trace.append("0,85≤CPI<0,90: +3")

    # SPI
    if spi is not None:
        if spi < 0.90:
            score += 5; trace.append("SPI<0,90: +5")
        elif spi < 0.95:
            score += 3; trace.append("0,90≤SPI<0,95: +3")

    # Assimetria físico x financeiro
    if fis is not None and fin is not None:
        gap = abs(fis - fin)
        if gap >= 15:
            score += 2; trace.append("Gap físico x financeiro ≥15pp: +2")
        elif gap >= 8:
            score += 1; trace.append("Gap físico x financeiro ≥8pp: +1")

    # Palavras-chave em observações
    obs_norm = normalize(observacoes)
    keywords = ["atraso", "licenca", "embargo", "paralis", "fornecedor", "pressao", "custo", "multas", "sancao", "risco", "equipamento", "critico"]
    pontos = sum(1 for k in keywords if k in obs_norm)
    if pontos > 0:
        add = min(4, pontos)
        score += add; trace.append(f"Keywords em observações (+{add})")
    return score

def classificar_risco(score: float) -> str:
    # Política Kaio: evitar "Crítico" -> consolidar em "Alto"
    if score >= 7:
        return "Alto"
    elif score >= 4:
        return "Médio"
    else:
        return "Baixo"

def inferir_pilar(campos: Dict[str, str], campos_num: Dict[str, Optional[float]], trace: List[str]) -> Optional[str]:
    obs = normalize(campos.get("observacoes", ""))
    cpi = campos_num.get("cpi_num")
    spi = campos_num.get("spi_num")

    # Observações de cliente/atendimento
    if any(k in obs for k in ["reclamacao", "qualidade", "satisfacao", "experiencia", "atendimento", "sla", "cliente"]):
        trace.append("ECK→Foco no Cliente (observações de experiência/atendimento)")
        return "Foco no Cliente"

    # Observações de capital/retorno
    if any(k in obs for k in ["orcamento", "capex", "investimento", "priorizacao", "retorno", "payback", "vpl", "tir"]):
        trace.append("ECK→Alocação Estratégica de Capital (observações de CAPEX/retorno)")
        return "Alocação Estratégica de Capital"

    # Métricas abaixo do alvo
    if (cpi is not None and cpi < 0.90) or (spi is not None and spi < 0.95):
        trace.append("ECK→Excelência Organizacional (desempenho abaixo do target)")
        return "Excelência Organizacional"

    return None

def justificativa_pilar_eck(pilar: str) -> str:
    p = normalize(pilar)
    if "excelencia" in p:
        return ("Excelência Organizacional: alinhar pessoas, processos, estrutura e incentivos à estratégia; "
                "desdobrar metas para coerência entre áreas e execução coordenada.")
    if "cliente" in p:
        return ("Foco no Cliente: colocar o cliente no centro, entender necessidades, antecipar soluções "
                "e melhorar continuamente as jornadas com confiabilidade e SLAs.")
    if "alocacao" in p:
        return ("Alocação Estratégica de Capital: priorizar investimentos que maximizem valor no longo prazo, "
                "com disciplina de capital e seleção criteriosa de oportunidades (VPL/TIR ajustadas a risco).")
    return f"Pilar declarado: {pilar}"

def split_stakeholders(stakeholders: str) -> List[str]:
    if not stakeholders or stakeholders == "Não informado":
        return []
    parts: List[str] = []
    for sep in [";", ",", "\n", "|"]:
        if sep in stakeholders:
            parts = [p.strip() for p in stakeholders.split(sep)]
            break
    if not parts:
        parts = [stakeholders.strip()]
    return [p for p in parts if p]

def gerar_proximos_passos(cpi: Optional[float], spi: Optional[float], gap_pf: Optional[float],
                          obs: str, pilar_final: str, stakeholders: str) -> List[str]:
    passos: List[str] = []
    # Base em CPI/SPI
    if cpi is not None and cpi < 0.90:
        passos.append("Estabelecer plano de contenção de custos e variação de escopo (D+7).")
        passos.append("Revisar curvas de medição e baseline financeiro (D+10).")
    if spi is not None and spi < 0.95:
        passos.append("Replanejar caminho crítico e renegociar marcos críticos (D+5).")
        passos.append("Avaliar compressão de cronograma/fast-track onde aplicável (D+10).")
    # Assimetria físico x financeiro
    if gap_pf is not None:
        if gap_pf >= 15:
            passos.append("Investigar assimetria físico x financeiro (≥15pp): auditoria de medição (D+7).")
        elif gap_pf >= 8:
            passos.append("Alinhar critérios de medição físico x financeiro (≥8pp) (D+10).")
    # Observações
    obs_n = normalize(obs)
    if "fornecedor" in obs_n:
        passos.append("Conduzir reunião executiva com fornecedor crítico e plano de ação 5W2H (D+3).")
    if "equip" in obs_n or "equipamento" in obs_n or "critico" in obs_n:
        passos.append("Ativar plano de contingência para equipamentos críticos e alternativas logísticas (D+7).")
    if "licenc" in obs_n or "embargo" in obs_n or "paralis" in obs_n:
        passos.append("Acionar frente regulatória/jurídica para destravar licenças/embargos (D+3).")
    # Diretrizes por Pilar ECK
    p = normalize(pilar_final)
    if "excelencia" in p:
        passos.append("Desdobrar metas operacionais e RACI de governança semanal (D+7).")
        passos.append("Implantar rituais de performance e indicadores leading/lagging (D+14).")
    if "cliente" in p:
        passos.append("Mapear jornada do cliente e ajustar SLAs de comunicação de obra (D+15).")
        passos.append("Rodar pulso de satisfação/NPS interno ao marco seguinte (D+30).")
    if "alocacao" in p:
        passos.append("Repriorizar CAPEX do portfólio, priorizando itens de maior retorno ajustado a risco (D+20).")
        passos.append("Revisar business case do projeto e opções de escopo/financiamento (D+30).")
    # Responsáveis sugeridos
    owners = split_stakeholders(stakeholders)
    if owners:
        passos.append(f"Responsáveis sugeridos: {', '.join(owners[:3])}.")
    # Remover duplicados mantendo ordem
    dedup: List[str] = []
    seen = set()
    for it in passos:
        if it not in seen:
            seen.add(it)
            dedup.append(it)
    return dedup

def listar_riscos(campos_num: Dict[str, Optional[float]], observacoes: str) -> List[str]:
    """Gera lista de riscos-chave, alinhada às mesmas regras do score."""
    riscos: List[str] = []
    cpi = campos_num.get("cpi_num")
    spi = campos_num.get("spi_num")
    fis = campos_num.get("avanco_fisico_num")
    fin = campos_num.get("avanco_financeiro_num")

    if cpi is not None:
        if cpi < 0.85:
            riscos.append("Custo: CPI < 0,85 — forte risco de estouro orçamentário.")
        elif cpi < 0.90:
            riscos.append("Custo: CPI entre 0,85 e 0,90 — pressão de custos e necessidade de correções.")
    if spi is not None:
        if spi < 0.90:
            riscos.append("Prazo: SPI < 0,90 — alto risco de atraso em marcos contratuais.")
        elif spi < 0.95:
            riscos.append("Prazo: SPI entre 0,90 e 0,95 — risco de deslizamento de cronograma.")
    if fis is not None and fin is not None:
        gap = abs(fis - fin)
        if gap >= 15:
            riscos.append("Execução: assimetria físico x financeiro ≥15pp — risco de medição/execução inconsistente.")
        elif gap >= 8:
            riscos.append("Execução: assimetria físico x financeiro ≥8pp — atenção à coerência de medição.")
    obs = normalize(observacoes)
    # Mapear palavras-chave em observações para riscos compreensíveis
    mapping = [
        ("atraso", "Cronograma: indícios de atraso em frentes críticas."),
        ("licenc", "Regulatório: risco de licenças/autorizações."),
        ("embargo", "Regulatório: risco de embargo/interdição."),
        ("paralis", "Operação: risco de paralisação de obra/frentes."),
        ("fornecedor", "Suprimentos: dependência de fornecedor crítico."),
        ("pressao", "Financeiro: pressão de custos nos pacotes."),
        ("custo", "Financeiro: tendência de aumento de custos."),
        ("multas", "Contratual: risco de multas por descumprimento."),
        ("sancao", "Compliance: risco de sanções."),
        ("equip", "Técnico: risco com fornecimento de equipamentos."),
        ("equipamento", "Técnico: risco com fornecimento de equipamentos."),
        ("critico", "Risco crítico citado em observações (tratado como Alto)."),
        ("risco", "Risco adicional citado em observações."),
    ]
    already = set()
    for key, msg in mapping:
        if key in obs and msg not in already:
            already.add(msg)
            riscos.append(msg)
    # Dedup final
    out: List[str] = []
    seen = set()
    for r in riscos:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out

# -------------------------------------------------------------------------
# Formatação (TXT, Markdown, HTML)
# -------------------------------------------------------------------------
def format_report(campos: Dict[str, str],
                  campos_num: Dict[str, Optional[float]],
                  score: float,
                  risco: str,
                  pilar_declarado: str,
                  pilar_final: str,
                  justificativa_eck_txt: str,
                  proximos_passos_recomendado: List[str],
                  proximos_passos_atual: List[str],
                  kpis: Dict[str, Any],
                  riscos_chave: List[str],
                  divergente: bool,
                  pilar_sugerido: Optional[str],
                  justificativa_sugerido: Optional[str]) -> Dict[str, str]:

    nome = campos.get("nome_projeto", "Projeto não identificado") or "Projeto não identificado"
    cpi = campos.get("cpi", "Não informado")
    spi = campos.get("spi", "Não informado")
    fisico = campos.get("avanco_fisico", "Não informado")
    financeiro = campos.get("avanco_financeiro", "Não informado")
    contrato = campos.get("tipo_contrato", "Não informado")
    stakeholders = campos.get("stakeholders", "Não informado")
    observacoes = campos.get("observacoes", "Não informado")

    # Emojis por risco
    risco_emoji = {"Alto": "🔴", "Médio": "🟠", "Baixo": "🟢"}.get(risco, "⚠️")

    # ------------------ Markdown ------------------
    md = []
    md.append(f"### 📊 Relatório Executivo Preditivo – Projeto **{nome}**")
    md.append("")
    md.append("**✅ Status Geral**")
    md.append(f"- CPI: **{cpi}**")
    md.append(f"- SPI: **{spi}**")
    md.append(f"- Avanço Físico: **{fisico}**")
    md.append(f"- Avanço Financeiro: **{financeiro}**")
    md.append(f"- Tipo de Contrato: **{contrato}**")
    md.append(f"- Stakeholders: **{stakeholders}**")
    md.append(f"- Risco (classificação): **{risco} {risco_emoji}** *(score interno: {score:.1f})*")
    md.append(f"- Observação: **{observacoes}**")
    md.append("")
    md.append("**📈 Diagnóstico de Performance**")
    md.append(f"- Custo: CPI em {cpi} → disciplina orçamentária.")
    md.append(f"- Prazo: SPI em {spi} → gestão de caminho crítico.")
    md.append(f"- Execução: físico ({fisico}) vs. financeiro ({financeiro}).")
    md.append(f"- Contrato: “{contrato}” → reforçar governança de escopo/custos.")
    if kpis.get("gap_pf") is not None:
        md.append(f"- Gap físico x financeiro: **{kpis['gap_pf']:.1f}pp**.")
    if riscos_chave:
        md.append("")
        md.append("**⚠️ Riscos‑chave identificados**")
        for r in riscos_chave:
            md.append(f"- {r}")
    md.append("")
    md.append("**📅 Projeção de Impactos**")
    md.append("- Curto prazo: risco de novos atrasos e pressão de custos.")
    md.append("- Médio prazo: impacto em marcos contratuais e metas estratégicas.")
    md.append("- Stakeholders: intensificar monitoramento e comunicação executiva.")
    md.append("")
    md.append("**🧭 Recomendações Estratégicas (metas gerais)**")
    md.append("- Revisar caminho crítico e renegociar entregas críticas.")
    md.append("- Metas‑alvo: **CPI ≥ 0,90** e **SPI ≥ 0,95**.")
    md.append("- Integrar áreas e reforçar controle de produtividade.")
    md.append("")
    md.append("**🏛 Pilar ECK (foco estratégico)**")
    if pilar_declarado != "Não informado":
        md.append(f"- Pilar declarado: **{pilar_declarado}**")
    if divergente and pilar_sugerido:
        md.append(f"- Pilar sugerido (análise): **{pilar_sugerido}** ⚠️ *(recomendado realinhar)*")
        if justificativa_sugerido:
            md.append(f"- Justificativa (sugerido): {justificativa_sugerido}")
        md.append(f"- Justificativa (atual): {justificativa_eck_txt}")
    else:
        show = pilar_declarado if pilar_declarado != "Não informado" else pilar_final
        md.append(f"- Pilar: **{show}**")
        md.append(f"- Justificativa: {justificativa_eck_txt}")

    # Duas opções de próximos passos
    if proximos_passos_recomendado:
        md.append("")
        md.append("**▶ Próximos Passos — (Recomendado, alinhado ao Pilar sugerido)**")
        for p in proximos_passos_recomendado:
            md.append(f"- {p}")
    if proximos_passos_atual:
        md.append("")
        md.append("**▶ Próximos Passos — (Atual, alinhado ao Pilar declarado)**")
        for p in proximos_passos_atual:
            md.append(f"- {p}")

    md.append("")
    md.append("**✅ Resumo Executivo**")
    resumo_pilar = (pilar_sugerido or pilar_final) if (divergente and pilar_sugerido) else (pilar_declarado if pilar_declarado != "Não informado" else pilar_final)
    md.append(f"O projeto **{nome}** requer atenção **{risco.lower()} {risco_emoji}**. "
              f"Considerar foco no pilar **{resumo_pilar}** e disciplina de execução para assegurar valor e entrega.")
    md_report = "\n".join(md)

    # ------------------ Texto (para A360) ------------------
    txt_lines = [
        f"📊 Relatório Executivo Preditivo – Projeto “{nome}”",
        "",
        "✅ Status Geral",
        f"CPI: {cpi}",
        f"SPI: {spi}",
        f"Avanço Físico: {fisico}",
        f"Avanço Financeiro: {financeiro}",
        f"Tipo de Contrato: {contrato}",
        f"Stakeholders: {stakeholders}",
        f"Risco (classificação): {risco} {risco_emoji} (score interno: {score:.1f})",
        f"Observação: {observacoes}",
        "",
        "📈 Diagnóstico de Performance",
        f"- Custo: CPI em {cpi} → disciplina orçamentária.",
        f"- Prazo: SPI em {spi} → gestão de caminho crítico.",
        f"- Execução: físico ({fisico}) vs. financeiro ({financeiro}).",
        f"- Contrato: “{contrato}” → reforçar governança de escopo/custos.",
    ]
    if kpis.get("gap_pf") is not None:
        txt_lines.append(f"- Gap físico x financeiro: {kpis['gap_pf']:.1f}pp.")
    if riscos_chave:
        txt_lines += ["", "⚠️ Riscos‑chave identificados"]
        for r in riscos_chave:
            txt_lines.append(f"- {r}")
    txt_lines += [
        "",
        "📅 Projeção de Impactos",
        "- Curto prazo: risco de novos atrasos e pressão de custos.",
        "- Médio prazo: impacto em marcos contratuais e metas estratégicas.",
        "- Stakeholders: intensificar monitoramento e comunicação executiva.",
        "",
        "🧭 Recomendações Estratégicas (metas gerais)",
        "- Revisar caminho crítico e renegociar entregas críticas.",
        "- Metas-alvo: CPI ≥ 0,90 e SPI ≥ 0,95.",
        "- Integrar áreas e reforçar controle de produtividade.",
        "",
        "🏛 Pilar ECK (foco estratégico)",
    ]
    if pilar_declarado != "Não informado":
        txt_lines.append(f"- Pilar declarado: {pilar_declarado}")
    if divergente and pilar_sugerido:
        txt_lines.append(f"- Pilar sugerido (análise): {pilar_sugerido} ⚠️ (recomendado realinhar)")
        if justificativa_sugerido:
            txt_lines.append(f"- Justificativa (sugerido): {justificativa_sugerido}")
        txt_lines.append(f"- Justificativa (atual): {justificativa_eck_txt}")
    else:
        show_txt = pilar_declarado if pilar_declarado != "Não informado" else pilar_final
        txt_lines.append(f"- Pilar: {show_txt}")
        txt_lines.append(f"- Justificativa: {justificativa_eck_txt}")

    # Duas opções de próximos passos
    if proximos_passos_recomendado:
        txt_lines.append("")
        txt_lines.append("▶ Próximos Passos — (Recomendado, alinhado ao Pilar sugerido)")
        for p in proximos_passos_recomendado:
            txt_lines.append(f"- {p}")
    if proximos_passos_atual:
        txt_lines.append("")
        txt_lines.append("▶ Próximos Passos — (Atual, alinhado ao Pilar declarado)")
        for p in proximos_passos_atual:
            txt_lines.append(f"- {p}")

    txt_lines += [
        "",
        "✅ Resumo Executivo",
    ]
    resumo_pilar_txt = (pilar_sugerido or pilar_final) if (divergente and pilar_sugerido) else (pilar_declarado if pilar_declarado != "Não informado" else pilar_final)
    txt_lines.append(
        f"O projeto “{nome}” requer atenção {risco.lower()} {risco_emoji}. "
        f"Considerar foco no pilar {resumo_pilar_txt} e disciplina de execução para assegurar valor e entrega."
    )
    txt_report = "\n".join(txt_lines)

    # ------------------ HTML ------------------
    def esc(s: str) -> str:
        return html.escape(str(s)).replace("\n", "<br/>")

    def li_list(items: List[str]) -> str:
        return "".join(f"<li>{esc(i)}</li>" for i in items)

    riscos_html = li_list(riscos_chave) if riscos_chave else ""
    proximos_rec_html = li_list(proximos_passos_recomendado) if proximos_passos_recomendado else ""
    proximos_atual_html = li_list(proximos_passos_atual) if proximos_passos_atual else ""

    html_report = f"""
<h3>📊 Relatório Executivo Preditivo – Projeto “{esc(nome)}”</h3>
<p><strong>✅ Status Geral</strong><br/>
CPI: <strong>{esc(cpi)}</strong><br/>
SPI: <strong>{esc(spi)}</strong><br/>
Avanço Físico: <strong>{esc(fisico)}</strong><br/>
Avanço Financeiro: <strong>{esc(financeiro)}</strong><br/>
Tipo de Contrato: <strong>{esc(contrato)}</strong><br/>
Stakeholders: <strong>{esc(stakeholders)}</strong><br/>
Risco (classificação): <strong>{esc(risco)}</strong> {esc(risco_emoji)} (score interno: {score:.1f})<br/>
Observação: <strong>{esc(observacoes)}</strong></p>

<p><strong>📈 Diagnóstico de Performance</strong></p>
<ul>
  <li>Custo: CPI em {esc(cpi)} → disciplina orçamentária.</li>
  <li>Prazo: SPI em {esc(spi)} → gestão de caminho crítico.</li>
  <li>Execução: físico ({esc(fisico)}) vs. financeiro ({esc(financeiro)}).</li>
  <li>Contrato: “{esc(contrato)}” → reforçar governança de escopo/custos.</li>
  {f"<li>Gap físico x financeiro: {kpis['gap_pf']:.1f}pp.</li>" if kpis.get('gap_pf') is not None else ""}
</ul>

{f"<p><strong>⚠️ Riscos‑chave identificados</strong></p><ul>{riscos_html}</ul>" if riscos_html else ""}

<p><strong>📅 Projeção de Impactos</strong></p>
<ul>
  <li>Curto prazo: risco de novos atrasos e pressão de custos.</li>
  <li>Médio prazo: impacto em marcos contratuais e metas estratégicas.</li>
  <li>Stakeholders: intensificar monitoramento e comunicação executiva.</li>
</ul>

<p><strong>🧭 Recomendações Estratégicas (metas gerais)</strong></p>
<ul>
  <li>Revisar caminho crítico e renegociar entregas críticas.</li>
  <li>Metas‑alvo: CPI ≥ 0,90 e SPI ≥ 0,95.</li>
  <li>Integrar áreas e reforçar controle de produtividade.</li>
</ul>

<p><strong>🏛 Pilar ECK (foco estratégico)</strong><br/>
{f"Pilar declarado: <strong>{esc(pilar_declarado)}</strong><br/>" if pilar_declarado != "Não informado" else ""}
{(f"Pilar sugerido (análise): <strong>{esc(pilar_sugerido)}</strong> ⚠️ (recomendado realinhar)<br/>{'Justificativa (sugerido): ' + esc(justificativa_sugerido) + '<br/>' if justificativa_sugerido else ''}Justificativa (atual): {esc(justificativa_eck_txt)}"
  if (divergente and pilar_sugerido) else
  f"Pilar: <strong>{esc(pilar_declarado if pilar_declarado != 'Não informado' else pilar_final)}</strong><br/>Justificativa: {esc(justificativa_eck_txt)}")}
</p>

{f"<p><strong>▶ Próximos Passos — (Recomendado, alinhado ao Pilar sugerido)</strong></p><ul>{proximos_rec_html}</ul>" if proximos_rec_html else ""}
{f"<p><strong>▶ Próximos Passos — (Atual, alinhado ao Pilar declarado)</strong></p><ul>{proximos_atual_html}</ul>" if proximos_atual_html else ""}

<p><strong>✅ Resumo Executivo</strong><br/>
O projeto “{esc(nome)}” requer atenção {esc(risco.lower())} {esc(risco_emoji)}. Considerar foco no pilar {esc((pilar_sugerido or pilar_final) if (divergente and pilar_sugerido) else (pilar_declarado if pilar_declarado != 'Não informado' else pilar_final))} e disciplina de execução para assegurar valor e entrega.</p>
""".strip()

    return {"txt": txt_report.strip(), "md": md_report.strip(), "html": html_report}

# -------------------------------------------------------------------------
# Endpoint helpers
# -------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "version": "1.3.0"}

def _analisar(campos: Dict[str, str]) -> Dict[str, Any]:
    trace: List[str] = []

    # Números normalizados
    campos_num = {
        "cpi_num": to_number(campos.get("cpi")),
        "spi_num": to_number(campos.get("spi")),
        "avanco_fisico_num": percent_to_number(campos.get("avanco_fisico")),
        "avanco_financeiro_num": percent_to_number(campos.get("avanco_financeiro")),
    }

    # KPIs auxiliares
    gap_pf = None
    if campos_num["avanco_fisico_num"] is not None and campos_num["avanco_financeiro_num"] is not None:
        gap_pf = abs(campos_num["avanco_fisico_num"] - campos_num["avanco_financeiro_num"])
    kpis = {
        "gap_pf": gap_pf,
        "gap_spi": (0.95 - campos_num["spi_num"]) if campos_num["spi_num"] is not None else None,
        "gap_cpi": (0.90 - campos_num["cpi_num"]) if campos_num["cpi_num"] is not None else None,
    }

    # Pilar
    pilar_declarado = campos.get("pilar", "Não informado")
    pilar_inferido = inferir_pilar(campos, campos_num, trace)  # sugerido (pode ser None)

    # Divergência: declarado vs inferido
    def _norm(s): return normalize(s or "")
    divergente = (
        pilar_declarado and pilar_declarado != "Não informado" and
        pilar_inferido and _norm(pilar_declarado) != _norm(pilar_inferido)
    )

    # Pilar final (mantém política anterior: se declararam, prevalece; senão usa inferido)
    pilar_final = pilar_declarado if (pilar_declarado and pilar_declarado != "Não informado") else (pilar_inferido or "Não informado")

    if divergente:
        trace.append(f"Divergência Pilar: declarado='{pilar_declarado}' vs sugerido='{pilar_inferido}'")

    # Score e risco
    score = calcular_score_risco(campos_num, campos.get("observacoes", ""), trace)
    classificacao = classificar_risco(score)

    # Próximos passos — duas opções
    # (Recomendado): alinha ao sugerido se existir; senão, usa pilar_final
    pilar_para_recomendado = pilar_inferido or pilar_final
    proximos_recomendado = gerar_proximos_passos(
        cpi=campos_num["cpi_num"],
        spi=campos_num["spi_num"],
        gap_pf=gap_pf,
        obs=campos.get("observacoes", ""),
        pilar_final=pilar_para_recomendado,
        stakeholders=campos.get("stakeholders", "Não informado"),
    )
    # (Atual): alinha ao pilar declarado (se não informado, ainda assim gera passos gerais sem diretriz de pilar)
    proximos_atual = gerar_proximos_passos(
        cpi=campos_num["cpi_num"],
        spi=campos_num["spi_num"],
        gap_pf=gap_pf,
        obs=campos.get("observacoes", ""),
        pilar_final=pilar_declarado if pilar_declarado else "Não informado",
        stakeholders=campos.get("stakeholders", "Não informado"),
    )

    # Riscos-chave
    riscos_chave = listar_riscos(campos_num, campos.get("observacoes", ""))

    # Justificativas
    justificativa_final = justificativa_pilar_eck(pilar_final)
    justificativa_sugerido = justificativa_pilar_eck(pilar_inferido) if pilar_inferido else None

    # Relatórios
    reports = format_report(
        campos=campos,
        campos_num=campos_num,
        score=score,
        risco=classificacao,
        pilar_declarado=pilar_declarado,
        pilar_final=pilar_final,
        justificativa_eck_txt=justificativa_final,
        proximos_passos_recomendado=proximos_recomendado,
        proximos_passos_atual=proximos_atual,
        kpis=kpis,
        riscos_chave=riscos_chave,
        divergente=divergente,
        pilar_sugerido=pilar_inferido,
        justificativa_sugerido=justificativa_sugerido
    )

    payload_out = {
        "versao_api": "1.3.0",
        "campos_interpretados": {**campos, **campos_num, "pilar_final": pilar_final},
        "kpis": kpis,
        "score_risco": score,
        "classificacao_risco": classificacao,
        "riscos_chave": riscos_chave,
        "pilar_declarado": pilar_declarado,
        "pilar_sugerido": pilar_inferido,
        "pilar_divergente": divergente,
        "proximos_passos_recomendado": proximos_recomendado,
        "proximos_passos_atual": proximos_atual,
        "trace": trace,
        # Compat com A360:
        "conclusao_executiva": reports["txt"],
        # Extras (Teams/Email):
        "conclusao_executiva_markdown": reports["md"],
        "conclusao_executiva_html": reports["html"],
    }
    return payload_out

# -------------------------------------------------------------------------
# Endpoints principais
# -------------------------------------------------------------------------
@app.post("/analisar-projeto-texto")
async def analisar_projeto_texto(payload: TextoRequest):
    campos = parse_from_text(payload.texto)
    return _analisar(campos)

@app.post("/analisar-projeto")
async def analisar_projeto(payload: ProjetoRequest):
    campos = {
        "nome_projeto": payload.nome_projeto or "Não informado",
        "cpi": payload.cpi or "Não informado",
        "spi": payload.spi or "Não informado",
        "avanco_fisico": payload.avanco_fisico or "Não informado",
        "avanco_financeiro": payload.avanco_financeiro or "Não informado",
        "tipo_contrato": payload.tipo_contrato or "Não informado",
        "stakeholders": payload.stakeholders or "Não informado",
        "observacoes": payload.observacoes or "Não informado",
        "pilar": payload.pilar or "Não informado",
    }
    return _analisar(campos)
