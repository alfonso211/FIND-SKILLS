/* INVERPMS — Grupo INVERSIETE · interfaz web (SPA sin dependencias) */
const S = { token: localStorage.getItem("pms_token"), me: null, cat: null, assets: [], companies: [], asset: "" };
const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const eur = (n) => (n == null ? "" : Number(n).toLocaleString("es-ES", { style: "currency", currency: "EUR" }));
const fdate = (d) => (d ? new Date(d.length === 10 ? d + "T00:00:00" : d).toLocaleDateString("es-ES") : "");
const fdt = (d) => (d ? new Date(d).toLocaleString("es-ES") : "");
const iso = (dt) => dt.toISOString().slice(0, 10);
const today = () => iso(new Date());
const addDays = (d, n) => { const x = new Date(d + "T00:00:00"); x.setDate(x.getDate() + n); return iso(x); };
const can = (p) => !!S.me?.permisos?.[p];
const label = (s) => String(s ?? "").replace(/_/g, " ");
// ---- marca INVERPMS: avatares con iniciales y logotipos (variante clara para fondo blanco)
const iniciales = (n) => String(n ?? "").replace(/[·|(].*$/, "").trim().split(/\s+/).filter((w) => w.length > 2 || /^[A-ZÁÉÍÓÚÑ]/.test(w)).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";
const avatar = (n, cls = "") => `<span class="avatar ${cls}" title="${esc(n)}">${esc(iniciales(n))}</span>`;
const claro = (url) => (url ? url.replace("-oscuro.png", "-claro.png") : "");
const logoActivo = (id, cls = "logo-activo") => { const a = S.assets.find((x) => String(x.id) === String(id)); const url = a?.logo || a?.logo_sociedad; return url ? `<img class="${cls}" src="${claro(url)}" alt="${esc(a.nombre)}">` : ""; };  // sin logo propio: el de la gestora
const rolDe = (me) => (me.is_superadmin ? "Superadministrador" : me.ambitos?.[0]?.rol || "");
const badge = (v) => (v == null || v === "" ? "" : `<span class="badge b-${esc(v)}">${esc(label(v))}</span>`);
const assetName = (id) => S.assets.find((a) => a.id === id)?.nombre ?? id;
const PLURAL = { vivienda: "viviendas", apartamento: "apartamentos", garaje: "garajes", trastero: "trasteros", local: "locales", oficina: "oficinas" };
const plural = (u) => PLURAL[u] || u;
const canOpenOT = () => can("mantenimiento.abrir") || can("mantenimiento.editar");
const assetsOf = (mod) => S.assets.filter((a) => !mod || a.modalidad === mod);

// ------------------------------------------------------------------ API
async function api(method, path, body) {
  const res = await fetch(path, {
    method, headers: { "Content-Type": "application/json", ...(S.token ? { Authorization: `Bearer ${S.token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 401 && S.token) { logout(); throw new Error("Sesión caducada"); }
  nuevaVersion(res.headers.get("X-PMS-Version"));
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw new Error(errMsg(data, res));
  return data;
}
// Tras actualizar el programa en el servidor, la pantalla se recarga sola (sin Ctrl + F5).
// Si hay un formulario abierto espera a que se cierre, para no perder lo que se está tecleando.
function nuevaVersion(v) {
  if (!v || !window.PMS_VERSION || v === window.PMS_VERSION || S.recargando) return;
  S.recargando = true;
  const recargar = () => ($("#modal").open ? setTimeout(recargar, 5000) : location.reload());
  toast("Hay una versión nueva del PMS: se actualiza la pantalla…");
  setTimeout(recargar, 2500);
}
function errMsg(data, res) {
  let msg = data?.detail ?? res.statusText;
  if (Array.isArray(msg)) msg = msg.map((e) => `${e.loc?.slice(-1)[0] ?? ""}: ${e.msg}`).join(" · ");
  return msg;
}
// Descarga un fichero generado por la API (p.ej. un contrato .docx)
async function download(method, path, body) {
  const res = await fetch(path, {
    method, headers: { "Content-Type": "application/json", Authorization: `Bearer ${S.token}` },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(errMsg(await res.json().catch(() => null), res));
  const nombre = (res.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/)?.[1] || "documento";
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(await res.blob()), download: nombre });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  return res;
}
// Envío de ficheros (multipart). No lleva Content-Type: lo pone el navegador con el separador.
async function upload(path, fd) {
  const res = await fetch(path, { method: "POST", headers: { Authorization: `Bearer ${S.token}` }, body: fd });
  if (res.status === 401) { logout(); throw new Error("Sesión caducada"); }
  nuevaVersion(res.headers.get("X-PMS-Version"));
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(errMsg(data, res));
  return data;
}
async function blobUrl(path) {
  const res = await fetch(path, { headers: { Authorization: `Bearer ${S.token}` } });
  if (!res.ok) throw new Error(errMsg(await res.json().catch(() => null), res));
  return URL.createObjectURL(await res.blob());
}
async function abrirFichero(path) {  // abre una foto o PDF en otra pestaña
  const w = window.open("", "_blank");
  try { w.location = await blobUrl(path); } catch (e) { w && w.close(); toast(e.message, true); }
}
const get = (p, q) => api("GET", q ? `${p}?${new URLSearchParams(Object.entries(q).filter(([, v]) => v !== "" && v != null))}` : p);
const post = (p, b = {}) => api("POST", p, b);
const put = (p, b) => api("PUT", p, b);

function toast(msg, err = false) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast show" + (err ? " err" : "");
  clearTimeout(t._h); t._h = setTimeout(() => (t.className = "toast"), 3500);
}
async function run(fn, okMsg) {
  try { const r = await fn(); if (okMsg) toast(typeof okMsg === "function" ? okMsg(r) : okMsg); return r; }
  catch (e) { toast(e.message, true); throw e; }
}

// ------------------------------------------------------------------ tabla genérica
// cols: [{k, t, f?:(v,row)=>html, num?}]   actions: (row)=>[[label, fn, cls?], ...]
function table(el, cols, rows, actions) {
  if (!el) return;  // la vista cambió mientras se cargaban los datos
  if (!rows.length) { el.innerHTML = `<div class="table-wrap"><div class="empty">Sin resultados</div></div>`; return; }
  const head = cols.map((c) => `<th class="${c.num ? "num" : ""}">${esc(c.t)}</th>`).join("") + (actions ? "<th></th>" : "");
  const acts = rows.map((r) => (actions ? actions(r).filter(Boolean) : []));
  const body = rows.map((r, i) => "<tr>" + cols.map((c) => `<td class="${c.num ? "num" : ""}">${c.f ? c.f(r[c.k], r) : esc(r[c.k])}</td>`).join("") +
    (actions ? `<td>${acts[i].map(([l, , cls], j) => `<button class="btn sm ${cls || ""}" data-r="${i}" data-a="${j}">${esc(l)}</button>`).join(" ")}</td>` : "") + "</tr>").join("");
  el.innerHTML = `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>
    <p class="muted">${rows.length} registro(s)</p>`;
  el.querySelectorAll("button[data-r]").forEach((b) => (b.onclick = () => acts[b.dataset.r][b.dataset.a][1](rows[b.dataset.r])));
}

// ------------------------------------------------------------------ formulario modal genérico
// fields: [{k, t, type?: text|number|date|select|textarea|checkbox|email|password, options?: [[v,l]], req?, wide?, step?}]
let formGen = 0;
function form(title, fields, init = {}, onSubmit, submitLabel = "Guardar") {
  const dlg = $("#modal"), f = $("#modalForm"), gen = ++formGen;
  dlg.classList.remove("ancho");
  pararCamara();
  dlg.onclose = pararCamara;
  const input = (fd) => {
    const v = init[fd.k] ?? fd.def ?? "";
    const req = fd.req ? "required" : "";
    if (fd.type === "select")
      return `<select name="${fd.k}" ${req}>${fd.req ? "" : '<option value=""></option>'}${fd.options.map(([o, l]) => `<option value="${esc(o)}" ${String(o) === String(v) ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
    if (fd.type === "textarea") return `<textarea name="${fd.k}" ${req}>${esc(v)}</textarea>`;
    if (fd.type === "checkbox") return `<input type="checkbox" name="${fd.k}" ${v ? "checked" : ""}>`;
    if (fd.type === "checks") {  // varias casillas: el valor es una lista
      const sel = Array.isArray(v) ? v : v ? [v] : [];
      return `<div class="checks">${fd.options.map(([o, l]) => `<label class="check"><input type="checkbox" name="${fd.k}" value="${esc(o)}" ${sel.includes(o) ? "checked" : ""}> ${esc(l)}</label>`).join("")}</div>`;
    }
    return `<input name="${fd.k}" type="${fd.type || "text"}" value="${esc(v)}" ${req} ${fd.step ? `step="${fd.step}"` : fd.type === "number" ? 'step="any"' : ""}>`;
  };
  f.innerHTML = `<h3>${esc(title)}</h3><div class="grid">${fields.map((fd) => fd.html ? `<div class="wide">${fd.html}</div>` :
    fd.type === "checkbox" ? `<label class="check ${fd.wide ? "wide" : ""}">${input(fd)} ${esc(fd.t)}</label>` :
    fd.type === "checks" ? `<fieldset class="wide"><legend>${esc(fd.t)}</legend>${input(fd)}</fieldset>` :
    `<label class="${fd.wide ? "wide" : ""}">${esc(fd.t)}${fd.req ? " *" : ""}${input(fd)}</label>`).join("")}</div>
    <p class="error" id="formErr"></p>
    <div class="actions"><button type="button" class="btn" id="fCancel">Cancelar</button><button class="btn primary" type="submit">${esc(submitLabel)}</button></div>`;
  $("#fCancel").onclick = () => dlg.close();
  if (!f._avisoCampos) {  // el navegador no envía si falta un dato obligatorio: se dice cuál, bien visible
    f._avisoCampos = new Set();
    f.addEventListener("invalid", (ev) => {
      const el = ev.target, lab = el.closest("label, fieldset");
      const nombre = (lab?.querySelector("legend")?.textContent || lab?.childNodes[0]?.textContent || el.name || "").replace("*", "").trim();
      f._avisoCampos.add(`${nombre}${el.validity.valueMissing ? "" : " (valor no válido)"}`);
      clearTimeout(f._avisoT);
      f._avisoT = setTimeout(() => { $("#formErr").textContent = `Revise: ${[...f._avisoCampos].join(", ")}`; f._avisoCampos.clear(); }, 0);
    }, true);
  }
  f.onsubmit = async (ev) => {
    ev.preventDefault();
    const data = {};
    for (const fd of fields) {
      if (!fd.k || fd.html) continue;
      const el = f.elements[fd.k];
      if (fd.type === "checks") { data[fd.k] = [...f.querySelectorAll(`input[name="${fd.k}"]:checked`)].map((x) => x.value); continue; }
      if (fd.type === "checkbox") data[fd.k] = el.checked;
      else if (el.value === "") data[fd.k] = null;
      else data[fd.k] = fd.type === "number" ? Number(el.value) : el.value;
    }
    try { await onSubmit(data, f); if (gen === formGen) dlg.close(); }  // no cerrar si el submit abrió otro formulario
    catch (e) { if (gen === formGen) $("#formErr").textContent = e.message; }
  };
  if (!dlg.open) dlg.showModal();
  ayudasDomicilio(f);
  return f;
}
// Países (lista) y municipios (nomenclátor del INE, filtrado por el C.P.) mientras se escribe
function ayudasDomicilio(f) {
  const campos = (re) => [...f.querySelectorAll("input")].filter((i) => re.test(i.name || ""));
  const paises = campos(/^(cliente_)?(pais|nacionalidad)$/);
  if (paises.length && S.cat?.paises) {
    f.insertAdjacentHTML("beforeend", `<datalist id="dl-paises">${S.cat.paises.map((p) => `<option value="${esc(p)}">`).join("")}</datalist>`);
    paises.forEach((i) => i.setAttribute("list", "dl-paises"));
  }
  campos(/^(cliente_)?municipio$/).forEach((i, n) => {
    const id = `dl-mun-${n}`, cp = f.elements[i.name.replace("municipio", "cp")];
    f.insertAdjacentHTML("beforeend", `<datalist id="${id}"></datalist>`);
    i.setAttribute("list", id); i.setAttribute("autocomplete", "off");
    i.addEventListener("input", debounce(async () => {
      if (i.value.trim().length < 2) return;
      const r = await get("/api/municipios", { q: i.value, cp: cp?.value }).catch(() => []);
      f.querySelector("#" + id).innerHTML = r.map((m) => `<option value="${esc(m.nombre)}">`).join("");
    }, 250));
  });
}
const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== null && v !== ""));
const opts = (arr, v = "id", l = "nombre") => arr.map((x) => [x[v], typeof l === "function" ? l(x) : x[l]]);
const kv = (obj) => Object.entries(obj).map(([k, v]) => [k, v]);
const list = (arr) => arr.map((x) => [x, label(x)]);

function pickAsset(modalidad, perm) {
  const pool = assetsOf(modalidad);
  const cur = pool.find((a) => String(a.id) === String(S.asset));
  if (cur) return Promise.resolve(cur.id);
  if (pool.length === 1) return Promise.resolve(pool[0].id);
  if (!pool.length) { toast("No tiene activos de este tipo", true); return Promise.reject(); }
  return new Promise((resolve) => form("Seleccione activo", [{ k: "asset_id", t: "Activo", type: "select", req: true, options: opts(pool) }],
    {}, async (d) => resolve(Number(d.asset_id)), "Continuar"));
}

// ------------------------------------------------------------------ vistas
const V = {};

V.panel = async (el) => {
  const [p, conPlano] = await Promise.all([get("/api/panel"), get("/api/plano/activos")]);
  if (!p.activos.length) { el.innerHTML = `<div class="empty">No tiene activos asignados.</div>`; return; }
  // Quien ve varios activos: tarjetas de situación interactivas (abren el plano del activo, si lo tiene).
  // Quien solo ve su activo (o filtra uno): situación informativa y las plantas en miniatura para trabajar.
  const varios = S.assets.length > 1 && !S.asset;
  const conMapa = new Set(conPlano.map((a) => a.id));
  const planos = varios ? [] : conPlano.filter((a) => !S.asset || String(a.id) === String(S.asset));
  el.innerHTML = `${planos.map((a) => `<section class="plano-resumen" data-plano="${a.id}"><div class="toolbar"><h3 style="margin:0">${esc(a.nombre)} · plano por plantas</h3><span class="spacer"></span>${leyendaHtml()}</div><div class="minis"><p class="muted">Cargando plano…</p></div></section>`).join("")}
    <p class="muted">Situación a ${fdate(p.fecha)}</p><div class="cards">${p.activos.filter((a) => !S.asset || String(a.id) === String(S.asset)).map((a) => {
    const k = [];
    // los datos del edificio son de los alojamientos: las plazas de garaje van aparte y no computan
    k.push([a.unidades, Object.entries(a.usos || {}).filter(([u]) => u !== "garaje").map(([u, n]) => `${n} ${n === 1 ? u : plural(u)}`).join(" · ") || "Unidades"]);
    if (a.ocupacion_hoy != null) k.push([a.ocupacion_hoy + " %", "Ocupación hoy"]);
    if (a.llegadas_hoy != null) k.push([a.llegadas_hoy, "Llegadas hoy"], [a.salidas_hoy, "Salidas hoy"]);
    if (a.estancias_vencidas) k.push([a.estancias_vencidas, "Estancias vencidas (renovar o salida)", "mal"]);
    if (a.contratos_vigentes != null) {
      const al = a.alquiladas_por_uso || {};
      Object.entries(a.usos || {}).filter(([u]) => u !== "garaje").forEach(([u, n]) => {
        const t = plural(u);
        k.push([`${al[u] || 0} / ${n}`, `${t[0].toUpperCase()}${t.slice(1)} alquilad${["vivienda", "oficina"].includes(u) ? "as" : "os"}`]);
      });
    }
    if (a.produccion_mes != null) k.push([eur(a.produccion_mes), "Producción mes (facturado sin IVA ni garajes)"]);
    if (a.garajes) k.push([`${a.garajes_ocupados} / ${a.garajes}`, "Plazas de garaje alquiladas hoy (no computa)"]);
    else if (a.usos?.garaje && a.alquiladas_por_uso) k.push([`${a.alquiladas_por_uso.garaje || 0} / ${a.usos.garaje}`, "Plazas de garaje alquiladas (no computa)"]);
    if (a.garajes_facturado_mes) k.push([eur(a.garajes_facturado_mes), "Garajes facturados mes (aparte)"]);
    if (a.renta_mensual != null) k.push([eur(a.renta_mensual), "Renta mensual"], [eur(a.deuda_vencida), "Deuda vencida"]);
    if (a.ot_abiertas != null) k.push([a.ot_abiertas, "OT abiertas"], [a.ot_urgentes, "OT urgentes"], [a.ot_pendientes_cierre, "OT pendientes de cierre"]);
    const est = Object.entries(a.estados).map(([e, n]) => `${badge(e)} ${n}`).join(" ");
    const clic = varios && conMapa.has(a.id);
    return `<div class="card${clic ? " clic" : ""}" ${clic ? `data-abrir="${a.id}" tabindex="0" role="button" title="Abrir el plano de ${esc(a.nombre)}"` : ""}>${logoActivo(a.id)}<h3>${esc(a.nombre)}${clic ? '<span class="ver-plano">Ver plano →</span>' : ""}</h3><div class="sub">${esc(a.modalidad_nombre)} · Gestiona ${esc(a.sociedad)} · Propiedad ${esc(a.propietaria)}</div>
      ${a.ocupacion_hoy != null ? `<div class="bar"><i style="width:${Math.min(100, a.ocupacion_hoy)}%"></i></div>` : ""}
      <div class="kpis">${k.map(([v, l, cls]) => `<div class="kpi ${cls || ""}"><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join("")}</div>
      <p style="margin-top:12px">${est || '<span class="muted">Sin unidades dadas de alta</span>'}</p></div>`;
  }).join("")}</div>`;
  el.querySelectorAll("[data-abrir]").forEach((c) => {
    const abrir = () => { S.plano = { asset: Number(c.dataset.abrir) }; go("plano"); };
    c.onclick = abrir; c.onkeydown = (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), abrir());
  });
  pintarMinis(el).catch((e) => el.querySelectorAll(".minis").forEach((m) => (m.innerHTML = `<p class="error">${esc(e.message)}</p>`)));
};

// miniaturas del plano en el panel (se rellenan después para no retrasar el resto)
async function pintarMinis(el) {
  for (const sec of el.querySelectorAll("[data-plano]")) {
    const pl = await get(`/api/plano/${sec.dataset.plano}`);
    $(".minis", sec).innerHTML = pl.plantas.map((x) => `<button class="mini-planta" data-p="${esc(x.planta)}" title="Abrir ${esc(x.etiqueta)}">
        ${gridPlano(pl, x, true)}<b>${esc(x.etiqueta)}</b>${contadores(x.resumen)}</button>`).join("");
    sec.querySelectorAll(".mini-planta").forEach((b) => (b.onclick = () => { S.plano = { asset: pl.asset.id, planta: b.dataset.p }; go("plano"); }));
  }
}

// ------------------------------------------------------------------ plano por plantas
// Colores del PMS anterior: alquilado (cian), reserva (salmón), disponible (verde), bloqueado (oliva)
const ESTADOS_PLANO = [["alquilado", "Alquilados"], ["reserva", "Reservas"], ["disponible", "Disponibles"], ["bloqueado", "Bloqueados"]];
const ESTADO_TXT = { alquilado: "Alquilado", reserva: "Reserva", disponible: "Disponible", bloqueado: "Bloqueado" };
const leyendaHtml = () => `<span class="leyenda">${ESTADOS_PLANO.map(([k, t]) => `<span><i class="pc-${k}"></i>${t}</span>`).join("")}<span><i class="pc-zc"></i>Zonas comunes</span></span>`;
const contadores = (r) => `<span class="contadores">${ESTADOS_PLANO.map(([k]) => `<span class="pc-${k}" title="${ESTADO_TXT[k]}">${r[k]}</span>`).join("")}</span>`;
const DECOR = { asc: "", esc: "", escA: "", escB: "", pis: "", jar: "", acc: "←", pat: "", ter: "Ter" };
function gridPlano(pl, planta, mini = false) {
  const celdas = planta.celdas.map((c) => {
    const pos = `grid-row:${c.f};grid-column:${c.c}`;
    if (c.t === "u") {
      const tip = `${c.codigo} · ${c.tipologia || ""} · ${ESTADO_TXT[c.estado]}${c.vencida ? " · ESTANCIA VENCIDA" : ""}${c.reserva ? ` · ${c.reserva.proxima ? "próxima llegada: " : ""}${c.reserva.huesped} ${fdate(c.reserva.entrada)} → ${fdate(c.reserva.salida)}` : ""}${c.alquiler ? ` · alquiler mensual: ${c.alquiler.cliente}${c.alquiler.matricula ? " (" + c.alquiler.matricula + ")" : ""}` : ""}${c.ot ? ` · ${c.ot} incidencia(s) abierta(s)` : ""}${c.limpieza ? " · pendiente de limpieza" : ""}`;
      return `<div class="pc u pc-${c.estado}" style="${pos}" data-u="${c.unit_id}" title="${esc(tip)}">${mini ? "" : `<b>${esc(c.num)}</b><small>${esc(c.tipo)}</small>${c.ot ? `<span class="m${c.urgente ? " urg" : ""}">M</span>` : ""}${c.limpieza ? '<span class="lim" title="Pendiente de limpieza">L</span>' : ""}${c.vencida ? '<span class="venc" title="Estancia vencida: renovar o dar la salida">V</span>' : ""}`}</div>`;
    }
    if (c.t === "zc") return `<div class="pc zc pc-zc" style="${pos}" data-z="${esc(c.zona)}" title="${esc(c.nombre)}${c.ot ? ` · ${c.ot} incidencia(s) abierta(s)` : ""}">${mini ? "" : `<b>ZC</b>${c.ot ? `<span class="m${c.urgente ? " urg" : ""}">${c.ot}</span>` : ""}`}</div>`;
    if (c.t === "falta") return `<div class="pc falta" style="${pos}" title="El ${esc(c.num)} no existe en las unidades del PMS">${mini ? "" : esc(c.num) + "?"}</div>`;
    if (c.t === "lbl") return `<div class="pc lbl lbl-${esc(c.texto)}" style="${pos}">${mini ? "" : esc(c.texto)}</div>`;
    const TIT = { acc: "Entrada", pis: "Piscina", jar: "Jardín", asc: "Ascensor", esc: "Escalera", escA: "Escalera bloque A", escB: "Escalera bloque B", ter: "Terraza", portal: `Portal ${c.texto}`, plaza: "Patio", tarima: "Solárium", rampa: "Rampa", sentido: "Sentido de circulación", entrada: "Entrada de vehículos", salida: "Salida de vehículos", muro: "Muro", puerta: "Puerta peatonal", arbol: "Arbolado" };
    return `<div class="pc ${c.t}" style="${pos}"${TIT[c.t] ? ` title="${TIT[c.t]}"` : ""}>${mini ? "" : esc(c.texto || DECOR[c.t] || "")}</div>`;
  }).join("");
  const cols = planta.columnas || pl.columnas, filas = planta.filas || pl.filas;
  return `<div class="plano${mini ? " mini" : ""}${cols > 20 ? " denso" : ""}${cols > 36 ? " muy-denso" : ""}" style="grid-template-columns:repeat(${cols},minmax(0,1fr));grid-template-rows:repeat(${filas},minmax(0,1fr));aspect-ratio:${cols}/${filas}">${celdas}</div>`;
}

V.plano = async (el) => {
  const activos = await get("/api/plano/activos");
  if (!activos.length) { el.innerHTML = '<div class="empty">Ningún activo de su ámbito tiene plano.</div>'; return; }
  S.plano = S.plano || {};
  const elegido = activos.find((a) => a.id === S.plano.asset) || activos.find((a) => String(a.id) === String(S.asset)) || activos[0];
  S.plano.asset = elegido.id;
  const fecha = S.plano.fecha || today();
  el.innerHTML = `<div class="toolbar">${activos.length > 1 ? `<select id="pa">${activos.map((a) => `<option value="${a.id}" ${a.id === elegido.id ? "selected" : ""}>${esc(a.nombre)}</option>`).join("")}</select>` : `<strong>${esc(elegido.nombre)}</strong>`}${logoActivo(elegido.id)}
    <span id="tabs" class="tabs"></span><span class="spacer"></span>
    <label>Fecha<input type="date" id="pf" value="${fecha}"></label><button class="btn" id="hoy">Hoy</button><button class="btn" id="imp">Imprimir</button></div>
    <div class="plano-vista"><div id="grid" class="plano-wrap"><p class="muted">Cargando…</p></div><aside id="lat" class="plano-lat"></aside></div>`;
  let datos;
  const pinta = () => {
    const planta = datos.plantas.find((x) => x.planta === S.plano.planta) || datos.plantas[0];
    S.plano.planta = planta.planta;
    $("#tabs", el).innerHTML = datos.plantas.map((x) => `<button class="btn ${x.planta === planta.planta ? "primary" : ""}" data-p="${esc(x.planta)}">${esc(x.etiqueta)}</button>`).join("");
    $("#tabs", el).querySelectorAll("button").forEach((b) => (b.onclick = () => { S.plano.planta = b.dataset.p; pinta(); }));
    $("#grid", el).innerHTML = gridPlano(datos, planta);
    const r = planta.resumen;
    $("#lat", el).innerHTML = `<h4>${esc(datos.asset.nombre)}</h4><p class="muted">${esc(planta.etiqueta)} · ${fdate(datos.fecha)}</p>
      <div class="marcadores">${ESTADOS_PLANO.map(([k, t]) => `<div><i class="pc-${k}"></i><span>${t}</span><b>${r[k]}</b></div>`).join("")}
      <div class="total"><span>${planta.planta.startsWith("-") ? "Plazas en el sótano" : "Total en planta"}</span><b>${r.total}</b></div></div>
      <div class="marcadores ayuda"><div><i class="pc-zc"></i><span>Zona común: incidencias de ese lado del edificio</span></div>
      <div><span class="m-ej" style="background:#fff;color:#111;border-color:#111">←</span><span>${datos.asset.codigo === "SAE" ? "Entrada del edificio. Entrando: bloque A a la derecha, bloque B a la izquierda" : datos.asset.codigo === "SFL" ? "Entrada. Entrando: portales 2 y 3 a la derecha (arriba), 1 y 4 a la izquierda (abajo). Zona común de cada portal junto a su número" : "Entrada"}</span></div>
      <div><span class="m-ej">M</span><span>Mantenimiento pendiente (rojo: urgente)</span></div><div><span class="m-ej venc">V</span><span>Estancia vencida: renovar o dar la salida</span></div><div><span class="m-ej lim">L</span><span>Pendiente de limpieza</span></div></div>
      <p class="muted">Pulse un apartamento para ver su ficha completa, reservar, bloquear o abrir una incidencia.</p>`;
    $("#grid", el).querySelectorAll("[data-u]").forEach((c) => (c.onclick = () => fichaApartamento(Number(c.dataset.u), recarga)));
    $("#grid", el).querySelectorAll("[data-z]").forEach((c) => (c.onclick = () => zonaComun(datos.asset.id, c.dataset.z, recarga)));
  };
  const recarga = async () => { datos = await get(`/api/plano/${S.plano.asset}`, { fecha: $("#pf", el)?.value }); if ($("#grid", el)) pinta(); };
  $("#pf", el).onchange = () => { S.plano.fecha = $("#pf", el).value; recarga(); };
  $("#hoy", el).onclick = () => { $("#pf", el).value = today(); S.plano.fecha = null; recarga(); };
  $("#imp", el).onclick = () => window.print();
  if ($("#pa", el)) $("#pa", el).onchange = () => { S.plano = { asset: Number($("#pa", el).value) }; go("plano"); };
  await recarga();
  // el plano se refresca solo cada 30 s (reservas hechas desde otro puesto); no mientras hay una ficha abierta
  clearInterval(S.planoTimer);
  S.planoTimer = setInterval(() => {
    if (!document.body.contains(el)) return clearInterval(S.planoTimer);
    if (!$("#modal").open && !document.hidden) recarga().catch(() => {});
  }, 30000);
};

// Ficha del apartamento: estado, acciones y buscador sobre todo lo registrado
const normaliza = (t) => String(t ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
function cerrarSolo(f) { const b = $("button[type=submit]", f); if (b) b.remove(); $("#fCancel", f).textContent = "Cerrar"; return f; }
async function fichaApartamento(uid, recarga) {
  const d = await run(() => get(`/api/plano/unidades/${uid}/ficha`));
  const u = d.unidad;
  const garaje = u.uso === "garaje";
  const items = [];
  (d.reservas || []).forEach((r) => items.push({ tipo: "reserva", fecha: r.entrada, texto: [r.localizador, r.huesped, r.documento, r.canal, r.estado, r.notas].join(" "),
    html: `<b>Reserva ${esc(r.localizador || "R-" + r.id)}</b> · ${fdate(r.entrada)} → ${fdate(r.salida)} (${r.noches} noches) · ${esc(r.huesped)} · ${badge(r.estado)}${r.proxima ? ' <span class="badge b-pendiente">próxima</span>' : ""}<br><span class="muted">${esc(r.canal)} · ${r.adultos + r.ninos} pax · ${eur(r.importe_total)} (cobrado ${eur(r.importe_pagado)})${r.contrato ? " · contrato impreso" : ""}</span>`,
    acc: can("reservas.editar") ? [...(garaje ? [] : [["Contrato", () => accommodationContract({ id: r.id, unidad: u.codigo, huesped: r.huesped })]]),
      ...(!garaje && ["confirmada", "checkin"].includes(r.estado) ? [["Renovar", () => renovarEstancia({ id: r.id, unidad: u.codigo, huesped: r.huesped }, recarga)]] : []),
      ["Huésped", () => editGuest(r.guest_id)]] : [] }));
  const clientes = new Map();
  (d.reservas || []).forEach((r) => { const c = clientes.get(r.guest_id) || { ...r, estancias: 0 }; c.estancias += 1; clientes.set(r.guest_id, c); });
  clientes.forEach((c) => items.push({ tipo: "cliente", fecha: c.entrada, texto: [c.huesped, c.documento, c.telefono, c.email, c.nacionalidad].join(" "),
    html: `<b>${esc(c.huesped)}</b> · ${c.estancias} estancia(s)<br><span class="muted">${esc([c.documento, c.nacionalidad, c.telefono, c.email].filter(Boolean).join(" · "))}</span>`,
    acc: can("reservas.editar") ? [["Ficha", () => editGuest(c.guest_id)]] : [] }));
  (d.alquileres || []).forEach((a) => items.push({ tipo: "alquiler", fecha: a.desde, texto: [a.cliente, a.telefono, a.matricula, a.estado].join(" "),
    html: `<b>Alquiler mensual · ${esc(a.cliente)}</b> · desde ${fdate(a.desde)}${a.hasta ? " hasta " + fdate(a.hasta) : " (indefinido)"} · ${badge(a.estado)}<br><span class="muted">${eur(a.renta_mensual)}/mes + IVA${a.matricula ? " · " + esc(a.matricula) : ""}${a.telefono ? " · " + esc(a.telefono) : ""}</span>`,
    acc: [["Ver", () => { $("#modal").close(); location.hash = "garajes"; }]] }));
  (d.incidencias || []).forEach((w) => items.push({ tipo: "incidencia", fecha: w.fecha_apertura, texto: [w.titulo, w.descripcion, w.categoria, w.estado, w.solucion, w.proveedor, w.abierta_por, "OT-" + w.id].join(" "),
    html: `<b>OT-${String(w.id).padStart(5, "0")} · ${esc(w.titulo)}</b> · ${badge(w.prioridad)} ${badge(w.estado)}<br><span class="muted">${fdate(w.fecha_apertura)} · ${esc(w.categoria)}${w.abierta_por ? " · aviso de " + esc(w.abierta_por) : ""}${w.solucion ? " · " + esc(w.solucion) : ""}</span>`,
    acc: [["📎", () => adjuntosOT(w)], ["Parte PDF", () => run(() => download("GET", `/api/mantenimiento/ordenes/${w.id}/parte`))]] }));
  (d.bloqueos || []).forEach((b) => items.push({ tipo: "bloqueo", fecha: b.desde.slice(0, 10), texto: [b.motivo, b.usuario, b.nota_levantado].join(" "),
    html: `<b>Bloqueo</b> · ${esc(b.motivo)}<br><span class="muted">${fdt(b.desde)}${b.usuario ? " · " + esc(b.usuario) : ""}${b.hasta ? " · previsto hasta " + fdate(b.hasta) : ""} · ${b.levantado ? "levantado " + fdt(b.levantado) + (b.nota_levantado ? " (" + esc(b.nota_levantado) + ")" : "") : "<b>vigente</b>"}</span>`, acc: [] }));
  (d.facturas || []).forEach((x) => items.push({ tipo: "factura", fecha: x.fecha, texto: [x.codigo, x.cliente].join(" "),
    html: `<b>Factura ${esc(x.codigo)}</b> · ${esc(x.cliente)} · ${eur(x.total)}${x.tipo === "rectificativa" ? " · rectificativa" : ""}`, acc: [["PDF", () => descargarFactura(x.id)]] }));
  items.sort((a, b) => (a.fecha < b.fecha ? 1 : -1));
  const TIPOS = [["", "Todo"], ["alquiler", "Alquileres"], ["reserva", "Reservas"], ["cliente", "Clientes"], ["incidencia", "Incidencias"], ["bloqueo", "Bloqueos"], ["factura", "Facturas"]].filter(([t]) => !t || items.some((i) => i.tipo === t));
  const bloqueoVigente = (d.bloqueos || []).find((b) => !b.levantado);
  const actual = d.alquiler ? `<p><b>Alquilada por meses a:</b> ${esc(d.alquiler.cliente)} · desde ${fdate(d.alquiler.desde)}${d.alquiler.hasta ? " hasta " + fdate(d.alquiler.hasta) : ""}${d.alquiler.matricula ? " · " + esc(d.alquiler.matricula) : ""}</p>`
    : d.actual ? `<p><b>${d.estado === "alquilado" ? "Alojado" : d.actual.proxima ? "Próxima llegada" : "Llega hoy"}:</b> ${esc(d.actual.huesped)} · ${fdate(d.actual.entrada)} → ${fdate(d.actual.salida)}</p>` : "";
  const acciones = [
    d.puede.reservar && ["reserva", "Reserva", garaje ? "Por días o semanas (huésped o cliente)" : "Nueva reserva en este apartamento"],
    d.puede.alquilar && !d.alquiler && ["alquiler", "Alquiler mensual", "Cliente externo: recibo cada mes y factura al 21 %"],
    d.puede.bloquear && (d.estado === "bloqueado" ? ["desbloquear", "Bloqueado", bloqueoVigente ? `Motivo: ${bloqueoVigente.motivo}. Pulse para desbloquear` : "Pulse para desbloquear"] : ["bloqueo", "Bloqueado", "Sacarlo de venta indicando el motivo"]),
    d.puede.incidencia && ["incidencia", "Incidencia", "Abrir una incidencia (avería) con fotos"],
  ].filter(Boolean);
  const f = cerrarSolo(form(garaje ? `Plaza de garaje ${u.codigo} · ${u.bloque || ""}` : `Apartamento ${u.codigo} · ${u.tipologia || ""}`, [
    { html: `<p><span class="estado-ap pc-${d.estado}">${ESTADO_TXT[d.estado]}</span> ${u.bloque ? esc(u.bloque) + " · " : ""}planta ${esc(u.planta || "")}${u.capacidad ? ` · ${u.capacidad} plazas` : ""}${d.limpieza ? ' · <span class="badge b-pendiente_limpieza">pendiente de limpieza</span>' : ""}</p>${actual}
      <div class="acciones-ap">${acciones.map(([k, t, ayuda]) => `<button type="button" class="accion-ap ${k === "desbloquear" ? "marcada" : ""}" data-acc="${k}"><span class="caja">${k === "desbloquear" ? "☑" : "☐"}</span><b>${t}</b><small>${esc(ayuda)}</small></button>`).join("")}</div>
      <div class="buscador"><input type="search" placeholder="Buscar en este apartamento: cliente, reserva, documento, incidencia, bloqueo, factura…" data-q>
      <div class="chips">${TIPOS.map(([t, n]) => `<button type="button" class="chip ${t ? "" : "on"}" data-t="${t}">${n}</button>`).join("")}</div></div>
      <div class="resultados" data-res></div>` },
  ], {}, async () => {}));
  $("#modal").classList.add("ancho");
  let filtroTipo = "";
  const pintaRes = () => {
    const q = normaliza($("[data-q]", f).value).split(/\s+/).filter(Boolean);
    const vis = items.filter((i) => (!filtroTipo || i.tipo === filtroTipo) && q.every((w) => normaliza(i.texto + " " + i.tipo).includes(w)));
    $("[data-res]", f).innerHTML = vis.length ? vis.slice(0, 200).map((i, n) => `<div class="res"><span class="tipo t-${i.tipo}">${i.tipo}</span><div>${i.html}</div><div class="res-acc">${i.acc.map(([l], j) => `<button type="button" class="btn sm" data-i="${items.indexOf(i)}" data-j="${j}">${esc(l)}</button>`).join("")}</div></div>`).join("")
      : `<p class="muted">${items.length ? "Sin resultados para esa búsqueda." : "Este apartamento aún no tiene nada registrado."}</p>`;
    $("[data-res]", f).querySelectorAll("button[data-i]").forEach((b) => (b.onclick = () => items[b.dataset.i].acc[b.dataset.j][1]()));
  };
  $("[data-q]", f).oninput = pintaRes;
  f.querySelectorAll(".chip").forEach((c) => (c.onclick = () => { filtroTipo = c.dataset.t; f.querySelectorAll(".chip").forEach((x) => x.classList.toggle("on", x === c)); pintaRes(); }));
  pintaRes();
  const fija = { id: u.id, codigo: u.codigo, asset_id: u.asset_id, uso: u.uso };
  f.querySelectorAll("[data-acc]").forEach((b) => (b.onclick = () => {
    const acc = b.dataset.acc;
    if (acc === "reserva") newReservation(recarga, fija);
    if (acc === "alquiler") alquilarGaraje(recarga, fija);
    if (acc === "incidencia") newWorkOrder(u.asset_id, u.id).then(recarga);
    if (acc === "bloqueo") form(`Bloquear apartamento ${u.codigo}`, [
      { html: '<p class="muted">El apartamento queda fuera de venta (no admite reservas) hasta que se desbloquee. Queda registrado quién lo bloquea y por qué.</p>' },
      { k: "motivo", t: "Motivo del bloqueo", type: "textarea", req: true, wide: true }, { k: "hasta", t: "Fin previsto (opcional)", type: "date" },
    ], {}, async (x) => {
      const r = await post(`/api/plano/unidades/${u.id}/bloquear`, clean(x));
      toast(`Apartamento ${u.codigo} bloqueado`); await recarga();
      if (r.reservas_afectadas.length) setTimeout(() => cerrarSolo(form("Atención: reservas afectadas por el bloqueo", [{ html: `<p>Hay reservas confirmadas en este apartamento. Cámbielas de apartamento o avise al cliente:</p><ul>${r.reservas_afectadas.map((a) => `<li>${esc(a.localizador || "R-" + a.id)} · ${esc(a.huesped)} · ${fdate(a.entrada)} → ${fdate(a.salida)}</li>`).join("")}</ul>` }], {}, async () => {})), 0);
    }, "Bloquear");
    if (acc === "desbloquear") form(`Desbloquear apartamento ${u.codigo}`, [
      { html: `<p>${bloqueoVigente ? `Bloqueado desde ${fdt(bloqueoVigente.desde)}${bloqueoVigente.usuario ? " por " + esc(bloqueoVigente.usuario) : ""}. Motivo: <b>${esc(bloqueoVigente.motivo)}</b>` : `Estado actual: ${esc(label(u.estado))}`}</p>` },
      { k: "nota", t: "Nota (p.ej. trabajo terminado)", wide: true },
    ], {}, async (x) => { await post(`/api/plano/unidades/${u.id}/desbloquear`, clean(x)); toast(`Apartamento ${u.codigo} disponible`); await recarga(); }, "Desbloquear");
  }));
}

async function zonaComun(assetId, zona, recarga) {
  const z = await run(() => get(`/api/plano/${assetId}/zonas/${encodeURIComponent(zona)}`));
  const ots = z.incidencias || [];
  const f = cerrarSolo(form(`Zona común · ${z.nombre}`, [
    { html: `${z.puede.incidencia ? '<div class="acciones-ap"><button type="button" class="accion-ap" data-nueva><span class="caja">☐</span><b>Incidencia</b><small>Abrir una incidencia en esta zona común</small></button></div>' : ""}
      <div class="buscador"><input type="search" placeholder="Buscar en las incidencias de esta zona…" data-q></div><div class="resultados" data-res></div>` },
  ], {}, async () => {}));
  const pinta = () => {
    const q = normaliza($("[data-q]", f).value);
    const vis = ots.filter((w) => normaliza([w.titulo, w.descripcion, w.estado, w.categoria, w.solucion].join(" ")).includes(q));
    $("[data-res]", f).innerHTML = vis.length ? vis.map((w) => `<div class="res"><span class="tipo t-incidencia">incidencia</span><div><b>OT-${String(w.id).padStart(5, "0")} · ${esc(w.titulo)}</b> · ${badge(w.prioridad)} ${badge(w.estado)}<br><span class="muted">${fdate(w.fecha_apertura)} · ${esc(w.categoria)}${w.abierta_por ? " · aviso de " + esc(w.abierta_por) : ""}</span></div>
      <div class="res-acc"><button type="button" class="btn sm" data-adj="${w.id}">📎</button><button type="button" class="btn sm" data-parte="${w.id}">Parte PDF</button></div></div>`).join("") : '<p class="muted">Sin incidencias registradas en esta zona.</p>';
    $("[data-res]", f).querySelectorAll("[data-adj]").forEach((b) => (b.onclick = () => adjuntosOT(ots.find((w) => w.id === Number(b.dataset.adj)))));
    $("[data-res]", f).querySelectorAll("[data-parte]").forEach((b) => (b.onclick = () => run(() => download("GET", `/api/mantenimiento/ordenes/${b.dataset.parte}/parte`))));
  };
  $("[data-q]", f).oninput = pinta; pinta();
  const nueva = $("[data-nueva]", f);
  if (nueva) nueva.onclick = () => newWorkOrder(assetId, null, { zona: z.zona, nombre: z.nombre }).then(recarga);
}

V.activos = async (el) => {
  const rows = await get("/api/activos");
  el.innerHTML = `<div class="toolbar"><span class="spacer"></span>${can("activos.editar") ? '<button class="btn primary" id="new">Nuevo activo</button>' : ""}</div><div id="t"></div>`;
  const fields = (isNew) => [
    ...(isNew ? [{ k: "codigo", t: "Código", req: true }] : []),
    { k: "nombre", t: "Nombre", req: true },
    { k: "company_id", t: "Sociedad gestora (explotación y accesos)", type: "select", req: true, options: opts(S.companies) },
    { k: "propietaria_id", t: "Sociedad propietaria del inmueble", type: "select", options: opts(S.companies) },
    ...(isNew ? [{ k: "modalidad", t: "Modalidad", type: "select", req: true, options: kv(S.cat.modalidades) }] : []),
    { k: "direccion", t: "Dirección", wide: true }, { k: "municipio", t: "Municipio" }, { k: "provincia", t: "Provincia" },
    { k: "cp", t: "C.P." }, { k: "ref_catastral", t: "Ref. catastral" }, { k: "num_registro_turistico", t: "Nº registro turístico" },
    { k: "ses_codigo_establecimiento", t: "Código de establecimiento SES.HOSPEDAJE" },
    { html: "<h4>Facturación</h4><p class='muted'>Factura la sociedad gestora. Cada activo tiene su serie y la numeración es correlativa por año (p.ej. SF/00001/2026). No cambie la serie de un activo que ya tiene facturas del año en curso.</p>" },
    { k: "serie_factura", t: "Serie de facturas (p.ej. B35, SF, SA)" },
    { html: "<h4>Datos de la empresa en los contratos de alojamiento</h4>" },
    { k: "contrato_representante", t: "Representante (firma por la empresa)" }, { k: "contrato_representante_dni", t: "DNI del representante" },
    { k: "contrato_email", t: "Correo para notificaciones", type: "email" },
    { k: "activo", t: "Activo en explotación", type: "checkbox", def: true }, { k: "notas", t: "Notas", type: "textarea", wide: true },
  ];
  const edit = (a) => form(a ? `Editar ${a.nombre}` : "Nuevo activo", fields(!a), a || {}, async (d) => {
    if (d.serie_factura) d.serie_factura = d.serie_factura.trim().toUpperCase();
    if (a) await put(`/api/activos/${a.id}`, d); else await post("/api/activos", clean(d));
    toast("Activo guardado"); await loadAssets(); go("activos");
  });
  if ($("#new", el)) $("#new", el).onclick = () => edit(null);
  table($("#t", el), [
    { k: "logo", t: "", f: (v, a) => (v ? `<img class="logo-tabla" src="${claro(v)}" alt="">` : `<span class="avatar sm">${esc(a.codigo.slice(0, 2))}</span>`) },
    { k: "codigo", t: "Código" }, { k: "nombre", t: "Nombre" }, { k: "modalidad_nombre", t: "Modalidad" },
    { k: "sociedad", t: "Gestora" }, { k: "propietaria", t: "Propietaria" }, { k: "municipio", t: "Municipio" }, { k: "num_unidades", t: "Unidades", num: true },
    { k: "serie_factura", t: "Serie facturas" },
    { k: "activo", t: "Estado", f: (v) => (v ? badge("vigente") : badge("baja")) },
  ], rows, (a) => [["Unidades", () => { setAsset(a.id); go("unidades"); }], can("activos.editar") && ["Editar", () => edit(a)]]);
};

V.unidades = async (el) => {
  const bloques = S.asset ? await get("/api/unidades/bloques", { asset_id: S.asset }) : [];
  el.innerHTML = `<div class="toolbar"><input id="q" placeholder="Buscar código / tipología">
    ${bloques.length ? `<select id="blq"><option value="">Todos los bloques</option>${bloques.map((b) => `<option>${esc(b)}</option>`).join("")}</select>` : ""}
    <select id="uso"><option value="">Todos los usos</option>${S.cat.usos_unidad.map((u) => `<option value="${u}">${label(u)}</option>`).join("")}</select>
    <select id="est"><option value="">Todos los estados</option>${S.cat.estados_unidad.map((e) => `<option value="${e}">${label(e)}</option>`).join("")}</select>
    <span class="spacer"></span>${can("activos.editar") ? '<button class="btn" id="bulk">Alta masiva</button><button class="btn primary" id="new">Nueva unidad</button>' : ""}</div><div id="t"></div>`;
  const fields = [
    { k: "codigo", t: "Código", req: true }, { k: "bloque", t: "Bloque / portal" },
    { k: "uso", t: "Uso", type: "select", req: true, options: list(S.cat.usos_unidad), def: "vivienda" },
    { k: "tipologia", t: "Tipología" }, { k: "planta", t: "Planta" },
    { k: "superficie_m2", t: "Superficie m²", type: "number" }, { k: "dormitorios", t: "Dormitorios", type: "number", step: 1 },
    { k: "capacidad", t: "Capacidad (plazas)", type: "number", step: 1 }, { k: "ref_catastral", t: "Ref. catastral" },
    { k: "estado", t: "Estado", type: "select", req: true, options: list(S.cat.estados_unidad), def: "disponible" },
    { k: "renta_base", t: "Renta base €/mes", type: "number" }, { k: "tarifa_base_noche", t: "Tarifa base €/noche", type: "number" },
    { k: "coef_participacion", t: "Coef. participación %", type: "number" }, { k: "cuota_comunidad", t: "Cuota comunidad €/mes", type: "number" },
    { k: "anejos", t: "Anejos (trasteros, plazas)" },
    { k: "notas", t: "Notas", type: "textarea", wide: true },
  ];
  const load = async () => {
    const rows = await get("/api/unidades", { asset_id: S.asset, estado: $("#est", el).value, q: $("#q", el).value, uso: $("#uso", el).value, bloque: $("#blq", el)?.value });
    table($("#t", el), [
      { k: "asset_id", t: "Activo", f: (v) => esc(assetName(v)) }, { k: "bloque", t: "Bloque" }, { k: "codigo", t: "Unidad" },
      { k: "uso", t: "Uso", f: (v) => esc(label(v)) }, { k: "tipologia", t: "Tipología" },
      { k: "planta", t: "Planta" }, { k: "superficie_m2", t: "m²", num: true }, { k: "anejos", t: "Anejos" },
      { k: "coef_participacion", t: "Coef. %", num: true }, { k: "cuota_comunidad", t: "Cuota com.", num: true, f: eur },
      { k: "estado", t: "Estado", f: badge },
    ], rows, (u) => [
      u.estado === "pendiente_limpieza" && (can("limpieza.editar") || can("activos.editar")) &&
        ["Limpia ✓", () => run(() => post(`/api/unidades/${u.id}/limpia`), "Unidad disponible").then(load)],
      can("activos.editar") && ["Editar", () => form(`Unidad ${u.codigo}`, fields, u, async (d) => { await put(`/api/unidades/${u.id}`, d); toast("Guardado"); load(); })],
      canOpenOT() && ["Avería", () => newWorkOrder(u.asset_id, u.id).then(load)],
    ]);
  };
  $("#q", el).oninput = debounce(load); $("#est", el).onchange = load; $("#uso", el).onchange = load;
  if ($("#blq", el)) $("#blq", el).onchange = load;
  if ($("#new", el)) {
    $("#new", el).onclick = async () => { const aid = await pickAsset(); form("Nueva unidad", fields, {}, async (d) => { await post("/api/unidades", clean({ ...d, asset_id: aid })); toast("Unidad creada"); load(); }); };
    $("#bulk", el).onclick = async () => {
      const aid = await pickAsset();
      form(`Alta masiva en ${assetName(aid)}`, [
        { k: "prefijo", t: "Prefijo (p.ej. P1-1)" }, { k: "bloque", t: "Bloque / portal" },
        { k: "uso", t: "Uso", type: "select", req: true, options: list(S.cat.usos_unidad), def: "vivienda" }, { k: "desde", t: "Desde nº", type: "number", req: true, def: 1 },
        { k: "hasta", t: "Hasta nº", type: "number", req: true }, { k: "digitos", t: "Dígitos", type: "number", def: 3 },
        { k: "tipologia", t: "Tipología" }, { k: "capacidad", t: "Plazas", type: "number" },
        { k: "renta_base", t: "Renta base €/mes", type: "number" }, { k: "tarifa_base_noche", t: "Tarifa €/noche", type: "number" },
      ], {}, async (d) => { const r = await post("/api/unidades/masivo", clean({ ...d, prefijo: d.prefijo || "", asset_id: aid })); toast(`${r.creadas} unidades creadas, ${r.omitidas} ya existían`); load(); });
    };
  }
  load();
};

// ---- turístico
const resCols = [
  { k: "localizador", t: "Localizador" }, { k: "asset_id", t: "Activo", f: (v) => esc(assetName(v)) }, { k: "unidad", t: "Unidad" },
  { k: "huesped", t: "Huésped" }, { k: "fecha_entrada", t: "Entrada", f: fdate }, { k: "fecha_salida", t: "Salida", f: fdate },
  { k: "noches", t: "Noches", num: true }, { k: "adultos", t: "Pax", num: true, f: (v, r) => v + r.ninos }, { k: "canal", t: "Canal" },
  { k: "importe_total", t: "Importe", num: true, f: eur },
  { k: "importe_pagado", t: "Cobrado", num: true, f: (v, r) => eur(v) + (r.importe_total - v > 0.004 && v > 0 ? ' <span class="badge b-parcial">parcial</span>' : "") },
  { k: "estado", t: "Estado", f: badge },
];
// ---- cobros y facturas: al registrar un cobro se emite la factura y se descarga en PDF
const descargarFactura = (id) => download("GET", `/api/facturas/${id}/pdf`).catch((e) => toast(e.message, true));
// Líneas de servicios (limpieza, aparcamiento...) dentro de una factura: del catálogo o escritas a mano
function serviciosHtml(titulo = "Servicios (IVA 21 % salvo que se indique otro)") {
  return `<fieldset class="servicios"><legend>${esc(titulo)}</legend><div data-lineas></div>
    <button type="button" class="btn sm" data-addsrv>+ Añadir servicio</button> <span class="muted" data-srvtot></span></fieldset>`;
}
async function bindServicios(f, assetId, inicial = 0) {
  const cat = await get("/api/servicios", { asset_id: assetId });
  const cont = $("[data-lineas]", f);
  if (!cont) return;
  const total = () => {
    const t = leerServicios(f).reduce((a, x) => a + (x.precio || 0) * x.cantidad, 0);
    $("[data-srvtot]", f).textContent = t ? `Servicios: ${eur(t)} (IVA incluido)` : "";
  };
  const fila = () => {
    cont.insertAdjacentHTML("beforeend", `<div class="srv-fila">
      <select data-s><option value="">— Otro (escribir) —</option>${cat.map((x) => `<option value="${x.id}" data-precio="${x.precio ?? ""}" data-iva="${x.tipo_iva}">${esc(x.nombre)}${x.unidad !== "ud" ? " (" + esc(x.unidad) + ")" : ""}${x.precio != null ? " · " + eur(x.precio) : ""}</option>`).join("")}</select>
      <input data-c placeholder="Concepto" hidden><input data-n type="number" step="any" min="0" value="1" title="Cantidad">
      <input data-p type="number" step="0.01" min="0" placeholder="Precio € IVA incl." title="Precio unitario, IVA incluido">
      <select data-i title="IVA">${[21, 10, 4, 0].map((v) => `<option value="${v}">${v ? v + " %" : "Exento"}</option>`).join("")}</select>
      <button type="button" class="btn sm danger" data-x>✕</button></div>`);
    const r = cont.lastElementChild;
    const sel = $("[data-s]", r);
    sel.onchange = () => {
      const o = sel.selectedOptions[0];
      $("[data-c]", r).hidden = !!sel.value;
      if (sel.value) { $("input[data-p]", r).value = o.dataset.precio; $("select[data-i]", r).value = String(Number(o.dataset.iva)); }
      total();
    };
    sel.onchange();
    r.querySelectorAll("input,select").forEach((i) => (i.oninput = total));
    $("[data-x]", r).onclick = () => { r.remove(); total(); };
  };
  $("[data-addsrv]", f).onclick = fila;
  for (let i = 0; i < inicial; i++) fila();
}
function leerServicios(f) {
  return [...f.querySelectorAll(".srv-fila")].map((r) => {
    const v = (q) => $(q, r).value;
    return clean({ servicio_id: v("[data-s]") ? Number(v("[data-s]")) : null, concepto: v("[data-s]") ? null : v("[data-c]"),
      cantidad: Number(v("[data-n]") || 1), precio: v("input[data-p]") === "" ? null : Number(v("input[data-p]")), tipo_iva: Number(v("select[data-i]")) });
  }).filter((x) => x.servicio_id || x.concepto);
}
function cobroForm(titulo, pendiente, url, reload, assetId) {
  const f = form(titulo, [
    { k: "importe", t: pendiente > 0 ? "Importe cobrado € (IVA incluido)" : "Importe cobrado € (nada pendiente)", type: "number", req: true },
    { k: "fecha_pago", t: "Fecha del cobro", type: "date", def: today() },
    { k: "forma_pago", t: "Forma de pago", type: "select", options: kv(S.cat.formas_pago) },
    ...(assetId ? [{ html: serviciosHtml("Servicios en la misma factura (limpieza, aparcamiento…)") }] : []),
    { k: "otra", t: "Facturar a una empresa u otra persona (no al cliente)", type: "checkbox", wide: true },
    { k: "fa_nombre", t: "Razón social / nombre" }, { k: "fa_nif", t: "CIF / NIF" }, { k: "fa_domicilio", t: "Domicilio fiscal completo", wide: true },
    { html: '<p class="muted">Al registrar el cobro se emite la factura con el siguiente número de la serie del activo y se descarga en PDF. Una factura emitida no se puede modificar: si hay un error, Administración emite una rectificativa.</p>' },
  ], { importe: Math.max(0, pendiente) }, async (d, fr) => {
    const body = { importe: d.importe || 0, fecha_pago: d.fecha_pago, forma_pago: d.forma_pago, servicios: leerServicios(fr) };
    if (d.otra) body.facturar_a = { nombre: d.fa_nombre, nif: d.fa_nif, domicilio: d.fa_domicilio };
    const r = await post(url, clean(body));
    toast(`Cobro registrado · Factura ${r.factura.codigo}`);
    reload && reload();
    await descargarFactura(r.factura.id);
  }, "Registrar cobro y facturar");
  const sync = () => f.querySelectorAll('[name^="fa_"]').forEach((i) => {
    i.closest("label").style.display = f.elements.otra.checked ? "" : "none"; i.required = f.elements.otra.checked;
  });
  f.elements.otra.onchange = sync; sync();
  if (assetId) bindServicios(f, assetId, pendiente > 0 ? 0 : 1).catch((e) => toast(e.message, true));
}
function resActions(reload) {
  return (r) => can("reservas.editar") ? [
    r.uso !== "garaje" && ["Ocupantes", () => ocupantesReserva(r, reload)],
    r.uso !== "garaje" && ["Contrato", () => accommodationContract(r)],
    [r.importe_total - r.importe_pagado > 0.004 ? "Cobro" : "Servicios", () => cobroForm(`Cobro reserva ${r.localizador || r.id} · ${r.unidad} · pendiente ${eur(r.importe_total - r.importe_pagado)}`,
      Math.round((r.importe_total - r.importe_pagado) * 100) / 100, `/api/turistico/reservas/${r.id}/cobro`, reload, r.asset_id)],
    r.estado === "confirmada" && ["Check-in", () => run(() => post(`/api/turistico/reservas/${r.id}/checkin`), "Check-in realizado").then(reload).catch(() => ocupantesReserva(r, reload))],
    ["confirmada", "checkin"].includes(r.estado) && r.uso !== "garaje" && ["Renovar", () => renovarEstancia(r, reload)],
    r.estado === "checkin" && ["Check-out", () => run(() => post(`/api/turistico/reservas/${r.id}/checkout`), "Check-out realizado").then(reload)],
    ["Huésped", () => editGuest(r.guest_id)],
    ["Editar", () => editReservation(r, reload)],
    r.estado === "confirmada" && ["Cancelar", () => confirm("¿Cancelar la reserva?") && run(() => post(`/api/turistico/reservas/${r.id}/cancelar`), "Reserva cancelada").then(reload), "danger"],
  ] : [];
}
async function accommodationContract(r) {
  const info = await run(() => get(`/api/turistico/reservas/${r.id}/contrato`));
  const sel = (obj) => Object.entries(obj).map(([k, v]) => [k, v.replace(/:$/, "")]);
  const firmados = info.historial.filter((h) => h.firmado), impresos = info.historial.filter((h) => !h.firmado);
  const historial = (firmados.length ? `<p>Firmados en tablet: ${firmados.map((h) => `<b>${fdt(h.firmado)}</b> <a href="#" data-pdf="${h.id}">Ver PDF</a> · <a href="#" data-reenviar="${h.id}">Reenviar</a>${h.envios.length ? ` <span class="muted">(enviado por ${[...new Set(h.envios.map((e) => e.canal === "email" ? "correo" : "WhatsApp"))].join(" y ")})</span>` : ""}`).join(" · ")}</p>` : "") +
    (impresos.length ? `<p class="muted">Impresos: ${impresos.map((h) =>
    `<a href="#" data-c="${h.id}">${fdt(h.creado)}${h.usuario ? " · " + esc(h.usuario) : ""}</a>`).join(" · ")}</p>` : "");
  let modo = "imprimir";
  const f = form(`Contrato de alojamiento · ${r.unidad} · ${r.huesped}`, [
    { html: `<p class="muted">Complete todo aquí: al imprimir, el cliente solo tendrá que firmar. Si falta algo, el sistema le avisará antes de imprimir. De la tarjeta solo se anotan los 4 últimos dígitos.</p>${historial}` },
    { html: scanHtml() },
    { k: "localizador", t: "Localizador" }, { k: "fecha_firma", t: "Fecha de firma", type: "date", req: true },
    { html: "<h4>Cliente</h4>" },
    { k: "cliente_nombre", t: "Nombre y apellidos", wide: true }, { k: "cliente_nacionalidad", t: "Nacionalidad" },
    { k: "cliente_documento", t: "DNI / Pasaporte / NIE" },
    { k: "cliente_email", t: "Correo electrónico", type: "email" }, { k: "cliente_movil", t: "Móvil" },
    { html: "<h4>Domicilio habitual del cliente</h4>" },
    { k: "cliente_domicilio", t: "Dirección (calle, número, piso, puerta)", wide: true },
    { k: "cliente_cp", t: "Código postal" }, { k: "cliente_municipio", t: "Municipio" }, { k: "cliente_pais", t: "País" },
    { html: "<h4>Estancia</h4>" },
    { k: "capacidad", t: "Capacidad máxima (plazas)", type: "number", step: 1 }, { k: "dormitorios", t: "Dormitorios", type: "number", step: 1 },
    { k: "precio_total", t: "Precio total € (IVA incl.)", type: "number" }, { k: "fianza", t: "Fianza €", type: "number" },
    { k: "sin_garaje", t: "Sin plaza de garaje (se imprime «No incluido»)", type: "checkbox" },
    { k: "garaje_sotano", t: "Garaje: sótano" }, { k: "garaje_plaza", t: "Garaje: plaza nº" },
    { k: "tarjeta_titular", t: "Tarjeta: titular" }, { k: "tarjeta_terminacion", t: "Tarjeta: últimos 4 dígitos" },
    { k: "tarjeta_caducidad", t: "Tarjeta: caducidad (MM/AA)" },
    { html: `<fieldset><legend>Ocupantes autorizados (los registrados en la reserva; son los mismos del parte a SES.HOSPEDAJE)</legend>
      <pre class="ocupantes-txt">${esc(info.datos.ocupantes || "")}</pre><button type="button" class="btn sm" id="gOcup">Gestionar ocupantes</button></fieldset>` },
    { k: "motivo", t: "Motivo de la estancia (marque las que correspondan)", type: "checks", options: sel(info.motivos) },
    { k: "motivo_otro", t: "Motivo «otro»: detalle", wide: true },
    { k: "acreditacion", t: "Acreditación del domicilio habitual (se une copia)", type: "checks", options: sel(info.acreditaciones) },
    { k: "acreditacion_otro", t: "Acreditación «otro»: detalle", wide: true },
    { html: "<h4>Empresa</h4>" },
    { k: "representante", t: "Representante" }, { k: "representante_dni", t: "DNI representante" }, { k: "email_empresa", t: "Correo notificaciones", type: "email" },
    { html: "<h4>Opciones</h4>" },
    { k: "actualizar_huesped", t: "Guardar los datos del cliente en su ficha de huésped", type: "checkbox", def: true, wide: true },
    { k: "solo_guardar", t: "Solo guardar (imprimir más tarde, a la llegada del cliente)", type: "checkbox", wide: true },
    { k: "permitir_huecos", t: "Imprimir aunque falten datos (quedarán puntos para rellenar a mano)", type: "checkbox", wide: true },
  ], info.datos, async (d) => {
    if (modo === "firma") {
      modo = "imprimir";
      const prep = await post(`/api/turistico/reservas/${r.id}/contrato/firma`, { ...d, solo_guardar: false, permitir_huecos: false });
      $("#modal").close();
      firmaTablet(r, prep);
      return;
    }
    if (d.solo_guardar) {
      const res = await post(`/api/turistico/reservas/${r.id}/contrato`, d);
      toast(res.faltan.length ? `Datos guardados. Aún faltan: ${res.faltan.join(", ")}` : "Datos guardados. El contrato está listo para imprimir.");
      return;
    }
    await download("POST", `/api/turistico/reservas/${r.id}/contrato`, d);
    toast("Contrato generado. Ábralo e imprima dos copias para firmar.");
  }, "Imprimir en papel");
  if (info.firma_disponible) {
    $(".actions", f).insertAdjacentHTML("beforeend", '<button type="button" class="btn primary" id="fFirma">✍ Firmar en tablet</button>');
    $("#fFirma", f).onclick = () => { modo = "firma"; f.requestSubmit(); };
    $("button[type=submit]", f).classList.remove("primary");
  }
  $("#gOcup", f).onclick = () => ocupantesReserva(r, null, () => accommodationContract(r));
  f.querySelectorAll("[data-pdf]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); abrirFichero(`/api/turistico/reservas/${r.id}/contrato/${a.dataset.pdf}/pdf`); }));
  f.querySelectorAll("[data-reenviar]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); reenviarContrato(r, a.dataset.reenviar, info.datos); }));
  f.querySelectorAll("[data-c]").forEach((a) => (a.onclick = (e) => {
    e.preventDefault(); run(() => download("GET", `/api/turistico/reservas/${r.id}/contrato/${a.dataset.c}`), "Contrato descargado");
  }));
  bindScan(f, r.guest_id, (lec) => {
    const el = f.elements;
    const nombre = conTildes(el.cliente_nombre.value, [lec.nombre, lec.apellidos].filter(Boolean).join(" "));
    const dom = lec.domicilio || {};
    rellena(f, { cliente_nombre: nombre, cliente_documento: lec.documento_num, cliente_nacionalidad: lec.nacionalidad,
      cliente_domicilio: dom.direccion, cliente_municipio: dom.municipio, cliente_pais: dom.pais });
  });
}

const guestFields = [
  { k: "nombre", t: "Nombre", req: true }, { k: "apellidos", t: "Apellidos" },
  { k: "documento_tipo", t: "Tipo doc.", type: "select", options: list(["DNI", "NIE", "PAS", "CIF", "OTRO"]) },
  { k: "documento_num", t: "Nº documento" }, { k: "nacionalidad", t: "Nacionalidad" },
  { k: "fecha_nacimiento", t: "Fecha nacimiento", type: "date" },
  { k: "sexo", t: "Sexo", type: "select", options: [["F", "Mujer"], ["M", "Hombre"]] },
  { k: "num_soporte", t: "Nº de soporte (DNI/NIE)" }, { k: "fecha_caducidad_doc", t: "Caducidad del documento", type: "date" },
  { k: "email", t: "Email", type: "email" },
  { k: "telefono", t: "Teléfono" },
  { html: "<h4>Domicilio habitual</h4>" },
  { k: "direccion", t: "Dirección (calle, número, piso, puerta)", wide: true },
  { k: "cp", t: "Código postal" }, { k: "municipio", t: "Municipio" }, { k: "pais", t: "País" },
];
function unidadesHtml(c) {
  const u = c.unidades || [];
  if (!u.length) return `<p class="muted">Sin apartamentos ni plazas en este momento${c.n_estancias ? ` · ${c.n_estancias} estancia(s) en total` : ""}.</p>`;
  return `<fieldset><legend>Tiene ${c.n_apartamentos} apartamento(s)${u.length > c.n_apartamentos ? ` y ${u.length - c.n_apartamentos} plaza(s) de garaje` : ""}${c.n_estancias ? ` · ${c.n_estancias} estancia(s) en total` : ""}</legend>
    <ul class="envios">${u.map((x) => `<li><b>${esc(x.codigo)}</b> · ${esc(x.activo)} · ${x.tipo === "reserva" ? `reserva ${esc(x.localizador || "")} (${x.estado === "checkin" ? "alojado" : "confirmada"})` : `contrato ${esc(x.localizador || "")}`} · ${fdate(x.desde)} → ${x.hasta ? fdate(x.hasta) : "indefinido"}</li>`).join("")}</ul></fieldset>`;
}
async function editGuest(id, tipo = "huesped", onSaved) {
  const c = await get(`/api/terceros/${id}`).catch(() => null);
  if (!c) return toast("Cliente no encontrado", true);
  const f = form(`${{ huesped: "Huésped", cliente_garaje: "Cliente de garaje" }[tipo] || "Inquilino"}: ${c.nombre} ${c.apellidos || ""}${c.activo ? ` · ${c.activo}` : ""}`.trim(), [{ html: unidadesHtml(c) }, { html: scanHtml() }, ...guestFields, { k: "iban", t: "IBAN" }, { k: "notas", t: "Notas", type: "textarea", wide: true }], c,
    async (d) => { await put(`/api/terceros/${id}`, { ...d, company_id: c.company_id, tipo: c.tipo }); toast("Datos guardados"); onSaved && onSaved(); });
  bindScan(f, id, (lec) => rellenaFicha(f, lec));
}

// ---- escaneo de documentos de identidad
// Al seleccionar el fichero (o capturar con la cámara) el documento se lee solo. Con cliente existente la copia
// se guarda en su ficha; en un alta (cid = null) queda pendiente y se adjunta al crear la reserva o el cliente.
const scanHtml = (titulo = "Escanear documento de identidad (DNI, NIE/TIE, pasaporte)") => `<fieldset class="scan"><legend>${esc(titulo)}</legend>
  <p class="muted">Seleccione el documento escaneado (una o las dos caras, imagen o PDF) o use la cámara: se lee automáticamente y se guarda una copia cifrada en la ficha del cliente.</p>
  <div class="scan-row">
    <label>Documento escaneado<input type="file" data-scanfile accept="image/*,application/pdf" multiple></label>
    <button type="button" class="btn" data-cam>📷 Usar cámara</button>
  </div>
  <div data-camzone class="camzone hidden">
    <video data-video autoplay playsinline muted></video>
    <div class="toolbar"><button type="button" class="btn primary" data-capturar>Capturar</button>
      <button type="button" class="btn" data-camoff>Cerrar cámara</button>
      <label class="check"><input type="checkbox" data-camauto> Abrir la cámara automáticamente</label></div>
  </div>
  <div data-scanmsg></div><div data-docs class="muted"></div></fieldset>`;
function pararCamara() {
  if (S.cam) { S.cam.getTracks().forEach((t) => t.stop()); S.cam = null; }
}
async function hayCamara() {
  try { return (await navigator.mediaDevices.enumerateDevices()).some((d) => d.kind === "videoinput"); } catch { return false; }
}
function bindScan(f, cid, aplicar) {
  const $s = (sel) => f.querySelector(sel);
  const msg = $s("[data-scanmsg]"), lista = $s("[data-docs]"), zona = $s("[data-camzone]"), video = $s("[data-video]");
  f._docs = [];  // alta: copias pendientes de adjuntar ({id, tipo, cara, subido})
  const pinta = (docs) => {
    lista.innerHTML = docs.length ? "Copias guardadas: " + docs.map((d) => `${esc(d.tipo || "Documento")} · ${esc(d.cara)} (${fdt(d.subido)})
      <a href="#" data-ver="${d.id}">Ver</a> <a href="#" data-borrar="${d.id}" class="danger">Borrar</a>`).join(" &nbsp;|&nbsp; ") : "";
    lista.querySelectorAll("[data-ver]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); verDocumento(a.dataset.ver); }));
    lista.querySelectorAll("[data-borrar]").forEach((a) => (a.onclick = async (e) => {
      e.preventDefault();
      if (!confirm("¿Borrar esta copia del documento?")) return;
      await run(() => api("DELETE", `/api/documentos/${a.dataset.borrar}`), "Copia borrada");
      f._docs = f._docs.filter((d) => String(d.id) !== a.dataset.borrar);
      cargar();
    }));
  };
  const cargar = async () => pinta(cid ? await get(`/api/terceros/${cid}/documentos`).catch(() => []) : f._docs);
  // envía las caras (File[]) y aplica lo leído; devuelve true si se han leído los datos
  const subir = async (ficheros) => {
    const fd = new FormData();
    ficheros.slice(0, 2).forEach((fi, n) => fd.append(n ? "reverso" : "anverso", fi));
    msg.innerHTML = '<p class="muted">Leyendo el documento… (unos segundos)</p>';
    try {
      const res = await fetch(cid ? `/api/terceros/${cid}/documentos` : "/api/documentos/leer",
        { method: "POST", headers: { Authorization: `Bearer ${S.token}` }, body: fd });
      const j = await res.json().catch(() => null);
      if (!res.ok) throw new Error(errMsg(j, res));
      const lec = j.lectura;
      if (!cid) f._docs.push(...j.documentos);
      if (lec.leido) aplicar(lec, j.tercero);
      const ok = lec.leido ? (lec.mrz_valido ? "✔ Documento leído y validado" : "⚠ Documento leído con dudas")
        : "✖ En esta cara no están las líneas «<<<». Escanee o capture la otra cara";
      msg.innerHTML = `<p><b>${esc(ok)}.</b> Copia guardada${cid ? " en la ficha" : " (se adjuntará al cliente)"}. ${lec.leido ? "Revise los campos resaltados." : ""}</p>` +
        (lec.leido ? (lec.avisos || []) : []).map((a) => `<p class="${a.includes("CADUCADO") ? "error" : "muted"}">• ${esc(a)}</p>`).join("");
      cargar();
      return lec.leido;
    } catch (e) { msg.innerHTML = `<p class="error">${esc(e.message)}</p>`; return false; }
  };
  $s("[data-scanfile]").onchange = async (e) => {  // lectura automática al elegir el fichero
    const fs = [...e.target.files];
    if (fs.length) await subir(fs);
    e.target.value = "";
  };
  // cámara (webcam de recepción, tablet o móvil)
  const encender = async () => {
    if (!navigator.mediaDevices?.getUserMedia) { msg.innerHTML = '<p class="error">Este navegador no permite usar la cámara.</p>'; return; }
    try {
      pararCamara();
      S.cam = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } } });
      video.srcObject = S.cam; zona.classList.remove("hidden");
      msg.innerHTML = '<p class="muted">Encuadre el documento (mejor la cara con las líneas «<<<») y pulse Capturar.</p>';
    } catch { msg.innerHTML = '<p class="error">No se ha podido abrir la cámara (permiso denegado o sin cámara).</p>'; }
  };
  const apagar = () => { pararCamara(); zona.classList.add("hidden"); };
  $s("[data-cam]").onclick = encender;
  $s("[data-camoff]").onclick = apagar;
  $s("[data-capturar]").onclick = async () => {
    if (!S.cam) return;
    const c = document.createElement("canvas");
    c.width = video.videoWidth; c.height = video.videoHeight;
    c.getContext("2d").drawImage(video, 0, 0);
    const blob = await new Promise((ok) => c.toBlob(ok, "image/jpeg", 0.92));
    if (await subir([new File([blob], "captura.jpg", { type: "image/jpeg" })])) apagar();
  };
  const auto = $s("[data-camauto]");
  let pref = null;
  try { pref = localStorage.getItem("pms_cam_auto"); } catch {}
  auto.onchange = () => { try { localStorage.setItem("pms_cam_auto", auto.checked ? "1" : "0"); } catch {} };
  (async () => {
    const docs = cid ? await get(`/api/terceros/${cid}/documentos`).catch(() => []) : [];
    pinta(docs.length ? docs : f._docs);
    const tiene = await hayCamara();
    auto.checked = pref ? pref === "1" : tiene;  // por defecto, si el equipo tiene cámara se abre sola
    if (tiene && auto.checked && !docs.length && !f._sinCamara) encender();  // si ya hay copia del documento, no hace falta
  })();
}
// formulario de alta con escáner: lo leído rellena la ficha y las copias se adjuntan al crear
const conEscaner = (f) => { bindScan(f, null, (lec) => rellenaFicha(f, lec)); return f; };
// rellena una ficha de cliente (campos de guestFields) con lo leído del documento
function rellenaFicha(f, lec) {
  const dom = lec.domicilio || {};
  rellena(f, { nombre: conTildes(f.elements.nombre.value, lec.nombre), apellidos: conTildes(f.elements.apellidos.value, lec.apellidos),
    documento_tipo: lec.documento_tipo, documento_num: lec.documento_num, nacionalidad: lec.nacionalidad,
    fecha_nacimiento: lec.fecha_nacimiento, sexo: lec.sexo, num_soporte: lec.num_soporte,
    fecha_caducidad_doc: lec.fecha_caducidad, direccion: dom.direccion, municipio: dom.municipio, pais: dom.pais });
}
const sinTildes = (x) => String(x || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase().trim();
// La MRZ no lleva tildes: si lo ya escrito coincide salvo tildes, se conserva lo escrito
const conTildes = (actual, leido) => (leido && sinTildes(actual) !== sinTildes(leido) ? leido : actual);
function rellena(f, valores) {
  Object.entries(valores).forEach(([k, v]) => {
    const el = f.elements[k];
    if (!el || v == null || v === "" || String(el.value) === String(v)) return;
    el.value = v; el.classList.add("auto");
  });
}
async function verDocumento(did) {
  const w = window.open("", "_blank");  // se abre ya para que el navegador no lo bloquee
  try {
    const res = await fetch(`/api/documentos/${did}`, { headers: { Authorization: `Bearer ${S.token}` } });
    if (!res.ok) throw new Error(errMsg(await res.json().catch(() => null), res));
    w.location = URL.createObjectURL(await res.blob());
  } catch (e) { w && w.close(); toast(e.message, true); }
}
function editReservation(r, reload) {
  form(`Reserva ${r.localizador || r.id} · ${r.unidad}`, [
    { k: "localizador", t: "Localizador" }, { k: "canal", t: "Canal", type: "select", options: list(S.cat.canales) },
    { k: "fecha_entrada", t: "Entrada", type: "date", req: true }, { k: "fecha_salida", t: "Salida", type: "date", req: true },
    { k: "adultos", t: "Adultos", type: "number" }, { k: "ninos", t: "Niños", type: "number" },
    { k: "importe_total", t: "Importe total € (IVA incluido)", type: "number" },
    { html: `<p class="muted">Cobrado: ${eur(r.importe_pagado)}. Los cobros se registran con el botón <b>Cobro</b>, que emite la factura.</p>` },
    { k: "notas", t: "Notas", type: "textarea", wide: true },
  ], r, async (d) => { await put(`/api/turistico/reservas/${r.id}`, d); toast("Reserva actualizada"); reload(); });
}
async function newReservation(reload, fija) {  // fija: {id, codigo, asset_id} para reservar un apartamento concreto
  const aid = fija ? fija.asset_id : await pickAsset("apartamentos_turisticos");
  form(fija ? `Nueva reserva · apartamento ${fija.codigo}` : `Nueva reserva · ${assetName(aid)}`, [
    { k: "fecha_entrada", t: "Entrada", type: "date", req: true, def: today() }, { k: "fecha_salida", t: "Salida", type: "date", req: true, def: addDays(today(), 1) },
    { k: "adultos", t: "Adultos", type: "number", def: 2, req: true }, { k: "ninos", t: "Niños", type: "number", def: 0 },
  ], {}, async (q) => {
    const disp = await get("/api/turistico/disponibilidad", { asset_id: aid, desde: q.fecha_entrada, hasta: q.fecha_salida, capacidad: q.adultos + (q.ninos || 0), uso: fija?.uso === "garaje" ? "garaje" : null });
    if (fija) {
      disp.unidades = disp.unidades.filter((u) => u.id === fija.id);
      if (!disp.unidades.length) throw new Error(`El apartamento ${fija.codigo} no está libre esas fechas o no tiene plazas suficientes`);
      disp.libres = 1;
    }
    if (!disp.libres) throw new Error("No hay unidades disponibles para esas fechas y ocupación");
    setTimeout(() => bindBuscaCliente(conEscaner(form(`Reserva ${fdate(q.fecha_entrada)} → ${fdate(q.fecha_salida)} · ${disp.libres} libres`, [
      { html: buscaClienteHtml() },
      { html: scanHtml("1. Escanee el documento del huésped titular (DNI, NIE/TIE, pasaporte)") },
      { html: "<h4>Huésped titular</h4>" }, ...guestFields,
      { html: "<h4>Reserva</h4>" },
      { k: "unit_id", t: "Unidad", type: "select", req: true, options: disp.unidades.map((u) => [u.id, `${u.codigo} ${u.bloque ? "· " + u.bloque : ""} ${u.tipologia ?? ""} ${u.tarifa_base_noche ? "· " + eur(u.tarifa_base_noche) : ""}`]) },
      { k: "canal", t: "Canal", type: "select", req: true, options: list(S.cat.canales), def: "directo" }, { k: "localizador", t: "Localizador" },
      { k: "importe_total", t: "Importe total € (IVA incluido)", type: "number", def: 0 },
      { k: "importe_pagado", t: "Cobrado ahora € (se emite factura)", type: "number", def: 0 },
      { k: "forma_pago", t: "Forma de pago", type: "select", options: kv(S.cat.formas_pago) },
      { k: "notas", t: "Notas", type: "textarea", wide: true },
    ], {}, async (d, fr) => {
      const g = {}; guestFields.filter((f) => f.k).forEach((f) => { g[f.k] = d[f.k]; delete d[f.k]; });
      let cliente = { guest: clean(g) };
      if (fr._cliente) {  // cliente habitual: se actualiza su ficha y se reutiliza
        await put(`/api/terceros/${fr._cliente.id}`, { ...clean(g), company_id: fr._cliente.company_id, tipo: "huesped" });
        cliente = { guest_id: fr._cliente.id };
      }
      const nueva = await post("/api/turistico/reservas", { ...clean(d), ...q, unit_id: Number(d.unit_id), ...cliente, documentos: fr._docs.map((x) => x.id) });
      toast("Reserva creada" + (nueva.factura ? ` · Factura ${nueva.factura.codigo}` : "") + ". Complete ahora el contrato (puede guardarlo e imprimirlo a la llegada).");
      reload && reload();
      if (nueva.factura) await descargarFactura(nueva.factura.id);
      if (nueva.adultos + nueva.ninos > 1) await ocupantesReserva(nueva, reload, () => accommodationContract(nueva));
      else await accommodationContract(nueva);
    }, "Crear reserva")), aid), 0);
  }, "Buscar disponibilidad");
}

// ---- ocupantes de la reserva: todos quedan registrados (contrato y parte de viajeros a SES.HOSPEDAJE)
const PARENTESCO_OPC = () => kv(S.cat.parentescos || {});
async function ocupantesReserva(r, reload, continuar) {
  const o = await run(() => get(`/api/turistico/reservas/${r.id}/ocupantes`));
  const n = o.ocupantes.length, req = o.requeridos;
  const estado = (x) => x.faltan.length ? `<span class="badge b-pendiente">falta: ${esc(x.faltan.join(", "))}</span>` : '<span class="badge b-vigente">completo</span>';
  const f = form(`Ocupantes · ${r.unidad} · ${r.localizador || "R-" + r.id}`, [
    { html: `<div class="ocup-cab"><div class="ocup-cuenta ${o.pendiente.length ? "pend" : "ok"}"><b>${n}</b> de <b>${req}</b> registrados</div>
      <p class="muted">Registre a <b>todas</b> las personas alojadas: los mayores de edad escaneando su documento; los menores sin documento, a mano con su parentesco. Todos figuran en el contrato y en el parte de viajeros.</p></div>
      <div class="ocupantes">${o.ocupantes.map((x) => `<div class="ocupante">${avatar(x.nombre, "sm")}
        <div class="ocup-datos"><b>${esc(x.nombre)}</b>${x.titular ? ' <span class="badge b-confirmada">titular</span>' : ""}${x.menor ? ` <span class="badge b-parcial">menor${x.edad != null ? ", " + x.edad + " años" : ""}</span>` : ""}
          <div class="muted">${x.contact.documento_num ? esc(`${x.contact.documento_tipo || "Doc."} ${x.contact.documento_num}`) : "Sin documento"}${x.parentesco ? " · " + esc(S.cat.parentescos[x.parentesco]) : ""} · ${esc(x.contact.nacionalidad || "")}</div>
          ${estado(x)}</div>
        <div class="ocup-acc"><button type="button" class="btn sm" data-ficha="${x.contact.id}">Completar ficha</button>${x.menor && !x.titular ? `<button type="button" class="btn sm" data-par="${x.id}">Parentesco</button>` : ""}${x.titular ? "" : `<button type="button" class="btn sm danger" data-quitar="${x.id}">Quitar</button>`}</div></div>`).join("")}</div>
      ${n < req ? `<div class="toolbar"><button type="button" class="btn primary" id="oAdulto">＋ Adulto (escanear documento)</button><button type="button" class="btn" id="oMenor">＋ Menor sin documento</button></div>` :
        `<div class="toolbar"><button type="button" class="btn sm" id="oAdulto">＋ Añadir otro adulto</button><button type="button" class="btn sm" id="oMenor">＋ Añadir otro menor</button></div>`}` },
  ], {}, async () => { reload && reload(); if (continuar) setTimeout(continuar, 0); }, continuar ? "Continuar al contrato" : "Cerrar");
  const volver = () => ocupantesReserva(r, reload, continuar);
  const titular = o.ocupantes.find((x) => x.titular)?.contact || {};
  $("#oAdulto", f).onclick = () => nuevoOcupante(r, titular, false, volver);
  $("#oMenor", f).onclick = () => nuevoOcupante(r, titular, true, volver);
  f.querySelectorAll("[data-ficha]").forEach((b) => (b.onclick = () => editGuest(Number(b.dataset.ficha), "huesped", volver)));
  f.querySelectorAll("[data-quitar]").forEach((b) => (b.onclick = async () => {
    if (!confirm("¿Quitar este ocupante de la reserva? (su ficha de huésped se conserva)")) return;
    await run(() => api("DELETE", `/api/turistico/reservas/${r.id}/ocupantes/${b.dataset.quitar}`), "Ocupante quitado"); volver();
  }));
  f.querySelectorAll("[data-par]").forEach((b) => (b.onclick = () => form("Parentesco del menor", [
    { k: "parentesco", t: "Parentesco con un adulto de la reserva", type: "select", req: true, options: PARENTESCO_OPC() }],
    { parentesco: o.ocupantes.find((x) => String(x.id) === b.dataset.par)?.parentesco }, async (d) => {
      await put(`/api/turistico/reservas/${r.id}/ocupantes/${b.dataset.par}`, d); toast("Parentesco guardado"); setTimeout(volver, 0);
    })));
}
function nuevoOcupante(r, titular, menor, volver) {
  // el domicilio del titular se propone para el resto (familias); lo leído del documento lo sustituye
  const dom = Object.fromEntries(["direccion", "cp", "municipio", "pais"].map((k) => [k, titular[k]]));
  const campos = menor ? [
    { html: '<p class="muted">Menor sin documento: registro manual. Si tiene DNI o pasaporte, escanéelo igualmente.</p>' },
    { html: scanHtml("Documento del menor (opcional)") },
    { k: "parentesco", t: "Parentesco con un adulto de la reserva", type: "select", req: true, options: PARENTESCO_OPC() },
    ...guestFields.map((x) => (x.k === "fecha_nacimiento" || x.k === "sexo" || x.k === "nacionalidad" ? { ...x, req: true } : x)),
  ] : [{ html: scanHtml("Escanee el documento del ocupante (DNI, NIE/TIE, pasaporte)") }, ...guestFields];
  const f = form(menor ? "Nuevo ocupante menor de edad" : "Nuevo ocupante adulto", campos, { ...dom, nacionalidad: menor ? titular.nacionalidad : "" }, async (d, fr) => {
    const parentesco = d.parentesco; delete d.parentesco;
    await post(`/api/turistico/reservas/${r.id}/ocupantes`, { contact: clean(d), parentesco, documentos: fr._docs.map((x) => x.id) });
    toast("Ocupante registrado"); setTimeout(volver, 0);
  }, "Registrar ocupante");
  f._sinCamara = menor;  // en los menores (normalmente sin documento) no se abre la cámara sola
  bindScan(f, null, (lec) => rellenaFicha(f, lec));
}

// ---- firma del contrato en la tablet: el cliente lee, acepta y firma con el dedo; se envía por correo o WhatsApp
function firmaTablet(r, prep) {
  pararCamara();
  const a = S.assets.find((x) => x.id === r.asset_id);
  const ov = document.createElement("div");
  ov.className = "firma-pantalla";
  ov.innerHTML = `<header class="firma-cab">${a?.logo ? `<img src="${esc(a.logo)}" alt="">` : ""}<div><div class="wordmark">CONTRATO DE <b>ALOJAMIENTO</b></div>
      <small>${esc(r.unidad)} · ${fdate(r.fecha_entrada)} – ${fdate(r.fecha_salida)} · ${esc(prep.cliente || "")}</small></div>
      <button type="button" class="btn ghost firma-x" data-cancel>✕ Cancelar</button></header>
    <div class="firma-doc">${prep.paginas.map((p, i) => `<img src="${p}" alt="Página ${i + 1}">`).join("")}<div class="firma-fin" data-fin></div></div>
    <section class="firma-panel">
      <p class="firma-aviso" data-leer>Desplácese hasta el final del contrato para poder firmar.</p>
      <label class="check"><input type="checkbox" data-acepta> He leído el contrato completo y acepto expresamente sus condiciones, en especial las destacadas en <b>negrita</b>.</label>
      <label class="check"><input type="checkbox" data-priv> He sido informado/a del tratamiento de mis datos personales (condición 13) y del envío del parte de viajeros a las autoridades (RD 933/2021).</label>
      <div class="firma-lienzo"><canvas data-canvas></canvas><span class="firma-guia">Firme aquí</span><button type="button" class="btn sm" data-borrar>Borrar</button></div>
      <div class="firma-envio"><label>Correo electrónico<input type="email" data-email value="${esc(prep.email || "")}"></label>
        <label>Móvil (WhatsApp)<input data-movil value="${esc(prep.movil || "")}"></label></div>
      <p class="error" data-err></p>
      <div class="firma-acc"><button type="button" class="btn primary grande" data-firmar disabled>Firmar contrato</button></div>
    </section>`;
  document.body.appendChild(ov);
  document.body.classList.add("sin-scroll");
  const q = (s) => ov.querySelector(s);
  const cerrar = () => { ov.remove(); document.body.classList.remove("sin-scroll"); };
  q("[data-cancel]").onclick = () => confirm("¿Cancelar la firma? El contrato quedará sin firmar.") && cerrar();
  // lienzo de firma (dedo, lápiz o ratón)
  const cv = q("[data-canvas]"), ctx = cv.getContext("2d");
  let trazos = 0, dibujando = false;
  const ajustar = () => {
    const rect = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    cv.width = rect.width * dpr; cv.height = rect.height * dpr;
    ctx.scale(dpr, dpr); ctx.lineWidth = 2.6; ctx.lineCap = ctx.lineJoin = "round"; ctx.strokeStyle = "#0e0e10";
    trazos = 0; q(".firma-guia").hidden = false;
  };
  requestAnimationFrame(ajustar);
  const pos = (e) => { const b = cv.getBoundingClientRect(); return [e.clientX - b.left, e.clientY - b.top]; };
  cv.onpointerdown = (e) => { dibujando = true; cv.setPointerCapture(e.pointerId); ctx.beginPath(); ctx.moveTo(...pos(e)); q(".firma-guia").hidden = true; };
  cv.onpointermove = (e) => { if (!dibujando) return; ctx.lineTo(...pos(e)); ctx.stroke(); trazos++; };
  cv.onpointerup = cv.onpointercancel = () => { dibujando = false; listo(); };
  q("[data-borrar]").onclick = () => { ctx.clearRect(0, 0, cv.width, cv.height); ajustar(); listo(); };
  // hay que llegar al final del documento y aceptar las dos casillas
  let leido = false;
  new IntersectionObserver((ents) => { if (ents.some((x) => x.isIntersecting)) { leido = true; q("[data-leer]").hidden = true; listo(); } },
    { root: q(".firma-doc") }).observe(q("[data-fin]"));
  const listo = () => (q("[data-firmar]").disabled = !(leido && trazos > 10 && q("[data-acepta]").checked && q("[data-priv]").checked));
  q("[data-acepta]").onchange = q("[data-priv]").onchange = listo;
  q("[data-firmar]").onclick = async () => {
    const b = q("[data-firmar]"); b.disabled = true; b.textContent = "Firmando…"; q("[data-err]").textContent = "";
    try {
      const res = await post(`/api/turistico/reservas/${r.id}/contrato/${prep.contrato_id}/firmar`, {
        firma: cv.toDataURL("image/png"), acepta: true, acepta_privacidad: true,
        email: q("[data-email]").value.trim() || null, movil: q("[data-movil]").value.trim() || null });
      const env = Object.fromEntries(res.envios.map((e) => [e.canal, e]));
      ov.querySelector(".firma-panel").innerHTML = `<div class="firma-ok"><div class="firma-check">✓</div><h2>Contrato firmado</h2>
        <p>${env.email ? (env.email.enviado ? `Enviado por correo a <b>${esc(q("[data-email]")?.value || "")}</b>.` : `<span class="error">Correo no enviado: ${esc(env.email.error)}</span>`) : ""}</p>
        ${env.whatsapp?.whatsapp ? `<p><a class="btn primary grande" href="${esc(env.whatsapp.whatsapp)}" target="_blank" rel="noopener">Enviar por WhatsApp</a></p>` : env.whatsapp?.error ? `<p class="error">${esc(env.whatsapp.error)}</p>` : ""}
        <p class="muted">No hace falta copia en papel: el contrato firmado queda guardado cifrado. Huella SHA-256: <code>${esc(res.sha256.slice(0, 16))}…</code></p>
        <button type="button" class="btn" data-cerrar>Terminar</button></div>`;
      ov.querySelector(".firma-doc").classList.add("hecho");
      ov.querySelector("[data-cerrar]").onclick = cerrar;
      ov.querySelector("[data-cancel]").hidden = true;
    } catch (e) { q("[data-err]").textContent = e.message; b.disabled = false; b.textContent = "Firmar contrato"; }
  };
}
function reenviarContrato(r, cid, datos) {
  form("Enviar el contrato firmado al cliente", [
    { k: "canal", t: "Por", type: "select", req: true, options: [["email", "Correo electrónico (con el PDF adjunto)"], ["whatsapp", "WhatsApp (enlace de descarga, 7 días)"]], def: datos.cliente_email ? "email" : "whatsapp" },
    { k: "destino", t: "Correo o móvil", req: true, def: datos.cliente_email || datos.cliente_movil },
  ], {}, async (d) => {
    const res = await post(`/api/turistico/reservas/${r.id}/contrato/${cid}/enviar`, d);
    if (res.whatsapp) window.open(res.whatsapp, "_blank", "noopener");
    toast(res.enviado ? "Contrato enviado por correo" : "Se abre WhatsApp con el enlace del contrato");
  }, "Enviar");
}


// ---- alquiler mensual de plazas de garaje a clientes externos (no son huéspedes ni ocupantes del edificio)
const clienteGarajeFields = [
  { k: "nombre", t: "Nombre o razón social", req: true }, { k: "apellidos", t: "Apellidos" },
  { k: "documento_tipo", t: "Tipo doc.", type: "select", options: list(["DNI", "NIE", "PAS", "CIF", "OTRO"]) },
  { k: "documento_num", t: "DNI / NIE / CIF" }, { k: "telefono", t: "Teléfono", req: true }, { k: "email", t: "Correo electrónico", type: "email" },
  { k: "direccion", t: "Domicilio (para la factura)", wide: true }, { k: "cp", t: "Código postal" }, { k: "municipio", t: "Municipio" }, { k: "pais", t: "País", def: "España" },
];
async function alquilarGaraje(reload, fija, assetId) {
  const aid = fija ? fija.asset_id : assetId || await pickAsset("apartamentos_turisticos");
  const inicio = today();
  const libres = fija ? null : await get("/api/turistico/disponibilidad", { asset_id: aid, desde: inicio, hasta: addDays(inicio, 1), uso: "garaje" });
  const f = conEscaner(form(fija ? `Alquiler mensual · plaza ${fija.codigo}` : `Alquiler mensual de plaza de garaje · ${assetName(aid)}`, [
    { html: '<p class="muted">Cliente externo: no es huésped ni ocupante del edificio. Cada mes se emite su recibo (renta + 21 % de IVA) con vencimiento el día de pago; si no se cobra, el PMS avisa. Al cobrar se emite la factura.</p>' },
    ...(fija ? [] : [{ k: "unit_id", t: "Plaza libre hoy", type: "select", req: true, options: libres.unidades.map((u) => [u.id, `${u.codigo} · ${u.bloque || ""}`]) }]),
    { html: scanHtml("Documento del cliente (opcional: rellena los datos)") },
    { html: "<h4>Cliente</h4>" }, ...clienteGarajeFields,
    { html: "<h4>Alquiler</h4>" },
    { k: "fecha_inicio", t: "Fecha de inicio", type: "date", req: true, def: inicio }, { k: "fecha_fin", t: "Fecha de fin (vacío: indefinido, mes a mes)", type: "date" },
    { k: "renta_mensual", t: "Renta mensual € SIN IVA", type: "number", req: true }, { k: "dia_pago", t: "Día de pago (1–28)", type: "number", step: 1, def: 5, req: true },
    { k: "fianza", t: "Fianza €", type: "number" }, { k: "referencia", t: "Referencia del contrato" },
    { k: "matricula", t: "Matrícula" }, { k: "vehiculo", t: "Vehículo (marca, modelo, color)" }, { k: "mandos", t: "Mandos / tarjetas entregados", wide: true },
    { k: "notas", t: "Notas", type: "textarea", wide: true },
    { html: '<p class="muted" data-iva></p>' },
  ], {}, async (d, fr) => {
    const cliente = {}; clienteGarajeFields.forEach((x) => { cliente[x.k] = d[x.k]; delete d[x.k]; });
    const c = await post("/api/garajes/contratos", clean({ ...d, unit_id: fija ? fija.id : Number(d.unit_id), cliente: clean(cliente), documentos: fr._docs.map((x) => x.id) }));
    toast(`Plaza ${c.unidad} alquilada a ${c.cliente}`);
    reload && reload();
    if (!c.proximo_recibo) return;
    const r = c.proximo_recibo;  // primer recibo: se cobra y factura ahora o más tarde desde «Alquiler de garajes»
    form(`Plaza ${c.unidad} alquilada a ${c.cliente}`, [{ html: `<p>Primer recibo <b>${esc(r.periodo)}</b>: <b>${eur(r.pendiente)}</b> (IVA incluido), vence el ${fdate(r.fecha_vencimiento)}.</p>
      <p class="muted">Si lo cobra ahora se emite la factura. Si no, queda pendiente en «Alquiler de garajes → Recibos» y el PMS avisa si vence sin cobrar.</p>` }],
    {}, async () => { setTimeout(() => cobroForm(`Cobro plaza ${c.unidad} · ${c.cliente} · ${r.periodo}`, r.pendiente, `/api/garajes/recibos/${r.id}/cobro`, reload), 0); }, "Cobrar y facturar ahora");
    $("#fCancel").textContent = "Más tarde";
  }, "Alquilar plaza"));
  if (!fija && !libres.unidades.length) $("#formErr", f).textContent = "No hay plazas libres hoy en este activo: libere una o elija otra fecha desde el plano.";
  const iva = () => { const v = Number(f.elements.renta_mensual.value || 0); $("[data-iva]", f).textContent = v ? `Recibo mensual: ${eur(v)} + 21 % IVA = ${eur(Math.round(v * 121) / 100)}` : ""; };
  f.elements.renta_mensual.oninput = iva;
  f._sinCamara = true;
}
V.garajes = async (el) => {
  const aid = await pickAsset("apartamentos_turisticos");
  el.innerHTML = `<div class="toolbar"><strong>${esc(assetName(aid))}</strong><span class="tabs" id="tabs"><button class="btn primary" data-v="c">Alquileres</button><button class="btn" data-v="r">Recibos</button></span>
    <label>Buscar<input id="q" placeholder="Plaza, cliente, matrícula"></label><label>Estado<select id="e"><option value="vigente">Vigentes</option><option value="">Todos</option><option value="finalizado">Finalizados</option></select></label>
    <span class="spacer"></span>${can("reservas.editar") ? '<button class="btn primary" id="new">Nuevo alquiler</button>' : ""}</div>
    <div class="kpis kpis-garaje" id="k"></div><div id="t"></div>`;
  let vista = "c";
  const load = async () => {
    const [cs, rs] = await Promise.all([get("/api/garajes/contratos", { asset_id: aid, estado: $("#e", el).value, q: $("#q", el).value }), get("/api/garajes/recibos", { asset_id: aid })]);
    const vig = cs.filter((c) => c.estado === "vigente"), venc = rs.filter((r) => r.vencido);
    $("#k", el).innerHTML = `<div class="kpi"><b>${vig.length}</b><span>Plazas alquiladas por meses</span></div>
      <div class="kpi"><b>${eur(vig.reduce((s, c) => s + c.renta_mensual, 0))}</b><span>Renta mensual sin IVA</span></div>
      <div class="kpi ${venc.length ? "mal" : ""}"><b>${venc.length}</b><span>Recibos vencidos sin cobrar</span></div>
      <div class="kpi ${venc.length ? "mal" : ""}"><b>${eur(venc.reduce((s, r) => s + r.pendiente, 0))}</b><span>Deuda vencida</span></div>`;
    const cobrar = (r, c) => cobroForm(`Cobro plaza ${r.unidad} · ${r.cliente} · ${r.periodo}`, r.pendiente, `/api/garajes/recibos/${r.id}/cobro`, load);
    if (vista === "c") table($("#t", el), [
      { k: "unidad", t: "Plaza", f: (v, c) => `<b>${esc(v)}</b><div class="muted peq">${esc(c.bloque || "")}</div>` },
      { k: "matricula", t: "Vehículo", f: (v, c) => `${esc(v || "")}<div class="muted peq">${esc(c.vehiculo || "")}</div>` },
      { k: "cliente", t: "Cliente", f: (v, c) => `<span class="persona">${avatar(v, "sm")}<span>${esc(v)}<div class="muted peq">${esc(c.telefono || c.email || "")}</div></span></span>` },
      { k: "fecha_inicio", t: "Periodo", f: (v, c) => `${fdate(v)}<div class="muted peq">${c.fecha_fin ? "hasta " + fdate(c.fecha_fin) : "indefinido"}</div>` },
      { k: "renta_con_iva", t: "Recibo/mes", num: true, f: (v, c) => `${eur(v)}<div class="muted peq">día ${c.dia_pago}</div>` },
      { k: "al_corriente", t: "Pagos", f: (v, c) => (c.estado !== "vigente" ? badge(c.estado) : (v ? '<span class="badge b-vigente">al corriente</span>' : `<span class="badge b-cancelada">${c.recibos_vencidos} vencido(s) · ${eur(c.deuda_vencida)}</span>`)
        + (c.proximo_recibo ? `<div class="muted peq">próximo: ${esc(c.proximo_recibo.periodo)} · vence ${fdate(c.proximo_recibo.fecha_vencimiento)}</div>` : "")) },
    ], cs, (c) => can("reservas.editar") ? [
      c.proximo_recibo && ["Cobrar", () => cobrar(c.proximo_recibo, c)],
      ["Cliente", () => editGuest(c.cliente_id, "cliente_garaje", load)],
      c.estado === "vigente" && ["Editar", () => editarAlquilerGaraje(c, load)],
      c.estado === "vigente" && ["Baja", () => form(`Baja del alquiler · plaza ${c.unidad} · ${c.cliente}`, [
        { html: '<p class="muted">Se anulan los recibos posteriores a la baja que no tengan cobros. Si hay deuda pendiente, sigue en «Recibos».</p>' },
        { k: "fecha_fin", t: "Fecha de baja (último día)", type: "date", req: true, def: today() }, { k: "motivo", t: "Motivo", wide: true },
      ], {}, async (x) => { await post(`/api/garajes/contratos/${c.id}/finalizar`, clean(x)); toast("Alquiler dado de baja"); load(); }, "Dar de baja"), "danger"],
    ] : []);
    else {
      const q = normaliza($("#q", el).value);
      const filas = rs.filter((r) => !q || normaliza(`${r.unidad} ${r.cliente}`).includes(q));
      table($("#t", el), [
        { k: "periodo", t: "Mes" }, { k: "unidad", t: "Plaza" }, { k: "cliente", t: "Cliente" },
        { k: "fecha_vencimiento", t: "Vence", f: fdate }, { k: "importe", t: "Importe", num: true, f: eur }, { k: "pendiente", t: "Pendiente", num: true, f: eur },
        { k: "estado", t: "Estado", f: (v, r) => (r.vencido ? '<span class="badge b-cancelada">vencido</span>' : badge(v)) },
      ], filas, (r) => can("reservas.editar") && r.pendiente > 0.004 && r.estado !== "anulado" ? [["Cobrar", () => cobrar(r)]] : []);
    }
  };
  const marcar = () => el.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("primary", b.dataset.v === vista));
  el.querySelectorAll("#tabs button").forEach((b) => (b.onclick = () => { vista = b.dataset.v; marcar(); load(); }));
  $("#e", el).onchange = load; $("#q", el).oninput = debounce(load);
  if ($("#new", el)) $("#new", el).onclick = () => alquilarGaraje(load, null, aid);  // sin volver a preguntar el activo
  load();
};
function editarAlquilerGaraje(c, reload) {
  form(`Alquiler plaza ${c.unidad} · ${c.cliente}`, [
    { k: "renta_mensual", t: "Renta mensual € SIN IVA (desde el próximo recibo)", type: "number", req: true }, { k: "dia_pago", t: "Día de pago", type: "number", step: 1 },
    { k: "fecha_fin", t: "Fecha de fin prevista", type: "date" }, { k: "fianza", t: "Fianza €", type: "number" }, { k: "referencia", t: "Referencia" },
    { k: "matricula", t: "Matrícula" }, { k: "vehiculo", t: "Vehículo" }, { k: "mandos", t: "Mandos / tarjetas", wide: true }, { k: "notas", t: "Notas", type: "textarea", wide: true },
  ], c, async (d) => { await put(`/api/garajes/contratos/${c.id}`, d); toast("Alquiler actualizado"); reload(); });
}

// ---- renovación de la estancia al mismo cliente: reserva nueva, datos completos y contrato nuevo firmado
async function renovarEstancia(r, reload) {
  const info = await run(() => get(`/api/turistico/reservas/${r.id}/renovacion`));
  const res = info.reserva;
  if (info.pendiente.length) {
    const f = form(`Renovar · ${res.unidad} · ${res.huesped}: faltan datos`, [
      { html: `<p>Para renovar hay que completar los datos del cliente y de los ocupantes (son los del contrato y del parte de viajeros):</p>
        <ul>${info.pendiente.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>
        <p class="muted">Pulse «Completar datos»: escanee el documento o rellene la ficha de cada uno. Al terminar, vuelva a «Renovar».</p>` },
    ], {}, async () => { setTimeout(() => ocupantesReserva(res, reload, () => renovarEstancia(r, reload)), 0); }, "Completar datos");
    return f;
  }
  form(`Renovar estancia · ${res.unidad} · ${res.huesped}`, [
    { html: `<p>Renovación al <b>mismo cliente</b> en el mismo apartamento: nueva estancia desde el <b>${fdate(info.desde)}</b> (salida actual, ${info.noches_anteriores} noches la anterior).
      El cliente firma un <b>contrato nuevo</b> y la renovación se cobra y factura aparte. Los datos del cliente y sus ocupantes se mantienen.</p>` },
    { k: "fecha_salida", t: "Nueva fecha de salida", type: "date", req: true, def: info.hasta },
    { k: "importe_total", t: "Importe de la renovación € (IVA incluido)", type: "number", def: 0 },
    ...(info.garajes.length ? [{ k: "renovar_garaje", t: `Renovar también la plaza de garaje ${info.garajes.join(", ")}`, type: "checkbox", def: true, wide: true }] : []),
    { k: "notas", t: "Notas", type: "textarea", wide: true },
  ], {}, async (d) => {
    const nueva = await post(`/api/turistico/reservas/${res.id}/renovar`, clean({ ...d, renovar_garaje: d.renovar_garaje !== false }));
    toast(`Renovación ${nueva.localizador} creada. Ahora el cliente firma el contrato.`);
    reload && reload();
    setTimeout(() => accommodationContract(nueva), 0);
  }, "Renovar y pasar al contrato");
}
// ---- cliente habitual: buscar su ficha (datos y documentos guardados) para no volver a pedirlos
const buscaClienteHtml = () => `<fieldset class="busca-cliente"><legend>¿Ya ha estado alojado? Busque su ficha</legend>
  <input type="search" data-buscacli placeholder="Nombre, apellidos, documento, teléfono o correo" autocomplete="off"><div data-clires class="cli-res"></div></fieldset>`;
function bindBuscaCliente(f, assetId) {  // solo las fichas de clientes de ese activo
  const res = $("[data-clires]", f);
  $("[data-buscacli]", f).oninput = debounce(async (e) => {
    const q = e.target.value.trim();
    if (q.length < 3) { res.innerHTML = ""; return; }
    const lista = (await get("/api/terceros", { tipo: "huesped", q, asset_id: assetId }).catch(() => [])).slice(0, 8);
    res.innerHTML = lista.length ? lista.map((c, i) => `<button type="button" class="btn sm" data-c="${i}">${esc(`${c.nombre} ${c.apellidos || ""}`.trim())}${c.documento_num ? ` · ${esc(c.documento_num)}` : ""}${c.telefono ? ` · ${esc(c.telefono)}` : ""}</button>`).join("") : '<span class="muted">Sin coincidencias: es un cliente nuevo.</span>';
    res.querySelectorAll("[data-c]").forEach((b) => (b.onclick = () => {
      const c = lista[b.dataset.c];
      f._cliente = c;
      rellena(f, Object.fromEntries(guestFields.filter((x) => x.k).map((x) => [x.k, c[x.k]])));
      res.innerHTML = `<p class="cli-ok">✔ Ficha de <b>${esc(c.nombre)} ${esc(c.apellidos || "")}</b>: se reutilizan sus datos y documentos. Revise y complete lo que falte.</p>`;
    }));
  }, 300);
}

// ---- estancias vencidas: siguen alojados después de su fecha de salida (y las que terminan en 3 días)
async function estanciasVencidas(cont, reload) {
  if (!cont) return;
  const v = await get("/api/turistico/vencidas", { asset_id: S.asset, dias: 3 }).catch(() => null);
  if (!v || !(v.vencidas.length + v.proximas.length)) { cont.innerHTML = ""; return; }
  const acc = (r) => [
    r.whatsapp && ["WhatsApp", () => window.open(r.whatsapp, "_blank", "noopener")],
    can("reservas.editar") && ["Renovar", () => renovarEstancia(r, reload)],
    can("reservas.editar") && ["Ampliar", () => editReservation(r, reload)],
    can("reservas.editar") && ["Check-out", () => confirm(`¿Dar la salida a ${r.huesped} (${r.unidad})?`) && run(() => post(`/api/turistico/reservas/${r.id}/checkout`), "Check-out realizado").then(reload)],
    ["Cliente", () => editGuest(r.guest_id, "huesped", reload)],
  ];
  const cols = [{ k: "unidad", t: "Apartamento" }, { k: "huesped", t: "Cliente" }, { k: "telefono", t: "Teléfono", f: (x) => esc(x || "—") },
    { k: "fecha_entrada", t: "Entrada", f: fdate }, { k: "fecha_salida", t: "Salida", f: fdate },
    { k: "dias", t: "Situación", f: (d) => (d > 0 ? `<span class="badge b-cancelada">vencida hace ${d} día${d === 1 ? "" : "s"}</span>` : d === 0 ? '<span class="badge b-pendiente">sale hoy</span>' : `<span class="badge b-pendiente">termina en ${-d} día${d === -1 ? "" : "s"}</span>`) }];
  cont.innerHTML = `<div class="aviso-vencidas"><h4>⚠ Estancias vencidas o que terminan pronto (${v.vencidas.length} vencidas · ${v.proximas.length} en 3 días)</h4>
    <p class="muted">Siguen alojados después de su fecha de salida, o la tienen muy próxima. <b>Renovar</b>: nueva estancia con contrato nuevo firmado por el cliente (pide los datos que falten). <b>Ampliar</b>: solo corrige la fecha de salida. O dé la salida. Con teléfono, «WhatsApp» abre el aviso al cliente ya escrito.</p><div data-t></div></div>`;
  table($("[data-t]", cont), cols, [...v.vencidas, ...v.proximas], acc);
}
// ---- ocupación actual exportada del PMS anterior
async function importarOcupacion(reload) {
  const aid = await pickAsset("apartamentos_turisticos");
  const f = form(`Importar ocupación del PMS anterior · ${assetName(aid)}`, [
    { html: `<p>Listado de ocupación exportado del PMS anterior (Excel con una hoja por planta: Localizador, Núm, Sótano/Plaza, FEntrada/FSalida, Ocupante, Teléfonos).</p>
      <ul class="muted"><li>Los <b>alojados</b> quedan con check-in hecho; si su salida ya pasó, como <b>estancia vencida</b> (aviso para renovar o dar la salida).</li>
      <li>Las <b>reservas</b> futuras quedan confirmadas.</li><li>La <b>plaza de garaje</b> de cada fila se reserva para las mismas fechas y sigue al apartamento.</li>
      <li>Si vuelve a importar el listado, se actualizan fechas y estado: no se duplica nada.</li></ul>` },
    { html: '<label>Fichero *<input type="file" accept=".xlsx" data-fich required></label>' },
  ], {}, async (_, fr) => {
    const fich = $("[data-fich]", fr).files[0];
    const enviar = (confirmar) => { const fd = new FormData(); fd.append("fichero", fich); fd.append("asset_id", aid); fd.append("confirmar", confirmar); return upload("/api/turistico/importar-ocupacion", fd); };
    const prev = await enviar(false);
    setTimeout(() => {
      const filas = prev.filas.map((x) => `<tr><td>${esc(x.localizador)}</td><td>${esc(x.unidad)}</td><td>${esc(x.ocupante)}</td><td>${fdate(x.entrada)} → ${fdate(x.salida)}</td>
        <td>${x.situacion === "alojado" ? (x.vencida ? '<span class="badge b-cancelada">alojado · vencida</span>' : '<span class="badge b-vigente">alojado</span>') : '<span class="badge b-confirmada">reserva</span>'}</td>
        <td>${esc(x.garaje || "")}</td><td style="white-space:normal">${x.estado === "ok" ? (x.accion === "actualizar" ? "se actualiza" : "nueva") + (x.aviso ? ` <span class="muted">· ${esc(x.aviso)}</span>` : "") : `<span class="badge b-cancelada">error</span> ${esc(x.motivo)}`}</td></tr>`).join("");
      form(`Vista previa · ${prev.nuevas} nuevas · ${prev.actualizadas} a actualizar · ${prev.vencidas} vencidas · ${prev.errores} con error`, [
        { html: `<div class="table-wrap" style="max-height:55vh;overflow:auto"><table><thead><tr><th>Localizador</th><th>Apto.</th><th>Ocupante</th><th>Estancia</th><th>Situación</th><th>Garaje</th><th>Resultado</th></tr></thead><tbody>${filas}</tbody></table></div>` },
      ], {}, async () => {
        const r = await enviar(true);
        toast(`Ocupación cargada: ${r.nuevas} nuevas, ${r.actualizadas} actualizadas, ${r.garajes} plazas de garaje`); reload && reload();
      }, "Cargar ocupación");
      $("#modal").classList.add("ancho");
    }, 0);
  }, "Comprobar fichero");
}

// ---- parte de viajeros: fichero para SES.HOSPEDAJE (plazo: 24 h desde la llegada)
V.ses = async (el) => {
  const aid = await pickAsset("apartamentos_turisticos");
  el.innerHTML = `<div class="toolbar"><strong>${esc(assetName(aid))}</strong><label>Llegadas desde<input type="date" id="d" value="${addDays(today(), -1)}"></label>
    <label>hasta<input type="date" id="h" value="${addDays(today(), 1)}"></label><span class="spacer"></span>
    ${can("reservas.editar") ? '<button class="btn primary" id="xml">Generar fichero para SES.HOSPEDAJE</button>' : ""}</div>
    <div id="aviso"></div><div id="t"></div>
    <div class="card nota"><h4>Cómo se comunica</h4><p>1. Registre a todos los ocupantes de cada llegada (botón <b>Ocupantes</b>). 2. Marque las reservas completas y genere el fichero. 3. En la sede <a href="https://hospedajes.ses.mir.es" target="_blank" rel="noopener">hospedajes.ses.mir.es</a>, entre con el usuario del establecimiento y cárguelo en <i>Comunicaciones → Carga de ficheros</i>. El plazo es de <b>24 horas</b> desde la llegada. Las reservas quedan marcadas como comunicadas.</p></div>`;
  const load = async () => {
    const st = await get("/api/turistico/ses", { asset_id: aid, desde: $("#d", el).value, hasta: $("#h", el).value });
    $("#aviso", el).innerHTML = st.codigo_establecimiento ? `<p class="muted">Código de establecimiento SES: <b>${esc(st.codigo_establecimiento)}</b></p>`
      : '<p class="error">Falta el código de establecimiento de SES.HOSPEDAJE: indíquelo en Activos → Editar.</p>';
    table($("#t", el), [
      { k: "id", t: "", f: (v, x) => `<input type="checkbox" data-sel="${v}" ${x.completo && !x.ses_comunicado ? "checked" : ""} ${x.completo ? "" : "disabled"}>` },
      { k: "localizador", t: "Localizador" }, { k: "unidad", t: "Unidad" }, { k: "huesped", t: "Titular" },
      { k: "fecha_entrada", t: "Entrada", f: fdate }, { k: "ocupantes_registrados", t: "Ocupantes", f: (v, x) => `${v} / ${x.adultos + x.ninos}` },
      { k: "completo", t: "Registro", f: (v, x) => (v ? '<span class="badge b-vigente">completo</span>' : `<span class="badge b-pendiente">pendiente</span><div class="muted peq">${esc(x.pendiente.join(" · "))}</div>`) },
      { k: "ses_comunicado", t: "Comunicado", f: (v) => (v ? `<span class="badge b-confirmada">${fdt(v)}</span>` : '<span class="muted">no</span>') },
    ], st.reservas, (x) => [["Ocupantes", () => ocupantesReserva(x, load)]]);
  };
  ["#d", "#h"].forEach((s) => ($(s, el).onchange = load));
  if ($("#xml", el)) $("#xml", el).onclick = () => {
    const ids = [...el.querySelectorAll("[data-sel]:checked")].map((c) => Number(c.dataset.sel));
    if (!ids.length) return toast("Marque las reservas completas que quiere comunicar", true);
    run(() => download("POST", `/api/turistico/ses/partes.xml?asset_id=${aid}`, ids), `Fichero generado con ${ids.length} reserva(s). Cárguelo en SES.HOSPEDAJE.`).then(load);
  };
  load();
};

// ---- encuesta mensual del INE (apartamentos turísticos)
async function encuestaIne() {
  const aid = await pickAsset("apartamentos_turisticos");
  const prev = new Date(); prev.setDate(1); prev.setMonth(prev.getMonth() - 1);
  form(`Encuesta INE · ${assetName(aid)}`, [
    { html: '<p class="muted">Encuesta de Ocupación en Apartamentos Turísticos: viajeros entrados y pernoctaciones por día y residencia, apartamentos ocupados y tarifa media por tipo de cliente. Calculado con los ocupantes registrados de cada reserva.</p>' },
    { k: "mes", t: "Mes", type: "month", req: true, def: prev.toISOString().slice(0, 7) },
  ], {}, async (d) => {
    const [anio, mes] = d.mes.split("-").map(Number);
    const q = { asset_id: aid, anio, mes };
    const x = await get("/api/turistico/ine", q), t = x.totales;
    setTimeout(() => {
      const f = form(`Encuesta INE · ${x.activo} · ${String(mes).padStart(2, "0")}/${anio}`, [{ html: `<div class="kpis">
        <div class="kpi"><b>${t.viajeros_entrados}</b><span>Viajeros entrados</span></div><div class="kpi"><b>${t.pernoctaciones}</b><span>Pernoctaciones</span></div>
        <div class="kpi"><b>${(t.ocupacion_apartamentos * 100).toFixed(1)} %</b><span>Ocupación apartamentos</span></div>
        <div class="kpi"><b>${(t.ocupacion_plazas * 100).toFixed(1)} %</b><span>Ocupación plazas</span></div><div class="kpi"><b>${eur(t.tarifa_media)}</b><span>Tarifa media sin IVA</span></div>
        <div class="kpi"><b>${x.apartamentos_disponibles}</b><span>Apartamentos abiertos</span></div></div>
        <h4>Residencia de los viajeros</h4><p>${x.residencias.map((y) => `${esc(y.residencia)}: <b>${y.entradas.reduce((p, c) => p + c, 0)}</b>`).join(" · ") || "Sin viajeros"}</p>
        ${x.avisos.length ? `<h4>Avisos</h4>${x.avisos.map((a) => `<p class="muted">• ${esc(a)}</p>`).join("")}` : ""}
        <p class="muted">Traslade los datos al cuestionario del INE en IRIA (iria.ine.es) con el Excel, que trae el detalle por día.</p>` }], {},
        async () => { await download("GET", "/api/turistico/ine.xlsx?" + new URLSearchParams(q)); }, "Descargar Excel");
      return f;
    }, 0);
  }, "Calcular");
}

V.hoy = async (el) => {
  el.innerHTML = `<div class="toolbar"><input type="date" id="f" value="${today()}"><span class="spacer"></span>${can("limpieza.editar") ? '<button class="btn" id="pl">Parte de limpieza</button>' : ""}${can("reservas.editar") ? '<button class="btn primary" id="new">Nueva reserva</button>' : ""}</div>
    <div id="venc"></div>
    <h4>Llegadas</h4><div id="l"></div><h4>Salidas</h4><div id="s"></div><h4>Alojados</h4><div id="a"></div>`;
  const load = async () => {
    estanciasVencidas($("#venc", el), load);
    const r = await get("/api/turistico/hoy", { asset_id: S.asset, fecha: $("#f", el).value });
    table($("#l", el), resCols, r.llegadas, resActions(load));
    table($("#s", el), resCols, r.salidas, resActions(load));
    table($("#a", el), resCols, r.alojados, resActions(load));
  };
  $("#f", el).onchange = load;
  if ($("#new", el)) $("#new", el).onclick = () => newReservation(load);
  if ($("#pl", el)) $("#pl", el).onclick = () => parteLimpieza($("#f", el).value);
  load();
};

V.reservas = async (el) => {
  el.innerHTML = `<div class="toolbar"><label>Desde<input type="date" id="d" value="${today()}"></label><label>Hasta<input type="date" id="h" value="${addDays(today(), 30)}"></label>
    <label>Estado<select id="e"><option value="">Todos</option>${["confirmada", "checkin", "checkout", "cancelada", "no_show"].map((x) => `<option>${x}</option>`).join("")}</select></label>
    <label>Buscar<input id="q" placeholder="Localizador, huésped, unidad"></label><span class="spacer"></span>${can("reservas.editar") ? '<button class="btn" id="ocu">Importar ocupación (PMS anterior)</button><button class="btn" id="imp">Importar Excel</button><button class="btn primary" id="new">Nueva reserva</button>' : ""}</div><div id="t"></div>`;
  const load = async () => table($("#t", el), resCols, await get("/api/turistico/reservas", { asset_id: S.asset, desde: $("#d", el).value, hasta: $("#h", el).value, estado: $("#e", el).value, q: $("#q", el).value }), resActions(load));
  ["#d", "#h", "#e"].forEach((s) => ($(s, el).onchange = load)); $("#q", el).oninput = debounce(load);
  if ($("#new", el)) $("#new", el).onclick = () => newReservation(load);
  if ($("#imp", el)) $("#imp", el).onclick = () => importarReservas(load);
  if ($("#ocu", el)) $("#ocu", el).onclick = () => importarOcupacion(load);
  load();
};

// Importación de reservas: primero vista previa fila a fila; después se importan las válidas
async function importarReservas(reload) {
  const aid = await pickAsset("apartamentos_turisticos");
  const f = form(`Importar reservas · ${assetName(aid)}`, [
    { html: `<p>Excel (.xlsx) o CSV con una fila por reserva. Use la <a href="#" data-plantilla>plantilla</a> o la exportación de Booking.
      Si no se indica la unidad, el PMS asigna un apartamento libre. No se registran cobros ni se emiten facturas.</p>` },
    { html: '<label>Fichero *<input type="file" accept=".xlsx,.csv" data-fich required></label>' },
  ], {}, async (_, fr) => {
    const fich = $("[data-fich]", fr).files[0];
    const enviar = (confirmar) => { const fd = new FormData(); fd.append("fichero", fich); fd.append("asset_id", aid); fd.append("confirmar", confirmar); return upload("/api/turistico/importar", fd); };
    const prev = await enviar(false);
    setTimeout(() => {
      const filas = prev.filas.map((x) => `<tr><td>${x.fila}</td><td>${esc(x.localizador || "")}</td><td>${esc(x.unidad || "")}${x.asignada ? ' <span class="muted">(auto)</span>' : ""}</td>
        <td>${fdate(x.entrada)}</td><td>${fdate(x.salida)}</td><td>${esc(x.huesped || "")}</td><td class="num">${x.importe_total != null ? eur(x.importe_total) : ""}</td>
        <td style="white-space:normal;min-width:220px">${x.estado === "valida" ? '<span class="badge b-vigente">válida</span>' : x.estado === "omitida" ? `<span class="badge">omitida</span> ${esc(x.motivo)}` : `<span class="badge b-cancelada">error</span> ${esc(x.motivo)}`}</td></tr>`).join("");
      form(`Vista previa · ${prev.validas} válidas, ${prev.errores} con error, ${prev.omitidas} omitidas`, [
        { html: `${prev.columnas_ignoradas.length ? `<p class="muted">Columnas no usadas: ${esc(prev.columnas_ignoradas.join(", "))}</p>` : ""}
          <div class="table-wrap" style="max-height:50vh;overflow:auto"><table><thead><tr><th>Fila</th><th>Localizador</th><th>Unidad</th><th>Entrada</th><th>Salida</th><th>Huésped</th><th class="num">Importe</th><th>Resultado</th></tr></thead><tbody>${filas}</tbody></table></div>
          <p>${prev.errores ? "Las filas con error no se importan: corríjalas en el fichero y vuelva a importarlo (las ya importadas no se duplican)." : ""}</p>` },
      ], {}, async () => {
        if (!prev.validas) throw new Error("No hay ninguna reserva válida que importar");
        const r = await enviar(true);
        toast(`${r.importadas} reservas importadas`); reload && reload();
      }, `Importar ${prev.validas} reservas`);
    }, 0);
  }, "Comprobar fichero");
  $("[data-plantilla]", f).onclick = (e) => { e.preventDefault(); run(() => download("GET", "/api/turistico/importar/plantilla")); };
}

V.planning = async (el) => {
  const pool = assetsOf("apartamentos_turisticos");
  const cur = pool.find((a) => String(a.id) === String(S.asset)) || pool[0];
  if (!cur) { el.innerHTML = '<div class="empty">Sin activos turísticos</div>'; return; }
  const bloques = await get("/api/unidades/bloques", { asset_id: cur.id });
  el.innerHTML = `<div class="toolbar"><strong>${esc(cur.nombre)}</strong>
    ${bloques.length ? `<label>Bloque<select id="b"><option value="">Todos</option>${bloques.map((b) => `<option>${esc(b)}</option>`).join("")}</select></label>` : ""}<label>Desde<input type="date" id="d" value="${today()}"></label>
    <label>Días<select id="n"><option>7</option><option selected>14</option><option>31</option></select></label>
    <span class="muted legend"><i style="background:#cfe0f5"></i>reservada<i style="background:#9cc0ea"></i>alojado<i style="background:#d9e8d9"></i>salida realizada<i style="background:#f5d0cb"></i>no disponible</span></div><div id="t" class="table-wrap"></div>`;
  const load = async () => {
    const p = await get("/api/turistico/planning", { asset_id: cur.id, desde: $("#d", el).value, dias: $("#n", el).value, bloque: $("#b", el)?.value });
    const days = [...Array(p.dias)].map((_, i) => addDays(p.desde, i));
    const head = `<tr><th>Unidad</th>${days.map((d) => `<th>${d.slice(8)}/${d.slice(5, 7)}</th>`).join("")}</tr>`;
    const body = p.unidades.map((u) => `<tr><td class="u">${esc(u.codigo)}</td>${days.map((d) => {
      const r = u.reservas.find((x) => x.entrada <= d && d < x.salida);
      if (r) return `<td class="${r.estado === "checkin" ? "in" : r.estado === "checkout" ? "co" : "occ"}" title="${esc(r.huesped)} ${fdate(r.entrada)}→${fdate(r.salida)}">${r.entrada === d ? esc(r.huesped.slice(0, 6)) : ""}</td>`;
      return `<td class="${["bloqueada", "fuera_servicio", "mantenimiento"].includes(u.estado) && d === p.desde ? "blk" : ""}"></td>`;
    }).join("")}</tr>`).join("");
    $("#t", el).innerHTML = `<table class="planning">${head}${body}</table>`;
  };
  $("#d", el).onchange = load; $("#n", el).onchange = load; if ($("#b", el)) $("#b", el).onchange = load;
  load();
};

// ---- alquiler residencial
// IVA del alquiler: vacío = automático (vivienda exenta; garajes, trasteros y locales al 21 %)
const ivaField = { k: "tipo_iva", t: "IVA (vacío = automático según el uso)", type: "select", options: [["0", "Exento (vivienda, o garaje arrendado con ella)"], ["21", "21 %"]] };
V.contratos = async (el) => {
  el.innerHTML = `<div class="toolbar"><select id="e"><option value="">Todos</option>${["borrador", "vigente", "finalizado", "rescindido"].map((x) => `<option ${x === "vigente" ? "selected" : ""}>${x}</option>`).join("")}</select>
    <span class="spacer"></span>${can("alquiler.editar") ? '<button class="btn primary" id="new">Nuevo contrato</button>' : ""}</div><div id="t"></div>`;
  const leaseFields = [
    { k: "referencia", t: "Referencia" }, { k: "fecha_inicio", t: "Fecha inicio", type: "date", req: true }, { k: "fecha_fin", t: "Fecha fin", type: "date" },
    { k: "renta_mensual", t: "Renta mensual € (sin IVA)", type: "number", req: true }, { k: "fianza", t: "Fianza €", type: "number" },
    ivaField,
    { k: "garantia_adicional", t: "Garantía adicional €", type: "number" }, { k: "dia_pago", t: "Día de pago", type: "number", def: 5 },
    { k: "indice_actualizacion", t: "Índice actualización", type: "select", options: list(["IRAV", "IPC", "NINGUNO"]), def: "IRAV" },
    { k: "estado", t: "Estado", type: "select", options: list(["borrador", "vigente"]), def: "vigente" },
  ];
  const load = async () => table($("#t", el), [
    { k: "referencia", t: "Ref." }, { k: "asset_id", t: "Activo", f: (v) => esc(assetName(v)) }, { k: "unidad", t: "Unidad" },
    { k: "inquilino", t: "Inquilino" }, { k: "fecha_inicio", t: "Inicio", f: fdate }, { k: "fecha_fin", t: "Fin", f: fdate },
    { k: "renta_mensual", t: "Renta (sin IVA)", num: true, f: eur }, { k: "fianza", t: "Fianza", num: true, f: eur },
    { k: "indice_actualizacion", t: "Índice" }, { k: "estado", t: "Estado", f: badge },
  ], await get("/api/alquiler/contratos", { asset_id: S.asset, estado: $("#e", el).value }), (l) => can("alquiler.editar") ? [
    ["Inquilino", () => editGuest(l.tenant_id, "inquilino")],
    ["Editar", () => form(`Contrato ${l.unidad}`, [
      { k: "referencia", t: "Referencia" }, { k: "fecha_fin", t: "Fecha fin", type: "date" }, { k: "fianza", t: "Fianza €", type: "number" },
      { k: "garantia_adicional", t: "Garantía adicional €", type: "number" }, { k: "dia_pago", t: "Día de pago", type: "number" },
      { k: "indice_actualizacion", t: "Índice", type: "select", options: list(["IRAV", "IPC", "NINGUNO"]) },
      ivaField,
      { k: "estado", t: "Estado", type: "select", options: list(["borrador", "vigente", "finalizado", "rescindido"]) },
      { k: "notas", t: "Notas", type: "textarea", wide: true }], l, async (d) => { await put(`/api/alquiler/contratos/${l.id}`, d); toast("Contrato actualizado"); load(); })],
    l.estado === "vigente" && ["Actualizar renta", () => form(`Actualizar renta (${eur(l.renta_mensual)}) · índice ${l.indice_actualizacion}`, [
      { k: "porcentaje", t: "Variación %", type: "number", req: true }, { k: "motivo", t: "Motivo / referencia índice", wide: true }], {},
      async (d) => { const r = await post(`/api/alquiler/contratos/${l.id}/actualizar-renta`, d); toast(`Nueva renta ${eur(r.renta_mensual)}`); load(); })],
  ] : []);
  $("#e", el).onchange = load;
  if ($("#new", el)) $("#new", el).onclick = async () => {
    const aid = await pickAsset("alquiler_residencial");
    const units = (await get("/api/unidades", { asset_id: aid })).filter((u) => u.estado !== "fuera_servicio");
    if (!units.length) return toast("El activo no tiene unidades. Dé de alta las viviendas primero.", true);
    conEscaner(form(`Nuevo contrato · ${assetName(aid)}`, [
      { html: scanHtml("1. Escanee el documento del inquilino (DNI, NIE/TIE, pasaporte)") },
      { html: "<h4>Inquilino</h4>" }, ...guestFields,
      { html: "<h4>Contrato</h4>" },
      { k: "unit_id", t: "Unidad", type: "select", req: true, options: units.map((u) => [u.id, `${u.codigo} · ${label(u.uso)} · ${label(u.estado)}`]) }, ...leaseFields,
      { k: "notas", t: "Notas contrato", type: "textarea", wide: true },
    ], {}, async (d, fr) => {
      const t = {}; guestFields.filter((f) => f.k).forEach((f) => { t[f.k] = d[f.k]; delete d[f.k]; });
      await post("/api/alquiler/contratos", { ...clean(d), unit_id: Number(d.unit_id), tenant: clean(t), documentos: fr._docs.map((x) => x.id) });
      toast("Contrato creado"); load();
    }));
  };
  load();
};

V.recibos = async (el) => {
  const mes = today().slice(0, 7);
  el.innerHTML = `<div class="toolbar"><label>Periodo<input type="month" id="p" value="${mes}"></label>
    <label>Estado<select id="e"><option value="">Todos</option>${["pendiente", "parcial", "pagado", "anulado"].map((x) => `<option>${x}</option>`).join("")}</select></label>
    <span class="spacer"></span>${can("alquiler.editar") ? '<button class="btn primary" id="gen">Emitir recibos del periodo</button>' : ""}</div><div id="t"></div>`;
  const load = async () => table($("#t", el), [
    { k: "periodo", t: "Periodo" }, { k: "asset_id", t: "Activo", f: (v) => esc(assetName(v)) }, { k: "unidad", t: "Unidad" },
    { k: "inquilino", t: "Inquilino" }, { k: "concepto", t: "Concepto" }, { k: "fecha_vencimiento", t: "Vence", f: fdate },
    { k: "importe", t: "Importe", num: true, f: (v, c) => eur(v) + (c.tipo_iva > 0 ? ` <span class="muted">(IVA ${c.tipo_iva} %)</span>` : "") }, { k: "importe_pagado", t: "Cobrado", num: true, f: eur },
    { k: "pendiente", t: "Pendiente", num: true, f: eur }, { k: "estado", t: "Estado", f: badge },
  ], await get("/api/alquiler/recibos", { asset_id: S.asset, periodo: $("#p", el).value, estado: $("#e", el).value }), (c) =>
    can("alquiler.editar") && ["pendiente", "parcial"].includes(c.estado) ? [
      ["Cobrar", () => cobroForm(`Cobro recibo ${c.unidad} ${c.periodo} · ${c.inquilino}`, c.pendiente, `/api/alquiler/recibos/${c.id}/cobro`, load, c.asset_id)],
      c.importe_pagado == 0 && ["Anular", () => confirm("¿Anular recibo?") && run(() => post(`/api/alquiler/recibos/${c.id}/anular`), "Recibo anulado").then(load), "danger"],
    ] : []);
  $("#p", el).onchange = load; $("#e", el).onchange = load;
  if ($("#gen", el)) $("#gen", el).onclick = () => run(() => post("/api/alquiler/recibos/generar", clean({ periodo: $("#p", el).value, asset_id: S.asset ? Number(S.asset) : null })), (r) => `${r.creados} recibos emitidos`).then(load);
  load();
};

V.facturas = async (el) => {
  const series = [...new Set(S.assets.map((a) => a.serie_factura).filter(Boolean))].sort();
  el.innerHTML = `<div class="toolbar"><label>Año<input type="number" id="y" value="${new Date().getFullYear()}" style="width:90px"></label>
    <label>Serie<select id="s"><option value="">Todas</option>${series.flatMap((x) => [x, x + "R"]).map((x) => `<option>${esc(x)}</option>`).join("")}</select></label>
    <label>Buscar<input id="q" placeholder="Nº de factura, cliente, concepto"></label><span class="spacer"></span>
    <button class="btn" id="csv">Libro de facturas emitidas (Excel)</button>${can("reservas.editar") || can("alquiler.editar") ? '<button class="btn primary" id="fsrv">Nueva factura de servicios</button>' : ""}</div><div id="t"></div><p id="tot"></p>`;
  const filtros = () => ({ asset_id: S.asset, anio: $("#y", el).value, serie: $("#s", el).value, q: $("#q", el).value });
  const load = async () => {
    const rows = await get("/api/facturas", filtros());
    table($("#t", el), [
      { k: "codigo", t: "Factura", f: (v) => `<b>${esc(v)}</b>` }, { k: "fecha_expedicion", t: "Fecha", f: fdate }, { k: "activo", t: "Activo" },
      { k: "cliente", t: "Cliente", f: (v) => esc(v.nombre) }, { k: "cliente", t: "NIF", f: (v) => esc(v.nif || "") },
      { k: "concepto", t: "Concepto", f: (v, r) => { const p = r.lineas[0].concepto; return `<span title="${esc(v)}">${esc(p.length > 55 ? p.slice(0, 55) + "…" : p)}${r.lineas.length > 1 ? ` <span class="badge">+${r.lineas.length - 1}</span>` : ""}</span>`; } },
      { k: "base_imponible", t: "Base", num: true, f: eur }, { k: "tipo_iva", t: "IVA", num: true, f: (v, r) => r.desglose.map((x) => (x.tipo_iva == 0 ? "Exento" : x.tipo_iva + " %")).join(" + ") },
      { k: "cuota_iva", t: "Cuota", num: true, f: eur }, { k: "total", t: "Total", num: true, f: eur },
      { k: "tipo", t: "", f: (v, r) => (v === "rectificativa" ? badge("rectificativa") : r.rectificada_por ? `<span class="badge b-rectificada">rectificada por ${esc(r.rectificada_por)}</span>` : "") },
    ], rows, (r) => [
      ["PDF", () => descargarFactura(r.id)],
      can("facturas.rectificar") && r.tipo === "ordinaria" && !r.rectificada_por && ["Rectificar", () => form(`Rectificar la factura ${r.codigo} (${eur(r.total)})`, [
        { html: `<p>Se emitirá una <b>factura rectificativa</b> por ${eur(-r.total)} en la serie ${esc(r.serie)}R que anula esta factura, y se deshará el cobro (el recibo o la reserva vuelven a quedar pendientes por ese importe).</p>` },
        { k: "motivo", t: "Motivo de la rectificación", type: "textarea", req: true, wide: true },
      ], {}, async (d) => { const x = await post(`/api/facturas/${r.id}/rectificar`, d); toast(`Rectificativa ${x.codigo} emitida`); load(); await descargarFactura(x.id); }, "Emitir rectificativa"), "danger"],
    ]);
    const sum = (k) => rows.reduce((a, x) => a + Number(x[k]), 0);
    $("#tot", el).innerHTML = rows.length ? `Base imponible <b>${eur(sum("base_imponible"))}</b> · IVA <b>${eur(sum("cuota_iva"))}</b> · Total <b>${eur(sum("total"))}</b>` : "";
  };
  $("#y", el).onchange = load; $("#s", el).onchange = load; $("#q", el).oninput = debounce(load);
  $("#csv", el).onclick = () => run(() => download("GET", "/api/facturas/libro.csv?" + new URLSearchParams(clean({ ...filtros(), q: null }))));
  if ($("#fsrv", el)) $("#fsrv", el).onclick = () => facturaServicios(load);
  load();
};

V.informes = async (el) => {
  const y = new Date().getFullYear();
  const INF = [
    ["ocupacion", "Ocupación", "Turísticos: noches disponibles y ocupadas, % de ocupación, ADR y RevPAR por mes. Residencial: unidades alquiladas por uso.", can("reservas.ver") || can("alquiler.ver")],
    ["produccion", "Producción", "Lo facturado cada mes según la fecha de factura: alojamiento, rentas y servicios (sin IVA), IVA y total, por activo.", can("finanzas.ver")],
    ["morosidad", "Morosidad", "Recibos vencidos sin cobrar y reservas con saldo, con contacto del cliente y antigüedad de la deuda (a la fecha final).", can("alquiler.ver") || can("reservas.ver")],
    ["mantenimiento", "Costes de mantenimiento", "Órdenes de trabajo del periodo con sus costes, y resúmenes por instalación, tipo y proveedor.", can("mantenimiento.ver")],
  ].filter((x) => x[3]);
  el.innerHTML = `<div class="toolbar"><label>Desde<input type="date" id="d" value="${y}-01-01"></label><label>Hasta<input type="date" id="h" value="${today()}"></label>
    <span class="muted">Activo: ${esc(S.asset ? assetName(Number(S.asset)) : "todos los de su ámbito")} (filtro de arriba)</span></div>
    <div class="cards">${INF.map(([k, t, d]) => `<div class="card"><h3>${esc(t)}</h3><p class="sub">${esc(d)}</p><button class="btn primary" data-inf="${k}">Descargar Excel</button></div>`).join("")}</div>`;
  el.querySelectorAll("[data-inf]").forEach((b) => (b.onclick = () => run(() => download("GET", `/api/informes/${b.dataset.inf}?` + new URLSearchParams(clean({ desde: $("#d", el).value, hasta: $("#h", el).value, asset_id: S.asset }))))));
  if (can("reservas.ver") && assetsOf("apartamentos_turisticos").length) {
    $(".cards", el).insertAdjacentHTML("beforeend", '<div class="card"><h3>Encuesta del INE</h3><p class="sub">Cuestionario mensual de ocupación en apartamentos turísticos: viajeros y pernoctaciones por día y residencia, ocupación y precios.</p><button class="btn primary" id="ine">Preparar encuesta</button></div>');
    $("#ine", el).onclick = encuestaIne;
  }
};

// Factura solo de servicios: a un cliente externo (p.ej. plaza de aparcamiento) o al huésped de una reserva
async function facturaServicios(reload, reserva) {
  const aid = reserva ? reserva.asset_id : await pickAsset();
  const f = form(reserva ? `Factura de servicios · reserva ${reserva.localizador || reserva.id} · ${reserva.huesped}` : `Nueva factura de servicios · ${assetName(aid)}`, [
    ...(reserva ? [] : [{ html: "<h4>Cliente</h4>" }, { k: "nombre", t: "Nombre / razón social", req: true }, { k: "nif", t: "NIF / CIF", req: true },
      { k: "domicilio", t: "Domicilio fiscal completo", req: true, wide: true }]),
    { html: serviciosHtml() },
    { k: "forma_pago", t: "Forma de pago", type: "select", options: kv(S.cat.formas_pago) },
    { k: "fecha_operacion", t: "Fecha del servicio", type: "date", def: today() },
    { html: '<p class="muted">Se emite con el siguiente número de la serie del activo y se descarga en PDF.</p>' },
  ], {}, async (d, fr) => {
    const lineas = leerServicios(fr);
    if (!lineas.length) throw new Error("Añada al menos un servicio");
    const x = await post("/api/facturas/servicios", clean({ asset_id: aid, reservation_id: reserva?.id, lineas, forma_pago: d.forma_pago, fecha_operacion: d.fecha_operacion,
      cliente: reserva ? null : { nombre: d.nombre, nif: d.nif, domicilio: d.domicilio } }));
    toast(`Factura ${x.codigo} emitida`); reload && reload(); await descargarFactura(x.id);
  }, "Emitir factura");
  await bindServicios(f, aid, 1);
}

V.servicios = async (el) => {
  const rows = await get("/api/servicios", { todos: true });
  el.innerHTML = `<div class="toolbar"><span class="muted">Servicios que se pueden añadir a las facturas. Precio con IVA incluido; si se deja vacío, se indica al facturar.</span><span class="spacer"></span>${can("activos.editar") ? '<button class="btn primary" id="new">Nuevo servicio</button>' : ""}</div><div id="t"></div>`;
  const fields = [
    { k: "nombre", t: "Servicio", req: true, wide: true },
    { k: "asset_id", t: "Activo (vacío = todos)", type: "select", options: opts(S.assets) },
    { k: "precio", t: "Precio € (IVA incluido)", type: "number" }, { k: "unidad", t: "Unidad", type: "select", req: true, options: list(["ud", "día", "noche", "semana", "mes", "hora"]), def: "ud" },
    { k: "tipo_iva", t: "IVA", type: "select", req: true, options: [["21", "21 %"], ["10", "10 %"], ["4", "4 %"], ["0", "Exento"]], def: "21" },
    { k: "activo", t: "Disponible", type: "checkbox", def: true },
  ];
  const guardar = (sv) => form(sv ? sv.nombre : "Nuevo servicio", fields, sv ? { ...sv, tipo_iva: String(Number(sv.tipo_iva)) } : {}, async (d) => {
    d.asset_id = d.asset_id ? Number(d.asset_id) : null; d.tipo_iva = Number(d.tipo_iva);
    if (sv) await put(`/api/servicios/${sv.id}`, d); else await post("/api/servicios", d);
    toast("Servicio guardado"); go("servicios");
  });
  if ($("#new", el)) $("#new", el).onclick = () => guardar(null);
  table($("#t", el), [{ k: "nombre", t: "Servicio" }, { k: "asset_id", t: "Activo", f: (v) => esc(v ? assetName(v) : "Todos") },
    { k: "unidad", t: "Unidad" }, { k: "precio", t: "Precio (IVA incl.)", num: true, f: (v) => (v == null ? '<span class="muted">al facturar</span>' : eur(v)) },
    { k: "tipo_iva", t: "IVA", num: true, f: (v) => (v == 0 ? "Exento" : v + " %") }, { k: "activo", t: "Estado", f: (v) => (v ? badge("vigente").replace(">vigente<", ">disponible<") : badge("baja")) }],
  rows, (sv) => (can("activos.editar") ? [["Editar", () => guardar(sv)]] : []));
};

V.inquilinos = (el) => contactsView(el, "inquilino");
V.huespedes = (el) => contactsView(el, "huesped");
async function contactsView(el, tipo) {
  const perm = { inquilino: "alquiler", huesped: "reservas" }[tipo];
  el.innerHTML = `<div class="toolbar"><input id="q" placeholder="Nombre, documento, email, teléfono"><span class="spacer"></span>${can(perm + ".editar") ? '<button class="btn primary" id="new">Nuevo</button>' : ""}</div><div id="dup"></div><div id="t"></div>`;
  const fields = [...guestFields, { k: "iban", t: "IBAN" }, { k: "notas", t: "Notas", type: "textarea", wide: true }];
  const load = async () => table($("#t", el), [
    { k: "nombre", t: "Nombre" }, { k: "apellidos", t: "Apellidos" }, { k: "documento_num", t: "Documento" },
    { k: "unidades", t: "Apartamentos", f: (v, c) => (v.length ? `<b>${c.n_apartamentos}</b> <span class="muted">${esc(v.join(", "))}</span>` : '<span class="muted">—</span>') },
    { k: "email", t: "Email" }, { k: "telefono", t: "Teléfono" },
    { k: "activo", t: "Activo", f: (v) => esc(v || "Sin activo") },
  ], await get("/api/terceros", { tipo, q: $("#q", el).value, asset_id: S.asset }), (c) => [[can(perm + ".editar") ? "Ficha" : "Ver", () => editGuest(c.id, tipo, load)]]);
  const repetidos = async () => {
    if (!can(perm + ".editar")) return;
    const g = await get("/api/terceros/duplicados", { tipo }).catch(() => []);
    $("#dup", el).innerHTML = g.length ? `<div class="aviso-vencidas"><b>${g.length} cliente(s) con la ficha repetida</b> (mismo nombre). Revise y únalas para que cada cliente tenga una sola ficha con todos sus apartamentos. <button class="btn sm primary" data-revisar>Revisar y unir</button></div>` : "";
    if (g.length) $("[data-revisar]", el).onclick = () => unirFichas(g, () => { load(); repetidos(); });
  };
  $("#q", el).oninput = debounce(load);
  if ($("#new", el)) $("#new", el).onclick = () => {
    const activos = assetsOf(tipo === "inquilino" ? "alquiler_residencial" : "apartamentos_turisticos");
    const f = form("Nuevo", [{ html: scanHtml("1. Escanee el documento del cliente (DNI, NIE/TIE, pasaporte)") },
      { k: "asset_id", t: "Activo (cada recepción ve solo sus clientes)", type: "select", req: true, options: opts(activos), def: S.asset }, ...fields], {},
      async (d, fr) => {
        const a = S.assets.find((x) => x.id === Number(d.asset_id));
        await post("/api/terceros", clean({ ...d, asset_id: a.id, company_id: a.company_id, tipo, documentos: fr._docs.map((x) => x.id) }));
        toast("Creado"); load(); repetidos();
      });
    conEscaner(f);
  };
  load(); repetidos();
}

// Fichas repetidas: se elige la que se conserva y las demás se unen a ella (reservas, contratos, documentos)
function unirFichas(grupos, done) {
  const g = grupos[0];
  if (!g) return done();
  const desc = (c) => `Ficha ${c.id}: ${c.documento_num || "sin documento"} · ${c.telefono || "sin teléfono"} · ${c.email || "sin correo"} · ${c.reservas} reserva(s)${c.unidades.length ? ` · ${c.unidades.join(", ")}` : ""}`;
  form(`Ficha repetida: ${g.nombre}${g.activo ? ` · ${g.activo}` : ""} (${grupos.length} pendiente(s))`, [
    { html: g.documentos_distintos
      ? '<p class="error">Estas fichas tienen documentos distintos: son personas diferentes con el mismo nombre. Solo se pueden unir las que coinciden.</p>'
      : '<p class="muted">Se conserva la ficha elegida; las demás se unen a ella: pasan sus reservas, contratos, documentos escaneados y facturas, y se completan los datos que falten.</p>' },
    { k: "conservar", t: "Conservar la ficha", type: "select", req: true, options: g.fichas.map((c) => [String(c.id), desc(c)]), def: String(g.principal), wide: true },
    { k: "unir", t: "Unir a ella", type: "checks", options: g.fichas.map((c) => [String(c.id), desc(c)]) },
  ], { unir: g.documentos_distintos ? [] : g.fichas.map((c) => String(c.id)) }, async (d) => {
    const ids = d.unir.map(Number).filter((x) => x !== Number(d.conservar));
    if (ids.length) {
      await post(`/api/terceros/${d.conservar}/fusionar`, { ids });
      toast(`${g.nombre}: ${ids.length + 1} fichas unidas en una`);
    }
    unirFichas(grupos.slice(1), done);
  }, "Unir y seguir");
}

// ---- proveedores del grupo (no dependen de ninguna sociedad)
const TIPOS_PERSONA = [["empresa", "Empresa (CIF)"], ["autonomo", "Autónomo (DNI/NIE)"], ["particular", "Persona física (DNI/NIE)"]];
V.proveedores = async (el) => {
  const editar = can("mantenimiento.editar");
  el.innerHTML = `<div class="toolbar"><input id="q" placeholder="Nombre, CIF/DNI, actividad, municipio"><label class="check"><input type="checkbox" id="baja"> Ver también los de baja</label>
    <span class="spacer"></span>${editar ? '<button class="btn primary" id="new">Nuevo proveedor</button>' : ""}</div>
    <p class="muted">Fichero de proveedores del grupo, común a todas las sociedades. Se usa al indicar el proveedor de una orden de trabajo, la empresa mantenedora de un plan preventivo o la empresa del personal.</p><div id="t"></div>`;
  const fields = [
    { k: "nombre", t: "Nombre o razón social", req: true, wide: true },
    { k: "tipo_persona", t: "Tipo", type: "select", req: true, options: TIPOS_PERSONA, def: "empresa" },
    { k: "nif", t: "CIF / DNI / NIE" },
    { k: "direccion", t: "Domicilio", wide: true }, { k: "cp", t: "C.P." }, { k: "municipio", t: "Municipio" },
    { k: "provincia", t: "Provincia" }, { k: "pais", t: "País", def: "España" },
    { k: "email", t: "Correo electrónico", type: "email" }, { k: "telefono", t: "Teléfono" },
    { k: "persona_contacto", t: "Persona de contacto" }, { k: "actividad", t: "Actividad / gremio" },
    { k: "activo", t: "Proveedor en activo", type: "checkbox", def: true },
    { k: "notas", t: "Notas", type: "textarea", wide: true },
  ];
  const guardar = (p) => async (d) => {
    await (p ? put(`/api/proveedores/${p.id}`, d) : post("/api/proveedores", d));
    S.proveedores = null; toast(p ? "Proveedor guardado" : "Proveedor dado de alta"); load();
  };
  const load = async () => table($("#t", el), [
    { k: "nombre", t: "Nombre" }, { k: "nif", t: "CIF / DNI" }, { k: "tipo_persona_nombre", t: "Tipo" },
    { k: "actividad", t: "Actividad" }, { k: "municipio", t: "Municipio" }, { k: "telefono", t: "Teléfono" },
    { k: "email", t: "Correo" }, { k: "activo", t: "Estado", f: (v) => (v ? "En activo" : '<span class="muted">Baja</span>') },
  ], await get("/api/proveedores", { q: $("#q", el).value, solo_activos: !$("#baja", el).checked }), (p) => [
    [editar ? "Ficha" : "Ver", () => form(p.nombre, fields, p, editar ? guardar(p) : async () => {}, editar ? "Guardar" : "Cerrar")],
    editar && ["Borrar", async () => { if (confirm(`¿Borrar la ficha de ${p.nombre}? Las órdenes de trabajo conservan su nombre.`)) { await run(() => api("DELETE", `/api/proveedores/${p.id}`), "Ficha borrada"); S.proveedores = null; load(); } }, "danger"],
  ]);
  $("#q", el).oninput = debounce(load); $("#baja", el).onchange = load;
  if ($("#new", el)) $("#new", el).onclick = () => form("Nuevo proveedor", fields, {}, guardar(null));
  load();
};
// Sugerencias del fichero de proveedores en los campos de texto «proveedor» / «empresa»
async function sugerirProveedores(f, ...campos) {
  if (!can("mantenimiento.ver")) return;
  S.proveedores = S.proveedores || await get("/api/proveedores", { solo_activos: true }).catch(() => []);
  if (!f.querySelector("#dl-prov")) f.insertAdjacentHTML("beforeend", `<datalist id="dl-prov">${S.proveedores.map((p) => `<option value="${esc(p.nombre)}">${esc(p.actividad || "")}</option>`).join("")}</datalist>`);
  campos.forEach((c) => f.elements[c]?.setAttribute("list", "dl-prov"));
}

// ---- mantenimiento
async function newWorkOrder(assetId, unitId, zona) {  // zona: {zona, nombre} de una zona común del plano
  const aid = assetId || await pickAsset();
  const units = zona ? [] : await get("/api/unidades", { asset_id: aid });
  const titulo = zona ? `Nueva incidencia · ${zona.nombre}` : unitId ? `Nueva incidencia · ${units.find((u) => u.id === unitId)?.codigo ?? ""}` : `Nueva orden de trabajo · ${assetName(aid)}`;
  return new Promise((resolve) => sugerirProveedores(bindFotos(form(titulo, [
    { k: "titulo", t: "Título", req: true, wide: true },
    ...(zona ? [] : [{ k: "unit_id", t: "Unidad (vacío = zonas comunes)", type: "select", options: units.map((u) => [u.id, u.codigo]) }]),
    ...(can("mantenimiento.editar") ? [{ k: "tipo", t: "Tipo", type: "select", req: true, options: list(["correctivo", "preventivo", "normativo", "mejora"]), def: "correctivo" }] : []),
    { k: "categoria", t: "Instalación / gremio", type: "select", req: true, options: list(S.cat.categorias_mto), def: "general" },
    { k: "prioridad", t: "Prioridad", type: "select", req: true, options: list(S.cat.prioridades), def: "media" },
    ...(can("mantenimiento.editar") ? [{ k: "asignado_a", t: "Asignado a" }, { k: "proveedor", t: "Proveedor" },
      { k: "coste_estimado", t: "Coste estimado €", type: "number" }, { k: "fecha_prevista", t: "Fecha prevista", type: "date" }] : []),
    ...(zona ? [] : [{ k: "bloquea_unidad", t: "Bloquear unidad (fuera de venta hasta cierre)", type: "checkbox", wide: true }]),
    { k: "descripcion", t: "Descripción de la avería", type: "textarea", wide: true },
    { html: fotosHtml("Fotos de la avería (opcional)") },
  ], { unit_id: unitId }, async (d, f) => {
    const w = await post("/api/mantenimiento/ordenes", clean({ ...d, asset_id: aid, unit_id: d.unit_id ? Number(d.unit_id) : null, zona: zona?.zona }));
    const n = await subirFotos(f, w.id, "averia");
    toast(`Orden de trabajo OT-${String(w.id).padStart(5, "0")} creada` + (n ? ` con ${n} foto(s)` : "") + (w.prioridad === "urgente" ? ". Se ha avisado por correo." : ""));
    resolve();
  })), "proveedor"));
}
// Bloque de fotos: en el móvil «Hacer foto» abre directamente la cámara trasera
function fotosHtml(titulo, pdf = false) {
  return `<fieldset><legend>${esc(titulo)}</legend><div class="toolbar" style="margin:0">
    <label class="btn">📷 Hacer foto<input type="file" accept="image/*" capture="environment" multiple data-fotos hidden></label>
    <label class="btn">📁 Elegir ${pdf ? "fotos o PDF" : "fotos"}<input type="file" accept="image/*${pdf ? ",application/pdf" : ""}" multiple data-fotos hidden></label>
    <span class="muted" data-fotosmsg>Ninguna seleccionada</span></div></fieldset>`;
}
function ficherosElegidos(f) { return [...f.querySelectorAll("[data-fotos]")].flatMap((i) => [...i.files]); }
function bindFotos(f) {
  f.querySelectorAll("[data-fotos]").forEach((i) => (i.onchange = () => {
    const n = ficherosElegidos(f);
    $("[data-fotosmsg]", f).textContent = n.length ? `${n.length} fichero(s): ${n.map((x) => x.name).join(", ").slice(0, 80)}` : "Ninguna seleccionada";
  }));
}
async function subirFotos(f, wid, tipo, descripcion) {
  const files = ficherosElegidos(f);
  if (!files.length) return 0;
  const fd = new FormData(); fd.append("tipo", tipo); if (descripcion) fd.append("descripcion", descripcion);
  files.forEach((x) => fd.append("ficheros", x));
  return (await upload(`/api/mantenimiento/ordenes/${wid}/adjuntos`, fd)).length;
}
async function adjuntosOT(w, reload) {
  const editar = can("mantenimiento.editar");
  const tipos = Object.entries({ averia: "Foto de la avería", trabajo: "Foto del trabajo terminado", oca: "Certificado OCA / inspección", factura: "Factura de proveedor", presupuesto: "Presupuesto", otro: "Otro documento" })
    .filter(([k]) => editar || ["averia", "otro"].includes(k));
  const f = form(`OT-${String(w.id).padStart(5, "0")} · ${w.titulo} · fotos y documentos`, [
    { html: '<div data-lista class="adjuntos"><p class="muted">Cargando…</p></div>' },
    ...(canOpenOT() || editar ? [
      { html: "<h4>Añadir</h4>" },
      { k: "tipo", t: "Tipo", type: "select", req: true, options: tipos, def: w.conf_mto_por || w.estado === "cerrada" ? (editar ? "trabajo" : "otro") : "averia" },
      { k: "descripcion", t: "Descripción (opcional)" },
      { html: fotosHtml("Ficheros", true) }] : []),
  ], {}, async (d, fr) => {
    if (!ficherosElegidos(fr).length) throw new Error("Elija o haga al menos una foto");
    const n = await subirFotos(fr, w.id, d.tipo, d.descripcion);
    toast(`${n} fichero(s) adjuntado(s)`); reload && reload();
    setTimeout(() => adjuntosOT(w, reload), 0);
  }, "Subir");
  bindFotos(f);
  const lista = await get(`/api/mantenimiento/ordenes/${w.id}/adjuntos`);
  const cont = $("[data-lista]", f);
  if (!cont) return;
  if (!lista.length) { cont.innerHTML = '<p class="muted">Sin fotos ni documentos.</p>'; return; }
  cont.innerHTML = lista.map((a) => `<figure data-a="${a.id}">
      <div class="thumb">${a.mime.startsWith("image/") ? "" : '<span class="pdf">PDF</span>'}</div>
      <figcaption><b>${esc(a.tipo_nombre)}</b><br>${esc(a.descripcion || a.nombre)}<br><span class="muted">${esc(a.usuario || "")} · ${fdt(a.subido)}</span>
      <br><a href="#" data-ver>Abrir</a>${editar || a.user_id === S.me.id ? ' · <a href="#" class="danger" data-borrar>Borrar</a>' : ""}</figcaption></figure>`).join("");
  for (const a of lista) {
    const fig = cont.querySelector(`[data-a="${a.id}"]`);
    $("[data-ver]", fig).onclick = (e) => { e.preventDefault(); abrirFichero(`/api/mantenimiento/adjuntos/${a.id}`); };
    $(".thumb", fig).onclick = () => abrirFichero(`/api/mantenimiento/adjuntos/${a.id}`);
    const del = $("[data-borrar]", fig);
    if (del) del.onclick = async (e) => {
      e.preventDefault();
      if (!confirm(`¿Borrar «${a.nombre}»?`)) return;
      await run(() => api("DELETE", `/api/mantenimiento/adjuntos/${a.id}`), "Adjunto borrado");
      fig.remove(); reload && reload();
    };
    if (a.mime.startsWith("image/")) blobUrl(`/api/mantenimiento/adjuntos/${a.id}`).then((u) => ($(".thumb", fig).style.backgroundImage = `url(${u})`)).catch(() => {});
  }
}

V.ordenes = async (el) => {
  el.innerHTML = `<div class="toolbar"><select id="e"><option value="abiertas">Abiertas</option><option value="">Todas</option>${S.cat.estados_ot.map((x) => `<option value="${x}">${label(x)}</option>`).join("")}</select>
    <select id="tp"><option value="">Todos los tipos</option>${["correctivo", "preventivo", "normativo", "mejora"].map((x) => `<option>${x}</option>`).join("")}</select>
    <span class="spacer"></span>${canOpenOT() ? '<button class="btn primary" id="new">Nueva OT</button>' : ""}</div>
    <p class="muted">Flujo: se abre la OT → mantenimiento confirma el trabajo → limpieza confirma la unidad → recepción cierra. Las preventivas de zonas comunes no pasan por limpieza.</p><div id="t"></div>`;
  const check = (who, when) => (who ? `<span title="${esc(fdt(when))}">✓ ${esc(who)}</span>` : '<span class="muted">pendiente</span>');
  const load = async () => {
    const e = $("#e", el).value;
    const rows = await get("/api/mantenimiento/ordenes", { asset_id: S.asset, tipo: $("#tp", el).value, ...(e === "abiertas" ? { abiertas: true } : { estado: e }) });
    table($("#t", el), [
      { k: "id", t: "Nº", f: otNum }, { k: "fecha_apertura", t: "Apertura", f: fdate }, { k: "asset_id", t: "Activo", f: (v) => esc(assetName(v)) },
      { k: "unidad", t: "Unidad", f: (v, w) => esc(v || w.zona_nombre || "Z. comunes") }, { k: "titulo", t: "Título" },
      { k: "categoria", t: "Instalación" }, { k: "prioridad", t: "Prioridad", f: badge }, { k: "abierta_por_nombre", t: "Abierta por" },
      { k: "asignado_a", t: "Asignado" }, { k: "envios", t: "Enviada", f: (v) => (v?.length ? `<span title="${esc(v.map((e) => `${fdt(e.fecha)} ${e.nombre} (${e.canal === "email" ? "correo" : "WhatsApp"})`).join("\n"))}">✉ ${esc([...new Set(v.map((e) => e.nombre))].join(", "))}</span>` : "") }, { k: "conf_mto_por_nombre", t: "Mantenimiento", f: (v, w) => check(v, w.conf_mto_fecha) },
      { k: "conf_limpieza_por_nombre", t: "Limpieza", f: (v, w) => (w.requiere_limpieza ? check(v, w.conf_limpieza_fecha) : '<span class="muted">no aplica</span>') },
      { k: "coste_real", t: "Coste", num: true, f: eur }, { k: "estado", t: "Estado", f: badge },
    ], rows, (w) => {
      const comunes = [
        [`📎 ${w.n_adjuntos || ""}`.trim(), () => adjuntosOT(w, load)],
        ["Parte PDF", () => run(() => download("GET", `/api/mantenimiento/ordenes/${w.id}/parte`))],
      ];
      if (["cerrada", "cancelada"].includes(w.estado)) return comunes;
      const enTrabajo = !w.conf_mto_por;
      return [...comunes,
        puedeEnviarOT() && enTrabajo && ["Enviar", () => enviarOT(w, load)],
        can("mantenimiento.editar") && enTrabajo && ["Editar", () => sugerirProveedores(form(`OT ${w.id}: ${w.titulo}`, [
          { k: "titulo", t: "Título", req: true, wide: true }, { k: "estado", t: "Estado", type: "select", options: list(["abierta", "asignada", "en_curso", "pendiente_material"]) },
          { k: "prioridad", t: "Prioridad", type: "select", options: list(S.cat.prioridades) }, { k: "categoria", t: "Instalación", type: "select", options: list(S.cat.categorias_mto) },
          { k: "tipo", t: "Tipo", type: "select", options: list(["correctivo", "preventivo", "normativo", "mejora"]) },
          { k: "asignado_a", t: "Asignado a" }, { k: "proveedor", t: "Proveedor" }, { k: "coste_estimado", t: "Coste estimado €", type: "number" },
          { k: "fecha_prevista", t: "Fecha prevista", type: "date" }, { k: "descripcion", t: "Descripción", type: "textarea", wide: true },
        ], w, async (d) => { await put(`/api/mantenimiento/ordenes/${w.id}`, d); toast("OT actualizada"); load(); }), "proveedor")],
        can("mantenimiento.editar") && enTrabajo && ["Trabajo realizado", () => bindFotos(form(`OT ${w.id}: confirmar trabajo realizado`, [
          { k: "solucion", t: "Trabajo realizado / solución", type: "textarea", wide: true, req: true }, { k: "coste_real", t: "Coste real €", type: "number" },
          { html: fotosHtml("Fotos del trabajo terminado (opcional)") }],
          {}, async (d, f) => {
            const n = await subirFotos(f, w.id, "trabajo");
            const r = await post(`/api/mantenimiento/ordenes/${w.id}/confirmar-mantenimiento`, d);
            toast((r.requiere_limpieza ? "Trabajo confirmado. Pendiente de limpieza" : "Trabajo confirmado. Pendiente de cierre") + (n ? ` · ${n} foto(s)` : "")); load();
          }))],
        can("limpieza.confirmar_ot") && w.requiere_limpieza && w.conf_mto_por && !w.conf_limpieza_por && ["Unidad OK", () => run(() => post(`/api/mantenimiento/ordenes/${w.id}/confirmar-limpieza`), "Confirmado por limpieza. Pendiente de cierre").then(load)],
        (can("mantenimiento.cerrar") || (can("limpieza.confirmar_ot") && w.requiere_limpieza)) && w.conf_mto_por && ["Rechazar", () => form(`OT ${w.id}: devolver a mantenimiento`, [
          { k: "motivo", t: "Motivo (qué no está bien)", type: "textarea", wide: true, req: true }], {},
          async (d) => { await post(`/api/mantenimiento/ordenes/${w.id}/rechazar`, d); toast("Devuelta a mantenimiento"); load(); }), "danger"],
        can("mantenimiento.cerrar") && w.estado === "pendiente_cierre" && ["Cerrar OT", () => run(() => post(`/api/mantenimiento/ordenes/${w.id}/cerrar`, {}), "OT cerrada").then(load), "primary"],
        can("mantenimiento.cerrar") && ["Anular", () => form(`Anular OT ${w.id}`, [{ k: "motivo", t: "Motivo", type: "textarea", wide: true, req: true }], {},
          async (d) => { await post(`/api/mantenimiento/ordenes/${w.id}/cerrar`, { cancelar: true, motivo: d.motivo }); toast("OT anulada"); load(); }), "danger"],
      ];
    });
  };
  $("#e", el).onchange = load; $("#tp", el).onchange = load;
  if ($("#new", el)) $("#new", el).onclick = () => newWorkOrder().then(load);
  load();
};

V.preventivo = async (el) => {
  el.innerHTML = `<div class="toolbar"><span class="spacer"></span>${can("mantenimiento.editar") ? '<button class="btn" id="tpl">Cargar plantilla normativa</button><button class="btn" id="gen">Generar OT próximas</button><button class="btn primary" id="new">Nuevo plan</button>' : ""}</div>
    <p class="muted">La plantilla normativa es orientativa: revise periodicidades según potencia, uso y tipo de instalación de cada activo.</p><div id="t"></div>`;
  const fields = [
    { k: "titulo", t: "Título", req: true, wide: true }, { k: "categoria", t: "Instalación", type: "select", req: true, options: list(S.cat.categorias_mto) },
    { k: "normativa", t: "Normativa / referencia" }, { k: "periodicidad_dias", t: "Periodicidad (días)", type: "number", req: true },
    { k: "proxima_fecha", t: "Próxima fecha", type: "date", req: true }, { k: "proveedor", t: "Empresa mantenedora" },
    { k: "activo", t: "Plan activo", type: "checkbox", def: true },
  ];
  const load = async () => table($("#t", el), [
    { k: "asset_id", t: "Activo", f: (v) => esc(assetName(v)) }, { k: "titulo", t: "Plan" }, { k: "categoria", t: "Instalación" },
    { k: "normativa", t: "Normativa" }, { k: "periodicidad_dias", t: "Cada (días)", num: true },
    { k: "proxima_fecha", t: "Próxima", f: (v) => (v < today() ? `<b style="color:var(--bad)">${fdate(v)}</b>` : fdate(v)) },
    { k: "proveedor", t: "Mantenedor" }, { k: "activo", t: "Activo", f: (v) => (v ? "Sí" : "No") },
  ], await get("/api/mantenimiento/planes", { asset_id: S.asset }), (p) => can("mantenimiento.editar") ? [["Editar", () => sugerirProveedores(form(p.titulo, fields, p, async (d) => { await put(`/api/mantenimiento/planes/${p.id}`, d); toast("Plan guardado"); load(); }), "proveedor")]] : []);
  if ($("#new", el)) {
    $("#new", el).onclick = async () => { const aid = await pickAsset(); sugerirProveedores(form("Nuevo plan preventivo", fields, {}, async (d) => { await post("/api/mantenimiento/planes", clean({ ...d, asset_id: aid })); toast("Plan creado"); load(); }), "proveedor"); };
    $("#tpl", el).onclick = async () => { const aid = await pickAsset(); run(() => post("/api/mantenimiento/planes/plantilla", { asset_id: aid }), (r) => `${r.creados} planes cargados`).then(load); };
    $("#gen", el).onclick = () => form("Generar órdenes preventivas", [{ k: "dias_antelacion", t: "Días de antelación", type: "number", def: 7, req: true }], {},
      async (d) => { const r = await post("/api/mantenimiento/planes/generar", clean({ ...d, asset_id: S.asset ? Number(S.asset) : null })); toast(`${r.creadas} órdenes generadas`); load(); });
  }
  load();
};

// ---- personal de mantenimiento y limpieza: fichas con correo y teléfono; envío de las OT y del parte de limpieza
const AREAS = [["mantenimiento", "Mantenimiento"], ["limpieza", "Limpieza"]];
const puedeEnviarOT = () => can("mantenimiento.editar") || can("mantenimiento.cerrar");
const otNum = (id) => `OT-${String(id).padStart(5, "0")}`;
const personaTxt = (p) => `${p.nombre}${p.empresa ? ` (${p.empresa})` : ""}${p.email ? "" : " · sin correo"}${p.whatsapp ? "" : " · sin WhatsApp"}`;
const canalEnvio = (que) => ({ k: "canal", t: "Enviar por", type: "select", req: true, def: S.cat.correo ? "email" : "whatsapp",
  options: [["email", `Correo electrónico${que}`], ["whatsapp", "WhatsApp (se abre con el mensaje escrito)"]] });

function resultadoEnvio(titulo, res) {
  const wa = res.some((r) => r.whatsapp);
  form(titulo, [{ html: `${wa ? '<p class="muted">Pulse «Abrir WhatsApp» en cada persona y después «Enviar» en WhatsApp: hasta entonces el mensaje no sale.</p>' : ""}
    <ul class="envios">${res.map((r) => `<li><b>${esc(r.nombre)}</b> · ${esc(r.destino)} · ${r.whatsapp
      ? `<a class="btn sm primary" href="${esc(r.whatsapp)}" target="_blank" rel="noopener">Abrir WhatsApp</a>`
      : r.ok ? "correo enviado ✓" : `<span class="error">no enviado: ${esc(r.error || "error")}</span>`}</li>`).join("")}</ul>` }],
  {}, async () => {}, "Cerrar");
}

async function enviarOT(w, reload) {
  const gente = await get("/api/personal", { asset_id: w.asset_id, solo_activos: true });
  if (!gente.length) return toast("No hay personal dado de alta para este activo (Mantenimiento → Personal)", true);
  gente.sort((a, b) => (a.area !== "mantenimiento") - (b.area !== "mantenimiento"));
  const previos = [...new Set((w.envios || []).map((e) => e.nombre))];
  form(`Enviar ${otNum(w.id)} · ${w.titulo}`, [
    { k: "personal_ids", t: "Enviar a", type: "checks", options: gente.map((p) => [String(p.id), `${personaTxt(p)} · ${p.area_nombre}`]) },
    canalEnvio(" (con el parte en PDF y las fotos)"),
    { k: "nota", t: "Nota para el técnico (opcional)", type: "textarea", wide: true },
    previos.length && { html: `<p class="muted">Ya enviada a: ${esc(previos.join(", "))}</p>` },
  ].filter(Boolean), {}, async (d) => {
    if (!d.personal_ids.length) throw new Error("Elija al menos una persona");
    const r = await post(`/api/mantenimiento/ordenes/${w.id}/enviar`, { ...clean(d), personal_ids: d.personal_ids.map(Number) });
    reload && reload();
    resultadoEnvio(`${otNum(w.id)} enviada`, r.enviados);
  }, "Enviar");
}

async function parteLimpieza(fecha) {
  const aid = await pickAsset();
  const [p, gente] = await Promise.all([get("/api/personal/limpieza", { asset_id: aid, fecha }),
    get("/api/personal", { asset_id: aid, area: "limpieza", solo_activos: true })]);
  if (!gente.length) return toast("No hay personal de limpieza dado de alta para este activo (Mantenimiento → Personal)", true);
  if (!p.unidades.length) return toast(`No hay unidades pendientes de limpieza ni salidas el ${fdate(p.fecha)}`);
  form(`Parte de limpieza · ${assetName(aid)} · ${fdate(p.fecha)}`, [
    { html: '<p class="muted">Unidades pendientes de limpieza y salidas del día; primero las que tienen llegada. Para repartir el trabajo, marque las unidades de cada persona y envíe; repita con el resto.</p>' },
    { k: "unit_ids", t: `Unidades (${p.unidades.length})`, type: "checks", options: p.unidades.map((u) => [String(u.unit_id), `${u.codigo} · ${u.motivo}${u.llegada ? ` · LLEGADA (${u.pax_llegada} pax)` : ""}`]) },
    { k: "personal_ids", t: "Enviar a", type: "checks", options: gente.map((x) => [String(x.id), personaTxt(x)]) },
    canalEnvio(""),
    { k: "nota", t: "Nota (opcional)", type: "textarea", wide: true },
  ], { unit_ids: p.unidades.map((u) => String(u.unit_id)) }, async (d) => {
    if (!d.unit_ids.length) throw new Error("Elija al menos una unidad");
    if (!d.personal_ids.length) throw new Error("Elija al menos una persona");
    const r = await post("/api/personal/limpieza/enviar", { ...clean(d), asset_id: aid, fecha: p.fecha,
      unit_ids: d.unit_ids.map(Number), personal_ids: d.personal_ids.map(Number) });
    resultadoEnvio("Parte de limpieza enviado", r.enviados);
  }, "Enviar");
}

V.personal = async (el) => {
  const editar = (area) => can(area === "limpieza" ? "limpieza.editar" : "mantenimiento.editar");
  const areas = AREAS.filter(([a]) => editar(a));
  el.innerHTML = `<div class="toolbar"><select id="ar"><option value="">Mantenimiento y limpieza</option>${AREAS.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>
    <span class="spacer"></span>${can("limpieza.editar") ? '<button class="btn" id="pl">Enviar parte de limpieza</button>' : ""}${areas.length ? '<button class="btn primary" id="new">Nueva persona</button>' : ""}</div>
    <p class="muted">Técnicos y personal de limpieza, propios o de subcontratas, a los que se envían las órdenes de trabajo («Enviar» en cada OT) y el parte de limpieza por correo o WhatsApp. No necesitan usuario en INVERPMS.</p><div id="t"></div>`;
  const fields = [
    { k: "area", t: "Área", type: "select", req: true, options: areas },
    { k: "asset_id", t: "Activo (vacío = todos)", type: "select", options: opts(S.assets) },
    { k: "nombre", t: "Nombre", req: true }, { k: "empresa", t: "Empresa (si es subcontrata)" },
    { k: "email", t: "Correo electrónico", type: "email" }, { k: "telefono", t: "Móvil (WhatsApp)" },
    { k: "avisar_urgentes", t: "Recibir al momento por correo las OT urgentes (mantenimiento)", type: "checkbox", wide: true },
    { k: "activo", t: "En activo", type: "checkbox", def: true },
    { k: "notas", t: "Notas (horario, especialidad…)", type: "textarea", wide: true },
  ];
  const guardar = (p) => async (d) => {
    const body = { ...d, asset_id: d.asset_id ? Number(d.asset_id) : null };
    await (p ? put(`/api/personal/${p.id}`, body) : post("/api/personal", body));
    toast(p ? "Ficha guardada" : "Persona dada de alta"); load();
  };
  const load = async () => table($("#t", el), [
    { k: "area_nombre", t: "Área" }, { k: "nombre", t: "Nombre" }, { k: "empresa", t: "Empresa" },
    { k: "activo_nombre", t: "Activo" }, { k: "email", t: "Correo" }, { k: "telefono", t: "Móvil" },
    { k: "avisar_urgentes", t: "OT urgentes", f: (v) => (v ? "Al momento" : "") },
    { k: "activo", t: "Estado", f: (v) => (v ? "En activo" : '<span class="muted">Baja</span>') },
  ], await get("/api/personal", { asset_id: S.asset, area: $("#ar", el).value }), (p) => editar(p.area) ? [
    ["Editar", () => sugerirProveedores(form(p.nombre, fields, p, guardar(p)), "empresa")],
    ["Borrar", async () => { if (confirm(`¿Borrar la ficha de ${p.nombre}?`)) { await run(() => api("DELETE", `/api/personal/${p.id}`), "Ficha borrada"); load(); } }, "danger"],
  ] : []);
  $("#ar", el).onchange = load;
  if ($("#new", el)) $("#new", el).onclick = () => sugerirProveedores(form("Nueva persona", fields, { area: areas[0][0], asset_id: S.asset }, guardar(null)), "empresa");
  if ($("#pl", el)) $("#pl", el).onclick = () => parteLimpieza(today());
  load();
};

// ---- documentos recibidos (carpeta de cada activo) y cuenta de gastos
async function catGastos() { S.catGastos = S.catGastos || await get("/api/gastos/catalogos"); return S.catGastos; }
// Campos del gasto (en el alta de un documento y en el gasto sin documento)
function camposGasto(C, unidades) {
  return [
    { k: "categoria", t: "Categoría del gasto", type: "select", options: kv(C.categorias) },
    { k: "ambito", t: "Imputado a", type: "select", options: kv(C.ambitos), def: "general" },
    { k: "unit_id", t: "Apartamento", type: "select", options: unidades.map((u) => [u.id, `${u.codigo}${u.bloque ? " · " + u.bloque : ""}`]) },
    { k: "ambito_detalle", t: "Detalle (zona, varios apartamentos…)" },
    { k: "concepto", t: "Concepto del gasto", wide: true },
    { k: "total", t: "Importe total € (IVA incluido)", type: "number" },
    { k: "tipo_iva", t: "IVA %", type: "select", options: C.ivas.map((x) => [x, `${x} %`]), def: 21 },
    { k: "base", t: "Base € (solo si hay varios tipos de IVA)", type: "number" },
    { k: "forma_pago", t: "Forma de pago", type: "select", options: kv(C.formas_pago) },
    { k: "pagado", t: "Pagado", type: "checkbox" }, { k: "fecha_pago", t: "Fecha de pago", type: "date" },
  ];
}
const CAMPOS_GASTO = ["categoria", "ambito", "unit_id", "ambito_detalle", "concepto", "total", "tipo_iva", "base", "forma_pago", "pagado", "fecha_pago"];
function verCampos(f, nombres, ver) { nombres.forEach((n) => { const el = f.elements[n]; if (el) (el.closest("label") || el).style.display = ver ? "" : "none"; }); }
function bindAmbito(f) {
  const pinta = () => { const a = f.elements.ambito.value; verCampos(f, ["unit_id"], a === "apartamento"); verCampos(f, ["ambito_detalle"], a === "otro"); };
  f.elements.ambito.onchange = pinta; pinta();
}
function datosGasto(d, extra = {}) {
  if (!d.categoria) throw new Error("Elija la categoría del gasto");
  if (d.total == null) throw new Error("Indique el importe total del gasto");
  if (d.ambito === "apartamento" && !d.unit_id) throw new Error("Elija el apartamento del gasto");
  return clean({ categoria: d.categoria, ambito: d.ambito, unit_id: d.unit_id ? Number(d.unit_id) : null, ambito_detalle: d.ambito_detalle,
    concepto: d.concepto, total: d.total, tipo_iva: Number(d.tipo_iva ?? 21), base: d.base, forma_pago: d.forma_pago, pagado: !!d.pagado, fecha_pago: d.fecha_pago, ...extra });
}
async function unidadesActivo(aid) { return (await get("/api/unidades", { asset_id: aid })).filter((u) => u.uso !== "garaje"); }

async function subirDocumento(reload) {
  const aid = await pickAsset();
  const [C, unidades] = await Promise.all([catGastos(), unidadesActivo(aid)]);
  const f = form(`Subir documento recibido · ${assetName(aid)}`, [
    { k: "tipo", t: "Tipo de documento", type: "select", req: true, options: kv(C.tipos_documento), def: "factura" },
    { html: fotosHtml("Documento escaneado: PDF, o fotos de cada página (se unen en un PDF)", true) },
    { k: "fecha", t: "Fecha del documento", type: "date", req: true, def: today() },
    { k: "emisor", t: "Emisor / proveedor" }, { k: "referencia", t: "Nº de factura / referencia" },
    { k: "descripcion", t: "Descripción", type: "textarea", wide: true },
    { k: "es_gasto", t: "Es un gasto: anotarlo en la cuenta de gastos del activo", type: "checkbox", wide: true, def: true },
    ...camposGasto(C, unidades),
  ], {}, async (d, fr) => {
    const ficheros = ficherosElegidos(fr);
    if (!ficheros.length) throw new Error("Adjunte el documento escaneado (foto o PDF)");
    const fd = new FormData();
    ficheros.forEach((x) => fd.append("ficheros", x));
    fd.append("asset_id", aid); fd.append("tipo", d.tipo); fd.append("fecha", d.fecha);
    ["emisor", "referencia", "descripcion"].forEach((k) => d[k] && fd.append(k, d[k]));
    if (d.ambito === "apartamento" && d.unit_id) fd.append("unit_id", d.unit_id);
    if (d.es_gasto) fd.append("gasto", JSON.stringify(datosGasto(d, { fecha: d.fecha, concepto: d.concepto || d.descripcion || `${C.tipos_documento[d.tipo]} ${d.emisor || ""}`.trim(),
      proveedor: d.emisor, numero_factura: d.referencia })));
    const r = await upload("/api/documentos-recibidos", fd);
    toast(`Documento guardado en la carpeta de ${assetName(aid)}${r.gasto ? ` · gasto de ${eur(r.gasto.total)} anotado` : ""}`);
    reload && reload();
  }, "Guardar documento");
  bindFotos(f); bindAmbito(f); sugerirProveedores(f, "emisor");
  const gasto = () => { verCampos(f, CAMPOS_GASTO, f.elements.es_gasto.checked); if (f.elements.es_gasto.checked) bindAmbito(f); };
  f.elements.es_gasto.onchange = gasto;
  f.elements.tipo.onchange = () => { f.elements.es_gasto.checked = ["factura", "ticket", "albaran"].includes(f.elements.tipo.value); gasto(); };
  gasto();
}

async function editarGasto(g, reload, aidNuevo) {
  const aid = g ? g.asset_id : aidNuevo || await pickAsset();
  const [C, unidades] = await Promise.all([catGastos(), unidadesActivo(aid)]);
  const f = form(g ? `Gasto · ${g.concepto}` : `Nuevo gasto sin documento · ${assetName(aid)}`, [
    { k: "fecha", t: "Fecha", type: "date", req: true, def: today() },
    { k: "proveedor", t: "Proveedor" }, { k: "numero_factura", t: "Nº de factura" },
    ...camposGasto(C, unidades), { k: "notas", t: "Notas", type: "textarea", wide: true },
  ], g ? { ...g, base: null } : {}, async (d) => {
    const body = datosGasto(d, { fecha: d.fecha, concepto: d.concepto, proveedor: d.proveedor, numero_factura: d.numero_factura, notas: d.notas });
    if (!body.concepto) throw new Error("Indique el concepto del gasto");
    await (g ? put(`/api/gastos/${g.id}`, body) : post("/api/gastos", { ...body, asset_id: aid }));
    toast(g ? "Gasto actualizado" : "Gasto anotado"); reload && reload();
  });
  bindAmbito(f); sugerirProveedores(f, "proveedor");
}

V.docrecibidos = async (el) => {
  const C = await catGastos();
  const editar = can("documentos.editar");
  const ini = `${today().slice(0, 4)}-01-01`;
  el.innerHTML = `<div class="toolbar"><select id="tp"><option value="">Todos los tipos</option>${Object.entries(C.tipos_documento).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select>
    <label>Desde<input type="date" id="d" value="${ini}"></label><label>Hasta<input type="date" id="h" value="${today()}"></label>
    <input id="q" placeholder="Emisor, referencia, descripción"><span class="spacer"></span>${editar ? '<button class="btn primary" id="new">Subir documento</button>' : ""}</div>
    <p class="muted">Carpeta de documentos recibidos del activo (facturas, tickets, cartas, notificaciones…), guardados cifrados. Cada activo ve solo los suyos.</p><div id="t"></div>`;
  const load = async () => {
    const docs = await get("/api/documentos-recibidos", { asset_id: S.asset, tipo: $("#tp", el).value, desde: $("#d", el).value, hasta: $("#h", el).value, q: $("#q", el).value });
    table($("#t", el), [
      { k: "fecha", t: "Fecha", f: fdate }, { k: "activo", t: "Activo" }, { k: "tipo_nombre", t: "Tipo" }, { k: "emisor", t: "Emisor" },
      { k: "referencia", t: "Referencia" }, { k: "descripcion", t: "Descripción" }, { k: "unidad", t: "Apartamento" },
      { k: "gasto", t: "Gasto", f: (v) => (v ? `${eur(v.total)} <span class="muted">${esc(v.categoria_nombre)}${v.pagado ? " · pagado" : " · pendiente"}</span>` : '<span class="muted">—</span>') },
      { k: "usuario", t: "Subido por", f: (v, x) => `${esc(v || "")}<div class="muted peq">${fdt(x.subido)}</div>` },
    ], docs, (x) => [
      ["Ver", () => abrirFichero(`/api/documentos-recibidos/${x.id}/fichero`)],
      editar && !x.gasto && ["Anotar gasto", async () => {
        const [C2, unidades] = await Promise.all([catGastos(), unidadesActivo(x.asset_id)]);
        const f = form(`Gasto del documento · ${x.tipo_nombre} ${x.emisor || ""}`, [{ k: "fecha", t: "Fecha", type: "date", req: true }, ...camposGasto(C2, unidades)],
          { fecha: x.fecha, concepto: x.descripcion || `${x.tipo_nombre} ${x.emisor || ""}`.trim(), unit_id: x.unit_id, ambito: x.unit_id ? "apartamento" : "general" },
          async (d) => { await post("/api/gastos", datosGasto(d, { fecha: d.fecha, concepto: d.concepto, documento_id: x.id, proveedor: x.emisor, numero_factura: x.referencia })); toast("Gasto anotado"); load(); });
        bindAmbito(f);
      }],
      x.gasto && editar && ["Gasto", () => editarGasto(x.gasto, load)],
      editar && ["Borrar", async () => { if (confirm(`¿Borrar el documento «${x.nombre}»? El apunte del gasto, si lo tiene, se conserva.`)) { await run(() => api("DELETE", `/api/documentos-recibidos/${x.id}`), "Documento borrado"); load(); } }, "danger"],
    ]);
  };
  ["#tp", "#d", "#h"].forEach((s) => ($(s, el).onchange = load)); $("#q", el).oninput = debounce(load);
  if ($("#new", el)) $("#new", el).onclick = () => subirDocumento(load);
  load();
};

V.gastos = async (el) => {
  const C = await catGastos();
  const editar = can("documentos.editar");
  const ini = `${today().slice(0, 4)}-01-01`;
  el.innerHTML = `<div class="toolbar"><label>Desde<input type="date" id="d" value="${ini}"></label><label>Hasta<input type="date" id="h" value="${today()}"></label>
    <select id="c"><option value="">Todas las categorías</option>${Object.entries(C.categorias).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select>
    <select id="p"><option value="">Pagados y pendientes</option><option value="false">Pendientes de pago</option><option value="true">Pagados</option></select>
    <span class="spacer"></span><button class="btn" id="xls">Excel</button>${editar ? '<button class="btn" id="sin">Gasto sin documento</button><button class="btn primary" id="doc">Subir factura / ticket</button>' : ""}</div>
    <div class="kpis" id="k"></div><div id="t"></div>`;
  const filtros = () => ({ asset_id: S.asset, desde: $("#d", el).value, hasta: $("#h", el).value, categoria: $("#c", el).value, pagado: $("#p", el).value });
  const load = async () => {
    const r = await get("/api/gastos", filtros());
    const t = r.totales;
    $("#k", el).innerHTML = [[eur(t.base), "Gasto (base sin IVA)"], [eur(t.cuota), "IVA soportado"], [eur(t.total), "Total con IVA"],
      [eur(t.pendiente_pago), "Pendiente de pago", t.pendiente_pago > 0 ? "mal" : ""], [t.sin_documento, "Apuntes sin documento", t.sin_documento ? "mal" : ""],
      ...Object.entries(t.por_categoria).slice(0, 4).map(([c, v]) => [eur(v), c])]
      .map(([v, l, cls]) => `<div class="kpi ${cls || ""}"><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join("");
    table($("#t", el), [
      { k: "fecha", t: "Fecha", f: fdate }, { k: "activo", t: "Activo" }, { k: "lugar", t: "Imputado a" }, { k: "categoria_nombre", t: "Categoría" },
      { k: "concepto", t: "Concepto" }, { k: "proveedor", t: "Proveedor", f: (v, g) => `${esc(v || "")}${g.numero_factura ? `<div class="muted peq">${esc(g.numero_factura)}</div>` : ""}` },
      { k: "base", t: "Base", num: true, f: eur }, { k: "cuota", t: "IVA", num: true, f: (v, g) => `${eur(v)}<div class="muted peq">${g.tipo_iva} %</div>` },
      { k: "total", t: "Total", num: true, f: eur },
      { k: "pagado", t: "Pago", f: (v, g) => (v ? `<span class="badge b-vigente">pagado</span><div class="muted peq">${fdate(g.fecha_pago)}</div>` : '<span class="badge b-pendiente">pendiente</span>') },
      { k: "documento_tipo", t: "Documento", f: (v) => (v ? esc(v) : '<span class="badge b-cancelada">sin documento</span>') },
    ], r.gastos, (g) => [
      g.documento_id && ["Ver", () => abrirFichero(`/api/documentos-recibidos/${g.documento_id}/fichero`)],
      editar && !g.pagado && ["Pagado", () => run(() => put(`/api/gastos/${g.id}`, { ...g, pagado: true, fecha_pago: today(), base: null }), "Marcado como pagado").then(load)],
      editar && ["Editar", () => editarGasto(g, load)],
      editar && ["Borrar", async () => { if (confirm(`¿Borrar el gasto «${g.concepto}»?`)) { await run(() => api("DELETE", `/api/gastos/${g.id}`), "Gasto borrado"); load(); } }, "danger"],
    ]);
  };
  ["#d", "#h", "#c", "#p"].forEach((s) => ($(s, el).onchange = load));
  $("#xls", el).onclick = () => run(() => download("GET", `/api/gastos/excel?${new URLSearchParams(Object.entries(filtros()).filter(([k, v]) => v && k !== "pagado"))}`));
  if ($("#sin", el)) { $("#sin", el).onclick = () => editarGasto(null, load); $("#doc", el).onclick = () => subirDocumento(load); }
  load();
};

// ---- administración
V.usuarios = async (el) => {
  const [users, roles] = await Promise.all([get("/api/admin/usuarios"), get("/api/admin/roles")]);
  el.innerHTML = `<div class="toolbar"><span class="spacer"></span><button class="btn primary" id="new">Nuevo usuario</button></div><div id="t"></div>`;
  const scopeTxt = (a) => a.asset_id ? `Activo: ${assetName(a.asset_id)}` : a.company_id ? `Sociedad: ${S.companies.find((c) => c.id === a.company_id)?.nombre}` : "Todo el grupo";
  const assignRow = (a = {}) => `<div class="assign-row">
      <select data-f="role_id">${roles.map((r) => `<option value="${r.id}" ${r.id === a.role_id ? "selected" : ""}>${esc(r.nombre)}</option>`).join("")}</select>
      <select data-f="company_id"><option value="">Todo el grupo</option>${S.companies.map((c) => `<option value="${c.id}" ${c.id === a.company_id ? "selected" : ""}>${esc(c.nombre)}</option>`).join("")}</select>
      <select data-f="asset_id"><option value="">Todos sus activos</option>${S.assets.map((x) => `<option value="${x.id}" ${x.id === a.asset_id ? "selected" : ""}>${esc(x.nombre)}</option>`).join("")}</select>
      <button type="button" class="btn sm danger" data-del>✕</button></div>`;
  const edit = (u) => {
    const f = form(u ? `Usuario: ${u.nombre}` : "Nuevo usuario", [
      { k: "email", t: "Email (usuario de acceso)", type: "email", req: true }, { k: "nombre", t: "Nombre", req: true },
      { k: "password", t: u ? "Restablecer contraseña provisional (opcional)" : "Contraseña provisional (mín. 8)", type: "password", req: !u },
      { k: "activo", t: "Usuario activo", type: "checkbox", def: true },
      ...(S.me.is_superadmin ? [{ k: "is_superadmin", t: "Superadministrador (acceso total)", type: "checkbox" }] : []),
      { html: `<fieldset><legend>Roles y ámbito de acceso (rol · sociedad · activo)</legend><div id="asg">${(u?.asignaciones || []).map(assignRow).join("")}</div>
        <button type="button" class="btn sm" id="addA">+ Añadir rol</button></fieldset>` },
    ], u || {}, async (d) => {
      const asignaciones = [...f.querySelectorAll(".assign-row")].map((row) => {
        const v = (k) => row.querySelector(`[data-f=${k}]`).value;
        return { role_id: Number(v("role_id")), company_id: v("company_id") ? Number(v("company_id")) : null, asset_id: v("asset_id") ? Number(v("asset_id")) : null };
      });
      const body = { ...d, asignaciones }; if (!body.password) delete body.password;
      if (u) await put(`/api/admin/usuarios/${u.id}`, body); else await post("/api/admin/usuarios", body);
      toast("Usuario guardado"); go("usuarios");
    });
    const bindDel = () => f.querySelectorAll("[data-del]").forEach((b) => (b.onclick = () => b.parentElement.remove()));
    $("#addA", f).onclick = () => { $("#asg", f).insertAdjacentHTML("beforeend", assignRow()); bindDel(); };
    bindDel();
  };
  $("#new", el).onclick = () => edit(null);
  table($("#t", el), [
    { k: "nombre", t: "Nombre", f: (v) => `<span class="persona">${avatar(v, "sm")}${esc(v)}</span>` }, { k: "email", t: "Email" },
    { k: "asignaciones", t: "Roles / ámbito", f: (v, u) => u.is_superadmin ? "<b>Superadministrador</b>" : v.map((a) => `${esc(a.rol)} <span class="muted">(${esc(scopeTxt(a))})</span>`).join("<br>") || '<span class="muted">Sin acceso</span>' },
    { k: "activo", t: "Estado", f: (v, u) => (v ? badge("vigente") : badge("baja")) + (u.debe_cambiar_password ? ' <span class="badge b-pendiente">contraseña provisional</span>' : "") },
  ], users, (u) => [["Editar", () => edit(u)]]);
};

V.roles = async (el) => {
  const roles = await get("/api/admin/roles");
  el.innerHTML = `<div class="toolbar"><span class="muted">Los permisos se aplican dentro del ámbito asignado a cada usuario (grupo, sociedad o activo).</span><span class="spacer"></span><button class="btn primary" id="new">Nuevo rol</button></div><div id="t"></div>`;
  const edit = (r) => {
    const f = form(r ? `Rol: ${r.nombre}` : "Nuevo rol", [{ k: "nombre", t: "Nombre", req: true }, { k: "descripcion", t: "Descripción", wide: true },
      { html: `<fieldset><legend>Permisos</legend><div class="perm-grid">${Object.entries(S.cat.permisos).map(([k, d]) => `<label class="check"><input type="checkbox" data-p="${k}" ${r?.permisos.includes(k) ? "checked" : ""}> ${esc(d)}</label>`).join("")}</div></fieldset>` }],
      r || {}, async (d) => {
        const body = { ...d, permisos: [...f.querySelectorAll("[data-p]:checked")].map((c) => c.dataset.p) };
        if (r) await put(`/api/admin/roles/${r.id}`, body); else await post("/api/admin/roles", body);
        toast("Rol guardado"); go("roles");
      });
  };
  $("#new", el).onclick = () => edit(null);
  table($("#t", el), [{ k: "nombre", t: "Rol" }, { k: "descripcion", t: "Descripción" }, { k: "permisos", t: "Permisos", f: (v) => `${v.length} / ${Object.keys(S.cat.permisos).length}` }], roles, (r) => [["Editar", () => edit(r)]]);
};

V.sociedades = async (el) => {
  el.innerHTML = `<div class="toolbar"><span class="spacer"></span><button class="btn primary" id="new">Nueva sociedad</button></div><div id="t"></div>`;
  const fields = [{ k: "nombre", t: "Razón social", req: true }, { k: "cif", t: "CIF" },
    { k: "parent_id", t: "Sociedad matriz", type: "select", options: opts(S.companies) }, { k: "activa", t: "Activa", type: "checkbox", def: true },
    { html: "<h4>Domicilio fiscal</h4><p class='muted'>Obligatorio para emitir facturas. Se imprime en todas las facturas de la sociedad.</p>" },
    { k: "direccion", t: "Dirección", wide: true }, { k: "cp", t: "C.P." }, { k: "municipio", t: "Municipio" }, { k: "provincia", t: "Provincia" }];
  const save = (c) => form(c ? c.nombre : "Nueva sociedad", fields, c || {}, async (d) => {
    d.parent_id = d.parent_id ? Number(d.parent_id) : null;
    if (c) await put(`/api/sociedades/${c.id}`, d); else await post("/api/sociedades", d);
    toast("Sociedad guardada"); await loadCompanies(); go("sociedades");
  });
  $("#new", el).onclick = () => save(null);
  table($("#t", el), [{ k: "logo", t: "", f: (v, c) => (v ? `<img class="logo-tabla" src="${claro(v)}" alt="">` : avatar(c.nombre, "sm")) },
    { k: "nombre", t: "Razón social" }, { k: "cif", t: "CIF" },
    { k: "direccion", t: "Domicilio fiscal", f: (v, c) => v ? esc([v, c.cp, c.municipio].filter(Boolean).join(", ")) : '<span class="badge b-pendiente">falta (no puede facturar)</span>' },
    { k: "parent_id", t: "Matriz", f: (v) => esc(S.companies.find((c) => c.id === v)?.nombre ?? "") },
    { k: "activa", t: "Estado", f: (v) => (v ? badge("vigente") : badge("baja")) }], S.companies, (c) => [["Editar", () => save(c)]]);
};

V.avisos = async (el) => {
  const st = await get("/api/admin/avisos");
  el.innerHTML = `<div class="card" style="max-width:820px"><h3>Envío de correos</h3>
    ${st.configurado ? `<p>Servidor <b>${esc(st.servidor)}</b> · remitente <b>${esc(st.remitente || "")}</b> · resumen diario a las <b>${esc(st.hora_resumen)}</b> (hora de Madrid).</p>`
      : '<p class="error">No configurado. Hay que indicar el servidor de correo en el fichero .env del servidor (ver deploy/INSTALACION.md, apartado «Avisos por correo»).</p>'}
    <p class="muted">OT urgentes: al momento, a quien ve el mantenimiento del activo. Resumen diario: recibos impagados, contratos que vencen en 90 días y revisiones preventivas/normativas en 30 días o vencidas; solo a quien tenga algo pendiente en sus activos. Cada usuario elige sus avisos en «Mi perfil».</p>
    <div class="toolbar"><button class="btn" id="probar">Enviarme un correo de prueba</button><button class="btn" id="resumen">Enviar el resumen diario ahora</button></div></div>
    <h4>Últimos envíos</h4><div id="t"></div>`;
  $("#probar", el).onclick = () => run(() => post("/api/admin/avisos/probar", {}), (r) => `Correo de prueba enviado a ${r.destino}`).then(() => go("avisos"));
  $("#resumen", el).onclick = () => confirm("¿Enviar ahora el resumen a todos los usuarios con avisos pendientes?") && run(() => post("/api/admin/avisos/resumen"), (r) => `Resumen enviado a ${r.enviados} usuario(s)` + (r.errores ? `, ${r.errores} error(es)` : "")).then(() => go("avisos"));
  table($("#t", el), [{ k: "fecha", t: "Fecha", f: fdt }, { k: "tipo", t: "Tipo", f: (v) => esc(label(v)) }, { k: "usuario", t: "Usuario" }, { k: "destinatario", t: "Correo" },
    { k: "asunto", t: "Asunto" }, { k: "ok", t: "Estado", f: (v, r) => (v ? '<span class="badge b-vigente">enviado</span>' : `<span class="badge b-cancelada" title="${esc(r.error)}">error</span> <span class="muted">${esc((r.error || "").slice(0, 60))}</span>`) }], st.registro);
};

V.auditoria = async (el) => {
  table(el, [{ k: "fecha", t: "Fecha", f: fdt }, { k: "usuario", t: "Usuario" }, { k: "accion", t: "Acción" }, { k: "entidad", t: "Entidad" },
    { k: "entidad_id", t: "ID" }, { k: "detalle", t: "Detalle", f: (v) => `<code>${esc(v ? JSON.stringify(v).slice(0, 140) : "")}</code>` }],
    await get("/api/admin/auditoria"));
};

V.perfil = async (el) => {
  el.innerHTML = `<div class="card" style="max-width:640px"><div class="perfil-cab">${avatar(S.me.nombre, "lg")}<div><h3>${esc(S.me.nombre)}</h3><div class="sub">${esc(S.me.email)} · ${esc(rolDe(S.me))}</div></div></div>
    <h4>Accesos</h4>${S.me.is_superadmin ? "<p><b>Superadministrador</b> — acceso total</p>" : S.me.ambitos.map((a) => `<p>${esc(a.rol)} · <span class="muted">${esc(a.ambito)}</span></p>`).join("") || "<p class='muted'>Sin roles asignados</p>"}
    <button class="btn" id="pw">Cambiar contraseña</button>
    <h4>Avisos por correo</h4><div id="avisos"><p class="muted">Cargando…</p></div></div>`;
  const av = await get("/api/auth/avisos");
  $("#avisos", el).innerHTML = (av.correo_configurado ? "" : '<p class="muted">El envío de correos aún no está configurado en el servidor: puede dejar elegidos sus avisos y empezarán a llegar cuando se configure.</p>') +
    (av.tipos.length ? `<p class="muted">Se envían a ${esc(av.email)}, solo de los activos a los que tiene acceso.</p>${av.tipos.map((t) => `<label class="check"><input type="checkbox" data-av="${t.tipo}" ${t.activo ? "checked" : ""}> ${esc(t.descripcion)}</label>`).join("")}
      <p><button class="btn" id="avSave">Guardar avisos</button></p>` : '<p class="muted">Su perfil no tiene avisos disponibles.</p>');
  if ($("#avSave", el)) $("#avSave", el).onclick = () => run(() => put("/api/auth/avisos", { avisos: [...el.querySelectorAll("[data-av]:checked")].map((c) => c.dataset.av) }), "Avisos guardados");
  $("#pw", el).onclick = () => form("Cambiar contraseña", [{ k: "actual", t: "Contraseña actual", type: "password", req: true }, { k: "nueva", t: "Nueva (mín. 10 caracteres)", type: "password", req: true }], {},
    async (d) => { await post("/api/auth/password", d); toast("Contraseña cambiada"); });
};

// ------------------------------------------------------------------ navegación
const MENU = [
  ["General", [["panel", "Panel de control", null], ["activos", "Activos", "activos.ver"], ["unidades", "Unidades", "activos.ver"]]],
  ["Apartamentos turísticos", [["plano", "Plano de apartamentos", "activos.ver"], ["hoy", "Llegadas / salidas", "reservas.ver"], ["reservas", "Reservas", "reservas.ver"], ["planning", "Planning", "reservas.ver"], ["huespedes", "Huéspedes", "reservas.ver"], ["ses", "Parte de viajeros (SES)", "reservas.ver"], ["garajes", "Alquiler de garajes", "reservas.ver"]]],
  ["Alquiler residencial", [["contratos", "Contratos", "alquiler.ver"], ["recibos", "Recibos y cobros", "alquiler.ver"], ["inquilinos", "Inquilinos", "alquiler.ver"]]],
  ["Facturación e informes", [["facturas", "Facturas emitidas", "facturas.ver"], ["servicios", "Servicios", "activos.ver"], ["informes", "Informes Excel", "informes"]]],
  ["Documentos y gastos", [["docrecibidos", "Documentos recibidos", "documentos.ver"], ["gastos", "Cuenta de gastos", "documentos.ver"]]],
  ["Mantenimiento", [["ordenes", "Órdenes de trabajo", "mantenimiento.ver"], ["preventivo", "Plan preventivo", "mantenimiento.ver"], ["personal", "Personal mto. y limpieza", "personal"], ["proveedores", "Proveedores", "mantenimiento.ver"]]],
  ["Administración", [["usuarios", "Usuarios", "admin"], ["roles", "Roles y permisos", "admin"], ["sociedades", "Sociedades", "admin"], ["avisos", "Avisos por correo", "admin"], ["auditoria", "Auditoría", "auditoria.ver"]]],
  ["", [["perfil", "Mi perfil", null]]],
];
const allowed = (p) => !p || (p === "admin" ? S.me.admin_grupo : p === "informes" ? ["reservas.ver", "alquiler.ver", "finanzas.ver", "mantenimiento.ver"].some(can)
  : p === "personal" ? ["mantenimiento.ver", "limpieza.editar", "limpieza.confirmar_ot"].some(can) : can(p));
const TITLES = Object.fromEntries(MENU.flatMap(([, items]) => items.map(([id, t]) => [id, t])));

function renderNav() {
  $("#nav").innerHTML = MENU.map(([g, items]) => {
    const vis = items.filter(([, , p]) => allowed(p));
    return vis.length ? `${g ? `<div class="group">${g}</div>` : "<br>"}${vis.map(([id, t]) => `<a href="#${id}" data-v="${id}">${t}</a>`).join("")}` : "";
  }).join("");
}
async function go(view) {
  view = TITLES[view] && allowed(MENU.flatMap(([, i]) => i).find(([id]) => id === view)[2]) ? view : "panel";
  if (location.hash !== "#" + view) history.replaceState(null, "", "#" + view);
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.v === view));
  $(".sidebar").classList.remove("open");
  $("#viewTitle").textContent = TITLES[view];
  // contenedor nuevo por navegación: una carga anterior aún en curso escribe en uno ya desmontado
  const el = document.createElement("div"); $("#view").replaceChildren(el); el.innerHTML = '<p class="muted">Cargando…</p>';
  try { await V[view](el); } catch (e) { el.innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}
function setAsset(id) { S.plano = null; S.asset = id ? String(id) : ""; $("#assetFilter").value = S.asset; localStorage.setItem("pms_asset", S.asset); }
function debounce(fn, ms = 300) { let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); }; }

async function loadAssets() {
  S.assets = await get("/api/activos");
  $("#assetFilter").innerHTML = `<option value="">Todos los activos</option>` + S.assets.map((a) => `<option value="${a.id}">${esc(a.nombre)}</option>`).join("");
  if (!S.assets.some((a) => String(a.id) === S.asset)) S.asset = "";
  $("#assetFilter").value = S.asset;
}
async function loadCompanies() { S.companies = await get("/api/sociedades"); }

function forcePasswordChange() {
  $("#login").classList.add("hidden"); $("#app").classList.remove("hidden");
  pintarUsuario(); $("#nav").innerHTML = ""; $("#view").innerHTML = ""; $("#assetFilter").hidden = true;
  $("#viewTitle").textContent = "Cambio de contraseña obligatorio";
  const f = form("Primer acceso: cambie su contraseña provisional", [
    { html: '<p class="muted">Mínimo 10 caracteres. No puede ser la contraseña provisional.</p>' },
    { k: "actual", t: "Contraseña provisional", type: "password", req: true },
    { k: "nueva", t: "Nueva contraseña", type: "password", req: true },
    { k: "repite", t: "Repita la nueva contraseña", type: "password", req: true },
  ], {}, async (d) => {
    if (d.nueva !== d.repite) throw new Error("Las contraseñas no coinciden");
    await post("/api/auth/password", { actual: d.actual, nueva: d.nueva });
    toast("Contraseña actualizada"); setTimeout(start, 0);
  }, "Cambiar contraseña");
  $("#fCancel", f).textContent = "Salir"; $("#fCancel", f).onclick = () => { $("#modal").close(); logout(); };
  $("#modal").oncancel = (e) => e.preventDefault();  // no se puede cerrar con Esc
}

async function start() {
  try { S.me = await get("/api/auth/me"); } catch { return showLogin(); }
  if (S.me.debe_cambiar_password) return forcePasswordChange();
  $("#modal").oncancel = null; $("#assetFilter").hidden = false;
  S.cat = await get("/api/catalogos");
  S.asset = localStorage.getItem("pms_asset") || "";
  await Promise.all([loadAssets(), loadCompanies()]);
  $("#login").classList.add("hidden"); $("#app").classList.remove("hidden");
  pintarUsuario();
  renderNav();
  go(location.hash.slice(1) || "panel");
}
function pintarUsuario() {
  $("#userAvatar").textContent = iniciales(S.me.nombre); $("#userAvatar").title = S.me.nombre;
  $("#userName").innerHTML = `${esc(S.me.nombre)}<small>${esc(rolDe(S.me))}</small>`;
}
function showLogin() { $("#app").classList.add("hidden"); $("#login").classList.remove("hidden"); }
function logout() { S.token = null; localStorage.removeItem("pms_token"); showLogin(); }

$("#loginForm").onsubmit = async (e) => {
  e.preventDefault();
  const d = Object.fromEntries(new FormData(e.target));
  try { S.token = (await post("/api/auth/login", d)).token; localStorage.setItem("pms_token", S.token); $("#loginError").textContent = ""; start(); }
  catch (err) { $("#loginError").textContent = err.message; }
};
$("#logoutBtn").onclick = logout;
$("#menuBtn").onclick = () => $(".sidebar").classList.toggle("open");
$("#assetFilter").onchange = (e) => { setAsset(e.target.value); go(location.hash.slice(1)); };
window.onhashchange = () => S.me && go(location.hash.slice(1));
S.token ? start() : showLogin();
