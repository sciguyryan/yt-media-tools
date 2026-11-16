/* Briefing two: the observer's reading. It stays on screen until Escape
 * closes it; the animation freezes at its final state for exploration. Invoked with dashboard facts; shows
 * the worldlines as they are, not as the organisation would like them. */
function (facts) {
  const canvas = document.createElement("canvas");
  canvas.style.cssText = "position:fixed;inset:0;z-index:9999;background:#070b10;cursor:pointer";
  document.body.append(canvas);
  const context = canvas.getContext("2d");
  const started = performance.now();
  const duration = 12000;
  let raf = 0;
  let hoverIndex = -1;
  let mouseX = -1;
  let mouseY = -1;

  const entries = ((facts || {}).functions || []).map((entry) => {
    const counts = Object.values(entry.dimensions || {});
    const open = counts.filter((d) => d.status === "unverified").length;
    return { name: entry.name, open: open, total: counts.length };
  });
  const total = entries.reduce((sum, entry) => sum + entry.total, 0);
  const unverified = entries.reduce((sum, entry) => sum + entry.open, 0);
  const divergence = total ? unverified / total : 1;

  const PALETTE = [
    [255, 64, 96], [255, 128, 64], [255, 214, 64], [128, 240, 96],
    [64, 224, 192], [64, 160, 255], [160, 96, 255], [255, 96, 200],
  ];

  function resize() {
    const ratio = window.devicePixelRatio || 1;
    canvas.width = window.innerWidth * ratio;
    canvas.height = window.innerHeight * ratio;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
  }
  resize();
  window.addEventListener("resize", resize);

  // Each function's thread starts on the converged axis and, as the reading
  // begins, departs to its own band: the observed divergence made visible.
  function threadY(seed, x, width, height, elapsed) {
    const spread = Math.min(elapsed / (duration * 0.3), 1);
    const band = height * (0.12 + 0.76 * seed / Math.max(entries.length - 1, 1));
    const wave = Math.sin(x / (width / 9) + seed * 1.7) * 8 * (1 - spread);
    const lift = (height / 2 - band) * spread;
    return height / 2 + lift + wave;
  }

  function hoverHit(x, y, width, height, elapsed) {
    if (x < 0 || !entries.length) return -1;
    let best = -1;
    let bestDistance = 14;
    for (let seed = 0; seed < entries.length; seed += 1) {
      const distance = Math.abs(threadY(seed, x, width, height, elapsed) - y);
      if (distance < bestDistance) { bestDistance = distance; best = seed; }
    }
    return best;
  }

  function frame(now) {
    const elapsed = Math.min(now - started, duration);
    const width = window.innerWidth;
    const height = window.innerHeight;
    context.fillStyle = "#070b10";
    context.fillRect(0, 0, width, height);

    hoverIndex = hoverHit(mouseX, mouseY, width, height, elapsed);

    for (let seed = 0; seed < entries.length; seed += 1) {
      const [red, green, blue] = PALETTE[seed % PALETTE.length];
      const entry = entries[seed];
      const complete = entry.open === 0;
      const hovered = hoverIndex === seed;
      const alpha = complete ? 0.35 : hovered ? 0.95 : 0.6;
      context.strokeStyle = "rgba(" + red + "," + green + "," + blue + "," + alpha + ")";
      context.lineWidth = hovered ? 2.6 : entry.open ? 1.6 : 1;
      context.beginPath();
      for (let x = 0; x <= width; x += 10) {
        const y = threadY(seed, x, width, height, elapsed);
        if (x === 0) context.moveTo(x, y); else context.lineTo(x, y);
      }
      context.stroke();
      // The thread's label rides its own band.
      context.fillStyle = complete ? "rgba(139,150,160,0.75)" : "rgba(" + red + "," + green + "," + blue + ",0.95)";
      context.font = "600 13px 'Segoe UI', system-ui, sans-serif";
      context.textAlign = "left";
      context.textBaseline = "middle";
      context.fillText(entry.name + (entry.open ? " — " + (entry.total - entry.open) + "/" + entry.total : " ✓"), 14, threadY(seed, 30, width, height, elapsed));
    }

    const reading = (divergence * Math.min(elapsed / (duration * 0.25), 1)).toFixed(6);
    context.fillStyle = "rgba(219,226,232,0.9)";
    context.font = "600 24px 'Segoe UI', system-ui, sans-serif";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText("Divergence Meter: " + reading + "%", width / 2, height / 2 - 56);
    context.fillStyle = "rgba(242,175,64,0.95)";
    context.font = "600 32px 'Segoe UI', system-ui, sans-serif";
    context.fillText("Reading Steiner.", width / 2, height / 2 - 20);
    const unverifiedCells = unverified;
    context.fillStyle = "rgba(219,226,232,0.85)";
    context.font = "15px 'Segoe UI', system-ui, sans-serif";
    context.fillText(
      unverifiedCells === 0
        ? "Every coverage dimension carries reviewed evidence. The observer sees a converged corpus."
        : unverifiedCells + " of " + total + " coverage dimensions await reviewed evidence. The observer sees the work that remains.",
      width / 2, height / 2 + 14
    );

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
