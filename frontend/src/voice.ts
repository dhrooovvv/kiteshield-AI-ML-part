/** Browser speech is opt-in and may use the browser's remote recognition service. */
export interface RecognitionResult {
  isFinal: boolean; 0: { transcript: string; confidence: number };
}
export interface Recognition {
  lang: string; continuous: boolean; interimResults: boolean;
  onresult: ((event: { results: ArrayLike<RecognitionResult> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void; stop(): void; abort(): void;
}
export type RecognitionConstructor = new () => Recognition;
export function browserRecognition(): RecognitionConstructor | undefined {
  if (typeof window === 'undefined') return undefined;
  const browser = window as unknown as { SpeechRecognition?: RecognitionConstructor; webkitSpeechRecognition?: RecognitionConstructor };
  return browser.SpeechRecognition ?? browser.webkitSpeechRecognition;
}
export function voiceSession(Constructor: RecognitionConstructor, events: {
  text(value: string): void; listening(value: boolean): void;
  final(value: string): void; error(value: string): void;
}) {
  const recognition = new Constructor();
  recognition.lang = 'en-IN'; recognition.continuous = false; recognition.interimResults = true;
  let cancelled = false, running = false, finalText = '', confident = true;
  recognition.onresult = event => {
    const results = Array.from(event.results);
    events.text(results.map(result => result[0].transcript).join(' ').slice(0, 2000));
    const finals = results.filter(result => result.isFinal);
    finalText = finals.map(result => result[0].transcript).join(' ').trim().slice(0, 2000);
    confident = finals.every(result => result[0].confidence >= .75);
  };
  recognition.onerror = event => {
    cancelled = true;
    events.error(event.error === 'not-allowed' ? 'Microphone permission was denied. You can type instead.'
      : event.error === 'no-speech' ? 'No speech detected. Hold the microphone and try again.'
      : 'Browser speech unavailable. Use text input or a supported browser.');
  };
  recognition.onend = () => {
    running = false; events.listening(false);
    if (cancelled || !finalText) return;
    if (!confident) { events.error('Speech was uncertain. Review the transcript and press Ask.'); return; }
    events.final(finalText);
  };
  return {
    start() {
      if (running) return;
      cancelled = false; finalText = ''; confident = true;
      try { recognition.start(); running = true; events.listening(true); }
      catch { events.error('Cannot start the microphone. Try again or type your request.'); }
    },
    stop() { if (running) recognition.stop(); },
    cancel() { cancelled = true; running = false; recognition.abort(); events.listening(false); },
  };
}
export function speakLocally(text: string): boolean {
  if (typeof window === 'undefined' || !window.speechSynthesis) return false;
  const voice = window.speechSynthesis.getVoices().find(item => item.localService && item.lang.startsWith('en'));
  if (!voice) return false;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text.slice(0, 400));
  utterance.voice = voice; window.speechSynthesis.speak(utterance);
  return true;
}
