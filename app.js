let filter = "all";
let token = localStorage.getItem("pledgecity_token") || "";
let currentUser = null;
let threads = [];
let challenges = [];

const createForm = document.getElementById("create-form");
const challengeForm = document.getElementById("challenge-form");
const threadList = document.getElementById("thread-list");
const challengeList = document.getElementById("challenge-list");
const template = document.getElementById("thread-template");
const challengeTemplate = document.getElementById("challenge-template");
const globalStats = document.getElementById("global-stats");
const chips = Array.from(document.querySelectorAll(".chip"));
const authView = document.getElementById("auth-view");

function money(value) {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value || 0);
}

function dateTimeText(value) {
  if (!value) return "sem prazo";
  const date = new Date(value);
  return date.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

function badgeInfo(status) {
  if (status === "funded") return { text: "Meta batida", className: "badge-funded" };
  if (status === "committed_current") return { text: "Commit no valor atual", className: "badge-commit" };
  if (status === "expired") return { text: "Prazo expirado", className: "badge-expired" };
  return { text: "Aberta para pledges", className: "badge-open" };
}

function challengeBadge(status) {
  if (status === "accepted") return { text: "Aceito/Commit", className: "badge-funded" };
  if (status === "countered") return { text: "Counteroffer enviada", className: "badge-commit" };
  if (status === "rejected") return { text: "Recusado", className: "badge-expired" };
  return { text: "Pendente", className: "badge-open" };
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(path, {
    ...options,
    headers
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || "Erro da API");
  }
  return data;
}

function renderAuth() {
  if (currentUser) {
    authView.innerHTML = `
      <div class="auth-box">
        <p>Logado como <strong>@${currentUser.username}</strong></p>
        <button id="logout-btn" type="button">Sair</button>
      </div>
    `;
    document.getElementById("logout-btn").addEventListener("click", async () => {
      try {
        await api("/api/auth/logout", { method: "POST" });
      } catch {
        // ignore logout api errors
      }
      token = "";
      currentUser = null;
      localStorage.removeItem("pledgecity_token");
      await refreshAll();
    });
    return;
  }

  authView.innerHTML = `
    <form id="login-form">
      <label>
        Username
        <input type="text" name="username" required />
      </label>
      <label>
        Senha
        <input type="password" name="password" required />
      </label>
      <div class="auth-actions">
        <button type="submit">Entrar</button>
        <button type="button" id="register-btn">Criar conta</button>
      </div>
    </form>
  `;

  const loginForm = document.getElementById("login-form");
  const registerBtn = document.getElementById("register-btn");

  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(loginForm);
    const username = String(form.get("username")).trim();
    const password = String(form.get("password")).trim();

    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password })
      });
      token = data.token;
      localStorage.setItem("pledgecity_token", token);
      await refreshAll();
    } catch (error) {
      alert(error.message);
    }
  });

  registerBtn.addEventListener("click", async () => {
    const form = new FormData(loginForm);
    const username = String(form.get("username")).trim();
    const password = String(form.get("password")).trim();

    try {
      const data = await api("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({ username, password })
      });
      token = data.token;
      localStorage.setItem("pledgecity_token", token);
      await refreshAll();
    } catch (error) {
      alert(error.message);
    }
  });
}

function updateStats(items) {
  const totals = items.reduce(
    (acc, thread) => {
      acc.totalRaised += Number(thread.pledgedTotal || 0);
      acc.totalPledges += (thread.pledges || []).length;
      if (thread.status === "funded" || thread.status === "committed_current") acc.totalFunded += 1;
      return acc;
    },
    { totalRaised: 0, totalPledges: 0, totalFunded: 0 }
  );

  globalStats.innerHTML = `
    <ul>
      <li><span>Arrecadado na plataforma</span> <strong>${money(totals.totalRaised)}</strong></li>
      <li><span>Total de pledges</span> <strong>${totals.totalPledges}</strong></li>
      <li><span>Desafios committed</span> <strong>${totals.totalFunded}</strong></li>
    </ul>
  `;
}

function renderThreads() {
  const visible = threads.filter((thread) => (filter === "all" ? true : thread.status === filter));
  threadList.innerHTML = "";

  if (!visible.length) {
    threadList.innerHTML = `<p class="empty">Nenhuma thread para este filtro.</p>`;
    return;
  }

  visible.forEach((thread) => {
    const progress = Math.min(100, (Number(thread.pledgedTotal || 0) / Number(thread.targetAmount || 1)) * 100);

    const node = template.content.firstElementChild.cloneNode(true);
    node.querySelector(".thread-title").textContent = thread.title;
    node.querySelector(".thread-author").textContent = `@${thread.creatorUsername}`;
    node.querySelector(".thread-description").textContent = thread.description;
    node.querySelector(".thread-meta").textContent = `Meta ${money(Number(thread.targetAmount))} • Prazo ${dateTimeText(
      thread.deadlineAt
    )}`;

    const badge = node.querySelector(".badge");
    const info = badgeInfo(thread.status);
    badge.textContent = info.text;
    badge.classList.add(info.className);

    node.querySelector(".progress span").style.width = `${progress}%`;
    node.querySelector(".progress-text").textContent = `${money(Number(thread.pledgedTotal || 0))} de ${money(
      Number(thread.targetAmount)
    )} (${progress.toFixed(0)}%)`;

    const pledgeList = node.querySelector(".pledge-list");
    if (!thread.pledges.length) {
      pledgeList.innerHTML = "<li>Ainda sem apoios.</li>";
    } else {
      pledgeList.innerHTML = thread.pledges
        .map((pledge) => `<li>@${pledge.supporterUsername} apoiou com ${money(Number(pledge.amount))}</li>`)
        .join("");
    }

    const actions = node.querySelector(".thread-actions");
    if (thread.canCommitCurrent) {
      const commitBtn = document.createElement("button");
      commitBtn.type = "button";
      commitBtn.className = "secondary-btn";
      commitBtn.textContent = "Commit no valor atual";
      commitBtn.addEventListener("click", async () => {
        try {
          await api(`/api/threads/${thread.id}/commit-current`, { method: "POST" });
          await refreshAll();
        } catch (error) {
          alert(error.message);
        }
      });
      actions.appendChild(commitBtn);
    }

    if (thread.canDelete) {
      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "danger-btn";
      deleteBtn.textContent = "Apagar thread";
      deleteBtn.addEventListener("click", async () => {
        if (!confirm("Tem certeza que deseja apagar esta thread?")) return;
        try {
          await api(`/api/threads/${thread.id}`, { method: "DELETE" });
          await refreshAll();
        } catch (error) {
          alert(error.message);
        }
      });
      actions.appendChild(deleteBtn);
    }

    const pledgeForm = node.querySelector(".pledge-form");
    if (thread.status !== "open") {
      pledgeForm.innerHTML = `<p class="empty">Esta thread nao aceita novos pledges.</p>`;
    } else if (!currentUser) {
      pledgeForm.innerHTML = `<p class="empty">Faca login para enviar pledge.</p>`;
    } else {
      pledgeForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        const amount = Number(form.get("amount"));
        if (amount < 1) return;

        try {
          await api(`/api/threads/${thread.id}/pledges`, {
            method: "POST",
            body: JSON.stringify({ amount })
          });
          await refreshAll();
        } catch (error) {
          alert(error.message);
        }
      });
    }

    threadList.appendChild(node);
  });
}

function renderChallenges() {
  challengeList.innerHTML = "";

  if (!currentUser) {
    challengeList.innerHTML = `<p class="empty">Faca login para ver e responder desafios.</p>`;
    return;
  }

  if (!challenges.length) {
    challengeList.innerHTML = `<p class="empty">Nenhum desafio por enquanto.</p>`;
    return;
  }

  challenges.forEach((item) => {
    const node = challengeTemplate.content.firstElementChild.cloneNode(true);
    node.querySelector(".challenge-title").textContent = item.title;
    node.querySelector(".thread-description").textContent = item.description;
    node.querySelector(".thread-meta").textContent = `@${item.challengerUsername} -> @${item.challengedUsername} • Oferta ${money(
      item.offeredAmount
    )}${item.counterAmount > 0 ? ` • Counter ${money(item.counterAmount)}` : ""}`;

    const badge = node.querySelector(".badge");
    const info = challengeBadge(item.status);
    badge.textContent = info.text;
    badge.classList.add(info.className);

    const actions = node.querySelector(".thread-actions");

    if (item.canRespond && item.status === "pending") {
      const accept = document.createElement("button");
      accept.type = "button";
      accept.className = "secondary-btn";
      accept.textContent = "Commit";
      accept.onclick = async () => {
        await api(`/api/challenges/${item.id}/respond`, {
          method: "POST",
          body: JSON.stringify({ action: "accept" })
        });
        await refreshAll();
      };

      const reject = document.createElement("button");
      reject.type = "button";
      reject.className = "danger-btn";
      reject.textContent = "Recusar";
      reject.onclick = async () => {
        await api(`/api/challenges/${item.id}/respond`, {
          method: "POST",
          body: JSON.stringify({ action: "reject" })
        });
        await refreshAll();
      };

      const counter = document.createElement("button");
      counter.type = "button";
      counter.className = "secondary-btn";
      counter.textContent = "Counteroffer";
      counter.onclick = async () => {
        const raw = prompt("Digite o valor da counteroffer em R$");
        if (!raw) return;
        const value = Number(raw);
        if (value < 1) return alert("Valor invalido");

        await api(`/api/challenges/${item.id}/respond`, {
          method: "POST",
          body: JSON.stringify({ action: "counter", counterAmount: value })
        });
        await refreshAll();
      };

      actions.append(accept, reject, counter);
    }

    if (item.canRespond && item.status === "countered") {
      const acceptCounterAsChallenged = document.createElement("button");
      acceptCounterAsChallenged.type = "button";
      acceptCounterAsChallenged.className = "secondary-btn";
      acceptCounterAsChallenged.textContent = "Commit na counteroffer";
      acceptCounterAsChallenged.onclick = async () => {
        await api(`/api/challenges/${item.id}/respond`, {
          method: "POST",
          body: JSON.stringify({ action: "accept" })
        });
        await refreshAll();
      };
      actions.appendChild(acceptCounterAsChallenged);
    }

    if (item.canAcceptCounter) {
      const acceptCounter = document.createElement("button");
      acceptCounter.type = "button";
      acceptCounter.className = "secondary-btn";
      acceptCounter.textContent = "Aceitar counteroffer";
      acceptCounter.onclick = async () => {
        await api(`/api/challenges/${item.id}/accept-counter`, { method: "POST" });
        await refreshAll();
      };
      actions.appendChild(acceptCounter);
    }

    challengeList.appendChild(node);
  });
}

async function refreshAll() {
  try {
    if (token) {
      const me = await api("/api/auth/me");
      currentUser = me.user;
      if (!currentUser) {
        token = "";
        localStorage.removeItem("pledgecity_token");
      }
    } else {
      currentUser = null;
    }

    const threadData = await api("/api/threads", { headers: token ? {} : { Authorization: "" } });
    threads = threadData.threads || [];

    if (currentUser) {
      const challengeData = await api("/api/challenges");
      challenges = challengeData.challenges || [];
    } else {
      challenges = [];
    }

    renderAuth();
    updateStats(threads);
    renderThreads();
    renderChallenges();
  } catch (error) {
    renderAuth();
    threadList.innerHTML = `<p class="empty">Falha ao carregar: ${error.message}</p>`;
  }
}

createForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentUser) return alert("Faca login antes de criar thread.");

  const form = new FormData(event.currentTarget);
  const title = String(form.get("title")).trim();
  const description = String(form.get("description")).trim();
  const targetAmount = Number(form.get("targetAmount"));
  const deadlineDate = String(form.get("deadlineDate"));
  const deadlineHour = String(form.get("deadlineHour"));
  const localDeadline = new Date(`${deadlineDate}T${deadlineHour}`);
  const deadlineAt = localDeadline.toISOString();

  try {
    await api("/api/threads", {
      method: "POST",
      body: JSON.stringify({ title, description, targetAmount, deadlineDate, deadlineHour, deadlineAt })
    });
    createForm.reset();
    await refreshAll();
  } catch (error) {
    alert(error.message);
  }
});

challengeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentUser) return alert("Faca login antes de desafiar alguem.");

  const form = new FormData(event.currentTarget);
  const challengedUsername = String(form.get("challengedUsername")).trim();
  const title = String(form.get("title")).trim();
  const description = String(form.get("description")).trim();
  const offeredAmount = Number(form.get("offeredAmount"));

  try {
    await api("/api/challenges", {
      method: "POST",
      body: JSON.stringify({ challengedUsername, title, description, offeredAmount })
    });
    challengeForm.reset();
    await refreshAll();
  } catch (error) {
    alert(error.message);
  }
});

chips.forEach((chip) => {
  chip.addEventListener("click", () => {
    chips.forEach((item) => item.classList.remove("active"));
    chip.classList.add("active");
    filter = chip.dataset.filter;
    renderThreads();
  });
});

refreshAll();
