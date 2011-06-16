==================
Network management
==================

.. contents:: :depth: 4

This is a design document detailing the implementation of network resource
management in Ganeti.

Current state and shortcomings
==============================

Currently Ganeti supports two configuration modes for instance NICs:
routed and bridged mode. The ``ip`` NIC parameter, which is mandatory
for routed NICs and optional for bridged ones, holds the given NIC's IP
address and may be filled either manually, or via a DNS lookup for the
instance's hostname.

This approach presents some shortcomings:

a) It relies on external systems to perform network resource
   management. Although large organizations may already have IP pool
   management software in place, this is not usually the case with
   stand-alone deployments. For smaller installations it makes sense to
   allocate a pool of IP addresses to Ganeti and let it transparently
   assign these IPs to instances as appropriate.

b) The NIC network information is incomplete, lacking netmask and
   gateway.  Operating system providers could for example use the
   complete network information to fully configure an instance's
   network parameters upon its creation.

   Furthermore, having full network configuration information would
   enable Ganeti nodes to become more self-contained and be able to
   infer system configuration (e.g. /etc/network/interfaces content)
   from Ganeti configuration. This should make configuration of
   newly-added nodes a lot easier and less dependant on external
   tools/procedures.

c) Instance placement must explicitly take network availability in
   different node groups into account; the same ``link`` is implicitly
   expected to connect to the same network across the whole cluster,
   which may not always be the case with large clusters with multiple
   node groups.


Proposed changes
----------------

In order to deal with the above shortcomings, we propose to extend
Ganeti with high-level network management logic, which consists of a new
NIC mode called ``managed``, a new "Network" configuration object and
logic to perform IP address pool management, i.e. maintain a set of
available and occupied IP addresses.

Configuration changes
+++++++++++++++++++++

We propose the introduction of a new high-level Network object,
containing (at least) the following data:

- Symbolic name
- UUID
- Network in CIDR notation (IPv4 + IPv6)
- Default gateway, if one exists (IPv4 + IPv6)
- IP pool management data (reservations)
- Default NIC connectivity mode (bridged, routed). This is the
  functional equivalent of the current NIC ``mode``.
- Default host interface (e.g. br0). This is the functional equivalent
  of the current NIC ``link``.
- Tags

Each network will be connected to any number of node groups, possibly
overriding connectivity mode and host interface for each node group.
This is achieved by adding a ``networks`` slot to the NodeGroup object
and using the networks' UUIDs as keys.

IP pool management
++++++++++++++++++

A new helper library is introduced, wrapping around Network objects to
give IP pool management capabilities. A network's pool is defined by two
bitfields, the length of the network size each:

``reservations``
  This field holds all IP addresses reserved by Ganeti instances, as
  well as cluster IP addresses (node addresses + cluster master)

``external reservations``
  This field holds all IP addresses that are manually reserved by the
  administrator, because some other equipment is using them outside the
  scope of Ganeti.

The bitfields are implemented using the python-bitarray package for
space efficiency and their binary value stored base64-encoded for JSON
compatibility. This approach gives relatively compact representations
even for large IPv4 networks (e.g. /20).

Ganeti-owned IP addresses (node + master IPs) are reserved automatically
if the cluster's data network itself is placed under pool management.

Helper ConfigWriter methods provide free IP address generation and
reservation, using a TemporaryReservationManager.

It should be noted that IP pool management is performed only for IPv4
networks, as they are expected to be densely populated. IPv6 networks
can use different approaches, e.g. sequential address asignment or
EUI-64 addresses.

Managed NIC mode
++++++++++++++++

In order to be able to use the new network facility while maintaining
compatibility with the current networking model, a new network mode is
introduced, called ``managed`` to reflect the fact that the given NICs
network configuration is managed by Ganeti itself. A managed mode NIC
accepts the network it is connected to in its ``link`` argument.
Userspace tools can refer to networks using their symbolic names,
however internally, the link argument stores the network's UUID.

We also introduce a new ``ip`` address value, ``constants.NIC_IP_POOL``,
that specifies that a given NIC's IP address should be obtained using
the IP address pool of the specified network. This value is only valid
for managed-mode NICs, where it is also used as a default instead of
``constants.VALUE_AUTO``. A managed-mode NIC's IP address can also be
specified manually, as long as it is compatible with the network the NIC
is connected to.


Hooks
+++++

``OP_NETWORK_ADD``
  Add a network to Ganeti

  :directory: network-add
  :pre-execution: master node
  :post-execution: master node

``OP_NETWORK_CONNECT``
  Connect a network to a node group. This hook can be used to e.g.
  configure network interfaces on the group's nodes.

  :directory: network-connect
  :pre-execution: master node, all nodes in the connected group
  :post-execution: master node, all nodes in the connected group

``OP_NETWORK_DISCONNECT``
  Disconnect a network to a node group. This hook can be used to e.g.
  deconfigure network interfaces on the group's nodes.

  :directory: network-disconnect
  :pre-execution: master node, all nodes in the connected group
  :post-execution: master node, all nodes in the connected group

``OP_NETWORK_REMOVE``
  Remove a network from Ganeti

  :directory: network-add
  :pre-execution: master node, all nodes
  :post-execution: master node, all nodes

Hook variables
^^^^^^^^^^^^^^

``INSTANCE_NICn_MANAGED``
  Non-zero if NIC n is a managed-mode NIC

``INSTANCE_NICn_NETWORK``
  The friendly name of the network

``INSTANCE_NICn_NETWORK_UUID``
  The network's UUID

``INSTANCE_NICn_NETWORK_TAGS``
  The network's tags

``INSTANCE_NICn_NETWORK_IPV4_CIDR``, ``INSTANCE_NICn_NETWORK_IPV6_CIDR``
  The subnet in CIDR notation

``INSTANCE_NICn_NETWORK_IPV4_GATEWAY``, ``INSTANCE_NICn_NETWORK_IPV6_GATEWAY``
  The subnet's default gateway


Backend changes
+++++++++++++++

In order to keep the hypervisor-visible changes to a minimum, and
maintain compatibility with the existing network configuration scripts,
the instance's hypervisor configuration will have host-level link and
mode replaced by the *connectivity mode* and *host interface* of the
given network on the current node group.

The managed mode can be detected by the presence of new environment
variables in network configuration scripts:

Network configuration script variables
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``MANAGED``
  Non-zero if NIC is a managed-mode NIC

``NETWORK``
  The friendly name of the network

``NETWORK_UUID``
  The network's UUID

``NETWORK_TAGS``
  The network's tags

``NETWORK_IPv4_CIDR``, ``NETWORK_IPv6_CIDR``
  The subnet in CIDR notation

``NETWORK_IPV4_GATEWAY``, ``NETWORK_IPV6_GATEWAY``
  The subnet's default gateway

Userland interface
++++++++++++++++++

A new client script is introduced, ``gnt-network``, which handles
network-related configuration in Ganeti.

Network addition/deletion
^^^^^^^^^^^^^^^^^^^^^^^^^
::

 gnt-network add --cidr=192.0.2.0/24 --gateway=192.0.2.1 \
                --cidr6=2001:db8:2ffc::/64 --gateway6=2001:db8:2ffc::1 \
                --nic_connectivity=bridged --host_interface=br0 public
 gnt-network remove public (only allowed if no instances are using the network)

Manual IP address reservation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
::

 gnt-network reserve-ips public 192.0.2.2 192.0.2.10-192.0.2.20
 gnt-network release-ips public 192.0.2.3


Network modification
^^^^^^^^^^^^^^^^^^^^
::

 gnt-network modify --cidr=192.0.2.0/25 public (only allowed if all current reservations fit in the new network)
 gnt-network modify --gateway=192.0.2.126 public
 gnt-network modify --host_interface=test --nic_connectivity=routed public (issues warning about instances that need to be rebooted)
 gnt-network rename public public2


Assignment to node groups
^^^^^^^^^^^^^^^^^^^^^^^^^
::

 gnt-network connect public nodegroup1
 gnt-network connect --host_interface=br1 public nodegroup2
 gnt-network disconnect public nodegroup1 (only permitted if no instances are currently using this network in the group)

Tagging
^^^^^^^
::

 gnt-network add-tags public foo bar:baz

Network listing
^^^^^^^^^^^^^^^
::

 gnt-network list
  Name		IPv4 Network	IPv4 Gateway	      IPv6 Network	       IPv6 Gateway		Connected to
  public	 192.0.2.0/24	192.0.2.1	2001:db8:dead:beef::/64	   2001:db8:dead:beef::1       nodegroup1:br0
  private	 10.0.1.0/24	   -			 -				-

Network information
^^^^^^^^^^^^^^^^^^^
::

 gnt-network info public
  Name: public
  IPv4 Network: 192.0.2.0/24
  IPv4 Gateway: 192.0.2.1
  IPv6 Network: 2001:db8:dead:beef::/64
  IPv6 Gateway: 2001:db8:dead:beef::1
  Total IPv4 count: 256
  Free address count: 201 (80% free)
  IPv4 pool status: XXX.........XXXXXXXXXXXXXX...XX.............
                    XXX..........XXX...........................X
                    ....XXX..........XXX.....................XXX
                                            X: occupied  .: free
  Externally reserved IPv4 addresses:
    192.0.2.3, 192.0.2.22
  Connected to node groups:
   default (link br0), other_group(link br1)
  Used by 22 instances:
   inst1
   inst2
   inst32
   ..


IAllocator changes
++++++++++++++++++

The IAllocator protocol can be made network-aware, i.e. also consider
network availability for node group selection. Networks, as well as
future shared storage pools, can be seen as constraints used to rule out
the placement on certain node groups.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
