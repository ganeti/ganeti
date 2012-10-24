====================
Linux HA integration
====================

.. contents:: :depth: 4

This is a design document detailing the integration of Ganeti and Linux HA.


Current state and shortcomings
==============================

Ganeti doesn't currently support any self-healing or self-monitoring.

We are now working on trying to improve the situation in this regard:

- The :doc:`autorepair system <design-autorepair>` will take care
  of self repairing a cluster in the presence of offline nodes.
- The :doc:`monitoring agent <design-monitoring-agent>` will take care
  of exporting data to monitoring.

What is still missing is a way to self-detect "obvious" failures rapidly
and to:

- Maintain the master role active.
- Offline resource that are obviously faulty so that the autorepair
  system can perform its work.


Proposed changes
================

Linux-HA provides software that can be used to provide high availability
of services through automatic failover of resources. In particular
Pacemaker can be used together with Heartbeat or Corosync to make sure a
resource is kept active on a self-monitoring cluster.

Ganeti OCF agents
-----------------

The Ganeti agents will be slightly special in the HA world. The
following will apply:

- The agents will be able to be configured cluster-wise by tags (which
  will be read on the nodes via ssconf_cluster_tags) and locally by
  files on the filesystem that will allow them to "simulate" a
  particular condition (eg. simulate a failure even if none is
  detected).
- The agents will be able to run in "full" or "partial" mode: in
  "partial" mode they will always succeed, and thus never fail a
  resource as long as a node is online, is running the linux HA software
  and is responding to the network. In "full" mode they will also check
  resources like the cluster master ip or master daemon, and act if they
  are missing

Note that for what Ganeti does OCF agents are needed: simply relying on
the LSB scripts will not work for the Ganeti service.


Master role agent
-----------------

This agent will manage the Ganeti master role. It needs to be configured
as a sticky resource (you don't want to flap the master role around, do
you?) that is active on only one node. You can require quorum or fencing
to protect your cluster from multiple masters.

The agent will implement a stateless resource that considers itself
"started" only the master node, "stopped" on all master candidates and
in error mode for all other nodes.

Note that if not all your nodes are master candidates this resource
might have problems:

- if all nodes are configured to run the resource, heartbeat may decide
  to "fence" (aka stonith) all your non-master-candidate nodes if told
  to do so. This might not be what you want.
- if only master candidates are configured as nodes for the resource,
  beware of promotions and demotions, as nothing will update
  automatically pacemaker should a change happen at the Ganeti level.

Other solutions, such as reporting the resource just as "stopped" on non
master candidates as well might mean that pacemaker would choose the
"wrong" node to promote to master, which is also a bad idea.

Future improvements
+++++++++++++++++++

- Ability to work better with non-master-candidate nodes
- Stateful resource that can "safely" transfer the master role between
  online nodes (with queue drain and such)
- Implement "full" mode, with detection of the cluster IP and the master
  node daemon.


Node role agent
---------------

This agent will manage the Ganeti node role. It needs to be configured
as a cloned resource that is active on all nodes.

In partial mode it will always return success (and thus trigger a
failure only upon an HA level or network failure). Full mode, which
initially will not be implemented, couls also check for the node daemon
being unresponsive or other local conditions (TBD).

When a failure happens the HA notification system will trigger on all
other nodes, including the master. The master will then be able to
offline the node. Any other work to restore instance availability should
then be done by the autorepair system.

The following cluster tags are supported:

- ``ocf:node-offline:use-powercycle``: Try to powercycle a node using
  ``gnt-node powercycle`` when offlining.
- ``ocf:node-offline:use-poweroff``: Try to power off a node using
  ``gnt-node power off`` when offlining (requires OOB support).

Future improvements
+++++++++++++++++++

- Handle draining differently than offlining
- Handle different modes of "stopping" the service
- Implement "full" mode


Risks
-----

Running Ganeti with Pacemaker increases the risk of stability for your
Ganeti Cluster. Events like:

- stopping heartbeat or corosync on a node
- corosync or heartbeat being killed for any reason
- temporary failure in a node's networking

will trigger potentially dangerous operations such as node offlining or
master role failover. Moreover if the autorepair system will be working
they will be able to also trigger instance failovers or migrations, and
disk replaces.

Also note that operations like: master-failover, or manual node-modify
might interact badly with this setup depending on the way your HA system
is configured (see below).

This of course is an inherent problem with any Linux-HA installation,
but is probably more visible with Ganeti given that our resources tend
to be more heavyweight than many others managed in HA clusters (eg. an
IP address).

Code status
-----------

This code is heavily experimental, and Linux-HA is a very complex
subsystem. *We might not be able to help you* if you decide to run this
code: please make sure you understand fully high availability on your
production machines. Ganeti only ships this code as an example but it
might need customization or complex configurations on your side for it
to run properly.

*Ganeti does not automate HA configuration for your cluster*. You need
to do this job by hand. Good luck, don't get it wrong.


Future work
===========

- Integrate the agents better with the ganeti monitoring
- Add hooks for managing HA at node add/remove/modify/master-failover
  operations
- Provide a stonith system through Ganeti's OOB system
- Provide an OOB system that does "shunning" of offline nodes, for
  emulating a real OOB, at least on all nodes

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
