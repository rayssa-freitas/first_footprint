"""
Downloads global layers that need no login:
- ETOPO 2022 60" (NOAA NCEI): elevation -> terrain, roughness, slope
- GHSL GHS-POP 2020 30" (European Commission/JRC): population
- GLiM 0.5° (Hartmann & Moosdorf 2012, PANGAEA, CC-BY 3.0): rock types (geology)
- WDPA (UNEP-WCMC & IUCN, Protected Planet): protected areas — large (~1-2 GB);
  if the automatic download fails, download the shapefile manually from
  https://www.protectedplanet.net/en/thematic-areas/wdpa and put the .zip in dados/brutos/wdpa/

Usage: python coleta/baixar_externos.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from config import BRUTOS

ARQUIVOS = {
    "etopo/ETOPO_2022_v1_60s_N90W180_surface.nc":
        "https://www.ngdc.noaa.gov/thredds/fileServer/global/ETOPO2022/60s/"
        "60s_surface_elev_netcdf/ETOPO_2022_v1_60s_N90W180_surface.nc",
    "ghsl/GHS_POP_E2020_GLOBE_R2023A_4326_30ss_V1_0.zip":
        "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/"
        "GHS_POP_E2020_GLOBE_R2023A_4326_30ss/V1-0/GHS_POP_E2020_GLOBE_R2023A_4326_30ss_V1_0.zip",
    "glim/glim_0.5deg.zip": "https://hdl.handle.net/10013/epic.39939.d001",
}
WDPA_URL = "https://d1gam3xoknrgr2.cloudfront.net/current/WDPA_{mes}{ano}_Public_shp.zip"
MESES_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def arquivo_ok(caminho):
    """Checks that the file opens (catches interrupted downloads)."""
    try:
        if caminho.suffix == ".nc":
            import netCDF4
            netCDF4.Dataset(str(caminho)).close()
        elif caminho.suffix == ".zip":
            import zipfile
            with zipfile.ZipFile(caminho) as z:
                z.namelist()
        return True
    except Exception:  # noqa
        return False


def baixar(rel, url):
    dest = BRUTOS / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and arquivo_ok(dest):
        print("already present and intact:", dest.name)
        return
    if dest.exists():
        print("incomplete/corrupted file, downloading again:", dest.name)
        dest.unlink()
    print("downloading", dest.name, "(may be large, do not close the window)")
    parcial = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        feito = 0
        with open(parcial, "wb") as f:
            for bloco in r.iter_content(1 << 20):
                f.write(bloco)
                feito += len(bloco)
                tot = f"/{total/1e6:.0f}" if total else ""
                print(f"\r  {feito/1e6:.0f}{tot} MB", end="", flush=True)
    parcial.replace(dest)
    print("  done")


def baixar_wdpa():
    """WDPA changes name every month: tries this month and the two before."""
    pasta = BRUTOS / "wdpa"
    existentes = [f for ext in ("*.zip", "*.shp", "*.gpkg") for f in pasta.glob(ext)]
    if existentes and all(arquivo_ok(f) for f in existentes if f.suffix == ".zip"):
        print("already present: WDPA")
        return
    import datetime as dt
    hoje = dt.date.today().replace(day=1)
    for k in range(3):
        d = (hoje - dt.timedelta(days=28 * k)).replace(day=1)
        url = WDPA_URL.format(mes=MESES_EN[d.month - 1], ano=d.year)
        try:
            if requests.head(url, timeout=30, allow_redirects=True).status_code == 200:
                baixar(f"wdpa/{url.rsplit('/', 1)[1]}", url)
                return
        except Exception:  # noqa
            pass
    print("  ! WDPA: automatic download not available. Download the shapefile at\n"
          "    https://www.protectedplanet.net/en/thematic-areas/wdpa (Download > SHP)\n"
          "    and save the .zip in", pasta)


if __name__ == "__main__":
    for rel, url in ARQUIVOS.items():
        try:
            baixar(rel, url)
        except Exception as e:  # noqa — one failing layer does not stop the others
            print(f"\n  ! ERROR downloading {rel}: {type(e).__name__}: {e}")
    baixar_wdpa()
    print("OK")
