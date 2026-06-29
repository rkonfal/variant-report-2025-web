async function loadReport() {
  const response = await fetch("./data/report.json");
  if (!response.ok) {
    throw new Error(`Failed to load report.json: ${response.status}`);
  }
  return response.json();
}

function formatInt(value) {
  return new Intl.NumberFormat("cs-CZ", { maximumFractionDigits: 0 }).format(value);
}

function formatPct(value) {
  return new Intl.NumberFormat("cs-CZ", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value) + " %";
}

function monthPeak(months) {
  return Object.entries(months)
    .sort((a, b) => b[1] - a[1])[0];
}

function renderSummary(summary) {
  const grid = document.querySelector("#summary-grid");
  const items = [
    ["Variantní kusy", formatInt(summary.variantUnits), summary.definitionShort || "Všechno prodané přesně v suffix formátu /dd."],
    ["Podíl na všech kusech", formatPct(summary.sharePct), "Jak velká část prodejů byla variantní SKU."],
    ["Aktivní variantní SKU", formatInt(summary.skuCount), "Počet SKU, která měla v roce 2025 prodej."],
    ["Základní produkty", formatInt(summary.baseCount), "Kolik základních kódů mělo aspoň jednu prodanou variantu."],
  ];

  grid.innerHTML = items.map(([label, value, foot]) => `
    <article class="stat-card">
      <div class="stat-label">${label}</div>
      <div class="stat-value">${value}</div>
      <div class="stat-foot">${foot}</div>
    </article>
  `).join("");
}

function renderMonths(months) {
  const max = Math.max(...months.map((row) => row.variantUnits));
  document.querySelector("#month-chart").innerHTML = months.map((row) => `
    <div class="bar-row">
      <div class="bar-label">${row.label}</div>
      <div class="bar-track">
        <div class="bar-fill" style="width:${(row.variantUnits / max) * 100}%"></div>
      </div>
      <div class="bar-value">${formatInt(row.variantUnits)}</div>
    </div>
  `).join("");

  document.querySelector("#months-body").innerHTML = months.map((row) => `
    <tr>
      <td><strong>${row.label}</strong></td>
      <td>${formatInt(row.variantUnits)}</td>
      <td>${formatInt(row.allUnits)}</td>
      <td>${formatPct(row.sharePct)}</td>
      <td>${formatInt(row.activeVariantSkus)}</td>
    </tr>
  `).join("");
}

function renderTopSkus(topSkus) {
  document.querySelector("#top-skus-body").innerHTML = topSkus.map((row) => `
    <tr>
      <td><strong>${row.sku}</strong></td>
      <td>${row.title || '<span class="muted">bez názvu</span>'}</td>
      <td>${formatInt(row.total)}</td>
    </tr>
  `).join("");
}

function renderInsights(report) {
  const sortedMonths = [...report.months].sort((a, b) => b.variantUnits - a.variantUnits);
  const topMonth = sortedMonths[0];
  const topSku = report.topSkus[0];
  const concentration = (topSku.total / report.summary.variantUnits) * 100;
  const topBase = [...report.baseProducts].sort((a, b) => b.total - a.total)[0];

  document.querySelector("#insights").innerHTML = `
    <article class="insight">
      <strong>Peak měsíc byl ${topMonth.label}</strong>
      <div>Prodalo se ${formatInt(topMonth.variantUnits)} variantních kusů, tedy ${formatPct(topMonth.sharePct)} ze všech kusů v měsíci.</div>
    </article>
    <article class="insight">
      <strong>Největší tahoun: ${topSku.sku}</strong>
      <div>${formatInt(topSku.total)} ks za rok 2025. To je ${formatPct(concentration)} všech variantních prodejů.</div>
    </article>
    <article class="insight">
      <strong>Nejsilnější základní produkt: ${topBase.baseSku}</strong>
      <div>${formatInt(topBase.total)} ks přes ${formatInt(topBase.variantSkuCount)} variantní SKU.</div>
    </article>
  `;
}

function renderBaseProducts(baseProducts) {
  document.querySelector("#base-products-body").innerHTML = baseProducts.map((row) => `
    <tr>
      <td><strong>${row.baseSku}</strong></td>
      <td>${row.variantSkus.map((sku) => `<span class="variant-pill">${sku}</span>`).join("")}</td>
      <td>${formatInt(row.variantSkuCount)}</td>
      <td>${formatInt(row.total)}</td>
    </tr>
  `).join("");
}

function renderSkuRows(skus, filter = "") {
  const needle = filter.trim().toLowerCase();
  const rows = skus.filter((row) => {
    if (!needle) return true;
    return row.sku.toLowerCase().includes(needle) || (row.title || "").toLowerCase().includes(needle);
  });

  document.querySelector("#all-skus-body").innerHTML = rows.map((row) => {
    const [peakMonth, peakValue] = monthPeak(row.months);
    return `
      <tr>
        <td><strong>${row.sku}</strong></td>
        <td>${row.title || '<span class="muted">bez názvu</span>'}</td>
        <td>${row.baseSku}</td>
        <td>${formatInt(row.total)}</td>
        <td>${peakMonth} / ${formatInt(peakValue)} ks</td>
      </tr>
    `;
  }).join("");
}

async function init() {
  try {
    const report = await loadReport();
    const sourceEl = document.querySelector("#source-note");
    if (sourceEl && report.source?.logic) {
      sourceEl.textContent = report.source.logic;
    }
    document.querySelector("#generated-at").textContent = `Generováno ${new Date(report.generatedAt).toLocaleString("cs-CZ")}`;
    renderSummary(report.summary);
    renderMonths(report.months);
    renderTopSkus(report.topSkus);
    renderInsights(report);
    renderBaseProducts(report.baseProducts);
    renderSkuRows(report.skus);

    document.querySelector("#sku-filter").addEventListener("input", (event) => {
      renderSkuRows(report.skus, event.target.value);
    });
  } catch (error) {
    document.body.innerHTML = `<main class="shell"><section class="panel"><h1>Report se nepodařilo načíst</h1><p>${error.message}</p></section></main>`;
  }
}

init();
