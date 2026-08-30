import av
from av.codec.codec import UnknownCodecError

from .....exceptions import EngineError
from ...models import ExportPlan


###########################################################################################################
###########################################################################################################
def pick_encoder(names: list[str]) -> str:
    for name in names:
        try:
            av.Codec(name, "w")
            return name
        except UnknownCodecError:
            continue
    raise EngineError(f"pyav has none of the encoders {names}")


###########################################################################################################
###########################################################################################################
def supported_rate(codec, wanted: int) -> int:
    rates = codec.audio_rates
    if not rates or wanted in rates:
        return wanted
    return min(rates, key=lambda rate: abs(rate - wanted))


###########################################################################################################
###########################################################################################################
def rate_options(plan: ExportPlan, encoder: str) -> dict[str, str]:
    rate = plan.rate
    if rate is None:
        return {}
    style = plan.rc.get(encoder)
    if rate.mode == "abr":
        if style == "abr-vbv" and rate.capped and rate.bitrate:
            return {"maxrate": str(rate.bitrate), "bufsize": str(2 * rate.bitrate)}
        if style in ("vbv", "abr-vbv") and rate.maxrate:
            return {"maxrate": str(rate.maxrate), "bufsize": str(rate.bufsize)}
        return {}
    if style == "vbv" and rate.capped and rate.maxrate:
        return {"maxrate": str(rate.maxrate), "bufsize": str(rate.bufsize)}
    if style == "cq":
        return {"b": str(rate.maxrate) if rate.capped and rate.maxrate else "0"}
    if style == "budget" and rate.maxrate:
        return {"b": str(rate.maxrate)}
    return {}
