gnt-storage(8) Ganeti | Version @GANETI_VERSION@
================================================

Name
----

gnt-storage - Ganeti storage administration

Synopsis
--------

**gnt-storage** {command} [arguments...]

DESCRIPTION
-----------

The **gnt-storage** is used for managing the available storage inside
the Ganeti cluster. At the moment, it manages only external storage
(ExtStorage).

COMMANDS
--------

DIAGNOSE
~~~~~~~~

| **diagnose**

This command provides detailed information about the state of all
ExtStorage providers available in the Ganeti cluster. The state of each
provider is calculated per nodegroup. This means that a provider may be
valid (meaning usable) for some nodegroups, and invalid (not usable) for
some others. This command will help you see why an installed ExtStorage
provider is not valid for a specific nodegroup. It could be that it is
missing from a node, or is only partially installed. This command will
show the details of all ExtStorage providers and the reasons they are or
aren't valid for every nodegroup in the cluster.

INFO
~~~~

| **info**
| [*provider*]

This command will list detailed information about each ExtStorage
provider found in the cluster, including its nodegroup validity, the
supported parameters (if any) and their documentations, etc.

For each ExtStorage provider only the valid nodegroups will be listed.

If run with no arguments, it will display info for all ExtStorage
providers found in the cluster. If given ExtStorage provider's names as
arguments it will list info only for providers given.

NOTES
-----

In the future **gnt-storage** can be extended to also handle internal
storage (such as lvm, drbd, etc) and also provide diagnostics for them
too.

It can also be extended to handle internal and external storage pools,
if/when this kind of abstraction is implemented inside Ganeti.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
