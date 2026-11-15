"""
Turns the raw files into a global 1° grid (180 x 360).
Each cell gets every environmental variable. Output: dados/grade.parquet

Convention: row 0 = latitude 89.5 (north), column 0 = longitude -179.5.
Missing files become empty (NaN) columns with a warning — the rest carries on.

Usage: python processamento/processar_grade.py
"""
import sys
import glob
import zipfile
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from config import BRUTOS, GRADE_PARQUET, NLAT, NLON, RES

warnings.filterwarnings("ignore", category=RuntimeWarning)
LATS = 90 - RES / 2 - np.arange(NLAT) * RES
LONS = -180 + RES / 2 + np.arange(NLON) * RES


def vazio():
    return np.full((NLAT, NLON), np.nan, dtype="float32")


def blocos(arr, fator, func=np.nanmean):
    """Aggregates an (NLAT*f, NLON*f) matrix into (NLAT, NLON)."""
    a = arr.reshape(NLAT, fator, NLON, fator)
    return func(func(a, axis=3), axis=1)


def arquivos(pasta, padrao="*"):
    fs = sorted(glob.glob(str(BRUTOS / pasta / padrao)))
    if not fs:
        print(f"  ! no files in brutos/{pasta} — those variables will be empty")
    return fs


# ---------------- MODIS (HDF4) ----------------
def ler_sds(caminho, nome):
    from pyhdf.SD import SD, SDC
    hdf = SD(caminho, SDC.READ)
    sds = hdf.select(nome)
    raw = sds.get().astype("float64")
    at = sds.attributes()
    fill = at.get("_FillValue")
    vr = at.get("valid_range")
    mask = np.zeros(raw.shape, bool)
    if fill is not None:
        mask |= raw == fill
    if vr is not None:
        mask |= (raw < vr[0]) | (raw > vr[1])
    raw[mask] = np.nan
    hdf.end()
    return raw, at


def mod08():
    """Clouds, AOD 550 nm and water vapour (MODIS Terra L3 1°)."""
    print("MOD08_M3 (clouds, AOD, vapour)")
    campos = {
        "nuvem_frac": "Cloud_Fraction_Mean_Mean",
        "aod_550": "AOD_550_Dark_Target_Deep_Blue_Combined_Mean_Mean",
        "vapor_agua_cm": "Atmospheric_Water_Vapor_Mean_Mean",
    }
    acum = {k: [] for k in campos}
    for f in arquivos("mod08", "*.hdf"):
        for k, sds in campos.items():
            try:
                raw, at = ler_sds(f, sds)
                acum[k].append(at.get("scale_factor", 1) * (raw - at.get("add_offset", 0)))
            except Exception as e:  # noqa
                print(f"  ! {sds}: {e}")
    return {k: (np.nanmean(v, axis=0) if v else vazio()) for k, v in acum.items()}


def mod13():
    print("MOD13C2 (NDVI)")
    meses = []
    for f in arquivos("mod13", "*.hdf"):
        raw, _ = ler_sds(f, "CMG 0.05 Deg Monthly NDVI")
        meses.append(blocos(raw * 1e-4, 20))
    if not meses:
        return {"ndvi_medio": vazio(), "ndvi_max": vazio()}
    return {"ndvi_medio": np.nanmean(meses, axis=0), "ndvi_max": np.nanmax(meses, axis=0)}


def mod11():
    print("MOD11C3 (day/night land surface temperature)")
    dia, noite = [], []
    for f in arquivos("mod11", "*.hdf"):
        d, _ = ler_sds(f, "LST_Day_CMG")
        n, _ = ler_sds(f, "LST_Night_CMG")
        dia.append(blocos(d * 0.02 - 273.15, 20))
        noite.append(blocos(n * 0.02 - 273.15, 20))
    if not dia:
        return {k: vazio() for k in ("lst_dia_c", "lst_noite_c", "amplitude_termica_c", "lst_max_c", "lst_min_c")}
    dia, noite = np.array(dia), np.array(noite)
    return {
        "lst_dia_c": np.nanmean(dia, axis=0),
        "lst_noite_c": np.nanmean(noite, axis=0),
        "amplitude_termica_c": np.nanmean(dia - noite, axis=0),
        "lst_max_c": np.nanmax(dia, axis=0),
        "lst_min_c": np.nanmin(noite, axis=0),
    }


def mcd12():
    """% land, barren soil (IGBP 16) and snow/ice (IGBP 15)."""
    print("MCD12C1 (land cover)")
    fs = arquivos("mcd12", "*.hdf")
    if not fs:
        return {"terra_pct": vazio(), "arido_pct": vazio(), "gelo_pct": vazio()}
    from pyhdf.SD import SD, SDC
    hdf = SD(fs[-1], SDC.READ)
    pct = hdf.select("Land_Cover_Type_1_Percent").get()  # (3600, 7200, 17) in %
    hdf.end()
    out = {
        "terra_pct": blocos(100 - pct[:, :, 0].astype("float32"), 20),
        "gelo_pct": blocos(pct[:, :, 15].astype("float32"), 20),
        "arido_pct": blocos(pct[:, :, 16].astype("float32"), 20),
    }
    return out


# ---------------- MERRA-2 (NetCDF) ----------------
def para_grade(da):
    """Samples any lat/lon field at the 1° grid centres (nearest neighbour)."""
    da = da.squeeze()
    latn = [c for c in da.dims if c.lower().startswith("lat")][0]
    lonn = [c for c in da.dims if c.lower().startswith("lon")][0]
    v = da.sel({latn: LATS, lonn: LONS}, method="nearest")
    v = v.transpose(latn, lonn).values.astype("float32")
    return v


def media_nc(pasta, var, conv=lambda x: x, func=np.nanmean):
    import xarray as xr
    campos = []
    for f in arquivos(pasta, "*.nc4"):
        with xr.open_dataset(f) as ds:
            if var not in ds:
                print(f"  ! {var} missing in {Path(f).name}")
                continue
            campos.append(conv(para_grade(ds[var])))
    return func(campos, axis=0) if campos else vazio()


def merra():
    print("MERRA-2 (wind, rain, air, dust)")
    out = {
        "vento_medio_ms": media_nc("merra_flx", "SPEED"),
        "vento_max_ms": media_nc("merra_flx", "SPEEDMAX", func=np.nanmax),
        "precip_mm_ano": media_nc("merra_flx", "PRECTOT", lambda x: x * 86400 * 365),
        "t2m_c": media_nc("merra_slv", "T2M", lambda x: x - 273.15),
        "poeira_ugm3": media_nc("merra_aer", "DUSMASS", lambda x: x * 1e9),
        "aerossol_ext_tau": media_nc("merra_aer", "TOTEXTTAU"),
    }
    q = media_nc("merra_slv", "QV2M")
    ps = media_nc("merra_slv", "PS")
    t = out["t2m_c"]
    e = q * ps / (0.622 + 0.378 * q)
    es = 611.2 * np.exp(17.67 * t / (t + 243.5))
    out["umidade_rel_pct"] = np.clip(100 * e / es, 0, 100)
    out["pressao_hpa"] = ps / 100
    return out


# ---------------- Terrain (ETOPO 2022) ----------------
def etopo():
    print("ETOPO 2022 (elevation, roughness, slope)")
    fs = arquivos("etopo", "*.nc")
    nomes = ("elev_m", "rugosidade_m", "declividade_graus")
    if not fs:
        return {k: vazio() for k in nomes}
    import xarray as xr
    ds = xr.open_dataset(fs[0])
    z = ds["z"]
    latn = [c for c in z.dims if c.lower().startswith("lat")][0]
    lats = ds[latn].values
    fator = int(round(RES / abs(lats[1] - lats[0])))  # 60 for 60"
    norte_primeiro = lats[0] > lats[-1]
    res = {k: vazio() for k in nomes}
    passo_m = 1852.0 * 60.0 / fator  # pixel size in metres (1' of arc ≈ 1852 m)
    for i in range(NLAT):
        a = i * fator if norte_primeiro else (NLAT - 1 - i) * fator
        banda = z.isel({latn: slice(a, a + fator)}).values.astype("float32")
        if not norte_primeiro:
            banda = banda[::-1]
        banda = banda[:, : NLON * fator]
        banda[banda < -450] = np.nan  # drop the ocean (Dead Sea ≈ -430 m)
        lat_c = LATS[i]
        dx = passo_m * max(np.cos(np.radians(lat_c)), 0.01)
        gy, gx = np.gradient(banda, passo_m, dx)
        decl = np.degrees(np.arctan(np.hypot(gx, gy)))
        b = banda.reshape(fator, NLON, fator)
        res["elev_m"][i] = np.nanmean(np.nanmean(b, axis=2), axis=0)
        res["rugosidade_m"][i] = np.nanstd(b.transpose(1, 0, 2).reshape(NLON, -1), axis=1)
        res["declividade_graus"][i] = np.nanmean(decl.reshape(fator, NLON, fator).transpose(1, 0, 2).reshape(NLON, -1), axis=1)
    ds.close()
    return res


# ---------------- Population (GHSL) ----------------
AREA_KM2 = (111.32 ** 2) * np.cos(np.radians(LATS))[:, None] * RES ** 2 * np.ones((1, NLON))


def vizinhanca(soma):
    """Mean density in the 3x3 window (longitude wraps around the globe)."""
    vp = sum(np.roll(np.roll(soma, di, 0), dj, 1) for di in (-1, 0, 1) for dj in (-1, 0, 1))
    va = sum(np.roll(np.roll(AREA_KM2, di, 0), dj, 1) for di in (-1, 0, 1) for dj in (-1, 0, 1))
    return vp / va


def ghsl():
    print("GHSL (population)")
    fs = arquivos("ghsl", "*.zip")
    if not fs:
        return {"pop_total": vazio(), "pop_dens_km2": vazio(), "pop_viz_km2": vazio()}
    tif = [n for n in zipfile.ZipFile(fs[0]).namelist() if n.endswith(".tif")][0]
    soma = somar_raster(f"/vsizip/{Path(fs[0]).resolve().as_posix()}/{tif}")
    return {"pop_total": soma, "pop_dens_km2": soma / AREA_KM2, "pop_viz_km2": vizinhanca(soma)}


def rebanhos():
    """Optional: FAO GLW rasters (head of livestock per pixel) placed in brutos/glw/*.tif."""
    fs = sorted(glob.glob(str(BRUTOS / "glw" / "*.tif")))
    if not fs:
        print("GLW (livestock): optional, no files — skipping")
        return {"rebanho_dens_km2": vazio()}
    print("GLW (livestock):", ", ".join(Path(f).stem for f in fs))
    total = sum(somar_raster(f) for f in fs)
    return {"rebanho_dens_km2": total / AREA_KM2}


def somar_raster(caminho):
    """Sums a WGS84 raster (counts per pixel) inside each 1° cell."""
    import rasterio
    from rasterio.windows import Window
    soma = np.zeros((NLAT, NLON), "float64")
    with rasterio.open(caminho) as src:
        T = src.transform
        nod = src.nodata
        passo = 240
        cols = np.arange(src.width)
        lon_c = T.c + (cols + 0.5) * T.a
        jj = np.clip(((lon_c + 180) / RES).astype(int), 0, NLON - 1)
        for r0 in range(0, src.height, passo):
            h = min(passo, src.height - r0)
            v = src.read(1, window=Window(0, r0, src.width, h)).astype("float64")
            if nod is not None:
                v[v == nod] = 0
            v[v < 0] = 0
            lat_c = T.f + (np.arange(r0, r0 + h) + 0.5) * T.e
            ii = np.clip(((90 - lat_c) / RES).astype(int), 0, NLAT - 1)
            v[~np.isfinite(v)] = 0
            # sum per cell: bincount is much faster than add.at
            idx = (ii[:, None] * NLON + jj[None, :]).ravel()
            soma += np.bincount(idx, weights=v.ravel(), minlength=NLAT * NLON).reshape(NLAT, NLON)
    return soma


# ---------------- Geology (GLiM 0.5°) ----------------
# GLiM first-level classes (Hartmann & Moosdorf 2012). The code number of each class
# is read from the legend inside the zip when there is one; otherwise this default is used.
GLIM_PADRAO = {"su": 1, "vb": 2, "ss": 3, "pb": 4, "sm": 5, "sc": 6, "va": 7, "mt": 8,
               "pa": 9, "vi": 10, "wb": 11, "py": 12, "pi": 13, "ev": 14, "nd": 15, "ig": 16}
GLIM_NOMES = {"su": "unconsolidated sediments", "vb": "basic volcanic (basalt)", "ss": "siliciclastic sedimentary",
              "pb": "basic plutonic", "sm": "mixed sedimentary", "sc": "carbonate sedimentary",
              "va": "acid volcanic", "mt": "metamorphic", "pa": "acid plutonic", "vi": "intermediate volcanic",
              "wb": "water", "py": "pyroclastics", "pi": "intermediate plutonic", "ev": "evaporites",
              "nd": "no data", "ig": "ice and glaciers"}


def _legenda_glim(z):
    """Looks for a 'code + abbreviation' legend in the zip text files."""
    import re
    leg = {}
    for n in z.namelist():
        if n.lower().endswith((".txt", ".csv", ".dat", ".xml")) and z.getinfo(n).file_size < 200_000:
            txt = z.read(n).decode("latin-1", errors="ignore")
            for a, b in re.findall(r"\b(\d{1,2})\s*[=:;,\t ]\s*([a-z]{2})\b", txt):
                if b in GLIM_PADRAO:
                    leg[b] = int(a)
            for b, a in re.findall(r"\b([a-z]{2})\s*[=:;,\t ]\s*(\d{1,2})\b", txt):
                if b in GLIM_PADRAO and b not in leg:
                    leg[b] = int(a)
    return leg if len(leg) >= 10 else {}


def glim():
    """% of each 1° cell covered by basalt, sediments and evaporites (dominant class of each 0.5° pixel)."""
    print("GLiM (geology / rock types)")
    nomes = ("basalto_pct", "sedimento_pct", "evaporito_pct", "vulcanica_pct")
    fs = arquivos("glim", "*.zip") or arquivos("glim", "*.asc") or arquivos("glim", "*.tif")
    if not fs:
        return {k: vazio() for k in nomes}
    import rasterio
    caminho, leg = fs[0], {}
    if fs[0].endswith(".zip"):
        with zipfile.ZipFile(fs[0]) as z:
            ras = [n for n in z.namelist() if n.lower().endswith((".asc", ".tif", ".tiff", ".flt", ".adf", ".nc"))]
            if not ras:
                print("  ! no raster inside the GLiM zip:", z.namelist()[:10])
                return {k: vazio() for k in nomes}
            leg = _legenda_glim(z)
        caminho = f"/vsizip/{Path(fs[0]).resolve().as_posix()}/{ras[0]}"
    cod = leg or GLIM_PADRAO
    print("  legend used:", "from the zip" if leg else "default (check it against the GLiM documentation)",
          {k: cod[k] for k in ("su", "vb", "ss", "sm", "ev", "va", "vi", "py")})
    with rasterio.open(caminho) as src:
        v = src.read(1)
        T = src.transform
        nod = src.nodata
    lat_c = T.f + (np.arange(v.shape[0]) + 0.5) * T.e
    lon_c = T.c + (np.arange(v.shape[1]) + 0.5) * T.a
    ii = np.clip(((90 - lat_c) / RES).astype(int), 0, NLAT - 1)
    jj = np.clip(((lon_c + 180) / RES).astype(int), 0, NLON - 1)
    idx = (ii[:, None] * NLON + jj[None, :]).ravel()
    v = v.ravel()
    valido = (v != nod) if nod is not None else np.ones_like(v, bool)
    valido &= (v != cod["wb"]) & (v != cod["nd"]) & (v > 0)
    total = np.bincount(idx[valido], minlength=NLAT * NLON).reshape(NLAT, NLON).astype("float32")
    total[total == 0] = np.nan

    def pct(*classes):
        m = valido & np.isin(v, [cod[c] for c in classes])
        return 100 * np.bincount(idx[m], minlength=NLAT * NLON).reshape(NLAT, NLON) / total

    return {"basalto_pct": pct("vb"), "sedimento_pct": pct("su", "ss", "sm"),
            "evaporito_pct": pct("ev"), "vulcanica_pct": pct("vb", "va", "vi", "py")}


# ---------------- Protected areas (WDPA) ----------------
def _camadas_wdpa():
    """Paths (GDAL syntax) of every polygon layer of the WDPA, inside zips or loose."""
    pasta = BRUTOS / "wdpa"
    out = [f.resolve().as_posix() for ext in ("*.shp", "*.gpkg") for f in pasta.glob(ext)
           if "point" not in f.name.lower()]
    for z in pasta.glob("*.zip"):
        zp = z.resolve().as_posix()
        with zipfile.ZipFile(z) as zz:
            for n in zz.namelist():
                low = n.lower()
                if low.endswith(".shp") and "point" not in low:
                    out.append(f"/vsizip/{zp}/{n}")
                elif low.endswith(".zip"):  # Protected Planet ships 3 zips inside the zip
                    import io
                    with zipfile.ZipFile(io.BytesIO(zz.read(n))) as inner:
                        for m in inner.namelist():
                            if m.lower().endswith(".shp") and "point" not in m.lower():
                                out.append(f"/vsizip/{{/vsizip/{zp}/{n}}}/{m}")
    return out


def wdpa():
    """% of each 1° cell inside a protected area (rasterized at 0.05°)."""
    print("WDPA (protected areas)")
    camadas = _camadas_wdpa() if (BRUTOS / "wdpa").exists() else []
    if not camadas:
        print("  ! no files in brutos/wdpa — protected-area layer will be empty")
        return {"protegido_pct": vazio()}
    import fiona
    from rasterio import features
    from rasterio.transform import from_origin
    fator = 20
    grade = np.zeros((NLAT * fator, NLON * fator), dtype="uint8")
    T = from_origin(-180, 90, RES / fator, RES / fator)
    n = 0
    for cam in camadas:
        with fiona.open(cam) as src:
            lote = []
            for feat in src:
                pr = feat["properties"]
                if str(pr.get("STATUS", "")).lower() == "proposed" or str(pr.get("MARINE", "0")) == "2":
                    continue
                if feat["geometry"] is None:
                    continue
                lote.append((feat["geometry"], 1))
                if len(lote) >= 5000:
                    features.rasterize(lote, out=grade, transform=T)
                    n += len(lote)
                    lote = []
            if lote:
                features.rasterize(lote, out=grade, transform=T)
                n += len(lote)
        print(f"  {n} areas so far ({Path(cam).name})")
    return {"protegido_pct": 100 * blocos(grade.astype("float32"), fator)}


def montar():
    camadas = {}
    for f in (mcd12, mod08, mod13, mod11, merra, etopo, ghsl, rebanhos, glim, wdpa):
        try:
            camadas.update(f())
        except Exception as e:  # noqa — one failing layer does not break the grid
            print(f"  ! ERROR in layer {f.__name__}: {type(e).__name__}: {e}")
            print(f"    carrying on without it. If a file is corrupted, delete the dados\\brutos\\{f.__name__} folder and download again.")
    ii, jj = np.meshgrid(np.arange(NLAT), np.arange(NLON), indexing="ij")
    df = pd.DataFrame({
        "id": [f"{a}_{b}" for a, b in zip(ii.ravel(), jj.ravel())],
        "lat": LATS[ii.ravel()], "lon": LONS[jj.ravel()],
    })
    for k, v in camadas.items():
        df[k] = np.asarray(v, dtype="float32").ravel()
    # keep only land cells (or all, if no mask is available)
    tem = lambda c: c in df and df[c].notna().any()
    if tem("terra_pct"):
        df = df[df["terra_pct"] >= 50]
    elif tem("elev_m"):
        df = df[df["elev_m"] > 0]
    df.to_parquet(GRADE_PARQUET, index=False)
    print(f"\nOK: {len(df)} land cells -> {GRADE_PARQUET}")
    print(df.describe().T[["count", "mean", "min", "max"]].round(2).to_string())


if __name__ == "__main__":
    montar()
