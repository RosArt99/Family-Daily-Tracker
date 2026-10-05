# Учим Odoo на собственном проекте

Идея: не читать документацию вообще, а разобрать код, который уже работает у вас дома, и
пять раз что-то в нём сломать и починить. Всё делается **на домашнем ПК** (локальная копия,
admin/admin), на сервер ничего не выкатывается, пока не проверено. Работайте в отдельной
ветке: `git switch -c learning`.

Обновить модуль после правки Python/XML:

```bash
docker compose exec -T odoo odoo -d family_tracker_db -u family_finance --db_host=db --db_user=odoo --db_password=odoo --stop-after-init --no-http
docker compose restart odoo
```

Правки только в `.js`, `.xml` шаблонах (`static/`) и `.scss` модуль обновлять не нужно:
достаточно `docker compose restart odoo` и обновить страницу (Ctrl+Shift+R).

Если сломали: `git restore <файл>` возвращает файл, `git switch main` возвращает всё.

---

## Занятие 1. Модель = таблица (≈1 час)

Читать: [finance_bill.py](../addons/family_finance/models/finance_bill.py) целиком (это короткий файл).

Вопросы, на которые нужно уметь ответить своими словами:
1. Что такое `_name` и во что превращается `finance.bill` в базе? (подсказка: `\d finance_bill`
   в psql, точка заменяется на `_`)
2. Чем `fields.Monetary` отличается от `fields.Float`? Зачем рядом `currency_id`?
3. `food_amount` не вводится руками. Как он считается и почему он `store=True`?
4. Что случится, если ввести хозяйственную часть больше итога? Где это проверяется
   (подсказка: `_check_household_within_total` и `_sql_constraints`) и в чём разница между ними?

**Практика.** Добавьте в `finance.bill` поле «Способ оплаты» (`fields.Selection`: наличные /
карта / BLIK). Обновите модуль. Поле пока нигде не видно: это нормально, это занятие 2.

Проверка: `docker compose exec db psql -U odoo -d family_tracker_db -c "\d finance_bill"`
должна показать новую колонку.

## Занятие 2. Представления (views) (≈1 час)

Читать: [finance_bill_views.xml](../addons/family_finance/views/finance_bill_views.xml).

Понять: `form`, `tree`, `kanban`, `graph`, `search` это разные «взгляды» на одну модель;
`ir.actions.act_window` связывает меню с моделью и списком видов; `ir.ui.menu` показывает действие.

**Практика.**
1. Выведите «Способ оплаты» в форму чека.
2. Покажите его в списке (`tree`) как необязательную колонку (`optional="show"`).
3. Добавьте в `search` фильтр «Наличные» и группировку «По способу оплаты».

Что нужно заметить: поле в `view` должно быть и в модели; если опечататься в имени, Odoo
скажет об этом при обновлении модуля, читайте ошибку в логе.

## Занятие 3. Вычисляемые поля и ORM в shell (≈1 час)

Читать: `_compute_stock_quantity` в [groceries_product.py](../addons/family_tracker/models/groceries_product.py)
и `get_overview` в [finance_overview.py](../addons/family_finance/models/finance_overview.py).

Запустить shell и «поиграть»:

```bash
docker compose exec odoo odoo shell -d family_tracker_db --db_host=db --db_user=odoo --db_password=odoo --no-http
```

```python
env['finance.bill'].search([]).mapped('total_amount')        # все суммы
env['finance.bill'].create({'total_amount': 50, 'household_amount': 10}).food_amount
env['finance.overview'].get_overview()['income']              # то, что видит Overview
env.cr.rollback()                                             # откатить всё, что натворили
```

Вопросы: что делает `read_group`? Чем `search` отличается от `browse`? Почему внутри
`@api.depends` пишут поля, от которых зависит расчёт?

**Практика.** Добавьте в `finance.bill` вычисляемое поле «Доля химии в чеке, %»
(`household_amount / total_amount * 100`, без деления на ноль).

## Занятие 4. Безопасность и права (≈45 минут)

Читать: [ir.model.access.csv](../addons/family_finance/security/ir.model.access.csv) и
[finance_security.xml](../addons/family_finance/security/finance_security.xml).

Понять: без строки в `ir.model.access.csv` модель недоступна никому, кроме суперпользователя.
`ir.rule` добавляет фильтр поверх доступа: так сделано «видеть чужой доход, но править только свой».

**Практика.** Войдите под вторым пользователем (Руслана) и проверьте, что она не может
изменить вашу запись дохода. Потом уберите `perm_unlink` для чеков и убедитесь, что удаление
пропало.

## Занятие 5. Фронтенд: Owl и шаблоны (≈1.5 часа)

Читать по порядку:
1. [finance_overview.xml](../addons/family_finance/static/src/xml/finance_overview.xml): шаблон (QWeb): `t-foreach`, `t-if`, `t-esc`.
2. [finance_overview.js](../addons/family_finance/static/src/js/finance_overview.js): компонент: `setup()`, `useState`, `orm.call`.
3. `get_overview` в Python: откуда берутся данные.

Схема: JS вызывает метод Python (`orm.call`), Python возвращает словарь, шаблон его рисует.
Понять это значит понять 80% фронтенда этого проекта.

**Практика.** В шапке Overview добавьте четвёртую цифру: «Сколько в среднем за день потрачено»
(`spent / число дней месяца`). Для этого придётся тронуть и Python (метод), и шаблон.

## Занятие 6. Собрать всё вместе (по желанию)

Сделайте свою мини-фичу с нуля, например справочник «Магазины» с рейтингом, сначала на бумаге
(какие модели, какие поля, какие меню), потом по шагам из занятий 1-4.
Хорошая цель на вечер: «Обещания купить» (кто что обещал купить и когда).

## Где смотреть, если застряли

- Ошибки: `docker compose logs odoo --tail 80`
- Что реально лежит в базе: psql или `odoo shell`
- Неизвестное поле/метод: открыть код самой Odoo внутри контейнера:
  `docker compose exec odoo ls /usr/lib/python3/dist-packages/odoo/addons/web/static/src/views`
- Или просто спросить: попросите объяснить конкретный метод построчно.
