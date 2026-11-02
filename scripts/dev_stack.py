"""Start the four local processes and stop all children on Ctrl+C."""
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    if len(os.environ.get('SERVICE_TOKEN', '')) < 16:
        raise SystemExit('Set SERVICE_TOKEN to at least 16 characters first')
    env = os.environ | {'PYTHONPATH': str(ROOT / 'src'), 'PYTHONDONTWRITEBYTECODE': '1',
                        'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'}
    children = []
    try:
        for name, port in [('jobs', 8100), ('data', 8101), ('compute', 8102)]:
            children.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', f'math_engine.services.{name}:app',
                                              '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT, env=env))
        children.append(subprocess.Popen([sys.executable, '-m', 'math_engine.worker'], cwd=ROOT, env=env))
        print('Jobs: 8100, Data: 8101, Compute: 8102. Ctrl+C stops the stack.', flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    main()
