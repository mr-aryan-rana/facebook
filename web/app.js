/* ==========================================================================
   📘 FACEBOOK CREATOR EMAIL OUTREACH - HIGH-PERFORMANCE DASHBOARD JS
   ========================================================================== */

let isHarvesterRunning = false;
let pollingInterval = null;
let facebookEmailsList = [];
let filteredEmails = [];

let currentPage = 1;
let pageSize = 25;
let lastEmailCount = -1;

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
      
      // Update metric cards instantly without re-rendering full DOM
      document.getElementById("metricTotalEmails").innerText = data.totalEmails !== undefined ? data.totalEmails : 0;
      document.getElementById("metricSentEmails").innerText = data.totalSent !== undefined ? data.totalSent : 0;
      document.getElementById("metricVerifiedEmails").innerText = data.dnsVerified !== undefined ? data.dnsVerified : 0;
      document.getElementById("metricLeadsCount").innerText = data.totalEmails !== undefined ? data.totalEmails : 0;

      // Only reload email list if data count changed
      if (data.totalEmails !== undefined && data.totalEmails !== lastEmailCount) {
        lastEmailCount = data.totalEmails;
        if (data.emails && data.emails.length > 0) {
          facebookEmailsList = data.emails;
          applyFilterAndRender();
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
}

function updateUIStatus(running, statusText) {
  isHarvesterRunning = running;
  const badge = document.getElementById("statusBadge");
  const text = document.getElementById("statusText");
  const btnStart = document.getElementById("btnStart");
  const btnStop = document.getElementById("btnStop");

  text.innerText = statusText || (running ? "Harvester Active" : "System Idle");

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

async function startHarvester() {
  const reqBudget = parseInt(document.getElementById("fbRequestBudget").value) || 100;
  updateUIStatus(true, "Launching Facebook Harvester...");

  try {
    const res = await fetch("/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ requests: reqBudget })
    });
    if (res.ok) {
      const data = await res.json();
      showToast("🚀 Facebook Email Harvester started!");
    }
  } catch (err) {
    console.error("Failed to start Facebook harvester:", err);
    showToast("⚠️ Failed to start harvester", false);
  }
}

async function stopHarvester() {
  updateUIStatus(false, "Stopping Harvester...");
  try {
    const res = await fetch("/api/stop", { method: "POST" });
    if (res.ok) {
      showToast("⏹️ Facebook Harvester stopped");
    }
  } catch (err) {
    console.error("Failed to stop Facebook harvester:", err);
  }
}

async function loadEmails() {
  try {
    const res = await fetch("/api/emails");
    if (res.ok) {
      const data = await res.json();
      facebookEmailsList = data.emails || [];
      lastEmailCount = data.totalEmails || facebookEmailsList.length;

      document.getElementById("metricTotalEmails").innerText = data.totalEmails !== undefined ? data.totalEmails : facebookEmailsList.length;
      document.getElementById("metricSentEmails").innerText = data.totalSent !== undefined ? data.totalSent : 0;
      document.getElementById("metricVerifiedEmails").innerText = data.dnsVerified !== undefined ? data.dnsVerified : facebookEmailsList.length;
      document.getElementById("metricLeadsCount").innerText = facebookEmailsList.length;

      applyFilterAndRender();
    }
  } catch (err) {
    console.error("Failed to load Facebook emails:", err);
  }
}

function applyFilterAndRender() {
  const query = (document.getElementById("tableFilterInput")?.value || "").toLowerCase().trim();
  
  if (!query) {
    filteredEmails = [...facebookEmailsList];
  } else {
    filteredEmails = facebookEmailsList.filter(item => {
      const name = (item.name || "").toLowerCase();
      const uname = (item.username || "").toLowerCase();
      const email = (item.email || "").toLowerCase();
      const dns = (item.dns_status || "").toLowerCase();
      const status = (item.status || "").toLowerCase();
      return name.includes(query) || uname.includes(query) || email.includes(query) || dns.includes(query) || status.includes(query);
    });
  }

  // Ensure current page is valid
  const totalPages = Math.max(1, Math.ceil(filteredEmails.length / pageSize));
  if (currentPage > totalPages) currentPage = totalPages;

  renderPaginatedTable();
}

function renderPaginatedTable() {
  const tbody = document.getElementById("facebookTableBody");
  const totalItems = filteredEmails.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));

  const startIdx = (currentPage - 1) * pageSize;
  const endIdx = Math.min(startIdx + pageSize, totalItems);
  const pageItems = filteredEmails.slice(startIdx, endIdx);

  // Update pagination info & controls
  const infoEl = document.getElementById("paginationInfo");
  const indicatorEl = document.getElementById("pageIndicator");
  const btnPrev = document.getElementById("btnPrevPage");
  const btnNext = document.getElementById("btnNextPage");

  if (infoEl) {
    infoEl.innerText = totalItems > 0 
      ? `Showing ${startIdx + 1} to ${endIdx} of ${totalItems} creator emails`
      : "No creator emails found";
  }
  if (indicatorEl) indicatorEl.innerText = `Page ${currentPage} of ${totalPages}`;
  if (btnPrev) btnPrev.disabled = (currentPage <= 1);
  if (btnNext) btnNext.disabled = (currentPage >= totalPages);

  if (pageItems.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No Facebook creator emails found. Run harvester to collect leads.</td></tr>`;
    return;
  }

  let html = "";
  pageItems.forEach(item => {
    const isSent = item.status && item.status.includes("Sent");
    const isVerified = item.dns_status && (item.dns_status.includes("Valid") || item.dns_status.includes("Verified"));

    let statusPill = `<span class="pill-badge pill-success">Verified Lead</span>`;
    if (isSent) {
      statusPill = `<span class="pill-badge pill-success" style="background: rgba(59, 130, 246, 0.2); color: #60a5fa; border-color: rgba(59, 130, 246, 0.4);">Email Sent</span>`;
    } else if (!isVerified) {
      statusPill = `<span class="pill-badge pill-skipped">Pending</span>`;
    }

    const username = item.username || "creator";
    const email = item.email || "";
    const pageUrl = item.page_url || `https://www.facebook.com/${username}`;
    const sentTime = item.sent_at ? new Date(item.sent_at).toLocaleString() : "Ready for Mail";

    html += `
      <tr>
        <td>${statusPill}</td>
        <td>
          <div class="user-handle">${escapeHtml(item.name || username)}</div>
          <div class="user-name">@${escapeHtml(username)}</div>
        </td>
        <td>
          <div style="display: flex; align-items: center; gap: 6px;">
            <a href="mailto:${email}" style="color: #60a5fa; font-weight: 500; text-decoration: none;">${escapeHtml(email)}</a>
            <button onclick="copyToClipboard('${escapeHtml(email)}')" title="Copy Email" style="background: transparent; border: none; cursor: pointer; font-size: 13px;">📋</button>
          </div>
        </td>
        <td>
          <span style="font-size: 11px; padding: 2px 8px; border-radius: 10px; background: rgba(16, 185, 129, 0.12); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.25);">
            🛡️ ${escapeHtml(item.dns_status || 'Valid (DNS Verified)')}
          </span>
        </td>
        <td>
          <a class="link-btn" href="${escapeHtml(pageUrl)}" target="_blank" rel="noopener">
            📘 View FB Page ↗
          </a>
        </td>
        <td>${escapeHtml(item.location || 'United States')}</td>
        <td>
          <div style="display: flex; flex-direction: column; gap: 4px;">
            <span style="font-size: 11px; color: #9ca3af;">${sentTime}</span>
            <a href="mailto:${email}?subject=Collaboration%20Query&body=Hi%20${encodeURIComponent(item.name || 'there')}," class="link-btn" style="font-size: 11px; background: rgba(139, 92, 246, 0.15); color: #c4b5fd;">
              ✉️ Send Mail
            </a>
          </div>
        </td>
      </tr>
    `;
  });

  tbody.innerHTML = html;
}

function changePage(delta) {
  const totalPages = Math.max(1, Math.ceil(filteredEmails.length / pageSize));
  currentPage += delta;
  if (currentPage < 1) currentPage = 1;
  if (currentPage > totalPages) currentPage = totalPages;
  renderPaginatedTable();
}

function changePageSize(newSize) {
  pageSize = parseInt(newSize) || 25;
  currentPage = 1;
  renderPaginatedTable();
}

function filterTable() {
  currentPage = 1;
  applyFilterAndRender();
}

function copyToClipboard(text) {
  navigator.clipboard.writeText(text);
  showToast(`📋 Copied to clipboard: ${text}`);
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

function exportEmailsCSV() {
  if (!facebookEmailsList || facebookEmailsList.length === 0) {
    showToast("⚠️ No Facebook emails available to export", false);
    return;
  }

  let csvContent = "data:text/csv;charset=utf-8,Name,Username,Email,DNS Status,Page URL,Location,Status,Sent Date\n";
  facebookEmailsList.forEach(item => {
    const row = [
      `"${(item.name || '').replace(/"/g, '""')}"`,
      `"${(item.username || '').replace(/"/g, '""')}"`,
      `"${(item.email || '').replace(/"/g, '""')}"`,
      `"${(item.dns_status || '').replace(/"/g, '""')}"`,
      `"${(item.page_url || '').replace(/"/g, '""')}"`,
      `"${(item.location || '').replace(/"/g, '""')}"`,
      `"${(item.status || '').replace(/"/g, '""')}"`,
      `"${(item.sent_at || '').replace(/"/g, '""')}"`
    ];
    csvContent += row.join(",") + "\n";
  });

  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  link.setAttribute("download", `facebook_creator_emails_${Date.now()}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  showToast("📥 Exported Facebook creator emails CSV");
}
