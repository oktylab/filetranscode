from ...css import avfilter_stages
from ...models import atempo_factors


###########################################################################################################
###########################################################################################################
def video_filters(plan, metadata) -> list[str]:
    steps = []
    if metadata.sar != 1.0:
        steps += [f"scale={metadata.width}:{metadata.height}", "setsar=1"]
    if plan.crop:
        steps.append(f"crop={plan.crop.width}:{plan.crop.height}:{plan.crop.x}:{plan.crop.y}")
    base = (plan.crop.width, plan.crop.height) if plan.crop else (metadata.width, metadata.height)
    if (plan.width, plan.height) != base:
        steps.append(f"scale={plan.width}:{plan.height}")
    if plan.speed != 1.0:
        steps.append(f"setpts=PTS/{plan.speed:g}")
    if plan.fps and (plan.fps != metadata.fps or plan.speed != 1.0):
        steps.append(f"fps={plan.fps:g}")
    steps += [f"{name}={escape(args)}" for name, args in avfilter_stages(plan.color, plan.height, plan.pix_fmt, metadata)]
    return steps


###########################################################################################################
###########################################################################################################
def escape(args: str) -> str:
    return args.replace(",", "\\,")


###########################################################################################################
###########################################################################################################
def audio_filters(plan) -> list[str]:
    steps = []
    if plan.volume != 1.0:
        steps.append(f"volume={plan.volume:g}")
    if plan.speed != 1.0:
        steps += [f"atempo={factor:g}" for factor in atempo_factors(plan.speed)]
    return steps
