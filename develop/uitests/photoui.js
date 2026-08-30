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

let failures = 0;
function check(name, ok, detail){
  console.log((ok ? "ok " : "FAIL ") + name + (detail ? ` — ${detail}` : ""));
  if(!ok) failures += 1;
}

(async () => {
  const html = await (await fetch(`${BASE}/photo/export`)).text();
  const dom = new JSDOM(html, { runScripts: "outside-only", url: `${BASE}/photo/export`, pretendToBeVisual: true });
  const { window } = dom;
  window.fetch = () => Promise.resolve({ok: false});
  window.URL.createObjectURL = () => "blob:x"; window.URL.revokeObjectURL = () => {};
  const fake = fakeContext();
  window.HTMLCanvasElement.prototype.getContext = () => fake.context;
  Object.defineProperty(window.HTMLImageElement.prototype, "src", {
    get(){ return "blob:x"; },
    set(value){ setTimeout(() => this.dispatchEvent(new window.Event("load")), 0); },
  });
  const scripts = [
    await (await fetch(`${BASE}/static/player.js?p=1`)).text(),
    await (await fetch(`${BASE}/static/app.js?p=1`)).text(),
    ...[...window.document.querySelectorAll("script:not([src])")].map(s => s.textContent),
  ];
  window.eval(scripts.join("\n;\n"));
  const doc = window.document, form = doc.getElementById("op");

  check("form is image media", form.dataset.media === "image", form.dataset.media);
  check("no trim sliders on photo page", !form.querySelector('[name="edits_trim_start"]'));
  check("no speed slider on photo page", !form.querySelector('[name="edits_speed"]'));
  check("dual width slider present", Boolean(form.querySelector('[name="photo_constraints_min_width"][data-dual-low]')));

  window.showStage("image", "blob:out", "blob:orig", "image");
  const comparator = window.comparator;
  await comparator.ready;
  check("comparator built for images", Boolean(comparator));
  check("image sources used", comparator.original.kind === "image" && comparator.result.kind === "image");
  check("no approx label for images", comparator.approx === false);
  check("transport hidden for images", doc.getElementById("transport").hidden === true);

  Object.defineProperties(comparator.original.element, {naturalWidth: {value: 1201}, naturalHeight: {value: 900}});
  Object.defineProperties(comparator.result.element, {naturalWidth: {value: 900}, naturalHeight: {value: 900}});
  comparator.canvas.width = 800; comparator.canvas.height = 450;
  window.devicePixelRatio = 1;

  form.querySelectorAll(".aspects .ratio").forEach(b => {if(b.dataset.value === "1:1") b.onclick();});
  check("aspect reaches comparator", Math.abs(comparator.aspect - 1) < 1e-9, String(comparator.aspect));

  const plan = comparator.layout();
  const round = r => r && [Math.round(r.x), Math.round(r.y), Math.round(r.w), Math.round(r.h)].join(",");
  check("split: crop overlay present", plan.crop !== null);
  check("split: result pinned to crop rect", round(plan.crop) === round(plan.result), `${round(plan.crop)} vs ${round(plan.result)}`);
  const overlayWidth = plan.crop.w / plan.original.w * 1201;
  check("pixel snap (900px window on 1201 source)", Math.abs(overlayWidth - 900) < 0.6, overlayWidth.toFixed(2));

  const saturation = form.querySelector('[name="filters_saturation"]');
  saturation.value = "1.5";
  saturation.dispatchEvent(new window.Event("input", {bubbles: true}));
  saturation.dispatchEvent(new window.Event("change", {bubbles: true}));
  check("filters css reaches comparator", comparator.filter.includes("saturate(1.5)"), comparator.filter);

  comparator.setView("side");
  const side = comparator.layout();
  check("side view has both boxes", side.mode === "side" && Boolean(side.original) && Boolean(side.result));

  check("still checkbox present", Boolean(form.querySelector('input[name="edits_still"]')));
  const primaries = [...form.querySelectorAll(".field")].map(f => f.querySelector("[name]")).filter(Boolean).map(el => el.name);
  check("engine right after preset, ungrouped", primaries.indexOf("engine") === primaries.indexOf("preset") + 1,
        primaries.slice(0, 4).join(","));
  check("engine not inside a fieldset group", !form.querySelector("fieldset [name='engine']"));

  comparator._checker = null;
  fake.calls.length = 0;
  comparator.render();
  const called = fake.calls.map(call => call[0]);
  check("checkerboard pattern drawn", called.includes("createPattern") && called.includes("fillRect"));

  check("gif sniff", window.eval('sniffImageMime(new Uint8Array([0x47,0x49,0x46,0x38,0x39,0x61]))') === "image/gif");
  check("webp sniff", window.eval('sniffImageMime(new Uint8Array([0x52,0x49,0x46,0x46,0,0,0,0,0x57,0x45,0x42,0x50]))') === "image/webp");
  check("png sniff", window.eval('sniffImageMime(new Uint8Array([0x89,0x50,0x4E,0x47,0,0]))') === "image/png");
  check("jpeg sniff is null", window.eval('sniffImageMime(new Uint8Array([0xFF,0xD8,0xFF,0xE0]))') === null);
  const picks = window.eval('[0, 150, 250, 550, 650].map(t => animationFrameIndex([100, 200, 300], 600, t))');
  check("frame index math", JSON.stringify(picks) === "[0,1,1,2,0]", JSON.stringify(picks));

  check("no ImageDecoder here -> static fallback, not fake animation", comparator.original.animated === false);

  const fakeFrame = () => ({displayWidth: 300, displayHeight: 225, close(){}});
  for(const source of [comparator.original, comparator.result]){
    source.frames = [fakeFrame(), fakeFrame(), fakeFrame()];
    source.durations = [200, 200, 200];
    source.totalMs = 600;
    source.animated = true;
  }
  check("animated master is result", comparator.master === comparator.result);
  check("animated duration from frames", Math.abs(comparator.duration - 0.6) < 1e-9, String(comparator.duration));
  check("markers are frame starts", JSON.stringify(comparator.markers()) === "[0,0.2,0.4]", JSON.stringify(comparator.markers()));

  comparator.playing = true;
  comparator._imageLast = window.performance.now() - 50;
  comparator.clock = 0;
  comparator._loop();
  const advanced = comparator.clock;
  check("play advances shared clock", advanced > 0.03, String(advanced));
  check("both sources on the shared clock", comparator.original.time === advanced && comparator.result.time === advanced,
        `${comparator.original.time} vs ${comparator.result.time}`);
  comparator.clock = 0.59;
  comparator._imageLast = window.performance.now() - 50;
  comparator._loop();
  check("clock wraps at duration (loops)", comparator.clock < 0.6, String(comparator.clock));
  comparator.pause();
  const held = comparator.clock;
  comparator._loop();
  check("pause holds the clock", comparator.clock === held);
  comparator.seek(0.2);
  check("seek drives both sources", comparator.original.time === 0.2 && comparator.result.time === 0.2);

  window.eval('initTransport("image")');
  await new Promise(resolve => setTimeout(resolve, 10));
  check("transport shown for animated image", doc.getElementById("transport").hidden === false);
  const strip = doc.getElementById("tp-markers");
  check("marker strip has 3 stop points", strip.hidden === false && strip.children.length === 3, String(strip.children.length));
  strip.children[1].onclick();
  check("clicking a marker seeks to its frame", comparator.time === 0.2, String(comparator.time));
  const tpSeek = doc.getElementById("tp-seek");
  tpSeek.value = "700";
  tpSeek.oninput();
  check("dragging snaps to nearest frame start", comparator.time === 0.4, String(comparator.time));
  for(const source of [comparator.original, comparator.result]){
    source.animated = false; source.frames = [];
  }
  comparator.original.staticOnly = true;
  fake.calls.length = 0;
  comparator.render();
  const staticLabel = fake.calls.some(call => call[0] === "fillText" && String(call[1]).includes("static"));
  check("static-gif label drawn when decoder missing", staticLabel);

  const saturation2 = form.querySelector('[name="filters_saturation"]');
  saturation2.value = "2.5";
  saturation2.dataset.dirty = "1";
  const aspectHidden = form.querySelector('.aspects input[type="hidden"]');
  aspectHidden.value = "9:16";
  const chipsHidden = form.querySelector('input[type="hidden"][name="photo_constraints_formats"]');
  chipsHidden.value = "webp gif";
  window.eval('resetFormState(document.getElementById("op"))');
  check("reload reset clears restored slider", saturation2.value === saturation2.defaultValue && !saturation2.dataset.dirty, saturation2.value);
  check("reload reset clears restored aspect", aspectHidden.value === "" && form.querySelector('.aspects .ratio[data-value=""]').classList.contains("on"));
  check("reload reset clears restored chips", chipsHidden.value === "");
  check("form blocks browser autofill", form.getAttribute("autocomplete") === "off");

  doc.getElementById("status").textContent = "delivered: old stuff";
  doc.getElementById("viewbar").hidden = false;
  const uploadInput = form.querySelector('input[type="file"]');
  Object.defineProperty(uploadInput, "files", {value: [{name: "next.png", type: "image/png"}], configurable: true});
  uploadInput.dispatchEvent(new window.Event("change", {bubbles: true}));
  check("new file clears old status", doc.getElementById("status").textContent === "");
  check("new file hides stale viewbar", doc.getElementById("viewbar").hidden === true);

  const view = window.eval('renderJson({a: {b: {c: 1}}, list: [1, 2, {d: 3}]})');
  doc.body.append(view);
  const toggle = view.querySelector(".j-toggle-all");
  check("json toggle-all button present", Boolean(toggle));
  const folded = () => view.querySelectorAll(".j-fold").length;
  const startFolds = folded();
  check("deep nodes folded by default", startFolds > 0, String(startFolds));
  toggle.onclick();
  check("first click expands everything", folded() === 0, String(folded()));
  check("icon flips to collapse glyph", toggle.textContent === "⊟");
  toggle.onclick();
  check("second click collapses all but root", folded() > 0 && !view.querySelector(".j-row > span.j-fold ~ *") !== null && folded() >= startFolds, String(folded()));
  const rootWrap = view.querySelector(":scope > .j-row > span");
  check("root stays open on collapse-all", !rootWrap.classList.contains("j-fold"));
  toggle.onclick();
  check("toggle cycles back to expanded", folded() === 0);

  console.log(failures ? `${failures} FAILURES` : "all photoui checks passed");
  process.exit(failures ? 1 : 0);
})().catch(error => { console.error("photoui crashed:", error); process.exit(1); });
