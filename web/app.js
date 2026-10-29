'use strict';
/* Baseline Shot Lab — local player app.
   Talks only to the loopback API in web_app.py. Machine proposals stay separate
   from human review; no outcome, metric or cue is invented in the browser. */

const MAX_VIDEO_BYTES = 250 * 1024 * 1024;
const PLAYER_ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;
const LABELS = {
  camera_view: {side_90: 'side view', oblique_45: 'angled view', frontal: 'front view', rear: 'view from behind'},
  shot_type: {catch_and_shoot: 'catch and shoot', off_dribble: 'off the dribble', free_throw: 'free throw'},
  shot_style: {jump_shot: 'jump shot', set_shot: 'set shot'},
  review_status: {quarantined: 'Needs review', approved: 'Approved', discarded: 'Discarded'},
  outcome: {unknown: 'Outcome unknown', make: 'Make', miss: 'Miss'},
};
const PHASES = [['start', 'Load'], ['dip', 'Dip'], ['set', 'Set'], ['release', 'Release'], ['end', 'Follow-through']];

const $ = selector => document.querySelector(selector);
const form = $('#upload-form');
const fileInput = $('#video-file');
const fileTitle = $('#file-title');
const fileCaption = $('#file-caption');
const dropzone = $('#dropzone');
const submitButton = $('#submit-button');
const formError = $('#form-error');
const playerIdInput = form.elements.player_id;
const reviewEmpty = $('#review-empty');
const jobPanel = $('#job-panel');
const jobTitle = $('#job-title');
const jobBadge = $('#job-badge');
const jobMessage = $('#job-message');
const jobProgress = $('#job-progress');
const progressBar = $('#progress-bar');
const progressLabel = $('#progress-label');
const errorText = $('#job-error');
const results = $('#results');
const sessionContext = $('#session-context');
const navReviewCount = $('#nav-review-count');
const progressPlayer = $('#progress-player');
const weeklyTarget = $('#weekly-target');
const historyOverview = $('#history-overview');
const historySummary = $('#history-summary');
const historyPlan = $('#history-plan');
const historyList = $('#history-list');
const historyCharts = $('#history-charts');
const cameraPreview = $('#camera-preview');
const cameraOverlay = $('#camera-overlay');
const cameraStatus = $('#camera-status');
const cameraStartButton = $('#camera-start');
const cameraStopButton = $('#camera-stop');
const recordStartButton = $('#record-start');
const recordStopButton = $('#record-stop');
const hudPanierLive = $('#hud-panier-live');
const hudPicMax = $('#hud-pic-max');
const hudKneeVal = $('#hud-knee-val');
const hudElbowVal = $('#hud-elbow-val');
const hudPhaseText = $('#hud-phase-text');
const hudHoopDot = $('#hud-hoop-dot');
const hudHoopText = $('#hud-hoop-text');
const hudMakesCount = $('#hud-makes-count');
const hudMissesCount = $('#hud-misses-count');
const hudAccVal = $('#hud-acc-val');
const hudRecalibrateBtn = $('#hud-recalibrate-btn');
const hudFinishBtn = $('#hud-finish-btn');
const hudBtnClose = $('#hud-btn-close');
const hudBtnSkeleton = $('#hud-btn-skeleton');
const hudOutcomeBanner = $('#hud-outcome-banner');
const hudOutcomeText = $('#hud-outcome-text');
let liveShowSkeleton = true;
const cancelButton = $('#cancel-job');
const reportRoot = $('#report-root');
const reportEmpty = $('#report-empty');
const reportStatus = $('#report-status');
const reportPrint = $('#report-print');
const reportRefresh = $('#report-refresh');

let pollingTimer = null;
let activeJobId = null;
let activeSessionId = null;
let cameraStream = null;
let mediaRecorder = null;
let recordedChunks = [];
let recordingSize = 0;
let healthInfo = null;
let liveTrackingActive = false;
let liveProcessing = false;
let liveLoopTimer = null;
let liveOutcomeTimer = null;
let lastReportedShotTotal = 0;
const liveCaptureCanvas = document.createElement('canvas');
const liveCaptureCtx = liveCaptureCanvas.getContext('2d');
let reportSessionId = null;
let currentReport = null;
let refreshReturnJob = null;
let pendingSeek = null;     // {time, attempt} to apply once the replay for a session is ready
let reviewApi = null;       // seek/select helpers of the open Review screen

/* ------------------------------------------------------------------ helpers */
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}
const iconEl = (id, extraClass = '') => {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', `icon ${extraClass}`.trim());
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#${id}`);
  svg.append(use);
  return svg;
};
const svgEl = (tag, attrs = {}) => {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
};

async function api(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const headers = {...(options.headers || {})};
  if (method !== 'GET') headers['X-Shotlab'] = '1';  // server-side CSRF guard
  let response;
  try {
    response = await fetch(path, {cache: 'no-store', ...options, headers});
  } catch {
    const error = new Error('Could not reach Shot Lab. Check that the app is still running on the computer and that this device is on the same network.');
    error.status = 0;
    throw error;
  }
  let payload = {};
  try { payload = await response.json(); } catch { payload = {}; }
  if (!response.ok) {
    const error = new Error(payload.error || `Request failed (${response.status})`);
    error.status = response.status;
    if (payload.code) error.code = payload.code;
    throw error;
  }
  return payload;
}
const jsonBody = (method, body) => ({method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});

/* ------------------------------------------------------------- motion layer
   Uses Motion (motion.dev, vendored in report.js as window.Motion). Everything here is
   progressive enhancement: without Motion, or with prefers-reduced-motion, elements are
   shown in their final state immediately. Only opacity/transform are animated, except a
   few single-element widths (nav indicator) and SVG attributes. */
const Motion = window.Motion || null;
const reducedMotionQuery = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
const motionOn = () => Boolean(Motion) && !(reducedMotionQuery && reducedMotionQuery.matches);
const EASE_OUT = [0.22, 1, 0.36, 1];
const SPRING = {type: 'spring', stiffness: 380, damping: 32, mass: 1};
const SOFT_SPRING = {type: 'spring', stiffness: 220, damping: 26};

function enter(nodes, {y = 14, delay = 0, stagger = 0.05, duration = 0.5} = {}) {
  const list = [...(nodes || [])].filter(node => node && node.nodeType === 1);
  if (!list.length || !motionOn()) return;
  Motion.animate(list, {opacity: [0, 1], y: [y, 0]},
    {duration, ease: EASE_OUT, delay: Motion.stagger(stagger, {startDelay: delay})});
}

// amount 'some': a report section can be many screens tall, so a fractional threshold
// (e.g. 15% visible) may never be reached and the section would stay hidden.
function revealOnScroll(nodes, {y = 18, amount = 'some'} = {}) {
  if (!motionOn()) return;
  for (const node of nodes || []) {
    if (!node || node.dataset.revealed) continue;
    node.dataset.revealed = '1';
    node.setAttribute('data-motion-hidden', '');
    node.style.opacity = '0';
    const stop = Motion.inView(node, () => {
      node.removeAttribute('data-motion-hidden');
      Motion.animate(node, {opacity: [0, 1], y: [y, 0]}, {duration: 0.6, ease: EASE_OUT});
      stop();
    }, {amount});
  }
}
// Never leave content hidden in a printout.
window.addEventListener('beforeprint', () => {
  for (const node of document.querySelectorAll('[data-motion-hidden]')) {
    node.removeAttribute('data-motion-hidden');
    node.style.opacity = '';
    node.style.transform = '';
  }
});

function countUp(node, to, {duration = 0.9, format = v => Math.round(v).toLocaleString()} = {}) {
  if (!node) return;
  if (!motionOn() || !Number.isFinite(Number(to))) { node.textContent = format(Number(to) || 0); return; }
  Motion.animate(0, Number(to), {duration, ease: EASE_OUT, onUpdate: value => { node.textContent = format(value); }});
}

function pop(node) {
  if (node && motionOn()) Motion.animate(node, {scale: [1.35, 1]}, SPRING);
}

let toastTimer = null;
function toast(message) {
  const node = $('#toast');
  node.textContent = message;
  node.classList.add('show');
  clearTimeout(toastTimer);
  if (motionOn()) Motion.animate(node, {opacity: [0, 1], y: [18, 0], scale: [0.96, 1]}, SPRING);
  toastTimer = setTimeout(() => {
    if (motionOn()) {
      Motion.animate(node, {opacity: 0, y: 10}, {duration: 0.2, ease: EASE_OUT}).then(() => node.classList.remove('show'));
    } else node.classList.remove('show');
  }, 3600);
}

/* Nav indicator and segmented-control thumb glide between items with a spring. */
function moveNavIndicator(animateIt = true) {
  // The same nav is a vertical sidebar, an icon rail or a bottom tab bar depending on width,
  // so the active pill follows the link in both directions.
  const indicator = document.querySelector('.nav-indicator');
  const current = document.querySelector('.view-nav a[aria-current="page"]');
  if (!indicator || !current) return;
  const box = {x: current.offsetLeft, y: current.offsetTop, width: current.offsetWidth, height: current.offsetHeight};
  if (Motion) {
    const shown = indicator.style.opacity === '1';
    indicator.style.opacity = '1';
    Motion.animate(indicator, box, animateIt && shown && motionOn() ? SPRING : {duration: 0});
  } else {
    Object.assign(indicator.style, {width: `${box.width}px`, height: `${box.height}px`, transform: `translate(${box.x}px, ${box.y}px)`, opacity: '1'});
  }
}
window.addEventListener('resize', () => moveNavIndicator(false));

function moveSegmentThumb(animateIt = true) {
  const group = document.querySelector('.segmented');
  const thumb = group?.querySelector('.segmented-thumb');
  const selected = group?.querySelector('[aria-selected="true"]');
  if (!thumb || !selected) return;
  group.classList.add('has-thumb');
  const x = selected.offsetLeft - 4;
  thumb.style.width = `${selected.offsetWidth}px`;
  if (Motion) Motion.animate(thumb, {x}, animateIt && motionOn() ? SPRING : {duration: 0});
  else thumb.style.transform = `translateX(${x}px)`;
}
window.addEventListener('resize', () => moveSegmentThumb(false));

/* Accordion: animate <details> height open/closed (shadcn accordion behaviour). */
const ACCORDIONS = 'details.manual-attempt, details.review-history, details.measure-details';
document.addEventListener('click', event => {
  const summary = event.target.closest('summary');
  const details = summary?.parentElement;
  if (!details || !details.matches(ACCORDIONS) || !motionOn()) return;
  event.preventDefault();
  let body = details.querySelector(':scope > .accordion-body');
  if (!body) {
    body = document.createElement('div');
    body.className = 'accordion-body';
    while (summary.nextSibling) body.append(summary.nextSibling);
    details.append(body);
  }
  if (details.open) {
    Motion.animate(body, {height: [`${body.scrollHeight}px`, '0px'], opacity: [1, 0]}, {duration: 0.22, ease: EASE_OUT})
      .then(() => { details.open = false; body.style.height = ''; body.style.opacity = ''; });
  } else {
    details.open = true;
    Motion.animate(body, {height: ['0px', `${body.scrollHeight}px`], opacity: [0, 1]}, {duration: 0.3, ease: EASE_OUT})
      .then(() => { body.style.height = ''; });
  }
});

/* Tooltip for any element with data-tip (shadcn tooltip behaviour: delay, side flip, arrow). */
const tooltip = $('#tooltip');
let tooltipTimer = null;
let tooltipTarget = null;
function showTooltip(target) {
  tooltipTarget = target;
  tooltip.textContent = target.dataset.tip;
  tooltip.hidden = false;
  const rect = target.getBoundingClientRect();
  const tip = tooltip.getBoundingClientRect();
  const above = rect.top > tip.height + 14;
  const left = Math.min(window.innerWidth - tip.width - 8, Math.max(8, rect.left + rect.width / 2 - tip.width / 2));
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${above ? rect.top - tip.height - 10 : rect.bottom + 10}px`;
  tooltip.style.setProperty('--arrow-x', `${rect.left + rect.width / 2 - left}px`);
  tooltip.dataset.side = above ? 'top' : 'bottom';
  if (motionOn()) Motion.animate(tooltip, {opacity: [0, 1], y: [above ? 4 : -4, 0], scale: [0.96, 1]}, {duration: 0.16, ease: EASE_OUT});
}
function hideTooltip() {
  clearTimeout(tooltipTimer);
  tooltipTarget = null;
  tooltip.hidden = true;
}
document.addEventListener('pointerover', event => {
  const target = event.target.closest?.('[data-tip]');
  if (!target || target === tooltipTarget) return;
  clearTimeout(tooltipTimer);
  tooltipTimer = setTimeout(() => showTooltip(target), 180);
});
document.addEventListener('pointerout', event => {
  if (event.target.closest?.('[data-tip]') && !event.relatedTarget?.closest?.('[data-tip]')) hideTooltip();
});
document.addEventListener('focusin', event => { const t = event.target.closest?.('[data-tip]'); if (t) showTooltip(t); });
document.addEventListener('focusout', hideTooltip);
document.addEventListener('keydown', event => { if (event.key === 'Escape') hideTooltip(); });
window.addEventListener('scroll', hideTooltip, {passive: true});

/* Alert dialog (shadcn alert-dialog): focus moves to Cancel, Tab is trapped, Esc cancels. */
function confirmDialog({title, description, confirmLabel = 'Delete'}) {
  const root = $('#confirm-dialog');
  const dialog = root.querySelector('.dialog');
  const overlay = root.querySelector('.dialog-overlay');
  const confirm = $('#dialog-confirm');
  const cancel = root.querySelector('button[data-dialog-cancel]');
  const opener = document.activeElement;
  $('#dialog-title').textContent = title;
  $('#dialog-desc').textContent = description;
  confirm.textContent = confirmLabel;
  root.hidden = false;
  document.body.classList.add('dialog-open');
  if (motionOn()) {
    Motion.animate(overlay, {opacity: [0, 1]}, {duration: 0.2});
    Motion.animate(dialog, {opacity: [0, 1], scale: [0.95, 1], y: [8, 0]}, SPRING);
  }
  cancel.focus();
  return new Promise(resolve => {
    const close = async result => {
      root.removeEventListener('click', onClick);
      root.removeEventListener('keydown', onKey);
      if (motionOn()) {
        await Promise.all([
          Motion.animate(overlay, {opacity: 0}, {duration: 0.15}),
          Motion.animate(dialog, {opacity: 0, scale: 0.97}, {duration: 0.15, ease: EASE_OUT}),
        ]);
      }
      root.hidden = true;
      document.body.classList.remove('dialog-open');
      if (opener && opener.focus) opener.focus();
      resolve(result);
    };
    const onClick = event => {
      if (event.target.closest('[data-dialog-cancel]')) close(false);
      else if (event.target.closest('#dialog-confirm')) close(true);
    };
    const onKey = event => {
      if (event.key === 'Escape') { event.preventDefault(); close(false); }
      if (event.key === 'Tab') {
        const items = [cancel, confirm];
        const index = items.indexOf(document.activeElement);
        event.preventDefault();
        items[(index + (event.shiftKey ? -1 : 1) + items.length) % items.length].focus();
      }
    };
    root.addEventListener('click', onClick);
    root.addEventListener('keydown', onKey);
  });
}

function skeleton(...kinds) {
  return el('div', {class: 'skeleton-wrap', 'aria-hidden': 'true'},
    kinds.map(kind => el('span', {class: `skeleton skeleton-${kind}`})));
}

/* Hero: one orchestrated moment — tags appear, the ball travels the shot arc to the rim
   and leaves measured points behind; then gentle scroll parallax on the court layers. */
function playHero() {
  const arc = document.getElementById('hero-arc');
  const ball = document.getElementById('hero-ball');
  const marks = document.getElementById('hero-marks');
  if (!arc || !ball || !marks) return;
  const length = arc.getTotalLength();
  const stops = [0.12, 0.28, 0.44, 0.6, 0.76];
  marks.replaceChildren();
  const svgNS = 'http://www.w3.org/2000/svg';
  const dots = stops.map(t => {
    const point = arc.getPointAtLength(length * t);
    const dot = document.createElementNS(svgNS, 'circle');
    dot.setAttribute('cx', point.x.toFixed(1));
    dot.setAttribute('cy', point.y.toFixed(1));
    dot.setAttribute('r', '4.5');
    marks.append(dot);
    return {dot, t};
  });
  const end = arc.getPointAtLength(length);
  if (!motionOn()) {
    ball.setAttribute('cx', end.x.toFixed(1));
    ball.setAttribute('cy', (end.y - 4).toFixed(1));
    return;
  }
  const tags = [...document.querySelectorAll('.hero-tag')];
  // SVG elements: Motion animates opacity as an attribute, so hide them the same way.
  for (const node of [...tags, ...dots.map(d => d.dot)]) node.setAttribute('opacity', '0');
  Motion.animate(tags, {opacity: [0, 1]}, {duration: 0.45, ease: EASE_OUT, delay: Motion.stagger(0.14, {startDelay: 0.25})});
  Motion.animate(arc, {opacity: [0, 1], strokeDashoffset: [36, 0]}, {duration: 1.4, ease: EASE_OUT, delay: 0.3});
  Motion.animate(0, 1, {
    duration: 1.35, delay: 0.55, ease: [0.45, 0.05, 0.55, 0.95],
    onUpdate: t => {
      const point = arc.getPointAtLength(length * t);
      ball.setAttribute('cx', point.x.toFixed(2));
      ball.setAttribute('cy', point.y.toFixed(2));
      for (const item of dots) {
        if (!item.shown && t >= item.t) {
          item.shown = true;
          Motion.animate(item.dot, {opacity: [0, 1], scale: [0.2, 1]}, SPRING);
        }
      }
    },
  }).then(() => Motion.animate(ball, {cy: [end.y, end.y + 26, end.y + 18]}, {duration: 0.45, ease: EASE_OUT}));
}

function setupHeroParallax() {
  const stage = document.querySelector('.hero-stage');
  if (!stage || !motionOn() || !Motion.scroll) return;
  const layers = [...stage.querySelectorAll('.hero-layer')];
  Motion.scroll(progress => {
    for (const layer of layers) {
      const depth = Number(layer.dataset.depth || 1);
      layer.style.transform = `translateY(${(-28 * depth * progress).toFixed(2)}px)`;
    }
  }, {target: stage, offset: ['start start', 'end start']});
  let lastReplay = 0;
  stage.addEventListener('pointerenter', () => {
    if (Date.now() - lastReplay > 4000) { lastReplay = Date.now(); playHero(); }
  });
}

/* Top bar gains a soft shadow once the page scrolls. */
let scrollTicking = false;
window.addEventListener('scroll', () => {
  if (scrollTicking) return;
  scrollTicking = true;
  requestAnimationFrame(() => {
    document.querySelector('.topbar')?.classList.toggle('is-scrolled', window.scrollY > 8);
    scrollTicking = false;
  });
}, {passive: true});

/* ---------------------------------------------------------------- theme
   Light and dark palettes live in app.css as tokens. With no saved choice the OS setting
   wins (pure CSS); an explicit choice is stored in this browser only and applied before
   first paint by the small bootstrap in report.js. */
const THEME_KEY = 'shotLabTheme';
const THEME_BG = {light: '#f5f4f1', dark: '#0b0d10'};
const themeToggle = $('#theme-toggle');
const darkQuery = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
function currentTheme() {
  const chosen = document.documentElement.dataset.theme;
  if (chosen === 'light' || chosen === 'dark') return chosen;
  return darkQuery && darkQuery.matches ? 'dark' : 'light';
}
function syncThemeUi() {
  const theme = currentTheme();
  const label = theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme';
  themeToggle.setAttribute('aria-label', label);
  themeToggle.title = label;
  const metas = [...document.querySelectorAll('meta[name="theme-color"]')];
  if (document.documentElement.dataset.theme && metas.length) {
    metas.slice(1).forEach(meta => meta.remove());
    metas[0].removeAttribute('media');
    metas[0].setAttribute('content', THEME_BG[theme]);
  }
}
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  storage('set', THEME_KEY, theme);
  syncThemeUi();
}
themeToggle.addEventListener('click', () => {
  const next = currentTheme() === 'dark' ? 'light' : 'dark';
  const root = document.documentElement;
  if (motionOn() && document.startViewTransition) {
    // Circular reveal from the toggle (View Transitions API), Chromium and Safari 18+.
    const rect = themeToggle.getBoundingClientRect();
    const x = rect.left + rect.width / 2, y = rect.top + rect.height / 2;
    const radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
    const transition = document.startViewTransition(() => applyTheme(next));
    transition.ready.then(() => root.animate(
      {clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`]},
      {duration: 560, easing: 'cubic-bezier(.22, 1, .36, 1)', pseudoElement: '::view-transition-new(root)'})).catch(() => {});
  } else if (motionOn()) {
    root.classList.add('theme-anim');
    applyTheme(next);
    setTimeout(() => root.classList.remove('theme-anim'), 420);
  } else {
    applyTheme(next);
  }
  if (motionOn()) Motion.animate(themeToggle, {rotate: [0, next === 'dark' ? -20 : 20, 0]}, {duration: 0.5, ease: EASE_OUT});
});
darkQuery?.addEventListener?.('change', syncThemeUi);

function storage(action, key, value) {
  try {
    if (action === 'get') return localStorage.getItem(key);
    if (action === 'set') localStorage.setItem(key, value);
    if (action === 'remove') localStorage.removeItem(key);
  } catch { /* storage can be unavailable; the app works without it */ }
  return null;
}

function formatDate(value) {
  if (!value) return 'Unknown date';
  const iso = value.includes('T') ? value : `${value.replace(' ', 'T')}Z`;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'});
}
function describeContext(context = {}) {
  const view = LABELS.camera_view[context.camera_view] || context.camera_view || 'unknown view';
  const type = LABELS.shot_type[context.shot_type] || context.shot_type || 'unknown shot type';
  const style = LABELS.shot_style[context.shot_style] || context.shot_style || 'unknown style';
  return `${view}, ${type}, ${style}`;
}
const fmt = (value, digits = 1) => Number(value).toFixed(digits).replace(/\.0+$/, '');
const frameOf = (shot, key) => shot[`annotated_${key}_frame`] ?? shot[`machine_${key}_frame`];
const mmss = seconds => {
  if (seconds == null || !Number.isFinite(Number(seconds))) return '—';
  const m = Math.floor(seconds / 60);
  return `${m}:${(seconds - m * 60).toFixed(2).padStart(5, '0')}`;
};

/* ------------------------------------------------------------------ routing */
const VIEWS = ['new', 'review', 'report', 'workout', 'progress', 'drills'];
const VIEW_TITLES = {new: 'New session', review: 'Review', report: 'Report', workout: 'Workout', progress: 'Progress', drills: 'Drills'};
let currentView = null;
let workoutSessionId = null;  // the shooting session whose report a workout is built from
function setView(name, {push = true} = {}) {
  const view = VIEWS.includes(name) ? name : 'new';
  if (currentView === 'workout' && view !== 'workout') window.ShotLabWorkout?.hide();
  currentView = view;
  for (const section of document.querySelectorAll('[data-view]')) section.hidden = section.dataset.view !== view;
  for (const link of document.querySelectorAll('[data-nav]')) {
    if (link.dataset.nav === view) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  if (push && location.hash !== `#${view}`) history.replaceState(null, '', `#${view}`);
  const topbarTitle = document.getElementById('topbar-title');
  if (topbarTitle) topbarTitle.textContent = VIEW_TITLES[view];
  document.title = `${VIEW_TITLES[view]} · Baseline Shot Lab`;
  if (view === 'progress') loadPlayerHistory(progressPlayer.value || playerIdInput.value);
  if (view === 'report') showReport(reportSessionId || activeSessionId);
  if (view === 'workout') {
    workoutSessionId = workoutSessionId || storage('get', 'shotLabWorkoutSession') || reportSessionId || activeSessionId;
    // workout.js loads after app.js (both deferred); on the very first boot it may not exist yet.
    if (window.ShotLabWorkout) window.ShotLabWorkout.show(workoutSessionId);
    else window.addEventListener('DOMContentLoaded', () => window.ShotLabWorkout?.show(workoutSessionId), {once: true});
  }
  if (view === 'drills') initDrillsView();
  window.scrollTo({top: 0});
  moveNavIndicator();
  const section = document.querySelector(`[data-view="${view}"]`);
  if (section && section.dataset.lastShown !== '1') {
    for (const other of document.querySelectorAll('[data-view]')) other.dataset.lastShown = '';
    section.dataset.lastShown = '1';
    if (view === 'new') {
      enter(section.querySelectorAll('.hero-copy > *, .hero-stage'), {stagger: 0.07});
      enter(section.querySelectorAll('.setup-main > *, .setup-aside > :not(.hidden)'), {delay: 0.25, stagger: 0.08, y: 22});
      playHero();
    } else {
      enter([...section.children].filter(child => !child.hidden && !child.classList.contains('hidden')), {stagger: 0.06});
    }
  }
}
window.addEventListener('hashchange', () => setView(location.hash.slice(1), {push: false}));

/* -------------------------------------------------------------- video source */
for (const tab of document.querySelectorAll('[data-source]')) {
  tab.addEventListener('click', () => selectSource(tab.dataset.source));
  tab.addEventListener('keydown', event => {
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      const next = tab.dataset.source === 'file' ? 'camera' : 'file';
      selectSource(next);
      document.querySelector(`[data-source="${next}"]`).focus();
    }
  });
}
function selectSource(source) {
  for (const tab of document.querySelectorAll('[data-source]')) {
    const selected = tab.dataset.source === source;
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
  }
  $('#pane-file').hidden = source !== 'file';
  $('#pane-camera').hidden = source !== 'camera';
  moveSegmentThumb();
  enter([$(source === 'file' ? '#pane-file' : '#pane-camera')], {y: 8, duration: 0.35});
}

fileInput.addEventListener('change', () => {
  const file = fileInput.files?.[0];
  if (!file) return;
  fileTitle.textContent = file.name;
  fileCaption.textContent = `${(file.size / (1024 * 1024)).toFixed(1)} MB, ready to analyze`;
  dropzone.classList.add('has-file');
  formError.classList.add('hidden');
  pop(dropzone.querySelector('.drop-icon'));
});
for (const eventName of ['dragenter', 'dragover']) {
  dropzone.addEventListener(eventName, event => { event.preventDefault(); dropzone.classList.add('dragover'); });
}
for (const eventName of ['dragleave', 'drop']) {
  dropzone.addEventListener(eventName, event => { event.preventDefault(); dropzone.classList.remove('dragover'); });
}
dropzone.addEventListener('drop', event => {
  const file = event.dataTransfer?.files?.[0];
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  fileInput.files = transfer.files;
  fileInput.dispatchEvent(new Event('change'));
});

/* ---------------------------------------------------------- camera recorder
   Browsers expose the camera only in a secure context (https:// or http://localhost). On a phone
   that opens http://<computer IP>, navigator.mediaDevices is undefined, so we explain that instead
   of claiming the browser cannot record. States: off → live → recording ⇄ paused → review. */
const cameraReview = $('#camera-review');
const cameraIdle = $('#camera-idle');
const cameraViewport = $('#camera-viewport');
const cameraSecureNote = $('#camera-secure-note');
const recordPauseButton = $('#record-pause');
const recordRetakeButton = $('#record-retake');
const cameraSwitchButton = $('#camera-switch');
const recIndicator = $('#rec-indicator');
const recLabel = $('#rec-label');
const recTime = $('#rec-time');
const MAX_RECORDING_MS = 10 * 60 * 1000;   // the server accepts clips up to 10 minutes

let cameraState = 'off';          // off | starting | live | recording | paused | review
let recordedFile = null;          // the finished recording, used by "Analyze this session"
let recordedUrl = null;
let recordedMs = 0;
let recordTimer = null;
let recordSegmentStart = 0;
let videoInputs = [];
let currentDeviceId = null;
let currentFacing = 'environment';

function cameraCapabilities() {
  const secure = window.isSecureContext === true;
  const getUserMedia = !!(navigator.mediaDevices && typeof navigator.mediaDevices.getUserMedia === 'function');
  const recorder = typeof window.MediaRecorder === 'function';
  return {secure, getUserMedia, recorder,
          pause: recorder && typeof window.MediaRecorder.prototype.pause === 'function'};
}

/* Pick a format this browser can both record and play back for the preview:
   WebM (VP9/VP8) on Chrome, Edge, Firefox and Android; MP4 (H.264) on Safari/iOS. */
function pickRecordingType() {
  if (typeof MediaRecorder.isTypeSupported !== 'function') return '';
  const probe = document.createElement('video');
  const candidates = [
    ['video/webm;codecs=vp9', 'video/webm; codecs="vp9"'],
    ['video/webm;codecs=vp8', 'video/webm; codecs="vp8"'],
    ['video/mp4;codecs=avc1.42E01E', 'video/mp4; codecs="avc1.42E01E"'],
    ['video/mp4', 'video/mp4'],
    ['video/webm', 'video/webm'],
  ];
  for (const [recordType, playType] of candidates) {
    let ok = false;
    try { ok = MediaRecorder.isTypeSupported(recordType); } catch { ok = false; }
    if (ok && probe.canPlayType(playType) !== '') return recordType;
  }
  return '';
}

function formatClock(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

let lastCameraError = null;
async function renderCameraDiagnostics() {
  const list = $('#camera-diag-list');
  if (!list) return;
  const caps = cameraCapabilities();
  const types = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/mp4;codecs=avc1.42E01E', 'video/mp4'];
  const supported = caps.recorder && typeof MediaRecorder.isTypeSupported === 'function'
    ? types.filter(type => { try { return MediaRecorder.isTypeSupported(type); } catch { return false; } }) : [];
  let cameras = 'unknown (allow the camera first)';
  if (caps.getUserMedia && navigator.mediaDevices.enumerateDevices) {
    try { cameras = String((await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'videoinput').length); } catch { /* ignore */ }
  }
  const rows = [
    ['Page address', `${location.protocol}//${location.host}`],
    ['Secure context (needed for the camera)', caps.secure ? 'yes' : 'NO: open the https:// address'],
    ['Camera API (getUserMedia)', caps.getUserMedia ? 'available' : 'not available'],
    ['Recording API (MediaRecorder)', caps.recorder ? 'available' : 'not available'],
    ['Pause while recording', caps.pause ? 'supported' : 'not supported'],
    ['Recordable formats', supported.length ? supported.join(', ') : 'none reported'],
    ['Format that will be used', caps.recorder ? (pickRecordingType() || 'browser default') : '—'],
    ['Cameras found', cameras],
    ['Last camera error', lastCameraError || 'none'],
    ['Browser', navigator.userAgent],
  ];
  list.replaceChildren(...rows.flatMap(([term, value]) => [el('dt', {text: term}), el('dd', {text: value})]));
}
$('#camera-diagnostics')?.addEventListener('toggle', event => { if (event.target.open) renderCameraDiagnostics(); });

function cameraErrorMessage(error) {
  switch (error && error.name) {
    case 'NotAllowedError':
    case 'PermissionDeniedError':
      return 'Camera permission was blocked. Allow the camera for this site (Safari: the aA menu › Website Settings › Camera; Chrome: the icon left of the address › Permissions), then try again.';
    case 'NotFoundError':
    case 'DevicesNotFoundError':
      return 'No camera was found on this device.';
    case 'NotReadableError':
    case 'TrackStartError':
      return 'The camera is busy in another app or tab. Close it there and try again.';
    case 'SecurityError':
      return 'The browser blocked the camera because this page is not secure. Open the https:// address instead.';
    default:
      return `The camera could not start (${(error && (error.message || error.name)) || 'unknown error'}).`;
  }
}

function showInsecureNote() {
  const host = location.hostname;
  cameraSecureNote.replaceChildren(
    el('strong', {text: 'Camera recording needs a secure (https) connection. '}),
    document.createTextNode(`This page was opened at http://${host}, so the browser hides the camera. `),
    document.createTextNode('On the computer, restart Shot Lab with '),
    el('code', {text: 'python web_app.py --lan --https'}),
    document.createTextNode(' and open the https:// address it prints (README › “Phone camera over Wi-Fi”). '),
    document.createTextNode('Until then, record with the phone’s Camera app and choose Upload a file.'));
  cameraSecureNote.classList.remove('hidden');
}

function renderCameraControls() {
  const state = cameraState;
  const caps = cameraCapabilities();
  const show = (button, visible) => button.classList.toggle('hidden', !visible);
  show(cameraStartButton, state === 'off' || state === 'starting');
  cameraStartButton.disabled = state === 'starting';
  show(recordStartButton, state === 'live');
  recordStartButton.disabled = state !== 'live';
  show(recordPauseButton, (state === 'recording' || state === 'paused') && caps.pause);
  recordPauseButton.disabled = !(state === 'recording' || state === 'paused');
  recordPauseButton.textContent = state === 'paused' ? 'Resume' : 'Pause';
  recordPauseButton.setAttribute('aria-pressed', String(state === 'paused'));
  show(recordStopButton, state === 'recording' || state === 'paused');
  recordStopButton.disabled = !(state === 'recording' || state === 'paused');
  show(recordRetakeButton, state === 'review');
  show(cameraSwitchButton, state === 'live' && videoInputs.length > 1);
  cameraSwitchButton.disabled = state !== 'live';
  show(cameraStopButton, state !== 'off' && state !== 'starting');
  cameraStopButton.disabled = state === 'off' || state === 'starting';
  cameraViewport.classList.toggle('is-live', !!cameraStream && state !== 'review');
  cameraViewport.classList.toggle('is-review', state === 'review');
  cameraViewport.classList.toggle('is-recording', state === 'recording' || state === 'paused');
  cameraIdle.hidden = !!cameraStream || state === 'review';
  cameraPreview.classList.toggle('camera-live', !!cameraStream && state !== 'review');
  cameraReview.hidden = state !== 'review';
  recIndicator.classList.toggle('hidden', !(state === 'recording' || state === 'paused'));
  recIndicator.classList.toggle('is-paused', state === 'paused');
  recLabel.textContent = state === 'paused' ? 'PAUSED' : 'REC';
}

function updateRecordClock() {
  const running = cameraState === 'recording' ? performance.now() - recordSegmentStart : 0;
  const total = recordedMs + running;
  recTime.textContent = formatClock(total);
  if (total >= MAX_RECORDING_MS && cameraState === 'recording') {
    cameraStatus.textContent = 'Recording reached the 10-minute limit and was stopped.';
    stopRecording();
  }
}

function setPreviewAspect() {
  const w = cameraPreview.videoWidth, h = cameraPreview.videoHeight;
  if (w && h) cameraViewport.style.setProperty('--cam-ratio', `${w} / ${h}`);
}
cameraPreview.addEventListener('loadedmetadata', setPreviewAspect);
cameraPreview.addEventListener('resize', setPreviewAspect);

async function listVideoInputs() {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    videoInputs = devices.filter(device => device.kind === 'videoinput');
  } catch { videoInputs = []; }
}

function releaseStream() {
  stopLiveTracking();
  cameraStream?.getTracks().forEach(track => track.stop());
  cameraStream = null;
  cameraPreview.srcObject = null;
}

async function openCamera({deviceId = null, facing = currentFacing} = {}) {
  const quality = {width: {ideal: 1280}, height: {ideal: 720}, frameRate: {ideal: 30}};
  const attempts = deviceId
    ? [{video: {deviceId: {exact: deviceId}, ...quality}, audio: false}]
    : [{video: {facingMode: {ideal: facing}, ...quality}, audio: false}, {video: true, audio: false}];
  let lastError = null;
  for (const constraints of attempts) {
    try { return await navigator.mediaDevices.getUserMedia(constraints); }
    catch (error) {
      lastError = error;
      if (error.name !== 'OverconstrainedError' && error.name !== 'ConstraintNotSatisfiedError') break;
    }
  }
  throw lastError;
}

async function startCamera(options = {}) {
  const caps = cameraCapabilities();
  if (!caps.secure || !caps.getUserMedia) {
    if (!caps.secure) showInsecureNote();
    lastCameraError = caps.secure ? 'getUserMedia is not available in this browser' : 'Page is not a secure context (http://)';
    renderCameraDiagnostics();
    cameraStatus.textContent = caps.secure
      ? 'This browser does not give web pages camera access. Record with the Camera app and choose Upload a file.'
      : 'Camera recording is not available on this http:// address (see the note below). Uploading a file still works.';
    return;
  }
  if (!caps.recorder) {
    cameraStatus.textContent = 'This browser can show the camera but cannot record video in a web page. Update the browser, or record with the Camera app and choose Upload a file.';
    return;
  }
  cameraState = 'starting';
  renderCameraControls();
  cameraStatus.textContent = 'Waiting for camera permission…';
  try {
    const stream = await openCamera(options);
    releaseStream();
    cameraStream = stream;
    const track = stream.getVideoTracks()[0];
    const settings = track?.getSettings ? track.getSettings() : {};
    currentDeviceId = settings.deviceId || options.deviceId || null;
    if (settings.facingMode) currentFacing = settings.facingMode;
    track?.addEventListener('ended', () => {
      if (cameraStream !== stream) return;
      if (mediaRecorder && mediaRecorder.state !== 'inactive') stopRecording();
      releaseStream();
      if (cameraState !== 'review') cameraState = 'off';
      renderCameraControls();
      cameraStatus.textContent = 'The camera was turned off by the device (for example the screen locked or another app took it). Turn it on again to continue.';
    });
    cameraPreview.srcObject = stream;
    try { await cameraPreview.play(); } catch { /* autoplay is allowed for muted inline video; ignore */ }
    await listVideoInputs();
    cameraState = 'live';
    renderCameraControls();
    cameraStatus.textContent = 'Camera on. Frame your whole body and the ball, then start recording.';
    startLiveTracking();
  } catch (error) {
    cameraState = cameraStream ? 'live' : 'off';
    renderCameraControls();
    lastCameraError = `${error?.name || 'Error'}: ${error?.message || ''}`.trim();
    cameraStatus.textContent = `${cameraErrorMessage(error)} You can still upload a file.`;
    renderCameraDiagnostics();
  }
}

function discardRecording() {
  if (recordedUrl) URL.revokeObjectURL(recordedUrl);
  recordedUrl = null;
  recordedFile = null;
  cameraReview.removeAttribute('src');
  try { cameraReview.load(); } catch { /* ignore */ }
}

function startRecording() {
  if (!cameraStream || cameraState !== 'live') return;
  discardRecording();
  const mimeType = pickRecordingType();
  const options = {videoBitsPerSecond: 4_000_000};
  if (mimeType) options.mimeType = mimeType;
  try {
    mediaRecorder = new MediaRecorder(cameraStream, options);
  } catch (error) {
    try { mediaRecorder = new MediaRecorder(cameraStream); }
    catch (fallbackError) {
      cameraStatus.textContent = `Could not start recording (${fallbackError.message || 'unsupported format'}). Record with the Camera app and choose Upload a file.`;
      return;
    }
  }
  const recorder = mediaRecorder;
  recordedChunks = [];
  recordingSize = 0;
  recordedMs = 0;
  recorder.addEventListener('dataavailable', event => {
    if (!event.data || !event.data.size) return;
    recordingSize += event.data.size;
    recordedChunks.push(event.data);
    if (recordingSize > MAX_VIDEO_BYTES && recorder.state !== 'inactive') {
      cameraStatus.textContent = 'Recording reached the 250 MB limit and was stopped.';
      stopRecording();
    }
  });
  recorder.addEventListener('error', event => {
    lastCameraError = `MediaRecorder: ${event.error?.name || ''} ${event.error?.message || 'unknown error'}`.trim();
    cameraStatus.textContent = `Recording failed (${event.error?.message || 'unknown error'}). Open Camera diagnostics below for details.`;
  });
  recorder.addEventListener('stop', () => finishRecording(recorder));
  recorder.start(1000);
  recordSegmentStart = performance.now();
  clearInterval(recordTimer);
  recordTimer = setInterval(updateRecordClock, 250);
  cameraState = 'recording';
  renderCameraControls();
  updateRecordClock();
  cameraStatus.textContent = 'Recording… Shoot as usual. Stop when you are done.';
}

function togglePauseRecording() {
  if (!mediaRecorder) return;
  if (cameraState === 'recording' && mediaRecorder.state === 'recording') {
    mediaRecorder.pause();
    recordedMs += performance.now() - recordSegmentStart;
    cameraState = 'paused';
    cameraStatus.textContent = 'Recording paused. Resume to continue the same clip, or Stop to finish it.';
  } else if (cameraState === 'paused' && mediaRecorder.state === 'paused') {
    mediaRecorder.resume();
    recordSegmentStart = performance.now();
    cameraState = 'recording';
    cameraStatus.textContent = 'Recording…';
  }
  renderCameraControls();
  updateRecordClock();
}

function stopRecording() {
  if (!mediaRecorder || mediaRecorder.state === 'inactive') return;
  if (cameraState === 'recording') recordedMs += performance.now() - recordSegmentStart;
  clearInterval(recordTimer);
  recordTimer = null;
  recordStopButton.disabled = true;
  recordPauseButton.disabled = true;
  try { mediaRecorder.stop(); } catch { finishRecording(mediaRecorder); }
}

function finishRecording(recorder) {
  if (recorder !== mediaRecorder) return;
  clearInterval(recordTimer);
  recordTimer = null;
  const chunks = recordedChunks;
  if (!chunks.length) {
    cameraState = cameraStream ? 'live' : 'off';
    renderCameraControls();
    cameraStatus.textContent = 'Nothing was recorded. Try again.';
    return;
  }
  const type = (recorder.mimeType || chunks[0].type || 'video/webm').split(';')[0];
  const blob = new Blob(chunks, {type});
  const extension = type.includes('mp4') ? 'mp4' : 'webm';
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace('T', '-').slice(0, 15);
  recordedFile = new File([blob], `practice-${stamp}.${extension}`, {type});
  recordedUrl = URL.createObjectURL(blob);
  cameraReview.src = recordedUrl;
  cameraState = 'review';
  stopLiveTracking();
  renderCameraControls();
  const seconds = Math.round(recordedMs / 1000);
  if (blob.size > MAX_VIDEO_BYTES) {
    cameraStatus.textContent = `This recording is ${(blob.size / 1048576).toFixed(0)} MB, over the 250 MB limit. Retake a shorter clip.`;
  } else {
    cameraStatus.textContent = `Recording ready: ${formatClock(seconds * 1000)}, ${(blob.size / 1048576).toFixed(1)} MB (${extension.toUpperCase()}). Watch it back, then press Analyze this session, or Retake.`;
  }
  formError.classList.add('hidden');
}

function retakeRecording() {
  discardRecording();
  cameraState = cameraStream ? 'live' : 'off';
  renderCameraControls();
  if (cameraStream) startLiveTracking();
  cameraStatus.textContent = cameraStream ? 'Ready to record again.' : 'Turn on the camera to record again.';
}

function stopCamera() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') stopRecording();
  releaseStream();
  if (cameraState !== 'review') {
    cameraState = 'off';
    cameraStatus.textContent = 'Camera is off.';
  }
  renderCameraControls();
}

async function switchCamera() {
  if (cameraState !== 'live') return;
  await listVideoInputs();
  if (videoInputs.length > 1 && videoInputs.some(device => device.deviceId)) {
    const index = videoInputs.findIndex(device => device.deviceId === currentDeviceId);
    const next = videoInputs[(index + 1) % videoInputs.length];
    await startCamera({deviceId: next.deviceId});
  } else {
    await startCamera({facing: currentFacing === 'environment' ? 'user' : 'environment'});
  }
}

cameraStartButton.addEventListener('click', () => startCamera());
cameraStopButton.addEventListener('click', stopCamera);
recordStartButton.addEventListener('click', startRecording);
recordStopButton.addEventListener('click', stopRecording);
recordPauseButton.addEventListener('click', togglePauseRecording);
recordRetakeButton.addEventListener('click', retakeRecording);
cameraSwitchButton.addEventListener('click', switchCamera);
window.addEventListener('pagehide', () => { if (cameraStream) stopCamera(); });
(function initCameraSupport() {
  const caps = cameraCapabilities();
  if (!caps.secure) showInsecureNote();
  renderCameraControls();
})();

function selectedVideoFile() {
  const cameraTab = !$('#pane-camera').hidden;
  return cameraTab ? recordedFile : fileInput.files?.[0] || null;
}

function startLiveTracking() {
  liveTrackingActive = true;
  liveProcessing = false;
  scheduleLiveFrame(100);
}

function stopLiveTracking() {
  liveTrackingActive = false;
  liveProcessing = false;
  if (liveLoopTimer) {
    clearTimeout(liveLoopTimer);
    liveLoopTimer = null;
  }
  if (cameraOverlay) {
    const ctx = cameraOverlay.getContext('2d');
    if (ctx) ctx.clearRect(0, 0, cameraOverlay.width, cameraOverlay.height);
  }
  if (hudHoopText) hudHoopText.textContent = 'Searching for rim…';
  if (hudHoopDot) hudHoopDot.className = 'hud-dot';
  if (hudPanierLive) hudPanierLive.textContent = '—';
  if (hudPicMax) hudPicMax.textContent = '—';
  if (hudKneeVal) hudKneeVal.textContent = '—';
  if (hudElbowVal) hudElbowVal.textContent = '—';
  if (hudPhaseText) hudPhaseText.textContent = 'IDLE';
  if (hudOutcomeBanner) hudOutcomeBanner.classList.remove('is-visible', 'outcome-make', 'outcome-miss');
}

function scheduleLiveFrame(delayMs = 50) {
  if (!liveTrackingActive) return;
  if (liveLoopTimer) clearTimeout(liveLoopTimer);
  liveLoopTimer = setTimeout(processLiveFrame, delayMs);
}

async function processLiveFrame() {
  if (!liveTrackingActive) return;
  if (!cameraPreview || cameraPreview.readyState < 2) {
    scheduleLiveFrame(120);
    return;
  }
  if (liveProcessing) {
    scheduleLiveFrame(40);
    return;
  }

  liveProcessing = true;
  try {
    const vw = cameraPreview.videoWidth || 640;
    const vh = cameraPreview.videoHeight || 480;
    const scale = Math.min(1, 640 / vw);
    const cw = Math.round(vw * scale);
    const ch = Math.round(vh * scale);
    liveCaptureCanvas.width = cw;
    liveCaptureCanvas.height = ch;
    liveCaptureCtx.drawImage(cameraPreview, 0, 0, cw, ch);
    const dataUrl = liveCaptureCanvas.toDataURL('image/jpeg', 0.65);
    const nowMs = Date.now();

    const response = await api('/api/live/process-frame', jsonBody('POST', {
      image: dataUrl,
      timestamp_ms: nowMs
    }));

    if (response && response.status === 'ok') {
      renderLiveHUD(response, vw, vh);
    }
  } catch (err) {
    // Network or processing hiccup; maintain live loop
  } finally {
    liveProcessing = false;
    if (liveTrackingActive) {
      scheduleLiveFrame(cameraState === 'recording' ? 250 : 50);
    }
  }
}

function renderLiveHUD(data, vw, vh) {
  if (!cameraOverlay) return;
  const ctx = cameraOverlay.getContext('2d');
  if (!ctx) return;

  if (cameraOverlay.width !== vw || cameraOverlay.height !== vh) {
    cameraOverlay.width = vw;
    cameraOverlay.height = vh;
  }
  ctx.clearRect(0, 0, vw, vh);

  const [fw, fh] = data.frame_size || [640, 480];
  const sx = vw / fw;
  const sy = vh / fh;

  // 1. Draw Rim / Basket Box & Target Reticle
  if (data.rim && data.rim.detected && data.rim.box) {
    const [rx1, ry1, rx2, ry2] = data.rim.box;
    const x = rx1 * sx;
    const y = ry1 * sy;
    const w = (rx2 - rx1) * sx;
    const h = (ry2 - ry1) * sy;
    const cx = x + w / 2;
    const cy = y + h / 2;

    ctx.save();
    ctx.strokeStyle = '#ff6b00';
    ctx.lineWidth = 2.5;
    ctx.shadowColor = 'rgba(255, 107, 0, 0.8)';
    ctx.shadowBlur = 10;
    ctx.strokeRect(x, y, w, h);

    const targetR = Math.min(w, h) * 0.35;
    ctx.beginPath();
    ctx.arc(cx, cy, targetR, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(255, 107, 0, 0.9)';
    ctx.lineWidth = 2;
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(cx - targetR * 1.3, cy);
    ctx.lineTo(cx + targetR * 1.3, cy);
    ctx.moveTo(cx, cy - targetR * 1.3);
    ctx.lineTo(cx, cy + targetR * 1.3);
    ctx.strokeStyle = 'rgba(255, 107, 0, 0.6)';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    const rimConfPct = Math.round((data.rim.conf || 0.89) * 100);
    const tagText = `RIM ${rimConfPct}%`;
    ctx.font = 'bold 12px Inter, system-ui, sans-serif';
    const tagW = ctx.measureText(tagText).width + 14;
    ctx.fillStyle = '#ff6b00';
    ctx.fillRect(x, Math.max(0, y - 20), tagW, 20);
    ctx.fillStyle = '#ffffff';
    ctx.fillText(tagText, x + 7, Math.max(14, y - 6));
    ctx.restore();
  }

  // 2. Draw Ball & Parabolic Flight Trail
  if (data.ball) {
    const trail = data.ball.flight_trail || [];
    if (trail.length > 1) {
      ctx.save();
      ctx.strokeStyle = '#ff8c00';
      ctx.lineWidth = 3.5;
      ctx.shadowColor = 'rgba(255, 140, 0, 0.9)';
      ctx.shadowBlur = 12;
      ctx.beginPath();
      for (let i = 0; i < trail.length; i++) {
        const tx = trail[i][0] * sx;
        const ty = trail[i][1] * sy;
        if (i === 0) ctx.moveTo(tx, ty);
        else ctx.lineTo(tx, ty);
      }
      ctx.stroke();

      for (let i = 0; i < trail.length; i++) {
        const tx = trail[i][0] * sx;
        const ty = trail[i][1] * sy;
        ctx.beginPath();
        ctx.arc(tx, ty, 3, 0, Math.PI * 2);
        ctx.fillStyle = '#fbbf24';
        ctx.fill();
      }
      ctx.restore();
    }

    if (data.ball.detected && data.ball.box) {
      const [bx1, by1, bx2, by2] = data.ball.box;
      const x = bx1 * sx;
      const y = by1 * sy;
      const w = (bx2 - bx1) * sx;
      const h = (by2 - by1) * sy;
      const cx = x + w / 2;
      const cy = y + h / 2;

      ctx.save();
      ctx.strokeStyle = '#38bdf8';
      ctx.lineWidth = 2.5;
      ctx.shadowColor = 'rgba(56, 189, 248, 0.8)';
      ctx.shadowBlur = 10;
      ctx.beginPath();
      ctx.arc(cx, cy, Math.max(w, h) / 2, 0, Math.PI * 2);
      ctx.stroke();

      const ballConfPct = Math.round((data.ball.conf || 0.9) * 100);
      const tagText = `BALL ${ballConfPct}%`;
      ctx.font = 'bold 11px Inter, system-ui, sans-serif';
      const tagW = ctx.measureText(tagText).width + 12;
      ctx.fillStyle = '#38bdf8';
      ctx.fillRect(x, Math.max(0, y - 18), tagW, 18);
      ctx.fillStyle = '#0f172a';
      ctx.fillText(tagText, x + 6, Math.max(13, y - 5));
      ctx.restore();
    }
  }

  // 3. Draw Pose Skeleton (glowing orange broadcast aesthetic)
  if (liveShowSkeleton && data.pose && data.pose.landmarks && data.pose.landmarks.length >= 33) {
    const lm = data.pose.landmarks;
    const POSE_PAIRS = [
      [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
      [11, 23], [12, 24], [23, 24],
      [23, 25], [25, 27], [27, 29], [29, 31],
      [24, 26], [26, 28], [28, 30], [30, 32],
    ];

    ctx.save();
    ctx.strokeStyle = '#ff6b00';
    ctx.lineWidth = 3.5;
    ctx.shadowColor = 'rgba(255, 107, 0, 0.8)';
    ctx.shadowBlur = 10;

    for (const [i, j] of POSE_PAIRS) {
      const p1 = lm[i];
      const p2 = lm[j];
      if (!p1 || !p2 || (p1[2] < 0.3 && p2[2] < 0.3)) continue;
      ctx.beginPath();
      ctx.moveTo(p1[0] * vw, p1[1] * vh);
      ctx.lineTo(p2[0] * vw, p2[1] * vh);
      ctx.stroke();
    }

    for (let i = 11; i < 33; i++) {
      const pt = lm[i];
      if (!pt || pt[2] < 0.3) continue;
      const jx = pt[0] * vw;
      const jy = pt[1] * vh;

      ctx.beginPath();
      ctx.arc(jx, jy, 5, 0, Math.PI * 2);
      ctx.fillStyle = '#ff6b00';
      ctx.fill();

      ctx.beginPath();
      ctx.arc(jx, jy, 2.5, 0, Math.PI * 2);
      ctx.fillStyle = '#ffffff';
      ctx.fill();
    }
    ctx.restore();
  }

  // 4. Update HUD Pills
  const rimDetected = Boolean(data.rim && data.rim.detected);
  if (hudHoopText) {
    hudHoopText.textContent = rimDetected ? 'Rim Calibrated' : 'Searching for rim…';
  }
  if (hudHoopDot) {
    hudHoopDot.className = rimDetected ? 'hud-dot active' : 'hud-dot';
  }
  if (hudPanierLive) {
    hudPanierLive.textContent = rimDetected ? '100%' : '—';
  }

  if (hudPicMax) {
    if (data.shot?.arc_peak != null) {
      hudPicMax.textContent = `${Number(data.shot.arc_peak).toFixed(1)} m`;
    } else if (data.ball?.flight_trail?.length > 2) {
      hudPicMax.textContent = 'IN FLIGHT';
    } else {
      hudPicMax.textContent = '—';
    }
  }

  if (hudKneeVal) {
    hudKneeVal.textContent = data.pose?.knee_angle != null ? `${Math.round(data.pose.knee_angle)}°` : '—';
  }

  if (hudElbowVal) {
    hudElbowVal.textContent = data.pose?.elbow_angle != null ? `${Math.round(data.pose.elbow_angle)}°` : '—';
  }

  if (hudPhaseText) {
    const phaseNames = {
      idle: 'IDLE',
      gathering: 'DIP',
      dip: 'DIP',
      set_point: 'SET POINT',
      releasing: 'RELEASE',
      follow_through: 'FOLLOW THROUGH',
    };
    const p = data.shot?.phase || data.pose?.phase || 'idle';
    hudPhaseText.textContent = phaseNames[p] || p.toUpperCase().replaceAll('_', ' ');
  }

  // 5. Update Broadcast Stats
  if (data.shot) {
    if (hudMakesCount) hudMakesCount.textContent = String(data.shot.makes || 0);
    if (hudMissesCount) hudMissesCount.textContent = String(data.shot.misses || 0);
    if (hudAccVal) {
      const acc = data.shot.total > 0 ? Math.round(data.shot.accuracy) : 0;
      hudAccVal.textContent = `${acc}%`;
    }

    if (data.shot.outcome && data.shot.total !== lastReportedShotTotal) {
      lastReportedShotTotal = data.shot.total;
      flashOutcomeBanner(data.shot.outcome, data.shot.outcome_conf);
    }
  }
}

function flashOutcomeBanner(outcome, conf) {
  if (!hudOutcomeBanner) return;
  clearTimeout(liveOutcomeTimer);
  const isMake = outcome === 'make';
  if (hudOutcomeText) {
    hudOutcomeText.textContent = isMake
      ? `SHOT MADE! (${Math.round((conf || 0.85) * 100)}%)`
      : `SHOT MISSED! (${Math.round((conf || 0.85) * 100)}%)`;
  }
  hudOutcomeBanner.className = `hud-outcome-banner is-visible ${isMake ? 'outcome-make' : 'outcome-miss'}`;
  liveOutcomeTimer = setTimeout(() => {
    hudOutcomeBanner.className = 'hud-outcome-banner';
  }, 3200);
}

if (hudRecalibrateBtn) {
  hudRecalibrateBtn.addEventListener('click', async () => {
    hudRecalibrateBtn.disabled = true;
    try {
      await api('/api/live/reset', {method: 'POST'});
      lastReportedShotTotal = 0;
      if (hudMakesCount) hudMakesCount.textContent = '0';
      if (hudMissesCount) hudMissesCount.textContent = '0';
      if (hudAccVal) hudAccVal.textContent = '0%';
      if (cameraOverlay) {
        const ctx = cameraOverlay.getContext('2d');
        if (ctx) ctx.clearRect(0, 0, cameraOverlay.width, cameraOverlay.height);
      }
      toast('Rim and trajectory recalibrated');
    } catch (err) {
      toast('Recalibration failed: ' + err.message);
    } finally {
      hudRecalibrateBtn.disabled = false;
    }
  });
}

if (hudBtnClose) {
  hudBtnClose.addEventListener('click', () => {
    if (cameraStopButton && !cameraStopButton.disabled) cameraStopButton.click();
  });
}

if (hudFinishBtn) {
  hudFinishBtn.addEventListener('click', () => {
    if (cameraStopButton && !cameraStopButton.disabled) cameraStopButton.click();
    toast('Practice session ended');
  });
}

if (hudBtnSkeleton) {
  hudBtnSkeleton.addEventListener('click', () => {
    liveShowSkeleton = !liveShowSkeleton;
    hudBtnSkeleton.classList.toggle('active', liveShowSkeleton);
    toast(liveShowSkeleton ? 'Skeleton overlay enabled' : 'Skeleton overlay hidden');
  });
}

/* ------------------------------------------------------------------- upload */
function showFormError(message) {
  formError.textContent = message;
  formError.classList.remove('hidden');
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  formError.classList.add('hidden');
  playerIdInput.removeAttribute('aria-invalid');
  const file = selectedVideoFile();
  const fromCamera = !$('#pane-camera').hidden;
  if (!PLAYER_ID_PATTERN.test(playerIdInput.value.trim())) {
    playerIdInput.setAttribute('aria-invalid', 'true');
    playerIdInput.focus();
    return showFormError('Player ID can use letters, numbers, - and _ only (up to 64 characters).');
  }
  if (fromCamera && (cameraState === 'recording' || cameraState === 'paused')) return showFormError('Stop the recording first, then press Analyze this session.');
  if (!file) return showFormError(fromCamera ? 'Record a clip first (or switch to Upload a file).' : 'Choose a video file or record a clip first.');
  if (file.size > MAX_VIDEO_BYTES) return showFormError('This clip is larger than 250 MB. Trim it or record a shorter clip.');

  if (pollingTimer) clearTimeout(pollingTimer);
  playerIdInput.value = playerIdInput.value.trim();
  progressPlayer.value = playerIdInput.value;
  storage('set', 'shotLabPlayerId', playerIdInput.value);
  prepareJobPanel('Uploading your clip', 'uploading', 'Copying the video into the local app.');
  sessionContext.textContent = `Player ${playerIdInput.value}, ${describeContext({
    camera_view: form.elements.camera_view.value, shot_type: form.elements.shot_type.value, shot_style: form.elements.shot_style.value})}`;
  submitButton.disabled = true;
  setView('review');

  const data = new FormData(form);
  const query = new URLSearchParams();
  for (const key of ['player_id', 'handedness', 'skill_level', 'goals', 'camera_view', 'shot_type', 'shot_style']) {
    query.set(key, data.get(key) || '');
  }
  query.set('pain_reported', form.elements.pain_reported.checked ? '1' : '0');
  cancelButton.classList.remove('hidden');
  cancelButton.textContent = 'Cancel upload';
  jobProgress.classList.add('is-running');
  try {
    const payload = await uploadWithProgress(`/api/sessions?${query}`, file);
    cancelButton.textContent = 'Cancel analysis';
    jobTitle.textContent = 'Analyzing your session';
    setBadge('queued');
    jobMessage.textContent = `${payload.video.frame_count.toLocaleString()} frames, ${payload.video.duration_seconds} s of video${payload.video.codec ? ` (${payload.video.codec})` : ''}. Analysis runs on the computer.`;
    setProgress(0.01, 'Queued for analysis');
    storage('set', 'shotLabLastJobId', payload.job_id);
    pollJob(payload.job_id);
  } catch (error) {
    cancelButton.classList.add('hidden');
    jobTitle.textContent = error.aborted ? 'Upload cancelled' : 'The upload was not accepted';
    setBadge('failed');
    showJobError(error.message || 'Could not reach the local app. Is web_app.py still running?');
    submitButton.disabled = false;
  }
});

let activeUpload = null;
function uploadWithProgress(url, file) {
  // XMLHttpRequest (not fetch) so the browser reports upload progress, including on phones.
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    activeUpload = xhr;
    xhr.open('POST', url);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.setRequestHeader('X-Upload-Filename', encodeURIComponent(file.name || 'video.mp4'));
    if (file.type) xhr.setRequestHeader('X-Upload-Type', file.type);
    xhr.setRequestHeader('X-Shotlab', '1');
    xhr.upload.addEventListener('progress', event => {
      if (!event.lengthComputable) return;
      const ratio = event.loaded / event.total;
      setProgress(ratio, `Uploading ${Math.round(ratio * 100)}% (${(event.loaded / 1048576).toFixed(1)} of ${(event.total / 1048576).toFixed(1)} MB)`);
      if (ratio >= 1) setProgress(1, 'Upload complete; checking the video…');
    });
    xhr.addEventListener('load', () => {
      activeUpload = null;
      let payload = {};
      try { payload = JSON.parse(xhr.responseText || '{}'); } catch { payload = {}; }
      if (xhr.status >= 200 && xhr.status < 300) resolve(payload);
      else reject(Object.assign(new Error(payload.error || `Upload failed (${xhr.status})`), {status: xhr.status}));
    });
    xhr.addEventListener('error', () => { activeUpload = null; reject(new Error('The upload was interrupted (connection lost). Check that this device is still on the same network as the computer running Shot Lab, then try again.')); });
    xhr.addEventListener('abort', () => { activeUpload = null; reject(Object.assign(new Error('You cancelled the upload. Nothing was saved.'), {aborted: true})); });
    xhr.send(file);
  });
}

cancelButton.addEventListener('click', async () => {
  if (activeUpload) { activeUpload.abort(); return; }
  if (!pendingJobId) return;
  cancelButton.disabled = true;
  try {
    await api(`/api/jobs/${pendingJobId}/cancel`, {method: 'POST'});
    jobMessage.textContent = 'Stopping…';
  } catch (error) { showJobError(error.message); }
  finally { cancelButton.disabled = false; }
});

function prepareJobPanel(title, state, message) {
  reviewEmpty.classList.add('hidden');
  jobPanel.classList.remove('hidden');
  jobProgress.classList.remove('is-complete');
  errorText.classList.add('hidden');
  results.classList.add('hidden');
  results.replaceChildren();
  jobTitle.textContent = title;
  setBadge(state);
  jobMessage.textContent = message;
  setProgress(0, 'Starting');
}
function setBadge(state) {
  jobBadge.dataset.state = state;
  jobBadge.textContent = {queued: 'Queued', uploading: 'Uploading', running: 'Analyzing', complete: 'Ready to review', failed: 'Failed'}[state] || state;
}
function setProgress(ratio, label) {
  const percent = Math.max(0, Math.min(100, Math.round(ratio * 100)));
  const scale = Math.max(percent, ratio > 0 ? 1 : 0) / 100;
  progressBar.style.width = '100%';
  progressBar.style.transformOrigin = 'left center';
  if (motionOn()) Motion.animate(progressBar, {scaleX: scale}, SOFT_SPRING);
  else progressBar.style.transform = `scaleX(${scale})`;
  progressBar.parentElement.setAttribute('aria-valuenow', String(percent));
  progressLabel.textContent = label;
}
function showJobError(message) {
  errorText.textContent = message;
  errorText.classList.remove('hidden');
}

let pendingJobId = null;
async function pollJob(jobId) {
  pendingJobId = jobId;
  try {
    const job = await api(`/api/jobs/${jobId}`);
    setBadge(job.status);
    jobMessage.textContent = job.message;
    cancelButton.classList.toggle('hidden', !['queued', 'running'].includes(job.status));
    jobProgress.classList.toggle('is-running', ['queued', 'running'].includes(job.status));
    if (job.status === 'complete' && job.kind === 'pose_refresh') {
      toast('Pose data refreshed; reopening the session.');
      const target = refreshReturnJob || storage('get', 'shotLabLastJobId');
      refreshReturnJob = null;
      if (target) return openSession(target);
    }
    if (job.status === 'complete') {
      activeJobId = jobId;
      jobTitle.textContent = 'Session ready to review';
      jobProgress.classList.add('is-complete');
      renderResults(job.result, jobId);
      submitButton.disabled = false;
      return;
    }
    if (job.status === 'failed') {
      jobTitle.textContent = job.error === 'cancelled' ? 'Analysis cancelled' : 'This analysis did not finish';
      showJobError(job.error === 'cancelled' ? 'The analysis was stopped and its partial results were removed.' : `${job.message}${job.error ? ` Details: ${job.error}` : ''}`);
      submitButton.disabled = false;
      if (job.error === 'cancelled') storage('remove', 'shotLabLastJobId');
      return;
    }
    setProgress(job.progress || 0, `${Math.round((job.progress || 0) * 100)}% analyzed`);
    pollingTimer = setTimeout(() => pollJob(jobId), 1000);
  } catch (error) {
    if (error.status === 404) {
      storage('remove', 'shotLabLastJobId');
      clearReview();
      return;
    }
    showJobError(error.message || 'Could not read analysis status.');
    submitButton.disabled = false;
  }
}

function clearReview() {
  activeJobId = null;
  activeSessionId = null;
  results.replaceChildren();
  results.classList.add('hidden');
  jobPanel.classList.add('hidden');
  reviewEmpty.classList.remove('hidden');
  navReviewCount.classList.add('hidden');
}

function openSession(jobId) {
  if (pollingTimer) clearTimeout(pollingTimer);
  storage('set', 'shotLabLastJobId', jobId);
  prepareJobPanel('Opening session', 'queued', 'Loading saved analysis and reviews.');
  sessionContext.textContent = '';
  setView('review');
  pollJob(jobId);
}

/* ------------------------------------------------------------------ results */
function renderResults(result, jobId) {
  if (!result) return;
  activeSessionId = result.session_id;
  const shots = result.shots || [];
  const fps = Number(result.video?.fps || 30);
  const frameCount = Number(result.video?.frame_count || result.frames_processed || 1);
  let selected = 0;
  results.replaceChildren();

  // Summary numbers
  const statRow = el('div', {class: 'stat-row'});
  const reviewCountNode = el('strong');
  const approvedCountNode = el('strong');
  statRow.append(
    el('div', {class: 'stat'}, el('strong', {text: shots.length}), el('span', {text: 'attempts proposed'})),
    el('div', {class: 'stat is-review'}, reviewCountNode, el('span', {text: 'need your review'})),
    el('div', {class: 'stat is-approved'}, approvedCountNode, el('span', {text: 'approved by you'})),
    el('div', {class: 'stat'}, el('strong', {text: Number(result.frames_processed || 0).toLocaleString()}), el('span', {text: `frames analyzed at ${fmt(fps)} fps`})),
  );
  results.append(statRow);
  const statNumbers = [...statRow.querySelectorAll('strong')];
  const notes = [result.notice || 'Attempts are machine proposals. Confirm them before they count.'];
  if (result.finalized_at_video_end_count) notes.push('One attempt reached the end of the clip; its follow-through frame is the last frame.');
  if (result.incomplete_candidate_count) notes.push('A possible attempt started but the clip ended before a release was seen, so it was not proposed.');
  results.append(el('p', {class: 'result-note', text: notes.join(' ')}));

  // Replay + review
  const layout = el('div', {class: 'review-layout'});
  const playerCard = el('section', {class: 'card player-card monitor', 'aria-label': 'Replay'});
  const frame = el('div', {class: 'video-frame'});
  const video = el('video', {id: 'replay-video', controls: true, playsinline: true, preload: 'metadata', src: `/api/jobs/${jobId}/video`});
  video.playsInline = true;
  const canvas = el('canvas', {class: 'pose-overlay', 'aria-hidden': 'true'});
  const overlayToggle = el('input', {type: 'checkbox', checked: true});
  overlayToggle.checked = true;
  const overlayLabel = el('label', {class: 'overlay-toggle'}, overlayToggle, 'Pose');
  const anglesToggle = el('input', {type: 'checkbox'});
  anglesToggle.checked = true;
  const anglesLabel = el('label', {class: 'overlay-toggle'}, anglesToggle, 'Angles');
  const ballToggle = el('input', {type: 'checkbox'});
  ballToggle.checked = true;
  const ballLabel = el('label', {class: 'overlay-toggle'}, ballToggle, 'Ball & Rim');
  frame.append(video, canvas, el('div', {class: 'overlay-toggles'}, overlayLabel, anglesLabel, ballLabel));
  playerCard.append(frame);

  const timelineTrack = el('div', {class: 'timeline-track', role: 'slider', tabindex: '0', 'aria-label': 'Clip timeline. Use arrow keys to step frames.', 'aria-valuemin': '0', 'aria-valuemax': String(frameCount - 1), 'aria-valuenow': '0'});
  const playhead = el('div', {class: 'timeline-playhead'});
  // Attempt segments and coach markers sit in a layer above (not inside) the slider, so the
  // slider has no nested interactive children; empty-space clicks fall through to it.
  const timelineMarks = el('div', {class: 'timeline-marks'});
  const frameReadout = el('span', {class: 'frame-readout', text: `0:00.00 · frame 0 of ${frameCount - 1}`});
  const prevButton = el('button', {type: 'button', class: 'btn btn-quiet btn-small', onclick: () => selectAttempt(selected - 1, true), 'aria-label': 'Previous attempt'}, '‹ Prev');
  const nextAttemptButton = el('button', {type: 'button', class: 'btn btn-quiet btn-small', onclick: () => selectAttempt(selected + 1, true), 'aria-label': 'Next attempt'}, 'Next ›');
  const phaseJumps = el('div', {class: 'phase-jumps', role: 'group', 'aria-label': 'Jump to a phase of the selected attempt'});
  playerCard.append(el('div', {class: 'clip-timeline'},
    el('div', {class: 'timeline-head'}, el('strong', {text: 'Clip timeline'}), frameReadout,
      el('span', {class: 'attempt-nav'}, prevButton, nextAttemptButton)),
    el('div', {class: 'timeline-wrap'}, timelineTrack, timelineMarks),
    el('div', {class: 'timeline-legend'},
      el('span', {}, el('i', {class: 'swatch-review'}), 'Needs review'),
      el('span', {}, el('i', {class: 'swatch-approved'}), 'Approved'),
      el('span', {}, el('i', {class: 'swatch-discarded'}), 'Discarded'),
      el('span', {}, el('i', {class: 'swatch-release'}), 'Release'),
      el('span', {}, el('i', {class: 'legend-dot legend-improve'}), 'Coach: work on'),
      el('span', {}, el('i', {class: 'legend-dot legend-strength'}), 'Coach: strength')),
    phaseJumps));
  layout.append(playerCard);

  const reviewCard = el('section', {class: 'card attempts-card', 'aria-labelledby': 'attempts-title'});
  reviewCard.append(el('div', {class: 'card-head'}, el('h2', {id: 'attempts-title', text: 'Attempts'}),
    el('p', {text: shots.length ? 'Pick an attempt, check it against the replay, then approve, correct or discard it.' : ''})));
  const list = el('ul', {class: 'attempt-list'});
  reviewCard.append(list);
  const editor = el('div', {class: 'review-editor'});
  reviewCard.append(editor);
  const manualPanel = el('details', {class: 'manual-attempt'});
  reviewCard.append(manualPanel);
  layout.append(reviewCard);
  results.append(layout);

  const seekToFrame = frameNumber => {
    if (frameNumber == null) return;
    video.currentTime = Math.min(frameCount - 1, Math.max(0, frameNumber)) / fps + 0.0001;
  };
  const currentFrame = () => Math.min(frameCount - 1, Math.max(0, Math.round(video.currentTime * fps)));

  timelineTrack.addEventListener('click', event => {
    if (event.target.closest('.timeline-seg')) return;
    const rect = timelineTrack.getBoundingClientRect();
    seekToFrame(Math.round(((event.clientX - rect.left) / rect.width) * (frameCount - 1)));
  });
  timelineTrack.addEventListener('keydown', event => {
    const step = event.shiftKey ? Math.round(fps) : 1;
    if (event.key === 'ArrowRight') { event.preventDefault(); seekToFrame(currentFrame() + step); }
    if (event.key === 'ArrowLeft') { event.preventDefault(); seekToFrame(currentFrame() - step); }
  });

  function renderTimeline() {
    timelineMarks.replaceChildren();
    shots.forEach((shot, index) => {
      const start = frameOf(shot, 'start') ?? 0;
      const end = frameOf(shot, 'end') ?? start;
      const seg = el('button', {
        type: 'button', class: 'timeline-seg', 'data-status': shot.review_status || 'quarantined',
        'aria-current': index === selected ? 'true' : 'false',
        'aria-label': `Attempt ${index + 1}, frames ${start} to ${end}, ${LABELS.review_status[shot.review_status] || 'Needs review'}`,
        style: `left:${(start / frameCount) * 100}%;width:${Math.max(0.6, ((end - start + 1) / frameCount) * 100)}%`,
        onclick: () => selectAttempt(index, true),
      }, el('span', {text: index + 1}));
      timelineMarks.append(seg);
      const release = frameOf(shot, 'release');
      const dip = frameOf(shot, 'dip');
      if (dip != null) timelineMarks.append(el('div', {class: 'timeline-dip', style: `left:${(dip / frameCount) * 100}%`, title: `Dip: frame ${dip}`}));
      if (release != null) timelineMarks.append(el('div', {class: 'timeline-release', style: `left:${(release / frameCount) * 100}%`, title: `Release: frame ${release}`}));
    });
    // Coach notes often fall within a few frames of each other, which would stack their dots
    // on top of one another and leave most of them unreachable. Notes closer than one hit
    // target (24px) are grouped into a single button; each press jumps to the next note in
    // the group, so every note stays reachable by mouse, touch and keyboard.
    const noteText = marker => `${marker.kind === 'strength' ? 'Strength' : 'Work on'}: ${marker.title} (attempt ${marker.attempt}, ${mmss(marker.time_s)})`;
    const trackWidth = timelineTrack.clientWidth || 600;
    const minGapFrames = (24 / trackWidth) * frameCount;
    const groups = [];
    for (const marker of [...coachMarkers].sort((a, b) => a.frame - b.frame)) {
      const last = groups[groups.length - 1];
      if (last && marker.frame - last[0].frame < minGapFrames) last.push(marker);
      else groups.push([marker]);
    }
    for (const group of groups) {
      const kinds = new Set(group.map(marker => marker.kind));
      const kind = kinds.size > 1 ? 'mixed' : group[0].kind;
      // Placed at the group's first note (where the first press seeks), which also keeps
      // neighbouring buttons at least one 24px target apart.
      const centre = group[0].frame;
      let next = 0;
      const describe = () => group.length === 1 ? noteText(group[0])
        : `${group.length} coach notes here. Press to step through them; next: ${noteText(group[next])}`;
      const button = el('button', {type: 'button', class: `timeline-insight insight-${kind}${group.length > 1 ? ' is-group' : ''}`,
        style: `left:${(Math.min(frameCount - 1, centre) / frameCount) * 100}%`,
        'data-count': group.length > 1 ? String(group.length) : null,
        'data-tip': describe(),
        'aria-label': group.length === 1 ? `Coach note: ${group[0].title}, attempt ${group[0].attempt} at ${mmss(group[0].time_s)}`
          : `Group of ${group.length} coach notes. Next: ${group[next].title}, attempt ${group[next].attempt} at ${mmss(group[next].time_s)}`});
      button.addEventListener('click', event => {
        event.stopPropagation();
        const marker = group[next];
        seekToFrame(marker.frame);
        if (group.length > 1) {
          toast(`Note ${next + 1} of ${group.length}: ${noteText(marker)}`);
          next = (next + 1) % group.length;
          button.dataset.tip = describe();
          button.setAttribute('aria-label', `Group of ${group.length} coach notes. Next: ${group[next].title}, attempt ${group[next].attempt} at ${mmss(group[next].time_s)}`);
          if (!tooltip.hidden && tooltipTarget === button) showTooltip(button);
        }
      });
      timelineMarks.append(button);
    }
    timelineMarks.append(playhead);
    updatePlayhead();
    prevButton.disabled = selected <= 0 || !shots.length;
    nextAttemptButton.disabled = selected >= shots.length - 1;
  }
  function updatePlayhead() {
    const current = currentFrame();
    playhead.style.left = `${(current / Math.max(1, frameCount - 1)) * 100}%`;
    timelineTrack.setAttribute('aria-valuenow', String(current));
    frameReadout.textContent = `${mmss(current / fps)} · frame ${current} of ${frameCount - 1}`;
    if (editor.currentFrameNode) editor.currentFrameNode.textContent = String(current);
  }

  function renderList() {
    list.replaceChildren();
    shots.forEach((shot, index) => {
      const status = shot.review_status || 'quarantined';
      const release = frameOf(shot, 'release');
      let outcomeLabel = 'Needs confirmation';
      if ((shot.review_status || 'quarantined') === 'approved' && shot.outcome && shot.outcome !== 'unknown') {
        outcomeLabel = `${LABELS.outcome[shot.outcome]} (Confirmed)`;
      } else if (shot.outcome_source === 'automated_trajectory' || (shot.automated_outcome && shot.automated_outcome !== 'unknown')) {
        const auto = shot.automated_outcome || shot.outcome;
        const conf = Math.round((shot.automated_outcome_conf || 0) * 100);
        if (auto && auto !== 'unknown') {
          outcomeLabel = `Automatic: ${LABELS.outcome[auto] || auto} (${conf}%)`;
        }
      } else if (shot.outcome && shot.outcome !== 'unknown') {
        outcomeLabel = `${LABELS.outcome[shot.outcome]} (Confirmed)`;
      }
      list.append(el('li', {}, el('button', {
        type: 'button', class: 'attempt', 'aria-pressed': String(index === selected), onclick: () => selectAttempt(index, true),
      },
      el('span', {class: 'attempt-num', text: index + 1}),
      el('span', {class: 'attempt-meta'},
        el('strong', {text: `${mmss((frameOf(shot, 'start') ?? 0) / fps)}${release == null ? ' · release not marked' : ` · release ${mmss(release / fps)}`}`}),
        el('span', {text: `${outcomeLabel}, ${shot.tracking_confidence === 'SUFFICIENT' ? 'body well tracked' : 'body partly tracked'}`})),
      el('span', {class: `chip chip-${status}`, text: shot.outcome_source === 'manual_attempt' ? 'Added by you' : (LABELS.review_status[status] || status)}))));
    });
    const pending = shots.filter(shot => (shot.review_status || 'quarantined') === 'quarantined').length;
    reviewCountNode.textContent = pending;
    approvedCountNode.textContent = shots.filter(shot => shot.review_status === 'approved').length;
    if (navReviewCount.textContent !== String(pending)) pop(navReviewCount);
    navReviewCount.textContent = pending;
    navReviewCount.classList.toggle('hidden', !pending);
  }

  function renderPhaseJumps() {
    phaseJumps.replaceChildren();
    const shot = shots[selected];
    if (!shot) return;
    for (const [key, label] of PHASES) {
      const value = frameOf(shot, key);
      if (key === 'dip' && value == null) {
        // Enforce user rule: Show Dip only when pipeline produced a valid frame.
        // If no valid dip exists, omit the Dip control completely.
        continue;
      }
      phaseJumps.append(el('button', {
        type: 'button', class: 'btn btn-quiet btn-small', disabled: value == null,
        title: value == null ? 'Not marked' : `Frame ${value}`,
        onclick: () => seekToFrame(value),
      }, value == null ? `${label}: not marked` : `${label} ${value}`));
    }
  }

  function renderEditor() {
    editor.replaceChildren();
    const shot = shots[selected];
    if (!shot) {
      editor.append(el('div', {class: 'abstain span-all'},
        el('p', {text: `No attempts passed the shot detector in this clip (${result.candidate_count || 0} possible start${result.candidate_count === 1 ? '' : 's'} examined).`}),
        el('p', {text: 'Try a steadier side-on clip with your whole body and the ball in view. You can still watch the replay and pose overlay.'})));
      editor.currentFrameNode = null;
      return;
    }
    editor.append(el('h3', {text: `Review attempt ${selected + 1}`}));
    const inputs = {};
    for (const [key, label] of PHASES) {
      const value = frameOf(shot, key);
      if (key === 'dip' && value == null) {
        // Enforce user rule: Omit Dip control if pipeline produced no valid dip.
        // Do not show a blank input, ask player to guess, or fabricate a value.
        continue;
      }
      const input = el('input', {type: 'number', min: '0', max: String(frameCount - 1), step: '1', inputmode: 'numeric',
        placeholder: 'Not marked'});
      input.value = value == null ? '' : value;
      input.addEventListener('change', () => { if (input.value !== '') seekToFrame(Number(input.value)); });
      inputs[key] = input;
      editor.append(el('label', {class: 'field'}, `${label} frame`, input));
    }
    const currentFrameNode = el('b', {text: String(currentFrame())});
    editor.currentFrameNode = currentFrameNode;
    editor.append(el('div', {class: 'frame-helper span-all'},
      el('span', {}, 'Replay is at frame ', currentFrameNode),
      el('button', {type: 'button', class: 'btn btn-quiet btn-small', onclick: () => { inputs.release.value = currentFrame(); }}, 'Set as release frame')));

    const radioGroup = (name, legend, options, current) => {
      const row = el('div', {class: 'choice-row'});
      for (const [value, text] of options) {
        const input = el('input', {type: 'radio', name: `${name}-${shot.shot_id}`, value});
        input.checked = value === current;
        row.append(el('label', {}, input, el('span', {text})));
      }
      return el('fieldset', {class: 'choice-group'}, el('legend', {text: legend}), row);
    };
    const autoOutcome = shot.automated_outcome || (shot.outcome_source === 'automated_trajectory' ? shot.outcome : null);
    const defaultOutcome = (shot.outcome && shot.outcome !== 'unknown')
      ? shot.outcome
      : ((autoOutcome && autoOutcome !== 'unknown' && (shot.automated_outcome_conf || 0) >= 0.70)
          ? autoOutcome
          : 'unknown');

    const outcomeGroup = radioGroup('outcome', 'Outcome you saw', [['unknown', 'Not sure'], ['make', 'Make'], ['miss', 'Miss']], defaultOutcome);
    const statusGroup = radioGroup('status', 'Decision', [['quarantined', 'Leave for later'], ['approved', 'Approve'], ['discarded', 'Not a shot']], shot.review_status || 'quarantined');

    // Advisory automated outcome banner
    let autoOutcomeBanner = null;
    if (autoOutcome && autoOutcome !== 'unknown') {
      const isHighConf = (shot.automated_outcome_conf || 0) >= 0.70 && (shot.trajectory_fit_r2 || 0) >= 0.70;
      const confPct = Math.round((shot.automated_outcome_conf || 0) * 100);
      const r2Text = shot.trajectory_fit_r2 != null ? Number(shot.trajectory_fit_r2).toFixed(2) : '—';
      const label = LABELS.outcome[autoOutcome] || autoOutcome;
      if (isHighConf) {
        const confirmBtn = el('button', {type: 'button', class: 'btn btn-quiet btn-small', onclick: () => {
          const radio = outcomeGroup.querySelector(`input[value="${autoOutcome}"]`);
          if (radio) radio.checked = true;
          const approveRadio = statusGroup.querySelector('input[value="approved"]');
          if (approveRadio) approveRadio.checked = true;
        }}, `Confirm prediction (${label})`);
        autoOutcomeBanner = el('div', {class: 'auto-outcome-banner span-all'},
          el('div', {style: 'display: flex; align-items: center; gap: 8px; flex-wrap: wrap;'},
            el('span', {class: 'auto-outcome-pill', text: `Trajectory: ${label}`}),
            el('span', {class: 'auto-outcome-conf', text: `${confPct}% conf · R² ${r2Text}`})
          ),
          confirmBtn
        );
      } else {
        autoOutcomeBanner = el('div', {class: 'auto-outcome-banner span-all'},
          el('div', {style: 'display: flex; align-items: center; gap: 8px; flex-wrap: wrap;'},
            el('span', {class: 'auto-outcome-pill neutral', text: `Uncertain: ${label}`}),
            el('span', {class: 'auto-outcome-conf', text: `${confPct}% conf · R² ${r2Text} (Needs review)`})
          )
        );
      }
    } else {
      autoOutcomeBanner = el('div', {class: 'auto-outcome-banner span-all'},
        el('span', {class: 'auto-outcome-pill neutral', text: 'No ball tracking prediction'}),
        el('span', {class: 'auto-outcome-conf', text: 'Confirm outcome manually'})
      );
    }

    const notes = el('textarea', {rows: '2', maxlength: '2000', placeholder: 'Optional, e.g. ball hidden at release'});
    notes.value = shot.review_notes || '';
    const saveStatus = el('p', {class: 'review-save-status', 'aria-live': 'polite'});
    const saveButton = el('button', {type: 'button', class: 'btn btn-primary'}, 'Save review');
    const nextButton = el('button', {type: 'button', class: 'btn btn-quiet', disabled: selected >= shots.length - 1,
      onclick: () => selectAttempt(selected + 1, true)}, 'Next attempt');
    editor.append(autoOutcomeBanner, outcomeGroup, statusGroup, el('label', {class: 'field span-all'}, 'Notes', notes),
      el('div', {class: 'review-actions'}, saveButton, nextButton), saveStatus,
      el('div', {class: 'attempt-measures span-all'}));
    renderEditorMeasurements();

    const historyItems = shot.review_history || [];
    const historyLog = el('ol', {class: 'history-log'});
    for (const entry of historyItems.slice().reverse()) {
      const before = entry.previous_values || {}, after = entry.updated_values || {};
      const changes = Object.keys(after).filter(key => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
        .map(key => `${key.replace(/^annotated_/, '').replaceAll('_', ' ')}: ${before[key] ?? 'none'} to ${after[key] ?? 'none'}`);
      historyLog.append(el('li', {text: `${formatDate(entry.created_at)}, ${entry.reviewer_id || 'local user'}. ${changes.length ? changes.join('; ') : 'Saved with no field changes'}`}));
    }
    editor.append(el('details', {class: 'review-history'},
      el('summary', {text: `Change history (${historyItems.length})`}),
      historyItems.length ? historyLog : el('p', {class: 'hint', text: 'No human edits yet. The machine proposal is unchanged.'}),
      el('p', {class: 'hint', text: `Machine proposal kept separately: frames ${frameOrDash(shot.machine_start_frame)} to ${frameOrDash(shot.machine_end_frame)}${shot.machine_dip_frame != null ? `, dip ${shot.machine_dip_frame}` : ''}, release ${frameOrDash(shot.machine_release_frame)}.`})));

    saveButton.addEventListener('click', async () => {
      const boundaries = {};
      for (const [key] of PHASES) {
        if (!inputs[key]) {
          boundaries[`${key}_frame`] = null;
          continue;
        }
        const raw = inputs[key].value.trim();
        if (raw !== '' && !/^\d+$/.test(raw)) { saveStatus.textContent = 'Frame numbers must be whole numbers.'; inputs[key].focus(); return; }
        boundaries[`${key}_frame`] = raw === '' ? null : Number(raw);
      }
      const outcome = outcomeGroup.querySelector('input:checked')?.value || 'unknown';
      const status = statusGroup.querySelector('input:checked')?.value || 'quarantined';
      if (outcome !== 'unknown' && status !== 'approved') {
        saveStatus.textContent = 'To record a make or miss, choose Approve so the label counts as confirmed.';
        return;
      }
      saveButton.disabled = true;
      saveStatus.textContent = 'Saving…';
      try {
        const payload = await api(`/api/shots/${shot.shot_id}/review`, jsonBody('PUT', {boundaries, outcome, review_status: status, review_notes: notes.value}));
        const updated = {...payload.shot, review_history: payload.history};
        shots[selected] = updated;
        renderList();
        renderTimeline();
        renderPhaseJumps();
        renderEditor();
        editor.querySelector('.review-save-status').textContent = 'Review saved. The machine proposal is kept unchanged alongside your edit.';
        toast(`Attempt ${selected + 1} saved as ${LABELS.review_status[status].toLowerCase()}`);
        refreshInsights();
      } catch (error) {
        saveStatus.textContent = error.message;
        saveButton.disabled = false;
      }
    });
  }

  function selectAttempt(index, seek) {
    if (!shots.length) return;
    selected = Math.max(0, Math.min(shots.length - 1, index));
    renderList();
    renderTimeline();
    renderPhaseJumps();
    renderEditor();
    if (seek) seekToFrame(frameOf(shots[selected], 'start'));
  }

  // Pose overlay
  let poseData = null;
  const redraw = () => {
    const side = attemptAnalysis[shots[selected]?.shot_id]?.shooting_side;
    drawPoseOverlay(video, canvas, poseData, result.video, {
      pose: overlayToggle.checked,
      angles: anglesToggle.checked,
      ball: ballToggle.checked,
      side,
      selectedShot: shots[selected],
    });
    updatePlayhead();
  };
  api(`/api/jobs/${jobId}/pose`).then(data => { poseData = data; redraw(); })
    .catch(() => { overlayLabel.replaceChildren('Pose overlay unavailable'); overlayToggle.checked = false; });
  overlayToggle.addEventListener('change', redraw);
  anglesToggle.addEventListener('change', redraw);
  ballToggle.addEventListener('change', redraw);
  for (const eventName of ['timeupdate', 'seeked', 'loadedmetadata']) video.addEventListener(eventName, redraw);
  let rafId = null;
  video.addEventListener('play', () => {
    const tick = () => { redraw(); if (!video.paused && !video.ended) rafId = requestAnimationFrame(tick); };
    rafId = requestAnimationFrame(tick);
  });
  video.addEventListener('pause', () => cancelAnimationFrame(rafId));
  video.addEventListener('error', () => {
    frame.append(el('p', {class: 'abstain replay-error', text: 'This browser could not play the replay (the file is missing or its codec is unsupported). Review still works by frame number.'}));
  });
  window.addEventListener('resize', redraw);
  // Re-group coach markers whenever the timeline's width changes (resize, rotation, or the
  // Review view becoming visible again after it was hidden with zero width).
  let timelineWidth = timelineTrack.clientWidth;
  if ('ResizeObserver' in window) {
    const observer = new ResizeObserver(() => {
      if (!timelineTrack.isConnected) { observer.disconnect(); return; }
      const width = timelineTrack.clientWidth;
      if (!width || Math.abs(width - timelineWidth) < 1) return;
      timelineWidth = width;
      renderTimeline();
    });
    observer.observe(timelineTrack);
  }

  // Insights, chat, report
  const insightGrid = el('div', {class: 'insight-grid'});
  const coachCard = el('section', {class: 'card coach-card', 'aria-labelledby': 'coach-title'});
  const cueCard = el('section', {class: 'card', 'aria-label': 'Personal drill plan'});
  const metricsStatus = el('p', {class: 'hint'});
  insightGrid.append(coachCard, cueCard);
  results.append(insightGrid);

  const lowerGrid = el('div', {class: 'lower-grid'});
  const chatNotice = el('p', {class: 'hint', text: 'Optional AI explanations are off. The rule-based cue above works without them.'});
  const chatInput = el('input', {type: 'text', maxlength: '1000', placeholder: 'Why is this mechanic flagged?', 'aria-label': 'Question for the AI coach', disabled: true});
  const chatButton = el('button', {type: 'submit', class: 'btn btn-quiet', disabled: true}, 'Ask');
  const chatAnswer = el('p', {class: 'chat-answer', 'aria-live': 'polite'});
  const chatForm = el('form', {class: 'chat-form'}, chatInput, chatButton);
  const chatStatus = el('p', {class: 'hint chat-status hidden', role: 'status'});
  const chatSuggestions = el('div', {class: 'chat-suggestions hidden'},
    ['Explain my top issue in plain words', 'What should I practise this week?', 'Which results are uncertain, and why?']
      .map(text => el('button', {type: 'button', class: 'btn btn-quiet btn-small', onclick: () => { chatInput.value = text; chatForm.requestSubmit(); }}, text)));
  lowerGrid.append(el('section', {class: 'card', 'aria-labelledby': 'chat-title'},
    el('h2', {id: 'chat-title', text: 'Ask about this session'}), chatNotice, chatStatus, chatSuggestions, chatForm, chatAnswer));
  lowerGrid.append(el('section', {class: 'card report-card', 'aria-labelledby': 'report-title'},
    el('h2', {id: 'report-title', text: 'Full coaching report'}),
    el('p', {text: 'Ten sections: overview, coaching summary, technical table, annotated keyframes, shot-by-shot review, correction plan, practice plan, technique and injury-risk reduction, progress, and methodology. Print it or save it as a PDF.'}),
    el('div', {class: 'report-card-actions'},
      el('button', {type: 'button', class: 'btn btn-primary', onclick: () => { reportSessionId = result.session_id; setView('report'); }}, 'Open full report'),
      el('button', {type: 'button', class: 'btn btn-quiet', onclick: () => { reportSessionId = result.session_id; openWorkoutFor(result.session_id); }}, 'Personalized workout'))));
  results.append(lowerGrid);

  const showChatStatus = status => {
    const problem = status && ['invalid_key', 'no_credits', 'forbidden', 'model_not_found', 'model_not_listed', 'unreachable'].includes(status.state);
    chatStatus.textContent = problem ? status.message : '';
    chatStatus.classList.toggle('hidden', !problem);
  };
  const enableChat = health => {
    if (!health?.llm_chat_enabled) {
      chatNotice.textContent = health?.llm_setup || 'Optional AI explanations are off. The rule-based cue above works without them.';
      return;
    }
    chatNotice.textContent = `AI explanations are on (${health.llm_provider_label || 'AI'}, ${health.llm_model || ''}). Only your question and text summaries of this session's results and report are sent; video and body landmarks stay on the computer.`;
    showChatStatus(health.llm_status);
    chatInput.disabled = false;
    chatButton.disabled = false;
    chatSuggestions.classList.remove('hidden');
  };
  // Always re-read health: the key check (and its result) happens in the background after start-up.
  api('/api/health').then(health => { healthInfo = health; enableChat(health); }).catch(() => { if (healthInfo) enableChat(healthInfo); });
  chatForm.addEventListener('submit', async event => {
    event.preventDefault();
    if (!chatInput.value.trim()) return;
    chatButton.disabled = true;
    chatAnswer.textContent = 'Thinking… (this can take up to a minute)';
    try {
      const payload = await api(`/api/sessions/${encodeURIComponent(result.session_id)}/coach-chat`, jsonBody('POST', {question: chatInput.value}));
      const sources = payload.evidence?.supporting_shot_frames || [];
      const references = sources.map(source => `${source.metric_value} ${source.unit} (shot ${source.shot_id}${source.frame == null ? '' : `, frame ${source.frame}`})`);
      const samples = (payload.evidence?.metrics || []).map(metric => `${metric.label}: ${metric.sample_count} of ${metric.minimum_required} samples`);
      chatAnswer.textContent = `${payload.answer}\n\n${payload.notice}${samples.length ? `\nMetrics supplied: ${samples.join('; ')}` : ''}${references.length ? `\nEvidence: ${references.join('; ')}` : '\nNo shot-level evidence was available for this answer.'}`;
    } catch (error) {
      chatAnswer.textContent = error.message;
      if (error.code && error.code !== 'rate_limited' && error.code !== 'timeout') showChatStatus({state: error.code, message: error.message});
    }
    finally { chatButton.disabled = false; }
  });

  async function refreshInsights() {
    try {
      const insights = await api(`/api/sessions/${result.session_id}/insights`);
      sessionContext.textContent = `Player ${insights.context?.player_id || ''}, ${describeContext(insights.context)}`;
      renderCue(insights);
    } catch (error) {
      cueCard.replaceChildren(el('h2', {text: 'Personal drill plan'}), el('p', {class: 'hint', text: error.message}));
    }
    refreshCoach();
  }

  // ---------------------------------------------------------------- coach summary
  let coachMarkers = [];
  let attemptAnalysis = {};
  async function refreshCoach() {
    coachCard.replaceChildren(el('h2', {id: 'coach-title', text: 'Coach summary'}),
      el('p', {class: 'hint', text: 'Measuring your mechanics and writing the report…'}),
      skeleton('title', 'line', 'line', 'block', 'line'));
    try {
      const report = await api(`/api/sessions/${encodeURIComponent(result.session_id)}/report`);
      if (activeSessionId !== result.session_id) return;
      currentReport = report;
      renderCoach(report);
    } catch (error) {
      coachCard.replaceChildren(el('h2', {id: 'coach-title', text: 'Coach summary'}), el('p', {class: 'form-error', text: error.message}),
        el('button', {type: 'button', class: 'btn btn-quiet btn-small', onclick: refreshCoach}, 'Try again'));
    }
  }

  function renderCoach(report) {
    const o = report.overview, q = o.quality || {}, ex = report.executive;
    attemptAnalysis = {};
    for (const shot of report.shots) attemptAnalysis[shot.shot_id] = shot;
    coachMarkers = (report.evidence.observations || []).filter(item => item.frame != null).map(item => ({
      frame: item.frame, time_s: item.time_s, attempt: item.attempt, kind: item.kind, title: item.text}));
    renderTimeline();
    const parts = [el('h2', {id: 'coach-title', text: 'Coach summary'})];
    if (q.issues?.length) {
      const banner = el('div', {class: 'quality-banner'}, el('strong', {text: `Recording check: ${q.grade}. `}), q.issues.join(' '));
      if (q.view_matches === false && q.estimated_view) {
        const select = el('select', {'aria-label': 'Camera view for this session'},
          ...Object.entries(LABELS.camera_view).map(([value, label]) => {
            const option = el('option', {value}, label.replace(/^./, c => c.toUpperCase()));
            option.selected = value === q.estimated_view;
            return option;
          }));
        banner.append(el('div', {class: 'inline-form'}, el('label', {}, 'Correct the camera view: ', select),
          el('button', {type: 'button', class: 'btn btn-quiet btn-small', onclick: async () => {
            try {
              await api(`/api/sessions/${encodeURIComponent(result.session_id)}/camera-view`, jsonBody('PUT', {camera_view: select.value}));
              toast('Camera view updated; rebuilding the report.');
              refreshInsights();
            } catch (error) { toast(error.message); }
          }}, 'Save view')));
      }
      parts.push(banner);
    }
    if (q.pose_lagged && reviewApi?.jobId) {
      parts.push(el('div', {class: 'quality-banner'}, (q.notes || []).find(n => n.includes('before 2026-10-25')) || 'This session uses older pose data.',
        el('button', {type: 'button', class: 'btn btn-quiet btn-small', onclick: async () => {
          try {
            const payload = await api(`/api/sessions/${encodeURIComponent(result.session_id)}/refresh-pose`, {method: 'POST'});
            refreshReturnJob = reviewApi.jobId;
            prepareJobPanel('Refreshing pose data', 'queued', payload.message);
            pollJob(payload.job_id);
          } catch (error) { toast(error.message); }
        }}, 'Refresh pose data')));
    }
    parts.push(el('p', {class: 'coach-summary-text', text: o.summary}));
    const focus = ex.first_focus;
    if (focus) {
      parts.push(el('div', {class: 'focus-mini'}, el('span', {class: 'focus-label', text: 'Work on this first'}),
        el('strong', {text: focus.title}), el('p', {text: focus.action}), el('small', {text: focus.reason})));
    }
    const list = el('ul', {class: 'coach-list'});
    for (const finding of [...ex.improvements, ...ex.strengths, ...ex.possible_issues]) {
      const stamps = (finding.timestamps || []).slice(0, 4).map(t => el('button', {type: 'button', class: 'ts ts-link',
        onclick: () => seekToFrame(t.frame), title: t.label}, `A${t.attempt} ${mmss(t.time_s)}`));
      list.append(el('li', {class: `coach-item coach-${finding.kind}`},
        el('span', {class: 'coach-kind', text: finding.kind === 'strength' ? 'Strength' : 'Work on'}),
        el('div', {}, el('strong', {text: finding.title}), el('span', {class: `conf conf-${finding.confidence}`, text: finding.confidence, tabindex: '0', 'data-tip': finding.confidence_reason}),
          el('p', {text: finding.observed}), stamps.length ? el('div', {class: 'ts-row'}, ...stamps) : null)));
    }
    if (list.childElementCount) parts.push(list);
    else parts.push(el('p', {class: 'abstain', text: 'No strength or correction was supported strongly enough to show. Confirm attempts in the list above, or film a clearer clip; the full report still lists every measurement.'}));
    parts.push(el('button', {type: 'button', class: 'btn btn-primary', onclick: () => { reportSessionId = result.session_id; setView('report'); }}, 'Open full report'));
    coachCard.replaceChildren(...parts);
    enter(coachCard.querySelectorAll('.coach-summary-text, .focus-mini, .quality-banner, .coach-item'), {stagger: 0.05, y: 10});
    renderEditorMeasurements();
  }

  function renderEditorMeasurements() {
    const host = editor.querySelector('.attempt-measures');
    const shot = shots[selected];
    if (!host || !shot) return;
    const analysis = attemptAnalysis[shot.shot_id];
    host.replaceChildren();
    if (!analysis) { host.append(el('p', {class: 'hint', text: 'Measurements appear here once the report is ready.'})); return; }
    const usable = analysis.measurements.filter(m => m.confidence === 'high' || m.confidence === 'medium');
    const items = usable.slice(0, 8).map(m => el('li', {},
      el('span', {text: m.label}), el('b', {text: m.display}),
      m.time_s != null ? el('button', {type: 'button', class: 'ts ts-link', onclick: () => seekToFrame(m.frame), title: 'Show this frame'}, mmss(m.time_s)) : el('span')));
    host.append(el('h4', {text: 'Measured on this attempt'}),
      items.length ? el('ul', {class: 'measure-list'}, ...items) : el('p', {class: 'hint', text: 'No measurement had enough landmark visibility on this attempt.'}),
      el('p', {class: 'hint', text: [...analysis.strengths.map(x => `✓ ${x}`), ...analysis.opportunities.map(x => `△ ${x}`)].join('   ') || ''}));
  }

  function renderCue(insights) {
    cueCard.replaceChildren();
    cueCard.classList.toggle('cue-card', Boolean(insights.cue));
    if (!insights.cue) {
      const have = insights.cohort_approved_valid_shots || 0;
      const need = insights.minimum_required || 5;
      cueCard.append(el('h2', {text: 'Personal drill plan'}),
        el('p', {class: 'hint', text: 'A drill you can track over time unlocks once you have confirmed five well-tracked attempts in the same camera view and shot type.'}),
        el('p', {class: 'abstain', style: 'margin-top:14px', text: insights.message || 'No cue yet: the evidence threshold is not met.'}),
        el('div', {class: 'gate-meter'},
          el('div', {class: 'progress-track', role: 'img', 'aria-label': `${Math.min(have, need)} of ${need} approved attempts`}, el('div', {style: `width:${Math.min(100, (have / need) * 100)}%`})),
          el('span', {text: `${have} of ${need} approved`})),
        el('p', {class: 'hint', style: 'margin-top:10px', text: 'Counts approved, well-tracked attempts for this player with the same camera view, shot type and style.'}));
      return;
    }
    const cue = insights.cue;
    cueCard.append(el('span', {class: 'cue-kicker', text: 'Personal drill plan · from your confirmed history'}),
      el('h3', {text: cue.cue_title || 'Practice cue'}),
      el('p', {text: cue.biomechanical_evidence || cue.evidence || ''}));
    if (cue.recommended_drill) {
      cueCard.append(el('p', {class: 'cue-drill', text: `${cue.recommended_drill}${cue.drill_reps ? `, ${cue.drill_reps} reps` : ''}${cue.target_goal ? `. Goal: ${cue.target_goal}` : ''}`}));
    }
    if (cue.priority_tier > 0) {
      const planButton = el('button', {type: 'button', class: 'btn btn-primary', style: 'margin-top:14px'}, 'Add drill to my practice plan');
      planButton.addEventListener('click', async () => {
        planButton.disabled = true;
        try {
          const payload = await api(`/api/sessions/${encodeURIComponent(result.session_id)}/remediation`, {method: 'POST'});
          planButton.textContent = payload.already_active ? 'You already have an active drill' : 'Added to practice plan';
          toast(payload.already_active ? 'An active drill is already in your plan' : 'Drill added. Compare a later session from Progress.');
        } catch (error) { planButton.disabled = false; planButton.textContent = error.message; }
      });
      cueCard.append(planButton);
    }
    const evidenceList = el('div', {class: 'evidence-list'});
    for (const evidence of insights.evidence || []) {
      const item = el('div', {class: 'evidence-item'},
        el('span', {text: `${evidence.metric_value} ${evidence.unit}${evidence.frame == null ? '' : ` at frame ${evidence.frame}`} (${evidence.shot_id}${evidence.current_session ? '' : ', earlier session'})`}));
      if (evidence.current_session && evidence.frame != null) {
        item.append(el('button', {type: 'button', class: 'btn btn-quiet btn-small', onclick: () => { seekToFrame(evidence.frame); video.scrollIntoView({block: 'center'}); }}, 'Show in replay'));
      } else if (evidence.job_id && evidence.frame != null) {
        item.append(el('a', {class: 'btn btn-quiet btn-small', target: '_blank', rel: 'noopener',
          href: `/api/jobs/${evidence.job_id}/video#t=${(evidence.frame / Number(evidence.fps || 30)).toFixed(3)}`}, 'Open clip'));
      }
      evidenceList.append(item);
    }
    if (evidenceList.childElementCount) cueCard.append(evidenceList);
    cueCard.append(el('small', {class: 'cue-caveat', text: 'Thresholds are prototype starting points, not clinical standards. This describes your mechanics; it does not prove a mechanic caused a make or miss.'}));
  }

  function renderManualPanel() {
    const inputs = {start: null, release: null, end: null};
    const status = el('p', {class: 'review-save-status', 'aria-live': 'polite'});
    const row = el('div', {class: 'manual-grid'});
    for (const [key, label] of [['start', 'Start'], ['release', 'Release'], ['end', 'End']]) {
      const input = el('input', {type: 'number', min: '0', max: String(frameCount - 1), inputmode: 'numeric', placeholder: 'frame'});
      inputs[key] = input;
      row.append(el('label', {class: 'field'}, `${label} frame`, input,
        el('button', {type: 'button', class: 'btn btn-quiet btn-small', onclick: () => { input.value = currentFrame(); }}, 'Use current frame')));
    }
    const save = el('button', {type: 'button', class: 'btn btn-primary btn-small'}, 'Add attempt');
    save.addEventListener('click', async () => {
      const values = Object.fromEntries(Object.entries(inputs).map(([k, input]) => [k, input.value.trim() === '' ? null : Number(input.value)]));
      if (Object.values(values).some(v => v == null || !Number.isInteger(v))) { status.textContent = 'Set a start, release and end frame (play the clip and use “Use current frame”).'; return; }
      save.disabled = true;
      try {
        const payload = await api(`/api/sessions/${encodeURIComponent(result.session_id)}/shots`, jsonBody('POST',
          {start_frame: values.start, release_frame: values.release, end_frame: values.end}));
        shots.push({...payload.shot});
        shots.sort((a, b) => (frameOf(a, 'start') ?? 0) - (frameOf(b, 'start') ?? 0));
        selectAttempt(shots.findIndex(s => s.shot_id === payload.shot.shot_id), true);
        for (const input of Object.values(inputs)) input.value = '';
        status.textContent = payload.message;
        manualPanel.open = false;
        toast('Attempt added');
        refreshInsights();
      } catch (error) { status.textContent = error.message; }
      finally { save.disabled = false; }
    });
    manualPanel.replaceChildren(el('summary', {text: 'Add an attempt the detector missed'}),
      el('p', {class: 'hint', text: 'Play or scrub the replay to each moment and press “Use current frame”. Added attempts count as confirmed by you.'}),
      row, save, status);
  }

  reviewApi = {
    jobId, sessionId: result.session_id,
    seekTime: (time, attempt) => {
      if (attempt != null && shots[attempt - 1]) selectAttempt(attempt - 1, false);
      seekToFrame(Math.round(time * fps));
      video.scrollIntoView({block: 'center', behavior: 'smooth'});
    },
  };
  if (shots.length) selectAttempt(0, false);
  else { renderList(); renderTimeline(); renderEditor(); }
  renderManualPanel();
  refreshInsights();
  results.classList.remove('hidden');
  if (!results.dataset.entered || results.dataset.entered !== result.session_id) {
    results.dataset.entered = result.session_id;
    enter(results.children, {stagger: 0.06});
    for (const node of statNumbers) {
      const target = Number(node.textContent.replace(/[^0-9]/g, ''));
      countUp(node, target);
    }
    enter(list.children, {delay: 0.2, stagger: 0.035, y: 10});
  }
  if (pendingSeek && pendingSeek.sessionId === result.session_id) {
    const target = pendingSeek;
    pendingSeek = null;
    const apply = () => reviewApi.seekTime(target.time, target.attempt);
    if (video.readyState >= 1) apply(); else video.addEventListener('loadedmetadata', apply, {once: true});
  }
}

function frameOrDash(value) { return value == null ? 'not marked' : value; }

/* ----------------------------------------------------------------- progress */
progressPlayer.addEventListener('change', () => {
  const value = progressPlayer.value.trim();
  if (!PLAYER_ID_PATTERN.test(value)) { historySummary.textContent = 'Player ID can use letters, numbers, - and _ only.'; return; }
  storage('set', 'shotLabPlayerId', value);
  playerIdInput.value = value;
  loadPlayerHistory(value);
});
weeklyTarget.addEventListener('change', async () => {
  const playerId = progressPlayer.value.trim();
  try {
    await api(`/api/players/${encodeURIComponent(playerId)}/goal`, jsonBody('PUT', {weekly_session_target: Number(weeklyTarget.value)}));
    toast(`Weekly goal set to ${weeklyTarget.value} session${weeklyTarget.value === '1' ? '' : 's'}`);
    loadPlayerHistory(playerId);
  } catch (error) { historySummary.textContent = error.message; }
});

function goalRing(done, goal) {
  const radius = 40, circumference = 2 * Math.PI * radius;
  const ratio = Math.min(1, goal ? done / goal : 0);
  const svg = svgEl('svg', {class: 'goal-ring', viewBox: '0 0 100 100', role: 'img', 'aria-label': `${done} of ${goal} sessions this week`});
  svg.append(svgEl('circle', {class: 'ring-bg', cx: 50, cy: 50, r: radius}));
  const ring = svgEl('circle', {class: 'ring-fg', cx: 50, cy: 50, r: radius, 'stroke-dasharray': circumference, 'stroke-dashoffset': circumference * (1 - ratio)});
  svg.append(ring);
  if (motionOn()) {
    ring.setAttribute('stroke-dashoffset', circumference);
    requestAnimationFrame(() => Motion.animate(ring, {strokeDashoffset: [circumference, circumference * (1 - ratio)]}, {duration: 1, ease: EASE_OUT, delay: 0.15}));
  }
  const text = svgEl('text', {x: 50, y: 58});
  text.textContent = `${done}/${goal}`;
  svg.append(text);
  return svg;
}

async function loadPlayerHistory(playerId, currentSessionId = activeSessionId) {
  playerId = (playerId || '').trim();
  if (!PLAYER_ID_PATTERN.test(playerId)) return;
  progressPlayer.value = playerId;
  if (!historyList.childElementCount) historyList.replaceChildren(skeleton('block', 'block'));
  try {
    const history = await api(`/api/players/${encodeURIComponent(playerId)}/history`);
    const goal = history.weekly_target || 3;
    weeklyTarget.value = String(goal);
    historyOverview.replaceChildren(
      el('section', {class: 'card goal-card'}, goalRing(history.eligible_sessions_this_week || 0, goal),
        el('div', {}, el('h2', {text: 'This week'}), el('span', {text: `Counted sessions toward your goal of ${goal}. Weeks start on Monday (UTC).`}))),
      el('section', {class: 'card'}, el('strong', {class: 'big', text: history.active_streak_days || 0}), el('span', {text: 'day practice streak'})),
      el('section', {class: 'card'}, el('strong', {class: 'big', text: history.total_eligible_sessions || 0}), el('span', {text: 'counted sessions in total'})));
    historySummary.textContent = `${history.activity_definition || ''} ${history.consistency_definition || ''}`.trim();
    renderPlan(history, playerId, currentSessionId);
    renderHistoryCharts(history.sessions || []);
    historyList.replaceChildren();
    for (const session of history.sessions || []) historyList.append(sessionItem(session, playerId));
    const firstLoad = historyOverview.dataset.player !== playerId;
    historyOverview.dataset.player = playerId;
    if (firstLoad) {
      enter(historyOverview.children, {stagger: 0.07});
      for (const big of historyOverview.querySelectorAll('strong.big')) countUp(big, Number(big.textContent));
      enter(historyList.children, {delay: 0.15, stagger: 0.05, y: 16});
    }
    revealOnScroll(historyCharts.querySelectorAll('.chart-card'));
    if (!(history.sessions || []).length) {
      historyList.append(el('div', {class: 'card empty-state'},
        el('span', {class: 'empty-icon', 'aria-hidden': 'true'}, iconEl('i-progress')),
        el('h3', {text: `No sessions for ${playerId} yet`}),
        el('p', {text: 'Analyze a clip and approve its attempts to start tracking progress.'}),
        el('div', {class: 'empty-actions'}, el('a', {class: 'btn btn-primary', href: '#new'}, 'Start a session'))));
    }
  } catch (error) { historySummary.textContent = error.message; }
}

function renderPlan(history, playerId, currentSessionId) {
  historyPlan.replaceChildren();
  const active = history.active_remediation;
  const latest = history.latest_remediation;
  const parse = text => { try { return JSON.parse(text || '{}'); } catch { return {}; } };
  if (active) {
    const meta = parse(active.feedback_notes);
    const status = el('p', {text: `Saved ${formatDate(active.created_at)}. Compare a later session with the same camera view, shot type and style, and at least five approved measurements.`});
    const card = el('section', {class: 'card plan-card'}, el('h3', {text: `Current drill: ${active.targeted_flaw}`}),
      el('p', {text: `${active.recommended_drill}, ${active.drill_reps} reps`}), status);
    if (currentSessionId && currentSessionId !== meta.source_session_id) {
      const compare = el('button', {type: 'button', class: 'btn btn-quiet'}, 'Compare the open session to before the drill');
      compare.addEventListener('click', async () => {
        compare.disabled = true;
        compare.textContent = 'Checking evidence…';
        try {
          const payload = await api(`/api/remediations/${encodeURIComponent(active.remediation_id)}/follow-up`, jsonBody('PUT', {session_id: currentSessionId}));
          toast(payload.comparison.notice);
          loadPlayerHistory(playerId, currentSessionId);
        } catch (error) { compare.disabled = false; compare.textContent = 'Compare the open session to before the drill'; status.textContent = error.message; }
      });
      card.append(compare);
    }
    historyPlan.append(card);
  } else if (latest?.status === 'completed') {
    const meta = parse(latest.feedback_notes);
    historyPlan.append(el('section', {class: 'card plan-card'}, el('h3', {text: `Completed drill: ${latest.targeted_flaw}`}),
      el('p', {text: latest.post_drill_metric_mean == null
        ? 'Marked complete; no matching follow-up session has been compared.'
        : `Before ${fmt(latest.pre_drill_metric_mean, 2)} ± ${fmt(latest.pre_drill_metric_std, 2)}, after ${fmt(latest.post_drill_metric_mean, 2)} ± ${fmt(latest.post_drill_metric_std, 2)} (${meta.follow_up_sample_count || 'unknown'} approved measurements). A before/after description, not proof the drill caused the change.`})));
  }
}

function dateParts(value) {
  if (!value) return null;
  const date = new Date(value.includes('T') ? value : `${value.replace(' ', 'T')}Z`);
  if (Number.isNaN(date.getTime())) return null;
  return {day: date.getDate(), month: date.toLocaleString(undefined, {month: 'short'})};
}

function sessionItem(session, playerId) {
  const lines = el('ul', {class: 'lines'});
  for (const [key, metric] of Object.entries(session.metrics || {})) {
    if (metric.mean == null) continue;
    const delta = session.session_deltas?.[key];
    lines.append(el('li', {text: `${metric.label}: ${metric.mean} ± ${metric.sample_std} ${metric.unit} (${metric.sample_count} measurements)${delta ? `, ${delta.delta > 0 ? '+' : ''}${delta.delta} vs previous comparable session` : ''}`}));
  }
  for (const drift of Object.values(session.within_session_change || {})) {
    lines.append(el('li', {text: `${drift.label}, early vs late in session: ${drift.early_mean} to ${drift.late_mean}. Describes change only; not a fatigue measure.`}));
  }
  if (!lines.childElementCount) lines.append(el('li', {text: 'No mechanic has five approved measurements in this session yet.'}));
  const count = session.approved_sufficient_shots;
  const actions = el('div', {class: 'session-actions'});
  if (session.job_id) {
    actions.append(el('button', {type: 'button', class: 'btn btn-primary btn-small', onclick: () => openSession(session.job_id)}, count ? 'Open review' : 'Review attempts'));
    actions.append(el('button', {type: 'button', class: 'btn btn-quiet btn-small', onclick: () => { reportSessionId = session.session_id; setView('report'); }}, 'Report'));
  }
  const deleteButton = el('button', {type: 'button', class: 'btn btn-danger btn-small'}, 'Delete');
  deleteButton.addEventListener('click', async () => {
    const confirmed = await confirmDialog({
      title: 'Delete this session?',
      description: `The session from ${formatDate(session.created_at)} will be removed from this computer: its attempts, reviews, report, linked drill, uploaded video, keyframes and pose data. This cannot be undone.`,
      confirmLabel: 'Delete session',
    });
    if (!confirmed) return;
    deleteButton.disabled = true;
    try {
      const payload = await api(`/api/sessions/${encodeURIComponent(session.session_id)}`, {method: 'DELETE'});
      if (session.session_id === activeSessionId) { storage('remove', 'shotLabLastJobId'); clearReview(); }
      const card = deleteButton.closest('.session-item');
      if (card && motionOn()) await Motion.animate(card, {opacity: 0, x: -24, scale: 0.98}, {duration: 0.25, ease: EASE_OUT});
      toast(payload.warnings?.length ? payload.warnings.join(' ') : 'Session and its local files deleted');
      loadPlayerHistory(playerId, activeSessionId);
    } catch (error) { deleteButton.disabled = false; historySummary.textContent = error.message; }
  });
  actions.append(deleteButton);
  const parts = dateParts(session.created_at);
  return el('article', {class: `card session-item${session.session_id === activeSessionId ? ' is-current' : ''}`},
    el('div', {class: 'session-date', 'aria-hidden': 'true'}, el('b', {text: parts ? parts.day : '—'}), el('small', {text: parts ? parts.month : ''})),
    el('div', {}, el('h3', {text: formatDate(session.created_at)}),
      el('p', {class: 'meta'}, `${describeContext(session).replace(/^./, c => c.toUpperCase())}. `,
        el('span', {class: `chip ${count ? 'chip-approved' : 'chip-quarantined'}`, text: count ? `${count} approved` : 'Not counted yet'}))),
    actions, lines);
}

function drawChartOnView(svg) {
  if (!motionOn()) return;
  const line = svg.querySelector('.chart-line');
  const points = [...svg.querySelectorAll('.chart-point')];
  for (const point of points) point.setAttribute('opacity', '0');
  const stop = Motion.inView(svg, () => {
    stop();
    const length = line.getTotalLength ? line.getTotalLength() : 600;
    line.style.strokeDasharray = `${length}`;
    Motion.animate(line, {strokeDashoffset: [length, 0]}, {duration: 1.1, ease: EASE_OUT})
      .then(() => { line.style.strokeDasharray = ''; });
    Motion.animate(points, {opacity: [0, 1], scale: [0.3, 1]}, {...SPRING, delay: Motion.stagger(0.12, {startDelay: 0.2})});
  }, {amount: 0.4});
}

function renderHistoryCharts(sessions) {
  historyCharts.replaceChildren();
  const latest = sessions.find(session => session.approved_sufficient_shots > 0);
  const comparable = latest ? sessions.filter(session => session.approved_sufficient_shots > 0 &&
    session.camera_view === latest.camera_view && session.shot_type === latest.shot_type && session.shot_style === latest.shot_style).reverse() : [];
  for (const [metricKey, latestMetric] of Object.entries(latest?.metrics || {})) {
    const points = comparable.map(session => ({session, metric: session.metrics?.[metricKey]})).filter(point => Number.isFinite(point.metric?.mean));
    if (points.length < 2) continue;
    const lows = points.map(p => p.metric.mean - (p.metric.sample_std || 0));
    const highs = points.map(p => p.metric.mean + (p.metric.sample_std || 0));
    let min = Math.min(...lows), max = Math.max(...highs);
    const pad = max === min ? Math.max(Math.abs(max) * 0.05, 1) : (max - min) * 0.1;
    min -= pad; max += pad;
    const x0 = 46, x1 = 504, y0 = 16, y1 = 132;
    const y = value => y1 - ((value - min) * (y1 - y0)) / (max - min);
    const coords = points.map((point, index) => ({...point, x: x0 + (index * (x1 - x0)) / (points.length - 1), y: y(point.metric.mean)}));
    const svg = svgEl('svg', {viewBox: '0 0 520 160', role: 'img', 'aria-label': `${latestMetric.label} across ${points.length} comparable sessions`});
    for (const value of [max, (min + max) / 2, min]) {
      svg.append(svgEl('line', {x1: x0, x2: x1, y1: y(value), y2: y(value), class: 'chart-grid-line'}));
      const label = svgEl('text', {x: 4, y: y(value) + 4, class: 'chart-label'});
      label.textContent = fmt(value, 1);
      svg.append(label);
    }
    for (const point of coords) {
      const sd = point.metric.sample_std || 0;
      svg.append(svgEl('rect', {x: point.x - 5, y: y(point.metric.mean + sd), width: 10, height: Math.max(1, y(point.metric.mean - sd) - y(point.metric.mean + sd)), rx: 3, class: 'chart-band'}));
    }
    svg.append(svgEl('polyline', {points: coords.map(p => `${p.x},${p.y}`).join(' '), class: 'chart-line'}));
    coords.forEach((point, index) => {
      const circle = svgEl('circle', {cx: point.x, cy: point.y, r: 5, class: 'chart-point'});
      const tip = svgEl('title', {});
      tip.textContent = `${formatDate(point.session.created_at)}: ${point.metric.mean} ± ${point.metric.sample_std}, n=${point.metric.sample_count}`;
      circle.append(tip);
      svg.append(circle);
      const label = svgEl('text', {x: point.x, y: 152, 'text-anchor': 'middle', class: 'chart-label'});
      label.textContent = `S${index + 1}`;
      svg.append(label);
    });
    drawChartOnView(svg);
    historyCharts.append(el('article', {class: 'card chart-card'},
      el('h3', {text: `${latestMetric.label} (${latestMetric.unit})`}), svg,
      el('small', {text: `Oldest to newest, ${describeContext(latest)} only. Dots are session means; bars show ± one standard deviation. Each session has at least five approved measurements.`})));
  }
  if (!historyCharts.childElementCount) {
    historyCharts.append(el('p', {class: 'hint', text: 'Charts appear once two comparable sessions each have at least five approved measurements of the same mechanic.'}));
  }
}

/* ------------------------------------------------------------- pose overlay */
const CONNECTIONS = [[11, 12], [11, 13], [13, 15], [12, 14], [14, 16], [11, 23], [12, 24], [23, 24], [23, 25],
  [25, 27], [24, 26], [26, 28], [27, 29], [29, 31], [27, 31], [28, 30], [30, 32], [28, 32]];
const ARM = {right: [12, 14, 16], left: [11, 13, 15]};
const LEG = {right: [24, 26, 28], left: [23, 25, 27]};

function framePoints(poseData, frame) {
  // Format 2 caches hold raw landmarks; average x/y over neighbouring frames (no time lag).
  const current = poseData.frames[frame];
  if (!current || !current.length || (poseData.format || 1) < 2) return current;
  return current.map((point, j) => {
    if (!point || !point[3]) return point;
    let x = 0, y = 0, n = 0;
    for (const [f, weight] of [[frame - 1, 1], [frame, 2], [frame + 1, 1]]) {
      const other = poseData.frames[f]?.[j];
      if (other && other[3]) { x += weight * other[0]; y += weight * other[1]; n += weight; }
    }
    return [x / n, y / n, point[2], point[3]];
  });
}

function jointAngle(a, b, c, w, h) {
  if (!a || !b || !c) return null;
  const v1 = [(a[0] - b[0]) * w, (a[1] - b[1]) * h], v2 = [(c[0] - b[0]) * w, (c[1] - b[1]) * h];
  const n1 = Math.hypot(...v1), n2 = Math.hypot(...v2);
  if (n1 < 1e-6 || n2 < 1e-6) return null;
  return Math.acos(Math.max(-1, Math.min(1, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))) * 180 / Math.PI;
}

function drawPoseOverlay(video, canvas, poseData, videoMetadata, options = {}) {
  if (!canvas || !videoMetadata) return;
  const width = video.clientWidth, height = video.clientHeight;
  if (!width || !height) return;
  const dpr = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  if (!poseData || !video.videoWidth) return;

  const vw = video.videoWidth || Number(videoMetadata.width) || 1280;
  const vh = video.videoHeight || Number(videoMetadata.height) || 720;
  const displayedWidth = Math.min(width, (height * vw) / vh);
  const displayedHeight = Math.min(height, (width * vh) / vw);
  const offsetX = (width - displayedWidth) / 2, offsetY = (height - displayedHeight) / 2;
  const sx = displayedWidth / vw;
  const sy = displayedHeight / vh;
  const mapX = px => offsetX + px * sx;
  const mapY = py => offsetY + py * sy;

  const totalFrames = (poseData.frames?.length) || (poseData.ball_rim?.length) || 1;
  const frame = Math.min(totalFrames - 1, Math.max(0, Math.round(video.currentTime * Number(videoMetadata.fps || 30))));

  // 1. Ball & Rim Overlay
  if (options.ball !== false && poseData.ball_rim && poseData.ball_rim.length > 0) {
    const trk = poseData.ball_rim[frame];

    // Rim box & Target Reticle
    const rimBox = trk?.rim || poseData._lastRim;
    const rimConf = trk?.rim ? trk.rim_conf : poseData._lastRimConf;
    if (trk?.rim) {
      poseData._lastRim = trk.rim;
      poseData._lastRimConf = trk.rim_conf;
    }
    if (rimBox) {
      const [rx1, ry1, rx2, ry2] = rimBox;
      const rx = mapX(rx1);
      const ry = mapY(ry1);
      const rw = (rx2 - rx1) * sx;
      const rh = (ry2 - ry1) * sy;
      const rcx = rx + rw / 2;
      const rcy = ry + rh / 2;

      ctx.save();
      ctx.strokeStyle = '#ff6b00';
      ctx.lineWidth = 2.5;
      ctx.shadowColor = 'rgba(255, 107, 0, 0.8)';
      ctx.shadowBlur = 10;
      ctx.strokeRect(rx, ry, rw, rh);

      const targetR = Math.min(rw, rh) * 0.35;
      ctx.beginPath();
      ctx.arc(rcx, rcy, targetR, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(255, 107, 0, 0.9)';
      ctx.lineWidth = 2;
      ctx.stroke();

      ctx.beginPath();
      ctx.moveTo(rcx - targetR * 1.3, rcy);
      ctx.lineTo(rcx + targetR * 1.3, rcy);
      ctx.moveTo(rcx, rcy - targetR * 1.3);
      ctx.lineTo(rcx, rcy + targetR * 1.3);
      ctx.strokeStyle = 'rgba(255, 107, 0, 0.6)';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      const rimConfPct = Math.round((rimConf || 0.89) * 100);
      const tagText = `RIM ${rimConfPct}%`;
      ctx.font = 'bold 12px Inter, system-ui, sans-serif';
      const tagW = ctx.measureText(tagText).width + 14;
      ctx.fillStyle = '#ff6b00';
      ctx.fillRect(rx, Math.max(0, ry - 20), tagW, 20);
      ctx.fillStyle = '#ffffff';
      ctx.fillText(tagText, rx + 7, Math.max(14, ry - 6));
      ctx.restore();
    }

    // Parabolic Flight Arc / Trail
    let trail = null;
    const shot = options.selectedShot;
    if (shot && poseData.ball_rim) {
      const relFrame = frameOf(shot, 'release') ?? frameOf(shot, 'start') ?? 0;
      const endFrame = Math.min(poseData.ball_rim.length - 1, (frameOf(shot, 'end') ?? relFrame) + 60);
      const shotTrail = [];
      for (let f = relFrame; f <= endFrame; f++) {
        const b = poseData.ball_rim[f]?.ball;
        if (b) shotTrail.push([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]);
      }
      if (shotTrail.length > 1) {
        trail = shotTrail;
      }
    }
    if (!trail && poseData.ball_rim) {
      const recent = [];
      const startF = Math.max(0, frame - 25);
      for (let f = startF; f <= frame; f++) {
        const b = poseData.ball_rim[f]?.ball;
        if (b) recent.push([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]);
      }
      if (recent.length > 1) trail = recent;
    }

    if (trail && trail.length > 1) {
      ctx.save();
      ctx.strokeStyle = '#ff8c00';
      ctx.lineWidth = 3.5;
      ctx.shadowColor = 'rgba(255, 140, 0, 0.9)';
      ctx.shadowBlur = 12;
      ctx.beginPath();
      for (let i = 0; i < trail.length; i++) {
        const tx = mapX(trail[i][0]);
        const ty = mapY(trail[i][1]);
        if (i === 0) ctx.moveTo(tx, ty);
        else ctx.lineTo(tx, ty);
      }
      ctx.stroke();

      for (let i = 0; i < trail.length; i++) {
        const tx = mapX(trail[i][0]);
        const ty = mapY(trail[i][1]);
        ctx.beginPath();
        ctx.arc(tx, ty, 3, 0, Math.PI * 2);
        ctx.fillStyle = '#fbbf24';
        ctx.fill();
      }
      ctx.restore();
    }

    // Ball Detection Circle & Badge
    if (trk && trk.ball) {
      const [bx1, by1, bx2, by2] = trk.ball;
      const bx = mapX(bx1);
      const by = mapY(by1);
      const bw = (bx2 - bx1) * sx;
      const bh = (by2 - by1) * sy;
      const bcx = bx + bw / 2;
      const bcy = by + bh / 2;

      ctx.save();
      ctx.strokeStyle = '#38bdf8';
      ctx.lineWidth = 2.5;
      ctx.shadowColor = 'rgba(56, 189, 248, 0.8)';
      ctx.shadowBlur = 10;
      ctx.beginPath();
      ctx.arc(bcx, bcy, Math.max(bw, bh) / 2, 0, Math.PI * 2);
      ctx.stroke();

      const ballConfPct = Math.round((trk.ball_conf || 0.9) * 100);
      const tagText = `BALL ${ballConfPct}%`;
      ctx.font = 'bold 11px Inter, system-ui, sans-serif';
      const tagW = ctx.measureText(tagText).width + 12;
      ctx.fillStyle = '#38bdf8';
      ctx.fillRect(bx, Math.max(0, by - 18), tagW, 18);
      ctx.fillStyle = '#0f172a';
      ctx.fillText(tagText, bx + 6, Math.max(13, by - 5));
      ctx.restore();
    }
  }

  // 2. Pose Skeleton & Joint Angles
  if (options.pose !== false && poseData.frames?.length) {
    const points = framePoints(poseData, frame);
    if (points && points.length) {
      const byJoint = new Map(poseData.landmark_indices.map((joint, index) => [joint, points[index]]));
      const visible = point => point && point[3] && point[2] >= 0.25;
      const px = point => [offsetX + point[0] * displayedWidth, offsetY + point[1] * displayedHeight];
      ctx.lineCap = 'round';
      for (const [a, b] of CONNECTIONS) {
        const p1 = byJoint.get(a), p2 = byJoint.get(b);
        if (!visible(p1) || !visible(p2)) continue;
        ctx.beginPath(); ctx.moveTo(...px(p1)); ctx.lineTo(...px(p2));
        ctx.strokeStyle = 'rgba(16,21,29,.55)'; ctx.lineWidth = 6; ctx.stroke();
        ctx.strokeStyle = '#f2b705'; ctx.lineWidth = 3; ctx.stroke();
      }
      for (const [joint, point] of byJoint.entries()) {
        if (joint < 11 || !visible(point)) continue;
        ctx.beginPath(); ctx.arc(...px(point), 4, 0, Math.PI * 2);
        ctx.fillStyle = '#ffffff'; ctx.fill();
        ctx.lineWidth = 2; ctx.strokeStyle = '#10151d'; ctx.stroke();
      }
      if (options.angles) {
        const side = options.side || (() => {
          const l = byJoint.get(15), r = byJoint.get(16);
          return visible(l) && visible(r) && l[1] < r[1] ? 'left' : 'right';
        })();
        const label = (joints, name) => {
          const [a, b, c] = joints.map(j => byJoint.get(j));
          if (![a, b, c].every(visible)) return;
          const angle = jointAngle(a, b, c, vw, vh);
          if (angle == null) return;
          const [x, y] = px(b);
          const text = `${name} ${Math.round(angle)}°`;
          ctx.font = '600 13px Archivo, system-ui, sans-serif';
          const w = ctx.measureText(text).width + 10;
          ctx.fillStyle = 'rgba(16,21,29,.82)';
          ctx.fillRect(Math.min(width - w - 2, x + 10), y - 11, w, 22);
          ctx.fillStyle = '#ffffff';
          ctx.fillText(text, Math.min(width - w - 2, x + 10) + 5, y + 5);
        };
        label(ARM[side], 'Elbow');
        const legSide = [LEG.left, LEG.right].map(js => js.reduce((sum, j) => sum + (byJoint.get(j)?.[2] || 0), 0));
        label(legSide[0] > legSide[1] ? LEG.left : LEG.right, 'Knee');
      }
    }
  }
}

/* ------------------------------------------------------------------- report */
async function showReport(sessionId, {refresh = false} = {}) {
  if (!sessionId) {
    reportEmpty.classList.remove('hidden');
    reportRoot.replaceChildren();
    reportPrint.disabled = true;
    reportRefresh.disabled = true;
    reportWorkout.disabled = true;
    reportStatus.textContent = '';
    return;
  }
  reportSessionId = sessionId;
  reportEmpty.classList.add('hidden');
  reportRefresh.disabled = false;
  reportPrint.disabled = true;
  reportStatus.textContent = refresh ? 'Rebuilding the report…' : 'Loading the report…';
  if (!currentReport || currentReport.meta.session_id !== sessionId || refresh || !reportRoot.childElementCount) {
    reportRoot.replaceChildren(el('div', {class: 'report-section'}, skeleton('title', 'line', 'line', 'block'), skeleton('line', 'line', 'block')));
  }
  try {
    const report = await api(`/api/sessions/${encodeURIComponent(sessionId)}/report${refresh ? '?refresh=1' : ''}`);
    currentReport = report;
    window.ShotLabReport.render(reportRoot, report, {
      onSeek: (time, attempt) => {
        if (reviewApi && reviewApi.sessionId === sessionId) {
          setView('review');
          reviewApi.seekTime(time, attempt);
        } else if (report.meta.job_id) {
          pendingSeek = {sessionId, time, attempt};
          openSession(report.meta.job_id);
        }
      },
    });
    reportPrint.disabled = false;
    reportWorkout.disabled = false;
    const cover = reportRoot.querySelector('.report-cover');
    if (cover) cover.after(workoutCta(sessionId));
    animateReport();
    reportStatus.textContent = report.meta.from_cache ? `Saved report from ${formatDate(report.meta.generated_at)}` : `Generated ${formatDate(report.meta.generated_at)}`;
  } catch (error) {
    reportStatus.textContent = '';
    reportRoot.replaceChildren(el('div', {class: 'form-error', text: error.message}));
  }
}
let tocObserver = null;
function animateReport() {
  enter(reportRoot.querySelectorAll('.report-cover > *, .report-toc'), {stagger: 0.06});
  revealOnScroll(reportRoot.querySelectorAll('.report-section, .keyframe-row'));
  // Highlight the table-of-contents chip for the section being read.
  if (tocObserver) tocObserver.disconnect();
  const links = new Map([...reportRoot.querySelectorAll('.report-toc a')].map(a => [a.getAttribute('href').slice(1), a]));
  if (!('IntersectionObserver' in window) || !links.size) return;
  tocObserver = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      for (const link of links.values()) link.removeAttribute('aria-current');
      links.get(entry.target.id)?.setAttribute('aria-current', 'true');
    }
  }, {rootMargin: '-35% 0px -55% 0px'});
  for (const id of links.keys()) {
    const section = document.getElementById(id);
    if (section) tocObserver.observe(section);
  }
}
reportPrint.addEventListener('click', () => window.print());
function openWorkoutFor(sessionId) {
  if (!sessionId) return;
  workoutSessionId = sessionId;
  storage('set', 'shotLabWorkoutSession', sessionId);
  setView('workout');
}
const reportWorkout = $('#report-workout');
reportWorkout.addEventListener('click', () => openWorkoutFor(reportSessionId));
function workoutCta(sessionId) {
  return el('section', {class: 'workout-cta no-print', 'aria-labelledby': 'workout-cta-title'},
    el('div', {},
      el('p', {class: 'eyebrow', text: 'Next step'}),
      el('h2', {id: 'workout-cta-title', text: 'Turn this report into a workout'}),
      el('p', {text: 'Builds a plan of 20 minutes or more from the findings above, the equipment you have and how you feel today. You review it before you start.'})),
    el('button', {type: 'button', class: 'btn btn-primary', id: 'report-workout-cta', onclick: () => openWorkoutFor(sessionId)},
      iconEl('i-workout'), 'Generate My Personalized Workout'));
}
// Collapsed <details> do not print their content; open them for printing, then restore.
let printOpened = [];
window.addEventListener('beforeprint', () => {
  printOpened = [...reportRoot.querySelectorAll('details:not([open])')];
  printOpened.forEach(node => { node.open = true; });
});
window.addEventListener('afterprint', () => { printOpened.forEach(node => { node.open = false; }); printOpened = []; });
reportRefresh.addEventListener('click', () => showReport(reportSessionId, {refresh: true}));

/* -------------------------------------------------------------- phone access */
async function loadPhoneCard() {
  const card = $('#phone-card');
  const body = $('#phone-body');
  try {
    const info = await api('/api/connection');
    card.classList.remove('hidden');
    if (!info.lan_enabled) {
      body.replaceChildren(
        el('p', {text: 'Phone access is off, so only this computer can open the app. To use your phone on the same Wi-Fi (upload and camera recording), stop the app and start it again with:'}),
        el('pre', {class: 'cmd'}, 'python web_app.py --lan --https'),
        el('p', {class: 'hint', text: 'The terminal then shows an address and an access code to enter on the phone. Only devices on your private network can connect.'}));
      return;
    }
    const url = info.urls[0];
    body.replaceChildren(
      el('p', {text: 'On your phone, join the same Wi-Fi, open this address in Safari or Chrome, and enter the access code.'}),
      el('dl', {class: 'phone-facts'},
        el('dt', {text: 'Address'}), el('dd', {}, el('code', {text: url || 'See the terminal'})),
        el('dt', {text: 'Access code'}), el('dd', {}, el('code', {class: 'access-code', text: info.access_code}))),
      url ? el('button', {type: 'button', class: 'btn btn-quiet btn-small', onclick: async () => {
        try { await navigator.clipboard.writeText(`${url}?token=${info.access_code}`); toast('Link copied. Send it only to your own phone.'); }
        catch { toast('Copy failed; type the address and code instead.'); }
      }}, 'Copy one-tap link') : null,
      info.https_builtin ? el('p', {class: 'hint'},
        'Camera recording on the phone needs it to trust this computer\'s Shot Lab certificate (once per phone). On the phone, open ',
        el('code', {text: info.setup_url || `${url || ''}shotlab-ca.crt`}),
        ' and follow the steps. Fingerprint to compare: ', el('code', {class: 'fingerprint', text: info.ca_fingerprint || ''})) : null,
      (info.tls_problems || []).length ? el('div', {class: 'quality-banner', role: 'status'},
        el('strong', {text: 'A device could not connect securely. '}),
        ...(info.tls_problems || []).map(problem => el('span', {text: `${problem.ip} (${Math.max(1, Math.round(problem.seconds_ago / 60))} min ago): ${problem.hint} `}))) : null,
      el('p', {class: 'hint', text: info.tls ? 'HTTPS is on, so the camera can record in the phone\'s browser.' : 'Uploading from the photo library works now. Recording with the phone camera needs HTTPS: restart with --lan --https (see README).'}));
  } catch {
    card.classList.add('hidden');  // shown only on the computer running the app
  }
}

/* --------------------------------------------------------------------- boot */
(function boot() {
  const savedPlayer = storage('get', 'shotLabPlayerId');
  if (savedPlayer && PLAYER_ID_PATTERN.test(savedPlayer)) playerIdInput.value = savedPlayer;
  progressPlayer.value = playerIdInput.value;
  const requested = location.hash.slice(1);
  const lastJob = storage('get', 'shotLabLastJobId');
  if (lastJob && /^[a-f0-9]{32}$/.test(lastJob)) {
    prepareJobPanel('Restoring your last session', 'queued', 'Loading saved analysis and reviews.');
    pollJob(lastJob);
  }
  setView(VIEWS.includes(requested) ? requested : 'new', {push: true});
  syncThemeUi();
  moveNavIndicator(false);
  moveSegmentThumb(false);
  setupHeroParallax();
  loadPhoneCard();
  document.fonts?.ready.then(() => { moveNavIndicator(false); moveSegmentThumb(false); });
})();



/* ========================================================================
   DRILLS MODULE v2
   - 4 video-backed dribbling drills
   - Side-by-side: reference video (9:16 shorts) + live camera feed
   - Rep counter via frame-diff motion tracking
   - Post-drill form feedback card
   ======================================================================== */

const drillsState = {
  catalog: null,
  activeDrill: null,
  stream: null,
  animFrame: null,
  timerInterval: null,
  elapsedSeconds: 0,
  repCount: 0,
  repTimestamps: [],       // epoch ms of each counted rep (for rhythm graph)
  counting: false,
  // dribble detection
  prevY: null,
  direction: null,
  lastValley: null,
  lastPeak: null,
  BOUNCE_THRESHOLD: 16,
  prevFrameData: null,
};

// ---------------------------------------------------------------- DOM refs
const drillsCatalog      = document.getElementById('drills-catalog');
const drillRunner        = document.getElementById('drill-runner');
const drillRefVideo      = document.getElementById('drill-ref-video');
const drillCamVideo      = document.getElementById('drill-cam-video');
const drillCamCanvas     = document.getElementById('drill-cam-canvas');
const drillCamStatus     = document.getElementById('drill-cam-status');
const drillRepCount      = document.getElementById('drill-rep-count');
const drillBigCount      = document.getElementById('drill-big-count');
const drillTimerEl       = document.getElementById('drill-timer');
const drillStartCam      = document.getElementById('drill-start-cam');
const drillStopBtn       = document.getElementById('drill-stop');
const drillDoneBtn       = document.getElementById('drill-done');
const drillBackBtn       = document.getElementById('drill-back');
const drillRunnerName    = document.getElementById('drill-runner-name');
const drillRunnerCat     = document.getElementById('drill-runner-category');
const drillRunnerDiff    = document.getElementById('drill-runner-difficulty');
const drillRunnerHow     = document.getElementById('drill-runner-how');
const drillRunnerCues    = document.getElementById('drill-runner-cues');
const drillFeedbackPanel = document.getElementById('drill-feedback-panel');
const drillFeedbackList  = document.getElementById('drill-feedback-list');
const drillFeedbackSummary = document.getElementById('drill-feedback-summary');
const filterCategory     = document.getElementById('drills-filter-category');
const filterDifficulty   = document.getElementById('drills-filter-difficulty');

const DIFFICULTY_COLOURS = {
  beginner:     'approved',
  intermediate: 'caution',
  advanced:     'review',
};

// ---------------------------------------------------------------- init
let drillsViewInitialised = false;
function initDrillsView() {
  if (drillsViewInitialised) return;
  drillsViewInitialised = true;
  loadDrillCatalog();
  if (filterCategory)   filterCategory.addEventListener('change', renderDrillCards);
  if (filterDifficulty) filterDifficulty.addEventListener('change', renderDrillCards);
  if (drillStartCam)    drillStartCam.addEventListener('click', startDrillSession);
  if (drillStopBtn)     drillStopBtn.addEventListener('click', stopDrillSession);
  if (drillDoneBtn)     drillDoneBtn.addEventListener('click', showDrillCatalogView);
  if (drillBackBtn)     drillBackBtn.addEventListener('click', showDrillCatalogView);
}

// ---------------------------------------------------------------- catalog
async function loadDrillCatalog() {
  try {
    drillsState.catalog = await api('/api/drills');
    renderDrillCards();
  } catch (err) {
    if (drillsCatalog) drillsCatalog.innerHTML =
      `<p class="form-error">Could not load drills: ${err.message}</p>`;
  }
}

function renderDrillCards() {
  if (!drillsState.catalog) return;
  const catFilter  = filterCategory  ? filterCategory.value  : '';
  const diffFilter = filterDifficulty ? filterDifficulty.value : '';
  let drills = drillsState.catalog.drills;
  if (catFilter)  drills = drills.filter(d => d.category === catFilter);
  if (diffFilter) drills = drills.filter(d => d.difficulty === diffFilter);

  // Remove any previous grid but keep the page-head inside drills-catalog
  const oldGrid = drillsCatalog.querySelector('.drills-grid');
  if (oldGrid) oldGrid.remove();
  const oldMsg = drillsCatalog.querySelector('.hint');
  if (oldMsg) oldMsg.remove();

  if (!drills.length) {
    drillsCatalog.append(el('p', {class: 'hint', text: 'No drills match that filter.'}));
    return;
  }

  const grid = el('div', {class: 'drills-grid'}, ...drills.map(buildDrillCard));
  drillsCatalog.append(grid);
}

function buildDrillCard(drill) {
  const diffColour = DIFFICULTY_COLOURS[drill.difficulty] || 'neutral';
  return el('article', {
      class: 'drill-card', 'data-drill-id': drill.id,
      role: 'button', tabindex: '0',
      onclick: () => openDrillRunner(drill),
      onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDrillRunner(drill); } },
    },
    // thumbnail on top — 9:16 shorts aspect, capped by CSS max-height
    el('div', {class: 'drill-card-thumb'},
      el('video', {
        src: `/drills/${drill.video}`,
        class: 'drill-card-thumb-video',
        muted: true, preload: 'metadata', playsinline: true,
        'aria-hidden': 'true',
      }),
      el('span', {class: 'drill-card-play-icon', 'aria-hidden': 'true'},
        iconEl('i-play')
      )
    ),
    // text body below the thumbnail
    el('div', {class: 'drill-card-body'},
      el('div', {class: 'drill-card-header'},
        el('span', {class: `difficulty-badge difficulty-${diffColour}`, text: drill.difficulty}),
        el('span', {class: 'drill-card-dur', text: drill.duration})
      ),
      el('h3', {class: 'drill-card-title', text: drill.name}),
      el('p',  {class: 'drill-card-how',   text: drill.how}),
      el('div', {class: 'drill-card-skills'},
        ...(drill.skills || []).map(s => el('span', {class: 'skill-chip', text: s}))
      )
    )
  );
}

// ---------------------------------------------------------------- runner
function openDrillRunner(drill) {
  drillsState.activeDrill = drill;

  // Fill runner header
  drillRunnerName.textContent = drill.name;
  drillRunnerCat.textContent  = (drillsState.catalog.categories || {})[drill.category] || drill.category;
  drillRunnerDiff.textContent = drill.difficulty;
  drillRunnerDiff.className   = `difficulty-badge difficulty-${DIFFICULTY_COLOURS[drill.difficulty] || 'neutral'}`;
  drillRunnerHow.textContent  = drill.how;

  // Cues list
  drillRunnerCues.replaceChildren(
    ...(drill.cues || []).map(cue =>
      el('li', {class: 'drill-cue-item'},
        el('span', {class: 'drill-cue-dot', 'aria-hidden': 'true'}),
        cue
      )
    )
  );

  // Load reference video
  if (drillRefVideo) {
    drillRefVideo.src = `/drills/${drill.video}`;
    drillRefVideo.loop = true;
    drillRefVideo.load();
  }

  // Reset
  resetDrillCounters();
  if (drillFeedbackPanel) drillFeedbackPanel.hidden = true;

  // Hide catalog, show runner
  drillsCatalog.hidden = true;
  drillRunner.hidden   = false;
  drillStartCam.hidden  = false;
  drillStopBtn.hidden   = true;
  drillDoneBtn.hidden   = true;
  if (drillCamStatus) drillCamStatus.textContent = '';
  // show placeholder, hide actual video elements until camera starts
  const placeholder = document.getElementById('drill-cam-placeholder');
  if (placeholder) placeholder.classList.remove('hidden');
}

function showDrillCatalogView() {
  stopDrillSession();
  if (drillRefVideo) { drillRefVideo.pause(); drillRefVideo.src = ''; }
  drillRunner.hidden   = true;
  drillsCatalog.hidden = false;
  drillsState.activeDrill = null;
  window.scrollTo({top: 0});
}

// ---------------------------------------------------------------- counters
function resetDrillCounters() {
  drillsState.repCount       = 0;
  drillsState.elapsedSeconds = 0;
  drillsState.repTimestamps  = [];
  drillsState.prevY          = null;
  drillsState.direction      = null;
  drillsState.lastPeak       = null;
  drillsState.lastValley     = null;
  drillsState.prevFrameData  = null;
  updateRepDisplay(0);
  updateTimerDisplay(0);
}

function updateRepDisplay(n) {
  if (drillRepCount) drillRepCount.textContent = n;
  if (drillBigCount) drillBigCount.textContent = n;
}

function updateTimerDisplay(secs) {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  if (drillTimerEl) drillTimerEl.textContent = `${m}:${String(s).padStart(2, '0')}`;
}

// ---------------------------------------------------------------- camera session
async function startDrillSession() {
  if (drillCamStatus) drillCamStatus.textContent = 'Requesting camera…';
  drillStartCam.disabled = true;

  try {
    drillsState.stream = await navigator.mediaDevices.getUserMedia({
      video: {width: {ideal: 640}, height: {ideal: 480}, facingMode: 'user'},
      audio: false,
    });
  } catch (err) {
    if (drillCamStatus) drillCamStatus.textContent =
      `Camera unavailable: ${err.message}. You can still follow along with the video.`;
    drillStartCam.disabled = false;
    // Still play the reference video
    drillRefVideo?.play();
    return;
  }

  drillCamVideo.srcObject = drillsState.stream;
  await new Promise(resolve => { drillCamVideo.onloadedmetadata = resolve; });
  drillCamVideo.play();

  drillCamCanvas.width  = drillCamVideo.videoWidth  || 640;
  drillCamCanvas.height = drillCamVideo.videoHeight || 480;

  // hide placeholder
  const placeholder = document.getElementById('drill-cam-placeholder');
  if (placeholder) placeholder.classList.add('hidden');

  // Play the reference video alongside
  drillRefVideo?.play();

  if (drillCamStatus) drillCamStatus.textContent = '';
  drillStartCam.hidden = true;
  drillStopBtn.hidden  = false;

  drillsState.counting = true;
  startDrillTimer();
  startFrameLoop();
}

function stopDrillSession() {
  drillsState.counting = false;

  if (drillsState.stream) {
    drillsState.stream.getTracks().forEach(t => t.stop());
    drillsState.stream = null;
    drillCamVideo.srcObject = null;
  }
  if (drillsState.animFrame) {
    cancelAnimationFrame(drillsState.animFrame);
    drillsState.animFrame = null;
  }
  if (drillsState.timerInterval) {
    clearInterval(drillsState.timerInterval);
    drillsState.timerInterval = null;
  }

  drillRefVideo?.pause();

  // restore placeholder
  const placeholder = document.getElementById('drill-cam-placeholder');
  if (placeholder) placeholder.classList.remove('hidden');

  drillStopBtn.hidden  = true;
  drillDoneBtn.hidden  = false;
  drillStartCam.hidden = false;
  drillStartCam.disabled = false;

  // Show form feedback
  showFormFeedback();
}

function startDrillTimer() {
  if (drillsState.timerInterval) clearInterval(drillsState.timerInterval);
  drillsState.timerInterval = setInterval(() => {
    drillsState.elapsedSeconds++;
    updateTimerDisplay(drillsState.elapsedSeconds);
  }, 1000);
}

// ---------------------------------------------------------------- frame loop
function startFrameLoop() {
  const ctx = drillCamCanvas.getContext('2d');

  function loop() {
    if (!drillsState.counting) return;
    drillsState.animFrame = requestAnimationFrame(loop);
    const w = drillCamCanvas.width;
    const h = drillCamCanvas.height;

    // Draw mirrored camera feed
    ctx.save();
    ctx.translate(w, 0);
    ctx.scale(-1, 1);
    ctx.drawImage(drillCamVideo, 0, 0, w, h);
    ctx.restore();

    detectDribble(ctx, w, h);
    drawCamHud(ctx, w, h);
  }

  drillsState.animFrame = requestAnimationFrame(loop);
}

// ---------------------------------------------------------------- dribble detection
// Motion centroid in lower 45% of frame: track down→up bounce cycles.
function detectDribble(ctx, w, h) {
  const ROI_TOP  = Math.floor(h * 0.45);
  const ROI_H    = h - ROI_TOP;
  const STEP_W   = Math.max(1, Math.floor(w / 4));
  const STEP_H   = Math.max(1, Math.floor(ROI_H / 4));

  const imageData = ctx.getImageData(0, ROI_TOP, w, ROI_H);
  const pixels    = imageData.data;
  const prev      = drillsState.prevFrameData;

  if (!prev || prev.length !== pixels.length) {
    drillsState.prevFrameData = new Uint8ClampedArray(pixels);
    return;
  }

  let totalWeight = 0, weightedY = 0;
  for (let py = 0; py < ROI_H; py += STEP_H) {
    for (let px = 0; px < w; px += STEP_W) {
      const i = (py * w + px) * 4;
      const motion = (Math.abs(pixels[i]-prev[i]) + Math.abs(pixels[i+1]-prev[i+1]) + Math.abs(pixels[i+2]-prev[i+2])) / 3;
      if (motion > 20) { totalWeight += motion; weightedY += py * motion; }
    }
  }
  drillsState.prevFrameData = new Uint8ClampedArray(pixels);
  if (totalWeight < 200) return;

  const centroidY = weightedY / totalWeight;
  const prevY = drillsState.prevY;
  drillsState.prevY = centroidY;
  if (prevY === null) return;

  const dy = centroidY - prevY;
  const THRESH = drillsState.BOUNCE_THRESHOLD;

  if (dy > 2) {
    if (drillsState.direction !== 'down') {
      drillsState.direction = 'down';
      drillsState.lastValley = centroidY;
    }
  } else if (dy < -2 && drillsState.direction === 'down') {
    const excursion = (drillsState.lastValley || centroidY) - (drillsState.lastPeak || 0);
    if (excursion > THRESH) {
      drillsState.repCount++;
      drillsState.repTimestamps.push(Date.now());
      updateRepDisplay(drillsState.repCount);
      flashRepIndicator();
    }
    drillsState.direction = 'up';
    drillsState.lastPeak  = centroidY;
  }
}

function flashRepIndicator() {
  if (!drillBigCount) return;
  drillBigCount.classList.remove('rep-flash');
  void drillBigCount.offsetWidth;
  drillBigCount.classList.add('rep-flash');
}

function drawCamHud(ctx, w, h) {
  const reps = drillsState.repCount;
  const m = Math.floor(drillsState.elapsedSeconds / 60);
  const s = drillsState.elapsedSeconds % 60;
  ctx.save();
  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  ctx.beginPath();
  ctx.roundRect(10, 10, 120, 62, 8);
  ctx.fill();
  ctx.fillStyle = '#ff8a3d';
  ctx.font = 'bold 20px system-ui,sans-serif';
  ctx.fillText(`${reps} reps`, 20, 36);
  ctx.fillStyle = '#aab3bf';
  ctx.font = '14px system-ui,sans-serif';
  ctx.fillText(`${m}:${String(s).padStart(2,'0')}`, 20, 58);
  ctx.restore();
}

// ---------------------------------------------------------------- form feedback
/*
  Heuristic form checks based on:
  - repTimestamps → rhythm consistency (are the gaps even?)
  - elapsedSeconds + repCount → dribble rate (too slow = not low enough / not powered)
  - No pose model in browser; these are pattern-based estimates with honest caveats.
*/
function showFormFeedback() {
  if (!drillFeedbackPanel || !drillFeedbackList) return;
  const drill    = drillsState.activeDrill;
  const reps     = drillsState.repCount;
  const secs     = drillsState.elapsedSeconds;
  const checks   = drill?.form_checks || [];
  const labels   = (drillsState.catalog?.form_check_labels) || {};
  const stamps   = drillsState.repTimestamps;

  // --- compute rhythm score (0–1): std dev of inter-rep intervals
  let rhythmScore = null;
  let avgRate = null;
  if (stamps.length >= 4) {
    const gaps = [];
    for (let i = 1; i < stamps.length; i++) gaps.push(stamps[i] - stamps[i-1]);
    const mean = gaps.reduce((a,b) => a+b, 0) / gaps.length;
    const variance = gaps.reduce((a,b) => a + (b-mean)**2, 0) / gaps.length;
    const cv = Math.sqrt(variance) / mean; // coefficient of variation; lower = more consistent
    rhythmScore = Math.max(0, 1 - cv * 2);   // 0–1
    avgRate = reps / Math.max(1, secs);       // reps per second
  }

  // --- build feedback items
  const items = [];

  if (reps === 0) {
    items.push({status: 'neutral', text: 'No reps were counted. Make sure your dribbling hand is visible in the lower part of the camera frame.'});
  } else {
    // Rep count context
    const expected = secs > 0 ? Math.round(secs * 2.5) : null; // ~2.5 reps/sec is a reasonable active pace
    if (expected && reps >= expected * 0.75) {
      items.push({status: 'good', text: `Solid pace — ${reps} reps in ${secs}s. Keep that energy up.`});
    } else if (expected && reps < expected * 0.5) {
      items.push({status: 'tip', text: `${reps} reps in ${secs}s is on the slower side. Try to push the ball down harder and faster to build rhythm.`});
    } else {
      items.push({status: 'good', text: `${reps} reps counted in ${secs}s.`});
    }

    // Rhythm feedback
    if (rhythmScore !== null) {
      if (rhythmScore >= 0.75) {
        items.push({status: 'good', text: 'Good rhythm — your dribble timing was consistent.'});
      } else if (rhythmScore >= 0.45) {
        items.push({status: 'tip', text: 'Rhythm was a bit uneven. Try counting "1-2-1-2" out loud to lock in the beat.'});
      } else {
        items.push({status: 'tip', text: 'Inconsistent rhythm detected. Slow down first, get the timing smooth, then build speed.'});
      }
    }
  }

  // Drill-specific cue reminders (these are always shown as reminders, not measurements)
  for (const checkKey of checks) {
    const label = labels[checkKey];
    if (label) {
      items.push({status: 'remind', text: label});
    }
  }

  // Render
  drillFeedbackList.replaceChildren(
    ...items.map(item =>
      el('li', {class: `feedback-item feedback-${item.status}`},
        el('span', {class: 'feedback-icon', 'aria-hidden': 'true'},
          item.status === 'good'   ? '✓' :
          item.status === 'tip'    ? '↑' :
          item.status === 'remind' ? '●' : '○'
        ),
        el('span', {class: 'feedback-text', text: item.text})
      )
    )
  );

  if (drillFeedbackSummary) {
    drillFeedbackSummary.textContent = reps > 0
      ? `You completed ${reps} rep${reps !== 1 ? 's' : ''} in ${secs}s. Compare your technique with the reference video above.`
      : 'Drill ended. Watch the reference video and try again.';
  }

  drillFeedbackPanel.hidden = false;
  drillFeedbackPanel.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}
