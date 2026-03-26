"""
Configuration utilities. Contains no business logic.

"""

import copy
import inspect
import tomllib

import click
from click.core import ParameterSource


def config_option(*args, **kwargs):
    return click.option(
        *args,
        type=InteractiveFile('rb'),
        callback=load_defaults,
        is_eager=True,
        expose_value=False,
        **kwargs,
    )


def load_config(command, args=None):
    """Return the parameters from invoking command with args,
    but without actually running any (sub)command.

    Together with an option using load_defaults(),
    allows using Click to parse a config file,
    honoring the same defaults and environment variables.

    Returns a {command path: parameters, ...} dict
    where the path of the root command is '' (the empty string)

    Click UsageErrors are left to bubble up.

    """
    command = copy.deepcopy(command)
    calls = {}

    def callback(**kwargs):
        calls.update(load_config_from_context())

    def patch_command(command):
        command.callback = callback
        command.no_args_is_help = False
        if hasattr(command, 'commands'):
            command.invoke_without_command = True
            for subcommand in command.commands.values():
                patch_command(subcommand)

    patch_command(command)
    command(args, standalone_mode=False, prog_name='')
    return calls


def load_config_from_context():
    """Like load_config(), but from inside a running command."""
    ctx = click.get_current_context()
    root = ctx.find_root()
    rv = {}
    while ctx:
        if ctx is root:
            path = ''
        else:
            path = ctx.command_path.removeprefix(root.info_name + ' ')
        rv[path] = ctx.params
        ctx = ctx.parent
    return rv


def load_defaults(ctx, param, value):
    """Option callback: set the root context default_map from a click.File().

    Values come from a TOML section matching auto_envvar_prefix.lower().

    """
    if not value:
        return

    section_name = ctx.find_root().auto_envvar_prefix.lower()

    try:
        config = tomllib.load(value)
    except tomllib.TOMLDecodeError as e:
        param.type.fail(f"TOML error: {e}", param, ctx)

    if section_name not in config:
        param.type.fail(f"No [{section_name}] section found", param, ctx)

    default_map = config[section_name]
    root = ctx.find_root()

    if errors := validate_default_map(root.command, default_map, section_name):
        sep = '\n* '
        message = f"\n{sep}{sep.join(errors)}\n"
        param.type.fail(message, param, ctx)

    root.default_map = default_map
    return config


def validate_default_map(command, default_map, section_name):

    def validate(command, map, path=section_name):
        if map is None:
            return
        if not isinstance(map, dict):
            yield f"{path}: Expected mapping, got: {type(map).__name__}"
            return

        map = map.copy()
        for param in command.params:
            map.pop(param.name, None)
        for sub_name, sub in getattr(command, 'commands', {}).items():
            yield from validate(sub, map.pop(sub_name, None), f"{path}.{sub_name}")

        for key in map:
            yield f"{path}.{key}: No such option or command"

    return list(reversed(list(validate(command, default_map))))


class InteractiveFile(click.File):
    """Like click.File, but can be missing if the value is not from command line."""

    def convert(self, value, param, ctx):
        try:
            return super().convert(value, param, ctx)
        except click.BadParameter:
            source = ctx.get_parameter_source(param.name)
            if source not in (ParameterSource.DEFAULT, ParameterSource.ENVIRONMENT):
                raise
            return None


def extend_defaults(ctx, param, value):
    """Option callback: extend default_map values instead of replacing them."""
    source = ctx.get_parameter_source(param.name)
    if source == ParameterSource.DEFAULT_MAP:
        return value
    raw_defaults = (ctx.default_map or {}).get(param.name, [])
    defaults = param.type_cast_value(ctx, raw_defaults)
    defaults = tuple(d for d in defaults if d not in value)
    return defaults + value


def extract_args(params, callable):
    rv = {}
    for sp in inspect.signature(callable).parameters.values():
        if 'KEYWORD' not in sp.kind.name:
            continue
        if sp.name in params:
            rv[sp.name] = params[sp.name]
    return rv
