# main.py - Vera Estratégica API v1.6.0
# Kaio / Projeto Verinha
# - Compatível com v1.2/1.3/1.4/1.5 (A360 consome conclusao_executiva TXT)
# - Textos 100% contextuais: diagnóstico, riscos, projeção e recomendações sob medida
# - Pilar ECK com justificativa específica do projeto e sem duplicidade quando não houver divergência
# - Análise Estratégica textual (sem exibir métricas de propósito/valores no TXT)
# - Mantém packs financeiro/cronograma, Strategy Fit, Lições Aprendidas

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Tuple
import unicodedata
import html
import os
from datetime import datetime, date

app = FastAPI(title="Vera Estratégica API", version="1.6.0")

# -------------------------------------------------------------------------------------------------
# Feature flags e metas
# -------------------------------------------------------------------------------------------------
FEATURES = {
    "enable_strategy_fit": True,
    "enable_lessons_learned": True,
    "enable_finance_pack": True,
    "enable_schedule_pack": True,
    "enable_external_evidence": os.getenv("EXTERNAL_EVIDENCE_ENABLED", "false").lower() == "true",
    "enable_strategic_analysis": True,
}
TARGETS = {"cpi": 0.90, "spi": 0.95, "idx_meta": 1.00}  # ISP/IDP/IDCo/IDB
LEAN_MODE = os.getenv("LEAN_MODE", "false").lower() == "true"

# -------------------------------------------------------------------------------------------------
# Models
# -------------------------------------------------------------------------------------------------
class TextoRequest(BaseModel):
    texto: str

class ProjetoRequest(BaseModel):
    # Campos já existentes
    nome_projeto: Optional[str] = None
    cpi: Optional[str] = None
    spi: Optional[str] = None
    avanco_fisico: Optional[str] = None
    avanco_financeiro: Optional[str] = None
    tipo_contrato: Optional[str] = None
    stakeholders: Optional[str] = None
    observacoes: Optional[str] = None
    pilar: Optional[str] = None
    # Novos campos (opcionais)
    objetivo: Optional[str] = None
    resumo_status: Optional[List[str]] = None  # bullets
    planos_proximo_periodo: Optional[List[str]] = None
    pontos_atencao: Optional[List[str]] = None
    indicadores: Optional[Dict[str, Any]] = None  # {"isp":..., "idp":..., "idco":..., "idb":...}
    data_final_planejada: Optional[str] = None  # "YYYY-MM-DD" | "DD/MM/YYYY" | "DD-MM-YYYY"
    baseline: Optional[Dict[str, Any]] = None  # {"prazo":{"data_planejada":...},"custo":{"capex_aprovado":...},"escopo":"..."}
    escopo: Optional[str] = None
    cronograma: Optional[Dict[str, Any]] = None  # {"tarefas":[{"nome":...,"inicio":...,"fim":...,"pct":...,"critica":...}]}
    financeiro: Optional[Dict[str, Any]] = None  # {"capex_aprovado":...,"capex_comp":...,"capex_exec":...,"ev":...,"pv":...,"ac":...,"eac":...,"vac":...}

# -------------------------------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------------------------------
def normalize(s: Optional[str]) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.lower().strip()

def to_number(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    s = str(s).strip().replace(" ", "").replace("%", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except:
        return None

def percent_to_number(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    s = str(s).strip()
    if s.endswith("%"):
        s = s[:-1]
    return to_number(s)

def parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except:
            continue
    return None

# -------------------------------------------------------------------------------------------------
# Parser do texto colado no A360 (rótulos + blocos)
# -------------------------------------------------------------------------------------------------
def parse_from_text(texto: str) -> Dict[str, Any]:
    campos: Dict[str, Any] = {
        "nome_projeto": "Não informado",
        "cpi": "Não informado",
        "spi": "Não informado",
        "avanco_fisico": "Não informado",
        "avanco_financeiro": "Não informado",
        "tipo_contrato": "Não informado",
        "stakeholders": "Não informado",
        "observacoes": "Não informado",
        "pilar": "Não informado",
        # Novos
        "objetivo": "Não informado",
        "resumo_status": [],
        "planos_proximo_periodo": [],
        "pontos_atencao": [],
        "indicadores": {},
        "data_final_planejada": "Não informado",
        "baseline": {},
        "escopo": "Não informado",
        "cronograma": {"tarefas": []},
        "financeiro": {},
    }
    lines = texto.splitlines()
    i = 0
    labels = {
        "nome do projeto","objetivo",
        "resumo status","resumo da situacao atual","resumo da situação atual",
        "planos proximo periodo","planos próximo periodo","planos para o proximo periodo",
        "pontos de atencao","pontos de atenção",
        "cpi","spi","isp","idp","idco","idb",
        "avanco fisico","avanco financeiro",
        "tipo de contrato","stakeholders",
        "data final planejada",
        "baseline prazo","baseline custo (capex aprovado)","baseline custo",
        "escopo",
        "observacoes","observações",
        "tarefas","financeiro",
        "pilar"
    }

    def is_label(line: str) -> Tuple[bool, str, str]:
        if ":" not in line:
            return False, "", ""
        k, v = line.split(":", 1)
        nk = normalize(k)
        return (nk in labels, nk, v.strip())

    def collect_bullets(start_idx: int) -> Tuple[List[str], int]:
        bullets: List[str] = []
        j = start_idx
        while j < len(lines):
            raw = lines[j].strip()
            if raw == "":
                break
            has, _, _ = is_label(raw)
            if has:
                break
            if raw.startswith("- "):
                bullets.append(raw[2:].strip())
            else:
                if bullets:
                    bullets[-1] = (bullets[-1] + " " + raw).strip()
                else:
                    bullets.append(raw)
            j += 1
        return bullets, j

    def parse_task_line(raw: str) -> Optional[Dict[str, Any]]:
        # Espera pares "Chave: Valor" por linha
        parts = [p.strip() for p in raw.split("\n")]
        d: Dict[str, Any] = {}
        for p in parts:
            if ":" in p:
                k, vv = p.split(":", 1)
                d[normalize(k)] = vv.strip()
        if not d:
            return None
        nome = d.get("nome") or raw.replace("- ", "").strip()
        ini = parse_date(d.get("inicio") or d.get("início"))
        fim = parse_date(d.get("fim"))
        pct = to_number(d.get("%") or d.get("pct"))
        crit = normalize(d.get("critica") or d.get("crítica")) in ("sim", "true", "critica", "crítica")
        return {"nome": nome, "inicio": ini, "fim": fim, "pct": pct, "critica": crit}

    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        has, nk, val = is_label(line)
        if not has:
            i += 1
            continue
        # Blocos
        if nk in ("resumo status", "resumo da situacao atual", "resumo da situação atual"):
            i += 1
            bullets, j = collect_bullets(i)
            campos["resumo_status"] = bullets
            i = j
            continue
        if nk in ("planos proximo periodo", "planos próximo periodo", "planos para o proximo periodo"):
            i += 1
            bullets, j = collect_bullets(i)
            campos["planos_proximo_periodo"] = bullets
            i = j
            continue
        if nk in ("pontos de atencao", "pontos de atenção"):
            i += 1
            bullets, j = collect_bullets(i)
            campos["pontos_atencao"] = bullets
            i = j
            continue
        if nk == "tarefas":
            i += 1
            tasks: List[Dict[str, Any]] = []
            while i < len(lines):
                raw = lines[i].strip()
                if raw == "":
                    break
                has2, _, _ = is_label(raw)
                if has2:
                    break
                if raw.startswith("-"):
                    t = parse_task_line(raw.lstrip("-").strip())
                    if t:
                        tasks.append(t)
                i += 1
            campos["cronograma"] = {"tarefas": tasks}
            continue
        if nk == "financeiro":
            i += 1
            fin: Dict[str, Any] = {}
            while i < len(lines):
                raw = lines[i].strip()
                if raw == "":
                    break
                has2, _, _ = is_label(raw)
                if has2:
                    break
                if ":" in raw:
                    k, v = raw.split(":", 1)
                    fin[normalize(k)] = v.strip()
                i += 1
            campos["financeiro"] = fin
            continue

        # Chaves simples
        if nk == "nome do projeto":
            campos["nome_projeto"] = val or "Não informado"
        elif nk == "objetivo":
            campos["objetivo"] = val or "Não informado"
        elif nk in ("cpi","spi","isp","idp","idco","idb"):
            ind = campos.get("indicadores") or {}
            if nk in ("cpi","spi"):
                campos[nk] = val or "Não informado"
            else:
                ind[nk] = val
            campos["indicadores"] = ind
        elif nk == "avanco fisico":
            campos["avanco_fisico"] = val or "Não informado"
        elif nk == "avanco financeiro":
            campos["avanco_financeiro"] = val or "Não informado"
        elif nk == "tipo de contrato":
            campos["tipo_contrato"] = val or "Não informado"
        elif nk == "stakeholders":
            campos["stakeholders"] = val or "Não informado"
        elif nk == "data final planejada":
            campos["data_final_planejada"] = val or "Não informado"
        elif nk == "baseline prazo":
            b = campos.get("baseline") or {}
            b["prazo"] = {"data_planejada": val}
            campos["baseline"] = b
        elif nk in ("baseline custo (capex aprovado)","baseline custo"):
            b = campos.get("baseline") or {}
            bb = b.get("custo") or {}
            bb["capex_aprovado"] = val
            b["custo"] = bb
            campos["baseline"] = b
        elif nk == "escopo":
            campos["escopo"] = val or "Não informado"
        elif nk in ("observacoes","observações"):
            campos["observacoes"] = val or "Não informado"
        elif nk == "pilar":
            campos["pilar"] = val or "Não informado"
        i += 1

    return campos

# -------------------------------------------------------------------------------------------------
# Heurísticas de risco / pilar / etc.
# -------------------------------------------------------------------------------------------------
def calcular_score_risco_base(campos_num: Dict[str, Optional[float]], observacoes: str, trace: List[str]) -> float:
    score = 0.0
    cpi = campos_num.get("cpi_num")
    spi = campos_num.get("spi_num")
    fis = campos_num.get("avanco_fisico_num")
    fin = campos_num.get("avanco_financeiro_num")

    # CPI
    if cpi is not None:
        if cpi < 0.85: score += 5; trace.append("CPI<0,85: +5")
        elif cpi < 0.90: score += 3; trace.append("0,85≤CPI<0,90: +3")
    # SPI
    if spi is not None:
        if spi < 0.90: score += 5; trace.append("SPI<0,90: +5")
        elif spi < 0.95: score += 3; trace.append("0,90≤SPI<0,95: +3")
    # Gap físico x financeiro
    if fis is not None and fin is not None:
        gap = abs(fis - fin)
        if gap >= 15: score += 2; trace.append("Gap físico x financeiro ≥15pp: +2")
        elif gap >= 8: score += 1; trace.append("Gap físico x financeiro ≥8pp: +1")
    # Palavras-chave em observações
    obs_norm = normalize(observacoes)
    keywords = ["atraso","licenc","embargo","paralis","fornecedor","pressao","custo","multas","sancao","risco","equip","critico"]
    pontos = sum(1 for k in keywords if k in obs_norm)
    if pontos > 0:
        add = min(4, pontos); score += add; trace.append(f"Keywords observações (+{add})")
    return score

def risco_por_indices(ind: Dict[str, Optional[float]], trace: List[str]) -> float:
    score = 0.0
    def add(k: str, v: Optional[float]):
        nonlocal score
        if v is None: return
        if v < 0.90: score += 3; trace.append(f"{k.upper()}<0,90: +3")
        elif v < TARGETS["idx_meta"]: score += 1; trace.append(f"0,90≤{k.upper()}<1,00: +1")
        else: trace.append(f"{k.upper()}≥1,00: +0")
    for k in ("isp","idp","idco","idb"):
        add(k, ind.get(k))
    return score

def risco_por_cronograma(tarefas: List[Dict[str, Any]], trace: List[str]) -> float:
    score = 0.0
    hoje = date.today()
    for t in tarefas:
        fim = t.get("fim")
        pct = t.get("pct")
        crit = t.get("critica", False)
        atrasado = (isinstance(fim, date) and fim < hoje and (pct is None or pct < 100))
        if atrasado and crit:
            score += 3; trace.append(f"Tarefa crítica atrasada: {t.get('nome','')} (+3)")
        elif atrasado:
            score += 1; trace.append(f"Tarefa atrasada: {t.get('nome','')} (+1)")
        if pct is not None and pct < 30 and crit:
            score += 1; trace.append(f"Tarefa crítica <30%: {t.get('nome','')} (+1)")
    return score

def risco_por_baseline_financeiro(baseline: Dict[str, Any], fin: Dict[str, Any], trace: List[str]) -> float:
    score = 0.0
    capex_aprovado = to_number((baseline.get("custo") or {}).get("capex_aprovado"))
    eac = to_number(fin.get("eac"))
    vac = to_number(fin.get("vac"))
    if vac is not None and vac < 0:
        score += 3; trace.append("VAC < 0: +3")
    if capex_aprovado is not None and eac is not None and eac > capex_aprovado:
        score += 2; trace.append("EAC > CAPEX aprovado: +2")
    comp = to_number(fin.get("capex_comp") or fin.get("capex comprometido"))
    if capex_aprovado is not None and comp is not None and comp > capex_aprovado:
        score += 2; trace.append("Comprometido > Aprovado: +2")
    return score

def classificar_risco(score: float) -> str:
    # Política Kaio: sem "Crítico"
    if score >= 7: return "Alto"
    elif score >= 4: return "Médio"
    else: return "Baixo"

def inferir_pilar(campos: Dict[str, Any], campos_num: Dict[str, Optional[float]], indicadores: Dict[str, Optional[float]], trace: List[str]) -> Optional[str]:
    obs = normalize(campos.get("observacoes", ""))
    objetivo = normalize(campos.get("objetivo", ""))
    escopo = normalize(campos.get("escopo", ""))
    resumo_join = " ".join([normalize(x) for x in (campos.get("resumo_status") or [])])
    planos_join = " ".join([normalize(x) for x in (campos.get("planos_proximo_periodo") or [])])
    texto_base = " ".join([obs, objetivo, escopo, resumo_join, planos_join])

    cpi = campos_num.get("cpi_num")
    spi = campos_num.get("spi_num")
    isp, idp, idco, idb = (indicadores.get("isp"), indicadores.get("idp"), indicadores.get("idco"), indicadores.get("idb"))

    score_exc = 0; score_cli = 0; score_cap = 0
    if any(k in texto_base for k in ["processo","estrutura","governanca","governança","rituais","metas","desdobramento","coerencia","coerência","execucao","execução"]): score_exc += 2
    if any(k in texto_base for k in ["cliente","experiencia","experiência","sla","jornada","confiabilidade","satisfacao","satisfação","atendimento"]): score_cli += 2
    if any(k in texto_base for k in ["capex","investimento","priorizacao","priorização","retorno","vpl","tir","payback","disciplina de capital"]): score_cap += 2

    if (cpi is not None and cpi < TARGETS["cpi"]) or (spi is not None and spi < TARGETS["spi"]):
        score_exc += 2; trace.append("ECK hint→Excelência (CPI/SPI abaixo do target)")
    for v in (isp, idp, idco, idb):
        if v is not None and v < TARGETS["idx_meta"]: score_exc += 1
    fin_capex = to_number((campos.get("financeiro") or {}).get("capex_aprovado"))
    if any(k in texto_base for k in ["retorno","vpl","tir","payback"]) or fin_capex: score_cap += 1

    trio = [("Excelência Organizacional", score_exc), ("Foco no Cliente", score_cli), ("Alocação Estratégica de Capital", score_cap)]
    trio.sort(key=lambda x: x[1], reverse=True)
    if trio[0][1] == 0:
        return None
    sugerido = trio[0][0]
    trace.append(f"ECK sugerido: {sugerido} (E={score_exc}, C={score_cli}, K={score_cap})")
    return sugerido

# -------------------------------------------------------------------------------------------------
# Strategy Fit (mantido)
# -------------------------------------------------------------------------------------------------
def strategy_fit(campos: Dict[str, Any],
                 campos_num: Dict[str, Optional[float]],
                 indicadores: Dict[str, Optional[float]]) -> Dict[str, Any]:
    if not FEATURES["enable_strategy_fit"]:
        return {"score": None, "pilar_sugerido": None, "justificativa": None}
    objetivo = normalize(campos.get("objetivo", ""))
    resumo_join = " ".join([normalize(x) for x in (campos.get("resumo_status") or [])])
    escopo = normalize(campos.get("escopo", ""))
    obs = normalize(campos.get("observacoes", ""))
    planos_join = " ".join([normalize(x) for x in (campos.get("planos_proximo_periodo") or [])])
    texto = " ".join([objetivo, resumo_join, escopo, obs, planos_join])

    score_exc = 0; score_cli = 0; score_cap = 0
    if any(k in texto for k in ["processo","estrutura","governanca","rituais","metas","desdobramento","coerencia","execucao"]): score_exc += 20
    if any(k in texto for k in ["cliente","experiencia","sla","jornada","confiabilidade","satisfacao","atendimento"]): score_cli += 20
    if any(k in texto for k in ["capex","investimento","priorizacao","retorno","vpl","tir","payback"]): score_cap += 20

    cpi, spi = campos_num.get("cpi_num"), campos_num.get("spi_num")
    for (v, alvo) in [(cpi, TARGETS["cpi"]), (spi, TARGETS["spi"])]:
        if v is not None and v < alvo: score_exc += 10
    for v in (indicadores.get("isp"), indicadores.get("idp"), indicadores.get("idco"), indicadores.get("idb")):
        if v is not None and v < TARGETS["idx_meta"]: score_exc += 5

    raw_sum = score_exc + score_cli + score_cap
    if raw_sum == 0:
        return {"score": 0, "pilar_sugerido": None, "justificativa": "Sem sinais suficientes."}
    trio = [("Excelência Organizacional", score_exc), ("Foco no Cliente", score_cli), ("Alocação Estratégica de Capital", score_cap)]
    trio.sort(key=lambda x: x[1], reverse=True)
    pilar_sugerido, top = trio[0]
    score = int(min(100, max(0, (top / max(1, raw_sum)) * 100)))
    # justificativa textual curta
    return {"score": score, "pilar_sugerido": pilar_sugerido, "justificativa": f"Pilar com maior evidência nos textos do projeto."}

# -------------------------------------------------------------------------------------------------
# Camada de linguagem contextual
# -------------------------------------------------------------------------------------------------
def _first_delayed_critical_task(tarefas: List[Dict[str, Any]]) -> Optional[str]:
    hoje = date.today()
    for t in tarefas:
        fim = t.get("fim")
        pct = t.get("pct")
        crit = t.get("critica", False)
        if crit and isinstance(fim, date) and fim < hoje and (pct is None or pct < 100):
            return t.get("nome") or "tarefa crítica"
    return None

def _regulatory_flags(obs_norm: str) -> List[str]:
    reasons = []
    if "licenc" in obs_norm: reasons.append("licenças pendentes")
    if "embargo" in obs_norm: reasons.append("embargo/interdição")
    if "paralis" in obs_norm: reasons.append("paralisação de frentes")
    return reasons

def _supplier_flags(obs_norm: str) -> List[str]:
    reasons = []
    if "fornecedor" in obs_norm: reasons.append("fornecedor crítico")
    if "equip" in obs_norm: reasons.append("equipamentos sensíveis")
    return reasons

def diagnostico_contextual(campos: Dict[str, Any],
                           campos_num: Dict[str, Optional[float]],
                           tarefas: List[Dict[str, Any]],
                           baseline: Dict[str, Any],
                           fin: Dict[str, Any]) -> List[str]:
    """
    Gera bullets de diagnóstico explicativos (sem 'boilerplate'), com causas.
    """
    out: List[str] = []
    cpi = campos.get("cpi", "Não informado"); spi = campos.get("spi", "Não informado")
    cpi_num = campos_num.get("cpi_num"); spi_num = campos_num.get("spi_num")
    fis = campos_num.get("avanco_fisico_num"); finv = campos_num.get("avanco_financeiro_num")
    contrato = campos.get("tipo_contrato", "Não informado")
    obs_norm = normalize(campos.get("observacoes", ""))

    vac = to_number(fin.get("vac")); eac = to_number(fin.get("eac"))
    capex_aprovado = to_number((baseline.get("custo") or {}).get("capex_aprovado"))
    comp = to_number(fin.get("capex_comp") or fin.get("capex comprometido"))

    # Custo (CPI) com motivos
    custo_bits: List[str] = []
    if cpi_num is not None:
        custo_bits.append(f"CPI {cpi}")
        if vac is not None:
            if vac < 0: custo_bits.append("VAC negativo (projeção acima do aprovado)")
            elif vac >= 0: custo_bits.append("VAC não negativo")
        if eac is not None and capex_aprovado is not None and eac > capex_aprovado:
            custo_bits.append("EAC > CAPEX aprovado")
        if comp is not None and capex_aprovado is not None and comp > capex_aprovado:
            custo_bits.append("Comprometido > Aprovado")
        if "pressao" in obs_norm or "custo" in obs_norm:
            custo_bits.append("pressão de custos citada em observações")
        out.append("- Custo: " + " — ".join(custo_bits) + ".")

    # Prazo (SPI) com motivos
    prazo_bits: List[str] = []
    if spi_num is not None:
        prazo_bits.append(f"SPI {spi}")
        delayed = _first_delayed_critical_task(tarefas)
        if delayed:
            prazo_bits.append(f"tarefa crítica atrasada: {delayed}")
        reg = _regulatory_flags(obs_norm)
        if reg:
            prazo_bits.append(", ".join(reg))
        out.append("- Prazo: " + " — ".join(prazo_bits) + ".")

    # Execução (gap PF) com motivos
    if fis is not None and finv is not None:
        gap = abs(fis - finv)
        mot = "revisar critérios de medição e auditoria" if gap >= 8 else "gap sob controle"
        out.append(f"- Execução: físico ({campos.get('avanco_fisico')}) vs. financeiro ({campos.get('avanco_financeiro')}) — gap {gap:.1f}pp; {mot}.")

    # Contrato / Governança
    gov_hint = []
    if "sem governança" in normalize(contrato):
        gov_hint.append("reforçar governança contratual")
    if comp is not None and capex_aprovado is not None and comp > capex_aprovado:
        gov_hint.append("controle de comprometidos")
    if gov_hint:
        out.append(f"- Contrato: “{contrato}” — " + "; ".join(gov_hint) + ".")
    else:
        out.append(f"- Contrato: “{contrato}”.")
    return out

def riscos_chave_contextual(campos_num: Dict[str, Optional[float]],
                            tarefas: List[Dict[str, Any]],
                            baseline: Dict[str, Any],
                            fin: Dict[str, Any],
                            observacoes: str,
                            indicadores: Dict[str, Optional[float]]) -> List[str]:
    """
    Bullets de risco com mini-justificativa (porquês).
    """
    riscos: List[str] = []
    cpi = campos_num.get("cpi_num"); spi = campos_num.get("spi_num")
    fis = campos_num.get("avanco_fisico_num"); finv = campos_num.get("avanco_financeiro_num")
    obs_n = normalize(observacoes)
    delayed = _first_delayed_critical_task(tarefas)

    # Custo
    vac = to_number(fin.get("vac")); eac = to_number(fin.get("eac"))
    capex_aprovado = to_number((baseline.get("custo") or {}).get("capex_aprovado"))
    comp = to_number(fin.get("capex_comp") or fin.get("capex comprometido"))
    if cpi is not None:
        if cpi < 0.85:
            cause = []
            if vac is not None and vac < 0: cause.append("VAC negativo")
            if eac is not None and capex_aprovado is not None and eac > capex_aprovado: cause.append("EAC>CAPEX")
            if comp is not None and capex_aprovado is not None and comp > capex_aprovado: cause.append("Comprometido>aprovado")
            riscos.append("Custo: CPI < 0,85 — forte risco orçamentário" + (f" ({'; '.join(cause)})" if cause else "") + ".")
        elif cpi < TARGETS["cpi"]:
            riscos.append("Custo: CPI entre 0,85 e 0,90 — pressão de custos.")

    # Prazo
    if spi is not None:
        if spi < 0.90:
            motivo = []
            if delayed: motivo.append(f"tarefa crítica atrasada: {delayed}")
            motivo += _regulatory_flags(obs_n)
            riscos.append("Prazo: SPI < 0,90 — alto risco de atraso" + (f" ({'; '.join(motivo)})" if motivo else "") + ".")
        elif spi < TARGETS["spi"]:
            riscos.append("Prazo: SPI entre 0,90 e 0,95 — risco de deslizamento.")

    # Execução (gap)
    if fis is not None and finv is not None:
        gap = abs(fis - finv)
        if gap >= 15:
            riscos.append("Execução: gap físico x financeiro ≥15pp — possível inconsistência de medição (auditar critérios).")
        elif gap >= 8:
            riscos.append("Execução: gap físico x financeiro ≥8pp — atenção à coerência de medição.")

    # Índices (ISP/IDP/IDCo/IDB)
    for k in ("isp","idp","idco","idb"):
        v = indicadores.get(k)
        if v is not None and v < TARGETS["idx_meta"]:
            riscos.append(f"Índice {k.upper()} abaixo de 1,00 ({v:.2f}).")

    # Sinais de observações
    mapping = [
        ("licenc","Regulatório: risco de licenças/autorizações."),
        ("embargo","Regulatório: risco de embargo/interdição."),
        ("paralis","Operação: risco de paralisação de frentes."),
        ("fornecedor","Suprimentos: dependência de fornecedor crítico."),
        ("equip","Técnico: fornecimento de equipamentos sensível."),
        ("critico","Incidência de itens críticos."),
        ("risco","Riscos adicionais reportados.")
    ]
    seen=set()
    for key, msg in mapping:
        if key in obs_n and msg not in seen:
            riscos.append(msg); seen.add(msg)

    # Dedup
    out: List[str] = []
    memo=set()
    for r in riscos:
        if r not in memo:
            memo.add(r); out.append(r)
    return out

def contextual_justificativa_pilar(campos: Dict[str, Any],
                                   campos_num: Dict[str,
