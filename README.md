# filetranscode

A pluggable, typed pipeline engine for file processing, not just video and photo. The core (`Node`, `Sequence`, `Branch`, a shared `Registry`) knows nothing about media; it's a generic tree of typed, named, swappable steps that anything can register into. Video and photo ship as the two builtin pipelines, each exposing probe/plan/export operations, but writing a new pipeline (audio, PDF, a spreadsheet transform, anything file-shaped) is the intended way to extend this library, not an afterthought.

## Install

```sh
pip install filetranscode                 # core: video via the ffmpeg binary, photo via pillow
pip install 'filetranscode[pyav]'         # adds the pyav video engine
pip install 'filetranscode[moviepy]'      # adds the moviepy video engine
pip install 'filetranscode[cli]'          # adds the web ui served by `filetranscode server start`
```

System requirements: the video pipeline shells out to `ffmpeg`/`ffprobe`. The photo pipeline is pure pillow (HEIF included); an `imagemagick` engine registers itself automatically when the `magick` binary is present.

## Use the builtin pipelines

```python
from filetranscode import PhotoPipeline, VideoPipeline

video = VideoPipeline()
metadata = await video.probe(input="clip.mov")
plan = await video.plan(input="clip.mov", config={"preset": "instagram_reel"})
await video.export(input="clip.mov", output="reel.mp4", config={"preset": "instagram_reel"})

photo = PhotoPipeline()
await photo.export(input="shot.heic", output="post.jpg", config={"preset": "instagram_photo"})
```

Planning also works from metadata alone, no file, no probe:

```python
from filetranscode.builtin.photo.models import PhotoMetadata

meta = PhotoMetadata(format="png", width=4000, height=3000, mode="RGBA", alpha=True, size=18_000_000)
plan = await photo.plan(metadata=meta, config={"preset": "instagram_photo"})
```

`plan` returns an `ExportPlan` (action, target format/codec, geometry, quality, reasons) or raises `UnsatisfiableError` with a plain explanation of which constraint cannot be met.

Instead of a preset, pass explicit constraints: `config={"photo_constraints": {"formats": ["jpeg"], "max_bytes": 5_000_000}}`. Filters (brightness, contrast, saturation, hue, grayscale, sepia, invert) and edits (aspect, trim, speed, volume, background, still) ride along in the same config.

## CLI and web UI

Every public operation is also a command and a web page, for any pipeline, builtin or plugin:

```sh
filetranscode photo export --input shot.heic --output post.jpg --preset instagram_photo
filetranscode video probe --input clip.mov
filetranscode server start        # needs the cli extra
```

## Writing a plugin

A plugin is a normal Python package that imports `filetranscode` and registers things into the shared registry on import, then declares itself under the `filetranscode.plugins` entry point group so `import filetranscode` picks it up automatically. There is no special plugin base class or manifest format: registering a node is the whole interface.

The builtin pipelines never hold a fixed reference to the thing they call. A `Branch` looks its child up by name at call time, so a plugin adding an entry to that branch after the pipeline is already built and running takes effect on the very next call, with zero changes to any builtin file. That one mechanism covers every extension point:

- **A new engine** for an existing pipeline: register a `Node` under `"video.engine.<name>"` and it shows up as a CLI/API/UI engine choice immediately.
- **A new codec, format, or preset**: extend the relevant `Branch` or data dict the same way.
- **A new resolver**: pipelines resolve their `input`/`output` role by URL scheme through a `Branch`, so a plugin can add e.g. `s3://` support to `video.resolve` and `video.output` without the pipeline knowing S3 exists. See [filetranscode-s3](https://github.com/oktylab/filetranscode-s3) for a real example.
- **A whole new pipeline**: subclass `Pipeline`, decorate its methods with `@node`/`@engine_node`, and it gets probe/plan/export style operations, a CLI group, an HTTP API, and a web form for free, the same machinery video and photo use.

```python
from filetranscode.registry import registry
from filetranscode.builtin.toolkit.input_resolve import InputData, InputResolver

class MyResolver(InputResolver):
    accepts = str
    async def __call__(self, ctx):
        ctx.input = [InputData(raw_bytes=fetch_it(ctx.params.input))]
        return ctx

registry.get("photo.resolve").add("myscheme", MyResolver())
```

```toml
[project.entry-points."filetranscode.plugins"]
myplugin = "my_plugin_package"
```

## License

MIT
