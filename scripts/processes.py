import os
import subprocess


def stop_process(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        # The Windows virtualenv launcher has a child Python process.
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    else:
        process.terminate()
    process.wait(timeout=10)
