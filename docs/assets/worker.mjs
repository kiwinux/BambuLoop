import { loadPyodide } from "../runtime/pyodide.mjs";

const ROOT = "/bambuloop";
let initialized;
let queue = Promise.resolve();

async function initialize() {
  self.postMessage({ state: "loading" });
  const runtime = await loadPyodide({ indexURL: new URL("../runtime/", import.meta.url).href });
  const asset = await fetch(new URL("./engine.zip", import.meta.url));
  if (!asset.ok) throw new Error("Could not load the BambuLoop engine.");
  runtime.unpackArchive(await asset.arrayBuffer(), "zip", { extractDir: "/engine" });
  runtime.runPython("import sys\nsys.path.insert(0, '/engine')");
  const bridge = runtime.pyimport("browser_bridge");
  self.postMessage({ state: "ready" });
  return { fs: runtime.FS, bridge };
}

async function handle({ id, action, data, files, file }) {
  initialized ??= initialize().catch(error => { initialized = undefined; throw error; });
  const { fs, bridge } = await initialized;
  if (action === "import") {
    const result = { files: [], errors: [] };
    for (const entry of files) {
      const limit = bridge.input_limit_error(entry.size);
      if (limit) {
        result.errors.push({ filename: entry.name, message: JSON.parse(limit) });
        continue;
      }
      const incoming = ROOT + "/incoming";
      try {
        const contents = new Uint8Array(await entry.arrayBuffer());
        fs.writeFile(incoming, contents, { canOwn: true });
        const part = JSON.parse(bridge.import_one(entry.name));
        result.files.push(...part.files);
        result.errors.push(...part.errors);
      } catch (error) {
        result.errors.push({ filename: entry.name, message: String(error?.message || error) });
      } finally {
        if (fs.analyzePath(incoming).exists) fs.unlink(incoming);
      }
    }
    self.postMessage({ id, status: 200, data: result });
    return;
  }

  const outputPath = name => {
    if (typeof name !== "string" || !name || /[/\\:\0]/.test(name) || name === "." || name === "..") {
      throw new Error("Invalid result filename.");
    }
    return ROOT + "/results/" + name;
  };
  if (file && action !== "validate") throw new Error("Unexpected file.");
  const temporary = file ? outputPath(data.filename) : null;
  try {
    if (temporary) fs.writeFile(temporary, new Uint8Array(await file.arrayBuffer()), { canOwn: true });
    const [status, result] = JSON.parse(bridge.perform(action, JSON.stringify(data)));
    if (status === 200 && result.filename) {
      const name = result.filename_3mf || result.filename;
      try {
        const bytes = fs.readFile(outputPath(name));
        self.postMessage({ id, status, data: result, bytes: bytes.buffer }, [bytes.buffer]);
      } finally {
        for (const key of [result.filename, result.filename_3mf].filter(Boolean)) fs.unlink(outputPath(key));
      }
    } else {
      self.postMessage({ id, status, data: result });
    }
  } finally {
    if (temporary && fs.analyzePath(temporary).exists) fs.unlink(temporary);
  }
}

self.onmessage = ({ data }) => {
  queue = queue.then(() => handle(data)).catch(error => {
    self.postMessage({ id: data.id, failure: String(error?.message || error) });
  });
};
