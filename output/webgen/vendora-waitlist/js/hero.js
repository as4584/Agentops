/* Vendora Hero — Pretext Particle Animation
   Particles scatter then coalesce into the headline text.
   Based on Agentop pretext-hero v2 pattern. */
'use strict';

(function () {
  const canvas = document.getElementById('heroCanvas');
  if (!canvas || typeof Pretext === 'undefined') return;
  const ctx = canvas.getContext('2d');

  const HEADLINE = 'Resell Smarter. Not Harder.';
  const NUM_P = 500;
  const SETTLE_MS = 2400;
  const ACCENT = '#6c5ce7';
  const ACCENT_RGB = [108, 92, 231];

  const mouse = { x: -9999, y: -9999 };
  let particles = [];
  let ambientPts = [];
  let wordPositions = [];
  let fontStr = '';
  let lineH = 0;
  let settled = false;
  let settleTime = 0;
  let startTime = 0;
  let textAlpha = 0;

  function fontSize() { return Math.max(22, Math.min(56, window.innerWidth * 0.042)); }
  function heroFont() { fontStr = `800 ${fontSize()}px Inter,-apple-system,sans-serif`; return fontStr; }
  function lh() { lineH = Math.round(fontSize() * 1.14); return lineH; }
  function resize() { canvas.width = window.innerWidth; canvas.height = window.innerHeight; }

  function computeWordPositions() {
    const f = heroFont();
    const lhpx = lh();
    const maxW = Math.min(canvas.width * 0.72, 800);
    let lines;
    try {
      const prep = Pretext.prepareWithSegments(HEADLINE, f);
      const result = Pretext.layoutWithLines(prep, maxW, lhpx);
      lines = result.lines;
    } catch {
      // Fallback if pretext APIs differ
      lines = [{ text: HEADLINE, width: ctx.measureText(HEADLINE).width }];
    }

    const offsetX = (canvas.width - maxW) / 2;
    const offsetY = Math.max(80, (canvas.height - lines.length * lhpx) / 2 - lhpx * 0.3);

    ctx.font = f;
    const wps = [];
    lines.forEach(function (line, li) {
      const words = line.text.trim().split(/\s+/).filter(Boolean);
      if (!words.length) return;
      const wws = words.map(function (w) { return ctx.measureText(w).width; });
      const total = wws.reduce(function (a, b) { return a + b; }, 0);
      const gap = words.length > 1 ? (line.width - total) / (words.length - 1) : 0;
      const lineX = offsetX + (maxW - line.width) / 2;
      var cx = lineX;
      words.forEach(function (w, wi) {
        wps.push({ text: w, x: cx, y: offsetY + li * lhpx, w: wws[wi], h: lhpx });
        cx += wws[wi] + gap;
      });
    });
    return wps;
  }

  function rasterTargets() {
    const off = document.createElement('canvas');
    off.width = canvas.width;
    off.height = canvas.height;
    const oc = off.getContext('2d');
    oc.font = fontStr;
    oc.fillStyle = '#fff';
    oc.textBaseline = 'top';
    wordPositions.forEach(function (wp) { oc.fillText(wp.text, wp.x, wp.y); });
    const id = oc.getImageData(0, 0, off.width, off.height);
    const pts = [];
    const step = 3;
    for (var y = 0; y < off.height; y += step) {
      for (var x = 0; x < off.width; x += step) {
        if (id.data[(y * off.width + x) * 4 + 3] > 128) {
          pts.push({ x: x, y: y });
        }
      }
    }
    return pts;
  }

  function init() {
    resize();
    wordPositions = computeWordPositions();
    const targets = rasterTargets();
    if (!targets.length) return;

    particles = [];
    for (var i = 0; i < NUM_P; i++) {
      var t = targets[Math.floor(Math.random() * targets.length)];
      particles.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        tx: t.x,
        ty: t.y,
        vx: 0,
        vy: 0,
        size: 1.2 + Math.random() * 1.8,
        alpha: 0.4 + Math.random() * 0.6
      });
    }

    // Ambient floating dots
    ambientPts = [];
    for (var j = 0; j < 60; j++) {
      ambientPts.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        r: 0.5 + Math.random() * 1.2,
        dx: (Math.random() - 0.5) * 0.3,
        dy: (Math.random() - 0.5) * 0.3,
        alpha: 0.08 + Math.random() * 0.12
      });
    }

    settled = false;
    textAlpha = 0;
    startTime = performance.now();
    settleTime = 0;
  }

  function frame(now) {
    requestAnimationFrame(frame);
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    var elapsed = now - startTime;
    var allClose = true;

    // Ambient
    ambientPts.forEach(function (p) {
      p.x += p.dx;
      p.y += p.dy;
      if (p.x < 0 || p.x > canvas.width) p.dx *= -1;
      if (p.y < 0 || p.y > canvas.height) p.dy *= -1;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(' + ACCENT_RGB.join(',') + ',' + p.alpha + ')';
      ctx.fill();
    });

    // Particles
    particles.forEach(function (p) {
      var dx = p.tx - p.x;
      var dy = p.ty - p.y;
      var dist = Math.sqrt(dx * dx + dy * dy);

      // Mouse repulsion
      var mx = p.x - mouse.x;
      var my = p.y - mouse.y;
      var md = Math.sqrt(mx * mx + my * my);
      if (md < 100 && !settled) {
        p.vx += (mx / md) * 3;
        p.vy += (my / md) * 3;
      }

      // Spring
      var spring = settled ? 0.12 : 0.06;
      p.vx += dx * spring;
      p.vy += dy * spring;
      p.vx *= 0.88;
      p.vy *= 0.88;
      p.x += p.vx;
      p.y += p.vy;

      if (dist > 2) allClose = false;

      var a = settled ? Math.max(0, p.alpha * (1 - textAlpha)) : p.alpha;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(' + ACCENT_RGB.join(',') + ',' + a + ')';
      ctx.fill();
    });

    // Force settle after timeout
    if (!settled && (allClose || elapsed > SETTLE_MS)) {
      settled = true;
      settleTime = now;
    }

    // Fade in crisp text
    if (settled) {
      textAlpha = Math.min(1, (now - settleTime) / 800);
      ctx.globalAlpha = textAlpha;
      ctx.font = fontStr;
      ctx.fillStyle = '#fff';
      ctx.textBaseline = 'top';
      wordPositions.forEach(function (wp) { ctx.fillText(wp.text, wp.x, wp.y); });
      ctx.globalAlpha = 1;
    }
  }

  canvas.addEventListener('mousemove', function (e) { mouse.x = e.clientX; mouse.y = e.clientY; });
  canvas.addEventListener('mouseleave', function () { mouse.x = -9999; mouse.y = -9999; });
  window.addEventListener('resize', function () { init(); });

  // Hide the HTML headline once canvas is active
  var hl = document.getElementById('heroHeadline');
  if (hl) hl.style.opacity = '0';

  init();
  requestAnimationFrame(frame);
})();
