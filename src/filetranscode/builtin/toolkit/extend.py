from pydantic import BaseModel


###########################################################################################################
###########################################################################################################
def extend_model(base: type[BaseModel], mixin: type[BaseModel]) -> None:
    overlap = set(base.model_fields) & set(mixin.model_fields)
    if overlap:
        raise TypeError(f"field conflict: {overlap} already on {base.__name__}, redeclared by {mixin.__name__}")
    base.__annotations__.update({name: field.annotation for name, field in mixin.model_fields.items()})
    base.__pydantic_fields__.update(mixin.model_fields)
    base.model_rebuild(force=True)
