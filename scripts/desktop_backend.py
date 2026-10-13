"""Minimal executable bootstrap; multiprocessing must precede argument parsing."""
import multiprocessing

if __name__ == '__main__':
    multiprocessing.freeze_support()
    from vault_rag.desktop_runtime import main
    main()
