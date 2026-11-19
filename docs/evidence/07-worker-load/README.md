# Worker load evidence — pending isolated run

No load run has been performed: Docker Engine was not available. Do not treat
the existing HTTP load benchmark as a worker measurement. Follow the procedure
in `load-tests/README.md` to collect three target rates (10/50/100 errors/s),
accepted throughput and failures, cycle CSV with window timestamps, Locust
output, Docker stats, and the CPU/RAM and warm-up configuration. Record whether
the full 30-window baseline was populated, whether the target rate was reached,
and whether worker logs establish any skipped window. Preserve raw results and
make no claim about the 30-second optimization trigger until measured.
