"""Open the shared service using the same platform controller as the CLI and tray."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def main():
    from vault_rag.service_control import control
    control('open')

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        from vault_rag.platform_support import show_error, state_directory
        show_error(str(error) + '\n日志：' + str(state_directory() / 'logs'))
        raise
