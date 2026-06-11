import logging
import re
from collections import namedtuple

from telegram import ReactionTypeEmoji

from steward.data.models.rule import Response, Rule, RulePattern
from steward.framework import (
    Button,
    Feature,
    FeatureContext,
    Keyboard,
    collection,
    on_callback,
    step,
    subcommand,
    wizard,
)
from steward.session.step import Step

logger = logging.getLogger(__name__)


# ── Общие хелперы ────────────────────────────────────────────────────────────

_ChatRef = namedtuple("_ChatRef", ["id", "name"])


def _manageable_chats(repository, user_id: int) -> list[_ChatRef]:
    """Чаты, которые пользователь может скоупить правилом: где он состоит и
    является чат-админом (глобальный админ — везде). Это и есть механика
    распространения: юзер видит только свои чаты, чужие в правиле не трогает."""
    user = next((u for u in repository.db.users if u.id == user_id), None)
    ids = list(dict.fromkeys(user.chat_ids)) if user and user.chat_ids else []
    out: list[_ChatRef] = []
    for cid in ids:
        if not repository.is_chat_admin(user_id, cid):
            continue
        chat = repository.get_chat(cid)
        out.append(_ChatRef(cid, chat.name if chat else str(cid)))
    out.sort(key=lambda c: c.name.lower())
    return out


def _member_chats(repository, user_id: int) -> list[_ChatRef]:
    """Все чаты, где юзер состоит (для предложений). Видимость по-прежнему
    ограничена своими чатами — чужие чаты юзеру не показываются."""
    user = next((u for u in repository.db.users if u.id == user_id), None)
    ids = list(dict.fromkeys(user.chat_ids)) if user and user.chat_ids else []
    out: list[_ChatRef] = []
    for cid in ids:
        chat = repository.get_chat(cid)
        out.append(_ChatRef(cid, chat.name if chat else str(cid)))
    out.sort(key=lambda c: c.name.lower())
    return out


def _user_display(repository, user_id: int) -> str:
    u = next((u for u in repository.db.users if u.id == user_id), None)
    if u is None:
        return str(user_id)
    if u.username:
        return f"@{u.username}"
    if u.first_name:
        return u.first_name
    return str(user_id)


def _render_rule_proposal(rule: Rule) -> str:
    """Краткая карточка правила для запроса в целевой чат — без списка других
    чатов (чтобы не светить их названия чужому админу)."""
    if 0 in rule.from_users:
        froms = "все"
    else:
        froms = ", ".join(str(i) for i in rule.from_users) or "—"
    return "\n".join([
        f"Шаблон: {rule.pattern.regex}",
        f"От: {froms}",
        f"Игнорировать регистр: {'да' if rule.pattern.ignore_case_flag else 'нет'}",
        f"Ответов: {len(rule.responses)}",
    ])


def _build_regex(raw: str, mode: str) -> str:
    if mode == "exact":
        return f"^{raw}$"
    return f".*{raw}.*"


def _equal_probabilities(n: int) -> list[int]:
    if n <= 0:
        return []
    base = 1000 // n
    rem = 1000 % n
    return [base + (1 if i < rem else 0) for i in range(n)]


def _validate_probs(vals: list[int], n: int) -> str | None:
    if len(vals) != n:
        return "Количество промилле не совпадает с числом ответов"
    if any(v < 0 or v > 1000 for v in vals):
        return "Каждое промилле должно быть от 0 до 1000"
    if sum(vals) > 1000:
        return "Сумма промилле не должна превышать 1000"
    return None


def _resp_short(r: Response) -> str:
    if r.reaction_emoji:
        return f"реакция {r.reaction_emoji}"
    if r.text:
        return (r.text[:24] + "…") if len(r.text) > 24 else r.text
    return "сообщение"


def _responses_list(responses: list[Response]) -> str:
    if not responses:
        return "(пока пусто)"
    return "\n".join(f"{i + 1}. {_resp_short(r)}" for i, r in enumerate(responses))


async def _safe_delete(msg) -> None:
    if msg is None:
        return
    try:
        await msg.delete()
    except Exception:
        pass


def _chat_name(repository, cid: int) -> str:
    chat = repository.get_chat(cid) if repository is not None else None
    return chat.name if chat else str(cid)


def _render_rule(rule: Rule, repository=None) -> str:
    chats = ", ".join(_chat_name(repository, c) for c in rule.chats) or "—"
    if 0 in rule.from_users:
        froms = "все"
    else:
        froms = ", ".join(str(i) for i in rule.from_users) or "—"
    return "\n".join([
        f"id: {rule.id}",
        f"Чаты: {chats}",
        f"От: {froms}",
        f"Шаблон: {rule.pattern.regex}",
        f"Игнорировать регистр: {'да' if rule.pattern.ignore_case_flag else 'нет'}",
        f"Ответов: {len(rule.responses)}",
    ])


# ── Кастомные шаги визарда ───────────────────────────────────────────────────


class _ChatPickerStep(Step):
    """Первый шаг add-визарда: мультивыбор чатов галочками."""

    PREFIX = "rule_chat"

    def __init__(self):
        self.is_waiting = False
        self.msg = None

    def _keyboard(self, context) -> tuple[Keyboard, list[_ChatRef]]:
        chats = _manageable_chats(context.repository, context.update.effective_user.id)
        selected = context.session_context.setdefault("chats", set())
        rows = [
            [Button(
                f"{'✅' if c.id in selected else '⬜'} {c.name}",
                callback_data=f"{self.PREFIX}|t|{c.id}",
            )]
            for c in chats
        ]
        rows.append([Button("Готово", callback_data=f"{self.PREFIX}|done")])
        return Keyboard(rows), chats

    async def _render(self, context, edit: bool = False) -> None:
        kb, chats = self._keyboard(context)
        if chats:
            text = "В каких чатах будет работать правило? Отметь галочками и жми «Готово»."
        else:
            text = (
                "Нет чатов, где ты админ. Назначь себя чат-админом через /settings"
                " в нужном чате и повтори."
            )
        if edit and self.msg is not None:
            try:
                await self.msg.edit_text(text, reply_markup=kb.to_markup())
                return
            except Exception:
                pass
        self.msg = await context.bot.send_message(
            context.update.effective_chat.id, text, reply_markup=kb.to_markup()
        )

    async def chat(self, context):
        if not self.is_waiting:
            context.session_context.setdefault("chats", set())
            await self._render(context)
            self.is_waiting = True
        return False

    async def callback(self, context):
        if not self.is_waiting:
            context.session_context.setdefault("chats", set())
            await self._render(context)
            self.is_waiting = True
            return False
        data = context.callback_query.data
        await context.callback_query.answer()
        if data.startswith(f"{self.PREFIX}|t|"):
            cid = int(data.rsplit("|", 1)[1])
            # Не доверяем callback_data: тоггл проходит только для чатов, где
            # юзер реально чат-админ (защита от сфабрикованного callback).
            allowed = {
                c.id
                for c in _manageable_chats(context.repository, context.update.effective_user.id)
            }
            if cid not in allowed:
                return False
            selected = context.session_context.setdefault("chats", set())
            selected.discard(cid) if cid in selected else selected.add(cid)
            await self._render(context, edit=True)
            return False
        if data == f"{self.PREFIX}|done":
            if not context.session_context.get("chats"):
                await context.bot.send_message(
                    context.update.effective_chat.id, "Выбери хотя бы один чат"
                )
                return False
            return True
        return False

    def stop(self):
        self.is_waiting = False


class _FromUsersStep(Step):
    """От кого реагировать: id через пробел или кнопка «От всех»."""

    PREFIX = "rule_from"

    def __init__(self):
        self.is_waiting = False
        self.prompt_msg = None

    async def _render(self, context) -> None:
        kb = Keyboard([[Button("От всех", callback_data=f"{self.PREFIX}|all")]])
        self.prompt_msg = await context.bot.send_message(
            context.update.effective_chat.id,
            "От кого реагировать? Пришли id пользователей через пробел или жми «От всех».",
            reply_markup=kb.to_markup(),
        )

    async def chat(self, context):
        if not self.is_waiting:
            await self._render(context)
            self.is_waiting = True
            return False
        parts = (context.message.text or "").split()
        try:
            ids = {int(p) for p in parts}
        except ValueError:
            await context.message.reply_text("id пользователей — целые числа")
            return False
        if not ids:
            await context.message.reply_text("Пусто. Пришли id или жми «От всех».")
            return False
        context.session_context["from_users"] = ids
        await _safe_delete(self.prompt_msg)
        await _safe_delete(context.message)
        return True

    async def callback(self, context):
        if not self.is_waiting:
            await self._render(context)
            self.is_waiting = True
            return False
        if context.callback_query.data == f"{self.PREFIX}|all":
            await context.callback_query.answer()
            context.session_context["from_users"] = {0}
            await _safe_delete(self.prompt_msg)
            return True
        return False

    def stop(self):
        self.is_waiting = False


class _PatternStep(Step):
    """Шаблон-regex с тоглом «в середине строки / точно»."""

    PREFIX = "rule_pat"

    def __init__(self):
        self.is_waiting = False
        self.prompt_msg = None

    def _mode(self, context) -> str:
        return context.session_context.setdefault("pattern_mode", "middle")

    def _keyboard(self, context) -> Keyboard:
        label = (
            "🔵 В середине строки" if self._mode(context) == "middle"
            else "🎯 Точное совпадение"
        )
        return Keyboard([[Button(label, callback_data=f"{self.PREFIX}|mode")]])

    async def _render(self, context, edit: bool = False) -> None:
        text = (
            "Пришли шаблон (регулярное выражение). Кнопкой переключи режим совпадения"
            " (в середине строки → к шаблону добавится .* по краям; точно → ^…$)."
        )
        kb = self._keyboard(context).to_markup()
        if edit and self.prompt_msg is not None:
            try:
                await self.prompt_msg.edit_text(text, reply_markup=kb)
                return
            except Exception:
                pass
        self.prompt_msg = await context.bot.send_message(
            context.update.effective_chat.id, text, reply_markup=kb
        )

    async def chat(self, context):
        if not self.is_waiting:
            self._mode(context)
            await self._render(context)
            self.is_waiting = True
            return False
        raw = (context.message.text or "").strip()
        if not raw:
            await context.message.reply_text("Пустой шаблон")
            return False
        try:
            re.compile(raw)
        except re.error:
            await context.message.reply_text("Некорректное регулярное выражение")
            return False
        context.session_context["pattern"] = _build_regex(raw, self._mode(context))
        context.session_context["pattern_raw"] = raw
        await _safe_delete(self.prompt_msg)
        await _safe_delete(context.message)
        return True

    async def callback(self, context):
        if not self.is_waiting:
            self._mode(context)
            await self._render(context)
            self.is_waiting = True
            return False
        if context.callback_query.data == f"{self.PREFIX}|mode":
            await context.callback_query.answer()
            cur = self._mode(context)
            context.session_context["pattern_mode"] = "exact" if cur == "middle" else "middle"
            await self._render(context, edit=True)
        return False

    def stop(self):
        self.is_waiting = False


class _CheckRegexpStep(Step):
    """Проверка шаблона: пользователь шлёт примеры, бот отвечает подходит/нет."""

    PREFIX = "rule_check"

    def __init__(self):
        self.is_first = True

    async def chat(self, context):
        if self.is_first:
            kb = Keyboard([[Button("Закончить", callback_data=f"{self.PREFIX}|done")]])
            await context.message.reply_text(
                "Проверка шаблона: пришли примеры сообщений, а потом жми «Закончить».",
                reply_markup=kb.to_markup(),
            )
            self.is_first = False
            return False
        if not context.message.text:
            await context.message.reply_text("Пустое сообщение")
            return False
        result = re.search(context.session_context["pattern"], context.message.text)
        await context.message.reply_text("Подходит" if result else "Не подходит")
        return False

    async def callback(self, context):
        if context.callback_query.data == f"{self.PREFIX}|done":
            await context.callback_query.answer()
            return True
        return False

    def stop(self):
        self.is_first = True


class _ResponsesStep(Step):
    """Сбор/редактирование ответов: список с номерами, кнопки удаления, реакция."""

    PREFIX = "rule_resp"

    def __init__(self):
        self.is_waiting = False
        self.is_waiting_for_reaction = False
        self.control_msg = None

    def _keyboard(self, responses: list[Response]) -> Keyboard:
        rows = [
            [Button(f"🗑 #{i + 1} {_resp_short(r)}", callback_data=f"{self.PREFIX}|del|{i}")]
            for i, r in enumerate(responses)
        ]
        rows.append([
            Button("➕ Реакция", callback_data=f"{self.PREFIX}|react"),
            Button("💾 Готово", callback_data=f"{self.PREFIX}|done"),
        ])
        return Keyboard(rows)

    async def _render(self, context, edit: bool = False) -> None:
        responses = context.session_context.setdefault("responses", [])
        text = (
            "Ответы на сообщение. Присылай сообщения / стикеры / медиа — каждое станет"
            " ответом. Реакцию добавь кнопкой. Лишнее удаляй кнопками 🗑.\n\n"
            + _responses_list(responses)
        )
        markup = self._keyboard(responses).to_markup()
        if edit and self.control_msg is not None:
            try:
                await self.control_msg.edit_text(text, reply_markup=markup)
                return
            except Exception:
                pass
        self.control_msg = await context.bot.send_message(
            context.update.effective_chat.id, text, reply_markup=markup
        )

    async def chat(self, context):
        if not self.is_waiting:
            context.session_context.setdefault("responses", [])
            await self._render(context)
            self.is_waiting = True
            return False
        msg = context.message
        context.session_context["responses"].append(
            Response(msg.chat_id, msg.message_id, 100)
        )
        await self._render(context, edit=True)
        return False

    async def callback(self, context):
        if not self.is_waiting:
            context.session_context.setdefault("responses", [])
            await self._render(context)
            self.is_waiting = True
            return False
        data = context.callback_query.data
        await context.callback_query.answer()
        if data == f"{self.PREFIX}|react":
            self.is_waiting_for_reaction = True
            await context.bot.send_message(
                context.update.effective_chat.id, "Поставь реакцию на это сообщение:"
            )
            return False
        if data.startswith(f"{self.PREFIX}|del|"):
            idx = int(data.rsplit("|", 1)[1])
            responses = context.session_context.get("responses", [])
            if 0 <= idx < len(responses):
                responses.pop(idx)
                await self._render(context, edit=True)
            return False
        if data == f"{self.PREFIX}|done":
            if not context.session_context.get("responses"):
                await context.bot.send_message(
                    context.update.effective_chat.id, "Нужен хотя бы один ответ"
                )
                return False
            return True
        return False

    async def reaction(self, context):
        if not self.is_waiting_for_reaction:
            return False
        new = context.message_reaction.new_reaction
        if not new:
            return False
        first = new[0]
        if not isinstance(first, ReactionTypeEmoji):
            await context.bot.send_message(
                context.message_reaction.chat.id, "Поддерживаются только обычные эмодзи"
            )
            return False
        context.session_context.setdefault("responses", []).append(
            Response(0, 0, 100, reaction_emoji=first.emoji)
        )
        self.is_waiting_for_reaction = False
        await self._render(context, edit=True)
        return False

    def stop(self):
        self.is_waiting = False
        self.is_waiting_for_reaction = False


class _ProbabilitiesStep(Step):
    """Промилле для ответов: ввод текстом или пресет «Равновероятно»."""

    PREFIX = "rule_prob"

    def __init__(self):
        self.is_waiting = False
        self.prompt_msg = None

    def _text(self, context) -> str:
        n = len(context.session_context.get("responses", []))
        return (
            f"Промилле для {n} ответов через пробел (100 = 10%, сумма ≤ 1000)."
            " Или жми «Равновероятно»."
        )

    async def _render(self, context) -> None:
        kb = Keyboard([[Button("⚖ Равновероятно", callback_data=f"{self.PREFIX}|equal")]])
        self.prompt_msg = await context.bot.send_message(
            context.update.effective_chat.id, self._text(context), reply_markup=kb.to_markup()
        )

    async def chat(self, context):
        if not self.is_waiting:
            await self._render(context)
            self.is_waiting = True
            return False
        parts = (context.message.text or "").split()
        try:
            vals = [int(p) for p in parts]
        except ValueError:
            await context.message.reply_text("Промилле — целые числа")
            return False
        err = _validate_probs(vals, len(context.session_context.get("responses", [])))
        if err:
            await context.message.reply_text(err)
            return False
        context.session_context["probabilities"] = vals
        return True

    async def callback(self, context):
        if not self.is_waiting:
            await self._render(context)
            self.is_waiting = True
            return False
        if context.callback_query.data == f"{self.PREFIX}|equal":
            await context.callback_query.answer()
            n = len(context.session_context.get("responses", []))
            context.session_context["probabilities"] = _equal_probabilities(n)
            return True
        return False

    def stop(self):
        self.is_waiting = False


class _IgnoreCaseStep(Step):
    """Игнорировать регистр — кнопками Да/Нет (рендерится с любого пути входа)."""

    PREFIX = "rule_ic"

    def __init__(self):
        self.is_waiting = False

    async def _render(self, context) -> None:
        kb = Keyboard([[
            Button("Да", callback_data=f"{self.PREFIX}|1"),
            Button("Нет", callback_data=f"{self.PREFIX}|0"),
        ]])
        await context.bot.send_message(
            context.update.effective_chat.id, "Игнорировать регистр?", reply_markup=kb.to_markup()
        )

    async def chat(self, context):
        if not self.is_waiting:
            await self._render(context)
            self.is_waiting = True
        return False

    async def callback(self, context):
        if not self.is_waiting:
            await self._render(context)
            self.is_waiting = True
            return False
        data = context.callback_query.data
        if data in (f"{self.PREFIX}|1", f"{self.PREFIX}|0"):
            await context.callback_query.answer()
            context.session_context["ignore_case_flag"] = int(data.rsplit("|", 1)[1])
            return True
        return False

    def stop(self):
        self.is_waiting = False


# ── Фича ─────────────────────────────────────────────────────────────────────


class RuleFeature(Feature):
    command = "rules"
    aliases = ("rule",)
    description = "Управление правилами-ответами"

    rules = collection("rules")

    # ── Команды ──────────────────────────────────────────────────────────────

    @subcommand("", description="Список правил", permission="rules.manage")
    async def list_(self, ctx: FeatureContext):
        rules = list(self.rules)
        if not rules:
            await ctx.reply("Правил нет")
            return
        text = "\n\n".join(_render_rule(r, ctx.repository) for r in rules)
        await ctx.reply(text, markdown=False)

    @subcommand("add", description="Добавить правило (сессия)", permission="rules.manage")
    async def add(self, ctx: FeatureContext):
        await self.start_wizard("rule:add", ctx)

    @subcommand("remove <ids:rest>", description="Удалить правила", permission="rules.manage")
    async def remove(self, ctx: FeatureContext, ids: str):
        for rule_id_str in ids.split():
            try:
                rule_id = int(rule_id_str)
            except ValueError:
                await ctx.reply(f"Ошибка. Id правила должно быть целым числом: {rule_id_str}")
                continue
            rule = self.rules.find_by(id=rule_id)
            if rule is None:
                await ctx.reply(f"Ошибка. Правила с id={rule_id} не существует")
            else:
                self.rules.remove(rule)
                await self.rules.save()
                await ctx.reply(f"Правило {rule_id} удалено")

    @subcommand("edit <rule_id:int>", description="Редактировать правило", permission="rules.manage")
    async def edit(self, ctx: FeatureContext, rule_id: int):
        rule = self.rules.find_by(id=rule_id)
        if rule is None:
            await ctx.reply("Правила с таким id не существует")
            return
        if not self._can_edit(ctx, rule):
            await ctx.reply("Это правило можно редактировать только из своих чатов.")
            return
        await self._render_edit_root(ctx, rule)

    @subcommand("<rule_id:int>", description="Просмотр правила", permission="rules.manage")
    async def view(self, ctx: FeatureContext, rule_id: int):
        rule = self.rules.find_by(id=rule_id)
        if rule is None:
            await ctx.reply("Правила с таким id не существует")
            return
        await ctx.reply(_render_rule(rule, ctx.repository), markdown=False)

    # ── Add-визард ───────────────────────────────────────────────────────────

    @wizard(
        "rule:add",
        step("chats", _ChatPickerStep()),
        step("from_users", _FromUsersStep()),
        step("pattern", _PatternStep()),
        step("regexp_check", _CheckRegexpStep()),
        step("responses", _ResponsesStep()),
        step("probabilities", _ProbabilitiesStep()),
        step("ignore_case_flag", _IgnoreCaseStep()),
    )
    async def on_add_done(self, ctx: FeatureContext, **state):
        responses = state.get("responses", [])
        probs = state.get("probabilities", [])
        for index, response in enumerate(responses):
            response.probability = probs[index] if index < len(probs) else 0
        # Скоуп ограничиваем чатами, которыми юзер реально управляет — даже если
        # в session_context просочился чужой чат через подделанный callback.
        allowed = {c.id for c in _manageable_chats(ctx.repository, ctx.user_id)}
        chats = set(state.get("chats") or set()) & allowed
        if not chats:
            await ctx.reply("Не выбрано ни одного твоего чата — правило не создано.")
            return
        new_rule = self.rules.add(
            Rule(
                id=0,
                from_users=set(state.get("from_users") or set()),
                pattern=RulePattern(
                    regex=state["pattern"],
                    ignore_case_flag=int(state.get("ignore_case_flag", 1)),
                ),
                responses=responses,
                tags=[],
                chats=chats,
            )
        )
        await self.rules.save()
        await ctx.reply(f"Правило добавлено с id {new_rule.id}")

    # ── Edit-меню ────────────────────────────────────────────────────────────

    def _cb(self, name: str, **values) -> str:
        return self.cb(f"rules:{name}")(**values)

    def _can_edit(self, ctx: FeatureContext, rule: Rule) -> bool:
        if ctx.repository.is_admin(ctx.user_id):
            return True
        return any(ctx.repository.is_chat_admin(ctx.user_id, c) for c in rule.chats)

    async def _render_edit_root(self, ctx: FeatureContext, rule: Rule, edit: bool = False):
        ic = "вкл" if rule.pattern.ignore_case_flag else "выкл"
        rows = [
            [Button("💬 Чаты", callback_data=self._cb("edit_chats", rule_id=rule.id))],
            [Button("👤 От кого", callback_data=self._cb("edit_from", rule_id=rule.id))],
            [Button("🔤 Шаблон", callback_data=self._cb("edit_pattern", rule_id=rule.id))],
            [Button(f"Aa Игнор регистра: {ic}", callback_data=self._cb("edit_ic", rule_id=rule.id))],
            [Button("📝 Ответы", callback_data=self._cb("edit_responses", rule_id=rule.id))],
        ]
        text = _render_rule(rule, ctx.repository)
        if edit:
            await ctx.edit(text, keyboard=Keyboard(rows), markdown=False)
        else:
            await ctx.reply(text, keyboard=Keyboard(rows), markdown=False)

    async def _guard(self, ctx: FeatureContext, rule_id: int) -> Rule | None:
        rule = self.rules.find_by(id=rule_id)
        if rule is None:
            await ctx.toast("Правило не найдено")
            return None
        if not self._can_edit(ctx, rule):
            await ctx.toast("Доступно только из своих чатов")
            return None
        return rule

    @on_callback("rules:edit_root", schema="<rule_id:int>")
    async def cb_edit_root(self, ctx: FeatureContext, rule_id: int):
        rule = await self._guard(ctx, rule_id)
        if rule is None:
            return
        await self._render_edit_root(ctx, rule, edit=True)

    async def _render_chat_editor(self, ctx: FeatureContext, rule: Rule):
        chats = _member_chats(ctx.repository, ctx.user_id)
        rows = []
        for c in chats:
            is_admin = ctx.repository.is_chat_admin(ctx.user_id, c.id)
            in_scope = c.id in rule.chats
            if is_admin:
                # Свой чат — добавляем/убираем сразу.
                mark = "✅" if in_scope else "❌"
                cb = self._cb("chat_toggle", rule_id=rule.id, chat_id=c.id)
            elif in_scope:
                # Не свой, но уже подключён — убрать может только их админ.
                mark = "✅🔒"
                cb = self._cb("chat_propose", rule_id=rule.id, chat_id=c.id)
            else:
                # Не свой и не подключён — можно предложить (нужно подтверждение).
                mark = "📨"
                cb = self._cb("chat_propose", rule_id=rule.id, chat_id=c.id)
            rows.append([Button(f"{mark} {c.name}", callback_data=cb)])
        rows.append([Button("⏎ Назад", callback_data=self._cb("edit_root", rule_id=rule.id))])
        text = (
            "Чаты правила. ✅ — входит, ❌ — нет (твои чаты, жми чтобы вкл/выкл).\n"
            "📨 — предложить чужому чату (нужно подтверждение их чат-админа).\n"
            "🔒 — убрать может только их админ."
        )
        await ctx.edit(text, keyboard=Keyboard(rows), markdown=False)

    @on_callback("rules:edit_chats", schema="<rule_id:int>")
    async def cb_edit_chats(self, ctx: FeatureContext, rule_id: int):
        rule = await self._guard(ctx, rule_id)
        if rule is None:
            return
        await self._render_chat_editor(ctx, rule)

    @on_callback("rules:chat_toggle", schema="<rule_id:int>|<chat_id:int>")
    async def cb_chat_toggle(self, ctx: FeatureContext, rule_id: int, chat_id: int):
        rule = await self._guard(ctx, rule_id)
        if rule is None:
            return
        if not ctx.repository.is_chat_admin(ctx.user_id, chat_id):
            await ctx.toast("Это не твой чат")
            return
        rule.chats.discard(chat_id) if chat_id in rule.chats else rule.chats.add(chat_id)
        await self.rules.save()
        await self._render_chat_editor(ctx, rule)

    @on_callback("rules:chat_propose", schema="<rule_id:int>|<chat_id:int>")
    async def cb_chat_propose(self, ctx: FeatureContext, rule_id: int, chat_id: int):
        rule = await self._guard(ctx, rule_id)
        if rule is None:
            return
        if ctx.repository.is_chat_admin(ctx.user_id, chat_id):
            await ctx.toast("Это твой чат — жми ✅/❌, подтверждение не нужно")
            return
        if chat_id in rule.chats:
            await ctx.toast("Чат уже в скоупе; убрать может только его админ")
            return
        by = _user_display(ctx.repository, ctx.user_id)
        kb = Keyboard.row(
            Button(
                "✅ Подтвердить",
                callback_data=self._cb("prop_accept", rule_id=rule_id, chat_id=chat_id, by=ctx.user_id),
            ),
            Button(
                "❌ Отклонить",
                callback_data=self._cb("prop_decline", rule_id=rule_id, chat_id=chat_id, by=ctx.user_id),
            ),
        )
        text = (
            "📌 Запрос на правило-ответ\n\n"
            f"{by} предлагает включить в этом чате правило #{rule_id}:\n\n"
            f"{_render_rule_proposal(rule)}\n\n"
            "Подтвердить может только чат-админ этого чата."
        )
        try:
            await ctx.send_to(chat_id, text, keyboard=kb, markdown=False)
        except Exception:
            logger.exception("rule %s: failed to deliver proposal to %s", rule_id, chat_id)
            await ctx.toast("Не удалось отправить запрос в чат")
            return
        await ctx.toast("Запрос отправлен, ждём подтверждения их чат-админа")

    @on_callback("rules:prop_accept", schema="<rule_id:int>|<chat_id:int>|<by:int>")
    async def cb_prop_accept(self, ctx: FeatureContext, rule_id: int, chat_id: int, by: int):
        if ctx.chat_id != chat_id:
            await ctx.toast("Этот запрос не для этого чата")
            return
        if not ctx.repository.is_chat_admin(ctx.user_id, ctx.chat_id):
            await ctx.toast("Подтвердить может только чат-админ этого чата")
            return
        rule = self.rules.find_by(id=rule_id)
        if rule is None:
            await ctx.edit("Правило больше не существует.")
            return
        if chat_id in rule.chats:
            await ctx.edit(f"Правило #{rule_id} уже подключено к этому чату.")
            return
        rule.chats.add(chat_id)
        await self.rules.save()
        await ctx.edit(f"✅ Правило #{rule_id} подключено к этому чату.")
        await self._notify_user(
            by, f"✅ Чат «{_chat_name(ctx.repository, chat_id)}» подтвердил правило #{rule_id}."
        )

    @on_callback("rules:prop_decline", schema="<rule_id:int>|<chat_id:int>|<by:int>")
    async def cb_prop_decline(self, ctx: FeatureContext, rule_id: int, chat_id: int, by: int):
        if ctx.chat_id != chat_id:
            await ctx.toast("Этот запрос не для этого чата")
            return
        if not ctx.repository.is_chat_admin(ctx.user_id, ctx.chat_id):
            await ctx.toast("Отклонить может только чат-админ этого чата")
            return
        await ctx.edit(f"❌ Запрос на правило #{rule_id} отклонён.")
        await self._notify_user(
            by, f"❌ Чат «{_chat_name(ctx.repository, chat_id)}» отклонил правило #{rule_id}."
        )

    async def _notify_user(self, user_id: int, text: str) -> None:
        try:
            await self.bot.send_message(user_id, text)
        except Exception:
            logger.debug("could not DM user %s", user_id)

    @on_callback("rules:edit_ic", schema="<rule_id:int>")
    async def cb_edit_ic(self, ctx: FeatureContext, rule_id: int):
        rule = await self._guard(ctx, rule_id)
        if rule is None:
            return
        rule.pattern.ignore_case_flag = 0 if rule.pattern.ignore_case_flag else 1
        await self.rules.save()
        await self._render_edit_root(ctx, rule, edit=True)

    @on_callback("rules:edit_from", schema="<rule_id:int>")
    async def cb_edit_from(self, ctx: FeatureContext, rule_id: int):
        rule = await self._guard(ctx, rule_id)
        if rule is None:
            return
        await self.start_wizard("rules:edit_from", ctx, rule_id=rule_id)

    @wizard("rules:edit_from", step("from_users", _FromUsersStep()))
    async def edit_from_done(self, ctx: FeatureContext, rule_id, from_users, **_):
        rule = self.rules.find_by(id=rule_id)
        if rule is None:
            await ctx.reply("Правило не найдено")
            return
        rule.from_users = set(from_users)
        await self.rules.save()
        await ctx.reply("«От кого» обновлено")

    @on_callback("rules:edit_pattern", schema="<rule_id:int>")
    async def cb_edit_pattern(self, ctx: FeatureContext, rule_id: int):
        rule = await self._guard(ctx, rule_id)
        if rule is None:
            return
        await self.start_wizard("rules:edit_pattern", ctx, rule_id=rule_id)

    @wizard(
        "rules:edit_pattern",
        step("pattern", _PatternStep()),
        step("regexp_check", _CheckRegexpStep()),
    )
    async def edit_pattern_done(self, ctx: FeatureContext, rule_id, pattern, **_):
        rule = self.rules.find_by(id=rule_id)
        if rule is None:
            await ctx.reply("Правило не найдено")
            return
        rule.pattern.regex = pattern
        await self.rules.save()
        await ctx.reply("Шаблон обновлён")

    @on_callback("rules:edit_responses", schema="<rule_id:int>")
    async def cb_edit_responses(self, ctx: FeatureContext, rule_id: int):
        rule = await self._guard(ctx, rule_id)
        if rule is None:
            return
        await self.start_session(
            [_ResponsesStep(), _ProbabilitiesStep()],
            ctx,
            on_done=type(self)._edit_responses_done,
            responses=list(rule.responses),
            rule_id=rule_id,
        )

    async def _edit_responses_done(
        self, ctx: FeatureContext, responses, probabilities, rule_id, **_
    ):
        rule = self.rules.find_by(id=rule_id)
        if rule is None:
            await ctx.reply("Правило не найдено")
            return
        for index, response in enumerate(responses):
            response.probability = probabilities[index] if index < len(probabilities) else 0
        rule.responses = responses
        await self.rules.save()
        await ctx.reply("Ответы обновлены")
