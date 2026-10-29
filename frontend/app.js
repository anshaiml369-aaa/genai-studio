/* =========================================================
   Kalpana · GenAI Studio — front-end logic (vanilla JS)
   Sections: helpers · router · home effects · chat · studio · gallery
   ========================================================= */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
let STATUS = null;

function toast(text, type = "info") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = text;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), 5000);
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res;
}
const postJSON = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function escapeHTML(text) {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function renderMarkdown(text) {
  if (window.marked && window.DOMPurify) return DOMPurify.sanitize(marked.parse(text));
  return escapeHTML(text).replace(/\n/g, "<br>");
}
const icon = (name) => `<svg class="ic"><use href="#i-${name}"/></svg>`;
const fmtTime = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/* ---------------- Status (which APIs are switched on) ---------------- */
async function loadStatus() {
  try {
    STATUS = await (await api("/api/status")).json();
  } catch { toast("Could not reach the server.", "error"); return; }

  const pills = [
    ["Chat", STATUS.chat], ["Voice", !!STATUS.voice_in], ["Images", STATUS.image.length > 0],
    ["Video", true], ["Kling", STATUS.video.includes("Kling")],
  ];
  $("#hero-status").innerHTML = pills.map(([name, on]) =>
    `<span class="status-pill ${on ? "" : "off"}"><i></i>${name}</span>`).join("");

  $("#engine-list").innerHTML = `
    <div>brain <b>${STATUS.models.chat}</b></div>
    <div>ears <b>${STATUS.voice_in || "off"}</b></div>
    <div>images <b>${STATUS.image.join(" → ") || "off"}</b></div>
    <div>video <b>${STATUS.video.join(" → ")}</b></div>`;

  for (const sel of ["#voice", "#vo-voice"]) {
    $(sel).innerHTML = STATUS.voices.map((v) => `<option value="${v}">${v[0].toUpperCase() + v.slice(1)}</option>`).join("");
  }
  restoreSettings();
  if (!STATUS.video.includes("Kling")) $('[data-engine="kling"]').classList.add("disabled");
  updateCost();
}

/* ---------------- Router (#home, #chat, #studio, #gallery) ---------------- */
const VIEWS = ["home", "chat", "studio", "gallery"];
function route() {
  const name = VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "home";
  for (const v of VIEWS) $(`#view-${v}`).hidden = v !== name;
  $$(".nav-links a, .tabbar a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === `#${name}`));
  window.scrollTo(0, 0);
  if (name === "gallery") loadGallery();
  if (name === "studio") loadRecent();
  if (name === "chat") setTimeout(() => $("#input").focus(), 50);
}
window.addEventListener("hashchange", route);

/* =========================================================
   HOME EFFECTS
   ========================================================= */
function setupReveal() {
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
  }, { threshold: 0.15 });
  $$(".reveal").forEach((el, i) => { el.style.transitionDelay = `${(i % 4) * 80}ms`; io.observe(el); });

  // Animated counters
  const counters = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      const el = e.target, target = +el.dataset.count, start = performance.now();
      const tick = (now) => {
        const p = Math.min((now - start) / 1400, 1);
        el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3)));
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
      counters.unobserve(el);
    }
  });
  $$("[data-count]").forEach((el) => counters.observe(el));
}

function setupTypewriter() {
  const prompts = [
    "a paper boat sailing down a rainy Mumbai street",
    "an astronaut cat floating between neon planets",
    "a lighthouse guiding a ship through a storm",
    "Diwali lamps glowing on an old haveli rooftop",
  ];
  const stages = ["Writing the story", "Directing scene 1", "Directing scene 2", "Recording narrator", "Final cut"];
  const out = $("#typewriter"), bar = $("#demo-bar"), pct = $("#demo-pct"), stage = $("#demo-stage");
  let i = 0;
  async function loop() {
    const text = prompts[i++ % prompts.length];
    out.textContent = "";
    for (const ch of text) { out.textContent += ch; await new Promise((r) => setTimeout(r, reduceMotion ? 0 : 38)); }
    for (let p = 0; p <= 100; p += 2) {
      bar.style.width = `${p}%`; pct.textContent = `${p}%`;
      stage.textContent = stages[Math.min(Math.floor(p / 21), stages.length - 1)];
      await new Promise((r) => setTimeout(r, 45));
    }
    await new Promise((r) => setTimeout(r, 1400));
    loop();
  }
  loop();
}

function setupPointerEffects() {
  // Spotlight that follows the mouse on cards
  document.addEventListener("pointermove", (e) => {
    const card = e.target.closest?.(".spot");
    if (!card) return;
    const r = card.getBoundingClientRect();
    card.style.setProperty("--mx", `${e.clientX - r.left}px`);
    card.style.setProperty("--my", `${e.clientY - r.top}px`);
  });

  // Custom cursor: dot follows instantly, ring follows smoothly
  if (!matchMedia("(hover: hover) and (pointer: fine)").matches || reduceMotion) return;
  document.body.classList.add("has-cursor");
  const cursor = $(".cursor"), dot = $(".cursor-dot"), ring = $(".cursor-ring");
  let x = innerWidth / 2, y = innerHeight / 2, rx = x, ry = y;
  document.addEventListener("pointermove", (e) => {
    x = e.clientX; y = e.clientY;
    dot.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%)`;
    cursor.classList.toggle("hover", !!e.target.closest?.("a, button, label, select, input, textarea, video, .tile"));
  });
  (function follow() {
    rx += (x - rx) * 0.18; ry += (y - ry) * 0.18;
    ring.style.transform = `translate(${rx}px, ${ry}px) translate(-50%, -50%)`;
    requestAnimationFrame(follow);
  })();
}

/* =========================================================
   CHAT
   ========================================================= */
const STORE_KEY = "kalpana-chats-v1";
let chats = [];                 // [{id, title, messages: [{role, text, images, media, notices}]}]
let current = null;             // the open chat
let attachments = [];           // data URLs waiting to be sent
let streaming = null;           // AbortController while a reply is streaming
let audioPlayer = null;

function loadChats() {
  try { chats = JSON.parse(localStorage.getItem(STORE_KEY)) || []; } catch { chats = []; }
}
function saveChats() {
  // Uploaded photos are big, so we don't keep them in browser storage
  const slim = chats.slice(0, 30).map((c) => ({
    ...c, messages: c.messages.map((m) => ({ ...m, images: m.images?.length ? [] : undefined, hadImages: m.hadImages || !!m.images?.length })),
  }));
  try { localStorage.setItem(STORE_KEY, JSON.stringify(slim)); } catch {}
}
function restoreSettings() {
  try {
    const s = JSON.parse(localStorage.getItem("kalpana-settings")) || {};
    if (s.personality) $("#personality").value = s.personality;
    if (s.voice) { $("#voice").value = s.voice; $("#vo-voice").value = s.voice; }
    if (s.autospeak !== undefined) $("#autospeak").checked = s.autospeak;
  } catch {}
}
function saveSettings() {
  try {
    localStorage.setItem("kalpana-settings", JSON.stringify({
      personality: $("#personality").value, voice: $("#voice").value, autospeak: $("#autospeak").checked }));
  } catch {}
}

function newChat() {
  current = { id: Date.now().toString(36), title: "New chat", messages: [] };
  renderChat();
  renderConvList();
  $("#input").focus();
}
function openChat(id) {
  current = chats.find((c) => c.id === id);
  renderChat();
  renderConvList();
  $("#sidebar").classList.remove("open");
}
function renderConvList() {
  $("#conv-list").innerHTML = chats.map((c) => `
    <li class="${current && c.id === current.id ? "active" : ""}" data-id="${c.id}">
      ${icon("chat")}<span>${escapeHTML(c.title)}</span>
      <button class="icon-btn" data-del="${c.id}" title="Delete">${icon("trash")}</button></li>`).join("")
    || `<li class="muted" style="cursor:default">No chats yet</li>`;
}

function setGreeting() {
  const h = new Date().getHours();
  $("#greeting").innerHTML = h < 12 ? "Good <em>morning.</em>" : h < 17 ? "Good <em>afternoon.</em>" : "Good <em>evening.</em>";
}

function renderChat() {
  const box = $("#messages");
  $$(".msg", box).forEach((m) => m.remove());
  $("#chat-empty").hidden = current.messages.length > 0;
  for (const msg of current.messages) box.append(messageEl(msg));
  box.scrollTop = box.scrollHeight;
}

function messageEl(msg) {
  const el = document.createElement("div");
  el.className = `msg ${msg.role}`;
  if (msg.role === "user") {
    const imgs = (msg.images || []).map((src) => `<img src="${src}" alt="attached image">`).join("");
    const note = msg.hadImages && !msg.images?.length ? `<div class="mono muted">${icon("image")} image attached</div>` : "";
    el.innerHTML = `<div class="bubble">${imgs}${note}${msg.voice ? `<div class="mono muted">${icon("mic")} spoken</div>` : ""}${escapeHTML(msg.text || "").replace(/\n/g, "<br>")}</div>`;
    return el;
  }
  el.innerHTML = `<div class="avatar"></div><div class="msg-body"><div class="md"></div><div class="extras"></div>
    <div class="msg-actions">
      <button class="icon-btn" data-act="speak" title="Read aloud">${icon("volume")}</button>
      <button class="icon-btn" data-act="copy" title="Copy">${icon("copy")}</button></div></div>`;
  el._msg = msg;
  $(".md", el).innerHTML = renderMarkdown(msg.text || "");
  for (const n of msg.notices || []) addNotice(el, n);
  for (const m of msg.media || []) addMedia(el, m);
  return el;
}

function addMedia(el, m) {
  const card = document.createElement("div");
  card.className = "media-card";
  const view = m.type === "image"
    ? `<img src="${m.url}" alt="${escapeHTML(m.prompt || "generated image")}" loading="lazy">`
    : `<video src="${m.url}" controls playsinline loop></video>`;
  const animate = m.type === "image" ? `<button class="icon-btn" data-animate title="Animate this image">${icon("video")}</button>` : "";
  card.innerHTML = `${view}<div class="media-meta"><span class="mono muted">${m.type === "image" ? icon("image") : icon("video")}
    <span class="badge">${escapeHTML(m.engine || "")}</span></span>
    <span>${animate}<a class="icon-btn" href="${m.url}" download title="Download">${icon("download")}</a></span></div>`;
  $(".extras", el).append(card);
}
function addNotice(el, text, cls = "notice") {
  const n = document.createElement("div");
  n.className = cls;
  n.textContent = text;
  $(".extras", el).append(n);
}

/* ----- Sending a message and reading the streamed reply ----- */
async function sendMessage(text, { voice = false } = {}) {
  text = text.trim();
  if ((!text && !attachments.length) || streaming) return;
  if (!current) newChat();
  if (!chats.includes(current)) chats.unshift(current);
  if (current.title === "New chat") current.title = (text || "Image chat").slice(0, 42);

  const userMsg = { role: "user", text, images: [...attachments], voice };
  current.messages.push(userMsg);
  attachments = []; renderAttachments();
  $("#input").value = ""; autosize();
  $("#chat-empty").hidden = true;
  const box = $("#messages");
  box.append(messageEl(userMsg));

  const reply = { role: "assistant", text: "", media: [], notices: [] };
  const el = messageEl(reply);
  el.classList.add("thinking");
  $(".md", el).innerHTML = `<span class="typing"><i></i><i></i><i></i></span>`;
  box.append(el);
  box.scrollTop = box.scrollHeight;
  renderConvList();

  streaming = new AbortController();
  setSendMode(true);
  let statusEl = null;
  try {
    const history = current.messages.map(({ role, text, images, media }) => ({ role, text, images: images || [], media: media || [] }));
    const res = await api("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" }, signal: streaming.signal,
      body: JSON.stringify({ history, personality: $("#personality").value }),
    });
    const reader = res.body.getReader(), decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop();
      for (const part of parts) {
        if (!part.startsWith("data: ")) continue;
        const ev = JSON.parse(part.slice(6));
        if (ev.type === "text") {
          reply.text += ev.delta;
          $(".md", el).innerHTML = renderMarkdown(reply.text);
        } else if (ev.type === "status") {
          if (!statusEl) {
            statusEl = document.createElement("div");
            statusEl.className = "status-line";
            statusEl.innerHTML = `<span class="label-text"></span><div class="bar"><span></span></div>`;
            $(".extras", el).append(statusEl);
          }
          const secs = (statusEl._t = (statusEl._t || 0) + 1);
          $(".label-text", statusEl).textContent = `${ev.text}… ${ev.progress ? ev.progress + "%" : ""}  · ${fmtTime(secs)}`;
          $(".bar", statusEl).classList.toggle("indeterminate", !ev.progress);
          $(".bar span", statusEl).style.width = `${ev.progress || 0}%`;
        } else if (ev.type === "image" || ev.type === "video") {
          statusEl?.remove(); statusEl = null;
          const m = { type: ev.type, url: ev.url, prompt: ev.prompt, engine: ev.engine };
          reply.media.push(m); addMedia(el, m);
        } else if (ev.type === "notice") {
          reply.notices.push(ev.text); addNotice(el, ev.text);
        } else if (ev.type === "error") {
          statusEl?.remove(); statusEl = null;
          addNotice(el, ev.text, "error-line");
        }
        box.scrollTop = box.scrollHeight;
      }
    }
  } catch (err) {
    if (err.name !== "AbortError") addNotice(el, `Something went wrong: ${err.message}`, "error-line");
  } finally {
    statusEl?.remove();
    el.classList.remove("thinking");
    if (!reply.text) $(".md", el).innerHTML = $(".extras", el).children.length ? "" : `<span class="muted">(stopped)</span>`;
    current.messages.push(reply);
    streaming = null;
    setSendMode(false);
    saveChats();
    if ($("#autospeak").checked && reply.text) speakMessage(el);
  }
}

function setSendMode(isStreaming) {
  const btn = $("#send-btn");
  btn.classList.toggle("stop", isStreaming);
  btn.innerHTML = icon(isStreaming ? "stop" : "send");
  btn.setAttribute("aria-label", isStreaming ? "Stop" : "Send");
}

async function speakMessage(el) {
  const btn = $('[data-act="speak"]', el);
  if (audioPlayer && !audioPlayer.paused && audioPlayer._el === el) {   // tap again = stop
    audioPlayer.pause(); btn.classList.remove("playing"); return;
  }
  audioPlayer?.pause();
  $$(".icon-btn.playing").forEach((b) => b.classList.remove("playing"));
  try {
    btn.classList.add("playing");
    if (!el._audioURL) {
      const res = await postJSON("/api/speak", { text: el._msg.text, voice: $("#voice").value, personality: $("#personality").value });
      el._audioURL = URL.createObjectURL(await res.blob());
    }
    audioPlayer = new Audio(el._audioURL);
    audioPlayer._el = el;
    audioPlayer.onended = () => btn.classList.remove("playing");
    await audioPlayer.play();
  } catch (err) {
    btn.classList.remove("playing");
    if (err.name !== "NotAllowedError") toast(`Voice failed: ${err.message}`, "error");
  }
}

/* ----- Attachments (click, drag & drop, paste) ----- */
function shrinkImage(file, max = 1280) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, max / Math.max(img.width, img.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(img.width * scale); canvas.height = Math.round(img.height * scale);
      canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(img.src);
      resolve(canvas.toDataURL("image/jpeg", 0.88));
    };
    img.onerror = reject;
    img.src = URL.createObjectURL(file);
  });
}
async function addFiles(files) {
  for (const f of files) {
    if (!f.type.startsWith("image/")) continue;
    if (attachments.length >= 4) { toast("Up to 4 images per message."); break; }
    attachments.push(await shrinkImage(f));
  }
  renderAttachments();
}
function renderAttachments() {
  $("#attachments").innerHTML = attachments.map((src, i) =>
    `<div class="thumb"><img src="${src}" alt=""><button type="button" data-remove="${i}" aria-label="Remove">${icon("x")}</button></div>`).join("");
}

function autosize() {
  const t = $("#input");
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 200) + "px";
}

/* ----- Voice typing: record -> Whisper -> text appears in the box ----- */
let recorder = null;
async function toggleRecording() {
  if (recorder) { recorder.stop(); return; }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch { toast("Microphone blocked — allow it in the browser and in macOS Privacy settings.", "error"); return; }

  const type = ["audio/webm", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported(t)) || "";
  recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
  const chunks = [];
  recorder.ondataavailable = (e) => chunks.push(e.data);

  // Live waveform
  const ctx = new AudioContext(), analyser = ctx.createAnalyser();
  ctx.createMediaStreamSource(stream).connect(analyser);
  analyser.fftSize = 256;
  const data = new Uint8Array(analyser.frequencyBinCount), canvas = $("#rec-wave"), g = canvas.getContext("2d");
  const started = performance.now();
  $("#recorder").hidden = false;
  $("#mic-btn").classList.add("recording");
  (function draw() {
    if (!recorder) return;
    analyser.getByteFrequencyData(data);
    g.clearRect(0, 0, canvas.width, canvas.height);
    const bars = 60, w = canvas.width / bars;
    for (let i = 0; i < bars; i++) {
      const v = data[i * 2] / 255, h = Math.max(3, v * canvas.height);
      g.fillStyle = `hsl(${250 - i * 1.5} 90% 70%)`;
      g.fillRect(i * w + 1, (canvas.height - h) / 2, w - 3, h);
    }
    $("#rec-time").textContent = fmtTime((performance.now() - started) / 1000);
    requestAnimationFrame(draw);
  })();

  recorder.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    ctx.close();
    recorder = null;
    $("#recorder").hidden = true;
    $("#mic-btn").classList.remove("recording");
    const blob = new Blob(chunks, { type: type || "audio/webm" });
    const form = new FormData();
    form.append("audio", blob, type.includes("mp4") ? "voice.mp4" : "voice.webm");
    $("#composer-hint").textContent = "Transcribing…";
    try {
      const { text } = await (await api("/api/transcribe", { method: "POST", body: form })).json();
      const input = $("#input");
      input.value = `${input.value} ${text}`.trim();
      input.dataset.voice = "1";
      autosize(); input.focus();
    } catch (err) { toast(`Couldn't understand the audio: ${err.message}`, "error"); }
    $("#composer-hint").textContent = "Enter to send";
  };
  recorder.start();
}

function setupChat() {
  loadChats();
  setGreeting();
  current = chats[0] || null;
  if (current) renderChat(); else newChat();
  renderConvList();

  $("#composer").addEventListener("submit", (e) => {
    e.preventDefault();
    if (streaming) { streaming.abort(); return; }
    const input = $("#input");
    sendMessage(input.value, { voice: input.dataset.voice === "1" });
    delete input.dataset.voice;
  });
  $("#input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#composer").requestSubmit(); }
  });
  $("#input").addEventListener("input", autosize);
  $("#input").addEventListener("paste", (e) => {
    const files = [...e.clipboardData.files];
    if (files.length) { e.preventDefault(); addFiles(files); }
  });
  $("#file-input").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
  $("#attachments").addEventListener("click", (e) => {
    const b = e.target.closest("[data-remove]");
    if (b) { attachments.splice(+b.dataset.remove, 1); renderAttachments(); }
  });
  const composer = $("#composer");
  composer.addEventListener("dragover", (e) => { e.preventDefault(); composer.classList.add("drag"); });
  composer.addEventListener("dragleave", () => composer.classList.remove("drag"));
  composer.addEventListener("drop", (e) => { e.preventDefault(); composer.classList.remove("drag"); addFiles(e.dataTransfer.files); });
  $("#mic-btn").addEventListener("click", toggleRecording);

  $("#new-chat").addEventListener("click", newChat);
  $("#conv-list").addEventListener("click", (e) => {
    const del = e.target.closest("[data-del]");
    if (del) {
      chats = chats.filter((c) => c.id !== del.dataset.del);
      saveChats();
      if (current?.id === del.dataset.del) newChat(); else renderConvList();
      return;
    }
    const li = e.target.closest("li[data-id]");
    if (li) openChat(li.dataset.id);
  });
  $("#sidebar-toggle").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
  $$(".suggestion").forEach((b) => b.addEventListener("click", () => sendMessage(b.dataset.prompt)));
  for (const id of ["#personality", "#voice", "#autospeak"]) $(id).addEventListener("change", saveSettings);

  $("#messages").addEventListener("click", async (e) => {
    const el = e.target.closest(".msg");
    if (e.target.closest('[data-act="speak"]')) speakMessage(el);
    if (e.target.closest('[data-act="copy"]')) { await navigator.clipboard.writeText(el._msg.text); toast("Copied"); }
    if (e.target.closest("[data-animate]")) sendMessage("Animate that image into a short cinematic video.");
  });
}

/* =========================================================
   VIDEO STUDIO
   ========================================================= */
const studio = { mode: "text", engine: "auto", ratio: "16:9", seconds: 5, image: null, story: null, job: null };
const IDEAS = [
  "A small paper boat drifts down a rain-soaked cobblestone street at dusk, warm streetlights shimmering in the puddles, camera gliding low beside it",
  "A lonely rusty robot in a junkyard at sunset gently shields a tiny green sprout from the wind, slow push-in on its glowing blue eye",
  "An ancient white dragon wakes inside a crystal ice cave, frost cracking off its scales, camera pulling back to reveal its size",
  "Thousands of Diwali diyas glowing on the steps of an old riverside ghat at night, fireworks blooming over the water, slow aerial drift",
  "A lighthouse sweeps its golden beam across a stormy sea while giant waves explode against the cliffs, dramatic low angle",
  "A hummingbird hovers beside a red hibiscus in morning light, wings in slow motion, macro shot with soft bokeh",
];

function updateCost() {
  if (!STATUS) return;
  const scenes = studio.mode === "story" ? +$("#scenes").value : 1;
  const motion = 0.01 * scenes;
  const kling = studio.engine === "kling" || (studio.engine === "auto" && STATUS.video.includes("Kling"));
  const text = kling ? "Kling credits" : `~$${motion.toFixed(2)}`;
  $("#cost").textContent = `· ${text}`;
}

function setStudioMode(mode) {
  studio.mode = mode;
  $$("#studio-modes button").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  $("#dropzone").hidden = mode !== "image";
  $("#story-box").hidden = mode !== "story";
  $("#vo-text").hidden = mode === "story";
  $("#studio-prompt").placeholder = {
    text: "Describe your scene… e.g. A small paper boat drifting down a rain-soaked street at dusk",
    image: "Describe the motion… e.g. Gentle wind moves the hair, camera slowly pushes in",
    story: "Your story idea… e.g. A lonely robot finds a flower and protects it",
  }[mode];
  if (mode === "story") { $("#vo-toggle").checked = true; $("#vo-fields").hidden = false; }
  updateCost();
}

function setStudioImage(file) {
  if (!file?.type.startsWith("image/")) return;
  studio.image = file;
  const img = $("#dz-preview");
  img.src = URL.createObjectURL(file);
  img.hidden = false;
  $(".dz-empty").hidden = true;
}

function renderScenes() {
  $("#scene-list").innerHTML = (studio.story?.scenes || []).map((s, i) => `
    <div class="scene"><b>SCENE ${i + 1}</b>
      <textarea rows="3" data-i="${i}" data-k="visual">${escapeHTML(s.visual)}</textarea>
      <input type="text" data-i="${i}" data-k="narration" value="${escapeHTML(s.narration || "")}" placeholder="Narration"></div>`).join("");
}

function setStage(state) {
  $("#stage-idle").hidden = state !== "idle";
  $("#stage-run").hidden = state !== "run";
  $("#stage-done").hidden = state !== "done";
}

async function generateVideo() {
  const prompt = $("#studio-prompt").value.trim();
  if (!prompt) { toast("Write a prompt first."); $("#studio-prompt").focus(); return; }
  if (studio.mode === "image" && !studio.image) { toast("Upload an image to animate."); return; }

  const form = new FormData();
  form.append("mode", studio.mode);
  form.append("prompt", prompt);
  form.append("engine", studio.engine);
  form.append("ratio", studio.ratio);
  form.append("seconds", studio.seconds);
  form.append("scenes", $("#scenes").value);
  if ($("#vo-toggle").checked) {
    form.append("voice", $("#vo-voice").value);
    form.append("narration", $("#vo-text").value);
  }
  if (studio.mode === "story" && studio.story) form.append("story", JSON.stringify(studio.story));
  if (studio.mode === "image") form.append("image", studio.image);

  $("#generate").disabled = true;
  setStage("run");
  $$("#checklist li").forEach((li) => (li.className = ""));
  const started = performance.now();
  try {
    const { job_id } = await (await api("/api/videos", { method: "POST", body: form })).json();
    while (true) {
      await new Promise((r) => setTimeout(r, 1000));
      const job = await (await api(`/api/jobs/${job_id}`)).json();
      $("#ring").style.setProperty("--p", job.progress);
      $("#ring-pct").textContent = `${job.progress}%`;
      $("#stage-label").textContent = job.stage + (job.status === "running" ? "…" : "");
      $("#elapsed").textContent = fmtTime((performance.now() - started) / 1000);
      const order = ["plan", "gen", "voice", "edit"];
      const now = /Writ/.test(job.stage) ? 0 : /Generat/.test(job.stage) ? 1 : /Record/.test(job.stage) ? 2 : /Edit/.test(job.stage) ? 3 : job.status === "done" ? 4 : 1;
      $$("#checklist li").forEach((li) => {
        const idx = order.indexOf(li.dataset.step);
        li.className = idx < now ? "done" : idx === now ? "active" : "";
      });
      if (job.status === "error") throw new Error(job.error);
      if (job.status === "done") { showResult(job); break; }
    }
  } catch (err) {
    toast(`Generation failed: ${err.message}`, "error");
    setStage("idle");
  } finally {
    $("#generate").disabled = false;
  }
}

function showResult(job) {
  const r = job.result;
  setStage("done");
  const v = $("#result-video");
  v.src = r.url;
  v.play().catch(() => {});
  $("#result-title").textContent = r.title;
  $("#result-engine").textContent = r.engine;
  $("#result-download").href = r.url;
  $("#result-notice").hidden = !job.notice;
  $("#result-notice").textContent = job.notice || "";
  loadRecent();
}

async function loadRecent() {
  try {
    const items = (await (await api("/api/gallery")).json()).filter((i) => i.type === "video").slice(0, 10);
    $("#recent").innerHTML = items.map((i) => `<video src="${i.url}#t=0.5" muted preload="metadata" data-url="${i.url}" title="Play"></video>`).join("")
      || `<span class="muted">Your films will appear here.</span>`;
  } catch {}
}

function setupStudio() {
  $("#studio-modes").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setStudioMode(b.dataset.mode); });
  const prompt = $("#studio-prompt");
  prompt.addEventListener("input", () => ($("#prompt-count").textContent = `${prompt.value.length}/1000`));
  $("#inspire").addEventListener("click", () => {
    prompt.value = IDEAS[Math.floor(Math.random() * IDEAS.length)];
    prompt.dispatchEvent(new Event("input"));
  });
  $("#enhance").addEventListener("click", async (e) => {
    if (!prompt.value.trim()) { toast("Type a short idea first, then enhance it."); return; }
    const btn = e.currentTarget;
    btn.disabled = true; btn.innerHTML = `${icon("sparkles")} Enhancing…`;
    try {
      prompt.value = (await (await postJSON("/api/enhance", { prompt: prompt.value })).json()).prompt;
      prompt.dispatchEvent(new Event("input"));
    } catch (err) { toast(err.message, "error"); }
    btn.disabled = false; btn.innerHTML = `${icon("sparkles")} AI enhance`;
  });

  // Image upload (click or drag & drop)
  const dz = $("#dropzone");
  $("#studio-image").addEventListener("change", (e) => setStudioImage(e.target.files[0]));
  dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
  dz.addEventListener("drop", (e) => { e.preventDefault(); dz.classList.remove("drag"); setStudioImage(e.dataTransfer.files[0]); });

  // Story planning
  $("#scenes").addEventListener("input", (e) => { $("#scenes-val").textContent = e.target.value; studio.story = null; renderScenes(); updateCost(); });
  $("#write-story").addEventListener("click", async (e) => {
    if (!prompt.value.trim()) { toast("Write a story idea first."); return; }
    const btn = e.currentTarget;
    btn.disabled = true; btn.innerHTML = `${icon("book")} Writing…`;
    try {
      studio.story = await (await postJSON("/api/story", { idea: prompt.value, scenes: +$("#scenes").value, seconds: studio.seconds })).json();
      renderScenes();
      toast(`“${studio.story.title}” — edit the scenes, then Generate.`);
    } catch (err) { toast(err.message, "error"); }
    btn.disabled = false; btn.innerHTML = `${icon("book")} Rewrite the story`;
  });
  $("#scene-list").addEventListener("input", (e) => {
    const t = e.target;
    if (studio.story && t.dataset.i) studio.story.scenes[+t.dataset.i][t.dataset.k] = t.value;
  });

  // Options
  $("#engine-cards").addEventListener("click", (e) => {
    const b = e.target.closest(".engine-card");
    if (!b) return;
    if (b.classList.contains("disabled")) {
      toast("Add a KLING_API_KEY in .env to use Kling.");
      return;
    }
    studio.engine = b.dataset.engine;
    $$(".engine-card").forEach((c) => c.classList.toggle("active", c === b));
    updateCost();
  });
  $("#ratios").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    studio.ratio = b.dataset.ratio;
    $$("#ratios button").forEach((x) => x.classList.toggle("active", x === b));
  });
  $("#durations").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    studio.seconds = +b.dataset.sec;
    $$("#durations button").forEach((x) => x.classList.toggle("active", x === b));
    updateCost();
  });
  $("#vo-toggle").addEventListener("change", (e) => ($("#vo-fields").hidden = !e.target.checked));
  $("#generate").addEventListener("click", generateVideo);
  $("#recent").addEventListener("click", (e) => {
    const v = e.target.closest("video");
    if (v) openLightbox({ type: "video", url: v.dataset.url, name: v.dataset.url.split("/").pop().split(".")[0] });
  });
}

/* =========================================================
   GALLERY
   ========================================================= */
let galleryItems = [], galleryFilter = "all", lightboxItem = null;

async function loadGallery() {
  try { galleryItems = await (await api("/api/gallery")).json(); } catch { galleryItems = []; }
  renderGallery();
}
function renderGallery() {
  const items = galleryItems.filter((i) => galleryFilter === "all" || i.type === galleryFilter);
  $("#gallery-empty").hidden = items.length > 0;
  $("#masonry").innerHTML = items.map((i, n) => `
    <figure class="tile" data-n="${galleryItems.indexOf(i)}" style="animation-delay:${Math.min(n, 12) * 40}ms">
      ${i.type === "image" ? `<img src="${i.url}" alt="" loading="lazy">` : `<video src="${i.url}#t=0.5" muted loop playsinline preload="metadata"></video>`}
      <figcaption class="tile-meta"><span class="badge mono">${i.type === "image" ? icon("image") : icon("video")} ${new Date(i.time * 1000).toLocaleDateString()}</span></figcaption>
    </figure>`).join("");
}
function openLightbox(item) {
  lightboxItem = item;
  $("#lb-body").innerHTML = item.type === "image" ? `<img src="${item.url}" alt="">` : `<video src="${item.url}" controls autoplay loop playsinline></video>`;
  $("#lb-download").href = item.url;
  $("#lightbox").hidden = false;
}
function closeLightbox() { $("#lightbox").hidden = true; $("#lb-body").innerHTML = ""; }

function setupGallery() {
  $("#gallery-filter").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    galleryFilter = b.dataset.filter;
    $$("#gallery-filter button").forEach((x) => x.classList.toggle("active", x === b));
    renderGallery();
  });
  $("#masonry").addEventListener("click", (e) => {
    const t = e.target.closest(".tile"); if (t) openLightbox(galleryItems[+t.dataset.n]);
  });
  $("#masonry").addEventListener("pointerover", (e) => e.target.closest(".tile")?.querySelector("video")?.play().catch(() => {}));
  $("#masonry").addEventListener("pointerout", (e) => e.target.closest(".tile")?.querySelector("video")?.pause());
  $("#lb-close").addEventListener("click", closeLightbox);
  $("#lightbox").addEventListener("click", (e) => { if (e.target.id === "lightbox") closeLightbox(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeLightbox(); });
  $("#lb-delete").addEventListener("click", async () => {
    if (!lightboxItem || !confirm("Delete this file permanently?")) return;
    await api(`/api/gallery/${lightboxItem.type}/${lightboxItem.name}`, { method: "DELETE" });
    closeLightbox();
    loadGallery(); loadRecent();
    toast("Deleted");
  });
}

/* ---------------- Start ---------------- */
document.addEventListener("DOMContentLoaded", () => {
  setupReveal();
  setupTypewriter();
  setupPointerEffects();
  setupChat();
  setupStudio();
  setupGallery();
  loadStatus();
  route();
});
