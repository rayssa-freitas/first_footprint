"""Central configuration of the First Footprint project."""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DADOS = RAIZ / "dados"
BRUTOS = DADOS / "brutos"          # downloaded files (HDF, NetCDF, TIF)
CACHE = DADOS / "cache"            # API responses (POWER, GBIF)
GRADE_PARQUET = DADOS / "grade.parquet"     # 1° grid with all variables
CELULAS_JSON = DADOS / "celulas.json"       # scored cells for the globe

# Reference year and months used for the climatology.
# 4 months (one per season) = download ~4x smaller than 12 months.
# For a final result, change to list(range(1, 13)).
ANO = 2023
MESES = [1, 4, 7, 10]

# Grid resolution (degrees). 1° = 180 x 360 cells.
RES = 1.0
NLAT, NLON = int(180 / RES), int(360 / RES)

# "Away from cities" pre-filter: mean population density
# in the cell's 3x3 neighbourhood (people/km²) below this value.
POP_VIZ_MAX = 5.0

# Protected areas (WDPA): cells with at least this % inside a protected area are
# removed from the candidates. None = only show a warning (NASA uses analogs inside
# parks, e.g. Death Valley National Park), which is the default.
PROTEGIDO_MAX = None

# How many candidate cells to send to the globe per profile
TOP_N_POR_PERFIL = 150

RESULTADOS = DADOS / "resultados"  # CSVs written by the app

# Serverless hosting (Vercel) has a read-only disk except /tmp:
# cache and result CSVs go there; the grid (grade.parquet) is only read.
SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("FF_SERVERLESS"))
if SERVERLESS:
    CACHE = Path("/tmp/ff_cache")
    RESULTADOS = Path("/tmp/ff_resultados")

for p in (BRUTOS, CACHE, RESULTADOS):
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:  # read-only disk: these folders are only needed for collection
        pass
