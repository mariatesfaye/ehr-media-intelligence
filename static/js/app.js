const searchInput = document.getElementById("searchInput");
const searchBtn = document.getElementById("searchBtn");
const resourceFilter = document.getElementById("resourceFilter");
const dateFrom = document.getElementById("dateFrom");
const dateTo = document.getElementById("dateTo");
const statusLine = document.getElementById("statusLine");
const resultsList = document.getElementById("resultsList");
const emptyState = document.getElementById("emptyState");
const loadingState = document.getElementById("loadingState");
const errorState = document.getElementById("errorState");
const drawer = document.getElementById("drawer");
const drawerBackdrop = document.getElementById("drawerBackdrop");
const drawerContent = document.getElementById("drawerContent");
const closeDrawer = document.getElementById("closeDrawer");
const drawerTitle = document.getElementById("drawerTitle");

let debounceTimer = null;
let lastFocusedCard = null;

function badgeClass(resourceType) {
  const map = {
    DocumentReference: "bg-indigo-100 text-indigo-900",
    DiagnosticReport: "bg-emerald-100 text-emerald-900",
    Summary: "bg-amber-100 text-amber-900",
  };
  return map[resourceType] || "bg-slate-100 text-slate-800";
}

function setLoading(loading) {
  searchBtn.disabled = loading;
  loadingState.classList.toggle("hidden", !loading);
  if (loading) statusLine.textContent = "";
}

function showError(message) {
  errorState.textContent = message;
  errorState.classList.remove("hidden");
}

function clearStates() {
  errorState.classList.add("hidden");
  emptyState.classList.add("hidden");
  resultsList.innerHTML = "";
}

async function runSearch() {
  const query = searchInput.value.trim();
  if (!query) {
    statusLine.textContent = "Enter a search query.";
    return;
  }

  clearStates();
  setLoading(true);

  const payload = { query, limit: 5 };
  if (resourceFilter.value) payload.resource_types = [resourceFilter.value];
  if (dateFrom.value) payload.date_from = dateFrom.value;
  if (dateTo.value) payload.date_to = dateTo.value;

  try {
    const response = await fetch("/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`Search failed (${response.status})`);
    const data = await response.json();
    renderResults(data);
    statusLine.textContent = `${data.results.length} result(s) in ${data.took_ms} ms`;
  } catch (err) {
    showError("Unable to search. Ensure the API is running and the index is built (ehr-index).");
    emptyState.classList.remove("hidden");
  } finally {
    setLoading(false);
  }
}

function renderResults(data) {
  if (!data.results.length) {
    emptyState.classList.remove("hidden");
    return;
  }

  data.results.forEach((hit, index) => {
    const card = document.createElement("article");
    card.className =
      "result-card bg-white border border-slate-200 rounded-xl p-4 shadow-sm hover:border-blue-300 cursor-pointer";
    card.setAttribute("role", "listitem");
    card.tabIndex = 0;
    card.setAttribute("aria-label", `Result ${index + 1}: ${hit.patient_name}`);

    const scorePct = (hit.relevance_score * 100).toFixed(1);
    card.innerHTML = `
      <div class="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 class="font-semibold text-slate-900">${escapeHtml(hit.patient_name)}</h3>
          <p class="text-sm text-slate-600">MRN: ${escapeHtml(hit.mrn)}</p>
        </div>
        <span class="text-xs font-medium px-2 py-1 rounded-full ${badgeClass(hit.resource_type)}">${escapeHtml(hit.resource_type)}</span>
      </div>
      <dl class="mt-2 text-sm text-slate-600 flex flex-wrap gap-x-4 gap-y-1">
        <div><dt class="inline">Date: </dt><dd class="inline">${escapeHtml(hit.record_date || "n/a")}</dd></div>
        <div><dt class="inline">Match: </dt><dd class="inline">${scorePct}%</dd></div>
        <div><dt class="inline">Record: </dt><dd class="inline">${escapeHtml(hit.title || "—")}</dd></div>
      </dl>
      <p class="mt-3 text-sm text-slate-800 leading-relaxed">${escapeHtml(hit.summary_snippet || hit.snippet)}</p>
    `;

    card.addEventListener("click", () => openDrawer(hit));
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openDrawer(hit);
      }
    });

    resultsList.appendChild(card);
  });
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function openDrawer(hit) {
  lastFocusedCard = document.activeElement;
  drawerTitle.textContent = hit.patient_name;
  drawerContent.innerHTML = `<p class="text-slate-500">Loading patient details…</p>`;
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  drawerBackdrop.classList.remove("hidden");
  closeDrawer.focus();

  const id = encodeURIComponent(hit.patient_id);
  try {
    const [summaryRes, resourcesRes] = await Promise.all([
      fetch(`/patients/${id}/summary`),
      fetch(`/patients/${id}/resources`),
    ]);
    if (!summaryRes.ok || !resourcesRes.ok) throw new Error("Not found");
    const { summary } = await summaryRes.json();
    const { resources } = await resourcesRes.json();

    const mediaHtml = (summary.recent_media || [])
      .map(
        (m) => `
        <li class="border rounded-lg p-3">
          <span class="font-medium capitalize">${escapeHtml(m.type)}</span>
          <span class="text-slate-500"> · ${escapeHtml(m.date)}</span>
          <p class="mt-1 text-slate-700">${escapeHtml(m.summary)}</p>
        </li>`
      )
      .join("");

    const resourcesHtml = resources
      .map(
        (r) => `
        <li class="border rounded-lg p-3">
          <p class="font-medium">${escapeHtml(r.title)}</p>
          <p class="text-xs text-slate-500 mt-1">${escapeHtml(r.resource_type)} · ${escapeHtml(r.date || "n/a")}</p>
        </li>`
      )
      .join("");

    const anomalies = summary.flagged_anomalies?.length
      ? `<ul class="list-disc pl-5 mt-1 space-y-1">${summary.flagged_anomalies.map((a) => `<li>${escapeHtml(a)}</li>`).join("")}</ul>`
      : '<p class="text-slate-500">None flagged in source records.</p>';

    drawerContent.innerHTML = `
      <section aria-labelledby="aiSummaryHeading">
        <h3 id="aiSummaryHeading" class="font-semibold text-base mb-2">AI clinical summary</h3>
        <p class="mb-2"><span class="font-medium text-slate-700">Chief concern:</span> ${escapeHtml(summary.chief_concern)}</p>
        <p class="mb-3 leading-relaxed whitespace-pre-wrap">${escapeHtml(summary.narrative)}</p>
        <p class="text-xs text-slate-600 mb-1">Confidence: ${escapeHtml(summary.confidence)}</p>
        <p class="text-xs text-amber-900 bg-amber-50 border border-amber-200 rounded p-2">${escapeHtml(summary.disclaimer)}</p>
      </section>
      <section class="mt-5" aria-labelledby="anomaliesHeading">
        <h3 id="anomaliesHeading" class="font-semibold text-base mb-1">Flagged anomalies</h3>
        ${anomalies}
      </section>
      <section class="mt-5" aria-labelledby="mediaHeading">
        <h3 id="mediaHeading" class="font-semibold text-base mb-2">Recent media (summary)</h3>
        <ul class="space-y-2" role="list">${mediaHtml || '<li class="text-slate-500">No items</li>'}</ul>
      </section>
      <section class="mt-5" aria-labelledby="fhirHeading">
        <h3 id="fhirHeading" class="font-semibold text-base mb-2">Linked FHIR resources</h3>
        <ul class="space-y-2" role="list">${resourcesHtml || '<li class="text-slate-500">No resources</li>'}</ul>
      </section>
    `;
  } catch (err) {
    drawerContent.innerHTML = `<p class="text-red-700">Could not load patient details.</p>`;
  }
}

function closeDrawerPanel() {
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  drawerBackdrop.classList.add("hidden");
  if (lastFocusedCard && typeof lastFocusedCard.focus === "function") {
    lastFocusedCard.focus();
  } else {
    searchInput.focus();
  }
}

searchBtn.addEventListener("click", runSearch);
searchInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") runSearch();
});
searchInput.addEventListener("input", () => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(runSearch, 350);
});
resourceFilter.addEventListener("change", runSearch);
dateFrom.addEventListener("change", runSearch);
dateTo.addEventListener("change", runSearch);
closeDrawer.addEventListener("click", closeDrawerPanel);
drawerBackdrop.addEventListener("click", closeDrawerPanel);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && drawer.classList.contains("open")) closeDrawerPanel();
});