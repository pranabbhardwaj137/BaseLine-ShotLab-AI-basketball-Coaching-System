'use strict';
/* Baseline Shot Lab — Personalized Workout Coach (page + player).
   Plans come from the server (built from the persisted report of ONE shooting session). The player
   is a small state machine: work (guided repetitions or a timer) → rest → next set/exercise.
   Minimal voice: the exercise name once when a new exercise starts, then only the final 10% of each
   count, spoken in descending order. Rest is silent. The counter is a guided pace, never presented
   as detected or verified movement. */

(function () {
  const root = document.getElementById('workout-root');
  if (!root) return;
  const MotionLib = window.Motion || null;
  const reduceMotion = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  const motionOn = () => Boolean(MotionLib) && !(reduceMotion && reduceMotion.matches);
  const EASE = [0.22, 1, 0.36, 1];
  const ACTIVE_KEY = 'shotLabActiveWorkout';
  const TICK_MS = 100;
  const SAVE_EVERY_MS = 10000;

  /* ------------------------------------------------------------------ helpers */
  function h(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
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
  const svgIcon = (id, cls = 'icon') => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', cls);
    svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', `#${id}`);
    svg.append(use);
    return svg;
  };
  function storage(action, key, value) {
    try {
      if (action === 'get') return localStorage.getItem(key);
      if (action === 'set') localStorage.setItem(key, value);
      if (action === 'remove') localStorage.removeItem(key);
    } catch { /* storage may be unavailable */ }
    return null;
  }
  async function api(path, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    const headers = {...(options.headers || {})};
    if (method !== 'GET') headers['X-Shotlab'] = '1';
    let response;
    try {
      response = await fetch(path, {cache: 'no-store', ...options, headers});
    } catch {
      throw Object.assign(new Error('Could not reach Shot Lab. Check that the app is still running.'), {status: 0});
    }
    let payload = {};
    try { payload = await response.json(); } catch { payload = {}; }
    if (!response.ok) throw Object.assign(new Error(payload.error || `Request failed (${response.status})`), {status: response.status});
    return payload;
  }
  const jsonBody = (method, body) => ({method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const notify = message => (typeof window.toast === 'function' ? window.toast(message) : null);
  const fmtClock = seconds => {
    const s = Math.max(0, Math.round(seconds));
    const m = Math.floor(s / 60);
    return `${m}:${String(s % 60).padStart(2, '0')}`;
  };
  const fmtMinutes = seconds => `${Math.round(seconds / 60)} min`;
  const fmtDate = value => {
    if (!value) return 'unknown date';
    const date = new Date(value.includes('T') ? value : `${value.replace(' ', 'T')}Z`);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'});
  };
  const enter = (nodes, opts = {}) => {
    const list = [...(nodes || [])].filter(n => n && n.nodeType === 1);
    if (!list.length || !motionOn()) return;
    MotionLib.animate(list, {opacity: [0, 1], y: [opts.y ?? 12, 0]},
      {duration: 0.45, ease: EASE, delay: MotionLib.stagger(opts.stagger ?? 0.05, {startDelay: opts.delay ?? 0})});
  };

  /* Count the final 10%: spokenCount = max(1, ceil(N × 0.10)). Exposed for tests. */
  function spokenCount(total) {
    return Math.min(total, Math.max(1, Math.ceil(total * 0.1)));
  }
  const setTarget = item => item.target * (item.per_side ? 2 : 1);

  /* ------------------------------------------------------------------ voice
     One utterance at a time: every call cancels anything queued, so speech never overlaps. */
  const Voice = {
    supported: 'speechSynthesis' in window && typeof window.SpeechSynthesisUtterance === 'function',
    enabled: true,
    speak(text) {
      if (!this.supported || !this.enabled) return false;
      try {
        window.speechSynthesis.cancel();
        const utterance = new window.SpeechSynthesisUtterance(String(text));
        utterance.rate = 1.0;
        window.speechSynthesis.speak(utterance);
        return true;
      } catch { return false; }
    },
    cancel() {
      if (!this.supported) return;
      try { window.speechSynthesis.cancel(); } catch { /* ignore */ }
    },
  };

  /* ------------------------------------------------------------------ page state */
  let sessionId = null;
  let context = null;
  let workout = null;      // server record {workout_id, plan, state, progress, status, ...}
  let player = null;       // running player instance
  let formState = null;    // last chosen preferences (kept when going back from the plan)

  function show(id, {workoutId} = {}) {
    sessionId = id || null;
    const target = workoutId || null;
    if (player && player.workoutId && (!target || target === player.workoutId)) {
      player.mount();
      return;
    }
    if (target) return openWorkout(target);
    const saved = storage('get', ACTIVE_KEY);
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        if (parsed && parsed.workout_id && (!sessionId || parsed.session_id === sessionId)) {
          return openWorkout(parsed.workout_id, {fallbackSession: sessionId});
        }
      } catch { storage('remove', ACTIVE_KEY); }
    }
    if (!sessionId) return renderNoSession();
    loadContext();
  }

  function hide() {
    if (player) player.pause('left the page');
  }

  function renderNoSession() {
    root.replaceChildren(h('div', {class: 'empty-state'},
      h('span', {class: 'empty-icon', 'aria-hidden': 'true'}, svgIcon('i-workout')),
      h('h1', {text: 'No shooting report selected'}),
      h('p', {text: 'A workout is built from one session’s shooting report. Open a report and choose “Generate My Personalized Workout”.'}),
      h('div', {class: 'empty-actions'}, h('a', {class: 'btn btn-primary', href: '#progress'}, 'Choose a session'),
        h('a', {class: 'btn btn-quiet', href: '#report'}, 'Open the current report'))));
  }

  function pageHead(subtitle) {
    return h('header', {class: 'page-head wk-head'},
      h('div', {},
        h('p', {class: 'eyebrow'}, 'Personalized Workout Coach'),
        h('h1', {id: 'workout-title', text: 'Your workout'}),
        h('p', {text: subtitle})));
  }

  async function loadContext() {
    root.replaceChildren(pageHead('Reading your shooting report…'),
      h('div', {class: 'card'}, h('div', {class: 'skeleton-wrap', 'aria-hidden': 'true'},
        h('span', {class: 'skeleton skeleton-title'}), h('span', {class: 'skeleton skeleton-line'}), h('span', {class: 'skeleton skeleton-block'}))));
    try {
      context = await api(`/api/sessions/${encodeURIComponent(sessionId)}/workout-context`);
    } catch (error) {
      root.replaceChildren(pageHead('The workout planner needs a finished shooting report.'),
        h('p', {class: 'form-error', role: 'alert', text: error.message}),
        h('div', {class: 'empty-actions'}, h('a', {class: 'btn btn-quiet', href: '#report'}, 'Back to the report')));
      return;
    }
    renderPlanner();
  }

  /* ------------------------------------------------------------------ stage A–D: planner form */
  const EQUIPMENT_ICON = {
    barbell: 'M2 12h20M5 7v10M8 8.5v7M16 8.5v7M19 7v10', bodyweight: 'M12 5.5a2 2 0 1 0 0-.01M12 8v6M8 10l4-2 4 2M9.5 21l2.5-7 2.5 7',
    cable: 'M5 3v18M19 3v18M5 4h14M12 4v7M10 13h4l-1 7h-2z', dumbbell: 'M3 12h18M6 8v8M3.5 10v4M18 8v8M20.5 10v4',
    machine: 'M4 20h16M6 20V6l6-3v17M12 9h6v11M15 12v4', band: 'M6 6c6 0 6 12 12 12M6 18c6 0 6-12 12-12M4 6h2M18 6h2M4 18h2M18 18h2',
    smith: 'M4 3v18M20 3v18M2 10h20M6 8v4M18 8v4', stretching: 'M13 4.5a1.8 1.8 0 1 0 0-.01M5 20l5-6 3-6 5 3M13 8l1 6 4 6',
    trx: 'M12 2v4M12 6l-5 9M12 6l5 9M5 15h4M15 15h4',
  };
  const equipmentIcon = key => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('class', 'wk-equip-icon');
    svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', EQUIPMENT_ICON[key] || EQUIPMENT_ICON.bodyweight);
    svg.append(path);
    return svg;
  };

  function confChip(level, extra = '') {
    return h('span', {class: `conf conf-${level}`}, `${level}${extra}`);
  }

  function renderSourceCard() {
    const f = context.findings;
    const improvements = f.improvements || [];
    const list = h('ul', {class: 'wk-findings'});
    for (const item of improvements) {
      list.append(h('li', {class: `wk-finding${item.possible ? ' is-possible' : ''}`},
        h('div', {class: 'wk-finding-head'},
          h('span', {class: 'coach-kind wk-kind', text: item.possible ? 'Possible' : 'Work on'}),
          h('strong', {text: item.title}), confChip(item.confidence, ' confidence')),
        h('p', {text: item.observed}),
        item.timestamps?.length ? h('p', {class: 'muted wk-times'}, 'Seen at ',
          item.timestamps.map(t => `attempt ${t.attempt} (${fmtClock(t.time_s)})`).join(', '), '.') : null,
        item.training_note ? h('p', {class: 'wk-limit'}, h('b', {}, 'Limits: '), item.training_note) : null));
    }
    const strengths = (f.strengths || []).map(s => h('li', {}, h('strong', {text: s.title}), ' ', confChip(s.confidence)));
    return h('section', {class: 'card wk-source', 'aria-labelledby': 'wk-source-title'},
      h('header', {class: 'step-head'},
        h('span', {class: 'step-num', 'aria-hidden': 'true'}, 'A'),
        h('div', {}, h('h2', {id: 'wk-source-title', text: 'From your shooting analysis'}),
          h('p', {}, `Session from ${fmtDate(context.source.session_date)}`,
            context.source.video_filename ? ` · ${context.source.video_filename}` : '',
            ` · ${context.source.attempts_total ?? 0} attempts (${context.source.attempts_confirmed ?? 0} confirmed by you)`))),
      h('p', {class: 'wk-summary', text: context.summary}),
      improvements.length ? h('div', {}, h('h3', {class: 'wk-sub', text: 'Improvement areas used for training'}), list)
        : h('p', {class: 'abstain', text: 'No improvement area in this report is supported with enough confidence to personalise training. You can still build a clearly labelled general workout or add your own goals.'}),
      strengths.length ? h('div', {}, h('h3', {class: 'wk-sub', text: 'Strengths to keep'}), h('ul', {class: 'wk-plain'}, strengths)) : null,
      (f.technique_only || []).length ? h('div', {}, h('h3', {class: 'wk-sub', text: 'Practise on court, not in the gym'}),
        h('ul', {class: 'wk-plain'}, f.technique_only.map(t => h('li', {}, h('strong', {text: t.title}), ` — ${t.note}`)))) : null,
      h('details', {class: 'wk-details'}, h('summary', {text: 'What the report cannot tell us'}),
        h('ul', {class: 'wk-plain'}, [...f.not_assessed, ...(f.uncertainty || [])].map(text => h('li', {text})))));
  }

  function renderPlanner() {
    const defaults = context.defaults;
    const prefs = formState || {equipment: [], fitness_level: defaults.fitness_level, duration_min: defaults.duration_min,
      goals: [], avoid: [], pain: defaults.pain, limitations_note: ''};
    const formError = h('p', {class: 'form-error hidden', role: 'alert', id: 'wk-form-error'});

    // Stage B — equipment
    const equipGrid = h('div', {class: 'wk-equip-grid', role: 'group', 'aria-labelledby': 'wk-equip-title'});
    for (const eq of context.equipment) {
      const input = h('input', {type: 'checkbox', name: 'equipment', value: eq.key});
      input.checked = prefs.equipment.includes(eq.key);
      equipGrid.append(h('label', {class: 'wk-equip'},
        input,
        h('span', {class: 'wk-equip-body'},
          h('span', {class: 'wk-equip-top'}, equipmentIcon(eq.key), h('span', {class: 'wk-check', 'aria-hidden': 'true'})),
          h('strong', {text: eq.label}),
          h('small', {text: eq.description}),
          h('small', {class: 'wk-equip-meta', text: `${eq.exercises} exercises · ${eq.videos} with demo video`}))));
    }
    const equipCard = h('section', {class: 'card form-step', 'aria-labelledby': 'wk-equip-title'},
      h('header', {class: 'step-head'}, h('span', {class: 'step-num', 'aria-hidden': 'true'}, 'B'),
        h('div', {}, h('h2', {id: 'wk-equip-title', text: 'Which equipment can you access for your workout?'}),
          h('p', {text: 'Select everything you can use. Only exercises for the equipment you select are prescribed. Warm-up and cool-down use equipment-free movements.'}))),
      equipGrid,
      h('div', {class: 'wk-equip-actions'},
        h('button', {type: 'button', class: 'btn btn-quiet btn-small', onclick: () => {
          equipGrid.querySelectorAll('input').forEach(i => { i.checked = i.value === 'bodyweight'; });
        }}, 'Bodyweight only'),
        h('button', {type: 'button', class: 'btn btn-quiet btn-small', onclick: () => {
          equipGrid.querySelectorAll('input').forEach(i => { i.checked = false; });
        }}, 'Clear selection')));

    // Stage C — preferences
    const levelRow = h('div', {class: 'choice-row wk-levels'});
    for (const [value, label] of [['beginner', 'Beginner'], ['intermediate', 'Intermediate'], ['advanced', 'Advanced']]) {
      const input = h('input', {type: 'radio', name: 'wk-level', value});
      input.checked = prefs.fitness_level === value;
      levelRow.append(h('label', {}, input, h('span', {text: label})));
    }
    const duration = h('select', {id: 'wk-duration', name: 'duration'},
      context.durations.map(m => { const o = h('option', {value: String(m)}, `${m} minutes${m === 20 ? ' (minimum)' : ''}`); o.selected = m === prefs.duration_min; return o; }));
    const checks = (name, options, selected) => h('div', {class: 'wk-checks'},
      Object.entries(options).map(([value, label]) => {
        const input = h('input', {type: 'checkbox', name, value});
        input.checked = selected.includes(value);
        return h('label', {class: 'wk-check-pill'}, input, h('span', {text: label}));
      }));
    const goalChecks = checks('goals', context.goals, prefs.goals);
    const avoidChecks = checks('avoid', context.avoid, prefs.avoid);
    const pain = h('input', {type: 'checkbox', name: 'pain', value: '1'});
    pain.checked = Boolean(prefs.pain);
    const note = h('textarea', {rows: '2', maxlength: '300', placeholder: 'Optional, for your own reference (e.g. “left knee after long runs”)'});
    note.value = prefs.limitations_note || '';
    const prefCard = h('section', {class: 'card form-step', 'aria-labelledby': 'wk-pref-title'},
      h('header', {class: 'step-head'}, h('span', {class: 'step-num', 'aria-hidden': 'true'}, 'C'),
        h('div', {}, h('h2', {id: 'wk-pref-title', text: 'A few preferences'}),
          h('p', {text: 'Defaults come from your session profile. Change anything that does not fit today.'}))),
      h('div', {class: 'wk-pref-grid'},
        h('fieldset', {class: 'choice-group'}, h('legend', {text: 'Fitness level'}), levelRow),
        h('label', {class: 'field'}, 'Workout length', duration, h('small', {text: 'Every plan is at least 20 minutes, calculated from its own sets and rests.'})),
        h('fieldset', {class: 'wk-fieldset field-wide'}, h('legend', {text: 'Anything you want to add? (optional)'}), goalChecks,
          h('small', {class: 'muted', text: 'These add goals the report cannot measure (for example stamina). They are labelled as your choice in the plan.'})),
        h('fieldset', {class: 'wk-fieldset field-wide'}, h('legend', {text: 'Movements to avoid'}), avoidChecks),
        h('label', {class: 'check-field field-wide'}, pain, h('span', {}, 'I currently have pain or an injury that affects exercise',
          h('small', {text: 'The plan avoids impact and heavier loading and uses lower volumes. It is not rehabilitation; please get pain assessed by a professional.'}))),
        h('label', {class: 'field field-wide'}, h('span', {}, 'Notes about limitations ', h('span', {class: 'optional', text: '(optional)'})), note,
          h('small', {text: 'Saved with the plan for your reference. The planner uses the checkboxes above, not this note.'}))));

    const generate = h('button', {type: 'submit', class: 'btn btn-primary btn-block', id: 'wk-generate'}, 'Generate My Workout', svgIcon('i-arrow-right'));
    const form = h('form', {class: 'wk-form', novalidate: true},
      equipCard, prefCard,
      h('section', {class: 'card form-step'},
        h('header', {class: 'step-head'}, h('span', {class: 'step-num', 'aria-hidden': 'true'}, 'D'),
          h('div', {}, h('h2', {text: 'Generate your plan'}),
            h('p', {text: 'You can review every exercise, and why it was chosen, before you start.'}))),
        formError, generate));

    const collect = () => ({
      equipment: [...equipGrid.querySelectorAll('input:checked')].map(i => i.value),
      fitness_level: levelRow.querySelector('input:checked')?.value || 'beginner',
      duration_min: Number(duration.value),
      goals: [...goalChecks.querySelectorAll('input:checked')].map(i => i.value),
      avoid: [...avoidChecks.querySelectorAll('input:checked')].map(i => i.value),
      pain: pain.checked,
      limitations_note: note.value.trim(),
    });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const chosen = collect();
      formState = chosen;
      formError.classList.add('hidden');
      if (!chosen.equipment.length) {
        formError.textContent = 'Select at least one type of equipment (choose Bodyweight if you have none).';
        formError.classList.remove('hidden');
        equipGrid.querySelector('input')?.focus();
        return;
      }
      generate.disabled = true;
      generate.replaceChildren(h('span', {class: 'wk-spinner', 'aria-hidden': 'true'}), 'Building your workout…');
      try {
        const record = await api(`/api/sessions/${encodeURIComponent(sessionId)}/workouts`, jsonBody('POST', chosen));
        workout = record;
        renderPlan();
        window.scrollTo({top: 0});
      } catch (error) {
        formError.textContent = error.message;
        formError.classList.remove('hidden');
      } finally {
        generate.disabled = false;
        generate.replaceChildren('Generate My Workout', svgIcon('i-arrow-right'));
      }
    });

    const existing = (context.workouts || []);
    const history = existing.length ? h('section', {class: 'card wk-history', 'aria-labelledby': 'wk-history-title'},
      h('h2', {id: 'wk-history-title', text: 'Workouts from this report'}),
      h('ul', {class: 'wk-history-list'}, existing.map(w => h('li', {},
        h('span', {}, h('strong', {text: w.title || 'Workout'}), h('small', {class: 'muted'}, ` ${fmtDate(w.created_at)} · ${fmtMinutes(w.planned_duration_s)} planned`)),
        h('span', {class: `chip ${w.status === 'completed' ? 'chip-approved' : w.status === 'ended_early' ? 'chip-discarded' : 'chip-measure'}`,
          text: {planned: 'Not started', active: 'In progress', completed: 'Completed', ended_early: 'Ended early'}[w.status] || w.status}),
        h('button', {type: 'button', class: 'btn btn-quiet btn-small', onclick: () => openWorkout(w.workout_id)},
          w.status === 'active' ? 'Resume' : w.status === 'planned' ? 'Open plan' : 'View summary'))))) : null;

    root.replaceChildren(pageHead('Built from your shooting report, the equipment you have, and how you feel today.'),
      history, renderSourceCard(), form);
    enter(root.children, {stagger: 0.06});
  }

  /* ------------------------------------------------------------------ plan review */
  function itemDose(item) {
    const target = item.mode === 'time' ? `${item.target} s` : `${item.target} reps`;
    return `${item.sets} × ${target}${item.per_side ? ' each side' : ''}`;
  }
  function restText(item, isLast) {
    const parts = [];
    if (item.sets > 1) parts.push(`${item.rest_between_sets_s} s rest between sets`);
    parts.push(item.rest_after_s ? `${item.rest_after_s} s before the next exercise` : isLast ? 'workout ends' : 'no rest after (next block starts)');
    return parts.join(' · ');
  }
  const PHASE_LABEL = {warmup: 'Warm-up', main: 'Main workout', cooldown: 'Cool-down'};

  function renderPlan() {
    const plan = workout.plan;
    const d = plan.duration;
    const main = plan.items.filter(i => i.phase === 'main');
    const overview = h('section', {class: 'wk-overview monitor'},
      h('div', {class: 'wk-overview-copy'},
        h('p', {class: 'eyebrow eyebrow-on-dark'}, h('span', {class: 'live-dot', 'aria-hidden': 'true'}), plan.general ? 'General workout' : 'Personalized workout'),
        h('h2', {class: 'wk-plan-title', text: plan.title}),
        h('p', {class: 'wk-overview-summary', text: plan.summary}),
        h('p', {class: 'wk-overview-source'}, `From the session of ${fmtDate(plan.source.session_date)}`,
          plan.source.video_filename ? ` (${plan.source.video_filename})` : '', '.')),
      h('dl', {class: 'wk-stats'},
        h('div', {}, h('dt', {text: 'Planned'}), h('dd', {text: fmtMinutes(d.total_s)})),
        h('div', {}, h('dt', {text: 'Exercises'}), h('dd', {text: `${main.length} + warm-up & cool-down`})),
        h('div', {}, h('dt', {text: 'Level'}), h('dd', {text: plan.preferences.fitness_level.replace(/^./, c => c.toUpperCase())})),
        h('div', {}, h('dt', {text: 'Equipment'}), h('dd', {text: plan.equipment_labels.join(', ')}))));

    const priorities = h('section', {class: 'card wk-priorities'},
      h('h2', {text: 'Main improvement priorities'}),
      h('ol', {class: 'wk-priority-list'}, plan.focus.map(f => {
        // strongest two reasons only (weak cross-links such as torso → balance are not repeated here)
        const sources = f.sources.filter(s => s.type !== 'general').sort((a, b) => (b.weight || 0) - (a.weight || 0))
          .filter((s, i) => i === 0 || (s.weight || 0) >= 0.25).slice(0, 2);
        return h('li', {}, h('strong', {text: f.label}),
          h('span', {class: 'muted'}, sources.length ? ` — ${sources.map(s => s.type === 'finding'
            ? `report: ${s.title.toLowerCase()} (${s.confidence}${s.possible ? ', possible' : ''})` : s.type === 'goal' ? `your goal: ${s.title.toLowerCase()}` : s.title.toLowerCase()).join('; ')}`
            : ' — general support (not from a report finding)'));
      })),
      plan.unaddressed.length ? h('div', {class: 'quality-banner'}, h('strong', {text: 'Not covered: '}),
        plan.unaddressed.map(u => `${u.label} — ${u.reason}`).join(' ')) : null,
      plan.adjustments.length ? h('details', {class: 'wk-details'}, h('summary', {text: 'How the planned duration was reached'}),
        h('ul', {class: 'wk-plain'}, plan.adjustments.map(a => h('li', {text: a})))) : null,
      plan.video_policy ? h('p', {class: 'muted wk-video-policy', text: `${plan.video_policy.rule}${plan.video_policy.excluded_count
        ? ` ${plan.video_policy.excluded_count} catalog exercises without a video were not considered.` : ''}`}) : null);

    const safety = h('section', {class: 'card wk-safety', 'aria-labelledby': 'wk-safety-title'},
      h('h2', {id: 'wk-safety-title', text: 'Safety first'}),
      plan.pain_note ? h('p', {class: 'pain-box pain-flagged', text: plan.pain_note}) : null,
      h('ul', {class: 'wk-plain'}, plan.safety.map(s => h('li', {text: s}))));

    const timeline = h('section', {class: 'card wk-plan-list', 'aria-labelledby': 'wk-list-title'},
      h('div', {class: 'wk-list-head'}, h('h2', {id: 'wk-list-title', text: 'Your plan'}),
        h('span', {class: 'muted', text: `Warm-up ${fmtMinutes(d.warmup_s)} · main ${fmtMinutes(d.main_s)} · cool-down ${fmtMinutes(d.cooldown_s)} · total ${fmtClock(d.total_s)}`})));
    for (const phase of ['warmup', 'main', 'cooldown']) {
      const items = plan.items.filter(i => i.phase === phase);
      if (!items.length) continue;
      timeline.append(h('h3', {class: 'wk-phase', text: PHASE_LABEL[phase]}));
      const list = h('ol', {class: 'wk-items'});
      for (const item of items) {
        const r = item.rationale;
        list.append(h('li', {class: 'wk-item'},
          h('div', {class: 'wk-item-main'},
            h('div', {class: 'wk-item-title'}, h('strong', {text: item.name}),
              item.video ? h('span', {class: 'chip chip-approved', text: 'Demo video'})
                : h('span', {class: 'chip chip-discarded', text: item.video_missing ? 'Video file missing — written guide' : 'Written guide'}),
              item.area_label ? h('span', {class: 'chip chip-measure', text: item.area_label}) : null),
            h('p', {class: 'wk-dose'}, h('b', {text: itemDose(item)}), ` · ${restText(item, item === plan.items[plan.items.length - 1])} · about ${fmtClock(item.planned_s)}`),
            item.needs ? h('p', {class: 'muted'}, `Needs: ${item.needs}`) : null),
          phase === 'main' ? h('details', {class: 'wk-why'}, h('summary', {text: 'Why this exercise'}),
            h('dl', {class: 'five-q'},
              h('dt', {text: 'Why it was selected'}), h('dd', {text: r.reason}),
              h('dt', {text: 'Expected benefit'}), h('dd', {text: r.benefit}),
              h('dt', {text: 'Fit for you'}), h('dd', {text: r.fit}),
              h('dt', {text: 'Limits of the evidence'}), h('dd', {text: r.evidence_limit}),
              h('dt', {text: 'Coaching cue'}), h('dd', {text: r.cue}),
              h('dt', {text: 'Easier / harder'}), h('dd', {text: `${r.regression} / ${r.progression}`}))) : null));
      }
      timeline.append(list);
    }
    const statusText = {planned: 'Start workout', active: 'Resume workout'}[workout.status];
    const actions = h('div', {class: 'wk-plan-actions'},
      statusText ? h('button', {type: 'button', class: 'btn btn-primary', id: 'wk-start', onclick: () => startPlayer()}, statusText) : null,
      workout.status === 'planned' ? h('button', {type: 'button', class: 'btn btn-quiet', onclick: () => backToForm()}, 'Change my choices') : null,
      workout.status === 'planned' ? h('button', {type: 'button', class: 'btn btn-danger', onclick: () => discardPlan()}, 'Discard plan') : null,
      ['completed', 'ended_early'].includes(workout.status) ? h('button', {type: 'button', class: 'btn btn-quiet', onclick: () => renderSummary()}, 'View summary') : null);
    const audio = h('p', {class: 'muted wk-audio-note', text: Voice.supported
      ? 'Voice: the exercise name once, then only the last 10% of each count. Rest is silent. You can mute it at any time.'
      : 'Voice guidance is not available in this browser; the workout works fully with on-screen counts.'});
    const bottom = statusText ? h('div', {class: 'wk-plan-actions'},
      h('button', {type: 'button', class: 'btn btn-primary', onclick: () => startPlayer()}, statusText)) : null;
    root.replaceChildren(pageHead(`${fmtMinutes(d.total_s)} planned · ${plan.counting}`), overview, actions, audio, priorities, timeline, safety, bottom || '');
    enter(root.children, {stagger: 0.05});
  }

  function backToForm() {
    if (!context) return loadContext();
    renderPlanner();
    window.scrollTo({top: 0});
  }

  async function discardPlan() {
    const ok = typeof window.confirmDialog === 'function'
      ? await window.confirmDialog({title: 'Discard this plan?', description: 'The generated plan will be deleted. Your shooting report is not affected.', confirmLabel: 'Discard plan'})
      : true;
    if (!ok) return;
    try {
      await api(`/api/workouts/${workout.workout_id}`, {method: 'DELETE'});
      workout = null;
      storage('remove', ACTIVE_KEY);
      notify('Plan discarded');
      loadContext();
    } catch (error) { notify(error.message); }
  }

  async function openWorkout(workoutId, {fallbackSession} = {}) {
    try {
      workout = await api(`/api/workouts/${encodeURIComponent(workoutId)}`);
    } catch (error) {
      storage('remove', ACTIVE_KEY);
      if (fallbackSession) { sessionId = fallbackSession; return loadContext(); }
      root.replaceChildren(pageHead('This workout could not be opened.'), h('p', {class: 'form-error', role: 'alert', text: error.message}));
      return;
    }
    sessionId = workout.session_id;
    if (workout.status === 'active') {
      storage('set', ACTIVE_KEY, JSON.stringify({workout_id: workout.workout_id, session_id: workout.session_id}));
      return startPlayer({restore: true});
    }
    if (['completed', 'ended_early'].includes(workout.status)) {
      storage('remove', ACTIVE_KEY);
      return renderSummary();
    }
    renderPlan();
  }

  /* ------------------------------------------------------------------ player */
  function startPlayer({restore = false} = {}) {
    if (player) player.destroy();
    player = new Player(workout, {restore});
    player.mount();
    if (!restore) player.begin();
  }

  class Player {
    constructor(record, {restore}) {
      this.workoutId = record.workout_id;
      this.plan = record.plan;
      this.items = record.plan.items;
      const saved = record.state || {};
      const progress = record.progress || {};
      this.state = {
        index: saved.index || 0, set: saved.set || 0, phase: saved.phase || 'ready',
        remaining_ms: saved.remaining_ms || 0, rest_total_ms: saved.rest_total_ms || 0, count: saved.count || 0,
        elapsed_ms: saved.elapsed_ms || 0, announced: saved.announced || [], spoken: saved.spoken || [],
        paused: true, voice: saved.voice !== false, rest_kind: saved.rest_kind || null, ending: saved.ending || null,
      };
      if (this.state.phase === 'done' && this.state.ending) this.finalStatus = this.state.ending;
      this.progress = {items: progress.items || {}, active_s: progress.active_s || 0,
        rest_added_s: progress.rest_added_s || 0, rest_skipped: progress.rest_skipped || 0};
      this.repElapsed = 0;
      this.timer = null;
      this.lastTick = 0;
      this.lastSave = 0;
      this.restored = restore;
      this.saving = Promise.resolve();
      Voice.enabled = this.state.voice;
      this.onHide = () => { if (document.visibilityState === 'hidden') this.saveNow(); };
      this.onPageHide = () => this.saveNow({keepalive: true});
      document.addEventListener('visibilitychange', this.onHide);
      window.addEventListener('pagehide', this.onPageHide);
    }

    get item() { return this.items[this.state.index]; }

    record(uid) {
      if (!this.progress.items[uid]) this.progress.items[uid] = {sets: [], skipped: false};
      return this.progress.items[uid];
    }

    /* -------- layout */
    mount() {
      const v = h('video', {class: 'wk-video', muted: true, loop: true, playsinline: true, autoplay: true, preload: 'auto',
        'aria-label': 'Exercise demonstration (muted, loops)'});
      v.muted = true;
      v.loop = true;
      v.playsInline = true;
      v.addEventListener('error', () => this.videoFailed());
      this.video = v;
      this.el = {
        phase: h('span', {class: 'wk-phase-label'}), position: h('span', {class: 'wk-position'}),
        elapsed: h('b', {}), remaining: h('b', {}), planned: h('b', {text: fmtClock(this.plan.duration.total_s)}),
        bar: h('div', {class: 'wk-progress-fill'}),
        media: h('div', {class: 'wk-media'}), guide: h('div', {class: 'wk-guide'}),
        name: h('h2', {class: 'wk-name', id: 'wk-current-name'}), muscles: h('p', {class: 'wk-muscles'}),
        setInfo: h('p', {class: 'wk-setinfo'}), counter: h('p', {class: 'wk-counter', 'aria-live': 'off'}),
        counterLabel: h('p', {class: 'wk-counter-label'}), sideNote: h('p', {class: 'wk-side'}),
        status: h('p', {class: 'wk-status sr-only', 'aria-live': 'polite'}),
        restAfter: h('p', {class: 'muted wk-rest-after'}), next: h('p', {class: 'wk-next'}),
        controls: h('div', {class: 'wk-controls'}), timeline: h('ol', {class: 'wk-timeline'}),
        stage: h('section', {class: 'wk-stage', 'aria-labelledby': 'wk-current-name'}),
      };
      const voiceToggle = h('button', {type: 'button', class: 'btn btn-quiet btn-small wk-voice', 'aria-pressed': String(this.state.voice),
        onclick: () => this.toggleVoice()});
      this.el.voiceToggle = voiceToggle;
      const header = h('div', {class: 'wk-player-head'},
        h('div', {class: 'wk-player-meta'}, this.el.phase, this.el.position),
        h('div', {class: 'wk-player-times'},
          h('span', {}, 'Elapsed ', this.el.elapsed), h('span', {}, 'Remaining ~', this.el.remaining), h('span', {}, 'Planned ', this.el.planned)),
        h('div', {class: 'progress-track wk-progress', role: 'progressbar', 'aria-label': 'Workout progress', 'aria-valuemin': '0', 'aria-valuemax': '100'}, this.el.bar));
      const info = h('div', {class: 'wk-info'},
        h('div', {class: 'wk-info-top'}, this.el.name, voiceToggle),
        this.el.muscles, this.el.setInfo,
        h('div', {class: 'wk-countbox'}, this.el.counter, this.el.counterLabel, this.el.sideNote),
        this.el.status, this.el.controls, this.el.restAfter, this.el.next);
      this.el.stage.append(h('div', {class: 'wk-stage-media monitor'}, this.el.media), info);
      const guideCard = h('section', {class: 'card wk-guide-card', 'aria-label': 'How to do this exercise'}, this.el.guide);
      const timelineCard = h('section', {class: 'card wk-timeline-card', 'aria-labelledby': 'wk-timeline-title'},
        h('h2', {id: 'wk-timeline-title', text: 'Workout timeline'}), this.el.timeline);
      const note = h('p', {class: 'muted wk-guided-note', text: `${this.plan.counting} ${Voice.supported ? '' : 'Voice is not available in this browser; follow the on-screen count.'}`});
      root.replaceChildren(h('div', {class: 'wk-player'}, header, this.el.stage, note, h('div', {class: 'wk-player-lower'}, guideCard, timelineCard)));
      if (this.state.phase === 'done' && this.finalStatus) { this.renderFeedback(); return; }
      this.renderAll();
      if (this.restored && this.state.phase !== 'done') {
        this.el.status.textContent = 'Workout restored and paused. Press Resume to continue.';
        notify('Workout restored where you left it (paused).');
      }
    }

    destroy() {
      this.stopTimer();
      Voice.cancel();
      document.removeEventListener('visibilitychange', this.onHide);
      window.removeEventListener('pagehide', this.onPageHide);
    }

    /* -------- flow */
    begin() {
      storage('set', ACTIVE_KEY, JSON.stringify({workout_id: this.workoutId, session_id: this.plan.source.session_id}));
      this.state.paused = false;
      this.startWork(0, 0);
      this.startTimer();
      this.saveNow();
    }

    startWork(index, set, {announce = true} = {}) {
      const item = this.items[index];
      this.state.index = index;
      this.state.set = set;
      this.state.phase = 'work';
      this.state.count = 0;
      this.state.spoken = [];
      this.state.rest_kind = null;
      this.state.remaining_ms = item.mode === 'time' ? setTarget(item) * 1000 : 0;
      this.repElapsed = 0;
      // Announce the exercise name once, only when a genuinely new exercise begins.
      if (announce && set === 0 && !this.state.announced.includes(item.uid)) {
        this.state.announced.push(item.uid);
        Voice.speak(item.name);
      }
      this.renderAll();
      this.playVideo();
    }

    startRest(kind, seconds) {
      Voice.cancel();
      this.state.phase = 'rest';
      this.state.rest_kind = kind;
      this.state.remaining_ms = seconds * 1000;
      this.state.rest_total_ms = seconds * 1000;
      this.state.spoken = [];
      this.pauseVideo();
      this.renderAll();
    }

    afterSet() {
      const item = this.item;
      if (this.state.set < item.sets - 1) {
        if (item.rest_between_sets_s > 0) return this.startRest('set', item.rest_between_sets_s);
        return this.startWork(this.state.index, this.state.set + 1);
      }
      this.afterExercise();
    }

    afterExercise({skipRest = false} = {}) {
      const item = this.item;
      if (this.state.index >= this.items.length - 1) return this.finish('completed');
      if (!skipRest && item.rest_after_s > 0) return this.startRest('exercise', item.rest_after_s);
      this.startWork(this.state.index + 1, 0);
    }

    endRest() {
      if (this.state.rest_kind === 'set') this.startWork(this.state.index, this.state.set + 1);
      else this.startWork(this.state.index + 1, 0);
      this.saveNow();
    }

    completeSet(status = 'completed') {
      const item = this.item;
      const target = setTarget(item);
      const rec = this.record(item.uid);
      const reached = item.mode === 'time' ? Math.round(target - this.state.remaining_ms / 1000) : this.state.count;
      rec.sets[this.state.set] = status === 'completed' ? {status: 'completed', count: target}
        : reached > 0 ? {status: 'partial', count: Math.min(target, Math.max(0, reached))} : {status: 'skipped', count: 0};
      Voice.cancel();
      this.afterSet();
      this.saveNow();
    }

    skipExercise() {
      const item = this.item;
      const rec = this.record(item.uid);
      if (this.state.phase === 'work') {
        const target = setTarget(item);
        const reached = item.mode === 'time' ? Math.round(target - this.state.remaining_ms / 1000) : this.state.count;
        rec.sets[this.state.set] = reached > 0 ? {status: 'partial', count: Math.min(target, reached)} : {status: 'skipped', count: 0};
      }
      rec.skipped = true;
      Voice.cancel();
      this.el.status.textContent = `${item.name} skipped.`;
      this.afterExercise({skipRest: true});
      this.saveNow();
    }

    finish(status) {
      this.stopTimer();
      Voice.cancel();
      this.pauseVideo();
      this.state.phase = 'done';
      this.state.paused = true;
      this.state.ending = status;
      this.finalStatus = status;
      // Persist "finished, waiting for feedback" so a reload shows the feedback form, not a restart.
      this.saveNow({force: true});
      this.renderFeedback();
    }

    /* -------- clock */
    startTimer() {
      this.stopTimer();
      this.lastTick = performance.now();
      this.timer = setInterval(() => this.tick(), TICK_MS);
    }
    stopTimer() {
      if (this.timer) clearInterval(this.timer);
      this.timer = null;
    }
    tick() {
      if (this.state.paused || this.state.phase === 'done') { this.lastTick = performance.now(); return; }
      const now = performance.now();
      const dt = Math.min(1000, now - this.lastTick);   // cap: a sleeping tab must not skip a whole set
      this.lastTick = now;
      this.state.elapsed_ms += dt;
      const item = this.item;
      if (this.state.phase === 'rest') {
        this.state.remaining_ms = Math.max(0, this.state.remaining_ms - dt);
        if (this.state.remaining_ms <= 0) return this.endRest();
      } else if (this.state.phase === 'work') {
        const total = setTarget(item);
        const spokenN = spokenCount(total);
        if (item.mode === 'time') {
          this.state.remaining_ms = Math.max(0, this.state.remaining_ms - dt);
          const left = Math.ceil(this.state.remaining_ms / 1000);
          if (left > 0 && left <= spokenN && !this.state.spoken.includes(left)) {
            this.state.spoken.push(left);
            Voice.speak(String(left));
          }
          if (this.state.remaining_ms <= 0) return this.completeSet('completed');
        } else {
          this.repElapsed += dt;
          const repMs = item.cadence_s * 1000;
          while (this.repElapsed >= repMs && this.state.count < total) {
            this.repElapsed -= repMs;
            this.state.count += 1;
            const left = total - this.state.count;
            if (left > 0 && left <= spokenN && !this.state.spoken.includes(left)) {
              this.state.spoken.push(left);
              Voice.speak(String(left));
            }
          }
          if (this.state.count >= total) return this.completeSet('completed');
        }
      }
      this.renderTick();
      if (now - this.lastSave > SAVE_EVERY_MS) this.saveNow();
    }

    /* -------- controls */
    pause(reason) {
      if (this.state.paused || this.state.phase === 'done') return;
      this.state.paused = true;
      Voice.cancel();
      this.pauseVideo();
      this.el.status.textContent = reason === 'left the page' ? 'Paused because you left the workout page.' : 'Paused.';
      this.renderControls();
      this.saveNow();
    }
    resume() {
      if (this.state.phase === 'done') return;
      if (!this.timer) this.startTimer();
      this.state.paused = false;
      this.lastTick = performance.now();
      if (this.state.phase === 'work') this.playVideo();
      this.el.status.textContent = 'Resumed.';
      this.renderAll();
    }
    addRest(seconds) {
      if (this.state.phase !== 'rest') return;
      this.state.remaining_ms += seconds * 1000;
      this.state.rest_total_ms += seconds * 1000;
      this.progress.rest_added_s += seconds;
      this.renderTick();
      this.saveNow();
    }
    skipRest() {
      if (this.state.phase !== 'rest') return;
      this.progress.rest_skipped += 1;
      this.endRest();
    }
    toggleVoice() {
      this.state.voice = !this.state.voice;
      Voice.enabled = this.state.voice;
      if (!this.state.voice) Voice.cancel();
      this.renderVoice();
      this.saveNow();
    }
    async endWorkout() {
      const wasPaused = this.state.paused;
      this.pause();
      const ok = typeof window.confirmDialog === 'function'
        ? await window.confirmDialog({title: 'End the workout now?', description: 'Work you have not done will be recorded as skipped or not reached, not as completed.', confirmLabel: 'End workout'})
        : true;
      if (!ok) { if (!wasPaused) this.resume(); return; }
      if (this.state.phase === 'work') {
        const item = this.item;
        const target = setTarget(item);
        const reached = item.mode === 'time' ? Math.round(target - this.state.remaining_ms / 1000) : this.state.count;
        if (reached > 0) this.record(item.uid).sets[this.state.set] = {status: 'partial', count: Math.min(target, reached)};
      }
      this.finish('ended_early');
    }
    replayDemo() {
      if (!this.video || !this.video.src) return;
      try { this.video.currentTime = 0; } catch { /* ignore */ }
      this.video.play().catch(() => {});
    }
    toggleSlow(button) {
      if (!this.video) return;
      const slow = this.video.playbackRate !== 1;
      this.video.playbackRate = slow ? 1 : 0.5;
      button.setAttribute('aria-pressed', String(!slow));
      button.textContent = slow ? 'Slow motion' : 'Normal speed';
    }

    /* -------- video */
    playVideo() {
      const item = this.item;
      if (!item) return;
      if (!item.video || !item.media_url) { this.showGuideOnly(item); return; }
      if (this.videoFor !== item.uid) {
        this.videoFor = item.uid;
        this.video.src = item.media_url;
        this.video.playbackRate = 1;
        this.el.media.replaceChildren(this.video, this.mediaTools());
      } else if (!this.el.media.contains(this.video)) {
        this.el.media.replaceChildren(this.video, this.mediaTools());
      }
      this.video.classList.remove('is-resting');
      if (!this.state.paused) this.video.play().catch(() => {});
    }
    pauseVideo() {
      if (this.video) {
        this.video.pause();
        this.video.classList.add('is-resting');
      }
    }
    mediaTools() {
      const slow = h('button', {type: 'button', class: 'btn btn-quiet btn-small', 'aria-pressed': 'false'}, 'Slow motion');
      slow.addEventListener('click', () => this.toggleSlow(slow));
      return h('div', {class: 'wk-media-tools'},
        h('button', {type: 'button', class: 'btn btn-quiet btn-small', onclick: () => this.replayDemo()}, 'Replay demo'), slow,
        h('span', {class: 'wk-loop-badge'}, 'Demo loops · muted'));
    }
    showGuideOnly(item, message) {
      this.videoFor = null;
      if (this.video) { this.video.pause(); this.video.removeAttribute('src'); this.video.load(); }
      this.el.media.replaceChildren(h('div', {class: 'wk-noguide'},
        h('strong', {text: message || (item.video_missing ? 'The demonstration file is missing from the workout folder.' : 'No demonstration video for this exercise.')}),
        h('span', {text: 'Follow the written steps below.'}),
        h('ol', {}, item.instructions.map(s => h('li', {text: s})))));
    }
    videoFailed() {
      const item = this.item;
      if (item && item.video) this.showGuideOnly(item, 'This demonstration video could not be played in this browser.');
    }

    /* -------- rendering */
    remainingSeconds() {
      const s = this.state;
      if (s.phase === 'done') return 0;
      const item = this.item;
      let total = 0;
      const repWork = it => it.work_s;
      if (s.phase === 'work') {
        total += item.mode === 'time' ? s.remaining_ms / 1000 : Math.max(0, (setTarget(item) - s.count) * item.cadence_s - this.repElapsed / 1000);
        const setsLeft = item.sets - s.set - 1;
        total += setsLeft * (repWork(item) + item.rest_between_sets_s);
        if (s.index < this.items.length - 1) total += item.rest_after_s;
      } else if (s.phase === 'rest') {
        total += s.remaining_ms / 1000;
        if (s.rest_kind === 'set') {
          const setsLeft = item.sets - s.set - 1;
          total += setsLeft * repWork(item) + Math.max(0, setsLeft - 1) * item.rest_between_sets_s + item.rest_after_s;
        }
      } else {
        total += item.planned_s;
      }
      for (let i = s.index + 1; i < this.items.length; i += 1) total += this.items[i].planned_s;
      return Math.max(0, total);
    }

    renderAll() {
      const s = this.state;
      const item = this.item;
      if (!item) return;
      this.el.phase.textContent = s.phase === 'rest' ? 'Rest' : `${PHASE_LABEL[item.phase]}`;
      this.el.phase.dataset.phase = s.phase === 'rest' ? 'rest' : item.phase;
      this.el.position.textContent = `Step ${s.index + 1} of ${this.items.length}`;
      this.el.stage.classList.toggle('is-rest', s.phase === 'rest');
      if (s.phase === 'rest') {
        const next = s.rest_kind === 'set' ? item : this.items[s.index + 1];
        this.el.name.textContent = 'Rest';
        this.el.muscles.textContent = s.rest_kind === 'set' ? `Next: ${item.name}, set ${s.set + 2} of ${item.sets}` : `Next: ${next ? next.name : 'finish'}`;
        this.el.setInfo.textContent = s.rest_kind === 'set' ? 'Rest between sets (silent)' : 'Rest before the next exercise (silent)';
        this.el.sideNote.textContent = '';
      } else {
        this.el.name.textContent = item.name;
        this.el.muscles.textContent = item.muscles.join(' · ');
        this.el.setInfo.textContent = `Set ${s.set + 1} of ${item.sets} · ${itemDose(item)}`;
        if (s.phase === 'ready') this.el.setInfo.textContent += ' · ready';
      }
      this.el.restAfter.textContent = s.phase === 'rest' ? '' : (s.set < item.sets - 1 ? `Then ${item.rest_between_sets_s} s rest.`
        : item.rest_after_s ? `Then ${item.rest_after_s} s rest before the next exercise.` : (s.index < this.items.length - 1 ? 'Then straight into the next block.' : 'Last exercise.'));
      const upcoming = this.items[s.index + 1];
      this.el.next.replaceChildren(h('span', {class: 'muted'}, 'Next exercise: '), h('strong', {text: upcoming ? upcoming.name : 'Finish and summary'}));
      this.renderGuide(item);
      this.renderControls();
      this.renderVoice();
      this.renderTimeline();
      this.renderTick();
      if (s.phase === 'work' || s.phase === 'ready') {
        if (item.video && item.media_url) {
          if (this.videoFor !== item.uid || !this.el.media.contains(this.video)) {
            this.videoFor = null;
            this.playVideo();
            if (s.paused) this.pauseVideo();
          }
        } else this.showGuideOnly(item);
      }
    }

    renderTick() {
      const s = this.state;
      const item = this.item;
      if (!item) return;
      const remaining = this.remainingSeconds();
      this.el.elapsed.textContent = fmtClock(s.elapsed_ms / 1000);
      this.el.remaining.textContent = fmtClock(remaining);
      const planned = this.plan.duration.total_s;
      const doneShare = Math.max(0, Math.min(1, 1 - remaining / planned));
      this.el.bar.style.width = `${(doneShare * 100).toFixed(1)}%`;
      this.el.bar.parentElement.setAttribute('aria-valuenow', String(Math.round(doneShare * 100)));
      if (s.phase === 'rest') {
        this.el.counter.textContent = fmtClock(s.remaining_ms / 1000);
        this.el.counterLabel.textContent = 'rest left';
      } else if (s.phase === 'work' || s.phase === 'ready') {
        const total = setTarget(item);
        if (item.mode === 'time') {
          this.el.counter.textContent = fmtClock(s.phase === 'ready' ? total : s.remaining_ms / 1000);
          this.el.counterLabel.textContent = 'time left';
          const half = total / 2;
          this.el.sideNote.textContent = item.per_side ? (s.remaining_ms / 1000 > half ? 'Side 1 — switch at halfway' : 'Side 2') : '';
        } else {
          const left = total - s.count;
          this.el.counter.textContent = String(left);
          this.el.counterLabel.textContent = `reps left · rep ${Math.min(total, s.count + 1)} of ${total} (guided pace)`;
          this.el.sideNote.textContent = item.per_side ? `${item.target} each side` : '';
        }
      }
    }

    renderControls() {
      const s = this.state;
      const c = this.el.controls;
      c.replaceChildren();
      if (s.phase === 'done') return;
      const pauseBtn = s.paused
        ? h('button', {type: 'button', class: 'btn btn-primary', id: 'wk-resume', onclick: () => (s.phase === 'ready' ? this.beginFromReady() : this.resume())}, s.phase === 'ready' ? 'Start' : 'Resume')
        : h('button', {type: 'button', class: 'btn btn-quiet', id: 'wk-pause', onclick: () => this.pause()}, 'Pause workout');
      if (s.phase === 'rest') {
        c.append(h('button', {type: 'button', class: 'btn btn-primary', id: 'wk-skip-rest', onclick: () => this.skipRest()}, 'Skip rest'),
          h('button', {type: 'button', class: 'btn btn-quiet', id: 'wk-add-rest', onclick: () => this.addRest(15)}, 'Add 15 seconds'),
          pauseBtn);
      } else {
        c.append(pauseBtn,
          h('button', {type: 'button', class: 'btn btn-quiet', id: 'wk-set-done', disabled: s.phase !== 'work', onclick: () => this.completeSet('completed')}, 'Set done'),
          h('button', {type: 'button', class: 'btn btn-quiet', id: 'wk-skip-set', disabled: s.phase !== 'work', onclick: () => this.completeSet('skipped')}, 'Skip set'),
          h('button', {type: 'button', class: 'btn btn-quiet', id: 'wk-skip-ex', disabled: s.phase !== 'work', onclick: () => this.skipExercise()}, 'Skip exercise'));
      }
      c.append(h('button', {type: 'button', class: 'btn btn-danger', id: 'wk-end', onclick: () => this.endWorkout()}, 'End workout'));
    }

    beginFromReady() {
      this.state.paused = false;
      this.startWork(this.state.index, this.state.set);
      this.startTimer();
    }

    renderVoice() {
      const b = this.el.voiceToggle;
      if (!Voice.supported) {
        b.disabled = true;
        b.textContent = 'Voice unavailable';
        return;
      }
      b.setAttribute('aria-pressed', String(this.state.voice));
      b.textContent = this.state.voice ? 'Voice on' : 'Voice muted';
      b.setAttribute('aria-label', this.state.voice ? 'Voice guidance on; press to mute' : 'Voice guidance muted; press to turn on');
    }

    renderGuide(item) {
      this.el.guide.replaceChildren(
        h('h3', {text: `How to do it: ${item.name}`}),
        h('p', {class: 'muted', text: item.description}),
        h('ol', {class: 'wk-steps'}, item.instructions.map(s => h('li', {text: s}))),
        h('div', {class: 'two-col'},
          h('div', {}, h('h4', {text: 'Form cues'}), h('ul', {class: 'wk-plain'}, item.cues.map(s => h('li', {text: s})))),
          h('div', {}, h('h4', {text: 'Common mistakes'}), h('ul', {class: 'wk-plain'}, item.mistakes.map(s => h('li', {text: s}))))),
        h('p', {class: 'wk-safety-line'}, h('b', {text: 'Safety: '}), item.safety, ' Stop if anything hurts.'),
        h('p', {class: 'muted'}, `Easier: ${item.regression} · Harder: ${item.progression}`),
        item.phase === 'main' ? h('p', {class: 'muted'}, h('b', {text: 'Why: '}), item.rationale.reason) : null);
    }

    renderTimeline() {
      const s = this.state;
      this.el.timeline.replaceChildren(...this.items.map((item, index) => {
        const rec = this.progress.items[item.uid] || {sets: []};
        const done = rec.sets.filter(x => x && x.status === 'completed').length;
        const partial = rec.sets.filter(x => x && x.status === 'partial').length;
        let status = index < s.index ? (done === item.sets ? 'done' : rec.skipped || (!done && !partial) ? 'skipped' : 'partial')
          : index === s.index && s.phase !== 'done' ? 'current' : 'upcoming';
        if (index === s.index && s.phase === 'done') status = done === item.sets ? 'done' : 'partial';
        const label = {done: 'completed', skipped: 'skipped', partial: 'partly done', current: 'current', upcoming: 'upcoming'}[status];
        const dots = h('span', {class: 'wk-dots', 'aria-hidden': 'true'},
          Array.from({length: item.sets}, (_, k) => h('i', {class: `wk-dot ${rec.sets[k] ? `is-${rec.sets[k].status}` : ''}`})));
        return h('li', {class: `wk-tl is-${status}`, 'aria-current': status === 'current' ? 'step' : null},
          h('span', {class: 'wk-tl-name'}, h('b', {text: item.name}), h('small', {text: `${PHASE_LABEL[item.phase]} · ${itemDose(item)}`})),
          dots, h('span', {class: 'sr-only', text: `, ${label}, ${done} of ${item.sets} sets completed`}));
      }));
    }

    /* -------- persistence */
    payload(status) {
      this.progress.active_s = Math.round(this.state.elapsed_ms / 1000);
      const state = {...this.state, remaining_ms: Math.round(this.state.remaining_ms), elapsed_ms: Math.round(this.state.elapsed_ms),
        rest_total_ms: Math.round(this.state.rest_total_ms)};
      return {status, state, progress: this.progress};
    }
    saveNow({keepalive = false, force = false} = {}) {
      if ((this.state.phase === 'done' && !force) || !this.workoutId) return this.saving;
      this.lastSave = performance.now();
      const body = JSON.stringify(this.payload('active'));
      const send = () => fetch(`/api/workouts/${this.workoutId}/progress`, {method: 'PUT', keepalive,
        headers: {'Content-Type': 'application/json', 'X-Shotlab': '1'}, body})
        .then(r => { if (!r.ok && r.status !== 409) this.el.status.textContent = 'Progress could not be saved; keep this page open.'; })
        .catch(() => { this.el.status.textContent = 'Progress could not be saved (connection lost).'; });
      this.saving = this.saving.then(send, send);
      return this.saving;
    }

    /* -------- end of workout */
    renderFeedback() {
      const status = this.finalStatus;
      const difficulty = h('div', {class: 'choice-row'});
      for (const [value, label] of [['too_easy', 'Too easy'], ['about_right', 'About right'], ['too_hard', 'Too hard']]) {
        difficulty.append(h('label', {}, h('input', {type: 'radio', name: 'wk-difficulty', value}), h('span', {text: label})));
      }
      const pain = h('input', {type: 'checkbox', name: 'wk-felt-pain'});
      const note = h('textarea', {rows: '2', maxlength: '500', placeholder: 'Optional notes for next time'});
      const error = h('p', {class: 'form-error hidden', role: 'alert'});
      const save = h('button', {type: 'submit', class: 'btn btn-primary btn-block', id: 'wk-save-summary'}, 'Save and see my summary');
      const form = h('form', {class: 'card form-step wk-feedback', novalidate: true},
        h('h2', {text: status === 'completed' ? 'Workout complete' : 'Workout ended early'}),
        h('p', {class: 'muted', text: 'A quick check-in makes the next recommendation more useful. Nothing here is required.'}),
        h('fieldset', {class: 'choice-group'}, h('legend', {text: 'How did it feel?'}), difficulty),
        h('label', {class: 'check-field'}, pain, h('span', {}, 'I felt pain during this workout',
          h('small', {text: 'If so, stop these exercises and get it assessed before repeating them.'}))),
        h('label', {class: 'field'}, 'Notes', note), error, save);
      form.addEventListener('submit', async event => {
        event.preventDefault();
        save.disabled = true;
        const feedback = {difficulty: form.querySelector('input[name="wk-difficulty"]:checked')?.value || null,
          felt_pain: pain.checked, note: note.value.trim()};
        await this.saving;
        try {
          const body = {...this.payload(status), feedback};
          body.state.phase = 'done';
          workout = await api(`/api/workouts/${this.workoutId}/progress`, jsonBody('PUT', body));
          storage('remove', ACTIVE_KEY);
          this.destroy();
          player = null;
          renderSummary();
        } catch (error_) {
          error.textContent = error_.message;
          error.classList.remove('hidden');
          save.disabled = false;
        }
      });
      root.replaceChildren(pageHead('Recording what you actually did.'), form);
      enter([form]);
      form.querySelector('input')?.focus();
    }
  }

  /* ------------------------------------------------------------------ summary */
  function renderSummary() {
    const s = workout.summary;
    const plan = workout.plan;
    if (!s) { renderPlan(); return; }
    const statusLabel = {completed: 'Completed', partial: 'Partly done', skipped: 'Skipped', not_reached: 'Not reached'};
    const statusChip = {completed: 'chip-approved', partial: 'chip-measure', skipped: 'chip-quarantined', not_reached: 'chip-discarded'};
    const stats = h('dl', {class: 'wk-summary-stats'},
      [['Exercises completed', `${s.counts.completed} of ${s.exercises.length}`],
        ['Exercises skipped', String(s.counts.skipped)],
        ['Sets completed', `${s.sets.sets_completed} of ${s.sets.sets_planned}`],
        ['Guided reps recorded', String(s.guided_reps)],
        ['Timed work recorded', fmtClock(s.timed_work_s)],
        ['Active time', fmtClock(s.active_s)],
        ['Planned workout', fmtClock(s.planned_total_s)],
        ['Planned vs completed work', `${fmtClock(s.completed_work_s)} of ${fmtClock(s.planned_work_s)}`]]
        .map(([k, v]) => h('div', {}, h('dt', {text: k}), h('dd', {text: v}))));
    const table = h('div', {class: 'table-scroll'}, h('table', {class: 'report-table'},
      h('thead', {}, h('tr', {}, ['Exercise', 'Status', 'Sets', 'Recorded'].map(x => h('th', {scope: 'col', text: x})))),
      h('tbody', {}, s.exercises.map(e => h('tr', {},
        h('th', {scope: 'row', 'data-label': 'Exercise'}, e.name, h('small', {class: 'muted', text: ` (${PHASE_LABEL[e.phase]})`})),
        h('td', {'data-label': 'Status'}, h('span', {class: `chip ${statusChip[e.status]}`, text: statusLabel[e.status]})),
        h('td', {'data-label': 'Sets', text: `${e.sets_completed} done${e.sets_partial ? `, ${e.sets_partial} partial` : ''}${e.sets_skipped ? `, ${e.sets_skipped} skipped` : ''} / ${e.sets_planned}`}),
        h('td', {'data-label': 'Recorded', text: e.mode === 'reps' ? `${e.count_recorded} guided reps` : `${fmtClock(e.count_recorded)} timed`}))))));
    const fb = workout.feedback;
    root.replaceChildren(
      pageHead(`${plan.title} · ${workout.status === 'completed' ? 'completed' : 'ended early'} · ${fmtDate(workout.ended_at)}`),
      h('section', {class: 'card wk-summary-card'}, h('h2', {text: 'Workout summary'}), stats,
        h('p', {class: 'muted', text: s.counting_note}),
        s.elapsed_s != null ? h('p', {class: 'muted', text: `Wall-clock time from start to finish: ${fmtClock(s.elapsed_s)} (includes any pauses).`}) : null),
      h('section', {class: 'card'}, h('h2', {text: 'Exercise by exercise'}), table),
      h('section', {class: 'card wk-next-card'}, h('h2', {text: 'For your next session'}),
        h('ul', {class: 'wk-plain'}, s.next_session.map(t => h('li', {text: t}))),
        fb ? h('p', {class: 'muted'}, `Your feedback: ${fb.difficulty ? fb.difficulty.replace('_', ' ') : 'no rating'}${fb.felt_pain ? ', felt pain' : ''}${fb.note ? ` — “${fb.note}”` : ''}`) : null),
      h('div', {class: 'wk-plan-actions'},
        h('button', {type: 'button', class: 'btn btn-primary', onclick: () => { formState = workout.plan.preferences; loadContext(); }}, 'Plan another workout'),
        h('a', {class: 'btn btn-quiet', href: '#report'}, 'Back to the report')));
    enter(root.children, {stagger: 0.06});
  }

  window.ShotLabWorkout = {show, hide, spokenCount, _player: () => player};
})();
