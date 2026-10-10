
let currentPage = "scan";
let status = {};
let opportunities = [];
let trades = [];

async function getData(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[char]);
}

async function refreshDashboard() {
  try {
    status = await getData("/api/status");

    const balance = Number(status.balance_sol);
    document.getElementById("balance").textContent =
      Number.isFinite(balance) ? balance.toFixed(3) + " SOL" : "-- SOL";

    document.getElementById("mode").textContent =
      status.paper_mode ? "PAPER" : "LIVE";

    document.getElementById("positions").textContent =
      (status.open_positions || []).length;
  } catch (error) {
    console.error("Status error:", error);
  }

  try {
    opportunities = await getData("/api/opportunities");
  } catch (error) {
    console.error("Opportunities error:", error);
  }

  try {
    trades = await getData("/api/trades");
  } catch (error) {
    console.error("Trades error:", error);
  }

  render();
}

function render() {
  const content = document.getElementById("content");

  if (currentPage === "scan") {
    content.innerHTML = '<div class="grid">' +
      opportunities.map(item => {
        const token = item.token || {};
        const entry = item.entry || {};
        const fast = item.fast || {};
        const score = Number(entry.combined_score || fast.score || 0);

        return `
          <div class="card">
            <h3>$${escapeHtml(token.symbol || "?")}
              <span class="score">${Math.round(score)}</span>
            </h3>
            <p class="muted">
              ${escapeHtml(token.name || "")} ·
              ${escapeHtml(fast.provider || "pending")} ·
              ${escapeHtml((item.route || {}).route || "—")}
            </p>
            <p>
              Liquidity: $${Number(token.liquidity_usd || 0).toLocaleString()}
            </p>
          </div>
        `;
      }).join("") + "</div>";

  } else if (currentPage === "positions") {
    content.innerHTML = `
      <div class="card">
        <h2>Open Positions</h2>
        <pre>${escapeHtml(JSON.stringify(status.open_positions || [], null, 2))}</pre>
      </div>
    `;

  } else if (currentPage === "agents") {
    content.innerHTML = `
      <div class="card">
        <h2>AI Agents</h2>
        <pre>${escapeHtml(JSON.stringify(status.agents || {}, null, 2))}</pre>
      </div>
    `;

  } else if (currentPage === "routes") {
    content.innerHTML = `
      <div class="card">
        <h2>Execution Routes</h2>
        <p>Pump Direct → PumpSwap → Jupiter fallback</p>
        <p class="muted">Live trading is not enabled.</p>
      </div>
    `;

  } else if (currentPage === "history") {
    content.innerHTML = `
      <div class="card">
        <h2>Trade History</h2>
        <pre>${escapeHtml(JSON.stringify(trades, null, 2))}</pre>
      </div>
    `;
  }
}

document.querySelectorAll("nav button").forEach(button => {
  button.addEventListener("click", () => {
    currentPage = button.dataset.v;
    render();
  });
});

refreshDashboard();
setInterval(refreshDashboard, 5000);
