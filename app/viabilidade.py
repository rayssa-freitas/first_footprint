"""
Feasibility of a landing/launch/field test for a piece of equipment at a site.

Two different answers:
1) FORECAST (next 16 days, hour by hour): Open-Meteo, which aggregates weather
   service models (ECMWF, NOAA GFS, DWD ICON...). Dust/AOD come from CAMS
   (Copernicus) and only cover ~5 days.
2) HISTORY (probability by month x hour): hourly NASA POWER (MERRA-2/CERES),
   last complete years. It says WHEN conditions usually work, not whether a
   specific day beyond 16 days will work.
"""
import json
import math
import datetime as dt
from typing import Optional

import numpy as np
import pandas as pd
import requests
from pydantic import BaseModel, Field

from config import CACHE

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY = "https://air-quality-api.open-meteo.com/v1/air-quality"
POWER_HORARIO = "https://power.larc.nasa.gov/api/temporal/hourly/point"
ANOS_HISTORICO = 2  # 2 years = 2 requests; faster for the demo


class Equipamento(BaseModel):
    nome: str = "Test module"
    tipo: str = Field("pouso", description="pouso (landing) | lancamento (launch) | rover | drone")
    lat: float
    lon: float
    vento_max_ms: float = 10.0
    rajada_max_ms: Optional[float] = 15.0
    vento_altitude_max_ms: Optional[float] = None  # wind at ~180 m (launch/drone)
    temp_min_c: float = -20.0
    temp_max_c: float = 45.0
    umidade_max_pct: Optional[float] = 90.0
    chuva_max_mm_h: float = 0.1
    nuvem_max_pct: Optional[float] = 50.0   # optical navigation / cameras
    visibilidade_min_m: Optional[float] = 5000.0
    poeira_max_ugm3: Optional[float] = None
    aod_max: Optional[float] = None
    luz_dia: bool = True
    elev_solar_min_graus: float = 10.0
    elev_solar_max_graus: Optional[float] = None  # to simulate grazing sun (lunar pole)
    duracao_h: int = 3                    # consecutive hours required
    declividade_max_graus: Optional[float] = None
    # "baixas_medias": only clouds that block the view of the ground (optical navigation);
    # "todas": includes high cirrus (more conservative)
    nuvem_tipo: str = "baixas_medias"
    perfil: Optional[str] = None          # planetary profile active on the globe


# ---------- Sun position (simplified NOAA algorithm, error < 1°) ----------
def elevacao_solar(utc: pd.DatetimeIndex, lat, lon):
    doy = utc.dayofyear.values
    hora = utc.hour.values + utc.minute.values / 60
    g = 2 * math.pi / 365 * (doy - 1 + (hora - 12) / 24)
    eqt = 229.18 * (0.000075 + 0.001868 * np.cos(g) - 0.032077 * np.sin(g)
                    - 0.014615 * np.cos(2 * g) - 0.040849 * np.sin(2 * g))
    decl = (0.006918 - 0.399912 * np.cos(g) + 0.070257 * np.sin(g) - 0.006758 * np.cos(2 * g)
            + 0.000907 * np.sin(2 * g) - 0.002697 * np.cos(3 * g) + 0.00148 * np.sin(3 * g))
    t_solar = hora * 60 + eqt + 4 * lon
    ha = np.radians(t_solar / 4 - 180)
    la = math.radians(lat)
    cosz = math.sin(la) * np.sin(decl) + math.cos(la) * np.cos(decl) * np.cos(ha)
    return 90 - np.degrees(np.arccos(np.clip(cosz, -1, 1)))


# ---------- rules ----------
def avaliar(df: pd.DataFrame, eq: Equipamento) -> pd.DataFrame:
    """Takes standardized columns and returns df with ok_<criterion> and ok (all of them)."""
    regras = {
        "wind": ("vento_ms", lambda x: x <= eq.vento_max_ms),
        "gust": ("rajada_ms", (lambda x: x <= eq.rajada_max_ms) if eq.rajada_max_ms else None),
        "wind_180m": ("vento_alt_ms", (lambda x: x <= eq.vento_altitude_max_ms) if eq.vento_altitude_max_ms else None),
        "temperature": ("temp_c", lambda x: (x >= eq.temp_min_c) & (x <= eq.temp_max_c)),
        "humidity": ("umidade_pct", (lambda x: x <= eq.umidade_max_pct) if eq.umidade_max_pct else None),
        "rain": ("chuva_mm_h", lambda x: x <= eq.chuva_max_mm_h),
        "clouds": ("nuvem_pct", (lambda x: x <= eq.nuvem_max_pct) if eq.nuvem_max_pct is not None else None),
        "visibility": ("visib_m", (lambda x: x >= eq.visibilidade_min_m) if eq.visibilidade_min_m else None),
        "dust": ("poeira_ugm3", (lambda x: x <= eq.poeira_max_ugm3) if eq.poeira_max_ugm3 else None),
        "aod": ("aod", (lambda x: x <= eq.aod_max) if eq.aod_max else None),
    }
    if eq.luz_dia:
        regras["sun"] = ("elev_solar", lambda x: (x >= eq.elev_solar_min_graus) &
                         ((x <= eq.elev_solar_max_graus) if eq.elev_solar_max_graus is not None else True))
    usados, sem_dado = [], []
    ok_total = pd.Series(True, index=df.index)
    for nome, (col, f) in regras.items():
        if f is None:
            continue
        if col not in df or df[col].isna().all():
            sem_dado.append(nome)
            continue
        val = df[col]
        res = pd.Series(f(val), index=df.index).astype(bool) | val.isna()  # no data for that hour: does not fail it
        df[f"ok_{nome}"] = res
        ok_total &= res
        usados.append(nome)
    # an hour with no weather data at all (end of forecast) cannot count as OK
    base = [c for c in ("temp_c", "vento_ms") if c in df]
    if base:
        ok_total &= ~df[base].isna().all(axis=1)
    df["ok"] = ok_total
    df.attrs["criterios"] = usados
    df.attrs["sem_dado"] = sem_dado
    return df


def marcar_confianca(jans, t0):
    lim = pd.Timestamp(t0) + pd.Timedelta(days=DIAS_CONFIAVEIS)
    for j in jans:
        j["confiavel"] = pd.Timestamp(j["inicio"]) < lim
    return jans


def janelas(df: pd.DataFrame, duracao: int, col_tempo="hora_local"):
    """Runs of OK hours at least `duracao` long."""
    out, ini, n = [], None, 0
    for t, ok in zip(df[col_tempo], df["ok"]):
        if ok:
            ini = ini or t
            n += 1
        else:
            if n >= duracao:
                out.append({"inicio": str(ini), "horas": n})
            ini, n = None, 0
    if n >= duracao:
        out.append({"inicio": str(ini), "horas": n})
    return out


# ---------- forecast ----------
HOURLY = ("temperature_2m,relative_humidity_2m,precipitation,cloud_cover,cloud_cover_low,cloud_cover_mid,"
          "visibility,wind_speed_10m,wind_gusts_10m,wind_speed_180m")
DIAS_CONFIAVEIS = 7  # after this the forecast is indicative


def _nuvem(h, tipo):
    tot = pd.to_numeric(pd.Series(h.get("cloud_cover")), errors="coerce")
    if tipo == "todas":
        return tot
    n = len(tot)
    camadas = [pd.to_numeric(pd.Series(h[k]), errors="coerce").reindex(range(n))
               for k in ("cloud_cover_low", "cloud_cover_mid") if h.get(k) is not None]
    if not camadas:
        return tot
    bm = pd.concat(camadas, axis=1).max(axis=1)  # cover that blocks the view of the ground
    return bm.where(bm.notna(), tot)


def _df_previsao(j, lat, lon, eq):
    h = j["hourly"]
    df = pd.DataFrame({
        "hora_local": pd.to_datetime(h["time"]),
        "temp_c": h.get("temperature_2m"), "umidade_pct": h.get("relative_humidity_2m"),
        "chuva_mm_h": h.get("precipitation"), "nuvem_pct": _nuvem(h, eq.nuvem_tipo).values,
        "visib_m": h.get("visibility"), "vento_ms": h.get("wind_speed_10m"),
        "rajada_ms": h.get("wind_gusts_10m"), "vento_alt_ms": h.get("wind_speed_180m"),
    })
    for c in df.columns[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    utc = pd.DatetimeIndex(df["hora_local"] - pd.Timedelta(seconds=j.get("utc_offset_seconds", 0)))
    df["elev_solar"] = elevacao_solar(utc, lat, lon)
    return df


def previsao(eq: Equipamento):
    p = {"latitude": eq.lat, "longitude": eq.lon, "forecast_days": 16, "timezone": "auto",
         "wind_speed_unit": "ms", "hourly": HOURLY}
    r = requests.get(OPEN_METEO, params=p, timeout=30)
    r.raise_for_status()
    j = r.json()
    df = _df_previsao(j, eq.lat, eq.lon, eq)
    # dust and AOD (CAMS) — optional, ~5 days
    try:
        a = requests.get(AIR_QUALITY, params={"latitude": eq.lat, "longitude": eq.lon, "timezone": "auto",
                                               "hourly": "dust,aerosol_optical_depth", "forecast_days": 5},
                         timeout=20).json()["hourly"]
        aq = pd.DataFrame({"hora_local": pd.to_datetime(a["time"]),
                           "poeira_ugm3": pd.to_numeric(pd.Series(a.get("dust")), errors="coerce"),
                           "aod": pd.to_numeric(pd.Series(a.get("aerosol_optical_depth")), errors="coerce")})
        df = df.merge(aq, on="hora_local", how="left")
    except Exception:  # noqa
        pass
    df = avaliar(df, eq)
    horas = df.assign(hora_local=df["hora_local"].dt.strftime("%Y-%m-%d %H:%M")).replace({np.nan: None})
    motivos = [c for c in df.columns if c.startswith("ok_")]
    return {
        "fonte": "Open-Meteo (ECMWF/GFS/ICON) + CAMS for dust/AOD",
        "fuso": j.get("timezone"),
        "criterios": df.attrs["criterios"], "sem_dado": df.attrs["sem_dado"],
        "janelas": marcar_confianca(janelas(df, eq.duracao_h), df["hora_local"].iloc[0]),
        "nuvem_tipo": "low + mid (block the view of the ground)" if eq.nuvem_tipo != "todas" else "all (includes high cirrus)",
        "horas_ok_pct": round(100 * df["ok"].mean(), 1),
        "horas": horas[["hora_local", "ok", "temp_c", "vento_ms", "rajada_ms", "nuvem_pct", "chuva_mm_h",
                        "visib_m", "elev_solar"] + [c for c in ("poeira_ugm3", "aod") if c in horas] + motivos]
        .round(2).to_dict("records"),
    }


def previsao_lote(eq: Equipamento, pontos: list[dict]):
    """Same rule for many points at once (Open-Meteo accepts a list of coordinates)."""
    out = []
    for i in range(0, len(pontos), 50):
        lote = pontos[i:i + 50]
        p = {"latitude": ",".join(f"{q['lat']:.3f}" for q in lote),
             "longitude": ",".join(f"{q['lon']:.3f}" for q in lote),
             "forecast_days": 16, "timezone": "auto", "wind_speed_unit": "ms", "hourly": HOURLY}
        r = requests.get(OPEN_METEO, params=p, timeout=60)
        r.raise_for_status()
        js = r.json()
        js = js if isinstance(js, list) else [js]
        for q, j in zip(lote, js):
            df = avaliar(_df_previsao(j, q["lat"], q["lon"], eq), eq)
            jan = janelas(df, eq.duracao_h)
            out.append({**q, "horas_ok_pct": round(100 * df["ok"].mean(), 1), "n_janelas": len(jan),
                        "primeira_janela": jan[0]["inicio"] if jan else None,
                        "maior_janela_h": max((x["horas"] for x in jan), default=0)})
    return out


# ---------- NASA POWER history ----------
PARAMS_POWER = ["T2M", "RH2M", "WS10M", "PRECTOTCORR", "ALLSKY_SFC_SW_DWN", "CLRSKY_SFC_SW_DWN"]


DEFASAGEM_DIAS = 3  # NASA POWER: weather data becomes available ~2-3 days later


def fim_disponivel():
    return dt.date.today() - dt.timedelta(days=DEFASAGEM_DIAS)


def _power_bruto(lat, lon, ini: dt.date, fim: dt.date):
    """Downloads hourly NASA POWER (UTC) between two dates, cached on disk."""
    arq = CACHE / f"power_{lat:.2f}_{lon:.2f}_{ini:%Y%m%d}_{fim:%Y%m%d}.json"
    if arq.exists():
        return json.loads(arq.read_text())
    params = {"parameters": ",".join(PARAMS_POWER), "community": "RE", "latitude": lat, "longitude": lon,
              "start": f"{ini:%Y%m%d}", "end": f"{fim:%Y%m%d}", "format": "JSON", "time-standard": "UTC"}
    r = requests.get(POWER_HORARIO, params=params, timeout=90)
    if r.status_code == 422:  # some parameter (e.g. recent radiation) unavailable: retry with the minimum set
        params["parameters"] = "T2M,RH2M,WS10M,PRECTOTCORR"
        r = requests.get(POWER_HORARIO, params=params, timeout=90)
    r.raise_for_status()
    dados = r.json()["properties"]["parameter"]
    arq.write_text(json.dumps(dados))
    return dados


def power_ano(lat, lon, ano):
    return _power_bruto(lat, lon, dt.date(ano, 1, 1), dt.date(ano, 12, 31))


def _df_power(blocos, eq):
    """Converts POWER blocks into standardized columns (UTC index)."""
    df = pd.concat([pd.DataFrame(b) for b in blocos])
    df.index = pd.to_datetime(df.index, format="%Y%m%d%H", utc=True)
    df = df[~df.index.duplicated()].sort_index().replace(-999, np.nan).astype(float)
    out = pd.DataFrame(index=df.index)
    out["temp_c"] = df.get("T2M")
    out["umidade_pct"] = df.get("RH2M")
    out["vento_ms"] = df.get("WS10M")
    out["chuva_mm_h"] = df.get("PRECTOTCORR")
    if {"ALLSKY_SFC_SW_DWN", "CLRSKY_SFC_SW_DWN"} <= set(df.columns):
        clr = df["CLRSKY_SFC_SW_DWN"].where(df["CLRSKY_SFC_SW_DWN"] > 50)
        out["nuvem_pct"] = (100 * (1 - df["ALLSKY_SFC_SW_DWN"] / clr)).clip(0, 100)  # proxy, daytime only
    out["elev_solar"] = elevacao_solar(df.index, eq.lat, eq.lon)
    return out


NOTA_HIST = ("Hourly NASA POWER history (MERRA-2 / GEOS-IT). No gust, visibility or dust: "
             "those criteria only apply to the forecast. Cloudiness is estimated from the ratio of actual to clear-sky radiation "
             "(daytime only; may be missing in recent months because of the CERES delay). Time = local solar time.")


def historico(eq: Equipamento):
    """Climatology: chance of a window by month x hour over the last complete years."""
    lat, lon = round(eq.lat, 2), round(eq.lon, 2)
    ano_fim = dt.date.today().year - 1
    out = _df_power([power_ano(lat, lon, a) for a in range(ano_fim - ANOS_HISTORICO + 1, ano_fim + 1)], eq)
    out = avaliar(out, eq)
    ok_janela = out["ok"].astype(float)[::-1].rolling(eq.duracao_h, min_periods=eq.duracao_h).min()[::-1]
    hora_solar = (out.index + pd.to_timedelta(eq.lon / 15, unit="h"))
    tab = pd.DataFrame({"mes": hora_solar.month, "hora": hora_solar.hour, "ok": ok_janela.values})
    matriz = tab.pivot_table(index="mes", columns="hora", values="ok", aggfunc="mean") * 100
    matriz = matriz.reindex(index=range(1, 13), columns=range(24))
    media_mes = matriz.mean(axis=1)  # mean chance of a window across the day
    return {
        "fonte": f"Hourly NASA POWER (MERRA-2/CERES), {ano_fim - ANOS_HISTORICO + 1}–{ano_fim}",
        "nota": NOTA_HIST,
        "criterios": out.attrs["criterios"], "sem_dado": out.attrs["sem_dado"],
        "hora": "local solar time",
        "matriz_pct": [[None if pd.isna(v) else round(float(v), 1) for v in linha] for linha in matriz.values],
        "melhores_meses": [int(m) for m in media_mes.sort_values(ascending=False).index[:3]],
        "media_mes_pct": [None if pd.isna(v) else round(float(v), 1) for v in media_mes.values],
        "horas_ok_pct": round(100 * out["ok"].mean(), 1),
    }


def _periodo_valido(ini: dt.date, fim: dt.date):
    lim = fim_disponivel()
    if fim > lim:
        fim = lim
    if ini > fim:
        raise ValueError(f"No data for this period: NASA POWER goes up to {lim:%Y-%m-%d}.")
    if (fim - ini).days > 366:
        raise ValueError("Maximum period: 366 days.")
    return ini, fim


def _avaliar_periodo(eq, ini, fim):
    lat, lon = round(eq.lat, 2), round(eq.lon, 2)
    blocos = []
    for ano in range(ini.year, fim.year + 1):  # one request per year (cached)
        a, b = max(ini, dt.date(ano, 1, 1)), min(fim, dt.date(ano, 12, 31))
        blocos.append(_power_bruto(lat, lon, a, b))
    out = avaliar(_df_power(blocos, eq), eq)
    out.index = out.index + pd.to_timedelta(eq.lon / 15, unit="h")  # local solar time
    out = out[(out.index.date >= ini) & (out.index.date <= fim)]
    out = out.assign(hora_local=out.index.strftime("%Y-%m-%d %H:%M"))
    return out


def simular_periodo(eq: Equipamento, ini: dt.date, fim: dt.date):
    """Replays the equipment rules hour by hour over a real past period."""
    ini, fim = _periodo_valido(ini, fim)
    out = _avaliar_periodo(eq, ini, fim)
    jan = janelas(out, eq.duracao_h)
    dias = out.groupby(out.index.date)["ok"].agg(["sum", "count"])
    maior_dia = {}
    for j in jan:
        d = j["inicio"][:10]
        maior_dia[d] = max(maior_dia.get(d, 0), j["horas"])
    mes = out.groupby(out.index.month)["ok"].mean() * 100
    return {
        "fonte": f"Hourly NASA POWER, {ini:%Y-%m-%d} to {fim:%Y-%m-%d}",
        "nota": NOTA_HIST, "fim_disponivel": f"{fim_disponivel():%Y-%m-%d}",
        "criterios": out.attrs.get("criterios", []), "sem_dado": out.attrs.get("sem_dado", []),
        "horas_ok_pct": round(100 * out["ok"].mean(), 1),
        "n_janelas": len(jan), "dias_com_janela": len(maior_dia), "dias": len(dias),
        "janelas": jan[:300],
        "tira": {"inicio": out["hora_local"].iloc[0] if len(out) else None,
                 "ok": out["ok"].astype(int).tolist()},
        "por_mes_pct": {int(k): round(float(v), 1) for k, v in mes.items()},
        "_df": out,  # removed before responding; used to write the CSV
    }


def simular_dias(eq: Equipamento, pontos: list[dict]):
    """Random draw on history: evaluates one specific past day for each point."""
    res = []
    for q in pontos:
        d = dt.date.fromisoformat(q["data"])
        e = eq.model_copy(update={"lat": q["lat"], "lon": q["lon"]})
        try:
            out = _avaliar_periodo(e, d, d)
            jan = janelas(out, e.duracao_h)
            res.append({**q, "horas_ok_pct": round(100 * out["ok"].mean(), 1), "n_janelas": len(jan),
                        "primeira_janela": jan[0]["inicio"] if jan else None,
                        "maior_janela_h": max((x["horas"] for x in jan), default=0)})
        except Exception as ex:  # noqa
            res.append({**q, "erro": f"{type(ex).__name__}: {ex}"})
    return res


def checar_local(celula: Optional[dict], eq: Equipamento):
    """Cell terrain + whether the point is (or is not) an analog candidate in the active profile."""
    if not celula:
        return None
    out = {}
    if eq.perfil:
        sc = celula.get(f"score_{eq.perfil}")
        if sc is not None and not (isinstance(sc, float) and math.isnan(sc)):
            out["similaridade"] = round(float(sc), 2)
            out["remota"] = bool(celula.get("longe_cidades"))
            out["e_candidata"] = out["similaridade"] >= 0.6 and out["remota"]
    if eq.declividade_max_graus is not None:
        d = celula.get("declividade_graus")
        if d is None or (isinstance(d, float) and math.isnan(d)):
            out["declividade"] = "no data"
        else:
            out.update({"declividade_media_celula": round(d, 2), "limite": eq.declividade_max_graus,
                        "ok": d <= eq.declividade_max_graus,
                        "nota": "1° cell mean (ETOPO ~1.8 km). For the exact spot, use a 30 m DEM (Copernicus/SRTM)."})
    return out or None
