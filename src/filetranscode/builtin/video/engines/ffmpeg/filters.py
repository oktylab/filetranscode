from fractions import Fraction

from ...css import avfilter_stages
from ...models import atempo_factors, resamples


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
    if resamples(plan):
        # an exact rate (60000/1001, not the 59.9401 :g prints), so every fanout chunk gets the same time base
        rate = Fraction(plan.fps).limit_denominator(1001)
        if plan.frames is None:
            steps.append(f"fps={rate}")
        else:
            # a fanout chunk takes its share of the whole output's grid: the grid's phase at its start, then exactly its
            # frame count. Its file ends at its last frame, short of the next chunk's start, so the last frame is passed
            # on at the end instead of rounded away, and the clone fills a grid point the end still leaves
            steps += [f"fps={rate}:start_time={plan.first_frame_at:.6f}:eof_action=pass", "tpad=stop_mode=clone:stop=1", f"trim=end_frame={plan.frames}", "setpts=PTS-STARTPTS"]
    steps += [f"{name}={escape(args)}" for name, args in avfilter_stages(plan.color, plan.height, plan.pix_fmt, metadata)]
    return steps


###########################################################################################################
###########################################################################################################
def output_fps(plan, metadata) -> float:
    return plan.fps or metadata.fps or 30.0


def frame_image_graph(plan, metadata, filters: list[str]) -> str:
    """The video filters, then the image (input 1, frame_image_frames frames each lasting one output frame) swapped in
    for the first or last that many frames. The last ones are dropped without knowing when the video ends: a copy that
    many frames ahead, shrunk to an invisible 2x2 overlay, runs out that many frames early and overlay=shortest stops
    the video there."""
    image = (f"[1:v]trim=end_frame={plan.frame_image_frames},scale={plan.width}:{plan.height}:force_original_aspect_ratio=increase,"
             f"crop={plan.width}:{plan.height},setsar=1,format={plan.pix_fmt},setpts=PTS-STARTPTS[image]")
    video = f"[0:v]{','.join(filters) or 'null'},setpts=PTS-STARTPTS"
    if plan.trim_end is not None:
        # the output's -t cut, made inside the graph so the swapped frame is the last one -t keeps
        video += f",trim=end={(plan.trim_end - (plan.trim_start or 0)) / plan.speed:.6f}"
    frames = plan.frame_image_frames
    if plan.frame_image_at == "first":
        return f"{video},trim=start_frame={frames},setpts=PTS-STARTPTS[rest];{image};[image][rest]concat=n=2:v=1:a=0[video]"
    return (f"{video},split[full][ahead];"
            f"[ahead]trim=start_frame={frames},setpts=PTS-STARTPTS,scale=2:2,format=yuva420p,colorchannelmixer=aa=0[mask];"
            f"[full][mask]overlay=shortest=1:format=auto[rest];{image};[rest][image]concat=n=2:v=1:a=0[video]")


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
