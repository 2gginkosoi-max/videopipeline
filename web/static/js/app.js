/* ============================================================
   ГУСЬ ПЕРЕВОДИЛА — клиентская логика
   ============================================================ */
(function () {
  "use strict";

  const $  = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const state = {
    user: null,
    voices: [],
    voiceFilter: "all",
    selectedVoice: null,
    busy: false,
  };

  /* ------------------------------------------------ toast */

  let toastTimer = null;
  function toast(msg, kind) {
    const t = $("#toast");
    if (!t) return;
    t.textContent = msg;
    t.className = "toast is-show" + (kind ? " is-" + kind : "");
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      t.classList.remove("is-show");
      setTimeout(() => { t.hidden = true; }, 250);
    }, 3600);
  }

  function api(path, opts) {
    opts = opts || {};
    const init = { method: opts.method || "GET", headers: {} };
    if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    if (opts.form) { init.body = opts.form; delete init.headers["Content-Type"]; }
    return fetch(path, init).then(async (r) => {
      let d = null;
      try { d = await r.json(); } catch (e) { d = null; }
      if (!r.ok) {
        const msg = (d && (d.detail || d.message)) || ("Ошибка " + r.status);
        throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
      }
      return d;
    });
  }

  /* ------------------------------------------------ авторизация */

  async function loadMe() {
    try {
      const d = await api("/api/auth/me");
      state.user = d.user;
    } catch (e) { state.user = null; }

    const menu = $("#userMenu");
    const loginBtn = $("#loginBtn");
    if (state.user) {
      if (menu) menu.hidden = false;
      if (loginBtn) loginBtn.hidden = true;
      const name = state.user.username;
      const n = $("#userName"); if (n) n.textContent = name;
      const a = $("#userAvatar"); if (a) a.textContent = name.slice(0, 1).toUpperCase();
      const pn = $("#profileName"); if (pn) pn.textContent = name;
      const pa = $("#profileAvatar"); if (pa) pa.textContent = name.slice(0, 1).toUpperCase();
      const pe = $("#profileEmail");
      if (pe) pe.textContent = state.user.email || "аккаунт активен";
      loadMyStats();
      renderProfileTab();
    } else {
      if (menu) menu.hidden = true;
      if (loginBtn) loginBtn.hidden = false;
    }
  }

  async function loadMyStats() {
    if (!state.user) return;
    try {
      const v = await api("/api/videos");
      const n = v.videos.length;
      ["statVideos", "profVideos"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = n;
      });
    } catch (e) {}
    try {
      const v = await api("/api/voices");
      const mine = v.voices.filter(x => !x.builtin).length;
      ["statVoices", "profVoices"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = mine;
      });
    } catch (e) {}
  }

  function initUserMenu() {
    // всплывающее меню со ссылками на старые страницы убрано:
    // архив и профиль — это вкладки в левом меню, здесь остаётся только выход
    const out = $("#logoutBtn");
    if (out) out.addEventListener("click", () => doLogout());
    const pout = $("#profileLogout");
    if (pout) pout.addEventListener("click", () => doLogout());
  }

  async function doLogout() {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch (e) {}
    location.reload();
  }

  /* ------------------------------------------------ голоса */

  const GENDER_LABEL = { male: "М", female: "Ж", neutral: "—", unknown: "?" };
  const GENDER_TITLE = { male: "Мужской", female: "Женский",
                         neutral: "Нейтральный", unknown: "Не определён" };

  async function loadVoices() {
    try {
      const d = await api("/api/voices");
      state.voices = d.voices || [];
    } catch (e) {
      state.voices = [];
    }
    renderVoices();
    renderVoiceOptions();
  }

  /* Селект «Выбор голоса» в новом layout. Группируем: встроенные / мои клоны. */
  function renderVoiceOptions() {
    const sel = $("#voiceId");
    if (!sel) return;
    const prev = state.selectedVoice || sel.value;
    sel.innerHTML = "";

    if (!state.voices.length) {
      const o = document.createElement("option");
      o.value = "";
      o.textContent = "Голоса не загрузились";
      sel.appendChild(o);
      return;
    }

    const groups = [
      ["Встроенные", state.voices.filter(v => v.builtin)],
      ["Мои клоны", state.voices.filter(v => !v.builtin)]
    ];
    groups.forEach(([label, items]) => {
      if (!items.length) return;
      const g = document.createElement("optgroup");
      g.label = label;
      items.forEach((v) => {
        const o = document.createElement("option");
        o.value = v.id;
        o.textContent = v.name + (v.gender === "female" ? " · ж" : v.gender === "male" ? " · м" : "");
        g.appendChild(o);
      });
      sel.appendChild(g);
    });

    const pick = state.voices.some(v => v.id === prev) ? prev : state.voices[0].id;
    sel.value = pick;
    state.selectedVoice = pick;
  }

  function initVoiceSelect() {
    const sel = $("#voiceId");
    if (sel) sel.addEventListener("change", () => { state.selectedVoice = sel.value; });

    const btn = $("#voicePreviewBtn");
    if (btn) btn.addEventListener("click", () => {
      const id = state.selectedVoice || (sel && sel.value);
      if (!id) { toast("Выберите голос", "err"); return; }
      previewVoice(id);
    });
  }

  function renderVoices() {
    const grid = $("#voiceGrid");
    if (!grid) return;
    let items = state.voices.slice();

    if (state.voiceFilter === "male" || state.voiceFilter === "female") {
      items = items.filter(v => v.gender === state.voiceFilter);
    } else if (state.voiceFilter === "mine") {
      items = items.filter(v => !v.builtin);
    }

    if (!items.length) {
      grid.innerHTML = '<div class="empty__inline">Здесь пока пусто</div>';
      return;
    }

    grid.innerHTML = "";
    items.forEach((v) => {
      const el = document.createElement("div");
      el.className = "vcard2" + (state.selectedVoice === v.id ? " is-on" : "");
      el.dataset.id = v.id;
      el.innerHTML =
        '<div class="vcard2__gender g-' + (v.gender || "unknown") + '" title="' +
        (GENDER_TITLE[v.gender] || "") + ' — клик меняет пол">' + (GENDER_LABEL[v.gender] || "?") + '</div>' +
        '<div class="vcard2__name" title="' + esc(v.name) + ' (двойной клик — переименовать)">' + esc(v.name) + '</div>' +
        '<div class="vcard2__meta">' + (v.builtin ? "встроенный" : "мой клон") +
          (v.f0 ? ' · ' + v.f0 + ' Гц' : "") + '</div>' +
        '<button type="button" class="vcard2__play" title="Прослушать">▶</button>';
      el.addEventListener("click", (e) => {
        if (e.target.closest(".vcard2__play")) return;
        if (e.target.closest(".vcard2__gender")) return;
        selectVoice(v.id);
      });
      $(".vcard2__play", el).addEventListener("click", (e) => {
        e.stopPropagation();
        previewVoice(v.id);
      });
      $(".vcard2__gender", el).addEventListener("click", (e) => {
        e.stopPropagation();
        cycleGender(v);
      });
      $(".vcard2__name", el).addEventListener("dblclick", (e) => {
        e.stopPropagation();
        renameVoice(v);
      });
      grid.appendChild(el);
    });
  }

  const GENDER_CYCLE = ["male", "female", "neutral"];

  async function cycleGender(v) {
    const i = GENDER_CYCLE.indexOf(v.gender);
    const next = GENDER_CYCLE[(i + 1) % GENDER_CYCLE.length];
    try {
      await api("/api/voices/" + encodeURIComponent(v.id), {
        method: "PATCH", body: { gender: next }
      });
      v.gender = next;
      renderVoices();
      toast("«" + v.name + "» → " + GENDER_TITLE[next], "ok");
    } catch (e) { toast(e.message, "err"); }
  }

  async function renameVoice(v) {
    const name = prompt("Новое название голоса:", v.name);
    if (!name || name === v.name) return;
    try {
      await api("/api/voices/" + encodeURIComponent(v.id), {
        method: "PATCH", body: { name: name.trim() }
      });
      v.name = name.trim();
      renderVoices();
      toast("Переименовано", "ok");
    } catch (e) { toast(e.message, "err"); }
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function selectVoice(id) {
    state.selectedVoice = id;
    const hidden = $("#voiceId");
    if (hidden) hidden.value = id;
    renderVoices();
  }

  /* Прослушивание: сначала готовый пример файлом (играет сразу),
     синтез «на месте» — только если примера нет. */
  async function previewVoice(id) {
    // профиль грузится асинхронно — дождёмся его, иначе сразу после
    // открытия страницы кнопка «Прослушать» ругалась «Войдите»
    if (!state.user && state.mePromise) {
      try { await state.mePromise; } catch (e) { /* ignore */ }
    }
    if (!state.user) { toast("Войдите, чтобы слушать голоса", "err"); return; }
    const v = state.voices.find(x => x.id === id) || {
      id: id, name: id, sample_ts: 0,
      sample_url: "/api/voices/" + encodeURIComponent(id) + "/sample"
    };
    const box = $("#voicePreview");
    const audio = $("#voiceAudio");

    if (box && audio && v && v.sample_url) {
      box.hidden = false;
      $("#voicePreviewName").textContent = "Пример: " + v.name;
      audio.onerror = () => {
        audio.onerror = null;
        synthesizePreview(v);        // примера нет — синтезируем как раньше
      };
      audio.src = v.sample_url + "?v=" + (v.sample_ts || 0);
      const pr = audio.play();
      if (pr && pr.catch) pr.catch(() => {});
      return;
    }
    synthesizePreview(v || { id: id, name: id });
  }

  async function synthesizePreview(v) {
    const id = v && v.id;
    toast("Готовим пробное аудио…");
    try {
      const d = await api("/api/voices/preview", {
        method: "POST", body: { voice_id: id }
      });
      const box = $("#voicePreview");
      const audio = $("#voiceAudio");
      if (box && audio) {
        audio.src = d.url + "?t=" + Date.now();
        box.hidden = false;
        $("#voicePreviewName").textContent = "Проба: " + (d.voice || "");
        audio.play().catch(() => {});
      }
      toast("Готово", "ok");
    } catch (e) {
      toast("Не удалось: " + e.message, "err");
    }
  }

  function initVoiceTabs() {
    const tabs = $("#voiceTabs");
    if (!tabs) return;
    tabs.addEventListener("click", (e) => {
      const b = e.target.closest(".seg");
      if (!b) return;
      $$(".seg", tabs).forEach(x => x.classList.remove("is-on"));
      b.classList.add("is-on");
      state.voiceFilter = b.dataset.gender;
      renderVoices();
    });
  }

  function initClone() {
    const modal = $("#cloneModal");
    const openBtn = $("#cloneBtn");
    if (!modal || !openBtn) return;

    const close = () => { modal.hidden = true; };
    openBtn.addEventListener("click", () => {
      if (!state.user) { toast("Войдите, чтобы добавлять голоса", "err"); return; }
      modal.hidden = false;
    });
    $("#cloneClose").addEventListener("click", close);
    $("#cloneCancel").addEventListener("click", close);
    modal.addEventListener("click", (e) => { if (e.target === modal) close(); });

    $("#cloneGo").addEventListener("click", async () => {
      const f = $("#cloneFile").files[0];
      if (!f) { toast("Выберите файл", "err"); return; }
      const fd = new FormData();
      fd.append("file", f);
      fd.append("name", $("#cloneName").value || "");
      fd.append("gender", $("#cloneGender").value || "auto");

      const btn = $("#cloneGo");
      btn.disabled = true;
      btn.textContent = "Клонируем…";
      const log = $("#cloneLog");
      log.hidden = false;
      log.textContent = "Извлекаем голос и распознаём текст референса… (30–90 c)";

      try {
        const d = await api("/api/voices/clone", { method: "POST", form: fd });
        toast("Голос «" + d.voice.name + "» добавлен", "ok");
        close();
        $("#cloneFile").value = "";
        $("#cloneName").value = "";
        await loadVoices();
        selectVoice(d.voice.id);
        previewVoice(d.voice.id);     // сразу слышно, что получилось
        loadMyStats();
      } catch (e) {
        log.textContent = "Ошибка: " + e.message;
        toast("Ошибка клонирования: " + e.message, "err");
      } finally {
        btn.disabled = false;
        btn.textContent = "Клонировать";
      }
    });
  }

  /* ------------------------------------------------ новости */

  function initNews() {
    const toggle = $("#toggleNews");
    const block = $("#newsBlock");
    if (toggle && block) {
      toggle.addEventListener("click", () => {
        block.hidden = !block.hidden;
        toggle.textContent = block.hidden ? "Открыть" : "Скрыть";
        if (!block.hidden) loadSubs();
      });
    }

    const modeBox = $("#newsMode");
    if (modeBox) modeBox.addEventListener("click", (e) => {
      const b = e.target.closest(".seg");
      if (!b) return;
      $$(".seg", modeBox).forEach(x => x.classList.remove("is-on"));
      b.classList.add("is-on");
    });

    const btn = $("#searchNews");
    if (btn) btn.addEventListener("click", doSearchNews);
  }

  async function loadSubs() {
    const sel = $("#newsSubs");
    if (!sel || sel.options.length) return;
    try {
      const d = await api("/api/news/subs");
      sel.innerHTML = "";
      (d.subs || []).forEach((s, i) => {
        const o = document.createElement("option");
        o.value = s.key;
        o.textContent = "r/" + s.name;
        if (i < 3) o.selected = true;
        sel.appendChild(o);
      });
    } catch (e) {}
  }

  async function doSearchNews() {
    if (!state.user) { toast("Войдите, чтобы искать новости", "err"); return; }
    const sel = $("#newsSubs");
    const subs = Array.from(sel.selectedOptions).map(o => o.value);
    if (!subs.length) { toast("Выберите хотя бы один сабреддит", "err"); return; }

    const mode = ($("#newsMode .seg.is-on") || {}).dataset?.mode || "hot";
    const btn = $("#searchNews");
    btn.disabled = true;
    btn.textContent = "Ищем…";
    $("#newsHint").textContent = "Ищем свежие посты…";

    try {
      await api("/api/news/search", { method: "POST", body: { subs, mode } });
      $("#newsList").hidden = false;
      $("#newsItems").innerHTML = '<div class="empty__inline">Ищем…</div>';
    } catch (e) {
      toast("Ошибка поиска: " + e.message, "err");
    } finally {
      btn.disabled = false;
      btn.textContent = "🔍 Найти новости";
    }
  }

  function renderNews(posts) {
    const box = $("#newsItems");
    if (!box) return;
    $("#newsList").hidden = false;
    if (!posts || !posts.length) {
      box.innerHTML = '<div class="empty__inline">Ничего не нашлось. Reddit мог ответить 429 — попробуйте позже или другой сабреддит.</div>';
      return;
    }
    box.innerHTML = "";
    posts.forEach((p) => {
      const el = document.createElement("div");
      el.className = "newsitem";
      const thumb = p.thumb ? '<img class="newsitem__thumb" src="' + esc(p.thumb) + '" alt="">' : "";
      el.innerHTML =
        thumb +
        '<div class="newsitem__body">' +
          '<div class="newsitem__title">' + esc(p.title) + '</div>' +
          '<div class="newsitem__meta">r/' + esc(p.sub || "") +
            (p.video_url ? ' · <span class="newsitem__vid">видео</span>' : '') + '</div>' +
        '</div>' +
        '<button type="button" class="btn btn--mini btn--accent newsitem__go">Сценарий</button>';
      $(".newsitem__go", el).addEventListener("click", () => makeScenario(p));
      box.appendChild(el);
    });
  }

  async function makeScenario(p) {
    if (!state.user) { toast("Войдите, чтобы генерировать сценарии", "err"); return; }
    toast("LLM пишет сценарий… (10–40 c)");
    const topic = $("input[name=topic]");
    if (topic && !topic.value) topic.value = p.title;
    try {
      const d = await api("/api/news/scenario", {
        method: "POST",
        body: { title: p.title, context: p.context || "", link: p.link || "" }
      });
      showVariants(d.variants || []);
      if (p.video_url) {
        const vu = $("input[name=video_url]");
        if (vu) vu.value = p.video_url;
        toast("Ссылка на видео подставлена", "ok");
      }
    } catch (e) {
      toast("Не удалось: " + e.message, "err");
    }
  }

  /* ------------------------------------------------ сценарии */

  function showVariants(variants) {
    const box = $("#variants");
    if (!box) return;
    box.hidden = false;
    box.innerHTML = "";
    if (!variants.length) {
      box.innerHTML = '<div class="empty__inline">Вариантов нет</div>';
      return;
    }
    variants.forEach((v) => {
      const el = document.createElement("div");
      el.className = "variant";
      el.innerHTML =
        '<div class="variant__title">' + esc(v.title || "") + '</div>' +
        (v.hook ? '<div class="variant__hook">хук: ' + esc(v.hook) + '</div>' : "") +
        '<div class="variant__text">' + esc(v.script) + '</div>';
      const b = document.createElement("button");
      b.type = "button";
      b.className = "btn btn--mini btn--accent";
      b.textContent = "Взять этот";
      b.addEventListener("click", () => {
        const ta = $("textarea[name=script]");
        if (ta) { ta.value = v.script; ta.dispatchEvent(new Event("input")); }
        toast("Сценарий подставлен", "ok");
      });
      el.appendChild(b);
      box.appendChild(el);
    });
  }

  function initScenarioTools() {
    const gen = $("#genScenario");
    if (gen) gen.addEventListener("click", async () => {
      if (!state.user) { toast("Войдите, чтобы генерировать сценарии", "err"); return; }
      const topic = prompt("О чём сценарий? Опишите тему одним предложением:");
      if (!topic) return;
      gen.disabled = true;
      gen.textContent = "Пишем…";
      try {
        const d = await api("/api/scenarios/generate", {
          method: "POST", body: { topic }
        });
        showVariants(d.variants || []);
        toast("Готово — выберите вариант", "ok");
      } catch (e) {
        toast("Ошибка: " + e.message, "err");
      } finally {
        gen.disabled = false;
        gen.textContent = "✨ Варианты по теме";
      }
    });

    const mine = $("#myScenariosBtn");
    if (mine) mine.addEventListener("click", async () => {
      if (!state.user) { toast("Войдите, чтобы видеть свои сценарии", "err"); return; }
      try {
        const d = await api("/api/scenarios");
        const list = d.scenarios || [];
        if (!list.length) { toast("Сохранённых сценариев пока нет", "err"); return; }
        showVariants(list.map(s => ({
          title: s.title, script: s.text, id: s.id
        })));
        toast("Показаны сохранённые сценарии", "ok");
      } catch (e) { toast("Ошибка: " + e.message, "err"); }
    });
  }

  /* ------------------------------------------------ terminal log */

  const MAX_LINES = 3000;

  function classify(line) {
    const l = line.toLowerCase();
    if (l.startsWith("=====")) return "term-line--head";
    if (l.includes("[ok]") || l.includes("[done]")) return "term-line--ok";
    if (l.includes("[error]") || l.includes("[block]") || l.includes("traceback")) return "term-line--err";
    if (l.includes("[warn]") || l.includes("[skip]") || l.includes("[archive]")) return "term-line--warn";
    if (l.startsWith("$ ")) return "term-line--cmd";
    return "";
  }

  function appendLog(line) {
    const body = $("#logBody");
    if (!body) return;
    const empty = $(".terminal__empty", body);
    if (empty) empty.remove();
    const div = document.createElement("div");
    div.className = "term-line " + classify(line);
    div.textContent = line;
    body.appendChild(div);
    while (body.childElementCount > MAX_LINES) body.removeChild(body.firstChild);
    const term = $("#log");
    if (term) term.scrollTop = term.scrollHeight;
  }

  function setLive(on, text) {
    const d = $("#liveDot");
    if (d) d.className = "step step--live" + (on ? " is-live" : "");
    const m = $("#logMeta");
    if (m) m.textContent = text || (on ? "выполняется…" : "ожидание запуска");
  }

  function setBusy(on) {
    state.busy = on;
    const btn = $("#runBtn");
    if (!btn) return;
    btn.disabled = on;
    btn.classList.toggle("is-busy", on);
    const label = $(".btn__label", btn);
    if (label) label.textContent = on ? "Собираем…" : "Собрать ролик";
    const sub = $(".btn__sub", btn);
    if (sub) sub.textContent = on
      ? "не закрывайте вкладку" : "~5–8 минут · F5-TTS + FFmpeg";
  }

  /* ------------------------------------------------ этапы конвейера */

  let stageTimer = null;
  let stageStart = 0;

  function fmtDur(sec) {
    const s = Math.max(0, Math.floor(sec));
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }

  function resetStages() {
    const body = $("#logBody");
    if (body) body.innerHTML = "";
    clearInterval(stageTimer);
    stageTimer = null;
    stageStart = 0;
  }

  function addStage(label, step) {
    const body = $("#logBody");
    if (!body) return;
    const prev = body.querySelector(".job-step.is-active");
    if (prev) {
      prev.classList.remove("is-active");
      prev.classList.add("is-done");
      const t = prev.querySelector(".job-step__time");
      if (t && stageStart) t.textContent = fmtDur((Date.now() - stageStart) / 1000);
    }
    const row = document.createElement("div");
    row.className = "job-step is-active";
    if (step) row.dataset.step = step;
    row.innerHTML = '<span class="job-step__dot"></span>' +
                    '<span class="job-step__label"></span>' +
                    '<span class="job-step__time">0:00</span>';
    row.querySelector(".job-step__label").textContent = label;
    body.appendChild(row);
    const term = $("#log");
    if (term) term.scrollTop = term.scrollHeight;
    stageStart = Date.now();
    setLive(true, label);
    clearInterval(stageTimer);
    stageTimer = setInterval(() => {
      const cur = body.querySelector(".job-step.is-active .job-step__time");
      if (cur) cur.textContent = fmtDur((Date.now() - stageStart) / 1000);
    }, 1000);
  }

  function finishStages(text) {
    clearInterval(stageTimer);
    stageTimer = null;
    const body = $("#logBody");
    const cur = body && body.querySelector(".job-step.is-active");
    if (cur) {
      cur.classList.remove("is-active");
      cur.classList.add("is-done");
      const t = cur.querySelector(".job-step__time");
      if (t && stageStart) t.textContent = fmtDur((Date.now() - stageStart) / 1000);
    }
    stageStart = 0;
    setLive(false, text || "готово");
  }

  function appendFinal(text, ok) {
    const body = $("#logBody");
    if (!body) return;
    const div = document.createElement("div");
    div.className = "job-final " + (ok ? "is-ok" : "is-err");
    div.textContent = text;
    body.appendChild(div);
    const term = $("#log");
    if (term) term.scrollTop = term.scrollHeight;
  }

  /* Готовый ролик: путь на диске + кнопки «Скачать» и «Открыть». */
  function appendVideoReady(msg) {
    const body = $("#logBody");
    if (!body) return;
    const box = document.createElement("div");
    box.className = "video-ready";

    const head = document.createElement("div");
    head.className = "video-ready__head";
    const check = document.createElement("span");
    check.className = "video-ready__check";
    check.textContent = "✓";
    const headText = document.createElement("span");
    headText.textContent = "Ролик готов";
    head.appendChild(check);
    head.appendChild(headText);

    const name = document.createElement("div");
    name.className = "video-ready__name";
    name.textContent = msg.name || msg.title || "видео";

    const path = document.createElement("div");
    path.className = "video-ready__path";
    path.textContent = msg.path || "";
    path.title = msg.path || "";

    const meta = document.createElement("div");
    meta.className = "video-ready__meta";
    meta.textContent = (msg.size_h || "") +
      (msg.title ? " · " + msg.title : "") + " · сохранён в профиль";

    const actions = document.createElement("div");
    actions.className = "video-ready__actions";
    if (msg.download) {
      const dl = document.createElement("a");
      dl.className = "video-ready__btn is-primary";
      dl.href = msg.download;
      dl.setAttribute("download", "");
      dl.textContent = "Скачать";
      actions.appendChild(dl);
    }
    if (msg.url) {
      const open = document.createElement("a");
      open.className = "video-ready__btn";
      open.href = msg.url;
      open.target = "_blank";
      open.rel = "noopener";
      open.textContent = "Открыть";
      actions.appendChild(open);
    }

    box.appendChild(head);
    box.appendChild(name);
    if (msg.path) box.appendChild(path);
    box.appendChild(meta);
    if (actions.children.length) box.appendChild(actions);
    body.appendChild(box);
    const term = $("#log");
    if (term) term.scrollTop = term.scrollHeight;
  }

  /* Теги, которые SEO подобрал именно под этот ролик. */
  function appendSeo(msg) {
    const body = $("#logBody");
    if (!body) return;
    const box = document.createElement("div");
    box.className = "seo-card";

    const head = document.createElement("div");
    head.className = "seo-card__head";
    head.textContent = "Теги под этот ролик";

    const title = document.createElement("div");
    title.className = "seo-card__title";
    title.textContent = msg.title || "";

    const list = document.createElement("div");
    list.className = "seo-card__tags";
    (msg.tags || []).forEach((t) => {
      const chip = document.createElement("span");
      chip.className = "seo-tag";
      chip.textContent = t;
      list.appendChild(chip);
    });

    box.appendChild(head);
    if (msg.title) box.appendChild(title);
    if ((msg.tags || []).length) box.appendChild(list);
    if ((msg.hashtags || []).length) {
      const note = document.createElement("div");
      note.className = "seo-card__note";
      note.textContent = "Хэштеги в описании: " + msg.hashtags.join(" ");
      box.appendChild(note);
    }
    body.appendChild(box);
    const term = $("#log");
    if (term) term.scrollTop = term.scrollHeight;
  }

  /* ------------------------------------------------ websocket */

  let ws = null;
  let wsRetry = 0;

  function setConn(state, text) {
    const el = $("#conn");
    if (!el) return;
    el.className = "status " + (state === "on" ? "is-on" : "");
    $("span", el).textContent = text;
  }

  function connectWS() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    try { ws = new WebSocket(proto + "//" + location.host + "/ws"); }
    catch (e) { setConn("off", "нет связи"); return; }

    ws.onopen = () => { wsRetry = 0; setConn("on", "на связи"); };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      handleMsg(msg);
    };
    ws.onclose = () => {
      setConn("off", "переподключение…");
      wsRetry = Math.min(wsRetry + 1, 6);
      setTimeout(connectWS, 800 * wsRetry);
    };
    ws.onerror = () => { try { ws.close(); } catch (e) {} };
  }

  function handleMsg(msg) {
    switch (msg.kind) {
      case "hello":
        break;

      case "news_start": {
        const h = $("#newsHint");
        if (h) h.textContent = "Ищем…";
        break;
      }

      case "news_progress": {
        const h = $("#newsHint");
        if (h) h.textContent = msg.text + " (" + msg.current + "/" + msg.total + ")";
        break;
      }

      case "news_end": {
        const h = $("#newsHint");
        if (!h) break;
        if (msg.ok) {
          h.textContent = "Готово: " + (msg.posts || []).length + " постов";
          renderNews(msg.posts || []);
        } else {
          h.textContent = "Reddit не ответил: " + (msg.error || "");
          toast("Reddit: " + (msg.error || "ошибка"), "err");
        }
        break;
      }

      case "job_start":
        resetStages();
        setLive(true, "запуск…");
        setBusy(true);
        break;

      case "stage":
        addStage(msg.label, msg.step);
        break;

      case "seo":
        appendSeo(msg);
        break;

      case "log":
        appendLog(msg.line);
        break;

      case "video_ready":
        appendVideoReady(msg);
        loadMyStats();
        renderArchive();
        break;

      case "job_end": {
        finishStages(msg.status === "done" ? "готово" : "остановлено");
        setBusy(false);
        // если ролик уже показан карточкой — не дублируем финальной строкой
        const body = $("#logBody");
        if (!(msg.status === "done" && body && body.querySelector(".video-ready"))) {
          appendFinal(msg.status === "done" ? "✓ Готово" : "Остановлено",
                      msg.status === "done");
        }
        toast(msg.status === "done"
          ? "Ролик готов — он в вашем профиле"
          : "Сборка остановлена", msg.status === "done" ? "ok" : "err");
        loadMyStats();
        break;
      }
    }
  }

  /* ------------------------------------------------ форма */

  function initCounter() {
    const ta = $("textarea[name=script]");
    if (!ta) return;
    const upd = () => {
      const v = ta.value.trim();
      const lenEl = $("#scriptLen");
      const wordsEl = $("#scriptWords");
      if (lenEl) lenEl.textContent = v.length;
      if (wordsEl) wordsEl.textContent = v ? v.split(/\s+/).length : 0;
    };
    ta.addEventListener("input", upd);
    upd();
  }

  function initUpload() {
    const drop = $("#drop");
    const input = $("#fileInput");
    const pick = $("#pickBtn");
    const info = $("#dropFile");
    if (!drop || !input) return;

    const show = (name, path) => {
      info.hidden = false;
      info.textContent = "✔ " + name + (path ? "  →  " + path : "");
      $(".drop__title", drop).textContent = "Файл прикреплён";
    };

    drop.addEventListener("click", (e) => {
      if (e.target === pick) return;
      input.click();
    });
    if (pick) pick.addEventListener("click", (e) => { e.stopPropagation(); input.click(); });

    ["dragenter", "dragover"].forEach(ev =>
      drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("is-over"); }));
    ["dragleave", "drop"].forEach(ev =>
      drop.addEventListener(ev, (e) => {
        e.preventDefault();
        if (ev === "dragleave" && drop.contains(e.relatedTarget)) return;
        drop.classList.remove("is-over");
      }));

    drop.addEventListener("drop", (e) => {
      const f = e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) upload(f);
    });
    input.addEventListener("change", () => {
      if (input.files && input.files[0]) upload(input.files[0]);
    });

    async function upload(file) {
      show(file.name, "загружаем…");
      const fd = new FormData();
      fd.append("file", file);
      try {
        const d = await api("/api/upload", { method: "POST", form: fd });
        show(d.name, d.path);
        const asset = $("input[name=asset]");
        if (asset) asset.value = d.path;
        toast("Файл загружен: " + d.name, "ok");
      } catch (err) {
        info.hidden = true;
        $(".drop__title", drop).textContent = "Перетащите видео сюда";
        toast("Ошибка загрузки: " + err.message, "err");
      }
    }
  }

  function initForm() {
    const form = $("#runForm");
    if (!form) return;

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (state.busy) return;
      if (!state.user) { toast("Войдите, чтобы собирать ролики", "err"); return; }

      const fd = new FormData(form);
      const payload = {};
      for (const [k, v] of fd.entries()) payload[k] = v;
      for (const el of $$("input[type=checkbox]", form)) payload[el.name] = el.checked;

      if (!payload.script && !payload.asset && !payload.video_url) {
        toast("Укажите сценарий или источник b-roll", "err");
        return;
      }

      setBusy(true);
      setLive(true, "запуск…");
      appendLog("");
      appendLog("● Запуск конвейера…");

      try {
        const d = await api("/api/process", { method: "POST", body: payload });
        const ta = $("textarea[name=script]");
        if (ta) ta.value = payload.script || "";
        await api("/api/scenarios", {
          method: "POST",
          body: { text: payload.script || "", title: payload.topic || "", source: "used" }
        });
      } catch (err) {
        setBusy(false);
        setLive(false);
        toast("Ошибка запуска: " + err.message, "err");
      }
    });

    const clr = $("#clearBtn");
    if (clr) clr.addEventListener("click", () => {
      form.reset();
      const info = $("#dropFile");
      if (info) info.hidden = true;
      const t = $(".drop__title", $("#drop"));
      if (t) t.textContent = "Перетащите видео сюда";
      initCounter();
    });
  }

  function initLogButtons() {
    const copy = $("#copyLog");
    if (copy) copy.addEventListener("click", async () => {
      const body = $("#logBody");
      if (!body) return;
      const text = (body.innerText || "").trim();
      try { await navigator.clipboard.writeText(text); toast("Список этапов скопирован", "ok"); }
      catch (e) { toast("Не удалось скопировать", "err"); }
    });

    const clr = $("#clearLog");
    if (clr) clr.addEventListener("click", () => {
      const body = $("#logBody");
      if (body) body.innerHTML = '<div class="terminal__empty">// лог очищен</div>';
    });
  }

  /* ------------------------------------------------ страница архива */

  function initResults() {
    const reload = $("#reload");
    if (reload) reload.addEventListener("click", () => renderArchive());

    const openFolder = $("#openFolder");
    if (openFolder) openFolder.addEventListener("click", () => openFolderPath(
      "D:\\AI\\VIDEO_PIPELINE\\output"));

    // карточки архива рендерятся из API — слушатели вешаем в renderArchive()
    document.querySelectorAll('[data-tab="archive"]').forEach(btn =>
      btn.addEventListener("click", () => renderArchive()));
    renderArchive();

    // вкладка «Профиль» — голоса и сценарии прямо на странице
    document.querySelectorAll('[data-tab="profile"]').forEach(btn =>
      btn.addEventListener("click", () => renderProfileTab()));
    renderProfileTab();

    // страница /results отдаётся сервером с готовой разметкой — оживляем её как раньше
    $$("[data-open]").forEach(btn =>
      btn.addEventListener("click", () => openFolderPath(btn.dataset.open))
    );

    $$(".vcard__play").forEach(btn =>
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const card = btn.closest(".vcard");
        const vid = card && card.querySelector("video");
        if (!vid) return;
        if (vid.paused) {
          vid.play();
          btn.classList.add("is-playing");
        } else {
          vid.pause();
          btn.classList.remove("is-playing");
        }
      })
    );

    // Ленивая подгрузка видео — страница открывается мгновенно
    if ("IntersectionObserver" in window) {
      const io = new IntersectionObserver((entries) => {
        entries.forEach((e) => {
          if (!e.isIntersecting) return;
          const v = e.target;
          if (v.dataset.src && !v.src) { v.src = v.dataset.src; v.load(); }
          io.unobserve(v);
        });
      }, { rootMargin: "300px" });
      $$(".vcard__thumb video").forEach((v) => io.observe(v));
    } else {
      $$(".vcard__thumb video").forEach((v) => { v.src = v.dataset.src; });
    }

    $$(".vcard__thumb video").forEach(v =>
      v.addEventListener("mouseenter", () => v.play().catch(() => {}))
    );
    $$(".vcard__thumb").forEach(th =>
      th.addEventListener("mouseleave", () => {
        const v = th.querySelector("video");
        if (v) { v.pause(); v.currentTime = 0; }
      })
    );
  }

  async function renderArchive() {
    const grid = $("#archiveGrid");
    if (!grid) return;
    const empty = $("#archiveEmpty");

    if (!state.user) {
      grid.innerHTML = "";
      if (empty) {
        empty.hidden = false;
        empty.textContent = "Войдите, чтобы увидеть свои ролики.";
      }
      return;
    }

    let videos = [];
    try {
      const d = await api("/api/videos");
      videos = d.videos || [];
    } catch (e) {
      grid.innerHTML = "";
      if (empty) {
        empty.hidden = false;
        empty.textContent = "Не удалось загрузить список: " + e.message;
      }
      return;
    }

    grid.innerHTML = "";
    if (empty) {
      empty.hidden = videos.length > 0;
      if (!videos.length) empty.textContent = "Роликов пока нет — соберите первый на вкладке «Сборка».";
    }

    videos.forEach((v) => {
      const card = document.createElement("article");
      card.className = "vcard";
      card.innerHTML =
        '<div class="vcard__thumb">' +
          '<video preload="none" muted playsinline' +
            (v.url ? ' data-src="' + esc(v.url) + '"' : '') + '></video>' +
          (v.url ? '<button type="button" class="vcard__play">▶</button>' : '') +
        '</div>' +
        '<div class="vcard__body">' +
          '<div class="vcard__title">' + esc(v.title || v.filename) + '</div>' +
          '<div class="vcard__meta">' + esc(v.size_h || "") +
            (v.created_at ? ' · ' + esc(String(v.created_at).slice(0, 16)) : "") +
            (v.exists ? "" : " · файл удалён") + '</div>' +
          '<div class="vcard__actions">' +
            (v.exists
              ? '<a class="btn btn--mini btn--accent" href="/api/download/' + esc(v.id) + '">Скачать</a>'
              : "") +
            '<button type="button" class="btn btn--mini btn--ghost vcard__del">Удалить</button>' +
          '</div>' +
        '</div>';

      const play = $(".vcard__play", card);
      const vid = $("video", card);
      if (play && vid) {
        play.addEventListener("click", (e) => {
          e.stopPropagation();
          if (!vid.src) { vid.src = vid.dataset.src; vid.load(); }
          if (vid.paused) { vid.play().catch(() => {}); play.textContent = "❚❚"; }
          else { vid.pause(); play.textContent = "▶"; }
        });
        vid.addEventListener("ended", () => { play.textContent = "▶"; });
        vid.addEventListener("mouseenter", () => {
          if (!vid.src) { vid.src = vid.dataset.src; vid.load(); }
        });
      }

      const del = $(".vcard__del", card);
      if (del) del.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm("Удалить ролик «" + (v.title || v.filename) + "»? Файл тоже будет удалён.")) return;
        try {
          await api("/api/videos/" + encodeURIComponent(v.id), { method: "DELETE" });
          toast("Ролик удалён", "ok");
          renderArchive();
          loadMyStats();
        } catch (err) { toast(err.message, "err"); }
      });

      grid.appendChild(card);
    });
  }

  /* ------------------------------------------------ вкладка «Профиль» */

  async function renderProfileTab() {
    const voicesBox = $("#profileVoiceList");
    const scenBox = $("#profileScenarioList");

    if (!state.user) {
      if (voicesBox) voicesBox.innerHTML = '<div class="hint">Войдите, чтобы увидеть свои голоса.</div>';
      if (scenBox) scenBox.innerHTML = '<div class="hint">Войдите, чтобы увидеть свои сценарии.</div>';
      return;
    }

    // свои клоны голоса
    if (voicesBox) {
      try {
        const d = await api("/api/voices");
        const mine = (d.voices || []).filter((v) => !v.builtin);
        voicesBox.innerHTML = "";
        if (!mine.length) {
          voicesBox.innerHTML = '<div class="hint">Клонов пока нет — запишите голос на вкладке «Сборка».</div>';
        }
        mine.forEach((v) => {
          const row = document.createElement("div");
          row.className = "profile-item";
          row.innerHTML =
            '<span class="profile-item__name">' + esc(v.name) + '</span>' +
            '<span class="profile-item__meta">' + (v.ready ? "готов" : "нет файла") + '</span>' +
            '<button type="button" class="btn btn--mini btn--ghost">Удалить</button>';
          row.querySelector("button").addEventListener("click", async () => {
            if (!confirm("Удалить голос «" + v.name + "»?")) return;
            try {
              await api("/api/voices/" + encodeURIComponent(v.id), { method: "DELETE" });
              toast("Голос удалён", "ok");
              renderProfileTab();
              loadVoices();
              loadMyStats();
            } catch (e) { toast(e.message, "err"); }
          });
          voicesBox.appendChild(row);
        });
      } catch (e) {
        voicesBox.innerHTML = '<div class="hint">Не удалось загрузить голоса: ' + esc(e.message) + '</div>';
      }
    }

    // сохранённые сценарии
    if (scenBox) {
      try {
        const d = await api("/api/scenarios");
        const list = d.scenarios || [];
        scenBox.innerHTML = "";
        if (!list.length) {
          scenBox.innerHTML = '<div class="hint">Сценариев пока нет — сгенерируйте на вкладке «Сборка».</div>';
        }
        list.slice(0, 20).forEach((s) => {
          const row = document.createElement("div");
          row.className = "profile-item";
          const title = (s.title || s.text || "без названия").slice(0, 80);
          row.innerHTML =
            '<span class="profile-item__name">' + esc(title) + '</span>' +
            '<span class="profile-item__meta">' + esc(String(s.created_at || "").slice(0, 16)) + '</span>' +
            '<button type="button" class="btn btn--mini btn--ghost">Удалить</button>';
          row.querySelector("button").addEventListener("click", async () => {
            if (!confirm("Удалить сценарий?")) return;
            try {
              await api("/api/scenarios/" + encodeURIComponent(s.id), { method: "DELETE" });
              toast("Сценарий удалён", "ok");
              renderProfileTab();
            } catch (e) { toast(e.message, "err"); }
          });
          scenBox.appendChild(row);
        });
      } catch (e) {
        scenBox.innerHTML = '<div class="hint">Не удалось загрузить сценарии: ' + esc(e.message) + '</div>';
      }
    }
  }

  async function openFolderPath(path) {
    try {
      const d = await api("/api/open-folder", { method: "POST", body: { path } });
      if (d.ok) toast("Папка открыта в проводнике", "ok");
    } catch (e) {
      toast("Открытие папки доступно только в локальном режиме", "err");
    }
  }

  /* ------------------------------------------------ превью субтитров */

  const SUB_PREVIEW = {
    classic: { label: "Классика", hint: "Слово выскакивает с лёгким увеличением, ключевые — красным." },
    clean: { label: "Чистый", hint: "Все слова белые, появляются по одному, в такт голосу — без вспышек." },
    neon: { label: "Неон", hint: "Белое слово с холодным неоновым свечением." },
    min: { label: "Минимум", hint: "Мелкий текст без обводки — ничего не отвлекает от кадра." },
    cinema: { label: "Кино", hint: "Шрифт с засечками и разрядкой, как в титрах." },
  };

  function initSubtitlePreview() {
    const box = $("#subPreview");
    if (!box) return;
    const word = $("#subPreviewWord");
    const label = $("#subPreviewLabel");
    const hint = $("#subPreviewHint");
    const hidden = $('input[name="sub_style"]');
    const pills = $$(".subtitle-pill[data-sub]");
    if (!word || !pills.length) return;

    const phrase = ["Медведь", "вышел", "к", "воде"];
    let step = 0;

    function show(style) {
      const meta = SUB_PREVIEW[style] || SUB_PREVIEW.classic;
      box.dataset.style = style;
      word.textContent = phrase[step % phrase.length];
      // без reflow браузер не проиграет анимацию заново
      word.classList.remove("is-in", "is-key");
      void word.offsetWidth;
      if (style === "classic" && step % phrase.length === 0) word.classList.add("is-key");
      word.classList.add("is-in");
      if (label) label.textContent = meta.label;
      if (hint) hint.textContent = meta.hint;
      if (hidden) hidden.value = style;
    }

    pills.forEach((p) => p.addEventListener("click", () => {
      pills.forEach((x) => x.classList.toggle("is-active", x === p));
      step = 0;
      show(p.dataset.sub);
    }));

    show(box.dataset.style || "classic");
    setInterval(() => {
      step += 1;
      show(box.dataset.style || "classic");
    }, 720);
  }

  /* ------------------------------------------------ чистота адресной строки */

  /* Enter в поле отправляет форму нативно (метод GET по умолчанию) и дописывает
     в адрес все её поля: ?videoFile=&youtubeUrl=…#assembly. Гасим нативную
     отправку: обработчики submit (initForm, нарезка) продолжают работать, но
     страница не перезагружается с грязным URL. Формы с явным POST/action
     не трогаем. */
  function initAddressBarGuard() {
    document.addEventListener("submit", (e) => {
      const form = e.target;
      if (!(form instanceof HTMLFormElement)) return;
      const method = (form.getAttribute("method") || "get").toLowerCase();
      if (method !== "post" && !form.hasAttribute("action")) e.preventDefault();
    }, true);
  }

  /* ------------------------------------------------ init */

  document.addEventListener("DOMContentLoaded", () => {
    // Один сломанный инициализатор не должен убивать весь интерфейс.
    const steps = [initAddressBarGuard, initCounter, initUpload, initForm, initLogButtons,
      initVoiceTabs, initVoiceSelect, initClone, initNews, initScenarioTools,
      initUserMenu, initResults, restoreScript, initSubtitlePreview];
    for (const step of steps) {
      try { step(); } catch (e) { console.error("[init]", step.name, e); }
    }
    state.mePromise = loadMe();
    state.mePromise.then(() => { loadVoices(); loadMyStats(); });
    connectWS();
  });

  /* сценарий, отправленный из профиля кнопкой «В сборку» */
  function restoreScript() {
    const saved = sessionStorage.getItem("goose_script");
    if (!saved) return;
    sessionStorage.removeItem("goose_script");
    const ta = $("textarea[name=script]");
    if (ta) { ta.value = saved; ta.dispatchEvent(new Event("input")); }
    toast("Сценарий из профиля подставлен", "ok");
  }
})();
