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

The **ganeti-cleaner** is a periodically run script to remove expired
X509 certificates and keys, as well as outdated **ganeti-watcher**
information.

**ganeti-cleaner** automatically removes  all expired certificates and
keys from ``@LOCALSTATEDIR@/run/ganeti/crypto``.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
