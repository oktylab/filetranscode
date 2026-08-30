const fs = require("fs");
const path = require("path");
global.performance = {now: () => Date.now()};
let rafQueue = [];
global.requestAnimationFrame = fn => rafQueue.push(fn);
global.window = global;
global.document = {createElement: () => ({addEventListener: () => {}, style: {}})};

// faithful-enough VideoDecoder: consumes chunks async, emits frames in presentation order
class FakeVideoDecoder{
  constructor({output, error}){ this.output = output; this.state = "unconfigured"; this._held = []; this.decodeQueueSize = 0; }
  static async isConfigSupported(){ return {supported: true}; }
  configure(){ this.state = "configured"; }
  decode(chunk){
    this.decodeQueueSize++;
    setImmediate(() => {
      this.decodeQueueSize--;
      this._held.push({timestamp: chunk.timestamp, duration: chunk.duration, displayWidth: 100, displayHeight: 100, close(){}});
      this._held.sort((a, b) => a.timestamp - b.timestamp);
      while(this._held.length > 4) this.output(this._held.shift());
    });
  }
  async flush(){ await new Promise(r => setImmediate(r)); this._held.sort((a,b)=>a.timestamp-b.timestamp).forEach(f => this.output(f)); this._held = []; }
  reset(){ this._held = []; this.state = "unconfigured"; this.decodeQueueSize = 0; }
  close(){ this.state = "closed"; }
}
global.VideoDecoder = FakeVideoDecoder;
global.EncodedVideoChunk = class { constructor(o){ Object.assign(this, o); } };

const read = f => fs.readFileSync(path.join(__dirname, f), "utf8");
eval(fs.readFileSync(path.join(__dirname, "../../src/filetranscode/builtin/toolkit/web/static/mp4demux.js"), "utf8") + "\nglobal.demuxMp4 = demuxMp4;");
eval(fs.readFileSync(path.join(__dirname, "../../src/filetranscode/builtin/toolkit/web/static/player.js"), "utf8") + "\nglobal.Comparator = Comparator; global.DecodedVideoSource = DecodedVideoSource;");

(async () => {
  for(const file of ["/home/crosspost/Downloads/test.mp4", "/home/crosspost/Downloads/16376174_1920_1080_25fps.mp4"]){
    const raw = fs.readFileSync(file);
    global.fetch = async () => ({arrayBuffer: async () => raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength)});
    const source = new DecodedVideoSource(file);
    await source.ready;
    if(source.failed){ console.log(`${path.basename(file)}: INIT FAILED`); continue; }
    const canvas = {getContext: () => null, style: {}, getBoundingClientRect: () => ({left: 0, top: 0, width: 10, height: 10})};
    const comparator = new Comparator(canvas, {original: source});
    await comparator.ready;
    comparator.play();
    const spin = async () => { const q = rafQueue; rafQueue = []; q.forEach(fn => fn()); await new Promise(r => setImmediate(r)); };
    let ticks = 0, lastClock = -1, stalls = 0, maxStall = 0, stall = 0;
    while(comparator.playing && ticks < 500000){
      await spin();
      if(comparator.clock === lastClock){ stall++; maxStall = Math.max(maxStall, stall); if(stall === 1) stalls++; }
      else stall = 0;
      lastClock = comparator.clock;
      ticks++;
    }
    if(!(!comparator.playing)){
      const next = source.nextTime(comparator.clock);
      const usec = next * 1e6;
      console.log(`  STALL: clock=${comparator.clock} next=${next} frames=${source._frames.length} feed=${source._feed}/${source.track.samples.length} queue=${source._decoder.decodeQueueSize} current.ts=${source._current && source._current.timestamp} target=${source._targetTimestamp(usec)} flushed=${source._flushed} ended=${source.ended} frames0.ts=${source._frames[0] && source._frames[0].timestamp}`);
    }
    const reached = comparator.clock;
    console.log(`${path.basename(file)}: played to ${reached.toFixed(2)}/${source.duration.toFixed(2)}s in ${ticks} ticks, stalls=${stalls}, worst stall=${maxStall} ticks, finished=${!comparator.playing}`);
    comparator.seek(source.duration / 2);
    await spin(); await spin();
    console.log(`  seek to middle presents a frame: ${source._current !== null}`);
    comparator.destroy();
  }
  process.exit(0);
})();
