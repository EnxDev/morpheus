/**
 * HR Assistant — Chat UI logic.
 * Handles query submission, clarification loops, and pipeline visualization.
 */

const messagesEl = document.getElementById("messages");
const queryInput = document.getElementById("query-input");
const sendBtn = document.getElementById("send-btn");
const clarBar = document.getElementById("clarification-bar");
const clarText = document.getElementById("clarification-text");
const clarInput = document.getElementById("clarification-input");
const clarSend = document.getElementById("clarification-send");

// State for the clarification loop and confirmation
let pendingClarification = null; // { intent, field, originalQuery }
let pendingConfirmation = null;  // { intent, originalQuery }

// ── Send query ──────────────────────────────────────────────────────

sendBtn.addEventListener("click", () => sendQuery());
queryInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendQuery();
  }
});

// Preset buttons
document.querySelectorAll("button.preset").forEach((btn) => {
  btn.addEventListener("click", () => {
    const query = btn.dataset.query;
    queryInput.value = query;
    sendQuery();
  });
});

// Clarification send
clarSend.addEventListener("click", () => sendClarification());
clarInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    sendClarification();
  }
});

async function sendQuery() {
  const query = queryInput.value.trim();
  if (!query) return;

  addMessage(query, "user");
  queryInput.value = "";
  hideClarification();
  resetPipeline();
  setStep("parse", "active");

  const typing = showTyping();
  setLoading(true);

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    const data = await res.json();
    removeTyping(typing);
    handleResponse(data, query);
  } catch (err) {
    removeTyping(typing);
    addMessage("Connection error. Make sure the server is running.", "assistant blocked");
  } finally {
    setLoading(false);
  }
}

async function sendClarification() {
  if (!pendingClarification) return;
  const answer = clarInput.value.trim();
  if (!answer) return;

  // Save state before clearing (hideClarification nulls pendingClarification)
  const { originalQuery, intent, field } = pendingClarification;

  addMessage(answer, "user");
  clarInput.value = "";
  hideClarification();
  setStep("clarification", "active");

  const typing = showTyping();
  setLoading(true);

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: originalQuery,
        intent: intent,
        clarify_field: field,
        clarify_answer: answer,
      }),
    });
    const data = await res.json();
    removeTyping(typing);
    handleResponse(data, originalQuery);
  } catch (err) {
    removeTyping(typing);
    addMessage("Error during clarification.", "assistant blocked");
  } finally {
    setLoading(false);
  }
}

// ── Handle Morpheus response ────────────────────────────────────────

function handleResponse(data, originalQuery) {
  if (data.error || data.type === "error") {
    addMessage(data.message || data.error, "assistant blocked");
    return;
  }

  if (data.type === "conversational") {
    addMessage(data.message, "assistant");
    return;
  }

  if (data.type === "clarification") {
    setStep("confidence_check", "done");
    setStep("clarification", "active");

    let html = `<span class="badge clarify">Clarification needed</span>\n`;
    html += `<p>${escapeHtml(data.message)}</p>`;

    if (data.confidence_details) {
      html += renderConfidenceGrid(data.confidence_details);
    }

    addMessageHtml(html, "assistant clarification");

    pendingClarification = {
      intent: data.intent,
      field: data.field,
      originalQuery: originalQuery,
    };
    showClarification(data.message);
    return;
  }

  if (data.type === "confirmation") {
    completePipelineUntil("decision");
    setStep("decision", "active");

    let html = `<span class="badge confirm">Confirm intent</span>\n`;
    html += `<pre>${escapeHtml(data.message)}</pre>`;

    if (data.confidence_details) {
      html += renderConfidenceGrid(data.confidence_details);
    }

    html += `<div class="confirm-actions">`;
    html += `<button class="btn-reject" onclick="rejectIntent()">✗ Edit</button>`;
    html += `<button class="btn-confirm" onclick="confirmIntent()">✓ Proceed</button>`;
    html += `</div>`;

    addMessageHtml(html, "assistant confirmation");

    // Store pending confirmation with server-issued token
    pendingConfirmation = {
      intent: data.intent,
      originalQuery: originalQuery,
      confirmToken: data.confirm_token,
    };
    return;
  }

  if (data.type === "blocked") {
    completePipelineUntil("action_validation");
    setStep("action_validation", "blocked");

    let html = `<span class="badge blocked">BLOCKED — ${escapeHtml(data.risk_level)}</span>\n`;
    html += `<pre>${escapeHtml(data.message)}</pre>`;

    addMessageHtml(html, "assistant blocked");
    return;
  }

  if (data.type === "no_action") {
    completePipelineUntil("decision");
    addMessage(data.message, "assistant");
    return;
  }

  if (data.type === "result") {
    completePipelineUntil("executed");
    setStep("executed", "done");

    let html = `<span class="badge approved">✓ ${escapeHtml(data.action)}</span>`;
    if (data.score) {
      html += `<span class="badge score">score: ${data.score.toFixed(2)}</span>`;
    }
    html += `\n<pre>${escapeHtml(data.message)}</pre>`;

    addMessageHtml(html, "assistant");
    return;
  }

  addMessage(JSON.stringify(data, null, 2), "assistant");
}

// ── Confirmation actions ─────────────────────────────────

async function confirmIntent() {
  if (!pendingConfirmation) return;
  const { intent, originalQuery, confirmToken } = pendingConfirmation;
  pendingConfirmation = null;

  addMessage("✓ Confirmed — proceeding", "user");
  setStep("decision", "done");
  setStep("action_validation", "active");

  const typing = showTyping();
  setLoading(true);

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: originalQuery,
        intent: intent,
        confirmed: true,
        confirm_token: confirmToken,
      }),
    });
    const data = await res.json();
    removeTyping(typing);
    handleResponse(data, originalQuery);
  } catch (err) {
    removeTyping(typing);
    addMessage("Error during execution.", "assistant blocked");
  } finally {
    setLoading(false);
  }
}

function rejectIntent() {
  pendingConfirmation = null;
  addMessage("✗ Cancelled — please rephrase your request", "user");
  resetPipeline();
}

// ── Confidence grid ─────────────────────────────────────────────────

function renderConfidenceGrid(details) {
  let html = '<div class="confidence-grid">';
  for (const [field, info] of Object.entries(details)) {
    // Show 0% if value is null/empty — confidence on a null field is meaningless to the user
    const hasValue = info.value !== null && info.value !== undefined && info.value !== "" && info.value !== "—";
    const pct = hasValue ? Math.round((info.confidence || 0) * 100) : 0;
    const color = pct >= 80 ? "var(--green)" : pct >= 60 ? "var(--yellow)" : "var(--red)";
    // Use human-readable label from domain config, fall back to field name
    const displayName = info.label || field;
    html += `
      <div class="confidence-item">
        <span style="min-width:120px">${escapeHtml(displayName)}</span>
        <div class="confidence-bar">
          <div class="confidence-fill" style="width:${pct}%;background:${color}"></div>
        </div>
        <span style="min-width:35px;text-align:right">${pct}%</span>
      </div>`;
  }
  html += "</div>";
  return html;
}

// ── Pipeline visualization ──────────────────────────────────────────

function resetPipeline() {
  document.querySelectorAll("#pipeline-steps .step").forEach((el) => {
    el.classList.remove("active", "done", "blocked");
  });
}

function setStep(name, state) {
  const el = document.querySelector(`[data-step="${name}"]`);
  if (el) {
    el.classList.remove("active", "done", "blocked");
    el.classList.add(state);
  }
}

function completePipelineUntil(name) {
  const steps = ["parse", "confidence_check", "clarification", "decision", "action_validation", "executed"];
  for (const s of steps) {
    if (s === name) break;
    setStep(s, "done");
  }
}

// ── DOM helpers ─────────────────────────────────────────────────────

function addMessage(text, cls) {
  const div = document.createElement("div");
  div.className = `message ${cls}`;
  div.textContent = text;
  messagesEl.appendChild(div);
  scrollToBottom();
}

function addMessageHtml(html, cls) {
  const div = document.createElement("div");
  div.className = `message ${cls}`;
  div.innerHTML = html;
  messagesEl.appendChild(div);
  scrollToBottom();
}

function showTyping() {
  const div = document.createElement("div");
  div.className = "message assistant typing-indicator";
  div.innerHTML = "<span></span><span></span><span></span>";
  messagesEl.appendChild(div);
  scrollToBottom();
  return div;
}

function removeTyping(el) {
  if (el && el.parentNode) el.parentNode.removeChild(el);
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setLoading(on) {
  sendBtn.disabled = on;
  queryInput.disabled = on;
  clarSend.disabled = on;
  clarInput.disabled = on;
}

function showClarification(question) {
  clarText.textContent = "🟡 " + question;
  clarBar.classList.remove("hidden");
  // Disable main input while clarification is active
  queryInput.disabled = true;
  sendBtn.disabled = true;
  clarInput.disabled = false;
  clarSend.disabled = false;
  clarInput.focus();
}

function hideClarification() {
  clarBar.classList.add("hidden");
  pendingClarification = null;
  clarInput.value = "";
  // Re-enable main input
  queryInput.disabled = false;
  sendBtn.disabled = false;
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
