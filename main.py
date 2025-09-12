# main.py - Vera Estratégica API v1.4.0
# Kaio / Projeto Vera
# - Mantém compat com v1.2/1.3 (A360 consome conclusao_executiva TXT)
# - Acrescenta campos opcionais: objetivo, resumo/planos/pontos, ISP/IDP/IDCo/IDB,
#   cronograma, data_final_planejada, baseline, escopo, financeiro
# - Strategy Fit (ECK) + divergência (declarado x sugerido) e 2 trilhas de próximos passos
# - Lições aprendidas (auto-sugeridas)
# - Riscos-chave ampliados
# - Stub de evidências externas (desligado por padrão)

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Tuple
import unicodedata
import html
import os
import re
from datetime import datetime, date

app = FastAPI(title="Vera Estratégica API", version="1.4.0")

# -----------------------------------------------------------------------------
# Feature flags e metas simples (edite aqui conforme necessidade)
# -----------------------------------------------------------------------------
FEATURES = {
    "enable_strategy_fit": True,
    "enable_lessons_learned": True,
    "enable_finance_pack": True,
    "enable_schedule_pack": True,
    # Habilita busca de evidências externas (stub) via var de ambiente:
    "enable_external_evidence": os.getenv("EXTERNAL_EVIDENCE_ENABLED", "false").lower() == "true",
}

TARGETS = {
    "cpi": 0.90,
    "spi": 0.95,
    "idx_meta": 1.00,  # ISP / IDP / IDCo / IDB (abaixo é pior; acima é melhor)
}

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
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
    resumo_status: Optional[List[str]] = None       # lista de bullets
    planos_proximo_periodo: Optional[List[str]] = None
    pontos_atencao: Optional[List[str]] = None
    indicadores: Optional[Dict[str, Any]] = None    # {"isp":..., "idp":..., "idco":..., "idb":...}
    data_final_planejada: Optional[str] = None      # "YYYY-MM-DD" ou "DD/MM/YYYY"
    baseline: Optional[Dict[str, Any]] = None       # {"prazo": {"data_planejada":...}, "custo":{"capex_aprovado":...}, "escopo":"..."}
    escopo: Optional[str] = None
    cronograma: Optional[Dict[str, Any]] = None     # {"tarefas":[{"nome":..., "inicio":..., "fim":..., "pct":..., "critica":True/False}, ...]}
    financeiro: Optional[Dict[str, Any]] = None     # {"capex_aprovado":..., "capex_comp":..., "capex_exec":..., "ev":..., "pv":..., "ac":..., "eac":..., "vac":...}

# -----------------------------------------------------------------------------
# Helpers de normalização e parsing
# -----------------------------------------------------------------------------
def normalize(s: Optional[str]) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.lower().strip()

def to_number(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    s = str(s).strip().replace(" ", "")
    s = s.replace("%", "")
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

# -----------------------------------------------------------------------------
# Parser do texto colado no A360 (rótulos + blocos)
# -----------------------------------------------------------------------------
def parse_from_text(texto: str) -> Dict[str, Any]:
    # Campos base com valores default
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
        "indicadores": {},  # isp/idp/idco/idb
        "data_final_planejada": "Não informado",
        "baseline": {},     # prazo/custo/escopo
        "escopo": "Não informado",
        "cronograma": {"tarefas": []},
        "financeiro": {},
    }

    lines = texto.splitlines()
    i = 0
    # Conjunto de rótulos conhecidos (normalizados)
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
            # se for um novo rótulo, parar
            has, _, _ = is_label(raw)
            if has:
                break
            if raw.startswith("- "):
                bullets.append(raw[2:].strip())
            else:
                # linha contínua: agrega ao último bullet (se houver)
                if bullets:
                    bullets[-1] = (bullets[-1] + " " + raw).strip()
                else:
                    bullets.append(raw)
            j += 1
        return bullets, j

    def parse_task_line(raw: str) -> Optional[Dict[str, Any]]:
        # Exemplo: "- Nome: Fundação | Início: 2025-08-01 | Fim: 2025-09-15 | %: 60 | Crítica: Sim"
        m = re.findall(r"(?i)(nome|inicio|início|fim|%|pct|critica|crítica)\s*:\s*([^|]+)")
        if not m:
            # tentativa por split simples:
            parts = [p.strip() for p in raw.split("|")]
            d: Dict[str, Any] = {}
            for p in parts:
                if ":" in p:
                    k, vv = p.split(":", 1)
                    d[normalize(k)] = vv.strip()
        else:
            d = {normalize(k): v.strip() for k, v in m}  # type: ignore
        if not d:
            # fallback: se a linha vier como "- Comissionamento 0% 2025-12-01 a 2025-12-10 Critica: Nao"
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

        # Rótulos com bloco de bullets subsequente
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
                # espera começar com "-" (bullet)
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
                    kn = normalize(k)
                    fin[kn] = v.strip()
                i += 1
            campos["financeiro"] = fin
            continue

        # Rótulos simples (uma linha)
        if nk == "nome do projeto":
            campos["nome_projeto"] = val or "Não informado"
        elif nk == "objetivo":
            campos["objetivo"] = val or "Não informado"
        elif nk in ("cpi", "spi", "isp", "idp", "idco", "idb"):
            # índices podem ficar em indicadores
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

# -----------------------------------------------------------------------------
# Heurísticas: risco, pilar, cronograma, baseline, financeiro
# -----------------------------------------------------------------------------
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
        # andamento baixo em tarefa crítica
        if pct is not None and pct < 30 and crit:
            score += 1; trace.append(f"Tarefa crítica <30%: {t.get('nome','')} (+1)")
    return score

def risco_por_baseline_financeiro(baseline: Dict[str, Any], fin: Dict[str, Any], trace: List[str]) -> float:
    score = 0.0
    # Prazo: comparar baseline prazo com data_final_planejada se existir
    prazo = baseline.get("prazo") or {}
    data_base = parse_date(prazo.get("data_planejada"))
    # (Pontuar aqui apenas se desejar; manteremos leve)
    # Financeiro: VAC < 0, EAC > BAC(capex aprovado)
    capex_aprovado = to_number((baseline.get("custo") or {}).get("capex_aprovado"))
    eac = to_number(fin.get("eac"))
    vac = to_number(fin.get("vac"))
    if vac is not None and vac < 0:
        score += 3; trace.append("VAC < 0 (projeção acima do aprovado): +3")
    if capex_aprovado is not None and eac is not None and eac > capex_aprovado:
        score += 2; trace.append("EAC > CAPEX aprovado: +2")
    comp = to_number(fin.get("capex_comp") or fin.get("capex comprometido"))
    if capex_aprovado is not None and comp is not None and comp > capex_aprovado:
        score += 2; trace.append("Comprometido > Aprovado: +2")
    return score

def classificar_risco(score: float) -> str:
    # Política Kaio: sem "Crítico" (consolida em "Alto")
    # Mantido v1.3.0: Alto ≥ 7 (ajustável aqui para ≥10, se desejar)
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

    score_exc = 0
    score_cli = 0
    score_cap = 0

    # Palavras-chave por pilar (base ECK)
    if any(k in texto_base for k in ["processo", "estrutura", "governanca", "governança", "rituais", "metas", "desdobramento", "coerencia", "coerência", "execucao", "execução"]):
        score_exc += 2
    if any(k in texto_base for k in ["cliente", "experiencia", "experiência", "sla", "jornada", "confiabilidade", "satisfacao", "satisfação", "atendimento"]):
        score_cli += 2
    if any(k in texto_base for k in ["capex", "investimento", "priorizacao", "priorização", "retorno", "vpl", "tir", "payback", "disciplina de capital"]):
        score_cap += 2

    # Métricas puxando para Excelência quando abaixo alvo
    if (cpi is not None and cpi < TARGETS["cpi"]) or (spi is not None and spi < TARGETS["spi"]):
        score_exc += 2; trace.append("ECK hint→Excelência (CPI/SPI abaixo do target)")
    # Índices <1,00 puxam Excelência (capaci/execução)
    for v in (isp, idp, idco, idb):
        if v is not None and v < TARGETS["idx_meta"]:
            score_exc += 1

    # Se CAPEX/retorno fortemente enfatizados, puxar Capital
    if any(k in texto_base for k in ["retorno", "vpl", "tir", "payback"]) or \
       to_number((campos.get("financeiro") or {}).get("capex_aprovado")):
        score_cap += 1

    # Escolha do pilar dominante sugerido
    trio = [("Excelência Organizacional", score_exc), ("Foco no Cliente", score_cli), ("Alocação Estratégica de Capital", score_cap)]
    trio.sort(key=lambda x: x[1], reverse=True)
    if trio[0][1] == 0:
        return None
    sugerido = trio[0][0]
    trace.append(f"ECK sugerido: {sugerido} (scores: E={score_exc}, C={score_cli}, K={score_cap})")
    return sugerido

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
                "com disciplina de capital e seleção criteriosa (VPL/TIR ajustadas a risco).")
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
    if cpi is not None and cpi < TARGETS["cpi"]:
        passos += ["Estabelecer plano de contenção de custos e variação de escopo (D+7).",
                   "Revisar curvas de medição e baseline financeiro (D+10)."]
    if spi is not None and spi < TARGETS["spi"]:
        passos += ["Replanejar caminho crítico e renegociar marcos críticos (D+5).",
                   "Avaliar compressão de cronograma/fast-track onde aplicável (D+10)."]
    if gap_pf is not None:
        if gap_pf >= 15: passos += ["Investigar assimetria físico x financeiro (≥15pp): auditoria de medição (D+7)."]
        elif gap_pf >= 8: passos += ["Alinhar critérios de medição físico x financeiro (≥8pp) (D+10)."]
    obs_n = normalize(obs)
    if "fornecedor" in obs_n:
        passos += ["Conduzir reunião executiva com fornecedor crítico e plano 5W2H (D+3)."]
    if "equip" in obs_n or "equipamento" in obs_n or "critico" in obs_n:
        passos += ["Ativar contingência p/ equipamentos críticos e alternativas logísticas (D+7)."]
    if "licenc" in obs_n or "embargo" in obs_n or "paralis" in obs_n:
        passos += ["Acionar frente regulatória/jurídica para destravar licenças/embargos (D+3)."]
    p = normalize(pilar_final)
    if "excelencia" in p:
        passos += ["Desdobrar metas operacionais e RACI de governança semanal (D+7).",
                   "Implantar rituais de performance e indicadores leading/lagging (D+14)."]
    if "cliente" in p:
        passos += ["Mapear jornada do cliente e ajustar SLAs de comunicação (D+15).",
                   "Rodar pulso de satisfação/NPS até o próximo marco (D+30)."]
    if "alocacao" in p:
        passos += ["Repriorizar CAPEX priorizando retorno ajustado a risco (D+20).",
                   "Revisar business case e opções de escopo/financiamento (D+30)."]
    owners = split_stakeholders(stakeholders)
    if owners: passos += [f"Responsáveis sugeridos: {', '.join(owners[:3])}."]
    # dedup
    dedup: List[str] = []
    seen = set()
    for it in passos:
        if it not in seen:
            seen.add(it); dedup.append(it)
    return dedup

def listar_riscos(campos_num: Dict[str, Optional[float]],
                  observacoes: str,
                  indicadores: Dict[str, Optional[float]],
                  tarefas: List[Dict[str, Any]],
                  baseline: Dict[str, Any],
                  fin: Dict[str, Any]) -> List[str]:
    riscos: List[str] = []
    cpi = campos_num.get("cpi_num")
    spi = campos_num.get("spi_num")
    fis = campos_num.get("avanco_fisico_num")
    finv = campos_num.get("avanco_financeiro_num")
    if cpi is not None:
        if cpi < 0.85: riscos.append("Custo: CPI < 0,85 — forte risco orçamentário.")
        elif cpi < TARGETS["cpi"]: riscos.append("Custo: CPI entre 0,85 e 0,90 — pressão de custos.")
    if spi is not None:
        if spi < 0.90: riscos.append("Prazo: SPI < 0,90 — alto risco de atraso.")
        elif spi < TARGETS["spi"]: riscos.append("Prazo: SPI entre 0,90 e 0,95 — risco de deslizamento.")
    if fis is not None and finv is not None:
        gap = abs(fis - finv)
        if gap >= 15: riscos.append("Execução: gap físico x financeiro ≥15pp — risco de inconsistência de medição.")
        elif gap >= 8: riscos.append("Execução: gap físico x financeiro ≥8pp — atenção à coerência de medição.")
    # Índices meta 1,00
    for k in ("isp", "idp", "idco", "idb"):
        v = indicadores.get(k)
        if v is not None and v < TARGETS["idx_meta"]:
            riscos.append(f"Índice {k.upper()} abaixo de 1,00 ({v:.2f}).")
    # Cronograma
    hoje = date.today()
    for t in tarefas:
        nome = t.get("nome", "")
        fim = t.get("fim")
        pct = t.get("pct")
        crit = t.get("critica", False)
        atrasado = (isinstance(fim, date) and fim < hoje and (pct is None or pct < 100))
        if atrasado and crit:
            riscos.append(f"Cronograma: tarefa crítica atrasada — {nome}.")
        elif atrasado:
            riscos.append(f"Cronograma: tarefa atrasada — {nome}.")
    # Financeiro
    vac = to_number(fin.get("vac"))
    capex_aprovado = to_number((baseline.get("custo") or {}).get("capex_aprovado"))
    eac = to_number(fin.get("eac"))
    comp = to_number(fin.get("capex_comp") or fin.get("capex comprometido"))
    if vac is not None and vac < 0:
        riscos.append("Financeiro: VAC negativo — projeção acima do aprovado.")
    if capex_aprovado is not None and eac is not None and eac > capex_aprovado:
        riscos.append("Financeiro: EAC acima do CAPEX aprovado.")
    if capex_aprovado is not None and comp is not None and comp > capex_aprovado:
        riscos.append("Financeiro: comprometido acima do aprovado.")
    # Observações (keywords)
    obs = normalize(observacoes)
    mapping = [
        ("licenc", "Regulatório: risco de licenças/autorizações."),
        ("embargo", "Regulatório: risco de embargo/interdição."),
        ("paralis", "Operação: risco de paralisação de frentes."),
        ("fornecedor", "Suprimentos: dependência de fornecedor crítico."),
        ("pressao", "Financeiro: pressão de custos em pacotes."),
        ("equip", "Técnico: fornecimento de equipamentos sensível."),
        ("critico", "Risco crítico citado em observações."),
        ("risco", "Risco adicional citado em observações.")
    ]
    for key, msg in mapping:
        if key in obs and msg not in riscos:
            riscos.append(msg)
    # dedup
    out: List[str] = []
    seen = set()
    for r in riscos:
        if r not in seen:
            seen.add(r); out.append(r)
    return out
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

    # Scores por pilar
    score_exc = 0
    score_cli = 0
    score_cap = 0

    # Marcadores (simples e calibráveis)
    if any(k in texto for k in ["processo", "estrutura", "governanca", "rituais", "metas", "desdobramento", "coerencia", "execucao"]):
        score_exc += 20
    if any(k in texto for k in ["cliente", "experiencia", "sla", "jornada", "confiabilidade", "satisfacao", "atendimento"]):
        score_cli += 20
    if any(k in texto for k in ["capex", "investimento", "priorizacao", "retorno", "vpl", "tir", "payback"]):
        score_cap += 20
    # Métricas (puxam Excelência quando abaixo)
    cpi, spi = campos_num.get("cpi_num"), campos_num.get("spi_num")
    for (v, alvo) in [(cpi, TARGETS["cpi"]), (spi, TARGETS["spi"])]:
        if v is not None and v < alvo:
            score_exc += 10
    for v in (indicadores.get("isp"), indicadores.get("idp"), indicadores.get("idco"), indicadores.get("idb")):
        if v is not None and v < TARGETS["idx_meta"]:
            score_exc += 5

    # Normalização ingênua para 0-100
    raw_sum = score_exc + score_cli + score_cap
    if raw_sum == 0:
        return {"score": 0, "pilar_sugerido": None, "justificativa": "Sem sinais suficientes."}
    # escolher dominante
    trio = [("Excelência Organizacional", score_exc), ("Foco no Cliente", score_cli), ("Alocação Estratégica de Capital", score_cap)]
    trio.sort(key=lambda x: x[1], reverse=True)
    pilar_sugerido, top = trio[0]
    score = int(min(100, max(0, (top / max(1, raw_sum)) * 100)))
    justificativa = justificativa_pilar_eck(pilar_sugerido)
    return {"score": score, "pilar_sugerido": pilar_sugerido, "justificativa": justificativa}

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

    # Padrões básicos
    cpi = campos_num.get("cpi_num"); spi = campos_num.get("spi_num")
    if cpi is not None and cpi < TARGETS["cpi"]:
        itens.append({
            "problema": "Desvio de custo (CPI abaixo da meta).",
            "causa_raiz": "Estimativas subavaliadas e controle de mudanças sem gate claro.",
            "contramedida": "Instalar Change Control Board e reforçar baseline; auditoria de medição financeira.",
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
    # Tarefa crítica atrasada
    hoje = date.today()
    for t in tarefas:
        if t.get("critica") and isinstance(t.get("fim"), date) and t["fim"] < hoje and (t.get("pct") or 0) < 100:
            itens.append({
                "problema": f"Tarefa crítica atrasada: {t.get('nome','')}.",
                "causa_raiz": "Sequenciamento de frentes e restrições não modeladas.",
                "contramedida": "Aplicar técnica de remoção de restrições (LPS) e travas de pré-requisitos.",
                "owner": owner, "prazo": "D+5", "categoria": "Planejamento/Execução"
            })
            break

    # Adiciona no máximo 5
    return itens[:5]

# -----------------------------------------------------------------------------
# Formatação (TXT/MD/HTML) - mantém estrutura aprovada e acrescenta novas seções
# -----------------------------------------------------------------------------
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
                  licoes: List[Dict[str, str]]) -> Dict[str, str]:

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

    # ---------- Texto (para A360) ----------
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

    # Resumo/Planos/Pontos (no formato que você utiliza)
    if resumo_status:
        txt += ["", "📝 RESUMO DA SITUAÇÃO ATUAL (PROGRESSO) E AÇÕES CORRETIVAS REALIZADAS"]
        txt += [f"- {b}" for b in resumo_status]
    if planos:
        txt += ["", "📅 PLANOS PARA O PRÓXIMO PERÍODO"]
        txt += [f"- {b}" for b in planos]
    if pontos:
        txt += ["", "🔎 PONTOS DE ATENÇÃO"]
        txt += [f"- {b}" for b in pontos]

    # KPIs
    txt += ["", "📈 Diagnóstico de Performance"]
    txt += [
        f"- Custo: CPI em {cpi} → disciplina orçamentária.",
        f"- Prazo: SPI em {spi} → gestão de caminho crítico.",
        f"- Execução: físico ({fisico}) vs. financeiro ({financeiro_pf}).",
        f"- Contrato: “{contrato}” → reforçar governança de escopo/custos.",
    ]
    if kpis.get("gap_pf") is not None:
        txt.append(f"- Gap físico x financeiro: {kpis['gap_pf']:.1f}pp.")
    # Índices meta 1,00
    if any(x is not None for x in (isp, idp, idco, idb)):
        txt += ["- Indicadores de desempenho (meta = 1,00):"]
        if isp is not None: txt.append(f"  • ISP: {isp}")
        if idp is not None: txt.append(f"  • IDP: {idp}")
        if idco is not None: txt.append(f"  • IDCo: {idco}")
        if idb is not None: txt.append(f"  • IDB: {idb}")

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
        if evpvac:
            txt.append("- " + ", ".join(evpvac))

    # Riscos-chave
    if riscos_chave:
        txt += ["", "⚠️ Riscos‑chave identificados"]
        txt += [f"- {r}" for r in riscos_chave]

    # Projeção e Recomendações gerais
    txt += [
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
        txt.append(f"- Pilar declarado: {pilar_declarado}")
    if divergente and pilar_sugerido:
        txt.append(f"- Pilar sugerido (análise): {pilar_sugerido} ⚠️ (recomendado realinhar)")
        if justificativa_sugerido: txt.append(f"- Justificativa (sugerido): {justificativa_sugerido}")
        txt.append(f"- Justificativa (atual): {justificativa_eck_txt}")
    else:
        show_txt = pilar_declarado if pilar_declarado != "Não informado" else pilar_final
        txt.append(f"- Pilar: {show_txt}")
        txt.append(f"- Justificativa: {justificativa_eck_txt}")

    # Strategy fit
    if FEATURES["enable_strategy_fit"] and strategy.get("score") is not None:
        txt += ["", "📐 Strategy Fit (ECK)", f"- Score (0-100): {strategy.get('score')}"]
        if strategy.get("pilar_sugerido"):
            txt.append(f"- Pilar dominante sugerido: {strategy['pilar_sugerido']}")

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
                f"  • Causa-raiz: {it['causa_raiz']}",
                f"  • Contramedida: {it['contramedida']}",
                f"  • Owner: {it['owner']}   • Prazo: {it['prazo']}   • Categoria: {it['categoria']}",
            ]

    # Resumo executivo
    txt += ["", "✅ Resumo Executivo"]
    resumo_pilar_txt = (pilar_sugerido or pilar_final) if (divergente and pilar_sugerido) else (pilar_declarado if pilar_declarado != "Não informado" else pilar_final)
    txt.append(
        f"O projeto “{nome}” requer atenção {risco.lower()} {({'Alto':'🔴','Médio':'🟠','Baixo':'🟢'}.get(risco,'⚠️'))}. "
        f"Considerar foco no pilar {resumo_pilar_txt} e disciplina de execução para assegurar valor e entrega."
    )
    txt_report = "\n".join(txt)

    # Mantemos MD/HTML simples (mesmo texto)
    md_report = txt_report
    html_report = html.escape(txt_report).replace("\n", "<br/>")

    return {"txt": txt_report.strip(), "md": md_report.strip(), "html": html_report}

# -----------------------------------------------------------------------------
# Helpers de evidências externas (stub)
# -----------------------------------------------------------------------------
def buscar_evidencias_externas(topicos: List[str]) -> List[str]:
    # Stub não faz chamadas externas por padrão (feature flag controla)
    if not FEATURES["enable_external_evidence"]:
        return []
    # Aqui poderia haver uma busca via urllib/requests/httpx com allowlist
    # Retornaríamos bullets como "Caso semelhante: ... (link)"
    return []

# -----------------------------------------------------------------------------
# Core: _analisar
# -----------------------------------------------------------------------------
def _analisar(campos: Dict[str, Any]) -> Dict[str, Any]:
    trace: List[str] = []

    # Números normalizados base
    campos_num = {
        "cpi_num": to_number(campos.get("cpi")),
        "spi_num": to_number(campos.get("spi")),
        "avanco_fisico_num": percent_to_number(campos.get("avanco_fisico")),
        "avanco_financeiro_num": percent_to_number(campos.get("avanco_financeiro")),
    }

    # Indicadores meta 1,00
    ind_raw = campos.get("indicadores") or {}
    indicadores = {
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

    # Baseline e financeiro
    baseline = campos.get("baseline") or {}
    fin_raw = campos.get("financeiro") or {}
    # Normalizar chaves de financeiro
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

    # Pilar final (mantém política: se declararam, prevalece; senão usa inferido)
    pilar_final = pilar_declarado if (pilar_declarado and pilar_declarado != "Não informado") else (pilar_inferido or "Não informado")

    if divergente:
        trace.append(f"Divergência Pilar: declarado='{pilar_declarado}' vs sugerido='{pilar_inferido}'")

    # Score de risco total
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
    proximos_recomendado = gerar_proximos_passos(
        cpi=campos_num["cpi_num"], spi=campos_num["spi_num"], gap_pf=gap_pf,
        obs=campos.get("observacoes", ""), pilar_final=pilar_para_recomendado,
        stakeholders=campos.get("stakeholders", "Não informado"),
    )
    proximos_atual = gerar_proximos_passos(
        cpi=campos_num["cpi_num"], spi=campos_num["spi_num"], gap_pf=gap_pf,
        obs=campos.get("observacoes", ""), pilar_final=pilar_declarado if pilar_declarado else "Não informado",
        stakeholders=campos.get("stakeholders", "Não informado"),
    )

    # Riscos-chave
    riscos_chave = listar_riscos(campos_num, campos.get("observacoes", ""), indicadores, tarefas, baseline, fin)

    # Strategy fit
    strategy = strategy_fit(campos, campos_num, indicadores)

    # Lições aprendidas
    licoes = gerar_licoes_aprendidas(campos, campos_num, kpis, tarefas, riscos_chave)

    # Justificativas
    justificativa_final = justificativa_pilar_eck(pilar_final)
    justificativa_sugerido = justificativa_pilar_eck(pilar_inferido) if pilar_inferido else None

    # Relatórios
    reports = format_report(
        campos=campos, campos_num=campos_num, score=score, risco=classificacao,
        pilar_declarado=pilar_declarado, pilar_final=pilar_final,
        justificativa_eck_txt=justificativa_final,
        proximos_passos_recomendado=proximos_recomendado,
        proximos_passos_atual=proximos_atual,
        kpis=kpis, riscos_chave=riscos_chave,
        divergente=divergente, pilar_sugerido=pilar_inferido,
        justificativa_sugerido=justificativa_sugerido,
        strategy=strategy, licoes=licoes
    )

    payload_out = {
        "versao_api": "1.4.0",
        "campos_interpretados": {**campos, **campos_num, "pilar_final": pilar_final},
        "indicadores": indicadores,
        "kpis": kpis,
        "score_risco": score,
        "classificacao_risco": classificacao,
        "riscos_chave": riscos_chave,
        "strategy_fit": strategy,
        "pilar_declarado": pilar_declarado,
        "pilar_sugerido": pilar_inferido,
        "pilar_divergente": divergente,
        "proximos_passos_recomendado": proximos_recomendado,
        "proximos_passos_atual": proximos_atual,
        "licoes_aprendidas": licoes,
        "conclusao_executiva": reports["txt"],                 # compat A360 (TXT)
        "conclusao_executiva_markdown": reports["md"],         # extras
        "conclusao_executiva_html": reports["html"],           # extras
    }
    return payload_out

# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "version": app.version}

@app.post("/analisar-projeto-texto")
async def analisar_projeto_texto(payload: TextoRequest):
    campos = parse_from_text(payload.texto)
    return _analisar(campos)

@app.post("/analisar-projeto")
async def analisar_projeto(payload: ProjetoRequest):
    # Monta o dicionário a partir do JSON estruturado (mantendo defaults)
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
