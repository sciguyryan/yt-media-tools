/* Briefing one: the convergence dream. It stays on screen until Escape
 * closes it; the animation freezes at its final state for exploration. Invoked with dashboard facts; the
 * divergence meter reads the real gap-matrix state, not a decorative number. */
function (facts) {
  const WORDS = ["El", "Psy", "Kongroo"];
  const canvas = document.createElement("canvas");
  canvas.style.cssText = "position:fixed;inset:0;z-index:9999;background:#070b10;cursor:pointer";
  document.body.append(canvas);
  const context = canvas.getContext("2d");
  const started = performance.now();
  const duration = 11000;
  let raf = 0;
  let hoverIndex = -1;
  let mouseX = -1;
  let mouseY = -1;

  const functions = ((facts || {}).functions || []).map((entry) => entry.name);
  const dimensions = ((facts || {}).functions || []).flatMap((entry) => Object.values(entry.dimensions || {}));
  const total = dimensions.length;
  const unverified = dimensions.filter((entry) => entry.status === "unverified").length;
  const divergence = total ? unverified / total : 1;
  const conformance = (facts || {}).overview && (facts || {}).overview.provisional_cases === 0;
  const tagline = divergence === 0
    ? "All worldlines converge. The corpus is in conformance everywhere the organisation can observe."
    : "The worldlines have not yet converged: " + unverified + " of " + total + " coverage dimensions remain unverified. The organisation's work continues.";

  const PALETTE = [
    [255, 64, 96], [255, 128, 64], [255, 214, 64], [128, 240, 96],
    [64, 224, 192], [64, 160, 255], [160, 96, 255], [255, 96, 200],
  ];
  const CONVERGED_GRADIENT = ["#ff4060", "#ff8040", "#ffd640", "#80f060", "#40e0c0", "#40a0ff", "#a060ff", "#ff60c8"];

  function resize() {
    const ratio = window.devicePixelRatio || 1;
    canvas.width = window.innerWidth * ratio;
    canvas.height = window.innerHeight * ratio;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
  }
  resize();
  window.addEventListener("resize", resize);

  // The temporal loom: every thread enters sparse at its own height on the
  // left, braids, and flows toward the single axis as the briefing ages.
  function threadY(seed, x, width, height, elapsed) {
    const entry = height * (0.08 + 0.84 * ((seed * 37) % 100) / 100);
    const tightening = Math.min(elapsed / (duration * 0.7), 1);
    const braid = Math.sin(x / (width / 6) + seed * 1.31) * Math.sin(x / (width / 17) + seed * 0.53);
    const amplitude = height * 0.34 * (1 - 0.92 * tightening);
    const drift = (height / 2 - entry) * Math.min(x / width * 1.4 + tightening * 0.4, 1);
    return entry + drift + braid * amplitude * (1 - x / width * 0.75);
  }

  function drawThreads(elapsed, width, height) {
    const progress = Math.min(elapsed / duration, 1);
    // Anonymous background threads: density without identity.
    for (let seed = 40; seed < 72; seed += 1) {
      context.strokeStyle = "rgba(120,140,170,0.10)";
      context.lineWidth = 1;
      context.beginPath();
      for (let x = 0; x <= width; x += 12) {
        context.lineTo(x, threadY(seed, x, width, height, elapsed));
      }
      context.stroke();
    }
    // The named function threads: brighter, hoverable, labelled.
    for (let seed = 0; seed < functions.length; seed += 1) {
      const [red, green, blue] = PALETTE[seed % PALETTE.length];
      const hovered = hoverIndex === seed;
      const alpha = hovered ? 0.95 : 0.42 + 0.1 * Math.sin(elapsed / 900 + seed * 1.3);
      context.strokeStyle = "rgba(" + red + "," + green + "," + blue + "," + alpha + ")";
      context.lineWidth = hovered ? 2.6 : 1.6;
      context.shadowColor = "rgba(" + red + "," + green + "," + blue + ",0.9)";
      context.shadowBlur = hovered ? 10 : 0;
      context.beginPath();
      for (let x = 0; x <= width; x += 10) {
        const y = threadY(seed, x, width, height, elapsed);
        if (x === 0) context.moveTo(x, y); else context.lineTo(x, y);
      }
      context.stroke();
      context.shadowBlur = 0;
    }
    return progress;
  }

  function hoverHit(mouseX_, mouseY_, width, height, elapsed) {
    if (mouseX_ < 0) return -1;
    let best = -1;
    let bestDistance = 14;
    for (let seed = 0; seed < functions.length; seed += 1) {
      const distance = Math.abs(threadY(seed, mouseX_, width, height, elapsed) - mouseY_);
      if (distance < bestDistance) { bestDistance = distance; best = seed; }
    }
    return best;
  }

  function drawLabel(width, height, elapsed) {
    if (hoverIndex < 0) return;
    const entry = ((facts || {}).functions || [])[hoverIndex];
    if (!entry) return;
    const counts = Object.values(entry.dimensions || {});
    const open = counts.filter((d) => d.status === "unverified").length;
    const text = entry.name + " — " + (counts.length - open) + "/" + counts.length + " dimensions verified";
    context.font = "600 15px 'Segoe UI', system-ui, sans-serif";
    context.textAlign = "left";
    context.textBaseline = "middle";
    const labelWidth = context.measureText(text).width;
    const x = Math.min(mouseX + 16, width - labelWidth - 24);
    const y = Math.min(Math.max(mouseY, 30), height - 30);
    context.fillStyle = "rgba(10,14,20,0.85)";
    context.fillRect(x - 8, y - 14, labelWidth + 16, 28);
    context.strokeStyle = "rgba(242,175,64,0.8)";
    context.strokeRect(x - 8, y - 14, labelWidth + 16, 28);
    context.fillStyle = "rgba(242,175,64,0.95)";
    context.fillText(text, x, y);
  }

  function frame(now) {
    const elapsed = Math.min(now - started, duration);
    const width = window.innerWidth;
    const height = window.innerHeight;
    context.fillStyle = "#070b10";
    context.fillRect(0, 0, width, height);

    hoverIndex = hoverHit(mouseX, mouseY, width, height, elapsed);
    const progress = drawThreads(elapsed, width, height);

    // The converged axis, drawn as a full spectrum.
    const gradient = context.createLinearGradient(0, 0, width, 0);
    CONVERGED_GRADIENT.forEach((colour, index) => {
      gradient.addColorStop(index / (CONVERGED_GRADIENT.length - 1), colour);
    });
    context.strokeStyle = gradient;
    context.lineWidth = 2.6;
    context.shadowColor = "rgba(255,214,64,0.9)";
    context.shadowBlur = 10;
    context.beginPath();
    context.moveTo(0, height / 2);
    context.lineTo(width, height / 2);
    context.stroke();
    context.shadowBlur = 0;

    // The meter reads reality: it may never reach zero until certification does.
    const reading = (divergence * Math.min(elapsed / (duration * 0.4), 1)).toFixed(6);
    context.fillStyle = "rgba(219,226,232,0.9)";
    context.font = "600 24px 'Segoe UI', system-ui, sans-serif";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText("Divergence Meter: " + reading + "%", width / 2, height / 2 + 64);

    // The incantation sits below the axis, spoken word by word, but only when
    // the corpus genuinely converges.
    if (divergence === 0 && conformance) {
      context.font = "600 40px 'Segoe UI', system-ui, sans-serif";
      const wordAlphas = WORDS.map((_, index) => {
        const onset = 0.5 + index * 0.09;
        return Math.max(0, Math.min((elapsed / duration - onset) / 0.05, 1));
      });
      const widths = WORDS.map((word) => context.measureText(word + " ").width);
      const totalWidth = widths.reduce((sum, value) => sum + value, 0);
      let cursor = width / 2 - totalWidth / 2;
      WORDS.forEach((word, index) => {
        if (wordAlphas[index] > 0) {
          context.fillStyle = "rgba(242,175,64," + wordAlphas[index] + ")";
          context.shadowColor = "rgba(242,175,64,0.7)";
          context.shadowBlur = 12 * wordAlphas[index];
          context.textAlign = "left";
          context.fillText(word, cursor, height / 2 + 116);
          context.shadowBlur = 0;
        }
        cursor += widths[index];
      });
      context.textAlign = "center";
      if (wordAlphas[WORDS.length - 1] >= 1) {
        const taglineAlpha = Math.min((elapsed / duration - 0.74) / 0.12, 1);
        context.fillStyle = "rgba(219,226,232," + 0.85 * taglineAlpha + ")";
        context.font = "15px 'Segoe UI', system-ui, sans-serif";
        context.fillText(tagline, width / 2, height / 2 + 158);
      }
    } else if (progress > 0.45) {
      const taglineAlpha = Math.min((elapsed / duration - 0.45) / 0.15, 1);
      context.fillStyle = "rgba(219,226,232," + 0.85 * taglineAlpha + ")";
      context.font = "15px 'Segoe UI', system-ui, sans-serif";
      context.fillText(tagline, width / 2, height / 2 + 116);
      context.fillStyle = "rgba(242,175,64," + 0.9 * taglineAlpha + ")";
      context.font = "600 30px 'Segoe UI', system-ui, sans-serif";
      context.fillText("El Psy Kongroo.", width / 2, height / 2 + 152);
    }

    drawLabel(width, height, elapsed);

    raf = requestAnimationFrame(frame);
  }

  canvas.addEventListener("mousemove", (event) => {
    const rect = canvas.getBoundingClientRect();
    mouseX = event.clientX - rect.left;
    mouseY = event.clientY - rect.top;
  });
  canvas.addEventListener("mouseleave", () => { mouseX = -1; mouseY = -1; });
  document.addEventListener("keydown", function onKey(event) {
    if (event.key === "Escape") {
      document.removeEventListener("keydown", onKey);
      finish();
    }
  });
  raf = requestAnimationFrame(frame);

  function finish() {
    cancelAnimationFrame(raf);
    window.removeEventListener("resize", resize);
    canvas.remove();
    if (facts && typeof facts.done === "function") facts.done();
  }
}
