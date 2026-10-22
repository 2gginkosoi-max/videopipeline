# Reddit-исследование: что стреляет на YouTube (для второго канала, US-аудитория)

Дата: 15.10.2026
Источник: Reddit (r/PartneredYoutube, r/NewTubers, r/ContentCreators, r/SmallYoutubers, r/youtubegaming, r/Shorts, r/LetsPlay, r/interestingasfuck, r/Damnthatsinteresting, r/nextfuckinglevel, r/BeAmazed, r/oddlysatisfying)
Метод: shreddit HTML-API Reddit (работает без логина) + чтение тредов через встроенный браузер OpenChamber.

---

## 1. ГЛАВНЫЕ ФОРУМЫ (где сидят американские ютуберы)

| Сабреддит | О чём | Размер/активность |
|---|---|---|
| **r/PartneredYoutube** | Монетизированные каналы: деньги, RPM, нарушения, апдейты YouTube | Самый «профессиональный», топ за год |
| **r/NewTubers** | Новички: первые 1000 сабов, алгоритм, ошибки | Очень активный, много мифов |
| **r/SmallYoutubers** | Маленькие каналы, milestones, CTR, удержание | Живой, много «что сработало» |
| **r/youtubers** | Общие вопросы: оборудование, монтаж, права | Средний |
| **r/ContentCreators** | Кросс-платформенно: YouTube+IG+TikTok, ниши, деньги | Много про faceless и монетизацию |
| **r/youtubegaming** | Игровые каналы, Shorts-гайды | Есть сильный гайд по Shorts |
| **r/LetsPlay** | Летсплеи, long-form | Поменьше |
| **r/Shorts** | Сам сабреддит Shorts (контент, не стратегия) | Шумный, малополезный для стратегии |

**Дополнительно для идей контента (то, что заходит в US):** r/interestingasfuck, r/Damnthatsinteresting, r/nextfuckinglevel, r/BeAmazed, r/oddlysatisfying, r/PublicFreakout.

---

## 2. ЧТО РЕАЛЬНО СТРЕЛЯЕТ — по прочитанным топ-тредам

### 2.1. Пять «правил», которые на самом деле не работают (r/NewTubers, топ месяца)
Тред `Five YouTube "rules" this sub repeats constantly that aren't actually true` — 17660 символов, живое обсуждение.

1. **«Новые каналы в shadowban»** — нет shadowban. Это **cold start**: у YouTube нет данных, кому показывать. Наполняется загрузками + временем, не «исправляется».
2. **«Нужно доказать, что ты не бот»** — нет probation-периода. YouTube просто не может рекомендовать видео, пока зрители не отреагировали. **Постить каждый день не ускоряет это — ускоряют данные.**
3. **«Теги — как тебя находят»** — теги играют минимальную роль уже годы. Работают **название, превью и тема**.
4. **«Не пости в [конкретное время], иначе похоронят»** — нет штрафа за время. Время влияет только на то, бодрствует ли твоя аудитория.
5. **«Удаляй флоп-видео, чтобы не тянули канал вниз»** — **не удалять.** Каждое видео тестируется отдельно. В комментариях: флоп-видео через 18 месяцев внезапно взяло 400k просмотров; другое через 5 лет прыгнуло с 60k до 12 млн.

**Вывод для канала:** не удалять старьё, не гнаться за временем постинга, вкладываться в превью+заголовок+тему, а не в теги.

### 2.2. Формула вирусного Shorts (r/youtubegaming, топ года)
Тред `I've hit 599M+ shorts views in under a year` (mblaze111, 21 канал, 17 взлетели).

Заявленная схема кадра:
```
1. НАЗВАНИЕ ИГРЫ/ТЕМЫ — СВЕРХУ
2. ЗАГОЛОВОК SHORTS — ПОД НИМ
3. ВИДЕО — В КВАДРАТЕ (не на весь экран!)
4. КОРОТКИЕ ШАГИ/ГАЙД — ПОД ВИДЕО
```
Плюс советы: аватар профиля важнее, чем кажется; старые аккаунты пуш быстрее; регулярность важнее, чем думают.

**Важная поправка из комментариев (модератор, YT Product Expert):** часть заявленных 599M — это просмотры **чужих видео, где использована его музыка** (Shorts revenue share). То есть формула «квадрат+шаги» реальна, но цифра успеха завышена. **Не копировать слепо — тестировать.**

**Вывод:** формат «текст сверху + видео в квадрате + текст снизу» — рабочий приём для обучающего/игрового Shorts. Это можно взять в дизайн-паттерн второго канала (отдельно от нашего текущего full-screen формата).

### 2.3. Что заходит в faceless-нишах (r/ContentCreators, топ года)
Тред `I spent months researching the faceless channel niches that are ACTUALLY printing money` — прочитан целиком.

| Ниша | Доход/мес (по автору) | Инструменты | Риски |
|---|---|---|---|
| **Movie Recap / Explanation** | $2k–35k | Whisper, Premiere/CapCut, ChatGPT | Высокий: copyright, DMCA |
| **Long-form Reddit Stories** (лучшая) | $5k–88k | PRAW, CapCut/Resolve, yt-dlp, Figma, Taletok (авто) | Средний: нужен объём, авто-постинг 6×/день |
| **4chan Greentext** | $1k–4k | 4chan scraper, CapCut, ElevenLabs | Мало конкурентов, но NSFW-риск |
| **Creepy Cartoon AI Shorts** | $1k–2k | Pika/Runway, CapCut, ElevenLabs, Topaz | Высокая сатурация, RPM падают |
| **Horror Storytelling** | $20k–110k | Pexels/Pixabay, Resolve, свой голос | Эвергрин, растёт к Хэллоуину |

**Ключевой инсайт автора:** автоматизация превращает «игру в виральность» в **игру чисел** — те, кто постит 6 раз в день, зарабатывают просто по закону средних.

**Вывод для второго канала:** Reddit-stories long-form + Creepy AI Shorts — самые низкопороговые для старта. Reddit-stories имеет лучший доход/риск при автоматизации.

### 2.4. Аудио как приём (r/youtubegaming, комментарии)
Из треда про 599M:
> «YT считает использование твоего звука другими видео как метрику Shorts»
> → вывод комментатора: **делать шортсы с уникальными звуками** (своя музыка/звук), чтобы попадать в чужую статистику и получать revenue share.

**Это прямой аргумент за наши локально-генерируемые аудио-ассеты** (`audio_assets.py`, boom/riser/whoosh) — они уникальны, и их может использовать кто-то ещё.

### 2.5. Превью Shorts теперь важны (r/PartneredYoutube, топ месяца)
Тред `Since custom thumbnails got available for shorts, did you find them important just like with long-form videos?`

Из обсуждения в r/youtubegaming: кастомное превью Shorts можно поставить **только в мобильном приложении YouTube** (в Studio — нет; три точки на видео → Edit → нажать на видео сверху). Многие не знают.

**Вывод:** для US-канала обязательно ставить кастомные превью шортсов — это недоиспользованный рычаг.

---

## 3. ПРИЁМЫ И ТАКТИКИ, КОТОРЫЕ ПОВТОРЯЮТСЯ

Собрано из заголовков и прочитанных тредов r/NewTubers, r/PartneredYoutube, r/SmallYoutubers:

- **Удержание (retention) > виральность**: тред `Retention help please`, `What to do if a video is not performing despite good AVD and CTR?`, `If you're struggling with CTR, here's where I'd start`.
- **AVD и CTR — главные метрики**: обсуждают вместе постоянно; «хорошее видео с плохим CTR» = проблема превью, не контента.
- **Превью решает**: `I designed 346 thumbnails for small youtubers. Here's exactly what worked`.
- **Частота vs качество**: `I was posting every day and getting nowhere. Then I switched to 3x/week and everything changed`.
- **Не удалять флопы** (см. 2.1) — повторяется в комментариях.
- **Аудио-качество**: `What I've learned about audio quality as a NewTuber` — звук важнее картинки на старте.
- **Рост канала**: `When you get monetized and have a breakout video, the floor and the ceiling rise` — после прорыва аудитория растёт и на старых видео.
- **YouTube ужесточает борьбу с ре-аплоадами**: `YouTube is updating Shorts recommendations to cut reach for channels that just re-upload other people's clips` — важно для нашего пайплайна (брать футаж с добавленной ценностью, не чистый ре-аплоад).
- **С 02.2027 пороги YPP растут**: 8 000 часов просмотра / 20 млн Shorts-просмотров за 90 дней (r/youtubegaming).

---

## 4. ТРЕНДЫ, КОТОРЫЕ ОТМЕЧАЮТ (2026)

- **Публика против AI-слопа**: `If your thumbnail is made with AI I'm clicking Don't recommend Channel` (топ r/youtubegaming за год), `Can we please ban AI from this subreddit please`, `Abundance of AI slop thumbnail designers`. → **AI можно использовать в пайплайне, но нельзя, чтобы это читалось как AI в превью/названии.**
- **AI Shorts с сатурацией**: Creepy Cartoon AI Shorts теряют RPM и удержание (из 2.3).
- **Гипер-монтаж мёртв**: тред `the hyper-editing trend is dead (here is what actually holds retention now)` (r/PartneredYoutube, топ месяца) — 2 года монтажа business/finance каналов. Тренд на более спокойный, но плотный монтаж.
- **Reddit-контент как источник**: подтверждено и в r/ContentCreators (Reddit Stories), и в нашем пайплайне.

---

## 5. ЗВУКИ И ШАБЛОНЫ — ГДЕ БРАТЬ

Прямых ссылок на «паки звуков» в топ-тредах нет (Reddit не любит рекламу). Что реально обсуждают:

- **CapCut** — самый упоминаемый редактор (шаблоны, TTS, авто-субтитры).
- **Premiere Pro, DaVinci Resolve** — профи.
- **Figma** — превью.
- **Taletok** — автоматизация Reddit-stories с авто-постингом.
- **ElevenLabs, AWS Polly, CapCut TTS** — озвучка (но с оговоркой про AI-слоп).
- **yt-dlp** — фоновые видео.
- **Topaz Video Enhance** — апскейл AI-визуалов.
- **Whisper** — транскрипты.

**Про звуки:** инсайт из 2.4 — уникальные звуки дают больше, чем заимствование трендовых. Для US-канала стоит генерировать свою библиотеку (как у нас в `audio_assets.py`).

---

## 6. ЧТО ИЗ ЭТОГО ПРИМЕНИМО К НАШЕМУ ВТОРОМУ КАНАЛУ (US)

| Приём | Как применить |
|---|---|
| Reddit-stories long-form / Creepy Shorts | Низкий порог, авто-постинг → игра чисел |
| Кастомные превью Shorts | Ставить через мобильное приложение (Studio не умеет) |
| Уникальные звуки | Уже есть: `audio_assets.py` (boom/riser/whoosh + подложки) |
| Не удалять флопы | Хранить архив, не чистить |
| Плотный монтаж вместо гипер-монтажа | Уже сделано: `compose_segments.py` + boom/riser |
| Не выглядеть как AI | Минимум AI в превью/названии; голос и картинка — человеческие |
| Формат «текст-квадрат-текст» | Новый паттерн для обучающего/игрового контента |
| Борьба с ре-аплоадами | Добавлять аналитику/ценность к сырому футажу (наш `ORIGINALITY_GUIDE.md` это уже требует) |

---

## 7. ГРАБЛИ И ОГРАНИЧЕНИЯ

- Reddit **закрыт для анонимного API** (403). Рабочий обход: `https://www.reddit.com/svc/shreddit/community-more-posts/<sort>/?name=<sub>&t=<period>` (HTML).
- Прямые URL постов через webfetch отдают пустую страницу — читать через встроенный браузер OpenChamber (`browser.open` + `browser.snapshot`).
- `old.reddit.com/*.json` отдаёт 404/HTML, не JSON.
- OpenCLI reddit требует расширения браузера (не подключено).
- Exa-поиск (mcporter) отдаёт 403 OAuth.
- Jina Reader на Reddit — 451.

---

## 8. ИТОГ: 5 главных выводов

1. **Не удалять флопы** — они стреляют через месяцы и годы. Архив хранить.
2. **Уникальные звуки** дают дополнительные просмотры и revenue share — у нас уже своя библиотека.
3. **Reddit-stories long-form** — лучшая faceless-ниша по деньгам/риску, автоматизируется до 6 постов/день.
4. **Публика устала от AI-слопа** — пайплайн можно, но UI/превью/название не должны выглядеть как AI.
5. **Кастомные превью Shorts** — недоиспользованный рычаг, ставится только с телефона.
