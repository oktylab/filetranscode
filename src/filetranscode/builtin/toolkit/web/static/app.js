const blobSlots = {};
function blobFor(slot, source){
  if(blobSlots[slot]) URL.revokeObjectURL(blobSlots[slot]);
  return blobSlots[slot] = URL.createObjectURL(source);
}
const applyLiveOf = new WeakMap();
let transportFrame = null;

function renderJson(value, changed, path){
  const touched = p => changed && (changed.has(p) || [...changed].some(c => c.startsWith(p + ".")));
  const leaf = p => changed && changed.has(p);
  const foldable = value => value !== null && typeof value === "object" &&
    (Array.isArray(value) ? value.length : Object.keys(value).length) > 0;
  const armCopy = (row, child, text) => {
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "j-copy";
    copy.textContent = "⧉";
    copy.onclick = event => {
      event.stopPropagation();
      navigator.clipboard.writeText(text);
      copy.textContent = "✓";
      setTimeout(() => copy.textContent = "⧉", 900);
    };
    const block = child.querySelector(":scope>.j-block");
    block ? child.insertBefore(copy, block) : row.appendChild(copy);
  };
  const armRow = (row, target) => {
    row.classList.add("j-can");
    row.onclick = event => {
      if(event.target.closest(".j-row") !== row) return;
      event.stopPropagation();
      target.classList.toggle("j-fold");
    };
  };
  const build = (value, path, depth) => {
    if(value === null || typeof value !== "object"){
      const span = document.createElement("span");
      span.className = value === null ? "j-null" : typeof value === "string" ? "j-str" : typeof value === "boolean" ? "j-bool" : "j-num";
      span.textContent = JSON.stringify(value);
      if(leaf(path)) span.classList.add("j-hl");
      return span;
    }
    const isArray = Array.isArray(value);
    const entries = isArray ? value.map((item, index) => [String(index), item]) : Object.entries(value);
    const wrap = document.createElement("span");
    if(entries.length && depth >= 1 && !touched(path)) wrap.classList.add("j-fold");
    const open = document.createElement("span");
    open.className = "j-p";
    open.textContent = isArray ? "[" : "{";
    wrap.appendChild(open);
    if(entries.length){
      const caret = document.createElement("span");
      caret.className = "j-caret";
      caret.textContent = "\u25be";
      wrap.appendChild(caret);
      const dots = document.createElement("span");
      dots.className = "j-dots";
      dots.textContent = "…";
      wrap.appendChild(dots);
      const block = document.createElement("div");
      block.className = "j-block";
      entries.forEach(([key, item]) => {
        const childPath = path ? `${path}.${key}` : key;
        const row = document.createElement("div");
        row.className = "j-row";
        const child = build(item, childPath, depth + 1);
        if(foldable(item)) armRow(row, child);
        if(!isArray){
          const keySpan = document.createElement("span");
          keySpan.className = touched(childPath) ? "j-key j-touch" : "j-key";
          keySpan.textContent = JSON.stringify(key);
          const colon = document.createElement("span");
          colon.className = "j-p";
          colon.textContent = ": ";
          row.append(keySpan, colon);
        }
        row.appendChild(child);
        armCopy(row, child, (isArray ? "" : JSON.stringify(key) + ": ") + JSON.stringify(item, null, 2));
        block.appendChild(row);
      });
      wrap.appendChild(block);
    }
    const close = document.createElement("span");
    close.className = "j-p";
    close.textContent = isArray ? "]" : "}";
    wrap.appendChild(close);
    return wrap;
  };
  const root = document.createElement("div");
  root.className = "jsonview";
  const rootEl = build(value, path || "", 0);
  const rootRow = document.createElement("div");
  rootRow.className = "j-row";
  if(foldable(value)) armRow(rootRow, rootEl);
  rootRow.appendChild(rootEl);
  armCopy(rootRow, rootEl, JSON.stringify(value, null, 2));
  if(foldable(value)){
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "j-toggle-all";
    toggle.title = "expand / collapse all";
    toggle.textContent = "⊟";
    toggle.onclick = () => {
      const wraps = [...root.querySelectorAll(".j-caret")].map(caret => caret.parentElement);
      const anyFolded = wraps.some(wrap => wrap.classList.contains("j-fold"));
      wraps.forEach(wrap => wrap.classList.toggle("j-fold", !anyFolded && wrap !== rootEl));
      toggle.textContent = anyFolded ? "⊟" : "⊞";
    };
    root.appendChild(toggle);
  }
  root.appendChild(rootRow);
  return root;
}

function parseAspect(text){
  if(!text) return null;
  const [w, h] = String(text).split(":").map(Number);
  const ratio = h ? w / h : Number(text);
  return Number.isFinite(ratio) && ratio > 0 ? ratio : null;
}

function aspectValue(){
  const hidden = document.querySelector('#op .aspects input[type="hidden"]');
  return hidden ? hidden.value : "";
}

function initAspects(form){
  form.querySelectorAll(".aspects").forEach(box => {
    const hidden = box.querySelector('input[type="hidden"]');
    const free = box.querySelector(".ratio-free");
    const select = value => {
      hidden.value = value;
      box.querySelectorAll(".ratio").forEach(button => button.classList.toggle("on", button.dataset.value === value));
      if(free && value !== free.value) free.value = "";
      hidden.dispatchEvent(new Event("change", {bubbles: true}));
    };
    box.querySelectorAll(".ratio").forEach(button => button.onclick = () => select(button.dataset.value));
    if(free) free.addEventListener("input", () => {
      hidden.value = free.value.trim();
      box.querySelectorAll(".ratio").forEach(button => button.classList.toggle("on", false));
      hidden.dispatchEvent(new Event("change", {bubbles: true}));
    });
  });
}

function fitTrimRange(form, file){
  const start = form.querySelector('[name="edits_trim_start"]');
  const end = form.querySelector('[name="edits_trim_end"]');
  if(!start || !end || !file.type.startsWith("video")) return;
  const probe = document.createElement("video");
  probe.preload = "metadata";
  probe.onloadedmetadata = () => {
    const max = Math.floor(probe.duration * 10) / 10;
    if(!Number.isFinite(max) || !max) return;
    const dirty = [start.dataset.dirty, end.dataset.dirty];
    [start, end].forEach(range => {
      range.max = max;
      if(Number(range.value) > max) range.value = max;
      range.dispatchEvent(new Event("input", {bubbles: true}));
    });
    if(!dirty[0]) delete start.dataset.dirty;
    if(!dirty[1]) delete end.dataset.dirty;
  };
  probe.src = blobFor("trim-probe", file);
}

function short(value){
  const n = Number(value);
  if(Math.abs(n) >= 1e6) return (n / 1e6) + "M";
  if(Math.abs(n) >= 1e4) return (n / 1e3) + "k";
  return String(value);
}

function resetFormState(form){
  form.reset();
  form.querySelectorAll("input[data-range]").forEach(range => {
    delete range.dataset.dirty;
    range.value = range.defaultValue;
    const out = form.querySelector(`output[data-for="${range.name}"]`);
    if(out) out.textContent = short(range.value);
  });
  form.querySelectorAll(".dual").forEach(dual => {
    const low = dual.querySelector("[data-dual-low]");
    const out = form.querySelector(`output[data-dual="${low.name}"]`);
    if(out) out.textContent = "any";
  });
  form.querySelectorAll(".aspects").forEach(box => {
    const hidden = box.querySelector('input[type="hidden"]');
    hidden.value = "";
    box.querySelectorAll(".ratio").forEach(button => button.classList.toggle("on", button.dataset.value === ""));
    const free = box.querySelector(".ratio-free");
    if(free) free.value = "";
  });
  form.querySelectorAll("[data-chips]").forEach(chips => {
    const hidden = form.querySelector(`input[type="hidden"][name="${CSS.escape(chips.dataset.chips)}"]`);
    hidden.value = "";
    chips.querySelectorAll('input[type="checkbox"]').forEach(box => box.checked = false);
  });
}

function initForm(form){
  resetFormState(form);
  window.addEventListener("pageshow", event => {
    if(event.persisted) resetFormState(form);
  });
  initAspects(form);
  form.querySelectorAll("input[data-range]:not([data-dual-low]):not([data-dual-high])").forEach(range => {
    const out = form.querySelector(`output[data-for="${range.name}"]`);
    range.addEventListener("input", () => {range.dataset.dirty = "1"; if(out) out.textContent = short(range.value);});
  });
  form.querySelectorAll(".dual").forEach(dual => {
    const low = dual.querySelector("[data-dual-low]"), high = dual.querySelector("[data-dual-high]");
    const out = form.querySelector(`output[data-dual="${low.name}"]`);
    const sync = () => {
      if(Number(low.value) > Number(high.value)) [low.value, high.value] = [high.value, low.value];
      if(out) out.textContent = short(low.value) + " – " + short(high.value);
    };
    [low, high].forEach(range => range.addEventListener("input", () => {low.dataset.dirty = high.dataset.dirty = "1"; sync();}));
  });
  form.querySelectorAll("[data-output-toggle]").forEach(toggle => {
    const input = toggle.parentElement.querySelector("input");
    toggle.addEventListener("change", () => input.disabled = toggle.value === "");
  });
  form.querySelectorAll("[data-chips]").forEach(chips => {
    const hidden = form.querySelector(`input[type="hidden"][name="${CSS.escape(chips.dataset.chips)}"]`);
    chips.addEventListener("change", event => {
      const box = event.target;
      const picked = (hidden.value ? hidden.value.split(" ") : []).filter(value => value !== box.value);
      hidden.value = (box.checked ? [...picked, box.value] : picked).join(" ");
    });
  });
  const cssControls = [...form.querySelectorAll("[data-css]")];
  if(cssControls.length){
    const applyLive = () => {
      const filter = liveFilterCss();
      if(comparator) comparator.setFilter(filter);
      document.querySelectorAll("#inputs-grid .tile > :first-child").forEach(el => el.style.filter = filter);
    };
    cssControls.forEach(control => control.addEventListener("input", applyLive));
    applyLiveOf.set(form, applyLive);
  }
  const preset = form.querySelector('select[name="preset"]');
  if(preset) preset.addEventListener("change", () => applyPreset(form, preset.value));
  form.querySelectorAll("[data-source]").forEach(source => {
    const toggle = source.querySelector("[data-source-toggle]");
    const zone = source.querySelector(".dropzone");
    const file = zone.querySelector('input[type="file"]');
    const names = zone.querySelector(".drop-names");
    const reference = source.querySelector(".source-ref");
    const update = () => {
      const upload = toggle.value === "upload";
      zone.hidden = !upload;
      file.disabled = !upload;
      reference.hidden = upload;
      reference.disabled = upload;
    };
    const show = () => names.textContent = [...file.files].map(item => item.name).join(", ");
    toggle.addEventListener("change", update);
    file.addEventListener("change", show);
    zone.addEventListener("dragover", event => {event.preventDefault(); zone.classList.add("over");});
    zone.addEventListener("dragleave", () => zone.classList.remove("over"));
    zone.addEventListener("drop", event => {event.preventDefault(); zone.classList.remove("over"); file.files = event.dataTransfer.files; file.dispatchEvent(new Event("change"));});
    update();
  });
}

async function post(form){
  const status = document.getElementById("status");
  const spin = document.getElementById("spin");
  status.textContent = "";
  if(spin) spin.hidden = false;
  const data = new FormData(form);
  form.querySelectorAll("input[data-range]").forEach(range => {if(!range.dataset.dirty) data.delete(range.name);});
  let response;
  try{
    response = await fetch(form.dataset.api, {method:"POST", body:data});
  }catch(error){
    if(spin) spin.hidden = true;
    status.textContent = String(error);
    return null;
  }
  if(spin) spin.hidden = true;
  if(!response.ok){
    status.textContent = await response.text();
    return null;
  }
  loadTrace(response);
  return response;
}

async function loadTrace(response){
  const url = response.headers.get("X-Trace");
  if(!url) return;
  const traceResponse = await fetch(url);
  if(!traceResponse.ok) return;
  const tree = await traceResponse.json();
  const panel = document.getElementById("tracer");
  if(!panel) return;
  document.getElementById("trace-detail").replaceChildren();
  document.getElementById("trace-tree").replaceChildren(...tree.children.map(child => stepBox(child)));
  panel.hidden = tree.children.length === 0;
}

function stepBox(step){
  const wrap = document.createElement("div");
  let fold = null;
  if(step.children.length){
    fold = document.createElement("button");
    fold.type = "button";
    fold.className = "fold";
    fold.textContent = "▾";
    fold.onclick = event => {event.stopPropagation(); wrap.classList.toggle("folded");};
  }
  if(step.label){
    const chip = document.createElement("span");
    chip.className = "key";
    chip.textContent = step.label;
    wrap.appendChild(chip);
  }
  const box = document.createElement("span");
  box.className = "node";
  const kind = document.createElement("b");
  kind.textContent = step.kind;
  box.appendChild(kind);
  if(step.took_ms >= 1){
    const ms = document.createElement("span");
    ms.className = "sub";
    ms.textContent = Math.round(step.took_ms) + "ms";
    box.appendChild(ms);
  }
  box.onclick = () => {
    document.querySelectorAll(".node.picked").forEach(el => el.classList.remove("picked"));
    box.classList.add("picked");
    const detail = document.getElementById("trace-detail");
    const parts = [renderJson(step.state, new Set(step.changed), "")];
    if(step.error){
      const err = document.createElement("div");
      err.className = "trace-error";
      err.textContent = step.error;
      parts.unshift(err);
    }
    detail.replaceChildren(...parts);
  };
  wrap.appendChild(box);
  if(fold) wrap.appendChild(fold);
  if(step.children.length){
    const kids = document.createElement("div");
    kids.className = "kids";
    step.children.forEach(child => kids.appendChild(stepBox(child)));
    wrap.appendChild(kids);
    wrap.classList.add("folded");
  }
  return wrap;
}

function formToJson(form){
  initForm(form);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const response = await post(form);
    if(!response) return;
    const out = document.getElementById("json");
    out.hidden = false;
    out.replaceChildren(renderJson(await response.json()));
  });
}

function mediaElement(kind, url){
  if(kind === "video"){const v = document.createElement("video"); v.src = url; v.muted = true; v.loop = true; v.preload = "auto"; return v;}
  if(kind === "image"){const i = document.createElement("img"); i.src = url; i.draggable = false; return i;}
  if(kind === "pdf"){const e = document.createElement("embed"); e.src = url; e.type = "application/pdf"; return e;}
  const a = document.createElement("a"); a.href = url; a.textContent = "download result"; a.download = "result"; return a;
}

function formToCompare(form){
  initForm(form);
  const kind = form.dataset.media;
  const multiple = Boolean(form.dataset.multiple);
  const multiout = Boolean(form.dataset.multiout);
  if(multiout) form.dataset.api += (form.dataset.api.includes("?") ? "&" : "?") + "parts=1";
  const upload = form.querySelector('input[type="file"]');
  if(upload){
    upload.addEventListener("change", () => {
      if(!upload.files.length) return;
      document.getElementById("status").textContent = "";
      const viewbar = document.getElementById("viewbar");
      if(viewbar) viewbar.hidden = true;
      const outputs = document.getElementById("outputs-grid");
      if(outputs){ outputs.hidden = true; outputs.replaceChildren(); }
      ["edits_trim_start", "edits_trim_end"].forEach(name => {
        const range = form.querySelector(`[name="${name}"]`);
        if(range){ delete range.dataset.dirty; range.value = range.defaultValue; }
      });
      if(multiple) previewInputs(upload.files, kind);
      else previewOriginal(kindOf(upload.files[0], kind), blobFor("preview", upload.files[0]));
      fitTrimRange(form, upload.files[0]);
      if(applyLiveOf.get(form)) applyLiveOf.get(form)();
    });
  }
  form.addEventListener("submit", async event => {
    event.preventDefault();
    document.getElementById("stage").hidden = false;
    const response = await post(form);
    if(!response) return;
    const type = response.headers.get("Content-Type") || "";
    if(multiout && type.includes("json")){
      const payload = await response.json();
      if(payload.parts){
        showParts(kind, payload.parts);
        if(applyLiveOf.get(form)) applyLiveOf.get(form)();
        return;
      }
      document.getElementById("status").textContent = "delivered: " + JSON.stringify(payload);
      return;
    }
    if(type.includes("json")){
      document.getElementById("status").textContent = "delivered: " + JSON.stringify(await response.json());
      return;
    }
    const blob = await response.blob();
    const url = blobFor("result", blob);
    const viewbar = document.getElementById("viewbar");
    const download = document.getElementById("download");
    viewbar.hidden = false;
    download.href = url;
    download.download = type.includes("zip") ? "chunks.zip" : "result";
    if(kind === "file" || type.includes("zip")){
      viewbar.classList.add("bare");
      document.getElementById("stage").hidden = true;
      return;
    }
    viewbar.classList.remove("bare");
    if(multiple){
      showResult(kind, url);
      if(applyLiveOf.get(form)) applyLiveOf.get(form)();
      return;
    }
    const origFile = upload && !upload.disabled ? upload.files[0] : null;
    showStage(kind, url, origFile ? blobFor("stage-orig", origFile) : null, origFile ? kindOf(origFile, kind) : kind);
    if(applyLiveOf.get(form)) applyLiveOf.get(form)();
  });
}

function previewInputs(files, fallback){
  const stage = document.getElementById("stage");
  const grid = document.getElementById("inputs-grid");
  stage.hidden = false;
  document.getElementById("frame").hidden = true;
  document.getElementById("transport").hidden = true;
  grid.hidden = false;
  grid.replaceChildren(...[...files].map((file, index) => {
    const tile = document.createElement("figure");
    tile.className = "tile";
    const media = mediaElement(kindOf(file, fallback), blobFor(`tile-${index}`, file));
    if(media.tagName === "VIDEO") media.controls = true;
    const caption = document.createElement("figcaption");
    caption.textContent = file.name;
    tile.append(media, caption);
    return tile;
  }));
}

function showParts(kind, urls){
  const grid = document.getElementById("outputs-grid");
  document.getElementById("stage").hidden = false;
  document.getElementById("frame").hidden = true;
  document.getElementById("transport").hidden = true;
  document.getElementById("seg").hidden = true;
  document.getElementById("download").hidden = true;
  grid.hidden = false;
  grid.replaceChildren(...urls.map((url, index) => {
    const tile = document.createElement("figure");
    tile.className = "tile";
    const media = mediaElement(kind, url);
    if(media.tagName === "VIDEO") media.controls = true;
    const caption = document.createElement("figcaption");
    const label = document.createElement("span");
    label.textContent = String(index + 1);
    const save = document.createElement("a");
    save.href = url;
    save.download = `part_${index + 1}`;
    save.textContent = "download";
    caption.append(label, save);
    tile.append(media, caption);
    return tile;
  }));
}

let comparator = null;

function trimOffset(){
  const start = document.querySelector('#op [name="edits_trim_start"]');
  return start && start.dataset.dirty ? Number(start.value) || 0 : 0;
}

function speedFactor(){
  const speed = document.querySelector('#op [name="edits_speed"]');
  return speed && speed.dataset.dirty ? Number(speed.value) || 1 : 1;
}

function liveFilterCss(){
  const form = document.getElementById("op");
  if(!form) return "";
  return [...form.querySelectorAll("[data-css]")]
    .filter(control => control.value !== control.defaultValue)
    .map(control => control.dataset.css.replace("{}", control.value))
    .join(" ");
}

function setStageView(mode){
  if(comparator) comparator.setView(mode);
  document.querySelectorAll("[data-view]").forEach(button => button.classList.toggle("on", button.dataset.view === mode));
}

function stageComparator({originalKind = null, originalUrl = null, resultKind = null, resultUrl = null} = {}){
  const frame = document.getElementById("frame");
  const canvas = document.getElementById("stagecanvas");
  const fallback = document.getElementById("stage-fallback");
  document.getElementById("stage").hidden = false;
  document.getElementById("inputs-grid").hidden = true;
  document.getElementById("outputs-grid").hidden = true;
  frame.hidden = false;
  if(comparator){comparator.destroy(); comparator = null;}
  window.comparator = null;
  const pdf = originalKind === "pdf" || resultKind === "pdf";
  fallback.hidden = !pdf;
  canvas.hidden = pdf;
  if(pdf){
    fallback.replaceChildren(...[originalUrl && mediaElement(originalKind, originalUrl), resultUrl && mediaElement(resultKind, resultUrl)].filter(Boolean));
    document.getElementById("seg").hidden = true;
    initTransport("pdf");
    return;
  }
  const original = originalUrl ? sourceFor(originalKind, originalUrl) : null;
  const result = resultUrl ? sourceFor(resultKind, resultUrl) : null;
  comparator = new Comparator(canvas, {original, result, offset: trimOffset(), speed: speedFactor()});
  window.comparator = comparator;
  comparator.setAspect(parseAspect(aspectValue()));
  comparator.setFilter(liveFilterCss());
  comparator.resize();
  const both = Boolean(original && result);
  document.getElementById("seg").hidden = !both;
  setStageView(both ? "split" : "side");
  initTransport([result, original].find(Boolean).kind);
}

function showStage(kind, outUrl, origUrl, origKind){
  stageComparator({originalKind: origKind || kind, originalUrl: origUrl, resultKind: kind, resultUrl: outUrl});
}

function previewOriginal(kind, origUrl){
  stageComparator({originalKind: kind, originalUrl: origUrl});
}

function showResult(kind, outUrl){
  stageComparator({resultKind: kind, resultUrl: outUrl});
}

function initTransport(kind){
  const transport = document.getElementById("transport");
  if(transportFrame) cancelAnimationFrame(transportFrame);
  transport.hidden = true;
  if(kind === "image" && comparator){
    const current = comparator;
    current.ready.then(() => {
      if(comparator === current && current.duration > 0) enableTransport();
    });
    return;
  }
  if(kind !== "video") return;
  enableTransport();
}

function transportMarkers(){
  const strip = document.getElementById("tp-markers");
  const marks = comparator && comparator.markers ? comparator.markers() : [];
  strip.replaceChildren();
  strip.hidden = marks.length < 2 || marks.length > 120 || !comparator.duration;
  if(strip.hidden) return marks;
  for(const at of marks){
    const dot = document.createElement("button");
    dot.type = "button";
    dot.className = "tp-mark";
    dot.style.left = `${(at / comparator.duration) * 100}%`;
    dot.title = formatTime(at);
    dot.onclick = () => comparator && comparator.seek(at);
    strip.append(dot);
  }
  return marks;
}

function enableTransport(){
  const transport = document.getElementById("transport");
  transport.hidden = false;
  const play = document.getElementById("tp-play");
  const seek = document.getElementById("tp-seek");
  const time = document.getElementById("tp-time");
  const marks = transportMarkers();
  let seeking = false;
  play.onclick = () => {
    if(!comparator) return;
    if(comparator.paused) comparator.play();
    else comparator.pause();
  };
  seek.oninput = () => {
    seeking = true;
    if(comparator && Number.isFinite(comparator.duration)){
      let target = (seek.value / 1000) * comparator.duration;
      if(marks.length) target = marks.reduce((best, at) => Math.abs(at - target) < Math.abs(best - target) ? at : best, marks[0]);
      comparator.seek(target);
    }
  };
  seek.onchange = () => seeking = false;
  const tick = () => {
    if(comparator){
      play.textContent = comparator.paused ? "\u25BA" : "\u2759\u2759";
      time.textContent = formatTime(comparator.time) + " / " + formatTime(comparator.duration);
      if(!seeking && Number.isFinite(comparator.duration) && comparator.duration > 0){
        seek.value = Math.round((comparator.time / comparator.duration) * 1000);
      }
    }
    transportFrame = requestAnimationFrame(tick);
  };
  transportFrame = requestAnimationFrame(tick);
}

window.addEventListener("resize", () => comparator && comparator.resize());
document.addEventListener("change", event => {
  if(event.target.closest && event.target.closest(".aspects") && comparator) comparator.setAspect(parseAspect(aspectValue()));
});
document.addEventListener("click", event => {
  const button = event.target.closest && event.target.closest("[data-view]");
  if(button) setStageView(button.dataset.view);
});

function kindOf(file, fallback){
  const type = (file && file.type) || "";
  if(type.startsWith("video/")) return "video";
  if(type.startsWith("image/")) return "image";
  if(type === "application/pdf") return "pdf";
  return fallback;
}

function formatTime(seconds){
  const tenths = Number.isFinite(seconds) ? Math.max(0, Math.round(seconds * 10)) : 0;
  const minutes = Math.floor(tenths / 600);
  const rest = (tenths % 600) / 10;
  return minutes + ":" + rest.toFixed(1).padStart(4, "0");
}

function nodeBox(data, key){
  const wrap = document.createElement("div");
  const kidCount = (data.children || []).length + Object.keys(data.branches || {}).length + (data.wraps ? 1 : 0) + (data.target ? 1 : 0);
  let fold = null;
  if(kidCount){
    fold = document.createElement("button");
    fold.type = "button";
    fold.className = "fold";
    fold.textContent = "▾";
    fold.onclick = event => {event.stopPropagation(); wrap.classList.toggle("folded");};
  }
  if(key){const chip = document.createElement("span"); chip.className = "key"; chip.textContent = key; wrap.appendChild(chip);}
  const box = document.createElement("span");
  box.className = "node";
  const kind = document.createElement("b");
  kind.textContent = data.kind;
  box.appendChild(kind);
  if(data.calls){const sub = document.createElement("span"); sub.className = "sub"; sub.textContent = "→ " + data.calls; box.appendChild(sub);}
  box.onclick = () => {
    document.querySelectorAll(".node.picked").forEach(el => el.classList.remove("picked"));
    box.classList.add("picked");
    document.getElementById("detail").replaceChildren(renderJson({kind: data.kind, calls: data.calls, ...data.detail}));
  };
  wrap.appendChild(box);
  if(fold) wrap.appendChild(fold);
  const addKids = pairs => {
    const kids = document.createElement("div");
    kids.className = "kids";
    pairs.forEach(([label, child]) => kids.appendChild(nodeBox(child, label)));
    wrap.appendChild(kids);
    wrap.classList.add("folded");
  };
  if(data.children) addKids(data.children.map((child, index) => [String(index + 1), child]));
  if(data.branches) addKids(Object.entries(data.branches));
  if(data.wraps) addKids([["wraps", data.wraps]]);
  if(data.target) addKids([["", data.target]]);
  return wrap;
}

function graphPage(group){
  const load = async name => {
    const response = await fetch(`/api/${group}/graph?name=${encodeURIComponent(name)}`);
    if(!response.ok){document.getElementById("detail").textContent = await response.text(); return;}
    document.getElementById("tree").replaceChildren(nodeBox(await response.json()));
  };
  document.querySelectorAll("[data-graph]").forEach(button => button.onclick = () => load(button.dataset.graph));
  const first = document.querySelector("[data-graph]");
  if(first) load(first.dataset.graph);
}

async function applyPreset(form, name){
  if(!form.dataset.presets){
    const response = await fetch(form.dataset.api.replace(/\/[^/]+$/, "/presets"));
    if(!response.ok) return;
    form.dataset.presets = JSON.stringify(await response.json());
  }
  const spec = JSON.parse(form.dataset.presets)[name];
  if(!spec) return;
  const resets = [];
  for(const [key, value] of Object.entries(spec)) setControl(form, key, value, resets);
  resets.forEach(range => delete range.dataset.dirty);
  form.querySelectorAll(".dual").forEach(dual => {
    const low = dual.querySelector("[data-dual-low]"), high = dual.querySelector("[data-dual-high]");
    const out = form.querySelector(`output[data-dual="${low.name}"]`);
    if(out && !low.dataset.dirty && !high.dataset.dirty) out.textContent = "any";
  });
}

function setControl(form, name, value, resets){
  const controls = [...form.querySelectorAll(`[name="${CSS.escape(name)}"]`)];
  if(!controls.length){
    if(value !== null && typeof value === "object" && !Array.isArray(value)){
      for(const [sub, subvalue] of Object.entries(value)) setControl(form, `${name}_${sub}`, subvalue, resets);
    }
    return;
  }
  const select = controls.find(el => el.tagName === "SELECT" && !el.dataset.outputToggle);
  const checkboxes = controls.filter(el => el.type === "checkbox");
  const range = controls.find(el => el.type === "range");
  if(Array.isArray(value)){
    const hidden = controls.find(el => el.type === "hidden");
    const chips = form.querySelector(`[data-chips="${CSS.escape(name)}"]`);
    if(hidden && chips){
      hidden.value = value.join(" ");
      chips.querySelectorAll('input[type="checkbox"]').forEach(box => box.checked = value.includes(box.value));
    }
    return;
  }
  if(value !== null && typeof value === "object"){
    for(const [sub, subvalue] of Object.entries(value)) setControl(form, `${name}_${sub}`, subvalue, resets);
    return;
  }
  if(range){
    range.value = value === null ? range.defaultValue : value;
    range.dispatchEvent(new Event("input", {bubbles: true}));
    if(value === null) resets.push(range);
    return;
  }
  if(select){select.value = value === null ? "" : String(value); return;}
  if(checkboxes.length){checkboxes.forEach(box => box.checked = Boolean(value)); return;}
  if(controls[0].name === "preset") return;
  controls[0].value = value === null ? "" : String(value);
}
