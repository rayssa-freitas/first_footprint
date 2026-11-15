"""
Quick QA for First Footprint: tests every API function with the server running.

Usage (with uvicorn running in another terminal):
    python tests\\qa.py
    python tests\\qa.py http://127.0.0.1:8000     (another address)

Uses real data (Open-Meteo, NASA POWER, GBIF): needs internet.
The first time, history takes ~1 min; it is cached afterwards.
"""
import sys
import time
import datetime as dt

import requests

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
SAARA = (25.5, 5.5)
EQ = {"nome": "QA Spot", "tipo": "rover", "lat": SAARA[0], "lon": SAARA[1], "vento_max_ms": 14,
      "rajada_max_ms": 18, "temp_min_c": -20, "temp_max_c": 45, "chuva_max_mm_h": 0.5,
      "nuvem_max_pct": None, "visibilidade_min_m": None, "luz_dia": True, "elev_solar_min_graus": 5,
      "duracao_h": 3, "perfil": "marte_planicie"}
resultados = []


def teste(nome, func):
    t0 = time.time()
    try:
        info = func()
        resultados.append(("OK", nome, time.time() - t0, info or ""))
    except AssertionError as e:
        resultados.append(("FAILED", nome, time.time() - t0, str(e)))
    except Exception as e:  # noqa
        resultados.append(("ERROR", nome, time.time() - t0, f"{type(e).__name__}: {e}"[:150]))
    s, n, t, i = resultados[-1]
    print(f"[{s:^6}] {n:<38} {t:5.1f}s  {i}")


def get(rota, **kw):
    r = requests.get(BASE + rota, timeout=180, **kw)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:120]}"
    return r


def post(rota, corpo):
    r = requests.post(BASE + rota, json=corpo, timeout=300)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:120]}"
    return r.json()


ESTADO = {}


def t_site():
    r = get("/")
    assert "First Footprint" in r.text, "old index.html (no First Footprint name)"
    js = get("/static/app.js").text
    v = js.split("VERSAO = '")[1].split("'")[0]
    assert "function processando" in js and "function concluido" in js, "app.js without the pop-ups"
    get("/static/favicon.svg")
    return f"app.js {v}"


def t_status():
    s = get("/api/status").json()
    ESTADO["grade"] = s.get("grade")
    if not s.get("grade"):
        return "NO GRID: candidates/cell/region will be skipped (" + s.get("msg", "") + ")"
    assert s["celulas"] > 1000, "too few cells in the grid"
    vaz = s.get("variaveis_vazias", [])
    return f"{s['celulas']} cells, {s['longe_cidades']} remote" + (f" | no data: {vaz}" if vaz else "")


def t_perfis():
    p = get("/api/perfis").json()
    assert len(p) >= 4, "expected 4 profiles"
    ESTADO["perfis"] = list(p)
    return ", ".join(p)


def t_candidatas():
    if not ESTADO.get("grade"):
        return "pulado (sem grade)"
    infos = []
    for pid in ESTADO["perfis"]:
        c = get("/api/candidatas", params={"perfil": pid, "n": 50}).json()
        assert c, f"profile {pid} has no candidates"
        notas = [x["score"] for x in c]
        assert notas == sorted(notas, reverse=True), f"{pid}: ranking out of order"
        assert all(0 <= n <= 1 for n in notas), f"{pid}: score outside 0..1"
        ESTADO.setdefault("cel", c[0]["id"])
        infos.append(f"{pid.split('_')[0]} top {notas[0]:.2f}")
    return " | ".join(infos)


def t_celula():
    if not ESTADO.get("grade"):
        return "pulado (sem grade)"
    d = get(f"/api/celula/{ESTADO['cel']}", params={"perfil": "marte_planicie"}).json()
    a = d["analise"]
    assert a["itens"], "empty analysis"
    assert all("fonte" in x for x in a["limitacoes_fixas"]), "limitation without a source"
    return f"{len(a['itens'])} variables · GBIF {d['fauna'].get('registros_animais')}"


def t_regiao():
    if not ESTADO.get("grade"):
        return "pulado (sem grade)"
    r = get("/api/regiao", params={"lat": -24.5, "lon": -68.5, "raio_km": 300}).json()
    assert r["n"] > 0, "Atacama region has no cells"
    return f"{r['n']} cells within 300 km (Atacama)"


def t_conhecidos():
    c = get("/api/conhecidos", params={"perfil": "marte_planicie"}).json()
    assert c, "known analogs list is empty"
    return f"{len(c)} agency analogs"


def t_equip():
    e = get("/api/equipamentos").json()
    assert e.get("equipamentos") and e.get("locais_terrestres"), "equipamentos.json incompleto"
    return f"{len(e['equipamentos'])} presets, {len(e['locais_terrestres'])} sites"


def t_previsao():
    r = post("/api/viabilidade/previsao", EQ)
    p = r["previsao"]
    assert "erro" not in p, p.get("erro")
    assert len(p["horas"]) >= 300, "forecast with too few hours"
    assert 0 <= p["horas_ok_pct"] <= 100
    assert r["arquivos"], "CSV not written"
    ESTADO["csv"] = r["arquivos"][0]
    return f"{len(p['janelas'])} windows, {p['horas_ok_pct']}% hours OK"


def t_climatologia():
    h = post("/api/viabilidade/historico", EQ)["historico"]
    assert "erro" not in h, h.get("erro")
    assert len(h["matriz_pct"]) == 12 and len(h["matriz_pct"][0]) == 24, "wrong month x hour matrix"
    return f"best months {h['melhores_meses']}"


def t_mapa():
    pts = [{"id": "a", "lat": 25.5, "lon": 5.5}, {"id": "b", "lat": -24.5, "lon": -68.5}, {"id": "c", "lat": -80.5, "lon": 78.5}]
    r = post("/api/viabilidade/mapa", {"equipamento": EQ, "pontos": pts})
    assert len(r["pontos"]) == 3, "map did not return the 3 points"
    return " | ".join(f"{p['id']}: {p['n_janelas']} win" for p in r["pontos"])


def t_limites():
    l = get("/api/simulacao/limites").json()
    fim = dt.date.fromisoformat(l["fim_disponivel"])
    assert (dt.date.today() - fim).days <= 5, "available end date too old"
    ESTADO["fim"] = fim
    return f"data up to {fim:%Y-%m-%d}"


def t_hist_periodo():
    fim = ESTADO.get("fim", dt.date.today() - dt.timedelta(days=3))
    ini = fim - dt.timedelta(days=13)
    r = post("/api/simulacao/historico", {"equipamento": EQ, "inicio": f"{ini}", "fim": f"{fim}"})
    assert r["dias"] >= 13, "period with too few days"
    assert len(r["tira"]["ok"]) >= 13 * 24 - 24, "incomplete hourly strip"
    assert len(r["arquivos"]) == 2
    return f"{r['dias_com_janela']}/{r['dias']} days with a window (14 days)"


def t_hist_invalido():
    r = requests.post(BASE + "/api/simulacao/historico", timeout=60,
                      json={"equipamento": EQ, "inicio": "2024-01-01", "fim": "2025-06-01"})
    assert r.status_code == 400, f"period > 366 days should return 400, got {r.status_code}"
    return "long period correctly refused"


def t_sorteio_hist():
    pts = [{"id": "1", "lat": 25.5, "lon": 5.5, "data": "2026-01-15"},
           {"id": "2", "lat": -80.5, "lon": 78.5, "data": "2026-02-01"},
           {"id": "3", "lat": 40.5, "lon": 92.5, "data": "2019-07-10"}]
    r = post("/api/simulacao/historico_lote", {"equipamento": EQ, "pontos": pts})["pontos"]
    erros = [p for p in r if "erro" in p]
    assert not erros, erros[0]["erro"]
    pol = r[1]
    assert pol["n_janelas"] == 0, "south pole should be infeasible for Spot (-20 °C)"
    return " | ".join(f"{p['id']}: {p['n_janelas']} win" for p in r)


def t_csvs():
    if not ESTADO.get("grade"):
        get(ESTADO["csv"])
        return "forecast CSV OK (candidates skipped: no grid)"
    r = get("/api/export/candidatas.csv", params={"perfil": "marte_planicie"})
    assert r.content[:3] == b"\xef\xbb\xbf" and b";" in r.content[:200], "CSV not in Excel (pt-BR) format"
    get(ESTADO["csv"])
    return "candidates + forecast downloaded"


print(f"\nQA First Footprint → {BASE}\n" + "-" * 70)
try:
    requests.get(BASE + "/api/status", timeout=5)
except Exception:
    sys.exit("Server not responding. Start it first:  uvicorn app.main:app --reload")

for nome, f in [("Site (index, app.js, favicon)", t_site), ("Grid status", t_status), ("Profiles", t_perfis),
                ("Candidates per profile", t_candidatas), ("Cell analysis + GBIF", t_celula),
                ("Mark region", t_regiao), ("Known analogs", t_conhecidos), ("Equipment presets", t_equip),
                ("16-day forecast", t_previsao), ("NASA POWER climatology", t_climatologia),
                ("Map feasibility (batch)", t_mapa), ("History limit", t_limites),
                ("Historical simulation (14 days)", t_hist_periodo), ("Period validation", t_hist_invalido),
                ("Historical random draw (3 points)", t_sorteio_hist), ("Downloads CSV", t_csvs)]:
    teste(nome, f)

ok = sum(r[0] == "OK" for r in resultados)
print("-" * 70 + f"\n{ok}/{len(resultados)} OK")
sys.exit(0 if ok == len(resultados) else 1)
