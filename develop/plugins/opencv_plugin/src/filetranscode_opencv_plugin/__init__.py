import cv2

from filetranscode.builtin.toolkit.output_resolve import OutputData
from filetranscode.builtin.toolkit.engine import Engine, operation, probing
from filetranscode.builtin.video.css import transform
from filetranscode.builtin.video.models import VideoMetadata
from filetranscode.exceptions import ProbeError
from filetranscode.registry import registry

FOURCC_CODECS = {"avc1": "h264", "h264": "h264", "hvc1": "hevc", "hev1": "hevc", "mp4v": "mpeg4", "xvid": "mpeg4", "vp08": "vp8", "vp09": "vp9", "av01": "av1", "mjpg": "mjpeg"}


###########################################################################################################
###########################################################################################################
class OpenCvEngine(Engine):
    #####################################################
    #####################################################
    @operation
    async def probe(self, ctx):
        datas, sink = probing(ctx)
        for data in datas:
            sink.append(self._probe(data))
        return ctx

    def _probe(self, data) -> VideoMetadata:
        capture = cv2.VideoCapture(data.path)
        if not capture.isOpened():
            raise ProbeError(data.path, "cv2 cannot open the file")
        fourcc = "".join(chr((int(capture.get(cv2.CAP_PROP_FOURCC)) >> (8 * index)) & 0xFF) for index in range(4)).strip().lower()
        fps = capture.get(cv2.CAP_PROP_FPS) or None
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or None
        metadata = VideoMetadata(
            size=data.size,
            codec=FOURCC_CODECS.get(fourcc, fourcc or "unknown"),
            width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            fps=fps,
            frame_count=frame_count,
            duration=frame_count / fps if frame_count and fps else None,
        )
        capture.release()
        return metadata

    #####################################################
    #####################################################
    @operation
    async def encode(self, ctx):
        plan = ctx.plan
        capture = cv2.VideoCapture(ctx.input[0].path)
        delivered = OutputData()
        path = delivered.temp(suffix=".mp4")
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), plan.fps or 30.0, (plan.width, plan.height))
        grade = transform(plan.color) if plan.color and not plan.color.identity() else None
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if (frame.shape[1], frame.shape[0]) != (plan.width, plan.height):
                frame = cv2.resize(frame, (plan.width, plan.height))
            if grade is not None:
                frame = grade(frame[..., ::-1])[..., ::-1]
            writer.write(frame)
        capture.release()
        writer.release()
        delivered.path = path
        ctx.output.append(delivered)
        return ctx

registry.register("video.engine.opencv", OpenCvEngine())
