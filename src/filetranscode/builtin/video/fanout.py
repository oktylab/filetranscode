import asyncio
import io
import math
import os
from fractions import Fraction

from ...core.core import Node
from ...core.trace import span
from ...exceptions import UnsatisfiableError
from ..toolkit.introspect import param
from ..toolkit.output_resolve import AsBytes, OutputData
from .models import Chunk, resamples

CHUNK_BITRATE_FACTOR = 0.88
CHUNK_CAP_FACTOR = 0.85


###########################################################################################################
###########################################################################################################
class AdoptPlan(Node):
    async def __call__(self, ctx):
        ctx.plan = ctx.params.plan.model_copy(deep=True)
        return ctx


###########################################################################################################
###########################################################################################################
class AdoptChunks(Node):
    # merge given the source: the listed chunks become the pending outputs, so the source can take the input slot
    async def __call__(self, ctx):
        ctx.output = [OutputData(raw_path=data.raw_path, raw_stream=data.raw_stream, raw_bytes=data.raw_bytes) for data in ctx.input]
        return ctx


###########################################################################################################
###########################################################################################################
class SplitChunks(Node):
    # split's result: each chunk with the source time it covers, which chunk_plans and merge need
    async def __call__(self, ctx):
        ctx.out = [Chunk(output=output, duration=duration) for output, duration in zip(ctx.out, ctx.spans, strict=True)]
        return ctx


###########################################################################################################
###########################################################################################################
class MergeLengths(Node):
    # merge given the plan and the split's durations: each chunk lasts the length its plan gives, in the order kept
    async def __call__(self, ctx):
        durations = getattr(ctx.params, "durations", None)
        if ctx.plan is not None and durations:
            ctx.lengths = [plan.length for plan in chunk_plans(ctx.plan, durations) if plan]
        return ctx


###########################################################################################################
###########################################################################################################
class FanOutExport(Node):
    def __init__(self, pipeline) -> None:
        self.pipeline = pipeline

    async def __call__(self, ctx):
        limit = asyncio.Semaphore(os.cpu_count() or 4)
        config = param(ctx, "config")
        if ctx.plan.trim_start is not None or ctx.plan.trim_end is not None or ctx.plan.speed != 1.0:
            probed = [(await self.pipeline.probe(input=chunk.path, engine=config.engine))[0] for chunk in ctx.output]
            if any(metadata.audio for metadata in probed):
                raise UnsatisfiableError(f"fanout trims and speed need chunks without audio, which the {config.engine} engine's split keeps; use export")

        async def export_chunk(index, chunk, plan):
            async with limit:
                with span("Chunk", str(index)):
                    return await self.pipeline.export(input=chunk.bytes_, output=AsBytes(), config=config, plan=plan)

        kept = [(chunk, plan) for chunk, plan in zip(ctx.output, chunk_plans(ctx.plan, ctx.spans)) if plan]
        ctx.lengths = [plan.length for _, plan in kept]
        delivered = await asyncio.gather(*(export_chunk(index, chunk, plan) for index, (chunk, plan) in enumerate(kept)))
        for chunk in ctx.output:
            chunk.cleanup()
        # the exported chunks are the pending outputs merge reassembles; the source stays as the input (its soundtrack)
        ctx.output = [OutputData(raw_bytes=data.getvalue() if isinstance(data, io.BytesIO) else bytes(data)) for data in delivered]
        return ctx


###########################################################################################################
###########################################################################################################
def _chunk_plan(plan):
    rate = plan.rate
    if rate is None:
        return plan
    updates = {}
    if rate.bitrate:
        updates["bitrate"] = int(rate.bitrate * CHUNK_BITRATE_FACTOR)
    if rate.capped and rate.maxrate:
        updates["maxrate"] = int(rate.maxrate * CHUNK_CAP_FACTOR)
        if rate.bufsize:
            updates["bufsize"] = 2 * updates["maxrate"]
    return plan.model_copy(update={"rate": rate.model_copy(update=updates)}) if updates else plan


###########################################################################################################
###########################################################################################################
def chunk_plans(plan, durations: list[float]) -> list:
    """The plan each split chunk exports with, None for a chunk the trim window drops or that holds no frame of the
    output. `durations` are the source time each chunk covers, as the split found it (Chunk.duration): the cuts land on
    keyframes, not on multiples of chunk_seconds, and a chunk file's own length misses the gap to the next chunk.
    Trims are rebased onto the chunk holding the window's edges, and every chunk plan carries the `length` it lasts in
    the merged output, which the merge places it by. A plan that resamples (capped rate, speed) lays one constant rate
    grid from the output's start, as the single pass does: each chunk delivers exactly that grid's frames inside its
    span, from the grid's phase at its start, so the per-chunk rounding never adds up into drift."""
    plan = _chunk_plan(plan)
    start, end = plan.trim_start or 0.0, math.inf if plan.trim_end is None else plan.trim_end
    begins = [sum(durations[:index]) for index in range(len(durations))]
    plans = []
    for index, (begin, duration) in enumerate(zip(begins, durations)):
        # the last chunk keeps a trim end past the probed source end (the planner allows a frame of slack there)
        stop = begin + duration if index < len(durations) - 1 else math.inf
        if stop <= start or begin >= end:
            plans.append(None)
            continue
        update = {"trim_start": start - begin if start > begin else None, "trim_end": end - begin if end < stop else None}
        kept = (max(begin, start), min(begin + duration, end))
        if resamples(plan):
            # the chunk's span in output frames of the rate the engines filter to; the frame count ends the chunk
            rate = float(Fraction(plan.fps).limit_denominator(1001))
            first, last = ((time - start) / plan.speed * rate for time in kept)
            if round(last) <= round(first):
                plans.append(None)
                continue
            frames = round(last) - round(first)
            update.update(frames=frames, first_frame_at=(round(first) - first) / rate, length=frames / rate, trim_end=None)
        else:
            update["length"] = kept[1] - kept[0]
        plans.append(plan.model_copy(update=update))
    return _place_frame_image(plans)


def _place_frame_image(plans: list) -> list:
    # the frame image belongs to the first or last chunk the trim keeps, every other chunk exports without it
    kept = [index for index, plan in enumerate(plans) if plan]
    if not kept or plans[kept[0]].frame_image is None:
        return plans
    target = kept[0] if plans[kept[0]].frame_image_at == "first" else kept[-1]
    return [plan if plan is None or index == target else plan.model_copy(update={"frame_image": None}) for index, plan in enumerate(plans)]
