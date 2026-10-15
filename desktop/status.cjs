'use strict';
(async () => {
  const bridge = window.leafloomDesktop;
  const info = await bridge.appInfo();
  const t=info.text;
  document.getElementById('message').textContent = t.starting;
  document.querySelectorAll('p')[1].textContent = t.offline;
  for (const id of ['retry','logs','quit']) document.getElementById(id).textContent = t[id];
  if (info.error) {document.getElementById('message').textContent = t.failed; document.getElementById('error').textContent = info.error; document.getElementById('actions').hidden = false;}
  document.getElementById('retry').onclick = () => {document.getElementById('actions').hidden = true; document.getElementById('error').textContent = ''; document.getElementById('message').textContent = t.retrying; void bridge.retry();};
  document.getElementById('logs').onclick = () => void bridge.openLogs();
  document.getElementById('quit').onclick = () => void bridge.quit();
})().catch(error => {document.getElementById('error').textContent = error.message;});
