HROLLER(1) Ganeti | Version @GANETI_VERSION@
============================================

NAME
----

hroller \- Cluster rolling maintenance scheduler for Ganeti

SYNOPSIS
--------

**hroller** {backend options...} [algorithm options...] [reporting options...]

**hroller** \--version


Backend options:

{ **-m** *cluster* | **-L[** *path* **]** | **-t** *data-file* |
**-I** *path* }

Algorithm options:

**[ -O *name...* ]**

Reporting options:

**[ -v... | -q ]**
**[ -S *file* ]**

DESCRIPTION
-----------

hroller is a cluster maintenance reboot scheduler. It can calculate
which set of nodes can be rebooted at the same time while avoiding
having both primary and secondary nodes being rebooted at the same time.

OPTIONS
-------

Currently only standard htools options are supported. For a description of them
check **htools(7)** and **hbal(1)**.

BUGS
----

The program does nothing.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
