import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

NB_PATH = r'C:\Users\kysop\Team_Project_Multiculture\multicultural-ai\model\classification\Business_Plan\National_Key_Data\01_multicultural_youth_panel_schoolbridge.ipynb'
SERVICE_KEY = '1f5a539548cda96feb37ea180c6f3e62bf0f831a9da59038bccc7f4e13b08932'

with open(NB_PATH, 'r', encoding='utf-8') as f:
    nb = json.load(f)

print(f'Total cells before: {len(nb["cells"])}')

# Cell 5,6 = second run (clean, no em-dash) - KEEP
# Cell 7,8 = first run (may have em-dash) - REMOVE
# Total: 19 -> 17

if len(nb['cells']) == 19:
    cell7_first = ''.join(nb['cells'][7]['source'])[:30]
    cell8_first = ''.join(nb['cells'][8]['source'])[:30]
    print(f'Removing cell 7: {repr(cell7_first)}')
    print(f'Removing cell 8: {repr(cell8_first)}')
    nb['cells'] = nb['cells'][:7] + nb['cells'][9:]
    print(f'Total cells after: {len(nb["cells"])}')
elif len(nb['cells']) == 17:
    print('Already 17 cells - no fix needed')
else:
    print(f'Unexpected cell count: {len(nb["cells"])} - aborting')
    sys.exit(1)

# Verify SERVICE_KEY
key_found = False
for i, cell in enumerate(nb['cells']):
    src = ''.join(cell['source']) if isinstance(cell['source'], list) else cell['source']
    if SERVICE_KEY in src:
        print(f'SERVICE_KEY OK in cell {i}')
        key_found = True
        break
    elif 'YOUR_SERVICE_KEY_HERE' in src:
        new_src = src.replace('YOUR_SERVICE_KEY_HERE', SERVICE_KEY)
        cell['source'] = new_src.splitlines(keepends=True)
        print(f'SERVICE_KEY replaced in cell {i}')
        key_found = True
        break

if not key_found:
    print('WARNING: SERVICE_KEY not found!')

# Final structure
print('\nFinal cell structure:')
for i, cell in enumerate(nb['cells']):
    src = ''.join(cell['source']) if isinstance(cell['source'], list) else cell['source']
    first = src.split('\n')[0][:55]
    print(f'  Cell {i:2d} [{cell["cell_type"]:8s}]: {repr(first)}')

with open(NB_PATH, 'w', encoding='utf-8') as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)

print('\nDONE')
