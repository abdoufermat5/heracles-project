"""Catalog and syntax rules of the ``sudoOption`` values (sudoers ``Defaults`` options).

A stored value has one of these shapes:

``name``            enable a flag
``!name``           disable a flag, or unset a non-flag option
``name=value``      set an ``int``, ``string`` or ``list`` option
``name+=value``     add to a ``list`` option
``name-=value``     remove from a ``list`` option

Rules enforced by :func:`parse_option`:

* ``name`` must be in :data:`OPTIONS`;
* a ``flag`` takes no value (``name`` and ``!name`` are its only forms);
* a non-flag needs a value, except in the ``!name`` form (which unsets it);
  ``!name`` never carries a value;
* ``int`` values are optionally signed decimal integers (``-1`` disables a timeout);
* ``+=`` and ``-=`` are accepted for ``list`` options only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from heracles.i18n import _

FLAG: Final = "flag"
INT: Final = "int"
STRING: Final = "string"
LIST: Final = "list"
OPTION_TYPES: Final = (FLAG, INT, STRING, LIST)


@dataclass(frozen=True, slots=True)
class OptionSpec:
    """One known sudoers option."""

    name: str
    type: str
    description: str


def _catalog(*entries: tuple[str, str, str]) -> dict[str, OptionSpec]:
    return {name: OptionSpec(name, kind, text) for name, kind, text in entries}


OPTIONS: Final[dict[str, OptionSpec]] = _catalog(
    # --- environment
    ("env_reset", FLAG, "Start commands from a minimal, sanitised environment."),
    ("env_keep", LIST, "Variables preserved from the caller's environment."),
    ("env_check", LIST, "Variables kept only when their value looks safe."),
    ("env_delete", LIST, "Variables always removed from the environment."),
    ("env_file", STRING, "File with extra variables to set for the command."),
    ("secure_path", STRING, "PATH used when running commands."),
    ("setenv", FLAG, "Allow the caller to set environment variables on the command line."),
    ("set_home", FLAG, "Set HOME to the target user's home directory."),
    ("always_set_home", FLAG, "Always set HOME to the target user's home directory."),
    ("preserve_groups", FLAG, "Keep the caller's supplementary groups."),
    ("stay_setuid", FLAG, "Keep the real uid equal to the target user's."),
    ("umask", INT, "Umask applied to the command (octal digits, e.g. 0022)."),
    ("umask_override", FLAG, "Use the configured umask even if it is more permissive."),
    ("runcwd", STRING, "Working directory of the command."),
    ("runchroot", STRING, "Root directory of the command."),
    ("closefrom", INT, "First file descriptor left open for the command."),
    ("closefrom_override", FLAG, "Allow the caller to choose the closefrom value."),
    ("ignore_dot", FLAG, "Ignore '.' and empty entries in the caller's PATH."),
    ("exec_background", FLAG, "Run the command in the background of its terminal."),
    # --- authentication
    ("authenticate", FLAG, "Require the caller to authenticate."),
    ("rootpw", FLAG, "Ask for the root password instead of the caller's."),
    ("runaspw", FLAG, "Ask for the password of the user given as the runas user."),
    ("targetpw", FLAG, "Ask for the password of the target user."),
    ("timestamp_timeout", INT, "Minutes an authentication stays valid (-1 never expires)."),
    ("timestamp_type", STRING, "Scope of the authentication cache (global, ppid, tty, kernel)."),
    ("passwd_tries", INT, "Number of password attempts allowed."),
    ("passwd_timeout", INT, "Minutes to wait for a password."),
    ("passprompt", STRING, "Text of the password prompt."),
    ("passprompt_override", FLAG, "Prefer the configured prompt over the environment's."),
    ("badpass_message", STRING, "Message shown after a wrong password."),
    ("visiblepw", FLAG, "Allow asking a password even when it would be echoed."),
    ("pwfeedback", FLAG, "Show a mask character for each typed password character."),
    ("insults", FLAG, "Print a humorous message after a wrong password."),
    ("lecture", STRING, "When to show the lecture (always, once or never)."),
    ("lecture_file", STRING, "File with the lecture text."),
    ("shell_noargs", FLAG, "Run a shell when no command is given."),
    ("path_info", FLAG, "Tell the caller when a command is not found in the path."),
    ("listpw", STRING, "When a password is needed to list privileges."),
    ("verifypw", STRING, "When a password is needed to validate the timestamp."),
    # --- terminal and execution
    ("requiretty", FLAG, "Only run from a real terminal."),
    ("use_pty", FLAG, "Run the command in a pseudo-terminal."),
    ("noexec", FLAG, "Prevent the command from running other programs."),
    ("intercept", FLAG, "Intercept sub-commands of the command."),
    ("log_subcmds", FLAG, "Log the sub-commands of the command."),
    ("fqdn", FLAG, "Match hosts with their fully qualified name."),
    ("match_group_by_gid", FLAG, "Match groups by numeric id as well as by name."),
    ("root_sudo", FLAG, "Allow root to run the sudo command."),
    ("allow_unknown_runas_id", FLAG, "Accept a runas user or group unknown to the system."),
    ("sudoedit_checkdir", FLAG, "Refuse to edit files in directories writable by the caller."),
    ("sudoedit_follow", FLAG, "Follow symbolic links when editing files."),
    ("rlimit_core", STRING, "Core file size limit for the command."),
    ("command_timeout", INT, "Seconds after which the command is terminated."),
    ("runas_default", STRING, "User used when none is given on the command line."),
    # --- logging
    ("log_input", FLAG, "Record the terminal input of the session."),
    ("log_output", FLAG, "Record the terminal output of the session."),
    ("log_allowed", FLAG, "Log commands that were allowed."),
    ("log_denied", FLAG, "Log commands that were denied."),
    ("log_host", FLAG, "Record the host name in log lines."),
    ("log_year", FLAG, "Record the year in log lines."),
    ("logfile", STRING, "File receiving the log lines (unset to disable)."),
    ("iolog_dir", STRING, "Directory holding session recordings."),
    ("iolog_file", STRING, "File name pattern of session recordings."),
    ("syslog", STRING, "Syslog facility used for logging (unset to disable)."),
    ("syslog_goodpri", STRING, "Syslog priority of allowed commands."),
    ("syslog_badpri", STRING, "Syslog priority of denied commands."),
    ("loglinelen", INT, "Maximum length of a log line."),
    # --- mail
    ("mailto", STRING, "Address receiving the notification mail."),
    ("mailfrom", STRING, "Sender address of the notification mail."),
    ("mailsub", STRING, "Subject of the notification mail."),
    ("mail_always", FLAG, "Send mail every time sudo is run."),
    ("mail_badpass", FLAG, "Send mail when the password is wrong."),
    ("mail_no_user", FLAG, "Send mail when the caller is not allowed to use sudo."),
    ("mail_no_host", FLAG, "Send mail when the caller may not run sudo on this host."),
    ("mail_no_perms", FLAG, "Send mail when the command is not permitted."),
    ("mail_all_cmnds", FLAG, "Send mail for any command, allowed or not."),
    ("mailerpath", STRING, "Path of the mail program."),
    ("mailerflags", STRING, "Flags passed to the mail program."),
)

_OPTION_RE: Final = re.compile(
    r"(?P<neg>!)?(?P<name>[A-Za-z0-9_]+)(?P<op>\+=|-=|=)?(?P<value>.*)", re.DOTALL
)
_INT_RE: Final = re.compile(r"-?[0-9]+")


@dataclass(frozen=True, slots=True)
class ParsedOption:
    """A syntactically valid ``sudoOption`` value."""

    spec: OptionSpec
    negated: bool
    operator: str
    value: str


def parse_option(text: str) -> ParsedOption:
    """Parse one ``sudoOption`` value.

    Raises :class:`ValueError` with a user-facing message when the value is
    malformed or breaks the rules listed in the module docstring.
    """
    match = _OPTION_RE.fullmatch(text.strip())
    if match is None:
        raise ValueError(_("Invalid option syntax."))
    name = match["name"]
    spec = OPTIONS.get(name)
    if spec is None:
        raise ValueError(_("Unknown option: {name}.").format(name=name))
    negated = match["neg"] is not None
    operator = match["op"] or ""
    value = match["value"].strip()

    if spec.type == FLAG:
        if operator or value:
            raise ValueError(_("{name} is a flag and takes no value.").format(name=name))
        return ParsedOption(spec, negated, "", "")
    if negated:
        if operator or value:
            raise ValueError(_("{name} cannot be unset and given a value.").format(name=name))
        return ParsedOption(spec, True, "", "")
    if not operator:
        raise ValueError(_("{name} needs a value (name=value).").format(name=name))
    if operator != "=" and spec.type != LIST:
        raise ValueError(_("{name} is not a list: use '=' to set it.").format(name=name))
    if not value:
        raise ValueError(_("{name} needs a value.").format(name=name))
    if spec.type == INT and _INT_RE.fullmatch(value) is None:
        raise ValueError(_("{name} needs an integer value.").format(name=name))
    return ParsedOption(spec, False, operator, value)


def option_error(text: str) -> str | None:
    """Return the problem with ``text`` or ``None`` when it is valid."""
    try:
        parse_option(text)
    except ValueError as exc:
        return str(exc)
    return None


__all__ = [
    "FLAG",
    "INT",
    "LIST",
    "OPTIONS",
    "OPTION_TYPES",
    "STRING",
    "OptionSpec",
    "ParsedOption",
    "option_error",
    "parse_option",
]
