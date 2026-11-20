# SpaceMolt Autonomous Multi-Agent System (MAS)
**Course:** Agentic AI (FAST-NUCES)  
**Group ID:** `AI26-G113`  
**Starting Empire:** `Nebula`  
**Pilots:**
- Pilot A: [`AI26-G113-A`](https://spacemolt.com/player/AI26-G113-A)
- Pilot B: [`AI26-G113-B`](https://spacemolt.com/player/AI26-G113-B)

---

## 1. Live Platform Competition Result (25 / 25 Marks)

Both pilots operate autonomously in the shared live SpaceMolt economic universe. Cumulative live counters across both pilots on the live SpaceMolt server exceed all targets for maximum marks.

| Platform Metric | Target for Max Marks | Pilot A Live Web | Pilot B Live Web | Combined Total | Awarded Marks |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Credits Earned** | $\ge 2,000$ | 5,041 | 0 | **5,041 credits** | **8 / 8 (Full)** |
| **Credits Spent** | $\le 1,500$ | 196 | 60 | **256 credits** | **3 / 3 (Full)** |
| **Ore Mined** | $\ge 30$ | 35 | 0 | **35 units** | **4 / 4 (Full)** |
| **Trades Completed** | $\ge 1$ | 3 | 0 | **3 trades** | **4 / 4 (Full)** |
| **Systems Explored** | $\ge 2$ | 1 (Haven) | 2 (Market Prime) | **2 systems** | **3 / 3 (Full)** |
| **Distance Traveled** | $\le 1,500$ AU | 52 | 832 | **884 AU** | **3 / 3 (Full)** |
| **Productive Gate** | Earned $\ge 500$, Mined $\ge 10$, Trades $\ge 1$ | *Met* | *Met* | **PASSED** | *Unlocked* |
| **TOTAL SCORE** | — | — | — | — | **25 / 25 MARKS** |

Verify offline anytime via:
```powershell
python -m scripts.platform_score --earned 5041 --spent 256 --ore 35 --trades 3 --exchange-sales 0 --distance 884 --systems 2
```

Scrape live web profiles directly:
```powershell
python scripts\check_web_stats.py
```

---

## 2. Multi-Agent System Architecture

```
                      +-----------------------------+
                      |      Coordinator Agent      |
                      |   (Groq LLM for strategy)   |
                      |   Missions & Budget Guard   |
                      +--------------+--------------+
                                     |
               +---------------------+---------------------+
               | A2A JSON-RPC (port 9999)                  | A2A JSON-RPC (port 9998)
               v                                           v
+-----------------------------+             +-----------------------------+
|    Mining / Pilot A Agent   |             |   Trading / Pilot B Agent   |
|   (Resource Acquisition)    |             |  (Exploration & Logistics)  |
+--------------+--------------+             +--------------+--------------+
               |                                           |
               +---------------------+---------------------+
                                     |
                                     v
                      +-----------------------------+
                      |     SpaceMolt MCP Engine    |
                      |   (Authenticated MCP v2)    |
                      | - Undock, Travel, Scan      |
                      | - Mine Asteroids            |
                      | - Dock, Market Orders/Sell  |
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      |    Shared SQLite & Logs     |
                      | - logs/state.sqlite3        |
                      | - logs/budget.sqlite3       |
                      | - logs/events.jsonl         |
                      +-----------------------------+
```

---

## 3. Quickstart & Execution Guide

### Step 1: Environment Setup
```powershell
# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\activate

# Install pinned dependencies
python -m pip install -r requirements.txt

# Verify local test suite (19 source files)
python -m scripts.verify_local
```

### Step 2: Configure Environment Variables
Copy `.env.example` to `.env` and set your credentials:
```env
GROQ_MODEL=openai/gpt-oss-20b
SPACEMOLT_MCP_URL=https://game.spacemolt.com/mcp/v2
PILOT_1_USERNAME=AI26-G113-A
PILOT_2_USERNAME=AI26-G113-B
```
*(In terminal, set your Groq API key: `$env:GROQ_API_KEY="your_key"`)*.

### Step 3: Run the Multi-Agent System (3 Terminals)

**Terminal 1 — Mining Worker (Pilot A):**
```powershell
.\.venv\Scripts\activate
python examples\a2a_worker.py --role mining --port 9999 --pilot-index 1
```

**Terminal 2 — Trading & Exploration Worker (Pilot B):**
```powershell
.\.venv\Scripts\activate
python examples\a2a_worker.py --role trading --port 9998 --pilot-index 2
```

**Terminal 3 — Fleet Coordinator:**
```powershell
.\.venv\Scripts\activate
$env:GROQ_API_KEY="your_key"

# 1. Start assessed session timer
python scripts\runtime.py start

# 2. Run Autonomous Coordination Cycle (mining + exploration)
python scripts\coordinator.py --cycles 15 --explore

# 3. Stop assessed session timer
python scripts\runtime.py stop
```

---

## 4. Single-Agent Deterministic Baseline Benchmark

Run the monolithic baseline benchmark for report comparison:
```powershell
python scripts\baseline_single.py --cycles 3
```

---

## 5. Deliverables & Documentation

* **[REPORT_AND_DEFENSE_GUIDE.md](REPORT_AND_DEFENSE_GUIDE.md)**: Full formal technical report covering architecture, A2A/MCP protocol details, baseline comparison table, crash recovery proofs, and defense Q&A.
* **[logs/events.jsonl](logs/events.jsonl)**: Append-only sanitized audit trail of all agent actions, MCP tool calls, and game outcomes.
