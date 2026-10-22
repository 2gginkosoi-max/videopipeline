/* ============================================================
   ГУСЬ ПЕРЕВОДИЛА — клиентская логика
   ============================================================ */
(function () {
  "use strict";

  const $  = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

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
    }, 3200);
  }

  /* ------------------------------------------------ connection badge */

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
    try {
      ws = new WebSocket(proto + "//" + location.host + "/ws");
    } catch (e) {
      setConn("off", "нет связи");
      return;
    }

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

  /* ------------------------------------------------ terminal log */

  const MAX_LINES = 3000;

  function classify(line) {
    const l = line.toLowerCase();
    if (l.startsWith("====="))   return "term-line--head";
    if (l.includes("[ok]") || l.includes("[done]")) return "term-line--ok";
    if (l.includes("[error]") || l.includes("[block]") || l.includes("traceback")) return "term-line--err";
    if (l.includes("[warn]") || l.includes("[skip]") || l.includes("[archive]")) return "term-line--warn";
    if (l.startsWith("$ "))       return "term-line--cmd";
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

  function setLive(on) {
    const d = $("#liveDot");
    if (d) d.className = "step step--live" + (on ? " is-live" : "");
    const m = $("#logMeta");
    if (m) m.textContent = on ? "выполняется…" : "ожидание запуска";
  }

  /* ------------------------------------------------ websocket messages */

  let currentJob = null;
  let busy = false;

  function handleMsg(msg) {
    switch (msg.kind) {
      case "hello":
        if (Array.isArray(msg.jobs) && msg.jobs.length) {
          $("#statJobs").textContent = msg.jobs.length;
        }
        break;

      case "job_start":
        currentJob = msg.job_id;
        setLive(true);
        setBusy(true);
        appendLog("");
        appendLog(msg.cmd);
        break;

      case "log":
        appendLog(msg.line);
        break;

      case "job_end": {
        setLive(false);
        setBusy(false);
        appendLog("");
        appendLog(msg.status === "done"
          ? "✓ Конвейер завершён успешно"
          : "✗ Конвейер завершился с ошибкой (код " + msg.returncode + ")");
        if (msg.status === "done") {
          toast("Ролик готов — смотрите раздел «Готовые ролики»", "ok");
          refreshStats();
        } else {
          toast("Ошибка в конвейере — смотрите лог", "err");
        }
        currentJob = null;
        break;
      }
    }
  }

  /* ------------------------------------------------ busy state */

  function setBusy(on) {
    busy = on;
    const btn = $("#runBtn");
    if (!btn) return;
    btn.disabled = on;
    btn.classList.toggle("is-busy", on);
    $(".btn__label", btn).textContent = on ? "Собираем…" : "Собрать ролик";
    $(".btn__sub", btn).textContent = on
      ? "не закрывайте вкладку"
      : "~5–8 минут · F5-TTS + FFmpeg";
  }

  /* ------------------------------------------------ script counter */

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

  /* ------------------------------------------------ drag & drop upload */

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
      drop.addEventListener(ev, (e) => {
        e.preventDefault();
        drop.classList.add("is-over");
      })
    );
    ["dragleave", "drop"].forEach(ev =>
      drop.addEventListener(ev, (e) => {
        e.preventDefault();
        if (ev === "dragleave" && drop.contains(e.relatedTarget)) return;
        drop.classList.remove("is-over");
      })
    );

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
        const r = await fetch("/api/upload", { method: "POST", body: fd });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || "ошибка загрузки");
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

  /* ------------------------------------------------ submit */

  function initForm() {
    const form = $("#runForm");
    if (!form) return;

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (busy) return;

      const fd = new FormData(form);
      const payload = {};
      for (const [k, v] of fd.entries()) payload[k] = v;
      for (const el of $$("input[type=checkbox]", form)) {
        payload[el.name] = el.checked;
      }

      if (!payload.script && !payload.asset && !payload.video_url) {
        toast("Укажите сценарий или источник b-roll", "err");
        return;
      }

      setBusy(true);
      setLive(true);
      appendLog("");
      appendLog("● Запуск конвейера…");

      try {
        const r = await fetch("/api/process", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || "не удалось запустить");
        currentJob = d.job_id;
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

  /* ------------------------------------------------ log buttons */

  function initLogButtons() {
    const copy = $("#copyLog");
    if (copy) copy.addEventListener("click", async () => {
      const body = $("#logBody");
      if (!body) return;
      const text = Array.from(body.querySelectorAll(".term-line"))
        .map(n => n.textContent).join("\n");
      try {
        await navigator.clipboard.writeText(text);
        toast("Лог скопирован", "ok");
      } catch (e) {
        toast("Не удалось скопировать", "err");
      }
    });

    const clr = $("#clearLog");
    if (clr) clr.addEventListener("click", () => {
      const body = $("#logBody");
      if (!body) return;
      body.innerHTML = '<div class="terminal__empty">// лог очищен</div>';
    });
  }

  /* ------------------------------------------------ results page */

  function initResults() {
    const reload = $("#reload");
    if (reload) reload.addEventListener("click", () => location.reload());

    const openFolder = $("#openFolder");
    if (openFolder) openFolder.addEventListener("click", async () => {
      try {
        const r = await fetch("/api/open-folder", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: "D:\\AI\\VIDEO_PIPELINE\\output" })
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || "не удалось открыть");
        toast("Папка открыта в проводнике", "ok");
      } catch (err) {
        toast("Открытие папки доступно только в локальном режиме", "err");
      }
    });

    $$("[data-open]").forEach(btn =>
      btn.addEventListener("click", async () => {
        try {
          const r = await fetch("/api/open-folder", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: btn.dataset.open })
          });
          const d = await r.json();
          if (!r.ok) throw new Error(d.detail || "ошибка");
          toast("Папка открыта", "ok");
        } catch (err) {
          toast("Открытие папки доступно только в локальном режиме", "err");
        }
      })
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

    // Ленивая подгрузка метаданных видео — страница открывается мгновенно
    if ("IntersectionObserver" in window) {
      const io = new IntersectionObserver((entries) => {
        entries.forEach((e) => {
          if (!e.isIntersecting) return;
          const v = e.target;
          if (v.dataset.src && !v.src) {
            v.src = v.dataset.src;
            v.load();
          }
          io.unobserve(v);
        });
      }, { rootMargin: "300px" });
      $$(".vcard__thumb video").forEach((v) => io.observe(v));
    } else {
      $$(".vcard__thumb video").forEach((v) => {
        v.src = v.dataset.src;
      });
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

  /* ------------------------------------------------ stats */

  async function refreshStats() {
    try {
      const r = await fetch("/api/results");
      const d = await r.json();
      const el = $("#statVideos");
      if (el) el.textContent = d.videos.length;
    } catch (e) {}
  }

  /* ------------------------------------------------ init */

  document.addEventListener("DOMContentLoaded", () => {
    initCounter();
    initUpload();
    initForm();
    initLogButtons();
    initResults();
    refreshStats();
    connectWS();
  });
})();
