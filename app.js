let filter = "all";
let cache = [];

const createForm = document.getElementById("create-form");
const threadList = document.getElementById("thread-list");
const template = document.getElementById("thread-template");
const globalStats = document.getElementById("global-stats");
const chips = Array.from(document.querySelectorAll(".chip"));

function money(value) {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value);
}

function toDateText(value) {
  if (!value) return "sem prazo";
  const date = new Date(`${value}T00:00:00`);
  return date.toLocaleDateString("pt-BR");
}

function getPledgedTotal(thread) {
  return thread.pledges.reduce((acc, pledge) => acc + Number(pledge.amount || 0), 0);
}

function getStatus(thread) {
  if (thread.status) return thread.status;

  const total = getPledgedTotal(thread);
  const isFunded = total >= Number(thread.targetAmount);
  const deadlineTs = new Date(`${thread.deadline}T23:59:59`).getTime();
  const isExpired = Date.now() > deadlineTs;

  if (isFunded) return "funded";
  if (isExpired) return "expired";
  return "open";
}

function badgeInfo(status) {
  if (status === "funded") return { text: "Meta batida: comprometido", className: "badge-funded" };
  if (status === "expired") return { text: "Prazo expirado", className: "badge-expired" };
  return { text: "Aberta para pledges", className: "badge-open" };
}

function updateStats(threads) {
  const totals = threads.reduce(
    (acc, thread) => {
      const pledged = getPledgedTotal(thread);
      const status = getStatus(thread);
      acc.totalRaised += pledged;
      acc.totalPledges += thread.pledges.length;
      if (status === "funded") acc.totalFunded += 1;
      return acc;
    },
    { totalRaised: 0, totalPledges: 0, totalFunded: 0 }
  );

  globalStats.innerHTML = `
    <ul>
      <li><span>Arrecadado na plataforma</span> <strong>${money(totals.totalRaised)}</strong></li>
      <li><span>Total de pledges</span> <strong>${totals.totalPledges}</strong></li>
      <li><span>Desafios com meta batida</span> <strong>${totals.totalFunded}</strong></li>
    </ul>
  `;
}

function sortThreads(threads) {
  return [...threads].sort((a, b) => b.createdAt - a.createdAt);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json"
    },
    ...options
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || "Erro inesperado da API");
  }

  return data;
}

async function loadThreads() {
  const data = await api("/api/threads");
  cache = data.threads || [];
}

function render() {
  const sorted = sortThreads(cache);
  updateStats(cache);

  const visible = sorted.filter((thread) => (filter === "all" ? true : getStatus(thread) === filter));

  threadList.innerHTML = "";

  if (!visible.length) {
    threadList.innerHTML = `<p class="empty">Nenhuma thread para este filtro.</p>`;
    return;
  }

  visible.forEach((thread) => {
    const status = getStatus(thread);
    const pledged = getPledgedTotal(thread);
    const progress = Math.min(100, (pledged / Number(thread.targetAmount)) * 100);

    const node = template.content.firstElementChild.cloneNode(true);
    node.querySelector(".thread-title").textContent = thread.title;
    node.querySelector(".thread-description").textContent = thread.description;
    node.querySelector(".thread-meta").textContent = `Criado por ${thread.creatorName} • Meta ${money(
      Number(thread.targetAmount)
    )} • Prazo ${toDateText(thread.deadline)}`;

    const badge = node.querySelector(".badge");
    const info = badgeInfo(status);
    badge.textContent = info.text;
    badge.classList.add(info.className);

    node.querySelector(".progress span").style.width = `${progress}%`;
    node.querySelector(".progress-text").textContent = `${money(pledged)} de ${money(
      Number(thread.targetAmount)
    )} (${progress.toFixed(0)}%)`;

    const pledgeList = node.querySelector(".pledge-list");
    if (!thread.pledges.length) {
      pledgeList.innerHTML = "<li>Ainda sem apoios.</li>";
    } else {
      pledgeList.innerHTML = thread.pledges
        .sort((a, b) => b.createdAt - a.createdAt)
        .map((pledge) => `<li>${pledge.supporterName} apoiou com ${money(Number(pledge.amount))}</li>`)
        .join("");
    }

    const pledgeForm = node.querySelector(".pledge-form");
    if (status !== "open") {
      pledgeForm.innerHTML = `<p class="empty">Este desafio nao aceita novos pledges.</p>`;
    } else {
      pledgeForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        const supporterName = String(form.get("supporterName")).trim();
        const amount = Number(form.get("amount"));

        if (!supporterName || amount < 1) return;

        try {
          await api(`/api/threads/${thread.id}/pledges`, {
            method: "POST",
            body: JSON.stringify({ supporterName, amount })
          });
          await refresh();
        } catch (error) {
          alert(error.message);
        }
      });
    }

    threadList.appendChild(node);
  });
}

async function refresh() {
  try {
    await loadThreads();
    render();
  } catch (error) {
    threadList.innerHTML = `<p class="empty">Falha ao carregar dados: ${error.message}</p>`;
  }
}

createForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const creatorName = String(form.get("creatorName")).trim();
  const title = String(form.get("title")).trim();
  const description = String(form.get("description")).trim();
  const targetAmount = Number(form.get("targetAmount"));
  const deadline = String(form.get("deadline"));

  if (!creatorName || !title || !description || targetAmount < 1 || !deadline) return;

  try {
    await api("/api/threads", {
      method: "POST",
      body: JSON.stringify({ creatorName, title, description, targetAmount, deadline })
    });
    createForm.reset();
    await refresh();
  } catch (error) {
    alert(error.message);
  }
});

chips.forEach((chip) => {
  chip.addEventListener("click", () => {
    chips.forEach((item) => item.classList.remove("active"));
    chip.classList.add("active");
    filter = chip.dataset.filter;
    render();
  });
});

refresh();
