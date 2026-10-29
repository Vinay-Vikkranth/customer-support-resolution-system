"use strict";
let token = "",
  bootstrap = {},
  selected = null,
  activeIncident = false,
  cases = [],
  pendingDecision = null,
  noticeTimer;
const $ = (id) => document.getElementById(id);
function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function pretty(value) {
  return String(value).replaceAll("_", " ");
}
function message(text, error = false) {
  clearTimeout(noticeTimer);
  $("message").textContent = text;
  $("message").className = error ? "error" : "";
  $("message").hidden = false;
  noticeTimer = setTimeout(
    () => ($("message").hidden = true),
    error ? 12000 : 4500,
  );
}
async function request(path, method = "GET", body) {
  const response = await fetch("/api" + path, {
    method,
    headers: {
      Authorization: "Bearer " + token,
      "Content-Type": "application/json",
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (response.status === 401 && path != "/auth/login") {
    disconnect();
    throw Error("Your session has expired. Sign in again.");
  }
  return response;
}
async function api(path, method = "GET", body) {
  const response = await request(path, method, body);
  const data = await response.json();
  if (!response.ok)
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : "Please check the form fields and try again.",
    );
  return data;
}
async function task(button, fn) {
  button.disabled = true;
  try {
    await fn();
  } catch (error) {
    message(error.message, true);
  } finally {
    button.disabled = false;
  }
}
function action(label, fn, cls) {
  const button = el("button", label, cls);
  button.type = "button";
  button.onclick = () => task(button, fn);
  return button;
}
function badge(status) {
  return el("span", pretty(status), "tag " + status);
}
function renderCases() {
  const query = $("search").value.toLowerCase();
  const status = $("statusFilter").value;
  const filtered = cases.filter(
    (t) =>
      (!status || t.status === status) &&
      [t.title, t.body, t.account_id, String(t.id)].some((v) =>
        v.toLowerCase().includes(query),
      ),
  );
  $("caseCount").textContent = filtered.length;
  $("tickets").replaceChildren();
  if (!filtered.length)
    $("tickets").append(el("p", "No cases match your filters."));
  for (const t of filtered) {
    const button = el(
      "button",
      undefined,
      "ticket" + (selected === t.id ? " selected" : ""),
    );
    button.setAttribute("aria-pressed", String(selected === t.id));
    button.append(
      el(
        "small",
        "#" +
          String(t.id).padStart(4, "0") +
          " / " +
          t.account_id.toUpperCase(),
      ),
      el("strong", t.title),
    );
    const meta = el("div", undefined, "ticket-meta");
    meta.append(
      badge(t.status),
      el(
        "span",
        new Date(t.created * 1000).toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
        }),
        "ticket-date",
      ),
    );
    button.append(meta);
    button.onclick = () => task(button, () => show(t.id));
    $("tickets").append(button);
  }
}
async function refresh() {
  const [tickets, metrics] = await Promise.all([
    api("/tickets"),
    api("/metrics"),
  ]);
  cases = tickets;
  $("metrics").replaceChildren();
  for (const [key, label, note] of [
    ["tickets", "TOTAL CASES", "Across this workspace"],
    ["awaiting_review", "NEEDS REVIEW", "Waiting for human judgment"],
    ["resolved", "VERIFIED RESOLUTIONS", "Approved and checked"],
    ["mean_latency_ms", "INVESTIGATION · MS", "Average across recorded runs"],
  ]) {
    const box = el("div", undefined, "metric");
    box.append(
      el("small", label),
      el("strong", Number(metrics[key]).toLocaleString()),
      el("span", note, "metric-note"),
    );
    $("metrics").append(box);
  }
  renderCases();
}
function disclosure(title) {
  const node = el("details");
  node.append(el("summary", title));
  return node;
}
async function show(id) {
  selected = id;
  const data = await api("/tickets/" + id);
  if (selected !== id) return;
  const box = $("detail");
  box.replaceChildren();
  const heading = el("div", undefined, "detail-heading");
  heading.append(
    el("small", "CASE #" + String(id).padStart(4, "0"), "eyebrow"),
    badge(data.ticket.status),
  );
  box.append(
    heading,
    el("h2", data.ticket.title),
    el("p", data.ticket.body, "detail-body"),
  );
  const context = el("div", undefined, "context");
  for (const [label, value] of [
    ["Customer account", data.context.account.name],
    [
      "Plan / billing",
      data.context.account.plan + " / " + pretty(data.context.account.status),
    ],
    ["Verified member", data.context.member.name],
    [
      "Reporting permission",
      data.context.member.reporting ? "Enabled" : "Disabled",
    ],
  ]) {
    const item = el("div");
    item.append(el("small", label), el("strong", value));
    context.append(item);
  }
  box.append(context);
  const tools = el("div", undefined, "actions");
  if (!["resolved", "closed"].includes(data.ticket.status))
    tools.append(
      action("✦ Investigate case", async () => {
        message("Collecting evidence and analyzing the case…");
        await api("/tickets/" + id + "/investigate", "POST");
        await show(id);
        await operations();
        message("Investigation ready for review.");
      }),
    );
  if (bootstrap.role === "reviewer")
    tools.append(
      action(
        "Update status",
        () => {
          $("statusReason").value = "";
          $("statusDialog").showModal();
        },
        "secondary",
      ),
    );
  box.append(tools);
  const run = data.investigations[0];
  if (run) {
    const finding = el("div", undefined, "finding");
    finding.append(
      el(
        "div",
        "PROPOSED ACTION / " + pretty(run.action).toUpperCase(),
        "eyebrow",
      ),
      el("h3", run.reason),
      el(
        "small",
        pretty(run.model_status) +
          " · " +
          run.latency_ms +
          " ms · " +
          run.status,
      ),
    );
    box.append(finding);
    const trace = disclosure("Investigation trace · evidence and checks");
    for (const [i, step] of (Array.isArray(run.trace)
      ? run.trace
      : []
    ).entries()) {
      const row = el("div", undefined, "trace-row");
      const text = el("div");
      text.append(
        el("strong", step.tool + " · " + step.status),
        el("p", step.detail),
      );
      row.append(el("span", i + 1, "trace-number"), text);
      trace.append(row);
    }
    box.append(trace);
    const evidence = disclosure(
      "Supporting policies · " + run.evidence.length + " references",
    );
    for (const policy of run.evidence) {
      const node = el("div", undefined, "policy");
      node.append(
        el("strong", policy.id + " · " + policy.title),
        el("p", policy.text),
      );
      evidence.append(node);
    }
    box.append(evidence);
    const draft = el("div", undefined, "draft");
    draft.append(
      el("h3", "Customer reply draft"),
      el("p", run.draft),
      el(
        "small",
        "Review before sharing. This draft has not been sent.",
        "subtle",
      ),
      action(
        "Copy draft",
        async () => {
          await navigator.clipboard.writeText(run.draft);
          message("Draft copied. Review it before sending.");
        },
        "secondary",
      ),
    );
    box.append(draft);
    if (run.analysis?.next_steps?.length) {
      const steps = el("ol");
      for (const step of run.analysis.next_steps) steps.append(el("li", step));
      box.append(el("h3", "Recommended next steps"), steps);
    }
    if (["pending", "execution_unknown"].includes(run.status)) {
      if (bootstrap.role === "reviewer") {
        const actions = el("div", undefined, "actions");
        for (const choice of ["approve", "reject"])
          actions.append(
            action(
              choice === "approve"
                ? "Approve proposed action"
                : "Reject proposal",
              () => {
                pendingDecision = { runId: run.id, ticketId: id, choice };
                $("decisionTitle").textContent =
                  choice === "approve"
                    ? "Approve this proposal?"
                    : "Reject this proposal?";
                $("decisionDescription").textContent =
                  choice === "reject"
                    ? "The case will return to Open for further investigation."
                    : run.action === "restore_reporting"
                      ? "Reporting access will be restored for this sandbox member, then verified. The server rechecks account state before executing."
                      : "The case will be escalated for further review. No account permission will change.";
                $("decisionConfirm").textContent =
                  choice === "approve"
                    ? "Approve and execute"
                    : "Reject proposal";
                $("decisionDialog").showModal();
              },
              choice === "reject" ? "secondary" : "",
            ),
          );
        box.append(actions);
      } else
        box.append(el("p", "A reviewer must approve or reject this proposal."));
    }
  }
  const notes = disclosure("Case notes · " + data.notes.length);
  for (const note of data.notes) {
    const node = el("div", undefined, "note");
    node.append(
      el("p", note.body),
      el(
        "small",
        note.actor + " · " + new Date(note.created * 1000).toLocaleString(),
      ),
    );
    notes.append(node);
  }
  const form = el("form");
  const label = el("label", "Add an internal note");
  const input = el("textarea");
  input.required = true;
  input.maxLength = 5000;
  input.name = "note";
  label.append(input);
  const submit = el("button", "Save note");
  form.append(label, submit);
  form.onsubmit = async (event) => {
    event.preventDefault();
    await task(submit, async () => {
      await api("/tickets/" + id + "/notes", "POST", { body: input.value });
      await show(id);
      message("Note saved.");
    });
  };
  notes.append(form);
  box.append(notes);
  const history = disclosure(
    "Audit history · " + data.audit.length + " events",
  );
  for (const event of data.audit) {
    const node = el("div", undefined, "audit");
    node.append(
      el("strong", pretty(event.event)),
      el(
        "small",
        event.actor + " · " + new Date(event.created * 1000).toLocaleString(),
      ),
    );
    const details = JSON.parse(event.details);
    node.append(
      el(
        "div",
        Object.entries(details)
          .map(([k, v]) => pretty(k) + ": " + v)
          .join(" · "),
        "audit-details",
      ),
    );
    history.append(node);
  }
  box.append(history);
  await refresh();
}
async function connect() {
  bootstrap = await api("/bootstrap");
  $("token").value = "";
  $("password").value = "";
  $("login").hidden = true;
  $("workspace").hidden = false;
  $("role").textContent = bootstrap.name + " · " + pretty(bootstrap.role);
  $("aiMode").textContent = bootstrap.ai_enabled
    ? "AI analysis enabled · Policy enforced"
    : "Local policy analysis · No model charges";
  $("controls").hidden =
    bootstrap.role !== "reviewer" || bootstrap.remote_accounts;
  activeIncident = bootstrap.incident;
  renderIncident();
  $("policies").replaceChildren();
  for (const policy of bootstrap.policies) {
    const node = el("div", undefined, "policy");
    node.append(
      el("h3", policy.id + " · " + policy.title),
      el("p", policy.text),
    );
    $("policies").append(node);
  }
  for (const target of ["accountSelect", "importAccount"])
    $(target).replaceChildren(
      ...bootstrap.accounts.map((account) => {
        const option = el("option", account.name);
        option.value = account.id;
        return option;
      }),
    );
  members();
  importMembers();
  $("zendeskStatus").textContent = bootstrap.zendesk_configured
    ? "Configured"
    : "Not configured";
  $("modelStatus").textContent = bootstrap.ai_enabled
    ? "Configured"
    : "Local fallback active";
  $("importButton").disabled =
    !bootstrap.zendesk_configured || bootstrap.role !== "reviewer";
  await refresh();
  await operations();
  message("Workspace connected. Select a case to begin.");
}
$("loginForm").onsubmit = async (event) => {
  event.preventDefault();
  await task(event.submitter, async () => {
    token = $("token").value;
    await connect();
  });
};
$("userLoginForm").onsubmit = async (event) => {
  event.preventDefault();
  await task(event.submitter, async () => {
    const result = await api("/auth/login", "POST", {
      username: $("username").value,
      password: $("password").value,
    });
    token = result.token;
    await connect();
  });
};
function disconnect() {
  token = "";
  bootstrap = {};
  selected = null;
  cases = [];
  $("workspace").hidden = true;
  $("login").hidden = false;
  $("detail").replaceChildren();
  $("tickets").replaceChildren();
  $("operationContent").replaceChildren();
}
$("logout").onclick = () =>
  task($("logout"), async () => {
    await api("/auth/logout", "POST");
    disconnect();
    message("Signed out.");
  });
function populateMembers(account, select) {
  $(select).replaceChildren(
    ...bootstrap.members
      .filter((member) => member.account_id === $(account).value)
      .map((member) => {
        const option = el("option", member.name);
        option.value = member.id;
        return option;
      }),
  );
}
function members() {
  populateMembers("accountSelect", "memberSelect");
}
function importMembers() {
  populateMembers("importAccount", "importMember");
}
$("accountSelect").onchange = members;
$("importAccount").onchange = importMembers;
$("search").oninput = renderCases;
$("statusFilter").onchange = renderCases;
$("newTicket").onclick = () => $("createDialog").showModal();
$("cancel").onclick = () => $("createDialog").close();
$("createForm").onsubmit = async (event) => {
  event.preventDefault();
  await task(event.submitter, async () => {
    const ticket = await api(
      "/tickets",
      "POST",
      Object.fromEntries(new FormData(event.target)),
    );
    event.target.reset();
    members();
    $("createDialog").close();
    $("search").value = "";
    $("statusFilter").value = "";
    await show(ticket.id);
    message("Case created.");
  });
};
$("decisionCancel").onclick = () => $("decisionDialog").close();
$("decisionForm").onsubmit = async (event) => {
  event.preventDefault();
  await task(event.submitter, async () => {
    const decision = pendingDecision;
    const result = await api(
      "/investigations/" + decision.runId + "/decision",
      "POST",
      { decision: decision.choice },
    );
    $("decisionDialog").close();
    await show(decision.ticketId);
    await operations();
    message("Decision saved: " + pretty(result.ticket_status || result.status));
  });
};
$("statusCancel").onclick = () => $("statusDialog").close();
$("statusForm").onsubmit = async (event) => {
  event.preventDefault();
  await task(event.submitter, async () => {
    await api("/tickets/" + selected, "PATCH", {
      status: $("newStatus").value,
      reason: $("statusReason").value,
    });
    $("statusDialog").close();
    await show(selected);
    message("Case status updated.");
  });
};
function renderIncident() {
  $("incidentState").textContent = activeIncident
    ? " Reporting incident ACTIVE"
    : " All services healthy";
}
$("incident").onclick = () =>
  task($("incident"), async () => {
    await api("/sandbox/incident", "POST", { active: !activeIncident });
    activeIncident = !activeIncident;
    renderIncident();
    await operations();
    message("Sandbox service status updated.");
  });
$("export").onclick = () =>
  task($("export"), async () => {
    const response = await request("/export");
    if (!response.ok) throw Error("Export failed.");
    const url = URL.createObjectURL(await response.blob());
    const link = el("a");
    link.href = url;
    link.download = "resolvedesk-cases.csv";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    message("Case export downloaded.");
  });
$("importButton").onclick = () => $("importDialog").showModal();
$("importCancel").onclick = () => $("importDialog").close();
$("importForm").onsubmit = async (event) => {
  event.preventDefault();
  await task(event.submitter, async () => {
    const value = Object.fromEntries(new FormData(event.target));
    value.ticket_id = Number(value.ticket_id);
    const result = await api("/integrations/zendesk/import", "POST", value);
    $("importDialog").close();
    await show(result.id);
    message(
      result.replayed
        ? "This ticket was already imported."
        : "Zendesk ticket imported.",
    );
  });
};
async function operations() {
  if (bootstrap.role !== "reviewer") return;
  const data = await api("/operations");
  $("operationSummary").textContent =
    `${data.usage.input_tokens.toLocaleString()} input tokens · ${data.usage.output_tokens.toLocaleString()} output tokens. ${data.cost_note}`;
  const box = $("operationContent");
  box.replaceChildren();
  for (const mode of data.modes)
    box.append(
      el(
        "p",
        pretty(mode.model_status) + " · " + mode.count + " investigations",
      ),
    );
  const audit = disclosure(
    "Workspace activity · latest " + data.events.length + " events",
  );
  for (const event of data.events) {
    const node = el("div", undefined, "audit");
    node.append(
      el(
        "strong",
        pretty(event.event) +
          (event.ticket_id ? " · Case #" + event.ticket_id : ""),
      ),
      el(
        "small",
        event.actor + " · " + new Date(event.created * 1000).toLocaleString(),
      ),
    );
    audit.append(node);
  }
  box.append(audit);
}
for (const link of document.querySelectorAll(".nav-link"))
  link.addEventListener("click", () => {
    document
      .querySelectorAll(".nav-link")
      .forEach((node) => node.classList.remove("active"));
    link.classList.add("active");
  });
