Virtual cluster support
=======================

Documents Ganeti version 2.16

.. contents::

Introduction
------------

This is a description of Ganeti's support for virtual clusters
introduced in version 2.7. The original design is described
in a separate :doc:`design document <design-virtual-clusters>`.

A virtual cluster consists of multiple virtual nodes (instances of
Ganeti daemons) running on the same physical machine within one
operating system. This way multiple (virtual) nodes can be simulated
using a single machine. Virtual clusters can be run as a user without
root privileges (see :ref:`limitations <limitations>`).

While not implemented in the helper setup script at the time of this
writing, virtual clusters can also be split over multiple physical
machines, allowing for even more virtual nodes.


.. _limitations:

Limitations
-----------

Due to historical and practical design decisions virtual clusters
have several limitations.

- "fake" hypervisor only
- Instances must be diskless or file-backed
- Node information is the same over multiple virtual nodes (e.g. free
  memory)
- If running as a user without root privileges, certain operations are
  not available; some operations are not useful even when running as
  root (e.g. powercycle)
- OS definitions must be prepared for this setup
- Setup is partially manual, especially when not running as root


Basics
------

Ganeti programs act as running on a virtual node if the environment
variables ``GANETI_ROOTDIR`` and ``GANETI_HOSTNAME`` are set. The former
must be an absolute path to a directory with the last component being
equal to the value of ``GANETI_HOSTNAME``, which contains the name of
the virtual node. The reason for this requirement is that one virtual
node must be able to compute an absolute path on another node for
copying files via SSH.

The whole content of ``GANETI_ROOTDIR`` is the node directory, its
parent directory (without hostname) is the cluster directory.

Example for environment variables::

  GANETI_ROOTDIR=/tmp/vcluster/node1.example.com
  GANETI_HOSTNAME=node1.example.com


With this example the node directory is
``/tmp/vcluster/node1.example.com`` and the cluster directory
``/tmp/vcluster``.


.. _vcluster-setup:

Setup
-----

A script to configure virtual clusters is included with Ganeti as
``tools/vcluster-setup`` (usually installed as
``/usr/lib/ganeti/tools/vcluster-setup``). Running it with the ``-h``
option prints a usage description. The script creates all necessary
directories, configures network interfaces, adds or updates entries in
``/etc/hosts`` and generates a small number of helper scripts.

.. TODO: Describe setup of non-root virtual cluster


Use
---

Once the virtual cluster has been :ref:`set up <vcluster-setup>`, the
cluster can be initialized. The instructions for doing so have been
printed by the ``vcluster-setup`` script together with other useful
information, such as the list of virtual nodes. The commands printed
should be used to configure the list of enabled hypervisors and other
settings.

To run commands for a specific virtual node, the script named ``cmd``
located in the node directory can be used. It takes a command as its
argument(s), sets the environment variables ``GANETI_ROOTDIR`` and
``GANETI_HOSTNAME`` and then runs the command. Example:

.. highlight:: shell-example

::

  # Let's create a cluster with node1 as its master node
  $ cd /tmp/vcluster
  $ node1.example.com/cmd gnt-cluster info
  Cluster name: cluster.example.com
  …
  Master node: node1.example.com
  …
  # Configure cluster as per "vcluster-setup" script
  $ node1.example.com/cmd gnt-cluster modify …

Scripts are provided in the cluster root directory to start, stop or
restart all daemons for all virtual nodes. These are named
``start-all``, ``stop-all`` and ``restart-all``. ``ganeti-watcher`` can
be run for all virtual nodes using ``watcher-all``.

Adding an instance (assuming node1.example.com is the master node as per
the example above):

.. highlight:: shell-example

::

  $ node1.example.com/cmd gnt-instance add --os-size 1G \
    --disk-template=file --os-type dummy -B memory=192 -I hail \
    instance1.example.com

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
