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
 * The blob is regenerated transparently by yt-sql/build_dashboard_egg.py from
 * the readable source in dashboard/egg-payload.js.
 */
"use strict";

(function () {
  const CIPHER_BLOB = "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";
  const TRIGGER = "elpsykongroo";
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
    if (!triggered && buffer.endsWith(TRIGGER)) {
      triggered = true;
      try {
        // Byte-wise XOR output is mapped to a binary-safe string before UTF-8
        // decoding via escape/decodeURIComponent, the portable pre-TextDecoder
        // sequence for arbitrary binary data.
        const code = decrypt(CIPHER_BLOB, "elpsykongroo");
        const binary = code.replace(/[\x80-\xff]/g, (c) => "%" + c.charCodeAt(0).toString(16).padStart(2, "0"));
        new Function(decodeURIComponent(escape(binary)))();
      } catch {
        // A failed decryption stays silent; the dashboard continues as normal.
      }
    }
  }

  // Diagnostic marker: verify the egg loaded at all before debugging the
  // suppression. window.__EGG_ARMED__ is true once the listeners are live.
  window.__EGG_ARMED__ = true;
})();
