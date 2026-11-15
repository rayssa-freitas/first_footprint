# First Footprint – Earth analogs for the Moon and Mars (NASA Space Apps Challenge 2026)

*Every giant leap starts on Earth.*

An interactive globe that:

1. scans the Earth in 1° cells and scores how similar each one is to 4 lunar/martian environments;
2. explains, variable by variable, where the analogy holds and where it fails, with scientific sources;
3. pre-marks candidate regions away from cities with octagons;
4. checks, for a given piece of equipment (drone, robot, launcher, lander), on which days and hours a field test is feasible — using the 16-day forecast and real hourly history since 2001.

## Software
- **Python 3.12** (on Windows, avoid 3.13: `pyhdf` has no ready-made wheel)
- **A modern browser** (Chrome/Edge/Firefox) — the globe uses `globe.gl` from a CDN (needs internet)
- A free **NASA Earthdata** account: https://urs.earthdata.nasa.gov
- Libraries: `requirements.txt` = website/API only; `requirements-data.txt` = everything, including the data collection (xarray, pyhdf, rasterio, earthaccess…)
- ~3 GB of free disk space (4 months of data). With 12 months, ~7 GB.

## Run (step by step)

```bash
# 1) environment
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1     Linux/Mac: source .venv/bin/activate
pip install -r requirements-data.txt   # or requirements.txt if you only run the website

# 2) Earthdata: create the account and, under "Applications > Authorized Apps",
#    approve "NASA GESDISC DATA ARCHIVE" (required for MERRA-2)
#    Login is automatic through a _netrc / .netrc file in your user folder:
#    machine urs.earthdata.nasa.gov login <user> password <password>

# 3) data collection (once)
python coleta/baixar_nasa.py
python coleta/baixar_externos.py

# 4) processing -> dados/grade.parquet (once, or after downloading new data)
python processamento/processar_grade.py

# 5) website
uvicorn app.main:app --reload
# open http://127.0.0.1:8000
```

The **Simulation** tab works even without steps 3–4 (it uses live APIs): just type a lat/lon.

## Deploy online (Vercel)
The repo is ready for Vercel: `index.py` exposes the app, `requirements.txt` has only the web dependencies and `vercel.json` sets a 300 s limit. Commit `dados/grade.parquet`, import the GitHub repo at vercel.com/new and deploy. On Vercel, cache and result CSVs go to `/tmp` (temporary).

## Tests
- `python tests/qa.py` — with the server running: 16 checks of every API function using real data. Expected: `16/16 OK`.
- `python tests/teste_sintetico.py` — tests the whole pipeline with fake files in a temporary folder, no download needed. Expected: `ALL OK`.

## How to use
- **Profile**: Mars arid plain, Mars periglacial, Moon south pole, Moon basaltic mare.
- **Candidates tab**: the 150 best cells away from cities. Color is relative to the cells shown (dark red = lowest, white = highest; the legend shows the real numbers). Blue labels = analogs agencies already use.
- **Mark region**: tick it, set the radius and click the globe → ranking of the cells inside.
- **Simulation tab**:
  - pick a real equipment preset (DJI Matrice 350 RTK, Boston Dynamics Spot, SpaceX Falcon 9, Astrobotic Xodiac) or type your own limits;
  - **16-day forecast**: operating windows + month × hour climatology, and the candidates on the map are colored by feasibility;
  - **History**: any period since 2001, hour by hour;
  - **Random draw**: up to 40 random tests across sites, equipment and real days.
- Every run shows a *Processing → Complete* pop-up and writes CSVs (with English column names) to `dados/resultados`.
- Accessibility: full keyboard use, screen-reader announcements, colour-blind-safe colors, visual-only feedback (no sound needed) and a responsive layout for phones and tablets.

## Data

| Variable | Product | Source |
|---|---|---|
| Vegetation (NDVI) | MOD13C2 | NASA LP DAAC (Earthdata) |
| Day/night land surface temperature, range | MOD11C3 | NASA LP DAAC (Earthdata) |
| Clouds, aerosols (AOD), water vapour | MOD08_M3 | NASA LAADS (Earthdata) |
| Barren soil / ice / land mask | MCD12C1 | NASA LP DAAC (Earthdata) |
| Wind, precipitation | MERRA-2 M2TMNXFLX | NASA GES DISC (Earthdata) |
| Air temperature, relative humidity, pressure | MERRA-2 M2TMNXSLV | NASA GES DISC (Earthdata) |
| Dust | MERRA-2 M2TMNXAER | NASA GES DISC (Earthdata) |
| Elevation, slope, roughness | ETOPO 2022 60" | NOAA NCEI |
| Population | GHSL GHS-POP 2020 | European Commission (JRC) |
| Geology (basalt, sediments, evaporites) | GLiM 0.5° (Hartmann & Moosdorf 2012) | PANGAEA, CC-BY 3.0 |
| Protected areas (warning) | WDPA | UNEP-WCMC & IUCN, Protected Planet |
| Wildlife (records) | GBIF API | GBIF |
| Livestock (optional) | FAO GLW | FAO — download manually to `dados/brutos/glw/*.tif` |
| 16-day hourly forecast | Open-Meteo (ECMWF, GFS, ICON) | weather services |
| Forecast dust/AOD (5 days) | CAMS via Open-Meteo | Copernicus |
| Hourly history since 2001 | NASA POWER (MERRA-2/CERES) | NASA LaRC |
| Moon/Mars references | NSSDC Fact Sheets, LRO Diviner/LOLA/LEND, MSL REMS, MGS TES | NASA/PDS |
| Globe texture | Blue Marble | NASA |

## Limitations
- 1° grid (~110 km): good for global screening, not for picking the exact landing spot. Local detail → 30 m DEM and a field visit.
- Moon/Mars references are published values (fact sheets, Diviner etc.), not processed PDS files.
- **CO₂ is not in the model**: it varies only a few ppm across Earth (NOAA GML), so it does not distinguish analogs; Mars is ~95% CO₂.
- Geology comes from GLiM at 0.5° (dominant rock type per pixel). Detailed mineralogy (ASTER/EMIT) is a next step.
- Protected areas (WDPA) are shown as a warning; set `PROTEGIDO_MAX` in config.py to exclude them. Military areas and indigenous lands are not covered.
- GBIF counts records (sampling bias), not animal density.
- Gravity, vacuum, Martian pressure and radiation cannot be reproduced on Earth.
- Hourly history has no gust, visibility or dust; those only apply to the forecast.
- Some equipment limits are not published by the manufacturer; each preset lists what was estimated.

## Structure
```
config.py                          year, months, resolution, population threshold
coleta/baixar_nasa.py              Earthdata download (earthaccess)
coleta/baixar_externos.py          ETOPO + GHSL download
processamento/processar_grade.py   raw files -> 1° grid
processamento/analise.py           similarity per profile (+ ranking CSV)
dados/referencias_planetarias.json Moon/Mars profiles (edit weights and limits here)
dados/analogos_conhecidos.json     Atacama, Mojave, Haughton... (validation)
dados/equipamentos.json            real equipment presets and favorable Earth sites
app/main.py                        FastAPI API + CSV export
app/viabilidade.py                 equipment rules, forecast and history
app/static/                        website (globe.gl, app.js, style.css)
tests/                             qa.py (live API) and teste_sintetico.py (offline)
```

Folder and file names are kept in Portuguese (the original working language of the team); everything the user sees is in English.

Validation: the known analogs (blue labels) should score high in the matching profile. Atacama comes out #1 in the Mars arid-plain profile (0.83).
