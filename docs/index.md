## Documentation index / Индекс документации

> EN: This file lists the main entry points to osysHome documentation.  
> RU: Этот файл перечисляет основные точки входа в документацию osysHome.

---

### Quickstart

- **Self‑host users** / **Self‑host пользователи**
  - `QUICKSTART_selfhost.md` — fast path from `git clone` to a running web UI (Linux/Windows, Docker, minimal config).
- **Developers** / **Разработчики**
  - `QUICKSTART_dev.md` — architecture overview, dev‑mode, first plugin, tests.

---

### Architecture / Архитектура

- `ARCHITECTURE.md` — high‑level architecture, main components and data flow.
- `PARAMS_DOCUMENTATION.md` — detailed documentation of property `params` and validation.
- `ENUM_TYPE_USAGE.md` — how to use `enum` properties.
- `MIGRATION_ENUM_VALUES.md` — enum migration details and rationale.

---

### Plugins / Плагины

- `PLUGINS_guide.md` — how to write and structure plugins (`BasePlugin`, actions, routes, widgets).
- Recommended external plugins (separate repositories):
  - `osysHome-Modules`
  - `osysHome-Objects`
  - `osysHome-Users`
  - `osysHome-Scheduler`
  - `osysHome-wsServer`
  - `osysHome-Dashboard`

---

### Examples & tests / Примеры и тесты

- Directory `../examples/` — Python examples:
  - `advanced_validation_examples.py`
  - `enum_property_example.py`
  - `property_params_examples.py`
  - `default_value_example.py`
- Directory `../tests/`
  - `README.md` — how to run tests.
  - `test_object_manager.py`, `test_property_validation.py`, etc.

---

### Operations & troubleshooting / Эксплуатация и отладка

- `TROUBLESHOOTING.md` — common problems and how to diagnose/fix them.
- Logging:
  - See `app/logging_config.py` in the source tree for logger names and configuration.
- Translations:
  - `scripts/create_translations.py` — scan project and regenerate translation JSON files.

---

### Scripts / Скрипты

- `../scripts/README.md` — versioning, Git hooks, translations.
- `../scripts/install_recommended_plugins.sh` — install core plugins on Linux/macOS.
- `../scripts/install_recommended_plugins.ps1` — install core plugins on Windows (PowerShell).

---
title: Введение
layout: home
nav_order: 1
---

# osysHome

osysHome - это современная система управления умным домом, которая делает вашу жизнь комфортнее, безопаснее и экономичнее. Система позволяет управлять всеми устройствами в доме через удобный веб-интерфейс, создавать автоматические сценарии и контролировать климат в помещениях.

## Для кого эта система?

osysHome создана для тех, кто ценит:
* **Комфорт** — автоматическое поддержание оптимальной температуры и свежести воздуха
* **Удобство** — управление всеми устройствами из одного места
* **Экономию** — умная автоматизация помогает снизить расходы на электроэнергию
* **Гибкость** — система подстраивается под ваши привычки и расписание
* **Безопасность** — контроль доступа и уведомления о важных событиях

## Что умеет osysHome?

### Управление климатом
Система следит за температурой и влажностью в каждой комнате, автоматически включает отопление, вентиляцию или кондиционер, чтобы вам всегда было комфортно. Больше никакой духоты или перегрева!

### Умный веб-интерфейс
Удобная панель управления доступна с любого устройства — компьютера, планшета или телефона. Все данные обновляются моментально, вы всегда видите актуальное состояние дома.

### Автоматизация
Создавайте сценарии для любых ситуаций: утреннее пробуждение, уход из дома, вечерний отдых. Система сама научится вашим привычкам и будет предлагать оптимальные настройки.

### Уведомления
Получайте важные сообщения в Telegram: когда температура слишком высокая, когда кто-то пришел домой, когда нужно заменить фильтр вентиляции.

### Работа с устройствами
Поддержка популярных устройств российского рынка: Xiaomi, Яндекс, LG ThinQ, роутеры Keenetic, Zigbee-устройства и многое другое.

### Сенсорные панели
Настенные сенсорные панели в каждой комнате для быстрого управления светом, климатом и другими устройствами без необходимости доставать телефон.

## Доступные возможности

### Управление устройствами
* **Xiaomi Smart Home** — датчики, выключатели, лампочки и другие устройства экосистемы Xiaomi
* **Яндекс устройства** — умные колонки, лампочки, розетки
* **LG ThinQ** — холодильники, кондиционеры, стиральные машины
* **Роутеры Keenetic** — мониторинг сети, родительский контроль
* **Zigbee-устройства** — датчики температуры, движения, открытия дверей
* **ESP-устройства** — самодельные датчики и реле на базе ESP32/ESP8266
* **Телевизоры Hisense** — управление телевизором
* **Сенсорные панели OpenHASP** — настенные сенсорные экраны

### Сервисы и интеграции
* **Telegram бот** — управление домом через мессенджер
* **2GIS** — отслеживание местоположения членов семьи на карте
* **GPS-трекер** — автоматические действия при входе/выходе из дома
* **Голосовые уведомления** — озвучивание событий через Яндекс TTS
* **Задачи и напоминания** — встроенный планировщик дел

### Автоматизация с искусственным интеллектом
Система может анализировать ваши привычки и автоматически создавать сценарии:
* Когда вы обычно просыпаетесь и ложитесь спать
* Какую температуру предпочитаете в разное время суток
* Когда нужно включить вентиляцию, чтобы избежать духоты
* Оптимальное время для работы отопления

## Начало работы

1. **[Установка системы]({% link docs/install.md %})** — если вы администратор
2. **[Быстрый старт]({% link docs/quick_start.md %})** — первые шаги для пользователей
3. **[Управление климатом]({% link docs/climate_control.md %})** — настройка комфортной температуры
4. **[Веб-интерфейс]({% link docs/web_interface.md %})** — работа с панелью управления
5. **[Плагины]({% link docs/plugins/index.md %})** — установка и настройка плагинов
6. **[Часто задаваемые вопросы]({% link docs/faq.md %})** — ответы на популярные вопросы

## Поддержка

* **Telegram-канал**: [t.me/osysHome](https://t.me/osysHome)
* **Документация**: вы её сейчас читаете!
* **Сообщество**: задавайте вопросы в Telegram-группе

