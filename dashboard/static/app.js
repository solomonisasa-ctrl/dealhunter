const state = {
  findings: [],
  watchlist: [],
  categories: {},
};

const DISCLAIMER =
  "These are AI-generated estimates, not professional appraisals. Do your own diligence before buying or reselling.";

function fmtPrice(v) {
  return v === null || v === undefined ? "n/a" : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function scoreBadgeClass(color) {
  return { green: "badge-green", yellow: "badge-yellow", red: "badge-red" }[color] || "badge-yellow";
}

function timeAgo(ts) {
  if (!ts) return "";
  const diff = Date.now() / 1000 - ts;
  if (diff < 3600) return `${Math.max(1, Math.round(diff / 60))}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

// ---------- Tabs ----------
document.getElementById("tabs").addEventListener("click", (e) => {
  const btn = e.target.closest(".tab");
  if (!btn) return;
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  btn.classList.add("active");
  document.getElementById(`view-${btn.dataset.tab}`).classList.add("active");
});

// ---------- Status ----------
async function loadStatus() {
  const pill = document.getElementById("status-pill");
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    const latest = data.latest;
    if (!latest) {
      pill.textContent = "No runs yet";
      pill.className = "status-pill status-unknown";
    } else {
      const counts = Object.entries(latest.sources)
        .map(([name, h]) => `${name}: ${h.fetched}`)
        .join(", ");
      pill.textContent = `Last run ${timeAgo(latest.timestamp)} · ${latest.overall_status} · ${counts || "no sources"}`;
      pill.className = `status-pill status-${latest.overall_status}`;
    }
    document.getElementById("unpushed-banner").classList.toggle("hidden", !data.unpushed_config_changes);
  } catch (err) {
    pill.textContent = "Status unavailable";
    pill.className = "status-pill status-unknown";
  }
}

// ---------- Schedule (poll interval + pause) ----------
function updatePauseButton(paused) {
  const btn = document.getElementById("pause-toggle");
  btn.textContent = paused ? "▶ Resume hunting" : "⏸ Pause hunting";
  btn.classList.toggle("btn-paused", paused);
  btn.dataset.paused = paused ? "1" : "0";
}

async function loadSchedule() {
  const select = document.getElementById("poll-interval");
  try {
    const res = await fetch("/api/schedule");
    const data = await res.json();
    const minutes = String(data.poll_interval_minutes);
    if (!select.querySelector(`option[value="${minutes}"]`)) {
      // Someone hand-edited schedule.yaml to a non-preset value - show it anyway.
      const opt = document.createElement("option");
      opt.value = minutes;
      opt.textContent = `Poll every ${minutes} min`;
      select.appendChild(opt);
    }
    select.value = minutes;
    updatePauseButton(data.paused);
  } catch (err) {
    // Leave the default selection if the schedule can't be loaded.
  }
}

document.getElementById("poll-interval").addEventListener("change", async (e) => {
  await fetch("/api/schedule", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ poll_interval_minutes: Number(e.target.value) }),
  });
  loadStatus();
});

document.getElementById("pause-toggle").addEventListener("click", async () => {
  const btn = document.getElementById("pause-toggle");
  const currentlyPaused = btn.dataset.paused === "1";
  const res = await fetch("/api/schedule", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paused: !currentlyPaused }),
  });
  const data = await res.json();
  updatePauseButton(data.paused);
  loadStatus();
});

// ---------- Refresh now ----------
document.getElementById("refresh-now").addEventListener("click", async () => {
  const btn = document.getElementById("refresh-now");
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Refreshing…";
  try {
    const res = await fetch("/api/run-now", { method: "POST" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(`Refresh failed: ${err.detail || res.statusText}`);
    } else {
      await Promise.all([loadFeed(), loadStatus()]);
    }
  } catch (err) {
    alert(`Refresh failed: ${err}`);
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
});

// ---------- Feed ----------
async function loadFeed() {
  const watchItemId = document.getElementById("filter-watch-item").value;
  const sort = document.getElementById("sort-order").value;
  const showAll = document.getElementById("show-all").checked;
  const params = new URLSearchParams();
  if (watchItemId) params.set("watch_item_id", watchItemId);
  params.set("sort", sort);
  if (showAll) params.set("show_all", "1");
  const res = await fetch(`/api/findings?${params.toString()}`);
  state.findings = await res.json();
  renderFeed();
}

document.getElementById("show-all").addEventListener("change", loadFeed);

function renderFeed() {
  const grid = document.getElementById("feed-grid");
  const empty = document.getElementById("feed-empty");
  grid.innerHTML = "";
  empty.classList.toggle("hidden", state.findings.length > 0);

  for (const f of state.findings) {
    const card = document.createElement("div");
    card.className = "card";
    card.addEventListener("click", () => openDetail(f.id));

    const img = f.listing.image_url
      ? `<img src="${f.listing.image_url}" alt="">`
      : "No image";

    const duplicateBadge = f.duplicate_of
      ? '<span class="badge badge-duplicate">Possible duplicate</span>'
      : "";

    card.innerHTML = `
      <div class="card-image">${img}</div>
      <div class="card-body">
        <div class="card-title">${escapeHtml(f.listing.title)}</div>
        <div class="card-price">${fmtPrice(f.all_in_price)}</div>
        <div class="badge-row">
          <span class="badge ${scoreBadgeClass(scoreColor(f.deal_score))}">${f.deal_score}/100</span>
          <span class="badge badge-liquidity">${f.liquidity.rating} liquidity</span>
          ${duplicateBadge}
        </div>
        <div class="card-summary">${escapeHtml(f.analysis.condition_summary || "")}</div>
      </div>
    `;
    grid.appendChild(card);
  }
}

function scoreColor(score) {
  if (score >= 80) return "green";
  if (score >= 50) return "yellow";
  return "red";
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s || "";
  return div.innerHTML;
}

document.getElementById("filter-watch-item").addEventListener("change", loadFeed);
document.getElementById("sort-order").addEventListener("change", loadFeed);

// ---------- Detail overlay ----------
let currentFindingId = null;

function renderQaList(qaHistory) {
  if (!qaHistory || qaHistory.length === 0) {
    return '<p class="qa-empty">No questions asked yet.</p>';
  }
  return `<div class="qa-list">${qaHistory
    .map(
      (qa) => `
      <div class="qa-entry">
        <div class="qa-question">${escapeHtml(qa.question)}</div>
        <div class="qa-answer">${escapeHtml(qa.answer)}</div>
      </div>`
    )
    .join("")}</div>`;
}

async function openDetail(findingId) {
  const res = await fetch(`/api/findings/${encodeURIComponent(findingId)}`);
  if (!res.ok) return;
  const f = await res.json();
  currentFindingId = f.id;
  const content = document.getElementById("detail-content");
  const duplicateNote = f.duplicate_of
    ? `<div class="banner duplicate-banner">Possible duplicate of <a href="#" data-open-finding="${escapeHtml(f.duplicate_of)}">an earlier finding</a> for this watch item - no notification was sent for this one.</div>`
    : "";

  content.innerHTML = `
    <div class="detail-title">${escapeHtml(f.listing.title)}</div>
    <div class="detail-price">${fmtPrice(f.all_in_price)}
      <span class="badge ${scoreBadgeClass(scoreColor(f.deal_score))}">${f.deal_score}/100</span>
      <span class="badge badge-liquidity">${f.liquidity.rating} liquidity</span>
    </div>
    ${duplicateNote}

    <div class="detail-section">
      <h4>Match reasoning</h4>
      <p>${escapeHtml(f.analysis.match_reasoning)}</p>
    </div>
    <div class="detail-section">
      <h4>Valuation</h4>
      <p>Estimated value: ${fmtPrice(f.analysis.estimated_value)} (confidence ${(f.analysis.confidence * 100).toFixed(0)}%)<br>
      ${f.discount !== null ? `Discount vs. estimated value: ${(f.discount * 100).toFixed(0)}%` : "Discount: n/a"}</p>
    </div>
    <div class="detail-section">
      <h4>Condition</h4>
      <p>${escapeHtml(f.analysis.condition_summary)}</p>
    </div>
    <div class="detail-section">
      <h4>Authenticity (${f.analysis.authenticity_risk} risk)</h4>
      <p>${escapeHtml(f.analysis.authenticity_notes)}</p>
    </div>
    <div class="detail-section">
      <h4>Rarity</h4>
      <p>${escapeHtml(f.analysis.rarity_notes)}</p>
    </div>
    <div class="detail-section">
      <h4>Liquidity reasoning</h4>
      <p>${escapeHtml(f.liquidity.reasoning)}</p>
    </div>

    <a class="detail-link" href="${f.listing.url}" target="_blank" rel="noopener noreferrer">View original listing →</a>

    <div class="detail-section">
      <h4>Ask a follow-up</h4>
      <div id="qa-list">${renderQaList(f.qa_history)}</div>
      <form class="qa-form" id="qa-form">
        <input type="text" id="qa-input" placeholder="Ask a question about this listing…" autocomplete="off" />
        <button type="submit" class="btn btn-secondary" id="qa-submit">Ask</button>
      </form>
    </div>

    <div class="disclaimer">${DISCLAIMER}</div>
  `;
  document.getElementById("detail-overlay").classList.remove("hidden");

  const originalLink = content.querySelector("[data-open-finding]");
  if (originalLink) {
    originalLink.addEventListener("click", (e) => {
      e.preventDefault();
      openDetail(originalLink.dataset.openFinding);
    });
  }

  document.getElementById("qa-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("qa-input");
    const submitBtn = document.getElementById("qa-submit");
    const question = input.value.trim();
    if (!question) return;

    input.disabled = true;
    submitBtn.disabled = true;
    submitBtn.textContent = "Asking…";
    try {
      const askRes = await fetch(`/api/findings/${encodeURIComponent(currentFindingId)}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      if (!askRes.ok) {
        const err = await askRes.json().catch(() => ({}));
        alert(`Question failed: ${err.detail || askRes.statusText}`);
        return;
      }
      const updated = await askRes.json();
      document.getElementById("qa-list").innerHTML = renderQaList(updated.qa_history);
      input.value = "";
    } catch (err) {
      alert(`Question failed: ${err}`);
    } finally {
      input.disabled = false;
      submitBtn.disabled = false;
      submitBtn.textContent = "Ask";
    }
  });
}

document.getElementById("detail-close").addEventListener("click", () => {
  document.getElementById("detail-overlay").classList.add("hidden");
});
document.getElementById("detail-overlay").addEventListener("click", (e) => {
  if (e.target.id === "detail-overlay") e.target.classList.add("hidden");
});

// ---------- Watchlist ----------
async function loadWatchlist() {
  const [wRes, cRes] = await Promise.all([fetch("/api/watchlist"), fetch("/api/categories")]);
  state.watchlist = await wRes.json();
  state.categories = await cRes.json();
  renderWatchlist();
  renderWatchItemFilter();
}

function renderWatchItemFilter() {
  const select = document.getElementById("filter-watch-item");
  const current = select.value;
  select.innerHTML = '<option value="">All watch items</option>';
  for (const item of state.watchlist) {
    const opt = document.createElement("option");
    opt.value = item.id;
    opt.textContent = item.id;
    select.appendChild(opt);
  }
  select.value = current;
}

function renderWatchlist() {
  const container = document.getElementById("watchlist-items");
  container.innerHTML = "";
  for (const item of state.watchlist) {
    const card = document.createElement("div");
    card.className = `watch-item-card ${item.enabled ? "" : "disabled"}`;
    card.innerHTML = `
      <div class="watch-item-main">
        <strong>${escapeHtml(item.id)}</strong> <span class="badge badge-liquidity">${escapeHtml(item.category)}</span>
        <div class="watch-item-desc">${escapeHtml(item.description)}</div>
        <div class="watch-item-meta">
          <span>Discount threshold: ${(item.discount_threshold * 100).toFixed(0)}%</span>
          <span>Lookback: ${item.lookback_days}d</span>
          <span>${item.enabled ? "Enabled" : "Disabled"}</span>
        </div>
      </div>
      <div class="watch-item-actions">
        <button class="btn btn-secondary" data-action="edit" data-id="${item.id}">Edit</button>
        <button class="btn btn-danger" data-action="delete" data-id="${item.id}">Delete</button>
      </div>
    `;
    container.appendChild(card);
  }
  container.querySelectorAll('[data-action="edit"]').forEach((btn) =>
    btn.addEventListener("click", () => openEdit(btn.dataset.id))
  );
  container.querySelectorAll('[data-action="delete"]').forEach((btn) =>
    btn.addEventListener("click", () => deleteWatchItem(btn.dataset.id))
  );
}

function openEdit(itemId) {
  const item = itemId
    ? state.watchlist.find((i) => i.id === itemId)
    : { id: "", category: Object.keys(state.categories)[0] || "watches", description: "", discount_threshold: 0.3, lookback_days: 30, enabled: true, parsed_criteria: null };

  const categoryOptions = Object.keys(state.categories)
    .map((c) => `<option value="${c}" ${c === item.category ? "selected" : ""}>${c}</option>`)
    .join("");

  document.getElementById("edit-content").innerHTML = `
    <h3>${itemId ? "Edit hunt" : "Add hunt"}</h3>
    <form class="edit-form" id="edit-form">
      <div>
        <label>Id</label>
        <input name="id" value="${escapeHtml(item.id)}" ${itemId ? "readonly" : ""} required />
      </div>
      <div>
        <label>Category</label>
        <select name="category">${categoryOptions}</select>
      </div>
      <div>
        <label>Description (plain English)</label>
        <textarea name="description" required>${escapeHtml(item.description)}</textarea>
      </div>
      <div class="field-row">
        <div>
          <label>Discount threshold (%)</label>
          <input name="discount_threshold" type="number" min="0" max="100" step="1" value="${item.discount_threshold * 100}" />
        </div>
        <div>
          <label>Lookback (days)</label>
          <input name="lookback_days" type="number" min="1" value="${item.lookback_days}" />
        </div>
      </div>
      <div>
        <label><input type="checkbox" name="enabled" ${item.enabled ? "checked" : ""} style="width:auto;display:inline-block;margin-right:6px;" /> Enabled</label>
      </div>
      <div class="form-actions">
        <button type="submit" class="btn btn-primary">Save</button>
        <button type="button" class="btn btn-secondary" id="edit-cancel">Cancel</button>
      </div>
    </form>
  `;
  document.getElementById("edit-overlay").classList.remove("hidden");
  document.getElementById("edit-cancel").addEventListener("click", closeEdit);

  document.getElementById("edit-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    const payload = {
      id: form.get("id").trim(),
      category: form.get("category"),
      description: form.get("description").trim(),
      discount_threshold: Number(form.get("discount_threshold")) / 100,
      lookback_days: Number(form.get("lookback_days")),
      enabled: form.get("enabled") === "on",
      // Changing the description invalidates any previously-parsed criteria
      // so the next run re-parses it via Claude.
      parsed_criteria: itemId && item.description === form.get("description").trim() ? item.parsed_criteria : null,
    };
    await fetch("/api/watchlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    closeEdit();
    loadWatchlist();
  });
}

function closeEdit() {
  document.getElementById("edit-overlay").classList.add("hidden");
}

document.getElementById("edit-close").addEventListener("click", closeEdit);
document.getElementById("edit-overlay").addEventListener("click", (e) => {
  if (e.target.id === "edit-overlay") closeEdit();
});
document.getElementById("add-watch-item").addEventListener("click", () => openEdit(null));

async function deleteWatchItem(itemId) {
  if (!confirm(`Delete hunt "${itemId}"? This cannot be undone.`)) return;
  await fetch(`/api/watchlist/${encodeURIComponent(itemId)}`, { method: "DELETE" });
  loadWatchlist();
}

// ---------- Init ----------
(async function init() {
  await loadWatchlist();
  await loadFeed();
  await loadStatus();
  await loadSchedule();
})();
