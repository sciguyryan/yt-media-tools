(function () {
  const WORDS = ["El", "Psy", "Kongroo"];
  const TAGLINE = "All worldlines converge. The corpus is in conformance everywhere the organisation can observe.";
  const canvas = document.createElement("canvas");
  canvas.style.cssText = "position:fixed;inset:0;z-index:9999;background:#070b10;cursor:pointer";
  document.body.append(canvas);
  const context = canvas.getContext("2d");
  const started = performance.now();
  const duration = 10000;
  let raf = 0;

  // A prideful spectrum for the worldlines: bright, varied and unashamed.
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

  function worldline(seed, progress, width, height) {
    // Fan of divergent worldlines on the left, converging on the right toward
    // the single bright line at zero divergence.
    const spread = (seed - 9) / 9;
    const wobble = Math.sin(progress * 6 + seed * 1.7) * 40 * (1 - progress);
    const y1 = height / 2 + spread * height * 0.38 + wobble;
    const y2 = height / 2 + spread * height * 0.02;
    const mid = width * (0.35 + 0.25 * (1 - progress));
    context.beginPath();
    context.moveTo(0, y1);
    context.bezierCurveTo(mid, y1, mid, y2, width, y2);
    return context;
  }

  function frame(now) {
    const elapsed = now - started;
    const progress = Math.min(elapsed / duration, 1);
    const width = window.innerWidth;
    const height = window.innerHeight;
    context.fillStyle = "#070b10";
    context.fillRect(0, 0, width, height);

    for (let seed = 0; seed < 19; seed += 1) {
      const [red, green, blue] = PALETTE[seed % PALETTE.length];
      // A slow, shallow pulse keeps the spectrum alive without strobing, and
      // per-line shadow glow is omitted: 19 blurred strokes per frame exceed
      // the frame budget and read as flicker.
      const alpha = 0.55 + 0.08 * Math.sin(elapsed / 900 + seed * 1.3);
      context.strokeStyle = `rgba(${red},${green},${blue},${alpha})`;
      context.lineWidth = 1.6;
      worldline(seed, Math.min(progress * 1.4, 1), width, height);
      context.stroke();
    }
    context.shadowBlur = 0;

    // The converged line at zero divergence, drawn as a full spectrum.
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

    const meter = (1 - Math.min(progress * 1.2, 1)).toFixed(6);
    context.fillStyle = "rgba(219,226,232,0.9)";
    context.font = "600 26px 'Segoe UI', system-ui, sans-serif";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText("Divergence Meter: " + meter + "%", width / 2, height / 2 - 64);

    // The incantation at the exact centre, spoken word by word: each word
    // fades in on its own beat, in the order the observer says it.
    context.font = "600 44px 'Segoe UI', system-ui, sans-serif";
    const wordAlphas = WORDS.map((_, index) => {
      const onset = 0.5 + index * 0.1;
      return Math.max(0, Math.min((progress - onset) / 0.06, 1));
    });
    const widths = WORDS.map((word) => context.measureText(word + (word === WORDS[WORDS.length - 1] ? "" : " ")).width);
    const spacing = WORDS.map((word, index) => (index < WORDS.length - 1 ? " " : ""));
    const totalWidth = widths.reduce((sum, value) => sum + value, 0);
    let cursor = width / 2 - totalWidth / 2;
    WORDS.forEach((word, index) => {
      const wordWidth = context.measureText(word).width;
      if (wordAlphas[index] > 0) {
        context.fillStyle = `rgba(242,175,64,${wordAlphas[index]})`;
        context.shadowColor = "rgba(242,175,64,0.7)";
        context.shadowBlur = 12 * wordAlphas[index];
        context.textAlign = "left";
        context.fillText(word, cursor, height / 2);
        context.shadowBlur = 0;
      }
      cursor += widths[index];
    });
    context.textAlign = "center";

    if (wordAlphas[WORDS.length - 1] >= 1) {
      const taglineAlpha = Math.min((progress - 0.7) / 0.15, 1);
      context.fillStyle = `rgba(219,226,232,${0.85 * taglineAlpha})`;
      context.font = "16px 'Segoe UI', system-ui, sans-serif";
      context.fillText(TAGLINE, width / 2, height / 2 + 52);
    }

    if (progress < 1) {
      raf = requestAnimationFrame(frame);
    } else {
      finish();
    }
  }

  function finish() {
    cancelAnimationFrame(raf);
    window.removeEventListener("resize", resize);
    canvas.remove();
  }

  canvas.addEventListener("click", finish);
  document.addEventListener("keydown", function onKey(event) {
    if (event.key === "Escape") {
      document.removeEventListener("keydown", onKey);
      finish();
    }
  });
  raf = requestAnimationFrame(frame);
})();
