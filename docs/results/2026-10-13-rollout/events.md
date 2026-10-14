# Soak events: PASS

`studio-lan`: 5 events, each judged over the next 5 minutes. The quiet baseline p95 is 96 ms; an event passes with no errors, every canary right and p95 within 1.5x of it.

Alignment: the soak's times were shifted by -2 s onto the watcher's clock, found from the pods' CPU rising when the soak started and falling when it ended (start +12 s, end -16 s; resolution about 15 s).

| time (UTC) | what | verdict | windows | errors | wrong canaries | worst p95 ms | fewest ready | most terminating | restarts | peak memory MiB | |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-13T15:53:50Z | soak started | **PASS** | 6 | 0 | 0 | 99 | 20 | 0 | 0 | 191.2 |  |
| 2026-10-13T16:41:29Z | rollback to previous revision | **PASS** | 6 | 0 | 0 | 100 | 20 | 20 | 0 | 190.8 |  |
| 2026-10-13T17:18:17Z | roll forward to NEXT | **PASS** | 6 | 0 | 0 | 99 | 20 | 20 | 0 | 163.6 |  |
| 2026-10-13T17:39:22Z | delete one pod | **PASS** | 6 | 0 | 0 | 97 | 20 | 1 | 0 | 163.2 |  |
| 2026-10-13T17:56:04Z | early end due to delayed steps | **NOT JUDGED** | 0 | 0 | 0 |  | 20 | 0 | 0 | 163.3 | no soak window overlaps it (a mark outside the soak, not judged) |
