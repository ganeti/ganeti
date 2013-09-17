HINFO(1) Ganeti | Version @GANETI_VERSION@
==========================================

NAME
----

hinfo \- Cluster information printer

SYNOPSIS
--------

**hinfo** {backend options...} [algorithm options...] [reporting options...]

**hinfo** \--version


Backend options:

{ **-m** *cluster* | **-L[** *path* **]** | **-t** *data-file* |
**-I** *path* }

Algorithm options:

**[ -O *name...* ]**

Reporting options:

**[ -p[ *fields* ] ]**
**[ \--print-instances ]**
**[ -v... | -q ]**


DESCRIPTION
-----------

hinfo is the cluster information printer. It prints information about
the current cluster state and its residing nodes/instances. It's
similar to the output of **hbal** except that it doesn't take any action
is just for information purpose. This information might be useful for
debugging a certain cluster state.

OPTIONS
-------

For a detailed description about the options listed above have a look at
**htools**\(1) and **hbal**\(1).

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
