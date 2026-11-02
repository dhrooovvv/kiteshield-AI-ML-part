import { api } from './api/client.ts';

export interface LocalVoiceHealth { enabled: boolean; available: boolean; max_seconds: number }
const base = (import.meta.env?.VITE_API_BASE_URL || '/api/v1') + '/voice';

export function pcmWav(samples: Float32Array, inputRate: number): ArrayBuffer {
  if (!Number.isFinite(inputRate) || inputRate < 8000 || inputRate > 192000 || samples.length / inputRate > 30) throw new Error('Recording limit exceeded.');
  const count = Math.floor(samples.length * 16000 / inputRate);
  const buffer = new ArrayBuffer(44 + count * 2), view = new DataView(buffer);
  const text = (offset: number, value: string) => [...value].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0)));
  text(0, 'RIFF'); view.setUint32(4, 36 + count * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, 16000, true); view.setUint32(28, 32000, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, 'data'); view.setUint32(40, count * 2, true);
  for (let i = 0; i < count; i++) {
    const position = i * inputRate / 16000, left = Math.floor(position), fraction = position - left;
    const value = samples[left] * (1 - fraction) + samples[Math.min(left + 1, samples.length - 1)] * fraction;
    if (!Number.isFinite(value)) throw new Error('Invalid microphone audio.');
    const bounded = Math.max(-1, Math.min(1, value));
    view.setInt16(44 + i * 2, Math.round(bounded * (bounded < 0 ? 32768 : 32767)), true);
  }
  return buffer;
}

export function localTranscript(result: unknown): string {
  const value = result as Record<string, unknown>;
  if (!value || value.local !== true || value.untrusted !== true || value.authorizes !== false
    || value.requires_review !== true || typeof value.transcript !== 'string'
    || !value.transcript.trim() || value.transcript.length > 2000) throw new Error('Transcript unavailable. Type your request instead.');
  return value.transcript;
}

export async function localVoiceHealth(): Promise<LocalVoiceHealth> {
  const response = await fetch(base + '/health', {signal: AbortSignal.timeout(5000), cache: 'no-store'});
  if (!response.ok) throw new Error('Local voice status unavailable.');
  return response.json();
}

export async function transcribeLocal(audio: ArrayBuffer, signal?: AbortSignal): Promise<string> {
  if (!api.getConnectedRoles().includes('proposer')) throw new Error('Connect the Proposer role to dictate a task.');
  const response = await fetch(base + '/transcribe', {method: 'POST', body: audio,
    headers: {'Content-Type': 'audio/wav', 'X-API-Key': api.getRoleKey('proposer')},
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(35000)]) : AbortSignal.timeout(35000)});
  if (!response.ok) throw new Error(response.status === 429 ? 'Local voice is busy. Try again shortly.' : 'Local transcription failed. Type your request instead.');
  return localTranscript(await response.json());
}

export function localCapture(maxSeconds: number, events: {
  listening(value: boolean): void; busy(value: boolean): void; text(value: string): void; error(value: string): void;
}) {
  let wanted = false, starting = false, generation = 0, stream: MediaStream | null = null, context: AudioContext | null = null;
  let source: MediaStreamAudioSourceNode | null = null, processor: ScriptProcessorNode | null = null;
  let chunks: Float32Array[] = [], count = 0, timer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | null = null;
  function release() {
    clearTimeout(timer); processor?.disconnect(); source?.disconnect(); stream?.getTracks().forEach(track => track.stop());
    if (context) void context.close(); processor = null; source = null; stream = null; context = null;
    events.listening(false);
  }
  const capture = {
    async start() {
      if (wanted || starting || controller) return;
      wanted = true; starting = true; const token = ++generation;
      try {
        const microphone = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1}, video: false});
        if (!wanted || generation !== token) { microphone.getTracks().forEach(track => track.stop()); return; }
        stream = microphone; context = new AudioContext(); await context.resume();
        if (!wanted || generation !== token || !context) { release(); return; }
        chunks = []; count = 0; source = context.createMediaStreamSource(stream);
        processor = context.createScriptProcessor(4096, 1, 1);
        processor.onaudioprocess = event => {
          if (!wanted || !context) return;
          const channel = new Float32Array(event.inputBuffer.getChannelData(0));
          if (count + channel.length > context.sampleRate * maxSeconds) { void capture.stop(); return; }
          chunks.push(channel); count += channel.length;
          event.outputBuffer.getChannelData(0).fill(0);
        };
        source.connect(processor); processor.connect(context.destination);
        events.listening(true); timer = setTimeout(() => void capture.stop(), maxSeconds * 1000);
      } catch { wanted = false; release(); events.error('Microphone unavailable or permission denied. You can type instead.'); }
      finally { starting = false; }
    },
    async stop() {
      wanted = false;
      if (!context) return;
      const rate = context.sampleRate, samples = new Float32Array(count);
      let offset = 0; for (const part of chunks) { samples.set(part, offset); offset += part.length; }
      release(); chunks = []; count = 0;
      if (samples.length < rate * .1) { events.error('No speech recorded. Hold the microphone while speaking.'); return; }
      controller = new AbortController(); const current = controller;
      events.busy(true);
      try {
        const text = await transcribeLocal(pcmWav(samples, rate), current.signal);
        if (!current.signal.aborted) { events.text(text); events.error('Review the transcript, then press Ask. Speech does not approve payments.'); }
      } catch (error) { if (!current.signal.aborted) events.error(error instanceof Error ? error.message : 'Local voice unavailable.'); }
      finally { if (controller === current) controller = null; events.busy(false); }
    },
    cancel() { wanted = false; generation++; controller?.abort(); controller = null; release(); chunks = []; count = 0; events.busy(false); },
  };
  return capture;
}
