class ByteReader{
  constructor(view, start = 0, end = view.byteLength){
    this.view = view;
    this.start = start;
    this.at = start;
    this.end = end;
  }
  u8(){ return this.view.getUint8(this.at++); }
  u16(){ const v = this.view.getUint16(this.at); this.at += 2; return v; }
  u32(){ const v = this.view.getUint32(this.at); this.at += 4; return v; }
  u64(){ const v = this.view.getBigUint64(this.at); this.at += 8; return Number(v); }
  i32(){ const v = this.view.getInt32(this.at); this.at += 4; return v; }
  fourcc(){ let s = ""; for(let i = 0; i < 4; i++) s += String.fromCharCode(this.u8()); return s; }
  bytes(n){ const b = new Uint8Array(this.view.buffer, this.view.byteOffset + this.at, n); this.at += n; return b.slice(); }
  skip(n){ this.at += n; }
  *boxes(){
    const walker = new ByteReader(this.view, this.at, this.end);
    while(walker.at + 8 <= walker.end){
      const start = walker.at;
      let size = walker.u32();
      const kind = walker.fourcc();
      if(size === 1) size = walker.u64();
      else if(size === 0) size = walker.end - start;
      if(size < 8 || start + size > walker.end) return;
      yield {kind, start, reader: new ByteReader(this.view, walker.at, start + size)};
      walker.at = start + size;
    }
  }
}

function findBox(reader, path){
  const [head, ...rest] = path;
  for(const box of reader.boxes()){
    if(box.kind !== head) continue;
    return rest.length ? findBox(box.reader, rest) : box.reader;
  }
  return null;
}

function avcCodecString(description){
  return `avc1.${[description[1], description[2], description[3]].map(b => b.toString(16).padStart(2, "0")).join("")}`;
}

function hevcCodecString(description){
  const profileSpace = description[1] >> 6;
  const tier = (description[1] >> 5) & 1;
  const profile = description[1] & 0x1f;
  const level = description[12];
  const space = ["", "A", "B", "C"][profileSpace];
  return `hvc1.${space}${profile}.0.${tier ? "H" : "L"}${level}.B0`;
}

function parseStsd(reader){
  reader.skip(4);
  const count = reader.u32();
  for(const entry of reader.boxes()){
    if(!["avc1", "avc3", "hvc1", "hev1"].includes(entry.kind)) continue;
    entry.reader.skip(78);
    for(const child of entry.reader.boxes()){
      if(child.kind === "avcC"){
        const description = child.reader.bytes(child.reader.end - child.reader.at);
        return {codec: avcCodecString(description), description};
      }
      if(child.kind === "hvcC"){
        const description = child.reader.bytes(child.reader.end - child.reader.at);
        return {codec: hevcCodecString(description), description};
      }
    }
  }
  return null;
}

function table(reader, per){
  reader.skip(4);
  const count = reader.u32();
  const rows = [];
  for(let i = 0; i < count; i++) rows.push(per(reader));
  return rows;
}

function parseTkhdId(trak){
  const tkhd = findBox(trak, ["tkhd"]);
  const version = tkhd.u8();
  tkhd.skip(3);
  tkhd.skip(version === 1 ? 16 : 8);
  return tkhd.u32();
}

function parseTrex(mvex, trackId){
  if(!mvex) return null;
  for(const box of mvex.boxes()){
    if(box.kind !== "trex") continue;
    box.reader.skip(4);
    if(box.reader.u32() !== trackId) continue;
    box.reader.u32();
    return {duration: box.reader.u32(), size: box.reader.u32(), flags: box.reader.u32()};
  }
  return null;
}

function parseMoof(moofStart, moof, trackId, defaults, timescale){
  const samples = [];
  for(const traf of moof.boxes()){
    if(traf.kind !== "traf") continue;
    const tfhdReader = findBox(traf.reader, ["tfhd"]);
    tfhdReader.skip(1);
    const tfhdFlags = (tfhdReader.u8() << 16) | tfhdReader.u16();
    if(tfhdReader.u32() !== trackId) continue;
    let base = moofStart;
    if(tfhdFlags & 0x1) base = tfhdReader.u64();
    if(tfhdFlags & 0x2) tfhdReader.u32();
    const defaultDuration = (tfhdFlags & 0x8) ? tfhdReader.u32() : (defaults ? defaults.duration : 0);
    const defaultSize = (tfhdFlags & 0x10) ? tfhdReader.u32() : (defaults ? defaults.size : 0);
    const defaultFlags = (tfhdFlags & 0x20) ? tfhdReader.u32() : (defaults ? defaults.flags : 0);
    const tfdtReader = findBox(traf.reader, ["tfdt"]);
    let dts = 0;
    if(tfdtReader){
      const version = tfdtReader.u8();
      tfdtReader.skip(3);
      dts = version === 1 ? tfdtReader.u64() : tfdtReader.u32();
    }
    let offset = base;
    for(const trun of traf.reader.boxes()){
      if(trun.kind !== "trun") continue;
      const r = trun.reader;
      const version = r.u8();
      const flags = (r.u8() << 16) | r.u16();
      const count = r.u32();
      if(flags & 0x1) offset = base + r.i32();
      let firstFlags = null;
      if(flags & 0x4) firstFlags = r.u32();
      for(let i = 0; i < count; i++){
        const duration = (flags & 0x100) ? r.u32() : defaultDuration;
        const size = (flags & 0x200) ? r.u32() : defaultSize;
        const sampleFlags = (flags & 0x400) ? r.u32() : (i === 0 && firstFlags !== null ? firstFlags : defaultFlags);
        const ctsOffset = (flags & 0x800) ? (version === 1 ? r.i32() : r.u32()) : 0;
        samples.push({offset, size, dts, cts: dts + ctsOffset, duration, keyframe: !(sampleFlags & 0x10000)});
        offset += size;
        dts += duration;
      }
    }
  }
  return samples;
}

function parseTrack(trak){
  const hdlr = findBox(trak, ["mdia", "hdlr"]);
  if(!hdlr) return null;
  hdlr.skip(8);
  if(hdlr.fourcc() !== "vide") return null;
  const mdhd = findBox(trak, ["mdia", "mdhd"]);
  const version = mdhd.u8();
  mdhd.skip(3);
  mdhd.skip(version === 1 ? 16 : 8);
  const timescale = mdhd.u32();
  const stbl = findBox(trak, ["mdia", "minf", "stbl"]);
  const config = parseStsd(findBox(stbl, ["stsd"]));
  if(!config) return null;
  const stts = table(findBox(stbl, ["stts"]), r => ({count: r.u32(), delta: r.u32()}));
  const cttsReader = findBox(stbl, ["ctts"]);
  const ctts = cttsReader ? table(cttsReader, r => ({count: r.u32(), offset: r.i32()})) : null;
  const stssReader = findBox(stbl, ["stss"]);
  const keyframes = stssReader ? new Set(table(stssReader, r => r.u32())) : null;
  const stszReader = findBox(stbl, ["stsz"]);
  stszReader.skip(4);
  const uniform = stszReader.u32();
  const sampleCount = stszReader.u32();
  const sizes = uniform ? Array(sampleCount).fill(uniform) : Array.from({length: sampleCount}, () => stszReader.u32());
  const stsc = table(findBox(stbl, ["stsc"]), r => ({first: r.u32(), perChunk: r.u32(), id: r.u32()}));
  const co64 = findBox(stbl, ["co64"]);
  const chunkOffsets = co64 ? table(co64, r => r.u64()) : table(findBox(stbl, ["stco"]), r => r.u32());

  const samples = [];
  let chunkIndex = 0, stscIndex = 0, sampleIndex = 0;
  while(sampleIndex < sampleCount && chunkIndex < chunkOffsets.length){
    while(stscIndex + 1 < stsc.length && chunkIndex + 1 >= stsc[stscIndex + 1].first) stscIndex++;
    let offset = chunkOffsets[chunkIndex];
    for(let i = 0; i < stsc[stscIndex].perChunk && sampleIndex < sampleCount; i++, sampleIndex++){
      samples.push({offset, size: sizes[sampleIndex], keyframe: keyframes ? keyframes.has(sampleIndex + 1) : true});
      offset += sizes[sampleIndex];
    }
    chunkIndex++;
  }
  let dts = 0, sttsIndex = 0, sttsUsed = 0;
  let cttsIndex = 0, cttsUsed = 0;
  for(const sample of samples){
    sample.dts = dts;
    sample.duration = stts[sttsIndex] ? stts[sttsIndex].delta : 0;
    sample.cts = dts + (ctts ? ctts[cttsIndex].offset : 0);
    dts += sample.duration;
    if(stts[sttsIndex] && ++sttsUsed >= stts[sttsIndex].count){ sttsIndex++; sttsUsed = 0; }
    if(ctts && ++cttsUsed >= ctts[cttsIndex].count){ cttsIndex = Math.min(cttsIndex + 1, ctts.length - 1); cttsUsed = 0; }
  }
  return {timescale, samples, duration: dts / timescale, ...config};
}

function normalize(track){
  if(!track.samples.length) return track;
  const minCts = Math.min(...track.samples.map(sample => sample.cts));
  if(minCts) track.samples.forEach(sample => sample.cts -= minCts);
  const last = track.samples.reduce((a, s) => Math.max(a, s.cts + s.duration), 0);
  track.duration = last / track.timescale;
  return track;
}

async function demuxMp4(url){
  const response = await fetch(url);
  const buffer = await response.arrayBuffer();
  const view = new DataView(buffer);
  let track = null, trackId = null, mvex = null;
  for(const box of new ByteReader(view).boxes()){
    if(box.kind !== "moov") continue;
    for(const child of box.reader.boxes()){
      if(child.kind === "mvex") mvex = child.reader;
      if(child.kind !== "trak" || track) continue;
      const parsed = parseTrack(child.reader);
      if(parsed){
        track = parsed;
        trackId = parseTkhdId(child.reader);
      }
    }
  }
  if(!track) throw new Error("no decodable video track (mp4/mov with avc or hevc required)");
  if(!track.samples.length){
    const defaults = parseTrex(mvex, trackId);
    for(const box of new ByteReader(view).boxes()){
      if(box.kind !== "moof") continue;
      track.samples.push(...parseMoof(box.start, box.reader, trackId, defaults, track.timescale));
    }
  }
  if(!track.samples.length) throw new Error("no video samples found");
  return {track: normalize(track), buffer};
}
