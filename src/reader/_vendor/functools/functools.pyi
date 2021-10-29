"""
Copied from: https://github.com/python/typeshed/blob/master/stdlib/3/functools.pyi
Copyright: https://github.com/python/typeshed/blob/master/LICENSE

"""
from typing import Generic, TypeVar, Optional, Any, Callable, Type, overload

_T = TypeVar("_T")
_S = TypeVar("_S")

class cached_property(Generic[_T]):
    func: Callable[[Any], _T]
    attrname: Optional[str]
    def __init__(self, func: Callable[[Any], _T]) -> None: ...
    @overload
    def __get__(
        self, instance: None, owner: Optional[Type[Any]] = ...
    ) -> cached_property[_T]: ...
    @overload
    def __get__(self, instance: _S, owner: Optional[Type[Any]] = ...) -> _T: ...
    def __set_name__(self, owner: Type[Any], name: str) -> None: ...
