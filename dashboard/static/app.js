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
    document.getElementById("unpushed-banner").classList.toggle("hidden", !data.unpushed_watchlist_changes);
  } catch (err) {
    pill.textContent = "Status unavailable";
    pill.className = "status-pill status-unknown";
  }
}

// ---------- Feed ----------
async function loadFeed() {
  const watchItemId = document.getElementById("filter-watch-item").value;
  const sort = document.getElementById("sort-order").value;
  const params = new URLSearchParams();
  if (watchItemId) params.set("watch_item_id", watchItemId);
  params.set("sort", sort);
  const res = await fetch(`/api/findings?${params.toString()}`);
  state.findings = await res.json();
  renderFeed();
}

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

    card.innerHTML = `
      <div class="card-image">${img}</div>
      <div class="card-body">
        <div class="card-title">${escapeHtml(f.listing.title)}</div>
        <div class="card-price">${fmtPrice(f.all_in_price)}</div>
        <div class="badge-row">
          <span class="badge ${scoreBadgeClass(scoreColor(f.deal_score))}">${f.deal_score}/100</span>
          <span class="badge badge-liquidity">${f.liquidity.rating} liquidity</span>
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
async function openDetail(findingId) {
  const res = await fetch(`/api/findings/${encodeURIComponent(findingId)}`);
  if (!res.ok) return;
  const f = await res.json();
  const content = document.getElementById("detail-content");
  content.innerHTML = `
    <div class="detail-title">${escapeHtml(f.listing.title)}</div>
    <div class="detail-price">${fmtPrice(f.all_in_price)}
      <span class="badge ${scoreBadgeClass(scoreColor(f.deal_score))}">${f.deal_score}/100</span>
      <span class="badge badge-liquidity">${f.liquidity.rating} liquidity</span>
    </div>

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
    <div class="disclaimer">${DISCLAIMER}</div>
  `;
  document.getElementById("detail-overlay").classList.remove("hidden");
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
})();
