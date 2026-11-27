// Hands-free voice mode: turn-based speech-to-text / text-to-speech, no push-to-talk.
//
// The microphone stays open while voice mode is on. A small voice-activity detector (signal level
// against an adaptive noise floor) decides when the customer starts and stops talking; each finished
// utterance is sent for transcription and then answered like typed text. Replies are read out
// sentence by sentence, so playback starts after the first sentence is ready. If the customer starts
// talking while a reply is playing, playback stops at once and the new utterance is recorded
// (barge-in). Echo cancellation in the browser keeps the assistant's own voice out of the mic.

const PREROLL_MS = 400;        // audio kept from before speech was detected, so first syllables aren't cut
const END_SILENCE_MS = 900;    // this much quiet ends an utterance
const MAX_UTTERANCE_MS = 30000;
const MIN_SPEECH_MS = 250;     // shorter bursts (a cough, a door) are ignored
const START_MS = 160;          // sustained speech needed to start listening...
const BARGE_IN_MS = 300;       // ...and a bit more to interrupt a reply (guards against echo leaking through)
const START_DB = 14;           // dB above the noise floor that counts as speech
const BARGE_IN_DB = 20;        // stricter while the assistant is talking
const END_DB = 8;              // dB above the noise floor that still counts as talking (trailing words)
const MIN_SPEECH_LEVEL = -55;  // dBFS; very quiet rooms otherwise trigger on breathing
const TARGET_RATE = 16000;

// False when the browser lacks the APIs, or when a page embedding the app doesn't allow the microphone
// (an <iframe> needs allow="microphone"); then the mic button is hidden instead of failing on click.
export const voiceSupported = () => {
  const policy = document.permissionsPolicy || document.featurePolicy;  // Chromium only
  if (policy && !policy.allowsFeature("microphone")) return false;
  return Boolean(navigator.mediaDevices?.getUserMedia && window.AudioContext && window.AudioWorkletNode);
};

export class VoiceMode {
  // transcribe(Blob) -> text; synthesize(text, AbortSignal) -> ArrayBuffer (mp3)
  // onUtterance(text) -> Promise that resolves once the reply has been handed to speak()
  // onState(state, detail), onLevel(0..1), onError(messageKey, detail?)
  constructor({ transcribe, synthesize, onUtterance, onState = () => {}, onLevel = () => {}, onError = () => {} }) {
    Object.assign(this, { transcribe, synthesize, onUtterance, onState, onLevel, onError });
    this.state = "off";
  }

  get active() { return this.state !== "off"; }

  async start() {
    if (this.active) return;
    this.setState("starting");
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
      this.ctx = new AudioContext();
      await this.ctx.audioWorklet.addModule("voice-worklet.js");
      await this.ctx.resume();
    } catch (err) {
      this.stop();
      const denied = err?.name === "NotAllowedError" || err?.name === "SecurityError";
      this.onError(denied ? "mic_blocked" : "mic_failed");
      return;
    }
    const source = this.ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.ctx, "mic-frames");
    const mute = this.ctx.createGain();
    mute.gain.value = 0;  // the worklet must be connected to run everywhere; nothing is played back
    source.connect(this.node).connect(mute).connect(this.ctx.destination);
    this.rate = this.ctx.sampleRate;
    this.frameMs = 1000 * (Math.round(this.rate * 0.02) / this.rate);
    this.floor = -60;
    this.calibration = [];
    this.calibrationFrames = Math.round(300 / this.frameMs);
    this.preroll = [];
    this.resetDetector();
    this.node.port.onmessage = (e) => this.onFrame(e.data);
    this.setState("listening");
  }

  stop() {
    this.interrupt();
    this.node?.port && (this.node.port.onmessage = null);
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close().catch(() => {});
    this.stream = this.ctx = this.node = null;
    this.onLevel(0);
    this.setState("off");
  }

  setState(state, detail) {
    this.state = state;
    this.onState(state, detail);
  }

  resetDetector() {
    this.above = 0;            // ms of speech-level signal while waiting for an utterance
    this.captured = [];
    this.heardMs = 0;
    this.quietMs = 0;
    this.lengthMs = 0;
  }

  // ---------------------------------------------------------------- detection

  onFrame(frame) {
    if (!this.active || this.state === "starting") return;
    let sum = 0;
    for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
    const db = 10 * Math.log10(sum / frame.length + 1e-12);
    this.trackFloor(db);
    this.onLevel(Math.max(0, Math.min(1, (db - this.floor) / 30)));

    if (this.state === "hearing") return this.continueUtterance(frame, db);
    this.preroll.push(frame);
    while (this.preroll.length * this.frameMs > PREROLL_MS) this.preroll.shift();
    if (this.calibration.length < this.calibrationFrames) return;
    if (this.state !== "listening" && this.state !== "speaking") return;  // thinking: wait for the reply

    const speaking = this.state === "speaking";
    const threshold = Math.max(this.floor + (speaking ? BARGE_IN_DB : START_DB), MIN_SPEECH_LEVEL);
    // Leaky counter: brief dips between syllables don't reset it.
    this.above = db > threshold ? this.above + this.frameMs : Math.max(0, this.above - this.frameMs / 2);
    if (this.above >= (speaking ? BARGE_IN_MS : START_MS)) {
      if (speaking) this.interrupt();  // barge-in: the customer talks over the reply
      this.captured = this.preroll.splice(0);
      this.heardMs = this.above;
      this.lengthMs = this.captured.length * this.frameMs;
      this.quietMs = 0;
      this.setState("hearing", { bargeIn: speaking });
    }
  }

  trackFloor(db) {
    if (this.calibration.length < this.calibrationFrames) {
      // The first moments set the room's noise level (median, so a click doesn't skew it).
      this.calibration.push(db);
      const sorted = [...this.calibration].sort((a, b) => a - b);
      this.floor = sorted[Math.floor(sorted.length / 2)];
    } else if (db < this.floor) {
      this.floor = this.floor * 0.8 + db * 0.2;  // a quieter room is picked up quickly
    } else if (this.state !== "hearing") {
      this.floor += this.frameMs / 1000;         // louder background only slowly (~1 dB/s), never from speech
    }
    this.floor = Math.max(-90, Math.min(-30, this.floor));
  }

  continueUtterance(frame, db) {
    this.captured.push(frame);
    this.lengthMs += this.frameMs;
    if (db > Math.max(this.floor + END_DB, MIN_SPEECH_LEVEL - 6)) {
      this.quietMs = 0;
      if (db > this.floor + START_DB) this.heardMs += this.frameMs;
    } else {
      this.quietMs += this.frameMs;
    }
    if (this.quietMs >= END_SILENCE_MS || this.lengthMs >= MAX_UTTERANCE_MS) this.finishUtterance();
  }

  async finishUtterance() {
    const frames = this.captured;
    const heard = this.heardMs;
    this.resetDetector();
    if (heard < MIN_SPEECH_MS) { this.setState("listening"); return; }
    this.setState("thinking");
    try {
      const text = (await this.transcribe(encodeWav(frames, this.rate))).trim();
      if (!this.active) return;
      if (text.replace(/[\s.,!?…-]/g, "").length < 2) { this.setState("listening"); return; }
      await this.onUtterance(text);
    } catch (err) {
      if (this.active) this.onError("not_understood", err.message);
    }
    if (this.state === "thinking") this.setState("listening");
  }

  // ---------------------------------------------------------------- playback

  // Reads a reply aloud. Sentences are synthesised in parallel and played in order.
  speak(text) {
    // Never talk over the customer (e.g. a reply to a click arriving while they speak).
    if (!this.active || !text || this.state === "hearing" || this.state === "starting") return;
    this.interrupt();
    const chunks = splitForSpeech(text);
    if (!chunks.length) return;
    const abort = new AbortController();
    this.playback = { abort, sources: new Set() };
    const audio = chunks.map((chunk) => this.synthesize(chunk, abort.signal)
      .then((buf) => this.ctx.decodeAudioData(buf)));
    audio.forEach((p) => p.catch(() => {}));  // errors are handled when that chunk's turn comes
    this.setState("speaking");
    this.playChunks(audio, this.playback);
  }

  async playChunks(audio, playback) {
    for (const pending of audio) {
      let buffer;
      try {
        buffer = await pending;
      } catch (err) {
        if (playback !== this.playback) return;
        if (err?.name !== "AbortError") this.onError("play_failed");
        break;
      }
      if (playback !== this.playback) return;
      await new Promise((resolve) => {
        const src = this.ctx.createBufferSource();
        src.buffer = buffer;
        src.connect(this.ctx.destination);
        src.onended = () => { playback.sources.delete(src); resolve(); };
        playback.sources.add(src);
        src.start();
      });
      if (playback !== this.playback) return;
    }
    this.playback = null;
    if (this.state === "speaking") this.setState("listening");
  }

  // Stops the reply immediately (barge-in, a new reply, or voice mode off).
  interrupt() {
    const playback = this.playback;
    if (!playback) return;
    this.playback = null;
    playback.abort.abort();
    playback.sources.forEach((src) => { src.onended = null; try { src.stop(); } catch { /* not started */ } });
  }
}

// Short first chunk so speech starts quickly; later sentences are grouped to sound natural.
export function splitForSpeech(text) {
  const plain = text.replace(/\*\*(.+?)\*\*/g, "$1").replace(/^\s*[-*]\s+/gm, "").replace(/\s+/g, " ").trim();
  const sentences = plain.match(/[^.!?]+(?:[.!?]+["')\]]*|$)\s*/g) || [];
  const chunks = [];
  for (const s of sentences.map((x) => x.trim()).filter(Boolean)) {
    const last = chunks.length > 1 ? chunks.length - 1 : -1;  // never merge into the first chunk
    if (last > 0 && chunks[last].length + s.length < 220) chunks[last] += " " + s;
    else chunks.push(s);
  }
  return chunks;
}

// 16 kHz mono 16-bit WAV: small, and accepted everywhere (MediaRecorder formats differ per browser).
export function encodeWav(frames, rate) {
  const total = frames.reduce((n, f) => n + f.length, 0);
  const input = new Float32Array(total);
  let offset = 0;
  for (const f of frames) { input.set(f, offset); offset += f.length; }
  const ratio = rate / TARGET_RATE;
  const length = Math.floor(total / ratio);
  const view = new DataView(new ArrayBuffer(44 + length * 2));
  const ascii = (at, s) => [...s].forEach((c, i) => view.setUint8(at + i, c.charCodeAt(0)));
  ascii(0, "RIFF"); view.setUint32(4, 36 + length * 2, true); ascii(8, "WAVE");
  ascii(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, TARGET_RATE, true); view.setUint32(28, TARGET_RATE * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  ascii(36, "data"); view.setUint32(40, length * 2, true);
  for (let i = 0; i < length; i++) {
    // Average the input samples that fall into this output sample (simple low-pass + resample).
    const start = Math.floor(i * ratio), end = Math.min(total, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j];
    const v = Math.max(-1, Math.min(1, sum / Math.max(1, end - start)));
    view.setInt16(44 + i * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true);
  }
  return new Blob([view], { type: "audio/wav" });
}
