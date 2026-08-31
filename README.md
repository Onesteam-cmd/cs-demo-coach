# CS Demo Coach

Инструмент для многоуровневого анализа матчей Counter-Strike 2 по demo-файлам. Проект превращает `.dem` в структурированные данные, вычисляет игровые и тактические признаки, формирует отчёты по отдельному игроку и может подключать LLM как дополнительный слой проверки и объяснения выводов.

Проект находится в статусе **рабочего исследовательского прототипа**. Базовый аналитический pipeline используется отдельно от AI-слоя: для получения механических и тактических метрик подключение языковой модели не требуется.

## Что умеет проект

### Парсинг матча

Для demo-файла строятся таблицы событий и состояния матча:

- раунды;
- убийства и урон;
- выстрелы;
- гранаты, смоки и огонь;
- bomb events;
- tick-level данные;
- позиции игроков;
- yaw/pitch и дополнительные view-angle признаки.

Базовый parser layer использует `awpy`, а отдельный view-angle layer — `demoparser2`.

### Механический и тактический анализ

В проекте реализованы отдельные анализаторы для:

- дуэлей;
- контактов и приближённой видимости;
- первого выстрела и механических ошибок;
- utility;
- trade/spacing;
- фаз раунда;
- area profile;
- combat profile;
- advantage state;
- round impact;
- macro;
- loss patterns;
- enemy intent;
- canonical info state;
- decision context;
- tactical context.

Результаты собираются в versioned JSON/CSV/Parquet артефакты и HTML-отчёты.

### Анализ прогресса

Система может сохранять результаты нескольких матчей и сравнивать их между собой:

- K/D и ADR;
- механические показатели;
- категории потерянных контактов;
- повторяющиеся паттерны ошибок;
- тренд между матчами.

Для просмотра результатов генерируется локальный HTML-dashboard.

### Structured coach pipeline

Поверх аналитических слоёв строится структурированный пакет контекста для разборов:

```text
CS2 demo
  ↓
parser layers
  ↓
canonical match / round data
  ↓
mechanics + utility + macro + tactical analyzers
  ↓
player-focused evidence
  ↓
decision context / information state / enemy intent
  ↓
coach input package
  ↓
optional AI judge
  ↓
validated report
```

В поздней экспериментальной ветке используются versioned `round cards`, claim permissions, semantic validation и отдельные judge/repair stages. Цель этого слоя — ограничивать вывод модели фактическими данными матча, а не позволять ей свободно придумывать причины игровых событий.

## Структура

```text
backend/
  parser_core/     парсинг demo и view angles
  layers/          canonical представления матча
  analyzers/       механические и тактические анализаторы
  reports/         player-focused отчёты и progress tracking
  dashboard/       HTML-dashboard
  package/         versioned match/coach packages
  cases/           round casebook
  verdict/         приоритизация ошибок и action plan
  ai/              optional LLM judge / validation pipeline
  pipeline/        составные entry points

scripts/           PowerShell wrappers для отдельных стадий
config/            локальная конфигурация и безопасные examples
docs/              техническая документация
data/              локальные demo и генерируемые результаты; в Git не входят
```

## Требования

- Windows;
- Python 3.11+;
- PowerShell 7 рекомендуется для `scripts/*.ps1`;
- CS2 `.dem` для анализа.

Основные Python-зависимости перечислены в `requirements.txt`.

## Установка

Из корня репозитория:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Настройка игрока

В `config/project_settings.json` укажите ник игрока так, как он записан в demo:

```json
{
  "primary_player_names": ["MyNickname"],
  "primary_player_display_name": "MyNickname"
}
```

Можно также передавать игрока явно через `--player`.

## Базовый запуск

Поместите demo, например, в:

```text
data/demos/match.dem
```

Затем:

```powershell
python .\backend\pipeline\run_full_pipeline_v0_3.py `
  .\data\demos\match.dem `
  --match-id match_001 `
  --player "MyNickname" `
  --no-open
```

Pipeline создаёт локальные артефакты внутри `data/`. Они намеренно исключены из Git, поскольку могут содержать данные конкретного матча и игрока.

## AI-слой

AI-часть **не обязательна** для базового анализа.

Сначала создайте локальный конфиг:

```powershell
Copy-Item .\config\llm.env.example .\config\llm.env
Copy-Item .\config\llm_profiles.env.example .\config\llm_profiles.env
```

Затем заполните в `config/llm.env`:

```env
CS_DEMO_COACH_LLM_BASE_URL=https://provider.example/v1
CS_DEMO_COACH_LLM_API_KEY=...
CS_DEMO_COACH_LLM_MODEL=...
```

Используется OpenAI-compatible HTTP API. Реальные credentials исключены через `.gitignore`.

В `config/llm_profiles.env` можно назначить разные модели для core generation, дешёвой проверки, semantic judge, repair и редакторского прохода.

## Текущие ограничения

- Contact Visibility в текущем прототипе не выполняет полноценный raycast по геометрии карты; часть оценки основана на углах/FOV и строгих фильтрах.
- Совместимость полей зависит от версии demo и parser-библиотек.
- Некоторые поздние AI-stage скрипты сохраняют versioned experimental interfaces и требуют результатов предыдущих стадий.
- HTML-dashboard локальный; отдельный production web frontend пока не является частью проекта.
- LLM-вывод не считается первичным источником фактов: корректность отчёта зависит от качества исходного demo parsing и аналитических слоёв.
- Demo-файлы, пользовательские результаты и API credentials в репозиторий не включаются.

## Технологии

- Python
- PowerShell
- awpy
- demoparser2
- pandas
- NumPy
- PyArrow / Parquet
- SQLite
- HTML reports
- JSON contracts
- LLM orchestration
- structured output validation

## Назначение проекта

CS Demo Coach создавался как эксперимент по переходу от обычной статистики матча к доказательному разбору игровых решений: система сначала формирует измеримые события и контекст, затем строит выводы и только после этого, при необходимости, использует языковую модель для объяснения и дополнительной проверки.
