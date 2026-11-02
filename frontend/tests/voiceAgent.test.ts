import test from 'node:test';
import assert from 'node:assert/strict';
import { voiceSession } from '../src/voice.ts';
import type { Recognition, RecognitionResult } from '../src/voice.ts';
import { contextualQuestion } from '../src/assistant.ts';
import { invoiceAutomationDisabled, invoiceOutcome, taskFinished, taskStage } from '../src/invoiceAgent.ts';
class FakeRecognition implements Recognition {
  static instance: FakeRecognition;
  lang=''; continuous=false; interimResults=false;
  onresult: Recognition['onresult']=null; onerror: Recognition['onerror']=null; onend: Recognition['onend']=null;
  constructor(){ FakeRecognition.instance=this; }
  start() {} stop() { this.onend?.(); } abort() { this.onend?.(); }
  result(text: string, confidence: number, final = true) {
    this.onresult?.({ results: [{ isFinal: final, 0: { transcript: text, confidence } } as RecognitionResult] });
  }
}
test('voice runs only a confident final transcript once recognition ends', () => {
  const results: string[]=[];
  const voice=voiceSession(FakeRecognition,{text(){},listening(){},error(){},final(text){results.push(text);}});
  voice.start(); FakeRecognition.instance.result('Find acme.pdf and pay it.',.98,false);
  assert.equal(results.length,0);
  FakeRecognition.instance.result('Find acme.pdf and pay it.',.98); voice.stop();
  assert.deepEqual(results,['Find acme.pdf and pay it.']);
});
test('cancelled and uncertain speech never auto-runs a command', () => {
  const results: string[]=[], errors:string[]=[];
  const voice=voiceSession(FakeRecognition,{text(){},listening(){},error(text){errors.push(text);},final(text){results.push(text);}});
  voice.start(); FakeRecognition.instance.result('Pay invoice.pdf',.99); voice.cancel();
  voice.start(); FakeRecognition.instance.result('Pay invoice.pdf',.5); voice.stop();
  assert.equal(results.length,0); assert.match(errors[0],/Review the transcript/);
});
test('read follow-up context never supplies payment authority', () => {
  assert.match(contextualQuestion('And last month?',{kind:'payments',question:'What was my biggest payment today?'}),/last month/);
  for (const kind of ['payment','invoice_task','funding']) {
    assert.equal(contextualQuestion('And last month?',{kind,question:'Send 1 ETH to someone'}),'And last month?');
  }
});
test('task labels keep simulation, checked and submitted outcomes distinct', () => {
  assert.equal(invoiceOutcome('SIMULATED'),'Simulated · no funds sent');
  assert.equal(invoiceOutcome('CHECKED'),'Checked · not executed');
  assert.equal(invoiceOutcome('PAID'),'Submitted · awaiting receipt');
  const task={state:'NEEDS_ATTENTION',stage:'RESULT_RECORDED'} as Parameters<typeof taskStage>[0];
  assert.equal(taskStage(task),'Needs attention'); assert.equal(taskFinished(task),true);
});

test('historical automation-disabled reason does not contradict a submitted or confirmed invoice', () => {
  const task = (states: string[]) => ({
    reason: 'AUTOMATION_DISABLED', items: states.map(state => ({ state })),
  }) as Parameters<typeof invoiceAutomationDisabled>[0];
  assert.equal(invoiceAutomationDisabled(task(['CHECKED'])), true);
  assert.equal(invoiceAutomationDisabled(task(['PAID'])), false);
  assert.equal(invoiceAutomationDisabled(task(['VERIFIED'])), false);
  assert.equal(invoiceAutomationDisabled(task(['VERIFIED', 'CHECKED'])), true);
  assert.equal(invoiceAutomationDisabled(task([])), false);
});
