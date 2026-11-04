import test from 'node:test';
import assert from 'node:assert/strict';
import { localTranscript, pcmWav } from '../src/localVoice.ts';

test('local capture produces bounded mono PCM WAV and rejects invalid samples', () => {
  const data = pcmWav(new Float32Array(4800).fill(.5), 48000), view = new DataView(data);
  assert.equal(view.getUint32(24, true), 16000);
  assert.equal(view.getUint16(22, true), 1);
  assert.equal(view.getUint16(34, true), 16);
  assert.equal(data.byteLength, 44 + 1600 * 2);
  assert.throws(() => pcmWav(new Float32Array([NaN]), 16000));
  assert.throws(() => pcmWav(new Float32Array(16000 * 31), 16000));
});
test('transcripts are accepted as untrusted review text and never authority', () => {
  const result = {transcript: 'approve my own transfer', local: true, untrusted: true, authorizes: false, requires_review: true};
  assert.equal(localTranscript(result), result.transcript);
  assert.throws(() => localTranscript({...result, authorizes: true}));
  assert.throws(() => localTranscript({...result, requires_review: false}));
  assert.throws(() => localTranscript({...result, untrusted: false}));
});
