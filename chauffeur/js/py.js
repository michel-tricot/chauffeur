// Browser-side half of the chauffeur channel. Injected into every document
// (and evaluable in extension service workers). Symmetric to the Python side:
//   await py.call("save_password", {...})  -> runs the @browser.command handler
//   py.notify("telemetry", {...})          -> fire-and-forget
//   py.on("refresh_ui", async p => {...})  -> handles browser.call() from Python
(() => {
  if (globalThis.py) return;
  const pending = new Map();
  const handlers = new Map();
  let seq = 0;

  function dispatch(envelope) {
    const binding = globalThis.__chauffeur_dispatch;
    if (typeof binding !== "function") {
      throw new Error("chauffeur binding not installed in this context");
    }
    binding(JSON.stringify(envelope));
  }

  globalThis.py = {
    call(command, params) {
      const id = "js" + ++seq;
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
        try {
          dispatch({ id, command, params: params ?? null });
        } catch (err) {
          pending.delete(id);
          reject(err);
        }
      });
    },

    notify(command, params) {
      dispatch({ id: null, command, params: params ?? null });
    },

    on(command, fn) {
      handlers.set(command, fn);
    },

    // Called by Python via Runtime.evaluate to resolve a pending py.call().
    _deliver(reply) {
      const entry = pending.get(reply.id);
      if (!entry) return;
      pending.delete(reply.id);
      if (reply.error) {
        entry.reject(Object.assign(new Error(reply.error.message), { type: reply.error.type }));
      } else {
        entry.resolve(reply.result);
      }
    },

    // Called by Python via Runtime.evaluate(awaitPromise) for browser.call().
    async _handle(msg) {
      const fn = handlers.get(msg.command);
      if (!fn) throw new Error("no JS handler for command: " + msg.command);
      return await fn(msg.params);
    },
  };
})();
