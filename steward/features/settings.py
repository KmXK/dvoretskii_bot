import logging

from steward.data.models.chat_settings import ChatSettings
from steward.data.models.role import Role, UserRole
from steward.helpers.formats import escape_markdown
from steward.framework import (
    Button,
    Feature,
    FeatureContext,
    Keyboard,
    ask,
    collection,
    on_callback,
    paginated,
    subcommand,
    wizard,
)

logger = logging.getLogger(__name__)


_CAP_ORDER = [
    "ai", "transcribe", "rules", "fun", "trackers",
    "chat_meta", "stats", "downloads", "moderation",
]


def _all_caps_ordered() -> list[str]:
    from steward.features.registry import CAPABILITIES
    return [c for c in _CAP_ORDER if c in CAPABILITIES] + [
        c for c in CAPABILITIES if c not in _CAP_ORDER
    ]


def _cap_label(cap: str) -> str:
    from steward.features.registry import CAPABILITY_LABELS
    return CAPABILITY_LABELS.get(cap, cap)


def _features_in(cap: str) -> list[type]:
    from steward.features.registry import features_in_capability
    return features_in_capability(cap)


def _slug(cls: type) -> str:
    from steward.features.registry import feature_slug
    return feature_slug(cls)


class SettingsFeature(Feature):
    command = "settings"
    description = "Настройки бота для этого чата"
    excluded_from_ai_router = True

    chat_settings_col = collection("chat_settings")
    roles_col = collection("roles")
    user_roles_col = collection("user_roles")
    users_col = collection("users")
    chats_col = collection("chats")

    # ── Permissions catalogue ────────────────────────────────────────────────

    def known_permissions(self) -> list[str]:
        seen: set[str] = set()
        for h in getattr(self, "_all_handlers", []) or []:
            for sub in getattr(h, "_subcommands", []) or []:
                if sub.permission:
                    seen.add(sub.permission)
        return sorted(seen)

    # ── Root ────────────────────────────────────────────────────────────────

    @subcommand("", description="Открыть настройки")
    async def open_(self, ctx: FeatureContext):
        await self._render_root(ctx)

    async def _render_root(self, ctx: FeatureContext, *, edit: bool = False):
        chat = ctx.update.effective_chat
        if chat is None:
            await ctx.reply("Нет данных о чате")
            return

        is_global = ctx.repository.is_admin(ctx.user_id)
        is_private = chat.type == "private"
        settings = ctx.repository.chat_settings_for(chat.id)
        is_chat_admin = ctx.repository.is_chat_admin(ctx.user_id, chat.id)
        if is_private:
            role_label = "owner"
        elif is_global:
            role_label = "global-admin"
        elif is_chat_admin:
            role_label = "chat-admin"
        else:
            role_label = "пользователь"

        from steward.features.registry import CAPABILITIES, ALL_CAPABILITIES
        total_caps = len(CAPABILITIES)
        on_caps = len(settings.enabled_capabilities & ALL_CAPABILITIES)
        if is_private:
            chat_name = "личный чат"
        else:
            chat_name = chat.title or chat.username or str(chat.id)
        text_lines = [
            f"⚙ *Настройки* — {escape_markdown(chat_name)}",
            "",
            f"Включено: {on_caps}/{total_caps} функций",
            f"Вы: {role_label}",
        ]
        text = "\n".join(text_lines)

        kb_rows: list[list[Button]] = [
            [Button("📦 Функции", callback_data=self._cb("caps_tab", chat_id=chat.id))],
        ]
        if not is_private and (is_chat_admin or is_global):
            kb_rows.append([
                Button("👥 Чат-админы", callback_data=self._cb("admins_tab", chat_id=chat.id))
            ])
        if is_global:
            kb_rows.append([Button("🎭 Роли", callback_data=self._cb("roles_tab"))])
        kb = Keyboard(kb_rows)
        if edit:
            await ctx.edit(text, keyboard=kb)
        else:
            await ctx.reply(text, keyboard=kb)

    # ── Callback router (simple, since we need static prefix names) ──────────

    @on_callback("settings:root", schema="<chat_id:int>")
    async def cb_root(self, ctx: FeatureContext, chat_id: int):
        await self._render_root(ctx, edit=True)

    _NOTIFY_FIELDS = {
        "fr": "fr_notifications_enabled",
        "bills": "bills_notifications_enabled",
    }

    _NOTIFY_LABELS = {
        "fr": ("FR-обновления", "DM при смене статуса/приоритета фича-реквеста"),
        "bills": ("Bills-уведомления", "Платёжки и предложения из /bills"),
    }

    def _notifications_state(self, ctx: FeatureContext) -> str:
        states = [self._notify_state(ctx, f) for f in self._NOTIFY_FIELDS.values()]
        if all(states):
            return "on"
        if not any(states):
            return "off"
        return "partial"

    def _notifications_summary(self, ctx: FeatureContext) -> str:
        bits: list[str] = []
        for key, field in self._NOTIFY_FIELDS.items():
            label = self._NOTIFY_LABELS[key][0]
            mark = "✅" if self._notify_state(ctx, field) else "❌"
            bits.append(f"{mark} {label}")
        return " · ".join(bits)

    @on_callback("settings:notify_tab", schema="")
    async def cb_notify_tab(self, ctx: FeatureContext):
        await self.paginate(ctx, "notify", metadata="")

    @paginated("notify", per_page=50, header="", parse_mode="markdown")
    def notify_page(self, ctx: FeatureContext, metadata: str):
        chat = ctx.update.effective_chat
        chat_id = chat.id if chat else 0

        def render(batch):
            lines = ["🔔 *Уведомления* — личные настройки", ""]
            for key, field in self._NOTIFY_FIELDS.items():
                title, desc = self._NOTIFY_LABELS[key]
                mark = "✅" if self._notify_state(ctx, field) else "❌"
                lines.append(f"{mark} *{title}*")
                lines.append(f"   _{desc}_")
            lines.append("")
            lines.append("Тогл — личный, действует во всех чатах.")
            return "\n".join(lines)

        rows: list[list[Button]] = []
        for key, field in self._NOTIFY_FIELDS.items():
            mark = "✅" if self._notify_state(ctx, field) else "❌"
            title = self._NOTIFY_LABELS[key][0]
            rows.append([Button(
                f"{mark} {title}",
                callback_data=self._cb("notify_toggle", key=key),
            )])
        rows.append([
            Button("⏎ Назад", callback_data=self._cb("caps_tab", chat_id=chat_id)),
        ])
        return list(self._NOTIFY_FIELDS), render, Keyboard(rows)

    @on_callback("settings:notify_toggle", schema="<key:literal[fr|bills]>")
    async def cb_notify_toggle(self, ctx: FeatureContext, key: str):
        user = next((u for u in ctx.repository.db.users if u.id == ctx.user_id), None)
        if user is None:
            await ctx.toast("Сначала напиши что-нибудь в чат")
            return
        field = self._NOTIFY_FIELDS.get(key)
        if not field:
            await ctx.toast("Неизвестная настройка")
            return
        setattr(user, field, not getattr(user, field, True))
        await ctx.repository.save()
        await self.paginate(ctx, "notify", metadata="")

    @on_callback("settings:caps_tab", schema="<chat_id:int>")
    async def cb_caps_tab(self, ctx: FeatureContext, chat_id: int):
        await self.paginate(ctx, "caps", metadata=str(chat_id))

    @on_callback("settings:admins_tab", schema="<chat_id:int>")
    async def cb_admins_tab(self, ctx: FeatureContext, chat_id: int):
        if not self._can_manage_chat(ctx, chat_id):
            await ctx.toast("Только chat-admin или global-admin")
            return
        await self.paginate(ctx, "admins", metadata=str(chat_id))

    @on_callback("settings:roles_tab", schema="")
    async def cb_roles_tab(self, ctx: FeatureContext):
        if not ctx.repository.is_admin(ctx.user_id):
            await ctx.toast("Только global-admin")
            return
        await self.paginate(ctx, "roles", metadata="")

    @on_callback("settings:cap_toggle", schema="<chat_id:int>|<cap:str>")
    async def cb_cap_toggle(self, ctx: FeatureContext, chat_id: int, cap: str):
        if not self._can_manage_chat(ctx, chat_id):
            await ctx.toast("Только chat-admin или global-admin")
            return
        settings = ctx.repository.chat_settings_for(chat_id)
        if cap in settings.enabled_capabilities:
            settings.enabled_capabilities.discard(cap)
            for cls in _features_in(cap):
                settings.disabled_features.discard(_slug(cls))
        else:
            settings.enabled_capabilities.add(cap)
            for cls in _features_in(cap):
                settings.disabled_features.discard(_slug(cls))
        await self.chat_settings_col.save()
        await self.paginate(ctx, "caps", metadata=str(chat_id))

    @on_callback("settings:cap_drill", schema="<chat_id:int>|<cap:str>")
    async def cb_cap_drill(self, ctx: FeatureContext, chat_id: int, cap: str):
        await self.paginate(ctx, "feats", metadata=f"{chat_id}|{cap}")

    @on_callback("settings:feat_toggle", schema="<chat_id:int>|<cap:str>|<feat:str>")
    async def cb_feat_toggle(self, ctx: FeatureContext, chat_id: int, cap: str, feat: str):
        if not self._can_manage_chat(ctx, chat_id):
            await ctx.toast("Только chat-admin или global-admin")
            return
        settings = ctx.repository.chat_settings_for(chat_id)
        if cap not in settings.enabled_capabilities:
            # Группа была выключена целиком. Включаем группу, но гасим все
            # ОСТАЛЬНЫЕ фичи, чтобы зажглась только та, по которой нажали,
            # а не вся категория разом.
            settings.enabled_capabilities.add(cap)
            for cls in _features_in(cap):
                settings.disabled_features.add(_slug(cls))
            settings.disabled_features.discard(feat)
        elif feat in settings.disabled_features:
            settings.disabled_features.discard(feat)
        else:
            settings.disabled_features.add(feat)
        await self.chat_settings_col.save()
        await self.paginate(ctx, "feats", metadata=f"{chat_id}|{cap}")

    @on_callback("settings:cap_all_on", schema="<chat_id:int>|<cap:str>")
    async def cb_cap_all_on(self, ctx: FeatureContext, chat_id: int, cap: str):
        if not self._can_manage_chat(ctx, chat_id):
            await ctx.toast("Только chat-admin или global-admin")
            return
        settings = ctx.repository.chat_settings_for(chat_id)
        settings.enabled_capabilities.add(cap)
        for cls in _features_in(cap):
            settings.disabled_features.discard(_slug(cls))
        await self.chat_settings_col.save()
        await self.paginate(ctx, "feats", metadata=f"{chat_id}|{cap}")

    @on_callback("settings:cap_all_off", schema="<chat_id:int>|<cap:str>")
    async def cb_cap_all_off(self, ctx: FeatureContext, chat_id: int, cap: str):
        if not self._can_manage_chat(ctx, chat_id):
            await ctx.toast("Только chat-admin или global-admin")
            return
        settings = ctx.repository.chat_settings_for(chat_id)
        for cls in _features_in(cap):
            settings.disabled_features.add(_slug(cls))
        await self.chat_settings_col.save()
        await self.paginate(ctx, "feats", metadata=f"{chat_id}|{cap}")

    @on_callback("settings:admin_toggle", schema="<chat_id:int>|<user_id:int>")
    async def cb_admin_toggle(self, ctx: FeatureContext, chat_id: int, user_id: int):
        if not self._can_manage_chat(ctx, chat_id):
            await ctx.toast("Только chat-admin или global-admin")
            return
        settings = ctx.repository.chat_settings_for(chat_id)
        if user_id in settings.chat_admins:
            settings.chat_admins.discard(user_id)
        else:
            settings.chat_admins.add(user_id)
        await self.chat_settings_col.save()
        await self.paginate(ctx, "admins", metadata=str(chat_id))

    # ── Paginators ──────────────────────────────────────────────────────────

    @paginated("caps", per_page=50, header="", parse_mode="markdown")
    def caps_page(self, ctx: FeatureContext, metadata: str):
        chat_id = int(metadata) if metadata else 0
        chat = ctx.repository.get_chat(chat_id)
        chat_name = chat.name if chat else str(chat_id)
        settings = ctx.repository.chat_settings_for(chat_id)
        can_manage = self._can_manage_chat(ctx, chat_id)

        items = _all_caps_ordered()
        icons = {"on": "✅", "off": "❌", "partial": "➖"}
        notify_state = self._notifications_state(ctx)
        notify_summary = self._notifications_summary(ctx)

        def render(batch: list[str]) -> str:
            lines = [f"📦 *Функции* — {escape_markdown(chat_name)}", ""]
            for cap in items:
                state = self._cap_state(settings, cap)
                feats = self._cap_feature_summary(cap, settings)
                lines.append(f"{icons[state]} *{_cap_label(cap)}*")
                if feats:
                    lines.append(f"   _{feats}_")
            lines.append(f"{icons[notify_state]} *Уведомления* _(личные)_")
            lines.append(f"   _{notify_summary}_")
            lines.append("")
            lines.append("Тап по строке — тогл группы. ⚙ — детали.")
            return "\n".join(lines)

        rows: list[list[Button]] = []
        for cap in items:
            state = self._cap_state(settings, cap)
            text = f"{icons[state]} {_cap_label(cap)}"
            cb = self._cb("cap_toggle", chat_id=chat_id, cap=cap) if can_manage else "settings:noop"
            rows.append([
                Button(text, callback_data=cb),
                Button("⚙", callback_data=self._cb("cap_drill", chat_id=chat_id, cap=cap)),
            ])
        rows.append([
            Button(
                f"{icons[notify_state]} Уведомления",
                callback_data=self._cb("notify_tab"),
            ),
            Button("⚙", callback_data=self._cb("notify_tab")),
        ])
        rows.append([Button("⏎ Назад", callback_data=self._cb("root", chat_id=chat_id))])
        extra = Keyboard(rows)
        return items, render, extra

    @paginated("feats", per_page=50, header="", parse_mode="markdown")
    def feats_page(self, ctx: FeatureContext, metadata: str):
        parts = metadata.split("|", 1)
        chat_id = int(parts[0]) if parts and parts[0] else 0
        cap = parts[1] if len(parts) > 1 else ""
        chat = ctx.repository.get_chat(chat_id)
        chat_name = chat.name if chat else str(chat_id)
        cap_label = _cap_label(cap)
        settings = ctx.repository.chat_settings_for(chat_id)
        can_manage = self._can_manage_chat(ctx, chat_id)

        classes = _features_in(cap)
        classes.sort(key=lambda c: c.__name__)

        cap_enabled = cap in settings.enabled_capabilities
        from steward.features.registry import features_in_group

        def render(batch):
            lines = [f"📦 *{cap_label}* — {escape_markdown(chat_name)}", ""]
            for cls in classes:
                slug = _slug(cls)
                disabled = slug in settings.disabled_features
                active = cap_enabled and not disabled
                icon = "✅" if active else "❌"
                label = self._feature_button_label(cls)
                desc = (getattr(cls, "description", "") or "").strip()
                bundle = features_in_group(cls)
                if len(bundle) > 1:
                    extras = ", ".join(
                        c.__name__.removesuffix("Feature") for c in bundle[1:]
                    )
                    suffix = f" _(+ {extras})_"
                else:
                    suffix = ""
                line = f"{icon} *{label}*{suffix}"
                if desc:
                    line += f" — {desc}"
                lines.append(line)
            if not cap_enabled:
                lines.append("")
                lines.append("_Группа выключена. Тогл фичи включит её._")
            return "\n".join(lines)

        rows: list[list[Button]] = []
        for cls in classes:
            slug = _slug(cls)
            disabled = slug in settings.disabled_features
            active = cap_enabled and not disabled
            icon = "✅" if active else "❌"
            label = self._feature_button_label(cls)
            cb = (
                self._cb("feat_toggle", chat_id=chat_id, cap=cap, feat=slug)
                if can_manage else "settings:noop"
            )
            rows.append([Button(f"{icon} {label}", callback_data=cb)])
        if can_manage:
            rows.append([
                Button("Включить все", callback_data=self._cb("cap_all_on", chat_id=chat_id, cap=cap)),
                Button("Выключить все", callback_data=self._cb("cap_all_off", chat_id=chat_id, cap=cap)),
            ])
        rows.append([
            Button("⏎ Назад", callback_data=self._cb("caps_tab", chat_id=chat_id)),
        ])
        extra = Keyboard(rows)
        return classes, render, extra

    @paginated("admins", per_page=50, header="👥 Чат-админы", parse_mode="markdown")
    def admins_page(self, ctx: FeatureContext, metadata: str):
        chat_id = int(metadata) if metadata else 0
        settings = ctx.repository.chat_settings_for(chat_id)
        can_manage = self._can_manage_chat(ctx, chat_id)

        members = [u for u in ctx.repository.db.users if chat_id in (u.chat_ids or [])]
        members.sort(key=lambda u: (u.id not in settings.chat_admins, (u.username or "").lower(), u.id))

        def display(u) -> str:
            if u.username:
                return f"@{u.username}"
            if u.first_name:
                return u.first_name
            return str(u.id)

        def render(batch):
            chat = ctx.repository.get_chat(chat_id)
            name = chat.name if chat else str(chat_id)
            lines = [f"*{escape_markdown(name)}*", ""]
            for u in batch:
                badge = "★ chat-admin" if u.id in settings.chat_admins else ""
                lines.append(f"• {escape_markdown(display(u))} {badge}".rstrip())
            return "\n".join(lines)

        rows: list[list[Button]] = []
        if can_manage:
            for u in members[:20]:
                is_admin = u.id in settings.chat_admins
                btn_label = ("✖ Снять " if is_admin else "+ Сделать ") + display(u)
                rows.append([
                    Button(btn_label, callback_data=self._cb("admin_toggle", chat_id=chat_id, user_id=u.id))
                ])
        rows.append([Button("⏎ Назад", callback_data=self._cb("root", chat_id=chat_id))])
        extra = Keyboard(rows)
        return members, render, extra

    # ── Roles tab (full editor lives in stage 6 below) ──────────────────────

    @paginated("roles", per_page=50, header="🎭 Роли", parse_mode="markdown")
    def roles_page(self, ctx: FeatureContext, metadata: str):
        if not ctx.repository.is_admin(ctx.user_id):
            return [], (lambda batch: "Только global-admin"), None

        roles: list[Role] = list(ctx.repository.db.roles)
        roles.sort(key=lambda r: r.id)

        def render(batch):
            if not batch:
                return "Ролей пока нет"
            lines = []
            for r in batch:
                count_users = sum(1 for ur in ctx.repository.db.user_roles if ur.role_id == r.id)
                lines.append(
                    f"• *{escape_markdown(r.name)}* — {count_users} чел · {len(r.permissions)} прав"
                )
            return "\n".join(lines)

        rows: list[list[Button]] = []
        for r in roles:
            rows.append([
                Button(f"🎭 {r.name}", callback_data=self._cb("role_open", role_id=r.id)),
                Button("✏", callback_data=self._cb("role_rename", role_id=r.id)),
                Button("🗑", callback_data=self._cb("role_delete", role_id=r.id)),
            ])
        rows.append([Button("➕ Создать роль", callback_data=self._cb("role_create"))])
        rows.append([Button("⏎ Назад", callback_data=self._cb("root", chat_id=0))])
        extra = Keyboard(rows)
        return roles, render, extra

    @on_callback("settings:role_open", schema="<role_id:int>")
    async def cb_role_open(self, ctx: FeatureContext, role_id: int):
        if not ctx.repository.is_admin(ctx.user_id):
            await ctx.toast("Только global-admin")
            return
        await self.paginate(ctx, "role_view", metadata=str(role_id))

    @paginated("role_view", per_page=100, header="", parse_mode="markdown")
    def role_view_page(self, ctx: FeatureContext, metadata: str):
        role_id = int(metadata) if metadata else 0
        role = next((r for r in ctx.repository.db.roles if r.id == role_id), None)
        if role is None:
            return [], (lambda batch: "Роль не найдена"), None
        known = self.known_permissions()
        # ensure permissions on role that aren't in known are still shown
        for p in role.permissions:
            if p not in known:
                known.append(p)

        users_in_role = [
            u for u in ctx.repository.db.users
            if any(
                ur.user_id == u.id and ur.role_id == role.id
                for ur in ctx.repository.db.user_roles
            )
        ]

        def render(batch):
            users_text = "\n".join(
                f"  • @{escape_markdown(u.username)}" if u.username else f"  • id={u.id}"
                for u in users_in_role
            ) or "  (никого)"
            return f"🎭 *{escape_markdown(role.name)}*\n\nПользователи:\n{users_text}"

        rows: list[list[Button]] = []
        for perm in known:
            icon = "✅" if perm in role.permissions else "❌"
            rows.append([Button(
                f"{icon} {perm}",
                callback_data=self._cb("role_perm_toggle", role_id=role.id, perm=perm),
            )])
        rows.append([
            Button("➕ Добавить пользователя", callback_data=self._cb("role_user_add", role_id=role.id)),
        ])
        for u in users_in_role[:20]:
            label = f"✖ @{u.username}" if u.username else f"✖ id={u.id}"
            rows.append([Button(
                label,
                callback_data=self._cb("role_user_remove", role_id=role.id, user_id=u.id),
            )])
        rows.append([Button("⏎ Назад", callback_data=self._cb("roles_tab"))])
        return known, render, Keyboard(rows)

    @on_callback("settings:role_perm_toggle", schema="<role_id:int>|<perm:str>")
    async def cb_role_perm_toggle(self, ctx: FeatureContext, role_id: int, perm: str):
        if not ctx.repository.is_admin(ctx.user_id):
            await ctx.toast("Только global-admin")
            return
        role = next((r for r in ctx.repository.db.roles if r.id == role_id), None)
        if role is None:
            await ctx.toast("Роль не найдена")
            return
        if perm in role.permissions:
            role.permissions.discard(perm)
        else:
            role.permissions.add(perm)
        await self.roles_col.save()
        await self.paginate(ctx, "role_view", metadata=str(role_id))

    @on_callback("settings:role_user_remove", schema="<role_id:int>|<user_id:int>")
    async def cb_role_user_remove(self, ctx: FeatureContext, role_id: int, user_id: int):
        if not ctx.repository.is_admin(ctx.user_id):
            await ctx.toast("Только global-admin")
            return
        ctx.repository.db.user_roles = [
            ur for ur in ctx.repository.db.user_roles
            if not (ur.role_id == role_id and ur.user_id == user_id)
        ]
        await ctx.repository.save()
        await self.paginate(ctx, "role_view", metadata=str(role_id))

    @on_callback("settings:role_delete", schema="<role_id:int>")
    async def cb_role_delete(self, ctx: FeatureContext, role_id: int):
        if not ctx.repository.is_admin(ctx.user_id):
            await ctx.toast("Только global-admin")
            return
        ctx.repository.db.roles = [r for r in ctx.repository.db.roles if r.id != role_id]
        ctx.repository.db.user_roles = [
            ur for ur in ctx.repository.db.user_roles if ur.role_id != role_id
        ]
        await ctx.repository.save()
        await self.paginate(ctx, "roles", metadata="")

    # ── Role create / rename / add-user wizards ─────────────────────────────

    @on_callback("settings:role_create", schema="")
    async def cb_role_create(self, ctx: FeatureContext):
        if not ctx.repository.is_admin(ctx.user_id):
            await ctx.toast("Только global-admin")
            return
        await self.start_wizard("role_create", ctx)

    @wizard(
        "role_create",
        ask("name", "Название роли:"),
    )
    async def role_create_done(self, ctx: FeatureContext, name: str):
        if not ctx.repository.is_admin(ctx.user_id):
            await ctx.reply("Только global-admin")
            return
        name = (name or "").strip()
        if not name:
            await ctx.reply("Пустое название")
            return
        next_id = (max((r.id for r in ctx.repository.db.roles), default=0) + 1)
        role = Role(id=next_id, name=name, permissions=set())
        ctx.repository.db.roles.append(role)
        await ctx.repository.save()
        await ctx.reply(f"Роль *{name}* создана. /settings → 🎭 Роли")

    @on_callback("settings:role_rename", schema="<role_id:int>")
    async def cb_role_rename(self, ctx: FeatureContext, role_id: int):
        if not ctx.repository.is_admin(ctx.user_id):
            await ctx.toast("Только global-admin")
            return
        await self.start_wizard("role_rename", ctx, role_id=role_id)

    @wizard(
        "role_rename",
        ask("new_name", "Новое название:"),
    )
    async def role_rename_done(self, ctx: FeatureContext, role_id: int, new_name: str):
        role = next((r for r in ctx.repository.db.roles if r.id == role_id), None)
        if role is None:
            await ctx.reply("Роль не найдена")
            return
        role.name = (new_name or "").strip() or role.name
        await ctx.repository.save()
        await ctx.reply(f"Переименовано в *{role.name}*")

    @on_callback("settings:role_user_add", schema="<role_id:int>")
    async def cb_role_user_add(self, ctx: FeatureContext, role_id: int):
        if not ctx.repository.is_admin(ctx.user_id):
            await ctx.toast("Только global-admin")
            return
        await self.start_wizard("role_user_add", ctx, role_id=role_id)

    @wizard(
        "role_user_add",
        ask("target", "Пользователь (@username или id):"),
    )
    async def role_user_add_done(self, ctx: FeatureContext, role_id: int, target: str):
        if not ctx.repository.is_admin(ctx.user_id):
            await ctx.reply("Только global-admin")
            return
        uid = self._resolve_user(target)
        if uid is None:
            await ctx.reply("Пользователь не найден. Попроси его написать что-нибудь сначала.")
            return
        if any(ur.user_id == uid and ur.role_id == role_id for ur in ctx.repository.db.user_roles):
            await ctx.reply("Уже в этой роли")
            return
        ctx.repository.db.user_roles.append(UserRole(user_id=uid, role_id=role_id))
        await ctx.repository.save()
        await ctx.reply("Добавлен")

    # ── Helpers ────────────────────────────────────────────────────────────

    def _cb(self, name: str, **values) -> str:
        return self.cb(f"settings:{name}")(**values)

    def _notify_state(self, ctx: FeatureContext, field: str) -> bool:
        user = next((u for u in ctx.repository.db.users if u.id == ctx.user_id), None)
        return getattr(user, field, True) if user else True

    def _can_manage_chat(self, ctx: FeatureContext, chat_id: int) -> bool:
        if ctx.repository.is_admin(ctx.user_id):
            return True
        return ctx.repository.is_chat_admin(ctx.user_id, chat_id)

    def _cap_feature_summary(self, cap: str, settings: ChatSettings) -> str:
        """Compact 'in this group: /a, /b, /c' for the caps overview line."""
        classes = _features_in(cap)
        if not classes:
            return ""
        names: list[str] = []
        for cls in classes:
            command = getattr(cls, "command", None)
            if command:
                names.append(f"/{command}")
            else:
                names.append(cls.__name__.removesuffix("Feature"))
        return ", ".join(names)

    def _cap_state(self, settings: ChatSettings, cap: str) -> str:
        if cap not in settings.enabled_capabilities:
            return "off"
        classes = _features_in(cap)
        if any(_slug(c) in settings.disabled_features for c in classes):
            return "partial"
        return "on"

    def _feature_button_label(self, cls: type) -> str:
        command = getattr(cls, "command", None)
        if command:
            return f"/{command}"
        # passive feature — use class name humanized
        name = cls.__name__.removesuffix("Feature")
        return f"{name} (пассивно)"

    def _resolve_user(self, target: str) -> int | None:
        target = (target or "").strip()
        if not target:
            return None
        if target.startswith("@"):
            username = target[1:].lower()
            for u in self.repository.db.users:
                if u.username and u.username.lower() == username:
                    return u.id
            return None
        try:
            return int(target)
        except ValueError:
            return None

    # Static no-op callback so disabled toggles do not raise
    @on_callback("settings:noop", schema="")
    async def cb_noop(self, ctx: FeatureContext):
        await ctx.toast("Нет прав")
