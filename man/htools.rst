HTOOLS(1) Ganeti | Version @GANETI_VERSION@
===========================================

NAME
----

htools - Cluster allocation and placement tools for Ganeti

SYNOPSIS
--------

**hbal**
  cluster balancer

**hspace**
  cluster capacity computation

**hail**
  IAllocator plugin

**hscan**
  saves cluster state for later reuse


DESCRIPTION
-----------


``htools`` is a suite of tools designed to help with allocation/movement
of instances and balancing of Ganeti clusters. ``htools`` is also the
generic binary that must be symlinked or hardlinked under each tool's
name in order to perform the different functions. Alternatively, the
environment variable HTOOLS can be used to set the desired role.

Installed as ``hbal``, it computes and optionally executes a suite of
instance moves in order to balance the cluster.

Installed as ``hspace``, it computes how many additional instances can
be fit on a cluster, while maintaining N+1 status. It can run on models
of existing clusters or of simulated clusters.

Installed as ``hail``, it acts as an IAllocator plugin, i.e. it is used
by Ganeti to compute new instance allocations and instance moves.

Installed as ``hscan``, it scans the local or remote cluster state and
saves it to files which can later be reused by the other roles.

COMMON OPTIONS
--------------

Options behave the same in all program modes, but not all program modes
support all options. Some common options are:

-v, --verbose
  Increase the output verbosity. Each usage of this option will
  increase the verbosity (currently more than 2 doesn't make sense)
  from the default of one.

-q, --quiet
  Decrease the output verbosity. Each usage of this option will
  decrease the verbosity (less than zero doesn't make sense) from the
  default of one.

-V, --version
  Just show the program version and exit.

UNITS
~~~~~

Some options accept not simply numerical values, but numerical values
together with a unit. By default, such unit-accepting options use
mebibytes. Using the lower-case letters of *m*, *g* and *t* (or their
longer equivalents of *mib*, *gib*, *tib*, for which case doesn't
matter) explicit binary units can be selected. Units in the SI system
can be selected using the upper-case letters of *M*, *G* and *T* (or
their longer equivalents of *MB*, *GB*, *TB*, for which case doesn't
matter).

More details about the difference between the SI and binary systems can
be read in the *units(7)* man page.

ENVIRONMENT
-----------

The environment variable ``HTOOLS`` can be used instead of
renaming/symlinking the programs; simply set it to the desired role and
then the name of the program is no longer used.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
