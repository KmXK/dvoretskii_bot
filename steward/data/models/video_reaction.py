from dataclasses import dataclass, field


@dataclass
class VideoReaction:
    """
    Хранит связь между сообщением пользователя (ссылка на видео) 
    и сообщением бота (само видео), а также счетчик реакций.
    """
    chat_id: int  # ID чата
    user_id: int  # ID автора (кто кинул ссылку)
    user_message_id: int  # ID сообщения со ссылкой
    bot_message_id: int  # ID сообщения с видео от бота
    video_type: str  # tiktok/reels/youtube/pinterest
    reactions: dict[int, set[str]] = field(default_factory=dict)  # user_id -> set of emojis
    
    def get_total_reactions(self) -> int:
        """Возвращает общее количество уникальных пользователей, поставивших реакцию"""
        return len(self.reactions)
    
    def get_reactions_count(self) -> int:
        """Возвращает общее количество реакций (с учетом нескольких от одного юзера)"""
        return sum(len(emojis) for emojis in self.reactions.values())
