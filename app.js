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

function monthlyAverage(months) {
  const values = Object.values(months);
  if (!values.length) return 0;
  const total = values.reduce((sum, value) => sum + value, 0);
  return total / values.length;
}

function renderYearTabs(report, activeYear, onChange) {
  const tabs = document.querySelector("#year-tabs");
  tabs.innerHTML = report.availableYears.map((year) => `
    <button class="year-tab${year === activeYear ? " is-active" : ""}" type="button" data-year="${year}">
      ${year}
    </button>
  `).join("");

  tabs.querySelectorAll("[data-year]").forEach((button) => {
    button.addEventListener("click", () => onChange(Number(button.dataset.year)));
  });
}

function renderSummary(summary, year) {
  const grid = document.querySelector("#summary-grid");
  const items = [
    ["Variantní kusy", formatInt(summary.variantUnits), summary.definitionShort || "Všechno prodané přesně v suffix formátu /dd."],
    ["Podíl na všech kusech", formatPct(summary.sharePct), "Jak velká část prodejů byla variantní SKU."],
    ["Aktivní variantní SKU", formatInt(summary.skuCount), `Počet SKU, která měla v roce ${year} prodej.`],
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
  const max = Math.max(1, ...months.map((row) => row.variantUnits));
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

function renderInsights(yearReport) {
  const sortedMonths = [...yearReport.months].sort((a, b) => b.variantUnits - a.variantUnits);
  const topMonth = sortedMonths[0];
  const topSku = yearReport.topSkus[0];
  const concentration = yearReport.summary.variantUnits
    ? (topSku.total / yearReport.summary.variantUnits) * 100
    : 0;
  const topBase = [...yearReport.baseProducts].sort((a, b) => b.total - a.total)[0];

  document.querySelector("#insights").innerHTML = `
    <article class="insight">
      <strong>Peak měsíc byl ${topMonth.label}</strong>
      <div>Prodalo se ${formatInt(topMonth.variantUnits)} variantních kusů, tedy ${formatPct(topMonth.sharePct)} ze všech kusů v měsíci.</div>
    </article>
    <article class="insight">
      <strong>Největší tahoun: ${topSku.sku}</strong>
      <div>${formatInt(topSku.total)} ks za rok ${yearReport.year}. To je ${formatPct(concentration)} všech variantních prodejů.</div>
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
    const averageValue = monthlyAverage(row.months);
    return `
      <tr>
        <td><strong>${row.sku}</strong></td>
        <td>${row.title || '<span class="muted">bez názvu</span>'}</td>
        <td>${row.baseSku}</td>
        <td>${formatInt(row.total)}</td>
        <td>${formatInt(averageValue)} ks</td>
      </tr>
    `;
  }).join("");
}

function updateYearLabels(year) {
  document.querySelector("#current-year-chip").textContent = String(year);
  document.querySelector("#top-skus-total-label").textContent = String(year);
  document.querySelector("#base-products-total-label").textContent = String(year);
  document.querySelector("#all-skus-total-label").textContent = String(year);
}

function renderYear(report, activeYear) {
  const yearReport = report.annual.find((item) => item.year === activeYear) || report.annual[0];
  const filterValue = document.querySelector("#sku-filter").value;

  updateYearLabels(yearReport.year);
  renderSummary(yearReport.summary, yearReport.year);
  renderMonths(yearReport.months);
  renderTopSkus(yearReport.topSkus);
  renderInsights(yearReport);
  renderBaseProducts(yearReport.baseProducts);
  renderSkuRows(yearReport.skus, filterValue);
}

async function init() {
  try {
    const report = await loadReport();
    const sourceEl = document.querySelector("#source-note");
    let activeYear = report.defaultYear || report.availableYears?.[0];

    if (sourceEl && report.source?.logic) {
      sourceEl.textContent = report.source.logic;
    }
    document.querySelector("#generated-at").textContent = `Generováno ${new Date(report.generatedAt).toLocaleString("cs-CZ")}`;

    const render = () => {
      renderYearTabs(report, activeYear, (nextYear) => {
        activeYear = nextYear;
        render();
      });
      renderYear(report, activeYear);
    };

    document.querySelector("#sku-filter").addEventListener("input", () => {
      renderYear(report, activeYear);
    });

    render();
  } catch (error) {
    document.body.innerHTML = `<main class="shell"><section class="panel"><h1>Report se nepodařilo načíst</h1><p>${error.message}</p></section></main>`;
  }
}

init();
