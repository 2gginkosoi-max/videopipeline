# Автопубликация Shorts на YouTube через n8n

Схема: **наш Python-пайплайн → вебхук n8n → загрузка на YouTube**.

```
publish.py  ──POST JSON──►  n8n Webhook (/webhook/publish-short)
                                 │
                                 ├─ Read Video   (читает final_video.mp4 с диска)
                                 └─ YouTube Upload (загружает как Unlisted)
```

---

## 1. Что уже готово

| Файл | Назначение |
|------|-----------|
| `D:\AI\VIDEO_PIPELINE\n8n\youtube_autopost_workflow.json` | Workflow для импорта в n8n |
| `D:\AI\VIDEO_PIPELINE\publish.py` | Отправка ролика + метаданных на вебхук |
| `D:\AI\F5-TTS\title.txt` | Заголовок (используется автоматически) |
| `D:\AI\F5-TTS\description.txt` | Описание |
| `D:\AI\F5-TTS\tags.txt` | Теги |

Workflow уже импортирован в твою базу n8n (workflow «YouTube Shorts Autopost»).

---

## 2. Разовая настройка YouTube OAuth2 (делает пользователь)

### 2.1 Google Cloud Console
1. Открой https://console.cloud.google.com/ → создай проект (напр. `shorts-autopost`).
2. **APIs & Services → Library** → найди **YouTube Data API v3** → **Enable**.
3. **APIs & Services → OAuth consent screen**:
   - User type: **External** → Create.
   - App name, support email, developer email → Save.
   - **Audience → Test users** → добавь свой Google-аккаунт (канал).
   - (Пока приложение в режиме Testing, refresh-token живёт 7 дней. Чтобы не переподключаться каждую неделю — нажми **Publish app** в разделе Audience.)
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: **Web application**.
   - **Authorized redirect URI** (ровно так):
     ```
     http://localhost:5678/rest/oauth2-credential/callback
     ```
   - Create → скопируй **Client ID** и **Client Secret**.

### 2.2 n8n
1. Запусти n8n (см. раздел 3).
2. Открой http://localhost:5678 → workflow **YouTube Shorts Autopost**.
3. Двойной клик по узлу **YouTube Upload** → в поле Credential выбери **Create new** → **YouTube OAuth2 API**.
4. Вставь **Client ID** и **Client Secret** → **Sign in with Google** → разреши доступ каналу.
5. Сохрани узел (Save).
6. Активируй workflow, чтобы включить «боевой» вебхук `/webhook/publish-short`:
   - **Через CLI (надёжно в n8n 2.42):**
     ```powershell
     n8n publish:workflow --id=YtShortsAutopst1
     ```
     затем **перезапусти n8n** (вебхуки регистрируются при старте).
   - **Через UI:** тумблер **Active** справа сверху. В версии 2.42 он иногда не завершает активацию (workflow остаётся `active=0`) — тогда используй CLI-вариант выше.

> Пока workflow не активен/не опубликован, работает только тестовый адрес `/webhook-test/publish-short` при нажатии «Listen for test event».
> После перезапуска n8n боевой вебхук регистрируется **не сразу** — подожди ~15 секунд, прежде чем публиковать (иначе `404 Cannot POST /webhook/publish-short`).

---

## 3. Запуск n8n

```powershell
n8n
# откроется http://localhost:5678
```
Данные хранятся в `D:\AI\n8n-data` (переменная `N8N_USER_FOLDER`).

Фоновый запуск без окна:
```powershell
Start-Process -WindowStyle Hidden n8n
```

### Важно: доступ к файлам (иначе «Access to the file is not allowed»)
В n8n ≥ 2.42 доступ к файловой системе по умолчанию ограничен только папкой `~/.n8n-files`, поэтому узел **Read Video** не может прочитать ролик из `D:\AI\VIDEO_PIPELINE`.

Разреши нужные папки (на этой машине уже настроено, действует постоянно):
```powershell
setx N8N_RESTRICT_FILE_ACCESS_TO "D:\AI\VIDEO_PIPELINE;~/.n8n-files"
```
После `setx` **перезапусти n8n** — текущий процесс новую переменную не подхватит.
(Несколько путей разделяются `;`. Список полностью **заменяет** дефолт, поэтому `~/.n8n-files` включён явно.)

---

## 4. Публикация ролика

После того как пайплайн собрал `final_video.mp4`:

```powershell
& "D:\AI\python310\python.exe" "D:\AI\VIDEO_PIPELINE\publish.py" `
  --video "D:\AI\VIDEO_PIPELINE\output\final_video.mp4" `
  --privacy unlisted `
  --category 24
```

Заголовок/описание/теги подтянутся из `title.txt` / `description.txt` / `tags.txt`.
Рядом с роликом появится `publish.json`, а n8n загрузит видео на YouTube.

> Вебхук отвечает `200 {"message":"Workflow was started"}` **сразу** (режим onReceived) — это значит «принято», а не «загружено». Итог (video ID) смотри во вкладке **Executions** в n8n. Ролик открывается по `https://youtu.be/<videoId>`.

Проверить без отправки (только пишет `publish.json`):
```powershell
... publish.py --video "...\final_video.mp4" --no-post
```

### Категории (categoryId)
| id | Категория |
|----|-----------|
| 24 | Entertainment (по умолчанию) |
| 2  | Autos & Vehicles |
| 25 | News & Politics |
| 28 | Science & Technology |
| 22 | People & Blogs |

---

## 5. Ручная проверка вебхука (PowerShell)

```powershell
$body = @{
  videoPath    = "D:/AI/VIDEO_PIPELINE/output/final_video.mp4"
  title        = "ТЕСТ #shorts"
  description  = "проверка"
  tags         = "shorts, тест"
  privacyStatus= "unlisted"
  categoryId   = "24"
} | ConvertTo-Json -Compress

Invoke-RestMethod -Uri "http://localhost:5678/webhook/publish-short" `
  -Method Post -ContentType "application/json; charset=utf-8" `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
```

---

## 6. Ограничения и заметки
- **Квота YouTube API:** 10 000 единиц/день; одна загрузка = 1600 единиц → **~6 загрузок в день**. На следующий день сбрасывается.
- Shorts определяется автоматически (вертикальное видео ≤3 мин + `#shorts` в заголовке/описании) — у нас и то и другое есть.
- Ошибки загрузки видны в n8n: вкладка **Executions**.
- Вебхук слушает только `localhost` (наружу не выставлен). Если понадобится доступ извне — добавляй авторизацию (Header Auth) в узел Webhook.
