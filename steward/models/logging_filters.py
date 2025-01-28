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


class SkipFilter(logging.Filter):
    def __init__(self, template_for_skip: str) -> None:
        super().__init__('SkipFilter')
        self.template_for_skip = template_for_skip

    def filter(self, record):
        return not record.getMessage().find(self.template_for_skip)
