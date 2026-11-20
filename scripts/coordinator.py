"""Autonomous Multi-Agent Fleet Coordinator.
Orchestrates Mining and Trading agents across the Agent-to-Agent (A2A) protocol:
- Assesses current progress against platform targets (25 marks)
- Solicits strategic guidance from Groq LLM within strict budget limits
- Dispatches tasks to A2A workers (port 9999 for mining, 9998 for trading)
- Maintains persistent mission memory and restart-safety in SQLite
- Redacts credentials and logs auditable traces to logs/events.jsonl
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
from groq import Groq

from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types import Role, SendMessageRequest

from scripts.budget import reserve, complete, connection as budget_conn, usage as budget_usage
from scripts.evidence import record
from scripts.platform_score import calculate as calc_platform_score
from scripts.state_manager import StateManager

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = 'openai/gpt-oss-20b'
MINING_URL = 'http://127.0.0.1:9999'
TRADING_URL = 'http://127.0.0.1:9998'


class FleetCoordinator:
    """Central orchestrator for the autonomous multi-agent enterprise."""

    def __init__(self, groq_model: str = DEFAULT_MODEL):
        self.groq_model = groq_model
        self.state_mgr = StateManager()

    def _get_llm_strategic_plan(self, current_stats: Dict[str, Any]) -> str:
        """Consult Groq LLM for tactical mission prioritization within the allowed budget."""
        api_key = os.environ.get('GROQ_API_KEY')
        if not api_key:
            record('coordinator.warning', agent='coordinator', data={'msg': 'No GROQ_API_KEY set; using fallback heuristic planning'})
            return 'Execute standardized mining cycle (15 units) followed by station market liquidation.'

        # Check budget limit before making LLM call
        try:
            reservation_id = reserve(self.groq_model)
        except RuntimeError as e:
            record('coordinator.budget_gate', agent='coordinator', data={'reason': str(e)})
            return 'Budget cap reached. Execute deterministic mining and trading cycles.'

        try:
            client = Groq(api_key=api_key)
            prompt = (
                f'We are managing an autonomous SpaceMolt fleet with 2 pilots in the Nebula empire.\n'
                f'Targets: 30 ore mined, 2,000 credits earned, at least 1 trade, under 1,500 credits spent.\n'
                f'Current Stats: {json.dumps(current_stats)}\n'
                f'Provide 2-3 concise, actionable strategic instructions for the Mining and Trading agents.'
            )
            response = client.chat.completions.create(
                model=self.groq_model,
                temperature=0.2,
                max_completion_tokens=200,
                messages=[
                    {'role': 'system', 'content': 'You are an autonomous space fleet coordinator. Output direct strategic priorities only.'},
                    {'role': 'user', 'content': prompt}
                ]
            )
            usage = response.usage
            complete(reservation_id, getattr(usage, 'prompt_tokens', 0), getattr(usage, 'completion_tokens', 0))
            advice = response.choices[0].message.content or ''
            record('coordinator.llm_plan', agent='coordinator', data={'model': self.groq_model, 'advice': advice})
            return advice
        except Exception as e:
            complete(reservation_id, 0, 0, ok=False)
            record('coordinator.llm_error', agent='coordinator', data={'error': str(e)})
            return 'Deterministic fallback: prioritize ore extraction then station trade.'

    async def dispatch_a2a_task(self, worker_url: str, role: str, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch a task to an independent A2A worker service over JSON-RPC."""
        task_id = task_data.get('task_id') or f'A2A-{uuid.uuid4().hex[:8].upper()}'
        task_data['task_id'] = task_id

        # Record task creation in persistent SQLite store
        self.state_mgr.create_task(agent=role, goal=task_data.get('goal', f'{role} mission'), payload=task_data, task_id=task_id)
        record('a2a.dispatch', agent='coordinator', task_id=task_id, data={'url': worker_url, 'role': role})

        task_timeout = 600.0
        http_client = httpx.AsyncClient(timeout=task_timeout)
        async with httpx.AsyncClient(timeout=60.0) as http:
            resolver = A2ACardResolver(httpx_client=http, base_url=worker_url)
            card = await resolver.get_agent_card()

        client = await create_client(agent=card, client_config=ClientConfig(streaming=False, httpx_client=http_client))
        try:
            message = new_text_message(json.dumps(task_data, ensure_ascii=False), role=Role.ROLE_USER)
            last_response = None
            async for response in client.send_message(SendMessageRequest(message=message)):
                last_response = response

            record('a2a.response_received', agent='coordinator', task_id=task_id, data={'response': str(last_response)[:300]})
            return {'task_id': task_id, 'status': 'success', 'response': str(last_response)}
        finally:
            await client.close()
            await http_client.aclose()

    async def run_mission_cycle(self, mining_cycles: int = 5, explore: bool = False):
        """Execute a full coordinated operational cycle across both agents."""
        print('====================================================')
        print('  STARTING AUTONOMOUS ENTERPRISE COORDINATION CYCLE ')
        print('====================================================')

        # 1. State assessment & strategy
        summary = self.state_mgr.get_summary()
        plan = self._get_llm_strategic_plan(summary)
        print(f'\n[COORDINATOR STRATEGY]:\n{plan}\n')

        # 2. Dispatch Task 1: Mining / Resource Acquisition (Pilot A)
        print('[DISPATCHING TASK 1]: Mining / Resource Acquisition...')
        mining_task = {
            'task_id': f'MINE-{uuid.uuid4().hex[:6].upper()}',
            'goal': 'Extract ore from asteroid belt and return to station',
            'cycles': mining_cycles
        }
        try:
            mine_res = await self.dispatch_a2a_task(MINING_URL, 'mining', mining_task)
            if 'TASK_STATE_FAILED' in mine_res.get('response', ''):
                print('[TASK 1 FAILED]: Worker reported execution failure.')
            else:
                print('[TASK 1 COMPLETED]: Mining worker finished successfully.')
        except Exception as e:
            print(f'[TASK 1 FAILED]: Mining worker error: {e}')
            print('Ensure mining worker is running: python examples/a2a_worker.py --role mining --port 9999')

        # 3. Dispatch Task 2: Trading or System Exploration (Pilot B)
        if explore:
            print('\n[DISPATCHING TASK 2]: System Exploration (Pilot B -> Market Prime)...')
            second_task = {
                'task_id': f'EXPLORE-{uuid.uuid4().hex[:6].upper()}',
                'goal': 'Chart adjacent system market_prime and return to Haven',
                'action': 'explore',
                'target_system': 'market_prime'
            }
        else:
            print('\n[DISPATCHING TASK 2]: Trading / Market Liquidation...')
            second_task = {
                'task_id': f'TRADE-{uuid.uuid4().hex[:6].upper()}',
                'goal': 'Liquidate cargo ore on station exchange and record profit'
            }
        try:
            sec_res = await self.dispatch_a2a_task(TRADING_URL, 'trading', second_task)
            if 'TASK_STATE_FAILED' in sec_res.get('response', ''):
                print('[TASK 2 FAILED]: Worker reported execution failure.')
            else:
                task_name = 'Exploration' if explore else 'Trading'
                print(f'[TASK 2 COMPLETED]: {task_name} worker finished successfully.')
        except Exception as e:
            print(f'[TASK 2 FAILED]: Worker error: {e}')
            print('Ensure trading worker is running: python examples/a2a_worker.py --role trading --port 9998')

        # 4. Display budget and audit summary
        print('\n====================================================')
        print('  COORDINATION CYCLE SUMMARY & AUDIT LEDGER')
        print('====================================================')
        b_db = budget_conn()
        usage = budget_usage(b_db)
        b_db.close()
        print(f'LLM Requests Used: {usage["requests"]} / 300')
        print(f'LLM Tokens Used:   {usage["tokens"]} / 250,000')
        tasks_summary = self.state_mgr.get_summary()
        print(f'Persistent Tasks:  {tasks_summary["completed_tasks"]} completed / {tasks_summary["total_tasks"]} total')
        print('Audit events recorded to: logs/events.jsonl')


def main():
    parser = argparse.ArgumentParser(description='SpaceMolt Multi-Agent Fleet Coordinator')
    parser.add_argument('--cycles', type=int, default=5, help='Number of mining cycles per task')
    parser.add_argument('--model', default=DEFAULT_MODEL, help='Groq LLM model')
    parser.add_argument('--explore', action='store_true', help='Dispatch Pilot B to jump to an adjacent system to chart 2+ systems')
    args = parser.parse_args()

    coordinator = FleetCoordinator(groq_model=args.model)
    asyncio.run(coordinator.run_mission_cycle(mining_cycles=args.cycles, explore=args.explore))


if __name__ == '__main__':
    main()
