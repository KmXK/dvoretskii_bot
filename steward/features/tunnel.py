import logging
import re

from telegram import ReactionTypeEmoji

from steward.data.models.chat_tunnel import ChatTunnel, TunnelMessage
from steward.framework import (
    INITIATOR_ONLY,
    Feature,
    FeatureContext,
    Keyboard,
    collection,
    on_callback,
    on_message,
    subcommand,
)

logger = logging.getLogger(__name__)

OK_EMOJI = "👌"
# Сколько последних маппингов сообщений держим на один туннель (для реплаев).
MAX_MESSAGES_PER_TUNNEL = 500
# Ограничение на размер inline-списка чатов в /tunnel to.
MAX_PICK_BUTTONS = 30

# Команда в подписи к медиа: «/tunnel 4 текст» (телеграм не считает её командой,
# поэтому ловим вручную в on_message по caption).
_CAPTION_CMD_RE = re.compile(r"^/tunnel(?:@\w+)?\s+(\d+)(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)


HELP_TEXT = """\
/tunnel — туннели между чатами: связать два чата и пересылать сообщения.

Как создать туннель (по шагам):
  1. В чате, КУДА хотите пускать сообщения, чатадмин пишет:  /tunnel open
     (этим чат становится виден в списке для подключения)
  2. В своём чате любой участник пишет:  /tunnel to
  3. Бот покажет список открытых чатов — выберите нужный кнопкой.
  4. В выбранный чат придёт запрос с кнопками «Согласиться / Отклонить».
     Нажать может только чатадмин того чата.
  5. Если согласились — в ОБА чата придёт номер туннеля (например #4),
     а вам в чат вернётся подтверждение, что подключение приняли (или отклонили).

Как пользоваться:
  • Отправить текст:            /tunnel 4 привет, как дела
  • Отправить медиа:            прикрепите фото/видео/гифку и в подписи
    напишите /tunnel 4 (можно с текстом: /tunnel 4 смотри сюда)
  • Переслать любое сообщение:  сделайте reply на ЛЮБОЕ сообщение в чате
    (своё фото, чужой текст, стикер, голосовое…) и напишите /tunnel 4 —
    это сообщение улетит в другой чат, а на ваш reply встанет 👌
  • Ответить на пришедшее:      сделайте reply на сообщение из туннеля —
    ответ улетит обратно. В ответе можно слать что угодно: текст, фото,
    видео, стикеры, голосовые — всё перешлётся в другой чат.
  • Дописать к отправленному:    сделайте reply на своё же сообщение,
    ушедшее в туннель (на нём стоит 👌), и допишите — улетит туда же,
    команду повторять не нужно.
  • Альбом (несколько фото/видео): реплайните на альбом и напишите
    /tunnel <id> — перешлётся весь альбом целиком, а не одна картинка.
  • Список туннелей этого чата:  /tunnel   (или /tunnel list)
  • Удалить туннель (чатадмин):  /tunnel rm 4
  • Перестать принимать запросы: /tunnel close

Команды:
  /tunnel open            — открыть чат для подключений (чатадмин)
  /tunnel to              — начать подключение к другому чату
  /tunnel <id> <текст>    — переслать текст по туннелю
  /tunnel <id>            — reply на сообщение → переслать его по туннелю
  /tunnel list            — туннели этого чата
  /tunnel rm <id>         — удалить туннель (чатадмин)
  /tunnel close           — закрыть чат для новых подключений (чатадмин)
  /tunnel help            — эта справка\
"""


class TunnelFeature(Feature):
    """Двунаправленные туннели сообщений между чатами.

    `/tunnel open` помечает чат как открытый для подключений. `/tunnel to`
    показывает список открытых чатов; выбор шлёт запрос в целевой чат, где
    чатадмин жмёт «Согласиться/Отклонить». После согласия туннель получает
    числовой id, и любой участник любой из сторон может слать
    `/tunnel <id> текст`. Реплай на пришедшее сообщение доставляется обратно
    автору исходного, а на сам реплай ставится 👌.
    """

    command = "tunnel"
    description = "Туннели между чатами"
    custom_help = HELP_TEXT
    help_examples = [
        "«открой чат для туннелей» → /tunnel open",
        "«подключиться к другому чату» → /tunnel to",
        "«напиши в туннель 4 привет» → /tunnel 4 привет",
        "«покажи туннели чата» → /tunnel",
        "«удали туннель 4» → /tunnel rm 4",
    ]

    tunnels = collection("chat_tunnels")
    tmsgs = collection("tunnel_messages")
    open_chats = collection("tunnel_open_chats")
    chats = collection("chats")
    users = collection("users")

    # ------------------------------------------------------------------ #
    # Open / close
    # ------------------------------------------------------------------ #

    @subcommand("open", description="Открыть чат для подключений (чатадмин)")
    async def open_chat(self, ctx: FeatureContext):
        if not ctx.repository.is_chat_admin(ctx.user_id, ctx.chat_id):
            await ctx.reply("Открыть чат для туннелей может только чатадмин.")
            return
        if self.open_chats.contains(ctx.chat_id):
            await ctx.reply("Этот чат уже открыт для подключений.")
            return
        self.open_chats.add(ctx.chat_id)
        await self.open_chats.save()
        await ctx.reply(
            "Чат открыт для подключений. Теперь он виден в /tunnel to из других чатов.\n"
            "Закрыть: /tunnel close"
        )

    @subcommand("close", description="Закрыть чат для новых подключений (чатадмин)")
    async def close_chat(self, ctx: FeatureContext):
        if not ctx.repository.is_chat_admin(ctx.user_id, ctx.chat_id):
            await ctx.reply("Закрыть чат может только чатадмин.")
            return
        if not self.open_chats.contains(ctx.chat_id):
            await ctx.reply("Этот чат и так не открыт для подключений.")
            return
        self.open_chats.remove(ctx.chat_id)
        await self.open_chats.save()
        await ctx.reply(
            "Чат закрыт для новых подключений. Существующие туннели продолжают работать."
        )

    # ------------------------------------------------------------------ #
    # Initiate connection
    # ------------------------------------------------------------------ #

    @subcommand("to", description="Подключиться к другому чату")
    async def connect_to(self, ctx: FeatureContext):
        candidates = self._candidate_open_chats(ctx.chat_id)
        if not candidates:
            await ctx.reply(
                "Нет доступных чатов для подключения.\n\n"
                "Чтобы чат появился здесь, его чатадмин должен выполнить там /tunnel open."
            )
            return
        buttons = [
            self.cb("tunnel:pick").button(
                self._chat_name(cid), target=cid, initiator=ctx.user_id
            )
            for cid in candidates[:MAX_PICK_BUTTONS]
        ]
        await ctx.reply(
            "Выберите чат, к которому хотите подключиться:",
            keyboard=Keyboard.column(*buttons),
        )

    @on_callback(
        "tunnel:pick",
        schema="<target:int>|<initiator:int>",
        access=INITIATOR_ONLY,
    )
    async def on_pick(self, ctx: FeatureContext, target: int, initiator: int):
        from_chat = ctx.chat_id
        if target == from_chat:
            await ctx.toast("Нельзя подключить чат к самому себе.")
            return
        if self._tunnel_between(from_chat, target) is not None:
            await ctx.edit("Туннель с этим чатом уже существует.")
            return
        if not self.open_chats.contains(target):
            await ctx.edit("Этот чат больше не принимает подключения.")
            return

        from_name = self._chat_name(from_chat)
        by_name = self._user_name(initiator)
        kb = Keyboard.row(
            self.cb("tunnel:accept").button(
                "✅ Согласиться", from_chat=from_chat, to_chat=target, by=initiator
            ),
            self.cb("tunnel:decline").button(
                "❌ Отклонить", from_chat=from_chat, to_chat=target, by=initiator
            ),
        )
        try:
            await ctx.send_to(
                target,
                (
                    "🔗 Запрос на туннель\n\n"
                    f"Чат «{from_name}» хочет связаться с этим чатом.\n"
                    f"Запросил: {by_name}\n\n"
                    "Принять или отклонить может только чатадмин этого чата."
                ),
                keyboard=kb,
                markdown=False,
            )
        except Exception:
            logger.exception("failed to deliver tunnel request to %s", target)
            await ctx.edit(
                "Не удалось отправить запрос в выбранный чат — возможно, бот там больше не состоит."
            )
            return

        await ctx.edit(
            f"📨 Запрос отправлен в чат «{self._chat_name(target)}». "
            "Ждём подтверждения от их чатадмина."
        )

    # ------------------------------------------------------------------ #
    # Accept / decline (in the target chat)
    # ------------------------------------------------------------------ #

    @on_callback(
        "tunnel:accept",
        schema="<from_chat:int>|<to_chat:int>|<by:int>",
    )
    async def on_accept(self, ctx: FeatureContext, from_chat: int, to_chat: int, by: int):
        if not ctx.repository.is_chat_admin(ctx.user_id, ctx.chat_id):
            await ctx.toast("Подтвердить может только чатадмин этого чата.")
            return
        if from_chat == to_chat:
            await ctx.edit("Нельзя подключить чат к самому себе.")
            return

        existing = self._tunnel_between(from_chat, to_chat)
        if existing is not None:
            await ctx.edit(f"Туннель с этим чатом уже существует (#{existing.id}).")
            return

        from_name = self._chat_name(from_chat)
        to_name = self._chat_name(to_chat)
        tunnel = self.tunnels.add(
            ChatTunnel(
                id=0,
                chat_a=from_chat,
                chat_b=to_chat,
                chat_a_name=from_name,
                chat_b_name=to_name,
                created_by=by,
            )
        )
        await self.tunnels.save()

        await ctx.edit(
            f"✅ Туннель #{tunnel.id} с чатом «{from_name}» создан.\n"
            f"Пишите: /tunnel {tunnel.id} ваш текст"
        )
        await self._notify(
            ctx,
            from_chat,
            f"✅ Чат «{to_name}» принял подключение!\n"
            f"Туннель #{tunnel.id} готов. Пишите: /tunnel {tunnel.id} ваш текст",
        )

    @on_callback(
        "tunnel:decline",
        schema="<from_chat:int>|<to_chat:int>|<by:int>",
    )
    async def on_decline(self, ctx: FeatureContext, from_chat: int, to_chat: int, by: int):
        if not ctx.repository.is_chat_admin(ctx.user_id, ctx.chat_id):
            await ctx.toast("Отклонить может только чатадмин этого чата.")
            return
        from_name = self._chat_name(from_chat)
        to_name = self._chat_name(to_chat)
        await ctx.edit(f"❌ Запрос от чата «{from_name}» отклонён.")
        await self._notify(ctx, from_chat, f"❌ Чат «{to_name}» отклонил подключение.")

    # ------------------------------------------------------------------ #
    # List / remove
    # ------------------------------------------------------------------ #

    @subcommand("", description="Туннели этого чата")
    async def list_default(self, ctx: FeatureContext):
        await self._list(ctx)

    @subcommand("list", description="Туннели этого чата")
    async def list_alias(self, ctx: FeatureContext):
        await self._list(ctx)

    @subcommand("help", description="Подробная справка")
    async def help_cmd(self, ctx: FeatureContext):
        await ctx.reply(HELP_TEXT, markdown=False)

    @subcommand("rm <id:int>", description="Удалить туннель (чатадмин)")
    async def remove(self, ctx: FeatureContext, id: int):
        await self._remove(ctx, id)

    @subcommand("delete <id:int>", description="Удалить туннель (чатадмин)")
    async def remove_alt(self, ctx: FeatureContext, id: int):
        await self._remove(ctx, id)

    async def _list(self, ctx: FeatureContext):
        mine = [t for t in self.tunnels if t.involves(ctx.chat_id)]
        if not mine:
            await ctx.reply(
                "В этом чате нет туннелей.\n\n"
                "Создать: /tunnel to (нужно, чтобы целевой чат сделал /tunnel open).\n"
                "Подробнее: /tunnel help",
                markdown=False,
            )
            return
        lines = ["Туннели этого чата:", ""]
        for t in sorted(mine, key=lambda x: x.id):
            other = t.other_side(ctx.chat_id)
            lines.append(
                f"#{t.id} → «{self._chat_name(other)}» "
                f"(создал {self._user_name(t.created_by)})"
            )
        lines.append("")
        lines.append("Написать: /tunnel <id> текст · Удалить: /tunnel rm <id>")
        await ctx.reply("\n".join(lines), markdown=False)

    async def _remove(self, ctx: FeatureContext, tunnel_id: int):
        tunnel = self.tunnels.find_by(id=tunnel_id)
        if tunnel is None or not tunnel.involves(ctx.chat_id):
            await ctx.reply("Туннель не найден в этом чате.")
            return
        if not ctx.repository.is_chat_admin(ctx.user_id, ctx.chat_id):
            await ctx.reply("Удалять туннели может только чатадмин.")
            return
        other = tunnel.other_side(ctx.chat_id)
        this_name = self._chat_name(ctx.chat_id)
        self.tunnels.remove(tunnel)
        self.tmsgs.replace_all(
            [m for m in self.tmsgs if m.tunnel_id != tunnel_id]
        )
        await self.tunnels.save()
        await ctx.reply(f"Туннель #{tunnel_id} удалён.")
        if other is not None:
            await self._notify(
                ctx, other, f"Туннель #{tunnel_id} с чатом «{this_name}» был удалён."
            )

    # ------------------------------------------------------------------ #
    # Send through tunnel
    # ------------------------------------------------------------------ #

    @subcommand("<id:int> <message:rest>", description="Переслать сообщение по туннелю")
    async def send(self, ctx: FeatureContext, id: int, message: str):
        tunnel = self.tunnels.find_by(id=id)
        if tunnel is None or not tunnel.involves(ctx.chat_id):
            await ctx.reply("Туннель не найден в этом чате. Список: /tunnel list")
            return
        target = tunnel.other_side(ctx.chat_id)
        if target is None:
            await ctx.reply("Туннель не найден в этом чате.")
            return

        try:
            sent = await ctx.send_to(
                target,
                f"{self._header(ctx, '💬')}\n{message}",
                markdown=False,
            )
        except Exception:
            logger.exception("tunnel %s: failed to forward to %s", id, target)
            await ctx.reply("Не удалось доставить сообщение — возможно, бот выгнан из того чата.")
            return

        self._record_message(
            tunnel_id=id,
            src_chat=ctx.chat_id,
            src_msg_id=ctx.message.message_id if ctx.message else 0,
            dst_chat=target,
            dst_msg_id=sent.message_id,
            sender_id=ctx.user_id,
        )
        await self.tmsgs.save()
        await self._react_ok(ctx.chat_id, ctx.message.message_id if ctx.message else None)

    @subcommand("<id:int>", description="Reply на сообщение → переслать его по туннелю")
    async def send_reply(self, ctx: FeatureContext, id: int):
        msg = ctx.message
        reply = msg.reply_to_message if msg else None
        if reply is None:
            await ctx.reply(
                f"Чтобы что-то отправить по туннелю #{id}: либо напишите текст "
                f"(/tunnel {id} привет), либо ответьте (reply) на сообщение "
                f"и напишите /tunnel {id} — это сообщение перешлётся в другой чат."
            )
            return
        tunnel = self.tunnels.find_by(id=id)
        if tunnel is None or not tunnel.involves(ctx.chat_id):
            await ctx.reply("Туннель не найден в этом чате. Список: /tunnel list")
            return
        target = tunnel.other_side(ctx.chat_id)
        if target is None:
            await ctx.reply("Туннель не найден в этом чате.")
            return

        header = self._header(ctx, "💬")
        try:
            if self._album_id(reply) is not None:
                # Реплай на альбом (несколько фото/видео одной новостью): тянем
                # все части и пересылаем группой, сохраняя их подписи.
                ids = await self._album_message_ids(ctx, reply)
                dst_ids = await self._relay_album(
                    ctx, target, header, src_chat=ctx.chat_id, message_ids=ids
                )
                self._record_album(id, ctx.chat_id, ids, target, dst_ids, ctx.user_id)
            else:
                dst_msg_id = await self._relay(ctx, target, header, copy_from=reply)
                self._record_message(
                    tunnel_id=id,
                    src_chat=ctx.chat_id,
                    src_msg_id=reply.message_id,
                    dst_chat=target,
                    dst_msg_id=dst_msg_id,
                    sender_id=ctx.user_id,
                )
        except Exception:
            logger.exception("tunnel %s: failed to forward replied message to %s", id, target)
            await ctx.reply("Не удалось доставить сообщение — возможно, бот выгнан из того чата.")
            return

        await self.tmsgs.save()
        await self._react_ok(ctx.chat_id, msg.message_id if msg else None)

    # ------------------------------------------------------------------ #
    # Media with a command in the caption: «/tunnel 4 текст» on a photo/video
    # ------------------------------------------------------------------ #

    @on_message
    async def forward_caption(self, ctx: FeatureContext) -> bool:
        msg = ctx.message
        if msg is None:
            return False
        parsed = self._caption_command(msg)
        if parsed is None:
            return False
        tunnel_id, body = parsed

        tunnel = self.tunnels.find_by(id=tunnel_id)
        if tunnel is None or not tunnel.involves(ctx.chat_id):
            await ctx.reply("Туннель не найден в этом чате. Список: /tunnel list")
            return True
        target = tunnel.other_side(ctx.chat_id)
        if target is None:
            await ctx.reply("Туннель не найден в этом чате.")
            return True

        header = self._header(ctx, "💬")
        try:
            if self._album_id(msg) is not None:
                # Альбом с командой в подписи: подпись «/tunnel N text» — это
                # команда, поэтому подписи частей убираем (remove_caption), а
                # текст пользователя уносим в шапку.
                ids = await self._album_message_ids(ctx, msg)
                dst_ids = await self._relay_album(
                    ctx, target, header, src_chat=ctx.chat_id, message_ids=ids,
                    body=body or None, strip_captions=True,
                )
                self._record_album(tunnel_id, ctx.chat_id, ids, target, dst_ids, ctx.user_id)
            else:
                dst_msg_id = await self._relay(ctx, target, header, copy_from=msg, text=body)
                self._record_message(
                    tunnel_id=tunnel_id,
                    src_chat=ctx.chat_id,
                    src_msg_id=msg.message_id,
                    dst_chat=target,
                    dst_msg_id=dst_msg_id,
                    sender_id=ctx.user_id,
                )
        except Exception:
            logger.exception("tunnel %s: failed to forward media to %s", tunnel_id, target)
            await ctx.reply("Не удалось доставить сообщение — возможно, бот выгнан из того чата.")
            return True

        await self.tmsgs.save()
        await self._react_ok(ctx.chat_id, msg.message_id)
        return True

    # ------------------------------------------------------------------ #
    # Reply forwarding (back through the tunnel)
    # ------------------------------------------------------------------ #

    @on_message
    async def forward_reply(self, ctx: FeatureContext) -> bool:
        msg = ctx.message
        if msg is None:
            return False
        # Команды идут своим путём; не пересылаем их как ответы.
        if msg.text and msg.text.startswith("/"):
            return False
        # Медиа с командой в подписи обрабатывает forward_caption.
        if self._caption_command(msg) is not None:
            return False
        reply = msg.reply_to_message
        if reply is None:
            return False

        # Реплай может быть как на пришедшее из туннеля сообщение (dst-сторона),
        # так и на своё же отправленное в туннель (src-сторона) — последнее даёт
        # возможность дописать к отправленному, не повторяя /tunnel <id>.
        mapping = self.tmsgs.find_one(
            lambda m: m.dst_chat == ctx.chat_id and m.dst_msg_id == reply.message_id
        )
        if mapping is not None:
            target_chat = mapping.src_chat
            reply_to = mapping.src_msg_id or None
        else:
            mapping = self.tmsgs.find_one(
                lambda m: m.src_chat == ctx.chat_id and m.src_msg_id == reply.message_id
            )
            if mapping is None:
                return False
            target_chat = mapping.dst_chat
            reply_to = mapping.dst_msg_id or None

        header = self._header(ctx)
        try:
            if self._album_id(msg) is not None:
                ids = await self._album_message_ids(ctx, msg)
                dst_ids = await self._relay_album(
                    ctx, target_chat, header,
                    src_chat=ctx.chat_id, message_ids=ids, reply_to=reply_to,
                )
                self._record_album(
                    mapping.tunnel_id, ctx.chat_id, ids, target_chat, dst_ids, ctx.user_id
                )
            else:
                dst_msg_id = await self._relay(
                    ctx, target_chat, header, copy_from=msg, reply_to=reply_to
                )
                # Цепочка реплаев работает в обе стороны: запоминаем новую пару.
                self._record_message(
                    tunnel_id=mapping.tunnel_id,
                    src_chat=ctx.chat_id,
                    src_msg_id=msg.message_id,
                    dst_chat=target_chat,
                    dst_msg_id=dst_msg_id,
                    sender_id=ctx.user_id,
                )
        except Exception:
            logger.exception(
                "tunnel %s: failed to deliver reply to %s",
                mapping.tunnel_id,
                target_chat,
            )
            return True

        await self.tmsgs.save()
        await self._react_ok(ctx.chat_id, msg.message_id)
        return True

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _candidate_open_chats(self, current: int) -> list[int]:
        connected = set()
        for t in self.tunnels:
            if t.chat_a == current:
                connected.add(t.chat_b)
            elif t.chat_b == current:
                connected.add(t.chat_a)
        out = []
        for cid in self.open_chats.all():
            if cid == current or cid in connected:
                continue
            out.append(cid)
        out.sort(key=lambda c: self._chat_name(c).lower())
        return out

    def _tunnel_between(self, a: int, b: int) -> ChatTunnel | None:
        return self.tunnels.find_one(lambda t: t.involves(a) and t.involves(b))

    def _record_message(
        self,
        *,
        tunnel_id: int,
        src_chat: int,
        src_msg_id: int,
        dst_chat: int,
        dst_msg_id: int,
        sender_id: int,
    ) -> None:
        self.tmsgs.add(
            TunnelMessage(
                tunnel_id=tunnel_id,
                src_chat=src_chat,
                src_msg_id=src_msg_id,
                dst_chat=dst_chat,
                dst_msg_id=dst_msg_id,
                sender_id=sender_id,
            )
        )
        self._prune(tunnel_id)

    def _record_album(
        self,
        tunnel_id: int,
        src_chat: int,
        src_ids: list[int],
        dst_chat: int,
        dst_ids: list[int],
        sender_id: int,
    ) -> None:
        """Запомнить маппинг для каждой части альбома — тогда реплай на любую из
        доставленных частей корректно уходит обратно по туннелю."""
        for src_id, dst_id in zip(src_ids, dst_ids):
            self._record_message(
                tunnel_id=tunnel_id,
                src_chat=src_chat,
                src_msg_id=src_id,
                dst_chat=dst_chat,
                dst_msg_id=dst_id,
                sender_id=sender_id,
            )

    def _prune(self, tunnel_id: int) -> None:
        for_tunnel = [m for m in self.tmsgs if m.tunnel_id == tunnel_id]
        if len(for_tunnel) <= MAX_MESSAGES_PER_TUNNEL:
            return
        extra = len(for_tunnel) - MAX_MESSAGES_PER_TUNNEL
        oldest = sorted(for_tunnel, key=lambda m: m.created_at)[:extra]
        for m in oldest:
            self.tmsgs.remove(m)

    async def _react_ok(self, chat_id: int, message_id: int | None) -> None:
        if message_id is None:
            return
        try:
            await self.bot.set_message_reaction(
                chat_id=chat_id,
                message_id=message_id,
                reaction=[ReactionTypeEmoji(emoji=OK_EMOJI)],
            )
        except Exception:
            logger.debug("could not set %s reaction on %s/%s", OK_EMOJI, chat_id, message_id)

    async def _notify(self, ctx: FeatureContext, chat_id: int, text: str) -> None:
        try:
            await ctx.send_to(chat_id, text, markdown=False)
        except Exception:
            logger.exception("failed to notify chat %s", chat_id)

    def _chat_name(self, chat_id: int | None) -> str:
        if chat_id is None:
            return "?"
        # Личка: chat_id == user_id, «название чата» — это имя самого человека.
        if chat_id > 0:
            return self._user_name(chat_id)
        chat = self.chats.find_by(id=chat_id)
        if chat is not None and chat.name and chat.name != "Unknown":
            return chat.name
        return f"чат {chat_id}"

    def _header(self, ctx: FeatureContext, prefix: str = "") -> str:
        sender = self._sender_name(ctx)
        lead = f"{prefix} " if prefix else ""
        # В личке отправитель и есть «чат» — не дублируем имя.
        if ctx.chat_id > 0:
            return f"{lead}{sender}:"
        return f"{lead}[{self._chat_name(ctx.chat_id)}] {sender}:"

    def _caption_command(self, msg) -> tuple[int, str] | None:
        """Если сообщение — медиа с подписью вида «/tunnel <id> [текст]»,
        вернуть (id, очищенный_текст). Иначе None.
        """
        caption = getattr(msg, "caption", None)
        if not isinstance(caption, str):
            return None
        m = _CAPTION_CMD_RE.match(caption.strip())
        if m is None:
            return None
        return int(m.group(1)), (m.group(2) or "").strip()

    async def _send_text(
        self, ctx: FeatureContext, dst_chat: int, text: str, reply_to: int | None
    ):
        """Отправить текст; если reply_to недоступен (сообщения нет) — без него."""
        try:
            return await ctx.send_to(dst_chat, text, markdown=False, reply_to_message_id=reply_to)
        except Exception:
            return await ctx.send_to(dst_chat, text, markdown=False)

    def _album_id(self, msg) -> str | None:
        """media_group_id, только если это настоящий альбом (непустая строка).
        Для одиночных сообщений (и для MagicMock в тестах) вернёт None — так
        альбомная ветка не срабатывает на обычных медиа."""
        gid = getattr(msg, "media_group_id", None)
        return gid if isinstance(gid, str) and gid else None

    async def _album_message_ids(self, ctx: FeatureContext, part) -> list[int]:
        """Все message_id альбома, которому принадлежит `part`.

        Bot API отдаёт альбом как отдельные апдейты и не группирует их, а reply
        указывает лишь на одну часть. Через Telethon (`ctx.client`) тянем
        соседние id — внутри альбома они идут подряд, максимум 10 штук — и
        оставляем те, у кого совпадает grouped_id. На ошибке или если это не
        альбом — возвращаем [part.message_id] (поведение как раньше).
        """
        gid = self._album_id(part)
        base = part.message_id
        client = getattr(ctx, "client", None)
        if gid is None or client is None:
            return [base]
        try:
            candidates = list(range(base - 9, base + 10))
            fetched = await client.get_messages(ctx.chat_id, ids=candidates)
        except Exception:
            logger.warning(
                "tunnel: could not resolve album %s in chat %s", gid, ctx.chat_id,
                exc_info=True,
            )
            return [base]
        ids = sorted(
            m.id
            for m in (fetched or [])
            if m is not None and str(getattr(m, "grouped_id", None)) == gid
        )
        return ids or [base]

    async def _relay_album(
        self,
        ctx: FeatureContext,
        dst_chat: int,
        header: str,
        *,
        src_chat: int,
        message_ids: list[int],
        body: str | None = None,
        strip_captions: bool = False,
        reply_to: int | None = None,
    ) -> list[int]:
        """Доставить альбом одним вызовом copy_messages, сохранив группировку.

        Шапку (и `body`, если есть) шлём отдельным сообщением перед альбомом.
        `strip_captions=True` убирает подписи частей (для случая, когда подпись
        была командой `/tunnel N text`). Возвращает id доставленных сообщений
        в порядке `message_ids`.
        """
        head = f"{header}\n{body}" if body else header
        await self._send_text(ctx, dst_chat, head, reply_to)
        copied = await self.bot.copy_messages(
            chat_id=dst_chat,
            from_chat_id=src_chat,
            message_ids=message_ids,
            remove_caption=strip_captions,
        )
        return [m.message_id for m in copied]

    async def _relay(
        self,
        ctx: FeatureContext,
        dst_chat: int,
        header: str,
        *,
        copy_from=None,
        text: str | None = None,
        reply_to: int | None = None,
    ) -> int:
        """Доставить контент в dst_chat и вернуть id доставленного сообщения.

        copy_from — исходное сообщение. Если оно нетекстовое (медиа/стикер/
        голос/…), оно копируется через copy_message; иначе пересылается текст.
        text — для медиа это новая подпись (override; "" убирает подпись,
        None оставляет оригинальную); для текста — тело под шапкой.
        """
        is_media = copy_from is not None and copy_from.text is None
        if is_media:
            # Шапка отдельным сообщением, затем копия контента.
            await self._send_text(ctx, dst_chat, header, reply_to)
            copied = await ctx.copy_to(
                dst_chat, ctx.chat_id, copy_from.message_id, caption=text
            )
            return copied.message_id

        body = text if text is not None else (copy_from.text if copy_from is not None else None)
        full = f"{header}\n{body}" if body else header
        sent = await self._send_text(ctx, dst_chat, full, reply_to)
        return sent.message_id

    def _user_name(self, user_id: int) -> str:
        user = self.users.find_by(id=user_id)
        if user is None:
            return str(user_id)
        # Предпочитаем @username; имя — фоллбэк, если юзернейма нет.
        if user.username:
            return f"@{user.username}"
        if user.first_name:
            return user.first_name
        return str(user_id)

    def _sender_name(self, ctx: FeatureContext) -> str:
        msg = ctx.message
        if msg is not None and msg.from_user is not None:
            u = msg.from_user
            if u.username:
                return f"@{u.username}"
            if u.first_name:
                return u.first_name
        return self._user_name(ctx.user_id)
