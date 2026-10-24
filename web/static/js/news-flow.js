/* news-flow.js — шаги 1–2 конвейера: поиск новостей и источник видео.
   ВАЖНО: подключать ПОСЛЕ app.js.
   Шаг 1 ходит в реальный API (/api/news/search + /api/news),
   шаг 2 скачивает b-roll через /api/broll/check. */
(function () {
  "use strict";

  var state = { posts: [], loading: false };
  var currentNews = null;
  /* Что видно в кадре — подпись b-roll от сервера (BLIP). */
  var videoDesc = "";
  /* Уже показанные ссылки: повторный поиск не подсовывает те же посты. */
  var seen = Object.create(null);

  function q(sel, root) { return (root || document).querySelector(sel); }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function unlockSteps() {
    Array.prototype.forEach.call(
      document.querySelectorAll("#runForm .step-card.is-locked"),
      function (el) { el.classList.remove("is-locked"); }
    );
  }

  function bind() {
    var searchBtn = document.getElementById("searchNews");
    var results = document.getElementById("newsResults");
    var list = document.getElementById("newsList");
    var preview = document.getElementById("videoPreview");
    if (!searchBtn || !results || !list || !preview) return;

    var step1 = results.closest(".step-card");
    var step2 = preview.closest(".step-card");

    function titleOf(item) {
      return (item && (item.title_ru || item.title)) || "";
    }

    function renderNews(posts) {
      list.innerHTML = "";
      posts.forEach(function (item, i) {
        var card = document.createElement("div");
        card.className = "news-card";
        card.dataset.id = item.id || String(i);
        card.tabIndex = 0;
        card.setAttribute("role", "link");
        if (item.link) card.title = "Открыть пост: " + (item.title || "");
        card.innerHTML =
          '<span class="news-card__num">' + (i + 1) + '</span>' +
          '<span class="news-card__title">' +
            '<span class="news-card__text">' + esc(titleOf(item).slice(0, 240)) + '</span>' +
            '<span class="news-card__meta">r/' + esc(item.sub || "") +
              (item.video_url ? ' · видео' : ' · без видео') + '</span>' +
          '</span>' +
          '<span class="news-card__side">' +
            '<span class="news-card__open">↗</span>' +
            '<span class="news-card__pick" role="button" tabindex="0">Выбрать</span>' +
          '</span>';

        /* клик по новости — открываем сам пост Reddit в новой вкладке */
        function openLink(e) {
          if (e) e.preventDefault();
          if (item.link) window.open(item.link, "_blank", "noopener");
        }
        card.addEventListener("click", openLink);
        card.addEventListener("keydown", function (e) {
          if (e.key === "Enter" || e.key === " ") openLink(e);
        });

        /* отдельная кнопка — взять новость в работу (шаги 2–5) */
        var pick = card.querySelector(".news-card__pick");
        function takeIt(e) {
          e.preventDefault();
          e.stopPropagation();
          selectNews(item, card);
        }
        pick.addEventListener("click", takeIt);
        pick.addEventListener("keydown", function (e) {
          if (e.key === "Enter" || e.key === " ") takeIt(e);
        });

        list.appendChild(card);
      });
    }

    function selectNews(item, card) {
      Array.prototype.forEach.call(list.children, function (c) {
        c.classList.remove("is-selected");
      });
      card.classList.add("is-selected");

      /* Шаг 1: помечаем выбранным и сворачиваем список */
      if (step1) {
        step1.classList.add("is-done");
        var subtitle = q(".step-card__titles p", step1);
        if (subtitle) subtitle.textContent = "Выбрано: " + titleOf(item);
      }
      results.style.display = "none";

      /* Шаг 3: запоминаем новость и подставляем её в «Тему ролика» */
      currentNews = item;
      videoDesc = "";
      var topicInput = document.querySelector('#runForm input[name="topic"]');
      if (topicInput && !topicInput.value.trim()) topicInput.value = titleOf(item);

      /* Шаг 2: кладём b-roll в форму конвейера */
      var videoInput = document.getElementById("videoUrlInput");
      var assetInput = document.getElementById("assetInput");
      if (videoInput) videoInput.value = item.video_url || "";
      if (assetInput) assetInput.value = "";

      preview.classList.remove("has-video");
      preview.classList.add("is-loaded");
      preview.innerHTML =
        '<div class="video-preview-container__inner">' +
          '<span class="video-preview-container__icon">▶</span>' +
          '<span>Видео для новости «' + esc(titleOf(item)) + '»</span>' +
          '<span class="broll-status" id="brollStatus">' +
            (item.video_url ? "Источник: " + esc(item.video_url) : "У поста нет видео") +
          '</span>' +
          (item.video_url
            ? '<button type="button" class="btn btn--mini btn--accent" id="brollCheck">Проверить видео</button>'
            : '') +
        '</div>';
      if (step2) step2.classList.add("is-done");

      var check = document.getElementById("brollCheck");
      if (check) check.addEventListener("click", function () { checkBroll(item, check); });

      unlockSteps();
    }

    /* Что в кадре: кадры подписывает сервер, поэтому опрашиваем готовность. */
    function showBrollDesc(text) {
      videoDesc = text || "";
      var el = document.getElementById("brollDesc");
      if (!el || !videoDesc) return;
      el.hidden = false;
      el.textContent = "В кадре: " + videoDesc;
    }

    function pollBrollDesc(url, left) {
      var name = String(url || "").split("/").pop();
      if (!name) return;
      if (left == null) left = 25;
      fetch("/api/broll/desc/" + encodeURIComponent(name))
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d && d.ready && d.desc) { showBrollDesc(d.desc); return; }
          if (left <= 0) return;
          setTimeout(function () { pollBrollDesc(url, left - 1); }, 1500);
        })
        .catch(function () {
          if (left > 0) setTimeout(function () { pollBrollDesc(url, left - 1); }, 2500);
        });
    }

    function checkBroll(item, btn) {
      var status = document.getElementById("brollStatus");
      btn.disabled = true;
      btn.textContent = "Скачиваем…";
      if (status) status.textContent = "Скачиваем b-roll с Reddit… 5–20 с";

      fetch("/api/broll/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_url: item.video_url })
      })
        .then(function (r) {
          return r.json().then(function (d) { return { ok: r.ok, d: d }; });
        })
        .then(function (res) {
          if (!res.ok || !res.d.ok) throw new Error(res.d.detail || "не удалось скачать");
          var d = res.d;
          preview.innerHTML =
            '<video class="video-preview-container__video" src="' + d.url +
              '" controls playsinline preload="metadata"></video>' +
            '<div class="video-preview-container__caption">' +
              esc(titleOf(item)) + ' · ' + d.width + '×' + d.height +
              ' · ' + d.duration + ' с · ' + (d.size / 1048576).toFixed(1) + ' МБ' +
            '</div>' +
            '<div class="broll-desc" id="brollDesc" hidden></div>';
          preview.classList.add("is-loaded", "has-video");
          var cap = q(".video-preview-container__caption", preview);
          if (cap) cap.dataset.src = d.url;
          if (d.desc) showBrollDesc(d.desc);
          else pollBrollDesc(d.url);
          unlockSteps();
        })
        .catch(function (err) {
          if (status) status.textContent = "Ошибка: " + err.message;
          btn.disabled = false;
          btn.textContent = "Повторить";
        });
    }

    /* Ждём, пока кэш обновится: cache_news переписывает строки с новым created_at. */
    /* ---------- шаг 3: варианты сценария ---------- */

    function renderVariants(variants, descText) {
      var box = document.getElementById("variants");
      if (!box) return;
      box.hidden = false;
      box.innerHTML = "";
      if (descText) {
        var note = document.createElement("div");
        note.className = "variants-note";
        note.textContent = "Сценарий написан по видео: " + descText;
        box.appendChild(note);
      }
      if (!variants.length) {
        var empty = document.createElement("div");
        empty.className = "hint";
        empty.textContent = "Вариантов нет";
        box.appendChild(empty);
        return;
      }
      variants.forEach(function (v, i) {
        var el = document.createElement("div");
        el.className = "variant";
        el.innerHTML =
          '<div class="variant__title">' + esc(v.title || ("Вариант " + (i + 1))) + '</div>' +
          (v.hook ? '<div class="variant__hook">хук: ' + esc(v.hook) + '</div>' : "") +
          '<div class="variant__text">' + esc(v.script || "") + '</div>';
        var b = document.createElement("button");
        b.type = "button";
        b.className = "btn btn--mini btn--accent";
        b.textContent = "Взять этот";
        b.addEventListener("click", function () { takeVariant(v, el); });
        el.appendChild(b);
        box.appendChild(el);
      });
    }

    function takeVariant(v, el) {
      var ta = document.querySelector('#runForm textarea[name="script"]');
      if (ta) {
        ta.value = v.script || "";
        ta.dispatchEvent(new Event("input", { bubbles: true }));
      }
      Array.prototype.forEach.call(
        document.querySelectorAll("#variants .variant"),
        function (n) { n.classList.remove("is-selected"); }
      );
      if (el) el.classList.add("is-selected");
      var step3 = ta && ta.closest(".step-card");
      if (step3) step3.classList.add("is-done");
    }

    async function generateVariants(btn) {
      var box = document.getElementById("variants");
      if (!currentNews) {
        if (box) {
          box.hidden = false;
          box.innerHTML = '<div class="hint">Сначала выберите новость в шаге 1</div>';
        }
        return;
      }
      if (btn.disabled) return;
      btn.disabled = true;
      var label = btn.textContent;
      btn.textContent = "Пишем…";
      if (box) {
        box.hidden = false;
        box.innerHTML = '<div class="hint">Смотрим видео и пишем 3 варианта… 20–60 с</div>';
      }

      try {
        var res = await fetch("/api/news/scenario", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: currentNews.title || "",
            title_ru: currentNews.title_ru || "",
            sub: currentNews.sub || "",
            context: currentNews.context || "",
            link: currentNews.link || "",
            video_url: currentNews.video_url || ""
          })
        });
        var d = await res.json();
        if (!res.ok || !d.ok) throw new Error(d.detail || "LLM не ответил");
        if (d.video) showBrollDesc(d.video);
        renderVariants(d.variants || [], d.video || "");
      } catch (err) {
        if (box) box.innerHTML = '<div class="hint">Ошибка: ' + esc(err.message) + '</div>';
      } finally {
        btn.disabled = false;
        btn.textContent = label;
      }
    }

    /* Ждём news_end по WebSocket: сервер пришлёт именно свежую выдачу.
       null — не дождались (таймаут/ошибка WS). */
    function waitForNewsEnd(timeoutMs) {
      return new Promise(function (resolve) {
        var ws = null, done = false;
        var timer = setTimeout(function () { finish(null); }, timeoutMs || 120000);

        function finish(value) {
          if (done) return;
          done = true;
          clearTimeout(timer);
          try { if (ws) ws.close(); } catch (e) {}
          resolve(value);
        }

        try {
          ws = new WebSocket((location.protocol === "https:" ? "wss:" : "ws:") +
                             "//" + location.host + "/ws");
        } catch (e) {
          finish(null);
          return;
        }

        ws.onmessage = function (ev) {
          try {
            var m = JSON.parse(ev.data);
            if (m.kind === "news_end") finish(m);
          } catch (e) {}
        };
        ws.onerror = function () { finish(null); };
      });
    }

    async function onSearchClick(event) {
      if (event) event.stopImmediatePropagation();
      results.style.display = "block";
      if (state.loading) return;

      var hint = document.getElementById("newsHint");

      var me = await fetch("/api/auth/me")
        .then(function (r) { return r.json(); })
        .catch(function () { return {}; });
      if (!me || !me.user) {
        if (hint) hint.textContent = "Войдите, чтобы искать новости";
        results.style.display = "none";
        return;
      }

      state.loading = true;
      searchBtn.disabled = true;
      var label = searchBtn.textContent;
      searchBtn.textContent = "Ищем…";
      if (hint) hint.textContent = "Ищем свежие посты в Reddit (до 60 с)…";
      list.innerHTML = '<div class="hint">Ищем новые видео по всему Reddit…</div>';

      try {
        var pending = waitForNewsEnd(120000);
        await new Promise(function (r) { setTimeout(r, 400); });   // даём WS подключиться

        await fetch("/api/news/search", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: "new", force: true })
        });

        var msg = await pending;

        if (msg && msg.ok === false) {
          list.innerHTML = '<div class="hint">' + esc(msg.error || "Reddit не ответил") + '</div>';
          return;
        }

        var posts = msg
          ? (msg.posts || [])
          : await fetch("/api/news")
              .then(function (r) { return r.json(); })
              .then(function (d) { return d.posts || []; })
              .catch(function () { return []; });

        var unseen = posts.filter(function (p) { return p.link && !seen[p.link]; });
        var fresh = unseen.slice(0, 25);
        fresh.forEach(function (p) { seen[p.link] = true; });
        state.posts = fresh;

        if (!posts.length) {
          list.innerHTML = '<div class="hint">Reddit не отдал новые посты — вероятно, сработал лимит запросов. Попробуйте через минуту.</div>';
          return;
        }
        if (!fresh.length) {
          list.innerHTML = '<div class="hint">Все найденные посты уже показаны. Новые подтянутся в течение минуты.</div>';
          return;
        }
        renderNews(fresh);
        if (hint) hint.textContent = "Свежих новостей: " + fresh.length;
      } catch (err) {
        list.innerHTML = '<div class="hint">Ошибка поиска: ' + esc(err.message) + '</div>';
      } finally {
        state.loading = false;
        searchBtn.disabled = false;
        searchBtn.textContent = label;
      }
    }

    /* app.js уже повесил на эту кнопку свой обработчик (он ищет #newsSubs,
       которого больше нет) — пересоздаём узел и оставляем только наш. */
    var fresh = searchBtn.cloneNode(true);
    searchBtn.replaceWith(fresh);
    fresh.addEventListener("click", onSearchClick);

    /* Шаг 3: у app.js на этой кнопке висит prompt() — снимаем его клон-приёмом
       и генерируем варианты по выбранной новости. */
    var genBtn = document.getElementById("genScenario");
    if (genBtn) {
      var freshGen = genBtn.cloneNode(true);
      genBtn.replaceWith(freshGen);
      freshGen.addEventListener("click", function (event) {
        if (event) event.stopImmediatePropagation();
        generateVariants(freshGen);
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
