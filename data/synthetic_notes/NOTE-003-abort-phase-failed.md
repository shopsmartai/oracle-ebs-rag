---
id: NOTE-003
category: patching
ebs_version: R12.2.11
db_version: 19c
created: 2026-MM-DD
tags: [abort phase, abort, EBS]
severity: high
---

# Abort Phase faileed

## Symptom

ERROR: InDbCtxFile.uploadCtx() : Exception : Error executng BEGIN fnd_gsm_util.upload_context_file(:1,:2,:3,:4,:5); END;: 1; Serial number in context file contains lower value than that of database copy.
 
Cause: Context file editing through Oracle Applications Manager did not complete file system syncronization. Please correct the errors that caused during editing and then run this program again. (FILE=/apps/applmgr/r12/fs1/inst/apps/ebs9d_ebsappd01/appl/admin/ebs9d_ebsappd01.xml)
Exception : Error executng BEGIN fnd_gsm_util.upload_context_file(:1,:2,:3,:4,:5); END;: 1; Serial number in context file contains lower value than that of database copy.
 
Cause: Context file editing through Oracle Applications Manager did not complete file system syncronization. Please correct the errors that caused during editing and then run this program again. (FILE=/apps/applmgr/r12/fs1/inst/apps/ebs9d_ebsappd01/appl/admin/ebs9d_ebsappd01.xml)

## Diagnosis steps

SELECT extractValue(XMLType(TEXT),'//oa_context_serial') SERIAL_NUMBER, extractValue(XMLType(TEXT),'//file_edition_type') FILE_EDITION from fnd_oam_context_files where name not in ('TEMPLATE','METADATA') and (status !='H') and (CTX_TYPE !='D') ;

## Root cause

abort fails with error "Serial number in context file contains lower value than that of database copy.

## Resolution

Run Context FILE:
 
[applmgr@ebsappd01 ~]$ grep s_contextserial $CONTEXT_FILE
        <oa_context_serial oa_var="s_contextserial">1427</oa_context_serial>
 
Patch Context File:
 
[applmgr@ebsappd01 ~]$ grep s_contextserial $CONTEXT_FILE
   <oa_context_serial oa_var="s_contextserial">1422</oa_context_serial>
 
 
In the database, we see the following value for s_contextserial for the PATCH filesystem:
 
SELECT extractValue(XMLType(TEXT),'//oa_context_serial') SERIAL_NUMBER, extractValue(XMLType(TEXT),'//file_edition_type') FILE_EDITION from fnd_oam_context_files where name not in ('TEMPLATE','METADATA') and (status !='H') and (CTX_TYPE !='D') ;
 
 
[applmgr@ebsappd01 ~]$ . /apps/applmgr/r12/EBSapps.env patch
[applmgr@ebsappd01 admin]$ cp $CONTEXT_FILE $CONTEXT_FILE.bak
 
We have to update the serial number 1428 context, including all backup context files.
 
[applmgr@ebsappd01 admin]$ grep s_contextserial $CONTEXT_FILE
   <oa_context_serial oa_var="s_contextserial">1428</oa_context_serial>
[applmgr@ebsappd01 admin]$ grep s_contextserial ebs9d_ebsappd01.xml.bak
   <oa_context_serial oa_var="s_contextserial">1428</oa_context_serial>
 
[applmgr@ebsappd01 admin]$ grep s_contextserial ebs9d_ebsappd01.xml_08MAY2024
   <oa_context_serial oa_var="s_contextserial">1428</oa_context_serial>
[applmgr@ebsappd01 admin]$ grep s_contextserial ebs9d_ebsappd01_backup.xml
   <oa_context_serial oa_var="s_contextserial">1428</oa_context_serial>
[applmgr@ebsappd01 admin]$


## References
adop phase=abort fails with error "Serial number in context file contains lower value than that of database copy." (Doc ID 1916658.1)
