import asyncio
import logging

from steward.handlers.handler import Handler
from steward.helpers.command_validation import validate_command_msg

logger = logging.getLogger("ScriptHandler")


# TODO: Уведомление в чат об окончании скрипта даже после смерти
class ScriptHandler(Handler):
    def __init__(self, command: str, script_path: str, help_text: str):
        self.command = command
        self.script_path = script_path
        self.help_text = help_text
        self.only_for_admin = True

    async def chat(self, context):
        if validate_command_msg(context.update, self.command):
            process = await asyncio.create_subprocess_shell(
                self.script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            [stdout, stderr] = await process.communicate()

            logger.info(
                f"Update command result: \nstdout: {stdout.decode(errors='replace')}\nstderr: {stderr.decode(errors='replace')}"
            )

            if process.returncode != 0:
                await context.update.message.reply_markdown(
                    f"Script executed with errorcode {process.returncode}"
                )
                return True

            # FIX: Now bot is dying and we need to send this on restart or make grace shutdown (too hard)
            await context.update.message.reply_markdown(
                "Script has been finished successfully"
            )
            return True

    def help(self):
        return f"/{self.command} - {self.help_text}"
