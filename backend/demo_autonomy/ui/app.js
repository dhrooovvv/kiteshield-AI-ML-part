const $ = id => document.getElementById(id);
const tokens = {agent: '', admin: '', approver: ''};
let refreshing = false;
async function request(path, role = 'agent', body, method) {
  if (!tokens[role]) throw new Error(`Connect the ${role} role first.`);
  const response = await fetch('/demo' + path, {method: method || (body ? 'POST' : 'GET'),
    headers: {Authorization: 'Bearer ' + tokens[role], 'Content-Type': 'application/json'},
    ...(body ? {body: JSON.stringify(body)} : {})});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Request rejected. Check the fields.');
  return result;
}
const words = value => String(value || '').toLowerCase().replaceAll('_', ' ');
function node(tag, text, className) {
  const result = document.createElement(tag);
  if (text !== undefined) result.textContent = text;
  if (className) result.className = className;
  return result;
}
function notice(text) {$('notice').textContent = text;}
async function refresh() {
  if (!tokens.agent || refreshing) return;
  refreshing = true;
  try {
    const data = await request('/snapshot');
    $('control').textContent = data.control.quarantined ? 'Agent quarantined' : 'Working within your permissions';
    $('resume').hidden = !data.control.quarantined;
    $('count').textContent = `${data.tasks.length} recorded tasks`;
    $('tasks').replaceChildren();
    if (!data.tasks.length) $('tasks').append(node('p', 'Start a task above to watch the wallet work.', 'empty'));
    for (const task of data.tasks) {
      const article = node('article', undefined, 'task');
      const head = node('div', undefined, 'task-head');
      head.append(node('h3', `Pay saved supplier · ${task.amount} wei`), node('span', words(task.state), 'state ' + (task.state === 'COMPLETED' ? 'completed' : task.state === 'WAITING_APPROVAL' ? 'waiting' : '')));
      article.append(head);
      const steps = node('ol', undefined, 'steps');
      for (const [index, name] of ['Check balance', 'Fund if needed', 'Pay supplier', 'Verify result'].entries()) {
        const step = task.steps[index];
        steps.append(node('li', name, step?.state === 'COMPLETED' ? 'done' : ['RUNNING', 'WAITING'].includes(step?.state) ? 'active' : ''));
      }
      article.append(steps);
      if (task.reason) article.append(node('p', words(task.reason)));
      if (task.state === 'WAITING_APPROVAL') {
        const actions = node('div', undefined, 'approval-actions');
        for (const choice of ['APPROVE', 'REJECT']) {
          const button = node('button', choice === 'APPROVE' ? 'Approve as human' : 'Reject as human', 'secondary');
          button.onclick = async () => {try {await request(`/approvals/${task.id}/decision`, 'approver', {decision: choice}); notice('Human decision recorded.'); await refresh();} catch (e) {notice(e.message);}};
          actions.append(button);
        }
        article.append(actions);
      }
      const detail = node('details'); detail.append(node('summary', `Persisted timeline · ${task.events.length} events`));
      for (const event of task.events) detail.append(node('div', `${words(event.kind)}: ${event.detail}`, 'event'));
      article.append(detail); $('tasks').append(article);
    }
    $('issues').replaceChildren();
    for (const issue of data.issues) {
      const item = node('div', undefined, 'issue');
      item.append(node('strong', words(issue.reason)), node('p', issue.task_id ? `Task ${issue.task_id.slice(0, 8)}` : 'Untrusted event or instruction'));
      $('issues').append(item);
    }
    if (!data.issues.length) $('issues').append(node('p', 'No exceptions recorded.', 'empty'));
  } catch (e) {notice(e.message);} finally {refreshing = false;}
}
$('connect').onsubmit = async event => {event.preventDefault(); for (const role of Object.keys(tokens)) {tokens[role] = $(role).value; $(role).value = '';} $('connection').open = false; notice('Demo roles connected for this page session.'); await refresh();};
$('goal').onsubmit = async event => {event.preventDefault(); const button = event.submitter; button.disabled = true; try {const task = await request('/goals', 'agent', {goal: $('instruction').value, request_key: crypto.randomUUID()}); notice(`Task ${task.task_id.slice(0, 8)} started. No further clicks are needed within your permissions.`); await refresh();} catch (e) {notice(e.message);} finally {button.disabled = false;}};
$('mandate').onsubmit = async event => {event.preventDefault(); try {await request('/mandate', 'admin', {supplier: $('supplier').value, recipient: $('recipient').value, payment_cap: Number($('payment-cap').value), funding_cap: Number($('funding-cap').value), approval_threshold: Number($('threshold').value)}, 'PUT'); notice('Administrator permissions saved.');} catch (e) {notice(e.message);}};
$('resume').onclick = async () => {try {await request('/quarantine/resume', 'admin', {}); notice('Administrator resumed the agent.'); await refresh();} catch (e) {notice(e.message);}};
fetch('/demo/health').then(r => r.json()).then(data => {$('health').textContent = data.planner_enabled ? 'Local Gemma planner enabled' : 'Planner disabled';}).catch(() => {$('health').textContent = 'Demo backend unavailable';});
setInterval(refresh, 1500);
