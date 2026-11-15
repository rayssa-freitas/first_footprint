"""
Similarity engine: compares every land cell with Moon/Mars profiles.

Per-variable similarity (0..1) is linear between the profile's 'ideal' and 'pior' (worst).
Profile score = weighted mean of the available variables.
Variables with no data are skipped and reported (coverage < 60% => no score).

Can also be run directly to export a ranking CSV:
    python processamento/analise.py marte_planicie
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from config import DADOS, GRADE_PARQUET, POP_VIZ_MAX
try:
    from config import PROTEGIDO_MAX
except ImportError:
    PROTEGIDO_MAX = None

REF = json.loads((DADOS / "referencias_planetarias.json").read_text(encoding="utf-8"))
PERFIS = REF["perfis"]
OPERACIONAL = REF["operacional"]["variaveis"]
COBERTURA_MIN = 0.6


def carregar_grade():
    if not GRADE_PARQUET.exists():
        return pd.DataFrame()
    df = pd.read_parquet(GRADE_PARQUET)
    df["abs_lat"] = df["lat"].abs()
    return df.set_index("id", drop=False)


def sim_variavel(x, ideal, pior):
    x = np.asarray(x, dtype="float64")
    s = (x - pior) / (ideal - pior)
    return np.clip(s, 0, 1)


def pontuar(df, variaveis):
    """Returns (score, coverage, matrix of per-variable similarities)."""
    sims, pesos = {}, {}
    for v, p in variaveis.items():
        if v not in df.columns:
            continue
        sims[v] = sim_variavel(df[v].values, p["ideal"], p["pior"])
        pesos[v] = p["peso"]
    if not sims:
        n = len(df)
        return np.full(n, np.nan), np.zeros(n), pd.DataFrame(index=df.index)
    S = pd.DataFrame(sims, index=df.index)
    W = np.array([pesos[c] for c in S.columns], dtype="float64")
    disp = S.notna().values
    w_tot = sum(p["peso"] for p in variaveis.values())
    w_ok = (disp * W).sum(axis=1)
    score = np.nansum(S.values * W, axis=1) / np.where(w_ok > 0, w_ok, np.nan)
    cobertura = w_ok / w_tot
    score[cobertura < COBERTURA_MIN] = np.nan
    return score, cobertura, S


def pontuar_todos(df):
    if df.empty:
        return df
    out = df.copy()
    for pid, perfil in PERFIS.items():
        s, c, _ = pontuar(df, perfil["variaveis"])
        out[f"score_{pid}"] = s
        out[f"cob_{pid}"] = c
    s, c, _ = pontuar(df, OPERACIONAL)
    out["score_operacional"] = s
    pop = out.get("pop_viz_km2")
    out["longe_cidades"] = (pop <= POP_VIZ_MAX) if pop is not None and pop.notna().any() else True
    # protected areas (WDPA): only excluded when PROTEGIDO_MAX is set in config.py
    prot = out.get("protegido_pct")
    if PROTEGIDO_MAX is not None and prot is not None and prot.notna().any():
        out["longe_cidades"] = out["longe_cidades"] & ~(prot >= PROTEGIDO_MAX)
    return out


def explicar(linha, perfil_id):
    """Details where the analogy works and where it fails for one cell."""
    perfil = PERFIS[perfil_id]
    itens = []
    for v, p in perfil["variaveis"].items():
        val = linha.get(v, np.nan)
        if val is None or pd.isna(val):
            itens.append({"variavel": v, "valor": None, "sim": None, "status": "sem dado",
                          "referencia": p["referencia"], "peso": p["peso"]})
            continue
        s = float(sim_variavel(val, p["ideal"], p["pior"]))
        status = "forte" if s >= 0.7 else ("parcial" if s >= 0.35 else "falha")
        itens.append({"variavel": v, "valor": round(float(val), 3), "sim": round(s, 2), "status": status,
                      "ideal": p["ideal"], "pior": p["pior"], "referencia": p["referencia"], "peso": p["peso"]})
    return {
        "perfil": perfil["nome"],
        "itens": itens,
        "limitacoes_fixas": REF["limitacoes_fixas"][perfil["corpo"]],
        "limitacoes_metodo": REF.get("limitacoes_metodo", []),
    }


if __name__ == "__main__":
    pid = sys.argv[1] if len(sys.argv) > 1 else "marte_planicie"
    df = pontuar_todos(carregar_grade())
    if df.empty:
        sys.exit("grade.parquet does not exist. Run processamento/processar_grade.py first.")
    top = df[df["longe_cidades"]].sort_values(f"score_{pid}", ascending=False).head(50)
    arq = DADOS / f"ranking_{pid}.csv"
    top.to_csv(arq, index=False)
    print(top[["lat", "lon", f"score_{pid}", "score_operacional"]].to_string())
    print("saved to", arq)
