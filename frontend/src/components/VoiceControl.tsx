import { useEffect, useRef, useState } from 'react';
import { Mic, Square, Volume2 } from 'lucide-react';
import { browserRecognition, voiceSession, speakLocally } from '../voice.ts';
import type { AssistantAnswer } from '../assistant.ts';
import { localCapture, localVoiceHealth, type LocalVoiceHealth } from '../localVoice.ts';

export function VoiceControl({ disabled, onText, onCommand, reply }: {
  disabled: boolean; onText: (text: string) => void; onCommand: (text: string) => void; reply: AssistantAnswer | null;
}) {
  const [listening, setListening] = useState(false);
  const [error, setError] = useState('');
  const [spoken, setSpoken] = useState(false);
  const [browserAvailable] = useState(() => !!browserRecognition());
  const [local, setLocal] = useState<LocalVoiceHealth | null>(null);
  const [transcribing, setTranscribing] = useState(false);
  const available = !!local && (local.enabled ? local.available && !!navigator.mediaDevices?.getUserMedia : browserAvailable);
  const [localVoices, setLocalVoices] = useState(() => typeof window !== 'undefined' && !!window.speechSynthesis?.getVoices().some(voice => voice.localService && voice.lang.startsWith('en')));
  const events = useRef({ onText, onCommand });
  useEffect(() => { events.current = { onText, onCommand }; }, [onText, onCommand]);
  const session = useRef<ReturnType<typeof voiceSession> | null>(null);
  const capture = useRef<ReturnType<typeof localCapture> | null>(null);
  useEffect(() => {
    let active = true;
    void localVoiceHealth().then(value => { if (active) setLocal(value); }).catch(() => { /* No remote fallback when local status is unknown. */ });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!local?.enabled) return;
    capture.current = localCapture(local.max_seconds, {text: text => events.current.onText(text),
      listening: setListening, busy: setTranscribing, error: setError});
    return () => capture.current?.cancel();
  }, [local]);
  useEffect(() => {
    const Constructor = browserRecognition();
    if (!Constructor) return;
    session.current = voiceSession(Constructor, { text: text => events.current.onText(text),
      final: text => events.current.onCommand(text), listening: setListening, error: setError });
    return () => { session.current?.cancel(); window.speechSynthesis?.cancel(); };
  }, []);
  useEffect(() => {
    const refresh = () => setLocalVoices(!!window.speechSynthesis?.getVoices().some(voice => voice.localService && voice.lang.startsWith('en')));
    window.speechSynthesis?.addEventListener('voiceschanged', refresh);
    return () => window.speechSynthesis?.removeEventListener('voiceschanged', refresh);
  }, []);
  useEffect(() => {
    if (!spoken || !reply || !localVoices) return;
    const amount = reply.data?.total_eth;
    const message = reply.kind === 'invoice_task' ? 'Invoice task started. I will process it within the enabled permissions.'
      : reply.kind === 'payment' ? reply.data?.submitted_proposal
        ? `Payment request processed. Status: ${reply.data.submitted_proposal.transaction?.execution_outcome ?? reply.data.submitted_proposal.status}.`
        : 'Review the exact amount and recipient before submitting.'
      : `${reply.title}. ${amount ? `Total ${amount} ETH.` : reply.message ?? ''}`;
    speakLocally(message);
  }, [reply, spoken, localVoices]);
  const activeSession = () => local?.enabled ? capture.current : session.current;
  function start() { if (!disabled && !transcribing) { setError(''); window.speechSynthesis?.cancel(); void activeSession()?.start(); } }
  return <div className="assistant-voice">
    <div className="assistant-voice-controls"><button type="button" className={`btn btn-outline ${listening ? 'is-listening' : ''}`}
      disabled={disabled || !available || transcribing} aria-pressed={listening} aria-label="Hold to speak"
      onPointerDown={event => { event.currentTarget.setPointerCapture(event.pointerId); start(); }}
      onPointerUp={() => void activeSession()?.stop()} onPointerCancel={() => activeSession()?.cancel()}
      onKeyDown={event => { if (event.key === ' ' && !event.repeat) { event.preventDefault(); start(); } }}
      onKeyUp={event => { if (event.key === ' ') { event.preventDefault(); void activeSession()?.stop(); } }}
      onClick={event => { if (event.detail === 0) { if (listening) void activeSession()?.stop(); else start(); } }}>
      <Mic size={16} />{transcribing ? 'Transcribing locally…' : listening ? local?.enabled ? 'Listening… release to transcribe' : 'Listening… release to run' : local?.enabled ? 'Hold to dictate locally' : 'Hold to speak'}</button>
      {(listening || transcribing) && <button type="button" className="btn btn-outline" onClick={() => activeSession()?.cancel()}><Square size={14} />Cancel</button>}
      <label><input type="checkbox" checked={spoken} onChange={event => { setSpoken(event.target.checked); if (!event.target.checked) window.speechSynthesis?.cancel(); }} /><Volume2 size={14} /> Spoken replies</label>
    </div>
    <div className="assistant-voice-info"><p className="assistant-voice-hint">{available ? local?.enabled ? 'Audio stays on this computer. Review the transcript before pressing Ask.' : 'Release to run within enabled limits.' : 'Voice unavailable here. You can type your command.'}</p>
    <details className="assistant-voice-details"><summary>Voice & privacy</summary><p>{local?.enabled ? 'whisper.cpp transcribes locally. Audio is deleted after transcription. Transcripts are untrusted input and cannot approve or expand permissions.' : 'Invoice commands may execute within enabled limits. Browser speech may send audio to your browser’s recognition provider.'} Spoken replies use an available local English voice.</p></details></div>
    {error && <p role="status">{error}</p>}
    {spoken && !localVoices && <p role="status">No local English voice available. Responses appear as text.</p>}
  </div>;
}
