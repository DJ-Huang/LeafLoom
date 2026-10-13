"""Validate CI secrets without printing them; materialize the Apple key privately."""
import os
from pathlib import Path
import sys

required = ['CSC_LINK', 'CSC_KEY_PASSWORD']
if sys.platform == 'darwin':
    required += ['APPLE_API_KEY_CONTENT', 'APPLE_API_KEY_ID', 'APPLE_API_ISSUER']
missing = [name for name in required if not os.environ.get(name)]
if missing:
    raise SystemExit('正式签名缺少凭据：' + ', '.join(missing))
if sys.platform == 'darwin':
    path = Path(os.environ['RUNNER_TEMP']) / 'desktop-apple-key.p8'
    path.write_text(os.environ['APPLE_API_KEY_CONTENT'], encoding='utf-8')
    path.chmod(0o600)
    with Path(os.environ['GITHUB_ENV']).open('a', encoding='utf-8') as output:
        output.write('APPLE_API_KEY=' + str(path) + '\n')
