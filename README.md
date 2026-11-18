# India Hotel Revenue Radar — public runner

Public execution code for India hotel revenue vacancy monitoring. **No SQLite state, recipient address, OAuth credential or access token belongs in this repository.** The private repository `atharvakul003-cpu/india-hotel-revenue-radar` retains its independent `radar-state` branch. The UK radar is not used.

## Deployment status

The monitor gate `INDIA_RADAR_MONITOR_ENABLED` and delivery gate `INDIA_RADAR_DELIVERY_ENABLED` are intentionally unset. A manual `probe` fetches public careers pages without state or mail. Do not claim scheduled alerts are live until a private state checkout, checkpoint push and real Gmail send have been verified.

Eight of 15 P1 sources have complete hosted probes and quiet baselines in the private state (22 relevant jobs on 18 November 2026). Seven sources remain disabled, including Hyatt because its Taleo API reports 456 India vacancies but exposes only 452 unique requisitions. [Private current state](https://github.com/atharvakul003-cpu/india-hotel-revenue-radar/blob/main/docs/current-state.md).

## Private state and delivery setup

1. Create a fine-grained GitHub token restricted to the **one private** repository `atharvakul003-cpu/india-hotel-revenue-radar`, with repository `Contents: Read and write`. Save it only as this public repository's Actions secret `INDIA_STATE_REPO_TOKEN`. The token grants the public runner access to the private `radar-state` branch; never print or commit it. The private repository's default branch and UK repository are not changed by the runner.
2. Run manual `probe` for a known source to validate public execution. With delivery off, set `INDIA_RADAR_MONITOR_ENABLED=true` and run a manual `monitor` for a small already-baselined source. Confirm its `radar-state` checkpoint, `baseline:false`, `relevant_new:0`, and `queued:0`; then run the full monitor once. Disable the gate on any failed state checkout or checkpoint.
3. Independently add `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` as Actions secrets, and `INDIA_RADAR_SENDER`, `INDIA_RADAR_RECIPIENT` as repository variables. Keep `INDIA_RADAR_DELIVERY_ENABLED` unset until a real new-job alert is sent and duplicate suppression is observed. Do not paste OAuth secrets in issues, commits or workflow logs.
4. Once state and delivery have passed, leave `INDIA_RADAR_MONITOR_ENABLED=true` for the two-hour Asia/Kolkata schedule. The private repository's own scheduled monitor remains gated off to avoid duplicate writers.

Only `workflow_dispatch` and `schedule` execute the monitor workflow; untrusted pull requests do not receive its secrets. `verify.yml` uses no secrets. Standard GitHub-hosted runners for a public repository do not draw from the account's private-repository included Actions compute allowance.

Run local checks with `python -m unittest discover -s tests -v`.
