from ...models import ExportPlan


###########################################################################################################
###########################################################################################################
def rate_args(plan: ExportPlan, encoder: str) -> list[str]:
    rate = plan.rate
    if rate is None:
        return []
    style = plan.rc.get(encoder)
    if rate.mode == "abr":
        args = ["-b:v", str(rate.bitrate)] if rate.bitrate else []
        if style == "abr-vbv" and rate.capped and rate.bitrate:
            args += ["-maxrate", str(rate.bitrate), "-bufsize", str(2 * rate.bitrate)]
        elif style in ("vbv", "abr-vbv") and rate.maxrate:
            args += ["-maxrate", str(rate.maxrate), "-bufsize", str(rate.bufsize)]
        return args
    if style == "vbv" and rate.capped and rate.maxrate:
        return ["-maxrate", str(rate.maxrate), "-bufsize", str(rate.bufsize)]
    if style == "cq":
        return ["-b:v", str(rate.maxrate) if rate.capped and rate.maxrate else "0"]
    if style == "budget" and rate.maxrate:
        return ["-b:v", str(rate.maxrate)]
    return []
