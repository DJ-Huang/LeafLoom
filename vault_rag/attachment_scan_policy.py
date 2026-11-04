"""Directory discovery preferences do not grant or revoke byte access."""
SCAN_INTERVAL = 30 * 60
STARTUP_GRACE = 60
MAX_DIRECTORY_INTERVAL = 7 * 24 * 60 * 60
MAX_METADATA_INTERVAL = 6 * 60 * 60


def idle_interval(previous=SCAN_INTERVAL, *, changed=False, maximum=MAX_METADATA_INTERVAL):
    return SCAN_INTERVAL if changed else min(maximum, max(SCAN_INTERVAL, previous) * 2)


def retry_interval(failures):
    return min(60 * 60, 60 * 2 ** min(max(0, failures - 1), 6))
