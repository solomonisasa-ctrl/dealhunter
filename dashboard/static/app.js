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
      const soldNote = latest.sold_detected > 0 ? ` · ${latest.sold_detected} sold` : "";
      pill.textContent = `Last run ${timeAgo(latest.timestamp)} · ${latest.overall_status} · ${counts || "no sources"}${soldNote}`;
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
function setProgressUI(visible, pct, label) {
  const container = document.getElementById("refresh-progress-container");
  const bar = document.getElementById("refresh-progress-bar");
  const labelEl = document.getElementById("refresh-progress-label");
  container.classList.toggle("hidden", !visible);
  labelEl.classList.toggle("hidden", !visible);
  if (visible) {
    bar.style.width = `${pct}%`;
    labelEl.textContent = label;
  }
}

async function pollRunStatus() {
  const btn = document.getElementById("refresh-now");
  const res = await fetch("/api/run-status");
  const status = await res.json();

  if (status.running) {
    const pct = status.total > 0 ? Math.min(100, Math.round((status.current / status.total) * 100)) : 0;
    const label = `${status.phase}${status.detail ? " - " + status.detail : ""} (${pct}%)`;
    setProgressUI(true, pct, label);
    btn.textContent = "Refreshing…";
    setTimeout(pollRunStatus, 1000);
  } else {
    setProgressUI(false, 0, "");
    btn.disabled = false;
    btn.textContent = "⟳ Refresh now";
    if (status.error) {
      alert(`Refresh failed: ${status.error}`);
    }
    await Promise.all([loadFeed(), loadStatus()]);
  }
}

document.getElementById("refresh-now").addEventListener("click", async () => {
  const btn = document.getElementById("refresh-now");
  btn.disabled = true;
  btn.textContent = "Starting…";
  try {
    const res = await fetch("/api/run-now", { method: "POST" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(`Refresh failed: ${err.detail || res.statusText}`);
      btn.disabled = false;
      btn.textContent = "⟳ Refresh now";
      return;
    }
  } catch (err) {
    alert(`Refresh failed: ${err}`);
    btn.disabled = false;
    btn.textContent = "⟳ Refresh now";
    return;
  }
  setTimeout(pollRunStatus, 300);
});

// If a refresh was already running when the page loaded (e.g. triggered
// from another tab, or this tab was reloaded mid-run), pick up polling
// instead of showing a stale idle button.
(async function resumeProgressIfRunning() {
  const res = await fetch("/api/run-status");
  const status = await res.json();
  if (status.running) {
    document.getElementById("refresh-now").disabled = true;
    pollRunStatus();
  }
})();

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

    const photoCount = photoUrls(f.listing).length;
    const img = f.listing.image_url
      ? `<img src="${f.listing.image_url}" alt="">`
      : "No image";
    const photoCountBadge = photoCount > 1 ? `<span class="photo-count">📷 ${photoCount}</span>` : "";

    const duplicateBadge = f.duplicate_of
      ? '<span class="badge badge-duplicate">Possible duplicate</span>'
      : "";
    const depthBadge =
      f.analysis_depth === "quick" ? '<span class="badge badge-liquidity">Quick scan</span>' : "";
    const soldBadge = f.listing.status === "sold" ? '<span class="badge badge-red">Sold</span>' : "";

    card.innerHTML = `
      <div class="card-image">${img}${photoCountBadge}</div>
      <div class="card-body">
        <div class="card-title">${escapeHtml(f.listing.title)}</div>
        <div class="card-price">${fmtPrice(f.all_in_price)}</div>
        <div class="badge-row">
          <span class="badge ${scoreBadgeClass(scoreColor(f.deal_score))}">${dealLabel(f.deal_score)}</span>
          <span class="badge badge-liquidity">${f.liquidity.rating} liquidity</span>
          ${depthBadge}
          ${soldBadge}
          ${duplicateBadge}
        </div>
        <div class="card-summary">${escapeHtml(f.analysis.condition_summary || "")}</div>
      </div>
    `;
    grid.appendChild(card);
  }
}

function scoreColor(score) {
  // deal_score is a plain percent under/over market value, not an abstract
  // 0-100 scale - these bands are percent thresholds.
  if (score >= 30) return "green";
  if (score >= 10) return "yellow";
  return "red";
}

function dealLabel(score) {
  return score >= 0 ? `${score}% under market` : `${Math.abs(score)}% over market`;
}

// All photos for a listing, falling back to just the primary image for
// findings scored before multi-image support existed.
function photoUrls(listing) {
  if (listing.image_urls && listing.image_urls.length > 0) return listing.image_urls;
  return listing.image_url ? [listing.image_url] : [];
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

function renderPhotoGallery(listing) {
  const urls = photoUrls(listing);
  if (urls.length === 0) return "";
  const thumbs = urls
    .map(
      (url, i) =>
        `<a href="${url}" target="_blank" rel="noopener noreferrer"><img src="${url}" alt="Photo ${i + 1}" loading="lazy"></a>`
    )
    .join("");
  return `<div class="detail-section"><h4>Photos (${urls.length})</h4><div class="photo-gallery">${thumbs}</div></div>`;
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

  const photoCount = photoUrls(f.listing).length;
  const isSold = f.listing.status === "sold";
  const canRunFullAnalysis = f.analysis_depth !== "full" && photoCount > 1 && !isSold;
  const depthNote =
    f.analysis_depth === "quick"
      ? `<span class="badge badge-liquidity">Quick scan (1 of ${photoCount} photos)</span>`
      : "";
  const soldNote = isSold ? '<span class="badge badge-red">Sold</span>' : "";
  const fullAnalysisSection = canRunFullAnalysis
    ? `<div class="detail-section">
        <button type="button" class="btn btn-secondary" id="full-analysis-btn">📸 Run full analysis (all ${photoCount} photos)</button>
      </div>`
    : "";

  content.innerHTML = `
    <div class="detail-title">${escapeHtml(f.listing.title)}</div>
    <div class="detail-price">${fmtPrice(f.all_in_price)}
      <span class="badge ${scoreBadgeClass(scoreColor(f.deal_score))}">${dealLabel(f.deal_score)}</span>
      <span class="badge badge-liquidity">${f.liquidity.rating} liquidity</span>
      ${depthNote}
      ${soldNote}
    </div>
    ${duplicateNote}
    ${renderPhotoGallery(f.listing)}
    ${fullAnalysisSection}

    <div class="detail-section">
      <h4>Match reasoning</h4>
      <p>${escapeHtml(f.analysis.match_reasoning)}</p>
    </div>
    <div class="detail-section">
      <h4>Valuation</h4>
      <p>Estimated value: ${fmtPrice(f.analysis.estimated_value)} (Claude's confidence: ${(f.analysis.confidence * 100).toFixed(0)}%)<br>
      ${f.discount !== null ? `Price vs. estimated value: ${dealLabel(Math.round(f.discount * 100))}` : "Discount: n/a"}</p>
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

  const fullAnalysisBtn = document.getElementById("full-analysis-btn");
  if (fullAnalysisBtn) {
    fullAnalysisBtn.addEventListener("click", async () => {
      const originalText = fullAnalysisBtn.textContent;
      fullAnalysisBtn.disabled = true;
      fullAnalysisBtn.textContent = "Analyzing all photos…";
      try {
        const res = await fetch(`/api/findings/${encodeURIComponent(currentFindingId)}/full-analysis`, {
          method: "POST",
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          alert(`Full analysis failed: ${err.detail || res.statusText}`);
          fullAnalysisBtn.disabled = false;
          fullAnalysisBtn.textContent = originalText;
          return;
        }
        await openDetail(currentFindingId);
        loadFeed();
      } catch (err) {
        alert(`Full analysis failed: ${err}`);
        fullAnalysisBtn.disabled = false;
        fullAnalysisBtn.textContent = originalText;
      }
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
          <span>Discount threshold: ${item.discount_threshold !== null && item.discount_threshold !== undefined ? (item.discount_threshold * 100).toFixed(0) + "%" : "none - any match"}</span>
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
    : { id: "", category: Object.keys(state.categories)[0] || "watches", description: "", discount_threshold: null, lookback_days: 30, enabled: true, parsed_criteria: null };

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
        <button type="button" class="btn btn-secondary" id="preview-match-count-btn" style="margin-top:6px;">Preview match count</button>
        <div id="preview-match-count-result"></div>
      </div>
      <div class="field-row">
        <div>
          <label>Discount threshold (%) - optional, leave blank for any match</label>
          <input name="discount_threshold" type="number" min="0" max="100" step="1" value="${item.discount_threshold !== null && item.discount_threshold !== undefined ? item.discount_threshold * 100 : ""}" placeholder="any" />
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

  document.getElementById("preview-match-count-btn").addEventListener("click", async () => {
    const btn = document.getElementById("preview-match-count-btn");
    const resultEl = document.getElementById("preview-match-count-result");
    const description = document.querySelector('textarea[name="description"]').value.trim();
    const category = document.querySelector('select[name="category"]').value;
    if (!description) {
      resultEl.textContent = "Enter a description first.";
      return;
    }
    btn.disabled = true;
    btn.textContent = "Checking…";
    resultEl.textContent = "";
    try {
      const res = await fetch(
        `/api/watchlist/preview-match-count?${new URLSearchParams({ description, category })}`
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        resultEl.textContent = `Couldn't check: ${err.detail || res.statusText}`;
      } else {
        const { count } = await res.json();
        // eBay's search match is fuzzy, not a strict phrase match - even a
        // specific reference number can return hundreds of loosely-related
        // results. Treat this as a relative signal (broader description ->
        // bigger number, more ongoing Claude usage as new ones appear), not
        // a precise prediction of next-run cost.
        const veryBroad = count > 3000;
        resultEl.innerHTML = veryBroad
          ? `⚠️ ~${count.toLocaleString()} eBay results for this text - that's very broad and will mean a steady stream of new matches (and Claude calls) on every run. A model or reference number will narrow it a lot. (eBay's match is fuzzy, so this is a rough gauge, not an exact count.)`
          : `~${count.toLocaleString()} eBay results for this text (rough gauge - eBay's match is fuzzy, not exact).`;
        resultEl.className = veryBroad ? "preview-warning" : "preview-ok";
      }
    } catch (err) {
      resultEl.textContent = `Couldn't check: ${err}`;
    } finally {
      btn.disabled = false;
      btn.textContent = "Preview match count";
    }
  });

  document.getElementById("edit-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    const rawThreshold = form.get("discount_threshold").trim();
    const payload = {
      id: form.get("id").trim(),
      category: form.get("category"),
      description: form.get("description").trim(),
      discount_threshold: rawThreshold === "" ? null : Number(rawThreshold) / 100,
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
