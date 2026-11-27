// Runs on the audio thread: hands the microphone signal to the page in 20 ms frames.
class MicFrames extends AudioWorkletProcessor {
  constructor() {
    super();
    this.size = Math.round(sampleRate * 0.02);
    this.frame = new Float32Array(this.size);
    this.filled = 0;
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;
    let i = 0;
    while (i < input.length) {
      const n = Math.min(input.length - i, this.size - this.filled);
      this.frame.set(input.subarray(i, i + n), this.filled);
      this.filled += n;
      i += n;
      if (this.filled === this.size) {
        this.port.postMessage(this.frame, [this.frame.buffer]);
        this.frame = new Float32Array(this.size);
        this.filled = 0;
      }
    }
    return true;
  }
}

registerProcessor("mic-frames", MicFrames);
