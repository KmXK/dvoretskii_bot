import argparse
import logging

from steward.bot import Bot
from steward.data.repository import JsonFileStorage, Repository
from steward.handlers.add_admin_handler import AddAdminHandler
from steward.handlers.add_rule_handler import AddRuleHandler
from steward.handlers.army_handler import AddArmyHandler, ArmyHandler, DeleteArmyHandler
from steward.handlers.delete_admin_handler import DeleteAdminHandler
from steward.handlers.delete_rule_handler import DeleteRuleHandler
from steward.handlers.download_handler import DownloadHandler
from steward.handlers.feature_request_handler import (
    FeatureRequestEditHandler,
    FeatureRequestViewHandler,
)
from steward.handlers.get_admins_handler import GetAdminsHandler
from steward.handlers.get_rules_handler import GetRulesHandler
from steward.handlers.handler import Handler
from steward.handlers.help_handler import HelpHandler
from steward.handlers.id_handler import IdHandler
from steward.handlers.logs_handler import LogsHandler
from steward.handlers.rule_answer_handler import RuleAnswerHandler
from steward.handlers.script_handler import ScriptHandler
from steward.logging.configure import configure_logging

logger: logging.Logger


def get_token(is_test=False):
    if is_test:
        return "***REMOVED***"
    else:
        return "***REMOVED***"


repository = Repository(JsonFileStorage("db.json"))

# TODO: Union CRUD handlers to one import
handlers: list[Handler] = [
    DownloadHandler(),
    GetRulesHandler(repository),
    AddRuleHandler(repository),
    DeleteRuleHandler(repository),
    GetAdminsHandler(repository),
    AddAdminHandler(repository),
    DeleteAdminHandler(repository),
    AddArmyHandler(repository),
    DeleteArmyHandler(repository),
    ArmyHandler(repository),
    FeatureRequestEditHandler(repository),
    FeatureRequestViewHandler(repository),
    LogsHandler("./main.log", repository),
    IdHandler(),
    ScriptHandler("update", "./update.sh", "скачать изменения и обновить бота"),
    ScriptHandler("reload", "./reload.sh", "перезапустить бота"),
    RuleAnswerHandler(repository),
]

handlers.append(HelpHandler(handlers, repository))


def main():
    parser = argparse.ArgumentParser("bot")
    parser.add_argument(
        "--prod",
        help="Use production environment",
        action="store_true",
    )
    parser.add_argument(
        "--log-file",
        help="Log to file",
    )
    args = parser.parse_args()
    is_test = not args.prod

    token = get_token(is_test)

    configure_logging(token, args.log_file)

    Bot(handlers, repository).start(token, True)


if __name__ == "__main__":
    main()
