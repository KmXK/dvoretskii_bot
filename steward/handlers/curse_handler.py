from steward.bot.context import ChatBotContext
from steward.handlers.command_handler import CommandHandler
from steward.handlers.handler import Handler
from steward.helpers.command_validation import ValidationArgumentsError, validate_command_msg


def _parse_words(raw: str) -> list[str]:
    words = []
    seen = set()
    for word in raw.split():
        normalized = word.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            words.append(normalized)
    return words


class CurseWordListViewHandler(Handler):
    async def chat(self, context: ChatBotContext):
        validation = validate_command_msg(
            context.update,
            "curse",
            r"(?P<args>.*)?",
        )
        if not validation:
            return False

        args = ((validation.args or {}).get("args") or "").strip()
        if args == "":
            raise ValidationArgumentsError()

        if args.startswith("word_list add ") or args.startswith("word_list remove "):
            return False

        if args != "word_list":
            raise ValidationArgumentsError()

        words = sorted(self.repository.db.curse_words)
        if not words:
            await context.message.reply_text("Список матерных слов пуст.")
            return True

        await context.message.reply_text("Матерные слова:\n\n" + "\n".join(words))
        return True

    def help(self):
        return "/curse word_list [add <слова через пробел>|remove <слова через пробел>] - управлять списком матерных слов"

    def prompt(self):
        return (
            "▶ /curse — управление списком матерных слов\n"
            "  Список: /curse word_list\n"
            "  Добавить: /curse word_list add <слова через пробел>\n"
            "  Удалить: /curse word_list remove <слова через пробел>"
        )


@CommandHandler(
    "curse",
    only_admin=True,
    arguments_template=r"word_list add (?P<words>.+)",
)
class CurseWordListAddHandler(Handler):
    async def chat(self, context: ChatBotContext, words: str):
        items = _parse_words(words)
        if not items:
            raise ValidationArgumentsError()

        added = []
        for word in items:
            if word not in self.repository.db.curse_words:
                self.repository.db.curse_words.add(word)
                added.append(word)

        if not added:
            await context.message.reply_text("Все слова уже есть в списке.")
            return True

        await self.repository.save()
        await context.message.reply_text("Добавлены слова: " + ", ".join(added))
        return True

    def help(self):
        return None


@CommandHandler(
    "curse",
    only_admin=True,
    arguments_template=r"word_list remove (?P<words>.+)",
)
class CurseWordListRemoveHandler(Handler):
    async def chat(self, context: ChatBotContext, words: str):
        items = _parse_words(words)
        if not items:
            raise ValidationArgumentsError()

        removed = []
        for word in items:
            if word in self.repository.db.curse_words:
                self.repository.db.curse_words.remove(word)
                removed.append(word)

        if not removed:
            await context.message.reply_text("Ни одно слово не найдено в списке.")
            return True

        await self.repository.save()
        await context.message.reply_text("Удалены слова: " + ", ".join(removed))
        return True

    def help(self):
        return None
