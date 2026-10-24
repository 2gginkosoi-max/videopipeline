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
      $("#userName").textContent = state.user.username;
      $("#userAvatar").textContent = state.user.username.slice(0, 1).toUpperCase();
      loadMyStats();
    } else {
      if (menu) menu.hidden = true;
      if (loginBtn) loginBtn.hidden = false;
    }
  }

  async function loadMyStats() {
    if (!state.user) return;
    try {
      const v = await api("/api/videos");
      const el = $("#statVideos");
      if (el) el.textContent = v.videos.length;
    } catch (e) {}
    try {
      const v = await api("/api/voices");
      const mine = v.voices.filter(x => !x.builtin);
      const el = $("#statVoices");
      if (el) el.textContent = mine.length;
    } catch (e) {}
  }

  function initUserMenu() {
    const btn = $("#userBtn");
    const pop = $("#userPop");
    if (btn && pop) {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        pop.hidden = !pop.hidden;
      });
      document.addEventListener("click", () => { pop.hidden = true; });
    }
    const out = $("#logoutBtn");
    if (out) out.addEventListener("click", async () => {
      await api("/api/auth/logout", { method: "POST" });
      location.reload();
    });
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

  async function previewVoice(id) {
    if (!state.user) { toast("Войдите, чтобы слушать голоса", "err"); return; }
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
    $(".btn__label", btn).textContent = on ? "Собираем…" : "Собрать ролик";
    $(".btn__sub", btn).textContent = on
      ? "не закрывайте вкладку" : "~5–8 минут · F5-TTS + FFmpeg";
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
        setLive(true, "выполняется…");
        setBusy(true);
        appendLog("");
        appendLog(msg.cmd);
        break;

      case "log":
        appendLog(msg.line);
        break;

      case "video_ready":
        appendLog("");
        appendLog("✓ Ролик сохранён в профиль: " + msg.title);
        loadMyStats();
        break;

      case "job_end": {
        setLive(false, msg.status === "done" ? "готово" : "ошибка");
        setBusy(false);
        appendLog("");
        appendLog(msg.status === "done"
          ? "✓ Конвейер завершён успешно"
          : "✗ Конвейер завершился с ошибкой (код " + msg.returncode + ")");
        toast(msg.status === "done"
          ? "Ролик готов — он в вашем профиле"
          : "Ошибка в конвейере — смотрите лог", msg.status === "done" ? "ok" : "err");
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
      $("#scriptLen").textContent = v.length;
      $("#scriptWords").textContent = v ? v.split(/\s+/).length : 0;
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
        $("textarea[name=script]").value = payload.script;
        await api("/api/scenarios", {
          method: "POST",
          body: { text: payload.script, title: payload.topic || "", source: "used" }
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
      const text = Array.from(body.querySelectorAll(".term-line"))
        .map(n => n.textContent).join("\n");
      try { await navigator.clipboard.writeText(text); toast("Лог скопирован", "ok"); }
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
    if (reload) reload.addEventListener("click", () => location.reload());

    const openFolder = $("#openFolder");
    if (openFolder) openFolder.addEventListener("click", () => openFolderPath(
      "D:\\AI\\VIDEO_PIPELINE\\output"));

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

  async function openFolderPath(path) {
    try {
      const d = await api("/api/open-folder", { method: "POST", body: { path } });
      if (d.ok) toast("Папка открыта в проводнике", "ok");
    } catch (e) {
      toast("Открытие папки доступно только в локальном режиме", "err");
    }
  }

  /* ------------------------------------------------ чистота адресной строки */

  /* Ни одна страница конвейера не читает query-параметры: состояние живёт
     в памяти/sessionStorage. Поэтому всё, что браузер дописал в URL сам
     (например, при нативной GET-отправке формы), — мусор, который портит
     ссылку на сайт. Чистим его, оставляя только путь и якорь раздела. */
  function cleanAddressBar() {
    if (!location.search) return;
    const cleaned = location.pathname + location.hash;
    if (location.href === location.origin + cleaned) return;
    history.replaceState(null, "", cleaned);
  }

  /* Enter в текстовом поле отправляет форму нативно (метод GET по умолчанию)
     и дописывает в адресную строку все её поля: ?videoFile=&youtubeUrl=…#assembly.
     Гасим нативную отправку: обработчики submit (initForm, логин) продолжают
     работать, но страница больше не перезагружается с грязным URL. */
  function initAddressBarGuard() {
    cleanAddressBar();

    document.addEventListener("submit", (e) => {
      const form = e.target;
      if (!(form instanceof HTMLFormElement)) return;
      const method = (form.getAttribute("method") || "get").toLowerCase();
      // Формы с явным POST/action — это не наша история, их не трогаем.
      if (method !== "post" && !form.hasAttribute("action")) e.preventDefault();
    }, true);
  }

  /* ------------------------------------------------ init */

  document.addEventListener("DOMContentLoaded", () => {
    initAddressBarGuard();
    initCounter();
    initUpload();
    initForm();
    initLogButtons();
    initVoiceTabs();
    initClone();
    initNews();
    initScenarioTools();
    initUserMenu();
    initResults();
    restoreScript();
    loadMe().then(() => { loadVoices(); loadMyStats(); });
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
