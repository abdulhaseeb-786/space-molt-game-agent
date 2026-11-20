"""Baseline Single-Agent Implementation (Deterministic Monolithic Script).
Satisfies Assignment Requirement: "Single-agent or deterministic baseline comparison (5 marks)"

Unlike the Multi-Agent System (MAS), this baseline:
1. Runs sequentially in a single process with no A2A protocol.
2. Uses hardcoded deterministic rules with no LLM tactical reasoning.
3. Has no role separation (one pilot performs both mining and selling).
4. Has minimal error recovery and no distributed task queues.

Use this script to compare throughput, modularity, and failure recovery against your MAS.
"""
from __future__ import annotations
import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evidence import record
from scripts.mcp_game import SpaceMoltMCPClient, resolve_pilot_credentials


async def run_baseline_cycle(cycles: int = 3) -> Dict[str, Any]:
    """Execute monolithic sequential workflow: undock -> travel -> mine -> return -> dock -> sell."""
    start_time = time.time()
    username, password = resolve_pilot_credentials(pilot_num=1)
    record('baseline.start', agent=username, data={'cycles': cycles})

    print('====================================================')
    print('  RUNNING MONOLITHIC SINGLE-AGENT BASELINE')
    print('====================================================')
    print(f'Pilot: {username}')

    async with SpaceMoltMCPClient(username=username, password=password) as client:
        # Step 1: Query initial state
        loc = await client.get_location()
        sys_info = await client.get_system()
        pois = sys_info.get('pois', []) or []

        asteroid_poi = None
        station_poi = None
        for p in pois:
            p_name = (p.get('name') or p.get('type') or '').lower()
            if any(k in p_name for k in ('asteroid', 'belt', 'deposit', 'field', 'ore')):
                asteroid_poi = p.get('id') or p.get('poi_id')
            if any(k in p_name for k in ('station', 'base', 'outpost')):
                station_poi = p.get('id') or p.get('poi_id')

        # Fallbacks
        if not asteroid_poi and len(pois) > 1:
            asteroid_poi = pois[1].get('id') or pois[1].get('poi_id')
        if not station_poi and len(pois) > 0:
            station_poi = pois[0].get('id') or pois[0].get('poi_id')

        # Step 2: Undock
        if loc.get('docked', False) or loc.get('is_docked', False):
            print('1. Undocking from station...')
            await client.undock()

        # Step 3: Travel to asteroid field
        if asteroid_poi:
            print(f'2. Traveling to asteroid field ({asteroid_poi})...')
            await client.travel(asteroid_poi)

        # Step 4: Mine
        print(f'3. Mining ore ({cycles} cycles)...')
        for i in range(cycles):
            await client.mine()
            await asyncio.sleep(0.5)

        # Step 5: Return to station and dock
        if station_poi:
            print(f'4. Returning to station ({station_poi})...')
            await client.travel(station_poi)
            print('5. Docking at station...')
            await client.dock()
            print('6. Refueling...')
            await client.refuel()

        # Step 6: Sell cargo
        print('7. Liquidating cargo on station exchange...')
        cargo = await client.get_cargo()
        for item in cargo.get('items', []) or []:
            item_id = item.get('id') or item.get('item_id')
            qty = item.get('quantity', 0)
            if item_id and qty > 0:
                await client.sell(item_id, qty)

        elapsed = time.time() - start_time
        summary = {
            'mode': 'single_agent_baseline',
            'pilot': username,
            'elapsed_seconds': elapsed,
            'mining_cycles': cycles,
            'status': 'completed'
        }
        record('baseline.complete', agent=username, data=summary)
        print('\n====================================================')
        print(f'BASELINE COMPLETE in {elapsed:.2f} seconds')
        print('====================================================')
        return summary


def main():
    parser = argparse.ArgumentParser(description='SpaceMolt Single-Agent Baseline')
    parser.add_argument('--cycles', type=int, default=3, help='Mining cycles to execute')
    args = parser.parse_args()
    asyncio.run(run_baseline_cycle(cycles=args.cycles))


if __name__ == '__main__':
    main()
