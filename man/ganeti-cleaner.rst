ganeti-cleaner(8) Ganeti | Version @GANETI_VERSION@
===================================================

Name
----

ganeti-cleaner - Ganeti job queue cleaner

Synopsis
--------

**ganeti-cleaner**

DESCRIPTION
-----------

The **ganeti-cleaner** is a periodically run script to clean old job
files from the job queue archive and to remove expired X509
certificates and keys.

**ganeti-cleaner** automatically removes all files older than 21 days
from ``@LOCALSTATEDIR@/lib/ganeti/queue/archive`` and all expired
certificates and keys from ``@LOCALSTATEDIR@/run/ganeti/crypto``.
