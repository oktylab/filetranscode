const { JSDOM } = require("jsdom");
const BASE = "http://127.0.0.1:" + (process.env.PORT || "8799");
const pages = ["video/export", "video/fanout", "video/split", "video/merge", "video/probe", "video/plan", "video/graph", "photo/export", "photo/probe", "photo/graph"];
(async () => {
  let bad = 0;
  for (const page of pages) {
    try {
      const html = await (await fetch(`${BASE}/${page}`)).text();
      const dom = new JSDOM(html, { runScripts: "outside-only", url: `${BASE}/${page}`, pretendToBeVisual: true });
      dom.window.fetch = (u) => fetch(new URL(u, BASE).href);
      dom.window.FormData = FormData;
      dom.window.URL.createObjectURL = () => "blob:fake";
      dom.window.URL.revokeObjectURL = () => {};
      for (const s of [...dom.window.document.querySelectorAll("script")]) {
        const src = s.src ? await (await fetch(s.src)).text() : s.textContent;
        try { dom.window.eval(src); } catch (e) { bad++; console.log(`${page}: THROW ${e.message}`); }
      }
    } catch (e) { bad++; console.log(`${page}: FAIL ${e.message}`); }
  }
  console.log(bad === 0 ? `all ${pages.length} pages eval clean` : `${bad} failures`);
})();
