"""
End-to-end test with SYNTHETIC FILES (same format as the real ones, made-up values).
Only validates the code without downloading GBs. Does not use or change dados/.
    python tests/teste_sintetico.py
"""
import sys, json, zipfile, tempfile, shutil
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RAIZ), str(RAIZ / "processamento")]
import numpy as np
import pandas as pd

TMP = Path(tempfile.mkdtemp())
rng = np.random.default_rng(0)
lat5 = np.linspace(89.975, -89.975, 3600)[:, None]
arid = (np.abs(np.abs(lat5) - 25) < 8).astype(float) * np.ones((1, 7200))  # "desert" band


def hdf(path, campos):
    from pyhdf.SD import SD, SDC
    path.parent.mkdir(parents=True, exist_ok=True)
    sd = SD(str(path), SDC.WRITE | SDC.CREATE)
    for nome, (arr, tipo, attrs) in campos.items():
        s = sd.create(nome, tipo, arr.shape)
        s[:] = arr
        for k, v in attrs.items():
            setattr(s, k, v)
        s.endaccess()
    sd.end()


def criar():
    from pyhdf.SD import SDC
    import xarray as xr
    B = TMP / "brutos"
    for m in (1, 7):
        ndvi = (0.6 - 0.55 * arid + rng.normal(0, .02, arid.shape)) * 1e4
        hdf(B / f"mod13/MOD13C2.A2023{m:03d}.061.x.hdf", {"CMG 0.05 Deg Monthly NDVI": (ndvi.astype("int16"), SDC.INT16, {"_FillValue": -3000})})
        dia = (300 + 25 * arid) / 0.02
        noi = (285 - 10 * arid) / 0.02
        hdf(B / f"mod11/MOD11C3.A2023{m:03d}.061.x.hdf", {
            "LST_Day_CMG": (dia.astype("uint16"), SDC.UINT16, {"_FillValue": 0}),
            "LST_Night_CMG": (noi.astype("uint16"), SDC.UINT16, {"_FillValue": 0})})
        a1 = arid[::20, ::20]
        hdf(B / f"mod08/MOD08_M3.A2023{m:03d}.061.x.hdf", {
            "Cloud_Fraction_Mean_Mean": (((0.6 - 0.5 * a1) * 1e4).astype("int16"), SDC.INT16, {"scale_factor": 1e-4, "add_offset": 0.0, "_FillValue": -9999}),
            "AOD_550_Dark_Target_Deep_Blue_Combined_Mean_Mean": (((0.1 + 0.3 * a1) * 1e3).astype("int16"), SDC.INT16, {"scale_factor": 1e-3, "add_offset": 0.0, "_FillValue": -9999}),
            "Atmospheric_Water_Vapor_Mean_Mean": (((3 - 2.5 * a1) * 1e3).astype("int16"), SDC.INT16, {"scale_factor": 1e-3, "add_offset": 0.0, "_FillValue": -9999})})
    pct = np.zeros((3600, 7200, 17), "uint8")
    terra = (np.abs(lat5) < 70) * np.ones((1, 7200))
    pct[:, :, 0] = (100 * (1 - terra)).astype("uint8")
    pct[:, :, 16] = (100 * terra * arid).astype("uint8")
    pct[:, :, 10] = (100 * terra * (1 - arid)).astype("uint8")
    hdf(B / "mcd12/MCD12C1.A2022001.061.x.hdf", {"Land_Cover_Type_1_Percent": (pct, SDC.UINT8, {})})
    # MERRA-2
    la = np.linspace(-90, 90, 361); lo = np.arange(576) * 0.625 - 180
    A = (np.abs(np.abs(la) - 25) < 8).astype(float)[:, None] * np.ones((1, 576))
    def nc(pasta, nome, vars_):
        p = B / pasta; p.mkdir(parents=True, exist_ok=True)
        xr.Dataset({k: (("time", "lat", "lon"), v[None].astype("float32")) for k, v in vars_.items()},
                   coords={"time": [0], "lat": la, "lon": lo}).to_netcdf(p / nome)
    for m in (1, 7):
        nc("merra_flx", f"M2.2023{m:02d}.nc4", {"SPEED": 3 + 4 * A, "SPEEDMAX": 10 + 5 * A, "PRECTOT": (1 - .99 * A) * 3e-5})
        nc("merra_slv", f"M2.2023{m:02d}.nc4", {"T2M": 290 + 8 * A, "QV2M": 0.012 - 0.01 * A, "PS": 95000 - 15000 * A})
        nc("merra_aer", f"M2.2023{m:02d}.nc4", {"DUSMASS": (5 + 120 * A) * 1e-9, "TOTEXTTAU": 0.1 + 0.3 * A})
        nc("oco2", f"oco2.2023{m:02d}.nc4", {"XCO2": np.full_like(A, 418e-6)})
    # coarse ETOPO (6'), same logic as the real one
    lae = np.linspace(-89.95, 89.95, 1800); loe = np.linspace(-179.95, 179.95, 3600)
    z = 500 + 1500 * rng.random((1800, 3600))
    z[np.abs(lae) > 70] = -3000
    (B / "etopo").mkdir(parents=True)
    xr.Dataset({"z": (("lat", "lon"), z.astype("float32"))}, coords={"lat": lae, "lon": loe}).to_netcdf(B / "etopo/etopo.nc")
    # coarse GHSL (0.1°) in a zip
    import rasterio
    from rasterio.transform import from_origin
    pop = np.where(rng.random((1800, 3600)) < 0.0005, 2e5, 1.0).astype("float32")
    (B / "ghsl").mkdir(parents=True)
    tif = B / "ghsl/pop.tif"
    with rasterio.open(tif, "w", driver="GTiff", width=3600, height=1800, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(-180, 90, 0.1, 0.1), nodata=-200) as d:
        d.write(pop, 1)
    with zipfile.ZipFile(B / "ghsl/pop.zip", "w") as zf:
        zf.write(tif, "pop.tif")
    tif.unlink()
    return B


def main():
    B = criar()
    import processar_grade as pg
    pg.BRUTOS = B
    pg.GRADE_PARQUET = TMP / "grade.parquet"
    pg.montar()
    import config, analise
    analise.GRADE_PARQUET = pg.GRADE_PARQUET
    df = analise.pontuar_todos(analise.carregar_grade())
    for p in analise.PERFIS:
        s = df[f"score_{p}"]
        print(f"{p:16s} valid={s.notna().sum():5d} mean={s.mean():.2f} max={s.max():.2f}")
    assert df["score_marte_planicie"].notna().sum() > 100
    # the synthetic desert (±25°) must beat the rest
    des = df[(df.lat.abs() - 25).abs() < 6]["score_marte_planicie"].mean()
    out = df[(df.lat.abs() - 25).abs() > 12]["score_marte_planicie"].mean()
    print("desert", round(des, 2), "vs outside", round(out, 2)); assert des > out

    # API
    with mock.patch.object(config, "GRADE_PARQUET", pg.GRADE_PARQUET):
        analise.GRADE_PARQUET = pg.GRADE_PARQUET
        from fastapi.testclient import TestClient
        import app.main as m
        m.GRADE = df
        m.contar_gbif = lambda lat, lon: {"registros_animais": 42, "nota": "mock"}
        c = TestClient(m.app)
        assert c.get("/").status_code == 200
        print("status", c.get("/api/status").json())
        cand = c.get("/api/candidatas?perfil=marte_planicie").json(); print("candidates", len(cand), cand[0])
        cel = c.get(f"/api/celula/{cand[0]['id']}?perfil=marte_planicie").json()
        print("analysis", [(i["variavel"], i["status"]) for i in cel["analise"]["itens"]])
        reg = c.get("/api/regiao?lat=25&lon=10&raio_km=500").json(); print("region n", reg["n"])
        print("known analogs", c.get("/api/conhecidos").json()[0])

        # feasibility with mocked external APIs
        horas = pd.date_range("2026-11-15", periods=16 * 24, freq="h")
        def falso_get(url, params=None, timeout=None):
            r = mock.Mock(status_code=200); r.raise_for_status = lambda: None
            if "air-quality" in url:
                r.json = lambda: {"hourly": {"time": horas[:120].strftime("%Y-%m-%dT%H:%M").tolist(),
                                             "dust": [20.0] * 120, "aerosol_optical_depth": [0.1] * 120}}
            elif "open-meteo" in url:
                n = len(horas); v = 5 + 8 * np.sin(np.arange(n) / 7)
                um = lambda: {"timezone": "Africa/Algiers", "utc_offset_seconds": 3600, "hourly": {
                    "time": horas.strftime("%Y-%m-%dT%H:%M").tolist(), "temperature_2m": [25.0] * n,
                    "relative_humidity_2m": [20.0] * n, "precipitation": [0.0] * n, "cloud_cover": [10.0] * n,
                    "visibility": [20000.0] * n, "wind_speed_10m": v.tolist(), "wind_gusts_10m": (v * 1.4).tolist(),
                    "wind_speed_180m": [None] * n}}
                k = str(params["latitude"]).count(",") + 1
                r.json = (lambda: [um() for _ in range(k)]) if k > 1 else um
            else:  # NASA POWER
                ano = params["start"][:4]
                t = pd.date_range(f"{ano}-01-01", f"{ano}-12-31 23:00", freq="h")
                k = t.strftime("%Y%m%d%H")
                ws = 4 + 6 * np.abs(np.sin(np.arange(len(t)) / 30))
                r.json = lambda: {"properties": {"parameter": {
                    "T2M": dict(zip(k, [22.0] * len(t))), "RH2M": dict(zip(k, [25.0] * len(t))),
                    "WS10M": dict(zip(k, ws)), "PRECTOTCORR": dict(zip(k, [0.0] * len(t))),
                    "ALLSKY_SFC_SW_DWN": dict(zip(k, [500.0] * len(t))), "CLRSKY_SFC_SW_DWN": dict(zip(k, [600.0] * len(t)))}}}
            return r
        import app.viabilidade as vb
        vb.CACHE = TMP
        with mock.patch.object(vb.requests, "get", falso_get):
            res = c.post("/api/viabilidade", json={"lat": 25.5, "lon": 10.5, "duracao_h": 3, "declividade_max_graus": 10}).json()
        p, h = res["previsao"], res["historico"]
        assert "erro" not in p, p; assert "erro" not in h, h
        print("forecast: windows", len(p["janelas"]), p["janelas"][:2], "ok%", p["horas_ok_pct"], "criteria", p["criterios"])
        print("history: best months", h["melhores_meses"], "jan 12h", h["matriz_pct"][0][12], "jan 0h", h["matriz_pct"][0][0])
        print("site", res["local"])
        with mock.patch.object(vb.requests, "get", falso_get):
            rp = c.post("/api/viabilidade/previsao", json={"lat": 25.5, "lon": 10.5}).json()
            rh = c.post("/api/viabilidade/historico", json={"lat": 25.5, "lon": 10.5}).json()
            pts = [{"id": f"p{i}", "lat": 20 + i, "lon": 10} for i in range(60)]
            rm = c.post("/api/viabilidade/mapa", json={"equipamento": {"lat": 25, "lon": 10}, "pontos": pts}).json()
        assert "erro" not in rp["previsao"] and "erro" not in rh["historico"], (rp, rh)
        print("split ok:", len(rp["previsao"]["janelas"]), "windows;", rh["historico"]["melhores_meses"])
        print("map:", len(rm["pontos"]), rm["pontos"][0], rm["arquivo"])
        cel2 = c.get(f"/api/celula/{cand[0]['id']}").json()["analise"]
        print("limits:", cel2["limitacoes_fixas"][0], cel2["limitacoes_metodo"][0]["fonte"])
        print("files", res["arquivos"])
        for a in res["arquivos"]:
            r = c.get(a); assert r.status_code == 200, a
        print("csv candidates", c.get("/api/export/candidatas.csv").status_code)
    shutil.rmtree(TMP)
    print("\nALL OK")


if __name__ == "__main__":
    main()
