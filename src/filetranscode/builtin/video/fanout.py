import asyncio
import io
import math
import os

from ...core.core import Node
from ...core.trace import span
from ...exceptions import UnsatisfiableError
from ..toolkit.introspect import param
from ..toolkit.output_resolve import AsBytes, OutputData

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
class FanOutExport(Node):
    def __init__(self, pipeline) -> None:
        self.pipeline = pipeline

    async def __call__(self, ctx):
        limit = asyncio.Semaphore(os.cpu_count() or 4)
        config = param(ctx, "config")
        durations = [0.0] * len(ctx.output)
        if ctx.plan.trim_start is not None or ctx.plan.trim_end is not None or ctx.plan.speed != 1.0:
            probed = [(await self.pipeline.probe(input=chunk.path, engine=config.engine))[0] for chunk in ctx.output]
            if any(metadata.audio for metadata in probed):
                raise UnsatisfiableError(f"fanout trims and speed need chunks without audio, which the {config.engine} engine's split keeps; use export")
            durations = [metadata.duration for metadata in probed]

        async def export_chunk(index, chunk, plan):
            async with limit:
                with span("Chunk", str(index)):
                    return await self.pipeline.export(input=chunk.bytes_, output=AsBytes(), config=config, plan=plan)

        kept = [(chunk, plan) for chunk, plan in zip(ctx.output, chunk_plans(ctx.plan, durations)) if plan]
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
    """The plan each split chunk exports with, None for a chunk the trim window drops. Speed needs no per-chunk change
    (setpts stretches every chunk alike), trims do: the window's edges are rebased onto the chunk holding them.
    `durations` are the chunks' probed video durations, read only when the plan trims: the cuts land on keyframes,
    not on multiples of chunk_seconds."""
    plan = _chunk_plan(plan)
    if plan.trim_start is None and plan.trim_end is None:
        return [plan] * len(durations)
    start, end = plan.trim_start or 0.0, math.inf if plan.trim_end is None else plan.trim_end
    begins = [sum(durations[:index]) for index in range(len(durations))]
    plans = []
    for begin, stop in zip(begins, [*begins[1:], math.inf]):
        if stop <= start or begin >= end:
            plans.append(None)
            continue
        plans.append(plan.model_copy(update={"trim_start": start - begin if start > begin else None, "trim_end": end - begin if end < stop else None}))
    return plans
