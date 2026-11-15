"""
First Footprint API + website. Run from the project root:
    uvicorn app.main:app --reload
Open: http://127.0.0.1:8000
"""
import sys
import json
import math
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "processamento"))

import numpy as np
import requests
from fastapi import FastAPI, HTTPException
import datetime as dt
import re
import pandas as pd
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from config import CACHE, DADOS, RESULTADOS, TOP_N_POR_PERFIL
import analise
from app import viabilidade as vb

app = FastAPI(title="First Footprint")
STATIC = Path(__file__).parent / "static"
GRADE = analise.pontuar_todos(analise.carregar_grade())
CSV_KW = dict(sep=";", decimal=",", index=False, encoding="utf-8-sig")  # opens directly in Excel (pt-BR locale)

# English column names for every CSV the app writes (internal names stay the same)
COLS_EN = {
    "hora_local": "local_time", "temp_c": "temp_c", "umidade_pct": "humidity_pct", "chuva_mm_h": "rain_mm_h",
    "nuvem_pct": "cloud_pct", "visib_m": "visibility_m", "vento_ms": "wind_ms", "rajada_ms": "gust_ms",
    "vento_alt_ms": "wind_180m_ms", "elev_solar": "sun_elevation_deg", "poeira_ugm3": "dust_ugm3",
    "inicio": "start", "horas": "hours", "confiavel": "reliable", "mes": "month",
    "horas_ok_pct": "hours_ok_pct", "n_janelas": "n_windows", "primeira_janela": "first_window",
    "maior_janela_h": "longest_window_h", "data_hora": "timestamp", "nome": "name", "tipo": "type",
    "vento_max_ms": "max_wind_ms", "rajada_max_ms": "max_gust_ms", "vento_altitude_max_ms": "max_wind_180m_ms",
    "temp_min_c": "min_temp_c", "temp_max_c": "max_temp_c", "umidade_max_pct": "max_humidity_pct",
    "chuva_max_mm_h": "max_rain_mm_h", "nuvem_max_pct": "max_cloud_pct", "visibilidade_min_m": "min_visibility_m",
    "poeira_max_ugm3": "max_dust_ugm3", "aod_max": "max_aod", "luz_dia": "needs_daylight",
    "elev_solar_min_graus": "min_sun_elevation_deg", "elev_solar_max_graus": "max_sun_elevation_deg",
    "duracao_h": "required_window_h", "declividade_max_graus": "max_slope_deg", "nuvem_tipo": "clouds_counted",
    "perfil": "profile", "previsao_horas_ok_pct": "forecast_hours_ok_pct", "previsao_n_janelas": "forecast_n_windows",
    "historico_horas_ok_pct": "history_hours_ok_pct", "melhores_meses": "best_months", "declividade_ok": "slope_ok",
    "erro_previsao": "forecast_error", "erro_historico": "history_error", "arquivos": "files",
    "nuvem_frac": "cloud_fraction", "aod_550": "aod_550", "vapor_agua_cm": "water_vapour_cm", "ndvi_medio": "ndvi_mean",
    "ndvi_max": "ndvi_max", "lst_dia_c": "surface_temp_day_c", "lst_noite_c": "surface_temp_night_c",
    "amplitude_termica_c": "day_night_range_c", "lst_max_c": "surface_temp_max_c", "lst_min_c": "surface_temp_min_c",
    "terra_pct": "land_pct", "arido_pct": "barren_pct", "gelo_pct": "snow_ice_pct", "vento_medio_ms": "mean_wind_ms",
    "precip_mm_ano": "rain_mm_year", "t2m_c": "air_temp_c", "aerossol_ext_tau": "aerosol_extinction_tau",
    "umidade_rel_pct": "relative_humidity_pct", "pressao_hpa": "pressure_hpa", "elev_m": "elevation_m",
    "rugosidade_m": "roughness_m", "declividade_graus": "slope_deg", "pop_total": "population",
    "pop_dens_km2": "population_density_km2", "pop_viz_km2": "neighbourhood_population_km2",
    "rebanho_dens_km2": "livestock_density_km2", "abs_lat": "abs_lat", "score_operacional": "operational_score",
    "longe_cidades": "away_from_cities", "protegido_pct": "protected_area_pct",
    "basalto_pct": "basalt_pct", "sedimento_pct": "sediment_pct", "evaporito_pct": "evaporite_pct",
    "vulcanica_pct": "volcanic_pct",
}


PERFIL_EN = {"marte_planicie": "mars_plains", "marte_polar": "mars_polar", "lua_polo_sul": "moon_south_pole", "lua_mare": "moon_mare"}
VAL_EN = {"baixas_medias": "low_mid", "todas": "all", "baixas": "low"}


def en(df):
    """Renames columns to English for CSV export (ok_<criterion>, score_<profile> and cob_<profile> keep their suffix)."""
    def nome(c):
        c = str(c)
        if c in COLS_EN:
            return COLS_EN[c]
        if c.startswith("score_"):
            return "similarity_" + PERFIL_EN.get(c[6:], c[6:])
        if c.startswith("cob_"):
            return "coverage_" + PERFIL_EN.get(c[4:], c[4:])
        return c
    df = df.rename(columns=nome)
    for c in ("clouds_counted", "nuvem_tipo"):
        if c in df:
            df[c] = df[c].replace(VAL_EN)
    for c in ("profile", "perfil"):
        if c in df:
            df[c] = df[c].replace(PERFIL_EN)
    return df
EQUIPAMENTOS = json.loads((DADOS / "equipamentos.json").read_text(encoding="utf-8"))
CONHECIDOS = json.loads((DADOS / "analogos_conhecidos.json").read_text(encoding="utf-8"))


def limpar(d):
    return {k: (None if isinstance(v, float) and math.isnan(v) else
                (float(v) if isinstance(v, (np.floating,)) else
                 (bool(v) if isinstance(v, (np.bool_,)) else v))) for k, v in d.items()}


def celula_mais_proxima(lat, lon):
    if GRADE.empty:
        return None
    d = (GRADE["lat"] - lat) ** 2 + ((GRADE["lon"] - lon) * math.cos(math.radians(lat))) ** 2
    return GRADE.loc[d.idxmin()]


@app.get("/api/status")
def status():
    if GRADE.empty:
        return {"grade": False, "msg": "dados/grade.parquet not found. Run the data collection and processing first."}
    cols = [c for c in GRADE.columns if not c.startswith(("score_", "cob_"))]
    opcionais = {"rebanho_dens_km2"}  # optional layer (FAO GLW), not missing data
    vazias = [COLS_EN.get(c, c) for c in cols if c not in opcionais and GRADE[c].isna().all()]
    return {"grade": True, "celulas": len(GRADE), "variaveis_vazias": vazias,
            "longe_cidades": int(GRADE["longe_cidades"].sum())}


@app.get("/api/perfis")
def perfis():
    return {k: {"nome": v["nome"], "corpo": v["corpo"], "variaveis": list(v["variaveis"])}
            for k, v in analise.PERFIS.items()}


@app.get("/api/candidatas")
def candidatas(perfil: str = "marte_planicie", n: int = TOP_N_POR_PERFIL, so_remotas: bool = True):
    if GRADE.empty:
        return []
    col = f"score_{perfil}"
    if col not in GRADE:
        raise HTTPException(404, "unknown profile")
    df = GRADE[GRADE["longe_cidades"]] if so_remotas else GRADE
    df = df.dropna(subset=[col]).sort_values(col, ascending=False).head(n)
    return [limpar({"id": r.id, "lat": r.lat, "lon": r.lon, "score": round(getattr(r, col), 3),
                    "operacional": round(r.score_operacional, 3) if not math.isnan(r.score_operacional) else None,
                    "protegido": round(float(getattr(r, "protegido_pct", float("nan"))), 0)})
            for r in df.itertuples()]


def contar_gbif(lat, lon):
    """Animal records (kingdom Animalia) in GBIF inside the 1° cell."""
    arq = CACHE / f"gbif_{lat:.1f}_{lon:.1f}.json"
    if arq.exists():
        return json.loads(arq.read_text())
    try:
        r = requests.get("https://api.gbif.org/v1/occurrence/search", timeout=20, params={
            "decimalLatitude": f"{lat-0.5},{lat+0.5}", "decimalLongitude": f"{lon-0.5},{lon+0.5}",
            "kingdomKey": 1, "limit": 0})
        res = {"registros_animais": r.json().get("count"), "fonte": "GBIF",
               "nota": "Counts occurrence records; depends on sampling effort, not a density."}
    except Exception as e:  # noqa
        return {"registros_animais": None, "erro": str(e)}
    arq.write_text(json.dumps(res))
    return res


@app.get("/api/celula/{cid}")
def celula(cid: str, perfil: str = "marte_planicie"):
    if cid not in GRADE.index:
        raise HTTPException(404, "cell not found")
    linha = GRADE.loc[cid]
    dados = limpar(linha.to_dict())
    return {"dados": dados, "analise": analise.explicar(linha, perfil),
            "fauna": contar_gbif(linha["lat"], linha["lon"])}


@app.get("/api/regiao")
def regiao(lat: float, lon: float, raio_km: float = 300, perfil: str = "marte_planicie"):
    if GRADE.empty:
        return {"celulas": []}
    la1, lo1 = np.radians(lat), np.radians(lon)
    la2, lo2 = np.radians(GRADE["lat"].values), np.radians(GRADE["lon"].values)
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    dist = 6371 * 2 * np.arcsin(np.sqrt(a))
    df = GRADE[dist <= raio_km].copy()
    df["dist_km"] = dist[dist <= raio_km]
    col = f"score_{perfil}"
    df = df.sort_values(col, ascending=False)
    cols = ["id", "lat", "lon", col, "score_operacional", "longe_cidades", "dist_km"]
    medias = df.select_dtypes("number").mean().round(3).to_dict()
    return {"n": len(df), "celulas": [limpar(r) for r in df[cols].rename(columns={col: "score"}).to_dict("records")],
            "medias": limpar(medias)}


@app.get("/api/conhecidos")
def conhecidos(perfil: str = "marte_planicie"):
    out = []
    for a in CONHECIDOS:
        c = celula_mais_proxima(a["lat"], a["lon"])
        s = None if c is None else c.get(f"score_{perfil}")
        out.append({**a, "score": None if s is None or math.isnan(s) else round(float(s), 3),
                    "celula": None if c is None else c["id"]})
    return out


@app.post("/api/viabilidade")
def viabilidade(eq: vb.Equipamento):
    c = celula_mais_proxima(eq.lat, eq.lon)
    res = {"equipamento": eq.model_dump(), "local": vb.checar_local(None if c is None else limpar(c.to_dict()), eq)}
    for nome, f in (("previsao", vb.previsao), ("historico", vb.historico)):
        try:
            res[nome] = f(eq)
        except Exception as e:  # noqa
            res[nome] = {"erro": f"{type(e).__name__}: {e}"}
    res["arquivos"] = salvar_viabilidade(eq, res)
    return res


@app.post("/api/viabilidade/previsao")
def viab_previsao(eq: vb.Equipamento):
    c = celula_mais_proxima(eq.lat, eq.lon)
    res = {"local": vb.checar_local(None if c is None else limpar(c.to_dict()), eq)}
    try:
        res["previsao"] = vb.previsao(eq)
    except Exception as e:  # noqa
        res["previsao"] = {"erro": f"{type(e).__name__}: {e}"}
    res["arquivos"] = salvar_viabilidade(eq, res)
    return res


@app.post("/api/viabilidade/historico")
def viab_historico(eq: vb.Equipamento):
    try:
        h = vb.historico(eq)
    except Exception as e:  # noqa
        h = {"erro": f"{type(e).__name__}: {e}"}
    res = {"historico": h}
    res["arquivos"] = salvar_viabilidade(eq, res)
    return res


from pydantic import BaseModel


class PedidoMapa(BaseModel):
    equipamento: vb.Equipamento
    pontos: list[dict]


@app.post("/api/viabilidade/mapa")
def viab_mapa(p: PedidoMapa):
    pts = [{"id": str(q.get("id", i)), "lat": float(q["lat"]), "lon": float(q["lon"])}
           for i, q in enumerate(p.pontos[:150])]
    try:
        res = vb.previsao_lote(p.equipamento, pts)
    except Exception as e:  # noqa
        raise HTTPException(502, f"{type(e).__name__}: {e}")
    nome = f"{dt.datetime.now():%Y%m%d_%H%M%S}_map_feasibility.csv"
    en(pd.DataFrame(res)).to_csv(RESULTADOS / nome, **CSV_KW)
    return {"pontos": res, "arquivo": f"/api/resultados/{nome}"}


class PedidoPeriodo(BaseModel):
    equipamento: vb.Equipamento
    inicio: str
    fim: str


@app.post("/api/simulacao/historico")
def sim_historico(p: PedidoPeriodo):
    try:
        r = vb.simular_periodo(p.equipamento, dt.date.fromisoformat(p.inicio), dt.date.fromisoformat(p.fim))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa
        raise HTTPException(502, f"{type(e).__name__}: {e}")
    df = r.pop("_df")
    nome = re.sub(r"\W+", "_", p.equipamento.nome)[:30]
    base = f"{dt.datetime.now():%Y%m%d_%H%M%S}_{nome}_history_{p.inicio}_{p.fim}"
    cols = ["hora_local", "ok"] + [c for c in df.columns if c not in ("hora_local", "ok")]
    en(df[cols].round(2)).to_csv(RESULTADOS / f"{base}_hours.csv", **CSV_KW)
    en(pd.DataFrame(r["janelas"] or [{"inicio": None, "horas": 0}])).to_csv(RESULTADOS / f"{base}_windows.csv", **CSV_KW)
    r["arquivos"] = [f"/api/resultados/{base}_hours.csv", f"/api/resultados/{base}_windows.csv"]
    return r


class PedidoLoteHist(BaseModel):
    equipamento: vb.Equipamento
    pontos: list[dict]


@app.post("/api/simulacao/historico_lote")
def sim_historico_lote(p: PedidoLoteHist):
    pts = [{"id": str(q.get("id", i)), "lat": float(q["lat"]), "lon": float(q["lon"]), "data": str(q["data"])}
           for i, q in enumerate(p.pontos[:40])]
    return {"pontos": vb.simular_dias(p.equipamento, pts)}


@app.get("/api/simulacao/limites")
def sim_limites():
    return {"fim_disponivel": f"{vb.fim_disponivel():%Y-%m-%d}", "ano": vb.fim_disponivel().year}


def salvar_viabilidade(eq, res):
    """Writes the query CSVs to dados/resultados and appends a line to the general log."""
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"{ts}_{re.sub(r'\W+', '_', eq.nome)[:30]}"
    arqs = []
    p, h = res.get("previsao", {}), res.get("historico", {})
    if "horas" in p:
        en(pd.DataFrame(p["horas"])).to_csv(RESULTADOS / f"{base}_forecast_hours.csv", **CSV_KW); arqs.append(f"{base}_forecast_hours.csv")
        en(pd.DataFrame(p["janelas"] or [{"inicio": None, "horas": 0}])).to_csv(RESULTADOS / f"{base}_windows.csv", **CSV_KW); arqs.append(f"{base}_windows.csv")
    if "matriz_pct" in h:
        m = pd.DataFrame(h["matriz_pct"], columns=[f"h{i:02d}" for i in range(24)])
        m.insert(0, "mes", range(1, 13))
        en(m).to_csv(RESULTADOS / f"{base}_history_month_hour.csv", **CSV_KW); arqs.append(f"{base}_history_month_hour.csv")
    linha = {"data_hora": ts, **eq.model_dump(),
             "previsao_horas_ok_pct": p.get("horas_ok_pct"), "previsao_n_janelas": len(p.get("janelas", []) or []),
             "primeira_janela": (p.get("janelas") or [{}])[0].get("inicio") if p.get("janelas") else None,
             "historico_horas_ok_pct": h.get("horas_ok_pct"),
             "melhores_meses": ",".join(map(str, h.get("melhores_meses", []))),
             "declividade_ok": (res.get("local") or {}).get("ok"),
             "erro_previsao": p.get("erro"), "erro_historico": h.get("erro"), "arquivos": " | ".join(arqs)}
    log = RESULTADOS / "feasibility_log.csv"
    en(pd.DataFrame([linha])).to_csv(log, mode="a", header=not log.exists(), **CSV_KW)
    return [f"/api/resultados/{a}" for a in arqs] + ["/api/resultados/feasibility_log.csv"]


@app.get("/api/resultados/{arquivo}")
def baixar_resultado(arquivo: str):
    f = (RESULTADOS / Path(arquivo).name)
    if not f.exists():
        raise HTTPException(404, "file not found")
    return FileResponse(f, media_type="text/csv", filename=f.name)


@app.get("/api/export/candidatas.csv")
def exportar_candidatas(perfil: str = "marte_planicie", so_remotas: bool = True, n: int = 500):
    if GRADE.empty:
        raise HTTPException(404, "no processed grid")
    col = f"score_{perfil}"
    df = GRADE[GRADE["longe_cidades"]] if so_remotas else GRADE
    df = df.dropna(subset=[col]).sort_values(col, ascending=False).head(n)
    df = df.dropna(axis=1, how="all").round(4)  # no empty columns, no 9-decimal noise
    nome = f"candidates_{PERFIL_EN.get(perfil, perfil)}_{dt.datetime.now():%Y%m%d_%H%M}.csv"
    en(df).to_csv(RESULTADOS / nome, **CSV_KW)
    return FileResponse(RESULTADOS / nome, media_type="text/csv", filename=nome)


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/api/equipamentos")
def equipamentos():
    return EQUIPAMENTOS


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
