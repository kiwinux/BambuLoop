// Each tab owns one worker, its imported files and its currently displayed download.
let worker;
let nextID = 0;
const pending = new Map();

function clearWorker(error, lostInputs = false) {
  worker?.terminate();
  worker = undefined;
  for (const call of pending.values()) call.reject(error);
  pending.clear();
  if (lostInputs) document.dispatchEvent(new Event("engine-invalidated"));
  document.dispatchEvent(new CustomEvent("engine-state", { detail: "idle" }));
}

function openWorker() {
  if (location.protocol === "file:") throw new Error(document.documentElement.lang === "ko"
    ? "Pages 주소 또는 로컬 HTTP 주소에서 열어 주세요." : "Open the site over HTTP or HTTPS.");
  const active = new Worker(new URL("./worker.mjs", import.meta.url), { type: "module" });
  active.onmessage = ({ data: message }) => {
    if (active !== worker) return;
    if (message.state) {
      document.dispatchEvent(new CustomEvent("engine-state", { detail: message.state }));
      return;
    }
    const call = pending.get(message.id);
    if (!call) return;
    pending.delete(message.id);
    if (message.failure) {
      document.dispatchEvent(new CustomEvent("engine-state", {detail: "idle"}));
      call.reject(new Error(message.failure));
      return;
    }
    const { status, data, bytes } = message;
    const type = data.filename_3mf ? "application/octet-stream" : "text/plain;charset=utf-8";
    call.resolve({ status, ok: status >= 200 && status < 300, data, blob: bytes ? new Blob([bytes], { type }) : null });
  };
  active.onerror = event => {
    if (active === worker) clearWorker(new Error(event.message || "Could not start the processing worker."), true);
  };
  active.onmessageerror = () => {
    if (active === worker) clearWorker(new Error("Could not read the worker response."), true);
  };
  return active;
}

export function requestJob(action, data = {}, attachments = {}) {
  return new Promise((resolve, reject) => {
    worker ??= openWorker();
    const id = ++nextID;
    pending.set(id, { resolve, reject });
    try {
      worker.postMessage({ id, action, data, ...attachments });
    } catch (error) {
      pending.delete(id);
      reject(error);
    }
  });
}

export function resetWorker() {
  clearWorker(new DOMException("Reset", "AbortError"));
}
