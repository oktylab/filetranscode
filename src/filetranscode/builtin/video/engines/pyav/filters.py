import av
import av.error

from ...css import avfilter_stages
from ...models import atempo_factors


###########################################################################################################
###########################################################################################################
ROTATE_STEPS: dict[int, list[tuple[str, str]]] = {
    90: [("transpose", "2")],
    180: [("hflip", ""), ("vflip", "")],
    270: [("transpose", "1")],
}


def video_steps(plan, metadata) -> list[tuple[str, str]]:
    steps = list(ROTATE_STEPS.get(metadata.rotation, []))
    if metadata.sar != 1.0:
        steps += [("scale", f"{metadata.width}:{metadata.height}"), ("setsar", "1")]
    if plan.crop:
        steps.append(("crop", f"{plan.crop.width}:{plan.crop.height}:{plan.crop.x}:{plan.crop.y}"))
    base = (plan.crop.width, plan.crop.height) if plan.crop else (metadata.width, metadata.height)
    if (plan.width, plan.height) != base:
        steps.append(("scale", f"{plan.width}:{plan.height}"))
    if plan.speed != 1.0:
        steps.append(("setpts", f"PTS/{plan.speed:g}"))
    if plan.fps and (plan.fps != metadata.fps or plan.speed != 1.0):
        steps.append(("fps", f"{plan.fps:g}"))
    steps += avfilter_stages(plan.color, plan.height, plan.pix_fmt, metadata)
    return steps


###########################################################################################################
###########################################################################################################
def build_graph(video, steps: list[tuple[str, str]]):
    if not steps:
        return None
    graph = av.filter.Graph()
    chain = [graph.add_buffer(template=video)]
    for name, args in steps:
        chain.append(graph.add(name, args))
    chain.append(graph.add("buffersink"))
    for left, right in zip(chain, chain[1:]):
        left.link_to(right)
    graph.configure()
    return graph


def drain_graph(graph):
    while True:
        try:
            yield graph.pull()
        except (av.error.BlockingIOError, av.error.EOFError):
            return


def filtered(graph, frame):
    if graph is None:
        return [frame]
    graph.push(frame)
    return list(drain_graph(graph))


###########################################################################################################
###########################################################################################################
def audio_graph(audio, plan):
    if (plan.speed == 1.0 and plan.volume == 1.0) or audio is None:
        return None
    graph = av.filter.Graph()
    chain = [graph.add_abuffer(template=audio)]
    if plan.volume != 1.0:
        chain.append(graph.add("volume", f"{plan.volume:g}"))
    if plan.speed != 1.0:
        for factor in atempo_factors(plan.speed):
            chain.append(graph.add("atempo", f"{factor:g}"))
    chain.append(graph.add("abuffersink"))
    for left, right in zip(chain, chain[1:]):
        left.link_to(right)
    graph.configure()
    return graph
