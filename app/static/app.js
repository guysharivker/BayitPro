// --- Auth ---
function getToken() {
  return localStorage.getItem("bp_token");
}

function logout() {
  localStorage.removeItem("bp_token");
  window.location.href = "/login";
}

let currentView = "dashboard";
let currentAreaId = null;
let dashboardData = null;
let areasData = [];
let areaDetailsCache = {};
let ws = null;
let allBuildings = [];
let allTickets = [];
let companyMap = null;
let areaMap = null;
let companyMapLayer = null;
let areaMapLayer = null;
let lastUpdatedAt = null;
let activeDashboardPanel = "overview";
let activeAreaPanel = "overview";
const DEFAULT_TITLE = "BayitPro - שליטה תפעולית";

const CATEGORY_LABELS = {
  CLEANING: "ניקיון",
  ELECTRIC: "חשמל",
  PLUMBING: "אינסטלציה",
  ELEVATOR: "מעלית",
  GENERAL: "כללי",
};

const CATEGORY_ICONS = {
  CLEANING: "🧹",
  ELECTRIC: "⚡",
  PLUMBING: "🚰",
  ELEVATOR: "🛗",
  GENERAL: "🔧",
};

const STATUS_LABELS = {
  OPEN: "פתוח",
  IN_PROGRESS: "בטיפול",
  DONE: "בוצע",
};

const URGENCY_LABELS = {
  LOW: "רגיל",
  MEDIUM: "רגיל",
  HIGH: "חשוב",
  CRITICAL: "דחוף",
};

const DAY_NAMES = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"];
const URGENCY_PRIORITY = { CRITICAL: 4, HIGH: 3, MEDIUM: 2, LOW: 1 };

function isMobile() {
  return window.matchMedia("(max-width: 768px)").matches;
}

const ROLE_LABELS = {
  SUPER_ADMIN: "מנהל ראשי",
  COMPANY_ADMIN: "מנהל חברה",
  AREA_MANAGER: "מנהל אזור",
  WORKER: "עובד",
};

let currentUser = null;

document.addEventListener("DOMContentLoaded", async () => {
  if (!getToken()) {
    window.location.href = "/login";
    return;
  }

  try {
    currentUser = await api("/auth/me");
  } catch {
    logout();
    return;
  }

  // Populate user menu
  const nameEl = document.getElementById("user-menu-name");
  const roleEl = document.getElementById("user-menu-role");
  if (nameEl) nameEl.textContent = currentUser.full_name;
  if (roleEl) roleEl.textContent = ROLE_LABELS[currentUser.role] || currentUser.role;

  applyRoleVisibility();
  setupDemoToggle();
  setupUserMenu();
  renderLucideIcons();
  startRefreshTicker();
  document.body.classList.add("has-sidebar");
  loadDashboard();
  connectWebSocket();
});

async function api(path, options = {}) {
  const token = getToken();
  if (!token) {
    window.location.href = "/login";
    return;
  }
  const headers = { ...(options.headers || {}), Authorization: `Bearer ${token}` };
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    logout();
    return;
  }
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

async function loadDashboard() {
  if (currentUser?.role === "WORKER") {
    await loadWorkerDashboard();
    return;
  }
  // Area managers go straight to their area — no company dashboard needed
  if (currentUser?.role === "AREA_MANAGER" && currentUser?.area_id) {
    showArea(currentUser.area_id);
    return;
  }

  const [companyDashboard, areas, buildings, tickets] = await Promise.all([
    api("/company/dashboard"),
    api("/areas"),
    api("/buildings"),
    api("/tickets"),
  ]);

  dashboardData = companyDashboard;
  areasData = areas;
  allBuildings = buildings;
  allTickets = tickets;

  renderDashboard();
  loadSimAreas();
  loadWorkerAttendanceWidget();
  updateRefreshTime();
}

/* ================ Dashboard rendering ================ */

function renderDashboard() {
  document.getElementById("brand-title").textContent = dashboardData.company_name;
  document.title = DEFAULT_TITLE;
  const areasTab = document.getElementById("dashboard-tab-areas");
  if (areasTab) {
    areasTab.textContent = `אזורים (${dashboardData.areas.length})`;
  }

  renderUrgentHero();
  renderCompanyStats();
  renderAreaCards();
  renderCompanyAlerts();
  renderDailySummary();
  renderCompanyMapCard();
  updateAlertsBadge();
  showDashboardPanel(activeDashboardPanel, true);
}

function renderUrgentHero() {
  const openTickets = allTickets
    .filter((ticket) => ticket.status !== "DONE")
    .sort(compareTickets);

  const top3 = openTickets.slice(0, 3);
  const container = document.getElementById("urgent-hero");
  const mobile = isMobile();

  if (top3.length === 0) {
    container.className = "urgent-hero urgent-calm";
    container.innerHTML = mobile
      ? `
      <div class="urgent-hero-head compact">
        <h1 class="urgent-hero-title">הכול תחת שליטה ✓</h1>
        <div class="urgent-hero-subtitle">אין כרגע קריאות דורשות טיפול.</div>
      </div>
    `
      : `
      <div class="urgent-hero-head">
        <div>
          <h1 class="urgent-hero-title">הכול תחת שליטה</h1>
          <div class="urgent-hero-subtitle">אין כרגע קריאות פתוחות שדורשות את תשומת הלב שלך.</div>
        </div>
        <span class="urgent-hero-badge is-ok">✓ תקין</span>
      </div>
    `;
    return;
  }

  const criticalCount = top3.filter((t) => t.urgency === "CRITICAL" || t.sla_breached).length;
  container.className = "urgent-hero urgent-alert";

  if (mobile) {
    const headline =
      criticalCount > 0 ? `${criticalCount} לטיפול דחוף` : `${top3.length} לטיפול`;
    container.innerHTML = `
      <div class="urgent-hero-head compact">
        <h1 class="urgent-hero-title">${headline}</h1>
      </div>
      <div class="urgent-list">
        ${top3.map(renderUrgentRow).join("")}
      </div>
    `;
    return;
  }

  const headline =
    criticalCount > 0
      ? `${criticalCount} קריאות דורשות טיפול מיידי`
      : `${top3.length} קריאות דורשות את תשומת ליבך`;

  const badgeText =
    criticalCount > 0 ? `🚨 דחוף` : `${top3.length} לטיפול`;
  const badgeClass = criticalCount > 0 ? "" : "is-ok";

  container.innerHTML = `
    <div class="urgent-hero-head">
      <div>
        <h1 class="urgent-hero-title">${headline}</h1>
        <div class="urgent-hero-subtitle">הקריאות הבוערות ביותר כרגע – לחץ כדי לעבור לאזור הרלוונטי.</div>
      </div>
      <span class="urgent-hero-badge ${badgeClass}">${badgeText}</span>
    </div>
    <div class="urgency-legend" aria-label="מקרא דחיפות">🔴 קריטי · 🟠 גבוה · 🔵 בינוני</div>
    <div class="urgent-list">
      ${top3.map(renderUrgentRow).join("")}
    </div>
  `;
}

function renderUrgentRow(ticket) {
  const area = areasData.find((a) => a.id === ticket.area_id);
  const areaName = area ? area.name : "";
  const urgencyClass =
    ticket.urgency === "CRITICAL"
      ? "is-critical"
      : ticket.urgency === "HIGH"
      ? "is-high"
      : "is-medium";

  const building = ticket.building_text_raw || "ללא בניין";
  const icon = getCategoryIcon(ticket.category);
  const ariaLabel = `קריאה: ${ticket.description} - ${building} - ${areaName}${ticket.sla_breached ? " - באיחור" : ""}`;

  if (isMobile()) {
    const lateFlag = ticket.sla_breached ? ` · <span class="sla-breach-inline">באיחור</span>` : "";
    return `
      <article
        class="urgent-row urgent-row-mobile ${urgencyClass}"
        role="button"
        tabindex="0"
        aria-label="${escapeHtml(ariaLabel)}"
        onclick="openTicketDetail(${ticket.id})"
        onkeydown="handleCardKeyDown(event, () => openTicketDetail(${ticket.id}))"
      >
        <div class="urgent-row-body">
          <div class="urgent-row-title">${icon} <span>${escapeHtml(ticket.description)}</span></div>
          <div class="urgent-row-sub">${escapeHtml(building)} · ${getTimeAgo(ticket.created_at)}${lateFlag}</div>
        </div>
        <div class="urgent-row-chevron" aria-hidden="true">‹</div>
      </article>
    `;
  }

  const urgencyLabel = getUrgencyLabel(ticket.urgency || "MEDIUM");
  const metadataId = `urgent-meta-${ticket.id}`;

  return `
    <article
      class="urgent-row ${urgencyClass}"
      role="button"
      tabindex="0"
      aria-label="${escapeHtml(ariaLabel)}"
      aria-describedby="${metadataId}"
      onclick="openTicketDetail(${ticket.id})"
      onkeydown="handleCardKeyDown(event, () => openTicketDetail(${ticket.id}))"
    >
      <div class="urgent-row-main">
        <span class="urgency-label ${getUrgencyClass(ticket.urgency || "MEDIUM")}">${urgencyLabel}</span>
        <div class="urgent-row-title">${icon}<span>${escapeHtml(ticket.description)}</span></div>
        <ul id="${metadataId}" class="urgent-row-meta">
          <li>${escapeHtml(building)}</li>
          <li>${escapeHtml(areaName)}</li>
          <li>נפתח ${getTimeAgo(ticket.created_at)}</li>
          ${ticket.sla_breached ? '<li class="sla-breach-inline">באיחור</li>' : ""}
        </ul>
      </div>
      <div class="urgent-row-cta">פרטים ←</div>
    </article>
  `;
}

function renderCompanyStats() {
  const stats = [
    {
      value: dashboardData.open_tickets,
      label: "קריאות פתוחות",
      className: "stat-open",
      icon: "📂",
    },
    {
      value: dashboardData.in_progress_tickets,
      label: "בטיפול עכשיו",
      className: "stat-progress",
      icon: "🔄",
    },
    {
      value: dashboardData.done_tickets,
      label: "הושלמו",
      className: "stat-done",
      icon: "✓",
    },
    {
      value: dashboardData.sla_breached_count,
      label: "מאחרות",
      className: "stat-sla",
      icon: "⚠️",
    },
  ];

  document.getElementById("company-stats").innerHTML = stats.map(statCard).join("");
}

function statCard({ value, label, className, icon }) {
  return `
    <article class="stat-card ${className}">
      <div class="stat-icon" aria-hidden="true">${icon}</div>
      <div class="stat-body">
        <div class="stat-value">${value}</div>
        <div class="stat-label">${label}</div>
      </div>
    </article>
  `;
}

function renderAreaCards() {
  const isSuperAdmin = currentUser?.role === "SUPER_ADMIN";
  document.getElementById("area-cards").innerHTML = dashboardData.areas
    .map((summary) => {
      const areaMeta = areasData.find((area) => area.id === summary.area_id);
      const buildingCount = areaMeta ? areaMeta.building_count : 0;
      const metaId = `area-card-meta-${summary.area_id}`;
      const ariaLabel = `אזור ${summary.area_name}. ${buildingCount} בניינים. ${summary.open_tickets} קריאות פתוחות. ${summary.sla_breached_count > 0 ? `${summary.sla_breached_count} מאחרות.` : "ללא מאחרות."}`;

      let primaryBadge;
      if (summary.sla_breached_count > 0) {
        primaryBadge = `<span class="area-primary-badge is-danger">🚨 ${summary.sla_breached_count} מאחרות</span>`;
      } else if (summary.open_tickets > 0) {
        primaryBadge = `<span class="area-primary-badge is-warning">${summary.open_tickets} פתוחות</span>`;
      } else {
        primaryBadge = `<span class="area-primary-badge is-ok">✓ תקין</span>`;
      }

      return `
        <article
          class="area-card"
          role="button"
          tabindex="0"
          aria-label="${escapeHtml(ariaLabel)}"
          aria-describedby="${metaId}"
          onclick="showArea(${summary.area_id})"
          onkeydown="handleCardKeyDown(event, () => showArea(${summary.area_id}))"
        >
          <div class="area-card-top">
            <div>
              <div class="area-title">${escapeHtml(summary.area_name)}</div>
              <div class="area-subtitle">${buildingCount} בניינים באחריות האזור</div>
              ${
                summary.manager_name
                  ? `<div class="area-manager">👤 ${escapeHtml(summary.manager_name)}</div>`
                  : `<div class="area-manager" style="color:var(--danger)">⚠️ ללא מנהל אזור</div>`
              }
            </div>
            ${primaryBadge}
          </div>
          <div id="${metaId}" class="area-card-stats">
            <span><strong>${summary.open_tickets}</strong> פתוחות</span>
            <span>·</span>
            <span><strong>${summary.in_progress_tickets}</strong> בטיפול</span>
            <span>·</span>
            <span><strong>${summary.done_tickets}</strong> הושלמו</span>
          </div>
          <div class="area-card-footer" id="area-card-footer-${summary.area_id}">
            <span>${summary.total_tickets} קריאות סה"כ</span>
            <span class="area-card-cta">פתח אזור ←</span>
          </div>
        </article>
      `;
    })
    .join("");

  // Load profit indicator for super admins asynchronously (non-blocking)
  if (isSuperAdmin) {
    dashboardData.areas.forEach(summary => {
      const footer = document.getElementById(`area-card-footer-${summary.area_id}`);
      const card = footer?.closest(".area-card");
      if (card) loadAreaCardProfit(summary.area_id, card);
    });
  }
}

function renderCompanyAlerts() {
  const alertAreas = [...dashboardData.areas]
    .filter((area) => area.sla_breached_count > 0 || area.open_tickets > 2)
    .sort((left, right) => right.sla_breached_count - left.sla_breached_count);
  const insightsTab = document.getElementById("dashboard-tab-insights");
  if (insightsTab) {
    insightsTab.textContent = `התראות ותובנות (${alertAreas.length})`;
  }

  document.getElementById("company-alerts").innerHTML = alertAreas.length
    ? alertAreas
        .slice(0, 5)
        .map(
          (area) => `
          <article
            class="alert-card ${area.sla_breached_count > 0 ? "is-danger" : "is-warning"}"
            role="button"
            tabindex="0"
            aria-label="${escapeHtml(`התראה לאזור ${area.area_name}. ${area.sla_breached_count > 0 ? `${area.sla_breached_count} מאחרות ו-${area.open_tickets} קריאות פתוחות` : `${area.open_tickets} קריאות פתוחות דורשות מעקב`}`)}"
            onclick="showArea(${area.area_id})"
            onkeydown="handleCardKeyDown(event, () => showArea(${area.area_id}))"
          >
            <div class="alert-title">${escapeHtml(area.area_name)}</div>
            <div class="alert-body">
              ${
                area.sla_breached_count > 0
                  ? `${area.sla_breached_count} מאחרות ו-${area.open_tickets} קריאות פתוחות`
                  : `${area.open_tickets} קריאות פתוחות דורשות מעקב`
              }
            </div>
            <div class="alert-meta">${area.manager_name ? `מנהל אזור: ${escapeHtml(area.manager_name)}` : "ללא מנהל אזור"}</div>
          </article>
        `
        )
        .join("")
    : `<div class="empty-state">אין כרגע אזורים שמאותתים על סיכון חריג.</div>`;
}

function renderDailySummary() {
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();

  const createdToday = allTickets.filter(
    (t) => new Date(t.created_at).getTime() >= todayStart
  );
  const closedToday = allTickets.filter(
    (t) => t.completed_at && new Date(t.completed_at).getTime() >= todayStart
  );
  const criticalNow = allTickets.filter(
    (t) => t.urgency === "CRITICAL" && t.status !== "DONE"
  );

  const avgResponseHours = calcAvgResponseHours(allTickets);
  const topSupplier = findTopSupplier(allTickets);

  const insights = [
    {
      icon: "🆕",
      title: "קריאות חדשות היום",
      body: `${createdToday.length} קריאות חדשות נפתחו מתחילת היום.`,
      empty: createdToday.length === 0,
    },
    {
      icon: closedToday.length > 0 ? "✅" : "✓",
      title: "נסגרו היום",
      body:
        closedToday.length > 0
          ? `${closedToday.length} קריאות כבר נסגרו היום.`
          : "עדיין לא נסגרו קריאות היום.",
      empty: closedToday.length === 0,
    },
    {
      icon: "⏱️",
      title: "זמן תגובה ממוצע",
      body:
        avgResponseHours != null
          ? `ממוצע של ${avgResponseHours} שעות מפתיחה לסגירה.`
          : "אין עדיין מספיק קריאות סגורות למדידה.",
      empty: avgResponseHours == null,
    },
    {
      icon: "🏆",
      title: "ספק בולט",
      body: topSupplier
        ? `${topSupplier.name} – הכי פעיל עם ${topSupplier.count} קריאות.`
        : "עדיין אין מספיק מידע על ספקים.",
      empty: topSupplier == null,
    },
  ];

  if (criticalNow.length > 0) {
    insights.unshift({
      icon: "🚨",
      title: "קריאות קריטיות פתוחות",
      body: `${criticalNow.length} קריאות בדרגה קריטית ממתינות לטיפול.`,
      empty: false,
    });
  }

  document.getElementById("daily-summary").innerHTML = insights
    .map(
      (insight) => `
      <div class="insight-card is-metric ${insight.empty ? "is-empty" : ""}">
        <div class="insight-icon" aria-hidden="true">${insight.icon}</div>
        <div>
          <div class="insight-title">${insight.title}</div>
          <div class="insight-body">${insight.body}</div>
        </div>
      </div>
    `
    )
    .join("");
}

function calcAvgResponseHours(tickets) {
  const closed = tickets.filter((t) => t.completed_at && t.created_at);
  if (closed.length === 0) return null;

  const totalMs = closed.reduce((sum, t) => {
    return sum + (new Date(t.completed_at) - new Date(t.created_at));
  }, 0);
  const avgMs = totalMs / closed.length;
  return Math.round(avgMs / (1000 * 60 * 60));
}

function findTopSupplier(tickets) {
  const counts = {};
  for (const t of tickets) {
    if (t.assigned_supplier) {
      const name = t.assigned_supplier.name;
      counts[name] = (counts[name] || 0) + 1;
    }
  }
  const entries = Object.entries(counts);
  if (entries.length === 0) return null;
  entries.sort((a, b) => b[1] - a[1]);
  return { name: entries[0][0], count: entries[0][1] };
}

function renderCompanyMapCard() {
  const card = document.getElementById("map-card");
  const withCoords = allBuildings.filter(hasCoordinates);

  if (withCoords.length === 0) {
    card.classList.add("hidden");
    return;
  }
  card.classList.remove("hidden");

  document.getElementById("map-summary").textContent = `${withCoords.length} בניינים על המפה`;

  // Delay map init so container has layout dimensions, then watch for scroll into view
  setTimeout(() => {
    renderCompanyMap(withCoords);
    observeMapVisibility("company-map", companyMap);
  }, 200);
}

/* ================ Area view ================ */

async function showArea(areaId, options = {}) {
  currentView = "area";
  currentAreaId = areaId;
  if (!options.keepPanel) {
    activeAreaPanel = "overview";
  }
  document.getElementById("dashboard-view").classList.add("hidden");
  document.getElementById("area-view").classList.remove("hidden");
  setSidebarActive("dashboard"); // area view is accessed from dashboard context
  window.scrollTo(0, 0);

  const [summary, tickets, buildings, workers, areaMeta] = await Promise.all([
    api(`/areas/${areaId}/summary`),
    api(`/areas/${areaId}/tickets`),
    api(`/areas/${areaId}/buildings`),
    api(`/areas/${areaId}/workers`),
    api(`/areas/${areaId}`),
  ]);

  areaDetailsCache[areaId] = { summary, tickets, buildings, workers, areaMeta };
  renderArea(summary, tickets, buildings, workers, areaMeta);
  updateAreaSwitcherDropdown();
  document.title = `${summary.area_name} | BayitPro אחזקה`;
  updateRefreshTime();
}

function renderMyDayStrip(summary, openTickets, workers) {
  const urgentCount = openTickets.filter(
    (t) => t.urgency === "CRITICAL" || t.sla_breached,
  ).length;
  const lateCount = Number(summary.sla_breached_count || 0);
  const todayIdx = new Date().getDay();
  const workingToday = workers.filter((w) => {
    const sched = w.schedule || w.working_days || [];
    if (Array.isArray(sched) && sched.length) {
      return sched.includes(todayIdx) || sched.includes(DAY_NAMES[todayIdx]);
    }
    return w.is_active !== false;
  }).length;

  return `
    <div class="my-day-strip" role="group" aria-label="המצב שלי היום">
      <button type="button" class="my-day-cell is-danger" onclick="showAreaPanel('tickets', true)">
        <div class="md-value">${urgentCount}</div>
        <div class="md-label">דחופות</div>
      </button>
      <button type="button" class="my-day-cell is-success" onclick="showAreaPanel('workers', true)">
        <div class="md-value">${workingToday}</div>
        <div class="md-label">עובדים היום</div>
      </button>
      <button type="button" class="my-day-cell is-warning" onclick="showAreaPanel('tickets', true)">
        <div class="md-value">${lateCount}</div>
        <div class="md-label">מאחרות</div>
      </button>
    </div>
  `;
}

function renderArea(summary, tickets, buildings, workers, areaMeta) {
  const openTickets = [...tickets].filter((t) => t.status !== "DONE").sort(compareTickets);
  const criticalCount = openTickets.filter((t) => t.urgency === "CRITICAL" || t.sla_breached).length;
  renderAreaBreadcrumb(summary.area_name);

  /* --- My Day strip (AREA_MANAGER on mobile only) --- */
  const myDayHost = document.getElementById("area-my-day");
  if (myDayHost) {
    if (currentUser && currentUser.role === "AREA_MANAGER" && isMobile()) {
      myDayHost.innerHTML = renderMyDayStrip(summary, openTickets, workers);
      myDayHost.classList.remove("hidden");
    } else {
      myDayHost.innerHTML = "";
      myDayHost.classList.add("hidden");
    }
  }

  /* --- Hero: top urgent in this area --- */
  const hero = document.getElementById("area-urgent-hero");
  const top3 = openTickets.slice(0, 3);
  const mobile = isMobile();

  if (top3.length === 0) {
    hero.className = "urgent-hero urgent-calm";
    if (mobile) {
      hero.innerHTML = `
        <div class="urgent-hero-head compact">
          <h1 class="urgent-hero-title">הכול תחת שליטה ✓</h1>
          <div class="urgent-hero-subtitle">${escapeHtml(summary.area_name)} · ${buildings.length} בניינים</div>
        </div>
      `;
    } else {
      hero.innerHTML = `
        <div class="urgent-hero-head">
          <div>
            <h1 class="urgent-hero-title">${escapeHtml(summary.area_name)} – הכול תחת שליטה</h1>
            <div class="urgent-hero-subtitle">
              ${areaMeta.manager ? `מנהל אזור: ${escapeHtml(areaMeta.manager.name)} · ` : ""}
              ${buildings.length} בניינים באזור
            </div>
          </div>
          <span class="urgent-hero-badge is-ok">✓ תקין</span>
        </div>
      `;
    }
  } else {
    hero.className = criticalCount > 0 ? "urgent-hero urgent-alert" : "urgent-hero";
    const headline =
      criticalCount > 0
        ? `${criticalCount} קריאות דורשות טיפול מיידי ב${summary.area_name}`
        : `${summary.area_name} – ${top3.length} קריאות לטיפול`;

    const mobileHead = `
      <div class="urgent-hero-head compact">
        <h1 class="urgent-hero-title">${criticalCount > 0 ? `${criticalCount} לטיפול דחוף` : `${top3.length} לטיפול`}</h1>
      </div>
    `;
    const desktopHead = `
      <div class="urgent-hero-head">
        <div>
          <h1 class="urgent-hero-title">${headline}</h1>
          <div class="urgent-hero-subtitle">
            ${areaMeta.manager ? `מנהל אזור: ${escapeHtml(areaMeta.manager.name)} · ` : ""}
            ${buildings.length} בניינים באזור
          </div>
        </div>
        ${
          criticalCount > 0
            ? `<span class="urgent-hero-badge">🚨 דחוף</span>`
            : `<span class="urgent-hero-badge is-ok">${top3.length} לטיפול</span>`
        }
      </div>
      <div class="urgency-legend" aria-label="מקרא דחיפות">🔴 קריטי · 🟠 גבוה · 🔵 בינוני</div>
    `;

    const rowsHtml = top3
      .map((ticket) => {
        const building = ticket.building_text_raw || "ללא בניין";
        const urgencyClass = getUrgencyClass(ticket.urgency || "MEDIUM");
        const icon = getCategoryIcon(ticket.category);
        const urgencyLabel = getUrgencyLabel(ticket.urgency || "MEDIUM");
        const metadataId = `area-urgent-meta-${ticket.id}`;

        if (mobile) {
          const lateFlag = ticket.sla_breached ? ` · <span class="sla-breach-inline">באיחור</span>` : "";
          return `
            <article
              class="urgent-row urgent-row-mobile ${urgencyClass}"
              role="button"
              tabindex="0"
              aria-label="${escapeHtml(`${ticket.description} - ${building}${ticket.sla_breached ? " - באיחור" : ""}`)}"
              onclick="focusTicket(${ticket.id})"
              onkeydown="handleCardKeyDown(event, () => focusTicket(${ticket.id}))"
            >
              <div class="urgent-row-body">
                <div class="urgent-row-title">${icon}<span>${escapeHtml(ticket.description)}</span></div>
                <div class="urgent-row-sub">${escapeHtml(building)} · ${getTimeAgo(ticket.created_at)}${lateFlag}</div>
              </div>
              <div class="urgent-row-chevron" aria-hidden="true">‹</div>
            </article>
          `;
        }

        return `
          <article
            class="urgent-row ${urgencyClass}"
            role="button"
            tabindex="0"
            aria-label="${escapeHtml(`קריאה באזור ${summary.area_name}: ${ticket.description} - ${building}${ticket.sla_breached ? " - באיחור" : ""}`)}"
            aria-describedby="${metadataId}"
            onclick="focusTicket(${ticket.id})"
            onkeydown="handleCardKeyDown(event, () => focusTicket(${ticket.id}))"
          >
            <div class="urgent-row-main">
              <span class="urgency-label ${urgencyClass}">${urgencyLabel}</span>
              <div class="urgent-row-title">${icon}<span>${escapeHtml(ticket.description)}</span></div>
              <ul id="${metadataId}" class="urgent-row-meta">
                <li>${escapeHtml(building)}</li>
                <li>נפתח ${getTimeAgo(ticket.created_at)}</li>
                ${ticket.sla_breached ? '<li class="sla-breach-inline">באיחור</li>' : ""}
              </ul>
            </div>
            <div class="urgent-row-cta">גלול לקריאה ←</div>
          </article>
        `;
      })
      .join("");

    hero.innerHTML = `
      ${mobile ? mobileHead : desktopHead}
      <div class="urgent-list">${rowsHtml}</div>
    `;
  }

  /* --- Area stats --- */
  document.getElementById("area-stats").innerHTML = [
    statCard({ value: summary.open_tickets, label: "פתוחות", className: "stat-open", icon: "📂" }),
    statCard({ value: summary.in_progress_tickets, label: "בטיפול", className: "stat-progress", icon: "🔄" }),
    statCard({ value: summary.done_tickets, label: "הושלמו", className: "stat-done", icon: "✓" }),
    statCard({ value: summary.sla_breached_count, label: "מאחרות", className: "stat-sla", icon: "⚠️" }),
  ].join("");

  /* --- Ticket list --- */
  document.getElementById("area-tickets").innerHTML = openTickets.length
    ? `<div class="ticket-legend" aria-label="מקרא דחיפות">🔴 קריטי · 🟠 גבוה · 🔵 בינוני</div>${openTickets
        .map(renderTicket)
        .join("")}`
    : `<div class="empty-state">אין כרגע קריאות פעילות באזור הזה.</div>`;

  /* --- Buildings list --- */
  document.getElementById("area-buildings").innerHTML = buildings.length
    ? buildings.map((building) => renderBuildingCard(building, tickets)).join("")
    : `<div class="empty-state">אין עדיין בניינים באזור.</div>`;

  /* --- Setup wizard for empty areas --- */
  if (buildings.length === 0) {
    renderAreaSetupWizard(currentAreaId);
  }

  document.getElementById("area-workers").innerHTML = workers.length
    ? workers.map(renderAreaWorkerCard).join("")
    : `<div class="empty-state">אין עדיין עובדי שטח משויכים לאזור הזה.</div>`;

  const areaTabWorkers = document.getElementById("area-tab-workers");
  if (areaTabWorkers) {
    areaTabWorkers.textContent = `עובדים (${workers.length})`;
  }
  const areaTabTickets = document.getElementById("area-tab-tickets");
  if (areaTabTickets) {
    areaTabTickets.textContent = `קריאות (${openTickets.length})`;
  }
  const areaTabBuildings = document.getElementById("area-tab-buildings");
  if (areaTabBuildings) {
    areaTabBuildings.textContent = `בניינים (${buildings.length})`;
  }

  // Hide payroll/schedule tabs for workers
  const payrollTab = document.getElementById("area-tab-payroll");
  const scheduleTab = document.getElementById("area-tab-schedule");
  if (currentUser && currentUser.role === "WORKER") {
    if (payrollTab) payrollTab.classList.add("hidden");
    if (scheduleTab) scheduleTab.classList.add("hidden");
  } else {
    if (payrollTab) payrollTab.classList.remove("hidden");
    if (scheduleTab) scheduleTab.classList.remove("hidden");
  }

  /* --- Area map --- */
  const areaMapCard = document.getElementById("area-map-card");
  const withCoords = buildings.filter(hasCoordinates);
  if (withCoords.length === 0) {
    areaMapCard.classList.add("hidden");
  } else {
    areaMapCard.classList.remove("hidden");
    setTimeout(() => {
      renderAreaMap(buildings, summary);
      observeMapVisibility("area-map");
    }, 200);
  }

  showAreaPanel(activeAreaPanel, true);
}

function renderTicket(ticket) {
  const building = ticket.building_text_raw || "";
  const categoryLabel = CATEGORY_LABELS[ticket.category] || ticket.category;
  const categoryIcon = getCategoryIcon(ticket.category);
  const urgency = ticket.urgency || "MEDIUM";

  if (isMobile()) {
    const lateFlag = ticket.sla_breached ? ` · <span class="tc-late">באיחור</span>` : "";
    const sub = `${escapeHtml(building || "ללא בניין")} · ${getTimeAgo(ticket.created_at)}${lateFlag}`;
    const chips = [];
    if (urgency === "CRITICAL") {
      chips.push(`<span class="tc-chip tc-chip-urgent">דחוף</span>`);
    } else if (urgency === "HIGH") {
      chips.push(`<span class="tc-chip tc-chip-high">חשוב</span>`);
    }
    if (ticket.status && ticket.status !== "OPEN") {
      chips.push(`<span class="tc-chip tc-chip-status tc-chip-status-${ticket.status}">${STATUS_LABELS[ticket.status] || ticket.status}</span>`);
    }
    return `
      <article
        id="ticket-${ticket.id}"
        class="ticket-card-mobile urgency-${urgency}"
        tabindex="0"
        role="button"
        aria-label="${escapeHtml(`${ticket.description} - ${building}`)}"
        onclick="focusTicket(${ticket.id})"
        onkeydown="handleCardKeyDown(event, () => focusTicket(${ticket.id}))"
      >
        <div class="tc-edge" aria-hidden="true"></div>
        <div class="tc-body">
          <div class="tc-title">${categoryIcon} <span>${escapeHtml(ticket.description)}</span></div>
          <div class="tc-sub">${sub}</div>
          ${chips.length ? `<div class="tc-chips">${chips.join("")}</div>` : ""}
        </div>
        <div class="tc-chevron" aria-hidden="true">‹</div>
      </article>
    `;
  }

  return `
    <article id="ticket-${ticket.id}" class="ticket-card urgency-${urgency}" tabindex="-1">
      <div class="ticket-pills">
        <span class="pill pill-urgency-${urgency}">${URGENCY_LABELS[urgency] || urgency}</span>
        <span class="pill pill-cat-${ticket.category}">${categoryIcon} ${categoryLabel}</span>
        ${building ? `<span class="pill pill-building"><span role="img" aria-label="בניין">🏢</span> ${escapeHtml(building)}</span>` : ""}
        <span class="pill pill-status-${ticket.status}">${STATUS_LABELS[ticket.status] || ticket.status}</span>
      </div>
      <p class="ticket-description">${escapeHtml(ticket.description)}</p>
      <div class="ticket-meta">
        <span class="ticket-meta-item">נפתח ${getTimeAgo(ticket.created_at)}</span>
        ${ticket.assigned_supplier ? `<span class="ticket-meta-item">ספק: ${escapeHtml(ticket.assigned_supplier.name)}</span>` : ""}
        ${ticket.sla_breached ? `<span class="ticket-meta-item sla-breach">⚠️ באיחור</span>` : ""}
        <span class="ticket-id">${ticket.public_id || ""}</span>
      </div>
    </article>
  `;
}

function renderBuildingCard(building, tickets) {
  const buildingTickets = tickets.filter((ticket) => {
    const text = (ticket.building_text_raw || "").trim();
    return text && (text === building.address_text || text === building.name);
  });
  const openTickets = buildingTickets.filter((t) => t.status !== "DONE");
  const openCount = openTickets.length;
  const hasCritical = openTickets.some((t) => t.urgency === "CRITICAL" || t.sla_breached);

  let pillClass = "";
  let pillText = "✓ ללא קריאות פתוחות";
  if (openCount > 0 && hasCritical) {
    pillClass = "is-danger";
    pillText = `🚨 ${openCount} דחופות`;
  } else if (openCount > 0) {
    pillClass = "is-warning";
    pillText = `${openCount} פתוחות`;
  }

  let focusLine;
  if (openCount > 0) {
    const sorted = [...openTickets].sort(compareTickets);
    const top = sorted[0];
    focusLine = `<div class="building-focus-line"><span aria-hidden="true">⚠️</span> ${getCategoryIcon(top.category)} ${escapeHtml(truncate(top.description, 55))}</div>`;
  } else {
    const nextCleaning = getNextCleaningSummary(building);
    focusLine = `<div class="building-focus-line muted">${nextCleaning}</div>`;
  }

  const workerTag = building.current_worker
    ? `<div class="worker-tag"><span class="worker-avatar">${getInitials(building.current_worker.name)}</span>${escapeHtml(building.current_worker.name)}</div>`
    : `<div class="worker-tag is-missing"><span class="worker-avatar">!</span>ללא עובד משויך</div>`;

  const cardClass = hasCritical ? "has-critical" : openCount > 0 ? "has-open" : "";
  const metaId = `building-meta-${building.id}`;
  const ariaLabel = `בניין ${building.name}. ${openCount > 0 ? `${openCount} קריאות פתוחות` : "ללא קריאות פתוחות"}. ${building.num_floors ? `${building.num_floors} קומות.` : ""} ${building.has_elevator ? "כולל מעלית." : "ללא מעלית."}`;

  return `
    <article
      class="building-card ${cardClass}"
      role="button"
      tabindex="0"
      aria-label="${escapeHtml(ariaLabel)}"
      aria-describedby="${metaId}"
      onclick="showBuilding(${building.id})"
      onkeydown="handleCardKeyDown(event, () => showBuilding(${building.id}))"
    >
      <div class="building-card-top">
        <div>
          <div class="building-title">${escapeHtml(building.name)}</div>
          <div class="building-address">${escapeHtml(building.address_text)}${building.city ? `, ${escapeHtml(building.city)}` : ""}</div>
        </div>
        <span class="building-open-pill ${pillClass}">${pillText}</span>
      </div>
      ${focusLine}
      ${workerTag}
      <ul id="${metaId}" class="building-mini-meta">
        ${building.num_floors ? `<li><span role="img" aria-label="קומות">🏢</span> ${building.num_floors} קומות</li>` : ""}
        ${building.has_elevator ? `<li><span role="img" aria-label="מעלית">🛗</span> מעלית</li>` : `<li>ללא מעלית</li>`}
        ${building.has_parking ? `<li><span role="img" aria-label="חניון">🅿️</span> חניון</li>` : ""}
      </ul>
    </article>
  `;
}

function renderAreaWorkerCard(worker) {
  const statusClass = !worker.is_active
    ? "is-inactive"
    : worker.critical_ticket_count > 0
    ? "is-critical"
    : worker.open_ticket_count > 0
    ? "is-busy"
    : "is-ready";

  let statusText = "פנוי";
  if (!worker.is_active) {
    statusText = "לא פעיל";
  } else if (worker.critical_ticket_count > 0) {
    statusText = `${worker.critical_ticket_count} קריטיות פתוחות`;
  } else if (worker.open_ticket_count > 0) {
    statusText = `${worker.open_ticket_count} קריאות פתוחות`;
  }

  return `
    <article class="worker-card ${statusClass}" onclick="openWorkerDetail(${worker.id})" style="cursor:pointer" tabindex="0" role="button" aria-label="פרטי עובד ${escapeHtml(worker.name)}">
      <div class="worker-card-top">
        <div class="worker-card-id">
          <span class="worker-card-avatar">${getInitials(worker.name)}</span>
          <div>
            <div class="worker-card-name">${escapeHtml(worker.name)}</div>
            <div class="worker-card-phone" dir="ltr">${escapeHtml(worker.phone_number)}</div>
          </div>
        </div>
        <span class="worker-state-badge ${statusClass}">${statusText}</span>
      </div>

      <div class="worker-metrics">
        <div class="worker-metric">
          <span class="worker-metric-value">${worker.assigned_building_count}</span>
          <span class="worker-metric-label">בניינים</span>
        </div>
        <div class="worker-metric">
          <span class="worker-metric-value">${worker.open_ticket_count}</span>
          <span class="worker-metric-label">פתוחות</span>
        </div>
        <div class="worker-metric">
          <span class="worker-metric-value">${worker.critical_ticket_count}</span>
          <span class="worker-metric-label">קריטיות</span>
        </div>
      </div>

      ${worker.assigned_buildings.length
        ? `<div class="worker-building-block">
             <div class="worker-section-label">בניינים באחריות</div>
             <div class="worker-building-list">
               ${worker.assigned_buildings.map(b => `<span class="worker-building-pill">${escapeHtml(b.name)}</span>`).join("")}
             </div>
           </div>`
        : `<div class="worker-empty-note">כרגע ללא בניינים משויכים</div>`
      }
      <div class="worker-card-cta">לחץ לפרטים מלאים ←</div>
    </article>
  `;
}

/* ================ Worker detail modal ================ */

let _wdWorkerId = null;

async function openWorkerDetail(workerId, yearMonth) {
  _wdWorkerId = workerId;
  const modal = document.getElementById("worker-detail-modal");
  const body = document.getElementById("worker-detail-body");
  body.innerHTML = '<div class="loading-state">טוען פרטי עובד...</div>';
  modal.classList.remove("hidden");

  const now = new Date();
  const ym = yearMonth || `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const [ymYear, ymMonth] = ym.split("-").map(Number);
  const firstOfMonth = `${ym}-01`;
  // Last day of the month or today (whichever is earlier)
  const lastOfMonth = new Date(ymYear, ymMonth, 0).toISOString().slice(0, 10);
  const todayStr = now.toISOString().slice(0, 10);
  const toDate = lastOfMonth < todayStr ? lastOfMonth : todayStr;

  try {
    const [attendance, payroll] = await Promise.all([
      api(`/attendance?worker_id=${workerId}&from=${firstOfMonth}&to=${toDate}`),
      api(`/payroll/worker/${workerId}?from=${firstOfMonth}&to=${toDate}`),
    ]);

    // Find worker data from cached area workers
    const areaState = currentAreaId ? areaDetailsCache[currentAreaId] : null;
    const worker = areaState?.workers?.find(w => w.id === workerId) || { id: workerId, name: "", phone_number: "", assigned_buildings: [] };

    const statusClass = !worker.is_active ? "is-inactive"
      : worker.critical_ticket_count > 0 ? "is-critical"
      : worker.open_ticket_count > 0 ? "is-busy" : "is-ready";

    // Attendance table (last 15 records)
    const recent = attendance.slice(0, 15);
    const attRows = recent.length
      ? recent.map(r => {
          const dateStr = new Date(r.work_date).toLocaleDateString("he-IL", { weekday: "short", day: "2-digit", month: "2-digit" });
          const inStr = r.clock_in_at ? new Date(r.clock_in_at).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" }) : "—";
          const outStr = r.clock_out_at ? new Date(r.clock_out_at).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" }) : "בפנים";
          const dur = r.duration_minutes ? `${Math.floor(r.duration_minutes / 60)}:${String(r.duration_minutes % 60).padStart(2, "0")} שע'` : "";
          const swapTag = r.is_swap_day ? '<span class="sched-badge open" style="font-size:0.7rem">החלפה</span>' : "";
          return `<tr><td>${dateStr}</td><td>${escapeHtml(r.building_name)}</td><td dir="ltr">${inStr}</td><td dir="ltr">${outStr}</td><td>${dur}</td><td>${swapTag}</td></tr>`;
        }).join("")
      : `<tr><td colspan="6" class="muted" style="text-align:center;padding:1rem">אין נוכחות החודש</td></tr>`;

    // Payroll summary
    const payrollHtml = payroll.buildings.length
      ? `<div class="wd-payroll-grid">
           ${payroll.buildings.map(b => `
             <div class="wd-payroll-row">
               <span class="wd-bldg-name">${escapeHtml(b.building_name)}</span>
               <span class="muted">${b.days_worked} ימים × ₪${b.daily_rate}</span>
               ${b.swap_days ? `<span class="payroll-swap">+${b.swap_days} החלפות</span>` : ""}
               ${b.deduction_days ? `<span class="payroll-ded">-${b.deduction_days} ניכויים</span>` : ""}
               <span class="fin-revenue wd-earnings">₪${b.earnings.toLocaleString()}</span>
             </div>`).join("")}
           <div class="wd-payroll-total">
             <span>סה"כ לתשלום החודש</span>
             <span class="fin-revenue" style="font-size:1.1rem;font-weight:800">₪${payroll.net_earnings.toLocaleString()}</span>
           </div>
         </div>`
      : `<div class="muted" style="padding:.5rem 0">אין נוכחות רשומה החודש</div>`;

    body.innerHTML = `
      <div class="wd-header">
        <div class="worker-card-id">
          <span class="worker-card-avatar ${statusClass}" style="width:52px;height:52px;font-size:1.2rem">${getInitials(worker.name)}</span>
          <div>
            <div style="font-size:1.3rem;font-weight:700">${escapeHtml(worker.name)}</div>
            <div class="worker-card-phone" dir="ltr">${escapeHtml(worker.phone_number)}</div>
          </div>
        </div>
        <div class="wd-actions">
          <input type="month" class="wd-month-picker schedule-date-input" value="${ym}"
            onchange="openWorkerDetail(${worker.id}, this.value)" title="בחר חודש">
          <a class="btn-primary wd-wa-btn" href="https://wa.me/${(worker.phone_number || "").replace(/\D/g, "")}" target="_blank" rel="noopener">WhatsApp</a>
          <button class="btn-ghost" onclick="openWorkerSwapFromDetail(${worker.id}, '${escapeHtml(worker.name)}')">+ החלפה</button>
          <button class="btn-ghost" onclick="openWorkerPayrollReport(${worker.id}, '${escapeHtml(worker.name)}')">דוח שכר</button>
        </div>
      </div>

      <div class="wd-metrics">
        <div class="wd-metric"><span class="wd-metric-val">${worker.assigned_building_count ?? 0}</span><span class="wd-metric-label">בניינים</span></div>
        <div class="wd-metric"><span class="wd-metric-val">${worker.open_ticket_count ?? 0}</span><span class="wd-metric-label">קריאות פתוחות</span></div>
        <div class="wd-metric"><span class="wd-metric-val fin-revenue">${payroll.total_days_worked + payroll.total_swap_days}</span><span class="wd-metric-label">ימי נוכחות החודש</span></div>
        <div class="wd-metric"><span class="wd-metric-val fin-revenue">₪${payroll.net_earnings.toLocaleString()}</span><span class="wd-metric-label">שכר צבור החודש</span></div>
      </div>

      <div class="wd-body">
        ${worker.assigned_buildings?.length ? `
          <div>
            <div class="wd-section-title">בניינים באחריות (${worker.assigned_buildings.length})</div>
            <div class="wd-buildings-chips">
              ${worker.assigned_buildings.map(b => `<span class="wd-building-chip">${escapeHtml(b.name)}</span>`).join("")}
            </div>
          </div>` : ""}

        <div>
          <div class="wd-section-title">נוכחות – ${new Date(ymYear, ymMonth - 1).toLocaleString("he-IL", { month: "long", year: "numeric" })}</div>
          <div class="wd-att-table-wrap">
            <table class="wd-att-table">
              <thead><tr><th>תאריך</th><th>בניין</th><th>כניסה</th><th>יציאה</th><th>משך</th><th></th></tr></thead>
              <tbody>${attRows}</tbody>
            </table>
          </div>
        </div>

        <div>
          <div class="wd-section-title">שכר – ${new Date(ymYear, ymMonth - 1).toLocaleString("he-IL", { month: "long", year: "numeric" })}</div>
          ${payrollHtml}
        </div>
      </div>
    `;
  } catch (e) {
    body.innerHTML = `<div class="empty-state">שגיאה בטעינת הנתונים: ${escapeHtml(String(e))}</div>`;
  }
}

function closeWorkerDetailModal(e) {
  if (e && e.target !== document.getElementById("worker-detail-modal")) return;
  document.getElementById("worker-detail-modal").classList.add("hidden");
}

/* ================ Building modal ================ */

async function showBuilding(buildingId) {
  const building = await api(`/buildings/${buildingId}`);
  const areaState = currentAreaId ? areaDetailsCache[currentAreaId] : null;
  const areaTickets = areaState ? areaState.tickets : [];
  const buildingTickets = areaTickets.filter((ticket) => {
    const text = (ticket.building_text_raw || "").trim();
    return text && (text === building.address_text || text === building.name);
  });
  const openTickets = buildingTickets.filter((t) => t.status !== "DONE").sort(compareTickets);

  const nextCleaning = getNextCleaningSummary(building);
  const hasActionNeeded = openTickets.length > 0 || !building.current_worker;

  const workerBlock = building.current_worker
    ? `
      <div class="modal-action-item">
        <div class="modal-action-icon">👷</div>
        <div>
          <div class="modal-action-label">עובד ניקיון נוכחי</div>
          <div class="modal-action-value">${escapeHtml(building.current_worker.name)}</div>
        </div>
      </div>
    `
    : `
      <div class="modal-action-item">
        <div class="modal-action-icon is-danger">!</div>
        <div>
          <div class="modal-action-label">עובד ניקיון</div>
          <div class="modal-action-value" style="color:var(--danger)">לא משויך עובד</div>
        </div>
      </div>
    `;

  const openBlock = `
    <div class="modal-action-item">
      <div class="modal-action-icon ${openTickets.length > 0 ? "is-warning" : ""}">${openTickets.length > 0 ? "⚠️" : "✓"}</div>
      <div>
        <div class="modal-action-label">קריאות פתוחות</div>
        <div class="modal-action-value">${openTickets.length} קריאות</div>
      </div>
    </div>
  `;

  const nextCleaningBlock = `
    <div class="modal-action-item">
      <div class="modal-action-icon">🧹</div>
      <div>
        <div class="modal-action-label">ניקיון הבא</div>
        <div class="modal-action-value">${nextCleaning}</div>
      </div>
    </div>
  `;

  const entryBlock = `
    <div class="modal-action-item">
      <div class="modal-action-icon">🔑</div>
      <div>
        <div class="modal-action-label">קוד כניסה</div>
        <div class="modal-action-value">${building.entry_code || "לא הוגדר"}</div>
      </div>
    </div>
  `;

  document.getElementById("building-modal-body").innerHTML = `
    <div class="modal-title">${escapeHtml(building.name)}</div>
    <div class="modal-subtitle">${escapeHtml(building.address_text)}${building.city ? `, ${escapeHtml(building.city)}` : ""}</div>

    <div class="modal-section">
      <div class="modal-section-title ${hasActionNeeded ? "warn" : ""}">לטיפול עכשיו</div>
      <div class="modal-action-panel ${hasActionNeeded ? "is-alert" : ""}">
        <div class="modal-action-row">
          ${openBlock}
          ${workerBlock}
          ${nextCleaningBlock}
          ${entryBlock}
        </div>
      </div>
    </div>

    ${
      openTickets.length > 0
        ? `
      <div class="modal-section">
        <div class="modal-section-title warn">קריאות פתוחות בבניין</div>
        ${openTickets.slice(0, 5).map(renderTicket).join("")}
      </div>
    `
        : ""
    }

    <div class="modal-section">
      <div class="modal-section-title">פרטי הבניין</div>
      <div class="modal-detail-grid">
        ${modalDetail("קומות", building.num_floors || "לא הוגדר")}
        ${modalDetail("מעלית", building.has_elevator ? "כן" : "לא")}
        ${modalDetail("חניון", building.has_parking ? "כן" : "לא")}
      </div>
      ${
        building.notes
          ? `<div class="insight-card" style="margin-top:12px"><div class="insight-body">${escapeHtml(building.notes)}</div></div>`
          : ""
      }
    </div>

    <div class="modal-section">
      <div class="modal-section-title">לוח ניקיונות שבועי</div>
      ${
        building.cleaning_schedules.length
          ? [...building.cleaning_schedules]
              .sort((a, b) => a.day_of_week - b.day_of_week)
              .map(
                (schedule) => `
                <div class="schedule-row">
                  <span class="schedule-day">יום ${DAY_NAMES[schedule.day_of_week]}</span>
                  <span class="schedule-time">${schedule.time}</span>
                  <span class="schedule-desc">${escapeHtml(schedule.description)}</span>
                </div>
              `
              )
              .join("")
          : `<div class="empty-state">אין עדיין לוח ניקיונות מוגדר לבניין הזה.</div>`
      }
    </div>

    ${
      buildingTickets.length > openTickets.length
        ? `
      <div class="modal-section">
        <div class="modal-section-title">היסטוריית קריאות באזור</div>
        ${buildingTickets
          .filter((t) => t.status === "DONE")
          .slice(0, 4)
          .map(renderTicket)
          .join("")}
      </div>
    `
        : ""
    }
  `;

  document.getElementById("building-modal").classList.remove("hidden");
}

function closeBuildingModal(event) {
  if (event && event.target !== event.currentTarget) return;
  document.getElementById("building-modal").classList.add("hidden");
}

function showDashboard() {
  currentView = "dashboard";
  currentAreaId = null;
  activeAreaPanel = "overview";
  document.getElementById("dashboard-view").classList.remove("hidden");
  document.getElementById("area-view").classList.add("hidden");
  document.getElementById("area-breadcrumb").innerHTML = "";
  document.title = DEFAULT_TITLE;
  setSidebarActive("dashboard");
  window.scrollTo(0, 0);
  loadDashboard();
}

/* ================ WebSocket + toasts ================ */

function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocol}//${location.host}/ws`);

  ws.onopen = () => {
    document.getElementById("connection-status").className = "status-dot connected";
    document.getElementById("connection-text").textContent = "מחובר";
    renderRefreshLabel();
  };

  ws.onclose = () => {
    document.getElementById("connection-status").className = "status-dot disconnected";
    document.getElementById("connection-text").textContent = "מנותק";
    renderRefreshLabel();
    setTimeout(connectWebSocket, 3000);
  };

  ws.onerror = () => ws.close();

  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    handleRealtimeEvent(message);
  };
}

function handleRealtimeEvent(message) {
  if (
    message.type !== "new_ticket" &&
    message.type !== "updated_ticket" &&
    message.type !== "created_ticket"
  ) {
    return;
  }

  const ticket = message.data;
  updateRefreshTime();
  showToast(
    message.type === "updated_ticket" ? "קריאה עודכנה" : "🆕 קריאה חדשה",
    `${CATEGORY_LABELS[ticket.category] || ticket.category}${ticket.area_name ? ` · ${ticket.area_name}` : ""}`
  );

  const eventAreaId = message.data?.area_id ?? message.area_id;
  if (currentView === "area" && currentAreaId) {
    // Only refresh if this event belongs to the current area
    if (!eventAreaId || eventAreaId === currentAreaId) {
      showArea(currentAreaId, { keepPanel: true });
    }
    return;
  }

  loadDashboard();
}

const TOAST_TYPES = new Set(["success", "error", "info", "warning"]);

function showToast(title, bodyOrType) {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  const isType = TOAST_TYPES.has(bodyOrType);
  toast.className = `toast${isType ? ` toast-${bodyOrType}` : ""}`;
  toast.innerHTML = isType
    ? `<div class="toast-title">${title}</div>`
    : `<div class="toast-title">${title}</div>${bodyOrType ? `<div class="toast-body">${bodyOrType}</div>` : ""}`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add("toast-out");
    setTimeout(() => toast.remove(), 280);
  }, 3800);
}

/* ================ Sim panel ================ */

function toggleSimPanel() {
  const panel = document.getElementById("sim-content");
  const button = document.getElementById("sim-toggle");
  const isHidden = panel.classList.toggle("hidden");
  button.setAttribute("aria-expanded", String(!isHidden));
}

async function loadSimAreas() {
  const areas = await api("/areas");
  const select = document.getElementById("sim-area");
  select.innerHTML = areas
    .map(
      (area) =>
        `<option value="${area.whatsapp_number}">${area.name} · ${area.whatsapp_number}</option>`
    )
    .join("");
}

async function sendSimulation() {
  const button = document.getElementById("sim-send");
  const result = document.getElementById("sim-result");

  button.disabled = true;
  button.textContent = "שולח...";
  result.className = "hidden";
  result.innerHTML = "";

  try {
    const response = await fetch("/webhook/whatsapp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        phone_number: document.getElementById("sim-phone").value,
        text: document.getElementById("sim-message").value,
        receiving_number: document.getElementById("sim-area").value,
      }),
    });

    const data = await response.json();
    result.className = "sim-success";
    result.innerHTML = `
      <strong>${data.action_taken === "created_ticket" ? "נוצרה קריאה חדשה" : "קריאה עודכנה"}</strong><br>
      מספר קריאה: ${data.ticket_public_id}<br>
      קטגוריה: ${CATEGORY_LABELS[data.category] || data.category}<br>
      ${data.area_name ? `אזור: ${data.area_name}<br>` : ""}
      ${data.assigned_supplier ? `ספק משויך: ${data.assigned_supplier}<br>` : ""}
      סטטוס: ${STATUS_LABELS[data.status] || data.status}
    `;
    result.classList.remove("hidden");
    document.getElementById("sim-message").value = "";
  } catch (error) {
    result.className = "sim-error";
    result.textContent = `שגיאה: ${error.message}`;
    result.classList.remove("hidden");
  } finally {
    button.disabled = false;
    button.textContent = "שלח הודעה";
  }
}

/* ================ Maps ================ */

function ensureMap(mapRef, elementId, center, zoom) {
  if (typeof L === "undefined") {
    const target = document.getElementById(elementId);
    if (target) {
      target.innerHTML = `<div class="empty-state">מפה לא זמינה כרגע.</div>`;
    }
    return null;
  }

  if (mapRef) {
    mapRef.invalidateSize();
    return mapRef;
  }

  const map = L.map(elementId, {
    zoomControl: true,
    scrollWheelZoom: false,
  }).setView(center, zoom);

  const tileLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);

  // Ensure all tiles render after load
  tileLayer.on("load", () => map.invalidateSize());

  return map;
}

function buildingRiskColor(building) {
  const buildingTickets = allTickets.filter((ticket) => {
    const text = (ticket.building_text_raw || "").trim();
    return text && (text === building.address_text || text === building.name);
  });
  const openTickets = buildingTickets.filter((t) => t.status !== "DONE");
  const hasCritical = openTickets.some((t) => t.urgency === "CRITICAL" || t.sla_breached);

  if (hasCritical) return "#b91c1c"; // danger
  if (openTickets.length > 0) return "#b45309"; // warning
  return "#15803d"; // ok
}

function renderCompanyMap(buildings) {
  companyMap = ensureMap(companyMap, "company-map", [32.078, 34.79], 12);
  if (!companyMap) return;

  if (companyMapLayer) {
    companyMap.removeLayer(companyMapLayer);
  }

  companyMapLayer = L.layerGroup();
  const bounds = [];

  buildings.forEach((building) => {
    const color = buildingRiskColor(building);
    const openCount = allTickets.filter((t) => {
      if (t.status === "DONE") return false;
      const text = (t.building_text_raw || "").trim();
      return text && (text === building.address_text || text === building.name);
    }).length;

    const marker = L.circleMarker([building.latitude, building.longitude], {
      radius: 10,
      weight: 2,
      color: "#ffffff",
      fillColor: color,
      fillOpacity: 0.95,
    });

    marker.bindPopup(`
      <div class="map-popup">
        <h4>${building.name}</h4>
        <p>${building.address_text}</p>
        <p>${openCount > 0 ? `${openCount} קריאות פתוחות` : "תקין"}</p>
      </div>
    `);
    marker.addTo(companyMapLayer);
    bounds.push([building.latitude, building.longitude]);
  });

  companyMapLayer.addTo(companyMap);

  if (bounds.length) {
    companyMap.fitBounds(bounds, { padding: [40, 40] });
  }

  // Ensure tiles load fully
  setTimeout(() => companyMap.invalidateSize(), 300);
}

function renderAreaMap(buildings, summary) {
  const withCoords = buildings.filter(hasCoordinates);
  areaMap = ensureMap(areaMap, "area-map", [32.078, 34.79], 13);
  if (!areaMap) return;

  if (areaMapLayer) {
    areaMap.removeLayer(areaMapLayer);
  }

  areaMapLayer = L.layerGroup();
  const bounds = [];

  withCoords.forEach((building) => {
    const color = buildingRiskColor(building);
    const openTickets = (areaDetailsCache[summary.area_id]?.tickets || []).filter((ticket) => {
      const text = (ticket.building_text_raw || "").trim();
      return text && (text === building.address_text || text === building.name);
    });
    const openCount = openTickets.filter((t) => t.status !== "DONE").length;

    const marker = L.circleMarker([building.latitude, building.longitude], {
      radius: 10,
      weight: 2,
      color: "#ffffff",
      fillColor: color,
      fillOpacity: 0.95,
    });

    marker.bindPopup(`
      <div class="map-popup">
        <h4>${building.name}</h4>
        <p>${building.address_text}</p>
        <p>${openCount > 0 ? `${openCount} קריאות פתוחות` : "תקין"}</p>
      </div>
    `);
    marker.addTo(areaMapLayer);
    bounds.push([building.latitude, building.longitude]);
  });

  areaMapLayer.addTo(areaMap);

  if (bounds.length) {
    areaMap.fitBounds(bounds, { padding: [28, 28] });
  } else {
    areaMap.setView([32.078, 34.79], 12);
  }

  setTimeout(() => areaMap.invalidateSize(), 300);
}

/* ================ Map visibility observer ================ */

function observeMapVisibility(elementId, mapRefGetter) {
  const el = document.getElementById(elementId);
  if (!el || typeof IntersectionObserver === "undefined") return;

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          // Use the global variable since it may have been reassigned
          const map = elementId === "company-map" ? companyMap : areaMap;
          if (map) map.invalidateSize();
          observer.disconnect();
        }
      }
    },
    { threshold: 0.1 }
  );
  observer.observe(el);
}

/* ================ Helpers ================ */

function compareTickets(left, right) {
  if (left.sla_breached !== right.sla_breached) {
    return left.sla_breached ? -1 : 1;
  }
  const leftUrgency = URGENCY_PRIORITY[left.urgency] || 0;
  const rightUrgency = URGENCY_PRIORITY[right.urgency] || 0;
  if (leftUrgency !== rightUrgency) {
    return rightUrgency - leftUrgency;
  }
  return new Date(right.created_at) - new Date(left.created_at);
}

function getNextCleaningSummary(building) {
  if (!building.cleaning_schedules || !building.cleaning_schedules.length) {
    return "אין לוח ניקיונות מוגדר";
  }
  const next = [...building.cleaning_schedules].sort(
    (a, b) => a.day_of_week - b.day_of_week || a.time.localeCompare(b.time)
  )[0];
  return `יום ${DAY_NAMES[next.day_of_week]} ב-${next.time}`;
}

function modalDetail(label, value) {
  return `
    <div class="modal-detail-row">
      <span class="modal-detail-label">${label}</span>
      <span class="modal-detail-value">${value}</span>
    </div>
  `;
}

function hasCoordinates(building) {
  return typeof building.latitude === "number" && typeof building.longitude === "number";
}

function getTimeAgo(dateStr) {
  const now = new Date();
  const date = new Date(dateStr);
  const diffMs = now - date;
  const diffMinutes = Math.max(0, Math.floor(diffMs / 60000));

  if (diffMinutes < 1) return "הרגע";
  if (diffMinutes < 60) return `לפני ${diffMinutes} דקות`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `לפני ${diffHours} שעות`;
  const diffDays = Math.floor(diffHours / 24);
  return formatDaysAgo(diffDays);
}

function updateRefreshTime() {
  const now = new Date();
  lastUpdatedAt = now;
  renderRefreshLabel();
}

function getInitials(name) {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].charAt(0);
  return parts[0].charAt(0) + parts[parts.length - 1].charAt(0);
}

function truncate(text, max) {
  if (!text) return "";
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}

function escapeHtml(text) {
  if (text == null) return "";
  const div = document.createElement("div");
  div.textContent = String(text);
  return div.innerHTML;
}

function handleCardKeyDown(event, action) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    action();
  }
}

function showDashboardPanel(panel, preserveScroll = false) {
  activeDashboardPanel = panel;
  const panels = ["overview", "areas", "insights", "financial", "my-schedule"];
  panels.forEach((panelName) => {
    const panelEl = document.getElementById(`dashboard-${panelName}-panel`);
    const tabEl = document.getElementById(`dashboard-tab-${panelName}`);
    const isActive = panelName === panel;
    if (panelEl) {
      // Keep worker-only/non-worker-only class; only toggle hidden for activity
      const isWorkerOnly = panelEl.classList.contains("worker-only");
      const isNonWorkerOnly = panelEl.classList.contains("non-worker-only");
      const isWorker = currentUser?.role === "WORKER";
      if ((isWorkerOnly && !isWorker) || (isNonWorkerOnly && isWorker)) {
        panelEl.classList.add("hidden");
        return;
      }
      panelEl.classList.toggle("hidden", !isActive);
      panelEl.setAttribute("aria-hidden", String(!isActive));
    }
    if (tabEl) {
      tabEl.classList.toggle("is-active", isActive);
      tabEl.setAttribute("aria-selected", String(isActive));
      tabEl.tabIndex = isActive ? 0 : -1;
    }
  });

  if (panel === "financial") {
    initCompanyFinancialDatePickers();
    loadCompanyFinancial();
  }
  if (panel === "my-schedule") {
    loadMyWeeklySchedule();
  }

  if (!preserveScroll) {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
}

function showAreaPanel(panel, preserveScroll = false) {
  activeAreaPanel = panel;
  const panels = ["overview", "tickets", "buildings", "workers", "schedule", "payroll"];
  panels.forEach((panelName) => {
    const panelEl = document.getElementById(`area-${panelName}-panel`);
    const tabEl = document.getElementById(`area-tab-${panelName}`);
    const isActive = panelName === panel;
    if (panelEl) {
      panelEl.classList.toggle("hidden", !isActive);
      panelEl.setAttribute("aria-hidden", String(!isActive));
    }
    if (tabEl) {
      tabEl.classList.toggle("is-active", isActive);
      tabEl.setAttribute("aria-selected", String(isActive));
      tabEl.tabIndex = isActive ? 0 : -1;
    }
  });

  if (panel === "schedule") {
    initScheduleDatePicker();
    loadSchedule();
  }

  if (panel === "payroll") {
    loadAreaPayrollPanel(currentAreaId);
    initAreaFinancialDatePickers();
    loadAreaFinancial();
  }

  if (panel === "financial") {
    initCompanyFinancialDatePickers();
    loadCompanyFinancial();
  }

  if (!preserveScroll) {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
}

function focusTicket(ticketId) {
  // Open the detail slide-over (richer than scrolling to card)
  openTicketDetail(ticketId);
}

function renderAreaBreadcrumb(areaName) {
  document.getElementById("area-breadcrumb").innerHTML = `
    <li><a href="#" onclick="event.preventDefault(); showDashboard()">דשבורד ראשי</a></li>
    <li class="breadcrumb-separator" aria-hidden="true">/</li>
    <li aria-current="page">${escapeHtml(areaName)}</li>
  `;
}

function setupDemoToggle() {
  const showDemo = new URLSearchParams(window.location.search).get("demo") === "true";
  const panel = document.getElementById("sim-panel");
  if (!showDemo) {
    panel.style.display = "none";
    return;
  }
  panel.style.display = "";
}

function setupUserMenu() {
  const toggle = document.getElementById("user-menu-toggle");
  const menu = document.getElementById("user-menu");
  if (!toggle || !menu) return;

  document.addEventListener("click", (event) => {
    const inside = toggle.contains(event.target) || menu.contains(event.target);
    if (!inside) {
      menu.classList.add("hidden");
      toggle.setAttribute("aria-expanded", "false");
    }
  });
}

function toggleUserMenu() {
  const toggle = document.getElementById("user-menu-toggle");
  const menu = document.getElementById("user-menu");
  if (!toggle || !menu) return;

  const isHidden = menu.classList.toggle("hidden");
  toggle.setAttribute("aria-expanded", String(!isHidden));
}

function startRefreshTicker() {
  window.setInterval(renderRefreshLabel, 1000);
}

function renderRefreshLabel() {
  const el = document.getElementById("last-refresh");
  if (!el) return;

  if (!lastUpdatedAt) {
    el.textContent = "טרם נטען";
    el.dateTime = "";
    el.classList.remove("is-live");
    return;
  }

  el.dateTime = lastUpdatedAt.toISOString();
  const isConnected = ws && ws.readyState === WebSocket.OPEN;
  if (isConnected) {
    el.textContent = "עודכן בזמן אמת";
    el.classList.add("is-live");
    return;
  }

  el.classList.remove("is-live");
  const diffSeconds = Math.max(0, Math.floor((Date.now() - lastUpdatedAt.getTime()) / 1000));
  if (diffSeconds < 60) {
    el.textContent = `עודכן לפני ${diffSeconds} שניות`;
    return;
  }

  el.textContent = `עודכן ${lastUpdatedAt.toLocaleTimeString("he-IL", {
    hour: "2-digit",
    minute: "2-digit",
  })}`;
}

function formatDaysAgo(n) {
  if (n === 1) return "לפני יום אחד";
  if (n === 2) return "לפני יומיים";
  return `לפני ${n} ימים`;
}

function getUrgencyClass(urgency) {
  if (urgency === "CRITICAL") return "is-critical";
  if (urgency === "HIGH") return "is-high";
  if (urgency === "MEDIUM") return "is-medium";
  return "is-low";
}

function getUrgencyLabel(urgency) {
  return URGENCY_LABELS[urgency] || "בינוני";
}

function getCategoryIcon(category) {
  const icon = CATEGORY_ICONS[category] || "🔧";
  const label = CATEGORY_LABELS[category] || "כללי";
  return `<span class="category-icon" role="img" aria-label="${escapeHtml(label)}">${icon}</span>`;
}

// =============================================================================
// SCHEDULE & SWAPS
// =============================================================================

let scheduleData = null;
let swapContext = { buildingId: null, buildingName: null, originalWorkerName: null };
let allAreaWorkers = [];

// --- Date picker init & helpers ---

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function initScheduleDatePicker() {
  const picker = document.getElementById("schedule-date-picker");
  if (picker && !picker.value) picker.value = todayISO();
}

function hebrewDow(dow) {
  return ["ראשון","שני","שלישי","רביעי","חמישי","שישי","שבת"][dow] || "";
}

// Return ISO date string of the nearest upcoming occurrence of db_dow (0=Sun…6=Sat)
function nearestDayOfWeek(dbDow) {
  const today = new Date();
  // JS getDay(): 0=Sun,1=Mon,...,6=Sat  ← same as db_dow
  const todayDow = today.getDay();
  let diff = dbDow - todayDow;
  if (diff <= 0) diff += 7;
  const target = new Date(today);
  target.setDate(today.getDate() + diff);
  return target.toISOString().slice(0, 10);
}

function jumpToDate(isoDate) {
  const picker = document.getElementById("schedule-date-picker");
  if (picker) { picker.value = isoDate; loadSchedule(); }
}

// --- Load daily schedule ---

async function loadSchedule() {
  const picker = document.getElementById("schedule-date-picker");
  const d = picker ? picker.value : todayISO();
  const container = document.getElementById("schedule-content");
  if (!container) return;
  container.innerHTML = '<div class="loading-state">טוען לוח שיבוצים...</div>';

  try {
    const params = new URLSearchParams({ date: d });
    // Always scope to the current area when inside area view
    if (currentAreaId) {
      params.set("area_id", currentAreaId);
    } else if (currentUser && currentUser.role === "AREA_MANAGER" && currentUser.area_id) {
      params.set("area_id", currentUser.area_id);
    }
    scheduleData = await api(`/schedule/daily?${params}`);
    renderSchedule(scheduleData);
  } catch (e) {
    container.innerHTML = `<div class="empty-state">שגיאה בטעינת הלוח: ${escapeHtml(String(e))}</div>`;
  }
}

function renderSchedule(data) {
  const container = document.getElementById("schedule-content");
  if (!container) return;

  const dayLabel = hebrewDow(data.day_of_week);
  const dateLabel = data.date;

  let html = `<div class="schedule-day-label">יום ${dayLabel} · ${dateLabel}</div>`;

  if (!data.workers.length && !data.unassigned_buildings.length) {
    const dayName = hebrewDow(data.day_of_week);
    html += `
      <div class="schedule-empty-card">
        <div class="schedule-empty-icon">📅</div>
        <div class="schedule-empty-title">אין שיבוצי ניקיון ביום ${dayName}</div>
        <div class="schedule-empty-sub">נסה לבחור יום אחר שיש בו שיבוצים</div>
        <div class="schedule-jump-btns">
          ${["ראשון","שני","שלישי","רביעי","חמישי","שישי"].map((name, i) => {
            const d = nearestDayOfWeek(i === 6 ? 0 : i + 1);
            return `<button class="sched-day-jump" onclick="jumpToDate('${d}')">${name}</button>`;
          }).join("")}
        </div>
      </div>`;
    container.innerHTML = html;
    return;
  }

  html += '<div class="schedule-workers-grid">';
  for (const worker of data.workers) {
    html += renderWorkerCard(worker, data.date);
  }
  html += '</div>';

  if (data.unassigned_buildings.length) {
    html += `
      <div class="schedule-unassigned">
        <p class="eyebrow" style="color:#ef4444">ללא עובד משובץ</p>
        <div class="schedule-workers-grid">
          ${data.unassigned_buildings.map(b => renderUnassignedBuilding(b, data.date)).join("")}
        </div>
      </div>`;
  }

  container.innerHTML = html;
}

function renderWorkerCard(worker, date) {
  const statusClass = worker.is_active ? "" : " worker-inactive";
  const criticalBadge = worker.total_critical_tickets
    ? `<span class="sched-badge critical">${worker.total_critical_tickets} קריטי</span>` : "";
  const openBadge = worker.total_open_tickets
    ? `<span class="sched-badge open">${worker.total_open_tickets} פתוח</span>` : "";

  const buildingsHtml = worker.buildings.map(b => renderScheduleBuilding(b, worker, date)).join("");

  return `
    <div class="sched-worker-card${statusClass}">
      <div class="sched-worker-head">
        <div class="sched-worker-avatar">${escapeHtml(worker.worker_name[0])}</div>
        <div class="sched-worker-info">
          <div class="sched-worker-name">${escapeHtml(worker.worker_name)}</div>
          <div class="sched-worker-phone" dir="ltr">${escapeHtml(worker.worker_phone)}</div>
        </div>
        <div class="sched-worker-badges">${criticalBadge}${openBadge}</div>
      </div>
      <div class="sched-buildings">${buildingsHtml}</div>
    </div>`;
}

function renderScheduleBuilding(b, worker, date) {
  const swapBadge = b.is_swap ? '<span class="sched-badge swap">החלפה</span>' : "";
  const ticketInfo = b.open_ticket_count
    ? `<span class="sched-ticket-count">${b.open_ticket_count} קריאות</span>` : "";
  const criticalInfo = b.critical_ticket_count
    ? `<span class="sched-ticket-count critical">${b.critical_ticket_count} קריטי</span>` : "";

  return `
    <div class="sched-building-row">
      <div class="sched-building-info">
        <span class="sched-time">${escapeHtml(b.schedule_time)}</span>
        <span class="sched-building-name">${escapeHtml(b.building_name)}</span>
        ${swapBadge}
        <div class="sched-tickets">${ticketInfo}${criticalInfo}</div>
      </div>
      <button class="sched-swap-btn" title="החלפת עובד"
        onclick="openSwapModal(${b.building_id}, '${escapeHtml(b.building_name)}', '${escapeHtml(worker.worker_name)}', '${escapeHtml(date)}')">
        החלפה
      </button>
    </div>`;
}

function renderUnassignedBuilding(b, date) {
  return `
    <div class="sched-worker-card unassigned-card">
      <div class="sched-building-row">
        <div class="sched-building-info">
          <span class="sched-time">${escapeHtml(b.schedule_time)}</span>
          <span class="sched-building-name">${escapeHtml(b.building_name)}</span>
          <span class="sched-badge warn">ללא עובד</span>
        </div>
        <button class="sched-swap-btn"
          onclick="openSwapModal(${b.building_id}, '${escapeHtml(b.building_name)}', 'לא משובץ', '${escapeHtml(date)}')">
          שיבוץ
        </button>
      </div>
    </div>`;
}

// --- Swap modal ---

async function openSwapModal(buildingId, buildingName, originalWorkerName, date) {
  swapContext = { buildingId, buildingName, originalWorkerName };

  document.getElementById("swap-building-name").textContent = buildingName;
  document.getElementById("swap-original-worker").textContent = originalWorkerName;
  document.getElementById("swap-date").value = date || todayISO();
  document.getElementById("swap-reason").value = "";
  document.getElementById("swap-error").classList.add("hidden");

  // Load workers for dropdown
  const select = document.getElementById("swap-replacement");
  select.innerHTML = '<option value="">טוען עובדים...</option>';

  try {
    const params = new URLSearchParams();
    if (currentUser && currentUser.role === "AREA_MANAGER" && currentUser.area_id) {
      // use area workers already loaded
    }
    // Fetch workers scoped to current area view, or fall back to user's area
    let workers = [];
    const areaIdForWorkers = currentAreaId || (currentUser && currentUser.area_id) || null;
    if (areaIdForWorkers) {
      workers = await api(`/areas/${areaIdForWorkers}/workers`);
    } else if (areasData && areasData.length) {
      // super admin outside an area view — gather workers from all areas
      const results = await Promise.all(areasData.map(a => api(`/areas/${a.id}/workers`).catch(() => [])));
      workers = results.flat();
    }
    allAreaWorkers = workers;

    select.innerHTML = '<option value="">בחר עובד מחליף</option>' +
      workers
        .filter(w => w.is_active)
        .map(w => `<option value="${w.id}">${escapeHtml(w.name)}</option>`)
        .join("");
  } catch {
    select.innerHTML = '<option value="">שגיאה בטעינת עובדים</option>';
  }

  document.getElementById("swap-modal").classList.remove("hidden");
}

function closeSwapModal(e) {
  if (e && e.target !== document.getElementById("swap-modal")) return;
  document.getElementById("swap-modal").classList.add("hidden");
}

async function submitSwap() {
  const date = document.getElementById("swap-date").value;
  const replacementId = parseInt(document.getElementById("swap-replacement").value, 10);
  const reason = document.getElementById("swap-reason").value.trim();
  const errorEl = document.getElementById("swap-error");

  if (!date) { errorEl.textContent = "יש לבחור תאריך"; errorEl.classList.remove("hidden"); return; }
  if (!replacementId) { errorEl.textContent = "יש לבחור עובד מחליף"; errorEl.classList.remove("hidden"); return; }

  errorEl.classList.add("hidden");

  try {
    await api("/schedule/swaps", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        date,
        building_id: swapContext.buildingId,
        replacement_worker_id: replacementId,
        reason: reason || null,
      }),
    });

    document.getElementById("swap-modal").classList.add("hidden");
    showToast(`החלפה נוצרה בהצלחה ל-${swapContext.buildingName}`, "success");
    loadSchedule();
  } catch (e) {
    let msg = "שגיאה ביצירת ההחלפה";
    try { msg = JSON.parse(e.message)?.detail || msg; } catch {}
    errorEl.textContent = msg;
    errorEl.classList.remove("hidden");
  }
}

// --- Swaps panel ---

async function showSwapsPanel() {
  document.getElementById("swaps-panel").classList.remove("hidden");
  await loadSwapsList();
}

function hideSwapsPanel() {
  document.getElementById("swaps-panel").classList.add("hidden");
}

async function loadSwapsList() {
  const container = document.getElementById("swaps-list");
  container.innerHTML = '<div class="loading-state">טוען החלפות...</div>';

  try {
    const today = todayISO();
    const inMonth = new Date(); inMonth.setDate(inMonth.getDate() + 30);
    const to = inMonth.toISOString().slice(0, 10);
    const params = new URLSearchParams({ from: today, to });
    if (currentAreaId) {
      params.set("area_id", currentAreaId);
    } else if (currentUser && currentUser.role === "AREA_MANAGER" && currentUser.area_id) {
      params.set("area_id", currentUser.area_id);
    }
    const swaps = await api(`/schedule/swaps?${params}`);
    renderSwapsList(swaps);
  } catch (e) {
    container.innerHTML = `<div class="empty-state">שגיאה: ${escapeHtml(String(e))}</div>`;
  }
}

function renderSwapsList(swaps) {
  const container = document.getElementById("swaps-list");
  if (!swaps.length) {
    container.innerHTML = '<div class="empty-state">אין החלפות מתוכננות ב-30 הימים הקרובים</div>';
    return;
  }

  container.innerHTML = `
    <div class="swaps-table">
      <div class="swaps-table-head">
        <span>תאריך</span><span>בניין</span><span>עובד מקורי</span><span>עובד מחליף</span><span>סיבה</span><span></span>
      </div>
      ${swaps.map(s => `
        <div class="swaps-table-row">
          <span>${escapeHtml(s.date)}</span>
          <span>${escapeHtml(s.building_name)}</span>
          <span>${escapeHtml(s.original_worker_name)}</span>
          <span class="swap-replacement-name">${escapeHtml(s.replacement_worker_name)}</span>
          <span class="swap-reason">${escapeHtml(s.reason || "—")}</span>
          <span>
            <button class="sched-cancel-btn" onclick="cancelSwap(${s.id})">ביטול</button>
          </span>
        </div>`).join("")}
    </div>`;
}

async function cancelSwap(swapId) {
  if (!confirm("לבטל את ההחלפה?")) return;
  try {
    await api(`/schedule/swaps/${swapId}`, { method: "DELETE" });
    showToast("ההחלפה בוטלה", "success");
    loadSwapsList();
    loadSchedule();
  } catch {
    showToast("שגיאה בביטול ההחלפה", "error");
  }
}

// =============================================================================
// ATTENDANCE & PAYROLL
// =============================================================================

let attendanceState = null;   // today's AttendanceRecord (or null)
let payrollReportWorkerId = null;

// ---------------------------------------------------------------------------
// Worker attendance widget
// ---------------------------------------------------------------------------

async function loadWorkerAttendanceWidget() {
  const widget = document.getElementById("worker-attendance-widget");
  if (!widget) return;
  if (!currentUser || currentUser.role !== "WORKER") return;

  widget.classList.remove("hidden");

  try {
    const [todayRec, buildings] = await Promise.all([
      api("/attendance/me/today"),
      api("/attendance/me/buildings"),
    ]);
    attendanceState = todayRec;
    renderAttendanceWidget(todayRec, buildings);
  } catch {
    widget.innerHTML = '<div class="attendance-error">שגיאה בטעינת נוכחות</div>';
  }
}

function renderAttendanceWidget(rec, buildings) {
  const widget = document.getElementById("worker-attendance-widget");

  if (rec && rec.clock_in_at && !rec.clock_out_at) {
    // Currently clocked in
    const since = new Date(rec.clock_in_at);
    const sinceStr = since.toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });
    const swapBadge = rec.is_swap_day ? '<span class="sched-badge open">החלפה</span>' : "";
    widget.innerHTML = `
      <div class="attendance-card clocked-in">
        <div class="attendance-status-row">
          <span class="attendance-dot active"></span>
          <span class="attendance-status-label">בעבודה כרגע</span>
          ${swapBadge}
        </div>
        <div class="attendance-building">${escapeHtml(rec.building_name)}</div>
        <div class="attendance-time">כניסה בשעה ${sinceStr}</div>
        <button class="attendance-btn clock-out-btn" onclick="clockOut()">סיים עבודה</button>
        <button class="btn-ghost attendance-report-btn" onclick="openMyPayrollReport()">דוח שכר שלי</button>
      </div>`;
  } else if (rec && rec.clock_out_at) {
    // Done for today
    const inStr = new Date(rec.clock_in_at).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });
    const outStr = new Date(rec.clock_out_at).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });
    widget.innerHTML = `
      <div class="attendance-card clocked-out">
        <div class="attendance-status-row">
          <span class="attendance-dot done"></span>
          <span class="attendance-status-label">עבודת היום הסתיימה</span>
        </div>
        <div class="attendance-building">${escapeHtml(rec.building_name)}</div>
        <div class="attendance-time">${inStr} – ${outStr} · ${rec.duration_minutes} דקות</div>
        <button class="btn-ghost attendance-report-btn" onclick="openMyPayrollReport()">דוח שכר שלי</button>
      </div>`;
  } else {
    // Not clocked in
    const opts = buildings.map(b =>
      `<option value="${b.id}" data-swap="${b.is_swap}">${escapeHtml(b.name)}${b.is_swap ? " (החלפה)" : ""}</option>`
    ).join("");
    widget.innerHTML = `
      <div class="attendance-card idle">
        <div class="attendance-status-row">
          <span class="attendance-dot idle"></span>
          <span class="attendance-status-label">לא בעבודה</span>
        </div>
        <div class="attendance-clock-in-row">
          <select id="clock-in-building" class="schedule-date-input attendance-select">
            <option value="">בחר בניין...</option>
            ${opts}
          </select>
          <button class="attendance-btn clock-in-btn" onclick="clockIn()">התחל עבודה</button>
        </div>
        <button class="btn-ghost attendance-report-btn" onclick="openMyPayrollReport()">דוח שכר שלי</button>
      </div>`;
  }
}

async function clockIn() {
  const select = document.getElementById("clock-in-building");
  const buildingId = parseInt(select?.value);
  if (!buildingId) { showToast("בחר בניין לפני התחלת עבודה", "error"); return; }

  const btn = document.querySelector(".clock-in-btn");
  if (btn) { btn.disabled = true; btn.textContent = "מאתר מיקום..."; }

  let position = null;
  let gpsNote = "";
  try {
    position = await getGPSPosition();
  } catch (err) {
    const reason = err.code === 1 ? "הרשאת מיקום נדחתה" : "GPS לא זמין";
    gpsNote = `נרשמת ידנית (${reason})`;
  }

  try {
    await api("/attendance/clock-in", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        building_id: buildingId,
        latitude: position?.coords.latitude ?? null,
        longitude: position?.coords.longitude ?? null,
      }),
    });
    showToast(gpsNote ? `כניסה נרשמה · ${gpsNote}` : "כניסה נרשמה בהצלחה", "success");
    loadWorkerAttendanceWidget();
  } catch (e) {
    showToast(`שגיאה: ${e}`, "error");
    if (btn) { btn.disabled = false; btn.textContent = "התחל עבודה"; }
  }
}

async function clockOut() {
  const btn = document.querySelector(".clock-out-btn");
  if (btn) { btn.disabled = true; btn.textContent = "מסיים..."; }

  let position = null;
  try { position = await getGPSPosition(); } catch {}

  try {
    await api("/attendance/clock-out", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        latitude: position?.coords.latitude ?? null,
        longitude: position?.coords.longitude ?? null,
      }),
    });
    showToast("יציאה נרשמה בהצלחה", "success");
    loadWorkerAttendanceWidget();
  } catch (e) {
    showToast(`שגיאה: ${e}`, "error");
    if (btn) { btn.disabled = false; btn.textContent = "סיים עבודה"; }
  }
}

function getGPSPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) { reject(new Error("Geolocation not supported")); return; }
    navigator.geolocation.getCurrentPosition(resolve, reject, {
      timeout: 8000,
      enableHighAccuracy: false,
    });
  });
}

// ---------------------------------------------------------------------------
// Area payroll panel
// ---------------------------------------------------------------------------

async function loadAreaPayrollPanel(areaId) {
  const today = new Date();
  const picker = document.getElementById("payroll-month-picker");
  if (picker && !picker.value) {
    picker.value = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
    picker.onchange = () => loadAreaPayrollSummary(areaId);
  }
  await Promise.all([
    loadLastEntryTable(areaId),
    loadAreaPayrollSummary(areaId),
    loadDeductionsList(areaId),
  ]);
}

async function loadLastEntryTable(areaId) {
  const container = document.getElementById("last-entry-table");
  if (!container) return;
  container.innerHTML = '<div class="loading-state">טוען...</div>';
  try {
    const entries = await api(`/attendance/last-entry?area_id=${areaId}`);
    if (!entries.length) {
      container.innerHTML = '<div class="empty-state">אין רשומות נוכחות</div>';
      return;
    }
    container.innerHTML = `
      <div class="last-entry-grid">
        <div class="le-head"><span>בניין</span><span>עובד אחרון</span><span>כניסה אחרונה</span></div>
        ${entries.map(e => {
          const timeStr = e.last_clock_in_at
            ? new Date(e.last_clock_in_at).toLocaleString("he-IL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
            : "—";
          const ago = e.last_clock_in_at ? timeAgo(new Date(e.last_clock_in_at)) : "";
          return `
            <div class="le-row">
              <span class="le-building">${escapeHtml(e.building_name)}</span>
              <span>${escapeHtml(e.last_worker_name || "—")}</span>
              <span class="le-time">${timeStr}<span class="le-ago">${ago}</span></span>
            </div>`;
        }).join("")}
      </div>`;
  } catch {
    container.innerHTML = '<div class="empty-state">שגיאה בטעינה</div>';
  }
}

async function loadAreaPayrollSummary(areaId) {
  const container = document.getElementById("area-payroll-summary");
  if (!container) return;
  const picker = document.getElementById("payroll-month-picker");
  const [year, month] = picker?.value
    ? picker.value.split("-").map(Number)
    : [new Date().getFullYear(), new Date().getMonth() + 1];

  container.innerHTML = '<div class="loading-state">טוען...</div>';
  try {
    const overview = await api(`/payroll/area/${areaId}?year=${year}&month=${month}`);
    renderAreaPayrollSummary(overview);
  } catch {
    container.innerHTML = '<div class="empty-state">שגיאה בטעינה</div>';
  }
}

function renderAreaPayrollSummary(overview) {
  const container = document.getElementById("area-payroll-summary");
  const monthLabel = new Date(overview.year, overview.month - 1).toLocaleString("he-IL", { month: "long", year: "numeric" });

  if (!overview.workers.length) {
    container.innerHTML = '<div class="empty-state">אין עובדים פעילים באזור</div>';
    return;
  }

  container.innerHTML = `
    <div class="payroll-info-bar">${monthLabel} · ${overview.working_days} ימי עבודה</div>
    <div class="payroll-workers-list">
      ${overview.workers.map(w => `
        <div class="payroll-worker-row">
          <div class="payroll-worker-name">
            ${escapeHtml(w.worker_name)}
            <button class="btn-ghost payroll-detail-btn" onclick="openWorkerPayrollReport(${w.worker_id}, '${escapeHtml(w.worker_name)}')">דוח</button>
          </div>
          <div class="payroll-worker-stats">
            <span>${w.total_buildings} בניינים</span>
            <span class="payroll-rate">תקרה: ₪${w.total_monthly_rate.toLocaleString()}</span>
            <span class="payroll-earned">שולם: ₪${w.total_earned.toLocaleString()}</span>
          </div>
          <div class="payroll-buildings-mini">
            ${w.buildings.map(b => `
              <div class="payroll-bldg-mini">
                <span class="payroll-bldg-name">${escapeHtml(b.building_name)}</span>
                <span>${b.days_worked}/${b.working_days_in_month} ימים</span>
                <span class="payroll-rate-mini">₪${b.daily_rate}/יום</span>
                ${b.deduction_days ? `<span class="payroll-ded">-${b.deduction_days} ניכוי</span>` : ""}
                ${b.swap_days ? `<span class="payroll-swap">+${b.swap_days} החלפות</span>` : ""}
              </div>`).join("")}
            ${!w.buildings.length ? '<div class="muted">אין נתוני נוכחות</div>' : ""}
          </div>
        </div>`).join("")}
    </div>`;
}

// ---------------------------------------------------------------------------
// Deductions
// ---------------------------------------------------------------------------

async function loadDeductionsList(areaId) {
  const container = document.getElementById("deductions-list");
  if (!container) return;
  container.innerHTML = '<div class="loading-state">טוען...</div>';

  const today = new Date();
  const firstOfMonth = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-01`;
  const todayStr = today.toISOString().slice(0, 10);

  try {
    const deductions = await api(`/payroll/deductions?from=${firstOfMonth}&to=${todayStr}`);
    if (!deductions.length) {
      container.innerHTML = '<div class="empty-state">אין ניכויים החודש</div>';
      return;
    }
    container.innerHTML = `
      <div class="swaps-table">
        <div class="swaps-table-head"><span>עובד</span><span>בניין</span><span>תאריך</span><span>סיבה</span><span></span></div>
        ${deductions.map(d => `
          <div class="swaps-table-row">
            <span>${escapeHtml(d.worker_name || "")}</span>
            <span>${escapeHtml(d.building_name)}</span>
            <span>${escapeHtml(String(d.work_date))}</span>
            <span class="swap-reason">${escapeHtml(d.reason || "—")}</span>
            <span><button class="sched-cancel-btn" onclick="deleteDeduction(${d.id})">מחק</button></span>
          </div>`).join("")}
      </div>`;
  } catch {
    container.innerHTML = '<div class="empty-state">שגיאה בטעינה</div>';
  }
}

async function showAddDeductionModal() {
  const modal = document.getElementById("deduction-modal");
  if (!modal) return;

  // Populate workers
  const workerSel = document.getElementById("ded-worker");
  try {
    const workers = await api(`/areas/${currentAreaId}/workers`);
    workerSel.innerHTML = workers.map(w => `<option value="${w.id}">${escapeHtml(w.name)}</option>`).join("");
    workerSel.onchange = () => populateDedBuildings();
    populateDedBuildings();
  } catch {
    workerSel.innerHTML = '<option>שגיאה</option>';
  }

  document.getElementById("ded-date").value = new Date().toISOString().slice(0, 10);
  document.getElementById("ded-reason").value = "";
  document.getElementById("ded-error").classList.add("hidden");
  modal.classList.remove("hidden");
}

async function populateDedBuildings() {
  const bldgSel = document.getElementById("ded-building");
  try {
    const buildings = allBuildings.filter(b => !currentAreaId || b.area_id === currentAreaId);
    bldgSel.innerHTML = buildings.map(b => `<option value="${b.id}">${escapeHtml(b.name)}</option>`).join("");
  } catch {
    bldgSel.innerHTML = '<option>שגיאה</option>';
  }
}

function closeDeductionModal(e) {
  if (e && e.target !== document.getElementById("deduction-modal")) return;
  document.getElementById("deduction-modal").classList.add("hidden");
}

async function submitDeduction() {
  const workerId = parseInt(document.getElementById("ded-worker").value);
  const buildingId = parseInt(document.getElementById("ded-building").value);
  const workDate = document.getElementById("ded-date").value;
  const reason = document.getElementById("ded-reason").value.trim();
  const errorEl = document.getElementById("ded-error");

  if (!workerId || !buildingId || !workDate) {
    errorEl.textContent = "יש למלא עובד, בניין ותאריך";
    errorEl.classList.remove("hidden");
    return;
  }
  errorEl.classList.add("hidden");

  try {
    await api("/payroll/deductions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ worker_id: workerId, building_id: buildingId, work_date: workDate, reason: reason || null }),
    });
    document.getElementById("deduction-modal").classList.add("hidden");
    showToast("ניכוי נשמר", "success");
    loadDeductionsList(currentAreaId);
    loadAreaPayrollSummary(currentAreaId);
  } catch (e) {
    errorEl.textContent = `שגיאה: ${e}`;
    errorEl.classList.remove("hidden");
  }
}

async function deleteDeduction(dedId) {
  if (!confirm("למחוק ניכוי זה?")) return;
  try {
    await api(`/payroll/deductions/${dedId}`, { method: "DELETE" });
    showToast("ניכוי נמחק", "success");
    loadDeductionsList(currentAreaId);
    loadAreaPayrollSummary(currentAreaId);
  } catch {
    showToast("שגיאה במחיקת ניכוי", "error");
  }
}

// ---------------------------------------------------------------------------
// Worker payroll report modal
// ---------------------------------------------------------------------------

function openWorkerPayrollReport(workerId, workerName) {
  payrollReportWorkerId = workerId;
  document.getElementById("payroll-report-title").textContent = `דוח שכר – ${workerName}`;
  const today = new Date();
  const firstOfMonth = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-01`;
  document.getElementById("payroll-report-from").value = firstOfMonth;
  document.getElementById("payroll-report-to").value = today.toISOString().slice(0, 10);
  document.getElementById("payroll-report-modal").classList.remove("hidden");
  fetchPayrollReport();
}

function openMyPayrollReport() {
  if (!currentUser?.worker_id) return;
  openWorkerPayrollReport(currentUser.worker_id, currentUser.full_name);
}

function closePayrollReportModal(e) {
  if (e && e.target !== document.getElementById("payroll-report-modal")) return;
  document.getElementById("payroll-report-modal").classList.add("hidden");
}

async function fetchPayrollReport() {
  const body = document.getElementById("payroll-report-body");
  if (!body || !payrollReportWorkerId) return;
  const from = document.getElementById("payroll-report-from").value;
  const to = document.getElementById("payroll-report-to").value;
  body.innerHTML = '<div class="loading-state">טוען דוח...</div>';

  try {
    const report = await api(`/payroll/worker/${payrollReportWorkerId}?from=${from}&to=${to}`);
    renderPayrollReport(report);
  } catch (e) {
    body.innerHTML = `<div class="empty-state">שגיאה: ${escapeHtml(String(e))}</div>`;
  }
}

function renderPayrollReport(report) {
  const body = document.getElementById("payroll-report-body");

  const summaryRow = (label, value, cls = "") =>
    `<div class="pr-summary-row ${cls}"><span>${label}</span><span>${value}</span></div>`;

  const buildingRows = report.buildings.map(b => `
    <div class="pr-building-row">
      <div class="pr-building-name">${escapeHtml(b.building_name)}</div>
      <div class="pr-building-stats">
        <span>₪${b.daily_rate}/יום</span>
        <span>${b.days_worked} ימים רגילים</span>
        ${b.swap_days ? `<span class="payroll-swap">+${b.swap_days} החלפות</span>` : ""}
        ${b.deduction_days ? `<span class="payroll-ded">-${b.deduction_days} ניכויים</span>` : ""}
        <span class="pr-building-total">₪${b.earnings.toLocaleString()}</span>
      </div>
    </div>`).join("");

  body.innerHTML = `
    <div class="pr-buildings">${buildingRows || '<div class="empty-state">אין נתוני נוכחות בתקופה זו</div>'}</div>
    <div class="pr-summary">
      ${summaryRow("ימי עבודה רגילים", report.total_days_worked)}
      ${report.total_swap_days ? summaryRow("ימי החלפה (שעות נוספות)", report.total_swap_days, "payroll-swap") : ""}
      ${report.total_deduction_days ? summaryRow("ניכויים", `${report.total_deduction_days} ימים`, "payroll-ded") : ""}
      ${summaryRow("שכר בסיס", `₪${report.total_regular_earnings.toLocaleString()}`)}
      ${report.total_swap_earnings ? summaryRow("תוספת החלפות", `₪${report.total_swap_earnings.toLocaleString()}`, "payroll-swap") : ""}
      ${report.total_deductions_amount ? summaryRow("סה\"כ ניכויים", `-₪${report.total_deductions_amount.toLocaleString()}`, "payroll-ded") : ""}
      ${summaryRow("סה\"כ לתשלום", `₪${report.net_earnings.toLocaleString()}`, "pr-total")}
    </div>`;
}

// ---------------------------------------------------------------------------
// Area financial summary
// ---------------------------------------------------------------------------

function _defaultFinancialRange() {
  const today = new Date();
  const from = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-01`;
  const to = today.toISOString().slice(0, 10);
  return { from, to };
}

function initAreaFinancialDatePickers() {
  const fromEl = document.getElementById("area-fin-from");
  const toEl = document.getElementById("area-fin-to");
  if (!fromEl || !toEl) return;
  if (!fromEl.value) {
    const { from, to } = _defaultFinancialRange();
    fromEl.value = from;
    toEl.value = to;
  }
}

function initCompanyFinancialDatePickers() {
  const fromEl = document.getElementById("company-fin-from");
  const toEl = document.getElementById("company-fin-to");
  if (!fromEl || !toEl) return;
  if (!fromEl.value) {
    const { from, to } = _defaultFinancialRange();
    fromEl.value = from;
    toEl.value = to;
  }
}

async function loadAreaFinancial() {
  const container = document.getElementById("area-financial-content");
  if (!container || !currentAreaId) return;
  const from = document.getElementById("area-fin-from")?.value;
  const to = document.getElementById("area-fin-to")?.value;
  if (!from || !to) return;

  container.innerHTML = '<div class="loading-state">טוען...</div>';
  try {
    const data = await api(`/payroll/area/${currentAreaId}/financial?from=${from}&to=${to}`);
    renderAreaFinancial(data, container);
  } catch {
    container.innerHTML = '<div class="empty-state">שגיאה בטעינת הנתונים</div>';
  }
}

function renderAreaFinancial(data, container) {
  const profitClass = data.profit >= 0 ? "fin-profit-pos" : "fin-profit-neg";
  const profitSign = data.profit >= 0 ? "+" : "";

  const buildingRows = data.buildings.map(b => `
    <div class="fin-row">
      <span class="fin-label">${escapeHtml(b.building_name)}</span>
      <span class="fin-rate muted">₪${b.monthly_rate.toLocaleString()}/חודש</span>
      <span class="fin-value fin-revenue">₪${b.revenue_in_range.toLocaleString()}</span>
    </div>`).join("");

  const workerRows = data.workers.map(w => `
    <div class="fin-row">
      <span class="fin-label">${escapeHtml(w.worker_name)}</span>
      <span class="fin-value fin-expense">-₪${w.expense_in_range.toLocaleString()}</span>
    </div>`).join("");

  container.innerHTML = `
    <div class="fin-summary-bar">
      <div class="fin-kpi">
        <span class="fin-kpi-label">הכנסות</span>
        <span class="fin-kpi-val fin-revenue">₪${data.total_revenue.toLocaleString()}</span>
      </div>
      <div class="fin-kpi">
        <span class="fin-kpi-label">הוצאות</span>
        <span class="fin-kpi-val fin-expense">₪${data.total_expenses.toLocaleString()}</span>
      </div>
      <div class="fin-kpi fin-kpi-main">
        <span class="fin-kpi-label">רווח / הפסד</span>
        <span class="fin-kpi-val ${profitClass}">${profitSign}₪${Math.abs(data.profit).toLocaleString()}</span>
      </div>
    </div>
    <div class="fin-breakdown">
      <div class="fin-section">
        <div class="fin-section-title fin-revenue-title">הכנסות לפי בניין</div>
        ${buildingRows || '<div class="muted">אין נתונים</div>'}
      </div>
      <div class="fin-section">
        <div class="fin-section-title fin-expense-title">הוצאות לפי עובד</div>
        ${workerRows || '<div class="muted">אין נתוני נוכחות</div>'}
      </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Company financial summary (super admin)
// ---------------------------------------------------------------------------

async function loadCompanyFinancial() {
  const container = document.getElementById("company-financial-content");
  if (!container) return;
  const from = document.getElementById("company-fin-from")?.value;
  const to = document.getElementById("company-fin-to")?.value;
  if (!from || !to) return;

  container.innerHTML = '<div class="loading-state">טוען...</div>';
  try {
    const data = await api(`/payroll/company/financial?from=${from}&to=${to}`);
    renderCompanyFinancial(data, container);
  } catch {
    container.innerHTML = '<div class="empty-state">שגיאה בטעינת הנתונים</div>';
  }
}

function renderCompanyFinancial(data, container) {
  renderFinancialChart(data);
  const profitClass = data.profit >= 0 ? "fin-profit-pos" : "fin-profit-neg";
  const profitSign = data.profit >= 0 ? "+" : "";

  const areaRows = data.areas.map(a => {
    const pc = a.profit >= 0 ? "fin-profit-pos" : "fin-profit-neg";
    const ps = a.profit >= 0 ? "+" : "";
    return `
      <div class="fin-area-row">
        <div class="fin-area-name">${escapeHtml(a.area_name)}</div>
        <div class="fin-area-stats">
          <span class="fin-revenue">הכנסות ₪${a.total_revenue.toLocaleString()}</span>
          <span class="fin-expense">הוצאות ₪${a.total_expenses.toLocaleString()}</span>
          <span class="${pc} fin-area-profit">${ps}₪${Math.abs(a.profit).toLocaleString()}</span>
          <button class="btn-ghost fin-area-expand-btn" onclick="toggleAreaFinBreakdown(this)">פירוט ▾</button>
        </div>
        <div class="fin-area-breakdown hidden">
          <div class="fin-breakdown-cols">
            <div>
              <div class="fin-section-title fin-revenue-title">בניינים</div>
              ${a.buildings.map(b => `<div class="fin-row"><span class="fin-label">${escapeHtml(b.building_name)}</span><span class="fin-value fin-revenue">₪${b.revenue_in_range.toLocaleString()}</span></div>`).join("") || '<div class="muted">—</div>'}
            </div>
            <div>
              <div class="fin-section-title fin-expense-title">עובדים</div>
              ${a.workers.map(w => `<div class="fin-row"><span class="fin-label">${escapeHtml(w.worker_name)}</span><span class="fin-value fin-expense">-₪${w.expense_in_range.toLocaleString()}</span></div>`).join("") || '<div class="muted">אין נוכחות</div>'}
            </div>
          </div>
        </div>
      </div>`;
  }).join("");

  container.innerHTML = `
    <div class="fin-summary-bar company-level">
      <div class="fin-kpi">
        <span class="fin-kpi-label">סה"כ הכנסות</span>
        <span class="fin-kpi-val fin-revenue">₪${data.total_revenue.toLocaleString()}</span>
      </div>
      <div class="fin-kpi">
        <span class="fin-kpi-label">סה"כ הוצאות</span>
        <span class="fin-kpi-val fin-expense">₪${data.total_expenses.toLocaleString()}</span>
      </div>
      <div class="fin-kpi fin-kpi-main">
        <span class="fin-kpi-label">רווח / הפסד</span>
        <span class="fin-kpi-val ${profitClass}">${profitSign}₪${Math.abs(data.profit).toLocaleString()}</span>
      </div>
    </div>
    <div class="fin-areas-list">${areaRows}</div>`;
}

function toggleAreaFinBreakdown(btn) {
  const row = btn.closest(".fin-area-row");
  const bd = row.querySelector(".fin-area-breakdown");
  const hidden = bd.classList.toggle("hidden");
  btn.textContent = hidden ? "פירוט ▾" : "סגור ▴";
}

// ---------------------------------------------------------------------------
// Show/hide super-admin-only tabs
// ---------------------------------------------------------------------------

function applyRoleVisibility() {
  const isSuperAdmin = currentUser?.role === "SUPER_ADMIN";
  const isWorker = currentUser?.role === "WORKER";

  document.querySelectorAll(".superadmin-only").forEach(el => {
    el.classList.toggle("hidden", !isSuperAdmin);
  });
  document.querySelectorAll(".worker-only").forEach(el => {
    el.classList.toggle("hidden", !isWorker);
  });
  document.querySelectorAll(".non-worker-only, .non-worker-content").forEach(el => {
    el.classList.toggle("hidden", isWorker);
  });
}

// ---------------------------------------------------------------------------
// Time-ago helper
// ---------------------------------------------------------------------------

function timeAgo(date) {
  const seconds = Math.floor((new Date() - date) / 1000);
  if (seconds < 60) return "עכשיו";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `לפני ${minutes} דק׳`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `לפני ${hours} שע׳`;
  const days = Math.floor(hours / 24);
  return `לפני ${days} ימים`;
}

// =============================================================================
// SUPER ADMIN ENHANCEMENTS
// =============================================================================

// ── 1. Global Search ──────────────────────────────────────────────────────────

let _searchTimeout = null;

function onGlobalSearch(query) {
  clearTimeout(_searchTimeout);
  const results = document.getElementById("global-search-results");
  if (!query || query.trim().length < 2) {
    results.classList.add("hidden");
    return;
  }
  _searchTimeout = setTimeout(() => runGlobalSearch(query.trim()), 200);
}

function onGlobalSearchFocus() {
  const input = document.getElementById("global-search-input");
  if (input.value.trim().length >= 2) {
    runGlobalSearch(input.value.trim());
  }
}

function runGlobalSearch(query) {
  const q = query.toLowerCase();
  const results = document.getElementById("global-search-results");

  const matchedBuildings = allBuildings
    .filter(b => b.name.toLowerCase().includes(q) || (b.address_text || "").toLowerCase().includes(q))
    .slice(0, 5);

  const matchedTickets = allTickets
    .filter(t => t.status !== "DONE" && (
      t.description.toLowerCase().includes(q) ||
      (t.building_text_raw || "").toLowerCase().includes(q)
    ))
    .sort(compareTickets)
    .slice(0, 5);

  if (matchedBuildings.length === 0 && matchedTickets.length === 0) {
    results.innerHTML = `<div class="gs-empty">אין תוצאות עבור "${escapeHtml(query)}"</div>`;
    results.classList.remove("hidden");
    return;
  }

  let html = "";

  if (matchedBuildings.length) {
    html += `<div class="gs-section-label">בניינים</div>`;
    html += matchedBuildings.map(b => {
      const area = areasData.find(a => a.id === b.area_id);
      return `
        <button class="gs-row" onclick="globalSearchGoBuilding(${b.area_id})">
          <span class="gs-icon">🏢</span>
          <span class="gs-main">
            <span class="gs-name">${escapeHtml(b.name)}</span>
            <span class="gs-sub">${escapeHtml(b.address_text || "")}${area ? ` · ${escapeHtml(area.name)}` : ""}</span>
          </span>
          <span class="gs-cta">פתח ←</span>
        </button>`;
    }).join("");
  }

  if (matchedTickets.length) {
    html += `<div class="gs-section-label">קריאות פתוחות</div>`;
    html += matchedTickets.map(t => {
      const area = areasData.find(a => a.id === t.area_id);
      const urgIcon = t.urgency === "CRITICAL" ? "🔴" : t.urgency === "HIGH" ? "🟠" : "🔵";
      return `
        <button class="gs-row" onclick="globalSearchGoTicket(${t.area_id}, ${t.id})">
          <span class="gs-icon">${urgIcon}</span>
          <span class="gs-main">
            <span class="gs-name">${escapeHtml(t.description)}</span>
            <span class="gs-sub">${escapeHtml(t.building_text_raw || "")}${area ? ` · ${escapeHtml(area.name)}` : ""}</span>
          </span>
          <span class="gs-cta">פתח ←</span>
        </button>`;
    }).join("");
  }

  results.innerHTML = html;
  results.classList.remove("hidden");
}

function globalSearchGoBuilding(areaId) {
  closeGlobalSearch();
  showArea(areaId).then(() => showAreaPanel("buildings"));
}

async function globalSearchGoTicket(areaId, ticketId) {
  closeGlobalSearch();
  await showArea(areaId);
  showAreaPanel("tickets");
  setTimeout(() => focusTicket(ticketId), 400);
}

function closeGlobalSearch() {
  document.getElementById("global-search-input").value = "";
  document.getElementById("global-search-results").classList.add("hidden");
}

// Close search results on click outside
document.addEventListener("click", e => {
  const wrap = document.getElementById("global-search-wrap");
  if (wrap && !wrap.contains(e.target)) {
    document.getElementById("global-search-results")?.classList.add("hidden");
  }
});

// ── 2. Alerts Center (badge + drawer) ────────────────────────────────────────

let _alertsOpen = false;

function updateAlertsBadge() {
  const count = dashboardData?.areas?.reduce((s, a) => s + a.sla_breached_count, 0) || 0;
  const badge = document.getElementById("alerts-badge");
  if (badge) {
    badge.textContent = count;
    badge.classList.toggle("hidden", count === 0);
  }
  const mobileBadge = document.getElementById("mnav-alerts-badge");
  if (mobileBadge) {
    mobileBadge.textContent = count > 99 ? "99+" : count;
    mobileBadge.classList.toggle("hidden", count === 0);
  }
}

function openMobileMenuSheet() {
  const sheet = document.getElementById("mobile-menu-sheet");
  const backdrop = document.getElementById("mobile-menu-sheet-backdrop");
  if (!sheet || !backdrop) return;
  const nameEl = document.getElementById("mobile-menu-user-name");
  const roleEl = document.getElementById("mobile-menu-user-role");
  if (nameEl && currentUser) nameEl.textContent = currentUser.full_name || "";
  if (roleEl && currentUser) roleEl.textContent = ROLE_LABELS[currentUser.role] || currentUser.role || "";
  sheet.classList.remove("hidden");
  backdrop.classList.remove("hidden");
  if (window.lucide && typeof lucide.createIcons === "function") {
    lucide.createIcons({ attrs: { "stroke-width": 2 } });
  }
}

function closeMobileMenuSheet() {
  document.getElementById("mobile-menu-sheet")?.classList.add("hidden");
  document.getElementById("mobile-menu-sheet-backdrop")?.classList.add("hidden");
}

/* ── WhatsApp Simulator ──────────────────────────────────────── */

function openWaSimModal() {
  document.getElementById("wa-sim-text").value = "";
  document.getElementById("wa-sim-error").classList.add("hidden");
  document.getElementById("wa-sim-result").classList.add("hidden");
  document.getElementById("wa-sim-submit").disabled = false;
  document.getElementById("wa-sim-submit").textContent = "שלח הודעה";
  document.getElementById("wa-sim-modal").classList.remove("hidden");
}

function closeWaSimModal(e) {
  if (e && e.target !== document.getElementById("wa-sim-modal")) return;
  document.getElementById("wa-sim-modal").classList.add("hidden");
}

async function submitWaSim() {
  const text = document.getElementById("wa-sim-text").value.trim();
  const phone = document.getElementById("wa-sim-phone").value.trim() || "+972500000001";
  const errorEl = document.getElementById("wa-sim-error");
  const resultEl = document.getElementById("wa-sim-result");
  const btn = document.getElementById("wa-sim-submit");

  if (!text) {
    errorEl.textContent = "יש להזין טקסט הודעה";
    errorEl.classList.remove("hidden");
    return;
  }
  errorEl.classList.add("hidden");
  resultEl.classList.add("hidden");
  btn.disabled = true;
  btn.textContent = "שולח...";

  try {
    const res = await api("/webhook/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, phone_number: phone }),
    });

    const action = res.action_taken === "created_ticket" ? "נפתחה קריאה חדשה" : "קריאה קיימת עודכנה";
    const ticketId = res.public_id || res.ticket_id || "";
    const category = res.category || "";
    const urgency = res.urgency || "";

    resultEl.innerHTML = `
      <div class="wa-sim-success">
        <strong>✓ ${action}</strong>
        ${ticketId ? `<span>${ticketId}</span>` : ""}
        ${category ? `<span>${CATEGORY_LABELS[category] || category}</span>` : ""}
        ${urgency ? `<span>${URGENCY_LABELS[urgency] || urgency}</span>` : ""}
      </div>
    `;
    resultEl.classList.remove("hidden");
    btn.textContent = "שלח שוב";
    btn.disabled = false;

    // Refresh dashboard data
    setTimeout(() => {
      if (currentAreaId) loadAreaDetails(currentAreaId);
      else loadDashboard();
    }, 600);
  } catch (err) {
    errorEl.textContent = "שגיאה: " + (err.message || "לא ידוע");
    errorEl.classList.remove("hidden");
    btn.disabled = false;
    btn.textContent = "שלח הודעה";
  }
}

function renderLucideIcons() {
  if (window.lucide && typeof lucide.createIcons === "function") {
    try { lucide.createIcons(); } catch (e) { /* noop */ }
  }
}

function toggleAlertsDrawer() {
  _alertsOpen = !_alertsOpen;
  document.getElementById("alerts-drawer").classList.toggle("hidden", !_alertsOpen);
  document.getElementById("alerts-drawer-backdrop").classList.toggle("hidden", !_alertsOpen);
  if (_alertsOpen) renderAlertsDrawer();
}

function renderAlertsDrawer() {
  const content = document.getElementById("alerts-drawer-content");
  if (!dashboardData) {
    content.innerHTML = '<div class="loading-state">טוען...</div>';
    return;
  }

  const slaBreaches = dashboardData.areas
    .filter(a => a.sla_breached_count > 0)
    .flatMap(a => allTickets
      .filter(t => t.area_id === a.area_id && t.sla_breached && t.status !== "DONE")
      .map(t => ({ ...t, area_name: a.area_name }))
    );

  const highUrgency = allTickets
    .filter(t => t.urgency === "CRITICAL" && t.status !== "DONE" && !t.sla_breached)
    .map(t => {
      const area = areasData.find(a => a.id === t.area_id);
      return { ...t, area_name: area?.name || "" };
    });

  const openMany = dashboardData.areas
    .filter(a => a.open_tickets >= 5)
    .map(a => ({ ...a, type: "overload" }));

  const items = [
    ...slaBreaches.map(t => ({
      severity: "critical",
      icon: "🚨",
      title: `באיחור – ${t.building_text_raw || "ללא בניין"}`,
      body: escapeHtml(t.description),
      sub: t.area_name,
      areaId: t.area_id,
    })),
    ...highUrgency.map(t => ({
      severity: "warning",
      icon: "🔴",
      title: `קריטי – ${t.building_text_raw || "ללא בניין"}`,
      body: escapeHtml(t.description),
      sub: t.area_name,
      areaId: t.area_id,
    })),
    ...openMany.map(a => ({
      severity: "warning",
      icon: "📂",
      title: `עומס קריאות – ${a.area_name}`,
      body: `${a.open_tickets} קריאות פתוחות ממתינות לטיפול`,
      sub: a.manager_name || "",
      areaId: a.area_id,
    })),
  ];

  if (items.length === 0) {
    content.innerHTML = `
      <div class="alerts-drawer-empty">
        <div style="font-size:2.5rem;margin-bottom:.5rem">✅</div>
        <div>אין התראות פעילות כרגע</div>
      </div>`;
    return;
  }

  content.innerHTML = items.map(item => `
    <button class="alerts-drawer-item severity-${item.severity}" onclick="toggleAlertsDrawer(); showArea(${item.areaId})">
      <span class="adi-icon">${item.icon}</span>
      <span class="adi-body">
        <span class="adi-title">${item.title}</span>
        <span class="adi-desc">${item.body}</span>
        ${item.sub ? `<span class="adi-sub">${escapeHtml(item.sub)}</span>` : ""}
      </span>
      <span class="adi-cta">פתח ←</span>
    </button>
  `).join("");
}

// ── 3. Financial Bar Chart (SVG, no deps) ────────────────────────────────────

function renderFinancialChart(data) {
  const wrap = document.getElementById("company-financial-chart");
  if (!wrap || !data.areas || data.areas.length === 0) {
    wrap?.classList.add("hidden");
    return;
  }
  wrap.classList.remove("hidden");

  const areas = data.areas;
  const maxVal = Math.max(...areas.flatMap(a => [a.total_revenue, a.total_expenses])) || 1;
  const barW = 28;
  const gap = 16;
  const groupW = barW * 2 + gap;
  const groupGap = 40;
  const chartH = 140;
  const padL = 8;
  const padB = 36;
  const totalW = padL + areas.length * (groupW + groupGap);

  const toH = v => Math.round((v / maxVal) * chartH);

  const bars = areas.map((a, i) => {
    const x = padL + i * (groupW + groupGap);
    const rH = toH(a.total_revenue);
    const eH = toH(a.total_expenses);
    const profitColor = a.profit >= 0 ? "#15803d" : "#b91c1c";
    const nameShort = a.area_name.length > 8 ? a.area_name.slice(0, 7) + "…" : a.area_name;
    return `
      <g>
        <title>${escapeHtml(a.area_name)}: הכנסות ₪${a.total_revenue.toLocaleString()}, הוצאות ₪${a.total_expenses.toLocaleString()}</title>
        <!-- Revenue bar -->
        <rect x="${x}" y="${chartH - rH}" width="${barW}" height="${rH}" rx="3" fill="#0f766e" opacity="0.85"/>
        <!-- Expense bar -->
        <rect x="${x + barW + 4}" y="${chartH - eH}" width="${barW}" height="${eH}" rx="3" fill="#ef4444" opacity="0.75"/>
        <!-- Area label -->
        <text x="${x + groupW / 2}" y="${chartH + padB - 18}" text-anchor="middle" font-size="10" fill="#607487">${escapeHtml(nameShort)}</text>
        <!-- Profit label -->
        <text x="${x + groupW / 2}" y="${chartH + padB - 4}" text-anchor="middle" font-size="9" font-weight="700" fill="${profitColor}">${a.profit >= 0 ? "+" : ""}₪${Math.round(a.profit / 1000)}k</text>
      </g>`;
  }).join("");

  wrap.innerHTML = `
    <div class="fin-chart-title">הכנסות מול הוצאות לפי אזור</div>
    <div class="fin-chart-legend">
      <span><span class="fin-chart-dot" style="background:#0f766e"></span>הכנסות</span>
      <span><span class="fin-chart-dot" style="background:#ef4444"></span>הוצאות</span>
    </div>
    <div style="overflow-x:auto">
      <svg width="${Math.max(totalW, 320)}" height="${chartH + padB + 4}" style="display:block">
        <!-- baseline -->
        <line x1="0" y1="${chartH}" x2="${totalW + 200}" y2="${chartH}" stroke="#e5e7eb" stroke-width="1"/>
        ${bars}
      </svg>
    </div>`;
}

// ── 4. Area Cards Profit Indicator ───────────────────────────────────────────

let _areaFinCache = {};

async function loadAreaCardProfit(areaId, cardEl) {
  if (!cardEl) return;
  if (_areaFinCache[areaId] !== undefined) {
    _renderAreaCardProfit(cardEl, _areaFinCache[areaId]);
    return;
  }
  const now = new Date();
  const from = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
  const to = now.toISOString().slice(0, 10);
  try {
    const data = await api(`/payroll/area/${areaId}/financial?from=${from}&to=${to}`);
    _areaFinCache[areaId] = data;
    _renderAreaCardProfit(cardEl, data);
  } catch {
    // silent - financial data is optional enrichment
  }
}

function _renderAreaCardProfit(cardEl, data) {
  const existing = cardEl.querySelector(".area-card-profit");
  if (existing) existing.remove();
  const profitClass = data.profit >= 0 ? "area-profit-pos" : "area-profit-neg";
  const sign = data.profit >= 0 ? "+" : "";
  const footer = cardEl.querySelector(".area-card-footer");
  if (!footer) return;
  const tag = document.createElement("span");
  tag.className = `area-card-profit ${profitClass}`;
  tag.textContent = `${sign}₪${Math.abs(Math.round(data.profit)).toLocaleString()}`;
  tag.title = `רווח החודש: ${sign}₪${Math.abs(data.profit).toLocaleString()}`;
  footer.prepend(tag);
}

// ── 5. Area Switcher Dropdown ─────────────────────────────────────────────────

function updateAreaSwitcherDropdown() {
  const sel = document.getElementById("area-switcher-select");
  if (!sel || !areasData.length) return;
  sel.innerHTML = areasData.map(a =>
    `<option value="${a.id}" ${a.id === currentAreaId ? "selected" : ""}>${escapeHtml(a.name)}</option>`
  ).join("");
}

function switchAreaFromDropdown(areaIdStr) {
  const areaId = Number(areaIdStr);
  if (areaId && areaId !== currentAreaId) {
    showArea(areaId);
  }
}

// =============================================================================
// AREA MANAGER ENHANCEMENTS
// =============================================================================

// ── Schedule day navigation ───────────────────────────────────────────────────

function scheduleStepDay(delta) {
  const picker = document.getElementById("schedule-date-picker");
  if (!picker) return;
  const d = new Date(picker.value || todayISO());
  d.setDate(d.getDate() + delta);
  picker.value = d.toISOString().slice(0, 10);
  loadSchedule();
}

function scheduleGoToday() {
  const picker = document.getElementById("schedule-date-picker");
  if (!picker) return;
  picker.value = todayISO();
  loadSchedule();
}

// ── Add Building modal ────────────────────────────────────────────────────────

function openAddBuildingModal() {
  document.getElementById("ab-name").value = "";
  document.getElementById("ab-address").value = "";
  document.getElementById("ab-city").value = "";
  document.getElementById("ab-floors").value = "";
  document.getElementById("ab-entry-code").value = "";
  document.getElementById("ab-elevator").checked = false;
  document.getElementById("ab-parking").checked = false;
  document.getElementById("ab-notes").value = "";
  document.getElementById("ab-error").classList.add("hidden");
  document.getElementById("ab-submit-btn").disabled = false;
  document.getElementById("ab-submit-btn").textContent = "הוסף בניין";
  document.getElementById("add-building-modal").classList.remove("hidden");
}

function closeAddBuildingModal(e) {
  if (e && e.target !== document.getElementById("add-building-modal")) return;
  document.getElementById("add-building-modal").classList.add("hidden");
}

async function submitAddBuilding() {
  const name = document.getElementById("ab-name").value.trim();
  const address = document.getElementById("ab-address").value.trim();
  const city = document.getElementById("ab-city").value.trim() || null;
  const floors = parseInt(document.getElementById("ab-floors").value) || null;
  const entryCode = document.getElementById("ab-entry-code").value.trim() || null;
  const elevator = document.getElementById("ab-elevator").checked;
  const parking = document.getElementById("ab-parking").checked;
  const notes = document.getElementById("ab-notes").value.trim() || null;
  const errorEl = document.getElementById("ab-error");

  if (!name) { errorEl.textContent = "שם הבניין הוא שדה חובה"; errorEl.classList.remove("hidden"); return; }
  if (!address) { errorEl.textContent = "כתובת מלאה היא שדה חובה"; errorEl.classList.remove("hidden"); return; }
  errorEl.classList.add("hidden");

  const btn = document.getElementById("ab-submit-btn");
  btn.disabled = true;
  btn.textContent = "שומר...";

  try {
    const payload = {
      area_id: currentAreaId,
      name,
      address_text: address,
      city,
      num_floors: floors,
      entry_code: entryCode,
      has_elevator: elevator,
      has_parking: parking,
      notes,
    };
    await api("/buildings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    document.getElementById("add-building-modal").classList.add("hidden");
    showToast(`הבניין "${name}" נוסף בהצלחה`, "success");
    // Reload area to refresh buildings list + allBuildings cache
    await showArea(currentAreaId, { keepPanel: true });
    showAreaPanel("buildings");
  } catch (e) {
    let msg = "שגיאה בהוספת הבניין";
    try { msg = JSON.parse(e.message)?.detail || msg; } catch {}
    errorEl.textContent = msg;
    errorEl.classList.remove("hidden");
    btn.disabled = false;
    btn.textContent = "הוסף בניין";
  }
}

// ── Open swap modal from worker detail ────────────────────────────────────────

function openWorkerSwapFromDetail(workerId, workerName) {
  // Find first building of this worker to pre-populate
  const areaState = currentAreaId ? areaDetailsCache[currentAreaId] : null;
  const worker = areaState?.workers?.find(w => w.id === workerId);
  const firstBuilding = worker?.assigned_buildings?.[0];

  if (!firstBuilding) {
    // No building assigned — open generic swap modal with empty building
    openSwapModal(null, "—", workerName, todayISO());
    return;
  }
  openSwapModal(firstBuilding.id, firstBuilding.name, workerName, todayISO());
}

// =============================================================================
// WORKER ROLE — HOME DASHBOARD, SCHEDULE, REPORT PROBLEM
// =============================================================================

// ── Worker home dashboard ─────────────────────────────────────────────────────

async function loadWorkerDashboard() {
  try {
    const [todayRec, buildings, myTickets] = await Promise.all([
      api("/attendance/me/today"),
      api("/attendance/me/buildings"),
      api("/tickets?status=OPEN"),
    ]);

    attendanceState = todayRec;
    allBuildings = buildings.map(b => ({ id: b.id, name: b.name, area_id: null }));

    renderWorkerHome(todayRec, buildings, myTickets);
    renderAttendanceWidget(todayRec, buildings);

    // Show the worker-specific tab layout
    applyRoleVisibility();
    showDashboardPanel("overview", true);
    updateRefreshTime();
  } catch (e) {
    document.getElementById("worker-home").innerHTML =
      `<div class="empty-state">שגיאה בטעינה: ${escapeHtml(String(e))}</div>`;
    document.getElementById("worker-home").classList.remove("hidden");
  }
}

function renderWorkerHome(rec, buildings, tickets) {
  const home = document.getElementById("worker-home");
  home.classList.remove("hidden");

  const now = new Date();
  const dateLabel = now.toLocaleDateString("he-IL", { weekday: "long", day: "numeric", month: "long" });
  const greeting = now.getHours() < 12 ? "בוקר טוב" : now.getHours() < 17 ? "צהריים טובים" : "ערב טוב";
  const name = currentUser?.full_name?.split(" ")[0] || "";

  const openCount = tickets.filter(t => t.status !== "DONE").length;
  const criticalCount = tickets.filter(t => t.urgency === "CRITICAL" && t.status !== "DONE").length;

  const todayBuildings = buildings.length
    ? buildings.map(b =>
        `<div class="wh-building-row">
           <span class="wh-building-name">${escapeHtml(b.name)}</span>
           ${b.is_swap ? '<span class="sched-badge open wh-swap-badge">החלפה</span>' : ""}
         </div>`
      ).join("")
    : `<div class="wh-empty-day">אין שיבוצים היום</div>`;

  home.innerHTML = `
    <div class="worker-home-card">
      <div id="worker-attendance-widget" class="worker-attendance-widget"></div>

      <div class="wh-greeting">
        <div class="wh-greeting-text">
          <div class="wh-hello">${greeting}, ${escapeHtml(name)} 👋</div>
          <div class="wh-date">${dateLabel}</div>
        </div>
        <div class="wh-quick-actions">
          <button class="btn-primary wh-action-btn" onclick="openReportProblemModal()">+ דווח בעיה</button>
          <button class="btn-ghost wh-action-btn" onclick="openMyPayrollReport()">דוח שכר</button>
        </div>
      </div>

      <div class="wh-stats-row">
        <div class="wh-stat">
          <span class="wh-stat-val">${buildings.length}</span>
          <span class="wh-stat-label">בניינים היום</span>
        </div>
        <div class="wh-stat ${openCount > 0 ? "wh-stat-warn" : ""}">
          <span class="wh-stat-val">${openCount}</span>
          <span class="wh-stat-label">קריאות פתוחות</span>
        </div>
        ${criticalCount > 0 ? `
          <div class="wh-stat wh-stat-critical">
            <span class="wh-stat-val">${criticalCount}</span>
            <span class="wh-stat-label">קריטיות</span>
          </div>` : ""}
      </div>

      <div class="wh-section">
        <div class="wh-section-label">הבניינים שלי היום</div>
        <div class="wh-buildings-list">${todayBuildings}</div>
      </div>

      ${openCount > 0 ? `
        <div class="wh-section">
          <div class="wh-section-label">קריאות פתוחות בבניינים שלך</div>
          <div class="wh-tickets-list">
            ${tickets.filter(t => t.status !== "DONE").slice(0, 5).map(t => `
              <div class="wh-ticket-row urgency-${t.urgency || "MEDIUM"}">
                <span class="wh-ticket-urgency">${URGENCY_LABELS[t.urgency] || t.urgency}</span>
                <span class="wh-ticket-desc">${escapeHtml(t.description)}</span>
                <span class="wh-ticket-building">${escapeHtml(t.building_text_raw || "")}</span>
              </div>`).join("")}
          </div>
        </div>` : ""}
    </div>
  `;
}

// ── Worker weekly schedule ────────────────────────────────────────────────────

async function loadMyWeeklySchedule() {
  const container = document.getElementById("my-schedule-content");
  if (!container) return;
  container.innerHTML = '<div class="loading-state">טוען לוח שיבוצים...</div>';

  // Build ISO dates for the current week (today + 6 days, so we always see at least a full week)
  const days = [];
  const today = new Date();
  for (let i = 0; i < 7; i++) {
    const d = new Date(today);
    d.setDate(today.getDate() + i);
    days.push(d.toISOString().slice(0, 10));
  }

  try {
    const params = new URLSearchParams({ from: days[0] });
    const schedules = await api(`/schedule/my-week?${params}`);

    let html = '<div class="my-sched-grid">';

    schedules.forEach((sched, i) => {
      const myBuildings = sched.buildings;

      const dow = hebrewDow(sched.day_of_week);
      const dateStr = new Date(sched.date).toLocaleDateString("he-IL", { day: "numeric", month: "numeric" });
      const isToday = sched.date === days[0];

      html += `
        <div class="my-sched-day ${isToday ? "my-sched-today" : ""} ${myBuildings.length === 0 ? "my-sched-empty" : ""}">
          <div class="my-sched-day-header">
            <span class="my-sched-dow">${dow}</span>
            <span class="my-sched-date">${dateStr}</span>
            ${isToday ? '<span class="my-sched-today-badge">היום</span>' : ""}
          </div>
          ${myBuildings.length ? myBuildings.map(b => `
            <div class="my-sched-building">
              <span class="my-sched-time">${escapeHtml(b.schedule_time)}</span>
              <span class="my-sched-bname">${escapeHtml(b.building_name)}</span>
              ${b.is_swap ? '<span class="my-sched-swap">החלפה</span>' : ""}
              ${b.open_ticket_count > 0 ? `<span class="my-sched-tickets">${b.open_ticket_count} קריאות</span>` : ""}
            </div>`).join("")
          : `<div class="my-sched-rest">אין שיבוצים</div>`}
        </div>`;
    });

    html += "</div>";

    // Add a "jump to today" shortcut link below
    html += `<div style="text-align:center;margin-top:1rem">
      <button class="btn-ghost" onclick="showDashboardPanel('overview')">חזרה לדף הבית</button>
    </div>`;

    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = `<div class="empty-state">שגיאה בטעינת הלוח: ${escapeHtml(String(e))}</div>`;
  }
}

// ── Report problem modal ──────────────────────────────────────────────────────

async function openReportProblemModal() {
  // Populate worker's buildings
  const bldgSel = document.getElementById("rp-building");
  try {
    const buildings = await api("/attendance/me/buildings");
    if (!buildings.length) {
      showToast("אין בניינים משויכים לדיווח", "error");
      return;
    }
    bldgSel.innerHTML = buildings.map(b =>
      `<option value="${b.id}">${escapeHtml(b.name)}</option>`
    ).join("");
  } catch {
    bldgSel.innerHTML = '<option>שגיאה</option>';
  }

  document.getElementById("rp-description").value = "";
  document.getElementById("rp-error").classList.add("hidden");
  document.getElementById("rp-submit-btn").disabled = false;
  document.getElementById("rp-submit-btn").textContent = "שלח דיווח";
  document.getElementById("report-problem-modal").classList.remove("hidden");
}

function closeReportProblemModal(e) {
  if (e && e.target !== document.getElementById("report-problem-modal")) return;
  document.getElementById("report-problem-modal").classList.add("hidden");
}

async function submitReportProblem() {
  const buildingId = parseInt(document.getElementById("rp-building").value);
  const category = document.getElementById("rp-category").value;
  const urgency = document.getElementById("rp-urgency").value;
  const description = document.getElementById("rp-description").value.trim();
  const errorEl = document.getElementById("rp-error");

  if (!description) {
    errorEl.textContent = "יש לתאר את הבעיה";
    errorEl.classList.remove("hidden");
    return;
  }
  errorEl.classList.add("hidden");

  const btn = document.getElementById("rp-submit-btn");
  btn.disabled = true;
  btn.textContent = "שולח...";

  try {
    await api("/tickets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ building_id: buildingId, category, urgency, description }),
    });
    document.getElementById("report-problem-modal").classList.add("hidden");
    showToast("הדיווח נשלח בהצלחה", "success");
    // Reload to refresh ticket counts
    loadWorkerDashboard();
  } catch (e) {
    let msg = "שגיאה בשליחת הדיווח";
    try { msg = JSON.parse(e.message)?.detail || msg; } catch {}
    errorEl.textContent = msg;
    errorEl.classList.remove("hidden");
    btn.disabled = false;
    btn.textContent = "שלח דיווח";
  }
}

// =============================================================================
// SIDEBAR NAVIGATION
// =============================================================================

function setSidebarActive(key) {
  document.querySelectorAll(".sidebar-item, .mobile-nav-item").forEach(el => {
    el.classList.remove("active");
  });
  const sidebarItem = document.getElementById(`snav-${key}`);
  const mobileItem = document.getElementById(`mnav-${key}`);
  if (sidebarItem) sidebarItem.classList.add("active");
  if (mobileItem) mobileItem.classList.add("active");
}

function sidebarNav(key) {
  setSidebarActive(key);

  if (key === "dashboard") {
    showDashboard();
    return;
  }

  // For module shortcuts that target a specific area panel:
  // If we're already in an area, switch to the right tab.
  // Otherwise navigate to the area first (area manager has a fixed area).
  const areaModules = { tickets: "tickets", schedule: "schedule", attendance: "payroll", payroll: "payroll" };
  if (areaModules[key]) {
    if (currentView === "area" && currentAreaId) {
      showAreaPanel(areaModules[key]);
    } else if (currentUser?.role === "AREA_MANAGER" && currentUser?.area_id) {
      showArea(currentUser.area_id, { keepPanel: false }).then(() => showAreaPanel(areaModules[key]));
    } else if (currentUser?.role === "WORKER") {
      if (key === "schedule") showDashboardPanel("my-schedule");
    } else {
      // SUPER_ADMIN with no area selected — stay on dashboard, nothing to do
    }
  }
}

// Keep sidebar in sync when area panels switch via tabs
const _origShowAreaPanel = showAreaPanel;
// Wrap showAreaPanel to update sidebar active state
const _wrappedShowAreaPanel = function(panel, preserveScroll = false) {
  _origShowAreaPanel(panel, preserveScroll);
  const panelToSidebarKey = { tickets: "tickets", schedule: "schedule", payroll: "payroll", attendance: "attendance" };
  const sidebarKey = panelToSidebarKey[panel];
  if (sidebarKey) setSidebarActive(sidebarKey);
};

// =============================================================================
// TICKET DETAIL SLIDE-OVER
// =============================================================================

let _ticketDetailId = null;

async function openTicketDetail(ticketId) {
  const overlay = document.getElementById("ticket-detail-overlay");
  const panel = document.getElementById("ticket-detail-panel");
  const body = document.getElementById("ticket-detail-body");
  const idEl = document.getElementById("ticket-detail-id");
  const statusRow = document.getElementById("ticket-detail-status-row");

  _ticketDetailId = ticketId;

  overlay.classList.remove("hidden");
  panel.classList.remove("hidden");
  body.innerHTML = '<div class="loading-state">טוען קריאה...</div>';
  idEl.textContent = "";
  statusRow.innerHTML = "";

  // Trap escape key
  document.addEventListener("keydown", _ticketDetailKeyHandler);

  try {
    const ticket = await api(`/tickets/${ticketId}`);
    renderTicketDetail(ticket);
  } catch (e) {
    body.innerHTML = `<div class="empty-state">שגיאה בטעינת הקריאה</div>`;
  }
}

function closeTicketDetail(e) {
  if (e && e.target !== document.getElementById("ticket-detail-overlay")) return;
  _doCloseTicketDetail();
}

function _doCloseTicketDetail() {
  document.getElementById("ticket-detail-overlay").classList.add("hidden");
  document.getElementById("ticket-detail-panel").classList.add("hidden");
  document.removeEventListener("keydown", _ticketDetailKeyHandler);
  _ticketDetailId = null;
}

function _ticketDetailKeyHandler(e) {
  if (e.key === "Escape") _doCloseTicketDetail();
}

function renderTicketDetail(ticket) {
  const idEl = document.getElementById("ticket-detail-id");
  const statusRow = document.getElementById("ticket-detail-status-row");
  const body = document.getElementById("ticket-detail-body");

  idEl.textContent = ticket.public_id || `#${ticket.id}`;

  const urgencyClass = `urgency-label ${getUrgencyClass(ticket.urgency || "MEDIUM")}`;
  const statusLabel = STATUS_LABELS[ticket.status] || ticket.status;
  statusRow.innerHTML = `
    <span class="${urgencyClass}">${URGENCY_LABELS[ticket.urgency] || ticket.urgency || ""}</span>
    <span class="sched-badge ${ticket.status === "DONE" ? "done" : ticket.status === "IN_PROGRESS" ? "open" : "open"}">${statusLabel}</span>
    ${ticket.sla_breached ? '<span class="sla-breach-inline">באיחור</span>' : ""}
  `;

  const areaName = areasData.find(a => a.id === ticket.area_id)?.name || "";
  const buildingName = ticket.building_name || ticket.building_text_raw || "לא ידוע";
  const category = CATEGORY_LABELS[ticket.category] || ticket.category;
  const catIcon = CATEGORY_ICONS[ticket.category] || "";
  const supplierName = ticket.assigned_supplier?.name || "—";
  const phone = ticket.resident_phone || "—";

  // Messages thread
  const messages = (ticket.messages || []).map(m => `
    <div class="td-msg ${m.direction === "INBOUND" ? "inbound" : "outbound"}">
      <div>${escapeHtml(m.raw_text)}</div>
      <div class="td-msg-meta">${m.sender_role || (m.direction === "INBOUND" ? "דייר" : "מערכת")} · ${getTimeAgo(m.created_at)}</div>
    </div>
  `).join("");

  // Status action buttons (only for non-workers / area managers)
  const isWorker = currentUser?.role === "WORKER";
  const statusActions = isWorker ? "" : `
    <div class="td-section-label">שינוי סטטוס</div>
    <div class="td-status-actions">
      <button class="td-status-btn ${ticket.status === "OPEN" ? "active" : ""}" onclick="updateTicketStatus(${ticket.id}, 'OPEN')">פתוח</button>
      <button class="td-status-btn ${ticket.status === "IN_PROGRESS" ? "active" : ""}" onclick="updateTicketStatus(${ticket.id}, 'IN_PROGRESS')">בטיפול</button>
      <button class="td-status-btn ${ticket.status === "DONE" ? "active" : ""}" onclick="updateTicketStatus(${ticket.id}, 'DONE')">בוצע</button>
    </div>
  `;

  // Navigate-to-area button
  const navToArea = ticket.area_id ? `
    <button class="btn-ghost" style="margin-top:4px" onclick="_doCloseTicketDetail(); showArea(${ticket.area_id})">
      פתח אזור ${escapeHtml(areaName)} ←
    </button>
  ` : "";

  body.innerHTML = `
    <div>
      <div class="td-section-label">תיאור</div>
      <div class="td-description">${escapeHtml(ticket.description)}</div>
    </div>

    <div class="td-meta-grid">
      <div class="td-meta-item">
        <div class="td-meta-key">קטגוריה</div>
        <div class="td-meta-val">${catIcon} ${category}</div>
      </div>
      <div class="td-meta-item">
        <div class="td-meta-key">בניין</div>
        <div class="td-meta-val">${escapeHtml(buildingName)}</div>
      </div>
      <div class="td-meta-item">
        <div class="td-meta-key">ספק משויך</div>
        <div class="td-meta-val">${escapeHtml(supplierName)}</div>
      </div>
      <div class="td-meta-item">
        <div class="td-meta-key">טלפון מדווח</div>
        <div class="td-meta-val">${escapeHtml(phone)}</div>
      </div>
      ${ticket.sla_due_at ? `
      <div class="td-meta-item">
        <div class="td-meta-key">יעד טיפול</div>
        <div class="td-meta-val">${new Date(ticket.sla_due_at).toLocaleString("he-IL")}</div>
      </div>` : ""}
      <div class="td-meta-item">
        <div class="td-meta-key">נפתחה</div>
        <div class="td-meta-val">${getTimeAgo(ticket.created_at)}</div>
      </div>
    </div>

    ${statusActions}

    ${navToArea}

    ${messages ? `
    <div>
      <div class="td-section-label">היסטוריית הודעות (${ticket.messages?.length || 0})</div>
      <div class="td-messages">${messages}</div>
    </div>` : ""}
  `;
}

async function updateTicketStatus(ticketId, newStatus) {
  try {
    await api(`/tickets/${ticketId}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: newStatus }),
    });
    // Refresh the detail panel
    const ticket = await api(`/tickets/${ticketId}`);
    renderTicketDetail(ticket);
    showToast("סטטוס עודכן", "success");
    // Refresh current view in background
    if (currentView === "area" && currentAreaId) {
      showArea(currentAreaId, { keepPanel: true });
    } else {
      loadDashboard();
    }
  } catch (e) {
    showToast("שגיאה בעדכון סטטוס", "error");
  }
}

// =============================================================================
// AREA SETUP WIZARD (shown when area has 0 buildings)
// =============================================================================

function renderAreaSetupWizard(areaId) {
  const container = document.getElementById("area-overview-panel");
  if (!container) return;

  container.innerHTML = `
    <div class="side-card" style="max-width:540px;margin:2rem auto">
      <div class="side-card-head">
        <div>
          <p class="eyebrow">הגדרה ראשונית</p>
          <h3>ברוכים הבאים לאזור 👋</h3>
        </div>
      </div>
      <p style="color:var(--muted);margin-bottom:1.5rem">האזור ריק כרגע. כדי להתחיל, הוסף את הבניין הראשון.</p>
      <div id="setup-wizard-step" class="setup-wizard-step">
        <div class="td-section-label">שלב 1 — הוסף בניין</div>
        <button class="btn-primary" onclick="openAddBuildingModal()">+ הוסף בניין ראשון</button>
      </div>
    </div>
  `;
}
