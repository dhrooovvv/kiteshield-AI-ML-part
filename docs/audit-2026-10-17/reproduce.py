import sys, asyncio, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
import tests.conftest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select, func
from app.main import create_app
from app.db import get_db_session
from app.models import Base, ExecutionControl, SpendingRecord, CapabilityToken, ApprovalRequest
from app.api.routes import proposals
from app.services.agent import AgentService
from app.exceptions import TransactionSubmissionError

async def main():
    engine=create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    factory=async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(ExecutionControl(id='global', active=False, reason='', changed_by='test', version=0)); await s.commit()
    async def db():
        async with factory() as s:
            try: yield s; await s.commit()
            except Exception: await s.rollback(); raise
    app=create_app(); app.dependency_overrides[get_db_session]=db
    calls=[]
    async def broadcast(raw, *,session):
        calls.append(raw)
        return {'tx_hash':'0x'+format(len(calls),'064x'), 'status':'SUBMITTED','network':'isolated-audit-mock'}
    proposals.blockchain_service.submit_raw_transaction=broadcast
    async with AsyncClient(transport=ASGITransport(app=app,raise_app_exceptions=False),base_url='http://test',headers={'X-API-Key':tests.conftest.os.environ['API_KEY']}) as c:
        async def policy(**kwargs):
            r=await c.post('/api/v1/policies',json={'max_amount_wei':str(10**18),**kwargs}); assert r.status_code==200,r.text
            return r.json()['data']
        async def propose(amount, recipient='0x'+'12'*20):
            r=await c.post('/api/v1/proposals',json={'prompt':'isolated audit','recipient':recipient,'amount_wei':str(amount),'chain_id':11155111}); assert r.status_code==200,r.text
            return r.json()['data']['id']
        async def evaluate(p): return await c.post(f'/api/v1/proposals/{p}/evaluate')
        async def sign(p): return await c.post(f'/api/v1/proposals/{p}/sign')
        await policy(daily_limit_wei=str(10**17))
        statuses=[]
        for recipient in ['0x'+'12'*20,'0x'+'13'*20]:
            p=await propose(6*10**16,recipient); e=await evaluate(p); r=await sign(p)
            statuses.append({'decision':e.json()['data']['policy_decision']['decision'],'sign_http':r.status_code})
        async with factory() as s: count=await s.scalar(select(func.count()).select_from(SpendingRecord))
        print(json.dumps({'probe':'daily_limit_0.1_ETH_two_0.06_ETH_transfers','results':statuses,'spending_records':count}))
        await policy(); p=await propose(5*10**16); await evaluate(p)
        new=await policy(max_amount_wei='1'); r=await sign(p)
        print(json.dumps({'probe':'policy_tightened_after_evaluation','new_max_wei':new['max_amount_wei'],'sign_http':r.status_code,'status':r.json().get('data',{}).get('status')}))
        await policy()
        e=await evaluate(p)
        print(json.dumps({'probe':'reevaluate_submitted_proposal','http':e.status_code,'status':e.json().get('data',{}).get('status')}))
        await policy(escalation_threshold_wei='1'); p=await propose(1234); e=await evaluate(p); aid=e.json()['data']['approval']['id']
        r=await c.post(f'/api/v1/approvals/{aid}/decide',json={'decision':'APPROVE','approved_by':'arbitrary-claimed-human'})
        print(json.dumps({'probe':'proposer_credential_approves_with_self_declared_identity','http':r.status_code,'approved_by':r.json().get('data',{}).get('approved_by')}))
        async with factory() as s:
            approval=await s.get(ApprovalRequest,aid); approval.expires_at='2000-01-01T00:00:00+00:00'; await s.commit()
        r=await sign(p)
        print(json.dumps({'probe':'approved_record_expired_before_sign','sign_http':r.status_code,'status':r.json().get('data',{}).get('status')}))
        await policy(); p=await propose(5678); await evaluate(p)
        before=len(calls)
        async def ambiguous_broadcast(raw, *,session):
            calls.append(raw); raise TransactionSubmissionError('isolated audit: node accepted but response was lost')
        proposals.blockchain_service.submit_raw_transaction=ambiguous_broadcast
        r=await sign(p)
        state=(await c.get(f'/api/v1/proposals/{p}')).json()['data']
        async with factory() as s: consumed=await s.scalar(select(func.count()).select_from(CapabilityToken).where(CapabilityToken.proposal_id==p))
        print(json.dumps({'probe':'broadcast_side_effect_then_error','http':r.status_code,'broadcast_calls':len(calls)-before,'persisted_status':state['status'],'persisted_token_rows':consumed}))
    service=AgentService(api_key='')
    for text in ['Send .03 ETH to 0x'+'12'*20,'Send ETH to 0x'+'12'*20,'Send -0.03 ETH to 0x'+'12'*20]:
        p=service._parse_with_rules(text)
        print(json.dumps({'probe':'parser','prompt':text,'amount_wei':p.amount_wei}))
    await engine.dispose()
asyncio.run(main())
