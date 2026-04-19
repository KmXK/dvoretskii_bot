from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from steward.data.models.bill import Bill


HELP_TEXT = """📋 /bill

/bill — общий отчет по всем счетам
/bill all — список всех счетов
/bill {id} — отчет по счету (+ кнопка «Добавить контекст»)
/bill {id} edit — собрать контекст и добавить в счёт (не перезаписывает)
/bill {id} debug — отчет по счету с выводом сырых данных из таблицы
/bill add — добавить счет (если файла нет, переименовывается найденный «Копия Шаблон»)
/bill pay {кто} {кому} {сумма} — зарегистрировать перевод
/bill pay force delete {count} — удалить последние N платежей (админ)
/bill close {id1} {id2} ... — закрыть счета
/bill details add {пользователь} — добавить платежные данные
/bill details edit {пользователь} — изменить платежные данные"""

PROMPT_TEXT = (
    "▶ /bill — управление счетами (расходы, долги, переводы)\n"
    "  Основной отчёт по всем должникам: /bill\n"
    "  Список всех счетов: /bill all\n"
    "  Отчёт по конкретному счету: /bill <id> или /bill <имя_счёта>\n"
    "  Добавить контекст в счёт: /bill <id> edit\n"
    "  Отчёт с отладкой: /bill <id> debug\n"
    "  Добавить новый счет: /bill add <имя> или /bill add (начинает сессию)\n"
    "  Если счёт не найден, будет переименован найденный шаблон 'Копия Шаблон' в папке финансов\n"
    "  Зарегистрировать перевод: /bill pay <кто> <кому> <сумма>\n"
    "  Удалить последние N платежей: /bill pay force delete <N> (только админ)\n"
    "  Закрыть счета: /bill close <id1> <id2> ...\n"
    "  Добавить платёжные данные: /bill details add <пользователь> <описание> или /bill details add <пользователь> (начинает сессию)\n"
    "  Изменить платёжные данные: /bill details edit <пользователь> <описание> или /bill details edit <пользователь> (начинает сессию)\n"
    "  Помощь по /bill: /bill help\n"
    "  Примеры:\n"
    "  - «покажи общий отчёт по счетам» → /bill\n"
    "  - «покажи все счета» → /bill all\n"
    "  - «покажи счёт 3» → /bill 3\n"
    "  - «добавь контекст в счёт 3» → /bill 3 edit\n"
    "  - «зарегистрируй перевод Вася → Петя 500» → /bill pay Вася Петя 500\n"
    "  - «закрой счёт 1 и 2» → /bill close 1 2\n"
    "  - «помощь по биллу» → /bill help\n"
    "  - «добавь счёт» → /bill add\n"
    "\n"
    "  ВОПРОСЫ О ДАННЫХ В КОНТЕКСТЕ:\n"
    "  Если в контексте уже есть отчёт с долгами и пользователь задаёт ВОПРОС\n"
    "  (сколько я должен, кто должен X, какие долги у Y, и т.п.),\n"
    "  НЕ возвращай /bill — верни пустой ответ. Данные уже есть в контексте.\n"
    "\n"
    "  ЗАКРЫТИЕ ДОЛГОВ ЧЕРЕЗ КОНТЕКСТ:\n"
    "  В контексте долги представлены в формате: «X должен Y: сумма».\n"
    "  Если пользователь говорит что кто-то «заплатил по долгам» / «никому не должен» / «рассчитался»,\n"
    "  найди все строки «X должен Y: сумма» где X — указанный человек,\n"
    "  и сгенерируй /bill pay X Y сумма для каждой.\n"
    "  Имя берётся из запроса, из «Отправитель» контекста, или по смыслу («чел» = Отправитель).\n"
    "  Строки где человек после «должен» (т.е. ему должны) — НЕ включай.\n"
    "\n"
    "  Пример:\n"
    "  Контекст:\n"
    "    Альфа должен Бета: 1000\n"
    "    Бета должен Гамма: 82.33\n"
    "    Бета должен Дельта: 65\n"
    "    Бета должен Эпсилон: 12\n"
    "  Запрос: «Бета заплатил по долгам»\n"
    "  Ответ:\n"
    "  /bill pay Бета Гамма 82.33\n"
    "  /bill pay Бета Дельта 65\n"
    "  /bill pay Бета Эпсилон 12\n"
    "  «Альфа должен Бета: 1000» НЕ включается — тут Альфа должен Бета, а не Бета кому-то"
)


def build_bill_nav_keyboard(
    cb_factory, bills: list[Bill], current: str
) -> InlineKeyboardMarkup:
    sorted_bills = sorted(bills, key=lambda b: b.id)
    bill_ids = [str(b.id) for b in sorted_bills]

    def cb(target: str) -> str:
        prefix = "~" if target == current else ""
        return cb_factory(target=f"{prefix}{target}")

    if current == "общий":
        prev_target = bill_ids[-1] if bill_ids else "общий"
        next_target = bill_ids[0] if bill_ids else "общий"
    else:
        idx = bill_ids.index(current) if current in bill_ids else 0
        prev_target = bill_ids[idx - 1] if idx > 0 else "общий"
        next_target = bill_ids[idx + 1] if idx < len(bill_ids) - 1 else "общий"

    first_target = bill_ids[0] if bill_ids else "общий"
    last_target = bill_ids[-1] if bill_ids else "общий"
    общий_label = "• общий" if current == "общий" else "общий"

    row1 = [
        InlineKeyboardButton("<<", callback_data=cb(first_target)),
        InlineKeyboardButton("<", callback_data=cb(prev_target)),
        InlineKeyboardButton(общий_label, callback_data=cb("общий")),
        InlineKeyboardButton(">", callback_data=cb(next_target)),
        InlineKeyboardButton(">>", callback_data=cb(last_target)),
    ]

    last_5 = sorted_bills[-5:]
    row2 = [
        InlineKeyboardButton(
            f"• {b.id}" if str(b.id) == current else str(b.id),
            callback_data=cb(str(b.id)),
        )
        for b in last_5
    ]

    rows = [row1]
    if row2:
        rows.append(row2)
    return InlineKeyboardMarkup(rows)


def split_inline_details(text: str) -> tuple[str, str] | None:
    if not text:
        return None
    lines = text.split("\n", 1)
    if len(lines) == 2:
        head_parts = lines[0].split(None, 3)
        description = lines[1].strip()
        if len(head_parts) >= 4 and description:
            inline_name = head_parts[3].strip()
            if inline_name:
                return inline_name, description
        return None
    single_parts = text.split(None, 4)
    if len(single_parts) >= 5:
        inline_name = single_parts[3].strip()
        description = single_parts[4].strip()
        if inline_name and description:
            return inline_name, description
    return None


def split_inline_details_edit(
    text: str, find_info,
) -> tuple[object, str] | None:
    if not text:
        return None
    lines = text.split("\n", 1)
    head_parts = lines[0].split() if lines else []
    if len(lines) == 2 and len(head_parts) >= 4:
        inline_name = " ".join(head_parts[3:])
        description = lines[1].strip()
        info = find_info(inline_name)
        if info is not None and description:
            return info, description
    if len(head_parts) >= 5:
        for i in range(4, len(head_parts)):
            candidate = " ".join(head_parts[3:i])
            info = find_info(candidate)
            if info is not None:
                description = " ".join(head_parts[i:]).strip()
                if description:
                    return info, description
    return None
