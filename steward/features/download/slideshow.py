import logging

from telegram import InputFile, InputMediaPhoto, Message
from telegram.error import BadRequest, EndPointNotFound

logger = logging.getLogger(__name__)


def build_photo_slideshow(
    photos: list[str],
    caption: str | None = None,
    audios: list[str] | None = None,
) -> dict:
    slides = []
    media = []
    for index, photo in enumerate(photos):
        media_id = f"photo_{index}"
        slides.append(f'<img src="tg://photo?id={media_id}"/>')
        media.append({"id": media_id, "media": {"type": "photo", "media": photo}})
    html = "<tg-slideshow>" + "".join(slides) + "</tg-slideshow>"
    if caption:
        html += "<p>" + caption.replace("\n", "<br>") + "</p>"
    for index, audio in enumerate(audios or []):
        media_id = f"audio_{index}"
        html += f'<audio src="tg://audio?id={media_id}"></audio>'
        media.append({"id": media_id, "media": {"type": "audio", "media": audio}})
    return {"html": html, "media": media}


async def try_send_photo_slideshow(
    message: Message,
    medias: list,
    caption: str | None = None,
) -> bool:
    if len(medias) < 2 or any(not isinstance(media, InputMediaPhoto) for media in medias):
        return False

    photos = []
    attachments = {}
    for media in medias:
        if isinstance(media.media, InputFile):
            photos.append(media.media.attach_uri)
            attachments[media.media.attach_name] = media.media
        else:
            photos.append(media.media)

    params = {
        "chat_id": message.chat_id,
        "reply_parameters": {"message_id": message.message_id, "allow_sending_without_reply": True},
        "rich_message": build_photo_slideshow(photos, caption),
        "disable_notification": True,
        "message_thread_id": message.message_thread_id if message.is_topic_message else None,
        "business_connection_id": message.business_connection_id,
        "direct_messages_topic_id": (
            message.direct_messages_topic.topic_id if message.direct_messages_topic else None
        ),
        **attachments,
    }
    try:
        await message.get_bot().do_api_request("sendRichMessage", api_kwargs=params)
    except (BadRequest, EndPointNotFound) as error:
        logger.warning("Карусель отклонена Telegram, отправляем альбом: %s", error)
        return False
    return True
