let token = localStorage.getItem("pledgecity_token") || "";
let me = null;
let threads = [];
let reverseRequests = [];
let balance = { owes: 0, toReceive: 0, entries: [] };

const authView = document.getElementById("auth-view");
const balanceView = document.getElementById("balance-view");
const statsView = document.getElementById("global-stats");
const threadList = document.getElementById("thread-list");
const reverseList = document.getElementById("reverse-list");
const threadTpl = document.getElementById("thread-item-template");
const reverseTpl = document.getElementById("reverse-item-template");
const threadForm = document.getElementById("thread-form");
const reverseForm = document.getElementById("reverse-form");

function money(value) {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(Number(value || 0));
}

function dtText(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "America/Sao_Paulo"
  });
}

function relDate(ms) {
  return new Date(Number(ms || 0)).toLocaleString("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "America/Sao_Paulo"
  });
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Erro na API");
  return data;
}

function renderAuth() {
  if (me) {
    authView.innerHTML = `
      <div class="auth-box">
        <p>Logado como <strong>@${me.username}</strong>${me.isAdmin ? " (admin)" : ""}</p>
        <button id="logout-btn" type="button">Sair</button>
      </div>
    `;
    document.getElementById("logout-btn").onclick = async () => {
      try {
        await api("/api/auth/logout", { method: "POST" });
      } catch {
        // ignore
      }
      token = "";
      localStorage.removeItem("pledgecity_token");
      await refresh();
    };
    return;
  }

  authView.innerHTML = `
    <form id="auth-form" class="stack">
      <label>Username<input type="text" name="username" required /></label>
      <label>Senha<input type="password" name="password" required /></label>
      <div class="grid-2">
        <button type="submit">Entrar</button>
        <button id="register-btn" type="button">Criar conta</button>
      </div>
    </form>
  `;

  const authForm = document.getElementById("auth-form");
  authForm.onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(authForm);
    const payload = {
      username: String(fd.get("username") || "").trim().toLowerCase(),
      password: String(fd.get("password") || "").trim()
    };
    try {
      const out = await api("/api/auth/login", { method: "POST", body: JSON.stringify(payload) });
      token = out.token;
      localStorage.setItem("pledgecity_token", token);
      await refresh();
    } catch (err) {
      alert(err.message);
    }
  };

  document.getElementById("register-btn").onclick = async () => {
    const fd = new FormData(authForm);
    const payload = {
      username: String(fd.get("username") || "").trim().toLowerCase(),
      password: String(fd.get("password") || "").trim()
    };
    try {
      const out = await api("/api/auth/register", { method: "POST", body: JSON.stringify(payload) });
      token = out.token;
      localStorage.setItem("pledgecity_token", token);
      await refresh();
    } catch (err) {
      alert(err.message);
    }
  };
}

function renderStats() {
  const raisedA = threads.reduce((acc, t) => acc + Number(t.pledgedTotal || 0), 0);
  const raisedB = reverseRequests.reduce((acc, r) => acc + Number(r.pledgedTotal || 0), 0);
  const totalPledges =
    threads.reduce((acc, t) => acc + (t.pledges?.length || 0), 0) +
    reverseRequests.reduce((acc, r) => acc + (r.pledges?.length || 0), 0);

  statsView.innerHTML = `
    <ul>
      <li><span>Total pledged</span><strong>${money(raisedA + raisedB)}</strong></li>
      <li><span>Total de pledges</span><strong>${totalPledges}</strong></li>
      <li><span>Meu saldo a receber</span><strong>${money(balance.toReceive)}</strong></li>
    </ul>
  `;
}

function renderBalance() {
  if (!me) {
    balanceView.innerHTML = `<p class="empty">Faca login para ver seu saldo.</p>`;
    return;
  }

  const rows = (balance.entries || [])
    .map((entry) => {
      const action = entry.canDeclareReceived
        ? `<button class="secondary-btn" data-receive="${entry.id}" type="button">Declarar recebido</button>`
        : "";
      return `<li><strong>${money(entry.amount)}</strong> | ${entry.payerUsername} -> ${entry.payeeUsername} | ${entry.dealType} | ${entry.status} ${action}</li>`;
    })
    .join("");

  balanceView.innerHTML = `
    <div class="auth-box">
      <p>Voce deve: <strong>${money(balance.owes)}</strong></p>
      <p>Voce recebe: <strong>${money(balance.toReceive)}</strong></p>
    </div>
    <ul class="list">${rows || "<li>Nenhum item de saldo.</li>"}</ul>
  `;

  balanceView.querySelectorAll("button[data-receive]").forEach((btn) => {
    btn.onclick = async () => {
      try {
        await api(`/api/balance/${btn.dataset.receive}/declare-received`, { method: "POST" });
        await refresh();
      } catch (err) {
        alert(err.message);
      }
    };
  });
}

function threadBadge(status) {
  if (status === "funded") return ["Meta batida", "badge-funded"];
  if (status === "committed_current") return ["Commit parcial", "badge-commit"];
  if (status === "expired") return ["Prazo expirado", "badge-expired"];
  return ["Aberta", "badge-open"];
}

function reverseBadge(status) {
  return status === "closed" ? ["Fechado", "badge-funded"] : ["Aberto", "badge-open"];
}

function renderThreads() {
  threadList.innerHTML = "";
  if (!threads.length) {
    threadList.innerHTML = `<p class="empty">Sem missoes ainda.</p>`;
    return;
  }

  threads.forEach((item) => {
    const node = threadTpl.content.firstElementChild.cloneNode(true);
    const [badgeText, badgeClass] = threadBadge(item.status);
    const progress = Math.min(100, (Number(item.pledgedTotal || 0) / Number(item.targetAmount || 1)) * 100);

    node.querySelector(".title").textContent = item.title;
    node.querySelector(".badge").textContent = badgeText;
    node.querySelector(".badge").classList.add(badgeClass);
    node.querySelector(".author").textContent = `@${item.creatorUsername}`;
    node.querySelector(".desc").textContent = item.description;
    node.querySelector(".meta").textContent = `Meta ${money(item.targetAmount)} | Prazo ${dtText(item.deadlineAt)}`;

    node.querySelector(".progress span").style.width = `${progress}%`;
    node.querySelector(".progress-text").textContent = `${money(item.pledgedTotal)} de ${money(item.targetAmount)} (${progress.toFixed(
      0
    )}%)`;

    node.querySelector(".list").innerHTML =
      item.pledges.map((p) => `<li>@${p.supporterUsername} pledged ${money(p.amount)} em ${relDate(p.createdAt)}</li>`).join("") ||
      "<li>Sem pledges.</li>";

    const commentList = node.querySelector(".comment-list");
    commentList.innerHTML =
      (item.comments || [])
        .map((c) => `<li>@${c.username}: ${c.body} <span class="meta">(${relDate(c.createdAt)})</span></li>`)
        .join("") || "<li>Sem comentarios.</li>";

    const commentForm = node.querySelector(".comment-form");
    if (!me) {
      commentForm.replaceWith(document.createElement("div"));
    } else {
      commentForm.onsubmit = async (e) => {
        e.preventDefault();
        const fd = new FormData(commentForm);
        const body = String(fd.get("body") || "").trim();
        if (!body) return;
        try {
          await api(`/api/threads/${item.id}/comments`, { method: "POST", body: JSON.stringify({ body }) });
          commentForm.reset();
          await refresh();
        } catch (err) {
          alert(err.message);
        }
      };
    }

    const actions = node.querySelector(".actions");
    if (item.canCommitCurrent) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "secondary-btn";
      btn.textContent = "Commit no valor atual";
      btn.onclick = async () => {
        try {
          await api(`/api/threads/${item.id}/commit-current`, { method: "POST" });
          await refresh();
        } catch (err) {
          alert(err.message);
        }
      };
      actions.appendChild(btn);
    }

    if (item.canDelete) {
      const del = document.createElement("button");
      del.type = "button";
      del.className = "danger-btn";
      del.textContent = "Apagar thread";
      del.onclick = async () => {
        if (!confirm("Apagar thread?")) return;
        try {
          await api(`/api/threads/${item.id}`, { method: "DELETE" });
          await refresh();
        } catch (err) {
          alert(err.message);
        }
      };
      actions.appendChild(del);
    }

    const pledgeForm = node.querySelector(".pledge-form");
    if (!me || item.status !== "open") {
      pledgeForm.replaceWith(document.createElement("div"));
    } else {
      pledgeForm.onsubmit = async (e) => {
        e.preventDefault();
        const fd = new FormData(pledgeForm);
        const amount = Number(fd.get("amount") || 0);
        try {
          await api(`/api/threads/${item.id}/pledges`, { method: "POST", body: JSON.stringify({ amount }) });
          pledgeForm.reset();
          await refresh();
        } catch (err) {
          alert(err.message);
        }
      };
    }

    threadList.appendChild(node);
  });
}

function renderReverse() {
  reverseList.innerHTML = "";
  if (!reverseRequests.length) {
    reverseList.innerHTML = `<p class="empty">Sem pedidos ainda.</p>`;
    return;
  }

  reverseRequests.forEach((item) => {
    const node = reverseTpl.content.firstElementChild.cloneNode(true);
    const [badgeText, badgeClass] = reverseBadge(item.status);

    node.querySelector(".title").textContent = item.title;
    node.querySelector(".badge").textContent = badgeText;
    node.querySelector(".badge").classList.add(badgeClass);
    node.querySelector(".author").textContent = `Criado por @${item.creatorUsername}`;
    node.querySelector(".desc").textContent = item.description;
    node.querySelector(".meta").textContent = "Pedido aberto para a comunidade";

    const low = item.lowestBid;
    node.querySelector(".progress-text").textContent = `Menor oferta atual: ${
      low ? `@${low.bidderUsername} por ${money(low.askAmount)}` : "sem ofertas"
    } | Pledged: ${money(item.pledgedTotal)}`;

    node.querySelector(".bids").innerHTML =
      item.bids.map((b) => `<li>@${b.bidderUsername} faria por ${money(b.askAmount)}</li>`).join("") ||
      "<li>Sem ofertas.</li>";
    node.querySelector(".pledges").innerHTML =
      item.pledges.map((p) => `<li>@${p.supporterUsername} pledged ${money(p.amount)}</li>`).join("") ||
      "<li>Sem pledges.</li>";

    const commentList = node.querySelector(".comment-list");
    commentList.innerHTML =
      (item.comments || [])
        .map((c) => `<li>@${c.username}: ${c.body} <span class="meta">(${relDate(c.createdAt)})</span></li>`)
        .join("") || "<li>Sem comentarios.</li>";

    const commentForm = node.querySelector(".comment-form");
    if (!me) {
      commentForm.replaceWith(document.createElement("div"));
    } else {
      commentForm.onsubmit = async (e) => {
        e.preventDefault();
        const fd = new FormData(commentForm);
        const body = String(fd.get("body") || "").trim();
        if (!body) return;
        try {
          await api(`/api/reverse/${item.id}/comments`, { method: "POST", body: JSON.stringify({ body }) });
          commentForm.reset();
          await refresh();
        } catch (err) {
          alert(err.message);
        }
      };
    }

    const bidForm = node.querySelector(".bid-form");
    const pledgeForm = node.querySelectorAll(".pledge-form")[0];

    if (!me || item.status !== "open") {
      bidForm.replaceWith(document.createElement("div"));
    } else {
      bidForm.onsubmit = async (e) => {
        e.preventDefault();
        const fd = new FormData(bidForm);
        const askAmount = Number(fd.get("askAmount") || 0);
        try {
          await api(`/api/reverse/${item.id}/bids`, { method: "POST", body: JSON.stringify({ askAmount }) });
          await refresh();
        } catch (err) {
          alert(err.message);
        }
      };
    }

    if (!me || item.status !== "open") {
      pledgeForm.replaceWith(document.createElement("div"));
    } else {
      pledgeForm.onsubmit = async (e) => {
        e.preventDefault();
        const fd = new FormData(pledgeForm);
        const amount = Number(fd.get("amount") || 0);
        try {
          await api(`/api/reverse/${item.id}/pledges`, { method: "POST", body: JSON.stringify({ amount }) });
          await refresh();
        } catch (err) {
          alert(err.message);
        }
      };
    }

    reverseList.appendChild(node);
  });
}

async function refresh() {
  try {
    if (token) {
      const m = await api("/api/auth/me");
      me = m.user;
      if (!me) {
        token = "";
        localStorage.removeItem("pledgecity_token");
      }
    } else {
      me = null;
    }

    if (me) {
      const [t, r, b] = await Promise.all([api("/api/threads"), api("/api/reverse"), api("/api/balance")]);
      threads = t.threads || [];
      reverseRequests = r.requests || [];
      balance = b;
    } else {
      const [t, r] = await Promise.all([api("/api/threads"), api("/api/reverse")]);
      threads = t.threads || [];
      reverseRequests = r.requests || [];
      balance = { owes: 0, toReceive: 0, entries: [] };
    }

    renderAuth();
    renderBalance();
    renderThreads();
    renderReverse();
    renderStats();
  } catch (err) {
    renderAuth();
    statsView.innerHTML = `<ul><li><span>Erro</span><strong>${err.message}</strong></li></ul>`;
  }
}

threadForm.onsubmit = async (e) => {
  e.preventDefault();
  if (!me) return alert("Faca login antes.");
  const fd = new FormData(threadForm);
  const payload = {
    title: String(fd.get("title") || "").trim(),
    description: String(fd.get("description") || "").trim(),
    targetAmount: Number(fd.get("targetAmount") || 0),
    deadlineDate: String(fd.get("deadlineDate") || ""),
    deadlineHour: String(fd.get("deadlineHour") || "")
  };

  try {
    await api("/api/threads", { method: "POST", body: JSON.stringify(payload) });
    threadForm.reset();
    await refresh();
  } catch (err) {
    alert(err.message);
  }
};

reverseForm.onsubmit = async (e) => {
  e.preventDefault();
  if (!me) return alert("Faca login antes.");
  const fd = new FormData(reverseForm);
  const payload = {
    title: String(fd.get("title") || "").trim(),
    description: String(fd.get("description") || "").trim(),
    seedAmount: Number(fd.get("seedAmount") || 0)
  };

  try {
    await api("/api/reverse", { method: "POST", body: JSON.stringify(payload) });
    reverseForm.reset();
    await refresh();
  } catch (err) {
    alert(err.message);
  }
};

document.querySelectorAll(".tab").forEach((tab) => {
  tab.onclick = () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");

    const id = tab.dataset.tab;
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.add("hidden"));
    document.getElementById(`tab-${id}`).classList.remove("hidden");
  };
});

refresh();
