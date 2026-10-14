/* INVERPMS — Grupo INVERSIETE · interfaz web (SPA sin dependencias) */
const S = { token: localStorage.getItem("pms_token"), me: null, cat: null, assets: [], companies: [], asset: "" };
const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const eur = (n) => (n == null ? "" : Number(n).toLocaleString("es-ES", { style: "currency", currency: "EUR" }));
const fdate = (d) => (d ? new Date(d.length === 10 ? d + "T00:00:00" : d).toLocaleDateString("es-ES") : "");
const fdt = (d) => (d ? new Date(d).toLocaleString("es-ES") : "");
// Fechas en la hora local del ordenador (Madrid), nunca en UTC: con toISOString(), entre las 00:00 y las 02:00 el
// programa proponía el día anterior y «día siguiente» podía salir el mismo día.
const iso = (dt) => `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
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
const canOpenOT = () => can("mantenimiento.abrir");  // mantenimiento y limpieza avisan con un parte de estado
const canParteEstado = () => can("partes_estado.crear");
const irParteEstado = (aid, uid, zona) => go(`estado?a=${aid}${uid ? `&u=${uid}` : ""}${zona != null ? `&z=${encodeURIComponent(zona)}` : ""}`);
const assetsOf = (mod) => S.assets.filter((a) => !mod || a.modalidad === mod);

// ------------------------------------------------------------------ API
async function api(method, path, body, reintento = true) {
  const res = await fetch(path, {
    method, headers: { "Content-Type": "application/json", ...(S.token ? { Authorization: `Bearer ${S.token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 401 && S.token) { logout(); throw new Error("Sesión caducada"); }
  // Servidor ocupado (503): las consultas se reintentan solas una vez a los 3 s
  if (res.status === 503 && method === "GET" && reintento) { await new Promise((r) => setTimeout(r, 3000)); return api(method, path, body, false); }
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
  const head = cols.map((c) => `<th class="${c.num ? "num" : ""}">${esc(c.t)}</th>`).join("") + (actions ? '<th class="acc"></th>' : "");
  const acts = rows.map((r) => (actions ? actions(r).filter(Boolean) : []));
  const body = rows.map((r, i) => "<tr>" + cols.map((c) => `<td class="${c.num ? "num" : ""}">${c.f ? c.f(r[c.k], r) : esc(r[c.k])}</td>`).join("") +
    (actions ? `<td class="acc">${acts[i].map(([l, , cls], j) => `<button class="btn sm ${cls || ""}" data-r="${i}" data-a="${j}">${esc(l)}</button>`).join(" ")}</td>` : "") + "</tr>").join("");
  el.innerHTML = `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>
    <p class="muted">${rows.length} registro(s)</p>`;
  el.querySelectorAll("button[data-r]").forEach((b) => (b.onclick = () => acts[b.dataset.r][b.dataset.a][1](rows[b.dataset.r])));
}

// Pantallas de un vistazo: cada lista ocupa como mucho lo que queda de pantalla y se desplaza por dentro
// (cabecera fija), así la página no crece hacia abajo y los botones quedan a mano.
function encajarTablas() {
  const vista = document.getElementById("view");
  if (!vista) return;
  vista.querySelectorAll(".table-wrap").forEach((w) => {
    if (w.closest("dialog") || w.closest(".no-encajar")) return;
    const top = w.getBoundingClientRect().top + window.scrollY;
    const pie = w.nextElementSibling?.matches("p.muted") ? 30 : 12;
    w.style.maxHeight = `${Math.max(260, window.innerHeight - top - pie - 14)}px`;
  });
}
let _encajeT;
const encajeDiferido = () => { clearTimeout(_encajeT); _encajeT = setTimeout(encajarTablas, 60); };
window.addEventListener("resize", encajeDiferido);
{
  const observar = () => { const v = document.getElementById("view"); if (v) new MutationObserver(encajeDiferido).observe(v, { childList: true, subtree: true }); };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", observar); else observar();
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
  f.innerHTML = `<h3>${esc(title)}</h3><div class="grid">${fields.map((fd) => "html" in fd ? (fd.html ? `<div class="wide">${fd.html}</div>` : "") :
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
      if (!fd.k || "html" in fd) continue;
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
  // Código postal español: rellena solo la población y la provincia (y el país, si está vacío). Solo cambia lo
  // que está vacío o lo que puso él mismo antes; lo escrito a mano se respeta.
  campos(/^(cliente_)?cp$/).forEach((cp) => {
    const campo = (k) => f.elements[cp.name.replace(/cp$/, k)];
    const poner = (el, v) => { if (el && v && (!el.value.trim() || el.dataset.auto === "1")) { el.value = v; el.dataset.auto = "1"; } };
    ["municipio", "provincia", "pais"].forEach((k) => campo(k)?.addEventListener("input", (e) => { if (e.isTrusted) delete e.target.dataset.auto; }));
    const buscar = async () => {
      const v = cp.value.trim(), pais = campo("pais");
      if (!/^\d{5}$/.test(v) || (pais && pais.value.trim() && !/^espa/i.test(pais.value.trim()))) return;
      const r = await get(`/api/codigos-postales/${v}`).catch(() => null);
      if (!r || cp.value.trim() !== v) return;
      const mun = campo("municipio"), dl = mun?.list;
      if (r.municipios.length === 1) poner(mun, r.municipios[0].nombre);
      else if (mun) {
        if (mun.dataset.auto === "1") { mun.value = ""; delete mun.dataset.auto; }
        if (dl) dl.innerHTML = r.municipios.map((m) => `<option value="${esc(m.nombre)}">`).join("");
        if (r.municipios.length) mun.placeholder = `C.P. compartido: ${r.municipios.map((m) => m.nombre).join(", ")}`;
      }
      const elegido = r.municipios.find((m) => m.nombre === mun?.value);
      poner(campo("provincia"), elegido ? elegido.provincia : r.provincia);
      poner(pais, "España");
    };
    cp.addEventListener("input", debounce(buscar, 300));
    cp.addEventListener("change", buscar);
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
  if (!p.activos.length) {  // sin activos asignados: solo su agenda
    el.innerHTML = `<section class="panel-agenda"><h3>📅 Agenda</h3><div id="agp"></div></section>`;
    return agendaWidget($("#agp", el));
  }
  // Diseño: a la izquierda (lo que se trabaja) el plano por plantas arriba y la situación de cada activo;
  // a la derecha, estrecho, la agenda y los avisos. Todo cabe en la pantalla sin bajar.
  const varios = S.assets.length > 1 && !S.asset;
  const conMapa = new Set(conPlano.map((a) => a.id));
  S.conPlano = conMapa;
  const planos = conPlano.filter((a) => !S.asset || String(a.id) === String(S.asset));
  let elegido = null;
  try { elegido = localStorage.getItem("pms_panel_plano"); } catch {}
  const plano = planos.find((a) => String(a.id) === elegido) || planos[0];
  const visibles = p.activos.filter((a) => !S.asset || String(a.id) === String(S.asset));
  const avisos = [];
  const pf = visibles.filter((a) => a.facturas_pendientes);
  if (pf.length) avisos.push(`<div class="aviso-hito aviso-cobro"><h4>💶 Pendientes de cobro: ${pf.reduce((s, a) => s + a.facturas_pendientes, 0)} · ${eur(pf.reduce((s, a) => s + a.facturas_pendientes_importe, 0))}</h4>
    <p>${pf.map((a) => `${esc(a.nombre)}: ${a.facturas_pendientes} (${eur(a.facturas_pendientes_importe)}), la más antigua de ${a.facturas_pendientes_dias} días`).join(" · ")}.</p>
    <button class="btn sm primary" id="verCobros">Revisar</button></div>`);
  const pr = visibles.filter((a) => a.pagos_retenidos);
  if (pr.length) avisos.push(`<div class="aviso-hito aviso-cobro"><h4>⛔ Pago retenido: ${pr.reduce((s, a) => s + a.pagos_retenidos, 0)} · ${eur(pr.reduce((s, a) => s + a.pagos_retenidos_importe, 0))}</h4>
    <p>${pr.map((a) => `${esc(a.nombre)}: ${a.pagos_retenidos}${a.pagos_retenidos_revisar ? ` (<b>${a.pagos_retenidos_revisar} para revisar ya</b>)` : ""}`).join(" · ")}. No pagarlas hasta revisarlas.</p>
    <button class="btn sm primary" id="verRetenidas">Ver gastos</button></div>`);
  const ip = (p.informes_pendientes || []).filter((x) => !S.asset || String(x.asset_id) === String(S.asset));
  if (ip.length) avisos.push(`<div class="aviso-hito"><h4>📊 Informe a presidencia de ${esc(ip[0].periodo)}: pendiente</h4>
    <p>${ip.map((x) => `${esc(x.activo)} (lo envía ${esc(x.responsable)})`).join(" · ")}. Revíselo y envíelo por correo o WhatsApp.</p>
    <button class="btn sm primary" id="verPresidencia" data-a="${ip[0].asset_id}">Preparar informe</button></div>`);
  const ott = (p.ot_tecnico || []).filter((x) => !S.asset || String(x.asset_id) === String(S.asset));
  if (ott.length) {
    const esc_ = ott.filter((x) => x.resultado === "escalar"), pausa = ott.filter((x) => x.pausada);
    avisos.push(`<div class="aviso-hito${esc_.length || pausa.length ? " aviso-cobro" : ""}"><h4>🧰 Órdenes de trabajo con resultado del técnico: ${ott.length}${pausa.length ? ` · ${pausa.length} en pausa` : ""}</h4>
    ${esc_.map((x) => `<p class="error"><b>El personal propio solicita derivar la orden ${otNum(x.id)} a una subcontrata especializada.</b></p>`).join("")}
    <p>${ott.filter((x) => x.resultado !== "escalar").slice(0, 6).map((x) => `${otNum(x.id)} ${esc(x.titulo)}: <b>${esc(x.resultado_nombre)}</b>`).join(" · ")}</p>
    <button class="btn sm primary" id="verOtTecnico">Revisar</button></div>`);
  }
  const pe = (p.partes_estado || []).filter((x) => !S.asset || String(x.asset_id) === String(S.asset));
  if (pe.length) {
    const pend = pe.filter((x) => x.estado === "pendiente"), crit = pe.filter((x) => x.gravedad === "critica");
    avisos.push(`<div class="aviso-hito${crit.length ? " aviso-cobro" : ""}"><h4>🛠️ Partes de estado sin resolver: ${pe.length}${pend.length ? ` · ${pend.length} esperan orden de trabajo` : ""}${crit.length ? ` · ${crit.length} crítico(s)` : ""}</h4>
    <p>${pe.slice(0, 6).map((x) => `${esc(x.codigo)} ${esc(x.ubicacion)}: ${esc(x.elemento)} · ${esc(x.deficiencia)} (${esc(x.estado_nombre.toLowerCase())})`).join(" · ")}${pe.length > 6 ? " …" : ""}</p>
    <button class="btn sm primary" id="verPartesEstado">Revisar</button></div>`);
  }
  const ap = (p.ausencias_pendientes || []).filter((x) => !S.asset || String(x.asset_id) === String(S.asset));
  if (ap.length) avisos.push(`<div class="aviso-hito"><h4>🗓️ Ausencias que esperan su decisión: ${ap.length}</h4>
    <p>${ap.map((x) => `${esc(x.persona)} (${fdate(x.desde)}${x.hasta !== x.desde ? ` a ${fdate(x.hasta)}` : ""})`).join(" · ")}.</p>
    <button class="btn sm primary" id="verAusencias">Revisar</button></div>`);
  const ph = p.personal_hoy;
  if (ph && (ph.faltan.length || ph.dentro.length || ph.olvidos || ph.documentos)) {
    const fl = ph.faltan.filter((x) => !S.asset || String(x.asset_id) === String(S.asset));
    avisos.push(`<div class="aviso-hito${ph.olvidos || ph.documentos ? " aviso-cobro" : ""}"><h4>👥 Personal hoy: ${fl.length} ausente(s) · ${ph.dentro.length} dentro${ph.olvidos ? ` · ${ph.olvidos} sin fichar la salida` : ""}${ph.documentos ? ` · ${ph.documentos} documento(s) vencen` : ""}</h4>
    ${fl.length ? `<p>Ausentes: ${fl.map((x) => `${esc(x.persona)} (${esc(x.tipo)} hasta ${fdate(x.hasta)})`).join(" · ")}.</p>` : ""}
    ${ph.dentro.length ? `<p class="muted">Dentro: ${ph.dentro.map(esc).join(" · ")}.</p>` : ""}
    <button class="btn sm primary" id="verJornada">Registro de jornada</button> <button class="btn sm" id="verFichas">Fichas del personal</button></div>`);
  }
  (p.hitos || []).forEach((h) => avisos.push(`<div class="aviso-hito"><h4>📅 ${esc(h.titulo)} · ${fdate(h.fecha)} (${h.dias > 0 ? `faltan ${h.dias} días` : h.dias === 0 ? "hoy" : `hace ${-h.dias} días`})</h4><p>${esc(h.detalle)}</p></div>`));
  el.innerHTML = `<div class="panel-grid"><div class="panel-main">
    <div class="buscador"><input id="busq" type="search" autocomplete="off" placeholder="🔍 Buscar: documento, apartamento, cliente, teléfono, localizador, factura, OT, proveedor…" aria-label="Buscar">
      <div id="busqRes"></div></div>
    ${plano ? `<section class="plano-resumen" data-plano="${plano.id}"><div class="toolbar">
      ${planos.length > 1 ? `<span class="chips" style="margin:0">${planos.map((a) => `<button class="chip${a.id === plano.id ? " on" : ""}" data-elegir="${a.id}">${esc(a.nombre)}</button>`).join("")}</span>`
        : `<h3 style="margin:0">${esc(plano.nombre)}</h3>`}
      <button class="btn sm" id="abrirPlano">Abrir plano completo</button><span class="spacer"></span>${leyendaHtml()}</div>
      <div class="minis"><p class="muted">Cargando plano…</p></div></section>` : ""}
    <p class="muted panel-fecha">Situación a ${fdate(p.fecha)}</p><div class="cards panel-cards">${visibles.map((a) => {
    const k = [];
    // los datos del edificio son de los alojamientos: las plazas de garaje van aparte y no computan
    // cada casilla lleva a su listado (5º elemento: pantalla); el plano, con su botón
    k.push([a.unidades, Object.entries(a.usos || {}).filter(([u]) => u !== "garaje").map(([u, n]) => `${n} ${n === 1 ? u : plural(u)}`).join(" · ") || "Unidades", "", "", "unidades"]);
    if (a.ocupacion_hoy != null) k.push([a.ocupacion_hoy + " %", "Ocupación hoy", "", "Ocupación de hoy: abre el plano", "plano"]);
    if (a.llegadas_hoy != null) k.push([`${a.llegadas_hoy} / ${a.salidas_hoy}`, "Llegadas / salidas hoy", "", "", "hoy"]);
    if (a.estancias_vencidas) k.push([a.estancias_vencidas, "Estancias vencidas (ampliar reserva o salida)", "mal", "", "hoy"]);
    if (a.contratos_vigentes != null) {
      const al = a.alquiladas_por_uso || {};
      Object.entries(a.usos || {}).filter(([u]) => u !== "garaje").forEach(([u, n]) => {
        const t = plural(u);
        k.push([`${al[u] || 0} / ${n}`, `${t[0].toUpperCase()}${t.slice(1)} alquilad${["vivienda", "oficina"].includes(u) ? "as" : "os"}`, "", "", "contratos"]);
      });
    }
    if (a.produccion_mes != null) k.push([eur(a.produccion_mes), "Producción del mes", "", "Producción del mes: facturado sin IVA ni garajes" + (a.produccion_mes_externa ? ` · ${eur(a.produccion_mes_externa)} del programa anterior (SYADE)` : ""), "facturas"]);
    if (a.garajes) k.push([`${a.garajes_ocupados} / ${a.garajes}`, "Garajes alquilados", "", "Plazas de garaje alquiladas hoy (no computan en la ocupación)", "garajes"]);
    else if (a.usos?.garaje && a.alquiladas_por_uso) k.push([`${a.alquiladas_por_uso.garaje || 0} / ${a.usos.garaje}`, "Garajes alquilados", "", "Plazas de garaje alquiladas (no computan en la ocupación)", "contratos"]);
    if (a.garajes_facturado_mes) k.push([eur(a.garajes_facturado_mes), "Garajes facturados mes (aparte)", "", "", "facturas"]);
    if (a.renta_mensual != null) k.push([eur(a.renta_mensual), "Renta mensual", "", "", "recibos"], [eur(a.deuda_vencida), "Deuda vencida", "", "", "recibos"]);
    if (a.ot_abiertas != null) k.push([`${a.ot_abiertas} · ${a.ot_urgentes} · ${a.ot_pendientes_cierre}`, "OT abiert. · urg. · cerrar", a.ot_urgentes ? "mal" : "", "Órdenes de trabajo: abiertas · urgentes · pendientes de cierre", "ordenes"]);
    const est = Object.entries(a.estados).map(([e, n]) => `${badge(e)} ${n}`).join(" ");
    const clic = conMapa.has(a.id);  // el plano: con su botón o pulsando en una zona en blanco de la tarjeta
    return `<div class="card${clic ? " clic" : ""}" ${clic ? `data-abrir="${a.id}" title="Pulse en una zona en blanco o en «Ver plano» para abrir el plano de ${esc(a.nombre)}"` : ""}>${logoActivo(a.id)}<h3>${esc(a.nombre)}${clic ? `<button type="button" class="btn sm ver-plano" data-plano-btn="${a.id}" title="Abrir el plano del edificio de ${esc(a.nombre)}">🗺️ Ver plano del edificio</button>` : ""}</h3><div class="sub" title="${esc(`${a.modalidad_nombre} · Gestiona ${a.sociedad} · Propiedad ${a.propietaria}`)}">${esc(a.modalidad_nombre)} · ${esc(a.sociedad)}</div>
      ${a.ocupacion_hoy != null ? `<div class="bar"><i style="width:${Math.min(100, a.ocupacion_hoy)}%"></i></div>` : ""}
      <div class="kpis">${k.map(([v, l, cls, tip, ir]) => {
        const ok = ir && puedeIr(ir);
        return `<div class="kpi ${cls || ""}${ok ? " ir" : ""}" ${ok ? `data-ir="${ir}" data-a="${a.id}" tabindex="0" role="button"` : ""} title="${esc((tip || l) + (ok ? ` · Pulse para abrir «${tituloVista(ir)}»` : ""))}"><b>${esc(v)}</b><span>${esc(l)}</span></div>`;
      }).join("")}</div>
      <p class="estados">${est || '<span class="muted">Sin unidades dadas de alta</span>'}</p></div>`;
  }).join("")}</div></div>
    <aside class="panel-lateral"><section class="panel-agenda"><h3>📅 Agenda</h3><div id="agp"></div></section>${avisos.join("")}</aside></div>`;
  el.querySelectorAll("[data-abrir]").forEach((c) => {
    c.onclick = (e) => {  // zona en blanco o botón «Ver plano»; las casillas llevan a su listado
      if (e.target.closest("[data-ir]")) return;
      S.plano = { asset: Number(c.dataset.abrir) }; go("plano");
    };
  });
  el.querySelectorAll("[data-ir]").forEach((k) => {
    const ir = () => { setAsset(k.dataset.a); if (k.dataset.ir === "plano") S.plano = { asset: Number(k.dataset.a) }; go(k.dataset.ir); };
    k.onclick = (e) => { e.stopPropagation(); ir(); };
    k.onkeydown = (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), e.stopPropagation(), ir());
  });
  el.querySelectorAll("[data-elegir]").forEach((b) => (b.onclick = () => {
    try { localStorage.setItem("pms_panel_plano", b.dataset.elegir); } catch {}
    const sec = $("[data-plano]", el);
    sec.dataset.plano = b.dataset.elegir;
    el.querySelectorAll("[data-elegir]").forEach((x) => x.classList.toggle("on", x === b));
    pintarMinis(el).catch(() => {});
  }));
  if ($("#abrirPlano", el)) $("#abrirPlano", el).onclick = () => { S.plano = { asset: Number($("[data-plano]", el).dataset.plano) }; go("plano"); };
  if ($("#verCobros", el)) $("#verCobros", el).onclick = () => { S.filtroCobro = "pendiente"; go("facturas"); };
  if ($("#verRetenidas", el)) $("#verRetenidas", el).onclick = () => go("gastos");
  if ($("#verPresidencia", el)) $("#verPresidencia", el).onclick = (e) => { S.presidencia = { asset: e.currentTarget.dataset.a }; go("presidencia"); };
  if ($("#verAusencias", el)) $("#verAusencias", el).onclick = () => go("ausencias");
  if ($("#verJornada", el)) $("#verJornada", el).onclick = () => go("jornada");
  if ($("#verFichas", el)) $("#verFichas", el).onclick = () => go("personal");
  if ($("#verPartesEstado", el)) $("#verPartesEstado", el).onclick = () => go("estado?ver=lista");
  if ($("#verOtTecnico", el)) $("#verOtTecnico", el).onclick = () => go("ordenes");
  pintarMinis(el).catch((e) => el.querySelectorAll(".minis").forEach((m) => (m.innerHTML = `<p class="error">${esc(e.message)}</p>`)));
  bindBuscador($("#busq", el), $("#busqRes", el));
  agendaWidget($("#agp", el), false, true);
};

// ------------------------------------------------------------------ agenda (calendario de todos los usuarios)
// Reuniones, tareas, recordatorios y eventos: privados (solo yo), para personas concretas o públicos (todos).
const AG_TIPOS = { reunion: ["Reunión", "#2b6cb0"], tarea: ["Tarea", "#b7791f"], recordatorio: ["Recordatorio", "#2f855a"], evento: ["Evento", "#6b46c1"] };
const AG_VIS = [["privada", "🔒 Privada (solo yo)"], ["compartida", "👥 Solo las personas indicadas"], ["publica", "🌐 Pública (todos los usuarios)"]];
const AG_REP = [["", "No se repite"], ["diaria", "Cada día"], ["semanal", "Cada semana"], ["mensual", "Cada mes"], ["anual", "Cada año"]];
const AG_AVISO = [["", "Sin aviso por correo"], ["0", "A la hora de la cita"], ["15", "15 minutos antes"], ["60", "1 hora antes"], ["1440", "1 día antes"], ["2880", "2 días antes"], ["10080", "1 semana antes"]];
const isoLocal = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const hora = (x) => x.slice(11, 16);
const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];

async function editarCita(e, fecha, recargar) {  // e: cita existente o null
  S.agUsuarios = S.agUsuarios || await get("/api/agenda/usuarios");
  const ini = e ? e.inicio : `${fecha || today()}T09:00`;
  const v = e ? { ...e, fecha: ini.slice(0, 10), hora_ini: e.todo_el_dia ? "" : hora(ini), hora_fin: e.fin ? hora(e.fin) : "",
    participantes: e.participantes.map((p) => String(p.user_id)), aviso_min: e.aviso_min == null ? "" : String(e.aviso_min) }
    : { tipo: "tarea", fecha: ini.slice(0, 10), hora_ini: "09:00", visibilidad: "compartida", prioridad: "normal", aviso_min: "" };
  const destinos = S.agUsuarios.filter((u) => u.asignable || v.participantes?.includes(String(u.id)));
  const f = form(e ? `${AG_TIPOS[e.tipo][0]}: ${e.titulo}` : "Nueva cita en la agenda", [
    { k: "tipo", t: "Tipo", type: "select", req: true, options: Object.entries(AG_TIPOS).map(([k, [t]]) => [k, t]) },
    { k: "titulo", t: "Asunto", req: true, wide: true },
    { k: "fecha", t: "Fecha", type: "date", req: true }, { k: "hora_ini", t: "Hora (vacío = todo el día)", type: "time" }, { k: "hora_fin", t: "Hasta las", type: "time" },
    { k: "visibilidad", t: "Quién la ve", type: "select", req: true, options: AG_VIS },
    { k: "participantes", t: "Para / convocados (solo lo ven ellos y usted, salvo si es pública)", type: "checks", options: destinos.map((u) => [String(u.id), u.nombre]) },
    { k: "lugar", t: "Lugar" }, { k: "prioridad", t: "Prioridad", type: "select", req: true, options: [["normal", "Normal"], ["alta", "Alta"]] },
    { k: "aviso_min", t: "Aviso por correo (en blanco: sin aviso)", type: "select", options: AG_AVISO.slice(1) },
    { k: "repeticion", t: "Se repite (en blanco: no)", type: "select", options: AG_REP.slice(1) }, { k: "repetir_hasta", t: "Repetir hasta (opcional)", type: "date" },
    { k: "asset_id", t: "Activo relacionado (opcional)", type: "select", options: S.assets.map((a) => [a.id, a.nombre]) },
    { k: "descripcion", t: "Detalle", type: "textarea", wide: true },
  ], v, async (d) => {
    const body = { tipo: d.tipo, titulo: d.titulo, lugar: d.lugar, descripcion: d.descripcion, visibilidad: d.visibilidad, prioridad: d.prioridad,
      todo_el_dia: !d.hora_ini, inicio: `${d.fecha}T${d.hora_ini || "00:00"}:00`, fin: d.hora_ini && d.hora_fin ? `${d.fecha}T${d.hora_fin}:00` : null,
      participantes: (d.participantes || []).map(Number), aviso_min: d.aviso_min === null ? null : Number(d.aviso_min),
      repeticion: d.repeticion || null, repetir_hasta: d.repetir_hasta, asset_id: d.asset_id ? Number(d.asset_id) : null };
    if (e) await put(`/api/agenda/${e.id}`, body); else await post("/api/agenda", body);
    toast(e ? "Cita actualizada" : body.participantes.length ? "Cita creada y enviada" : "Cita creada");
    recargar && recargar();
  }, e ? "Guardar" : "Crear");
  const vis = f.elements.visibilidad, parts = f.querySelector('input[name="participantes"]')?.closest("fieldset");
  const pinta = () => { if (parts) parts.style.display = vis.value === "privada" ? "none" : ""; };
  vis.onchange = pinta; pinta();
  if (e && !e.puede_editar) f.querySelectorAll("input, select, textarea, button[type=submit]").forEach((x) => (x.disabled = true));
}

function citaHtml(e, conFecha = false) {
  const [t, color] = AG_TIPOS[e.tipo] || ["", "#666"];
  const quien = e.mio ? (e.participantes.length ? `para ${e.participantes.map((p) => p.nombre + (p.respuesta === "acepta" ? " ✔" : p.respuesta === "rechaza" ? " ✖" : "")).join(", ")}` : "")
    : `de ${e.creador}`;
  return `<div class="cita${e.hecha ? " hecha" : ""}${e.nuevo ? " nueva" : ""}" style="border-left-color:${color}">
    <div><b>${conFecha ? fdate(e.ocurrencia.slice(0, 10)) + " · " : ""}${e.todo_el_dia ? "Todo el día" : hora(e.ocurrencia)}${e.fin_ocurrencia ? "–" + hora(e.fin_ocurrencia) : ""}</b> · <span style="color:${color}">${esc(t)}</span>
      ${e.prioridad === "alta" ? '<span class="badge b-urgente">alta</span>' : ""}${e.nuevo ? ' <span class="badge b-pendiente">nueva</span>' : ""}
      ${e.vencida ?  ' <span class="badge b-urgente">vencida</span>' : ""}${e.hecha ? ` <span class="badge b-cerrada">hecha${e.hecha_por_nombre ? " por " + esc(e.hecha_por_nombre) : ""}</span>` : ""}
      <span class="muted peq">${{ privada: "🔒", compartida: "👥", publica: "🌐" }[e.visibilidad]}${e.repeticion ? " 🔁" : ""}</span></div>
    <div class="cita-tit">${esc(e.titulo)}${e.lugar ? ` <span class="muted">· ${esc(e.lugar)}</span>` : ""}</div>
    ${e.descripcion ? `<div class="muted peq">${esc(e.descripcion)}</div>` : ""}
    <div class="muted peq">${esc(quien)}</div>
    <div class="toolbar">${e.tipo === "tarea" && (e.mio || e.para_mi) ? `<button class="btn sm" data-ag="hecha" data-id="${e.id}" data-v="${e.hecha ? 0 : 1}">${e.hecha ? "Reabrir" : "✔ Hecha"}</button>` : ""}
      ${e.para_mi && e.tipo === "reunion" ? `<button class="btn sm ${e.mi_respuesta === "acepta" ? "primary" : ""}" data-ag="acepta" data-id="${e.id}">Asisto</button><button class="btn sm ${e.mi_respuesta === "rechaza" ? "danger" : ""}" data-ag="rechaza" data-id="${e.id}">No asisto</button>` : ""}
      <button class="btn sm" data-ag="ver" data-id="${e.id}">${e.puede_editar ? "Editar" : "Ver"}</button>
      <button class="btn sm" data-ag="ics" data-id="${e.id}" title="Añadir a su calendario del móvil, Outlook o Google">📅 A mi calendario</button>
      ${e.puede_editar ? `<button class="btn sm danger" data-ag="borrar" data-id="${e.id}">Borrar</button>` : ""}</div></div>`;
}

// Calendario mensual con los días que tienen citas marcados; al pulsar un día se ven sus citas al lado.
function agendaWidget(cont, grande = false, compacta = false) {
  const hoy = new Date();
  let mes = new Date(hoy.getFullYear(), hoy.getMonth(), 1), sel = isoLocal(hoy), citas = [], pend = { tareas: [], nuevas: [] };
  const cargar = async () => {
    const ini = new Date(mes), dow = (ini.getDay() + 6) % 7;
    const desde = new Date(ini); desde.setDate(1 - dow);
    const hasta = new Date(desde); hasta.setDate(desde.getDate() + 41);
    [citas, pend] = await Promise.all([get("/api/agenda", { desde: isoLocal(desde), hasta: isoLocal(hasta) }), get("/api/agenda/pendientes")]);
    pintar(desde);
  };
  const pintar = (desde) => {
    const porDia = {};
    citas.forEach((c) => (porDia[c.ocurrencia.slice(0, 10)] ||= []).push(c));
    const celdas = [...Array(42)].map((_, i) => {
      const d = new Date(desde); d.setDate(desde.getDate() + i);
      const k = isoLocal(d), cs = porDia[k] || [], fuera = d.getMonth() !== mes.getMonth();
      const puntos = [...new Set(cs.map((c) => c.tipo))].map((t) => `<i style="background:${AG_TIPOS[t][1]}"></i>`).join("");
      return `<button type="button" class="ag-dia${fuera ? " fuera" : ""}${k === isoLocal(hoy) ? " hoy" : ""}${k === sel ? " sel" : ""}${cs.some((c) => c.nuevo) ? " con-nueva" : ""}" data-dia="${k}">
        <span>${d.getDate()}</span>${cs.length ? `<span class="ag-puntos">${puntos}</span>${grande ? `<span class="ag-n">${cs.length}</span>` : ""}` : ""}</button>`;
    }).join("");
    const delDia = porDia[sel] || [];
    const f = new Date(sel + "T12:00");
    cont.innerHTML = `<div class="agenda${grande ? " grande" : ""}${compacta ? " compacta" : ""}">
      <div class="ag-cal"><div class="toolbar"><button class="btn sm" data-mes="-1">‹</button><b class="ag-mes">${MESES[mes.getMonth()]} ${mes.getFullYear()}</b><button class="btn sm" data-mes="1">›</button>
        <button class="btn sm" data-mes="0">Hoy</button><span class="spacer"></span><button class="btn sm primary" data-nueva title="Nueva cita, tarea o recordatorio">${compacta ? "+" : "+ Nueva"}</button></div>
        <div class="ag-sem">${["L", "M", "X", "J", "V", "S", "D"].map((x) => `<span>${x}</span>`).join("")}</div><div class="ag-grid">${celdas}</div>
        <p class="ag-leyenda">${Object.values(AG_TIPOS).map(([t, c]) => `<span><i style="background:${c}"></i>${t}</span>`).join("")}</p></div>
      <div class="ag-lista">
        ${pend.nuevas.length ? `<div class="ag-nuevas"><h4>🔔 Nuevo para usted (${pend.nuevas.length})</h4>${pend.nuevas.map((n) => `<div class="ag-nueva">
          <span><b>${esc(AG_TIPOS[n.tipo][0])}</b> de ${esc(n.creador)} · ${fdate(n.ocurrencia.slice(0, 10))}${n.todo_el_dia ? "" : " " + hora(n.ocurrencia)} · ${esc(n.titulo)}</span>
          <span><button class="btn sm" data-ag="ir" data-id="${n.id}" data-fecha="${n.ocurrencia.slice(0, 10)}">Ver día</button><button class="btn sm" data-ag="visto" data-id="${n.id}">Entendido</button></span></div>`).join("")}</div>` : ""}
        <h4>${f.toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" })}</h4>
        ${delDia.length ? delDia.map(citaHtml).join("") : '<p class="muted">Sin citas este día.</p>'}
        ${pend.tareas.length ? `<h4>Tareas pendientes (${pend.tareas.length})</h4>${pend.tareas.map((t) => citaHtml(t, true)).join("")}` : ""}
      </div></div>`;
    cont.querySelectorAll("[data-dia]").forEach((b) => (b.onclick = () => { sel = b.dataset.dia; pintar(desde); }));
    cont.querySelectorAll("[data-mes]").forEach((b) => (b.onclick = () => {
      const n = Number(b.dataset.mes);
      mes = n ? new Date(mes.getFullYear(), mes.getMonth() + n, 1) : new Date(hoy.getFullYear(), hoy.getMonth(), 1);
      if (!n) sel = isoLocal(hoy);
      cargar();
    }));
    cont.querySelector("[data-nueva]").onclick = () => editarCita(null, sel, cargar);
    const todas = [...citas, ...pend.tareas, ...pend.nuevas];
    cont.querySelectorAll("[data-ag]").forEach((b) => (b.onclick = async () => {
      const id = Number(b.dataset.id), c = todas.find((x) => x.id === id), a = b.dataset.ag;
      if (c?.nuevo) post(`/api/agenda/${id}/visto`).catch(() => {});
      if (a === "ver") return editarCita(c, null, cargar);
      if (a === "visto") { await post(`/api/agenda/${id}/visto`); return cargar(); }
      if (a === "ir") { sel = b.dataset.fecha; const f = new Date(sel + "T12:00"); mes = new Date(f.getFullYear(), f.getMonth(), 1); return cargar(); }
      if (a === "ics") return download("GET", `/api/agenda/${id}/ics`).catch((er) => toast(er.message, true));
      if (a === "borrar") { if (!confirm(`¿Borrar «${c.titulo}»${c.repeticion ? " (todas las repeticiones)" : ""}?`)) return; await run(() => api("DELETE", `/api/agenda/${id}`), "Cita borrada"); }
      if (a === "hecha") await run(() => post(`/api/agenda/${id}/hecha`, { hecha: b.dataset.v === "1" }), b.dataset.v === "1" ? "Tarea hecha" : "Tarea reabierta");
      if (a === "acepta" || a === "rechaza") await run(() => post(`/api/agenda/${id}/respuesta`, { respuesta: a }), a === "acepta" ? "Asistencia confirmada" : "Ha indicado que no asiste");
      cargar();
    }));
  };
  cargar().catch((e) => (cont.innerHTML = `<p class="error">${esc(e.message)}</p>`));
}
V.agenda = (el) => { el.innerHTML = '<div id="agw"></div>'; agendaWidget($("#agw", el), true); };

// ------------------------------------------------------------------ buscador del panel
// Un dato cualquiera y se ven todas las coincidencias con sus acciones (ficha, cobro, check-in…) sin cambiar de página.
function bindBuscador(inp, res) {
  let t = null, n = 0;
  try { inp.value = sessionStorage.getItem("pms_busq") || ""; } catch {}
  const buscar = async () => {
    const q = inp.value.trim(), gen = ++n;
    try { sessionStorage.setItem("pms_busq", q); } catch {}
    if (q.length < 2) { res.innerHTML = ""; return; }
    res.innerHTML = '<p class="muted">Buscando…</p>';
    try {
      const d = await get("/api/buscar", { q });
      if (gen === n) pintaBusqueda(res, d, buscar);
    } catch (e) { if (gen === n) res.innerHTML = `<p class="error">${esc(e.message)}</p>`; }
  };
  inp.oninput = () => { clearTimeout(t); t = setTimeout(buscar, 350); };
  inp.onkeydown = (e) => { if (e.key === "Escape") { inp.value = ""; buscar(); } if (e.key === "Enter") { clearTimeout(t); buscar(); } };
  if (inp.value) buscar();
}
function pintaBusqueda(res, d, recargar) {
  const grupos = [
    ["clientes", "Clientes", [{ k: "nombre", t: "Nombre", f: (v) => `<b>${esc(v)}</b>` }, { k: "tipo_nombre", t: "Tipo" }, { k: "documento", t: "Documento" },
      { k: "telefono", t: "Teléfono" }, { k: "activo", t: "Activo" }, { k: "unidades", t: "Ahora en", f: (v) => esc((v || []).join(", ")) }],
      (c) => [["Ficha", () => editGuest(c.id, c.tipo, recargar)]]],
    ["reservas", "Reservas", [{ k: "localizador", t: "Localizador" }, { k: "unidad", t: "Unidad", f: (v) => `<b>${esc(v)}</b>` }, { k: "huesped", t: "Huésped" },
      { k: "fecha_entrada", t: "Entrada", f: fdate }, { k: "fecha_salida", t: "Salida", f: fdate },
      { k: "importe_total", t: "Pendiente", num: true, f: (v, r) => eur(v - r.importe_pagado) }, { k: "estado", t: "Estado", f: badge }], resActions(recargar)],
    ["unidades", "Apartamentos y plazas", [{ k: "codigo", t: "Unidad", f: (v) => `<b>${esc(v)}</b>` }, { k: "activo", t: "Activo" }, { k: "tipologia", t: "Tipología" },
      { k: "estado", t: "Estado", f: badge }, { k: "ocupante", t: "Ocupado por", f: (v) => (v ? esc(v) : '<span class="muted">libre</span>') }],
      (u) => [
        conPlanoActivo(u.asset_id) && ["Plano", () => { S.plano = { asset: u.asset_id }; go("plano"); }],
        u.modalidad === "apartamentos_turisticos" && can("reservas.editar") && ["Reservar", () => newReservation(recargar, { id: u.id, codigo: u.codigo, asset_id: u.asset_id, uso: u.uso })],
        canOpenOT() && ["Abrir OT", () => newWorkOrder(u.asset_id, u.id)],
        !canOpenOT() && canParteEstado() && ["Parte de estado", () => irParteEstado(u.asset_id, u.id)],
      ]],
    ["contratos", "Contratos de alquiler", [{ k: "referencia", t: "Ref." }, { k: "unidad", t: "Unidad" }, { k: "inquilino", t: "Inquilino" },
      { k: "fecha_inicio", t: "Inicio", f: fdate }, { k: "fecha_fin", t: "Fin", f: fdate }, { k: "renta_mensual", t: "Renta", num: true, f: eur }, { k: "estado", t: "Estado", f: badge }],
      (l) => [["Inquilino", () => editGuest(l.tenant_id, l.tenant_tipo, recargar)]]],
    ["facturas", "Facturas", [{ k: "codigo", t: "Factura", f: (v) => `<b>${esc(v)}</b>` }, { k: "fecha_expedicion", t: "Fecha", f: fdate }, { k: "activo", t: "Activo" },
      { k: "cliente", t: "Cliente", f: (v) => esc(v.nombre) }, { k: "total", t: "Total", num: true, f: eur }],
      (f) => [["PDF", () => descargarFactura(f.id)]]],
    ["ordenes", "Órdenes de trabajo", [{ k: "id", t: "OT", f: (v) => `<b>${otNum(v)}</b>` }, { k: "titulo", t: "Título" }, { k: "activo", t: "Activo" },
      { k: "unidad", t: "Unidad", f: (v, w) => esc(v || w.zona_nombre || "") }, { k: "prioridad", t: "Prioridad", f: badge }, { k: "estado", t: "Estado", f: badge }],
      (w) => [["Adjuntos", () => adjuntosOT(w, recargar)], puedeEnviarOT() && ["Enviar", () => enviarAsignado(w, recargar)]]],
    ["proveedores", "Proveedores", [{ k: "nombre", t: "Nombre", f: (v) => `<b>${esc(v)}</b>` }, { k: "nif", t: "NIF" }, { k: "actividad", t: "Actividad" },
      { k: "telefono", t: "Teléfono" }, { k: "email", t: "Correo" }], null],
  ];
  const hay = grupos.filter(([k]) => d[k]?.length);
  if (!hay.length) { res.innerHTML = `<p class="muted">Sin resultados para «${esc(d.q)}».</p>`; return; }
  res.innerHTML = `<p class="muted">${hay.map(([k, t]) => `<a href="#" data-ir="${k}">${esc(t)} (${d[k].length})</a>`).join(" · ")}
    <a href="#" data-cerrar class="peq">✕ cerrar</a></p>` + hay.map(([k, t]) => `<section class="busq-grupo" id="bq-${k}"><h4>${esc(t)}</h4><div data-g="${k}"></div></section>`).join("");
  hay.forEach(([k, , cols, acciones]) => table(res.querySelector(`[data-g="${k}"]`), cols, d[k], acciones));
  res.querySelectorAll("[data-ir]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); res.querySelector(`#bq-${a.dataset.ir}`).scrollIntoView({ behavior: "smooth", block: "start" }); }));
  res.querySelector("[data-cerrar]").onclick = (e) => { e.preventDefault(); const i = $("#busq"); i.value = ""; i.oninput(); res.innerHTML = ""; };
}
const conPlanoActivo = (aid) => S.conPlano?.has(aid);

// miniaturas del plano en el panel (se rellenan después para no retrasar el resto)
async function pintarMinis(el) {
  for (const sec of el.querySelectorAll("[data-plano]")) {
    const pl = await get(`/api/plano/${sec.dataset.plano}`);
    const ley = $(".leyenda", sec);
    if (ley) ley.style.display = pl.tipo === "carpetas" ? "none" : "";  // la leyenda de colores es del croquis
    if (pl.tipo === "carpetas") {  // Babilonia 35: carpetas por planta en vez de croquis
      $(".minis", sec).style.gridTemplateColumns = "1fr";
      $(".minis", sec).innerHTML = `<div class="carpetas mini">${pl.plantas.map((x) => carpetaHtml(pl, x)).join("")}</div>`;
      sec.querySelectorAll("[data-carpeta]").forEach((b) => (b.onclick = () => { S.plano = { asset: pl.asset.id, planta: b.dataset.carpeta }; go("plano"); }));
      continue;
    }
    // panel: todas las plantas en una sola fila (si caben), para ver el edificio entero de un vistazo
    $(".minis", sec).style.gridTemplateColumns = sec.closest(".panel-main") && sec.clientWidth / pl.plantas.length >= 105
      ? `repeat(${pl.plantas.length}, minmax(0, 1fr))` : "";
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
      return `<div class="pc u pc-${c.estado}" style="${pos}" data-u="${c.unit_id}" title="${esc(tip)}">${mini ? "" : `<b>${esc(c.num)}</b><small>${esc(c.tipo)}</small>${c.ot ? `<span class="m${c.urgente ? " urg" : ""}">M</span>` : ""}${c.limpieza ? '<span class="lim" title="Pendiente de limpieza">L</span>' : ""}${c.vencida ? '<span class="venc" title="Estancia vencida: ampliar la reserva o dar la salida">V</span>' : ""}`}</div>`;
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

// ------------------------------------------------------------------ carpetas por planta (Babilonia 35)
// Situación de cada vivienda: se pide la primera vez que se abre; si está alquilada, después el contrato.
const SIT_ICONO = { alquilada: "🔑", vacia: "🟢", reservada: "📝", reforma_menor: "🛠️", obra_mayor: "🏗️", ocupada_sin_titulo: "⚠️", en_venta: "🏷️", uso_propio: "🏢", otra: "•" };
function carpetaHtml(pl, x) {
  const r = x.resumen;
  const pend = r.pendientes ? `<span class="carpeta-pend" title="Viviendas con la situación o el contrato pendientes">${r.pendientes} pendiente${r.pendientes === 1 ? "" : "s"}</span>` : "";
  return `<button type="button" class="carpeta${x.garaje ? " garaje" : ""}" data-carpeta="${esc(x.planta)}" title="Abrir ${esc(x.etiqueta)}">
    <span class="carpeta-icono"><span class="pestana"></span><span class="cuerpo">${pl.logo ? `<img src="${esc(pl.logo)}" alt="${esc(pl.sociedad || "")}">` : ""}</span></span>
    <b>${esc(x.etiqueta)}</b><small>${r.total} ${x.garaje ? (r.total === 1 ? "plaza" : "plazas") : r.total === 1 ? "vivienda" : "viviendas"}</small>${pend}</button>`;
}
function viviendaHtml(u) {
  const garaje = u.uso === "garaje";
  const sit = garaje ? (u.alquiler ? "alquilada" : "vacia") : u.situacion || "sin";
  const txt = garaje ? (u.alquiler ? `Alquilada · ${u.alquiler.cliente}` : "Libre") : u.situacion ? (u.situacion === "otra" && u.situacion_texto ? u.situacion_texto : u.situacion_nombre) : "Situación sin indicar";
  return `<button type="button" class="vivienda sit-${sit}${u.pendiente_situacion || u.pendiente_contrato ? " pendiente" : ""}" data-u="${u.unit_id}" title="Abrir ${esc(u.codigo)}">
    <span class="viv-icono">${garaje ? "🚗" : SIT_ICONO[u.situacion] || "🏠"}</span>
    <b>${esc(u.codigo)}</b><small>${esc([u.tipologia, u.superficie_m2 ? `${u.superficie_m2} m²` : ""].filter(Boolean).join(" · "))}</small>
    <span class="viv-sit">${esc(txt)}</span>${u.inquilino ? `<small class="viv-inq">${esc(u.inquilino)}</small>` : ""}
    ${u.pendiente_situacion ? '<span class="viv-aviso">Indicar situación</span>' : u.pendiente_contrato ? '<span class="viv-aviso">Contrato pendiente</span>' : ""}
    ${u.ot ? `<span class="m-ej${u.urgente ? " urg" : ""}" title="${u.ot} incidencia(s) abierta(s)">M</span>` : ""}</button>`;
}
function vistaCarpetas(el, datos, recarga) {
  const planta = datos.plantas.find((x) => x.planta === S.plano.planta);
  $("#tabs", el).innerHTML = "";
  if (!planta) {
    S.plano.planta = null;
    $("#grid", el).innerHTML = `<p class="muted">Pulse una carpeta para ver las viviendas o plazas de esa planta.</p><div class="carpetas">${datos.plantas.map((x) => carpetaHtml(datos, x)).join("")}</div>`;
    $("#grid", el).querySelectorAll("[data-carpeta]").forEach((b) => (b.onclick = () => { S.plano.planta = b.dataset.carpeta; vistaCarpetas(el, datos, recarga); }));
  } else {
    $("#grid", el).innerHTML = `<div class="ruta"><button type="button" class="btn sm" data-volver>← Todas las plantas</button>
      <span class="carpeta-abierta">📂 ${esc(datos.asset.nombre)} › <b>${esc(planta.etiqueta)}</b></span>
      <span class="spacer"></span>${datos.plantas.map((x) => `<button type="button" class="chip${x.planta === planta.planta ? " on" : ""}" data-ir="${esc(x.planta)}">${esc(x.etiqueta)}</button>`).join("")}</div>
      <div class="viviendas">${planta.unidades.map(viviendaHtml).join("")}</div>`;
    $("[data-volver]", el).onclick = () => { S.plano.planta = null; vistaCarpetas(el, datos, recarga); };
    $("#grid", el).querySelectorAll("[data-ir]").forEach((b) => (b.onclick = () => { S.plano.planta = b.dataset.ir; vistaCarpetas(el, datos, recarga); }));
    $("#grid", el).querySelectorAll("[data-u]").forEach((c) => (c.onclick = () => abrirVivienda(Number(c.dataset.u), recarga)));
  }
  const viv = datos.plantas.filter((x) => !x.garaje && (!planta || x === planta));
  const suma = (k) => viv.reduce((s, x) => s + (x.resumen[k] || 0), 0);
  $("#lat", el).innerHTML = `<h4>${esc(datos.asset.nombre)}</h4><p class="muted">${planta ? esc(planta.etiqueta) : "Todas las plantas"}${datos.sociedad ? " · " + esc(datos.sociedad) : ""}</p>
    ${planta?.garaje ? `<p class="muted">Plazas de garaje: pulse una para ver su ficha.</p>` : `<div class="marcadores">${Object.entries(datos.situaciones).map(([k, t]) => `<div><i class="sit-${k}"></i><span>${SIT_ICONO[k]} ${esc(t)}</span><b>${suma(k)}</b></div>`).join("")}
      <div><i class="sit-sin"></i><span>Situación sin indicar</span><b>${suma("sin_situacion")}</b></div>
      <div class="total"><span>Contratos pendientes de completar</span><b>${suma("contrato_pendiente")}</b></div></div>`}
    <p class="muted">Al abrir una vivienda por primera vez se pide su situación. Si está alquilada, después se pide completar el contrato; ese aviso vuelve cada día hasta que el contrato está completo. Mientras tanto se puede trabajar en la vivienda (facturas, incidencias…).</p>`;
}

// Al abrir una vivienda: primero lo pendiente (situación y contrato), después su ficha
async function abrirVivienda(uid, recarga) {
  const d = await run(() => get(`/api/plano/unidades/${uid}/ficha`));
  const p = d.pendientes || {};
  if (p.situacion && d.puede.situacion) return pedirSituacion(d, recarga, true);
  if (p.contrato?.mostrar && d.puede.contrato) return pedirContrato(d, recarga);
  fichaApartamento(uid, recarga, d);
}
function pedirSituacion(d, recarga, primeraVez = false) {
  const u = d.unidad, actual = d.situacion || {};
  const f = form(`Vivienda ${u.codigo} · ¿En qué situación se encuentra?`, [
    { html: `${primeraVez ? '<p class="aviso-amarillo">Es la primera vez que se abre esta vivienda: indique su situación. Si no lo hace ahora, se volverá a pedir cada vez que la abra.</p>' : ""}
      <div class="situaciones">${Object.entries(d.situaciones).map(([k, t]) => `<label class="situacion sit-${k}"><input type="radio" name="sit" value="${k}" ${actual.clave === k ? "checked" : ""}><span>${SIT_ICONO[k]}</span>${esc(t)}</label>`).join("")}</div>
      <label class="wide" data-otra style="display:none">Indique la situación *<input name="texto_sit" maxlength="200" value="${esc(actual.texto || "")}"></label>
      ${actual.fecha ? `<p class="muted">Indicada el ${fdt(actual.fecha)}${actual.por ? " por " + esc(actual.por) : ""}.</p>` : ""}` },
  ], {}, async () => {
    const sit = f.querySelector("input[name=sit]:checked")?.value;
    if (!sit) throw new Error("Elija la situación de la vivienda");
    const texto = f.elements.texto_sit.value.trim();
    if (sit === "otra" && !texto) throw new Error("Indique cuál es la situación");
    const r = await put(`/api/plano/unidades/${u.id}/situacion`, { situacion: sit, texto: sit === "otra" ? texto : null });
    toast(`Vivienda ${u.codigo}: ${d.situaciones[sit]}`);
    recarga && recarga();
    setTimeout(() => (r.pendientes.contrato && d.puede.contrato ? pedirContrato({ ...d, pendientes: r.pendientes, situacion: r.situacion }, recarga) : fichaApartamento(u.id, recarga)), 0);
  }, "Guardar situación");
  const otra = () => { $("[data-otra]", f).style.display = f.querySelector("input[name=sit]:checked")?.value === "otra" ? "" : "none"; };
  f.querySelectorAll("input[name=sit]").forEach((r) => (r.onchange = otra)); otra();
  $("#fCancel").textContent = primeraVez ? "Ahora no, abrir la vivienda" : "Cancelar";
  if (primeraVez) $("#fCancel").onclick = () => { $("#modal").close(); fichaApartamento(u.id, recarga); };
}
function pedirContrato(d, recarga) {
  const u = d.unidad, c = d.pendientes.contrato;
  const f = cerrarSolo(form(`Vivienda ${u.codigo} alquilada · contrato pendiente`, [
    { html: `<p class="aviso-amarillo">${c.lease_id ? "El contrato de alquiler está sin completar." : "La vivienda está alquilada pero aún no tiene contrato en el PMS."} Este aviso volverá a salir cada día hasta que el contrato esté completo. Mientras tanto puede trabajar en la vivienda.</p>
      <p><b>Falta${c.faltan.length === 1 ? "" : "n"} ${c.faltan.length} dato${c.faltan.length === 1 ? "" : "s"}:</b></p><ul class="faltan">${c.faltan.slice(0, 12).map((x) => `<li>${esc(x)}</li>`).join("")}${c.faltan.length > 12 ? `<li>… y ${c.faltan.length - 12} más</li>` : ""}</ul>
      <div class="acciones-ap"><button type="button" class="accion-ap" data-ahora><span class="caja">📝</span><b>${c.lease_id ? "Completar el contrato" : "Crear el contrato"}</b><small>${c.lease_id ? "Abrir el expediente en «Datos del contrato»" : "Inquilino, fechas, renta y fianza; después, el expediente"}</small></button>
      <button type="button" class="accion-ap" data-luego><span class="caja">⏰</span><b>Completar más tarde</b><small>No volverá a salir hasta mañana. Se abre la vivienda.</small></button></div>` },
  ], {}, async () => {}));
  $("[data-ahora]", f).onclick = () => {
    if (c.lease_id) expediente({ id: c.lease_id }, "datos");
    else nuevoContrato(u.asset_id, { id: u.id, codigo: u.codigo }, (lease) => { recarga && recarga(); expediente(lease, "datos"); });
  };
  $("[data-luego]", f).onclick = async () => { await run(() => post(`/api/plano/unidades/${u.id}/contrato-mas-tarde`, {})); recarga && recarga(); fichaApartamento(u.id, recarga); };
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
    if (datos.tipo === "carpetas") return vistaCarpetas(el, datos, recarga);
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
      <div><span class="m-ej">M</span><span>Mantenimiento pendiente (rojo: urgente)</span></div><div><span class="m-ej venc">V</span><span>Estancia vencida: ampliar la reserva o dar la salida</span></div><div><span class="m-ej lim">L</span><span>Pendiente de limpieza</span></div></div>
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
async function fichaApartamento(uid, recarga, cargada = null) {
  const d = cargada || await run(() => get(`/api/plano/unidades/${uid}/ficha`));
  const u = d.unidad;
  const garaje = u.uso === "garaje";
  const vivienda = !!d.situaciones;  // vivienda en alquiler residencial (Babilonia 35)
  const items = [];
  (d.contratos || []).forEach((l) => items.push({ tipo: "contrato", fecha: l.fecha_inicio, texto: [l.inquilino, l.referencia, l.estado].join(" "),
    html: `<b>Contrato de alquiler · ${esc(l.inquilino)}</b> · ${fdate(l.fecha_inicio)}${l.fecha_fin ? " → " + fdate(l.fecha_fin) : ""} · ${badge(l.estado)}<br><span class="muted">${eur(l.renta_mensual)}/mes${l.fianza ? " · fianza " + eur(l.fianza) : ""}</span>`,
    acc: [["Expediente", () => expediente(l)]] }));
  (d.gastos || []).forEach((g) => items.push({ tipo: "gasto", fecha: g.fecha, texto: [g.proveedor, g.numero_factura, g.concepto, g.naturaleza].join(" "),
    html: `<b>Factura recibida · ${esc(g.proveedor || "sin proveedor")}</b>${g.numero_factura ? " · " + esc(g.numero_factura) : ""} · ${eur(g.total)} · ${g.pagado ? badge("pagado") : badge("pendiente")}<br><span class="muted">${fdate(g.fecha)} · ${esc(g.concepto)}${g.naturaleza ? " · " + esc(g.naturaleza) : ""}</span>`,
    acc: g.documento_id ? [["Ver", () => abrirFichero(`/api/documentos-recibidos/${g.documento_id}/fichero`)]] : [] }));
  (d.reservas || []).forEach((r) => items.push({ tipo: "reserva", fecha: r.entrada, texto: [r.localizador, r.huesped, r.documento, r.canal, r.estado, r.notas].join(" "),
    html: `<b>Reserva ${esc(r.localizador || "R-" + r.id)}</b> · ${fdate(r.entrada)} → ${fdate(r.salida)} (${r.noches} noches) · ${esc(r.huesped)} · ${badge(r.estado)}${r.proxima ? ' <span class="badge b-pendiente">próxima</span>' : ""}<br><span class="muted">${esc(r.canal)} · ${r.adultos + r.ninos} pax · ${eur(r.importe_total)} (cobrado ${eur(r.importe_pagado)})${r.contrato ? " · contrato impreso" : ""}</span>`,
    acc: can("reservas.editar") ? [...(garaje ? [] : [["Contrato", () => accommodationContract({ id: r.id, unidad: u.codigo, huesped: r.huesped })]]),
      ...(!garaje && ["confirmada", "checkin"].includes(r.estado) ? [["Ampliar reserva", () => renovarEstancia({ id: r.id, unidad: u.codigo, huesped: r.huesped }, recarga)]] : []),
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
  const TIPOS = [["", "Todo"], ["contrato", "Contratos"], ["gasto", "Facturas recibidas"], ["alquiler", "Alquileres"], ["reserva", "Reservas"], ["cliente", "Clientes"], ["incidencia", "Incidencias"], ["bloqueo", "Bloqueos"], ["factura", "Facturas"]].filter(([t]) => !t || items.some((i) => i.tipo === t));
  const bloqueoVigente = (d.bloqueos || []).find((b) => !b.levantado);
  const actual = d.alquiler ? `<p><b>Alquilada por meses a:</b> ${esc(d.alquiler.cliente)} · desde ${fdate(d.alquiler.desde)}${d.alquiler.hasta ? " hasta " + fdate(d.alquiler.hasta) : ""}${d.alquiler.matricula ? " · " + esc(d.alquiler.matricula) : ""}</p>`
    : d.actual ? `<p><b>${d.estado === "alquilado" ? "Alojado" : d.actual.proxima ? "Próxima llegada" : "Llega hoy"}:</b> ${esc(d.actual.huesped)} · ${fdate(d.actual.entrada)} → ${fdate(d.actual.salida)}</p>` : "";
  const sit = d.situacion || {};
  const pc = d.pendientes?.contrato;
  const cabVivienda = vivienda ? `<p><span class="estado-ap sit-${sit.clave || "sin"}">${sit.clave ? `${SIT_ICONO[sit.clave]} ${esc(sit.clave === "otra" && sit.texto ? sit.texto : sit.nombre)}` : "Situación sin indicar"}</span>
      ${esc(u.tipologia || "")}${u.superficie_m2 ? ` · ${u.superficie_m2} m²` : ""} · planta ${esc(u.planta || "")}${sit.fecha ? ` <span class="muted">· indicada el ${fdate(sit.fecha)}${sit.por ? " por " + esc(sit.por) : ""}</span>` : ""}</p>
      ${pc ? `<p class="aviso-amarillo">Contrato pendiente: falta${pc.faltan.length === 1 ? "" : "n"} ${pc.faltan.length} dato${pc.faltan.length === 1 ? "" : "s"} (${esc(pc.faltan.slice(0, 3).join(", "))}${pc.faltan.length > 3 ? "…" : ""}).</p>` : ""}` : "";
  const acciones = vivienda ? [
    d.puede.situacion && ["situacion", "Situación", "Alquilada, vacía, en reforma, en obra…"],
    d.puede.contrato && sit.clave === "alquilada" && ["contrato", pc && !pc.lease_id ? "Crear contrato" : "Contrato", pc ? "Completar los datos del contrato" : "Expediente del contrato de alquiler"],
    d.puede.gasto && ["gasto", "Factura recibida", "Subir una factura o ticket imputado a esta vivienda"],
    d.puede.incidencia && ["incidencia", "Incidencia", "Abrir una incidencia o parte de trabajo con fotos"],
    d.puede.parte_estado && ["estado", "Parte de estado", "Señalar una deficiencia al revisar la vivienda"],
    S.me.gestion && ["gestion", "Gestión", "Abrir esta vivienda en INVERGESTION (órdenes de trabajo, costes)"],
  ].filter(Boolean) : [
    d.puede.reservar && ["reserva", "Reserva", garaje ? "Por días o semanas (huésped o cliente)" : "Nueva reserva en este apartamento"],
    d.puede.alquilar && !d.alquiler && ["alquiler", "Alquiler mensual", "Cliente externo: recibo cada mes y factura al 21 %"],
    d.puede.bloquear && (d.estado === "bloqueado" ? ["desbloquear", "Bloqueado", bloqueoVigente ? `Motivo: ${bloqueoVigente.motivo}. Pulse para desbloquear` : "Pulse para desbloquear"] : ["bloqueo", "Bloqueado", "Sacarlo de venta indicando el motivo"]),
    d.puede.incidencia && ["incidencia", "Incidencia", "Abrir una incidencia (avería) con fotos"],
    d.puede.parte_estado && ["estado", "Parte de estado", "Señalar una deficiencia al revisar el apartamento"],
    !garaje && S.me.gestion && ["gestion", "Gestión", "Abrir este apartamento en INVERGESTION (órdenes de trabajo, costes)"],
  ].filter(Boolean);
  const f = cerrarSolo(form(garaje ? `Plaza de garaje ${u.codigo} · ${u.bloque || ""}` : vivienda ? `Vivienda ${u.codigo} · ${assetName(u.asset_id)}` : `Apartamento ${u.codigo} · ${u.tipologia || ""}`, [
    { html: `${vivienda ? cabVivienda : `<p><span class="estado-ap pc-${d.estado}">${ESTADO_TXT[d.estado]}</span> ${u.bloque ? esc(u.bloque) + " · " : ""}planta ${esc(u.planta || "")}${u.capacidad ? ` · ${u.capacidad} plazas` : ""}${d.limpieza ? ' · <span class="badge b-pendiente_limpieza">pendiente de limpieza</span>' : ""}</p>${actual}`}
      <div class="acciones-ap">${acciones.map(([k, t, ayuda]) => `<button type="button" class="accion-ap ${k === "desbloquear" ? "marcada" : ""}" data-acc="${k}"><span class="caja">${k === "desbloquear" ? "☑" : "☐"}</span><b>${t}</b><small>${esc(ayuda)}</small></button>`).join("")}</div>
      <div class="buscador"><input type="search" placeholder="Buscar en ${vivienda ? "esta vivienda: contrato, inquilino, factura, proveedor, incidencia…" : "este apartamento: cliente, reserva, documento, incidencia, bloqueo, factura…"}" data-q>
      <div class="chips">${TIPOS.map(([t, n]) => `<button type="button" class="chip ${t ? "" : "on"}" data-t="${t}">${n}</button>`).join("")}</div></div>
      <div class="resultados" data-res></div>` },
  ], {}, async () => {}));
  $("#modal").classList.add("ancho");
  let filtroTipo = "";
  const pintaRes = () => {
    const q = normaliza($("[data-q]", f).value).split(/\s+/).filter(Boolean);
    const vis = items.filter((i) => (!filtroTipo || i.tipo === filtroTipo) && q.every((w) => normaliza(i.texto + " " + i.tipo).includes(w)));
    $("[data-res]", f).innerHTML = vis.length ? vis.slice(0, 200).map((i, n) => `<div class="res"><span class="tipo t-${i.tipo}">${i.tipo}</span><div>${i.html}</div><div class="res-acc">${i.acc.map(([l], j) => `<button type="button" class="btn sm" data-i="${items.indexOf(i)}" data-j="${j}">${esc(l)}</button>`).join("")}</div></div>`).join("")
      : `<p class="muted">${items.length ? "Sin resultados para esa búsqueda." : `${vivienda ? "Esta vivienda" : garaje ? "Esta plaza" : "Este apartamento"} aún no tiene nada registrado.`}</p>`;
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
    if (acc === "gestion") abrirGestion("unidad", u.asset_id, u.id);
    if (acc === "estado") { $("#modal").close(); irParteEstado(u.asset_id, u.id); }
    if (acc === "situacion") pedirSituacion(d, recarga);
    if (acc === "contrato") {
      const l = (d.contratos || []).find((x) => ["vigente", "borrador"].includes(x.estado));
      if (l) expediente(l, pc ? "datos" : "checklist");
      else nuevoContrato(u.asset_id, { id: u.id, codigo: u.codigo }, (lease) => { recarga && recarga(); expediente(lease, "datos"); });
    }
    if (acc === "gasto") subirDocumento(recarga, { asset_id: u.asset_id, unit_id: u.id });
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
    { html: `${z.puede.incidencia || z.puede.parte_estado ? `<div class="acciones-ap">${z.puede.incidencia ? '<button type="button" class="accion-ap" data-nueva><span class="caja">☐</span><b>Incidencia</b><small>Abrir una incidencia en esta zona común</small></button>' : ""}${z.puede.parte_estado ? '<button type="button" class="accion-ap" data-estado><span class="caja">☐</span><b>Parte de estado</b><small>Señalar una deficiencia de esta zona común</small></button>' : ""}</div>` : ""}
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
  if ($("[data-estado]", f)) $("[data-estado]", f).onclick = () => { $("#modal").close(); irParteEstado(assetId, null, z.zona); };
}

V.activos = async (el) => {
  const [rows, usuarios] = await Promise.all([get("/api/activos"), get("/api/agenda/usuarios").catch(() => [])]);
  el.innerHTML = `<div class="toolbar"><span class="spacer"></span>${can("activos.editar") ? '<button class="btn primary" id="new">Nuevo activo</button>' : ""}</div><div id="t"></div>`;
  const fields = (isNew) => [
    ...(isNew ? [{ k: "codigo", t: "Código", req: true }] : []),
    { k: "nombre", t: "Nombre", req: true },
    { k: "company_id", t: "Sociedad gestora (explotación y accesos)", type: "select", req: true, options: opts(S.companies) },
    { k: "propietaria_id", t: "Sociedad propietaria del inmueble", type: "select", options: opts(S.companies) },
    ...(isNew ? [{ k: "modalidad", t: "Modalidad", type: "select", req: true, options: kv(S.cat.modalidades) }] : []),
    { k: "direccion", t: "Dirección", wide: true }, { k: "cp", t: "Código postal" }, { k: "municipio", t: "Población" }, { k: "provincia", t: "Provincia" },
    { k: "pais", t: "País", def: "España" }, { k: "ref_catastral", t: "Ref. catastral" }, { k: "num_registro_turistico", t: "Nº registro turístico" },
    { k: "ses_codigo_establecimiento", t: "Código de establecimiento SES.HOSPEDAJE" },
    { html: "<h4>Facturación</h4><p class='muted'>Factura la sociedad gestora. Cada activo tiene su serie y la numeración es correlativa por año (p.ej. SF/00001/2026). No cambie la serie de un activo que ya tiene facturas del año en curso.</p>" },
    { k: "serie_factura", t: "Serie de facturas (p.ej. B35, SF, SA)" },
    { html: "<h4>Datos de la empresa en los contratos de alojamiento</h4>" },
    { k: "contrato_representante", t: "Representante (firma por la empresa)" }, { k: "contrato_representante_dni", t: "DNI del representante" },
    { k: "contrato_email", t: "Correo para notificaciones", type: "email" },
    { html: "<h4>Informe mensual a la presidencia</h4><p class='muted'>El primer día laborable de cada mes se avisa a quien lo revisa y envía (si no se indica, «Recepción 1» del activo). Correos: si se deja vacío, a la presidencia.</p>" },
    { k: "informe_responsable_id", t: "Revisa y envía el informe", type: "select", options: usuarios.map((u) => [u.id, u.nombre]) },
    ...(isNew ? [] : [{ html: "<h4>Recepción 1 del activo</h4><p class='muted'>Aprueba las ausencias de limpieza y conserjería, da el visto bueno a las de Recepción 2 y valida los partes. Debe tener el rol Recepción en este activo.</p>" },
      { k: "recepcion1_id", t: "Recepción 1", type: "select", options: usuarios.map((u) => [u.id, `${u.nombre} · ${u.email}`]) }]),
    { k: "informe_emails", t: "Correos de envío (separados por comas)", wide: true }, { k: "informe_whatsapp", t: "WhatsApp de envío (teléfono)" },
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
      can("activos.editar") && ["vivienda", "apartamento"].includes(u.uso) && ["Ficha alquiler", () => fichaAlquiler(u)],
      canOpenOT() && ["Avería", () => newWorkOrder(u.asset_id, u.id).then(load)],
      canParteEstado() && ["Parte de estado", () => irParteEstado(u.asset_id, u.id)],
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
async function bindServicios(f, assetId, inicial = 0, valores = []) {
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
  valores.forEach((v) => {  // líneas ya guardadas (extras de la reserva aún sin facturar)
    fila();
    const r = cont.lastElementChild;
    $("[data-s]", r).value = v.servicio_id && cat.some((x) => x.id === v.servicio_id) ? String(v.servicio_id) : "";
    $("[data-s]", r).onchange();
    $("[data-c]", r).value = v.concepto || ""; $("[data-n]", r).value = v.cantidad ?? 1;
    $("input[data-p]", r).value = v.precio ?? ""; $("select[data-i]", r).value = String(Number(v.tipo_iva ?? 21));
  });
  total();
}
function leerServicios(f) {
  return [...f.querySelectorAll(".srv-fila")].map((r) => {
    const v = (q) => $(q, r).value;
    return clean({ servicio_id: v("[data-s]") ? Number(v("[data-s]")) : null, concepto: v("[data-s]") ? null : v("[data-c]"),
      cantidad: Number(v("[data-n]") || 1), precio: v("input[data-p]") === "" ? null : Number(v("input[data-p]")), tipo_iva: Number(v("select[data-i]")) });
  }).filter((x) => x.servicio_id || x.concepto);
}
// ---- servicios extra y limpieza contratada en la reserva (pasan a la factura de la estancia)
const PERIODICIDADES = [["unica", "Un día concreto"], ["diaria", "Diaria"], ["cada_2", "Cada 2 días"], ["cada_3", "Cada 3 días"], ["semanal", "Semanal"], ["quincenal", "Quincenal"], ["otra", "Otra (indicar)"]];
const PASO_LIMPIEZA = { diaria: 1, cada_2: 2, cada_3: 3, semanal: 7, quincenal: 15 };
function fechasLimpieza(p, ent, sal) {  // igual que en el servidor: dentro de la estancia, sin entrada ni salida
  if (!p || !ent || !sal) return [];
  const dentro = (d) => d > ent && d < sal;
  if (p.periodicidad === "otra") return [...new Set(p.fechas || [])].filter(dentro).sort();
  if (!p.inicio) return [];
  if (p.periodicidad === "unica") return dentro(p.inicio) ? [p.inicio] : [];
  const out = [], paso = PASO_LIMPIEZA[p.periodicidad] || 0;
  for (let d = p.inicio; paso && d < sal; d = addDays(d, paso)) if (dentro(d)) out.push(d);
  return out;
}
function extrasHtml(r = null) {
  const fact = (r?.extras || []).filter((e) => e.factura);
  return `${fact.length ? `<p class="muted">Ya facturado: ${fact.map((e) => `${esc(e.concepto)} (${esc(e.factura)})`).join(" · ")}</p>` : ""}
    ${serviciosHtml("Servicios extra que pide el cliente (plaza extra, toallas…): se facturan aparte de la estancia")}
    <fieldset class="limpieza-plan"><legend>Limpieza contratada</legend>
      <label class="check"><input type="checkbox" data-lp-on> El cliente contrata limpieza durante la estancia</label>
      <div data-lp style="display:none"><div class="grid">
        <label>Servicio<select data-lp-srv><option value="">— Otro (escribir) —</option></select></label>
        <label data-lp-concepto-l>Concepto<input data-lp-concepto value="Limpieza"></label>
        <label>Precio por limpieza € (IVA incl.)<input data-lp-precio type="number" step="0.01" min="0"></label>
        <label>Periodicidad<select data-lp-per>${PERIODICIDADES.map(([k, t]) => `<option value="${k}">${t}</option>`).join("")}</select></label>
        <label data-lp-inicio-l>Día de la (primera) limpieza<input data-lp-inicio type="date"></label>
        <label data-lp-texto-l style="display:none">Indique la periodicidad *<input data-lp-texto maxlength="120" placeholder="p.ej. martes y viernes"></label>
        <label data-lp-dia-l style="display:none">Añadir día<span class="fila-dia"><input data-lp-dia type="date"><button type="button" class="btn sm" data-lp-add>Añadir</button></span></label>
      </div><div class="chips" data-lp-dias></div><p class="muted" data-lp-res></p></div></fieldset>`;
}
// fechas(): {fecha_entrada, fecha_salida} actuales del formulario
async function bindExtras(f, assetId, r, fechas) {
  const cat = await get("/api/servicios", { asset_id: assetId });
  await bindServicios(f, assetId, 0, (r?.extras || []).filter((e) => !e.factura && !e.limpieza));
  const q = (s) => $(s, f), p = r?.limpieza || null;
  let dias = [...(p?.fechas || [])];
  q("[data-lp-srv]").insertAdjacentHTML("beforeend", cat.map((x) => `<option value="${x.id}" data-precio="${x.precio ?? ""}">${esc(x.nombre)}${x.precio != null ? " · " + eur(x.precio) : ""}</option>`).join(""));
  const lim = cat.find((x) => /limpieza/i.test(x.nombre));
  q("[data-lp-srv]").value = p?.servicio_id ? String(p.servicio_id) : lim && !p ? String(lim.id) : "";
  if (p) { q("[data-lp-precio]").value = p.precio ?? ""; q("[data-lp-concepto]").value = p.concepto || "Limpieza"; q("[data-lp-per]").value = p.periodicidad; q("[data-lp-inicio]").value = p.inicio || ""; q("[data-lp-texto]").value = p.texto || ""; }
  else if (lim?.precio != null) q("[data-lp-precio]").value = lim.precio;
  q("[data-lp-on]").checked = !!p;
  const plan = () => ({ periodicidad: q("[data-lp-per]").value, inicio: q("[data-lp-inicio]").value || null, texto: q("[data-lp-texto]").value.trim() || null, fechas: dias });
  const pinta = () => {
    const on = q("[data-lp-on]").checked, otra = q("[data-lp-per]").value === "otra";
    q("[data-lp]").style.display = on ? "" : "none";
    q("[data-lp-concepto-l]").style.display = q("[data-lp-srv]").value ? "none" : "";
    q("[data-lp-inicio-l]").style.display = otra ? "none" : "";
    q("[data-lp-texto-l]").style.display = q("[data-lp-dia-l]").style.display = otra ? "" : "none";
    q("[data-lp-dias]").innerHTML = otra ? dias.map((d, i) => `<button type="button" class="chip on" data-quita="${i}" title="Quitar">${fdate(d)} ✕</button>`).join("") : "";
    f.querySelectorAll("[data-quita]").forEach((b) => (b.onclick = () => { dias.splice(Number(b.dataset.quita), 1); pinta(); }));
    const { fecha_entrada: ent, fecha_salida: sal } = fechas();
    const fs = fechasLimpieza(plan(), ent, sal), precio = Number(q("[data-lp-precio]").value || 0);
    q("[data-lp-res]").innerHTML = !on ? "" : fs.length ? `<b>${fs.length} limpieza${fs.length === 1 ? "" : "s"}</b>: ${fs.map((d) => fdate(d).slice(0, 5)).join(", ")}${precio ? ` · ${eur(precio * fs.length)}` : ""}. Saldrán en el parte de limpieza de cada día.`
      : '<span class="error">Elija un día dentro de la estancia (sin el día de entrada ni el de salida).</span>';
  };
  q("[data-lp-srv]").onchange = () => { const o = q("[data-lp-srv]").selectedOptions[0]; if (o?.dataset.precio) q("[data-lp-precio]").value = o.dataset.precio; pinta(); };
  q("[data-lp-add]").onclick = () => { const d = q("[data-lp-dia]").value; if (d && !dias.includes(d)) dias.push(d); dias.sort(); pinta(); };
  f.querySelectorAll("[data-lp-on],[data-lp-per],[data-lp-inicio],[data-lp-precio]").forEach((i) => (i.oninput = i.onchange = pinta));
  ["fecha_entrada", "fecha_salida"].forEach((k) => f.elements[k] && f.elements[k].addEventListener("change", pinta));
  pinta();
  f._extras = () => {
    const out = { extras: leerServicios(f) };
    if (q("[data-lp-on]").checked) {
      const pl = plan(), { fecha_entrada: ent, fecha_salida: sal } = fechas();
      if (pl.periodicidad === "otra" && !pl.texto) throw new Error("Indique la periodicidad de la limpieza");
      if (!fechasLimpieza(pl, ent, sal).length) throw new Error("Elija un día de limpieza dentro de la estancia");
      const srv = q("[data-lp-srv]").value;
      out.limpieza = clean({ ...pl, servicio_id: srv ? Number(srv) : null, concepto: srv ? null : q("[data-lp-concepto]").value || "Limpieza",
        precio: q("[data-lp-precio]").value === "" ? null : Number(q("[data-lp-precio]").value), fechas: pl.periodicidad === "otra" ? pl.fechas : [] });
    } else if (p) out.quitar_limpieza = true;
    return out;
  };
}
// Factura solo de los servicios extra pendientes (pedidos con la estancia ya pagada)
function facturarExtras(r, reload) {
  const pend = (r.extras || []).filter((e) => !e.factura);
  form(`Servicios extra · reserva ${r.localizador || r.id} · ${r.unidad}`, [
    { html: `<ul>${pend.map((e) => `<li>${esc(e.concepto)} · ${e.cantidad} × ${eur(e.precio)}</li>`).join("")}</ul><p><b>Total: ${eur(r.extras_pendientes)}</b> (IVA incluido)</p>` },
    { k: "cobrado", t: "Cobrado ahora (si no, la factura queda pendiente de cobro)", type: "checkbox", def: true, wide: true },
    { k: "forma_pago", t: "Forma de pago", type: "select", options: kv(S.cat.formas_pago) },
  ], {}, async (d) => {
    const x = await post(`/api/turistico/reservas/${r.id}/extras/factura`, clean(d));
    toast(`Factura ${x.factura.codigo} emitida`); reload && reload(); setTimeout(() => facturasEmitidas(x), 0);
  }, "Emitir factura");
}
// Facturas recién emitidas (la de la estancia y, aparte, la de servicios): imprimir o enviar al cliente
async function facturasEmitidas(resp, despues = null) {
  const fs = resp.facturas || (resp.factura ? [resp.factura] : []);
  if (!fs.length) return despues && despues();
  const g = resp.guest_id ? await get(`/api/terceros/${resp.guest_id}`).catch(() => ({})) : {};
  const varias = fs.length > 1;
  const f = form(varias ? "Facturas emitidas: estancia y servicios" : `Factura ${fs[0].codigo} emitida`, [
    { html: `${varias ? '<p class="muted">La estancia y los servicios van en facturas separadas (control de la gestoría).</p>' : ""}
      <ul class="envios">${fs.map((x) => `<li><b>${esc(x.codigo)}</b> · ${x.tipo === "servicios" ? "Servicios" : "Estancia"}${x.total != null ? " · " + eur(x.total) : ""}${x.cobro === "pendiente" ? ' <span class="badge b-pendiente">pendiente de cobro</span>' : ""}
        <button type="button" class="btn sm" data-imp="${x.id}">Imprimir</button></li>`).join("")}</ul>
      ${varias ? '<button type="button" class="btn" data-todas>Imprimir las dos</button>' : ""}<h4>Enviar al cliente</h4>` },
    { k: "canal", t: "Enviar por", type: "select", options: [["email", "Correo (con los PDF)"], ["whatsapp", "WhatsApp (enlace de descarga, 7 días)"]], def: g.email ? "email" : "whatsapp" },
    { k: "email", t: "Correo del cliente", type: "email", def: g.email || "" }, { k: "telefono", t: "Móvil del cliente", def: g.telefono || "" },
  ], {}, async (d) => {
    const r = await post("/api/facturas/enviar", { factura_ids: fs.map((x) => x.id), canal: d.canal, email: d.email || null, telefono: d.telefono || null });
    if (r.whatsapp) window.open(r.whatsapp, "_blank", "noopener");
    toast(r.canal === "email" ? `Enviada${varias ? "s" : ""} por correo a ${r.destino}` : "WhatsApp abierto con el mensaje: pulse «Enviar»");
    if (despues) setTimeout(despues, 0);
  }, varias ? "Enviar las dos" : "Enviar");
  f.querySelectorAll("[data-imp]").forEach((b) => (b.onclick = () => descargarFactura(Number(b.dataset.imp))));
  if ($("[data-todas]", f)) $("[data-todas]", f).onclick = async () => { for (const x of fs) await descargarFactura(x.id); };
  $("#fCancel").textContent = despues ? "No enviar y continuar" : "Cerrar";
  $("#fCancel").onclick = () => { $("#modal").close(); if (despues) despues(); };
}
// sinCobro: se factura ya y la factura queda «pendiente de cobro» (ampliaciones de reserva y reservas que pagan por transferencia)
function cobroForm(titulo, pendiente, url, reload, assetId, sinCobro = false, despues = null, reserva = null) {
  const pendExtras = (reserva?.extras || []).filter((e) => !e.factura);
  const f = form(titulo, [
    ...(pendExtras.length ? [{ html: `<p class="aviso-amarillo">Servicios extra pedidos por el cliente: ${pendExtras.map((e) => `${esc(e.concepto)} (${e.cantidad} × ${eur(e.precio)})`).join(" · ")} · <b>${eur(reserva.extras_pendientes)}</b></p>` },
      { k: "incluir_extras", t: "Facturarlos ahora (en una factura de servicios aparte de la estancia)", type: "checkbox", def: true, wide: true }] : []),
    ...(sinCobro ? [{ html: '<p class="aviso-faltan">La factura se emite <b>sin cobrar</b>: queda <b>pendiente de cobro</b>, recepción la revisa cada día y la marca <b>cobrada</b> cuando llegue la transferencia (Facturas emitidas → Cobrada).</p>' }] : []),
    { k: "importe", t: sinCobro ? "Importe a facturar € (IVA incluido)" : pendiente > 0 ? "Importe cobrado € (IVA incluido)" : "Importe cobrado € (nada pendiente)", type: "number", req: true },
    ...(sinCobro ? [] : [{ k: "fecha_pago", t: "Fecha del cobro", type: "date", def: today() }]),
    { k: "forma_pago", t: sinCobro ? "Forma de pago prevista" : "Forma de pago", type: "select", options: kv(S.cat.formas_pago), def: sinCobro ? "transferencia" : undefined },
    ...(assetId ? [{ html: serviciosHtml("Servicios (limpieza, aparcamiento…): se emite una factura de servicios aparte") }] : []),
    { k: "otra", t: "Facturar a una empresa u otra persona (no al cliente)", type: "checkbox", wide: true },
    { k: "fa_nombre", t: "Razón social / nombre" }, { k: "fa_nif", t: "CIF / NIF" }, { k: "fa_domicilio", t: "Domicilio fiscal completo", wide: true },
    { html: `<p class="muted">${sinCobro ? "Se emite" : "Al registrar el cobro se emite"} la factura con el siguiente número de la serie del activo y se descarga en PDF. Una factura emitida no se puede modificar: si hay un error, Administración emite una rectificativa.</p>` },
  ], { importe: Math.max(0, pendiente) }, async (d, fr) => {
    const body = { importe: d.importe || 0, fecha_pago: d.fecha_pago, forma_pago: d.forma_pago, servicios: leerServicios(fr),
      incluir_extras: pendExtras.length ? !!d.incluir_extras : undefined };
    if (d.otra) body.facturar_a = { nombre: d.fa_nombre, nif: d.fa_nif, domicilio: d.fa_domicilio };
    const soloExtras = !body.importe && !body.servicios.length && body.incluir_extras;  // nada más que los extras
    const r = await post(soloExtras ? url.replace(/\/cobro$/, "/extras/factura") : sinCobro ? url.replace(/\/cobro$/, "/facturar") : url,
      clean(soloExtras ? { cobrado: !sinCobro, fecha_pago: d.fecha_pago, forma_pago: d.forma_pago, facturar_a: body.facturar_a } : body));
    const codigos = (r.facturas || [r.factura]).map((x) => x.codigo).join(" y ");
    toast(sinCobro ? `Factura ${codigos} emitida · pendiente de cobro` : `Cobro registrado · Factura ${codigos}`);
    reload && reload();
    setTimeout(() => facturasEmitidas(r, despues), 0);
  }, sinCobro ? "Emitir factura pendiente de cobro" : "Registrar cobro y facturar");
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
      Math.round((r.importe_total - r.importe_pagado) * 100) / 100, `/api/turistico/reservas/${r.id}/cobro`, reload, r.asset_id, false, null, r)],
    r.importe_total - r.importe_pagado > 0.004 && ["Facturar sin cobrar", () => cobroForm(`Facturar sin cobrar · reserva ${r.localizador || r.id} · ${r.unidad}`,
      Math.round((r.importe_total - r.importe_pagado) * 100) / 100, `/api/turistico/reservas/${r.id}/cobro`, reload, r.asset_id, true, null, r)],
    r.extras_pendientes > 0 && ["Facturar extras", () => facturarExtras(r, reload)],
    r.estado === "confirmada" && ["Check-in", async () => {
      if (r.uso !== "garaje") {  // la dotación estándar del apartamento es obligatoria (reservas de antes de fijarla)
        const d = await get(`/api/dotacion/unidad/${r.unit_id}`).catch(() => ({ fijada: true }));
        if (!d.fijada) { alert(`Antes del check-in fije la dotación estándar de los apartamentos «${d.tipologia || "sin tipología"}» (Reservas → Dotación habitual). Solo se hace una vez por tipo de apartamento.`); return dotacionHabitual(); }
      }
      return run(() => post(`/api/turistico/reservas/${r.id}/checkin`), "Check-in realizado").then((x) => { reload && reload(); accesoTrasCheckin(x, reload); }).catch(() => ocupantesReserva(r, reload));
    }],
    ["confirmada", "checkin"].includes(r.estado) && r.uso !== "garaje" && ["Ampliar reserva", () => renovarEstancia(r, reload)],
    ["confirmada", "checkin"].includes(r.estado) && r.uso !== "garaje" && !r.fianza_cobro && ["Cobrar fianza", () => cobrarFianza(r, reload)],
    r.estado === "checkin" && ["Check-out", () => salidaReserva(r, reload)],
    r.uso !== "garaje" && ["confirmada", "checkin"].includes(r.estado) && ["Dotación", () => dotacionReserva(r)],
    ["Huésped", () => editGuest(r.guest_id)],
    ["Editar", () => editReservation(r, reload)],
    ["confirmada", "checkin"].includes(r.estado) && ["Anular", () => anular("la reserva", "anulada", `/api/turistico/reservas/${r.id}/anular`, reload), "danger"],
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
    { k: "dotacion", t: "Dotación habitual: imprimir o enviar con el contrato el Anexo I (inventario y dotación del apartamento, con la dotación especial de esta reserva)", type: "checkbox", wide: true },
    { html: `<p class="muted">Para cambiar la dotación de esta reserva (quitar, añadir u «Otra dotación») use el botón «Dotación» de la reserva.</p>` },
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
  { k: "cp", t: "Código postal" }, { k: "municipio", t: "Población" }, { k: "provincia", t: "Provincia" }, { k: "pais", t: "País" },
];
function unidadesHtml(c) {
  const u = c.unidades || [];
  if (!u.length) return `<p class="muted">Sin apartamentos ni plazas en este momento${c.n_estancias ? ` · ${c.n_estancias} estancia(s) en total` : ""}.</p>`;
  return `<fieldset><legend>Tiene ${c.n_apartamentos} apartamento(s)${u.length > c.n_apartamentos ? ` y ${u.length - c.n_apartamentos} plaza(s) de garaje` : ""}${c.n_estancias ? ` · ${c.n_estancias} estancia(s) en total` : ""}</legend>
    <ul class="envios">${u.map((x) => `<li><b>${esc(x.codigo)}</b> · ${esc(x.activo)} · ${x.tipo === "reserva" ? `reserva ${esc(x.localizador || "")} (${x.estado === "checkin" ? "alojado" : "confirmada"})` : `contrato ${esc(x.localizador || "")}`} · ${fdate(x.desde)} → ${x.hasta ? fdate(x.hasta) : "indefinido"}</li>`).join("")}</ul></fieldset>`;
}
// facturación del programa anterior (SYADE) del cliente, cruzada por su documento: solo control de producción
const HIST_TIPO = { alojamiento: "Alojamiento", servicio: "Servicios", abono: "Abono", fianza_devuelta: "Fianza devuelta" };
function historicoHtml(c) {
  const h = c.historico;
  if (!h) return "";
  return `<fieldset><legend>Facturación del programa anterior (SYADE) · control de producción</legend>
    <p>${h.facturas} factura(s)${h.abonos ? ` y ${h.abonos} abono(s)` : ""} · ${fdate(h.desde)} → ${fdate(h.hasta)}</p>
    <div class="table-wrap"><table><tbody>
      <tr><td>Alojamiento (base)</td><td class="num">${eur(h.alojamiento)}</td></tr>
      <tr><td>Servicios (base)</td><td class="num">${eur(h.servicios)}</td></tr>
      <tr class="total"><td><b>Producción (base)</b></td><td class="num"><b>${eur(h.produccion)}</b></td></tr>
      <tr><td>Total con IVA</td><td class="num">${eur(h.total)}</td></tr>
      ${h.fianzas_cobradas || h.fianzas_devueltas ? `<tr><td>Fianzas cobradas / devueltas</td><td class="num">${eur(h.fianzas_cobradas)} / ${eur(h.fianzas_devueltas)}</td></tr>` : ""}
    </tbody></table></div>
    <details><summary>Ver las ${h.detalle.length} líneas</summary><div class="table-wrap"><table><thead><tr><th>Fecha</th><th>Tipo</th><th>Factura</th><th>Localizador</th><th class="num">Base</th><th class="num">Total</th><th class="num">Fianza</th><th>Enlazado por</th></tr></thead><tbody>
      ${h.detalle.map((x) => `<tr><td>${fdate(x.fecha)}</td><td>${HIST_TIPO[x.tipo] || esc(x.tipo)}</td><td>${esc(x.factura)}</td><td>${esc(x.localizador || "")}</td><td class="num">${eur(x.base)}</td><td class="num">${eur(x.total)}</td><td class="num">${x.fianza ? eur(x.fianza) : "—"}</td><td>${{ documento: "DNI/NIF", nombre: "nombre", reserva: "reserva" }[x.enlace] || ""}</td></tr>`).join("")}
    </tbody></table></div></details>
    <p class="muted">Datos del programa anterior, enlazados por el DNI/NIF del cliente o, si no lo tiene, por su nombre y apellidos. No son facturas del PMS: la facturación válida para Hacienda empieza el 1 de enero de 2027.</p></fieldset>`;
}
// aviso en la ficha: otra ficha del mismo activo con el mismo nombre. Se unen, o se indica que no es la misma persona
function repetidasHtml(c) {
  if (!c.repetidas || !c.repetidas.length) return "";
  return `<div class="aviso-vencidas"><b>Hay ${c.repetidas.length} ficha(s) más con el mismo nombre.</b>
    <ul>${c.repetidas.map((o) => `<li>Ficha ${o.id}: ${esc(o.documento_num || "sin documento")} · ${esc(o.telefono || "sin teléfono")} · ${esc(o.email || "sin correo")}</li>`).join("")}</ul>
    Si es la misma persona, únalas. Si solo coincide el nombre, pulse «No es la misma persona» y el aviso desaparece.
    <div class="toolbar"><button type="button" class="btn sm" data-distinta>No es la misma persona</button><button type="button" class="btn sm primary" data-unir>Unir fichas</button></div></div>`;
}
function bindRepetidas(f, c, tipo, onSaved) {
  if (!$("[data-distinta]", f)) return;
  const volver = () => { onSaved && onSaved(); editGuest(c.id, tipo, onSaved); };
  $("[data-distinta]", f).onclick = async () => {
    await run(() => post("/api/terceros/distintos", { ids: [c.id, ...c.repetidas.map((o) => o.id)] }), "Hecho: ya no se avisará de estas fichas");
    volver();
  };
  $("[data-unir]", f).onclick = async () => {
    const g = (await run(() => get("/api/terceros/duplicados", { tipo }))).filter((x) => x.fichas.some((o) => o.id === c.id));
    unirFichas(g, () => onSaved && onSaved());
  };
}
async function editGuest(id, tipo = "huesped", onSaved) {
  const c = await get(`/api/terceros/${id}`).catch(() => null);
  if (!c) return toast("Cliente no encontrado", true);
  const f = form(`${{ huesped: "Huésped", cliente_garaje: "Cliente de garaje" }[tipo] || "Inquilino"}: ${c.nombre} ${c.apellidos || ""}${c.activo ? ` · ${c.activo}` : ""}`.trim(), [{ html: listaNegraHtml(c) }, { html: repetidasHtml(c) }, { html: `<div class="toolbar"><button type="button" class="btn sm primary" data-expediente>Expediente completo: estancias, contratos, facturas y fianzas</button>${can("reservas.editar") ? `<button type="button" class="btn sm ${c.lista_negra ? "" : "danger"}" data-negra>${c.lista_negra ? "Quitar de la lista negra" : "Lista negra"}</button>` : ""}</div>` }, { html: unidadesHtml(c) }, { html: historicoHtml(c) }, { html: scanHtml() }, ...guestFields, { k: "iban", t: "IBAN" }, { k: "notas", t: "Notas", type: "textarea", wide: true }], c,
    async (d) => { await put(`/api/terceros/${id}`, { ...d, company_id: c.company_id, tipo: c.tipo }); toast("Datos guardados"); onSaved && onSaved(); });
  bindScan(f, id, (lec) => rellenaFicha(f, lec));
  bindRepetidas(f, c, c.tipo, onSaved);
  $("[data-expediente]", f).onclick = () => expedienteCliente(c, () => editGuest(id, tipo, onSaved));
  const bn = $("[data-negra]", f);
  if (bn) bn.onclick = () => listaNegraForm(c, () => { onSaved && onSaved(); editGuest(id, tipo, onSaved); });
}

// ---- lista negra de clientes: la anotan Recepción 1, Recepción 2 o la Dirección; sale al volver a reservar
function listaNegraHtml(c) {
  const av = c.lista_negra_avisos || [];
  if (!av.length) return "";
  return `<div class="aviso-negra"><b>⛔ CLIENTE EN LISTA NEGRA</b><ul>${av.map((x) => `<li><b>${esc(x.motivo || "")}</b> · ${esc(x.activo || "grupo")} · ${esc(x.autor || "—")} · ${fdate(x.fecha)}</li>`).join("")}</ul></div>`;
}
async function avisoListaNegra(el, q) {
  const av = await get("/api/lista-negra/comprobar", q).catch(() => []);
  if (av.length) el.insertAdjacentHTML("beforeend", listaNegraHtml({ lista_negra_avisos: av }));
}
function listaNegraForm(c, onSaved) {
  if (c.lista_negra) {
    if (!confirm(`¿Quitar a ${c.nombre} ${c.apellidos || ""} de la lista negra?`)) return;
    return run(() => put(`/api/terceros/${c.id}/lista-negra`, { activa: false }), "Quitado de la lista negra").then(onSaved);
  }
  form(`Lista negra · ${c.nombre} ${c.apellidos || ""}`, [
    { html: `<p>Si este cliente vuelve a pedir una reserva (en cualquier activo, con el mismo documento), Recepción verá este <b>motivo</b> antes de confirmarla.</p>` },
    { k: "motivo", t: "Motivo (impago, desperfectos, molestias, conducta…)", type: "textarea", req: true, wide: true },
  ], {}, async (d) => { await put(`/api/terceros/${c.id}/lista-negra`, { activa: true, motivo: d.motivo }); toast("Anotado en la lista negra"); onSaved && onSaved(); }, "Incluir en la lista negra");
}
async function listaNegra() {
  const l = await run(() => get("/api/lista-negra"));
  const f = cerrarSolo(form(`Lista negra de clientes (${l.length})`, [{ html: `<p class="muted">Clientes anotados por Recepción 1, Recepción 2 o la Dirección. Al reservar de nuevo sale el motivo.</p><div data-t></div>` }], {}, async () => {}));
  $("#modal").classList.add("ancho");
  table($("[data-t]", f), [{ k: "nombre", t: "Cliente" }, { k: "documento_num", t: "Documento" }, { k: "activo", t: "Activo" },
    { k: "motivo", t: "Motivo" }, { k: "autor", t: "Anotado por" }, { k: "fecha", t: "Fecha", f: fdate }], l,
  (c) => [["Ficha", () => editGuest(c.id, "huesped")]]);
}

// ---- expediente del cliente: todo en un sitio para gestionar cliente y apartamento sin buscar
const ESTADO_RES = { confirmada: "Confirmada", checkin: "Alojado", checkout: "Salida hecha", cancelada: "Anulada", no_show: "No presentado" };
async function expedienteCliente(c, volver) {
  const e = await run(() => get(`/api/terceros/${c.id}/expediente`));
  const docs = await get(`/api/terceros/${c.id}/documentos`).catch(() => []);
  const t = (cab, filas) => filas.length ? `<div class="table-wrap"><table><thead><tr>${cab.map((x) => `<th>${x}</th>`).join("")}</tr></thead><tbody>${filas.join("")}</tbody></table></div>` : '<p class="muted">Nada registrado.</p>';
  const f = cerrarSolo(form(`Expediente · ${c.nombre} ${c.apellidos || ""}`, [
    { html: listaNegraHtml({ lista_negra_avisos: e.lista_negra }) },
    { html: `<fieldset><legend>Estancias (${e.reservas.length})</legend>${t(["Reserva", "Activo · apto.", "Fechas", "Estado", "Importe / cobrado", "Fianza", ""], e.reservas.map((r) =>
      `<tr><td>${esc(r.localizador || r.id)}${r.amplia ? ' <span class="badge b-pendiente">ampliación</span>' : ""}${r.titular ? "" : ' <span class="muted">(ocupante)</span>'}</td><td>${esc(r.activo)} · <b>${esc(r.unidad)}</b>${r.tipologia ? ` <span class="muted">${esc(r.tipologia)}</span>` : ""}</td>
      <td>${fdate(r.entrada)} → ${fdate(r.salida)}</td><td>${ESTADO_RES[r.estado] || esc(r.estado)}</td><td class="num">${eur(r.importe_total)} / ${eur(r.importe_pagado)}</td>
      <td>${r.fianza ? `${eur(r.fianza)}${r.devolucion ? ` · ${esc(r.devolucion.forma_texto)} (${r.devolucion.estado})` : ""}` : "—"}</td>
      <td><button type="button" class="btn sm" data-res="${r.id}">Gestionar</button></td></tr>`))}</fieldset>` },
    { html: `<fieldset><legend>Contratos de alojamiento (${e.contratos.length})</legend>${t(["Reserva", "Fecha", "Firma", ""], e.contratos.map((k) =>
      `<tr><td>${esc(k.localizador || k.reserva_id)}</td><td>${fdate(k.creado)}</td><td>${k.firmado ? `✔ firmado ${fdate(k.firmado)}` : "impreso"}</td>
      <td><button type="button" class="btn sm" data-con="${k.reserva_id}:${k.id}:${k.firmado ? 1 : 0}">${k.firmado ? "PDF firmado" : "Reimprimir"}</button></td></tr>`))}</fieldset>` },
    { html: `<fieldset><legend>Facturas (${e.facturas.length})</legend>${t(["Factura", "Fecha", "Total", "Cobro", ""], e.facturas.map((x) =>
      `<tr><td>${esc(x.codigo)}${x.tipo === "rectificativa" ? " (rect.)" : ""}</td><td>${fdate(x.fecha)}</td><td class="num">${eur(x.total)}</td><td>${x.cobro === "pendiente" ? '<span class="badge b-pendiente">pendiente</span>' : "cobrada"}</td>
      <td><button type="button" class="btn sm" data-fac="${x.id}">PDF</button></td></tr>`))}</fieldset>` },
    { html: `<fieldset><legend>Fianzas (${e.fianzas.length})</legend>${t(["Reserva", "Fianza", "Devuelto", "Forma", "Fecha", "Estado"], e.fianzas.map((x) =>
      `<tr><td>${esc(x.localizador || "")} · ${esc(x.unidad)}</td><td class="num">${eur(x.fianza)}</td><td class="num">${eur(x.importe)}${x.retenido ? ` <span class="muted">(retenido ${eur(x.retenido)}: ${esc(x.retenido_motivo || "")})</span>` : ""}</td>
      <td>${esc(x.forma_texto)}</td><td>${fdate(x.devuelta_fecha || x.fecha)}</td><td>${x.estado === "devuelta" ? "✔ devuelta" : '<span class="badge b-pendiente">transferencia pendiente</span>'}</td></tr>`))}</fieldset>` },
    ...(e.alquileres.length ? [{ html: `<fieldset><legend>Alquileres (${e.alquileres.length})</legend>${t(["Contrato", "Vivienda", "Periodo", "Renta", "Estado"], e.alquileres.map((l) =>
      `<tr><td>${esc(l.referencia || l.id)}</td><td>${esc(l.activo)} · ${esc(l.unidad)}</td><td>${fdate(l.inicio)} → ${l.fin ? fdate(l.fin) : "indefinido"}</td><td class="num">${eur(l.renta)}</td><td>${esc(l.estado)}</td></tr>`))}</fieldset>` }] : []),
    { html: `<fieldset><legend>Documentos escaneados (${docs.length})</legend>${docs.length ? `<ul class="envios">${docs.map((d) => `<li><a href="#" data-doc="${d.id}">${esc(d.nombre || d.tipo || "Documento")}</a> · ${fdate(d.creado || d.fecha)}</li>`).join("")}</ul>` : '<p class="muted">Sin documentos.</p>'}</fieldset>` },
    { html: `<div class="toolbar"><button type="button" class="btn" data-volver>← Volver a la ficha</button></div>` },
  ], {}, async () => {}));
  $("#modal").classList.add("ancho");
  $("[data-volver]", f).onclick = () => volver && volver();
  f.querySelectorAll("[data-fac]").forEach((b) => (b.onclick = () => abrirFichero(`/api/facturas/${b.dataset.fac}/pdf`)));
  f.querySelectorAll("[data-doc]").forEach((a) => (a.onclick = (ev) => { ev.preventDefault(); abrirFichero(`/api/documentos/${a.dataset.doc}`); }));
  f.querySelectorAll("[data-con]").forEach((b) => (b.onclick = () => {
    const [rid, cid, firmado] = b.dataset.con.split(":");
    return firmado === "1" ? abrirFichero(`/api/turistico/reservas/${rid}/contrato/${cid}/pdf`) : run(() => download("GET", `/api/turistico/reservas/${rid}/contrato/${cid}`));
  }));
  f.querySelectorAll("[data-res]").forEach((b) => (b.onclick = async () => {
    const r = await run(() => get(`/api/turistico/reservas/${b.dataset.res}`));
    const acc = resActions(() => expedienteCliente(c, volver))(r).filter(Boolean);
    const g = cerrarSolo(form(`Reserva ${r.localizador || r.id} · ${r.unidad} · ${ESTADO_RES[r.estado] || r.estado}`, [
      { html: `<p>${fdate(r.fecha_entrada)} → ${fdate(r.fecha_salida)} · ${eur(r.importe_total)} (cobrado ${eur(r.importe_pagado)})</p><div class="toolbar">${acc.map(([l, , cls], i) => `<button type="button" class="btn sm ${cls || ""}" data-i="${i}">${esc(l)}</button>`).join("")}</div>` },
      { html: `<div class="toolbar"><button type="button" class="btn" data-atras>← Expediente</button></div>` }], {}, async () => {}));
    g.querySelectorAll("[data-i]").forEach((x) => (x.onclick = () => acc[x.dataset.i][1]()));
    $("[data-atras]", g).onclick = () => expedienteCliente(c, volver);
  }));
}

// lo que se repone comprándolo (menaje, ropa de cama y baño): va al pedido de reposición; lo demás, a mantenimiento
const seRepone = (x) => x.zona === "menaje" || /^(BAN(07|09|10|11|12)|DOR(06|08|09|10|11|12))$/.test(x.codigo || "");
// ---- fianza cobrada al llegar (cuenta en la caja del turno y es la que se devuelve a la salida)
async function cobrarFianza(r, reload) {
  const info = await run(() => get(`/api/turistico/reservas/${r.id}/fianza`));
  form(`Cobrar fianza · ${r.unidad} · ${info.titular}`, [
    { html: `<p class="muted">Anote la fianza que entrega el cliente al llegar. Entra en su caja del turno y es la que se devuelve al dar la salida, aunque no se haya guardado el contrato.</p>` },
    { k: "importe", t: "Importe €", type: "number", step: "0.01", req: true, def: info.fianza || "" },
    { k: "forma", t: "Forma", type: "select", req: true, options: kv(info.formas_cobro) },
    { k: "referencia", t: "Referencia (nº de operación del datáfono, si lo hay)" },
  ], {}, async (d) => { await post(`/api/turistico/reservas/${r.id}/fianza/cobro`, clean(d)); toast("Fianza cobrada"); reload && reload(); }, "Cobrar fianza");
}
const saldoTxt = (s) => [s.estancia > 0.004 && `estancia ${eur(s.estancia)}`, s.extras > 0.004 && `servicios sin facturar ${eur(s.extras)}`,
  ...s.facturas.map((x) => `factura ${x.codigo} ${eur(x.importe)}`)].filter(Boolean).join(" · ");
// ---- salida del apartamento con la devolución de la fianza (si procede)
async function salidaReserva(r, reload, preguntar = false) {
  const info = await run(() => get(`/api/turistico/reservas/${r.id}/fianza`));
  if (info.saldo && info.saldo.total > 0.004 && !confirm(`ATENCIÓN: el cliente tiene ${eur(info.saldo.total)} pendiente de pago (${saldoTxt(info.saldo)}).\n\n¿Dar la salida igualmente? Si no, cancele y cobre antes.`)) return;
  preguntar = preguntar && !(info.saldo && info.saldo.total > 0.004);  // ya se ha confirmado
  if (!info.procede) {
    if (preguntar && !confirm(`¿Dar la salida a ${r.huesped} (${r.unidad})?`)) return;
    return run(() => post(`/api/turistico/reservas/${r.id}/checkout`), "Salida realizada").then(reload);
  }
  const dot = await get(`/api/turistico/reservas/${r.id}/dotacion`).catch(() => ({ items: [] }));
  const cargos = [];
  const f = form(`Salida y devolución de fianza · ${r.unidad} · ${info.titular}`, [
    { html: `<div class="aviso-vencidas"><b>Devolución de fianza: ${eur(info.fianza)}</b>${info.cobro ? ` <span class="muted">(cobrada el ${fdt(info.cobro.fecha)} · ${esc(info.formas_cobro[info.cobro.forma] || info.cobro.forma)})</span>` : ""}<br>Cliente: <b>${esc(info.titular)}</b>. Indique cómo se devuelve según las indicaciones de Recepción 1 o Recepción 2.
      Si es por <b>transferencia</b>, los datos se envían por correo y WhatsApp a la Dirección (${info.avisos.map(esc).join(" y ")}) para hacerla.</div>` },
    { k: "forma", t: "Forma de devolución", type: "select", req: true, options: kv(info.formas) },
    { html: `<fieldset><legend>Roturas y faltas (se descuentan a su precio de reposición)</legend>
      <div class="toolbar"><select data-art><option value="">Elija el artículo de la dotación…</option>${dot.items.map((x, i) => `<option value="${i}">${esc(x.articulo)}${x.precio ? ` · ${eur(x.precio)}` : ""}</option>`).join("")}<option value="otro">Otro (escribir)…</option></select>
      <input data-cant type="number" min="1" value="1" style="width:5em"><button type="button" class="btn sm" data-add>+ Añadir</button>
      <button type="button" class="btn sm" data-hoja>Hoja de revisión (PDF)</button><button type="button" class="btn sm" data-movil>Revisión en el móvil de limpieza</button></div>
      ${info.revision ? `<p class="cli-ok">✔ Revisado por <b>${esc(info.revision.nombre)}</b> (${new Date(info.revision.fecha).toLocaleString("es-ES")}): lo marcado ya está cargado abajo.${info.revision.nota ? ` Nota: ${esc(info.revision.nota)}` : ""}</p>` : ""}
      <div data-cargos></div><label class="check" data-exc style="display:none"><input type="checkbox" name="facturar_exceso" checked> Facturar al cliente lo que supera la fianza (sin IVA: indemnización; queda pendiente de cobro)</label></fieldset>` },
    { k: "importe", t: "Importe a devolver €", type: "number", def: info.fianza, step: "0.01" },
    { k: "retenido_motivo", t: "Motivo si se retiene algo más (las roturas de la lista ya van detalladas)", type: "textarea", wide: true },
    { k: "iban", t: "IBAN de la cuenta del cliente", def: info.iban || "", wide: true },
    { k: "fecha", t: "Fecha de la transferencia / devolución", type: "date", def: today() },
    { k: "nota", t: "Nota para la Dirección", type: "textarea", wide: true },
  ], {}, async (d) => {
    const facturar_exceso = f.elements.facturar_exceso.checked;
    const x = await post(`/api/turistico/reservas/${r.id}/checkout`, { fianza: { ...clean({ ...d, importe: d.forma === "no_procede" ? 0 : d.importe }), cargos, facturar_exceso } });
    toast(`Salida realizada · fianza: ${x.devolucion.forma_texto}${x.ots ? ` · ${x.ots.length} OT a mantenimiento` : ""}${x.pedido ? ` · pedido ${x.pedido.numero}` : ""}${x.factura_exceso ? ` · factura ${x.factura_exceso.codigo} (${eur(x.factura_exceso.total)}, pendiente de cobro)` : ""}`);
    reload && reload();
    if (x.whatsapp) setTimeout(() => avisoFianza(x), 0);
  }, "Dar la salida");
  const sync = () => {
    const forma = f.elements.forma.value, tr = forma === "transferencia", np = forma === "no_procede";
    f.elements.iban.closest("label").style.display = tr ? "" : "none"; f.elements.iban.required = tr;
    f.elements.importe.closest("label").style.display = np ? "none" : "";
    const sumaCargos = cargos.reduce((t, c) => t + c.cantidad * c.precio, 0);  // su detalle lo pone el PMS
    const parcial = np || Number(f.elements.importe.value) < info.fianza - sumaCargos - 0.004;
    f.elements.retenido_motivo.closest("label").style.display = parcial ? "" : "none"; f.elements.retenido_motivo.required = parcial;
  };
  f.elements.forma.onchange = sync; f.elements.importe.oninput = sync; sync();
  const pintaCargos = () => {
    const suma = Math.round(cargos.reduce((t, c) => t + c.cantidad * c.precio, 0) * 100) / 100;
    $("[data-cargos]", f).innerHTML = cargos.length ? `<ul class="envios">${cargos.map((c, i) => `<li>${c.cantidad} × ${esc(c.articulo)} · ${eur(c.precio)} = <b>${eur(c.cantidad * c.precio)}</b>
        <label class="check" title="Orden de trabajo a mantenimiento para reponerlo o repararlo"><input type="checkbox" data-ot="${i}" ${c.ot ? "checked" : ""}> OT mantenimiento</label>
        ${c.codigo ? `<label class="check" title="Se añade al pedido de reposición del activo (lo autoriza Recepción 1)"><input type="checkbox" data-ped="${i}" ${c.pedido ? "checked" : ""}> Pedido</label>` : ""} <button type="button" class="btn sm" data-quita="${i}">Quitar</button></li>`).join("")}</ul>
      <p>Total cargos: <b>${eur(suma)}</b>${suma > info.fianza ? ` <span class="error">supera la fianza en ${eur(suma - info.fianza)}</span>` : ""}</p>` : '<p class="muted">Sin roturas ni faltas.</p>';
    f.querySelectorAll("[data-quita]").forEach((b) => (b.onclick = () => { cargos.splice(Number(b.dataset.quita), 1); pintaCargos(); }));
    f.querySelectorAll("[data-ot]").forEach((b) => (b.onchange = () => (cargos[b.dataset.ot].ot = b.checked)));
    f.querySelectorAll("[data-ped]").forEach((b) => (b.onchange = () => (cargos[b.dataset.ped].pedido = b.checked)));
    $("[data-exc]", f).style.display = suma > info.fianza ? "" : "none";
    f.elements.importe.value = Math.max(0, Math.round((info.fianza - suma) * 100) / 100);
    sync();
  };
  $("[data-add]", f).onclick = () => {
    const v = $("[data-art]", f).value, cant = Math.max(1, Number($("[data-cant]", f).value) || 1);
    if (!v) return toast("Elija el artículo", true);
    if (v === "otro") {
      const art = prompt("Artículo roto o que falta:"); if (!art) return;
      const precio = Number(String(prompt("Precio de reposición € (IVA incluido):") || "").replace(",", "."));
      if (!(precio >= 0)) return toast("Precio no válido", true);
      cargos.push({ articulo: art, cantidad: cant, precio });
    } else {
      const x = dot.items[Number(v)];
      let precio = x.precio;
      if (precio == null) { precio = Number(String(prompt(`Precio de reposición de «${x.articulo}» €:`) || "").replace(",", ".")); if (!(precio >= 0)) return toast("Precio no válido", true); }
      cargos.push({ codigo: x.codigo, articulo: x.articulo, cantidad: cant, precio, pedido: seRepone(x), ot: !seRepone(x) && precio >= 20 });
    }
    pintaCargos();
  };
  $("[data-hoja]", f).onclick = () => abrirFichero(`/api/turistico/reservas/${r.id}/hoja-revision.pdf`);
  $("[data-movil]", f).onclick = async () => {
    const e = await run(() => get(`/api/revision/reserva/${r.id}/enlace`));
    window.open(e.whatsapp, "_blank", "noopener");
  };
  // lo que limpieza marcó en el móvil llega ya cargado; lo roto de valor abre OT a mantenimiento por defecto
  (info.revision?.items || []).forEach((x) => cargos.push({ codigo: x.codigo, articulo: x.articulo, cantidad: x.cantidad, precio: x.precio ?? 0,
    ot: x.estado === "roto" && !seRepone(x) && (x.precio ?? 0) >= 20, pedido: seRepone(x) }));
  pintaCargos();
}
async function informeRoturas() {
  const mes = today().slice(0, 8) + "01";
  const f = cerrarSolo(form("Informe de roturas y faltas", [
    { k: "desde", t: "Desde", type: "date", def: mes }, { k: "hasta", t: "Hasta", type: "date", def: today() },
    { html: `<div class="toolbar"><button type="button" class="btn" data-ver>Ver</button><button type="button" class="btn primary" data-xls>Excel</button></div><div data-r></div>` }], {}, async () => {}));
  $("#modal").classList.add("ancho");
  const q = () => ({ desde: f.elements.desde.value, hasta: f.elements.hasta.value, asset_id: S.asset });
  const ver = async () => {
    const x = await run(() => get("/api/turistico/informe-roturas", q()));
    $("[data-r]", f).innerHTML = `<p>${x.salidas} salida(s) con fianza · <b>${x.con_cargos}</b> con roturas o faltas · total <b>${eur(x.total)}</b>${x.facturado_exceso ? ` · facturado por exceso ${eur(x.facturado_exceso)}` : ""}</p>
      <h4>Por artículo</h4><div data-a></div><h4>Por apartamento</h4><div data-p></div>`;
    table($("[data-a]", f), [{ k: "articulo", t: "Artículo" }, { k: "veces", t: "Veces", num: true }, { k: "unidades", t: "Unidades", num: true }, { k: "importe", t: "Importe", num: true, f: eur }, { k: "ots", t: "OT", num: true }], x.por_articulo);
    table($("[data-p]", f), [{ k: "activo", t: "Activo" }, { k: "unidad", t: "Apto." }, { k: "tipologia", t: "Tipología" }, { k: "salidas", t: "Salidas", num: true }, { k: "unidades", t: "Unidades", num: true }, { k: "importe", t: "Importe", num: true, f: eur }], x.por_apartamento);
  };
  $("[data-ver]", f).onclick = ver;
  $("[data-xls]", f).onclick = () => run(() => download("GET", "/api/turistico/informe-roturas?" + new URLSearchParams(clean({ ...q(), formato: "xlsx" }))));
  ver();
}
function avisoFianza(x) {
  const env = x.avisos || [];
  const f = cerrarSolo(form("Transferencia de fianza: aviso a la Dirección", [
    { html: `<p>Correo enviado: ${env.map((e) => `${esc(e.destinatario)} ${e.ok ? "✔" : `✖ ${esc(e.error || "")}`}`).join(" · ") || "—"}. Queda en el registro de envíos y en el envío a INVERGESTION.</p>
      <p>Pulse cada botón para mandar el mismo texto por <b>WhatsApp</b>:</p>
      <div class="toolbar">${x.whatsapp.map((w, i) => `<button type="button" class="btn primary" data-w="${i}">WhatsApp · ${esc(w.destinatario)}${w.movil ? "" : " (elegir contacto)"}</button>`).join("")}</div>` }], {}, async () => {}));
  f.querySelectorAll("[data-w]").forEach((b) => (b.onclick = () => window.open(x.whatsapp[b.dataset.w].url, "_blank", "noopener")));
}
async function devolucionesFianza() {
  const pinta = async () => {
    const l = await run(() => get("/api/turistico/fianzas", { asset_id: S.asset }));
    table($("[data-t]", f), [{ k: "activo", t: "Activo" }, { k: "unidad", t: "Apto." }, { k: "localizador", t: "Reserva" }, { k: "titular", t: "Cliente" },
      { k: "fianza", t: "Fianza", num: true, f: eur }, { k: "importe", t: "Devuelto", num: true, f: eur }, { k: "forma_texto", t: "Forma" },
      { k: "fecha", t: "Fecha", f: (v, x) => fdate(x.devuelta_fecha || v) },
      { k: "estado", t: "Estado", f: (v) => (v === "devuelta" ? "✔ devuelta" : '<span class="badge b-pendiente">transferencia pendiente</span>') },
      { k: "exceso_total", t: "Exceso", f: (v, x) => (v ? `${eur(v)} ${x.exceso_cobro === "pendiente" ? '<span class="badge b-pendiente">sin cobrar</span>' : "✔"}` : "—") },
      { k: "exportada", t: "Gestoría", f: (v) => (v ? `enviada ${fdate(v)}` : "—") }], l,
    (x) => can("reservas.editar") ? [
      x.estado !== "devuelta" && ["Transferencia hecha", () => run(() => post(`/api/turistico/fianzas/${x.id}/devuelta`, {}), "Fianza devuelta").then(pinta)],
      x.estado !== "devuelta" && ["Reenviar aviso", async () => avisoFianza(await run(() => post(`/api/turistico/fianzas/${x.id}/avisar`)))],
      x.exceso_cobro === "pendiente" && ["Recordar cobro", async () => {
        const m = await run(() => post(`/api/turistico/fianzas/${x.id}/recordatorio`));
        toast(m.email ? `Recordatorio enviado a ${m.email.destinatario}${m.email.ok ? "" : " (error)"}` : "El cliente no tiene correo");
        if (m.whatsapp && confirm("¿Enviar también el recordatorio por WhatsApp al cliente?")) window.open(m.whatsapp, "_blank", "noopener");
      }]] : []);
  };
  const f = cerrarSolo(form("Devoluciones de fianza", [{ html: `<p class="muted">Registradas al dar la salida. Las transferencias las hace la Dirección; cuando esté hecha, márquela. Todas van en el envío a INVERGESTION (gestoría). Las facturas de exceso sin cobrar se recuerdan solas al cliente a los 3, 10 y 17 días (si tiene correo).</p>
    <div class="toolbar"><span class="spacer"></span><button type="button" class="btn" data-roturas>Informe de roturas</button></div><div data-t></div>` }], {}, async () => {}));
  $("#modal").classList.add("ancho");
  $("[data-roturas]", f).onclick = () => informeRoturas();
  pinta();
}

// ---- dotación del apartamento: la habitual (la fija Recepción) y la especial de cada reserva
let DOT_CAT = null;
async function catalogoDotacion(assetId) {
  if (!DOT_CAT || DOT_CAT._a !== assetId) DOT_CAT = { ...(await get("/api/dotacion/catalogo", { asset_id: assetId })), _a: assetId };
  return DOT_CAT;
}
// tabla editable: casilla (se entrega) + cantidad, por zonas; «Otra dotación» crea un artículo nuevo
function dotacionEditor(cont, cat, items, perfil, assetId) {
  const sel = Object.fromEntries(items.map((x) => [x.codigo, x]));
  const todos = [...cat.articulos.filter((a) => !a.propio || true)];
  items.forEach((x) => { if (!todos.some((a) => a.codigo === x.codigo)) todos.push({ codigo: x.codigo, zona: x.zona, articulo: x.articulo, cantidades: {} }); });
  const pinta = () => {
    cont.innerHTML = Object.entries(cat.zonas).map(([z, nz]) => {
      const filas = todos.filter((a) => a.zona === z);
      return `<details ${filas.some((a) => sel[a.codigo]) ? "open" : ""}><summary><b>${esc(nz)}</b> · ${filas.filter((a) => sel[a.codigo]).length}/${filas.length}</summary>
        <div class="table-wrap no-encajar"><table class="dot"><tbody>${filas.map((a) => {
          const v = sel[a.codigo]?.cantidad ?? (a.cantidades?.[perfil] && !["—", "No"].includes(a.cantidades[perfil]) ? a.cantidades[perfil] : "1");
          return `<tr><td><label class="check"><input type="checkbox" data-sel="${esc(a.codigo)}" ${sel[a.codigo] ? "checked" : ""}> ${esc(a.articulo)}</label></td>
            <td><input data-cant="${esc(a.codigo)}" value="${esc(v)}" size="14"></td><td class="muted">${esc(a.codigo)}</td></tr>`;
        }).join("")}</tbody></table></div></details>`;
    }).join("") + `<div class="toolbar"><select data-zona>${Object.entries(cat.zonas).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select>
      <input data-nuevo placeholder="Otra dotación: nombre del artículo nuevo"><button type="button" class="btn sm" data-otro>+ Otra dotación</button></div>`;
    cont.querySelectorAll("[data-sel]").forEach((c) => (c.onchange = () => {
      const a = todos.find((x) => x.codigo === c.dataset.sel), cant = cont.querySelector(`[data-cant="${c.dataset.sel}"]`).value;
      if (c.checked) sel[a.codigo] = { codigo: a.codigo, zona: a.zona, articulo: a.articulo, cantidad: cant || "1" }; else delete sel[a.codigo];
    }));
    cont.querySelectorAll("[data-cant]").forEach((i) => (i.oninput = () => { if (sel[i.dataset.cant]) sel[i.dataset.cant].cantidad = i.value; }));
    $("[data-otro]", cont).onclick = async () => {
      const nombre = $("[data-nuevo]", cont).value.trim();
      if (nombre.length < 2) return toast("Escriba el nombre del artículo", true);
      const a = await run(() => post("/api/dotacion/articulos", { asset_id: assetId, zona: $("[data-zona]", cont).value, articulo: nombre }), "Artículo añadido al catálogo");
      if (!todos.some((x) => x.codigo === a.codigo)) todos.push({ ...a, cantidades: {}, propio: true });
      sel[a.codigo] = { ...a, cantidad: "1" };
      DOT_CAT = null; pinta();
    };
  };
  pinta();
  return () => Object.values(sel);
}
async function dotacionHabitual(assetId) {
  const aid = assetId || S.asset || (await pickAsset("apartamentos_turisticos"));
  const [cat, tips] = await Promise.all([catalogoDotacion(aid), run(() => get("/api/dotacion/habitual", { asset_id: aid }))]);
  const f = cerrarSolo(form(`Dotación habitual · ${assetName(aid)}`, [
    { html: `<p>Lista de dotación de cada tipo de apartamento (catálogo 3 llaves). Recepción la revisa <b>una vez</b> y queda como <b>dotación habitual</b>: es la que se imprime o envía con el contrato al pulsar «Dotación habitual». Marque lo que hay, ajuste las cantidades y, si falta algo, use «Otra dotación».</p>
      <div class="toolbar">${tips.map((t, i) => `<button type="button" class="btn sm ${t.fijada ? "" : "primary"}" data-tip="${i}">${esc(t.tipologia || "Sin tipología")} · ${t.unidades} apto. ${t.fijada ? "✔" : "(por revisar)"}</button>`).join("")}</div>
      <div class="toolbar"><label>Apartamento concreto (terraza, VIP…)<select data-uni><option value="">Elija…</option></select></label><button type="button" class="btn sm" data-propia>Dotación propia</button>
      <span class="spacer"></span><button type="button" class="btn sm" data-precios>Precios de reposición</button></div><div data-ed></div>` }], {}, async () => {}));
  $("#modal").classList.add("ancho");
  const unis = await get("/api/dotacion/unidades", { asset_id: aid }).catch(() => []);
  $("[data-uni]", f).insertAdjacentHTML("beforeend", unis.map((u) => `<option value="${u.id}">${esc(u.codigo)}${u.tipologia ? ` · ${esc(u.tipologia)}` : ""}${u.propia ? " · ✔ propia" : ""}</option>`).join(""));
  $("[data-precios]", f).onclick = () => preciosReposicion(aid);
  $("[data-propia]", f).onclick = async () => {
    const uid = $("[data-uni]", f).value;
    if (!uid) return toast("Elija el apartamento", true);
    const d = await run(() => get(`/api/dotacion/unidad/${uid}`));
    const ed = $("[data-ed]", f);
    ed.innerHTML = `<fieldset><legend>Apartamento ${esc(d.codigo)} · ${d.origen === "apartamento" ? "dotación propia" : `parte de la ${d.origen === "tipologia" ? "habitual de su tipo" : "estándar 3 llaves"}`}</legend>
      <div data-lista></div><div class="toolbar"><button type="button" class="btn primary" data-gu>Guardar dotación propia</button>${d.origen === "apartamento" ? '<button type="button" class="btn danger" data-qu>Quitar: volver a la de su tipo</button>' : ""}</div></fieldset>`;
    const leer = dotacionEditor($("[data-lista]", ed), cat, d.items, d.perfil, aid);
    $("[data-gu]", ed).onclick = () => run(() => put(`/api/dotacion/unidad/${uid}`, { items: leer() }), `Dotación propia de ${d.codigo} guardada`);
    if ($("[data-qu]", ed)) $("[data-qu]", ed).onclick = () => run(() => api("DELETE", `/api/dotacion/unidad/${uid}`), "Vuelve a la dotación de su tipo").then(() => (ed.innerHTML = ""));
  };
  f.querySelectorAll("[data-tip]").forEach((b) => (b.onclick = () => {
    const t = tips[b.dataset.tip];
    const ed = $("[data-ed]", f);
    ed.innerHTML = `<fieldset><legend>${esc(t.tipologia || "Sin tipología")} · perfil <select data-perfil>${Object.entries(cat.perfiles).map(([k, v]) => `<option value="${k}" ${k === t.perfil ? "selected" : ""}>${esc(v)} · ${esc(cat.codigos_perfil[k])}</option>`).join("")}</select></legend>
      <div data-lista></div><div class="toolbar"><button type="button" class="btn primary" data-guardar>Guardar como dotación habitual</button></div></fieldset>`;
    let leer = dotacionEditor($("[data-lista]", ed), cat, t.fijada ? t.items : t.items, t.perfil, aid);
    $("[data-perfil]", ed).onchange = async (e) => {  // otro perfil: se propone su lista estándar
      if (!confirm("¿Cargar la lista estándar de ese perfil? Se perderán los cambios sin guardar.")) return;
      const p = e.target.value;
      leer = dotacionEditor($("[data-lista]", ed), cat, cat.articulos.filter((a) => a.cantidades?.[p] && !["—", "No"].includes(a.cantidades[p])).map((a) => ({ ...a, cantidad: a.cantidades[p] })), p, aid);
    };
    $("[data-guardar]", ed).onclick = async () => {
      const r = await run(() => put("/api/dotacion/habitual", { asset_id: aid, tipologia: t.tipologia, perfil: $("[data-perfil]", ed).value, items: leer() }), "Dotación habitual guardada");
      Object.assign(t, r); b.classList.remove("primary"); b.textContent = `${t.tipologia || "Sin tipología"} · ${t.unidades} apto. ✔`;
    };
  }));
}
async function preciosReposicion(aid) {
  const l = await run(() => get("/api/dotacion/precios", { asset_id: aid }));
  const zonas = (await catalogoDotacion(aid)).zonas;
  const f = form(`Precios de reposición · ${assetName(aid)}`, [
    { html: `<p>Precio por unidad (IVA incluido) que se descuenta de la fianza si el artículo se rompe o falta. Los que no ha cambiado son <b>orientativos</b> (gama media de hostelería); ajústelos a lo que pagan ustedes. Deje vacío para volver al orientativo.</p>
      ${Object.entries(zonas).map(([z, nz]) => `<details><summary><b>${esc(nz)}</b></summary><div class="table-wrap no-encajar"><table class="dot"><tbody>${l.filter((x) => x.zona === z).map((x) =>
        `<tr><td>${esc(x.articulo)}</td><td><input data-pre="${esc(x.codigo)}" type="number" step="0.01" min="0" value="${x.fijado ? x.precio : ""}" placeholder="${x.orientativo ?? "—"}" style="width:7em"> €</td><td class="muted">${x.fijado ? "propio" : "orientativo"}</td></tr>`).join("")}</tbody></table></div></details>`).join("")}` }],
  {}, async () => {
    const precios = {};
    f.querySelectorAll("[data-pre]").forEach((i) => { const x = l.find((y) => y.codigo === i.dataset.pre); const v = i.value === "" ? null : Number(i.value); if (v !== (x.fijado ? x.precio : null)) precios[i.dataset.pre] = v; });
    await put("/api/dotacion/precios", { asset_id: aid, precios });
    toast("Precios de reposición guardados");
  }, "Guardar precios");
  $("#modal").classList.add("ancho");
}
async function dotacionReserva(r) {
  const [d, cat] = await Promise.all([run(() => get(`/api/turistico/reservas/${r.id}/dotacion`)), catalogoDotacion(r.asset_id)]);
  const f = form(`Dotación · ${r.unidad} · ${r.huesped}`, [
    { html: `<div class="toolbar"><button type="button" class="btn sm" data-hoja>Hoja de revisión de salida (PDF)</button></div><p>Parte de la <b>dotación ${d.origen === "apartamento" ? "propia de este apartamento" : "habitual"}</b>${d.habitual_fijada ? "" : ' <span class="badge b-pendiente">aún no revisada por Recepción: se usa la estándar 3 llaves</span>'}. Quite, cambie cantidades o añada artículos: es la <b>dotación especial</b> de esta reserva. Se imprime con el contrato marcando «Dotación habitual (Anexo I)».</p><div data-lista></div>` }],
  {}, async () => {
    const elegidos = leer(), base = Object.fromEntries(d.habitual.map((x) => [x.codigo, x]));
    const cambios = {}, extra = [];
    d.habitual.forEach((x) => { const e = elegidos.find((y) => y.codigo === x.codigo); if (!e) cambios[x.codigo] = "—"; else if (String(e.cantidad) !== String(x.cantidad)) cambios[x.codigo] = e.cantidad; });
    elegidos.forEach((e) => { if (!base[e.codigo]) extra.push(e); });
    const x = await put(`/api/turistico/reservas/${r.id}/dotacion`, { cambios, extra });
    toast(x.especial ? "Dotación especial guardada" : "Dotación habitual (sin cambios)");
  }, "Guardar dotación");
  $("#modal").classList.add("ancho");
  const leer = dotacionEditor($("[data-lista]", f), cat, d.items, d.perfil, r.asset_id);
  $("[data-hoja]", f).onclick = () => abrirFichero(`/api/turistico/reservas/${r.id}/hoja-revision.pdf`);
}

// ---- escaneo de documentos de identidad
// Al seleccionar el fichero (o capturar con la cámara) el documento se lee solo. Con cliente existente la copia
// se guarda en su ficha; en un alta (cid = null) queda pendiente y se adjunta al crear la reserva o el cliente.
// El operario elige el tipo de documento; en DNI y NIE/TIE hay una casilla por cara (el reverso, con las líneas «<<<»,
// es el que se lee; el anverso se guarda como copia). El marco de la cámara tiene la forma del documento y la
// captura se recorta a ese marco: el documento ocupa toda la imagen y se lee mucho mejor.
const TIPOS_DOC = {
  DNI: { t: "DNI", ratio: 1.586, caras: [["reverso", "Reverso · cara con las líneas «<<<» (se lee)"], ["anverso", "Anverso · cara de la foto (copia)"]],
    guia: "Escanee primero el <b>reverso</b> (la cara con las líneas «<<<»): de ahí se leen los datos y el domicilio. El anverso se guarda como copia." },
  NIE: { t: "NIE / TIE", ratio: 1.586, caras: [["reverso", "Reverso · cara con las líneas «<<<» (se lee)"], ["anverso", "Anverso · cara de la foto (copia)"]],
    guia: "Tarjeta de extranjero (TIE): escanee primero el <b>reverso</b>, la cara con las líneas «<<<». El anverso se guarda como copia." },
  PAS: { t: "Pasaporte", ratio: 1.42, caras: [["anverso", "Página de la foto (con las líneas «<<<» abajo)"]],
    guia: "Abra el pasaporte por la <b>página de la foto</b> y encuadre la página entera, con las dos líneas «<<<» de abajo bien visibles." },
  OTRO: { t: "Otro documento", ratio: 1.586, caras: [["reverso", "Cara con las líneas «<<<» (se lee)"], ["anverso", "Otra cara (copia, opcional)"]],
    guia: "Documentos de identidad de otros países, permisos de residencia…: escanee la cara con las líneas «<<<». Si no las tiene, guarde la copia y complete los datos a mano." },
};
const scanHtml = (titulo = "Escanear documento de identidad") => `<fieldset class="scan"><legend>${esc(titulo)}</legend>
  <div class="scan-tipos" role="group" aria-label="Tipo de documento">${Object.entries(TIPOS_DOC).map(([k, d]) => `<button type="button" class="btn sm" data-tipodoc="${k}">${esc(d.t)}</button>`).join("")}</div>
  <p class="muted" data-guia></p>
  <div class="scan-caras" data-caras></div>
  <div class="scan-lector"><b>Lector de documentos</b> <span class="muted peq">(lector MRZ conectado al ordenador)</span>
    <textarea data-mrz rows="2" spellcheck="false" autocomplete="off" autocapitalize="off" placeholder="Pulse aquí y pase el documento por el lector: los datos se rellenan solos"></textarea>
    <label class="check peq"><input type="checkbox" data-lectorpref> En este equipo hay lector: empezar siempre por aquí (sin abrir la cámara)</label></div>
  <div data-camzone class="camzone hidden">
    <div class="cam-marco"><video data-video autoplay playsinline muted></video><div class="cam-guia" data-guiacam><span data-guiatxt></span></div></div>
    <div class="toolbar"><button type="button" class="btn primary" data-capturar>📸 Capturar</button>
      <button type="button" class="btn" data-camoff>Cerrar cámara</button>
      <label class="check"><input type="checkbox" data-camauto> Abrir la cámara automáticamente</label></div>
    <p class="muted peq">Documento <b>dentro del marco</b>, recto, sin reflejos (incline un poco si brilla) y con buena luz.</p>
  </div>
  <div data-scanmsg></div><div data-docs class="muted"></div></fieldset>`;
function pararCamara() {
  if (S.cam) { S.cam.getTracks().forEach((t) => t.stop()); S.cam = null; }
}
async function hayCamara() {
  try { return (await navigator.mediaDevices.enumerateDevices()).some((d) => d.kind === "videoinput"); } catch { return false; }
}
// Foto de móvil (12 MP, varios MB): se reduce en el navegador a 2.600 px antes de enviarla. Sube mucho antes y se
// lee igual de bien (la copia guardada sigue siendo perfectamente legible). PDF y fotos pequeñas, tal cual.
async function reducirFoto(fichero, lado = 2600) {
  if (!fichero.type.startsWith("image/") || !window.createImageBitmap) return fichero;
  try {
    const bmp = await createImageBitmap(fichero, { imageOrientation: "from-image" });
    const k = lado / Math.max(bmp.width, bmp.height);
    if (k >= 1) { bmp.close?.(); return fichero; }
    const c = Object.assign(document.createElement("canvas"), { width: Math.round(bmp.width * k), height: Math.round(bmp.height * k) });
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    bmp.close?.();
    const blob = await new Promise((ok) => c.toBlob(ok, "image/jpeg", 0.92));
    return blob ? new File([blob], (fichero.name || "foto").replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }) : fichero;
  } catch { return fichero; }  // formato que el navegador no sabe abrir: se envía el original
}
function bindScan(f, cid, aplicar) {
  const $s = (sel) => f.querySelector(sel);
  const msg = $s("[data-scanmsg]"), lista = $s("[data-docs]"), zona = $s("[data-camzone]"), video = $s("[data-video]");
  const guiaCam = $s("[data-guiacam]");
  f._docs = [];  // alta: copias pendientes de adjuntar ({id, tipo, cara, subido})
  let tipo = "DNI", caraCam = null;
  const estado = {};  // cara -> texto del resultado
  try { tipo = localStorage.getItem("pms_tipo_doc") || "DNI"; } catch {}
  if (!TIPOS_DOC[tipo]) tipo = "DNI";
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
  const ajustaGuia = () => {  // marco con la forma del documento, centrado sobre la imagen de la cámara
    const vw = video.videoWidth || 16, vh = video.videoHeight || 9, r = TIPOS_DOC[tipo].ratio;
    let w = 0.86, h = (w * vw) / r / vh;
    if (h > 0.86) { h = 0.86; w = (h * vh * r) / vw; }
    Object.assign(guiaCam.style, { width: `${w * 100}%`, height: `${h * 100}%`, left: `${(1 - w) * 50}%`, top: `${(1 - h) * 50}%` });
    guiaCam._marco = { w, h };
  };
  const pintaTipo = () => {
    const d = TIPOS_DOC[tipo];
    f.querySelectorAll("[data-tipodoc]").forEach((b) => b.classList.toggle("primary", b.dataset.tipodoc === tipo));
    $s("[data-guia]").innerHTML = d.guia;
    $s("[data-caras]").innerHTML = d.caras.map(([cara, txt], n) => `<div class="scan-cara${n ? "" : " principal"}" data-cara="${cara}">
      <b>${n + 1}. ${esc(txt)}</b>
      <div class="toolbar"><button type="button" class="btn sm${n ? "" : " primary"}" data-camcara="${cara}">📷 Cámara</button>
        <label class="btn sm">📁 Fichero<input type="file" data-filecara="${cara}" accept="image/*,application/pdf" hidden></label></div>
      <div class="peq" data-estado="${cara}">${estado[cara] || ""}</div></div>`).join("");
    f.querySelectorAll("[data-camcara]").forEach((b) => (b.onclick = () => encender(b.dataset.camcara)));
    f.querySelectorAll("[data-filecara]").forEach((inp) => (inp.onchange = async (e) => {
      const fi = e.target.files[0];
      if (fi) await subir(inp.dataset.filecara, fi);
      e.target.value = "";
    }));
    $s("[data-guiatxt]").textContent = d.caras.find(([c]) => c === caraCam)?.[1] || d.caras[0][1];
    ajustaGuia();
  };
  f.querySelectorAll("[data-tipodoc]").forEach((b) => (b.onclick = () => {
    tipo = b.dataset.tipodoc;
    try { localStorage.setItem("pms_tipo_doc", tipo); } catch {}
    pintaTipo();
  }));
  // envía una cara y aplica lo leído; devuelve true si se han leído los datos
  const subir = async (cara, fichero) => {
    fichero = await reducirFoto(fichero);
    const fd = new FormData();
    fd.append(cara, fichero); fd.append("tipo", tipo);
    const caja = () => f.querySelector(`[data-estado="${cara}"]`);
    // nunca se queda «pensando»: contador visible y, como mucho, 60 s de espera
    const t0 = Date.now(), ctl = new AbortController();
    const reloj = setInterval(() => { estado[cara] = `<span class="muted">Leyendo… ${Math.round((Date.now() - t0) / 1000)} s</span>`; if (caja()) caja().innerHTML = estado[cara]; }, 1000);
    const corte = setTimeout(() => ctl.abort(), 60000);
    estado[cara] = '<span class="muted">Leyendo… 0 s</span>';
    if (caja()) caja().innerHTML = estado[cara];
    msg.innerHTML = "";
    try {
      const res = await fetch(cid ? `/api/terceros/${cid}/documentos` : "/api/documentos/leer",
        { method: "POST", headers: { Authorization: `Bearer ${S.token}` }, body: fd, signal: ctl.signal })
        .finally(() => { clearInterval(reloj); clearTimeout(corte); });
      const j = await res.json().catch(() => null);
      if (!res.ok) throw new Error(errMsg(j, res));
      const lec = j.lectura;
      if (!cid) f._docs.push(...j.documentos);
      if (lec.leido) aplicar(lec, j.tercero);
      estado[cara] = lec.leido ? (lec.mrz_valido ? '<span class="ok">✔ Leído y validado</span>' : '<span class="aviso">⚠ Leído con dudas: revise</span>')
        : lec.solo_copia ? '<span class="ok">✔ Copia guardada</span>' : '<span class="error">✖ No se ha podido leer</span>';
      if (caja()) caja().innerHTML = estado[cara];
      msg.innerHTML = (lec.leido ? `<p><b>Datos rellenados desde el documento.</b> Revise los campos resaltados.</p>` : "") +
        (lec.avisos || []).map((a) => `<p class="${a.includes("CADUCADO") || a.includes("No se han podido") ? "error" : "muted"}">• ${esc(a)}</p>`).join("");
      cargar();
      return lec.leido || lec.solo_copia;
    } catch (e) {
      const txt = e.name === "AbortError" ? "El servidor no ha respondido a tiempo: vuelva a intentarlo o complete los datos a mano" : e.message;
      estado[cara] = `<span class="error">✖ ${esc(txt)}</span>`;
      if (caja()) caja().innerHTML = estado[cara];
      return false;
    }
  };
  // cámara (webcam de recepción, tablet o móvil)
  const encender = async (cara) => {
    caraCam = cara || TIPOS_DOC[tipo].caras[0][0];
    $s("[data-guiatxt]").textContent = TIPOS_DOC[tipo].caras.find(([c]) => c === caraCam)?.[1] || "";
    if (S.cam && !zona.classList.contains("hidden")) return;
    if (!navigator.mediaDevices?.getUserMedia) { msg.innerHTML = '<p class="error">Este navegador no permite usar la cámara.</p>'; return; }
    try {
      pararCamara();
      S.cam = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 2560 }, height: { ideal: 1440 } } });
      video.srcObject = S.cam; zona.classList.remove("hidden");
      video.onloadedmetadata = ajustaGuia;
    } catch { msg.innerHTML = '<p class="error">No se ha podido abrir la cámara (permiso denegado o sin cámara).</p>'; }
  };
  const apagar = () => { pararCamara(); zona.classList.add("hidden"); };
  $s("[data-camoff]").onclick = apagar;
  $s("[data-capturar]").onclick = async () => {
    if (!S.cam || !video.videoWidth) return;
    // recorte al marco guía (con un pequeño margen para no cortar los bordes del documento)
    const { w, h } = guiaCam._marco || { w: 1, h: 1 }, m = 0.04;
    const vw = video.videoWidth, vh = video.videoHeight;
    const cw = Math.min(1, w + 2 * m) * vw, ch = Math.min(1, h + 2 * m) * vh;
    const c = document.createElement("canvas");
    c.width = Math.round(cw); c.height = Math.round(ch);
    c.getContext("2d").drawImage(video, (vw - cw) / 2, (vh - ch) / 2, cw, ch, 0, 0, cw, ch);
    const blob = await new Promise((ok) => c.toBlob(ok, "image/jpeg", 0.95));
    const cara = caraCam || TIPOS_DOC[tipo].caras[0][0];
    if (await subir(cara, new File([blob], `${cara}.jpg`, { type: "image/jpeg" }))) {
      const siguiente = TIPOS_DOC[tipo].caras.find(([cc]) => cc !== cara && !estado[cc]);
      if (siguiente) {  // pasa a la otra cara sin cerrar la cámara
        caraCam = siguiente[0];
        $s("[data-guiatxt]").textContent = siguiente[1];
        msg.innerHTML += `<p class="muted">Ahora, si quiere, dé la vuelta al documento y capture: <b>${esc(siguiente[1])}</b>. Si no, cierre la cámara.</p>`;
      } else apagar();
    }
  };
  // lector MRZ «por teclado»: escribe las líneas «<<<» en el cuadro; al terminar de escribir se interpretan
  const cajaMrz = $s("[data-mrz]"), prefLector = $s("[data-lectorpref]");
  let tMrz = null;
  const leerMrz = async () => {
    const texto = cajaMrz.value.trim();
    if (texto.replace(/\s/g, "").length < 60) return;  // aún llegando (la zona más corta tiene 72 caracteres)
    msg.innerHTML = '<p class="muted">Leyendo del lector…</p>';
    try {
      const j = await post("/api/documentos/mrz", { texto, tipo, tercero_id: cid || null });
      const lec = j.lectura;
      if (lec.leido) aplicar(lec, j.tercero);
      msg.innerHTML = (lec.leido ? `<p class="${lec.mrz_valido ? "ok" : "aviso"}"><b>${lec.mrz_valido ? "✔ Leído con el lector y validado." : "⚠ Leído con dudas: revise."}</b> Revise los campos resaltados. El lector no guarda copia del documento: si la necesita, escanéelo arriba.</p>` : "") +
        (lec.avisos || []).map((a) => `<p class="${a.includes("CADUCADO") || !lec.leido ? "error" : "muted"}">• ${esc(a)}</p>`).join("");
      if (lec.leido) cajaMrz.value = "";
    } catch (e) { msg.innerHTML = `<p class="error">${esc(e.message)}</p>`; }
  };
  cajaMrz.oninput = () => { clearTimeout(tMrz); tMrz = setTimeout(leerMrz, 500); };
  try { prefLector.checked = localStorage.getItem("pms_lector_mrz") === "1"; } catch {}
  prefLector.onchange = () => {
    try { localStorage.setItem("pms_lector_mrz", prefLector.checked ? "1" : "0"); } catch {}
    if (prefLector.checked) { apagar(); cajaMrz.focus(); }
  };
  if (prefLector.checked) { f._sinCamara = true; setTimeout(() => cajaMrz.focus(), 50); }
  const auto = $s("[data-camauto]");
  let pref = null;
  try { pref = localStorage.getItem("pms_cam_auto"); } catch {}
  auto.onchange = () => { try { localStorage.setItem("pms_cam_auto", auto.checked ? "1" : "0"); } catch {} };
  pintaTipo();
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
// ---- anular una reserva, un contrato o un alquiler hecho por error o que no sigue adelante (queda en el historial
// como anulado, con su motivo). Con facturas hay que rectificarlas antes; con cobros se da de baja en vez de anular.
function anular(que, hecho, url, reload) {
  form(`Anular ${que}`, [
    { html: `<p>Anule ${que} si se hizo por error o no sigue adelante. Queda en el historial como <b>${hecho}</b>, con el motivo, y la unidad queda libre.</p>
      <p class="muted">Si tiene facturas, antes hay que emitir la factura rectificativa. Si tiene cobros, no se anula: se da de baja con su fecha.</p>` },
    { k: "motivo", t: "Motivo de la anulación", req: true, wide: true },
  ], {}, async (d) => { await post(url, d); toast(`${que[0].toUpperCase()}${que.slice(1)}: ${hecho}`); reload && reload(); }, "Anular");
}
const botonAnular = (texto) => ({ html: `<div class="toolbar"><span class="spacer"></span><button type="button" class="btn sm danger" data-anular>${texto}</button></div>`, wide: true });
function editReservation(r, reload) {
  form(`Reserva ${r.localizador || r.id} · ${r.unidad}`, [
    { k: "localizador", t: "Localizador" }, { k: "canal", t: "Canal", type: "select", options: list(S.cat.canales) },
    { k: "fecha_entrada", t: "Entrada", type: "date", req: true }, { k: "fecha_salida", t: "Salida", type: "date", req: true },
    { k: "adultos", t: "Adultos (16 años o más)", type: "number" }, { k: "ninos", t: "Menores de 16 (no ocupan plaza)", type: "number" },
    { k: "importe_total", t: "Importe total € (IVA incluido)", type: "number" },
    { html: `<p class="muted">Cobrado: ${eur(r.importe_pagado)}. Los cobros se registran con el botón <b>Cobro</b>, que emite la factura.</p>` },
    { k: "notas", t: "Notas", type: "textarea", wide: true },
    ...(r.uso !== "garaje" ? [{ html: extrasHtml(r) }] : []),
    ...(["confirmada", "checkin"].includes(r.estado) ? [botonAnular("Anular reserva")] : []),
  ], r, async (d, fr) => {
    const ex = fr._extras ? fr._extras() : {};
    await put(`/api/turistico/reservas/${r.id}`, { ...d, ...ex }); toast("Reserva actualizada"); reload();
  });
  const f = $("#modalForm");
  if ($("[data-anular]", f)) $("[data-anular]", f).onclick = () => anular("la reserva", "anulada", `/api/turistico/reservas/${r.id}/anular`, reload);
  if (r.uso !== "garaje") bindExtras(f, r.asset_id, r, () => ({ fecha_entrada: f.elements.fecha_entrada.value, fecha_salida: f.elements.fecha_salida.value })).catch((e) => toast(e.message, true));
}
// ---- precio a pagar: lo propone la tarifa estándar según las noches (ver app/tarifas.py). Sale en naranja; recepción
// puede dejarlo o cambiarlo, pero para continuar tiene que marcar «Acepto el precio» (al cambiar algo se desmarca).
const precioCampos = (titulo = "Precio a pagar € (IVA incluido)") => [
  { k: "importe_total", t: titulo, type: "number", def: 0, req: true },
  { k: "precio_aceptado", t: "Acepto el precio", type: "checkbox" },
  { html: '<p class="muted tarifa-info" data-tarifa></p>', wide: true },
];
function bindPrecio(f, calc) {  // calc(): promesa con la tarifa estándar o null; devuelve la función para recalcular
  const imp = f.elements.importe_total, ok = f.elements.precio_aceptado, info = $("[data-tarifa]", f);
  let t = null;
  imp.classList.add("precio-propuesto");
  const pinta = () => {
    const cambiado = t && Math.abs(Number(imp.value || 0) - t.total) > 0.004;
    info.innerHTML = t ? `Tarifa estándar · <b>${esc(t.nombre)}</b> · ${t.noches} noche(s) · ${esc(t.tramo)} · ${eur(t.por_noche)}/noche = <b>${eur(t.total)}</b>${cambiado ? " · <b>precio cambiado por recepción</b>" : ""}`
      : "Esta unidad no tiene tarifa estándar: indique el precio.";
    ok.closest("label").classList.toggle("precio-pendiente", !ok.checked);
  };
  const recalcula = async () => {
    t = await Promise.resolve(calc()).catch(() => null);
    if (t) imp.value = t.total;
    ok.checked = false; pinta();
  };
  imp.addEventListener("input", () => { ok.checked = false; pinta(); });
  ok.addEventListener("change", pinta);
  f._validaPrecio = () => { if (!ok.checked) throw new Error("Revise el precio a pagar y marque «Acepto el precio» para continuar"); };
  recalcula();
  return recalcula;
}
async function newReservation(reload, fija) {  // fija: {id, codigo, asset_id} para reservar un apartamento concreto
  const aid = fija ? fija.asset_id : await pickAsset("apartamentos_turisticos");
  form(fija ? `Nueva reserva · apartamento ${fija.codigo}` : `Nueva reserva · ${assetName(aid)}`, [
    { k: "fecha_entrada", t: "Entrada", type: "date", req: true, def: today() }, { k: "fecha_salida", t: "Salida", type: "date", req: true, def: addDays(today(), 1) },
    { k: "adultos", t: "Adultos (16 años o más)", type: "number", def: 2, req: true }, { k: "ninos", t: "Menores de 16 (no ocupan plaza)", type: "number", def: 0 },
  ], {}, async (q) => {
    const disp = await get("/api/turistico/disponibilidad", { asset_id: aid, desde: q.fecha_entrada, hasta: q.fecha_salida, capacidad: q.adultos, uso: fija?.uso === "garaje" ? "garaje" : null });
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
      { k: "unit_id", t: "Unidad", type: "select", req: true, options: disp.unidades.map((u) => [u.id, `${u.codigo} ${u.bloque ? "· " + u.bloque : ""} ${u.tipologia ?? ""} ${u.tarifa ? "· " + eur(u.tarifa.total) : u.tarifa_base_noche ? "· " + eur(u.tarifa_base_noche) : ""}`]) },
      { k: "canal", t: "Canal", type: "select", req: true, options: list(S.cat.canales), def: "directo" }, { k: "localizador", t: "Localizador (en blanco: automático)" },
      ...precioCampos(),
      { k: "importe_pagado", t: "Cobrado ahora € (se emite factura)", type: "number", def: 0 },
      { k: "forma_pago", t: "Forma de pago", type: "select", options: kv(S.cat.formas_pago) },
      { k: "facturar_pendiente", t: "Si no se cobra ahora: facturar ya el importe total y dejarlo pendiente de cobro (pagará por transferencia)", type: "checkbox", wide: true },
      { k: "notas", t: "Notas", type: "textarea", wide: true },
      ...(fija?.uso === "garaje" ? [] : [{ html: extrasHtml() }, { html: dotacionAltaHtml() }]),
    ], {}, async (d, fr) => {
      fr._validaPrecio();
      const dotacion_extra = fr._dotacion ? fr._dotacion() : null;  // obligatorio: dotación estándar fijada
      Object.assign(d, fr._extras ? fr._extras() : {});
      const g = {}; guestFields.filter((f) => f.k).forEach((f) => { g[f.k] = d[f.k]; delete d[f.k]; });
      let cliente = { guest: clean(g) };
      if (fr._cliente) {  // cliente habitual: se actualiza su ficha y se reutiliza
        await put(`/api/terceros/${fr._cliente.id}`, { ...clean(g), company_id: fr._cliente.company_id, tipo: "huesped" });
        cliente = { guest_id: fr._cliente.id };
      }
      const cuerpo = { ...clean(d), ...q, unit_id: Number(d.unit_id), ...cliente, documentos: fr._docs.map((x) => x.id), ...(dotacion_extra ? { dotacion_extra } : {}) };
      const nueva = await post("/api/turistico/reservas", cuerpo).catch((e) => {
        if (!String(e.message).startsWith("LISTA NEGRA")) throw e;  // cliente en lista negra: Recepción decide
        if (!confirm(`⚠ CLIENTE EN LISTA NEGRA\n\n${e.message.replace("LISTA NEGRA: ", "Motivo: ")}\n\n¿Reservar igualmente? (quedará registrado)`)) throw new Error("Reserva no creada: cliente en lista negra");
        return post("/api/turistico/reservas", { ...cuerpo, lista_negra_aceptada: true });
      });
      toast("Reserva creada" + (nueva.factura ? ` · Factura ${nueva.factura.codigo}${nueva.factura.cobro === "pendiente" ? " (pendiente de cobro)" : ""}` : "") + ". Complete ahora el contrato (puede guardarlo e imprimirlo a la llegada).");
      reload && reload();
      const seguir = () => (nueva.adultos + nueva.ninos > 1 ? ocupantesReserva(nueva, reload, () => accommodationContract(nueva)) : accommodationContract(nueva));
      if (nueva.factura) setTimeout(() => facturasEmitidas(nueva, seguir), 0); else await seguir();
    }, "Crear reserva")), aid), 0);
    setTimeout(() => {
      const fr = $("#modalForm");
      const recalcula = bindPrecio(fr, () => disp.unidades.find((u) => u.id === Number(fr.elements.unit_id.value))?.tarifa);
      fr.elements.unit_id.addEventListener("change", recalcula);
    }, 0);
    if (fija?.uso !== "garaje") setTimeout(() => bindExtras($("#modalForm"), aid, null, () => q).catch((e) => toast(e.message, true)), 0);
    if (fija?.uso !== "garaje") setTimeout(() => bindDotacionAlta($("#modalForm"), aid).catch((e) => toast(e.message, true)), 0);
  }, "Buscar disponibilidad");
}
// ---- dotación al reservar: la estándar del apartamento es obligatoria (si su tipo aún no la tiene, se fija aquí) y,
// si el cliente necesita algo más, se añade la dotación extraordinaria de esta reserva. Sin nada añadido: la estándar.
const dotacionAltaHtml = () => `<fieldset data-dotalta><legend>Dotación del apartamento</legend><div data-dotest class="muted">Elija el apartamento…</div><div data-dfijar></div>
  <p class="muted peq">Dotación extraordinaria (cuna, trona, juego de toallas más…): elija el artículo y la cantidad total para esta reserva. Si no añade nada, se entrega la estándar.</p>
  <div class="toolbar"><select data-dart><option value="">Artículo…</option></select><input data-dcant value="1" size="6" aria-label="Cantidad"><button type="button" class="btn sm" data-dadd>+ Añadir</button></div><div data-dlista></div></fieldset>`;
async function bindDotacionAlta(f, aid) {
  const box = $("[data-dotalta]", f);
  if (!box) return;
  const cat = await catalogoDotacion(aid);
  const extra = [];
  let d = null;
  const estado = $("[data-dotest]", box), ed = $("[data-dfijar]", box), lista = $("[data-dlista]", box);
  $("[data-dart]", box).insertAdjacentHTML("beforeend", Object.entries(cat.zonas).map(([z, nz]) => `<optgroup label="${esc(nz)}">${cat.articulos.filter((a) => a.zona === z).map((a) => `<option value="${esc(a.codigo)}">${esc(a.articulo)}</option>`).join("")}</optgroup>`).join(""));
  const pintaLista = () => {
    lista.innerHTML = extra.length ? `<ul class="envios">${extra.map((x, i) => `<li>${esc(x.cantidad)} × ${esc(x.articulo)} <button type="button" class="btn sm" data-dq="${i}">Quitar</button></li>`).join("")}</ul>`
      : '<p class="muted">Sin dotación extraordinaria: se entrega la estándar.</p>';
    lista.querySelectorAll("[data-dq]").forEach((b) => (b.onclick = () => { extra.splice(Number(b.dataset.dq), 1); pintaLista(); }));
  };
  $("[data-dadd]", box).onclick = () => {
    const a = cat.articulos.find((x) => x.codigo === $("[data-dart]", box).value), cant = $("[data-dcant]", box).value.trim();
    if (!a || !cant) return toast("Elija el artículo y la cantidad", true);
    const i = extra.findIndex((x) => x.codigo === a.codigo);
    const item = { codigo: a.codigo, zona: a.zona, articulo: a.articulo, cantidad: cant };
    if (i >= 0) extra[i] = item; else extra.push(item);
    pintaLista();
  };
  const carga = async () => {
    ed.innerHTML = "";
    const uid = f.elements.unit_id?.value;
    if (!uid) { d = null; return; }
    d = await get(`/api/dotacion/unidad/${uid}`);
    if (d.fijada) {
      estado.innerHTML = `<span class="cli-ok">✔ Se entrega la dotación estándar ${d.origen === "apartamento" ? "propia de este apartamento" : `de los apartamentos «${esc(d.tipologia || "")}»`} (${d.items.length} artículos).</span>`;
      return;
    }
    estado.innerHTML = `<div class="aviso-vencidas"><b>Obligatorio:</b> los apartamentos «${esc(d.tipologia || "sin tipología")}» aún no tienen fijada su <b>dotación estándar</b>. Revísela (se propone la del catálogo 3 llaves), ajuste lo que haga falta y pulse «Guardar como dotación estándar». Solo hay que hacerlo una vez por tipo de apartamento.</div>
      <div class="toolbar"><button type="button" class="btn primary" data-dver>Revisar y fijar la dotación estándar</button></div>`;
    $("[data-dver]", estado).onclick = () => {
      ed.innerHTML = `<div data-dl></div><div class="toolbar"><button type="button" class="btn primary" data-dg>Guardar como dotación estándar</button></div>`;
      const leer = dotacionEditor($("[data-dl]", ed), cat, d.items, d.perfil, aid);
      $("[data-dg]", ed).onclick = async () => {
        await run(() => put("/api/dotacion/habitual", { asset_id: aid, tipologia: d.tipologia || "", perfil: d.perfil, items: leer() }), "Dotación estándar guardada");
        carga();
      };
    };
  };
  f.elements.unit_id?.addEventListener("change", () => carga().catch((e) => toast(e.message, true)));
  pintaLista();
  await carga();
  f._dotacion = () => {
    if (d && !d.fijada) throw new Error("Fije primero la dotación estándar de este tipo de apartamento (obligatorio): botón «Revisar y fijar la dotación estándar»");
    return extra;
  };
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
  { k: "direccion", t: "Domicilio (para la factura)", wide: true }, { k: "cp", t: "Código postal" }, { k: "municipio", t: "Población" }, { k: "provincia", t: "Provincia" }, { k: "pais", t: "País", def: "España" },
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
      c.estado === "vigente" && ["Anular", () => anular(`el alquiler de la plaza ${c.unidad}`, "anulado", `/api/garajes/contratos/${c.id}/anular`, load), "danger"],
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
    botonAnular("Anular alquiler"),
  ], c, async (d) => { await put(`/api/garajes/contratos/${c.id}`, d); toast("Alquiler actualizado"); reload(); });
  $("[data-anular]", $("#modalForm")).onclick = () => anular(`el alquiler de la plaza ${c.unidad}`, "anulado", `/api/garajes/contratos/${c.id}/anular`, reload);
}

// ---- ampliación de reserva al mismo cliente (los apartamentos turísticos no renuevan): reserva nueva, datos completos y contrato nuevo firmado
async function renovarEstancia(r, reload) {
  const info = await run(() => get(`/api/turistico/reservas/${r.id}/renovacion`));
  const res = info.reserva;
  if (info.pendiente.length) {
    const f = form(`Ampliar reserva · ${res.unidad} · ${res.huesped}: faltan datos`, [
      { html: `<p>Para ampliar la reserva hay que completar los datos del cliente y de los ocupantes (son los del contrato y del parte de viajeros):</p>
        <ul>${info.pendiente.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>
        <p class="muted">Pulse «Completar datos»: escanee el documento o rellene la ficha de cada uno. Al terminar, vuelva a «Ampliar reserva».</p>` },
    ], {}, async () => { setTimeout(() => ocupantesReserva(res, reload, () => renovarEstancia(r, reload)), 0); }, "Completar datos");
    return f;
  }
  form(`Ampliación de reserva · ${res.unidad} · ${res.huesped}`, [
    { html: `<p>Ampliación de reserva al <b>mismo cliente</b> en el mismo apartamento: nueva estancia desde el <b>${fdate(info.desde)}</b> (salida actual, ${info.noches_anteriores} noches la anterior).
      El cliente firma un <b>contrato nuevo</b> y la ampliación se cobra y factura aparte. Los datos del cliente y sus ocupantes se mantienen.</p>` },
    { k: "fecha_salida", t: "Nueva fecha de salida", type: "date", req: true, def: info.hasta },
    ...precioCampos("Precio de la ampliación € (IVA incluido)"),
    { k: "factura", t: "Factura de la ampliación", type: "select", req: true, def: "despues", options: [["despues", "Más tarde (al cobrar)"], ["cobro", "Cobrada ahora: registrar el cobro y facturar"], ["pendiente", "Facturar ya sin cobrar (pagará por transferencia)"]] },
    ...(info.garajes.length ? [{ k: "renovar_garaje", t: `Ampliar también la plaza de garaje ${info.garajes.join(", ")}`, type: "checkbox", def: true, wide: true }] : []),
    { k: "notas", t: "Notas", type: "textarea", wide: true },
  ], {}, async (d, fr) => {
    fr._validaPrecio();
    const factura = d.factura; delete d.factura;
    const nueva = await post(`/api/turistico/reservas/${res.id}/renovar`, clean({ ...d, renovar_garaje: d.renovar_garaje !== false }));
    toast(`Ampliación de reserva ${nueva.localizador} creada. Ahora el cliente firma el contrato.`);
    reload && reload();
    const contrato = () => accommodationContract(nueva);
    if (factura !== "despues" && nueva.importe_total > 0) {  // primero la factura (cobrada o pendiente), luego el contrato
      setTimeout(() => cobroForm(`${factura === "pendiente" ? "Facturar sin cobrar" : "Cobro"} · ampliación de reserva ${nueva.localizador} · ${nueva.unidad}`, nueva.importe_total,
        `/api/turistico/reservas/${nueva.id}/cobro`, reload, nueva.asset_id, factura === "pendiente", contrato), 0);
    } else setTimeout(contrato, 0);
  }, "Ampliar y pasar al contrato");
  const fr = $("#modalForm");
  const recalcula = bindPrecio(fr, () => fr.elements.fecha_salida.value > info.desde
    ? get("/api/turistico/tarifa", { unit_id: res.unit_id, entrada: info.desde, salida: fr.elements.fecha_salida.value }) : null);
  fr.elements.fecha_salida.addEventListener("change", recalcula);
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
      avisoListaNegra(res, { contact_id: c.id, documento: c.documento_num });
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
    can("reservas.editar") && ["Ampliar reserva", () => renovarEstancia(r, reload)],
    can("reservas.editar") && ["Corregir salida", () => editReservation(r, reload)],
    can("reservas.editar") && ["Check-out", () => salidaReserva(r, reload, true)],
    ["Cliente", () => editGuest(r.guest_id, "huesped", reload)],
  ];
  const cols = [{ k: "unidad", t: "Apartamento" }, { k: "huesped", t: "Cliente" }, { k: "telefono", t: "Teléfono", f: (x) => esc(x || "—") },
    { k: "fecha_entrada", t: "Entrada", f: fdate }, { k: "fecha_salida", t: "Salida", f: fdate },
    { k: "dias", t: "Situación", f: (d) => (d > 0 ? `<span class="badge b-cancelada">vencida hace ${d} día${d === 1 ? "" : "s"}</span>` : d === 0 ? '<span class="badge b-pendiente">sale hoy</span>' : `<span class="badge b-pendiente">termina en ${-d} día${d === -1 ? "" : "s"}</span>`) }];
  cont.innerHTML = `<div class="aviso-vencidas"><h4>⚠ Estancias vencidas o que terminan pronto (${v.vencidas.length} vencidas · ${v.proximas.length} en 3 días)</h4>
    <p class="muted">Siguen alojados después de su fecha de salida, o la tienen muy próxima. <b>Ampliar reserva</b>: nueva estancia con contrato nuevo firmado por el cliente (pide los datos que falten). <b>Corregir salida</b>: solo corrige la fecha de salida. O dé la salida. Con teléfono, «WhatsApp» abre el aviso al cliente ya escrito.</p><div data-t></div></div>`;
  table($("[data-t]", cont), cols, [...v.vencidas, ...v.proximas], acc);
}
// ---- ocupación actual exportada del PMS anterior
async function importarOcupacion(reload) {
  const aid = await pickAsset("apartamentos_turisticos");
  const f = form(`Importar ocupación del PMS anterior · ${assetName(aid)}`, [
    { html: `<p>Listado de ocupación exportado del PMS anterior (Excel con una hoja por planta: Localizador, Núm, Sótano/Plaza, FEntrada/FSalida, Ocupante, Teléfonos).</p>
      <ul class="muted"><li>Los <b>alojados</b> quedan con check-in hecho; si su salida ya pasó, como <b>estancia vencida</b> (aviso para ampliar la reserva o dar la salida).</li>
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
    { k: "mes", t: "Mes", type: "month", req: true, def: iso(prev).slice(0, 7) },
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
    <label>Buscar<input id="q" placeholder="Localizador, huésped, unidad"></label><span class="spacer"></span>${can("reservas.editar") ? '<button class="btn" id="dot">Dotación habitual</button><button class="btn" id="fz">Devoluciones de fianza</button><button class="btn" id="ln">Lista negra</button><button class="btn" id="ocu">Importar ocupación (PMS anterior)</button><button class="btn" id="imp">Importar Excel</button><button class="btn primary" id="new">Nueva reserva</button>' : ""}</div><div id="t"></div>`;
  const load = async () => table($("#t", el), resCols, await get("/api/turistico/reservas", { asset_id: S.asset, desde: $("#d", el).value, hasta: $("#h", el).value, estado: $("#e", el).value, q: $("#q", el).value }), resActions(load));
  ["#d", "#h", "#e"].forEach((s) => ($(s, el).onchange = load)); $("#q", el).oninput = debounce(load);
  if ($("#new", el)) $("#new", el).onclick = () => newReservation(load);
  if ($("#imp", el)) $("#imp", el).onclick = () => importarReservas(load);
  if ($("#ocu", el)) $("#ocu", el).onclick = () => importarOcupacion(load);
  if ($("#dot", el)) $("#dot", el).onclick = () => dotacionHabitual();
  if ($("#fz", el)) $("#fz", el).onclick = () => devolucionesFianza();
  if ($("#ln", el)) $("#ln", el).onclick = () => listaNegra();
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
        <td class="peq" style="white-space:normal;min-width:160px">${esc(x.dotacion || "")}</td>
        <td style="white-space:normal;min-width:220px">${x.estado === "valida" ? '<span class="badge b-vigente">válida</span>' : x.estado === "omitida" ? `<span class="badge">omitida</span> ${esc(x.motivo)}` : `<span class="badge b-cancelada">error</span> ${esc(x.motivo)}`}</td></tr>`).join("");
      const pv = form(`Vista previa · ${prev.validas} válidas, ${prev.errores} con error, ${prev.omitidas} omitidas`, [
        { html: `${prev.columnas_ignoradas.length ? `<p class="muted">Columnas no usadas: ${esc(prev.columnas_ignoradas.join(", "))}</p>` : ""}
          <div class="table-wrap" style="max-height:50vh;overflow:auto"><table><thead><tr><th>Fila</th><th>Localizador</th><th>Unidad</th><th>Entrada</th><th>Salida</th><th>Huésped</th><th class="num">Importe</th><th>Dotación</th><th>Resultado</th></tr></thead><tbody>${filas}</tbody></table></div>
          ${prev.sin_dotacion?.length ? `<div class="card aviso-bloqueo"><b>Falta la dotación estándar</b> de los apartamentos «${esc(prev.sin_dotacion.join("», «"))}». Sus reservas no se importan hasta fijarla (una sola vez por tipo de apartamento).
            <p><button type="button" class="btn sm primary" data-fijar>Fijar dotación habitual</button></p></div>` : ""}
          <p>${prev.errores ? "Las filas con error no se importan: corríjalas en el fichero y vuelva a importarlo (las ya importadas no se duplican)." : ""}</p>
          ${prev.filas.some((x) => (x.dotacion || "").includes("(nuevo)")) ? '<p class="muted peq">«(nuevo)»: el artículo no está en el catálogo y se dará de alta como «Otra dotación». Si es un error de escritura, corríjalo en el fichero.</p>' : ""}` },
      ], {}, async () => {
        if (!prev.validas) throw new Error("No hay ninguna reserva válida que importar");
        const r = await enviar(true);
        toast(`${r.importadas} reservas importadas`); reload && reload();
      }, `Importar ${prev.validas} reservas`);
      if ($("[data-fijar]", pv)) $("[data-fijar]", pv).onclick = () => dotacionHabitual(aid);
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
  const load = async () => table($("#t", el), [
    { k: "referencia", t: "Ref." }, { k: "asset_id", t: "Activo", f: (v) => esc(assetName(v)) }, { k: "unidad", t: "Unidad" },
    { k: "inquilino", t: "Inquilino" }, { k: "fecha_inicio", t: "Inicio", f: fdate }, { k: "fecha_fin", t: "Fin", f: fdate },
    { k: "renta_mensual", t: "Renta (sin IVA)", num: true, f: eur }, { k: "fianza", t: "Fianza", num: true, f: eur },
    { k: "indice_actualizacion", t: "Índice" }, { k: "estado", t: "Estado", f: badge },
  ], await get("/api/alquiler/contratos", { asset_id: S.asset, estado: $("#e", el).value }), (l) => can("alquiler.editar") ? [
    ["Expediente", () => expediente(l), "primary"],
    ["Inquilino", () => editGuest(l.tenant_id, "inquilino")],
    l.estado !== "anulado" && ["Editar", () => form(`Contrato ${l.unidad}`, [
      { k: "referencia", t: "Referencia" }, { k: "fecha_fin", t: "Fecha fin", type: "date" }, { k: "fianza", t: "Fianza €", type: "number" },
      { k: "garantia_adicional", t: "Garantía adicional €", type: "number" }, { k: "dia_pago", t: "Día de pago", type: "number" },
      { k: "indice_actualizacion", t: "Índice", type: "select", options: list(["IRAV", "IPC", "NINGUNO"]) },
      ivaField,
      { k: "estado", t: "Estado", type: "select", options: list(["borrador", "vigente", "finalizado", "rescindido"]) },
      { k: "notas", t: "Notas", type: "textarea", wide: true },
      ...(["borrador", "vigente"].includes(l.estado) ? [botonAnular("Anular contrato")] : [])], l, async (d) => { await put(`/api/alquiler/contratos/${l.id}`, d); toast("Contrato actualizado"); load(); })
      && $("[data-anular]", $("#modalForm")) && ($("[data-anular]", $("#modalForm")).onclick = () => anular(`el contrato ${l.referencia || l.unidad}`, "anulado", `/api/alquiler/contratos/${l.id}/anular`, load))],
    ["borrador", "vigente"].includes(l.estado) && ["Anular", () => anular(`el contrato ${l.referencia || l.unidad}`, "anulado", `/api/alquiler/contratos/${l.id}/anular`, load), "danger"],
    l.estado === "vigente" && ["Actualizar renta", () => form(`Actualizar renta (${eur(l.renta_mensual)}) · índice ${l.indice_actualizacion}`, [
      { k: "porcentaje", t: "Variación %", type: "number", req: true }, { k: "motivo", t: "Motivo / referencia índice", wide: true }], {},
      async (d) => { const r = await post(`/api/alquiler/contratos/${l.id}/actualizar-renta`, d); toast(`Nueva renta ${eur(r.renta_mensual)}`); load(); })],
  ] : [["Expediente", () => expediente(l)]]);
  $("#e", el).onchange = load;
  if ($("#new", el)) $("#new", el).onclick = async () => nuevoContrato(await pickAsset("alquiler_residencial"), null, () => load());
  load();
};
const LEASE_FIELDS = [
  { k: "referencia", t: "Referencia" }, { k: "fecha_inicio", t: "Fecha inicio", type: "date", req: true }, { k: "fecha_fin", t: "Fecha fin", type: "date" },
  { k: "renta_mensual", t: "Renta mensual € (sin IVA)", type: "number", req: true }, { k: "fianza", t: "Fianza €", type: "number" },
  ivaField,
  { k: "garantia_adicional", t: "Garantía adicional €", type: "number" }, { k: "dia_pago", t: "Día de pago", type: "number", def: 5 },
  { k: "indice_actualizacion", t: "Índice actualización", type: "select", options: list(["IRAV", "IPC", "NINGUNO"]), def: "IRAV" },
  { k: "estado", t: "Estado", type: "select", options: list(["borrador", "vigente"]), def: "vigente" },
];
// Alta de un contrato de alquiler. fija = {id, codigo}: la vivienda ya elegida (desde su carpeta). despues(lease).
async function nuevoContrato(aid, fija, despues) {
  const units = fija ? [] : (await get("/api/unidades", { asset_id: aid })).filter((u) => u.estado !== "fuera_servicio");
  if (!fija && !units.length) return toast("El activo no tiene unidades. Dé de alta las viviendas primero.", true);
  conEscaner(form(fija ? `Nuevo contrato · vivienda ${fija.codigo} · ${assetName(aid)}` : `Nuevo contrato · ${assetName(aid)}`, [
    { html: scanHtml("1. Escanee el documento del inquilino (DNI, NIE/TIE, pasaporte)") },
    { html: "<h4>Inquilino</h4>" }, ...guestFields,
    { html: "<h4>Contrato</h4>" },
    ...(fija ? [] : [{ k: "unit_id", t: "Unidad", type: "select", req: true, options: units.map((u) => [u.id, `${u.codigo} · ${label(u.uso)} · ${label(u.estado)}`]) }]), ...LEASE_FIELDS,
    { k: "notas", t: "Notas contrato", type: "textarea", wide: true },
  ], {}, async (d, fr) => {
    const t = {}; guestFields.filter((f) => f.k).forEach((f) => { t[f.k] = d[f.k]; delete d[f.k]; });
    const lease = await post("/api/alquiler/contratos", { ...clean(d), unit_id: fija ? fija.id : Number(d.unit_id), tenant: clean(t), documentos: fr._docs.map((x) => x.id) });
    toast("Contrato creado"); despues && setTimeout(() => despues(lease), 0);
  }));
}

// ---- expediente del contrato de vivienda (LAU): checklist, datos, inventario, cobros, carpeta y agenda
// Campos sueltos dentro de una ventana ya abierta (mismo formato que form()).
function camposHtml(fields, init = {}) {
  return `<div class="grid">${fields.map((fd) => {
    if (fd.html) return `<div class="wide">${fd.html}</div>`;
    const v = init[fd.k] ?? fd.def ?? "";
    let inp;
    if (fd.type === "select") inp = `<select name="${fd.k}">${fd.req ? "" : '<option value=""></option>'}${fd.options.map(([o, l]) => `<option value="${esc(o)}" ${String(o) === String(v) ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
    else if (fd.type === "textarea") inp = `<textarea name="${fd.k}">${esc(v)}</textarea>`;
    else if (fd.type === "checkbox") return `<label class="check ${fd.wide ? "wide" : ""}"><input type="checkbox" name="${fd.k}" ${v ? "checked" : ""}> ${esc(fd.t)}</label>`;
    else inp = `<input name="${fd.k}" type="${fd.type || "text"}" value="${esc(v)}" ${fd.type === "number" ? 'step="any"' : ""}>`;
    return `<label class="${fd.wide ? "wide" : ""}">${esc(fd.t)}${fd.req ? " *" : ""}${inp}</label>`;
  }).join("")}</div>`;
}
function leeCampos(cont, fields) {
  const d = {};
  fields.filter((fd) => fd.k && !fd.html).forEach((fd) => {
    const x = cont.querySelector(`[name="${fd.k}"]`);
    if (!x) return;
    d[fd.k] = fd.type === "checkbox" ? x.checked : x.value === "" ? null : fd.type === "number" ? Number(x.value) : x.value;
  });
  return d;
}
// Tabla editable de inventario. botones: [[texto, fn]] extra; guardar(filas) persiste.
function editorInventario(cont, inicial, { editar = true, nota = "", botones = [], guardar }) {
  let filas = inicial.map((i) => ({ ...i }));
  const leer = () => (filas = [...cont.querySelectorAll("tr[data-n]")].map((tr) => {
    const o = {}; tr.querySelectorAll("[data-c]").forEach((c) => (o[c.dataset.c] = c.type === "checkbox" ? c.checked : c.dataset.c === "uds" ? Number(c.value || 0) : c.value)); return o;
  }));
  const dibuja = () => {
    cont.innerHTML = `${nota}<div class="table-wrap"><table class="inv"><thead><tr><th>Se entrega</th><th>Estancia</th><th>Elemento / marca / modelo</th><th>Uds.</th><th>Estado</th><th>Observaciones</th><th></th></tr></thead><tbody>
      ${filas.map((i, n) => `<tr data-n="${n}"><td><input type="checkbox" data-c="entrega" ${i.entrega !== false ? "checked" : ""}></td>
        <td><input data-c="estancia" value="${esc(i.estancia)}"></td><td><input data-c="elemento" value="${esc(i.elemento)}"></td>
        <td><input data-c="uds" type="number" min="0" value="${esc(i.uds ?? 1)}" style="width:4.5em"></td>
        <td><select data-c="estado">${[["N", "Nuevo"], ["B", "Bueno"], ["U", "Con uso"]].map(([v, t]) => `<option value="${v}" ${i.estado === v ? "selected" : ""}>${t}</option>`).join("")}</select></td>
        <td><input data-c="obs" value="${esc(i.obs)}"></td><td>${editar ? '<button type="button" class="btn sm" data-quita>✕</button>' : ""}</td></tr>`).join("")}</tbody></table></div>
      ${editar ? `<div class="toolbar"><button type="button" class="btn" data-mas>+ Añadir elemento</button>${botones.map(([t], i) => `<button type="button" class="btn" data-extra="${i}">${esc(t)}</button>`).join("")}
        <span class="spacer"></span><button type="button" class="btn primary" data-guardar>Guardar inventario</button></div>` : ""}`;
    if (!editar) return;
    cont.querySelectorAll("[data-quita]").forEach((b) => (b.onclick = () => { leer(); filas.splice(Number(b.closest("tr").dataset.n), 1); dibuja(); }));
    cont.querySelectorAll("[data-extra]").forEach((b) => (b.onclick = botones[b.dataset.extra][1]));
    $("[data-mas]", cont).onclick = () => { leer(); filas.push({ estancia: "", elemento: "", uds: 1, estado: "B", obs: "", entrega: true }); dibuja(); };
    $("[data-guardar]", cont).onclick = () => {
      leer();
      if (filas.some((i) => !i.elemento.trim())) return toast("Hay filas sin elemento", true);
      guardar(filas);
    };
  };
  dibuja();
}
const EXP_ESTADO = { hecho: ["✔", "b-vigente", "Hecho"], no_aplica: ["–", "b-baja", "No aplica"], pendiente: ["○", "b-pendiente", "Pendiente"] };
const CONTADORES = ["Electricidad", "Gas", "Agua fría", "Agua caliente (si existe)", "Calefacción (repartidores)"];

async function expediente(l, pestana = "checklist") {
  const url = `/api/alquiler/contratos/${l.id}/expediente`;
  let x = await run(() => get(url));
  const asset = S.assets.find((a) => a.id === x.contrato.asset_id) || {};
  const personas = await get("/api/terceros", { tipo: "inquilino", asset_id: x.contrato.asset_id }).catch(() => []);
  const editar = can("alquiler.editar");
  const f = cerrarSolo(form(`Expediente ${x.referencia} · ${x.contrato.inquilino}`, [{ html: `
    <p class="muted">${esc(x.vivienda)} · renta ${eur(x.contrato.renta_mensual)}/mes · ${fdate(x.contrato.fecha_inicio)} → ${fdate(x.contrato.fecha_fin)} · ${badge(x.contrato.estado)}</p>
    <div class="chips" data-tabs>${[["checklist", "✅ Checklist"], ["datos", "📝 Datos del contrato"], ["inventario", "🛋️ Inventario"], ["cobros", "💶 Cobros y recibos"], ["carpeta", "📁 Carpeta"], ["agenda", "📅 Agenda"]]
      .map(([k, t]) => `<button type="button" class="chip" data-tab="${k}">${t}</button>`).join("")}</div>
    <div data-aviso></div><div data-cuerpo class="expediente"></div>` }], {}, async () => {}));
  $("#modal").classList.add("ancho");
  const cuerpo = $("[data-cuerpo]", f);
  const guarda = async (fn, msg) => { x = await run(fn, msg); pinta(); };
  const subir = (clave, nombre) => {
    const inp = Object.assign(document.createElement("input"), { type: "file", accept: ".pdf,.jpg,.jpeg,.png,.docx,image/*" });
    inp.onchange = () => { if (!inp.files[0]) return; const fd = new FormData(); fd.append("fichero", inp.files[0]); fd.append("clave", clave); if (nombre) fd.append("nombre", nombre);
      guarda(() => upload(`${url}/documentos`, fd), "Documento guardado en la carpeta"); };
    inp.click();
  };
  const descargarContrato = () => {
    if (x.faltan.length && !confirm(`Faltan datos (${x.faltan.length}). El contrato saldrá con esos huecos resaltados en amarillo para completarlos a mano.\n\n¿Descargarlo igualmente?`)) return;
    toast("Preparando el contrato (cuenta las páginas)…");
    run(() => download("GET", `${url}/contrato.docx`));
  };

  const vistas = {
    checklist() {
      const fase = (k, t) => `<h4>${t}</h4><ul class="checklist">${x.checklist.filter((c) => c.fase === k).map((c) => {
        const [ic, cls, txt] = EXP_ESTADO[c.estado];
        return `<li class="ck-${c.estado}${c.vencido ? " vencido" : ""}"><span class="badge ${cls}" title="${txt}">${ic}</span>
          <div><b>${esc(c.texto)}</b>${c.auto && c.estado === "hecho" ? ' <span class="muted">(comprobado por el PMS)</span>' : ""}
          ${c.motivo ? `<br><span class="error">${esc(c.motivo)}</span>` : ""}
          ${c.limite ? `<br><span class="${c.vencido ? "error" : "muted"}">Fecha límite: ${fdate(c.limite)}${c.vencido ? " · VENCIDO" : ""}</span>` : ""}
          ${c.marcado_por ? `<br><span class="muted">Marcado por ${esc(c.marcado_por)} · ${fdt(c.marcado_en)}${c.nota ? " · " + esc(c.nota) : ""}</span>` : ""}
          ${c.documentos ? `<br><span class="muted">📎 ${c.documentos} documento(s) en la carpeta</span>` : ""}</div>
          ${editar ? `<div class="ck-acc"><select data-ck="${c.clave}">${[["", "Automático"], ["hecho", "Hecho"], ["no_aplica", "No aplica"], ["pendiente", "Pendiente"]].map(([v, t]) => `<option value="${v}" ${(c.marcado_por ? c.estado : "") === v ? "selected" : ""}>${t}</option>`).join("")}</select>
          ${c.documento ? `<button type="button" class="btn sm" data-sube="${c.clave}">📎 Subir</button>` : ""}</div>` : ""}</li>`;
      }).join("")}</ul>`;
      const hechos = x.checklist.filter((c) => c.estado !== "pendiente").length;
      cuerpo.innerHTML = `<p><b>${hechos} de ${x.checklist.length}</b> puntos resueltos. Los que el PMS puede comprobar (certificado energético, IBI, cobros, alta y avisos) se marcan solos.</p>
        ${fase("antes", "Antes de firmar y entregar llaves")}${fase("despues", "Después de la firma")}`;
      cuerpo.querySelectorAll("[data-ck]").forEach((s) => (s.onchange = () => {
        const estado = s.value || null;
        const nota = estado === "no_aplica" ? prompt("¿Por qué no aplica? (opcional)") : null;
        guarda(() => put(`${url}/checklist/${s.dataset.ck}`, { estado, nota }), "Checklist actualizado");
      }));
      cuerpo.querySelectorAll("[data-sube]").forEach((b) => (b.onclick = () => subir(b.dataset.sube)));
    },
    datos() {
      const d = { ...x.datos };
      const lect = d.acta?.lecturas || {};
      CONTADORES.forEach((n, i) => (d[`lectura_${i}`] = lect[n]));
      d.animales = !!d.animales;
      if (!d.periodo_desde) d.periodo_desde = x.contrato.fecha_inicio;
      if (!d.importe_inicial) d.importe_inicial = x.contrato.renta_mensual;
      const per = [["", "—"], ...personas.filter((p) => p.id !== x.contrato.tenant_id).map((p) => [p.id, `${p.nombre} ${p.apellidos || ""} · ${p.documento_num || "sin documento"}`])];
      const campos = [
        { html: "<h4>Firma y entrega de llaves</h4>" },
        { k: "fecha_firma", t: "Fecha de firma", type: "date", req: true }, { k: "hora_firma", t: "Hora de firma", type: "time" },
        { k: "fecha_entrega", t: "Entrega de llaves (si es otro día)", type: "date" }, { k: "hora_entrega", t: "Hora de entrega", type: "time" },
        { k: "presentes", t: "Presentes en la entrega", wide: true },
        { html: "<h4>Partes</h4><p class='muted'>El arrendatario principal es el del contrato. Si hay un segundo arrendatario o un fiador, elija su ficha (o créela con «Nueva persona»).</p>" },
        { k: "arrendatario2_id", t: "Segundo arrendatario", type: "select", options: per }, { k: "fiador_id", t: "Fiador (solo si la garantía es «fiador»)", type: "select", options: per },
        { k: "domicilio_anterior", t: "Domicilio anterior del arrendatario (si no es el de su ficha)", wide: true },
        { html: "<h4>Renta y garantías</h4>" },
        { k: "forma_pago", t: "Pago de la renta", type: "select", options: [["transferencia", "Transferencia del inquilino"], ["sepa", "Domiciliación SEPA"]], def: "transferencia" },
        { k: "iban_arrendatario", t: "IBAN del inquilino (si se domicilia)" },
        { k: "importe_inicial", t: "Importe que paga a la firma (1er periodo) €", type: "number" },
        { k: "periodo_desde", t: "Primer periodo: desde", type: "date" }, { k: "periodo_hasta", t: "Primer periodo: hasta", type: "date" },
        { k: "garantia_modalidad", t: "Garantía adicional", type: "select", options: kv(x.opciones.garantia), def: "deposito" },
        { k: "aval_vencimiento", t: "Vencimiento del aval (si hay aval)", type: "date" },
        { html: "<h4>Ocupación y condiciones</h4>" },
        { k: "convivientes", t: "Personas que convivirán (nombre y DNI)", wide: true }, { k: "max_ocupantes", t: "Nº máximo de ocupantes", type: "number" },
        { k: "anejos", t: "Anejos (trastero, plaza)" }, { k: "seguro_capital", t: "Capital RC del seguro de hogar €", type: "number", def: 150000 },
        { k: "animales", t: "Se permiten animales", type: "checkbox" }, { k: "animales_detalle", t: "Animales permitidos (tipo y nº)" },
        { html: "<h4>Acta de entrega (Anexo II)</h4><p class='muted'>Las lecturas se pueden dejar en blanco y escribirlas a mano el día de la entrega.</p>" },
        ...CONTADORES.map((n, i) => ({ k: `lectura_${i}`, t: `Lectura ${n}` })),
        { k: "fotos", t: "Nº de fotografías del reportaje", type: "number" }, { k: "otros_docs", t: "Otros documentos aportados (Anexo III)", wide: true },
      ];
      cuerpo.innerHTML = `${x.faltan.length ? `<div class="aviso-faltan"><b>Faltan ${x.faltan.length} dato(s) para imprimir el contrato completo:</b> ${x.faltan.map(esc).join(" · ")}
          <br><span class="muted">Los de la sociedad se completan en Sociedades → Editar → «Datos para contratos»; los de la vivienda en Unidades → «Ficha alquiler».</span></div>`
          : '<p class="ok">✔ Están todos los datos para imprimir el contrato.</p>'}
        ${camposHtml(campos, d)}
        <div class="toolbar">${editar ? '<button type="button" class="btn" data-nueva>+ Nueva persona</button><button type="button" class="btn primary" data-guardar>Guardar datos</button>' : ""}
        <button type="button" class="btn" data-word>⬇ Contrato (Word)</button></div>`;
      $("[data-word]", cuerpo).onclick = descargarContrato;
      if (!editar) return;
      $("[data-guardar]", cuerpo).onclick = () => {
        const v = leeCampos(cuerpo, campos);
        const lecturas = {};
        CONTADORES.forEach((n, i) => { if (v[`lectura_${i}`]) lecturas[n] = v[`lectura_${i}`]; delete v[`lectura_${i}`]; });
        if (Object.keys(lecturas).length) v.acta = { lecturas };
        ["arrendatario2_id", "fiador_id"].forEach((k) => (v[k] = v[k] ? Number(v[k]) : null));
        if (!v.animales) v.animales = null;
        guarda(() => put(`${url}/datos`, clean(v)), "Datos guardados");
      };
      $("[data-nueva]", cuerpo).onclick = () => conEscaner(form("Nueva persona (segundo arrendatario o fiador)", [{ html: scanHtml() }, ...guestFields], {}, async (d, fr) => {
        await post("/api/terceros", { ...clean(d), tipo: "inquilino", company_id: asset.company_id, asset_id: x.contrato.asset_id, documentos: fr._docs.map((y) => y.id) });
        toast("Ficha creada: elíjala en «Segundo arrendatario» o «Fiador»");
        expediente(l, "datos");
      }));
    },
    inventario() {
      editorInventario(cuerpo, x.inventario, {
        editar, nota: `<p>Solo se imprime en el Anexo I lo marcado <b>«Se entrega»</b>. ${x.inventario_propio ? "Este contrato tiene su propio inventario." : "Se parte del inventario de la ficha de la vivienda."}</p>`,
        botones: x.inventario_propio ? [["Volver al de la vivienda", () => guarda(() => put(`${url}/inventario`, null), "Inventario de la vivienda")]] : [],
        guardar: (filas) => guarda(() => put(`${url}/inventario`, filas), "Inventario guardado"),
      });
    },
    cobros() {
      const lim = x.opciones.limite_efectivo;
      cuerpo.innerHTML = `${x.pendiente_cobro.length ? `<p class="error"><b>Pendiente de cobrar:</b> ${x.pendiente_cobro.map(esc).join(", ")}. No entregar las llaves hasta cobrarlo.</p>` : '<p class="ok">✔ Todo cobrado.</p>'}
        <div data-tabla></div>
        ${editar ? `<h4>Registrar una entrega de dinero (o un aval)</h4>${camposHtml(campos())}
          <p class="muted">Efectivo: nunca para la renta (cláusula 4.2) ni para ${eur(lim)} o más en total (Ley 7/2012). Cheque: el recibo queda «salvo buen fin».</p>
          <div class="toolbar"><span class="spacer"></span><button type="button" class="btn primary" data-alta>Registrar y ver recibo</button></div>` : ""}`;
      table($("[data-tabla]", cuerpo), [{ k: "numero", t: "Recibo" }, { k: "fecha", t: "Fecha", f: fdate },
        { k: "concepto", t: "Concepto", f: (v, e) => esc(e.concepto_texto || x.opciones.conceptos[v]) }, { k: "importe", t: "Importe", num: true, f: eur },
        { k: "forma", t: "Forma", f: (v, e) => esc(x.opciones.formas[v]) + (e.referencia ? ` · ${esc(e.referencia)}` : "") },
        { k: "anulada", t: "", f: (v, e) => (v ? `<span class="badge b-baja" title="${esc(e.motivo_anulacion)}">anulada</span>` : "") }],
      x.entregas, (e) => [["Recibo PDF", () => abrirFichero(`${url}/entregas/${e.n}/recibo`)],
        editar && !e.anulada && ["Anular", () => { const m = prompt("Motivo de la anulación:"); if (m) guarda(() => post(`${url}/entregas/${e.n}/anular`, { motivo: m }), "Entrega anulada"); }, "danger"],
        editar && ["📎 Firmado", () => subir("recibo", `Recibo ${e.numero} firmado`)]]);
      if (!editar) return;
      const forma = $("[name=forma]", cuerpo), concepto = $("[name=concepto]", cuerpo);
      const ajusta = () => {
        const efe = forma.querySelector("option[value=efectivo]");
        efe.disabled = concepto.value === "renta_inicial";
        if (efe.disabled && forma.value === "efectivo") forma.value = "transferencia";
        forma.querySelector("option[value=aval]").disabled = concepto.value !== "garantia";
        const imp = { renta_inicial: x.datos.importe_inicial, fianza: x.contrato.fianza, garantia: x.contrato.garantia_adicional }[concepto.value];
        const ya = x.entregas.filter((e) => !e.anulada && e.concepto === concepto.value).reduce((s, e) => s + Number(e.importe), 0);
        if (imp != null) $("[name=importe]", cuerpo).value = Math.max(0, Number(imp) - ya) || "";
      };
      concepto.onchange = ajusta; ajusta();
      $("[data-alta]", cuerpo).onclick = async () => {
        const v = leeCampos(cuerpo, campos());
        if (!v.importe || !v.fecha) return toast("Indique importe y fecha", true);
        if (v.forma === "efectivo" && v.importe >= lim) return toast(`En efectivo no se admiten ${eur(lim)} o más`, true);
        const antes = x.entregas.length;
        x = await run(() => post(`${url}/entregas`, clean(v)), "Entrega registrada");
        pinta();
        if (x.entregas.length > antes) abrirFichero(`${url}/entregas/${x.entregas.length}/recibo`);
      };
    },
    carpeta() {
      const cl = x.opciones.claves_doc;
      cuerpo.innerHTML = `<p>Toda la documentación del contrato, cifrada en el servidor. Suba aquí el contrato firmado escaneado, los recibos firmados, el justificante de la fianza, el seguro…</p>
        ${editar ? `<div class="toolbar"><select data-clave>${Object.entries(cl).map(([k, t]) => `<option value="${k}">${esc(t.length > 70 ? t.slice(0, 70) + "…" : t)}</option>`).join("")}</select>
          <button type="button" class="btn primary" data-sube>📎 Subir documento</button></div>` : ""}<div data-tabla></div>`;
      table($("[data-tabla]", cuerpo), [{ k: "clave", t: "Tipo", f: (v) => esc((cl[v] || v).split(":")[0].slice(0, 60)) }, { k: "nombre", t: "Documento" },
        { k: "subido", t: "Subido", f: fdt }, { k: "usuario", t: "Por" }, { k: "tamano", t: "Tamaño", num: true, f: (v) => `${Math.ceil(v / 1024)} KB` }],
      x.documentos, (d) => [["Ver", () => (d.mime.includes("word") ? run(() => download("GET", `${url}/documentos/${d.id}`)) : abrirFichero(`${url}/documentos/${d.id}`))],
        editar && ["Borrar", () => confirm(`¿Borrar «${d.nombre}»?`) && guarda(() => api("DELETE", `${url}/documentos/${d.id}`), "Documento borrado"), "danger"]]);
      if (editar) $("[data-sube]", cuerpo).onclick = () => subir($("[data-clave]", cuerpo).value);
    },
    agenda() {
      cuerpo.innerHTML = `<p>Se crean en <b>su agenda</b> (privadas) la firma, la entrega de llaves, los cobros, el depósito de la fianza (30 días), el seguro y los suministros (15 días), la actualización anual de la renta, la revisión de caldera/gas, el preaviso de vencimiento (4 meses) y el vencimiento del aval. Si cambian las fechas, vuelva a pulsar el botón y se actualizan. Al marcar un punto del checklist como hecho, su tarea queda hecha.</p>
        ${editar ? '<div class="toolbar"><button type="button" class="btn primary" data-gen>📅 Crear / actualizar en mi agenda</button></div>' : ""}
        <ul class="envios">${x.agenda.map((e) => `<li>${e.hecha ? "✔ " : ""}<b>${e.todo_el_dia ? fdate(e.inicio.slice(0, 10)) : fdt(e.inicio).slice(0, -3)}</b> · ${esc(e.titulo)}${e.repeticion ? ` · ${esc(e.repeticion)}` : ""}</li>`).join("") || '<li class="muted">Todavía no hay citas generadas.</li>'}</ul>`;
      if (editar) $("[data-gen]", cuerpo).onclick = () => guarda(() => post(`${url}/agenda`), "Agenda actualizada");
    },
  };
  function campos() {
    return [
      { k: "concepto", t: "Concepto", type: "select", req: true, options: kv(x.opciones.conceptos), def: x.pendiente_cobro.includes("primer periodo") ? "renta_inicial" : x.pendiente_cobro.includes("fianza") ? "fianza" : "garantia" },
      { k: "concepto_texto", t: "Descripción (si es «otro»)" },
      { k: "importe", t: "Importe €", type: "number", req: true },
      { k: "forma", t: "Forma de entrega", type: "select", req: true, options: kv(x.opciones.formas), def: "transferencia" },
      { k: "referencia", t: "Ref. transferencia / nº cheque / nº aval" }, { k: "entidad", t: "Banco (cheque o aval)" },
      { k: "fecha", t: "Fecha", type: "date", req: true, def: today() }, { k: "vencimiento", t: "Vencimiento del aval", type: "date" },
      { k: "periodo", t: "Periodo (1ª mensualidad)", def: x.datos.periodo_desde ? `${fdate(x.datos.periodo_desde)} – ${fdate(x.datos.periodo_hasta)}` : "" },
      { k: "pagador", t: "Paga otra persona (nombre)" }, { k: "pagador_doc", t: "Su DNI/NIE" },
      { k: "observaciones", t: "Observaciones", wide: true },
    ];
  }
  let actual = pestana;
  function pinta() {
    f.querySelectorAll("[data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === actual));
    const venc = x.checklist.filter((c) => c.vencido);
    $("[data-aviso]", f).innerHTML = venc.length ? `<p class="error">⚠ Plazo vencido: ${venc.map((c) => esc(c.texto.split(":")[0].split("(")[0])).join(" · ")}</p>` : "";
    vistas[actual]();
  }
  f.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => { actual = b.dataset.tab; pinta(); }));
  pinta();
}

// Ficha de la vivienda para los contratos: registro, certificado energético, tributos, llaves, contadores e inventario
async function fichaAlquiler(u) {
  const d = await run(() => get(`/api/unidades/${u.id}/ficha-alquiler`));
  const fi = d.ficha;
  const init = { ...fi };
  d.llaves.forEach((x, i) => { init[`ll_uds_${i}`] = x.uds; init[`ll_obs_${i}`] = x.obs; });
  d.contadores.forEach((x, i) => { init[`ct_cups_${i}`] = x.cups; init[`ct_tit_${i}`] = x.titular; });
  const campos = [
    { html: "<h4>Vivienda</h4>" }, { k: "puerta", t: "Puerta (letra)" }, { k: "cp", t: "Código postal" },
    { k: "superficie_util", t: "Superficie útil m²", type: "number" }, { k: "distribucion", t: "Distribución (p. ej. 2 dormitorios, salón, cocina y baño)", wide: true },
    { k: "registro_propiedad", t: "Registro de la Propiedad de Madrid nº (solo el número)" }, { k: "finca", t: "Finca registral nº" },
    { html: "<h4>Certificado de eficiencia energética</h4>" },
    { k: "cee_letra", t: "Calificación", type: "select", options: list(["A", "B", "C", "D", "E", "F", "G"]) }, { k: "cee_registro", t: "Nº de registro" },
    { k: "cee_vigencia", t: "Vigente hasta", type: "date" },
    { html: "<h4>Tributos que se repercuten (último recibo)</h4>" },
    { k: "ibi_anual", t: "IBI anual €", type: "number" }, { k: "tasa_residuos_anual", t: "Tasa de residuos anual €", type: "number" },
    { k: "sin_contador", t: "Suministros sin contador individual (cuál)" }, { k: "sin_contador_importe", t: "Importe mensual de esos suministros €", type: "number" },
    { html: "<h4>Llaves (Anexo II)</h4>" }, { k: "bombin", t: "Bombín de la puerta (marca / modelo)", wide: true },
    ...d.llaves.flatMap((x, i) => [{ k: `ll_uds_${i}`, t: `${x.elemento}: uds.`, type: "number" }, { k: `ll_obs_${i}`, t: "Observaciones" }]),
    { html: "<h4>Contadores (Anexo II)</h4>" },
    ...d.contadores.flatMap((x, i) => [{ k: `ct_cups_${i}`, t: `${x.suministro}: nº contador / CUPS` }, { k: `ct_tit_${i}`, t: "Titular actual" }]),
    { html: `<h4>Inventario</h4><p class="muted">${d.inventario_propio ? d.inventario.length + " elementos." : "Todavía no tiene inventario propio: se usa el inventario tipo."} Se ajusta en el expediente de cada contrato o aquí con «Inventario».</p>` },
  ];
  const f = form(`Ficha para contratos · ${u.codigo}`, campos, init, async (v) => {
    const ficha = {};
    Object.entries(v).forEach(([k, val]) => { if (!/^(ll|ct)_/.test(k)) ficha[k] = val; });
    ficha.llaves = d.llaves.map((x, i) => ({ elemento: x.elemento, uds: v[`ll_uds_${i}`], obs: v[`ll_obs_${i}`] || "" })).filter((x) => x.uds != null || x.obs);
    ficha.contadores = d.contadores.map((x, i) => ({ suministro: x.suministro, cups: v[`ct_cups_${i}`] || "", titular: v[`ct_tit_${i}`] || "" })).filter((x) => x.cups || x.titular);
    await put(`/api/unidades/${u.id}/ficha-alquiler`, { ficha: clean(ficha) });
    toast("Ficha guardada");
  });
  const b = Object.assign(document.createElement("button"), { type: "button", className: "btn", textContent: "Inventario" });
  b.onclick = () => inventarioVivienda(u, d.inventario);
  $(".actions", f).prepend(b);
}
function inventarioVivienda(u, inv) {
  const f = cerrarSolo(form(`Inventario · ${u.codigo}`, [{ html: "<div data-inv></div>" }], {}, async () => {}));
  $("#modal").classList.add("ancho");
  editorInventario($("[data-inv]", f), inv, {
    nota: '<p class="muted">Inventario de esta vivienda: cada contrato nuevo parte de él. Marque «Se entrega» solo lo que se entrega con la vivienda.</p>',
    guardar: async (filas) => {
      const d = await run(() => get(`/api/unidades/${u.id}/ficha-alquiler`));
      await run(() => put(`/api/unidades/${u.id}/ficha-alquiler`, { ficha: d.ficha, inventario: filas }), "Inventario guardado");
    },
  });
}

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
    <label>Buscar<input id="q" placeholder="Nº de factura, cliente, concepto"></label>
    <label>Cobro<select id="c"><option value="">Todas</option><option value="pendiente" ${S.filtroCobro === "pendiente" ? "selected" : ""}>Pendientes de cobro</option><option value="cobrada">Cobradas</option></select></label><span class="spacer"></span>
    <span class="muted peq" title="Criterio de la gestoría">Fecha de factura: último día del mes de emisión</span>
    <button class="btn" id="csv">Libro de facturas emitidas (Excel)</button>${can("reservas.editar") || can("alquiler.editar") ? '<button class="btn primary" id="fsrv">Nueva factura de servicios</button>' : ""}</div><div id="t"></div><p id="tot"></p>`;
  S.filtroCobro = null;
  const filtros = () => ({ asset_id: S.asset, anio: $("#c", el).value === "pendiente" ? "" : $("#y", el).value, serie: $("#s", el).value, q: $("#q", el).value, cobro: $("#c", el).value });
  const load = async () => {
    const rows = await get("/api/facturas", filtros());
    table($("#t", el), [
      { k: "codigo", t: "Factura", f: (v, r) => `<b>${esc(v)}</b>`
        + (r.tipo === "ordinaria" && r.cobro === "pendiente" ? `<br><span class="badge b-cancelada">pendiente de cobro · ${Math.max(0, Math.round((new Date(today()) - new Date(r.creada.slice(0, 10))) / 864e5))} días</span>` : "")
        + (r.cobro_marcado ? `<br><span class="badge b-vigente" title="${esc(`${r.cobro_forma || ""} ${r.cobro_ref || ""} · comprobado por ${r.cobro_usuario || ""}`)}">cobrada ${fdate(r.cobro_fecha)}</span>` : "") },
      { k: "fecha_expedicion", t: "Fecha", f: fdate }, { k: "activo", t: "Activo" },
      { k: "cliente", t: "Cliente", f: (v) => esc(v.nombre) }, { k: "cliente", t: "NIF", f: (v) => esc(v.nif || "") },
      { k: "concepto", t: "Concepto", f: (v, r) => { const p = r.lineas[0].concepto; return `<span title="${esc(v)}">${esc(p.length > 55 ? p.slice(0, 55) + "…" : p)}${r.lineas.length > 1 ? ` <span class="badge">+${r.lineas.length - 1}</span>` : ""}</span>`; } },
      { k: "base_imponible", t: "Base", num: true, f: eur }, { k: "tipo_iva", t: "IVA", num: true, f: (v, r) => r.desglose.map((x) => (x.tipo_iva == 0 ? "Exento" : x.tipo_iva + " %")).join(" + ") },
      { k: "cuota_iva", t: "Cuota", num: true, f: eur }, { k: "total", t: "Total", num: true, f: eur },
      { k: "tipo", t: "", f: (v, r) => (v === "rectificativa" ? badge("rectificativa") : r.rectificada_por ? `<span class="badge b-rectificada">rectificada por ${esc(r.rectificada_por)}</span>` : "") },
    ], rows, (r) => [
      ["PDF", () => descargarFactura(r.id)],
      r.cobro === "pendiente" && r.tipo === "ordinaria" && (can("reservas.editar") || can("facturas.rectificar") || can("alquiler.editar")) && ["Cobrada", () => form(`Factura ${r.codigo} cobrada (${eur(r.total)})`, [
        { html: `<p>Cliente: <b>${esc(r.cliente.nombre)}</b>. Compruebe en el banco que ha llegado el pago antes de marcarla.</p>` },
        { k: "fecha", t: "Fecha del cobro", type: "date", req: true, def: today() },
        { k: "forma_pago", t: "Forma de pago", type: "select", req: true, options: kv(S.cat.formas_pago), def: "transferencia" },
        { k: "referencia", t: "Referencia (concepto de la transferencia, nº de operación…)", wide: true },
      ], {}, async (d) => { await post(`/api/facturas/${r.id}/cobro`, clean(d)); toast(`Factura ${r.codigo} marcada como cobrada`); load(); }, "Marcar cobrada"), "primary"],
      r.cobro_marcado && (can("reservas.editar") || can("facturas.rectificar") || can("alquiler.editar")) && !r.rectificada_por && ["Deshacer cobro", () => form(`Deshacer el cobro de ${r.codigo}`, [
        { html: "<p>La factura vuelve a quedar <b>pendiente de cobro</b> (solo si el cobro se marcó por error).</p>" },
        { k: "motivo", t: "Motivo", type: "textarea", req: true, wide: true }], {}, async (d) => { await post(`/api/facturas/${r.id}/cobro/deshacer`, d); toast("Cobro deshecho"); load(); }, "Deshacer cobro")],
      can("facturas.rectificar") && r.tipo === "ordinaria" && !r.rectificada_por && ["Rectificar", () => form(`Rectificar la factura ${r.codigo} (${eur(r.total)})`, [
        { html: `<p>Se emitirá una <b>factura rectificativa</b> por ${eur(-r.total)} en la serie ${esc(r.serie)}R que anula esta factura${r.cobro === "pendiente" ? ". Estaba pendiente de cobro: deja de estarlo" : ", y se deshará el cobro (el recibo o la reserva vuelven a quedar pendientes por ese importe)"}.</p>` },
        { k: "motivo", t: "Motivo de la rectificación", type: "textarea", req: true, wide: true },
      ], {}, async (d) => { const x = await post(`/api/facturas/${r.id}/rectificar`, d); toast(`Rectificativa ${x.codigo} emitida`); load(); await descargarFactura(x.id); }, "Emitir rectificativa"), "danger"],
    ]);
    const sum = (k) => rows.reduce((a, x) => a + Number(x[k]), 0);
    $("#tot", el).innerHTML = rows.length ? `Base imponible <b>${eur(sum("base_imponible"))}</b> · IVA <b>${eur(sum("cuota_iva"))}</b> · Total <b>${eur(sum("total"))}</b>` : "";
  };
  $("#y", el).onchange = load; $("#s", el).onchange = load; $("#c", el).onchange = load; $("#q", el).oninput = debounce(load);
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
    ["cobros", "Facturas pendientes de cobro", "Facturas emitidas sin cobrar a la fecha final con los días pendientes, y las cobradas en el periodo (fecha, forma, referencia y quién lo comprobó).", can("facturas.ver")],
  ].filter((x) => x[3]);
  el.innerHTML = `<div class="toolbar"><label>Desde<input type="date" id="d" value="${y}-01-01"></label><label>Hasta<input type="date" id="h" value="${today()}"></label>
    <span class="muted">Activo: ${esc(S.asset ? assetName(Number(S.asset)) : "todos los de su ámbito")} (filtro de arriba)</span></div>
    <div class="cards">${INF.map(([k, t, d]) => `<div class="card"><h3>${esc(t)}</h3><p class="sub">${esc(d)}</p><button class="btn primary" data-inf="${k}">Descargar Excel</button></div>`).join("")}</div>`;
  el.querySelectorAll("[data-inf]").forEach((b) => (b.onclick = () => run(() => download("GET", `/api/informes/${b.dataset.inf}?` + new URLSearchParams(clean({ desde: $("#d", el).value, hasta: $("#h", el).value, asset_id: S.asset }))))));
  if (can("facturas.ver") || can("documentos.ver")) {
    $(".cards", el).insertAdjacentHTML("beforeend", '<div class="card"><h3>Exportar a INVERGESTION</h3><p class="sub">Facturas emitidas y recibidas en CSV con sus PDF, según la especificación de INVERGESTION. Envío semanal; histórico desde el 1 de enero de 2026.</p><button class="btn primary" id="invg">Preparar exportación</button></div>');
    $("#invg", el).onclick = exportarInvergestion;
  }
  if (can("finanzas.ver")) {
    $(".cards", el).insertAdjacentHTML("beforeend", `<div class="card"><h3>Programa anterior (SYADE)</h3><p class="sub">Facturación de 2026 importada de SYADE (alojamiento, servicios, abonos y fianzas) para ver la producción antes de que el PMS facture.</p>
      <div class="toolbar"><button class="btn" id="histVer">Ver resumen</button>${can("facturas.rectificar") ? '<button class="btn primary" id="histImp">Importar listados</button>' : ""}</div></div>`);
    $("#histVer", el).onclick = resumenHistorico;
    if ($("#histImp", el)) $("#histImp", el).onclick = () => importarHistorico(resumenHistorico);
  }
  if (can("reservas.ver") && assetsOf("apartamentos_turisticos").length) {
    $(".cards", el).insertAdjacentHTML("beforeend", '<div class="card"><h3>Encuesta del INE</h3><p class="sub">Cuestionario mensual de ocupación en apartamentos turísticos: viajeros y pernoctaciones por día y residencia, ocupación y precios.</p><button class="btn primary" id="ine">Preparar encuesta</button></div>');
    $("#ine", el).onclick = encuestaIne;
  }
};

// ---- facturación del programa anterior (SYADE): importación de sus listados y resumen mensual
const HIST_CMP = { registros: "Registros", base: "Base", cuota: "IVA", total: "Total", fianza: "Fianzas cobradas", devuelto: "Fianzas devueltas", retenido: "Retenido" };
async function importarHistorico(recargar) {
  const aid = await pickAsset();
  form(`Importar facturación del programa anterior · ${assetName(aid)}`, [
    { html: `<p>Listados de SYADE pasados a Excel. Puede elegir varios a la vez: <b>facturas de alojamiento</b>, <b>facturas de servicios</b>, <b>abonos</b> y <b>fianzas devueltas</b> (se reconocen solos).</p>
      <ul class="muted"><li>Cada listado se comprueba con su fila de <b>Totales</b>: debe cuadrar al céntimo.</li>
      <li>Cuenta en la producción del panel y del informe; no afecta a la numeración de las facturas del PMS.</li>
      <li>Si vuelve a importar un listado, se actualiza: no se duplica nada.</li></ul>` },
    { html: '<label>Ficheros *<input type="file" accept=".xlsx" multiple data-fich required></label>' },
  ], {}, async (_, fr) => {
    const fichs = [...$("[data-fich]", fr).files];
    const enviar = (fich, confirmar) => { const fd = new FormData(); fd.append("fichero", fich); fd.append("asset_id", aid); fd.append("confirmar", confirmar); return upload("/api/historico/importar", fd); };
    const prev = [];
    for (const fich of fichs) prev.push(await enviar(fich, false).catch((e) => ({ error: e.message, nombre: fich.name })));
    setTimeout(() => {
      const bloques = prev.map((p, i) => p.error ? `<div class="aviso-faltan"><b>${esc(fichs[i].name)}</b>: ${esc(p.error)}</div>` : `
        <fieldset><legend>${esc(p.tipo_nombre)} · ${esc(fichs[i].name)}</legend>
        <p>${p.cuadra ? '<span class="badge b-vigente">✔ cuadra con los totales del listado</span>' : '<span class="badge b-cancelada">no cuadra</span>'}
          ${p.registros} registros (${p.nuevas} nuevos, ${p.actualizadas} a actualizar) · ${fdate(p.desde)} → ${fdate(p.hasta)}${p.con_reserva ? ` · ${p.con_reserva} enlazados con su reserva` : ""}${p.clientes ? ` · ${p.con_cliente} registro(s) de ${p.clientes} cliente(s) del PMS${p.por_nombre ? ` (${p.por_nombre} por nombre)` : ""}` : ""}</p>
        <div class="table-wrap"><table><thead><tr><th></th>${Object.keys(p.leido).map((k) => `<th class="num">${HIST_CMP[k] || k}</th>`).join("")}</tr></thead><tbody>
          <tr><td>Leído</td>${Object.entries(p.leido).map(([k, v]) => `<td class="num">${k === "registros" ? v : eur(v)}</td>`).join("")}</tr>
          ${p.esperado ? `<tr><td>Totales del listado</td>${Object.keys(p.leido).map((k) => `<td class="num">${p.esperado[k] == null ? "—" : k === "registros" ? p.esperado[k] : eur(p.esperado[k])}</td>`).join("")}</tr>` : ""}
        </tbody></table></div>${p.avisos.length ? `<ul class="muted">${p.avisos.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : ""}</fieldset>`).join("");
      const validos = prev.map((p, i) => [p, fichs[i]]).filter(([p]) => !p.error);
      form(`Comprobación · ${validos.length} listado(s) válido(s)`, [{ html: bloques }], {}, async () => {
        if (!validos.length) throw new Error("Ningún listado válido");
        if (validos.some(([p]) => !p.cuadra) && !confirm("Algún listado no cuadra con sus totales. ¿Importarlo igualmente?")) throw new Error("Importación cancelada");
        let n = 0;
        for (const [, fich] of validos) n += (await enviar(fich, true)).registros;
        toast(`Importados ${n} registros del programa anterior`); recargar && recargar();
      }, "Importar");
      $("#modal").classList.add("ancho");
    }, 0);
  }, "Comprobar ficheros");
}
async function resumenHistorico() {
  const datos = await run(() => get("/api/historico", { asset_id: S.asset }));
  if (!datos.length) return toast("Todavía no se ha importado facturación del programa anterior", true);
  const col = [["alojamiento", "Alojamiento (base)"], ["abonos", "De ello, abonos"], ["servicio", "Servicios (base)"], ["produccion", "Producción (base)"],
    ["total", "Total con IVA"], ["fianzas_cobradas", "Fianzas cobradas"], ["fianzas_devueltas", "Fianzas devueltas"]];
  const html = datos.map((a) => {
    const tot = {}; a.meses.forEach((m) => col.forEach(([k]) => (tot[k] = (tot[k] || 0) + (m[k] || 0))));
    const celda = (k, v) => `<td class="num">${k === "n" ? (v || 0) : v ? eur(v) : "—"}</td>`;
    const mes = (m) => { const [y, mm] = m.split("-"); return `${MESES[Number(mm) - 1]} ${y}`; };
    return `<h4>${esc(a.activo)}</h4><p class="muted">${fdate(a.desde)} → ${fdate(a.hasta)} · importado ${fdt(a.importado)} · ${Object.entries(a.registros).map(([t, n]) => `${n} ${label(t)}`).join(" · ")}</p>
      <p>${a.clientes.con_cliente} de ${a.clientes.facturas} facturas y abonos enlazados con <b>${a.clientes.clientes} cliente(s)</b> del PMS (por DNI/NIF o, si no lo tienen, por nombre${a.clientes.por_nombre ? `: ${a.clientes.por_nombre}` : ""}): sus importes se ven en la ficha de cada cliente.</p>
      <div class="table-wrap"><table><thead><tr><th>Mes</th>${col.map(([, t]) => `<th class="num">${t}</th>`).join("")}</tr></thead><tbody>
      ${a.meses.map((m) => `<tr><td>${mes(m.mes)}</td>${col.map(([k]) => celda(k, m[k])).join("")}</tr>`).join("")}
      <tr class="total"><td><b>Total</b></td>${col.map(([k]) => `<td class="num"><b>${k === "n" ? tot[k] : eur(tot[k])}</b></td>`).join("")}</tr></tbody></table></div>
      ${can("facturas.rectificar") ? `<div class="toolbar"><span class="spacer"></span><button type="button" class="btn sm danger" data-borra="${a.asset_id}">Borrar lo importado de ${esc(a.activo)}</button></div>` : ""}`;
  }).join("");
  const f = cerrarSolo(form("Facturación del programa anterior (SYADE)", [{ html: `<p class="muted">Producción = base imponible de facturas de alojamiento y servicios menos abonos, por fecha de factura. Las fianzas no son producción.</p>${html}` }], {}, async () => {}));
  $("#modal").classList.add("ancho");
  f.querySelectorAll("[data-borra]").forEach((b) => (b.onclick = async () => {
    if (!confirm("¿Borrar toda la facturación importada de este activo? Podrá volver a importarla.")) return;
    const r = await run(() => api("DELETE", `/api/historico?asset_id=${b.dataset.borra}`));
    toast(`${r.borrados} registros borrados`); $("#modal").close();
  }));
}

// ---- exportación a INVERGESTION: facturas emitidas y recibidas (CSV + PDF), envío semanal
function semanaPasada() {
  const d = new Date(today() + "T00:00:00"), dia = (d.getDay() + 6) % 7;  // lunes = 0
  const lunes = new Date(d); lunes.setDate(d.getDate() - dia - 7);
  const domingo = new Date(lunes); domingo.setDate(lunes.getDate() + 6);
  return [isoLocal(lunes), isoLocal(domingo)];
}
function exportarInvergestion() {
  const [d0, d1] = semanaPasada();
  const f = cerrarSolo(form("Exportar a INVERGESTION", [
    { html: `<p>Genera <b>un solo ZIP</b> para INVERGESTION: los CSV de <b>EMITIDAS</b> y <b>RECIBIDAS</b>, el <b>manifest.json</b> y los PDF de las facturas en las carpetas <b>pdf/emitidas</b> y <b>pdf/recibidas</b>. Si falta el PDF de alguna factura, no se genera y se indica cuál.</p>
      <ul class="muted"><li>Emitidas: las <b>emitidas</b> en el periodo (aunque su fecha de factura sea el último día del mes) y las <b>cobradas</b> en el periodo, para informar el cobro.</li>
      <li>Recibidas: las de la cuenta de gastos con fecha de factura, registro o pago en el periodo.</li>
      <li>Fianzas: las devoluciones registradas al dar la salida o hechas en el periodo (FIANZAS_*.csv, solo si hay).</li>
      <li>INVERGESTION actualiza las facturas que ya tiene: se pueden repetir periodos sin duplicar nada.</li></ul>` },
    { k: "desde", t: "Desde", type: "date", req: true, def: d0 }, { k: "hasta", t: "Hasta", type: "date", req: true, def: d1 },
    { k: "activo", t: "Activo", type: "select", req: true, def: "TODOS", options: [["TODOS", "Todos"], ["SFLORIDA", "Suite Florida"], ["SAEROPUERTO", "Suite Aeropuerto"], ["BABILONIA35", "C/ Babilonia 35"]] },
    { k: "emitidas", t: "Facturas emitidas", type: "checkbox", def: true }, { k: "recibidas", t: "Facturas recibidas", type: "checkbox", def: true }, { k: "fianzas", t: "Devoluciones de fianza", type: "checkbox", def: true },
    { k: "pdf", t: "Incluir los PDF de las facturas", type: "checkbox", def: true, wide: true },
    { html: `<div class="toolbar"><button type="button" class="btn sm" data-p="semana">Semana pasada</button><button type="button" class="btn sm" data-p="mes">Este mes</button>
      <button type="button" class="btn sm" data-p="hist">Histórico 2026</button><span class="spacer"></span>
      <button type="button" class="btn" data-comprobar>Comprobar</button><button type="button" class="btn primary" data-bajar>Descargar ficheros</button></div><div data-res></div>` },
  ], {}, async () => {}));
  $("#modal").classList.add("ancho");
  const v = () => ({ desde: f.elements.desde.value, hasta: f.elements.hasta.value, activo: f.elements.activo.value,
    tipos: [f.elements.emitidas.checked && "emitidas", f.elements.recibidas.checked && "recibidas", f.elements.fianzas.checked && "fianzas"].filter(Boolean).join(","), pdf: f.elements.pdf.checked });
  f.querySelectorAll("[data-p]").forEach((b) => (b.onclick = () => {
    const [a, z] = b.dataset.p === "semana" ? semanaPasada() : b.dataset.p === "mes" ? [today().slice(0, 8) + "01", today()] : ["2026-01-01", today()];
    f.elements.desde.value = a; f.elements.hasta.value = z;
  }));
  $("[data-comprobar]", f).onclick = async () => {
    const q = v(); if (!q.tipos) return toast("Elija emitidas, recibidas o ambas", true);
    const r = await run(() => get("/api/exportacion/invergestion/comprobar", { desde: q.desde, hasta: q.hasta, activo: q.activo, tipos: q.tipos }));
    const paquete = r.paquete; delete r.paquete;
    $("[data-res]", f).innerHTML = `<p>Paquete: <b>${esc(paquete || "")}</b></p>` + Object.entries(r).map(([t, x]) => `<fieldset><legend>${{ emitidas: "Facturas emitidas", recibidas: "Facturas recibidas", fianzas: "Devoluciones de fianza" }[t]} · ${esc(x.csv)}</legend>
      <p>${t === "fianzas" ? `<b>${x.devoluciones}</b> devolución(es) · devuelto ${eur(x.total)}${x.devoluciones ? "" : " (sin fianzas: no va el CSV)"}` : `<b>${x.facturas}</b> factura(s) · ${x.filas} fila(s) · ${x.ficheros} PDF · total ${eur(x.total)}`}</p>
      ${(x.bloquea || []).length ? `<p class="error"><b>No se generará el paquete:</b> falta el PDF de ${x.bloquea.length} factura(s). Vuelva a subir esos documentos.</p>` : ""}
      ${x.n_avisos ? `<p class="error">${x.n_avisos} aviso(s): INVERGESTION rechazaría esas filas hasta corregirlas.</p><ul class="muted">${x.avisos.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : '<p class="ok">✔ Sin avisos: cumple la especificación.</p>'}</fieldset>`).join("");
  };
  $("[data-bajar]", f).onclick = () => {
    const q = v(); if (!q.tipos) return toast("Elija emitidas, recibidas o ambas", true);
    toast("Preparando el paquete…");
    run(() => download("GET", "/api/exportacion/invergestion?" + new URLSearchParams(q)));
  };
}

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
  if (tipo === "huesped") $(".toolbar", el).insertAdjacentHTML("beforeend", '<button class="btn" id="ln">Lista negra</button>');
  if ($("#ln", el)) $("#ln", el).onclick = () => listaNegra();
  const load = async () => table($("#t", el), [
    { k: "nombre", t: "Nombre", f: (v, c) => `${c.lista_negra ? '<span class="badge b-cancelada" title="Lista negra">⛔</span> ' : ""}${esc(v)}` }, { k: "apellidos", t: "Apellidos" }, { k: "documento_num", t: "Documento" },
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
    { html: `<div class="toolbar">${g.fichas.map((c) => `<button type="button" class="btn sm" data-verficha="${c.id}">Abrir ficha ${c.id}</button>`).join("")}
      <span class="spacer"></span><button type="button" class="btn sm" data-distintas>No son la misma persona</button></div>
      <p class="muted">Si solo coincide el nombre, pulse «No son la misma persona»: no se unen y el aviso desaparece.</p>`, wide: true },
  ], { unir: g.documentos_distintos ? [] : g.fichas.map((c) => String(c.id)) }, async (d) => {
    const ids = d.unir.map(Number).filter((x) => x !== Number(d.conservar));
    if (ids.length) {
      await post(`/api/terceros/${d.conservar}/fusionar`, { ids });
      toast(`${g.nombre}: ${ids.length + 1} fichas unidas en una`);
    }
    unirFichas(grupos.slice(1), done);
  }, "Unir y seguir");
  const f = $("#modalForm");
  f.querySelectorAll("[data-verficha]").forEach((b) => (b.onclick = () => editGuest(Number(b.dataset.verficha), g.fichas[0].tipo, done)));
  $("[data-distintas]", f).onclick = async () => {
    await run(() => post("/api/terceros/distintos", { ids: g.fichas.map((c) => c.id) }), `${g.nombre}: no son la misma persona`);
    unirFichas(grupos.slice(1), done);
  };
}

// ---- proveedores del grupo (no dependen de ninguna sociedad)
const TIPOS_PERSONA = [["empresa", "Empresa (CIF)"], ["autonomo", "Autónomo (DNI/NIE)"], ["particular", "Persona física (DNI/NIE)"]];
const CAMPOS_PROVEEDOR = [
  { k: "nombre", t: "Nombre o razón social", req: true, wide: true },
  { k: "tipo_persona", t: "Tipo", type: "select", req: true, options: TIPOS_PERSONA, def: "empresa" },
  { k: "nif", t: "CIF / DNI / NIE" },
  { k: "direccion", t: "Domicilio", wide: true }, { k: "cp", t: "Código postal" }, { k: "municipio", t: "Población" },
  { k: "provincia", t: "Provincia" }, { k: "pais", t: "País", def: "España" },
  { k: "email", t: "Correo electrónico", type: "email" }, { k: "telefono", t: "Teléfono" },
  { k: "persona_contacto", t: "Persona de contacto" }, { k: "actividad", t: "Actividad / gremio" },
  { k: "activo", t: "Proveedor en activo", type: "checkbox", def: true },
  { k: "cae_vence", t: "Documentación CAE/PRL válida hasta (subcontratas)", type: "date" },
  { k: "cae_nota", t: "CAE/PRL: qué documentación tiene (seguro RC, TC2, formación PRL…)" },
  { k: "notas", t: "Notas", type: "textarea", wide: true },
];
const verProveedores = () => can("mantenimiento.ver") || can("documentos.ver");
const editarProveedores = () => can("mantenimiento.editar") || can("documentos.editar");
// Proveedor escrito que no está en el fichero del grupo: se abre su ficha para completarla y que quede guardada
async function altaProveedorSiNuevo(nombre, actividad) {
  nombre = String(nombre || "").trim();
  if (!nombre || !editarProveedores()) return;
  const todos = await get("/api/proveedores").catch(() => null);
  if (!todos || todos.some((p) => normaliza(p.nombre).replace(/\s+/g, " ") === normaliza(nombre).replace(/\s+/g, " "))) return;
  form(`Proveedor nuevo: ${nombre}`, [{ html: '<p class="muted">No está en el fichero de proveedores. Complete su ficha (CIF o DNI, domicilio, correo, teléfono…): queda guardada para todos los activos del grupo. Si ahora no tiene los datos, pulse «Ahora no».</p>' },
    ...CAMPOS_PROVEEDOR], { nombre, actividad, pais: "España", tipo_persona: "empresa", activo: true },
  async (d) => { await post("/api/proveedores", d); S.proveedores = null; toast(`${d.nombre} guardado en el fichero de proveedores`); }, "Guardar proveedor");
  $("#fCancel").textContent = "Ahora no";
}
V.proveedores = async (el) => {
  const editar = editarProveedores();
  el.innerHTML = `<div class="toolbar"><input id="q" placeholder="Nombre, CIF/DNI, actividad, municipio"><label class="check"><input type="checkbox" id="baja"> Ver también los de baja</label>
    <span class="spacer"></span>${editar ? '<button class="btn primary" id="new">Nuevo proveedor</button>' : ""}</div>
    <p class="muted">Fichero de proveedores del grupo, común a todas las sociedades. Se usa al indicar el proveedor de una orden de trabajo, la empresa mantenedora de un plan preventivo o la empresa del personal.</p><div id="t"></div>`;
  const fields = CAMPOS_PROVEEDOR;
  const guardar = (p) => async (d) => {
    await (p ? put(`/api/proveedores/${p.id}`, d) : post("/api/proveedores", d));
    S.proveedores = null; toast(p ? "Proveedor guardado" : "Proveedor dado de alta"); load();
  };
  const load = async () => table($("#t", el), [
    { k: "nombre", t: "Nombre" }, { k: "nif", t: "CIF / DNI" }, { k: "tipo_persona_nombre", t: "Tipo" },
    { k: "actividad", t: "Actividad" }, { k: "municipio", t: "Municipio" }, { k: "telefono", t: "Teléfono" },
    { k: "email", t: "Correo" }, { k: "cae_vence", t: "CAE/PRL", f: (v, p) => (v ? (p.cae_vencida ? `<span class="badge b-urgente">vencida ${fdate(v)}</span>` : `hasta ${fdate(v)}`) : '<span class="muted">—</span>') },
    { k: "activo", t: "Estado", f: (v) => (v ? "En activo" : '<span class="muted">Baja</span>') },
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
  if (!verProveedores()) return;
  S.proveedores = S.proveedores || await get("/api/proveedores", { solo_activos: true }).catch(() => []);
  if (!f.querySelector("#dl-prov")) f.insertAdjacentHTML("beforeend", `<datalist id="dl-prov">${S.proveedores.map((p) => `<option value="${esc(p.nombre)}">${esc(p.actividad || "")}</option>`).join("")}</datalist>`);
  campos.forEach((c) => f.elements[c]?.setAttribute("list", "dl-prov"));
}

// ---- mantenimiento
// «Asignado a»: personal propio (ficha de Personal) o subcontrata (ficha de Proveedores)
const camposAsignacion = (gente) => [
  { k: "asignacion", t: "Asignado a", type: "select", options: [["propio", "Personal propio"], ["subcontrata", "Subcontrata (proveedor)"]] },
  { k: "personal_id", t: "Persona de mantenimiento", type: "select", options: gente.map((p) => [p.id, `${p.nombre}${p.telefono ? "" : " · sin móvil"}`]) },
  { k: "proveedor", t: "Subcontrata (escriba y elija de Proveedores)" },
];
function bindAsignacion(f) {
  const pinta = () => {
    const v = f.elements.asignacion.value;
    f.elements.personal_id.closest("label").style.display = v === "propio" ? "" : "none";
    f.elements.proveedor.closest("label").style.display = v === "subcontrata" ? "" : "none";
  };
  f.elements.asignacion.addEventListener("change", pinta); pinta();
  return f;
}
const datosAsignacion = (d) => ({ ...d, asignacion: d.asignacion || null, personal_id: d.asignacion === "propio" && d.personal_id ? Number(d.personal_id) : null,
  proveedor: d.asignacion === "subcontrata" ? d.proveedor || null : d.asignacion === "propio" ? null : d.proveedor });
const personalMto = (aid) => get("/api/personal", { asset_id: aid, area: "mantenimiento", solo_activos: true }).catch(() => []);
const puedeAsignarOT = () => can("mantenimiento.editar") || can("mantenimiento.cerrar");  // recepción y dirección
// Enviar la OT a quien la tiene asignada (WhatsApp y/o correo) con copia al personal de mantenimiento propio
function enviarAsignado(w, reload) {
  const c = w.contacto;
  if (!w.asignacion) return enviarOT(w, reload);
  if (!c) return toast(w.asignacion === "subcontrata" ? "La subcontrata no está en Proveedores: dela de alta con su correo o teléfono y vuelva a elegirla en la OT" : "Elija en la OT la persona de mantenimiento", true);
  const canales = [["whatsapp", `WhatsApp${c.whatsapp ? " (con el enlace para gestionarla desde el móvil)" : " · sin móvil en la ficha"}`], ["email", `Correo${c.email ? ` a ${c.email} (enlace + parte en PDF)` : " · sin correo en la ficha"}`]];
  const def = w.asignacion === "propio" ? ["whatsapp"] : ["email", "whatsapp"].filter((k) => (k === "email" ? c.email : c.whatsapp));
  form(`Enviar ${otNum(w.id)} · ${w.titulo}`, [
    { html: `<p>Se envía a <b>${esc(c.nombre)}</b> · ${w.asignacion === "propio" ? "personal propio" : "subcontrata"}.</p>` },
    { k: "canales", t: "Enviar por", type: "checks", options: canales },
    { k: "copia", t: "Enviar copia al personal de mantenimiento propio (para que sepan qué trabajos se van a hacer)", type: "checkbox", wide: true, def: true },
    { k: "nota", t: "Nota (opcional)", type: "textarea", wide: true },
  ], { canales: def }, async (d) => {
    if (!d.canales.length) throw new Error("Elija por dónde se envía");
    const r = await post(`/api/mantenimiento/ordenes/${w.id}/enviar-asignado`, { canales: d.canales, copia_mantenimiento: !!d.copia, nota: d.nota || null });
    reload && reload();
    setTimeout(() => resultadoEnvio(`${otNum(w.id)} enviada`, r.enviados.map((x) => (x.copia ? { ...x, nombre: `${x.nombre} (copia)` } : x))), 0);
  }, "Enviar");
}
// Recepción o dirección asignan la OT (o la derivan a una subcontrata cuando el personal propio lo pide)
async function asignarOT(w, reload) {
  const gente = await personalMto(w.asset_id);
  sugerirProveedores(bindAsignacion(form(`Asignar ${otNum(w.id)} · ${w.titulo}`, [
    ...(w.alerta_tecnico === "escalar" ? [{ html: `<p class="error">El personal propio solicita derivar esta orden a una subcontrata especializada${w.tecnico ? `: «${esc(w.tecnico.nombre)}»` : ""}.</p>` }] : []),
    ...camposAsignacion(gente), { k: "fecha_prevista", t: "Fecha prevista (reprogramar)", type: "date" },
  ], { ...w, asignacion: w.alerta_tecnico === "escalar" ? "subcontrata" : w.asignacion }, async (d) => {
    const x = await post(`/api/mantenimiento/ordenes/${w.id}/asignar`, clean(datosAsignacion(d)));
    toast(`Asignada a ${x.asignado_a}`); reload && reload();
    await altaProveedorSiNuevo(d.proveedor, w.categoria);
    if (confirm(`¿Enviar ahora la ${otNum(x.id)} a ${x.asignado_a}?`)) enviarAsignado(x, reload);
  }, "Asignar")), "proveedor");
}
// Intervenciones registradas por el técnico desde su enlace: tiempos, trabajos, materiales, resultado y firma
async function intervencionesOT(w) {
  const lista = await get(`/api/mantenimiento/ordenes/${w.id}/intervenciones`);
  const f = cerrarSolo(form(`${otNum(w.id)} · intervenciones del técnico`, [{ html: lista.length ? lista.map((v) => `<div class="intervencion">
      <p><b>${esc(v.tecnico || "—")}</b> · ${esc(v.empresa || "")} · ${v.resultado_nombre ? `<span class="badge ${v.resultado === "escalar" ? "b-urgente" : v.resultado === "resuelta" ? "b-cerrada" : "b-pendiente"}">${esc(v.resultado_nombre)}</span>` : '<span class="muted">en curso</span>'}</p>
      <p class="muted peq">Llegada ${v.llegada ? fdt(v.llegada) : "—"} · salida ${v.salida ? fdt(v.salida) : "—"}${v.minutos != null ? ` · ${v.minutos} min` : ""}${v.enviado ? ` · enviado ${fdt(v.enviado)}` : ""}</p>
      ${v.trabajos ? `<p><b>Trabajos / diagnóstico:</b> ${esc(v.trabajos)}</p>` : ""}
      ${(v.materiales || []).length ? `<p><b>Material:</b> ${v.materiales.map((m) => `${esc(m.material)}${m.cantidad ? ` (${esc(m.cantidad)})` : ""}`).join(" · ")}</p>` : ""}
      ${v.fecha_propuesta ? `<p><b>Siguiente visita propuesta:</b> ${fdate(v.fecha_propuesta)}</p>` : ""}
      ${v.justificacion ? `<p><b>Justificación:</b> ${esc(v.justificacion)}</p>` : ""}
      ${v.observaciones ? `<p><b>Observaciones:</b> ${esc(v.observaciones)}</p>` : ""}
      ${v.con_firma ? `<img class="firma-tecnico" data-firma="${v.id}" alt="Firma del técnico">` : ""}</div>`).join("") : '<p class="muted">Sin intervenciones registradas.</p>' }], {}, async () => {}));
  f.querySelectorAll("[data-firma]").forEach((img) => blobUrl(`/api/mantenimiento/intervenciones/${img.dataset.firma}/firma`).then((u) => (img.src = u)).catch(() => {}));
}
async function newWorkOrder(assetId, unitId, zona, parte) {  // zona: {zona, nombre} de una zona común del plano
  const aid = assetId || await pickAsset();
  const units = zona ? [] : await get("/api/unidades", { asset_id: aid });
  const titulo = zona ? `Nueva incidencia · ${zona.nombre}` : unitId ? `Nueva incidencia · ${units.find((u) => u.id === unitId)?.codigo ?? ""}` : `Nueva orden de trabajo · ${assetName(aid)}`;
  const gente = puedeAsignarOT() ? await personalMto(aid) : [];
  return new Promise((resolve) => sugerirProveedores((puedeAsignarOT() ? bindAsignacion : (x) => x)(bindFotos(bindAccesoOT(form(titulo, [
    { k: "titulo", t: "Título", req: true, wide: true },
    ...(zona ? [] : [{ k: "unit_id", t: "Unidad (vacío = zonas comunes)", type: "select", options: units.map((u) => [u.id, u.codigo]) }, { html: "<div data-acceso></div>", wide: true }]),
    ...(can("mantenimiento.editar") ? [{ k: "tipo", t: "Tipo", type: "select", req: true, options: list(["correctivo", "preventivo", "normativo", "mejora"]), def: "correctivo" }] : []),
    { k: "categoria", t: "Instalación / gremio", type: "select", req: true, options: list(S.cat.categorias_mto), def: "general" },
    { k: "prioridad", t: "Prioridad", type: "select", req: true, options: list(S.cat.prioridades), def: "media" },
    ...(puedeAsignarOT() ? [...camposAsignacion(gente), { k: "fecha_prevista", t: "Fecha prevista", type: "date" }] : []),
    ...(can("mantenimiento.editar") ? [{ k: "coste_estimado", t: "Coste estimado €", type: "number" }] : []),
    ...(zona ? [] : [{ k: "bloquea_unidad", t: "Bloquear unidad (fuera de venta hasta cierre)", type: "checkbox", wide: true }]),
    { k: "descripcion", t: "Descripción de la avería", type: "textarea", wide: true },
    { html: parte ? `<p class="muted">Se genera desde el parte de estado <b>${esc(parte.codigo)}</b>: sus fotos se adjuntan solas.</p>` : fotosHtml("Fotos de la avería (opcional)") },
  ], { unit_id: unitId, ...(parte ? parte.ot_propuesta : {}) }, async (d, f) => {
    const acc = f._acceso ? f._acceso() : null;
    const acceso = acc ? { acceso: acc.acceso, acceso_autoriza: acc.autoriza, acceso_medio: acc.medio } : {};
    const w = await post("/api/mantenimiento/ordenes", clean({ ...(puedeAsignarOT() ? datosAsignacion(d) : d), asset_id: aid, unit_id: d.unit_id ? Number(d.unit_id) : null, zona: zona?.zona, parte_estado_id: parte?.id, ...acceso }));
    const n = await subirFotos(f, w.id, "averia");
    toast(`Orden de trabajo OT-${String(w.id).padStart(5, "0")} creada` + (n ? ` con ${n} foto(s)` : "") + (w.prioridad === "urgente" ? ". Se ha avisado por correo." : ""));
    resolve();
    await altaProveedorSiNuevo(d.proveedor, d.categoria);
    if (w.asignacion && puedeEnviarOT()) setTimeout(() => enviarAsignado(w), 0);  // generada: se envía a quien la hace
  })))), "proveedor"));
}
// Apartamento con cliente dentro: obligatorio indicar cómo se entra (llave de recepción con su permiso, o contactar
// con él; su teléfono sale solo de la ficha del cliente alojado)
// Bloque de acceso con cliente alojado: llave de recepción (quién lo autoriza y cómo) o contactar (sale su teléfono)
const MEDIOS_ACCESO = [["en_persona", "En persona"], ["telefono", "Por teléfono"], ["whatsapp", "Por WhatsApp"], ["correo", "Por correo"]];
function accesoHtml(info, k = "acc", previo = {}) {
  return `<fieldset data-acc="${k}"><legend>Cliente alojado: acceso al apartamento</legend>
    <label class="check"><input type="radio" name="${k}" value="llave" ${previo.acceso === "llave" ? "checked" : ""}> El cliente autoriza entrar con la llave de recepción</label>
    <div class="acc-llave grid2" ${previo.acceso === "llave" ? "" : "hidden"}><label>Quién lo autoriza<input data-autoriza value="${esc(previo.acceso_autoriza || info.huesped || "")}"></label>
      <label>Cómo<select data-medio>${MEDIOS_ACCESO.map(([v, t]) => `<option value="${v}" ${v === (previo.acceso_medio || "en_persona") ? "selected" : ""}>${t}</option>`).join("")}</select></label></div>
    <label class="check"><input type="radio" name="${k}" value="contactar" ${previo.acceso === "contactar" ? "checked" : ""}> Contactar con el cliente para el acceso · tel. <b>${esc(info.telefono || "sin teléfono en su ficha")}</b></label></fieldset>`;
}
function bindAccesoBloque(box, k = "acc") {
  const fs = box.querySelector(`[data-acc="${k}"]`);
  if (!fs) return () => null;
  fs.querySelectorAll(`input[name="${k}"]`).forEach((r) => (r.onchange = () => { fs.querySelector(".acc-llave").hidden = fs.querySelector(`input[name="${k}"]:checked`)?.value !== "llave"; }));
  return () => {
    const x = fs.querySelector(`input[name="${k}"]:checked`);
    if (!x) throw new Error("El apartamento tiene un cliente alojado: indique si autoriza la llave de recepción o hay que contactarle");
    if (x.value !== "llave") return { acceso: "contactar" };
    const autoriza = fs.querySelector("[data-autoriza]").value.trim();
    if (!autoriza) throw new Error("Indique quién autoriza entrar con la llave de recepción");
    return { acceso: "llave", autoriza, medio: fs.querySelector("[data-medio]").value };
  };
}
function bindAccesoOT(f) {
  const box = $("[data-acceso]", f), sel = f.elements.unit_id;
  if (!box || !sel) return f;
  let leer = () => null;
  const pinta = async () => {
    const info = sel.value ? await get("/api/mantenimiento/acceso", { unit_id: sel.value }).catch(() => null) : null;
    leer = () => null;
    if (info?.situacion === "alojado") {
      box.innerHTML = accesoHtml(info);
      leer = bindAccesoBloque(box);
    } else if (info?.situacion === "llegada") {  // libre ahora: llega un cliente pronto
      const antes = sumaDias(info.llegada, -1);
      box.innerHTML = `<p class="aviso-llegada">🧳 <b>Llega un cliente el ${fdate(info.llegada)}</b> (${info.dias === 0 ? "hoy" : `en ${info.dias} días`}). Mejor hacerla antes de su llegada${f.elements.fecha_prevista ? ": se propone como fecha prevista el día anterior" : ""}.</p>`;
      if (f.elements.fecha_prevista && !f.elements.fecha_prevista.value && info.dias > 0) f.elements.fecha_prevista.value = antes;
    } else box.innerHTML = "";
  };
  sel.addEventListener("change", () => pinta());
  pinta();
  f._acceso = () => leer();
  return f;
}
const accesoBadge = (w) => {
  const e = w.acceso_estado;
  if (e && ["falta", "caducado"].includes(e.estado)) return `<div class="peq error">⚠ ${esc(e.texto)}</div>`;
  const llegada = e?.estado === "llegada" ? `<div class="peq aviso-llegada-txt">🧳 ${esc(e.texto)}</div>` : "";
  if (!w.acceso || (e && e.estado !== "vigente")) return llegada;
  return `<div class="peq" title="${esc(w.acceso_texto || "")}">${w.acceso === "llave" ? "🔑 Llave recepción" : `📞 ${esc((w.acceso_texto || "").split("tel. ")[1] || "Contactar")}`}</div>${llegada}`;
};
// Anotar o cambiar el acceso de una OT ya abierta (lista de OT o check-in de un cliente con OT abierta)
async function accesoOT(w, reload) {
  const info = await get("/api/mantenimiento/acceso", { unit_id: w.unit_id });
  if (info.situacion !== "alojado") return toast("El apartamento no tiene ningún cliente alojado ahora", true);
  const vigente = w.acceso_estado?.estado === "vigente";
  const f = form(`Acceso · ${otNum(w.id)} · ${w.unidad}`, [{ html: `<p class="peq">${esc(w.titulo)}</p>${vigente && w.acceso_texto ? `<p class="peq muted">Anotado: ${esc(w.acceso_texto)}</p>` : ""}${accesoHtml(info, "acc", vigente ? w : {})}`, wide: true }], {}, async () => {
    await put(`/api/mantenimiento/ordenes/${w.id}/acceso`, leer());
    toast("Acceso anotado"); reload && reload();
  });
  const leer = bindAccesoBloque(f);
}
// Check-in de un cliente con OT abiertas en su apartamento: se le pregunta en ese momento cómo se entra
function accesoTrasCheckin(r, reload) {
  if (!r.ot_acceso?.length) return;
  const info = { huesped: r.huesped, telefono: r.huesped_telefono };
  const f = form(`Órdenes de trabajo abiertas en ${r.unidad}`, [{ html: `<p>Pregunte al cliente cómo se puede entrar para hacerlas.</p>
    ${r.ot_acceso.map((w) => `<div class="card rev"><b>${otNum(w.id)}</b> · ${esc(w.titulo)} ${badge(w.prioridad)}${accesoHtml(info, `acc${w.id}`)}</div>`).join("")}`, wide: true }], {}, async () => {
    const datos = r.ot_acceso.map((w) => [w.id, lectores[w.id]()]);
    for (const [id, d] of datos) await put(`/api/mantenimiento/ordenes/${id}/acceso`, d);
    toast("Acceso anotado"); reload && reload();
  }, "Guardar acceso");
  const lectores = Object.fromEntries(r.ot_acceso.map((w) => [w.id, bindAccesoBloque(f, `acc${w.id}`)]));
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
  return f;
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
    <p class="muted">Flujo: recepción abre y asigna la OT (personal propio o subcontrata) → «Enviar» manda el enlace por WhatsApp o correo → el técnico la gestiona desde el móvil y firma → limpieza confirma la unidad → recepción da la conformidad de la propiedad y cierra. Las preventivas de zonas comunes no pasan por limpieza.</p><div id="t"></div>`;
  const check = (who, when) => (who ? `<span title="${esc(fdt(when))}">✓ ${esc(who)}</span>` : '<span class="muted">pendiente</span>');
  const load = async () => {
    const e = $("#e", el).value;
    const rows = await get("/api/mantenimiento/ordenes", { asset_id: S.asset, tipo: $("#tp", el).value, ...(e === "abiertas" ? { abiertas: true } : { estado: e }) });
    table($("#t", el), [
      { k: "id", t: "Nº", f: otNum }, { k: "fecha_apertura", t: "Apertura", f: fdate }, { k: "asset_id", t: "Activo", f: (v) => esc(assetName(v)) },
      { k: "unidad", t: "Unidad", f: (v, w) => esc(v || w.zona_nombre || "Z. comunes") }, { k: "titulo", t: "Título", f: (v, w) => esc(v) + accesoBadge(w) },
      { k: "categoria", t: "Instalación" }, { k: "prioridad", t: "Prioridad", f: (v, w) => badge(v) + (w.plazo ? `<br><span class="${w.plazo.vencido ? "badge b-urgente" : "muted peq"}" title="Plazo de respuesta: urgente 4 h, alta 24 h">${w.plazo.vencido ? "⏰ fuera de plazo" : "plazo"} ${fdt(w.plazo.limite).slice(0, -3)}</span>` : "") }, { k: "abierta_por_nombre", t: "Abierta por" },
      { k: "asignado_a", t: "Asignado", f: (v, w) => esc(v || "") + (w.cae_vencida ? `<br><span class="badge b-urgente" title="Documentación CAE/PRL vencida: pídala antes de que trabaje">CAE vencida</span>` : "") }, { k: "envios", t: "Enviada", f: (v) => (v?.length ? `<span title="${esc(v.map((e) => `${fdt(e.fecha)} ${e.nombre} (${e.canal === "email" ? "correo" : "WhatsApp"})`).join("\n"))}">✉ ${esc([...new Set(v.map((e) => e.nombre))].join(", "))}</span>` : "") }, { k: "conf_mto_por_nombre", t: "Mantenimiento", f: (v, w) => check(v, w.conf_mto_fecha) },
      { k: "conf_limpieza_por_nombre", t: "Limpieza", f: (v, w) => (w.requiere_limpieza ? check(v, w.conf_limpieza_fecha) : '<span class="muted">no aplica</span>') },
      { k: "coste_real", t: "Coste", num: true, f: eur }, { k: "estado", t: "Estado", f: (v, w) => badge(v) + (w.alerta_nombre ? `<br><span class="badge ${w.alerta_tecnico === "escalar" ? "b-urgente" : "b-pendiente"}" title="Resultado del técnico sin atender">⚑ ${esc(w.alerta_nombre)}</span>` : "") + (w.tecnico?.fecha_propuesta && w.estado === "pendiente_visita" ? `<br><span class="muted peq">visita ${fdate(w.tecnico.fecha_propuesta)}</span>` : "") },
    ], rows, (w) => {
      const comunes = [
        [`📎 ${w.n_adjuntos || ""}`.trim(), () => adjuntosOT(w, load)],
        ["Parte PDF", () => run(() => download("GET", `/api/mantenimiento/ordenes/${w.id}/parte`))],
        w.tecnico && ["Intervenciones", () => intervencionesOT(w)],
      ];
      if (["cerrada", "cancelada"].includes(w.estado)) return comunes;
      const enTrabajo = !w.conf_mto_fecha;
      return [...comunes,
        (canOpenOT() || can("reservas.editar")) && w.unit_id && ["falta", "caducado", "vigente"].includes(w.acceso_estado?.estado) && ["Acceso", () => accesoOT(w, load), w.acceso_estado.estado === "vigente" ? "" : "primary"],
        puedeAsignarOT() && enTrabajo && ["Asignar", () => asignarOT(w, load), w.alerta_tecnico === "escalar" ? "primary" : ""],
        puedeEnviarOT() && enTrabajo && ["Enviar", () => enviarAsignado(w, load)],
        puedeEnviarOT() && enTrabajo && w.asignacion && ["Enviar a otros", () => enviarOT(w, load)],
        puedeEnviarOT() && w.envios?.length && ["Revocar enlace", () => confirm(`¿Anular el enlace del técnico de la ${otNum(w.id)}? El enviado deja de funcionar; para seguir, envíe la orden de nuevo.`) && run(() => post(`/api/mantenimiento/ordenes/${w.id}/revocar-enlace`), "Enlace revocado").then(load), "danger"],
        can("mantenimiento.editar") && enTrabajo && ["Editar", async () => { const gente = await personalMto(w.asset_id); sugerirProveedores(bindAsignacion(form(`OT ${w.id}: ${w.titulo}`, [
          { k: "titulo", t: "Título", req: true, wide: true }, { k: "estado", t: "Estado", type: "select", options: list(["abierta", "asignada", "en_curso", "pendiente_material", "pendiente_visita", "escalada", "revisar"]) },
          { k: "prioridad", t: "Prioridad", type: "select", options: list(S.cat.prioridades) }, { k: "categoria", t: "Instalación", type: "select", options: list(S.cat.categorias_mto) },
          { k: "tipo", t: "Tipo", type: "select", options: list(["correctivo", "preventivo", "normativo", "mejora"]) },
          ...camposAsignacion(gente), { k: "coste_estimado", t: "Coste estimado €", type: "number" },
          { k: "fecha_prevista", t: "Fecha prevista", type: "date" }, { k: "descripcion", t: "Descripción", type: "textarea", wide: true },
        ], w, async (d) => {
          const x = await put(`/api/mantenimiento/ordenes/${w.id}`, datosAsignacion(d)); toast("OT actualizada"); load(); await altaProveedorSiNuevo(d.proveedor, d.categoria);
          if (x.asignacion && (x.asignado_a !== w.asignado_a) && confirm(`¿Enviar ahora la ${otNum(x.id)} a ${x.asignado_a}?`)) enviarAsignado(x, load);
        })), "proveedor"); }],
        can("mantenimiento.editar") && enTrabajo && ["Trabajo realizado", () => bindFotos(form(`OT ${w.id}: confirmar trabajo realizado`, [
          { k: "solucion", t: "Trabajo realizado / solución", type: "textarea", wide: true, req: true }, { k: "coste_real", t: "Coste real €", type: "number" },
          { html: fotosHtml("Fotos del trabajo terminado (opcional)") }],
          {}, async (d, f) => {
            const n = await subirFotos(f, w.id, "trabajo");
            const r = await post(`/api/mantenimiento/ordenes/${w.id}/confirmar-mantenimiento`, d);
            toast((r.requiere_limpieza ? "Trabajo confirmado. Pendiente de limpieza" : "Trabajo confirmado. Pendiente de cierre") + (n ? ` · ${n} foto(s)` : "")); load();
          }))],
        can("limpieza.confirmar_ot") && w.requiere_limpieza && w.conf_mto_fecha && !w.conf_limpieza_por && ["Unidad OK", () => run(() => post(`/api/mantenimiento/ordenes/${w.id}/confirmar-limpieza`), "Confirmado por limpieza. Pendiente de cierre").then(load)],
        (can("mantenimiento.cerrar") || (can("limpieza.confirmar_ot") && w.requiere_limpieza)) && w.conf_mto_fecha && ["Rechazar", () => form(`OT ${w.id}: devolver a mantenimiento`, [
          { k: "motivo", t: "Motivo (qué no está bien)", type: "textarea", wide: true, req: true }], {},
          async (d) => { await post(`/api/mantenimiento/ordenes/${w.id}/rechazar`, d); toast("Devuelta a mantenimiento"); load(); }), "danger"],
        can("mantenimiento.cerrar") && w.estado === "pendiente_cierre" && ["Conformidad y cierre", () => form(`${otNum(w.id)}: conformidad de la propiedad`, [
          { html: `<p>${w.tecnico ? `Trabajo enviado por <b>${esc(w.tecnico.nombre)}</b> (${esc(w.tecnico.empresa || "")}): ${esc(w.tecnico.resultado_nombre)} · ${fdt(w.tecnico.enviado)} (botón «Intervenciones» para ver el detalle y la firma).` : `Trabajo confirmado por ${esc(w.conf_mto_por_nombre || "mantenimiento")}.`}</p>` },
          { k: "ok", t: "He revisado el trabajo y la deficiencia está subsanada: doy la conformidad de la propiedad", type: "checkbox", wide: true, req: true },
          { html: `<p class="muted peq">Queda registrada con su usuario (${esc(S.me.nombre)}), la fecha y la hora, y aparece en el parte PDF. La orden pasa a cerrada y archivable.</p>` },
        ], {}, async (d) => {
          if (!d.ok) throw new Error("Marque la conformidad");
          await post(`/api/mantenimiento/ordenes/${w.id}/cerrar`, {}); toast("Conformidad registrada: OT cerrada"); load();
        }, "Dar conformidad y cerrar"), "primary"],
        can("mantenimiento.cerrar") && ["Anular", () => form(`Anular OT ${w.id}`, [{ k: "motivo", t: "Motivo", type: "textarea", wide: true, req: true }], {},
          async (d) => { await post(`/api/mantenimiento/ordenes/${w.id}/cerrar`, { cancelar: true, motivo: d.motivo }); toast("OT anulada"); load(); }), "danger"],
      ];
    });
  };
  $("#e", el).onchange = load; $("#tp", el).onchange = load;
  if ($("#new", el)) $("#new", el).onclick = () => newWorkOrder().then(load);
  load();
};

// ---- control del preventivo y de las inspecciones OCA: semáforo, revisiones con documentos, deficiencias con OT
const SEM = { rojo: "var(--bad)", naranja: "#c05621", ambar: "var(--warn)", verde: "var(--ok)", gris: "var(--muted)" };
const semaforo = (p) => `<span class="sem" style="--c:${SEM[p.color]}">${esc(p.estado_nombre)}</span>`;
const venceTxt = (p) => `${fdate(p.vence)}<br><span class="peq ${p.dias < 0 ? "error" : "muted"}">${p.dias < 0 ? `hace ${-p.dias} días` : p.dias === 0 ? "hoy" : `en ${p.dias} días`}</span>`;
const sumaDias = (iso, n) => { const d = new Date(iso + "T12:00:00"); d.setDate(d.getDate() + n); return iso ? `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}` : ""; };

V.preventivo = async (el) => {
  const editar = can("mantenimiento.editar");
  let filtro = "", tipo = "";
  el.innerHTML = `<div class="toolbar"><select id="tipo"><option value="">Mantenimiento y OCA</option><option value="mantenimiento">Solo mantenimiento</option><option value="oca">Solo inspecciones OCA</option></select>
    <span class="spacer"></span><button class="btn" id="xls">Excel</button>${editar ? '<button class="btn" id="tpl">Cargar plantilla normativa</button><button class="btn" id="gen">Generar OT próximas</button><button class="btn primary" id="new">Nuevo plan</button>' : ""}</div>
    <div id="cards" class="kpis kpis-prev"></div><div id="t"></div>
    <p class="muted peq">La plantilla normativa es orientativa: revise periodicidades según potencia, uso y tipo de instalación de cada activo. Al registrar una revisión, la próxima fecha del plan pasa a ser la del documento.</p>`;
  const fields = [
    { k: "titulo", t: "Título", req: true, wide: true },
    { k: "tipo", t: "Tipo", type: "select", req: true, def: "mantenimiento", options: [["mantenimiento", "Mantenimiento preventivo"], ["oca", "Inspección OCA (organismo de control)"]] },
    { k: "categoria", t: "Instalación", type: "select", req: true, options: list(S.cat.categorias_mto) },
    { k: "normativa", t: "Normativa / referencia" }, { k: "periodicidad_dias", t: "Periodicidad (días)", type: "number", req: true },
    { k: "proxima_fecha", t: "Próxima fecha", type: "date", req: true }, { k: "proveedor", t: "Empresa mantenedora u OCA" },
    { k: "checklist_txt", t: "Puntos a comprobar (uno por línea; vacío = los de su instalación)", type: "textarea", wide: true },
    { k: "activo", t: "Plan activo", type: "checkbox", def: true },
  ];
  const guardarPlan = (d) => { const { checklist_txt, ...x } = d; const pts = (checklist_txt || "").split("\n").map((l) => l.trim()).filter(Boolean); return clean({ ...x, checklist: pts.length ? pts : null }); };
  const load = async () => {
    const c = await get("/api/preventivo/control", { asset_id: S.asset, tipo });
    const t = c.totales;
    const card = (k, n, txt, color) => `<button type="button" class="kpi kpi-btn${filtro === k ? " sel" : ""}" data-f="${k}" style="--c:${color}"><b>${n}</b><span>${txt}</span></button>`;
    $("#cards", el).innerHTML = [card("", t.planes, `planes (${t.oca} OCA)`, "var(--ink)"), card("vencido", t.vencidos, "vencidos", SEM.rojo),
      card("subsanacion_vencida", t.subsanacion_vencida, "plazo de subsanación vencido", SEM.rojo), card("deficiencias", t.deficiencias, "deficiencias sin subsanar", SEM.naranja),
      card("proximo", t.proximos, "próximos 30 días", SEM.ambar), card("sin_documento", t.sin_documento, "revisiones sin documento", SEM.gris), card("al_dia", t.al_dia, "al día", SEM.verde)].join("");
    $("#cards", el).querySelectorAll("[data-f]").forEach((b) => (b.onclick = () => { filtro = filtro === b.dataset.f ? "" : b.dataset.f; load(); }));
    const filas = c.planes.filter((p) => !filtro || (filtro === "sin_documento" ? p.avisos.some((a) => a.includes("documento"))
      : filtro === "deficiencias" ? p.deficiencias_abiertas.length : p.estado === filtro));
    table($("#t", el), [
      { k: "estado", t: "Estado", f: (_, p) => semaforo(p) },
      { k: "titulo", t: "Plan", f: (v, p) => `${p.tipo === "oca" ? '<span class="badge b-escalada">OCA</span> ' : ""}<b>${esc(v)}</b><br><span class="peq muted">${esc(assetName(p.asset_id))} · ${esc(p.categoria)}${p.normativa ? ` · ${esc(p.normativa)}` : ""}</span>` },
      { k: "proveedor_nombre", t: "Empresa", f: (v) => esc(v || "—") },
      { k: "vence", t: "Vence", f: (_, p) => venceTxt(p) },
      { k: "ultima", t: "Última revisión", f: (u) => u ? `${fdate(u.fecha)} · ${esc(u.resultado_nombre)}${u.numero ? `<br><span class="peq muted">${esc(u.numero)}</span>` : ""} ${u.documentos.length ? `<span title="Documentos">📎${u.documentos.length}</span>` : '<span class="error peq">sin documento</span>'}` : '<span class="muted">sin registrar</span>' },
      { k: "avisos", t: "Para revisar", f: (v, p) => [...p.deficiencias_abiertas.map((d) => `<span class="error">● ${esc(d.descripcion)}</span> <a href="#" data-ot="${d.ot_id}">${otNum(d.ot_id)}</a>`), ...v.map((a) => esc(a))].map((x) => `<div class="peq">${x}</div>`).join("") || '<span class="muted">—</span>' },
    ], filas, (p) => [
      editar && p.activo && ["Registrar revisión", () => registrarRevision(p, load), "primary"],
      ["Historial", () => historialPlan(p.id, load)],
      editar && ["Editar", () => sugerirProveedores(form(p.titulo, fields, { ...p, checklist_txt: (p.checklist || []).join("\n") }, async (d) => { await put(`/api/mantenimiento/planes/${p.id}`, guardarPlan(d)); toast("Plan guardado"); load(); }), "proveedor")],
    ]);
    $("#t", el).querySelectorAll("[data-ot]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); verOT(Number(a.dataset.ot)); }));
  };
  $("#tipo", el).onchange = (e) => { tipo = e.target.value; load(); };
  $("#xls", el).onclick = () => run(() => download("GET", `/api/preventivo/excel${S.asset ? `?asset_id=${S.asset}` : ""}`));
  if ($("#new", el)) {
    $("#new", el).onclick = async () => { const aid = await pickAsset(); sugerirProveedores(form("Nuevo plan preventivo", fields, {}, async (d) => { await post("/api/mantenimiento/planes", { ...guardarPlan(d), asset_id: aid }); toast("Plan creado"); load(); }), "proveedor"); };
    $("#tpl", el).onclick = async () => { const aid = await pickAsset(); run(() => post("/api/mantenimiento/planes/plantilla", { asset_id: aid }), (r) => `${r.creados} planes cargados`).then(load); };
    $("#gen", el).onclick = () => form("Generar órdenes preventivas", [{ k: "dias_antelacion", t: "Días de antelación", type: "number", def: 7, req: true }], {},
      async (d) => { const r = await post("/api/mantenimiento/planes/generar", clean({ ...d, asset_id: S.asset ? Number(S.asset) : null })); toast(`${r.creadas} órdenes generadas`); load(); });
  }
  load();
};

// Registrar la revisión de un plan: lista de comprobación, resultado, próxima fecha (se contrasta con la periodicidad),
// deficiencias (cada una genera su OT) y documentos de la empresa
function registrarRevision(p, reload) {
  const hoy = today();
  const conDef = Object.fromEntries(p.resultados.map(([k, , d]) => [k, d]));
  const grav = [["leve", "Leve"], ["grave", "Grave"], ["muy_grave", "Muy grave"]];
  const filaDef = (d = {}) => `<div class="assign-row def-row"><input data-d="descripcion" placeholder="Deficiencia" value="${esc(d.descripcion || "")}">
    <select data-d="gravedad">${grav.map(([k, t]) => `<option value="${k}" ${k === (d.gravedad || "leve") ? "selected" : ""}>${t}</option>`).join("")}</select><button type="button" class="btn sm danger" data-x>✕</button></div>`;
  const f = form(`Registrar ${p.tipo === "oca" ? "inspección OCA" : "revisión"} · ${p.titulo}`, [
    { k: "fecha", t: "Fecha de la revisión", type: "date", req: true, def: hoy },
    { k: "resultado", t: "Resultado", type: "select", req: true, def: p.resultados[0][0], options: p.resultados.map(([k, t]) => [k, t]) },
    { k: "empresa", t: p.tipo === "oca" ? "Organismo de control (OCA)" : "Empresa", def: p.proveedor_nombre || "" },
    { k: "tecnico", t: p.tipo === "oca" ? "Inspector" : "Técnico" },
    { k: "numero", t: p.tipo === "oca" ? "Nº de acta / certificado" : "Nº de informe o parte" },
    { k: "proxima", t: "Próxima revisión (la que indica el documento)", type: "date", def: sumaDias(hoy, p.periodicidad_dias) },
    { html: '<p class="peq" data-contraste></p>', wide: true },
    { html: `<fieldset class="wide"><legend>Lista de comprobación</legend><table class="check-rev"><tbody>${p.puntos.map((pt, i) => `<tr><td>${esc(pt)}</td>
      ${[["ok", "Correcto"], ["deficiencia", "Deficiencia"], ["na", "No aplica"]].map(([v, t]) => `<td><label class="check"><input type="radio" name="pt${i}" value="${v}" ${v === "ok" ? "checked" : ""}> ${t}</label></td>`).join("")}
      <td><input data-nota="${i}" placeholder="Nota"></td></tr>`).join("")}</tbody></table></fieldset>`, wide: true },
    { html: `<fieldset class="wide" data-defs><legend>Deficiencias (cada una genera su orden de trabajo)</legend><div data-lista></div>
      <button type="button" class="btn sm" data-mas>+ Añadir deficiencia</button>
      <label>Plazo de subsanación<input type="date" name="plazo_subsanacion"></label><p class="peq muted">Si el documento no fija plazo: 60 días (leve), 30 (grave) o 2 (muy grave).</p></fieldset>`, wide: true },
    { html: `<label class="wide">Documentos de la empresa (${p.tipo === "oca" ? "acta, certificado" : "informe, parte"}, fotos)<input type="file" data-docs multiple accept=".pdf,image/*"></label>`, wide: true },
    { k: "observaciones", t: "Observaciones", type: "textarea", wide: true },
  ], {}, async (d, fr) => {
    const checklist = p.puntos.map((pt, i) => ({ punto: pt, estado: fr.querySelector(`[name=pt${i}]:checked`)?.value || "ok", nota: fr.querySelector(`[data-nota="${i}"]`).value.trim() || null }));
    const deficiencias = [...fr.querySelectorAll(".def-row")].map((r) => ({ descripcion: r.querySelector('[data-d="descripcion"]').value.trim(), gravedad: r.querySelector('[data-d="gravedad"]').value })).filter((x) => x.descripcion);
    const datos = clean({ fecha: d.fecha, resultado: d.resultado, empresa: d.empresa, tecnico: d.tecnico, numero: d.numero, proxima: d.proxima,
      plazo_subsanacion: fr.elements.plazo_subsanacion.value || null, observaciones: d.observaciones, checklist, deficiencias });
    const fd = new FormData(); fd.append("datos", JSON.stringify(datos));
    [...fr.querySelector("[data-docs]").files].forEach((x) => fd.append("ficheros", x));
    const r = await upload(`/api/preventivo/planes/${p.id}/revisiones`, fd);
    toast(`Revisión registrada${r.ots.length ? ` · ${r.ots.length} órdenes de trabajo generadas` : ""}`);
    if (r.aviso) alert(r.aviso);
    reload && reload();
  }, "Registrar");
  const lista = $("[data-lista]", f);
  const bindX = () => lista.querySelectorAll("[data-x]").forEach((b) => (b.onclick = () => { b.parentElement.remove(); }));
  $("[data-mas]", f).onclick = () => { lista.insertAdjacentHTML("beforeend", filaDef()); bindX(); };
  const res = f.elements.resultado;
  const verDefs = () => { $("[data-defs]", f).style.display = conDef[res.value] ? "" : "none"; if (conDef[res.value] && !lista.children.length) $("[data-mas]", f).click(); };
  res.onchange = verDefs;
  f.querySelectorAll('input[type=radio][value="deficiencia"]').forEach((r) => (r.onchange = () => { if (!conDef[res.value]) { res.value = p.resultados.find(([, , d]) => d)[0]; verDefs(); } }));
  const contraste = () => {  // la próxima fecha del documento frente a la periodicidad del plan
    const calc = sumaDias(f.elements.fecha.value, p.periodicidad_dias), prox = f.elements.proxima.value;
    const dif = prox && calc ? Math.round((new Date(prox) - new Date(calc)) / 864e5) : 0;
    $("[data-contraste]", f).innerHTML = Math.abs(dif) > 31 ? `<span class="error">⚠ Según la periodicidad del plan (cada ${p.periodicidad_dias} días) tocaría el ${fdate(calc)}. Compruebe la fecha del documento.</span>` : "";
  };
  f.elements.fecha.onchange = () => { f.elements.proxima.value = sumaDias(f.elements.fecha.value, p.periodicidad_dias); contraste(); };
  f.elements.proxima.onchange = contraste;
  sugerirProveedores(f, "empresa");
  verDefs();
}

// Ficha rápida de una OT (desde el control del preventivo): datos y accesos a asignar, enviar y documentos
async function verOT(wid) {
  const w = await get(`/api/mantenimiento/ordenes/${wid}`);
  const f = form(`${otNum(w.id)} · ${w.titulo}`, [{ html: `<p>${badge(w.estado)} ${badge(w.prioridad)} · ${esc(assetName(w.asset_id))} · ${esc(w.unidad || w.zona_nombre || "Zonas comunes")}</p>
    <p class="peq">Apertura ${fdate(w.fecha_apertura)}${w.fecha_prevista ? ` · prevista ${fdate(w.fecha_prevista)}` : ""}${w.asignado_a || w.proveedor ? ` · ${esc(w.asignado_a || w.proveedor)}` : " · sin asignar"}</p>
    <p style="white-space:pre-line">${esc(w.descripcion || "")}</p>${accesoBadge(w)}
    <p>${puedeEnviarOT() ? '<button type="button" class="btn sm" data-a="asignar">Asignar</button> <button type="button" class="btn sm" data-a="enviar">Enviar</button> ' : ""}<button type="button" class="btn sm" data-a="docs">Fotos y documentos (${w.n_adjuntos})</button>
    <button type="button" class="btn sm" data-a="ir">Ver en órdenes de trabajo</button></p>` }], {}, async () => {}, "Cerrar");
  const acc = { asignar: () => asignarOT(w), enviar: () => enviarOT(w), docs: () => adjuntosOT(w), ir: () => { $("#modal").close(); go("ordenes"); } };
  f.querySelectorAll("[data-a]").forEach((b) => (b.onclick = () => acc[b.dataset.a]()));
}

async function historialPlan(pid, reload) {
  const h = await get(`/api/preventivo/planes/${pid}/revisiones`);
  const p = h.plan;
  const f = form(`Historial · ${p.titulo}`, [{ html: `<p>${semaforo(p)} · vence ${fdate(p.vence)} · cada ${p.periodicidad_dias} días${p.normativa ? ` · ${esc(p.normativa)}` : ""}</p>
    ${h.revisiones.length ? h.revisiones.map((r) => `<div class="card rev">
      <b>${fdate(r.fecha)}</b> · <span class="badge ${r.con_deficiencias ? "b-cancelada" : "b-vigente"}">${esc(r.resultado_nombre)}</span>
      ${r.numero ? ` · ${esc(r.numero)}` : ""}${r.empresa ? ` · ${esc(r.empresa)}` : ""}${r.tecnico ? ` · ${esc(r.tecnico)}` : ""}
      <div class="peq muted">Prevista ${fdate(r.fecha_prevista)} · próxima ${fdate(r.proxima)}${r.plazo_subsanacion ? ` · subsanar antes del ${fdate(r.plazo_subsanacion)}` : ""} · registró ${esc(r.usuario || "—")}</div>
      ${(r.deficiencias || []).map((d) => `<div class="peq">● ${esc(d.descripcion)} (${esc(d.gravedad.replace("_", " "))}) · <a href="#" data-ot="${d.ot_id}">${otNum(d.ot_id)}</a> ${d.ot_estado ? badge(d.ot_estado) : ""}</div>`).join("")}
      ${(r.checklist || []).filter((x) => x.estado !== "ok").map((x) => `<div class="peq muted">${x.estado === "na" ? "N/A" : "✗"} ${esc(x.punto)}${x.nota ? `: ${esc(x.nota)}` : ""}</div>`).join("")}
      ${r.observaciones ? `<div class="peq">${esc(r.observaciones)}</div>` : ""}
      <div class="peq">${r.documentos.map((x) => `<a href="#" data-doc="${x.id}">📎 ${esc(x.nombre)}</a>`).join(" ") || '<span class="error">Sin documento</span>'}
      ${can("mantenimiento.editar") ? `<label class="btn sm">+ Documento<input type="file" data-subir="${r.id}" multiple accept=".pdf,image/*" hidden></label>` : ""}</div></div>`).join("") : '<p class="muted">Todavía no hay revisiones registradas.</p>'}` }], {}, async () => {}, "Cerrar");
  f.querySelectorAll("[data-doc]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); abrirFichero(`/api/preventivo/documentos/${a.dataset.doc}`); }));
  f.querySelectorAll("[data-ot]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); verOT(Number(a.dataset.ot)); }));
  f.querySelectorAll("[data-subir]").forEach((inp) => (inp.onchange = async () => {
    const fd = new FormData(); [...inp.files].forEach((x) => fd.append("ficheros", x));
    await run(() => upload(`/api/preventivo/revisiones/${inp.dataset.subir}/documentos`, fd), "Documento añadido");
    historialPlan(pid, reload); reload && reload();
  }));
}

// ---- personal de mantenimiento y limpieza: fichas con correo y teléfono; envío de las OT y del parte de limpieza
const AREAS = [["mantenimiento", "Mantenimiento"], ["limpieza", "Limpieza"], ["conserjeria", "Conserjería"], ["recepcion", "Recepción"], ["administracion", "Administración y oficinas"], ["otros", "Otros (por administración)"]];
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
  if (!gente.length) return toast("No hay personal dado de alta para este activo (Personal → Fichas del personal)", true);
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

// ---- parte diario de limpieza: salidas (con la próxima llegada), contratadas por el cliente y extras de recepción.
// Lo que no se valida pasa al día siguiente. PDF para imprimir, envío por WhatsApp o correo y Excel en documentos.
async function parteLimpieza(fecha) { S.limpieza = { ...(S.limpieza || {}), fecha }; go("limpieza"); }
V.limpieza = async (el) => {
  const pool = assetsOf("apartamentos_turisticos");
  if (!pool.length) { el.innerHTML = '<div class="empty">Sin activos turísticos</div>'; return; }
  S.limpieza = S.limpieza || {};
  const cur = pool.find((a) => a.id === S.limpieza.asset) || pool.find((a) => String(a.id) === String(S.asset)) || pool[0];
  S.limpieza.asset = cur.id;
  el.innerHTML = `<div class="toolbar">${pool.length > 1 ? `<select id="la">${pool.map((a) => `<option value="${a.id}" ${a.id === cur.id ? "selected" : ""}>${esc(a.nombre)}</option>`).join("")}</select>` : `<strong>${esc(cur.nombre)}</strong>`}
    <label>Día<input type="date" id="lf" value="${S.limpieza.fecha || today()}"></label><button class="btn" id="lhoy">Hoy</button><button class="btn" id="lman">Mañana</button>
    <span class="spacer"></span><button class="btn danger" id="lurg">⚡ Limpieza urgente</button><button class="btn" id="lextra">＋ Limpieza extra</button><button class="btn" id="lpdf">Imprimir PDF</button><button class="btn" id="lhoja" title="Una hoja por apartamento con su dotación para revisar antes de devolver la fianza">Hojas de revisión</button><button class="btn" id="lmovil" title="Enlaces para revisar las salidas en el móvil">Revisión en el móvil</button><button class="btn" id="lxls">Excel</button><button class="btn primary" id="lenv">Enviar</button></div>
    <div class="kpis" id="lk"></div><div id="lt"></div>
    <p class="muted">Antes de imprimir o enviar, recepción puede <b>ordenar</b> el parte (↑ ↓), marcar algo como <b>urgente</b>, añadir una nota o <b>pasarlo a otro día</b> («Cambiar»). Limpieza avisa al terminar y recepción pulsa <b>Hecha</b>: sale del parte (si es de salida, el apartamento queda disponible). Lo que no se valida sigue en el parte del día siguiente. Al imprimir o enviar, el Excel del día queda en Documentos recibidos.</p>`;
  let p;
  const fecha = () => $("#lf", el).value || today();
  const load = async () => {
    S.limpieza.fecha = fecha();
    p = await get("/api/limpieza/parte", { asset_id: cur.id, fecha: fecha() });
    const pend = p.limpiezas.filter((x) => x.estado === "pendiente"), n = (t) => pend.filter((x) => x.tipo === t).length;
    $("#lk", el).innerHTML = [[pend.length, "Pendientes", pend.length ? "" : ""], [pend.filter((x) => x.urgente).length, "Urgentes / llegada hoy", pend.some((x) => x.urgente) ? "mal" : ""],
      [n("salida"), "Por salida"], [n("contratada"), "Contratadas"], [n("extra"), "Extra"], [pend.filter((x) => x.arrastrada).length, "De días anteriores", pend.some((x) => x.arrastrada) ? "mal" : ""],
      [p.limpiezas.length - pend.length, "Validadas hoy"]].map(([v, l, c]) => `<div class="kpi ${c || ""}"><b>${v}</b><span>${l}</span></div>`).join("");
    const pri = (x) => (x.urgente_manual ? '<span class="badge b-cancelada">⚡ URGENTE</span> ' : "") + (x.antes_de ? (x.urgente ? `<span class="badge b-cancelada">LLEGADA HOY${x.pax_llegada ? ` · ${x.pax_llegada} pax` : ""}</span>` : `<span class="badge b-pendiente">Antes del ${fdate(x.antes_de).slice(0, 5)}${x.pax_llegada ? ` · ${x.pax_llegada} pax` : ""}</span>`) : "");
    table($("#lt", el), [
      { k: "codigo", t: "Apartamento", f: (v, x) => `<b>${esc(v)}</b><div class="muted peq">${esc([x.bloque, x.planta ? "planta " + x.planta : ""].filter(Boolean).join(" · "))}</div>` },
      { k: "tipo_nombre", t: "Tipo", f: (v, x) => `<span class="tipo t-${x.tipo === "salida" ? "reserva" : x.tipo === "extra" ? "incidencia" : "cliente"}">${esc(v)}</span>` },
      { k: "motivo", t: "Limpieza", f: (v, x) => `${esc(v)}${x.arrastrada ? `<div class="peq" style="color:#a15c00">Pendiente desde el ${fdate(x.fecha)}</div>` : ""}` },
      { k: "antes_de", t: "Prioridad", f: (v, x) => pri(x) },
      { k: "estado", t: "Estado", f: (v, x) => v === "hecha" ? `<span class="badge b-vigente">hecha</span><div class="muted peq">${fdt(x.hecha)}${x.validada_por ? " · " + esc(x.validada_por) : ""}</div>` : '<span class="badge b-pendiente">pendiente</span>' },
    ], p.limpiezas, (x) => x.estado === "pendiente" ? [
      ["↑", () => mover(x, -1)], ["↓", () => mover(x, 1)],
      ["Cambiar", () => form(`Limpieza de ${x.codigo}`, [
        { k: "urgente", t: "Urgente: va la primera del parte", type: "checkbox", wide: true },
        { k: "nota", t: "Nota para limpieza", wide: true },
        { k: "fecha", t: "Día (pasarla a otro día)", type: "date", req: true },
      ], { urgente: x.urgente_manual, nota: x.nota, fecha: x.fecha < fecha() ? fecha() : x.fecha }, async (d) => {
        await put(`/api/limpieza/${x.id}`, { urgente: !!d.urgente, nota: d.nota || null, ...(d.fecha !== x.fecha && d.fecha !== fecha() ? { fecha: d.fecha } : {}) });
        toast("Parte actualizado"); load();
      })],
      ["✔ Hecha", () => run(() => post(`/api/limpieza/${x.id}/hecha`), `Limpieza de ${x.codigo} validada`).then(load), "primary"],
      ["Hecha con incidencia", () => form(`Incidencia en ${x.codigo}`, [
        { html: '<p class="muted">Se valida la limpieza y se abre una orden de trabajo a mantenimiento (también llega a gestión).</p>' },
        { k: "incidencia", t: "¿Qué hay que reparar?", type: "textarea", req: true, wide: true },
        { k: "prioridad", t: "Prioridad", type: "select", req: true, options: [["baja", "Baja"], ["media", "Media"], ["alta", "Alta"], ["urgente", "Urgente"]] },
        { k: "bloquea", t: "No se puede alquilar hasta repararlo", type: "checkbox" },
      ], { prioridad: "media" }, async (d) => {
        const r = await post(`/api/limpieza/${x.id}/hecha`, { incidencia: d.incidencia, prioridad: d.prioridad, bloquea: !!d.bloquea });
        toast(`Limpieza validada · abierta la OT-${String(r.orden_trabajo).padStart(5, "0")}`); load();
      }, "Validar y abrir la orden")],
      x.tipo === "extra" && ["Quitar", () => confirm(`¿Quitar la limpieza extra de ${x.codigo}?`) && run(() => api("DELETE", `/api/limpieza/${x.id}`), "Limpieza extra quitada").then(load), "danger"],
    ] : [["Deshacer", () => run(() => post(`/api/limpieza/${x.id}/deshacer`), "Vuelve a estar pendiente").then(load)]]);
  };
  const mover = async (x, paso) => {  // recepción fija el orden del parte (todas las pendientes)
    const ids = p.limpiezas.filter((y) => y.estado === "pendiente").map((y) => y.id);
    const i = ids.indexOf(x.id), j = i + paso;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    await run(() => post("/api/limpieza/orden", { ids })); load();
  };
  const enviarUna = async (tid, gente) => form("Enviar orden de limpieza urgente", [
    ...(gente.length ? [{ k: "personal_ids", t: "Personal de limpieza", type: "checks", options: gente.map((x) => [String(x.id), personaTxt(x)]) }] : []),
    canalEnvio(" (con el PDF)"), { k: "telefono", t: "Otro número (WhatsApp)" }, { k: "email", t: "Otro correo", type: "email" },
  ], {}, async (d) => {
    const r = await post(`/api/limpieza/${tid}/enviar`, { ...clean(d), personal_ids: (d.personal_ids || []).map(Number) });
    setTimeout(() => resultadoEnvio("Orden de limpieza urgente enviada", r.enviados), 0);
  }, "Enviar");
  $("#lurg", el).onclick = () => form(`⚡ Orden de limpieza urgente · ${cur.nombre}`, [
    { html: '<p class="muted">Para hoy y la primera del parte. Al guardarla se imprime o se envía al momento al personal de limpieza.</p>' },
    { k: "unit_id", t: "Apartamento", type: "select", req: true, options: p.unidades.map((u) => [u.id, `${u.codigo}${u.bloque ? " · " + u.bloque : ""}`]) },
    { k: "nota", t: "Qué hay que hacer", req: true, wide: true },
  ], {}, async (d) => {
    const t = await post("/api/limpieza/urgente", { asset_id: cur.id, unit_id: Number(d.unit_id), nota: d.nota });
    load();
    const gente = await get("/api/personal", { asset_id: cur.id, area: "limpieza", solo_activos: true }).catch(() => []);
    setTimeout(() => {
      const f = cerrarSolo(form("Orden de limpieza urgente creada", [{ html: `<div class="acciones-ap">
        <button type="button" class="accion-ap" data-imp><span class="caja">🖨️</span><b>Imprimir</b><small>PDF de la orden</small></button>
        <button type="button" class="accion-ap" data-env><span class="caja">📲</span><b>Enviar</b><small>WhatsApp o correo al personal de limpieza</small></button></div>` }], {}, async () => {}));
      $("[data-imp]", f).onclick = () => run(() => download("GET", `/api/limpieza/${t.id}/orden.pdf`));
      $("[data-env]", f).onclick = () => enviarUna(t.id, gente);
    }, 0);
  }, "Crear orden urgente");
  $("#lf", el).onchange = load;
  $("#lhoy", el).onclick = () => { $("#lf", el).value = today(); load(); };
  $("#lman", el).onclick = () => { $("#lf", el).value = addDays(today(), 1); load(); };
  if ($("#la", el)) $("#la", el).onchange = () => { S.limpieza.asset = Number($("#la", el).value); go("limpieza"); };
  $("#lextra", el).onclick = () => form(`Limpieza extra · ${cur.nombre}`, [
    { html: '<p class="muted">Limpieza no programada (repaso, a fondo, petición del cliente…). Saldrá en el parte del día elegido.</p>' },
    { k: "unit_id", t: "Apartamento", type: "select", req: true, options: p.unidades.map((u) => [u.id, `${u.codigo}${u.bloque ? " · " + u.bloque : ""}`]) },
    { k: "fecha", t: "Día", type: "date", req: true, def: fecha() < today() ? today() : fecha() },
    { k: "nota", t: "Qué hay que hacer", wide: true },
  ], {}, async (d) => { await post("/api/limpieza/extra", { ...clean(d), asset_id: cur.id, unit_id: Number(d.unit_id) }); toast("Limpieza extra añadida"); load(); }, "Añadir");
  $("#lpdf", el).onclick = () => run(() => download("GET", `/api/limpieza/parte.pdf?asset_id=${cur.id}&fecha=${fecha()}`));
  $("#lhoja", el).onclick = () => abrirFichero(`/api/limpieza/hojas-revision.pdf?asset_id=${cur.id}&fecha=${fecha()}`);
  $("#lmovil", el).onclick = async () => {
    const x = await run(() => get("/api/revision/dia", { asset_id: cur.id, fecha: fecha() }));
    const f = cerrarSolo(form("Revisión de salidas en el móvil", [{ html: x.salidas.length ? `<p>Limpieza abre cada enlace en el móvil y marca lo que falta o está roto. Al dar la salida, Recepción lo ve ya cargado para descontarlo de la fianza.</p>
      <ul class="envios">${x.salidas.map((s, i) => `<li><b>${esc(s.unidad)}</b> · ${s.estado === "checkin" ? "salida prevista" : "salida hecha"} · ${s.hecha ? "✔ revisado" : "pendiente"} <button type="button" class="btn sm" data-copia="${i}">Copiar enlace</button></li>`).join("")}</ul>
      <div class="toolbar"><button type="button" class="btn primary" data-wa>Enviar todos por WhatsApp</button></div>` : '<p class="muted">No hay salidas ese día.</p>' }], {}, async () => {}));
    f.querySelectorAll("[data-copia]").forEach((b) => (b.onclick = () => navigator.clipboard.writeText(x.salidas[b.dataset.copia].url).then(() => toast("Enlace copiado"))));
    if ($("[data-wa]", f)) $("[data-wa]", f).onclick = () => window.open(x.whatsapp, "_blank", "noopener");
  };
  $("#lxls", el).onclick = () => run(() => download("GET", `/api/limpieza/parte.xlsx?asset_id=${cur.id}&fecha=${fecha()}`));
  $("#lenv", el).onclick = async () => {
    const gente = await get("/api/personal", { asset_id: cur.id, area: "limpieza", solo_activos: true }).catch(() => []);
    form(`Enviar parte de limpieza · ${fdate(fecha())}`, [
      { html: `<p class="muted">${p.limpiezas.filter((x) => x.estado === "pendiente").length} limpieza(s) pendiente(s). Por correo va el PDF adjunto; por WhatsApp, el parte escrito.</p>` },
      ...(gente.length ? [{ k: "personal_ids", t: "Personal de limpieza", type: "checks", options: gente.map((x) => [String(x.id), personaTxt(x)]) }] : [{ html: '<p class="muted">No hay personal de limpieza dado de alta (Personal → Fichas del personal): indique un número o un correo.</p>' }]),
      canalEnvio(" (con el PDF)"),
      { k: "telefono", t: "Otro número (WhatsApp)" }, { k: "email", t: "Otro correo", type: "email" },
      { k: "nota", t: "Nota (opcional)", type: "textarea", wide: true },
    ], {}, async (d) => {
      const r = await post("/api/limpieza/parte/enviar", { ...clean(d), asset_id: cur.id, fecha: fecha(), personal_ids: (d.personal_ids || []).map(Number) });
      setTimeout(() => resultadoEnvio("Parte de limpieza enviado · Excel guardado en documentos", r.enviados), 0);
    }, "Enviar");
  };
  await load();
};
V.personal = async (el) => {
  // Personal propio de las sociedades: lo da de alta el Director Técnico. Subcontratas: Recepción (1 y 2), quien
  // gestiona mantenimiento o limpieza y dirección. Un usuario del PMS solo puede estar en una ficha.
  const dt = !!(S.me.is_superadmin || can("personal.autorizar_mto"));
  const alta = dt || ["mantenimiento.abrir", "mantenimiento.editar", "limpieza.editar", "personal.autorizar"].some(can);
  el.innerHTML = `<div class="toolbar"><select id="ar"><option value="">Todas las áreas</option>${AREAS.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>
    <span class="spacer"></span>${dt ? '<button class="btn" id="chk">Comprobar personal</button>' : ""}${can("limpieza.editar") ? '<button class="btn" id="pl">Enviar parte de limpieza</button>' : ""}${alta ? '<button class="btn primary" id="new">Nueva persona</button>' : ""}</div>
    <p class="muted">${dt ? "Como Director Técnico da de alta al <b>personal propio</b> de las sociedades (con su ficha de empleado y su usuario del PMS, que solo puede estar en una ficha) y también al de subcontratas." : "Recepción da de alta solo al <b>personal de subcontratas</b> (indique la empresa). El personal propio de las sociedades lo da de alta el Director Técnico."} Las vacaciones y ausencias las pide cada persona con su usuario, sobre su propia ficha.</p><div id="t"></div>`;
  const catP = await get("/api/personal/catalogos");
  let usuarios = [];
  const frescos = async () => { if (dt) usuarios = await get("/api/personal/usuarios").catch(() => []); };  // un usuario, una ficha
  const fields = (p) => [
    ...(dt && !p ? [{ k: "tipo", t: "Tipo de personal", type: "select", req: true, options: [["propio", "Personal propio de la sociedad"], ["subcontrata", "Subcontrata (indique la empresa)"]], wide: true }] : []),
    { k: "area", t: "Área", type: "select", req: true, options: AREAS },
    { k: "asset_id", t: "Activo (vacío = todos)", type: "select", options: opts(S.assets) },
    { k: "nombre", t: "Nombre", req: true }, { k: "empresa", t: dt ? "Empresa (solo si es subcontrata)" : "Empresa subcontratista", req: !dt },
    { k: "email", t: "Correo electrónico", type: "email" }, { k: "telefono", t: "Móvil (WhatsApp)" },
    { k: "avisar_urgentes", t: "Recibir al momento por correo las OT urgentes (mantenimiento)", type: "checkbox", wide: true },
    { k: "activo", t: "En activo", type: "checkbox", def: true },
    { k: "notas", t: "Notas (horario, especialidad…)", type: "textarea", wide: true },
  ];
  // datos laborales del personal propio: los gestiona el Director Técnico
  const ficha = (p) => [
    { html: '<fieldset><legend>Ficha del empleado (personal propio)</legend><p class="muted peq">La gestiona el Director Técnico. Las vacaciones se cuentan con estos datos y el registro de jornada se hace sobre esta ficha. El usuario del PMS solo puede estar en una ficha.</p></fieldset>', wide: true },
    { k: "dni", t: "DNI / NIE" }, { k: "puesto", t: "Puesto" },
    { k: "tipo_contrato", t: "Contrato", type: "select", options: Object.entries(catP.contratos) },
    { k: "jornada_semanal", t: "Jornada (horas / semana)", type: "number" },
    { k: "fecha_alta", t: "Fecha de alta", type: "date" }, { k: "fecha_baja", t: "Fecha de baja", type: "date" },
    { k: "vacaciones_dias", t: "Días de vacaciones al año (convenio)", type: "number" },
    { k: "vacaciones_tipo", t: "Los días son", type: "select", options: [["laborables", "Laborables"], ["naturales", "Naturales"]] },
    { k: "user_id", t: "Su usuario del PMS (para pedir vacaciones y fichar)", type: "select", wide: true,
      options: usuarios.filter((u) => !u.ficha_id || u.ficha_id === p?.id).map((u) => [u.id, `${u.nombre} · ${u.email}`]) },
  ];
  const camposDe = (p) => (dt && (!p || p.propio) ? [...fields(p), ...ficha(p)] : fields(p));
  const guardar = (p) => async (d) => {
    const sub = p ? !p.propio : !dt || d.tipo === "subcontrata";
    if (sub && !(d.empresa || "").trim()) throw new Error("Indique la empresa subcontratista");
    if (!sub && (d.empresa || "").trim()) throw new Error("El personal propio no lleva empresa: elija «Subcontrata» o deje la empresa vacía");
    delete d.tipo;
    const body = { ...d, asset_id: d.asset_id ? Number(d.asset_id) : null, user_id: d.user_id ? Number(d.user_id) : null,
      jornada_semanal: d.jornada_semanal ? Number(d.jornada_semanal) : null, vacaciones_dias: d.vacaciones_dias !== undefined && d.vacaciones_dias !== null && d.vacaciones_dias !== "" ? Number(d.vacaciones_dias) : null,
      tipo_contrato: d.tipo_contrato || null, vacaciones_tipo: d.vacaciones_tipo || null, fecha_alta: d.fecha_alta || null, fecha_baja: d.fecha_baja || null };
    if (!dt || sub) ["user_id", "dni", "puesto", "tipo_contrato", "jornada_semanal", "fecha_alta", "fecha_baja", "vacaciones_dias", "vacaciones_tipo"].forEach((k) => { if (p && !(k in d)) body[k] = p[k] ?? null; });
    await (p ? put(`/api/personal/${p.id}`, body) : post("/api/personal", body));
    toast(p ? "Ficha guardada" : "Persona dada de alta"); load();
    if (sub) await altaProveedorSiNuevo(d.empresa, d.area === "limpieza" ? "Limpieza" : d.area === "mantenimiento" ? "Mantenimiento" : "Otros");
  };
  const load = async () => table($("#t", el), [
    { k: "area_nombre", t: "Área" },
    { k: "nombre", t: "Nombre", f: (v, p) => `${esc(v)}${p.activo ? "" : ' <span class="badge">baja</span>'}${p.puesto ? `<div class="muted peq">${esc(p.puesto)}</div>` : ""}<div class="muted peq">${p.propio ? `Personal propio${p.usuario ? ` · usuario ${esc(p.usuario)}` : ""}` : `Subcontrata · ${esc(p.empresa || "")}`}</div>` },
    { k: "activo_nombre", t: "Activo" },
    { k: "telefono", t: "Contacto", f: (v, p) => [v, p.email].filter(Boolean).map(esc).join("<br>") + (p.avisar_urgentes ? '<div class="muted peq">OT urgentes al momento</div>' : "") },
    { k: "saldo", t: "Vacaciones", f: (v) => (v ? `<b>${v.pendientes_solicitar}</b> por solicitar<div class="muted peq">de ${v.corresponden} ${v.tipo} · ${v.disfrutadas} disfrutadas · ${v.solicitadas} solicitadas${v.por_aprobar ? ` (${v.por_aprobar} por aprobar)` : ""}</div>` : "") },
    { k: "fichado", t: "Jornada", f: (v, p) => (p.gestiona && p.propio ? (v ? '<span class="badge b-vigente">dentro</span>' : '<span class="muted">fuera</span>') : "") },
    { k: "documentos_vencen", t: "Docs.", f: (v) => (v ? `<span class="badge b-urgente" title="Documentos vencidos">${v} ⚠</span>` : "") },
  ], await get("/api/personal", { asset_id: S.asset, area: $("#ar", el).value }), (p) => [
    p.editable && ["Editar", async () => { await frescos(); sugerirProveedores(form(p.nombre, camposDe(p), p, guardar(p)), "empresa"); }],
    p.gestiona && p.propio && ["Vacaciones", () => vacacionesFicha(p, load)],
    p.gestiona && ["Docs.", () => documentosEmpleado(p, load)],
    p.gestiona && p.propio && ["Enlace", () => enlaceFichaje(p, load)],
    p.gestiona && p.propio && ["Jornada", () => { S.jornadaStaff = p.id; go("jornada"); }],
    p.editable && ["Borrar", async () => { if (confirm(`¿Borrar la ficha de ${p.nombre}?`)) { await run(() => api("DELETE", `/api/personal/${p.id}`), "Ficha borrada"); load(); } }, "danger"],
  ]);
  $("#ar", el).onchange = load;
  if ($("#new", el)) $("#new", el).onclick = async () => { await frescos(); sugerirProveedores(form("Nueva persona", camposDe(null), { tipo: dt ? "propio" : "subcontrata", area: AREAS[0][0], asset_id: S.asset || (S.assets.length === 1 ? S.assets[0].id : "") }, guardar(null)), "empresa"); };
  if ($("#pl", el)) $("#pl", el).onclick = () => parteLimpieza(today());
  if ($("#chk", el)) $("#chk", el).onclick = () => comprobarPersonal(load);
  load();
};

// Vacaciones de la ficha: saldo (disfrutadas, solicitadas, pendientes de solicitar) y periodos. El Director Técnico
// registra las ya disfrutadas y las ya acordadas para cuadrar el saldo; cada cambio envía el calendario a todos.
async function vacacionesFicha(p, reload) {
  const r = await get(`/api/personal/${p.id}/vacaciones`), s = r.saldo;
  const filas = r.periodos.map((x) => `<tr><td>${fdate(x.desde)}${x.hasta !== x.desde ? ` – ${fdate(x.hasta)}` : ""}</td><td class="num">${x.dias}</td>
    <td><span class="badge ${x.estado === "disfrutada" ? "b-vigente" : x.estado === "por aprobar" ? "b-pendiente" : "b-borrador"}">${esc(x.estado)}</span></td>
    <td class="peq muted">${x.registrada_por ? `registrada por ${esc(x.registrada_por)}` : "solicitada por la persona"}</td>
    <td>${r.registrar ? `<button type="button" class="btn sm danger" data-anula="${x.id}">Anular</button>` : ""}</td></tr>`).join("");
  const f = form(`Vacaciones ${s.anio} · ${p.nombre}`, [
    { html: `<div class="capex-kpis" style="margin-bottom:10px"><div><small>Corresponden (${esc(s.tipo)})</small><b>${s.corresponden}</b></div><div><small>Disfrutadas</small><b>${s.disfrutadas}</b></div>
      <div><small>Solicitadas (pdte. disfrutar)</small><b>${s.solicitadas}</b></div><div class="${s.pendientes_solicitar > 0 ? "mal" : ""}"><small>Pendientes de solicitar</small><b>${s.pendientes_solicitar}</b></div></div>
      ${filas ? `<div class="table-wrap"><table><thead><tr><th>Periodo</th><th class="num">Días</th><th>Estado</th><th></th><th></th></tr></thead><tbody>${filas}</tbody></table></div>` : '<p class="muted">Sin periodos registrados este año.</p>'}
      ${r.registrar ? `<h4>Registrar vacaciones (Director Técnico)</h4><p class="muted peq">Para cuadrar el saldo: periodos ya disfrutados o ya acordados con la persona. Quedan autorizados y se incluyen en la próxima revisión del calendario, que se envía a todos los usuarios y colaboradores.</p><div id="vfPer"></div><button type="button" class="btn sm" id="vfMas">+ Otro periodo</button>` : ""}` },
    ...(r.registrar ? [{ k: "nota", t: "Nota (opcional)", wide: true }] : []),
  ], {}, async (d, fm) => {
    if (!r.registrar) return;
    const periodos = [...fm.querySelectorAll(".vf-per")].map((x) => ({ desde: x.querySelector("[data-d]").value, hasta: x.querySelector("[data-h]").value })).filter((x) => x.desde && x.hasta);
    if (!periodos.length) throw new Error("Indique al menos un periodo (desde y hasta)");
    await post(`/api/personal/${p.id}/vacaciones`, { periodos, nota: d.nota });
    toast("Vacaciones registradas · saldrán en la próxima revisión del calendario"); reload();
  }, r.registrar ? "Registrar" : "Cerrar");
  $("#modal").classList.add("ancho");
  const otro = () => $("#vfPer", f).insertAdjacentHTML("beforeend", '<div class="vf-per toolbar"><label>Desde <input type="date" data-d></label><label>Hasta <input type="date" data-h></label></div>');
  if (r.registrar) { otro(); $("#vfMas", f).onclick = otro; }
  f.querySelectorAll("[data-anula]").forEach((b) => (b.onclick = async () => {
    const m = prompt("Motivo de la anulación (se comunica a la persona y a Recepción):"); if (!m) return;
    await run(() => post(`/api/ausencias/${b.dataset.anula}/anular`, { nota: m }), "Periodo anulado"); $("#modal").close(); reload(); vacacionesFicha(p, reload);
  }));
}

// Comprobación de errores (Recepción 1 de cada activo, fichas, usuarios repetidos, solicitudes mal clasificadas),
// corrección automática y borrado de todo el personal para empezar de nuevo
async function comprobarPersonal(reload) {
  const r = await get("/api/personal/comprobar");
  const color = { error: "b-urgente", aviso: "b-pendiente", info: "b-borrador" };
  const f = cerrarSolo(form("Comprobar personal", [{ html: `<p>${r.fichas} ficha(s) de personal.</p>
    ${r.resultados.length ? `<table><tbody>${r.resultados.map((x) => `<tr><td><span class="badge ${color[x.nivel]}">${esc(x.nivel)}</span></td><td><b>${esc(x.que)}</b></td><td>${esc(x.texto)}</td></tr>`).join("")}</tbody></table>` : '<p class="ok">✔ No se ha encontrado ningún error.</p>'}
    <div class="toolbar">${r.resultados.some((x) => x.corregible) ? '<button type="button" class="btn primary" id="cpFix">Corregir las solicitudes mal clasificadas</button>' : ""}
      <button type="button" class="btn" id="cpGen">Generar las fichas desde los usuarios</button><span class="spacer"></span>
      ${r.puede_borrar ? '<button type="button" class="btn danger" id="cpDel">Borrar todo el personal</button>' : ""}</div>
    <p class="muted peq">Recepción 1 de cada activo se asigna en Activos → Editar. Los roles se asignan en Administración → Usuarios.</p>` }], {}, async () => {}));
  $("#modal").classList.add("ancho");
  if ($("#cpFix", f)) $("#cpFix", f).onclick = async () => { const x = await run(() => post("/api/personal/comprobar/corregir")); toast(`${x.corregidas} solicitud(es) corregida(s)`); comprobarPersonal(reload); };
  $("#cpGen", f).onclick = async () => {
    if (!confirm("Se creará la ficha de personal propio de cada usuario del PMS que aún no la tenga (área y activo según su rol; sin presidencia ni colaboradores). Después complete en cada ficha el DNI, contrato, jornada y vacaciones.")) return;
    const x = await run(() => post("/api/personal/generar-desde-usuarios"));
    toast(x.creadas.length ? `${x.creadas.length} ficha(s) creada(s)` : "Todos los usuarios ya tienen ficha"); reload(); comprobarPersonal(reload);
  };
  if ($("#cpDel", f)) $("#cpDel", f).onclick = async () => {
    const c = prompt("Se borrarán TODAS las fichas del personal, sus fichajes, documentos y envíos (las ausencias de los usuarios se conservan). No se puede deshacer.\n\nEscriba BORRAR PERSONAL para confirmar:");
    if (c === null) return;
    const x = await run(() => post("/api/personal/borrar-todo", { confirmacion: c }));
    toast(`Borradas ${x.fichas} fichas, ${x.fichajes} fichajes y ${x.documentos} documentos`); $("#modal").close(); reload();
  };
}

// ---- ficha del empleado: documentos (contrato, nóminas, reconocimiento médico, formación…) con vencimiento
async function documentosEmpleado(p, reload) {
  const cat = await get("/api/personal/catalogos");
  const docs = await get(`/api/personal/${p.id}/documentos`);
  const filas = docs.length ? `<div class="table-wrap"><table><thead><tr><th>Tipo</th><th>Fecha</th><th>Vence</th><th>Notas</th><th class="acc"></th></tr></thead><tbody>
    ${docs.map((d) => `<tr><td>${esc(d.tipo_nombre)}</td><td>${fdate(d.fecha)}</td><td>${d.vence ? (d.vencido ? `<span class="badge b-urgente">${fdate(d.vence)} vencido</span>` : fdate(d.vence)) : ""}</td>
      <td>${esc(d.notas || "")}</td><td class="acc"><button type="button" class="btn sm" data-ver="${d.id}">Ver</button> <button type="button" class="btn sm danger" data-borra="${d.id}">Borrar</button></td></tr>`).join("")}
    </tbody></table></div>` : '<p class="muted">Sin documentos todavía.</p>';
  const f = form(`Documentos · ${p.nombre}`, [
    { html: `${filas}<p class="muted peq">Se guardan cifrados. Solo los ven Recepción 1 del activo y la dirección, y queda registrado quién los abre. Los que vencen en 30 días salen en el panel y en el resumen diario.</p><h4>Añadir documento</h4>` },
    { k: "tipo", t: "Tipo", type: "select", req: true, options: Object.entries(cat.documentos) },
    { k: "fecha", t: "Fecha del documento", type: "date" }, { k: "vence", t: "Vence (si caduca)", type: "date" },
    { k: "notas", t: "Notas", wide: true },
    { html: '<label class="wide">Fichero (PDF o foto) *<input type="file" name="fichero" accept="application/pdf,image/*" required></label>' },
  ], {}, async (d, fm) => {
    const fd = new FormData();
    fd.append("ficheros", fm.elements.fichero.files[0]); fd.append("tipo", d.tipo);
    ["fecha", "vence", "notas"].forEach((k) => d[k] && fd.append(k, d[k]));
    await upload(`/api/personal/${p.id}/documentos`, fd);
    toast("Documento guardado"); reload && reload();
    setTimeout(() => documentosEmpleado(p, reload), 0);
  }, "Subir documento");
  $("#modal").classList.add("ancho");
  f.querySelectorAll("[data-ver]").forEach((b) => (b.onclick = () => abrirFichero(`/api/personal/documentos/${b.dataset.ver}`)));
  f.querySelectorAll("[data-borra]").forEach((b) => (b.onclick = async () => {
    if (!confirm("¿Borrar este documento?")) return;
    await run(() => api("DELETE", `/api/personal/documentos/${b.dataset.borra}`), "Documento borrado");
    reload && reload(); documentosEmpleado(p, reload);
  }));
}

// ---- enlace personal para fichar desde el móvil (personal sin usuario del PMS)
async function enlaceFichaje(p, reload, nuevo = false) {
  const r = await run(() => api("POST", `/api/personal/${p.id}/enlace-fichaje${nuevo ? "?nuevo=true" : ""}`));
  const f = cerrarSolo(form(`Enlace de fichaje · ${p.nombre}`, [{ html: `
    <p>Con este enlace <b>${esc(p.nombre)}</b> ficha la entrada y la salida desde su móvil, sin usuario ni contraseña. Que lo guarde en la pantalla de inicio.</p>
    <p><input id="enl" readonly value="${esc(r.url)}" style="width:100%"></p>
    <div class="toolbar"><button type="button" class="btn" id="copiar">Copiar enlace</button>
      ${r.whatsapp ? `<a class="btn primary" href="${esc(r.whatsapp)}" target="_blank" rel="noopener">Enviar por WhatsApp</a>` : '<span class="muted">Sin móvil en la ficha: cópielo y envíelo usted.</span>'}
      <span class="spacer"></span><button type="button" class="btn danger" id="cambiar">Cambiar enlace</button></div>
    <p class="muted peq">«Cambiar enlace» anula el anterior (si lo ha perdido o lo ha compartido). Al dar de baja la ficha, el enlace deja de funcionar.</p>` }], {}, async () => {}));
  $("#copiar", f).onclick = async () => {
    try { await navigator.clipboard.writeText(r.url); toast("Enlace copiado"); } catch { $("#enl", f).select(); document.execCommand("copy"); toast("Enlace copiado"); }
  };
  $("#cambiar", f).onclick = () => { if (confirm("El enlace actual dejará de funcionar. ¿Crear uno nuevo?")) enlaceFichaje(p, reload, true); };
  reload && reload();
}

// ---- registro de jornada (Recepción 1 y dirección): consulta del mes, correcciones, informe y Excel
const horasTxt = (h) => `${Number(h || 0).toFixed(2).replace(".", ",")} h`;
const hhmm = (iso) => (iso ? new Date(iso).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" }) : "—");
const isoMin = (iso) => (iso ? iso.slice(0, 16) : "");
V.jornada = async (el) => {
  S.jornadaMes = S.jornadaMes || today().slice(0, 7);
  el.innerHTML = `<div class="toolbar"><label>Mes <input type="month" id="mes" value="${S.jornadaMes}"></label>
    <select id="per"><option value="">Todo el personal</option></select>
    <span class="spacer"></span><button class="btn" id="man">Registro manual</button><button class="btn" id="xl">Excel del mes (asesoría)</button></div>
    <p class="muted">Registro diario de jornada del personal propio (art. 34.9 ET): entrada y salida con la hora del servidor. Se conserva 4 años. Fichan desde «Mi jornada» (con usuario) o con su enlace personal (Personal → Fichas del personal → «Enlace fichaje»). Las correcciones guardan el registro original, quién lo cambia y el motivo.</p>
    <div id="t"></div>`;
  let datos = [];
  const corregir = (e, t) => form(`Corregir fichaje · ${e.nombre}`, [
    ...(t.original ? [{ html: `<p class="muted">Original: entrada ${fdt(t.original.entrada)} · salida ${t.original.salida ? fdt(t.original.salida) : "—"}</p>` }] : []),
    { k: "entrada", t: "Entrada", type: "datetime-local", req: true }, { k: "salida", t: "Salida", type: "datetime-local" },
    { k: "motivo", t: "Motivo de la corrección", req: true, wide: true },
  ], { entrada: isoMin(t.entrada), salida: isoMin(t.salida), motivo: t.motivo || "" }, async (d) => {
    await post(`/api/jornada/${t.id}/corregir`, d); toast("Fichaje corregido"); load();
  });
  const manual = (staffId) => form("Registro manual de jornada", [
    { k: "staff_id", t: "Empleado", type: "select", req: true, options: datos.map((e) => [e.id, `${e.nombre}${e.puesto ? " · " + e.puesto : ""}`]) },
    { k: "entrada", t: "Entrada", type: "datetime-local", req: true }, { k: "salida", t: "Salida", type: "datetime-local" },
    { k: "motivo", t: "Motivo (no pudo fichar…)", req: true, wide: true },
  ], { staff_id: staffId || "" }, async (d) => {
    await api("POST", "/api/jornada/manual", { ...d, staff_id: Number(d.staff_id) }); toast("Registro guardado"); load();
  });
  const detalle = (e) => {
    const f = cerrarSolo(form(`${e.nombre} · ${S.jornadaMes}`, [{ html: `<p>${horasTxt(e.horas)} en ${e.dias} día(s)${e.sin_salida ? ` · <span class="error">${e.sin_salida} sin salida</span>` : ""}</p>
      ${e.fichajes.length ? `<div class="table-wrap"><table><thead><tr><th>Día</th><th>Entrada</th><th>Salida</th><th class="num">Horas</th><th>Origen</th><th>Observaciones</th><th class="acc"></th></tr></thead><tbody>
      ${e.fichajes.map((t, i) => `<tr><td>${fdate(t.entrada)}</td><td>${hhmm(t.entrada)}</td><td>${t.salida ? hhmm(t.salida) : '<span class="error">sin salida</span>'}</td><td class="num">${horasTxt(t.horas)}</td>
        <td>${esc(t.origen)}${t.lat != null ? ` <a href="https://maps.google.com/?q=${t.lat},${t.lon}" target="_blank" rel="noopener" title="Ubicación al fichar">📍</a>` : ""}</td>
        <td class="peq">${t.corregido || t.origen === "manual" ? `${esc(t.motivo || "")} <span class="muted">(${esc(t.editado_nombre || "")})</span>` : ""}</td>
        <td class="acc"><button type="button" class="btn sm" data-c="${i}">Corregir</button></td></tr>`).join("")}</tbody></table></div>` : '<p class="muted">Sin fichajes este mes.</p>'}
      <div class="toolbar"><button type="button" class="btn" id="dm">Registro manual</button><span class="spacer"></span><button type="button" class="btn primary" id="dp">Informe PDF para firmar</button></div>` }], {}, async () => {}));
    $("#modal").classList.add("ancho");
    f.querySelectorAll("[data-c]").forEach((b) => (b.onclick = () => corregir(e, e.fichajes[b.dataset.c])));
    $("#dm", f).onclick = () => manual(e.id);
    $("#dp", f).onclick = () => run(() => download("GET", `/api/jornada/informe.pdf?staff_id=${e.id}&mes=${S.jornadaMes}`));
  };
  const load = async () => {
    S.jornadaMes = $("#mes", el).value || today().slice(0, 7);
    try { datos = await get("/api/jornada", { mes: S.jornadaMes, asset_id: S.asset }); }
    catch (e) { $("#t", el).innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }
    const sel = $("#per", el), v = S.jornadaStaff || sel.value;
    sel.innerHTML = '<option value="">Todo el personal</option>' + datos.map((e) => `<option value="${e.id}" ${String(e.id) === String(v) ? "selected" : ""}>${esc(e.nombre)}</option>`).join("");
    S.jornadaStaff = null;
    const filas = sel.value ? datos.filter((e) => String(e.id) === sel.value) : datos;
    table($("#t", el), [
      { k: "nombre", t: "Empleado" }, { k: "puesto", t: "Puesto" }, { k: "activo", t: "Activo" },
      { k: "dentro", t: "Hoy", f: (v) => (v ? '<span class="badge b-vigente">dentro</span>' : '<span class="muted">fuera</span>') },
      { k: "dias", t: "Días", num: true }, { k: "horas", t: "Horas del mes", num: true, f: horasTxt },
      { k: "sin_salida", t: "Sin salida", num: true, f: (v) => (v ? `<span class="badge b-urgente">${v}</span>` : "") },
      { k: "enlace", t: "Ficha con", f: (v, e) => [e.usuario && "usuario", v && "enlace"].filter(Boolean).join(" y ") || '<span class="muted">sin configurar</span>' },
    ], filas, (e) => [["Detalle", () => detalle(e)], ["Informe PDF", () => run(() => download("GET", `/api/jornada/informe.pdf?staff_id=${e.id}&mes=${S.jornadaMes}`))]]);
    if (filas.length === 1 && sel.value) detalle(filas[0]);
  };
  $("#mes", el).onchange = load; $("#per", el).onchange = load;
  $("#man", el).onclick = () => manual(Number($("#per", el).value) || null);
  $("#xl", el).onclick = () => run(() => download("GET", `/api/jornada/excel?mes=${S.jornadaMes}${S.asset ? `&asset_id=${S.asset}` : ""}`));
  load();
};

// ---- Mi jornada: el propio empleado ficha entrada y salida
V.mijornada = async (el) => {
  let gps = {};
  if (navigator.geolocation) navigator.geolocation.getCurrentPosition((x) => { gps = { lat: x.coords.latitude, lon: x.coords.longitude }; }, () => {}, { timeout: 8000, maximumAge: 120000 });
  const pinta = (e, msg = "") => {
    el.innerHTML = `<div class="mi-jornada" style="max-width:460px;margin:0 auto;text-align:center">
      <h3>${esc(e.nombre)}${e.puesto ? ` <span class="muted">· ${esc(e.puesto)}</span>` : ""}</h3>
      <p style="font-size:18px">${e.dentro ? `<b style="color:var(--ok,#2e7d4f)">● Dentro</b> desde las ${hhmm(e.desde)}` : '<b class="muted">○ Fuera</b>'}</p>
      <button class="btn ${e.dentro ? "danger" : "primary"}" id="fichar" style="width:100%;min-height:72px;font-size:22px">${e.dentro ? "Fichar SALIDA" : "Fichar ENTRADA"}</button>
      <p class="${msg.startsWith("✔") ? "ok" : "error"}">${esc(msg)}</p>
      <div class="table-wrap no-encajar"><table><thead><tr><th>Hoy · entrada</th><th>Salida</th><th class="num">Horas</th></tr></thead><tbody>
      ${e.hoy.length ? e.hoy.map((t) => `<tr><td>${hhmm(t.entrada)}</td><td>${hhmm(t.salida)}</td><td class="num">${horasTxt(t.horas)}</td></tr>`).join("") : '<tr><td colspan="3" class="muted">Sin fichajes hoy</td></tr>'}
      </tbody></table></div>
      <p class="muted">Este mes: <b>${horasTxt(e.horas_mes)}</b>${e.jornada_semanal ? ` · contrato ${e.jornada_semanal} h/semana` : ""}. Se registra la hora del servidor y, si lo permite, la ubicación. Si se equivoca, avise a Recepción 1 para corregirlo.</p></div>`;
    $("#fichar", el).onclick = async (ev) => {
      ev.target.disabled = true;
      try {
        const r = await post("/api/jornada/mia/fichar", gps);
        pinta(r, r.dentro ? `✔ Entrada registrada a las ${hhmm(r.fichaje.entrada)}` : `✔ Salida registrada a las ${hhmm(r.fichaje.salida)}`);
      } catch (err) { toast(err.message, true); ev.target.disabled = false; }
    };
  };
  try { pinta(await get("/api/jornada/mia")); }
  catch (e) { el.innerHTML = `<p class="error">${esc(e.message)}</p><p class="muted">Recepción 1 o dirección enlazan su usuario en Personal → Fichas del personal → Editar → «Su usuario del PMS».</p>`; }
};

// ---- documentos recibidos (carpeta de cada activo) y cuenta de gastos
async function catGastos() { S.catGastos = S.catGastos || await get("/api/gastos/catalogos"); return S.catGastos; }
// Campos del gasto (en el alta de un documento y en el gasto sin documento)
function camposGasto(C, unidades, alta = true) {
  return [
    { k: "categoria", t: "Categoría del gasto", type: "select", options: kv(C.categorias) },
    { k: "naturaleza", t: "OPEX o CAPEX", type: "select", options: kv(C.naturalezas) },
    { k: "ambito", t: "Imputado a", type: "select", options: kv(C.ambitos), def: "general" },
    { k: "unit_id", t: "Apartamento", type: "select", options: unidades.map((u) => [u.id, `${u.codigo}${u.bloque ? " · " + u.bloque : ""}`]) },
    { k: "ambito_detalle", t: "Detalle (zona, varios apartamentos…)" },
    { k: "concepto", t: "Concepto del gasto", wide: true },
    { k: "total", t: "Total de la factura € (el que figura: IVA incluido y retención descontada)", type: "number" },
    { k: "tipo_iva", t: "IVA %", type: "select", options: C.ivas.map((x) => [x, `${x} %`]), def: 21 },
    { k: "base", t: "Base € (solo si hay varios tipos de IVA)", type: "number" },
    { k: "retencion_tipo", t: "Retención (IRPF u otra)", type: "select", options: Object.entries(C.retenciones).map(([k, v]) => [k, v.pct ? `${v.nombre} · ${v.pct} %` : v.nombre]) },
    { k: "retencion_pct", t: "Retención %", type: "number" },
    { k: "forma_pago", t: "Se paga por (transferencia o cargo en cuenta)", type: "select", options: kv(C.formas_pago) },
    { k: "pagado", t: "Pagado (se marca con el botón «Pagado» de la cuenta de gastos, adjuntando el justificante de pago)", type: "checkbox", wide: true }, { k: "fecha_pago", t: "Fecha de pago", type: "date" },
    ...(alta ? [{ k: "retener_pago", t: "Retener el pago: no pagar de momento (se avisa a dirección y administración)", type: "checkbox", wide: true },
      { k: "retener_motivo", t: "Motivo de la retención del pago", wide: true }, { k: "retener_revision", t: "Fecha de revisión", type: "date" }] : []),
  ];
}
// Retención IRPF: % habitual al elegir el tipo. Pago retenido: motivo y fecha de revisión.
function bindRetencion(f) {
  const C = S.catGastos, e = f.elements;
  if (e.pagado) e.pagado.disabled = true;  // solo con el justificante (botón «Pagado»)
  const pinta = () => {
    verCampos(f, ["retencion_pct"], !!e.retencion_tipo.value);
    verCampos(f, ["fecha_pago"], !!e.pagado?.checked);
    if (e.retener_pago) { verCampos(f, ["retener_motivo", "retener_revision"], e.retener_pago.checked); verCampos(f, ["pagado", "fecha_pago"], !e.retener_pago.checked); }
  };
  e.retencion_tipo.onchange = () => { const p = C.retenciones[e.retencion_tipo.value]?.pct; if (p) e.retencion_pct.value = p; pinta(); };
  if (e.retener_pago) e.retener_pago.onchange = pinta;
  pinta();
}
const CAMPOS_GASTO = ["categoria", "naturaleza", "ambito", "unit_id", "ambito_detalle", "concepto", "total", "tipo_iva", "base", "retencion_tipo", "retencion_pct", "forma_pago", "pagado", "fecha_pago", "retener_pago", "retener_motivo", "retener_revision"];
function verCampos(f, nombres, ver) { nombres.forEach((n) => { const el = f.elements[n]; if (el) (el.closest("label") || el).style.display = ver ? "" : "none"; }); }
function bindAmbito(f) {
  const pinta = () => { const a = f.elements.ambito.value; verCampos(f, ["unit_id"], a === "apartamento"); verCampos(f, ["ambito_detalle"], a === "otro"); };
  f.elements.ambito.onchange = pinta; pinta();
}
function datosGasto(d, extra = {}) {
  if (!d.categoria) throw new Error("Elija la categoría del gasto");
  if (!d.naturaleza) throw new Error("Indique si el gasto es OPEX (gasto corriente) o CAPEX (inversión)");
  if (d.total == null) throw new Error("Indique el importe total del gasto");
  if (d.ambito === "apartamento" && !d.unit_id) throw new Error("Elija el apartamento del gasto");
  if (!d.forma_pago) throw new Error("Indique cómo se paga: transferencia o cargo en cuenta (domiciliación)");
  if (d.retencion_tipo && !(Number(d.retencion_pct) > 0)) throw new Error("Indique el % de la retención");
  if (d.retener_pago && (!d.retener_motivo || !d.retener_revision)) throw new Error("Para retener el pago indique el motivo y la fecha de revisión");
  return clean({ categoria: d.categoria, naturaleza: d.naturaleza, ambito: d.ambito, unit_id: d.unit_id ? Number(d.unit_id) : null, ambito_detalle: d.ambito_detalle,
    concepto: d.concepto, total: d.total, tipo_iva: Number(d.tipo_iva ?? 21), base: d.base, forma_pago: d.forma_pago, pagado: !!d.pagado && !d.retener_pago, fecha_pago: d.fecha_pago,
    retencion_tipo: d.retencion_tipo || null, retencion_pct: d.retencion_tipo ? Number(d.retencion_pct) : 0,
    retener_pago: !!d.retener_pago, retener_motivo: d.retener_pago ? d.retener_motivo : null, retener_revision: d.retener_pago ? d.retener_revision : null, ...extra });
}
// Facturas: «Posible duplicado» se puede registrar si quien la sube lo confirma; «Factura duplicada» no se registra.
async function conDuplicado(enviar) {
  try { return await enviar(false); } catch (e) {
    if (/^Posible duplicado/.test(e.message) && confirm(`${e.message}\n\n¿Es otra factura distinta y quiere registrarla igualmente?`)) return enviar(true);
    throw e;
  }
}
async function unidadesActivo(aid) { return (await get("/api/unidades", { asset_id: aid })).filter((u) => u.uso !== "garaje"); }

// Lector de facturas: al elegir el PDF o las fotos, propone los datos. Lo dudoso o no encontrado, en amarillo.
const CAMPOS_LECTOR = ["fecha", "vencimiento", "emisor", "referencia", "total", "tipo_iva", "base", "retencion_tipo", "retencion_pct", "forma_pago"];
function marcarRevisar(f, k, si) {
  const el = f.elements[k]; const lab = el && el.closest("label");
  if (!lab) return;
  lab.classList.toggle("revisar", si);
  if (si && !el._quitaRevisar) { el._quitaRevisar = true; el.addEventListener("input", () => lab.classList.remove("revisar")); el.addEventListener("change", () => lab.classList.remove("revisar")); }
}
async function leerFactura(f) {
  const files = ficherosElegidos(f), msg = $("[data-fotosmsg]", f);
  if (!files.length || !["factura", "ticket"].includes(f.elements.tipo.value)) return;
  const antes = msg.textContent;
  msg.textContent = "📄 Leyendo la factura…";
  try {
    const fd = new FormData(); files.forEach((x) => fd.append("ficheros", x));
    const r = await upload("/api/documentos-recibidos/leer", fd), c = r.campos, e = f.elements;
    const pon = (k, v) => { if (v == null || !e[k]) return; e[k].value = String(v); };
    ["fecha", "vencimiento", "emisor", "referencia", "total", "base", "forma_pago"].forEach((k) => pon(k, c[k]));
    if (c.tipo_iva != null) pon("tipo_iva", c.tipo_iva);
    if (c.retencion_tipo && e.retencion_tipo) { e.retencion_tipo.value = c.retencion_tipo; e.retencion_tipo.dispatchEvent(new Event("change")); pon("retencion_pct", c.retencion_pct); }
    CAMPOS_LECTOR.forEach((k) => marcarRevisar(f, k, r.dudosos.includes(k)));
    msg.innerHTML = `${esc(antes)} · <b>${r.aviso ? esc(r.aviso) : `Datos leídos${c.nif ? ` (NIF emisor ${esc(c.nif)}${r.proveedor_conocido ? ", proveedor conocido" : ""})` : ""}: revise lo marcado en amarillo`}</b>`;
  } catch (err) { msg.textContent = `${antes} · no se pudo leer: ${err.message}`; }
}
async function subirDocumento(reload, fija = null) {  // fija = {asset_id, unit_id}: imputado a esa vivienda
  const aid = fija ? fija.asset_id : await pickAsset();
  const [C, unidades] = await Promise.all([catGastos(), unidadesActivo(aid)]);
  const f = form(`Subir documento recibido · ${assetName(aid)}`, [
    { k: "tipo", t: "Tipo de documento", type: "select", req: true, options: kv(C.tipos_documento), def: "factura" },
    { html: fotosHtml("Documento escaneado: PDF, o fotos de cada página (se unen en un PDF)", true) },
    { k: "fecha", t: "Fecha de la factura (la impresa en ella, no la de hoy)", type: "date", req: true },
    { k: "vencimiento", t: "Vencimiento (el de la factura)", type: "date" },
    { k: "emisor", t: "Emisor / proveedor" }, { k: "referencia", t: "Nº de factura / referencia" },
    { k: "descripcion", t: "Descripción", type: "textarea", wide: true },
    { k: "es_gasto", t: "Es un gasto: anotarlo en la cuenta de gastos del activo", type: "checkbox", wide: true, def: true },
    ...camposGasto(C, unidades),
  ], fija ? { ambito: "apartamento", unit_id: fija.unit_id } : {}, async (d, fr) => {
    const ficheros = ficherosElegidos(fr);
    if (!ficheros.length) throw new Error("Adjunte el documento escaneado (foto o PDF)");
    const gastoJson = d.es_gasto ? JSON.stringify(datosGasto(d, { fecha: d.fecha, vencimiento: d.vencimiento, concepto: d.concepto || d.descripcion || `${C.tipos_documento[d.tipo]} ${d.emisor || ""}`.trim(),
      proveedor: d.emisor, numero_factura: d.referencia })) : null;
    const r = await conDuplicado((confirmado) => {
      const fd = new FormData();
      ficheros.forEach((x) => fd.append("ficheros", x));
      fd.append("asset_id", aid); fd.append("tipo", d.tipo); fd.append("fecha", d.fecha);
      ["vencimiento", "emisor", "referencia", "descripcion"].forEach((k) => d[k] && fd.append(k, d[k]));
      if (d.ambito === "apartamento" && d.unit_id) fd.append("unit_id", d.unit_id);
      if (gastoJson) fd.append("gasto", gastoJson);
      fd.append("confirmar_duplicado", confirmado ? "true" : "false");
      return upload("/api/documentos-recibidos", fd);
    });
    toast(`Documento guardado en la carpeta de ${assetName(aid)}${r.gasto ? ` · gasto de ${eur(r.gasto.total)} anotado` : ""}`);
    reload && reload();
    await altaProveedorSiNuevo(d.emisor, d.es_gasto ? C.categorias[d.categoria] : null);
  }, "Guardar documento");
  bindFotos(f); bindAmbito(f); sugerirProveedores(f, "emisor");
  f.querySelectorAll("[data-fotos]").forEach((i) => { const antes = i.onchange; i.onchange = () => { antes(); leerFactura(f); }; });
  const gasto = () => { verCampos(f, CAMPOS_GASTO, f.elements.es_gasto.checked); if (f.elements.es_gasto.checked) { bindAmbito(f); bindRetencion(f); } };
  f.elements.es_gasto.onchange = gasto;
  f.elements.tipo.onchange = () => { f.elements.es_gasto.checked = ["factura", "ticket", "albaran"].includes(f.elements.tipo.value); gasto(); };
  gasto();
}

// Marcar una factura recibida como pagada: el justificante de pago es obligatorio
function pagarGasto(g, reload) {
  const C = S.catGastos || {};
  form(`Pagado · ${g.proveedor || g.concepto} · ${eur(g.liquido)}`, [
    { html: `<div class="aviso-vencidas"><b>Antes de marcar la factura como pagada es obligatorio adjuntar el justificante de pago</b> (transferencia, cargo en cuenta, recibo…). Se guarda en la carpeta del activo y queda enlazado al gasto.</div>` },
    { html: '<label class="wide">Justificante de pago (PDF o fotos) *<input type="file" name="ficheros" multiple accept="application/pdf,image/*" required></label>' },
    { k: "fecha_pago", t: "Fecha de pago", type: "date", req: true, def: today() },
    ...(g.forma_pago ? [] : [{ k: "forma_pago", t: "Se ha pagado por", type: "select", req: true, options: kv(C.formas_pago || {}) }]),
  ], {}, async (d, fm) => {
    const files = [...fm.querySelector("input[type=file]").files];
    if (!files.length) throw new Error("Adjunte el justificante de pago");
    const fd = new FormData();
    files.forEach((x) => fd.append("ficheros", x));
    fd.append("fecha_pago", d.fecha_pago);
    if (d.forma_pago) fd.append("forma_pago", d.forma_pago);
    await upload(`/api/gastos/${g.id}/pagar`, fd);
    toast("Factura pagada con su justificante"); reload && reload();
  }, "Marcar como pagada");
}
async function editarGasto(g, reload, aidNuevo) {
  const aid = g ? g.asset_id : aidNuevo || await pickAsset();
  const [C, unidades] = await Promise.all([catGastos(), unidadesActivo(aid)]);
  const f = form(g ? `Gasto · ${g.concepto}` : `Nuevo gasto sin documento · ${assetName(aid)}`, [
    { k: "fecha", t: "Fecha de la factura (la impresa en ella)", type: "date", req: true }, { k: "vencimiento", t: "Vencimiento", type: "date" },
    { k: "proveedor", t: "Proveedor" }, { k: "numero_factura", t: "Nº de factura" },
    ...camposGasto(C, unidades, !g), { k: "notas", t: "Notas", type: "textarea", wide: true },
  ], g ? { ...g, total: g.liquido, base: null } : {}, async (d) => {
    const body = datosGasto(d, { fecha: d.fecha, vencimiento: d.vencimiento, concepto: d.concepto, proveedor: d.proveedor, numero_factura: d.numero_factura, notas: d.notas });
    if (!body.concepto) throw new Error("Indique el concepto del gasto");
    await (g ? put(`/api/gastos/${g.id}`, body) : conDuplicado((c) => post("/api/gastos", { ...body, asset_id: aid, confirmar_duplicado: c })));
    toast(g ? "Gasto actualizado" : "Gasto anotado"); reload && reload();
    await altaProveedorSiNuevo(d.proveedor, C.categorias[d.categoria]);
  });
  bindAmbito(f); bindRetencion(f); sugerirProveedores(f, "proveedor");
}

V.docrecibidos = async (el) => {
  const C = await catGastos();
  const editar = can("documentos.editar");
  const ini = `${today().slice(0, 4)}-01-01`;
  el.innerHTML = `<div class="toolbar"><select id="tp"><option value="">Todos los tipos</option>${Object.entries(C.tipos_documento).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select>
    <label>Desde<input type="date" id="d" value="${ini}"></label><label>Hasta<input type="date" id="h" value="${today()}"></label>
    <input id="q" placeholder="Emisor, referencia, descripción"><select id="rv"><option value="">Todos</option><option value="pendiente">De colaboradores: por revisar</option><option value="aceptado">De colaboradores: aceptados</option><option value="rechazado">De colaboradores: rechazados</option></select>
    <span class="spacer"></span>${editar ? '<button class="btn primary" id="new">Subir documento</button>' : ""}</div>
    <p class="muted">Carpeta de documentos recibidos del activo (facturas, tickets, cartas, notificaciones…), guardados cifrados. Cada activo ve solo los suyos.</p><div id="t"></div>`;
  const load = async () => {
    const docs = await get("/api/documentos-recibidos", { asset_id: S.asset, tipo: $("#tp", el).value, desde: $("#d", el).value, hasta: $("#h", el).value, q: $("#q", el).value, revision: $("#rv", el).value });
    table($("#t", el), [
      { k: "fecha", t: "Fecha", f: (v, x) => fdate(v) + (x.vencimiento ? `<div class="muted peq">vence ${fdate(x.vencimiento)}</div>` : "") }, { k: "activo", t: "Activo" }, { k: "tipo_nombre", t: "Tipo" }, { k: "emisor", t: "Emisor" },
      { k: "referencia", t: "Referencia" }, { k: "descripcion", t: "Descripción" }, { k: "unidad", t: "Apartamento" },
      { k: "gasto", t: "Gasto", f: (v) => (v ? `${eur(v.total)} <span class="muted">${esc(v.categoria_nombre)}${v.pagado ? " · pagado" : " · pendiente"}</span>` : '<span class="muted">—</span>') },
      { k: "usuario", t: "Subido por", f: (v, x) => `${esc(v || "")}<div class="muted peq">${fdt(x.subido)}</div>${x.de_colaborador ? `<span class="badge ${{ pendiente: "b-pendiente", aceptado: "b-vigente", rechazado: "b-anulado" }[x.revision]}">Colaborador · ${esc(x.revision)}</span>${x.revision_nota ? `<div class="muted peq">${esc(x.revision_nota)}</div>` : ""}` : ""}` },
    ], docs, (x) => [
      ["Ver", () => abrirFichero(`/api/documentos-recibidos/${x.id}/fichero`)],
      editar && x.revision === "pendiente" && ["Aceptar", () => run(() => post(`/api/documentos-recibidos/${x.id}/revisar`, { aceptar: true }), "Documento aceptado").then(load), "primary"],
      editar && x.revision === "pendiente" && ["Rechazar", () => form(`Rechazar · ${x.nombre}`, [{ k: "nota", t: "Motivo (lo verá el colaborador)", type: "textarea", req: true, wide: true }], {},
        async (d) => { await post(`/api/documentos-recibidos/${x.id}/revisar`, { aceptar: false, nota: d.nota }); toast("Documento rechazado"); load(); }, "Rechazar")],
      editar && !x.gasto && ["Anotar gasto", async () => {
        const [C2, unidades] = await Promise.all([catGastos(), unidadesActivo(x.asset_id)]);
        const f = form(`Gasto del documento · ${x.tipo_nombre} ${x.emisor || ""}`, [{ k: "fecha", t: "Fecha de la factura", type: "date", req: true }, { k: "vencimiento", t: "Vencimiento", type: "date" }, ...camposGasto(C2, unidades)],
          { fecha: x.fecha, vencimiento: x.vencimiento, concepto: x.descripcion || `${x.tipo_nombre} ${x.emisor || ""}`.trim(), unit_id: x.unit_id, ambito: x.unit_id ? "apartamento" : "general" },
          async (d) => { const body = datosGasto(d, { fecha: d.fecha, vencimiento: d.vencimiento, concepto: d.concepto, documento_id: x.id, proveedor: x.emisor, numero_factura: x.referencia });
            await conDuplicado((c) => post("/api/gastos", { ...body, confirmar_duplicado: c })); toast("Gasto anotado"); load(); });
        bindAmbito(f); bindRetencion(f);
      }],
      x.gasto && editar && ["Gasto", () => editarGasto(x.gasto, load)],
      editar && ["Borrar", async () => { if (confirm(`¿Borrar el documento «${x.nombre}»? El apunte del gasto, si lo tiene, se conserva.`)) { await run(() => api("DELETE", `/api/documentos-recibidos/${x.id}`), "Documento borrado"); load(); } }, "danger"],
    ]);
  };
  ["#tp", "#d", "#h", "#rv"].forEach((s) => ($(s, el).onchange = load)); $("#q", el).oninput = debounce(load);
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
      [eur(t.opex), "OPEX (base)"], [eur(t.capex), "CAPEX (base)"],
      ...(t.sin_naturaleza ? [[t.sin_naturaleza, "Sin OPEX/CAPEX indicado", "mal"]] : []),
      ...(t.retencion ? [[eur(t.retencion), "Retenciones IRPF practicadas"]] : []),
      ...(t.retenidas ? [[`${t.retenidas} · ${eur(t.retenidas_importe)}`, "Pagos retenidos (no pagar)", "mal"]] : []),
      ...Object.entries(t.por_categoria).slice(0, 4).map(([c, v]) => [eur(v), c])]
      .map(([v, l, cls]) => `<div class="kpi ${cls || ""}"><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join("");
    const FORMAS_GASTO = (await catGastos()).formas_pago;
    table($("#t", el), [
      { k: "fecha", t: "Fecha", f: fdate }, { k: "activo", t: "Activo" }, { k: "lugar", t: "Imputado a" }, { k: "categoria_nombre", t: "Categoría", f: (v, g) => `${esc(v)}<div class="muted peq">${g.naturaleza ? esc(g.naturaleza) : '<span class="badge b-cancelada">falta OPEX/CAPEX</span>'}</div>` },
      { k: "concepto", t: "Concepto" }, { k: "proveedor", t: "Proveedor", f: (v, g) => `${esc(v || "")}${g.numero_factura ? `<div class="muted peq">${esc(g.numero_factura)}</div>` : ""}` },
      { k: "base", t: "Base", num: true, f: eur }, { k: "cuota", t: "IVA", num: true, f: (v, g) => `${eur(v)}<div class="muted peq">${g.tipo_iva} %</div>` },
      { k: "liquido", t: "A pagar", num: true, f: (v, g) => `${eur(v)}${g.retencion ? `<div class="muted peq">ret. ${g.retencion_pct} %: ${eur(g.retencion)}</div>` : ""}` },
      { k: "pagado", t: "Pago", f: (v, g) => (g.pago_retenido && !v ? `<span class="badge b-cancelada" title="${esc(g.pago_retenido_motivo || "")}">RETENIDA</span><div class="muted peq">revisar ${fdate(g.pago_retenido_revision)}</div><div class="muted peq">${esc(g.pago_retenido_motivo || "")}</div>` : "") + (v ? `<span class="badge b-vigente">pagado</span><div class="muted peq">${fdate(g.fecha_pago)}</div>`
        : `<span class="badge ${g.vencimiento && g.vencimiento < today() ? "b-cancelada" : "b-pendiente"}">${g.vencimiento && g.vencimiento < today() ? "vencida" : "pendiente"}</span>${g.vencimiento ? `<div class="muted peq">vence ${fdate(g.vencimiento)}</div>` : ""}`)
        + (g.forma_pago ? `<div class="muted peq">${esc(FORMAS_GASTO[g.forma_pago] || g.forma_pago)}</div>` : '<div><span class="badge b-cancelada">falta forma de pago</span></div>') },
      { k: "documento_tipo", t: "Documento", f: (v) => (v ? esc(v) : '<span class="badge b-cancelada">sin documento</span>') },
    ], r.gastos, (g) => [
      g.documento_id && ["Ver", () => abrirFichero(`/api/documentos-recibidos/${g.documento_id}/fichero`)],
      g.justificante_id && ["Justificante", () => abrirFichero(`/api/documentos-recibidos/${g.justificante_id}/fichero`)],
      editar && !g.pagado && !g.pago_retenido && ["Pagado", () => pagarGasto(g, load)],
      editar && !g.pagado && ["Retener pago", () => form(g.pago_retenido ? "Cambiar la retención del pago" : "Retener el pago: no pagar de momento", [
        { html: '<p class="muted">Se avisa por correo a dirección y administración (quienes pagan). La factura sigue en el resumen diario hasta que se libere.</p>' },
        { k: "motivo", t: "Motivo", req: true, wide: true }, { k: "revision", t: "Fecha de revisión", type: "date", req: true }],
        { motivo: g.pago_retenido_motivo, revision: g.pago_retenido_revision },
        async (d) => { await post(`/api/gastos/${g.id}/retener-pago`, d); toast("Pago retenido: avisado a quien paga"); load(); }, "Retener pago")],
      g.pago_retenido && !g.pagado && ["Liberar pago", () => form("Liberar el pago (ya se puede pagar)", [{ k: "nota", t: "Nota (opcional)", wide: true }], {},
        async (d) => { await post(`/api/gastos/${g.id}/liberar-pago`, d); toast("Pago liberado"); load(); }, "Liberar")],
      editar && ["Editar", () => editarGasto(g, load)],
      editar && ["Borrar", async () => { if (confirm(`¿Borrar el gasto «${g.concepto}»?`)) { await run(() => api("DELETE", `/api/gastos/${g.id}`), "Gasto borrado"); load(); } }, "danger"],
    ]);
  };
  ["#d", "#h", "#c", "#p"].forEach((s) => ($(s, el).onchange = load));
  $("#xls", el).onclick = () => run(() => download("GET", `/api/gastos/excel?${new URLSearchParams(Object.entries(filtros()).filter(([k, v]) => v && k !== "pagado"))}`));
  if ($("#sin", el)) { $("#sin", el).onclick = () => editarGasto(null, load); $("#doc", el).onclick = () => subirDocumento(load); }
  load();
};

// ---- partes de estado (mantenimiento y limpieza revisan una vivienda o zona común; recepción genera la OT)
V.estado = async (el) => {
  const crea = canParteEstado(), gestiona = can("mantenimiento.abrir");
  const pestanas = [crea && ["nuevo", "➕ Nuevo parte"], ["lista", "📋 Partes"], gestiona && ["kpis", "📈 Panel técnico"]].filter(Boolean);
  const params = S.params || new URLSearchParams();
  let tab = params.get("ver") || (params.has("a") || params.has("u") ? "nuevo" : crea && !gestiona ? "nuevo" : "lista");
  if (!pestanas.some(([k]) => k === tab)) tab = pestanas[0][0];
  el.innerHTML = `<div class="toolbar"><div class="chips" style="margin:0">${pestanas.map(([k, t]) => `<button type="button" class="chip" data-tab="${k}">${t}</button>`).join("")}</div>
    <span class="spacer"></span>${gestiona ? '<button class="btn" id="qr">🔳 Códigos QR</button>' : ""}</div><div id="pe"></div>`;
  const cuerpo = $("#pe", el);
  const pinta = () => {
    el.querySelectorAll("[data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
    ({ nuevo: parteNuevo, lista: partesLista, kpis: partesKpis })[tab](cuerpo, params);
  };
  el.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => { tab = b.dataset.tab; params.delete("u"); params.delete("z"); pinta(); }));
  if ($("#qr", el)) $("#qr", el).onclick = async () => { const aid = S.asset || await pickAsset(); run(() => download("GET", `/api/partes-estado/qr.pdf?asset_id=${aid}`)); };
  pinta();
};

const GRAVEDAD_TXT = { leve: ["🟢", "Leve"], media: ["🟠", "Media"], critica: ["🔴", "Crítica"] };

// Alta en 4 pasos + foto: ubicación (QR o buscador) → estancia → elemento → deficiencia, gravedad y foto
async function parteNuevo(cuerpo, params) {
  const cat = S.catEstado || (S.catEstado = await get("/api/partes-estado/catalogo"));
  const activos = S.assets;
  let aid = Number(params.get("a")) || Number(S.asset) || (activos.length === 1 ? activos[0].id : null);
  const sel = {};
  let ubic = null, gps = null;
  if (navigator.geolocation) navigator.geolocation.getCurrentPosition((p) => { gps = p.coords; }, () => {}, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  const paso = (n, html) => `<div class="pe-pasos">${["Ubicación", "Estancia", "Elemento", "Deficiencia"].map((t, i) => `<span class="${i < n ? "hecho" : i === n ? "actual" : ""}">${i + 1}. ${t}</span>`).join("")}</div>
    ${sel.lugar ? `<p class="pe-ruta"><b>${esc(sel.lugar)}</b>${sel.estanciaNombre ? ` › ${esc(sel.estanciaNombre)}` : ""}${sel.elementoNombre ? ` › ${esc(sel.elementoNombre)}` : ""} <button type="button" class="btn sm" data-atras>← Atrás</button></p>` : ""}${html}`;
  const atras = () => { const b = cuerpo.querySelector("[data-atras]"); if (b) b.onclick = () => { if (sel.elemento) { delete sel.elemento; delete sel.elementoNombre; paso3(); } else if (sel.estancia) { delete sel.estancia; delete sel.estanciaNombre; paso2(); } else { Object.keys(sel).forEach((k) => delete sel[k]); paso1(); } }; };
  // 1. ubicación
  const paso1 = async () => {
    if (!aid) {
      cuerpo.innerHTML = paso(0, `<p>Elija el activo:</p><div class="pe-grid">${activos.map((a) => `<button type="button" class="pe-btn" data-a="${a.id}">${esc(a.nombre)}</button>`).join("")}</div>`);
      cuerpo.querySelectorAll("[data-a]").forEach((b) => (b.onclick = () => { aid = Number(b.dataset.a); paso1(); }));
      return;
    }
    ubic = await get("/api/partes-estado/ubicaciones", { asset_id: aid });
    const uq = Number(params.get("u")), zq = params.get("z");
    if (uq) { const u = ubic.unidades.find((x) => x.id === uq); params.delete("u"); if (u) return elegirUnidad(u); }
    if (zq !== null) { params.delete("z"); return elegirZona(zq); }
    cuerpo.innerHTML = paso(0, `<p class="muted">Escanee el código QR de la puerta o busque la unidad. Activo: <b>${esc(ubic.activo)}</b>${activos.length > 1 ? ' <button type="button" class="btn sm" data-cambia>Cambiar</button>' : ""}</p>
      <input type="search" class="pe-busca" placeholder="Nº de apartamento o vivienda (p. ej. 412)" data-busca autocomplete="off">
      <div class="pe-grid" data-res></div>
      <h4>Zonas comunes</h4><div class="pe-grid">${[{ zona: "", nombre: "Zonas comunes (general)" }, ...ubic.zonas].map((z) => `<button type="button" class="pe-btn zc" data-z="${esc(z.zona)}">${esc(z.nombre)}</button>`).join("")}</div>`);
    const res = cuerpo.querySelector("[data-res]");
    const busca = () => {
      const q = normaliza(cuerpo.querySelector("[data-busca]").value);
      const vis = q ? ubic.unidades.filter((u) => normaliza(u.codigo).includes(q)).slice(0, 24) : [];
      res.innerHTML = vis.map((u) => `<button type="button" class="pe-btn" data-u="${u.id}"><b>${esc(u.codigo)}</b><small>${esc(u.descripcion || "")}</small></button>`).join("") || (q ? '<p class="muted">Sin coincidencias.</p>' : "");
      res.querySelectorAll("[data-u]").forEach((b) => (b.onclick = () => elegirUnidad(ubic.unidades.find((u) => u.id === Number(b.dataset.u)))));
    };
    cuerpo.querySelector("[data-busca]").oninput = busca;
    cuerpo.querySelectorAll("[data-z]").forEach((b) => (b.onclick = () => elegirZona(b.dataset.z)));
    if (cuerpo.querySelector("[data-cambia]")) cuerpo.querySelector("[data-cambia]").onclick = () => { aid = null; paso1(); };
    cuerpo.querySelector("[data-busca]").focus();
  };
  const elegirUnidad = (u) => {
    Object.assign(sel, { unit_id: u.id, zona: null, lugar: `${u.codigo}${u.descripcion ? " · " + u.descripcion : ""}`, tipologia: u.tipologia });
    if (u.tipologia) return paso2();
    cuerpo.innerHTML = paso(0, `<p>¿Qué distribución tiene <b>${esc(u.codigo)}</b>?</p><div class="pe-grid">${["T0", "T1", "T2"].map((t) => `<button type="button" class="pe-btn" data-t="${t}">${esc(cat.tipologias[t])}</button>`).join("")}</div>`);
    cuerpo.querySelectorAll("[data-t]").forEach((b) => (b.onclick = () => { sel.tipologia = b.dataset.t; paso2(); }));
    atras();
  };
  const elegirZona = (z) => {
    const nombre = z ? ubic.zonas.find((x) => x.zona === z)?.nombre || z : "";
    Object.assign(sel, { unit_id: null, zona: z || null, tipologia: "ZC", lugar: `Zonas comunes${nombre ? " · " + nombre : ""}` });
    paso2();
  };
  // 2. estancia
  const paso2 = () => {
    cuerpo.innerHTML = paso(1, `<div class="pe-grid grande">${cat.estancias[sel.tipologia].map((e) => `<button type="button" class="pe-btn" data-e="${e.clave}">${esc(e.nombre)}</button>`).join("")}</div>`);
    cuerpo.querySelectorAll("[data-e]").forEach((b) => (b.onclick = () => { const e = cat.estancias[sel.tipologia].find((x) => x.clave === b.dataset.e); Object.assign(sel, { estancia: e.clave, estanciaNombre: e.nombre }); paso3(); }));
    atras();
  };
  // 3. familias (acordeón) y elemento
  const paso3 = () => {
    const e = cat.estancias[sel.tipologia].find((x) => x.clave === sel.estancia);
    cuerpo.innerHTML = paso(2, e.elementos.map((f, i) => `<details class="pe-familia"${i === 0 ? " open" : ""}><summary>${esc(f.nombre)}</summary>
      <div class="pe-grid">${f.elementos.map((x) => `<button type="button" class="pe-btn" data-el="${x.clave}">${esc(x.nombre)}</button>`).join("")}</div></details>`).join(""));
    cuerpo.querySelectorAll("details").forEach((d) => (d.ontoggle = () => { if (d.open) cuerpo.querySelectorAll("details").forEach((o) => o !== d && (o.open = false)); }));
    cuerpo.querySelectorAll("[data-el]").forEach((b) => (b.onclick = () => { Object.assign(sel, { elemento: b.dataset.el, elementoNombre: b.textContent }); paso4(); }));
    atras();
  };
  // 4. cierre rápido: deficiencia, gravedad, foto obligatoria, observaciones
  const paso4 = () => {
    cuerpo.innerHTML = paso(3, `<form class="pe-cierre" data-f>
      <label>Deficiencia<select name="deficiencia" required><option value="">Elija…</option>${cat.deficiencias.map((g) => `<optgroup label="${esc(g.nombre)}">${g.opciones.map((o) => `<option value="${o.clave}">${esc(o.nombre)}</option>`).join("")}</optgroup>`).join("")}</select></label>
      <div class="pe-gravedad" role="group" aria-label="Gravedad">${Object.entries(GRAVEDAD_TXT).map(([k, [ic, t]]) => `<button type="button" class="pe-grav g-${k}" data-g="${k}" title="${esc(cat.gravedades[k])}">${ic} ${t}</button>`).join("")}</div>
      <p class="muted peq" data-gtxt>Elija la gravedad.</p>
      <label class="btn pe-foto">📷 Hacer foto (obligatoria)<input type="file" accept="image/*" capture="environment" multiple name="fotos" hidden></label>
      <span class="muted" data-fmsg>Ninguna foto</span>
      <label>Observaciones (opcional)<textarea name="observaciones" rows="2" maxlength="2000"></textarea></label>
      <p class="error" data-err></p>
      <button type="submit" class="btn primary pe-enviar">Generar parte</button></form>`);
    const f = cuerpo.querySelector("[data-f]");
    let fotos = [];
    f.fotos.onchange = () => { fotos = [...fotos, ...f.fotos.files].slice(0, 6); cuerpo.querySelector("[data-fmsg]").textContent = fotos.length ? `${fotos.length} foto(s)` : "Ninguna foto"; };
    f.querySelectorAll("[data-g]").forEach((b) => (b.onclick = () => {
      sel.gravedad = b.dataset.g;
      f.querySelectorAll("[data-g]").forEach((x) => x.classList.toggle("on", x === b));
      cuerpo.querySelector("[data-gtxt]").textContent = cat.gravedades[sel.gravedad];
    }));
    f.onsubmit = async (ev) => {
      ev.preventDefault();
      const err = cuerpo.querySelector("[data-err]");
      if (!f.deficiencia.value) return (err.textContent = "Elija la deficiencia");
      if (!sel.gravedad) return (err.textContent = "Elija la gravedad");
      if (!fotos.length) return (err.textContent = "La foto es obligatoria");
      const fd = new FormData();
      Object.entries({ asset_id: aid, unit_id: sel.unit_id, zona: sel.zona, tipologia: sel.tipologia, estancia: sel.estancia, elemento: sel.elemento,
        deficiencia: f.deficiencia.value, gravedad: sel.gravedad, observaciones: f.observaciones.value.trim(),
        lat: gps?.latitude, lon: gps?.longitude, precision: gps?.accuracy }).forEach(([k, v]) => v != null && v !== "" && fd.append(k, v));
      for (const x of fotos) fd.append("fotos", await reducirFoto(x));
      const boton = f.querySelector(".pe-enviar"); boton.disabled = true; boton.textContent = "Enviando…";
      try { hecho(await upload("/api/partes-estado", fd)); } catch (e) { err.textContent = e.message; boton.disabled = false; boton.textContent = "Generar parte"; }
    };
    atras();
  };
  const hecho = (p) => {
    cuerpo.innerHTML = `<div class="pe-hecho"><h3>✔ Parte ${esc(p.codigo)} enviado a recepción</h3>
      <p><b>${esc(p.ubicacion)}</b> › ${esc(p.estancia_nombre)} › ${esc(p.elemento_nombre)}: ${esc(p.deficiencia_nombre)}</p>
      <p>${GRAVEDAD_TXT[p.gravedad].join(" ")} · ${esc(p.departamento_nombre)} · prioridad propuesta ${badge(p.prioridad)}</p>
      ${p.bloquea_unidad ? '<p class="error"><b>La unidad queda fuera de servicio</b> hasta que se cierre su orden de trabajo.</p>' : ""}
      ${(p.alertas || []).map((a) => `<p class="aviso-amarillo">${esc(a)}</p>`).join("")}
      <button type="button" class="btn primary" data-otro>Otro parte en ${esc(p.ubicacion)}</button> <button type="button" class="btn" data-nuevo>Otra ubicación</button></div>`;
    cuerpo.querySelector("[data-otro]").onclick = () => { delete sel.estancia; delete sel.estanciaNombre; delete sel.elemento; delete sel.elementoNombre; delete sel.gravedad; paso2(); };
    cuerpo.querySelector("[data-nuevo]").onclick = () => { Object.keys(sel).forEach((k) => delete sel[k]); paso1(); };
  };
  await paso1();
}

// Recepción: pendientes de decidir (generar OT o descartar) y abiertos hasta resolverse
async function partesLista(cuerpo) {
  cuerpo.innerHTML = `<div class="toolbar"><select data-estado><option value="abiertos">Sin resolver</option><option value="pendiente">Pendientes de recepción</option>
    <option value="ot_generada">Con orden de trabajo</option><option value="resuelto">Resueltos</option><option value="descartado">Descartados</option><option value="">Todos</option></select></div><div data-t></div>`;
  const load = async () => {
    const v = cuerpo.querySelector("[data-estado]").value;
    const filas = await get("/api/partes-estado", { asset_id: S.asset, ...(v === "abiertos" ? { abiertos: true } : { estado: v }) });
    table(cuerpo.querySelector("[data-t]"), [
      { k: "codigo", t: "Parte", f: (v, p) => `<b>${esc(v)}</b><br><span class="muted peq">${fdt(p.creado)}</span>` },
      { k: "ubicacion", t: "Ubicación", f: (v, p) => `${esc(v)}<br><span class="muted peq">${esc(p.estancia_nombre)}</span>` },
      { k: "elemento_nombre", t: "Elemento · deficiencia", f: (v, p) => `${esc(v)}: <b>${esc(p.deficiencia_nombre)}</b>${p.observaciones ? `<br><span class="muted peq">${esc(p.observaciones)}</span>` : ""}${(p.alertas || []).length ? `<br><span class="peq aviso">⚠ ${esc(p.alertas[0])}</span>` : ""}` },
      { k: "gravedad", t: "Gravedad", f: (v, p) => `${GRAVEDAD_TXT[v].join(" ")}${p.bloquea_unidad ? '<br><span class="badge b-urgente">fuera de servicio</span>' : ""}` },
      { k: "departamento_nombre", t: "Para", f: (v, p) => `${esc(v)}<br>${badge(p.prioridad)}` },
      { k: "estado_nombre", t: "Situación", f: (v, p) => `${esc(v)}${p.ot ? `<br>${otNum(p.ot.id)} ${badge(p.ot.estado)}` : ""}${p.motivo_descarte ? `<br><span class="muted peq">${esc(p.motivo_descarte)}</span>` : ""}` },
      { k: "usuario", t: "Registró" },
    ], filas, (p) => [
      ["Fotos", () => p.fotos.forEach((f) => abrirFichero(`/api/partes-estado/fotos/${f.id}`))],
      p.lat != null && ["GPS", () => window.open(`https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lon}#map=19/${p.lat}/${p.lon}`, "_blank")],
      p.puede_gestionar && p.estado === "pendiente" && ["Generar OT", () => newWorkOrder(p.asset_id, p.unit_id, p.zona ? { zona: p.zona, nombre: p.ubicacion } : null, p).then(load), "primary"],
      p.puede_gestionar && p.estado === "pendiente" && ["Descartar", () => form(`Descartar ${p.codigo}`, [{ k: "motivo", t: "Motivo", req: true, wide: true }], {},
        async (d) => { await post(`/api/partes-estado/${p.id}/descartar`, d); toast("Parte descartado"); load(); }, "Descartar")],
    ]);
  };
  cuerpo.querySelector("[data-estado]").onchange = load;
  load();
}

// Panel técnico de la dirección: Pareto de fallos, tiempo medio de reparación e intervenciones por unidad y mes
async function partesKpis(cuerpo) {
  const hoyIso = today(), haceAnio = iso(new Date(Date.now() - 365 * 864e5));
  cuerpo.innerHTML = `<div class="toolbar"><label>Desde <input type="date" data-d value="${haceAnio}"></label><label>Hasta <input type="date" data-h value="${hoyIso}"></label></div><div data-k></div>`;
  const horas = (m) => (m.horas == null ? "—" : m.horas < 48 ? `${m.horas} h` : `${(m.horas / 24).toFixed(1)} días`);
  const load = async () => {
    const k = await get("/api/partes-estado/kpis", { asset_id: S.asset, desde: cuerpo.querySelector("[data-d]").value, hasta: cuerpo.querySelector("[data-h]").value });
    const tarj = [[k.total, "Partes (sin descartados)"], [horas(k.mttr.global), `Tiempo medio de reparación (${k.mttr.global.resueltos} resueltos)`],
      [horas(k.mttr.mantenimiento), "MTTR mantenimiento"], [horas(k.mttr.limpieza), "MTTR limpieza"], [horas(k.mttr.critica), "MTTR críticos"],
      [k.por_estado.pendiente + k.por_estado.ot_generada, "Sin resolver"]];
    cuerpo.querySelector("[data-k]").innerHTML = `<div class="cards">${tarj.map(([v, t]) => `<div class="card kpi"><b>${esc(String(v))}</b><span>${esc(t)}</span></div>`).join("")}</div>
      <h3>Frecuencia de fallos por elemento (Pareto)</h3>
      ${k.pareto.length ? `<div class="table-wrap"><table><thead><tr><th>Elemento</th><th>Familia</th><th class="num">Partes</th><th>%</th><th class="num">Acumulado</th></tr></thead><tbody>
        ${k.pareto.map((r) => `<tr${r.acumulado - r.pct < 80 ? ' class="pareto-a"' : ""}><td>${esc(r.elemento)}</td><td>${esc(r.familia)}</td><td class="num">${r.partes}</td>
          <td><div class="barra"><span style="width:${r.pct}%"></span></div> ${r.pct} %</td><td class="num">${r.acumulado} %</td></tr>`).join("")}</tbody></table></div>
        <p class="muted peq">En negrita, los elementos que suman el 80 % de los fallos: ahí está la mayor parte del coste.</p>` : '<p class="muted">Sin partes en el periodo.</p>'}
      <h3>Intervenciones técnicas por unidad y mes</h3>
      ${k.intervenciones.filas.length ? `<div class="table-wrap"><table><thead><tr><th>Ubicación</th>${k.intervenciones.meses.map((m) => `<th class="num">${m.slice(5)}/${m.slice(2, 4)}</th>`).join("")}<th class="num">Total</th></tr></thead><tbody>
        ${k.intervenciones.filas.map((f) => `<tr><td>${esc(f.ubicacion)}</td>${f.meses.map((n) => `<td class="num">${n || ""}</td>`).join("")}<td class="num"><b>${f.total}</b></td></tr>`).join("")}</tbody></table></div>` : '<p class="muted">Sin intervenciones técnicas en el periodo.</p>'}
      <h3>Por familia y deficiencia</h3><p>${k.familias.map(([n, c]) => `${esc(n)}: <b>${c}</b>`).join(" · ") || "—"}</p><p>${k.deficiencias.map(([n, c]) => `${esc(n)}: <b>${c}</b>`).join(" · ") || "—"}</p>`;
  };
  cuerpo.querySelectorAll("input").forEach((i) => (i.onchange = load));
  load();
}

// ---- administración
V.usuarios = async (el) => {
  const [users, roles, provs] = await Promise.all([get("/api/admin/usuarios"), get("/api/admin/roles"), get("/api/proveedores").catch(() => [])]);
  const provNombre = Object.fromEntries(provs.map((p) => [p.id, p.nombre]));
  el.innerHTML = `<div class="toolbar"><span class="spacer"></span><button class="btn primary" id="new">Nuevo usuario</button></div><div id="bloq"></div><div id="t"></div>`;
  bloqueosAcceso($("#bloq", el));
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
      { k: "no_asignable", t: "Presidencia: los demás no pueden enviarle tareas, recordatorios ni convocatorias", type: "checkbox" },
      { k: "supplier_id", t: "Colaborador externo de (subcontrata): solo verá su portal", type: "select", wide: true, options: provs.map((p) => [p.id, p.nombre]) },
      { html: '<p class="muted peq">Para un colaborador: elija su empresa y dele el rol <b>Colaborador</b> en los activos donde trabaja. No podrá entrar en ninguna otra pantalla.</p>' },
      { html: `<fieldset><legend>Roles y ámbito de acceso (rol · sociedad · activo)</legend><div id="asg">${(u?.asignaciones || []).map(assignRow).join("")}</div>
        <button type="button" class="btn sm" id="addA">+ Añadir rol</button></fieldset>` },
    ], u || {}, async (d) => {
      const asignaciones = [...f.querySelectorAll(".assign-row")].map((row) => {
        const v = (k) => row.querySelector(`[data-f=${k}]`).value;
        return { role_id: Number(v("role_id")), company_id: v("company_id") ? Number(v("company_id")) : null, asset_id: v("asset_id") ? Number(v("asset_id")) : null };
      });
      const body = { ...d, asignaciones, supplier_id: d.supplier_id ? Number(d.supplier_id) : (u ? 0 : null) }; if (!body.password) delete body.password;
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
    { k: "asignaciones", t: "Roles / ámbito", f: (v, u) => (u.supplier_id ? `<span class="badge b-asignada">Colaborador · ${esc(provNombre[u.supplier_id] || "")}</span><br>` : "") + (u.is_superadmin ? "<b>Superadministrador</b>" : v.map((a) => `${esc(a.rol)} <span class="muted">(${esc(scopeTxt(a))})</span>`).join("<br>") || '<span class="muted">Sin acceso</span>') },
    { k: "activo", t: "Estado", f: (v, u) => (v ? badge("vigente") : badge("baja")) + (u.debe_cambiar_password ? ' <span class="badge b-pendiente">contraseña provisional</span>' : "") },
  ], users, (u) => [["Editar", () => edit(u)], S.me.borrar_usuarios && u.id !== S.me.id && ["Borrar", () => borrarUsuario(u), "danger"]]);
};
// Usuarios y conexiones bloqueados por intentos fallidos (se desbloquean solos a los 15 minutos)
async function bloqueosAcceso(box) {
  const b = await get("/api/admin/seguridad").catch(() => []);
  if (!b.length) { box.innerHTML = ""; return; }
  box.innerHTML = `<div class="card aviso-bloqueo"><h3>Accesos bloqueados por intentos fallidos</h3>
    <p class="muted peq">Se desbloquean solos a la hora indicada. Desbloquee solo si sabe quién es (por ejemplo, alguien del equipo que se equivocó de contraseña).</p>
    <div class="table-wrap"><table><thead><tr><th>Qué</th><th>Usuario o conexión</th><th class="num">Intentos</th><th>Último intento</th><th>Hasta</th><th class="acc"></th></tr></thead><tbody>
    ${b.map((x, i) => `<tr><td>${esc(x.nombre)}</td><td>${esc(x.clave)}</td><td class="num">${x.intentos}</td><td class="peq">${esc(x.ultimo || "")}</td><td>${hhmm(x.hasta)}</td>
      <td class="acc"><button type="button" class="btn sm" data-u="${i}">Desbloquear</button></td></tr>`).join("")}</tbody></table></div></div>`;
  box.querySelectorAll("[data-u]").forEach((btn) => (btn.onclick = async () => {
    const x = b[btn.dataset.u];
    if (!confirm(`¿Desbloquear ${x.clave}?`)) return;
    await run(() => post("/api/admin/seguridad/desbloquear", { tipo: x.tipo, clave: x.clave }), "Desbloqueado");
    bloqueosAcceso(box);
  }));
}
async function borrarUsuario(u) {
  if (!confirm(`¿Borrar el usuario ${u.nombre} (${u.email})?\n\nDejará de poder entrar. Si ya ha trabajado en el PMS, su nombre se conserva solo en el historial (partes, gastos, auditoría).`)) return;
  try {
    const r = await api("DELETE", `/api/admin/usuarios/${u.id}`);
    toast(r.historial ? "Usuario borrado (su nombre se conserva en el historial)" : "Usuario borrado"); go("usuarios");
  } catch (e) { alert(e.message); }
}

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

const CONTRATO_SOC = [["rm_tomo", "Registro Mercantil: tomo"], ["rm_folio", "Folio"], ["rm_hoja", "Hoja"],
  ["representante", "Representante (nombre y apellidos)"], ["representante_dni", "DNI del representante"], ["representante_cargo", "Cargo (administrador, apoderado…)"],
  ["representante_poder", "Escritura de poder (fecha, notario y nº de protocolo)", true], ["iban", "IBAN para el cobro de la renta", true],
  ["email_notificaciones", "Correo de notificaciones y averías"], ["email_rgpd", "Correo de protección de datos"], ["telefono_averias", "Teléfono de averías"]];
V.sociedades = async (el) => {
  el.innerHTML = `<div class="toolbar"><span class="spacer"></span><button class="btn primary" id="new">Nueva sociedad</button></div><div id="t"></div>`;
  const fields = [{ k: "nombre", t: "Razón social", req: true }, { k: "cif", t: "CIF" },
    { k: "parent_id", t: "Sociedad matriz", type: "select", options: opts(S.companies) }, { k: "activa", t: "Activa", type: "checkbox", def: true },
    { html: "<h4>Domicilio fiscal</h4><p class='muted'>Obligatorio para emitir facturas. Se imprime en todas las facturas de la sociedad.</p>" },
    { k: "direccion", t: "Dirección", wide: true }, { k: "cp", t: "Código postal" }, { k: "municipio", t: "Población" }, { k: "provincia", t: "Provincia" }, { k: "pais", t: "País", def: "España" },
    { html: "<h4>Datos para contratos de alquiler de vivienda</h4><p class='muted'>Se imprimen en el contrato (comparecencia, cláusulas 4, 21 y 23 y anexo de averías).</p>" },
    ...CONTRATO_SOC.map(([k, t, wide]) => ({ k: `ct_${k}`, t, wide }))];
  const save = (c) => form(c ? c.nombre : "Nueva sociedad", fields, c ? { ...c, ...Object.fromEntries(Object.entries(c.contratos || {}).map(([k, v]) => [`ct_${k}`, v])) } : {}, async (d) => {
    d.parent_id = d.parent_id ? Number(d.parent_id) : null;
    d.contratos = {};
    CONTRATO_SOC.forEach(([k]) => { if (d[`ct_${k}`]) d.contratos[k] = d[`ct_${k}`]; delete d[`ct_${k}`]; });
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
    async (d) => { const r = await post("/api/auth/password", d); nuevoToken(r); toast("Contraseña cambiada"); });
};

// ------------------------------------------------------------------ informe mensual a la presidencia
const pctTxt = (x, signo) => (x == null ? "—" : `${signo && x > 0 ? "+" : ""}${x.toFixed(1).replace(".", ",")} %`);
const numTxt = (x) => (x == null ? "—" : Number(x).toLocaleString("es-ES"));
V.presidencia = async (el) => {
  const hoy = new Date(), prev = new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1);
  const ym = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  const ini = S.presidencia || {};
  const aid = String(ini.asset || S.asset || S.assets[0]?.id || "");
  el.innerHTML = `<div class="toolbar"><select id="pa">${S.assets.map((a) => `<option value="${a.id}" ${String(a.id) === aid ? "selected" : ""}>${esc(a.nombre)}</option>`).join("")}</select>
    <label>Mes<input type="month" id="pm" value="${ini.mes || ym(prev)}" max="${ym(hoy)}"></label>
    <button class="btn" id="ppdf">Descargar PDF</button><button class="btn" id="pxls">Descargar Excel</button><span class="spacer"></span>
    <label class="check" id="prevLbl"><input type="checkbox" id="prev"> He revisado el informe y todos los datos son correctos</label>
    <button class="btn primary" id="pmail" disabled>Enviar por correo</button><button class="btn primary" id="pwa" disabled>Enviar por WhatsApp</button></div>
    <div id="pest" class="muted"></div><div id="pinf" class="informe-pres"><p class="muted">Cargando…</p></div>`;
  const q = () => { const [anio, mes] = $("#pm", el).value.split("-").map(Number); return { asset_id: $("#pa", el).value, anio, mes }; };
  let j = null;
  const tablaAnual = (r) => `<table class="tabla-inf"><thead><tr><th>Mes</th><th class="num">Producción</th><th class="num">Pernoct.</th><th class="num">Ocupación</th>
      <th class="num" title="Producción: variación respecto al mes anterior">Δ prod. mes</th><th class="num" title="Pernoctaciones: variación respecto al mes anterior">Δ pern. mes</th><th class="num" title="Producción: variación respecto al mismo mes del año anterior">Δ prod. año</th><th class="num" title="Pernoctaciones: variación respecto al mismo mes del año anterior">Δ pern. año</th></tr></thead><tbody>
    ${r.meses.map((m) => `<tr><td>${esc(m.nombre)}</td><td class="num">${eur(m.produccion)}</td><td class="num">${numTxt(m.pernoctaciones)}</td><td class="num">${pctTxt(m.ocupacion)}</td>
      ${["var_mes_produccion", "var_mes_pernoctaciones", "var_anio_produccion", "var_anio_pernoctaciones"].map((k) => `<td class="num ${m[k] == null ? "" : m[k] >= 0 ? "sube" : "baja"}">${pctTxt(m[k], true)}</td>`).join("")}</tr>`).join("")}
    <tr class="tot"><td>Total</td><td class="num">${eur(r.total_produccion)}</td><td class="num">${numTxt(r.total_pernoctaciones)}</td><td colspan="5"></td></tr></tbody></table>`;
  const pinta = () => {
    const d = j.datos, r = j.registro;
    $("#pest", el).innerHTML = r && r.enviado_en
      ? `✅ Enviado el ${fdate(r.enviado_en.slice(0, 10))} ${r.enviado_en.slice(11, 16)} por ${esc(r.enviado_por_nombre || "")} · ${r.canal === "email" ? "correo" : "WhatsApp"} a ${esc(r.destino || "")}. El Excel está en Documentos recibidos (tipo «Informe mensual»). Puede volver a enviarlo.`
      : `Pendiente de revisar y enviar${j.responsable ? ` · lo envía ${esc(j.responsable)}` : ""}.`;
    $("#pinf", el).innerHTML = `<div class="inf-cols"><section class="card"><h3>Producción · ${esc(d.periodo)}</h3>
      <table class="tabla-inf"><thead><tr><th>Ingresos por alquileres</th><th class="num">Contratos</th><th class="num">Pernoct.</th><th class="num">Importe</th></tr></thead><tbody>
        ${d.alquileres.map((f) => `<tr><td>${esc(f.concepto)}</td><td class="num">${numTxt(f.contratos)}</td><td class="num">${numTxt(f.pernoctaciones)}</td><td class="num">${eur(f.importe)}</td></tr>`).join("")}
        <tr class="tot"><td>Total alquileres</td><td></td><td class="num">${numTxt(d.total_pernoctaciones)}</td><td class="num">${eur(d.total_alquileres)}</td></tr></tbody></table>
      <table class="tabla-inf"><thead><tr><th>Ingresos por servicios</th><th class="num">Importe</th></tr></thead><tbody>
        ${d.servicios.map((x) => `<tr><td>${esc(x.concepto)}</td><td class="num">${eur(x.importe)}</td></tr>`).join("") || '<tr><td class="muted">Sin servicios facturados</td><td></td></tr>'}
        <tr class="tot"><td>Total servicios</td><td class="num">${eur(d.total_servicios)}</td></tr>
        <tr class="tot grande"><td>TOTAL PRODUCCIÓN · ${esc(d.periodo.toUpperCase())}</td><td class="num">${eur(d.total_ingresos)}</td></tr></tbody></table>
      <table class="tabla-inf"><thead><tr><th>Gastos: proveedor</th><th>Nº de factura</th><th class="num">Importe sin IVA</th><th>CAPEX / OPEX</th></tr></thead><tbody>
        ${d.gastos.map((g) => `<tr><td>${esc(g.proveedor || "")}</td><td>${esc(g.facturas.join(", "))}</td><td class="num">${eur(g.importe)}</td><td>${esc(g.naturaleza)}</td></tr>`).join("") || '<tr><td class="muted" colspan="4">Sin gastos registrados en el mes</td></tr>'}
        <tr class="tot"><td>Total gastos</td><td></td><td class="num">${eur(d.total_gastos)}</td><td></td></tr></tbody></table>
      <table class="tabla-inf"><tbody><tr><td>Total producción (ingresos)</td><td class="num">${eur(d.total_ingresos)}</td></tr><tr><td>Total gastos</td><td class="num">${eur(-d.total_gastos)}</td></tr>
        <tr class="tot grande"><td>RESULTADO DE PRODUCCIÓN</td><td class="num">${eur(d.resultado)}</td></tr>
        <tr class="sem sem-${d.semaforo}"><td>Porcentaje de resultado sobre la producción</td><td class="num">${pctTxt(d.porcentaje)}</td></tr></tbody></table>
      <p class="muted peq">Sin IVA. Semáforo: rojo de 0 % a 12 % · naranja de 13 % a 25 % · verde de 26 % en adelante.</p></section>
      <section class="card"><div class="toolbar" style="margin:0 0 8px"><h3 style="margin:0">Resumen mensual</h3><span class="spacer"></span>
        <span class="chips" style="margin:0"><button class="chip" data-anio="anterior">${d.anterior.anio}</button><button class="chip on" data-anio="actual">${d.actual.anio}</button></span></div>
        <div id="anual">${tablaAnual(d.actual)}</div>
        <p class="muted peq">Producción: facturado sin IVA. Pernoctaciones y ocupación: noches en ${d.actual.apartamentos} apartamentos (sin garajes). «—»: sin datos.</p></section></div>`;
    el.querySelectorAll("[data-anio]").forEach((b) => (b.onclick = () => {
      el.querySelectorAll("[data-anio]").forEach((x) => x.classList.toggle("on", x === b)); $("#anual", el).innerHTML = tablaAnual(d[b.dataset.anio]);
    }));
  };
  const load = async () => {
    S.presidencia = { asset: $("#pa", el).value, mes: $("#pm", el).value };
    $("#prev", el).checked = false; $("#pmail", el).disabled = $("#pwa", el).disabled = true;
    try { j = await get("/api/presidencia", q()); pinta(); } catch (e) { $("#pinf", el).innerHTML = `<p class="error">${esc(e.message)}</p>`; }
  };
  $("#pa", el).onchange = load; $("#pm", el).onchange = load;
  $("#prev", el).onchange = () => { $("#pmail", el).disabled = $("#pwa", el).disabled = !$("#prev", el).checked; };
  const qs = () => new URLSearchParams(q()).toString();
  $("#ppdf", el).onclick = () => run(() => download("GET", `/api/presidencia/pdf?${qs()}`));
  $("#pxls", el).onclick = () => run(() => download("GET", `/api/presidencia/excel?${qs()}`));
  $("#pmail", el).onclick = () => form("Enviar el informe por correo (PDF)", [
    { html: `<p class="muted">Se envía en PDF y el Excel queda guardado en los documentos del activo.</p>` },
    { k: "destinatarios", t: "Correos (separados por comas)", wide: true, req: true }], { destinatarios: (j.destinatarios || []).join(", ") },
    async (d) => { await post("/api/presidencia/enviar", { ...q(), revisado: true, canal: "email", destinatarios: d.destinatarios.split(/[,;\s]+/).filter(Boolean) }); toast("Informe enviado por correo"); load(); }, "Enviar");
  $("#pwa", el).onclick = () => form("Enviar el informe por WhatsApp (PDF)", [
    { html: `<p class="muted">Se abre WhatsApp con el mensaje; en el móvil se adjunta el PDF directamente, en el ordenador se descarga para adjuntarlo. El Excel queda guardado en los documentos del activo.</p>` },
    { k: "telefono", t: "Teléfono de WhatsApp", req: true }], { telefono: j.whatsapp || "" },
    async (d) => {
      const w = window.open("about:blank", "_blank");
      const r = await post("/api/presidencia/enviar", { ...q(), revisado: true, canal: "whatsapp", telefono: d.telefono });
      const res = await fetch(`/api/presidencia/pdf?${qs()}`, { headers: { Authorization: `Bearer ${S.token}` } });
      const fichero = new File([await res.blob()], r.pdf, { type: "application/pdf" });
      if (navigator.canShare && navigator.canShare({ files: [fichero] })) {
        if (w) w.close();
        await navigator.share({ files: [fichero], text: decodeURIComponent(r.whatsapp_url.split("text=")[1] || "") }).catch(() => {});
      } else {
        const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(fichero), download: r.pdf });
        document.body.appendChild(a); a.click(); a.remove();
        if (w) w.location = r.whatsapp_url; else window.open(r.whatsapp_url, "_blank");
      }
      toast("Informe preparado para WhatsApp: adjunte el PDF descargado"); load();
    }, "Abrir WhatsApp");
  load();
};

// ------------------------------------------------------------------ manual de uso
// Markdown sencillo (títulos, listas, negrita, cursiva, citas) del manual a HTML. El texto viene del programa.
function mdHtml(md) {
  const enLinea = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|[^\w*])\*(?!\s)(.+?)\*(?![\w*])/g, "$1<i>$2</i>").replace(/`(.+?)`/g, "<code>$1</code>");
  let out = "", lista = null;
  const cierra = () => { if (lista) { out += `</${lista}>`; lista = null; } };
  for (const ln of md.split("\n")) {
    let m;
    if (!ln.trim()) { cierra(); continue; }
    if ((m = ln.match(/^(#{1,3}) (.+)/))) { cierra(); const n = m[1].length + 1; out += `<h${n}>${enLinea(m[2])}</h${n}>`; }
    else if ((m = ln.match(/^(\s*)([-*]|\d+\.) (.+)/))) {
      const num = /\d/.test(m[2]), tipo = num ? "ol" : "ul";
      // sub-viñeta: dentro de la lista en curso, sin cortar la numeración
      if (m[1] && lista) { out += `<li class="sub">${enLinea(m[3])}</li>`; continue; }
      if (lista !== tipo) { cierra(); out += `<${tipo}>`; lista = tipo; }
      out += `<li${num ? ` value="${parseInt(m[2])}"` : ""}>${enLinea(m[3])}</li>`;
    }
    else if (ln.startsWith("> ")) { cierra(); out += `<blockquote>${enLinea(ln.slice(2))}</blockquote>`; }
    else { cierra(); out += `<p>${enLinea(ln)}</p>`; }
  }
  cierra(); return out;
}
V.manual = async (el) => {
  const idx = await get("/api/manual");
  let sec = idx.recomendada;
  try { localStorage.setItem("pms_manual_visto", idx.version); } catch {}
  el.innerHTML = `<div class="toolbar"><div class="chips">${idx.secciones.map((s) => `<button class="chip" data-s="${s.id}">${esc(s.titulo)}</button>`).join("")}</div>
    <span class="spacer"></span><button class="btn" id="mPdf">Descargar PDF para enviar</button></div>
    <p class="muted">Versión: ${esc(idx.version)}. Recomendado para su puesto: <b>${esc(idx.secciones.find((s) => s.id === idx.recomendada).titulo)}</b>.</p>
    <article class="manual card" id="mTxt"></article>`;
  const pinta = async () => {
    el.querySelectorAll("[data-s]").forEach((b) => b.classList.toggle("on", b.dataset.s === sec));
    $("#mTxt", el).innerHTML = mdHtml((await get(`/api/manual/${sec}`)).texto);
  };
  el.querySelectorAll("[data-s]").forEach((b) => b.onclick = () => { sec = b.dataset.s; pinta(); });
  $("#mPdf", el).onclick = async () => { try { await download("GET", `/api/manual/${sec}/pdf`); } catch (e) { toast(e.message, true); } };
  await pinta();
};
// Tras una actualización, la primera vez que entra cada usuario: aviso con las novedades.
async function avisoNovedades() {
  let visto = null;
  try { visto = localStorage.getItem("pms_manual_visto"); } catch { return; }
  const idx = await get("/api/manual").catch(() => null);
  if (!idx || !idx.version || visto === idx.version) return;
  try { localStorage.setItem("pms_manual_visto", idx.version); } catch {}
  if (visto === null) return;  // primer uso en este navegador: no hay «novedades» que contar
  const md = (await get("/api/manual/novedades")).texto;
  const ultima = md.split(/\n(?=## )/)[1] || "";
  cerrarSolo(form("Novedades de esta actualización", [{ html: `<div class="manual">${mdHtml(ultima)}</div><p class="muted">Tiene el detalle en <b>Manual de uso</b>.</p>` }], {}, async () => {}));
}

// ------------------------------------------------------------------ pedidos de material (Mantenimiento → Pedidos)
// Catálogo de productos (compartido con INVERGESTION) y pedidos por activo. Los hace cualquiera con permiso; los
// de recepción 2, mantenimiento o limpieza los autoriza Recepción 1. Autorizados, se envían al proveedor en PDF.
const ESTADOS_PEDIDO = { pendiente: "Pendiente de autorizar", autorizado: "Autorizado", enviado: "Enviado", recibido: "Recibido", rechazado: "Rechazado", anulado: "Anulado" };
const verPedidos = () => can("pedidos.crear") || can("pedidos.autorizar");
const num = (v) => (v == null || v === "" ? null : Number(String(v).replace(",", ".")));
let FAMILIAS = null;
const familias = async () => (FAMILIAS ||= await get("/api/productos/familias"));
const prodTxt = (p) => `<b>${esc(p.referencia)}</b> · ${esc(p.articulo)}${p.marca ? ` · ${esc(p.marca)}` : ""}${p.proveedor ? ` <span class="muted">· ${esc(p.proveedor)}</span>` : ""} · ${p.precio != null ? eur(p.precio) + "/" + esc(p.unidad) + " s/IVA" : '<span class="muted">sin precio</span>'}`;
const camposProducto = async (conActivo) => [
  { k: "articulo", t: "Artículo (descripción)", req: true, wide: true },
  { k: "referencia", t: "Referencia (en blanco: automática PMS-…)" },
  { k: "familia", t: "Familia", type: "select", req: true, options: (await familias()).map((f) => [f, f]), def: "OTROS" },
  { k: "unidad", t: "Unidad (ud, m, kg, caja…)", def: "ud" },
  { k: "precio", t: "Precio unitario € sin IVA", type: "number", step: "0.0001" },
  { k: "tipo_iva", t: "IVA %", type: "select", options: [["21", "21 %"], ["10", "10 %"], ["4", "4 %"], ["0", "0 %"]], def: "21" },
  { k: "marca", t: "Marca" }, { k: "ref_proveedor", t: "Referencia del proveedor" }, { k: "proveedor", t: "Proveedor habitual" },
  ...(conActivo ? [{ k: "asset_id", t: "Activo que lo da de alta", type: "select", req: true, options: opts(S.assets), def: S.asset }] : []),
];
const productoDatos = (d) => clean({ ...d, precio: num(d.precio), tipo_iva: num(d.tipo_iva) ?? 21, asset_id: d.asset_id ? Number(d.asset_id) : undefined });

V.pedidos = async (el) => {
  el.innerHTML = `<div class="toolbar"><select id="e"><option value="">Todos los estados</option>${Object.entries(ESTADOS_PEDIDO).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select>
    <span class="spacer"></span><button class="btn" id="cat">Catálogo de productos</button><button class="btn primary" id="new">Nuevo pedido</button></div><div id="pend"></div><div id="t"></div>`;
  const load = async () => {
    const rows = await get("/api/pedidos", { asset_id: S.asset, estado: $("#e", el).value });
    const mios = rows.filter((p) => p.puede_autorizar);
    $("#pend", el).innerHTML = mios.length ? `<div class="aviso-vencidas"><b>${mios.length} pedido(s) pendiente(s) de su autorización.</b> Ábralos para revisarlos y autorizarlos.</div>` : "";
    table($("#t", el), [
      { k: "numero", t: "Pedido", f: (v) => `<b>${esc(v)}</b>` }, { k: "fecha", t: "Fecha", f: fdate }, { k: "activo", t: "Activo" },
      { k: "proveedor_nombre", t: "Proveedor", f: (v) => esc(v || "—") }, { k: "n_lineas", t: "Líneas", num: true },
      { k: "total", t: "Total estimado", num: true, f: (v, p) => eur(v) + (p.sin_precio ? ` <span class="muted">(${p.sin_precio} sin precio)</span>` : "") },
      { k: "estado", t: "Estado", f: (v) => `<span class="badge b-${v === "pendiente" ? "pendiente" : v === "rechazado" || v === "anulado" ? "cancelada" : "vigente"}">${esc(ESTADOS_PEDIDO[v] || v)}</span>` },
      { k: "creado_por", t: "Hecho por", f: (v) => esc(v || "") },
    ], rows, (p) => [["Abrir", () => fichaPedido(p.id, load), "primary"], p.puede_autorizar && ["Autorizar", () => run(() => post(`/api/pedidos/${p.id}/autorizar`), "Pedido autorizado").then(load)],
      ["PDF", () => run(() => download("GET", `/api/pedidos/${p.id}/pdf`))]]);
  };
  $("#e", el).onchange = load;
  $("#new", el).onclick = () => formPedido(null, load);
  $("#cat", el).onclick = () => { location.hash = "#productos"; };
  load();
};

async function formPedido(p, reload) {
  const activos = S.assets;
  const lineas = (p?.lineas || []).map((x) => ({ product_id: x.product_id, producto: x.producto, cantidad: x.cantidad, precio: x.precio, nota: x.nota }));
  const f = form(p ? `Pedido ${p.numero}` : "Nuevo pedido de material", [
    { k: "asset_id", t: "Activo", type: "select", req: true, options: opts(activos), def: p?.asset_id ?? S.asset },
    { k: "proveedor", t: "Proveedor (escriba para buscar en Proveedores)" },
    { k: "fecha_entrega", t: "Entrega deseada", type: "date" },
    { k: "notas", t: "Observaciones para el proveedor", type: "textarea", wide: true },
    { html: `<fieldset class="ped-lineas"><legend>Productos</legend>
      <div class="ped-busca"><input type="search" data-pbusca placeholder="Escriba referencia, artículo, marca o proveedor…" autocomplete="off"><div data-psug class="cli-res"></div></div>
      <div class="toolbar"><button type="button" class="btn sm" data-pnuevo>＋ Producto nuevo (no está en el catálogo)</button></div>
      <div data-plineas></div><p data-ptot class="ped-tot"></p></fieldset>`, wide: true },
  ], { proveedor: p?.proveedor_nombre || "", fecha_entrega: p?.fecha_entrega, notas: p?.notas }, async (d) => {
    if (!lineas.length) throw new Error("Añada al menos un producto");
    const sup = provs.find((s) => s.nombre.toLowerCase() === String(d.proveedor || "").trim().toLowerCase());
    const body = { asset_id: Number(d.asset_id), supplier_id: sup?.id ?? null, proveedor: d.proveedor || null, fecha_entrega: d.fecha_entrega || null, notas: d.notas || null,
      lineas: lineas.map((x) => clean({ product_id: x.product_id, nuevo: x.nuevo, cantidad: num(x.cantidad), precio: num(x.precio), nota: x.nota })) };
    const r = p ? await put(`/api/pedidos/${p.id}`, body) : await post("/api/pedidos", body);
    toast(`Pedido ${r.numero}: ${ESTADOS_PEDIDO[r.estado]}${r.estado === "pendiente" ? (r.r1 ? ` (lo autoriza ${r.r1})` : " (lo autoriza Recepción 1)") : ""}`);
    reload && reload();
    setTimeout(() => fichaPedido(r.id, reload), 0);
  }, p ? "Guardar cambios" : "Hacer pedido");
  $("#modal").classList.add("ancho");
  let provs = [];
  const inProv = f.elements.proveedor;
  inProv.setAttribute("list", "provlista");
  inProv.insertAdjacentHTML("afterend", '<datalist id="provlista"></datalist>');
  const cargaProvs = async () => { provs = await get("/api/proveedores-pedido", { q: inProv.value }).catch(() => []); $("#provlista", f).innerHTML = provs.map((s) => `<option value="${esc(s.nombre)}">${esc(s.nif || "")}</option>`).join(""); };
  inProv.oninput = debounce(cargaProvs); cargaProvs();
  const pinta = () => {
    $("[data-plineas]", f).innerHTML = lineas.length ? `<div class="table-wrap"><table><thead><tr><th>Referencia</th><th>Artículo</th><th class="num">Cantidad</th><th class="num">Precio s/IVA</th><th class="num">Importe</th><th></th></tr></thead><tbody>
      ${lineas.map((x, i) => { const pr = x.producto; const imp = num(x.cantidad) && num(x.precio) != null ? num(x.cantidad) * num(x.precio) : null;
        return `<tr><td>${esc(pr.referencia || "nueva (automática)")}</td><td>${esc(pr.articulo)}${x.nuevo ? ' <span class="badge b-pendiente">nuevo</span>' : ""}<div class="muted peq">${esc(pr.unidad || "ud")}${pr.marca ? " · " + esc(pr.marca) : ""}</div></td>
        <td class="num"><input type="number" step="any" min="0" value="${x.cantidad ?? 1}" data-cant="${i}" style="width:80px"></td>
        <td class="num"><input type="number" step="0.0001" min="0" value="${x.precio ?? ""}" data-prec="${i}" style="width:95px" placeholder="sin precio"></td>
        <td class="num">${imp != null ? eur(imp) : "—"}</td><td><button type="button" class="btn sm danger" data-quita="${i}">✕</button></td></tr>`; }).join("")}</tbody></table></div>`
      : '<p class="muted">Busque los productos arriba y púlselos para añadirlos al pedido.</p>';
    let base = 0, iva = 0, sinp = 0;
    lineas.forEach((x) => { const c = num(x.cantidad), pr = num(x.precio); if (pr == null || !c) { sinp += 1; return; } const b = Math.round(c * pr * 100) / 100; base += b; iva += Math.round(b * Number(x.producto.tipo_iva ?? 21)) / 100; });
    $("[data-ptot]", f).innerHTML = lineas.length ? `Coste estimado: <b>${eur(base)}</b> sin IVA · IVA ${eur(iva)} · <b>${eur(base + iva)}</b> con IVA${sinp ? ` · <span class="muted">${sinp} línea(s) sin precio</span>` : ""}` : "";
    f.querySelectorAll("[data-cant]").forEach((i) => (i.oninput = () => { lineas[i.dataset.cant].cantidad = i.value; repinta(); }));
    f.querySelectorAll("[data-prec]").forEach((i) => (i.oninput = () => { lineas[i.dataset.prec].precio = i.value; repinta(); }));
    f.querySelectorAll("[data-quita]").forEach((b) => (b.onclick = () => { lineas.splice(Number(b.dataset.quita), 1); pinta(); }));
  };
  const repinta = debounce(() => { const foco = document.activeElement?.dataset; pinta(); if (foco) { const k = Object.keys(foco)[0]; f.querySelector(`[data-${k}="${foco[k]}"]`)?.focus(); } }, 400);
  const sug = $("[data-psug]", f), busca = $("[data-pbusca]", f);
  busca.oninput = debounce(async () => {
    const q = busca.value.trim();
    if (q.length < 2) { sug.innerHTML = ""; return; }
    const res = await get("/api/productos", { q, limit: 12 }).catch(() => []);
    sug.innerHTML = res.length ? res.map((x, i) => `<button type="button" class="btn sm" data-s="${i}">${prodTxt(x)}</button>`).join("")
      : `<span class="muted">No está en el catálogo.</span> <button type="button" class="btn sm primary" data-crear>＋ Crear «${esc(q)}» como producto nuevo</button>`;
    sug.querySelectorAll("[data-s]").forEach((b) => (b.onclick = () => {
      const x = res[b.dataset.s];
      lineas.push({ product_id: x.id, producto: x, cantidad: 1, precio: x.precio });
      if (!inProv.value && x.proveedor) inProv.value = x.proveedor;
      busca.value = ""; sug.innerHTML = ""; pinta();
    }));
    if ($("[data-crear]", sug)) $("[data-crear]", sug).onclick = () => nuevo(q);
  });
  const nuevo = async (texto) => {  // mini-ficha del producto nuevo dentro del pedido (sin cerrar el pedido)
    const caja = document.createElement("div");
    caja.className = "ped-nuevo";
    const campos = (await camposProducto(false)).filter((c) => c.k !== "proveedor");
    caja.innerHTML = `<fieldset><legend>Producto nuevo (se añade al catálogo)</legend><div class="grid">${campos.map((c) => `<label class="${c.wide ? "wide" : ""}">${esc(c.t)}${c.req ? " *" : ""}
      ${c.type === "select" ? `<select data-n="${c.k}">${c.options.map(([v, t]) => `<option value="${esc(v)}" ${String(v) === String(c.def) ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>`
        : `<input data-n="${c.k}" ${c.type === "number" ? 'type="number" step="0.0001"' : ""} value="${esc(c.k === "articulo" ? texto || "" : c.def ?? "")}">`}</label>`).join("")}
      <label>Cantidad<input data-n="cantidad" type="number" step="any" value="1"></label></div>
      <div class="toolbar"><span class="spacer"></span><button type="button" class="btn sm" data-ncancel>Cancelar</button><button type="button" class="btn sm primary" data-nok>Añadir al pedido</button></div></fieldset>`;
    $("[data-plineas]", f).before(caja);
    caja.querySelector("[data-n=articulo]").focus();
    $("[data-ncancel]", caja).onclick = () => caja.remove();
    $("[data-nok]", caja).onclick = () => {
      const v = Object.fromEntries([...caja.querySelectorAll("[data-n]")].map((i) => [i.dataset.n, i.value.trim()]));
      if (v.articulo.length < 2) return toast("Escriba la descripción del artículo", true);
      const { cantidad, ...prod } = v;
      const nuevoP = productoDatos(prod);
      lineas.push({ nuevo: nuevoP, producto: { ...nuevoP, referencia: nuevoP.referencia || "", tipo_iva: nuevoP.tipo_iva }, cantidad: num(cantidad) || 1, precio: nuevoP.precio ?? null });
      caja.remove(); busca.value = ""; sug.innerHTML = ""; pinta();
    };
  };
  $("[data-pnuevo]", f).onclick = () => nuevo(busca.value.trim());
  pinta();
}

async function fichaPedido(id, reload) {
  const p = await run(() => get(`/api/pedidos/${id}`));
  const volver = () => { reload && reload(); fichaPedido(id, reload); };
  const f = cerrarSolo(form(`Pedido ${p.numero} · ${p.activo}`, [
    { html: `<p><span class="badge b-${p.estado === "pendiente" ? "pendiente" : ["rechazado", "anulado"].includes(p.estado) ? "cancelada" : "vigente"}">${esc(p.estado_nombre)}</span>
      Proveedor: <b>${esc(p.proveedor_nombre || "sin indicar")}</b> · ${fdate(p.fecha)}${p.fecha_entrega ? ` · entrega ${fdate(p.fecha_entrega)}` : ""}<br>
      <span class="muted">Hecho por ${esc(p.creado_por || "—")}${p.autorizado_por_nombre ? ` · autorizado por ${esc(p.autorizado_por_nombre)} (${fdt(p.autorizado_en)})` : p.estado === "pendiente" ? ` · lo autoriza ${esc(p.r1 || "Recepción 1")}` : ""}${p.enviado_en ? ` · enviado ${fdt(p.enviado_en)}` : ""}${p.motivo_rechazo ? ` · motivo: ${esc(p.motivo_rechazo)}` : ""}</span></p>
      <div class="table-wrap"><table><thead><tr><th>Referencia</th><th>Artículo</th><th class="num">Cantidad</th><th class="num">Precio s/IVA</th><th class="num">Importe</th></tr></thead><tbody>
      ${p.lineas.map((x) => `<tr><td>${esc(x.producto.referencia)}</td><td>${esc(x.producto.articulo)}<div class="muted peq">${esc(x.producto.familia)}${x.producto.marca ? " · " + esc(x.producto.marca) : ""}</div></td><td class="num">${x.cantidad} ${esc(x.producto.unidad)}</td><td class="num">${x.precio != null ? eur(x.precio) : "—"}</td><td class="num">${x.importe != null ? eur(x.importe) : "—"}</td></tr>`).join("")}
      <tr class="total"><td colspan="4">Base · IVA · <b>Total estimado</b></td><td class="num">${eur(p.base)} · ${eur(p.iva)} · <b>${eur(p.total)}</b></td></tr></tbody></table></div>
      ${p.notas ? `<p><b>Observaciones:</b> ${esc(p.notas)}</p>` : ""}
      <div class="toolbar">
        ${p.puede_autorizar ? '<button type="button" class="btn primary" data-a="autorizar">Autorizar</button><button type="button" class="btn danger" data-a="rechazar">Rechazar</button>' : ""}
        ${p.puede_editar ? '<button type="button" class="btn" data-a="editar">Modificar</button>' : ""}
        <button type="button" class="btn" data-a="pdf">PDF</button>
        ${p.puede_enviar ? '<button type="button" class="btn primary" data-a="enviar">Enviar al proveedor</button>' : ""}
        ${["autorizado", "enviado"].includes(p.estado) ? '<button type="button" class="btn" data-a="recibido">Recibido</button>' : ""}
        ${["pendiente", "autorizado", "enviado"].includes(p.estado) ? '<button type="button" class="btn danger" data-a="anular">Anular</button>' : ""}
      </div>`, wide: true },
  ], {}, async () => {}));
  $("#modal").classList.add("ancho");
  const motivo = (titulo, url, ok) => form(titulo, [{ k: "motivo", t: "Motivo", req: true, wide: true }], {}, async (d) => { await post(url, d); toast(ok); volver(); });
  const acc = {
    autorizar: () => run(() => post(`/api/pedidos/${id}/autorizar`), "Pedido autorizado").then(volver),
    rechazar: () => motivo(`Rechazar el pedido ${p.numero}`, `/api/pedidos/${id}/rechazar`, "Pedido rechazado"),
    anular: () => motivo(`Anular el pedido ${p.numero}`, `/api/pedidos/${id}/anular`, "Pedido anulado"),
    editar: () => formPedido(p, reload),
    pdf: () => run(() => download("GET", `/api/pedidos/${id}/pdf`)),
    recibido: () => run(() => post(`/api/pedidos/${id}/recibido`), "Pedido recibido").then(volver),
    enviar: () => form(`Enviar ${p.numero} a ${p.proveedor_nombre || "proveedor"}`, [
      { html: `<p class="muted">Correo: ${esc(p.proveedor_email || "no tiene")} · Teléfono: ${esc(p.proveedor_telefono || "no tiene")}. Por correo va el PDF; por WhatsApp, un enlace al PDF.</p>` },
      { k: "canales", t: "Enviar por", type: "checks", req: true, options: [["email", "Correo electrónico (con el PDF)"], ["whatsapp", "WhatsApp (enlace al PDF)"]] },
      { k: "nota", t: "Nota para el proveedor", type: "textarea", wide: true },
    ], { canales: p.proveedor_email ? ["email"] : ["whatsapp"] }, async (d) => {
      const r = await post(`/api/pedidos/${id}/enviar`, { canales: d.canales, nota: d.nota || null });
      r.enviados.filter((x) => x.whatsapp).forEach((x) => window.open(x.whatsapp, "_blank"));
      toast(r.enviados.map((x) => `${x.canal === "email" ? "Correo" : "WhatsApp"}: ${x.ok ? "enviado" : "error " + (x.error || "")}`).join(" · "));
      volver();
    }, "Enviar"),
  };
  f.querySelectorAll("[data-a]").forEach((b) => (b.onclick = () => acc[b.dataset.a]()));
}

V.productos = async (el) => {
  const dir = can("pedidos.autorizar");
  el.innerHTML = `<div class="toolbar"><input id="q" placeholder="Referencia, artículo, marca o proveedor"><select id="fa"><option value="">Todas las familias</option>${(await familias()).map((x) => `<option>${esc(x)}</option>`).join("")}</select>
    <span class="spacer"></span>${dir ? '<button class="btn" id="imp">Importar de INVERGESTION</button><button class="btn" id="exp">Enviar a INVERGESTION</button>' : ""}<button class="btn primary" id="new">Nuevo producto</button></div><div id="t"></div>`;
  const load = async () => table($("#t", el), [
    { k: "referencia", t: "Referencia", f: (v) => `<b>${esc(v)}</b>` }, { k: "articulo", t: "Artículo" }, { k: "familia", t: "Familia" },
    { k: "marca", t: "Marca" }, { k: "proveedor", t: "Proveedor" }, { k: "unidad", t: "Ud." },
    { k: "precio", t: "Precio s/IVA", num: true, f: (v) => (v != null ? eur(v) : "—") }, { k: "origen", t: "Origen" },
  ], await get("/api/productos", { q: $("#q", el).value, familia: $("#fa", el).value, limit: 500 }), (x) => (dir ? [["Editar", async () => {
    form(`Producto ${x.referencia}`, (await camposProducto(false)).filter((c) => c.k !== "referencia"), { ...x, tipo_iva: String(Math.round(x.tipo_iva)) },
      async (d) => { await put(`/api/productos/${x.id}`, productoDatos(d)); toast("Producto actualizado"); load(); });
  }]] : []));
  $("#q", el).oninput = debounce(load); $("#fa", el).onchange = load;
  $("#new", el).onclick = async () => form("Nuevo producto", await camposProducto(true), {}, async (d) => {
    const p = await post("/api/productos", productoDatos(d)); toast(`Producto ${p.referencia} creado`); load();
  });
  if (dir) {
    $("#imp", el).onclick = () => form("Importar el catálogo de INVERGESTION", [
      { html: '<p>Fichero <b>INVERGESTION_PRODUCTOS_….zip</b> (productos.csv y manifest.json). Si la referencia no existe se da de alta; si existe, se actualizan el precio y los datos. No se borra nada y volver a cargarlo no duplica.</p>' },
      { html: '<label>Fichero *<input type="file" accept=".zip,.csv" data-fich required></label>' },
    ], {}, async (_, fr) => {
      const fich = $("[data-fich]", fr).files[0];
      const enviar = (c) => { const fd = new FormData(); fd.append("fichero", fich); fd.append("confirmar", c); return upload("/api/productos/importar", fd); };
      const r = await enviar(false);
      setTimeout(() => form(`Comprobación · ${fich.name}`, [{ html: `<p>${r.tipo ? `Envío <b>${esc(r.tipo)}</b>${r.fecha ? " del " + esc(r.fecha) : ""} · ` : ""}${r.filas} fila(s): <b>${r.altas}</b> alta(s), <b>${r.modificaciones}</b> modificación(es), ${r.sin_cambios} sin cambios${r.errores.length ? `, <b class="error">${r.errores.length} con error</b>` : ""}.</p>
        ${r.errores.length ? `<ul class="error">${r.errores.slice(0, 20).map((e) => `<li>Fila ${e.fila} (${esc(e.referencia || "sin referencia")}): ${esc(e.motivo)}</li>`).join("")}</ul>` : ""}
        ${r.avisos.length ? `<ul class="muted">${r.avisos.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : ""}` }], {}, async () => {
        const c = await enviar(true); toast(`Catálogo importado: ${c.altas} alta(s), ${c.modificaciones} modificación(es)`); load();
      }, "Importar"), 0);
    }, "Comprobar");
    $("#exp", el).onclick = () => form("Enviar productos a INVERGESTION", [
      { k: "activo", t: "Activo", type: "select", req: true, options: S.assets.map((a) => [a.codigo, a.nombre]), def: S.assets.find((a) => a.id === S.asset)?.codigo },
      { html: '<p class="muted">Se genera PRODUCTOS_PMS_&lt;ACTIVO&gt;_&lt;fecha&gt;.zip con los productos dados de alta en el PMS y los pedidos con precio, <b>solo lo nuevo desde el último envío</b>. «Fichero de prueba» lo descarga sin marcarlo como enviado.</p>' },
      { k: "prueba", t: "Fichero de prueba (no lo marca como enviado)", type: "checkbox" },
    ], {}, async (d) => {
      const cod = { SFL: "SFLORIDA", SAE: "SAEROPUERTO", BAB35: "BABILONIA35" }[d.activo] || d.activo;
      const r = await get("/api/productos/exportar/resumen", { activo: cod });
      if (!r.filas && !confirm("No hay nada nuevo desde el último envío. ¿Descargar el fichero vacío?")) return;
      await download("GET", `/api/productos/exportar?activo=${cod}&prueba=${!!d.prueba}`);
      toast(`${r.fichero}: ${r.altas} alta(s) y ${r.pedidos} línea(s) de pedido${d.prueba ? " (prueba)" : ""}`);
    }, "Descargar");
  }
  load();
};

// ------------------------------------------------------------------ parte de trabajo diario (mantenimiento y limpieza)
// Entran solas las OT terminadas y las limpiezas hechas del día; se anotan las actuaciones sin parte. Recepción lo
// valida y entonces se imprime (PDF / Excel) y queda archivado. Informe quincenal con los totales.
const verPartes = () => ["mantenimiento.ver", "limpieza.editar", "partes.validar"].some(can);
const ORIGEN_PARTE = { ot: "Orden de trabajo", limpieza: "Limpieza del parte", actuacion: "Actuación anotada" };
// Corregir una línea del parte (abierto). Actuación: todos sus datos. OT o limpieza: hora, persona, horas y detalle;
// la OT y la limpieza no cambian, la corrección queda en el parte. Se pide el motivo (queda en la auditoría).
async function editarLineaParte(x, p, aid, load) {
  const act = x.origen === "actuacion";
  const uds = act ? await get("/api/unidades", { asset_id: aid }).catch(() => []) : [];
  form(`Editar ${x.ref} · ${ORIGEN_PARTE[x.origen]} · ${fdate(p.fecha)}`, [
    ...(act ? [] : [{ html: `<p class="muted">${esc(x.trabajo)}${x.ubicacion ? " · " + esc(x.ubicacion) : ""}. La corrección queda en el parte; la ${x.origen === "ot" ? "orden de trabajo" : "limpieza"} no cambia.</p>` }]),
    ...(act ? [{ k: "fecha", t: "Día", type: "date", req: true }, { k: "descripcion", t: "Trabajo realizado", type: "textarea", req: true, wide: true },
      { k: "unit_id", t: "Apartamento / unidad", type: "select", options: [["", "—"], ...uds.filter((u) => u.uso !== "garaje").map((u) => [u.id, u.codigo])] },
      { k: "ubicacion", t: "Zona / ubicación" }] : [{ k: "detalle", t: "Detalle", type: "textarea", wide: true }]),
    { k: "hora", t: "Hora a la que se hizo", type: "time", req: true }, { k: "persona", t: "Quién lo hizo" },
    { k: "horas", t: "Horas", type: "number", step: "0.25" },
    { k: "motivo", t: "Motivo de la corrección", req: true, wide: true },
  ], { fecha: p.fecha, descripcion: x.trabajo, unit_id: x.unit_id || "", ubicacion: x.ubicacion_texto ?? "", detalle: x.detalle, hora: x.hora, persona: x.persona, horas: x.horas ?? "" },
  async (d) => {
    const cuerpo = { origen: x.origen, id: x.id, hora: d.hora, persona: d.persona || null, horas: d.horas === "" || d.horas == null ? null : Number(d.horas), motivo: d.motivo,
      ...(act ? { fecha: d.fecha, descripcion: d.descripcion, unit_id: d.unit_id ? Number(d.unit_id) : null, ubicacion: d.ubicacion || null } : { detalle: d.detalle || null }) };
    await put("/api/partes-trabajo/lineas?" + new URLSearchParams({ asset_id: aid, area: p.area, fecha: p.fecha }), cuerpo);
    toast("Línea corregida"); load();
  }, "Guardar corrección");
}
V.partestrabajo = async (el) => {
  const aid = await pickAsset();
  const areaDef = can("mantenimiento.editar") || !can("limpieza.editar") ? "mantenimiento" : "limpieza";
  el.innerHTML = `<div class="toolbar"><select id="ar"><option value="mantenimiento">Mantenimiento</option><option value="limpieza">Limpieza</option></select>
    <input type="date" id="f" value="${today()}" max="${today()}"><span class="spacer"></span>
    <button class="btn" id="quin">Informe quincenal</button></div>
    <div class="parte-dias" id="dias"></div><div id="cab"></div><div id="t"></div>`;
  $("#ar", el).value = areaDef;
  const q = () => ({ asset_id: aid, area: $("#ar", el).value, fecha: $("#f", el).value });
  const load = async () => {
    const [p, dias] = await Promise.all([get("/api/partes-trabajo", q()), get("/api/partes-trabajo/dias", { asset_id: aid, area: $("#ar", el).value })]);
    $("#dias", el).innerHTML = dias.map((d) => `<button type="button" class="btn sm ${d.fecha === p.fecha ? "primary" : ""}" data-dia="${d.fecha}" title="${d.trabajos} trabajo(s)">${Number(d.fecha.slice(8))}/${Number(d.fecha.slice(5, 7))} ${d.validado ? "✔" : d.trabajos ? `<span class="badge b-pendiente">${d.trabajos}</span>` : ""}</button>`).join("");
    $("#dias", el).querySelectorAll("[data-dia]").forEach((b) => (b.onclick = () => { $("#f", el).value = b.dataset.dia; load(); }));
    const val = p.estado === "validado";
    $("#cab", el).innerHTML = `<div class="${val ? "aviso-ok" : "aviso-vencidas"}" style="margin:8px 0"><b>Parte de ${esc(p.area_nombre.toLowerCase())} · ${fdate(p.fecha)}</b> ·
      ${val ? `validado por ${esc(p.validado_por)} (${fdt(p.validado_en)})` : "pendiente de validar por recepción (hasta entonces no se imprime)"} · ${p.lineas.length} trabajo(s)
      ${p.observaciones ? `<br>Observaciones: ${esc(p.observaciones)}` : ""}
      <div class="toolbar">${p.puede_anotar ? '<button class="btn sm" data-x="anotar">＋ Anotar actuación (sin parte)</button>' : ""}
      ${!val && p.puede_validar ? '<button class="btn sm primary" data-x="validar">Validar parte</button>' : ""}
      ${val && p.puede_validar ? '<button class="btn sm" data-x="reabrir">Reabrir</button>' : ""}
      ${val ? '<button class="btn sm" data-x="pdf">PDF</button><button class="btn sm" data-x="xlsx">Excel</button>' : ""}</div></div>`;
    table($("#t", el), [
      { k: "hora", t: "Hora" }, { k: "ref", t: "Ref.", f: (v) => `<b>${esc(v)}</b>` }, { k: "origen", t: "Origen", f: (v) => esc(ORIGEN_PARTE[v] || v) },
      { k: "ubicacion", t: "Ubicación" }, { k: "trabajo", t: "Trabajo realizado", f: (v, x) => `${esc(v)}${x.detalle ? `<div class="muted peq">${esc(x.detalle)}</div>` : ""}` },
      { k: "persona", t: "Persona" }, { k: "horas", t: "Horas", num: true, f: (v, x) => (v ? String(v).replace(".", ",") : "") + (x.corregida ? ' <span class="badge b-pendiente" title="Corregida en el parte">corregida</span>' : "") },
    ], p.lineas, (x) => (!val && p.puede_anotar ? [["Editar", () => editarLineaParte(x, p, aid, load)],
      x.origen === "actuacion" && ["Quitar", () => confirm("¿Quitar esta actuación del parte?") && run(() => api("DELETE", `/api/partes-trabajo/actuaciones/${x.id}`), "Actuación quitada").then(load), "danger"]] : []));
    const acc = {
      anotar: async () => {
        const uds = await get("/api/unidades", { asset_id: aid }).catch(() => []);
        form(`Anotar actuación · ${p.area_nombre} · ${fdate(p.fecha)}`, [
          { html: `<p class="muted">Trabajos que no estaban en ningún parte: ${p.area === "limpieza" ? "limpieza de zonas comunes según el programa, repasos…" : "tareas de mantenimiento sin orden de trabajo, revisiones…"} Las OT terminadas y las limpiezas hechas ya entran solas.</p>` },
          { k: "descripcion", t: "Trabajo realizado", type: "textarea", req: true, wide: true },
          { k: "unit_id", t: "Apartamento / unidad (si es en una)", type: "select", options: [["", "—"], ...uds.filter((u) => u.uso !== "garaje").map((u) => [u.id, u.codigo])] },
          { k: "ubicacion", t: "Zona / ubicación (zonas comunes, sala de máquinas…)" },
          { k: "persona", t: "Quién lo hizo (en blanco: usted)" }, { k: "hora", t: "Hora a la que se hizo", type: "time" }, { k: "horas", t: "Horas", type: "number", step: "0.25" },
        ], { hora: p.fecha === today() ? new Date().toTimeString().slice(0, 5) : "" }, async (d) => { await post("/api/partes-trabajo/actuaciones", clean({ ...q(), ...d, unit_id: d.unit_id ? Number(d.unit_id) : null, horas: d.horas ? Number(d.horas) : null })); toast("Actuación anotada en el parte"); load(); }, "Anotar");
      },
      validar: () => form(`Validar el parte de ${p.area_nombre.toLowerCase()} · ${fdate(p.fecha)}`, [
        { html: `<p>Se validan <b>${p.lineas.length} trabajo(s)</b>. El parte queda cerrado, se puede imprimir y su PDF y Excel se archivan en los documentos del activo.</p>` },
        { k: "observaciones", t: "Observaciones (opcional)", type: "textarea", wide: true },
      ], {}, async (d) => { await post("/api/partes-trabajo/validar", { ...q(), observaciones: d.observaciones || null }); toast("Parte validado y archivado"); load(); }, "Validar"),
      reabrir: () => confirm("¿Reabrir el parte para corregirlo? Se quitarán sus documentos archivados hasta validarlo de nuevo.") && run(() => post("/api/partes-trabajo/reabrir", q()), "Parte reabierto").then(load),
      pdf: () => run(() => download("GET", "/api/partes-trabajo/descargar?" + new URLSearchParams({ ...q(), formato: "pdf" }))),
      xlsx: () => run(() => download("GET", "/api/partes-trabajo/descargar?" + new URLSearchParams({ ...q(), formato: "xlsx" }))),
    };
    $("#cab", el).querySelectorAll("[data-x]").forEach((b) => (b.onclick = acc[b.dataset.x]));
  };
  $("#ar", el).onchange = load; $("#f", el).onchange = load;
  $("#quin", el).onclick = () => informeQuincenal(aid);
  load();
};
async function informeQuincenal(aid, sel) {
  const inf = await run(() => get("/api/partes-trabajo/quincenal", { asset_id: aid, ...(sel || {}) }));
  const per = { asset_id: aid, anio: inf.anio, mes: inf.mes, quincena: inf.quincena };
  const opciones = [];
  for (let i = 0, d = new Date(); i < 12; i++) {  // las últimas 12 quincenas
    const y = d.getFullYear(), m = d.getMonth() + 1, qn = d.getDate() > 15 ? 2 : 1;
    opciones.push([`${y}-${m}-${qn}`, `${qn === 1 ? "1ª" : "2ª"} quincena de ${MESES[m - 1]} ${y}`]);
    if (qn === 2) d.setDate(1); else d.setDate(0);
  }
  const f = cerrarSolo(form(`Informe quincenal · ${assetName(aid)} · ${fdate(inf.desde)} a ${fdate(inf.hasta)}`, [
    { k: "periodo", t: "Quincena", type: "select", options: opciones, def: `${inf.anio}-${inf.mes}-${inf.quincena}` },
    { html: `<div class="table-wrap"><table><thead><tr><th>Área</th><th class="num">Trabajos</th><th class="num">OT</th><th class="num">Limpiezas</th><th class="num">Actuaciones</th><th class="num">Horas anotadas</th><th>Días sin validar</th></tr></thead><tbody>
      ${Object.values(inf.areas).map((a) => `<tr><td><b>${esc(a.nombre)}</b><div class="muted peq">${Object.entries(a.por_persona).map(([k, v]) => `${esc(k)} (${v})`).join(", ")}</div></td><td class="num"><b>${a.total}</b></td><td class="num">${a.por_origen.ot || 0}</td><td class="num">${a.por_origen.limpieza || 0}</td><td class="num">${a.por_origen.actuacion || 0}</td><td class="num">${String(a.horas_anotadas).replace(".", ",")}</td>
        <td>${a.sin_validar.length ? `<span class="badge b-pendiente">${a.sin_validar.map((x) => `${Number(x.slice(8))}/${Number(x.slice(5, 7))}`).join(", ")}</span>` : "✔"}</td></tr>`).join("")}</tbody></table></div>
      <p class="muted">${inf.archivado ? "✔ Ya archivado en los documentos del activo." : "Aún no archivado."} Los días sin validar cuentan sus trabajos, pero conviene validarlos antes de archivar.</p>
      <div class="toolbar"><button type="button" class="btn" data-q="pdf">PDF</button><button type="button" class="btn" data-q="xlsx">Excel</button>${can("partes.validar") ? '<button type="button" class="btn primary" data-q="archivar">Archivar en documentos</button>' : ""}</div>`, wide: true },
  ], {}, async () => {}));
  $("#modal").classList.add("ancho");
  f.elements.periodo.onchange = () => { const [anio, mes, quincena] = f.elements.periodo.value.split("-").map(Number); informeQuincenal(aid, { anio, mes, quincena }); };
  const url = (x) => "/api/partes-trabajo/quincenal/descargar?" + new URLSearchParams({ ...per, ...x });
  f.querySelectorAll("[data-q]").forEach((b) => (b.onclick = () => run(() => download("GET", url(b.dataset.q === "archivar" ? { formato: "pdf", archivar: true } : { formato: b.dataset.q })))
    .then(() => { if (b.dataset.q === "archivar") { toast("Informe archivado (PDF y Excel)"); informeQuincenal(aid, per); } })));
}

// ---- personal: vacaciones, días libres, bajas, permisos y faltas (quién aprueba según el colectivo)
const COLOR_AUS = { vacaciones: "aus-vac", dia_libre: "aus-libre", baja_medica: "aus-baja", permiso: "aus-permiso", falta: "aus-falta", otro: "aus-otro", ausencia: "aus-otro" };
// ---- ausencias: autorizar, desestimar o anular (con motivo) y comunicarlo al trabajador y a Recepción
function comunicadoAusencia(r, que) {
  const c = r.comunicado;
  if (!c) return toast(`Ausencia ${que}`);
  const lineas = [];
  if (!c.correo_configurado) lineas.push('<p class="error">El correo saliente no está configurado: no se ha enviado ningún aviso.</p>');
  else lineas.push(c.enviados.length ? `<p>Correo enviado a: <b>${c.enviados.map(esc).join(", ")}</b></p>` : '<p class="muted">No había a quién enviar el correo.</p>');
  if (!c.trabajador_correo) lineas.push(c.whatsapp
    ? `<p>${esc(r.persona)} no tiene correo: avísele por WhatsApp (el mensaje va escrito; pulse «Enviar» en WhatsApp).</p><p><a class="btn primary" href="${esc(c.whatsapp)}" target="_blank" rel="noopener">Abrir WhatsApp</a></p>`
    : `<p class="error">${esc(r.persona)} no tiene correo ni móvil en su ficha: comuníqueselo de palabra.</p>`);
  cerrarSolo(form(`Ausencia ${que} · ${r.persona}`, [{ html: lineas.join("") }], {}, async () => {}));
}
function accionesAusencia(x, load) {
  const decide = x.puede_aprobar || x.puede_visto_bueno;
  return [
    x.puede_visto_bueno && ["Visto bueno", () => run(() => post(`/api/ausencias/${x.id}/visto-bueno`), "Visto bueno dado: pasa a dirección").then(load), "primary"],
    x.puede_aprobar && ["Autorizar", async () => {
      if (x.aviso_saldo && !confirm(`${x.aviso_saldo}\n\n¿Autorizarla de todas formas?`)) return;
      const r = await run(() => post(`/api/ausencias/${x.id}/aprobar`)); load(); comunicadoAusencia(r, "autorizada");
    }, "primary"],
    decide && ["Desestimar", () => form(`Desestimar · ${x.persona}`, [
      { html: '<p class="muted">El motivo se comunica por correo al trabajador y a Recepción.</p>' },
      { k: "nota", t: "Motivo", type: "textarea", req: true, wide: true }], {},
    async (d) => { const r = await post(`/api/ausencias/${x.id}/denegar`, d); load(); setTimeout(() => comunicadoAusencia(r, "desestimada"), 0); }, "Desestimar")],
    x.puede_anular && ["Anular", () => form(`Anular · ${x.persona}`, [
      { html: `<p class="muted">Para una solicitud con un error o que no procede. Queda registrada como anulada${x.propia ? "" : " y se comunica el motivo al trabajador y a Recepción"}.</p>` },
      { k: "nota", t: x.propia ? "Motivo (opcional)" : "Motivo de la anulación", type: "textarea", req: !x.propia, wide: true }], {},
    async (d) => { const r = await post(`/api/ausencias/${x.id}/anular`, d); load(); setTimeout(() => comunicadoAusencia(r, "anulada"), 0); }, "Anular"), "danger"],
  ];
}
V.ausencias = async (el) => {
  // con «Todos los activos» y varios activos: vista global (cuadrante y pendientes de todos); para solicitar se elige activo
  const global = !S.asset && S.assets.length > 1;
  const aid = global ? null : await pickAsset();
  const cat = await get("/api/ausencias/catalogos");
  el.innerHTML = `<div class="toolbar"><label>Mes<input type="month" id="m" value="${today().slice(0, 7)}"></label>
    <select id="e"><option value="vigentes">Pendientes y aprobadas</option><option value="">Todas</option><option value="pendiente">Pendientes</option><option value="aprobada">Autorizadas</option><option value="denegada">Desestimadas</option><option value="anulada">Anuladas</option></select>
    <span class="spacer"></span><button class="btn" id="cal">Calendario de vacaciones (PDF)</button><button class="btn" id="res">Resumen del año</button><button class="btn" id="xl">Excel</button><button class="btn primary" id="new">Solicitar ausencia</button></div>
    <div id="colaCal"></div><div id="pend"></div><div id="cuad" class="no-encajar"></div><div id="t"></div>`;
  // cambios de vacaciones que saldrán juntos en la próxima revisión del calendario
  const colaCal = async () => {
    const q = await get("/api/ausencias/calendario-vacaciones/pendientes").catch(() => null);
    if (!q || !q.cambios.length || !$("#colaCal", el)) { if ($("#colaCal", el)) $("#colaCal", el).innerHTML = ""; return; }
    $("#colaCal", el).innerHTML = `<div class="aviso-hito" style="margin:8px 0"><b>📅 ${q.cambios.length} cambio(s) de vacaciones pendientes de enviar</b>
      <span class="muted peq">· el calendario se envía a todos cada ${q.horas} h agrupando los cambios (próximo hacia las ${new Date(q.proximo).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })}, en días laborables de 8 a 20 h)</span>
      <div class="muted peq">${q.cambios.map(esc).join(" · ")}</div>
      ${q.puede_enviar ? '<button class="btn sm primary" id="calYa">Enviar calendario ahora</button>' : ""}</div>`;
    if ($("#calYa", el)) $("#calYa", el).onclick = async () => { const r = await run(() => post("/api/ausencias/calendario-vacaciones/enviar")); toast(`Calendario enviado: ${r.cambios} cambio(s), ${r.correos} correo(s)`); colaCal(); };
  };
  const leyenda = Object.entries(cat.tipos).map(([k, v]) => `<span class="aus-ley ${COLOR_AUS[k]}">${esc(v.split(" (")[0])}</span>`).join("") + '<span class="aus-ley aus-pend">Pendiente</span>';
  const load = async () => {
    const [y, m] = $("#m", el).value.split("-").map(Number), n = new Date(y, m, 0).getDate();
    const ini = `${y}-${String(m).padStart(2, "0")}-01`, fin = `${y}-${String(m).padStart(2, "0")}-${n}`;
    const filas = await get("/api/ausencias", { asset_id: aid, desde: ini, hasta: fin, estado: $("#e", el).value });
    const mias = (await get("/api/ausencias", { asset_id: aid, estado: "vigentes" })).filter((x) => x.puede_aprobar || x.puede_visto_bueno);
    colaCal();
    // solicitudes que esperan su decisión (de cualquier mes): se resuelven aquí mismo
    $("#pend", el).innerHTML = mias.length ? `<div class="aviso-vencidas aus-pendientes" style="margin:8px 0"><b>${mias.length} solicitud(es) esperan su decisión</b>
      <span class="muted peq">· al autorizar, desestimar o anular se avisa por correo al trabajador y a Recepción</span><div id="pendT"></div></div>` : "";
    if (mias.length) table($("#pendT", el), [
      { k: "persona", t: "Persona", f: (v, x) => `<b>${esc(v)}</b><div class="muted peq">${esc(x.colectivo_nombre)}${!S.asset ? ` · ${esc(x.activo)}` : ""}</div>${x.aviso_saldo ? `<div class="peq error">⚠ ${esc(x.aviso_saldo)}</div>` : ""}` },
      { k: "tipo_nombre", t: "Tipo", f: (v, x) => `${esc(v)}${x.motivo ? `<div class="muted peq">${esc(x.motivo)}</div>` : ""}` },
      { k: "desde", t: "Fechas", f: (v, x) => `${fdate(v)}${x.hasta !== v ? ` a ${fdate(x.hasta)}` : ""}<div class="muted peq">${x.dias_naturales} días · ${x.dias_laborables} lab.</div>` },
      { k: "estado_nombre", t: "Estado", f: (v) => `<span class="badge b-pendiente">${esc(v)}</span>` },
    ], mias, (x) => [...accionesAusencia(x, load), ["Ver mes", () => { $("#m", el).value = x.desde.slice(0, 7); load(); }]]);
    // cuadrante del mes: una fila por persona, una columna por día
    const vis = filas.filter((x) => ["pendiente", "visto_bueno", "aprobada"].includes(x.estado));
    const personas = [...new Map(vis.map((x) => [`${x.colectivo}|${x.persona}`, x])).values()].sort((a, b) => a.colectivo_nombre.localeCompare(b.colectivo_nombre) || a.persona.localeCompare(b.persona));
    const dias = Array.from({ length: n }, (_, i) => i + 1);
    const finde = (d) => [0, 6].includes(new Date(y, m - 1, d).getDay());
    const celda = (p, d) => {
      const f = `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      const x = vis.find((z) => z.persona === p.persona && z.colectivo === p.colectivo && z.desde <= f && z.hasta >= f);
      return `<td class="${finde(d) ? "aus-finde" : ""} ${x ? `${COLOR_AUS[x.tipo] || "aus-otro"} ${x.estado !== "aprobada" ? "aus-pend" : ""}` : ""}" title="${x ? esc(`${x.tipo_nombre} · ${x.estado_nombre}${global ? ` · ${x.activo}` : ""}`) : ""}"></td>`;
    };
    $("#cuad", el).innerHTML = personas.length ? `<div class="table-wrap aus-cuadrante"><table><thead><tr><th>Persona</th>${dias.map((d) => `<th class="${finde(d) ? "aus-finde" : ""}">${d}</th>`).join("")}</tr></thead>
      <tbody>${personas.map((p) => `<tr><td><b>${esc(p.persona)}</b><div class="muted peq">${esc(p.colectivo_nombre)}${global ? ` · ${esc(p.activo)}` : ""}</div></td>${dias.map((d) => celda(p, d)).join("")}</tr>`).join("")}</tbody></table></div>
      <div class="aus-leyenda">${leyenda}</div>` : `<p class="muted">Nadie tiene ausencias en ${MESES[m - 1]} de ${y}.</p>`;
    table($("#t", el), [
      { k: "persona", t: "Persona", f: (v, x) => `<b>${esc(v)}</b><div class="muted peq">${esc(x.colectivo_nombre)}${global ? ` · ${esc(x.activo)}` : ""}</div>${x.aviso_saldo ? `<div class="peq error">⚠ ${esc(x.aviso_saldo)}</div>` : ""}` },
      { k: "tipo_nombre", t: "Tipo", f: (v, x) => `${esc(v)}${x.motivo ? `<div class="muted peq">${esc(x.motivo)}</div>` : ""}` },
      { k: "desde", t: "Desde", f: fdate }, { k: "hasta", t: "Hasta", f: fdate },
      { k: "dias_naturales", t: "Días", num: true, f: (v, x) => `${v}<div class="muted peq">${x.dias_laborables} lab.</div>` },
      { k: "estado_nombre", t: "Estado", f: (v, x) => `<span class="badge ${x.estado === "aprobada" ? "b-vigente" : ["denegada", "anulada"].includes(x.estado) ? "b-anulado" : "b-pendiente"}">${esc(v)}</span>
        ${x.visto_bueno_nombre ? `<div class="muted peq">V.º B.º ${esc(x.visto_bueno_nombre)}</div>` : ""}${x.resuelto_nombre && x.estado !== "anulada" ? `<div class="muted peq">${esc(x.resuelto_nombre)}</div>` : ""}${x.nota ? `<div class="muted peq">${esc(x.nota)}</div>` : ""}` },
      { k: "aprueba", t: "La aprueba" },
    ], filas, (x) => accionesAusencia(x, load));
  };
  // cada persona solicita sus propias ausencias, con su usuario y sobre su ficha de empleado
  $("#new", el).onclick = async () => {
    const aidN = aid || await pickAsset();
    const f = form(`Solicitar ausencia · ${S.me.nombre}`, [
      { html: '<p class="muted">La solicitud es para usted y queda en su ficha de empleado. Si su usuario no está enlazado a una ficha, pídalo al Director Técnico.</p>' },
      { k: "tipo", t: "Tipo", type: "select", req: true, options: Object.entries(cat.tipos) },
      { k: "desde", t: "Desde", type: "date", req: true, def: today() }, { k: "hasta", t: "Hasta (incluido)", type: "date", req: true, def: today() },
      { k: "motivo", t: "Motivo / observaciones", type: "textarea", wide: true },
    ], {}, async (d) => {
      const r = await post("/api/ausencias", clean({ asset_id: aidN, tipo: d.tipo, desde: d.desde, hasta: d.hasta, motivo: d.motivo }));
      toast(`Solicitud enviada · la aprueba: ${r.aprueba}${r.coinciden.length ? ` · coincide con ${r.coinciden.join(", ")}` : ""}${r.aviso_saldo ? ` · ⚠ ${r.aviso_saldo}` : ""}`, !!r.aviso_saldo);
      load();
    }, "Enviar solicitud");
    f.elements.desde.onchange = () => { if (f.elements.hasta.value < f.elements.desde.value) f.elements.hasta.value = f.elements.desde.value; };
  };
  $("#cal", el).onclick = () => abrirFichero(`/api/ausencias/calendario-vacaciones.pdf?anio=${$("#m", el).value.slice(0, 4)}`);
  $("#res", el).onclick = async () => {
    const anio = Number($("#m", el).value.slice(0, 4));
    const r = await run(() => get("/api/ausencias/resumen", { asset_id: aid, anio }));
    const tipos = Object.entries(r.tipos);
    cerrarSolo(form(`Ausencias aprobadas ${anio} · ${aid ? assetName(aid) : "todos los activos"}`, [{ html: r.personas.length ? `<div class="table-wrap"><table><thead><tr><th>Persona</th>${tipos.map(([, v]) => `<th class="num">${esc(v.split(" (")[0])}</th>`).join("")}<th class="num">Total</th><th class="num">Laborables</th></tr></thead>
      <tbody>${r.personas.map((p) => `<tr><td><b>${esc(p.persona)}</b><div class="muted peq">${esc(p.colectivo)}</div></td>${tipos.map(([k]) => `<td class="num">${p.tipos[k]?.naturales || ""}</td>`).join("")}<td class="num"><b>${p.naturales}</b></td><td class="num">${p.laborables}</td></tr>`).join("")}</tbody></table></div>
      <p class="muted">Días naturales por tipo. Laborables = de lunes a viernes (sin descontar festivos).</p>` : "<p>No hay ausencias aprobadas este año.</p>", wide: true }], {}, async () => {}));
    $("#modal").classList.add("ancho");
  };
  $("#xl", el).onclick = () => run(() => download("GET", "/api/ausencias/excel?" + new URLSearchParams({ ...(aid ? { asset_id: aid } : {}), anio: $("#m", el).value.slice(0, 4) })));
  $("#m", el).onchange = load; $("#e", el).onchange = load;
  load();
};

// ---- portal del colaborador (subcontrata): sus OT, partes, envíos, documentos y personal
const TIPO_ENVIO = { ot_enviada: "Orden de trabajo", parte_limpieza: "Parte de limpieza", limpieza_urgente: "Limpieza urgente" };
V.colaborador = async (el) => {
  const R = S.colab = await get("/api/colaborador/resumen");
  const pestanas = [["ot", "Órdenes de trabajo"], ["partes", "Partes de trabajo"], ["envios", "Envíos recibidos"], ["docs", "Mis documentos"], ["personal", "Mi personal"]];
  el.innerHTML = `<div class="aviso-ok" style="margin-bottom:10px"><b>${esc(R.proveedor.nombre)}</b>${R.proveedor.nif ? ` · ${esc(R.proveedor.nif)}` : ""} · ${R.activos.map((a) => esc(a.nombre)).join(", ")}
      · ${R.ot_abiertas} OT abierta(s) · ${R.personal} persona(s)</div>
    <div class="toolbar">${pestanas.map(([k, t]) => `<button type="button" class="btn sm" data-tab="${k}">${t}</button>`).join("")}<span class="spacer"></span><span id="acc"></span></div><div id="t"></div>`;
  const T = {
    ot: async () => {
      $("#acc", el).innerHTML = '<label class="check"><input type="checkbox" id="ab" checked> Solo abiertas</label>';
      const load = async () => table($("#t", el), [
        { k: "ref", t: "OT", f: (v) => `<b>${esc(v)}</b>` }, { k: "activo", t: "Activo" }, { k: "lugar", t: "Lugar" },
        { k: "titulo", t: "Trabajo", f: (v, w) => `${esc(v)}${w.descripcion ? `<div class="muted peq">${esc(w.descripcion)}</div>` : ""}` },
        { k: "prioridad", t: "Prioridad", f: badge }, { k: "estado", t: "Estado", f: badge },
        { k: "fecha_apertura", t: "Abierta", f: (v, w) => fdate(v) + (w.fecha_prevista ? `<div class="muted peq">prevista ${fdate(w.fecha_prevista)}</div>` : "") },
        { k: "solucion", t: "Realizado", f: (v, w) => (w.terminada ? `${fdate(w.terminada)}<div class="muted peq">${esc(v || "")}</div>` : "") },
        { k: "ultimo", t: "Último resultado", f: (v) => (v ? `<b>${esc(v.resultado)}</b><div class="muted peq">${fdt(v.enviado)}${v.tecnico ? ` · ${esc(v.tecnico)}` : ""}${v.fecha_propuesta ? `<br>siguiente visita ${fdate(v.fecha_propuesta)}` : ""}</div>` : '<span class="muted">—</span>') },
        { k: "persona", t: "Persona" },
      ], await get("/api/colaborador/ordenes", { abiertas: $("#ab", el).checked }), (w) => [
        w.gestionar && ["Gestionar", () => window.open(w.gestionar, "_blank", "noopener"), "primary"],
        ["Subir factura / albarán", () => subirColab({ work_order_id: w.id, tipo: "factura" })]]);
      $("#ab", el).onchange = load; load();
    },
    partes: async () => {
      $("#acc", el).innerHTML = "";
      const partes = await get("/api/colaborador/partes");
      const filas = partes.flatMap((p) => p.lineas.map((x) => ({ ...x, fecha: p.fecha, activo: p.activo, area: p.area })));
      table($("#t", el), [{ k: "fecha", t: "Fecha", f: fdate }, { k: "activo", t: "Activo" }, { k: "ref", t: "Ref.", f: (v) => `<b>${esc(v)}</b>` },
        { k: "ubicacion", t: "Ubicación" }, { k: "trabajo", t: "Trabajo", f: (v, x) => `${esc(v)}${x.detalle ? `<div class="muted peq">${esc(x.detalle)}</div>` : ""}` },
        { k: "persona", t: "Persona" }, { k: "horas", t: "Horas", num: true }], filas);
      $("#t", el).insertAdjacentHTML("afterbegin", '<p class="muted">Sus trabajos en los partes diarios ya validados por recepción (último mes).</p>');
    },
    envios: async () => {
      $("#acc", el).innerHTML = "";
      table($("#t", el), [{ k: "fecha", t: "Fecha", f: fdt }, { k: "persona", t: "Enviado a" }, { k: "tipo", t: "Tipo", f: (v) => esc(TIPO_ENVIO[v] || v) },
        { k: "canal", t: "Canal", f: (v) => (v === "email" ? "Correo" : "WhatsApp") }, { k: "asunto", t: "Asunto" }],
        await get("/api/colaborador/envios"), (e) => [["Ver", () => cerrarSolo(form(e.asunto, [{ html: `<pre class="texto-envio">${esc(e.texto || "")}</pre>` }], {}, async () => {}))]]);
    },
    docs: async () => {
      $("#acc", el).innerHTML = '<button class="btn primary" id="sub">Subir documento</button>';
      $("#sub", el).onclick = () => subirColab({});
      table($("#t", el), [{ k: "subido", t: "Subido", f: fdt }, { k: "activo", t: "Activo" }, { k: "tipo_nombre", t: "Tipo" },
        { k: "referencia", t: "Referencia", f: (v, x) => `${esc(v || x.nombre)}${x.descripcion ? `<div class="muted peq">${esc(x.descripcion)}</div>` : ""}` },
        { k: "persona", t: "Trabajador" }, { k: "ot", t: "OT" },
        { k: "revision_nombre", t: "Estado", f: (v, x) => `<span class="badge ${{ pendiente: "b-pendiente", aceptado: "b-vigente", rechazado: "b-anulado" }[x.revision]}">${esc(v)}</span>${x.revision_nota ? `<div class="muted peq">${esc(x.revision_nota)}</div>` : ""}` }],
        await get("/api/colaborador/documentos"), (x) => [["Ver", () => abrirFichero(`/api/colaborador/documentos/${x.id}/fichero`)],
          x.revision === "pendiente" && ["Borrar", () => confirm("¿Borrar este documento?") && run(() => api("DELETE", `/api/colaborador/documentos/${x.id}`), "Documento borrado").then(() => T.docs()), "danger"]]);
    },
    personal: async () => {
      $("#acc", el).innerHTML = "";
      table($("#t", el), [{ k: "nombre", t: "Nombre" }, { k: "area", t: "Área" }, { k: "activo_nombre", t: "Activo" }, { k: "telefono", t: "Móvil" }, { k: "email", t: "Correo" },
        { k: "activo", t: "Estado", f: (v) => (v ? "En activo" : '<span class="muted">Baja</span>') }], await get("/api/colaborador/personal"),
        (p) => [["Subir documentación", () => subirColab({ staff_id: p.id, tipo: "personal" })]]);
      $("#t", el).insertAdjacentHTML("afterbegin", '<p class="muted">Su personal dado de alta por Recepción 1. Si falta alguien o hay un dato mal, avise a Recepción 1.</p>');
    },
  };
  const abrir = (k) => { el.querySelectorAll("[data-tab]").forEach((b) => b.classList.toggle("primary", b.dataset.tab === k)); T[k]().catch((e) => toast(e.message, true)); };
  el.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => abrir(b.dataset.tab)));
  abrir("ot");
  async function subirColab(ini) {
    const [ots, gente] = await Promise.all([get("/api/colaborador/ordenes"), get("/api/colaborador/personal")]);
    const f = form("Subir documento", [
      { k: "asset_id", t: "Activo", type: "select", req: true, options: R.activos.map((a) => [a.id, a.nombre]) },
      { k: "tipo", t: "Tipo", type: "select", req: true, options: Object.entries(R.tipos_documento) },
      { k: "fecha", t: "Fecha del documento", type: "date", req: true, def: today() }, { k: "referencia", t: "Nº de factura / albarán / referencia" },
      { k: "work_order_id", t: "Orden de trabajo (si corresponde)", type: "select", options: ots.map((w) => [w.id, `${w.ref} · ${w.titulo}`]) },
      { k: "staff_id", t: "Trabajador (documentación de personal)", type: "select", options: gente.map((p) => [p.id, p.nombre]) },
      { k: "descripcion", t: "Descripción", type: "textarea", wide: true },
      { html: '<label class="wide">Fichero (PDF o fotos; varias fotos = varias páginas) *<input type="file" name="ficheros" multiple accept="application/pdf,image/jpeg,image/png" required></label><p class="muted peq">Lo revisará Recepción 1 o dirección. La documentación de personal solo la ven Recepción 1 y dirección.</p>' },
    ], { asset_id: R.activos.length === 1 ? R.activos[0].id : "", ...ini }, async (d, fm) => {
      const fd = new FormData();
      Object.entries(d).forEach(([k, v]) => v !== null && v !== "" && fd.append(k, v));
      [...fm.querySelector("input[type=file]").files].forEach((x) => fd.append("ficheros", x));
      await upload("/api/colaborador/documentos", fd);
      toast("Documento enviado: pendiente de revisar"); abrir("docs");
    }, "Enviar");
    return f;
  }
};

// ---- documentación legal de cada activo: checklist, escaneos en PDF, vencimientos, imprimir y enviar
const ESTADO_LEGAL = { falta: "b-anulado", caducado: "b-anulado", por_vencer: "b-pendiente", aportado: "b-vigente", no_aplica: "", opcional: "" };
V.legal = async (el) => {
  const editar = can("legal.editar");
  const verActivo = async (aid) => {
    const c = await get("/api/documentacion-legal", { asset_id: aid });
    const r = c.resumen;
    el.innerHTML = `<div class="toolbar"><button class="btn" id="todos">← Todos los activos</button><b>${esc(c.activo)}</b>
      <span class="spacer"></span><button class="btn" id="pdf">Imprimir checklist</button>${editar ? '<button class="btn" id="extra">＋ Documento propio</button>' : ""}</div>
      <div class="${r.pendientes ? "aviso-vencidas" : "aviso-ok"}" style="margin:8px 0"><b>${r.completos} de ${r.exigibles} documentos (${r.porcentaje} %)</b>
        · faltan ${r.falta} · caducados ${r.caducado} · por vencer ${r.por_vencer} · no aplican ${r.no_aplica}
        <div class="barra-legal"><span style="width:${r.porcentaje}%"></span></div></div><div id="t" class="no-encajar"></div>`;
    const grupos = [...new Set(c.items.map((x) => x.grupo_nombre))];
    $("#t", el).innerHTML = grupos.map((g) => `<h3 class="legal-grupo">${esc(g)}</h3><div class="table-wrap"><table><tbody>
      ${c.items.filter((x) => x.grupo_nombre === g).map((x) => `<tr>
        <td style="width:110px"><span class="badge ${ESTADO_LEGAL[x.estado] || ""}">${esc(x.estado_nombre)}</span></td>
        <td><b>${esc(x.titulo)}</b><div class="muted peq">${esc(x.norma)}</div>${x.no_aplica && x.motivo ? `<div class="muted peq"><i>No aplica: ${esc(x.motivo)}</i></div>` : ""}${x.notas ? `<div class="peq">${esc(x.notas)}</div>` : ""}
          ${x.ficheros.map((f) => `<div class="peq">📄 <a href="#" data-ver="${f.id}">${esc(f.nombre)}</a>${editar ? ` <a href="#" class="danger" data-borrar="${f.id}">borrar</a>` : ""}</div>`).join("")}</td>
        <td class="peq" style="width:120px">${x.fecha_documento ? `Fecha ${fdate(x.fecha_documento)}` : ""}${x.vencimiento ? `<br>Vence ${fdate(x.vencimiento)}` : ""}</td>
        <td class="acc">${editar ? `<button class="btn sm primary" data-subir="${x.clave}">Escanear / subir</button> <button class="btn sm" data-datos="${x.clave}">Datos</button>` : ""}
          ${x.ficheros.length ? ` <button class="btn sm" data-enviar="${x.clave}">Enviar</button>` : ""}${editar && x.grupo === "propios" && !x.ficheros.length ? ` <button class="btn sm danger" data-quitar="${x.clave}">Quitar</button>` : ""}</td></tr>`).join("")}
      </tbody></table></div>`).join("");
    const item = (k) => c.items.find((x) => x.clave === k);
    const recargar = () => verActivo(aid);
    $("#todos", el).onclick = () => resumenTodos();
    $("#pdf", el).onclick = () => abrirFichero(`/api/documentacion-legal/${aid}/checklist.pdf`);
    if ($("#extra", el)) $("#extra", el).onclick = () => form("Documento propio del activo", [{ k: "titulo", t: "Documento", req: true, wide: true }], {},
      async (d) => { await post(`/api/documentacion-legal/${aid}/extra`, d); toast("Añadido al checklist"); recargar(); }, "Añadir");
    el.querySelectorAll("[data-ver]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); abrirFichero(`/api/documentacion-legal/ficheros/${a.dataset.ver}`); }));
    el.querySelectorAll("[data-borrar]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); if (confirm("¿Borrar este documento?")) run(() => api("DELETE", `/api/documentacion-legal/ficheros/${a.dataset.borrar}`), "Documento borrado").then(recargar); }));
    el.querySelectorAll("[data-quitar]").forEach((b) => (b.onclick = () => confirm("¿Quitar este punto del checklist?") && run(() => api("DELETE", `/api/documentacion-legal/${aid}/extra/${b.dataset.quitar}`), "Quitado").then(recargar)));
    el.querySelectorAll("[data-subir]").forEach((b) => (b.onclick = () => {
      const x = item(b.dataset.subir);
      form(`Escanear · ${x.titulo}`, [
        { html: `<p class="muted">${esc(x.norma)}</p><label class="wide">PDF o fotos (desde el móvil se puede hacer la foto; varias fotos = varias páginas de un PDF) *<input type="file" name="ficheros" multiple accept="application/pdf,image/*" required></label>` },
        { k: "fecha_documento", t: "Fecha del documento", type: "date", def: x.fecha_documento || "" },
        { k: "vencimiento", t: x.meses ? `Vence (en blanco: ${x.meses >= 12 ? `${x.meses / 12} año(s)` : `${x.meses} meses`} desde la fecha)` : "Vence (si caduca)", type: "date" },
      ], {}, async (d, fm) => {
        const fd = new FormData();
        [...fm.querySelector("input[type=file]").files].forEach((f) => fd.append("ficheros", f));
        if (d.fecha_documento) fd.append("fecha_documento", d.fecha_documento);
        if (d.vencimiento) fd.append("vencimiento", d.vencimiento);
        await upload(`/api/documentacion-legal/${aid}/${x.clave}/ficheros`, fd); toast("Documento guardado en PDF"); recargar();
      }, "Guardar");
    }));
    el.querySelectorAll("[data-datos]").forEach((b) => (b.onclick = () => {
      const x = item(b.dataset.datos);
      const f = form(`Datos · ${x.titulo}`, [
        { k: "fecha_documento", t: "Fecha del documento", type: "date" }, { k: "vencimiento", t: "Vence", type: "date" },
        { k: "no_aplica", t: "No aplica a este activo", type: "checkbox", wide: true }, { k: "motivo", t: "Por qué no aplica", wide: true },
        { k: "notas", t: "Notas (nº de expediente, póliza, empresa…)", type: "textarea", wide: true },
      ], x, async (d) => { await put(`/api/documentacion-legal/${aid}/${x.clave}`, d); toast("Guardado"); recargar(); });
      const motivo = () => (f.elements.motivo.closest("label").style.display = f.elements.no_aplica.checked ? "" : "none");
      f.elements.no_aplica.onchange = motivo; motivo();
    }));
    el.querySelectorAll("[data-enviar]").forEach((b) => (b.onclick = () => {
      const x = item(b.dataset.enviar);
      form(`Enviar por correo · ${x.titulo}`, [{ html: `<p class="muted">Se adjuntan ${x.ficheros.length} documento(s) en PDF.</p>` },
        { k: "email", t: "Correo del destinatario", type: "email", req: true, wide: true }, { k: "nota", t: "Mensaje (opcional)", type: "textarea", wide: true }],
      {}, async (d) => { await post(`/api/documentacion-legal/${aid}/${x.clave}/enviar`, clean(d)); toast("Enviado"); }, "Enviar");
    }));
  };
  const resumenTodos = async () => {
    const lista = await get("/api/documentacion-legal/resumen");
    el.innerHTML = `<p class="muted">Documentación legal obligatoria de cada activo (Comunidad y Ayuntamiento de Madrid), según sea de apartamentos turísticos o de alquiler residencial. Cada lunes se avisa a Recepción 1 de lo que falta en su activo y a la dirección del total, hasta completarla.</p><div id="t"></div>`;
    table($("#t", el), [
      { k: "activo", t: "Activo" }, { k: "porcentaje", t: "Completo", f: (v) => `<div class="barra-legal"><span style="width:${v}%"></span></div>${v} %` },
      { k: "falta", t: "Faltan", num: true }, { k: "caducado", t: "Caducados", num: true }, { k: "por_vencer", t: "Por vencer", num: true },
      { k: "pendientes_lista", t: "Pendientes", f: (v) => `<span class="peq">${v.slice(0, 4).map(esc).join(" · ")}${v.length > 4 ? ` y ${v.length - 4} más` : ""}</span>` },
    ], lista, (a) => [["Abrir", () => verActivo(a.asset_id), "primary"]]);
  };
  if (S.asset) verActivo(Number(S.asset)); else resumenTodos();
};

// ---- alquiler residencial: cobros de otro programa (facturas en PDF/ZIP) como ingresos por arrendamiento
V.cobrosext = async (el) => {
  const aid = await pickAsset("alquiler_residencial");
  const anio = new Date().getFullYear();
  el.innerHTML = `<div class="toolbar"><label>Año<select id="y">${[anio, anio - 1, anio - 2].map((y) => `<option>${y}</option>`).join("")}</select></label>
    <span class="spacer"></span><button class="btn" id="xl">Excel de ingresos</button>${can("alquiler.editar") ? '<button class="btn primary" id="imp">Importar facturas (PDF o ZIP)</button>' : ""}</div>
    <p class="muted">Rentas cobradas con otro programa: cada mensualidad cuenta como ingreso del activo (producción). Al importar se abre la ficha del inquilino; el piso y el contrato se completan después en <b>Contratos</b>.</p><div id="k"></div><div id="t"></div>`;
  const load = async () => {
    const r = await get("/api/cobros-alquiler", { asset_id: aid, anio: $("#y", el).value });
    $("#k", el).innerHTML = `<div class="kpis"><div class="kpi"><b>${r.inquilinos.length}</b><span>Inquilinos</span></div><div class="kpi"><b>${eur(r.renta_mensual)}</b><span>Renta mensual</span></div><div class="kpi"><b>${eur(r.total)}</b><span>Cobrado en ${$("#y", el).value}</span></div></div>`;
    table($("#t", el), [
      { k: "cliente", t: "Inquilino", f: (v, x) => `${esc(v)}${x.contact_id ? "" : ' <span class="badge b-pendiente">sin ficha</span>'}` },
      { k: "renta", t: "Renta", num: true, f: eur }, { k: "desde", t: "Desde" }, { k: "hasta", t: "Hasta" },
      { k: "meses", t: "Meses", num: true }, { k: "total", t: "Cobrado", num: true, f: eur },
    ], r.inquilinos, (x) => [["Documento", () => abrirFichero(`/api/cobros-alquiler/${x.clave}/pdf?asset_id=${aid}`)],
      can("alquiler.editar") && ["Borrar cobros", () => confirm(`¿Borrar los ${x.meses} cobros importados de ${x.cliente}? La ficha se conserva.`) && run(() => api("DELETE", `/api/cobros-alquiler/${x.clave}?asset_id=${aid}`), "Cobros borrados").then(load), "danger"]]);
  };
  $("#y", el).onchange = load;
  $("#xl", el).onclick = () => run(() => download("GET", `/api/cobros-alquiler/excel/ingresos?asset_id=${aid}&anio=${$("#y", el).value}`));
  if ($("#imp", el)) $("#imp", el).onclick = () => form("Importar facturas de alquiler", [
    { html: '<label class="wide">Facturas en PDF o un ZIP con todas *<input type="file" name="ficheros" multiple accept="application/pdf,application/zip,.zip" required></label><p class="muted peq">Se leen el inquilino, el importe y el mes. En el paso siguiente indica de qué mes a qué mes se repite la renta.</p>' },
  ], {}, async (d, fm) => {
    const fd = new FormData(); fd.append("asset_id", aid);
    [...fm.querySelector("input[type=file]").files].forEach((f) => fd.append("ficheros", f));
    const r = await upload("/api/cobros-alquiler/leer", fd);
    setTimeout(() => revisar(r), 0);
  }, "Leer facturas");
  const revisar = (r) => {
    const f = form(`Revisar ${r.facturas.length} factura(s)`, [{ html: `${r.avisos.length ? `<div class="aviso-vencidas"><b>Revise:</b><ul>${r.avisos.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></div>` : ""}
      <p class="muted">Cada inquilino genera un cobro por mes, del mes «Desde» al «Hasta», con su importe. Quite la marca de los que no quiera importar.</p>
      <div class="table-wrap"><table><thead><tr><th></th><th>Inquilino</th><th>Factura</th><th>Mes factura</th><th class="num">Renta</th><th>Desde</th><th>Hasta</th></tr></thead><tbody>
      ${r.facturas.map((x, i) => `<tr><td><input type="checkbox" data-i="${i}" checked></td><td>${esc(x.cliente || "?")}${x.ficha ? ' <span class="muted peq">(ya tiene ficha)</span>' : ""}</td><td>${esc(x.numero)}<div class="muted peq">${fdate(x.fecha)}</div></td>
        <td>${esc(x.mes || "—")}</td><td class="num">${eur(x.total)}</td><td><input type="month" data-d="${i}" value="${x.desde}"></td><td><input type="month" data-h="${i}" value="${x.hasta}"></td></tr>`).join("")}</tbody></table></div>`, wide: true }], {},
    async (_, fm) => {
      const filas = r.facturas.map((x, i) => ({ ...x, desde: fm.querySelector(`[data-d="${i}"]`).value, hasta: fm.querySelector(`[data-h="${i}"]`).value }))
        .filter((_, i) => fm.querySelector(`[data-i="${i}"]`).checked).map(({ numero, fecha, cliente, nif, direccion, total, desde, hasta }) => ({ numero, fecha, cliente, nif, direccion, total, desde, hasta }));
      if (!filas.length) throw new Error("No hay ninguna marcada");
      const res = await post("/api/cobros-alquiler/importar", { asset_id: aid, filas });
      toast(`${res.cobros} cobros de ${res.inquilinos} inquilinos · ${res.fichas_nuevas} ficha(s) nueva(s)`); load();
    }, "Importar");
    $("#modal").classList.add("ancho");
    return f;
  };
  load();
};

// ------------------------------------------------------------------ navegación
// ------------------------------------------------------------------ CAPEX (inversiones y reformas)
// Proyecto → presupuesto (BC3, base de precios, plantillas) → documentos → licitación ciega → comparativo →
// adjudicación (completa o por capítulos) → aprobación de la Dirección General por correo (> umbral).
const num2 = (v) => (v == null ? "" : Number(v).toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const pct = (v) => (v == null ? "" : `${v > 0 ? "+" : ""}${Number(v).toLocaleString("es-ES")} %`);
const COLOR_EST_CAPEX = { definicion: "b-borrador", licitacion: "b-pendiente", adjudicacion: "b-pendiente", pendiente_aprobacion: "b-urgente", adjudicado: "b-vigente", cancelado: "b-anulado" };
async function catCapex() { S.catCapex = S.catCapex || await get("/api/capex/catalogos"); return S.catCapex; }

V.capex = async (el) => {
  const id = Number(S.params?.get("id"));
  if (id) return capexProyecto(el, id);
  const C = await catCapex();
  const gest = can("capex.gestionar");
  el.innerHTML = `<div class="toolbar"><select id="est"><option value="abiertos">En curso</option><option value="">Todos</option>${Object.entries(C.estados).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select>
    <span class="spacer"></span>${gest ? '<button class="btn primary" id="new">Nuevo proyecto</button>' : ""}</div>
    <p class="muted">Inversiones y reformas: mediciones y presupuesto base, documentación, petición de ofertas a contratistas sin mostrar los precios base, comparativo y adjudicación. Por encima de ${eur(C.umbral)} (sin IVA) la adjudicación la aprueba la Dirección General por correo.</p><div id="t"></div>`;
  const load = async () => table($("#t", el), [
    { k: "codigo", t: "Código", f: (v) => `<b>${esc(v)}</b>` },
    { k: "titulo", t: "Proyecto", f: (v, p) => `${esc(v)}<div class="muted peq">${esc(p.activo)}${p.unidad ? ` · ${esc(p.unidad)}` : ""}${p.ubicacion ? ` · ${esc(p.ubicacion)}` : ""}</div>` },
    { k: "estado_nombre", t: "Estado", f: (v, p) => `<span class="badge ${COLOR_EST_CAPEX[p.estado] || ""}">${esc(v)}</span>` },
    { k: "pbl", t: "PBL (sin IVA)", num: true, f: (v, p) => `${eur(v)}${p.presupuesto_objetivo ? `<div class="muted peq">objetivo ${eur(p.presupuesto_objetivo)} · ${pct(p.desviacion_objetivo)}</div>` : ""}` },
    { k: "adjudicado", t: "Adjudicado", num: true, f: (v) => (v != null ? eur(v) : "") },
    { k: "actualizado", t: "Actualizado", f: fdt },
  ], await get("/api/capex", { asset_id: S.asset, estado: $("#est", el).value }), (p) => [["Abrir", () => go(`capex?id=${p.id}`), "primary"]]);
  $("#est", el).onchange = load;
  if ($("#new", el)) $("#new", el).onclick = async () => {
    const plantillas = await get("/api/capex/plantillas/lista");
    form("Nuevo proyecto CAPEX", [
      { k: "asset_id", t: "Activo", type: "select", req: true, options: opts(S.assets) },
      { k: "titulo", t: "Título (p. ej. Reforma integral baños planta 3)", req: true, wide: true },
      { k: "plantilla_id", t: "Cargar una plantilla «CAPEX tipo» (capítulos, partidas y documentos base)", type: "select", options: plantillas.filter((t) => t.activa).map((t) => [t.id, `${t.nombre} · ${t.n_partidas} partidas`]), wide: true },
      { k: "ubicacion", t: "Ubicación (planta, zona, unidades…)" }, { k: "presupuesto_objetivo", t: "Presupuesto objetivo € (sin IVA)", type: "number" },
      { k: "fecha_inicio", t: "Inicio previsto", type: "date" }, { k: "fecha_fin", t: "Fin previsto", type: "date" },
      { k: "gg_pct", t: "Gastos generales %", type: "number", def: 13 }, { k: "bi_pct", t: "Beneficio industrial %", type: "number", def: 6 },
      { k: "iva_pct", t: "IVA %", type: "select", options: [[21, "21 %"], [10, "10 % (renovación de vivienda)"], [0, "Exento / no sujeto"]], def: 21 },
      { k: "descripcion", t: "Descripción / alcance", type: "textarea", wide: true },
    ], { asset_id: S.asset || (S.assets.length === 1 ? S.assets[0].id : "") }, async (d) => {
      const p = await post("/api/capex", { ...clean(d), asset_id: Number(d.asset_id), plantilla_id: d.plantilla_id ? Number(d.plantilla_id) : null, iva_pct: Number(d.iva_pct ?? 21) });
      toast(`Proyecto ${p.codigo} creado`); setTimeout(() => go(`capex?id=${p.id}`), 0);
    }, "Crear");
  };
  load();
};

async function capexProyecto(el, id) {
  const C = await catCapex();
  let D, tab = S.capexTab = "presupuesto";
  const cargar = async () => { D = await get(`/api/capex/${id}`); };
  await cargar();
  const pinta = () => {
    const p = D.proyecto, t = D.totales, g = D.gestionar, def = p.estado === "definicion";
    const pest = [["presupuesto", "📐 Presupuesto"], ["documentos", `📎 Documentos (${D.documentos.length})`], ["licitacion", "📨 Licitación"], ["comparativo", "📊 Comparativo y adjudicación"], ["aprobacion", `✅ Aprobación${D.aprobaciones.some((a) => a.estado === "pendiente") ? " (pendiente)" : ""}`]];
    el.innerHTML = `<div class="capex-cab"><div><div class="muted peq"><a href="#capex" id="lista">← Proyectos CAPEX</a></div>
        <h3 style="margin:2px 0">${esc(p.codigo)} · ${esc(p.titulo)} <span class="badge ${COLOR_EST_CAPEX[p.estado] || ""}">${esc(p.estado_nombre)}</span></h3>
        <div class="muted">${esc(p.activo)}${p.unidad ? ` · ${esc(p.unidad)}` : ""}${p.ubicacion ? ` · ${esc(p.ubicacion)}` : ""}${p.fecha_inicio ? ` · ${fdate(p.fecha_inicio)} → ${fdate(p.fecha_fin)}` : ""}</div></div>
      <div class="capex-kpis"><div><small>Ejecución material</small><b>${eur(t.pem)}</b></div><div><small>PBL (GG ${p.gg_pct} % + BI ${p.bi_pct} %)</small><b>${eur(t.pbl)}</b></div>
        <div><small>Total con IVA ${p.iva_pct} %</small><b>${eur(t.total)}</b></div>
        ${p.presupuesto_objetivo ? `<div class="${t.desviacion_objetivo > 0 ? "mal" : ""}"><small>Objetivo ${eur(p.presupuesto_objetivo)}</small><b>${pct(t.desviacion_objetivo)}</b></div>` : ""}
        ${p.adjudicado != null ? `<div><small>Adjudicado</small><b>${eur(p.adjudicado)}</b></div>` : ""}</div></div>
      <div class="toolbar"><div class="chips" style="margin:0">${pest.map(([k, l]) => `<button type="button" class="chip${k === tab ? " on" : ""}" data-tab="${k}">${l}</button>`).join("")}</div><span class="spacer"></span>
        ${g ? `<button class="btn sm" id="datos">Datos del proyecto</button><button class="btn sm" id="plant">Guardar como plantilla</button>` : ""}
        <button class="btn sm" id="xls">Excel</button>
        ${g && ["licitacion", "cancelado"].includes(p.estado) && !D.licitaciones.some((l) => l.invitaciones.some((i) => i.oferta?.estado === "enviada")) ? '<button class="btn sm" id="adef">Volver a definición</button>' : ""}
        ${g && !["adjudicado", "cancelado"].includes(p.estado) ? '<button class="btn sm danger" id="cancel">Cancelar</button>' : ""}
        ${g && def && !D.licitaciones.length ? '<button class="btn sm danger" id="borrar">Borrar</button>' : ""}</div>
      <div id="cx"></div>`;
    $("#lista", el).onclick = (e) => { e.preventDefault(); go("capex"); };
    el.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => { tab = S.capexTab = b.dataset.tab; pinta(); }));
    $("#xls", el).onclick = () => run(() => download("GET", `/api/capex/${id}/presupuesto.xlsx`));
    if ($("#datos", el)) $("#datos", el).onclick = () => form(`Datos · ${p.codigo}`, [
      { k: "titulo", t: "Título", req: true, wide: true }, { k: "ubicacion", t: "Ubicación" },
      { k: "presupuesto_objetivo", t: "Presupuesto objetivo € (sin IVA)", type: "number" },
      { k: "fecha_inicio", t: "Inicio previsto", type: "date" }, { k: "fecha_fin", t: "Fin previsto", type: "date" },
      ...(def ? [{ k: "gg_pct", t: "Gastos generales %", type: "number" }, { k: "bi_pct", t: "Beneficio industrial %", type: "number" }] : []),
      { k: "iva_pct", t: "IVA %", type: "number" }, { k: "descripcion", t: "Descripción / alcance", type: "textarea", wide: true },
    ], p, async (d) => { await put(`/api/capex/${id}`, d); toast("Datos guardados"); await cargar(); pinta(); });
    if ($("#plant", el)) $("#plant", el).onclick = () => form("Guardar como plantilla «CAPEX tipo»", [
      { html: '<p class="muted">Guarda los capítulos, partidas y precios de este proyecto, y sus planos, pliegos y memorias, para cargarlos con un clic en proyectos nuevos.</p>' },
      { k: "nombre", t: "Nombre (p. ej. Reforma integral baño)", req: true, wide: true }, { k: "descripcion", t: "Descripción", type: "textarea", wide: true },
      { k: "con_cantidades", t: "Guardar también las cantidades (si no, se miden en cada proyecto)", type: "checkbox", def: true, wide: true },
    ], {}, async (d) => { await post("/api/capex/plantillas/lista", { ...d, project_id: id }); toast("Plantilla guardada"); });
    const estado = (estado, txt, motivo) => async () => {
      let m = null;
      if (motivo) { m = prompt(txt); if (m === null) return; } else if (!confirm(txt)) return;
      await run(() => post(`/api/capex/${id}/estado`, { estado, motivo: m })); await cargar(); pinta();
    };
    if ($("#adef", el)) $("#adef", el).onclick = estado("definicion", "¿Volver a definición? Las invitaciones enviadas quedan cerradas y habrá que volver a pedir ofertas.");
    if ($("#cancel", el)) $("#cancel", el).onclick = estado("cancelado", "Motivo de la cancelación:", true);
    if ($("#borrar", el)) $("#borrar", el).onclick = async () => { if (confirm("¿Borrar el proyecto y sus documentos?")) { await run(() => api("DELETE", `/api/capex/${id}`), "Proyecto borrado"); go("capex"); } };
    const recarga = async () => { await cargar(); tab = S.capexTab || tab; pinta(); };
    ({ presupuesto: capexPresupuesto, documentos: capexDocumentos, licitacion: capexLicitacion, comparativo: capexComparativo, aprobacion: capexAprobacion })[tab]($("#cx", el), D, recarga, C);
  };
  pinta();
}

// ---- presupuesto: grid por capítulos (editable en definición)
function capexPresupuesto(cx, D, recarga) {
  const p = D.proyecto, ed = D.gestionar && p.estado === "definicion", t = D.totales;
  const caps = t.capitulos;
  const fila = (x) => ed
    ? `<tr data-id="${x.id}"><td><input data-f="codigo" value="${esc(x.codigo || "")}" class="cx-cod"></td><td><textarea data-f="descripcion" rows="${Math.min(4, x.descripcion.split("\n").length)}">${esc(x.descripcion)}</textarea></td>
       <td><input data-f="unidad" value="${esc(x.unidad || "")}" class="cx-ud"></td><td class="num"><input data-f="cantidad" type="number" step="any" min="0" value="${x.cantidad}" class="cx-num ${x.cantidad ? "" : "cx-cero"}"></td>
       <td class="num"><input data-f="precio" type="number" step="0.01" min="0" value="${x.precio}" class="cx-num"></td><td class="num">${num2(x.importe)}</td>
       <td class="acc"><button class="btn sm danger" data-del="${x.id}" title="Borrar partida">✕</button></td></tr>`
    : `<tr><td>${esc(x.codigo || "")}</td><td class="cx-desc">${esc(x.descripcion)}</td><td>${esc(x.unidad || "")}</td><td class="num">${x.cantidad.toLocaleString("es-ES")}</td><td class="num">${num2(x.precio)}</td><td class="num">${num2(x.importe)}</td></tr>`;
  cx.innerHTML = `${ed ? `<div class="toolbar"><button class="btn" id="bc3">Importar BC3 (Presto, Arquímedes…)</button><button class="btn" id="base">Añadir desde base de precios</button><button class="btn" id="pla">Cargar plantilla</button><button class="btn" id="cap">Nuevo capítulo</button><span class="spacer"></span><span class="muted peq">Los cambios se guardan solos al salir de cada casilla.</span></div>`
    : `<p class="muted">${p.estado === "definicion" ? "Solo lectura." : "Las mediciones están cerradas: el proyecto ya se ha licitado (todas las ofertas son sobre lo mismo)."}</p>`}
    ${caps.length ? `<div class="table-wrap no-encajar"><table class="cx-grid"><thead><tr><th style="width:90px">Código</th><th>Descripción</th><th style="width:60px">Ud</th><th class="num" style="width:100px">Cantidad</th><th class="num" style="width:100px">Precio €</th><th class="num" style="width:110px">Importe €</th>${ed ? '<th class="acc"></th>' : ""}</tr></thead><tbody>
      ${caps.map((c) => `<tr class="cx-cap"><td colspan="5"><b>${esc(c.capitulo)} ${esc(c.nombre)}</b> <span class="muted peq">${c.partidas} partida(s)</span>
        ${ed ? ` <button class="btn sm" data-ren="${esc(c.capitulo)}">Renombrar</button> <button class="btn sm" data-add="${esc(c.capitulo)}">+ Partida</button>` : ""}</td><td class="num"><b>${num2(c.importe)}</b></td>${ed ? "<td></td>" : ""}</tr>
        ${D.partidas.filter((x) => x.capitulo === c.capitulo).map(fila).join("")}`).join("")}
    </tbody></table></div>` : '<div class="empty" style="padding:20px">Sin partidas. Importe un BC3, cargue una plantilla, añada desde la base de precios o cree un capítulo.</div>'}
    <div class="cx-totales"><table>
      <tr><td>Presupuesto de ejecución material (PEM)</td><td class="num">${eur(t.pem)}</td></tr>
      <tr><td>Gastos generales ${p.gg_pct} %</td><td class="num">${eur(t.gg)}</td></tr><tr><td>Beneficio industrial ${p.bi_pct} %</td><td class="num">${eur(t.bi)}</td></tr>
      <tr class="tot"><td>Presupuesto base de licitación (PBL)</td><td class="num">${eur(t.pbl)}</td></tr>
      <tr><td>IVA ${p.iva_pct} %</td><td class="num">${eur(t.iva)}</td></tr><tr class="tot"><td>Total con IVA</td><td class="num">${eur(t.total)}</td></tr></table></div>`;
  if (!ed) return;
  cx.querySelectorAll("tr[data-id] [data-f]").forEach((i) => (i.onchange = async () => {
    const f = i.dataset.f, v = ["cantidad", "precio"].includes(f) ? Number(i.value || 0) : i.value;
    try { await put(`/api/capex/partidas/${i.closest("tr").dataset.id}`, { [f]: v }); if (["cantidad", "precio"].includes(f)) recarga(); }
    catch (e) { toast(e.message, true); }
  }));
  cx.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { if (confirm("¿Borrar la partida?")) { await run(() => api("DELETE", `/api/capex/partidas/${b.dataset.del}`)); recarga(); } }));
  cx.querySelectorAll("[data-ren]").forEach((b) => (b.onclick = () => { const c = caps.find((z) => z.capitulo === b.dataset.ren);
    form("Renombrar capítulo", [{ k: "capitulo", t: "Número", req: true }, { k: "nombre", t: "Nombre", req: true, wide: true }], c,
      async (d) => { await put(`/api/capex/${p.id}/capitulos/${encodeURIComponent(c.capitulo)}`, d); recarga(); }); }));
  const nueva = (capitulo, nombre) => form(`Nueva partida · ${capitulo} ${nombre}`, [
    { k: "codigo", t: "Código" }, { k: "unidad", t: "Unidad (m2, ml, ud…)" }, { k: "descripcion", t: "Descripción", type: "textarea", req: true, wide: true },
    { k: "cantidad", t: "Cantidad", type: "number" }, { k: "precio", t: "Precio unitario € (ejecución material)", type: "number" },
  ], {}, async (d) => { await post(`/api/capex/${p.id}/partidas`, { ...clean(d), capitulo, capitulo_nombre: nombre }); recarga(); });
  cx.querySelectorAll("[data-add]").forEach((b) => (b.onclick = () => nueva(b.dataset.add, caps.find((z) => z.capitulo === b.dataset.add).nombre)));
  $("#cap", cx).onclick = () => form("Nuevo capítulo", [{ k: "capitulo", t: "Número", req: true, def: String(caps.length + 1).padStart(2, "0") }, { k: "nombre", t: "Nombre (p. ej. DEMOLICIONES)", req: true, wide: true }], {},
    async (d) => { setTimeout(() => nueva(d.capitulo, d.nombre), 0); });
  $("#bc3", cx).onclick = () => form("Importar presupuesto BC3", [
    { html: '<p class="muted">Fichero FIEBDC-3 (.bc3, o .zip que lo contenga) con mediciones, exportado de Presto, Arquímedes, Menfis… Se cargan los capítulos, las partidas, las cantidades y los precios.</p>' },
    { html: '<label class="wide">Fichero *<input type="file" name="f" accept=".bc3,.zip" required></label>' },
    { k: "reemplazar", t: "Sustituir las partidas actuales (si no, se añaden)", type: "checkbox", wide: true },
  ], {}, async (d, f) => {
    const fd = new FormData(); fd.append("fichero", f.elements.f.files[0]); fd.append("reemplazar", d.reemplazar ? "true" : "false");
    const r = await upload(`/api/capex/${p.id}/importar-bc3`, fd); toast(`${r.partidas} partidas en ${r.capitulos} capítulos`); recarga();
  }, "Importar");
  $("#pla", cx).onclick = async () => {
    const pl = (await get("/api/capex/plantillas/lista")).filter((x) => x.activa);
    if (!pl.length) return toast("No hay plantillas: guarde un proyecto como plantilla o créela en «Plantillas CAPEX tipo»", true);
    form("Cargar plantilla", [{ k: "plantilla_id", t: "Plantilla", type: "select", req: true, options: pl.map((x) => [x.id, `${x.nombre} · ${x.n_partidas} partidas · ${eur(x.pem)}`]), wide: true },
      { html: '<p class="muted">Se añaden sus capítulos, partidas y documentos base. Después ajuste las mediciones de este proyecto.</p>' }], {},
    async (d) => { const r = await post(`/api/capex/${p.id}/plantilla`, { plantilla_id: Number(d.plantilla_id) }); toast(`${r.partidas} partidas añadidas`); recarga(); }, "Cargar");
  };
  $("#base", cx).onclick = () => buscarPrecios(async (sel) => {
    const capOps = caps.map((c) => [`${c.capitulo}|${c.nombre}`, `${c.capitulo} ${c.nombre}`]);
    form(`Añadir ${sel.length} partida(s)`, [
      ...(capOps.length ? [{ k: "cap", t: "Al capítulo", type: "select", options: capOps }] : []),
      { k: "nuevo_num", t: "…o capítulo nuevo: número" }, { k: "nuevo_nombre", t: "Nombre del capítulo nuevo", wide: true },
    ], {}, async (d) => {
      const [capitulo, capitulo_nombre] = d.nuevo_num && d.nuevo_nombre ? [d.nuevo_num, d.nuevo_nombre] : (d.cap || "").split("|");
      if (!capitulo) throw new Error("Elija un capítulo o indique uno nuevo");
      await post(`/api/capex/${p.id}/partidas/desde-base`, { precio_ids: sel.map((x) => x.id), capitulo, capitulo_nombre });
      toast("Partidas añadidas: indique sus cantidades"); recarga();
    }, "Añadir");
  });
}

// Buscador de la base de precios con selección múltiple (onElegir recibe las partidas marcadas)
async function buscarPrecios(onElegir) {
  const bases = await get("/api/capex/bases/lista");
  if (!bases.length) return toast("No hay bases de precios: impórtela en CAPEX → Base de precios (BC3)", true);
  const elegidas = new Map();
  const f = form("Base de precios", [
    { html: `<div class="toolbar"><select id="bpB">${bases.length > 1 ? '<option value="">Todas las bases</option>' : ""}${bases.map((b) => `<option value="${b.id}">${esc(b.nombre)}</option>`).join("")}</select>
      <input id="bpQ" type="search" placeholder="Buscar: alicatado gres, demolición tabique, LAD010…" style="flex:1"></div><div id="bpR" class="cx-buscar"><p class="muted">Escriba al menos 3 letras.</p></div><p id="bpN" class="muted"></p>` },
  ], {}, async () => { if (!elegidas.size) throw new Error("Marque alguna partida"); setTimeout(() => onElegir([...elegidas.values()]), 0); }, "Añadir las marcadas");
  $("#modal").classList.add("ancho");
  const busca = debounce(async () => {
    const q = $("#bpQ", f).value.trim();
    if (q.length < 3) return;
    const r = await get("/api/capex/precios/buscar", { q, base_id: $("#bpB", f).value });
    $("#bpR", f).innerHTML = r.length ? `<table><tbody>${r.map((x) => `<tr><td><input type="checkbox" data-p="${x.id}" ${elegidas.has(x.id) ? "checked" : ""}></td>
      <td><b>${esc(x.codigo)}</b></td><td>${esc(x.resumen)}<div class="muted peq">${esc(x.capitulo || "")}</div></td><td>${esc(x.unidad || "")}</td><td class="num">${num2(x.precio)}</td></tr>`).join("")}</tbody></table>` : '<p class="muted">Sin resultados.</p>';
    $("#bpR", f).querySelectorAll("[data-p]").forEach((c) => (c.onchange = () => { const x = r.find((z) => z.id === Number(c.dataset.p)); c.checked ? elegidas.set(x.id, x) : elegidas.delete(x.id); $("#bpN", f).textContent = `${elegidas.size} marcada(s)`; }));
  }, 300);
  $("#bpQ", f).oninput = busca; $("#bpB", f).onchange = busca; $("#bpQ", f).focus();
}

// ---- documentos del proyecto
function capexDocumentos(cx, D, recarga, C) {
  const g = D.gestionar;
  cx.innerHTML = `${g ? '<div class="toolbar"><button class="btn primary" id="sub">Subir documentos</button><span class="spacer"></span><span class="muted peq">Los marcados «Va a licitación» se envían a los contratistas.</span></div>' : ""}<div id="dt"></div>`;
  table($("#dt", cx), [
    { k: "etiqueta_nombre", t: "Tipo" }, { k: "nombre", t: "Documento", f: (v, d) => `${esc(v)}${d.notas ? `<div class="muted peq">${esc(d.notas)}</div>` : ""}` },
    { k: "tamano", t: "Tamaño", num: true, f: (v) => `${(v / 1048576).toFixed(1).replace(".", ",")} MB` },
    { k: "licitacion", t: "Va a licitación", f: (v, d) => (g ? `<input type="checkbox" data-lic="${d.id}" ${v ? "checked" : ""}>` : v ? "Sí" : "") },
    { k: "subido", t: "Subido", f: fdt },
  ], D.documentos, (d) => [["Ver", () => (d.mime.startsWith("image/") || d.mime === "application/pdf" ? abrirFichero(`/api/capex/documentos/${d.id}`) : run(() => download("GET", `/api/capex/documentos/${d.id}`))), "primary"],
    g && ["Borrar", async () => { if (confirm(`¿Borrar ${d.nombre}?`)) { await run(() => api("DELETE", `/api/capex/documentos/${d.id}`)); recarga(); } }, "danger"]]);
  cx.querySelectorAll("[data-lic]").forEach((c) => (c.onchange = () => run(() => put(`/api/capex/documentos/${c.dataset.lic}`, { licitacion: c.checked }), "Guardado")));
  if (g) $("#sub", cx).onclick = () => form("Subir documentos", [
    { k: "etiqueta", t: "Tipo", type: "select", req: true, options: Object.entries(C.etiquetas) },
    { html: '<label class="wide">Ficheros (PDF, fotos, planos DWG/DXF, Word, Excel) *<input type="file" name="f" multiple required></label>' },
    { k: "notas", t: "Notas", wide: true }, { k: "licitacion", t: "Enviar a los contratistas con la petición de ofertas", type: "checkbox", def: true, wide: true },
  ], {}, async (d, f) => {
    const fd = new FormData(); [...f.elements.f.files].forEach((x) => fd.append("ficheros", x));
    fd.append("etiqueta", d.etiqueta); fd.append("licitacion", d.licitacion ? "true" : "false"); if (d.notas) fd.append("notas", d.notas);
    await upload(`/api/capex/${D.proyecto.id}/documentos`, fd); toast("Documentos subidos"); recarga();
  }, "Subir");
}

// ---- licitación ciega
function capexLicitacion(cx, D, recarga) {
  const p = D.proyecto, g = D.gestionar, puede = g && ["definicion", "licitacion"].includes(p.estado);
  const lic = D.licitaciones.at(-1);
  const invs = D.licitaciones.flatMap((l) => l.invitaciones.map((i) => ({ ...i, licitacion: l })));
  cx.innerHTML = `<div class="toolbar">${puede ? `<button class="btn primary" id="pedir">${lic && lic.estado === "abierta" ? "Invitar a más contratistas" : "Pedir ofertas"}</button>` : ""}
    ${g && lic && lic.estado === "abierta" && invs.some((i) => i.oferta?.estado === "enviada") ? '<button class="btn" id="cerrar">Cerrar recepción y comparar</button>' : ""}<span class="spacer"></span>
    ${lic ? `<span class="muted">Plazo: <b>${fdate(lic.fecha_limite)}</b> · ${lic.estado === "abierta" ? "abierta" : "cerrada"}</span>` : ""}</div>
    <p class="muted">Licitación ciega: cada contratista recibe por correo un enlace personal (sin usuario) y una plantilla Excel protegida con las mediciones y <b>sin los precios base</b>. Puede escribir los precios en la web o devolver el Excel. Se registra cuándo abre el enlace y descarga la documentación.</p><div id="it"></div>`;
  table($("#it", cx), [
    { k: "proveedor", t: "Contratista", f: (v, i) => `<b>${esc(v)}</b><div class="muted peq">${esc(i.email || "sin correo")}</div>` },
    { k: "enviado", t: "Invitación", f: (v, i) => (v ? `enviada ${fdt(v)}` : `<span class="error">${esc(i.envio_error || "no enviada")}</span>`) },
    { k: "aperturas", t: "Seguimiento", f: (v, i) => (i.abierto_en ? `abierto ${v} vez/veces<div class="muted peq">1.ª ${fdt(i.abierto_en)} · ${i.descargas} descarga(s)</div>` : '<span class="muted">sin abrir</span>') },
    { k: "oferta", t: "Oferta", f: (o) => (!o ? '<span class="muted">—</span>' : `<span class="badge ${o.estado === "enviada" ? "b-vigente" : "b-borrador"}">${o.estado === "enviada" ? "enviada" : "borrador"}</span> ${eur(o.pem)}<div class="muted peq">${o.enviada_en ? fdt(o.enviada_en) : ""}${o.faltan ? ` · faltan ${o.faltan} precio(s)` : ""}${o.origen !== "portal" ? ` · ${o.origen}` : ""}</div>`) },
  ], invs, (i) => [
    g && i.licitacion.estado === "abierta" && ["Reenviar", async () => { const r = await run(() => post(`/api/capex/invitaciones/${i.id}/reenviar`)); resultadoInvitaciones([r]); recarga(); }],
    ["Excel ciego", () => run(() => download("GET", `/api/capex/invitaciones/${i.id}/excel`))],
    g && ["licitacion", "adjudicacion"].includes(p.estado) && ["Subir su Excel", () => form(`Oferta recibida de ${i.proveedor}`, [
      { html: '<p class="muted">Suba la plantilla Excel que el contratista ha devuelto por correo: se leen sus precios y queda como oferta enviada.</p><label class="wide">Fichero .xlsx *<input type="file" name="f" accept=".xlsx" required></label>' }], {},
    async (d, f) => { const fd = new FormData(); fd.append("fichero", f.elements.f.files[0]); const r = await upload(`/api/capex/invitaciones/${i.id}/oferta-excel`, fd); toast(`${r.precios} precios leídos`); recarga(); }, "Subir")],
  ]);
  if ($("#cerrar", cx)) $("#cerrar", cx).onclick = async () => { if (confirm("¿Cerrar la recepción de ofertas y pasar al comparativo? Los contratistas ya no podrán modificarlas.")) { await run(() => post(`/api/capex/licitacion/${lic.id}/cerrar`)); S.capexTab = "comparativo"; recarga(); } };
  if ($("#pedir", cx)) $("#pedir", cx).onclick = async () => {
    const provs = (await get("/api/proveedores")).filter((s) => !invs.some((i) => i.supplier_id === s.id));
    const docs = D.documentos.filter((d) => d.licitacion);
    const plazo = iso(new Date(Date.now() + 14 * 864e5));
    form(lic && lic.estado === "abierta" ? "Invitar a más contratistas" : "Pedir ofertas", [
      { html: `<input type="search" id="fprov" placeholder="Filtrar por nombre o actividad" style="width:100%">` },
      { k: "proveedor_ids", t: "Contratistas", type: "checks", options: provs.map((s) => [String(s.id), `${s.nombre}${s.actividad ? ` · ${s.actividad}` : ""}${s.email ? "" : " (sin correo)"}`]) },
      { k: "fecha_limite", t: "Plazo de presentación", type: "date", req: true, def: lic?.fecha_limite || plazo },
      { k: "mensaje", t: "Mensaje para los contratistas (visita de obra, condiciones…)", type: "textarea", wide: true, def: lic?.mensaje || "" },
      { html: `<p class="muted">Se adjuntan: plantilla Excel ciega${docs.length ? ` y ${docs.length} documento(s): ${docs.map((d) => esc(d.nombre)).join(", ")}` : " (no hay documentos marcados para licitación)"}. Si pesan más de 15 MB, se descargan desde el enlace.</p>` },
    ], {}, async (d) => {
      if (!d.proveedor_ids.length) throw new Error("Marque al menos un contratista");
      const r = await post(`/api/capex/${p.id}/licitacion`, { proveedor_ids: d.proveedor_ids.map(Number), fecha_limite: d.fecha_limite, mensaje: d.mensaje });
      setTimeout(() => resultadoInvitaciones(r.enviados), 0); recarga();
    }, "Enviar invitaciones");
    $("#fprov").oninput = (e) => { const q = normaliza(e.target.value); document.querySelectorAll('#modalForm input[name="proveedor_ids"]').forEach((c) => (c.closest("label").style.display = normaliza(c.closest("label").textContent).includes(q) ? "" : "none")); };
  };
}
function resultadoInvitaciones(res) {
  form("Invitaciones", [{ html: `<ul class="envios">${res.map((r) => `<li><b>${esc(r.proveedor)}</b> · ${r.ok ? `correo enviado a ${esc(r.email)} ✓` : `<span class="error">${esc(r.error || "no enviado")}</span>`}
    ${r.whatsapp ? ` <a class="btn sm" href="${esc(r.whatsapp)}" target="_blank" rel="noopener">Avisar por WhatsApp</a>` : ""}</li>`).join("")}</ul>` }], {}, async () => {}, "Cerrar");
}

// ---- comparativo (mapa de calor) y adjudicación
async function capexComparativo(cx, D, recarga, C) {
  const p = D.proyecto;
  const R = await get(`/api/capex/${p.id}/comparativo`);
  if (!R.ofertas.length) { cx.innerHTML = '<p class="muted">Todavía no hay ofertas enviadas.</p>'; return; }
  const o = R.ofertas, col = (n) => `background:${R.colores[n] || "#fff"}`;
  const celda = (c, extra = "") => (c.precio == null && c.importe == null ? `<td class="num" style="${col("sin_precio")}">—</td>`
    : `<td class="num" style="${col(c.nivel)}" title="${esc(R.niveles[c.nivel] || "")}${c.desviacion != null ? ` · ${pct(c.desviacion)}` : ""}">${num2(c.precio ?? c.importe)}${extra}</td>`);
  cx.innerHTML = `<div class="toolbar"><span class="aus-leyenda">${Object.entries(R.niveles).filter(([k]) => k !== "sin_base").map(([k, v]) => `<span class="aus-ley" style="${col(k)};border:1px solid #ddd">${esc(v)}</span>`).join("")}</span><span class="spacer"></span>
    <button class="btn" id="pdf">PDF del comparativo</button></div>
    <div class="table-wrap no-encajar"><table class="cx-cmp"><thead><tr><th>Resumen</th><th class="num">Base</th>${o.map((x) => `<th class="num">${esc(x.proveedor)}</th>`).join("")}</tr></thead><tbody>
      <tr><td>Ejecución material</td><td class="num">${num2(R.base.pem)}</td>${o.map((x) => `<td class="num" style="${col(x.nivel)}">${num2(x.pem)}</td>`).join("")}</tr>
      <tr><td><b>PBL (PEM + GG + BI)</b></td><td class="num"><b>${num2(R.base.pbl)}</b></td>${o.map((x) => `<td class="num"><b>${num2(x.pbl)}</b><div class="peq">${pct(x.desviacion)}</div></td>`).join("")}</tr>
      <tr><td>Partidas sin precio · plazo</td><td></td>${o.map((x) => `<td class="num">${x.faltan ? `<span class="error">${x.faltan}</span>` : "0"} · ${x.plazo_dias ? `${x.plazo_dias} días` : "—"}</td>`).join("")}</tr>
      ${o.some((x) => x.notas) ? `<tr><td>Observaciones</td><td></td>${o.map((x) => `<td class="peq">${esc(x.notas || "")}</td>`).join("")}</tr>` : ""}
      <tr class="cx-sep"><th>Capítulo / partida (precio unitario)</th><th class="num">Base</th>${o.map((x) => `<th class="num">${esc(x.proveedor)}</th>`).join("")}</tr>
      ${R.capitulos.map((c) => `<tr class="cx-cap"><td><b>${esc(c.capitulo)} ${esc(c.nombre)}</b></td><td class="num"><b>${num2(c.importe_base)}</b></td>${o.map((x) => { const v = c.ofertas[x.bid_id]; return `<td class="num" style="${col(v.nivel)}"><b>${num2(v.importe)}</b>${v.completo ? "" : " *"}${c.mejor === x.bid_id ? " ★" : ""}</td>`; }).join("")}</tr>
        ${R.partidas.filter((f) => f.capitulo === c.capitulo).map((f) => `<tr><td class="peq">${esc(f.codigo || "")} ${esc(f.descripcion.split("\n")[0])}<span class="muted"> · ${f.cantidad.toLocaleString("es-ES")} ${esc(f.unidad || "")}</span></td><td class="num">${num2(f.precio_base)}</td>${o.map((x) => celda(f.ofertas[x.bid_id])).join("")}</tr>`).join("")}`).join("")}
    </tbody></table></div><p class="muted peq">★ mejor oferta completa del capítulo · * faltan precios · pase el ratón por una casilla para ver la desviación.</p>
    <div id="adj"></div>`;
  $("#pdf", cx).onclick = () => abrirFichero(`/api/capex/${p.id}/comparativo.pdf`);
  if (!D.gestionar || !["licitacion", "adjudicacion"].includes(p.estado)) {
    $("#adj", cx).innerHTML = D.adjudicaciones.length ? `<h4>Adjudicación</h4><ul>${D.adjudicaciones.filter((a) => a.estado !== "anulada").map((a) => `<li><b>${esc(a.proveedor)}</b> · ${a.capitulos.length ? esc(a.capitulos.join(", ")) : "obra completa"} · ${eur(a.importe)} <span class="badge ${a.estado === "aprobada" ? "b-vigente" : a.estado === "rechazada" ? "b-anulado" : "b-pendiente"}">${esc(a.estado)}</span></li>`).join("")}</ul>` : "";
    return;
  }
  // adjudicación: por cada capítulo, la contrata (por defecto la mejor oferta completa)
  $("#adj", cx).innerHTML = `<fieldset><legend>Adjudicación (obra completa o por capítulos)</legend>
    <div class="toolbar">${o.filter((x) => x.completa).map((x) => `<button type="button" class="btn sm" data-todo="${x.bid_id}">Todo a ${esc(x.proveedor)}</button>`).join("")}</div>
    <table class="cx-adj">${R.capitulos.map((c) => `<tr><td>${esc(c.capitulo)} ${esc(c.nombre)}</td><td><select data-cap="${esc(c.capitulo)}"><option value="">— sin adjudicar —</option>${o.filter((x) => c.ofertas[x.bid_id].completo).map((x) => `<option value="${x.bid_id}" ${c.mejor === x.bid_id ? "selected" : ""}>${esc(x.proveedor)} · ${num2(c.ofertas[x.bid_id].importe)} €</option>`).join("")}</select></td></tr>`).join("")}</table>
    <p>Importe a adjudicar (PEM + GG + BI, sin IVA): <b id="adjTot"></b> <span id="adjAviso"></span></p>
    <label>Nota / justificación (va en el correo de aprobación)<textarea id="adjNota"></textarea></label>
    <div class="toolbar"><button class="btn" id="reabrir">Reabrir licitación</button><span class="spacer"></span><button class="btn primary" id="adjudicar">Adjudicar</button></div></fieldset>`;
  const sels = [...cx.querySelectorAll("[data-cap]")];
  const calc = () => {
    const pem = sels.reduce((s, x) => s + (x.value ? R.capitulos.find((c) => c.capitulo === x.dataset.cap).ofertas[x.value].importe : 0), 0);
    const tot = Math.round(pem * (1 + (p.gg_pct + p.bi_pct) / 100) * 100) / 100;
    $("#adjTot", cx).textContent = eur(tot);
    $("#adjAviso", cx).innerHTML = tot > C.umbral ? `<span class="badge b-urgente">Supera ${eur(C.umbral)}: se enviará a la Dirección General para su aprobación</span>` : "";
  };
  sels.forEach((x) => (x.onchange = calc)); calc();
  cx.querySelectorAll("[data-todo]").forEach((b) => (b.onclick = () => { sels.forEach((x) => (x.value = b.dataset.todo)); calc(); }));
  $("#reabrir", cx).onclick = async () => { if (confirm("¿Reabrir la licitación para que los contratistas puedan modificar o enviar ofertas?")) { await run(() => post(`/api/capex/${p.id}/estado`, { estado: "licitacion" })); S.capexTab = "licitacion"; recarga(); } };
  $("#adjudicar", cx).onclick = async () => {
    const lotes = {};
    sels.forEach((x) => { if (x.value) (lotes[x.value] = lotes[x.value] || []).push(x.dataset.cap); });
    if (!Object.keys(lotes).length) return toast("Elija al menos un capítulo", true);
    const sin = sels.filter((x) => !x.value).length;
    if (!confirm(`¿Adjudicar por ${$("#adjTot", cx).textContent}?${sin ? `\n${sin} capítulo(s) quedan sin adjudicar.` : ""}`)) return;
    const r = await run(() => post(`/api/capex/${p.id}/adjudicar`, { lotes: Object.entries(lotes).map(([b, caps]) => ({ bid_id: Number(b), capitulos: caps })), nota: $("#adjNota", cx).value || null }));
    if (r.requiere_aprobacion) {
      S.capexTab = "aprobacion";
      form("Pendiente de aprobación", [{ html: `<p>La adjudicación (${eur(r.total)}) supera ${eur(C.umbral)} y se ha enviado a la Dirección General:</p><ul>${r.aprobacion.map((a) => `<li>${esc(a.email)}: ${a.ok ? "correo enviado ✓" : `<span class="error">${esc(a.error || "no enviado")}</span>`}</li>`).join("")}</ul><p class="muted">La obra queda bloqueada hasta que apruebe. Recibirá un correo con la decisión.</p>` }], {}, async () => {}, "Cerrar");
    } else toast(`Adjudicado por ${eur(r.total)}`);
    recarga();
  };
}

// ---- aprobación de la Dirección General
function capexAprobacion(cx, D, recarga, C) {
  const p = D.proyecto, pend = D.aprobaciones.some((a) => a.estado === "pendiente");
  cx.innerHTML = `<p class="muted">Las adjudicaciones de más de ${eur(C.umbral)} (sin IVA) las aprueba la Dirección General (${C.aprobadores.map(esc).join(", ")}) con los botones del correo, sin entrar en el PMS, o desde aquí. Queda la fecha y hora de la decisión.</p>
    ${D.aprobar ? '<div class="toolbar"><button class="btn primary" id="si">Aprobar</button><button class="btn danger" id="no">Rechazar</button></div>' : ""}
    ${D.gestionar && pend ? '<div class="toolbar"><button class="btn" id="re">Reenviar el correo de aprobación</button></div>' : ""}<div id="at"></div>`;
  table($("#at", cx), [
    { k: "email", t: "Dirección General" }, { k: "importe", t: "Importe", num: true, f: eur },
    { k: "estado", t: "Estado", f: (v) => `<span class="badge ${v === "aprobada" ? "b-vigente" : v === "rechazada" ? "b-anulado" : v === "pendiente" ? "b-pendiente" : ""}">${esc(v)}</span>` },
    { k: "enviada_en", t: "Correo", f: (v, a) => (v ? fdt(v) : `<span class="error">${esc(a.envio_error || "")}</span>`) },
    { k: "decidido_en", t: "Decisión", f: (v, a) => (v ? `${fdt(v)} · ${a.canal === "correo" ? "desde el correo" : "desde el PMS"}${a.comentario ? `<div class="muted peq">${esc(a.comentario)}</div>` : ""}` : "") },
  ], D.aprobaciones);
  const decide = (decision) => form(decision === "aprobar" ? "Aprobar la adjudicación" : "Rechazar la adjudicación", [
    { k: "comentario", t: decision === "aprobar" ? "Comentario (opcional)" : "Motivo del rechazo", type: "textarea", req: decision === "rechazar", wide: true }], {},
  async (d) => { await post(`/api/capex/${p.id}/aprobacion`, { decision, comentario: d.comentario }); toast(decision === "aprobar" ? "Adjudicación aprobada" : "Adjudicación rechazada"); recarga(); }, decision === "aprobar" ? "Aprobar" : "Rechazar");
  if ($("#si", cx)) { $("#si", cx).onclick = () => decide("aprobar"); $("#no", cx).onclick = () => decide("rechazar"); }
  if ($("#re", cx)) $("#re", cx).onclick = async () => { const r = await run(() => post(`/api/capex/${p.id}/aprobacion/reenviar`)); toast(r.every((x) => x.ok) ? "Correo reenviado" : "No se ha podido enviar el correo", !r.every((x) => x.ok)); recarga(); };
}

// ---- plantillas «CAPEX tipo»
V.capexplantillas = async (el) => {
  const C = await catCapex();
  el.innerHTML = `<div class="toolbar"><span class="spacer"></span><button class="btn primary" id="new">Nueva plantilla</button></div>
    <p class="muted">Un «CAPEX tipo» (reforma integral de baño, panelado de puertas…) guarda capítulos, partidas estándar con su precio y documentos base (planos, pliegos). Al crear un proyecto se carga con un clic y solo hay que ajustar las mediciones. La forma más rápida de crearla: abrir un proyecto y pulsar «Guardar como plantilla».</p><div id="t"></div>`;
  const load = async () => table($("#t", el), [
    { k: "nombre", t: "Plantilla", f: (v, t) => `<b>${esc(v)}</b>${t.descripcion ? `<div class="muted peq">${esc(t.descripcion)}</div>` : ""}` },
    { k: "capitulos", t: "Capítulos", f: (v) => esc(v.join(" · ")) }, { k: "n_partidas", t: "Partidas", num: true },
    { k: "pem", t: "PEM tipo", num: true, f: eur }, { k: "documentos", t: "Docs.", num: true, f: (v) => v.length },
    { k: "activa", t: "Estado", f: (v) => (v ? "Activa" : '<span class="muted">Archivada</span>') },
  ], await get("/api/capex/plantillas/lista"), (t) => [
    ["Partidas", () => editarPlantilla(t, load), "primary"],
    ["Documentos", () => docsPlantilla(t, load, C)],
    [t.activa ? "Archivar" : "Activar", async () => { await run(() => put(`/api/capex/plantillas/lista/${t.id}`, { activa: !t.activa })); load(); }],
    ["Borrar", async () => { if (confirm(`¿Borrar la plantilla ${t.nombre}?`)) { await run(() => api("DELETE", `/api/capex/plantillas/lista/${t.id}`)); load(); } }, "danger"],
  ]);
  $("#new", el).onclick = () => form("Nueva plantilla", [{ k: "nombre", t: "Nombre", req: true, wide: true }, { k: "descripcion", t: "Descripción", type: "textarea", wide: true }], {},
    async (d) => { const t = await post("/api/capex/plantillas/lista", d); load(); setTimeout(() => editarPlantilla(t, load), 0); }, "Crear");
  load();
};
function editarPlantilla(t, reload) {
  let filas = (t.partidas || []).map((x) => ({ ...x }));
  const f = form(`Partidas · ${t.nombre}`, [{ html: `<div class="toolbar"><button type="button" class="btn sm" id="ptAdd">+ Partida</button><button type="button" class="btn sm" id="ptBase">Desde base de precios</button><span class="spacer"></span><span class="muted peq" id="ptTot"></span></div><div id="ptG"></div>` }], {},
    async () => { await put(`/api/capex/plantillas/lista/${t.id}`, { partidas: filas.filter((x) => x.descripcion) }); toast("Plantilla guardada"); reload(); });
  $("#modal").classList.add("ancho");
  const pinta = () => {
    $("#ptG", f).innerHTML = `<table class="cx-grid"><thead><tr><th>Cap.</th><th>Nombre capítulo</th><th>Código</th><th>Descripción</th><th>Ud</th><th class="num">Cant.</th><th class="num">Precio</th><th></th></tr></thead><tbody>
      ${filas.map((x, i) => `<tr data-i="${i}"><td><input data-f="capitulo" value="${esc(x.capitulo || "")}" class="cx-ud"></td><td><input data-f="capitulo_nombre" value="${esc(x.capitulo_nombre || "")}"></td>
        <td><input data-f="codigo" value="${esc(x.codigo || "")}" class="cx-cod"></td><td><textarea data-f="descripcion" rows="1">${esc(x.descripcion || "")}</textarea></td>
        <td><input data-f="unidad" value="${esc(x.unidad || "")}" class="cx-ud"></td><td><input data-f="cantidad" type="number" step="any" value="${x.cantidad ?? 0}" class="cx-num"></td>
        <td><input data-f="precio" type="number" step="0.01" value="${x.precio ?? 0}" class="cx-num"></td><td><button type="button" class="btn sm danger" data-x="${i}">✕</button></td></tr>`).join("")}</tbody></table>`;
    $("#ptTot", f).textContent = `${filas.length} partida(s) · PEM ${eur(filas.reduce((s, x) => s + (Number(x.cantidad) || 0) * (Number(x.precio) || 0), 0))}`;
    $("#ptG", f).querySelectorAll("[data-f]").forEach((i) => (i.onchange = () => { const x = filas[i.closest("tr").dataset.i]; x[i.dataset.f] = ["cantidad", "precio"].includes(i.dataset.f) ? Number(i.value || 0) : i.value; pinta(); }));
    $("#ptG", f).querySelectorAll("[data-x]").forEach((b) => (b.onclick = () => { filas.splice(Number(b.dataset.x), 1); pinta(); }));
  };
  const ultimo = () => filas.at(-1) || { capitulo: "01", capitulo_nombre: "" };
  $("#ptAdd", f).onclick = () => { filas.push({ capitulo: ultimo().capitulo, capitulo_nombre: ultimo().capitulo_nombre, descripcion: "", cantidad: 0, precio: 0 }); pinta(); };
  $("#ptBase", f).onclick = () => {
    const guardadas = filas;
    buscarPrecios((sel) => { setTimeout(() => { filas = guardadas.concat(sel.map((x) => ({ capitulo: ultimo().capitulo, capitulo_nombre: ultimo().capitulo_nombre, codigo: x.codigo, descripcion: x.resumen, unidad: x.unidad, cantidad: 0, precio: x.precio })));
      editarPlantilla({ ...t, partidas: filas }, reload); }, 0); });
  };
  pinta();
}
function docsPlantilla(t, reload, C) {
  const f = form(`Documentos base · ${t.nombre}`, [
    { html: t.documentos.length ? `<ul>${t.documentos.map((d) => `<li>${esc(d.etiqueta_nombre)}: <a href="#" data-ver="${d.id}">${esc(d.nombre)}</a> <button type="button" class="btn sm danger" data-del="${d.id}">Borrar</button></li>`).join("")}</ul>` : '<p class="muted">Sin documentos.</p>' },
    { k: "etiqueta", t: "Tipo", type: "select", req: true, options: Object.entries(C.etiquetas) },
    { html: '<label class="wide">Ficheros *<input type="file" name="f" multiple required></label>' },
  ], {}, async (d, fm) => {
    const fd = new FormData(); [...fm.elements.f.files].forEach((x) => fd.append("ficheros", x)); fd.append("etiqueta", d.etiqueta);
    await upload(`/api/capex/plantillas/lista/${t.id}/documentos`, fd); toast("Documentos subidos"); reload();
  }, "Subir");
  f.querySelectorAll("[data-ver]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); abrirFichero(`/api/capex/documentos/${a.dataset.ver}`); }));
  f.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { if (confirm("¿Borrar el documento?")) { await run(() => api("DELETE", `/api/capex/documentos/${b.dataset.del}`)); $("#modal").close(); reload(); } }));
}

// ---- base de precios FIEBDC-3
V.capexprecios = async (el) => {
  el.innerHTML = `<div class="toolbar"><input type="search" id="q" placeholder="Buscar en las bases: alicatado, demolición, LAD010…" style="flex:1"><span class="spacer"></span><button class="btn primary" id="imp">Importar base (.bc3 / .zip)</button></div>
    <p class="muted">Bases de precios de construcción en formato FIEBDC-3 (.bc3). Las públicas se descargan gratis, por ejemplo la Base de Costes de la Construcción de Andalucía (BCCA) o la del IVE (Comunidad Valenciana); también vale cualquier .bc3 exportado de Presto o Arquímedes. Sus partidas se añaden a los proyectos desde «Añadir desde base de precios».</p>
    <div id="b"></div><div id="r"></div>`;
  const load = async () => table($("#b", el), [
    { k: "nombre", t: "Base", f: (v) => `<b>${esc(v)}</b>` }, { k: "fichero", t: "Fichero" }, { k: "partidas", t: "Partidas", num: true }, { k: "importado", t: "Importada", f: fdt },
  ], await get("/api/capex/bases/lista"), (b) => [["Borrar", async () => { if (confirm(`¿Borrar la base ${b.nombre}?`)) { await run(() => api("DELETE", `/api/capex/bases/lista/${b.id}`)); load(); } }, "danger"]]);
  $("#imp", el).onclick = () => form("Importar base de precios", [
    { k: "nombre", t: "Nombre (p. ej. BCCA 2025)", req: true, wide: true },
    { html: '<label class="wide">Fichero .bc3 o .zip *<input type="file" name="f" accept=".bc3,.zip" required></label><p class="muted">Una base completa puede tardar un minuto en importarse.</p>' },
  ], {}, async (d, f) => {
    const fd = new FormData(); fd.append("fichero", f.elements.f.files[0]); fd.append("nombre", d.nombre);
    toast("Importando…"); const r = await upload("/api/capex/bases/lista", fd); toast(`${r.partidas} partidas importadas`); load();
  }, "Importar");
  $("#q", el).oninput = debounce(async () => {
    const q = $("#q", el).value.trim();
    if (q.length < 3) { $("#r", el).innerHTML = ""; return; }
    table($("#r", el), [{ k: "codigo", t: "Código", f: (v) => `<b>${esc(v)}</b>` }, { k: "resumen", t: "Partida", f: (v, x) => `${esc(v)}<div class="muted peq">${esc(x.capitulo || "")}</div>` },
      { k: "unidad", t: "Ud" }, { k: "precio", t: "Precio €", num: true, f: num2 }], await get("/api/capex/precios/buscar", { q }));
  }, 300);
  load();
};

// ------------------------------------------------------------------ INVERGESTION (fase 4, 13/10/2026)
// Abre gestión en una pestaña nueva. La dirección (con el pase firmado, de un solo uso) la da el servidor.
async function abrirGestion(destino, assetId, unitId) {
  const w = window.open("about:blank", "_blank");
  try {
    const r = await get("/api/gestion/pase", { destino, asset_id: assetId, unit_id: unitId });
    if (w) { w.opener = null; w.location.href = r.url; } else location.href = r.url;
  } catch (e) { if (w) w.close(); toast(e.message); }
}
const CANAL_TXT = { directo: "Directo", booking: "Booking", airbnb: "Airbnb", expedia: "Expedia", web: "Web propia", agencia: "Agencia", otros: "Otros" };
const EV_TXT = { "reserva.creada": "Reserva nueva", "reserva.modificada": "Reserva modificada", "reserva.cancelada": "Reserva cancelada", checkout: "Check-out", "incidencia.reportada": "Incidencia", "liquidacion.periodo": "Liquidación",
  "reserva.ampliada": "Ampliación", "fianza.cobrada": "Fianza cobrada", "fianza.devolucion": "Fianza devuelta", "fianza.transferida": "Transferencia de fianza", "caja.cierre": "Cierre de caja", "incidencia.cerrada": "Incidencia cerrada", "kpi.diario": "Indicadores del día" };
V.gestion = async (el) => {
  const d = await get("/api/gestion/estado");
  const c = d.cuenta || {};
  const mesAnt = (() => { const x = new Date(); x.setDate(0); return iso(x).slice(0, 7); })();
  el.innerHTML = `<div class="kpis">
      <div class="kpi ${d.configurado ? "" : "mal"}"><b>${d.configurado ? "Conectada" : "Sin clave"}</b><span>Avisos a gestión</span></div>
      <div class="kpi ${d.sso ? "" : "mal"}"><b>${d.sso ? "Directo" : "Con contraseña"}</b><span>Botón «Gestión»</span></div>
      <div class="kpi"><b>${c.enviado || 0}</b><span>Avisos entregados</span></div>
      <div class="kpi ${c.pendiente ? "mal" : ""}"><b>${c.pendiente || 0}</b><span>Pendientes</span></div>
      <div class="kpi ${c.aviso ? "mal" : ""}"><b>${c.aviso || 0}</b><span>Sin entregar tras varios intentos</span></div></div>
    ${d.configurado ? "" : '<p class="aviso-amarillo">Falta la clave PMS_EVENTOS_SECRET en el servidor: los avisos se guardan y se mandarán en cuanto esté puesta.</p>'}
    ${d.v2 ? '<p class="muted">Avisos nuevos (fianzas, ampliaciones, cierres de caja, cierre de incidencias e indicadores diarios): activados.</p>' : `<p class="aviso-amarillo">Avisos nuevos (fianzas, ampliaciones, cierres de caja, cierre de incidencias e indicadores diarios): <b>en espera</b> hasta que gestión los sepa recibir (${d.v2_en_espera || 0} guardados). Se activan con PMS_GESTION_EVENTOS_V2=1 en el servidor y salen todos los guardados.</p>`}
    <div class="card"><h3>Comisión de cada canal (% del bruto)</h3><p class="muted">Se usa para calcular el neto de la liquidación mensual que recibe gestión. La diferencia real se ve al conciliar con el banco.</p><div id="gcom"></div></div>
    <div class="card"><h3>Liquidación mensual</h3><p class="muted">Si el activo tiene marcado «Mandar sola cada mes», el día 2 se manda la del mes anterior. Aquí se puede ver antes o mandar a mano (gestión no pisa una producción metida a mano sin enseñar las diferencias). Ojo: sale de las reservas del PMS; si no están todas, la cifra saldrá corta.</p>
      <div class="toolbar"><select id="gla">${d.activos.map((a) => `<option value="${a.id}">${esc(a.nombre)}</option>`).join("")}</select><input id="glp" type="month" value="${mesAnt}">
      <button class="btn" id="glv">Ver</button><button class="btn primary" id="gle">Mandar a gestión</button></div><div id="glr"></div></div>
    <div class="card"><h3>Últimos avisos a gestión</h3><div class="toolbar"><button class="btn" id="grt">Reintentar ahora los pendientes</button></div><div id="gev"></div></div>`;
  $("#gcom", el).innerHTML = `<div style="overflow-x:auto"><table class="tabla"><thead><tr><th>Activo</th>${d.canales.map((k) => `<th class="num">${CANAL_TXT[k] || k}</th>`).join("")}<th>Mandar sola cada mes</th><th></th></tr></thead><tbody>${d.activos.map((a) => `<tr data-a="${a.id}"><td>${esc(a.nombre)}</td>${d.canales.map((k) => `<td class="num"><input type="number" step="0.1" min="0" max="50" style="width:70px" data-k="${k}" value="${a.comisiones[k] ?? ""}"></td>`).join("")}<td><input type="checkbox" data-auto ${a.comisiones._auto ? "checked" : ""}></td><td><button class="btn sm" data-g>Guardar</button></td></tr>`).join("")}</tbody></table></div>`;
  $("#gcom", el).querySelectorAll("[data-g]").forEach((b) => (b.onclick = () => { const tr = b.closest("tr"); const com = {};
    tr.querySelectorAll("input[data-k]").forEach((i) => { if (i.value !== "") com[i.dataset.k] = Number(i.value); });
    run(() => api("PUT", `/api/gestion/activos/${tr.dataset.a}/comisiones`, { comisiones: com, auto: $("[data-auto]", tr).checked }), "Comisiones guardadas"); }));
  const pinta = (l) => { $("#glr", el).innerHTML = `<p><b>${esc(l.activo)} · ${esc(l.periodo)}</b> · ${l.reservas} reservas · ${l.noches_ocupadas} noches de ${l.noches_disponibles} (${l.ocupacion ?? 0} %)</p>`; const t = document.createElement("div"); $("#glr", el).appendChild(t);
    table(t, [{ k: "canal", t: "Canal", f: (v) => CANAL_TXT[v] || v }, { k: "reservas", t: "Reservas" }, { k: "noches", t: "Noches" }, { k: "bruto", t: "Bruto", f: eur }, { k: "iva", t: "IVA", f: eur }, { k: "comision_pct", t: "% com." }, { k: "comision", t: "Comisión", f: eur }, { k: "neto", t: "Neto", f: eur }], l.canales); };
  const lq = () => ({ asset_id: Number($("#gla", el).value), periodo: $("#glp", el).value });
  $("#glv", el).onclick = () => run(() => post("/api/gestion/liquidacion/previa", lq())).then((l) => l && pinta(l));
  $("#gle", el).onclick = () => confirm("¿Mandar la liquidación de ese mes a gestión?") && run(() => post("/api/gestion/liquidacion/enviar", lq()), "Liquidación en la cola de envío").then(() => go("gestion"));
  $("#grt", el).onclick = () => run(() => post("/api/gestion/cola/reintentar"), "Reintento lanzado").then(() => go("gestion"));
  table($("#gev", el), [{ k: "creado", t: "Fecha", f: fdt }, { k: "tipo", t: "Aviso", f: (v) => EV_TXT[v] || v }, { k: "resumen", t: "Detalle" },
    { k: "estado", t: "Estado", f: (v, x) => `${badge(v === "enviado" ? "entregado" : v === "aviso" ? "sin entregar" : "pendiente")}${x.error && v !== "enviado" ? `<div class="peq" style="color:#a15c00">${esc(x.error)}</div>` : ""}` },
    { k: "intentos", t: "Intentos" }], d.eventos);
};

// ---- caja de recepción: arqueo por turno y recepcionista
V.caja = async (el) => {
  const turisticos = can("reservas.editar") ? assetsOf("apartamentos_turisticos") : [];
  let aid = turisticos.some((a) => a.id === Number(S.asset)) ? Number(S.asset) : turisticos[0]?.id;
  el.innerHTML = `${aid ? `<div class="card"><h3>Mi turno</h3><div class="toolbar"><select id="ac">${turisticos.map((a) => `<option value="${a.id}" ${a.id === aid ? "selected" : ""}>${esc(a.nombre)}</option>`).join("")}</select></div><div id="tu"></div></div>` : ""}
    <div class="card"><h3>Cierres de caja</h3><div class="toolbar"><input type="date" id="d"> <input type="date" id="h"></div><div id="ci"></div></div>`;
  const formas = {};
  const turno = async () => {
    if (!$("#tu", el)) return;
    const t = await get("/api/caja/turno", { asset_id: aid });
    Object.assign(formas, t.formas);
    $("#tu", el).innerHTML = `<p>Desde <b>${fdt(t.desde)}</b> (su último cierre o el inicio del día).</p>
      <div class="kpis">${Object.entries(t.totales).map(([k, v]) => `<div class="kpi"><b>${eur(v)}</b><span>${esc(t.formas[k] || k)}</span></div>`).join("") || '<p class="muted">Sin cobros ni devoluciones en este turno.</p>'}</div>
      <div id="mv"></div><div class="toolbar"><button class="btn primary" id="cerrar">Cerrar turno (arqueo)</button></div>`;
    table($("#mv", el), [{ k: "hora", t: "Hora", f: fdt }, { k: "tipo", t: "Movimiento" }, { k: "ref", t: "Referencia" },
      { k: "forma", t: "Forma", f: (v) => esc(t.formas[v] || v) }, { k: "importe", t: "Importe", num: true, f: eur }], t.movimientos);
    $("#cerrar", el).onclick = () => form("Cierre de turno: arqueo de caja", [
      { html: `<p>Efectivo que debería haber (cobros menos devoluciones en efectivo del turno): <b>${eur(t.efectivo_esperado)}</b>. Cuente el efectivo y anótelo; si deja fondo de caja, indíquelo.</p>` },
      { k: "efectivo_contado", t: "Efectivo contado €", type: "number", step: "0.01", req: true },
      { k: "fondo", t: "Fondo de caja que se queda €", type: "number", step: "0.01", def: 0 },
      { k: "nota", t: "Motivo si no cuadra", type: "textarea", wide: true },
    ], {}, async (d) => {
      const c = await post("/api/caja/cierre", { asset_id: aid, ...clean(d) });
      toast(Number(c.diferencia) ? `Turno cerrado con descuadre de ${eur(c.diferencia)}: avisada la Dirección` : "Turno cerrado: la caja cuadra");
      turno(); cierres();
    }, "Cerrar turno");
  };
  const cierres = async () => table($("#ci", el), [{ k: "hasta", t: "Cierre", f: fdt }, { k: "activo", t: "Activo" }, { k: "recepcionista", t: "Recepcionista" },
    { k: "totales", t: "Cobrado", f: (v) => Object.entries(v || {}).map(([k, x]) => `${esc(formas[k] || k)} ${eur(x)}`).join(" · ") },
    { k: "efectivo_esperado", t: "Efectivo esperado", num: true, f: eur }, { k: "efectivo_contado", t: "Contado", num: true, f: eur },
    { k: "diferencia", t: "Diferencia", num: true, f: (v, c) => (Number(v) ? `<span class="badge b-urgente" title="${esc(c.nota || "")}">${eur(v)}</span>` : "✔") }],
    await get("/api/caja/cierres", { asset_id: S.asset || undefined, desde: $("#d", el).value || undefined, hasta: $("#h", el).value || undefined }));
  $("#d", el).onchange = cierres; $("#h", el).onchange = cierres;
  if ($("#ac", el)) $("#ac", el).onchange = () => { aid = Number($("#ac", el).value); turno(); };
  await turno(); cierres();
};

const MENU = [
  ["General", [["panel", "Panel de control", null], ["agenda", "Agenda", null], ["manual", "Manual de uso", null], ["activos", "Activos", "activos.ver"], ["unidades", "Unidades", "activos.ver"]]],
  ["Personal", [["ausencias", "Vacaciones y ausencias", "activos.ver"], ["personal", "Fichas del personal", "personal"], ["jornada", "Registro de jornada", "gestpersonal"], ["mijornada", "Mi jornada (fichar)", null]]],
  ["Apartamentos turísticos", [["plano", "Plano de apartamentos", "activos.ver"], ["hoy", "Llegadas / salidas", "reservas.ver"], ["limpieza", "Parte de limpieza", "limpieza.editar"], ["reservas", "Reservas", "reservas.ver"], ["planning", "Planning", "reservas.ver"], ["huespedes", "Huéspedes", "reservas.ver"], ["ses", "Parte de viajeros (SES)", "reservas.ver"], ["garajes", "Alquiler de garajes", "reservas.ver"], ["caja", "Caja y cierres de turno", "caja"]]],
  ["Alquiler residencial", [["contratos", "Contratos", "alquiler.ver"], ["recibos", "Recibos y cobros", "alquiler.ver"], ["inquilinos", "Inquilinos", "alquiler.ver"], ["cobrosext", "Cobros de otro programa", "alquiler.ver"]]],
  ["Facturación e informes", [["facturas", "Facturas emitidas", "facturas.ver"], ["servicios", "Servicios", "activos.ver"], ["informes", "Informes Excel", "informes"], ["presidencia", "Informe a presidencia", "facturas.ver"]]],
  ["Documentos y gastos", [["docrecibidos", "Documentos recibidos", "documentos.ver"], ["gastos", "Cuenta de gastos", "documentos.ver"]]],
  ["Mantenimiento", [["estado", "Partes de estado", "partesestado"], ["ordenes", "Órdenes de trabajo", "mantenimiento.ver"], ["preventivo", "Plan preventivo", "mantenimiento.ver"], ["partestrabajo", "Parte de trabajo diario", "partes"], ["pedidos", "Pedidos de material", "pedidos"], ["productos", "Catálogo de productos", "pedidos"], ["proveedores", "Proveedores", "proveedores"]]],
  ["Inversiones (CAPEX)", [["capex", "Proyectos CAPEX", "capex.ver"], ["capexplantillas", "Plantillas CAPEX tipo", "capex.gestionar"], ["capexprecios", "Base de precios (BC3)", "capex.gestionar"]]],
  ["Administración", [["gestion", "Pasarela con gestión", "admin"], ["legal", "Documentación legal", "legal.ver"], ["usuarios", "Usuarios", "admin"], ["roles", "Roles y permisos", "admin"], ["sociedades", "Sociedades", "admin"], ["avisos", "Avisos por correo", "admin"], ["auditoria", "Auditoría", "auditoria.ver"]]],
  ["", [["perfil", "Mi perfil", null]]],
];
const allowed = (p) => !p || (p === "admin" ? S.me.admin_grupo : p === "informes" ? ["reservas.ver", "alquiler.ver", "finanzas.ver", "mantenimiento.ver"].some(can)
  : p === "personal" ? ["mantenimiento.ver", "limpieza.editar", "limpieza.confirmar_ot"].some(can)
  : p === "proveedores" ? verProveedores() : p === "pedidos" ? verPedidos() : p === "partes" ? verPartes()
  : p === "partesestado" ? canParteEstado() || can("mantenimiento.abrir")
  : p === "gestpersonal" ? can("personal.autorizar") || can("partes.validar")
  : p === "caja" ? can("reservas.editar") || can("finanzas.ver") : can(p));
const TITLES = Object.fromEntries(MENU.flatMap(([, items]) => items.map(([id, t]) => [id, t])));
const PERMISO_VISTA = Object.fromEntries(MENU.flatMap(([, items]) => items.map(([id, , p]) => [id, p])));
const puedeIr = (vista) => vista in PERMISO_VISTA && allowed(PERMISO_VISTA[vista]);  // pantalla del menú visible
const tituloVista = (vista) => TITLES[vista] || vista;

// Menú lateral sin desplazamiento: grupos plegables. Si todo cabe en la altura de la pantalla se ven abiertos;
// si no, solo «General» y el grupo de la pantalla actual (pulsando un título se abre ese y se cierran los demás).
const MENU_COLAB = [["", [["colaborador", "Portal del colaborador", null]]], ["", [["perfil", "Mi perfil", null]]]];
TITLES.colaborador = "Portal del colaborador";
function renderNav() {
  $("#nav").innerHTML = (S.me.colaborador ? MENU_COLAB : MENU).map(([g, items], i) => {
    const vis = items.filter(([, , p]) => allowed(p));
    if (!vis.length) return "";
    const links = vis.map(([id, t]) => `<a href="#${id}" data-v="${id}">${t}</a>`).join("");
    return g ? `<div class="grupo" data-g="${i}"><button type="button" class="group">${g}<span class="flecha">▾</span></button><div class="items">${links}</div></div>`
      : `<div class="grupo fijo">${links}</div>`;
  }).join("");
  $("#nav").querySelectorAll(".grupo > .group").forEach((b) => (b.onclick = () => {
    const g = b.parentElement, abrir = g.classList.contains("cerrado");
    if (abrir && S.navPlegado) $("#nav").querySelectorAll(".grupo[data-g]").forEach((x) => x !== g && !x.querySelector("a.active") && x.dataset.g !== "0" && x.classList.add("cerrado"));
    g.classList.toggle("cerrado", !abrir);
    if (abrir) ajustarNav(g);
  }));
  ajustarNav();
}
function ajustarNav(prioritario) {
  const sb = $(".sidebar"), grupos = [...$("#nav").querySelectorAll(".grupo[data-g]")];
  if (!sb || !grupos.length) return;
  grupos.forEach((g) => g.classList.remove("cerrado"));
  S.navPlegado = sb.scrollHeight > sb.clientHeight + 1;
  if (!S.navPlegado) return;
  // se pliegan los grupos (de abajo arriba) que no son el de la pantalla actual, General ni el que se acaba de abrir
  const plegables = grupos.filter((g) => g !== prioritario && !g.querySelector("a.active") && g.dataset.g !== "0").reverse();
  for (const g of plegables) g.classList.add("cerrado");
  // y se vuelven a abrir, de arriba abajo, todos los que quepan
  const cabe = () => sb.scrollHeight <= sb.clientHeight + 1;
  for (const g of [...plegables].reverse()) { g.classList.remove("cerrado"); if (!cabe()) g.classList.add("cerrado"); }
  // si aun así no cabe, se pliega también General
  const gen = grupos.find((g) => g.dataset.g === "0");
  if (sb.scrollHeight > sb.clientHeight + 1 && gen && gen !== prioritario && !gen.querySelector("a.active")) gen.classList.add("cerrado");
}
window.addEventListener("resize", () => { clearTimeout(S._navT); S._navT = setTimeout(() => $("#nav") && $("#nav").children.length && ajustarNav(), 150); });
// Volver: pantallas visitadas en esta sesión (la última es la actual)
S.pila = [];
function pintarVolver() {
  const b = $("#backBtn"), inicio = S.me?.colaborador ? "colaborador" : "panel";
  b.hidden = S.pila.length < 2 && S.pila[0] === inicio;
}
function volver() {
  if ($("#modal").open) return $("#modal").close();
  S.pila.pop();  // la actual
  go(S.pila.pop() || (S.me.colaborador ? "colaborador" : "panel"));
}
async function go(view) {
  const [vista, qs] = String(view || "").split("?");
  view = vista; S.params = new URLSearchParams(qs || "");
  if (S.me.colaborador) view = ["colaborador", "perfil"].includes(view) ? view : "colaborador";
  else view = TITLES[view] && view !== "colaborador" && allowed(MENU.flatMap(([, i]) => i).find(([id]) => id === view)[2]) ? view : "panel";
  if (location.hash !== "#" + view) history.replaceState(null, "", "#" + view);
  if (S.pila.at(-1) !== view) { S.pila.push(view); if (S.pila.length > 50) S.pila.shift(); }
  pintarVolver();
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.v === view));
  ajustarNav();
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
    nuevoToken(await post("/api/auth/password", { actual: d.actual, nueva: d.nueva }));
    toast("Contraseña actualizada"); setTimeout(start, 0);
  }, "Cambiar contraseña");
  $("#fCancel", f).textContent = "Salir"; $("#fCancel", f).onclick = () => { $("#modal").close(); logout(); };
  $("#modal").oncancel = (e) => e.preventDefault();  // no se puede cerrar con Esc
}

async function start() {
  try { S.me = await get("/api/auth/me"); } catch { return showLogin(); }
  if (S.me.debe_cambiar_password) return forcePasswordChange();
  if (S.me.colaborador) return startColaborador();
  $("#modal").oncancel = null; $("#assetFilter").hidden = false;
  S.cat = await get("/api/catalogos");
  S.asset = localStorage.getItem("pms_asset") || "";
  await Promise.all([loadAssets(), loadCompanies()]);
  $("#login").classList.add("hidden"); $("#app").classList.remove("hidden");
  pintarUsuario();
  renderNav();
  go(location.hash.slice(1) || "panel");
  avisoNovedades();
  vigilarResultadosOT();
  comprobarReloj();
}
// El reloj de este ordenador y el del programa (Madrid) deben coincidir: si no, las fechas y horas que propone el
// navegador salen mal. A la Dirección se le avisa además si el servidor no está en hora de Madrid.
async function comprobarReloj() {
  const r = await get("/api/auth/reloj").catch(() => null);
  if (!r) return;
  const min = Math.round((Date.now() - new Date(r.utc).getTime()) / 60000);
  if (Math.abs(min) >= 3) toast(`El reloj de este ordenador va ${Math.abs(min)} minutos ${min > 0 ? "adelantado" : "atrasado"} respecto al programa: corríjalo (Windows: Configuración → Hora e idioma → Sincronizar ahora).`, true);
  if (S.me.admin_grupo && !r.correcta) toast(`El servidor no está en hora de Madrid (zona ${r.zona_efectiva}, UTC${r.horas_sobre_utc >= 0 ? "+" : ""}${r.horas_sobre_utc}). Avise al responsable del servidor.`, true);
}
// Colaborador externo (subcontrata): solo su portal; el resto de la API le está cerrada
async function startColaborador() {
  $("#modal").oncancel = null; $("#assetFilter").hidden = true;
  S.cat = { permisos: {} }; S.companies = [];
  S.colab = await get("/api/colaborador/resumen");
  S.assets = S.colab.activos; S.asset = "";
  $("#login").classList.add("hidden"); $("#app").classList.remove("hidden");
  pintarUsuario();
  renderNav();
  go(location.hash.slice(1) || "colaborador");
}
// Alerta al momento (sonido + aviso) cuando un técnico envía el resultado de una orden desde su enlace
function vigilarResultadosOT() {
  clearInterval(S._otT);
  if (!can("mantenimiento.cerrar")) return;
  S._otDesde = S._otDesde || new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 19);
  const pita = (urgente) => {
    try {
      const ac = new (window.AudioContext || window.webkitAudioContext)();
      [0, 0.25, ...(urgente ? [0.5] : [])].forEach((t) => { const o = ac.createOscillator(), g = ac.createGain(); o.frequency.value = urgente ? 880 : 660; g.gain.value = 0.08; o.connect(g); g.connect(ac.destination); o.start(ac.currentTime + t); o.stop(ac.currentTime + t + 0.15); });
    } catch {}
  };
  S._otT = setInterval(async () => {
    if (!S.me || document.hidden) return;
    try {
      const nuevos = await get("/api/mantenimiento/resultados", { desde: S._otDesde });
      if (!nuevos.length) return;
      S._otDesde = nuevos[nuevos.length - 1].enviado;
      const n = nuevos[nuevos.length - 1];
      pita(nuevos.some((x) => x.resultado === "escalar"));
      toast(nuevos.length === 1 ? `${otNum(n.ot)} · ${n.tecnico}: ${n.resultado_nombre}` : `${nuevos.length} resultados de técnicos nuevos (último: ${otNum(n.ot)} ${n.resultado_nombre})`, n.resultado === "escalar");
    } catch {}
  }, 60000);
}
function pintarUsuario() {
  $("#userAvatar").textContent = iniciales(S.me.nombre); $("#userAvatar").title = S.me.nombre;
  $("#gestionBtn").hidden = !S.me.gestion;  // solo superadministrador, Alfonso y Bárbara
  $("#userName").innerHTML = `${esc(S.me.nombre)}<small>${esc(S.me.colaborador ? S.me.colaborador.proveedor : rolDe(S.me))}</small>`;
}
function showLogin() { $("#app").classList.add("hidden"); $("#login").classList.remove("hidden"); }
// al cambiar la contraseña se cierran las demás sesiones; esta sigue con el token nuevo
function nuevoToken(r) { if (r && r.token) { S.token = r.token; localStorage.setItem("pms_token", S.token); } }
function logout() { S.token = null; S.pila = []; localStorage.removeItem("pms_token"); showLogin(); }

$("#loginForm").onsubmit = async (e) => {
  e.preventDefault();
  const d = Object.fromEntries(new FormData(e.target));
  try { S.token = (await post("/api/auth/login", d)).token; localStorage.setItem("pms_token", S.token); $("#loginError").textContent = ""; start(); }
  catch (err) { $("#loginError").textContent = err.message; }
};
$("#logoutBtn").onclick = logout;
$("#gestionBtn").onclick = () => abrirGestion("inicio");
$("#menuBtn").onclick = () => $(".sidebar").classList.toggle("open");
$("#backBtn").onclick = volver;
$("#assetFilter").onchange = (e) => { setAsset(e.target.value); go(location.hash.slice(1)); };
window.onhashchange = () => S.me && go(location.hash.slice(1));
S.token ? start() : showLogin();
