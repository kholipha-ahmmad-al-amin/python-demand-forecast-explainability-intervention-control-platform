from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.domain import DomainFailure, ForecastEngine, Role


class ObservationRequest(BaseModel):
    id: str
    sku: str
    observed_on: str
    units_sold: int = Field(ge=0)
    price: float = Field(gt=0)
    promotion_active: bool = False


class ForecastRequest(BaseModel):
    id: str
    sku: str
    forecast_on: str
    price: float = Field(gt=0)
    promotion_active: bool = False


class InterventionRequest(BaseModel):
    id: str
    forecast_run_id: str
    action_type: str


def create_app() -> FastAPI:
    app = FastAPI(title="Demand Forecast Explainability Control")
    engine = ForecastEngine()
    app.state.engine = engine

    def identity(actor: str | None, role_value: str | None) -> tuple[str, Role]:
        if not actor or len(actor.strip()) < 3:
            raise DomainFailure("authorization", "authenticated actor header is required")
        try:
            return actor.strip(), Role(role_value or "")
        except ValueError as error:
            raise DomainFailure("authorization", "valid forecast role header is required") from error

    def execute(callback):
        try:
            return callback()
        except DomainFailure as failure:
            status = {"validation": 422, "authorization": 403, "conflict": 409, "not_found": 404}.get(failure.kind, 500)
            raise HTTPException(status, {"error": failure.message, "kind": failure.kind}) from failure

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "python-demand-forecast-explainability-control"}

    @app.get("/api/snapshot")
    def snapshot(x_actor: str | None = Header(default=None), x_role: str | None = Header(default=None)):
        return execute(lambda: (identity(x_actor, x_role), engine.snapshot())[1])

    @app.post("/api/observations", status_code=201)
    def observation(input: ObservationRequest, x_actor: str | None = Header(default=None), x_role: str | None = Header(default=None)):
        def run():
            actor, role = identity(x_actor, x_role)
            payload = input.model_dump()
            return engine.add_observation(actor, role, payload["id"], payload["sku"], payload["observed_on"], payload["units_sold"], payload["price"], payload["promotion_active"]).__dict__
        return execute(run)

    @app.post("/api/forecasts", status_code=201)
    def forecast(input: ForecastRequest, x_actor: str | None = Header(default=None), x_role: str | None = Header(default=None)):
        def run():
            actor, role = identity(x_actor, x_role)
            payload = input.model_dump()
            return engine.create_forecast(actor, role, payload["id"], payload["sku"], payload["forecast_on"], payload["price"], payload["promotion_active"]).__dict__
        return execute(run)

    @app.post("/api/interventions", status_code=201)
    def intervention(input: InterventionRequest, x_actor: str | None = Header(default=None), x_role: str | None = Header(default=None)):
        def run():
            actor, role = identity(x_actor, x_role)
            payload = input.model_dump()
            item = engine.propose_intervention(actor, role, payload["id"], payload["forecast_run_id"], payload["action_type"])
            return {**item.__dict__, "status": item.status.value}
        return execute(run)

    @app.post("/api/interventions/{intervention_id}/approve")
    def approve(intervention_id: str, x_actor: str | None = Header(default=None), x_role: str | None = Header(default=None)):
        def run():
            actor, role = identity(x_actor, x_role)
            item = engine.approve_intervention(actor, role, intervention_id)
            return {**item.__dict__, "status": item.status.value}
        return execute(run)

    @app.post("/api/demo")
    def demo(x_actor: str | None = Header(default=None), x_role: str | None = Header(default=None)):
        return execute(lambda: engine.seed_demo(*identity(x_actor, x_role)))

    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        return DASHBOARD_HTML + APPROVAL_SCRIPT

    return app


app = create_app()


APPROVAL_SCRIPT = """<script>
const priorForecastRenderer = renderForecasts;
renderForecasts = function(items, interventions) {
  priorForecastRenderer(items, interventions);
  const proposed = interventions.filter(item => item.status === 'PROPOSED');
  if (!proposed.length) return;
  const queue = document.createElement('div');
  queue.className = 'forecast';
  queue.innerHTML = '<b>Approval queue</b><div class=\"message\">Approver or administrator authority is required before a replenishment intervention is approved.</div>';
  proposed.forEach(item => {
    const button = document.createElement('button');
    button.textContent = 'Approve ' + item.action_type;
    button.className = 'gold';
    button.onclick = async () => {
      try {
        await api('/api/interventions/' + encodeURIComponent(item.id) + '/approve', {method: 'POST', body: '{}'});
        note('Intervention approved.');
        load();
      } catch (error) {
        note(error.message, true);
      }
    };
    queue.appendChild(button);
  });
  document.querySelector('#forecasts').appendChild(queue);
};
</script>"""


DASHBOARD_HTML = """<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Northstar Forecast Control</title><style>
:root{--ink:#1e2940;--bg:#f6f5fb;--muted:#6d7184;--violet:#5b4ad4;--purple:#8b5cf6;--line:#dedcef;--card:#fff;--gold:#c47c24;--green:#16745a;--red:#bd4755}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 90% 0,#e4ddff 0,transparent 35%),var(--bg);color:var(--ink);font:15px Inter,ui-sans-serif,system-ui,sans-serif}header{background:linear-gradient(115deg,#32265e,#5b3da6);color:white;padding:30px clamp(20px,5vw,70px);display:flex;align-items:end;justify-content:space-between;gap:20px}h1{font-size:clamp(29px,4vw,46px);letter-spacing:-.05em;margin:5px 0}h2{font-size:16px;margin:0 0 14px}.eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.15em;color:#ddd2ff;font-weight:900}.online{border:1px solid #b5a1ff;border-radius:999px;background:#513e9c;color:#eee9ff;padding:8px 12px;font-weight:900}.shell{max-width:1450px;margin:auto;padding:28px clamp(20px,5vw,70px) 58px}.identity,.forms,.grid{display:grid;gap:16px}.identity{grid-template-columns:1fr 190px auto;align-items:end;background:#ece9fb;border:1px solid var(--line);padding:16px;border-radius:13px;margin-bottom:18px}.forms{grid-template-columns:repeat(3,1fr);margin-bottom:18px}.grid{grid-template-columns:1.35fr .9fr;align-items:start}.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:19px;box-shadow:0 10px 26px #50359c0d}.form-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:9px}.span2{grid-column:span 2}label{display:grid;gap:6px;font-size:12px;color:var(--muted);font-weight:800}input,select{width:100%;padding:10px;background:white;border:1px solid var(--line);border-radius:8px;color:var(--ink)}button{padding:10px 12px;border:0;border-radius:8px;background:var(--violet);color:white;font-weight:900;cursor:pointer}button.gold{background:var(--gold)}button:active{transform:scale(.97)}.message{color:var(--muted);font-size:13px}.error{color:var(--red)}.table{display:grid;gap:8px}.forecast{background:#f8f7ff;border:1px solid #e2dff5;border-radius:10px;padding:13px;display:grid;gap:9px}.head{display:flex;justify-content:space-between;gap:10px}.metric{font-size:27px;font-weight:950;letter-spacing:-.04em;color:var(--violet)}.badges{display:flex;gap:6px;flex-wrap:wrap}.badge{font-size:11px;border-radius:999px;background:#e8e3ff;color:#5841b5;font-weight:900;padding:4px 8px}.features{display:grid;grid-template-columns:repeat(2,1fr);gap:6px}.feature{font-size:12px;background:white;border:1px solid #eceafd;padding:7px;border-radius:7px}.events{display:grid;gap:8px;max-height:600px;overflow:auto}.event{background:#f3f1ff;border-left:3px solid var(--purple);padding:12px;border-radius:0 8px 8px 0}.event small{display:block;color:var(--muted);margin-top:4px}.empty{padding:28px;text-align:center;color:var(--muted)}@media(max-width:960px){.forms,.grid{grid-template-columns:1fr}.identity{grid-template-columns:1fr}}@media(max-width:540px){header{align-items:start;flex-direction:column}.form-grid,.features{grid-template-columns:1fr}.span2{grid-column:span 1}}
</style></head><body><header><div><div class=\"eyebrow\">Northstar planning intelligence</div><h1>Demand forecast explainability</h1><p>Turn historical demand into accountable replenishment decisions with model evidence, local explanations, and controlled approvals.</p></div><div id=\"health\" class=\"online\">Checking service</div></header><main class=\"shell\"><section class=\"identity\"><label>Operator<input id=\"actor\" value=\"forecast-analyst\"></label><label>Role<select id=\"role\"><option>ANALYST</option><option>PLANNER</option><option>APPROVER</option><option>ADMIN</option><option>OBSERVER</option></select></label><button id=\"reload\">Refresh planning board</button></section><p id=\"message\" class=\"message\">Seed the local workspace to demonstrate forecast and intervention controls.</p><section class=\"forms\"><article class=\"card\"><h2>Training workspace</h2><p class=\"message\">Create a local planning dataset with historical observations for one SKU.</p><button id=\"seed\" class=\"span2\">Seed planning workspace</button></article><article class=\"card\"><h2>Create forecast</h2><form id=\"forecastForm\" class=\"form-grid\"><label>Forecast ID<input name=\"id\" value=\"FC-1001\" required></label><label>SKU<input name=\"sku\" value=\"DEMO-SKU\" required></label><label>Forecast date<input name=\"forecast_on\" value=\"2026-01-15\" required></label><label>Price<input name=\"price\" type=\"number\" step=\"0.01\" value=\"22\" required></label><label class=\"span2\">Promotion active<select name=\"promotion_active\"><option value=\"false\">No</option><option value=\"true\">Yes</option></select></label><button class=\"span2\">Run forecast</button></form></article><article class=\"card\"><h2>Planning intervention</h2><form id=\"interventionForm\" class=\"form-grid\"><label>Intervention ID<input name=\"id\" value=\"INT-1001\" required></label><label>Forecast ID<input name=\"forecast_run_id\" value=\"FC-1001\" required></label><label class=\"span2\">Action<select name=\"action_type\"><option value=\"increase_replenishment\">Increase replenishment</option><option value=\"reduce_replenishment\">Reduce replenishment</option><option value=\"review_promotion\">Review promotion</option></select></label><button class=\"span2 gold\">Propose intervention</button></form></article></section><section class=\"grid\"><article class=\"card\"><h2>Forecast evidence</h2><div id=\"forecasts\" class=\"table\"><div class=\"empty\">No forecasts loaded.</div></div></article><aside class=\"card\"><h2>Decision audit</h2><div id=\"events\" class=\"events\"><div class=\"empty\">No audit evidence loaded.</div></div></aside></section></main><script>
const s=q=>document.querySelector(q),m=s('#message'),hdr=()=>({'X-Actor':s('#actor').value,'X-Role':s('#role').value,'Content-Type':'application/json'}),esc=v=>String(v).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));function note(t,b=false){m.textContent=t;m.className=b?'message error':'message'}async function api(path,opt={}){const r=await fetch(path,{...opt,headers:{...hdr(),...(opt.headers||{})}}),p=await r.json();if(!r.ok)throw Error(p.detail?.error||p.error||'Request failed');return p}function renderForecasts(items,interventions){s('#forecasts').innerHTML=items.length?items.map(f=>{const factors=Object.entries(f.shap_contributions).map(([k,v])=>'<div class=\"feature\"><b>'+esc(k)+'</b> '+Number(v).toFixed(3)+'</div>').join('');const ints=interventions.filter(i=>i.forecast_run_id===f.id).map(i=>'<span class=\"badge\">'+esc(i.action_type)+' '+esc(i.status)+'</span>').join('');return '<div class=\"forecast\"><div class=\"head\"><div><b>'+esc(f.sku)+'</b><div class=\"message\">'+esc(f.id)+' via '+esc(f.model_version)+'</div></div><div><div class=\"metric\">'+Number(f.projected_units).toFixed(1)+'</div><div class=\"message\">projected units with '+Math.round(Number(f.confidence)*100)+'% confidence</div></div></div><div class=\"badges\">'+(ints||'<span class=\"badge\">No intervention</span>')+'</div><div class=\"features\">'+factors+'</div></div>'}).join(''):'<div class=\"empty\">No forecasts are currently available.</div>'}function renderEvents(items){s('#events').innerHTML=items.length?items.map(e=>'<div class=\"event\"><b>'+esc(e.action)+'</b><span>'+esc(e.detail)+'</span><small>'+esc(e.actor)+' at '+new Date(e.created_at).toLocaleString()+'</small></div>').join(''):'<div class=\"empty\">No audit evidence is available.</div>'}async function load(){try{const d=await api('/api/snapshot');renderForecasts(d.forecasts,d.interventions);renderEvents(d.audit_events);note('Planning board refreshed with '+d.observations.length+' observations.')}catch(e){note(e.message,true)}}function bind(form,path){s(form).onsubmit=async e=>{e.preventDefault();const f=e.currentTarget,p=Object.fromEntries(new FormData(f));p.price&&=Number(p.price);p.promotion_active=p.promotion_active==='true';try{await api(path,{method:'POST',body:JSON.stringify(p)});note('Planning action recorded.');load()}catch(x){note(x.message,true)}}}bind('#forecastForm','/api/forecasts');bind('#interventionForm','/api/interventions');s('#seed').onclick=async()=>{try{await api('/api/demo',{method:'POST',body:'{}'});note('Planning workspace seeded.');load()}catch(e){note(e.message,true)}};s('#reload').onclick=load;fetch('/health').then(r=>r.ok?s('#health').textContent='Forecast API online':Promise.reject()).catch(()=>s('#health').textContent='Forecast API unavailable');load();
</script></body></html>"""
