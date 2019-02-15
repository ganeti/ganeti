ganeti-cleaner(8) Ganeti | Version @GANETI_VERSION@
===================================================

Name
----

ganeti-cleaner - Ganeti job queue cleaner

Synopsis
--------

**ganeti-cleaner** node|master

DESCRIPTION
-----------

The **ganeti-cleaner** is a periodically run script to remove old
files. It can clean either node-specific or master-specific files.

When called with ``node`` as argument, it will cleanup expired X509
certificates and keys from ``@LOCALSTATEDIR@/run/ganeti/crypto``, as
well as outdated **ganeti-watcher** information.

When called with ``master`` as argument, it will instead automatically
remove all files older than 21 days from
``@LOCALSTATEDIR@/lib/ganeti/queue/archive``.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
