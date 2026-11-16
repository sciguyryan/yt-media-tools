/* The organisation does not read this file.
 *
 * Typing the observer's incantation anywhere on the dashboard (with or without
 * spaces) renders the timeline-convergence briefing. The briefing is stored
 * encrypted so its text cannot be read at a glance; the cipher is deliberately
 * visible, the key is not.
 *
 * The key is the phrase you just typed, lowercased and without spaces.
 * The organisation would never think to look here.
 *
 * The blobs are regenerated transparently by yt-sql/build_dashboard_egg.py
 * from the readable sources in dashboard/egg-payload-*.js.
 */
"use strict";

(function () {
  const CIPHER_CONVERGENCE = "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";
  const CIPHER_READING_STEINER = "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";
  const BRIEFINGS = {
    elpsykongroo: { blob: CIPHER_CONVERGENCE },
    readingsteiner: { blob: CIPHER_READING_STEINER },
  };
  let buffer = "";
  let triggered = false;

  // RC4, mirroring the generator; the key is the incantation above.
  function decrypt(blob, key) {
    const data = atob(blob);
    const s = [];
    for (let i = 0; i < 256; i += 1) s.push(i);
    let j = 0;
    for (let i = 0; i < 256; i += 1) {
      j = (j + s[i] + key.charCodeAt(i % key.length)) % 256;
      const swap = s[i];
      s[i] = s[j];
      s[j] = swap;
    }
    let i = 0;
    j = 0;
    let out = "";
    for (let index = 0; index < data.length; index += 1) {
      i = (i + 1) % 256;
      j = (j + s[i]) % 256;
      const swap = s[i];
      s[i] = s[j];
      s[j] = swap;
      out += String.fromCharCode(data.charCodeAt(index) ^ s[(s[i] + s[j]) % 256]);
    }
    return out;
  }

  function isTypingTarget(event) {
    const tag = (event.target && event.target.tagName) || "";
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || event.target.isContentEditable;
  }

  const KEYBOARD_ACTIVABLE = new Set(["BUTTON", "A", "SUMMARY"]);

  // Firefox's find-as-you-type never triggers while an editable element holds
  // focus. Rather than racing the browser's internal key handling (page-level
  // preventDefault lost that race repeatedly), the capture field below holds
  // focus whenever no real input is active, which is the pattern terminal
  // emulators use to own the keyboard in Firefox.
  const captureField = document.createElement("textarea");
  captureField.className = "egg-capture";
  captureField.setAttribute("tabindex", "-1");
  captureField.setAttribute("aria-hidden", "true");
  captureField.setAttribute("autocomplete", "off");
  document.body.append(captureField);

  function focusCaptureField() {
    if (!isTypingTarget({ target: document.activeElement })) captureField.focus({ preventScroll: true });
  }

  document.addEventListener("click", (event) => {
    if (!isTypingTarget(event) && !(event.target && KEYBOARD_ACTIVABLE.has(event.target.tagName))) focusCaptureField();
  });
  focusCaptureField();

  window.addEventListener(
    "keydown",
    function (event) {
      if (
        event.key.length === 1 &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey &&
        !isTypingTarget(event) &&
        !(event.key === " " && event.target && KEYBOARD_ACTIVABLE.has(event.target.tagName))
      ) {
        // Keep the best-effort suppression for events that land outside the
        // capture field, such as after focusing a button by keyboard.
        event.preventDefault();
      }
    },
    { capture: true, passive: false }
  );

  document.addEventListener("keydown", (event) => {
    if (event.target === captureField) return; // Handled by the capture field below.
    if (event.ctrlKey || event.metaKey || event.altKey || event.key.length !== 1) return;
    buffer = (buffer + event.key.toLowerCase()).slice(-32);
    triggerIfComplete();
  });

  captureField.addEventListener("keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key === "Escape") return; // Detail overlays handle Escape themselves.
    if (event.key.length === 1) {
      // The capture field never accumulates text and never scrolls: printable
      // keys are consumed before the default action can edit the field.
      event.preventDefault();
      buffer = (buffer + event.key.toLowerCase()).slice(-32);
      triggerIfComplete();
    }
  });

  function triggerIfComplete() {
    if (triggered) return;
    // Two incantations, two briefings: the convergence dream and the
    // observer's reading. Each trigger names its own encrypted payload.
    for (const trigger of Object.keys(BRIEFINGS)) {
      if (!buffer.endsWith(trigger)) continue;
      triggered = true;
      const assemble = (facts) => {
        try {
          // Finishing releases the trigger latch: the incantation can be
          // typed again without reloading the page.
          facts.done = () => { triggered = false; };
          // Byte-wise XOR output is mapped to a binary-safe string before UTF-8
          // decoding via escape/decodeURIComponent, the portable pre-TextDecoder
          // sequence for arbitrary binary data.
          const code = decrypt(BRIEFINGS[trigger].blob, trigger);
          const binary = code.replace(/[\x80-\xff]/g, (c) => "%" + c.charCodeAt(0).toString(16).padStart(2, "0"));
          // Each payload is an anonymous function expression taking the facts.
          new Function("facts", "return (" + decodeURIComponent(escape(binary)) + ")(facts);")(facts);
        } catch {
          // A failed decryption stays silent; the dashboard continues as normal.
        }
      };
      // The briefings read real dashboard data: the meter is the truth.
      if (window.__STATIC_DATA__) {
        assemble({ functions: window.__STATIC_DATA__.functions || [], overview: window.__STATIC_DATA__.overview || {} });
      } else {
        Promise.all([
          fetch("/api/functions").then((r) => r.json()).catch(() => []),
          fetch("/api/overview").then((r) => r.json()).catch(() => ({})),
        ]).then(([functions, overview]) => assemble({ functions: functions || [], overview: overview || {} }));
      }
      return;
    }
  }

  // Diagnostic marker: verify the egg loaded at all before debugging the
  // suppression. window.__EGG_ARMED__ is true once the listeners are live.
  window.__EGG_ARMED__ = true;
})();
