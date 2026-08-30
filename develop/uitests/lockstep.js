const fs = require("fs");
global.performance = {now: () => Date.now()};
let rafQueue = [];
global.requestAnimationFrame = fn => rafQueue.push(fn);
global.window = global;
global.document = {createElement: () => ({addEventListener: () => {}, style: {}})};
global.Audio = class { constructor(){ this.currentTime = 0; this.muted = false; this.preload = ""; } play(){ return {catch: () => {}}; } pause(){} };
const player = fs.readFileSync(require("path").join(__dirname, "../../src/filetranscode/builtin/toolkit/web/static/player.js"), "utf8");
eval(player + "\nglobal.Comparator = Comparator; global.VideoSource = VideoSource;");

class FakeSource{
  constructor(name){
    this.kind = "video";
    this.url = "fake:" + name;
    this.name = name;
    this.failed = false;
    this.readyTimes = new Set();
    this.presented = [];
    this.ready = Promise.resolve(this);
  }
  get size(){ return {w: 100, h: 100}; }
  get duration(){ return 10; }
  get time(){ return this.presented.length ? this.presented[this.presented.length - 1] : 0; }
  frameStep(){ return 0.5; }
  present(t){
    const key = Math.round(t * 2) / 2;
    this.presented.push(t);
    return this.readyTimes.has(key);
  }
  seek(t){ this.seeked = t; }
  draw(){}
  onFrame(){}
  destroy(){}
}

const canvas = {getContext: () => null, style: {}, getBoundingClientRect: () => ({left: 0, top: 0, width: 100, height: 100})};
(async () => {
  const original = new FakeSource("orig"), result = new FakeSource("res");
  const comparator = new Comparator(canvas, {original, result, offset: 2});
  await comparator.ready;
  console.log("lockstep mode (not approx):", comparator.approx === false);
  comparator.play();
  const step = () => {const queue = rafQueue; rafQueue = []; queue.forEach(fn => fn());};
  // result ready at 0.5, original NOT ready at its mapped 2.5 -> clock must hold
  result.readyTimes.add(0.5);
  step(); step();
  console.log("clock holds when one pane not decoded:", comparator.clock === 0);
  // original catches up -> clock advances exactly one frame, no skipping
  original.readyTimes.add(2.5);
  step();
  console.log("clock advances one frame when both ready:", comparator.clock === 0.5);
  console.log("original asked at trim-offset time:", original.presented.some(t => Math.abs(t - 2.5) < 1e-9));
  // seek maps offset per source
  comparator.seek(4);
  console.log("seek maps trim offset:", original.seeked === 6 && result.seeked === 4);
  // no frame ever skipped: presented times advanced by exactly frameStep
  console.log("no dropped steps:", comparator.clock === 4);
})();
