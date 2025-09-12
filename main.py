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
        "nome do projeto", "objetivo",
        "resumo status", "resumo da situacao atual", "resumo da situação atual",
        "planos proximo periodo", "planos próximo periodo", "planos para o proximo periodo",
        "pontos de atencao", "pontos de atenção",
        "cpi", "spi", "isp", "idp", "idco", "idb",
        "avanco fisico", "avanco financeiro",
        "tipo de contrato", "stakeholders",
        "data final planejada",
        "baseline prazo", "baseline custo (capex aprovado)", "baseline custo",
        "escopo",
        "observacoes", "observações",
        "tarefas", "financeiro",
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
        elif nk in ("cpi", "spi", "isp", "idp", "idco", "idb"):
            ind = campos.get("indicadores") or {}
            if nk in ("cpi", "spi"):
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
        elif nk in ("baseline custo (capex aprovado)", "baseline custo"):
            b = campos.get("baseline") or {}
            bb = b.get("custo") or {}
            bb["capex_aprovado"] = val
            b["custo"] = bb
            campos["baseline"] = b
        elif nk == "escopo":
            campos["escopo"] = val or "Não informado"
        elif nk in ("observacoes", "observações"):
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
    keywords = ["atraso", "licenc", "embargo", "paralis", "fornecedor", "pressao", "custo", "multas", "sancao", "risco", "equip", "critico"]
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
    for k in ("isp", "idp", "idco", "idb"):
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
    return {"score": score, "pilar_sugerido": pilar_sugerido, "justificativa": "Pilar com maior evidência nos textos do projeto."}

# -------------------------------------------------------------------------------------------------
# Camada de linguagem contextual
# -------------------------------------------------------------------------------------------------
def split_stakeholders(stakeholders: str) -> List[str]:
    if not stakeholders or stakeholders == "Não informado":
        return []
    parts: List[str] = []
    for sep in [";", ",", "\\n", "\n"]:
        if sep in stakeholders:
            parts = [p.strip() for p in stakeholders.split(sep)]
            break
    if not parts:
        parts = [stakeholders.strip()]
    return [p for p in parts if p]

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
    Gera bullets de diagnóstico explicativos (sem 'boilerplate'), com causas reais.
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
    if cpi_num is not None:
        custo_bits: List[str] = [f"CPI {cpi}"]
        if vac is not None:
            if vac < 0: custo_bits.append("VAC negativo (projeção acima do aprovado)")
            else: custo_bits.append("VAC não negativo")
        if eac is not None and capex_aprovado is not None and eac > capex_aprovado:
            custo_bits.append("EAC > CAPEX aprovado")
        if comp is not None and capex_aprovado is not None and comp > capex_aprovado:
            custo_bits.append("Comprometido > Aprovado")
        if "pressao" in obs_norm or "custo" in obs_norm:
            custo_bits.append("pressão de custos citada em observações")
        out.append("- Custo: " + " — ".join(custo_bits) + ".")

    # Prazo (SPI) com motivos
    if spi_num is not None:
        prazo_bits: List[str] = [f"SPI {spi}"]
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
    for k in ("isp", "idp", "idco", "idb"):
        v = indicadores.get(k)
        if v is not None and v < TARGETS["idx_meta"]:
            riscos.append(f"Índice {k.upper()} abaixo de 1,00 ({v:.2f}).")

    # Sinais de observações
    mapping = [
        ("licenc", "Regulatório: risco de licenças/autorizações."),
        ("embargo", "Regulatório: risco de embargo/interdição."),
        ("paralis", "Operação: risco de paralisação de frentes."),
        ("fornecedor", "Suprimentos: dependência de fornecedor crítico."),
        ("equip", "Técnico: fornecimento de equipamentos sensível."),
        ("critico", "Incidência de itens críticos."),
        ("risco", "Riscos adicionais reportados.")
    ]
    seen = set()
    for key, msg in mapping:
        if key in obs_n and msg not in seen:
            riscos.append(msg); seen.add(msg)

    # Dedup
    out: List[str] = []
    memo = set()
    for r in riscos:
        if r not in memo:
            memo.add(r); out.append(r)
    return out

def contextual_justificativa_pilar(campos: Dict[str, Any],
                                   campos_num: Dict[str, Optional[float]],
                                   indicadores: Dict[str, Optional[float]],
                                   pilar_foco: str) -> str:
    """
    Retorna justificativa textual específica do projeto para o pilar de foco.
    """
    texto = " ".join([
        normalize(campos.get("objetivo", "")),
        normalize(campos.get("observacoes", "")),
        normalize(campos.get("escopo", "")),
        " ".join([normalize(x) for x in (campos.get("resumo_status") or [])]),
        " ".join([normalize(x) for x in (campos.get("planos_proximo_periodo") or [])]),
    ])
    p = normalize(pilar_foco)
    cpi = campos_num.get("cpi_num"); spi = campos_num.get("spi_num")
    isp = indicadores.get("isp"); idp = indicadores.get("idp"); idco = indicadores.get("idco"); idb = indicadores.get("idb")

    if "cliente" in p:
        sinais = []
        for kw in ["cliente", "jornada", "sla", "confiabilidade", "satisfacao", "satisfação", "atendimento"]:
            if kw in texto: sinais.append(kw)
        base = "Foco no Cliente, pois o projeto cita diretamente jornadas/SLAs/necessidades do cliente" if sinais else \
               "Foco no Cliente, pela natureza de impacto em experiência/confiabilidade do cliente"
        return base + (f" (sinais: {', '.join(sorted(set(sinais)))})." if sinais else ".")
    if "excelencia" in p:
        sinais = []
        for kw in ["processo", "governanca", "governança", "estrutura", "rituais", "metas", "desdobramento", "execucao", "execução", "seguranca", "segurança"]:
            if kw in texto: sinais.append(kw)
        met = []
        if cpi is not None and cpi < TARGETS["cpi"]: met.append("CPI abaixo da meta")
        if spi is not None and spi < TARGETS["spi"]: met.append("SPI abaixo da meta")
        for v, cod in [(isp, "ISP"), (idp, "IDP"), (idco, "IDCo"), (idb, "IDB")]:
            if v is not None and v < TARGETS["idx_meta"]:
                met.append(f"{cod}<1,00")
        motivo = "Excelência Organizacional, com ênfase em pessoas/processos/governança para execução coordenada"
        extras = []
        if sinais: extras.append(f"sinais: {', '.join(sorted(set(sinais)))}")
        if met: extras.append(f"métricas a endereçar: {', '.join(met)}")
        return motivo + (f" ({'; '.join(extras)})." if extras else ".")
    if "alocacao" in p:
        sinais = []
        for kw in ["capex", "investimento", "retorno", "vpl", "tir", "payback"]:
            if kw in texto: sinais.append(kw)
        motivo = "Alocação Estratégica de Capital, pela ênfase em retorno de longo prazo e disciplina de capital"
        return motivo + (f" (sinais: {', '.join(sorted(set(sinais)))})." if sinais else ".")
    return f"Pilar de foco: {pilar_foco}."

def gerar_projecao_contextual(campos: Dict[str, Any],
                              campos_num: Dict[str, Optional[float]],
                              tarefas: List[Dict[str, Any]],
                              baseline: Dict[str, Any],
                              fin: Dict[str, Any],
                              observacoes: str) -> List[str]:
    """
    Projeção sob medida com base nos drivers dominantes do caso.
    """
    out: List[str] = []
    spi = campos_num.get("spi_num"); cpi = campos_num.get("cpi_num")
    obs_n = normalize(observacoes)
    delayed = _first_delayed_critical_task(tarefas)
    vac = to_number(fin.get("vac")); eac = to_number(fin.get("eac"))
    capex_aprovado = to_number((baseline.get("custo") or {}).get("capex_aprovado"))

    curto = []
    if spi is not None and spi < TARGETS["spi"]:
        if delayed: curto.append(f"deslizamento de marcos por {delayed}")
        if "licenc" in obs_n or "embargo" in obs_n: curto.append("restrições regulatórias")
    if cpi is not None and cpi < TARGETS["cpi"]:
        if vac is not None and vac < 0: curto.append("pressão orçamentária (VAC<0)")
        if eac is not None and capex_aprovado is not None and eac > capex_aprovado: curto.append("tendência de EAC>CAPEX")

    medio = []
    if spi is not None and spi < 0.90:
        medio.append("impacto em marcos contratuais/penalidades")
    if cpi is not None and cpi < 0.85:
        medio.append("necessidade de rebase financeiro e cortes de escopo")

    out.append("- Curto prazo: " + (", ".join(curto) if curto else "sem impactos relevantes projetados.") )
    out.append("- Médio prazo: " + (", ".join(medio) if medio else "metas e prazos tendem a se manter sob controle.") )
    if "stake" in obs_n or "comunic" in obs_n:
        out.append("- Stakeholders: intensificar monitoramento e comunicação executiva.")
    else:
        out.append("- Stakeholders: manter cadência de ritos executivos e transparência de status.")
    return out

def gerar_recomendacoes_contextuais(campos: Dict[str, Any],
                                    campos_num: Dict[str, Optional[float]],
                                    tarefas: List[Dict[str, Any]],
                                    baseline: Dict[str, Any],
                                    fin: Dict[str, Any],
                                    observacoes: str,
                                    pilar_foco: str) -> List[str]:
    """
    Recomendações ligadas às causas detectadas e ao pilar de foco.
    """
    recs: List[str] = []
    obs_n = normalize(observacoes)
    cpi = campos_num.get("cpi_num"); spi = campos_num.get("spi_num")
    gap_pf = None
    fis = campos_num.get("avanco_fisico_num"); finv = campos_num.get("avanco_financeiro_num")
    if fis is not None and finv is not None:
        gap_pf = abs(fis - finv)
    vac = to_number(fin.get("vac")); eac = to_number(fin.get("eac"))
    capex_aprovado = to_number((baseline.get("custo") or {}).get("capex_aprovado"))
    delayed = _first_delayed_critical_task(tarefas)

    # Prazo
    if spi is not None and spi < TARGETS["spi"]:
        if delayed: recs.append(f"Replanejar caminho crítico e atacar {delayed} com dono e data (D+5).")
        if "licenc" in obs_n or "embargo" in obs_n: recs.append("Acionar frente regulatória/jurídica para destravar licenças/embargos (D+3).")

    # Custo
    if cpi is not None and cpi < TARGETS["cpi"]:
        if vac is not None and vac < 0 or (eac is not None and capex_aprovado is not None and eac > capex_aprovado):
            recs.append("Instalar ou reforçar Change Control Board e rebaselinar financeiro (D+10).")

    # Gap PF
    if gap_pf is not None:
        if gap_pf >= 15: recs.append("Auditar critérios de medição físico x financeiro (≥15pp) e unificar regras (D+7).")
        elif gap_pf >= 8: recs.append("Alinhar critérios de medição físico x financeiro (≥8pp) (D+10).")

    # Fornecedor
    if "fornecedor" in obs_n:
        recs.append("Conduzir reunião executiva com fornecedor crítico e plano 5W2H/contingência (D+3).")

    # Pilar foco
    pf = normalize(pilar_foco)
    if "excelencia" in pf:
        recs.append("Implantar rituais semanais de performance com metas desdobradas e RACI claro (D+7).")
    if "cliente" in pf:
        recs.append("Mapear jornada do cliente e ajustar SLAs de comunicação/serviço (D+15).")
    if "alocacao" in pf:
        recs.append("Revisar business case (VPL/TIR ajustados a risco) e repriorizar CAPEX (D+20).")

    # Donos
    owners = split_stakeholders(campos.get("stakeholders", ""))
    if owners:
        recs.append(f"Owners sugeridos: {', '.join(owners[:3])}.")
    # Dedup
    out: List[str] = []
    seen = set()
    for r in recs:
        if r not in seen:
            seen.add(r); out.append(r)
    return out

def analise_estrategica_textual(campos: Dict[str, Any],
                                strategy: Dict[str, Any],
                                classificacao_risco: str,
                                divergente: bool,
                                pilar_declarado: str,
                                pilar_sugerido: Optional[str]) -> Dict[str, Any]:
    """
    Consolida pitacos estratégicos em texto (sem scores no TXT):
    - Alinhamento (Alinhado/Parcial/Não) com motivo
    - Fit de Portfólio (Core/Opcionalidade/Exploratório/Indefinido)
    - Faz sentido? (Sim/Parcial/Não)
    - Rota recomendada (Acelerar/Seguir/Salvaguardas/Pausar/Pivotar)
    - Bullets de Continuar/Ajustar/Parar
    """
    # Base textual
    texto = " ".join([
        normalize(campos.get("objetivo", "")),
        normalize(campos.get("observacoes", "")),
        normalize(campos.get("escopo", "")),
        " ".join([normalize(x) for x in (campos.get("resumo_status") or [])]),
        " ".join([normalize(x) for x in (campos.get("planos_proximo_periodo") or [])]),
    ])

    # Derivar pilar de foco
    pilar_foco = pilar_sugerido or (pilar_declarado if pilar_declarado != "Não informado" else "Não informado")

    # Fit de Portfólio
    def _classificar_portfolio(t: str) -> Tuple[str, str]:
        core_kw = ["transmissao","transmissão","lt","linhas de transmissao","subestacao","subestação","uhe","hidreletrica","hidrelétrica","eolico onshore","eólico onshore","solar onshore","geracao","geração","rm transmissao","rm geração"]
        opc_kw = ["armazenamento","bateria","adicao de potencia","adição de potência","repotenciacao","repotenciação","modernizacao","modernização","eficiencia energetica","eficiência energética","gestao de ativos","gestão de ativos","ppa corporativo","contratos corporativos"]
        exp_kw = ["eolica offshore","eólica offshore","hidrogenio verde","hidrogênio verde","datacenter","data center","telecom","criptomoeda","crypto","internacionalizacao","internacionalização","gd flutuante","offshore","h2v"]
        if any(k in t for k in core_kw): return "Core", "Aderente ao core (Transmissão/Geração renovável e O&M)."
        if any(k in t for k in opc_kw): return "Opcionalidade", "Adjacências que ampliam o portfólio (armazenamento/repotenciação/eficiência)."
        if any(k in t for k in exp_kw): return "Exploratório", "Trilhas emergentes com maturidade setorial em evolução."
        return "Indefinido", "Sem sinais setoriais claros no texto."
    portfolio_fit, portfolio_msg = _classificar_portfolio(texto)

    # Alinhamento (usa strategy_fit e penaliza divergência/risco para decisão textual)
    base = strategy.get("score") or 0
    ajuste = 0
    if divergente:
        ajuste -= 10
    if classificacao_risco == "Alto":
        ajuste -= 20
    elif classificacao_risco == "Médio":
        ajuste -= 10
    score_final = max(0, min(100, base + ajuste))
    if score_final >= 60 and portfolio_fit in ("Core", "Opcionalidade"):
        alinhamento = "Alinhado"; motivo_alinhamento = "coerente com a Visão 2028/E‑C‑K para o portfólio atual."
    elif score_final >= 40:
        alinhamento = "Parcialmente alinhado"; motivo_alinhamento = "há aderência parcial; é preciso ajustar premissas/escopo para elevar o fit."
    else:
        alinhamento = "Não alinhado"; motivo_alinhamento = "baixo fit estratégico e/ou riscos elevados para o momento."

    # Faz sentido?
    faz_sentido = "Sim" if alinhamento == "Alinhado" else ("Parcialmente" if alinhamento == "Parcialmente alinhado" else "Não")

    # Rota recomendada
    if classificacao_risco == "Alto" and alinhamento != "Alinhado":
        rota = "Pausar/Pivotar"; rota_msg = "Pausar compromissos irreversíveis e pivotar escopo para elevar alinhamento e reduzir risco."
    elif classificacao_risco == "Alto":
        rota = "Seguir com salvaguardas"; rota_msg = "Manter andamento com gates de decisão e mitigadores de prazo/custo."
    elif classificacao_risco == "Médio":
        rota = "Seguir"; rota_msg = "Prosseguir com controle ativo (EVM/rituais) e validação de hipóteses de cliente/retorno."
    else:
        rota = "Acelerar" if alinhamento == "Alinhado" else "Seguir"
        rota_msg = "Capturar ganhos rápidos no pilar de foco." if rota == "Acelerar" else "Seguir plano com monitoramento padrão."

    # Recomendações (resumo)
    continuar, ajustar, parar = [], [], []
    pf = normalize(pilar_foco)
    if "cliente" in pf: continuar.append("Aprofundar entendimento de necessidades e SLAs do cliente.")
    if "excelencia" in pf: continuar.append("Manter rituais de performance e coerência entre áreas.")
    if "alocacao" in pf: continuar.append("Reforçar disciplina de capital e revisão de business case.")

    if alinhamento == "Parcialmente alinhado":
        ajustar.append("Reenquadrar escopo/premissas para o pilar de foco e conectar entregas à Visão 2028.")
    if alinhamento == "Não alinhado":
        parar.append("Evitar CAPEX relevante até elevar o fit estratégico e mitigar riscos principais.")

    # LEAN
    if LEAN_MODE:
        continuar = continuar[:1] or ["Manter disciplina no pilar de foco."]
        ajustar = ajustar[:1] or ["Ajustar premissas para elevar o fit."]
        parar = parar[:1] if parar else []

    return {
        "alinhamento": alinhamento,
        "motivo_alinhamento": motivo_alinhamento,
        "portfolio_fit": portfolio_fit,
        "portfolio_msg": portfolio_msg,
        "faz_sentido": faz_sentido,
        "rota_recomendada": rota,
        "rota_msg": rota_msg,
        "recomendacoes_continuar": continuar,
        "recomendacoes_ajustar": ajustar,
        "recomendacoes_parar": parar,
        "pilar_estrategico_foco": pilar_foco,
        "score_interno": score_final,  # mantido no JSON, mas não exibido no TXT
    }

# -------------------------------------------------------------------------------------------------
# Lições aprendidas (mantido, com toques leves)
# -------------------------------------------------------------------------------------------------
def gerar_licoes_aprendidas(campos: Dict[str, Any],
                            campos_num: Dict[str, Optional[float]],
                            kpis: Dict[str, Any],
                            tarefas: List[Dict[str, Any]],
                            riscos_chave: List[str]) -> List[Dict[str, str]]:
    if not FEATURES["enable_lessons_learned"]:
        return []
    itens: List[Dict[str, str]] = []
    owners = split_stakeholders(campos.get("stakeholders", ""))
    owner = owners[0] if owners else "PMO/Projeto"

    cpi = campos_num.get("cpi_num"); spi = campos_num.get("spi_num")
    if cpi is not None and cpi < TARGETS["cpi"]:
        itens.append({
            "problema": "Desvio de custo (CPI abaixo da meta).",
            "causa_raiz": "Estimativas subavaliadas e controle de mudanças sem gate claro.",
            "contramedida": "Reforçar Change Control Board e auditoria de medição financeira.",
            "owner": owner, "prazo": "D+14", "categoria": "Financeiro/Controle"
        })
    if spi is not None and spi < TARGETS["spi"]:
        itens.append({
            "problema": "Risco de atraso (SPI abaixo da meta).",
            "causa_raiz": "Caminho crítico sem replanejamento tempestivo.",
            "contramedida": "Replanejar caminho crítico e instituir rito semanal com EVM.",
            "owner": owner, "prazo": "D+7", "categoria": "Prazo/Planejamento"
        })

    gap_pf = kpis.get("gap_pf")
    if gap_pf is not None and gap_pf >= 15:
        itens.append({
            "problema": "Assimetria físico x financeiro ≥15pp.",
            "causa_raiz": "Critérios de medição divergentes entre equipes.",
            "contramedida": "Unificar critérios e auditar 3 pacotes críticos.",
            "owner": owner, "prazo": "D+10", "categoria": "Execução/Medição"
        })

    hoje = date.today()
    for t in tarefas:
        if t.get("critica") and isinstance(t.get("fim"), date) and t["fim"] < hoje and (t.get("pct") or 0) < 100:
            itens.append({
                "problema": f"Tarefa crítica atrasada: {t.get('nome','')}.",
                "causa_raiz": "Sequenciamento de frentes e restrições não modeladas.",
                "contramedida": "Remover restrições (LPS) e travas de pré-requisitos.",
                "owner": owner, "prazo": "D+5", "categoria": "Planejamento/Execução"
            })
            break
    return itens[:5]

# -------------------------------------------------------------------------------------------------
# Formatação (TXT/MD/HTML) - inclui novas seções contextuais
# -------------------------------------------------------------------------------------------------
def format_report(campos: Dict[str, Any],
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
                  justificativa_sugerido: Optional[str],
                  strategy: Dict[str, Any],
                  licoes: List[Dict[str, str]],
                  analise: Dict[str, Any],
                  diag_ctx: List[str],
                  proj_ctx: List[str],
                  recs_ctx: List[str]) -> Dict[str, str]:

    nome = campos.get("nome_projeto", "Projeto não identificado") or "Projeto não identificado"
    cpi = campos.get("cpi", "Não informado")
    spi = campos.get("spi", "Não informado")
    fisico = campos.get("avanco_fisico", "Não informado")
    financeiro_pf = campos.get("avanco_financeiro", "Não informado")
    contrato = campos.get("tipo_contrato", "Não informado")
    stakeholders = campos.get("stakeholders", "Não informado")
    observacoes = campos.get("observacoes", "Não informado")
    objetivo = campos.get("objetivo", "Não informado")
    resumo_status = campos.get("resumo_status") or []
    planos = campos.get("planos_proximo_periodo") or []
    pontos = campos.get("pontos_atencao") or []
    escopo = campos.get("escopo", "Não informado")
    data_final = campos.get("data_final_planejada", "Não informado")
    ind = campos.get("indicadores") or {}
    isp = ind.get("isp"); idp = ind.get("idp"); idco = ind.get("idco"); idb = ind.get("idb")
    fin = campos.get("financeiro") or {}
    capex_aprovado = fin.get("capex_aprovado") or (campos.get("baseline", {}).get("custo", {}) or {}).get("capex_aprovado")
    capex_comp = fin.get("capex_comp") or fin.get("capex comprometido")
    capex_exec = fin.get("capex_exec") or fin.get("capex executado")
    ev = fin.get("ev"); pv = fin.get("pv"); ac = fin.get("ac"); eac = fin.get("eac"); vac = fin.get("vac")
    risco_emoji = {"Alto": "🔴", "Médio": "🟠", "Baixo": "🟢"}.get(risco, "⚠️")

    # --- Texto (para A360) ---
    txt: List[str] = []
    txt += [
        f"📊 Relatório Executivo Preditivo – Projeto “{nome}”",
        "",
        "✅ Status Geral",
        f"CPI: {cpi}",
        f"SPI: {spi}",
        f"Avanço Físico: {fisico}",
        f"Avanço Financeiro: {financeiro_pf}",
        f"Tipo de Contrato: {contrato}",
        f"Stakeholders: {stakeholders}",
        f"Risco (classificação): {risco} {risco_emoji} (score interno: {score:.1f})",
        f"Observação: {observacoes}",
    ]
    if escopo and escopo != "Não informado":
        txt += [f"Escopo: {escopo}"]
    if data_final and data_final != "Não informado":
        txt += [f"Data Final Planejada: {data_final}"]

    txt += ["", "🎯 Objetivo do Projeto", f"{objetivo if objetivo!='Não informado' else '—'}"]

    # Resumo/Planos/Pontos
    if resumo_status:
        txt += ["", "📝 RESUMO DA SITUAÇÃO ATUAL (PROGRESSO) E AÇÕES CORRETIVAS REALIZADAS"]
        txt += [f"- {b}" for b in resumo_status]
    if planos:
        txt += ["", "📅 PLANOS PARA O PRÓXIMO PERÍODO"]
        txt += [f"- {b}" for b in planos]
    if pontos:
        txt += ["", "🔎 PONTOS DE ATENÇÃO"]
        txt += [f"- {b}" for b in pontos]

    # 📈 Diagnóstico de Performance (contextual)
    txt += ["", "📈 Diagnóstico de Performance"]
    txt += diag_ctx

    # Índices meta 1,00 (apenas se vierem)
    if any(x is not None for x in (isp, idp, idco, idb)):
        txt += ["- Indicadores de desempenho (meta = 1,00):"]
        if isp is not None: txt.append(f" • ISP: {isp}")
        if idp is not None: txt.append(f" • IDP: {idp}")
        if idco is not None: txt.append(f" • IDCo: {idco}")
        if idb is not None: txt.append(f" • IDB: {idb}")

    # Financeiro (resumo)
    if FEATURES["enable_finance_pack"] and any([capex_aprovado, capex_comp, capex_exec, ev, pv, ac, eac, vac]):
        txt += ["", "💰 Financeiro (resumo)"]
        if capex_aprovado: txt.append(f"- CAPEX Aprovado: {capex_aprovado}")
        if capex_comp: txt.append(f"- CAPEX Comprometido: {capex_comp}")
        if capex_exec: txt.append(f"- CAPEX Executado: {capex_exec}")
        evpvac = []
        if ev is not None: evpvac.append(f"EV={ev}")
        if pv is not None: evpvac.append(f"PV={pv}")
        if ac is not None: evpvac.append(f"AC={ac}")
        if eac is not None: evpvac.append(f"EAC={eac}")
        if vac is not None: evpvac.append(f"VAC={vac}")
        if evpvac: txt.append("- " + ", ".join(evpvac))

    # Riscos‑chave (contextual)
    if riscos_chave:
        txt += ["", "⚠️ Riscos‑chave identificados"]
        txt += [f"- {r}" for r in riscos_chave]

    # Projeção de Impactos (contextual)
    txt += ["", "📅 Projeção de Impactos"]
    txt += proj_ctx

    # Recomendações Estratégicas (contextuais)
    if recs_ctx:
        txt += ["", "🧠 Recomendações Estratégicas"]
        txt += [f"- {r}" for r in recs_ctx]

    # Pilar ECK (sem duplicidade quando não há divergência)
    txt += ["", "🏛️ Pilar ECK (foco estratégico)"]
    if divergente and pilar_sugerido:
        txt.append(f"- Pilar declarado: {pilar_declarado}")
        txt.append(f"- Pilar sugerido (análise): {pilar_sugerido} ⚠️ (recomendado realinhar)")
        if justificativa_sugerido: txt.append(f"- Por que este projeto indica {pilar_sugerido}: {justificativa_sugerido}")
    else:
        show_txt = pilar_declarado if pilar_declarado != "Não informado" else pilar_final
        txt.append(f"- Pilar de foco: {show_txt}")
        txt.append(f"- Por que este projeto indica {show_txt}: {justificativa_eck_txt}")

    # Strategy fit (mantido, mas sucinto)
    if FEATURES["enable_strategy_fit"] and strategy.get("score") is not None and strategy.get("pilar_sugerido"):
        txt += ["", "📐 Strategy Fit (ECK)"]
        txt += [f"- Pilar dominante sugerido pela leitura de conteúdo: {strategy['pilar_sugerido']}"]

    # Próximos Passos (2 trilhas)
    if proximos_passos_recomendado:
        txt += ["", "▶ Próximos Passos — (Recomendado, alinhado ao Pilar sugerido)"]
        txt += [f"- {p}" for p in proximos_passos_recomendado]
    if proximos_passos_atual:
        txt += ["", "▶ Próximos Passos — (Atual, alinhado ao Pilar declarado)"]
        txt += [f"- {p}" for p in proximos_passos_atual]

    # Lições aprendidas
    if licoes:
        txt += ["", "📚 Lições Aprendidas (sugeridas)"]
        for it in licoes:
            txt += [
                f"- Problema: {it['problema']}",
                f" • Causa-raiz: {it['causa_raiz']}",
                f" • Contramedida: {it['contramedida']}",
                f" • Owner: {it['owner']} • Prazo: {it['prazo']} • Categoria: {it['categoria']}",
            ]

    # 🧭 Análise Estratégica (textual, sem números)
    if FEATURES["enable_strategic_analysis"]:
        txt += ["", "🧭 Análise Estratégica"]
        txt += [
            f"- Alinhamento com a Visão: {analise['alinhamento']} — {analise['motivo_alinhamento']}",
            f"- Fit de Portfólio: {analise['portfolio_fit']} — {analise['portfolio_msg']}",
            f"- Faz sentido para a companhia? {analise['faz_sentido']}",
            f"- Rota recomendada: {analise['rota_recomendada']} — {analise['rota_msg']}",
        ]
        if not LEAN_MODE:
            txt += ["• Continuar"]
            txt += [f"  - {b}" for b in (analise.get("recomendacoes_continuar") or ["—"])]
            txt += ["• Ajustar"]
            txt += [f"  - {b}" for b in (analise.get("recomendacoes_ajustar") or ["—"])]
            if analise.get("recomendacoes_parar"):
                txt += ["• Parar/Evitar"]
                txt += [f"  - {b}" for b in analise["recomendacoes_parar"]]

    # Resumo executivo (mais rico)
    txt += ["", "✅ Resumo Executivo"]
    resumo_foco = (pilar_sugerido or pilar_final) if (divergente and pilar_sugerido) else (pilar_declarado if pilar_declarado != "Não informado" else pilar_final)
    linha = (
        f"O projeto “{nome}” apresenta risco {risco.lower()} {({'Alto':'🔴','Médio':'🟠','Baixo':'🟢'}.get(risco,'⚠️'))}. "
        f"Foco no pilar {resumo_foco}. "
        f"Principais direcionadores: {', '.join([d[2:] if d.startswith('- ') else d for d in diag_ctx[:2]])}. "
        f"Rota: {analise.get('rota_recomendada','Seguir')} — {analise.get('rota_msg','')}"
    )
    txt.append(linha.strip())

    txt_report = "\n".join(txt)
    md_report = txt_report
    html_report = html.escape(txt_report).replace("\n", "<br/>")
    return {"txt": txt_report.strip(), "md": md_report.strip(), "html": html_report}

# -------------------------------------------------------------------------------------------------
# Core: _analisar
# -------------------------------------------------------------------------------------------------
def _analisar(campos: Dict[str, Any]) -> Dict[str, Any]:
    trace: List[str] = []

    # Números normalizados
    campos_num: Dict[str, Optional[float]] = {
        "cpi_num": to_number(campos.get("cpi")),
        "spi_num": to_number(campos.get("spi")),
        "avanco_fisico_num": percent_to_number(campos.get("avanco_fisico")),
        "avanco_financeiro_num": percent_to_number(campos.get("avanco_financeiro")),
    }

    # Indicadores 1,00
    ind_raw = campos.get("indicadores") or {}
    indicadores: Dict[str, Optional[float]] = {
        "isp": to_number(ind_raw.get("isp")),
        "idp": to_number(ind_raw.get("idp")),
        "idco": to_number(ind_raw.get("idco")),
        "idb": to_number(ind_raw.get("idb")),
    }

    # Cronograma
    tarefas: List[Dict[str, Any]] = []
    if (campos.get("cronograma") or {}).get("tarefas"):
        for t in campos["cronograma"]["tarefas"]:
            tarefas.append({
                "nome": t.get("nome"),
                "inicio": t.get("inicio") if isinstance(t.get("inicio"), date) else parse_date(t.get("inicio")),
                "fim": t.get("fim") if isinstance(t.get("fim"), date) else parse_date(t.get("fim")),
                "pct": t.get("pct") if isinstance(t.get("pct"), (int, float)) else to_number(t.get("pct")),
                "critica": bool(t.get("critica")),
            })

    # Baseline e financeiro normalizado
    baseline = campos.get("baseline") or {}
    fin_raw = campos.get("financeiro") or {}
    fin = {
        "capex_aprovado": fin_raw.get("capex_aprovado") or ((baseline.get("custo") or {}).get("capex_aprovado")),
        "capex_comp": fin_raw.get("capex_comp") or fin_raw.get("capex comprometido"),
        "capex_exec": fin_raw.get("capex_exec") or fin_raw.get("capex executado"),
        "ev": fin_raw.get("ev"), "pv": fin_raw.get("pv"), "ac": fin_raw.get("ac"),
        "eac": fin_raw.get("eac"), "vac": fin_raw.get("vac"),
    }

    # KPIs auxiliares
    gap_pf = None
    if campos_num["avanco_fisico_num"] is not None and campos_num["avanco_financeiro_num"] is not None:
        gap_pf = abs(campos_num["avanco_fisico_num"] - campos_num["avanco_financeiro_num"])
    kpis = {
        "gap_pf": gap_pf,
        "gap_spi": (TARGETS["spi"] - campos_num["spi_num"]) if campos_num["spi_num"] is not None else None,
        "gap_cpi": (TARGETS["cpi"] - campos_num["cpi_num"]) if campos_num["cpi_num"] is not None else None,
    }

    # Pilar (declarado x sugerido)
    pilar_declarado = campos.get("pilar", "Não informado")
    pilar_inferido = inferir_pilar(campos, campos_num, indicadores, trace)  # pode ser None

    # Divergência
    def _norm(s): return normalize(s or "")
    divergente = (
        pilar_declarado and pilar_declarado != "Não informado" and
        pilar_inferido and _norm(pilar_declarado) != _norm(pilar_inferido)
    )

    # Pilar final (política: se declararam, prevalece; senão usa inferido)
    pilar_final = pilar_declarado if (pilar_declarado and pilar_declarado != "Não informado") else (pilar_inferido or "Não informado")
    if divergente:
        trace.append(f"Divergência Pilar: declarado='{pilar_declarado}' vs sugerido='{pilar_inferido}'")

    # Score/classificação de risco
    score = 0.0
    score += calcular_score_risco_base(campos_num, campos.get("observacoes", ""), trace)
    score += risco_por_indices(indicadores, trace)
    if FEATURES["enable_schedule_pack"]:
        score += risco_por_cronograma(tarefas, trace)
    if FEATURES["enable_finance_pack"]:
        score += risco_por_baseline_financeiro(baseline, fin, trace)
    classificacao = classificar_risco(score)

    # Próximos passos — 2 trilhas
    pilar_para_recomendado = pilar_inferido or pilar_final
    proximos_recomendado = gerar_recomendacoes_contextuais(
        campos, campos_num, tarefas, baseline, fin, campos.get("observacoes", ""), pilar_para_recomendado
    )
    proximos_atual = gerar_recomendacoes_contextuais(
        campos, campos_num, tarefas, baseline, fin, campos.get("observacoes", ""), pilar_declarado if pilar_declarado else "Não informado"
    )

    # Riscos‑chave (contextual)
    riscos_ctx = riscos_chave_contextual(campos_num, tarefas, baseline, fin, campos.get("observacoes", ""), indicadores)

    # Strategy fit
    strategy = strategy_fit(campos, campos_num, indicadores)

    # Lições aprendidas
    licoes = gerar_licoes_aprendidas(campos, campos_num, kpis, tarefas, riscos_ctx)

    # Justificativas de pilar (contextualizadas)
    justificativa_final = contextual_justificativa_pilar(campos, campos_num, indicadores, pilar_final)
    justificativa_sugerido = contextual_justificativa_pilar(campos, campos_num, indicadores, pilar_inferido) if pilar_inferido else None

    # Análise Estratégica (textual)
    analise = analise_estrategica_textual(
        campos=campos,
        strategy=strategy,
        classificacao_risco=classificacao,
        divergente=divergente,
        pilar_declarado=pilar_declarado,
        pilar_sugerido=pilar_inferido
    ) if FEATURES["enable_strategic_analysis"] else {}

    # Diagnóstico / Projeção (contextuais)
    diag_ctx = diagnostico_contextual(campos, campos_num, tarefas, baseline, fin)
    proj_ctx = gerar_projecao_contextual(campos, campos_num, tarefas, baseline, fin, campos.get("observacoes", ""))

    # Relatórios
    reports = format_report(
        campos=campos, campos_num=campos_num, score=score, risco=classificacao,
        pilar_declarado=pilar_declarado, pilar_final=pilar_final,
        justificativa_eck_txt=justificativa_final,
        proximos_passos_recomendado=proximos_recomendado,
        proximos_passos_atual=proximos_atual,
        kpis=kpis, riscos_chave=riscos_ctx,
        divergente=divergente, pilar_sugerido=pilar_inferido,
        justificativa_sugerido=justificativa_sugerido,
        strategy=strategy, licoes=licoes,
        analise=analise,
        diag_ctx=diag_ctx, proj_ctx=proj_ctx, recs_ctx=proximos_recomendado  # recomendo usar as do recomendado como base
    )

    payload_out = {
        "versao_api": app.version,
        "campos_interpretados": {**campos, **campos_num, "pilar_final": pilar_final},
        "indicadores": indicadores,
        "kpis": kpis,
        "score_risco": score,
        "classificacao_risco": classificacao,
        "riscos_chave": riscos_ctx,
        "strategy_fit": strategy,
        "pilar_declarado": pilar_declarado,
        "pilar_sugerido": pilar_inferido,
        "pilar_divergente": divergente,
        "proximos_passos_recomendado": proximos_recomendado,
        "proximos_passos_atual": proximos_atual,
        "licoes_aprendidas": licoes,
        "analise_estrategica": analise,  # objeto textual estruturado
        "conclusao_executiva": reports["txt"],                 # compat A360 (TXT)
        "conclusao_executiva_markdown": reports["md"],         # extras
        "conclusao_executiva_html": reports["html"],           # extras
        "trace": trace,
    }
    return payload_out

# -------------------------------------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "version": app.version}

@app.post("/analisar-projeto-texto")
async def analisar_projeto_texto(payload: TextoRequest):
    campos = parse_from_text(payload.texto)
    return _analisar(campos)

@app.post("/analisar-projeto")
async def analisar_projeto(payload: ProjetoRequest):
    campos: Dict[str, Any] = {
        "nome_projeto": payload.nome_projeto or "Não informado",
        "cpi": payload.cpi or "Não informado",
        "spi": payload.spi or "Não informado",
        "avanco_fisico": payload.avanco_fisico or "Não informado",
        "avanco_financeiro": payload.avanco_financeiro or "Não informado",
        "tipo_contrato": payload.tipo_contrato or "Não informado",
        "stakeholders": payload.stakeholders or "Não informado",
        "observacoes": payload.observacoes or "Não informado",
        "pilar": payload.pilar or "Não informado",
        "objetivo": payload.objetivo or "Não informado",
        "resumo_status": payload.resumo_status or [],
        "planos_proximo_periodo": payload.planos_proximo_periodo or [],
        "pontos_atencao": payload.pontos_atencao or [],
        "indicadores": payload.indicadores or {},
        "data_final_planejada": payload.data_final_planejada or "Não informado",
        "baseline": payload.baseline or {},
        "escopo": payload.escopo or "Não informado",
        "cronograma": payload.cronograma or {"tarefas": []},
        "financeiro": payload.financeiro or {},
    }
    return _analisar(campos)
