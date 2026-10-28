import json
from pathlib import Path

import pytest

from agent.neon_agents import to_report
from tests.test_neon_agents import bundle

NOTEBOOKS = {'industry_business_model': '01_산업사업모델_Agent_Neon.ipynb',
             'technical_analysis': '02_기술적분석_Agent_Neon.ipynb'}


def code(name):
    nb = json.loads((Path(__file__).parents[1] / 'notebooks' / name).read_text(encoding='utf-8'))
    return [''.join(c['source']) for c in nb['cells'] if c['cell_type'] == 'code']


@pytest.mark.parametrize('domain, name', NOTEBOOKS.items())
def test_notebook_structure_and_safe_defaults(domain, name):
    cells = code(name)
    assert len(cells) == 9
    src = '\n'.join(cells)
    assert f"DOMAIN = '{domain}'" in src
    assert "INPUT_MODE = 'wait'" in src and 'SAVE_RESULTS = False' in src and 'RUN_SOLAR = False' in src
    assert 'USE_NEON' not in src
    assert 'save_results(' in cells[-1] and 'write_text' not in cells[-1]
    assert 'trading_dates=TRADING_DATES' in cells[4] and 'trading_dates=TRADING_DATES' in cells[6]


def test_notebooks_share_snapshot_settings():
    a, b = ('\n'.join(code(n)) for n in NOTEBOOKS.values())
    for line in ["START = (TODAY - timedelta(days=800)).isoformat()",
                 "SNAPSHOT_DIR = ROOT / 'private_outputs' / 'snapshots'"]:
        assert line in a and line in b
    assert code(NOTEBOOKS['industry_business_model'])[3] == code(NOTEBOOKS['technical_analysis'])[3]


def test_to_report_rejects_unknown_data_mode():
    with pytest.raises(ValueError):
        to_report(bundle(), {}, data_mode='mock')
    assert to_report(bundle(), {}, data_mode='synthetic')['dataMode'] == 'synthetic'
