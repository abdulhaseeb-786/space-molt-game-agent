"""SpaceMolt MCP v2 Game Engine Client.
Provides authenticated gameplay actions via the official Model Context Protocol (MCP):
- Session management & automatic token/session renewal
- Navigation: undock, travel to POI, jump systems, dock
- Resource Acquisition: asteroid survey, mining loops
- Market/Trading: view market, sell cargo on station exchange
- Ship Management: status query, refuel, repair
- Auditable logging to logs/events.jsonl (with credentials redacted)
"""
from __future__ import annotations
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import keyring
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from scripts.evidence import record

DEFAULT_MCP_URL = 'https://game.spacemolt.com/mcp/v2'
VAULT = 'spacemolt'


def load_env_file() -> Dict[str, str]:
    """Load key-value pairs from .env if present."""
    env = {}
    env_path = ROOT / '.env'
    if env_path.exists():
        for line in env_path.read_text(encoding='utf-8', errors='ignore').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def resolve_pilot_credentials(username: Optional[str] = None, pilot_num: int = 1) -> tuple[str, str]:
    """Retrieve username and password from keyring, .env, or environment variables."""
    env = load_env_file()
    if not username:
        username = (
            env.get(f'PILOT_{pilot_num}_USERNAME')
            or os.environ.get(f'PILOT_{pilot_num}_USERNAME')
        )
    if not username:
        raise ValueError(f'Pilot username not found for pilot {pilot_num}. Set in .env or pass explicitly.')

    # Try keyring first with known course and standard service names
    password = None
    for service in ('spacemolt-course-test', 'spacemolt', 'SpaceMolt'):
        password = keyring.get_password(service, username)
        if password:
            break

    if not password:
        # Check .env or OS environment
        password = (
            env.get(f'PILOT_{pilot_num}_PASSWORD')
            or os.environ.get(f'PILOT_{pilot_num}_PASSWORD')
            or env.get(f'{username}_PASSWORD')
            or os.environ.get(f'{username}_PASSWORD')
            or env.get('PILOT_PASSWORD')
            or os.environ.get('PILOT_PASSWORD')
        )
    if not password:
        raise ValueError(
            f'Password for pilot {username} not found in Windows Credential Manager or .env. '
            f'Run "python examples/pilot_setup.py status --username {username}" or add PILOT_{pilot_num}_PASSWORD to .env.'
        )
    return username, password


class SpaceMoltMCPClient:
    """Async MCP v2 client for an authenticated SpaceMolt pilot."""

    def __init__(self, username: str, password: str, mcp_url: str = DEFAULT_MCP_URL):
        self.username = username
        self.password = password
        self.mcp_url = mcp_url
        self.session_id: Optional[str] = None
        self._session: Optional[ClientSession] = None
        self._http_ctx = None

    async def connect(self):
        """Establish streamable HTTP MCP session and perform login."""
        self._http_ctx = streamable_http_client(self.mcp_url)
        read, write = await self._http_ctx.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()
        await self.login()
        return self

    async def close(self):
        """Safely close MCP session."""
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                pass
            self._session = None
        if self._http_ctx:
            try:
                await self._http_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._http_ctx = None

    async def __aenter__(self):
        return await self.connect()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def _parse_response_content(self, res) -> Dict[str, Any]:
        """Parse MCP CallToolResult content block into python dict or structured text."""
        raw_texts = []
        for c in res.content:
            text = getattr(c, 'text', '')
            raw_texts.append(text)

        combined = '\n'.join(raw_texts).strip()

        # Check for JSON payload inside response
        try:
            return json.loads(combined)
        except Exception:
            pass

        # Try to find json block { ... } inside text
        m = re.search(r'(\{[\s\S]*\})', combined)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass

        return {'raw_text': combined, 'is_error': getattr(res, 'is_error', False)}

    async def raw_call(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Invoke an MCP tool with schema arguments."""
        if not self._session:
            raise RuntimeError('MCP client is not connected')

        res = await self._session.call_tool(tool_name, args)
        parsed = self._parse_response_content(res)
        if getattr(res, 'is_error', False) or (isinstance(parsed, dict) and parsed.get('error')):
            err_msg = parsed.get('error') or parsed.get('raw_text') or 'MCP tool call error'
            # Check for session expiration
            if 'session_invalid' in str(err_msg) or 'expired' in str(err_msg):
                record('mcp.session_expired', agent=self.username, data={'tool': tool_name})
                await self.login()
                if 'session_id' in args:
                    args['session_id'] = self.session_id
                res = await self._session.call_tool(tool_name, args)
                parsed = self._parse_response_content(res)
            else:
                record('mcp.error', agent=self.username, data={'tool': tool_name, 'error': str(err_msg)[:200]})
        return parsed

    async def login(self) -> str:
        """Authenticate pilot with spacemolt_auth tool and cache session_id."""
        record('mcp.auth_request', agent=self.username, data={'username': self.username})
        res = await self._session.call_tool(
            'spacemolt_auth',
            {'action': 'login', 'username': self.username, 'password': self.password}
        )
        parsed = self._parse_response_content(res)
        raw = parsed.get('raw_text', '')

        # Session ID can be parsed from json or regex from text
        sid = parsed.get('session_id')
        if not sid:
            # Pattern: session_id = '...' or Session ID: ...
            m = re.search(r'(?:session_id|Session ID)[:\s=]+([a-zA-Z0-9_-]{10,})', raw)
            if m:
                sid = m.group(1)

        if not sid:
            raise RuntimeError(f'Failed to obtain session_id for {self.username}: {raw[:300]}')

        self.session_id = sid
        record('mcp.auth_success', agent=self.username, data={'username': self.username})
        return self.session_id

    async def call_game(self, action: str, **kwargs) -> Dict[str, Any]:
        """Call core spacemolt tool with current session_id."""
        payload = {'action': action, 'session_id': self.session_id, **kwargs}
        record('mcp.game_action', agent=self.username, data={'action': action, 'kwargs': kwargs})
        result = await self.raw_call('spacemolt', payload)
        record('mcp.game_result', agent=self.username, data={'action': action, 'result': str(result)[:300]})
        return result

    async def call_market(self, action: str, **kwargs) -> Dict[str, Any]:
        """Call spacemolt_market tool with current session_id."""
        payload = {'action': action, 'session_id': self.session_id, **kwargs}
        record('mcp.market_action', agent=self.username, data={'action': action, 'kwargs': kwargs})
        result = await self.raw_call('spacemolt_market', payload)
        record('mcp.market_result', agent=self.username, data={'action': action, 'result': str(result)[:300]})
        return result

    # --- High-level gameplay queries and commands ---

    async def get_status(self) -> Dict[str, Any]:
        """Retrieve full pilot status: player stats, ship, cargo, location, fuel."""
        return await self.call_game('get_status')

    async def get_location(self) -> Dict[str, Any]:
        """Retrieve location summary (system, poi, docked status)."""
        res = await self.call_game('get_location')
        raw = res.get('raw_text', '')
        res['docked'] = 'docked' in raw.lower()
        return res

    async def get_system(self) -> Dict[str, Any]:
        """Retrieve current system chart: POIs (stations, belts), connections."""
        res = await self.call_game('get_system')
        raw = res.get('raw_text', '')
        pois = []
        in_pois = False
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith('POIs ('):
                in_pois = True
                continue
            if line.startswith('Connections ('):
                in_pois = False
                continue
            if in_pois and '\t' in line:
                parts = line.split('\t')
                if parts[0] != 'id':
                    pois.append({
                        'id': parts[0],
                        'name': parts[1] if len(parts) > 1 else '',
                        'type': parts[2] if len(parts) > 2 else '',
                        'class': parts[3] if len(parts) > 3 else ''
                    })
        res['pois'] = pois
        return res

    async def get_cargo(self) -> Dict[str, Any]:
        """Retrieve current cargo inventory."""
        res = await self.call_game('get_cargo')
        raw = res.get('raw_text', '')
        items = []
        for line in raw.splitlines():
            line = line.strip()
            if '\t' in line and not line.startswith('id\t'):
                parts = line.split('\t')
                try:
                    qty = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
                except Exception:
                    qty = 1
                items.append({'id': parts[0], 'quantity': qty})
        res['items'] = items
        return res

    async def undock(self) -> Dict[str, Any]:
        """Leave current station into space."""
        res = await self.call_game('undock')
        if 'not_docked' in str(res.get('raw_text', '')).lower():
            return {'status': 'already_undocked'}
        return res

    async def dock(self) -> Dict[str, Any]:
        """Dock at current station POI."""
        return await self.call_game('dock')

    async def travel(self, poi_id: str) -> Dict[str, Any]:
        """Move to a POI in the current system (costs fuel)."""
        return await self.call_game('travel', id=poi_id)

    async def jump(self, target_system: str) -> Dict[str, Any]:
        """Jump to an adjacent system."""
        return await self.call_game('jump', id=target_system)

    async def mine(self) -> Dict[str, Any]:
        """Extract resources at current asteroid/deposit POI."""
        return await self.call_game('mine')

    async def refuel(self) -> Dict[str, Any]:
        """Refuel ship when docked."""
        return await self.call_game('refuel')

    async def repair(self) -> Dict[str, Any]:
        """Repair ship hull when docked."""
        return await self.call_game('repair')

    async def view_market(self, category: Optional[str] = None) -> Dict[str, Any]:
        """View order books while docked at a station."""
        args = {}
        if category:
            args['category'] = category
        return await self.call_market('view_market', **args)

    async def create_sell_order(self, item_id: str, quantity: int, price_each: int) -> Dict[str, Any]:
        """Post a sell order on station exchange."""
        return await self.call_market(
            'create_sell_order',
            item_id=item_id,
            quantity=quantity,
            price_each=price_each
        )

    async def sell(self, item_id: str, quantity: int) -> Dict[str, Any]:
        """Directly sell items to station exchange buy orders."""
        return await self.call_game('sell', id=item_id, quantity=quantity)
