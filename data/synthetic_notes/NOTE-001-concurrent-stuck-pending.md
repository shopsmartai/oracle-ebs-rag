---
id: NOTE-001
category: concurrent-manager
ebs_version: R12.2.11
db_version: 19c
created: 2026-03-14
tags: [pending-normal, opp, output-post-processor, fnd-cp]
severity: medium
---

# Concurrent Request stuck in Pending - Normal phase

## Symptom
User submits a standard concurrent program (e.g., "Active Users" or any
XML Publisher report) and the request stays in **Phase = PENDING,
Status = Normal** for 30+ minutes. Other requests in the same
Standard Manager queue process normally. The "View Output" button is
unavailable.

## Diagnosis steps
1. Check the request status:

       SELECT request_id, phase_code, status_code, completion_text,
              oracle_process_id
         FROM fnd_concurrent_requests
        WHERE request_id = &req_id;

2. Verify the parent Concurrent Manager is up:

       SELECT concurrent_queue_name, running_processes, max_processes
         FROM fnd_concurrent_queues_vl
        WHERE concurrent_queue_name = 'STANDARD';

3. Check the Output Post Processor service:

       SELECT component_name, component_status
         FROM fnd_svc_components
        WHERE component_name LIKE '%OUTPUT%';

4. Tail `$APPLCSF/log/FNDOPP*.log` for OPP errors.

## Root cause
The Output Post Processor (OPP) service crashed silently after a
memory exhaustion event when processing a large XML Publisher report.
Pending requests that need post-processing wait for an OPP worker
that no longer exists. The Standard Manager itself is healthy, which
is why other requests succeed — only requests with output-processing
steps are affected.

## Resolution
1. From CM control (`adcmctl.sh status`), confirm OPP is not running.
2. Restart the OPP service from OAM:
   System Administrator → Oracle Applications Manager →
   Workflow Manager → restart "Output Post Processor".
3. Resubmit the stuck request (do **not** force-delete from
   `fnd_concurrent_requests` — it leaves orphaned XML Publisher temp
   files).
4. Bump OPP JVM heap if memory pressure is recurring:
   OAFM → OPP → properties → `-Xmx1024m` minimum for large XMLP jobs.

## Verified on
EBS R12.2.11 on Oracle 19c, April 2026.

## References
- docs.oracle.com — "Oracle E-Business Suite Concurrent Processing"
