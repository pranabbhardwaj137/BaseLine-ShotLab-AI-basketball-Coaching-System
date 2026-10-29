/* Test double for navigator.mediaDevices (camera switching tests). Real MediaStreams come from a
   canvas, so preview and MediaRecorder still work. Configure with window.__fakeCamConfig before load:
     devices:     [{deviceId, label, facing}]  in the order the browser would list them
     exclusive:   true  -> opening a camera while another is open throws NotReadableError (many Android phones)
     exactFacing: false -> {facingMode: {exact: …}} throws OverconstrainedError (some browsers)
     steal:       true  -> opening a camera ends the previous one, like iOS Safari
   window.__cam exposes calls, live tracks, and `deny` to simulate a permission refusal. */
(() => {
  const cfg = Object.assign({
    devices: [
      {deviceId: 'front-1', label: 'Front Camera', facing: 'user'},
      {deviceId: 'back-1', label: 'Back Camera', facing: 'environment'},
      {deviceId: 'back-2', label: 'Back Ultra Wide Camera', facing: 'environment'},
      {deviceId: 'back-3', label: 'Back Telephoto Camera', facing: 'environment'},
    ],
    exclusive: true, exactFacing: true, steal: false,
  }, window.__fakeCamConfig || {});
  const state = {granted: false, live: [], calls: [], opened: [], deny: false, cfg};
  window.__cam = state;
  const fail = (name, message, constraint) => Object.assign(new Error(message), {name, constraint});

  function makeStream(dev) {
    const canvas = document.createElement('canvas');
    canvas.width = 640; canvas.height = 360;
    const ctx = canvas.getContext('2d');
    let frame = 0;
    const paint = () => {
      ctx.fillStyle = dev.facing === 'user' ? '#1e7a4c' : '#7a1e4c';
      ctx.fillRect(0, 0, 640, 360);
      ctx.fillStyle = '#fff'; ctx.font = '36px sans-serif';
      ctx.fillText(`${dev.label} ${frame++}`, 20, 70);
    };
    paint();
    const timer = setInterval(paint, 66);
    const stream = canvas.captureStream(15);
    const track = stream.getVideoTracks()[0];
    const nativeStop = track.stop.bind(track);
    track.stop = () => {
      clearInterval(timer);
      state.live = state.live.filter(t => t !== track);
      nativeStop();
    };
    track.getSettings = () => ({deviceId: dev.deviceId, facingMode: dev.facing, width: 640, height: 360, frameRate: 15});
    track.__dev = dev;
    return {stream, track};
  }

  navigator.mediaDevices.enumerateDevices = async () => cfg.devices.map(d => ({
    kind: 'videoinput', groupId: '', deviceId: state.granted ? d.deviceId : '', label: state.granted ? d.label : '',
  }));
  navigator.mediaDevices.getUserMedia = async constraints => {
    state.calls.push(JSON.parse(JSON.stringify(constraints)));
    if (state.deny) throw fail('NotAllowedError', 'Permission denied');
    const v = constraints && constraints.video;
    let candidates = cfg.devices.slice();
    if (v && typeof v === 'object') {
      if (v.deviceId) {
        const id = v.deviceId.exact || v.deviceId.ideal || v.deviceId;
        const match = cfg.devices.filter(d => d.deviceId === id);
        if (match.length) candidates = match;
        else if (v.deviceId.exact) throw fail('OverconstrainedError', 'No such device', 'deviceId');
      }
      if (v.facingMode) {
        const want = v.facingMode.exact || v.facingMode.ideal || v.facingMode;
        if (v.facingMode.exact && !cfg.exactFacing) throw fail('OverconstrainedError', 'exact facingMode not supported', 'facingMode');
        const match = candidates.filter(d => d.facing === want);
        if (match.length) candidates = match;
        else if (v.facingMode.exact) throw fail('OverconstrainedError', `No ${want} camera`, 'facingMode');
      }
    }
    if (cfg.steal) {
      for (const old of state.live.slice()) { old.stop(); old.dispatchEvent(new Event('ended')); }
    } else if (cfg.exclusive && state.live.length) {
      throw fail('NotReadableError', 'Could not start video source');
    }
    state.granted = true;
    const {stream, track} = makeStream(candidates[0]);
    state.live.push(track);
    state.opened.push(candidates[0].deviceId);
    return stream;
  };
})();
