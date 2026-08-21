from unittest.mock import MagicMock

from steward.features.download.yt import _auto_video_transcription_enabled
from steward.features.registry import features_in_capability
from steward.features.settings import SettingsFeature
from steward.features.transcribe import (
    AutoVideoTranscriptionFeature,
    TranscribeFeature,
)


def test_manual_and_automatic_transcription_have_separate_settings_items():
    transcription_features = features_in_capability("transcribe")

    assert TranscribeFeature in transcription_features
    assert AutoVideoTranscriptionFeature in transcription_features
    assert SettingsFeature()._feature_button_label(TranscribeFeature) == (
        "Ручная транскрибация (/transcribe)"
    )
    assert SettingsFeature()._feature_button_label(AutoVideoTranscriptionFeature) == (
        "Автотранскрибация видео"
    )


def test_automatic_video_transcription_uses_its_own_setting():
    repository = MagicMock()
    repository.is_capability_enabled.return_value = False
    message = MagicMock(chat_id=-1001)

    assert not _auto_video_transcription_enabled(repository, message, supported=True)
    repository.is_capability_enabled.assert_called_once_with(
        -1001,
        AutoVideoTranscriptionFeature,
    )
