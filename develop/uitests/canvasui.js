const { JSDOM } = require("jsdom");
const BASE = "http://127.0.0.1:" + (process.env.PORT || "8799");

function fakeContext(){
  const calls = [];
  const record = name => (...args) => calls.push([name, ...args]);
  return {calls, context: new Proxy({}, {
    get(target, prop){
      if(prop === "calls") return calls;
      return record(String(prop));
    },
    set(){ return true; },
  })};
}

(async () => {
  const html = await (await fetch(`${BASE}/video/export`)).text();
  const dom = new JSDOM(html, { runScripts: "outside-only", url: `${BASE}/video/export`, pretendToBeVisual: true });
  const { window } = dom;
  window.fetch = () => Promise.resolve({ok: false});
  window.URL.createObjectURL = () => "blob:x"; window.URL.revokeObjectURL = () => {};
  const fake = fakeContext();
  window.HTMLCanvasElement.prototype.getContext = () => fake.context;
  const realCreateElement = window.document.createElement.bind(window.document);
  window.document.createElement = tag => {
    const el = realCreateElement(tag);
    if(tag === "video") setTimeout(() => el.dispatchEvent(new window.Event("loadedmetadata")), 0);
    return el;
  };
  const scripts = [
    await (await fetch(`${BASE}/static/player.js?p=1`)).text(),
    await (await fetch(`${BASE}/static/app.js?p=1`)).text(),
    ...[...window.document.querySelectorAll("script:not([src])")].map(s => s.textContent),
  ];
  window.eval(scripts.join("\n;\n"));
  const doc = window.document, form = doc.getElementById("op");

  window.showStage("video", "blob:out", "blob:orig", "video");
  const comparator = window.comparator;
  await comparator.ready;
  console.log("comparator built:", !!comparator, "| master is result:", comparator.master === comparator.result);
  console.log("no WebCodecs here -> honest approx fallback:", comparator.approx === true);
  console.log("slave muted, master audible:", comparator.slave.element.muted === true && comparator.master.element.muted === false);
  Object.defineProperties(comparator.original.element, {videoWidth: {value: 1600}, videoHeight: {value: 900}});
  Object.defineProperties(comparator.result.element, {videoWidth: {value: 506}, videoHeight: {value: 900}});
  comparator.canvas.width = 800; comparator.canvas.height = 450;
  window.devicePixelRatio = 1;

  form.querySelectorAll(".aspects .ratio").forEach(b => {if(b.dataset.value === "9:16") b.onclick();});
  console.log("aspect reaches comparator:", Math.abs(comparator.aspect - 0.5625) < 1e-9);
  const plan = comparator.layout();
  const round = r => r && [Math.round(r.x), Math.round(r.y), Math.round(r.w), Math.round(r.h)].join(",");
  console.log("split: result pinned to crop region:", round(plan.result), "(expect ~273,0,253,450)");
  console.log("crop rect == result rect:", round(plan.crop) === round(plan.result));

  comparator.setView("side");
  const side = comparator.layout();
  console.log("side: two boxes, crop overlay only on original:", side.mode === "side" && side.crop === null && round(side.original) !== round(side.result));
  comparator.setView("split");

  fake.calls.length = 0;
  comparator.render();
  const names = fake.calls.map(c => c[0]);
  console.log("render draws: clip for divider:", names.includes("clip"), "| evenodd dim fill:", fake.calls.some(c => c[0] === "fill" && c[1] === "evenodd"), "| dashed window:", names.includes("setLineDash"), "| divider line:", names.includes("moveTo"));
  const texts = fake.calls.filter(c => c[0] === "fillText").map(c => String(c[1]));
  console.log("fps counter drawn:", texts.some(t => t.endsWith("fps")), "| approx label drawn:", texts.includes("approx sync"));

  comparator.zoomAt(400, 225, 1.2);
  console.log("cursor-anchored zoom:", comparator.zoom.scale.toFixed(2) === "1.20" && Math.round(comparator.zoom.x) === -80);
  comparator.canvas.getBoundingClientRect = () => ({left: 0, top: 0, width: 800, height: 450});
  comparator.canvas.onpointerdown({clientX: 400, clientY: 10, pointerId: 1});
  console.log("pointer near divider grabs divider:", comparator.dragging && comparator.dragging.divider === true);
  comparator.canvas.onpointermove({clientX: 600, clientY: 10});
  console.log("divider drags to 75%:", Math.abs(comparator.divider - 0.75) < 0.01);
  comparator.canvas.onpointerup();
  comparator.canvas.onpointerdown({clientX: 100, clientY: 10, pointerId: 1});
  console.log("pointer away from divider pans:", comparator.dragging && comparator.dragging.pan === true);
  comparator.canvas.onpointerup();
  comparator.canvas.ondblclick();
  console.log("dblclick resets zoom:", comparator.zoom.scale === 1 && comparator.zoom.x === 0);

  form.querySelectorAll("[data-css]").forEach(c => {if(c.dataset.css.startsWith("saturate")){c.value = "1.5"; c.dispatchEvent(new window.Event("input", {bubbles: true}));}});
  console.log("live filter reaches comparator:", comparator.filter.includes("saturate(1.5)"));

  window.previewOriginal("image", "blob:img");
  console.log("image-only preview works:", window.comparator.original.kind === "image" && window.comparator.result === null);
  console.log("transport hidden for image:", doc.getElementById("transport").hidden === true);
  process.exit(0);
})();