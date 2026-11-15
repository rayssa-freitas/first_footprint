"""
Downloads global layers that need no login:
- ETOPO 2022 60" (NOAA NCEI): elevation -> terrain, roughness, slope
- GHSL GHS-POP 2020 30" (European Commission/JRC): population

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
}


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
    print("downloading", dest.name, "(~450 MB, do not close the window)")
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


if __name__ == "__main__":
    for rel, url in ARQUIVOS.items():
        baixar(rel, url)
    print("OK")
