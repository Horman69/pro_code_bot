# LEAD+ GUIDE — Телеграм-бот школы программирования

> Этот файл — мой внутренний стандарт. Перед каждой задачей я открываю его и прохожу чеклист.
> Цель: не просто написать код, а написать правильный код с первого раза.

---

## КОНТЕКСТ ПРОЕКТА

**Клиент:** школа программирования (1 преподаватель/менеджер)
**Текущий масштаб:** ~10 учеников → цель 100+
**Возраст учеников:** 9-13 лет
**Цена урока:** 1,000-1,500 руб/час
**Расписание:** 1-2 урока в неделю, по графику
**Календарь:** Google Calendar (интегрируем)
**БД сейчас:** SQLite → PostgreSQL при 50+ учениках

---

## РОЛИ В СИСТЕМЕ

| Роль | Telegram | Доступ |
|------|----------|--------|
| Менеджер (владелец) | 1 аккаунт | Полный контроль |
| Родитель | 1 аккаунт = 1+ детей | Только свои данные |

---

## СТЕК — ФИНАЛЬНЫЕ РЕШЕНИЯ

```
aiogram 3.x          — async Telegram bot framework, FSM из коробки
SQLite → PostgreSQL  — база данных (SQLAlchemy 2.0 ORM)
APScheduler          — планировщик напоминаний (persistent jobs)
Redis                — job store для APScheduler (выживает при рестарте)
Google Calendar API  — синхронизация расписания
Docker               — деплой на VPS
```

**Почему aiogram 3.x а не python-telegram-bot:**
- Полностью async — критично для scheduler + bot одновременно
- Лучший FSM (Finite State Machine) для диалогов
- Активная поддержка, современный API

**Почему APScheduler + Redis а не cron:**
- Напоминания создаются динамически (разное время у каждого урока)
- Redis job store = jobs не теряются при перезапуске сервера
- Можно отменить конкретный job (если урок отменили)

---

## АРХИТЕКТУРА ПРОЕКТА

```
school_bot/
├── bot/
│   ├── __init__.py
│   ├── main.py                 — точка входа, запуск бота + scheduler
│   ├── config.py               — настройки из .env
│   ├── database/
│   │   ├── models.py           — SQLAlchemy модели
│   │   ├── crud.py             — все операции с БД
│   │   └── session.py          — async session factory
│   ├── handlers/
│   │   ├── parent.py           — хэндлеры для родителей
│   │   ├── manager.py          — хэндлеры для менеджера
│   │   ├── referral.py         — реферальная система
│   │   └── common.py           — общие (start, help)
│   ├── keyboards/
│   │   ├── parent_kb.py        — клавиатуры родителя
│   │   └── manager_kb.py       — клавиатуры менеджера
│   ├── scheduler/
│   │   ├── jobs.py             — функции-джобы (отправка напоминаний)
│   │   └── setup.py            — инициализация APScheduler
│   ├── services/
│   │   ├── google_calendar.py  — интеграция с Google Calendar
│   │   ├── notifications.py    — логика уведомлений
│   │   └── referral.py         — бизнес-логика рефералов
│   └── states/
│       ├── parent_states.py    — FSM состояния родителя
│       └── manager_states.py   — FSM состояния менеджера
├── .env                        — секреты (в .gitignore)
├── .env.example                — шаблон для деплоя
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── LEAD_PLUS.md                — этот файл
```

**Принцип разделения:**
- `handlers/` — только роутинг и вызовы сервисов. Никакой бизнес-логики.
- `services/` — вся бизнес-логика. Не знает о Telegram.
- `database/crud.py` — только SQL операции. Не знает о боте.
- Это позволяет тестировать сервисы без поднятия бота.

---

## СХЕМА БАЗЫ ДАННЫХ

```sql
-- Родители
Parents
  id              INTEGER PK
  telegram_id     INTEGER UNIQUE NOT NULL
  name            TEXT NOT NULL
  phone           TEXT
  referral_code   TEXT UNIQUE          -- их код для приглашений
  referred_by_id  INTEGER FK Parents   -- кто их пригласил
  status          TEXT DEFAULT 'active' -- active | blocked
  created_at      DATETIME

-- Ученики
Students
  id                INTEGER PK
  name              TEXT NOT NULL
  age               INTEGER
  parent_id         INTEGER FK Parents NOT NULL
  lessons_balance   INTEGER DEFAULT 0  -- текущий остаток
  lessons_completed INTEGER DEFAULT 0  -- всего проведено
  is_active         BOOLEAN DEFAULT TRUE
  created_at        DATETIME

-- Уроки
Lessons
  id                    INTEGER PK
  student_id            INTEGER FK Students NOT NULL
  scheduled_at          DATETIME NOT NULL
  status                TEXT DEFAULT 'scheduled'
    -- scheduled | completed | cancelled_by_parent
    -- cancelled_by_teacher | no_show
  reminder_24h_sent     BOOLEAN DEFAULT FALSE
  reminder_1h_sent      BOOLEAN DEFAULT FALSE
  reminder_15m_sent     BOOLEAN DEFAULT FALSE
  google_event_id       TEXT              -- для синхронизации
  parent_confirmed      BOOLEAN           -- подтвердил ли родитель
  cancellation_reason   TEXT
  created_at            DATETIME
  updated_at            DATETIME

-- Оплаты
Payments
  id              INTEGER PK
  student_id      INTEGER FK Students NOT NULL
  lessons_count   INTEGER NOT NULL      -- сколько уроков куплено
  amount          INTEGER               -- сумма в рублях
  note            TEXT
  created_at      DATETIME

-- Рефералы (отдельная таблица для milestone-трекинга)
Referrals
  id              INTEGER PK
  referrer_id     INTEGER FK Parents NOT NULL
  referred_id     INTEGER FK Parents NOT NULL
  status          TEXT DEFAULT 'pending'
    -- pending | active | completed
  month_1_bonus   BOOLEAN DEFAULT FALSE  -- начислен ли бонус за 1 мес
  month_3_bonus   BOOLEAN DEFAULT FALSE  -- начислен ли бонус за 3 мес
  month_6_bonus   BOOLEAN DEFAULT FALSE  -- начислен ли бонус за 6 мес
  created_at      DATETIME

-- Начисления бонусов
ReferralBonuses
  id              INTEGER PK
  referral_id     INTEGER FK Referrals
  recipient_id    INTEGER FK Parents
  type            TEXT    -- lesson | cash
  amount          INTEGER -- уроки или рубли
  milestone       TEXT    -- signup | month_1 | month_3 | month_6
  is_paid         BOOLEAN DEFAULT FALSE
  created_at      DATETIME

-- Обратная связь
Feedback
  id              INTEGER PK
  parent_id       INTEGER FK Parents
  message         TEXT NOT NULL
  is_read         BOOLEAN DEFAULT FALSE
  created_at      DATETIME
```

---

## БИЗНЕС-ЛОГИКА — КЛЮЧЕВЫЕ ПРАВИЛА

### Урок
1. Статус меняет только менеджер (не родитель)
2. `completed` → `student.lessons_balance -= 1`, `lessons_completed += 1`
3. `cancelled_by_parent` → баланс не трогаем (это бизнес-решение, менять по договорённости)
4. При отмене урока → отменить все запланированные scheduler jobs для этого урока
5. При переносе урока → отменить старые jobs, создать новые

### Оплата
1. При добавлении Payment → `student.lessons_balance += payment.lessons_count`
2. Менеджер может только добавлять уроки, не вычитать вручную (только через урок)
3. Когда баланс <= 2 → уведомить родителя "скоро заканчиваются уроки"
4. Когда баланс = 0 → уведомить родителя и менеджера

### Реферальная программа
```
MILESTONE          ТИП БОНУСА    СУММА        УСЛОВИЕ ВЫПЛАТЫ
─────────────────────────────────────────────────────────────
Первая оплата      урок          +1 тебе      авто после payment
                   урок          +1 другу     авто после payment
1 месяц            урок          +1 тебе      30 дней с первой оплаты
3 месяца           кэш           2,000 руб    90 дней с первой оплаты
6 месяцев          кэш           2,500 руб    180 дней с первой оплаты
```
- Бонус за урок → `lessons_balance += 1` автоматически
- Бонус кэш → создаётся запись ReferralBonuses(is_paid=False) → менеджер видит в ЛК → выплачивает → ставит is_paid=True

### Статусы Ambassador
```
Обычный       — 0 активных рефералов
Партнёр       — 1+ (учится 3+ мес)    → +500 руб к каждому milestone
Старший       — 3+ рефералов           → +1,000 руб к каждому milestone
Амбассадор    — 5+ рефералов           → бесплатный месяц ребёнку
```

---

## ЧЕКЛИСТ — ПЕРЕД КАЖДОЙ ЗАДАЧЕЙ

### 1. Понять задачу
- [ ] Что конкретно должно произойти? (вход → выход)
- [ ] Кто пользователь этой функции? (менеджер / родитель)
- [ ] Какие edge cases могут сломать это?

### 2. Подумать как Lead+
- [ ] Что будет при 100 учениках? Не сломается ли?
- [ ] Что если пользователь нажмёт кнопку дважды? (idempotency)
- [ ] Что если scheduler упал и job не выполнился?
- [ ] Что если родитель удалил бота? (бот не может писать → обработать ошибку)
- [ ] Что если Google Calendar недоступен?

### 3. База данных
- [ ] Нужна ли транзакция? (если меняем 2+ таблицы — да)
- [ ] Правильный ли индекс для этого запроса?
- [ ] Не делаю ли N+1 запросов? (использовать joinedload)

### 4. Код
- [ ] Handler только роутит — бизнес-логика в services/
- [ ] Все ошибки обработаны (try/except с понятным сообщением пользователю)
- [ ] Нет хардкода — константы в config.py
- [ ] Логирование есть для важных событий

### 5. Scheduler jobs
- [ ] Job имеет уникальный id (format: `reminder_{lesson_id}_{type}`)
- [ ] При отмене урока — удаляем все связанные jobs
- [ ] Jobs персистентны (Redis store)

### 6. Безопасность
- [ ] Manager-only хэндлеры проверяют MANAGER_ID из config
- [ ] Parent видит только своих детей (фильтр по parent.telegram_id)
- [ ] Нет возможности угадать referral_code другого (UUID, не sequential)

---

## ПАТТЕРНЫ КОДА — СТАНДАРТЫ

### Правило комментариев
**Все комментарии в коде — только на русском языке.**
Комментарий пишем только когда логика неочевидна. Не комментируем то, что понятно из названия.

### Handler (тонкий)
```python
@router.callback_query(F.data == "confirm_lesson")
async def confirm_lesson_handler(callback: CallbackQuery):
    # Вся логика в сервисе — хэндлер только роутит
    result = await lesson_service.confirm_attendance(callback.from_user.id)
    await callback.message.edit_text(result.message, reply_markup=result.keyboard)
    await callback.answer()
```

### Service (вся логика)
```python
async def confirm_attendance(telegram_id: int) -> ServiceResult:
    async with get_session() as session:
        lesson = await crud.get_pending_lesson(session, telegram_id)
        if not lesson:
            return ServiceResult(message="Урок не найден")
        # Меняем статус и обновляем счётчики в одной транзакции
        await crud.complete_lesson(session, lesson.id)
        return ServiceResult(message="✅ Подтверждено!")
```

### CRUD (только SQL)
```python
async def get_pending_lesson(session: AsyncSession, telegram_id: int) -> Lesson | None:
    # Ищем ближайший запланированный урок для этого родителя
    result = await session.execute(
        select(Lesson)
        .join(Student)
        .join(Parent)
        .where(Parent.telegram_id == telegram_id)
        .where(Lesson.status == "scheduled")
        .order_by(Lesson.scheduled_at)
    )
    return result.scalar_one_or_none()
```

---

## УВЕДОМЛЕНИЯ — ПОЛНАЯ КАРТА

### Родителю автоматически
| Триггер | Сообщение |
|---------|-----------|
| За 24 часа до урока | "Завтра урок в {time}. Ждём!" + [Приду / Не приду / Перенести] |
| За 1 час до урока | "Через час урок! 🎯" + [Еду / Не приду] |
| Баланс <= 2 урока | "Осталось {n} урока, скоро нужно продлить" |
| Баланс = 0 | "Уроки закончились. Реквизиты: ..." |
| Реферал оплатил | "Ваш друг записался! +1 урок вам" |
| Milestone реферала | "Ваш друг учится {n} месяцев! Бонус: ..." |

### Менеджеру автоматически
| Триггер | Сообщение |
|---------|-----------|
| 9:00 каждый день | Список уроков на сегодня |
| За 1 час до урока | "Через час: {имя ученика} (родитель {подтвердил/не ответил})" |
| Родитель отменил | "❌ {имя} отменил урок на {time}. Причина: ..." |
| Баланс студента = 0 | "{имя} закончил уроки, нужна оплата" |
| Новый реферал | "Новый ученик по реферальной ссылке {имя родителя}" |
| Кэш-бонус к выплате | "💳 Нужно выплатить {сумма} руб → {имя родителя}" |

---

## EDGE CASES — ВСЕГДА ПОМНИТЬ

1. **Двойное нажатие кнопки** → проверять статус перед изменением
2. **Родитель удалил бота** → `TelegramForbiddenError` → помечать как неактивный
3. **Урок перенесён** → отменить старые jobs, создать новые, уведомить
4. **Два ребёнка у одного родителя** → показывать выбор ребёнка
5. **Scheduler упал** → при старте проверять пропущенные напоминания
6. **Google Calendar недоступен** → логировать, не падать, уведомить менеджера
7. **Реферал сам себя** → проверка на telegram_id
8. **Бонус начислен дважды** → флаги month_1_bonus и т.д. в таблице Referrals

---

## ДЕПЛОЙ

```yaml
# docker-compose.yml структура
services:
  bot:        — основной бот
  redis:      — для APScheduler job store
  # PostgreSQL добавим при 50+ учениках
```

**Переменные окружения (.env):**
```
BOT_TOKEN=
MANAGER_TELEGRAM_ID=
DATABASE_URL=sqlite+aiosqlite:///data/school.db
REDIS_URL=redis://redis:6379/0
GOOGLE_CALENDAR_ID=
GOOGLE_CREDENTIALS_JSON=
```

---

## ВОПРОСЫ КОТОРЫЕ Я ЗАДАЮ СЕБЕ КАК LEAD+

```
1. "Что если это сломается в 2 ночи?" → логи, алерты, graceful errors
2. "Поймёт ли мама 45 лет что тут написано?" → простой UX
3. "Что будет при 100 учениках и 200 jobs в очереди?" → нагрузка
4. "Можно ли это сделать проще?" → YAGNI принцип
5. "Что если менеджер ошибся?" → всегда должна быть возможность исправить
6. "Данные не потеряются?" → транзакции, бэкапы
7. "Не утечёт ли чужой номер телефона?" → изоляция данных по ролям
```

---

*Обновлять этот файл при каждом значимом архитектурном решении.*
*Версия: 1.0 | Дата: 2026-05-23*
