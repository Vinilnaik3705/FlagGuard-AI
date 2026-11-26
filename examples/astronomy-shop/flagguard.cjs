// Optional adapter for the upstream Astronomy Shop payment service.
// Node 22+; only synthetic test traffic. Never forwards payment data.
const { performance } = require('node:perf_hooks');
const FLAG = 'new_checkout';
let cached, expires = 0;
async function flag(identity) {
  if (process.env.FLAGGUARD_IDENTITY_MODE === 'true') {
    if (!/^fg-test-[0-9]{1,10}$/.test(identity || '')) throw Error('Missing synthetic identity');
    const url = new URL('https://edge.api.flagsmith.com/api/v1/identities/');
    url.searchParams.set('identifier', identity);
    const response = await fetch(url, {headers:{'X-Environment-Key':process.env.FLAGSMITH_ENVIRONMENT_KEY},signal:AbortSignal.timeout(5000)});
    if (!response.ok) throw Error('Identity evaluation unavailable');
    const data = await response.json();
    const found = data.flags?.find(f => f.feature?.name === FLAG);
    if (!found || typeof found.enabled !== 'boolean') throw Error('Missing identity flag');
    return found.enabled;
  }
  if (Date.now() < expires) return cached;
  const response = await fetch('https://edge.api.flagsmith.com/api/v1/flags/', {
    headers: {'X-Environment-Key': process.env.FLAGSMITH_ENVIRONMENT_KEY},
    signal: AbortSignal.timeout(2000)
  });
  if (!response.ok) throw Error('Flag evaluation unavailable');
  const flags = await response.json();
  const found = flags.find(f => f.feature?.name === FLAG);
  if (!found || typeof found.enabled !== 'boolean') throw Error('Missing flag');
  cached = found.enabled; expires = Date.now() + 2000;
  return cached;
}
let pending = 0;
function report(enabled, status, start) {
  if (pending >= 32 || !process.env.FLAGGUARD_URL || !(process.env.FLAGGUARD_TELEMETRY_KEY || process.env.FLAGGUARD_API_KEY)) return;
  pending++;
  fetch(process.env.FLAGGUARD_URL.replace(/\/$/, '') + '/api/v1/telemetry', {
    method: 'POST',
    headers: {'Authorization': 'Bearer ' + (process.env.FLAGGUARD_TELEMETRY_KEY || process.env.FLAGGUARD_API_KEY), 'Content-Type': 'application/json'},
    body: JSON.stringify({service:'astronomy-payment',environment:'development',flags:{[FLAG]:enabled},status_code:status,latency_ms:performance.now()-start}),
    signal: AbortSignal.timeout(2000)
  }).catch(()=>{}).finally(()=>pending--);
}
async function instrument(original, request, identity) {
  if (process.env.FLAGGUARD_DEMO_MODE !== 'true') return original(request);
  let enabled;
  try { enabled = await flag(identity); } catch { return original(request); }
  const start = performance.now();
  let status = 200;
  try {
    if (enabled && Math.random() < 0.3) throw Error('FlagGuard synthetic payment failure');
    return await original(request);
  } catch (err) { status = 500; throw err; }
  finally { report(enabled,status,start); }
}
module.exports = {instrument};
