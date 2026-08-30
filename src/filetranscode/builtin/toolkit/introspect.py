from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel


###########################################################################################################
###########################################################################################################
def unwrap(annotation: Any) -> Any:
    if get_origin(annotation) in (Union, UnionType):
        return next(arg for arg in get_args(annotation) if arg is not type(None))
    return annotation


###########################################################################################################
###########################################################################################################
def model_of(annotation: Any) -> type[BaseModel] | None:
    base = unwrap(annotation)
    if isinstance(base, type) and not get_args(base) and issubclass(base, BaseModel):
        return base
    return None


###########################################################################################################
###########################################################################################################
class Role(str):
    pass


###########################################################################################################
###########################################################################################################
def param(ctx: Any, role: str) -> Any:
    name = type(ctx.params).roles.get(role)
    return getattr(ctx.params, name) if name else None
