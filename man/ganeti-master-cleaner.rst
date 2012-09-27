ganeti-master-cleaner(8) Ganeti | Version @GANETI_VERSION@
==========================================================

Name
----

ganeti-master-cleaner - Ganeti job queue cleaner

Synopsis
--------

**ganeti-master-cleaner**

DESCRIPTION
-----------

The **ganeti-master-cleaner** is a periodically run script to clean old
job files from the job queue archive.

**ganeti-master-cleaner** automatically removes all files older than 21
days from ``@LOCALSTATEDIR@/lib/ganeti/queue/archive``.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
