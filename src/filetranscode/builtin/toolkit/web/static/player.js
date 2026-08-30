class VideoSource{
  constructor(url){
    this.kind = "video";
    this.element = document.createElement("video");
    this.element.muted = false;
    this.element.preload = "auto";
    this.element.playsInline = true;
    this.element.src = url;
    this.ready = new Promise(resolve => this.element.addEventListener("loadedmetadata", () => resolve(this), {once: true}));
  }
  get size(){ return {w: this.element.videoWidth, h: this.element.videoHeight}; }
  get duration(){ return this.element.duration || 0; }
  get time(){ return this.element.currentTime; }
  set time(value){ this.element.currentTime = value; }
  get paused(){ return this.element.paused; }
  get rate(){ return this.element.playbackRate; }
  set rate(value){ this.element.playbackRate = value; }
  play(){ return this.element.play().catch(() => {}); }
  pause(){ this.element.pause(); }
  draw(context, rect){ context.drawImage(this.element, rect.x, rect.y, rect.w, rect.h); }
  onFrame(callback){
    if(!this.element.requestVideoFrameCallback) return;
    const loop = () => {callback(); this.element.requestVideoFrameCallback(loop);};
    this.element.requestVideoFrameCallback(loop);
  }
}

function sniffImageMime(bytes){
  if(bytes.length > 3 && bytes[0] === 0x47 && bytes[1] === 0x49 && bytes[2] === 0x46) return "image/gif";
  if(bytes.length > 11 && bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46
     && bytes[8] === 0x57 && bytes[9] === 0x45 && bytes[10] === 0x42 && bytes[11] === 0x50) return "image/webp";
  if(bytes.length > 3 && bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4E && bytes[3] === 0x47) return "image/png";
  return null;
}

function animationFrameIndex(durations, totalMs, elapsedMs){
  let remaining = elapsedMs % totalMs;
  for(let index = 0; index < durations.length; index++){
    remaining -= durations[index];
    if(remaining < 0) return index;
  }
  return durations.length - 1;
}

const MAX_ANIMATION_FRAMES = 600;

class ImageSource{
  constructor(url){
    this.kind = "image";
    this.animated = false;
    this.staticOnly = false;
    this.element = new Image();
    this.frames = [];
    this.durations = [];
    this.totalMs = 0;
    this._clock = 0;
    this.ready = this._open(url);
  }
  async _open(url){
    const fallback = new Promise(resolve => {
      this.element.addEventListener("load", () => resolve(this), {once: true});
      this.element.addEventListener("error", () => resolve(this), {once: true});
    });
    this.element.src = url;
    try{
      const data = await (await fetch(url)).arrayBuffer();
      const mime = sniffImageMime(new Uint8Array(data, 0, Math.min(16, data.byteLength)));
      if(mime && typeof ImageDecoder !== "undefined" && await ImageDecoder.isTypeSupported(mime)){
        const decoder = new ImageDecoder({data, type: mime});
        await decoder.tracks.ready;
        const track = decoder.tracks.selectedTrack;
        if(track && track.frameCount > 1){
          const count = Math.min(track.frameCount, MAX_ANIMATION_FRAMES);
          for(let index = 0; index < count; index++){
            const {image} = await decoder.decode({frameIndex: index});
            this.frames.push(image);
            this.durations.push((image.duration || 100000) / 1000);
          }
          this.totalMs = this.durations.reduce((total, duration) => total + duration, 0);
          this.animated = this.frames.length > 1 && this.totalMs > 0;
        }
        decoder.close();
      } else if(mime === "image/gif" && typeof ImageDecoder === "undefined"){
        this.staticOnly = true;
      }
    }catch(error){}
    await fallback;
    return this;
  }
  get size(){
    if(this.frames.length) return {w: this.frames[0].displayWidth, h: this.frames[0].displayHeight};
    return {w: this.element.naturalWidth, h: this.element.naturalHeight};
  }
  get duration(){ return this.animated ? this.totalMs / 1000 : 0; }
  get time(){ return this._clock; }
  set time(value){ this._clock = value; }
  get paused(){ return true; }
  get rate(){ return 1; }
  set rate(value){}
  play(){}
  pause(){}
  seek(value){ this._clock = value; }
  draw(context, rect){
    if(this.animated){
      const index = animationFrameIndex(this.durations, this.totalMs, this._clock * 1000);
      context.drawImage(this.frames[index], rect.x, rect.y, rect.w, rect.h);
      return;
    }
    context.drawImage(this.element, rect.x, rect.y, rect.w, rect.h);
  }
  onFrame(callback){}
  destroy(){
    this.frames.forEach(frame => frame.close());
    this.frames = [];
    this.animated = false;
  }
}

const MAX_DECODE_BUFFER = 500 * 1024 * 1024;
const DECODE_AHEAD = 8;

class DecodedVideoSource{
  constructor(url){
    this.kind = "video";
    this.url = url;
    this.failed = false;
    this.ended = false;
    this._frames = [];
    this._current = null;
    this._feed = 0;
    this._flushed = false;
    this.ready = this._init();
  }

  async _init(){
    try{
      if(typeof VideoDecoder === "undefined") throw new Error("WebCodecs unavailable");
      const {track, buffer} = await demuxMp4(this.url);
      if(buffer.byteLength > MAX_DECODE_BUFFER) throw new Error("file too large for decoded playback");
      this.track = track;
      this.buffer = buffer;
      const config = {codec: track.codec, description: track.description, hardwareAcceleration: "prefer-hardware"};
      const support = await VideoDecoder.isConfigSupported(config);
      if(!support.supported) throw new Error(`codec ${track.codec} unsupported`);
      this._decoder = new VideoDecoder({
        output: frame => {
          this._frames.push(frame);
          if(this._frameCallback) this._frameCallback();
        },
        error: () => {
          this.failed = true;
          if(this._frameCallback) this._frameCallback();
        },
      });
      this._config = config;
      this._decoder.configure(config);
      this._ctsUsec = track.samples.map(sample => Math.round(sample.cts / track.timescale * 1e6)).sort((a, b) => a - b);
      let runningMax = -1;
      this._fedMaxCts = track.samples.map(sample => runningMax = Math.max(runningMax, Math.round(sample.cts / track.timescale * 1e6)));
    }catch(error){
      this.failed = true;
    }
    return this;
  }

  get size(){
    const frame = this._current || this._frames[0];
    return frame ? {w: frame.displayWidth, h: frame.displayHeight} : {w: 0, h: 0};
  }
  get duration(){ return this.track ? this.track.duration : 0; }
  get time(){ return this._current ? this._current.timestamp / 1e6 : 0; }

  frameStep(){
    if(!this.track || this.track.samples.length < 2) return 1 / 30;
    const step = this.track.samples[0].duration / this.track.timescale;
    return step > 0 ? step : this.duration / this.track.samples.length;
  }

  _chunk(sample){
    return new EncodedVideoChunk({
      type: sample.keyframe ? "key" : "delta",
      timestamp: Math.round(sample.cts / this.track.timescale * 1e6),
      duration: Math.round((sample.duration || 1) / this.track.timescale * 1e6),
      data: new Uint8Array(this.buffer, sample.offset, sample.size),
    });
  }

  _pump(targetUsec){
    if(this.failed || !this._decoder || this._decoder.state !== "configured") return;
    const samples = this.track.samples;
    while(this._feed < samples.length
          && this._frames.length + this._decoder.decodeQueueSize < 64
          && (this._frames.length + this._decoder.decodeQueueSize < DECODE_AHEAD
              || (this._feed === 0 ? -1 : this._fedMaxCts[this._feed - 1]) < targetUsec)){
      this._decoder.decode(this._chunk(samples[this._feed]));
      this._feed++;
    }
    if(this._feed >= samples.length && !this._flushed){
      this._flushed = true;
      this._decoder.flush().then(() => {this.ended = true;}).catch(() => {});
    }
  }

  nextTime(t){
    const usec = Math.round(t * 1e6);
    const cts = this._ctsUsec;
    let low = 0, high = cts.length - 1, next = null;
    while(low <= high){
      const mid = (low + high) >> 1;
      if(cts[mid] > usec){ next = cts[mid]; high = mid - 1; }
      else low = mid + 1;
    }
    return next === null ? null : next / 1e6;
  }

  _targetTimestamp(usec){
    const cts = this._ctsUsec;
    let low = 0, high = cts.length - 1, best = cts[0];
    while(low <= high){
      const mid = (low + high) >> 1;
      if(cts[mid] <= usec){ best = cts[mid]; low = mid + 1; }
      else high = mid - 1;
    }
    return best;
  }

  present(t){
    if(this.failed) return true;
    if(!this.track) return false;
    const usec = Math.round(t * 1e6);
    this._pump(usec);
    while(this._frames.length && this._frames[0].timestamp <= usec){
      if(this._current) this._current.close();
      this._current = this._frames.shift();
    }
    if(!this._current && this._frames.length){
      this._current = this._frames.shift();
      return true;
    }
    if(!this._current) return this.ended;
    return this._current.timestamp >= this._targetTimestamp(usec) || this.ended;
  }

  seek(t){
    if(this.failed || !this.track || !this._decoder) return;
    const usec = Math.round(t * 1e6);
    const samples = this.track.samples;
    let target = samples.length - 1;
    for(let i = 0; i < samples.length; i++){
      if(samples[i].cts / this.track.timescale * 1e6 > usec){ target = Math.max(0, i - 1); break; }
    }
    let key = 0;
    for(let i = target; i >= 0; i--){
      if(samples[i].keyframe){ key = i; break; }
    }
    this._frames.forEach(frame => frame.close());
    this._frames = [];
    if(this._current){ this._current.close(); this._current = null; }
    this._decoder.reset();
    this._decoder.configure(this._config);
    this._feed = key;
    this._flushed = false;
    this.ended = false;
  }

  play(){}
  pause(){}
  onFrame(callback){ this._frameCallback = callback; }
  draw(context, rect){ if(this._current) context.drawImage(this._current, rect.x, rect.y, rect.w, rect.h); }

  destroy(){
    this._frames.forEach(frame => frame.close());
    this._frames = [];
    if(this._current){ this._current.close(); this._current = null; }
    if(this._decoder && this._decoder.state !== "closed") this._decoder.close();
  }
}

const SOURCE_KINDS = {video: DecodedVideoSource, image: ImageSource};

function sourceFor(kind, url){
  const Kind = SOURCE_KINDS[kind];
  return Kind ? new Kind(url) : null;
}

function fitRect(size, box){
  const scale = Math.min(box.w / size.w, box.h / size.h);
  const w = size.w * scale, h = size.h * scale;
  return {x: box.x + (box.w - w) / 2, y: box.y + (box.h - h) / 2, w, h};
}

function evenSnap(value){
  const half = value / 2;
  const floor = Math.floor(half);
  const fraction = half - floor;
  const nearest = fraction > 0.5 ? floor + 1 : fraction < 0.5 ? floor : (floor % 2 ? floor + 1 : floor);
  return 2 * nearest;
}

function cropRegion(size, ratio, snap = "even"){
  const source = size.w / size.h;
  if(!ratio || Math.abs(source / ratio - 1) <= 0.01) return null;
  const fit = snap === "pixel" ? Math.round : evenSnap;
  const align = snap === "pixel" ? (v => Math.floor(v / 2)) : (v => Math.floor(Math.floor(v / 2) / 2) * 2);
  let w = size.w, h = size.h;
  if(ratio < source) w = fit(size.h * ratio);
  else h = fit(size.w / ratio);
  const x = align(size.w - w);
  const y = align(size.h - h);
  return {x: x / size.w, y: y / size.h, w: w / size.w, h: h / size.h};
}

const SYNC_NUDGE = 0.02;
const SYNC_SNAP = 0.25;
const DIVIDER_GRAB = 14;

class Comparator{
  constructor(canvas, {original = null, result = null, offset = 0, speed = 1} = {}){
    this.canvas = canvas;
    this.context = canvas.getContext("2d");
    this.original = original;
    this.result = result;
    this.offset = offset;
    this.speed = speed || 1;
    this.view = "split";
    this.divider = 0.5;
    this.zoom = {scale: 1, x: 0, y: 0};
    this.aspect = null;
    this.filter = "";
    this.dragging = null;
    this.approx = false;
    this.clock = 0;
    this.playing = false;
    this.destroyed = false;
    this._renderTimes = [];
    this._bindPointers();
    this._loop = this._loop.bind(this);
    this.ready = this._ensureSources().then(() => {
      this._present(this.clock);
      this.render();
      return this;
    });
    requestAnimationFrame(this._loop);
  }

  async _ensureSources(){
    await Promise.all([this.original, this.result].filter(Boolean).map(source => source.ready));
    const anyFailed = ["original", "result"].some(role => this[role] && this[role].kind === "video" && this[role].failed);
    if(anyFailed){
      this.approx = true;
      for(const role of ["original", "result"]){
        const source = this[role];
        if(source && source.kind === "video"){
          if(source.destroy) source.destroy();
          this[role] = new VideoSource(source.url);
          await this[role].ready;
        }
      }
    }
    if(this.approx){
      this.videos.forEach(source => source.onFrame(() => this.render()));
      if(this.slave && this.slave.element) this.slave.element.muted = true;
    } else {
      this.videos.forEach(source => source.onFrame(() => {
        if(!this.playing){
          this._present(this.clock);
          this.render();
        }
      }));
    }
    if([this.original, this.result].some(source => source && source.kind === "image" && source.animated)){
      this.playing = true;
    }
  }

  _cropRatio(){

    const resultSize = this.result && this.result.size && this.result.size.w ? this.result.size : null;
    if(this.aspect && resultSize) return resultSize.w / resultSize.h;
    return this.aspect;
  }

  _cropSnap(){
    const lead = this.original || this.result;
    return lead && lead.kind === "image" ? "pixel" : "even";
  }

  _mapped(source, t){
    return source === this.original ? t * this.speed + this.offset : t;
  }

  _present(t){
    [this.original, this.result].filter(Boolean).forEach(source => {
      if(source.present) source.present(this._mapped(source, t));
    });
  }

  _lockstepReady(t){
    return [this.original, this.result].filter(Boolean).every(source =>
      source.present ? source.present(this._mapped(source, t)) : true);
  }

  get master(){
    const playable = source => source && (source.kind === "video" || source.animated);
    if(playable(this.result)) return this.result;
    if(playable(this.original)) return this.original;
    return this.original || this.result;
  }
  get slave(){ return this.master === this.result ? this.original : this.result; }
  get videos(){ return [this.original, this.result].filter(source => source && source.kind === "video"); }
  get paused(){ return this.approx ? (this.master ? this.master.paused : true) : !this.playing; }
  get time(){ return this.approx ? (this.master ? this.master.time : 0) : this.clock; }
  get duration(){ return this.master ? this.master.duration : 0; }

  setView(view){ this.view = view; this.render(); }
  setAspect(ratio){ this.aspect = ratio; this.render(); }
  setFilter(css){ this.filter = css; this.render(); }

  markers(){
    const master = this.master;
    if(!master || master.kind !== "image" || !master.animated) return [];
    let elapsed = 0;
    return master.durations.map(duration => {
      const at = elapsed / 1000;
      elapsed += duration;
      return at;
    });
  }

  play(){
    if(this.approx){
      this._syncSlave(true);
      this.videos.forEach(source => source.play());
      return;
    }
    const step = this.master && this.master.frameStep ? this.master.frameStep() : 1 / 30;
    if(this.duration && this.clock + step * 1.5 >= this.duration) this.seek(0);
    this.playing = true;
  }
  pause(){
    if(this.approx){
      this.videos.forEach(source => source.pause());
      this._syncSlave(true);
      this.render();
      return;
    }
    this.playing = false;
    this.render();
  }
  seek(time){
    if(this.approx){
      if(this.master) this.master.time = time;
      this._syncSlave(true);
      this.render();
      return;
    }
    this.clock = Math.max(0, Math.min(time, this.duration || time));
    [this.original, this.result].filter(Boolean).forEach(source => {
      if(source.seek) source.seek(this._mapped(source, this.clock));
    });
    this._present(this.clock);
    this.render();
  }

  _syncSlave(snap = false){
    const master = this.master, slave = this.slave;
    if(!master || !slave || slave.kind !== "video" || master.kind !== "video") return;
    const base = Number.isFinite(master.rate) ? master.rate : 1;
    const target = master.time + (slave === this.original ? this.offset : -this.offset);
    const drift = slave.time - target;
    if(snap || Math.abs(drift) > SYNC_SNAP){
      slave.time = target;
      slave.rate = base;
    } else if(Math.abs(drift) > SYNC_NUDGE){
      slave.rate = base * (drift > 0 ? 0.95 : 1.05);
    } else {
      slave.rate = base;
    }
  }

  _loop(){
    if(this.destroyed) return;
    const animatedImages = [this.original, this.result].filter(source => source && source.kind === "image" && source.animated);
    if(animatedImages.length){
      const now = performance.now();
      if(this.playing && this._imageLast !== undefined){
        this.clock += (now - this._imageLast) / 1000;
        if(this.duration && this.clock >= this.duration) this.clock %= this.duration;
      }
      this._imageLast = now;
      animatedImages.forEach(source => source.time = this.clock);
      this.render();
    }
    if(this.approx){
      if(this.master && this.master.kind === "video" && !this.master.paused){
        this._syncSlave();
        this.render();
      }
    } else if(this.playing && this.master && this.master.kind === "video"){
      const next = this.master.nextTime ? this.master.nextTime(this.clock)
                 : this.clock + (this.master.frameStep ? this.master.frameStep() : 1 / 30);
      if(next === null || next >= (this.duration || Infinity)){
        this.playing = false;
      } else if(this._lockstepReady(next)){
        this.clock = next;
        this.render();
      } else {
        this._present(next);
      }
    }
    requestAnimationFrame(this._loop);
  }

  resize(){
    const ratio = window.devicePixelRatio || 1;
    const box = this.canvas.getBoundingClientRect();
    this.canvas.width = Math.round(box.width * ratio);
    this.canvas.height = Math.round(box.height * ratio);
    this.render();
  }

  layout(){
    const ratio = window.devicePixelRatio || 1;
    const w = this.canvas.width / ratio, h = this.canvas.height / ratio;
    const originalSize = this.original && this.original.size.w ? this.original.size : null;
    const resultSize = this.result && this.result.size.w ? this.result.size : null;
    if(this.view === "side" && this.original && this.result){
      const gap = 8;
      const half = {w: (w - gap) / 2, h};
      return {
        mode: "side",
        original: originalSize ? fitRect(originalSize, {x: 0, y: 0, ...half}) : null,
        result: resultSize ? fitRect(resultSize, {x: half.w + gap, y: 0, ...half}) : null,
        crop: null,
      };
    }
    const base = originalSize ? fitRect(originalSize, {x: 0, y: 0, w, h})
               : resultSize ? fitRect(resultSize, {x: 0, y: 0, w, h}) : null;
    const region = originalSize && this.aspect ? cropRegion(originalSize, this._cropRatio(), this._cropSnap()) : null;
    const crop = base && region ? {x: base.x + region.x * base.w, y: base.y + region.y * base.h, w: region.w * base.w, h: region.h * base.h} : null;
    return {
      mode: "split",
      original: originalSize ? base : null,
      result: resultSize ? (crop || (originalSize ? base : null) || fitRect(resultSize, {x: 0, y: 0, w, h})) : null,
      crop,
    };
  }

  _checkerboard(context){
    if(!this._checker){
      const tile = document.createElement("canvas");
      tile.width = tile.height = 24;
      const brush = tile.getContext("2d");
      brush.fillStyle = "#ffffff";
      brush.fillRect(0, 0, 24, 24);
      brush.fillStyle = "#d7d7d7";
      brush.fillRect(0, 0, 12, 12);
      brush.fillRect(12, 12, 12, 12);
      this._checker = context.createPattern(tile, "repeat") || "#ffffff";
    }
    return this._checker;
  }

  render(){
    if(!this.context) return;
    const ratio = window.devicePixelRatio || 1;
    const context = this.context;
    const w = this.canvas.width / ratio, h = this.canvas.height / ratio;
    const zoom = this.zoom;
    const plan = this.layout();
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, w, h);
    context.fillStyle = this._checkerboard(context);
    context.fillRect(0, 0, w, h);
    context.save();
    context.translate(zoom.x, zoom.y);
    context.scale(zoom.scale, zoom.scale);
    const dividerX = (w * this.divider - zoom.x) / zoom.scale;
    if(plan.mode === "side"){
      this._drawOriginal(context, plan.original);
      if(plan.original) this._drawCropWindow(context, plan.original, {x: 0, y: 0, w, h});
      if(this.result && plan.result) this.result.draw(context, plan.result);
    } else {
      const showDivider = Boolean(this.original && this.result && plan.original && plan.result);
      this._drawOriginal(context, plan.original);
      if(plan.original) this._drawCropWindow(context, plan.original, {x: 0, y: 0, w, h});
      if(this.result && plan.result){
        context.save();
        if(showDivider){
          context.beginPath();
          context.rect(dividerX, -1e6, 1e6, 2e6);
          context.clip();
        }
        this.result.draw(context, plan.result);
        context.restore();
      }
    }
    context.restore();
    if(plan.mode === "split" && this.original && this.result){
      this._drawDivider(context, w * this.divider, h);
    }
    this._drawBadges(context, plan, w, h);
    this._drawHud(context, w);
  }

  _drawBadges(context, plan, w, h){
    if(!(this.original && this.result)) return;
    const badge = (text, x, y, align) => {
      context.save();
      context.font = "11px system-ui, sans-serif";
      context.textBaseline = "top";
      const width = context.measureText(text).width;
      const boxX = align === "right" ? x - width - 12 : x;
      context.fillStyle = "rgba(0,0,0,0.55)";
      context.fillRect(boxX, y, width + 12, 18);
      context.fillStyle = "#fff";
      context.fillText(text, boxX + 6, y + 4);
      context.restore();
    };
    if(plan.mode === "side"){
      if(plan.original) badge("original", plan.original.x + 6, plan.original.y + 6);
      if(plan.result) badge("result", plan.result.x + 6, plan.result.y + 6);
    } else {
      badge("original", 6, h - 24);
      badge("result", w - 6, h - 24, "right");
    }
  }

  _drawHud(context, w){
    const now = performance.now();
    this._renderTimes.push(now);
    while(this._renderTimes.length && this._renderTimes[0] < now - 1000) this._renderTimes.shift();
    context.save();
    context.font = "11px ui-monospace, monospace";
    context.textBaseline = "top";
    const fps = `${this._renderTimes.length} fps`;
    const pad = 4;
    const fpsWidth = context.measureText(fps).width;
    context.fillStyle = "rgba(0,0,0,0.55)";
    context.fillRect(w - fpsWidth - pad * 3, pad, fpsWidth + pad * 2, 17);
    context.fillStyle = "#fff";
    context.fillText(fps, w - fpsWidth - pad * 2, pad + 3);
    if([this.original, this.result].some(source => source && source.failed)){
      const failLabel = "decode error";
      const failWidth = context.measureText(failLabel).width;
      context.fillStyle = "rgba(180,30,30,0.8)";
      context.fillRect(pad, 24 + pad, failWidth + pad * 2, 17);
      context.fillStyle = "#fff";
      context.fillText(failLabel, pad * 2, 24 + pad + 3);
    }
    if(this.approx){
      const label = "approx sync";
      const labelWidth = context.measureText(label).width;
      context.fillStyle = "rgba(180,60,0,0.75)";
      context.fillRect(pad, pad, labelWidth + pad * 2, 17);
      context.fillStyle = "#fff";
      context.fillText(label, pad * 2, pad + 3);
    }
    if([this.original, this.result].some(source => source && source.kind === "image" && source.staticOnly)){
      const label = "gif shown static (no ImageDecoder)";
      const labelWidth = context.measureText(label).width;
      context.fillStyle = "rgba(180,60,0,0.75)";
      context.fillRect(pad, pad, labelWidth + pad * 2, 17);
      context.fillStyle = "#fff";
      context.fillText(label, pad * 2, pad + 3);
    }
    context.restore();
  }

  _drawOriginal(context, rect){
    if(!this.original || !rect) return;
    context.save();
    if(this.filter) context.filter = this.filter;
    this.original.draw(context, rect);
    context.restore();
  }

  _drawCropWindow(context, base, canvasBox){
    const size = this.original && this.original.size.w ? this.original.size : null;
    const region = size && this.aspect ? cropRegion(size, this._cropRatio(), this._cropSnap()) : null;
    if(!region) return;
    const rect = {x: base.x + region.x * base.w, y: base.y + region.y * base.h, w: region.w * base.w, h: region.h * base.h};
    context.save();
    context.fillStyle = "rgba(0,0,0,0.45)";
    context.beginPath();
    context.rect(canvasBox.x - 1e6, canvasBox.y - 1e6, canvasBox.w + 2e6, canvasBox.h + 2e6);
    context.rect(rect.x, rect.y, rect.w, rect.h);
    context.fill("evenodd");
    context.strokeStyle = "rgba(255,255,255,0.85)";
    context.setLineDash([6, 4]);
    context.lineWidth = 1.5 / this.zoom.scale;
    context.strokeRect(rect.x, rect.y, rect.w, rect.h);
    context.restore();
  }

  _drawDivider(context, x, h){
    context.save();
    context.strokeStyle = "rgba(0,0,0,0.6)";
    context.lineWidth = 3.5;
    context.beginPath();
    context.moveTo(x, 0);
    context.lineTo(x, h);
    context.stroke();
    context.strokeStyle = "rgba(255,255,255,0.95)";
    context.lineWidth = 1.5;
    context.beginPath();
    context.moveTo(x, 0);
    context.lineTo(x, h);
    context.stroke();
    context.fillStyle = "rgba(255,255,255,0.95)";
    context.strokeStyle = "rgba(0,0,0,0.6)";
    context.lineWidth = 2;
    context.beginPath();
    context.arc(x, h / 2, 6, 0, Math.PI * 2);
    context.fill();
    context.stroke();
    context.restore();
  }

  zoomAt(cx, cy, factor){
    const next = Math.min(16, Math.max(1, this.zoom.scale * factor));
    const ratio = next / this.zoom.scale;
    this.zoom.x = cx - (cx - this.zoom.x) * ratio;
    this.zoom.y = cy - (cy - this.zoom.y) * ratio;
    this.zoom.scale = next;
    if(next === 1){ this.zoom.x = 0; this.zoom.y = 0; }
    this.render();
  }

  _local(event){
    const box = this.canvas.getBoundingClientRect();
    return {x: event.clientX - box.left, y: event.clientY - box.top, w: box.width, h: box.height};
  }

  _bindPointers(){
    const canvas = this.canvas;
    canvas.style.touchAction = "none";
    canvas.onwheel = event => {
      event.preventDefault();
      const point = this._local(event);
      this.zoomAt(point.x, point.y, event.deltaY < 0 ? 1.2 : 1 / 1.2);
    };
    canvas.ondblclick = () => {this.zoom = {scale: 1, x: 0, y: 0}; this.render();};
    canvas.onpointerdown = event => {
      const point = this._local(event);
      const onDivider = this.view === "split" && this.original && this.result && Math.abs(point.x - point.w * this.divider) <= DIVIDER_GRAB;
      this.dragging = onDivider ? {divider: true} : {pan: true, x: event.clientX - this.zoom.x, y: event.clientY - this.zoom.y};
      if(canvas.setPointerCapture) canvas.setPointerCapture(event.pointerId);
    };
    canvas.onpointermove = event => {
      if(!this.dragging){
        const point = this._local(event);
        const onDivider = this.view === "split" && this.original && this.result && Math.abs(point.x - point.w * this.divider) <= DIVIDER_GRAB;
        canvas.style.cursor = onDivider ? "ew-resize" : "grab";
        return;
      }
      if(this.dragging.divider){
        const point = this._local(event);
        this.divider = Math.min(1, Math.max(0, point.x / point.w));
      } else {
        this.zoom.x = event.clientX - this.dragging.x;
        this.zoom.y = event.clientY - this.dragging.y;
      }
      this.render();
    };
    canvas.onpointerup = () => this.dragging = null;
  }

  destroy(){
    this.destroyed = true;
    this.playing = false;
    [this.original, this.result].filter(Boolean).forEach(source => {
      if(source.destroy) source.destroy();
      else if(source.pause) source.pause();
    });
    this.canvas.onwheel = this.canvas.onpointerdown = this.canvas.onpointermove = this.canvas.onpointerup = this.canvas.ondblclick = null;
    this.original = this.result = null;
  }
}
