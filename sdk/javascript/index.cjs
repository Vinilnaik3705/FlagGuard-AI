// Server-side Node.js 22+ client. Do not embed credentials in browser code.
class FlagGuardClient {
  constructor({service, environment, url=process.env.FLAGGUARD_URL || 'http://127.0.0.1:8000', apiKey=process.env.FLAGGUARD_TELEMETRY_KEY || process.env.FLAGGUARD_API_KEY, timeout=2000}) {
    const parsed = new URL(url);
    if (parsed.username || parsed.password || parsed.search || parsed.hash || (parsed.protocol !== 'https:' && !(parsed.protocol === 'http:' && ['localhost','127.0.0.1','[::1]'].includes(parsed.hostname)))) throw new Error('HTTPS required except for local development');
    if (!apiKey || ![service, environment].every(x => typeof x === 'string' && x.length > 0 && x.length <= 100) || !Number.isInteger(timeout) || timeout < 1 || timeout > 10000) throw new Error('Invalid client configuration');
    Object.assign(this,{service,environment,url:url.replace(/\/+$/,''),apiKey,timeout});
  }
  async record(flags,statusCode,latencyMs,segments={}) {
    if (!flags || typeof flags !== 'object' || Array.isArray(flags) || !Object.values(flags).every(v=>typeof v==='boolean') || !Number.isInteger(statusCode) || statusCode<100 || statusCode>599 || !Number.isFinite(latencyMs) || latencyMs<0) throw new Error('Invalid telemetry');
    if (!segments || typeof segments !== 'object' || Array.isArray(segments) || Object.keys(segments).length>100 || Object.entries(segments).some(([k,v])=>!Object.hasOwn(flags,k)||!Number.isSafeInteger(v)||v<=0)) throw new Error('Invalid evaluated segment metadata');
    try {
      const response = await fetch(this.url+'/api/v1/telemetry',{method:'POST',redirect:'error',headers:{Authorization:'Bearer '+this.apiKey,'Content-Type':'application/json'},body:JSON.stringify({service:this.service,environment:this.environment,flags,status_code:statusCode,latency_ms:latencyMs,segments}),signal:AbortSignal.timeout(this.timeout)});
      return response.ok;
    } catch { return false; }
  }
}
module.exports={FlagGuardClient};
