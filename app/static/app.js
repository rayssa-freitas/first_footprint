const VERSAO = 'v18';
// ---------- utilities ----------
const $ = (s) => document.querySelector(s);
const api = async (url, opt) => {
  const r = await fetch(url, opt);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
};
const MESES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
// English labels for the grid variables shown in the analysis
const VAR_EN = { ndvi_max: 'max NDVI (vegetation)', ndvi_medio: 'mean NDVI', precip_mm_ano: 'rain (mm/year)', umidade_rel_pct: 'relative humidity (%)',
  vapor_agua_cm: 'water vapour (cm)', amplitude_termica_c: 'day–night temperature range (°C)', lst_min_c: 'min surface temperature (°C)',
  lst_dia_c: 'day surface temperature (°C)', lst_noite_c: 'night surface temperature (°C)', arido_pct: 'barren land (%)', poeira_ugm3: 'dust (µg/m³)',
  nuvem_frac: 'cloud fraction', pressao_hpa: 'pressure (hPa)', t2m_c: 'air temperature (°C)', vento_medio_ms: 'mean wind (m/s)', vento_max_ms: 'max wind (m/s)',
  abs_lat: 'absolute latitude (°)', rugosidade_m: 'terrain roughness (m)', declividade_graus: 'slope (°)', aod_550: 'aerosol optical depth (AOD 550)',
  elev_m: 'elevation (m)', protegido_pct: 'protected area (%)', basalto_pct: 'basalt',
  vulcanica_pct: 'all volcanic rocks', sedimento_pct: 'sediments (loose + sedimentary rock)', evaporito_pct: 'evaporites (salts, sulfates)', gelo_pct: 'snow/ice (%)', pop_dens_km2: 'population density (/km²)', pop_viz_km2: 'neighbourhood population (/km²)' };
const vn = k => VAR_EN[k] || k;
const STATUS_EN = { forte: 'strong', parcial: 'partial', falha: 'fails', 'sem dado': 'no data' };
const fmt = (v, d = 2) => (v === null || v === undefined || Number.isNaN(v)) ? '—' : (+v).toFixed(d);

// scale relative to the candidates shown: worst = dark red, middle = yellow, best = white
let ESCALA = { min: 0, max: 1 };
function corScore(s) {
  if (s === null || s === undefined) return 'rgba(120,120,120,0.6)';
  const amp = ESCALA.max - ESCALA.min;
  s = amp > 1e-6 ? (s - ESCALA.min) / amp : 1;
  s = Math.max(0, Math.min(1, s));
  if (s < 0.5) {                     // dark red -> yellow
    const t = s / 0.5;
    return `rgba(${Math.round(120 + 135 * t)},${Math.round(20 + 210 * t)},${Math.round(20 + 20 * t)},0.9)`;
  }
  const r = 255, g = Math.round(s < 0.5 ? 60 + 380 * s : 250), b = Math.round(s < 0.5 ? 40 : 40 + 430 * (s - 0.5));
  return `rgba(${r},${g},${Math.min(b, 255)},0.85)`;
}
// colour-blind-safe palette (Okabe-Ito): differs in hue AND lightness
const COR_VIAB = { ok: 'rgba(63,208,201,0.92)', parcial: 'rgba(240,228,66,0.92)', nao: 'rgba(213,94,0,0.92)', espera: 'rgba(150,150,150,0.7)' };
function corCelula(p) {
  if (p.tipo === 'regiao') return 'rgba(255,207,107,0.10)';
  if (p.viab) return COR_VIAB[p.viab];
  if (p.tipo === 'ponto') return 'rgba(80,170,255,0.9)';
  return corScore(p.score);
}
function classeViab(r, dur) {
  if (r.n_janelas > 0) return 'ok';
  return r.horas_ok_pct > 0 ? 'parcial' : 'nao';
}
function corPct(p) {
  if (p === null || p === undefined) return '#222';
  return `hsl(178,60%,${10 + p * 0.5}%)`;   // single hue: lighter = more OK hours (readable for colour-blind users)
}

// octagon around a point (radius in degrees of latitude)
// IMPORTANT: vertices CLOCKWISE. On the globe (d3-geo) a counter-clockwise ring
// means "the whole planet minus this octagon" and paints the entire sphere.
function octogono(lat, lon, raioGraus, props) {
  const coords = [];
  const k = 1 / Math.max(Math.cos(lat * Math.PI / 180), 0.05);
  for (let i = 0; i < 8; i++) {
    const a = (Math.PI / 8) - i * (Math.PI / 4);
    coords.push([lon + raioGraus * k * Math.cos(a), lat + raioGraus * Math.sin(a)]);
  }
  coords.push([...coords[0]]);   // ring must close exactly (GeoJSON)
  return { type: 'Feature', properties: props, geometry: { type: 'Polygon', coordinates: [coords] } };
}

// ---------- layout: side panel (desktop) or bottom sheet (phone/tablet) ----------
const MOBILE = () => window.matchMedia('(max-width: 900px)').matches;
function larguraGlobo() { return MOBILE() ? window.innerWidth : window.innerWidth - 420; }
function alturaGlobo() {
  if (!MOBILE()) return window.innerHeight;
  const topoPainel = document.querySelector('#painel')?.getBoundingClientRect().top || window.innerHeight * 0.48;
  return Math.max(200, topoPainel);
}
function ajustarGlobo() { if (typeof world !== 'undefined' && world) world.width(larguraGlobo()).height(alturaGlobo()); }
document.addEventListener('DOMContentLoaded', () => {
  const bt = document.querySelector('#btPainel');
  if (!bt) return;
  bt.addEventListener('click', () => {
    const fechado = document.querySelector('#painel').classList.toggle('recolhido');
    document.body.classList.toggle('painelFechado', fechado);
    bt.setAttribute('aria-expanded', String(!fechado));
    bt.querySelector('span:last-child').textContent = fechado ? 'Show panel' : 'Hide panel';
    bt.querySelector('span').textContent = fechado ? '▲' : '▼';
    setTimeout(ajustarGlobo, 260);
  });
});

// ---------- globe ----------
const el = $('#globo');
let world;
try { world = Globe()(el); } catch (e) { world = new Globe(el); }
world
  .globeImageUrl('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg')   // NASA Blue Marble
  .bumpImageUrl('https://unpkg.com/three-globe/example/img/earth-topology.png')
  .backgroundImageUrl('https://unpkg.com/three-globe/example/img/night-sky.png')
  .width(larguraGlobo()).height(alturaGlobo())
  .polygonAltitude(d => d.properties.tipo === 'regiao' ? 0.004 : 0.012)
  .polygonCapColor(d => corCelula(d.properties))
  .polygonSideColor(() => 'rgba(0,0,0,0.25)')
  .polygonStrokeColor(d => d.properties.tipo === 'regiao' ? '#ffcf6b' : '#111')
  .polygonLabel(d => { const p = d.properties;
    if (p.tipo === 'regiao') return 'Marked region';
    let t = `<b>${fmt(p.lat,1)}°, ${fmt(p.lon,1)}°</b>`;
    if (p.score !== undefined) t += `<br>similarity ${fmt(p.score)} · operational ${fmt(p.operacional ?? p.score_operacional)}`;
    if (p.protegido > 0) t += `<br>⚠ ${fmt(p.protegido, 0)}% protected area (WDPA)`;
    if (p.viab_txt) t += `<br>${p.viab_txt}`;
    return t; })
  .onPolygonClick((d, ev, c) => { const p = d.properties;
    if ($('#modoRegiao').checked && c) { marcarRegiao(c.lat, c.lng); return; }
    if (p.tipo === 'celula' && TEM_GRADE) abrirCelula(p.id);
    else { definirPonto(p.lat, p.lon); pontoLivre(p.lat, p.lon); } })
  .labelLat('lat').labelLng('lon').labelText('nome').labelSize(0.9).labelDotRadius(0.5)
  .labelColor(() => '#7fd3ff').labelResolution(2)
  .labelLabel(d => `<b>${d.nome}</b><br>${d.uso}<br>profile score: ${fmt(d.score)}`)
  .onLabelClick(d => d.celula && abrirCelula(d.celula))
  .onGlobeClick(({ lat, lng }) => { if ($('#modoRegiao').checked) marcarRegiao(lat, lng); else { definirPonto(lat, lng); pontoLivre(lat, lng); } });
window.addEventListener('resize', ajustarGlobo);

let camadaCand = [], camadaRegiao = [], camadaPonto = [], camadaSim = [];
let TEM_GRADE = false;
const redesenhar = () => world.polygonsData([...camadaRegiao, ...camadaCand, ...camadaSim, ...camadaPonto]);

// click on the globe (outside region mode) = picks the equipment point
function definirPonto(lat, lon, viab, txt) {
  $('#formEq').lat.value = (+lat).toFixed(2);
  $('#formEq').lon.value = (+lon).toFixed(2);
  camadaPonto = [octogono(+lat, +lon, 0.7, { tipo: 'ponto', lat: +lat, lon: +lon, viab, viab_txt: txt })];
  redesenhar();
}
const SEM_GRADE = `<p class="aviso">No processed grid yet: the satellite data has not been downloaded/processed
  (run <code>coleta\\baixar_nasa.py</code>, <code>coleta\\baixar_externos.py</code> and <code>processamento\\processar_grade.py</code>, then restart uvicorn).<br><br>
  Meanwhile this <b>works</b>: click the globe to pick a point → Simulation tab.</p>`;
function pontoLivre(lat, lon) {
  abrirAba('aba-sim');
  $('#selecionado').innerHTML = `<b>Selected point:</b> ${fmt(lat, 2)}°, ${fmt(lon, 2)}° (free point, outside the octagons).
    <br><small>To use an analog from the profile, click an octagon.</small>`;
}
const perfil = () => $('#perfil').value;

// ---------- tabs ----------
document.querySelectorAll('#painel nav button').forEach(b => b.onclick = () => abrirAba(b.dataset.aba));
function abrirAba(id) {
  document.querySelectorAll('#painel nav button').forEach(x => { x.classList.toggle('ativa', x.dataset.aba === id); x.setAttribute('aria-selected', x.dataset.aba === id); });
  document.querySelectorAll('.aba').forEach(x => x.classList.toggle('ativa', x.id === id));
}

// ---------- loading ----------
async function iniciar() {
  const st = await api('/api/status');
  TEM_GRADE = !!st.grade;
  console.log('First Footprint app.js', VERSAO);
  $('#status').textContent = `[${VERSAO}] ` + (st.grade
    ? `${st.celulas} cells · ${st.longe_cidades} remote` + (st.variaveis_vazias.length ? ` · no data: ${st.variaveis_vazias.join(', ')}` : '')
    : st.msg);
  const perfis = await api('/api/perfis');
  PERFIS = perfis;
  $('#perfil').innerHTML = Object.entries(perfis).map(([k, v]) => `<option value="${k}">${v.nome}</option>`).join('');
  $('#perfil').onchange = carregar;
  $('#raio').oninput = () => $('#raioTxt').textContent = `${$('#raio').value} km`;
  // radius changed with a region already marked → redraw it with the new radius
  $('#raio').onchange = () => { if (centroRegiao && $('#modoRegiao').checked) marcarRegiao(...centroRegiao); };
  // unchecking 'mark region' clears the region and its cells
  $('#modoRegiao').onchange = () => { if (!$('#modoRegiao').checked && centroRegiao) {
    centroRegiao = null; camadaRegiao = []; camadaCand = camadaCand.filter(f => !['celula', 'grade'].includes(f.properties.tipo) || f.properties.score_regiao === undefined); redesenhar(); } };
  await carregar();
  if (Object.keys(EQUIP).length) montarSorteio();
}

async function carregar() {
  const cand = await api(`/api/candidatas?perfil=${perfil()}&so_remotas=true`);
  const notas = cand.map(c => c.score).filter(v => v !== null && v !== undefined);
  ESCALA = notas.length ? { min: Math.min(...notas), max: Math.max(...notas) } : { min: 0, max: 1 };
  $('#legMin').textContent = fmt(ESCALA.min); $('#legMax').textContent = fmt(ESCALA.max);
  $('#legenda').setAttribute('aria-label', `Similarity scale: dark ${fmt(ESCALA.min)}, light ${fmt(ESCALA.max)}`);
  camadaCand = cand.map(c => octogono(c.lat, c.lon, 0.48, { ...c, tipo: 'celula' }));
  redesenhar();
  $('#csvCand').href = `/api/export/candidatas.csv?perfil=${perfil()}&so_remotas=true`;
  $('#listaCand').innerHTML = cand.slice(0, 60).map(c =>
    `<li data-id="${c.id}"><button type="button" class="linkLista">${fmt(c.lat,1)}°, ${fmt(c.lon,1)}° — similarity ${fmt(c.score)} · operational ${fmt(c.operacional)}${c.protegido >= 10 ? ` · ⚠ ${fmt(c.protegido, 0)}% protected` : ''}</button></li>`).join('')
    || (TEM_GRADE ? '<p class="aviso">No scored cells for this profile. Check the variables with no data at the top.</p>' : SEM_GRADE);
  document.querySelectorAll('#listaCand li').forEach(li => li.onclick = () => abrirCelula(li.dataset.id, true));
  const conh = await api(`/api/conhecidos?perfil=${perfil()}`);
  world.labelsData(conh);
}

// ---------- cell (shown as a note at the top of Simulation) ----------
async function abrirCelula(id, voar = false) {
  abrirAba('aba-sim');
  $('#selecionado').innerHTML = '<p class="dica">Loading point…</p>';
  const r = await api(`/api/celula/${id}?perfil=${perfil()}`);
  const d = r.dados, a = r.analise;
  if (voar) world.pointOfView({ lat: d.lat, lng: d.lon, altitude: 1.2 }, 1200);
  definirPonto(d.lat, d.lon);
  const sc = d[`score_${perfil()}`];
  const chip = st => a.itens.filter(i => i.status === st).map(i => vn(i.variavel)).join(', ') || '—';
  const linhas = a.itens.map(i => `<tr>
      <td>${vn(i.variavel)}</td><td>${i.valor ?? '—'}</td>
      <td class="${i.status.replace(' ', '')}">${STATUS_EN[i.status] || i.status}${i.sim !== null ? ` (${i.sim})` : ''}</td>
      <td><small>${i.referencia}</small></td></tr>`).join('');
  const extras = ['t2m_c','lst_dia_c','lst_noite_c','vento_medio_ms','vento_max_ms','poeira_ugm3','aod_550',
    'elev_m','declividade_graus','rugosidade_m','gelo_pct','pop_dens_km2','pop_viz_km2','protegido_pct']
    .filter(k => k in d).map(k => `<tr><td>${vn(k)}</td><td>${fmt(d[k])}</td></tr>`).join('');
  const geo = ['basalto_pct','vulcanica_pct','sedimento_pct','evaporito_pct']
    .filter(k => d[k] !== null && d[k] !== undefined).map(k => `<tr><td>${vn(k)}</td><td>${fmt(d[k], 0)}%</td></tr>`).join('')
    || `<tr><td colspan="2"><small>not downloaded yet (run coleta\\baixar_externos.py)</small></td></tr>`;
  const avisoProt = d.protegido_pct > 0 ? `<p class="aviso">⚠ <b>${fmt(d.protegido_pct, 0)}%</b> of this cell is a protected area (WDPA). Field tests there need a permit from the park authority.</p>` : '';
  $('#selecionado').innerHTML = `
    <b>Selected octagon:</b> ${fmt(d.lat,2)}°, ${fmt(d.lon,2)}° · cell ${d.id}<br>
    Similarity <b>${fmt(sc)}</b> <span class="barra"><i style="width:${(sc||0)*100}%"></i></span>
    Operational <b>${fmt(d.score_operacional)}</b> · ${d.longe_cidades ? 'no significant human occupation' : 'near human occupation'}<br>
    <small><span class="forte">strong:</span> ${chip('forte')} · <span class="parcial">partial:</span> ${chip('parcial')} · <span class="falha">fails:</span> ${chip('falha')}</small>
    ${avisoProt}
    <details><summary>Full analog analysis</summary>
      <table><tr><th>variable</th><th>value</th><th>status</th><th>reference</th></tr>${linhas}</table>
      <h3>Differences Earth cannot reproduce</h3>
      <ul>${a.limitacoes_fixas.map(x => `<li>${x.texto ?? x} ${x.url ? `<small>— <a href="${x.url}" target="_blank">${x.fonte}</a></small>` : ''}</li>`).join('')}</ul>
      <h3>Method limits</h3>
      <ul>${(a.limitacoes_metodo || []).map(x => `<li>${x.texto} <small>— <a href="${x.url}" target="_blank">${x.fonte}</a></small></li>`).join('')}</ul>
      <h3>Biological occupation</h3>
      <p>${r.fauna.registros_animais ?? '—'} animal records (GBIF). <small>${r.fauna.nota || r.fauna.erro || ''}</small></p>
      <h3>Other variables</h3><table>${extras}</table>
      <h3>Geology (GLiM)</h3><table>${geo}</table>
    </details>`;
}

// ---------- region ----------
let centroRegiao = null;
async function marcarRegiao(lat, lon) {
  centroRegiao = [lat, lon];
  const raio = +$('#raio').value;
  camadaRegiao = [octogono(lat, lon, raio / 111, { tipo: 'regiao' })];
  const r = await api(`/api/regiao?lat=${lat}&lon=${lon}&raio_km=${raio}&perfil=${perfil()}`);
  definirPonto(lat, lon);
  camadaCand = r.celulas.length
    ? r.celulas.map(c => octogono(c.lat, c.lon, 0.48, { ...c, tipo: 'celula', score_regiao: c.score }))
    : pontosGrade(lat, lon, raio).map(c => octogono(c.lat, c.lon, 0.48, { ...c, tipo: 'grade', score_regiao: null }));
  redesenhar();
  abrirAba('aba-sim');
  if (!r.celulas.length) {
    $('#selecionado').innerHTML = `<b>Region:</b> ${fmt(lat,2)}°, ${fmt(lon,2)}° · radius ${raio} km · ${camadaCand.length} points marked.
      Run the forecast to color them.${SEM_GRADE}`;
    return;
  }
  const top = r.celulas.slice(0, 25).map(c => `<tr data-id="${c.id}" style="cursor:pointer">
     <td>${fmt(c.lat,1)}, ${fmt(c.lon,1)}</td><td>${fmt(c.score)}</td><td>${fmt(c.score_operacional)}</td>
     <td>${c.longe_cidades ? 'yes' : 'no'}</td></tr>`).join('');
  $('#selecionado').innerHTML = `<b>Region:</b> ${fmt(lat,2)}°, ${fmt(lon,2)}° · radius ${raio} km · ${r.n} cells (center used as the point).
    <details><summary>Cells in the region (click to select)</summary>
    <table><tr><th>cell</th><th>sim.</th><th>oper.</th><th>remote</th></tr>${top}</table></details>`;
  document.querySelectorAll('#selecionado tr[data-id]').forEach(tr => tr.onclick = () => abrirCelula(tr.dataset.id));
  $('#formEq').lat.value = lat.toFixed(2);
  $('#formEq').lon.value = lon.toFixed(2);
}

// ---------- equipment ----------
function lerEquip() {
  const f = new FormData($('#formEq')), corpo = {};
  for (const [k, v] of f.entries()) {
    if (k === 'luz_dia' || v === '') continue;
    corpo[k] = ['nome', 'tipo', 'nuvem_tipo'].includes(k) ? v : +v;
  }
  corpo.luz_dia = $('#formEq').luz_dia.checked;
  corpo.perfil = perfil();
  return corpo;
}
const linksCsv = (arqs) => (arqs || []).map(a => `<a class="botao" href="${a}">⬇ ${a.split('/').pop()}</a>`).join(' ');

$('#btPrev').onclick = async () => {
  const eq = lerEquip();
  if (Number.isNaN(eq.lat) || Number.isNaN(eq.lon) || eq.lat === undefined) { $('#resEq').innerHTML = '<p class="erro">Click the globe or type lat/lon.</p>'; return; }
  definirPonto(eq.lat, eq.lon, 'espera', 'querying…');
  processando(`Simulation of ${eq.nome || 'equipment'}`, '1/2 16-day forecast (Open-Meteo)…');
  $('#resEq').innerHTML = '<p class="dica">1/2 16-day forecast (Open-Meteo)… ~5 s</p><div id="resPrev"></div><div id="resHist"></div>';
  const corpo = JSON.stringify(eq), hdr = { 'Content-Type': 'application/json' }, resumo = [], erros = [];
  // forecast and history in parallel; each shows up when it arrives
  const pPrev = api('/api/viabilidade/previsao', { method: 'POST', headers: hdr, body: corpo })
    .then(r => {
      const p = r.previsao;
      const v = p.erro ? undefined : (p.janelas.length ? 'ok' : (p.horas_ok_pct > 0 ? 'parcial' : 'nao'));
      definirPonto(eq.lat, eq.lon, v, p.erro ? 'forecast error' : `${p.janelas.length} windows · ${p.horas_ok_pct}% hours OK`);
      $('#resPrev').innerHTML = `<p>${linksCsv(r.arquivos)}</p>` + renderLocal(r.local) + renderPrevisao(p, eq.duracao_h);
      $('#resEq .dica').textContent = '2/2 NASA POWER history (2 years)… may take ~30–60 s the first time';
      etapa('2/2 NASA POWER history (2 years)… may take ~30–60 s the first time');
      resumo.push(`16-day forecast: <b>${p.janelas.length}</b> windows · ${p.horas_ok_pct}% of hours OK`);
    }).catch(e => { erros.push('Forecast: ' + e.message); $('#resPrev').innerHTML = `<p class="erro">Forecast: ${e.message}</p>`; });
  const pHist = api('/api/viabilidade/historico', { method: 'POST', headers: hdr, body: corpo })
    .then(r => { $('#resHist').innerHTML = renderHistorico(r.historico) + `<p>${linksCsv(r.arquivos)}</p>`; resumo.push('NASA POWER climatology (2 years) loaded'); })
    .catch(e => { erros.push('History: ' + e.message); $('#resHist').innerHTML = `<p class="erro">History: ${e.message}</p>`; });
  await pPrev;
  if (camadaCand.length) etapa('Coloring the map by feasibility…');
  const pCor = camadaCand.length ? colorirViabilidade(true).then(t => t && resumo.push(t)) : null;   // built in
  await Promise.allSettled([pPrev, pHist, pCor]);
  const d = $('#resEq .dica'); if (d) d.remove();
  concluido(`Simulation of ${eq.nome || 'equipment'}`, resumo, erros);
};

// grid of points (~1° step) within a radius, when there is no processed grid
function pontosGrade(lat, lon, raioKm) {
  const out = [], passo = Math.max(1, raioKm / 111 / 5), r = raioKm / 111;
  for (let a = -r; a <= r + 1e-9; a += passo)
    for (let b = -r; b <= r + 1e-9; b += passo) {
      if (a * a + b * b > r * r) continue;
      const la = lat + a, lo = lon + b / Math.max(Math.cos(la * Math.PI / 180), 0.1);
      if (Math.abs(la) < 89) out.push({ id: `g${out.length}`, lat: +la.toFixed(2), lon: +(((lo + 540) % 360) - 180).toFixed(2) });
    }
  return out.slice(0, 120);
}

async function colorirViabilidade(silencioso = false) {
  const eq = lerEquip();
  let alvos = camadaCand.map(f => f.properties);
  if (!alvos.length) {
    if (Number.isNaN(eq.lat) || eq.lat === undefined) { alert('Click the globe to pick a point or mark a region.'); return; }
    alvos = pontosGrade(eq.lat, eq.lon, +$('#raio').value);
    camadaCand = alvos.map(c => octogono(c.lat, c.lon, 0.48, { ...c, tipo: 'grade' }));
  }
  alvos = alvos.slice(0, 150);
  eq.lat = eq.lat ?? alvos[0].lat; eq.lon = eq.lon ?? alvos[0].lon;
  camadaCand.forEach(f => { f.properties.viab = 'espera'; });
  redesenhar();
  const alvoMsg = $('#resMapa');
  alvoMsg.innerHTML = `<p class="dica">Querying the forecast for ${alvos.length} points…</p>`;
  if (!silencioso) processando('Feasibility on the map', `Querying the forecast for ${alvos.length} points…`);
  try {
    const r = await api('/api/viabilidade/mapa', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ equipamento: eq, pontos: alvos.map(a => ({ id: a.id, lat: a.lat, lon: a.lon })) }) });
    const porId = Object.fromEntries(r.pontos.map(p => [p.id, p]));
    camadaCand.forEach(f => {
      const p = porId[String(f.properties.id)];
      if (!p) return;
      f.properties.viab = classeViab(p);
      f.properties.viab_txt = `${p.n_janelas} windows (longest ${p.maior_janela_h} h) · ${p.horas_ok_pct}% hours OK` + (p.primeira_janela ? `<br>1st: ${p.primeira_janela}` : '');
    });
    redesenhar();
    const n = { ok: 0, parcial: 0, nao: 0 };
    camadaCand.forEach(f => n[f.properties.viab] !== undefined && n[f.properties.viab]++);
    alvoMsg.innerHTML = `<h3>Feasibility on the map (${alvos.length} points)</h3><p><span style="color:#3FD0C9" aria-hidden="true">■</span> ✓ ${n.ok} with a ${eq.duracao_h} h window ·
      <span style="color:#F0E442" aria-hidden="true">■</span> ! ${n.parcial} isolated hours only · <span style="color:#D55E00" aria-hidden="true">■</span> ✕ ${n.nao} not feasible (16 days)</p>
      <p>${linksCsv([r.arquivo])}</p>`;
    const txt = `Map: <b>${n.ok}</b> of ${alvos.length} points with a ${eq.duracao_h} h window`;
    if (!silencioso) concluido('Feasibility on the map', [txt]);
    return txt;
  } catch (e) { alvoMsg.innerHTML = `<p class="erro">${e.message}</p>`; if (!silencioso) concluido('Feasibility on the map', [], ['Map: ' + e.message]); }
}

function renderLocal(l) {
  if (!l) return '';
  let t = '<h3>Site</h3>';
  if (l.similaridade !== undefined) {
    t += l.e_candidata
      ? `<p class="forte">This point is an analog candidate for this profile (similarity ${fmt(l.similaridade)}).</p>`
      : `<p class="aviso">This point is <b>not an analog candidate</b> for this profile (similarity ${fmt(l.similaridade)}${l.remota ? '' : ', populated area'}). The windows below only reflect the weather; for the demo, use one of the candidates.</p>`;
  }
  if (l.declividade === 'no data') t += '<p>Slope: no data</p>';
  else if (l.limite !== undefined) t += `<p class="${l.ok ? 'forte' : 'falha'}">Mean slope ${l.declividade_media_celula}° (limit ${l.limite}°) — ${l.ok ? 'OK' : 'above the limit'}</p><small>${l.nota}</small>`;
  return t;
}

function renderPrevisao(p, dur) {
  if (p.erro) return `<h3>Forecast</h3><p class="erro">${p.erro}</p>`;
  const jan = p.janelas.length
    ? p.janelas.slice(0, 15).map(j => `<li>${j.inicio} · ${j.horas} h in a row${j.confiavel === false ? ' <small>(indicative: beyond 7 days)</small>' : ''}</li>`).join('')
    : `<li class="falha">No ${dur} h window in the next 16 days.</li>`;
  // strip per day: 1 square per hour
  const dias = {};
  p.horas.forEach(h => { (dias[h.hora_local.slice(0, 10)] ||= []).push(h); });
  const tiras = Object.entries(dias).map(([d, hs]) => `<div><small>${d}</small><div class="horas">${
    hs.map(h => `<i title="${h.hora_local} · wind ${fmt(h.vento_ms,1)} m/s · cloud ${fmt(h.nuvem_pct,0)}% · sun ${fmt(h.elev_solar,0)}°"
      style="background:${h.ok ? '#3FD0C9' : '#3a2416'}"></i>`).join('')}</div></div>`).join('');
  return `<h3>Forecast – next 16 days (${p.fuso})</h3>
    <small>${p.fonte}. Clouds: ${p.nuvem_tipo}. Criteria: ${p.criterios.join(', ')}${p.sem_dado.length ? ` · no data: ${p.sem_dado.join(', ')}` : ''}</small>
    <p>${p.horas_ok_pct}% of hours meet every limit.</p><ul>${jan}</ul>${tiras}`;
}

function renderHistorico(h) {
  if (h.erro) return `<h3>History</h3><p class="erro">${h.erro}</p>`;
  const cab = '<tr><th></th>' + [...Array(24).keys()].map(i => `<th>${i}</th>`).join('') + '</tr>';
  const lin = h.matriz_pct.map((row, m) => `<tr><th>${MESES[m]}</th>${
    row.map(v => `<td style="background:${corPct(v)};color:${v > 55 ? '#0A0F24' : '#F2EBDD'}" title="${v ?? '—'}%">${v === null ? '' : Math.round(v)}</td>`).join('')}</tr>`).join('');
  return `<h3>Historical window probability (month × hour, ${h.hora})</h3>
    <small>${h.fonte}. ${h.nota}</small>
    <table class="mapa">${cab}${lin}</table>
    <p>Best months (mean chance across the day): <b>${h.melhores_meses.map(m => `${MESES[m - 1]} ${fmt(h.media_mes_pct[m - 1], 0)}%`).join(', ')}</b> · ${h.horas_ok_pct}% of hours OK overall.</p>`;
}

// ---------- real equipment ----------
let EQUIP = {}, TERRA = [], PERFIS = {};
async function carregarPresets() {
  const d = await api('/api/equipamentos');
  EQUIP = d.equipamentos; TERRA = d.locais_terrestres || [];
  montarSorteio();
  $('#preset').innerHTML += Object.entries(EQUIP).map(([k, e]) => `<option value="${k}">${e.nome}</option>`).join('');
  $('#preset').onchange = () => aplicarPreset($('#preset').value);
}
function aplicarPreset(k) {
  const f = $('#formEq'), e = EQUIP[k];
  if (!e) { $('#presetInfo').innerHTML = ''; return; }
  // clear optional fields and apply the preset's
  ['vento_altitude_max_ms', 'poeira_max_ugm3', 'aod_max', 'declividade_max_graus', 'elev_solar_max_graus'].forEach(n => f[n].value = '');
  f.nome.value = e.nome; f.tipo.value = e.tipo;
  Object.entries(e.params).forEach(([n, v]) => {
    if (n === 'luz_dia') f.luz_dia.checked = v; else if (f[n]) f[n].value = v;
  });
  $('#presetInfo').innerHTML = `${e.uso}.<br>Source: <a href="${e.fonte.url}" target="_blank">${e.fonte.texto}</a><br>
    <span class="parcial">Estimated (not published): ${e.estimados.join('; ')}</span>`;
}
carregarPresets().catch(() => {});

// ---------- Simulation modes ----------
document.querySelectorAll('.modos button').forEach(b => b.onclick = () => {
  document.querySelectorAll('.modos button').forEach(x => x.classList.toggle('ativo', x === b));
  document.querySelectorAll('.modo').forEach(x => x.classList.toggle('ativo', x.id === b.dataset.modo));
});
const json = (u, corpo) => api(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo) });
const temPonto = eq => !(eq.lat === undefined || eq.lon === undefined || Number.isNaN(eq.lat) || Number.isNaN(eq.lon));

// ---------- history (real past period) ----------
let FIM_DISP = null;
api('/api/simulacao/limites').then(l => {
  FIM_DISP = l.fim_disponivel;
  $('#anoHist').textContent = l.ano;
  $('#hIni').value = `${l.ano}-01-01`; $('#hFim').value = l.fim_disponivel;
  $('#hIni').max = $('#hFim').max = l.fim_disponivel;
  $('#sIni').value = `${l.ano}-01-01`; $('#sFim').value = l.fim_disponivel;
  $('#sIni').max = $('#sFim').max = l.fim_disponivel;
  $('#hNota').innerHTML += ` Data available up to <b>${l.fim_disponivel}</b> (NASA POWER publishes with a ~2–3 day delay).`;
}).catch(() => {});

$('#btHist').onclick = async () => {
  const eq = lerEquip();
  if (!temPonto(eq)) { $('#resPer').innerHTML = '<p class="erro">Select a point on the globe first.</p>'; return; }
  $('#resPer').innerHTML = '<p class="dica">Downloading hourly NASA POWER data… (1 year ≈ 10–30 s the first time; cached afterwards)</p>';
  processando('Historical simulation', 'Downloading hourly NASA POWER data… (1 year ≈ 10–30 s the first time)');
  try {
    const r = await json('/api/simulacao/historico', { equipamento: eq, inicio: $('#hIni').value, fim: $('#hFim').value });
    $('#resPer').innerHTML = renderPeriodo(r, eq.duracao_h);
    const temHora = Object.values(r.por_mes_pct || {}).some(v => v > 0);
    definirPonto(eq.lat, eq.lon, r.n_janelas > 0 ? 'ok' : (temHora ? 'parcial' : 'nao'),
      `history ${$('#hIni').value} → ${$('#hFim').value}: ${r.dias_com_janela}/${r.dias} days with a window`);
    concluido('Historical simulation', [`<b>${r.dias_com_janela}</b> of ${r.dias} days with at least one window`, `${r.n_janelas} windows in the period · CSV ready to download in the panel`]);
  } catch (e) { $('#resPer').innerHTML = `<p class="erro">${e.message}</p>`; concluido('Historical simulation', [], [e.message]); }
};

function renderPeriodo(r, dur) {
  // strip: one row per day, 24 squares (local solar time)
  const t0 = new Date(r.tira.inicio.replace(' ', 'T') + ':00Z');
  const dias = [];
  r.tira.ok.forEach((v, i) => {
    const t = new Date(t0.getTime() + i * 3600e3), d = t.toISOString().slice(0, 10);
    if (!dias.length || dias[dias.length - 1].d !== d) dias.push({ d, h: Array(24).fill(null) });
    dias[dias.length - 1].h[t.getUTCHours()] = v;
  });
  const cor = v => v === null ? '#222' : (v ? '#3FD0C9' : '#3a2416');
  const tiras = dias.map(x => `<div class="diaLinha"><small>${x.d.slice(5)}</small>${x.h.map(v => `<i style="background:${cor(v)}"></i>`).join('')}</div>`).join('');
  const meses = Object.entries(r.por_mes_pct).map(([m, v]) => `<td style="background:${corPct(v)};color:${v > 55 ? '#0A0F24' : '#F2EBDD'}">${MESES[m - 1]}<br>${fmt(v, 0)}%</td>`).join('');
  const jan = r.janelas.slice(0, 20).map(j => `<li>${j.inicio} · ${j.horas} h</li>`).join('') || `<li class="falha">No ${dur} h window in the period.</li>`;
  return `<h3>Historical simulation</h3>
    <small>${r.fonte}. ${r.nota}${r.sem_dado.length ? ` No data: ${r.sem_dado.join(', ')}.` : ''}</small>
    <p><b>${r.horas_ok_pct}%</b> of hours meet every limit · <b>${r.n_janelas}</b> windows of ${dur} h or more ·
       <b>${r.dias_com_janela}</b> of ${r.dias} days with at least one window.</p>
    <table class="mapa"><tr>${meses}</tr></table>
    <p>${linksCsv(r.arquivos)}</p>
    <details><summary>First windows</summary><ul>${jan}</ul></details>
    <details open><summary>Day by day (light = feasible hour, dark = not; solar hour 0–23)</summary><div class="tiraDias">${tiras}</div></details>`;
}

// ---------- random draw ----------
let LINHAS = [];
function montarSorteio() {
  const pf = Object.keys(PERFIS).length ? PERFIS : null;
  $('#sOrig').innerHTML = (pf ? Object.entries(pf).map(([k, p]) =>
      `<label class="chkl"><input type="checkbox" name="sorig" value="${k}" checked> ${p.nome.split('(')[0]}</label>`).join('') : '')
    + `<label class="chkl"><input type="checkbox" name="sorig" value="terra" checked> Favorable Earth regions (Sahara, Tarim, Atacama…)</label>`;
  $('#sEq').innerHTML = Object.entries(EQUIP).map(([k, e]) =>
      `<label class="chkl"><input type="checkbox" name="seq" value="${k}" checked> ${e.nome}</label>`).join('');
}
const LIMITE = {"wind": "wind", "gust": "gusts", "wind_180m": "wind at 180 m", "temperature": "temperature", "humidity": "humidity", "rain": "rain", "clouds": "clouds", "visibility": "visibility", "sun": "daylight/sun", "dust": "dust", "aod": "aerosols"};
const limTxt = k => k ? (LIMITE[k] || k) : '';
const sorteia = a => a[Math.floor(Math.random() * a.length)];
function diaAleatorio() {
  const lim = FIM_DISP || new Date(Date.now() - 3 * 864e5).toISOString().slice(0, 10);
  let a = $('#sIni').value || `${lim.slice(0, 4)}-01-01`, b = $('#sFim').value || lim;
  if (b > lim) b = lim;
  if (a < '2001-01-01') a = '2001-01-01';
  if (a > b) [a, b] = [b, a];
  const ini = Date.parse(a + 'T00:00:00Z'), fim = Date.parse(b + 'T00:00:00Z');
  const dias = Math.round((fim - ini) / 864e5);
  return new Date(ini + Math.floor(Math.random() * (dias + 1)) * 864e5).toISOString().slice(0, 10);
}
$('#sBase').onchange = () => { $('#sPeriodo').hidden = $('#sBase').value !== 'hist'; };
async function poolPontos() {
  const sel = [...document.querySelectorAll('input[name=sorig]:checked')].map(i => i.value);
  const k = +$('#sK').value || 25, pool = [];
  for (const o of sel) {
    if (o === 'terra') {
      for (const t of TERRA) {
        let sim = null;
        try { const r = await api(`/api/regiao?lat=${t.lat}&lon=${t.lon}&raio_km=120&perfil=${perfil()}`); if (r.celulas && r.celulas.length) sim = r.celulas[0].score; } catch (e) {}
        pool.push({ ...t, origem: 'Favorable Earth site', sim });
      }
      continue;
    }
    const c = await api(`/api/candidatas?perfil=${o}&n=${k}&so_remotas=true`);
    const nome = PERFIS[o].nome.split('(')[0].split(':')[0].trim();
    c.forEach(x => pool.push({ nome: `cell ${x.id}`, lat: x.lat, lon: x.lon, origem: nome, sim: x.score }));
  }
  return pool;
}
$('#btSort').onclick = async () => {
  if (!Object.keys(PERFIS).length || !$('#sOrig input')) montarSorteio();
  const eqs = [...document.querySelectorAll('input[name=seq]:checked')].map(i => i.value);
  if (!eqs.length) { $('#sMsg').textContent = 'Pick at least one piece of equipment.'; return; }
  const n = Math.min(+$('#sN').value || 10, 40), base = $('#sBase').value, antes = LINHAS.length, errosS = [];
  $('#sMsg').textContent = 'Building points…';
  processando('Random test draw', 'Building points…');
  const pool = await poolPontos();
  if (!pool.length) { $('#sMsg').textContent = 'No points available.'; concluido('Random test draw', [], ['No points available.']); return; }
  const grupos = {};
  for (let i = 0; i < n; i++) {
    const e = sorteia(eqs);
    (grupos[e] ||= []).push({ ...sorteia(pool), id: `s${LINHAS.length + i}`, data: base === 'hist' ? diaAleatorio() : null });
  }
  for (const [ek, pts] of Object.entries(grupos)) {
    const e = EQUIP[ek];
    $('#sMsg').textContent = `Simulating ${e.nome} (${pts.length})…`;
    etapa(`Simulating ${e.nome} (${pts.length} points)…`);
    const eq = { ...e.params, nome: e.nome, tipo: e.tipo, lat: pts[0].lat, lon: pts[0].lon };
    try {
      const r = base === 'hist'
        ? await json('/api/simulacao/historico_lote', { equipamento: eq, pontos: pts.map(p => ({ id: p.id, lat: p.lat, lon: p.lon, data: p.data })) })
        : await json('/api/viabilidade/mapa', { equipamento: eq, pontos: pts.map(p => ({ id: p.id, lat: p.lat, lon: p.lon })) });
      const porId = Object.fromEntries(r.pontos.map(p => [p.id, p]));
      pts.forEach(p => {
        const v = porId[p.id] || {};
        LINHAS.push({ equipment: e.nome, basis: base === 'hist' ? `history ${p.data}` : '16-day forecast', source: p.origem,
          site: p.nome, lat: p.lat, lon: p.lon, similarity: p.sim, hours_ok_pct: v.horas_ok_pct, n_windows: v.n_janelas,
          longest_window_h: v.maior_janela_h, first_window: v.primeira_janela, main_limit: v.n_janelas > 0 ? '' : limTxt(v.principal_limite),
          result: v.erro ? 'error' : (v.n_janelas > 0 ? 'feasible' : (v.horas_ok_pct > 0 ? 'isolated hours only' : 'not feasible')) });
      });
    } catch (err) { errosS.push(`${e.nome}: ${err.message}`); $('#sMsg').textContent = 'Error: ' + err.message; }
  }
  $('#sMsg').textContent = `${LINHAS.length} tests in total.`;
  desenharSorteio();
  const novas = LINHAS.slice(antes), viav = novas.filter(l => l.result === 'feasible').length;
  concluido('Your tests are complete', [`<b>${novas.length}</b> tests drawn`, `<b>${viav}</b> feasible · ${novas.length - viav} without a window`], errosS);
};
function desenharSorteio() {
  const agrup = {};
  LINHAS.forEach(l => { const k = `${l.lat},${l.lon}`; (agrup[k] ||= []).push(l); });
  camadaSim = Object.values(agrup).map(ls => {
    const v = ls.some(l => l.n_windows > 0) ? 'ok' : (ls.some(l => l.hours_ok_pct > 0) ? 'parcial' : 'nao');
    const txt = ls.map(l => `${l.equipment.split('(')[0].trim()} · ${l.basis} · <b>${l.result}</b>`).join('<br>');
    return octogono(ls[0].lat, ls[0].lon, 0.6, { tipo: 'sorteio', lat: ls[0].lat, lon: ls[0].lon, viab: v, viab_txt: txt });
  });
  redesenhar();
  const cls = r => r === 'feasible' ? 't-ok' : (r === 'not feasible' || r === 'error' ? 't-nao' : 't-par');
  const curto = n => n.split('(')[0].trim();
  const ag = {};
  LINHAS.forEach(l => { const a = (ag[curto(l.equipment)] ||= { n: 0, ok: 0, h: 0 }); a.n++; a.ok += l.n_windows > 0; a.h += l.hours_ok_pct || 0; });
  $('#resSort').innerHTML = !LINHAS.length ? '' : `<h3>Summary by equipment</h3><table>
    <tr><th>Equipment</th><th>Tests</th><th>with window</th><th>% hours OK</th></tr>
    ${Object.entries(ag).map(([k, a]) => `<tr><td>${k}</td><td>${a.n}</td><td>${fmt(100 * a.ok / a.n, 0)}%</td><td>${fmt(a.h / a.n, 1)}%</td></tr>`).join('')}</table>
    <h3>Tests</h3><table class="tabSort"><tr><th>Equip.</th><th>Site</th><th>Basis</th><th>% OK</th><th>Win.</th><th></th></tr>
    ${LINHAS.map((l, i) => `<tr data-i="${i}" style="cursor:pointer" title="click to select the point">
      <td>${curto(l.equipment)}</td><td>${l.source}<br><small>${fmt(l.lat, 1)}, ${fmt(l.lon, 1)}${l.similarity !== null ? ` · sim ${fmt(l.similarity)}` : ''}</small></td>
      <td><small>${l.basis}</small></td><td>${fmt(l.hours_ok_pct, 1)}</td><td>${l.n_windows ?? '—'}</td>
      <td><span class="tag ${cls(l.result)}">${l.result}</span></td></tr>`).join('')}</table>`;
  document.querySelectorAll('.tabSort tr[data-i]').forEach(tr => tr.onclick = () => {
    const l = LINHAS[+tr.dataset.i]; definirPonto(l.lat, l.lon); world.pointOfView({ lat: l.lat, lng: l.lon, altitude: 1.4 }, 1000);
  });
}
$('#btSortLimpa').onclick = () => { LINHAS = []; desenharSorteio(); $('#sMsg').textContent = ''; };
$('#btSortCsv').onclick = () => {
  if (!LINHAS.length) return;
  const cols = Object.keys(LINHAS[0]);
  const v = x => x === null || x === undefined ? '' : (typeof x === 'number' ? String(x).replace('.', ',') : `"${String(x).replace(/"/g, '""')}"`);
  const txt = '\ufeff' + cols.join(';') + '\n' + LINHAS.map(l => cols.map(c => v(l[c])).join(';')).join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([txt], { type: 'text/csv' }));
  a.download = `random_draw_${new Date().toISOString().slice(0, 16).replace(/[:T-]/g, '')}.csv`; a.click();
};

iniciar().catch(e => { $('#status').textContent = 'Error: ' + e.message; });

// ---------- zoom ----------
function zoom(f) {
  const p = world.pointOfView();
  world.pointOfView({ lat: p.lat, lng: p.lng, altitude: Math.min(Math.max(p.altitude * f, 0.15), 6) }, 400);
}
$('#zMais').onclick = () => zoom(0.7);
$('#zMenos').onclick = () => zoom(1.4);

// ---------- processing / completion pop-ups ----------
function processando(titulo, msg = 'Fetching data from NASA and weather services…') {
  window.__focoAntes = document.activeElement;
  document.querySelector('.popOk')?.remove();
  const logo = document.querySelector('#topo h1.marca svg')?.outerHTML.replace(/ochdr/g, 'ocproc') || '';
  const d = document.createElement('div');
  d.className = 'popOk popProc';
  d.innerHTML = `<div class="popCaixa" role="alertdialog" aria-modal="true" aria-busy="true" aria-labelledby="procT" aria-describedby="procM" tabindex="-1">
    <div class="popLogo pulsa">${logo}</div><span class="selo proc">PROCESSING</span>
    <h2 id="procT">${titulo}</h2>
    <div class="barra" aria-hidden="true"><i></i></div>
    <p id="procM" class="popSub" aria-live="polite">${msg}</p></div>`;
  document.body.appendChild(d);
  d.addEventListener('keydown', ev => { if (ev.key === 'Tab') ev.preventDefault(); });
  d.querySelector('.popCaixa').focus();
}
function etapa(msg) { const m = document.querySelector('#procM'); if (m) m.textContent = msg; }
function concluido(titulo, linhas = [], erros = []) {
  const antes = document.querySelector('.popProc') ? (window.__focoAntes || document.body) : document.activeElement;
  document.querySelector('.popOk')?.remove();
  const ok = !erros.length, parcial = ok ? false : linhas.length > 0;
  const selo = ok ? '<span class="selo ok">✓ COMPLETE</span>' : parcial ? '<span class="selo par">! PARTIAL</span>' : '<span class="selo nao">✕ FAILED</span>';
  const logo = document.querySelector('#topo h1.marca svg')?.outerHTML.replace(/ochdr/g, 'ocpop') || '';
  const d = document.createElement('div');
  d.className = 'popOk';
  d.innerHTML = `<div class="popCaixa" role="alertdialog" aria-modal="true" aria-labelledby="popT" aria-describedby="popD">
    <div class="popLogo">${logo}</div>${selo}
    <h2 id="popT">${ok ? 'Your tests are complete' : titulo}</h2>
    ${ok && titulo !== 'Your tests are complete' ? `<p class="popSub">${titulo}</p>` : ''}
    <ul id="popD">${linhas.map(l => `<li>${l}</li>`).join('')}${erros.map(l => `<li class="erro">${l}</li>`).join('')}</ul>
    <button class="principal" id="popFechar">OK</button></div>`;
  document.body.appendChild(d);
  const fechar = () => { d.remove(); antes?.focus?.(); };
  d.addEventListener('keydown', ev => { if (ev.key === 'Escape' || ev.key === 'Tab') { if (ev.key === 'Escape') fechar(); else ev.preventDefault(); } });
  d.querySelector('#popFechar').onclick = fechar;
  d.onclick = ev => { if (ev.target === d) fechar(); };
  d.querySelector('#popFechar').focus();
}

// ---------- accessibility: keyboard ----------
// clickable table rows become focusable and respond to Enter/Space
new MutationObserver(() => {
  document.querySelectorAll('tr[data-i]:not([tabindex]), tr[data-id]:not([tabindex])').forEach(tr => {
    tr.tabIndex = 0;
    tr.setAttribute('aria-label', 'Select point ' + tr.textContent.replace(/\s+/g, ' ').trim());
  });
}).observe(document.body, { childList: true, subtree: true });
document.addEventListener('keydown', ev => {
  const t = ev.target;
  if ((ev.key === 'Enter' || ev.key === ' ') && t.matches?.('tr[data-i], tr[data-id]')) { ev.preventDefault(); t.click(); }
});
// globe by keyboard: arrows rotate, +/− zoom, Enter selects the center
$('#globo').addEventListener('keydown', ev => {
  const p = world.pointOfView(), passo = Math.max(1, p.altitude * 5);
  const mov = { ArrowUp: [passo, 0], ArrowDown: [-passo, 0], ArrowLeft: [0, -passo], ArrowRight: [0, passo] }[ev.key];
  if (mov) { ev.preventDefault(); world.pointOfView({ lat: Math.max(-89, Math.min(89, p.lat + mov[0])), lng: p.lng + mov[1], altitude: p.altitude }, 200); }
  else if (ev.key === '+' || ev.key === '=') { ev.preventDefault(); zoom(0.7); }
  else if (ev.key === '-' || ev.key === '_') { ev.preventDefault(); zoom(1.4); }
  else if (ev.key === 'Enter') { ev.preventDefault(); definirPonto(p.lat, p.lng); pontoLivre(p.lat, p.lng); $('#status').textContent = `Selected point: ${fmt(p.lat, 2)}°, ${fmt(p.lng, 2)}°`; }
});
