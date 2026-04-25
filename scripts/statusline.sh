#!/bin/bash
# APE statusline — multiline with context bar, cost, git, and APE stats
# Reads Claude Code JSON from stdin; calls adaptive-cli for APE counts
cat | python3 -c "
import sys, json, subprocess, os
from pathlib import Path

try:
    data = json.load(sys.stdin)
except Exception:
    data = {}

CYAN   = '\033[36m'
GREEN  = '\033[32m'
YELLOW = '\033[33m'
RED    = '\033[91m'
RESET  = '\033[0m'

model   = (data.get('model') or {}).get('display_name', '?')
ws      = data.get('workspace') or {}
cwd     = ws.get('current_dir') or data.get('cwd', '')
dirname = os.path.basename(cwd) if cwd else '?'
ctx     = data.get('context_window') or {}
pct     = int(ctx.get('used_percentage', 0) or 0)
MODEL_CTX = {'Sonnet': 200000, 'Opus': 200000, 'Haiku': 200000}
max_ctx = next((v for k, v in MODEL_CTX.items() if k.lower() in model.lower()), None)
cost_d  = data.get('cost') or {}
cost    = cost_d.get('total_cost_usd', 0) or 0
dur_ms  = cost_d.get('total_duration_ms', 0) or 0
rate    = data.get('rate_limits') or {}
five_h  = (rate.get('five_hour') or {}).get('used_percentage')
week    = (rate.get('seven_day') or {}).get('used_percentage')

# Git branch (cached per session to avoid lag)
branch = ''
session_id = data.get('session_id', 'default')
cache = Path(f'/tmp/statusline-git-{session_id}')
import time
try:
    if not cache.exists() or time.time() - cache.stat().st_mtime > 5:
        b = subprocess.check_output(['git','branch','--show-current'], stderr=subprocess.DEVNULL, text=True).strip()
        cache.write_text(b)
    branch = cache.read_text().strip()
except Exception:
    pass

# APE stats + buddy icon
ape_seg = ''
try:
    stats = subprocess.check_output(['adaptive-cli','stats','--oneline'], stderr=subprocess.DEVNULL, text=True).strip()
    if stats:
        config_path = Path.home() / '.adaptive-cli' / 'config.json'
        buddy = False
        if config_path.exists():
            try:
                buddy = json.loads(config_path.read_text()).get('buddy_enabled', False)
            except Exception:
                pass
        icon = '🦧' if buddy else 'APE:'
        ape_seg = f'{icon} {stats}'
except Exception:
    pass

# Line 1: model · dir · branch · APE
parts1 = [f'{CYAN}[{model}]{RESET}', f'📁 {dirname}']
if branch:
    parts1.append(f'🌿 {branch}')
if ape_seg:
    parts1.append(ape_seg)
print(' · '.join(parts1))

# Line 2: context bar · cost · duration · rate limits
bar_color = RED if pct >= 90 else YELLOW if pct >= 70 else GREEN
bar = '█' * (pct // 10) + '░' * (10 - pct // 10)
mins = dur_ms // 60000
secs = (dur_ms % 60000) // 1000
if max_ctx:
    used_k = round(pct * max_ctx / 100000)
    max_k  = max_ctx // 1000
    ctx_seg = f'{bar_color}{bar}{RESET} {pct}% ({used_k}K / {max_k}K)'
else:
    ctx_seg = f'{bar_color}{bar}{RESET} {pct}%'
parts2 = [ctx_seg, f'{YELLOW}\${cost:.2f}{RESET}', f'⏱️  {mins}m {secs}s']
if five_h is not None:
    parts2.append(f'5h:{five_h:.0f}%')
if week is not None:
    parts2.append(f'7d:{week:.0f}%')
print(' · '.join(parts2))
" 2>/dev/null || echo "🦧 APE"
