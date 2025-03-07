"""Manages logging configuration for DVC repo."""

import logging.config
import logging.handlers

import colorama

from dvc.progress import Tqdm


FOOTER = (
    "\n{yellow}Having any troubles?{nc}"
    " Hit us up at {blue}https://dvc.org/support{nc},"
    " we are always happy to help!"
).format(
    blue=colorama.Fore.BLUE,
    nc=colorama.Fore.RESET,
    yellow=colorama.Fore.YELLOW,
)


class LoggingException(Exception):
    def __init__(self, record):
        msg = "failed to log {}".format(str(record))
        super().__init__(msg)


class ExcludeErrorsFilter(logging.Filter):
    def filter(self, record):
        return record.levelno < logging.WARNING


class ExcludeInfoFilter(logging.Filter):
    def filter(self, record):
        return record.levelno < logging.INFO


class ColorFormatter(logging.Formatter):
    """Spit out colored text in supported terminals.

    colorama__ makes ANSI escape character sequences work under Windows.
    See the colorama documentation for details.

    __ https://pypi.python.org/pypi/colorama

    If record has an extra `tb_only` attribute, it will not show the
    exception cause, just the message and the traceback.
    """

    color_code = {
        "DEBUG": colorama.Fore.BLUE,
        "WARNING": colorama.Fore.YELLOW,
        "ERROR": colorama.Fore.RED,
        "CRITICAL": colorama.Fore.RED,
    }

    def format(self, record):
        record.message = record.getMessage()
        msg = self.formatMessage(record)

        if record.levelname == "INFO":
            return msg

        if record.exc_info:
            if getattr(record, "tb_only", False):
                cause = ""
            else:
                cause = ": ".join(_iter_causes(record.exc_info[1]))

            msg = "{message}{separator}{cause}".format(
                message=msg or "",
                separator=" - " if msg and cause else "",
                cause=cause,
            )

            if _is_verbose():
                msg += _stack_trace(record.exc_info)

        return "{asctime}{color}{levelname}{nc}: {msg}".format(
            asctime=self.formatTime(record, self.datefmt),
            color=self.color_code[record.levelname],
            nc=colorama.Fore.RESET,
            levelname=record.levelname,
            msg=msg,
        )

    def formatTime(self, record, datefmt=None):
        # only show if current level is set to DEBUG
        # also, skip INFO as it is used for UI
        if not _is_verbose() or record.levelno == logging.INFO:
            return ""

        return "{green}{date}{nc} ".format(
            green=colorama.Fore.GREEN,
            date=super().formatTime(record, datefmt),
            nc=colorama.Fore.RESET,
        )


class LoggerHandler(logging.StreamHandler):
    def handleError(self, record):
        super().handleError(record)
        raise LoggingException(record)

    def emit(self, record):
        """Write to Tqdm's stream so as to not break progress-bars"""
        try:
            msg = self.format(record)
            Tqdm.write(
                msg, file=self.stream, end=getattr(self, "terminator", "\n")
            )
            self.flush()
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)


def _is_verbose():
    return logging.getLogger("dvc").getEffectiveLevel() == logging.DEBUG


def _iter_causes(exc):
    while exc:
        yield str(exc)
        exc = exc.__cause__


def _stack_trace(exc_info):
    import traceback

    return (
        "\n"
        "{red}{line}{nc}\n"
        "{trace}"
        "{red}{line}{nc}".format(
            red=colorama.Fore.RED,
            line="-" * 60,
            trace="".join(traceback.format_exception(*exc_info)),
            nc=colorama.Fore.RESET,
        )
    )


def disable_other_loggers():
    logging.captureWarnings(True)
    root = logging.root
    for (logger_name, logger) in root.manager.loggerDict.items():
        if logger_name != "dvc" and not logger_name.startswith("dvc."):
            logger.disabled = True


def setup(level=logging.INFO):
    colorama.init()

    logging.config.dictConfig(
        {
            "version": 1,
            "filters": {
                "exclude_errors": {"()": ExcludeErrorsFilter},
                "exclude_info": {"()": ExcludeInfoFilter},
            },
            "formatters": {"color": {"()": ColorFormatter}},
            "handlers": {
                "console_info": {
                    "class": "dvc.logger.LoggerHandler",
                    "level": "INFO",
                    "formatter": "color",
                    "stream": "ext://sys.stdout",
                    "filters": ["exclude_errors"],
                },
                "console_debug": {
                    "class": "dvc.logger.LoggerHandler",
                    "level": "DEBUG",
                    "formatter": "color",
                    "stream": "ext://sys.stdout",
                    "filters": ["exclude_info"],
                },
                "console_errors": {
                    "class": "dvc.logger.LoggerHandler",
                    "level": "WARNING",
                    "formatter": "color",
                    "stream": "ext://sys.stderr",
                },
            },
            "loggers": {
                "dvc": {
                    "level": level,
                    "handlers": [
                        "console_info",
                        "console_debug",
                        "console_errors",
                    ],
                },
            },
            "disable_existing_loggers": False,
        }
    )
