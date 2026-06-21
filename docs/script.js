let tickets = [];
let optionsData = { departamentos: [], categorias: [], atendentes: [], sla_regras: [], canais: [] };
let currentUser = JSON.parse(localStorage.getItem("cs_user") || "null");
let token = localStorage.getItem("cs_token") || "";
let activeTicketId = "";
let ticketQuickFilter = "";
let pendingRoute = "";

const services = [
  ["Acesso", "Solicitar acesso", "Liberação de usuário em sistemas internos, CRM, ERP e portais."],
  ["Usuário", "Criar usuário", "Cadastro corporativo com perfil, unidade e permissões iniciais."],
  ["Erro", "Corrigir erro em sistema", "Análise de falhas em aplicações críticas e integrações."],
  ["Software", "Instalar software", "Instalação de ferramentas homologadas para trabalho."],
  ["Relatório", "Gerar relatório", "Criação de extrações, consultas SQL e relatórios gerenciais."],
  ["Dashboard", "Ajustar dashboard", "Correções em Power BI, métricas, filtros e atualização de dados."],
  ["Nuvem", "Solicitar suporte em nuvem", "Apoio em ambientes cloud, acessos, deploys e monitoramento."],
  ["Banco", "Ajustar base de dados", "Permissões, consultas, lentidão e inconsistências em dados."],
];

const articles = [
  ["Como redefinir senha com segurança", "Acesso e Senhas", "Passo a passo para recuperar acesso sem acionar o suporte."],
  ["Checklist para erro em dashboard Power BI", "Dados e Relatórios", "Valide gateway, atualização, credenciais e conexão SQL."],
  ["Boas práticas para abrir chamado crítico", "SLA", "Como informar impacto, urgência e evidências para reduzir tempo de triagem."],
  ["VPN conectada, mas sem acesso aos sistemas", "Rede e Internet", "Teste DNS, perfil de rede e políticas de acesso."],
  ["Como solicitar criação de usuário", "Serviços", "Dados obrigatórios para cadastro correto de colaborador."],
];

const routes = [...document.querySelectorAll(".view")].map((section) => section.id);
const protectedRoutes = new Set(["user-dashboard", "admin-dashboard", "new-ticket", "tickets", "ticket-detail", "reports", "profile"]);
const $ = (selector) => document.querySelector(selector);
const $all = (selector) => [...document.querySelectorAll(selector)];

function isLoggedIn() {
  return Boolean(token && currentUser);
}

function formatPct(value, total) {
  const t = Number(total || 0);
  return t ? `${Math.round((Number(value || 0) / t) * 100)}%` : "0%";
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(String(value).replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function formatHours(value) {
  const hours = Number(value || 0);
  if (!hours) return "-";
  if (hours < 1) return `${Math.round(hours * 60)}min`;
  return `${hours.toFixed(1).replace(".", ",")}h`;
}

function setTicketMessage(text = "", type = "") {
  const box = $("#ticketMessage");
  if (!box) return;
  box.textContent = text;
  box.className = `form-message span-2 ${type}`.trim();
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, { ...options, headers });
  const data = await response.json();
  if (!response.ok || data.ok === false) throw new Error(data.error || "Erro inesperado");
  return data;
}

function go(route) {
  let target = routes.includes(route) ? route : "landing";
  if (protectedRoutes.has(target) && !isLoggedIn()) {
    pendingRoute = target;
    const msg = $("#authMessage");
    if (msg) msg.textContent = "Entre ou crie uma conta para abrir e acompanhar chamados.";
    target = "login";
    showAuthPanel("login");
  }
  $all(".view").forEach((view) => view.classList.toggle("active", view.id === target));
  $all("[data-route]").forEach((link) => link.classList.toggle("active", link.dataset.route === target));
  location.hash = target;
  if (target === "tickets") loadTickets();
  if (target === "ticket-detail") loadTicketDetail(activeTicketId || tickets[0]?.id || tickets[0]?.ticket_id);
  drawCharts();
}

function showAuthPanel(mode) {
  $("#loginPanel")?.classList.toggle("active", mode !== "register");
  $("#registerPanel")?.classList.toggle("active", mode === "register");
  const msg = $("#authMessage");
  if (msg && mode === "register") msg.textContent = "";
}

function normalizeTicket(row) {
  return {
    id: row.ticket_id || row.id,
    title: row.titulo || row.title || row.subcategoria || "Chamado sem título",
    category: row.nome_categoria || row.category,
    priority: row.prioridade || row.priority,
    status: row.status,
    requester: row.solicitante || row.requester || "-",
    owner: row.responsavel || row.owner || "Triagem",
    opened: row.data_abertura || row.opened,
    sla: row.sla_label || row.sla || "-",
    risk: Boolean(row.risk),
    description: row.descricao || "",
  };
}

function statusClass(ticket) {
  if (ticket.priority === "Critica" || ticket.risk) return "danger";
  return "";
}

function priorityClass(priority = "") {
  const normalized = priority.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  if (normalized === "alta" || normalized === "critica") return "danger";
  if (normalized === "media") return "warn";
  if (normalized === "baixa") return "success";
  return "";
}

function fillSelect(select, rows, valueKey, labelKey, placeholder = "") {
  if (!select) return;
  const items = placeholder ? [`<option value="">${placeholder}</option>`] : [];
  rows.forEach((row) => items.push(`<option value="${row[valueKey]}">${row[labelKey]}</option>`));
  select.innerHTML = items.join("");
}

async function loadOptions() {
  optionsData = await api("/api/options");
  fillSelect($("#registerDepartment"), optionsData.departamentos, "departamento_id", "nome_departamento", "Selecione");
  fillSelect($("#ticketCategory"), optionsData.categorias, "categoria_id", "nome_categoria");
  fillSelect($("#ticketOwner"), optionsData.atendentes, "atendente_id", "nome_atendente", "Especialista padrão");
  if ($("#ticketChannel")) $("#ticketChannel").innerHTML = optionsData.canais.map((c) => `<option>${c}</option>`).join("");
}

async function loadTickets() {
  const status = $("#statusFilter")?.value || "";
  const prioridade = $("#priorityFilter")?.value || "";
  const params = new URLSearchParams();
  if (status && status !== "Todos") params.set("status", status);
  if (prioridade && prioridade !== "Todas prioridades") params.set("prioridade", prioridade);
  const data = await api(`/api/tickets?${params.toString()}`);
  tickets = data.tickets.map(normalizeTicket);
  if (ticketQuickFilter) {
    tickets = tickets.filter((ticket) => ticket.priority === ticketQuickFilter || (ticketQuickFilter === "SLA" && ticket.risk));
  }
  renderTickets();
  renderUserTickets();
  renderTriage();
  drawCharts();
}

async function loadMetrics() {
  try {
    const data = await api("/api/metrics");
    const slaPct = formatPct(data.dentro_sla, data.total);
    const riskTotal = Number(data.sla_vencidos_abertos || 0) + Number(data.sla_risco || 0);
    if ($("#heroSla")) $("#heroSla").textContent = slaPct;
    if ($("#heroOpen")) $("#heroOpen").textContent = data.abertos ?? "0";
    if ($("#heroSat")) $("#heroSat").textContent = data.satisfacao || "-";
    if ($("#metricOpen")) $("#metricOpen").textContent = data.abertos ?? "0";
    if ($("#metricRiskText")) $("#metricRiskText").textContent = `${riskTotal} chamados com atenção de SLA`;
    if ($("#metricOnTime")) $("#metricOnTime").textContent = slaPct;
    if ($("#metricUpdated")) $("#metricUpdated").textContent = formatDateTime(data.ultima_atualizacao);
    if ($("#metricSatisfaction")) $("#metricSatisfaction").textContent = data.satisfacao || "-";
    if ($("#adminOpen")) $("#adminOpen").textContent = data.abertos ?? "0";
    if ($("#adminRisk")) $("#adminRisk").textContent = riskTotal;
    if ($("#adminResolved")) $("#adminResolved").textContent = data.resolvidos ?? "0";
    if ($("#adminAvgTime")) $("#adminAvgTime").textContent = formatHours(data.tempo_medio_resolucao);
  } catch {
    // Dashboard still renders if metrics are unavailable.
  }
}

function renderUserTickets() {
  const container = $("#userTicketCards");
  if (!container) return;
  container.innerHTML = tickets.slice(0, 3).map((ticket) => `
    <article class="ticket-card">
      <header><strong>${ticket.id}</strong><span class="status-chip ${priorityClass(ticket.priority)}">${ticket.priority}</span></header>
      <span>${ticket.title}</span>
      <small class="muted">${ticket.status} · ${ticket.sla}</small>
    </article>
  `).join("");
}

function renderTriage() {
  const container = $("#triageQueue");
  if (!container) return;
  container.innerHTML = tickets.filter((ticket) => ticket.status !== "Resolvido" && ticket.status !== "Fechado").slice(0, 5).map((ticket) => `
    <article class="triage-item">
      <div>
        <strong>${ticket.id} · ${ticket.title}</strong>
        <p class="muted">${ticket.category} · ${ticket.requester}</p>
      </div>
      <span class="status-chip ${statusClass(ticket)}">${ticket.sla}</span>
    </article>
  `).join("");
}

function renderTickets() {
  const table = $("#ticketTable");
  if (!table) return;
  table.innerHTML = tickets.map((ticket) => `
    <tr data-ticket="${ticket.id}" data-route="ticket-detail">
      <td>${ticket.id}</td>
      <td>${ticket.title}</td>
      <td>${ticket.category}</td>
      <td><span class="status-chip ${priorityClass(ticket.priority)}">${ticket.priority}</span></td>
      <td>${ticket.status}</td>
      <td>${ticket.sla}</td>
      <td>${ticket.owner}</td>
    </tr>
  `).join("");
}

function renderServices() {
  const grid = $("#serviceGrid");
  if (!grid) return;
  grid.innerHTML = services.map(([icon, title, desc]) => `
    <article class="service-card">
      <div class="service-icon">${icon.slice(0, 2)}</div>
      <h3>${title}</h3>
      <p class="muted">${desc}</p>
    </article>
  `).join("");
}

function renderArticles(term = "") {
  const list = $("#articleList");
  if (!list) return;
  const q = term.toLowerCase();
  const filtered = articles.filter((article) => article.join(" ").toLowerCase().includes(q));
  list.innerHTML = filtered.map(([title, tag, desc]) => `
    <article class="article">
      <div><h3>${title}</h3><p class="muted">${desc}</p></div>
      <span class="chip">${tag}</span>
    </article>
  `).join("") || `<article class="article"><p class="muted">Nenhum artigo encontrado.</p></article>`;
}

function renderTeam() {
  const list = $("#teamReport");
  if (!list) return;
  const rows = [
    ["Marina Costa", "96%", "32 chamados resolvidos"],
    ["Diego Nunes", "91%", "28 chamados resolvidos"],
    ["Patrícia Rocha", "88%", "24 chamados resolvidos"],
    ["Renata Dias", "86%", "19 chamados resolvidos"],
  ];
  list.innerHTML = rows.map(([name, pct, detail]) => `
    <article class="team-row">
      <strong>${name}</strong><span>${pct}</span>
      <small class="muted">${detail}</small>
      <div class="bar"><i style="width:${pct}"></i></div>
    </article>
  `).join("");
}

async function loadTicketDetail(ticketId) {
  if (!ticketId) return;
  try {
    const data = await api(`/api/ticket?id=${encodeURIComponent(ticketId)}`);
    const t = normalizeTicket(data.ticket);
    activeTicketId = t.id;
    const title = $("#ticket-detail .detail-main h2");
    const desc = $("#ticket-detail .description");
    if (title) title.textContent = t.title;
    if (desc) desc.textContent = t.description || `${t.category} · Solicitante: ${t.requester}`;
    renderChat(data.ticket.comentarios || []);
    renderTimeline(data.ticket.historico || []);
  } catch (error) {
    renderChat([{ autor: "Sistema", mensagem: error.message }]);
  }
}

function renderChat(messages = []) {
  const box = $("#chatBox");
  if (!box) return;
  box.innerHTML = messages.map((msg, idx) => `
    <div class="message-row ${idx === 0 ? "me" : ""}">
      <strong>${msg.autor || "Usuário"}</strong>
      <p>${msg.mensagem || ""}</p>
    </div>
  `).join("") || `<div class="message-row"><strong>Sistema</strong><p>Nenhuma mensagem ainda.</p></div>`;
  box.scrollTop = box.scrollHeight;
}

function renderTimeline(items = []) {
  const timeline = $(".timeline");
  if (!timeline) return;
  timeline.innerHTML = items.map((item) => `
    <div><span></span><strong>${item.evento}</strong><small>${item.criado_em || ""}</small></div>
  `).join("") || `<div><span></span><strong>Chamado registrado</strong><small>Aguardando histórico.</small></div>`;
}

function inferSuggestion() {
  const title = $("#ticketTitle")?.value || "";
  const desc = $("#ticketDescription")?.value || "";
  const text = `${title} ${desc}`.toLowerCase();
  const categories = optionsData.categorias || [];
  let chosen = categories[0];
  let priority = "Media";
  if (/dashboard|relat.rio|power bi|sql|base|dados/.test(text)) chosen = categories.find((c) => c.nome_categoria === "Dados e Relatorios") || chosen;
  if (/senha|acesso|login|mfa|token/.test(text)) chosen = categories.find((c) => c.nome_categoria === "Acesso e Senhas") || chosen;
  if (/hardware|notebook|monitor|impressora/.test(text)) chosen = categories.find((c) => c.nome_categoria === "Hardware") || chosen;
  if (/fora do ar|parado|indispon.vel|produção|critico|crítico/.test(text)) priority = "Critica";
  else if (/diretoria|hoje|urgente|erro|falha/.test(text)) priority = "Alta";
  if (chosen && $("#ticketCategory")) $("#ticketCategory").value = chosen.categoria_id;
  if ($("#ticketPriority")) $("#ticketPriority").value = priority;
  const sla = optionsData.sla_regras.find((s) => s.categoria_id === chosen?.categoria_id && s.prioridade === priority);
  $("#suggestedCategory").textContent = chosen?.nome_categoria || "-";
  $("#suggestedPriority").textContent = priority;
  $("#suggestedSla").textContent = sla ? `${Number(sla.sla_resolucao_horas)} horas` : "-";
}

async function submitTicket(event) {
  event.preventDefault();
  const button = $("#submitTicketButton");
  if (!isLoggedIn()) {
    pendingRoute = "new-ticket";
    go("login");
    return;
  }
  if (!$("#ticketCategory")?.value) {
    setTicketMessage("Selecione uma categoria antes de enviar o chamado.", "error");
    return;
  }
  if (!$("#ticketTitle")?.value.trim() || !$("#ticketDescription")?.value.trim()) {
    setTicketMessage("Preencha título e descrição para registrar o chamado.", "error");
    return;
  }
  const payload = {
    titulo: $("#ticketTitle").value,
    descricao: $("#ticketDescription").value,
    categoria_id: $("#ticketCategory").value,
    prioridade: $("#ticketPriority").value,
    atendente_id: $("#ticketOwner").value,
    canal: $("#ticketChannel").value || "Portal",
  };
  try {
    if (button) {
      button.disabled = true;
      button.textContent = "Enviando...";
    }
    setTicketMessage("Registrando chamado no MySQL...", "info");
    const data = await api("/api/tickets", { method: "POST", body: JSON.stringify(payload) });
    const id = data.ticket?.ticket_id || data.ticket?.id || "novo chamado";
    setTicketMessage(`Chamado ${id} criado com sucesso. Redirecionando para a lista...`, "success");
    ticketQuickFilter = "";
    await loadTickets();
    activeTicketId = id;
    go("tickets");
  } catch (error) {
    setTicketMessage(error.message || "Não foi possível enviar o chamado.", "error");
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = "Enviar chamado";
    }
  }
}

function drawLine(canvas, values, colors = ["#0284c7", "#2563eb"]) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  canvas.width = canvas.clientWidth * devicePixelRatio;
  canvas.height = Number(canvas.getAttribute("height")) * devicePixelRatio;
  ctx.scale(devicePixelRatio, devicePixelRatio);
  const width = canvas.clientWidth;
  const height = Number(canvas.getAttribute("height"));
  ctx.clearRect(0, 0, width, height);
  const max = Math.max(...values), min = Math.min(...values);
  const pts = values.map((v, i) => [18 + i * ((width - 36) / (values.length - 1)), height - 28 - ((v - min) / (max - min || 1)) * (height - 70)]);
  const grad = ctx.createLinearGradient(0, 0, width, 0);
  grad.addColorStop(0, colors[0]); grad.addColorStop(1, colors[1]);
  ctx.strokeStyle = grad; ctx.lineWidth = 4; ctx.beginPath();
  pts.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
  ctx.stroke();
}

function drawDonut(canvas, values) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const height = Number(canvas.getAttribute("height"));
  canvas.width = canvas.clientWidth * devicePixelRatio;
  canvas.height = height * devicePixelRatio;
  ctx.scale(devicePixelRatio, devicePixelRatio);
  const cx = canvas.clientWidth / 2, cy = height / 2 + 6;
  const total = values.reduce((a, b) => a + b.value, 0);
  let start = -Math.PI / 2;
  values.forEach((part) => {
    const angle = (part.value / total) * Math.PI * 2;
    ctx.strokeStyle = part.color; ctx.lineWidth = 34; ctx.beginPath();
    ctx.arc(cx, cy, 78, start, start + angle); ctx.stroke(); start += angle;
  });
  ctx.fillStyle = "#102033"; ctx.font = "700 26px Segoe UI"; ctx.textAlign = "center"; ctx.fillText(`${total}`, cx, cy + 8);
}

function drawBars(canvas, values) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const height = Number(canvas.getAttribute("height"));
  canvas.width = canvas.clientWidth * devicePixelRatio; canvas.height = height * devicePixelRatio;
  ctx.scale(devicePixelRatio, devicePixelRatio);
  const width = canvas.clientWidth, max = Math.max(...values.map((v) => v.value));
  values.forEach((item, i) => {
    const y = 36 + i * 54, barW = ((width - 170) * item.value) / max;
    ctx.fillStyle = "#94a3b8"; ctx.font = "700 13px Segoe UI"; ctx.fillText(item.label, 10, y);
    ctx.fillStyle = "rgba(203,213,225,.45)"; ctx.fillRect(120, y - 14, width - 150, 18);
    ctx.fillStyle = item.color; ctx.fillRect(120, y - 14, barW, 18);
    ctx.fillStyle = "#102033"; ctx.fillText(`${item.value}%`, width - 44, y);
  });
}

function drawCharts() {
  const open = tickets.filter((t) => t.status === "Em atendimento").length || 1;
  const waiting = tickets.filter((t) => t.status === "Aguardando usuario").length || 1;
  const closed = tickets.filter((t) => t.status === "Resolvido" || t.status === "Fechado").length || 1;
  drawDonut($("#userDonut"), [{ value: open, color: "#0284c7" }, { value: waiting, color: "#2563eb" }, { value: closed, color: "#16a34a" }]);
  drawLine($("#adminLine"), [31, 38, 35, 44, 52, 49, 61, 58, 63, 72, 68, 79]);
  drawBars($("#slaBar"), [
    { label: "Critica", value: 81, color: "#e11d48" },
    { label: "Alta", value: 88, color: "#d97706" },
    { label: "Media", value: 94, color: "#2563eb" },
    { label: "Baixa", value: 97, color: "#16a34a" },
  ]);
}

function bindEvents() {
  document.body.addEventListener("click", async (event) => {
    const row = event.target.closest("[data-ticket]");
    if (row) activeTicketId = row.dataset.ticket;
    const routeEl = event.target.closest("[data-route]");
    if (routeEl) { event.preventDefault(); ticketQuickFilter = ""; go(routeEl.dataset.route); }
    const backEl = event.target.closest("[data-back]");
    if (backEl) {
      event.preventDefault();
      if (window.history.length > 1) window.history.back();
      else go("user-dashboard");
    }
    const filterEl = event.target.closest("[data-filter]");
    if (filterEl) { ticketQuickFilter = filterEl.dataset.filter; go("tickets"); await loadTickets(); }
  });
  $("#navToggle")?.addEventListener("click", () => $(".topnav").classList.toggle("open"));
  $("#statusFilter")?.addEventListener("change", loadTickets);
  $("#priorityFilter")?.addEventListener("change", loadTickets);
  $("#ticketTitle")?.addEventListener("input", inferSuggestion);
  $("#ticketDescription")?.addEventListener("input", inferSuggestion);
  $("#ticketForm")?.addEventListener("submit", submitTicket);
  $("#showRegister")?.addEventListener("click", async () => {
    try {
      if (!optionsData.departamentos.length) await loadOptions();
    } catch {
      // The register form will show the backend error on submit if the database is unavailable.
    }
    showAuthPanel("register");
  });
  $("#showLogin")?.addEventListener("click", () => showAuthPanel("login"));
  $("#loginForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const data = await api("/api/login", { method: "POST", body: JSON.stringify({ email: $("#loginEmail").value, senha: $("#loginPassword").value }) });
      token = data.token; currentUser = data.user;
      localStorage.setItem("cs_token", token); localStorage.setItem("cs_user", JSON.stringify(currentUser));
      const nextRoute = pendingRoute || "user-dashboard";
      pendingRoute = "";
      await initData(); go(nextRoute);
    } catch (error) { $("#authMessage").textContent = error.message; }
  });
  $("#registerForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const data = await api("/api/register", { method: "POST", body: JSON.stringify({
        nome: $("#registerName").value, email: $("#registerEmail").value, senha: $("#registerPassword").value, departamento_id: $("#registerDepartment").value,
      }) });
      token = data.token; currentUser = data.user;
      localStorage.setItem("cs_token", token); localStorage.setItem("cs_user", JSON.stringify(currentUser));
      const nextRoute = pendingRoute || "user-dashboard";
      pendingRoute = "";
      await initData(); go(nextRoute);
    } catch (error) { $("#authMessage").textContent = error.message; }
  });
  $("#sendChat")?.addEventListener("click", async () => {
    const input = $("#chatInput");
    if (!input.value.trim() || !activeTicketId) return;
    const data = await api("/api/comments", { method: "POST", body: JSON.stringify({ ticket_id: activeTicketId, mensagem: input.value.trim() }) });
    input.value = ""; renderChat(data.ticket.comentarios || []); renderTimeline(data.ticket.historico || []);
  });
  $("#kbSearch")?.addEventListener("input", (event) => renderArticles(event.target.value));
}

async function initData() {
  await loadOptions();
  await loadTickets();
  await loadMetrics();
  renderServices();
  renderArticles();
  renderTeam();
  inferSuggestion();
}

window.addEventListener("resize", drawCharts);
window.addEventListener("hashchange", () => go(location.hash.replace("#", "")));
bindEvents();
api("/api/health").then(initData).catch((err) => console.warn(err));
go(location.hash.replace("#", "") || "landing");
