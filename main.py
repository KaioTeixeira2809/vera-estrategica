# main.py - Vera Estratégica API v1.5.1 (Lean + Alinhamento Estratégico ECK + Hotfix)
# Kaio / Projeto Verinha
# - Compatível com A360 (consome conclusao_executiva TXT)
# - Mantém endpoints: /health, /analisar-projeto-texto, /analisar-projeto
# - Regra Kaio: sem "Crítico"; Alto >= RISK_HIGH_THRESHOLD (default=10)
# - Nova camada: alinhamento estratégico (temas + decisão recomendada)
# - Modo LEAN de relatório (enxuto, com limites de bullets configuráveis)
# - Hotfix: conversão de indicadores e EAC/VAC para float dentro de format_report

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Tuple
import unicodedata
import html as _html
import os
import re
import uuid
import json
from datetime import datetime, date

app = FastAPI(title="Vera Estratégica API", version="1.5.1")

# ------------------------------
# Feature flags e metas simples
# ------------------------------
FEATURES = {
    "enable_strategy_fit": True,          # legado
    "enable_lessons_learned": True,
    "enable_finance_pack": True,
    "enable_schedule_pack": True,
    "enable_external_evidence": os.getenv("EXTERNAL_EVIDENCE_ENABLED", "false").lower() == "true",
}
TARGETS = {"cpi": 0.90, "spi": 0.95, "idx_meta": 1.00}
RISK_HIGH_THRESHOLD = float(os.getenv("RISK_HIGH_THRESHOLD", "10"))  # Regra Kaio
REPORT_MODE = os.getenv("REPORT_MODE", "lean").lower()                # 'lean' | 'full'
MAX_BULLETS_RISCOS = int(os.getenv("MAX_BULLETS_RISCOS", "4"))
MAX_BULLETS_ACOES  = int(os.getenv("MAX_BULLETS_ACOES",  "5"))

# CORS básico (ajuste allow_origins conforme necessário)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------
# Strategy config (default) — pode ser sobrescrito via STRATEGY_CONFIG_JSON (ENV)
# ------------------------------
_STRATEGY_DEFAULT = {
  "temas": {
    "Eficiência Operacional": {
      "peso": 3,
      "keywords": ["produtividade", "processo", "governança", "rituais", "evm", "padronização", "padronizacao"],
      "indicadores": {"CPI<0.90": 2, "SPI<0.95": 2, "gap_pf>=8": 1},
      "como_alinhar": [
        "Ritos EVM semanais com plano D+7 por desvio",
        "Replanejar caminho crítico e proteger buffer",
        "Padronizar medição físico x financeiro (auditoria)"
      ]
    },
    "Disciplina de Capital": {
      "peso": 3,
      "keywords": ["capex", "roi", "vpl", "tir", "payback", "alocação de capital", "alocacao de capital"],
      "indicadores": {"VAC<0": 2, "EAC>CAPEX_aprovado": 2},
      "como_alinhar": [
        "Revisar business case e opções de escopo",
        "Instalar Change Control Board (gates)",
        "Repriorizar investimentos por retorno ajustado a risco"
      ]
    },
    "Cliente & Qualidade de Serviço": {
      "peso": 2,
      "keywords": ["cliente", "sla", "jornada", "confiabilidade", "satisfação", "satisfacao", "nps"],
      "indicadores": {},
      "como_alinhar": [
        "Ajustar SLAs por segmento",
        "Mapear jornada e pontos de atrito",
        "Comitê de interface com stakeholders externos"
      ]
    },
    "ESG & Licenciamento": {
      "peso": 2,
      "keywords": ["licença", "licenca", "ambiental", "ibama", "comunidades", "emissões", "emissoes"],
      "indicadores": {},
      "como_alinhar": [
        "Squad regulatório com calendário conjunto",
        "Plano de relacionamento comunitário",
        "Monitoramento de condicionantes e indicadores ESG"
      ]
    },
    "Digital & Automação": {
      "peso": 1,
      "keywords": ["automação", "automacao", "digital", "dados", "ia", "a360"],
      "indicadores": {},
      "como_alinhar": [
        "Automatizar rotinas operacionais",
        "Implantar métricas data-driven",
        "Integração de sistemas críticos"
      ]
    }
  },
  "limiares": {"score_alto": 70, "score_medio": 40}
}

def load_strategy_config() -> Dict[str, Any]:
    js = os.getenv("STRATEGY_CONFIG_JSON")
    if js:
        try:
            return json.loads(js)
        except Exception:
            pass
    return _STRATEGY_DEFAULT

# ------------------------------
# Models
# ------------------------------
class TextoRequest(BaseModel):
    texto: str

class ProjetoRequest(BaseModel):
    # Campos pré-existentes
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
    resumo_status: Optional[List[str]] = None
    planos_proximo_periodo: Optional[List[str]] = None
    pontos_atencao: Optional[List[str]] = None
    indicadores: Optional[Dict[str, Any]] = None
    data_final_planejada: Optional[str] = None
    baseline: Optional[Dict[str, Any]] = None
    escopo: Optional[str] = None
    cronograma: Optional[Dict[str, Any]] = None
    financeiro: Optional[Dict[str, Any]] = None

# ------------------------------
# Helpers de normalização e parsing
# ------------------------------
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

# ------------------------------
# Parser do texto colado no A360 (rótulos + blocos)
# ------------------------------
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
        txt = raw.strip().lstrip("-").strip()
        tokens = [t.strip() for t in re.split(r";+", txt) if t.strip()]
        d: Dict[str, Any] = {}
        for t in tokens:
            if ":" in t:
                k, v = t.split(":", 1)
                d[normalize(k)] = v.strip()
            else:
                parts = t.split()
                if len(parts) >= 2:
                    d[normalize(parts[0])] = " ".join(parts[1:])
                else:
                    d.setdefault("nome", t)
        if not d:
            return None
        nome = d.get("nome") or txt
        ini = parse_date(d.get("inicio") or d.get("início"))
        fim = parse_date(d.get("fim"))
        pct = to_number(d.get("%") or d.get("pct") or d.get("progresso"))
        crit_val = normalize(d.get("critica") or d.get("crítica") or "")
        crit = crit_val in ("sim", "true", "critica", "crítica", "yes")
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
                    t = parse_task_line(raw)
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
        # Rótulos simples
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

# ------------------------------
# Heurísticas: risco, pilar, cronograma, baseline, financeiro
# ------------------------------
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
        if gap >= 15: score += 2; trace.append("Gap F×F ≥15pp: +2")
        elif gap >= 8: score += 1; trace.append("Gap F×F ≥8pp: +1")
    # Keywords
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
    if score >= RISK_HIGH_THRESHOLD:
        return "Alto"
    elif score >= 4:
        return "Médio"
    else:
        return "Baixo"

def inferir_pilar(campos: Dict[str, Any], campos_num: Dict[str, Optional[float]], indicadores: Dict[str, Optional[float]], trace: List[str]) -> Optional[str]:
    obs = normalize(campos.get("observacoes", ""))
    objetivo = normalize(campos.get("objetivo", ""))
    escopo = normalize(campos.get("escopo", ""))
    resumo_join = " ".join([normalize(x) for x in (campos.get("resumo_status") or [])])
    planos_join = " ".join([normalize(x) for x in (campos.get("planos_proximo_periodo") or [])])
    texto_base = " ".join([obs, objetivo, escopo, resumo_join, planos_join])
    cpi = campos_num.get("cpi_num"); spi = campos_num.get("spi_num")
    isp, idp, idco, idb = (indicadores.get("isp"), indicadores.get("idp"), indicadores.get("idco"), indicadores.get("idb"))
    score_exc = score_cli = score_cap = 0
    if any(k in texto_base for k in ["processo", "estrutura", "governanca", "governança", "rituais", "metas", "desdobramento", "coerencia", "coerência", "execucao", "execução"]):
        score_exc += 2
    if any(k in texto_base for k in ["cliente", "experiencia", "experiência", "sla", "jornada", "confiabilidade", "satisfacao", "satisfação", "atendimento"]):
        score_cli += 2
    if any(k in texto_base for k in ["capex", "investimento", "priorizacao", "priorização", "retorno", "vpl", "tir", "payback", "disciplina de capital"]):
        score_cap += 2
    if (cpi is not None and cpi < TARGETS["cpi"]) or (spi is not None and spi < TARGETS["spi"]):
        score_exc += 2; trace.append("ECK hint→Excelência (CPI/SPI abaixo do target)")
    for v in (isp, idp, idco, idb):
        if v is not None and v < TARGETS["idx_meta"]:
            score_exc += 1
    if any(k in texto_base for k in ["retorno", "vpl", "tir", "payback"]) or to_number((campos.get("financeiro") or {}).get("capex_aprovado")):
        score_cap += 1
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
        return ("Excelência Organizacional: alinhar pessoas, processos, estrutura e incentivos; "
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
    for sep in [";", ",", "\n", "\r\n"]:
        if sep in stakeholders:
            parts = [p.strip() for p in stakeholders.split(sep)]
            break
    if not parts:
        parts = [stakeholders.strip()]
    return [p for p in parts if p]

def gerar_proximos_passos(cpi: Optional[float], spi: Optional[float], gap_pf: Optional[float], obs: str, pilar_final: str, stakeholders: str) -> List[str]:
    passos: List[str] = []
    if cpi is not None and cpi < TARGETS["cpi"]:
        passos += [
            "Plano de contenção de custos e variação de escopo (D+7)",
            "Revisar curvas de medição e baseline financeiro (D+10)",
        ]
    if spi is not None and spi < TARGETS["spi"]:
        passos += [
            "Replanejar caminho crítico e renegociar marcos (D+5)",
            "Avaliar compressão de cronograma/fast-track (D+10)",
        ]
    if gap_pf is not None:
        if gap_pf >= 15: passos += ["Investigar assimetria F×F ≥15pp: auditoria de medição (D+7)"]
        elif gap_pf >= 8: passos += ["Alinhar critérios de medição F×F ≥8pp (D+10)"]
    obs_n = normalize(obs)
    if "fornecedor" in obs_n:
        passos += ["Reunião executiva com fornecedor crítico e plano 5W2H (D+3)"]
    if "equip" in obs_n or "equipamento" in obs_n or "critico" in obs_n:
        passos += ["Contingência para equipamentos críticos e alternativas logísticas (D+7)"]
    if "licenc" in obs_n or "embargo" in obs_n or "paralis" in obs_n:
        passos += ["Frente regulatória/jurídica para destravar licenças/embargos (D+3)"]
    p = normalize(pilar_final)
    if "excelencia" in p:
        passos += ["RACI de governança semanal (D+7)", "Rituais de performance (leading/lagging) (D+14)"]
    if "cliente" in p:
        passos += ["Mapear jornada do cliente e ajustar SLAs (D+15)", "Rodar pulso de satisfação/NPS (D+30)"]
    if "alocacao" in p:
        passos += ["Repriorizar CAPEX por retorno ajustado a risco (D+20)", "Revisar business case e funding (D+30)"]
    owners = split_stakeholders(stakeholders)
    if owners: passos += [f"Responsáveis sugeridos: {', '.join(owners[:3])}."]
    dedup: List[str] = []
    seen = set()
    for it in passos:
        if it not in seen:
            seen.add(it); dedup.append(it)
    return dedup

def listar_riscos(campos_num: Dict[str, Optional[float]], observacoes: str, indicadores: Dict[str, Optional[float]], tarefas: List[Dict[str, Any]], baseline: Dict[str, Any], fin: Dict[str, Any]) -> List[str]:
    riscos: List[str] = []
    cpi = campos_num.get("cpi_num"); spi = campos_num.get("spi_num")
    fis = campos_num.get("avanco_fisico_num"); finv = campos_num.get("avanco_financeiro_num")
    if cpi is not None:
        if cpi < 0.85: riscos.append("Custo: CPI < 0,85 — forte risco orçamentário.")
        elif cpi < TARGETS["cpi"]: riscos.append("Custo: CPI entre 0,85 e 0,90 — pressão de custos.")
    if spi is not None:
        if spi < 0.90: riscos.append("Prazo: SPI < 0,90 — alto risco de atraso.")
        elif spi < TARGETS["spi"]: riscos.append("Prazo: SPI entre 0,90 e 0,95 — risco de deslizamento.")
    if fis is not None and finv is not None:
        gap = abs(fis - finv)
        if gap >= 15: riscos.append("Execução: gap físico x financeiro ≥15pp — inconsistência de medição.")
        elif gap >= 8: riscos.append("Execução: gap físico x financeiro ≥8pp — atenção à coerência de medição.")
    for k in ("isp", "idp", "idco", "idb"):
        v = indicadores.get(k)
        if v is not None and v < TARGETS["idx_meta"]:
            riscos.append(f"Índice {k.upper()} abaixo de 1,00 ({v:.2f}).")
    hoje = date.today()
    for t in tarefas:
        nome = t.get("nome", "")
        fim = t.get("fim"); pct = t.get("pct"); crit = t.get("critica", False)
        atrasado = (isinstance(fim, date) and fim < hoje and (pct is None or pct < 100))
        if atrasado and crit:
            riscos.append(f"Cronograma: tarefa crítica atrasada — {nome}.")
        elif atrasado:
            riscos.append(f"Cronograma: tarefa atrasada — {nome}.")
    vac = to_number(fin.get("vac"))
    capex_aprovado = to_number((baseline.get("custo") or {}).get("capex_aprovado"))
    eac = to_number(fin.get("eac"))
    comp = to_number(fin.get("capex_comp") or fin.get("capex comprometido"))
    if vac is not None and vac < 0: riscos.append("Financeiro: VAC negativo — projeção acima do aprovado.")
    if capex_aprovado is not None and eac is not None and eac > capex_aprovado: riscos.append("Financeiro: EAC acima do CAPEX aprovado.")
    if capex_aprovado is not None and comp is not None and comp > capex_aprovado: riscos.append("Financeiro: comprometido acima do aprovado.")
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
    out: List[str] = []
    seen = set()
    for r in riscos:
        if r not in seen:
            seen.add(r); out.append(r)
    return out
# --- Strategy fit legado (mantido)
def strategy_fit(campos: Dict[str, Any], campos_num: Dict[str, Optional[float]], indicadores: Dict[str, Optional[float]]) -> Dict[str, Any]:
    if not FEATURES["enable_strategy_fit"]:
        return {"score": None, "pilar_sugerido": None, "justificativa": None}
    objetivo = normalize(campos.get("objetivo", ""))
    resumo_join = " ".join([normalize(x) for x in (campos.get("resumo_status") or [])])
    escopo = normalize(campos.get("escopo", ""))
    obs = normalize(campos.get("observacoes", ""))
    planos_join = " ".join([normalize(x) for x in (campos.get("planos_proximo_periodo") or [])])
    texto = " ".join([objetivo, resumo_join, escopo, obs, planos_join])
    score_exc = score_cli = score_cap = 0
    if any(k in texto for k in ["processo", "estrutura", "governanca", "rituais", "metas", "desdobramento", "coerencia", "execucao"]): score_exc += 20
    if any(k in texto for k in ["cliente", "experiencia", "sla", "jornada", "confiabilidade", "satisfacao", "atendimento"]): score_cli += 20
    if any(k in texto for k in ["capex", "investimento", "priorizacao", "retorno", "vpl", "tir", "payback"]): score_cap += 20
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
    justificativa = justificativa_pilar_eck(pilar_sugerido)
    return {"score": score, "pilar_sugerido": pilar_sugerido, "justificativa": justificativa}

# --- Nova: alinhamento estratégico corporativo
def avaliar_alinhamento_estrategico(campos: Dict[str, Any], campos_num: Dict[str, Optional[float]], indicadores: Dict[str, Optional[float]], pilar_sugerido: Optional[str]) -> Dict[str, Any]:
    cfg = load_strategy_config()
    temas = cfg.get("temas", {})
    lim = cfg.get("limiares", {"score_alto": 70, "score_medio": 40})
    textos = [campos.get("objetivo",""), " ".join(campos.get("resumo_status") or []), " ".join(campos.get("planos_proximo_periodo") or []), campos.get("escopo",""), campos.get("observacoes","")]
    base = normalize(" ".join(t for t in textos if t))
    cpi, spi = campos_num.get("cpi_num"), campos_num.get("spi_num")
    vac = to_number((campos.get("financeiro") or {}).get("vac"))
    capex_apr = to_number(((campos.get("baseline") or {}).get("custo") or {}).get("capex_aprovado"))
    eac = to_number((campos.get("financeiro") or {}).get("eac"))
    gap_pf = None
    if campos_num.get("avanco_fisico_num") is not None and campos_num.get("avanco_financeiro_num") is not None:
        gap_pf = abs(campos_num["avanco_fisico_num"] - campos_num["avanco_financeiro_num"])

    tema_scores: Dict[str, float] = {}
    for nome, meta in temas.items():
        peso = float(meta.get("peso", 1))
        sc = 0.0
        for kw in meta.get("keywords", []):
            if normalize(kw) in base:
                sc += 1
        for rule, pts in (meta.get("indicadores") or {}).items():
            try:
                if rule == "CPI<0.90" and cpi is not None and cpi < 0.90: sc += pts
                if rule == "SPI<0.95" and spi is not None and spi < 0.95: sc += pts
                if rule == "gap_pf>=8" and gap_pf is not None and gap_pf >= 8: sc += pts
                if rule == "VAC<0" and vac is not None and vac < 0: sc += pts
                if rule == "EAC>CAPEX_aprovado" and (eac is not None and capex_apr is not None and eac > capex_apr): sc += pts
            except Exception:
                pass
        tema_scores[nome] = sc * peso

    total = sum(tema_scores.values()) or 1.0
    tema_dominante, dom_val = (None, 0.0)
    if tema_scores:
        tema_dominante, dom_val = max(tema_scores.items(), key=lambda x: x[1])
    score = int(min(100, max(0, (dom_val / total) * 100)))
    if score >= lim["score_alto"]: nivel = "ALTO"
    elif score >= lim["score_medio"]: nivel = "MÉDIO"
    else: nivel = "BAIXO"

    coerencia = None
    if pilar_sugerido and tema_dominante:
        mapa = {
            "Excelência Organizacional": "Eficiência Operacional",
            "Alocação Estratégica de Capital": "Disciplina de Capital",
            "Foco no Cliente": "Cliente & Qualidade de Serviço",
        }
        coerencia = "Coerente" if mapa.get(pilar_sugerido) == tema_dominante else "Em tensão"

    racional: List[str] = []
    for nome, val in sorted(tema_scores.items(), key=lambda x: x[1], reverse=True)[:3]:
        racional.append(f"Tema {nome}: contribuição relativa {int((val/total)*100)}%.")

    acoes = (temas.get(tema_dominante, {}).get("como_alinhar") or [])[:3] if tema_dominante else []

    return {
        "score": score,
        "nivel": nivel,
        "tema_dominante": tema_dominante,
        "coerencia_eck": coerencia,
        "racional": racional,
        "acoes_estrategicas": acoes
    }

# --- Lições aprendidas (mantém, com cortes no LEAN)
def gerar_licoes_aprendidas(campos: Dict[str, Any], campos_num: Dict[str, Optional[float]], kpis: Dict[str, Any], tarefas: List[Dict[str, Any]], riscos_chave: List[str]) -> List[Dict[str, str]]:
    if not FEATURES["enable_lessons_learned"]:
        return []
    itens: List[Dict[str, str]] = []
    owners = split_stakeholders(campos.get("stakeholders", ""))
    owner = owners[0] if owners else "PMO/Projeto"
    cpi = campos_num.get("cpi_num"); spi = campos_num.get("spi_num")
    if cpi is not None and cpi < TARGETS["cpi"]:
        itens.append({
            "problema": "Desvio de custo (CPI abaixo da meta).",
            "causa_raiz": "Estimativas subavaliadas / change sem gate claro.",
            "contramedida": "Change Control Board + reforço de baseline; auditoria financeira.",
            "owner": owner, "prazo": "D+14", "categoria": "Financeiro/Controle"
        })
    if spi is not None and spi < TARGETS["spi"]:
        itens.append({
            "problema": "Risco de atraso (SPI abaixo da meta).",
            "causa_raiz": "Caminho crítico sem replanejamento tempestivo.",
            "contramedida": "Replanejar caminho crítico; rito semanal com EVM.",
            "owner": owner, "prazo": "D+7", "categoria": "Prazo/Planejamento"
        })
    gap_pf = kpis.get("gap_pf")
    if gap_pf is not None and gap_pf >= 15:
        itens.append({
            "problema": "Assimetria físico x financeiro ≥15pp.",
            "causa_raiz": "Critérios de medição divergentes.",
            "contramedida": "Unificar critérios e auditar 3 pacotes críticos.",
            "owner": owner, "prazo": "D+10", "categoria": "Execução/Medição"
        })
    hoje = date.today()
    for t in tarefas:
        if t.get("critica") and isinstance(t.get("fim"), date) and t["fim"] < hoje and (t.get("pct") or 0) < 100:
            itens.append({
                "problema": f"Tarefa crítica atrasada: {t.get('nome','')}.",
                "causa_raiz": "Sequenciamento / restrições não modeladas.",
                "contramedida": "Técnica de remoção de restrições (LPS) e travas de pré-requisitos.",
                "owner": owner, "prazo": "D+5", "categoria": "Planejamento/Execução"
            })
            break
    return itens[:5]

# ------------------------------
# Formatação (LEAN por padrão) — HOTFIX aplicado aqui
# ------------------------------
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
                  alinhamento: Dict[str, Any],
                  decisao: str) -> Dict[str, str]:

    nome = campos.get("nome_projeto", "Projeto não identificado") or "Projeto não identificado"
    cpi = campos.get("cpi", "Não informado")
    spi = campos.get("spi", "Não informado")
    fisico = campos.get("avanco_fisico", "Não informado")
    financeiro_pf = campos.get("avanco_financeiro", "Não informado")
    contrato = campos.get("tipo_contrato", "Não informado")
    stakeholders = campos.get("stakeholders", "Não informado")
    observacoes = campos.get("observacoes", "Não informado")
    objetivo = campos.get("objetivo", "Não informado")
    escopo = campos.get("escopo", "Não informado")

    # HOTFIX: converter indicadores e financeiro para número aqui
    ind_raw = campos.get("indicadores") or {}
    isp = to_number(ind_raw.get("isp"))
    idp = to_number(ind_raw.get("idp"))
    idco = to_number(ind_raw.get("idco"))
    idb = to_number(ind_raw.get("idb"))

    fin = campos.get("financeiro") or {}
    eac = to_number(fin.get("eac"))
    vac = to_number(fin.get("vac"))

    risco_emoji = {"Alto": "🔴", "Médio": "🟠", "Baixo": "🟢"}.get(risco, "⚠️")

    txt: List[str] = []
    header = f"[{nome}]  Risco: {risco} {risco_emoji} (score {score:.1f}) | Pilar: {pilar_final}"
    if divergente and pilar_sugerido:
        header += f" (divergente: sugerido {pilar_sugerido})"
    header += f" | Alinhamento Estratégico: {alinhamento.get('nivel')} ({alinhamento.get('score')}/100)"
    header += f" | Decisão: {decisao}"
    txt.append(header)

    # Alinhamento Estratégico
    txt += [
        "",
        "🎯 Alinhamento Estratégico",
        f"- Tema dominante: {alinhamento.get('tema_dominante') or '—'}; Coerência com ECK: {alinhamento.get('coerencia_eck') or '—'}",
    ]
    for b in (alinhamento.get("racional") or [])[:3]:
        txt.append(f"- {b}")
    if alinhamento.get("acoes_estrategicas"):
        txt.append("- Como alinhar/manter:")
        for a in alinhamento["acoes_estrategicas"][:3]:
            txt.append(f"  • {a}")

    # Riscos‑chave
    if riscos_chave:
        txt += ["", "⚠️ Riscos‑chave"]
        for r in riscos_chave[:MAX_BULLETS_RISCOS]:
            txt.append(f"- {r}")

    # Próximos passos (Recomendado) — limitado
    if proximos_passos_recomendado:
        txt += ["", "▶ Próximos Passos (Recomendado)"]
        for p in proximos_passos_recomendado[:MAX_BULLETS_ACOES]:
            txt.append(f"- {p}")

    # Indicadores essenciais (linha única)
    linha_inds = []
    if cpi != "Não informado": linha_inds.append(f"CPI {cpi}")
    if spi != "Não informado": linha_inds.append(f"SPI {spi}")
    if kpis.get("gap_pf") is not None: linha_inds.append(f"gap F×F {kpis['gap_pf']:.1f}pp")
    if any(x is not None for x in (isp, idp, idco, idb)):
        abaixo = [f"{lbl} {val:.2f}" for lbl, val in [("ISP", isp), ("IDP", idp), ("IDCo", idco), ("IDB", idb)]
                 if val is not None and val < 1.0]
        if abaixo:
            linha_inds.append("Índices<1,00: " + ", ".join(abaixo))
    if linha_inds:
        txt += ["", "📈 Indicadores", "- " + " | ".join(linha_inds)]

    # Financeiro (crítico somente)
    if FEATURES["enable_finance_pack"] and (eac is not None or vac is not None):
        evpvac = []
        if eac is not None: evpvac.append(f"EAC={eac}")
        if vac is not None: evpvac.append(f"VAC={vac}")
        if evpvac:
            txt += ["", "💰 Financeiro (crítico)", "- " + ", ".join(evpvac)]

    # Lições Aprendidas (curto)
    if licoes:
        txt += ["", "📚 Lições Aprendidas (sugeridas)"]
        for it in licoes[:2]:
            txt.append(f"- {it['problema']} → {it['contramedida']} (Owner {it['owner']}, {it['prazo']})")

    # Resumo final (uma linha)
    txt += ["", "✅ Resumo Executivo",
            f"Projeto “{nome}”: {risco} | Alinhamento {alinhamento.get('nivel')} ({alinhamento.get('score')}/100) | Decisão: {decisao}."]

    txt_report = "\n".join(txt)
    md_report = txt_report
    html_report = _html.escape(txt_report).replace("\n", "<br/>")
    return {"txt": txt_report.strip(), "md": md_report.strip(), "html": html_report}

# ------------------------------
# Core: _analisar
# ------------------------------
def _analisar(campos: Dict[str, Any]) -> Dict[str, Any]:
    trace: List[str] = []
    campos_num = {
        "cpi_num": to_number(campos.get("cpi")),
        "spi_num": to_number(campos.get("spi")),
        "avanco_fisico_num": percent_to_number(campos.get("avanco_fisico")),
        "avanco_financeiro_num": percent_to_number(campos.get("avanco_financeiro")),
    }
    ind_raw = campos.get("indicadores") or {}
    indicadores = {"isp": to_number(ind_raw.get("isp")), "idp": to_number(ind_raw.get("idp")), "idco": to_number(ind_raw.get("idco")), "idb": to_number(ind_raw.get("idb"))}

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

    baseline = campos.get("baseline") or {}
    fin_raw = campos.get("financeiro") or {}
    fin = {
        "capex_aprovado": fin_raw.get("capex_aprovado") or ((baseline.get("custo") or {}).get("capex_aprovado")),
        "capex_comp": fin_raw.get("capex_comp") or fin_raw.get("capex comprometido"),
        "capex_exec": fin_raw.get("capex_exec") or fin_raw.get("capex executado"),
        "ev": fin_raw.get("ev"), "pv": fin_raw.get("pv"), "ac": fin_raw.get("ac"),
        "eac": fin_raw.get("eac"), "vac": fin_raw.get("vac"),
    }

    gap_pf = None
    if campos_num["avanco_fisico_num"] is not None and campos_num["avanco_financeiro_num"] is not None:
        gap_pf = abs(campos_num["avanco_fisico_num"] - campos_num["avanco_financeiro_num"])
    kpis = {"gap_pf": gap_pf, "gap_spi": (TARGETS["spi"] - campos_num["spi_num"]) if campos_num["spi_num"] is not None else None, "gap_cpi": (TARGETS["cpi"] - campos_num["cpi_num"]) if campos_num["cpi_num"] is not None else None}

    pilar_declarado = campos.get("pilar", "Não informado")
    pilar_inferido = inferir_pilar(campos, campos_num, indicadores, trace)
    def _norm(s): return normalize(s or "")
    divergente = (pilar_declarado and pilar_declarado != "Não informado" and pilar_inferido and _norm(pilar_declarado) != _norm(pilar_inferido))
    pilar_final = pilar_declarado if (pilar_declarado and pilar_declarado != "Não informado") else (pilar_inferido or "Não informado")
    if divergente:
        trace.append(f"Divergência Pilar: declarado='{pilar_declarado}' vs sugerido='{pilar_inferido}'")

    score = 0.0
    score += calcular_score_risco_base(campos_num, campos.get("observacoes", ""), trace)
    score += risco_por_indices(indicadores, trace)
    if FEATURES["enable_schedule_pack"]:
        score += risco_por_cronograma(tarefas, trace)
    if FEATURES["enable_finance_pack"]:
        score += risco_por_baseline_financeiro(baseline, fin, trace)
    classificacao = classificar_risco(score)

    pilar_para_recomendado = pilar_inferido or pilar_final
    proximos_recomendado = gerar_proximos_passos(cpi=campos_num["cpi_num"], spi=campos_num["spi_num"], gap_pf=gap_pf, obs=campos.get("observacoes", ""), pilar_final=pilar_para_recomendado, stakeholders=campos.get("stakeholders", "Não informado"))
    proximos_atual = gerar_proximos_passos(cpi=campos_num["cpi_num"], spi=campos_num["spi_num"], gap_pf=gap_pf, obs=campos.get("observacoes", ""), pilar_final=pilar_declarado if pilar_declarado else "Não informado", stakeholders=campos.get("stakeholders", "Não informado"))

    riscos_chave = listar_riscos(campos_num, campos.get("observacoes", ""), indicadores, tarefas, baseline, fin)
    strategy = strategy_fit(campos, campos_num, indicadores)  # legado
    alinhamento = avaliar_alinhamento_estrategico(campos, campos_num, indicadores, pilar_inferido)

    def _decisao(classificacao: str, nivel_align: str) -> str:
        if nivel_align == "ALTO":
            return "Continuar" if classificacao in ("Baixo","Médio") else "Replanejar"
        if nivel_align == "MÉDIO":
            return "Replanejar" if classificacao in ("Médio","Alto") else "Continuar"
        return "Despriorizar" if classificacao != "Alto" else "Cancelar"
    decisao = _decisao(classificacao, alinhamento["nivel"])

    justificativa_final = justificativa_pilar_eck(pilar_final)
    justificativa_sugerido = justificativa_pilar_eck(pilar_inferido) if pilar_inferido else None

    reports = format_report(
        campos=campos, campos_num=campos_num, score=score, risco=classificacao,
        pilar_declarado=pilar_declarado, pilar_final=pilar_final,
        justificativa_eck_txt=justificativa_final,
        proximos_passos_recomendado=proximos_recomendado,
        proximos_passos_atual=proximos_atual,
        kpis=kpis, riscos_chave=riscos_chave,
        divergente=divergente, pilar_sugerido=pilar_inferido,
        justificativa_sugerido=justificativa_sugerido,
        strategy=strategy, licoes=gerar_licoes_aprendidas(campos, campos_num, kpis, tarefas, riscos_chave),
        alinhamento=alinhamento, decisao=decisao
    )

    payload_out = {
        "versao_api": "1.5.1",
        "campos_interpretados": {**campos, **campos_num, "pilar_final": pilar_final},
        "indicadores": indicadores,
        "kpis": kpis,
        "score_risco": score,
        "classificacao_risco": classificacao,
        "riscos_chave": riscos_chave,
        "strategy_fit": strategy,
        "alinhamento_estrategico": alinhamento,
        "decisao_recomendada": decisao,
        "pilar_declarado": pilar_declarado,
        "pilar_sugerido": pilar_inferido,
        "pilar_divergente": divergente,
        "proximos_passos_recomendado": proximos_recomendado,
        "proximos_passos_atual": proximos_atual,
        "licoes_aprendidas": gerar_licoes_aprendidas(campos, campos_num, kpis, tarefas, riscos_chave),
        "conclusao_executiva": reports["txt"],
        "conclusao_executiva_markdown": reports["md"],
        "conclusao_executiva_html": reports["html"],
        "trace": {"steps": []},
    }
    return payload_out

# ------------------------------
# Endpoints
# ------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "version": app.version, "risk_high_threshold": RISK_HIGH_THRESHOLD, "report_mode": REPORT_MODE}

@app.post("/analisar-projeto-texto")
async def analisar_projeto_texto(payload: TextoRequest, x_trace_id: Optional[str] = Header(default=None)):
    trace_id = x_trace_id or str(uuid.uuid4())
    campos = parse_from_text(payload.texto)
    out = _analisar(campos)
    out_trace = out.get("trace") or {}
    out_trace["trace_id"] = trace_id
    out["trace"] = out_trace
    return JSONResponse(content=out, headers={"X-Trace-Id": trace_id})

@app.post("/analisar-projeto")
async def analisar_projeto(payload: ProjetoRequest, x_trace_id: Optional[str] = Header(default=None)):
    trace_id = x_trace_id or str(uuid.uuid4())
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
    out = _analisar(campos)
    out_trace = out.get("trace") or {}
    out_trace["trace_id"] = trace_id
    out["trace"] = out_trace
    return JSONResponse(content=out, headers={"X-Trace-Id": trace_id})
