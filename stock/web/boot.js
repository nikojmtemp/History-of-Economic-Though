// Stock in the browser: the game's engine is Python, run in this page by Pyodide.
// Only the web build (scripts/build_web.py) loads this file; the desktop app talks to its
// own server instead. It sets window.STOCK_READY, and app.js's api() then sends each
// request to the engine here rather than over HTTP.
"use strict";
(function () {
  const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";
  const cover = document.getElementById("loading");
  const say = (text) => { if (cover) cover.querySelector(".what").textContent = text; };
  const stamp = document.currentScript.dataset.stamp || "";

  window.STOCK_READY = (async () => {
    say("Loading Python (about 10 MB the first time; after that it is quick)…");
    const py = await loadPyodide({ indexURL: PYODIDE });
    say("Loading the game…");
    const zip = await (await fetch(`stock.zip?v=${stamp}`)).arrayBuffer();
    py.unpackArchive(zip, "zip", { extractDir: "/home/pyodide" });
    say("Making the world…");
    await new Promise((r) => setTimeout(r, 30));  // let the message paint before the work
    const engine = py.pyimport("stock.browser");
    engine.start(window.localStorage);
    window.STOCK_LOCAL = (path, body) => JSON.parse(engine.call(path, JSON.stringify(body ?? null)));
    if (cover) cover.hidden = true;
  })();
  window.STOCK_READY.catch((err) => {
    say(`Stock could not start: ${err}`);
    if (cover) cover.classList.add("failed");
  });
})();
