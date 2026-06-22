"""Background worker stub."""

import time


def process_job(job_id: str) -> dict:
    time.sleep(0)  # placeholder
    return {"job_id": job_id, "status": "done"}


if __name__ == "__main__":
    while True:
        time.sleep(5)
