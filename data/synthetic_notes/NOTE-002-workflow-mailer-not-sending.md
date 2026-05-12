---
id: NOTE-002
category: workflow
ebs_version: R12.2.11
db_version: 19c
created: 2026-02-08
tags: [workflow-mailer, wf-notification, smtp, fnd-svc-component]
severity: high
---

# Workflow Mailer is running but sends zero notifications

## Symptom
Workflow Notification Mailer shows component_status = RUNNING in OAM,
but no emails are being delivered to users. `wf_notifications` table
shows `mail_status = MAIL` for hundreds of rows, none transitioning
to SENT. No errors in the mailer log at INFO level.

## Diagnosis steps
1. Verify pending notification queue depth:

       SELECT mail_status, COUNT(*)
         FROM wf_notifications
        WHERE status = 'OPEN' AND mail_status IS NOT NULL
        GROUP BY mail_status;

2. Check mailer thread state:

       SELECT component_name, component_status, startup_mode
         FROM fnd_svc_components
        WHERE component_name LIKE '%MAILER%';

3. Bump mailer log level to STATEMENT temporarily and tail
   `$APPLCSF/log/FNDCPGSC*.log`.

4. Test SMTP reachability from the application tier:

       telnet smtp-host 25

## Root cause
The corporate SMTP gateway rotated its TLS certificate and the new
intermediate CA was not in the Java truststore used by the mailer.
The mailer connection attempts fail at TLS handshake, but the failure
is logged only at STATEMENT level — at INFO it appears as "thread
idle, no work available", which masks the issue.

## Resolution
1. Identify the new SMTP server certificate chain:

       openssl s_client -showcerts -starttls smtp \
         -connect smtp.example.local:25 < /dev/null

2. Import the new intermediate CA into the JVM truststore used by
   the mailer (usually `$AFJVA_TOP/jre/lib/security/cacerts`):

       keytool -importcert -alias corp-smtp-intermediate-2026 \
               -file intermediate.pem \
               -keystore $JAVA_HOME/jre/lib/security/cacerts

3. Bounce the Workflow Mailer service from OAM.
4. Verify a fresh notification flips to SENT:

       SELECT notification_id, mail_status, end_date
         FROM wf_notifications
        WHERE recipient_role = 'YOUR_TEST_USER'
        ORDER BY begin_date DESC FETCH FIRST 5 ROWS ONLY;

## Verified on
EBS R12.2.11 on Oracle 19c, February 2026.

## References
- docs.oracle.com — "Oracle Workflow Administrator's Guide"
