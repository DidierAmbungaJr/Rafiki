const messagesEl = document.querySelector("#messages");
const form = document.querySelector("#chatForm");
const input = document.querySelector("#messageInput");
const micBtn = document.querySelector("#micBtn");
const speakToggle = document.querySelector("#speakToggle");
const resetBtn = document.querySelector("#resetBtn");
const refreshStatusBtn = document.querySelector("#refreshStatusBtn");
const runtimeState = document.querySelector("#runtimeState");
const llmStatus = document.querySelector("#llmStatus");
const bodyStatus = document.querySelector("#bodyStatus");
const lastSource = document.querySelector("#lastSource");
const liveStatus = document.querySelector("#liveStatus");
const profileBox = document.querySelector("#profileBox");
const parentBox = document.querySelector("#parentBox");
const liveBodyToggle = document.querySelector("#liveBodyToggle");
const voiceRate = document.querySelector("#voiceRate");
const voiceRateValue = document.querySelector("#voiceRateValue");
const voicePitch = document.querySelector("#voicePitch");
const voicePitchValue = document.querySelector("#voicePitchValue");
const audioStatus = document.querySelector("#audioStatus");

let speakEnabled = true;
let busy = false;
let recognition = null;
let listening = false;
let audioDraft = "";
let audioSilenceTimer = null;
let manualStop = false;

function cleanOutput(text) {
  return String(text || "")
    .replace(/[\u{1F300}-\u{1FAFF}\u{2700}-\u{27BF}]/gu, "")
    .replace(/\[[^\]]*(TOOL|JSON|MCP)[^\]]*\]/gi, "")
    .replace(/\s+/g, " ")
    .trim();
}

function addMessage(role, text, pending = false) {
  const article = document.createElement("article");
  article.className = `message ${role}${pending ? " pending" : ""}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  article.appendChild(bubble);
  messagesEl.appendChild(article);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return article;
}

function setBusy(value) {
  busy = value;
  input.disabled = value;
  form.querySelector("button[type='submit']").disabled = value;
}

function speak(text) {
  if (!speakEnabled || !("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(cleanOutput(text));
  utterance.lang = "fr-FR";
  utterance.rate = Number(voiceRate.value);
  utterance.pitch = Number(voicePitch.value);
  window.speechSynthesis.speak(utterance);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "Erreur serveur");
  }
  return data;
}

async function sendMessage(message, inputMode = "text") {
  const trimmed = message.trim();
  if (!trimmed || busy) return;

  addMessage("user", cleanOutput(trimmed));
  input.value = "";
  input.style.height = "42px";
  const pending = addMessage("assistant", "Rafiki reflechit...", true);
  setBusy(true);

  try {
    const data = await fetchJson("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: trimmed,
        input_mode: inputMode,
        live_body: liveBodyToggle.checked,
      }),
    });
    pending.remove();
    const reply = cleanOutput(data.reply);
    addMessage("assistant", reply);
    lastSource.textContent = data.source || "llm";
    liveStatus.textContent = liveBodyToggle.checked ? "live" : "calme";
    runtimeState.textContent = data.source === "llm" ? "Reponse LLM" : "Action locale";
    speak(reply);
    refreshPanels();
  } catch (error) {
    pending.remove();
    addMessage("assistant", `Je n'ai pas pu repondre: ${error.message}`);
    runtimeState.textContent = "Erreur";
  } finally {
    setBusy(false);
    input.focus();
  }
}

async function sendBodyFeedback(action, text = "") {
  if (!liveBodyToggle.checked) return;
  try {
    await fetchJson("/api/body-feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, text }),
    });
  } catch {
    bodyStatus.textContent = "feedback limite";
  }
}

async function refreshStatus() {
  try {
    const data = await fetchJson("/api/status");
    llmStatus.textContent = data.systems?.status || "ok";
    const body = data.body || {};
    bodyStatus.textContent = body.status || (body.mqtt_connected ? "connecte" : "non detecte");
    runtimeState.textContent = "Pret";
  } catch (error) {
    llmStatus.textContent = "indisponible";
    bodyStatus.textContent = "inconnu";
    runtimeState.textContent = "Serveur a verifier";
  }
}

async function refreshProfile() {
  try {
    const data = await fetchJson("/api/profile");
    const profile = data.profile || {};
    const interests = Array.isArray(profile.interests) ? profile.interests.join(", ") : "";
    profileBox.textContent = `${profile.name || "enfant"}, ${profile.age || 7} ans, ${profile.language || "francais simple"}${interests ? ` - ${interests}` : ""}`;
  } catch {
    profileBox.textContent = "Profil indisponible.";
  }
}

async function refreshParentReport() {
  try {
    const data = await fetchJson("/api/parent-report");
    const events = data.events || [];
    if (!events.length) {
      parentBox.textContent = "Aucun evenement recent.";
      return;
    }
    parentBox.innerHTML = "";
    events.slice(0, 6).forEach((event) => {
      const item = document.createElement("div");
      item.className = "event";
      item.textContent = event.summary || "Evenement Rafiki";
      const meta = document.createElement("small");
      meta.textContent = `${event.event_type || "info"} - ${event.severity || "info"}`;
      item.appendChild(meta);
      parentBox.appendChild(item);
    });
  } catch {
    parentBox.textContent = "Journal parent indisponible.";
  }
}

function refreshPanels() {
  refreshStatus();
  refreshProfile();
  refreshParentReport();
}

function setupSpeechRecognition() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    micBtn.disabled = true;
    micBtn.title = "Micro non supporte par ce navigateur";
    return;
  }
  recognition = new Recognition();
  recognition.lang = "fr-FR";
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    listening = true;
    manualStop = false;
    micBtn.classList.add("listening");
    runtimeState.textContent = "J'ecoute...";
    audioStatus.textContent = "Ecoute en cours. Parle naturellement.";
    sendBodyFeedback("listening");
  };
  recognition.onend = () => {
    listening = false;
    micBtn.classList.remove("listening");
    if (!manualStop && !busy && audioDraft.trim()) {
      startSilenceCountdown(500);
    }
    if (!busy) runtimeState.textContent = "Pret";
  };
  recognition.onerror = (event) => {
    micBtn.classList.remove("listening");
    listening = false;
    runtimeState.textContent = "Micro a verifier";
    audioStatus.textContent = event.error ? `Micro: ${event.error}` : "Micro a verifier.";
  };
  recognition.onresult = (event) => {
    let finalText = "";
    let interimText = "";
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const transcript = event.results[index]?.[0]?.transcript || "";
      if (event.results[index].isFinal) finalText += transcript;
      else interimText += transcript;
    }
    if (finalText) {
      audioDraft = `${audioDraft} ${finalText}`.trim();
      startSilenceCountdown(1800);
    }
    const preview = `${audioDraft} ${interimText}`.trim();
    input.value = preview;
    input.dispatchEvent(new Event("input"));
  };
}

function startSilenceCountdown(delayMs) {
  clearTimeout(audioSilenceTimer);
  audioSilenceTimer = setTimeout(() => {
    const text = audioDraft.trim();
    audioDraft = "";
    if (text && !busy) sendMessage(text, "audio");
  }, delayMs);
}

function startListening() {
  if (!recognition || busy || listening) return;
  audioDraft = input.value.trim();
  clearTimeout(audioSilenceTimer);
  try {
    recognition.start();
  } catch {
    audioStatus.textContent = "Micro deja actif.";
  }
}

function stopListening(sendNow = true) {
  if (!recognition) return;
  manualStop = true;
  try {
    recognition.stop();
  } catch {
    // Le navigateur peut deja avoir arrete l'ecoute.
  }
  if (sendNow) startSilenceCountdown(120);
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage(input.value, "text");
});

input.addEventListener("input", () => {
  input.style.height = "42px";
  input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

micBtn.addEventListener("click", () => {
  if (listening) stopListening(true);
  else startListening();
});

speakToggle.addEventListener("click", () => {
  speakEnabled = !speakEnabled;
  speakToggle.classList.toggle("active", speakEnabled);
  if (!speakEnabled && "speechSynthesis" in window) window.speechSynthesis.cancel();
});

resetBtn.addEventListener("click", async () => {
  await fetchJson("/api/reset", { method: "POST" });
  messagesEl.innerHTML = "";
  addMessage("assistant", "Conversation remise a zero. Je suis pret.");
  refreshPanels();
});

refreshStatusBtn.addEventListener("click", refreshPanels);

voiceRate.addEventListener("input", () => {
  voiceRateValue.textContent = Number(voiceRate.value).toFixed(2);
});

voicePitch.addEventListener("input", () => {
  voicePitchValue.textContent = Number(voicePitch.value).toFixed(2);
});

liveBodyToggle.addEventListener("change", () => {
  liveStatus.textContent = liveBodyToggle.checked ? "live" : "calme";
  sendBodyFeedback(liveBodyToggle.checked ? "neutral" : "neutral");
});

setupSpeechRecognition();
refreshPanels();
input.focus();
