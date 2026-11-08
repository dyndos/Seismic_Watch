# Seismic Watch — руководство по запуску

Этот репозиторий содержит два режима:

1. веб-приложение Seismic Watch (Next.js + PostgreSQL);
2. исследовательский Python-конвейер K0–K4 для перспективных прогнозов и исторических blind-hindcast проверок.

Чтобы получить текущие исследовательские скрипты, переключитесь на ветку **feature/2023-first-half-blind-test**. В main эти исследовательские изменения пока не включены.

## 1. Получить проект

    git clone https://github.com/dyndos/Seismic_Watch.git
    cd Seismic_Watch
    git fetch origin
    git switch --track origin/feature/2023-first-half-blind-test

## 2. Запустить веб-приложение

### Рекомендуемый способ: Docker Compose

Нужен установленный Docker Desktop (Windows/macOS) либо Docker Engine + Compose plugin (Linux).

Из корневой папки проекта:

    docker compose up --build -d

Откройте в браузере: http://localhost:3000

Посмотреть журналы приложения:

    docker compose logs -f app

Остановить контейнеры:

    docker compose down

База PostgreSQL хранится в именованном volume pgdata, поэтому обычная команда down не удаляет данные. Команда docker compose down -v удаляет volume вместе с данными базы — использовать ее только при осознанном сбросе.

В Docker Compose переменная DATABASE_URL задается автоматически; отдельный файл .env для этого режима не нужен.

### Локальный запуск без контейнера приложения

Нужны Node.js 22 и отдельный работающий PostgreSQL. Создайте файл .env в корне проекта со строкой подключения, например:

    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/app_db

Затем:

    npm install
    npm run build
    npm start

Для режима разработки вместо последних двух команд:

    npm run dev

Примечание: в репозитории сейчас нет файла .env.example и нет закоммиченного package-lock.json; поэтому используйте npm install, а не npm ci. Dockerfile обновлен с учетом отсутствующего lock-файла.

## 3. Запустить исследовательскую модель K0–K4

Нужен Python 3.12. Установка выполняется из корня проекта.

### Windows PowerShell

    py -3.12 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    python -m pip install -r research/requirements.txt
    pytest -q research/tests

### macOS / Linux

    python3.12 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    python -m pip install -r research/requirements.txt
    pytest -q research/tests

### Новый перспективный прогноз по триггерам

Команда использует все землетрясения M≥6,5, доступные в USGS ComCat на момент запуска, и строит отдельные карты K0–K4 для Тибета и Флореса:

    python -m research.run_2026_trigger_cases \
      --download-coupling \
      --download-slab2 \
      --output research/outputs/2026-trigger-cases

Результаты:
- forecast_summary.json — сводка вероятностей и рейтингов;
- forecast_rows.csv — таблица по моделям и горизонтам;
- forecast_snapshots/*.npz — замороженные полные поверхности;
- case_source_checks.json — использованные решения очага и временные метки;
- report.md — краткий отчет.

**Важно:** каждый новый запуск создает новый прогнозный винтаж с новым временем фиксации. Чтобы сохранить старый прогноз, не перезаписывайте его каталог output; задайте новую папку, например research/outputs/2026-11-09-run.

### Историческая blind-hindcast проверка

Пример: десять равномерно выбранных механизм-подтвержденных событий M≥6,5 в первом полугодии 2023 года с последующим сравнением прогнозов и фактических событий:

    python -m research.run_blind_test \
      --start-year 2023 \
      --end-year 2023 \
      --start-date 2023-01-01T00:00:00Z \
      --end-date 2023-07-01T00:00:00Z \
      --max-triggers 10 \
      --no-controls \
      --download-coupling \
      --download-slab2 \
      --output research/outputs/2023-first-half-blind

Границы дат: начало включительно, конец не включается. Поэтому 2023-07-01 включает весь день 30 июня, но не включает события июля.

Для каждого триггера прогнозная отсечка рассчитывается как:

    max(время главного толчка + 7 суток, время анализа Global CMT)

Затем сначала сохраняются все прогнозные поверхности, и только после этого открываются последующие события для оценки. Выходные таблицы:
- scores.csv — оценка для каждого триггера, модели и горизонта;
- aggregate_scores.csv — агрегированные метрики;
- common_sample_manifest.json — одинаковый набор отсечек для сравнения моделей;
- forecast_snapshots/ — сохраненные прогнозы до проверки.

## 4. Запуск через GitHub Actions без локального Python

Для воспроизведения теста 2023:
1. Откройте вкладку Actions репозитория.
2. Выберите **2023 first-half ten-trigger blind hindcast**.
3. Нажмите Run workflow, если нужен повторный запуск.

Для проверки результатов прошлых запусков откройте соответствующий workflow run и скачайте artifact. Успешный run означает, что компиляция, тесты, расчет и загрузка артефакта завершились успешно.

## 5. Что важно помнить

- K0 — базовая пространственная частота; K1 — кинематика плит; K2 — геофизические Coupling Cloud/Slab2 данные; K3 — статическое изменение напряжения Кулона; K4 — Dieterich rate-and-state.
- Сетка имеет номинальный шаг около 500 км. Это региональная оценка, а не локализация отдельного разлома.
- Для исторических тестов текущий ComCat не является архивом точных публичных состояний каталога на прошлые даты. Время анализа Global CMT используется как proxy доступности механизма, но не гарантированное время его публикации.
- Современные Coupling Cloud и Slab2 — ретроспективные данные; это ограничивает строгость исторической проверки K2–K4.
- Результаты экспериментальные и не являются официальным сейсмологическим прогнозом или основанием для решений по безопасности.


## 6. Географически размеченный отчет и данные для карты

После перспективного расчета K0–K4 можно дополнительно сформировать отчет с названиями территорий и GeoJSON:

    python -m research.render_forecast_report --output research/outputs/2026-trigger-cases

Скрипт создает report-visual-ru.md, forecast_locations.geojson и кэш geocode_cache.json. Для географических подписей нужен интернет-доступ к OpenStreetMap Nominatim. Первый запуск может занять время из-за ограничения частоты запросов; повторные запуски используют кэш.

Описание трактовки вероятностей, географических подписей и будущего отображения на карте: docs/FORECAST_DISPLAY_RU.md.
