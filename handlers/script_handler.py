import asyncio
from handlers.handler import Handler, validate_command_msg


class ScriptHandler(Handler):
    def __init__(self, command: str, script_path: str, help_text: str):
        self.command = command
        self.script_path = script_path
        self.help_text = help_text
        self.only_for_admin = True

    async def chat(self, update, context):
        if validate_command_msg(update, self.command):
            process = await asyncio.create_subprocess_shell(
                f"sudo {self.script_path}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate()

    def help(self):
        return f"/{self.command} - {self.help_text}"
