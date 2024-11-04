
import logging


class ReplaceFilter(logging.Filter):
    def __init__(self, old: str = '', new: str = '') -> None:
        super().__init__('ReplaceFilter')
        self.old = old
        self.new = new

    def filter(self, record):
        msg = record.getMessage()

        if record.getMessage().find(self.old):
            msg = msg.replace(self.old, self.new)
            record.msg = '%s'
            record.args = msg
        return True


class StringFilter(logging.Filter):
    def __init__(self, s: str = '') -> None:
        super().__init__('String filter')
        self.s = s

    def filter(self, record):
        return self.s not in record.getMessage()
