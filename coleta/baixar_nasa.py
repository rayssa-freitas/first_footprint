"""
Downloads the NASA products (Earthdata) used in the global grid.

Requires a free account: https://urs.earthdata.nasa.gov
For MERRA-2 (GES DISC), approve the "NASA GESDISC DATA ARCHIVE" app
at: Earthdata Login > Applications > Authorized Apps.

Usage:
    python coleta/baixar_nasa.py            # all products
    python coleta/baixar_nasa.py MOD08_M3   # a single product
"""
import sys
import calendar
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import earthaccess
from config import ANO, MESES, BRUTOS

# short_name -> (folder, description, file name filter, monthly?)
PRODUTOS = {
    "MOD08_M3": ("mod08", "MODIS Terra atmosphere 1°: clouds, AOD, water vapour", ".061.", True),
    "MOD13C2": ("mod13", "MODIS monthly NDVI 0.05°", ".061.", True),
    "MOD11C3": ("mod11", "MODIS day/night land surface temperature 0.05°", ".061.", True),
    "MCD12C1": ("mcd12", "MODIS land cover (barren/ice/water) 0.05°", ".061.", False),
    "M2TMNXFLX": ("merra_flx", "MERRA-2 wind and precipitation", "", True),
    "M2TMNXSLV": ("merra_slv", "MERRA-2 air temperature, humidity, pressure", "", True),
    "M2TMNXAER": ("merra_aer", "MERRA-2 dust and aerosols", "", True),
}


def janela(mes):
    ult = calendar.monthrange(ANO, mes)[1]
    return (f"{ANO}-{mes:02d}-01", f"{ANO}-{mes:02d}-{ult}")


def baixar(short):
    pasta, desc, filtro, mensal = PRODUTOS[short]
    destino = BRUTOS / pasta
    destino.mkdir(parents=True, exist_ok=True)
    print(f"\n== {short}: {desc}")
    periodos = [janela(m) for m in MESES] if mensal else [(f"{ANO-1}-01-01", f"{ANO}-12-31")]
    for ini, fim in periodos:
        res = earthaccess.search_data(short_name=short, temporal=(ini, fim))
        if filtro:
            res = [r for r in res if filtro in str(r.data_links())]
        if not mensal:
            res = res[-1:]  # land cover: most recent only
        elif len(res) > 1:
            # ensure 1 granule per month: the one starting in the requested month
            certos = [r for r in res if _inicio(r).startswith(ini[:7])]
            res = certos[:1] or res[:1]
        if not res:
            print(f"  ! nothing found for {ini}..{fim}")
            continue
        earthaccess.download(res, local_path=str(destino))


def _inicio(granulo):
    try:
        return granulo["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"]
    except (KeyError, TypeError):
        return ""


if __name__ == "__main__":
    import os
    # order: environment variables -> .netrc/_netrc file in the user folder
    if os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD"):
        auth = earthaccess.login(strategy="environment")
    else:
        for nome in ("_netrc", ".netrc"):
            arq = Path.home() / nome
            if arq.exists():
                os.environ.setdefault("NETRC", str(arq))
                break
        auth = earthaccess.login(strategy="netrc")
    if not auth or not auth.authenticated:
        sys.exit("Login failed: create the _netrc file (see README) or check your username/password at urs.earthdata.nasa.gov.")
    print("Login Earthdata OK")
    alvos = sys.argv[1:] or list(PRODUTOS)
    falhas = []
    for s in alvos:
        try:
            baixar(s)
        except Exception as e:  # noqa — one failing product does not stop the others
            falhas.append(s)
            print(f"  ! ERROR in {s}: {type(e).__name__}")
            if "Eula" in type(e).__name__ or "eula" in str(e).lower():
                print("    -> approve the 'NASA GESDISC DATA ARCHIVE' app and accept the EULA on Earthdata:\n"
                      "       https://urs.earthdata.nasa.gov/profile  > Applications > Authorized Apps > Approve More Applications")
    if falhas:
        print("\nProducts with errors:", ", ".join(falhas))
        print("After fixing, run only those, e.g.: python coleta\\baixar_nasa.py " + " ".join(falhas))
    print("\nOK. Files in", BRUTOS)
