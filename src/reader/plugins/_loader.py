from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import dataclass
from pkgutil import resolve_name

from ..exceptions import InvalidPluginError
from ..exceptions import PluginInitError

type PluginFunc[T] = Callable[[T], None]
type PluginInput[T] = str | PluginFunc[T]


@dataclass
class PluginLoader:
    default_func: str
    builtin_package: str | None = None

    # TODO: Remove legacy reader.<plugin> support in 4.0.
    process_name: Callable[[str], str | None] | None = None

    def load[T](self, plugin: PluginInput[T]) -> Plugin[T]:
        if not isinstance(plugin, str):
            return Plugin(plugin, None)

        name = plugin

        if self.process_name:
            name = self.process_name(name) or name

        builtin = False
        if name.startswith('.'):
            if self.builtin_package is None:
                raise InvalidPluginError(f"built-in plugins not supported: {plugin}")
            builtin = True
            name = self.builtin_package + name

        if ':' not in name:
            name = name + ':' + self.default_func

        try:
            func = resolve_name(name)
        except (ValueError, ImportError, AttributeError) as e:
            what = "built-in plugin" if builtin else "plugin"
            raise InvalidPluginError(f"no such {what}: {plugin}") from e
        except Exception as e:
            raise InvalidPluginError(f"during plugin import: {plugin}") from e

        return Plugin(func, plugin)

    def load_many[T](self, plugins: Iterable[PluginInput[T]]) -> list[Plugin[T]]:
        # convenience method
        return [self.load(plugin) for plugin in plugins]

    def init_many[T](self, target: T, plugins: Iterable[Plugin[T]]) -> None:
        for plugin in plugins:
            plugin.init(target)

    def oneshot[T](self, target: T, plugins: Iterable[PluginInput[T]]) -> None:
        self.init_many(target, self.load_many(plugins))


@dataclass
class Plugin[T]:
    func: PluginFunc[T]
    name: str | None

    def init(self, target: T) -> None:
        try:
            self.func(target)
        except Exception as e:
            if self.name:
                name = self.name
            else:
                name = f"{self.func.__module__}:{self.func.__qualname__}"
            raise PluginInitError(f"during plugin initialization: {name}") from e
