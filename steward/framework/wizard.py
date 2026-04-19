from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from telegram import Update

from steward.framework.keyboard import Button, Keyboard
from steward.helpers.validation import (
    Error,
    Validator,
    call_validator_callable,
    validate_message_text,
)
from steward.session.context import (
    CallbackStepContext,
    ChatStepContext,
    SessionContext,
)
from steward.session.session_handler_base import SessionHandlerBase
from steward.session.session_registry import get_session_key
from steward.session.step import Step
from steward.session.steps.keyboard_step import KeyboardStep
from steward.session.steps.question_step import QuestionStep


@dataclass
class _AskStepSpec:
    key: str
    question: str | Callable[[dict], str]
    validator: Validator | None = None
    when: Callable[[SessionContext], bool] | None = None

    def build(self) -> Step:
        validator = (
            self.validator if self.validator is not None else validate_message_text([])
        )
        step = QuestionStep(
            key=self.key,
            question=self.question,
            filter_answer=validator,
        )
        if self.when is not None:
            return _ConditionalStep(step, self.when)
        return step


@dataclass
class _AskMessageStepSpec:
    key: str
    question: str | Callable[[dict], str]
    filter: Callable[[Any], bool] | None = None
    transform: Callable[[Any], Any] | None = None
    error: str = "Неподходящее сообщение, попробуй ещё раз"
    when: Callable[[SessionContext], bool] | None = None

    def build(self) -> Step:
        step = _AskMessageStep(
            key=self.key,
            question=self.question,
            filter=self.filter,
            transform=self.transform,
            error=self.error,
        )
        if self.when is not None:
            return _ConditionalStep(step, self.when)
        return step


@dataclass
class _ChoiceStepSpec:
    key: str
    question: str | Callable[[dict], str]
    options: list[tuple[str, Any]]
    when: Callable[[SessionContext], bool] | None = None

    def build(self) -> Step:
        keyboard = [
            [
                (label, f"_wizard:{self.key}:{i}", value)
                for i, (label, value) in enumerate(self.options)
            ]
        ]
        step = KeyboardStep(name=self.key, msg=self.question, keyboard=keyboard)
        if self.when is not None:
            return _ConditionalStep(step, self.when)
        return step


@dataclass
class _StepWrapper:
    key: str
    step: Step
    when: Callable[[SessionContext], bool] | None = None

    def build(self) -> Step:
        if self.when is not None:
            return _ConditionalStep(self.step, self.when)
        return self.step


class _AskMessageStep(Step):
    def __init__(
        self,
        key: str,
        question: str | Callable[[dict], str],
        filter: Callable[[Any], bool] | None,
        transform: Callable[[Any], Any] | None,
        error: str,
    ):
        self.key = key
        self.question = question
        self.filter = filter
        self.transform = transform
        self.error = error
        self.is_waiting = False

    async def chat(self, context: ChatStepContext) -> bool:
        if not self.is_waiting:
            text = (
                self.question(context.session_context)
                if callable(self.question)
                else self.question
            )
            await context.message.reply_text(text)
            self.is_waiting = True
            return False

        message = context.message
        if self.filter is not None and not self.filter(message):
            await context.message.reply_text(self.error)
            return False

        value = (
            self.transform(message) if self.transform is not None else message
        )
        if isinstance(value, Awaitable):  # type: ignore
            value = await value
        if isinstance(value, Error):
            await context.message.reply_text(value.message)
            return False

        context.session_context[self.key] = value
        self.is_waiting = False
        return True

    async def callback(self, context: CallbackStepContext) -> bool:
        if not self.is_waiting:
            text = (
                self.question(context.session_context)
                if callable(self.question)
                else self.question
            )
            await context.callback_query.message.chat.send_message(text)
            self.is_waiting = True
        return False

    def stop(self) -> None:
        self.is_waiting = False


class _ConditionalStep(Step):
    def __init__(self, inner: Step, when: Callable[[SessionContext], bool]):
        self._inner = inner
        self._when = when

    async def chat(self, context: ChatStepContext) -> bool:
        if not self._when(context.session_context):
            return True
        return await self._inner.chat(context)

    async def callback(self, context: CallbackStepContext) -> bool:
        if not self._when(context.session_context):
            return True
        return await self._inner.callback(context)

    def stop(self) -> None:
        self._inner.stop()


def ask(
    key: str,
    question: str | Callable[[dict], str],
    *,
    validator: Validator | None = None,
    when: Callable[[SessionContext], bool] | None = None,
) -> _AskStepSpec:
    return _AskStepSpec(key=key, question=question, validator=validator, when=when)


def ask_message(
    key: str,
    question: str | Callable[[dict], str],
    *,
    filter: Callable[[Any], bool] | None = None,
    transform: Callable[[Any], Any] | None = None,
    error: str = "Неподходящее сообщение, попробуй ещё раз",
    when: Callable[[SessionContext], bool] | None = None,
) -> _AskMessageStepSpec:
    return _AskMessageStepSpec(
        key=key,
        question=question,
        filter=filter,
        transform=transform,
        error=error,
        when=when,
    )


def choice(
    key: str,
    question: str | Callable[[dict], str],
    options: list[tuple[str, Any]],
    *,
    when: Callable[[SessionContext], bool] | None = None,
) -> _ChoiceStepSpec:
    return _ChoiceStepSpec(key=key, question=question, options=options, when=when)


def confirm(
    key: str,
    question: str | Callable[[dict], str],
    *,
    yes_label: str = "Да",
    no_label: str = "Нет",
    when: Callable[[SessionContext], bool] | None = None,
) -> _ChoiceStepSpec:
    return choice(
        key,
        question,
        [(yes_label, True), (no_label, False)],
        when=when,
    )


def step(
    key: str,
    step_instance: Step,
    *,
    when: Callable[[SessionContext], bool] | None = None,
) -> _StepWrapper:
    return _StepWrapper(key=key, step=step_instance, when=when)


@dataclass
class WizardSpec:
    name: str
    step_specs: list[Any]
    on_done: Callable[..., Awaitable[Any]]
    keys: list[str] = field(default_factory=list)

    def build_steps(self) -> list[Step]:
        return [s.build() for s in self.step_specs]


def wizard(name: str, *step_specs: Any):
    def decorator(func):
        spec = WizardSpec(
            name=name,
            step_specs=list(step_specs),
            on_done=func,
            keys=[s.key for s in step_specs],
        )
        setattr(func, "_feature_wizard", spec)
        setattr(func, "_feature_marker", "wizard")
        return func

    return decorator


@dataclass
class CustomStepSpec:
    name: str
    step_cls: type[Step]


def custom_step(name: str):
    def decorator(step_cls):
        spec = CustomStepSpec(name=name, step_cls=step_cls)
        setattr(step_cls, "_feature_custom_step", spec)
        return step_cls

    return decorator


class FeatureWizardSession(SessionHandlerBase):
    def __init__(self, feature: Any, spec: WizardSpec):
        super().__init__(spec.build_steps())
        self._feature = feature
        self._spec = spec
        self._pending_starts: dict[tuple[int, int], dict[str, Any]] = {}

    def stage_start(self, update: Update, initial: dict[str, Any]) -> None:
        self._pending_starts[get_session_key(update)] = initial

    def try_activate_session(self, update, session_context):
        key = get_session_key(update)
        initial = self._pending_starts.pop(key, None)
        if initial is None:
            return False
        session_context.update(initial)
        return True

    async def on_session_finished(self, update, session_context):
        kwargs: dict[str, Any] = {}
        for k, v in session_context.items():
            if k == "__internal_session_data__":
                continue
            kwargs[k] = v
        ctx = self._feature._make_wizard_context(update)
        try:
            await self._spec.on_done(self._feature, ctx, **kwargs)
        except TypeError:
            filtered = {k: v for k, v in kwargs.items() if k in self._spec.keys}
            extras = {k: v for k, v in kwargs.items() if k not in self._spec.keys}
            kwargs = {**filtered, **extras} if extras else filtered
            await self._spec.on_done(self._feature, ctx, **kwargs)

    async def on_stop(self, update, context):
        pass


class _AdhocSession(SessionHandlerBase):
    def __init__(
        self,
        feature: Any,
        steps: list[Step],
        on_done: Callable[..., Awaitable[Any]] | None = None,
        on_stop: Callable[..., Awaitable[Any]] | None = None,
    ):
        super().__init__(steps)
        self._feature = feature
        self._on_done = on_done
        self._on_stop = on_stop
        self._pending_starts: dict[tuple[int, int], dict[str, Any]] = {}

    def stage_start(self, update: Update, initial: dict[str, Any]) -> None:
        self._pending_starts[get_session_key(update)] = initial

    def try_activate_session(self, update, session_context):
        key = get_session_key(update)
        initial = self._pending_starts.pop(key, None)
        if initial is None:
            return False
        session_context.update(initial)
        return True

    async def on_session_finished(self, update, session_context):
        if self._on_done is None:
            return
        kwargs = {
            k: v for k, v in session_context.items() if k != "__internal_session_data__"
        }
        ctx = self._feature._make_wizard_context(update)
        await self._on_done(self._feature, ctx, **kwargs)

    async def on_stop(self, update, context):
        if self._on_stop is None:
            return
        ctx = self._feature._make_wizard_context(update)
        await self._on_stop(self._feature, ctx)
