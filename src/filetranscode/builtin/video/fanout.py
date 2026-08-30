import asyncio
import io
import os

from ...core.core import Node
from ...core.trace import span
from ...exceptions import UnsatisfiableError
from ..toolkit.input_resolve import InputData
from ..toolkit.introspect import param
from ..toolkit.output_resolve import AsBytes

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
class FanOutExport(Node):
    def __init__(self, pipeline) -> None:
        self.pipeline = pipeline

    async def __call__(self, ctx):
        if ctx.plan.trim_start is not None or ctx.plan.trim_end is not None or ctx.plan.speed != 1.0:
            raise UnsatisfiableError("fanout does not support trims or speed yet; use export")
        limit = asyncio.Semaphore(os.cpu_count() or 4)
        plan = _chunk_plan(ctx.plan)
        config = param(ctx, "config")

        async def export_chunk(index, chunk):
            async with limit:
                with span("Chunk", str(index)):
                    return await self.pipeline.export(input=chunk.bytes_, output=AsBytes(), config=config, plan=plan)

        delivered = await asyncio.gather(*(export_chunk(index, chunk) for index, chunk in enumerate(ctx.output)))
        for chunk in ctx.output:
            chunk.cleanup()
        ctx.input = [InputData(raw_bytes=data.getvalue() if isinstance(data, io.BytesIO) else bytes(data)) for data in delivered]
        ctx.output = []
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
