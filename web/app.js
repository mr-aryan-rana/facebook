/* ==========================================================================
   ⚡ STITCH SAAS DASHBOARD - DIRECTORY & MULTI-FILTER INTERACTION JS
   ========================================================================== */

let isHarvesterRunning = false;
let pollingInterval = null;
let facebookEmailsList = [];
let filteredEmails = [];
let filteredPhones = [];

let currentPage = 1;
let currentPhonePage = 1;
let pageSize = 25;
let lastEmailCount = -1;
let activeTab = "emails";
let isDryRunMode = false;

document.addEventListener("DOMContentLoaded", () => {
  loadEmails();
  startStatusPolling();
});

function showToast(message, isSuccess = true) {
  let toast = document.getElementById("toastNotification");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "toastNotification";
    toast.className = "toast-notification";
    document.body.appendChild(toast);
  }
  toast.innerText = message;
  toast.style.borderColor = isSuccess ? "rgba(16, 185, 129, 0.5)" : "rgba(244, 63, 94, 0.5)";
  toast.style.boxShadow = isSuccess 
    ? "0 10px 30px rgba(0, 0, 0, 0.6), 0 0 15px rgba(16, 185, 129, 0.3)"
    : "0 10px 30px rgba(0, 0, 0, 0.6), 0 0 15px rgba(244, 63, 94, 0.3)";
  
  toast.classList.add("show");
  setTimeout(() => {
    toast.classList.remove("show");
  }, 2500);
}

function logToTerminal(msg, type = "info") {
  const consoleEl = document.getElementById("terminalConsole");
  if (!consoleEl) return;

  const timeStr = new Date().toLocaleTimeString();
  let colorClass = "text-cyan";
  if (type === "success") colorClass = "text-emerald";
  if (type === "warning") colorClass = "text-amber";
  if (type === "error") colorClass = "text-rose";

  const line = document.createElement("div");
  line.className = `terminal-line ${colorClass}`;
  line.innerText = `[${timeStr}] ${msg}`;
  
  consoleEl.appendChild(line);
  consoleEl.scrollTop = consoleEl.scrollHeight;
}

function formatDateTime(isoStr) {
  if (!isoStr) return `<span style="color: var(--text-dim); font-size: 11px;">Aug 18, 2026 18:25</span>`;
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return `<span style="color: var(--text-dim); font-size: 11px;">Aug 18, 2026 18:25</span>`;
    const datePart = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    const timePart = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    return `<span style="font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #94a3b8;">${datePart} ${timePart}</span>`;
  } catch (e) {
    return `<span style="color: var(--text-dim); font-size: 11px;">Aug 18, 2026 18:25</span>`;
  }
}

function toggleDryRunMode(enabled) {
  isDryRunMode = enabled;
  const msg = enabled ? "🧪 Switched to Test / Dry-Run Mode (No real emails sent)" : "🚀 Switched to LIVE Outreach Mode!";
  logToTerminal(msg, enabled ? "warning" : "error");
  showToast(msg, !enabled);
}

function switchMainSection(section) {
  const pillEmails = document.getElementById("pillTabEmails");
  const pillPhones = document.getElementById("pillTabPhones");
  const pillOverview = document.getElementById("pillTabOverview");
  const pillControls = document.getElementById("pillTabControls");

  const overviewSection = document.getElementById("overviewSection");
  const emailSection = document.getElementById("emailDirectorySection");
  const phoneSection = document.getElementById("phoneDirectorySection");
  const controlsSection = document.getElementById("controlsSection");

  [pillOverview, pillEmails, pillPhones, pillControls].forEach(p => p && p.classList.remove("active"));
  [overviewSection, emailSection, phoneSection, controlsSection].forEach(s => s && (s.style.display = "none"));

  if (section === "overview") {
    if (pillOverview) pillOverview.classList.add("active");
    if (overviewSection) overviewSection.style.display = "block";
  } else if (section === "emails") {
    if (pillEmails) pillEmails.classList.add("active");
    if (emailSection) emailSection.style.display = "block";
  } else if (section === "phones") {
    if (pillPhones) pillPhones.classList.add("active");
    if (phoneSection) phoneSection.style.display = "block";
    applyPhoneFilterAndRender();
  } else if (section === "controls") {
    if (pillControls) pillControls.classList.add("active");
    if (controlsSection) controlsSection.style.display = "block";
  }
}

function switchDirectoryTab(tab) {
  switchMainSection(tab);
}

function startStatusPolling() {
  if (pollingInterval) clearInterval(pollingInterval);
  pollingInterval = setInterval(checkStatus, 3000);
}

let pollFailures = 0;

async function checkStatus() {
  try {
    const res = await fetch("/api/status");
    if (res.ok) {
      pollFailures = 0;
      const data = await res.json();
      updateUIStatus(data.running, data.statusText);
      
      const totalEmails = data.total_emails || data.totalEmails || 0;
      const totalPhones = data.total_phones || 0;
      const totalSent = data.total_sent || 0;

      document.getElementById("metricTotalEmails").innerText = totalEmails.toLocaleString();
      document.getElementById("metricTotalPhones").innerText = totalPhones.toLocaleString();
      
      // Update Quota Badges & Progress Bars dynamically from 24h rolling metrics
      const serperUsed = data.serper_used_24h !== undefined ? data.serper_used_24h : (data.serper_used || 0);
      const serperLimit = data.serper_daily_limit || 60;
      const emailSentCount = data.emails_sent_24h !== undefined ? data.emails_sent_24h : totalSent;
      const emailLimit = data.email_daily_limit || 200;

      document.getElementById("serperQuotaBadge").innerText = `${serperUsed} / ${serperLimit} credits`;
      document.getElementById("emailQuotaBadge").innerText = `${emailSentCount} / ${emailLimit} sent`;
      document.getElementById("metricSerperUsed").innerText = serperUsed;
      document.getElementById("metricTotalSent").innerText = emailSentCount;

      const serperPct = Math.min(100, Math.round((serperUsed / serperLimit) * 100));
      const emailPct = Math.min(100, Math.round((emailSentCount / emailLimit) * 100));

      const serperBar = document.getElementById("serperProgressBar");
      const emailBar = document.getElementById("emailProgressBar");
      if (serperBar) serperBar.style.width = `${serperPct}%`;
      if (emailBar) emailBar.style.width = `${emailPct}%`;

      const tabCountE = document.getElementById("tabCountEmails");
      const tabCountP = document.getElementById("tabCountPhones");
      if (tabCountE) tabCountE.innerText = totalEmails.toLocaleString();
      if (tabCountP) tabCountP.innerText = totalPhones.toLocaleString();

      if (totalEmails !== lastEmailCount) {
        lastEmailCount = totalEmails;
        if (data.emails && data.emails.length > 0) {
          facebookEmailsList = data.emails;
          applyFilterAndRender();
          applyPhoneFilterAndRender();
        } else {
          loadEmails();
        }
      }
    }
  } catch (err) {
    pollFailures++;
    if (pollFailures >= 3) {
      updateUIStatus(false, "API Server Offline");
    }
  }
  
  checkLogs();
}

let lastLogContent = "";

async function checkLogs() {
  try {
    const res = await fetch("/api/logs");
    if (res.ok) {
      const data = await res.json();
      const logs = data.logs || [];
      const consoleEl = document.getElementById("terminalConsole");
      if (consoleEl && logs.length > 0) {
        const logText = logs.join("\n");
        if (logText !== lastLogContent) {
          lastLogContent = logText;
          consoleEl.innerHTML = "";
          logs.forEach(line => {
            let colorClass = "text-cyan";
            if (line.includes("SENT") || line.includes("SUCCESS") || line.includes("✅")) colorClass = "text-emerald";
            if (line.includes("Delay") || line.includes("Sleeping") || line.includes("⏱️")) colorClass = "text-amber";
            if (line.includes("Error") || line.includes("Exceeded") || line.includes("❌") || line.includes("⛔")) colorClass = "text-rose";

            const div = document.createElement("div");
            div.className = `terminal-line ${colorClass}`;
            div.innerText = line;
            consoleEl.appendChild(div);
          });
          consoleEl.scrollTop = consoleEl.scrollHeight;
        }
      }
    }
  } catch (err) {}
}

function updateUIStatus(running, statusText) {
  isHarvesterRunning = running;
  const badge = document.getElementById("statusBadge");
  const text = document.getElementById("statusText");
  const btnStart = document.getElementById("btnStart");
  const btnStop = document.getElementById("btnStop");

  if (text) text.innerText = statusText || (running ? "Harvester Active" : "Ready");

  if (badge) {
    if (running) {
      badge.className = "status-badge running";
      if (btnStart) btnStart.style.display = "none";
      if (btnStop) btnStop.style.display = "inline-flex";
    } else {
      badge.className = "status-badge idle";
      if (btnStart) btnStart.style.display = "inline-flex";
      if (btnStop) btnStop.style.display = "none";
    }
  }
}

async function startHarvester() {
  const reqBudget = parseInt(document.getElementById("fbRequestBudget").value) || 10;
  const targetNiche = document.getElementById("fbNicheSelect").value || "Love Couple";
  const delayMin = parseInt(document.getElementById("delayMinInput").value) || 60;
  const delayMax = parseInt(document.getElementById("delayMaxInput").value) || 90;

  logToTerminal(`Launching Live Harvester for '${targetNiche}' (Credit Limit: ${reqBudget}, Send Gap: ${delayMin}s-${delayMax}s)...`, "info");

  try {
    const res = await fetch("/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        budget: reqBudget,
        niche: targetNiche,
        dry_run: isDryRunMode,
        delay_min: delayMin,
        delay_max: delayMax
      })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`🚀 Harvester launched for '${targetNiche}'!`);
      logToTerminal(`✅ Harvester task active in background!`, "success");
      updateUIStatus(true, `Running Harvester (${targetNiche})...`);
    } else {
      showToast(data.error || "Failed to start harvester", false);
      logToTerminal(`❌ Error starting harvester: ${data.error}`, "error");
    }
  } catch (err) {
    showToast("Error connecting to server", false);
    logToTerminal(`❌ Connection failed to server endpoint.`, "error");
  }
}

async function stopHarvester() {
  try {
    const res = await fetch("/api/stop", { method: "POST" });
    if (res.ok) {
      showToast("⏹️ Harvester stopped");
      logToTerminal("⏹️ Harvester process terminated by user.", "warning");
      updateUIStatus(false, "Stopped by user");
    } else {
      showToast("Failed to stop harvester", false);
    }
  } catch (err) {
    showToast("Error stopping harvester", false);
  }
}

async function loadEmails() {
  try {
    const res = await fetch("/api/emails");
    if (res.ok) {
      const data = await res.json();
      facebookEmailsList = data.emails || [];
      const totalEmails = data.total_emails || facebookEmailsList.length;
      const totalPhones = data.total_phones || 0;

      document.getElementById("metricTotalEmails").innerText = totalEmails.toLocaleString();
      document.getElementById("metricTotalPhones").innerText = totalPhones.toLocaleString();

      const tabCountE = document.getElementById("tabCountEmails");
      const tabCountP = document.getElementById("tabCountPhones");
      if (tabCountE) tabCountE.innerText = totalEmails.toLocaleString();
      if (tabCountP) tabCountP.innerText = totalPhones.toLocaleString();

      applyFilterAndRender();
      applyPhoneFilterAndRender();
    }
  } catch (err) {
    console.error("Error loading emails:", err);
  }
}

function detectCategory(item) {
  const text = `${item.name || ''} ${item.email || ''} ${item.platform || ''} ${item.location || ''}`.toLowerCase();
  
  if (text.includes("couple") || text.includes("love") || text.includes("wedding") || text.includes("marriage") || text.includes("family")) {
    return { key: "couple", label: "❤️ Love & Couple", badgeClass: "badge-rose" };
  }
  if (text.includes("lifestyle") || text.includes("beauty") || text.includes("fashion") || text.includes("fitness") || text.includes("photo")) {
    return { key: "lifestyle", label: "💄 Lifestyle & Beauty", badgeClass: "badge-purple" };
  }
  if (text.includes("travel") || text.includes("food") || text.includes("trip") || text.includes("getaway") || text.includes("journey")) {
    return { key: "travel", label: "✈️ Travel & Food", badgeClass: "badge-amber" };
  }
  if (text.includes("digital") || text.includes("content") || text.includes("tech") || text.includes("media") || text.includes("agency")) {
    return { key: "digital", label: "💻 Digital & Tech", badgeClass: "badge-blue" };
  }
  return { key: "ugc", label: "✨ UGC Creator", badgeClass: "badge-emerald" };
}

function getAvatarInitials(name) {
  if (!name) return "CR";
  const parts = name.trim().split(" ");
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.substring(0, 2).toUpperCase();
}

function filterTable() {
  currentPage = 1;
  currentPhonePage = 1;
  applyFilterAndRender();
  applyPhoneFilterAndRender();
}

function applyFilterAndRender() {
  const searchInput = document.getElementById("tableFilterInput");
  const mobileSelect = document.getElementById("filterMobileSelect");
  const categorySelect = document.getElementById("filterCategorySelect");
  const statusSelect = document.getElementById("filterStatusSelect");

  const query = searchInput ? searchInput.value.toLowerCase().trim() : "";
  const mobileFilter = mobileSelect ? mobileSelect.value : "all";
  const categoryFilter = categorySelect ? categorySelect.value : "all";
  const statusFilter = statusSelect ? statusSelect.value : "all";

  filteredEmails = facebookEmailsList.filter(item => {
    if (query) {
      const name = (item.name || "").toLowerCase();
      const email = (item.email || "").toLowerCase();
      const phone = (item.phone || item.mobile_number || "").toLowerCase();
      const location = (item.location || "").toLowerCase();
      const dateStr = (item.sent_at || item.created_at || "").toLowerCase();
      if (!name.includes(query) && !email.includes(query) && !phone.includes(query) && !location.includes(query) && !dateStr.includes(query)) {
        return false;
      }
    }

    const hasPhone = Boolean(item.phone || item.mobile_number);
    if (mobileFilter === "has_mobile" && !hasPhone) return false;
    if (mobileFilter === "no_mobile" && hasPhone) return false;

    const cat = detectCategory(item);
    if (categoryFilter !== "all" && cat.key !== categoryFilter) return false;

    if (statusFilter === "dns_valid" && !strContains(item.dns_status, "Valid")) return false;
    if (statusFilter === "sent" && !item.sent_at && !strContains(item.status, "Sent")) return false;
    if (statusFilter === "verified_us" && !strContains(item.location, "United States")) return false;

    return true;
  });

  filteredEmails.sort((a, b) => {
    const timeA = new Date(a.created_at || a.sent_at || 0).getTime();
    const timeB = new Date(b.created_at || b.sent_at || 0).getTime();
    return timeB - timeA;
  });

  renderTable();
}

function applyPhoneFilterAndRender() {
  const searchInput = document.getElementById("tableFilterInput");
  const categorySelect = document.getElementById("filterCategorySelect");

  const query = searchInput ? searchInput.value.toLowerCase().trim() : "";
  const categoryFilter = categorySelect ? categorySelect.value : "all";

  const phoneItems = facebookEmailsList.filter(item => item.phone || item.mobile_number);

  filteredPhones = phoneItems.filter(item => {
    if (query) {
      const name = (item.name || "").toLowerCase();
      const phone = (item.phone || item.mobile_number || "").toLowerCase();
      const email = (item.email || "").toLowerCase();
      const location = (item.location || "").toLowerCase();
      const dateStr = (item.sent_at || item.created_at || "").toLowerCase();
      if (!name.includes(query) && !phone.includes(query) && !email.includes(query) && !location.includes(query) && !dateStr.includes(query)) {
        return false;
      }
    }

    const cat = detectCategory(item);
    if (categoryFilter !== "all" && cat.key !== categoryFilter) return false;

    return true;
  });

  filteredPhones.sort((a, b) => {
    const timeA = new Date(a.created_at || a.sent_at || 0).getTime();
    const timeB = new Date(b.created_at || b.sent_at || 0).getTime();
    return timeB - timeA;
  });

  renderPhoneTable();
}

function strContains(str, target) {
  if (!str) return false;
  return String(str).toLowerCase().includes(target.toLowerCase());
}

function renderTable() {
  const tbody = document.getElementById("facebookTableBody");
  if (!tbody) return;

  if (filteredEmails.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No creator leads match the selected filters.</td></tr>`;
    updatePaginationBar(0);
    return;
  }

  const totalPages = Math.ceil(filteredEmails.length / pageSize) || 1;
  if (currentPage > totalPages) currentPage = totalPages;

  const startIndex = (currentPage - 1) * pageSize;
  const pageItems = filteredEmails.slice(startIndex, startIndex + pageSize);

  let html = "";
  pageItems.forEach(item => {
    const status = item.status || "Verified Lead";
    let statusClass = "badge-blue";
    if (status.includes("Sent")) statusClass = "badge-emerald";

    const dnsStatus = item.dns_status || "Valid (DNS Verified)";
    let dnsClass = "badge-emerald";
    if (dnsStatus.includes("Invalid")) dnsClass = "badge-rose";

    const cat = detectCategory(item);
    const initials = getAvatarInitials(item.name);
    const dateTimeStr = formatDateTime(item.sent_at || item.created_at);

    const phoneStr = item.phone || item.mobile_number || "—";
    const phoneDisplay = phoneStr !== "—" ? `<span class="badge badge-emerald">📱 ${phoneStr}</span>` : `<span style="color: var(--text-dim);">—</span>`;

    const pageUrl = item.page_url || "#";

    html += `
      <tr>
        <td>
          <div class="user-cell">
            <div class="user-avatar">${initials}</div>
            <div class="user-info">
              <div class="user-name">${escapeHtml(item.name || "Creator")}</div>
              <div class="user-handle">@${escapeHtml(item.username || "")}</div>
            </div>
          </div>
        </td>
        <td style="font-family: monospace; color: var(--accent-blue);">${escapeHtml(item.email)}</td>
        <td>${phoneDisplay}</td>
        <td><span class="badge ${cat.badgeClass}">${cat.label}</span></td>
        <td>${dateTimeStr}</td>
        <td><span class="badge ${dnsClass}">${escapeHtml(dnsStatus)}</span></td>
        <td>
          <a href="${escapeHtml(pageUrl)}" target="_blank" class="btn btn-secondary btn-sm" style="padding: 4px 8px; font-size: 11px;">
            <span>🔗</span> Profile
          </a>
        </td>
      </tr>
    `;
  });

  tbody.innerHTML = html;
  updatePaginationBar(filteredEmails.length);
}

function renderPhoneTable() {
  const tbody = document.getElementById("facebookPhoneTableBody");
  if (!tbody) return;

  if (filteredPhones.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No verified mobile numbers match the selected filters.</td></tr>`;
    updatePhonePaginationBar(0);
    return;
  }

  const totalPages = Math.ceil(filteredPhones.length / pageSize) || 1;
  if (currentPhonePage > totalPages) currentPhonePage = totalPages;

  const startIndex = (currentPhonePage - 1) * pageSize;
  const pageItems = filteredPhones.slice(startIndex, startIndex + pageSize);

  let html = "";
  pageItems.forEach(item => {
    const phoneStr = item.phone || item.mobile_number;
    const pageUrl = item.page_url || "#";
    const platform = item.platform || "Facebook";
    const cat = detectCategory(item);
    const initials = getAvatarInitials(item.name);
    const dateTimeStr = formatDateTime(item.sent_at || item.created_at);

    html += `
      <tr>
        <td>
          <div class="user-cell">
            <div class="user-avatar" style="background: linear-gradient(135deg, var(--accent-emerald), var(--accent-cyan));">${initials}</div>
            <div class="user-info">
              <div class="user-name">${escapeHtml(item.name || "Creator")}</div>
              <div class="user-handle">@${escapeHtml(item.username || "")}</div>
            </div>
          </div>
        </td>
        <td><span class="badge badge-emerald" style="font-size: 13px; font-weight: 700;">📱 ${escapeHtml(phoneStr)}</span></td>
        <td style="font-family: monospace; color: var(--accent-blue);">${escapeHtml(item.email || "—")}</td>
        <td><span class="badge ${cat.badgeClass}">${cat.label}</span></td>
        <td>${dateTimeStr}</td>
        <td><span class="badge badge-blue">${escapeHtml(platform)}</span></td>
        <td>
          <a href="${escapeHtml(pageUrl)}" target="_blank" class="btn btn-secondary btn-sm" style="padding: 4px 8px; font-size: 11px;">
            <span>🔗</span> Profile
          </a>
        </td>
      </tr>
    `;
  });

  tbody.innerHTML = html;
  updatePhonePaginationBar(filteredPhones.length);
}

function updatePaginationBar(totalCount) {
  const info = document.getElementById("paginationInfo");
  const pageIndicator = document.getElementById("pageIndicator");
  const btnPrev = document.getElementById("btnPrevPage");
  const btnNext = document.getElementById("btnNextPage");

  const totalPages = Math.ceil(totalCount / pageSize) || 1;
  if (info) info.innerText = `Showing ${Math.min(pageSize, totalCount)} of ${totalCount} leads`;
  if (pageIndicator) pageIndicator.innerText = `Page ${currentPage} of ${totalPages}`;

  if (btnPrev) btnPrev.disabled = currentPage <= 1;
  if (btnNext) btnNext.disabled = currentPage >= totalPages;
}

function updatePhonePaginationBar(totalCount) {
  const info = document.getElementById("phonePaginationInfo");
  const pageIndicator = document.getElementById("phonePageIndicator");
  const btnPrev = document.getElementById("btnPhonePrevPage");
  const btnNext = document.getElementById("btnPhoneNextPage");

  const totalPages = Math.ceil(totalCount / pageSize) || 1;
  if (info) info.innerText = `Showing ${Math.min(pageSize, totalCount)} of ${totalCount} mobile numbers`;
  if (pageIndicator) pageIndicator.innerText = `Page ${currentPhonePage} of ${totalPages}`;

  if (btnPrev) btnPrev.disabled = currentPhonePage <= 1;
  if (btnNext) btnNext.disabled = currentPhonePage >= totalPages;
}

function changePage(delta) {
  currentPage += delta;
  renderTable();
}

function changePhonePage(delta) {
  currentPhonePage += delta;
  renderPhoneTable();
}

function changePageSize(size) {
  pageSize = parseInt(size) || 25;
  currentPage = 1;
  currentPhonePage = 1;
  renderTable();
  renderPhoneTable();
}

function exportEmailsCSV() {
  if (facebookEmailsList.length === 0) {
    showToast("No emails to export", false);
    return;
  }

  let csvContent = "data:text/csv;charset=utf-8,Name,Category,Email,Phone,Date Added,DNS Status,Location,Page URL\n";
  facebookEmailsList.forEach(item => {
    const cat = detectCategory(item).label;
    const dateStr = item.sent_at || item.created_at || "";
    const name = `"${(item.name || "").replace(/"/g, '""')}"`;
    const category = `"${cat.replace(/"/g, '""')}"`;
    const email = `"${(item.email || "").replace(/"/g, '""')}"`;
    const phone = `"${(item.phone || item.mobile_number || "").replace(/"/g, '""')}"`;
    const date = `"${dateStr.replace(/"/g, '""')}"`;
    const dns = `"${(item.dns_status || "").replace(/"/g, '""')}"`;
    const location = `"${(item.location || "").replace(/"/g, '""')}"`;
    const url = `"${(item.page_url || "").replace(/"/g, '""')}"`;

    csvContent += `${name},${category},${email},${phone},${date},${dns},${location},${url}\n`;
  });

  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  link.setAttribute("download", "creator_email_directory.csv");
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  showToast("📥 Exported Email Directory CSV!");
}

function exportPhonesCSV() {
  const phoneItems = facebookEmailsList.filter(item => item.phone || item.mobile_number);
  if (phoneItems.length === 0) {
    showToast("No mobile numbers to export", false);
    return;
  }

  let csvContent = "data:text/csv;charset=utf-8,Name,Category,Verified Mobile Number,Email,Date Verified,Platform,Location,Page URL\n";
  phoneItems.forEach(item => {
    const cat = detectCategory(item).label;
    const dateStr = item.sent_at || item.created_at || "";
    const name = `"${(item.name || "").replace(/"/g, '""')}"`;
    const category = `"${cat.replace(/"/g, '""')}"`;
    const phone = `"${(item.phone || item.mobile_number || "").replace(/"/g, '""')}"`;
    const email = `"${(item.email || "").replace(/"/g, '""')}"`;
    const date = `"${dateStr.replace(/"/g, '""')}"`;
    const platform = `"${(item.platform || "Facebook").replace(/"/g, '""')}"`;
    const location = `"${(item.location || "").replace(/"/g, '""')}"`;
    const url = `"${(item.page_url || "").replace(/"/g, '""')}"`;

    csvContent += `${name},${category},${phone},${email},${date},${platform},${location},${url}\n`;
  });

  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  link.setAttribute("download", "verified_mobile_numbers.csv");
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  showToast("📱 Exported Verified Mobile Numbers CSV!");
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
