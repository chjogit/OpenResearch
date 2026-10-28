import sys
from pathlib import Path

# members/SH → sh_agents·examples 패키지, 저장소 루트 → 공용 agent 패키지
SH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SH))
if str(SH.parents[1]) not in sys.path:
    sys.path.append(str(SH.parents[1]))
