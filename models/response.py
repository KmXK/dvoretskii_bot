import uuid

class Response:
    def __init__(self, from_chat_id, message_id, probability):
        self.id = uuid.uuid4().hex
        self.from_chat_id = from_chat_id
        self.message_id = message_id
        self.probability = probability